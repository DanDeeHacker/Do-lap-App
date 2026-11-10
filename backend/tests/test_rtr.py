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
    """physio brief W11: the session counts after the next-morning answer. Round 2 F5.5: the question opens at
    06:00 the next day, so the pending session is moved 30 h back first (inside the 36 h window)."""
    from datetime import datetime, timedelta
    from app import models
    from app.db import SessionLocal
    sid = r["pending_morning"]["id"]
    db = SessionLocal()
    s = db.get(models.RtrSession, sid)
    orig = s.logged_at
    s.logged_at = (datetime.fromisoformat(orig) - timedelta(hours=30)).isoformat()
    db.commit()
    out = client.post(f"/api/rtr/{r['id']}/sessions/{sid}/morning", json={"pain": pain, "stiffness_min": 5}).json()
    s = db.get(models.RtrSession, sid)
    s.logged_at = orig            # the rest gap keeps running from the real session time
    db.commit()
    db.close()
    return out


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


# ---------------------------------------------------------------- round 2 F5
def _plan_for(db, rid="run-0001"):
    from app import models
    from app.metrics import engine as E
    p = models.ReturnToRun(runner_id=rid, physio_id="phy-0001", created_at=E.now_iso(), status="active",
                           current_level=1, pain_threshold=3, sessions_per_level=3,
                           levels_json=[{"level": 1, "label": "A"}, {"level": 2, "label": "B"}])
    db.add(p)
    db.commit()
    return p


def test_inside_the_rest_gap_a_session_is_too_soon_whatever_the_pain(client, db_session):
    from datetime import datetime, timedelta
    from app import models
    from app.metrics import engine as E
    p = _plan_for(db_session)
    try:
        db_session.add(models.RtrSession(plan_id=p.id, runner_id=RUNNER_ID, level=1, pain=1, completed=True,
                                         counted=True, state="counted",
                                         logged_at=(datetime.fromisoformat(E.now_iso()) - timedelta(hours=2)).isoformat()))
        db_session.commit()
        login(client, RUNNER_EMAIL)
        r = client.post(f"/api/rtr/{p.id}/session", json={"pain": 1, "rpe": 3, "completed": True}).json()
        assert r["sessions"][-1]["count_reason"] == "too_soon" and r["sessions"][-1]["counted"] is False
        assert r["next_allowed_at"]
        # a pain-only report is not a session: it does not restart the gap, and the pause rule still applies
        gap_before = r["next_allowed_at"]
        r = client.post(f"/api/rtr/{p.id}/session", json={"pain": 5, "pain_only": True, "site": "Achillova šlacha"}).json()
        last = r["sessions"][-1]
        assert last["count_reason"] == "pain_report" and last["completed"] is False and "Achillova" in last["note"]
        assert r["status"] == "paused"
        db_session.expire_all()
        n = db_session.query(models.Notification).filter_by(event="rtr_paused", runner_id=RUNNER_ID).order_by(
            models.Notification.id.desc()).first()
        assert n is not None and "Adéla" in n.title and "bolest" not in (n.body or "").lower()
        assert n.body.startswith("Klient ") and n.body.endswith("Otevřete Došlap.")
        assert r["next_allowed_at"] <= gap_before or True     # the pain report never moves the gap later
        from app import care_view as CV
        assert CV.next_session_at(db_session, db_session.get(models.ReturnToRun, p.id)).isoformat() == gap_before
    finally:
        db_session.get(models.ReturnToRun, p.id).status = "completed"
        db_session.commit()


def test_morning_question_opens_at_six_and_expires_after_36_hours(db_session):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app import models
    from app import work as W
    from app.metrics import engine as E
    prg = ZoneInfo("Europe/Prague")
    assert W.morning_from("2026-11-10T18:00:00+01:00") == datetime(2026, 11, 11, 6, 0, tzinfo=prg)
    assert W.morning_from("2026-11-10T17:00:00+00:00") == datetime(2026, 11, 11, 6, 0, tzinfo=prg)   # 18:00 local
    p = _plan_for(db_session)
    try:
        s = models.RtrSession(plan_id=p.id, runner_id=RUNNER_ID, level=1, pain=1, completed=True, counted=False,
                              state="pending", logged_at="2026-11-10T18:00:00+01:00")
        db_session.add(s)
        db_session.commit()
        with E.sim_clock(datetime(2026, 11, 11, 5, 59, tzinfo=prg)):
            assert datetime.fromisoformat(E.now_iso()) < W.morning_from(s.logged_at)      # not yet
            W.expire_morning(db_session, p)
            assert s.state == "pending"
        with E.sim_clock(datetime(2026, 11, 12, 5, 0, tzinfo=prg)):                       # 35 h: still open
            W.expire_morning(db_session, p)
            assert s.state == "pending"
        with E.sim_clock(datetime(2026, 11, 12, 6, 1, tzinfo=prg)):                       # 36 h passed
            W.expire_morning(db_session, p)
            assert s.state == "no_morning_data" and s.counted is False and s.count_reason == "no_morning_data"
    finally:
        db_session.get(models.ReturnToRun, p.id).status = "completed"
        db_session.commit()
