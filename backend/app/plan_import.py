"""Plán od trenéra — getting the coach's plan in (owner request 2026-10-12).

  • text (WhatsApp, e-mail, a spreadsheet's rows): a rule-based Czech / English parser
    (days, dates, the kind of session, km, minutes, the hard part, hills, a pace / HR
    target), optionally read first by the free hosted language model (llm.py, NVIDIA NIM);
    whatever comes back is validated here, and the parser is always the fallback;
  • a photo or a page of the plan: the free vision model (llm.vision) transcribes it into
    lines, which then take the text route — never stored;
  • a calendar link (iCal / webcal: TrainingPeaks, Final Surge, Intervals.icu, Runna,
    Google Calendar …): fetched behind an SSRF guard (https only, public addresses only,
    no redirects to elsewhere, 2 MB, 8 s), refreshed lazily when older than 3 hours and
    every morning; a pull replaces only the calendar's own sessions, and a day the coach
    edited in the overview stays the coach's.
Everything imported is a PREVIEW until the runner confirms it; uncertain fields are
flagged (`unsure`) for the runner to check.
"""
import ipaddress
import json
import logging
import re
import socket
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import httpx

from . import llm
from .metrics import coach_plan as CP

log = logging.getLogger("dosslap.plan")

DAYS = {
    0: ("po", "pondělí", "pondeli", "pondělí", "mon", "monday"),
    1: ("út", "ut", "úterý", "utery", "tue", "tues", "tuesday"),
    2: ("st", "středa", "streda", "středu", "stredu", "wed", "wednesday"),
    3: ("čt", "ct", "čtvrtek", "ctvrtek", "thu", "thur", "thurs", "thursday"),
    4: ("pá", "pa", "pátek", "patek", "fri", "friday"),
    5: ("so", "sobota", "sobotu", "sat", "saturday"),
    6: ("ne", "neděle", "nedele", "neděli", "nedeli", "sun", "sunday"),
}
_DAY_WORD = {w: d for d, ws in DAYS.items() for w in ws}
_DAY_RX = re.compile(r"^\s*[-•*]?\s*(" + "|".join(sorted((re.escape(w) for w in _DAY_WORD), key=len, reverse=True))
                     + r")\b\.?\s*[:\-–—)]?\s*", re.I)
_DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}))?|(\d{4})-(\d{2})-(\d{2})|(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?")
KIND_WORDS = [  # order matters: the first match wins
    ("rest", r"\b(volno|odpočinek|odpocinek|rest|off|day off|pauza|nic)\b"),
    ("race", r"\b(závod|zavod|race|půlmaraton|pulmaraton|maraton|marathon|parkrun|10k závod)\b"),
    ("swim", r"\b(plav\w*|swim\w*|bazén|bazen|pool)\b"),
    ("ride", r"\b(kolo|cyklo\w*|bike|cycling|ride|spinning|trenažér|trenazer|zwift|bicykl\w*)\b"),
    ("strength", r"\b(posil\w*|síla|sila|strength|gym|posilovna|core|kruhov\w*|stabilizac\w*)\b"),
    ("hills", r"\b(kopc\w*|kopec|hill\w*|výběh\w*|vybeh\w*|do kopce)\b"),
    ("quality", r"(\d\s*[x×]\s*\d)|\b(interval\w*|tempo\w*|fartlek|úsek\w*|usek\w*|threshold|prah\w*|rovinky|"
                r"stupňovan\w*|vo2|speed|rychl\w*|progres\w*|repeats?|strides|track|dráha|draha)\b"),
    ("long", r"\b(dlouh\w*|long|lsd|vytrvalost\w*)\b"),
    ("recovery", r"\b(regener\w*|recovery|vyklus\w*|výklus\w*|shakeout|velmi lehce|klus na vyklusání)\b"),
    ("easy", r"\b(lehk\w*|easy|aerob\w*|klus\w*|z2|base|volně|volne|pohodov\w*|běh|beh|run|jog\w*)\b"),
]
_KM_RX = re.compile(r"(?<![x×\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*(km|k\b|mi\b|mil\w*)", re.I)
_DUR_HMS = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2}):(\d{2})(?![\d:])")
_DUR_H = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d)?)\s*(?:h|hod\w*|hours?)\b(?:\s*(\d{1,2})\s*(?:min|m\b|'))?", re.I)
_DUR_MIN = re.compile(r"(?<![x×\d])(\d{2,3})\s*(?:min\w*|'|´|mins?)", re.I)
_ASC_RX = re.compile(r"(?:\+\s*(\d{2,4})\s*m\b|(\d{2,4})\s*m\s*(?:převýšení|prevyseni|stoupání|stoupani|nahoru|D\+|elev\w*|gain|vert\w*))", re.I)
_DESC_RX = re.compile(r"(?:-\s*(\d{2,4})\s*m\b|(\d{2,4})\s*m\s*(?:klesání|klesani|dolů|dolu|D-|descent))", re.I)
_TARGET_RX = re.compile(r"((?:@|v\s+tempu|tempo|pace)\s*\d{1,2}:\d{2}(?:\s*[-–]\s*\d{1,2}:\d{2})?\s*(?:/km|min/km)?|"
                        r"\b(?:Z[1-5](?:\s*[-–]\s*Z?[1-5])?)\b|(?:tep|TF|HR)\s*\d{2,3}(?:\s*[-–]\s*\d{2,3})?)", re.I)
_TOTAL_RX = re.compile(r"(celkem|total|distance|vzdálenost|vzdalenost|planned|plán\w*|cca|~)\W*$", re.I)
_WARM_RX = re.compile(r"(rozklus\w*|výklus\w*|vyklus\w*|warm[\s-]?up|cool[\s-]?down|zahřát\w*|wu\b|cd\b)", re.I)
_REP_DIST = re.compile(r"(\d{1,2})\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(km|m)\b", re.I)
_INTERVAL_RX = re.compile(r"(\d{1,2}\s*[x×]\s*\(?\s*\d+(?:[.,]\d+)?\s*(?:km|m|min|s|'|´|\")?[^,;\n]*)", re.I)


def _f(s) -> float:
    return float(str(s).replace(",", "."))


def _kind(text: str) -> tuple:
    t = text.lower()
    for k, rx in KIND_WORDS:
        if re.search(rx, t, re.I):
            return k, False
    return "easy", True


def parse_line(text: str) -> dict:
    """One session's description → {kind, km, duration_min, intervals, target, ascent_m,
    descent_m, notes, unsure[]}."""
    t = " ".join(text.split())
    kind, unsure_kind = _kind(t)
    out = {"kind": kind, "title": t[:80], "notes": t if len(t) > 80 else None, "unsure": []}
    if unsure_kind:
        out["unsure"].append("kind")
    if kind == "rest":
        return out
    km, total, parts = None, None, []
    for m in _KM_RX.finditer(t):
        v = _f(m.group(1)) * (1.609 if m.group(2).lower().startswith("mi") else 1.0)
        if not 0.5 <= v <= 120:
            continue
        if _TOTAL_RX.search(t[max(0, m.start() - 24):m.start()]):
            total = v                            # "celkem 12 km", "Planned distance: 11 km"
        parts.append(v)
    reps = sum(int(m.group(1)) * (_f(m.group(2)) if m.group(3).lower() == "km" else _f(m.group(2)) / 1000)
               for m in _REP_DIST.finditer(t))
    if total is not None:
        km = total
    elif parts and reps and _WARM_RX.search(t):
        km = sum(parts) + reps                   # "2 km rozklus, 6× 1 km, 2 km výklus"
    elif parts:
        km = max(parts)                          # the session's total, not a repetition's
    if km is not None:
        out["km"] = round(km, 1)
    dur = None
    m = _DUR_HMS.search(t)
    if m:
        dur = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 60
    if dur is None:
        m = _DUR_H.search(t)
        if m:
            dur = _f(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
    if dur is None:
        for m in _DUR_MIN.finditer(t):
            v = int(m.group(1))
            before = t[max(0, m.start() - 14):m.start()]
            if 15 <= v <= 400 and not re.search(r"(tempo|tempu|úsek|usek)\s*$", before, re.I) and not _WARM_RX.search(before):
                dur = max(dur or 0, v)
    if dur:
        out["duration_min"] = round(dur)
    iv = _INTERVAL_RX.search(t)
    if iv and kind in ("quality", "hills", "easy", "long"):
        out["intervals"] = re.split(_WARM_RX, iv.group(1))[0].strip(" ,;")[:80]
        if kind == "easy":
            out["kind"] = "quality"
    elif kind in ("quality", "hills"):
        hm = CP.hard_minutes(t)
        if hm is not None:
            out["intervals"] = t[:80]
    tg = _TARGET_RX.search(t)
    if tg:
        out["target"] = tg.group(1).strip()
    m = _ASC_RX.search(t)
    if m:
        out["ascent_m"] = float(m.group(1) or m.group(2))
    m = _DESC_RX.search(t)
    if m:
        out["descent_m"] = float(m.group(1) or m.group(2))
    if kind in CP.RUN and not out.get("km") and not out.get("duration_min"):
        out["unsure"].append("km")
    if kind in ("ride", "swim", "strength") and not out.get("duration_min"):
        out["unsure"].append("min")
    if out["kind"] in ("quality", "hills") and CP.hard_minutes(out.get("intervals") or t) is None:
        out["unsure"].append("z4")
    return out


def _date_in(m, week_start: date) -> date | None:
    try:
        if m.group(1):
            y = int(m.group(3)) if m.group(3) else week_start.year
            d = date(y, int(m.group(2)), int(m.group(1)))
        elif m.group(4):
            d = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        else:
            y = m.group(9)
            y = (2000 + int(y) if len(y) == 2 else int(y)) if y else week_start.year
            d = date(y, int(m.group(8)), int(m.group(7)))
    except ValueError:
        return None
    if not m.group(3) and not m.group(4) and (d - week_start).days < -180:
        d = d.replace(year=d.year + 1)            # "5. 1." in a December plan → next year
    return d


def parse_text(text: str, week_start: date) -> list:
    """A pasted plan → sessions [{date, seq, kind, …, unsure[]}]. Lines are anchored by a
    weekday (Po / Pondělí / Mon …, within the week starting `week_start`) or a date; a line
    without one continues the day above (a second session of the day)."""
    out = []
    cur = None
    for raw in (text or "").splitlines():
        line = raw.strip().strip("|").strip()
        if not line:
            continue
        cells = [c.strip() for c in re.split(r"\t|;|\s\|\s", line) if c.strip()]
        line = " ".join(cells)
        d = None
        m = _DATE_RX.search(line[:24])
        if m:
            d = _date_in(m, week_start)
            if d:
                line = (line[:m.start()] + line[m.end():]).strip(" :-–—,")
        dm = _DAY_RX.match(line)
        if dm:
            wd = _DAY_WORD[dm.group(1).lower()]
            if d is None:
                d = week_start + timedelta(days=wd)
            line = line[dm.end():].strip(" :-–—,")
        if d is None and cur is None:
            continue                                 # a heading before the first day
        if d is not None:
            cur = d
        if not line:
            continue
        parts = [p for p in re.split(r"\s+\+\s+|\s*/\s*(?=[A-ZÁ-Ža-zá-ž]{4})|\b(?:a pak|then|odpoledne|večer|vecer|pm)\b", line) if p and p.strip()]
        for p in parts or [line]:
            s = parse_line(p)
            seq = sum(1 for x in out if x["date"] == cur.isoformat())
            if s["kind"] == "rest" and seq:
                continue
            out.append({"date": cur.isoformat(), "seq": seq, **s})
    return out


# ------------------------------------------------------------------ the free language model
LLM_SYSTEM = (
    "You turn a running coach's training plan into JSON. Reply with JSON only: "
    '{"sessions": [{"date": "YYYY-MM-DD", "kind": one of easy|recovery|long|quality|hills|race|ride|swim|strength|rest|other, '
    '"title": short original wording, "km": number or null, "duration_min": number or null, '
    '"intervals": the hard part as written (e.g. "6x 1 km @4:30") or null, "z4_min": minutes of the hard part or null, '
    '"target": pace / heart-rate target as written or null, "ascent_m": number or null, "unsure": [field names you guessed]}]}. '
    "Use only what the text says; never invent distances. Weekdays belong to the week that starts on the given Monday."
)


def llm_parse(text: str, week_start: date) -> list | None:
    """The plan read by the free hosted model, validated; None when unavailable or invalid."""
    if not llm.available() or not text.strip():
        return None
    reply = llm.chat(LLM_SYSTEM, f"Monday of the week: {week_start.isoformat()}\n\nPlan:\n{text[:6000]}",
                     temperature=0.0, max_tokens=1800, timeout=40)
    return validate(_json_of(reply), week_start) if reply else None


def _json_of(reply: str):
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 1) if lo <= x <= hi else None


def validate(obj, week_start: date) -> list | None:
    """Keep only well-formed sessions in a sane range (dates within −7 / +190 days of the
    week, distances 0.5–120 km, minutes 5–600 …)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("sessions"), list):
        return None
    out = []
    for s in obj["sessions"][:60]:
        if not isinstance(s, dict):
            continue
        try:
            d = date.fromisoformat(str(s.get("date"))[:10])
        except ValueError:
            continue
        if not -7 <= (d - week_start).days <= 190:
            continue
        k = s.get("kind") if s.get("kind") in CP.KINDS else "other"
        row = {"date": d.isoformat(), "kind": k, "title": (str(s.get("title") or "")[:80] or None),
               "km": _num(s.get("km"), 0.5, 120), "duration_min": _num(s.get("duration_min"), 5, 600),
               "z4_min": _num(s.get("z4_min"), 0, 240), "intervals": (str(s["intervals"])[:80] if s.get("intervals") else None),
               "target": (str(s["target"])[:60] if s.get("target") else None),
               "ascent_m": _num(s.get("ascent_m"), 0, 5000), "descent_m": _num(s.get("descent_m"), 0, 5000),
               "notes": None,
               "unsure": [u for u in (s.get("unsure") or []) if u in ("kind", "km", "min", "z4", "date")]}
        if k in CP.RUN and not row["km"] and not row["duration_min"]:
            row["unsure"].append("km")
        out.append(row)
    out.sort(key=lambda r: r["date"])
    for r in out:
        r["seq"] = sum(1 for x in out if x["date"] == r["date"] and x is not r and out.index(x) < out.index(r))
    return out or None


def import_text(text: str, week_start: date) -> dict:
    """{sessions, via: llm | rules}. The model's reading is preferred; where the rules read
    a field differently, it is flagged for the runner to check."""
    rules = parse_text(text, week_start)
    got = None
    try:
        got = llm_parse(text, week_start)
    except Exception:  # noqa: BLE001 — the parser is always there
        log.exception("Plan import via the model failed")
    if not got:
        return {"sessions": rules, "via": "rules"}
    for s in got:
        twin = next((r for r in rules if r["date"] == s["date"] and r["seq"] == s.get("seq", 0)), None)
        if twin is None:
            s["unsure"] = sorted(set(s["unsure"]) | {"date"})
            continue
        if twin["kind"] != s["kind"]:
            s["unsure"] = sorted(set(s["unsure"]) | {"kind"})
        if twin.get("km") and s.get("km") and abs(twin["km"] - s["km"]) > 0.15 * twin["km"]:
            s["unsure"] = sorted(set(s["unsure"]) | {"km"})
    return {"sessions": got, "via": "llm"}


VISION_PROMPT = (
    "This is a photo or screenshot of a running training plan. Transcribe it as plain text lines, one session per line, "
    "each starting with the day or date exactly as written (e.g. 'Po 12.10.: 10 km lehce' or 'Tue: 6x1km @4:30'). "
    "Keep the original language and numbers. No commentary."
)


def import_photo(data_url: str, week_start: date) -> dict:
    """A photo / screenshot of the plan → transcribed by the free vision model → the text route."""
    if not data_url.startswith("data:image/"):
        raise ValueError("Nahrajte obrázek (JPG nebo PNG).")
    text, model = llm.vision(VISION_PROMPT, data_url, max_tokens=900, timeout=60)
    if not text:
        raise RuntimeError("Fotku se teď nepodařilo přečíst. Zkuste ostřejší snímek, nebo plán vložte jako text.")
    res = import_text(text, week_start)
    for s in res["sessions"]:
        s["unsure"] = sorted(set(s.get("unsure") or []))
    res.update({"via": "photo", "text": text[:4000]})
    return res


# ------------------------------------------------------------------ calendar feeds (iCal)
FEED_MAX_BYTES = 2 * 1024 * 1024
FEED_TIMEOUT = 8.0
FEED_STALE_H = 3


class FeedError(ValueError):
    pass


def _public_host(host: str) -> None:
    """Every address the host resolves to must be public (no loopback, private, link-local,
    reserved, multicast or cloud-metadata ranges)."""
    if not host:
        raise FeedError("Neplatná adresa kalendáře.")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FeedError("Server kalendáře nebyl nalezen.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise FeedError("Tato adresa kalendáře není povolená.")


def check_url(url: str) -> str:
    """webcal:// → https://; https only, no credentials, default port, a public host."""
    u = (url or "").strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    p = urlparse(u)
    if p.scheme != "https":
        raise FeedError("Odkaz musí začínat https:// nebo webcal://.")
    if p.username or p.password or (p.port not in (None, 443)):
        raise FeedError("Tato adresa kalendáře není povolená.")
    _public_host(p.hostname or "")
    if len(u) > 2000:
        raise FeedError("Odkaz je příliš dlouhý.")
    return u


def fetch_feed(url: str) -> str:
    """The calendar's text: redirects followed by hand (each one re-checked), at most 2 MB."""
    u = check_url(url)
    for _ in range(4):
        with httpx.Client(timeout=FEED_TIMEOUT, follow_redirects=False,
                          headers={"User-Agent": "Doslap-plan/1.0", "Accept": "text/calendar, */*"}) as client:
            with client.stream("GET", u) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    nxt = httpx.URL(u).join(resp.headers["location"])
                    u = check_url(str(nxt))
                    continue
                if resp.status_code != 200:
                    raise FeedError(f"Kalendář odpověděl chybou {resp.status_code}.")
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > FEED_MAX_BYTES:
                        raise FeedError("Kalendář je příliš velký.")
                text = buf.decode(resp.encoding or "utf-8", errors="replace")
                if "BEGIN:VCALENDAR" not in text[:2000]:
                    raise FeedError("Na odkazu není kalendář ve formátu iCal.")
                return text
    raise FeedError("Příliš mnoho přesměrování.")


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_ics(text: str) -> list:
    """VEVENTs → [{uid, date, summary, description}] (unfolded lines, date or date-time)."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    out, ev = [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            ev = {}
        elif ln == "END:VEVENT":
            if ev and ev.get("date"):
                out.append(ev)
            ev = None
        elif ev is not None and ":" in ln:
            key, val = ln.split(":", 1)
            name = key.split(";")[0].upper()
            if name == "DTSTART":
                m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
                if m:
                    ev["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            elif name == "SUMMARY":
                ev["summary"] = _unescape(val)
            elif name == "DESCRIPTION":
                ev["description"] = _unescape(val)
            elif name == "UID":
                ev["uid"] = val[:200]
    return out


_TP_PREFIX = re.compile(r"^\s*(run|running|běh|bike|cycling|ride|swim|strength|brick|other|day off|rest)\s*[:\-–]\s*", re.I)


def ics_sessions(events: list, today: date) -> list:
    """Calendar events → planned sessions (the parser on the title + the description),
    from a week back to 6 months ahead; events that read as nothing training-like are left out."""
    lo, hi = today - timedelta(days=7), today + timedelta(days=183)
    out = []
    for ev in sorted(events, key=lambda e: e["date"]):
        try:
            d = date.fromisoformat(ev["date"])
        except ValueError:
            continue
        if not lo <= d <= hi:
            continue
        title = ev.get("summary") or ""
        desc = (ev.get("description") or "")[:600]
        pref = _TP_PREFIX.match(title)
        s = parse_line(f"{title} {desc}")
        if pref:
            w = pref.group(1).lower()
            base = {"bike": "ride", "cycling": "ride", "ride": "ride", "swim": "swim", "strength": "strength",
                    "day off": "rest", "rest": "rest"}.get(w)
            if base:
                s["kind"] = base
        elif "kind" in s.get("unsure", []) and not re.search(r"\d", title + desc):
            continue                                  # "Dentist" — not a session
        s["title"] = title[:80] or s.get("title")
        s["notes"] = desc[:400] or None
        seq = sum(1 for x in out if x["date"] == d.isoformat())
        out.append({"date": d.isoformat(), "seq": seq, "ext_uid": ev.get("uid"), **s})
    return out


def sync_feed(db, runner, now_iso: str, today: date) -> dict:
    """Pull the runner's calendar and replace its sessions (source = ics) from a week back on;
    days the coach edited in the overview keep the coach's sessions."""
    from . import models
    try:
        events = parse_ics(fetch_feed(runner.plan_feed_url))
        sess = ics_sessions(events, today)
    except FeedError as e:
        st = {"ok": False, "at": now_iso, "error": str(e), "n": (runner.plan_feed_status or {}).get("n")}
        runner.plan_feed_status = st
        db.commit()
        return st
    except Exception as e:  # noqa: BLE001
        log.warning("Plan feed failed for %s: %s", runner.id, e)
        st = {"ok": False, "at": now_iso, "error": "Kalendář se nepodařilo načíst.", "n": (runner.plan_feed_status or {}).get("n")}
        runner.plan_feed_status = st
        db.commit()
        return st
    P = models.PlannedSession
    lo = (today - timedelta(days=7)).isoformat()
    coach_days = {r.date for r in db.query(P.date).filter(P.runner_id == runner.id, P.source == "coach", P.date >= lo)}
    edited = {r.ext_uid for r in db.query(P.ext_uid).filter(P.runner_id == runner.id, P.source != "ics",
                                                            P.ext_uid.isnot(None), P.date >= lo)}
    db.query(P).filter(P.runner_id == runner.id, P.source == "ics", P.date >= lo).delete(synchronize_session=False)
    n = 0
    for s in sess:
        if s["date"] in coach_days or (s.get("ext_uid") and s["ext_uid"] in edited):
            continue                              # the coach's day / the runner's own edit of this event
        db.add(P(runner_id=runner.id, date=s["date"], seq=s["seq"], kind=s["kind"], title=s.get("title"),
                 km=s.get("km"), duration_min=s.get("duration_min"), z4_min=s.get("z4_min"),
                 intervals=s.get("intervals"), target=s.get("target"), ascent_m=s.get("ascent_m"),
                 descent_m=s.get("descent_m"), notes=s.get("notes"), source="ics", ext_uid=s.get("ext_uid"),
                 created_at=now_iso, updated_at=now_iso))
        n += 1
    st = {"ok": True, "at": now_iso, "n": n, "error": None}
    runner.plan_feed_status = st
    db.commit()
    return st


def feed_stale(runner, now: datetime) -> bool:
    st = runner.plan_feed_status or {}
    if not runner.plan_feed_url:
        return False
    try:
        at = datetime.fromisoformat(str(st.get("at"))[:19])
    except ValueError:
        return True
    return (now.replace(tzinfo=None) - at) > timedelta(hours=FEED_STALE_H)
