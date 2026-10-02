"""Owner feedback 2026-10-02 (#154–#161)."""
from app import models
from app.metrics import engine as E
from app.metrics import guidance as G
from .test_guidance import _guide, _runner


def _run_today(db, rid, km, hr=145, ext="today"):
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id=ext, started_at=E.day_ago(0),
                           sport="running", title="Ranní běh", distance_km=km, duration_min=km * 6,
                           avg_hr=hr, surface="road", ascent_m=10, descent_m=10))
    db.commit()


def test_a_run_that_covers_today_closes_the_running_day(client, db_session):
    rid, r = _runner(client, db_session, "fb1002a@test.cz")
    g0 = _guide(db_session, rid, r)
    assert g0["afterDone"] is None
    lo = g0["types"]["lehký"]["km"]["lo"]
    _run_today(db_session, rid, max(lo, 6))
    g = _guide(db_session, rid, r)
    assert g["type"] == "volno" and g["afterDone"]["type"] == "volno"
    assert g["reasons"][0].startswith("Dnes už máte hotovo")


def test_a_short_run_leaves_an_easy_top_up(client, db_session):
    rid, r = _runner(client, db_session, "fb1002b@test.cz")
    _run_today(db_session, rid, 2.0)
    g = _guide(db_session, rid, r)
    if g["afterDone"] and g["type"] != "volno":
        assert g["type"] in ("lehký", "regenerace", "dlouhý") and "krátký lehký běh" in g["afterDone"]["text"]


def test_after_done_rules():
    types = {k: {"allowed": True, "km": {"lo": 6, "hi": 8}} for k in G.TYPES}
    hard_bike = {"run": False, "sport": "cycling", "title": "Kolo", "durationMin": 90, "rpe": 8, "exp": {}}
    out = G._after_done("kvalitní", types, [], [hard_bike], 8.0, None, False)
    assert out["type"] == "lehký" and "náročný trénink" in out["text"]
    assert G._after_done("lehký", types, [], [], 8.0, None, False) is None
    assert G._after_done("lehký", types, [], [hard_bike], 8.0, {"kind": "injury"}, False) is None
