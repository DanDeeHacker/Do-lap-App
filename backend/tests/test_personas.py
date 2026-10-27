"""Simulated runners (owner request 2026-10-27): the switch, the persona's own clock, a simulated
day end to end, the checks, filing into Inbox (dedupe, cap, reopen, verified), the usage consent
and the anonymous behaviour profile with its group floor, and the calibration import."""
from datetime import date, timedelta

import pytest

from app import models, team as T
from app.deps import reset_team_cache
from app.personas import calibration as CAL, checks as CH, sim as S

from .conftest import register

TOKEN = "persona-test-token"
H = {"X-Persona-Token": TOKEN}


@pytest.fixture()
def personas_on(monkeypatch):
    monkeypatch.setenv("DOSSLAP_PERSONAS", "on")
    monkeypatch.setenv("DOSSLAP_PERSONA_TOKEN", TOKEN)
    monkeypatch.delenv("DOSSLAP_PERSONA_REPORT_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    reset_team_cache()
    yield


def test_off_by_default_and_never_in_production(client, monkeypatch):
    monkeypatch.delenv("DOSSLAP_PERSONAS", raising=False)
    assert not S.enabled()
    assert client.get("/api/personas", headers=H).status_code == 404
    monkeypatch.setenv("DOSSLAP_PERSONAS", "on")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    assert not S.enabled()


def test_token_or_team_only(client, personas_on, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "")
    register(client, "pers-cizi@test.cz", "Cizí", "runner")
    assert client.get("/api/personas").status_code == 403
    assert client.get("/api/personas", headers={"X-Persona-Token": "spatne"}).status_code == 403
    r = client.get("/api/personas", headers=H)
    assert r.status_code == 200 and {p["key"] for p in r.json()["personas"]} == {"tereza", "martin", "jana", "eva", "pavel"}


def test_a_simulated_day_runs_on_the_personas_clock(client, personas_on, db_session):
    r = client.post("/api/personas/tereza/reset", json={"seed": 3}, headers=H)
    assert r.status_code == 200, r.text
    start = r.json()["startDate"]
    assert date.fromisoformat(start) < date.today()                     # simulated weeks in the past
    r = client.post("/api/personas/tereza/advance", json={"days": 1, "to": "morning"}, headers=H).json()
    assert r["phase"] == "morning" and r["simDate"] == start
    # the browser signs in as the persona and the app shows the simulated day
    s = client.post("/api/personas/tereza/session", headers=H)
    assert s.status_code == 200 and s.json()["clock"].startswith(f"{start}T07:30")
    wp = client.get(f"/api/runners/{r['runnerId']}/week-plan").json()["plan"]
    monday = date.fromisoformat(start) - timedelta(days=date.fromisoformat(start).weekday())
    assert wp["weekStart"] == monday.isoformat()
    assert any(d["today"] and d["date"] == start for d in wp["days"])
    r = client.post("/api/personas/tereza/advance", json={"days": 1}, headers=H).json()
    assert r["phase"] == "evening" and r["simDate"] == start and r["stats"]["days"] == 1
    days = client.get("/api/personas/tereza/days", headers=H).json()["days"]
    assert days[0]["date"] == start and days[0]["morning"]["type"] and "did" in days[0]
    # the persona's account is not a pilot runner
    pilot = {g["key"]: g for g in T.pilot(db_session)["gates"]}
    assert all(u.provider != "persona" for u in T._pilot_runner_users(db_session)) and pilot["runners"]["value"] >= 0


def test_checks_name_what_breaks():
    ctx = {"persona": "eva", "name": "Eva", "label": "x", "day": 20, "date": "2026-09-01", "events":
           [{"kind": "illness", "from": 18, "to": 22}], "checkin": True, "stats": {}, "goal": None, "start": "2026-08-12"}
    snap = {"type": "kvalitní", "typeLabel": "Kvalitní trénink", "readiness": 120, "todayMax": 6.0,
            "types": {"kvalitní": {"allowed": True}, "dlouhý": {"allowed": False}},
            "planToday": [{"kind": "run", "type": "dlouhý", "label": "Dlouhý běh", "km": {"lo": 8, "hi": 9}}],
            "report": {"type": "lehký", "label": "Lehký běh"}, "weekTotals": {"km": 30, "kmBudget": 25}}
    got = {f["check"] for f in CH.morning_checks(None, "x", snap, ctx)}
    assert {"plan-forbidden", "plan-over-limit", "report-mismatch", "readiness-range", "week-budget", "illness-allows-hard"} <= got
    # km already run are not the plan's fault: only what is still to come counts against the target
    mid = {**snap, "weekTotals": {"km": 30, "kmBudget": 25, "kmDone": 20}, "planToday": [], "report": {}, "readiness": 50}
    assert "week-budget" in {f["check"] for f in CH.morning_checks(None, "x", mid, {**ctx, "events": []})}
    ok = {**mid, "weekTotals": {"km": 30, "kmBudget": 25, "kmDone": 26}}
    assert "week-budget" not in {f["check"] for f in CH.morning_checks(None, "x", ok, {**ctx, "events": []})}


def _finding(check="plan-forbidden", key="dlouhý"):
    return {"check": check, "route": "/app/training", "key": key, "title": "Trénink plánuje, co Dnes nedovoluje",
            "detail": "Persona Eva, den 20", "type": "bug"}


def test_filing_dedupes_caps_reopens_and_verifies(client, personas_on, monkeypatch, db_session):
    monkeypatch.setenv("DOSSLAP_SYNTHETIC_DAILY_CAP", "2")
    assert client.post("/api/team/synthetic-notes", json={"items": []}).status_code == 401
    post = lambda body: client.post("/api/team/synthetic-notes", json=body, headers=H).json()   # noqa: E731
    from app.personas import filing as F
    one = F.payload("eva", [_finding()], "2026-09-01")
    db_session.query(models.Annotation).filter(models.Annotation.source.isnot(None)).delete()
    db_session.commit()
    assert post(one)["created"] == 1
    assert post(one)["repeats"] == 1                                         # same problem, same note
    res = post(F.payload("eva", [_finding(key="a"), _finding(key="b")], "2026-09-02"))
    assert res["created"] == 1 and res["capped"] == 1                       # daily cap 2
    db_session.expire_all()
    a = db_session.query(models.Annotation).filter(models.Annotation.fingerprint == F.fingerprint(_finding())).one()
    assert a.source == "synthetic" and a.approved_at is None and (a.context_json or {}).get("repeats") == 2
    # resolved, then the check passes again → verified; then it recurs → reopened
    a.status, a.resolution = "done", "Vydáno v PR #5"
    db_session.commit()
    assert post(F.payload("eva", [], "2026-09-03", passed=["plan-forbidden"]))["verified"] == 1
    db_session.expire_all()
    assert db_session.get(models.Annotation, a.id).context_json["verifiedAt"]
    assert post(one)["reopened"] == 1
    db_session.expire_all()
    a = db_session.get(models.Annotation, a.id)
    assert a.status == "open" and "Znovu se objevilo" in a.resolution and "verifiedAt" not in a.context_json


def test_synthetic_notes_show_in_inbox_and_need_approval(client, personas_on, monkeypatch, db_session):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "pers-majitel@test.cz")
    from app.personas import filing as F
    client.post("/api/team/synthetic-notes", json=F.payload("jana", [_finding(key="inbox")], "2026-09-05"), headers=H)
    register(client, "pers-majitel@test.cz", "Majitel", "runner")
    items = client.get("/api/team/inbox?source=synthetic").json()["items"]
    mine = next(x for x in items if x["synthetic"] and x["synthetic"]["check"] == "plan-forbidden")
    assert mine["synthetic"]["persona"] == "Jana" and not mine["ready"]
    assert all(x["source"] is None for x in client.get("/api/team/inbox?source=people").json()["items"])


def _usage(db, uid, days=10, hour=7):
    t = date.today()
    for k in range(days):
        db.add(models.UsageDay(user_id=uid, day=(t - timedelta(days=k)).isoformat(), tab="_app", hour=hour, seconds=0, views=1))
        db.add(models.UsageDay(user_id=uid, day=(t - timedelta(days=k)).isoformat(), tab="today", hour=hour, seconds=240, views=2))
        db.add(models.UsageDay(user_id=uid, day=(t - timedelta(days=k)).isoformat(), tab="training", hour=hour, seconds=60, views=1))


def test_behaviour_profile_needs_consent_and_five_people(client, personas_on, monkeypatch, db_session):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "pers-majitel2@test.cz")
    db_session.query(models.Settings).update({models.Settings.share_usage: False})
    db_session.commit()
    ids = []
    for i in range(6):
        register(client, f"pers-souhlas{i}@test.cz", f"Běžec {i}", "runner")
        if i < 4:
            assert client.patch("/api/auth/settings", json={"share_usage": True}).json()["share_usage"] is True
        u = db_session.query(models.User).filter(models.User.email == f"pers-souhlas{i}@test.cz").one()
        ids.append(u.id)
        _usage(db_session, u.id)
    db_session.commit()
    assert CAL.profile(db_session)["groups"] == {}                         # 4 people: nothing leaves
    s = db_session.query(models.Settings).filter(models.Settings.user_id == ids[4]).one()
    s.share_usage = True
    db_session.commit()
    prof = CAL.profile(db_session)
    g = prof["groups"]["all"]
    assert g["n"] == 5 and g["topHours"][0] == 7 and g["open"] > 0.1 and g["tabs"]["today"] > g["tabs"]["training"]
    assert "user_id" not in str(prof) and "@" not in str(prof)              # no per-person rows
    register(client, "pers-majitel2@test.cz", "Majitel", "runner")
    assert client.get("/api/team/behaviour-profile").json()["groups"]["all"]["n"] == 5
    # staging imports it; the personas' habits move halfway to the group
    assert client.post("/api/personas/calibration", json={"kind": "x"}, headers=H).status_code == 422
    r = client.post("/api/personas/calibration", json=prof, headers=H)
    assert r.status_code == 200
    beh = client.get("/api/personas/calibration", headers=H).json()["behaviour"]["tereza"]
    assert beh["calibrated"] and beh["hours"] == [7] and beh["tabs"]["today"] > 0
