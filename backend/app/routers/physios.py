"""Physio-scoped bootstrap for the practitioner-level views (calendar,
programs, candidates) in physio.html — self only. The triage *queue* itself
stays on GET /api/triage (platform-wide, see triage.py); this covers what's
specifically "mine": my bookings, my programs, my claimed-but-not-yet-
programmed candidates.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/physios", tags=["physios"])


@router.get("/{pid}/bootstrap")
def bootstrap(pid: str, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if user.physio_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto profilu")
    physio = db.query(models.Physio).filter(models.Physio.id == pid).first()
    if not physio:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")

    def _with_runner_and_assessment(row, runner_id):
        out = to_dict(row)
        r = db.query(models.Runner).filter(models.Runner.id == runner_id).first()
        out["runner"] = to_dict(r)
        a = db.query(models.Assessment).filter(models.Assessment.runner_id == runner_id).first()
        out["assessment"] = E.assessment_row_to_dict(a)
        return out

    conclusions = db.query(models.Conclusion).filter(models.Conclusion.physio_id == pid).all()
    concl_by_booking = {c.booking_id: c for c in conclusions}

    bookings = db.query(models.Booking).filter(models.Booking.physio_id == pid).order_by(models.Booking.slot_at.asc()).all()
    bookings_out = []
    for b in bookings:
        item = _with_runner_and_assessment(b, b.runner_id)
        c = concl_by_booking.get(b.id)
        item["conclusion"] = to_dict(c) if c else None
        bookings_out.append(item)

    programs = db.query(models.Program).filter(models.Program.physio_id == pid).order_by(models.Program.id.desc()).all()
    programs_out = []
    for p in programs:
        item = _with_runner_and_assessment(p, p.runner_id)
        item["exercises"] = to_dicts(db.query(models.Exercise).filter(models.Exercise.program_id == p.id).all())
        item["revision_count"] = db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == p.id).count()
        programs_out.append(item)
    programmed_runner_ids = {p.runner_id for p in programs}

    triage_mine = (
        db.query(models.Triage).filter(models.Triage.claimed_by == pid, models.Triage.status != "closed").all()
    )
    triage_out = []
    for t in triage_mine:
        item = _with_runner_and_assessment(t, t.runner_id)
        ci = (
            db.query(models.Checkin).filter(models.Checkin.runner_id == t.runner_id)
            .order_by(models.Checkin.submitted_at.desc()).first()
        )
        item["checkin_latest"] = to_dict(ci)
        item["has_program"] = t.runner_id in programmed_runner_ids
        triage_out.append(item)

    requests = (
        db.query(models.Booking)
        .filter(models.Booking.physio_id == pid, models.Booking.status == "requested")
        .order_by(models.Booking.slot_at.asc()).all()
    )
    requests_out = [_with_runner_and_assessment(b, b.runner_id) for b in requests]
    slots = (
        db.query(models.PhysioSlot)
        .filter(models.PhysioSlot.physio_id == pid, models.PhysioSlot.slot_at > E.now_iso())
        .order_by(models.PhysioSlot.slot_at.asc()).all()
    )
    from ..routers.booking import due_reminders
    reminders = due_reminders(db, physio_id=pid)

    return {
        "physio": to_dict(physio), "bookings": bookings_out, "programs": programs_out, "triage_mine": triage_out,
        "requests": requests_out, "slots": to_dicts(slots), "reminders": reminders,
    }
