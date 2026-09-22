"""Injury-risk engine v0.4 — Python port of core.js's `metrics`/`assess`
(core.js lines ~93-304 of the original prototype), extended with three new
wearable-derived signals and a refined ACWR band. Every signal still carries
an evidence grade (A/B/C) and is documented in sig_doc.py with the same
formula/why/limit/clear structure the prototype established.

Nothing here is a diagnosis. See ai_brief.py's closing caveat, which every
clinician-facing summary repeats verbatim.
"""
import math
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DBSession

from . import terrain
from .. import models
from ..serializers import to_dict

ENGINE_VERSION = "v0.6.1"
BASE_FROM, BASE_TO, RECENT = 84, 29, 28
QUAD_THRESHOLD = 25
QUAD_EXIT = 18  # hysteresis: an axis already "hot" stays hot until it drops below this


# ---------------------------------------------------------------- utils
def mean(a):
    a = list(a)
    return sum(a) / len(a) if a else 0


def sd(a):
    a = list(a)
    if len(a) < 2:
        return 0
    m = mean(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1))


def median(a):
    a = sorted(a)
    n = len(a)
    if not n:
        return 0
    mid = n // 2
    return a[mid] if n % 2 else (a[mid - 1] + a[mid]) / 2


def mad_sd(a):
    """Robust standard deviation from the median absolute deviation. Less
    inflated by a single outlier run than the plain SD, so a genuinely small
    but consistent shift still clears the threshold (v2 noise scale)."""
    a = list(a)
    if len(a) < 2:
        return 0
    m = median(a)
    return 1.4826 * median([abs(x - m) for x in a])


def slope(a):
    a = list(a)
    n = len(a)
    if n < 3:
        return 0
    xm = (n - 1) / 2
    ym = mean(a)
    num = den = 0.0
    for i, y in enumerate(a):
        num += (i - xm) * (y - ym)
        den += (i - xm) ** 2
    return num / den if den else 0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def r1(n):
    return None if n is None else round(n, 1)


def r2(n):
    return None if n is None else round(n, 2)


def rnd(n):
    return None if n is None else round(n)


def sgn(n):
    return f"+{n}" if n > 0 else str(n)


# The runner-facing engine works in local wall-clock time (Czech app), so
# "today", day_ago() windows and calendar weeks match the runner's real day —
# UTC made the day (and Mon–Sun week) flip early on weekday evenings.
LOCAL_TZ = ZoneInfo("Europe/Prague")


# Historical replay (mech-history / quadrant-history / backtest) pins "today" to
# a past date so window math is computed as of that day. This override is stored
# thread-locally — FastAPI runs sync endpoints in a threadpool, so a plain module
# global would race across concurrent requests and could leave "today" pinned to
# a stale date process-wide, corrupting every subsequent score. Use
# `with today_pinned(d): ...` to scope it.
_today_override = threading.local()


def today_date():
    o = getattr(_today_override, "value", None)
    return o if o is not None else datetime.now(LOCAL_TZ).date()


def now_iso():
    o = getattr(_today_override, "value", None)
    if o is not None:
        return datetime.combine(o, datetime.min.time(), LOCAL_TZ).isoformat()
    return datetime.now(LOCAL_TZ).isoformat()


@contextmanager
def today_pinned(d):
    prev = getattr(_today_override, "value", None)
    _today_override.value = d
    try:
        yield
    finally:
        _today_override.value = prev


# --- Engine mode (v1 = standard/averaged, v2 = sensitive/per-run) -----------
# The mechanics axis can be computed two ways; the runner picks which in the app
# (Runner.engine_mode). Stored thread-locally for the same threadpool-safety
# reason as today_pinned. v2 changes ONLY the mechanics drift core (_drift_z_core)
# — load, recovery, quadrant machinery and payload shape are shared, so the two
# engines are directly comparable and swappable per runner.
_engine_ctx = threading.local()


def _emode() -> str:
    return getattr(_engine_ctx, "mode", None) or "v1"


def _eexcl() -> frozenset:
    return getattr(_engine_ctx, "excl", None) or frozenset()


@contextmanager
def engine_pinned(mode: str):
    prev_m = getattr(_engine_ctx, "mode", None)
    prev_e = getattr(_engine_ctx, "excl", None)
    _engine_ctx.mode = mode or "v1"
    _engine_ctx.excl = frozenset()
    try:
        yield
    finally:
        _engine_ctx.mode = prev_m
        _engine_ctx.excl = prev_e


def engine_version_for(mode: str) -> str:
    return ENGINE_VERSION + ("-s" if mode == "v2" else "")


def iso_date(d):
    return d.isoformat()


def day_ago(n):
    return iso_date(today_date() - timedelta(days=n))


def days_between(a: str, b: str) -> int:
    da = datetime.fromisoformat(a).date()
    db_ = datetime.fromisoformat(b).date()
    return (db_ - da).days


_SURF_LABEL = {"road": "silnice", "trail": "terén", "treadmill": "pás", "track": "dráha"}
_GRADE_LABEL = {"up": "stoupání", "flat": "rovina", "down": "klesání", "rolling": "kopcovitě"}
_PACE_LABEL = {"fast": "rychle", "mod": "středně", "easy": "volně"}


def quadrant_of(load_score, mech_score, prev=None, hi=QUAD_THRESHOLD, lo=QUAD_EXIT, mech_ok=True):
    """Quadrant with hysteresis: an axis counts as elevated once it crosses
    `hi`, and keeps counting until it falls back below `lo`. Without this the
    label flip-flops week to week when a score hovers around 25 (seen on real
    backtested data). `prev` is the last persisted quadrant.

    `mech_ok` (v2 only) is the Phase-2 flag gate: the mechanics axis may push to
    Silent/Critical only when the across-session evidence is a real flag
    (persistence or convergence), not a single-session blip. v1 always passes
    True, so its behaviour is unchanged."""
    prev_load = prev in ("overreaching", "critical")
    prev_mech = prev in ("silent", "critical")
    load_hot = load_score >= hi or (prev_load and load_score >= lo)
    mech_hot = (mech_score >= hi or (prev_mech and mech_score >= lo)) and mech_ok
    if load_hot and mech_hot:
        return "critical"
    if load_hot:
        return "overreaching"
    if mech_hot:
        return "silent"
    return "stable"


def bucket(a) -> str:
    km = max(a.distance_km or 0, 1)
    asc = (a.ascent_m or 0) / km
    desc = (a.descent_m or 0) / km
    # Net-elevation aware: a point-to-point descent (desc ≫ asc) is "klesání",
    # a net climb is "stoupání", lots of both is rolling/hilly ("kopcovitě",
    # typical of trails), and little of either is "rovina". Previously any
    # desc/km > 12 was tagged "klesání", so rolling trails were mislabelled.
    if desc - asc > 12:
        g = "down"
    elif asc - desc > 12:
        g = "up"
    elif asc + desc >= 30:
        g = "rolling"
    else:
        g = "flat"
    p = (a.duration_min or 0) / km * 60
    pb = "fast" if p < 270 else ("mod" if p < 330 else "easy")
    return f"{a.surface}|{g}|{pb}"


def bucket_label(b: str) -> str:
    s, g, p = b.split("|")
    return f"{_SURF_LABEL.get(s, s)} · {_GRADE_LABEL[g]} · {_PACE_LABEL[p]}"


# ---------------------------------------------------------------- queries
def is_run(a) -> bool:
    return (a.sport or "running") == "running"


def all_acts(db: DBSession, rid: str):
    return (
        db.query(models.Activity)
        .filter(models.Activity.runner_id == rid)
        .order_by(models.Activity.started_at.asc(), models.Activity.id.asc())
        .all()
    )


def acts(db: DBSession, rid: str):
    """Running activities only — the mechanics engine (cadence, vertical ratio,
    ground contact, descent, terrain buckets) is running-specific. Cross-training
    reaches load() via all_acts()/running-equivalent km, not here."""
    return [a for a in all_acts(db, rid) if is_run(a)]


# Fallback load per minute by sport, used only when a session has neither heart
# rate nor a Garmin training load to work from.
_SPORT_LPM = {"running": 1.0, "cycling": 0.85, "swimming": 1.1, "strength": 0.7,
              "rowing": 1.0, "elliptical": 0.8, "hiking": 0.6, "walking": 0.4, "other": 0.8}


def hr_bounds(runs, dailies):
    """Estimate the runner's HR max / resting HR for TRIMP. No birth year, so
    HR max is anchored on their own hardest sessions (avg HR + margin, floor 185)
    and resting HR on the median of recorded daily readings."""
    hrs = [a.avg_hr for a in runs if a.avg_hr]
    rhrs = sorted(d.resting_hr for d in dailies if d.resting_hr)
    rhr = rhrs[len(rhrs) // 2] if rhrs else 50.0
    hrmax = max(185.0, (max(hrs) + 10) if hrs else 0.0)
    return hrmax, rhr


def session_load(a, hrmax: float = 190.0, rhr: float = 50.0) -> float:
    """One session's training load in arbitrary units (AU) — the standard
    HR-based load (Banister TRIMP) when heart rate is present, else Garmin's own
    training load, else duration × a per-sport intensity. Sport-agnostic, so
    running and cross-training land on one comparable load scale."""
    dur = a.duration_min or 0
    if dur <= 0:
        return 0.0
    if a.avg_hr and hrmax > rhr:
        hrr = min(max((a.avg_hr - rhr) / (hrmax - rhr), 0.0), 1.0)
        return dur * hrr * 0.64 * math.exp(1.92 * hrr)
    if a.training_load:
        return float(a.training_load)
    if a.rpe:
        return dur * (a.rpe / 5.0)
    return dur * _SPORT_LPM.get(a.sport or "other", 0.8)


def daily(db: DBSession, rid: str, n: int):
    cutoff = day_ago(n)
    return (
        db.query(models.DailyMetric)
        .filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date > cutoff)
        .order_by(models.DailyMetric.date.asc())
        .all()
    )


# ---------------------------------------------------------------- drift-z core
_V2_HALFLIFE = 10.0     # days — recency half-life for the v2 recent aggregate [Calibrate]
_V2_EWMA_LAMBDA = 0.3   # EWMA weight on the newest session (spec S7) [Calibrate]
_V2_EWMA_L = 2.5        # control-limit width in σ_DI (spec S7) [Calibrate]
_V2_DELTA = 0.5         # "possible deviation" threshold, typical-error units [Calibrate]
_V2_CLEAR = 1.0         # "clear deviation" threshold, typical-error units [Calibrate]


def _ewma_flag(dis):
    """Across-session EWMA control chart over a per-session drift-index series
    (oldest→newest, in typical-error units). Returns the smoothed drift `z` plus
    the persistence/convergence label fields, or None if the series is empty.
    Shared by the per-run drift core and the Phase-5 segment path."""
    if not dis:
        return None
    e = 0.0
    for d in dis:
        e = _V2_EWMA_LAMBDA * d + (1 - _V2_EWMA_LAMBDA) * e
    sigma = mad_sd(dis) or sd(dis) or 1.0
    ctrl = _V2_EWMA_L * sigma * math.sqrt(_V2_EWMA_LAMBDA / (2 - _V2_EWMA_LAMBDA))
    last3 = dis[-3:]
    dom = 1 if sum(x > 0 for x in last3) >= 2 else (-1 if sum(x < 0 for x in last3) >= 2 else 0)
    return {
        "z": r2(e), "ewma": r2(e), "latest": r2(dis[-1]), "ctrl": r2(ctrl), "nSessions": len(dis),
        "beyond": abs(e) > ctrl,
        "persist": dom != 0 and e * dom > 0,
        "state": "clear" if abs(e) >= _V2_CLEAR else ("possible" if abs(e) >= _V2_DELTA else "usual"),
    }


def _drift_z_core(A, field, recent_days):
    """Per-terrain-bucket drift of `field`: recent vs the runner's own baseline.

    v1 (standard): recent value = flat mean over the whole recent window, noise
    scale = baseline SD. A small change gets averaged away by older recent runs
    and the SD is inflated by outliers, so only a large shift crosses.

    v2 (sensitive): recent value = recency-weighted mean (10-day half-life) so a
    fresh change dominates instead of being diluted; noise scale = robust MAD so
    a genuinely small-but-consistent shift still clears; baseline excludes pain
    periods so the norm doesn't quietly absorb the drift. Same output shape."""
    v2 = _emode() == "v2"
    lo, hi = day_ago(BASE_FROM), day_ago(BASE_TO)
    base = [a for a in A if a.started_at <= hi and a.started_at > lo and getattr(a, field) is not None]
    if v2:
        excl = _eexcl()
        if excl:
            trimmed = [a for a in base if a.started_at[:10] not in excl]
            if len(trimmed) >= 6:  # only apply if enough baseline survives
                base = trimmed
    rec_cut = day_ago(recent_days)
    rec = [a for a in A if a.started_at > rec_cut and getattr(a, field) is not None]
    if len(base) < 6 or len(rec) < 3:
        return None
    by_b: dict[str, list[float]] = {}
    rec_b: dict[str, list] = {}
    for a in base:
        by_b.setdefault(bucket(a), []).append(getattr(a, field))
    for a in rec:
        rec_b.setdefault(bucket(a), []).append(a)
    today_iso = iso_date(today_date())
    num, den, n_scored = 0.0, 0.0, 0
    detail = []
    for b, recs in rec_b.items():
        bv = by_b.get(b)
        if not bv or len(bv) < 3:
            continue
        recvals = [getattr(a, field) for a in recs]
        if v2:
            center = median(bv)
            s = max(mad_sd(bv), sd(bv) * 0.5, abs(center) * 0.012)
            ws = [0.5 ** (max(0, days_between(a.started_at, today_iso)) / _V2_HALFLIFE) for a in recs]
            wsum = sum(ws) or 1.0
            now_val = sum(w * v for w, v in zip(ws, recvals)) / wsum
            weight = wsum  # recency mass — a bucket with a very recent run gets more say
        else:
            center = mean(bv)
            s = max(sd(bv), abs(center) * 0.012)
            now_val = mean(recvals)
            weight = len(recs)
        # Clamp per-bucket z so one degenerate bucket (near-constant baseline, or
        # an outlier/mislabelled run-walk) can't dominate the weighted drift.
        z = clamp((now_val - center) / s, -4, 4) if s else 0
        detail.append({
            "bucket": b, "label": bucket_label(b), "z": r2(z),
            "base": r2(center), "now": r2(now_val), "nBase": len(bv), "nNow": len(recs),
        })
        num += z * weight
        den += weight
        n_scored += len(recs)
    if not den:
        return None
    detail.sort(key=lambda d: -d["z"])
    series = [getattr(a, field) for a in A if getattr(a, field) is not None][-26:]
    base_center = median if v2 else mean
    out = {
        "z": r2(num / den), "buckets": len(detail), "nRecent": n_scored, "detail": detail,
        "baseMean": r2(base_center([getattr(a, field) for a in base])),
        "recMean": r2(mean([getattr(a, field) for a in rec])),
        "series": series,
    }
    if v2:
        # --- Phase 2: across-session EWMA + persistence/convergence -----------
        # Build a per-session drift index (oldest→newest) in the runner's own
        # typical-error units, only for sessions in a familiar terrain bucket
        # (domain-of-applicability — unfamiliar conditions are "not scored").
        base_stats = {}
        for b, bv in by_b.items():
            if len(bv) < 3:
                continue
            c = median(bv)
            base_stats[b] = (c, max(mad_sd(bv), sd(bv) * 0.5, abs(c) * 0.012))
        dis = []
        for a in sorted(rec, key=lambda a: a.started_at):
            st = base_stats.get(bucket(a))
            if not st or not st[1]:
                continue
            dis.append(clamp((getattr(a, field) - st[0]) / st[1], -4, 4))
        flag = _ewma_flag(dis)
        if flag:
            out.update(flag)
    return out


def drift_z(db: DBSession, rid: str, field: str, recent_days: int = RECENT):
    return _drift_z_core(acts(db, rid), field, recent_days)


def tavr(db: DBSession, rid: str):
    return drift_z(db, rid, "vert_ratio_pct")


def gct_drift(db: DBSession, rid: str):
    A = [a for a in acts(db, rid) if a.gct_ms is not None and a.cadence_spm]
    base = [a for a in A if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM)]
    if len(base) < 6:
        return None
    cad_base = mean([a.cadence_spm for a in base])
    A2 = [
        SimpleNamespace(
            distance_km=a.distance_km, descent_m=a.descent_m, ascent_m=a.ascent_m,
            duration_min=a.duration_min, surface=a.surface, started_at=a.started_at,
            gct_adj=(a.gct_ms * (a.cadence_spm / cad_base)) if cad_base else None,
        )
        for a in A
    ]
    return _drift_z_core(A2, "gct_adj", 14)


def duty_factor(db: DBSession, rid: str):
    """v0.5 — duty factor = ground contact / stride time (both derived from
    contact time and cadence the watch already gives). A recognized profile
    marker; shown as a terrain-cleaned drift metric but *not* scored separately,
    since it's a deterministic function of GCT and cadence that already feed the
    mechanical drift score (would double-count)."""
    A = [a for a in acts(db, rid) if a.gct_ms and a.cadence_spm]
    A2 = [
        SimpleNamespace(
            distance_km=a.distance_km, descent_m=a.descent_m, ascent_m=a.ascent_m,
            duration_min=a.duration_min, surface=a.surface, started_at=a.started_at,
            duty=a.gct_ms * a.cadence_spm / 120000.0,  # GCT / stride-time (both legs)
        )
        for a in A
    ]
    return _drift_z_core(A2, "duty", RECENT)


def run_compare(db: DBSession, rid: str, aid: int | None = None):
    """A single run's key metrics next to the runner's own baseline *as of that
    run's day* and the baseline a month before that day — so both how the run
    sits on the norm and how the norm itself drifted are visible. Baselines are
    always relative to the run's date, so any run in history is comparable.
    Baseline = mean in the same terrain bucket over the 84→29-day window before
    the run; the earlier one shifts that window +30 d. Falls back to all-terrain
    when the exact bucket is too thin. `aid=None` → the most recent run."""
    A = acts(db, rid)
    if not A:
        return None
    run = next((x for x in A if x.id == aid), None) if aid is not None else A[-1]
    if run is None:
        return None
    b = bucket(run)
    rd = datetime.fromisoformat(run.started_at[:10]).date()
    ds = lambda n: iso_date(rd - timedelta(days=n))
    win = lambda lo, hi: [x for x in A if lo < x.started_at[:10] <= hi]
    base_now = win(ds(BASE_FROM), ds(BASE_TO))          # 84→29 d before the run
    base_1mo = win(ds(BASE_FROM + 30), ds(BASE_TO + 30))  # a month earlier

    def bmean(rows, field):
        bv = [getattr(x, field) for x in rows if getattr(x, field) is not None and bucket(x) == b]
        terrain = len(bv) >= 3
        vals = bv if terrain else [getattr(x, field) for x in rows if getattr(x, field) is not None]
        return (mean(vals), len(vals), terrain) if vals else (None, 0, False)

    defs = [("pace_s_km", "Tempo", "s/km", 0), ("cadence_spm", "Kadence", "spm", 0),
            ("stride_len_m", "Délka kroku", "m", 2), ("vert_ratio_pct", "Vertikální poměr", "%", 1),
            ("gct_ms", "Kontakt se zemí", "ms", 0), ("vert_osc_cm", "Vertikální oscilace", "cm", 1)]
    metrics = []
    for field, label, unit, dec in defs:
        v = getattr(run, field)
        if v is None:
            continue
        bn, nn, tn = bmean(base_now, field)
        b1, n1, _ = bmean(base_1mo, field)
        metrics.append({
            "key": field, "label": label, "unit": unit, "dec": dec,
            "value": round(v, dec) if dec else round(v),
            "baseNow": round(bn, dec) if bn is not None else None, "nNow": nn, "terrain": tn,
            "base1mo": round(b1, dec) if b1 is not None else None, "n1mo": n1,
        })
    return {
        "id": run.id, "date": run.started_at, "title": run.title, "surface": run.surface,
        "bucketLabel": bucket_label(b), "distanceKm": run.distance_km,
        "paceSKm": rnd(run.pace_s_km) if run.pace_s_km else None, "metrics": metrics,
    }


def gait_cv(db: DBSession, rid: str):
    """v0.5 — run-to-run gait *variability*, distinct from the mean drift the
    other mechanics signals track. Uses cadence-normalized ground contact, and
    subtracts each run's terrain-bucket baseline so only scatter around the
    runner's own norm remains. A rising SD of that residual (recent vs baseline)
    flags less consistent mechanics — an early neuromuscular-fatigue / compensation
    marker that appears before the average itself moves.

    (Caveat: it's session-to-session variability from per-run averages, not the
    within-run stride-to-stride CV of lab studies — we don't get per-stride
    streams from the summary API. It's the closest wearable-friendly proxy.)"""
    A = [a for a in acts(db, rid) if a.gct_ms and a.cadence_spm]
    base = [a for a in A if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM)]
    if len(base) < 8:
        return None
    cad_base = mean([a.cadence_spm for a in base])
    adj = lambda a: a.gct_ms * (a.cadence_spm / cad_base)
    by_b: dict[str, list[float]] = {}
    for a in base:
        by_b.setdefault(bucket(a), []).append(adj(a))
    bmean = {b: mean(v) for b, v in by_b.items()}
    resid = lambda a: (adj(a) - bmean[bucket(a)]) if bucket(a) in bmean else None
    base_res = [r for r in (resid(a) for a in base) if r is not None]
    rec = [a for a in A if a.started_at > day_ago(RECENT)]
    rec_res = [r for r in (resid(a) for a in rec) if r is not None]
    if len(base_res) < 6 or len(rec_res) < 4:
        return None
    sd_base, sd_now = sd(base_res), sd(rec_res)
    ratio = (sd_now / sd_base) if sd_base else None
    return {"sdNow": r1(sd_now), "sdBase": r1(sd_base), "ratio": r2(ratio) if ratio is not None else None, "n": len(rec_res)}


def balance(db: DBSession, rid: str):
    A = [a for a in acts(db, rid) if a.gct_balance_l is not None]
    base = [a for a in A if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM)]
    rec = [a for a in A if a.started_at > day_ago(14)]
    if len(base) < 6 or len(rec) < 3:
        return None
    bm, rm = mean([a.gct_balance_l for a in base]), mean([a.gct_balance_l for a in rec])
    return {
        "baseline": r2(bm), "now": r2(rm), "excursion": r2(abs(rm - bm)),
        "side": "levá" if rm < bm else "pravá",
        "direction": "kratší kontakt vlevo — pravá noha nese déle" if rm < bm
        else "kratší kontakt vpravo — levá noha nese déle",
        "series": [a.gct_balance_l for a in A[-26:]],
    }


# 2.5%-wide gradient bands, 0-30% then a >=30% catch-all, per the request
# this replaces a flat "total descent meters" figure with: how much of that
# descent happened on genuinely steep terrain, which loads the quads
# eccentrically far more per meter than a gentle rolling descent does.
GRADIENT_LABELS = [
    "0–2,5 %", "2,5–5 %", "5–7,5 %", "7,5–10 %", "10–12,5 %", "12,5–15 %", "15–17,5 %",
    "17,5–20 %", "20–22,5 %", "22,5–25 %", "25–27,5 %", "27,5–30 %", "30 %+",
]
STEEP_BUCKET_FROM = 4  # index of the 10-12.5% band — buckets from here up count as "steep"


def _gradient_bucket_index(pct: float) -> int:
    idx = int(pct // 2.5)
    return min(idx, len(GRADIENT_LABELS) - 1)


def _descent_gradient_totals(activities) -> list[float]:
    buckets = [0.0] * len(GRADIENT_LABELS)
    for a in activities:
        profile = a.elevation_profile
        if not profile:
            continue
        for i in range(len(profile) - 1):
            d0, alt0 = profile[i]["distance_m"], profile[i]["altitude_m"]
            d1, alt1 = profile[i + 1]["distance_m"], profile[i + 1]["altitude_m"]
            seg_dist = d1 - d0
            if seg_dist <= 0:
                continue
            drop = alt0 - alt1
            if drop <= 0:
                continue  # ascending or flat segment
            pct = drop / seg_dist * 100
            buckets[_gradient_bucket_index(pct)] += drop
    return buckets


def descent_by_gradient(db: DBSession, rid: str):
    A = [a for a in acts(db, rid) if a.elevation_profile]
    recent = [a for a in A if a.started_at > day_ago(7)]
    base = [a for a in A if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM)]
    if not recent and not base:
        return None
    recent_buckets = _descent_gradient_totals(recent)
    base_buckets = _descent_gradient_totals(base)
    recent_total = sum(recent_buckets)
    steep_recent = sum(recent_buckets[STEEP_BUCKET_FROM:])
    steep_base_weekly = sum(base_buckets[STEEP_BUCKET_FROM:]) / 8  # ~8-week baseline window, per-week average
    spike = r2(steep_recent / steep_base_weekly) if steep_base_weekly > 5 else None
    return {
        "buckets": [rnd(b) for b in recent_buckets], "labels": GRADIENT_LABELS,
        "total7": rnd(recent_total), "steep7": rnd(steep_recent),
        "steepBaseWeekly": rnd(steep_base_weekly), "steepSpike": spike,
        "nActivities7": len(recent),
    }


def decouple(db: DBSession, rid: str):
    A = [a for a in acts(db, rid) if a.vr_thirds and a.duration_min and a.duration_min >= 45]
    A = sorted(A, key=lambda a: a.started_at)[-8:]
    if len(A) < 4:
        return None
    vals = [r1((a.vr_thirds[2] / a.vr_thirds[0] - 1) * 100) for a in A]
    return {"series": vals, "dates": [a.started_at for a in A], "latest": vals[-1], "trend": r2(slope(vals)), "n": len(vals)}


def load(db: DBSession, rid: str):
    A = acts(db, rid)                    # running only — km volume bars, descent, mechanics
    ALL = all_acts(db, rid)              # every sport — drives systemic training load
    CROSS = [a for a in ALL if not is_run(a)]
    hrmax, rhr = hr_bounds(A, daily(db, rid, 180))
    sl = lambda a: session_load(a, hrmax, rhr)

    # A session counts as high-intensity when its average HR sits at ≥80 % of
    # heart-rate reserve (≈ threshold / Z4+) — a hard tempo/interval effort.
    def hi(a):
        return bool(a.avg_hr) and hrmax > rhr and (a.avg_hr - rhr) / (hrmax - rhr) >= 0.80

    daily_km = []       # running km per day (volume view)
    daily_load = []     # training load (AU) per day across ALL sports (drives the load axis)
    daily_hi = []       # high-intensity training load (AU) per day (drives HI-ACWR)
    for d in range(55, -1, -1):
        k = day_ago(d)
        daily_km.append(sum(a.distance_km or 0 for a in A if a.started_at == k))
        daily_load.append(sum(sl(a) for a in ALL if a.started_at == k))
        daily_hi.append(sum(sl(a) for a in ALL if a.started_at == k and hi(a)))

    def ewma(arr, n):
        lam = 2 / (n + 1)
        seed = arr[: min(3, len(arr))]
        v = mean(seed)
        for x in arr:
            v = x * lam + v * (1 - lam)
        return v

    # The load axis (acute/chronic/ratio/monotony/strain) is expressed in the
    # usual training-load units (AU) across every sport — running and
    # cross-training on one scale. The km bars below are pure running volume.
    acute = ewma(daily_load[-14:], 7) * 7
    chronic = ewma(daily_load, 28) * 7
    fitness42 = ewma(daily_load, 42) * 7  # v0.4: Banister-style "fitness" arm, see tsb
    # v0.5: high-intensity exposure ACWR — a spike of hard efforts on top of a
    # low chronic hard base is riskier than the same total load spread easy.
    hi_acute = ewma(daily_hi[-14:], 7) * 7
    hi_chronic = ewma(daily_hi, 28) * 7
    hi_ratio = r2(hi_acute / max(hi_chronic, 0.15 * chronic, 1))
    # v0.5: load "creep" — acute load now vs. two weeks ago. Catches slow,
    # persistent build-ups the spike thresholds miss (literature: even small
    # fortnightly ACWR rises precede injury).
    prior = daily_load[:-14]
    acute_2w = ewma(prior[-14:], 7) * 7 if len(prior) >= 7 else 0
    load_creep = r2(acute / acute_2w) if acute_2w > 0 else None
    # Calendar weeks (Mon–Sun), not trailing 7-day windows — the last bar is
    # the current week to date. Trailing-7 volume is reported separately as km7.
    this_mon = today_date() - timedelta(days=today_date().weekday())
    weekly = []
    week_starts = []
    weekly_run_load = []
    weekly_other_load = []
    for w in range(11, -1, -1):
        mon = this_mon - timedelta(days=7 * w)
        ms, ss = iso_date(mon), iso_date(mon + timedelta(days=6))
        in_week = [a for a in ALL if ms <= (a.started_at or "")[:10] <= ss]
        weekly.append(r1(sum(a.distance_km or 0 for a in in_week if is_run(a))))
        weekly_run_load.append(rnd(sum(sl(a) for a in in_week if is_run(a))))
        weekly_other_load.append(rnd(sum(sl(a) for a in in_week if not is_run(a))))
        week_starts.append(ms)
    last14 = daily_load[-14:]
    m14 = mean(last14)
    mono = r2(m14 / max(sd(last14), m14 * 0.12)) if m14 > 0 else 0
    active28 = sum(1 for x in daily_load[-28:] if x > 0)
    w7 = [a for a in A if a.started_at > day_ago(7)]
    desc7 = sum((a.descent_m or 0) for a in w7)
    km7 = sum(a.distance_km or 0 for a in w7)
    base_window = [a for a in A if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM)]
    desc_base = sum((a.descent_m or 0) for a in base_window) / 8
    hilly = km7 > 0 and (desc7 / km7) >= 12

    # Cross-training rollup (training load AU) for the "jiný sport" breakdown card.
    cross7 = [a for a in CROSS if a.started_at > day_ago(7)]
    run_load7 = sum(sl(a) for a in w7)
    cross_load7 = sum(sl(a) for a in cross7)
    # v0.6 — internal load via session-RPE (Foster): more sensitive than HR for
    # acute load change (IOC 2016) and the one common unit for cross-training and
    # HR-less sessions. session_load() already falls back to it; surfaced here too.
    srpe7 = sum((a.rpe or 0) * (a.duration_min or 0) for a in ALL if a.started_at > day_ago(7) and a.rpe)
    _SPORT_CS = {"cycling": "kolo", "swimming": "plavání", "strength": "silový trénink",
                 "rowing": "veslování", "elliptical": "orbitrek", "hiking": "turistika",
                 "walking": "chůze", "other": "jiný sport"}
    cross_list = [
        {"sport": a.sport, "sportLabel": _SPORT_CS.get(a.sport or "other", a.sport or "jiný sport"),
         "date": a.started_at, "title": a.title, "durationMin": rnd(a.duration_min or 0),
         "avgHr": rnd(a.avg_hr) if a.avg_hr else None,
         "load": rnd(sl(a))}
        for a in sorted(cross7, key=lambda x: x.started_at, reverse=True)
    ]

    # v0.6.1 — single-session spike now combines EXTERNAL (distance) and INTERNAL
    # (effort / TRIMP) load and takes the worse of the two. BJSM 2025 (n=5205)
    # established the distance spike as the load-axis spine; Neal 2024 — on the same
    # consumer-wristwatch data Došlap ingests — found acute *effort* load, not
    # distance, was the one variable that predicted injury, and Paquette 2020 argues
    # load must combine external + internal. So a run that spikes in either
    # dimension (vs the worst run of the prior 30 days) counts.
    runs = sorted([a for a in A if (a.distance_km or 0) > 0], key=lambda a: a.started_at)
    today = today_date()
    # v2 (Phase 3): Minetti grade-adjusted distance per run — flat-equivalent km,
    # so a hilly run's true cost feeds the spike, not just its raw distance.
    _v2 = _emode() == "v2"
    _ga = {id(a): terrain.grade_adjusted_km(a.elevation_profile, a.distance_km or 0) for a in runs} if _v2 else {}

    def _sess_spikes(a):
        d0 = a.started_at[:10]
        lo = iso_date(date.fromisoformat(d0) - timedelta(days=30))
        prior = [x for x in runs if lo <= x.started_at[:10] < d0]
        if len(prior) < 3:
            return None
        dist_r = (a.distance_km or 0) / max(x.distance_km for x in prior)
        prior_eff = [sl(x) for x in prior if sl(x) > 0]
        eff = sl(a)
        eff_r = (eff / max(prior_eff)) if (prior_eff and eff > 0) else 0.0
        ga_r = 0.0
        if _v2:
            prior_ga = [_ga[id(x)] for x in prior if _ga.get(id(x), 0) > 0]
            ga_r = (_ga[id(a)] / max(prior_ga)) if (prior_ga and _ga.get(id(a), 0) > 0) else 0.0
        return (max(dist_r, eff_r, ga_r), dist_r, eff_r, ga_r)  # combined, distance, effort, grade-adj

    def _days_ago(a):
        return (today - date.fromisoformat(a.started_at[:10])).days

    spikes = []
    for a in runs:
        d = _days_ago(a)
        if d <= 28:
            r = _sess_spikes(a)
            if r is not None:
                spikes.append((a, r, d))
    # Acute spike: the riskiest single run in the last 7 days, in either dimension.
    acute_spikes = [(a, r) for (a, r, d) in spikes if d <= 7]
    if acute_spikes:
        sess_spike_a, best = max(acute_spikes, key=lambda t: t[1][0])
        sess_spike = best[0]
        # basis = whichever component (distance / effort / grade-adjusted terrain)
        # drove the spike; "obojí" when the top two are within 0.08 of each other.
        comps = [("vzdálenost", best[1]), ("intenzita", best[2]), ("převýšení", best[3])]
        comps.sort(key=lambda kv: -kv[1])
        sess_spike_basis = comps[0][0] if (comps[0][1] - comps[1][1] >= 0.08) else "obojí"
    else:
        sess_spike_a, sess_spike, sess_spike_basis = None, None, None
    # Latent memory: a big spike 8-28 days ago still elevates risk (IOC 2016 —
    # injury likelihood peaks in the 1-4 weeks *after* a rapid load rise), decaying
    # linearly to zero at 28 days. Only spikes older than the acute window.
    latent = 0.0
    latent_days = None
    for a, r, d in spikes:
        s = r[0]
        if d > 7 and s > 1.3:
            decayed = (s - 1.3) * max(0.0, (28 - d) / 21)
            if decayed > latent:
                latent, latent_days = decayed, d
    # Pace spike (distinct injury mechanism — Nielsen 2014 maps sudden *pace*
    # rises to Achilles/plantar/tibial, vs *distance* to knee/shin). Fastest run
    # in the last 7 days vs. the runner's median pace over the prior 30 days.
    def _pace(a):
        return (a.duration_min or 0) / (a.distance_km or 1) * 60
    recent_pace = [_pace(a) for a in runs if _days_ago(a) <= 7 and (a.duration_min or 0) > 0]
    base_pace = sorted(_pace(a) for a in runs if 7 < _days_ago(a) <= 37 and (a.duration_min or 0) > 0)
    pace_spike = None
    if recent_pace and len(base_pace) >= 3:
        med = base_pace[len(base_pace) // 2]
        fastest = min(recent_pace)  # lower s/km = faster
        if med > 0 and fastest < med:
            pace_spike = r2(med / fastest)  # >1 means ran faster than usual

    return {
        "acute": rnd(acute), "chronic": rnd(chronic), "weekly": weekly, "weekStarts": week_starts,
        "weekKm": weekly[-1] if weekly else 0, "daily": daily_km[-28:],
        "ratio": r2(acute / chronic) if chronic > 0 else None, "valid": chronic > 0 and active28 >= 8,
        "monotony": mono, "strain": rnd(m14 * 7 * mono), "loadUnit": "AU",
        # cross-training folded into the load axis above, expressed in AU
        "runKm7": r1(km7), "runLoad7": rnd(run_load7), "crossLoad7": rnd(cross_load7), "sRPE7": rnd(srpe7),
        "crossCount7": len(cross7), "crossList": cross_list,
        "weeklyRunLoad": weekly_run_load, "weeklyOtherLoad": weekly_other_load,
        "descent7": rnd(desc7), "descentBase": rnd(desc_base),
        "descentSpike": r2(desc7 / desc_base) if (hilly and desc_base > 150) else None,
        "descentPerKm": rnd(desc7 / km7) if km7 else 0,
        # v0.4
        "fitness42": rnd(fitness42),
        "tsbBalance": rnd(fitness42 - acute),
        # v0.5 — high-intensity exposure + load creep
        "hiAcute": rnd(hi_acute), "hiChronic": rnd(hi_chronic), "hiRatio": hi_ratio,
        "loadCreep": load_creep,
        # v0.6 — single-session paradigm: acute spike, 28-day latent memory, pace spike
        "sessionSpike": r2(sess_spike) if sess_spike is not None else None,
        "sessionSpikeKm": r1(sess_spike_a.distance_km) if sess_spike_a else None,
        "sessionSpikeAt": sess_spike_a.started_at if sess_spike_a else None,
        "sessionSpikeBasis": sess_spike_basis,  # v0.6.1 — distance / effort / both
        "spikeLatent": r2(latent) if latent > 0 else None,
        "spikeLatentDaysAgo": latent_days,
        "paceSpike": pace_spike,
        # safe single-session ceiling: ~10% over the longest run of the last 30d
        "safeLongRunKm": r1(max([a.distance_km for a in runs if _days_ago(a) <= 30], default=0) * 1.1) or None,
        # v2 Phase 3 — terrain-aware load from the elevation profile (None when no
        # profile, e.g. summary-only Garmin imports).
        "gradeAdjKm7": (lambda g: r1(g) if g else None)(sum(terrain.grade_adjusted_km(a.elevation_profile, a.distance_km or 0) for a in w7 if a.elevation_profile)),
        "downhillKm7": (lambda d: r1(d) if d else None)(sum(terrain.downhill_exposure(a.elevation_profile)[0] for a in w7 if a.elevation_profile)),
    }


def aerobic(db: DBSession, rid: str):
    cutoff = day_ago(21)
    A = [a for a in acts(db, rid) if a.hr_thirds and a.pace_thirds and a.started_at > cutoff]
    A = sorted(A, key=lambda a: a.started_at)[-5:]
    if len(A) < 3:
        return None
    v = [r1((a.hr_thirds[2] / a.pace_thirds[2]) / (a.hr_thirds[0] / a.pace_thirds[0]) * 100 - 100) for a in A]
    return {"latest": v[-1], "mean": r1(mean(v)), "series": v}


def recovery(db: DBSession, rid: str):
    rec = daily(db, rid, 7)
    base = (
        db.query(models.DailyMetric)
        .filter(
            models.DailyMetric.runner_id == rid,
            models.DailyMetric.date <= day_ago(7),
            models.DailyMetric.date > day_ago(35),
        )
        .all()
    )
    if len(rec) < 4 or len(base) < 14:
        return None

    def f(arr, k):
        return [getattr(d, k) for d in arr if getattr(d, k) is not None]

    hrv_b, hrv_r = f(base, "hrv_ms"), f(rec, "hrv_ms")
    rhr_b, rhr_r = f(base, "resting_hr"), f(rec, "resting_hr")
    sl_b, sl_r = f(base, "sleep_h"), f(rec, "sleep_h")
    hrv_z = r2((mean(hrv_r) - mean(hrv_b)) / sd(hrv_b)) if sd(hrv_b) else 0
    rhr_z = r2((mean(rhr_r) - mean(rhr_b)) / sd(rhr_b)) if sd(rhr_b) else 0
    sleep_debt = r1((mean(sl_b) - mean(sl_r)) * 7)

    # A single lay-readable "regenerace" score (0-100, 50 = your own baseline).
    # It's an *overnight* reading: each night's own HRV / resting HR / sleep
    # z-scored against the 28-day baseline, so the score — and the day-over-day
    # delta — actually move night to night. (The earlier version scored a 7-day
    # rolling mean, so two consecutive days shared 6 nights and the delta was
    # always ~0.) rhr is inverted: an elevated resting HR is the bad direction.
    hbm, hsd = mean(hrv_b), sd(hrv_b)
    rbm, rsd = mean(rhr_b), sd(rhr_b)
    sbm, ssd = mean(sl_b), sd(sl_b)

    def night_score(d):
        comps, n = 0.0, 0
        if d.hrv_ms is not None and hsd:
            comps += (d.hrv_ms - hbm) / hsd; n += 1
        if d.resting_hr is not None and rsd:
            comps += -(d.resting_hr - rbm) / rsd; n += 1
        if d.sleep_h is not None and ssd:
            comps += (d.sleep_h - sbm) / ssd; n += 1
        if n == 0:
            return None
        return int(clamp(round(50 + (comps / n) * 20), 0, 100))

    def label_of(s):
        return "Nadprůměrná" if s >= 65 else "Obvyklá" if s >= 40 else "Snížená" if s >= 20 else "Potlačená"

    # Two most recent nights that have any data → today's score and the delta.
    nights = sorted(daily(db, rid, 14), key=lambda d: d.date, reverse=True)
    scored = [(d.date, night_score(d)) for d in nights]
    scored = [(dt, s) for dt, s in scored if s is not None]
    score = scored[0][1] if scored else 50
    score_date = scored[0][0] if scored else None
    label = label_of(score)
    score_prev = scored[1][1] if len(scored) > 1 else None
    score_delta = (score - score_prev) if score_prev is not None else None

    return {
        "hrv": {"base": r1(mean(hrv_b)), "now": r1(mean(hrv_r)), "z": hrv_z, "series": hrv_r},
        "rhr": {"base": r1(mean(rhr_b)), "now": r1(mean(rhr_r)), "z": rhr_z, "series": rhr_r},
        "sleep": {"base": r1(mean(sl_b)), "now": r1(mean(sl_r)), "debt": sleep_debt, "series": sl_r},
        "edited": len([d for d in rec if d.source == "manual"]),
        "score": score, "scoreLabel": label, "scoreDate": score_date,
        "scorePrev": score_prev, "scoreDelta": score_delta,
    }


def hrv_cv(db: DBSession, rid: str):
    """v0.4 — HRV day-to-day coefficient of variation (volatility), distinct
    from `recovery().hrv` which tracks the mean level. Compares CV over the
    last 7 days to CV over the preceding 28-day window."""
    rec = daily(db, rid, 7)
    base = (
        db.query(models.DailyMetric)
        .filter(
            models.DailyMetric.runner_id == rid,
            models.DailyMetric.date <= day_ago(7),
            models.DailyMetric.date > day_ago(35),
        )
        .all()
    )
    hrv_r = [d.hrv_ms for d in rec if d.hrv_ms is not None]
    hrv_b = [d.hrv_ms for d in base if d.hrv_ms is not None]
    if len(hrv_r) < 4 or len(hrv_b) < 14:
        return None
    cv_now = (sd(hrv_r) / mean(hrv_r) * 100) if mean(hrv_r) else 0
    cv_base = (sd(hrv_b) / mean(hrv_b) * 100) if mean(hrv_b) else 0
    ratio = (cv_now / cv_base) if cv_base else None
    return {"cvNow": r1(cv_now), "cvBase": r1(cv_base), "ratio": r2(ratio) if ratio is not None else None}


def sleep_regularity(db: DBSession, rid: str):
    """v0.4 — variability of sleep *duration* (not clock-time onset/wake, the
    schema doesn't have those) over 14 days vs a 35-day baseline window."""
    rec = daily(db, rid, 14)
    base = (
        db.query(models.DailyMetric)
        .filter(
            models.DailyMetric.runner_id == rid,
            models.DailyMetric.date <= day_ago(14),
            models.DailyMetric.date > day_ago(49),
        )
        .all()
    )
    sl_r = [d.sleep_h for d in rec if d.sleep_h is not None]
    sl_b = [d.sleep_h for d in base if d.sleep_h is not None]
    if len(sl_r) < 6 or len(sl_b) < 14:
        return None
    sd_now, sd_base = sd(sl_r), sd(sl_b)
    ratio = (sd_now / sd_base) if sd_base else None
    return {"sdNow": r1(sd_now), "sdBase": r1(sd_base), "ratio": r2(ratio) if ratio is not None else None}


def sleep_efficiency(db: DBSession, rid: str):
    """v0.5 — sleep efficiency = time asleep / time in bed (imported from the
    watch). Low efficiency (fragmented sleep / long time awake) is linked to
    higher musculoskeletal injury risk beyond raw duration. Reports the recent
    7-day mean and the runner's own 28-day baseline. None when not imported
    (older data / devices that don't expose it)."""
    rec = [d.sleep_efficiency for d in daily(db, rid, 7) if d.sleep_efficiency is not None]
    base = (
        db.query(models.DailyMetric)
        .filter(
            models.DailyMetric.runner_id == rid,
            models.DailyMetric.date <= day_ago(7),
            models.DailyMetric.date > day_ago(35),
            models.DailyMetric.sleep_efficiency.isnot(None),
        )
        .all()
    )
    base_v = [d.sleep_efficiency for d in base]
    if len(rec) < 3:
        return None
    return {"now": r2(mean(rec)), "base": r2(mean(base_v)) if base_v else None, "n": len(rec)}


def feedback(db: DBSession, rid: str):
    fb = (
        db.query(models.ActivityFeedback)
        .filter(models.ActivityFeedback.runner_id == rid)
        .order_by(models.ActivityFeedback.submitted_at.asc())
        .all()
    )
    cutoff = day_ago(21)
    rec = [f for f in fb if f.submitted_at > cutoff]
    if not rec:
        return None
    niggles = [f for f in rec if f.niggle]
    sites: dict[str, int] = {}
    for f in niggles:
        if f.pain_site:
            sites[f.pain_site] = sites.get(f.pain_site, 0) + 1
    top_site = max(sites.items(), key=lambda kv: kv[1]) if sites else None
    feels = [f.feeling for f in rec if f.feeling is not None]
    pains = [f.pain_during or 0 for f in rec]
    return {
        "n": len(rec), "total": len(fb), "niggleCount": len(niggles),
        "niggleRate": r2(len(niggles) / len(rec)),
        "topSite": {"site": top_site[0], "n": top_site[1]} if top_site else None,
        "feelingMean": r1(mean(feels)), "feelingTrend": r2(slope(feels)),
        "painMax": max(pains) if pains else 0,
        "recent": [to_dict(f) for f in rec[-8:]],
    }


def stiffness_pattern(db: DBSession, rid: str):
    """v0.5 — self-reported pre-run leg stiffness, gathered retrospectively
    at rating time ("how stiff were your legs before this run"), tracked
    over time. Rising stiffness alone is a symptom signal like any other;
    the more specific pattern this looks for is stiffness the runner trained
    hard through anyway (RPE>=6) — an inability to back off when the body's
    already signalling, not just the signal itself."""
    fb = (
        db.query(models.ActivityFeedback)
        .filter(models.ActivityFeedback.runner_id == rid, models.ActivityFeedback.stiffness_pre.isnot(None))
        .order_by(models.ActivityFeedback.submitted_at.asc())
        .all()
    )
    cutoff = day_ago(21)
    rec = [f for f in fb if f.submitted_at > cutoff]
    if len(rec) < 4:
        return None
    vals = [f.stiffness_pre for f in rec]
    stiff_high = [f for f in rec if f.stiffness_pre >= 4]
    pushed_through = [f for f in stiff_high if (f.rpe or 0) >= 6]
    ignore_rate = r2(len(pushed_through) / len(stiff_high)) if stiff_high else None
    return {
        "mean": r1(mean(vals)), "trend": r2(slope(vals)), "n": len(rec),
        "highCount": len(stiff_high), "pushedThroughCount": len(pushed_through), "ignoreRate": ignore_rate,
        "series": vals[-14:],
    }


_REGION_LABEL = {
    "achilles": "Achillova šlacha", "calf": "lýtko", "shin": "holeň", "knee": "koleno",
    "hamstring": "hamstring", "quad": "kvadriceps", "hip": "kyčel", "glute": "hýždě",
    "foot": "chodidlo", "plantar": "plantární fascie", "ankle": "kotník", "itb": "IT pás",
    "groin": "tříslo", "lowback": "bederní páteř",
}


def _injury_site_label(rep) -> str:
    region = _REGION_LABEL.get(rep.body_region, rep.body_region) if rep.body_region else "nespecifikováno"
    side = " vpravo" if rep.body_side == "P" else (" vlevo" if rep.body_side == "L" else "")
    return f"{region}{side}"


def injury(db: DBSession, rid: str):
    """v0.6 — patient/physio-reported injury outcome (OSTRC-H severity), the
    label the whole engine will eventually be calibrated against. The most
    recent *active* report inside a 28-day window becomes a symptom-axis
    signal; a physio-confirmed report (source='physio_conclusion') carries
    evidence grade A, a self-report grade B. 'resolved'/'none' rows don't
    score but are kept and returned as the negative datapoints validation
    needs. `substantial` mirrors the OSTRC definition (reduced or lost
    participation/performance, i.e. an item at >=17)."""
    cutoff = day_ago(28)
    rows = (
        db.query(models.InjuryReport)
        .filter(models.InjuryReport.runner_id == rid, models.InjuryReport.submitted_at > cutoff)
        .order_by(models.InjuryReport.submitted_at.desc())
        .all()
    )
    if not rows:
        return None
    active = next((r for r in rows if r.status == "active" and (r.severity or 0) > 0), None)
    out = {"reports28": len(rows), "latestAt": rows[0].submitted_at, "active": None}
    if active:
        out["active"] = {
            "severity": active.severity,
            "site": _injury_site_label(active),
            "confirmed": bool(active.confirmed),
            "source": active.source,
            "substantial": (active.q_participation or 0) >= 17 or (active.q_performance or 0) >= 17,
            "at": active.submitted_at,
        }
    return out


# Lower-limb / running-overuse regions — pain here is running-relevant, unlike
# an arm or shoulder. Matched loosely against the body-map region titles.
_RUN_PAIN_KEYS = (
    "achill", "lýtk", "lytk", "holen", "holeň", "tibial", "kolen", "patel", "hamstring",
    "kvadric", "kyčl", "kyčel", "hýžd", "glute", "chodid", "plantár", "plantar", "kotník",
    "hlezen", "iliotib", "it band", "třísl", "trisl", "bérec", "nárt", "nart", "pata",
    "metatar", "adduktor", "ohýbač kyčle", "bederní", "si kloub", "prsty",
)


def _run_relevant(region) -> bool:
    r = (region or "").lower()
    return any(k in r for k in _RUN_PAIN_KEYS)


# Knee sub-zones runners can't reliably distinguish (Smits 2019) → collapse to "knee".
_KNEE_SUBZONES = {"patella", "patellar", "patellar_tendon", "patellar-tendon", "patela"}


def _norm_region(region):
    r = (region or "").strip().lower()
    return "knee" if r in _KNEE_SUBZONES else region


def pain_recurrence(db: DBSession, rid: str, window: int = 28) -> dict:
    """Dates on which each painful body region was reported across *all* self-
    reported sources — daily check-ins, run diary ratings, injury reports —
    inside the window. Localised, recurring pain (same site again and again) is
    the classic overuse pattern; the dates also let us spot pain that repeats
    within a day or two (not resolving between runs = acute overload)."""
    cut = day_ago(window)
    dates: dict[str, list[str]] = {}

    def add(region, date):
        # Smits 2019: runners locate pain reliably at the region level but knee
        # *sub-locations* are unreliable — collapse patella/patellar-tendon back to
        # "knee" so recurrence isn't split across zones a layperson can't distinguish.
        region = _norm_region(region)
        if region and date:
            dates.setdefault(region, []).append(date[:10])

    for ck in db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at > cut):
        for p in (ck.pain_points or []):
            add(p.get("region"), ck.submitted_at)
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid, models.ActivityFeedback.submitted_at > cut):
        for p in (f.pain_points or []):
            add(p.get("region"), f.submitted_at)
    for r in db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid, models.InjuryReport.submitted_at > cut):
        for p in (r.pain_points or []):
            add(p.get("region"), r.submitted_at)
    return dates


def confidence(db: DBSession, rid: str):
    A = acts(db, rid)
    if not A:
        return {"value": 0, "sessions": 0, "days": 0, "baseSessions": 0, "note": "Žádná data.", "deviceChanged": False}
    base = [
        a for a in A
        if a.started_at <= day_ago(BASE_TO) and a.started_at > day_ago(BASE_FROM) and a.vert_ratio_pct is not None
    ]
    first_day = min(a.started_at for a in A)
    days = days_between(first_day, iso_date(today_date()))
    shared = {bucket(a) for a in base}
    matched = len([a for a in A if a.started_at > day_ago(RECENT) and bucket(a) in shared])
    # Full confidence needs (a) enough matched recent sessions, (b) a *full*
    # baseline window — the window is 84→29 days ago, so history shorter than
    # BASE_FROM days only partially fills it — and (c) enough baseline runs for
    # a stable per-terrain SD. Backtesting on real data showed the old
    # days/42 term hit 1.0 at 42 days while the baseline held only ~7 runs,
    # producing a spurious z≈4 "silent drift". Requiring days/BASE_FROM and a
    # baseline-count floor suppresses that thin-baseline artifact.
    v = r2(min(1, matched / 8) * min(1, days / BASE_FROM) * min(1, len(base) / 15))

    # Vertical-oscillation-derived values aren't comparable across watch
    # models — a device swap inside the baseline window silently corrupts
    # the z-score, so it caps confidence below the mechanical-signal gate
    # regardless of how many matched sessions exist.
    device_log = (
        db.query(models.DeviceHistory).filter(models.DeviceHistory.runner_id == rid)
        .order_by(models.DeviceHistory.recorded_at.asc()).all()
    )
    device_changed = len(device_log) >= 2 and device_log[-1].recorded_at > day_ago(BASE_FROM)
    if device_changed:
        v = min(v, 0.4)

    if device_changed:
        note = "Během baseline okna došlo ke změně hodinek — mechanické signály jsou umlčené, dokud se baseline nepostaví znovu na novém zařízení."
    elif v < 0.6:
        note = "Baseline se zatím buduje — mechanické signály se nezobrazují."
    else:
        note = "Baseline je dostatečný."
    return {
        "value": v, "sessions": matched, "days": days, "baseSessions": len(base),
        "note": note, "deviceChanged": device_changed,
    }


# ---------------------------------------------------------------- assess
def _act_dict(a) -> dict:
    if a is None:
        return None
    return {
        "id": a.id, "started_at": a.started_at, "title": a.title,
        "feeling": a.feeling, "pain_during": a.pain_during, "pain_site": a.pain_site,
    }


def _v2_baseline_exclusions(db: DBSession, rid: str, after_days: int = 14, thr: int = 3) -> frozenset:
    """v2 only — ISO dates within `after_days` of a pain report >= thr/10 (daily
    check-ins + post-run feedback). Baseline runs on these dates are dropped so a
    painful period isn't quietly absorbed into the runner's norm (spec S8.4)."""
    out: set[str] = set()

    def add(d: str | None):
        if not d:
            return
        try:
            d0 = date.fromisoformat(d[:10])
        except ValueError:
            return
        for k in range(after_days + 1):
            out.add((d0 + timedelta(days=k)).isoformat())

    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid).all():
        if (c.pain_score or 0) >= thr:
            add(c.submitted_at)
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid).all():
        if (f.pain_during or 0) >= thr:
            add(f.submitted_at)
    return frozenset(out)


_SEG_FIELD2KEY = {"vratio_pct": "tavr", "gct_ms": "gct", "cadence_spm": "cadence",
                  "step_len_m": "stride", "vo_cm": "vosc"}


def segment_mechanics(db: DBSession, rid: str):
    """Phase 5 — within-run mechanics drift from stored S3 segments. Each session's
    segments are scored against the runner's own per-(surface, band) segment
    baseline (median + MAD), giving a duration-weighted session drift index that
    a per-run average would have hidden (e.g. a downhill-only drift). The series
    is smoothed by the shared EWMA. Returns per-metric results keyed by engine
    metric name, or None when there aren't enough segmented sessions yet."""
    from . import segmentation as seg
    rows = (
        db.query(models.ActivityStream.segments_json, models.Activity.started_at)
        .join(models.Activity, models.ActivityStream.activity_id == models.Activity.id)
        .filter(models.ActivityStream.runner_id == rid, models.ActivityStream.segments_json.isnot(None))
        .all()
    )
    if not rows:
        return None
    lo, hi = day_ago(BASE_FROM), day_ago(BASE_TO)
    excl = _eexcl()
    base_segs, recent = [], []
    for segs, started in rows:
        if not segs:
            continue
        d = (started or "")[:10]
        if hi >= (started or "") > lo and d not in excl:
            base_segs.extend(segs)
        if (started or "") > day_ago(RECENT):
            recent.append((started, segs))
    recent.sort(key=lambda t: t[0])
    if len(base_segs) < 15 or len(recent) < 1:
        return None
    from . import regression as reg
    stats = seg.baseline_stats(base_segs)
    if not stats:
        return None
    out = {}
    for field, key in _SEG_FIELD2KEY.items():
        # S4: prefer the continuous context regression; fall back to the
        # per-(surface, band) bucket method when there aren't enough segments.
        model = reg.fit_metric(base_segs, field)
        dis, last_by, method = [], None, "bucket"
        for _started, segs in recent:
            sd_ = reg.session_residual_drift(segs, model) if model else seg.session_drift(segs, stats, field)
            if sd_:
                dis.append(max(-4.0, min(4.0, sd_["di"])))
                last_by = sd_["byBand"]
        if model and dis:
            method = "regression"
        elif not dis:  # regression scored nothing in domain → retry with buckets
            for _started, segs in recent:
                sd_ = seg.session_drift(segs, stats, field)
                if sd_:
                    dis.append(max(-4.0, min(4.0, sd_["di"])))
                    last_by = sd_["byBand"]
        flag = _ewma_flag(dis)
        if flag and len(dis) >= 1:
            out[key] = {**flag, "byBand": last_by, "segment": True, "method": method}
    return out or None


def assess(db: DBSession, rid: str) -> dict:
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if _emode() == "v2":
        # Feed pain-period exclusions to the mechanics drift core for this scope.
        _engine_ctx.excl = _v2_baseline_exclusions(db, rid)
    conf = confidence(db, rid)
    L = load(db, rid)
    gated = conf["value"] >= 0.6

    tv = tavr(db, rid) if gated else None
    gc = gct_drift(db, rid) if gated else None
    bal = balance(db, rid) if gated else None
    # Cadence / stride / vertical oscillation are strongly pace- and
    # terrain-dependent, so they get the same per-terrain-bucket drift-z as
    # vertical ratio — a shift only counts when it holds at comparable pace.
    cad = drift_z(db, rid, "cadence_spm") if gated else None
    strd = drift_z(db, rid, "stride_len_m") if gated else None
    vosc = drift_z(db, rid, "vert_osc_cm") if gated else None
    duty = duty_factor(db, rid) if gated else None
    gcv = gait_cv(db, rid) if gated else None
    dec = decouple(db, rid) if gated else None
    # Phase 5 — when detailed streams have been fetched, replace each metric's
    # per-run drift with the finer within-run SEGMENT drift (no within-run
    # averaging). Only overrides metrics that already passed the confidence gate;
    # keeps the per-run detail/series for the existing charts.
    seg_scored = False
    if gated and _emode() == "v2":
        sm = segment_mechanics(db, rid)
        if sm:
            for key, var in (("tavr", tv), ("gct", gc), ("cadence", cad), ("stride", strd), ("vosc", vosc)):
                res = sm.get(key)
                if res and isinstance(var, dict):
                    for k in ("z", "ewma", "ctrl", "latest", "state", "persist", "beyond", "nSessions"):
                        if k in res:
                            var[k] = res[k]
                    var["byBand"] = res.get("byBand")
                    var["segment"] = True
                    seg_scored = True
    aer = aerobic(db, rid)
    rcv = recovery(db, rid)
    fb = feedback(db, rid)
    hcv = hrv_cv(db, rid)
    sreg = sleep_regularity(db, rid)
    seff = sleep_efficiency(db, rid)
    stiff = stiffness_pattern(db, rid)
    gdesc = descent_by_gradient(db, rid)
    inj = injury(db, rid)

    # Daily check-in is a *today* signal — only the last few days count, so a
    # stale pain report from weeks ago doesn't keep inflating the score forever.
    # Persistent problems live on the weekly OSTRC / injury path (28-day window).
    ci = (
        db.query(models.Checkin)
        .filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at > day_ago(4))
        .order_by(models.Checkin.submitted_at.desc())
        .first()
    )

    sig = []

    def push(sid, name, grade, pts, val, detail):
        sig.append({"id": sid, "name": name, "grade": grade, "pts": pts, "val": val, "detail": detail})

    mech_score = load_score = symp_score = 0

    # v0.6 — injury history is the single most robust RRI risk factor (Hulme 2017;
    # van Poppel 2021 high-quality evidence; Desai 2021 HR 1.9). It acts two ways:
    #  (a) FRAILTY — reduced load tolerance: the same load/mechanics count for more
    #      (Bertelsen 2017 — "how much can a runner with X tolerate?"), applied as a
    #      multiplier so it only amplifies existing signals, never invents risk;
    #  (b) REGION WEIGHTING — recurring pain at a previously injured site scores extra.
    prior_regions = set()
    if r and r.prior_injury:
        low = r.prior_injury.lower()
        for key, lbl in _REGION_LABEL.items():
            if key in low or lbl.lower() in low:
                prior_regions.add(key)
    for rep in db.query(models.InjuryReport).filter(
        models.InjuryReport.runner_id == rid, models.InjuryReport.submitted_at > day_ago(365)
    ):
        if rep.body_region:
            prior_regions.add(rep.body_region)
        for pp in (rep.pain_points or []):
            if pp.get("region"):
                prior_regions.add(pp["region"])
    prior_months = r.prior_injury_months_ago if (r and r.prior_injury_months_ago is not None) else None
    frailty = 1.0
    if r and r.prior_injury and prior_months is not None and prior_months <= 12:
        frailty = 1 + clamp(0.20 * (1 - prior_months / 12), 0.04, 0.20)

    # --- Mechanical drift: scored *continuously* rather than only above a hard
    # z ≥ 1 threshold, so subtle terrain-cleaned changes nudge the drift score up
    # instead of leaving it stuck at zero. Each metric adds points proportional
    # to how far it drifted past a small per-metric noise deadzone, in its "bad"
    # direction. A signal is listed only once the drift is genuinely notable
    # (`show`), so tiny drift still feeds the score without cluttering the list.
    #                (id,     name,                            grade, mag,               dead, weight, cap, show,  val,                     detail)
    mech_terms = []
    if tv:
        mech_terms.append(("tavr", "Vertikální poměr roste", "B", tv["z"], 0.2, 17, 4.0, 0.6, f"z {sgn(tv['z'])}",
                           f"{tv['baseMean']} % → {tv['recMean']} % · {tv['buckets']} shodných profilů terénu"))
    if gc:
        mech_terms.append(("gct", "Prodloužený kontakt se zemí", "B", gc["z"], 0.2, 13, 4.0, 0.6, f"z {sgn(gc['z'])}",
                           f"{gc['baseMean']} ms → {gc['recMean']} ms po normalizaci na kadenci"))
    if cad:
        mech_terms.append(("cad", "Klesající kadence", "C", -cad["z"], 0.2, 10, 4.0, 0.6, f"z {sgn(cad['z'])}",
                           f"{cad['baseMean']} → {cad['recMean']} spm · {cad['buckets']} shodných profilů terénu"))
    if vosc:
        mech_terms.append(("vosc", "Vyšší vertikální oscilace", "C", vosc["z"], 0.2, 10, 4.0, 0.6, f"z {sgn(vosc['z'])}",
                           f"{vosc['baseMean']} → {vosc['recMean']} cm · {vosc['buckets']} shodných profilů terénu"))
    if bal:
        mech_terms.append(("bal", "Posun v symetrii kontaktu", "B", bal["excursion"], 0.4, 22, 3.0, 0.8, f"{sgn(bal['excursion'])} p.b.",
                           f"{bal['baseline']} % → {bal['now']} % vlevo · {bal['direction']}"))
    for sid, name, grade, mag, dead, weight, cap, show, val, detail in mech_terms:
        p = rnd(clamp(mag - dead, 0, cap) * weight)
        if p:
            mech_score += p
            if mag >= show:
                push(sid, name, grade, p, val, detail)
    # Decoupling (fatigue resistance) is a %/run trend, scored on its own ramp.
    if dec and dec["trend"] > 0.15:
        p = rnd(clamp(dec["trend"] - 0.1, 0, 1.2) * 26)
        if p:
            mech_score += p
            if dec["trend"] >= 0.35:
                push("dec", "Klesající odolnost proti únavě", "C", p, f"{sgn(dec['latest'])} %",
                     f"Technika se v poslední třetině rozpadá víc než dřív · trend {sgn(dec['trend'])}/běh")
    # v0.5 — gait variability: mechanics scattered more around own norm than before
    if gcv and gcv["ratio"] is not None and gcv["ratio"] >= 1.5:
        p = rnd(clamp((gcv["ratio"] - 1.5) * 14, 0, 14))
        if p:
            mech_score += p
            push("gaitcv", "Kolísavější mechanika", "C", p, f"×{gcv['ratio']}",
                 f"Kontakt se zemí je z běhu na běh rozházenější kolem vaší normy (SD {gcv['sdNow']} vs {gcv['sdBase']} ms) — "
                 "časný signál nervosvalové únavy nebo kompenzace, ještě než se posune samotný průměr.")

    # --- Load axis is evidence-weighted (v0.5.2 recalibration). The well-
    # validated grade-B signals (ACWR, high-intensity spike, monotony, HRV,
    # resting HR, aerobic decoupling) can flip the "overreaching" state on their
    # own at genuinely elevated values. The softer grade-C signals (descent
    # spikes, load creep, HRV volatility, fitness–fatigue balance) are capped low
    # so they add nuance/severity but don't stack their way to the threshold by
    # themselves — before this, a single hilly week (desc, cap 26) nearly flipped
    # the quadrant, pinning ~half of days at "Přetížení".
    # v0.6 — SINGLE-SESSION SPIKE is now the spine of the load axis. Bands from
    # the RUNSAFE cohort's hazard ratios (BJSM 2025): >+100 % (×2.0) is the clear
    # danger zone (HRR 2.28); +30–100 % moderate; +10–30 % a mild nudge.
    if L["valid"] and L["sessionSpike"] is not None and L["sessionSpike"] > 1.1:
        s = L["sessionSpike"]
        if s > 2.0:
            p = rnd(clamp((s - 2.0) * 16, 0, 16) + 14)      # 14..30
            band = "nad +100 %"
        elif s > 1.3:
            p = rnd(clamp((s - 1.3) * 20, 0, 14))           # up to 14
            band = "+30–100 %"
        else:
            p = rnd(clamp((s - 1.1) * 25, 0, 6))            # up to 6
            band = "+10–30 %"
        if p:
            load_score += p
            _basis = L.get("sessionSpikeBasis") or "vzdálenost"
            _bl = {"vzdálenost": "délce", "intenzita": "intenzitě", "obojí": "délce i intenzitě"}.get(_basis, "délce")
            push("session_spike", "Skok v jednom běhu", "B", p, f"×{s}",
                 f"Nejnáročnější běh ({L['sessionSpikeKm']} km) je {band} proti nejnáročnějšímu běhu za předchozích 30 dní — "
                 f"skok ve {_bl}. Skok v jednotlivém běhu je nejsilnější signál rizika (běžecká kohorta 5 205 běžců; "
                 "u intenzity potvrzeno i na datech z hodinek, Neal 2024) — silnější než poměr 7:28.")

    # v0.6 — latent memory: risk stays elevated 1-4 weeks AFTER a big spike, not
    # the day of it (IOC 2016), decaying to zero by 28 days.
    if L["valid"] and L["spikeLatent"] is not None:
        p = rnd(clamp(L["spikeLatent"] * 22, 0, 16))
        if p:
            load_score += p
            push("spike_latent", "Doznívající skok v zátěži", "B", p, f"před {L['spikeLatentDaysAgo']} dny",
                 "Velký skok v délce běhu z posledních týdnů — riziko zranění vrcholí 1–4 týdny po prudkém nárůstu, "
                 "ne hned. Stav proto zůstává zvýšený, dokud tělo nedožene adaptaci.")

    # v0.6 — pace spike: a distinct mechanism from distance (Nielsen 2014 — sudden
    # pace → Achilles/plantar/tibial; distance → knee/shin).
    if L["valid"] and L["paceSpike"] is not None and L["paceSpike"] > 1.06:
        p = rnd(clamp((L["paceSpike"] - 1.06) * 40, 0, 10))
        if p:
            load_score += p
            push("pace_spike", "Skok v tempu", "C", p, f"×{L['paceSpike']}",
                 "Nedávný běh byl výrazně rychlejší než vaše obvyklé tempo posledních 30 dní — prudké zrychlení "
                 "zatěžuje jinak než delší vzdálenost (spíš Achillovka / planta / holeň).")

    # v0.6 — ACWR DEMOTED to low-weight context (grade C). The team-sport
    # acute:chronic "sweet spot" does not transfer to distance running — the same
    # RUNSAFE cohort found ACWR *inversely* related to overuse injury and the
    # week-to-week ratio unrelated. Kept only as a mild descriptor / detraining flag.
    if L["valid"] and L["ratio"] is not None and L["ratio"] > 1.5:
        p = rnd(clamp((L["ratio"] - 1.5) * 18, 0, 12) + 2)
        load_score += p
        push("ewma", "Zvýšený poměr zátěže (7:28)", "C", p, f"×{L['ratio']}",
             f"Akutní zátěž {L['acute']} proti chronické {L['chronic']} j.z./týden. Pozn.: v běžecké kohortě "
             "sám poměr 7:28 riziko nepředpovídá — hlavní signál je skok v jednotlivém běhu výše.")
    elif L["valid"] and L["ratio"] is not None and L["ratio"] < 0.7:
        load_score += 10
        push("ewma", "Náhlý pokles zátěže", "C", 10, f"×{L['ratio']}",
             "Prudké snížení objemu — mírně vyšší riziko při návratu k plné zátěži, ne bezpečná zóna")

    # v0.5 — high-intensity exposure spike (hard efforts jumping on a low hard base)
    if L["valid"] and L["hiAcute"] >= 60 and L["hiRatio"] is not None and L["hiRatio"] > 1.5:
        p = rnd(clamp((L["hiRatio"] - 1.5) * 20, 0, 20))
        load_score += p
        push("hi_load", "Skok ve vysoké intenzitě", "B", p, f"×{L['hiRatio']}",
             f"Tvrdá práce (vysoký tep) {L['hiAcute']} vs obvyklých {L['hiChronic']} j.z./týden. "
             "Prudký nárůst intenzity na nízké základně nese vyšší riziko než stejná zátěž volně.")

    # v0.5 — load creep: slow, persistent acute rise the spike thresholds miss
    if L["valid"] and L["ratio"] is not None and L["ratio"] < 1.3 and L["loadCreep"] is not None and L["loadCreep"] >= 1.15:
        p = rnd(clamp((L["loadCreep"] - 1.15) * 30, 0, 10))
        if p:
            load_score += p
            push("load_creep", "Postupný nárůst zátěže", "C", p, f"+{round((L['loadCreep'] - 1) * 100)} % / 2 týdny",
                 "Zátěž pozvolna roste dva týdny po sobě, i když poměr 7:28 je ještě v klidu — "
                 "plíživé navyšování předchází zranění častěji než jednorázový skok.")

    if L["monotony"] > 2.4:
        p = rnd(clamp((L["monotony"] - 2.4) * 7, 0, 20))
        load_score += p
        push("mono", "Monotónní trénink", "B", p, f"{L['monotony']}", f"Chybí skutečně lehké dny · strain {L['strain']}")
    if L["descentSpike"] is not None and L["descentSpike"] > 1.45:
        p = rnd(clamp((L["descentSpike"] - 1.45) * 15, 0, 14))
        load_score += p
        push("desc", "Nárůst sbíhání", "C", p, f"×{L['descentSpike']}",
             f"{L['descent7']} m klesání za 7 dní proti obvyklým {L['descentBase']} m")
    if gdesc and gdesc["steepSpike"] is not None and gdesc["steepSpike"] > 1.5:
        p = rnd(clamp((gdesc["steepSpike"] - 1.5) * 12, 0, 12))
        load_score += p
        push("desc_steep", "Nárůst strmého klesání (≥10 % sklon)", "C", p, f"×{gdesc['steepSpike']}",
             f"{gdesc['steep7']} m klesání nad 10% sklonem za 7 dní proti obvyklým {gdesc['steepBaseWeekly']} "
             "m/týden — strmé klesání zatěžuje excentricky víc než pozvolné, i při stejném celkovém převýšení")
    if aer and aer["mean"] > 5.5:
        p = rnd(clamp((aer["mean"] - 5.5) * 3, 0, 12))
        load_score += p
        push("aer", "Aerobní decoupling", "B", p, f"{aer['mean']} %", "Tep se v druhé půli odpojuje od tempa")
    if rcv and rcv["hrv"]["z"] <= -1.0:
        p = rnd(clamp(-rcv["hrv"]["z"] * 10, 0, 22))
        load_score += p
        push("hrv", "Potlačená HRV", "B", p, f"{rcv['hrv']['now']} ms",
             f"Baseline {rcv['hrv']['base']} ms · z {rcv['hrv']['z']} za posledních 7 dní")
    if rcv and rcv["rhr"]["z"] >= 1.2:
        p = rnd(clamp(rcv["rhr"]["z"] * 8, 0, 18))
        load_score += p
        push("rhr", "Zvýšený klidový tep", "B", p, f"{rcv['rhr']['now']} tep/min",
             f"Baseline {rcv['rhr']['base']} · z {sgn(rcv['rhr']['z'])}")
    if hcv and hcv["ratio"] is not None and hcv["ratio"] >= 1.4:
        p = rnd(clamp((hcv["ratio"] - 1.4) * 14, 0, 10))
        load_score += p
        push("hrvcv", "Kolísavá HRV mezi dny", "C", p, f"CV ×{hcv['ratio']}",
             f"Den-k-dni variabilita HRV {hcv['cvNow']} % proti obvyklým {hcv['cvBase']} %")
    # Fitness–fatigue gap, relative to chronic load so the threshold is unit-free
    # (acute/chronic are now training-load AU, not km).
    if L["valid"] and L["chronic"] and L["tsbBalance"] is not None:
        tsb_rel = L["tsbBalance"] / L["chronic"]
        if tsb_rel <= -0.12:
            p = rnd(clamp((-tsb_rel - 0.12) * 90, 0, 12))
            load_score += p
            push("tsb", "Nepříznivá bilance zátěže", "C", p, f"{sgn(L['tsbBalance'])} j.z./týd",
                 f"Fitness (42denní průměr) {L['fitness42']} proti aktuální zátěži {L['acute']} j.z./týden — akutní zátěž předbíhá vybudovanou")

    # v0.6 — LOAD × CAPACITY interaction (Bertelsen 2017 framework: injury is
    # cumulative load exceeding *structure-specific capacity*, and capacity is
    # modulated by recovery). A spike on depleted recovery is far riskier than the
    # same spike when fresh — so score the interaction, not just the two alone.
    cap_parts = []
    if rcv and rcv["hrv"]["z"] is not None:
        cap_parts.append(clamp(-rcv["hrv"]["z"] / 2.0, 0, 1))            # suppressed HRV
    if rcv and rcv["rhr"]["z"] is not None:
        cap_parts.append(clamp(rcv["rhr"]["z"] / 2.0, 0, 1))            # elevated RHR
    if rcv and rcv["sleep"]["debt"] is not None:
        cap_parts.append(clamp(rcv["sleep"]["debt"] / 8.0, 0, 1))       # sleep debt
    capacity_deficit = r2(mean(cap_parts)) if cap_parts else None
    spike_sev = max((L["sessionSpike"] or 1) - 1, (L["ratio"] or 1) - 1, 0)
    if L["valid"] and capacity_deficit is not None and capacity_deficit >= 0.3 and spike_sev > 0.1:
        p = rnd(clamp(capacity_deficit * spike_sev * 34, 0, 16))
        if p:
            load_score += p
            push("load_capacity", "Zátěž na sníženou regeneraci", "B", p,
                 f"deficit {round(capacity_deficit * 100)} %",
                 "Skok v zátěži padá na oslabenou regeneraci (nižší HRV / vyšší klidový tep / spánkový dluh). "
                 "Stejný nárůst na unaveném těle přesahuje momentální kapacitu tkání dřív než na odpočatém.")

    # Race proximity is deliberately not a primary framing anywhere in the
    # UI — it's informational unless it combines with an already-elevated
    # load state, in which case it becomes a genuine red flag.
    if r and r.goal_date:
        days_to_race = days_between(iso_date(today_date()), r.goal_date)
        if days_to_race is not None and 0 <= days_to_race <= 21 and (
            load_score >= QUAD_THRESHOLD or (L["ratio"] is not None and L["ratio"] > 1.3)
        ):
            p = rnd(clamp((21 - days_to_race) / 21 * 14, 4, 14))
            load_score += p
            push("taper", "Blízký závod při zvýšené zátěži", "C", p, f"{days_to_race} dní do závodu",
                 f"{r.goal_race or 'cílový závod'} za {days_to_race} dní při zvýšené aktuální zátěži — "
                 "riziko přetížení těsně před závodem stoupá, zvažte odlehčení místo dalšího navyšování")

    if fb and fb["niggleCount"] >= 3:
        p = rnd(clamp(fb["niggleCount"] * 9, 0, 40))
        symp_score += p
        push("niggle", "Opakované bolestivé místo", "A", p, f"{fb['niggleCount']}× / 21 dní",
             f"{fb['topSite']['site']} — hlášeno {fb['topSite']['n']}× po tréninku" if fb["topSite"]
             else "Opakované hlášení po tréninku")
    pain_warn = None
    if ci:
        base = 44 if (ci.pain_score or 0) >= 6 else 26 if (ci.pain_score or 0) >= 3 else 8 if (ci.pain_score or 0) >= 1 else 0
        if base:
            # Location matters through *recurrence*. Two tiers:
            #  • back-to-back — the same running-relevant site reported again
            #    within ~2 days (pain not resolving between runs) is an acute
            #    overload flag and gets the strongest bonus;
            #  • chronic — the same site recurring over 28 days gets a milder one.
            # A one-off / non-running spot gets the base only.
            ci_regions = [p.get("region") for p in (ci.pain_points or []) if p.get("region")]
            rec = pain_recurrence(db, rid)
            d2 = day_ago(2)
            rec_n = max((len(rec.get(r, [])) for r in ci_regions), default=0)          # incl. this check-in, 28d
            recent2 = max((sum(1 for d in rec.get(r, []) if d > d2) for r in ci_regions), default=0)  # last 2 days
            run_rel = any(_run_relevant(r) for r in ci_regions)
            site = ", ".join(ci_regions) if ci_regions else (ci.pain_site or "—")
            back_to_back = run_rel and recent2 >= 2
            if back_to_back:
                bonus = rnd(clamp(recent2 * 8, 8, 26))
                p = base + bonus
                push("pain", f"Neustupující bolest: {site} — možné přetížení", "A", p, f"{ci.pain_score}/10",
                     f"{site} — hlášeno {recent2}× během 2 dnů. Bolest, která mezi běhy neustupuje na stejném místě, je varovný signál přetížení.")
            elif run_rel and rec_n >= 3:
                bonus = rnd(clamp((rec_n - 2) * 6, 0, 18))
                p = base + bonus
                push("pain", f"Opakující se bolest: {site}", "A", p, f"{ci.pain_score}/10",
                     f"{site} — hlášeno {rec_n}× za 28 dní napříč check-iny a deníkem. Opakující se lokalizovaná bolest je klasický vzorec přetížení.")
            else:
                p = base
                nm = "Bolest při běhu" if base == 44 else "Přetrvávající bolest" if base == 26 else "Mírný diskomfort"
                push("pain", nm, "A", p, f"{ci.pain_score}/10", site)
            symp_score += p
            # v0.6 — region weighting: pain at a previously injured site is the
            # classic recurrence pattern and the strongest evidence-backed flag.
            if run_rel and any(rg in prior_regions for rg in ci_regions):
                pb = 8
                symp_score += pb
                push("pain_prior", "Bolest v místě dřívějšího zranění", "A", pb, site,
                     "Aktuální bolest je na místě dřívějšího zranění — recidiva ve stejné oblasti je klasický vzorec a v literatuře nejsilnější rizikový faktor.")
            # Warn the runner to reconsider when pain is above 3/10.
            if (ci.pain_score or 0) > 3:
                pain_warn = {"score": ci.pain_score, "site": site, "backToBack": back_to_back}
        if ci.soreness is not None and ci.soreness >= 7:
            symp_score += 10
            push("sore", "Vysoká svalová únava", "B", 10, f"{ci.soreness}/10", "Po tréninku")
        # Self-reported fatigue (the check-in's "Únava" slider) — a soft symptom
        # signal: high perceived fatigue precedes overload before HRV/RHR move.
        if ci.stress is not None and ci.stress >= 6:
            p = rnd(clamp((ci.stress - 5) * 2.5, 0, 12))
            symp_score += p
            push("fatigue", "Vysoká vnímaná únava", "C", p, f"{ci.stress}/10", "Ze self-reportu v check-inu")
    if rcv and rcv["sleep"]["debt"] is not None and rcv["sleep"]["debt"] >= 4:
        p = rnd(clamp(rcv["sleep"]["debt"] * 2.5, 0, 16))
        symp_score += p
        push("sleep", "Spánkový dluh", "B", p, f"−{rcv['sleep']['debt']} h/týden",
             f"{rcv['sleep']['now']} h proti obvyklým {rcv['sleep']['base']} h")
    if sreg and sreg["ratio"] is not None and sreg["ratio"] >= 1.5:
        p = rnd(clamp((sreg["ratio"] - 1.5) * 12, 0, 14))
        symp_score += p
        push("sleepreg", "Nepravidelná délka spánku", "C", p, f"SD ×{sreg['ratio']}",
             f"kolísání délky spánku {sreg['sdNow']} h proti obvyklým {sreg['sdBase']} h za 14 dní")
    # v0.5 — low sleep efficiency (fragmented sleep) beyond raw duration
    if seff and seff["now"] < 0.85:
        p = rnd(clamp((0.85 - seff["now"]) * 60, 0, 16))
        if p:
            symp_score += p
            push("sleepeff", "Nízká efektivita spánku", "C", p, f"{round(seff['now'] * 100)} %",
                 f"Ze spánku prospáno {round(seff['now'] * 100)} %{f' (obvykle {round(seff['base'] * 100)} %)' if seff['base'] else ''} — "
                 "roztříštěný spánek zhoršuje regeneraci i nad rámec počtu hodin.")
    if fb and fb["n"] >= 6 and fb["feelingTrend"] <= -0.12:
        symp_score += 10
        push("feel", "Zhoršující se pocit z běhu", "C", 10, f"{fb['feelingMean']}/5",
             "Sebehodnocení po trénincích klesá napříč posledními 21 dny")
    if stiff and stiff["highCount"] >= 3 and stiff["ignoreRate"] is not None and stiff["ignoreRate"] >= 0.5:
        p = rnd(clamp(stiff["ignoreRate"] * 20, 0, 18))
        symp_score += p
        push("stiffness", "Trénink navzdory ztuhlosti nohou", "C", p,
             f"{stiff['pushedThroughCount']}/{stiff['highCount']}×",
             f"Při ztuhlosti nohou před během proběhlo {round(stiff['ignoreRate']*100)} % běhů i tak s vysokou "
             "vnímanou námahou (RPE ≥ 6)")
    elif stiff and stiff["n"] >= 6 and stiff["trend"] >= 0.15:
        symp_score += 10
        push("stiffness", "Rostoucí ztuhlost nohou před během", "C", 10, f"{stiff['mean']}/5",
             "Sebehodnocená ztuhlost nohou před během roste napříč posledními 21 dny")
    if r and r.prior_injury and prior_months is not None and prior_months <= 12:
        p = rnd(clamp(18 * (1 - prior_months / 12), 6, 18))
        symp_score += p
        push("hist", "Zranění v anamnéze", "A", p, f"{prior_months} měs.",
             f"{r.prior_injury} — nejrobustnější rizikový faktor napříč literaturou; váha klesá s časem od zranění "
             f"a snižuje toleranci zátěže (×{r2(frailty)}).")

    # v0.6 — a live reported/confirmed injury (OSTRC-H). Weighted on the
    # symptom axis on a par with an in-run pain report, scaled by severity;
    # a physio-confirmed conclusion carries grade A and a higher ceiling than
    # a runner self-report (grade B). Stored regardless (see injury()), but
    # only an *active* report with severity moves the score.
    if inj and inj["active"]:
        ia = inj["active"]
        sub = "omezená účast nebo výkon" if ia["substantial"] else "plná účast s obtížemi"
        if ia["confirmed"]:
            p = rnd(clamp(ia["severity"] * 0.5, 0, 46))
            symp_score += p
            push("injury", "Potvrzené zranění (fyzioterapeut)", "A", p, f"OSTRC {ia['severity']}/100",
                 f"{ia['site']} — {sub}")
        else:
            p = rnd(clamp(ia["severity"] * 0.34, 0, 32))
            symp_score += p
            push("injury", "Nahlášené zranění", "B", p, f"OSTRC {ia['severity']}/100",
                 f"{ia['site']} — {sub} · self-report, nepotvrzeno fyziem")

    # v0.6 — broad recent-complaint signal. Frandsen 2025: same-site recurrence is
    # rare before injury (6.9 % at 7d), but a problem in *any* location preceded
    # 39.6 % of injuries within 28 days — so a broad complaint tally is a more
    # sensitive (if less specific) early flag than same-site recurrence alone.
    rec_all = pain_recurrence(db, rid)
    run_complaint_days = len({d for reg, dts in rec_all.items() if _run_relevant(reg) for d in dts})
    if run_complaint_days >= 3:
        p = rnd(clamp((run_complaint_days - 2) * 4, 0, 14))
        symp_score += p
        push("complaints", "Opakované obtíže (napříč místy)", "B", p, f"{run_complaint_days} dní / 28",
             "Bolest hlášená ve více dnech za poslední 4 týdny, i když se místo mění. Opakované obtíže "
             "předcházejí zranění častěji než jednorázová bolest — širší, citlivější varování než jen recidiva stejného místa.")

    # Frailty (injury history) reduces load tolerance: same objective load/mechanics
    # count for more. Multiplicative, so it amplifies existing signals only. Rounded
    # so scores stay integer end-to-end (and the live-formula backtest matches exactly).
    mech_score = rnd(clamp(mech_score * frailty, 0, 100))
    load_score = rnd(clamp(load_score * frailty, 0, 100))
    symp_score = rnd(clamp(symp_score, 0, 100))
    overall = rnd(clamp(mech_score * 0.38 + load_score * 0.30 + symp_score * 0.52, 0, 100))
    prev_row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
    # v2 Phase 2: across-session evidence label (informational — shown to the
    # user, NOT yet a hard quadrant gate). "flag" = persistence (EWMA past its
    # control limit + same sign in ≥2 of last 3 sessions, rule A) or convergence
    # (≥2 registry metrics clear, rule B); "watch" = one clear metric. The EWMA
    # smoothing already damps one-off spikes and accumulates genuine slow drift,
    # so the quadrant follows the smoothed mech score; the hard flag-gate is
    # deferred to the segmentation phase, where within-session "clear" (a CI over
    # many segments) is reliable enough to gate on.
    mech_flag = mech_watch = False
    if _emode() == "v2":
        mm = [m for m in (tv, gc, cad, strd, vosc) if isinstance(m, dict) and "state" in m]
        clears = [m for m in mm if m.get("state") == "clear"]
        rule_a = any(m.get("beyond") and m.get("persist") for m in mm)
        rule_b = len(clears) >= 2
        mech_flag = rule_a or rule_b
        mech_watch = (not mech_flag) and len(clears) >= 1
    quadrant = quadrant_of(load_score, mech_score, prev_row.quadrant if prev_row else None)
    tier = "alert" if overall >= 70 else ("watch" if overall >= 40 else "ok")

    return {
        "runner_id": rid, "computed_at": now_iso(), "engine": engine_version_for(_emode()),
        "engineMode": _emode(), "mechFlag": mech_flag, "mechWatch": mech_watch, "segmentScored": seg_scored,
        "mech": mech_score, "load": load_score, "symp": symp_score, "overall": overall,
        "tier": tier, "quadrant": quadrant, "confidence": conf,
        "signals": sorted(sig, key=lambda s: -s["pts"]),
        "loadDetail": L, "tavr": tv, "gct": gc, "bal": bal, "dec": dec, "aer": aer, "rcv": rcv, "fb": fb,
        "cadence": cad, "stride": strd, "vosc": vosc, "duty": duty, "gaitCv": gcv, "painWarn": pain_warn,
        "hrvCv": hcv, "sleepReg": sreg, "sleepEff": seff, "stiffness": stiff, "gradientDescent": gdesc, "injury": inj,
        # v0.6 — single-session paradigm surface + capacity/frailty transparency +
        # forward-looking guardrail (the safe next-long-run ceiling).
        "sessionSpike": L.get("sessionSpike"), "spikeLatent": L.get("spikeLatent"),
        "sessionSpikeBasis": L.get("sessionSpikeBasis"),
        "paceSpike": L.get("paceSpike"), "safeLongRunKm": L.get("safeLongRunKm"),
        "capacityDeficit": capacity_deficit, "frailty": r2(frailty), "priorRegions": sorted(prior_regions),
    }


DECISION_HEAD = {
    "physio_48h": "Objednat fyzioterapeuta do 48 hodin",
    "physio_7d": "Vyšetření do 7 dnů — mechanika se mění bez nárůstu objemu",
    "app_program": "Preventivní program v aplikaci, kontrola za 7 dnů",
    "self_managed": "Pokračovat podle plánu",
}


def recompute_assessment(db: DBSession, rid: str) -> dict:
    """Recomputes assess() and persists it, mirroring core.js's top-level
    assess(db,rid) which also upserts the runner's triage row. Call this
    after any mutation that can move the score (checkin, activity rating,
    daily-metric edit, garmin import, program claim)."""
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    with engine_pinned((r.engine_mode if r else None) or "v1"):
        a = assess(db, rid)
    row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
    if row is None:
        row = models.Assessment(runner_id=rid)
        db.add(row)
    row.computed_at = a["computed_at"]
    row.engine_version = a["engine"]
    row.mech, row.load, row.symp, row.overall = a["mech"], a["load"], a["symp"], a["overall"]
    row.tier, row.quadrant = a["tier"], a["quadrant"]
    row.confidence_json = a["confidence"]
    row.signals_json = a["signals"]
    row.detail_json = {
        k: a[k] for k in
        ("loadDetail", "tavr", "gct", "bal", "dec", "aer", "rcv", "fb", "cadence", "stride", "vosc",
         "duty", "gaitCv", "painWarn", "hrvCv", "sleepReg", "sleepEff", "stiffness", "gradientDescent", "injury",
         "engineMode", "mechFlag", "mechWatch", "segmentScored")
    }
    db.flush()

    if a["quadrant"] == "critical" or a["tier"] == "alert":
        decision = "physio_48h"
    elif a["quadrant"] == "silent":
        decision = "physio_7d"
    elif a["tier"] == "watch":
        decision = "app_program"
    else:
        decision = "self_managed"
    headline = DECISION_HEAD[decision]

    open_triage = (
        db.query(models.Triage)
        .filter(models.Triage.runner_id == rid, models.Triage.status != "closed")
        .first()
    )
    if open_triage:
        open_triage.decision = decision
        open_triage.headline = headline
    else:
        db.add(models.Triage(
            runner_id=rid, decision=decision, headline=headline,
            status="closed" if decision == "self_managed" else "open",
            claimed_by=None, created_at=now_iso(),
        ))
    db.commit()
    return a


def get_or_refresh_assessment(db: DBSession, rid: str) -> dict:
    """Read path: return the stored assessment, but recompute it when it's from
    a prior day or an older engine version. The assessment embeds time-relative
    windows (this calendar week, last 7 days, last night's recovery), so a row
    computed on a previous day is stale even if nothing was written since."""
    row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
    if row is None:
        return recompute_assessment(db, rid)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    expected = engine_version_for((r.engine_mode if r else None) or "v1")
    stale = (row.engine_version != expected) or ((row.computed_at or "")[:10] < iso_date(today_date()))
    return recompute_assessment(db, rid) if stale else assessment_row_to_dict(row)


def assessment_row_to_dict(row: models.Assessment) -> dict:
    """Reconstructs the assess()-shaped dict from a persisted Assessment row,
    for read endpoints that shouldn't recompute on every GET."""
    if row is None:
        return None
    out = {
        "runner_id": row.runner_id, "computed_at": row.computed_at, "engine": row.engine_version,
        "engineMode": "v2" if (row.engine_version or "").endswith("-s") else "v1",
        "mech": row.mech, "load": row.load, "symp": row.symp, "overall": row.overall,
        "tier": row.tier, "quadrant": row.quadrant, "confidence": row.confidence_json,
        "signals": row.signals_json,
    }
    out.update(row.detail_json or {})
    return out
