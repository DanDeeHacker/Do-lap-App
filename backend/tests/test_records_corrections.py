"""Physio brief 2026-11-09 R6: a correction is a new entry; the original stays readable; two corrections in a
row display correctly; a corrected client summary reaches the client marked as corrected."""
from app import models

from .conftest import login
from .test_records_ledger import approve_one

RID = "run-0001"


def test_two_corrections_and_the_original(client, db_session):
    c = approve_one(client, db_session, summary="Původní shrnutí.")
    rid0 = c["record_id"]
    r = client.post(f"/api/clinical-records/{rid0}/corrections", json={"changes": {"objective": "Oprava 1"}, "reason": ""})
    assert r.status_code == 422
    client.post(f"/api/clinical-records/{rid0}/corrections", json={"changes": {"objective": "Oprava 1"}, "reason": "Překlep"})
    v = client.post(f"/api/clinical-records/{rid0}/corrections",
                    json={"changes": {"summary": "Opravené shrnutí."}, "reason": "Na žádost", "at_patient_request": True}).json()
    assert v["current"]["objective"] == "Oprava 1" and v["current"]["summary"] == "Opravené shrnutí."
    assert v["original"]["objective"] == "Citlivý úpon." and len(v["corrections"]) == 2
    assert v["current"]["note_patient_request"] and v["corrections"][1]["at_patient_request"]
    doc = client.get(f"/api/physios/me/clients/{RID}/documentation").json()
    mine = next(x for x in doc["records"] if x["id"] == rid0)
    assert mine["current"]["summary"] == "Opravené shrnutí."
    assert db_session.get(models.ClinicalRecord, rid0).content_json.count("Citlivý úpon.") == 1   # untouched
    login(client, "adela@demo.cz")
    shown = client.get(f"/api/conclusions/{c['id']}").json()
    assert shown["summary"] == "Opravené shrnutí." and shown["corrected_at"]
