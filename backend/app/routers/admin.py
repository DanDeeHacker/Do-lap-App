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
