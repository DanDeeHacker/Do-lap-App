"""Engine sensitivity sandbox API — powers the "Citlivostní analýza" tab.

`/knobs` is the static spec (what sliders to draw). `/simulate` scores one
hypothetical state; `/sweep` returns a metric's sensitivity curve. `/inputs/{rid}`
seeds the sandbox from a runner's own live assessment. None of this touches or
mutates runner data — it's a pure function of the posted inputs — so it only
needs a logged-in session, and `/inputs` additionally scopes to the runner.
"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import ensure_runner_read_access, get_current_user
from ..metrics import engine as E
from ..metrics import sensitivity as S

router = APIRouter(prefix="/api/engine", tags=["engine"])


@router.get("/knobs")
def knobs(user: models.User = Depends(get_current_user)):
    """Static spec: the tunable inputs (grouped by axis), the axes, the quadrant
    thresholds and quadrant labels — everything the UI needs to render itself."""
    return {
        "knobs": S.KNOBS,
        "defaults": S.DEFAULTS,
        "axes": S.AXES,
        "quadrants": {
            "stable": "Stabilní", "overreaching": "Přetížení",
            "silent": "Tichý drift", "critical": "Kritická kombinace",
        },
        "thresholds": {"quadHi": S.QUAD_THRESHOLD, "quadLo": S.QUAD_EXIT},
    }


@router.post("/simulate")
def simulate(payload: dict = Body(...), user: models.User = Depends(get_current_user)):
    inputs = payload.get("inputs") if isinstance(payload, dict) else None
    prev = payload.get("prevQuadrant") if isinstance(payload, dict) else None
    mode = payload.get("mode") if isinstance(payload, dict) else None
    return S.simulate(inputs or {}, prev_quadrant=prev, mode=mode or "v1")


@router.post("/sweep")
def sweep(payload: dict = Body(...), user: models.User = Depends(get_current_user)):
    inputs = payload.get("inputs") if isinstance(payload, dict) else None
    knob = payload.get("knob") if isinstance(payload, dict) else None
    prev = payload.get("prevQuadrant") if isinstance(payload, dict) else None
    n = int(payload.get("points") or 41)
    mode = payload.get("mode") if isinstance(payload, dict) else None
    return S.sweep(inputs or {}, knob or "", n=max(2, min(n, 81)), prev_quadrant=prev, mode=mode or "v1")


@router.get("/inputs/{rid}")
def inputs_for_runner(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Seed the sandbox from a runner's own live assessment + injury history."""
    ensure_runner_read_access(db, user, rid)
    a = E.get_or_refresh_assessment(db, rid)
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    return {"inputs": S.inputs_from_assessment(a, runner), "prevQuadrant": a.get("quadrant"),
            "mode": "v3" if a.get("engineMode") == "v3" else "v1"}
