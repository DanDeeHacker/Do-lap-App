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
    next_allowed_at: str | None = None   # round 2 F3.1: when the next return-to-run session may start


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


PAIN_SOURCE_CS = {"checkin": "check-in", "activity": "po běhu", "rtr_session": "návrat k běhu",
                  "rtr_morning": "ráno po sezení", "exercise": "cvičení"}


def pain_events(db: DBSession, rid: str, frm: str | None = None, to: str | None = None) -> list[dict]:
    """Round 2 F4.1: every pain the runner reported, from one query — check-ins, post-run ratings, return-to-run
    sessions and their next-morning answers, programme exercises. Each event is
    {at, score, region, side, source, ref}; return-to-run pain takes the plan's episode or injury region and side.
    `frm` / `to` are ISO dates or datetimes (inclusive day bounds). Sorted by time; zero scores are kept (a
    report of no pain is still a report) — consumers count `score > 0` as pain."""
    lo = (frm or "")[:10]
    hi = (to or "9999-12-31")[:10] + "~"          # "~" sorts after any time on that day
    out: list[dict] = []

    def add(at, score, region, side, source, ref):
        if at and score is not None and lo <= at < hi:
            out.append({"at": at, "score": int(score), "region": region, "side": side, "source": source, "ref": ref})

    q = db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.pain_score.isnot(None))
    for c in q.all():
        pts = [pt for pt in (c.pain_points or []) if isinstance(pt, dict) and pt.get("region")]
        if pts and (c.pain_score or 0) > 0:
            for pt in pts:
                add(c.submitted_at, c.pain_score, pt.get("region"), pt.get("side"), "checkin", f"checkin:{c.id}")
        else:
            add(c.submitted_at, c.pain_score, c.pain_site, None, "checkin", f"checkin:{c.id}")
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid,
                                                      models.ActivityFeedback.pain_during.isnot(None)).all():
        add(f.submitted_at, f.pain_during, f.pain_site, None, "activity", f"activity:{f.activity_id}")
    plans = {p.id: p for p in db.query(models.ReturnToRun).filter_by(runner_id=rid).all()}
    where: dict[int, tuple] = {}
    for pid, plan in plans.items():
        ep = db.get(models.CareEpisode, plan.episode_id) if getattr(plan, "episode_id", None) else None
        reg, side = (ep.region, ep.side) if ep and ep.region else (None, None)
        if reg is None:
            inj = (db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid,
                                                        models.InjuryReport.body_region.isnot(None))
                   .order_by(models.InjuryReport.submitted_at.desc()).first())
            reg, side = (inj.body_region, inj.body_side) if inj else (None, None)
        where[pid] = (reg, side)
    for s in db.query(models.RtrSession).filter(models.RtrSession.runner_id == rid).all():
        reg, side = where.get(s.plan_id, (None, None))
        add(s.logged_at, s.pain, reg, side, "rtr_session", f"rtr_session:{s.id}")
        if s.next_morning_pain is not None:
            add(s.morning_at or s.logged_at, s.next_morning_pain, reg, side, "rtr_morning",
                f"rtr_session:{s.id}")
    for lg in db.query(models.ExerciseLog).filter(models.ExerciseLog.runner_id == rid, models.ExerciseLog.pain.isnot(None)).all():
        add(lg.created_at or lg.logged_on, lg.pain, None, None, "exercise", f"exercise_log:{lg.id}")
    out.sort(key=lambda e: e["at"])
    return out


def last_pain(db: DBSession, rid: str) -> dict | None:
    ev = pain_events(db, rid)
    if not ev:
        return None
    e = ev[-1]
    return {"score": e["score"], "site": e["region"], "at": e["at"], "source": e["source"]}


def pain_summary(events: list[dict]) -> dict:
    """Counts for 'Příznaky' and 'Kde to bolí' from pain_events: every source counts and is named."""
    pains = [e for e in events if e["score"] > 0]
    by_src: dict[str, int] = {}
    for e in pains:
        by_src[e["source"]] = by_src.get(e["source"], 0) + 1
    regions: dict[str, dict] = {}
    for e in pains:
        if not e["region"]:
            continue
        x = regions.setdefault(e["region"], {"region": e["region"], "count": 0, "max": 0, "last": None, "sides": []})
        x["count"] += 1
        x["max"] = max(x["max"], e["score"])
        x["last"] = max(x["last"] or "", e["at"][:10])
        if e["side"] and e["side"] not in x["sides"]:
            x["sides"].append(e["side"])
    return {"count": len(pains), "days": len({e["at"][:10] for e in pains}), "max": max((e["score"] for e in pains), default=None),
            "by_source": by_src, "sources_cs": ", ".join(f"{PAIN_SOURCE_CS[k]} {v}×" for k, v in sorted(by_src.items(), key=lambda kv: -kv[1])),
            "regions": sorted(regions.values(), key=lambda x: -x["count"])}


def _active_plan(db: DBSession, rid: str) -> models.ReturnToRun | None:
    return (db.query(models.ReturnToRun).filter(models.ReturnToRun.runner_id == rid,
                                                models.ReturnToRun.status.in_(("active", "paused")))
            .order_by(models.ReturnToRun.id.desc()).first())


WEEKDAY_CS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")


def rest_gap_headline(nxt: datetime, now: datetime) -> tuple[str, bool]:
    """Round 2 F3.1 (P0.2 row 4): the headline inside the return-to-run rest gap, in local time, and whether
    the runner may run today at all (only from `nxt` on, when it falls later today)."""
    nxt = nxt.astimezone(now.tzinfo) if nxt.tzinfo and now.tzinfo else nxt
    if nxt.date() == now.date():
        return f"Další sezení návratu k běhu dnes od {nxt.strftime('%H:%M')}.", False
    if nxt.date() == now.date() + timedelta(days=1):
        return f"Dnes bez běhu — další sezení zítra od {nxt.strftime('%H:%M')}.", False
    return f"Dnes bez běhu — další sezení {WEEKDAY_CS[nxt.weekday()]} {nxt.day}. {nxt.month}.", False


def next_session_at(db: DBSession, plan: models.ReturnToRun) -> datetime | None:
    """When the next return-to-run session may start: MIN_HOURS_BETWEEN_SESSIONS after the last one."""
    # round 2 F5.1: a pain report from inside the gap is not a session and does not restart the gap
    last = (db.query(models.RtrSession.logged_at).filter(models.RtrSession.plan_id == plan.id,
                                                         (models.RtrSession.count_reason.is_(None))
                                                         | (models.RtrSession.count_reason != "pain_report"))
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
            head, _ = rest_gap_headline(nxt, now)
            return CareDirective("rtr", False, None, head,
                                 f"Mezi sezeními plánu návratu má být aspoň {MIN_HOURS_BETWEEN_SESSIONS} hodin.",
                                 name, True, nxt.isoformat())
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


def _block_running(g: dict, why: str, physio: bool = False) -> None:
    """Round 2 F3.3: when running is not allowed, "Jiné možnosti dnes" lists only what is (rest and cross-
    training) plus one line saying why — the running options are removed, not marked "nedoporučeno". The
    week's running target becomes 0 with the reason, and the day's pick becomes rest (P0.2.4)."""
    types = g.get("types") or {}
    for t in RUN_TYPES:
        types.pop(t, None)
    if g.get("rank"):
        g["rank"] = [k for k in g["rank"] if k in types]
    if g.get("type") not in types:
        g["type"] = "volno" if "volno" in types else next(iter(types), None)
    if g.get("override"):
        g["typeLabel"] = g["override"]["title"]
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume")
    if isinstance(vol, dict):
        vol["engineBudget"] = vol.get("budget")
        vol["budget"], vol["left"], vol["todayMax"] = 0, 0, 0
    g["noRun"] = {"reason": why, "physio": physio, "line": f"Běh dnes ne — {why}",
                  "capacity": "Běh dnes 0 km podle pokynu fyzioterapeuta." if physio else f"Běh dnes 0 km — {why}"}


def _num(x: float) -> str:
    return (str(int(x)) if float(x).is_integer() else f"{x:.1f}").replace(".", ",")


def apply_clinical_limits(g: dict, limits: list, physio_name: str | None) -> bool:
    """Round 2 F3.4 (W12.2, W12.4): the physio's limits change the numbers, not just a note. The weekly target is
    min(engine, max_km_week), one run min(engine, max_km_session); the recommended session must fit what is left
    of the week; no_intervals removes the interval and quality sessions; descent is capped. Returns True when a
    limit changed the outcome (the directive's source becomes clinical_limit)."""
    from . import work as W
    if not g or not limits:
        return False
    types = g.get("types") or {}
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    before = (g.get("type"), {k: (v.get("km") or {}).get("hi") for k, v in types.items() if isinstance(v, dict)},
              vol.get("budget"))
    who = physio_name or "fyzioterapeuta"
    notes = [f"Podle {who}: {W.limit_text(x)} — {x.reason_cs}" if x.reason_cs else f"Podle {who}: {W.limit_text(x)}"
             for x in limits]
    week_cap = min((x.value for x in limits if x.kind == "max_km_week" and x.value is not None), default=None)
    run_cap = min((x.value for x in limits if x.kind == "max_km_session" and x.value is not None), default=None)
    remaining = None
    if week_cap is not None and vol:
        if vol.get("budget") is None or vol["budget"] > week_cap:
            vol["engineBudget"] = vol.get("budget")
            vol["budget"] = week_cap
        remaining = max(0.0, round(vol["budget"] - (vol.get("done") or 0), 1))
        vol["left"] = remaining
        vol["todayMax"] = min(vol.get("todayMax") if vol.get("todayMax") is not None else remaining, remaining)
    cap = min((c for c in (run_cap, remaining) if c is not None), default=None)
    for t in RUN_TYPES:
        x = types.get(t)
        if not isinstance(x, dict) or t == "závod":
            continue
        km = x.get("km") or {}
        if cap is not None and km.get("hi") is not None:
            if (km.get("lo") or 0) > cap or cap <= 0:
                x["allowed"], x["why"] = False, notes[0] if len(notes) == 1 else "Nevejde se do omezení fyzioterapeuta"
            elif km["hi"] > cap:
                km["hi"] = cap
                km["max"] = min(km.get("max") or cap, cap)
                x.setdefault("notes", []).insert(0, notes[0])
    kinds = {x.kind for x in limits}
    if kinds & {"no_intervals", "max_high_intensity_min"}:
        for t in ("kvalitní",):
            types.pop(t, None)
        if g.get("rank"):
            g["rank"] = [k for k in g["rank"] if k in types]
    for x in limits:
        if x.kind in ("no_downhill", "max_descent_m"):
            for t in types.values():
                if isinstance(t, dict) and "descentMax" in t:
                    t["descentMax"] = 0 if x.kind == "no_downhill" else min(t.get("descentMax") or x.value, x.value)
    # the recommended session must fit: fall back to the longest run that does, else rest
    cur = types.get(g.get("type"))
    if g.get("type") in RUN_TYPES and (cur is None or not cur.get("allowed", True)):
        fit = next((t for t in ("dlouhý", "lehký", "regenerace") if types.get(t, {}).get("allowed")), None)
        g["type"] = fit or ("volno" if "volno" in types else g.get("type"))
        g["typeLabel"] = (types.get(g["type"]) or {}).get("label", g.get("typeLabel"))
    g["limits"] = notes
    after = (g.get("type"), {k: (v.get("km") or {}).get("hi") for k, v in types.items() if isinstance(v, dict)},
             vol.get("budget"))
    return after != before


def guidance_physio(out: dict) -> list[str]:
    """Round 2 F3.6 (P0.11): what the client sees today, said to the physio in the third person — never "jste"
    or "vám". Nothing from the engine when the data are stale or missing."""
    fr = (out.get("freshness") or {}).get("status")
    if fr in ("stale", "none"):
        return []
    g = out.get("guidance") or {}
    d = out.get("careDirective") or {}
    bullets: list[str] = []
    if g.get("noRun"):
        bullets.append(f"Běh dnes ne — {g['noRun']['reason']}")
    t = (g.get("types") or {}).get(g.get("type")) or {}
    km = t.get("km") or {}
    if d.get("running_allowed") is not False and g.get("type") in RUN_TYPES and km.get("hi"):
        lo, hi = km.get("lo") or km["hi"], km["hi"]
        rng = _num(hi) if lo == hi else f"{_num(lo)}–{_num(hi)}"
        bullets.append(f"Doporučený trénink: {t.get('label', g.get('type'))}, {rng} km.")
    wk = g.get("week") or {}
    vol = (wk.get("channels") or {}).get("volume") or {}
    cyc = wk.get("cycle") or {}
    if vol.get("budget") is not None and not g.get("noRun"):
        eng = vol.get("engineBudget")
        tail = f" (omezeno z {_num(eng)} km)" if eng is not None and eng != vol["budget"] else ""
        line = f"týdenní cíl {_num(vol['budget'])} km{tail}; od pondělí naběháno {_num(vol.get('done') or 0)} km."
        if cyc.get("pos") and wk.get("mode") in ("build", "recovery"):
            line = f"{cyc['pos']}. týden cyklu, {line}"
        bullets.append(line[0].upper() + line[1:])
        if cyc.get("manual"):
            bullets.append("Týden cyklu si klient zvolil ručně.")
    bullets.extend(g.get("limits") or [])
    return bullets


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
    g = out.get("guidance")
    if g and d.source == "engine":
        # W12.2 / round 2 F3.4: the lower of the engine's numbers and the physio's limits; when a limit changes
        # the outcome, the directive says so (source clinical_limit, running still allowed)
        from . import work as W
        lims = [x for x in W.active_limits(db, rid) if x.kind != "no_running"]
        if lims and fr["status"] not in ("stale", "none"):
            ph = db.get(models.Physio, lims[0].physio_id)
            if apply_clinical_limits(g, lims, ph.name if ph else None):
                t = (g.get("types") or {}).get(g.get("type")) or {}
                d = CareDirective("clinical_limit", any((g.get("types") or {}).get(x, {}).get("allowed") for x in RUN_TYPES),
                                  None, t.get("label") or g.get("typeLabel"), (g.get("limits") or [None])[0],
                                  ph.name if ph else d.physio_name, True)
    out["careDirective"] = asdict(d)
    if g and d.running_allowed is False and d.source in ("rtr", "rtr_paused", "clinical_limit", "injury", "safety"):
        if d.source != "injury" and d.source != "safety":
            g["override"] = {"kind": d.source, "title": d.headline_cs, "text": d.reason_cs, "session": d.session}
        _block_running(g, d.reason_cs or d.headline_cs or "", physio=d.source != "safety")
    elif g and d.source in ("rtr",) and d.running_allowed:
        # today's return-to-run session is the only run: the plan's level, nothing from the engine's menu
        g["override"] = {"kind": d.source, "title": d.headline_cs, "text": d.reason_cs, "session": d.session}
        _block_running(g, "dnes jen sezení podle plánu návratu k běhu", physio=True)
        g["noRun"].update(line="Jiný běh dnes ne — jen sezení podle plánu návratu k běhu.",
                          capacity="Dnes jen sezení podle plánu návratu k běhu.")
    out["guidance_physio"] = guidance_physio(out)
    st = display_state(out, d)
    out["display_state"] = st
    out["display_label"] = DISPLAY_LABEL.get(st)
    return out
