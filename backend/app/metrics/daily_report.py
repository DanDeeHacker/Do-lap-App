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
the plan, the week, the rest of the week from the week planner (week_plan.py), and
tonight's sleep target.

Sleep guidance follows Walsh et al. (2021, BJSM consensus: athletes 7–9 h, more under
heavy training) and Drake et al. (2013: caffeine even 6 h before bed disturbs sleep).
The bedtime arithmetic and the wording are working assumptions."""
import logging
from datetime import date, timedelta

from .. import models
from . import dayload as DL
from . import engine as E
from . import day_tags as DT
from . import mobility as MOB
from . import tendon as TD
from . import week_plan as WP
from .guidance import WD_IN

log = logging.getLogger(__name__)

WD = ["po", "út", "st", "čt", "pá", "so", "ne"]
WD_LONG = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
NORM_DAYS = 28
SLEEP_MIN_H, SLEEP_MAX_H = 7.0, 9.5
FALL_ASLEEP_MIN = 15
CAFFEINE_H = 6


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
           "terrain": t.get("terrain"), "notes": (t.get("notes") or [])[:3], "reasons": (g.get("reasons") or [])[:6],   # the deciding one is picked in the app (UX audit F09)
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


def _week_plan(a, db, rid, today):
    """The calendar week laid out by week_plan.py, with the Runner's must-have session due next."""
    progs = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid, models.SelfProgram.active.is_(True)).all()
    prog = next((x for x in progs if x.template == "durability"), None)
    program = None
    if prog is not None:
        hist = (prog.state or {}).get("history") or []
        last = hist[-1] if hist else None
        program = {"name": prog.name, "due": "B" if (last and last.get("session") == "A") else "A",
                   "last": last.get("date") if last else None}
    return WP.build(a, today, program)


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


KIND_TYPE = {"rest": "volno", "ride": "kolo", "swim": "plavání", "strength": "posilování", "race": "závod"}


def _item_text(it, short=False) -> str:
    """One planned item in a few words, the way the Monday sheet lists it (`short`: a
    strength session by its letter only, when it rides along with a run)."""
    if it["kind"] == "run":
        km = it.get("km") or {}
        rng = f" {_cz(km['lo'])}–{_cz(km['hi'])} km" if km.get("lo") is not None and km.get("hi") else ""
        return f"{it['label']}{rng}"
    if it["kind"] == "strength":
        if short and it.get("sessionKey"):
            return f"{it['label']} {it['sessionKey']}"
        return f"{it['label']} {it['session']}" if it.get("session") else it["label"]
    if it["kind"] in ("ride", "swim") and it.get("min"):
        return f"{it['label']} {it['min'][0]}–{it['min'][1]} min"
    return it.get("label") or ""


def _rest_of_week(plan, today, week):
    """The days after today from the same planner as the Monday sheet (week_plan.py), so
    tomorrow, the week card, its AI notes and the Monday plan say the same thing — and today
    is exactly Trénink's recommendation. Owner request 2026-10-06: a simpler split here used
    to put all the week's kilometres on the usual hard day while the plan said otherwise.
    Each day keeps the planner's items (the report lists them like the Monday sheet) plus its
    headline: the run (a fixed one before an optional one), else a race, a ride, strength,
    rest."""
    left = week.get("left")
    if today.weekday() == 6:
        return {"days": [], "left": _r(left), "notes": [],
                "note": "Týden končí, zítra začíná nový. Plán na nový týden přinese pondělní ranní report."}
    if not plan:
        return {"days": [], "left": _r(left), "notes": [],
                "note": "Plán zbytku týdne zatím nejde sestavit. Každé ráno den určí Trénink."}
    order = ("run", "race", "ride", "swim", "strength", "rest")
    days = []
    for d in plan.get("days") or []:
        if d.get("past") or d.get("today") or not d.get("items"):
            continue
        items = d["items"]
        main = min(items, key=lambda it: (order.index(it["kind"]) if it["kind"] in order else 9, bool(it.get("optional"))))
        typ = main.get("type") if main["kind"] == "run" else KIND_TYPE.get(main["kind"])
        if main["kind"] == "rest" and main.get("label") != "Volno":
            typ = None                                  # "Podle ranního doporučení" — no data for a plan yet
        km = (main.get("km") or {}).get("hi") if main["kind"] == "run" else None
        days.append({**d, "type": typ, "label": main.get("label"), "km": _r(km),
                     "kmLo": _r((main.get("km") or {}).get("lo")) if main["kind"] == "run" else None,
                     "optional": bool(main.get("optional")),
                     "text": " · ".join(t for t in (_item_text(main), *(_lower1(_item_text(it, True)) for it in items if it is not main)) if t)})
    notes = plan.get("notes") or []
    if plan.get("override"):
        note = plan["override"].rstrip(".") + "."
    elif left is not None and left <= 0.5:
        note = "Týdenní cíl máte splněný. Zbytek týdne lehce, nebo volno."
    else:
        note = next((n for n in notes if n.startswith("Zbylých")), None)
    return {"days": days, "left": _r(left), "note": note, "notes": notes}


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


TIMING_NIGHTS, TREND_NIGHTS = 28, 14
STEP_MAX_MIN = 30          # a bedtime at most this much earlier than the usual one at a time (working assumption)
TREND_MIN_WEEK = 10        # a drift of the sleep onset worth mentioning, min a week


def _onset_scale(m: int | None) -> int | None:
    """Sleep onset on one evening scale: 23:10 → 1390, 00:30 → 1470 (minutes from the evening's midnight)."""
    if m is None:
        return None
    return m + 1440 if m < 12 * 60 else m


def _sleep_timing(det, today):
    """The last nights' sleep onset and wake times from the watch (the night belongs to the
    morning it ends): series, the usual times for the kind of day tomorrow is (a workday
    or the weekend), how regular the onset is and where it drifts."""
    nights = []
    for k in range(TIMING_NIGHTS - 1, -1, -1):
        d = today - timedelta(days=k)
        sl = (det[d.isoformat()].sleep or {}) if d.isoformat() in det else {}
        on, wk = _onset_scale(_min_of(sl.get("start"))), _min_of(sl.get("end"))
        if on is None or wk is None or not (18 * 60 <= on <= 30 * 60) or not (3 * 60 <= wk <= 13 * 60):
            continue
        nights.append({"d": d.isoformat(), "wd": WD[d.weekday()], "weekend": d.weekday() >= 5, "onset": on, "wake": wk})
    if len(nights) < 3:
        return None
    tomorrow_weekend = (today + timedelta(days=1)).weekday() >= 5
    same = [n for n in nights if n["weekend"] == tomorrow_weekend]
    pool = same if len(same) >= 3 else nights

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
    recent = nights[-TREND_NIGHTS:]
    ons = [n["onset"] for n in recent]
    mean = sum(ons) / len(ons)
    sd = (sum((x - mean) ** 2 for x in ons) / len(ons)) ** 0.5
    trend = None
    if len(recent) >= 7:
        xs = [(date.fromisoformat(n["d"]) - today).days for n in recent]
        mx = sum(xs) / len(xs)
        den = sum((x - mx) ** 2 for x in xs)
        if den:
            trend = round(sum((x - mx) * (y - mean) for x, y in zip(xs, ons)) / den * 7)
    wd_n = [n for n in nights if not n["weekend"]]
    we_n = [n for n in nights if n["weekend"]]
    jetlag = None
    if len(wd_n) >= 3 and len(we_n) >= 2:
        mid = lambda ns: med([(n["onset"] + n["wake"] + 1440) / 2 for n in ns])
        jetlag = round(mid(we_n) - mid(wd_n))
    return {"nights": nights[-TREND_NIGHTS:], "onset": round(med([n["onset"] for n in pool])),
            "wake": round(med([n["wake"] for n in pool])), "sd": round(sd), "trend": trend, "jetlag": jetlag,
            "tomorrowWeekend": tomorrow_weekend, "basis": "same" if pool is same else "all", "n": len(nights)}


def _tonight(a, det, dm, today, norm, week_next_hard: bool, debt):
    """Tonight's sleep target and when to go to bed for it: the runner's norm (7–9.5 h),
    +30 min before a hard or long day, + up to 1 h back of a sleep debt (Walsh et al., 2021).
    The bedtime comes from tomorrow's usual wake time (workday / weekend) minus the target and
    15 min to fall asleep; when that is over half an hour earlier than the runner's usual
    sleep onset, tonight moves only half an hour earlier — the evening before the habitual
    sleep time is the hardest time to fall asleep (the "forbidden zone", Lavie, 1986) — and
    the same time every night counts too: regular sleep timing predicted mortality better than
    sleep length (Windred et al., 2024)."""
    base = max(SLEEP_MIN_H, norm.get("h") or 7.5)
    target = base + (0.5 if week_next_hard else 0) + min(1.0, (debt or 0) / 2)
    target = min(SLEEP_MAX_H, round(target * 4) / 4)
    tm = _sleep_timing(det, today)
    wake = tm["wake"] if tm else 6 * 60 + 30
    ideal = wake - target * 60 - FALL_ASLEEP_MIN + 1440          # on the evening scale
    bed, mode, usual_bed = ideal, "ideal", None
    if tm:
        usual_bed = tm["onset"] - FALL_ASLEEP_MIN
        gap = usual_bed - ideal
        if gap > STEP_MAX_MIN:
            bed, mode = usual_bed - STEP_MAX_MIN, "step"
        elif gap < -STEP_MAX_MIN:
            bed, mode = usual_bed, "keep"
    bed, ideal = 5 * (bed // 5), 5 * round(ideal / 5)          # a bedtime on a 5-minute mark, not later than computed
    out = {"target": target, "wake": _hm(wake), "bed": _hm(bed), "caffeine": _hm(bed - CAFFEINE_H * 60),
           "base": _r(base), "hardTomorrow": week_next_hard, "debt": debt, "wakeFromWatch": bool(tm),
           "ideal": _hm(ideal), "mode": mode, "latency": FALL_ASLEEP_MIN,
           # what the report needs to redo the sum for another wake time the runner picks
           "wakeMin": round(wake) % 1440, "stepMax": STEP_MAX_MIN, "caffeineH": CAFFEINE_H,
           "usualBedMin": None if usual_bed is None else round(usual_bed)}
    if tm:
        out["timing"] = {**tm, "usualOnset": _hm(tm["onset"]), "usualWake": _hm(tm["wake"]), "usualBed": _hm(usual_bed),
                         "bedMin": round(bed), "idealMin": round(ideal), "wakeMin": wake}
    return out


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
    ov = g.get("override") or {}
    if ov.get("title"):                          # a rule that changes today outright (pain, illness, a tendon test …) first
        out.append({"level": "alert", "text": f"{ov['title']}."})
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
    nxt = _next_day(rest, today)
    plan_tmr = None
    if nxt:
        plan_tmr = {"type": nxt["type"], "label": nxt["label"], "km": nxt["km"], "kmLo": nxt.get("kmLo"),
                    "wd": nxt["wd"], "text": nxt["text"], "optional": nxt.get("optional")}
        out.append({"dir": 0, "text": f"Zítra podle plánu týdne: {_lower1(nxt['text'])}."})
    return {"effects": out[:5], "plan": plan_tmr}


def _next_day(rest, today):
    return next((d for d in (rest or {}).get("days") or [] if d["date"] == (today + timedelta(days=1)).isoformat()), None)


def _lower1(txt: str) -> str:
    """"Lehký běh 5–6 km" → "lehký běh 5–6 km" in the middle of a sentence (a race keeps its name)."""
    return txt[:1].lower() + txt[1:] if txt and not txt[1:2].isupper() else txt


# ------------------------------------------------------------------ rule-based card notes (fallback for the AI)
def _notes_morning(r) -> dict:
    n, rec, sl = r["night"], r["recovery"], r["sleep"]
    notes = {}
    sc = (sl.get("scores") or [{}])[-1].get("score") if sl else None
    if n:
        txt = _night_text(n)
        tip = ("Držte čas usínání co nejpravidelněji, pomáhá to hlubokému spánku." if (n.get("debt") or 0) < 1
               else "Dnes večer jděte spát o půl hodiny dřív a hodinu před spaním vynechte obrazovky.")
        # one sentence per piece, so the English dictionary takes them one by one (UX audit F13)
        notes["sleep"] = " ".join(x for x in ((f"Skóre spánku {sc} ze 100." if sc is not None else ""), txt, tip) if x)
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
    if r.get("weekPlan"):
        notes["weekPlan"] = WP.note(r["weekPlan"])
    if r.get("tendon"):
        notes["tendon"] = TD.note(r["tendon"])
    if r.get("tagsLastNight"):
        notes["tagsLastNight"] = DT.note_last_night(r["tagsLastNight"])
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
    notes["load"] = (f"Celková zátěž dne {_cz(ld['total'], 0)} bodů, z toho mimo trénink {_cz(ld['nt'], 0)}. "
                     + ("Dnešní limity jsou vyčerpané, zbytek dne odpočívejte." if ld.get("left") is not None and ld["left"] <= 0 else
                        "Do dnešních limitů zbývá prostor, ale není nutné ho využít."))
    t = r["tomorrow"]
    bad = [e for e in t["effects"] if e["dir"] < 0]
    notes["tomorrow"] = (bad[0]["text"] if bad else "Nic dnes zítřek výrazně nezhorší.") + (
        f" Zítra: {_lower1(t['plan']['text'])}." if t.get("plan") else "")
    wk, rw = r["week"], r["restOfWeek"]
    key = [d for d in rw.get("days") or [] if d.get("type") in ("kvalitní", "dlouhý") and not d.get("optional")]
    shape = " ".join(f"{WD_IN[date.fromisoformat(d['date']).weekday()].capitalize()} {d['label'].lower()}." for d in key) or None
    notes["week"] = " ".join(x for x in (
        f"Tento týden {_cz(wk.get('done') or 0)} z {_cz(wk['budget'], 0)} km." if wk.get("budget") else None,
        rw.get("note"), shape if not rw.get("note") or rw.get("note", "").startswith("Zbylých") else None,
        "Každé ráno plán upřesní připravenost.") if x)
    if r.get("mobility"):
        notes["mobility"] = MOB.note(r["mobility"])
    tn = r["tonight"]
    tmg = tn.get("timing") or {}
    notes["tonight"] = f"Cíl {_dur(tn['target'])} spánku: zítra vstáváte kolem {tn['wake']}, do postele kolem {tn['bed']}, poslední káva do {tn['caffeine']}."
    if tn.get("mode") == "step":
        notes["tonight"] += (f" Ideálně by to bylo {tn['ideal']}, obvykle ale usínáte až v {tmg.get('usualOnset')}, "
                             "proto dnes jen o půl hodiny dřív a další večery postupně.")
    elif (tmg.get("sd") or 0) >= 45:
        notes["tonight"] += f" Usínání vám kolísá zhruba o {tmg['sd']} min, stejný čas každý večer pomůže."
    else:
        notes["tonight"] += " Chladná a tmavá ložnice pomůže."
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
        if today.weekday() == 0:                 # owner request 2026-10-04: the week's plan every Monday
            r["weekPlan"] = _week_plan(a, db, rid, today)
        # suggestions #7 and #10: the morning test of a watched tendon, last evening's tags
        from . import data as D
        r["tendon"] = TD.card(D.load_runner_data(db, rid, priors=False), today)
        r["tagsLastNight"] = DT.last_night(db, rid, today)
        r["watch"] = _watchouts(a, rec, night, plan)
        r["summary"] = _summary_morning(night, rec, plan)
        r["notes"] = _notes_morning(r)
        return r
    acts = _activities(db, rid, today, today)
    day = _day(dm, det, today, acts)
    week = _week(a, db, rid, today)
    # owner request 2026-10-06: tomorrow and the rest of the week from the Monday sheet's planner
    plan = None
    if today.weekday() < 6:
        try:
            plan = _week_plan(a, db, rid, today)
        except Exception:                        # the report stands without the plan rather than fail
            log.exception("week plan for the evening report failed (runner %s)", rid)
    rest = _rest_of_week(plan, today, week)
    g = (a or {}).get("guidance") or {}
    tomorrow = (today + timedelta(days=1)).weekday()
    pat = g.get("pattern") or {}
    nxt = _next_day(rest, today)
    # a hard or long run (or a race) tomorrow: by the plan; by the usual hard days only without one
    hard_tomorrow = (nxt["type"] in ("dlouhý", "kvalitní", "závod")) if nxt else tomorrow in (pat.get("hardDays") or [])
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
    # owner request 2026-10-05: bedtime mobility picked by the day's activities
    r["mobility"] = MOB.evening(db, rid, a, today, acts, tonight.get("bed"), now_min, (view or {}).get("steps"))
    r["tomorrow"] = _tomorrow(a, view, dm, today, night, rest, tonight, hard_tomorrow)
    r["dayTags"] = DT.evening(db, rid, today)          # suggestion #10: what the day held
    if view and view.get("energy"):
        r["energyNow"] = view["energy"][-1][1]
    r["summary"] = _summary_evening(view, load, week, tonight, r["tomorrow"].get("plan"))
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


def _summary_evening(view, load, week, tonight, plan_tmr=None) -> str:
    s = []
    if view and view.get("energy"):
        s.append(f"Energie teď {view['energy'][-1][1]} ze 100.")
    if load.get("total"):
        s.append(f"Zátěž dne {_cz(load['total'], 0)} bodů" + (f", z toho mimo trénink {_cz(load['nt'], 0)}." if load.get("nt") else "."))
    if week.get("budget"):
        left = week.get("left") or 0
        s.append(f"Týden: {_cz(week.get('done') or 0)} z {_cz(week['budget'], 0)} km" + (f", zbývá {_cz(left)} km." if left > 0.5 else ", cíl splněný."))
    if plan_tmr:
        s.append(f"Zítra podle plánu: {_lower1(plan_tmr['text'])}.")
    s.append(f"Na noc {_dur(tonight['target'])} spánku, do postele kolem {tonight['bed']}.")
    return " ".join(s)
