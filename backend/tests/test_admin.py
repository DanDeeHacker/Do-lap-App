"""Admin view for the app's owners: the registered runners, a read-only view of any of
them, and every view in the runner's own access log."""
from .conftest import login, register
from .synth import seed_runs


def _runner(client, db, email, name="Běžec"):
    rid = register(client, email, name, "runner").json()["runner_id"]
    seed_runs(db, rid, days=40)
    return rid


def test_admin_list_is_owner_only(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "spravce@test.cz")
    other = _runner(client, db_session, "bezec-a@test.cz", "Anna")
    assert client.get("/api/admin/runners").status_code == 403            # signed in as Anna
    assert client.get("/api/auth/me").json()["owner"] is False
    _runner(client, db_session, "spravce@test.cz", "Správce")
    assert client.get("/api/auth/me").json()["owner"] is True
    items = client.get("/api/admin/runners").json()["items"]
    by_rid = {x["runnerId"]: x for x in items}
    assert other in by_rid and by_rid[other]["name"] == "Anna" and by_rid[other]["activities"] > 0
    assert any(x["self"] for x in items)
    from app.tutorial_demo import TUTORIAL_RID
    assert TUTORIAL_RID not in by_rid                                        # not the tour's demo runner


def test_owner_reads_any_runner_but_never_writes(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "spravce2@test.cz")
    other = _runner(client, db_session, "bezec-b@test.cz", "Bára")
    _runner(client, db_session, "spravce2@test.cz", "Správce")
    for path in ("bootstrap", "quadrant-history", "load-history", "activities", "self-programs", "messages"):
        assert client.get(f"/api/runners/{other}/{path}").status_code == 200, path
    # every write stays with the runner
    assert client.post(f"/api/runners/{other}/checkins", json={"pain_score": 1}).status_code == 403
    assert client.post(f"/api/runners/{other}/messages", json={"sender": "runner", "body": "ahoj"}).status_code == 403
    assert client.patch(f"/api/runners/{other}", json={"patch": {"city": "Brno"}}).status_code == 403
    assert client.get(f"/api/runners/{other}/assistant").status_code == 403   # the chat is the runner's own
    # the runner sees the view in "Kdo přistupoval k vašim datům"
    login(client, "bezec-b@test.cz", "testpass123")
    log = client.get(f"/api/runners/{other}/bootstrap").json()["access_log"]
    admin = [x for x in log if x.get("actor_role") == "admin"]
    assert admin and admin[0]["physio_name"] == "Správce aplikace" and admin[0]["access_count"] >= 6
    assert all(x["action"] == "read" for x in admin)


def test_a_runner_still_cannot_read_others(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "")
    other = _runner(client, db_session, "bezec-c@test.cz")
    _runner(client, db_session, "bezec-d@test.cz")
    assert client.get(f"/api/runners/{other}/bootstrap").status_code == 403


def test_engagement_is_counted_and_shown_to_owners_only(client, db_session, monkeypatch):
    """Owner request 2026-10-13: per runner the app opens, active days, minutes in use and the
    minutes per tab; the batches add up per day and tab, odd keys and far days are dropped."""
    from app.metrics import engine as E
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "spravce-eng@test.cz")
    rid = _runner(client, db_session, "bezec-eng@test.cz", "Eva")
    today = E.today_date().isoformat()
    for _ in range(2):
        assert client.post("/api/usage", json={"day": today, "opens": 1, "tabs": {
            "training": {"s": 120, "v": 2}, "today": {"s": 60, "v": 1}, "f:goal": {"s": 0, "v": 1},
            "<script>": {"s": 5, "v": 1}}}).json()["ok"]
    assert client.post("/api/usage", json={"day": "2020-01-01", "opens": 1, "tabs": {}}).json()["ok"] is False
    assert client.post("/api/usage", json={"day": today, "tabs": {"today": {"s": 99999}}}).status_code == 422
    assert client.get("/api/admin/engagement").status_code == 403          # Eva is not an owner
    _runner(client, db_session, "spravce-eng@test.cz", "Správce")
    d = client.get("/api/admin/engagement?days=7").json()
    x = next(i for i in d["items"] if i["runnerId"] == rid)
    assert x["opens"] == 2 and x["activeDays"] == 1 and x["minutes"] == 6.0
    assert x["tabs"] == {"training": 4.0, "today": 2.0} and x["features"] == {"goal": 2}
    assert x["avgVisitMin"] == 3.0 and x["lastActive"] == today
    assert d["tabs"]["training"] >= 4.0 and d["activeUsers"] >= 1


def test_engagement_last_24_hours_by_the_recorded_hour(client, db_session, monkeypatch):
    """railway#218: the overview's 24 h filter counts the batches by the local hour the app
    recorded them in — this hour and yesterday's later hours, not yesterday morning."""
    from datetime import datetime, timedelta
    from app.metrics import engine as E
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "spravce-24@test.cz")
    rid = _runner(client, db_session, "bezec-24@test.cz", "Jana")
    now = datetime.now(E.LOCAL_TZ)
    recent = now - timedelta(hours=3)
    old = now - timedelta(hours=30)
    for t, opens in ((now, 1), (recent, 1), (old, 5)):
        assert client.post("/api/usage", json={"day": t.date().isoformat(), "hour": t.hour, "opens": opens,
                                               "tabs": {"today": {"s": 60, "v": 1}}}).json()["ok"]
    # the same hour twice adds up in one row
    assert client.post("/api/usage", json={"day": now.date().isoformat(), "hour": now.hour,
                                           "tabs": {"today": {"s": 60, "v": 1}}}).json()["ok"]
    assert client.post("/api/usage", json={"day": now.date().isoformat(), "hour": 24, "tabs": {}}).status_code == 422
    _runner(client, db_session, "spravce-24@test.cz", "Správce")
    d = client.get("/api/admin/engagement?hours=24").json()
    x = next(i for i in d["items"] if i["runnerId"] == rid)
    assert d["hours"] == 24
    assert x["opens"] == 2 and x["minutes"] == 3.0 and x["opensPrev"] == 5
    week = next(i for i in client.get("/api/admin/engagement?days=7").json()["items"] if i["runnerId"] == rid)
    assert week["opens"] == 7 and week["minutes"] == 4.0
