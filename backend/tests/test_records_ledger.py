"""Physio brief 2026-11-09 R1/R2/R5/R10: approval needs provider and patient identity, writes one ledger row in
the same transaction, the database refuses UPDATE and DELETE, and the verifier spots a tampered copy."""
import base64
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app import models
from app import records as R
from app.metrics import engine as E

from .conftest import login

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


_n = [0]


def _visit(db, hours=-2):
    _n[0] += 1                           # one active visit per start (P0.6 unique index)
    b = models.Booking(runner_id=RID, physio_id="phy-0001", kind="follow_up", status="confirmed", created_at=E.now_iso(),
                       slot_at=(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                                + timedelta(hours=hours, days=-1, minutes=-7 * _n[0])).isoformat())
    db.add(b)
    db.commit()
    return b.id


def approve_one(client, db, summary="Shrnutí pro klienta."):
    bid = _visit(db)
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft",
                      json={"summary": summary, "subjective": "Bolí pata ráno.", "objective": "Citlivý úpon.",
                            "assessment": "Přetížení Achillovy šlachy", "plan": "Excentrika 3× týdně"}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_approval_writes_one_ledger_row_with_identity(client, db_session):
    c = approve_one(client, db_session)
    rec = db_session.get(models.ClinicalRecord, c["record_id"])
    body = R.content_of(rec)
    assert body["provider"]["ico"] and body["author"]["id"] == "phy-0001"
    assert body["patient"]["last_name"] == "Kučerová" and body["content"]["objective"] == "Citlivý úpon."
    assert rec.content_sha256 == R.sha256(rec.content_json) and rec.episode_id
    assert R.verify(db_session)["ok"]


def test_the_database_refuses_update_and_delete(client, db_session):
    c = approve_one(client, db_session)
    for sql in ("UPDATE clinical_records SET kind = 'x' WHERE id = :i", "DELETE FROM clinical_records WHERE id = :i"):
        with pytest.raises(DatabaseError):
            db_session.execute(text(sql), {"i": c["record_id"]})
        db_session.rollback()
    with pytest.raises(DatabaseError):
        db_session.execute(text("DELETE FROM record_events"))
    db_session.rollback()


def test_the_verifier_detects_a_tampered_copy(client, db_session, tmp_path):
    approve_one(client, db_session)
    src = db_session.get_bind().url.database
    copy = tmp_path / "copy.db"
    shutil.copy(src, copy)
    con = sqlite3.connect(copy)
    con.execute("DROP TRIGGER clinical_records_no_update")
    con.execute("UPDATE clinical_records SET content_json = replace(content_json, 'Citlivý', 'Necitlivý') "
                "WHERE id = (SELECT id FROM clinical_records ORDER BY created_at DESC LIMIT 1)")
    con.commit()
    con.close()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine(f"sqlite:///{copy}")
    s = sessionmaker(bind=eng)()
    try:
        res = R.verify(s)
    finally:
        s.close()
        eng.dispose()
    assert res["ok"] is False and res["problem"] == "content"


def test_approval_needs_provider_and_patient_identity(client, db_session):
    bid = _visit(db_session)
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft", json={"summary": "x"}).json()["id"]
    card = R.card(db_session, "cli-0001", RID)
    street = card.permanent_street
    card.permanent_street = None
    db_session.commit()
    try:
        r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": False})
        assert r.status_code == 409 and r.json()["detail"].startswith("Doplňte v kartě klienta:") and r.json()["missing"]
        assert db_session.query(models.Conclusion).get(cid).status == "draft"        # nothing half-written
    finally:
        card.permanent_street = street
        db_session.commit()
    clinic = db_session.get(models.Clinic, "cli-0001")
    ico, clinic.ico = clinic.ico, None
    db_session.commit()
    try:
        r = client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": False})
        assert r.status_code == 409 and "Praxi" in r.json()["detail"]
    finally:
        clinic.ico = ico
        db_session.commit()


def test_encrypted_card_fields(client, db_session, monkeypatch):
    login(client, PHYSIO)
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    assert client.put(f"/api/physios/me/clients/{RID}/card", json={"rodne_cislo": "915514/1234"}).status_code == 409
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    r = client.put(f"/api/physios/me/clients/{RID}/card", json={"rodne_cislo": "915514/1234"}).json()
    assert r["rodne_cislo"] == "915514/1234"
    db_session.expire_all()
    raw = R.card(db_session, "cli-0001", RID).rodne_cislo_enc
    assert raw.startswith("v1:") and "915514" not in raw


def test_recording_needs_the_clients_consent(client, db_session, monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "ASR_BASE_URL", "https://asr.invalid")
    monkeypatch.setattr(llm, "ASR_API_KEY", "k")
    monkeypatch.setattr(llm, "transcribe", lambda *a, **k: "Přepis")
    bid = _visit(db_session)
    login(client, PHYSIO)
    cid = client.post(f"/api/bookings/{bid}/conclusion/draft", json={"summary": "x"}).json()["id"]
    up = lambda: client.post(f"/api/conclusions/{cid}/audio", files={"file": ("a.webm", b"0" * 10, "audio/webm")})  # noqa: E731
    assert up().status_code == 409
    assert client.post(f"/api/bookings/{bid}/recording-consent").status_code == 200
    assert up().status_code == 200
