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

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "google/gemma-4-31b-it")
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

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


def chat_messages(messages: list[dict], temperature: float = 0.25, max_tokens: int = 700, timeout: float = 60.0):
    """Same contract as chat() but takes a full messages list (system + any
    number of prior user/assistant turns) — what the multi-turn AI chat in
    ai_brief.chat_reply() needs; chat() is the single-turn special case.

    timeout is generous (60s): a 70B model generating up to max_tokens on
    NVIDIA's shared free-tier infra routinely takes 25-40s for a full
    clinical narrative, well past a "quick API call" timeout."""
    if not NVIDIA_API_KEY:
        return None
    try:
        resp = httpx.post(
            f"{NVIDIA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": NVIDIA_MODEL,
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
    except Exception:
        return None


def chat(system: str, user: str, temperature: float = 0.25, max_tokens: int = 700, timeout: float = 60.0):
    """Returns the model's reply text, or None if no key is configured or
    the call fails for any reason (network, quota, bad response shape) —
    callers must treat None as "fall back to the deterministic version",
    never as an error to surface to the user."""
    return chat_messages(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature, max_tokens, timeout,
    )
