"""Physio brief round 2 F19: the checks that could be run from the code. Unsigned-record reminders go out at 17:00
and at 21:00 local time, once each; a physio with fewer than five reviews shows no rating."""
from datetime import datetime, timedelta, timezone

from app import models
from app import work as W
from app.metrics import engine as E

from .test_booking import _fresh_consented_runner

PID = "phy-0001"


def test_unsigned_reminders_at_17_and_21_once_each(client, db_session):
    day = E.today_date() + timedelta(days=3)
    visit = datetime.combine(day, datetime.min.time(), E.LOCAL_TZ).replace(hour=9, minute=11)
    b = models.Booking(runner_id="run-0001", physio_id=PID, slot_at=visit.astimezone(timezone.utc).isoformat(),
                       duration_min=45, kind="follow_up", status="confirmed", created_at=E.now_iso())
    db_session.add(b)
    db_session.commit()
    try:
        with E.sim_clock(visit.replace(hour=16, minute=59)):
            assert W.unsigned_reminders(db_session, PID) == 0
        with E.sim_clock(visit.replace(hour=17, minute=1)):
            assert W.unsigned_reminders(db_session, PID) == 1
            assert W.unsigned_reminders(db_session, PID) == 0          # once
        with E.sim_clock(visit.replace(hour=21, minute=5)):
            assert W.unsigned_reminders(db_session, PID) == 1
        refs = {n.ref for n in db_session.query(models.Notification).filter_by(physio_id=PID, event="note_unsigned").all()}
        assert {f"unsigned:{day.isoformat()}:17", f"unsigned:{day.isoformat()}:21"} <= refs
    finally:
        b.status = "cancelled"
        db_session.commit()


def test_rating_hidden_below_five_reviews(client, db_session):
    p = db_session.get(models.Physio, PID)
    p.rating, p.rating_count = 4.9, 0
    db_session.commit()
    _fresh_consented_runner(client, "hodnoceni-f19@test.cz")
    mine = next(x for x in client.get("/api/booking/options").json() if x["id"] == PID)
    assert mine["rating"] is None
