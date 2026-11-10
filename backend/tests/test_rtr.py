"""Return-to-run ladder — physio prescribes, runner logs, the plan advances
only on pain-free completed sessions, high pain is a non-advancing setback,
and access is scoped (physio can't log for the runner, other runners can't
touch the plan). One controlled flow keeps the shared-seed DB deterministic.
"""
from .conftest import login, register

RUNNER_EMAIL = "adela@demo.cz"          # run-0001, claimed by phy-0001 in the seed
PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"
RUNNER_ID = "run-0001"


READY = {"items": {"walk_30": True, "daily_pain_lt2": True, "no_night_pain": True, "no_limp": True}, "tests": []}


def _morning(client, r, pain=0):
    """physio brief W11: the session counts after the next-morning answer."""
    sid = r["pending_morning"]["id"]
    return client.post(f"/api/rtr/{r['id']}/sessions/{sid}/morning", json={"pain": pain, "stiffness_min": 5}).json()


def _age_sessions(db, pid, hours=21):
    """Move the logged sessions back past the rest gap (physio brief 2026-11-09 P0.7)."""
    from datetime import datetime, timedelta
    from app import models
    for s in db.query(models.RtrSession).filter(models.RtrSession.plan_id == pid).all():
        s.logged_at = (datetime.fromisoformat(s.logged_at) - timedelta(hours=hours)).isoformat()
    db.commit()


def test_rtr_full_flow(client, db_session):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    levels = [{"level": 1, "label": "A"}, {"level": 2, "label": "B"}, {"level": 3, "label": "C"}]
    plan = client.post("/api/rtr", json={
        "runner_id": RUNNER_ID, "sessions_per_level": 1, "levels": levels,
        "note": "Po tendinopatii Achillovky", "readiness": READY,
    })
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    pid = plan["id"]
    assert plan["current_level"] == 1 and plan["level_count"] == 3

    # only one active plan per runner
    assert client.post("/api/rtr", json={"runner_id": RUNNER_ID, "readiness": READY}).status_code == 409
    # physio may not log sessions on the runner's behalf
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 1}).status_code == 403

    # a different runner may not touch this plan
    register(client, "rtrother@test.cz", "Jiný Běžec", "runner")
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 1}).status_code == 403

    login(client, RUNNER_EMAIL)
    boot = client.get(f"/api/runners/{RUNNER_ID}/bootstrap").json()
    assert boot["rtr"] and boot["rtr"]["id"] == pid
    # the physio's note reaches the runner (P0.7)
    assert any("Po tendinopatii Achillovky" in (m["body"] or "") for m in boot["messages"])

    # no default pain (P0.7)
    assert client.post(f"/api/rtr/{pid}/session", json={"completed": True}).status_code == 422
    # clear level 1 → it waits for the morning (W11), then advances to 2
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 1, "completed": True}).json()
    assert r["current_level"] == 1 and r["pending_morning"]
    r = _morning(client, r, pain=1)
    assert r["current_level"] == 2
    # a second session within 20 hours is kept but does not count (P0.7)
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 1, "completed": True}).json()
    assert r["current_level"] == 2 and r["sessions"][-1]["count_reason"] == "too_soon"
    _age_sessions(db_session, pid)
    # clear level 2 → advance to 3 (a morning worse than the session would not count)
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 2, "completed": True}).json()
    r = _morning(client, r, pain=1)
    assert r["current_level"] == 3
    _age_sessions(db_session, pid)
    # pain over the limit pauses the plan, is not counted and goes to the physio only (P0.7, P0.10)
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 5, "completed": True}).json()
    assert r["current_level"] == 3 and r["status"] == "paused" and r["paused_reason"] == "pain_over_limit"
    assert r["sessions"][-1]["counted"] is False and r["sessions"][-1]["count_reason"] == "pain_over_limit"
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 0}).status_code == 409    # paused
    assert not any("Návrat k běhu: klient hlásí" in (m["body"] or "")
                   for m in client.get(f"/api/runners/{RUNNER_ID}/messages").json())
    # only the physio resumes it
    assert client.patch(f"/api/rtr/{pid}?status=active").status_code == 403
    login(client, PHYSIO_EMAIL, expected_role="physio")
    assert any("Návrat k běhu: klient hlásí" in (m["body"] or "")
               for m in client.get(f"/api/runners/{RUNNER_ID}/messages").json())
    assert client.patch(f"/api/rtr/{pid}?status=active").json()["status"] == "active"
    login(client, RUNNER_EMAIL)
    _age_sessions(db_session, pid)
    # a passing session at level 3 → plan completed after the morning
    r = client.post(f"/api/rtr/{pid}/session", json={"pain": 0, "completed": True}).json()
    r = _morning(client, r, pain=0)
    assert r["status"] == "completed"
    # can't log against a completed plan
    assert client.post(f"/api/rtr/{pid}/session", json={"pain": 0}).status_code == 409


def test_rtr_requires_care_assignment(client):
    register(client, "rtrphysio@test.cz", "Nepřevzatý Fyzio", "physio", "testpass123")
    r = client.post("/api/rtr", json={"runner_id": RUNNER_ID, "readiness": READY})
    assert r.status_code == 403
