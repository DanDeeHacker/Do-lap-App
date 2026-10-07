"""Morning / evening report (owner request 2026-10-03)."""
import json
from datetime import date, timedelta

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
    # the ideal bedtime + fall asleep + target = wake; tonight's bed is it, or a step towards it
    im, wm, bm = DR._min_of(t["ideal"]), DR._min_of(t["wake"]), DR._min_of(t["bed"])
    assert abs((wm - im) % 1440 - (round(t["target"] * 60) + DR.FALL_ASLEEP_MIN)) <= 2
    assert t["mode"] != "ideal" or min((bm - im) % 1440, (im - bm) % 1440) <= 5
    # a hard or long run tomorrow by the week's plan → half an hour more sleep
    assert t["hardTomorrow"] == ((e["tomorrow"]["plan"] or {}).get("type") in ("kvalitní", "dlouhý", "závod")
                                 if e["tomorrow"]["plan"] else t["hardTomorrow"])
    assert "do postele kolem" in e["summary"]
    assert client.get(f"/api/runners/{rid}/report?kind=noon").status_code == 422


def test_rest_of_week_is_the_week_plan():
    """Owner request 2026-10-06: the evening's tomorrow and rest of the week come from the
    Monday sheet's planner (week_plan.py) — a simpler split here put all the week's
    kilometres on the usual hard day while the plan and the AI notes said otherwise."""
    from app.metrics import week_plan as WP
    from .test_week_plan import MON, _a
    a = _a(type="lehký")
    plan = WP.build(a, MON, None)
    out = DR._rest_of_week(plan, MON, {"left": 40.0})
    want = [d for d in plan["days"] if d["date"] > MON.isoformat()]
    assert [d["date"] for d in out["days"]] == [d["date"] for d in want] and len(want) == 6
    for d, w in zip(out["days"], want):
        assert d["items"] == w["items"]
        run = next((it for it in w["items"] if it["kind"] == "run" and not it["optional"]), None)
        if run:
            assert d["type"] == run["type"] and d["km"] == run["km"]["hi"] and d["text"].startswith(run["label"])
        elif all(it["kind"] == "rest" for it in w["items"]):
            assert d["type"] == "volno" and d["km"] is None
    ceil = a["guidance"]["planCtx"]["ceilRun"]["volume"]
    assert all((d["km"] or 0) <= ceil for d in out["days"])          # never the week's rest on one day
    # tomorrow is the plan's next day, word for word
    t = DR._tomorrow(a, None, {}, MON, None, out, {"target": 8.0}, False)
    assert t["plan"]["type"] == out["days"][0]["type"] and t["plan"]["text"] == out["days"][0]["text"]
    assert any(e["text"].startswith("Zítra podle plánu týdne: ") for e in t["effects"])
    # Sunday: the week ends; no plan: no made-up days; the week's target met
    assert DR._rest_of_week(plan, MON + timedelta(days=6), {"left": 10.0})["days"] == []
    assert DR._rest_of_week(None, MON, {"left": 10.0})["days"] == []
    assert "splněný" in DR._rest_of_week(plan, MON, {"left": 0.0})["note"]


def test_every_evening_card_names_the_same_plan():
    from app.metrics import coach_validate as V
    from app.metrics import report_ai as RA
    tmr = {"type": "volno", "label": "Volno", "km": None, "wd": "st", "text": "Volno"}
    r = {"kind": "evening", "date": "2026-10-06", "energyNow": 62, "dayView": {},
         "load": {"total": 180, "train": 120, "nt": 60, "plan": {"type": "lehký", "label": "Lehký běh",
                                                                 "afterDone": {"type": "volno", "text": "Dnes už máte hotovo."}}},
         "week": {"done": 22.4, "budget": 40}, "tonight": {"target": 8.0},
         "tomorrow": {"effects": [], "plan": tmr},
         "restOfWeek": {"days": [{"wd": "st", "text": "Volno"}, {"wd": "čt", "text": "Lehký běh 6–7,5 km"}]}}
    f = RA.facts(r)
    for card in ("intro", "load", "tomorrow", "tonight"):
        assert f[card]["zitra_plan"] == "Volno"
    assert f["week"]["navrh"] == ["st Volno", "čt Lehký běh 6–7,5 km"]
    assert f["intro"]["dnes_doporuceno"] == "Lehký běh" and "doporuceni" not in f["load"]
    # a note naming another session for tomorrow (or "the planned" run once today's is done) falls back to the rules
    plans = {"tomorrow": "volno", "today": "volno"}
    bad = "Energie teď 62 ze 100, den byl vyrovnaný. Vyspěte se a připravte se na plánovaný lehký běh."
    assert any(i["code"] == "plan_mismatch" for i in V.validate("report_card", bad, {**f["intro"], "plans": plans})["issues"])
    bad2 = "Zátěž dne 180 bodů. Zítra vás čeká dlouhý běh, tak večer odpočívejte."
    assert any(i["code"] == "plan_mismatch" for i in V.validate("report_card", bad2, {**f["load"], "plans": plans})["issues"])
    ok = "Dnes jste měli lehký běh, zítra je v plánu volno. Večer zpomalte a jděte spát včas."
    assert V.validate("report_card", ok, {**f["intro"], "plans": plans})["ok"]
    assert V.validate("report_card", "Zítra lehký běh 6–7,5 km, dnes večer klid a dost spánku.",
                      {"zitra_plan": "Lehký běh 6–7,5 km", "plans": {"tomorrow": "lehký"}})["ok"]
    # the rule-based texts say the same: intro, tomorrow
    assert "Zítra podle plánu: volno." in DR._summary_evening(None, {"total": 0}, {}, {"target": 8.0, "bed": "22:15"}, tmr)


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
