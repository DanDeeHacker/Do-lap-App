"""Engagement tracking for the owners' overview (models.UsageDay): the app sends what it counted
every minute and when it goes to the background — foreground seconds per tab while in use, the
views, the app opens and a few features' opens. Not sent from the demo or while an owner views
another runner's data."""
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import get_current_user, verify_csrf
from ..metrics import engine as E

router = APIRouter(tags=["usage"])
KEY = re.compile(r"^(_app|f:[a-z][a-z0-9-]{0,23}|[a-z][a-z0-9-]{0,23})$")
MAX_S = 3600        # seconds per tab in one batch (a minute's batch, generous for a missed one)


class TabIn(BaseModel):
    s: float = Field(0, ge=0, le=MAX_S)
    v: int = Field(0, ge=0, le=500)


class UsageIn(BaseModel):
    day: str
    hour: int | None = Field(None, ge=0, le=23)     # the local hour of the batch (older apps don't send it)
    opens: int = Field(0, ge=0, le=20)
    tabs: dict[str, TabIn] = Field(default_factory=dict, max_length=30)


@router.post("/api/usage", dependencies=[Depends(verify_csrf)])
def post_usage(body: UsageIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    try:
        d = date.fromisoformat(body.day[:10])
    except ValueError:
        raise HTTPException(422, "Neplatné datum")
    today = E.today_date()
    if not (today - timedelta(days=2) <= d <= today + timedelta(days=1)):
        return {"ok": False}
    rows = {k: v for k, v in body.tabs.items() if KEY.match(k) and (v.s >= 1 or v.v)}
    if body.opens:
        rows["_app"] = TabIn(s=0, v=body.opens)
    if not rows:
        return {"ok": True}
    have = {u.tab: u for u in db.query(models.UsageDay).filter(models.UsageDay.user_id == user.id,
                                                               models.UsageDay.day == d.isoformat(),
                                                               models.UsageDay.hour.is_(body.hour) if body.hour is None
                                                               else models.UsageDay.hour == body.hour,
                                                               models.UsageDay.tab.in_(list(rows))).all()}
    for k, v in rows.items():
        u = have.get(k)
        if u is None:
            u = models.UsageDay(user_id=user.id, day=d.isoformat(), hour=body.hour, tab=k, seconds=0, views=0)
            db.add(u)
        u.seconds = (u.seconds or 0) + int(round(v.s))
        u.views = (u.views or 0) + v.v
    db.commit()
    return {"ok": True}
