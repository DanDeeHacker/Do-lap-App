"""Engine v0.9.0 — the calibration record: primary outcomes independent of the
engine's inputs, censoring, frozen morning snapshots, the session-scale dataset
and the safety rules kept outside the calibrated score."""
from datetime import timedelta

from app import calibration as CAL
from app import models, outcomes
from app.metrics import engine as E
from .conftest import register
from .synth import seed_runs


def _rid(client, db, email, **kw):
    rid = register(client, email, "Cal Test", "runner").json()["runner_id"]
    seed_runs(db, rid, **({"days": 60} | kw))
    return rid


def _iso(n):
    return (E.today_date() - timedelta(days=n)).isoformat()


def test_morning_snapshot_is_frozen_after_a_run(client, db_session):
    db = db_session
    rid = _rid(client, db, "c09a@test.cz", p_run=0.0)          # no runs yet
    a = E.recompute_assessment(db, rid)
    row = outcomes.record_snapshot(db, rid, {**a, "overall": 12})
    assert row.post_session is False
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-today", started_at=E.day_ago(0) + "T07:30:00",
                           sport="running", distance_km=8, duration_min=45, pace_s_km=337, avg_hr=150))
    db.commit()
    again = outcomes.record_snapshot(db, rid, {**a, "overall": 55})
    assert again.overall == 12                                   # the pre-run state is kept


def test_a_first_snapshot_after_the_run_is_marked(client, db_session):
    db = db_session
    rid = _rid(client, db, "c09b@test.cz", p_run=1.0)           # ran today (seed covers day 0)
    row = outcomes.record_snapshot(db, rid, E.recompute_assessment(db, rid))
    assert row.post_session is True
    assert outcomes.record_snapshot(db, rid, E.recompute_assessment(db, rid)).post_session is True   # stays frozen


def test_last_week_is_censored_not_event_free(client, db_session):
    db = db_session
    rid = _rid(client, db, "c09c@test.cz")
    for back in (20, 10, 3):
        db.add(models.EngineDailySnapshot(runner_id=rid, date=_iso(back), overall=10, features_json={}))
    db.commit()
    dates = {r["date"] for r in outcomes.labelled_snapshots(db, rid)}
    assert _iso(20) in dates and _iso(10) in dates and _iso(3) not in dates


def test_time_loss_needs_a_regular_runner_who_kept_syncing(client, db_session):
    db = db_session
    rid = register(client, "c09d@test.cz", "TL", "runner").json()["runner_id"]
    for d in range(60, 12, -1):                                  # daily runs until 13 days ago
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-{d}", started_at=E.day_ago(d),
                               sport="running", distance_km=8, duration_min=45, pace_s_km=337, avg_hr=150))
    for d in range(60, -1, -1):                                  # the watch keeps syncing nights
        db.add(models.DailyMetric(runner_id=rid, date=E.day_ago(d), hrv_ms=60, resting_hr=50, sleep_h=7.5))
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(12) + "T07:00:00", pain_score=4,
                          pain_site="Achillova šlacha (P)", pain_points=[{"region": "Achillova šlacha (P)"}]))
    db.commit()
    ev = outcomes.health_events(db, rid)
    assert [(e["date"], e["source"]) for e in ev] == [(_iso(12), "time_loss")]


def test_no_time_loss_when_the_runner_just_stopped_syncing(client, db_session):
    db = db_session
    rid = register(client, "c09e@test.cz", "TL2", "runner").json()["runner_id"]
    for d in range(60, 12, -1):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-{d}", started_at=E.day_ago(d),
                               sport="running", distance_km=8, duration_min=45, pace_s_km=337, avg_hr=150))
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(12) + "T07:00:00", pain_score=4,
                          pain_site="Achillova šlacha (P)", pain_points=[{"region": "Achillova šlacha (P)"}]))
    db.commit()
    assert outcomes.health_events(db, rid) == []


def test_session_rows_carry_the_runsafe_ratio(client, db_session):
    db = db_session
    rid = register(client, "c09f@test.cz", "Ses", "runner").json()["runner_id"]
    for d, km in ((40, 10), (35, 10), (30, 10), (25, 10), (20, 18), (15, 10)):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-{d}", started_at=E.day_ago(d),
                               sport="running", distance_km=km, duration_min=km * 5.5, pace_s_km=330, avg_hr=150))
    db.add(models.InjuryReport(runner_id=rid, submitted_at=E.day_ago(17), source="self_adhoc", status="active", severity=25))
    db.commit()
    rows = {r["date"]: r for r in outcomes.session_rows(db, rid)}
    assert _iso(40) not in rows                                   # no 30-day reference yet
    assert rows[_iso(20)]["session_ratio"] == 1.8 and rows[_iso(20)]["event"] is True
    assert rows[_iso(25)]["event"] is False and rows[_iso(25)]["interval_days"] == 5
    assert _iso(15) not in rows                                   # inside the episode


def test_safety_rules_floor_the_display_but_not_the_model(client, db_session):
    db = db_session
    rid = _rid(client, db, "c09g@test.cz")
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(0) + "T07:00:00", pain_score=3,
                          pain_points=[{"region": "SI kloub / bederní úpony"}], flags={"red_cauda": True}))
    db.commit()
    a = E.recompute_assessment(db, rid)
    rf = next(s for s in a["signals"] if s["id"] == "red_flag")
    assert rf["rule"] == "alert" and rf["impact"] is None
    assert a["tier"] == "alert" and a["overall"] >= 70 and a["symp"] >= 70
    assert a["overallModel"] < 70 and a["sympModel"] < a["symp"]
    snap = outcomes.record_snapshot(db, rid, a)
    assert snap.features_json["overall_model"] == a["overallModel"]
