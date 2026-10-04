"""NVIDIA NIM client — OpenAI-compatible chat completions
(https://build.nvidia.com/nim), used to turn ai_brief.py's deterministically
computed facts into natural clinical prose.

Entirely optional: `available()` is False until NVIDIA_API_KEY is set in the
environment, and every caller must have a non-LLM fallback ready — see
ai_brief.py, which always computes its structured, numerically-exact
sections first and only *adds* an LLM narrative on top when one comes back.
The LLM is never the sole carrier of a fact; it narrates facts that were
already computed deterministically, which is what keeps this safe from
hallucinating numbers that were never true.

Get a free key at https://build.nvidia.com/nim (sign in, pick a model,
"Get API Key"). Then either:
    setx NVIDIA_API_KEY "nvapi-..."          (Windows, new shells)
    $env:NVIDIA_API_KEY = "nvapi-..."        (current PowerShell session)
Optionally override the model with NVIDIA_MODEL. NVIDIA retires hosted models
(Llama 3.3 70B went on 2026-08-26 and every call then failed with HTTP 410), so
the default is the one that answered on the free tier in September 2026 — Gemma
4 31B, open-weight like Llama, good Czech. List what's live with
GET {NVIDIA_BASE_URL}/models.
"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

# Any OpenAI-compatible host works: LLM_* override the NVIDIA_* names (e.g. Mistral's
# API, or a Llama / Qwen / Mistral model on NVIDIA's catalog via NVIDIA_MODEL).
NVIDIA_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
NVIDIA_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("NVIDIA_MODEL", "google/gemma-4-31b-it")
NVIDIA_BASE_URL = (os.environ.get("LLM_BASE_URL") or os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")).rstrip("/")
# The runner-facing assistant may use its own model and even its own host (e.g.
# Mistral's API with mistral-small-latest) without moving coach texts or embeddings.
_NV_CATALOG = "integrate.api.nvidia.com"
# On Groq's free tier qwen/qwen3.8-27b answered 10/10 sample questions in Czech
# within the validator's rules at 1-2 s (2026-09-28); NVIDIA's catalog models
# returned 404/410 or timed out for this account.
_ASSIST_HOST = os.environ.get("ASSISTANT_BASE_URL") or NVIDIA_BASE_URL
ASSISTANT_MODEL = os.environ.get("ASSISTANT_MODEL") or (
    "qwen/qwen3.8-27b" if "groq.com" in _ASSIST_HOST else
    "mistralai/mistral-large-2-instruct" if _NV_CATALOG in _ASSIST_HOST else NVIDIA_MODEL)
ASSISTANT_BASE_URL = (os.environ.get("ASSISTANT_BASE_URL") or NVIDIA_BASE_URL).rstrip("/")
ASSISTANT_API_KEY = os.environ.get("ASSISTANT_API_KEY") or NVIDIA_API_KEY
# Embeddings for the assistant's knowledge search (multilingual, Czech included):
# llama-nemotron-embed-vl-1b-v2 won the Gate 1 comparison on the live knowledge
# base (assistant/evaluate.py); several catalog models answer 404 for this account.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2")
EMBED_BASE_URL = (os.environ.get("EMBED_BASE_URL") or NVIDIA_BASE_URL).rstrip("/")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY") or NVIDIA_API_KEY

# Speech-to-text for the post-visit conclusion. Kept separate from the chat
# model so it can point at any OpenAI-compatible /audio/transcriptions host
# (Whisper, NVIDIA Riva/Canary via an OpenAI-shim, etc.). Falls back to
# ASR_API_KEY→NVIDIA_API_KEY so a single NVIDIA key can drive both if the
# base URL is set. Without a base URL, asr_available() is False and the
# conclusion flow falls back to a physio-typed transcript.
ASR_API_KEY = os.environ.get("ASR_API_KEY") or NVIDIA_API_KEY
ASR_BASE_URL = os.environ.get("ASR_BASE_URL")
ASR_MODEL = os.environ.get("ASR_MODEL", "whisper-1")


def available() -> bool:
    return bool(NVIDIA_API_KEY)


def asr_available() -> bool:
    return bool(ASR_API_KEY and ASR_BASE_URL)


def transcribe(audio_bytes: bytes, filename: str = "session.webm",
               mime: str = "application/octet-stream", language: str = "cs"):
    """Transcribe session audio via an OpenAI-compatible /audio/transcriptions
    endpoint. Returns the transcript text, or None if no ASR endpoint is
    configured or the call fails — callers must then fall back to a manually
    typed transcript. The audio bytes are never written to disk here and are
    dropped as soon as this returns (GDPR data-minimisation: only the text is
    kept, and only after the physio approves it)."""
    if not asr_available():
        return None
    try:
        resp = httpx.post(
            f"{ASR_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {ASR_API_KEY}"},
            data={"model": ASR_MODEL, "language": language},
            files={"file": (filename, audio_bytes, mime)},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("text")
        return text.strip() if text else None
    except Exception:
        return None


LAST_ERROR: dict = {}


def _note_error(kind: str, e: Exception) -> None:
    """Keeps the last failure per kind (status code and a short body, never the key)
    so the assistant can log why it fell back and the ops check can show it."""
    resp = getattr(e, "response", None)
    detail = {"type": type(e).__name__, "status": getattr(resp, "status_code", None)}
    if resp is not None and resp.headers.get("retry-after"):
        detail["retryAfter"] = resp.headers.get("retry-after")
    try:
        detail["body"] = (resp.text or "")[:300] if resp is not None else str(e)[:300]
    except Exception:
        detail["body"] = str(e)[:300]
    LAST_ERROR[kind] = detail


def probe(kind: str = "chat", model: str | None = None) -> dict:
    """One tiny request to the assistant's chat model or the embedding model:
    {ok, ms, model, error}. For the ops check only."""
    import time
    LAST_ERROR.pop(kind, None)
    t0 = time.monotonic()
    if kind == "embed":
        m = model or EMBED_MODEL
        out = embed(["Kolik kilometrů mám dnes běžet?"], kind="query", timeout=30, model=m)
        ok = bool(out)
        extra = {"dim": len(out[0])} if ok else {}
    else:
        m = model or ASSISTANT_MODEL
        out = chat_messages([{"role": "user", "content": "Odpověz jednou českou větou: co je regenerace?"}],
                            max_tokens=60, timeout=45, model=m, base_url=ASSISTANT_BASE_URL, api_key=ASSISTANT_API_KEY)
        ok = bool(out)
        extra = {"reply": (out or "")[:200]}
    return {"kind": kind, "ok": ok, "ms": round((time.monotonic() - t0) * 1000), "model": m,
            "error": None if ok else LAST_ERROR.get(kind), **extra}


def assistant_available() -> bool:
    return bool(ASSISTANT_API_KEY)


def chat_messages(messages: list[dict], temperature: float = 0.25, max_tokens: int = 700, timeout: float = 60.0,
                  model: str | None = None, base_url: str | None = None, api_key: str | None = None):
    """Same contract as chat() but takes a full messages list (system + any
    number of prior user/assistant turns) — what the multi-turn AI chat in
    ai_brief.chat_reply() needs; chat() is the single-turn special case.

    timeout is generous (60s): a 70B model generating up to max_tokens on
    NVIDIA's shared free-tier infra routinely takes 25-40s for a full
    clinical narrative, well past a "quick API call" timeout."""
    key = api_key or NVIDIA_API_KEY
    if not key:
        return None
    try:
        resp = httpx.post(
            f"{base_url or NVIDIA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model or NVIDIA_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip() if text else None
    except Exception as e:
        _note_error("chat", e)
        return None


# v0.12.0 — image input (shoe recognition): the default chat model first, then the
# catalog's vision models. VISION_MODELS (comma-separated) overrides the order.
VISION_MODELS = [m.strip() for m in (os.environ.get("VISION_MODELS") or "").split(",") if m.strip()] or [
    NVIDIA_MODEL, "meta/llama-4-maverick-17b-128e-instruct"]
VISION_BASE_URL = (os.environ.get("VISION_BASE_URL") or NVIDIA_BASE_URL).rstrip("/")
VISION_API_KEY = os.environ.get("VISION_API_KEY") or NVIDIA_API_KEY
VISION_TIMEOUT = float(os.environ.get("VISION_TIMEOUT") or 45)


def vision(prompt: str, image_data_url: str, system: str | None = None, max_tokens: int = 300,
           timeout: float | None = None) -> tuple[str | None, str | None]:
    """(reply, model) for one image + a question, trying VISION_MODELS in turn;
    (None, None) without a key or when every model fails."""
    if not VISION_API_KEY:
        return None, None
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": [
        {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_data_url}}]}]
    errors = {}
    for m in VISION_MODELS:
        LAST_ERROR.pop("chat", None)
        out = chat_messages(msgs, temperature=0.1, max_tokens=max_tokens, timeout=timeout or VISION_TIMEOUT, model=m,
                            base_url=VISION_BASE_URL, api_key=VISION_API_KEY)
        if out:
            return out, m
        errors[m] = LAST_ERROR.get("chat")
    LAST_ERROR["vision"] = errors
    return None, None


def list_models(q: str = "") -> list[str]:
    """The provider's model ids containing `q` (ops only)."""
    if not NVIDIA_API_KEY:
        return []
    try:
        resp = httpx.get(f"{NVIDIA_BASE_URL}/models", headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"}, timeout=20)
        resp.raise_for_status()
        ids = [m.get("id", "") for m in resp.json().get("data", [])]
    except Exception as e:
        _note_error("models", e)
        return []
    return sorted(i for i in ids if q.lower() in i.lower())


def chat(system: str, user: str, temperature: float = 0.25, max_tokens: int = 700, timeout: float = 60.0):
    """Returns the model's reply text, or None if no key is configured or
    the call fails for any reason (network, quota, bad response shape) —
    callers must treat None as "fall back to the deterministic version",
    never as an error to surface to the user."""
    return chat_messages(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature, max_tokens, timeout,
    )


def _embed_body(model: str, texts: list[str], kind: str) -> dict:
    body = {"model": model, "input": texts, "encoding_format": "float"}
    if "nvidia.com" in EMBED_BASE_URL:            # NVIDIA's retrievers want these, other hosts may reject them
        body.update({"input_type": kind, "truncate": "END"})
    return body


def embed_available() -> bool:
    return bool(EMBED_API_KEY) and os.environ.get("DOSSLAP_EMBED", "on").lower() not in ("off", "0", "false")


def embed(texts: list[str], kind: str = "passage", timeout: float = 60.0, model: str | None = None):
    """Embedding vectors for `texts` (kind "passage" for the corpus, "query" for a
    question), or None when no key is configured or the call fails — callers then
    fall back to keyword search."""
    if not embed_available() or not texts:
        return None
    try:
        resp = httpx.post(
            f"{EMBED_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {EMBED_API_KEY}", "Content-Type": "application/json"},
            json=_embed_body(model or EMBED_MODEL, texts, kind),
            timeout=timeout,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]
    except Exception as e:
        _note_error("embed", e)
        return None
