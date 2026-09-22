"""Switchable mechanics engine: v1 standard vs v2 sensitive, per-runner toggle."""
from app.metrics import engine as E
from .conftest import register


def test_robust_helpers():
    assert E.median([1, 2, 3]) == 2
    assert E.median([1, 2, 3, 4]) == 2.5
    # MAD-based SD is far less inflated by a single outlier than plain SD.
    xs = [10, 10, 10, 10, 40]
    assert E.mad_sd(xs) < E.sd(xs)
    assert E.engine_version_for("v1") == E.ENGINE_VERSION
    assert E.engine_version_for("v2").endswith("-s")


def test_engine_toggle_recomputes(client):
    rid = register(client, "engtog@test.cz", "Eng Toggle", "runner").json()["runner_id"]

    r = client.post(f"/api/runners/{rid}/engine", json={"mode": "v2"})
    assert r.status_code == 200 and r.json()["engine_mode"] == "v2"
    a = client.get(f"/api/runners/{rid}/assessment").json()
    assert a["engineMode"] == "v2" and a["engine"].endswith("-s")

    r2 = client.post(f"/api/runners/{rid}/engine", json={"mode": "v1"})
    assert r2.json()["engine_mode"] == "v1"
    a2 = client.get(f"/api/runners/{rid}/assessment").json()
    assert a2["engineMode"] == "v1" and not a2["engine"].endswith("-s")


def test_engine_bad_mode_defaults_v1(client):
    rid = register(client, "engbad@test.cz", "Eng Bad", "runner").json()["runner_id"]
    r = client.post(f"/api/runners/{rid}/engine", json={"mode": "nonsense"})
    assert r.status_code == 200 and r.json()["engine_mode"] == "v1"


def test_engine_toggle_requires_self(client):
    register(client, "engphys@test.cz", "Eng Phys", "physio", "testpass123")
    r = client.post("/api/runners/run-0001/engine", json={"mode": "v2"})
    assert r.status_code in (403, 404)
