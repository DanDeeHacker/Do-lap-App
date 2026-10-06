"""Runner's must-have (owner request 2026-10-03): the 6-month durability programme —
sessions A / B alternating by what the day can carry, progression by the end-of-session
feeling, the session counted in the load, doses sized to the weekly strength capacity."""
from datetime import date

from app import durability as DU
from app import models
from app.metrics import engine as E

from .conftest import register


def _pin(monkeypatch, d):
    """The HTTP calls run in another thread, so the thread-local today_pinned doesn't reach them."""
    monkeypatch.setattr(E, "today_date", lambda: d)


def _start(client, email):
    rid = register(client, email, "Síla", "runner").json()["runner_id"]
    p = client.post(f"/api/runners/{rid}/self-programs", json={"template": "durability"}).json()
    return rid, p


def _do_all(client, rid, p):
    for x in p["exercises"]:
        p = client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": x["id"], "done": True}).json()
    return p


def test_programme_starts_with_session_a_and_phase_doses(client, monkeypatch):
    _pin(monkeypatch, date(2026, 10, 5))
    if True:
        rid, p = _start(client, "dur1@test.cz")
        d = p["durability"]
        assert d["session"] == "A" and d["week"] == 1 and d["phase"]["key"] == "base" and not d["blocked"]
        assert [x["id"] for x in p["exercises"]] == [e[0] for e in DU.SESSIONS["A"]["plan"]]
        bss = next(x for x in p["exercises"] if x["id"] == "bulgarian_ss")
        assert bss["dose"] == "2 × 8 každá noha" and bss["perWeek"] == 1   # each session once a week
        assert 30 <= d["estMin"] <= 60
        assert [ph["key"] for ph in d["phases"]] == DU.PHASE_KEYS and d["phases"][-1]["to"] == 26


def test_finish_rates_the_watch_recording_and_progresses_then_alternates(client, db_session, monkeypatch):
    _pin(monkeypatch, date(2026, 10, 5))                         # Monday
    if True:
        rid, p = _start(client, "dur2@test.cz")
        p = _do_all(client, rid, p)
        p = client.post(f"/api/runners/{rid}/self-programs/{p['id']}/finish", json={"feel": "easy"}).json()
        d = p["durability"]
        assert d["doneToday"] and d["blocked"] and d["note"].startswith("Příště o něco víc")
        # feedback #204 — no activity of the app's own: the rating waits for the watch's recording
        assert not p["sessionLinked"]
        assert db_session.query(models.Activity).filter(models.Activity.runner_id == rid).count() == 0
        prog = db_session.get(models.SelfProgram, p["id"])
        db_session.refresh(prog)
        rate = prog.state["history"][-1]["rate"]
        assert rate["rpe"] == DU.FEEL["easy"] and rate["type"] == "heavy" and rate["minutes"] >= 30
        # re-rating the same day doesn't progress twice
        p = client.post(f"/api/runners/{rid}/self-programs/{p['id']}/finish", json={"feel": "hard"}).json()
        db_session.refresh(prog)
        assert prog.state["levels"]["A"] == 0 and len(prog.state["history"]) == 1
        assert p["next"]["session"] == "B" and p["next"]["date"] == "2026-10-07"
        # the watch's strength workout of that day syncs later: it takes the session's rating
        w = models.Activity(runner_id=rid, provider="garmin", external_id="str1", sport="strength",
                            started_at="2026-10-05", duration_min=62)
        db_session.add(w)
        db_session.commit()
        assert DU.link_sessions(db_session, rid)
        db_session.commit()
        fb = db_session.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == w.id).one()
        db_session.refresh(w)
        assert fb.rpe == DU.FEEL["hard"] and w.strength_type == "heavy"
        db_session.refresh(prog)
        assert prog.state["history"][-1]["activityId"] == w.id
        assert db_session.query(models.Activity).filter(models.Activity.runner_id == rid).count() == 1
        # re-rating once linked rates the same recording again
        p = client.post(f"/api/runners/{rid}/self-programs/{p['id']}/finish", json={"feel": "ok"}).json()
        assert p["sessionLinked"]
        db_session.expire_all()
        assert db_session.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == w.id).one().rpe == DU.FEEL["ok"]
    _pin(monkeypatch, date(2026, 10, 6))                         # 24 h later: too soon
    if True:
        d = client.get(f"/api/runners/{rid}/self-programs").json()["active"]["durability"]
        assert d["blocked"] and "48 hodin" in d["blocked"]
    _pin(monkeypatch, date(2026, 10, 7))
    if True:
        d = client.get(f"/api/runners/{rid}/self-programs").json()["active"]["durability"]
        assert d["session"] == "B" and not d["blocked"]
        assert [x["id"] for x in d["plan"]][0] == "sl_hops"


def test_progression_rules():
    st = {"levels": {"A": 0, "B": 0}, "steps": {"A": 0, "B": 0}, "history": []}
    st = DU.progress(st, "A", "ok", 6)                           # first "just right": hold
    assert st["levels"]["A"] == 0
    st = DU.progress(st, "A", "ok", 6)                           # twice at the same level: up
    assert st["levels"]["A"] == 1
    st = DU.progress(st, "A", "easy", 7)
    assert st["levels"]["A"] == 2
    st = DU.progress(st, "A", "easy", 7)                         # top of the range: heavier, reps back down
    assert st["levels"]["A"] == 0 and st["steps"]["A"] == 1 and "zátěž" in st["note"]
    st = DU.progress(st, "A", "easy", 8)
    st = DU.progress(st, "A", "pain", 8)                         # pain: down at once
    assert st["levels"]["A"] == 0
    st = DU.progress({**st, "levels": {"A": 2, "B": 0}}, "A", "hard", 9)
    st = DU.progress(st, "A", "hard", 9)                         # hard twice: down
    assert st["levels"]["A"] == 1
    st = DU.progress(st, "A", "easy", 11)                        # new phase starts at its bottom
    assert st["history"][-1]["level"] == 0 and st["history"][-1]["phase"] == "strength"


def test_doses_follow_the_phase_and_deload():
    a1 = DU.session_plan("A", 1, 0, False)
    a12 = DU.session_plan("A", 12, 2, False)
    dl = DU.session_plan("A", 12, 2, True)
    rdl = lambda plan: next(x for x in plan if x["id"] == "rdl")
    assert (rdl(a1)["sets"], rdl(a1)["n"]) == (2, 10)
    assert (rdl(a12)["sets"], rdl(a12)["n"]) == (3, 8)            # the coach's 3 × 6–8, top of the range
    assert (rdl(dl)["sets"], rdl(dl)["n"]) == (2, 6)              # deload: a set less, bottom of the range
    assert DU.is_deload(8, None) and not DU.is_deload(9, None)
    assert not DU.is_deload(4, None) and not DU.is_deload(3, {"guidance": {"week": {"mode": "recovery"}}})   # the basics are light already
    assert DU.is_deload(6, {"guidance": {"week": {"mode": "recovery"}}})
    assert not DU.is_deload(8, {"guidance": {"week": {"mode": "build"}}})
    # every session of the six months stays a reasonable length
    for w in range(1, 27):
        for k in "AB":
            for lv in (0, 2):
                assert 25 <= DU.estimate_min(k, DU.session_plan(k, w, lv, DU.is_deload(w, None))) <= 60, (w, k, lv)


def test_weekly_strength_capacity_trims_the_sets():
    a = {"capacity": {"channels": {"strength": {"week": {"ceiling": 300}}}}}
    scale, cap = DU.capacity_scale(a, 12, 1, False)
    assert scale < 1.0 and cap["weekly"] > cap["ceiling"] == 300
    full = DU.session_plan("A", 12, 1, False)
    cut = DU.session_plan("A", 12, 1, False, scale)
    assert sum(x["sets"] for x in cut) < sum(x["sets"] for x in full) and all(x["sets"] >= 1 for x in cut)
    assert DU.capacity_scale({"capacity": {"channels": {"strength": {"week": {"ceiling": 5000}}}}}, 12, 1, False)[0] == 1.0


def test_a_demanding_day_gets_b_instead_of_a(client, db_session):
    with E.today_pinned(date(2026, 10, 5)):
        rid = register(client, "dur3@test.cz", "Síla", "runner").json()["runner_id"]
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="long1", sport="running",
                                       started_at=(date(2026, 10, 4)).isoformat() + "T08:00:00", duration_min=95, distance_km=18))
        db_session.commit()
        g = {"guidance": {"week": {"mode": "build", "channels": {}}, "axes": {"load": 10, "mech": 10, "threshold": 25},
                          "types": {"posilování": {"allowed": True}}, "readinessScore": 80, "type": "lehký"}}
        pick = DU.choose(db_session, rid, g, {"history": []}, E.today_date())
        assert pick["session"] == "B" and pick["due"] == "A" and "včera" in pick["why"]
        g["guidance"]["week"]["mode"] = "recovery"
        pick = DU.choose(db_session, rid, g, {"history": [{"date": "2026-10-01", "session": "B"}]}, date(2026, 10, 8))
        assert pick["session"] == "B" and "odlehčovací" in pick["why"]
        pick = DU.choose(db_session, rid, {"guidance": {**g["guidance"], "week": {"mode": "build"}}},
                         {"history": [{"date": "2026-10-01", "session": "B"}]}, date(2026, 10, 8))
        assert pick["session"] == "A"
        # two sessions this week already → not today
        pick = DU.choose(db_session, rid, None, {"history": [{"date": "2026-10-05", "session": "A"},
                                                             {"date": "2026-10-07", "session": "B"}]}, date(2026, 10, 10))
        assert pick["blocked"] and "2 z 2" in pick["blocked"]


# ---------------------------------------------------------------- owner request 2026-10-06
def test_an_exercise_added_to_the_template_later_can_be_logged(client, db_session, monkeypatch):
    """A programme started before pelvic_drop joined session B couldn't log it (422), so the
    session never ended."""
    _pin(monkeypatch, date(2026, 10, 5))
    rid, p = _start(client, "dur10@test.cz")
    prog = db_session.get(models.SelfProgram, p["id"])
    prog.exercises = [x for x in prog.exercises if x != "pelvic_drop"]
    db_session.commit()
    r = client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": "pelvic_drop", "done": True})
    assert r.status_code == 200
    db_session.refresh(prog)
    assert "pelvic_drop" in prog.exercises
    assert client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": "nordic", "done": True}).status_code == 422


def test_ending_a_session_early(client, db_session, monkeypatch):
    _pin(monkeypatch, date(2026, 10, 5))
    rid, p = _start(client, "dur11@test.cz")
    prog = db_session.get(models.SelfProgram, p["id"])
    prog.state = {**prog.state, "levels": {"A": 2, "B": 0}}
    db_session.commit()
    p = client.get(f"/api/runners/{rid}/self-programs").json()["active"]
    plan = p["durability"]["plan"]
    url = f"/api/runners/{rid}/self-programs/{p['id']}/finish"
    assert client.post(url, json={"feel": "ok"}).status_code == 422                # nothing done yet
    for x in plan[:3]:
        client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": x["id"], "done": True})
    p = client.post(url, json={"feel": "hard", "easier": True, "sets": {plan[3]["id"]: 1}}).json()
    d = p["durability"]
    total = sum(x["sets"] for x in plan)
    done = sum(x["sets"] for x in plan[:3]) + 1
    assert d["doneToday"] and d["partialToday"] and d["completionToday"] == round(done / total, 2)
    assert d["easierNext"] and "nebyl celý a byl těžký" in d["note"] and "lehčí verze" in d["noteNext"]
    db_session.refresh(prog)
    assert prog.state["levels"]["A"] == 1 and prog.state["easier"] is True
    rate = prog.state["history"][-1]["rate"]
    assert rate["minutes"] < DU.estimate_min("A", plan) and "hotovo" in rate["note"]
    # the next session is the lighter version: one set less, the bottom of the range
    _pin(monkeypatch, date(2026, 10, 7))
    p = client.get(f"/api/runners/{rid}/self-programs").json()["active"]
    d = p["durability"]
    assert d["session"] == "B" and d["light"]
    week = DU.week_of(prog.started_on, date(2026, 10, 7))
    assert [x["sets"] for x in d["plan"]] == [x["sets"] for x in DU.session_plan("B", week, 0, True)]
    for x in d["plan"]:
        client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": x["id"], "done": True})
    p = client.post(f"/api/runners/{rid}/self-programs/{p['id']}/finish", json={"feel": "ok"}).json()
    db_session.refresh(prog)
    assert prog.state["easier"] is False and prog.state["history"][-1].get("light") and not p["durability"]["partialToday"]


def test_a_partial_session_never_goes_up():
    st = {"levels": {"A": 1, "B": 0}, "steps": {"A": 0, "B": 0}, "history": []}
    st = DU.progress(st, "A", "easy", 6, partial=True, completion=0.6)
    assert st["levels"]["A"] == 1 and "nebyl celý" in st["note"] and st["history"][-1]["partial"]
    st = DU.progress(st, "A", "ok", 6, partial=True, completion=0.8, easier=True)
    assert st["levels"]["A"] == 1 and st["easier"] and "lehčí verze" in st["noteNext"]
    st = DU.progress(st, "A", "pain", 6, partial=True, completion=0.3)
    assert st["levels"]["A"] == 0 and not st["easier"]


def test_sessions_saved_as_activities_before_are_tidied_up(client, db_session, monkeypatch):
    """Feedback #204: an app-made "Posilování · …" activity from an earlier version goes; its
    rating moves onto the watch's recording of that day."""
    _pin(monkeypatch, date(2026, 10, 5))
    rid, p = _start(client, "dur12@test.cz")
    old = models.Activity(runner_id=rid, provider="manual", sport="strength", started_at="2026-10-03", duration_min=40,
                          title="Posilování · A · Síla (těžší)", strength_type="heavy", strength_focus="lower")
    w = models.Activity(runner_id=rid, provider="garmin", external_id="str2", sport="strength", started_at="2026-10-03", duration_min=75)
    hand = models.Activity(runner_id=rid, provider="manual", sport="cycling", started_at="2026-10-02", duration_min=60, title="Kolo")
    db_session.add_all([old, w, hand])
    db_session.flush()
    db_session.add(models.ActivityFeedback(activity_id=old.id, runner_id=rid, submitted_at="2026-10-03", rpe=8, pain_points=[],
                                           note="Runner's must-have A: těžké"))
    prog = db_session.get(models.SelfProgram, p["id"])
    prog.state = {**prog.state, "history": [{"date": "2026-10-03", "session": "A", "feel": "hard", "activityId": old.id}]}
    db_session.commit()
    client.get(f"/api/runners/{rid}/self-programs")                # the read tidies up
    db_session.expire_all()
    left = {a.title or a.sport for a in db_session.query(models.Activity).filter(models.Activity.runner_id == rid)}
    assert left == {"strength", "Kolo"}                              # the runner's own hand-logged ride stays
    fb = db_session.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == w.id).one()
    assert fb.rpe == 8 and "Runner's must-have" in fb.note
