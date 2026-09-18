"""Return-to-run ladder — physio prescribes, runner logs, the plan advances
only on pain-free completed sessions, high pain is a non-advancing setback,
and access is scoped (physio can't log for the runner, other runners can't
touch the plan). One controlled flow keeps the shared-seed DB deterministic.
"""
from .conftest import login, register

RUNNER_EMAIL = "adela@demo.cz"          # run-0001, claimed by phy-0001 in the seed
PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"
RUNNER_ID = "run-0001"


def test_rtr_full_flow(client):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    levels = [{"level": 1, "label": "A"}, {"level": 2, "label": "B"}, {"level": 3, "label": "C"}]
    plan = client.post("/api/rtr", json={
        "runner_id": RUNNER_ID, "sessions_per_level": 1, "levels": levels,
        "note": "Po tendinopatii Achillovky",
    }).json()
    pid = plan["id"]
    assert plan["current_level"] == 1 and plan["level_count"] == 3

    # only one active plan per runner
    assert client.post("/api/rtr", json={"runner_id": RUNNER_ID}).status_code == 409
    # physio may not log sessions on the runner's behalf
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 1}).status_code == 403

    # a different runner may not touch this plan
    register(client, "rtrother@test.cz", "Jiný Běžec", "runner")
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 1}).status_code == 403

    login(client, RUNNER_EMAIL)
    boot = client.get(f"/api/runners/{RUNNER_ID}/bootstrap").json()
    assert boot["rtr"] and boot["rtr"]["id"] == pid

    # clear level 1 → advance to 2
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 1, "completed": True}).json()
    assert r["current_level"] == 2
    # clear level 2 → advance to 3
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 2, "completed": True}).json()
    assert r["current_level"] == 3
    # setback at level 3 (pain over threshold+2) → stays, not counted, still active
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 8, "completed": True}).json()
    assert r["current_level"] == 3 and r["status"] == "active"
    assert r["sessions"][-1]["counted"] is False
    # a passing session at level 3 → plan completed
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 0, "completed": True}).json()
    assert r["status"] == "completed"
    # can't log against a completed plan
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 0}).status_code == 409


def test_rtr_requires_care_assignment(client):
    register(client, "rtrphysio@test.cz", "Nepřevzatý Fyzio", "physio", "testpass123")
    r = client.post("/api/rtr", json={"runner_id": RUNNER_ID})
    assert r.status_code == 403
