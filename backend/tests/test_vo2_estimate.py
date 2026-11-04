"""feedback #226 (engine v0.12.22): the app's own VO2max estimate beside Kondice — Daniels &
Gilbert's equations on the best 6, 10, 15 and 20 minute efforts of the last 90 days, ± 10 %.
An estimate from the runner's runs, never a measurement, and no score depends on it."""
import copy

from app.metrics import engine as E
from app.metrics import fitness as FT
from app.metrics import vo2 as V
from .test_guidance import _runner

DURS = [180, 360, 600, 900, 1200]


def test_the_equations_match_daniels_published_table():
    # Daniels' VDOT table: a 5 km in 20:00 is VDOT 49.8 (v = 250 m/min for 20 min)
    assert round(V.from_effort(250 / 60, 1200), 1) == 49.8
    # and 5 km in 25:00 is 38.3
    assert round(V.from_effort(200 / 60, 1500), 1) == 38.3


def test_the_highest_of_the_four_efforts_is_the_estimate():
    # paces in s/km for 3, 6, 10, 15, 20 min: the 15-minute effort implies the most
    e = V.estimate({"durs": DURS, "now": [215, 225, 230, 235, 240]})
    assert e["basisMin"] == 15 and e["value"] == 50.1 and e["windowDays"] == 90
    assert (e["low"], e["high"]) == (45.1, 55.1)                    # ± 10 %


def test_the_three_minute_best_is_not_used():
    # a very fast 3-minute effort alone gives nothing; with a 6-minute one it does not decide
    assert V.estimate({"durs": [180], "now": [150]}) is None
    base = V.estimate({"durs": [180, 360], "now": [999, 270]})
    fast3 = V.estimate({"durs": [180, 360], "now": [150, 270]})
    assert base == fast3 and base["basisMin"] == 6


def test_no_estimate_without_an_effort_or_from_an_absurd_one():
    assert V.estimate(None) is None
    assert V.estimate({}) is None
    assert V.estimate({"durs": DURS, "now": [None] * 5}) is None
    assert V.estimate({"durs": DURS, "now": [900, 900, 900, 900, 900]}) is None          # a walk: 15:00/km


def test_the_trend_carries_it_and_nothing_else_changes(client, db_session):
    rid, _ = _runner(client, db_session, "vo2a@test.cz", days=120)
    a = E.get_or_refresh_assessment(db_session, rid)
    with_curve = copy.deepcopy(a)
    with_curve["capacity"]["bestCurve"] = {"durs": DURS, "now": [215, 225, 230, 235, 240], "prev": [None] * 5, "csPace": None}
    without = copy.deepcopy(a)
    without["capacity"]["bestCurve"] = None
    t1, t2 = FT.trend(db_session, rid, with_curve), FT.trend(db_session, rid, without)
    assert t1["vo2"]["value"] == 50.1 and t2["vo2"] is None
    assert {k: v for k, v in t1.items() if k != "vo2"} == {k: v for k, v in t2.items() if k != "vo2"}    # Kondice, Únava, Čerstvost untouched
    res = client.get(f"/api/runners/{rid}/fitness-trend").json()
    assert "vo2" in res                                                   # present (value or null) on the endpoint


def test_the_engine_version_names_the_change():
    assert E.ENGINE_VERSION == "v0.12.22"
