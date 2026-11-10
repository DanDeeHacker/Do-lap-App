"""Physio brief round 2 F14: the calendar grid's data (working hours with the bookings), moving a visit to any time
(outside working hours it says so, a clash is 409), and the stale-data state instead of a score."""
from datetime import datetime, timedelta, timezone

from app import models
from app import work as W
from app.metrics import engine as E

from .conftest import login

PHYSIO, PID, RID = "havlickova@fyzioholesovice.cz", "phy-0001", "run-0001"


def _visit(db, days, hour, minute=0):
    at = (datetime.now(E.LOCAL_TZ) + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    b = models.Booking(runner_id=RID, physio_id=PID, slot_at=at.astimezone(timezone.utc).isoformat(), duration_min=45,
                       kind="follow_up", status="confirmed", created_at=E.now_iso())
    db.add(b)
    db.commit()
    return b


def test_calendar_carries_working_hours(client):
    login(client, PHYSIO)
    d = client.get(f"/api/physios/{PID}/calendar").json()
    assert d["rules"] and {"weekday", "start", "end"} <= set(d["rules"][0])


def test_move_to_any_time_warns_outside_hours_and_refuses_a_clash(client, db_session):
    a, b = _visit(db_session, 20, 6, 13), _visit(db_session, 20, 9, 7)
    login(client, PHYSIO)
    late = (datetime.now(E.LOCAL_TZ) + timedelta(days=21)).replace(hour=21, minute=31, second=0, microsecond=0)
    r = client.post(f"/api/bookings/{a.id}/reschedule", json={"starts_at": late.isoformat()})
    assert r.status_code == 200 and r.json()["outside_hours"] is True
    r = client.post(f"/api/bookings/{a.id}/reschedule", json={"starts_at": datetime.fromisoformat(b.slot_at).isoformat()})
    assert r.status_code == 409
    for x in (a, b):
        db_session.get(models.Booking, x.id).status = "cancelled"
    db_session.commit()


def test_within_hours(db_session):
    rule = db_session.query(models.AvailabilityRule).filter_by(physio_id=PID, active=True).first()
    d = E.today_date()
    while d.weekday() != rule.weekday:
        d += timedelta(days=1)
    start = W._local(d, rule.start_local)
    assert W.within_hours(db_session, PID, start, 30)
    assert not W.within_hours(db_session, PID, start - timedelta(minutes=30), 30)


def test_upcoming_visits_carry_freshness(client):
    login(client, PHYSIO)
    boot = client.get(f"/api/physios/{PID}/bootstrap").json()
    with_a = [b for b in boot["bookings"] if b.get("assessment")]
    assert with_a and all("freshness" in b["assessment"] for b in with_a)
