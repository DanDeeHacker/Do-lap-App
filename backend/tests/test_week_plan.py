"""Owner request 2026-10-04: the week's plan in the Monday morning report (metrics/week_plan.py)
— runs, strength and rides by day, at the edge of capacity but never over it."""
from datetime import date, timedelta

from app.metrics import week_plan as WP

MON = date(2026, 10, 5)


def _types():
    run = lambda lab, hr, z: {"label": lab, "km": {"lo": 5.0, "hi": 6.0}, "hr": hr, "hrZones": z, "pace": [320, 345],
                             "durationMin": [27, 35], "z4Target": None, "descentMax": 60, "ascentMax": 60, "allowed": True}
    t = {"volno": {"label": "Volno", "allowed": True}, "regenerace": run("Regenerační běh", [120, 135], "Z1–Z2"),
         "lehký": run("Lehký běh", [130, 146], "Z2"), "dlouhý": run("Dlouhý běh", [130, 150], "Z2"),
         "kvalitní": {**run("Kvalitní trénink", [165, 178], "Z4–Z5 v úsecích, jinak Z1–Z2"), "pace": None,
                      "z4Target": {"lo": 12, "hi": 20}},
         "kolo": {"label": "Kolo", "durationMin": [40, 60], "hr": [118, 132], "hrZones": "Z2 na kole", "allowed": True},
         "voda": {"label": "Plavání", "durationMin": [25, 40], "allowed": True},
         "posilování": {"label": "Posilování", "allowed": True}}
    return t


def _a(**over):
    """A runner with 5 runs a week (Tue, Wed, Thu, Sat, Sun), the long run on Sunday, hard on Tue / Thu."""
    ctx = {
        "past": {"volume": {(MON - timedelta(days=k)).isoformat(): v for k, v in zip(range(1, 7), (16, 0, 8, 10, 8, 0))},
                 "intensity": {(MON - timedelta(days=k)).isoformat(): v for k, v in zip(range(1, 7), (2, 0, 18, 0, 3, 0))},
                 "descent": {}, "ascent": {},
                 "systemic": {(MON - timedelta(days=k)).isoformat(): v for k, v in zip(range(1, 7), (170, 60, 120, 100, 90, 0))}},
        "lastHard": (MON - timedelta(days=3)).isoformat(), "hardThisWeek": [], "todayHard": False, "hardCap": 3,
        "readiness": 88, "novice": False, "painMod": False, "painWhy": None, "pain": 0, "ill": False, "illLight": False,
        "illWatch": False, "drift": False, "deload": False, "overreaching": False, "raceRecoveryUntil": None,
        "noQualityUntil": None, "races": [], "perKm": 10.0, "perMinRide": 1.6, "z4PerMin": 4.0, "kSrpe": 0.9,
        "rideHr": [118, 132], "rides8w": 6, "longest30": 16.0, "easyKm": 8.0, "easyPace": 330,
        "ceilRun": {"volume": 17.0, "intensity": 24, "descent": 250, "ascent": 250}, "noSpeedWeeks": False,
        "kolo": True, "koloNote": None,
    }
    ctx.update(over.pop("ctx", {}))
    g = {"type": over.pop("type", "volno"), "done": None, "override": over.pop("override", None),
         "readinessScore": ctx["readiness"], "types": _types(),
         "pattern": {"runsPerWeek": 5, "runDays": [1, 2, 3, 5, 6], "longDay": 6, "hardDays": [1, 3], "hardPerWeek": 2.0},
         "strength": {"target": 2, "done": 0, "today": False, "lastAge": 5},
         "week": {"mode": "build", "progression": 1.0, "cycle": {"pos": 2, "weeks": [{"km": 40}, {"km": 42}, {"km": 44}, {"km": 42}, {}]},
                  "channels": {"volume": {"budget": 46.0, "done": 0.0, "doneToday": 0, "ceiling7": 50.0},
                               "intensity": {"budget": 40, "done": 0, "doneToday": 0, "ceiling7": 45},
                               "descent": {"budget": 600, "done": 0}, "ascent": {"budget": 600, "done": 0},
                               "systemic": {"budget": 640, "done": 0, "doneToday": 0, "ceiling7": 700}}},
         "planCtx": ctx}
    for k, v in over.items():
        g["week"]["channels"][k].update(v)
    return {"guidance": g}


def _items(p, kind=None):
    return [(date.fromisoformat(d["date"]), it) for d in p["days"] for it in d["items"] if kind is None or it["kind"] == kind]


def _runs(p, typ=None):
    return [(d, it) for d, it in _items(p, "run") if typ is None or it["type"] == typ]


def test_a_normal_week_reaches_the_target_and_keeps_every_rule():
    a = _a()
    p = WP.build(a, MON, {"name": "Runner's must-have", "due": "A", "last": None})
    t = p["totals"]
    km = sum(it["km"]["hi"] for _, it in _runs(p) if not it["optional"])
    assert abs(km - 46.0) < 0.6 and km <= 46.05                     # at the edge of the target, not over
    long_ = _runs(p, "dlouhý")
    assert len(long_) == 1 and long_[0][0].weekday() == 6 and long_[0][1]["km"]["hi"] <= 17.0
    hard = [d for d, _ in _runs(p, "kvalitní")]
    assert 1 <= len(hard) <= 2 and all(d.weekday() in (1, 3) for d in hard)
    anchors = hard + [long_[0][0], MON - timedelta(days=3)]
    assert all(abs((h - o).days) >= 2 for h in hard for o in anchors if o != h)
    z4 = sum(it["z4"]["hi"] for _, it in _runs(p, "kvalitní"))
    assert z4 <= 40 and all(it["z4"]["hi"] <= 24 for _, it in _runs(p, "kvalitní"))
    assert all("× " in it["session"] and "Z4" in it["session"] for _, it in _runs(p, "kvalitní"))
    # every 7 days in a row with the end of last week stay under the ceiling
    vol = {date.fromisoformat(k): v for k, v in a["guidance"]["planCtx"]["past"]["volume"].items()}
    for d, it in _runs(p):
        vol[d] = vol.get(d, 0) + it["km"]["hi"]
    for k in range(7):
        end = MON + timedelta(days=k)
        assert sum(vol.get(end - timedelta(days=j), 0) for j in range(7)) <= 50.0 + 1e-6
    # strength: twice, 48 h apart, never the day before a hard / long run, A not on or after one
    st = _items(p, "strength")
    assert len(st) == 2 and (st[1][0] - st[0][0]).days >= 2 and t["strength"] == 2
    hard_or_long = set(hard) | {long_[0][0]}
    for d, it in st:
        assert d + timedelta(days=1) not in hard_or_long
        if it["sessionKey"] == "A":
            assert d not in hard_or_long and d - timedelta(days=1) not in hard_or_long
    # rides only on run-free days, and a day of full rest stays
    for d, _ in _items(p, "ride"):
        assert not any(dd == d for dd, _ in _runs(p))
    assert any(all(it["kind"] == "rest" for it in day["items"]) for day in p["days"])
    assert WP.note(p).startswith("Týden na")


def test_pain_takes_out_intensity_and_the_long_run():
    p = WP.build(_a(ctx={"painMod": True, "painWhy": "Bolest 4/10"}), MON)
    assert not _runs(p, "kvalitní") and not _runs(p, "dlouhý")
    assert any("Bolest 4/10" in n for n in p["notes"])


def test_low_readiness_keeps_the_first_two_days_easy():
    p = WP.build(_a(ctx={"readiness": 50}), MON)
    assert all((d - MON).days >= 2 for d, _ in _runs(p, "kvalitní"))
    assert any("Připravenost dnes 50" in n for n in p["notes"])


def test_a_race_on_saturday_shapes_the_week():
    p = WP.build(_a(ctx={"races": [{"date": (MON + timedelta(days=5)).isoformat(), "name": "Běchovice", "km": 10,
                                    "priority": "A"}]}), MON)
    race = MON + timedelta(days=5)
    assert any(it["kind"] == "race" for d, it in _items(p) if d == race)
    assert not _runs(p, "dlouhý")
    assert all(abs((d - race).days) > 2 for d, _ in _runs(p, "kvalitní"))
    assert all(not 0 <= (race - d).days <= 3 for d, _ in _items(p, "strength"))


def test_a_heavy_end_of_last_week_lowers_the_first_days():
    # 46 km in the last 3 days: the rolling 7 days leave little room early in the week
    past = {(MON - timedelta(days=k)).isoformat(): v for k, v in zip(range(1, 7), (20, 14, 12, 0, 0, 0))}
    a = _a(ctx={"past": {**_a()["guidance"]["planCtx"]["past"], "volume": past}})
    p = WP.build(a, MON)
    vol = {date.fromisoformat(k): v for k, v in past.items()}
    for d, it in _runs(p):
        vol[d] = vol.get(d, 0) + it["km"]["hi"]
    for k in range(7):
        end = MON + timedelta(days=k)
        assert sum(vol.get(end - timedelta(days=j), 0) for j in range(7)) <= 50.0 + 1e-6


def test_an_injury_stops_the_running_plan():
    p = WP.build(_a(override={"kind": "injury", "title": "Aktivní zranění — dnes bez běhu"}), MON)
    assert p["override"].startswith("Aktivní zranění") and not _runs(p)
    assert p["totals"] is None


def test_no_cycling_history_makes_rides_optional_and_tight_load_drops_them():
    p = WP.build(_a(ctx={"rides8w": 0}), MON)
    assert all(it["optional"] for _, it in _items(p, "ride"))
    p2 = WP.build(_a(systemic={"budget": 470}), MON)
    assert not _items(p2, "ride") and p2["totals"]["rides"] == 0


def test_the_report_shows_the_plan_only_on_monday(client, db_session):
    from app.metrics import daily_report as DR
    from app.metrics import engine as E
    from .conftest import register
    rid = register(client, "plan1004@test.cz", "Plánovač", "runner").json()["runner_id"]
    with E.today_pinned(MON):
        r = DR.build(db_session, rid, "morning")
    assert "weekPlan" in r
    with E.today_pinned(MON + timedelta(days=1)):
        r2 = DR.build(db_session, rid, "morning")
    assert "weekPlan" not in r2
