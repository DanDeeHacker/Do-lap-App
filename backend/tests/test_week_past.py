"""railway#216 — Trénink → Týden od pondělí: the weeks before this one, day by day."""
from datetime import date, timedelta

from app import models
from app.metrics import engine as E
from app.metrics import guidance as G
from .test_guidance import _guide, _runner


def test_past_weeks(client, db_session):
    rid, r = _runner(client, db_session, "wpast1@test.cz", days=70)
    g = _guide(db_session, rid, r)
    past = g["week"]["past"]
    assert 1 <= len(past) <= G.PAST_WEEKS
    today = E.today_date()
    mon = today - timedelta(days=today.weekday())
    assert past[0]["start"] == (mon - timedelta(days=7)).isoformat() and len(past[0]["days"]) == 7
    # the km of last week's runs, day by day, as the runs say
    for wk in past[:3]:
        lo = date.fromisoformat(wk["start"])
        for k, d in enumerate(wk["days"]):
            day = (lo + timedelta(days=k)).isoformat()
            km = sum(a.distance_km or 0 for a in db_session.query(models.Activity).filter(
                models.Activity.runner_id == rid, models.Activity.sport == "running")
                if a.started_at[:10] == day and E.counts_for(a, "load"))
            assert abs((d["by"]["volume"].get("run") or 0) - km) < 0.15
