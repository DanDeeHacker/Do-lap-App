"""British English for the AI assistant (translation request 2026-10-02).

The assistant keeps thinking and checking in Czech: its prompt, the facts, the
evidence cards and every safety rule of its validator are Czech, so an English
account's question is translated to Czech, the usual pipeline answers and
validates it, and only the validated answer is translated to British English.
Nothing the validator guarantees is lost on the way.

A translation must keep every number (with a decimal point instead of the Czech
comma) and every citation [n]; otherwise it is rejected and the caller shows the
Czech original. Translations are cached in the database (one row per text and
language), so history views and repeated summaries cost no model call.

The static texts of the app (engine signals, guidance, labels) are translated
in the browser from a fixed dictionary (frontend/src/i18n), not here.
"""
import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from . import llm, models
from .metrics import engine as E

log = logging.getLogger("doslap.translate")

GLOSSARY = (
    "Glossary (Czech → British English): Dnes → Today, Trénink → Training, Deník → Diary, Pohyb → Movement, "
    "Zátěž → Load, Péče → Care, Data → Data, Skóre → Score, Připravenost → Readiness, Příznaky → Symptoms, "
    "Mechanika → Mechanics, kvadrant → quadrant, tichý drift → silent drift, přetížení → overload, "
    "kritická kombinace → critical combination, stabilní → stable, kapacita → capacity, strop → ceiling, "
    "check-in → check-in, j.z. → LU (load units), body zátěže / bodů zátěže → load points, tep → heart rate (bpm), fyzioterapeut → physiotherapist, "
    "Ve vašich datech: → In your data:, Co říká výzkum: → What the research says:, Co s tím: → What to do:"
)
SYSTEM_EN = (
    "You translate texts from Došlap, a running app that helps runners and physiotherapists, from Czech into "
    "British English (British spelling, metric units). Translate faithfully: do not add, drop or soften anything, "
    "and keep the tone calm, plain and polite. Keep every number exactly and always in digits, never as words "
    "(3 stays 3, not three; 1. týden is week 1), but write decimals with a point (7,4 → 7.4). Keep citation markers such as [1] or [2][3] exactly where they are, keep line breaks and the "
    "bullet character •. Write dates as day month (3. 10. → 3 Oct). Reply with the translation only.\n" + GLOSSARY
)
SYSTEM_CS = (
    "Přelož otázku běžce z angličtiny do češtiny pro běžeckou aplikaci Došlap. Zachovej význam i čísla. "
    "Odpověz jen překladem."
)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_CITE = re.compile(r"\[\d{1,2}\]")


def _key(text: str, lang: str) -> str:
    return hashlib.sha256(f"{lang}|{text}".encode()).hexdigest()[:32]


def _nums(text: str, en: bool = False) -> list[str]:
    """The numbers of a text; thousands separators dropped (Czech "1 212", English "1,212"),
    decimals with a point."""
    t = _CITE.sub(" ", text or "")
    t = re.sub(r"(\d),(\d{3})(?!\d)", r"\1\2", t) if en else re.sub(r"(\d)[ \u00a0\u202f](\d{3})(?!\d)", r"\1\2", t)
    return sorted(n.replace(",", ".") for n in _NUM.findall(t))


_WORDS = {"0": ("zero",), "1": ("one", "first"), "2": ("two", "second", "both", "twice"),
          "3": ("three", "third"), "4": ("four", "fourth"), "5": ("five", "fifth"), "6": ("six", "sixth"),
          "7": ("seven", "seventh"), "8": ("eight", "eighth"), "9": ("nine", "ninth"), "10": ("ten", "tenth")}


def _problems(src: str, out: str) -> list[str]:
    """Why a translation can't be shown (empty when it can)."""
    if not out or not out.strip():
        return ["empty"]
    bad = []
    if sorted(_CITE.findall(src)) != sorted(_CITE.findall(out)):
        bad.append(f"citations {sorted(_CITE.findall(src))} → {sorted(_CITE.findall(out))}")
    # dates move from "3. 10." to "3 Oct", so compare the numbers as a multiset of
    # values found in the source that are not day / month pairs; a small whole number
    # the model wrote as a word ("three", "first") still counts
    src_n = _nums(re.sub(r"\b\d{1,2}\.\s?\d{1,2}\.(\s?\d{4})?", " ", src))
    out_n = _nums(out, en=True)
    low = (out or "").lower()
    for n in set(src_n):
        short = src_n.count(n) - out_n.count(n)
        if short > 0 and not (n in _WORDS and any(re.search(rf"\b{w}\b", low) for w in _WORDS[n])):
            bad.append(f"number {n} missing")
    return bad


def _ok(src: str, out: str) -> bool:
    return not _problems(src, out)


def _llm(system: str, text: str, max_tokens: int) -> str | None:
    if not llm.assistant_available():
        return None
    # the assistant model is a large shared one: a long summary takes well over 30 s
    return llm.chat_messages([{"role": "system", "content": system}, {"role": "user", "content": text}],
                             temperature=0.1, max_tokens=max_tokens, timeout=90,
                             model=llm.ASSISTANT_MODEL, base_url=llm.ASSISTANT_BASE_URL, api_key=llm.ASSISTANT_API_KEY)


def _cached(db, text: str, lang: str):
    return db.query(models.Translation).filter(models.Translation.key == _key(text, lang)).first()


def to_en(db, text: str | None) -> str | None:
    """British English for a Czech assistant text, or None (the caller keeps Czech)."""
    if not text or not text.strip():
        return text
    row = _cached(db, text, "en")
    if row is not None:
        return row.out
    out = _translate_en(text)
    if out is None:
        # a long text in one piece failed: translate it paragraph by paragraph
        paras = text.split("\n")
        if len([p for p in paras if p.strip()]) < 2:
            return None
        done = []
        for p in paras:
            if not p.strip():
                done.append(p)
                continue
            t = _translate_en(p)
            if t is None:
                return None
            done.append(t)
        out = "\n".join(done)
    db.add(models.Translation(key=_key(text, "en"), lang="en", src=text, out=out, created_at=E.now_iso()))
    db.commit()
    return out


def _translate_en(text: str) -> str | None:
    """One model call; None (logged) when it fails or the result doesn't keep the numbers."""
    out = (_llm(SYSTEM_EN, text, max_tokens=min(3000, 400 + len(text))) or "").strip()
    # a model sometimes wraps the reply in quotes or a lead-in
    out = re.sub(r"^(here is the translation:?\s*)", "", out, flags=re.I).strip()
    bad = _problems(text, out)
    if bad:
        log.warning("translation rejected (%d chars): %s", len(text), "; ".join(bad[:5]))
        return None
    return out


def to_cs(db, text: str) -> str:
    """Czech for an English question (the pipeline's gate, selector and validator are
    Czech); the original when translation is unavailable."""
    q = (text or "").strip()
    if not q:
        return q
    row = _cached(db, q, "cs")
    if row is not None:
        return row.out
    out = (_llm(SYSTEM_CS, q, max_tokens=300) or "").strip()
    if not out:
        return q
    db.add(models.Translation(key=_key(q, "cs"), lang="cs", src=q, out=out, created_at=E.now_iso()))
    db.commit()
    return out


# ------------------------------------------------------------------ fixed texts
DISCLAIMER_EN = ("The answer was written by AI from your data and the research literature. It can be wrong "
                 "and doesn't replace a physiotherapist.")
SUGGESTIONS_EN = {
    "Co mám dělat s bolestí holeně nebo chodidla?": "What should I do about shin or foot pain?",
    "Proč mám dnes nižší připravenost?": "Why is my readiness lower today?",
    "Proč dnes nemůžu dát intervaly?": "Why can't I do intervals today?",
    "Co znamená tichý drift?": "What does silent drift mean?",
    "Proč je moje zátěž zvýšená?": "Why is my load elevated?",
    "Jak dnes běhat v horku?": "How should I run in the heat today?",
    "Jak zařadit posilování do týdne?": "How do I fit strength training into my week?",
    "Co mám dnes běžet a proč?": "What should I run today and why?",
    "Jak vypadá můj tréninkový týden?": "What does my training week look like?",
    "Kde v aplikaci najdu svou kapacitu?": "Where in the app do I find my capacity?",
}

SUMMARY_TITLES_EN = {"Shrnutí dne": "Today's summary", "Dnešní trénink": "Today's training",
                     "Zátěž a kapacita": "Load and capacity", "Běžecká mechanika": "Running mechanics",
                     "Deník": "Diary", "Péče o tělo": "Body care"}


@lru_cache(maxsize=1)
def _cards_en() -> dict:
    p = Path(__file__).parent / "knowledge" / "cards.en.json"
    return json.loads(p.read_text(encoding="utf-8"))["cards"]


def sources_en(sources: list | None) -> list:
    """Evidence cards in English (study summaries and article passages are English already).
    The strength stays a key ("silné"…) the app translates on screen."""
    out = []
    for s in sources or []:
        en = _cards_en().get(s.get("id")) if s.get("kind") == "card" else None
        out.append({**s, **en} if en else s)
    return out


def message_en(db, m: dict) -> dict:
    """An assistant message dict in English (user messages are shown as typed)."""
    if not m or m.get("role") != "assistant":
        return m
    en = to_en(db, m.get("text"))
    out = {**m, "sources": sources_en(m.get("sources"))}
    if m.get("disclaimer"):
        out["disclaimer"] = DISCLAIMER_EN
    return {**out, "text": en, "lang": "en"} if en else {**out, "lang": "cs"}
