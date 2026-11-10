"""What both sides are shown about a runner today, decided in one place (physio brief 2026-11-09
P0.2–P0.4). The engine's stored result stays as computed (D8: the physio's instruction outranks the
engine only at the presentation layer); this module adds to a copy of it:

- `freshness` — how old the newest data is. Stale or missing data is not health: no score, risk tier
  or training recommendation is shown, only confirmed injuries and explicit symptoms (P0.3).
- `lastPain` — the latest pain the runner reported, from a check-in, a post-run rating or a
  return-to-run session.
- `careDirective` — the one answer to "may this runner run today?", first match wins (P0.2):
  safety red flag → physio's clinical limit (Phase 2, not built yet) → return-to-run plan (with the
  rest gap) → paused plan → confirmed injury → the engine.
- `display_state` — a status label that cannot contradict the others (P0.4).
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import engine as E

FRESH_MAX_DAYS = 3    # product assumption, review after the pilot (physio brief D9)
AGING_MAX_DAYS = 13   # product assumption, review after the pilot (physio brief D9)
MIN_HOURS_BETWEEN_SESSIONS = 20   # return-to-run rest gap (physio brief P0.7)
RUN_TYPES = ("regenerace", "lehký", "dlouhý", "kvalitní", "závod")

DISPLAY_LABEL = {"injury": "Zranění v péči", "rtr": "Návrat k běhu", "unknown": "Bez aktuálních dat"}


@dataclass(frozen=True)
class CareDirective:
    source: str                     # safety | clinical_limit | rtr | rtr_paused | injury | engine
    running_allowed: bool | None    # None = cannot be determined
    session: dict | None            # the return-to-run level for today
    headline_cs: str | None
    reason_cs: str | None
    physio_name: str | None
    physio_involved: bool = False


def _day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def data_freshness(last_activity: date | None, last_checkin: date | None, last_sync: date | None, today: date) -> dict:
    known = [d for d in (last_activity, last_checkin, last_sync) if d]
    if not known:
        return {"status": "none", "last_data_at": None, "days_since": None}
    last = max(known)
    days = (today - last).days
    status = "fresh" if days <= FRESH_MAX_DAYS else "aging" if days <= AGING_MAX_DAYS else "stale"
    return {"status": status, "last_data_at": last.isoformat(), "days_since": days}


def freshness_for(db: DBSession, rid: str, today: date | None = None) -> dict:
    act = (db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid)
           .order_by(models.Activity.started_at.desc()).first())
    ci = (db.query(models.Checkin.submitted_at).filter(models.Checkin.runner_id == rid)
          .order_by(models.Checkin.submitted_at.desc()).first())
    syncs = [s for (s,) in db.query(models.Integration.last_sync_at).filter(
        models.Integration.runner_id == rid, models.Integration.status == "connected").all() if s]
    today = today or E.today_date()
    # a date in the future (clock skew, a seeded record) counts as today
    clamp = lambda d: min(d, today) if d else None   # noqa: E731
    return data_freshness(clamp(_day(act[0] if act else None)), clamp(_day(ci[0] if ci else None)),
                          clamp(_day(max(syncs) if syncs else None)), today)


def last_pain(db: DBSession, rid: str) -> dict | None:
    cands = []
    ci = (db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.pain_score.isnot(None))
          .order_by(models.Checkin.submitted_at.desc()).first())
    if ci:
        cands.append((ci.submitted_at, ci.pain_score, ci.pain_site, "checkin"))
    fb = (db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid,
                                                   models.ActivityFeedback.pain_during.isnot(None))
          .order_by(models.ActivityFeedback.submitted_at.desc()).first())
    if fb:
        cands.append((fb.submitted_at, fb.pain_during, fb.pain_site, "run_rating"))
    s = (db.query(models.RtrSession).filter(models.RtrSession.runner_id == rid, models.RtrSession.pain.isnot(None))
         .order_by(models.RtrSession.logged_at.desc()).first())
    if s:
        cands.append((s.logged_at, s.pain, None, "rtr_session"))
    cands = [c for c in cands if c[0]]
    if not cands:
        return None
    at, score, site, source = max(cands, key=lambda c: c[0])
    return {"score": score, "site": site, "at": at, "source": source}


def _active_plan(db: DBSession, rid: str) -> models.ReturnToRun | None:
    return (db.query(models.ReturnToRun).filter(models.ReturnToRun.runner_id == rid,
                                                models.ReturnToRun.status.in_(("active", "paused")))
            .order_by(models.ReturnToRun.id.desc()).first())


def _when_cs(at: datetime, now: datetime) -> str:
    if at.date() == now.date():
        return f"dnes od {at.strftime('%H:%M')}"
    if at.date() == now.date() + timedelta(days=1):
        return "zítra"
    return f"{at.day}. {at.month}."


def next_session_at(db: DBSession, plan: models.ReturnToRun) -> datetime | None:
    """When the next return-to-run session may start: MIN_HOURS_BETWEEN_SESSIONS after the last one."""
    last = (db.query(models.RtrSession.logged_at).filter(models.RtrSession.plan_id == plan.id)
            .order_by(models.RtrSession.logged_at.desc()).first())
    if not last or not last[0]:
        return None
    try:
        at = datetime.fromisoformat(last[0])
    except ValueError:
        return None
    return at + timedelta(hours=MIN_HOURS_BETWEEN_SESSIONS)


def resolve_care_directive(db: DBSession, rid: str, a: dict | None, on_date: date | None = None) -> CareDirective:
    a = a or {}
    g = a.get("guidance") or {}
    ov = g.get("override") or {}
    inj = (a.get("injury") or {}).get("active") or None
    plan = _active_plan(db, rid)
    assigned = db.query(models.CareAssignment).filter(models.CareAssignment.runner_id == rid,
                                                      models.CareAssignment.status == "active").first()
    pid = (plan.physio_id if plan else None) or (assigned.physio_id if assigned else None)
    physio = db.get(models.Physio, pid) if pid else None
    name = physio.name if physio else None
    involved = bool(plan or assigned or (inj and inj.get("confirmed")))
    # 1. a safety red flag from the check-in or screening: the existing text, nothing overrides it
    if ov.get("kind") == "red_flag":
        return CareDirective("safety", False, None, ov.get("title"), ov.get("text"), name, involved)
    # 2. the physio's clinical limit "no running" (physio brief W12)
    from . import work as W
    lims = W.active_limits(db, rid)
    stop = next((x for x in lims if x.kind == "no_running"), None)
    if stop is not None:
        ph = db.get(models.Physio, stop.physio_id)
        return CareDirective("clinical_limit", False, None, "Dnes bez běhu podle pokynu fyzioterapeuta",
                             stop.reason_cs, ph.name if ph else name, True)
    # 3–5. the return-to-run plan
    if plan:
        levels = plan.levels_json or []
        cur = next((lv for lv in levels if lv.get("level") == plan.current_level), None)
        if plan.status == "paused":
            return CareDirective("rtr_paused", False, None,
                                 "Plán návratu je pozastavený. Počkejte na pokyn fyzioterapeuta.",
                                 "Fyzioterapeut plán návratu k běhu pozastavil. Do jeho pokynu dnes bez běhu.", name, True)
        now = datetime.fromisoformat(E.now_iso())
        nxt = next_session_at(db, plan)
        if nxt is not None:
            nxt = nxt if nxt.tzinfo else nxt.replace(tzinfo=now.tzinfo)
        if nxt is not None and nxt > now:
            return CareDirective("rtr", False, None, f"Dnes bez běhu — další sezení {_when_cs(nxt, now)}",
                                 f"Mezi sezeními plánu návratu má být aspoň {MIN_HOURS_BETWEEN_SESSIONS} hodin.",
                                 name, True)
        label = (cur or {}).get("label") or f"úroveň {plan.current_level}"
        return CareDirective("rtr", True, cur, f"Dnes podle plánu návratu: {label}",
                             "Jiný běh dnes ne. Po sezení zaznamenejte bolest v záložce Péče.", name, True)
    # 6. an active injury the physio confirmed, no plan yet
    if inj and inj.get("confirmed"):
        return CareDirective("injury", False, None, ov.get("title") or "Aktivní zranění — dnes bez běhu",
                             ov.get("text"), name, True)
    # 7. the engine
    allowed = None
    if g:
        allowed = any((g.get("types") or {}).get(t, {}).get("allowed") for t in RUN_TYPES)
    return CareDirective("engine", allowed, None, ov.get("title") if ov else None, ov.get("text") if ov else None,
                         name, involved)


def display_state(a: dict, directive: CareDirective | None = None) -> str:
    """Precedence (physio brief P0.4): active confirmed injury → return-to-run plan → no usable data
    → the engine's quadrant (kept unchanged in `quadrant` for the engine and history)."""
    inj = (a.get("injury") or {}).get("active") or None
    if inj and inj.get("confirmed"):
        return "injury"
    if directive and directive.source in ("rtr", "rtr_paused"):
        return "rtr"
    if (a.get("freshness") or {}).get("status") in ("stale", "none"):
        return "unknown"
    return a.get("quadrant") or "unknown"


def urgency(a: dict) -> int:
    """Queue and client-list order (physio brief P0.3): genuine risk first, then clients without current
    data, then low risk."""
    if (a.get("freshness") or {}).get("status") in ("stale", "none"):
        return 2
    return {"alert": 0, "watch": 1}.get(a.get("tier") or "", 3)


def _fmt_d(iso: str | None) -> str:
    d = _day(iso)
    return f"{d.day}. {d.month}." if d else "—"


def _block_running(g: dict, why: str) -> None:
    """No running option stays offered in "Jiné možnosti dnes"; the day's pick becomes rest, and the
    headline is the override's title (P0.2.4)."""
    types = g.get("types") or {}
    for t in RUN_TYPES:
        if t in types:
            types[t]["allowed"] = False
            types[t]["why"] = why
    if g.get("type") in RUN_TYPES and "volno" in types:
        g["type"] = "volno"
    if g.get("override"):
        g["typeLabel"] = g["override"]["title"]


def present(db: DBSession, rid: str, a: dict | None) -> dict | None:
    """The assessment as both sides are shown it today. Never written back (D8)."""
    if a is None:
        return None
    out = copy.deepcopy(a)
    fr = freshness_for(db, rid)
    out["freshness"] = fr
    out["lastPain"] = last_pain(db, rid)
    if fr["status"] in ("stale", "none"):
        for k in ("overall", "readiness", "load", "mech"):
            out[k] = None
        out["tier"] = out["quadrant"] = "unknown"
        g = out.get("guidance")
        if g:
            # no training recommendation without data; a confirmed injury or a red flag still shows
            ov = g.get("override") or {}
            if ov.get("kind") not in ("red_flag", "injury", "function", "bone_stress"):
                since = f"Poslední záznam {_fmt_d(fr['last_data_at'])} (před {fr['days_since']} dny). " if fr["last_data_at"] else ""
                g["override"] = {"kind": "no_data", "title": "Nemáme aktuální data",
                                 "text": since + "Stav ani doporučení se nepočítají. Nahrajte data a Trénink je spočítá znovu."}
            _block_running(g, "Bez aktuálních dat")
            g["noData"] = True
    d = resolve_care_directive(db, rid, out)
    out["careDirective"] = asdict(d)
    g = out.get("guidance")
    if g and d.source in ("rtr", "rtr_paused", "clinical_limit"):
        g["override"] = {"kind": d.source, "title": d.headline_cs, "text": d.reason_cs, "session": d.session}
        _block_running(g, d.headline_cs)
    if g and d.source == "engine":
        # W12.2: the lower of the engine's ceiling and the physio's limits, shown with the reason
        from . import work as W
        lims = [x for x in W.active_limits(db, rid) if x.kind != "no_running"]
        if lims:
            ph = db.get(models.Physio, lims[0].physio_id)
            W.apply_limits(g, lims, ph.name if ph else None)
    st = display_state(out, d)
    out["display_state"] = st
    out["display_label"] = DISPLAY_LABEL.get(st)
    return out
