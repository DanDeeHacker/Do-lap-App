"""Physio brief 2026-11-09 R11: retention from the last service (1 January after it + 5 years); records past it
are listed, never deleted automatically; destruction needs an approved list and leaves a log that cannot be
removed; deleting the runner account keeps the card and the records."""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app import models
from app import records as R

from .conftest import login, register
from .test_records_ledger import approve_one


def test_retention_rule():
    assert R.retain_until_for(date(2026, 3, 1)) == "2032-01-01"
    assert R.retain_until_for(date(2026, 12, 31)) == "2032-01-01"


def test_destruction_only_past_retention_and_logged(client, db_session):
    c = approve_one(client, db_session)
    card_id = db_session.get(models.ClinicalRecord, c["record_id"]).patient_record_id
    body = {"patient_record_ids": [card_id], "method": "skartace", "approved_by": "vlastník"}
    assert client.post("/api/physios/me/destructions", json=body).status_code == 409       # not yet
    # a separate past-retention card (a copied case from 2019) to destroy
    old = models.PatientRecord(id=R.new_record_id(), clinic_id="cli-0001", first_name="Starý", last_name="Klient",
                               retain_until="2025-01-01")
    db_session.add(old)
    db_session.commit()
    rec = R.write_record(db_session, clinic=db_session.get(models.Clinic, "cli-0001"), patient=old,
                         author=db_session.get(models.Physio, "phy-0001"), kind="visit_note",
                         encounter_at="2019-05-02T10:00:00+02:00", content={"summary": "x"})
    old.retain_until = "2025-01-01"
    db_session.commit()
    with pytest.raises(DatabaseError):                       # no logged destruction → the database refuses
        db_session.execute(text("DELETE FROM clinical_records WHERE id = :i"), {"i": rec.id})
    db_session.rollback()
    assert old.id in {x["id"] for x in client.get("/api/physios/me/retention-due").json()["items"]}
    r = client.post("/api/physios/me/destructions", json={**body, "patient_record_ids": [old.id]})
    assert r.status_code == 200 and r.json()["destroyed"][0]["records"] == 1
    db_session.expire_all()
    assert db_session.query(models.ClinicalRecord).filter_by(patient_record_id=old.id).count() == 0
    log = db_session.query(models.RecordDestruction).filter_by(patient_record_id=old.id).one()
    assert log.keep_until > "2060"
    with pytest.raises(DatabaseError):
        db_session.execute(text("DELETE FROM record_destructions"))
    db_session.rollback()


def test_account_deletion_keeps_the_record(client, db_session):
    rid = register(client, "smaze-se@test.cz", "Smaže Se", "runner").json()["runner_id"]
    db_session.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at="2026-11-01"))
    db_session.add(models.Message(runner_id=rid, sender="runner", body="ahoj", created_at="2026-11-01"))
    card = models.PatientRecord(id=R.new_record_id(), clinic_id="cli-0001", runner_id=rid, first_name="Smaže",
                                last_name="Se", birth_date="1990-01-01", sex_at_birth="m", permanent_street="A 1",
                                permanent_city="Praha", permanent_postal_code="17000")
    db_session.add(card)
    db_session.commit()
    R.write_record(db_session, clinic=db_session.get(models.Clinic, "cli-0001"), patient=card,
                   author=db_session.get(models.Physio, "phy-0001"), kind="visit_note",
                   encounter_at="2026-11-02T10:00:00+01:00", content={"summary": "x"})
    db_session.commit()
    assert client.post(f"/api/runners/{rid}/account/delete", json={"confirm": "ne"}).status_code == 422
    assert client.post(f"/api/runners/{rid}/account/delete", json={"confirm": "SMAZAT"}).status_code == 200
    db_session.expire_all()
    assert db_session.get(models.Runner, rid) is None
    assert db_session.query(models.Message).filter_by(runner_id=rid).count() == 0
    kept = db_session.get(models.PatientRecord, card.id)
    assert kept is not None and kept.runner_id is None
    assert db_session.query(models.ClinicalRecord).filter_by(patient_record_id=card.id).count() == 1
