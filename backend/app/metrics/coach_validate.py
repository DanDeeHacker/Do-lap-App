"""Checks a model-written text against the facts packet it was written from
(coach_facts.py). Any finding → the runner sees the deterministic text instead
(coach_texts.py); the findings are stored with the generation, for prompt work.

What must hold:
• every number, date and pace in the text is in the facts (rounding and the
  Czech decimal comma allowed) — the model narrates, it doesn't compute;
• the physio referral is mentioned whenever the engine makes one;
• the commentary names today's recommended session and doesn't push a harder
  one on a rest / easy day;
• no diagnosis, no medication advice, no running through pain, no promises;
• Czech prose of a sensible length, no links or headings.
"""
import re

LIMITS = {"daily_summary": (12, 130), "daily_commentary": (15, 170), "weekly_summary": (30, 280)}

_DATE = re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?")
_CLOCK = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_CITATION = re.compile(r"\([^()]*\b(?:19|20)\d\d[a-z]?\)")
_TIME_SPAN = re.compile(r"(?<![\d,.])[1-7]\s*(?:den|dny|dní|dnů|dnech|týden|týdny|týdnů|týdnech|hodin\w*|noc\w*)\b", re.I)
_NUM = re.compile(r"(?<![\w,.])(\d+(?:[.,]\d+)?)(?!\w)")

SESSION_WORDS = {
    "volno": r"voln|odpoč|neběh|pauz",
    "regenerace": r"regenera",
    "lehký": r"lehk",
    "dlouhý": r"dlouh",
    "kvalitní": r"kvalitn|interval|tempov",
}
# on these days the text must not push a harder session
HARDER = {
    "volno": [r"\binterval", r"\btempov", r"\bdlouh\w* běh", r"\bkvalitn\w* trénink", r"\b(za|vy|od)běhn\w*",
              r"\bběžte\b", r"\bběhejte\b"],
    "regenerace": [r"\binterval", r"\btempov\w* (běh|úsek)", r"\bkvalitn\w* trénink", r"\bdlouh\w* běh"],
    "lehký": [r"\binterval", r"\btempov\w* (běh|úsek)", r"\bkvalitn\w* trénink", r"\bdlouh\w* běh"],
}
# a sentence that negates or looks back ("žádné intervaly", "po včerejším dlouhém běhu") is fine
_EXEMPT = re.compile(
    r"\b(ne|nedělejte|neběhejte|nezařazujte|nezkoušejte|vynech\w*|žádn\w*|bez|místo|odlož\w*|počkejte|nechte|"
    r"včer\w*|předchoz\w*|minul\w*|posledn\w*|po|uplynul\w*|proběhl\w*|absolvoval\w*|zaběhl\w*|běžel\w*|"
    r"až|zítra|příště|později)\b", re.I)

BANNED = [
    ("medication", re.compile(
        r"\b(ibuprofen\w*|paralen\w*|brufen\w*|nurofen\w*|aspirin\w*|diklofenak\w*|diclofenac\w*|voltaren\w*|"
        r"analgeti\w*|nsaid\w*|antiflogisti\w*|lék|léky|léků|lékem|lékům|prášk\w*|injekc\w*|kortikoid\w*)\b", re.I)),
    ("diagnosis", re.compile(
        r"\b(máte|jde o|trpíte|je to|bude to|vypadá to na)\s+(\w+\s+){0,2}?(zán[eě]t\w*|zlomenin\w*|natržen\w*|ruptur\w*|"
        r"tendinitid\w*|tendinopati\w*|tendinóz\w*|fasciitid\w*|fasciitis|periostitid\w*|burzitid\w*|syndrom\w*|výr[oů]n\w*)|"
        r"\bdiagnostikuj\w*|\bdiagnó[zs]\w*\s+(je|zní)\b", re.I)),
    ("run_through_pain", re.compile(
        r"\bignoruj\w*\s+bolest|\bbolest\w*\s+(nevadí|ignorujte)|\bnevšímejte si bolest", re.I)),
    ("promise", re.compile(
        r"\bzaručen\w*|\bgarantuj\w*|\burčitě se nezraní\w*|\bbez (jakéhokoli )?rizika\b|\b100\s?%\s+(jist|bezpeč)", re.I)),
    ("link", re.compile(r"https?://|www\.", re.I)),
    ("heading", re.compile(r"^\s*#{1,6}\s", re.M)),
]
_THROUGH_PAIN = re.compile(r"\b(přes|navzdory)\s+bolest", re.I)
_RUN_VERB = re.compile(r"\b(běh|běž|trénuj|pokračuj|zaběhn|vyběhn|dokonč|odběhn)\w*", re.I)
_NEGATED = re.compile(r"\bne(běh|běž|trénuj|pokračuj|zkoušej|dokonču)\w*|\bnikdy\b|\bne\b", re.I)
_CZ_LETTERS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, bool) or o is None:
        return
    else:
        yield o


def allowed(facts: dict) -> dict:
    """Every number, date and clock/pace token the facts contain."""
    nums, dates, clocks = set(), set(), set()
    for v in _strings(facts):
        if isinstance(v, (int, float)):
            nums.add(float(v))
            continue
        s = str(v)
        for d, m, _ in _DATE.findall(s):
            dates.add((int(d), int(m)))
        for mm, ss in _CLOCK.findall(s):
            clocks.add(int(mm) * 60 + int(ss))
        s = _CLOCK.sub(" ", _DATE.sub(" ", s))
        nums.update(_num(x) for x in _NUM.findall(s))
    variants = set()
    for x in nums:
        for y in (x, abs(x)):
            variants.update({y, round(y), round(y, 1), round(y, 2)})
    return {"nums": variants, "dates": dates, "clocks": clocks}


def _unknown_numbers(text: str, ok: dict) -> list[str]:
    bad = []
    t = _CITATION.sub(" ", text)
    for d, m, _ in _DATE.findall(t):
        if (int(d), int(m)) not in ok["dates"]:
            bad.append(f"{d}. {m}.")
    t = _DATE.sub(" ", t)
    for mm, ss in _CLOCK.findall(t):
        sec = int(mm) * 60 + int(ss)
        if not any(abs(sec - c) <= 2 for c in ok["clocks"]):
            bad.append(f"{mm}:{ss}")
    t = _TIME_SPAN.sub(" ", _CLOCK.sub(" ", t))
    for x in _NUM.findall(t):
        v = _num(x)
        if not any(abs(v - a) < 1e-6 for a in ok["nums"]) and not any(abs(v - a) <= 0.05 for a in ok["nums"] if a != round(a)):
            bad.append(x)
    return bad


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def validate(kind: str, text: str, facts: dict) -> dict:
    issues = []
    if not text or not text.strip():
        return {"ok": False, "issues": [{"code": "empty"}]}
    words = re.findall(r"[^\W\d_]+", text)
    lo, hi = LIMITS.get(kind, (10, 300))
    if not lo <= len(words) <= hi:
        issues.append({"code": "length", "detail": f"{len(words)} slov (povoleno {lo}–{hi})"})
    letters = [c for c in text if c.isalpha()]
    if len(words) >= 15 and sum(c in _CZ_LETTERS for c in letters) / max(len(letters), 1) < 0.015:
        issues.append({"code": "not_czech"})
    bad = _unknown_numbers(text, allowed(facts))
    if bad:
        issues.append({"code": "number_not_in_facts", "detail": ", ".join(bad[:8])})
    if (facts.get("referral") or {}).get("physio") and not re.search(r"fyzio", text, re.I):
        issues.append({"code": "missing_referral", "detail": (facts["referral"] or {}).get("text")})
    today = facts.get("today") or {}
    rec = today.get("type")
    if kind == "daily_commentary" and rec in SESSION_WORDS and not re.search(SESSION_WORDS[rec], text, re.I):
        issues.append({"code": "recommendation_missing", "detail": today.get("label")})
    if kind in ("daily_commentary", "daily_summary") and rec in HARDER:
        for s in _sentences(text):
            if _EXEMPT.search(s):
                continue
            hit = next((p for p in HARDER[rec] if re.search(p, s, re.I)), None)
            if hit:
                issues.append({"code": "contradicts_recommendation", "detail": s.strip()[:160]})
                break
    for s in _sentences(text):   # "běžte i přes bolest" — but "neběhejte přes bolest" is exactly right
        if (_THROUGH_PAIN.search(s) and _RUN_VERB.search(s) and not _NEGATED.search(s)):
            issues.append({"code": "run_through_pain", "detail": s.strip()[:160]})
            break
    for code, rx in BANNED:
        m = rx.search(text)
        if m:
            issues.append({"code": code, "detail": m.group(0)[:80]})
    return {"ok": not issues, "issues": issues}
