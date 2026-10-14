"""v0.12.12 — Kondice a únava: the long-term trend of the total load and the race-day freshness.

The same picture as Fitness & Freshness in Strava or the Performance Management Chart in
TrainingPeaks, from the engine's own session loads (all sports, `session_load`, the Celková
zátěž channel): Kondice is the exponentially weighted average of the daily load with a 42-day
time constant, Únava the same with 7 days (Banister's fitness–fatigue model with the time
constants Coggan's PMC uses), Čerstvost their difference as a share of Kondice. It is a trend
to read, not a decision input: the fitness–fatigue model fits groups better than individuals
(Hellard 2006), and the day's training follows Připravenost and the capacity channels.

The race-day check projects the same numbers to the morning of the goal's race from the load
done so far and the plan's remaining weeks (km × the runner's load per km of the last 6 weeks),
and compares the taper as planned with the taper as run so far."""
from datetime import date, timedelta

from . import data as D
from . import engine as E

FIT_TC, FAT_TC = 42, 7          # days (Banister 1975; Coggan's PMC defaults)
FORM_FRESH, FORM_TIRED = 5.0, -10.0     # % of Kondice: the words (app convention, not a research threshold)
FORM_MIN_FIT = 10.0             # below this Kondice (load units a day) the share is not shown
WARM_DAYS = FIT_TC              # until 42 days of history Kondice is still settling
TREND_DAYS = 365
RATIO_DAYS = 42                 # load per run km: the last 6 weeks
CHECK_LEAD_DAYS = 7             # the race check shows from a week before the taper
PLAN_GAP = 10.0                 # points of Čerstvost below the planned taper → "less fresh than planned"
PLAN_OVER = 15.0                # points above → "fresher than planned"


def daily_loads(db, rid: str, hrmax: float, rhr: float) -> tuple[dict, dict]:
    """({date: total load of the day}, {date: run km of the day}) of every counted activity."""
    data = D.of(db, rid)
    acts = E.all_acts(data, rid, "load")
    ctx = E.load_context(data, rid, acts, hrmax, rhr)
    load, km = {}, {}
    for a in acts:
        if not a.started_at:
            continue
        d = a.started_at[:10]
        load[d] = load.get(d, 0.0) + (E.session_load(a, hrmax, rhr, ctx) or 0.0)
        if E.is_run(a) and a.distance_km:
            km[d] = km.get(d, 0.0) + a.distance_km
    return load, km


def step(fit: float, fat: float, v: float) -> tuple[float, float]:
    """One day of both averages (the PMC's form: x += (load − x) / time constant)."""
    return fit + (v - fit) / FIT_TC, fat + (v - fat) / FAT_TC


def form_pct(fit: float, fat: float) -> float | None:
    return round((fit - fat) / fit * 100, 1) if fit >= FORM_MIN_FIT else None


def form_word(p: float | None) -> str | None:
    if p is None:
        return None
    return "fresh" if p >= FORM_FRESH else "tired" if p < FORM_TIRED else "even"


def _run(loads: dict, start: date, end: date, fit=0.0, fat=0.0, rows: list | None = None):
    d = start
    while d <= end:
        iso = d.isoformat()
        v = loads.get(iso, 0.0)
        fit, fat = step(fit, fat, v)
        if rows is not None:
            rows.append({"d": iso, "load": round(v, 1), "fit": round(fit, 1), "fat": round(fat, 1),
                         "form": form_pct(fit, fat)})
        d += timedelta(days=1)
    return fit, fat


def _hr(db, rid: str, a: dict | None) -> tuple[float, float]:
    from . import capacity as CAP
    cap = (a or {}).get("capacity")
    if cap:
        return CAP.hr_exact(cap)
    data = D.of(db, rid)
    r = data.runner
    return E.hr_bounds(E.acts(data, rid, "load"), E.daily(data, rid, 180), getattr(r, "birth_year", None),
                       getattr(r, "hr_max", None))


def trend(db, rid: str, a: dict | None = None, today: date | None = None) -> dict:
    """The Zátěž card: a year of days {d, load, fit, fat, form} and today's numbers."""
    today = today or E.today_date()
    hrmax, rhr = _hr(db, rid, a)
    loads, _ = daily_loads(db, rid, hrmax, rhr)
    if not loads:
        return {"available": False}
    first = date.fromisoformat(min(loads))
    rows: list = []
    lo = today - timedelta(days=TREND_DAYS - 1)
    fit, fat = _run(loads, first, lo - timedelta(days=1)) if first < lo else (0.0, 0.0)
    _run(loads, max(first, lo), today, fit, fat, rows)
    now = rows[-1]
    ago = rows[-29] if len(rows) >= 29 else None
    return {"available": True, "days": rows, "since": first.isoformat(), "settling": (today - first).days < WARM_DAYS,
            "tc": [FIT_TC, FAT_TC], "bands": {"fresh": FORM_FRESH, "tired": FORM_TIRED},
            "today": {**now, "word": form_word(now["form"]),
                      "fitChange": round((now["fit"] - ago["fit"]) / ago["fit"] * 100) if ago and ago["fit"] >= FORM_MIN_FIT else None}}


# ------------------------------------------------------------------ race-day check
def _week_of(plan: list, d: date):
    for w in plan:
        s = date.fromisoformat(w["start"])
        if s <= d < s + timedelta(days=7):
            return w
    return None


def _future(plan: list, ratio: float, frm: date, race: date, done_km: dict) -> dict:
    """{date: projected load} from `frm` to the day before the race: each plan week's km (less
    what is already run in it) spread over its days left, the race week over the days before the race."""
    out = {}
    d = frm
    while d < race:
        w = _week_of(plan, d)
        if w is not None and w.get("km"):
            mon = date.fromisoformat(w["start"])
            last = min(mon + timedelta(days=6), race - timedelta(days=1))
            ran = sum(v for k, v in done_km.items() if mon.isoformat() <= k < frm.isoformat())
            days_left = (last - max(mon, frm)).days + 1
            if days_left > 0:
                out[d.isoformat()] = max(0.0, (w["km"] - ran)) * ratio / days_left
        d += timedelta(days=1)
    return out


def taper_plan(plan: list | None) -> dict | None:
    """The plan's taper weeks while the plan still holds all of them: {start, weeks[{start, km}]}."""
    rows = [w for w in plan or [] if w.get("taper")]
    if not rows or rows[0].get("taper") != 1:
        return None
    return {"start": rows[0]["start"], "weeks": [{"start": w["start"], "km": w.get("km")} for w in rows]}


def race_check(db, rid: str, res: dict, a: dict | None, stored: dict | None = None,
               today: date | None = None) -> dict | None:
    """Čerstvost on the race morning: projected from the load so far and the plan's remaining
    weeks, and — once the taper has begun — the same with the taper as planned (stored at its
    start), so extra load in the taper shows. From a week before the taper to the race."""
    today = today or E.today_date()
    goal = (res or {}).get("goal") or {}
    plan = (res or {}).get("plan") or []
    if not goal.get("date") or not plan or goal.get("kind") == "free":
        return None
    race = date.fromisoformat(goal["date"][:10])
    tw = [w for w in plan if w.get("taper")]
    if not tw or race <= today:
        return None
    t0 = date.fromisoformat(tw[0]["start"]) - timedelta(days=7 * ((tw[0].get("taper") or 1) - 1))
    if today < t0 - timedelta(days=CHECK_LEAD_DAYS):
        return None
    if stored and stored.get("start") != t0.isoformat():
        stored = None                          # a taper planned for another date (the goal moved)
    hrmax, rhr = _hr(db, rid, a)
    loads, km = daily_loads(db, rid, hrmax, rhr)
    if not loads:
        return None
    lo = today - timedelta(days=RATIO_DAYS)
    l6 = sum(v for k, v in loads.items() if lo.isoformat() < k <= today.isoformat())
    k6 = sum(v for k, v in km.items() if lo.isoformat() < k <= today.isoformat())
    if k6 < 5 or l6 <= 0:
        return None
    ratio = l6 / k6
    first = date.fromisoformat(min(loads))
    ran_today = today.isoformat() in loads
    upto = today if ran_today else today - timedelta(days=1)

    def project(until: date, weeks: list) -> float | None:
        fit, fat = _run(loads, first, until)
        fut = _future(weeks, ratio, until + timedelta(days=1), race, km)
        fit, fat = _run(fut, until + timedelta(days=1), race - timedelta(days=1), fit, fat)
        return form_pct(fit, fat)

    now = project(upto, plan)
    planned = None
    if today >= t0 and stored:
        planned = project(t0 - timedelta(days=1), stored["weeks"])
    if now is None:
        return None
    tone, kind = "ok", "onPlan"
    if now < FORM_TIRED:
        tone, kind = "alert", "tired"
    elif planned is not None and now < planned - PLAN_GAP:
        tone, kind = "watch", "lessFresh"
    elif planned is not None and now > planned + PLAN_OVER:
        tone, kind = "info", "fresher"
    return {"form": now, "word": form_word(now), "planned": planned, "tone": tone, "kind": kind,
            "inTaper": today >= t0, "taperStart": t0.isoformat(), "race": race.isoformat(), "daysTo": (race - today).days,
            "loadPerKm": round(ratio, 2)}
