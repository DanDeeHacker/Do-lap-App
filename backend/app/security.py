"""Password hashing, session cookies and a small in-memory login throttle.

Sessions (not JWT): a single FastAPI process + SQLite means statelessness
buys nothing, while a `sessions` row gives instant revocation on logout and
keeps the credential out of JS-reachable storage (httpOnly cookie).
"""
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session as DBSession

from . import models

SESSION_COOKIE = "dosslap_session"
SESSION_TTL_DAYS = 30
# Local/testing runs are plain HTTP, where a Secure cookie would never be
# stored by the browser. Set DOSSLAP_HTTPS=1 once this is actually served
# over HTTPS to turn Secure back on.
COOKIE_SECURE = os.environ.get("DOSSLAP_HTTPS") == "1"

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(raw, hashed)
    except Exception:
        return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(db: DBSession, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    db.add(models.UserSession(id=token, user_id=user_id, expires_at=expires_at, created_at=now_iso()))
    db.commit()
    return token, expires_at


def get_user_for_token(db: DBSession, token: Optional[str]) -> Optional[models.User]:
    if not token:
        return None
    sess = db.query(models.UserSession).filter(models.UserSession.id == token).first()
    if not sess:
        return None
    if sess.expires_at < now_iso():
        db.delete(sess)
        db.commit()
        return None
    return db.query(models.User).filter(models.User.id == sess.user_id).first()


def revoke_session(db: DBSession, token: Optional[str]) -> None:
    if not token:
        return
    db.query(models.UserSession).filter(models.UserSession.id == token).delete()
    db.commit()


# ---------------------------------------------------------------- CSRF
def same_origin(request: Request) -> bool:
    """Reject only when an Origin header is present and disagrees with the
    request's own host. Absent Origin (curl, test clients, older browser
    navigations) is allowed through — SameSite=Lax on the session cookie is
    the primary defense; this catches cross-site fetch/XHR specifically."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    return origin.endswith(host) or f"//{host}" in origin


# ---------------------------------------------------------------- throttle
class LoginThrottle:
    """Sliding-window limiter keyed by email+ip. In-memory: resets on
    restart, which is fine for a local/testing deployment."""

    def __init__(self, max_attempts: int = 8, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def _key(self, email: str, ip: str) -> str:
        return f"{email.strip().lower()}|{ip}"

    def check(self, email: str, ip: str) -> bool:
        key = self._key(email, ip)
        cutoff = time.time() - self.window_seconds
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        self._hits[key] = hits
        return len(hits) < self.max_attempts

    def record_failure(self, email: str, ip: str) -> None:
        key = self._key(email, ip)
        self._hits.setdefault(key, []).append(time.time())

    def reset(self, email: str, ip: str) -> None:
        self._hits.pop(self._key(email, ip), None)


login_throttle = LoginThrottle()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
