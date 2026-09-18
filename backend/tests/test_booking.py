"""Consent-driven booking flow: consent gate → browse → request → physio
confirm → mutual calendar + care access, plus decline (physio), cancel
(runner), reject-physio (runner revokes access), slot management and the
day-before reminder.
"""
from datetime import datetime, timedelta, timezone

from .conftest import login, register

PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"   # phy-0001
PHYSIO_ID = "phy-0001"


def _future(days=3, hour=10):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _in_hours(h):
    return (datetime.now(timezone.utc) + timedelta(hours=h)).isoformat()


def _add_slot(client, slot_at):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    return client.post(f"/api/physios/{PHYSIO_ID}/slots", json={"slot_at": slot_at}).json()


def _fresh_consented_runner(client, email):
    rid = register(client, email, "Booking Runner", "runner").json()["runner_id"]
    r = client.post(f"/api/runners/{rid}/physio-interest", json={"interested": True})
    assert r.status_code == 200 and r.json()["physio_interest"] is True
    return rid


def test_options_require_consent(client):
    rid = register(client, "noconsent@test.cz", "No Consent", "runner").json()["runner_id"]
    assert client.get("/api/booking/options").status_code == 409
    client.post(f"/api/runners/{rid}/physio-interest", json={"interested": True})
    assert client.get("/api/booking/options").status_code == 200


def test_full_booking_flow_confirm_then_reject(client):
    slot = _add_slot(client, _future(3))
    sid = slot["id"]
    rid = _fresh_consented_runner(client, "book1@test.cz")

    # the slot shows up in the browse options
    opts = client.get("/api/booking/options").json()
    mine = next((p for p in opts if p["id"] == PHYSIO_ID), None)
    assert mine and mine["bio"] and any(s["id"] == sid for s in mine["slots"])

    # request it → pending, slot held
    b = client.post("/api/booking/request", json={"slot_id": sid, "kind": "assessment"}).json()
    bid = b["id"]
    assert b["status"] == "requested"

    # physio can't read the runner yet (no care assignment until confirm)
    login(client, PHYSIO_EMAIL, expected_role="physio")
    assert client.get(f"/api/runners/{rid}").status_code == 403
    boot = client.get(f"/api/physios/{PHYSIO_ID}/bootstrap").json()
    assert any(x["id"] == bid for x in boot["requests"])

    # confirm → both sides, care access granted
    conf = client.post(f"/api/bookings/{bid}/confirm").json()
    assert conf["status"] == "confirmed"
    assert client.get(f"/api/runners/{rid}").status_code == 200

    login(client, "book1@test.cz", "testpass123")
    assert any(x["id"] == bid and x["status"] == "confirmed"
               for x in client.get(f"/api/runners/{rid}/bookings").json())

    # runner rejects the physio → access revoked, booking cancelled
    dec = client.post(f"/api/runners/{rid}/physios/{PHYSIO_ID}/decline")
    assert dec.status_code == 200 and dec.json()["revoked"] == 1
    login(client, PHYSIO_EMAIL, expected_role="physio")
    assert client.get(f"/api/runners/{rid}").status_code == 403


def test_physio_decline_frees_slot(client):
    slot = _add_slot(client, _future(4))
    sid = slot["id"]
    rid = _fresh_consented_runner(client, "book2@test.cz")
    bid = client.post("/api/booking/request", json={"slot_id": sid}).json()["id"]

    login(client, PHYSIO_EMAIL, expected_role="physio")
    d = client.post(f"/api/bookings/{bid}/decline").json()
    assert d["status"] == "declined"
    # slot is open again and re-appears in options
    login(client, "book2@test.cz", "testpass123")
    opts = client.get("/api/booking/options").json()
    assert any(s["id"] == sid for p in opts for s in p["slots"])


def test_runner_cancel_frees_slot(client):
    slot = _add_slot(client, _future(5))
    sid = slot["id"]
    rid = _fresh_consented_runner(client, "book3@test.cz")
    bid = client.post("/api/booking/request", json={"slot_id": sid}).json()["id"]
    c = client.post(f"/api/runners/{rid}/bookings/{bid}/cancel").json()
    assert c["status"] == "cancelled"
    opts = client.get("/api/booking/options").json()
    assert any(s["id"] == sid for p in opts for s in p["slots"])


def test_day_before_reminder_surfaces(client):
    slot = _add_slot(client, _in_hours(2))   # within the next 24h → reminder due
    sid = slot["id"]
    rid = _fresh_consented_runner(client, "book4@test.cz")
    bid = client.post("/api/booking/request", json={"slot_id": sid}).json()["id"]
    login(client, PHYSIO_EMAIL, expected_role="physio")
    client.patch(f"/api/bookings/{bid}/prep", json={"prep_info": "Přijďte 10 min předem, vezměte běžecké boty."})
    client.post(f"/api/bookings/{bid}/confirm")

    login(client, "book4@test.cz", "testpass123")
    boot = client.get(f"/api/runners/{rid}/bootstrap").json()
    rem = [r for r in boot["reminders"] if r["booking_id"] == bid]
    assert rem and "běžecké boty" in (rem[0]["prep_info"] or "")


def test_slot_add_and_delete(client):
    slot = _add_slot(client, _future(6))
    sid = slot["id"]
    assert slot["status"] == "open"
    assert any(s["id"] == sid for s in client.get(f"/api/physios/{PHYSIO_ID}/slots").json())
    assert client.delete(f"/api/physios/slots/{sid}").status_code == 200
    assert not any(s["id"] == sid for s in client.get(f"/api/physios/{PHYSIO_ID}/slots").json())
