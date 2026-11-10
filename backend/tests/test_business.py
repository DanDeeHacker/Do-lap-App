"""Physio brief 2026-11-09 Phase 3 (B1 payments and receipts, B2 seats and read-only, B4 waitlist, B5 PROMs,
B6 clinic report) and Phase 4 (M1 outcome follow-up and export, M2 recall, M3 video notes, M4 test battery).
B3 (referral fee) is not built: the brief makes it wait for counsel."""
from datetime import datetime, timedelta, timezone

from app import models
from app import moat as M
from app.metrics import engine as E

from .conftest import login, register
from .test_booking import _fresh_consented_runner

PHYSIO, PID, RID = "havlickova@fyzioholesovice.cz", "phy-0001", "run-0001"


def _past_booking(db, rid=RID, hours=3, service=None):
    b = models.Booking(runner_id=rid, physio_id=PID, slot_at=(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
                       duration_min=45, kind="follow_up", status="confirmed", payer="client", price_czk=990,
                       service_id=service, created_at=E.now_iso())
    db.add(b)
    db.commit()
    return b.id


def test_deposit_is_opened_and_only_the_payer_can_pay_it(client, db_session):
    _fresh_consented_runner(client, "zaloha@test.cz")
    opts = client.get("/api/booking/options").json()
    mine = next(p for p in opts if p["id"] == PID)
    t = next(s for s in mine["slots"] if s.get("computed"))
    first = next(s for s in mine["services"] if s["payment_mode"] == "deposit")
    r = client.post("/api/booking/request", json={"physio_id": PID, "starts_at": t["slot_at"], "service_id": first["id"]}).json()
    pay = r["payment"]
    assert pay and pay["amount_czk"] == 300 and pay["kind"] == "deposit" and pay["status"] == "pending"
    _fresh_consented_runner(client, "cizi@test.cz")
    assert client.post(f"/api/payments/{pay['id']}/mock-pay").status_code == 403
    login(client, "zaloha@test.cz", "testpass123")
    assert client.post(f"/api/payments/{pay['id']}/mock-pay").json()["status"] == "paid"
    db_session.get(models.Booking, r["id"]).status = "cancelled"
    db_session.commit()


def test_receipts_are_numbered_per_clinic_and_a_package_pays_the_visit(client, db_session):
    login(client, PHYSIO)
    year = datetime.now(E.LOCAL_TZ).year
    b1, b2 = _past_booking(db_session, hours=5), _past_booking(db_session, hours=3)
    i1 = client.post(f"/api/bookings/{b1}/complete").json()
    n1 = db_session.query(models.Invoice).filter_by(booking_id=b1).one().number
    assert i1["status"] == "completed" and n1.startswith(f"{year}-")
    # a package bought now pays for the next completed visit: a zero receipt that names it
    assert client.post(f"/api/physios/me/clients/{RID}/packages", json={"name": "5 kontrol", "visits_total": 5, "price_czk": 4500, "paid": True}).status_code == 200
    client.post(f"/api/bookings/{b2}/complete")
    inv2 = db_session.query(models.Invoice).filter_by(booking_id=b2).one()
    assert int(inv2.number.split("-")[1]) == int(n1.split("-")[1]) + 1
    assert inv2.amount_czk == 0 and "balíčku" in inv2.items[0]["text"]
    assert client.get(f"/api/physios/me/clients/{RID}/packages").json()["items"][0]["visits_used"] == 1
    # issuing again returns the same receipt, cancelling keeps the number
    assert client.post(f"/api/bookings/{b2}/invoice").json()["number"] == inv2.number
    inv1 = db_session.query(models.Invoice).filter_by(booking_id=b1).one()
    assert client.patch(f"/api/invoices/{inv1.id}", json={"status": "paid"}).json()["paid_czk"] == inv1.amount_czk
    csv = client.get("/api/physios/me/invoices.csv")
    assert csv.status_code == 200 and "cislo;vystaveno" in csv.text and n1 in csv.text
    rev = client.get("/api/physios/me/revenue").json()
    assert rev["invoiced_czk"] >= 990 + 4500 and rev["vat"] is None and "client" in rev["by_payer"]


def test_unpaid_practice_is_read_only_except_documentation(client, db_session):
    login(client, PHYSIO)
    p = db_session.get(models.Physio, PID)
    sub = db_session.query(models.Subscription).filter_by(clinic_id=p.clinic_id).one()
    keep = (sub.trial_ends_at, sub.paid_until, sub.status)
    sub.trial_ends_at, sub.paid_until = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(), None
    db_session.commit()
    try:
        r = client.post(f"/api/physios/me/clients/{RID}/limits", json={"kind": "no_running", "reason_cs": "test"})
        assert r.status_code == 402 and "jen pro čtení" in r.json()["detail"]
        assert client.get(f"/api/physios/me/clients/{RID}/documentation").status_code == 200
        assert client.get("/api/physios/me/subscription").json()["read_only"] is True
        pay = client.post("/api/physios/me/subscription/pay").json()          # paying is always possible
        assert client.post(f"/api/payments/{pay['id']}/mock-pay").json()["status"] == "paid"
        st = client.get("/api/physios/me/subscription").json()
        assert st["status"] == "active" and st["read_only"] is False
    finally:
        db_session.expire_all()
        sub = db_session.query(models.Subscription).filter_by(clinic_id=p.clinic_id).one()
        sub.trial_ends_at, sub.paid_until, sub.status = keep
        db_session.commit()


def test_waitlist_offers_one_person_at_a_time(client, db_session):
    rid_a = _fresh_consented_runner(client, "cekam1@test.cz")
    w1 = client.post(f"/api/physios/{PID}/waitlist", json={"dow": "", "dayparts": ""}).json()
    _fresh_consented_runner(client, "cekam2@test.cz")
    w2 = client.post(f"/api/physios/{PID}/waitlist", json={}).json()
    login(client, PHYSIO)
    items = client.get("/api/physios/me/waitlist").json()["items"]
    mine = next(i for i in items if i["id"] == w1["id"])
    assert mine["fits"], "free times from Tereza's working hours fit an open preference"
    at = mine["fits"][0]
    assert client.post(f"/api/waitlist/{w1['id']}/offer", json={"starts_at": at}).status_code == 200
    assert client.post(f"/api/waitlist/{w2['id']}/offer", json={"starts_at": at}).status_code == 409
    login(client, "cekam1@test.cz", "testpass123")
    r = client.post(f"/api/waitlist/{w1['id']}/accept").json()
    b = db_session.get(models.Booking, r["booking_id"])
    assert b.runner_id == rid_a and b.status == "requested"
    # an offer older than 2 hours goes back to waiting
    w = db_session.get(models.Waitlist, w2["id"])
    w.status, w.offered_at, w.offered_slot_at = "offered", (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(), at
    db_session.commit()
    login(client, "cekam2@test.cz", "testpass123")
    assert client.post(f"/api/waitlist/{w2['id']}/accept").status_code == 410
    b.status = "cancelled"
    db_session.commit()


def test_prom_schedule_answer_and_no_unlicensed_instrument(client, db_session):
    cat = client.get("/api/proms/instruments").json()
    assert all(not i["validated"] for i in cat["items"]) and "VISA-A" in cat["note"]
    login(client, PHYSIO)
    assert client.post(f"/api/physios/me/clients/{RID}/proms", json={"instrument": "visa_a"}).status_code == 422
    s = client.post(f"/api/physios/me/clients/{RID}/proms", json={"instrument": "dosslap_function", "every_days": 14}).json()
    login(client, "adela@demo.cz")
    due = client.get(f"/api/runners/{RID}/proms/due").json()["items"]
    assert any(d["schedule_id"] == s["id"] for d in due)
    assert client.post(f"/api/proms/{s['id']}/answer", json={"answers": {"pain_run": 11}}).status_code == 422
    r = client.post(f"/api/proms/{s['id']}/answer", json={"answers": {"pain_run": 2, "pain_day": 1, "function": 7}}).json()
    assert r["score"] == round((8 + 9 + 7) / 30 * 100)
    assert not any(d["schedule_id"] == s["id"] for d in client.get(f"/api/runners/{RID}/proms/due").json()["items"])
    db_session.get(models.PromSchedule, s["id"]).active = False
    db_session.commit()


def test_clinic_report_is_aggregates_only(client):
    login(client, PHYSIO)
    rep = client.get("/api/physios/me/clinic/report").json()
    for k in ("visits", "no_shows", "no_show_rate", "occupancy_pct", "new_clients", "returning_clients", "revenue"):
        assert k in rep
    text = str(rep)
    assert "run-0001" not in text and "Adéla" not in text


def test_outcome_followup_and_guarded_export(client, db_session, monkeypatch):
    ep = models.CareEpisode(physio_id=PID, runner_id=RID, status="discharged", diagnosis_code="M76.6",
                            diagnosis_label="Achillova tendinopatie", side="R", discharge_outcome="returned_full",
                            closed_at=(E.today_date() - timedelta(days=95)).isoformat(), opened_at=E.day_ago(150))
    db_session.add(ep)
    db_session.flush()
    fu = models.OutcomeFollowup(episode_id=ep.id, runner_id=RID, due_on=E.day_ago(2), status="scheduled", created_at=E.now_iso())
    db_session.add(fu)
    db_session.commit()
    login(client, "adela@demo.cz")
    assert any(f["id"] == fu.id for f in client.get(f"/api/runners/{RID}/outcome-followups").json()["items"])
    assert client.post(f"/api/outcome-followups/{fu.id}", json={"running_normally": True, "recurrence": False, "pain": 1}).status_code == 200
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "adela@demo.cz")
    monkeypatch.delenv("DOSSLAP_OUTCOME_EXPORT_BASIS", raising=False)
    assert client.get("/api/team/outcomes/export").status_code == 409
    monkeypatch.setenv("DOSSLAP_OUTCOME_EXPORT_BASIS", "test")
    monkeypatch.setenv("DOSSLAP_PSEUDO_KEY", "x" * 40)
    rows = client.get("/api/team/outcomes/export").json()["rows"]
    row = next(r for r in rows if r["episode"] == ep.id)
    assert row["followup_running_normally"] is True and row["outcome_kind"] == "returned_full"
    assert RID not in str(rows) and row["subject"] == M.pseudo(RID)
    db_session.delete(ep)
    db_session.commit()


def test_recall_needs_consent_and_a_new_signal(client, db_session):
    """Adéla discharged 30 days ago, with pain check-ins ≥ 3/10 since: recalled while she still shares data,
    not after she withdraws, and not while she is back in care (an open episode)."""
    opened = db_session.query(models.CareEpisode).filter_by(physio_id=PID, runner_id=RID, status="open").all()
    for e in opened:
        e.status = "paused-for-test"
    ep = models.CareEpisode(physio_id=PID, runner_id=RID, status="discharged", closed_at=E.day_ago(30), opened_at=E.day_ago(90))
    db_session.add(ep)
    ci = models.Checkin(runner_id=RID, submitted_at=E.now_iso(), pain_score=4, pain_site="Achillova šlacha")
    db_session.add(ci)
    db_session.commit()
    ca = db_session.query(models.CareAssignment).filter_by(physio_id=PID, runner_id=RID, status="active").first()
    try:
        assert any(x["runner_id"] == RID for x in M.recall_list(db_session, PID))
        ca.status = "revoked"
        db_session.commit()
        assert all(x["runner_id"] != RID for x in M.recall_list(db_session, PID))
        ca.status = "active"
        back = models.CareEpisode(physio_id=PID, runner_id=RID, status="open", opened_at=E.now_iso())
        db_session.add(back)
        db_session.commit()
        assert all(x["runner_id"] != RID for x in M.recall_list(db_session, PID))
        db_session.delete(back)
    finally:
        ca.status = "active"
        for e in opened:
            e.status = "open"
        db_session.delete(ep)
        db_session.delete(ci)
        db_session.commit()


def test_video_notes_only_on_video_and_only_for_care(client, db_session):
    m = models.Message(runner_id=RID, physio_id=PID, sender="runner", body="", attachment_path=f"{RID}/x.mp4",
                       attachment_type="video/mp4", attachment_name="beh.mp4", created_at=E.now_iso())
    t = models.Message(runner_id=RID, physio_id=PID, sender="runner", body="text", created_at=E.now_iso())
    db_session.add_all([m, t])
    db_session.commit()
    login(client, PHYSIO)
    assert client.post(f"/api/messages/{t.id}/annotations", json={"t_seconds": 1, "text": "x"}).status_code == 422
    assert client.post(f"/api/messages/{m.id}/annotations", json={"t_seconds": 3.4, "text": "Pánev padá vlevo"}).status_code == 200
    login(client, "adela@demo.cz")
    assert client.get(f"/api/messages/{m.id}/annotations").json()["items"][0]["text"] == "Pánev padá vlevo"
    register(client, "jiny-fyzio@test.cz", "Jiný Fyzio", "physio", "testpass123")
    u = db_session.query(models.User).filter_by(email="jiny-fyzio@test.cz").one()
    db_session.get(models.Physio, u.physio_id).verified_at = E.now_iso()
    db_session.commit()
    login(client, "jiny-fyzio@test.cz", "testpass123")
    assert client.post(f"/api/messages/{m.id}/annotations", json={"t_seconds": 1, "text": "x"}).status_code == 403


def test_test_battery_limb_symmetry(client):
    assert M.lsi(18, 25, "L") == 72 and M.lsi(25, 18, None) == 72 and M.lsi(None, 20, "R") is None
    login(client, PHYSIO)
    assert client.post(f"/api/physios/me/clients/{RID}/tests", json={"test": "neznamy", "left": 1}).status_code == 422
    r = client.post(f"/api/physios/me/clients/{RID}/tests", json={"test": "heel_raise_sl", "left": 25, "right": 18, "involved": "R"}).json()
    assert r["lsi"] == 72
    latest = client.get(f"/api/physios/me/clients/{RID}/tests").json()["latest"]
    assert latest["heel_raise_sl"]["lsi"] == 72
