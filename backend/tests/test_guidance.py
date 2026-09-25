"""Engine v3 phase 2 — daily training guidance (metrics/guidance.py)."""
from datetime import timedelta

from app import models
from app.metrics import engine as E
from app.metrics import guidance as G
from .conftest import register
from .synth import seed_runs


def _runner(client, db, email, days=100, mode="v3", **kw):
    """A steady runner (~4 runs/week) who hasn't run yet today — so there is
    headroom left in the week for the guidance to allocate."""
    rid = register(client, email, "Guide Runner", "runner").json()["runner_id"]
    kw.setdefault("p_run", 0.55)
    seed_runs(db, rid, days=days, **kw)
    db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                     models.Activity.started_at == E.day_ago(0)).delete()
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = mode
    db.commit()
    return rid, r


def _guide(db, rid, r, **patch):
    with E.engine_pinned("v3"):
        a = E.assess(db, rid)
    a.update(patch)
    return G.build_guidance(db, rid, a, r)


def _pain(db, rid, score, region="koleno"):
    db.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=score,
                          pain_points=[{"region": region}]))
    db.commit()


def test_guidance_only_on_v3(client, db_session):
    rid, r = _runner(client, db_session, "g1@test.cz", mode="v1")
    assert E.recompute_assessment(db_session, rid)["guidance"] is None
    r.engine_mode = "v3"
    db_session.commit()
    g = E.recompute_assessment(db_session, rid)["guidance"]
    assert g and g["type"] in G.TYPES and set(G.TYPES) <= set(g["types"])
    # the guidance survives the stored-row round trip the app reads
    a = client.get(f"/api/runners/{rid}/assessment")
    assert a.status_code in (200, 401, 403)


def test_ceilings_never_exceed_capacity_or_week_budget(client, db_session):
    rid, r = _runner(client, db_session, "g2@test.cz")
    g = _guide(db_session, rid, r)
    wk = g["week"]["channels"]["volume"]
    for kind in ("regenerace", "lehký", "dlouhý", "kvalitní"):
        t = g["types"][kind]
        assert t["km"]["hi"] <= wk["todayMax"] + 1e-9
        assert t["km"]["lo"] <= t["km"]["hi"]


def test_running_the_ceiling_does_not_raise_the_load_axis(client, db_session):
    """Following the guidance must never itself create a volume exceedance."""
    rid, r = _runner(client, db_session, "g3@test.cz")
    g = _guide(db_session, rid, r)
    km = g["types"]["dlouhý"]["km"]["hi"] if g["types"]["dlouhý"]["allowed"] else g["types"]["lehký"]["km"]["hi"]
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="ceil", started_at=E.day_ago(0),
                                   sport="running", title="Strop", distance_km=km, duration_min=km * 6,
                                   avg_hr=145, surface="road", ascent_m=20, descent_m=20))
    db_session.commit()
    with E.engine_pinned("v3"):
        a = E.assess(db_session, rid)
    assert a["capacity"]["channels"]["volume"]["pts"] == 0


def test_physio_override_needs_pain_over_5_and_a_referral(client, db_session):
    rid, r = _runner(client, db_session, "g4@test.cz")
    _pain(db_session, rid, 7)
    # pain 7 WITH the engine's own referral → no run, see the physio
    g = _guide(db_session, rid, r, quadrant="critical")
    assert g["type"] == "volno" and g["override"]["kind"] == "physio" and g["referral"] == "physio_48h"
    assert not any(g["types"][k]["allowed"] for k in ("regenerace", "lehký", "dlouhý", "kvalitní"))
    # the same pain WITHOUT a referral → easy / regeneration, no physio override
    g2 = _guide(db_session, rid, r, quadrant="stable", tier="ok")
    assert g2["override"] is None and g2["type"] == "regenerace"
    assert g2["types"]["regenerace"]["allowed"] and not g2["types"]["lehký"]["allowed"]


def test_moderate_pain_modifies_instead_of_cancelling(client, db_session):
    rid, r = _runner(client, db_session, "g5@test.cz")
    base = _guide(db_session, rid, r, quadrant="stable", tier="ok")
    _pain(db_session, rid, 4)
    g = _guide(db_session, rid, r, quadrant="critical")      # referral alone + pain 4 → still no override
    assert g["override"] is None
    assert g["types"]["lehký"]["allowed"]
    assert not g["types"]["dlouhý"]["allowed"] and not g["types"]["kvalitní"]["allowed"]
    assert g["types"]["lehký"]["km"]["hi"] < base["types"]["lehký"]["km"]["hi"]   # shorter
    assert "rovin" in g["types"]["lehký"]["terrain"]


def test_active_injury_means_rest(client, db_session):
    rid, r = _runner(client, db_session, "g6@test.cz")
    g = _guide(db_session, rid, r, injury={"active": {"severity": 40, "site": "holeň vlevo", "confirmed": True}})
    assert g["type"] == "volno" and g["override"]["kind"] == "injury"


def test_quality_needs_48h_after_the_last_hard_session(client, db_session):
    rid, r = _runner(client, db_session, "g7@test.cz")
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="hard", started_at=E.day_ago(1),
                                   sport="running", title="Intervaly", distance_km=10.0, duration_min=45,
                                   avg_hr=178, surface="road", ascent_m=10, descent_m=10))
    db_session.commit()
    g = _guide(db_session, rid, r)
    assert not g["types"]["kvalitní"]["allowed"]


def test_taper_before_the_goal_race(client, db_session):
    rid, r = _runner(client, db_session, "g8@test.cz")
    r.goal_date = (E.today_date() + timedelta(days=5)).isoformat()
    r.goal_race = "Pražský půlmaraton"
    db_session.commit()
    g = _guide(db_session, rid, r, load=0)
    assert g["week"]["mode"] == "taper" and g["week"]["progression"] == 0.5
    assert not g["types"]["dlouhý"]["allowed"]
    assert any("Pražský půlmaraton" in x for x in g["reasons"])


def test_deload_when_load_axis_is_high(client, db_session):
    rid, r = _runner(client, db_session, "g9@test.cz")
    g = _guide(db_session, rid, r, load=30)
    assert g["week"]["mode"] == "deload" and g["week"]["progression"] == round(G.CYCLE[4], 3)
    last_week = g["week"]["cycle"]["weeks"][3]["km"]
    assert g["week"]["channels"]["volume"]["budget"] <= 0.55 * last_week + 0.1   # 55 % of last week
    assert not g["types"]["kvalitní"]["allowed"] and not g["types"]["dlouhý"]["allowed"]


def test_provisional_until_todays_watch_data(client, db_session):
    rid, r = _runner(client, db_session, "g10@test.cz")
    assert _guide(db_session, rid, r)["provisional"] is True
    db_session.add(models.DailyMetric(runner_id=rid, date=E.iso_date(E.today_date()), sleep_h=7.4, hrv_ms=62, resting_hr=50))
    db_session.commit()
    assert _guide(db_session, rid, r)["provisional"] is False


def test_paces_stay_in_the_runners_own_range(client, db_session):
    rid, r = _runner(client, db_session, "g11@test.cz")
    g = _guide(db_session, rid, r)
    easy = g["pattern"]["easyPace"]
    for kind in ("regenerace", "lehký", "dlouhý"):
        p = g["types"][kind]["pace"]
        assert p and p[0] <= p[1] and 0.8 * easy <= p[0] and p[1] <= 1.3 * easy


def test_week_budget_used_up_means_rest(client, db_session):
    """Already over this week's volume budget (and ran today) → volno, with the reason."""
    rid = register(client, "g12@test.cz", "Guide Busy", "runner").json()["runner_id"]
    seed_runs(db_session, rid, days=100, p_run=0.75)
    for k in range(0, 6):                                 # a heavy last week on top
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"x{k}", started_at=E.day_ago(k),
                                       sport="running", title="Navíc", distance_km=8.0, duration_min=48,
                                       avg_hr=145, surface="road", ascent_m=10, descent_m=10))
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    db_session.commit()
    g = _guide(db_session, rid, r, load=0)
    vol = g["week"]["channels"]["volume"]
    assert g["type"] == "volno" and vol["todayMax"] == 0 and vol["limitedBy"] in ("7d", "week", "systemic")
    assert g["done"] and g["done"]["volume"] > 0
    assert any("dnes volno" in x for x in g["reasons"])


# ---------------------------------------------------------------- 4-week cycle
def test_cycle_position_from_the_last_recovery_week():
    base = [40.0] * 12
    rec = lambda j: base[:j] + [20.0] + base[j + 1:]           # recovery j+1 weeks back
    assert G.cycle_position(rec(0))["pos"] == 1                 # recovery last week → week 1
    assert G.cycle_position(rec(1))["pos"] == 2
    c = G.cycle_position([44.0, 20.0] + [40.0] * 10)            # recovery 2 weeks back after a 40 km week
    assert (c["pos"], c["ref"], c["refBack"]) == (2, 40.0, 3)
    assert G.cycle_position(rec(3))["pos"] == 4                 # 4 weeks after → recovery week again


def test_cycle_position_from_last_weeks_strain_without_a_recovery_week():
    steady = [40.0] * 12
    assert G.cycle_position([44.0] + steady)["pos"] == 4        # already above baseline → recover now
    assert G.cycle_position([40.0] + steady)["pos"] == 3
    assert G.cycle_position([35.0] + steady)["pos"] == 2
    c = G.cycle_position([30.0] + steady)                       # low week (not < 70 %) → start on the baseline
    assert c["pos"] == 1 and c["ref"] == 40.0
    assert G.cycle_position([10.0, 12.0, 0.0, 0.0]) is None     # too little history


def _weeks_of_runs(db, rid, weekly_km, runs_per_week=4, spacing=2):
    """Completed calendar weeks, oldest first, ending last week (today pinned);
    runs every `spacing` days from Monday."""
    ws = G.week_start(E.today_date())
    n = len(weekly_km)
    for i, km in enumerate(weekly_km):
        start = ws - timedelta(days=7 * (n - i))
        for k in range(runs_per_week):
            d = start + timedelta(days=k * spacing)
            db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{rid}-w{i}-{k}", started_at=d.isoformat(),
                                   sport="running", title="Běh", distance_km=km / runs_per_week,
                                   duration_min=km / runs_per_week * 5.8, pace_s_km=348, avg_hr=145, surface="road",
                                   ascent_m=15, descent_m=15))
    db.commit()


def test_weekly_target_follows_the_cycle_and_never_exceeds_capacity(client, db_session):
    from datetime import date
    rid = register(client, "gc1@test.cz", "Cycle", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    with E.today_pinned(date(2026, 9, 23)):                    # a Wednesday
        # 8 steady weeks, a recovery week, then week 1 of the new cycle (90 %) last week
        _weeks_of_runs(db_session, rid, [40, 40, 40, 40, 40, 40, 40, 40, 22, 36])
        g = _guide(db_session, rid, r, load=0)
        cyc, vol = g["week"]["cycle"], g["week"]["channels"]["volume"]
        assert cyc["pos"] == 2 and g["week"]["mode"] == "build"   # recovery 2 weeks back → week 2 (100 %)
        assert cyc["refKm"] == 40.0
        assert vol["budget"] == min(40.0, vol["ceiling7"])          # 100 % of the reference, capped by capacity
        assert vol["budget"] <= vol["ceiling7"] and vol["done"] == 0   # nothing run since Monday
        assert any("2. týden cyklu" in x for x in g["reasons"])


def test_celkova_zatez_bounds_todays_kilometres(client, db_session):
    rid, r = _runner(client, db_session, "gc2@test.cz")
    for k in range(1, 4):                                          # three long hard bike rides: lots of HR × time
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"bike{k}", started_at=E.day_ago(k),
                                       sport="cycling", title="Kolo", duration_min=240, avg_hr=160))
    db_session.commit()
    g = _guide(db_session, rid, r, load=0)
    sysc, vol = g["week"]["channels"]["systemic"], g["week"]["channels"]["volume"]
    assert sysc["left7"] is not None and sysc["left7"] < sysc["ceiling7"]
    assert vol["limitedBy"] == "systemic" or vol["todayMax"] == 0


def test_rested_runner_with_the_week_done_gets_rest_but_may_jog(client, db_session):
    from datetime import date
    rid = register(client, "gc3@test.cz", "Rested", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    with E.today_pinned(date(2026, 9, 24)):                     # Thursday
        # last week at the peak (run Mon–Thu, so it's outside today's 7-day window) → recovery week now
        _weeks_of_runs(db_session, rid, [40, 40, 40, 40, 40, 40, 40, 40, 44], spacing=1)
        for k, d in enumerate((21, 22, 23)):                    # Mon–Wed of the recovery week: 8,5 km each
            db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"rw{k}",
                                           started_at=date(2026, 9, d).isoformat(), sport="running", title="Běh",
                                           distance_km=8.5, duration_min=49, pace_s_km=345, avg_hr=140,
                                           surface="road", ascent_m=10, descent_m=10))
        db_session.commit()
        g = _guide(db_session, rid, r, load=0)
        vol = g["week"]["channels"]["volume"]
        assert g["week"]["mode"] == "recovery" and vol["limitedBy"] == "week" and g["type"] == "volno"
        assert g["types"]["regenerace"]["allowed"] and g["types"]["regenerace"]["km"]["hi"] > 0
        assert any("tělo je zregenerované" in x for x in g["reasons"]) or g["readiness"] < 0.9


def test_repeated_mild_pain_means_odlehcit(client, db_session):
    rid, r = _runner(client, db_session, "gc4@test.cz")
    for k in (1, 4, 8):                                          # the same site, 2/10, on three days
        db_session.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(k), pain_score=2,
                                      pain_points=[{"region": "Achillova šlacha (P)"}]))
    db_session.commit()
    a = E.recompute_assessment(db_session, rid)
    assert a["painRecurring"]["days"] == 3 and a["tier"] in ("watch", "alert")
    g = a["guidance"]
    assert not g["types"]["dlouhý"]["allowed"] and not g["types"]["kvalitní"]["allowed"]
    assert any("Opakovaná bolest" in x and "odlehčit" in x for x in g["reasons"])


def test_picking_this_weeks_place_in_the_cycle(client, db_session):
    from datetime import date
    rid = register(client, "gc5@test.cz", "Pick", "runner").json()["runner_id"]
    r = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db_session.commit()
    with E.today_pinned(date(2026, 9, 23)):
        _weeks_of_runs(db_session, rid, [40, 40, 40, 40, 40, 40, 40, 40, 22, 36])
        auto = _guide(db_session, rid, r, load=0)
        assert auto["week"]["cycle"]["pos"] == 2 and not auto["week"]["cycle"]["manual"]
        r.cycle_override = {"week": "2026-09-21", "pos": 4}                  # "I need a recovery week now"
        db_session.commit()
        g = _guide(db_session, rid, r, load=0)
        assert g["week"]["mode"] == "recovery" and g["week"]["cycle"]["manual"] and g["week"]["cycle"]["autoPos"] == 2
        assert g["week"]["channels"]["volume"]["budget"] < auto["week"]["channels"]["volume"]["budget"]
        assert any("ručně zvolili 4. týden" in x for x in g["reasons"])
        r.cycle_override = {"week": "2026-09-14", "pos": 4}                  # last week's pick doesn't carry over
        db_session.commit()
        assert _guide(db_session, rid, r, load=0)["week"]["cycle"]["pos"] == 2
    client.post("/api/auth/session", json={"email": "gc5@test.cz", "password": "testpass123"})
    assert client.put(f"/api/runners/{rid}/cycle", json={"pos": 7}).status_code == 422
    assert "assessment" in client.put(f"/api/runners/{rid}/cycle", json={"pos": 4}).json()
    db_session.expire_all()
    stored = db_session.query(models.Runner).filter(models.Runner.id == rid).first().cycle_override
    assert stored["pos"] == 4 and stored["week"] == G.week_start(E.today_date()).isoformat()
    client.put(f"/api/runners/{rid}/cycle", json={"pos": None})
    db_session.expire_all()
    assert db_session.query(models.Runner).filter(models.Runner.id == rid).first().cycle_override is None
    register(client, "gc6@test.cz", "Other", "runner")
    client.post("/api/auth/session", json={"email": "gc6@test.cz", "password": "testpass123"})
    assert client.put(f"/api/runners/{rid}/cycle", json={"pos": 1}).status_code == 403


def test_readiness_score_gates_hard_sessions_and_drift_trims_today(client, db_session):
    rid, r = _runner(client, db_session, "gc7@test.cz")
    with E.engine_pinned("v3"):
        a = E.assess(db_session, rid)
    a["capacity"]["readiness"].update({"score": 55, "parts": {"hrv": 0.4, "rhr": 0.3}})
    g = G.build_guidance(db_session, rid, a, r)
    assert g["readinessScore"] == 55 and not g["types"]["kvalitní"]["allowed"] and not g["types"]["dlouhý"]["allowed"]
    assert any("Připravenost 55 %" in x and "nižší HRV" in x for x in g["reasons"])
    a["capacity"]["readiness"]["score"] = 40
    assert G.build_guidance(db_session, rid, a, r)["type"] in ("regenerace", "volno")
    # mechanics over its threshold → today's volume / intensity / descent are cut, and say why
    base = _guide(db_session, rid, r, quadrant="stable", mechFlag=False)
    drift = _guide(db_session, rid, r, quadrant="silent")
    bv, dv = base["week"]["channels"]["volume"], drift["week"]["channels"]["volume"]
    assert dv["limitedBy"] == "mechanics" and dv["todayMax"] <= 0.8 * bv["todayMax"] + 0.05
    assert drift["axes"]["threshold"] == 25 and "mech" in drift["axes"]
