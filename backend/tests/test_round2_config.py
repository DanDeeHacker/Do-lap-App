"""Physio brief round 2 F9: no configuration names reach the UI; the field key can be rotated; MKN-10 comes from
the bundled ÚZIS release and is searched by code prefix and by text without diacritics."""
import base64
import os

from app import models
from app import records as R
from app.scripts import import_mkn10 as M

from .conftest import login

PHYSIO = "havlickova@fyzioholesovice.cz"


def test_frontend_shows_no_environment_variable_names_to_physios():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "physio")
    for name in os.listdir(root):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "FIELD_ENCRYPTION_KEY" not in text and "DOSSLAP_" not in text, name


def test_rotation_reads_with_the_previous_key(monkeypatch):
    old = base64.urlsafe_b64encode(os.urandom(32)).decode()
    new = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", old)
    blob = R.encrypt("9105141234")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", new)
    assert R.decrypt(blob) is None
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_PREVIOUS", old)
    assert R.decrypt(blob) == "9105141234"
    assert R.decrypt(R.encrypt("9105141234")) == "9105141234"


def test_mkn10_bundled_release_and_search(client, db_session):
    rows = M._read(M.BUNDLED)
    assert len(rows) > 38000
    if db_session.query(models.DiagnosisCode).count() < 1000:
        M.import_rows(db_session, rows)
    assert db_session.get(models.DiagnosisCode, "M76.6").label == "Tendinitida Achillovy šlachy"
    login(client, PHYSIO)
    by_code = client.get("/api/diagnoses", params={"q": "M76"}).json()
    assert by_code["imported"] and all(x["code"].startswith("M76") for x in by_code["items"])
    assert client.get("/api/diagnoses", params={"q": "m766"}).json()["items"][0]["code"] == "M76.6"
    plain = client.get("/api/diagnoses", params={"q": "achillovy slachy"}).json()["items"]
    assert any(x["code"] == "M76.6" for x in plain)                     # no diacritics typed
    assert M.import_rows(db_session, rows[:10]) == 10                    # re-running updates, never duplicates
