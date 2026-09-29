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
    # the plain assessment stays lean
    with E.engine_pinned("v3"):
        assert "history" not in C.assess_capacity(db, rid, runner=r)


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
