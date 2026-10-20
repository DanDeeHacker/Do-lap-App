"""Admin view for the app's owners (DOSSLAP_OWNER_EMAILS): the registered runners,
and — through deps.ensure_runner_read_access — a read-only view of any of them
("Zobrazit jako"). Writes stay with the runner (ensure_runner_self /
ensure_runner_write_access), and every view lands in the runner's access log
(models.AdminAccessLog, main.audit_access)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import GUEST_PROVIDER, get_current_user, is_owner, tutorial_demo_runner_id

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_owner(user: models.User = Depends(get_current_user)) -> models.User:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Jen pro správce aplikace")
    return user


@router.get("/runners")
def list_runners(user: models.User = Depends(require_owner), db: DBSession = Depends(get_db)):
    """Every registered runner account (not the tour demo, not guest sessions), with
    what the owner needs to pick one: name, e-mail, when they joined, their last
    activity / check-in and today's state. Newest activity first."""
    demo_rid = tutorial_demo_runner_id(db)
    users = (db.query(models.User).filter(models.User.role == "runner", models.User.runner_id.isnot(None),
                                          or_(models.User.provider.is_(None), models.User.provider != GUEST_PROVIDER)).all())
    rids = [u.runner_id for u in users if u.runner_id != demo_rid]
    if not rids:
        return {"items": []}
    last_act = dict(db.query(models.Activity.runner_id, func.max(models.Activity.started_at))
                    .filter(models.Activity.runner_id.in_(rids)).group_by(models.Activity.runner_id).all())
    n_act = dict(db.query(models.Activity.runner_id, func.count(models.Activity.id))
                 .filter(models.Activity.runner_id.in_(rids)).group_by(models.Activity.runner_id).all())
    last_ci = dict(db.query(models.Checkin.runner_id, func.max(models.Checkin.submitted_at))
                   .filter(models.Checkin.runner_id.in_(rids)).group_by(models.Checkin.runner_id).all())
    runners = {r.id: r for r in db.query(models.Runner).filter(models.Runner.id.in_(rids)).all()}
    state = {a.runner_id: a for a in db.query(models.Assessment).filter(models.Assessment.runner_id.in_(rids)).all()}
    items = []
    for u in users:
        rid = u.runner_id
        if rid not in runners:
            continue
        r, a = runners[rid], state.get(rid)
        items.append({
            "runnerId": rid, "name": u.name or r.name, "email": u.email, "joined": u.created_at,
            "demo": (u.email or "").lower().endswith("@demo.cz"), "self": u.id == user.id,
            "engineMode": r.engine_mode, "activities": n_act.get(rid, 0),
            "lastActivity": last_act.get(rid), "lastCheckin": last_ci.get(rid),
            "quadrant": a.quadrant if a else None, "tier": a.tier if a else None,
            "overall": a.overall if a else None,
        })
    items.sort(key=lambda x: (x["demo"], -(int((x["lastActivity"] or "0000")[:10].replace("-", "")))))
    return {"items": items}


@router.get("/goal-kpis")
def goal_kpis(replay: bool = False, user: models.User = Depends(require_owner), db: DBSession = Depends(get_db)):
    """Plan k cíli 2.0 #20: the goals' outcomes against the targets and the chance's calibration;
    with `replay`, the planner's 8-week projection against the capacity the runners really have."""
    from ..metrics import goal_backtest as GB
    out = {"outcomes": GB.outcome_kpis(db)}
    if replay:
        out["projection"] = GB.projection_kpis(db)
    return out


@router.get("/engagement")
def engagement(days: int = 30, hours: int | None = None, user: models.User = Depends(require_owner),
               db: DBSession = Depends(get_db)):
    """How the runners use the app over the last `days` days (models.UsageDay): app opens, active
    days, foreground minutes in use, the average visit, minutes per tab, feature opens, the last
    active day and the opens of the period before (the trend). Not the tour demo or guests.
    With `hours` (railway#218: the last 24 h) the window is that many hours back from now by the
    rows' local hour; a row from before the hour was recorded counts as midday."""
    from datetime import datetime, timedelta
    from ..metrics import engine as E
    days = max(1, min(int(days), 180))
    today = E.today_date()
    lo = (today - timedelta(days=days - 1)).isoformat()
    lo_prev = (today - timedelta(days=2 * days - 1)).isoformat()
    in_cur = lambda r: r.day >= lo
    in_prev = lambda r: r.day < lo
    if hours:
        hours = max(1, min(int(hours), 72))
        now = datetime.now(E.LOCAL_TZ).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        start, start_prev = now - timedelta(hours=hours - 1), now - timedelta(hours=2 * hours - 1)
        at = lambda r: datetime.fromisoformat(r.day) + timedelta(hours=12 if r.hour is None else r.hour)
        in_cur = lambda r: start <= at(r) <= now
        in_prev = lambda r: start_prev <= at(r) < start
        lo, lo_prev = start.date().isoformat(), start_prev.date().isoformat()
    demo_rid = tutorial_demo_runner_id(db)
    users = (db.query(models.User).filter(models.User.role == "runner", models.User.runner_id.isnot(None),
                                          or_(models.User.provider.is_(None), models.User.provider != GUEST_PROVIDER)).all())
    users = [u for u in users if u.runner_id != demo_rid]
    names = {r.id: r.name for r in db.query(models.Runner).filter(models.Runner.id.in_([u.runner_id for u in users])).all()} if users else {}
    rows = (db.query(models.UsageDay).filter(models.UsageDay.user_id.in_([u.id for u in users]),
                                             models.UsageDay.day >= lo_prev).all()) if users else []
    by_user: dict = {}
    for r in rows:
        by_user.setdefault(r.user_id, []).append(r)
    items, tab_tot, active_ids = [], {}, set()
    for u in users:
        rs = by_user.get(u.id, [])
        cur = [r for r in rs if in_cur(r)]
        prev_opens = sum(r.views or 0 for r in rs if in_prev(r) and r.tab == "_app")
        tabs, feats, opens, secs, act_days = {}, {}, 0, 0, set()
        for r in cur:
            if r.tab == "_app":
                opens += r.views or 0
                act_days.add(r.day)
            elif r.tab.startswith("f:"):
                feats[r.tab[2:]] = feats.get(r.tab[2:], 0) + (r.views or 0)
            else:
                tabs[r.tab] = tabs.get(r.tab, 0) + (r.seconds or 0)
                secs += r.seconds or 0
                if (r.seconds or 0) > 0:
                    act_days.add(r.day)
        for k, v in tabs.items():
            tab_tot[k] = tab_tot.get(k, 0) + v
        if opens or secs:
            active_ids.add(u.id)
        items.append({"runnerId": u.runner_id, "name": names.get(u.runner_id) or u.email, "email": u.email,
                      "opens": opens, "opensPrev": prev_opens, "activeDays": len(act_days),
                      "minutes": round(secs / 60, 1), "avgVisitMin": round(secs / 60 / opens, 1) if opens else None,
                      "tabs": {k: round(v / 60, 1) for k, v in sorted(tabs.items(), key=lambda kv: -kv[1])},
                      "features": feats, "lastActive": max(act_days) if act_days else None})
    items.sort(key=lambda x: (-x["minutes"], -x["opens"], x["name"] or ""))
    return {"days": days, "hours": hours, "from": lo, "to": today.isoformat(), "users": len(users), "activeUsers": len(active_ids),
            "tabs": {k: round(v / 60, 1) for k, v in sorted(tab_tot.items(), key=lambda kv: -kv[1])},
            "items": items}
