"""Runner-scoped resources: profile, assessment, activities, daily metrics,
bookings, program, messages, check-ins, activity ratings. Every handler
scopes through deps.ensure_runner_read_access / ensure_runner_self — a
runner may only ever touch their own runner_id; a physio may read (never
write on the runner's behalf) once they've claimed the case.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import history as H
from .. import models, precompute, schemas
from ..db import get_db
from ..deps import (
    ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf,
)
from ..metrics import coach_texts
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/runners", tags=["runners"])

ALLOWED_DAILY_PATCH = {"sleep_h", "hrv_ms", "resting_hr", "body_battery", "stress_avg", "steps"}
BOOKING_PRICE = {"gait_analysis": 1490, "video_call": 690, "follow_up": 1190, "assessment": 1190}
OSTRC_VALUES = {0, 8, 17, 25}  # the four fixed OSTRC-H response levels


@router.get("/{rid}")
def get_runner(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    return to_dict(r)


ALLOWED_PROFILE_PATCH = {
    "birth_year", "sex", "city", "goal_race", "goal_date", "prior_injury",
    "prior_injury_months_ago", "prior_injury_date", "prior_injury_side", "device", "hr_max",
}


@router.post("/{rid}/engine", dependencies=[Depends(verify_csrf)])
def set_engine(rid: str, body: schemas.EngineModeRequest,
               user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Switch the runner's engine: "v1" standard (averaged), "v2" sensitive
    (per-run, calibrated mechanics) or "v3" capacity (v2 mechanics + the load
    axis scored against the runner's own demonstrated capacity; unlocks the
    Trénink tab). Recomputes the assessment right away so the change is visible."""
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    mode = body.mode if body.mode in ("v1", "v2", "v3") else "v1"
    r.engine_mode = mode
    db.commit()
    a = E.recompute_assessment(db, rid)
    return {"ok": True, "engine_mode": mode, "assessment": a}


@router.put("/{rid}/cycle", dependencies=[Depends(verify_csrf)])
def set_cycle_week(rid: str, body: schemas.CycleWeekRequest,
                   user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Trénink: the runner picks this calendar week's place in the 4-week loading
    cycle (e.g. a recovery week now) — targets, today's allowance and the
    recommendation are recomputed right away. Applies to this week only; next
    week the cycle re-anchors on what was actually run. pos=None → automatic."""
    ensure_runner_self(user, rid)
    if body.pos is not None and body.pos not in (1, 2, 3, 4):
        raise HTTPException(status_code=422, detail="Týden cyklu musí být 1–4")
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    from ..metrics.guidance import week_start
    r.cycle_override = None if body.pos is None else {
        "week": week_start(E.today_date()).isoformat(), "pos": body.pos, "setAt": E.now_iso()}
    db.commit()
    return {"ok": True, "assessment": E.recompute_assessment(db, rid)}


@router.get("/{rid}/races")
def list_races(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Plan B4 — the race calendar (plus the profile's goal race as an A race)."""
    ensure_runner_read_access(db, user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    return E.races_for(db, r)


@router.post("/{rid}/races", dependencies=[Depends(verify_csrf)])
def add_race(rid: str, body: schemas.RaceRequest,
             user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    try:
        d = date.fromisoformat(body.date[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatné datum závodu")
    today = E.today_date()
    if not (today - timedelta(days=366) <= d <= today + timedelta(days=731)):
        raise HTTPException(status_code=422, detail="Datum závodu musí být do roka zpátky a do dvou let dopředu")
    if body.priority not in ("A", "B", "C"):
        raise HTTPException(status_code=422, detail="Priorita závodu musí být A, B nebo C")
    if body.distance_km is not None and not (0 < body.distance_km <= 300):
        raise HTTPException(status_code=422, detail="Délka závodu musí být 0–300 km")
    name = (body.name or "").strip()[:80] or None
    db.add(models.Race(runner_id=rid, date=d.isoformat(), name=name, distance_km=body.distance_km,
                       priority=body.priority, created_at=E.now_iso()))
    if r.goal_date and r.goal_date[:10] == d.isoformat():
        r.goal_race, r.goal_date = None, None          # the calendar entry replaces the profile's goal race
    db.commit()
    return {"races": E.races_for(db, r), "assessment": E.recompute_assessment(db, rid)}


@router.delete("/{rid}/races/{race_id}", dependencies=[Depends(verify_csrf)])
def delete_race(rid: str, race_id: str,
                user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    if race_id == "goal":                               # the profile's goal race
        r.goal_race, r.goal_date = None, None
    else:
        row = db.query(models.Race).filter(models.Race.runner_id == rid,
                                           models.Race.id == (int(race_id) if race_id.isdigit() else -1)).first()
        or_404(row, "Závod nenalezen")
        db.delete(row)
    db.commit()
    return {"races": E.races_for(db, r), "assessment": E.recompute_assessment(db, rid)}


@router.patch("/{rid}", dependencies=[Depends(verify_csrf)])
def update_runner(rid: str, body: schemas.RunnerProfilePatch,
                  user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Runner edits their own profile — the fields the engine (prior injury,
    goal date) and physio (age/sex/city/goal) rely on. Recomputes the
    assessment afterwards since goal/injury can move the score."""
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    for k, v in body.patch.items():
        if k not in ALLOWED_PROFILE_PATCH:
            continue
        if k == "hr_max" and v not in (None, ""):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Maximální tep musí být číslo") from None
            if not 120 <= v <= 230:
                raise HTTPException(status_code=422, detail="Maximální tep musí být 120–230 tepů/min")
        if k == "prior_injury_side" and v not in (None, "", "left", "right", "both"):
            raise HTTPException(status_code=422, detail="Strana zranění: levá, pravá nebo obě")
        if k == "prior_injury_date" and v:
            try:
                if date.fromisoformat(str(v)[:10]) > E.today_date():
                    raise ValueError
            except ValueError:
                raise HTTPException(status_code=422, detail="Datum zranění nesmí být v budoucnosti") from None
            v = str(v)[:10]
        setattr(r, k, (v or None) if k in ("prior_injury_side", "prior_injury_date", "hr_max") else v)
    db.commit()
    E.recompute_assessment(db, rid)
    db.refresh(r)
    return to_dict(r)


@router.get("/{rid}/bootstrap")
def bootstrap(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Everything runner.html (or physio.html's patient drill-down) needs
    for one runner in a single round trip: a DB-shaped bundle scoped to
    just this runner, assembled server-side instead of joined client-side.
    """
    ensure_runner_read_access(db, user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")

    assessment = E.get_or_refresh_assessment(db, rid)

    triage = (
        db.query(models.Triage).filter(models.Triage.runner_id == rid, models.Triage.status != "closed")
        .order_by(models.Triage.id.desc()).first()
    )
    checkins = db.query(models.Checkin).filter(models.Checkin.runner_id == rid).order_by(models.Checkin.submitted_at.asc()).all()
    activities = (
        db.query(models.Activity).filter(models.Activity.runner_id == rid)
        .order_by(models.Activity.started_at.desc()).all()
    )
    activity_feedback = (
        db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid)
        .order_by(models.ActivityFeedback.submitted_at.desc()).all()
    )
    daily_metrics = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid).order_by(models.DailyMetric.date.asc()).all()
    bookings = db.query(models.Booking).filter(models.Booking.runner_id == rid).order_by(models.Booking.slot_at.asc()).all()
    program = (
        db.query(models.Program).filter(models.Program.runner_id == rid, models.Program.active.is_(True))
        .order_by(models.Program.id.desc()).first()
    )
    program_out = None
    if program:
        program_out = to_dict(program)
        program_out["exercises"] = to_dicts(db.query(models.Exercise).filter(models.Exercise.program_id == program.id).all())
        program_out["revisions"] = to_dicts(
            db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == program.id)
            .order_by(models.ProgramRevision.id.asc()).all()
        )
    messages = db.query(models.Message).filter(models.Message.runner_id == rid).order_by(models.Message.created_at.asc()).all()
    integration = db.query(models.Integration).filter(models.Integration.runner_id == rid).first()
    device_history = (
        db.query(models.DeviceHistory).filter(models.DeviceHistory.runner_id == rid)
        .order_by(models.DeviceHistory.recorded_at.asc()).all()
    )
    injury_reports = (
        db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid)
        .order_by(models.InjuryReport.submitted_at.desc()).limit(12).all()
    )
    last_self = (
        db.query(models.InjuryReport.submitted_at)
        .filter(models.InjuryReport.runner_id == rid,
                models.InjuryReport.source.in_(("self_weekly", "self_adhoc")))
        .order_by(models.InjuryReport.submitted_at.desc()).first()
    )
    injury_prompt_due = last_self is None or last_self[0] <= E.day_ago(7)
    # runner sees a conclusion only once the physio has approved it
    conclusions = (
        db.query(models.Conclusion)
        .filter(models.Conclusion.runner_id == rid, models.Conclusion.status == "approved")
        .order_by(models.Conclusion.approved_at.desc()).all()
    )
    rtr_plan = (
        db.query(models.ReturnToRun)
        .filter(models.ReturnToRun.runner_id == rid, models.ReturnToRun.status != "completed")
        .order_by(models.ReturnToRun.id.desc()).first()
    )
    rtr_out = None
    if rtr_plan:
        from ..routers.rtr import _plan_dict
        rtr_out = _plan_dict(db, rtr_plan)
    access_rows = (
        db.query(models.AccessLog).filter(models.AccessLog.runner_id == rid)
        .order_by(models.AccessLog.last_at.desc()).limit(20).all()
    )
    access_names = {
        p.id: p.name for p in
        db.query(models.Physio).filter(models.Physio.id.in_({a.physio_id for a in access_rows})).all()
    } if access_rows else {}
    access_out = []
    for a in access_rows:
        d = to_dict(a)
        d["physio_name"] = access_names.get(a.physio_id)
        access_out.append(d)
    from ..routers.booking import due_reminders
    reminders = due_reminders(db, runner_id=rid)

    physio_ids = {b.physio_id for b in bookings if b.physio_id}
    physio_ids |= {program.physio_id} if program else set()
    physio_ids |= {m.physio_id for m in messages if m.physio_id}
    physios = {
        p.id: to_dict(p) for p in db.query(models.Physio).filter(models.Physio.id.in_(physio_ids)).all()
    } if physio_ids else {}

    return {
        "runner": to_dict(r), "assessment": assessment, "triage": to_dict(triage),
        "checkins": to_dicts(checkins), "activities": to_dicts(activities),
        "activity_feedback": to_dicts(activity_feedback), "daily_metrics": to_dicts(daily_metrics),
        "bookings": to_dicts(bookings), "program": program_out, "messages": to_dicts(messages),
        "physios": physios, "integration": to_dict(integration), "device_history": to_dicts(device_history),
        "injury_reports": to_dicts(injury_reports), "injury_prompt_due": injury_prompt_due,
        "conclusions": to_dicts(conclusions), "rtr": rtr_out, "access_log": access_out,
        "reminders": reminders,
    }


# The replay machinery and the history caches live in app.history (shared with
# the background precompute worker in app.precompute).
_engine_replay = H.engine_replay
_cached_history = H.cached_history


@router.get("/{rid}/mech-history")
def mech_history(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Weekly replay of assess() over the runner's whole history — the drift /
    stability score (and load/overall/quadrant) as of each week. Powers the
    Pohyb trend chart."""
    ensure_runner_read_access(db, user, rid)
    from datetime import date, timedelta

    def build():
        acts_dates = [a[0][:10] for a in db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid).all()]
        if not acts_dates:
            return []
        # Start at the first activity (no baseline warmup offset) so the trend
        # spans the runner's real history; the [-26:] cap keeps it ~6 months.
        ad = date.fromisoformat(min(acts_dates))
        end = E.today_date()  # end at *today*, so the last trend point equals the current score
        asofs = []
        while ad <= end:
            asofs.append(ad)
            ad += timedelta(days=7)
        if not asofs or asofs[-1] != end:
            asofs.append(end)
        asofs = asofs[-26:]  # cap cost — last ~6 months of weekly points
        return [{"date": av["_cut"], "mech": av["mech"], "load": av["load"], "symp": av["symp"],
                 "overall": av["overall"], "quadrant": av["quadrant"]} for av in _engine_replay(db, rid, asofs)]

    return _cached_history(db, rid, "mech", build)


ENGINE_MODES = ("v1", "v2", "v3")


def _state(av: dict, n_signals: int = 0) -> dict:
    out = {k: av.get(k) for k in ("overall", "load", "mech", "symp", "quadrant", "tier")}
    if n_signals:
        out["signals"] = [{"name": s["name"], "val": s.get("val"), "pts": s["pts"], "grade": s.get("grade")}
                          for s in (av.get("signals") or [])[:n_signals]]
        out["confidence"] = round(((av.get("confidence") or {}).get("value") or 0) * 100)
    return out


@router.get("/{rid}/engine-compare")
def engine_compare(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Data a připojení → Porovnání enginů: what each engine — v1 standard, v2
    sensitive, v3 capacity — scores for this runner today, what goes into it
    (top signals), and its weekly history over ~6 months, all replayed on the
    runner's own data. Nothing is persisted; cached per day like the other
    histories (invalidated by any data change)."""
    ensure_runner_read_access(db, user, rid)
    from datetime import date, timedelta

    def build():
        acts_dates = [a[0][:10] for a in db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid).all()]
        if not acts_dates:
            return {"today": {}, "series": []}
        end = E.today_date()
        ad = max(date.fromisoformat(min(acts_dates)), end - timedelta(days=7 * 25))
        asofs = []
        while ad < end:
            asofs.append(ad)
            ad += timedelta(days=7)
        asofs.append(end)
        inp = H.load_inputs(db, rid)   # read the runner's data once for all three replays
        replays = {m: _engine_replay(db, rid, asofs, mode=m, inputs=inp) for m in ENGINE_MODES}
        today = {}
        for m in ENGINE_MODES:
            with E.engine_pinned(m):
                today[m] = {**_state(E.assess(db, rid), n_signals=6), "version": E.engine_version_for(m)}
        series = [{"date": replays["v1"][i]["_cut"], **{m: _state(replays[m][i]) for m in ENGINE_MODES}}
                  for i in range(len(asofs))]
        return {"today": today, "series": series}

    return _cached_history(db, rid, "engines", build)


QUAD_HISTORY_DAYS = H.QUAD_HISTORY_DAYS
# How long a history read waits for the background rebuild before falling back.
QUAD_WAIT_S = 25.0


@router.get("/{rid}/quadrant-history")
def quadrant_history(rid: str, days: int = QUAD_HISTORY_DAYS, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Daily replay of the quadrant / state over the last ~6 months. Powers the
    Dnes strip and the Pohyb and Zátěž daily trend charts. One point per calendar
    day up to today.

    Normally a plain cache read: the background worker (app.precompute) rebuilds
    the history incrementally right after every data change and extends it each
    night. When the cache is dirty the read waits for that job (or, with the
    worker disabled, refreshes inline, which replays only the changed days)."""
    ensure_runner_read_access(db, user, rid)
    days = max(7, min(days, 190))
    if days != QUAD_HISTORY_DAYS:
        # A custom window is computed ad hoc so it can't poison the shared cache.
        return H.build_quadrant_history(db, rid, days)
    rows = H.quadrant_cache_fresh(db, rid)
    if rows is not None:
        return rows
    if precompute.enabled():
        precompute.schedule(rid)
        done = precompute.wait(rid, QUAD_WAIT_S)
        db.expire_all()
        rows = H.quadrant_cache_fresh(db, rid)
        if rows is not None:
            return rows
        if not done:
            stale = H.quadrant_cache_any(db, rid)
            if stale is not None:
                return stale   # still rebuilding: yesterday's strip beats a timeout
    return H.refresh_quadrant_history(db, rid)["rows"]


@router.get("/{rid}/alerts/pending")
def pending_alert(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Plan phase 0: the newest unanswered alert of the last 3 days (a load or
    mechanics axis that turned elevated), so the app can ask "does it fit?"."""
    ensure_runner_self(user, rid)
    from .. import outcomes
    a = outcomes.recent_unrated_alert(db, rid)
    return {"alert": {"id": a.id, "date": a.date, "axis": a.axis} if a else None}


@router.post("/{rid}/alerts/{aid}/feedback", dependencies=[Depends(verify_csrf)])
def alert_feedback(rid: str, aid: int, payload: dict, user: models.User = Depends(get_current_user),
                   db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    fb = (payload or {}).get("feedback")
    if fb not in ("fits", "no_fit"):
        raise HTTPException(400, "Neplatná odpověď")
    a = or_404(db.query(models.EngineAlert).filter(models.EngineAlert.id == aid,
                                                   models.EngineAlert.runner_id == rid).first(), "Upozornění nenalezeno")
    a.feedback, a.feedback_at = fb, E.now_iso()
    db.commit()
    return {"ok": True}


@router.get("/{rid}/run-history")
def run_history(rid: str, limit: int = 20, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Latest runs with terrain and weather context (Pohyb → Historie běhů).
    Weather is fetched once per run on first view and stored."""
    ensure_runner_read_access(db, user, rid)
    from ..metrics import run_context
    return run_context.run_history(db, rid, max(1, min(limit, 60)))


@router.get("/{rid}/run-compare/{aid}")
def run_compare(rid: str, aid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """One run's metrics vs. the comparable run from a month before."""
    ensure_runner_read_access(db, user, rid)
    return E.run_compare(db, rid, aid)


@router.get("/{rid}/run-segments/{aid}")
def run_segment_test(rid: str, aid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Per-segment test of one run vs. the baseline as of that run's day
    (Pohyb → Historie běhů). available=false until the run's detailed stream is fetched."""
    ensure_runner_read_access(db, user, rid)
    return E.run_segment_test(db, rid, aid)


@router.get("/{rid}/access-log")
def access_log(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """GDPR transparency: who accessed this runner's record. Visible to the
    runner themself and to a physio who has claimed them."""
    ensure_runner_read_access(db, user, rid)
    rows = (
        db.query(models.AccessLog).filter(models.AccessLog.runner_id == rid)
        .order_by(models.AccessLog.last_at.desc()).limit(50).all()
    )
    names = {
        p.id: p.name for p in
        db.query(models.Physio).filter(models.Physio.id.in_({r.physio_id for r in rows})).all()
    } if rows else {}
    out = []
    for r in rows:
        d = to_dict(r)
        d["physio_name"] = names.get(r.physio_id)
        out.append(d)
    return out


@router.get("/{rid}/assessment")
def get_assessment(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    return E.get_or_refresh_assessment(db, rid)


@router.get("/{rid}/run-segments")
def run_segments(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Per-run within-run segment drift (sjezd/rovina/výjezd) for the Pohyb tab.
    Empty until detailed streams have been fetched."""
    ensure_runner_read_access(db, user, rid)
    return E.run_segment_breakdown(db, rid)


@router.get("/{rid}/run-segment-significance")
def run_segment_significance(rid: str, n: int = 3, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Per-segment statistical test (each metric vs the runner's baseline for the
    same terrain) for the last n runs. Empty until detailed streams are fetched."""
    ensure_runner_read_access(db, user, rid)
    return E.segment_significance(db, rid, n_runs=n)


@router.get("/{rid}/backtest.xlsx")
def backtest_xlsx(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Download an Excel backtest comparing the original (v1) and new sensitive
    (v2) engine over THIS runner's own history — replayed weekly + daily."""
    from fastapi import Response
    from .. import reports
    ensure_runner_self(user, rid)
    data = reports.engine_compare_xlsx(db, rid)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="dosslap_backtest_{rid}.xlsx"'},
    )


@router.get("/{rid}/backtest-detailed.xlsx")
def backtest_detailed_xlsx(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Detailed backtest: per-date per-signal point contributions (v1 & v2), raw
    drivers, and a formula legend — on THIS runner's own history."""
    from fastapi import Response
    from .. import reports
    ensure_runner_self(user, rid)
    data = reports.engine_detail_xlsx(db, rid)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="dosslap_backtest_detailed_{rid}.xlsx"'},
    )


@router.get("/{rid}/export.json")
def export_json(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Download this runner's full data as JSON (no credentials/tokens) — for
    sharing / off-line analysis."""
    from fastapi import Response
    from .. import reports
    ensure_runner_self(user, rid)
    data = reports.runner_export(db, rid)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="dosslap_data_{rid}.json"'},
    )


@router.get("/{rid}/activities")
def list_activities(rid: str, limit: int = 10, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    rows = (
        db.query(models.Activity).filter(models.Activity.runner_id == rid)
        .order_by(models.Activity.started_at.desc()).limit(limit).all()
    )
    return to_dicts(rows)


@router.get("/{rid}/activities/unrated")
def unrated_activities(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    cutoff = E.day_ago(14)
    done_ids = {
        row[0] for row in db.query(models.ActivityFeedback.activity_id)
        .filter(models.ActivityFeedback.runner_id == rid)
    }
    rows = (
        db.query(models.Activity)
        .filter(models.Activity.runner_id == rid, models.Activity.started_at > cutoff,
                models.Activity.excluded.isnot(True))
        .order_by(models.Activity.started_at.desc()).all()
    )
    return to_dicts([a for a in rows if a.id not in done_ids])


@router.post("/{rid}/activities/{aid}/exclude", dependencies=[Depends(verify_csrf)])
def exclude_activity(rid: str, aid: int, body: schemas.ExcludeActivityRequest, background: BackgroundTasks,
                     user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Feedback railway#36 — take an activity out of every calculation (scores,
    capacity, comparisons, AI texts) or put it back. Kept in the database so a
    Garmin re-sync doesn't import it again and it can be restored."""
    ensure_runner_self(user, rid)
    a = or_404(db.query(models.Activity).filter(models.Activity.id == aid, models.Activity.runner_id == rid).first(),
               "Aktivita nenalezena")
    scope = (body.scope or "all") if body.excluded else None
    if scope is not None and scope not in E.EXCLUDE_SCOPES:
        raise HTTPException(status_code=422, detail="Neplatný rozsah vyřazení")
    a.excluded = bool(body.excluded)
    a.excluded_at = E.now_iso() if body.excluded else None
    a.excluded_scope = scope
    db.commit()
    out = E.recompute_assessment(db, rid)
    background.add_task(coach_texts.refresh_bg, rid)
    return {"ok": True, "id": aid, "excluded": a.excluded, "scope": scope, "assessment": out}


@router.post("/{rid}/activities/{aid}/rate", dependencies=[Depends(verify_csrf)])
def rate_activity(rid: str, aid: int, body: schemas.RateActivityRequest,
                   user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    or_404(
        db.query(models.Activity).filter(models.Activity.id == aid, models.Activity.runner_id == rid).first(),
        "Aktivita nenalezena",
    )
    # Upsert: re-rating an already-scored run edits the existing feedback in
    # place (keeps its id and original submit date) instead of duplicating.
    fb = (
        db.query(models.ActivityFeedback)
        .filter(models.ActivityFeedback.activity_id == aid, models.ActivityFeedback.runner_id == rid)
        .first()
    )
    if fb is None:
        fb = models.ActivityFeedback(
            activity_id=aid, runner_id=rid, submitted_at=E.iso_date(E.today_date()),
        )
        db.add(fb)
    fb.feeling = body.feeling
    fb.legs = body.legs
    fb.stiffness_pre = body.stiffness_pre
    fb.pain_during = body.pain_during or 0
    fb.pain_site = body.pain_site
    fb.niggle = bool(body.niggle)
    fb.rpe = body.rpe
    fb.note = body.note
    fb.pain_points = body.pain_points
    db.commit()
    return E.recompute_assessment(db, rid)


@router.get("/{rid}/daily")
def get_daily(rid: str, days: int = 14, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    rows = E.daily(db, rid, days)
    return to_dicts(list(reversed(rows)))


@router.patch("/{rid}/daily/{date}", dependencies=[Depends(verify_csrf)])
def edit_daily(rid: str, date: str, body: schemas.EditDailyRequest,
               user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    d = or_404(
        db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == date).first(),
        "Den nenalezen",
    )
    patch = {k: v for k, v in body.patch.items() if k in ALLOWED_DAILY_PATCH}
    if "sleep_h" in patch and d.original_sleep_h is None:
        d.original_sleep_h = d.sleep_h
    for k, v in patch.items():
        setattr(d, k, v)
    d.source = "manual"
    d.edited_at = E.now_iso()
    if body.note:
        d.edit_note = body.note
    db.commit()
    E.recompute_assessment(db, rid)
    db.refresh(d)
    return to_dict(d)


@router.get("/{rid}/bookings")
def get_bookings(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    rows = db.query(models.Booking).filter(models.Booking.runner_id == rid).order_by(models.Booking.slot_at.asc()).all()
    return to_dicts(rows)


@router.post("/{rid}/bookings", dependencies=[Depends(verify_csrf)])
def create_booking(rid: str, body: schemas.BookRequest, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    physio = or_404(db.query(models.Physio).filter(models.Physio.id == body.physio_id).first(), "Fyzioterapeut nenalezen")
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    slot_at = (datetime.now(timezone.utc) + timedelta(days=max(0, body.days_ahead))).isoformat()
    b = models.Booking(
        runner_id=rid, physio_id=physio.id, slot_at=slot_at, kind=body.kind, status="confirmed",
        price_czk=BOOKING_PRICE.get(body.kind, 1190), payer="employer" if r and r.employer_id else "self",
        created_at=E.now_iso(),
    )
    db.add(b)
    t = db.query(models.Triage).filter(models.Triage.runner_id == rid, models.Triage.status != "closed").first()
    if t:
        t.status = "booked"
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.get("/{rid}/program")
def get_program(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    p = (
        db.query(models.Program)
        .filter(models.Program.runner_id == rid, models.Program.active.is_(True))
        .order_by(models.Program.id.desc()).first()
    )
    if not p:
        return None
    ex = db.query(models.Exercise).filter(models.Exercise.program_id == p.id).all()
    rv = (
        db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == p.id)
        .order_by(models.ProgramRevision.id.asc()).all()
    )
    out = to_dict(p)
    out["exercises"] = to_dicts(ex)
    out["revisions"] = to_dicts(rv)
    return out


@router.patch("/{rid}/exercises/{ex_id}/log", dependencies=[Depends(verify_csrf)])
def log_exercise(rid: str, ex_id: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    ex = or_404(db.query(models.Exercise).filter(models.Exercise.id == ex_id).first(), "Cvik nenalezen")
    prog = or_404(db.query(models.Program).filter(models.Program.id == ex.program_id).first())
    if prog.runner_id != rid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto cviku")
    ex.done_count = min(ex.target_count or ex.done_count, (ex.done_count or 0) + 1)
    db.commit()
    db.refresh(ex)
    return to_dict(ex)


@router.get("/{rid}/messages")
def get_messages(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    rows = db.query(models.Message).filter(models.Message.runner_id == rid).order_by(models.Message.created_at.asc()).all()
    return to_dicts(rows)


@router.post("/{rid}/messages", dependencies=[Depends(verify_csrf)])
def post_message(rid: str, body: schemas.SendMessageRequest, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    sender = "physio" if user.role == "physio" else "runner"
    physio_id = user.physio_id if user.role == "physio" else (
        db.query(models.Program.physio_id).filter(models.Program.runner_id == rid).scalar()
    )
    m = models.Message(runner_id=rid, physio_id=physio_id, sender=sender, body=body.body, created_at=E.now_iso())
    db.add(m)
    db.commit()
    db.refresh(m)
    return to_dict(m)


@router.get("/{rid}/injury-reports")
def list_injury_reports(rid: str, limit: int = 12, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    rows = (
        db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid)
        .order_by(models.InjuryReport.submitted_at.desc()).limit(limit).all()
    )
    return to_dicts(rows)


@router.post("/{rid}/injury-report", dependencies=[Depends(verify_csrf)])
def report_injury(rid: str, body: schemas.InjuryReportRequest,
                  user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Runner-submitted OSTRC-H outcome (weekly nudge or ad-hoc). The
    physio-conclusion path writes an authoritative, confirmed row instead —
    see the conclusion endpoint — so this is scoped to the runner themself."""
    ensure_runner_self(user, rid)
    qs = {"q_participation": body.q_participation, "q_volume": body.q_volume,
          "q_performance": body.q_performance, "q_pain": body.q_pain}
    for k, v in qs.items():
        if v not in OSTRC_VALUES:
            raise HTTPException(status_code=422, detail=f"Neplatná OSTRC hodnota u {k}")

    if body.resolve:
        now = E.iso_date(E.today_date())
        for active in (
            db.query(models.InjuryReport)
            .filter(models.InjuryReport.runner_id == rid, models.InjuryReport.status == "active").all()
        ):
            active.status = "resolved"
            active.resolved_at = now

    severity = sum(qs.values())
    # Multiple picked sites live in pain_points; body_region/body_side keep the
    # primary (first) one for existing single-site consumers.
    pts = body.pain_points or []
    primary = pts[0] if pts else None
    region = body.body_region or (primary.get("region") if primary else None)
    side = body.body_side or (primary.get("side") if primary else None)
    rep = models.InjuryReport(
        runner_id=rid, submitted_at=E.now_iso(),
        source="self_adhoc" if body.kind == "adhoc" else "self_weekly",
        status="active" if severity > 0 else "none",
        q_participation=body.q_participation, q_volume=body.q_volume,
        q_performance=body.q_performance, q_pain=body.q_pain, severity=severity,
        body_region=region, body_side=side, pain_points=pts, note=body.note, confirmed=False,
    )
    db.add(rep)
    db.flush()
    E.record_injury(db, rid, rep)          # plan B3: a reported injury becomes the injury history
    db.commit()
    return E.recompute_assessment(db, rid)


@router.post("/{rid}/checkins", dependencies=[Depends(verify_csrf)])
def create_checkin(rid: str, body: schemas.CheckinRequest, background: BackgroundTasks,
                   user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    pts = body.pain_points or []
    site = body.pain_site or (pts[0].get("region") if pts else None)
    c = models.Checkin(
        runner_id=rid, submitted_at=E.iso_date(E.today_date()), pain_score=body.pain_score,
        pain_site=site, pain_points=pts, soreness=body.soreness, stress=body.stress,
        mood=body.mood, notes=body.notes, limits_movement=body.limits_movement,
        run_modified=body.run_modified, limping=body.limping,
    )
    db.add(c)
    db.commit()
    out = E.recompute_assessment(db, rid)
    background.add_task(coach_texts.refresh_bg, rid)   # pain / feeling changed → the day's AI texts follow
    return out
