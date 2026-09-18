"""Targeted coverage of the security-critical paths: auth itself, and every
place a session is used to scope access to someone else's data. Not a full
endpoint test matrix — see the plan doc for why these specific paths.
"""
from app import models
from .conftest import login, register

RUNNER_EMAIL = "adela@demo.cz"
PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"
EMPLOYER_EMAIL = "hexanet@demo.cz"
PARTNER_EMAIL = "letna@demo.cz"


# ---------------------------------------------------------------- auth
def test_register_login_logout_roundtrip(client):
    r = register(client, "newrunner@test.cz", "Nový Běžec", "runner")
    assert r.status_code == 200
    assert r.json()["role"] == "runner"
    assert r.json()["runner_id"]

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    r = login(client, "newrunner@test.cz", "testpass123")
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_duplicate_email_rejected(client):
    register(client, "dupe@test.cz", "Dupe", "runner")
    r2 = register(client, "dupe@test.cz", "Dupe Two", "runner")
    assert r2.status_code == 400


def test_wrong_password_rejected(client):
    r = login(client, RUNNER_EMAIL, "not-the-password")
    assert r.status_code == 401


def test_unauthenticated_me_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_login_wrong_door_rejected(client):
    r = login(client, PHYSIO_EMAIL, expected_role="runner")
    assert r.status_code == 403
    r2 = login(client, PHYSIO_EMAIL, expected_role="physio")
    assert r2.status_code == 200


def test_csrf_blocks_cross_origin_mutation(client):
    r = client.post(
        "/api/auth/session", json={"email": RUNNER_EMAIL, "password": "demo1234"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------- runner scoping
def test_runner_can_read_own_data(client):
    login(client, RUNNER_EMAIL)
    r = client.get("/api/runners/run-0001")
    assert r.status_code == 200
    assert r.json()["id"] == "run-0001"


def test_runner_cannot_read_another_runners_data(client):
    login(client, RUNNER_EMAIL)  # run-0001
    r = client.get("/api/runners/run-0002")
    assert r.status_code == 403


def test_runner_cannot_write_another_runners_checkin(client):
    login(client, RUNNER_EMAIL)  # run-0001
    r = client.post("/api/runners/run-0002/checkins", json={"pain_score": 5})
    assert r.status_code == 403


# ---------------------------------------------------------------- physio scoping
def test_physio_denied_before_claim(client):
    register(client, "newphysio@test.cz", "Nový Fyzio", "physio", "testpass123")
    r = client.get("/api/runners/run-0001")
    assert r.status_code == 403


def test_physio_allowed_after_seeded_claim(client):
    # Seed data already has phy-0001 assigned to run-0001 via a care_assignment.
    login(client, PHYSIO_EMAIL, expected_role="physio")
    r = client.get("/api/runners/run-0001")
    assert r.status_code == 200


def test_physio_can_claim_then_access(client):
    register(client, "physio2@test.cz", "Fyzio Dva", "physio", "testpass123")
    q = client.get("/api/triage?status=open").json()
    unclaimed = next((t for t in q if t["runner_id"] != "run-0001"), None)
    assert unclaimed is not None, "expected at least one open seeded triage case besides run-0001"
    rid = unclaimed["runner_id"]

    assert client.get(f"/api/runners/{rid}").status_code == 403
    claim_resp = client.patch(f"/api/triage/{unclaimed['id']}/claim")
    assert claim_resp.status_code == 200
    assert client.get(f"/api/runners/{rid}").status_code == 200


def test_ai_brief_not_available_to_runner_role(client):
    login(client, RUNNER_EMAIL)
    r = client.post("/api/ai/brief", json={"runner_id": "run-0001", "intent": "summary"})
    assert r.status_code == 403


# ---------------------------------------------------------------- employer k-anonymity
def test_employer_cohort_blocked_under_min_cohort(client):
    login(client, EMPLOYER_EMAIL, expected_role="employer")
    r = client.get("/api/employers/emp-0001/cohort")
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert body["n"] < 8


def test_employer_cannot_read_another_employer(client):
    login(client, EMPLOYER_EMAIL, expected_role="employer")
    r = client.get("/api/employers/emp-0002/cohort")
    assert r.status_code == 403


def test_employer_cohort_unblocked_once_large_enough(client, db_session):
    existing = db_session.query(models.Runner).filter(models.Runner.employer_id == "emp-0001").count()
    needed = max(0, 8 - existing)
    for i in range(needed):
        rid = f"run-filler-{i}"
        db_session.add(models.Runner(id=rid, name=f"Filler {i}", employer_id="emp-0001"))
    db_session.commit()

    login(client, EMPLOYER_EMAIL, expected_role="employer")
    r = client.get("/api/employers/emp-0001/cohort")
    body = r.json()
    assert body["blocked"] is False
    assert body["n"] >= 8
    assert "byTier" in body and "byQuadrant" in body
    # never leaks a per-runner row
    assert "runners" not in body and "runner" not in body


# ---------------------------------------------------------------- partner scoping
def test_partner_can_read_own_referrals(client):
    login(client, PARTNER_EMAIL, expected_role="partner")
    r = client.get("/api/partners/par-0001/referrals")
    assert r.status_code == 200


def test_partner_cannot_read_another_partner(client):
    login(client, PARTNER_EMAIL, expected_role="partner")
    r = client.get("/api/partners/par-0002/referrals")
    assert r.status_code == 403
