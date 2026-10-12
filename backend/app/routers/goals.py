"""Trénink k cíli, stage 1 (owner request 2026-10-12): the goal, its requirements and the
feasibility answer (metrics/goal_plan.py). Advice only — the plan doesn't change yet.

GET    /api/runners/{rid}/goal           the active goal with today's answer, and the races to pick from
POST   /api/runners/{rid}/goal/preview   the answer for a goal being entered, nothing stored
PUT    /api/runners/{rid}/goal           store it as the active goal (the previous one is cancelled)
DELETE /api/runners/{rid}/goal           cancel the active goal
"""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..assistant import knowledge as K
from ..db import get_db
from ..deps import ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf
from ..metrics import engine as E
from ..metrics import goal_plan as GP

router = APIRouter(tags=["goals"])
MAX_DAYS = 2 * 365


class FreeIn(BaseModel):
    weekly_km: float | None = Field(None, gt=0, le=250)
    long_km: float | None = Field(None, gt=0, le=150)
    climb_m: float | None = Field(None, gt=0, le=20000)
    climb_scope: Literal["week", "run"] = "week"


class GoalIn(BaseModel):
    kind: Literal["race", "free"] = "race"
    race_id: int | None = None
    name: str | None = Field(None, max_length=120)
    date: str
    km: float | None = Field(None, gt=0, le=250)
    ascent_m: float | None = Field(None, ge=0, le=20000)
    descent_m: float | None = Field(None, ge=0, le=20000)
    terrain: Literal["road", "trail"] | None = None
    aim: Literal["finish", "time"] = "finish"
    target_time_s: int | None = Field(None, gt=0, le=60 * 3600)
    free: FreeIn | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _race(db: DBSession, rid: str, race_id: int | None):
    if race_id is None:
        return None
    return or_404(db.query(models.Race).filter(models.Race.id == race_id, models.Race.runner_id == rid).first(),
                  "Závod nenalezen")


def _goal_of(db: DBSession, rid: str, body: GoalIn) -> dict:
    """The request as the dict goal_plan takes, the race's numbers filled in where the runner left them out."""
    try:
        d = date.fromisoformat(body.date[:10])
    except ValueError:
        raise HTTPException(422, "Neplatné datum")
    today = E.today_date()
    if d <= today:
        raise HTTPException(422, "Datum cíle musí být v budoucnosti")
    if (d - today).days > MAX_DAYS:
        raise HTTPException(422, "Cíl může být nejvýš 2 roky dopředu")
    race = _race(db, rid, body.race_id) if body.kind == "race" else None
    g = {"kind": body.kind, "raceId": race.id if race else None, "name": body.name or (race.name if race else None),
         "date": d.isoformat(), "km": body.km, "ascentM": body.ascent_m, "descentM": body.descent_m,
         "terrain": body.terrain, "aim": body.aim, "targetTimeS": body.target_time_s, "free": {}}
    if race:
        g["km"] = g["km"] or race.distance_km
        g["ascentM"] = g["ascentM"] if g["ascentM"] is not None else race.ascent_m
    if body.kind == "race" and not g["km"]:
        raise HTTPException(422, "Zadejte délku závodu")
    if body.kind == "free":
        f = body.free or FreeIn()
        g["free"] = {"weeklyKm": f.weekly_km, "longKm": f.long_km, "climbM": f.climb_m, "climbScope": f.climb_scope}
        if not (f.weekly_km or f.long_km or f.climb_m):
            raise HTTPException(422, "Zadejte aspoň jedno číslo cíle")
        g["km"] = None
    return g


def _answer(db: DBSession, rid: str, goal: dict) -> dict:
    a = E.get_or_refresh_assessment(db, rid)
    st = GP.runner_state(db, rid, a)
    out = GP.evaluate(goal, st)
    out["computedOn"] = st["today"]
    ids = set(out.get("sources") or []) | {s for n in out.get("notes") or [] for s in n.get("sources") or []}
    ids |= {s for x in out.get("alternatives") or [] for s in x.get("sources") or []}
    out["sourceInfo"] = {i: {"cite": K.summary_by_id()[i]["cite"], "url": K.summary_by_id()[i].get("url")}
                         for i in sorted(ids) if i in K.summary_by_id()}
    return out


def _active(db: DBSession, rid: str):
    return (db.query(models.Goal).filter(models.Goal.runner_id == rid, models.Goal.status == "active")
            .order_by(models.Goal.id.desc()).first())


def _races(db: DBSession, rid: str) -> list:
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    return [x for x in E.races_for(db, r) if (x.get("daysTo") or 0) > 0 and x.get("source") == "calendar"]


@router.get("/api/runners/{rid}/goal")
def get_goal(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    g = _active(db, rid)
    out = {"goal": None, "result": None, "races": _races(db, rid)}
    if g is None:
        return out
    race = db.query(models.Race).filter(models.Race.id == g.race_id).first() if g.race_id else None
    goal = GP.goal_dict(g, race)
    res = g.projection_json or {}
    if res.get("computedOn") != E.today_date().isoformat():
        res = _answer(db, rid, goal)
        if user.runner_id == rid:
            g.projection_json = res
            db.commit()
    out.update(goal=goal, result=res)
    return out


@router.post("/api/runners/{rid}/goal/preview", dependencies=[Depends(verify_csrf)])
def preview_goal(rid: str, body: GoalIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    return _answer(db, rid, _goal_of(db, rid, body))


@router.put("/api/runners/{rid}/goal", dependencies=[Depends(verify_csrf)])
def save_goal(rid: str, body: GoalIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    goal = _goal_of(db, rid, body)
    res = _answer(db, rid, goal)
    now = _now()
    for old in db.query(models.Goal).filter(models.Goal.runner_id == rid, models.Goal.status == "active"):
        old.status, old.updated_at = "cancelled", now
    f = goal["free"] or {}
    g = models.Goal(runner_id=rid, kind=goal["kind"], race_id=goal["raceId"], name=goal["name"], date=goal["date"],
                    distance_km=goal["km"], ascent_m=goal["ascentM"], descent_m=goal["descentM"], terrain=goal["terrain"],
                    aim=goal["aim"], target_time_s=goal["targetTimeS"], free_json=f or None, path="safe",
                    status="active", projection_json=res, created_at=now, updated_at=now)
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"goal": GP.goal_dict(g), "result": res, "races": _races(db, rid)}


@router.delete("/api/runners/{rid}/goal", dependencies=[Depends(verify_csrf)])
def cancel_goal(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    g = _active(db, rid)
    if g is not None:
        g.status, g.updated_at = "cancelled", _now()
        db.commit()
    return {"goal": None, "result": None, "races": _races(db, rid)}
