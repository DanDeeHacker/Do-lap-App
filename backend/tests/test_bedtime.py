"""Owner request 2026-10-05: the evening report's bedtime from the trend of sleep onset and
wake times — tomorrow's usual wake time (workday / weekend) minus the sleep target and 15 min
to fall asleep, never more than 30 min earlier than the usual bedtime at a time."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.metrics import daily_report as DR

MON = date(2026, 10, 5)      # a Monday evening: tomorrow is a workday


def _det(onsets, wakes, weekend_wake=None, today=MON, n=14):
    out = {}
    for k in range(n):
        d = today - timedelta(days=k)
        wk = weekend_wake if (weekend_wake and d.weekday() >= 5) else wakes
        out[d.isoformat()] = SimpleNamespace(sleep={"start": onsets, "end": wk})
    return out


def test_bedtime_steps_half_an_hour_earlier_than_a_late_habit():
    det = _det("23:45", "6:15")
    t = DR._tonight(None, det, {}, MON, {"h": 8.0}, False, 0)
    assert t["wake"] == "6:15" and t["ideal"] == "22:00"          # 6:15 − 8 h − 15 min
    assert t["mode"] == "step" and t["bed"] == "23:00"            # usual bed 23:30 − 30 min
    assert t["timing"]["usualOnset"] == "23:45" and t["caffeine"] == "17:00"


def test_an_early_habit_is_kept_and_a_close_one_gets_the_ideal():
    t = DR._tonight(None, _det("21:30", "6:15"), {}, MON, {"h": 8.0}, False, 0)
    assert t["mode"] == "keep" and t["bed"] == "21:15"
    t2 = DR._tonight(None, _det("22:20", "6:15"), {}, MON, {"h": 8.0}, False, 0)
    assert t2["mode"] == "ideal" and t2["bed"] == "22:00"


def test_a_weekend_tomorrow_uses_the_weekend_wake_time():
    sat_eve = date(2026, 10, 10)          # Saturday evening: tomorrow is Sunday
    det = _det("23:00", "6:15", weekend_wake="8:15", today=sat_eve, n=21)
    t = DR._tonight(None, det, {}, sat_eve, {"h": 8.0}, False, 0)
    assert t["timing"]["tomorrowWeekend"] and t["wake"] == "8:15"
    assert DR._tonight(None, det, {}, MON, {"h": 8.0}, False, 0)["wake"] == "6:15"


def test_after_midnight_onsets_and_the_trend():
    det = {}
    for k in range(14):
        d = MON - timedelta(days=k)
        m = 23 * 60 + 40 - k * 5                 # later every night, crossing midnight
        det[d.isoformat()] = SimpleNamespace(sleep={"start": f"{(m // 60) % 24}:{m % 60:02d}", "end": "6:30"})
    tm = DR._sleep_timing(det, MON)
    assert tm["trend"] == 35 and tm["onset"] > 23 * 60   # 5 min a night later = 35 min a week
    assert all(n["onset"] >= 18 * 60 for n in tm["nights"])


def test_without_watch_nights_the_old_rule_stays():
    t = DR._tonight(None, {}, {}, MON, {"h": 8.0}, False, 0)
    assert t["mode"] == "ideal" and t["wake"] == "6:30" and "timing" not in t and not t["wakeFromWatch"]
