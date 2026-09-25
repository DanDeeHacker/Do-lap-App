"""Points the app at an isolated temp SQLite file *before* app.main (and
therefore app.db) is imported anywhere, so tests never touch the real
backend/dosslap.db. The first TestClient a test uses triggers the app's
normal startup lifespan, which creates tables and seeds the standard demo
dataset (same as a real `uvicorn app.main:app` run) — tests then assert
against that known, deterministic seed rather than hand-building fixtures.
"""
import os
import sys
import tempfile

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ["DOSSLAP_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="dosslap_test_"), "test.db")
os.environ["DOSSLAP_WEATHER"] = "off"   # no network in tests; weather tests enable it with a fake fetch

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

DEMO_PASSWORD = "demo1234"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD, expected_role: str | None = None):
    body = {"email": email, "password": password}
    if expected_role:
        body["expected_role"] = expected_role
    return client.post("/api/auth/session", json=body)


def register(client: TestClient, email: str, name: str, role: str, password: str = "testpass123"):
    return client.post("/api/auth/register", json={
        "email": email, "password": password, "name": name, "role": role,
    })
