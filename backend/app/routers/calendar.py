"""Training calendar subscription (owner request 2026-10-26).

Profile → Kalendář gives the runner a secret link to this week's plan as an iCalendar feed
(RFC 5545), the format Apple Calendar (webcal://) and Google Calendar ("From URL") subscribe
to. The feed is the same plan Trénink shows (week_plan.py, the runner's own changes included):
one all-day event per session, so nothing is placed at a time the runner didn't choose. The
calendar apps poll it themselves — Apple as often as set on the device, Google every few hours —
so the morning's re-sizing shows up with their delay. The token is the only key: no session,
no CSRF; a new link revokes the old one."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import ensure_runner_self, get_current_user, verify_csrf
from ..metrics import engine as E

router = APIRouter(tags=["calendar"])

ICON = {"run": "🏃", "kvalitní": "⚡", "dlouhý": "🏃", "strength": "💪", "ride": "🚴", "swim": "🏊", "race": "🏁", "done": "✓"}


def _url(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/api/calendar/{token}.ics"


def _out(request: Request, row) -> dict:
    if row is None:
        return {"on": False}
    https = _url(request, row.token)
    webcal = "webcal://" + https.split("://", 1)[1]
    return {"on": True, "url": https, "webcal": webcal,
            "google": "https://calendar.google.com/calendar/r?cid=" + webcal.replace(":", "%3A").replace("/", "%2F"),
            "createdAt": row.created_at, "lastUsedAt": row.last_used_at}


@router.get("/api/runners/{rid}/calendar-feed")
def get_feed(rid: str, request: Request, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    return _out(request, db.query(models.CalendarFeed).filter(models.CalendarFeed.runner_id == rid).first())


@router.post("/api/runners/{rid}/calendar-feed", dependencies=[Depends(verify_csrf)])
def new_feed(rid: str, request: Request, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """A new secret link (the old one stops working)."""
    ensure_runner_self(user, rid)
    db.query(models.CalendarFeed).filter(models.CalendarFeed.runner_id == rid).delete()
    row = models.CalendarFeed(token=secrets.token_urlsafe(24), runner_id=rid, created_at=E.now_iso())
    db.add(row)
    db.commit()
    return _out(request, row)


@router.delete("/api/runners/{rid}/calendar-feed", dependencies=[Depends(verify_csrf)])
def stop_feed(rid: str, request: Request, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    db.query(models.CalendarFeed).filter(models.CalendarFeed.runner_id == rid).delete()
    db.commit()
    return {"on": False}


# ---------------------------------------------------------------- the feed
def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 3.1: lines of at most 75 octets, continued with a leading space."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def _num(v, d=1) -> str:
    if v is None:
        return ""
    t = f"{v:.{d}f}".replace(".", ",")
    return t[:-2] if d and t.endswith(",0") else t


def _summary(it: dict) -> str:
    k = it.get("kind")
    if k == "run":
        km = it.get("km") or {}
        lo, hi = km.get("lo"), km.get("hi")
        size = f"{_num(lo)}–{_num(hi)} km" if lo and hi and abs(hi - lo) >= 0.1 else f"{_num(hi or 0)} km"
        return f"{ICON.get(it.get('type'), ICON['run'])} {it.get('label')} {size}"
    if k in ("ride", "swim"):
        m = it.get("min") or [0, 0]
        return f"{ICON[k]} {it.get('label')} {m[0]}–{m[1]} min" if m[0] != m[1] else f"{ICON[k]} {it.get('label')} {m[1]} min"
    if k == "strength":
        return f"{ICON['strength']} {it.get('label')} {it.get('session') or ''}".strip()
    if k == "race":
        return f"{ICON['race']} {it.get('label')}" + (f" {_num(it['km'])} km" if it.get("km") else "")
    if k == "done":
        return f"{ICON['done']} {it.get('label')}" + (f" {_num(it['km'])} km" if it.get("km") else "")
    return it.get("label") or ""


def _detail(it: dict) -> list:
    rows = []
    if it.get("session"):
        rows.append(("Trénink", it["session"]) if it.get("kind") == "run" else ("Program", f"{it.get('program')} · {it['session']}"))
    if it.get("hr"):
        rows.append(("Tep", f"{it['hr'][0]}–{it['hr'][1]} tep/min" + (f" · {it['zones']}" if isinstance(it.get("zones"), str) else "")))
    if it.get("pace"):
        p = it["pace"]
        rows.append(("Tempo", f"{int(p[0] // 60)}:{int(p[0] % 60):02d}–{int(p[1] // 60)}:{int(p[1] % 60):02d} /km"))
    if it.get("durationMin"):
        rows.append(("Čas", f"{it['durationMin'][0]}–{it['durationMin'][1]} min"))
    if it.get("kind") == "strength" and it.get("min"):
        rows.append(("Čas", f"{it['min'][0]}–{it['min'][1]} min · náročnost {it.get('rpe')}"))
    if it.get("descentMax") is not None:
        rows.append(("Klesání", f"do {_num(it['descentMax'], 0)} m"))
    if it.get("ascentMax") is not None:
        rows.append(("Stoupání", f"do {_num(it['ascentMax'], 0)} m"))
    if it.get("when"):
        rows.append(("Kdy", it["when"]))
    if it.get("note"):
        rows.append(("Pozn.", it["note"]))
    return rows


def ics(plan: dict | None, rid: str, lang: str, app_url: str, now: datetime) -> str:
    """The week's sessions as all-day events; the past days' finished ones stay in the calendar."""
    from .. import i18n_static as T

    def tr(s):
        return T.translate(s) if lang == "en" else s
    salt = hashlib.sha256(rid.encode()).hexdigest()[:10]
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    en = lang == "en"
    name = "Došlap · training" if en else "Došlap · trénink"
    desc = ("This week's plan from Došlap — every morning Training adjusts it to your readiness." if en else
            "Plán týdne z Došlapu — každé ráno ho Trénink upraví podle připravenosti.")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Doslap//Training plan//CS", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}", "X-WR-TIMEZONE:Europe/Prague", f"X-WR-CALDESC:{_esc(desc)}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    foot = ("Every morning Training adjusts the day to your readiness — the current version is in the app." if en else
            "Každé ráno Trénink den upraví podle připravenosti — aktuální verze je v aplikaci.")
    mine = "Your choice in the week plan." if en else "Vaše volba v Plánu týdne."
    for day in (plan or {}).get("days") or []:
        d = datetime.fromisoformat(day["date"]).date()
        for k, it in enumerate(day["items"]):
            if it.get("kind") == "rest" or it.get("optional"):
                continue
            summ = tr(_summary(it))
            body = [f"{tr(a)}: {tr(b)}" for a, b in _detail(it)] + ["", foot, app_url]
            if it.get("pinned"):
                body.insert(0, mine)
            lines += ["BEGIN:VEVENT", f"UID:{day['date']}-{k}-{it.get('kind')}-{salt}@doslap",
                      f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
                      f"SUMMARY:{_esc(summ)}", f"DESCRIPTION:{_esc(chr(10).join(body))}", f"URL:{app_url}",
                      "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


@router.get("/api/calendar/{token}.ics")
def feed(token: str, request: Request, db: DBSession = Depends(get_db)):
    row = db.query(models.CalendarFeed).filter(models.CalendarFeed.token == token).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Kalendář nenalezen — vytvořte nový odkaz v profilu.")
    from ..metrics import daily_report as DR
    rid = row.runner_id
    user = db.query(models.User).filter(models.User.runner_id == rid).first()
    a = E.get_or_refresh_assessment(db, rid)
    plan = DR._week_plan(a, db, rid, E.today_date()) if a else None
    row.last_used_at = E.now_iso()
    db.commit()
    body = ics(plan, rid, (getattr(user, "lang", None) or "cs"), f"{str(request.base_url).rstrip('/')}/app/training",
               datetime.now(timezone.utc))
    return Response(content=body, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "Content-Disposition": 'inline; filename="doslap.ics"'})
