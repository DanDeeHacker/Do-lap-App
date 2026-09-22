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


def _mk(days_ago, val, field="vert_ratio_pct"):
    from types import SimpleNamespace
    return SimpleNamespace(
        started_at=E.day_ago(days_ago), distance_km=10.0, ascent_m=20, descent_m=20,
        duration_min=55, surface="road", pace_s_km=330, cadence_spm=170,
        **{field: val},
    )


def test_v2_ewma_damps_single_spike_but_accumulates_drift():
    """Core Phase-2 property: a persistent gradual drift builds up in the EWMA,
    while a single one-off spike is damped — so v2 catches slow change without
    over-reacting to one odd run."""
    base = [_mk(d, 100.0) for d in range(84, 29, -8)]  # ~7 flat baseline runs
    persistent = base + [_mk(12, 104), _mk(9, 105), _mk(6, 106), _mk(3, 107)]
    spike = base + [_mk(12, 100), _mk(9, 100), _mk(6, 100), _mk(3, 112)]
    with E.engine_pinned("v2"):
        zp = E._drift_z_core(persistent, "vert_ratio_pct", 28)["z"]
        zs = E._drift_z_core(spike, "vert_ratio_pct", 28)["z"]
    assert zp > 2.0                 # sustained drift shows up strongly
    assert zs < zp / 2             # a single spike is damped well below it


def test_v2_persistence_flag_fields_present():
    with E.engine_pinned("v2"):
        r = E._drift_z_core([_mk(d, 100.0) for d in range(84, 29, -8)]
                            + [_mk(9, 106), _mk(6, 107), _mk(3, 108)], "vert_ratio_pct", 28)
    assert {"ewma", "ctrl", "state", "persist", "beyond"} <= set(r)
    assert r["persist"] is True and r["state"] in ("possible", "clear")


def test_backtest_xlsx_download(client):
    rid = register(client, "bt@test.cz", "BT Runner", "runner").json()["runner_id"]
    r = client.get(f"/api/runners/{rid}/backtest.xlsx")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers.get("content-type", "")
    assert r.content[:2] == b"PK"        # valid xlsx (zip) even with little data
    assert "attachment" in r.headers.get("content-disposition", "")
