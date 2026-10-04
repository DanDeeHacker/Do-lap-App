"""Getting-started checklist and the read-only tour demo."""
from app import models
from .conftest import login, register


def test_new_runner_checklist_ticks_off_and_can_be_dismissed(client, db_session):
    rid = register(client, "onb1@test.cz", "Nová Běžkyně", "runner").json()["runner_id"]
    ob = client.get(f"/api/runners/{rid}/onboarding").json()
    assert ob["active"] and not ob["dismissed"] and not ob["completed"]
    assert [s["id"] for s in ob["steps"]] == ["data", "tutorial"] and not any(s["done"] for s in ob["steps"])
    # v0.12.0: the profile is asked before the checklist, not a step of it
    assert ob["profileMissing"] == ["birth_year", "sex", "running_since"]

    # data = a connected source or any imported data
    assert client.patch(f"/api/runners/{rid}", json={"patch": {"birth_year": 1990, "sex": "f"}}).status_code == 200
    db_session.add(models.DailyMetric(runner_id=rid, date="2026-09-01", sleep_h=7.0))
    db_session.commit()
    ob = client.get(f"/api/runners/{rid}/onboarding").json()
    assert [s["done"] for s in ob["steps"]] == [True, False] and ob["profileMissing"] == ["running_since"]
    r = client.patch(f"/api/runners/{rid}", json={"patch": {"running_since": "2026-03", "weight_kg": "61,5",
                                                            "menstrual_json": {"track": True, "length": 30, "starts": ["2026-09-01"]}}})
    assert r.status_code == 200 and r.json()["running_since"] == "2026-03-01" and r.json()["weight_kg"] == 61.5
    assert r.json()["menstrual_json"]["length"] == 30
    assert client.get(f"/api/runners/{rid}/onboarding").json()["profileMissing"] == []
    assert client.patch(f"/api/runners/{rid}", json={"patch": {"sex": "x"}}).status_code == 422
    assert client.patch(f"/api/runners/{rid}", json={"patch": {"weight_kg": 500}}).status_code == 422
    # a man's profile keeps no cycle data
    r = client.patch(f"/api/runners/{rid}", json={"patch": {"sex": "m"}})
    assert r.json()["menstrual_json"] is None

    assert client.post(f"/api/runners/{rid}/onboarding", json={"dismissed": True}).json()["dismissed"] is True
    ob = client.post(f"/api/runners/{rid}/onboarding", json={"tutorialDone": True}).json()
    assert ob["completed"] is True


def test_older_accounts_have_no_checklist_and_tour_demo_is_read_only(client):
    assert login(client, "adela@demo.cz").status_code == 200
    me = client.get("/api/auth/me").json()
    assert client.get(f"/api/runners/{me['runner_id']}/onboarding").json()["active"] is False

    rid = register(client, "onb2@test.cz", "Tour Test", "runner").json()["runner_id"]
    demo = client.get(f"/api/runners/{rid}/tutorial-demo").json()["runner_id"]
    assert client.get(f"/api/runners/{demo}/bootstrap").status_code == 200        # the tour can read it
    assert client.get(f"/api/runners/{demo}/quadrant-history").status_code == 200
    assert client.post(f"/api/runners/{demo}/checkins", json={"pain_score": 1}).status_code == 403   # never write
    other = register(client, "onb3@test.cz", "Jiný", "runner").json()["runner_id"]
    client.post("/api/auth/session", json={"email": "onb2@test.cz", "password": "testpass123"})
    assert client.get(f"/api/runners/{other}/bootstrap").status_code == 403       # other runners stay private


def test_tour_demo_always_has_training_journal_races_and_care(client):
    """The generated tour runner shows real content on every tab, on any weekday."""
    from datetime import date, timedelta
    from app import tutorial_demo
    from app.db import SessionLocal
    from app.metrics import engine as E
    rid = register(client, "onb4@test.cz", "Průvodce", "runner").json()["runner_id"]
    demo = client.get(f"/api/runners/{rid}/tutorial-demo").json()["runner_id"]
    assert demo == tutorial_demo.TUTORIAL_RID
    b = client.get(f"/api/runners/{demo}/bootstrap").json()
    assert len(b["activities"]) > 80 and len(b["activity_feedback"]) >= 10 and len(b["checkins"]) >= 10
    assert any(f["pain_points"] for f in b["activity_feedback"])                 # the body map has a point
    assert len(client.get(f"/api/runners/{demo}/activities/unrated").json()) >= 1  # "Čeká na zápis"
    assert b["messages"] and b["program"] and b["program"]["exercises"] and b["conclusions"]
    assert len(client.get(f"/api/runners/{demo}/races").json()) >= 2
    db = SessionLocal()
    try:
        assert not db.query(models.EngineDailySnapshot).filter_by(runner_id=demo).count()
        for k in range(7):                                                         # every weekday offers a run
            with E.today_pinned(date(2026, 9, 28) + timedelta(days=k)):
                tutorial_demo._rebuild(db)
                g = E.get_or_refresh_assessment(db, demo)["guidance"]
                assert g["type"] not in ("volno", "závod") and g["types"][g["type"]]["km"]["hi"] > 3, (k, g["reasons"])
    finally:
        db.close()
