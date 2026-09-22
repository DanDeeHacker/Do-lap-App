"""Runner-scoped resources: profile, assessment, activities, daily metrics,
bookings, program, messages, check-ins, activity ratings. Every handler
scopes through deps.ensure_runner_read_access / ensure_runner_self — a
runner may only ever touch their own runner_id; a physio may read (never
write on the runner's behalf) once they've claimed the case.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models, schemas
from ..db import get_db
from ..deps import (
    ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf,
)
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
    "prior_injury_months_ago", "device",
}


@router.post("/{rid}/engine", dependencies=[Depends(verify_csrf)])
def set_engine(rid: str, body: schemas.EngineModeRequest,
               user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Switch the runner's mechanics engine: "v1" standard (averaged) or "v2"
    sensitive (per-run, robust noise scale). Recomputes the assessment right
    away so the change is visible immediately."""
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    mode = body.mode if body.mode in ("v1", "v2") else "v1"
    r.engine_mode = mode
    db.commit()
    a = E.recompute_assessment(db, rid)
    return {"ok": True, "engine_mode": mode, "assessment": a}


@router.patch("/{rid}", dependencies=[Depends(verify_csrf)])
def update_runner(rid: str, body: schemas.RunnerProfilePatch,
                  user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Runner edits their own profile — the fields the engine (prior injury,
    goal date) and physio (age/sex/city/goal) rely on. Recomputes the
    assessment afterwards since goal/injury can move the score."""
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    for k, v in body.patch.items():
        if k in ALLOWED_PROFILE_PATCH:
            setattr(r, k, v)
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


def _engine_replay(db: DBSession, rid: str, asofs):
    """Replay assess() as of each date in `asofs` on a throwaway in-memory DB
    holding only the data that existed up to that date, engine 'today' pinned to
    it (same technique as build_backtest). Yields the full assessment per date.
    Objective wearable engine only (activities + daily) — self-report isn't
    replayed, so historical points match the mechanics/load/recovery view."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from ..db import Base

    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if not runner:
        return []
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = [{c.name: getattr(r, c.name) for c in models.Activity.__table__.columns}
            for r in db.query(models.Activity).filter(models.Activity.runner_id == rid).all()]
    daily = [{c.name: getattr(r, c.name) for c in models.DailyMetric.__table__.columns}
             for r in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid).all()]
    # DeviceHistory drives the confidence device-change gate that silences the
    # mechanical signals — without it the replayed confidence is higher than the
    # live one, so the replayed mech score diverges from the current score.
    devices = [{c.name: getattr(r, c.name) for c in models.DeviceHistory.__table__.columns}
               for r in db.query(models.DeviceHistory).filter(models.DeviceHistory.runner_id == rid).all()]
    if not acts:
        return []

    out = []
    prev_q = None
    for adate in asofs:
        # Pin "today" thread-locally (not a module global) so concurrent
        # requests in FastAPI's threadpool can't corrupt each other's clock.
        with E.today_pinned(adate):
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            try:
                ts.add(models.Runner(**rdata))
                cut = adate.isoformat()
                for a in acts:
                    if a["started_at"][:10] <= cut:
                        ts.add(models.Activity(**{k: v for k, v in a.items() if k != "id"}))
                for d in daily:
                    if d["date"][:10] <= cut:
                        ts.add(models.DailyMetric(**{k: v for k, v in d.items() if k != "id"}))
                for dv in devices:
                    if (dv.get("recorded_at") or "")[:10] <= cut:
                        ts.add(models.DeviceHistory(**{k: v for k, v in dv.items() if k != "id"}))
                ts.commit()
                if prev_q:
                    ts.add(models.Assessment(runner_id=rid, quadrant=prev_q, tier="ok",
                                             mech=0, load=0, symp=0, overall=0, engine_version=E.ENGINE_VERSION))
                    ts.commit()
                with E.engine_pinned((runner.engine_mode or "v1")):
                    av = E.assess(ts, rid)
                av["_cut"] = cut
                out.append(av)
                prev_q = av["quadrant"]
            finally:
                ts.close()
                eng.dispose()
    return out


@router.get("/{rid}/mech-history")
def mech_history(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Weekly replay of assess() over the runner's whole history — the drift /
    stability score (and load/overall/quadrant) as of each week. Powers the
    Pohyb trend chart."""
    ensure_runner_read_access(db, user, rid)
    from datetime import date, timedelta

    acts_dates = [a[0][:10] for a in db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid).all()]
    if not acts_dates:
        return []
    ad = date.fromisoformat(min(acts_dates)) + timedelta(days=42)
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


@router.get("/{rid}/quadrant-history")
def quadrant_history(rid: str, days: int = 60, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Daily replay of the quadrant / state over the last ~2 months — powers the
    hover overview on the quadrant. One point per calendar day up to today."""
    ensure_runner_read_access(db, user, rid)
    from datetime import date, timedelta

    acts_dates = [a[0][:10] for a in db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid).all()]
    if not acts_dates:
        return []
    days = max(7, min(days, 92))
    end = E.today_date()
    start = max(date.fromisoformat(min(acts_dates)) + timedelta(days=42), end - timedelta(days=days - 1))
    asofs = []
    ad = start
    while ad <= end:
        asofs.append(ad)
        ad += timedelta(days=1)
    return [{"date": av["_cut"], "quadrant": av["quadrant"], "overall": av["overall"],
             "tier": av["tier"], "mech": av["mech"], "load": av["load"], "symp": av["symp"],
             "signals": [{"name": s["name"], "pts": s["pts"], "grade": s["grade"]}
                         for s in (av.get("signals") or [])[:5]]}
            for av in _engine_replay(db, rid, asofs)]


@router.get("/{rid}/run-compare/{aid}")
def run_compare(rid: str, aid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """One run's metrics vs. the baseline as of that run's day and a month before."""
    ensure_runner_read_access(db, user, rid)
    return E.run_compare(db, rid, aid)


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
        .filter(models.Activity.runner_id == rid, models.Activity.started_at > cutoff)
        .order_by(models.Activity.started_at.desc()).all()
    )
    return to_dicts([a for a in rows if a.id not in done_ids])


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
    db.commit()
    return E.recompute_assessment(db, rid)


@router.post("/{rid}/checkins", dependencies=[Depends(verify_csrf)])
def create_checkin(rid: str, body: schemas.CheckinRequest, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    pts = body.pain_points or []
    site = body.pain_site or (pts[0].get("region") if pts else None)
    c = models.Checkin(
        runner_id=rid, submitted_at=E.iso_date(E.today_date()), pain_score=body.pain_score,
        pain_site=site, pain_points=pts, soreness=body.soreness, stress=body.stress,
        mood=body.mood, notes=body.notes,
    )
    db.add(c)
    db.commit()
    return E.recompute_assessment(db, rid)
