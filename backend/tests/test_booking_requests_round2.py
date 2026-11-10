"""Physio brief round 2 F13: a request shows what the client asked for; the server derives the kind from the
service; times fit the service's length; the runner sees 'od {lowest price}' and the booking stores that price;
the bell names the client and the time; a first visit at a clinic adds an intake that prefills Karta klienta."""
from datetime import datetime

from app import models
from app.metrics import engine as E

from .conftest import login
from .test_booking import _fresh_consented_runner

PHYSIO, PID = "havlickova@fyzioholesovice.cz", "phy-0001"


def test_request_detail_kind_price_and_bell(client, db_session):
    _fresh_consented_runner(client, "zadost-f13@test.cz")
    opts = client.get("/api/booking/options").json()
    mine = next(p for p in opts if p["id"] == PID)
    prices = [s["price_czk"] for s in mine["services"] if s["price_czk"] is not None]
    assert mine["price_from"] and mine["price_czk"] == min(prices)
    assert mine["needs_intake"] is True
    svc = next(s for s in mine["services"] if s["kind"] == "follow_up")
    # the times for that service step by its duration + buffer
    o2 = next(p for p in client.get("/api/booking/options", params={"service_id": svc["id"]}).json() if p["id"] == PID)
    t = [s for s in o2["slots"] if s.get("computed")]
    span = (datetime.fromisoformat(t[0]["end_at"]) - datetime.fromisoformat(t[0]["slot_at"])).total_seconds() / 60
    assert span == svc["duration_minutes"] + svc["buffer_minutes"]
    r = client.post("/api/booking/request", json={"physio_id": PID, "starts_at": t[0]["slot_at"], "service_id": svc["id"],
                                                  "kind": "video_call", "reason": "Bolest pod kolenem", "questions": "Smím běhat?"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["kind"] == "follow_up" and b["price_czk"] == svc["price_czk"]       # the client-sent kind is ignored
    db_session.expire_all()
    n = db_session.query(models.Notification).filter_by(event="booking_requested", physio_id=PID).order_by(models.Notification.id.desc()).first()
    loc = datetime.fromisoformat(b["slot_at"]).astimezone(E.LOCAL_TZ)
    assert n.title.endswith(f"{loc.day}. {loc.month}. {loc:%H:%M}") and "Nová žádost o termín:" in n.title
    # the intake prefills the physio's card
    assert client.post(f"/api/runners/{b['runner_id']}/intake", json={"booking_id": b["id"], "data": {
        "consent": True, "first_name": "Iva", "last_name": "Zkušební", "birth_date": "1990-02-03", "sex_at_birth": "f",
        "street": "Ukázková 3", "city": "Brno", "postal_code": "60200", "history": "výron 2024"}}).status_code == 200
    login(client, PHYSIO)
    boot = client.get(f"/api/physios/{PID}/bootstrap").json()
    req = next(x for x in boot["requests"] if x["id"] == b["id"])
    d = req["detail"]
    assert d["service"]["name"] == svc["name"] and d["reason"] == "Bolest pod kolenem" and d["questions"] == "Smím běhat?"
    assert d["first_visit"] is True and d["payer_cs"] == "platí klient" and d["price_czk"] == svc["price_czk"]
    db_session.add(models.CareAssignment(physio_id=PID, runner_id=b["runner_id"], status="active", created_at=E.now_iso()))
    db_session.commit()
    card = client.get(f"/api/physios/me/clients/{b['runner_id']}/card").json()
    assert card["prefill"]["birth_date"] == "1990-02-03" and card["prefill"]["permanent_city"] == "Brno"
    db_session.get(models.Booking, b["id"]).status = "cancelled"
    db_session.commit()
