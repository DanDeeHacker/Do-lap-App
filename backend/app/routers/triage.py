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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import care_view as CV, models, schemas
from ..db import get_db
from ..deps import or_404, require_verified_physio, verify_csrf
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


def _age_band(birth_year) -> str | None:
    if not birth_year:
        return None
    age = E.today_date().year - int(birth_year)
    lo = age // 10 * 10
    return f"{lo}–{lo + 9} let"


def _anonymous(t: models.Triage, r: models.Runner, a: dict, region: str | None, in_region: bool) -> dict:
    """An unclaimed case without the runner's name (physio brief 2026-11-09 P0.9): place, age band,
    urgency, the reason, the strongest signal and the last pain — enough to decide whether to take it."""
    sig = sorted((a or {}).get("signals") or [], key=lambda s: -(s.get("pts") or 0))
    keep = ("overall", "tier", "quadrant", "display_state", "display_label", "freshness", "lastPain", "painState")
    return {
        "id": t.id, "runner_id": t.runner_id, "decision": t.decision, "headline": t.headline, "status": t.status,
        "claimed_by": None, "created_at": t.created_at,
        "display_name": f"Klient · {r.city}" if r and r.city else "Klient",
        "city": r.city if r else None, "age_band": _age_band(r.birth_year if r else None), "sex": r.sex if r else None,
        "a": {**{k: (a or {}).get(k) for k in keep},
              "signals": [{k: s.get(k) for k in ("name", "grade", "val", "pts")} for s in sig[:1]]},
        "region": region, "in_region": in_region,
    }


@router.get("")
def queue(status: str = "open", scope: str = "clinic",
          user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    physio_region = _physio_region(db, user.physio_id)
    q = db.query(models.Triage)
    if status and status != "all":
        q = q.filter(models.Triage.status != "closed") if status == "open" else q.filter(models.Triage.status == status)
    rows = q.all()
    passed = {x.triage_id for x in db.query(models.TriagePass).filter(models.TriagePass.physio_id == user.physio_id).all()}
    out = []
    for t in rows:
        # physio brief 2026-11-09 P0.9: the queue holds only cases nobody claimed — someone else's case is
        # not shown at all and mine belong in Klienti; a case I passed on stays hidden for me
        if t.claimed_by or t.id in passed:
            continue
        r = db.query(models.Runner).filter(models.Runner.id == t.runner_id).first()
        # consent gate: a runner is invisible to physios until they opt into the service
        if not (r and r.physio_interest):
            continue
        rreg = _region(r.city if r else None)
        in_region = physio_region is None or rreg == physio_region
        if not in_region and scope != "all":
            continue
        a_row = db.query(models.Assessment).filter(models.Assessment.runner_id == t.runner_id).first()
        a = CV.present(db, t.runner_id, E.assessment_row_to_dict(a_row) if a_row else E.recompute_assessment(db, t.runner_id))
        out.append(_anonymous(t, r, a, rreg, in_region))
    # physio brief P0.3: no current data sorts after genuine risk, before low risk
    out.sort(key=lambda x: (CV.urgency(x.get("a") or {}), -((x.get("a") or {}).get("overall") or 0)))
    return out


@router.patch("/{tid}/claim", dependencies=[Depends(verify_csrf)])
def claim(tid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    t = or_404(db.query(models.Triage).filter(models.Triage.id == tid).first(), "Případ nenalezen")
    # review 2026-10-30 F1: a case is claimed once, while open, and only for a runner who asked for
    # a physio (the queue's consent gate) and hasn't declined this one
    if t.claimed_by and t.claimed_by != user.physio_id:
        raise HTTPException(status_code=409, detail="Případ už převzal jiný fyzioterapeut.")
    if t.status == "closed":
        raise HTTPException(status_code=409, detail="Případ je uzavřený.")
    r = db.query(models.Runner).filter(models.Runner.id == t.runner_id).first()
    if not (r and r.physio_interest):
        raise HTTPException(status_code=403, detail="Běžec zatím nepožádal o fyzioterapeuta.")
    revoked = (db.query(models.CareAssignment)
               .filter(models.CareAssignment.physio_id == user.physio_id, models.CareAssignment.runner_id == t.runner_id,
                       models.CareAssignment.status == "revoked").first())
    if revoked:
        raise HTTPException(status_code=403, detail="Běžec spolupráci s vámi ukončil.")
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


def _own_claim(db: DBSession, tid: int, user: models.User) -> models.Triage:
    t = or_404(db.query(models.Triage).filter(models.Triage.id == tid).first(), "Případ nenalezen")
    if t.claimed_by != user.physio_id:
        raise HTTPException(status_code=403, detail="Tento případ nemáte převzatý.")
    return t


@router.post("/{tid}/release", dependencies=[Depends(verify_csrf)])
def release(tid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """physio brief 2026-11-09 P0.9: hand a claimed case back — only before the first booking or record."""
    t = _own_claim(db, tid, user)
    pid, rid = user.physio_id, t.runner_id
    if (db.query(models.Booking.id).filter(models.Booking.physio_id == pid, models.Booking.runner_id == rid,
                                           models.Booking.status.in_(("requested", "confirmed", "completed"))).first()
            or db.query(models.Conclusion.id).filter(models.Conclusion.physio_id == pid, models.Conclusion.runner_id == rid).first()
            or db.query(models.Program.id).filter(models.Program.physio_id == pid, models.Program.runner_id == rid,
                                                 models.Program.status == "sent").first()):
        raise HTTPException(status_code=409, detail="Případ už má návštěvu nebo záznam — nelze ho vrátit do fronty.")
    t.claimed_by, t.status = None, "open"
    ca = db.query(models.CareAssignment).filter(models.CareAssignment.physio_id == pid,
                                                models.CareAssignment.runner_id == rid).first()
    if ca:
        ca.status = "released"
    db.add(models.TriagePass(triage_id=t.id, physio_id=pid, reason="vráceno do fronty", created_at=E.now_iso()))
    db.add(models.Message(runner_id=rid, physio_id=pid, sender="system", created_at=E.now_iso(),
                          body="Fyzioterapeut váš případ vrátil. Převezme ho jiný fyzioterapeut, nebo si termín vyberte sami."))
    db.commit()
    return {"ok": True}


@router.post("/{tid}/pass", dependencies=[Depends(verify_csrf)])
def pass_case(tid: int, body: schemas.TriagePassRequest, user: models.User = Depends(require_verified_physio),
              db: DBSession = Depends(get_db)):
    """physio brief 2026-11-09 P0.9: hide a case for me only, with a reason."""
    t = or_404(db.query(models.Triage).filter(models.Triage.id == tid).first(), "Případ nenalezen")
    if t.claimed_by:
        raise HTTPException(status_code=409, detail="Případ už je převzatý.")
    if not (body.reason or "").strip():
        raise HTTPException(status_code=422, detail="Uveďte důvod.")
    db.add(models.TriagePass(triage_id=t.id, physio_id=user.physio_id, reason=body.reason.strip(), created_at=E.now_iso()))
    db.commit()
    return {"ok": True}
