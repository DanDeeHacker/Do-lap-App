"""Physio triage queue — region-scoped by default (a physio sees the cases
in their own clinic's region, not every case on the platform), with an
explicit `scope=all` opt-in for overflow/backup cover. Region is derived
from the city string (clinics are "Praha 7"/"Praha 5", runners "Praha", so
an exact city match wouldn't group them — the first token is the region).
A physio with no clinic on file (e.g. a freshly self-registered account)
falls back to seeing everything, so onboarding isn't a dead queue.

Claiming a case creates the care_assignments row that then gates every read
of that patient.
"""
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import or_404, require_role, verify_csrf
from ..metrics import engine as E
from ..serializers import to_dict

router = APIRouter(prefix="/api/triage", tags=["triage"])


def _region(city: str | None) -> str | None:
    if not city:
        return None
    return re.split(r"[\s\-]+", city.strip())[0].lower() or None


def _physio_region(db: DBSession, physio_id: str) -> str | None:
    physio = db.query(models.Physio).filter(models.Physio.id == physio_id).first()
    if not physio or not physio.clinic_id:
        return None
    clinic = db.query(models.Clinic).filter(models.Clinic.id == physio.clinic_id).first()
    return _region(clinic.city) if clinic else None


@router.get("")
def queue(status: str = "open", scope: str = "clinic",
          user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    physio_region = _physio_region(db, user.physio_id)
    q = db.query(models.Triage)
    if status and status != "all":
        q = q.filter(models.Triage.status != "closed") if status == "open" else q.filter(models.Triage.status == status)
    rows = q.all()
    out = []
    for t in rows:
        r = db.query(models.Runner).filter(models.Runner.id == t.runner_id).first()
        # consent gate: a runner is invisible to physios until they opt into
        # the service — unless a physio already has them in active care.
        if not (r and r.physio_interest) and t.claimed_by != user.physio_id:
            continue
        rreg = _region(r.city if r else None)
        in_region = physio_region is None or rreg == physio_region
        if not in_region and scope != "all":
            continue
        a_row = db.query(models.Assessment).filter(models.Assessment.runner_id == t.runner_id).first()
        a = E.assessment_row_to_dict(a_row) if a_row else E.recompute_assessment(db, t.runner_id)
        item = to_dict(t)
        item["runner"] = to_dict(r)
        item["a"] = a
        item["region"] = rreg
        item["in_region"] = in_region
        out.append(item)
    out.sort(key=lambda x: -(x["a"]["overall"] if x.get("a") else 0))
    return out


@router.patch("/{tid}/claim", dependencies=[Depends(verify_csrf)])
def claim(tid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    t = or_404(db.query(models.Triage).filter(models.Triage.id == tid).first(), "Případ nenalezen")
    t.status = "claimed"
    t.claimed_by = user.physio_id
    existing = (
        db.query(models.CareAssignment)
        .filter(models.CareAssignment.physio_id == user.physio_id, models.CareAssignment.runner_id == t.runner_id)
        .first()
    )
    if not existing:
        db.add(models.CareAssignment(
            physio_id=user.physio_id, runner_id=t.runner_id, status="active", created_at=E.now_iso(),
        ))
    elif existing.status != "active":
        existing.status = "active"
    db.add(models.Message(
        runner_id=t.runner_id, physio_id=user.physio_id, sender="system",
        body="Fyzioterapeut převzal váš případ.", created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(t)
    return to_dict(t)
