"""All-day heart rate, own logic for every device (owner request 2026-10-03)."""
from datetime import date, timedelta

import garmin_live as GL
from app import models
from app.metrics import capacity as C
from app.metrics import dayload as DL
from app.metrics import engine as E

from .conftest import register
from .synth import garmin_hr_payloads, seed_details, seed_runs


def _raw(day="2026-10-03", **kw):
    return GL.compact_raw(*garmin_hr_payloads(day, **kw))


def test_raw_is_kept_at_the_watch_resolution():
    raw = _raw()
    assert len(raw["hr"]) == 720 and raw["hr"][0] == [0.0, raw["hr"][0][1]]          # every 2 minutes, local day
    assert len(raw["steps"]) == 96 and all(m % 15 == 0 for m, _ in raw["steps"])
    assert GL.compact_raw(None, None) is None


def test_day_states_load_and_raised_resting_hr():
    raw = _raw()
    res = DL.compute(raw, [(450, 510)], 390, 1380, hrmax=190, rhr=48, ref=None)
    # 90 min of walks (their 15-minute step intervals reach a bit wider) → load outside training, half weight
    assert 85 <= res["activeMin"] <= 120 and res["ntLoad"] > 0 and abs(res["ntLoad"] - 0.5 * res["ntRaw"]) < 0.2
    # the 90-minute stretch at 88 bpm while still is raised resting HR, the desk work isn't
    assert 80 <= res["highMin"] + res["mildMin"] <= 100
    assert res["trainingMin"] >= 60 and res["trainLoad"] > res["ntRaw"]
    states = {s for _, _, s, _, _ in res["timeline"]}
    assert {DL.STATE["sleep"], DL.STATE["training"], DL.STATE["active"], DL.STATE["calm"]} <= states
    # sample-by-sample load is above the load of 15-minute means (convex curve)
    walk = [v for m, v in raw["hr"] if 12 * 60 + 30 <= m < 13 * 60]
    mean_load = DL.trimp(30, (sum(walk) / len(walk) - 48) / 142)
    assert sum(DL.trimp(2, (v - 48) / 142) for v in walk) >= mean_load


def test_post_activity_tail_is_not_stress_and_unknown_start_is_found():
    raw = _raw()
    with_tail = DL.compute(raw, [(450, 510)], 390, 1380, 190, 48, None)
    assert with_tail["highMin"] < 100
    without = DL.compute(raw, [], 390, 1380, 190, 48, None)
    assert without["ntLoad"] > with_tail["ntLoad"]          # an unrecorded run would count as daily activity


def test_energy_curve_and_sleep_score():
    res = DL.compute(_raw(), [(450, 510)], 390, 1380, 190, 48, None)
    curve = DL.energy_curve(res["timeline"], 80, 50 / 200, 390)
    vals = [v for _, v in curve]
    assert vals[0] == 80 and min(vals) >= 5 and vals[-1] < vals[0]
    run_drop = [v for m, v in curve if 450 <= m <= 525]
    assert run_drop[0] - run_drop[-1] > 5                 # the run drains the most
    good = DL.sleep_score(8.0, 0.93, {"deep": 90, "rem": 110, "light": 260}, {"h": 7.5, "deep": 85, "rem": 100, "light": 250}, 10, 1)
    bad = DL.sleep_score(5.5, 0.82, {"deep": 40, "rem": 50, "light": 220}, {"h": 7.5, "deep": 85, "rem": 100, "light": 250}, 80, 6)
    assert good["score"] > 85 > 60 > bad["score"] and sum(p["max"] for p in good["parts"]) == 100


def test_engine_uses_the_excess_load_and_raised_resting_hr(client, db_session):
    rid = register(client, "dl1@test.cz", "Den", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    seed_runs(db_session, rid, days=60)
    seed_details(db_session, rid, days=14)
    rows = db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.nt_load.isnot(None)).all()
    assert len(rows) == 14 and all(x.rest_hr_med for x in rows)
    # a very active day today: only the excess over the usual day counts
    t = E.today_date().isoformat()
    dm = next(x for x in rows if x.date == t)
    usual = sorted(x.nt_load for x in rows if x.date < t)[len(rows[:-1]) // 2]
    dm.nt_load = usual + 40
    # yesterday: a long stretch of raised resting HR
    y = (E.today_date() - timedelta(days=1)).isoformat()
    next(x for x in rows if x.date == y).rest_high_min = 400
    db_session.commit()
    nt = C.nontraining_daily(db_session, rid)
    assert abs(nt[t] - 40) < 15
    a = E.recompute_assessment(db_session, rid)
    w7 = a["capacity"]["channels"]["systemic"]["week7"]
    assert any(x["sport"] == "daily" and x["date"] == t for x in w7)
    rd = a["capacity"]["readiness"]
    assert rd["parts"].get("dayStress", 0) > 0 and rd["inputs"]["dayStress"]["yesterday"] >= 400
