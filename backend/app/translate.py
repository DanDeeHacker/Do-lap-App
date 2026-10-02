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
import re

from . import llm, models
from .metrics import engine as E

GLOSSARY = (
    "Glossary (Czech → British English): Dnes → Today, Trénink → Training, Deník → Diary, Pohyb → Movement, "
    "Zátěž → Load, Péče → Care, Data → Data, Skóre → Score, Připravenost → Readiness, Příznaky → Symptoms, "
    "Mechanika → Mechanics, kvadrant → quadrant, tichý drift → silent drift, přetížení → overload, "
    "kritická kombinace → critical combination, stabilní → stable, kapacita → capacity, strop → ceiling, "
    "check-in → check-in, j.z. → LU (load units), tep → heart rate (bpm), fyzioterapeut → physiotherapist, "
    "Ve vašich datech: → In your data:, Co říká výzkum: → What the research says:, Co s tím: → What to do:"
)
SYSTEM_EN = (
    "You translate texts from Došlap, a running app that helps runners and physiotherapists, from Czech into "
    "British English (British spelling, metric units). Translate faithfully: do not add, drop or soften anything, "
    "and keep the tone calm, plain and polite. Keep every number exactly, but write decimals with a point "
    "(7,4 → 7.4). Keep citation markers such as [1] or [2][3] exactly where they are, keep line breaks and the "
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


def _nums(text: str) -> list[str]:
    return sorted(n.replace(",", ".") for n in _NUM.findall(_CITE.sub(" ", text or "")))


def _ok(src: str, out: str) -> bool:
    if not out or not out.strip():
        return False
    if sorted(_CITE.findall(src)) != sorted(_CITE.findall(out)):
        return False
    # dates move from "3. 10." to "3 Oct", so compare the numbers as a multiset of
    # values found in the source that are not day / month pairs
    src_n = _nums(re.sub(r"\b\d{1,2}\.\s?\d{1,2}\.(\s?\d{4})?", " ", src))
    out_n = _nums(out)
    return all(out_n.count(n) >= src_n.count(n) for n in set(src_n))


def _llm(system: str, text: str, max_tokens: int) -> str | None:
    if not llm.assistant_available():
        return None
    return llm.chat_messages([{"role": "system", "content": system}, {"role": "user", "content": text}],
                             temperature=0.1, max_tokens=max_tokens, timeout=30,
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
    out = _llm(SYSTEM_EN, text, max_tokens=900)
    out = (out or "").strip()
    if not _ok(text, out):
        return None
    db.add(models.Translation(key=_key(text, "en"), lang="en", src=text, out=out, created_at=E.now_iso()))
    db.commit()
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


def message_en(db, m: dict) -> dict:
    """An assistant message dict in English (user messages are shown as typed)."""
    if not m or m.get("role") != "assistant":
        return m
    en = to_en(db, m.get("text"))
    return {**m, "text": en, "lang": "en"} if en else {**m, "lang": "cs"}
