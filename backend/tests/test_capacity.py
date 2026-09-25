"""Engine v3 — per-runner load capacity model (metrics/capacity.py)."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from app.metrics import stream_qc as S
from .conftest import register
from .synth import seed_runs


def _day(n):
    return (E.today_date() - timedelta(days=n)).isoformat()


def _sess(n, **exp):
    return {"date": _day(n), "run": True, "title": "Běh", "km": exp.get("volume"), "exp": exp,
            "avgHr": None, "speed": None, "ascPerKm": 0}


def test_band_points_and_combination():
    assert C.band_points(1.10, 0.10) == 0
    assert C.band_points(1.30, 0.10) == pytest.approx(6)
    assert C.band_points(2.00, 0.10) == pytest.approx(20)
    assert C.band_points(3.00, 0.10) == pytest.approx(40)
    assert C.band_points(1.25, 0.15) == pytest.approx(4)       # weekly margin: +15 % free
    # the worst channel counts fully, the 2nd half, the rest a quarter
    assert C.combine({"volume": 20, "descent": 10, "ascent": 4}) == {"volume": 20, "descent": 5, "ascent": 1}


def test_session_capacity_is_recent_demonstrated_max():
    ses = [_sess(40, volume=30.0), _sess(20, volume=18.0), _sess(10, volume=12.0), _sess(5, volume=10.0)]
    items = C.channel_items(ses, "volume", set())
    cap = C.session_capacity(items, _day(0), "volume")
    # 30 km 40 days ago decays (half-life 30 d beyond day 30) to ~23.8 > 18
    assert cap == pytest.approx(30 * 0.5 ** (10 / 30), rel=1e-3)
    # too few runs in the last 30 days → unknown, not scored
    assert C.session_capacity(C.channel_items(ses[:2], "volume", set()), _day(0), "volume") is None


def test_runs_followed_by_pain_are_not_proven_capacity():
    ses = [_sess(20, volume=22.0), _sess(12, volume=12.0), _sess(8, volume=11.0), _sess(4, volume=10.0)]
    assert C.session_capacity(C.channel_items(ses, "volume", set()), _day(0), "volume") == 22.0
    pain = {_day(18)}                                     # pain 2 days after the 22 km run
    assert C.session_capacity(C.channel_items(ses, "volume", pain), _day(0), "volume") == 12.0


def test_weekly_capacity_average_or_best_week():
    daily = {_day(k): 6.0 for k in range(7, 35)}           # steady ~42 km weeks
    for k in range(14, 21):
        daily[_day(k)] = 9.0                                # one 63 km week 2–3 weeks ago
    cap = C.weekly_capacity(daily, _day(0), _day(60), set(), "volume")
    assert cap == pytest.approx(0.9 * 63.0)
    assert C.weekly_capacity(daily, _day(0), _day(20), set(), "volume") is None   # < 4 weeks of history


def test_z4_minutes_from_histogram_and_from_average():
    a = SimpleNamespace(duration_min=40, hr_thirds=None, avg_hr=None)
    hist = {"170": 600.0, "150": 1800.0}                    # 10 min at 170-171, 30 min at 150
    # HRmax 190, rest 50 → Z4 from 162 bpm
    assert C.z4_minutes(a, hist, 190, 50) == pytest.approx(10.0)
    easy = C.z4_minutes(SimpleNamespace(duration_min=40, hr_thirds=None, avg_hr=140), None, 190, 50)
    tempo = C.z4_minutes(SimpleNamespace(duration_min=40, hr_thirds=None, avg_hr=160), None, 190, 50)
    assert easy < 1 and 10 < tempo < 30                     # just under Z4 on average still counts hard minutes


def test_stream_records_hr_histogram():
    keys = ["sumElapsedDuration", "sumDistance", "directSpeed", "directGroundContactTime", "directHeartRate"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    rows = [{"metrics": [float(t), t * 3.0, 3.0, 240.0, 150.0 if t < 600 else 171.0]} for t in range(900)]
    q = S.process({"metricDescriptors": descs, "activityDetailMetrics": rows})["quality"]
    assert q["hrHist"]["150"] == pytest.approx(600, abs=2) and q["hrHist"]["170"] == pytest.approx(300, abs=2)


def test_relative_effort_bands_and_hr_at_pace():
    import random
    rng = random.Random(4)
    ses = []
    for k in range(56, 7, -2):                               # 8 weeks of easy runs, HR follows speed
        sp = rng.uniform(2.7, 3.2)
        ses.append({"date": _day(k), "run": True, "title": "Lehký", "km": 10.0,
                    "exp": {"systemic": 100 + rng.gauss(0, 10)}, "avgHr": 60 + 30 * sp + rng.gauss(0, 1.5),
                    "speed": sp, "ascPerKm": 5})
    ses.append({"date": _day(1), "run": True, "title": "Těžký", "km": 16.0, "exp": {"systemic": 210.0},
                "avgHr": 60 + 30 * 3.0 + 9, "speed": 3.0, "ascPerKm": 5})
    re = C.relative_effort(ses, _day(0))
    last = re["runs"][0]
    assert last["band"] == "výrazně nad" and last["pct"] == 100
    assert 6 <= last["hrDelta"] <= 12                       # +9 bpm at the usual pace
    assert re["week"] is not None and re["week"]["band"] in ("pod", "obvyklé", "nad")


def test_v3_engine_scores_a_volume_jump(client, db_session):
    rid = register(client, "cap3@test.cz", "Cap Three", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid, days=100)
    r = client.post(f"/api/runners/{rid}/engine", json={"mode": "v3"})
    assert r.status_code == 200 and r.json()["engine_mode"] == "v3"
    a = client.get(f"/api/runners/{rid}/assessment").json()
    assert a["engineMode"] == "v3" and a["engine"].endswith("-c")
    cap = a["capacity"]
    assert cap["channels"]["volume"]["ceilingToday"] is not None
    calm = a["load"]
    # a 24 km run today on a runner whose runs are all 10 km → a clear volume jump
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id="jump", started_at=E.day_ago(0),
                           sport="running", title="Dlouhý", distance_km=24.0, duration_min=24 * 6,
                           avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    db.commit()
    a2 = E.recompute_assessment(db, rid)
    vol = a2["capacity"]["channels"]["volume"]
    # (a long run is often an intensity jump too — then volume is the 2nd channel and
    # counts half in the combined score, so check its own raw points and the total)
    assert vol["session"]["ratio"] > 2.0 and vol["raw"] >= 20 and a2["capacity"]["score"] >= 20
    assert any(s["id"] == "cap_volume" for s in a2["signals"]) and a2["load"] > calm
    # v3 keeps the sensitive (v2) mechanics
    assert a2["mechFlag"] in (True, False) and "segmentScored" in a2


def test_poor_readiness_turns_a_normal_run_into_an_exceedance(client, db_session):
    """The same 10 km run scores nothing after a normal night, but counts as an
    exceedance after a night with crashed HRV / high resting HR / short sleep."""
    rid = register(client, "cap3r@test.cz", "Cap Ready", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid, days=100)
    for k in range(1, 60):
        db.add(models.DailyMetric(runner_id=rid, date=_day(k), sleep_h=7.5 + (k % 3) * 0.2,
                                  hrv_ms=60 + (k % 5), resting_hr=50 + (k % 3)))
    db.add(models.DailyMetric(runner_id=rid, date=_day(0), sleep_h=4.5, hrv_ms=35, resting_hr=62))
    db.commit()
    ready = C.readiness_by_day(db, rid, [_day(0), _day(1)])
    assert ready[_day(0)][0] <= 0.75 < ready[_day(1)][0]
    with E.engine_pinned("v3"):
        a = E.assess(db, rid)
    assert a["capacity"]["readiness"]["today"] <= 0.75
    # today's ceiling is scaled down by readiness
    vol = a["capacity"]["channels"]["volume"]
    assert vol["ceilingToday"] < vol["capSession"] * 1.1 * 0.8


def test_intensity_capacity_is_not_one_outlier_run():
    items = [(E.day_ago(k), v, True) for k, v in ((20, 90.0), (15, 20.0), (10, 18.0), (5, 16.0))]
    items.sort(key=lambda t: t[0])
    assert C.session_capacity(items, E.day_ago(0), "intensity") == pytest.approx((90 + 20 + 18) / 3)
    assert C.session_capacity(items, E.day_ago(0), "volume") == 90.0     # volume keeps the demonstrated max


def test_zone_minutes_add_up_to_the_z4_minutes():
    from types import SimpleNamespace
    a = SimpleNamespace(duration_min=60, hr_thirds=None, avg_hr=160)
    z = C.zone_minutes(a, None, 190, 50)
    assert sum(z) == pytest.approx(60, abs=2)
    assert z[3] + z[4] == pytest.approx(C.z4_minutes(a, None, 190, 50), abs=1e-6)
    hist = {"130": 600, "150": 1200, "168": 600}               # bpm → seconds
    zh = C.zone_minutes(a, hist, 190, 50)
    assert zh[3] + zh[4] == pytest.approx(C.z4_minutes(a, hist, 190, 50))


def test_readiness_follows_a_strained_hrv_week_even_after_good_sleep(client, db_session):
    db = db_session

    def seed(email, week_hrv, today_hrv, week_rhr):
        rid = register(client, email, "Ready", "runner").json()["runner_id"]
        for k in range(0, 36):
            normal = k >= 8
            hrv = (56 if k % 2 else 64) if normal else (today_hrv if k == 0 else week_hrv(k))
            db.add(models.DailyMetric(runner_id=rid, date=E.day_ago(k), hrv_ms=hrv,
                                      resting_hr=(49 if k % 2 else 51) if normal else week_rhr,
                                      sleep_h=7.5 if normal else 7.8))       # slept well all week
        db.commit()
        return C.readiness_by_day(db, rid, [E.day_ago(0)])[E.day_ago(0)]
    f_str, parts, strained = seed("rd1@test.cz", lambda k: 55, 55, 51)        # 7-day HRV ≈ 1.2 SD low, RHR up
    f_one, _, one_night = seed("rd2@test.cz", lambda k: 56 if k % 2 else 64, 55, 50)  # a normal week, one poor night
    assert strained <= 60 and parts["hrv"] > 0.35 and parts.get("sleep", 0) == 0  # good sleep doesn't rescue it
    assert strained < one_night < 100 and 65 <= one_night <= 85                    # the trend weighs more than one night
    assert f_str < f_one and 0.7 <= f_str                                           # capacity factor keeps its 0.7 floor


def test_how_far_off_hrv_and_resting_hr_must_be_to_drop_readiness():
    base = {"hrv_ms": (60.0, 5.0), "resting_hr": (50.0, 2.0), "sleep_h": (7.5, 0.4)}
    score = lambda hrv_sd, rhr_sd: C.readiness_from(C.readiness_parts(
        {"hrv_ms": 60 - hrv_sd * 5, "resting_hr": 50 + rhr_sd * 2, "sleep_h": 7.5}, {}, base))[1]
    assert score(0.4, 0.4) == 100                       # ordinary noise costs nothing
    assert score(1.0, 1.0) > 70 > score(1.2, 1.2)       # both ~1.1 SD off → ~70 %
    assert score(1.45, 0) == 70 and score(1.6, 0) < 70  # HRV alone needs ~1.45 SD
    assert score(1.75, 1.75) == 40                      # both 1.75 SD off → 40 %
    assert score(3, 3) == 20                            # the floor
    wk = C.readiness_from(C.readiness_parts({"hrv_ms": 60, "resting_hr": 50}, {"hrv_ms": 60 - 0.8 * 5}, base))[1]
    assert wk < 90                                      # a 7-night HRV mean 0.8 SD low already costs
