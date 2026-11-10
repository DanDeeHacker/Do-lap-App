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
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import care_view as CV, models, records as R, schemas
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


# physio brief W11.2: templates by region, levels editable in the UI before the plan starts. Bone stress
# (shin, a stress-fracture diagnosis) gets a slower ladder and a warning that it needs a physio-led plan.
TEMPLATES = {
    "default": DEFAULT_LEVELS,
    "achilles": [
        {"level": 1, "label": "1 min běh / 2 min chůze × 5, rovina", "run_s": 60, "walk_s": 120, "reps": 5},
        {"level": 2, "label": "2 min běh / 2 min chůze × 5", "run_s": 120, "walk_s": 120, "reps": 5},
        {"level": 3, "label": "3 min běh / 1 min chůze × 5", "run_s": 180, "walk_s": 60, "reps": 5},
        {"level": 4, "label": "5 min běh / 1 min chůze × 4", "run_s": 300, "walk_s": 60, "reps": 4},
        {"level": 5, "label": "10 min běh / 1 min chůze × 2", "run_s": 600, "walk_s": 60, "reps": 2},
        {"level": 6, "label": "20 min souvislý lehký běh", "run_s": 1200, "walk_s": 0, "reps": 1},
    ],
    "bone": [
        {"level": 1, "label": "30 min svižná chůze", "run_s": 0, "walk_s": 1800, "reps": 1},
        {"level": 2, "label": "30 s běh / 2 min chůze × 6", "run_s": 30, "walk_s": 120, "reps": 6},
        {"level": 3, "label": "1 min běh / 2 min chůze × 6", "run_s": 60, "walk_s": 120, "reps": 6},
        {"level": 4, "label": "2 min běh / 1 min chůze × 6", "run_s": 120, "walk_s": 60, "reps": 6},
        {"level": 5, "label": "5 min běh / 1 min chůze × 4", "run_s": 300, "walk_s": 60, "reps": 4},
        {"level": 6, "label": "10 min běh / 1 min chůze × 2", "run_s": 600, "walk_s": 60, "reps": 2},
        {"level": 7, "label": "20 min souvislý lehký běh", "run_s": 1200, "walk_s": 0, "reps": 1},
    ],
}
READINESS_ITEMS = ("walk_30", "daily_pain_lt2", "no_night_pain", "no_limp")   # W11.1 the physio ticks or adjusts


def _bone_warning(db: DBSession, rid: str, template: str | None) -> str | None:
    ep = (db.query(models.CareEpisode).filter_by(runner_id=rid, status="open").order_by(models.CareEpisode.id.desc()).first())
    text = f"{(ep.region if ep else '') or ''} {(ep.diagnosis_label if ep else '') or ''}".lower()
    if template == "bone" or "shin" in text or "únavov" in text or "stresov" in text:
        return ("Únavové přetížení kosti: návrat k běhu vede fyzioterapeut s dalším uvolněním (bez bolesti při chůzi "
                "a poskocích, případně se souhlasem lékaře).")
    return None


@router.get("/templates")
def templates(user: models.User = Depends(require_role("physio"))):
    return {"templates": TEMPLATES, "readiness_items": READINESS_ITEMS, "pain_limits": [0, 1, 2, 3, 4, 5]}


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
    from .. import work as W
    W.expire_morning(db, plan)        # W11.5: 36 h without the morning answer → not counted
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
    out["pending_morning"] = next(({"id": x.id, "logged_at": x.logged_at} for x in sessions if x.state == "pending"), None)
    rc = db.query(models.RtrReadinessCheck).filter_by(plan_id=plan.id).first()
    out["readiness"] = {"items": rc.items, "tests": rc.tests} if rc else None
    return out


@router.post("", dependencies=[Depends(verify_csrf)])
def create_plan(body: schemas.CreateRtrRequest, user: models.User = Depends(require_role("physio")),
                db: DBSession = Depends(get_db)):
    if not has_care_assignment(db, user.physio_id, body.runner_id):
        raise HTTPException(status_code=403, detail="Nejprve musíte tento případ převzít z fronty.")
    active = (
        db.query(models.ReturnToRun)
        .filter(models.ReturnToRun.runner_id == body.runner_id, models.ReturnToRun.status.notin_(("completed", "ended")))
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="Pacient už má aktivní plán návratu k běhu.")
    if not 0 <= body.pain_threshold <= 5:
        raise HTTPException(status_code=422, detail="Hranice bolesti je 0 až 5.")
    rd = body.readiness or {}
    if not isinstance(rd.get("items"), dict) or not all(k in rd["items"] for k in READINESS_ITEMS):
        raise HTTPException(status_code=422, detail="Vyplňte připravenost k návratu (chůze, bolest, noc, kulhání).")
    levels = body.levels or TEMPLATES.get(body.template or "default") or DEFAULT_LEVELS
    plan = models.ReturnToRun(
        runner_id=body.runner_id, physio_id=user.physio_id, conclusion_id=body.conclusion_id,
        created_at=E.now_iso(), started_on=E.iso_date(E.today_date()), status="active",
        current_level=1, pain_threshold=body.pain_threshold, sessions_per_level=body.sessions_per_level,
        levels_json=levels, note=body.note,
        episode_id=R.episode_for(db, user.physio_id, body.runner_id).id,     # physio brief R3
    )
    db.add(plan)
    db.flush()
    db.add(models.RtrReadinessCheck(plan_id=plan.id, runner_id=body.runner_id, physio_id=user.physio_id,
                                    items=rd.get("items"), tests=rd.get("tests") or [], created_at=E.now_iso()))
    R.physio_event(db, db.get(models.Physio, user.physio_id), "create", "rtr", plan.id, runner_id=body.runner_id)
    db.add(models.Message(
        runner_id=body.runner_id, physio_id=user.physio_id, sender="physio",
        body="Máte připravený plán návratu k běhu. Najdete ho v záložce Péče → Zranění. Po každém sezení zapište, "
             "jak vás to bolelo." + (f" Poznámka: {body.note}" if body.note else ""),
        created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(plan)
    return {**_plan_dict(db, plan), "warning": _bone_warning(db, body.runner_id, body.template)}


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
    if plan.status == "paused":
        raise HTTPException(status_code=409, detail="Plán je pozastavený. Počkejte na pokyn fyzioterapeuta.")
    if body.pain is None or not 0 <= body.pain <= 10:
        raise HTTPException(status_code=422, detail="Zapište bolest během sezení (0–10).")
    pain = body.pain
    # physio brief 2026-11-09 P0.7: pain over the limit pauses the plan (the UI promised it); a session
    # sooner than MIN_HOURS_BETWEEN_SESSIONS after the last one is kept but never advances the ladder
    nxt = CV.next_session_at(db, plan)
    now = datetime.fromisoformat(E.now_iso())
    if nxt is not None and nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=now.tzinfo)
    reason = None
    if pain > plan.pain_threshold:
        reason = "pain_over_limit"
    elif not body.completed:
        reason = "not_completed"
    elif nxt is not None and now < nxt:
        reason = "too_soon"
    # physio brief W11.5: a good session waits for the next-morning answer before it counts
    from .. import work as W
    level = next((lv for lv in (plan.levels_json or []) if lv.get("level") == plan.current_level), None)
    match = W.match_activity(db, plan, level, E.now_iso())
    s = models.RtrSession(
        plan_id=plan.id, runner_id=plan.runner_id, level=plan.current_level, logged_at=E.now_iso(),
        pain=pain, rpe=body.rpe, completed=bool(body.completed), counted=False, count_reason=reason,
        state="pending" if reason is None else "not_counted", note=body.note,
        matched_activity_id=match["activity_id"] if match else None,
    )
    db.add(s)
    if reason == "pain_over_limit":
        plan.status, plan.paused_reason = "paused", "pain_over_limit"
        db.add(models.Message(
            runner_id=plan.runner_id, physio_id=plan.physio_id, sender="system", audience="physio",
            body=f"Návrat k běhu: klient hlásí bolest {pain}/10 na úrovni {plan.current_level} (hranice "
                 f"{plan.pain_threshold}/10). Plán je pozastavený, dokud ho neobnovíte.",
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
        plan.paused_reason = "physio" if status == "paused" else None
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)


# ---- physio brief W11: the next morning and the physio's controls ---------------------------------------------
@router.post("/{pid}/sessions/{sid}/morning", dependencies=[Depends(verify_csrf)])
def morning(pid: int, sid: int, body: schemas.RtrMorningRequest, user: models.User = Depends(get_current_user),
            db: DBSession = Depends(get_db)):
    """Jak to bolí dnes ráno? A session counts only when the pain during it and the next morning are within
    the limit and the morning is not worse than the session (Silbernagel's pain-monitoring model)."""
    plan = or_404(db.query(models.ReturnToRun).filter(models.ReturnToRun.id == pid).first(), "Plán nenalezen")
    ensure_runner_self(user, plan.runner_id)
    s = db.get(models.RtrSession, sid)
    if s is None or s.plan_id != plan.id:
        raise HTTPException(status_code=404, detail="Sezení nenalezeno")
    if body.pain is None or not 0 <= body.pain <= 10:
        raise HTTPException(status_code=422, detail="Zapište ranní bolest (0–10).")
    from .. import work as W
    W.expire_morning(db, plan)
    if s.state != "pending":
        raise HTTPException(status_code=409, detail="Na toto sezení už se ráno neptáme.")
    s.next_morning_pain, s.morning_stiffness_min = body.pain, body.stiffness_min
    s.morning_at = E.now_iso()
    if body.pain > plan.pain_threshold:
        s.state, s.counted, s.count_reason = "not_counted", False, "morning_over_limit"
        plan.status, plan.paused_reason = "paused", "pain_over_limit"
        db.add(models.Message(runner_id=plan.runner_id, physio_id=plan.physio_id, sender="system", audience="physio",
                              created_at=E.now_iso(),
                              body=f"Návrat k běhu: ráno po sezení bolest {body.pain}/10 (hranice {plan.pain_threshold}/10). "
                                   "Plán je pozastavený, dokud ho neobnovíte."))
    elif body.pain > (s.pain or 0):
        s.state, s.counted, s.count_reason = "not_counted", False, "morning_worse"
    else:
        s.state, s.counted, s.count_reason = "counted", True, None
    db.flush()
    _recompute_progress(db, plan)
    if plan.status == "completed":
        db.add(models.Message(runner_id=plan.runner_id, physio_id=plan.physio_id, sender="system", created_at=E.now_iso(),
                              body="Plán návratu je splněný. Další týdny hlídá Trénink postupný návrat podle vaší kapacity."))
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)


@router.post("/{pid}/control", dependencies=[Depends(verify_csrf)])
def control(pid: int, body: schemas.RtrControlRequest, user: models.User = Depends(require_role("physio")),
            db: DBSession = Depends(get_db)):
    """W11.9: resume, repeat the level, step back, edit the remaining levels, end the plan — each logged."""
    plan = or_404(db.query(models.ReturnToRun).filter(models.ReturnToRun.id == pid).first(), "Plán nenalezen")
    if plan.physio_id != user.physio_id or not has_care_assignment(db, user.physio_id, plan.runner_id):
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto plánu")
    sess = db.query(models.RtrSession).filter_by(plan_id=plan.id, counted=True).all()
    a = body.action
    if a == "resume":
        plan.status, plan.paused_reason = "active", None
    elif a == "repeat_level":
        for x in sess:
            if x.level == plan.current_level:
                x.counted, x.count_reason = False, "repeat_level"
    elif a == "step_back":
        for x in sess:
            if x.level >= plan.current_level - 1:
                x.counted, x.count_reason = False, "step_back"
    elif a == "edit_levels":
        lv = body.levels or []
        if not lv or not all(isinstance(x, dict) and x.get("label") for x in lv):
            raise HTTPException(status_code=422, detail="Každá úroveň potřebuje popis.")
        keep = [x for x in (plan.levels_json or []) if x.get("level", 0) < plan.current_level]
        plan.levels_json = keep + [{**x, "level": len(keep) + i + 1} for i, x in enumerate(lv)]
    elif a == "end":
        plan.status, plan.paused_reason = "ended", "physio"
    else:
        raise HTTPException(status_code=422, detail="Neznámá akce")
    db.flush()
    if a != "end":
        _recompute_progress(db, plan)
        if a in ("repeat_level", "step_back") and plan.status == "completed":
            plan.status = "active"
    R.physio_event(db, db.get(models.Physio, user.physio_id), "update", "rtr", plan.id, runner_id=plan.runner_id,
                   detail={"action": a})
    db.add(models.Message(runner_id=plan.runner_id, physio_id=plan.physio_id, sender="system", created_at=E.now_iso(),
                          body={"resume": "Fyzioterapeut obnovil plán návratu k běhu.",
                                "repeat_level": "Fyzioterapeut vás nechal zopakovat aktuální úroveň návratu.",
                                "step_back": "Fyzioterapeut vrátil plán návratu o úroveň zpět.",
                                "edit_levels": "Fyzioterapeut upravil další úrovně plánu návratu.",
                                "end": "Fyzioterapeut ukončil plán návratu k běhu."}[a]))
    db.commit()
    db.refresh(plan)
    return _plan_dict(db, plan)
