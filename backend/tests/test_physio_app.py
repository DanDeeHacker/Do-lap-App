"""The physio app's own endpoints (owner request 2026-10-27, report v6 Section 6.2.7–6.2.8): the
physio's profile and clinic, the client list, the client overview before a visit and the
documentation — all behind the care assignment, every read in the runner's access log."""
from app import models

from .conftest import login, register

PHYSIO = "havlickova@fyzioholesovice.cz"


def _physio(client):
    r = login(client, PHYSIO)
    assert r.status_code == 200, r.text
    return r.json()


def test_profile_and_clinic_set_the_queue_region(client, db_session):
    _physio(client)
    me = client.get("/api/physios/me").json()
    assert me["email"] == PHYSIO and me["clinic"]
    r = client.patch("/api/physios/me", json={"credential": "Mgr., fyzioterapeutka", "bio": "Běžecká zranění.",
                                               "specialties": ["Achillova šlacha", " ", "koleno"], "price_czk": 1190})
    assert r.status_code == 200 and r.json()["specialties"] == ["Achillova šlacha", "koleno"] and r.json()["complete"]


def test_a_new_physio_sets_up_a_clinic(client):
    register(client, "nova-fyzio@test.cz", "Nová Fyzio", "physio")
    me = client.get("/api/physios/me").json()
    assert me["clinic"] is None and not me["complete"]
    me = client.patch("/api/physios/me", json={"credential": "Bc.", "clinic_name": "Fyzio Brno", "clinic_city": "Brno"}).json()
    assert me["clinic"]["city"] == "Brno" and me["complete"]
    # review 2026-10-30 F1: until an owner verifies the account, no runner data at all
    assert not me["verified"]
    assert client.get("/api/physios/me/clients").status_code == 403
    assert client.get("/api/triage").status_code == 403


def test_clients_overview_and_documentation_need_the_care_assignment(client, db_session):
    _physio(client)
    items = client.get("/api/physios/me/clients").json()["items"]
    assert items, "the demo physio has clients"
    c = items[0]
    assert {"runnerId", "name", "a", "attention", "program", "rtr", "next"} <= set(c)
    rid = c["runnerId"]
    ov = client.get(f"/api/physios/me/clients/{rid}")
    assert ov.status_code == 200
    ov = ov.json()
    assert ov["runner"]["name"] and "signals" in ov["a"] and len(ov["weeks"]) == 12 and isinstance(ov["checkins"], list)
    pid = db_session.query(models.User).filter(models.User.email == PHYSIO).one().physio_id
    db_session.expire_all()
    log = db_session.query(models.AccessLog).filter(models.AccessLog.runner_id == rid, models.AccessLog.physio_id == pid).all()
    assert any(x.resource in ("přehled klienta", "dokumentace") or x.action == "read" for x in log)
    doc = client.get(f"/api/physios/me/clients/{rid}/documentation").json()
    assert doc["physio"]["email"] == PHYSIO and isinstance(doc["visits"], list)
    # someone not in my care
    other = db_session.query(models.Runner).filter(~models.Runner.id.in_([i["runnerId"] for i in items])).first()
    assert client.get(f"/api/physios/me/clients/{other.id}").status_code == 403
    assert client.get(f"/api/physios/me/clients/{other.id}/documentation").status_code == 403


def test_runners_cannot_use_the_physio_app(client):
    register(client, "bezec-fyzioapp@test.cz", "Běžec", "runner")
    assert client.get("/api/physios/me").status_code == 403
    assert client.get("/api/physios/me/clients").status_code == 403


def test_a_physio_signs_in_through_the_physio_choice(client):
    r = login(client, PHYSIO, expected_role="physio")
    assert r.status_code == 200 and r.json()["role"] == "physio"
