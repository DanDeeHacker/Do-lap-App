"""Physio brief 2026-11-09 Phase 2: roles (W1), invites (W2), Dnes alerts (W3), capacity (W4), availability with
DST (W5), clinical limits (W12), notifications and reminders (W15)."""
from datetime import date, datetime, timedelta, timezone

from app import models
from app import work as W
from app.metrics import engine as E

from .conftest import login, register

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


def _verified(db, email):
    u = db.query(models.User).filter_by(email=email).first()
    db.get(models.Physio, u.physio_id).verified_at = E.now_iso()
    db.commit()
    return u.physio_id


def test_roles_reception_reads_no_clinical_data(client, db_session):
    register(client, "recepce@test.cz", "Recepce Holešovice", "physio", "testpass123")
    pid = _verified(db_session, "recepce@test.cz")
    login(client, PHYSIO)
    assert client.post("/api/physios/me/clinic/members", json={"email": "recepce@test.cz", "role": "reception"}).status_code == 200
    db_session.add(models.CareAssignment(physio_id=pid, runner_id=RID, status="active", created_at=E.now_iso()))
    db_session.commit()
    login(client, "recepce@test.cz", "testpass123")
    for url in (f"/api/physios/me/clients/{RID}", f"/api/physios/me/clients/{RID}/documentation",
                f"/api/runners/{RID}/program", f"/api/physios/me/clients/{RID}/timeline"):
        assert client.get(url).status_code == 403, url
    cal = client.get("/api/physios/phy-0001/calendar").json()       # the clinic calendar, without clinical status
    assert "bookings" in cal and all("record" not in b for b in cal["bookings"])
    login(client, PHYSIO)
    clinic = client.get("/api/physios/me/clinic").json()
    assert clinic["role"] == "owner" and clinic["subscription"]["price_czk_per_seat"] == 690
    assert clinic["subscription"]["trial_ends_at"] > (date.today() + timedelta(days=300)).isoformat()


def test_invite_register_and_appear_in_clients(client, db_session):
    login(client, PHYSIO)
    inv = client.post("/api/physios/me/invites", json={"name": "Nový Klient", "email": "pozvany@test.cz"}).json()
    token = inv["token"]
    assert client.get(f"/api/invites/{token}").json()["physio"].endswith("Havlíčková")
    rid = register(client, "pozvany@test.cz", "Nový Klient", "runner").json()["runner_id"]
    assert client.post(f"/api/invites/{token}/accept").status_code == 200
    assert client.post(f"/api/invites/{token}/accept").status_code == 410             # single use
    login(client, PHYSIO)
    assert rid in {c["runnerId"] for c in client.get("/api/physios/me/clients").json()["items"]}
    assert not db_session.query(models.Triage).filter_by(runner_id=rid, claimed_by="phy-0001").first()   # no queue
    old = models.ClientInvite(token_hash=W_hash("stary"), physio_id="phy-0001", status="open", created_at=E.now_iso(),
                              expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    db_session.add(old)
    db_session.commit()
    assert client.get("/api/invites/stary").status_code == 410


def W_hash(t):
    from app.routers.work import _hash
    return _hash(t)


def test_alert_rules(client, db_session):
    rid = register(client, "alerty@test.cz", "Alert Běžec", "runner").json()["runner_id"]
    db_session.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at=E.now_iso()))
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=6, pain_site="Koleno"))
    plan = models.ReturnToRun(runner_id=rid, physio_id="phy-0001", status="paused", paused_reason="pain_over_limit",
                              current_level=1, pain_threshold=3, sessions_per_level=3, levels_json=[{"level": 1, "label": "x"}],
                              created_at=E.now_iso())
    db_session.add(plan)
    db_session.add(models.ClinicalLimit(runner_id=rid, physio_id="phy-0001", kind="no_running", reason_cs="Zánět",
                                        starts_on=E.iso_date(E.today_date() - timedelta(days=3)), active=True))
    db_session.add(models.Activity(runner_id=rid, started_at=E.now_iso(), sport="running", distance_km=5, duration_min=30))
    db_session.commit()
    login(client, PHYSIO)
    t = client.get("/api/physios/me/today").json()
    rules = {a["rule"] for a in t["alerts"] if a["runner_id"] == rid}
    assert {"checkin_pain_high", "rtr_paused_pain", "limit_exceeded"} <= rules
    assert {"visits", "alerts", "unread", "unsigned", "requests", "new_cases"} <= set(t)
    # one active alert per rule and client, also after a second load
    client.get("/api/physios/me/today")
    n = db_session.query(models.PhysioAlert).filter_by(runner_id=rid, rule="checkin_pain_high", status="active").count()
    assert n == 1
    aid = next(a["id"] for a in t["alerts"] if a["runner_id"] == rid and a["rule"] == "checkin_pain_high")
    assert client.patch(f"/api/alerts/{aid}", json={"action": "resolve"}).status_code == 200


def test_free_times_respect_dst_bookings_and_time_off(client, db_session):
    login(client, PHYSIO)
    register(client, "kalendar@test.cz", "Kalendář Fyzio", "physio", "testpass123")
    pid = _verified(db_session, "kalendar@test.cz")
    login(client, "kalendar@test.cz", "testpass123")
    # Sunday 29 March 2026 is the switch to summer time; the Monday after keeps 08:00 local
    r = client.put("/api/physios/me/availability", json={"rules": [{"weekday": 0, "start_local": "08:00", "end_local": "10:00",
                                                                     "slot_minutes": 60}]})
    assert r.status_code == 200
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Prague")
    W_now = datetime(2026, 3, 20, tzinfo=timezone.utc)
    import app.work as Wm
    real = Wm.datetime

    class Fixed(datetime):
        @classmethod
        def now(cls, tz_=None):
            return W_now if tz_ else W_now.replace(tzinfo=None)
    Wm.datetime = Fixed
    try:
        ft = W.free_times(db_session, pid, date(2026, 3, 23), date(2026, 3, 30))
    finally:
        Wm.datetime = real
    starts = [datetime.fromisoformat(x["start"]).astimezone(tz) for x in ft]
    assert {(s.date().isoformat(), s.hour) for s in starts} == {("2026-03-23", 8), ("2026-03-23", 9), ("2026-03-30", 8), ("2026-03-30", 9)}
    assert {datetime.fromisoformat(x["start"]).utcoffset() for x in ft} == {timedelta(hours=1), timedelta(hours=2)}
    # a booking and time off remove their times
    mon = E.today_date() + timedelta(days=(7 - E.today_date().weekday()))
    at = datetime.combine(mon, datetime.min.time().replace(hour=8), tz)
    db_session.add(models.Booking(runner_id=RID, physio_id=pid, slot_at=at.astimezone(timezone.utc).isoformat(), duration_min=60,
                                  status="confirmed", kind="follow_up", created_at=E.now_iso()))
    db_session.add(models.TimeOff(physio_id=pid, starts_at=(at + timedelta(hours=1)).isoformat(),
                                  ends_at=(at + timedelta(hours=2)).isoformat()))
    db_session.commit()
    assert not [x for x in W.free_times(db_session, pid, mon, mon)]


def test_clinical_limit_changes_training_not_the_engine(client, db_session):
    from .test_prevention import _assess, _runner
    rid, _ = _runner(client, db_session, "limit@test.cz")
    db_session.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at=E.now_iso()))
    db_session.commit()
    raw = _assess(db_session, rid)
    login(client, PHYSIO)
    r = client.post(f"/api/physios/me/clients/{rid}/limits", json={"kind": "max_km_session", "value": 3, "reason_cs": "Achilovka"})
    assert r.status_code == 200
    assert client.post(f"/api/physios/me/clients/{rid}/limits", json={"kind": "max_km_week", "reason_cs": ""}).status_code == 422
    login(client, "limit@test.cz", "testpass123")
    a = client.get(f"/api/runners/{rid}/assessment").json()
    g = a["guidance"]
    assert any("Podle" in x and "Achilovka" in x for x in g["limits"])
    assert all((t.get("km") or {}).get("hi", 0) <= 3 for k, t in g["types"].items() if k in ("lehký", "dlouhý") and t.get("km"))
    assert E.get_or_refresh_assessment(db_session, rid)["overall"] == raw["overall"]          # the engine result unchanged
    login(client, PHYSIO)
    client.post(f"/api/physios/me/clients/{rid}/limits", json={"kind": "no_running", "reason_cs": "Zánět šlachy"})
    login(client, "limit@test.cz", "testpass123")
    d = client.get(f"/api/runners/{rid}/assessment").json()["careDirective"]
    assert d["source"] == "clinical_limit" and d["headline_cs"] == "Dnes bez běhu podle pokynu fyzioterapeuta"


def test_reminder_goes_out_once(client, db_session):
    at = (datetime.now(timezone.utc) + timedelta(hours=20)).replace(second=0, microsecond=0)
    b = models.Booking(runner_id=RID, physio_id="phy-0001", slot_at=at.isoformat(), duration_min=45, status="confirmed",
                       kind="follow_up", created_at=E.now_iso())
    db_session.add(b)
    db_session.commit()
    from app.routers.booking import send_due_reminders
    assert send_due_reminders(db_session) >= 1
    db_session.commit()
    assert send_due_reminders(db_session) == 0
    assert db_session.get(models.Booking, b.id).reminded
    assert db_session.query(models.Notification).filter_by(event="reminder_24h", ref=f"booking:{b.id}").count() == 2


def test_runner_books_a_computed_free_time_with_service_and_reason(client, db_session):
    """W5.4/W16: a computed free time (from Tereza's working hours) is bookable with a service, the reason and
    the questions; the same time a second time is refused."""
    from .test_booking import _fresh_consented_runner
    _fresh_consented_runner(client, "volnycas@test.cz")
    opts = client.get("/api/booking/options").json()
    mine = next(p for p in opts if p["id"] == "phy-0001")
    t = next(s for s in mine["slots"] if s.get("computed"))
    sv = mine["services"][0]
    body = {"physio_id": "phy-0001", "starts_at": t["slot_at"], "service_id": sv["id"], "kind": "assessment",
            "reason": "Bolest pod kolenem po delších bězích", "questions": "Mám zkrátit dlouhý běh?"}
    r = client.post("/api/booking/request", json=body)
    assert r.status_code == 200, r.text
    b = db_session.get(models.Booking, r.json()["id"])
    db_session.refresh(b)
    assert b.reason.startswith("Bolest pod kolenem") and b.questions and b.service_id == sv["id"]
    assert b.duration_min == sv["duration_minutes"] and b.payer == "client"
    # an equivalent instant written in UTC is the same time, and it is taken now
    utc = datetime.fromisoformat(t["slot_at"]).astimezone(timezone.utc).isoformat()
    _fresh_consented_runner(client, "volnycas2@test.cz")
    assert client.post("/api/booking/request", json={**body, "starts_at": utc}).status_code == 409
    b.status = "cancelled"
    db_session.commit()
