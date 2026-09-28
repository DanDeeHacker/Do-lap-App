"""Checks an assistant answer before the runner sees it (implementation plan,
safety section). Extends the Phase 1 validator (metrics/coach_validate.py):

• numbers — every number is in the runner facts or in the text of a source that
  was retrieved for this answer;
• citations — every [n] points to a retrieved source, and a research sentence
  carries one;
• engine consistency — no harder session than today's recommendation (unless the
  sentence declines it or talks about a later day), an active physio referral or
  safety warning is mentioned;
• quotation length — no run of 20 or more words copied from a full-text passage;
• the Phase 1 bans (diagnosis, medication, running through pain, promises, links).
"""
import re

from ..metrics import coach_validate as V
from .knowledge import fold

WORDS = (8, 300)
_CITE = re.compile(r"\[(\d{1,2})\]")
_APP_LINK = re.compile(r"\[(Dnes|Trénink|Deník|Pohyb|Zátěž|Péče|Data)\]")
_RESEARCH = re.compile(r"\b(studi\w*|výzkum\w*|meta-?analýz\w*|přehled\w* studií|autoři|v randomizovan\w*)\b", re.I)
_LATER = re.compile(
    r"\b(pondělí|úterý|středu|středa|čtvrtek|pátek|sobotu|sobota|neděli|neděle|zítra|pozítří|příští\w*|později|až\b|"
    r"za \w+ dn\w*|jindy|v dalších dnech|odlož\w*|přesuň\w*|počkej\w*|počkat)\b", re.I)
_DECLINE = re.compile(r"\b(nedoporuč\w*|nezařaz\w*|není vhodn\w*|není dnes|nechte|vynech\w*|bez\b|žádn\w*|ne\b|"
                      r"blokuj\w*|zablokov\w*|nepovol\w*|nedovol\w*|místo)\b", re.I)


def strip_links(text: str) -> tuple[str, list[str]]:
    links = list(dict.fromkeys(_APP_LINK.findall(text)))
    clean = _APP_LINK.sub("", text)
    clean = re.sub(r"[ \t]+([.,;!?])", r"\1", re.sub(r"[ \t]{2,}", " ", clean)).strip()
    return clean, links[:2]


def _ngrams(words: list[str], n: int) -> set:
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def validate(text: str, facts: dict, sources: list[dict]) -> dict:
    """{ok, issues}. `sources` are the numbered sources given to the model, each with
    `n` and `text` (the text the model saw) and `kind`."""
    issues = []
    if not text or not text.strip():
        return {"ok": False, "issues": [{"code": "empty"}]}
    body = _CITE.sub(" ", text)
    words = re.findall(r"[^\W\d_]+", body)
    if not WORDS[0] <= len(words) <= WORDS[1]:
        issues.append({"code": "length", "detail": f"{len(words)} slov (povoleno {WORDS[0]}–{WORDS[1]})"})
    letters = [c for c in text if c.isalpha()]
    if len(words) >= 15 and sum(c in V._CZ_LETTERS for c in letters) / max(len(letters), 1) < 0.015:
        issues.append({"code": "not_czech"})
    # numbers: facts or the retrieved sources' own text
    ok = V.allowed({"facts": facts, "sources": [s.get("text", "") for s in sources]})
    bad = V._unknown_numbers(body, ok)
    if bad:
        issues.append({"code": "number_not_in_facts", "detail": ", ".join(bad[:8])})
    # citations
    have = {s["n"] for s in sources}
    cited = {int(x) for x in _CITE.findall(text)}
    if cited - have:
        issues.append({"code": "unknown_citation", "detail": ", ".join(f"[{x}]" for x in sorted(cited - have))})
    for s in V._sentences(text):
        if _RESEARCH.search(s) and not _CITE.search(s) and not re.search(r"nemám ověřený zdroj", s, re.I):
            issues.append({"code": "uncited_research", "detail": s.strip()[:160]})
            break
    # the engine stays in charge
    ref = facts.get("referral") or {}
    if (ref.get("physio") or facts.get("safety", {}).get("boneStressWarning")) and not re.search(r"fyzio", text, re.I):
        issues.append({"code": "missing_referral", "detail": ref.get("text")})
    rec = (facts.get("today") or {}).get("type")
    if rec in V.HARDER:
        for s in V._sentences(text):
            if _DECLINE.search(s) or _LATER.search(s) or V._EXEMPT.search(s):
                continue
            hit = next((p for p in V.HARDER[rec] if re.search(p, s, re.I)), None)
            if hit:
                issues.append({"code": "contradicts_recommendation", "detail": s.strip()[:160]})
                break
    for s in V._sentences(text):
        if V._THROUGH_PAIN.search(s) and V._RUN_VERB.search(s) and not V._NEGATED.search(s):
            issues.append({"code": "run_through_pain", "detail": s.strip()[:160]})
            break
    for code, rx in V.BANNED:
        m = rx.search(text)
        if m:
            issues.append({"code": code, "detail": m.group(0)[:80]})
    # quotation length against full texts (copyright: paraphrase, don't copy)
    ans = _ngrams(fold(body).split(), 20)
    for s in sources:
        if s.get("kind") == "fulltext" and ans & _ngrams(fold(s.get("text", "")).split(), 20):
            issues.append({"code": "long_quote", "detail": s.get("cite")})
            break
    return {"ok": not issues, "issues": issues}
