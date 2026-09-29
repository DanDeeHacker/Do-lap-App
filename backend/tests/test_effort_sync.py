"""v0.8.6 — readiness after today's session, and the Garmin sync window."""
from datetime import timedelta

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from app.routers import integrations as I

HRMAX, RHR = 190, 50


def _s(day, load, *, run=True, z4=0.0, hr=140, mins=50, rpe=None, sport="running", title="Běh"):
    exp = {"systemic": load}
    if run:
        exp["intensity"] = z4
    return {"date": day, "run": run, "sport": sport, "title": title, "exp": exp, "avgHr": hr,
            "durationMin": mins, "rpe": rpe}


def _history(today, n=30, load=100.0):
    return [_s((today - timedelta(days=k)).isoformat(), load + (k % 5) * 10) for k in range(1, n + 1)]


def test_easy_session_costs_little_and_typical_about_eight_points():
    today = E.today_date()
    t = today.isoformat()
    hist = _history(today)
    easy = C.day_effort(hist + [_s(t, 120, hr=110, rpe=3)], t, HRMAX, RHR)       # 60 min, below the threshold
    assert easy["easy"] and easy["deficit"] <= C.EFFORT_EASY_MAX
    typical = C.day_effort(hist + [_s(t, 120, hr=150)], t, HRMAX, RHR)
    assert not typical["easy"] and 0.08 <= typical["deficit"] <= 0.2
    assert typical["band"] == "obvyklá náročnost"


def test_hard_session_adds_the_threshold_bonus_and_is_capped():
    today = E.today_date()
    t = today.isoformat()
    hist = _history(today)
    hard = C.day_effort(hist + [_s(t, 400, z4=25, hr=165)], t, HRMAX, RHR)
    assert hard["hard"] and hard["band"] == "nejnáročnější za 8 týdnů"
    assert abs(hard["deficit"] - C.EFFORT_CAP) < 1e-9                             # 0.35 + 0.15 → capped at 0.45
    _f, score = C.readiness_from({"session": hard["deficit"]})
    assert score == 64                                                            # at most 36 points off


def test_cross_training_counts_and_too_little_history_does_not():
    today = E.today_date()
    t = today.isoformat()
    ride = _s(t, 150, run=False, sport="cycling", title="Kolo", hr=150, mins=60)
    assert C.day_effort(_history(today) + [ride], t, HRMAX, RHR)["sessions"][0]["sport"] == "cycling"
    assert C.day_effort(_history(today, n=5) + [ride], t, HRMAX, RHR) is None


def test_yesterdays_hard_session_carries_half_until_the_night_data_arrive():
    today = E.today_date()
    y = (today - timedelta(days=1)).isoformat()
    hist = [x for x in _history(today) if x["date"] != y] + [_s(y, 400, z4=25, hr=165)]
    a = C.after_session(hist, today.isoformat(), night_today=False, hrmax=HRMAX, rhr=RHR)
    assert a and a["today"] is None and a["carry"] and abs(a["deficit"] - C.EFFORT_CAP * C.EFFORT_CARRY) < 1e-9
    assert C.after_session(hist, today.isoformat(), night_today=True, hrmax=HRMAX, rhr=RHR) is None


def test_stored_twin_blocks_a_duplicate_under_another_id(client, db_session):
    db_session.add(models.Runner(id="twin-r", name="T"))
    db_session.add(models.Activity(runner_id="twin-r", provider="garmin", external_id="111", started_at="2026-09-20",
                                   sport="running", distance_km=10.0, duration_min=55.0))
    db_session.commit()
    dup = {"started_at": "2026-09-20", "sport": "running", "distance_km": 10.02, "duration_min": 55.5}
    other = {"started_at": "2026-09-20", "sport": "running", "distance_km": 5.0, "duration_min": 28.0}
    assert I._stored_twin(db_session, "twin-r", dup) and not I._stored_twin(db_session, "twin-r", other)


def test_sync_backfills_once_then_looks_back_two_weeks(client, db_session, monkeypatch):
    rid = "sync-r"
    db_session.add(models.Runner(id=rid, name="S"))
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="1", started_at="2026-09-20",
                                   sport="running", distance_km=8.0, duration_min=45.0))
    db_session.commit()
    calls = []

    def fake_seed(garmin, activity_days=180, skip_dates=frozenset(), since_date=None, sleep_backfill_days=0):
        calls.append(since_date)
        return {"activities": [{"provider": "garmin", "external_id": "2", "started_at": "2026-08-01", "sport": "cycling",
                                "title": "Kolo", "duration_min": 60.0, "avg_hr": 130}], "daily_metrics": []}
    monkeypatch.setattr(I.garmin_live, "download_seed", fake_seed)
    out = I._download_and_merge(db_session, rid, garmin=object())
    assert calls[0] is None and out["added_activities"] == 1                     # the one-time full window
    assert (db_session.query(models.Runner).get(rid).onboarding_json or {}).get("crossBackfill")
    I._download_and_merge(db_session, rid, garmin=object())
    assert calls[1] == "2026-09-06"                                              # 14 days before the newest activity
    assert db_session.query(models.Activity).filter(models.Activity.runner_id == rid).count() == 2


def test_czech_and_extra_workout_names_are_recognised():
    import apple_health_ingest as A
    import garmin_live as G
    assert A.cross_sport("Cyklistika v interiéru") == "cycling" and A.cross_sport("Plavání v bazénu") == "swimming"
    assert A.is_run_name("Běh venku") and not A.is_run_name("Chůze")
    assert G._sport_of("e_bike_fitness") == "cycling" and G._sport_of("virtual_ride") == "cycling"
