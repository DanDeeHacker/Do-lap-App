"""Plan phase 0 (daily snapshot, alerts, health events, owner overview) and
phase 2B (every point ramp continuous and non-decreasing)."""
from datetime import timedelta

import pytest

from app import models, outcomes
from app.metrics import engine as E
from .conftest import register
from .synth import seed_runs


# ---------------------------------------------------------------- phase 2B
RAMPS = [
    ("session spike", E.pts_session_spike, 1.0, 3.5, 1),
    ("acwr high", E.pts_acwr, 1.0, 2.5, 1),
    ("acwr low (falling ratio)", lambda r: E.pts_acwr(1.0 - r), 0.0, 0.6, 1),
    ("hrv low (falling z)", lambda z: E.pts_hrv_low(-z), 0.0, 4.0, 1),
    ("rhr high", E.pts_rhr_high, 0.0, 4.0, 1),
]


@pytest.mark.parametrize("name,f,lo,hi,_", RAMPS)
def test_point_ramps_are_continuous_and_non_decreasing(name, f, lo, hi, _):
    n = 4000
    xs = [lo + (hi - lo) * i / n for i in range(n + 1)]
    ys = [f(x) for x in xs]
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), f"{name} decreases somewhere"
    step = (hi - lo) / n
    # no jumps: on a fine grid the slope stays bounded (Lipschitz), so a tiny input
    # change can never add several points at once (the old v1 cut-points did)
    worst = max((b - a) / step for a, b in zip(ys, ys[1:]))
    assert worst <= 51, f"{name} jumps: slope {worst}"


def test_session_spike_no_longer_drops_past_1_3():
    assert E.pts_session_spike(1.31) > E.pts_session_spike(1.29) > 4.5
    # v0.9.0: RUNSAFE plateau — a +100 % run scores little more than a +40 % one, past 2× it climbs
    assert E.pts_session_spike(2.0) == pytest.approx(0.8 * 14) and E.pts_session_spike(3.0) == pytest.approx(0.8 * 34)
    assert E.pts_session_spike(2.0) - E.pts_session_spike(1.4) < 2


def test_taper_fades_in_with_the_load():
    assert E.taper_weight(10, 1.0) == 0 and E.taper_weight(25, 1.0) == 1
    assert 0 < E.taper_weight(21, 1.0) < 1 and E.taper_weight(0, 1.3) == pytest.approx(1)


# ---------------------------------------------------------------- phase 0
def _runner(client, db, email):
    rid = register(client, email, "Outcome Test", "runner").json()["runner_id"]
    seed_runs(db, rid, days=60)
    return rid


def test_snapshot_is_upserted_and_alert_logged_when_an_axis_turns_hot(client, db_session):
    db = db_session
    rid = _runner(client, db, "out1@test.cz")
    a = E.recompute_assessment(db, rid)
    today = E.today_date()
    with E.today_pinned(today - timedelta(days=1)):
        outcomes.record_snapshot(db, rid, {**a, "quadrant": "stable"})
    outcomes.record_snapshot(db, rid, {**a, "quadrant": "overreaching"})
    outcomes.record_snapshot(db, rid, {**a, "quadrant": "overreaching"})   # idempotent for the day
    snaps = db.query(models.EngineDailySnapshot).filter_by(runner_id=rid).all()
    assert len(snaps) == 2 and any(s.features_json for s in snaps)
    alerts = db.query(models.EngineAlert).filter_by(runner_id=rid).all()
    assert [(x.axis, x.quadrant_to) for x in alerts] == [("load", "overreaching")]

    # the runner answers "does it fit?" once
    client.post("/api/auth/session", json={"email": "out1@test.cz", "password": "testpass123"})
    pend = client.get(f"/api/runners/{rid}/alerts/pending").json()["alert"]
    assert pend and pend["axis"] == "load"
    assert client.post(f"/api/runners/{rid}/alerts/{pend['id']}/feedback", json={"feedback": "no_fit"}).status_code == 200
    assert client.get(f"/api/runners/{rid}/alerts/pending").json()["alert"] is None
    assert client.post(f"/api/runners/{rid}/alerts/{pend['id']}/feedback", json={"feedback": "maybe"}).status_code == 400


def test_health_events_definition(client, db_session):
    db = db_session
    rid = _runner(client, db, "out2@test.cz")
    d = lambda n: (E.today_date() - timedelta(days=n)).isoformat() + "T08:00:00+02:00"   # noqa: E731
    # pain ≥ 3 at one running site twice within 7 days → one event on the second day
    db.add(models.Checkin(runner_id=rid, submitted_at=d(40), pain_score=4, pain_site="Achillova šlacha (P)"))
    db.add(models.Checkin(runner_id=rid, submitted_at=d(36), pain_score=3, pain_site="Achillova šlacha (P)"))
    # mild pain and a non-running site do not count
    db.add(models.Checkin(runner_id=rid, submitted_at=d(30), pain_score=2, pain_site="Achillova šlacha (P)"))
    db.add(models.Checkin(runner_id=rid, submitted_at=d(29), pain_score=5, pain_site="Zápěstí"))
    db.add(models.Checkin(runner_id=rid, submitted_at=d(28), pain_score=5, pain_site="Zápěstí"))
    # an OSTRC answer with reduced volume → an event; one within 14 days merges into the same episode
    db.add(models.InjuryReport(runner_id=rid, submitted_at=d(10), source="self_weekly", status="active",
                               q_volume=8, severity=8, body_region="koleno"))
    db.add(models.InjuryReport(runner_id=rid, submitted_at=d(5), source="self_adhoc", status="active", severity=17))
    db.add(models.InjuryReport(runner_id=rid, submitted_at=d(2), source="self_weekly", status="none"))
    db.commit()
    # v0.9.0: the primary outcome doesn't use the pain reports (they are engine inputs)
    # nor a mild OSTRC limitation — only the ad-hoc injury report counts
    ev = outcomes.health_events(db, rid)
    assert [(e["date"], e["source"]) for e in ev] == [(d(5)[:10], "self_adhoc")]
    # the secondary outcome keeps the old proposal
    ev2 = outcomes.health_events(db, rid, "secondary")
    assert [(e["date"], e["source"]) for e in ev2] == [(d(36)[:10], "pain_repeat"), (d(10)[:10], "ostrc_limit")]


def test_labelled_snapshots_and_owner_overview(client, db_session, monkeypatch):
    db = db_session
    rid = _runner(client, db, "out3@test.cz")
    a = E.recompute_assessment(db, rid)
    today = E.today_date()
    for back in (9, 8, 3):
        with E.today_pinned(today - timedelta(days=back)):
            outcomes.record_snapshot(db, rid, a)
    db.add(models.InjuryReport(runner_id=rid, submitted_at=(today - timedelta(days=4)).isoformat(),
                               source="self_adhoc", status="active", severity=25))
    db.commit()
    rows = {r["date"]: r["event"] for r in outcomes.labelled_snapshots(db, rid)}
    # 9 and 8 days back see the event within 7 days, 3 days back is inside the episode → left out
    assert rows == {(today - timedelta(days=9)).isoformat(): True, (today - timedelta(days=8)).isoformat(): True}

    register(client, "owner@test.cz", "Owner", "runner")
    client.post("/api/auth/session", json={"email": "owner@test.cz", "password": "testpass123"})
    assert client.get("/api/engine/outcomes").status_code == 403
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "owner@test.cz")
    ov = client.get("/api/engine/outcomes").json()
    assert ov["events"] >= 1 and ov["gate"]["events"] == 200 and ov["gate"]["passed"] is False
