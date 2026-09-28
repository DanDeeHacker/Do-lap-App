"""Public demo ("Vyzkoušej hned!"): a read-only guest session on the tutorial runner."""
from app.tutorial_demo import TUTORIAL_RID


def _guest(client):
    r = client.post("/api/auth/guest")
    assert r.status_code == 200, r.text
    return r.json()


def test_guest_session_sees_tutorial_runner(client):
    me = _guest(client)
    assert me["guest"] is True and me["demo_rid"] == TUTORIAL_RID and me["runner_id"] is None
    assert client.get("/api/auth/me").json()["guest"] is True
    boot = client.get(f"/api/runners/{TUTORIAL_RID}/bootstrap")
    assert boot.status_code == 200 and boot.json()["assessment"]


def test_guest_cannot_write(client):
    _guest(client)
    r = client.post(f"/api/runners/{TUTORIAL_RID}/checkins", json={"pain_score": 2})
    assert r.status_code == 403 and "ukázce" in r.json()["detail"]
    r = client.put("/api/auth/settings", json={"rail": []})
    assert r.status_code in (403, 404, 405)


def test_guest_reuses_one_account_and_can_leave(client, db_session):
    from app import models
    a = _guest(client)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    b = _guest(client)
    assert a["id"] == b["id"]
    assert db_session.query(models.User).filter(models.User.provider == "guest").count() == 1


def test_guest_account_has_no_password_login(client):
    _guest(client)
    client.post("/api/auth/logout")
    r = client.post("/api/auth/session", json={"email": "ukazka@guest.doslap.invalid", "password": ""})
    assert r.status_code in (401, 422)
