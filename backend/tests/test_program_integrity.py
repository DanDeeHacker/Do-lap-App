"""Physio brief 2026-11-09 P0.8: no invented reason, no blank dose, per_week 1–7, every change logged
with a full timestamp, a stable order, one library item once, targets per_week × weeks, an end date."""
from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


def _program(client, db):
    login(client, PHYSIO)
    pid = client.post("/api/programs", json={"runner_id": RID, "site": "Achillova šlacha"}).json()["id"]
    client.post(f"/api/programs/{pid}/send", json={})
    return pid


def test_validation_and_the_reason(client, db_session):
    pid = _program(client, db_session)
    ex = client.get(f"/api/runners/{RID}/program").json()
    assert ex["id"] == pid
    first = ex["exercises"][0]
    eid = first["id"]
    assert first["target_count"] == first["per_week"] * 4
    r = client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"dose": "  "}, "note": "x"})
    assert r.status_code == 422
    for bad in (0, 8):
        assert client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": bad}, "note": "x"}).status_code == 422
    # W10: edits to a sent programme are a draft; publishing asks for the reason the client sees (P0.8)
    assert client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"cue": ""}}).status_code == 200
    r = client.post(f"/api/programs/{pid}/send", json={})
    assert r.status_code == 422 and "důvod" in r.json()["detail"]
    assert client.post(f"/api/programs/{pid}/send", json={"note": "Pokyn už není potřeba"}).status_code == 200
    revs = db_session.query(models.ProgramRevision).filter_by(program_id=pid).all()
    assert revs[-1].note == "Pokyn už není potřeba" and "pokyn odstraněn" in revs[-1].changes[0]
    assert "T" in revs[-1].at and not any(rv.note == "Úprava po zpětné vazbě pacienta." for rv in revs)
    assert all(rv.note for rv in revs)                     # nothing pending after the publish


def test_order_is_stable_and_a_library_item_is_added_once(client, db_session):
    pid = _program(client, db_session)
    order = [e["id"] for e in client.get(f"/api/runners/{RID}/program").json()["exercises"]]
    client.patch(f"/api/programs/exercises/{order[0]}", json={"patch": {"dose": "3 × 10"}, "note": "Méně opakování"})
    client.post(f"/api/programs/{pid}/send", json={"note": "Méně opakování"})
    login(client, "adela@demo.cz")
    client.patch(f"/api/runners/{RID}/exercises/{order[1]}/log")
    assert [e["id"] for e in client.get(f"/api/runners/{RID}/program").json()["exercises"]] == order
    login(client, PHYSIO)
    body = {"name": "Most na jedné noze", "dose": "3 × 10", "per_week": 3, "library_id": "lib-bridge-1"}
    assert client.post(f"/api/programs/{pid}/exercises", json=body).status_code == 200
    assert client.post(f"/api/programs/{pid}/exercises", json=body).status_code == 409
    prog = client.get(f"/api/runners/{RID}/program").json()
    assert prog["exercises"][-1]["library_id"] == "lib-bridge-1" and prog["ends_on"]


def test_changing_per_week_keeps_what_is_done(client, db_session):
    pid = _program(client, db_session)
    eid = client.get(f"/api/runners/{RID}/program").json()["exercises"][0]["id"]
    e = db_session.get(models.Exercise, eid)
    e.done_count = 2
    db_session.commit()
    client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": 2}, "note": "Méně často"})
    db_session.expire_all()
    e = db_session.get(models.Exercise, eid)
    assert e.target_count == 2 + 2 * 4 and E.today_date()
