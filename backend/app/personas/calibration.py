"""Personas stage 3 (owner request 2026-10-27): the personas' habits follow how the pilot really
uses the app. Production builds an anonymous profile from runners who agreed to it
(Settings.share_usage) — groups of at least K people, behaviour only: how often they open the
app and when, which tabs and for how long, how often they check in and rate a run. No health
data, no per-person rows. Staging imports the profile; each persona keeps its character and
moves halfway towards its group."""
from datetime import date, datetime, timedelta
from statistics import median

from .. import models
from ..metrics import engine as E

K_MIN = 5            # smallest group that may be reported
WINDOW = 56          # days of usage looked at
BLEND = 0.5          # persona ↔ pilot


def current(db) -> dict | None:
    row = db.query(models.PersonaCalibration).order_by(models.PersonaCalibration.id.desc()).first()
    return row.data_json if row else None


def group_for(p: dict) -> str:
    return "novice" if p.get("running_months", 99) < 12 else "experienced"


def blend(key: str, p: dict, cal: dict | None) -> dict:
    h = dict(p["habits"])
    groups = (cal or {}).get("groups") or {}
    g = groups.get(group_for(p)) or groups.get("all")
    if not g:
        h["calibrated"] = False
        return h
    for k in ("checkin", "feedback", "open"):
        if g.get(k) is not None:
            h[k] = round((1 - BLEND) * h[k] + BLEND * g[k], 2)
    if g.get("topHours"):
        h["hours"] = sorted(g["topHours"][:3])
    if g.get("tabs"):
        h["tabs"] = g["tabs"]
    if g.get("minutesPerDay") is not None:
        h["minutesPerDay"] = g["minutesPerDay"]
    h.update(calibrated=True, calibrationGroup=group_for(p) if groups.get(group_for(p)) else "all", calibrationN=g.get("n"))
    return h


def _real_today() -> date:
    return datetime.now(E.LOCAL_TZ).date()


def profile(db) -> dict:
    """The anonymous behaviour profile (production, Team Console → Pilot). Groups below K_MIN
    people are left out entirely."""
    from ..deps import GUEST_PROVIDER, tutorial_demo_runner_id
    from . import catalog as KAT
    today = _real_today()
    lo = (today - timedelta(days=WINDOW)).isoformat()
    consent = {s.user_id for s in db.query(models.Settings).filter(models.Settings.share_usage.is_(True)).all()}
    demo = tutorial_demo_runner_id(db)
    users = [u for u in db.query(models.User).filter(models.User.role == "runner", models.User.runner_id.isnot(None)).all()
             if u.id in consent and u.runner_id != demo and u.provider not in (GUEST_PROVIDER, KAT.PROVIDER)
             and not (u.email or "").lower().endswith("@demo.cz")]
    runners = {r.id: r for r in db.query(models.Runner).filter(models.Runner.id.in_([u.runner_id for u in users])).all()} if users else {}
    per_user = []
    for u in users:
        rows = db.query(models.UsageDay).filter(models.UsageDay.user_id == u.id, models.UsageDay.day > lo).all()
        if not rows:
            continue
        days = {r.day for r in rows if r.tab == "_app"} or {r.day for r in rows}
        first = max(min(r.day for r in rows), lo)
        span = max(1, (today - date.fromisoformat(first)).days)
        hours = [0] * 24
        tabs: dict = {}
        secs = 0
        for r in rows:
            if r.tab == "_app" and r.hour is not None:
                hours[r.hour] += r.views or 1
            elif not r.tab.startswith(("_", "f:")):
                tabs[r.tab] = tabs.get(r.tab, 0) + (r.seconds or 0)
                secs += r.seconds or 0
        ci = db.query(models.Checkin).filter(models.Checkin.runner_id == u.runner_id, models.Checkin.submitted_at > lo).count()
        runs = db.query(models.Activity).filter(models.Activity.runner_id == u.runner_id, models.Activity.started_at > lo,
                                                models.Activity.sport == "running").count()
        rated = db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == u.runner_id,
                                                         models.ActivityFeedback.submitted_at > lo).count()
        r = runners.get(u.runner_id)
        months = None
        if r is not None and r.running_since:
            months = (today - date.fromisoformat(r.running_since[:10])).days / 30.4
        per_user.append({"open": min(1.0, len(days) / span), "hours": hours, "tabs": tabs, "secs": secs,
                         "minutes": secs / 60 / max(1, len(days)), "checkin": min(1.0, ci / max(1, len(days))),
                         "feedback": min(1.0, rated / runs) if runs else None,
                         "group": "novice" if months is not None and months < 12 else "experienced"})

    def agg(rows: list) -> dict | None:
        if len(rows) < K_MIN:
            return None
        hours = [sum(r["hours"][h] for r in rows) for h in range(24)]
        tot_h = sum(hours) or 1
        tabs: dict = {}
        for r in rows:
            for k, v in r["tabs"].items():
                tabs[k] = tabs.get(k, 0) + v / (r["secs"] or 1)       # each person counts once
        tot_t = sum(tabs.values()) or 1
        fb = [r["feedback"] for r in rows if r["feedback"] is not None]
        return {"n": len(rows), "open": round(median(r["open"] for r in rows), 2),
                "checkin": round(median(r["checkin"] for r in rows), 2),
                "feedback": round(median(fb), 2) if len(fb) >= K_MIN else None,
                "minutesPerDay": round(median(r["minutes"] for r in rows), 1),
                "hours": [round(h / tot_h, 3) for h in hours],
                "topHours": [h for h, _ in sorted(enumerate(hours), key=lambda x: -x[1])[:3] if hours[h]],
                "tabs": {k: round(v / tot_t, 3) for k, v in sorted(tabs.items(), key=lambda x: -x[1])[:8]}}
    groups = {}
    for name, rows in (("all", per_user), ("novice", [r for r in per_user if r["group"] == "novice"]),
                       ("experienced", [r for r in per_user if r["group"] == "experienced"])):
        g = agg(rows)
        if g:
            groups[name] = g
    return {"kind": "doslap-behaviour-profile", "v": 1, "generatedAt": datetime.now(E.LOCAL_TZ).isoformat(timespec="seconds"),
            "windowDays": WINDOW, "kMin": K_MIN, "consenting": len(per_user), "groups": groups}


def valid(data: dict) -> bool:
    if not isinstance(data, dict) or data.get("kind") != "doslap-behaviour-profile":
        return False
    for g in (data.get("groups") or {}).values():
        if not isinstance(g, dict) or (g.get("n") or 0) < K_MIN:
            return False
    return True
