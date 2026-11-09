"""Physio brief 2026-11-09 P0.2–P0.4: one answer to "may this runner run today?" (care directive, first
match wins), missing data is not health (freshness), and the status label cannot contradict the rest.
The engine's stored result is never changed (D8)."""
from datetime import date, datetime, timedelta

import pytest

from app import care_view as CV
from app import models
from app.metrics import engine as E

from .conftest import login
from .test_prevention import _assess, _checkin, _runner

T = date(2026, 11, 9)


# ---------------------------------------------------------------- P0.3 freshness boundaries
@pytest.mark.parametrize("days,status", [(0, "fresh"), (3, "fresh"), (4, "aging"), (13, "aging"), (14, "stale"), (54, "stale")])
def test_freshness_boundaries(days, status):
    f = CV.data_freshness(T - timedelta(days=days), None, None, T)
    assert f["status"] == status and f["days_since"] == days


def test_freshness_none_and_newest_source_wins():
    assert CV.data_freshness(None, None, None, T) == {"status": "none", "last_data_at": None, "days_since": None}
    f = CV.data_freshness(T - timedelta(days=54), T - timedelta(days=2), None, T)
    assert f["status"] == "fresh" and f["last_data_at"] == (T - timedelta(days=2)).isoformat()


def _stale_runner(client, db, email):
    """Adéla's case from the brief: last run weeks ago with pain 6/10, the last check-in a day later with 4/10."""
    rid, _ = _runner(client, db, email)
    db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                     models.Activity.started_at >= E.day_ago(53)).delete()
    db.query(models.Checkin).filter(models.Checkin.runner_id == rid).delete()
    db.commit()
    _checkin(db, rid, days_ago=53, pain_score=4, pain_site="Achillova šlacha")
    return rid


def test_stale_data_shows_no_score_tier_or_recommendation(client, db_session):
    rid = _stale_runner(client, db_session, "stale-adela@test.cz")
    raw = _assess(db_session, rid)
    a = CV.present(db_session, rid, raw)
    assert a["freshness"]["status"] == "stale" and a["freshness"]["days_since"] == 53
    assert a["overall"] is None and a["readiness"] is None and a["load"] is None and a["mech"] is None
    assert a["tier"] == "unknown" and a["quadrant"] == "unknown" and a["display_state"] == "unknown"
    g = a["guidance"]
    assert g["override"]["kind"] == "no_data" and "před 53 dny" in g["override"]["text"]
    assert not any(g["types"][t]["allowed"] for t in CV.RUN_TYPES if t in g["types"])
    assert a["lastPain"]["score"] == 4 and a["lastPain"]["source"] == "checkin"
    # D8: the stored engine result keeps its numbers
    assert E.get_or_refresh_assessment(db_session, rid)["quadrant"] != "unknown"


def test_runner_and_physio_get_the_same_stale_view(client, db_session):
    a = CV.present(db_session, "run-0001", E.get_or_refresh_assessment(db_session, "run-0001"))
    assert a["freshness"]["status"] == "fresh"      # the seeded demo runner is current
    login(client, "adela@demo.cz")
    boot = client.get("/api/runners/run-0001/bootstrap").json()["assessment"]
    login(client, "havlickova@fyzioholesovice.cz")
    phys = client.get("/api/physios/me/clients/run-0001").json()["a"]
    assert boot["display_state"] == phys["display_state"]
    assert boot["careDirective"]["headline_cs"] == phys["careDirective"]["headline_cs"]


# ---------------------------------------------------------------- P0.2 care directive rows
def _plan(db, rid, status="active"):
    db.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at=E.now_iso()))
    p = models.ReturnToRun(runner_id=rid, physio_id="phy-0001", created_at=E.now_iso(), started_on=E.iso_date(E.today_date()),
                           status=status, current_level=2, pain_threshold=3, sessions_per_level=3,
                           levels_json=[{"level": 1, "label": "1 min běh / 2 min chůze × 6"},
                                        {"level": 2, "label": "2 min běh / 1 min chůze × 6", "run_s": 120, "walk_s": 60, "reps": 6}])
    db.add(p)
    db.commit()
    return p


def _confirmed_injury(db, rid):
    db.add(models.InjuryReport(runner_id=rid, submitted_at=E.day_ago(2), status="active", confirmed=True,
                               source="physio_conclusion", severity=50, body_region="Achillova šlacha",
                               q_participation=17, q_volume=8, q_performance=8, q_pain=17))
    db.commit()


def test_row1_safety_red_flag_wins_over_a_plan(client, db_session):
    rid, _ = _runner(client, db_session, "cd-red@test.cz")
    _plan(db_session, rid)
    _checkin(db_session, rid, pain_score=6, pain_site="Bedra", pain_points=[{"region": "Bedra"}],
             flags={"red_systemic": True})
    a = CV.present(db_session, rid, _assess(db_session, rid))
    assert a["guidance"]["override"]["kind"] == "red_flag"
    assert a["careDirective"]["source"] == "safety" and a["careDirective"]["running_allowed"] is False


def test_row3_active_plan_today_only_this_session(client, db_session):
    rid, _ = _runner(client, db_session, "cd-rtr@test.cz")
    _confirmed_injury(db_session, rid)
    _plan(db_session, rid)
    a = CV.present(db_session, rid, _assess(db_session, rid))
    d = a["careDirective"]
    assert d["source"] == "rtr" and d["running_allowed"] is True and d["session"]["level"] == 2
    assert d["headline_cs"] == "Dnes podle plánu návratu: 2 min běh / 1 min chůze × 6"
    g = a["guidance"]
    assert g["override"]["title"] == d["headline_cs"]           # Dnes and Trénink say the same
    assert not any(g["types"][t]["allowed"] for t in CV.RUN_TYPES if t in g["types"])   # no other running option
    assert a["display_state"] == "injury"                       # the confirmed injury is still shown


def test_row4_inside_the_rest_gap_no_running(client, db_session):
    rid, _ = _runner(client, db_session, "cd-gap@test.cz")
    p = _plan(db_session, rid)
    db_session.add(models.RtrSession(plan_id=p.id, runner_id=rid, level=2, pain=1, completed=True, counted=True,
                                     logged_at=(datetime.fromisoformat(E.now_iso()) - timedelta(hours=3)).isoformat()))
    db_session.commit()
    d = CV.present(db_session, rid, _assess(db_session, rid))["careDirective"]
    assert d["source"] == "rtr" and d["running_allowed"] is False and d["headline_cs"].startswith("Dnes bez běhu — další sezení")


def test_row5_paused_plan(client, db_session):
    rid, _ = _runner(client, db_session, "cd-paused@test.cz")
    _plan(db_session, rid, status="paused")
    a = CV.present(db_session, rid, _assess(db_session, rid))
    assert a["careDirective"]["source"] == "rtr_paused" and a["careDirective"]["running_allowed"] is False
    assert a["guidance"]["override"]["title"].startswith("Plán návratu je pozastavený")
    assert a["display_state"] == "rtr"


def test_row6_confirmed_injury_without_a_plan(client, db_session):
    rid, _ = _runner(client, db_session, "cd-inj@test.cz")
    _confirmed_injury(db_session, rid)
    a = CV.present(db_session, rid, _assess(db_session, rid))
    assert a["careDirective"]["source"] == "injury" and a["careDirective"]["running_allowed"] is False
    assert a["careDirective"]["headline_cs"] == "Aktivní zranění — dnes bez běhu"


def test_row7_engine(client, db_session):
    rid, _ = _runner(client, db_session, "cd-engine@test.cz")
    a = CV.present(db_session, rid, _assess(db_session, rid))
    assert a["careDirective"]["source"] == "engine" and a["display_state"] == a["quadrant"]


# ---------------------------------------------------------------- P0.4 labels never contradict
@pytest.mark.parametrize("quadrant", ["stable", "overload", "mechanics", "both", None])
@pytest.mark.parametrize("injury", [None, {"confirmed": True}, {"confirmed": False}])
@pytest.mark.parametrize("fresh", ["fresh", "stale", "none"])
def test_stable_never_next_to_an_injury_or_missing_data(quadrant, injury, fresh):
    a = {"quadrant": quadrant, "tier": "alert", "injury": {"active": injury}, "freshness": {"status": fresh}}
    st = CV.display_state(a)
    if (injury or {}).get("confirmed"):
        assert st == "injury"
    elif fresh in ("stale", "none"):
        assert st == "unknown"
    if st == "stable":
        assert not (injury or {}).get("confirmed") and fresh not in ("stale", "none")
