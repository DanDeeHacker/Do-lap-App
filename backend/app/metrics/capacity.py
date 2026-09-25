"""Engine v3 ("Kapacitní") — the per-runner LOAD CAPACITY model.

One model, two views: the Zátěž axis scores how far recent training went past
what this runner has *demonstrated they tolerate* (this module), and the Trénink
tab (phase 2) spends the remaining headroom. Both read the same numbers, so they
can't contradict each other.

Channels (each scored per run AND per rolling 7 days):
  volume     km of running                               evidence B (RUNSAFE 2025, Nielsen 2014)
  intensity  minutes at ≥ 80 % heart-rate reserve (Z4+)  evidence B (effort, Neal 2024)
  descent    descent metres, weighted by steepness       evidence C (eccentric load, repeated-bout effect)
  ascent     ascent metres                               evidence C (calf / Achilles)
  systemic   HR training load (TRIMP) across all sports  evidence B (internal load)

Capacity = demonstrated tolerance:
  per run  — the largest single exposure in the last 30 days (runs 30–90 days old
             count with a 30-day half-life), ignoring runs that were followed
             within 72 h by running-relevant pain ≥ 3/10 (not actually tolerated);
             needs ≥ 3 prior runs in 30 days, else "unknown" (not scored).
  per week — max(the average week of the previous 4 weeks, 0.9 × the best
             pain-free 7-day window of the previous 6 weeks); needs 3 weeks.

Readiness (0.7–1.0) scales capacity DOWN on a poorly recovered day: that night's
HRV and resting HR against the runner's own 28-day baseline, sleep shortfall and
check-in soreness/fatigue. A normal run on a bad night therefore counts as an
exceedance; the same run on a good night doesn't. Injury history (frailty) shrinks
the safety margins.

Scoring: ratio r = exposure / (capacity × readiness). Points start above the
margin (+10 % per run, +15 % per week) and rise through mild (to 1.3×, ≤ 6 b),
moderate (to 2×, ≤ 20 b) and high (> 2×, up to 40 b at 3×) bands, times the channel's
evidence weight. The worst channel counts fully, the second 50 %, the rest 25 % —
so a run that is long AND hilly AND hard scores above any one of those alone,
without the same event being counted three times over.
"""
import math
from bisect import bisect_left
from datetime import date, timedelta
from functools import lru_cache

from .. import models
from . import engine as E
from . import terrain

CHANNELS = {
    "volume": {"label": "Objem", "unit": "km", "dec": 1, "w": 1.0, "grade": "B",
               "floor_s": 3.0, "floor_w": 10.0},
    "intensity": {"label": "Intenzita", "unit": "min v Z4+", "dec": 0, "w": 0.9, "grade": "B",
                  "floor_s": 5.0, "floor_w": 10.0},
    "descent": {"label": "Klesání", "unit": "m", "dec": 0, "w": 0.8, "grade": "C",
                "floor_s": 50.0, "floor_w": 150.0},
    "ascent": {"label": "Stoupání", "unit": "m", "dec": 0, "w": 0.5, "grade": "C",
               "floor_s": 50.0, "floor_w": 150.0},
    "systemic": {"label": "Celková zátěž", "unit": "j.z.", "dec": 0, "w": 0.7, "grade": "B",
                 "floor_s": 30.0, "floor_w": 100.0},
}
RUN_CHANNELS = ("volume", "intensity", "descent", "ascent")

MARGIN_SESSION = 0.10   # RUNSAFE: risk starts rising above +10 % of the 30-day longest run
MARGIN_WEEK = 0.15      # Nielsen 2014: > 30 %/week clearly risky; 10–15 % conservative
CAP_WINDOW, CAP_MAX_AGE, CAP_HALF_LIFE = 30, 90, 30.0   # days
MIN_PRIOR = 3           # prior runs in 30 days needed to know a per-run capacity
PAIN_AFTER = 3          # days after a run in which reported pain marks it "not tolerated"
READINESS_FLOOR = 0.7
Z4_HRR = 0.80           # Z4 starts at 80 % heart-rate reserve (Karvonen)
ECC_DEFAULT = 1.16      # descent weighting without a profile ≈ a typical −5 % descent
COMBO = (1.0, 0.5, 0.25, 0.25, 0.25)
TOP_N = {"intensity": 3}   # per-run capacity = mean of the N largest tolerated sessions (else the max)
ZONES = (("Z1", 0.50, 0.60), ("Z2", 0.60, 0.70), ("Z3", 0.70, 0.80), ("Z4", 0.80, 0.90), ("Z5", 0.90, 1.00))


# ------------------------------------------------------------------ scoring
def band_points(r, margin):
    """Points for an exposure/capacity ratio, before the channel weight."""
    if r is None or r <= 1 + margin:
        return 0.0
    if r <= 1.3:
        return (r - 1 - margin) / (0.3 - margin) * 6.0
    if r <= 2.0:
        return 6.0 + (r - 1.3) / 0.7 * 14.0
    return 20.0 + min(r - 2.0, 1.0) * 20.0   # > 2× (RUNSAFE's clear danger zone) keeps climbing to 40 at 3×


def latent_points(r, age):
    """A big exceedance 1–4 weeks ago still counts (IOC 2016: injury risk peaks
    1–4 weeks after a rapid rise), decaying linearly to zero at 28 days."""
    if r is None or r <= 1.3 or age <= 6 or age >= 28:
        return 0.0
    return min((r - 1.3) * (28 - age) / 21 * 22, 16.0)


def combine(scores: dict) -> dict:
    """Worst channel counts fully, the 2nd 50 %, the rest 25 % each."""
    order = sorted(scores, key=lambda c: -scores[c])
    return {c: scores[c] * COMBO[i] for i, c in enumerate(order)}


# ------------------------------------------------------------------ exposures
def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def z4_minutes(a, hist, hrmax, rhr):
    """Minutes at ≥ Z4. From the stream's HR histogram when fetched (exact), else
    from the run's thirds or its average HR, assuming HR spreads around the mean
    (so a tempo run averaging just under Z4 still counts its hard minutes)."""
    if hrmax <= rhr:
        return None
    thr = rhr + Z4_HRR * (hrmax - rhr)
    if hist:
        return sum(s for b, s in hist.items() if float(b) + 1.0 >= thr) / 60.0
    dur = a.duration_min or 0
    if dur <= 0:
        return None
    th = a.hr_thirds
    if th and len(th) == 3 and all(th):
        sdv = 0.04 * (hrmax - rhr)
        return sum(dur / 3 * (1 - _phi((thr - h) / sdv)) for h in th)
    if a.avg_hr:
        return dur * (1 - _phi((thr - a.avg_hr) / (0.06 * (hrmax - rhr))))
    return None


def zone_minutes(a, hist, hrmax, rhr):
    """Minutes in Z1–Z5 (heart-rate reserve bands, ZONES) — exact from the stream's
    HR histogram, else estimated like z4_minutes (HR spread around the thirds /
    the average). Z4 + Z5 equals z4_minutes. None without heart rate."""
    if hrmax <= rhr:
        return None
    bounds = [(rhr + lo * (hrmax - rhr), rhr + hi * (hrmax - rhr)) for _, lo, hi in ZONES]
    bounds[-1] = (bounds[-1][0], math.inf)
    out = [0.0] * len(ZONES)
    if hist:
        for b, sec in hist.items():
            h = float(b) + 1.0
            for i, (lo, hi) in enumerate(bounds):
                if lo <= h < hi:
                    out[i] += sec / 60.0
                    break
        return out
    dur = a.duration_min or 0
    th = a.hr_thirds
    if dur <= 0:
        return None
    if th and len(th) == 3 and all(th):
        parts = [(dur / 3, h, 0.04 * (hrmax - rhr)) for h in th]
    elif a.avg_hr:
        parts = [(dur, a.avg_hr, 0.06 * (hrmax - rhr))]
    else:
        return None
    for d, h, sdv in parts:
        for i, (lo, hi) in enumerate(bounds):
            out[i] += d * ((1.0 if hi == math.inf else _phi((hi - h) / sdv)) - _phi((lo - h) / sdv))
    return out


_ECC_CACHE: dict = {}


def _ecc_factor(profile, key=None):
    """weighted / raw descent for a profile (None when it barely descends).
    Memoised per activity — profiles don't change, and history replays ask daily."""
    if key is not None and key in _ECC_CACHE:
        return _ECC_CACHE[key]
    raw, weighted = terrain.descent_weighting(profile)
    val = (weighted / raw) if raw > 5 else None
    if key is not None:
        if len(_ECC_CACHE) > 20000:
            _ECC_CACHE.clear()
        _ECC_CACHE[key] = val
    return val


def run_exposures(db, rid, hrmax, rhr):
    """Every session → {id, date, run, title, km, exp{channel: value|None}}."""
    acts = E.all_acts(db, rid)
    hists = {}
    for aid, q in db.query(models.ActivityStream.activity_id, models.ActivityStream.quality_json).filter(
            models.ActivityStream.runner_id == rid).all():
        if q and q.get("hrHist"):
            hists[aid] = q["hrHist"]
    fac = {a.id: _ecc_factor(a.elevation_profile, (a.id, len(a.elevation_profile or [])))
           for a in acts if E.is_run(a) and a.elevation_profile}
    facs = [f for f in fac.values() if f]
    default_fac = E.median(facs) if facs else ECC_DEFAULT
    out = []
    for a in acts:
        if not a.started_at:
            continue
        run = E.is_run(a)
        exp = {"systemic": E.session_load(a, hrmax, rhr) or None}
        zones = None
        if run:
            desc = a.descent_m
            if desc is None and a.elevation_profile:
                desc = terrain.descent_weighting(a.elevation_profile)[0]
            exp["volume"] = a.distance_km or 0.0
            exp["intensity"] = z4_minutes(a, hists.get(a.id), hrmax, rhr)
            exp["descent"] = (desc or 0.0) * (fac.get(a.id) or default_fac)
            exp["ascent"] = a.ascent_m or 0.0
            zones = zone_minutes(a, hists.get(a.id), hrmax, rhr)
        out.append({"id": a.id, "date": a.started_at[:10], "run": run, "title": a.title,
                    "km": a.distance_km, "exp": exp, "avgHr": a.avg_hr,
                    "zoneMin": zones, "zoneExact": bool(hists.get(a.id)),
                    "speed": E._speed_ms(a), "ascPerKm": ((a.ascent_m or 0) + (a.descent_m or 0)) / max(a.distance_km or 1, 0.1)})
    return out


def pain_dates(db, rid) -> set:
    """Days with running-relevant pain ≥ 3/10 (check-ins, run ratings, niggles)."""
    out = set()
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid).all():
        if (c.pain_score or 0) >= 3 and c.submitted_at:
            regions = [p.get("region") for p in (c.pain_points or []) if p.get("region")]
            if not regions or any(E._run_relevant(r) for r in regions):
                out.add(c.submitted_at[:10])
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid).all():
        if ((f.pain_during or 0) >= 3 or f.niggle) and f.submitted_at:
            out.add(f.submitted_at[:10])
    return out


@lru_cache(maxsize=8192)
def _d(s):
    return date.fromisoformat(s[:10])


def tolerated(day: str, pain: set) -> bool:
    d0 = _d(day)
    return not any((d0 + timedelta(days=k)).isoformat() in pain for k in range(PAIN_AFTER + 1))


# ------------------------------------------------------------------ capacity
def _decay(age):
    return 1.0 if age <= CAP_WINDOW else 0.5 ** ((age - CAP_WINDOW) / CAP_HALF_LIFE)


def channel_items(sessions, ch, pain: set, tol: dict | None = None):
    """Sorted (date, value, tolerated) of every session carrying channel `ch` —
    built once per assessment so capacity lookups are a bisect, not a full scan.
    `tol` (day → tolerated) can be shared across channels."""
    tol = {} if tol is None else tol
    items = []
    for s in sessions:
        v = s["exp"].get(ch)
        if v is None:
            continue
        if s["date"] not in tol:
            tol[s["date"]] = tolerated(s["date"], pain)
        items.append((s["date"], v, tol[s["date"]]))
    items.sort(key=lambda t: t[0])
    return items


def session_capacity(items, ref_day: str, ch):
    """Largest tolerated single-session exposure before `ref_day` (decayed), or
    None when fewer than MIN_PRIOR sessions in the last 30 days carry the channel.
    Intensity uses the mean of the TOP_N largest instead: Z4+ minutes of one
    session can be an outlier (a race, a hot day inflating heart rate), and a
    single such run must not open a huge per-run allowance. `items` from
    channel_items()."""
    ref = _d(ref_day)
    lo = bisect_left(items, ((ref - timedelta(days=CAP_MAX_AGE)).isoformat(),))
    hi = bisect_left(items, (ref_day,))
    vals, n30 = [], 0
    for day, v, ok in items[lo:hi]:
        age = (ref - _d(day)).days
        if age <= CAP_WINDOW:
            n30 += 1
        if ok:
            vals.append(v * _decay(age))
    if n30 < MIN_PRIOR:
        return None
    vals.sort(reverse=True)
    top = vals[:TOP_N.get(ch, 1)]
    best = sum(top) / len(top) if top else 0.0
    return max(best, CHANNELS[ch]["floor_s"])


def _daily_sums(sessions, ch):
    out = {}
    for s in sessions:
        v = s["exp"].get(ch)
        if v:
            out[s["date"]] = out.get(s["date"], 0.0) + v
    return out


def weekly_capacity(daily: dict, ref_day: str, first_day: str, pain: set, ch):
    """max(average week of the 4 weeks before the current 7-day window,
    0.9 × best pain-free 7-day window of the 6 weeks before it)."""
    ref = _d(ref_day)
    if (ref - _d(first_day)).days < 27:
        return None
    iso = [(ref - timedelta(days=k)).isoformat() for k in range(49)]   # iso[k] = k days ago
    vals = [daily.get(d, 0.0) for d in iso]
    painful = [d in pain for d in iso]
    chronic = sum(vals[7:35]) / 4
    best = 0.0
    for back in range(7, 42):                 # window = days back … back+6
        if not any(painful[back:back + 7]):
            best = max(best, sum(vals[back:back + 7]))
    return max(chronic, 0.9 * best, CHANNELS[ch]["floor_w"])


def readiness_by_day(db, rid, days) -> dict:
    """{iso day: (factor 0.7–1.0, parts)} from that night's HRV / resting HR /
    sleep against the runner's own baseline (days −35…−8) plus that day's check-in
    soreness and fatigue. 1.0 when there isn't enough watch data to judge."""
    days = sorted(set(days))
    if not days:
        return {}
    lo = (_d(days[0]) - timedelta(days=36)).isoformat()
    dm = {d.date[:10]: d for d in db.query(models.DailyMetric).filter(
        models.DailyMetric.runner_id == rid, models.DailyMetric.date >= lo).all()}
    cks = {}
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid,
                                             models.Checkin.submitted_at >= lo).all():
        cks.setdefault(c.submitted_at[:10], []).append(c)
    out = {}
    for day in days:
        d0 = _d(day)
        base = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(8, 36)) if k in dm]
        parts = {}
        night = dm.get(day)
        if night is not None and len(base) >= 14:
            for key, fld, sign in (("hrv", "hrv_ms", -1), ("rhr", "resting_hr", 1)):
                vals = [getattr(b, fld) for b in base if getattr(b, fld) is not None]
                v = getattr(night, fld)
                if v is not None and len(vals) >= 10 and E.sd(vals):
                    parts[key] = round(E.clamp(sign * (v - E.mean(vals)) / E.sd(vals) / 2.0, 0, 1), 2)
            sl = [b.sleep_h for b in base if b.sleep_h is not None]
            if night.sleep_h is not None and len(sl) >= 10:
                parts["sleep"] = round(E.clamp((E.mean(sl) - night.sleep_h) / 2.0, 0, 1), 2)
        for c in cks.get(day, []):
            if c.soreness is not None and c.soreness >= 6:
                parts["soreness"] = max(parts.get("soreness", 0), round(E.clamp((c.soreness - 5) / 5, 0, 1), 2))
            if c.stress is not None and c.stress >= 6:
                parts["fatigue"] = max(parts.get("fatigue", 0), round(E.clamp((c.stress - 5) / 5, 0, 1), 2))
        deficit = E.mean(parts.values()) if parts else 0.0
        out[day] = (round(1 - (1 - READINESS_FLOOR) * deficit, 3), parts)
    return out


def hr_zones(hrmax, rhr):
    return [{"z": z, "lo": round(rhr + a * (hrmax - rhr)), "hi": round(rhr + b * (hrmax - rhr))}
            for z, a, b in ZONES]


# ------------------------------------------------------------------ relative effort
def _pct_rank(xs, v):
    return sum(1 for x in xs if x <= v) / len(xs) if xs else None


def _quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))] if xs else None


def hr_speed_fit(runs, ref_day: str, lo=7, hi=56):
    """The runner's own HR-vs-speed line (intercept, bpm per m/s) from flat-ish
    runs lo…hi days before `ref_day` — Theil–Sen, so odd runs don't bend it. None
    with < 8 runs, < 0.15 m/s of speed spread, or a non-rising slope."""
    d0 = _d(ref_day)
    base = [p for p in runs if lo <= (d0 - _d(p["date"])).days <= hi and p["avgHr"] and p["speed"]
            and p["ascPerKm"] < 15]
    if len(base) < 8:
        return None
    pts = [(p["speed"], p["avgHr"]) for p in base]
    sl = [(h2 - h1) / (v2 - v1) for i, (v1, h1) in enumerate(pts) for (v2, h2) in pts[i + 1:] if abs(v2 - v1) >= 0.05]
    spread = max(p[0] for p in pts) - min(p[0] for p in pts)
    if len(sl) < 10 or spread < 0.15:
        return None
    b = E.median(sl)
    if b <= 0.5:
        return None
    return (E.median([h - b * v for v, h in pts]), b)


def relative_effort(sessions, ref_day: str, n_runs=6):
    """Strava-style relative effort against the runner's last 8 weeks: each recent
    run's HR training load vs the runs of the previous 56 days (below / usual /
    above / well above), HR at that pace vs the heart rate the runner usually
    needs for it (an easy run costing +8 bpm is a fatigue / heat / illness hint),
    and the last 7 days' total vs the usual weekly range."""
    ref = _d(ref_day)
    runs = [s for s in sessions if s["run"] and s["exp"].get("systemic")]
    recent = [s for s in runs if 0 <= (ref - _d(s["date"])).days <= 13][-n_runs:]
    out_runs = []
    for s in reversed(recent):
        d0 = _d(s["date"])
        past = [p["exp"]["systemic"] for p in runs if 0 < (d0 - _d(p["date"])).days <= 56]
        row = {"date": s["date"], "title": s["title"], "km": E.r1(s["km"]) if s["km"] else None,
               "effort": E.rnd(s["exp"]["systemic"]), "band": None, "pct": None, "hrDelta": None, "hrExpected": None}
        if len(past) >= 6:
            v = s["exp"]["systemic"]
            q1, q3 = _quantile(past, 0.25), _quantile(past, 0.75)
            row["band"] = ("pod" if v < q1 else "obvyklé" if v <= q3 else "nad" if v <= max(past) else "výrazně nad")
            row["pct"] = round(_pct_rank(past, v) * 100)
            row["usual"] = [E.rnd(q1), E.rnd(q3)]
        fit = hr_speed_fit(runs, s["date"])
        if s["avgHr"] and s["speed"] and fit:
            exp_hr = fit[0] + fit[1] * s["speed"]
            row["hrExpected"] = E.rnd(exp_hr)
            row["hrDelta"] = E.rnd(s["avgHr"] - exp_hr)
        out_runs.append(row)
    daily = _daily_sums([s for s in sessions if s["exp"].get("systemic")], "systemic")

    def win(end):
        return sum(daily.get((end - timedelta(days=k)).isoformat(), 0.0) for k in range(7))
    week = None
    past_w = [win(ref - timedelta(days=b)) for b in range(7, 57)]
    if sum(1 for x in past_w if x > 0) >= 20:
        now = win(ref)
        lo, hi = _quantile(past_w, 0.25), _quantile(past_w, 0.75)
        week = {"now": E.rnd(now), "lo": E.rnd(lo), "hi": E.rnd(hi),
                "band": "pod" if now < lo else "obvyklé" if now <= hi else "nad"}
    return {"runs": out_runs, "week": week}


# ------------------------------------------------------------------ assessment
def _cz(day: str) -> str:
    d0 = _d(day)
    return f"{d0.day}. {d0.month}."


def _fmt(v, ch):
    dec = CHANNELS[ch]["dec"]
    return None if v is None else (round(v, dec) if dec else round(v))


def assess_capacity(db, rid, frailty=1.0, runner=None) -> dict:
    """The v3 load axis + today's capacity picture. Returns
    {score, signals[], channels{}, readiness{}, zones[], relativeEffort{}, margins{}}."""
    today = E.today_date()
    t_iso = today.isoformat()
    runs_only = E.acts(db, rid)
    hrmax, rhr = E.hr_bounds(runs_only, E.daily(db, rid, 180), runner.birth_year if runner else None)
    sessions = run_exposures(db, rid, hrmax, rhr)
    pain = pain_dates(db, rid)
    shrink = E.clamp(1 - 2.5 * (frailty - 1), 0.5, 1.0)
    m_s, m_w = MARGIN_SESSION * shrink, MARGIN_WEEK * shrink
    first_day = min((s["date"] for s in sessions), default=t_iso)
    recent_days = [(today - timedelta(days=k)).isoformat() for k in range(0, 28)]
    ready = readiness_by_day(db, rid, recent_days)
    r_today, parts_today = ready.get(t_iso, (1.0, {}))
    wk_ready = E.mean([ready.get(d, (1.0, {}))[0] for d in recent_days[:7]]) or 1.0

    channels, scores, drivers = {}, {}, {}
    tol: dict = {}
    runs_pool = [s for s in sessions if s["run"]]
    for ch, spec in CHANNELS.items():
        pool = sessions if ch == "systemic" else runs_pool
        items = channel_items(pool, ch, pain, tol)
        # --- per session: the recent session furthest over ITS capacity that day
        worst = None
        worst_r = None          # unrounded, for the v3 sandbox's exact replay
        latent = (0.0, None, None)
        for s in pool:
            v = s["exp"].get(ch)
            if v is None:
                continue
            age = (today - _d(s["date"])).days
            if age < 0 or age >= 28:
                continue
            cap = session_capacity(items, s["date"], ch)
            if cap is None:
                continue
            rd = ready.get(s["date"], (1.0, {}))[0]
            r = v / (cap * rd)
            if age <= 6:
                if worst_r is None or r > worst_r:
                    worst_r = r
                    worst = {"ratio": round(r, 2), "value": _fmt(v, ch), "cap": _fmt(cap, ch), "date": s["date"],
                             "title": s["title"], "readiness": rd}
            else:
                lp = latent_points(r, age)
                if lp > latent[0]:
                    latent = (lp, s["date"], round(r, 2))
        p_s = band_points(worst_r, m_s) if worst else 0.0
        # --- rolling 7 days
        daily = _daily_sums(pool, ch)
        capw = weekly_capacity(daily, t_iso, first_day, pain, ch)
        now_w = sum(daily.get((today - timedelta(days=k)).isoformat(), 0.0) for k in range(7))
        week = None
        p_w = 0.0
        rw = None
        if capw is not None:
            rw = now_w / (capw * wk_ready)
            p_w = band_points(rw, m_w)
            # the ceiling is exactly where the weekly score starts: capacity × the
            # week's average readiness × (1 + margin) — not today's readiness, so
            # the weekly picture doesn't jump with one night's sleep
            ceil_w = capw * (1 + m_w) * wk_ready
            week = {"now": _fmt(now_w, ch), "cap": _fmt(capw, ch), "ratio": round(rw, 2),
                    "ceiling": _fmt(ceil_w, ch), "left": _fmt(max(0.0, ceil_w - now_w), ch)}
        # --- today's per-run ceiling (capacity from everything before today)
        cap_today = session_capacity(items, (today + timedelta(days=1)).isoformat(), ch)
        raw = max(p_s, p_w, latent[0])
        driver = "session" if raw == p_s and p_s > 0 else "week" if raw == p_w and p_w > 0 else "latent" if raw > 0 else None
        scores[ch] = raw * spec["w"]
        drivers[ch] = driver
        channels[ch] = {
            "label": spec["label"], "unit": spec["unit"], "grade": spec["grade"], "weight": spec["w"],
            "session": worst, "week": week,
            "ceilingToday": _fmt(cap_today * (1 + m_s) * r_today, ch) if cap_today is not None else None,
            "capSession": _fmt(cap_today, ch) if cap_today is not None else None,
            "latent": {"pts": round(latent[0], 1), "date": latent[1], "ratio": latent[2]} if latent[0] else None,
            "raw": round(raw, 1), "driver": driver, "known": worst is not None or week is not None or cap_today is not None,
            "exact": {"rs": worst_r, "rw": rw, "lat": latent[0]},
        }
    contrib = combine(scores)
    signals = []
    total = 0
    for ch, c in sorted(contrib.items(), key=lambda kv: -kv[1]):
        pts = E.rnd(c)
        channels[ch]["pts"] = pts
        if not pts:
            continue
        total += pts
        info = channels[ch]
        spec = CHANNELS[ch]
        unit = spec["unit"]
        if drivers[ch] == "session":
            s = info["session"]
            val = f"×{s['ratio']}"
            detail = (f"Nejnáročnější běh 7 dní ({_cz(s['date'])}): {s['value']} {unit} proti vaší prokázané "
                      f"kapacitě {s['cap']} {unit}" + (f" · připravenost ten den {round(s['readiness'] * 100)} %" if s["readiness"] < 0.99 else ""))
        elif drivers[ch] == "week":
            w = info["week"]
            val = f"×{w['ratio']}"
            detail = f"Posledních 7 dní {w['now']} {unit} proti vaší týdenní kapacitě {w['cap']} {unit}"
        else:
            lt = info["latent"]
            val = f"před {(today - _d(lt['date'])).days} dny"
            detail = (f"Doznívá skok ×{lt['ratio']} z {_cz(lt['date'])} — riziko vrcholí 1–4 týdny po prudkém nárůstu.")
        name = {"volume": "Objem nad kapacitou", "intensity": "Intenzita nad kapacitou",
                "descent": "Klesání nad kapacitou", "ascent": "Stoupání nad kapacitou",
                "systemic": "Celková zátěž nad kapacitou"}[ch]
        signals.append({"id": f"cap_{ch}", "name": name, "grade": spec["grade"], "pts": pts, "val": val,
                        "detail": detail})
    week7 = [s for s in runs_pool if 0 <= (today - _d(s["date"])).days < 7 and s.get("zoneMin")]
    zmin = [sum(s["zoneMin"][i] for s in week7) for i in range(len(ZONES))]
    zone7 = {"minutes": [{"z": z, "min": round(m)} for (z, _, _), m in zip(ZONES, zmin)],
             "runs": len(week7), "exact": all(s["zoneExact"] for s in week7)} if week7 else None
    return {
        "score": total, "signals": signals, "channels": channels, "zones7d": zone7,
        "readiness": {"today": r_today, "parts": parts_today, "week": round(wk_ready, 3)},
        "margins": {"session": round(m_s, 3), "week": round(m_w, 3), "frailty": round(frailty, 2)},
        "zones": hr_zones(hrmax, rhr), "hrMax": E.rnd(hrmax), "hrRest": E.rnd(rhr),
        "relativeEffort": relative_effort(sessions, t_iso),
    }
