"""Morning and evening report (owner request 2026-10-03, form A: full-screen story
cards with a way into the assistant on each; v2 the same day: every card carries a
few sentences that rate it and give a tip — model-written and validated, else the
rule-based ones below — the evening follows the day from morning to night and what
it means for tomorrow, the morning analyses the night and how it set up today).

Only own metrics, computed from raw data every device gives (dayload.py): no vendor
stress, Body Battery or sleep score (those stay in the stored detail for the owners'
comparison only).

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
from . import dayload as DL
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
        out.append({"id": a.id, "date": a.started_at[:10], "time": a.start_time or a.started_at[11:16] or None,
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
        parts.append("Hlubokého a REM spánku bylo víc než obvykle." if r > 1.1 else "Hlubokého a REM spánku bylo méně než obvykle." if r < 0.9 else "Hlubokého a REM spánku bylo jako obvykle.")
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



# ------------------------------------------------------------------ v2 pieces
def _sleep_scores(dm, det, today, norm):
    """Own sleep score for the last 7 nights (oldest first)."""
    beds = [_min_of(((det[x].sleep or {}).get("start"))) for x in det if det[x].sleep]
    beds = sorted((b if b >= 12 * 60 else b + 1440) for b in beds if b is not None)
    med = beds[len(beds) // 2] if beds else None
    out = []
    for k in range(6, -1, -1):
        d = (today - timedelta(days=k)).isoformat()
        row, dd = dm.get(d), det.get(d)
        sl = (dd.sleep if dd else None) or {}
        b = _min_of(sl.get("start"))
        dev = None if (b is None or med is None) else abs((b if b >= 12 * 60 else b + 1440) - med)
        hours = row.sleep_h if row and row.sleep_h is not None else (_r(sl["sleepMin"] / 60) if sl.get("sleepMin") else None)
        stages = sl.get("stages") or ({x: getattr(row, f"{x}_min") for x in ("deep", "rem", "light")} if row else None)
        sc = DL.sleep_score(hours, row.sleep_efficiency if row else None, stages, norm, dev, sl.get("awakeCount"))
        out.append({"d": d, "h": _r(hours), "score": sc["score"] if sc else None, "parts": sc["parts"] if sc else None,
                    "bedDev": None if dev is None else round(dev)})
    return out


def _energy_k(db, rid, today) -> float:
    """Energy points per load unit: the runner's median day (training + outside) drains ENERGY_DAY_DRAIN."""
    tot = []
    for k in range(1, 8):
        res = DL.day_result(db, rid, (today - timedelta(days=k)).isoformat())
        if res:
            tot.append(res["trainLoad"] + res["ntLoad"])
    tot = sorted(t for t in tot if t > 0)
    # the runner's busier days (75th percentile) drain ENERGY_DAY_DRAIN, so one run isn't the whole tank
    ref = tot[min(len(tot) - 1, int(0.75 * len(tot)))] if tot else 150.0
    return DL.ENERGY_DAY_DRAIN / max(60.0, ref)


def _day_view(db, rid, d: date, start_energy: float | None, k: float, until: float | None = None) -> dict | None:
    """One day from morning to night: the 15-minute timeline (state, HR, load), the
    energy curve from the morning's readiness, the activities and the totals."""
    res = DL.day_result(db, rid, d.isoformat())
    if res is None:
        return None
    curve = DL.energy_curve(res["timeline"], start_energy if start_energy is not None else 80, k, res["wake"], until) if start_energy is not None else None
    acts = _activities(db, rid, d, d)
    raw_row = db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid, models.DailyDetail.date == d.isoformat()).first()
    for a in acts:
        t0 = _min_of(a.get("time"))
        if t0 is not None and a.get("min"):
            a["from"], a["to"] = t0, round(t0 + a["min"])
    hourly = {}
    for m, n in ((raw_row.raw or {}).get("steps") or []) if raw_row else []:
        hourly[m // 60] = hourly.get(m // 60, 0) + n
    return {**{k2: v for k2, v in res.items() if k2 != "timeline"}, "timeline": res["timeline"], "energy": curve,
            "activities": acts, "stepsHourly": [[h, n] for h, n in sorted(hourly.items())]}


def _usual(dm, today, field, days=28):
    vals = sorted(getattr(dm[x], field) for x in dm if x < today.isoformat() and getattr(dm[x], field, None) is not None)
    return vals[len(vals) // 2] if len(vals) >= 5 else None


def _week_loads(a, db, rid, today):
    """Mon … Sun: the all-sport load per day (training vs the day outside it, as Zátěž
    counts it) and the run kilometres."""
    ch = (((a or {}).get("capacity") or {}).get("channels") or {}).get("systemic") or {}
    w7 = ch.get("week7") or []
    ws = today - timedelta(days=today.weekday())
    acts = _activities(db, rid, ws, ws + timedelta(days=6))
    out = []
    for k in range(7):
        d = (ws + timedelta(days=k)).isoformat()
        tr = sum(x["value"] or 0 for x in w7 if x["date"] == d and x.get("sport") != "daily")
        nt = sum(x["value"] or 0 for x in w7 if x["date"] == d and x.get("sport") == "daily")
        out.append({"date": d, "wd": WD[k], "train": _r(tr, 0), "nt": _r(nt, 0),
                    "km": _r(sum(x["km"] or 0 for x in acts if x["date"] == d and x["run"])),
                    "sessions": [x["title"] for x in acts if x["date"] == d], "today": d == today.isoformat(), "past": d < today.isoformat()})
    return out


def _watchouts(a, rec, night, plan):
    """What to watch today, most important first: [{level: alert|watch|info, text}]."""
    g = (a or {}).get("guidance") or {}
    out = []
    if (g.get("pain") or 0) >= 3:
        out.append({"level": "alert", "text": f"Bolest {g['pain']}/10: při běhu nanejvýš 5/10 a do rána musí odeznít, jinak uberte."})
    sc = rec.get("score")
    if sc is not None and sc < 45:
        out.append({"level": "alert", "text": "Připravenost pod 45 %: dnes jen regenerace, žádný náročný trénink."})
    elif sc is not None and sc < 65:
        out.append({"level": "watch", "text": "Připravenost pod 65 %: dnes bez tvrdých úseků a dlouhého běhu."})
    ax = g.get("axes") or {}
    th = ax.get("threshold") or 25
    if (ax.get("load") or 0) >= th:
        out.append({"level": "watch", "text": f"Zátěž {ax['load']} je nad prahem {th}: tento týden odlehčit."})
    if (ax.get("mech") or 0) >= th:
        out.append({"level": "watch", "text": f"Mechanika {ax['mech']} je nad prahem {th}: raději rovina, méně klesání."})
    if night and (night.get("debt") or 0) >= 1:
        out.append({"level": "watch", "text": f"Spánkový dluh {_dur(night['debt'])} za 3 noci: večer dřív do postele."})
    ds = ((rec.get("readiness") or {}).get("inputs") or {}).get("dayStress") or {}
    if ((rec.get("readiness") or {}).get("parts") or {}).get("dayStress"):
        out.append({"level": "info", "text": f"Včera {ds.get('yesterday')} min zvýšeného tepu v klidu (obvykle {ds.get('usual')}): tělo bylo pod tlakem i mimo trénink."})
    st = g.get("strength") or {}
    if st.get("lastAge") is not None and st["lastAge"] <= 1 and (plan.get("type") == "kvalitní"):
        out.append({"level": "info", "text": "Po včerejším posilování nohou může být intenzivní běh těžší než obvykle."})
    heat = g.get("heat")
    if heat and heat.get("feelsMax"):
        out.append({"level": "watch", "text": f"Horko až {round(heat['feelsMax'])} °C: pít, zpomalit, běžet ráno nebo večer."})
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    if vol.get("budget") and vol.get("left") is not None and vol["left"] < 0.2 * vol["budget"]:
        out.append({"level": "info", "text": f"Z týdenního cíle zbývá {_cz(vol['left'])} km z {_cz(vol['budget'], 0)}."})
    return out[:5]


def _tomorrow(a, today_view, dm, today, night, rest, tonight, hard_tomorrow):
    """What today means for tomorrow: [{dir: -1|0|1, text}] and tomorrow's plan."""
    out = []
    if today_view:
        tot = today_view["trainLoad"] + today_view["ntLoad"]
        usual = _usual(dm, today, "nt_load")
        if tot > 0:
            if today_view["trainLoad"] > 0 and tot > 1.3 * max(60.0, (usual or 0) + 80):
                out.append({"dir": -1, "text": "Náročný den: tělo bude v noci zpracovávat víc zátěže, zítřejší připravenost může být nižší."})
            elif today_view["trainLoad"] == 0 and (today_view["ntLoad"] <= (usual or today_view["ntLoad"]) * 1.2):
                out.append({"dir": 1, "text": "Klidnější den bez tréninku: dobrá příležitost k regeneraci."})
        if usual is not None and today_view["ntLoad"] > 1.5 * usual + 5:
            out.append({"dir": -1, "text": f"Mimo trénink jste se nachodili víc než obvykle ({_cz(today_view['activeMin'], 0)} min aktivního pohybu)."})
        raised = today_view["highMin"] + 0.5 * today_view["mildMin"]
        u_r = _usual(dm, today, "rest_high_min")
        if raised >= 30 and (u_r is None or raised > 1.5 * (u_r or 0) + 15):
            out.append({"dir": -1, "text": f"Dnes {today_view['highMin']} min výrazně zvýšeného tepu v klidu: zkuste večer zpomalit, projít se, dýchat zhluboka."})
    if night and (night.get("debt") or 0) >= 1:
        out.append({"dir": -1, "text": f"Spánkový dluh {_dur(night['debt'])}: dnešní noc rozhodne, jak zítra vstanete."})
    else:
        out.append({"dir": 1, "text": f"S {_dur(tonight['target'])} spánku by zítřejší připravenost měla držet."})
    nxt = next((d for d in rest.get("days") or [] if d["date"] == (today + timedelta(days=1)).isoformat()), None)
    plan_tmr = {"type": nxt["type"], "km": nxt["km"], "wd": nxt["wd"]} if nxt else None
    if plan_tmr:
        out.append({"dir": 0, "text": f"Zítra podle plánu týdne: {plan_tmr['type']}" + (f" ≈ {_cz(plan_tmr['km'])} km." if plan_tmr['km'] else ".")})
    return {"effects": out[:5], "plan": plan_tmr}


# ------------------------------------------------------------------ rule-based card notes (fallback for the AI)
def _notes_morning(r) -> dict:
    n, rec, sl = r["night"], r["recovery"], r["sleep"]
    notes = {}
    sc = (sl.get("scores") or [{}])[-1].get("score") if sl else None
    if n:
        txt = _night_text(n)
        tip = ("Držte čas usínání co nejpravidelněji, pomáhá to hlubokému spánku." if (n.get("debt") or 0) < 1
               else "Dnes večer jděte spát o půl hodiny dřív a hodinu před spaním vynechte obrazovky.")
        notes["sleep"] = f"{txt} {tip}".strip() if sc is None else f"Skóre spánku {sc} ze 100. {txt} {tip}"
    else:
        notes["sleep"] = "Noc z hodinek zatím nedorazila. Po synchronizaci se report doplní."
    s0, y0 = rec.get("score"), rec.get("yesterday")
    if s0 is not None:
        trend = "" if y0 is None else (" Proti včerejšku beze změny." if s0 == y0 else (f" Proti včerejšku o {abs(s0 - y0)} bodů víc." if s0 > y0 else f" Proti včerejšku o {abs(s0 - y0)} bodů méně."))
        tip = ("Tělo je zregenerované, dnešní trénink zvládne podle plánu." if s0 >= 80 else
               "Držte se dnešního doporučení a nepřidávejte navíc." if s0 >= 60 else
               "Dnes raději lehce, regenerace má přednost.")
        notes["readiness"] = f"Připravenost {s0} %.{trend} {tip}"
    y = r["recent"]
    wk_tr = sum(x["train"] or 0 for x in y["week"] if x["past"])
    notes["recent"] = ((f"Včera: {', '.join(x['title'] for x in y['yesterday']['activities'])}. " if y["yesterday"]["activities"] else "Včera bez tréninku. ")
                       + (f"Tento týden zatím {_cz(y['weekKm'])} km." if y.get("weekKm") else "")
                       + (" Zátěž z posledních dní se ještě vstřebává, dnešní limity to zohledňují." if any(c["share"] > 0.6 for c in y["carry"]) else " Tělo má prostor na dnešní trénink."))
    p = r["plan"]
    w = r["watch"]
    rest = p.get("type") in ("volno", "regenerace")
    notes["plan"] = (f"Dnes {p['label'].lower() if p.get('label') else 'podle doporučení'}. "
                     + (w[0]["text"] if w else ("Tělo dnes regeneruje: procházka, protažení a dost jídla i pití pomohou víc než trénink navíc."
                                                if rest else "Nic zvláštního k hlídání, běžte podle plánu a v klidném tempu.")))
    notes["intro"] = r["summary"]
    return notes


def _notes_evening(r) -> dict:
    notes = {"intro": r["summary"]}
    v = r["dayView"]
    if v:
        parts = [f"Den začal v {_hm(v['wake'])}."] if v.get("wake") else []
        if v["activities"]:
            parts.append(f"Trénink: {', '.join(x['title'] for x in v['activities'])}.")
        parts.append(f"Aktivního pohybu mimo trénink {v['activeMin']} min, zvýšeného tepu v klidu {v['highMin'] + v['mildMin']} min.")
        tip = ("Večer si dopřejte klid, ať se tep před spaním zklidní." if v["highMin"] >= 30 else
               "Den byl vyrovnaný, večer už jen lehce.")
        notes["day"] = " ".join(parts) + " " + tip
    else:
        notes["day"] = "Celodenní tep z hodinek zatím nedorazil. Po synchronizaci se průběh dne doplní."
    ld = r["load"]
    notes["load"] = (f"Celková zátěž dne {_cz(ld['total'], 0)} j.z., z toho mimo trénink {_cz(ld['nt'], 0)}. "
                     + ("Dnešní limity jsou vyčerpané, zbytek dne odpočívejte." if ld.get("left") is not None and ld["left"] <= 0 else
                        "Do dnešních limitů zbývá prostor, ale není nutné ho využít."))
    t = r["tomorrow"]
    bad = [e for e in t["effects"] if e["dir"] < 0]
    notes["tomorrow"] = (bad[0]["text"] if bad else "Nic dnes zítřek výrazně nezhorší.") + (
        f" Zítra: {t['plan']['type']}." if t.get("plan") else "")
    wk = r["week"]
    notes["week"] = (f"Tento týden {_cz(wk.get('done') or 0)} z {_cz(wk['budget'], 0)} km. " if wk.get("budget") else "") + (
        r["restOfWeek"].get("note") or "Zbytek týdne rozložte podle návrhu, každé ráno ho upřesní připravenost.")
    tn = r["tonight"]
    notes["tonight"] = f"Cíl {_dur(tn['target'])} spánku: do postele kolem {tn['bed']}, poslední káva do {tn['caffeine']}. Chladná a tmavá ložnice pomůže."
    return notes


MORNING_Q = ["Proč mám dnes takové doporučení?", "Jak se vyspat lépe, když mi chybí hluboký spánek?", "Na co si dnes dát pozor?"]
EVENING_Q = ["Jak rozložit zbytek týdne?", "Co nejvíc ovlivnilo můj dnešní den?", "Co dělat, abych zítra byl odpočatý?"]


def build(db, rid: str, kind: str) -> dict:
    today = E.today_date()
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    a = E.get_or_refresh_assessment(db, rid)
    dm, det = _rows(db, rid, today)
    norm = _sleep_norm(dm, today)
    rec = _recovery(a, det, today)
    k = _energy_k(db, rid, today)
    base = {"kind": kind, "date": today.isoformat(), "weekday": WD_LONG[today.weekday()],
            "greeting": _greeting(kind, getattr(runner, "name", None)), "generatedAt": E.now_iso(),
            "hasDetail": today.isoformat() in det}
    night = _night(dm, det, today, norm)
    if kind == "morning":
        y = today - timedelta(days=1)
        plan = _plan(a, db, rid)
        scores = _sleep_scores(dm, det, today, norm)
        week = _week(a, db, rid, today)
        ystart = rec.get("yesterday")
        r = {**base, "night": night, "nightText": _night_text(night), "recovery": rec,
             "sleep": {"scores": scores, "norm": norm},
             "recent": {"yesterday": {"date": y.isoformat(), "activities": _activities(db, rid, y, y),
                                      "view": _day_view(db, rid, y, ystart, k)},
                        "week": _week_loads(a, db, rid, today), "weekKm": week.get("done"), "budget": week.get("budget"),
                        "carry": _carry(a), "axes": ((a or {}).get("guidance") or {}).get("axes")},
             "plan": plan, "watch": [], "questions": MORNING_Q}
        r["watch"] = _watchouts(a, rec, night, plan)
        r["summary"] = _summary_morning(night, rec, plan)
        r["notes"] = _notes_morning(r)
        return r
    acts = _activities(db, rid, today, today)
    day = _day(dm, det, today, acts)
    week = _week(a, db, rid, today)
    rest = _rest_of_week(a, today, week)
    g = (a or {}).get("guidance") or {}
    tomorrow = (today + timedelta(days=1)).weekday()
    pat = g.get("pattern") or {}
    nxt = next((d for d in rest.get("days") or [] if d["date"] == (today + timedelta(days=1)).isoformat()), None)
    hard_tomorrow = bool(nxt and nxt["type"] in ("dlouhý", "kvalitní")) or tomorrow in (pat.get("hardDays") or [])
    tonight = _tonight(a, det, dm, today, norm, hard_tomorrow, (night or {}).get("debt"))
    now_min = None
    try:
        hh = E.now_iso()[11:16]
        now_min = int(hh[:2]) * 60 + int(hh[3:5])
    except (ValueError, TypeError):
        pass
    view = _day_view(db, rid, today, rec.get("score"), k, now_min)
    ch = (g.get("week") or {}).get("channels") or {}
    sysc = ch.get("systemic") or {}
    load = {"train": _r(view["trainLoad"], 0) if view else None, "nt": _r(view["ntLoad"], 0) if view else 0,
            "total": _r((view["trainLoad"] + view["ntLoad"]) if view else (sysc.get("doneToday") or 0), 0),
            "usualNt": _r(_usual(dm, today, "nt_load"), 0), "left": sysc.get("todayMax"), "budget": sysc.get("budget"),
            "weekDone": sysc.get("done"),
            "channels": [{"ch": c, "label": (ch.get(c) or {}).get("label"), "unit": (ch.get(c) or {}).get("unit"),
                          "doneToday": (ch.get(c) or {}).get("doneToday"), "left": (ch.get(c) or {}).get("todayMax"),
                          "budget": (ch.get(c) or {}).get("budget"), "done": (ch.get(c) or {}).get("done")}
                         for c in ("volume", "intensity", "descent", "systemic") if ch.get(c)],
            "plan": {"type": g.get("type"), "label": g.get("typeLabel"), "afterDone": g.get("afterDone")}}
    r = {**base, "day": day, "dayView": view, "load": load, "week": week, "weekLoads": _week_loads(a, db, rid, today),
         "restOfWeek": rest, "tonight": tonight, "recovery": rec, "questions": EVENING_Q}
    r["tomorrow"] = _tomorrow(a, view, dm, today, night, rest, tonight, hard_tomorrow)
    if view and view.get("energy"):
        r["energyNow"] = view["energy"][-1][1]
    r["summary"] = _summary_evening(view, load, week, tonight)
    r["notes"] = _notes_evening(r)
    return r


def day_today(db, rid: str) -> dict:
    """The day so far for the Trénink tab (owner request 2026-10-03): the evening report's
    day without the story — the timeline with the energy curve and the states, minutes per
    state, the day's load (training and outside it against the usual day, and the part
    above the usual day that Celková zátěž counts) and readiness from the morning to now
    (today's sessions, the day outside training, v0.10.4)."""
    today = E.today_date()
    a = E.get_or_refresh_assessment(db, rid)
    dm, det = _rows(db, rid, today)
    rec = _recovery(a, det, today)
    try:
        hh = E.now_iso()[11:16]
        now_min = int(hh[:2]) * 60 + int(hh[3:5])
    except (ValueError, TypeError):
        now_min = None
    view = _day_view(db, rid, today, rec.get("score"), _energy_k(db, rid, today), now_min)
    r = rec.get("readiness") or {}
    after = r.get("afterSession") or {}
    t = today.isoformat()
    w7 = ((((a or {}).get("capacity") or {}).get("channels") or {}).get("systemic") or {}).get("week7") or []
    excess = sum(x.get("value") or 0 for x in w7 if x.get("sport") == "daily" and x.get("date") == t)
    load = {"train": _r(view["trainLoad"], 0) if view else None, "nt": _r(view["ntLoad"], 0) if view else None,
            "usualNt": _r(_usual(dm, today, "nt_load"), 0), "excess": _r(excess, 0)}
    ses = after.get("today") or {}
    readiness = {"morning": rec.get("score"), "now": r.get("score"), "label": rec.get("label"),
                 "sessionDrop": after.get("sessionDrop") or 0, "dayDrop": after.get("dayDrop") or 0,
                 "carry": bool(after.get("carry") and not after.get("today")),
                 "sessions": [x.get("title") or x.get("sport") for x in ses.get("sessions") or []], "band": ses.get("band"),
                 "nt": after.get("nt"), "stress": after.get("stress")}
    return {"date": t, "nowMin": now_min, "view": view, "load": load, "readiness": readiness}


def _summary_morning(night, rec, plan) -> str:
    """Three or four sentences from the facts (no model)."""
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
    return " ".join(s)


def _summary_evening(view, load, week, tonight) -> str:
    s = []
    if view and view.get("energy"):
        s.append(f"Energie teď {view['energy'][-1][1]} ze 100.")
    if load.get("total"):
        s.append(f"Zátěž dne {_cz(load['total'], 0)} j.z." + (f", z toho mimo trénink {_cz(load['nt'], 0)}." if load.get("nt") else "."))
    if week.get("budget"):
        left = week.get("left") or 0
        s.append(f"Týden: {_cz(week.get('done') or 0)} z {_cz(week['budget'], 0)} km" + (f", zbývá {_cz(left)} km." if left > 0.5 else ", cíl splněný."))
    s.append(f"Na noc {_dur(tonight['target'])} spánku, do postele kolem {tonight['bed']}.")
    return " ".join(s)
