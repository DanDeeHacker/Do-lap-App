"""The sensitivity sandbox must not drift from the real engine. For every seeded
runner we take the live assessment, map it onto the sandbox knobs, re-score with
simulate(), and assert the LOAD and MECHANICS axes (the two that determine the
quadrant) come out identical — per-load-signal and per-axis total. If someone
changes a threshold/weight in engine.assess() but not in sensitivity.simulate()
(or vice-versa), this fails.
"""
import pytest

from app import models
from app.metrics import engine as E
from app.metrics import sensitivity as S
from .conftest import DEMO_PASSWORD, login

# Every seeded runner login (adela + the two demo-account runners). The two
# demo-only accounts use password "demo"; adela uses the standard demo password.
RUNNERS = [("adela@demo.cz", DEMO_PASSWORD), ("tichydrift@demo.cz", "demo"), ("kritickepretizeni@demo.cz", "demo")]


def _runner_ids(db):
    return [u.runner_id for u in db.query(models.User).filter(models.User.role == "runner").all() if u.runner_id]


def test_knobs_defaults_score_to_stable(client):
    login(client, RUNNERS[0][0], RUNNERS[0][1])
    r = client.get("/api/engine/knobs")
    assert r.status_code == 200
    spec = r.json()
    assert spec["knobs"] and spec["defaults"] and spec["thresholds"]["quadHi"] == E.QUAD_THRESHOLD
    # Neutral defaults → every axis zero, quadrant stable.
    res = S.simulate(spec["defaults"])
    assert res["mech"] == 0 and res["load"] == 0 and res["symp"] == 0
    assert res["quadrant"] == "stable"


def test_simulate_matches_live_engine_load_and_mech(client, db_session):
    rids = _runner_ids(db_session)
    assert rids, "expected seeded runners"
    checked = 0
    for rid in rids:
        runner = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
        with E.engine_pinned((runner.engine_mode if runner else None) or "v1"):
            a = E.assess(db_session, rid)
        inp = S.inputs_from_assessment(a, runner)
        res = S.simulate(inp, prev_quadrant=None)

        # Per-signal parity on the load axis (all load pushes are unconditional
        # when fired, so ids + points must match one-for-one).
        live_load = {s["id"]: s["pts"] for s in a["signals"] if s["id"] in S._LOAD_SIGNAL_IDS}
        sim_load = {s["id"]: s["pts"] for s in res["signals"] if s["axis"] == "load"}
        assert sim_load == live_load, f"{rid}: load signals differ\nlive={live_load}\nsim={sim_load}"

        # Axis totals (post-frailty, clamped) must match for both quadrant axes.
        assert res["load"] == a["load"], f"{rid}: load total {res['load']} != {a['load']}"
        assert res["mech"] == a["mech"], f"{rid}: mech total {res['mech']} != {a['mech']}"
        checked += 1
    assert checked >= 1


def test_sweep_shows_metric_influence(client):
    login(client, RUNNERS[0][0], RUNNERS[0][1])
    body = {"inputs": S.DEFAULTS, "knob": "sessionSpike", "points": 21}
    r = client.post("/api/engine/sweep", json=body)
    assert r.status_code == 200
    sw = r.json()
    assert sw["knob"] == "sessionSpike" and len(sw["series"]) == 21 and sw["threshold"] == 1.1
    loads = [p["load"] for p in sw["series"]]
    # From the neutral default (no spike) the metric clearly drives the load axis
    # up over its range. (Not asserted monotone: the engine's spike bands step
    # down at ×1.3 — a real discontinuity the sweep chart is meant to surface.)
    assert loads[0] == 0 and max(loads) > 20 and loads[-1] > loads[10]


def test_simulate_quadrant_states():
    # Neutral → stable.
    assert S.simulate(S.DEFAULTS)["quadrant"] == "stable"
    # Load-only elevation → overreaching (no single knob crosses 25 alone; it
    # takes a combination — itself a useful property the tool makes visible).
    load_heavy = {**S.DEFAULTS, "sessionSpike": 2.6, "hrvZ": -1.5, "rhrZ": 1.5, "sleepDebt": 5, "monotony": 3.0}
    r = S.simulate(load_heavy)
    assert r["load"] >= 25 and r["mech"] < 25 and r["quadrant"] == "overreaching"
    # Mechanics-only elevation → silent drift.
    mech_heavy = {**S.DEFAULTS, "tavrZ": 2.0, "gctZ": 2.0}
    r = S.simulate(mech_heavy)
    assert r["mech"] >= 25 and r["load"] < 25 and r["quadrant"] == "silent"
    # Both → critical.
    r = S.simulate({**load_heavy, **{"tavrZ": 2.0, "gctZ": 2.0}})
    assert r["quadrant"] == "critical"


@pytest.mark.parametrize("email,password", RUNNERS)
def test_inputs_endpoint_seeds_from_runner(client, email, password):
    r = login(client, email, password)
    rid = r.json()["runner_id"]
    got = client.get(f"/api/engine/inputs/{rid}")
    assert got.status_code == 200
    payload = got.json()
    assert set(payload["inputs"]) >= set(S.DEFAULTS)
    # Seeding then simulating reproduces the runner's live load/mech axes.
    res = client.post("/api/engine/simulate", json={"inputs": payload["inputs"]}).json()
    live = client.get(f"/api/runners/{rid}/assessment").json()
    assert res["load"] == live["load"] and res["mech"] == live["mech"]
