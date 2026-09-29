"""v0.8.7 — Zátěž → Historie aktivit (per-activity channel breakdown) and the readiness
breakdown behind the Připravenost detail (feedback railway#107)."""
from datetime import timedelta

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from .conftest import register
from .synth import seed_runs


def _day(n):
    return (E.today_date() - timedelta(days=n)).isoformat()


def test_readiness_effects_follow_the_score_rule():
    parts = {"hrv": 0.4, "sleep": 0.2, "soreness": 0.1, "stress": 0.05}
    eff = C.readiness_effects(parts)
    # worst fully, 2nd half, 3rd a quarter, the rest nothing
    assert eff == {"hrv": 32.0, "sleep": 8.0, "soreness": 2.0, "stress": 0.0}
    _f, score = C.readiness_from(parts)
    assert abs((100 - score) - sum(eff.values())) <= 0.5
    # the combined deficit is capped at 1 → the effects never add up to more than 80
    big = C.readiness_effects({"hrv": 1.0, "rhr": 1.0, "sleep": 1.0})
    assert abs(sum(big.values()) - 80) < 0.2 and big["hrv"] > big["rhr"] > big["sleep"]
    assert C.readiness_effects({}) == {}


def test_readiness_carries_inputs_effects_and_yesterday(client, db_session):
    rid = register(client, "lh-ready@test.cz", "LH Ready", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid, days=100)
    for k in range(1, 60):
        db.add(models.DailyMetric(runner_id=rid, date=_day(k), sleep_h=7.5 + (k % 3) * 0.2,
                                  hrv_ms=60 + (k % 5), resting_hr=50 + (k % 3)))
    db.add(models.DailyMetric(runner_id=rid, date=_day(0), sleep_h=5.0, hrv_ms=40, resting_hr=60))
    db.add(models.Checkin(runner_id=rid, submitted_at=_day(0) + "T07:00:00", soreness=7, stress=3, life_stress=2,
                          pain_score=0, pain_points=[]))
    db.commit()
    with E.engine_pinned("v3"):
        a = E.assess(db, rid)
    r = a["capacity"]["readiness"]
    assert r["known"] and r["yesterday"]["known"]
    assert r["effects"]["hrv"] > 0 and r["effects"]["soreness"] > 0
    assert abs((100 - r["score"]) - sum(r["effects"].values())) <= 0.6
    i = r["inputs"]
    assert i["night"]["hrv"] == 40 and i["night"]["rhr"] == 60 and i["base"]["hrv"] in range(60, 65)
    assert i["checkin"] == {"soreness": 7, "fatigue": 3, "stress": 2, "sleepQuality": None}
    # a calm yesterday → today's morning is lower than yesterday's
    assert r["yesterday"]["score"] > r["morningScore"]


def test_history_breaks_each_activity_down_by_its_own_channels(client, db_session):
    rid = register(client, "lh-hist@test.cz", "LH Hist", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid, days=100)
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id="lh-ride", started_at=E.day_ago(1),
                           sport="cycling", title="Kolo", duration_min=75, avg_hr=135))
    db.add(models.Activity(runner_id=rid, provider="manual", started_at=E.day_ago(2), sport="strength",
                           title="Posilování", duration_min=45, strength_focus="lower", strength_type="heavy"))
    # a clear volume jump today, so something holds points
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id="lh-jump", started_at=E.day_ago(0),
                           sport="running", title="Dlouhý", distance_km=24.0, duration_min=24 * 6,
                           avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    db.commit()
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    with E.engine_pinned("v3"):
        cap = C.assess_capacity(db, rid, runner=r, with_history=True)
    h = cap["history"]
    assert h and h[0]["date"] == _day(0) and all(x["age"] < C.HISTORY_DAYS for x in h)
    assert [x["date"] for x in h] == sorted((x["date"] for x in h), reverse=True)
    ride = next(x for x in h if x["sport"] == "cycling")
    lift = next(x for x in h if x["sport"] == "strength")
    run = h[0]
    assert [c["ch"] for c in ride["channels"]] == ["systemic"] and ride["sportLabel"] == "kolo"
    assert {c["ch"] for c in lift["channels"]} <= {"systemic", "strength"} and "strength" in {c["ch"] for c in lift["channels"]}
    assert {c["ch"] for c in run["channels"]} >= {"volume", "systemic"}
    assert not {c["ch"] for c in run["channels"]} & {"strength"}
    vol = next(c for c in run["channels"] if c["ch"] == "volume")
    assert vol["ratio"] > 2.0 and vol["band"] == "výrazně nad" and vol["left"] == 1.0 and vol["pts"] > 0
    # every channel's points in today's score are attributed to the activities behind them
    for ch, c in cap["channels"].items():
        got = sum(cc["scorePts"] for x in h for cc in x["channels"] if cc["ch"] == ch)
        assert abs(got - (c.get("pts") or 0)) <= 0.6, ch
    assert abs(sum(x["scorePts"] for x in h) - cap["score"]) <= 1.5
    # railway#110 — the jump is over the per-run ceiling by value − ceiling, so no room is left
    assert any(o["ch"] == "volume" and abs(o["over"] - (vol["value"] - vol["ceiling"])) <= 0.15 for o in run["over"])
    assert run["extra"] is None and vol["weekCeiling"] and vol["weekBefore"] >= 0
    # a normal run earlier in the window has room: minutes at its own pace up to the nearer ceiling
    calm = next((x for x in h[1:] if x["run"] and not x["over"] and not x["weekOver"] and x["extra"]), None)
    if calm:
        c0 = next(c for c in calm["channels"] if c["ch"] == calm["extra"]["ch"])
        assert c0["extraMin"] == calm["extra"]["min"] and calm["extra"]["min"] >= 0
    # readiness around the day: morning, after the session, next morning (None without watch data)
    assert "readiness" in run
    # the plain assessment stays lean
    with E.engine_pinned("v3"):
        assert "history" not in C.assess_capacity(db, rid, runner=r)


def test_impacts_add_up_to_the_overall_risk_and_signals_carry_sources(client, db_session):
    """railway#111 / #113 — each signal's effect in percentage points of the Skóre, and the
    records behind it; a capacity channel set by one run names that run with share 1."""
    rid = register(client, "lh-imp@test.cz", "LH Imp", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid, days=100)
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id="imp-jump", started_at=E.day_ago(0),
                           sport="running", title="Dlouhý", distance_km=26.0, duration_min=26 * 6,
                           avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    db.commit()
    client.post(f"/api/runners/{rid}/engine", json={"mode": "v3"})
    a = E.recompute_assessment(db, rid)
    sc = a["impactScale"]
    assert set(sc) == {"mech", "load", "symp"} and 0 < sc["load"] <= 0.42      # ≤ the weight, up to rounding
    for s in a["signals"]:
        assert s["axis"] in sc and abs(s["impact"] - s["pts"] * sc[s["axis"]]) < 0.01
        assert isinstance(s.get("sources"), list)
    # listed signals never claim more than the overall risk (unlisted mechanics points exist)
    assert sum(s["impact"] for s in a["signals"]) <= a["overall"] + 0.6
    vol = next(s for s in a["signals"] if s["id"] == "cap_volume")
    ch = a["capacity"]["channels"]["volume"]
    if ch["driver"] == "session":
        assert vol["sources"][0]["share"] == 1.0 and vol["sources"][0]["title"] == "Dlouhý"
    else:
        assert abs(sum(x["share"] for x in vol["sources"]) - 1) <= 0.1
    # past days replayed for the history get no sources (and stay as fast)
    with E.today_pinned(E.today_date()), E.engine_pinned("v3"):
        assert all("sources" not in s for s in E.assess(db, rid)["signals"])
    # the endpoint hands the load scale to the history
    assert client.get(f"/api/runners/{rid}/load-history").json()["impactScale"] == sc["load"]


def test_impact_scale_handles_caps():
    sc = E.impact_scales({"mech": 50, "load": 200, "symp": 0}, {"mech": 50, "load": 100, "symp": 0},
                         {"mech": 0.38, "load": 0.4, "symp": 0.52}, 59)
    # load capped at 100 of 200 raw points → half of each point survives; overall 19 + 40 = 59 uncapped
    assert sc["load"] == 0.2 and sc["mech"] == 0.38 and sc["symp"] == 0.52
    sc2 = E.impact_scales({"mech": 100, "load": 100, "symp": 100}, {"mech": 100, "load": 100, "symp": 100},
                          {"mech": 0.38, "load": 0.4, "symp": 0.52}, 100)
    assert abs(100 * sum(sc2.values()) - 100) < 0.1        # the overall cap scales every axis alike


def test_load_history_endpoint(client, db_session):
    rid = register(client, "lh-api@test.cz", "LH Api", "runner").json()["runner_id"]
    seed_runs(db_session, rid, days=60)
    client.post(f"/api/runners/{rid}/engine", json={"mode": "v3"})
    d = client.get(f"/api/runners/{rid}/load-history").json()
    assert d["available"] and d["days"] == C.HISTORY_DAYS and d["items"]
    x = d["items"][0]
    assert {"id", "date", "title", "channels", "peak", "scorePts"} <= set(x)
    assert {"value", "cap", "ratio", "band", "left", "weekPct", "scorePts", "driver"} <= set(x["channels"][0])
    # a runner without the capacity model (v1) has nothing to break down
    client.post(f"/api/runners/{rid}/engine", json={"mode": "v1"})
    assert client.get(f"/api/runners/{rid}/load-history").json() == {"available": False, "items": []}


def test_runner_facing_texts_use_the_czech_decimal_comma(client, db_session):
    """v0.8.9 — a decimal point interpolated anywhere in engine text reads as a comma."""
    import re
    assert E.cz_text("×2.91 · +0.47 p.b. · -0.5 h") == "×2,91 · +0,47 p. b. · −0,5 h"
    assert E.cz_text("2026-09-29T13:59:06.399057+02:00") == "2026-09-29T13:59:06.399057+02:00"   # timestamps untouched
    assert E.cz_text("1–4 týdny, 80-90 %, 23. 9.") == "1–4 týdny, 80-90 %, 23. 9."
    assert E.cz_deep({"a": ["1.5 km", {"b": "2026-09-29"}], "n": 1.5}) == {"a": ["1,5 km", {"b": "2026-09-29"}], "n": 1.5}
    rid = register(client, "lh-cz@test.cz", "LH Cz", "runner").json()["runner_id"]
    seed_runs(db_session, rid, days=100)
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="cz-jump", started_at=E.day_ago(0),
                                   sport="running", title="Dlouhý", distance_km=24.3, duration_min=150,
                                   avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    db_session.commit()
    client.post(f"/api/runners/{rid}/engine", json={"mode": "v3"})
    a = E.recompute_assessment(db_session, rid)
    dot = re.compile(r"\d\.\d")
    assert a["signals"] and not any(dot.search(f"{s['val']} {s['detail']}") for s in a["signals"])
