"""Owner decision 2026-10-14 — consistency weeks, habit milestones and the goal as a path."""
from datetime import date, timedelta
from types import SimpleNamespace as NS

from app import models
from app.metrics import engine as E
from app.metrics import goal_track as GT
from app.metrics import habits as HB
from .test_guidance import _runner

MON = date(2026, 9, 7)                 # a Monday
TODAY = MON + timedelta(days=7 * 5 + 2)   # Wednesday of the 6th week


def _d(week, day=1):
    return (MON + timedelta(days=7 * week + day)).isoformat()


def test_weeks_kept_paused_missed_and_the_run_of_weeks():
    acts = [(_d(w), True) for w in (0, 1, 2, 4, 5)]                    # nothing in week 3
    load = {(MON + timedelta(days=k)).isoformat(): 10 for k in range(7 * 6)}
    load[_d(1, 3)] = 31                                                 # week 1: one day over the line
    ws = HB.weeks(TODAY, acts, load, set(), [])
    assert [w["status"] for w in ws] == ["kept", "missed", "kept", "paused", "kept", "now"]
    assert ws[1]["why"] == "zátěž nad prahem 1×" and ws[3]["why"] == "bez tréninku"
    assert HB.chain(ws) == 2                                            # week 4 and week 2, week 3 skipped
    best, reached = HB.chain_runs(ws)
    assert best == 2 and reached[2] == ws[4]["end"]
    # an illness pauses a week that went over the line instead of breaking the run
    ill = HB.weeks(TODAY, acts, load, {_d(1, 4)}, [])
    assert ill[1]["status"] == "paused" and HB.chain(ill) == 3


def test_the_programme_sessions_count_in_its_weeks():
    acts = [(_d(w), True) for w in range(6)]
    load = {(MON + timedelta(days=k)).isoformat(): 5 for k in range(7 * 6)}
    started = (MON - timedelta(days=7 * 7)).isoformat()                 # week 0 here = its 8th week (lighter: 1)
    sessions = [_d(0, 2), _d(1, 1), _d(1, 3), _d(2, 1)]                 # week 2: only one of two
    ws = HB.weeks(TODAY, acts, load, set(), [(started, sessions, True)])
    assert ws[0]["strength"] == [1, 1] and ws[0]["status"] == "kept"
    assert ws[1]["strength"] == [2, 2] and ws[1]["status"] == "kept"
    assert ws[2]["status"] == "missed" and ws[2]["why"] == "posilování 1 z 2"
    # a programme stopped after its last session asks nothing afterwards
    stopped = HB.weeks(TODAY, acts, load, set(), [(started, sessions, False)])
    assert stopped[3]["strength"] is None and stopped[3]["status"] == "kept"


def test_endpoint_milestones_are_kept_once_earned(client, db_session):
    rid, r = _runner(client, db_session, "hab1@test.cz", days=60)
    runs = (db_session.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == "running")
            .order_by(models.Activity.started_at).all())
    for a in runs[:20]:
        db_session.add(models.ActivityFeedback(activity_id=a.id, runner_id=rid, submitted_at=a.started_at, feeling=4, legs=4))
    db_session.commit()
    d = client.get(f"/api/runners/{rid}/habits").json()
    assert d["threshold"] == 25 and d["weeks"] and d["weeks"][-1]["status"] == "now"
    ms = {m["id"]: m for m in d["milestones"]}
    assert ms["diary20"]["earned"] == runs[19].started_at[:10] and ms["diary20"]["have"] == 20
    assert "shoes" not in ms and "return" not in ms                    # not relevant without shoes / a return plan
    assert ms["strength24"]["earned"] is None and ms["strength24"]["have"] == 0
    db_session.refresh(r)
    assert (r.onboarding_json or {})["milestones"]["diary20"] == runs[19].started_at[:10]
    # earned stays earned, even when the notes are gone
    db_session.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid).delete()
    db_session.commit()
    ms2 = {m["id"]: m for m in client.get(f"/api/runners/{rid}/habits").json()["milestones"]}
    assert ms2["diary20"]["earned"] == runs[19].started_at[:10]
    # the announced ones are stored per account
    assert client.patch("/api/auth/settings", json={"badges_seen": ["diary20", "diary20"]}).json()["badges_seen"] == ["diary20"]


def _plan(n, start, half_at=None):
    out = []
    for i in range(1, n + 1):
        w = {"i": i, "start": (start + timedelta(days=7 * (i - 1))).isoformat(),
             "phase": "taper" if i > n - 2 else "specific" if i > n - 6 else "build"}
        if i == half_at:
            w["milestone"] = "half"
        if i == n:
            w["race"] = True
        out.append(w)
    return out


def test_journey_runs_from_the_goal_set_to_the_race():
    today = date(2026, 10, 14)                                          # Wednesday
    mon = today - timedelta(days=today.weekday())
    created = mon - timedelta(days=7 * 6)
    race = mon + timedelta(days=7 * 13 + 6)
    g = NS(created_at=created.isoformat() + "T10:00", date=race.isoformat(), race_id=1,
           track_json={"weeks": {(created + timedelta(days=7 * k)).isoformat(): {"phase": "base"} for k in range(6)},
                       "checkpoints": {}})
    res = {"plan": _plan(14, mon, half_at=4), "goal": {"kind": "race"}}
    j = GT.journey(g, res, today)
    assert j["weeks"] == 20 and j["now"] == 7
    assert j["segs"][0] == {"from": 1, "to": 6, "phase": "base"} and j["segs"][-1]["phase"] == "taper"
    keys = [s["key"] for s in j["stops"]]
    assert keys[-1] == "race" and "half" in keys and {"w8", "w4"} <= set(keys)
    half_check = next(s for s in j["stops"] if s["key"] == "half" and s["kind"] == "check")
    assert half_check["i"] == 10 and not half_check["done"]
    hm = next(s for s in j["stops"] if s["kind"] == "milestone")
    assert hm["i"] == 10 and hm["label"] == "Mezicíl: běh na 21 km"
    assert j["next"]["i"] == 10 and j["next"]["inWeeks"] == 3
    assert GT.journey(g, {"plan": []}, today) is None
