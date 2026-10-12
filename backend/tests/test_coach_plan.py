"""Plán od trenéra (owner request 2026-10-12): the coach's plan evaluated against the
safety limits and the rules (metrics/coach_plan.py), the import (plan_import.py), the
calendar link's guard, and the coach's overview link (routers/plan.py)."""
import socket
from datetime import date, timedelta

import pytest

from app import models
from app import plan_import as PI
from app.metrics import coach_plan as CP
from app.metrics import engine as E
from app.metrics import guidance as G
from .conftest import register
from .synth import seed_runs


# ------------------------------------------------------------------ parsing
def test_hard_minutes_from_the_coachs_text():
    assert CP.hard_minutes("6× 1 km v 4:30", 360) == 27.0
    assert CP.hard_minutes("5x3min", 360) == 15.0
    assert CP.hard_minutes("45 min tempo 20 min", 360) == 20.0
    assert CP.hard_minutes("10x30s", 360) == 5.0
    assert CP.hard_minutes("lehce 10 km", 360) is None


def test_text_import_reads_days_kinds_and_sizes():
    ws = date(2026, 10, 12)
    s = PI.parse_text("Týden 42\nPo: 10 km lehce Z2\nÚt - 2 km rozklus, 6x1km v 4:30, 2 km výklus\nSt volno\n"
                      "Čt 45 min tempo 20 min\nPá: kolo 60 min\nSo 18 km dlouhý, +350 m\n"
                      "Ne: regenerace 5 km + posilování 30 min", ws)
    by = {(x["date"], x["seq"]): x for x in s}
    assert by[("2026-10-12", 0)]["kind"] == "easy" and by[("2026-10-12", 0)]["km"] == 10.0
    tue = by[("2026-10-13", 0)]
    assert tue["kind"] == "quality" and tue["km"] == 10.0 and "6x1km" in tue["intervals"]
    assert by[("2026-10-14", 0)]["kind"] == "rest"
    assert by[("2026-10-16", 0)]["kind"] == "ride" and by[("2026-10-16", 0)]["duration_min"] == 60
    assert by[("2026-10-17", 0)]["ascent_m"] == 350.0
    assert by[("2026-10-18", 1)]["kind"] == "strength"
    en = PI.parse_text("Mon 12/10: Easy 8k\nTue: 8 x 400m @ 3:50\nSat: Long run 1:45:00\nSun: swim 40'", ws)
    assert [x["kind"] for x in en] == ["easy", "quality", "long", "swim"]
    assert en[1]["unsure"] == ["km"]                      # no total distance → flagged for the runner
    assert en[2]["duration_min"] == 105


def test_llm_reply_is_validated():
    ws = date(2026, 10, 12)
    got = PI.validate({"sessions": [{"date": "2026-10-13", "kind": "quality", "km": 12, "intervals": "6x1km"},
                                    {"date": "2027-12-01", "kind": "easy", "km": 8},          # out of range
                                    {"date": "2026-10-14", "kind": "teleport", "km": 999}]}, ws)
    assert len(got) == 2 and got[1]["kind"] == "other" and got[1]["km"] is None
    assert PI.validate("nonsense", ws) is None


def test_ics_events_become_sessions_and_appointments_are_left_out():
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a1\r\nDTSTART;VALUE=DATE:20261013\r\nSUMMARY:Run: Intervals 6x800m\r\n"
           "DESCRIPTION:Warm up 15 min\\, 6x800 m @ 3:55\\, cool down. Planned distance: 11 km\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nUID:a2\r\nDTSTART:20261015T060000Z\r\nSUMMARY:Bike: Endurance\r\nDESCRIPTION:1:30:00 Z2\r\n"
           "END:VEVENT\r\nBEGIN:VEVENT\r\nUID:a3\r\nDTSTART:20261016T060000Z\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    s = PI.ics_sessions(PI.parse_ics(ics), date(2026, 10, 12))
    assert [(x["date"], x["kind"]) for x in s] == [("2026-10-13", "quality"), ("2026-10-15", "ride")]
    assert s[0]["km"] == 11.0 and s[1]["duration_min"] == 90 and s[0]["ext_uid"] == "a1"


@pytest.mark.parametrize("url", ["http://example.com/a.ics", "https://127.0.0.1/x", "https://169.254.169.254/latest",
                                 "webcal://localhost/x", "https://user:p@example.com/x", "https://10.0.0.1/x",
                                 "https://example.com:8443/x", "file:///etc/passwd"])
def test_calendar_link_guard_blocks_private_and_odd_addresses(url):
    with pytest.raises(PI.FeedError):
        PI.check_url(url)


def test_calendar_link_guard_checks_what_the_name_resolves_to(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))])
    with pytest.raises(PI.FeedError):
        PI.check_url("webcal://calendar.example.com/feed.ics")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert PI.check_url("webcal://calendar.example.com/feed.ics") == "https://calendar.example.com/feed.ics"


# ------------------------------------------------------------------ the engine
DAY = date(2026, 6, 10)   # a Wednesday


def _setup(client, db, email):
    with E.today_pinned(DAY):
        rid = register(client, email, "Trenérka", "runner").json()["runner_id"]
        seed_runs(db, rid, days=100, p_run=0.55)
        db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                         models.Activity.started_at == E.day_ago(0)).delete()
        r = db.query(models.Runner).filter(models.Runner.id == rid).first()
        r.engine_mode, r.coach_mode, r.coach_name = "v3", True, "Petr"
        db.commit()
    return rid, r


def _plan(db, rid, rows):
    db.query(models.PlannedSession).filter(models.PlannedSession.runner_id == rid).delete()
    for i, (n, kind, km, extra) in enumerate(rows):
        db.add(models.PlannedSession(runner_id=rid, date=(DAY + timedelta(days=n)).isoformat(), seq=0, kind=kind, km=km,
                                     source="manual", created_at="t", **(extra or {})))
    db.commit()


def _guide(db, rid, r, **patch):
    with E.today_pinned(DAY), E.engine_pinned("v3"):
        a = E.assess(db, rid)
        a.update(patch)
        return G.build_guidance(db, rid, a, r)


def _today(g):
    return g["coach"]["eval"]["today"]


def test_a_plan_inside_the_limits_fits_and_replaces_the_cycle(client, db_session):
    rid, r = _setup(client, db_session, "coach-fit@test.cz")
    _plan(db_session, rid, [(-2, "easy", 8, None), (0, "easy", 6, None), (2, "long", 12, None), (4, "rest", None, None)])
    g = _guide(db_session, rid, r)
    assert g["week"]["mode"] == "coach"
    vol = g["week"]["channels"]["volume"]
    assert vol["budget"] == pytest.approx(26.0, abs=0.1)        # this week's target = the plan's sum
    assert _today(g)[0]["verdict"] == "ok"
    assert any(p["key"] == "plan" for p in g["outlook"]["presets"])  # Výhled na zítra → Podle plánu
    assert g["coach"]["eval"]["week"]["plan"]["volume"] == pytest.approx(26.0, abs=0.1)
    # the Monday plan and the assistant follow the coach's plan
    from app.assistant import facts as AF
    from app.metrics import week_plan as WP
    wp = WP.build({"guidance": g}, DAY)
    assert wp["mode"] == "coach" and wp["headline"].startswith("Týden podle plánu trenéra")
    long_day = next(d for d in wp["days"] if d["date"] == (DAY + timedelta(days=2)).isoformat())
    assert long_day["items"][0]["kind"] == "run" and long_day["items"][0]["km"]["hi"] == 12.0
    lines = AF._coach({"guidance": g})
    assert lines[0].startswith("Běžec trénuje podle plánu trenéra (Petr)") and any("Dlouhý běh" in x for x in lines)


def test_without_a_plan_only_the_safety_limits_apply(client, db_session):
    rid, r = _setup(client, db_session, "coach-empty@test.cz")
    _plan(db_session, rid, [])
    g = _guide(db_session, rid, r)
    vol = g["week"]["channels"]["volume"]
    assert g["week"]["mode"] == "coach" and vol["budget"] is None
    assert vol["limitedBy"] in ("7d", "run", "systemic", "mechanics")


def test_over_the_room_gets_the_smallest_change_that_fits(client, db_session):
    rid, r = _setup(client, db_session, "coach-over@test.cz")
    _plan(db_session, rid, [(0, "quality", 40, {"intervals": "12× 1 km v 4:00"})])
    g = _guide(db_session, rid, r)
    s = _today(g)[0]
    assert s["verdict"] == "mod" and s["over"]
    room = s["room"]
    fit = s["fit"]
    kinds = [c["k"] for c in fit["changes"]]
    assert "km" in kinds
    cap_km = min(v for v in (room["volume"]["day"], room["volume"]["run"]) if v is not None)
    assert fit["km"] <= cap_km * (1 + CP.TOL_REL) + CP.TOL_ABS["volume"] + 0.05
    assert g["coach"]["eval"]["message"].startswith("Ahoj, dnes mám v plánu")


def test_the_body_first_pain_over_5_means_not_today_with_the_apps_option(client, db_session):
    rid, r = _setup(client, db_session, "coach-pain@test.cz")
    _plan(db_session, rid, [(0, "quality", 10, {"intervals": "5x3min"}), (1, "easy", 8, None)])
    with E.today_pinned(DAY):
        db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=7, pain_site="lýtko",
                                      pain_points=[{"region": "lýtko", "side": "L"}]))
        db_session.commit()
    g = _guide(db_session, rid, r)
    s = _today(g)[0]
    assert s["verdict"] == "no" and s["alt"]["type"]
    assert "7/10" in s["why"][0]


def test_hard_sessions_48h_apart_and_a_low_readiness_lightens_quality(client, db_session):
    rid, r = _setup(client, db_session, "coach-rules@test.cz")
    _plan(db_session, rid, [(1, "quality", 10, {"intervals": "6x1km"}), (2, "quality", 10, {"intervals": "tempo 20 min"}),
                            (3, "easy", 6, None)])
    g = _guide(db_session, rid, r)
    days = {d["date"]: d for d in g["coach"]["eval"]["days"]}
    second = days[(DAY + timedelta(days=2)).isoformat()]["sessions"][0]
    assert second["verdict"] == "mod" and any("48 h" in w for w in second["why"])
    # tomorrow's quality after a weak night: the readiness rule of the outlook's scenario
    pt = g["outlook"]["planTomorrow"]["byNight"]
    weak = next(n for n in g["outlook"]["nights"] if n["key"] == "weak")
    if weak["score"] < 65:
        assert pt["weak"]["verdict"] == "mod"


def test_adherence_two_by_two():
    def days(status, km_done):
        return [{"date": f"2026-10-0{i + 1}", "past": True, "today": False,
                 "sessions": [{"kind": "easy", "km": 10.0, "z4": 0, "status": status,
                               "act": {"id": i, "km": km_done} if status != "missed" else None}]} for i in range(5)]
    acts = [{"id": i, "date": f"2026-10-0{i + 1}", "durationMin": 60, "zoneMin": [20, 35, 3, 1, 1], "exp": {}}
            for i in range(5)]
    ok_days = {f"2026-10-0{i + 1}": True for i in range(5)}
    bad_days = {**ok_days, "2026-10-03": False}
    a = CP.adherence(days("done", 10.0), acts, ok_days, {}, {})
    assert a["quad"] == "both" and a["tone"] == "good" and a["easy"] == [5, 5]
    a = CP.adherence(days("done", 10.0), acts, bad_days, {"2026-10-01": 80}, {})
    assert a["quad"] == "plan" and a["tone"] == "ok"           # fine if the body says so
    a = CP.adherence(days("done", 10.0), acts, bad_days, {"2026-10-01": 50}, {"2026-10-02": 4})
    assert a["quad"] == "plan" and a["tone"] == "warn"
    a = CP.adherence(days("missed", 0), acts, ok_days, {}, {})
    assert a["quad"] == "safe" and a["tone"] == "praise" and "trenérem" in a["msg"]
    a = CP.adherence(days("missed", 0), acts, bad_days, {}, {})
    assert a["quad"] == "neither" and a["tone"] == "warn"


def test_pairing_done_partial_missed_and_extra():
    plan = [CP.norm({"id": 1, "date": "2026-10-05", "kind": "easy", "km": 10}, {}),
            CP.norm({"id": 2, "date": "2026-10-06", "kind": "long", "km": 20}, {}),
            CP.norm({"id": 3, "date": "2026-10-07", "kind": "easy", "km": 8}, {}),
            CP.norm({"id": 4, "date": "2026-10-08", "kind": "easy", "km": 8, "activity_id": 0}, {})]
    acts = [{"id": 11, "date": "2026-10-05", "run": True, "sport": "running", "km": 10.4},
            {"id": 12, "date": "2026-10-06", "run": True, "sport": "running", "km": 14.0},
            {"id": 13, "date": "2026-10-06", "run": False, "sport": "cycling", "durationMin": 50},
            {"id": 14, "date": "2026-10-08", "run": True, "sport": "running", "km": 8.0}]
    st, paired, extra = CP.match(plan, acts, "2026-10-09")
    assert st == {1: "done", 2: "partial", 3: "missed", 4: "missed"}
    assert {a["id"] for a in extra} == {13, 14}


# ------------------------------------------------------------------ the API and the coach's link
def _api_runner(client, db, email):
    rid = register(client, email, "Běžkyně Test", "runner").json()["runner_id"]
    seed_runs(db, rid, days=70, p_run=0.55)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    r.engine_mode = "v3"
    db.commit()
    return rid


def test_runner_flow_mode_sessions_import_and_coach_link(client, db_session):
    rid = _api_runner(client, db_session, "coach-api@test.cz")
    st = client.put(f"/api/runners/{rid}/plan/mode", json={"on": True, "name": "Petr"}).json()
    assert st["on"] and st["name"] == "Petr" and st["eval"]["days"]
    today = date.fromisoformat(st["date"])
    st = client.post(f"/api/runners/{rid}/plan/sessions", json={"date": today.isoformat(), "kind": "easy", "km": 7}).json()
    s = next(x for d in st["eval"]["days"] if d["today"] for x in d["sessions"])
    assert s["km"] == 7.0 and (s.get("verdict") in ("ok", "mod", "no") or s["status"] in ("done", "partial", "more"))
    ws = date.fromisoformat(st["weekStart"]) + timedelta(days=7)
    pv = client.post(f"/api/runners/{rid}/plan/import", json={"text": "Po 8 km lehce\nSt 6x1km v 4:30\nSo 16 km dlouhý",
                                                              "week": ws.isoformat()}).json()
    assert pv["via"] == "rules" and len(pv["sessions"]) == 3 and pv["preview"]["verdicts"]
    st = client.post(f"/api/runners/{rid}/plan/confirm", json={"sessions": pv["sessions"], "via": "text"}).json()
    rows = db_session.query(models.PlannedSession).filter(models.PlannedSession.runner_id == rid).all()
    assert len(rows) == 4 and {x.source for x in rows} == {"manual", "text"}
    # no link without consent; with it the coach sees the overview
    assert client.post(f"/api/runners/{rid}/plan/coach-link", json={"consent": False}).status_code == 422
    st = client.post(f"/api/runners/{rid}/plan/coach-link", json={"consent": True, "coach_name": "Petr"}).json()
    token = st["links"][0]["token"]
    client.cookies.clear()
    ov = client.get(f"/api/trener/{token}").json()
    assert ov["runner"]["name"] == "Běžkyně" and len(ov["health"]) == 42 and ov["plan"]
    # the coach's day replaces the runner's for that date
    d = (ws + timedelta(days=2)).isoformat()
    res = client.put(f"/api/trener/{token}/day/{d}", json={"sessions": [{"date": d, "kind": "easy", "km": 5}]}).json()
    assert [x["source"] for x in res["plan"]] == ["coach"] and res["plan"][0]["kind"] == "easy"
    assert client.put(f"/api/trener/{token}/day/{d}", json={"sessions": []},
                      headers={"origin": "https://evil.example"}).status_code == 403
    # a calendar pull never overwrites the coach's day
    db_session.expire_all()
    log = db_session.query(models.CoachAccessLog).filter(models.CoachAccessLog.runner_id == rid).all()
    assert {x.action for x in log} == {"read", "write"}
    # the runner sees it and can revoke
    client.post("/api/auth/session", json={"email": "coach-api@test.cz", "password": "testpass123"})
    al = client.get(f"/api/runners/{rid}/access-log").json()
    assert any(x["actor_role"] == "coach" for x in al)
    client.delete(f"/api/runners/{rid}/plan/coach-link/{token}")
    client.cookies.clear()
    assert client.get(f"/api/trener/{token}").status_code == 404
    assert client.get("/api/trener/not-a-token").status_code == 404


def test_other_runners_cannot_touch_the_plan(client, db_session):
    rid = _api_runner(client, db_session, "coach-own@test.cz")
    client.cookies.clear()
    register(client, "coach-other@test.cz", "Jiný", "runner")
    assert client.get(f"/api/runners/{rid}/plan").status_code == 403
    assert client.put(f"/api/runners/{rid}/plan/mode", json={"on": True}).status_code == 403
    assert client.post(f"/api/runners/{rid}/plan/coach-link", json={"consent": True}).status_code == 403


def test_feed_sync_replaces_only_its_own_sessions(client, db_session, monkeypatch):
    rid = _api_runner(client, db_session, "coach-feed@test.cz")
    client.put(f"/api/runners/{rid}/plan/mode", json={"on": True})
    t = E.today_date()
    d1, d2 = (t + timedelta(days=1)).strftime("%Y%m%d"), (t + timedelta(days=2)).strftime("%Y%m%d")
    ics = (f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:e1\nDTSTART;VALUE=DATE:{d1}\nSUMMARY:Run: Easy 8 km\nEND:VEVENT\n"
           f"BEGIN:VEVENT\nUID:e2\nDTSTART;VALUE=DATE:{d2}\nSUMMARY:Run: Tempo 3 km v 4:15, celkem 10 km\nEND:VEVENT\nEND:VCALENDAR\n")
    monkeypatch.setattr(PI, "check_url", lambda u: u)
    monkeypatch.setattr(PI, "fetch_feed", lambda u: ics)
    st = client.put(f"/api/runners/{rid}/plan/feed", json={"url": "https://calendar.example.com/x.ics"}).json()
    assert st["feed"]["status"]["ok"] and st["feed"]["status"]["n"] == 2 and st["feed"]["set"]
    manual = client.post(f"/api/runners/{rid}/plan/sessions",
                         json={"date": (t + timedelta(days=3)).isoformat(), "kind": "easy", "km": 5}).json()
    assert manual["on"]
    client.post(f"/api/runners/{rid}/plan/feed/sync")
    db_session.expire_all()
    rows = db_session.query(models.PlannedSession).filter(models.PlannedSession.runner_id == rid).all()
    assert sorted(x.source for x in rows) == ["ics", "ics", "manual"]
    q = next(x for x in rows if x.ext_uid == "e2")
    assert q.kind == "quality" and q.km == 10.0
    assert "plan_feed_url" not in client.get(f"/api/runners/{rid}").json()
