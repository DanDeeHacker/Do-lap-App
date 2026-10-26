"""British English for the app's fixed texts outside the browser (the calendar feed).

The page is translated in the browser from a fixed dictionary (frontend/src/i18n/en.json,
built by scripts/i18n); a calendar app has no such step, so the feed's texts go through this
port of the browser's lookup (frontend/src/i18n/translator.ts): exact → with its numbers as
placeholders → templates whose captured parts are translated in turn → its sentences → its
" · "-separated parts. Numbers get a decimal point, Czech dates become British ones; a text
the dictionary doesn't know stays Czech. The production image copies en.json next to the
backend (Dockerfile)."""
import json
import re
from functools import lru_cache
from pathlib import Path

_PATHS = [Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "en.json"]
LETTER = re.compile(r"[A-Za-zÀ-ž]")
NUM = re.compile(r"[-−+]?\d+(?:[   ]\d{3})*(?:,\d+)?")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CZ_DAYS = {"pondělí": "Monday", "úterý": "Tuesday", "středa": "Wednesday", "středu": "Wednesday", "čtvrtek": "Thursday",
           "pátek": "Friday", "sobota": "Saturday", "sobotu": "Saturday", "neděle": "Sunday", "neděli": "Sunday",
           "po": "Mon", "út": "Tue", "st": "Wed", "čt": "Thu", "pá": "Fri", "so": "Sat", "ne": "Sun"}
ICON = re.compile(r"^([\U0001F300-\U0001FAFF☀-➿]️?\s*)(.*[A-Za-zÀ-ž].*)$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ").replace(" ", " ")).strip()


def numbers_en(s: str) -> str:
    s = re.sub(r"(^|[^a-zà-ž])(po|út|st|čt|pá|so|ne)(?=\s\d{1,2}\.\s?\d{1,2}\.)",
               lambda m: m.group(1) + CZ_DAYS[m.group(2).lower()], s, flags=re.I)

    def date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return f"{d} {MONTHS[mo - 1]}" + (f" {y}" if y else "")
    s = re.sub(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?(?!\d)", date, s)
    s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    return re.sub(r"(\d)[   ](\d{3})(?!\d)", r"\1,\2", s)


class _Dict:
    def __init__(self, d: dict):
        self.exact = {_norm(k): v for k, v in (d.get("x") or {}).items()}
        self.num_tpl: dict = {}
        self.rx: list = []
        self.by_word: dict = {}
        for cs0, en in d.get("t") or []:
            cs = _norm(cs0)
            if "{}" not in cs:
                self.exact[cs] = en
                continue
            self.num_tpl[cs] = en
            parts = cs.split("{}")
            lits = [p.strip() for p in parts if LETTER.search(p.strip())]
            if not lits:
                continue
            # two placeholders back to back: the first takes the whole run (translator.ts)
            pat = "".join((("(.*?)" if (k > 1 and parts[k - 1] == "") else "(.+)" if p == "" else "(.+?)") if k else "")
                          + re.escape(p) for k, p in enumerate(parts))
            i = len(self.rx)
            self.rx.append((re.compile("^" + pat + "$", re.S), en, len(cs.replace("{}", ""))))
            words = sorted((w.lower() for w in re.split(r"[^A-Za-zÀ-ž]+", " ".join(lits)) if len(w) >= 3), key=len, reverse=True)
            if words:
                self.by_word.setdefault(words[0], []).append(i)
        self.cache: dict = {}


@lru_cache(maxsize=1)
def _dict() -> _Dict | None:
    for p in _PATHS:
        if p.exists():
            return _Dict(json.loads(p.read_text(encoding="utf-8")))
    return None


def _fill(en: str, vals: list) -> str:
    return re.sub(r"\{(\d+)\}", lambda m: vals[int(m.group(1))] if int(m.group(1)) < len(vals) else "", en)


def _core(D: _Dict, s: str, depth: int) -> str | None:
    if s in D.exact:
        return D.exact[s]
    vals: list = []
    key = NUM.sub(lambda m: (vals.append(m.group(0)), "{}")[1], s)
    if vals and key in D.num_tpl:
        return _fill(D.num_tpl[key], [numbers_en(v) for v in vals])
    ic = ICON.match(s)
    if ic:
        t = _core(D, ic.group(2), depth)
        if t is not None:
            return ic.group(1) + t
    if depth >= 3:
        return None
    best = None
    seen = set()
    for w in (w.lower() for w in re.split(r"[^A-Za-zÀ-ž]+", s) if len(w) >= 3):
        for i in D.by_word.get(w, []):
            if i in seen:
                continue
            seen.add(i)
            rx, en, lit = D.rx[i]
            m = rx.match(s)
            if m and (best is None or lit > best[2]):
                best = (m, en, lit)
    if best:
        return _fill(best[1], [translate(v, depth + 1) for v in best[0].groups()])
    sents = re.split(r"(?<=[.!?])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])", s)
    if len(sents) > 1:
        tr = [_core(D, p, depth + 1) for p in sents]
        if any(t is not None for t in tr):
            return " ".join(t if t is not None else numbers_en(p) for p, t in zip(sents, tr))
    for sep in (" → ", " + ", " · ", " – ", " — ", ": "):
        if sep in s:
            parts = s.split(sep, 1) if sep == ": " else s.split(sep)
            tr = [_core(D, p.strip(), depth + 1) for p in parts]
            if any(t is not None for t in tr):
                return sep.join(t if t is not None else numbers_en(p.strip()) for p, t in zip(parts, tr))
    return None


def translate(raw: str | None, depth: int = 0) -> str | None:
    """British English for one text, or the text with British numbers when the dictionary lacks it."""
    if not raw or not LETTER.search(raw):
        return numbers_en(raw) if raw else raw
    D = _dict()
    if D is None:
        return raw
    lead, trail = raw[:len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):]      # as translator.ts: the spaces stay
    s = _norm(raw)
    if s not in D.cache:
        t = _core(D, s, depth)
        D.cache[s] = t if t is not None else numbers_en(s)
    return lead + D.cache[s] + trail
