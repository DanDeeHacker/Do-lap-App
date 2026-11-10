"""Physio brief round 2 F4: pain from one source. A check-in pain, a post-run pain and a return-to-run session
pain are three events on every surface (Přehled, Kde to bolí, Příznaky, Časová osa, Příprava, lastPain), and a
range without data is a gap in the timeline — never a line drawn through it, never a 0."""
from datetime import date, datetime, timedelta

from app import care_view as CV
from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


def test_three_sources_are_three_events_everywhere(client, db_session):
    login(client, PHYSIO)
    since = (E.today_date() - timedelta(weeks=6)).isoformat()
    before = CV.pain_summary(CV.pain_events(db_session, RID, since))["count"]
    now = datetime.fromisoformat(E.now_iso())
    act = db_session.query(models.Activity).filter_by(runner_id=RID).order_by(models.Activity.started_at.desc()).first()
    plan = models.ReturnToRun(runner_id=RID, physio_id="phy-0001", created_at=E.now_iso(), status="active",
                              current_level=1, pain_threshold=3, sessions_per_level=3,
                              levels_json=[{"level": 1, "label": "1 min běh / 2 min chůze × 6"}])
    db_session.add(plan)
    db_session.flush()
    db_session.add_all([
        models.Checkin(runner_id=RID, submitted_at=(now - timedelta(hours=5)).isoformat(), pain_score=3,
                       pain_site="Achillova šlacha", pain_points=[{"region": "achilles", "side": "P"}]),
        models.ActivityFeedback(activity_id=act.id, runner_id=RID, submitted_at=(now - timedelta(hours=3)).isoformat(),
                                pain_during=4, pain_site="achilles"),
        models.RtrSession(plan_id=plan.id, runner_id=RID, level=1, pain=6, completed=True, counted=False,
                          logged_at=(now - timedelta(minutes=30)).isoformat()),
    ])
    db_session.commit()
    ev = CV.pain_events(db_session, RID, since)
    srcs = {e["source"] for e in ev if e["at"] >= (now - timedelta(hours=6)).isoformat()}
    assert {"checkin", "activity", "rtr_session"} <= srcs
    summ = CV.pain_summary(ev)
    assert summ["count"] == before + 3
    assert "check-in" in summ["sources_cs"] and "návrat k běhu" in summ["sources_cs"] and "po běhu" in summ["sources_cs"]
    # lastPain is the newest event, whatever its source
    lp = CV.last_pain(db_session, RID)
    newest = CV.pain_events(db_session, RID)[-1]
    assert (lp["at"], lp["score"], lp["source"]) == (newest["at"], newest["score"], newest["source"])
    # the physio's overview: the same count and the same places
    body = client.get(f"/api/physios/me/clients/{RID}").json()
    assert body["pain_summary"]["count"] == summ["count"]
    assert any(x["region"] == "achilles" for x in body["pain_map"])
    # the timeline shows a pain point on today
    tl = client.get(f"/api/physios/me/clients/{RID}/timeline", params={"weeks": 4}).json()
    today = [x for x in tl["days"] if x["date"] == now.date().isoformat() or x["date"] == (now - timedelta(hours=5)).date().isoformat()]
    assert any(x.get("pain") for x in today)
    # Příprava counts every source too
    pre = client.get(f"/api/physios/me/clients/{RID}/previsit").json()
    assert pre["since"]["pain_count"] >= 3 and "návrat k běhu" in pre["since"]["pain_sources"]
    # leave the shared demo runner without an open plan for the other tests
    plan.status = "completed"
    db_session.commit()


def test_timeline_gap_is_shaded_and_never_drawn(client, db_session):
    from app.routers.work import _gaps, _span
    today = date(2026, 11, 10)
    seen = {"2026-09-15", "2026-09-17", "2026-11-09"}
    gaps = _gaps("2026-09-14", today, seen)
    big = max(gaps, key=lambda g: g["days"])
    # the September–November gap: from the day after the freshness window ran out
    assert big["from"] == (date(2026, 9, 17) + timedelta(days=CV.FRESH_MAX_DAYS + 1)).isoformat()
    assert big["to"] == "2026-11-08"
    assert "2026-10-15" in _span(big["from"], big["to"])
    # a short pause between runs is not a gap
    assert not any(g["from"] <= "2026-09-16" <= g["to"] for g in gaps)


def test_dnes_alert_title_carries_the_real_number():
    from app import work as W
    assert W.alert_title("no_data_7d", {"days": 54, "last": "2026-09-17"}) == "Bez dat 54 dní"
    assert W.alert_title("no_data_7d", {"last": "2026-09-17"}) == "Bez dat od 17. 9."
