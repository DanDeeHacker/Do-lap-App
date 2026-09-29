"""Engine v0.8.4 — changes from the 2026-09 literature review.
P1: red flags (Finucane 2020), bone-stress warning signs and bone-typical pain
    (Warden 2014), illness and the fatigue / illness / performance cluster
    (Jeukendrup 2024).
P2: readiness (single night, valid nights, sleep, check-in items) is in
    test_capacity.py; the high-HRV-with-fatigue signal is here.
P3: heat (Périard 2015, Racinais 2015), hard sessions by RPE and a weekly cap
    (Seiler 2010), capacity after a break (Gabbett 2016).
P4: heart rate at the usual pace, strength habit, grade factor (Minetti 2002)."""
from types import SimpleNamespace

import pytest

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from app.metrics import guidance as G
from app.metrics import weather as W
from .conftest import register
from .test_guidance import _guide, _runner

SHIN = [{"region": "Tibialis anterior (holeň) (L)"}]
BACK = [{"region": "SI kloub / bederní úpony"}]
ACHILLES = [{"region": "Achillova šlacha (P)"}]


def _checkin(db, rid, days_ago=0, **kw):
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(days_ago), **kw))
    db.commit()


def _assess(db, rid):
    return E.recompute_assessment(db, rid)


# ---------------------------------------------------------------- P1
def test_site_helpers():
    assert E.bone_site("Tibialis anterior (holeň) (L)") and E.bone_site("Prsty / metatarzy (P)")
    assert E.bone_site("Chodidlo – nárt") and E.bone_site("Chodidlo – pata (L)")
    assert not E.bone_site("Úpon plantární fascie (pata)") and not E.bone_site("Achillova šlacha")
    assert E.back_site("SI kloub / bederní úpony") and E.back_site("Vzpřimovače páteře")
    assert not E.back_site("Zádové svaly (lats)")
    assert E.clean_checkin_flags({"ill": 1, "bone_walk": False, "hack": True}) == {"ill": True, "bone_walk": False}
    assert E.clean_checkin_flags(None) is None and E.clean_checkin_flags({}) is None


def test_back_pain_red_flag_stops_everything(client, db_session):
    rid, _ = _runner(client, db_session, "lr1@test.cz")
    _checkin(db_session, rid, pain_score=3, pain_points=BACK, flags={"red_cauda": True})
    a = _assess(db_session, rid)
    assert a["screening"]["redFlag"]["kind"] == "cauda" and a["tier"] == "alert"
    assert any(s["id"] == "red_flag" for s in a["signals"])
    g = a["guidance"]
    assert g["override"]["kind"] == "red_flag" and g["type"] == "volno"
    assert not any(g["types"][k]["allowed"] for k in ("regenerace", "lehký", "kolo", "voda", "posilování"))


def test_bone_stress_warning_signs_refer_whatever_the_number(client, db_session):
    rid, _ = _runner(client, db_session, "lr2@test.cz")
    _checkin(db_session, rid, pain_score=2, pain_points=SHIN, flags={"bone_walk": True, "bone_rest": False})
    a = _assess(db_session, rid)
    assert a["screening"]["boneStress"]["what"] == ["bolí i při chůzi"]
    assert a["tier"] == "alert" and E.triage_decision(a) == "physio_48h"
    g = a["guidance"]
    assert g["override"]["kind"] == "bone_stress" and not g["types"]["regenerace"]["allowed"]
    assert g["types"]["kolo"]["allowed"]                     # cross-training stays, if pain-free


def test_bone_pain_has_no_tolerance_but_tendon_pain_does(client, db_session):
    rid, _ = _runner(client, db_session, "lr3@test.cz")
    _checkin(db_session, rid, pain_score=3, pain_points=SHIN)
    a = _assess(db_session, rid)
    bp = a["screening"]["bonePain"]
    assert bp and bp["pain"] == 3 and not bp["repeated"] and a["tier"] in ("watch", "alert")
    g = a["guidance"]
    # v0.8.5: no running, the non-impact option instead (Warden et al., 2021)
    assert g["override"] is None and g["type"] == "kolo"
    assert not any(g["types"][k]["allowed"] for k in ("regenerace", "lehký", "dlouhý", "kvalitní"))
    assert "Jen pokud při tom nic nebolí." in g["types"]["kolo"]["notes"]
    assert any("druhý den" in n for n in g["types"]["kolo"]["notes"])
    # the same number at the Achilles tendon keeps the pain-monitoring allowance (easy running)
    rid2, _ = _runner(client, db_session, "lr3b@test.cz")
    _checkin(db_session, rid2, pain_score=3, pain_points=ACHILLES)
    a2 = _assess(db_session, rid2)
    assert a2["screening"]["bonePain"] is None
    assert a2["guidance"]["types"]["regenerace"]["allowed"] or a2["guidance"]["types"]["lehký"]["allowed"]


def test_repeated_bone_pain_is_flagged(client, db_session):
    rid, _ = _runner(client, db_session, "lr4@test.cz")
    _checkin(db_session, rid, days_ago=5, pain_score=3, pain_points=SHIN)
    _checkin(db_session, rid, pain_score=4, pain_points=SHIN)
    a = _assess(db_session, rid)
    assert a["screening"]["bonePain"]["repeated"]
    assert any("fyzioterapeutem" in x for x in a["guidance"]["reasons"])


def test_illness_rests_and_the_cluster_suggests_a_check(client, db_session):
    rid, _ = _runner(client, db_session, "lr5@test.cz")
    for d in (12, 9, 6, 3):
        _checkin(db_session, rid, days_ago=d, stress=7)
    _checkin(db_session, rid, days_ago=20, flags={"ill": True})
    _checkin(db_session, rid, flags={"ill": True}, stress=7)
    a = _assess(db_session, rid)
    assert a["screening"]["ill"] and a["screening"]["illDays28"] == 2
    assert a["cluster"] and set(a["cluster"]["parts"]) >= {"fatigue", "illness"}
    assert any(s["id"] == "cluster" for s in a["signals"])
    g = a["guidance"]
    assert g["type"] == "volno" and not g["types"]["kvalitní"]["allowed"]
    assert any("nemoc" in x.lower() for x in g["reasons"])


def test_checkin_endpoint_stores_new_items(client, db_session):
    rid = register(client, "lr6@test.cz", "Api", "runner").json()["runner_id"]
    client.post("/api/auth/session", json={"email": "lr6@test.cz", "password": "testpass123"})
    r = client.post(f"/api/runners/{rid}/checkins", json={
        "pain_score": 2, "pain_points": SHIN, "life_stress": 7, "sleep_quality": 1,
        "flags": {"bone_earlier": True, "junk": 1}})
    assert r.status_code == 200
    db_session.expire_all()
    c = db_session.query(models.Checkin).filter(models.Checkin.runner_id == rid).first()
    assert (c.life_stress, c.sleep_quality, c.flags) == (7, 1, {"bone_earlier": True})


# ---------------------------------------------------------------- P3
def test_hard_session_by_rpe_and_the_weekly_cap():
    easy_hr = {"exp": {"intensity": 2}, "rpe": 8, "durationMin": 50}
    long_run = {"exp": {"intensity": 3}, "rpe": 7, "durationMin": 120}
    assert G.is_hard(easy_hr) and not G.is_hard(long_run)
    assert G.is_hard({"exp": {"intensity": 12}, "rpe": None, "durationMin": None})


def test_weekly_hard_cap_blocks_quality(client, db_session):
    rid, r = _runner(client, db_session, "lr7@test.cz")
    runs = (db_session.query(models.Activity).filter(models.Activity.runner_id == rid,
                                                     models.Activity.started_at >= E.day_ago(6)).all())
    for a in runs:                                           # every run of the week rated as very hard
        db_session.add(models.ActivityFeedback(activity_id=a.id, runner_id=rid, submitted_at=a.started_at, rpe=8,
                                               pain_points=[]))
        a.duration_min = min(a.duration_min or 40, 60)
    db_session.commit()
    g = _guide(db_session, rid, r)
    assert g["hardWeek"]["done"] >= min(len({a.started_at[:10] for a in runs}), 3)
    if g["hardWeek"]["done"] >= g["hardWeek"]["cap"]:
        assert not g["types"]["kvalitní"]["allowed"]


def test_heat_forecast_before_acclimatisation(client, db_session, monkeypatch):
    rid, r = _runner(client, db_session, "lr8@test.cz")
    base = _guide(db_session, rid, r)
    monkeypatch.setitem(W._FORECAST, (rid, E.day_ago(0)), {"feelsMax": 31, "day": E.day_ago(0)})
    g = _guide(db_session, rid, r)
    assert g["heat"]["stage"] == "new" and g["heat"]["hot14"] == 0
    if base["types"]["kvalitní"]["z4Max"] and g["types"]["kvalitní"]["z4Max"]:
        assert g["types"]["kvalitní"]["z4Max"] <= base["types"]["kvalitní"]["z4Max"]
    assert any("31 °C" in n for n in g["types"]["kvalitní"]["notes"])
    # after two weeks of hot runs the caution eases
    for a in db_session.query(models.Activity).filter(models.Activity.runner_id == rid,
                                                      models.Activity.started_at >= E.day_ago(13)).all():
        a.weather_json = {"precision": "hour", "feelsC": 27, "hot": True}
    db_session.commit()
    g2 = _guide(db_session, rid, r)
    assert g2["heat"]["stage"] in ("adapting", "adapted") and g2["heat"]["hot14"] >= 5


def test_hot_runs_dont_set_the_hr_norm_and_dont_count_as_fatigue():
    runs = [{"date": E.day_ago(10 + k), "avgHr": 140 + k, "speed": 3.0 + 0.05 * k, "ascPerKm": 5, "hot": False}
            for k in range(10)]
    hot = [{"date": E.day_ago(9 + k), "avgHr": 175, "speed": 3.0, "ascPerKm": 5, "hot": True} for k in range(10)]
    fit = C.hr_speed_fit(runs + hot, E.day_ago(0))
    assert fit == C.hr_speed_fit(runs, E.day_ago(0))
    rel = {"runs": [{"hrDelta": 12, "hot": True}, {"hrDelta": 11, "hot": True}, {"hrDelta": 2}, {"hrDelta": 1},
                    {"hrDelta": 9, "hilly": True}]}
    assert E.hr_pace_deltas(rel) == [2, 1]


def test_capacity_after_a_break_doesnt_lean_on_an_old_peak():
    def cap_after(off_weeks):
        daily = {E.day_ago(k): 6.0 for k in range(7 + 7 * off_weeks, 90)}      # 42 km weeks, then a break
        return C.weekly_capacity(daily, E.day_ago(0), E.day_ago(89), set(), "volume")
    assert cap_after(0) == pytest.approx(42.0)
    assert cap_after(3) < 0.8 * 42 and cap_after(5) < cap_after(3)


# ---------------------------------------------------------------- P4
def test_grade_factor_prices_hills():
    flat = SimpleNamespace(distance_km=10, ascent_m=0, descent_m=0)
    rolling = SimpleNamespace(distance_km=10, ascent_m=200, descent_m=200)
    climb = SimpleNamespace(distance_km=10, ascent_m=500, descent_m=0)
    assert E.grade_factor(flat) == 1.0
    assert 1.0 < E.grade_factor(rolling) < 1.1 < E.grade_factor(climb)
    assert E.minetti_cost(0) == pytest.approx(3.6)


def test_heart_rate_at_usual_pace_signal(client, db_session, monkeypatch):
    rid, r = _runner(client, db_session, "lr9@test.cz")
    real = C.relative_effort
    monkeypatch.setattr(C, "relative_effort", lambda s, d, n_runs=6: {
        **real(s, d, n_runs), "runs": [{"hrDelta": 9}, {"hrDelta": 8}, {"hrDelta": 10}]})
    with E.engine_pinned("v3"):
        a = E.assess(db_session, rid)
    sig = next(s for s in a["signals"] if s["id"] == "hr_pace")
    assert sig["grade"] == "C" and 3 <= sig["pts"] <= 10


def test_strength_nudge_and_new_block(client, db_session):
    rid, r = _runner(client, db_session, "lr10@test.cz")
    g = _guide(db_session, rid, r)
    assert g["strength"]["lastAge"] is None
    assert any("Posilování zatím nemáte" in n for n in g["types"]["posilování"]["notes"])
    km0 = g["types"]["lehký"]["km"]["hi"]
    a = models.Activity(runner_id=rid, provider="manual", started_at=E.day_ago(3), sport="strength",
                        title="Posilování", duration_min=40, strength_focus="full", strength_type="circuit")
    db_session.add(a)
    db_session.commit()
    g2 = _guide(db_session, rid, r)
    assert g2["strength"]["newBlock"] and g2["strength"]["newBlock"]["day"] == 4
    assert g2["types"]["lehký"]["km"]["hi"] <= km0 + 1e-9


def test_high_hrv_with_fatigue_is_not_good_news(client, db_session):
    rid, r = _runner(client, db_session, "lr11@test.cz")
    for k in range(0, 36):
        db_session.merge(models.DailyMetric(runner_id=rid, date=E.day_ago(k), hrv_ms=(72 if k < 7 else 58 + (k % 5)),
                                            resting_hr=50, sleep_h=7.5))
    for d in (0, 1, 3):
        _checkin(db_session, rid, days_ago=d, stress=7)
    with E.engine_pinned("v3"):
        a = E.assess(db_session, rid)
    assert a["rcv"]["hrv"]["z"] >= E.HRV_HIGH_Z
    assert any(s["id"] == "hrv_high" for s in a["signals"])
