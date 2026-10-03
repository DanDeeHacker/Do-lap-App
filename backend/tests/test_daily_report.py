"""Morning / evening report (owner request 2026-10-03)."""
import json
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


def test_rows_without_all_day_heart_rate_are_filled_in(client, db_session):
    """v0.10.4 in production: the first reports saved nights and days without the all-day
    heart rate, and "a row exists" stopped the backfill — 3 days of heart rate, no 7-day
    usual day, so the day outside training never lowered readiness."""
    from app.routers.integrations import fetch_day_details
    from .synth import garmin_hr_payloads
    rid = register(client, "rawfill1@test.cz", "Rep", "runner").json()["runner_id"]
    today = date(2026, 10, 3)
    for k in range(14):                               # what the first reports left behind
        d = date.fromordinal(today.toordinal() - k).isoformat()
        db_session.add(models.DailyDetail(runner_id=rid, date=d, sleep=GL.compact_sleep(garmin_sleep_payload(d)),
                                          fetched_at=E.now_iso()))
    db_session.commit()
    calls = []

    class G:
        def get_sleep_data(self, d): return garmin_sleep_payload(d)
        def get_stress_data(self, d): return garmin_day_payloads(d)[0]
        def get_user_summary(self, d): return garmin_day_payloads(d)[1]
        def get_heart_rates(self, d): calls.append(d); return garmin_hr_payloads(d, seed=len(calls))[0]
        def get_steps_data(self, d): return garmin_hr_payloads(d, seed=len(calls))[1]
    assert fetch_day_details(db_session, rid, G(), today=today) == 14
    rows = db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                       models.DailyMetric.nt_load.isnot(None)).all()
    assert len(rows) == 14 and all(r.rest_hr_med for r in rows)
    calls.clear()
    assert fetch_day_details(db_session, rid, G(), today=today) == 3 and len(calls) == 3     # the rest is done

    class NoHr(G):
        def get_heart_rates(self, d): return None
        def get_steps_data(self, d): return None
    rid2 = register(client, "rawfill2@test.cz", "Rep", "runner").json()["runner_id"]
    assert fetch_day_details(db_session, rid2, NoHr(), today=today) == 14
    olds = db_session.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid2,
                                                       models.DailyDetail.date < "2026-10-01").all()
    assert len(olds) == 11 and all(r.raw == {} for r in olds)                             # asked, nothing there
    assert fetch_day_details(db_session, rid2, NoHr(), today=today) == 3                 # not asked again today


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


def test_report_cards_get_validated_ai_notes_or_keep_the_rules(client, db_session, monkeypatch):
    from app import llm
    from app.metrics import report_ai as RA
    rid = register(client, "rep2@test.cz", "Eva Běžkyně", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    seed_runs(db_session, rid, days=60)
    seed_details(db_session, rid)
    E.recompute_assessment(db_session, rid)
    m = client.get(f"/api/runners/{rid}/report?kind=morning").json()
    assert m["aiPending"] and set(m["notes"]) >= {"intro", "sleep", "readiness", "recent", "plan"}
    assert m["sleep"]["scores"][-1]["score"] is not None and m["recent"]["yesterday"]["view"]["timeline"]
    f = RA.facts(m)
    good = "Spánek byl v pořádku a hluboký spánek odpovídal normě. Držte pravidelný čas usínání i dnes večer."
    bad = "Spali jste 11 hodin, to je skvělé. Vezměte si ibuprofen na nohy."          # number not in facts + medication
    monkeypatch.setattr(llm, "assistant_available", lambda: True)
    monkeypatch.setattr(llm, "chat_messages", lambda *a, **k: json.dumps({"sleep": good, "plan": bad, "nonsense": "x"}))
    out = client.post(f"/api/runners/{rid}/report/ai?kind=morning").json()
    assert out["source"] == "ai" and out["notes"]["sleep"] == good and out["notes"]["plan"] == m["notes"]["plan"]
    row = db_session.query(models.ReportNote).filter(models.ReportNote.runner_id == rid).one()
    assert "plan" in row.rejected and set(f) >= set(row.notes)
    # cached for the same facts: the next report carries the model's sentence, no new call
    monkeypatch.setattr(llm, "chat_messages", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called again")))
    m2 = client.get(f"/api/runners/{rid}/report?kind=morning").json()
    assert not m2["aiPending"] and m2["notes"]["sleep"] == good
    e = client.get(f"/api/runners/{rid}/report?kind=evening").json()
    v = e["dayView"]
    assert v["timeline"] and v["energy"] and e["load"]["total"] is not None and e["tomorrow"]["effects"]
    assert set(e["notes"]) >= {"intro", "day", "load", "tomorrow", "week", "tonight"}


def test_day_today_for_the_training_tab(client, db_session):
    """Trénink: the day so far — timeline, load outside training vs the usual day, and
    readiness from the morning to now with the day outside training (v0.10.4)."""
    rid = register(client, "dayview@test.cz", "Den", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    seed_runs(db_session, rid, days=60)
    seed_details(db_session, rid, days=14)
    t = E.today_date().isoformat()
    rows = db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.nt_load.isnot(None)).all()
    next(x for x in rows if x.date == t).nt_load = max(x.nt_load for x in rows) + 300      # a day on the feet
    db_session.commit()
    E.recompute_assessment(db_session, rid)
    d = client.get(f"/api/runners/{rid}/day-today").json()
    assert d["date"] == t and d["view"]["timeline"] and d["view"]["activeMin"] > 0
    assert d["load"]["excess"] > 250 and d["load"]["usualNt"] is not None
    rd = d["readiness"]
    assert rd["dayDrop"] > 0 and rd["now"] == rd["morning"] - rd["sessionDrop"] - rd["dayDrop"]
    assert rd["nt"]["excess"] > 250
    # someone else's day stays private
    register(client, "other-day@test.cz", "Jiný", "runner")
    assert client.get(f"/api/runners/{rid}/day-today").status_code == 403
