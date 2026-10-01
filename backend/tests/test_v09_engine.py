"""Engine v0.9.0 — behaviours reproduced in the 2026-09 engine evaluation.

A runner who trains the same way every week must not score as "over capacity",
"pace spike" or "monotony" just for that routine, while a genuine first-time jump
still does. All runners here are synthetic and live only in the test database.
"""
import random
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import models
from app.metrics import capacity as C
from app.metrics import data as D
from app.metrics import engine as E


def _runner(db, rid, **kw):
    db.add(models.Runner(id=rid, name=rid, engine_mode="v3", birth_year=1990, **kw))
    db.commit()


def _run(db, rid, d, km, pace, hr, n, title="Běh", **kw):
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-{n}", started_at=E.day_ago(d),
                           sport="running", title=title, distance_km=km, duration_min=pace * km / 60,
                           pace_s_km=pace, avg_hr=hr, surface="road", ascent_m=30, descent_m=30, **kw))


def _nights(db, rid, days, seed=7):
    rng = random.Random(seed)
    for d in range(days, -1, -1):
        db.add(models.DailyMetric(runner_id=rid, date=E.day_ago(d), hrv_ms=60 + rng.gauss(0, 1.0),
                                  resting_hr=50 + rng.gauss(0, 0.5), sleep_h=7.6 + rng.gauss(0, 0.2)))


def _weekday(d):
    return (E.today_date() - timedelta(days=d)).weekday()


def _routine(db, rid, weeks=16):
    """3 easy 8 km runs + 1 identical 8 km tempo run every week, no check-ins."""
    n = 0
    for d in range(7 * weeks, -1, -1):
        if _weekday(d) in (0, 2, 5):
            _run(db, rid, d, 8, 340, 140, n)
            n += 1
        elif _weekday(d) == 3:
            _run(db, rid, d, 8, 290, 165, n)
            n += 1
    _nights(db, rid, 7 * weeks)
    db.commit()
    return n


def _assess(db, rid):
    with E.engine_pinned("v3"):
        return E.assess(db, rid)


def test_weekly_tempo_is_tolerated_without_checkins(client, db_session):
    _runner(db_session, "v09-routine")
    _routine(db_session, "v09-routine")
    a = _assess(db_session, "v09-routine")
    ch = a["capacity"]["channels"]["intensity"]
    assert ch["pendingJump"] is None                     # the habit is no longer a "jump" every week
    assert (ch.get("pts") or 0) == 0
    assert not [s for s in a["signals"] if s["id"] in ("pace_spike", "mono")]
    assert a["load"] < 10


def test_first_big_session_is_still_a_jump(client, db_session):
    rid = "v09-jump"
    _runner(db_session, rid)
    n = _routine(db_session, rid)
    _run(db_session, rid, 1, 20, 345, 142, n + 1, title="Dlouhý")       # 2.5× the longest run
    db_session.commit()
    a = _assess(db_session, rid)
    vol = a["capacity"]["channels"]["volume"]
    assert vol["pendingJump"] is not None and vol["pts"] > 0


def test_repeat_confirms_a_jump():
    day = lambda n: (E.today_date() - timedelta(days=n)).isoformat()   # noqa: E731
    ses = [{"date": day(k), "run": True, "exp": {"volume": 8.0}} for k in (60, 55, 50, 45, 40)]
    ses += [{"date": day(30), "run": True, "exp": {"volume": 16.0}},     # the jump
            {"date": day(25), "run": True, "exp": {"volume": 15.0}}]     # a similar run 5 days later
    items = C.channel_items(ses, "volume", set())
    jump = next(it for it in items if it[0] == day(30))
    assert jump[3] is True and jump[4] is True                          # flagged, then confirmed by the repeat
    assert next(it for it in items if it[0] == day(25))[3] is False     # the repeat itself is no jump


def test_pace_spike_compares_with_own_fast_runs(client, db_session):
    rid = "v09-pace"
    _runner(db_session, rid)
    n = _routine(db_session, rid)
    assert D.of(db_session, rid) and E.load(db_session, rid)["paceSpike"] is None
    _run(db_session, rid, 1, 6, 255, 172, n + 1)                        # 4:15/km, well past the usual 4:50 tempo
    db_session.commit()
    L = E.load(db_session, rid)
    assert L["paceSpike"] and L["paceSpike"] > 1.1
    # a race doesn't count as a pace spike (it has its own recovery rule)
    db_session.query(models.Activity).filter(models.Activity.external_id == f"{rid}-{n + 1}").update({"title": "Závod 10k"})
    db_session.commit()
    assert E.load(db_session, rid)["paceSpike"] is None


def test_daily_running_is_not_monotony(client, db_session):
    rid = "v09-daily"
    _runner(db_session, rid)
    for d in range(112, -1, -1):
        _run(db_session, rid, d, 8, 340, 140, d)
    _nights(db_session, rid, 112)
    db_session.commit()
    a = _assess(db_session, rid)
    assert a["loadDetail"]["monotony"] > 2.4
    assert not [s for s in a["signals"] if s["id"] == "mono"]


# ---------------------------------------------------------------- Priority 2: risk factors
def test_injury_history_keeps_a_residual_effect_to_24_months():
    assert E.frailty_of(None) == 1.0 and E.frailty_of(0) == pytest.approx(1.20)
    assert E.frailty_of(12) == pytest.approx(1.06)
    assert E.frailty_of(18) == pytest.approx(1.04) and E.frailty_of(24) == pytest.approx(1.02)
    assert E.frailty_of(25) == 1.0
    fs = [E.frailty_of(m) for m in range(0, 30)]
    assert all(b <= a for a, b in zip(fs, fs[1:]))              # fades, never rises


def test_trimp_uses_the_womens_coefficient():
    men = E._trimp(60, 160, 190, 50, E.trimp_b(SimpleNamespace(sex="m")))
    women = E._trimp(60, 160, 190, 50, E.trimp_b(SimpleNamespace(sex="f")))
    assert women < men and E.trimp_b(SimpleNamespace(sex=None)) == E.TRIMP_B_DEFAULT


def test_underconditioning_needs_four_weeks_and_low_frequency():
    today = E.today_date()
    day = lambda n: (today - timedelta(days=n)).isoformat()     # noqa: E731
    rare = [{"date": day(k), "run": True, "durationMin": 40} for k in range(0, 56, 7)]
    assert C.underconditioning(rare, today, day(55)) is not None          # 1 run a week
    assert C.underconditioning(rare, today, day(20)) is None              # not 4 weeks of data yet
    often = [{"date": day(k), "run": True, "durationMin": 45} for k in range(0, 56, 2)]
    assert C.underconditioning(often, today, day(55)) is None             # 3.5 runs, ~160 min a week


def _checkin_pain(db, rid, region, pain, days_ago):
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(days_ago) + "T07:00:00", pain_score=pain,
                          pain_site=region, pain_points=[{"region": region}]))


def test_bone_pain_rule_starts_lower_for_women(client, db_session):
    for rid, sex in (("v09-bone-f", "f"), ("v09-bone-m", "m")):
        _runner(db_session, rid, sex=sex)
        _checkin_pain(db_session, rid, "Tibialis anterior (holeň) (L)", 2, 0)
    db_session.commit()
    assert E.screening(db_session, "v09-bone-f")["bonePain"] is not None
    assert E.screening(db_session, "v09-bone-m")["bonePain"] is None


def test_achilles_recurs_sooner_for_men(client, db_session):
    for rid, sex in (("v09-ach-m", "m"), ("v09-ach-f", "f")):
        _runner(db_session, rid, sex=sex)
        for d in (2, 9):
            _checkin_pain(db_session, rid, "Achillova šlacha (P)", 2, d)
    db_session.commit()
    assert E.recurring_pain(db_session, "v09-ach-m")["days"] == 2
    assert E.recurring_pain(db_session, "v09-ach-f") is None


# ---------------------------------------------------------------- Priority 4: intensity
def test_zones_follow_a_measured_threshold_heart_rate():
    hrr = C.hr_zones(190, 50)
    lthr = C.hr_zones(190, 50, 170)
    assert [z["z"] for z in lthr] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    assert lthr[3]["lo"] == round(170 * 0.95) and lthr[4]["lo"] == 170 and lthr[4]["hi"] == 190
    assert hrr[3]["lo"] == round(50 + 0.8 * 140)
    assert C.hr_zones(190, 50, 250) == hrr                      # implausible LTHR → HRR zones


def test_intervals_count_their_hard_minutes_by_pace():
    # 6 × 3 min fast on the flat, recoveries and a downhill stretch in between
    fast, easy = {"meanSpeed": 4.6, "meanGradient": 0.0, "durationS": 180}, {"meanSpeed": 2.9, "meanGradient": 0.0, "durationS": 120}
    down = {"meanSpeed": 4.8, "meanGradient": -0.06, "durationS": 300}
    segs = [fast, easy] * 6 + [down]
    assert C.pace_z4_minutes(segs, 4.2) == 18.0                  # the downhill is fast, not hard
    uphill = {"meanSpeed": 3.3, "meanGradient": 0.08, "durationS": 240}
    assert C.pace_z4_minutes([uphill], 4.2) == 4.0              # slower uphill, but harder than 4.2 m/s flat


def test_every_engine_carries_readiness(client, db_session):
    rid = "v09-ready-v1"
    db_session.add(models.Runner(id=rid, name=rid, engine_mode="v1", birth_year=1990))
    _nights(db_session, rid, 60)
    db_session.commit()
    with E.engine_pinned("v1"):
        a = E.assess(db_session, rid)
    rd = a["readiness"]
    assert a["capacity"] is None and rd["score"] >= 20 and rd["label"]
    assert rd["inputs"]["range"]["hrv"] and len(rd["inputs"]["nights"]) == 7
    assert rd["yesterday"]["known"] is True
    rid2 = "v09-ready-none"
    db_session.add(models.Runner(id=rid2, name=rid2, engine_mode="v1", birth_year=1990))
    db_session.commit()
    with E.engine_pinned("v1"):
        assert E.assess(db_session, rid2)["readiness"] is None       # no watch data: "—", not 100 %


def test_a_weekly_session_is_not_over_capacity_on_its_own_day(client, db_session):
    """v0.10.1 — the routine runner (3 easy runs + 1 tempo a week) on every weekday,
    the tempo day included: the weekly score compares like with like."""
    from datetime import date
    for k in range(7):
        day = date(2026, 9, 28) + timedelta(days=k)
        with E.today_pinned(day):
            rid = f"v09-wd-{k}"
            _runner(db_session, rid)
            _routine(db_session, rid)
            a = _assess(db_session, rid)
        ch = a["capacity"]["channels"]["intensity"]
        ex = ch["exact"]
        assert ex["rw"] < 1 + C.MARGIN_WEEK and ch.get("driver") != "week", (day.strftime("%a"), ex, ch.get("week"))
        assert (ch.get("pts") or 0) <= 1                                 # at most a faint latent echo, never the week
        assert ch["week"]["capPeak"] is not None


def test_a_real_rise_over_the_weekly_habit_still_scores(client, db_session):
    """Doubling the weekly hard work (a second tempo, a longer one) is still over capacity."""
    rid = "v09-wd-rise"
    _runner(db_session, rid)
    n = _routine(db_session, rid)
    _run(db_session, rid, 1, 14, 290, 168, n + 1)                  # a 14 km tempo the day before the usual one
    _run(db_session, rid, 0, 12, 290, 168, n + 2)
    db_session.commit()
    a = _assess(db_session, rid)
    ch = a["capacity"]["channels"]["intensity"]
    assert ch["exact"]["rw"] > 1.3 and (ch.get("pts") or 0) > 0


def test_peak_capacity_equals_the_plain_one_on_steady_training():
    from datetime import date
    days = [(date(2026, 6, 1) + timedelta(days=k)).isoformat() for k in range(120)]
    daily = {d: 10.0 for d in days}
    ref = days[-1]
    plain = C.weekly_capacity(daily, ref, days[0], set(), "volume")
    peak = C.weekly_capacity_residual(daily, ref, days[0], set(), "volume")
    assert abs(peak - plain) / plain < 0.02
