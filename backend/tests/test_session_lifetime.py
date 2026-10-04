"""Owner request 2026-10-04: a runner is signed out only by "Odhlásit se" — a persistent,
sliding session (closing the browser or a long break keeps it); the guest demo keeps
its short session."""
from datetime import datetime, timedelta, timezone

from app import models
from app.security import SESSION_COOKIE, SESSION_TTL_DAYS
from .conftest import register


def _session(db, client):
    tok = client.cookies.get(SESSION_COOKIE)
    db.expire_all()
    return db.query(models.UserSession).filter(models.UserSession.id == tok).first()


def test_sign_in_is_persistent_and_slides(client, db_session):
    r = register(client, "sess1@test.cz", "Sess", "runner")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "max-age=" in cookie and "httponly" in cookie          # survives closing the browser
    sess = _session(db_session, client)
    sess.expires_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()   # nearly worn out
    db_session.commit()
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and "max-age=" in me.headers["set-cookie"].lower()  # cookie renewed
    end = datetime.fromisoformat(_session(db_session, client).expires_at)
    assert end > datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS - 2)  # session pushed out again


def test_only_logout_ends_the_session(client, db_session):
    register(client, "sess2@test.cz", "Sess", "runner")
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_guest_keeps_a_short_session(client, db_session):
    r = client.post("/api/auth/guest")
    assert r.status_code == 200 and "max-age=" not in r.headers["set-cookie"].lower()
    before = _session(db_session, client).expires_at
    client.get("/api/auth/me")
    assert _session(db_session, client).expires_at == before                    # no sliding for the demo
    assert datetime.fromisoformat(before) < datetime.now(timezone.utc) + timedelta(hours=13)
