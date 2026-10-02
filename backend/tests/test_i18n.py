"""British English (translation request 2026-10-02): the account language, set at
registration and switchable later, and the AI assistant answering in English
while its pipeline and safety validator stay Czech."""
import pytest

from app import llm, models
from app import translate as T
from .test_assistant import _demo, _reset_llm_pause, kb  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _assistant_on(monkeypatch):
    monkeypatch.setenv("DOSSLAP_ASSISTANT", "on")
    _reset_llm_pause()


def test_language_is_chosen_at_registration_and_switchable(client):
    r = client.post("/api/auth/register", json={"email": "en1@test.cz", "password": "testpass123", "name": "Ann",
                                                "role": "runner", "lang": "en"})
    assert r.status_code in (200, 201)
    assert client.get("/api/auth/me").json()["lang"] == "en"
    assert client.put("/api/auth/lang", json={"lang": "cs"}).status_code == 200
    assert client.get("/api/auth/me").json()["lang"] == "cs"
    assert client.put("/api/auth/lang", json={"lang": "de"}).status_code == 422


def test_registration_defaults_to_czech(client):
    client.post("/api/auth/register", json={"email": "cs1@test.cz", "password": "testpass123", "name": "Bára",
                                            "role": "runner"})
    assert client.get("/api/auth/me").json()["lang"] == "cs"


def test_a_translation_must_keep_numbers_and_citations():
    src = "Připravenost 74 %, strop 7,4 km [1]. Od 3. 10. lehce [2]."
    assert T._ok(src, "Readiness 74 %, ceiling 7.4 km [1]. From 3 Oct easy [2].")
    assert not T._ok(src, "Readiness 74 %, ceiling 7.4 km [1]. From 3 Oct easy.")      # citation lost
    assert not T._ok(src, "Readiness 47 %, ceiling 7.4 km [1]. From 3 Oct easy [2].")   # number changed
    assert not T._ok(src, "")


def _fake(monkeypatch):
    calls = []

    def fake(messages, temperature=0.25, max_tokens=700, timeout=60.0, model=None, base_url=None, api_key=None):
        system = messages[0]["content"]
        calls.append(system)
        if system == T.SYSTEM_CS:
            return "Můžu dnes dát intervaly?"
        if system == T.SYSTEM_EN:
            return "Today stick to the app's recommendation and run easy, without intervals."
        return "Dnes se držte doporučení aplikace a běžte lehce, bez intervalů."
    monkeypatch.setattr(llm, "assistant_available", lambda: True)
    monkeypatch.setattr(llm, "chat_messages", fake)
    return calls


def test_english_question_gets_a_validated_answer_in_british_english(client, kb, monkeypatch):  # noqa: F811
    rid, r, u = _demo(client, kb)
    calls = _fake(monkeypatch)
    out = client.post(f"/api/runners/{rid}/assistant/ask", json={"question": "Can I do intervals today?"},
                      headers={"X-Doslap-Lang": "en"}).json()
    assert out["lang"] == "en" and out["text"].startswith("Today stick to")
    assert calls[0] == T.SYSTEM_CS and calls[-1] == T.SYSTEM_EN
    # the runner sees their own words; the history comes back in English from the cache
    n = len(calls)
    hist = client.get(f"/api/runners/{rid}/assistant", headers={"X-Doslap-Lang": "en"}).json()["history"]
    assert hist[-2]["text"] == "Can I do intervals today?" and hist[-1]["text"].startswith("Today stick to")
    assert len(calls) == n
    assert kb.query(models.Translation).filter(models.Translation.lang == "en").count() == 1
    # Czech stays Czech
    cs = client.get(f"/api/runners/{rid}/assistant").json()["history"]
    assert cs[-1]["text"].startswith("Dnes se držte")


def test_a_failed_translation_shows_the_czech_original(client, kb, monkeypatch):  # noqa: F811
    rid, r, u = _demo(client, kb)
    _fake(monkeypatch)
    monkeypatch.setattr(llm, "chat_messages", lambda messages, **kw: "Dnes raději lehce a krátce, bez intervalů.")
    monkeypatch.setattr(T, "_llm", lambda system, text, max_tokens: None)
    out = client.post(f"/api/runners/{rid}/assistant/ask", json={"question": "Můžu dnes dát intervaly?"},
                      headers={"X-Doslap-Lang": "en"}).json()
    assert out["lang"] == "cs" and out["text"]


def test_every_evidence_card_has_an_english_version():
    from app.assistant import knowledge as K
    en = T._cards_en()
    for c in K.cards():
        assert c["id"] in en and all(en[c["id"]].get(k) for k in ("title", "claim", "limits")), c["id"]
        # the numbers of the claim survive the translation
        assert T._ok(c["claim"], en[c["id"]]["claim"]), c["id"]


def test_english_status_suggestions_disclaimer_and_sources(client, kb, monkeypatch):  # noqa: F811
    rid, r, u = _demo(client, kb)
    st = client.get(f"/api/runners/{rid}/assistant", headers={"X-Doslap-Lang": "en"}).json()
    assert st["disclaimer"] == T.DISCLAIMER_EN
    assert st["suggestions"] and all(q in T.SUGGESTIONS_EN.values() for q in st["suggestions"])
    card = {"n": 1, "kind": "card", "id": "a-10-procent", "title": "Pravidlo 10 % není prokázané", "claim": "x",
            "limits": "y", "strength": "střední"}
    out = T.sources_en([card, {"n": 2, "kind": "summary", "id": "buist-et-al-2008", "title": "Buist et al. (2008)"}])
    assert out[0]["title"] == "The 10 % rule is not proven" and out[0]["strength"] == "střední"
    assert out[1]["title"] == "Buist et al. (2008)"
