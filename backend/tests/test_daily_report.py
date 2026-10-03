"""Morning / evening report (owner request 2026-10-03)."""
from datetime import date

import garmin_live as GL
from app import models
from app.metrics import daily_report as DR
from app.metrics import engine as E

from .conftest import register
from .synth import garmin_day_payloads, garmin_sleep_payload, seed_details, seed_runs


def test_sleep_and_day_payloads_compact():
    sl = GL.compact_sleep(garmin_sleep_payload("2026-10-03"))
    assert sl["start"] == "22:50" and sl["sleepMin"] > 300 and sl["score"] >= 70
    hyp = sl["hypnogram"]
    assert hyp[0][0] == 0 and all(a[1] == b[0] for a, b in zip(hyp, hyp[1:]))      # contiguous from falling asleep
    assert {x[2] for x in hyp} >= {"deep", "light", "rem"}
    assert sum(x[1] - x[0] for x in hyp if x[2] == "deep") == sl["stages"]["deep"]
    dy = GL.compact_day(*garmin_day_payloads("2026-10-03"))
    assert dy["steps"] == 11840 and dy["bbWake"] == 80 and dy["stressMin"]["high"] == 40
    assert dy["stress"][0][0] == 0 and all(0 <= m < 1440 for m, _ in dy["stress"])
    assert all(m % 15 == 0 for m, _ in dy["bb"]) and max(v for _, v in dy["bb"]) <= 100
    # the run hour has no stress values (Garmin sends -2 during activity)
    assert not any(450 <= m < 510 for m, _ in dy["stress"])
    assert GL.compact_sleep({}) is None and GL.compact_day(None, None) is None


def test_fetch_day_details_fills_rows_and_never_raises(client, db_session):
    from app.routers.integrations import fetch_day_details
    rid = register(client, "rep0@test.cz", "Rep", "runner").json()["runner_id"]

    class G:
        def get_sleep_data(self, d): return garmin_sleep_payload(d)
        def get_stress_data(self, d): return garmin_day_payloads(d)[0]
        def get_user_summary(self, d): return garmin_day_payloads(d)[1]
    db_session.add(models.DailyMetric(runner_id=rid, date=date(2026, 10, 3).isoformat(), sleep_h=7.2))
    db_session.commit()
    assert fetch_day_details(db_session, rid, G(), today=date(2026, 10, 3)) == 14        # first time: 14 days back
    assert fetch_day_details(db_session, rid, G(), today=date(2026, 10, 3)) == 3         # then today + 2 days
    dm = db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == "2026-10-03").one()
    assert dm.body_battery == 80 and dm.stress_avg == 29

    class Broken:
        def __getattr__(self, n): raise RuntimeError("down")
    assert fetch_day_details(db_session, rid, Broken(), today=date(2026, 10, 4)) == 0


def test_morning_and_evening_reports(client, db_session):
    rid = register(client, "rep1@test.cz", "Daniel Běžec", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    seed_runs(db_session, rid, days=70)
    seed_details(db_session, rid)
    E.recompute_assessment(db_session, rid)
    m = client.get(f"/api/runners/{rid}/report?kind=morning").json()
    assert m["greeting"] == "Dobré ráno, Daniel." and m["hasDetail"]
    n = m["night"]
    assert n["hours"] and n["start"] and n["hypnogram"] and n["norm"]["h"] and len(n["nights"]) == 7
    assert m["nightText"].startswith("Spali jste") and m["summary"]
    assert m["recovery"]["score"] is not None and m["recovery"]["bbWake"] == 80
    assert m["plan"]["label"] and len(m["questions"]) == 3
    e = client.get(f"/api/runners/{rid}/report?kind=evening").json()
    assert e["greeting"].startswith("Dobrý večer") and e["day"]["steps"] == 11840 and e["day"]["stress"] and e["day"]["bb"]
    assert len(e["week"]["days"]) == 7 and sum(d["today"] for d in e["week"]["days"]) == 1
    t = e["tonight"]
    assert 7.0 <= t["target"] <= 9.5 and t["bed"] and t["wakeFromWatch"]
    # bed + fall asleep + target = wake
    bm, wm = DR._min_of(t["bed"]), DR._min_of(t["wake"])
    assert (wm - bm) % 1440 == round(t["target"] * 60) + DR.FALL_ASLEEP_MIN
    assert "do postele kolem" in e["summary"]
    assert client.get(f"/api/runners/{rid}/report?kind=noon").status_code == 422


def test_rest_of_week_split():
    a = {"guidance": {"pattern": {"runDays": [1, 3, 5, 6], "longDay": 6, "hardDays": [3]}},
         "capacity": {"channels": {"volume": {"ceilingSession": 18.0}}}}
    wk = {"left": 30.0}
    out = DR._rest_of_week(a, date(2026, 9, 28), wk)                 # Monday
    days = {d["wd"]: d for d in out["days"]}
    assert days["ne"]["type"] == "dlouhý" and days["ne"]["km"] <= 18.0
    assert days["čt"]["type"] == "kvalitní" and days["st"]["type"] == "volno"
    assert abs(sum(d["km"] or 0 for d in out["days"]) - 30.0) < 0.3
    done = DR._rest_of_week(a, date(2026, 9, 28), {"left": 0.0})
    assert "splněný" in done["note"]
    assert DR._rest_of_week(a, date(2026, 10, 4), wk)["days"] == []    # Sunday: the week ends
