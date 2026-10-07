"""Owner request 2026-10-06: the room under the weekly ceiling from the absorbed load (the
same load and ceiling as the weekly score), not a plain 7-day sum — a long run fades night
by night instead of counting fully for six days and vanishing on the seventh."""
from datetime import date, timedelta

from app.metrics import capacity as C
from app.metrics import week_plan as WP

T = date(2026, 10, 6)


def _days(n=42, today=T):
    return [(today - timedelta(days=k)).isoformat() for k in range(n - 1, -1, -1)]


def _room(daily, today=T, ceil=50.0, ch="volume"):
    days = _days(today=today)
    rates = {d: C._k(C.HALF_MSK) for d in days}
    return C.absorbed_room(daily, days, rates, ch, today.isoformat(), ceil)


def test_a_long_run_fades_instead_of_dropping_out():
    long_day = T - timedelta(days=10)
    daily = {long_day.isoformat(): 25.0}
    lefts = []
    for k in range(1, 11):
        r = _room(daily, today=long_day + timedelta(days=k))
        lefts.append(r["absorbedLeft"])
        share = r["absorbedPast"] / 25.0
        assert abs(share - (1 - C._k(C.HALF_MSK)) ** k) < 1e-6        # what is left of it that morning
    steps = [b - a for a, b in zip(lefts, lefts[1:])]
    assert all(s > 0 for s in steps)                                    # more room every morning…
    assert max(steps) < 0.25 * 25                                       # …but never the whole run at once
    # the plain 7-day sum: 0 room-change for 6 days, then all 25 km on day 7
    r6 = _room(daily, today=long_day + timedelta(days=6))
    assert 0.25 < r6["absorbedPast"] / 25.0 < 0.35                      # six nights later ≈ 30 % still counts


def test_the_room_adds_up_and_ends_where_the_weekly_score_starts():
    daily = {(T - timedelta(days=k)).isoformat(): 8.0 for k in range(0, 30, 2)}
    daily[T.isoformat()] = 5.0
    r = _room(daily)
    assert abs(r["absorbedMax"] - r["absorbed"] - r["absorbedLeft"]) < 1e-9
    # running exactly the room today puts the weekly residual right at the ceiling
    days = _days()
    rates = {d: C._k(C.HALF_MSK) for d in days}
    full = {**daily, T.isoformat(): 5.0 + r["absorbedLeft"]}
    assert abs(C.residual_week(full, days, rates, "volume") - 50.0) < 1e-6


def test_steady_training_matches_the_plain_week():
    daily = {(T - timedelta(days=k)).isoformat(): 6.0 for k in range(0, 42)}
    days = _days()
    rates = {d: C._k(C.HALF_MSK) for d in days}
    resid = C.residual_week(daily, days, rates, "volume")
    assert abs(resid - 42.0) < 0.5                                      # = 7 × 6 km
    r = _room(daily, ceil=1.15 * resid)
    assert r["absorbedLeft"] > 0 and r["absorbed"] < r["absorbedMax"]


def test_the_week_plan_counts_planned_days_with_their_absorption():
    k = C._k(C.HALF_MSK)
    chw = {"absorbedMax": 40.0, "absorbK": k, "absorbedPast": 10.0}
    planned = {T: 6.0, T + timedelta(days=1): 12.0}
    d = T + timedelta(days=2)
    q = 1 - k
    expect = 40.0 - (10.0 * q ** 2 + 6.0 * q ** 2 + 12.0 * q)
    assert abs(WP._room(d, T, chw, {}, planned) - expect) < 1e-9
    # without the absorbed figures the plain 7-day ceiling still works
    assert WP._room(d, T, {"ceiling7": 40.0}, {}, planned) == 22.0
