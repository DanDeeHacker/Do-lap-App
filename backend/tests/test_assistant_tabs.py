"""The assistant on a tab (product request 2026-10-01): the owner can try it in the
demo rollout, a question asked from a tab defaults to that tab's subject, and each
tab opens with its own summary — cached until the data change, outside the daily
question limit and outside the chat history."""
import pytest

from app import llm, models
from app.assistant import selector as SEL
from app.assistant import service as S
from .test_assistant import _demo, _fake_llm, kb  # noqa: F401 — the fixture
from .test_guidance import _runner


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("DOSSLAP_ASSISTANT", "on")
    S._LLM_PAUSE["until"] = 0.0


def test_owner_gets_the_assistant_in_the_demo_rollout(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_ASSISTANT", "demo")
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "majitel@test.cz")
    rid, r = _runner(client, db_session, "majitel@test.cz")
    u = db_session.query(models.User).filter(models.User.email == "majitel@test.cz").first()
    assert S.access(db_session, r, u)["reason"] == "consent"            # real data still need the AI consent
    r.coach_consent = True
    assert S.access(db_session, r, u)["enabled"]
    rid2, r2 = _runner(client, db_session, "nekdo@test.cz")
    u2 = db_session.query(models.User).filter(models.User.email == "nekdo@test.cz").first()
    assert S.access(db_session, r2, u2)["reason"] == "rollout"          # everyone else waits for "on"


@pytest.mark.parametrize("tab,want", [("training", "plan"), ("load", "load"), ("mechanics", "mechanics"),
                                      ("post", "run"), ("messages", "pain")])
def test_a_vague_question_is_about_the_tab(tab, want):
    sel = SEL.classify("Co s tím mám dělat?", {"kind": "tab", "id": tab})
    assert want in sel["intents"] and not sel["wantGuide"]


def test_a_question_with_its_own_subject_keeps_it():
    sel = SEL.classify("Proč mě bolí koleno?", {"kind": "tab", "id": "mechanics"})
    assert "pain" in sel["intents"] and "mechanics" not in sel["intents"]
    nav = SEL.classify("Kde najdu kvadrant stavu?", {"kind": "tab", "id": "load"})
    assert nav["intents"] == ["app"] and nav["wantGuide"]


def test_tab_summary_is_cached_and_stays_out_of_the_chat(client, kb, monkeypatch):   # noqa: F811
    rid, r, u = _demo(client, kb)
    calls = _fake_llm(monkeypatch, ["Dnes se držte doporučení aplikace a běžte lehce, bez intervalů. [Trénink]"])
    one = S.tab_summary(kb, r, "training", u)
    assert one["source"] == "llm" and one["title"] == "Dnešní trénink" and not one["cached"] and len(calls) == 1
    two = S.tab_summary(kb, r, "training", u)
    assert two["cached"] and two["text"] == one["text"] and len(calls) == 1       # no second model call
    assert S.history(kb, rid) == [] and S._used_today(kb, rid) == 0               # not a question, not in the chat
    other = S.tab_summary(kb, r, "nonsense", u)
    assert other["tab"] == "today"


def test_tab_summary_without_a_model_is_the_apps_own(client, kb, monkeypatch):   # noqa: F811
    monkeypatch.setattr(llm, "assistant_available", lambda: False)
    rid, r, u = _demo(client, kb)
    out = S.tab_summary(kb, r, "today", u)
    assert out["source"] == "fallback" and out["text"]


def test_summary_api_needs_access(client, kb, monkeypatch):   # noqa: F811
    from .conftest import register
    rid = register(client, "bezsouhlasu@test.cz", "Bez", "runner").json()["runner_id"]
    r = client.get(f"/api/runners/{rid}/assistant/summary?tab=load")
    assert r.status_code == 403


def test_a_short_rate_limit_is_waited_out(client, kb, monkeypatch):   # noqa: F811
    rid, r, u = _demo(client, kb)
    slept, calls = [], []

    def fake(messages, temperature=0.25, max_tokens=700, timeout=60.0, model=None, base_url=None, api_key=None):
        calls.append(1)
        if len(calls) == 1:
            llm.LAST_ERROR["chat"] = {"status": 429, "body": "Please try again in 2.7s. Need more tokens?"}
            return None
        return "Dnes se držte doporučení aplikace a běžte lehce, bez intervalů."
    monkeypatch.setattr(llm, "assistant_available", lambda: True)
    monkeypatch.setattr(llm, "chat_messages", fake)
    monkeypatch.setattr(S.time, "sleep", lambda s: slept.append(s))
    out = S.ask(kb, r, "Co mám dnes běžet?", user=u)
    assert out["source"] == "llm" and len(calls) == 2 and slept and slept[0] < S.RATE_WAIT_MAX
    assert S._LLM_PAUSE["until"] == 0.0                                  # no pause after a recovered call
