"""Getting-started checklist and the read-only tour demo."""
from app import models
from .conftest import login, register


def test_new_runner_checklist_ticks_off_and_can_be_dismissed(client, db_session):
    rid = register(client, "onb1@test.cz", "Nová Běžkyně", "runner").json()["runner_id"]
    ob = client.get(f"/api/runners/{rid}/onboarding").json()
    assert ob["active"] and not ob["dismissed"] and not ob["completed"]
    assert [s["id"] for s in ob["steps"]] == ["data", "profile", "tutorial"] and not any(s["done"] for s in ob["steps"])

    # profile = birth year + sex; data = a connected source or any imported data
    assert client.patch(f"/api/runners/{rid}", json={"patch": {"birth_year": 1990, "sex": "f"}}).status_code == 200
    db_session.add(models.DailyMetric(runner_id=rid, date="2026-09-01", sleep_h=7.0))
    db_session.commit()
    ob = client.get(f"/api/runners/{rid}/onboarding").json()
    assert [s["done"] for s in ob["steps"]] == [True, True, False]

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
