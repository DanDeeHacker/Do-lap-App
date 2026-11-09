"""Physio brief 2026-11-09 P0.6: a past slot, a duplicate slot and a slot on top of a visit are refused;
a second confirm of a clashing request gets 409 naming the time; the physio can cancel, move, complete
and mark a no-show, each only on their own visits."""
from datetime import datetime, timedelta, timezone

from app import models
from app.metrics import engine as E

from .conftest import login, register

PHYSIO, PID = "havlickova@fyzioholesovice.cz", "phy-0001"


def _at(days=0, hours=0):
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=days, hours=hours)
    return base.isoformat()


def _booking(db, at, status="confirmed", runner="run-0001", mins=45):
    b = models.Booking(runner_id=runner, physio_id=PID, slot_at=at, duration_min=mins, kind="follow_up",
                       status=status, created_at=E.now_iso())
    db.add(b)
    db.commit()
    return b.id


def test_three_slot_rejections(client, db_session):
    login(client, PHYSIO)
    r = client.post(f"/api/physios/{PID}/slots", json={"slot_at": _at(-1), "duration_min": 45})
    assert r.status_code == 422 and "minulosti" in r.json()["detail"]
    at = _at(20, 3)
    assert client.post(f"/api/physios/{PID}/slots", json={"slot_at": at, "duration_min": 45}).status_code == 200
    r = client.post(f"/api/physios/{PID}/slots", json={"slot_at": at, "duration_min": 45})
    assert r.status_code == 409 and "volným termínem" in r.json()["detail"]
    _booking(db_session, _at(21, 3))
    r = client.post(f"/api/physios/{PID}/slots", json={"slot_at": _at(21, 3.5), "duration_min": 45})
    assert r.status_code == 409 and r.json()["detail"].startswith("Koliduje s návštěvou")


def test_second_confirm_of_a_clash_is_409(client, db_session):
    a = _booking(db_session, _at(22, 2), status="requested")
    b = _booking(db_session, (datetime.fromisoformat(_at(22, 2)) + timedelta(minutes=30)).isoformat(),
                 status="requested", runner="run-0002")
    login(client, PHYSIO)
    assert client.post(f"/api/bookings/{a}/confirm").status_code == 200
    r = client.post(f"/api/bookings/{b}/confirm")
    assert r.status_code == 409 and "Koliduje s návštěvou" in r.json()["detail"]


def test_the_database_refuses_two_active_visits_at_one_start(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError
    at = _at(23, 2)
    _booking(db_session, at, status="requested")
    with pytest.raises(IntegrityError):
        _booking(db_session, at, status="requested", runner="run-0002")
    db_session.rollback()


def test_cancel_move_complete_no_show_and_other_physios(client, db_session):
    up = _booking(db_session, _at(24, 2))
    past = _booking(db_session, _at(-3, 2))
    login(client, PHYSIO)
    assert client.post(f"/api/bookings/{up}/cancel", json={"reason": ""}).status_code == 422
    sid = client.post(f"/api/physios/{PID}/slots", json={"slot_at": _at(25, 4), "duration_min": 45}).json()["id"]
    r = client.post(f"/api/bookings/{up}/reschedule", json={"slot_id": sid})
    assert r.status_code == 200 and r.json()["slot_id"] == sid
    assert db_session.get(models.PhysioSlot, sid).status == "booked"
    assert client.post(f"/api/bookings/{up}/complete").status_code == 409          # not started yet
    assert client.post(f"/api/bookings/{past}/complete").json()["status"] == "completed"
    assert client.post(f"/api/bookings/{past}/no-show").json()["status"] == "no_show"
    r = client.post(f"/api/bookings/{up}/cancel", json={"reason": "Nemoc"})
    assert r.json()["status"] == "cancelled" and db_session.get(models.PhysioSlot, sid).status == "open"
    # another physio: none of the four
    other = _booking(db_session, _at(26, 2))
    register(client, "jiny-fyzio-p06@test.cz", "Jiný Fyzio", "physio", "testpass123")
    me = db_session.query(models.User).filter_by(email="jiny-fyzio-p06@test.cz").first()
    db_session.get(models.Physio, me.physio_id).verified_at = E.now_iso()
    db_session.commit()
    for path, body in (("cancel", {"reason": "x"}), ("reschedule", {"starts_at": _at(27)}), ("complete", None), ("no-show", None)):
        assert client.post(f"/api/bookings/{other}/{path}", json=body).status_code == 403, path
