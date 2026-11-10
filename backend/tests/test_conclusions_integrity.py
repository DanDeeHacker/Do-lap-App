"""Physio brief 2026-11-09 P0.5: the visit record — opening it stores nothing, it is approved only
after the visit, the injury is dated by the visit, the OSTRC outcome counts only when it is chosen
and complete, the client never receives the clinical finding, and a physio-confirmed injury is
closed by the physio."""
from datetime import datetime, timedelta, timezone

from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RUNNER, RID = "havlickova@fyzioholesovice.cz", "adela@demo.cz", "run-0001"


def _booking(db, days=-2, status="confirmed"):
    at = (datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
          + timedelta(days=days)).isoformat()
    b = models.Booking(runner_id=RID, physio_id="phy-0001", slot_at=at, kind="follow_up", status=status,
                       created_at=E.now_iso())
    db.add(b)
    db.commit()
    return b.id


def test_opening_stores_nothing_and_the_first_save_does(client, db_session):
    bid = _booking(db_session)
    login(client, PHYSIO)
    r = client.post(f"/api/bookings/{bid}/conclusion").json()
    assert r["id"] is None and r["status"] == "new"
    assert db_session.query(models.Conclusion).filter_by(booking_id=bid).count() == 0
    r = client.post(f"/api/bookings/{bid}/conclusion/draft", json={"summary": "Shrnutí"}).json()
    assert r["id"] and r["status"] == "draft"
    assert db_session.query(models.Conclusion).filter_by(booking_id=bid).count() == 1


def test_a_future_visit_cannot_be_approved(client, db_session):
    bid = _booking(db_session, days=3)
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft", json={"summary": "Předem"}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": True})
    assert r.status_code == 409 and "začátku návštěvy" in r.json()["detail"]


def test_injury_needs_a_complete_outcome_and_is_dated_by_the_visit(client, db_session):
    bid = _booking(db_session, days=-10)
    visit_day = db_session.get(models.Booking, bid).slot_at[:10]
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft",
                      json={"summary": "Přetížení Achillovy šlachy.", "finding": "Citlivost úponu vpravo",
                            "outcome_kind": "injury", "out_participation": 8, "out_volume": 8}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": True})
    assert r.status_code == 422                                  # two answers, region and side missing
    client.patch(f"/api/conclusions/{cid}", json={"out_performance": 8, "out_pain": 17,
                                                   "out_region": "achilles", "out_side": "P"})
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": True}).json()
    assert r["status"] == "approved" and r["out_severity"] == 41
    rep = db_session.get(models.InjuryReport, r["injury_report_id"])
    assert rep.submitted_at[:10] == visit_day and rep.confirmed and rep.body_region == "Achillova šlacha"
    assert db_session.get(models.Booking, bid).status == "completed"
    # the client: the summary, never the finding
    login(client, RUNNER)
    assert "finding" not in client.get(f"/api/conclusions/{cid}").json()
    boot = client.get(f"/api/runners/{RID}/bootstrap").json()
    mine = next(c for c in boot["conclusions"] if c["id"] == cid)
    assert mine["summary"] and "finding" not in mine and "out_pain" not in mine and "transcript" not in mine
    # the client cannot close it, the physio can
    client.post(f"/api/runners/{RID}/injury-report", json={"kind": "adhoc", "q_participation": 0, "q_volume": 0,
                                                           "q_performance": 0, "q_pain": 0, "resolve": True})
    db_session.expire_all()
    assert db_session.get(models.InjuryReport, rep.id).status == "active"
    login(client, PHYSIO)
    r = client.post(f"/api/physios/me/clients/{RID}/injuries/{rep.id}/close")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"


def test_no_injury_is_an_explicit_choice_and_the_summary_can_wait(client, db_session):
    bid = _booking(db_session, days=-5)
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft",
                      json={"finding": "Bez nálezu", "outcome_kind": "no_injury"}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": False}).json()
    assert r["status"] == "approved" and r["shared_at"] is None and r["out_severity"] == 0
    assert db_session.get(models.InjuryReport, r["injury_report_id"]).status == "none"
    login(client, RUNNER)
    assert client.get(f"/api/conclusions/{cid}").status_code == 403         # not sent yet
