"""railway#116 — programs the runner starts on their own (ready-made ones for common
running problems, recommended by the pain they marked, or an own pick of exercises)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from .. import durability as DU
from .. import models
from .. import programs_library as PL
from ..db import get_db
from ..deps import ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf
from ..metrics import engine as E

router = APIRouter(prefix="/api/runners", tags=["self-programs"])
MARK_DAYS = 28


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str | None = None
    name: str | None = None
    exercises: list[str] | None = None


class FinishRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    feel: str
    session: str | None = None
    easier: bool = False                     # the next session the lighter version
    sets: dict[str, int] | None = None       # sets ticked per exercise (an exercise not logged as done)


class LogRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exercise: str
    done: bool = True


def _marked_regions(db, rid) -> list[tuple[str, str]]:
    """(submitted_at, region) for every pain mark of the last 4 weeks."""
    cut = E.day_ago(MARK_DAYS)
    out = []
    for m in (models.Checkin, models.ActivityFeedback, models.InjuryReport):
        for r in db.query(m).filter(m.runner_id == rid, m.submitted_at > cut).all():
            out += [(r.submitted_at or "", p.get("region")) for p in (r.pain_points or []) if p.get("region")]
            if getattr(r, "body_region", None):
                out.append((r.submitted_at or "", r.body_region))
    return out


def _regions_by_recency(marks: list[tuple[str, str]]) -> list[str]:
    """railway#133 — the marked regions, the most recently marked first (then the most often)."""
    last: dict[str, str] = {}
    count: dict[str, int] = {}
    for at, reg in marks:
        last[reg] = max(last.get(reg, ""), at)
        count[reg] = count.get(reg, 0) + 1
    return sorted(last, key=lambda r: (last[r], count[r]), reverse=True)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _durability(db, rid, p: models.SelfProgram, today: date) -> dict:
    """The runner's must-have programme: this week's phase, today's session (A / B) and
    its doses — sized by the level the end-of-session feeling set and by the weekly
    strength capacity."""
    st = p.state or {}
    week = DU.week_of(p.started_on, today)
    ph = DU.phase_of(week)
    try:
        a = E.get_or_refresh_assessment(db, rid)
    except Exception:                       # the programme must never fail on the engine
        a = None
    hist = st.get("history") or []
    done_today = next((h for h in reversed(hist) if h["date"] == today.isoformat()), None)
    pick = DU.choose(db, rid, a, st, today)
    if done_today:
        pick = {**pick, "session": done_today["session"], "blocked": "Dnešní trénink programu máte hotový."}
    ses = pick["session"]
    deload = DU.is_deload(week, a)
    level = (st.get("levels") or {}).get(ses, 0)
    # owner request 2026-10-06: the lighter version the runner asked for after the last session
    light = bool(done_today.get("light")) if done_today else bool(st.get("easier"))
    if done_today:
        level = done_today.get("level", level)
    scale, cap = DU.capacity_scale(a, week, level, deload)
    plan = DU.session_plan(ses, week, level, deload or light, scale)
    other = "B" if ses == "A" else "A"
    ws = _week_start(today).isoformat()
    return {
        "week": min(week, DU.WEEKS), "weeks": DU.WEEKS, "finished": week > DU.WEEKS,
        "phase": {"key": ph[2], "name": ph[3], "goal": ph[4], "rpe": ph[5], "from": ph[0], "to": ph[1]},
        "phases": [{"key": x[2], "name": x[3], "from": x[0], "to": x[1], "rpe": x[5]} for x in DU.PHASES],
        "deload": deload, "session": ses, "sessionLabel": DU.SESSIONS[ses]["label"], "why": pick["why"],
        "blocked": pick["blocked"], "level": level, "loadSteps": (st.get("steps") or {}).get(ses, 0),
        "plan": plan, "estMin": DU.estimate_min(ses, plan), "capacity": cap, "scaled": scale < 1.0,
        "weekDone": sum(1 for h in hist if h["date"] >= ws), "perWeek": DU.PER_WEEK,
        "history": hist[-12:], "note": st.get("note") if done_today else None, "doneToday": bool(done_today),
        "noteNext": st.get("noteNext") if done_today else None,
        "light": light, "easierNext": bool(st.get("easier")) and bool(done_today),
        "partialToday": bool(done_today and done_today.get("partial")),
        "completionToday": done_today.get("completion") if done_today else None,
        "otherSession": {"session": other, "label": DU.SESSIONS[other]["label"],
                         "plan": DU.session_plan(other, week, (st.get("levels") or {}).get(other, 0), deload, scale)},
    }


def _out(p: models.SelfProgram, db=None) -> dict:
    today = E.today_date()
    ws = _week_start(today).isoformat()
    log = p.log or {}
    week = {}
    for day, ids in log.items():
        if day >= ws:
            for x in ids:
                week[x] = week.get(x, 0) + 1
    tpl = PL.PROGRAM_BY_KEY.get(p.template or "")
    dur = _durability(db, p.runner_id, p, today) if (p.template == "durability" and db is not None) else None
    exs = [x["id"] for x in dur["plan"]] if dur else [x for x in (p.exercises or []) if x in PL.EXERCISES]
    doses = {x["id"]: x["dose"] for x in dur["plan"]} if dur else {}
    weeks = tpl["weeks"] if tpl else None
    # feedback #170 — the week at a glance (which days were trained), the programme's
    # progress and the next session, for the "trénink hotový" summary
    try:
        week_no = (today - date.fromisoformat(p.started_on)).days // 7 + 1
    except (TypeError, ValueError):
        week_no = 1
    week_days = []
    for k in range(7):
        d = (_week_start(today) + timedelta(days=k)).isoformat()
        n = len([x for x in (log.get(d) or []) if x in exs])
        week_days.append({"date": d, "done": n, "full": bool(exs) and n >= len(exs)})
    left = [x for x in exs if week.get(x, 0) < PL.EXERCISES[x].get("perWeek", 3)]
    next_day = today + timedelta(days=1) if left else _week_start(today) + timedelta(days=7)
    sessions_total = sum(1 for ids in log.values() if exs and set(exs) <= set(ids))
    nxt = {"date": next_day.isoformat(), "exercises": left or exs}
    if dur:
        # two sessions a week, 48 h apart: the next one after today's (or the week's last)
        hist = (p.state or {}).get("history") or []
        sessions_total = len(hist)
        nd = today + timedelta(days=DU.MIN_GAP_DAYS if dur["doneToday"] else 0)
        if dur["weekDone"] >= DU.PER_WEEK or (dur["doneToday"] and dur["weekDone"] + 1 > DU.PER_WEEK):
            nd = max(nd, _week_start(today) + timedelta(days=7))
        o = dur["otherSession"] if dur["doneToday"] else {"plan": dur["plan"]}
        nxt = {"date": nd.isoformat(), "exercises": [x["id"] for x in o["plan"]], "doses": {x["id"]: x["dose"] for x in o["plan"]},
               "session": o.get("session", dur["session"])}
    return {"id": p.id, "template": p.template, "name": p.name, "startedOn": p.started_on, "weeks": weeks,
            "weekNo": week_no, "weeksLeft": (max(0, weeks - week_no) if weeks else None),
            "weekDays": week_days, "sessionsTotal": sessions_total,
            "next": nxt, "durability": dur,
            "exercises": [{"id": x, **PL.EXERCISES[x], **({"dose": doses[x], "perWeek": 1} if x in doses else {}),
                           "doneWeek": week.get(x, 0), "doneToday": x in (log.get(today.isoformat()) or [])}
                          for x in exs]}


@router.get("/{rid}/self-programs")
def get_self_programs(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    # feedback #186 — several programmes can run at once; the newest first
    actives = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid,
                                                   models.SelfProgram.active.is_(True)).order_by(models.SelfProgram.id.desc()).all()
    marks = _marked_regions(db, rid)
    outs = [_out(p, db) for p in actives]
    return {"library": PL.library(), "recommended": PL.programs_for_regions([r for _, r in marks]),
            "regions": _regions_by_recency(marks), "active": outs[0] if outs else None, "actives": outs}


@router.post("/{rid}/self-programs", dependencies=[Depends(verify_csrf)])
def start_self_program(rid: str, body: StartRequest, user: models.User = Depends(get_current_user),
                       db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    if body.template:
        tpl = PL.PROGRAM_BY_KEY.get(body.template)
        if not tpl:
            raise HTTPException(status_code=404, detail="Program nenalezen")
        name, ex = tpl["name"], list(tpl["exercises"])
    else:
        ex = [x for x in dict.fromkeys(body.exercises or []) if x in PL.EXERCISES]
        if not ex:
            raise HTTPException(status_code=422, detail="Vyberte aspoň jeden cvik")
        if len(ex) > 12:
            raise HTTPException(status_code=422, detail="Nejvýš 12 cviků")
        name = (body.name or "").strip()[:60] or "Vlastní trénink"
    # feedback #186 — a new programme doesn't end the others; the same ready-made one isn't started twice
    if body.template:
        same = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid, models.SelfProgram.active.is_(True),
                                                   models.SelfProgram.template == body.template).first()
        if same is not None:
            return _out(same, db)
    p = models.SelfProgram(runner_id=rid, template=body.template if body.template else "custom", name=name, exercises=ex,
                           log={}, started_on=E.today_date().isoformat(), active=True,
                           state={"levels": {"A": 0, "B": 0}, "steps": {"A": 0, "B": 0}, "history": []} if body.template == "durability" else None)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p, db)


@router.patch("/{rid}/self-programs/{pid}/log", dependencies=[Depends(verify_csrf)])
def log_self_program(rid: str, pid: int, body: LogRequest, user: models.User = Depends(get_current_user),
                     db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    p = or_404(db.query(models.SelfProgram).filter(models.SelfProgram.id == pid, models.SelfProgram.runner_id == rid).first(),
               "Program nenalezen")
    if body.exercise not in (p.exercises or []):
        # owner report 2026-10-06: a programme started before an exercise joined its
        # template (pelvic_drop in session B) couldn't log it, so the session never ended
        tpl = PL.PROGRAM_BY_KEY.get(p.template or "")
        known = ({x[0] for s in DU.SESSIONS.values() for x in s["plan"]} if p.template == "durability"
                 else set(tpl["exercises"]) if tpl else set())
        if body.exercise not in known:
            raise HTTPException(status_code=422, detail="Cvik v programu není")
        p.exercises = list(p.exercises or []) + [body.exercise]
    day = E.today_date().isoformat()
    log = dict(p.log or {})
    ids = [x for x in (log.get(day) or []) if x != body.exercise]
    if body.done:
        ids.append(body.exercise)
    log[day] = ids
    p.log = log                      # reassign so the JSON column is saved
    db.commit()
    return _out(p, db)


@router.post("/{rid}/self-programs/{pid}/finish", dependencies=[Depends(verify_csrf)])
def finish_durability_session(rid: str, pid: int, body: FinishRequest, user: models.User = Depends(get_current_user),
                              db: DBSession = Depends(get_db)):
    """The runner's must-have session is over: how it felt moves the progression, and the
    session goes into the load (a strength activity with its session RPE, Foster et al.,
    2001) — or rates the watch's recording of it, when that is already imported."""
    ensure_runner_self(user, rid)
    p = or_404(db.query(models.SelfProgram).filter(models.SelfProgram.id == pid, models.SelfProgram.runner_id == rid).first(),
               "Program nenalezen")
    if p.template != "durability":
        raise HTTPException(status_code=400, detail="Hodnocení tréninku má jen program Runner's must-have")
    if body.feel not in DU.FEEL:
        raise HTTPException(status_code=422, detail="Neznámé hodnocení")
    today = E.today_date()
    t_iso = today.isoformat()
    st = dict(p.state or {})
    hist = list(st.get("history") or [])
    if hist and hist[-1]["date"] == t_iso:      # re-rating today's session: undo its progression first
        last = hist.pop()
        st = {**st, **(last.get("before") or {}), "history": hist}
        ses = last["session"]
    else:
        dur = _durability(db, rid, p, today)
        ses = body.session if body.session in DU.SESSIONS else dur["session"]
    week = DU.week_of(p.started_on, today)
    before = {"levels": dict(st.get("levels") or {"A": 0, "B": 0}), "steps": dict(st.get("steps") or {"A": 0, "B": 0}),
              "easier": bool(st.get("easier"))}
    level = before["levels"].get(ses, 0)
    light = before["easier"]
    try:
        a = E.get_or_refresh_assessment(db, rid)
    except Exception:
        a = None
    deload = DU.is_deload(week, a)
    scale, _cap = DU.capacity_scale(a, week, level, deload)
    plan = DU.session_plan(ses, week, level, deload or light, scale)
    # owner request 2026-10-06: how much of it was done — a logged exercise is whole, the
    # others count the sets ticked on the phone
    logged = set((p.log or {}).get(t_iso) or [])
    ticks = body.sets or {}
    total = sum(x["sets"] for x in plan) or 1
    done = sum(x["sets"] if x["id"] in logged else min(x["sets"], max(0, int(ticks.get(x["id"]) or 0))) for x in plan)
    completion = done / total
    if done == 0:
        raise HTTPException(status_code=422, detail="Zatím není odcvičená žádná série")
    partial = completion < 1.0
    st = DU.progress(st, ses, body.feel, week, partial=partial, completion=completion, easier=body.easier, light=light)
    st["history"][-1]["before"] = before
    # the load: the part of the dose the runner did today, its length and how hard it felt
    minutes = max(5, round(DU.estimate_min(ses, plan) * completion))
    rpe = DU.FEEL[body.feel]
    twin = E.find_twin(db, rid, "strength", t_iso, minutes)
    if twin is None:
        twin = db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == "strength",
                                                models.Activity.provider == "manual",
                                                models.Activity.started_at >= t_iso).first()
    if twin is None:
        twin = models.Activity(runner_id=rid, provider="manual", started_at=t_iso, sport="strength",
                               title=f"Posilování · {DU.SESSIONS[ses]['label']}", duration_min=float(minutes))
        db.add(twin)
        db.flush()
    if twin.provider == "manual":                # the app's own record follows the part that was done
        twin.duration_min = float(minutes)
    twin.strength_focus = twin.strength_focus or DU.SESSIONS[ses]["focus"]
    twin.strength_type = DU.SESSIONS[ses]["type"]
    fb = db.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == twin.id).first()
    if fb is None:
        fb = models.ActivityFeedback(activity_id=twin.id, runner_id=rid, submitted_at=t_iso, pain_points=[])
        db.add(fb)
    fb.rpe = rpe
    fb.note = f"Runner's must-have {ses}: {DU.FEEL_CS[body.feel]}" + (f", hotovo {round(completion * 100)} % sérií" if partial else "")
    if body.feel == "pain":
        fb.niggle = True
    st["history"][-1]["activityId"] = twin.id
    p.state = st
    db.commit()
    E.recompute_assessment(db, rid)
    return _out(p, db)


@router.delete("/{rid}/self-programs/{pid}", dependencies=[Depends(verify_csrf)])
def end_self_program(rid: str, pid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    p = or_404(db.query(models.SelfProgram).filter(models.SelfProgram.id == pid, models.SelfProgram.runner_id == rid).first(),
               "Program nenalezen")
    p.active = False
    db.commit()
    return {"ok": True}
