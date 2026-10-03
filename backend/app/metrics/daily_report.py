"""Morning and evening report (owner request 2026-10-03, form A: full-screen story
cards with a way into the assistant on each).

Everything here is deterministic — the numbers come from the stored day rows, the
watch's night / day detail (models.DailyDetail), the assessment (readiness, capacity,
today's guidance) and the activities; the summary sentences are rule-based. The
assistant only answers the follow-up questions.

Morning (after the night is synced): the night (hypnogram, stages against the
runner's 4-week norm, sleep debt), recovery (readiness, HRV, resting HR, Body
Battery), what is left of the last days' load, and today's plan.
Evening: the day in numbers (steps, stress and Body Battery curves), today against
the plan, the week, the rest of the week laid out by the runner's usual pattern, and
tonight's sleep target.

Sleep guidance follows Walsh et al. (2021, BJSM consensus: athletes 7–9 h, more under
heavy training) and Drake et al. (2013: caffeine even 6 h before bed disturbs sleep).
The rest-of-week split, the bedtime arithmetic and the wording are working assumptions."""
from datetime import date, timedelta

from .. import models
from . import engine as E

WD = ["po", "út", "st", "čt", "pá", "so", "ne"]
WD_LONG = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
NORM_DAYS = 28
SLEEP_MIN_H, SLEEP_MAX_H = 7.0, 9.5
FALL_ASLEEP_MIN = 15
CAFFEINE_H = 6
LONG_SHARE = 0.35                  # the long run's share of the rest of the week (working assumption)


def _avg(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _r(v, d=1):
    return None if v is None else round(v, d)


def _cz(v, d=1) -> str:
    """A number the Czech way: 12,5 / 9 800."""
    txt = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    return txt[:-2] if d and txt.endswith(",0") else txt


def _dur(hours: float) -> str:
    m = int(round(hours * 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _hm(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    m = int(round(minutes)) % 1440
    return f"{m // 60}:{m % 60:02d}"


def _min_of(hhmm: str | None) -> int | None:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
        return h * 60 + m
    except (AttributeError, ValueError):
        return None


def _greeting(kind: str, name: str | None) -> str:
    first = (name or "").split(" ")[0]
    return (("Dobré ráno" if kind == "morning" else "Dobrý večer") + (f", {first}" if first else "")) + "."


def _rows(db, rid, today):
    since = (today - timedelta(days=NORM_DAYS + 1)).isoformat()
    dm = {r.date: r for r in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                                 models.DailyMetric.date >= since).all()}
    det = {r.date: r for r in db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid,
                                                                  models.DailyDetail.date >= since).all()}
    return dm, det


def _activities(db, rid, d0: date, d1: date):
    """Counted activities from d0 to d1 (inclusive), oldest first, with their ratings."""
    acts = [a for a in db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                                       models.Activity.started_at >= d0.isoformat(),
                                                       models.Activity.started_at < (d1 + timedelta(days=1)).isoformat()).all()
            if E.counts_for(a, "all")]
    fb = {f.activity_id: f for f in db.query(models.ActivityFeedback).filter(
        models.ActivityFeedback.activity_id.in_([a.id for a in acts] or [-1])).all()}
    out = []
    for a in sorted(acts, key=lambda x: x.started_at):
        f = fb.get(a.id)
        out.append({"id": a.id, "date": a.started_at[:10], "time": a.started_at[11:16] or None,
                    "title": a.title or ("Běh" if (a.sport or "running") == "running" else a.sport),
                    "sport": a.sport or "running", "run": (a.sport or "running") == "running",
                    "km": _r(a.distance_km), "min": _r(a.duration_min, 0), "ascent": _r(a.ascent_m, 0),
                    "hr": _r(a.avg_hr, 0), "rpe": (f.rpe if f else None) or a.rpe, "load": _r(a.training_load, 0)})
    return out


def _sleep_norm(dm, today):
    """The runner's 4-week sleep: hours, stages (min) and efficiency, from the day rows."""
    rows = [dm[d] for d in dm if d < today.isoformat()]
    if not rows:
        return {}
    return {"h": _r(_avg([r.sleep_h for r in rows])), "deep": _r(_avg([r.deep_min for r in rows]), 0),
            "rem": _r(_avg([r.rem_min for r in rows]), 0), "light": _r(_avg([r.light_min for r in rows]), 0),
            "awake": _r(_avg([r.awake_min for r in rows]), 0), "eff": _r(_avg([r.sleep_efficiency for r in rows]), 3),
            "n": len(rows)}


def _night(dm, det, today, norm):
    t = today.isoformat()
    row, d = dm.get(t), det.get(t)
    sl = (d.sleep if d else None) or {}
    h = row.sleep_h if row and row.sleep_h is not None else (_r(sl["sleepMin"] / 60) if sl.get("sleepMin") else None)
    if h is None and not sl:
        return None
    stages = sl.get("stages") or ({k: _r(getattr(row, f"{k}_min"), 0) for k in ("deep", "rem", "light", "awake")} if row else {})
    # sleep debt: the last 3 nights below the runner's own norm (never below 7 h)
    need = max(SLEEP_MIN_H, norm.get("h") or SLEEP_MIN_H)
    last3 = [dm[(today - timedelta(days=k)).isoformat()].sleep_h for k in range(3)
             if (today - timedelta(days=k)).isoformat() in dm and dm[(today - timedelta(days=k)).isoformat()].sleep_h is not None]
    debt = _r(sum(max(0.0, need - x) for x in last3)) if last3 else None
    out = {"hours": h, "start": sl.get("start"), "end": sl.get("end"), "inBedMin": sl.get("inBedMin"),
           "stages": stages, "norm": norm, "eff": _r(row.sleep_efficiency, 3) if row and row.sleep_efficiency is not None else None,
           "score": sl.get("score"), "scoreWord": sl.get("scoreWord"), "awakeCount": sl.get("awakeCount"),
           "respiration": sl.get("respiration"), "sleepStress": sl.get("sleepStress"),
           "hypnogram": sl.get("hypnogram"), "hrv": sl.get("hrv"), "bbChange": sl.get("bbChange"),
           "debt": debt, "need": _r(need), "nights": [{"d": (today - timedelta(days=k)).isoformat(),
                                                      "h": _r(dm[(today - timedelta(days=k)).isoformat()].sleep_h)
                                                      if (today - timedelta(days=k)).isoformat() in dm else None} for k in range(6, -1, -1)]}
    return out


def _night_text(n) -> str:
    if not n:
        return "Noc z hodinek zatím nedorazila. Po synchronizaci se report doplní."
    norm = (n.get("norm") or {}).get("h")
    parts = []
    if n["hours"] is not None and norm:
        dlt = n["hours"] - norm
        parts.append(f"Spali jste {_dur(n['hours'])}, "
                     + ("zhruba jako obvykle" if abs(dlt) < 0.35 else f"o {_dur(abs(dlt))} {'víc' if dlt > 0 else 'méně'} než obvykle")
                     + ".")
    elif n["hours"] is not None:
        parts.append(f"Spali jste {_dur(n['hours'])}.")
    st, nm = n.get("stages") or {}, n.get("norm") or {}
    deep_rem, deep_rem_n = (st.get("deep") or 0) + (st.get("rem") or 0), (nm.get("deep") or 0) + (nm.get("rem") or 0)
    if deep_rem and deep_rem_n:
        r = deep_rem / deep_rem_n
        parts.append("Hlubokého a REM spánku bylo " + ("víc než obvykle." if r > 1.1 else "méně než obvykle." if r < 0.9 else "jako obvykle."))
    if n.get("debt") and n["debt"] >= 1:
        parts.append(f"Za poslední 3 noci vám chybí asi {_dur(n['debt'])} spánku.")
    return " ".join(parts) or "Noc je zapsaná."


def _recovery(a, det, today):
    cap = (a or {}).get("capacity") or {}
    r = cap.get("readiness") or {}
    inp = r.get("inputs") or {}
    day = ((det.get(today.isoformat()).day if det.get(today.isoformat()) else None) or {})
    # the morning report shows the morning's readiness (before today's training lowered it)
    score = r.get("morningScore") if r.get("morningScore") is not None else r.get("score")
    from . import capacity as CAP
    return {"score": score, "label": CAP.readiness_label(score), "now": r.get("score"),
            "yesterday": (r.get("yesterday") or {}).get("score"),
            "known": r.get("known"), "night": inp.get("night"), "base": inp.get("base"), "range": inp.get("range"),
            "bbWake": day.get("bbWake") if day.get("bbWake") is not None else ((day.get("bb") or [[0, None]])[0][1]),
            "bbHigh": day.get("bbHigh") if day else None, "readiness": r}


def _carry(a):
    """What the last days left unabsorbed, per channel (the Zátěž residual vs capacity)."""
    ch = ((a or {}).get("capacity") or {}).get("channels") or {}
    out = []
    for c in ("systemic", "volume", "intensity", "descent"):
        w = (ch.get(c) or {}).get("week") or {}
        if w.get("residual") is not None and w.get("cap"):
            out.append({"ch": c, "label": (ch.get(c) or {}).get("label"), "unit": (ch.get(c) or {}).get("unit"),
                        "residual": w["residual"], "cap": w["cap"], "share": round(w["residual"] / w["cap"], 2)})
    return out


def _plan(a, db, rid):
    g = (a or {}).get("guidance") or {}
    t = (g.get("types") or {}).get(g.get("type")) or {}
    out = {"type": g.get("type"), "label": g.get("typeLabel"), "km": t.get("km"), "hr": t.get("hr"),
           "pace": t.get("pace"), "duration": t.get("durationMin"), "z4": t.get("z4Target"),
           "terrain": t.get("terrain"), "notes": (t.get("notes") or [])[:3], "reasons": (g.get("reasons") or [])[:3],
           "override": (g.get("override") or {}).get("title"), "afterDone": g.get("afterDone"),
           "strength": None, "readinessScore": g.get("readinessScore")}
    progs = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid, models.SelfProgram.active.is_(True)).all()
    prog = next((x for x in progs if x.template == "durability"), progs[0] if progs else None)
    if prog is not None and prog.template == "durability":
        from .. import durability as DU
        pick = DU.choose(db, rid, a, prog.state or {}, E.today_date())
        out["strength"] = {"session": DU.SESSIONS[pick["session"]]["label"], "blocked": pick["blocked"], "why": pick["why"],
                           "name": prog.name}
    elif prog is not None:
        out["strength"] = {"session": None, "blocked": None, "why": None, "name": prog.name}
    return out


def _week(a, db, rid, today):
    g = (a or {}).get("guidance") or {}
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    ws = today - timedelta(days=today.weekday())
    acts = _activities(db, rid, ws, ws + timedelta(days=6))
    days = []
    for k in range(7):
        d = ws + timedelta(days=k)
        km = sum(x["km"] or 0 for x in acts if x["date"] == d.isoformat() and x["run"])
        other = [x["sport"] for x in acts if x["date"] == d.isoformat() and not x["run"]]
        days.append({"date": d.isoformat(), "wd": WD[k], "km": _r(km), "other": other, "today": d == today, "past": d < today})
    return {"days": days, "budget": vol.get("budget"), "done": vol.get("done"), "left": vol.get("left"),
            "ceiling7": vol.get("ceiling7"), "done7": vol.get("done7"), "mode": (g.get("week") or {}).get("mode"),
            "cycle": ((g.get("week") or {}).get("cycle") or {}).get("pos")}


def _rest_of_week(a, today, week):
    """The week's remaining kilometres over the remaining days by the runner's pattern:
    the usual long-run day gets ~35 % (never above the single-run ceiling), the other
    usual run days share the rest, the other days are rest days."""
    g = (a or {}).get("guidance") or {}
    pat = g.get("pattern") or {}
    left = week.get("left")
    run_days = set(pat.get("runDays") or [])
    long_day = pat.get("longDay")
    hard = set(pat.get("hardDays") or [])
    ceil_run = ((((a or {}).get("capacity") or {}).get("channels") or {}).get("volume") or {}).get("ceilingSession")
    rest = [today + timedelta(days=k) for k in range(1, 7 - today.weekday())]
    if not rest:
        return {"days": [], "left": left, "note": "Týden končí, zítra začíná nový."}
    if left is None:
        return {"days": [], "left": None, "note": "Týdenní cíl se zatím neurčil."}
    if left <= 0.5:
        return {"days": [{"date": d.isoformat(), "wd": WD[d.weekday()], "type": "lehce / volno", "km": None} for d in rest],
                "left": left, "note": "Týdenní cíl máte splněný. Zbytek týdne lehce, nebo volno."}
    runs = [d for d in rest if d.weekday() in run_days] or rest[: max(1, min(len(rest), round(len(run_days) * len(rest) / 7) or 1))]
    out, km_left = {}, left
    long_d = next((d for d in runs if d.weekday() == long_day), None)
    if long_d and len(runs) > 1:
        lk = min(LONG_SHARE * left if len(runs) > 2 else left / 2, ceil_run or 1e9)
        out[long_d] = ("dlouhý", lk)
        km_left -= lk
    others = [d for d in runs if d not in out]
    for d in others:
        out[d] = ("kvalitní" if d.weekday() in hard else "lehký", km_left / len(others))
    days = []
    for d in rest:
        typ, km = out.get(d, ("volno", None))
        if km is not None and ceil_run:
            km = min(km, ceil_run)
        days.append({"date": d.isoformat(), "wd": WD[d.weekday()], "type": typ, "km": _r(km)})
    planned = sum(d["km"] or 0 for d in days)
    note = (f"Zbylých {_cz(left - planned)} km se do týdne nevejde bez překročení stropu jednoho běhu. "
            "Cíl je horní hranice, ne povinnost." if left - planned > 2 else None)
    return {"days": days, "left": _r(left), "note": note}


def _day(dm, det, today, acts_today):
    t = today.isoformat()
    row, d = dm.get(t), det.get(t)
    day = (d.day if d else None) or {}
    steps = day.get("steps") or (row.steps if row else None)
    steps_norm = _avg([dm[x].steps for x in dm if x < t and dm[x].steps])
    return {"steps": steps, "stepsNorm": _r(steps_norm, 0), "stepGoal": day.get("stepGoal"),
            "stressAvg": day.get("stressAvg") or (row.stress_avg if row else None),
            "stressNorm": _r(_avg([dm[x].stress_avg for x in dm if x < t]), 0),
            "stress": day.get("stress"), "stressMin": day.get("stressMin"), "bb": day.get("bb"),
            "bbHigh": day.get("bbHigh"), "bbLow": day.get("bbLow"), "bbNow": day.get("bbNow"),
            "bbCharged": day.get("bbCharged"), "bbDrained": day.get("bbDrained"), "activities": acts_today}


def _tonight(a, det, dm, today, norm, week_next_hard: bool, debt):
    """Tonight's sleep target and when to go to bed for it: the runner's norm (7–9.5 h),
    +30 min before a hard or long day, + up to 1 h back of a sleep debt (Walsh et al., 2021)."""
    base = max(SLEEP_MIN_H, norm.get("h") or 7.5)
    target = base + (0.5 if week_next_hard else 0) + min(1.0, (debt or 0) / 2)
    target = min(SLEEP_MAX_H, round(target * 4) / 4)
    wakes = [_min_of(((det[x].sleep or {}).get("end"))) for x in det if x <= today.isoformat() and det[x].sleep]
    wakes = sorted(w for w in wakes if w is not None)
    wake = wakes[len(wakes) // 2] if wakes else 6 * 60 + 30
    bed = wake - target * 60 - FALL_ASLEEP_MIN
    return {"target": target, "wake": _hm(wake), "bed": _hm(bed), "caffeine": _hm(bed - CAFFEINE_H * 60),
            "base": _r(base), "hardTomorrow": week_next_hard, "debt": debt, "wakeFromWatch": bool(wakes)}


def _summary_morning(night, rec, plan) -> str:
    """Three or four sentences from the facts below (no model)."""
    s = []
    if rec.get("score") is not None:
        s.append(f"Připravenost {rec['score']} %" + (f" ({rec['label'].lower()})" if rec.get("label") else "") + ".")
    if night and night.get("hours") is not None:
        s.append(_night_text(night).split(".")[0] + ".")
    if plan.get("override"):
        s.append(plan["override"] + ".")
    elif plan.get("label"):
        km = plan.get("km") or {}
        rng = f" {_cz(km['lo'])}–{_cz(km['hi'])} km" if isinstance(km, dict) and km.get("lo") is not None and km.get("hi") is not None and km["hi"] > 0 else ""
        s.append(f"Na dnešek: {plan['label'].lower()}{rng}.")
    if plan.get("strength") and plan["strength"].get("session") and not plan["strength"].get("blocked"):
        s.append(f"Posilování: {plan['strength']['session']}.")
    return " ".join(s)


def _summary_evening(day, week, tonight) -> str:
    s = []
    if day.get("steps"):
        s.append(f"Dnes {_cz(day['steps'], 0)} kroků" + (f" (obvykle {_cz(day['stepsNorm'], 0)})" if day.get("stepsNorm") else "") + ".")
    if week.get("budget"):
        left = week.get("left") or 0
        s.append(f"Týden: {_cz(week.get('done') or 0)} z {_cz(week['budget'], 0)} km" + (f", zbývá {_cz(left)} km." if left > 0.5 else ", cíl splněný."))
    s.append(f"Na noc {_dur(tonight['target'])} spánku, do postele kolem {tonight['bed']}.")
    return " ".join(s)


MORNING_Q = ["Proč mám dnes takové doporučení?", "Jak se vyspat lépe, když mi chybí hluboký spánek?", "Můžu dnes přidat posilování?"]
EVENING_Q = ["Jak rozložit zbytek týdne?", "Proč mám dnes vysoký stres?", "Co dělat, abych zítra byl odpočatý?"]


def build(db, rid: str, kind: str) -> dict:
    today = E.today_date()
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    a = E.get_or_refresh_assessment(db, rid)
    dm, det = _rows(db, rid, today)
    norm = _sleep_norm(dm, today)
    base = {"kind": kind, "date": today.isoformat(), "weekday": WD_LONG[today.weekday()],
            "greeting": _greeting(kind, getattr(runner, "name", None)), "generatedAt": E.now_iso(),
            "hasDetail": today.isoformat() in det}
    if kind == "morning":
        night = _night(dm, det, today, norm)
        rec = _recovery(a, det, today)
        y = today - timedelta(days=1)
        plan = _plan(a, db, rid)
        return {**base, "night": night, "nightText": _night_text(night), "recovery": rec,
                "yesterday": {"date": y.isoformat(), "activities": _activities(db, rid, y, y), "carry": _carry(a),
                              "axes": ((a or {}).get("guidance") or {}).get("axes")},
                "plan": plan, "summary": _summary_morning(night, rec, plan), "questions": MORNING_Q}
    acts = _activities(db, rid, today, today)
    day = _day(dm, det, today, acts)
    week = _week(a, db, rid, today)
    rest = _rest_of_week(a, today, week)
    g = (a or {}).get("guidance") or {}
    tomorrow = (today + timedelta(days=1)).weekday()
    pat = g.get("pattern") or {}
    nxt = next((d for d in rest.get("days") or [] if d["date"] == (today + timedelta(days=1)).isoformat()), None)
    hard_tomorrow = bool(nxt and nxt["type"] in ("dlouhý", "kvalitní")) or tomorrow in (pat.get("hardDays") or [])
    night = _night(dm, det, today, norm)
    tonight = _tonight(a, det, dm, today, norm, hard_tomorrow, (night or {}).get("debt"))
    vol = ((g.get("week") or {}).get("channels") or {})
    vs = {"type": g.get("type"), "label": g.get("typeLabel"), "afterDone": g.get("afterDone"),
          "channels": [{"ch": c, "label": (vol.get(c) or {}).get("label"), "unit": (vol.get(c) or {}).get("unit"),
                        "doneToday": (vol.get(c) or {}).get("doneToday"), "limit": (vol.get(c) or {}).get("ceilingRun"),
                        "left": (vol.get(c) or {}).get("todayMax")}
                       for c in ("volume", "intensity", "descent", "systemic") if vol.get(c)]}
    return {**base, "day": day, "vsPlan": vs, "week": week, "restOfWeek": rest, "tonight": tonight,
            "summary": _summary_evening(day, week, tonight), "questions": EVENING_Q}
