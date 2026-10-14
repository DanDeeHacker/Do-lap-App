"""v0.12.12 — Kondice a únava (42/7-day averages of the total load) and Čerstvost on race day."""
from datetime import timedelta

from app import models
from app.metrics import engine as E
from app.metrics import fitness as FT
from .test_guidance import _runner


def test_averages_follow_the_load():
    t0 = E.today_date() - timedelta(days=299)
    loads = {(t0 + timedelta(days=i)).isoformat(): 50.0 for i in range(293)}     # steady, then 7 days off
    rows: list = []
    FT._run(loads, t0, t0 + timedelta(days=299), rows=rows)
    steady = rows[292]
    assert abs(steady["fit"] - 50) < 1 and abs(steady["fat"] - 50) < 0.5 and abs(steady["form"]) < 2
    rest = rows[-1]                                  # a week off: fatigue falls fast, fitness slowly
    assert rest["fat"] < 0.4 * 50 and rest["fit"] > 0.8 * 50
    assert rest["form"] > FT.FORM_FRESH and FT.form_word(rest["form"]) == "fresh"
    assert FT.form_word(-15) == "tired" and FT.form_word(0) == "even" and FT.form_pct(5, 1) is None


def test_trend_endpoint(client, db_session):
    rid, _ = _runner(client, db_session, "fit1@test.cz", days=120)
    res = client.get(f"/api/runners/{rid}/fitness-trend")
    assert res.status_code == 200
    d = res.json()
    assert d["available"] and d["tc"] == [42, 7] and not d["settling"]
    assert d["days"][-1]["d"] == E.today_date().isoformat() and 115 <= len(d["days"]) <= 121
    t = d["today"]
    assert t["fit"] > FT.FORM_MIN_FIT and t["word"] in ("fresh", "even", "tired")
    # the loads are the engine's own: the day sums match session_load
    a = E.get_or_refresh_assessment(db_session, rid)
    hrmax, rhr = FT._hr(db_session, rid, a)
    loads, _ = FT.daily_loads(db_session, rid, hrmax, rhr)
    day = next(x for x in reversed(d["days"]) if x["load"] > 0)
    assert abs(day["load"] - loads[day["d"]]) < 0.1


def _taper_res(today, start_off=-2, week_km=30.0):
    t0 = today + timedelta(days=start_off)
    plan = [{"i": 1, "start": t0.isoformat(), "phase": "taper", "taper": 1, "km": round(0.6 * week_km, 1)},
            {"i": 2, "start": (t0 + timedelta(days=7)).isoformat(), "phase": "taper", "taper": 2,
             "km": round(0.4 * week_km, 1), "race": True}]
    return {"goal": {"kind": "race", "date": (t0 + timedelta(days=13)).isoformat(), "km": 21.1}, "plan": plan}


def test_race_check_shows_extra_load_in_the_taper(client, db_session):
    rid, _ = _runner(client, db_session, "fit2@test.cz", days=120)
    today = E.today_date()
    t0 = (today - timedelta(days=8)).isoformat()      # the race week began yesterday, the race in 5 days
    lo = (today - timedelta(days=36)).isoformat()
    km = sum(a.distance_km or 0 for a in db_session.query(models.Activity).filter(
        models.Activity.runner_id == rid, models.Activity.started_at >= lo, models.Activity.started_at < t0))
    res = _taper_res(today, start_off=-8, week_km=km / 4)    # the runner's own weeks: 60 % and 40 % of them
    db_session.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at >= t0).delete()
    db_session.commit()
    stored = FT.taper_plan(res["plan"])
    on = FT.race_check(db_session, rid, res, None, stored, today)
    assert on["inTaper"] and on["planned"] is not None and on["daysTo"] == 5
    # nothing run in the taper so far: fresher than planned, never a warning
    assert on["form"] >= on["planned"] and on["form"] > 20 and on["tone"] in ("ok", "info")
    # two long hard runs in the race week → less fresh than planned
    for k in (1, 2):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"extra{k}", sport="running",
                                       title="Běh", started_at=(today - timedelta(days=k)).isoformat(), distance_km=20,
                                       duration_min=110, avg_hr=168))
    db_session.commit()
    over = FT.race_check(db_session, rid, res, None, stored, today)
    assert over["form"] < over["planned"] - FT.PLAN_GAP and over["kind"] in ("lessFresh", "tired")
    assert over["tone"] in ("watch", "alert")


def test_race_check_only_near_the_taper(client, db_session):
    rid, _ = _runner(client, db_session, "fit3@test.cz", days=60)
    today = E.today_date()
    assert FT.race_check(db_session, rid, _taper_res(today, start_off=30), None, None, today) is None
    near = FT.race_check(db_session, rid, _taper_res(today, start_off=5), None, None, today)
    assert near is not None and not near["inTaper"] and near["planned"] is None
    assert FT.race_check(db_session, rid, {**_taper_res(today), "goal": {"kind": "free", "date": "2099-01-01"}},
                         None, None, today) is None


# ------------------------------------------------------------------ zones check
from app.metrics import zonecheck as ZC  # noqa: E402


def test_hist_peak_ignores_short_spikes():
    hist = {"150": 600.0, "176": 40.0, "190": 6.0}          # 6 s at 190 is a spike, 46 s from 176 up
    assert ZC.hist_peak(1, hist) == 177.0
    assert ZC.hist_peak(2, {"150": 10.0}) is None


def _cap(db, rid):
    with E.engine_pinned("v3"):
        return E.assess(db, rid)["capacity"]


def test_zone_check_flags_a_higher_recorded_max(client, db_session):
    rid, r = _runner(client, db_session, "zc1@test.cz", days=60)
    zc = _cap(db_session, rid)["zoneCheck"]
    assert zc["hrMax"]["source"] in ("age", "runs", "default") and zc["hrMax"]["measured"] is None
    assert [f["key"] for f in zc["flags"]] == ["hrEstimated"]
    used = zc["hrMax"]["value"]
    a = (db_session.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == "running")
         .order_by(models.Activity.started_at.desc()).first())
    db_session.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id, created_at=E.now_iso(),
                                         quality_json={"hrHist": {"150": 900.0, str(used + 6): 50.0}}))
    db_session.commit()
    zc = _cap(db_session, rid)["zoneCheck"]
    above = next(f for f in zc["flags"] if f["key"] == "hrAbove")
    assert above["hr"] == used + 7 and above["used"] == used and zc["peak"]["id"] == a.id
    # the runner takes it over as the measured maximum → the check is quiet and the zones use it
    assert client.patch(f"/api/runners/{rid}", json={"patch": {"hr_max": used + 7}}).status_code == 200
    db_session.expire_all()
    cap = _cap(db_session, rid)
    assert cap["zoneCheck"]["hrMax"]["source"] == "profile" and not cap["zoneCheck"]["flags"]
    assert cap["hrMax"] == used + 7


def test_zone_check_threshold_outside_range(client, db_session):
    rid, r = _runner(client, db_session, "zc2@test.cz", days=40)
    r.threshold_hr = 40
    db_session.commit()
    zc = _cap(db_session, rid)["zoneCheck"]
    assert "lthrOut" in [f["key"] for f in zc["flags"]] and not zc["lthr"]["used"]


def test_goal_card_carries_the_race_check(client, db_session):
    rid, _ = _runner(client, db_session, "fit4@test.cz", days=120)
    race = (E.today_date() + timedelta(days=200)).isoformat()
    body = {"kind": "race", "name": "Maraton", "date": race, "km": 42.2, "aim": "finish"}
    assert client.put(f"/api/runners/{rid}/goal", json=body).status_code == 200
    d = client.get(f"/api/runners/{rid}/goal").json()
    assert "freshness" in d["track"] and d["track"]["freshness"] is None        # the taper is months away
    g = db_session.query(models.Goal).filter(models.Goal.runner_id == rid, models.Goal.status == "active").one()
    assert "taperPlan" not in (g.track_json or {})                              # nothing stored that early
