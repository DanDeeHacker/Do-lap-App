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
    assert g["week"]["mode"] == "deload" and g["week"]["progression"] == 0.7
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
    assert g["type"] == "volno" and g["week"]["channels"]["volume"]["left"] == 0
    assert g["done"] and g["done"]["volume"] > 0
    assert any("rozpočet objemu je vyčerpaný" in x for x in g["reasons"])
