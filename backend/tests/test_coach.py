"""AI coach phase 1 — facts packets, the validator, the deterministic fallbacks
and the generation service (consent, caching, regeneration, fallback)."""
import json
import re
from datetime import date

import pytest

from app import llm, models
from app.metrics import coach_facts as F
from app.metrics import coach_texts as CT
from app.metrics import coach_validate as V
from app.metrics import engine as E
from .conftest import register

FACTS = {
    "kind": "daily", "date": "25. 9.",
    "state": {"quadrant": "Přetížení", "risk": "Vysoké riziko", "overallScore": 78},
    "referral": {"code": "physio_48h", "text": "Objednat fyzioterapeuta do 48 hodin", "physio": True},
    "signals": [{"name": "Objem nad kapacitou", "value": "×3,4",
                 "detail": "Posledních 7 dní 171,1 km proti vaší týdenní kapacitě 65,3 km"}],
    "recovery": {"readinessPct": 77, "sleepH": {"now": "4,5", "usual": "5,0"}},
    "lastRun": {"date": "24. 9.", "km": "20,7", "pace": "5:47/km"},
    "today": {"type": "volno", "label": "Volno", "reasons": ["Odlehčovací týden (objem ×0,7)."]},
}
GOOD = ("Dnes je váš stav Přetížení s vysokým rizikem. Za posledních 7 dní jste naběhali 171,1 km, "
        "tedy ×3,4 vaší týdenní kapacity 65,3 km. Připravenost je 77 % a spali jste 4,5 h místo obvyklých 5,0 h. "
        "Dnes máte volno. Aplikace doporučuje objednat fyzioterapeuta do 48 hodin.")


def codes(kind, text, facts=FACTS):
    return {i["code"] for i in V.validate(kind, text, facts)["issues"]}


# ---------------------------------------------------------------- validator
def test_a_faithful_text_passes():
    assert V.validate("daily_summary", GOOD, FACTS) == {"ok": True, "issues": []}
    # rounding, the decimal dot, a range of days, a citation year and a pace from the facts are all fine
    ok = GOOD + " Odpočívejte 2 dny, jak doporučuje literatura (Nielsen 2014); poslední běh 24. 9. v tempu 5:47/km."
    assert V.validate("daily_summary", ok.replace("171,1", "171"), FACTS)["ok"]


@pytest.mark.parametrize("swap, code", [
    (("171,1 km", "180 km"), "number_not_in_facts"),
    (("77 %", "85 %"), "number_not_in_facts"),
    (("Dnes máte volno.", "Dnes máte volno, poslední běh byl 23. 9."), "number_not_in_facts"),
    (("Dnes máte volno.", "Dnes máte volno, minule jste běželi 4:55/km."), "number_not_in_facts"),
    (("Aplikace doporučuje objednat fyzioterapeuta do 48 hodin.", "Odpočívejte."), "missing_referral"),
])
def test_invented_facts_and_a_missing_referral_are_caught(swap, code):
    assert code in codes("daily_summary", GOOD.replace(*swap))


def test_commentary_must_follow_the_recommendation():
    base = "Aplikace doporučuje objednat fyzioterapeuta do 48 hodin."
    assert "recommendation_missing" in codes("daily_commentary", f"Dnes si dejte klidnou procházku a protažení. {base} " * 2)
    push = f"Dnes máte volno, ale krátké intervaly vám neuškodí. {base}"
    assert "contradicts_recommendation" in codes("daily_commentary", push * 2)
    fine = (f"Dnes máte volno. Žádné intervaly ani tempový běh, nohy potřebují odpočinek. "
            f"Po včerejším dlouhém běhu je to rozumné. {base}")
    assert V.validate("daily_commentary", fine, FACTS)["ok"], V.validate("daily_commentary", fine, FACTS)


@pytest.mark.parametrize("extra, code", [
    ("Na bolest si vezměte ibuprofen.", "medication"),
    ("Pravděpodobně máte zánět Achillovy šlachy.", "diagnosis"),
    ("Běžte klidně i přes bolest.", "run_through_pain"),
    ("Tímhle postupem se zaručeně nezraníte.", "promise"),
    ("Více na https://example.com.", "link"),
])
def test_unsafe_content_is_caught(extra, code):
    assert code in codes("daily_summary", f"{GOOD} {extra}")


def test_language_and_length():
    english = ("Today you are overreaching with a high risk. You ran a lot this week, more than your capacity. "
               "Readiness is lower than usual and sleep was short. Take a rest day and see a physio soon please.")
    assert "not_czech" in codes("daily_summary", english)
    assert "length" in codes("daily_summary", "Volno. Fyzioterapeut.")


# ---------------------------------------------------------------- facts + fallbacks on real (seeded) data
def _clone_runner(client, db, email, src_email="kritickepretizeni@demo.cz", mode="v3"):
    """A private copy of a demo runner's data, so tests can switch the engine and
    consent without touching the shared demo runners."""
    src = db.query(models.User).filter(models.User.email == src_email).first().runner_id
    rid = register(client, email, "Klon Běžec", "runner").json()["runner_id"]
    s = db.query(models.Runner).filter(models.Runner.id == src).first()
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    for col in ("birth_year", "sex", "prior_injury", "prior_injury_months_ago", "device", "city"):
        setattr(r, col, getattr(s, col))
    r.engine_mode = mode
    skip = {"id", "runner_id"}
    for M in (models.Activity, models.DailyMetric, models.Checkin, models.ActivityFeedback):
        for row in db.query(M).filter(M.runner_id == src).all():
            data = {c.name: getattr(row, c.name) for c in M.__table__.columns if c.name not in skip}
            if M is models.Activity:
                data["external_id"] = f"{email}-{row.id}"
            db.add(M(runner_id=rid, **data))
    db.commit()
    return rid


def test_facts_are_engine_values_without_identity(client, db_session):
    rid = _clone_runner(client, db_session, "coach1@test.cz")
    a = E.recompute_assessment(db_session, rid)
    runner = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
    for facts in (F.daily_facts(db_session, rid, a), F.weekly_facts(db_session, rid, a, F.week_bounds(E.today_date())[0])):
        dump = json.dumps(facts, ensure_ascii=False)
        for secret in (runner.name, "coach1@test.cz", runner.city or "@@", rid):
            assert secret not in dump
        assert not {"lat", "lon", "start_lat", "start_lon", "email", "city", "title_raw", "notes_raw"} & set(_keys(facts))
        assert not re.search(r"\d\.\d", dump)          # Czech decimal comma throughout
    d = F.daily_facts(db_session, rid, a)
    assert d["today"]["type"] == a["guidance"]["type"] and d["referral"]["code"] == E.triage_decision(a)


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


@pytest.mark.parametrize("src", ["kritickepretizeni@demo.cz", "tichydrift@demo.cz", "adela@demo.cz"])
@pytest.mark.parametrize("mode", ["v1", "v3"])
def test_fallback_texts_always_pass_the_validator(client, db_session, src, mode):
    rid = _clone_runner(client, db_session, f"fb-{mode}-{src}", src, mode)
    a = E.recompute_assessment(db_session, rid)
    for kind, _period, facts in CT.plan(db_session, rid, a):
        text = CT.FALLBACK[kind](facts)
        assert V.validate(kind, text, facts)["ok"], (kind, V.validate(kind, text, facts), text)


def test_week_bounds_are_the_last_completed_week():
    assert F.week_bounds(date(2026, 9, 25)) == (date(2026, 9, 14), date(2026, 9, 20))
    assert F.week_bounds(date(2026, 9, 21)) == (date(2026, 9, 14), date(2026, 9, 20))   # Monday → last week
    assert F.week_bounds(date(2026, 9, 20)) == (date(2026, 9, 7), date(2026, 9, 13))


def test_prompts_are_versioned_and_complete():
    for kind in CT.KINDS:
        version, text = CT.prompt(kind)
        assert version.endswith("+_rules.v1") and "{rules}" not in text and "fyzioterapeut" in text


# ---------------------------------------------------------------- the service
@pytest.fixture()
def fake_llm(monkeypatch):
    calls = []
    state = {"reply": lambda system, user: CT.FALLBACK[_kind(system)](_facts(user))}
    monkeypatch.setattr(llm, "available", lambda: True)

    def chat(system, user, temperature=0.25, max_tokens=700, timeout=60.0):
        calls.append(system)
        return state["reply"](system, user)
    monkeypatch.setattr(llm, "chat", chat)
    return state, calls


def _kind(system):
    return next(k for k in CT.KINDS if CT.prompt(k)[1] == system)


def _facts(user_msg):
    return json.loads(user_msg.split("```json\n", 1)[1].split("\n```", 1)[0])


def _consent(db, rid, on=True):
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    r.coach_consent = on
    db.commit()


def _rows(db, rid):
    db.expire_all()
    return db.query(models.CoachText).filter(models.CoachText.runner_id == rid).order_by(models.CoachText.id).all()


def test_nothing_without_consent_and_fallback_without_a_model(client, db_session):
    rid = _clone_runner(client, db_session, "coach2@test.cz")
    assert CT.refresh_runner(db_session, rid) == {"skipped": "no_consent"}
    _consent(db_session, rid)
    res = CT.refresh_runner(db_session, rid)
    assert res["generated"] == {"daily_summary": "fallback", "daily_commentary": "fallback", "weekly_summary": "fallback"}
    row = _rows(db_session, rid)[0]
    assert row.issues_json == [{"code": "llm_unavailable"}] and row.text == CT.FALLBACK[row.kind](row.facts_json)
    assert CT.refresh_runner(db_session, rid) == {"generated": {}}          # same facts → cached


def test_model_text_is_used_when_valid_and_rejected_when_not(client, db_session, fake_llm):
    state, calls = fake_llm
    rid = _clone_runner(client, db_session, "coach3@test.cz")
    _consent(db_session, rid)
    assert set(CT.refresh_runner(db_session, rid)["generated"].values()) == {"llm"}
    assert all(r.source == "llm" and r.model == llm.NVIDIA_MODEL for r in _rows(db_session, rid))
    # a model that invents a number: the runner gets the deterministic text, the raw output is kept
    CT.forget(db_session, rid)
    state["reply"] = lambda s, u: CT.FALLBACK[_kind(s)](_facts(u)) + " Zítra zkuste 42,4 km."
    CT.refresh_runner(db_session, rid)
    rows = _rows(db_session, rid)
    assert all(r.source == "fallback" and "42,4 km" in r.llm_text for r in rows)
    assert all(any(i["code"] == "number_not_in_facts" for i in r.issues_json) for r in rows)


def test_texts_follow_new_facts_and_a_model_coming_online(client, db_session, monkeypatch):
    rid = _clone_runner(client, db_session, "coach4@test.cz")
    _consent(db_session, rid)
    CT.refresh_runner(db_session, rid)
    n = len(_rows(db_session, rid))
    client.post("/api/auth/session", json={"email": "coach4@test.cz", "password": "testpass123"})
    client.post(f"/api/runners/{rid}/checkins", json={"pain_score": 6, "pain_site": "Koleno (L)", "soreness": 3})
    kinds = [r.kind for r in _rows(db_session, rid)[n:]]
    assert "daily_summary" in kinds                                      # check-in → regenerated in the background
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda s, u, **kw: CT.FALLBACK[_kind(s)](_facts(u)))
    m = len(_rows(db_session, rid))
    CT.refresh_runner(db_session, rid)
    assert {r.source for r in _rows(db_session, rid)[m:]} == {"llm"}      # fallback-for-no-model is retried


def test_endpoints_consent_and_access(client, db_session):
    rid = _clone_runner(client, db_session, "coach5@test.cz")
    client.post("/api/auth/session", json={"email": "coach5@test.cz", "password": "testpass123"})
    s = client.get(f"/api/runners/{rid}/coach").json()
    assert s["consent"] is False and "texts" not in s
    assert client.put(f"/api/runners/{rid}/coach/consent", json={"consent": True}).json()["consent"] is True
    s = client.get(f"/api/runners/{rid}/coach").json()                  # opt-in generated in the background
    assert s["pending"] == [] and s["texts"]["daily_summary"]["source"] == "fallback"
    assert s["texts"]["daily_commentary"]["text"] and s["texts"]["weekly_summary"]["period"]
    assert client.post(f"/api/runners/{rid}/coach/refresh").status_code == 202
    assert client.put(f"/api/runners/{rid}/coach/consent", json={"consent": False}).json()["consent"] is False
    assert _rows(db_session, rid) == []                                  # opting out deletes the texts
    register(client, "coach6@test.cz", "Cizí", "runner")
    client.post("/api/auth/session", json={"email": "coach6@test.cz", "password": "testpass123"})
    assert client.get(f"/api/runners/{rid}/coach").status_code in (403, 404)
    assert client.put(f"/api/runners/{rid}/coach/consent", json={"consent": True}).status_code == 403


def test_advice_not_to_run_through_pain_is_fine():
    assert V.validate("daily_summary", GOOD + " Nikdy neběhejte přes bolest.", FACTS)["ok"]
    assert "run_through_pain" in codes("daily_summary", GOOD + " Zkuste to dokončit i přes bolest.")


def test_daily_run_covers_every_consenting_runner(client, db_session, fake_llm):
    from app.db import SessionLocal
    a = _clone_runner(client, db_session, "coach7@test.cz")
    b = _clone_runner(client, db_session, "coach8@test.cz", "tichydrift@demo.cz", "v1")
    c = _clone_runner(client, db_session, "coach9@test.cz")
    _consent(db_session, a)
    _consent(db_session, b)
    res = CT.generate_all(SessionLocal)
    assert set(res["results"]) >= {a, b} and c not in res["results"]
    assert {r.kind for r in _rows(db_session, a)} == set(CT.KINDS)
    assert {r.kind for r in _rows(db_session, b)} == {"daily_summary", "weekly_summary"}   # v1: no training commentary
    assert _rows(db_session, c) == []
