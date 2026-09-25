"""Facts packets for the AI texts (coach_texts.py): everything a daily summary,
a training commentary or a weekly summary may say, computed by the engine and
nothing else. The model only narrates a packet; coach_validate.py rejects any
number that isn't in it, and the engine's recommendation can't be changed.

Privacy: derived values only. No name, e-mail, city, coordinates, bib, free-
text notes or activity titles (Garmin names runs after the place) are put in a
packet — it is what leaves the server for the hosted model. Numbers appear
Czech-formatted (decimal comma) so the model copies them instead of
reformatting or computing.
"""
import re
from datetime import date, timedelta

from .. import models
from . import capacity as C
from . import engine as E
from . import guidance as G

QUAD = {
    "stable": ("Stabilní", "Zátěž i mechanika sedí na vlastní normě."),
    "overreaching": ("Přetížení", "Zátěž vyskočila, ale technika zatím drží."),
    "silent": ("Tichý drift", "Mechanika se odchyluje od vaší normy — signál únavy/přetížení, ne předpověď zranění."),
    "critical": ("Kritická kombinace", "Zátěž i mechanika se hýbou naráz."),
}
TIER = {"ok": "Nízké riziko", "watch": "Sledovat", "alert": "Vysoké riziko"}
PHYSIO_REFERRALS = ("physio_48h", "physio_7d")
SURFACE = {"road": "silnice", "trail": "terén", "treadmill": "pás", "track": "dráha"}
WEEK_MODE = {"deload": "odlehčovací týden (zvýšená zátěž)", "recovery": "odlehčovací týden cyklu",
             "build": "budovací týden cyklu", "taper": "ladění před závodem", "learning": "nastavování cyklu",
             "hold": "udržovací týden"}

_DOT_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")


def cz_text(s):
    """Engine strings carry some decimals with a dot ("×3.4", "171.1 km") — the
    packet uses the Czech comma throughout so the model has one style to copy."""
    return _DOT_DECIMAL.sub(",", s) if isinstance(s, str) else s


def pace(sec) -> str | None:
    if not sec:
        return None
    sec = round(sec)
    return f"{sec // 60}:{sec % 60:02d}/km"


def cz_date(d: str | date) -> str:
    d = date.fromisoformat(d[:10]) if isinstance(d, str) else d
    return f"{d.day}. {d.month}."


def _signals(a: dict, n: int = 5) -> list[dict]:
    sig = sorted((s for s in a.get("signals") or [] if (s.get("pts") or 0) > 0), key=lambda s: -(s.get("pts") or 0))
    return [{"name": s.get("name"), "value": cz_text(s.get("val")), "detail": cz_text(s.get("detail")),
             "grade": s.get("grade")} for s in sig[:n]]


def _recovery(a: dict) -> dict:
    rcv = a.get("rcv") or {}
    g = a.get("guidance") or {}
    cr = (a.get("capacity") or {}).get("readiness") or {}
    ready = g.get("readinessScore") if g.get("readinessScore") is not None else cr.get("score")
    out = {"label": rcv.get("scoreLabel"), "readinessPct": ready if isinstance(ready, (int, float)) else None}
    for key, name, dec in (("hrv", "hrvMs", 0), ("rhr", "restingHr", 0), ("sleep", "sleepH", 1)):
        m = rcv.get(key) or {}
        if m.get("now") is not None:
            out[name] = {"now": G._cz(m["now"], dec), "usual": G._cz(m.get("base"), dec)}
    if (rcv.get("sleep") or {}).get("debt"):
        out["sleepDebtH"] = G._cz(rcv["sleep"]["debt"], 1)
    return out


def _pain(a: dict):
    p = a.get("painWarn")
    return {"score": p["score"], "site": p.get("site")} if p and p.get("score") else None


def _load(a: dict) -> dict:
    L = a.get("loadDetail") or {}
    out = {"km7": G._cz(L.get("runKm7"), 1) if L.get("runKm7") is not None else None}
    cap = (a.get("capacity") or {}).get("channels") or {}
    ch = {}
    for key in ("volume", "intensity", "descent", "ascent"):
        c = cap.get(key) or {}
        wk = c.get("week") or {}
        if wk.get("cap"):
            dec = 1 if key == "volume" else 0
            ch[key] = {"label": c.get("label"), "unit": c.get("unit"), "last7": G._cz(wk.get("now"), dec),
                       "weeklyCapacity": G._cz(wk.get("cap"), dec), "ratio": G._cz(wk.get("ratio"), 2)}
    if ch:
        out["vsCapacity"] = ch
    elif L.get("ratio") is not None:
        out["acuteChronicRatio"] = G._cz(L.get("ratio"), 2)
    return out


def _today(a: dict):
    """The v3 recommendation for today, exactly as the Trénink tab shows it."""
    g = a.get("guidance")
    if not g:
        return None
    t = (g.get("types") or {}).get(g.get("type")) or {}
    km = t.get("km") or {}
    dur = t.get("durationMin") or []
    out = {
        "type": g.get("type"), "label": g.get("typeLabel"), "provisional": bool(g.get("provisional")),
        "override": {"kind": g["override"].get("kind"), "title": cz_text(g["override"].get("title")),
                     "text": cz_text(g["override"].get("text"))} if g.get("override") else None,
        "reasons": [cz_text(r) for r in g.get("reasons") or []],
        "notes": [cz_text(n) for n in t.get("notes") or []],
        "weekMode": WEEK_MODE.get((g.get("week") or {}).get("mode"), (g.get("week") or {}).get("mode")),
        "cycleWeek": ((g.get("week") or {}).get("cycle") or {}).get("pos"),
    }
    if g.get("type") != "volno" and (km.get("hi") or 0) > 0:
        out.update({
            "km": f"{G._cz(km.get('lo'), 1)}–{G._cz(km.get('hi'), 1)} km",
            "durationMin": f"{dur[0]}–{dur[1]} min" if len(dur) == 2 and dur[1] else None,
            "hrZones": t.get("hrZones"), "hr": f"{t['hr'][0]}–{t['hr'][1]} tepů/min" if t.get("hr") else None,
            "pace": f"{pace(t['pace'][0])[:-3]}–{pace(t['pace'][1])}" if t.get("pace") else None,
            "terrain": t.get("terrain"),
            "hardMinutesMax": t.get("z4Max") or None,
            "descentMaxM": t.get("descentMax") or None, "ascentMaxM": t.get("ascentMax") or None,
        })
    left = {}
    for key, c in ((g.get("week") or {}).get("channels") or {}).items():
        dec = 1 if key == "volume" else 0
        if key not in ("volume", "intensity", "descent", "ascent"):
            continue
        left[key] = {"label": c.get("label"), "unit": c.get("unit"), "weekTarget": G._cz(c.get("budget"), dec),
                     "doneThisWeek": G._cz(c.get("done"), dec), "leftThisWeek": G._cz(c.get("left"), dec),
                     "todayMax": G._cz(c.get("todayMax"), dec)}
    if left:
        out["weekBudget"] = left
    return out


def _last_run(db, rid: str):
    a = (db.query(models.Activity)
         .filter(models.Activity.runner_id == rid, (models.Activity.sport == "running") | (models.Activity.sport.is_(None)))
         .order_by(models.Activity.started_at.desc(), models.Activity.id.desc()).first())
    if a is None:
        return None
    grade = E.bucket(a).split("|")[1] if a.distance_km else None
    w = a.weather_json or {}
    return {
        "date": cz_date(a.started_at), "daysAgo": (E.today_date() - date.fromisoformat(a.started_at[:10])).days,
        "km": G._cz(a.distance_km, 1) if a.distance_km else None, "pace": pace(a.pace_s_km),
        "avgHr": round(a.avg_hr) if a.avg_hr else None,
        "terrain": " · ".join(x for x in (SURFACE.get(a.surface or "", a.surface),
                                           {"up": "stoupání", "flat": "rovina", "down": "klesání", "rolling": "kopcovitě"}.get(grade or ""))
                              if x) or None,
        "weather": (f"{w.get('label')}, {w['tempC']} °C" if w.get("tempC") is not None
                    else f"{w.get('label')}, {w.get('tMin')}–{w.get('tMax')} °C") if w.get("label") else None,
    }


def daily_facts(db, rid: str, a: dict) -> dict:
    today = E.today_date()
    referral = E.triage_decision(a)
    q = QUAD.get(a.get("quadrant"), (a.get("quadrant"), ""))
    conf = a.get("confidence") or {}
    return {
        "kind": "daily", "date": cz_date(today), "weekday": G.WD[today.weekday()],
        "engine": a.get("engineMode") or "v1",
        "state": {"quadrant": q[0], "quadrantMeaning": q[1], "risk": TIER.get(a.get("tier"), a.get("tier")),
                  "overallScore": a.get("overall"), "loadScore": a.get("load"), "mechanicsScore": a.get("mech"),
                  "symptomsScore": a.get("symp"),
                  "baselineConfidencePct": round((conf.get("value") or 0) * 100)},
        "referral": {"code": referral, "text": E.DECISION_HEAD.get(referral), "physio": referral in PHYSIO_REFERRALS},
        "signals": _signals(a),
        "recovery": _recovery(a),
        "pain": _pain(a),
        "load": _load(a),
        "lastRun": _last_run(db, rid),
        "today": _today(a),
    }


def week_bounds(today: date) -> tuple[date, date]:
    """The last completed Monday–Sunday week."""
    start = today - timedelta(days=today.weekday() + 7)
    return start, start + timedelta(days=6)


def weekly_facts(db, rid: str, a: dict, week_start: date) -> dict:
    ws, we = week_start, week_start + timedelta(days=6)
    acts = [x for x in E.all_acts(db, rid) if x.started_at]
    in_week = lambda x, lo, hi: lo.isoformat() <= x.started_at[:10] <= hi.isoformat()
    runs = [x for x in acts if E.is_run(x) and in_week(x, ws, we)]
    other = [x for x in acts if not E.is_run(x) and in_week(x, ws, we)]
    km = sum(x.distance_km or 0 for x in runs)
    prev_km = sum(x.distance_km or 0 for x in acts if E.is_run(x) and in_week(x, ws - timedelta(days=7), ws - timedelta(days=1)))
    km4 = [sum(x.distance_km or 0 for x in acts if E.is_run(x) and in_week(x, ws - timedelta(days=7 * k), ws - timedelta(days=7 * k - 6)))
           for k in range(1, 5)]
    longest = max(runs, key=lambda x: x.distance_km or 0, default=None)
    cap = a.get("capacity") or {}
    z4 = None
    if cap.get("hrMax") and runs:
        ids = {x.id for x in runs}
        z4 = round(sum((s["exp"].get("intensity") or 0) for s in C.run_exposures(db, rid, cap["hrMax"], cap.get("hrRest"))
                       if s["id"] in ids))
    dm = {d.date: d for d in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid).all()}

    def avg(field, lo, hi, dec):
        vals = [getattr(dm[k], field) for k in dm if lo.isoformat() <= k <= hi.isoformat() and getattr(dm[k], field) is not None]
        return G._cz(sum(vals) / len(vals), dec) if vals else None
    base_lo = ws - timedelta(days=28)
    recovery = {}
    for field, name, dec in (("sleep_h", "sleepH", 1), ("hrv_ms", "hrvMs", 0), ("resting_hr", "restingHr", 0)):
        now = avg(field, ws, we, dec)
        if now is not None:
            recovery[name] = {"week": now, "previous4Weeks": avg(field, base_lo, ws - timedelta(days=1), dec)}
    pains = [c for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid).all()
             if c.submitted_at and ws.isoformat() <= c.submitted_at[:10] <= we.isoformat() and (c.pain_score or 0) > 0]
    worst = max(pains, key=lambda c: c.pain_score, default=None)
    q = QUAD.get(a.get("quadrant"), (a.get("quadrant"), ""))
    g = a.get("guidance") or {}
    wk = (g.get("week") or {}).get("channels") or {}
    return {
        "kind": "weekly", "weekFrom": cz_date(ws), "weekTo": cz_date(we), "engine": a.get("engineMode") or "v1",
        "training": {
            "runs": len(runs), "km": G._cz(km, 1),
            "timeMin": round(sum(x.duration_min or 0 for x in runs)),
            "ascentM": round(sum(x.ascent_m or 0 for x in runs)), "descentM": round(sum(x.descent_m or 0 for x in runs)),
            "hardMinutesZ4": z4,
            "longestRun": {"date": cz_date(longest.started_at), "km": G._cz(longest.distance_km, 1)}
            if longest and longest.distance_km else None,
            "crossTraining": {"sessions": len(other), "minutes": round(sum(x.duration_min or 0 for x in other))} if other else None,
        },
        "comparison": {"previousWeekKm": G._cz(prev_km, 1), "avg4WeeksKm": G._cz(sum(km4) / 4, 1),
                       "changeVsPreviousPct": round((km - prev_km) / prev_km * 100) if prev_km else None},
        "capacityNow": _load(a).get("vsCapacity"),
        "recovery": recovery,
        "pain": {"reports": len(pains), "max": worst.pain_score, "site": worst.pain_site} if worst else None,
        "stateNow": {"quadrant": q[0], "quadrantMeaning": q[1], "risk": TIER.get(a.get("tier"), a.get("tier"))},
        "referral": {"code": E.triage_decision(a), "text": E.DECISION_HEAD.get(E.triage_decision(a)),
                     "physio": E.triage_decision(a) in PHYSIO_REFERRALS},
        "signals": _signals(a, 4),
        "thisWeekPlan": {"mode": WEEK_MODE.get((g.get("week") or {}).get("mode"), (g.get("week") or {}).get("mode")),
                         "volumeBudgetKm": G._cz((wk.get("volume") or {}).get("budget"), 1) if wk.get("volume") else None,
                         "hardMinutesBudget": G._cz((wk.get("intensity") or {}).get("budget"), 0) if wk.get("intensity") else None}
        if g else None,
    }
