"""Engine prevention plan (Documentation/engine prevention plan.pdf).
A: function over pain numbers, acute overload after a run, recovery after races,
   a risk label consistent with the state, a prior injury without a date.
B: pain monitoring, injury report → history → graded return, race calendar
   (capacity from confirmed load only is in test_capacity.py).
C: generic rules for the first 6 weeks, measured HR max, validation replay."""
from datetime import timedelta

from app import models
from app.metrics import engine as E
from .conftest import register
from .synth import seed_runs


def _runner(client, db, email, mode="v3", p_run=0.55):
    rid = register(client, email, "Prevent Runner", "runner").json()["runner_id"]
    seed_runs(db, rid, days=100, p_run=p_run)
    db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at == E.day_ago(0)).delete()
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = mode
    db.commit()
    return rid, r


def _checkin(db, rid, days_ago=0, **kw):
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(days_ago), **kw))
    db.commit()


def _assess(db, rid):
    return E.recompute_assessment(db, rid)


GROIN = [{"region": "Tříslo / úpon adduktorů (L)"}]


# ---------------------------------------------------------------- A1 function
def test_pain_that_limits_movement_is_injury_level_whatever_the_number(client, db_session):
    rid, _ = _runner(client, db_session, "pa1@test.cz")
    _checkin(db_session, rid, pain_score=2, pain_points=GROIN, limits_movement=True)
    a = _assess(db_session, rid)
    assert a["functionLimit"]["severe"] and a["tier"] == "alert" and E.triage_decision(a) == "physio_48h"
    assert any(s["id"] == "function" for s in a["signals"])
    g = a["guidance"]
    assert g["type"] == "volno" and g["override"]["kind"] == "function"
    assert not any(g["types"][k]["allowed"] for k in ("regenerace", "lehký", "dlouhý", "kvalitní"))


def test_a_run_changed_because_of_pain_modifies_training(client, db_session):
    rid, _ = _runner(client, db_session, "pa2@test.cz")
    _checkin(db_session, rid, pain_score=2, pain_points=GROIN, run_modified=True)
    a = _assess(db_session, rid)
    assert not a["functionLimit"]["severe"] and a["tier"] in ("watch", "alert")
    g = a["guidance"]
    assert g["override"] is None and not g["types"]["dlouhý"]["allowed"] and not g["types"]["kvalitní"]["allowed"]


def test_limitation_outside_running_doesnt_stop_running(client, db_session):
    rid, _ = _runner(client, db_session, "pa3@test.cz")
    _checkin(db_session, rid, pain_score=3, pain_points=[{"region": "Rameno (P)"}], limits_movement=True)
    assert _assess(db_session, rid)["functionLimit"] is None


def test_checkin_endpoint_stores_the_function_answers(client, db_session):
    rid = register(client, "pa4@test.cz", "Api", "runner").json()["runner_id"]
    client.post("/api/auth/session", json={"email": "pa4@test.cz", "password": "testpass123"})
    r = client.post(f"/api/runners/{rid}/checkins", json={"pain_score": 2, "pain_points": GROIN, "limping": True})
    assert r.status_code == 200
    db_session.expire_all()
    c = db_session.query(models.Checkin).filter(models.Checkin.runner_id == rid).first()
    assert (c.limping, c.limits_movement, c.run_modified) == (True, None, None)


# ---------------------------------------------------------------- A2 acute overload
def test_acute_overload_after_a_run_rests_then_eases_then_expires(client, db_session):
    rid, _ = _runner(client, db_session, "pa5@test.cz")
    _checkin(db_session, rid, days_ago=1, pain_score=2, soreness=8,
             pain_points=GROIN + [{"region": "Chodidlo – nárt (P)"}, {"region": "Prsty / metatarzy (P)"}])
    a = _assess(db_session, rid)
    assert a["acuteOverload"]["daysSince"] == 1 and "bolest na 3 místech" in a["acuteOverload"]["reasons"]
    assert a["guidance"]["override"]["kind"] == "acute" and a["tier"] != "ok"
    db_session.query(models.Checkin).filter(models.Checkin.runner_id == rid).update({"submitted_at": E.day_ago(3)})
    db_session.commit()
    g = _assess(db_session, rid)["guidance"]
    assert g["override"] is None and not g["types"]["kvalitní"]["allowed"] and not g["types"]["dlouhý"]["allowed"]
    db_session.query(models.Checkin).filter(models.Checkin.runner_id == rid).update({"submitted_at": E.day_ago(5)})
    db_session.commit()
    assert _assess(db_session, rid)["acuteOverload"] is None


def test_rpe_10_with_pain_in_a_run_rating_is_acute(client, db_session):
    rid, _ = _runner(client, db_session, "pa6@test.cz")
    act = db_session.query(models.Activity).filter(models.Activity.runner_id == rid).order_by(models.Activity.started_at.desc()).first()
    db_session.add(models.ActivityFeedback(activity_id=act.id, runner_id=rid, submitted_at=E.day_ago(0), rpe=10,
                                           pain_during=2, pain_points=GROIN))
    db_session.commit()
    a = _assess(db_session, rid)
    assert "námaha 10/10 s bolestí" in a["acuteOverload"]["reasons"]


# ---------------------------------------------------------------- A3 race recovery
def _race(db, rid, days_ago, km=21.1, pace=300, title="Usti Half Marathon", hr=150):
    a = models.Activity(runner_id=rid, provider="garmin", external_id=f"race-{days_ago}-{km}", started_at=E.day_ago(days_ago),
                        sport="running", title=title, distance_km=km, duration_min=km * pace / 60, pace_s_km=pace,
                        avg_hr=hr, surface="road", ascent_m=20, descent_m=20)
    db.add(a)
    db.commit()
    return a


def test_a_half_marathon_race_gets_a_recovery_block(client, db_session):
    rid, _ = _runner(client, db_session, "pa7@test.cz")
    _race(db_session, rid, 1)
    a = _assess(db_session, rid)
    rr = a["raceRecovery"]
    assert rr and rr["days"] == 7 and rr["restDays"] == 3 and "závod" in rr["why"]
    g = a["guidance"]
    assert g["type"] == "volno" and not g["types"]["lehký"]["allowed"] and not g["types"]["kvalitní"]["allowed"]
    assert any("Zotavení po závodním úsilí" in x and "den 2 z 7" in x for x in g["reasons"])
    db_session.query(models.Activity).filter(models.Activity.external_id == "race-1-21.1").update({"started_at": E.day_ago(4)})
    db_session.commit()
    g = _assess(db_session, rid)["guidance"]            # after the rest days: the race rule no longer blocks easy runs,
    assert "první dny" not in (g["types"]["lehký"]["why"] or "")                    # but still intensity / long runs
    assert "Zotavení" in g["types"]["kvalitní"]["why"] and "Zotavení" in g["types"]["dlouhý"]["why"]


def test_a_race_pace_long_run_is_a_maximal_effort_without_a_race_title(client, db_session):
    rid, _ = _runner(client, db_session, "pa8@test.cz")
    for k in (20, 27, 34, 41):                          # usual long runs at ~6:30/km
        _race(db_session, rid, k, km=16, pace=390, title="Long run")
    _race(db_session, rid, 2, km=21.1, pace=293, title="Prague Running")   # 4:53/km
    efforts = _assess(db_session, rid)["maxEfforts"]
    fast = next(e for e in efforts if e["km"] == 21.1)
    assert any("rychlejší než vaše obvyklé dlouhé běhy" in w for w in fast["why"])
    assert all(e["km"] != 16 for e in efforts)          # the usual long runs are not "maximal"


# ---------------------------------------------------------------- A4 label follows the state
def test_risk_label_never_contradicts_the_state(client, db_session):
    rid, _ = _runner(client, db_session, "pa9@test.cz", p_run=0.75)
    for k in range(0, 4):                               # a sharp volume jump, nothing else wrong
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"jump{k}", started_at=E.day_ago(k),
                                       sport="running", title="Navíc", distance_km=24.0, duration_min=24 * 6,
                                       avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    db_session.commit()
    a = _assess(db_session, rid)
    assert a["quadrant"] in ("overreaching", "critical") and a["tier"] != "ok"


# ---------------------------------------------------------------- A5 prior injury
def test_prior_injury_without_a_date_counts_as_recent(client, db_session):
    rid, r = _runner(client, db_session, "pa10@test.cz")
    r.prior_injury = "ITB"
    db_session.commit()
    assert E.injury_months(r) == E.PRIOR_UNKNOWN_MONTHS
    a = _assess(db_session, rid)
    hist = next(s for s in a["signals"] if s["id"] == "hist")
    assert hist["val"] == "datum neznámé" and "doplňte ho v profilu" in hist["detail"]
    r.prior_injury_date, r.prior_injury_side = E.day_ago(150), "right"
    db_session.commit()
    assert E.injury_months(r) == 5
    hist = next(s for s in _assess(db_session, rid)["signals"] if s["id"] == "hist")
    assert hist["val"] == "5 měs." and "(vpravo)" in hist["detail"]


def test_profile_validates_injury_date_and_side(client, db_session):
    rid = register(client, "pa11@test.cz", "Prof", "runner").json()["runner_id"]
    client.post("/api/auth/session", json={"email": "pa11@test.cz", "password": "testpass123"})
    url = f"/api/runners/{rid}"
    assert client.patch(url, json={"patch": {"prior_injury_side": "up"}}).status_code == 422
    assert client.patch(url, json={"patch": {"prior_injury_date": "2999-01-01"}}).status_code == 422
    ok = client.patch(url, json={"patch": {"prior_injury": "ITB", "prior_injury_date": E.day_ago(150), "prior_injury_side": "right"}})
    assert ok.status_code == 200 and ok.json()["prior_injury_side"] == "right"


# ---------------------------------------------------------------- B2 pain monitoring
def _rated_run(db, rid, days_ago, pain, points=GROIN, km=8.0):
    a = _race(db, rid, days_ago, km=km, pace=360, title="Lehký běh")
    db.add(models.ActivityFeedback(activity_id=a.id, runner_id=rid, submitted_at=E.day_ago(days_ago), rpe=4,
                                   pain_during=pain, pain_points=points if pain else []))
    db.commit()
    return a


def test_pain_worse_next_morning_than_during_the_run_stops_running(client, db_session):
    rid, _ = _runner(client, db_session, "pb1@test.cz")
    _rated_run(db_session, rid, 1, pain=1)
    _checkin(db_session, rid, pain_score=3, pain_points=GROIN)
    a = _assess(db_session, rid)
    mw = a["painMonitor"]["morningWorse"]
    assert (mw["morning"], mw["during"]) == (3, 1) and "Tříslo" in mw["site"]
    assert a["tier"] != "ok" and any(s["id"] == "pain_morning" for s in a["signals"])
    g = a["guidance"]
    assert g["override"]["kind"] == "pain_monitor" and g["type"] == "volno"


def test_pain_that_settles_by_the_morning_is_fine(client, db_session):
    rid, _ = _runner(client, db_session, "pb2@test.cz")
    _rated_run(db_session, rid, 1, pain=3)
    _checkin(db_session, rid, pain_score=2, pain_points=GROIN)
    a = _assess(db_session, rid)
    assert (a["painMonitor"] or {}).get("morningWorse") is None
    assert (a["guidance"]["override"] or {}).get("kind") != "pain_monitor"


def test_morning_pain_at_a_site_the_run_didnt_hurt_counts_as_worse(client, db_session):
    rid, _ = _runner(client, db_session, "pb3@test.cz")
    _rated_run(db_session, rid, 1, pain=2, points=[{"region": "Koleno – zevní strana / ITB (P)"}])
    _checkin(db_session, rid, pain_score=2, pain_points=GROIN)
    assert _assess(db_session, rid)["painMonitor"]["morningWorse"]["during"] == 0


def test_pain_rising_week_to_week_modifies_training(client, db_session):
    rid, _ = _runner(client, db_session, "pb4@test.cz")
    for k in (9, 11):
        _checkin(db_session, rid, days_ago=k, pain_score=1, pain_points=GROIN)
    for k in (2, 4):
        _checkin(db_session, rid, days_ago=k, pain_score=3, pain_points=GROIN)
    a = _assess(db_session, rid)
    tr = a["painMonitor"]["trend"]
    assert (tr["before"], tr["now"]) == (1.0, 3.0) and a["tier"] != "ok"
    g = a["guidance"]
    assert not g["types"]["dlouhý"]["allowed"] and "roste týden od týdne" in g["types"]["kvalitní"]["why"]


def test_no_trend_without_reports_the_week_before(client, db_session):
    rid, _ = _runner(client, db_session, "pb5@test.cz")
    for k in (2, 4):
        _checkin(db_session, rid, days_ago=k, pain_score=3, pain_points=GROIN)
    assert (_assess(db_session, rid)["painMonitor"] or {}).get("trend") is None


# ---------------------------------------------------------------- B3 injury → history → graded return
def _login(client, email):
    client.post("/api/auth/session", json={"email": email, "password": "testpass123"})


def test_a_reported_injury_becomes_the_injury_history(client, db_session):
    rid, r = _runner(client, db_session, "pc1@test.cz")
    _login(client, "pc1@test.cz")
    body = {"kind": "adhoc", "q_participation": 17, "q_pain": 8,
            "pain_points": [{"region": "Tříslo / úpon adduktorů (L)", "side": "L"}]}
    assert client.post(f"/api/runners/{rid}/injury-report", json=body).status_code == 200
    db_session.expire_all()
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    assert "Tříslo / úpon adduktorů" in r.prior_injury and r.prior_injury_side == "left"
    assert r.prior_injury_date == E.day_ago(0)[:10]
    # the same episode reported again a week later keeps the start date
    r.prior_injury_date = E.day_ago(7)[:10]
    db_session.commit()
    client.post(f"/api/runners/{rid}/injury-report", json=body)
    db_session.expire_all()
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    assert r.prior_injury_date == E.day_ago(7)[:10] and r.prior_injury.count("Tříslo") == 1


def test_resolved_injury_returns_gradually(client, db_session):
    rid, _ = _runner(client, db_session, "pc2@test.cz")
    _login(client, "pc2@test.cz")
    client.post(f"/api/runners/{rid}/injury-report", json={"kind": "adhoc", "q_participation": 17, "q_pain": 8,
                                                          "pain_points": [{"region": "Holeň (P)", "side": "P"}]})
    db_session.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid).update({"submitted_at": E.day_ago(20)})
    db_session.commit()
    a = client.post(f"/api/runners/{rid}/injury-report", json={"resolve": True}).json()
    rt = a["returnToRun"]
    assert rt["week"] == 1 and rt["factor"] == 0.5 and rt["noQuality"] and rt["injuryAt"] == E.day_ago(20)[:10]
    g = a["guidance"]
    assert g["week"]["mode"] == "return" and not g["types"]["kvalitní"]["allowed"]
    assert any("Návrat po zranění" in x and "1. týden ze 3" in x for x in g["reasons"])
    ref = g["week"]["cycle"]["refKm"]
    assert ref and g["week"]["channels"]["volume"]["budget"] <= 0.5 * ref + 0.1
    for back, wk, q in ((8, 2, True), (15, 3, False)):
        db_session.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid).update({"resolved_at": E.day_ago(back)[:10]})
        db_session.commit()
        rt = _assess(db_session, rid)["returnToRun"]
        assert rt["week"] == wk and rt["noQuality"] is q
    db_session.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid).update({"resolved_at": E.day_ago(22)[:10]})
    db_session.commit()
    assert _assess(db_session, rid)["returnToRun"] is None


# ---------------------------------------------------------------- B4 race calendar
def test_race_calendar_crud_and_goal_race_compatibility(client, db_session):
    rid, r = _runner(client, db_session, "pd1@test.cz")
    _login(client, "pd1@test.cz")
    r.goal_race, r.goal_date = "Podzimní maraton", E.day_ago(-40)[:10]
    db_session.commit()
    races = client.get(f"/api/runners/{rid}/races").json()
    assert [(x["id"], x["priority"], x["source"]) for x in races] == [("goal", "A", "profile")]
    url = f"/api/runners/{rid}/races"
    assert client.post(url, json={"date": "not-a-date"}).status_code == 422
    assert client.post(url, json={"date": E.day_ago(-10)[:10], "priority": "X"}).status_code == 422
    assert client.post(url, json={"date": E.day_ago(-10)[:10], "distance_km": 0}).status_code == 422
    out = client.post(url, json={"date": E.day_ago(-10)[:10], "name": "Desítka", "distance_km": 10, "priority": "C"}).json()
    assert [x["name"] for x in out["races"]] == ["Desítka", "Podzimní maraton"]
    assert out["assessment"]["races"]["next"]["name"] == "Desítka"
    assert out["assessment"]["races"]["nextA"]["name"] == "Podzimní maraton"
    # a calendar race on the profile's goal day replaces the profile entry
    out = client.post(url, json={"date": E.day_ago(-40)[:10], "name": "Maraton", "priority": "A"}).json()
    assert [x["source"] for x in out["races"]] == ["calendar", "calendar"]
    db_session.expire_all()
    assert db_session.query(models.Runner).filter(models.Runner.id == rid).first().goal_date is None
    rid_c = next(x["id"] for x in out["races"] if x["name"] == "Desítka")
    out = client.delete(f"{url}/{rid_c}").json()
    assert [x["name"] for x in out["races"]] == ["Maraton"]
    assert client.delete(f"{url}/999999").status_code == 404


def test_an_a_race_drives_the_taper_and_blocks_the_long_run_the_week_before(client, db_session):
    rid, _ = _runner(client, db_session, "pd2@test.cz")
    db_session.add(models.Race(runner_id=rid, date=E.day_ago(-6)[:10], name="Půlmaraton", distance_km=21.1, priority="A"))
    db_session.commit()
    g = _assess(db_session, rid)["guidance"]
    assert g["week"]["mode"] == "taper" and not g["types"]["dlouhý"]["allowed"]
    assert any("Půlmaraton za 6 dní" in x for x in g["reasons"])


def test_a_c_race_doesnt_taper_but_is_still_race_day(client, db_session):
    rid, _ = _runner(client, db_session, "pd3@test.cz")
    db_session.add(models.Race(runner_id=rid, date=E.day_ago(-5)[:10], name="Parkrun", priority="C"))
    db_session.commit()
    assert _assess(db_session, rid)["guidance"]["week"]["mode"] != "taper"
    db_session.query(models.Race).filter(models.Race.runner_id == rid).update({"date": E.day_ago(0)[:10]})
    db_session.commit()
    g = _assess(db_session, rid)["guidance"]
    assert g["type"] == "závod"


def test_a_race_soon_after_a_maximal_effort_is_flagged(client, db_session):
    rid, _ = _runner(client, db_session, "pd4@test.cz")
    _race(db_session, rid, 7)                                       # a half marathon a week ago
    db_session.add(models.Race(runner_id=rid, date=E.day_ago(-7)[:10], name="Druhý půlmaraton", priority="A"))
    db_session.commit()
    a = _assess(db_session, rid)
    w = next(w for w in a["races"]["warnings"] if w["kind"] == "effort_before")
    assert w["gap"] == 14 and "Druhý půlmaraton" in w["text"] and "maximálním úsilí" in w["text"]
    assert any("maximálním úsilí" in x for x in a["guidance"]["reasons"])


def test_race_day_with_recent_pain_warns_and_an_override_still_wins(client, db_session):
    rid, _ = _runner(client, db_session, "pd5@test.cz")
    db_session.add(models.Race(runner_id=rid, date=E.day_ago(0)[:10], name="Závod", priority="B"))
    db_session.commit()
    _checkin(db_session, rid, days_ago=3, pain_score=3, pain_points=GROIN)
    a = _assess(db_session, rid)
    w = next(w for w in a["races"]["warnings"] if w["kind"] == "race_day")
    assert "bolest 3/10" in w["text"]
    g = a["guidance"]
    assert g["type"] == "závod" and w["text"] in g["types"]["závod"]["notes"]
    _checkin(db_session, rid, pain_score=2, pain_points=GROIN, limping=True)      # limping on race morning
    g = _assess(db_session, rid)["guidance"]
    assert g["type"] == "volno" and g["override"]["kind"] == "function" and not g["types"]["závod"]["allowed"]


# ---------------------------------------------------------------- C1 the first 6 weeks
def test_a_new_runner_gets_generic_rules_and_only_volume_limits(client, db_session):
    rid = register(client, "pe1@test.cz", "New Runner", "runner").json()["runner_id"]
    seed_runs(db_session, rid, days=20, p_run=0.6)
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    r.cycle_override = {"week": E.today_date().isoformat(), "pos": 4}        # a manual pick is ignored
    db_session.commit()
    g = _assess(db_session, rid)["guidance"]
    wk = g["week"]
    assert wk["novice"]["days"] == 20 and wk["mode"] == "learning" and not wk["cycle"]["manual"]
    last_week = wk["cycle"]["weeks"][3]["km"]
    assert last_week and abs(wk["channels"]["volume"]["budget"] - 1.1 * last_week) < 0.2
    for c in ("intensity", "descent", "ascent", "systemic"):
        assert wk["channels"][c]["budget"] is None and wk["channels"][c]["todayMax"] is None
    assert "Kapacitu intenzity" not in (g["types"]["kvalitní"]["why"] or "")
    assert g["types"]["kvalitní"]["z4Max"] == 10
    assert g["types"]["dlouhý"]["km"]["hi"] <= 11.0                       # all runs were 10 km
    assert any("Prvních 6 týdnů" in x for x in g["reasons"])


def test_after_six_weeks_the_personal_model_takes_over(client, db_session):
    rid, _ = _runner(client, db_session, "pe2@test.cz")
    assert _assess(db_session, rid)["guidance"]["week"]["novice"] is None


# ---------------------------------------------------------------- C2 measured HR max
def test_a_measured_hr_max_replaces_the_estimate(client, db_session):
    rid, r = _runner(client, db_session, "pf1@test.cz")
    _login(client, "pf1@test.cz")
    url = f"/api/runners/{rid}"
    assert client.patch(url, json={"patch": {"hr_max": 300}}).status_code == 422
    assert client.patch(url, json={"patch": {"hr_max": "abc"}}).status_code == 422
    est = _assess(db_session, rid)["capacity"]
    assert est["hrMaxMeasured"] is False
    assert client.patch(url, json={"patch": {"hr_max": 201}}).status_code == 200
    db_session.expire_all()
    cap = _assess(db_session, rid)["capacity"]
    assert cap["hrMaxMeasured"] is True and cap["hrMax"] == 201 and cap["zones"] != est["zones"]
    assert client.patch(url, json={"patch": {"hr_max": None}}).status_code == 200
    # never below the hardest average HR actually recorded
    runs = [type("A", (), {"avg_hr": 176})()]
    assert E.hr_bounds(runs, [], None, 170)[0] == 176 and E.hr_bounds(runs, [], None, 190)[0] == 190


# ---------------------------------------------------------------- C3 validation against injuries
def test_injury_timeline_replays_with_only_the_data_known_that_morning(client, db_session):
    from app.metrics import validation as V
    rid, _ = _runner(client, db_session, "pg1@test.cz")
    inj = E.today_date() - timedelta(days=3)
    for k in range(4, 10):                               # a sharp volume jump in the week before the injury
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"v-jump{k}", started_at=E.day_ago(k),
                                       sport="running", title="Navíc", distance_km=22.0, duration_min=22 * 6,
                                       avg_hr=150, surface="road", ascent_m=40, descent_m=40))
    # a run ON the injury day must not be visible that morning
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="v-injday", started_at=inj.isoformat(),
                                   sport="running", title="Den zranění", distance_km=30.0, duration_min=180, avg_hr=150,
                                   surface="road"))
    db_session.add(models.InjuryReport(runner_id=rid, submitted_at=inj.isoformat(), source="self_adhoc", status="active",
                                       q_participation=17, q_volume=0, q_performance=0, q_pain=8, severity=25))
    db_session.commit()
    assert V.injury_dates(db_session, rid) == [inj.isoformat()]
    t = V.injury_timeline(db_session, rid, inj.isoformat(), before=14, after=2, mode="v3")
    assert [r["date"] for r in t["days"]][0] == (inj - timedelta(days=14)).isoformat() and len(t["days"]) == 17
    assert t["firstWarning"] and t["leadDays"] >= 3 and t["warnedDaysBefore"] >= 3
    day = t["onInjuryDay"]
    assert day["warned"]
    after = next(r for r in t["days"] if r["date"] == (inj + timedelta(days=1)).isoformat())
    assert day["override"] != "injury" and after["override"] == "injury"   # the report is known the next morning


def test_no_quality_session_while_the_state_is_overreaching(client, db_session):
    rid, _ = _runner(client, db_session, "pa12@test.cz")
    a = _assess(db_session, rid)
    a["quadrant"], a["load"] = "overreaching", 20             # inside the hysteresis band: under 25, still Přetížení
    from app.metrics import guidance as G
    g = G.build_guidance(db_session, rid, a, db_session.query(models.Runner).filter(models.Runner.id == rid).first())
    assert not g["types"]["kvalitní"]["allowed"] and g["type"] != "kvalitní"


# ---------------------------------------------------------------- feedback railway#36 / #32
def test_an_excluded_activity_counts_nowhere_and_can_be_restored(client, db_session):
    rid, _ = _runner(client, db_session, "ph1@test.cz")
    _login(client, "ph1@test.cz")
    base = _assess(db_session, rid)
    big = models.Activity(runner_id=rid, provider="garmin", external_id="gps-glitch", started_at=E.day_ago(1),
                          sport="running", title="Chyba GPS", distance_km=48.0, duration_min=48 * 6, avg_hr=150,
                          surface="road", ascent_m=40, descent_m=40)
    db_session.add(big)
    db_session.commit()
    jumped = _assess(db_session, rid)
    assert jumped["load"] > base["load"]
    r = client.post(f"/api/runners/{rid}/activities/{big.id}/exclude", json={"excluded": True}).json()
    assert r["excluded"] is True and r["assessment"]["load"] == base["load"]
    assert big.id not in [x["id"] for x in client.get(f"/api/runners/{rid}/activities/unrated").json()]
    hist = client.get(f"/api/runners/{rid}/run-history?limit=5").json()
    assert next(x for x in hist if x["id"] == big.id)["excluded"] is True          # still listed, to restore
    r = client.post(f"/api/runners/{rid}/activities/{big.id}/exclude", json={"excluded": False}).json()
    assert r["assessment"]["load"] == jumped["load"]
    assert client.post(f"/api/runners/{rid}/activities/999999/exclude", json={"excluded": True}).status_code == 404


def test_the_weekly_longest_run_ceiling_ignores_todays_readiness(client, db_session):
    rid, _ = _runner(client, db_session, "ph2@test.cz")
    vol = _assess(db_session, rid)["capacity"]["channels"]["volume"]
    m = _assess(db_session, rid)["capacity"]["margins"]["session"]
    assert abs(vol["ceilingSession"] - vol["capSession"] * (1 + m)) <= 0.1 and vol["ceilingSession"] >= vol["ceilingToday"]
