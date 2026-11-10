"""Bring the approved visit notes written before the ledger into the record (physio brief round 2 F2,
completes R3.2, R5.6 and P0.6.7). One idempotent run, guarded by a row in `migrations_applied`:

1. a patient card for every runner–physio pair with an approved note and no card — first and last name from
   the runner profile only, `incomplete = 1`; birth date, sex at birth and address stay empty (never invented);
2. a care episode per pair, opened at the earliest booking, programme or note, linking the pair's bookings,
   programmes, return-to-run plans, notes and injury reports that have none;
3. a `visit_note` ledger row for every approved note without one — `legacy: true`, encounter = the visit,
   authorised = the approval time, inserted in ascending approval time through `records.write_record`, the
   same function approval uses;
4. a note approved before its visit is still recorded (it exists and was shared) with the flag
   `approved_before_encounter`, and listed for the provider — never hidden or deleted;
5. past confirmed visits with an approved note become `completed`.

    python -m app.scripts.backfill_round2 --dry-run   # counts per table, nothing written
    python -m app.scripts.backfill_round2             # writes, prints the new ids, then verifies the ledger
    python -m app.scripts.backfill_round2 --force     # run again even if the guard row exists (still idempotent)
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

from .. import models
from .. import records as R
from ..db import SessionLocal
from ..metrics import engine as E
from ..routers.conclusions import record_content

NAME = "backfill_round2"


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _earliest(*vals):
    xs = [v for v in vals if v]
    return min(xs, key=_dt) if xs else None


def run(db, dry_run: bool = False, force: bool = False) -> dict:
    """The whole backfill in the caller's session; commits unless dry_run. Returns what it did."""
    out = {"skipped": False, "counts": Counter(), "records": [], "flagged": [], "cards": [], "episodes": []}
    if not force and db.get(models.MigrationApplied, NAME) is not None:
        out["skipped"] = True
        return out
    now = E.now_iso()
    notes = (db.query(models.Conclusion).filter(models.Conclusion.status == "approved")
             .order_by(models.Conclusion.approved_at.asc(), models.Conclusion.id.asc()).all())
    pairs = sorted({(c.runner_id, c.physio_id) for c in notes})
    eps: dict[tuple[str, str], models.CareEpisode] = {}
    cards: dict[tuple[str, str], models.PatientRecord] = {}
    for rid, pid in pairs:
        physio = db.get(models.Physio, pid)
        if physio is None:
            continue
        clinic = R.clinic_of(db, physio)
        # 1. the card
        card = R.card(db, clinic.id, rid)
        if card is None:
            r = db.get(models.Runner, rid)
            first, last = R._split_name(r.name if r else "")
            card = models.PatientRecord(id=R.new_record_id(), clinic_id=clinic.id, runner_id=rid,
                                        first_name=first or "neuvedeno", last_name=last or "neuvedeno",
                                        incomplete=1, created_at=now, updated_at=now)
            db.add(card)
            db.flush()
            out["counts"]["patient_records"] += 1
            out["cards"].append(card.id)
        cards[(rid, pid)] = card
        # 2. the episode: the pair's earliest one, or a new one
        bks = db.query(models.Booking).filter_by(runner_id=rid, physio_id=pid).all()
        progs = db.query(models.Program).filter_by(runner_id=rid, physio_id=pid).all()
        plans = db.query(models.ReturnToRun).filter_by(runner_id=rid, physio_id=pid).all()
        mine = [c for c in notes if c.runner_id == rid and c.physio_id == pid]
        injuries = db.query(models.InjuryReport).filter_by(runner_id=rid, physio_id=pid).all()
        first_at = _earliest(*(b.slot_at for b in bks if b.status in ("confirmed", "completed")),
                             *(x.sent_at or x.started_on for x in progs), *(x.created_at for x in plans),
                             *(c.approved_at for c in mine))
        ep = (db.query(models.CareEpisode).filter_by(runner_id=rid, physio_id=pid)
              .order_by(models.CareEpisode.opened_at.asc(), models.CareEpisode.id.asc()).first())
        if ep is None:
            ep = models.CareEpisode(clinic_id=clinic.id, physio_id=pid, runner_id=rid, patient_record_id=card.id,
                                    opened_at=first_at or now, status="open")
            db.add(ep)
            db.flush()
            out["counts"]["care_episodes"] += 1
            out["episodes"].append(ep.id)
        else:
            if first_at and (not ep.opened_at or _dt(first_at) < _dt(ep.opened_at)):
                ep.opened_at = first_at                 # the care began before the first new approval
            ep.patient_record_id = ep.patient_record_id or card.id
        eps[(rid, pid)] = ep
        for table, rows in (("bookings", bks), ("programs", progs), ("return_to_run", plans),
                            ("conclusions", mine), ("injury_reports", injuries)):
            for x in rows:
                if getattr(x, "episode_id", None) is None and hasattr(x, "episode_id"):
                    x.episode_id = ep.id
                    out["counts"][f"{table}.episode_id"] += 1
    # 3–4. ledger rows in ascending approval time, through the one insert function
    for c in notes:
        if c.record_id or db.query(models.ClinicalRecord.id).filter_by(conclusion_id=c.id).first():
            continue
        physio = db.get(models.Physio, c.physio_id)
        card = cards.get((c.runner_id, c.physio_id))
        if physio is None or card is None:
            continue
        bk = db.get(models.Booking, c.booking_id) if c.booking_id else None
        encounter = bk.slot_at if bk and bk.slot_at else c.approved_at
        flags = []
        if bk and bk.slot_at and c.approved_at and _dt(c.approved_at) < _dt(bk.slot_at):
            flags.append("approved_before_encounter")
        ep = eps.get((c.runner_id, c.physio_id))
        rec = R.write_record(db, clinic=R.clinic_of(db, physio), patient=card, author=physio, kind="visit_note",
                             encounter_at=encounter, content=record_content(c, bk), booking_id=c.booking_id,
                             conclusion_id=c.id, episode_id=ep.id if ep else None, legacy=True,
                             authorised_at=c.approved_at, flags=flags)
        c.record_id = rec.id
        out["counts"]["clinical_records"] += 1
        out["records"].append(rec.id)
        if flags:
            out["flagged"].append({"record_id": rec.id, "conclusion_id": c.id, "runner_id": c.runner_id,
                                   "approved_at": c.approved_at, "visit_at": encounter})
    # 5. the visit took place
    now_dt = _dt(now)
    for c in notes:
        bk = db.get(models.Booking, c.booking_id) if c.booking_id else None
        if bk and bk.status == "confirmed" and bk.slot_at and _dt(bk.slot_at) < now_dt:
            bk.status = "completed"
            out["counts"]["bookings.completed"] += 1
    if dry_run:
        db.rollback()
        return out
    row = db.get(models.MigrationApplied, NAME)
    detail = {"counts": dict(out["counts"]), "flagged": out["flagged"]}
    if row is None:
        db.add(models.MigrationApplied(name=NAME, applied_at=now, detail=detail))
    else:
        row.applied_at, row.detail = now, detail
    db.commit()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    # run on its own (no server started on this database yet): the same additive schema step the app runs
    from ..db import Base, engine
    from ..main import _migrate
    Base.metadata.create_all(bind=engine)
    _migrate(engine)
    db = SessionLocal()
    try:
        res = run(db, dry_run=a.dry_run, force=a.force)
        if res["skipped"]:
            print(f"{NAME} už proběhl (migrations_applied). Nic se nemění; --force spustí kontrolu znovu.")
            return 0
        counts = res["counts"]
        print(("Zkušební běh — nic se nezapsalo." if a.dry_run else "Zapsáno.") + " Počty podle tabulek:")
        for k in sorted(counts):
            print(f"  {k}: {counts[k]}")
        if not counts:
            print("  nic k doplnění")
        if res["flagged"]:
            print("Záznamy schválené před začátkem návštěvy (pro poskytovatele ke kontrole):")
            for f in res["flagged"]:
                print(f"  záznam {f['record_id']} · klient {f['runner_id']} · schváleno {f['approved_at']} · návštěva {f['visit_at']}")
        if a.dry_run:
            return 0
        for rid in res["records"]:
            print(f"  nový záznam {rid}")
        v = R.verify(db)
        print(f"verify_records: {'OK' if v['ok'] else 'NESEDÍ'} ({v['checked']} záznamů)")
        return 0 if v["ok"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
