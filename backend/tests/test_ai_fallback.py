"""Physio brief 2026-11-09 P0.1: the physio's AI overview and chat are honest about where the text
comes from, answer at once when no model is configured, never send runner data out without the
runner's AI consent, and the visit recording answers at once when transcription is off."""
import time

import httpx

from app import llm, models
from app.metrics import ai_brief as AB
from app.metrics import engine as E

from .conftest import login, register

PHYSIO = "havlickova@fyzioholesovice.cz"


class FakeResp:
    def __init__(self, text, status=200):
        self.status_code, self._text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def _no_network(*a, **k):
    raise AssertionError("no external call expected")


def test_without_a_model_both_answer_at_once_and_say_so(client, monkeypatch):
    monkeypatch.setattr(llm, "NVIDIA_API_KEY", None)
    monkeypatch.setattr(httpx, "post", _no_network)
    login(client, PHYSIO)
    caps = client.get("/api/physios/me").json()["capabilities"]
    assert caps["llm"] is False and caps["hypotheses"] is False
    t0 = time.time()
    b = client.post("/api/ai/brief", json={"runner_id": "run-0001", "intent": "summary"}).json()
    c = client.post("/api/ai/chat", json={"runner_id": "run-0001", "message": "Co se změnilo?"}).json()
    assert time.time() - t0 < 2.0
    assert (b["source"], b["reason"], b["llm"]) == ("template", "not_configured", False)
    assert (c["source"], c["reason"]) == ("template", "not_configured")
    assert "Bez nakonfigurovaného" not in c["reply"]


def test_no_external_call_without_the_runners_consent(client, db_session, monkeypatch):
    monkeypatch.setattr(llm, "NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", _no_network)
    rid = register(client, "bez-souhlasu@ai.test.cz", "Bez Souhlasu", "runner").json()["runner_id"]
    db_session.add(models.CareAssignment(physio_id="phy-0001", runner_id=rid, status="active", created_at=E.now_iso()))
    db_session.commit()
    login(client, PHYSIO)
    b = client.post("/api/ai/brief", json={"runner_id": rid, "intent": "summary"}).json()
    c = client.post("/api/ai/chat", json={"runner_id": rid, "message": "Jak běhá?"}).json()
    assert b["reason"] == "no_consent" and c["reason"] == "no_consent"


def test_with_a_model_two_questions_get_two_answers_and_the_brief_is_cached(client, monkeypatch):
    monkeypatch.setattr(llm, "NVIDIA_API_KEY", "test-key")
    calls = []

    def fake_post(url, json=None, **k):
        calls.append(json)
        return FakeResp("Odpověď na: " + json["messages"][-1]["content"][:40])
    monkeypatch.setattr(httpx, "post", fake_post)
    AB._CACHE.clear()
    login(client, PHYSIO)
    a1 = client.post("/api/ai/chat", json={"runner_id": "run-0001", "message": "Jak se měnila zátěž?"}).json()
    a2 = client.post("/api/ai/chat", json={"runner_id": "run-0001", "message": "Jak spí?"}).json()
    assert a1["source"] == "llm" and a1["reply"] != a2["reply"]
    n = len(calls)
    b1 = client.post("/api/ai/brief", json={"runner_id": "run-0001", "intent": "summary"}).json()
    b2 = client.post("/api/ai/brief", json={"runner_id": "run-0001", "intent": "summary"}).json()
    assert b1["source"] == b2["source"] == "llm" and len(calls) == n + 1      # second one from the cache


def test_a_timeout_falls_back_with_the_reason(client, monkeypatch):
    monkeypatch.setattr(llm, "NVIDIA_API_KEY", "test-key")

    def slow(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "post", slow)
    AB._CACHE.clear()
    login(client, PHYSIO)
    c = client.post("/api/ai/chat", json={"runner_id": "run-0001", "message": "Co dál?"}).json()
    assert (c["source"], c["reason"]) == ("template", "timeout")


def test_transcription_off_answers_without_reading_or_calling(client, db_session, monkeypatch):
    monkeypatch.setattr(llm, "ASR_BASE_URL", None)
    monkeypatch.setattr(llm, "transcribe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ASR call")))
    login(client, PHYSIO)
    bk = db_session.query(models.Booking).filter(models.Booking.physio_id == "phy-0001",
                                                 models.Booking.runner_id == "run-0001").first()
    cid = client.post(f"/api/bookings/{bk.id}/conclusion/draft", json={"summary": "x"}).json()["id"]
    r = client.post(f"/api/conclusions/{cid}/audio", files={"file": ("a.webm", b"0" * 10, "audio/webm")}).json()
    assert r["asr_available"] is False and "ručně" in r["note"]


def test_a_failed_transcription_keeps_nothing(client, db_session, monkeypatch):
    monkeypatch.setattr(llm, "ASR_BASE_URL", "https://asr.invalid")
    monkeypatch.setattr(llm, "ASR_API_KEY", "k")

    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(llm, "transcribe", boom)
    login(client, PHYSIO)
    bk = db_session.query(models.Booking).filter(models.Booking.physio_id == "phy-0001",
                                                 models.Booking.runner_id == "run-0001").first()
    cid = client.post(f"/api/bookings/{bk.id}/conclusion/draft", json={"summary": "x"}).json()["id"]
    try:
        client.post(f"/api/conclusions/{cid}/audio", files={"file": ("a.webm", b"0" * 10, "audio/webm")})
    except RuntimeError:
        pass
    db_session.expire_all()
    c = db_session.get(models.Conclusion, cid)
    assert c is None or not c.transcript       # nothing of the recording is stored
