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
             A jump (> 1.3× that run's own capacity) doesn't count for 14 days
             and afterwards only fully when a pain-free report confirmed it.
  per week — max(the average week of the previous 4 weeks, 0.9 × the best
             pain-free 7-day window of the previous 6 weeks, spike weeks
             > 1.3× their preceding 4 weeks excluded); needs 3 weeks.

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
JUMP_RATIO = 1.3        # a session / week this far over its capacity is a jump, not proof (prevention plan B1)
JUMP_HOLD_DAYS = 14     # …a jump doesn't raise capacity for this long…
JUMP_UNCONFIRMED = 0.5  # …and afterwards counts fully only when a pain-free report confirmed it
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


def report_dates(db, rid) -> set:
    """Days with any check-in or run rating — what "confirmed tolerated" needs."""
    out = {c.submitted_at[:10] for c in db.query(models.Checkin.submitted_at).filter(models.Checkin.runner_id == rid) if c.submitted_at}
    out |= {f.submitted_at[:10] for f in db.query(models.ActivityFeedback.submitted_at).filter(models.ActivityFeedback.runner_id == rid) if f.submitted_at}
    return out


def confirmed(day: str, reports: set, pain: set) -> bool:
    """A report within 72 h after the session and no running pain ≥ 3 in that time."""
    d0 = _d(day)
    days = [(d0 + timedelta(days=k)).isoformat() for k in range(PAIN_AFTER + 1)]
    return any(d in reports for d in days) and not any(d in pain for d in days)


# ------------------------------------------------------------------ capacity
def _decay(age):
    return 1.0 if age <= CAP_WINDOW else 0.5 ** ((age - CAP_WINDOW) / CAP_HALF_LIFE)


def channel_items(sessions, ch, pain: set, tol: dict | None = None, reports: set | None = None):
    """Sorted (date, value, tolerated, jump, confirmed) of every session carrying
    channel `ch` — built once per assessment so capacity lookups are a bisect,
    not a full scan. `jump` = the session was > JUMP_RATIO × its own capacity
    that day (plan B1); `confirmed` = a pain-free report followed it. `tol`
    (day → tolerated) can be shared across channels."""
    tol = {} if tol is None else tol
    reports = reports or set()
    items = []
    for s in sorted((s for s in sessions if s["exp"].get(ch) is not None), key=lambda s: s["date"]):
        v = s["exp"][ch]
        if s["date"] not in tol:
            tol[s["date"]] = tolerated(s["date"], pain)
        cap = session_capacity(items, s["date"], ch)        # capacity from everything before it
        jump = cap is not None and v > JUMP_RATIO * cap
        items.append((s["date"], v, tol[s["date"]], jump, confirmed(s["date"], reports, pain)))
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
    for it in items[lo:hi]:
        day, v, ok = it[0], it[1], it[2]
        jump, conf = (it[3], it[4]) if len(it) > 3 else (False, True)
        age = (ref - _d(day)).days
        if age <= CAP_WINDOW:
            n30 += 1
        if not ok:
            continue
        if jump:                     # plan B1: a jump is not yet proof of capacity
            if age < JUMP_HOLD_DAYS:
                continue
            if not conf:
                v *= JUMP_UNCONFIRMED
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
    0.9 × best pain-free 7-day window of the 6 weeks before it). A window more
    than JUMP_RATIO × the average week before it is a spike, not demonstrated
    tolerance, and is left out (plan B1)."""
    ref = _d(ref_day)
    known = (ref - _d(first_day)).days          # days of history before today
    if known < 27:
        return None
    iso = [(ref - timedelta(days=k)).isoformat() for k in range(77)]   # iso[k] = k days ago
    vals = [daily.get(d, 0.0) for d in iso]
    painful = [d in pain for d in iso]
    chronic = sum(vals[7:35]) / 4
    best = 0.0
    for back in range(7, 42):                 # window = days back … back+6
        if any(painful[back:back + 7]):
            continue
        w = sum(vals[back:back + 7])
        prior = vals[back + 7:min(back + 35, known + 1)]     # up to 4 weeks before it, within the history
        if len(prior) >= 14:
            before = sum(prior) / (len(prior) / 7)
            if before > 0 and w > JUMP_RATIO * before:
                continue
        best = max(best, w)
    return max(chronic, 0.9 * best, CHANNELS[ch]["floor_w"])


READY_BASE = (8, 56)    # baseline nights: 8–56 days back (a strained stretch doesn't become its own norm)
READY_TOLERANCE = 0.5   # SD — ordinary night-to-night noise costs nothing
READY_FULL = 3.0        # SD off the baseline = the whole deficit for that signal
READY_WEEK_BOOST = 1.25 # a 7-night mean is less noisy than one night: its deviation counts 1.25×
SLEEP_QUALITY_W = 0.5   # sleep quality (deep + REM share, efficiency) counts at most half a signal —
                        # watch sleep staging is only moderately accurate against PSG (de Zambotti 2019)
SLEEP_SD_FLOOR = {"rest_share": 0.03, "sleep_efficiency": 0.02}   # a near-constant baseline mustn't turn a 2 % dip into 4 SD


def rest_share(row):
    """Deep + REM share of the staged sleep (0–1), None without stages."""
    parts = [getattr(row, k, None) for k in ("deep_min", "rem_min", "light_min")]
    if any(p is None for p in parts) or sum(parts) <= 0:
        return None
    return (parts[0] + parts[1]) / sum(parts)


def readiness_parts(night: dict, week: dict, base: dict) -> dict:
    """Per-signal deficits 0–1. `night` = that day's values, `week` = the last 7
    nights' means, `base` = {field: (mean, sd)} of the runner's baseline nights."""
    parts = {}
    for key, sign in (("hrv_ms", -1), ("resting_hr", 1)):
        if key not in base:
            continue
        m, s = base[key]
        views = []
        if night.get(key) is not None:
            views.append(sign * (night[key] - m) / s)
        if week.get(key) is not None:
            views.append(sign * (week[key] - m) / s * READY_WEEK_BOOST)
        if views:
            d = E.clamp((max(views) - READY_TOLERANCE) / (READY_FULL - READY_TOLERANCE), 0, 1)
            parts["hrv" if key == "hrv_ms" else "rhr"] = round(d, 2)
    dur = qual = None
    if "sleep_h" in base and night.get("sleep_h") is not None:
        short = base["sleep_h"][0] - night["sleep_h"]          # hours below the usual
        dur = E.clamp((short - 0.5) / 2.0, 0, 1)
    for key in ("rest_share", "sleep_efficiency"):             # quality: less deep + REM / more awake than usual
        if key in base and night.get(key) is not None:
            m, sdv = base[key]
            z = (m - night[key]) / max(sdv, SLEEP_SD_FLOOR[key])
            q = SLEEP_QUALITY_W * E.clamp((z - READY_TOLERANCE) / (READY_FULL - READY_TOLERANCE), 0, 1)
            qual = max(qual or 0.0, q)
    if dur is not None or qual is not None:                    # a long night of poor sleep still costs
        parts["sleep"] = round(1 - (1 - (dur or 0.0)) * (1 - (qual or 0.0)), 2)
    return parts


def readiness_from(parts: dict) -> tuple[float, int]:
    """(capacity factor 0.7–1.0, readiness score 20–100 %) from per-signal deficits.
    Agreeing signals compound: the worst counts fully, the 2nd half, the 3rd a quarter."""
    top = sorted(parts.values(), reverse=True) + [0.0, 0.0, 0.0]
    deficit = E.clamp(top[0] + 0.5 * top[1] + 0.25 * top[2], 0, 1)
    return round(1 - (1 - READINESS_FLOOR) * deficit, 3), round(100 * (1 - 0.8 * deficit))


def readiness_by_day(db, rid, days) -> dict:
    """{iso day: (capacity factor 0.7–1.0, parts, readiness score 20–100)}.

    Readiness = how far this runner's own recovery markers sit from THEIR normal
    (baseline nights 8–56 days back), scaled by the size of the deviation:
      • HRV (low) and resting HR (high): the worse of last night and the 7-night
        mean — the rolling mean is what HRV-guided training uses (Plews et al.
        2013) and what the watch's "HRV status" reflects; the mean's deviation
        counts 1.25× (it's less noisy than one night);
      • sleep: hours below the usual, compounded with its quality — a lower deep +
        REM share or efficiency than usual (at most half a signal);
      • check-in soreness / fatigue 6–10.
    Each signal: nothing within ±0.5 SD (normal noise), the full deficit at 3 SD.
    The score (shown as "připravenost") = 100 − 80 × combined deficit: ~70 % when
    HRV and resting HR are both ~1.1 SD off (7-night means ~0.9 SD) or HRV alone
    ~1.45 SD low, ~40 % at ~1.75 SD each, 20 % at the floor. The capacity factor that scales
    load capacity keeps the narrower 0.7–1.0 range. (1.0 / 100 without enough
    watch data to judge.)"""
    days = sorted(set(days))
    if not days:
        return {}
    lo = (_d(days[0]) - timedelta(days=READY_BASE[1] + 1)).isoformat()
    dm = {d.date[:10]: d for d in db.query(models.DailyMetric).filter(
        models.DailyMetric.runner_id == rid, models.DailyMetric.date >= lo).all()}
    cks = {}
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid,
                                             models.Checkin.submitted_at >= lo).all():
        cks.setdefault(c.submitted_at[:10], []).append(c)
    out = {}
    for day in days:
        d0 = _d(day)
        base_rows = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(READY_BASE[0], READY_BASE[1] + 1)) if k in dm]
        week_rows = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(0, 7)) if k in dm]
        parts = {}
        night = dm.get(day)
        if night is not None and len(base_rows) >= 14:
            base = {}
            for fld in ("hrv_ms", "resting_hr", "sleep_h", "sleep_efficiency", "rest_share"):
                vals = [v for v in ((rest_share(b) if fld == "rest_share" else getattr(b, fld)) for b in base_rows)
                        if v is not None]
                if len(vals) >= 10 and (E.sd(vals) or fld in SLEEP_SD_FLOOR):
                    base[fld] = (E.mean(vals), E.sd(vals) or 0.0)
            wk = {}
            for fld in ("hrv_ms", "resting_hr"):
                vals = [getattr(b, fld) for b in week_rows if getattr(b, fld) is not None]
                if len(vals) >= 3:
                    wk[fld] = E.mean(vals)
            parts = readiness_parts({**{f: getattr(night, f) for f in ("hrv_ms", "resting_hr", "sleep_h", "sleep_efficiency")},
                                     "rest_share": rest_share(night)}, wk, base)
        for c in cks.get(day, []):
            if c.soreness is not None and c.soreness >= 6:
                parts["soreness"] = max(parts.get("soreness", 0), round(E.clamp((c.soreness - 5) / 5, 0, 1), 2))
            if c.stress is not None and c.stress >= 6:
                parts["fatigue"] = max(parts.get("fatigue", 0), round(E.clamp((c.stress - 5) / 5, 0, 1), 2))
        factor, score = readiness_from(parts)
        out[day] = (factor, parts, score)
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
    hrmax, rhr = E.hr_bounds(runs_only, E.daily(db, rid, 180), runner.birth_year if runner else None,
                             runner.hr_max if runner else None)
    sessions = run_exposures(db, rid, hrmax, rhr)
    pain = pain_dates(db, rid)
    reports = report_dates(db, rid)
    shrink = E.clamp(1 - 2.5 * (frailty - 1), 0.5, 1.0)
    m_s, m_w = MARGIN_SESSION * shrink, MARGIN_WEEK * shrink
    first_day = min((s["date"] for s in sessions), default=t_iso)
    recent_days = [(today - timedelta(days=k)).isoformat() for k in range(0, 28)]
    ready = readiness_by_day(db, rid, recent_days)
    r_today, parts_today, score_today = ready.get(t_iso, (1.0, {}, 100))
    wk_ready = E.mean([ready.get(d, (1.0, {}))[0] for d in recent_days[:7]]) or 1.0

    channels, scores, drivers = {}, {}, {}
    tol: dict = {}
    runs_pool = [s for s in sessions if s["run"]]
    for ch, spec in CHANNELS.items():
        pool = sessions if ch == "systemic" else runs_pool
        items = channel_items(pool, ch, pain, tol, reports)
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
            rd, _parts, rd_score = ready.get(s["date"], (1.0, {}, 100))
            r = v / (cap * rd)
            if age <= 6:
                if worst_r is None or r > worst_r:
                    worst_r = r
                    worst = {"ratio": round(r, 2), "value": _fmt(v, ch), "cap": _fmt(cap, ch), "date": s["date"],
                             "title": s["title"], "readiness": rd, "readinessScore": rd_score}
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
        # --- the latest jump (plan B1) that doesn't count fully yet: held for
        # JUMP_HOLD_DAYS, then half unless a pain-free report confirmed it
        pending = None
        for day, v, ok, jump, conf in items:
            age = (today - _d(day)).days
            if jump and ok and 0 <= age < 28 and (age < JUMP_HOLD_DAYS or not conf):
                prev = session_capacity(items, day, ch)
                pending = {"date": day, "value": _fmt(v, ch), "ratio": round(v / prev, 2) if prev else None,
                           "countsFrom": (_d(day) + timedelta(days=JUMP_HOLD_DAYS)).isoformat(),
                           "confirmed": conf, "weight": 1.0 if conf else JUMP_UNCONFIRMED}
        raw = max(p_s, p_w, latent[0])
        driver = "session" if raw == p_s and p_s > 0 else "week" if raw == p_w and p_w > 0 else "latent" if raw > 0 else None
        scores[ch] = raw * spec["w"]
        drivers[ch] = driver
        channels[ch] = {
            "label": spec["label"], "unit": spec["unit"], "grade": spec["grade"], "weight": spec["w"],
            "session": worst, "week": week,
            "ceilingToday": _fmt(cap_today * (1 + m_s) * r_today, ch) if cap_today is not None else None,
            "capSession": _fmt(cap_today, ch) if cap_today is not None else None,
            # the per-run ceiling on a normally recovered day — "this week", not scaled by today's readiness
            "ceilingSession": _fmt(cap_today * (1 + m_s), ch) if cap_today is not None else None,
            "latent": {"pts": round(latent[0], 1), "date": latent[1], "ratio": latent[2]} if latent[0] else None,
            "pendingJump": pending,
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
                      f"kapacitě {s['cap']} {unit}" + (f" · připravenost ten den {s['readinessScore']} %" if s["readinessScore"] < 97 else ""))
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
        "readiness": {"today": r_today, "score": score_today, "parts": parts_today, "week": round(wk_ready, 3)},
        "margins": {"session": round(m_s, 3), "week": round(m_w, 3), "frailty": round(frailty, 2)},
        "zones": hr_zones(hrmax, rhr), "hrMax": E.rnd(hrmax), "hrRest": E.rnd(rhr),
        "hrMaxMeasured": bool(runner and runner.hr_max),
        "relativeEffort": relative_effort(sessions, t_iso),
    }
