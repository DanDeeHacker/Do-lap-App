"""railway#116 — programs the runner starts on their own (ready-made ones for common
running problems, recommended by the pain they marked, or an own pick of exercises)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

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


def _out(p: models.SelfProgram) -> dict:
    today = E.today_date()
    ws = _week_start(today).isoformat()
    log = p.log or {}
    week = {}
    for day, ids in log.items():
        if day >= ws:
            for x in ids:
                week[x] = week.get(x, 0) + 1
    tpl = PL.PROGRAM_BY_KEY.get(p.template or "")
    exs = [x for x in (p.exercises or []) if x in PL.EXERCISES]
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
    return {"id": p.id, "template": p.template, "name": p.name, "startedOn": p.started_on, "weeks": weeks,
            "weekNo": week_no, "weeksLeft": (max(0, weeks - week_no) if weeks else None),
            "weekDays": week_days, "sessionsTotal": sum(1 for ids in log.values() if exs and set(exs) <= set(ids)),
            "next": {"date": next_day.isoformat(), "exercises": left or exs},
            "exercises": [{"id": x, **PL.EXERCISES[x], "doneWeek": week.get(x, 0), "doneToday": x in (log.get(today.isoformat()) or [])}
                          for x in exs]}


@router.get("/{rid}/self-programs")
def get_self_programs(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    active = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid,
                                                  models.SelfProgram.active.is_(True)).order_by(models.SelfProgram.id.desc()).first()
    marks = _marked_regions(db, rid)
    return {"library": PL.library(), "recommended": PL.programs_for_regions([r for _, r in marks]),
            "regions": _regions_by_recency(marks), "active": _out(active) if active else None}


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
    for old in db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid, models.SelfProgram.active.is_(True)):
        old.active = False
    p = models.SelfProgram(runner_id=rid, template=body.template if body.template else "custom", name=name, exercises=ex,
                           log={}, started_on=E.today_date().isoformat(), active=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.patch("/{rid}/self-programs/{pid}/log", dependencies=[Depends(verify_csrf)])
def log_self_program(rid: str, pid: int, body: LogRequest, user: models.User = Depends(get_current_user),
                     db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    p = or_404(db.query(models.SelfProgram).filter(models.SelfProgram.id == pid, models.SelfProgram.runner_id == rid).first(),
               "Program nenalezen")
    if body.exercise not in (p.exercises or []):
        raise HTTPException(status_code=422, detail="Cvik v programu není")
    day = E.today_date().isoformat()
    log = dict(p.log or {})
    ids = [x for x in (log.get(day) or []) if x != body.exercise]
    if body.done:
        ids.append(body.exercise)
    log[day] = ids
    p.log = log                      # reassign so the JSON column is saved
    db.commit()
    return _out(p)


@router.delete("/{rid}/self-programs/{pid}", dependencies=[Depends(verify_csrf)])
def end_self_program(rid: str, pid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    p = or_404(db.query(models.SelfProgram).filter(models.SelfProgram.id == pid, models.SelfProgram.runner_id == rid).first(),
               "Program nenalezen")
    p.active = False
    db.commit()
    return {"ok": True}
