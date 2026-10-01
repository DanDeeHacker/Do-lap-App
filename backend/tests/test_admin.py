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
