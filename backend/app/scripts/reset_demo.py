"""Clean test leftovers out of the demo accounts (physio brief 2026-11-09 P0.12).

    ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo            # dry run: lists what it would do
    ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo --apply    # does it
    ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo --recreate --apply   # demo-only database: drop and reseed
    … --extra conclusions=47,48 --extra injury_reports=189 --extra bookings=95 --extra rtr=1 --extra slots=93
      --extra messages_from=240 --extra revisions_from=48 --extra release=<triage id>

It touches only demo runners (an @demo.cz login or the tour runner) and the demo physio's slots; one
target that belongs to anyone else aborts the whole run before anything changes. Running it twice gives
the same state. It restores what the seed defines (prior injury, programme order) and removes:
anything containing "TEST (Claude)", the rows named with --extra, and the demo physio's past open slots.
Never point it at production health data of real users — the guard refuses non-demo rows, but the
decision to run it on an environment is the owner's.

Round 2 F8: it also removes the round-2 test data (texts marked "TEST (Claude)" or "TEST Claude", the marked
service, limit, patient-card fields and provider name), return-to-run sessions logged inside the rest gap of the
previous one, notes approved before their visit, a demo physio's claim of a runner the seed never assigned, and
writes the seeded physio's messages in her grammatical gender. Clinical records are append-only (R5.7): the
in-place run never touches them and never disables the triggers; `--recreate` drops and reseeds the whole
database, and refuses unless every runner in it is a demo runner and the environment is not production.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from .. import models
from ..assistant.service import is_demo
from ..db import SessionLocal
from ..metrics import engine as E

MARK = "TEST (Claude)"
MARKS = ("TEST (Claude)", "TEST Claude", "TEST Fyzio")       # round 2 Appendix A
FEMININE = {"Sdílel jsem": "Sdílela jsem", "Potvrdil jsem": "Potvrdila jsem", "Upravil(a) jsem": "Upravila jsem",
            "Poslal jsem": "Poslala jsem", "Nastavil jsem": "Nastavila jsem", "Snížil jsem": "Snížila jsem"}
SEED_PROFILE = {"run-0001": {"birth_year": 1991, "sex": "f"}}


def _marked(*texts) -> bool:
    t = " ".join(x for x in texts if isinstance(x, str))
    return any(m in t for m in MARKS)
DEMO_PHYSIO = "phy-0001"


class Refused(Exception):
    pass


def _ids(v: str) -> list[int]:
    return [int(x) for x in v.split(",") if x.strip()]


def plan(db, extra: dict[str, str]) -> list[tuple[str, object]]:
    """Every change as (description, action). Raises Refused when a target is not demo data."""
    demo = {r.id for r in db.query(models.Runner).all() if is_demo(db, r.id)}
    out: list[tuple[str, object]] = []

    def own(rid: str, what: str):
        if rid not in demo:
            raise Refused(f"{what} patří běžci {rid}, který není demo účet — nic se nezměnilo.")

    def drop(row, what):
        own(row.runner_id, what)
        out.append((f"smazat {what}", lambda r=row: db.delete(r)))

    for m in db.query(models.Message).filter(models.Message.body.contains(MARK)).all():
        drop(m, f"zprávu {m.id}")
    for c in db.query(models.Conclusion).all():
        if MARK in " ".join(filter(None, (c.summary, c.finding, c.transcript))):
            drop(c, f"záznam z návštěvy {c.id}")
    for rv in db.query(models.ProgramRevision).filter(models.ProgramRevision.note.contains(MARK)).all():
        p = db.get(models.Program, rv.program_id)
        own(p.runner_id, f"revize {rv.id}")
        out.append((f"smazat revizi programu {rv.id}", lambda r=rv: db.delete(r)))
    for key, model in (("conclusions", models.Conclusion), ("injury_reports", models.InjuryReport),
                       ("bookings", models.Booking)):
        for i in _ids(extra.get(key, "")):
            row = db.get(model, i)
            if row is not None:
                drop(row, f"{key} {i}")
    for i in _ids(extra.get("rtr", "")):
        plan_row = db.get(models.ReturnToRun, i)
        if plan_row is not None:
            own(plan_row.runner_id, f"plán návratu {i}")
            for s in db.query(models.RtrSession).filter(models.RtrSession.plan_id == i).all():
                out.append((f"smazat sezení {s.id} plánu {i}", lambda r=s: db.delete(r)))
            out.append((f"smazat plán návratu {i}", lambda r=plan_row: db.delete(r)))
    for i in _ids(extra.get("slots", "")):
        sl = db.get(models.PhysioSlot, i)
        if sl is not None:
            if sl.physio_id != DEMO_PHYSIO:
                raise Refused(f"Termín {i} nepatří demo fyzioterapeutce — nic se nezměnilo.")
            out.append((f"smazat termín {i}", lambda r=sl: db.delete(r)))
    if extra.get("messages_from"):
        start = int(extra["messages_from"])
        for m in db.query(models.Message).filter(models.Message.id >= start, models.Message.runner_id == "run-0001").all():
            drop(m, f"zprávu {m.id}")
    if extra.get("revisions_from"):
        start = int(extra["revisions_from"])
        for rv in db.query(models.ProgramRevision).filter(models.ProgramRevision.id >= start).all():
            p = db.get(models.Program, rv.program_id)
            if p and p.runner_id == "run-0001":
                out.append((f"smazat revizi programu {rv.id}", lambda r=rv: db.delete(r)))
    for i in _ids(extra.get("release", "")):
        t = db.get(models.Triage, i)
        if t is not None and t.claimed_by:
            own(t.runner_id, f"převzetí případu {i}")

            def rel(t=t):
                ca = db.query(models.CareAssignment).filter_by(physio_id=t.claimed_by, runner_id=t.runner_id).first()
                if ca:
                    db.delete(ca)
                t.claimed_by, t.status = None, "open"
            out.append((f"vrátit případ {i} do fronty", rel))
    now = datetime.now(timezone.utc)
    for sl in db.query(models.PhysioSlot).filter(models.PhysioSlot.physio_id == DEMO_PHYSIO,
                                                 models.PhysioSlot.status == "open").all():
        try:
            past = datetime.fromisoformat(sl.slot_at).replace(tzinfo=datetime.fromisoformat(sl.slot_at).tzinfo or timezone.utc) < now
        except ValueError:
            past = True
        if past:
            out.append((f"smazat prošlý volný termín {sl.id}", lambda r=sl: db.delete(r)))
    # ---- round 2 F8 ------------------------------------------------------------------------------------------
    for sv in db.query(models.Service).filter_by(physio_id=DEMO_PHYSIO).all():
        if _marked(sv.name_cs):
            out.append((f"smazat službu {sv.id} ({sv.name_cs})", lambda r=sv: db.delete(r)))
    for lim in db.query(models.ClinicalLimit).all():
        if _marked(lim.reason_cs):
            own(lim.runner_id, f"omezení {lim.id}")
            out.append((f"smazat omezení tréninku {lim.id}", lambda r=lim: db.delete(r)))
    for v in db.query(models.ProgramVersion).all():
        if _marked(v.note):
            pr = db.get(models.Program, v.program_id)
            own(pr.runner_id, f"verze programu {v.id}")
            out.append((f"smazat verzi programu {v.id}", lambda r=v: db.delete(r)))
    for card in db.query(models.PatientRecord).all():
        fields = [f for f in ("permanent_street", "permanent_city", "anamnesis", "gp_name", "phone") if _marked(getattr(card, f))]
        if fields and card.runner_id:
            own(card.runner_id, f"karta klienta {card.id}")

            def clean(c=card, fs=fields):
                for f in fs:
                    setattr(c, f, None)
            out.append((f"vyčistit kartu klienta {card.id} ({', '.join(fields)})", clean))
    clinic = None
    ph0 = db.get(models.Physio, DEMO_PHYSIO)
    if ph0 is not None and ph0.clinic_id:
        clinic = db.get(models.Clinic, ph0.clinic_id)
    if clinic is not None and (_marked(clinic.legal_name) or clinic.ico == "12345678"):
        def provider(c=clinic):
            c.legal_name, c.legal_form, c.ico = "Fyzio Holešovice (ukázková praxe)", "s.r.o.", "00000000"
        out.append(("obnovit údaje poskytovatele z ukázky", provider))
    for b in db.query(models.Booking).all():
        if _marked(b.reason, b.questions, b.cancel_reason):
            drop(b, f"rezervaci {b.id}")
    # return-to-run sessions logged inside the previous one's rest gap (round 1: three within a minute)
    from .. import care_view as CV
    for pl in db.query(models.ReturnToRun).all():
        if pl.runner_id not in demo:
            continue
        prev = None
        for ss in (db.query(models.RtrSession).filter_by(plan_id=pl.id).order_by(models.RtrSession.logged_at).all()):
            if ss.count_reason == "pain_report":
                continue
            if prev is not None and ss.counted:
                try:
                    gap = (datetime.fromisoformat(ss.logged_at) - datetime.fromisoformat(prev.logged_at)).total_seconds() / 3600
                except (TypeError, ValueError):
                    gap = None
                if gap is not None and gap < CV.MIN_HOURS_BETWEEN_SESSIONS:
                    out.append((f"smazat sezení {ss.id} (do {CV.MIN_HOURS_BETWEEN_SESSIONS} h po předchozím)",
                                lambda r=ss: db.delete(r)))
                    continue
            prev = ss
    # a note approved before its visit (round 1: conclusion 48) — the ledger row, if any, stays (append-only)
    for c in db.query(models.Conclusion).filter_by(status="approved").all():
        bk = db.get(models.Booking, c.booking_id) if c.booking_id else None
        if bk and bk.slot_at and c.approved_at and c.runner_id in demo:
            try:
                early = datetime.fromisoformat(c.approved_at) < datetime.fromisoformat(bk.slot_at)
            except ValueError:
                early = False
            if early:
                drop(c, f"záznam {c.id} schválený před návštěvou")
    # the seeded physio writes in her grammatical gender
    for m in db.query(models.Message).filter(models.Message.physio_id == DEMO_PHYSIO,
                                             models.Message.sender.in_(("physio", "system"))).all():
        new_body = m.body or ""
        for a, b in FEMININE.items():
            new_body = new_body.replace(a, b)
        if new_body != (m.body or "") and m.runner_id in demo:
            out.append((f"zprávu {m.id} v ženském rodě", lambda r=m, t=new_body: setattr(r, "body", t)))
    # a claim the seed never made (round 1: Tomáš) goes back to the queue
    from ..tutorial_demo import TUTORIAL_RID
    seeded = {"run-0001", TUTORIAL_RID}
    for ca in db.query(models.CareAssignment).filter_by(physio_id=DEMO_PHYSIO, status="active").all():
        if ca.runner_id in demo and ca.runner_id not in seeded:
            t = db.query(models.Triage).filter_by(runner_id=ca.runner_id, claimed_by=DEMO_PHYSIO).first()

            def unclaim(ca=ca, t=t):
                db.delete(ca)
                if t is not None:
                    t.claimed_by, t.status = None, "open"
            out.append((f"vrátit klienta {ca.runner_id} do fronty (převzetí mimo seed)", unclaim))
    for rid, prof in SEED_PROFILE.items():
        rr = db.get(models.Runner, rid)
        if rr is not None and rid in demo and any(getattr(rr, k) != v for k, v in prof.items()):
            out.append((f"obnovit profil {rid} ze seedu ({prof})",
                        lambda r=rr, pr=prof: [setattr(r, k, v) for k, v in pr.items()]))
    # what the seed defines for Adéla
    r = db.get(models.Runner, "run-0001")
    if r is not None and "run-0001" in demo and (r.prior_injury, r.prior_injury_months_ago) != ("Achillova šlacha", 8):
        def restore(r=r):
            r.prior_injury, r.prior_injury_months_ago = "Achillova šlacha", 8
        out.append(("obnovit dřívější zranění Adély (Achillova šlacha, před 8 měsíci)", restore))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--extra", action="append", default=[], help="key=ids, e.g. conclusions=47,48")
    ap.add_argument("--recreate", action="store_true", help="demo-only database: drop every table and reseed")
    a = ap.parse_args(argv)
    if os.environ.get("ALLOW_DEMO_RESET") != "1":
        print("Odmítnuto: nastavte ALLOW_DEMO_RESET=1.", file=sys.stderr)
        return 2
    if a.recreate:
        return recreate(a.apply)
    extra = dict(x.split("=", 1) for x in a.extra)
    db = SessionLocal()
    try:
        try:
            steps = plan(db, extra)
        except Refused as e:
            print(f"Odmítnuto: {e}", file=sys.stderr)
            return 3
        for what, _ in steps:
            print(("" if a.apply else "[nanečisto] ") + what)
        if a.apply:
            for _, act in steps:
                act()
            db.commit()
            for rid in {"run-0001"}:
                E.recompute_assessment(db, rid)
        print(f"{len(steps)} změn" + ("" if a.apply else " (nic se nezměnilo, přidejte --apply)"))
        return 0
    finally:
        db.close()


def recreate(apply: bool) -> int:
    """Round 2 F8.2 (R5.7): the demo-only path for the append-only ledger — drop and reseed the whole database.
    Refused on production and on any database holding a runner that is not a demo runner."""
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production":
        print("Odmítnuto: --recreate nikdy na produkci.", file=sys.stderr)
        return 3
    from .. import seed as S0
    db = SessionLocal()
    try:
        # synthetic seed runners have no login; a runner owned by a non-demo login is a real person
        real = [r.id for r in db.query(models.Runner).all() if S0._has_real_account(db, r.id)]
        real += [u.email for u in db.query(models.User).filter(models.User.runner_id.is_(None),
                                                                models.User.role == "runner").all()
                 if not S0._is_demo_email(u.email)]
    finally:
        db.close()
    if real:
        print(f"Odmítnuto: databáze obsahuje {len(real)} účtů, které nejsou demo — nic se nezměnilo.", file=sys.stderr)
        return 3
    if not apply:
        print("[nanečisto] smazat všechny tabulky a znovu nasadit ukázková data")
        return 0
    from .. import seed as S
    from ..db import Base, engine
    from ..main import _ledger_guard, _migrate
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _migrate(engine)
    _ledger_guard(engine)
    db = SessionLocal()
    try:
        S.build_and_seed(db)
        S.ensure_demo_accounts(db)
        from . import backfill_round2
        backfill_round2.run(db)          # the seeded older notes enter the record, as on production (F2)
    finally:
        db.close()
    print("Databáze je znovu nasazená z ukázkových dat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
