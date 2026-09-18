"""Return-to-run — a progressive walk/run ladder the physio prescribes and
the runner works through, advancing only on pain-free completed sessions.

The physio (who has claimed the patient) creates the plan; the runner logs
their own sessions. Advancement is recomputed server-side after every log
from the full session history, so it's order-respecting and idempotent: a
level is "done" once `sessions_per_level` sessions at that level were
completed at or below `pain_threshold`, and levels must be cleared in order.
A session above the threshold is a logged setback that never advances the
ladder (and pings the physio).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models, schemas
from ..db import get_db
from ..deps import (
    ensure_runner_read_access, ensure_runner_self, get_current_user,
    has_care_assignment, or_404, require_role, verify_csrf,
)
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/rtr", tags=["return-to-run"])

# Default 6-stage ladder — conservative run:walk intervals building to
# continuous easy running. Physio can override with a custom `levels` list.
DEFAULT_LEVELS = [
    {"level": 1, "label": "1 min běh / 2 min chůze × 6", "run_s": 60, "walk_s": 120, "reps": 6},
    {"level": 2, "label": "2 min běh / 1 min chůze × 6", "run_s": 120, "walk_s": 60, "reps": 6},
    {"level": 3, "label": "4 min běh / 1 min chůze × 4", "run_s": 240, "walk_s": 60, "reps": 4},
    {"level": 4, "label": "9 min běh / 1 min chůze × 3", "run_s": 540, "walk_s": 60, "reps": 3},
    {"level": 5, "label": "14 min běh / 1 min chůze × 2", "run_s": 840, "walk_s": 60, "reps": 2},
    {"level": 6, "label": "25 min souvislý lehký běh", "run_s": 1500, "walk_s": 0, "reps": 1},
]


def _recompute_progress(db: DBSession, plan: models.ReturnToRun) -> None:
    """Order-respecting: current_level = first level not yet cleared; status
    completed once every level has enough passing sessions."""
    levels = plan.levels_json or []
    n = len(levels)
    counts = {}
    for s in db.query(models.RtrSession).filter(
        models.RtrSession.plan_id == plan.id, models.RtrSession.counted.is_(True)
    ).all():
        counts[s.level] = counts.get(s.level, 0) + 1
    cleared = 0
    for lvl in range(1, n + 1):
        if counts.get(lvl, 0) >= plan.sessions_per_level:
            cleared += 1
        else:
            break
    plan.current_level = min(cleared + 1, n) if n else 1
    if n and cleared >= n:
        plan.status = "completed"
    elif plan.status == "completed":
        plan.status = "active"


def _plan_dict(db: DBSession, plan: models.ReturnToRun) -> dict:
    out = to_dict(plan)
    sessions = (
        db.query(models.RtrSession).filter(models.RtrSession.plan_id == plan.id)
        .order_by(models.RtrSession.logged_at.asc()).all()
    )
    out["sessions"] = to_dicts(sessions)
    levels = plan.levels_json or []
    out["level_count"] = len(levels)
    out["current"] = next((l for l in levels if l.get("level") == plan.current_level), None)
    cleared_at_current = sum(
        1 for s in sessions if s.level == plan.current_level and s.counted
    )
    out["cleared_at_current"] = cleared_at_current
    out["remaining_at_current"] = max(0, plan.sessions_per_level - cleared_at_current)
    return out


@router.post("", dependencies=[Depends(verify_csrf)])
def create_plan(body: schemas.CreateRtrRequest, user: models.User = Depends(require_role("physio")),
                db: DBSession = Depends(get_db)):
    if not has_care_assignment(db, user.physio_id, body.runner_id):
        raise HTTPException(status_code=403, detail="Nejprve musíte tento případ převzít z fronty.")
    active = (
        db.query(models.ReturnToRun)
        .filter(models.ReturnToRun.runner_id == body.runner_id, models.ReturnToRun.status != "completed")
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="Pacient už má aktivní plán návratu k běhu.")
    levels = body.levels or DEFAULT_LEVELS
    plan = models.ReturnToRun(
        runner_id=body.runner_id, physio_id=user.physio_id, conclusion_id=body.conclusion_id,
        created_at=E.now_iso(), started_on=E.iso_date(E.today_date()), status="active",
        current_level=1, pain_threshold=body.pain_threshold, sessions_per_level=body.sessions_per_level,
        levels_json=levels, note=body.note,
    )
    db.add(plan)
    db.flush()
    db.add(models.Message(
        runner_id=body.runner_id, physio_id=user.physio_id, sender="physio",
        body="Připravil jsem vám plán návratu k běhu — najdete ho v aplikaci. Po každém sezení zaznamenejte, jak vás to bolelo.",
        created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)


@router.get("/{pid}")
def get_plan(pid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    plan = or_404(db.query(models.ReturnToRun).filter(models.ReturnToRun.id == pid).first(), "Plán nenalezen")
    ensure_runner_read_access(db, user, plan.runner_id)
    return _plan_dict(db, plan)


@router.post("/{pid}/session", dependencies=[Depends(verify_csrf)])
def log_session(pid: int, body: schemas.LogRtrSessionRequest,
                user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    plan = or_404(db.query(models.ReturnToRun).filter(models.ReturnToRun.id == pid).first(), "Plán nenalezen")
    ensure_runner_self(user, plan.runner_id)
    if plan.status == "completed":
        raise HTTPException(status_code=409, detail="Plán je už dokončený.")
    pain = max(0, min(10, body.pain or 0))
    counted = bool(body.completed) and pain <= plan.pain_threshold
    s = models.RtrSession(
        plan_id=plan.id, runner_id=plan.runner_id, level=plan.current_level, logged_at=E.now_iso(),
        pain=pain, rpe=body.rpe, completed=bool(body.completed), counted=counted, note=body.note,
    )
    db.add(s)
    # a setback (pain well over threshold) is worth surfacing to the physio
    if pain >= plan.pain_threshold + 2:
        db.add(models.Message(
            runner_id=plan.runner_id, physio_id=plan.physio_id, sender="system",
            body=f"Návrat k běhu: pacient hlásí bolest {pain}/10 na úrovni {plan.current_level} — plán zůstává na místě.",
            created_at=E.now_iso(),
        ))
    db.flush()
    _recompute_progress(db, plan)
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)


@router.patch("/{pid}", dependencies=[Depends(verify_csrf)])
def update_plan(pid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db),
                status: str = None):
    """Physio pause/resume. `status` in {active, paused}."""
    plan = or_404(db.query(models.ReturnToRun).filter(models.ReturnToRun.id == pid).first(), "Plán nenalezen")
    if plan.physio_id != user.physio_id or not has_care_assignment(db, user.physio_id, plan.runner_id):
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto plánu")
    if status in ("active", "paused"):
        plan.status = status
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)
