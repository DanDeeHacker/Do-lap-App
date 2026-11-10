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


# ---------------------------------------------------------------- F10 validation
def test_ico_checksum_and_provider_name():
    assert not R.ico_valid("12345678") and R.ico_valid("12345679")
    assert R.ico_valid("00000001") and not R.ico_valid("00000000")
    assert R.provider_name("TEST Fyzio Holešovice s.r.o.", "s.r.o.") == "TEST Fyzio Holešovice s.r.o."
    assert R.provider_name("Fyzio Holešovice", "s. r. o.") == "Fyzio Holešovice, s. r. o."
    assert R.provider_name("Fyzio Holešovice s r o", "s.r.o.") == "Fyzio Holešovice s r o"


def test_practice_rejects_a_bad_ico_and_profile_a_blank_name(client):
    login(client, PHYSIO)
    r = client.put("/api/physios/me/practice", json={"ico": "12345678"})
    assert r.status_code == 422 and r.json()["detail"] == "Neplatné IČO."
    for bad in ("", " ", "A", "x" * 121):
        assert client.patch("/api/physios/me", json={"name": bad}).status_code == 422
    assert client.get("/api/physios/me").json()["name"].strip()


def test_approval_gate_lists_what_is_missing(client, db_session):
    from datetime import datetime, timedelta, timezone
    from app.metrics import engine as E
    rid = "run-0002"
    if db_session.get(models.Runner, rid) is None:
        return
    db_session.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at=E.now_iso()))
    at = (datetime.now(timezone.utc).replace(hour=3, minute=41, second=0, microsecond=0) - timedelta(days=1)).isoformat()
    b = models.Booking(runner_id=rid, physio_id="phy-0001", slot_at=at, kind="follow_up", status="confirmed", created_at=E.now_iso())
    db_session.add(b)
    db_session.commit()
    login(client, PHYSIO)
    client.put(f"/api/physios/me/clients/{rid}/card", json={"first_name": "Jan", "last_name": "Novák", "sex_at_birth": "m"})
    cid = client.post(f"/api/bookings/{b.id}/conclusion/draft", json={"summary": "S"}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": False})
    assert r.status_code == 409
    body = r.json()
    assert body["missing"] == ["birth_date", "permanent_address"]
    assert body["detail"] == "Doplňte v kartě klienta: datum narození, adresa trvalého pobytu."
