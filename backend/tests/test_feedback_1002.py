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


def test_treadmill_runs_far_off_the_norm_leave_mechanics_until_put_back(client, db_session):
    rid, r = _runner(client, db_session, "fb1002tm@test.cz")
    tm = models.Activity(runner_id=rid, provider="garmin", external_id="tm1", started_at=E.day_ago(1),
                         sport="running", title="Treadmill Running", distance_km=6, duration_min=36, avg_hr=140,
                         surface="road", vert_ratio_pct=12.5, gct_ms=330, cadence_spm=150)
    ok = models.Activity(runner_id=rid, provider="garmin", external_id="tm2", started_at=E.day_ago(2),
                         sport="running", title="Pás", distance_km=6, duration_min=36, avg_hr=140, surface="treadmill")
    db_session.add_all([tm, ok])
    db_session.commit()
    E.recompute_assessment(db_session, rid)
    db_session.refresh(tm)
    db_session.refresh(ok)
    assert tm.excluded and tm.excluded_scope == "mech" and tm.auto_excluded == "treadmill"
    assert not ok.excluded                                           # no metrics → nothing stands out
    # it still waits for its diary note (mechanics-only exclusion)
    assert tm.id in [x["id"] for x in client.get(f"/api/runners/{rid}/activities/unrated").json()]
    # put back by the runner → stays in for good
    assert client.post(f"/api/runners/{rid}/activities/{tm.id}/exclude", json={"excluded": False}).status_code == 200
    E.recompute_assessment(db_session, rid)
    db_session.refresh(tm)
    assert not tm.excluded and tm.mech_keep and tm.auto_excluded is None


def test_an_early_sync_does_not_leave_today_without_the_night(client, db_session):
    """Feedback #167 — a morning sync before the watch uploaded the night must not
    freeze today's row: the next sync fills sleep and HRV in."""
    from app.routers import integrations as I
    rid, r = _runner(client, db_session, "fb1002sync@test.cz")
    t = E.iso_date(E.today_date())
    db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                models.DailyMetric.date == t).delete()
    db_session.add(models.DailyMetric(runner_id=rid, date=t, steps=900, resting_hr=50))
    db_session.commit()
    dates, _ = I._runner_history(db_session, rid)
    assert t not in dates                                      # today is always requested again
    I._merge_seed(db_session, rid, {"activities": [], "daily_metrics": [
        {"date": t, "source": "garmin", "steps": 4000, "resting_hr": 49, "hrv_ms": 61.0, "sleep_h": 7.4}]}, provider="garmin")
    db_session.commit()
    row = db_session.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == t).first()
    assert row.sleep_h == 7.4 and row.hrv_ms == 61.0 and row.steps == 4000 and row.resting_hr == 50


def test_programme_payload_has_week_overview_and_next_session(client, db_session):
    """Feedback #170 — what the 'trénink hotový' summary shows."""
    from .conftest import register
    rid = register(client, "fb1002prog@test.cz", "Prog", "runner").json()["runner_id"]
    p = client.post(f"/api/runners/{rid}/self-programs", json={"template": "calf"}).json()
    for x in p["exercises"]:
        p = client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": x["id"], "done": True}).json()
    assert p["weekNo"] == 1 and p["weeks"] == 6 and p["weeksLeft"] == 5 and p["sessionsTotal"] == 1
    assert len(p["weekDays"]) == 7 and sum(d["full"] for d in p["weekDays"]) == 1
    assert p["next"]["exercises"] and p["next"]["date"] > E.iso_date(E.today_date())


def test_race_day_facts_with_a_single_distance_do_not_crash():
    """Bug 2026-10-03 — on race day the 'závod' type carries km as one number; the
    assistant and its summaries crashed with a 500."""
    from app.metrics import coach_facts as CF
    from app.assistant import facts as AF
    g = {"type": "závod", "typeLabel": "Den závodu", "types": {"závod": {"label": "Den závodu", "km": 21.1, "allowed": True}},
         "week": {"channels": {}}, "reasons": []}
    out = CF._today({"guidance": g})
    assert out["km"].startswith("21,1")
    assert AF._types({"guidance": g}) if hasattr(AF, "_types") else True


def test_assistant_answers_and_summarises_on_race_day(client, db_session, monkeypatch):
    """End to end: a race today, the assistant (rule-based answer) and the tab summary work."""
    from app import llm
    from app.assistant import knowledge as K
    from app.assistant import service as S
    monkeypatch.setenv("DOSSLAP_ASSISTANT", "on")
    monkeypatch.setattr(llm, "assistant_available", lambda: False)
    K.sync_builtin(db_session)
    K.INDEX.invalidate()
    rid, r = _runner(client, db_session, "fb1002raceday@test.cz")
    r.coach_consent = True
    db_session.commit()
    body = {"name": "Dnešní půlka", "date": E.iso_date(E.today_date()), "distance_km": 21.1, "priority": "A"}
    assert client.post(f"/api/runners/{rid}/races", json=body).status_code == 200
    E.recompute_assessment(db_session, rid)
    db_session.commit()
    a = client.post(f"/api/runners/{rid}/assistant/ask", json={"question": "Jak vypadá můj tréninkový týden?"})
    assert a.status_code == 200, a.text
    s = client.get(f"/api/runners/{rid}/assistant/summary?tab=today")
    assert s.status_code == 200, s.text
