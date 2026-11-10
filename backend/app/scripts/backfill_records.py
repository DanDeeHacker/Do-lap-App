"""Copy approved visit records from before the ledger into it, once (physio brief R5.6). Idempotent: a
conclusion that already has its record_id is skipped. Rows are marked legacy=true; missing identity is
left empty, never invented — a card is created from the runner's name only, without birth date or address.

    python -m app.scripts.backfill_records            # dry run
    python -m app.scripts.backfill_records --apply
"""
from __future__ import annotations

import argparse

from .. import models
from .. import records as R
from ..db import SessionLocal
from ..routers.conclusions import record_content


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    n = 0
    try:
        rows = (db.query(models.Conclusion).filter(models.Conclusion.status == "approved", models.Conclusion.record_id.is_(None))
                .order_by(models.Conclusion.approved_at).all())
        for c in rows:
            physio = db.get(models.Physio, c.physio_id)
            if physio is None:
                continue
            clinic = R.clinic_of(db, physio)
            card = R.card(db, clinic.id, c.runner_id)
            if card is None:
                r = db.get(models.Runner, c.runner_id)
                first, last = R._split_name(r.name if r else "")
                card = models.PatientRecord(id=R.new_record_id(), clinic_id=clinic.id, runner_id=c.runner_id,
                                            first_name=first, last_name=last, created_at=c.approved_at)
                db.add(card)
                db.flush()
            bk = db.get(models.Booking, c.booking_id) if c.booking_id else None
            rec = R.write_record(db, clinic=clinic, patient=card, author=physio, kind="visit_note",
                                 encounter_at=(bk.slot_at if bk and bk.slot_at else c.approved_at),
                                 content=record_content(c, bk), booking_id=c.booking_id, conclusion_id=c.id, legacy=True)
            c.record_id = rec.id
            n += 1
        if a.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    print(f"{n} záznamů" + (" převedeno." if a.apply else " by se převedlo (přidejte --apply)."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
