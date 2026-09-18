"""Employer cohort view — the one endpoint that must never leak an
individual. Pre-aggregated server-side; small cells get suppressed on top
of the whole-cohort gate, since a bucket of 1-2 inside an 8+ cohort is
still identifying. Closes the inference-stacking hole the prototype's
client-side blocked() check left open (nothing stopped a client from just
not calling it).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role

router = APIRouter(prefix="/api/employers", tags=["employers"])

MIN_COHORT = 8
SICK_DAY_CZK = 3400
DAYS_SAVED = 2.4


def _suppress(n: int):
    """Round small (1-2) cell counts so a single flagged employee can't be
    singled out inside a cohort that only just clears MIN_COHORT."""
    return n if n == 0 or n >= 3 else "≤2"


@router.get("/{eid}/cohort")
def cohort(eid: str, user: models.User = Depends(require_role("employer")), db: DBSession = Depends(get_db)):
    if user.employer_id != eid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k této firmě")
    emp = db.query(models.Employer).filter(models.Employer.id == eid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Firma nenalezena")

    runners = db.query(models.Runner).filter(models.Runner.employer_id == eid).all()
    n = len(runners)
    emp_dict = {"id": emp.id, "name": emp.name, "city": emp.city, "seats": emp.seats,
                "plan": emp.plan, "contract_value_czk": emp.contract_value_czk}
    if n < MIN_COHORT:
        return {"blocked": True, "n": n, "minCohort": MIN_COHORT, "employer": emp_dict}

    runner_ids = [r.id for r in runners]
    assessments = (
        db.query(models.Assessment).filter(models.Assessment.runner_id.in_(runner_ids)).all()
    )
    by_tier = {"ok": 0, "watch": 0, "alert": 0}
    by_quadrant = {"stable": 0, "overreaching": 0, "silent": 0, "critical": 0}
    signal_agg: dict = {}  # id -> {name, grade, n, pts}
    for a in assessments:
        if a.tier in by_tier:
            by_tier[a.tier] += 1
        if a.quadrant in by_quadrant:
            by_quadrant[a.quadrant] += 1
        for s in a.signals_json or []:
            entry = signal_agg.setdefault(s["id"], {"id": s["id"], "name": s["name"], "grade": s["grade"], "n": 0, "pts": 0})
            entry["n"] += 1
            entry["pts"] += s.get("pts", 0)

    avg_overall = round(sum(a.overall for a in assessments) / len(assessments)) if assessments else 0

    silent = by_quadrant.get("silent", 0)
    alert = by_tier.get("alert", 0)
    caught = silent + alert
    modelled_savings = caught * DAYS_SAVED * SICK_DAY_CZK
    ratio = round(modelled_savings / emp.contract_value_czk, 2) if emp.contract_value_czk else None

    bookings = (
        db.query(models.Booking)
        .join(models.Runner, models.Booking.runner_id == models.Runner.id)
        .filter(models.Runner.employer_id == eid)
        .count()
    )

    # Signal-frequency table: small counts suppressed same as byTier/byQuadrant —
    # "1 person has signal X" would be as identifying as a raw per-runner row.
    signals_out = [
        {**s, "n": _suppress(s["n"]), "avgPts": round(s["pts"] / s["n"]) if s["n"] else 0}
        for s in sorted(signal_agg.values(), key=lambda s: -s["n"])
    ]

    return {
        "blocked": False, "employer": emp_dict, "n": n, "avgOverall": avg_overall,
        "byTier": {k: _suppress(v) for k, v in by_tier.items()},
        "byQuadrant": {k: _suppress(v) for k, v in by_quadrant.items()},
        "signals": signals_out,
        "bookings": bookings,
        "roi": {
            "caught": caught, "daysSaved": DAYS_SAVED, "sickDayCzk": SICK_DAY_CZK,
            "modelledSavingsCzk": round(modelled_savings), "ratio": ratio,
        },
    }
