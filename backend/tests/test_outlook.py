"""Owner feedback 2026-10-10 — the week's plan vs the safety limits, and the outlook for
tomorrow (metrics/outlook.py)."""
from datetime import date, timedelta

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from app.metrics import guidance as G
from app.metrics import outlook as O
from .conftest import register
from .synth import seed_runs


def _setup(client, db, email, day, **kw):
    with E.today_pinned(day):
        rid = register(client, email, "Outlook", "runner").json()["runner_id"]
        kw.setdefault("p_run", 0.55)
        seed_runs(db, rid, days=100, **kw)
        db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                         models.Activity.started_at == E.day_ago(0)).delete()
        r = db.query(models.Runner).filter(models.Runner.id == rid).first()
        r.engine_mode = "v3"
        db.commit()
    return rid, r


def _guide(db, rid, r, day, **patch):
    with E.today_pinned(day), E.engine_pinned("v3"):
        a = E.assess(db, rid)
        a.update(patch)
        return a, G.build_guidance(db, rid, a, r)


def _act(db, rid, ext, day, **kw):
    base = dict(runner_id=rid, provider="garmin", external_id=ext, started_at=day.isoformat(), title="Akt")
    db.add(models.Activity(**{**base, **kw}))
    db.commit()


def test_week_load_uses_the_capacity_heart_rate_bounds(client, db_session):
    """The guidance recomputes the loads with the unrounded HR max / rest of the capacity,
    so the 7-day all-sport load matches the Zátěž tab to the point."""
    day = date(2026, 10, 8)
    rid, r = _setup(client, db_session, "ol1@test.cz", day)
    a, g = _guide(db_session, rid, r, day, load=0)
    cap = a["capacity"]
    assert len(cap["hrExact"]) == 2 and abs(cap["hrExact"][0] - cap["hrMax"]) <= 0.5
    sysw = g["week"]["channels"]["systemic"]
    assert sysw["done7"] == cap["channels"]["systemic"]["week"]["now"]
    # the week from Monday is part of the last 7 days (Thursday: Mon–Thu ⊂ the 7 days)
    assert sysw["done"] <= sysw["done7"] + 0.5


def test_plan_bound_systemic_is_not_a_safety_ceiling(client, db_session):
    """Celková zátěž's weekly TARGET met by two long rides early in the week, the absorbed
    load well under the ceiling by Saturday: today is volno by the plan, the short easy run
    and a ride stay optional, and the text says it's the plan, not a ceiling."""
    day = date(2026, 10, 10)                               # Saturday
    rid, r = _setup(client, db_session, "ol2@test.cz", day)
    with E.today_pinned(day):
        db_session.query(models.Activity).filter(models.Activity.runner_id == rid,
                                                 models.Activity.started_at >= "2026-10-05").delete()
        db_session.commit()
    for k, d in enumerate((date(2026, 10, 5), date(2026, 10, 6))):
        _act(db_session, rid, f"ride{k}", d, sport="cycling", duration_min=150, avg_hr=145)
    a, g = _guide(db_session, rid, r, day, load=0)
    ch = g["week"]["channels"]
    sysw, vol = ch["systemic"], ch["volume"]
    assert sysw["limitedBy"] == "week" and sysw["bound"] == "plan"
    assert sysw["safeMax"] > 0 and sysw["todayMax"] == 0
    assert vol["limitedBy"] == "systemic" and vol["bound"] == "plan"
    assert vol["safeMax"] >= G.MIN_RUN_KM > vol["todayMax"]
    assert g["type"] == "volno"
    reg = g["types"]["regenerace"]
    assert reg["allowed"] and reg["km"]["hi"] >= G.MIN_RUN_KM and reg["descentMax"] > 0
    assert g["types"]["kolo"]["allowed"] and g["types"]["kolo"]["optional"]
    assert g["types"]["kolo"]["durationMin"][1] <= G.EXTRA_RIDE_MAX
    txt = " ".join(g["reasons"])
    assert "plán týdne, ne strop" in txt and "na stropu" not in txt


def test_safety_bound_systemic_still_reads_as_the_ceiling(client, db_session):
    day = date(2026, 10, 8)
    rid, r = _setup(client, db_session, "ol3@test.cz", day)
    for k in range(1, 4):                                  # three long hard rides right before today
        _act(db_session, rid, f"bike{k}", day - timedelta(days=k), sport="cycling", duration_min=240, avg_hr=160)
    a, g = _guide(db_session, rid, r, day, load=0)
    sysw, vol = g["week"]["channels"]["systemic"], g["week"]["channels"]["volume"]
    # the plan is far over too, but on a tie the safety limit is the one named
    assert sysw["limitedBy"] == "7d" and sysw["bound"] == "safety" and sysw["safeMax"] == 0
    assert vol["limitedBy"] == "systemic" and vol["bound"] == "safety" and vol["todayMax"] == 0
    assert not g["types"]["regenerace"]["allowed"] and not g["types"]["kolo"]["allowed"]
    assert not g["types"]["kolo"].get("optional")
    txt = " ".join(g["reasons"])
    assert "na stropu týdenní kapacity" in txt and "plán týdne" not in txt
    # nothing fits tomorrow either; the first day with room comes later
    ol = g["outlook"]
    assert not ol["grid"]["none"]["today"]["run"]
    assert ol["restRun"] and ol["restRun"]["n"] > 1


def test_outlook_carries_the_absorbed_load_one_night_forward(client, db_session):
    """Tomorrow's unabsorbed load from the outlook = what the next morning's capacity reports,
    for a run still done today (muscles / tendons absorb on a fixed half-life)."""
    day = date(2026, 10, 7)                                # Wednesday
    rid, r = _setup(client, db_session, "ol4@test.cz", day)
    a, g = _guide(db_session, rid, r, day, load=0)
    ol = g["outlook"]
    assert ol["date"] == "2026-10-08" and ol["toMonday"] == 5
    assert [n["key"] for n in ol["nights"]] == ["good", "today", "weak"]
    km = 7.0
    _act(db_session, rid, "today-run", day, sport="running", distance_km=km, duration_min=42, pace_s_km=360,
         avg_hr=145, surface="road", ascent_m=20, descent_m=20)
    a1, g1 = _guide(db_session, rid, r, day + timedelta(days=1), load=0)
    v1 = a1["capacity"]["channels"]["volume"]["week"]
    for n in ol["nights"]:
        mx, base, q = ol["channels"]["volume"]["byNight"][n["key"]]["terms"][0]
        assert abs((base + km) * q - v1["absorbedPast"]) < 0.11       # the dynamics are exact (km rounding)
        assert abs(mx - v1["absorbedMax"]) / v1["absorbedMax"] < 0.08    # the ceiling moves only a little


def test_outlook_evaluate_matches_todays_rules_and_presets(client, db_session):
    day = date(2026, 10, 7)
    rid, r = _setup(client, db_session, "ol5@test.cz", day)
    a, g = _guide(db_session, rid, r, day, load=0)
    ol = g["outlook"]
    keys = [p["key"] for p in ol["presets"]]
    assert keys[0] == "none" and "rec" in keys
    for p in ol["presets"]:
        for n in ol["nights"]:
            v = ol["grid"][p["key"]][n["key"]]
            assert set(v) == {"ch", "run", "quality", "long"}
            for c, x in v["ch"].items():
                if x["max"] is not None and x["safe"] is not None:
                    assert x["max"] <= x["safe"] + 1e-6 or x["lim"] == "week" or x["bound"] == "plan"
    # more done today never leaves more for tomorrow, a better night never less
    none, rec = ol["grid"]["none"], ol["grid"]["rec"]
    for n in ("good", "today", "weak"):
        assert rec[n]["ch"]["volume"]["max"] <= none[n]["ch"]["volume"]["max"] + 1e-6
    assert none["good"]["ch"]["systemic"]["max"] >= none["weak"]["ch"]["systemic"]["max"] - 1e-6
    # the run of the recommended preset adds its km and its all-sport load
    p = next(p for p in ol["presets"] if p["key"] == "rec")
    assert p["x"]["volume"] == p["act"]["runKm"] and p["x"]["systemic"] > 0


def test_outlook_resets_the_plan_on_monday(client, db_session):
    day = date(2026, 10, 11)                               # Sunday → tomorrow is a new week
    rid, r = _setup(client, db_session, "ol6@test.cz", day)
    a, g = _guide(db_session, rid, r, day, load=0)
    ol = g["outlook"]
    assert ol["toMonday"] == 1
    vol = ol["channels"]["volume"]
    ev = O.evaluate(ol, {"volume": 100.0}, "good")["volume"]
    # whatever is run today, Monday's plan is next week's target (only the safety room shrinks)
    if vol["planNext"] is not None and ev["lim"] == "week":
        assert abs(ev["max"] - vol["planNext"]) < 1e-6


def test_absorbed_series_ends_where_the_room_says(client, db_session):
    day = date(2026, 10, 7)
    rid, r = _setup(client, db_session, "ol7@test.cz", day)
    a, g = _guide(db_session, rid, r, day, load=0)
    w = a["capacity"]["channels"]["volume"]["week"]
    s = w["series"]
    assert len(s) == 17 and s[-4]["date"] == day.isoformat() and not s[-4]["rest"] and all(x["rest"] for x in s[-3:])
    assert abs(s[-4]["v"] - w["absorbed"]) < 0.11
    assert s[-1]["v"] < s[-2]["v"] < s[-3]["v"] <= s[-4]["v"] + 0.05
    assert w["inputs"]["basis"] in ("avg4", "best", "floor")
    assert abs(max(w["inputs"]["avg4"], w["inputs"]["best"], w["inputs"]["floor"]) - w["cap"]) < 0.11 \
        or w.get("capBase") is not None
    days = g["week"]["days"]
    assert len(days) == 7 and days[0]["date"] == "2026-10-05"
    assert abs(sum(sum(d["by"]["volume"].values()) for d in days) - g["week"]["channels"]["volume"]["done"]) < 0.2
