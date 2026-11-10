"""A physio's working day (physio brief 2026-11-09, Phase 2): clinic roles (W1), alerts for Dnes (W3), computed
free times (W5), clinical limits (W12), notifications (W15), programme adherence (W10) and the return-to-run
morning check (W11). Thresholds are named product assumptions, reviewed after the pilot."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from . import models
from . import records as R
from .metrics import engine as E

# ---- W1 roles ------------------------------------------------------------------------------------------
ROLES = ("owner", "admin", "physio", "reception")
SEAT_PRICE_CZK = int(os.environ.get("DOSSLAP_SEAT_PRICE_CZK", "690"))    # thesis: 690 CZK / seat / month excl. VAT
TRIAL_DAYS = 365                                                        # thesis assumption: one free year
PERMS = {   # W1.4
    "clinical": {"owner", "admin", "physio"},
    "clinic_calendar": {"owner", "admin", "reception"},
    "members": {"owner", "admin"},
    "practice": {"owner", "admin"},
    "billing": {"owner"},
}


def ensure_clinic(db: DBSession, physio: models.Physio) -> models.Clinic:
    """Every physio belongs to a clinic; the first member is its owner and the clinic gets a trial."""
    c = R.clinic_of(db, physio)
    if db.query(models.ClinicMember).filter_by(clinic_id=c.id, physio_id=physio.id).first() is None:
        first = db.query(models.ClinicMember).filter_by(clinic_id=c.id).first() is None
        db.add(models.ClinicMember(clinic_id=c.id, physio_id=physio.id, role="owner" if first else "physio",
                                   active=True, created_at=E.now_iso()))
    if db.query(models.Subscription).filter_by(clinic_id=c.id).first() is None:
        db.add(models.Subscription(clinic_id=c.id, status="trial", seats=1, price_czk_per_seat=SEAT_PRICE_CZK,
                                   trial_ends_at=(E.today_date() + timedelta(days=TRIAL_DAYS)).isoformat(),
                                   created_at=E.now_iso()))
    db.flush()
    return c


def role_of(db: DBSession, physio_id: str) -> str:
    m = (db.query(models.ClinicMember).filter_by(physio_id=physio_id, active=True)
         .order_by(models.ClinicMember.id).first())
    return m.role if m else "physio"


def can(db: DBSession, physio_id: str, what: str) -> bool:
    return role_of(db, physio_id) in PERMS[what]


# ---- W15 notifications -------------------------------------------------------------------------------------
class Notifier:
    """In-app first; email and SMS are channels that log until a provider is configured. Bodies never carry
    health details (W15.5) — only that something happened and where to look."""
    channels = ("in_app",)

    def send(self, db: DBSession, event: str, title: str, *, physio_id: str | None = None,
             runner_id: str | None = None, ref: str | None = None, body: str | None = None) -> list[str]:
        prefs = {}
        if physio_id:
            p = db.get(models.Physio, physio_id)
            prefs = (p.notify_settings or {}) if p else {}
        sent = []
        for ch in ("in_app", "email", "sms"):
            if ch != "in_app" and not prefs.get(ch):
                continue
            if prefs.get(f"off:{event}"):
                continue
            delivered = ch == "in_app"     # email / SMS: no provider yet — logged, not delivered
            db.add(models.Notification(physio_id=physio_id, runner_id=runner_id, channel=ch, event=event, title=title,
                                       body=body, ref=ref, delivered=delivered, created_at=E.now_iso()))
            if delivered:
                sent.append(ch)
        return sent


NOTIFY = Notifier()


# ---- W5 availability ---------------------------------------------------------------------------------------
HORIZON_DAYS, MAX_HORIZON_DAYS = 60, 90


def _local(d: date, hm: str) -> datetime:
    h, m = (int(x) for x in hm.split(":"))
    return datetime.combine(d, time(h, m), E.LOCAL_TZ)      # DST-correct: the wall clock in Prague that day


def _aware(iso: str) -> datetime:
    x = datetime.fromisoformat(iso)
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)


def busy_intervals(db: DBSession, physio_id: str) -> list[tuple[datetime, datetime]]:
    out = []
    for b in db.query(models.Booking).filter(models.Booking.physio_id == physio_id,
                                             models.Booking.status.in_(("requested", "confirmed"))).all():
        if not b.slot_at:
            continue
        s = _aware(b.slot_at)
        buf = 0
        if b.service_id:
            sv = db.get(models.Service, b.service_id)
            buf = (sv.buffer_minutes or 0) if sv else 0
        out.append((s, s + timedelta(minutes=(b.duration_min or 45) + buf)))
    for t in db.query(models.TimeOff).filter_by(physio_id=physio_id).all():
        out.append((_aware(t.starts_at), _aware(t.ends_at)))
    return out


def free_times(db: DBSession, physio_id: str, start: date, end: date, minutes: int | None = None) -> list[dict]:
    """Rules within the horizon, minus time off, minus active bookings and their buffers (W5.2)."""
    end = min(end, start + timedelta(days=MAX_HORIZON_DAYS))
    now = datetime.now(timezone.utc)
    busy = busy_intervals(db, physio_id)
    rules = db.query(models.AvailabilityRule).filter_by(physio_id=physio_id, active=True).all()
    out, d = [], start
    while d <= end:
        for r in rules:
            if r.weekday != d.weekday():
                continue
            if (r.valid_from and d.isoformat() < r.valid_from) or (r.valid_until and d.isoformat() > r.valid_until):
                continue
            step = minutes or r.slot_minutes or 45
            s, stop = _local(d, r.start_local), _local(d, r.end_local)
            while s + timedelta(minutes=step) <= stop:
                e = s + timedelta(minutes=step)
                if s > now and not any(s < b1 and b0 < e for b0, b1 in busy):
                    out.append({"start": s.isoformat(), "end": e.isoformat(), "rule_id": r.id})
                s = e
        d += timedelta(days=1)
    # one-off openings (the old slots) stay bookable
    for sl in db.query(models.PhysioSlot).filter_by(physio_id=physio_id, status="open").all():
        s = _aware(sl.slot_at)
        e = s + timedelta(minutes=sl.duration_min or 45)
        if s > now and start <= s.astimezone(E.LOCAL_TZ).date() <= end and not any(s < b1 and b0 < e for b0, b1 in busy):
            out.append({"start": s.isoformat(), "end": e.isoformat(), "slot_id": sl.id})
    return sorted(out, key=lambda x: x["start"])


def is_free(db: DBSession, physio_id: str, start: datetime, minutes: int) -> bool:
    end = start + timedelta(minutes=minutes)
    return not any(start < b1 and b0 < end for b0, b1 in busy_intervals(db, physio_id))


# ---- W12 clinical limits -----------------------------------------------------------------------------------
LIMIT_KINDS = {
    "no_running": "Dnes bez běhu", "max_km_week": "max. {v} km týdně", "max_km_session": "max. {v} km na jeden běh",
    "no_intervals": "bez intervalů a intenzity", "no_downhill": "bez seběhů", "max_descent_m": "klesání max. {v} m",
    "max_high_intensity_min": "intenzita max. {v} min",
}


def active_limits(db: DBSession, rid: str, on: date | None = None) -> list[models.ClinicalLimit]:
    on = (on or E.today_date()).isoformat()
    return [x for x in db.query(models.ClinicalLimit).filter_by(runner_id=rid, active=True).all()
            if (not x.starts_on or x.starts_on <= on) and (not x.ends_on or x.ends_on >= on)]


def limit_text(x: models.ClinicalLimit, today: date | None = None) -> str:
    """Round 2 F3.5: one wording everywhere — "max. 20 km týdně", with an end date "max. 20 km týdně do 24. 11.",
    and "tento týden" only when the limit ends this Sunday."""
    v = x.value
    vs = (str(int(v)) if v is not None and float(v).is_integer() else str(v).replace(".", ",")) if v is not None else ""
    text = LIMIT_KINDS.get(x.kind, x.kind).format(v=vs)
    end = None
    try:
        end = date.fromisoformat(x.ends_on[:10]) if x.ends_on else None
    except ValueError:
        end = None
    if end is None or x.kind == "no_running":
        return text
    t = today or E.today_date()
    sunday = t + timedelta(days=6 - t.weekday())
    if x.kind == "max_km_week" and end == sunday:
        return text.replace("týdně", "tento týden")
    return f"{text} do {end.day}. {end.month}."


def week_km(db: DBSession, rid: str) -> float:
    t = E.today_date()
    mon = t - timedelta(days=t.weekday())
    return sum(a.distance_km or 0 for a in db.query(models.Activity).filter(
        models.Activity.runner_id == rid, models.Activity.started_at >= mon.isoformat()).all()
        if (a.sport or "running") == "running")


def limit_breaches(db: DBSession, rid: str) -> list[dict]:
    """W12.5: an activity that breaks a limit."""
    out = []
    limits = active_limits(db, rid)
    if not limits:
        return out
    recent = db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                              models.Activity.started_at >= (E.today_date() - timedelta(days=7)).isoformat()).all()
    runs = [a for a in recent if (a.sport or "running") == "running"]
    for x in limits:
        if x.kind == "no_running":
            hit = [a for a in runs if (a.started_at or "")[:10] >= (x.starts_on or "")]
            if hit:
                out.append({"limit": x.id, "text": limit_text(x), "activity_id": hit[-1].id})
        elif x.kind == "max_km_session" and x.value is not None:
            hit = [a for a in runs if (a.distance_km or 0) > x.value and (a.started_at or "")[:10] >= (x.starts_on or "")]
            if hit:
                out.append({"limit": x.id, "text": limit_text(x), "activity_id": hit[-1].id})
        elif x.kind == "max_km_week" and x.value is not None and week_km(db, rid) > x.value:
            out.append({"limit": x.id, "text": limit_text(x)})
    return out


# ---- W10 adherence ---------------------------------------------------------------------------------------
def program_adherence(db: DBSession, program: models.Program, as_of: date | None = None) -> dict:
    """Round 2 F7: the one adherence number for Klienti, Dnes, Přehled, Plán, Příprava and the runner's Péče.
    Weekly (W10.9: past weeks in full, the current week by its elapsed days) when every tick has a date — a log
    without logged_on takes its created_at. Ticks from before dated logs existed (done_count above the logs) make
    it a total estimate: done / expected to date, capped at 100 %, labelled "odhad".
    Returns {pct, method, done, expected, undated_logs, weeks, text}."""
    from .routers.programs import published_at
    ex = db.query(models.Exercise).filter_by(program_id=program.id).all()
    per_week = sum(e.per_week or 0 for e in ex)
    empty = {"pct": None, "method": "weekly", "done": 0, "expected": 0, "undated_logs": 0, "weeks": [],
             "text": "Program bez cviků."}
    if not per_week:
        return empty
    try:
        start = date.fromisoformat((program.sent_at or program.started_on or published_at(db, program) or "")[:10])
    except ValueError:
        start = E.today_date()
    today = as_of or E.today_date()
    logs = db.query(models.ExerciseLog).filter(models.ExerciseLog.program_id == program.id).all()
    dated = [((lg.logged_on or (lg.created_at or "")[:10]) or None) for lg in logs]
    dated = [d for d in dated if d and start.isoformat() <= d <= today.isoformat()]
    ticks = sum(e.done_count or 0 for e in ex)
    undated = max(0, ticks - len(logs))
    weeks, expected, done = [], 0.0, 0
    ws = start - timedelta(days=start.weekday())
    while ws <= today:
        we = ws + timedelta(days=6)
        span_start, span_end = max(ws, start), min(we, today)
        frac = ((span_end - span_start).days + 1) / 7
        exp = per_week * frac
        n = sum(1 for d in dated if span_start.isoformat() <= d <= span_end.isoformat())
        weeks.append({"week": ws.isoformat(), "expected": round(exp, 1), "done": n,
                      "pct": round(100 * min(1.0, n / exp)) if exp > 0 else None})
        expected += exp
        done += n
        ws += timedelta(days=7)
    if undated:
        tot = done + undated
        pct = round(100 * min(1.0, tot / expected)) if expected else None
        return {"pct": pct, "method": "total_estimate", "done": tot, "expected": round(expected, 1),
                "undated_logs": undated, "weeks": weeks,
                "text": f"Program splněn na {pct} % (odhad)" if pct is not None else "Plnění zatím nejde spočítat."}
    pct = round(100 * min(1.0, done / expected)) if expected else None
    return {"pct": pct, "method": "weekly", "done": done, "expected": round(expected, 1), "undated_logs": 0,
            "weeks": weeks, "text": f"Program splněn na {pct} %" if pct is not None else "Plnění zatím nejde spočítat."}


def adherence(db: DBSession, program: models.Program, days: int | None = None) -> dict:
    """Kept for callers; round 2 F7 has one number (program_adherence) — `days` no longer changes it."""
    return program_adherence(db, program)


# ---- W3 alerts ---------------------------------------------------------------------------------------------
CHECKIN_PAIN_HIGH = 5          # product assumption
CHECKIN_PAIN_RISE = 2          # points above the 7-day average
ADHERENCE_LOW = 50             # % of scheduled work over 7 days
NO_DATA_DAYS = 7
SPIKE_SIGNALS = {"session_spike", "hi_load", "load_capacity"}
SEVERITY = {"rtr_paused_pain": "high", "rtr_morning_worse": "high", "checkin_pain_high": "high",
            "limit_exceeded": "high", "note_unsigned": "high", "adherence_drop": "medium", "load_spike": "medium",
            "no_data_7d": "medium", "programme_ended": "low", "no_morning_data": "medium"}
ALERT_CS = {"rtr_paused_pain": "Návrat k běhu: bolest nad hranicí", "rtr_morning_worse": "Návrat k běhu: ráno hůř",
            "checkin_pain_high": "Vysoká bolest v check-inu", "limit_exceeded": "Překročené omezení tréninku",
            "adherence_drop": "Program se plní pod 50 %", "load_spike": "Skok v zátěži",
            "no_data_7d": "Bez dat", "note_unsigned": "Nepodepsaný záznam", "programme_ended": "Program skončil",
            "no_morning_data": "Návrat k běhu: chybí ranní odpověď"}


def alert_title(rule: str, payload: dict | None) -> str:
    """Round 2 F4.4 / F7.5: the title carries the real number — "Bez dat 54 dní", "Program splněn na 38 %"."""
    p = payload or {}
    if rule == "no_data_7d":
        if p.get("days") is not None:
            return f"Bez dat {p['days']} dní"
        return "Bez dat" if not p.get("last") else f"Bez dat od {int(p['last'][8:10])}. {int(p['last'][5:7])}."
    if rule == "adherence_drop" and p.get("pct") is not None:
        return f"Program splněn na {round(p['pct'])} %" + (" (odhad)" if p.get("method") == "total_estimate" else "")
    return ALERT_CS.get(rule, rule)


def _clients(db: DBSession, physio_id: str) -> list[str]:
    return [c.runner_id for c in db.query(models.CareAssignment).filter_by(physio_id=physio_id, status="active").all()]


def _rule_hits(db: DBSession, physio_id: str, rid: str) -> dict[str, dict]:
    from . import care_view as CV
    hits: dict[str, dict] = {}
    plan = (db.query(models.ReturnToRun).filter(models.ReturnToRun.runner_id == rid, models.ReturnToRun.physio_id == physio_id,
                                                models.ReturnToRun.status.in_(("active", "paused"))).first())
    if plan is not None:
        if plan.paused_reason == "pain_over_limit":
            hits["rtr_paused_pain"] = {"plan_id": plan.id}
        worse = rtr_morning_worse(db, plan)
        if worse:
            hits["rtr_morning_worse"] = worse
        late = db.query(models.RtrSession).filter_by(plan_id=plan.id, state="no_morning_data").first()
        if late:
            hits["no_morning_data"] = {"session_id": late.id}
    cis = (db.query(models.Checkin).filter(models.Checkin.runner_id == rid,
                                           models.Checkin.submitted_at >= (E.today_date() - timedelta(days=8)).isoformat())
           .order_by(models.Checkin.submitted_at).all())
    if cis and cis[-1].pain_score is not None and cis[-1].submitted_at[:10] >= (E.today_date() - timedelta(days=1)).isoformat():
        last = cis[-1].pain_score
        prev = [c.pain_score or 0 for c in cis[:-1]]
        avg = sum(prev) / len(prev) if prev else 0
        if last >= CHECKIN_PAIN_HIGH or (prev and last - avg >= CHECKIN_PAIN_RISE):
            hits["checkin_pain_high"] = {"pain": last, "avg7": round(avg, 1), "site": cis[-1].pain_site}
    br = limit_breaches(db, rid)
    if br:
        hits["limit_exceeded"] = br[0]
    prog = (db.query(models.Program).filter_by(runner_id=rid, physio_id=physio_id, active=True, status="sent")
            .order_by(models.Program.id.desc()).first())
    if prog is not None:
        from .routers.programs import ends_on
        end = ends_on(prog, db)
        if end and end < E.iso_date(E.today_date()):
            hits["programme_ended"] = {"program_id": prog.id, "ended": end}
        else:
            sent = (prog.sent_at or "")[:10]
            if sent and sent <= (E.today_date() - timedelta(days=7)).isoformat():
                adh = program_adherence(db, prog)          # round 2 F7.5: the same number as everywhere
                if adh["pct"] is not None and adh["pct"] < ADHERENCE_LOW:
                    hits["adherence_drop"] = {"program_id": prog.id, "pct": adh["pct"], "method": adh["method"]}
    a = E.get_or_refresh_assessment(db, rid) or {}
    if any(s.get("id") in SPIKE_SIGNALS for s in a.get("signals") or []):
        hits["load_spike"] = {}
    fr = CV.freshness_for(db, rid)
    if fr["status"] == "none" or (fr["days_since"] or 0) >= NO_DATA_DAYS:
        # round 2 F4.4: the real N, and the severity from the freshness thresholds (stale is high)
        hits["no_data_7d"] = {"last": fr["last_data_at"], "days": fr["days_since"],
                              "severity": "high" if fr["status"] in ("stale", "none") else "medium"}
    return hits


def refresh_alerts(db: DBSession, physio_id: str) -> None:
    """Generate one active alert per rule and client; resolve the ones whose condition went away."""
    from .routers.records import unsigned_for
    now = E.now_iso()
    current: dict[tuple[str, str | None], dict] = {}
    for rid in _clients(db, physio_id):
        for rule, payload in _rule_hits(db, physio_id, rid).items():
            current[(rule, rid)] = payload
    for u in unsigned_for(db, physio_id):
        current[("note_unsigned", u["runner_id"])] = {"booking_id": u["booking_id"], "overdue": u["overdue"]}
    existing = {(x.rule, x.runner_id): x for x in db.query(models.PhysioAlert).filter(
        models.PhysioAlert.physio_id == physio_id, models.PhysioAlert.status.in_(("active", "snoozed"))).all()}
    for key, payload in current.items():
        x = existing.get(key)
        if x is None:
            db.add(models.PhysioAlert(physio_id=physio_id, runner_id=key[1], rule=key[0],
                                      severity=payload.get("severity") or SEVERITY[key[0]],
                                      payload_json=payload, created_at=now, status="active"))
        else:
            x.payload_json = payload
            x.severity = payload.get("severity") or x.severity
            if x.status == "snoozed" and x.snoozed_until and x.snoozed_until <= now:
                x.status = "active"
    for key, x in existing.items():
        if key not in current:
            x.status, x.resolved_at = "resolved", now
    db.flush()


# ---- W11 return to run: morning answers ------------------------------------------------------------------
MORNING_WINDOW_H = 36          # product assumption: no answer within 36 h → not counted


def rtr_morning_worse(db: DBSession, plan: models.ReturnToRun) -> dict | None:
    """W11.7: morning pain or stiffness rising two weeks in a row."""
    rows = db.query(models.RtrSession).filter(models.RtrSession.plan_id == plan.id,
                                              models.RtrSession.next_morning_pain.isnot(None)).all()
    if not rows:
        return None
    today = E.today_date()
    wk = []
    for k in (2, 1, 0):
        lo, hi = today - timedelta(days=7 * (k + 1)), today - timedelta(days=7 * k)
        vals = [r.next_morning_pain for r in rows if lo.isoformat() < (r.logged_at or "")[:10] <= hi.isoformat()]
        wk.append(sum(vals) / len(vals) if vals else None)
    if None not in wk and wk[0] < wk[1] < wk[2]:
        return {"weeks": [round(x, 1) for x in wk]}
    last = rows[-1]
    if last.next_morning_pain is not None and last.next_morning_pain > plan.pain_threshold:
        return {"morning": last.next_morning_pain}
    return None


MORNING_FROM_HOUR = 6          # round 2 F5.5: the morning question opens at 06:00 the next local day


def morning_from(logged_at: str) -> datetime:
    """When the next-morning question opens for a session: 06:00 local on the day after it."""
    at = datetime.fromisoformat(logged_at)
    if at.tzinfo is None:
        at = at.replace(tzinfo=E.LOCAL_TZ)
    loc = at.astimezone(E.LOCAL_TZ)
    return datetime.combine(loc.date() + timedelta(days=1), time(MORNING_FROM_HOUR), E.LOCAL_TZ)


def expire_morning(db: DBSession, plan: models.ReturnToRun) -> None:
    cutoff = datetime.fromisoformat(E.now_iso()) - timedelta(hours=MORNING_WINDOW_H)
    for s in db.query(models.RtrSession).filter_by(plan_id=plan.id, state="pending").all():
        try:
            at = datetime.fromisoformat(s.logged_at)
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=cutoff.tzinfo)
        if at < cutoff:
            s.state, s.counted, s.count_reason = "no_morning_data", False, "no_morning_data"


def match_activity(db: DBSession, plan: models.ReturnToRun, level: dict | None, on: str) -> dict | None:
    """W11.6: a watch run on the same day within ±30 % of the planned duration; a run clearly longer is flagged."""
    if not level:
        return None
    planned_s = ((level.get("run_s") or 0) + (level.get("walk_s") or 0)) * (level.get("reps") or 1)
    if not planned_s:
        return None
    runs = [a for a in db.query(models.Activity).filter(models.Activity.runner_id == plan.runner_id).all()
            if (a.started_at or "")[:10] == on[:10] and (a.sport or "running") == "running"]
    for a in runs:
        dur = (a.duration_min or 0) * 60
        if dur and abs(dur - planned_s) <= 0.3 * planned_s:
            return {"activity_id": a.id, "minutes": a.duration_min, "over": False}
    for a in runs:
        if (a.duration_min or 0) * 60 > 1.3 * planned_s:
            return {"activity_id": a.id, "minutes": a.duration_min, "over": True}
    return None



# ---- R8.4 unsigned-record reminders at 17:00 and 21:00 local time ---------------------------------------
UNSIGNED_HOURS = (17, 21)


def unsigned_reminders(db: DBSession, physio_id: str) -> int:
    from .routers.records import unsigned_for
    now = datetime.fromisoformat(E.now_iso()).astimezone(E.LOCAL_TZ)
    today = now.date().isoformat()
    due = [h for h in UNSIGNED_HOURS if now.hour >= h]
    if not due:
        return 0
    ref = f"unsigned:{today}:{due[-1]}"
    if db.query(models.Notification.id).filter_by(physio_id=physio_id, ref=ref).first():
        return 0
    todays = [u for u in unsigned_for(db, physio_id) if (u["slot_at"] or "")[:10] <= today]
    if not todays:
        return 0
    NOTIFY.send(db, "note_unsigned", f"Nepodepsané záznamy: {len(todays)}", physio_id=physio_id, ref=ref)
    return 1
