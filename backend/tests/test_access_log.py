"""GDPR access log: a physio's access to a runner's record is recorded and
deduped per day, the runner (data subject) can see who accessed their data,
and no one can read another runner's access log.
"""
from .conftest import login

RUNNER_EMAIL = "adela@demo.cz"      # run-0001, claimed by phy-0001
PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"   # phy-0001
RUNNER_ID = "run-0001"


def test_physio_access_is_logged_and_visible_to_runner(client):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    # two reads on the same day should collapse into one row with count >= 2
    client.get(f"/api/runners/{RUNNER_ID}/bootstrap")
    client.get(f"/api/runners/{RUNNER_ID}/assessment")

    login(client, RUNNER_EMAIL)
    log = client.get(f"/api/runners/{RUNNER_ID}/access-log").json()
    mine = [r for r in log if r["physio_id"] == "phy-0001" and r["action"] == "read"]
    assert mine, "expected a physio read to be logged"
    assert mine[0]["access_count"] >= 2
    assert mine[0]["physio_name"]                     # resolved for display

    boot = client.get(f"/api/runners/{RUNNER_ID}/bootstrap").json()
    assert any(r["physio_id"] == "phy-0001" for r in boot["access_log"])


def test_runner_cannot_read_another_runners_access_log(client):
    login(client, RUNNER_EMAIL)  # run-0001
    assert client.get("/api/runners/run-0002/access-log").status_code == 403


def test_runner_own_reads_are_not_logged(client):
    login(client, RUNNER_EMAIL)
    client.get(f"/api/runners/{RUNNER_ID}/bootstrap")
    log = client.get(f"/api/runners/{RUNNER_ID}/access-log").json()
    # the log only ever contains physio access, never the runner's own
    assert all(r["actor_role"] == "physio" for r in log)
