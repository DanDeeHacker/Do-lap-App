"""Injury-risk engine v0.4 — Python port of core.js's `metrics`/`assess`
(core.js lines ~93-304 of the original prototype), extended with three new
wearable-derived signals and a refined ACWR band. Every signal still carries
an evidence grade (A/B/C) and is documented in sig_doc.py with the same
formula/why/limit/clear structure the prototype established.

Nothing here is a diagnosis. See ai_brief.py's closing caveat, which every
clinician-facing summary repeats verbatim.
"""
import calendar
import math
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DBSession

from . import data as D
from . import terrain
from .. import models

# v0.7.0 — per-run drift adjusted to the runner's own pace sensitivity (both
# engines); v2: calibrated noise scale/EWMA, one-sided grouped flags, standardised
# segment drift. The version is part of the stored assessment, so bumping it makes
# every runner's cached score recompute on the next read.
# v0.7.1 — v3 guidance on a 4-week loading cycle (90/100/110/55 %), one weekly
# budget across tabs, robust per-run intensity capacity (mean of the top 3),
# zone minutes; repeated same-site pain lifts the tier to "watch" (odlehčit).
# v0.7.2 — readiness as a 20–100 % score from the size of HRV / resting-HR /
# sleep deviations (8-week baseline); guidance gates on it; mechanics over its
# threshold trims today's volume / intensity / descent.
# v0.7.3 — readiness recalibrated on real data (7-night mean ×1.25, full at 3 SD).
ENGINE_VERSION = "v0.11.0"  # v0.11.0: sleep in readiness by the evidence on watch sleep data — length and quality are separate parts; quality = sleep efficiency only (deep + REM share shown, not scored), over the last 3 nights, at most a quarter of a signal and half of that unless HRV or resting HR confirm; the 7-hour floor only until the own norm is known, then a separate note (sleepHabit); v0.10.5: hard minutes of cycling and swimming (Z4+ against the sport's own HR max) count in Intenzita — weekly load, per-session capacity and the spacing of hard days (railway#192); v0.10.4: the day outside training lowers today's readiness like a session (load above the usual day, at most ~8 points; today's raised resting heart rate × 0.6) until the night's data arrive; v0.10.3: all-day heart rate, own logic for every device (dayload.py) — load outside training above the usual day at half weight in the all-sport channel, yesterday's raised resting heart rate as a minor readiness signal (dayStress); v0.10.2: display data only, no scoring change — every session of the last 7 days per capacity channel (week7, feedback #149) and how far a run went past the hardest of 8 weeks (relativeEffort overMax, #148); v0.10.1: the weekly score compares the unabsorbed load with the usual weekly peak of the same measure (a once-a-week hard session no longer reads as over capacity on its own day); v0.10.0: pain and injury act on the capacity itself by the pain-monitoring model (hold inside it, one step back over it, no running on worse morning pain or an active injury, graded return caps the week), readiness per tissue (muscle / tendon / bone channels take HRV and resting HR at half weight); Příznaky and the readiness score unchanged; v0.9.4: the check-in steers the training recommendation again (not the Skóre or readiness), guidance.checkinReadiness; v0.9.3: graduated pain episodes per site (median / P75 re-marks, clean days halve, 3rd ends), no count escalation; check-in items only on Příznaky, watch sleep only through readiness; v0.9.2: displayed scores by band (tier band, model and trigger severity place the day in it; ok days spread), no fixed Skóre 60 floor; v0.9.1: recovery nights history and baseline spread for the readiness detail on Zátěž (railway#138), approximate per-item shares of every signal source (railway#132); v0.9.0: engine evaluation 2026-09 — pure snapshot engine (RunnerData, history replays by as_of), jump confirmation by repeats and passive tolerance, pace spike vs own fast runs, monotony only over capacity, RUNSAFE-shaped band curve, weather/equipment/pace-tertile confounders in mechanics, log-HRV readiness (single-night Regenerace removed), injury history to 24 months, under-conditioning, sex-specific TRIMP / bone / Achilles rules, safety rules outside the calibrated score, independent primary outcomes with censoring and session-scale data, LTHR zones and pace-based hard minutes, no physio referral for movement-only drift; v0.8.11: approximate per-item shares of every signal source (railway#132); v0.8.10: activity carousel rank (railway#119), swimming only (#118), sleep history (#114); v0.8.9: Czech decimal comma in all runner-facing engine texts; v0.8.8: signal effects in Skóre percentage points (railway#111), signal sources (#113), activity room and readiness around it (#110); v0.8.7: readiness breakdown (railway#107: what lowers it, change since yesterday), per-activity load history (Zátěž); v0.8.6: readiness after today's session (relative effort, Stanley 2013); v0.8.5: pain state (today's check-in decides, clean streaks, fading pain points, site-aware cross-training); v0.8.4: literature review 2026-09 (screening, readiness, heat, hard sessions); v0.8.3: cross-training (sport HR max, sRPE, strength channel, carry-over); v0.8.2: continuous point ramps, individual reference ranges, SWC dead zone (thresholds plan); v0.8.1: absorption (railway#100), prior-site rule (#91)
BASE_FROM, BASE_TO, RECENT = 84, 29, 28
QUAD_THRESHOLD = 25
QUAD_EXIT = 18  # hysteresis: an axis already "hot" stays hot until it drops below this
# v0.9.0 — the weights of the three axes in the overall score. Mechanics went 0.38 →
# 0.25: the watch's sagittal-plane metrics have no shown link to injury (Mason et al.,
# 2023; Neal et al., 2024; Willwacher et al., 2022), so until the calibration (plan
# phase 4) says otherwise they inform rather than drive the overall state.
W_MECH, W_LOAD_V3, W_LOAD, W_SYMP = 0.25, 0.40, 0.30, 0.52


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


# ---------------------------------------------------------------- continuous point ramps
# Plan phase 2B: every score function is continuous and non-decreasing in its
# input (Carey et al., 2018; Bache-Mathiesen et al., 2021, warn against cut-points).
# The old v1 versions jumped at their display thresholds, and the session-spike
# bands even dropped from 5 to 0 points just above 1.3×. Shared by assess() and
# the sensitivity sandbox (metrics/sensitivity.py) so the two cannot drift apart.
def pts_session_spike(s):
    """Single-session spike (v1/v2): the RUNSAFE-shaped curve of capacity.band_points
    over the 30-day longest run with the +10 % margin, scaled 0.8 (the v1/v2 axis
    has more signals). ~10 points on the +10–100 % plateau, ~19 at 2.5×."""
    from .capacity import band_points
    return 0.0 if s is None else band_points(s, 0.10) * 0.8


def pts_acwr(r):
    """7:28 ratio: a ramp into 2 points at 1.5× then +18/unit to 14, and a ramp to 10 below 0.8×."""
    if r is None:
        return 0.0
    if r >= 1.5:
        return clamp(2 + (r - 1.5) * 18, 0, 14)
    if r > 1.4:
        return (r - 1.4) * 20
    if r < 0.8:
        return clamp((0.8 - r) * 50, 0, 10)
    return 0.0


def pts_hrv_low(z):
    """Suppressed HRV: from 0 at z = −0.5 to 20 at z = −2 (cap 22)."""
    return 0.0 if z is None else clamp((-z - 0.5) * (20 / 1.5), 0, 22)


def pts_rhr_high(z):
    """Elevated resting HR: from 0 at z = 0.6 to 16 at z = 2 (cap 18)."""
    return 0.0 if z is None else clamp((z - 0.6) * (16 / 1.4), 0, 18)


def taper_weight(load_score, ratio):
    """0–1: how far the load sits into its elevated zone (18→25 points, or 7:28 1.2→1.3×).
    Replaces the old on/off gate at exactly 25, so the race-proximity points fade in."""
    return clamp(max((load_score - QUAD_EXIT) / (QUAD_THRESHOLD - QUAD_EXIT), ((ratio or 1.0) - 1.2) / 0.1), 0, 1)


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


def inlier_mean_sd(a, k=5.0):
    """(mean, SD, n) after dropping gross artefacts — points more than `k` robust
    SDs from the median (only with ≥ 10 points). Efficient like the plain SD when
    the data are clean (MAD alone is a noisy, often too-small scale on small
    samples, which inflated z-scores), yet one wild sensor value can't blow the
    scale up. k = 5 keeps a 95 % prediction test at ~5 % false positives on clean
    data; tighter trimming made it anti-conservative."""
    a = list(a)
    if len(a) < 10:
        # Too few points to tell an outlier from ordinary spread — the MAD itself
        # is unstable here, and trimming would shrink the SD (anti-conservative).
        return (mean(a), sd(a), len(a))
    m, r = median(a), mad_sd(a)
    keep = [x for x in a if abs(x - m) <= k * r] if r > 0 else a
    if len(keep) < 2:
        keep = a
    return (mean(keep), sd(keep), len(keep))


def _betacf(a, b, x):
    """Continued fraction for the regularised incomplete beta (Numerical Recipes)."""
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-14:
            break
    return h


def _betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t, df):
    """Two-sided p-value of Student's t with `df` degrees of freedom. With a
    baseline of only a handful of segments the normal p is far too small (a
    95 % test fired ~23 % of the time at n = 5)."""
    if df is None or df < 1:
        return 1.0
    if df > 1000:
        return math.erfc(abs(t) / math.sqrt(2))
    return clamp(_betai(df / 2.0, 0.5, df / (df + t * t)), 0.0, 1.0)


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


def _cz_num(n, dec=1) -> str:
    """A number for Czech text: decimal comma, no trailing ",0"."""
    v = round(float(n), dec)
    return (f"{v:.{dec}f}".rstrip("0").rstrip(".") if dec else str(int(v))).replace(".", ",")


def rnd(n):
    return None if n is None else round(n)


def sgn(n):
    return f"+{n}" if n > 0 else str(n)


# Runner-facing text is Czech: decimal comma, a real minus sign, "p. b." spacing. Applied
# where engine text leaves the engine (signals, guidance, coach and assistant texts), so a
# number interpolated anywhere upstream reads the same. A dot between digits in these
# texts is always a decimal point (dates are ISO with dashes or Czech with a space).
_DEC_DOT = re.compile(r"(?<=\d)\.(?=\d)")
_NEG = re.compile(r"(?<![\w\d.,])-(?=\d)")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def cz_text(s):
    if not isinstance(s, str) or not s or _ISO.match(s):
        return s
    return _NEG.sub("−", _DEC_DOT.sub(",", s)).replace("p.b.", "p. b.")


def cz_deep(o):
    """cz_text on every string of a nested dict / list (ISO dates and timestamps untouched)."""
    if isinstance(o, dict):
        return {k: cz_deep(v) for k, v in o.items()}
    if isinstance(o, list):
        return [cz_deep(v) for v in o]
    return cz_text(o)


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


def _edamp() -> frozenset:
    return getattr(_engine_ctx, "damp", None) or frozenset()


@contextmanager
def engine_pinned(mode: str):
    prev_m = getattr(_engine_ctx, "mode", None)
    prev_e = getattr(_engine_ctx, "excl", None)
    prev_d = getattr(_engine_ctx, "damp", None)
    _engine_ctx.mode = mode or "v1"
    _engine_ctx.excl = frozenset()
    _engine_ctx.damp = frozenset()
    try:
        yield
    finally:
        _engine_ctx.mode = prev_m
        _engine_ctx.excl = prev_e
        _engine_ctx.damp = prev_d


def mech_priors(field: str, device: str | None = None):
    """Population priors of a mechanics metric: from the snapshot being assessed
    (fixed for the whole assessment and its replays), else from reference.py."""
    from . import reference as REF
    p = getattr(_engine_ctx, "priors", None)
    if p is None:
        return REF.mech_priors(field=field, device=device)
    return p["mech"].get((REF._FIELD_ALIAS.get(field, field), device))


def recovery_priors(field: str, data=None):
    from . import reference as REF
    p = getattr(data, "priors", None) if data is not None else getattr(_engine_ctx, "priors", None)
    if p is None:
        return REF.recovery_priors(field=field)
    return p["rec"].get(field)


def _sensitive() -> bool:
    """v2 AND v3 use the sensitive (per-run, calibrated) mechanics engine; v3 adds
    the capacity-based load axis on top."""
    return _emode() in ("v2", "v3")


# v1 → "v0.7.3", v2 → "v0.7.3-s" (citlivý), v3 → "v0.7.3-c" (kapacitní). The suffix
# is how a stored assessment row remembers which engine produced it.
_MODE_SUFFIX = {"v2": "-s", "v3": "-c"}


def engine_version_for(mode: str) -> str:
    return ENGINE_VERSION + _MODE_SUFFIX.get(mode, "")


def mode_of_version(version: str) -> str:
    v = version or ""
    return next((m for m, suf in _MODE_SUFFIX.items() if v.endswith(suf)), "v1")


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


def quadrant_of(load_score, mech_score, prev=None, hi=QUAD_THRESHOLD, lo=QUAD_EXIT):
    """Quadrant with hysteresis: an axis counts as elevated once it crosses
    `hi`, and keeps counting until it falls back below `lo`. Without this the
    label flip-flops week to week when a score hovers around 25 (seen on real
    backtested data). `prev` is the last persisted quadrant.

    The mechanics axis follows its (EWMA-smoothed) score directly — the Phase-2
    persistence/convergence flags are surfaced as an informational chip
    (`mechFlag`/`mechWatch`) rather than gating the quadrant here; the hard gate
    is deferred to the within-run segmentation phase (see assess())."""
    prev_load = prev in ("overreaching", "critical")
    prev_mech = prev in ("silent", "critical")
    load_hot = load_score >= hi or (prev_load and load_score >= lo)
    mech_hot = mech_score >= hi or (prev_mech and mech_score >= lo)
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
    c1, c2 = getattr(_engine_ctx, "pace_cuts", None) or PACE_CUTS_FIXED
    pb = "fast" if p < c1 else ("mod" if p < c2 else "easy")
    return f"{a.surface}|{g}|{pb}"


# v0.9.0 — pace classes relative to the runner. Fixed cuts (4:30 / 5:30 per km) put
# every run of a 6:30/km runner in one class and every run of a 4:00/km runner in
# another; the runner's own pace thirds over the baseline window separate their easy,
# steady and fast running instead. Fixed cuts stay the fallback (and the pooled
# population priors keep them).
PACE_CUTS_FIXED = (270.0, 330.0)
PACE_CUTS_MIN_RUNS, PACE_CUTS_MIN_GAP = 12, 10.0     # runs, s/km between the two cuts


def pace_cuts(db, rid: str):
    """(fast|mod, mod|easy) cuts in s/km: the runner's own pace tertiles over the
    84→29-day baseline window, or None (→ fixed cuts) with too few or too alike runs."""
    lo, hi = day_ago(BASE_FROM), day_ago(BASE_TO)
    paces = sorted((a.duration_min or 0) / a.distance_km * 60 for a in D.of(db, rid).activities
                   if is_run(a) and counts_for(a, "mech") and lo < a.started_at <= hi
                   and (a.distance_km or 0) > 0 and (a.duration_min or 0) > 0)
    if len(paces) < PACE_CUTS_MIN_RUNS:
        return None
    q = lambda f: paces[int(round(f * (len(paces) - 1)))]   # noqa: E731
    c1, c2 = q(1 / 3), q(2 / 3)
    return (c1, c2) if c2 - c1 >= PACE_CUTS_MIN_GAP else None


@contextmanager
def mech_scope(data, rid: str):
    """The per-runner context the mechanics code reads: population priors, the
    runner's pace classes and an equipment step (mech_step_change) that restarts
    the baseline. assess() and the per-run views (run_compare, segment tests) use it."""
    keys = ("priors", "mech_since", "mech_step", "pace_cuts")
    saved = {k: getattr(_engine_ctx, k, None) for k in keys}
    try:
        _engine_ctx.priors = data.priors
        _engine_ctx.mech_since = _engine_ctx.mech_step = None
        _engine_ctx.pace_cuts = pace_cuts(data, rid)
        step = mech_step_change(data, rid)
        _engine_ctx.mech_step, _engine_ctx.mech_since = step, (step["date"] if step else None)
        yield
    finally:
        for k, v in saved.items():
            setattr(_engine_ctx, k, v)


def bucket_label(b: str) -> str:
    s, g, p = b.split("|")
    return f"{_SURF_LABEL.get(s, s)} · {_GRADE_LABEL[g]} · {_PACE_LABEL[p]}"


# ---------------------------------------------------------------- queries
def is_run(a) -> bool:
    return (a.sport or "running") == "running"


EXCLUDE_SCOPES = ("all", "mech", "load")


def counts_for(a, purpose: str = "all") -> bool:
    """Does this activity count for `purpose`? A run excluded with scope "all"
    (or the legacy NULL) counts nowhere; scope "mech" / "load" only takes it out of
    that side (feedback railway#47). purpose "all" = strictest (any exclusion)."""
    if not a.excluded:
        return True
    scope = a.excluded_scope or "all"
    if purpose == "all" or scope == "all":
        return False
    return scope != purpose


def all_acts(db, rid: str, purpose: str = "load"):
    """Every activity the engine counts — without the ones the runner excluded
    for this purpose. All sports feed systemic load, so the default is "load".
    `db` is a RunnerData snapshot (or a session, which loads one). For mechanics,
    runs before an equipment step (mech_scope) no longer count."""
    since = getattr(_engine_ctx, "mech_since", None) if purpose == "mech" else None
    return [a for a in D.of(db, rid).activities if counts_for(a, purpose) and (since is None or a.started_at >= since)]


def acts(db: DBSession, rid: str, purpose: str = "mech"):
    """Running activities only — the mechanics engine (cadence, vertical ratio,
    ground contact, descent, terrain buckets) is running-specific. Cross-training
    reaches load() via all_acts()/running-equivalent km, not here. Pass
    purpose="load" for the running km / descent that feed the load axis."""
    return [a for a in all_acts(db, rid, purpose) if is_run(a)]


# Fallback load per minute by sport, used only when a session has neither heart
# rate nor a Garmin training load to work from.
_SPORT_LPM = {"running": 1.0, "cycling": 0.85, "swimming": 1.1, "strength": 0.7,
              "rowing": 1.0, "elliptical": 0.8, "hiking": 0.6, "walking": 0.4, "other": 0.8}


def hr_bounds(runs, dailies, birth_year=None, measured=None):
    """Estimate the runner's HR max / resting HR for TRIMP. HR max is anchored on
    their own hardest sessions (avg HR + margin), and — when a birth year is on
    file — the age estimate (Tanaka 2001: 208 − 0.7·age) replaces the flat 185
    floor, which overestimates HR max for older runners and so understates
    HR-reserve / TRIMP. Never below the runner's own hardest observed effort.
    A MEASURED HR max from the profile (plan C2) replaces the estimate — only
    never below the hardest average HR actually recorded.
    Resting HR is the median of recorded daily readings."""
    hrs = [a.avg_hr for a in runs if a.avg_hr]
    rhrs = sorted(d.resting_hr for d in dailies if d.resting_hr)
    rhr = rhrs[len(rhrs) // 2] if rhrs else 50.0
    if measured:
        return max(float(measured), max(hrs, default=0.0)), rhr
    observed = (max(hrs) + 10) if hrs else 0.0
    est = 185.0
    if birth_year:
        age = today_date().year - int(birth_year)
        if 8 < age < 100:
            est = clamp(208 - 0.7 * age, 150.0, 210.0)
    return max(est, observed), rhr


# ---------------------------------------------------------------- cross-training
# Two load pathways (Vanrenterghem et al., 2017): every sport adds physiological
# load (the systemic channel), only running loads the running tissues. Strength
# work adds its own local load and a short carry-over into running intensity.
STRENGTH_FOCUS = ("lower", "upper", "full")
STRENGTH_TYPES = ("heavy", "explosive", "plyo", "circuit")
# HR max per sport when the runner has no hard sessions of that sport yet:
# cycling 6–10 bpm below running in triathletes (Millet et al., 2009) → 8;
# swimming 11 bpm below treadmill running, "reduce by 12" (DiCarlo et al., 1991).
SPORT_HR_OFFSET = {"cycling": 8.0, "swimming": 12.0}
SPORT_HR_MIN_SESSIONS = 5
# Session RPE × minutes (Foster et al., 2001) → TRIMP units, fitted per runner on
# runs that carry both (regression through the origin). The default is the ratio of
# an easy and a tempo run computed with this engine's TRIMP (≈ 0.40–0.48): a working
# assumption until the runner has SRPE_K_MIN_RUNS rated runs with heart rate.
SRPE_K_DEFAULT = 0.45
SRPE_K_BOUNDS = (0.25, 0.8)
SRPE_K_MIN_RUNS = 8
STRENGTH_DEFAULT_RPE = 5          # an unrated strength session counts as moderate (working assumption)
STRENGTH_FOCUS_W = {"lower": 1.0, "full": 1.0, "upper": 0.3, None: 0.7}   # working assumptions


# Banister TRIMP weighting: y = 0.64·e^(b·HRR) with b = 1.92 for men and 1.67 for
# women (Banister, 1991; Morton, Fitz-Clarke & Banister, 1990). Unknown sex → 1.92.
TRIMP_B = {"m": 1.92, "f": 1.67}
TRIMP_B_DEFAULT = 1.92


def trimp_b(runner) -> float:
    return TRIMP_B.get(getattr(runner, "sex", None) or "", TRIMP_B_DEFAULT)


def _trimp(dur, hr, hrmax, rhr, b: float = TRIMP_B_DEFAULT):
    hrr = min(max((hr - rhr) / (hrmax - rhr), 0.0), 1.0)
    return dur * hrr * 0.64 * math.exp(b * hrr)


def feedback_rpe(db, rid: str) -> dict:
    """{activity id: session RPE the runner gave in the journal}."""
    return {f.activity_id: f.rpe for f in D.of(db, rid).feedback if f.rpe is not None}


def sport_hr_max(all_list, hrmax: float) -> dict:
    """HR max per cross-training sport: the running value minus the literature
    offset, raised to the runner's own hardest sessions of that sport (avg + 10,
    as hr_bounds does for running) once there are enough of them."""
    out = {}
    for sport, off in SPORT_HR_OFFSET.items():
        hrs = [a.avg_hr for a in all_list if (a.sport or "running") == sport and a.avg_hr]
        observed = (max(hrs) + 10) if len(hrs) >= SPORT_HR_MIN_SESSIONS else 0.0
        out[sport] = min(hrmax, max(hrmax - off, observed))
    return out


def srpe_k(all_list, rpe: dict, hrmax: float, rhr: float, b: float = TRIMP_B_DEFAULT) -> tuple[float, int]:
    """(TRIMP per sRPE·min, runs used) — the runner's own conversion or the default."""
    xs, ys = [], []
    for a in all_list:
        r = rpe.get(a.id) or a.rpe
        if is_run(a) and r and a.avg_hr and (a.duration_min or 0) > 0 and hrmax > rhr:
            xs.append(r * a.duration_min)
            ys.append(_trimp(a.duration_min, a.avg_hr, hrmax, rhr, b))
    if len(xs) < SRPE_K_MIN_RUNS:
        return SRPE_K_DEFAULT, len(xs)
    k = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    return clamp(k, *SRPE_K_BOUNDS), len(xs)


def load_context(db: DBSession, rid: str, all_list, hrmax: float, rhr: float) -> dict:
    data = D.of(db, rid)
    rpe = feedback_rpe(data, rid)
    b = trimp_b(data.runner)
    k, n = srpe_k(all_list, rpe, hrmax, rhr, b)
    return {"hr": sport_hr_max(all_list, hrmax), "k": k, "kRuns": n, "rpe": rpe, "b": b, "memo": {}}


def session_rpe(a, ctx: dict | None):
    return ((ctx or {}).get("rpe") or {}).get(a.id) or a.rpe


def session_load(a, hrmax: float = 190.0, rhr: float = 50.0, ctx: dict | None = None) -> float:
    """One session's training load in arbitrary units (AU, TRIMP scale). Running:
    Banister TRIMP from heart rate. Cross-training (with `ctx` from load_context):
    cycling by TRIMP against the cycling HR max, else session RPE; swimming by
    session RPE first (heart rate in water reads lower, DiCarlo et al., 1991), else
    TRIMP against the swimming HR max; strength by session RPE only, because heart
    rate doesn't reflect a lifting session (Sweet et al., 2004). Then Garmin's own
    training load, then duration × a per-sport constant (no source, last resort)."""
    memo = ctx.get("memo") if ctx is not None else None
    if memo is not None and a.id is not None:
        v = memo.get(a.id)
        if v is None:
            v = memo[a.id] = _session_load(a, hrmax, rhr, ctx)
        return v
    return _session_load(a, hrmax, rhr, ctx)


def _session_load(a, hrmax: float, rhr: float, ctx: dict | None) -> float:
    dur = a.duration_min or 0
    if dur <= 0:
        return 0.0
    sport = a.sport or "running"
    if ctx is None:                           # legacy path, kept for callers without a context
        if a.avg_hr and hrmax > rhr:
            return _trimp(dur, a.avg_hr, hrmax, rhr)
        if a.training_load:
            return float(a.training_load)
        if a.rpe:
            return dur * (a.rpe / 5.0)
        return dur * _SPORT_LPM.get(sport or "other", 0.8)
    k = ctx["k"]
    r = session_rpe(a, ctx)
    hm = ctx["hr"].get(sport, hrmax)
    if sport == "strength":
        if r:
            return dur * r * k
        if a.training_load:
            return float(a.training_load)
        return dur * STRENGTH_DEFAULT_RPE * k
    if sport == "swimming" and r:
        return dur * r * k
    if a.avg_hr and hm > rhr:
        return _trimp(dur, a.avg_hr, hm, rhr, ctx.get("b", TRIMP_B_DEFAULT))
    if r:
        return dur * r * k
    if a.training_load:
        return float(a.training_load)
    return dur * _SPORT_LPM.get(sport, 0.8)


def strength_exposure(a, ctx: dict | None) -> float | None:
    """Local strength load of one session: session RPE × minutes × body-region weight."""
    if (a.sport or "") != "strength" or not (a.duration_min or 0):
        return None
    r = session_rpe(a, ctx) or STRENGTH_DEFAULT_RPE
    return a.duration_min * r * STRENGTH_FOCUS_W.get(a.strength_focus, 0.7)


def heavy_lower(a, ctx: dict | None) -> bool:
    """A strength session hard enough on the legs to blunt the next 24–48 h of
    intensive running (Doma et al., 2017): lower-body or whole-body work rated
    ≥ 7, or heavy / plyometric lower-body work rated ≥ 5 (or unrated)."""
    if (a.sport or "") != "strength" or a.strength_focus == "upper":
        return False
    r = session_rpe(a, ctx)
    if r is not None and r >= 7:
        return True
    return a.strength_focus in ("lower", "full") and a.strength_type in ("heavy", "plyo") and (r is None or r >= 5)


# Running kinematics change 24–48 h after lower-body resistance work (Doma et al., 2017),
# so runs on the day of and the two days after a heavy lower-body session count half in
# the mechanics drift (the weight is a working assumption) and are labelled in the app.
POST_STRENGTH_DAYS = (0, 1, 2)
POST_STRENGTH_W = 0.5


def post_strength_dates(db, rid: str) -> frozenset:
    """Run dates that fall within POST_STRENGTH_DAYS of a heavy lower-body session."""
    data = D.of(db, rid)
    rows = [a for a in data.activities if a.sport == "strength"]
    if not rows:
        return frozenset()
    ctx = {"rpe": feedback_rpe(data, rid)}
    out = set()
    for a in rows:
        if counts_for(a, "all") and heavy_lower(a, ctx) and a.started_at:
            d0 = date.fromisoformat(a.started_at[:10])
            out |= {(d0 + timedelta(days=k)).isoformat() for k in POST_STRENGTH_DAYS}
    return frozenset(out)


def find_twin(db: DBSession, rid: str, sport: str, day: str, dur: float, manual: bool = False):
    """An activity of the same sport on the same day and of similar length (±35 %) —
    an imported one (manual=False) or a hand-logged one (manual=True)."""
    q = db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == sport,
                                         models.Activity.started_at == day)
    for a in q:
        if (a.provider == "manual") != manual:
            continue
        if a.duration_min and dur and abs(a.duration_min - dur) <= 0.35 * max(a.duration_min, dur):
            return a
    return None


def absorb_manual(db: DBSession, rid: str) -> int:
    """A watch recording that arrives after a hand-logged session of the same sport,
    day and length replaces it: the rating and the strength details move over."""
    moved = 0
    for m in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.provider == "manual").all():
        twin = find_twin(db, rid, m.sport, m.started_at, m.duration_min or 0)
        if twin is None:
            continue
        for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == m.id).all():
            has = db.query(models.ActivityFeedback).filter(models.ActivityFeedback.activity_id == twin.id).first()
            if has is None:
                f.activity_id = twin.id
            else:
                db.delete(f)
        twin.strength_focus = twin.strength_focus or m.strength_focus
        twin.strength_type = twin.strength_type or m.strength_type
        db.delete(m)
        moved += 1
    if moved:
        db.flush()
    return moved


def daily(db, rid: str, n: int):
    cutoff = day_ago(n)
    return [m for m in D.of(db, rid).daily if m.date > cutoff]


def daily_between(db, rid: str, newer: int, older: int, newer_inclusive: bool = True):
    """Nights with day_ago(older) < date <= day_ago(newer) (date < day_ago(newer) when
    not `newer_inclusive`), oldest first."""
    hi, lo = day_ago(newer), day_ago(older)
    return [m for m in D.of(db, rid).daily if m.date > lo and (m.date <= hi if newer_inclusive else m.date < hi)]


# ---------------------------------------------------------------- drift-z core
# Calibrated by Monte Carlo on synthetic runners through this exact code (no real
# change, normal and heavy-tailed run-to-run noise, ~4 runs/week): λ = 0.15 puts
# the chance that a metric shows as a signal (z ≥ 0.6) with NO real change at
# ≈ 5 % (λ = 0.3 gave ≈ 10–12 %, v1 ≈ 3.5 %), while still catching a +1 SD shift
# in the last 5 days ~3× as often as v1 (33 % vs 12 %) and over 14 days 67 % vs
# 42 %. L = 2.75 puts the "⚑ mechanika přetrvává" flag at ≈ 5 % with no change
# (was ≈ 28 % before the σ / direction / grouping fixes).
_V2_EWMA_LAMBDA = 0.15  # EWMA weight on the newest session (spec S7 said 0.3) [Calibrated]
_V2_EWMA_L = 2.75       # control-limit width in EWMA standard errors [Calibrated]
_V2_DELTA = 0.5         # "possible deviation" threshold, typical-error units [Calibrate]
_V2_CLEAR = 1.0         # "clear deviation" threshold, typical-error units [Calibrate]


# Direction in which each mechanics metric drifts toward risk (+1 = rising is
# bad, −1 = falling is bad). The v2 flags are one-sided: an improvement (e.g. a
# cadence increase from gait retraining) must never raise a warning chip, just as
# it never adds score points. Stride/step length is judged at matched pace, where
# a longer step = a lower cadence (overstriding).
_BAD_SIGN = {
    "vert_ratio_pct": 1, "vratio_pct": 1, "gct_adj": 1, "gct_ms": 1, "vert_osc_cm": 1, "vo_cm": 1,
    "cadence_spm": -1, "stride_len_m": 1, "step_len_m": 1, "duty": 1,
}


def _ewma_flag(dis, bad=1):
    """Across-session EWMA control chart over a per-session drift-index series
    (oldest→newest, in the runner's own typical-error units). Returns the smoothed
    drift `z` plus the persistence/convergence label fields, or None if the series
    is empty. Shared by the per-run drift core and the Phase-5 segment path.

    The drift indices are already standardised by the runner's BASELINE noise, so
    the in-control σ is 1 by construction; the control limit uses the exact
    (time-varying) EWMA standard error for n sessions. It used to be scaled by the
    recent sessions' own spread, which made a trivially small but consistent
    deviation (DIs 0.05, 0.06, 0.05 …) look "beyond" the limits. All labels are
    one-sided in the metric's risk direction `bad`."""
    if not dis:
        return None
    lam = _V2_EWMA_LAMBDA
    e = 0.0
    for d in dis:
        e = lam * d + (1 - lam) * e
    n = len(dis)
    se = math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * n)))
    ctrl = _V2_EWMA_L * se
    eb = e * bad  # deviation measured in the risk direction
    last3 = dis[-3:]
    return {
        "z": r2(e), "ewma": r2(e), "latest": r2(dis[-1]), "ctrl": r2(ctrl), "se": r2(se), "nSessions": n,
        "beyond": eb > ctrl,
        "persist": eb > 0 and sum(1 for x in last3 if x * bad > 0) >= 2,
        "state": "clear" if eb >= _V2_CLEAR else ("possible" if eb >= _V2_DELTA else "usual"),
        "improving": eb <= -_V2_DELTA,
    }


def _speed_ms(a):
    km, mn = getattr(a, "distance_km", None) or 0, getattr(a, "duration_min", None) or 0
    return km * 1000.0 / (mn * 60.0) if km > 0 and mn > 0 else None


_PACE_MIN_RUNS = 8        # baseline runs needed to estimate the pace slope
_PACE_MIN_SPREAD = 0.15   # m/s — within-bucket speed spread (10–90 %) needed to estimate it [Calibrate]
_PACE_EXTRAP = 0.2        # m/s — how far past the baseline's speed range we extrapolate


def _pace_slope(base, field) -> float:
    """The runner's own sensitivity of `field` to running speed (units per m/s).

    Cadence, step length, ground contact, oscillation and vertical ratio all
    change with speed, and a terrain bucket spans a wide pace range (everything
    slower than 5:30/km is "volně"). Without this, easy runs done 15–25 s/km
    slower (heat, fatigue, simply running easier) read as mechanical drift and
    could push the runner into "silent drift" → a physio referral.

    Estimated WITHIN terrain buckets (each bucket centred on its own medians, so
    the bucket split itself can't create a slope) with Theil–Sen (median of
    pairwise slopes — robust to odd runs). 0 when the baseline has too few runs
    or too little speed variation to tell."""
    by = {}
    for a in base:
        v, sp = getattr(a, field), _speed_ms(a)
        if v is not None and sp is not None:
            by.setdefault(bucket(a), []).append((sp, v))
    pts = []
    for rows in by.values():
        if len(rows) < 3:
            continue
        ms, mv = median([r[0] for r in rows]), median([r[1] for r in rows])
        pts += [(sp - ms, v - mv) for sp, v in rows]
    if len(pts) < _PACE_MIN_RUNS:
        return 0.0
    xs = sorted(p_[0] for p_ in pts)
    if xs[int(0.9 * (len(xs) - 1))] - xs[int(0.1 * (len(xs) - 1))] < _PACE_MIN_SPREAD:
        return 0.0
    slopes = [(v2 - v1) / (s2 - s1) for i, (s1, v1) in enumerate(pts) for (s2, v2) in pts[i + 1:]
              if abs(s2 - s1) >= 0.03]
    return median(slopes) if len(slopes) >= 10 else 0.0


# v0.9.0 — weather as a confounder of running dynamics. Gait adapts to conditions, and
# differently in each runner (Ahamed et al., 2018: winter vs spring runs of the same
# runners, ~66 000 strides): so, like pace, the runner's OWN temperature sensitivity
# is estimated and removed, and runs on snow or ice are not scored against a baseline
# that has none (outside the model's domain, not a change in the runner).
SNOW_ICE_CODES = frozenset({56, 57, 66, 67, 71, 73, 75, 77, 85, 86})
_TEMP_MIN_RUNS, _TEMP_MIN_SPREAD, _TEMP_EXTRAP = 8, 8.0, 3.0   # runs, °C (10–90 %), °C past the baseline range
_WINTER_MIN_BASE = 3


def run_temp(a):
    """Air temperature during the run (°C) from its weather context, else None."""
    w = getattr(a, "weather_json", None) or {}
    if w.get("tempC") is not None:
        return float(w["tempC"])
    if w.get("tMin") is not None and w.get("tMax") is not None:
        return (float(w["tMin"]) + float(w["tMax"])) / 2
    return None


def winter_run(a) -> bool:
    """Snow, ice or freezing rain during the run (WMO weather code)."""
    return (getattr(a, "weather_json", None) or {}).get("code") in SNOW_ICE_CODES


def _temp_slope(base, val) -> float:
    """The runner's own sensitivity of the (pace-adjusted) metric to air temperature,
    per °C: Theil–Sen within terrain buckets, 0 without enough runs or spread."""
    by = {}
    for a in base:
        t = run_temp(a)
        if t is not None:
            by.setdefault(bucket(a), []).append((t, val(a)))
    pts = []
    for rows in by.values():
        if len(rows) < 3:
            continue
        mt, mv = median([r[0] for r in rows]), median([r[1] for r in rows])
        pts += [(t - mt, v - mv) for t, v in rows]
    if len(pts) < _TEMP_MIN_RUNS:
        return 0.0
    ts = sorted(p_[0] for p_ in pts)
    if ts[int(0.9 * (len(ts) - 1))] - ts[int(0.1 * (len(ts) - 1))] < _TEMP_MIN_SPREAD:
        return 0.0
    slopes = [(v2 - v1) / (t2 - t1) for i, (t1, v1) in enumerate(pts) for (t2, v2) in pts[i + 1:] if abs(t2 - t1) >= 2.0]
    return median(slopes) if len(slopes) >= 10 else 0.0


def _drift_z_core(A, field, recent_days):
    """Per-terrain-bucket drift of `field`: recent vs the runner's own baseline.

    v1 (standard): recent value = flat mean over the whole recent window, noise
    scale = baseline SD. A small change gets averaged away by older recent runs,
    so only a large or long-lasting shift crosses.

    v2 (sensitive): every recent run in a familiar terrain bucket becomes a drift
    index DI = (value − bucket median) / σ in the runner's own typical-error units,
    and the headline `z` is the across-session EWMA of those DIs (newest session
    weighted λ) — a fresh change dominates instead of being diluted, while one odd
    run is damped. σ is the bucket's outlier-trimmed SD, inflated for how well
    the baseline median itself is known (√(1 + π/2n)), so a DI is ~N(0, 1) when
    nothing changed (the earlier MAD-with-a-0.5·SD-floor scale was too small on
    small buckets and inflated z). The per-bucket `detail` and `baseMean`/
    `recMean` use the same EWMA session weights, so they decompose the headline
    z exactly and can't contradict its sign. The baseline excludes pain periods
    so the norm doesn't quietly absorb the drift. Same output shape.

    Both: values are first adjusted to the runner's typical baseline speed using
    their own speed sensitivity (_pace_slope), so a slower/faster pace inside a
    terrain bucket isn't mistaken for a change in form. `baseMean`/`recMean` and
    the per-bucket detail are in those pace-adjusted units; `series` stays raw."""
    v2 = _sensitive()
    from . import reference as REF
    _mp = mech_priors(field)
    s_rm = _mp["s_rm"] if _mp else None      # pooled repeated-measures SD (plan phase 1), None until enough runners
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
    winter_skipped = 0
    if sum(1 for a in base if winter_run(a)) < _WINTER_MIN_BASE:
        winter_skipped = sum(1 for a in rec if winter_run(a))
        rec = [a for a in rec if not winter_run(a)]
    if len(base) < 6 or len(rec) < 3:
        return None
    pslope = _pace_slope(base, field)
    base_sp = [sp for sp in (_speed_ms(a) for a in base) if sp is not None]
    ref_sp = median(base_sp) if base_sp else 0.0
    sp_lo = (min(base_sp) - _PACE_EXTRAP) if base_sp else 0.0
    sp_hi = (max(base_sp) + _PACE_EXTRAP) if base_sp else 0.0

    def val_p(a):
        """`field` at the runner's typical baseline speed."""
        v = getattr(a, field)
        sp = _speed_ms(a) if pslope else None
        return v if sp is None else v - pslope * (clamp(sp, sp_lo, sp_hi) - ref_sp)
    tslope = _temp_slope(base, val_p)
    base_t = [t for t in (run_temp(a) for a in base) if t is not None]
    ref_t = median(base_t) if base_t else 0.0
    t_lo, t_hi = (min(base_t) - _TEMP_EXTRAP, max(base_t) + _TEMP_EXTRAP) if base_t else (0.0, 0.0)

    def val(a):
        """`field` at the runner's typical baseline speed and temperature."""
        v = val_p(a)
        t = run_temp(a) if tslope else None
        return v if t is None else v - tslope * (clamp(t, t_lo, t_hi) - ref_t)
    by_b: dict[str, list[float]] = {}
    for a in base:
        by_b.setdefault(bucket(a), []).append(val(a))
    series = [getattr(a, field) for a in A if getattr(a, field) is not None][-26:]
    pace_out = {"paceSlope": round(pslope, 4), "paceAdjusted": bool(pslope),
                "tempSlope": round(tslope, 4), "tempAdjusted": bool(tslope), "winterSkipped": winter_skipped}
    if v2:
        return _drift_v2(field, rec, by_b, val, series, pace_out, s_rm)
    rec_b: dict[str, list] = {}
    for a in rec:
        rec_b.setdefault(bucket(a), []).append(a)
    num, den, n_scored = 0.0, 0.0, 0
    detail = []
    for b, recs in rec_b.items():
        bv = by_b.get(b)
        if not bv or len(bv) < 3:
            continue
        recvals = [val(a) for a in recs]
        center = mean(bv)
        s = max(REF.shrunk_sd(sd(bv), len(bv), s_rm), abs(center) * 0.012)   # plan phase 1
        now_val = mean(recvals)
        # Clamp per-bucket z so one degenerate bucket (near-constant baseline, or
        # an outlier/mislabelled run-walk) can't dominate the weighted drift.
        z = clamp((now_val - center) / s, -4, 4) if s else 0
        detail.append({
            "bucket": b, "label": bucket_label(b), "z": r2(z),
            "base": r2(center), "now": r2(now_val), "nBase": len(bv), "nNow": len(recs),
        })
        num += z * len(recs)
        den += len(recs)
        n_scored += len(recs)
    if not den:
        return None
    detail.sort(key=lambda d: -d["z"])
    bvals = [val(a) for a in base]
    return {
        "z": r2(num / den), "buckets": len(detail), "nRecent": n_scored, "detail": detail,
        "baseMean": r2(mean(bvals)),
        "recMean": r2(mean([val(a) for a in rec])),
        # plan phase 3: the individual reference SD behind the app's "usual range"
        # (shrunk towards the pooled s_RM), present only once population priors exist
        "refSd": round(REF.shrunk_sd(sd(bvals), len(bvals), s_rm), 3) if s_rm else None,
        "series": series, **pace_out,
    }


def _drift_v2(field, rec, by_b, val, series, pace_out, s_rm=None):
    """v2 body of _drift_z_core (see its docstring): per-session drift indices →
    EWMA, with the bucket detail and means built from the same session weights."""
    stats = {}
    for b, bv in by_b.items():
        if len(bv) < 3:
            continue
        _m, s_, _n = inlier_mean_sd(bv)
        if s_rm:
            from . import reference as REF
            s_ = REF.shrunk_sd(s_, len(bv), s_rm)   # plan phase 1
        c = median(bv)
        stats[b] = (c, max(s_, abs(c) * 0.012) * math.sqrt(1 + (math.pi / 2) / len(bv)), len(bv))
    # Domain of applicability: only sessions in a familiar terrain bucket are scored.
    sess = [(a, bucket(a)) for a in sorted(rec, key=lambda a: a.started_at) if bucket(a) in stats]
    if not sess:
        return None
    damp = _edamp()
    dis = [clamp((val(a) - stats[b][0]) / stats[b][1], -4, 4) * (POST_STRENGTH_W if a.started_at[:10] in damp else 1.0)
           for a, b in sess]
    flag = _ewma_flag(dis, _BAD_SIGN.get(field, 1))
    lam, n = _V2_EWMA_LAMBDA, len(dis)
    w = [lam * (1 - lam) ** (n - 1 - i) for i in range(n)]  # each session's weight in the final EWMA
    wsum = sum(w)
    per_b: dict[str, list] = {}
    for (a, b), wi, di in zip(sess, w, dis):
        per_b.setdefault(b, []).append((wi, di, val(a)))
    detail = []
    for b, items in per_b.items():
        wb = sum(x[0] for x in items)
        detail.append({
            "bucket": b, "label": bucket_label(b), "z": r2(sum(x[0] * x[1] for x in items) / wb),
            # Σ weight × z over buckets == the headline EWMA z (up to rounding)
            "weight": round(wb, 4), "base": r2(stats[b][0]),
            "now": r2(sum(x[0] * x[2] for x in items) / wb), "nBase": stats[b][2], "nNow": len(items),
        })
    detail.sort(key=lambda d: -d["z"])
    all_b = [v for bv in by_b.values() for v in bv]
    ref_sd = None
    if s_rm and len(all_b) >= 2:
        from . import reference as REF
        ref_sd = round(REF.shrunk_sd(sd(all_b), len(all_b), s_rm), 3)
    return {
        **flag, "refSd": ref_sd, "buckets": len(detail), "nRecent": n, "detail": detail,
        # EWMA-weighted, so recMean − baseMean has the sign of the headline z.
        "baseMean": r2(sum(wi * stats[b][0] for (a, b), wi in zip(sess, w)) / wsum),
        "recMean": r2(sum(wi * val(a) for (a, b), wi in zip(sess, w)) / wsum),
        "series": series, **pace_out,
    }


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
            weather_json=getattr(a, "weather_json", None),
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
            weather_json=getattr(a, "weather_json", None),
            duty=a.gct_ms * a.cadence_spm / 120000.0,  # GCT / stride-time (both legs)
        )
        for a in A
    ]
    return _drift_z_core(A2, "duty", RECENT)


MONTH_AGO_WINDOW_D = 7   # the comparable run may be up to a week younger than "a month ago", never older


def month_before(d: date) -> date:
    """Same day one calendar month earlier (31 Mar → 28/29 Feb)."""
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def comparable_month_ago(A: list, run):
    """The comparable run from a month before `run`: same terrain bucket (surface ·
    grade · pace class), dated from exactly one calendar month before up to
    MONTH_AGO_WINDOW_D days later — never older than a month. Closest to the
    one-month mark wins; a tie goes to the more similar distance. Returns
    (run or None, window_from, window_to)."""
    b = bucket(run)
    rd = date.fromisoformat(run.started_at[:10])
    lo = month_before(rd)
    hi = min(lo + timedelta(days=MONTH_AGO_WINDOW_D), rd - timedelta(days=1))
    cands = [x for x in A if x.id != run.id and x.started_at
             and lo.isoformat() <= x.started_at[:10] <= hi.isoformat() and bucket(x) == b]
    km = run.distance_km or 0

    def key(x):
        dist = abs(math.log((x.distance_km or 0.1) / km)) if km else 0.0
        return ((date.fromisoformat(x.started_at[:10]) - lo).days, dist)
    return (min(cands, key=key) if cands else None), lo, hi


def run_compare(db: DBSession, rid: str, aid: int | None = None):
    """A single run's key metrics next to the comparable run from a month before
    (comparable_month_ago) — the same kind of run on the same kind of terrain, so
    the difference is the runner, not the route. `aid=None` → the most recent run."""
    data = D.of(db, rid)
    saved = getattr(_engine_ctx, "pace_cuts", None)
    _engine_ctx.pace_cuts = pace_cuts(data, rid)     # the runner's own pace classes, as the engine uses
    try:
        return _run_compare(data, rid, aid)
    finally:
        _engine_ctx.pace_cuts = saved


def _run_compare(db, rid: str, aid: int | None):
    A = acts(db, rid)
    if not A:
        return None
    run = next((x for x in A if x.id == aid), None) if aid is not None else A[-1]
    if run is None:
        return None
    prev, lo, hi = comparable_month_ago(A, run)
    rd = date.fromisoformat(run.started_at[:10])
    defs = [("pace_s_km", "Tempo", "s/km", 0), ("cadence_spm", "Kadence", "spm", 0),
            ("stride_len_m", "Délka kroku", "m", 2), ("vert_ratio_pct", "Vertikální poměr", "%", 1),
            ("gct_ms", "Kontakt se zemí", "ms", 0), ("vert_osc_cm", "Vertikální oscilace", "cm", 1)]
    rnd_ = lambda v, dec: None if v is None else (round(v, dec) if dec else round(v))
    metrics = []
    for field, label, unit, dec in defs:
        v = getattr(run, field)
        if v is None:
            continue
        pv = getattr(prev, field) if prev is not None else None
        metrics.append({
            "key": field, "label": label, "unit": unit, "dec": dec,
            "value": rnd_(v, dec), "prev": rnd_(pv, dec),
            "diff": rnd_(v - pv, dec) if pv is not None else None,
        })
    return {
        "id": run.id, "date": run.started_at, "title": run.title, "surface": run.surface,
        "bucketLabel": bucket_label(bucket(run)), "distanceKm": run.distance_km,
        "paceSKm": rnd(run.pace_s_km) if run.pace_s_km else None,
        "prev": None if prev is None else {
            "id": prev.id, "date": prev.started_at, "title": prev.title, "distanceKm": prev.distance_km,
            "paceSKm": rnd(prev.pace_s_km) if prev.pace_s_km else None,
            "daysBefore": (rd - date.fromisoformat(prev.started_at[:10])).days,
        },
        "window": {"from": lo.isoformat(), "to": hi.isoformat()},
        "metrics": metrics,
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


def _descent_gradient_totals(activities, up: bool = False) -> list[float]:
    """Metres of descent (or, with up=True, of ascent) per 2.5 % gradient bucket."""
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
            drop = (alt1 - alt0) if up else (alt0 - alt1)
            if drop <= 0:
                continue  # the other direction or flat
            pct = drop / seg_dist * 100
            buckets[_gradient_bucket_index(pct)] += drop
    return buckets


def descent_by_gradient(db: DBSession, rid: str):
    A = [a for a in acts(db, rid, "load") if a.elevation_profile]
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


def ascent_by_gradient(db: DBSession, rid: str):
    """Feedback #160 — the last 7 days' ascent per gradient band (display only, no score)."""
    recent = [a for a in acts(db, rid, "load") if a.elevation_profile and a.started_at > day_ago(7)]
    b = _descent_gradient_totals(recent, up=True)   # empty week → zero bands (the detail says why)
    return {"buckets": [rnd(x) for x in b], "labels": GRADIENT_LABELS, "total7": rnd(sum(b)),
            "steep7": rnd(sum(b[STEEP_BUCKET_FROM:])), "nActivities7": len(recent)}


def decouple(db: DBSession, rid: str):
    A = [a for a in acts(db, rid) if a.vr_thirds and a.duration_min and a.duration_min >= 45]
    A = sorted(A, key=lambda a: a.started_at)[-8:]
    if len(A) < 4:
        return None
    vals = [r1((a.vr_thirds[2] / a.vr_thirds[0] - 1) * 100) for a in A]
    return {"series": vals, "dates": [a.started_at for a in A], "latest": vals[-1], "trend": r2(slope(vals)), "n": len(vals)}


def load(db: DBSession, rid: str):
    A = acts(db, rid, "load")            # running only — km volume bars, descent (load side)
    ALL = all_acts(db, rid, "load")      # every sport — drives systemic training load
    CROSS = [a for a in ALL if not is_run(a)]
    r = D.of(db, rid).runner
    hrmax, rhr = hr_bounds(A, daily(db, rid, 180), r.birth_year if r else None, r.hr_max if r else None)
    ctx = load_context(db, rid, ALL, hrmax, rhr)
    sl = lambda a: session_load(a, hrmax, rhr, ctx)

    # A session counts as high-intensity when its average HR sits at ≥80 % of
    # heart-rate reserve (≈ threshold / Z4+) — a hard tempo/interval effort.
    def hi(a):
        return bool(a.avg_hr) and hrmax > rhr and (a.avg_hr - rhr) / (hrmax - rhr) >= 0.80

    daily_km = []       # running km per day (volume view)
    daily_load = []     # training load (AU) per day across ALL sports (drives the load axis)
    daily_hi = []       # high-intensity training load (AU) per day (drives HI-ACWR)
    # One pass over the activities, grouped by day. Slice to the date component:
    # started_at is date-only from every current ingest path, but a bare `== k`
    # would silently zero the whole load axis if a datetime ever slipped in.
    by_day: dict[str, list] = {}
    for a in ALL:
        by_day.setdefault((a.started_at or "")[:10], []).append(a)
    for d in range(55, -1, -1):
        day_acts = by_day.get(day_ago(d), [])
        daily_km.append(sum(a.distance_km or 0 for a in day_acts if is_run(a)))
        daily_load.append(sum(sl(a) for a in day_acts))
        daily_hi.append(sum(sl(a) for a in day_acts if hi(a)))

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
    # v2 (Phase 3): terrain-load-weighted km per run (Minetti cost uphill, eccentric
    # load downhill) so a hilly run's true demand feeds the spike, not just its raw
    # distance. Only runs WITH an elevation profile are compared with each other.
    _v2 = _emode() == "v2"
    _ga = {id(a): terrain.load_km(a.elevation_profile) for a in runs} if _v2 else {}

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
        if _v2 and _ga.get(id(a)):
            prior_ga = [_ga[id(x)] for x in prior if _ga.get(id(x))]
            ga_r = (_ga[id(a)] / max(prior_ga)) if len(prior_ga) >= 3 else 0.0
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
        # basis = the component(s) that drove the spike: the top one plus any other
        # within 0.08 of it, e.g. "vzdálenost+terén". (With three components the old
        # "obojí" couldn't say which two.)
        comps = [("vzdálenost", best[1]), ("intenzita", best[2]), ("terén", best[3])]
        comps.sort(key=lambda kv: -kv[1])
        sess_spike_basis = "+".join(k for k, v in comps if v > 0 and comps[0][1] - v < 0.08) or comps[0][0]
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
    # rises to Achilles/plantar/tibial, vs *distance* to knee/shin; that study could
    # not measure pace itself). v0.9.0: like with like — the fastest grade-adjusted
    # run of the last 7 days against the runner's OWN fast runs of the 8–60 days
    # before (their 90th percentile, the fastest with < 10 runs), not the median of
    # all runs: a weekly tempo run used to count as a "spike" every week. Races and
    # runs under PACE_MIN_KM are left out (a race has its own recovery rule).
    pace_spike = pace_spike_run = pace_spike_ref = None
    fast = [a for a in runs if (a.duration_min or 0) > 0 and (a.distance_km or 0) >= PACE_MIN_KM and not is_race(a)]
    recent_fast = [a for a in fast if _days_ago(a) <= 7]
    base_speeds = sorted(grade_speed(a) for a in fast if 7 < _days_ago(a) <= PACE_BASE_DAYS)
    if recent_fast and len(base_speeds) >= 3:
        ref = base_speeds[-1] if len(base_speeds) < 10 else base_speeds[int(round(0.9 * (len(base_speeds) - 1)))]
        top = max(recent_fast, key=grade_speed)
        if ref > 0 and grade_speed(top) > ref:
            pace_spike, pace_spike_run, pace_spike_ref = r2(grade_speed(top) / ref), top, ref

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
        "sessionSpikeBasis": sess_spike_basis,  # "vzdálenost" / "intenzita" / "terén", "+"-joined when tied
        "spikeLatent": r2(latent) if latent > 0 else None,
        "spikeLatentDaysAgo": latent_days,
        "paceSpike": pace_spike,
        "paceSpikeAt": pace_spike_run.started_at if pace_spike_run else None,
        "paceSpikeId": pace_spike_run.id if pace_spike_run else None,
        "paceSpikeRefSKm": rnd(1000 / pace_spike_ref) if pace_spike_ref else None,
        # safe single-session ceiling: ~10% over the longest run of the last 30d
        "safeLongRunKm": r1(max([a.distance_km for a in runs if _days_ago(a) <= 30], default=0) * 1.1) or None,
        # v2 Phase 3 — terrain-aware load from the elevation profile (None when no
        # profile, e.g. summary-only Garmin imports).
        "gradeAdjKm7": (lambda g: r1(g) if g else None)(sum(terrain.grade_adjusted_km(a.elevation_profile, a.distance_km or 0) for a in w7 if a.elevation_profile)),
        "downhillKm7": (lambda d: r1(d) if d else None)(sum(terrain.downhill_exposure(a.elevation_profile)[0] for a in w7 if a.elevation_profile)),
    }


MONO_THR = 2.4         # Foster's monotony above which a week has no real easy days
MONO_V1_RATIO = 1.15   # v1/v2: monotony counts only while the 7:28 load ratio is above +15 %
PACE_MIN_KM = 3.0      # shorter runs (strides, a jog to the track) don't count for the pace spike
PACE_BASE_DAYS = 60


def is_race(a) -> bool:
    return any(w in (getattr(a, "title", None) or "").lower() for w in _RACE_WORDS)


def grade_speed(a) -> float:
    """Flat-equivalent speed (m/s): the run's speed × its grade cost factor."""
    return (_speed_ms(a) or 0.0) * grade_factor(a)


def hot_run(a) -> bool:
    """v0.8.4 — run in the heat (feels-like ≥ 24 °C during the run, weather.py):
    a higher heart rate there is heat strain, not lost fitness (Périard et al., 2015)."""
    return bool((getattr(a, "weather_json", None) or {}).get("hot"))


def minetti_cost(i: float) -> float:
    """Energy cost of running on grade i (J·kg⁻¹·m⁻¹), Minetti et al. (2002),
    valid for −0.45…+0.45 — one implementation, terrain.minetti_cr. Looney et al.
    (2026) find it accurate on the level and downhill, less so on steep climbs; an
    uphill-specific correction is not applied until its coefficients can be checked
    against the paper (v0.9.0: kept as a known limitation)."""
    return terrain.minetti_cr(i)


def grade_factor(a) -> float:
    """How much more a hilly run costs per metre than the same distance on the flat,
    from total ascent / descent (the climbing and descending parts assumed at the
    same average grade — no streams needed). 1.0 without elevation data."""
    km = getattr(a, "distance_km", None) or 0
    up, dn = getattr(a, "ascent_m", None) or 0, getattr(a, "descent_m", None) or 0
    if km <= 0 or up + dn < 1:
        return 1.0
    i = min((up + dn) / (km * 1000), 0.3)
    su = up / (up + dn)
    return (su * minetti_cost(i) + (1 - su) * minetti_cost(-i)) / minetti_cost(0)


def aerobic(db: DBSession, rid: str):
    cutoff = day_ago(21)
    # v0.8.4: hot runs left out — heat alone makes heart rate drift in the 2nd half
    A = [a for a in acts(db, rid, "load") if a.hr_thirds and a.pace_thirds and a.started_at > cutoff and not hot_run(a)]
    A = sorted(A, key=lambda a: a.started_at)[-5:]
    if len(A) < 3:
        return None
    v = [r1((a.hr_thirds[2] / a.pace_thirds[2]) / (a.hr_thirds[0] / a.pace_thirds[0]) * 100 - 100) for a in A]
    return {"latest": v[-1], "mean": r1(mean(v)), "series": v}


def recovery(db: DBSession, rid: str):
    rec = daily(db, rid, 7)
    base = daily_between(db, rid, 7, 35)
    if len(rec) < 4 or len(base) < 14:
        return None

    def f(arr, k):
        return [getattr(d, k) for d in arr if getattr(d, k) is not None]

    hrv_b, hrv_r = f(base, "hrv_ms"), f(rec, "hrv_ms")
    rhr_b, rhr_r = f(base, "resting_hr"), f(rec, "resting_hr")
    sl_b, sl_r = f(base, "sleep_h"), f(rec, "sleep_h")
    # v0.9.0 — HRV judged as Ln rMSSD (Plews et al., 2013; Schaffarczyk & Sperlich, 2026):
    # the log scale is where its day-to-day noise is roughly constant.
    lb, lr = [math.log(x) for x in hrv_b if x > 0], [math.log(x) for x in hrv_r if x > 0]
    hrv_z = r2((mean(lr) - mean(lb)) / sd(lb)) if len(lb) > 1 and lr and sd(lb) else 0
    rhr_z = r2((mean(rhr_r) - mean(rhr_b)) / sd(rhr_b)) if sd(rhr_b) else 0
    sleep_debt = r1((mean(sl_b) - mean(sl_r)) * 7)
    # v0.9.0 — the single-night "Regenerace" score (each night's own z-scores) is gone:
    # single nights mislead (Plews et al., 2012: 63.6 % of a well-training athlete's
    # single-day HRV fell outside the meaningful range; 2013: 10 km form tracked the
    # weekly mean, r = −0.76, not single days, r = −0.17). Readiness (capacity.py) is
    # the one recovery score: 7-night means, enough valid nights, the runner's norm.
    # railway#138 — `sd` = the 28-day spread, the usual-range band of the detail charts.
    hsd, rsd, ssd = sd(hrv_b), sd(rhr_b), sd(sl_b)
    out = {
        "hrv": {"base": r1(mean(hrv_b)), "sd": r1(hsd) if hsd else None, "now": r1(mean(hrv_r)), "z": hrv_z, "series": hrv_r, "log": True},
        "rhr": {"base": r1(mean(rhr_b)), "sd": r1(rsd) if rsd else None, "now": r1(mean(rhr_r)), "z": rhr_z, "series": rhr_r},
        "sleep": {"base": r1(mean(sl_b)), "sd": r1(ssd) if ssd else None, "now": r1(mean(sl_r)), "debt": sleep_debt, "series": sl_r},
        "edited": len([d for d in rec if d.source == "manual"]),
    }
    # railway#138 — HRV, resting HR and sleep night by night for the charts in the readiness
    # detail on Zátěž; live assessment only, not the history replay
    if getattr(_today_override, "value", None) is None:
        rows = daily(db, rid, RECOVERY_HISTORY_DAYS)
        hist = [{"d": m.date[:10], "hrv": r1(m.hrv_ms), "rhr": r1(m.resting_hr), "sleep": r1(m.sleep_h)}
                for m in sorted(rows, key=lambda m: m.date)
                if m.hrv_ms is not None or m.resting_hr is not None or m.sleep_h is not None]
        if len(hist) >= 7:
            out["history"] = hist
    return out


RECOVERY_HISTORY_DAYS = 60


def hrv_cv(db: DBSession, rid: str):
    """v0.4 — HRV day-to-day coefficient of variation (volatility), distinct
    from `recovery().hrv` which tracks the mean level. Compares CV over the
    last 7 days to CV over the preceding 28-day window."""
    rec = daily(db, rid, 7)
    base = daily_between(db, rid, 7, 35)
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
    base = daily_between(db, rid, 14, 49)
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
    from .capacity import rest_share
    week = daily(db, rid, 7)
    rec = [d.sleep_efficiency for d in week if d.sleep_efficiency is not None]
    base = daily_between(db, rid, 8, 56)
    base_v = [d.sleep_efficiency for d in base if d.sleep_efficiency is not None]
    # feedback railway#33 — quality, not only length: deep + REM share of the
    # staged sleep against the runner's own 8-week normal
    rs_now = [x for x in (rest_share(d) for d in week) if x is not None]
    rs_base = [x for x in (rest_share(d) for d in base) if x is not None]
    if len(rec) < 3 and len(rs_now) < 3:
        return None
    last = max(week, key=lambda d: d.date, default=None)
    out = {"now": r2(mean(rec)) if len(rec) >= 3 else None, "base": r2(mean(base_v)) if base_v else None, "n": len(rec)}
    if len(rs_now) >= 3:
        out["restNow"] = r2(mean(rs_now))
        out["restBase"] = r2(mean(rs_base)) if len(rs_base) >= 10 else None
        if last is not None and last.deep_min is not None:
            out["lastNight"] = {"date": last.date, "deepMin": rnd(last.deep_min), "remMin": rnd(last.rem_min or 0),
                                "lightMin": rnd(last.light_min or 0), "awakeMin": rnd(last.awake_min or 0)}
    # railway#114 — nights of the last 60 days (total sleep, deep and REM) for the chart under
    # the sleep quality overview; live assessment only, not the history replay
    if getattr(_today_override, "value", None) is None:
        rows = daily(db, rid, SLEEP_HISTORY_DAYS)
        hist = [{"d": m.date[:10], "sleep": r1(m.sleep_h), "deep": rnd(m.deep_min), "rem": rnd(m.rem_min)}
                for m in sorted(rows, key=lambda m: m.date) if m.sleep_h is not None or m.deep_min is not None]
        if len(hist) >= 7:
            out["history"] = hist
    return out


SLEEP_HISTORY_DAYS = 60


def feedback(db: DBSession, rid: str):
    fb = sorted(D.of(db, rid).feedback, key=lambda f: f.submitted_at)
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
        "lastNiggleAt": max((f.submitted_at for f in niggles), default=None),
        "niggleRate": r2(len(niggles) / len(rec)),
        "topSite": {"site": top_site[0], "n": top_site[1]} if top_site else None,
        "feelingMean": r1(mean(feels)), "feelingTrend": r2(slope(feels)),
        "painMax": max(pains) if pains else 0,
        "recent": [D.row_dict(f) for f in rec[-8:]],
    }


def stiffness_pattern(db: DBSession, rid: str):
    """v0.5 — self-reported pre-run leg stiffness, gathered retrospectively
    at rating time ("how stiff were your legs before this run"), tracked
    over time. Rising stiffness alone is a symptom signal like any other;
    the more specific pattern this looks for is stiffness the runner trained
    hard through anyway (RPE>=6) — an inability to back off when the body's
    already signalling, not just the signal itself."""
    fb = sorted((f for f in D.of(db, rid).feedback if f.stiffness_pre is not None), key=lambda f: f.submitted_at)
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
    needs. `substantial` mirrors the OSTRC definition (a moderate or severe
    reduction in participation, training volume or performance, i.e. an item at
    >= 17; Clarsen et al., 2013 — v0.9.0 adds the volume item)."""
    cutoff = day_ago(28)
    rows = D.stable_desc((x for x in D.of(db, rid).injuries if x.submitted_at > cutoff), lambda x: x.submitted_at)
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
            "substantial": max(active.q_participation or 0, active.q_volume or 0, active.q_performance or 0) >= 17,
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
    "zákolen", "zakolen", "vzpřimovač", "vzprimovac", "gastrocnem", "soleus",
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

    data = D.of(db, rid)
    for ck in data.checkins:
        if ck.submitted_at > cut:
            for p in (ck.pain_points or []):
                add(p.get("region"), ck.submitted_at)
    for f in data.feedback:
        if f.submitted_at > cut:
            for p in (f.pain_points or []):
                add(p.get("region"), f.submitted_at)
    for r in data.injuries:
        if r.submitted_at > cut:
            for p in (r.pain_points or []):
                add(p.get("region"), r.submitted_at)
    return dates


RECUR_MIN_DAYS = 3     # same running-relevant site on ≥ 3 different days in 28 = recurring
# v0.9.0 — men get proportionally more Achilles tendinopathy (Kakouris et al., 2021,
# citing Francis et al., 2019), so for them an Achilles / calf mark on 2 days already
# counts as recurring (working assumption on the threshold).
RECUR_MIN_DAYS_MEN_ACHILLES = 2
_ACHILLES_CALF_KEYS = ("achill", "lýtk", "lytk", "calf", "gastrocnem", "soleus")


def _recur_min_days(sex: str, region) -> int:
    r = str(region or "").lower()
    if sex == "m" and any(k in r for k in _ACHILLES_CALF_KEYS):
        return RECUR_MIN_DAYS_MEN_ACHILLES
    return RECUR_MIN_DAYS
PRIOR_UNKNOWN_MONTHS = 6   # a prior injury with no date counts as recent (prevention plan A5)
FUNCTION_WINDOW_DAYS = 2   # a check-in saying pain limits movement counts today and tomorrow (A1)
ACUTE_WINDOW_DAYS = 4      # an acute-overload report counts on its day and the 3 after (A2)
MAX_EFFORT_WINDOW = 21     # races / maximal efforts looked back for recovery blocks (A3)
RTR_FACTORS = (0.50, 0.75, 0.90)   # B3: weekly volume after a resolved injury, weeks 1–3 (of the pre-injury week)
RTR_NO_QUALITY_DAYS = 14           # B3: no intensity for this long after it's resolved
RACE_EFFORT_GAP = 14               # B4: a race this close after a maximal effort (or another race) is a risk
RACE_DAY_READY_MIN = 50            # B4: race-day warning below this readiness…
RACE_DAY_PAIN_DAYS = 7             # …or with running pain reported in these last days
PAIN_MORNING_MIN = 2       # B2: next-morning pain from this level counts (1/10 is noise)
PAIN_TREND_RISE = 1.0      # B2: weekly mean pain up by this much…
PAIN_TREND_MIN = 2.0       # …to at least this level = rising week to week
_RACE_WORDS = ("marathon", "maraton", "race", "závod", "zavod", "parkrun", "10k", "5k", "půlmaraton")
_SIDE_CZ = {"left": "vlevo", "right": "vpravo", "both": "oboustranně"}


# ---------------------------------------------------------------- v0.9.3 pain episodes
# Owner feedback 2026-09-30: marking the same spot again must not restart its weight
# automatically, and marking it over several runs must not keep raising the score until
# it is reported as an injury. Per running-relevant site, a level 0–1 of its pain
# still counts, walked day by day through the window:
#  • the first mark sets it to 1;
#  • a later mark is compared with the earlier marks at the same site: below their
#    median it changes nothing, from the median to the 75th percentile it lifts the level
#    halfway back to 1, above the 75th percentile it resets it to 1;
#  • a day with a check-in or a rated activity that does NOT mark the site counts as the
#    pain having passed: the 1st such day halves the level, the 2nd halves it again, the
#    3rd ends the episode (0);
#  • with nothing reported at all the level halves every SYMP_HALF_LIFE days (backstop).
# The points then follow the level and the intensity that set it, never the number of
# marks. Thresholds and steps are the owner's rules, working assumptions (no study
# prescribes them); the pain-monitoring idea behind "pain must settle" is Silbernagel
# et al. (2007).
EPISODE_CLEAN_STEPS = (0.5, 0.25, 0.0)   # level after the 1st, 2nd and 3rd clean day
EPISODE_MIN_I = 1                        # a marked spot without a number counts as 1/10


def _q(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def pain_episodes(db: DBSession, rid: str, window: int = 28) -> dict:
    """{"region|side": {region, side, level, ref, days, last, marks, clean, median, p75, how,
    label}} for every running-relevant site (left and right apart) marked in check-ins or
    run ratings inside the window. `ref` = the intensity that last set the level, `how` =
    what the latest mark did ("first" / "reset" / "partial" / "kept"), `clean` = clean
    days since it."""
    data = D.of(db, rid)
    cut = day_ago(window)
    today = today_date()
    marks: dict = {}                           # (region, side) -> {day: intensity}
    obs = set()                                # days with a check-in or a rated activity

    def mark(region, side, day, i):
        reg = _norm_region(region)
        if not reg or not _run_relevant(reg):
            return
        d = marks.setdefault((reg, _SIDE_KEY.get(side or "", "")), {})
        d[day] = max(d.get(day, 0), max(EPISODE_MIN_I, i or 0))

    for c in data.checkins:
        if c.submitted_at > cut:
            day = c.submitted_at[:10]
            obs.add(day)
            for p in (c.pain_points or []):
                mark(p.get("region"), p.get("side"), day, c.pain_score)
    for f, started in _rated_runs(data, cut, strict=True):
        day = (started or f.submitted_at)[:10]
        obs.add(day)
        pts = [p for p in (f.pain_points or []) if p.get("region")]
        if pts:
            for p in pts:
                mark(p.get("region"), p.get("side"), day, f.pain_during)
        else:
            for reg in _sites(None, f.pain_site if (f.niggle or (f.pain_during or 0) >= 1) else None):
                mark(reg, None, day, f.pain_during)
    out = {}
    for (reg, side), byday in marks.items():
        first = min(byday)
        level, ref, clean, prev, how, med, p75, last_obs = 0.0, 0, 0, [], "first", None, None, first
        for day in sorted(d for d in obs | set(byday) if d >= first):
            if day in byday:
                i = byday[day]
                if not prev:
                    level, ref, how = 1.0, i, "first"
                else:
                    med, p75 = _q(prev, 0.5), _q(prev, 0.75)
                    if i > p75:
                        level, ref, how = 1.0, i, "reset"
                    elif i >= med:
                        level, ref, how = level + (1 - level) / 2, max(ref, i), "partial"
                    else:
                        how = "kept"
                prev.append(i)
                clean = 0
            else:
                clean += 1
                level = level * 0.5 if clean < len(EPISODE_CLEAN_STEPS) else 0.0
            last_obs = day
        gap = max(0, (today - date.fromisoformat(last_obs)).days)
        level *= 0.5 ** (gap / SYMP_HALF_LIFE)
        lbl = _REGION_LABEL.get(str(reg).lower(), reg)
        out[f"{reg}|{side}"] = {"region": reg, "side": side, "level": round(level, 3), "ref": ref, "days": len(byday),
                                "last": max(byday), "marks": prev, "clean": clean, "median": med, "p75": p75, "how": how,
                                "label": f"{lbl} ({side})" if side else lbl}
    return out


def episode_points(ep: dict, top: float = 40.0) -> float:
    """Points of a site's episode: the level × what the intensity that set it is worth
    (1/10 → 15 … 9/10 → 39, top 40 — the old repeated-niggle range, working assumption)."""
    return ep["level"] * clamp(12 + 3 * (ep["ref"] or 0), 15, top)


def recurring_pain(db: DBSession, rid: str, window: int = 28):
    """The running-relevant site marked on the most different days in the window, when
    that's ≥ RECUR_MIN_DAYS (2 for a man's Achilles / calf) and its episode still counts
    (v0.9.3: three clean days end it) — {site, days, last, level, ref} — else None."""
    data = D.of(db, rid)
    sex = getattr(data.runner, "sex", None) or ""
    best = None
    for key, ep in pain_episodes(db, rid, window).items():
        if ep["level"] <= 0.01 or ep["days"] < _recur_min_days(sex, ep["region"]):
            continue
        if best is None or (ep["days"], ep["level"]) > (best["days"], best["level"]):
            best = {"site": ep["label"], "days": ep["days"], "last": ep["last"], "level": ep["level"], "ref": ep["ref"],
                    "region": ep["region"], "side": ep["side"]}
    return best


PRIOR_HIT_WINDOW = 14     # feedback railway#91: a mark at a previously injured site counts for 14 days
_SIDE_KEY = {"left": "L", "right": "P", "L": "L", "P": "P"}


def _region_aliases(x) -> set:
    """Lower-case names a region may go by: the key ("achilles"), its Czech label and
    the raw text, so a profile entry "ITB" matches a diary point "IT pás"."""
    x = (x or "").strip().lower()
    out = {x} if x else set()
    for k, lbl in _REGION_LABEL.items():
        lb = lbl.lower()
        if x == k or x == lb or lb in x or (len(k) >= 4 and k in x):
            out |= {k, lb}
    return out


def _site_matches(region, side, site) -> bool:
    r = (region or "").strip().lower()
    if not r:
        return False
    hit = any(a == r or (len(a) >= 4 and a in r) for a in site["aliases"])
    if not hit:
        return False
    s1, s2 = _SIDE_KEY.get(side or ""), site.get("side")
    return not (s1 and s2 and s1 != s2)


def prior_injury_sites(db: DBSession, r, rid: str) -> list[dict]:
    """Previously injured sites: the profile's prior injury and injury reports from
    the last 12 months, each with its side and months since the injury."""
    sites = []
    if r and r.prior_injury:
        al = _region_aliases(r.prior_injury)
        low = r.prior_injury.lower()
        for key, lbl in _REGION_LABEL.items():
            if key in low or lbl.lower() in low:
                al |= {key, lbl.lower()}
        sites.append({"aliases": al, "side": _SIDE_KEY.get(getattr(r, "prior_injury_side", None) or ""),
                      "months": injury_months(r), "label": r.prior_injury, "profile": True})
    for rep in (x for x in D.of(db, rid).injuries if x.submitted_at > day_ago(365)):
        try:
            months = max(0, (today_date() - date.fromisoformat(str(rep.submitted_at)[:10])).days // 30)
        except ValueError:
            months = 0
        regs = [(rep.body_region, rep.body_side)] + [(pp.get("region"), pp.get("side")) for pp in (rep.pain_points or [])]
        for reg, sd in regs:
            if reg:
                sites.append({"aliases": _region_aliases(reg), "side": _SIDE_KEY.get(sd or ""), "months": months,
                              "label": _REGION_LABEL.get(reg, reg), "profile": False})
    return sites


def prior_site_hits(db: DBSession, rid: str, sites: list[dict], window: int = PRIOR_HIT_WINDOW) -> dict | None:
    """Pain marked at a previously injured site in check-ins or run ratings within the
    window: any intensity, even once (a new site needs recurrence or pain ≥ 3 first)."""
    if not sites:
        return None
    cut = day_ago(window)
    days, labels, weights = set(), [], []

    def scan(points, when):
        for p in (points or []):
            for site in sites:
                if _site_matches(p.get("region"), p.get("side"), site):
                    days.add((when or "")[:10])
                    if p.get("region") not in labels:
                        labels.append(p.get("region"))
                    m = site["months"] if site["months"] is not None else PRIOR_UNKNOWN_MONTHS
                    weights.append((clamp(18 * (1 - m / 12), 6, 18), site))

    data = D.of(db, rid)
    for ck in data.checkins:
        if ck.submitted_at > cut:
            scan(ck.pain_points, ck.submitted_at)
    for f in data.feedback:
        if f.submitted_at > cut:
            scan(f.pain_points, f.submitted_at)
    if not days:
        return None
    w, site = max(weights, key=lambda x: x[0])
    return {"days": len(days), "weight": w, "labels": labels, "site": site, "last": max(days)}


# Desai, P., Jungmalm, J., Börjesson, M., Karlsson, J., & Grau, S. (2021). Recreational
#   runners with a history of injury are twice as likely to sustain a running-related
#   injury as runners with no history of injury: A 1-year prospective cohort study.
#   JOSPT, 51(3), 144–150. https://doi.org/10.2519/jospt.2021.9673
# van Poppel, D., van der Worp, M., Slabbekoorn, A., van den Heuvel, S. S. P., van
#   Middelkoop, M., Koes, B. W., Verhagen, A. P., & Scholten-Peeters, G. G. M. (2021).
#   Risk factors for overuse injuries in short- and long-distance running: A systematic
#   review. Journal of Sport and Health Science, 10(1), 14–28.
#   https://doi.org/10.1016/j.jshs.2020.06.006
def frailty_of(months) -> float:
    """How much an injury `months` ago lowers load tolerance (a multiplier ≥ 1; v3
    turns it into narrower safety margins). 1.20 right after it, fading to 1.06 at
    12 months; v0.9.0 keeps a residual 1.06 → 1.02 through 24 months instead of
    dropping to nothing at 12 — a history of injury doubled the risk in a 1-year
    cohort whatever its age (Desai et al., 2021, HR 1.9) and stayed the strongest
    predictor in the risk models (van Poppel et al., 2021). The fade = working assumption."""
    if months is None or months < 0:
        return 1.0
    if months <= 12:
        return 1 + clamp(0.20 * (1 - months / 12), 0.06, 0.20)
    if months <= 24:
        return 1.06 - 0.04 * (months - 12) / 12
    return 1.0


def injury_months(r) -> int | None:
    """Months since the runner's prior injury: from its date, else the months
    they entered, else PRIOR_UNKNOWN_MONTHS — an injury with no date is treated
    as recent rather than ignored (plan A5). None without a prior injury."""
    if not r or not r.prior_injury:
        return None
    if getattr(r, "prior_injury_date", None):
        try:
            return max(0, (today_date() - date.fromisoformat(str(r.prior_injury_date)[:10])).days // 30)
        except ValueError:
            pass
    if r.prior_injury_months_ago is not None:
        return r.prior_injury_months_ago
    return PRIOR_UNKNOWN_MONTHS


def _sites(points, site) -> list[str]:
    regs = [p.get("region") for p in (points or []) if p.get("region")]
    if not regs and site:
        regs = [x.strip() for x in str(site).split(",") if x.strip()]
    return list(dict.fromkeys(regs))


def function_limit(db: DBSession, rid: str):
    """Plan A1 — the latest check-in (today / yesterday) saying pain limits ordinary
    movement, made the runner limp, or shortened / changed a run. OSTRC logic:
    function, not the pain number, marks an injury — a 2/10 that makes you limp
    matters more than a 5/10 that doesn't. None when nothing was reported."""
    cut = day_ago(FUNCTION_WINDOW_DAYS - 1)
    rows = D.stable_desc((c for c in D.of(db, rid).checkins if c.submitted_at >= cut), lambda c: c.submitted_at)
    c = next((x for x in rows if x.limits_movement or x.limping or x.run_modified), None)
    if c is None:
        return None
    regs = _sites(c.pain_points, c.pain_site)
    if regs and not any(_run_relevant(x) for x in regs):
        return None                                   # an arm or shoulder doesn't stop running
    return {"at": c.submitted_at[:10], "site": ", ".join(regs) or None, "limitsMovement": bool(c.limits_movement),
            "limping": bool(c.limping), "runModified": bool(c.run_modified),
            "severe": bool(c.limits_movement or c.limping)}


def acute_overload(db: DBSession, rid: str):
    """Plan A2 — a report right after running that already says "too much":
    pain at ≥ 2 running-relevant sites, or soreness ≥ 7 with pain, or RPE 9–10
    with pain. Acts at once instead of waiting for pain to recur on 3 days.
    {at, daysSince, reasons, sites} of the latest trigger in the window, else None."""
    since = day_ago(ACUTE_WINDOW_DAYS - 1)
    trig = []
    data = D.of(db, rid)
    for c in (c for c in data.checkins if c.submitted_at >= since):
        sites = [x for x in _sites(c.pain_points, c.pain_site) if _run_relevant(x)]
        hurts = (c.pain_score or 0) >= 1 or bool(sites)
        why = []
        if len(sites) >= 2:
            why.append(f"bolest na {len(sites)} místech")
        if (c.soreness or 0) >= 7 and hurts:
            why.append(f"svalová bolest {c.soreness}/10")
        if why:
            trig.append((c.submitted_at[:10], why, sites))
    for f in (f for f in data.feedback if f.submitted_at >= since):
        sites = [x for x in _sites(f.pain_points, f.pain_site) if _run_relevant(x)]
        hurts = (f.pain_during or 0) >= 1 or bool(sites) or bool(f.niggle)
        why = []
        if len(sites) >= 2:
            why.append(f"bolest na {len(sites)} místech")
        if (f.rpe or 0) >= 9 and hurts:
            why.append(f"námaha {f.rpe}/10 s bolestí")
        if why:
            trig.append((f.submitted_at[:10], why, sites))
    if not trig:
        return None
    at = max(t[0] for t in trig)
    reasons = list(dict.fromkeys(w for t in trig for w in t[1]))
    sites = list(dict.fromkeys(x for t in trig for x in t[2]))
    return {"at": at, "daysSince": (today_date() - date.fromisoformat(at)).days, "reasons": reasons, "sites": sites}


_SIDE_OF = {"L": "left", "P": "right", "R": "right"}


def record_injury(db: DBSession, rid: str, rep) -> None:
    """Plan B3 — a reported injury (OSTRC severity > 0) becomes the runner's
    injury history: the site is added to prior_injury, and a NEW episode (no
    other active report) sets prior_injury_date / prior_injury_side, so injury
    history and frailty never depend on the profile being filled in by hand."""
    if not rep or (rep.severity or 0) <= 0:
        return
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is None:
        return
    others = (db.query(models.InjuryReport)
              .filter(models.InjuryReport.runner_id == rid, models.InjuryReport.status == "active",
                      models.InjuryReport.id != rep.id).count()) if rep.id else 0
    region = rep.body_region or next((p.get("region") for p in (rep.pain_points or []) if p.get("region")), None)
    site = re.sub(r"\s*\((L|P)\)$", "", str(region)).strip() if region else None
    if site and site.lower() not in (r.prior_injury or "").lower():
        r.prior_injury = f"{r.prior_injury}; {site}" if r.prior_injury else site
    elif not r.prior_injury:
        r.prior_injury = "zranění (nahlášené)"
    if others == 0 or not r.prior_injury_date:
        r.prior_injury_date = (rep.submitted_at or now_iso())[:10]
        sides = {_SIDE_OF.get(p.get("side")) for p in (rep.pain_points or [])} | {_SIDE_OF.get(rep.body_side)}
        sides.discard(None)
        r.prior_injury_side = "both" if len(sides) > 1 else (sides.pop() if sides else r.prior_injury_side)


def return_to_run(db: DBSession, rid: str):
    """Plan B3 — graded return after an injury the runner (or physio) marked as
    resolved: weeks 1–3 at 50 / 75 / 90 % of the pre-injury week, no intensity
    for the first 14 days. {site, injuryAt, resolvedAt, daysSince, week, factor,
    noQuality, physioPlan} while within 3 weeks of resolving, else None."""
    data = D.of(db, rid)
    reps = list(data.injuries)
    if any(x.status == "active" and (x.severity or 0) > 0 for x in reps):
        return None                                   # still injured — the injury override applies
    done = [x for x in reps if x.status == "resolved" and x.resolved_at and (x.severity or 0) > 0]
    if not done:
        return None
    last = max(x.resolved_at[:10] for x in done)
    days = (today_date() - date.fromisoformat(last)).days
    if not 0 <= days < 7 * len(RTR_FACTORS):
        return None
    episode = [x for x in done if x.resolved_at[:10] == last]
    first = min(episode, key=lambda x: x.submitted_at)
    wk = days // 7 + 1
    plan = next((p for p in data.rtr_plans if p.status == "active"), None)
    return {"site": _injury_site_label(first), "injuryAt": first.submitted_at[:10], "resolvedAt": last,
            "daysSince": days, "week": wk, "factor": RTR_FACTORS[wk - 1],
            "noQuality": days < RTR_NO_QUALITY_DAYS,
            "noQualityUntil": iso_date(date.fromisoformat(last) + timedelta(days=RTR_NO_QUALITY_DAYS)),
            "physioPlan": plan is not None}


def races_for(db, r) -> list[dict]:
    """Plan B4 — the race calendar, plus the profile's goal race (goal_race /
    goal_date) as an A race when the calendar has nothing on that day."""
    if r is None:
        return []
    today = today_date()
    out = [{"id": x.id, "date": x.date[:10], "name": x.name, "km": x.distance_km, "priority": x.priority or "B",
            "source": "calendar", "ascentM": x.ascent_m, "paceSKm": x.target_pace_s_km}
           for x in D.of(db, r.id).races]
    if r.goal_date and not any(o["date"] == str(r.goal_date)[:10] for o in out):
        out.append({"id": "goal", "date": str(r.goal_date)[:10], "name": r.goal_race, "km": None, "priority": "A",
                    "source": "profile", "ascentM": None, "paceSKm": None})
    for o in out:
        try:
            o["daysTo"] = (date.fromisoformat(o["date"]) - today).days
        except ValueError:
            o["daysTo"] = None
    return sorted((o for o in out if o["daysTo"] is not None), key=lambda o: o["date"])


def _race_name(x) -> str:
    return x.get("name") or ("cílový závod" if x.get("priority") == "A" else "závod")


def race_outlook(db: DBSession, rid: str, r, efforts: list[dict], readiness_score=None):
    """Plan B4 — what the calendar means today: {next, nextA, upcoming, warnings}
    or None without upcoming races. Warnings: a race within 14 days after a
    maximal effort or another race; on race day (or the day before) readiness
    under 50 % or running pain in the last 7 days."""
    races = races_for(db, r)
    upcoming = [x for x in races if 0 <= x["daysTo"] <= 120]
    if not upcoming:
        return None
    warnings = []
    for x in upcoming:
        if x["daysTo"] > 28:
            continue
        rd = date.fromisoformat(x["date"])
        near = [e for e in efforts if e["date"] != x["date"] and 0 < (rd - date.fromisoformat(e["date"])).days <= RACE_EFFORT_GAP]
        if near:
            e = max(near, key=lambda e: e["date"])
            gap = (rd - date.fromisoformat(e["date"])).days
            warnings.append({"kind": "effort_before", "race": x["date"], "gap": gap,
                             "text": f"{_race_name(x).capitalize()} ({x['date'][8:10].lstrip('0')}. {x['date'][5:7].lstrip('0')}.) "
                                     f"je jen {gap} dní po maximálním úsilí {e['date'][8:10].lstrip('0')}. "
                                     f"{e['date'][5:7].lstrip('0')}. ({_cz_num(e['km'])} km). Plné zotavení trvá ~{e['days']} dní — "
                                     "zvažte závod běžet jen jako trénink, nebo ho vynechat."})
        prev = [y for y in races if y["date"] < x["date"] and y["priority"] in ("A", "B") and x["priority"] in ("A", "B")
                and (rd - date.fromisoformat(y["date"])).days <= RACE_EFFORT_GAP and y["date"] not in {e["date"] for e in near}]
        if prev:
            y = prev[-1]
            gap = (rd - date.fromisoformat(y["date"])).days
            warnings.append({"kind": "races_close", "race": x["date"], "gap": gap,
                             "text": f"Dva závody {gap} dní po sobě ({_race_name(y)} → {_race_name(x)}) — na oba naplno "
                                     "není dost času na zotavení; jeden běžte jako trénink."})
    nxt = upcoming[0]
    if nxt["daysTo"] <= 1:
        why = []
        if readiness_score is not None and readiness_score < RACE_DAY_READY_MIN:
            why.append(f"připravenost {readiness_score} %")
        hurt = [p for p in _pain_reports(db, rid, day_ago(RACE_DAY_PAIN_DAYS - 1)) if p["pain"] >= PAIN_MORNING_MIN]
        if hurt:
            top = max(hurt, key=lambda p: p["pain"])
            why.append(f"bolest {top['pain']}/10 za posledních {RACE_DAY_PAIN_DAYS} dní"
                       + (f" ({', '.join(top['sites'][:2])})" if top["sites"] else ""))
        if why:
            warnings.append({"kind": "race_day", "race": nxt["date"], "gap": nxt["daysTo"], "why": why,
                             "text": f"{'Dnes' if nxt['daysTo'] == 0 else 'Zítra'} {_race_name(nxt)}, ale {' a '.join(why)}. "
                                     "Závod na hraně zotavení je častý začátek zranění — běžte jen v pohodlném tempu, "
                                     "nebo nestartujte; při bolesti během závodu zpomalte nebo odstupte."})
    nxt_a = next((x for x in upcoming if x["priority"] == "A"), None)
    return {"next": nxt, "nextA": nxt_a, "upcoming": upcoming[:8], "warnings": warnings}


def _rated_runs(data, since: str, strict: bool = False):
    """(rating, the rated run's started_at) for every rating whose run is on/after
    `since` (after it when `strict`) — the rating ⋈ activity join the engine used."""
    out = []
    for f in data.feedback:
        started = data.run_day(f)
        if started is None:
            continue
        if (started > since) if strict else (started >= since):
            out.append((f, started))
    return out


def _pain_reports(db, rid: str, since: str) -> list[dict]:
    """Running-relevant pain reports since `since`: check-ins by their day, run
    ratings by the RUN's day (pain during that run, even if rated later)."""
    out = []
    data = D.of(db, rid)
    for c in data.checkins:
        if c.submitted_at < since:
            continue
        sites = _sites(c.pain_points, c.pain_site)
        if sites and not any(_run_relevant(x) for x in sites):
            continue
        out.append({"day": c.submitted_at[:10], "kind": "checkin", "pain": c.pain_score or 0,
                    "sites": [x for x in sites if _run_relevant(x)]})
    for f, started in _rated_runs(data, since):
        sites = _sites(f.pain_points, f.pain_site)
        if sites and not any(_run_relevant(x) for x in sites):
            continue
        out.append({"day": started[:10], "kind": "run", "pain": f.pain_during or 0,
                    "sites": [x for x in sites if _run_relevant(x)]})
    return out


def pain_monitor(db: DBSession, rid: str):
    """Plan B2 — the pain-monitoring model (Silbernagel 2007): pain during a run
    may be tolerable, but it must settle by the next morning and must not grow
    from week to week. Returns {morningWorse, trend} (either may be None) or None.

    morningWorse — today's check-in shows more pain (≥ 2) at a site than was
                   reported during yesterday's run there → today no running.
    trend        — mean daily pain of the last 7 days ≥ 1 point above the 7
                   days before, reaching ≥ 2 → training is modified."""
    today = today_date()
    t_iso, y_iso = iso_date(today), iso_date(today - timedelta(days=1))
    reps = _pain_reports(db, rid, iso_date(today - timedelta(days=14)))
    morning = None
    ci = [r for r in reps if r["kind"] == "checkin" and r["day"] == t_iso and r["pain"] >= PAIN_MORNING_MIN]
    ran = [r for r in reps if r["kind"] == "run" and r["day"] == y_iso]
    if ci and ran:
        m = max(ci, key=lambda r: r["pain"])
        for site in (m["sites"] or [None]):
            # during = that run's pain at this site (0 when the rating didn't mark it)
            during = max((r["pain"] if (site is None or not r["sites"] or site in r["sites"]) else 0) for r in ran)
            if m["pain"] > during:
                morning = {"at": t_iso, "runDate": y_iso, "site": site, "morning": m["pain"], "during": during}
                break
    # weekly trend: per day the highest reported pain; a week needs ≥ 2 reported
    # days now and ≥ 1 before (no reports ≠ no pain, so missing days don't count)
    by_day: dict = {}
    for r in reps:
        by_day[r["day"]] = max(by_day.get(r["day"], 0), r["pain"])
    now = [v for d, v in by_day.items() if (today - date.fromisoformat(d)).days < 7]
    before = [v for d, v in by_day.items() if 7 <= (today - date.fromisoformat(d)).days < 14]
    trend = None
    # v0.8.5: the trend is about pain that keeps growing while training goes on; a
    # pain-free check-in this morning (< 2/10) means there is nothing growing today
    today_ci = [r["pain"] for r in reps if r["kind"] == "checkin" and r["day"] == t_iso]
    settled = bool(today_ci) and max(today_ci) < PAIN_MORNING_MIN
    if len(now) >= 2 and before and not settled:
        mn, mb = mean(now), mean(before)
        if mn - mb >= PAIN_TREND_RISE and mn >= PAIN_TREND_MIN:
            trend = {"now": r1(mn), "before": r1(mb), "daysNow": len(now), "daysBefore": len(before)}
    if not morning and not trend:
        return None
    return {"morningWorse": morning, "trend": trend}


# ---------------------------------------------------------------- v0.8.5 pain state
# How a pain episode ends. Pain-monitoring model: pain during activity may be
# acceptable when it settles by the next morning and does not grow week to week
# (Silbernagel et al., 2007); for bone, the right load gives no symptoms during,
# after or the day after, and running restarts after 5 pain-free days (Warden et
# al., 2021). So the morning check-in decides today, and pain-free check-ins lift
# the restrictions that older reports would otherwise keep for weeks.
CLEAR_CHECKINS = 2         # soft tissue: pain-free check-ins after the last pain (working assumption)
CLEAR_BONE_DAYS = 5        # bone-typical site: days without pain (Warden et al., 2021)
SYMP_HALF_LIFE = 7.0       # days: older pain reports count less on Příznaky (working assumption)
SYMP_CLEARED = 1 / 3       # what an old pain signal keeps after the clean streak (working assumption)


def _painful_checkin(c) -> bool:
    sites = _sites(c.pain_points, c.pain_site)
    if sites and not any(_run_relevant(x) for x in sites):
        return False                                   # an arm or shoulder isn't a running pain
    return (c.pain_score or 0) >= 1


def pain_state(db: DBSession, rid: str, window: int = 28) -> dict:
    """{todayPain, todaySites, cleanCheckins, lastPainDay, daysSincePain, cleared,
    boneLastDay, boneCleared}. todayPain is None without a check-in today.
    A check-in is clean at 0/10 with no running-relevant spot; a run rating counts
    as pain from 1/10, a niggle or a running-relevant spot (on the run's day)."""
    today = today_date()
    t_iso = iso_date(today)
    cut = day_ago(window)
    events = []                                            # (when, painful, sites, pain)
    data = D.of(db, rid)
    for c in data.checkins:
        if c.submitted_at <= cut:
            continue
        sites = [x for x in _sites(c.pain_points, c.pain_site) if _run_relevant(x)]
        events.append((c.submitted_at, _painful_checkin(c), sites, c.pain_score or 0, "checkin"))
    for f, started in _rated_runs(data, cut, strict=True):
        sites = [x for x in _sites(f.pain_points, f.pain_site) if _run_relevant(x)]
        hurt = (f.pain_during or 0) >= 1 or bool(f.niggle) or bool(sites)
        events.append((started or f.submitted_at, hurt, sites, f.pain_during or 0, "run"))
    pains = [e for e in events if e[1]]
    last_pain_at = max((e[0] for e in pains), default=None)
    clean_days = {e[0][:10] for e in events if e[4] == "checkin" and not e[1]
                  and (last_pain_at is None or e[0] > last_pain_at)}
    today_ci = [e for e in events if e[4] == "checkin" and e[0][:10] == t_iso]
    last_day = last_pain_at[:10] if last_pain_at else None
    bone_days = [e[0][:10] for e in pains if any(bone_site(x) for x in e[2])]
    bone_last = max(bone_days, default=None)
    since = (today - date.fromisoformat(last_day)).days if last_day else None
    bone_since = (today - date.fromisoformat(bone_last)).days if bone_last else None
    return {
        "todayPain": max((e[3] for e in today_ci), default=None) if today_ci else None,
        "todaySites": list(dict.fromkeys(x for e in today_ci for x in e[2])),
        "cleanCheckins": len(clean_days), "lastPainDay": last_day, "daysSincePain": since,
        "cleared": last_day is not None and len(clean_days) >= CLEAR_CHECKINS,
        "boneLastDay": bone_last,
        "boneCleared": bone_last is not None and bone_since >= CLEAR_BONE_DAYS and len(clean_days) >= CLEAR_CHECKINS,
    }


def pain_fade(age_days, cleared: bool) -> float:
    """Weight of an older pain signal on Příznaky: halves every SYMP_HALF_LIFE days
    and drops to SYMP_CLEARED once pain-free check-ins followed it."""
    f = 0.5 ** (max(0, age_days or 0) / SYMP_HALF_LIFE)
    return f * (SYMP_CLEARED if cleared else 1.0)


# ---------------------------------------------------------------- v0.8.4 screening
# Safety rules that sit above the load logic (literature review 2026-09, section H).
CHECKIN_FLAGS = ("ill", "bone_walk", "bone_rest", "bone_earlier", "red_cauda", "red_systemic")
HR_PACE_BPM = 6            # heart rate ≥ 6 bpm over the usual for the pace across ≥ 3 runs (working assumption)
HRV_HIGH_Z = 1.5           # 7-night HRV this far above the norm counts as "high" (working assumption)
HRV_CV_LOW = 0.6           # v0.9.0: day-to-day HRV variation this far below usual counts as "unusually stable"
BONE_PAIN_MIN = 3           # bone-typical site: from 3/10 the Silbernagel "≤ 5 is fine" allowance doesn't apply
# v0.9.0 — female sex is a recognised bone stress injury risk factor (Warden et al.,
# 2014; Toczyłowska et al., 2025; stress-fracture runners were more often women in Hoffman
# & Krishnan, 2014), so for women the bone-pain rule starts at 2/10 (working assumption).
BONE_PAIN_MIN_SEX = {"f": 2}
SCREEN_WINDOW_DAYS = 2      # a screening answer counts today and tomorrow (like the function rule, A1)
# Typical bone stress injury sites in runners (Warden et al., 2014): tibial shaft,
# metatarsals, navicular (midfoot), calcaneus. Plantar fascia / tendon insertions excluded.
_BONE_KEYS = ("holeň", "holen", "shin", "tibial", "bérec", "berec", "metatar", "nárt", "nart", "pata", "chodidl", "foot")
_NOT_BONE = ("plantár", "plantar", "fasci", "achill", "úpon", "upon", "šlach", "slach")
_BACK_KEYS = ("páteř", "pater", "bederní", "bederni", "lowback", "si kloub", "kříž", "kriz")


def clean_checkin_flags(d) -> dict | None:
    """Only the known yes/no screening answers, as booleans (None when nothing was answered)."""
    if not isinstance(d, dict):
        return None
    out = {k: bool(d[k]) for k in CHECKIN_FLAGS if k in d and d[k] is not None}
    return out or None


def bone_site(region) -> bool:
    r = (region or "").lower()
    return any(k in r for k in _BONE_KEYS) and not any(k in r for k in _NOT_BONE)


def back_site(region) -> bool:
    r = (region or "").lower()
    return any(k in r for k in _BACK_KEYS)


def _flags(c) -> dict:
    return getattr(c, "flags", None) or {}


def screening(db: DBSession, rid: str) -> dict:
    """v0.8.4 — screening answers and tissue-specific pain rules.

    redFlag    — low-back pain with bladder / bowel change or saddle numbness
                 (cauda equina signs → emergency) or with fever / after a fall or
                 accident (→ see a doctor soon). Finucane et al. (2020).
    boneStress — shin / foot pain that is there when walking, at rest or at night,
                 or starts earlier in each run: the warning signs of a bone stress
                 injury (Warden et al., 2014) → no running, physio within 48 h.
    bonePain   — pain ≥ 3/10 (≥ 2/10 for women) at a bone-typical site: return from bone stress is
                 guided by no pain at all (Warden 2014), unlike tendon pain
                 (Silbernagel 2007) → no running today, cross-training only.
    ill        — the runner reported being ill today / yesterday.
    illDays28  — days with an illness report in the last 28 days."""
    today = today_date()
    cut_screen = iso_date(today - timedelta(days=SCREEN_WINDOW_DAYS - 1))
    lo = iso_date(today - timedelta(days=27))
    data = D.of(db, rid)
    db = data
    bone_min = BONE_PAIN_MIN_SEX.get(getattr(data.runner, "sex", None) or "", BONE_PAIN_MIN)
    rows = D.stable_desc((c for c in data.checkins if c.submitted_at >= lo), lambda c: c.submitted_at)
    out = {"redFlag": None, "boneStress": None, "bonePain": None, "ill": None, "illDays28": 0}
    ill_days = set()
    for c in rows:
        f = _flags(c)
        if f.get("ill"):
            ill_days.add(c.submitted_at[:10])
        if c.submitted_at[:10] < cut_screen:
            continue
        sites = _sites(c.pain_points, c.pain_site)
        if out["ill"] is None and f.get("ill"):
            out["ill"] = {"at": c.submitted_at[:10]}
        if out["redFlag"] is None and (f.get("red_cauda") or f.get("red_systemic")):
            back = [x for x in sites if back_site(x)]
            out["redFlag"] = {"at": c.submitted_at[:10], "kind": "cauda" if f.get("red_cauda") else "systemic",
                              "site": ", ".join(back) or "záda"}
        if out["boneStress"] is None and any(f.get(k) for k in ("bone_walk", "bone_rest", "bone_earlier")):
            bone = [x for x in sites if bone_site(x)]
            what = [lbl for k, lbl in (("bone_walk", "bolí i při chůzi"), ("bone_rest", "bolí v klidu nebo v noci"),
                                        ("bone_earlier", "ozývá se při běhu čím dál dřív")) if f.get(k)]
            out["boneStress"] = {"at": c.submitted_at[:10], "site": ", ".join(bone) or "holeň / chodidlo", "what": what}
    out["illDays28"] = len(ill_days)
    # bone-typical pain (check-ins and run ratings) in the last 14 days
    reps = _pain_reports(db, rid, iso_date(today - timedelta(days=13)))
    hits = [(r["day"], r["pain"], [x for x in r["sites"] if bone_site(x)]) for r in reps]
    hits = [h for h in hits if h[2] and h[1] >= bone_min]
    if hits:
        last = max(hits, key=lambda h: (h[0], h[1]))
        days = sorted({h[0] for h in hits})
        if (today - date.fromisoformat(last[0])).days <= SCREEN_WINDOW_DAYS - 1:
            out["bonePain"] = {"at": last[0], "pain": last[1], "site": ", ".join(dict.fromkeys(last[2])),
                               "days14": len(days), "repeated": len(days) >= 2}
    return out


def hr_pace_deltas(rel_effort: dict | None, n: int = 4) -> list:
    """Heart rate above / below the runner's usual for the pace (grade-adjusted) on
    the latest runs, leaving out hot and very hilly runs (heat strain / terrain
    rather than fatigue). Newest first."""
    rows = (rel_effort or {}).get("runs") or []
    return [x["hrDelta"] for x in rows if x.get("hrDelta") is not None and not x.get("hot") and not x.get("hilly")][:n]


def overload_cluster(db: DBSession, rid: str, ill_days28: int, rel_effort: dict | None) -> dict | None:
    """v0.8.4 — persistent fatigue, repeated illness and falling performance
    together (Jeukendrup et al., 2024): many possible causes, so the app names no
    condition and only suggests having it looked at. Needs ≥ 2 of the 3.
    Thresholds are working assumptions (4 days of fatigue ≥ 6 in 14, ≥ 2 illness
    days in 28, heart rate at the usual pace ≥ 5 bpm higher over ≥ 3 runs)."""
    cut = day_ago(13)
    cks = [c for c in D.of(db, rid).checkins if c.submitted_at >= cut]
    tired = len({c.submitted_at[:10] for c in cks if (c.stress or 0) >= 6})
    deltas = hr_pace_deltas(rel_effort)
    hr_up = len(deltas) >= 3 and mean(deltas) >= 5
    parts = [("fatigue", tired >= 4), ("illness", ill_days28 >= 2), ("performance", hr_up)]
    got = [k for k, ok in parts if ok]
    if len(got) < 2:
        return None
    return {"parts": got, "fatigueDays": tired, "illDays": ill_days28, "hrDelta": r1(mean(deltas)) if deltas else None}


def max_efforts(db: DBSession, rid: str, hrmax: float | None, window: int = MAX_EFFORT_WINDOW) -> list[dict]:
    """Plan A3 — races and maximal efforts in the last `window` days: ≥ 10 km (≥ 5
    km when the title says it's a race) with RPE ≥ 9, or average HR ≥ 92 % of HR
    max, or a pace ≥ 12 % faster than the runner's usual long runs, or a race
    title. Each gets a recovery block of ~1 day per 3 km (2–14 days), the first
    third of it rest."""
    runs = acts(db, rid)
    fb = {f.activity_id: f for f in D.of(db, rid).feedback}
    since, today = day_ago(window), today_date()
    out = []
    for a in runs:
        if not a.started_at or a.started_at[:10] < since:
            continue
        km = a.distance_km or 0
        titled = any(w in (a.title or "").lower() for w in _RACE_WORDS)
        if km < (5 if titled else 10):
            continue
        d0 = a.started_at[:10]
        lo = iso_date(date.fromisoformat(d0) - timedelta(days=90))
        prior = [x for x in runs if x.id != a.id and x.pace_s_km and lo <= x.started_at[:10] < d0]
        long_ = [x.pace_s_km for x in prior if (x.distance_km or 0) >= 12]
        usual = median(long_) if len(long_) >= 3 else (median([x.pace_s_km for x in prior]) if len(prior) >= 5 else None)
        why = []
        f = fb.get(a.id)
        if f and (f.rpe or 0) >= 9:
            why.append(f"námaha {f.rpe}/10")
        if a.avg_hr and hrmax and a.avg_hr >= 0.92 * hrmax:
            why.append(f"průměrný tep {round(a.avg_hr)} ({round(100 * a.avg_hr / hrmax)} % maxima)")
        if usual and a.pace_s_km and a.pace_s_km <= 0.88 * usual:
            why.append(f"tempo o {round(100 * (1 - a.pace_s_km / usual))} % rychlejší než vaše obvyklé dlouhé běhy")
        if titled:
            why.append("závod")
        if not why:
            continue
        days = int(clamp(round(km / 3), 2, 14))
        since_days = (today - date.fromisoformat(d0)).days
        out.append({"date": d0, "km": r1(km), "title": a.title, "why": why, "days": days,
                    "restDays": max(2, math.ceil(days / 3)), "daysSince": since_days})
    return out


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
    device_log = list(D.of(db, rid).devices)
    device_changed = len(device_log) >= 2 and device_log[-1].recorded_at > day_ago(BASE_FROM)
    if device_changed:
        v = min(v, 0.4)
    step = getattr(_engine_ctx, "mech_step", None)

    if device_changed:
        note = "Během baseline okna došlo ke změně hodinek — mechanické signály jsou umlčené, dokud se baseline nepostaví znovu na novém zařízení."
    elif step:
        note = (f"Mechanika se {step['date'][8:10].lstrip('0')}. {step['date'][5:7].lstrip('0')}. skokově změnila "
                f"v {len(step['metrics'])} metrikách najednou ({', '.join(step['labels'])}) a bez hlášených obtíží — "
                "spíš nové boty, jiný snímač nebo aktualizace hodinek než změna běhu. Baseline se staví znovu od toho dne"
                + (", do té doby se mechanika nehodnotí." if v < 0.6 else "."))
    elif v < 0.6:
        note = "Baseline se zatím buduje — mechanické signály se nezobrazují."
    else:
        note = "Baseline je dostatečný."
    return {
        "value": v, "sessions": matched, "days": days, "baseSessions": len(base),
        "note": note, "deviceChanged": device_changed, "equipmentStep": step,
        # v0.9.0 — the pace classes of the terrain buckets (s/km), the runner's own when "relative"
        "paceCuts": [round(c) for c in (getattr(_engine_ctx, "pace_cuts", None) or PACE_CUTS_FIXED)],
        "paceRelative": getattr(_engine_ctx, "pace_cuts", None) is not None,
    }


# v0.9.0 — a step in several running-dynamics metrics on the same day, without any
# reported pain around it and at an unchanged pace, is far more likely new shoes, a
# different sensor (chest strap / pod / wrist) or a firmware update than a change in
# the runner (Willy, 2018: manufacturers change the algorithms remotely). The baseline
# then restarts from that day instead of reading the step as drift. With pain around
# it the step stays visible: a sudden compensation is exactly what should show.
STEP_FIELDS = (("vert_osc_cm", "vertikální oscilace"), ("vert_ratio_pct", "vertikální poměr"),
               ("gct_ms", "kontakt se zemí"), ("stride_len_m", "délka kroku"), ("cadence_spm", "kadence"))
STEP_MIN_METRICS, STEP_Z, STEP_AGREE, STEP_SPEED = 3, 2.0, 0.8, 0.04
STEP_BEFORE, STEP_AFTER, STEP_PAIN_DAYS = 8, 4, 7


def mech_step_change(db, rid: str):
    """{date, metrics, labels, shifts} of the latest such step within the last
    BASE_FROM days, else None (see STEP_* for the rule)."""
    data = D.of(db, rid)
    runs = [a for a in all_acts(data, rid, "mech") if is_run(a) and _speed_ms(a)]
    if len(runs) < STEP_BEFORE + STEP_AFTER:
        return None
    lo = day_ago(BASE_FROM)
    days = sorted({a.started_at[:10] for a in runs if a.started_at[:10] > lo})
    pain_days = sorted({p["day"] for p in _pain_reports(data, rid, day_ago(BASE_FROM + STEP_PAIN_DAYS)) if p["pain"] >= 1})
    best = None
    for d in days:
        before = [a for a in runs if a.started_at[:10] < d][-STEP_BEFORE:]
        after = [a for a in runs if a.started_at[:10] >= d][:STEP_BEFORE]
        if len(before) < 6 or len(after) < STEP_AFTER:
            continue
        sb, sa = median([_speed_ms(a) for a in before]), median([_speed_ms(a) for a in after])
        if abs(sa - sb) / sb > STEP_SPEED:
            continue                                   # the pace changed too: not a pure equipment step
        hit, shifts = [], {}
        for f, lbl in STEP_FIELDS:
            b = [getattr(a, f) for a in before if getattr(a, f) is not None]
            x = [getattr(a, f) for a in after if getattr(a, f) is not None]
            if len(b) < 6 or len(x) < STEP_AFTER:
                continue
            mb, s = median(b), max(mad_sd(b), sd(b) * 0.5, abs(median(b)) * 0.005)
            z = (median(x) - mb) / s if s else 0.0
            side = sum(1 for v in x if (v - mb) * z > 0) / len(x)
            if abs(z) >= STEP_Z and side >= STEP_AGREE:
                hit.append((f, lbl))
                shifts[f] = r2(z)
        if len(hit) < STEP_MIN_METRICS:
            continue
        d0 = date.fromisoformat(d)
        if any(abs((date.fromisoformat(p) - d0).days) <= STEP_PAIN_DAYS for p in pain_days):
            continue
        cand = {"date": d, "metrics": [f for f, _ in hit], "labels": [lbl for _, lbl in hit], "shifts": shifts,
                "_score": (len(hit), sum(abs(z) for z in shifts.values()))}
        if best is None or cand["_score"] > best["_score"]:    # the day that separates best is the step
            best = cand
    if best:
        best.pop("_score")
    return best


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

    data = D.of(db, rid)
    for c in data.checkins:
        if (c.pain_score or 0) >= thr:
            add(c.submitted_at)
    for f in data.feedback:
        if (f.pain_during or 0) >= thr:
            add(f.submitted_at)
    return frozenset(out)


_SEG_FIELD2KEY = {"vratio_pct": "tavr", "gct_ms": "gct", "cadence_spm": "cadence",
                  "step_len_m": "stride", "vo_cm": "vosc"}


def _stream_rows(db: DBSession, rid: str, newest_first: bool = False) -> list[dict]:
    """The runner's stored segment streams joined to their activity, one dict per
    run: {aid, created, started, title, distanceKm, surface, segs}. Each segment
    takes the activity's CURRENT surface — segments are cut at fetch time, and a
    later surface refinement (terrain sampling, a manual fix) must reach the
    segment baselines and the regression's surface terms too."""
    data = D.of(db, rid)
    since = getattr(_engine_ctx, "mech_since", None)      # equipment step: the baseline restarts there
    joined = []
    for st in data.streams:
        a = data.act_by_id.get(st.activity_id)
        if a is None or st.segments_json is None or not (a.excluded is not True or a.excluded_scope == "load"):
            continue
        if since is not None and a.started_at < since:
            continue
        joined.append((st.segments_json, st.created_at, a.id, a.started_at, a.title, a.distance_km, a.surface,
                       run_temp(a), winter_run(a)))
    joined.sort(key=lambda t: t[2])                       # Activity.id asc (secondary key)
    joined.sort(key=lambda t: t[3] or "", reverse=newest_first)
    out = []
    for segs, created, aid, started, title, dist, surface, temp, winter in joined:
        if not segs:
            continue
        if surface:
            segs = [s if s.get("surface") == surface else {**s, "surface": surface} for s in segs]
        if temp is not None:                  # v0.9.0: the run's air temperature, a regression covariate
            segs = [{**s, "tempC": temp} for s in segs]
        out.append({"aid": aid, "created": created or "", "started": started or "", "title": title,
                    "distanceKm": dist, "surface": surface, "segs": segs, "temp": temp, "winter": winter})
    return out


def _baseline_rows(rows: list[dict], excl) -> list[dict]:
    """Rows in the 84→29-day baseline window, minus pain-period dates."""
    lo, hi = day_ago(BASE_FROM), day_ago(BASE_TO)
    return [r for r in rows if hi >= r["started"] > lo and r["started"][:10] not in excl]


# Regression fits over the baseline segments are the expensive part of segment
# scoring (pure-Python ridge over hundreds of segments) and the baseline only
# changes when a run enters/leaves the window — so memoise per exact baseline.
# The key is the identity of every baseline stream (activity, fetch time, surface,
# segment count), so a re-fetched stream or a changed surface refits.
_SEG_FIT_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_SEG_FIT_LOCK = threading.Lock()
_SEG_FIT_MAX = 512


def _seg_cached(kind: str, base_rows: list[dict], field: str, build):
    key = (kind, field, tuple((r["aid"], r["created"], r["surface"], r.get("temp"), len(r["segs"])) for r in base_rows))
    with _SEG_FIT_LOCK:
        if key in _SEG_FIT_CACHE:
            _SEG_FIT_CACHE.move_to_end(key)
            return _SEG_FIT_CACHE[key]
    val = build()
    with _SEG_FIT_LOCK:
        _SEG_FIT_CACHE[key] = val
        while len(_SEG_FIT_CACHE) > _SEG_FIT_MAX:
            _SEG_FIT_CACHE.popitem(last=False)
    return val


def _seg_fit(base_rows: list[dict], field: str):
    from . import regression as reg
    return _seg_cached("fit", base_rows, field,
                       lambda: reg.fit_metric([s for r in base_rows for s in r["segs"]], field))


_SEG_MIN_BASE_SESS = 5   # baseline sessions needed to know the runner's session-level noise
_NOTABLE_DI, _NOTABLE_BAND = 2.5, 3.0   # "notable run" bars, session typical-error units
_SEG_SESS_FLOOR = 0.25   # floor on that noise (in segment-z units) — in-sample spreads can be tiny [Calibrate]


def _rms_scale(xs):
    """Session-level typical error from baseline-session drift indices (which
    centre on 0 by construction): RMS with an n−1 denominator and the √(1 + 1/n)
    prediction factor (a NEW session also carries the baseline's own estimation
    error), floored."""
    n = len(xs)
    if n < _SEG_MIN_BASE_SESS:
        return None
    return max(math.sqrt(sum(x * x for x in xs) / (n - 1) * (1 + 1 / n)), _SEG_SESS_FLOOR)


def _seg_scale(base_rows, stats, field, method):
    """How much the runner's own BASELINE sessions scatter on this metric, per
    session and per gradient group, in the scorer's units. A session's drift
    index is an average of many segment z-scores, so its natural spread depends
    on how the runner's noise splits between days and within a run — dividing by
    this empirical spread puts every session DI in session typical-error units
    (the same units the per-run path and the EWMA thresholds assume)."""
    from . import regression as reg
    from . import segmentation as seg
    model = _seg_fit(base_rows, field) if method == "regression" else None

    def build():
        dis, bands = [], {"down": [], "level": [], "up": []}
        for r in base_rows:
            d = reg.session_residual_drift(r["segs"], model) if model else seg.session_drift(r["segs"], stats, field)
            if d:
                dis.append(d["di"])
                for k, v in d["byBand"].items():
                    bands[k].append(v)
        return {"sess": _rms_scale(dis), "band": {k: _rms_scale(v) for k, v in bands.items()}, "n": len(dis)}
    return _seg_cached("scale-" + method, base_rows, field, build)


def _seg_session(segs, base_rows, stats, field, method):
    """One session's standardised segment drift for `field`, or None (not
    scorable / baseline too thin to know the session-level noise)."""
    from . import regression as reg
    from . import segmentation as seg
    sc = _seg_scale(base_rows, stats, field, method)
    if sc["sess"] is None:
        return None
    model = _seg_fit(base_rows, field) if method == "regression" else None
    d = reg.session_residual_drift(segs, model) if model else seg.session_drift(segs, stats, field)
    if not d:
        return None
    return {
        "di": clamp(d["di"] / sc["sess"], -4.0, 4.0), "rawDi": d["di"], "sessSd": r2(sc["sess"]),
        "nSeg": d["nSeg"],
        # a band without ≥5 baseline sessions keeps raw segment-z units (conservative)
        "byBand": {k: r2(v / (sc["band"].get(k) or 1.0)) for k, v in d["byBand"].items()},
    }


def _seg_method(base_rows, field):
    return "regression" if _seg_fit(base_rows, field) else "bucket"


def segment_mechanics(db: DBSession, rid: str):
    """Phase 5 — within-run mechanics drift from stored S3 segments. Each segment
    is scored against the runner's own baseline — the S4 context regression
    (speed, gradient, time-in-run, surface) when there are enough baseline
    segments, else the per-(surface, band) median/MAD — and the duration-weighted
    session drift index is standardised by the runner's own baseline-session
    scatter (_seg_scale). That surfaces changes a per-run average would hide
    (e.g. a downhill-only drift). The series is smoothed by the shared EWMA.
    Returns per-metric results keyed by engine metric name, or None when there
    aren't enough segmented sessions yet."""
    from . import segmentation as seg
    rows = _stream_rows(db, rid)
    if not rows:
        return None
    base_rows = _baseline_rows(rows, _eexcl())
    base_segs = [s for r in base_rows for s in r["segs"]]
    winter_ok = sum(1 for r in base_rows if r.get("winter")) >= _WINTER_MIN_BASE
    recent = [r["segs"] for r in rows if r["started"] > day_ago(RECENT) and (winter_ok or not r.get("winter"))]
    if len(base_segs) < 15 or len(base_rows) < _SEG_MIN_BASE_SESS or not recent:
        return None
    stats = seg.baseline_stats(base_segs)
    if not stats:
        return None
    out = {}
    for field, key in _SEG_FIELD2KEY.items():
        method = _seg_method(base_rows, field)
        res = [x for x in (_seg_session(s, base_rows, stats, field, method) for s in recent) if x]
        if not res and method == "regression":  # nothing in the model's domain → bucket method
            method = "bucket"
            res = [x for x in (_seg_session(s, base_rows, stats, field, method) for s in recent) if x]
        if not res:
            continue
        flag = _ewma_flag([x["di"] for x in res], _BAD_SIGN.get(field, 1))
        out[key] = {**flag, "byBand": res[-1]["byBand"], "segment": True, "method": method,
                    "sessSd": res[-1]["sessSd"]}
    return out or None


_SEG_METRIC_LABELS = {
    "gct_ms": "Kontakt se zemí", "vratio_pct": "Vertikální poměr", "cadence_spm": "Kadence",
    "step_len_m": "Délka kroku", "vo_cm": "Vertikální oscilace", "gct_bal_pct": "Symetrie kontaktu",
}
_BAND_LABELS = {"B1": "prudký sjezd", "B2": "sjezd", "B3": "rovina", "B4": "výjezd", "B5": "prudký výjezd"}


def _seg_test_setup(db: DBSession, rid: str, rows: list[dict], min_base: int = 5):
    """What each segment is tested against: the S4 context model per metric (when
    the baseline has enough segments) and the per-(metric, surface, band) bucket
    stats as fallback — both built from the 84→29-day baseline window relative to
    the pinned "today" (wrap in today_pinned to test a historic run)."""
    from . import segmentation as seg
    base_rows = _baseline_rows(rows, _v2_baseline_exclusions(db, rid))
    models_by = {f: _seg_fit(base_rows, f) for f in seg.MECH_FIELDS}
    by = {}  # (field, surface, band) -> [values]
    for r in base_rows:
        for s in r["segs"]:
            for f in seg.MECH_FIELDS:
                if s.get(f) is not None:
                    by.setdefault((f, s.get("surface") or "unknown", s.get("band")), []).append(s[f])
    base = {}
    for k, v in by.items():
        if len(v) >= min_base:
            m_, s_, n_ = inlier_mean_sd(v)
            base[k] = (m_, max(s_, abs(m_) * 0.012, 1e-9), n_)
    return base_rows, models_by, base


def _seg_test_run(r: dict, models_by: dict, base: dict, all_findings: list) -> dict:
    """Every segment × metric of one run vs the baseline's expectation for that
    segment. Findings are appended to `all_findings` for the family-wide FDR."""
    from . import regression as reg
    from . import segmentation as seg
    seg_out = []
    for i, s in enumerate(r["segs"]):
        findings = []
        for f in seg.MECH_FIELDS:
            v = s.get(f)
            if v is None:
                continue
            model = models_by.get(f)
            if model is not None:
                if not reg.in_domain(model, s):
                    continue
                expected = reg.predict(model, s)
                sdev = model["sigma"] * math.sqrt(1 + model["k"] / model["n"])
                df, nb, method = model["n"] - model["k"], model["n"], "regression"
            else:
                st = base.get((f, s.get("surface") or "unknown", s.get("band")))
                if not st:
                    continue
                expected, sd0, nb = st
                sdev = sd0 * math.sqrt(1 + 1 / nb)
                df, method = nb - 1, "bucket"
            t = (v - expected) / sdev
            p = t_two_sided_p(t, df)
            fnd = {
                "metric": f, "label": _SEG_METRIC_LABELS.get(f, f),
                "value": r2(v), "base": r2(expected), "sd": r2(sdev), "baseN": nb, "method": method,
                "z": r2(t), "_p": p, "p": round(p, 4), "sigRaw": p < 0.05,
                "sig": False, "dir": "up" if t > 0 else "down",
            }
            findings.append(fnd)
            all_findings.append(fnd)
        spd = s.get("meanSpeed")
        seg_out.append({
            "idx": i, "band": s.get("band"), "bandLabel": _BAND_LABELS.get(s.get("band"), s.get("band")),
            "surface": s.get("surface"), "elapsedMin": r1((s.get("elapsedS") or 0) / 60),
            "startS": round(s.get("elapsedS") or 0), "durationS": s.get("durationS"),
            "paceSKm": round(1000 / spd) if spd and spd > 0.5 else None,
            "gradePct": r1((s.get("meanGradient") or 0) * 100),
            "findings": findings, "sig": False,
        })
    return {
        "aid": r["aid"], "date": r["started"], "title": r["title"], "distanceKm": r["distanceKm"],
        "nSeg": len(r["segs"]), "sigCount": 0, "segments": seg_out,
    }


def _seg_fdr(all_findings: list, runs_out: list):
    """Benjamini–Hochberg FDR at 5 % across ALL segment × metric tests, so
    "significant" accounts for how many comparisons were run."""
    ps = sorted(f["_p"] for f in all_findings)
    thr = -1.0
    for rank, pv in enumerate(ps, 1):
        if pv <= (rank / len(ps)) * 0.05:
            thr = pv
    for f in all_findings:
        f["sig"] = f.pop("_p") <= thr
    for run in runs_out:
        for sgm in run["segments"]:
            sgm["sig"] = any(f["sig"] for f in sgm["findings"])
        run["sigCount"] = sum(1 for sgm in run["segments"] for f in sgm["findings"] if f["sig"])
        run["nTested"] = sum(len(sgm["findings"]) for sgm in run["segments"])


def segment_significance(db: DBSession, rid: str, n_runs: int = 3, min_base: int = 5) -> dict:
    """Per-segment statistical test of the last `n_runs` runs against the runner's
    own baseline. Each segment × metric is compared with what the runner's
    baseline predicts for THAT segment:

    • regression (enough baseline segments): the S4 context model's expected value
      at the segment's speed, gradient, time-in-run and surface; the test statistic
      is the residual over the model's residual SD (inflated for estimation). Out-
      of-domain segments (unfamiliar speed/gradient/surface) are not tested. This
      removes the pace confound — a faster run no longer lights up GCT/cadence/
      step length everywhere just for being faster.
    • bucket fallback: the baseline segments in the same surface × gradient band,
      as a prediction interval t = (value − mean) / (SD·√(1 + 1/n)).

    p-values come from Student's t (df from the baseline size), so a small baseline
    bucket is not over-trusted. "Significant" = Benjamini–Hochberg FDR 5 % across
    every segment × metric test shown. Uses stored segments (fetch Detailní data)."""
    db = D.of(db, rid)
    rows = _stream_rows(db, rid, newest_first=True)
    if not rows:
        return {"runs": [], "note": "no_streams"}
    _base_rows, models_by, base = _seg_test_setup(db, rid, rows, min_base)
    all_findings: list = []
    runs_out = [_seg_test_run(r, models_by, base, all_findings) for r in rows[:n_runs]]
    _seg_fdr(all_findings, runs_out)
    return {"runs": runs_out, "baselineBuckets": len(base), "fdr": 0.05,
            "method": "regression" if any(models_by.values()) else "bucket"}


def run_segment_test(db: DBSession, rid: str, aid: int, min_base: int = 5) -> dict:
    """The per-segment test for ONE run (Pohyb → Historie běhů), against the
    baseline as it stood on that run's day — the 84→29-day window before the run,
    so an older run is never judged by a norm that contains itself or later runs.
    FDR is controlled within the run."""
    db = D.of(db, rid)
    rows = _stream_rows(db, rid)
    r = next((x for x in rows if x["aid"] == aid), None)
    if r is None:
        return {"available": False, "reason": "no_stream"}
    rd = date.fromisoformat(r["started"][:10])
    with today_pinned(rd):
        base_rows, models_by, base = _seg_test_setup(db, rid, rows, min_base)
        win = {"from": day_ago(BASE_FROM - 1), "to": day_ago(BASE_TO)}
    all_findings: list = []
    run = _seg_test_run(r, models_by, base, all_findings)
    _seg_fdr(all_findings, [run])
    return {
        "available": True, "run": run, "fdr": 0.05,
        "method": "regression" if any(models_by.values()) else "bucket",
        "baseline": {"runs": len(base_rows), **win},
        "reason": None if run["nTested"] else ("no_baseline" if len(base_rows) < _SEG_MIN_BASE_SESS else "out_of_domain"),
    }


def run_segment_breakdown(db: DBSession, rid: str, days: int = 60, limit: int = 12) -> list:
    """Per-RUN within-run drift for the Pohyb tab: for each recent run that has a
    stored stream, how each metric deviated from the runner's own baseline, split
    by gradient (sjezd / rovina / výjezd), in session typical-error units (see
    _seg_scale). Surfaces the notable single-band changes the whole-session score
    averages out. Empty until streams are fetched."""
    db = D.of(db, rid)
    from . import segmentation as seg
    rows = _stream_rows(db, rid, newest_first=True)
    if not rows:
        return []
    base_rows = _baseline_rows(rows, _v2_baseline_exclusions(db, rid))
    base_segs = [s for r in base_rows for s in r["segs"]]
    if len(base_segs) < 15 or len(base_rows) < _SEG_MIN_BASE_SESS:
        return []
    stats = seg.baseline_stats(base_segs)
    methods = {f: _seg_method(base_rows, f) for f in _SEG_METRIC_LABELS}
    cut = day_ago(days)
    out = []
    for r in rows:
        if r["started"] <= cut:
            continue
        metrics = {}
        for f, label in _SEG_METRIC_LABELS.items():
            d = _seg_session(r["segs"], base_rows, stats, f, methods[f])
            if d and d.get("byBand"):
                metrics[f] = {"di": r2(d["di"]), "byBand": d["byBand"], "label": label, "method": methods[f]}
        if not metrics:
            continue
        # Up to 6 metrics × 3 gradient groups are looked at per run, so the bar
        # is set for that many looks: |session drift| ≥ 2.5 or a band ≥ 3.0 in the
        # runner's own session typical-error units (~1 % / ~0.3 % per look with no
        # real change). The old |di| ≥ 0.8 / band ≥ 1.5 in raw segment units
        # marked most ordinary runs "notable".
        notable = any(abs(v["di"]) >= _NOTABLE_DI or any(abs(z) >= _NOTABLE_BAND for z in v["byBand"].values())
                      for v in metrics.values())
        out.append({"date": r["started"], "title": r["title"], "distanceKm": r["distanceKm"],
                    "metrics": metrics, "notable": notable})
        if len(out) >= limit:
            break
    return out


def _mech_flags(tv, gc, cad, strd, vosc) -> tuple[bool, bool]:
    """v2 evidence labels over the per-metric drift results → (flag, watch).
    Rule A (persistence): some metric is past its EWMA control limit, most recent
    sessions agree, and the drift is at least "possible" in size. Rule B
    (convergence): ≥ 2 independent metric GROUPS show a clear drift. Watch: one
    clear group, or a metric past its control limit. One-sided throughout."""
    groups = {"vertical": (tv, vosc), "cadence": (cad, strd), "contact": (gc,)}

    def ok(m):
        return isinstance(m, dict) and "state" in m

    def grp(pred):
        return [g for g, ms in groups.items() if any(ok(m) and pred(m) for m in ms)]
    rule_a = bool(grp(lambda m: m.get("beyond") and m.get("persist") and m.get("state") != "usual"))
    clear_groups = grp(lambda m: m.get("state") == "clear")
    flag = rule_a or len(clear_groups) >= 2
    watch = (not flag) and (len(clear_groups) >= 1 or bool(grp(lambda m: m.get("beyond"))))
    return flag, watch


def assess(db, rid: str) -> dict:
    """The engine: a pure function of the runner's RunnerData snapshot (data.py), the
    engine day (today_pinned) and the engine mode (engine_pinned). Pass a snapshot, or
    a database session to have one loaded. Nothing is written and, given the snapshot,
    nothing is read from the database."""
    data = D.of(db, rid)
    with mech_scope(data, rid):
        return _assess(data, rid)


def assess_data(data, day=None, mode: str | None = None) -> dict:
    """assess() with the day and the engine mode passed explicitly."""
    from contextlib import nullcontext
    with (today_pinned(day) if day is not None else nullcontext()), \
            (engine_pinned(mode) if mode is not None else nullcontext()):
        return assess(data, data.rid)


def _assess(db, rid: str) -> dict:
    data = db
    r = data.runner
    if _sensitive():
        # Feed pain-period exclusions to the mechanics drift core for this scope.
        _engine_ctx.excl = _v2_baseline_exclusions(db, rid)
        _engine_ctx.damp = post_strength_dates(db, rid)
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
    if gated and _sensitive():
        sm = segment_mechanics(db, rid)
        if sm:
            for key, var in (("tavr", tv), ("gct", gc), ("cadence", cad), ("stride", strd), ("vosc", vosc)):
                res = sm.get(key)
                if res and isinstance(var, dict):
                    # The segment override replaces `z` (drives the score) with the
                    # finer within-run segment z, but leaves baseMean/recMean/series
                    # per-run. Preserve the per-run drift z as `perRunZ` so anything
                    # that narrates "baseMean → recMean · odchylka z" pairs the per-run
                    # means with a matching per-run z, not the segment one.
                    var["perRunZ"] = var.get("z")
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
    gasc = ascent_by_gradient(db, rid)
    inj = injury(db, rid)

    # Daily check-in is a *today* signal — only the last few days count, so a
    # stale pain report from weeks ago doesn't keep inflating the score forever.
    # Persistent problems live on the weekly OSTRC / injury path (28-day window).
    ci = next(iter(D.stable_desc((c for c in data.checkins if c.submitted_at > day_ago(4)), lambda c: c.submitted_at)), None)

    sig = []
    pstate = pain_state(db, rid)                  # v0.8.5: pain-free check-ins end an episode

    def age_of(iso):
        try:
            return (today_date() - date.fromisoformat(str(iso)[:10])).days
        except (TypeError, ValueError):
            return 0

    def faded(txt, f):
        return txt + (f" Slábne: poslední hlášení je starší a od té doby "
                      f"{'jste hlásili dny bez bolesti' if pstate['cleared'] else 'uběhlo pár dní'} (×{r2(f)})." if f < 0.99 else "")

    def push(sid, name, grade, pts, val, detail, rule=None):
        sig.append({"id": sid, "name": cz_text(name), "grade": grade, "pts": pts, "val": cz_text(val), "detail": cz_text(detail),
                    **({"rule": rule} if rule else {})})

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
    for rep in (x for x in data.injuries if x.submitted_at > day_ago(365)):
        if rep.body_region:
            prior_regions.add(rep.body_region)
        for pp in (rep.pain_points or []):
            if pp.get("region"):
                prior_regions.add(pp["region"])
    prior_months = injury_months(r)
    prior_unknown = bool(r and r.prior_injury and not getattr(r, "prior_injury_date", None)
                         and r.prior_injury_months_ago is None)
    frailty = frailty_of(prior_months) if (r and r.prior_injury) else 1.0

    # --- Mechanical drift: scored *continuously* rather than only above a hard
    # z ≥ 1 threshold, so subtle terrain-cleaned changes nudge the drift score up
    # instead of leaving it stuck at zero. Each metric adds points proportional
    # to how far it drifted past a small per-metric noise deadzone, in its "bad"
    # direction. A signal is listed only once the drift is genuinely notable
    # (`show`), so tiny drift still feeds the score without cluttering the list.
    #                (id,     name,                            grade, mag,               dead, weight, cap, show,  val,                     detail)
    # When v2 segment scoring overrode a metric, the per-run baseMean→recMean no
    # longer matches the (segment EWMA) z we show — so describe it by gradient
    # band instead, keeping `val` (z) and `detail` consistent.
    def _seg_detail(m):
        bb = (m or {}).get("byBand") or {}
        parts = [f"{lbl} {sgn(bb[k])}" for k, lbl in (("down", "sjezd"), ("level", "rovina"), ("up", "výjezd")) if k in bb]
        return ("úseky (odchylka v SD): " + " · ".join(parts)) if parts else "měřeno po úsecích běhu"

    def _pace_note(m):
        m = m or {}
        return ((" · přepočteno na vaše obvyklé tempo" if m.get("paceAdjusted") else "")
                + (" a teplotu" if m.get("paceAdjusted") and m.get("tempAdjusted") else
                   " · přepočteno na obvyklou teplotu" if m.get("tempAdjusted") else "")
                + (f" · {m['winterSkipped']}× běh na sněhu či ledu nehodnocen" if m.get("winterSkipped") else ""))

    # feedback railway#50 — show the change as a percentage of the runner's own
    # baseline (baseMean → recMean), not a z-score; the z still drives the points.
    def _pct(m):
        b, r = (m or {}).get("baseMean"), (m or {}).get("recMean")
        if b in (None, 0) or r is None:
            return f"{sgn(m['z'])} σ" if m and m.get("z") is not None else "—"
        v = round((r - b) / abs(b) * 100, 1)
        return f"{'+' if v > 0 else '−' if v < 0 else '±'}{str(abs(v)).replace('.', ',')} %"

    mech_terms = []
    if tv:
        d = _seg_detail(tv) if tv.get("segment") else f"{tv['baseMean']} % → {tv['recMean']} % · {tv['buckets']} shodných profilů terénu{_pace_note(tv)}"
        mech_terms.append(("tavr", "Vertikální poměr roste", "B", tv["z"], 0.2, 17, 4.0, 0.6, _pct(tv), d))
    if gc:
        d = _seg_detail(gc) if gc.get("segment") else f"{gc['baseMean']} ms → {gc['recMean']} ms po normalizaci na kadenci{_pace_note(gc)}"
        mech_terms.append(("gct", "Prodloužený kontakt se zemí", "B", gc["z"], 0.2, 13, 4.0, 0.6, _pct(gc), d))
    if cad:
        d = _seg_detail(cad) if cad.get("segment") else f"{cad['baseMean']} → {cad['recMean']} spm · {cad['buckets']} shodných profilů terénu{_pace_note(cad)}"
        mech_terms.append(("cad", "Klesající kadence", "C", -cad["z"], 0.2, 10, 4.0, 0.6, _pct(cad), d))
    if vosc:
        d = _seg_detail(vosc) if vosc.get("segment") else f"{vosc['baseMean']} → {vosc['recMean']} cm · {vosc['buckets']} shodných profilů terénu{_pace_note(vosc)}"
        mech_terms.append(("vosc", "Vyšší vertikální oscilace", "C", vosc["z"], 0.2, 10, 4.0, 0.6, _pct(vosc), d))
    if bal:
        mech_terms.append(("bal", "Posun v symetrii kontaktu", "B", bal["excursion"], 0.4, 22, 3.0, 0.8, f"{sgn(bal['excursion'])} p.b.",
                           f"{bal['baseline']} % → {bal['now']} % vlevo · {bal['direction']}"))
    # Plan phase 2A: the dead zone is the smallest worthwhile change in z units and a
    # metric too noisy to resolve it (typical error >= SWC) counts at half weight.
    # Both come from the pooled data and are neutral (0.2 SD, weight 1) until then.
    from . import reference as REF
    _dev = r.device if r else None
    mech_res = {}
    for sid, fld in (("tavr", "vert_ratio_pct"), ("gct", "gct_ms"), ("cad", "cadence_spm"), ("vosc", "vert_osc_cm")):
        mp = (mech_priors(fld, _dev) if _dev else None) or mech_priors(fld)
        mech_res[sid] = {"dead": round(REF.dead_zone_z(fld, mp["s_rm"] if mp else None, mp), 3),
                         "wf": REF.metric_weight_factor(mp),
                         **({"te": round(mp["te"], 3) if mp.get("te") else None, "swc": round(mp["swc"], 3) if mp.get("swc") else None} if mp else {})}
    mech_terms = [(sid, name, grade, mag, mech_res[sid]["dead"] if sid in mech_res else dead,
                   weight * (mech_res[sid]["wf"] if sid in mech_res else 1.0), cap, show, val, detail)
                  for sid, name, grade, mag, dead, weight, cap, show, val, detail in mech_terms]
    for sid, name, grade, mag, dead, weight, cap, show, val, detail in mech_terms:
        p = rnd(clamp(mag - dead, 0, cap) * weight)
        if p:
            mech_score += p
            if mag >= show:
                push(sid, name, grade, p, val, detail)
    # Decoupling (fatigue resistance) is a %/run trend, scored on its own ramp.
    if dec and dec["trend"] > 0.1:   # the ramp starts at 0.1, so no 1.3-point jump (plan 2B)
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

    cap_parts = []
    if rcv and rcv["hrv"]["z"] is not None:
        cap_parts.append(clamp(-rcv["hrv"]["z"] / 2.0, 0, 1))            # suppressed HRV
    if rcv and rcv["rhr"]["z"] is not None:
        cap_parts.append(clamp(rcv["rhr"]["z"] / 2.0, 0, 1))            # elevated RHR
    if rcv and rcv["sleep"]["debt"] is not None:
        cap_parts.append(clamp(rcv["sleep"]["debt"] / 8.0, 0, 1))       # sleep debt
    capacity_deficit = r2(mean(cap_parts)) if cap_parts else None

    cap_v3 = None
    if _emode() == "v3":
        # v3 (Kapacitní): the load axis is exceedance over the runner's own
        # demonstrated capacity per channel (objem / intenzita / klesání / stoupání /
        # celková zátěž), with readiness (HRV, klidový tep, spánek, check-in) scaling
        # capacity instead of adding separate points. See metrics/capacity.py.
        from . import capacity as CAP
        cap_v3 = CAP.assess_capacity(db, rid, frailty=frailty, runner=r)
        for cs in cap_v3["signals"]:
            load_score += cs["pts"]
            push(cs["id"], cs["name"], cs["grade"], cs["pts"], cs["val"], cs["detail"])
        # Pace spike (Nielsen 2014: sudden pace → Achilles / plantar / tibia) and
        # monotony (Foster) describe load *structure* the channels don't.
        if L["valid"] and L["paceSpike"] is not None and L["paceSpike"] > 1.06:
            p = rnd(clamp((L["paceSpike"] - 1.06) * 40, 0, 10))
            if p:
                load_score += p
                push("pace_spike", "Skok v tempu", "C", p, f"×{L['paceSpike']}",
                     "Nedávný běh byl rychlejší než vaše obvykle nejrychlejší běhy posledních 2 měsíců (s přepočtem "
                     "na převýšení, bez závodů) — prudké zrychlení zatěžuje jinak než delší vzdálenost "
                     "(spíš Achillovka / planta / holeň).")
        # v0.9.0 — monotony (Foster 1998) is a very-low-evidence warning sign and punished
        # the lowest-risk pattern in the running cohorts: frequent, consistent running
        # (Abrahamson et al., 2025: 24.7 % injured at 7 runs a week vs 71.8 % at ≤ 1;
        # Malisoux et al., 2015). Grade C, and scored only when the week's all-sport load
        # is also above the runner's weekly capacity (strain above what they tolerate).
        sys_w = (((cap_v3.get("channels") or {}).get("systemic") or {}).get("exact") or {}).get("rw")
        m_w = (cap_v3.get("margins") or {}).get("week", 0.15)
        if L["monotony"] > MONO_THR and sys_w is not None and sys_w > 1 + m_w:
            p = rnd(clamp((L["monotony"] - MONO_THR) * 7, 0, 12))
            if p:
                load_score += p
                push("mono", "Monotónní trénink nad kapacitou", "C", p, f"{L['monotony']}",
                     f"Týden bez skutečně lehkých dnů a zároveň nad stropem vaší týdenní kapacity (×{r2(sys_w)}) · strain {L['strain']}. "
                     "Pravidelnost sama riziko nezvyšuje — časté běhání má v kohortách nejnižší podíl zranění.")
        # v0.8.4 — internal vs external load: heart rate at a familiar (grade-adjusted)
        # pace drifting up over several runs, hot and very hilly runs left out
        # (Bourdon et al., 2017; Halson, 2014a: single-day HR varies up to 6.5 %, so
        # ≥ 3 runs and ≥ 6 bpm on average — working assumption).
        hpd = hr_pace_deltas(cap_v3.get("relativeEffort"))
        if len(hpd) >= 3 and mean(hpd) >= HR_PACE_BPM:
            p = rnd(clamp(3 + (mean(hpd) - HR_PACE_BPM) * 1.5, 3, 10))
            load_score += p
            push("hr_pace", "Vyšší tep při obvyklém tempu", "C", p, f"+{_cz_num(mean(hpd))} tepu",
                 f"Posledních {len(hpd)} běhů (bez horkých a velmi kopcovitých) mělo tep v průměru o {_cz_num(mean(hpd))} "
                 "úderů vyšší, než u vás obvykle odpovídá danému tempu (s přepočtem na převýšení). Rozchod mezi vnitřní "
                 "a vnější zátěží bývá známkou únavy.")
        # v0.8.4 — a higher HRV isn't automatically good: it rose during functional
        # overreaching (Plews et al., 2014). Only together with fatigue or a heart rate
        # rising at the usual pace (working assumption: 7-night z ≥ 1.5).
        # v0.9.3 — watch data only: check-in fatigue is scored on Příznaky, not here as well
        if rcv and (rcv["hrv"]["z"] or 0) >= HRV_HIGH_Z:
            hr_up = len(hpd) >= 3 and mean(hpd) >= 5
            if hr_up:
                load_score += 6
                push("hrv_high", "Vysoká HRV spolu s vyšším tepem", "C", 6, f"{rcv['hrv']['now']} ms",
                     f"HRV za 7 dní nad vaší normou ({rcv['hrv']['base']} ms) a zároveň vyšší tep při obvyklém tempu. "
                     "Vyšší HRV není vždy dobrá zpráva, při funkčním přetížení může také stoupat (Plews et al., 2014).")
    else:
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
            p = rnd(pts_session_spike(s))     # continuous across the bands (plan 2B)
            band = "nad +100 %" if s > 2.0 else "+30–100 %" if s > 1.3 else "+10–30 %"
            if p:
                load_score += p
                _basis = L.get("sessionSpikeBasis") or "vzdálenost"
                _names = {"vzdálenost": "délce", "intenzita": "intenzitě", "terén": "náročnosti terénu"}
                _bl = " i ".join(_names.get(b, "délce") for b in _basis.split("+"))
                push("session_spike", "Skok v jednom běhu", "B", p, f"×{s}",
                     f"Nejnáročnější běh ({L['sessionSpikeKm']} km) je {band} proti nejnáročnějšímu běhu za předchozích 30 dní — "
                     f"skok v {_bl}. Skok v jednotlivém běhu je nejsilnější signál rizika (běžecká kohorta 5 205 běžců; "
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
                     "Nedávný běh byl rychlejší než vaše obvykle nejrychlejší běhy posledních 2 měsíců (s přepočtem "
                     "na převýšení, bez závodů) — prudké zrychlení zatěžuje jinak než delší vzdálenost "
                     "(spíš Achillovka / planta / holeň).")

        # v0.6 — ACWR DEMOTED to low-weight context (grade C). The team-sport
        # acute:chronic "sweet spot" does not transfer to distance running — the same
        # RUNSAFE cohort found ACWR *inversely* related to overuse injury and the
        # week-to-week ratio unrelated. Kept only as a mild descriptor / detraining flag.
        p = rnd(pts_acwr(L["ratio"])) if L["valid"] else 0
        if p and L["ratio"] > 1:
            load_score += p
            if p:   # every contributing point is listed, so the axis adds up (plan 2B)
                push("ewma", "Zvýšený poměr zátěže (7:28)", "C", p, f"×{L['ratio']}",
                     f"Akutní zátěž {L['acute']} proti chronické {L['chronic']} j.z./týden. Pozn.: v běžecké kohortě "
                     "sám poměr 7:28 riziko nepředpovídá — hlavní signál je skok v jednotlivém běhu výše.")
        elif p:
            load_score += p
            if p:
                push("ewma", "Náhlý pokles zátěže", "C", p, f"×{L['ratio']}",
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

        # v0.9.0 — monotony only with a rising load (7:28 above +15 %), grade C (see v3 above)
        if L["monotony"] > MONO_THR and L["valid"] and (L["ratio"] or 0) > MONO_V1_RATIO:
            p = rnd(clamp((L["monotony"] - MONO_THR) * 7, 0, 20))
            load_score += p
            push("mono", "Monotónní trénink při rostoucí zátěži", "C", p, f"{L['monotony']}",
                 f"Týden bez skutečně lehkých dnů a zároveň rostoucí zátěž (7:28 ×{L['ratio']}) · strain {L['strain']}")
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
        p = rnd(pts_hrv_low(rcv["hrv"]["z"])) if rcv and rcv["hrv"]["z"] is not None else 0
        load_score += p
        if p:
            push("hrv", "Potlačená HRV", "B", p, f"{rcv['hrv']['now']} ms",
                 f"Baseline {rcv['hrv']['base']} ms · {_pct({'baseMean': rcv['hrv']['base'], 'recMean': rcv['hrv']['now'], 'z': rcv['hrv']['z']})} za posledních 7 dní")
        p = rnd(pts_rhr_high(rcv["rhr"]["z"])) if rcv and rcv["rhr"]["z"] is not None else 0
        load_score += p
        if p:
            push("rhr", "Zvýšený klidový tep", "B", p, f"{rcv['rhr']['now']} tep/min",
                 f"Baseline {rcv['rhr']['base']} · {_pct({'baseMean': rcv['rhr']['base'], 'recMean': rcv['rhr']['now'], 'z': rcv['rhr']['z']})}")
        if hcv and hcv["ratio"] is not None and hcv["ratio"] >= 1.4:
            p = rnd(clamp((hcv["ratio"] - 1.4) * 14, 0, 10))
            load_score += p
            push("hrvcv", "Kolísavá HRV mezi dny", "C", p, f"CV ×{hcv['ratio']}",
                 f"Den-k-dni variabilita HRV {hcv['cvNow']} % proti obvyklým {hcv['cvBase']} %")
        # v0.9.0 — two-sided: heading into non-functional overreaching the day-to-day
        # variation FELL while the weekly mean declined (Plews et al., 2012), so an
        # unusually stable HRV together with a falling 7-night mean counts too.
        elif hcv and hcv["ratio"] is not None and hcv["ratio"] <= HRV_CV_LOW and rcv and (rcv["hrv"]["z"] or 0) <= -0.5:
            p = rnd(clamp((HRV_CV_LOW - hcv["ratio"]) * 25, 0, 10))
            if p:
                load_score += p
                push("hrvcv", "Neobvykle stálá HRV při jejím poklesu", "C", p, f"CV ×{hcv['ratio']}",
                     f"Den-k-dni variabilita HRV {hcv['cvNow']} % proti obvyklým {hcv['cvBase']} % a zároveň nižší "
                     "týdenní průměr — u přetížení se kolísání HRV spíš ztrácí (Plews et al., 2012).")
        # Fitness–fatigue gap, relative to chronic load so the threshold is unit-free
        # (acute/chronic are now training-load AU, not km).
        if L["valid"] and L["chronic"] and L["tsbBalance"] is not None:
            tsb_rel = L["tsbBalance"] / L["chronic"]
            p = rnd(clamp((-tsb_rel - 0.12) * 90, 0, 12)) if tsb_rel <= -0.12 else 0
            if p:                                    # no 0-point signal at the threshold (as hrvcv, the sandbox)
                load_score += p
                push("tsb", "Nepříznivá bilance zátěže", "C", p, f"{sgn(L['tsbBalance'])} j.z./týd",
                     f"Fitness (42denní průměr) {L['fitness42']} proti aktuální zátěži {L['acute']} j.z./týden — akutní zátěž předbíhá vybudovanou")

        # v0.6 — LOAD × CAPACITY interaction (Bertelsen 2017 framework: injury is
        # cumulative load exceeding *structure-specific capacity*, and capacity is
        # modulated by recovery). A spike on depleted recovery is far riskier than the
        # same spike when fresh — so score the interaction, not just the two alone.
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
    next_a = next((x for x in races_for(db, r) if x["priority"] == "A" and x["daysTo"] >= 0), None) if r else None
    if next_a:                                # plan B4: the calendar's next A race (or the profile's goal race)
        days_to_race = next_a["daysTo"]
        tw = taper_weight(load_score, L["ratio"])
        if days_to_race is not None and 0 <= days_to_race <= 21 and tw > 0:
            p = rnd(clamp((21 - days_to_race) / 21 * 14, 4, 14) * tw)   # fades in with the load (plan 2B)
            load_score += p
            if p:
                push("taper", "Blízký závod při zvýšené zátěži", "C", p, f"{days_to_race} dní do závodu",
                 f"{next_a['name'] or 'cílový závod'} za {days_to_race} dní při zvýšené aktuální zátěži — "
                 "riziko přetížení těsně před závodem stoupá, zvažte odlehčení místo dalšího navyšování")

    # v0.9.3 — the repeated sore spot follows its pain episode (graduated re-marks, clean
    # days halve it), not the count of marks; the previously injured site is scored as
    # pain_prior below, so it isn't counted twice here.
    episodes = pain_episodes(db, rid)
    prior_sites = prior_injury_sites(db, r, rid)
    _sex = getattr(r, "sex", None) or ""

    def _is_prior(ep):
        return any(_site_matches(ep["region"], ep["side"] or None, st) for st in prior_sites)

    rep_eps = [(key, ep) for key, ep in episodes.items()
               if ep["days"] >= _recur_min_days(_sex, ep["region"]) and ep["level"] > 0.01 and not _is_prior(ep)]
    if rep_eps:
        reg, ep = max(rep_eps, key=lambda x: episode_points(x[1]))
        p = rnd(episode_points(ep))
        if p:
            symp_score += p
            how = {"reset": "poslední označení bylo nad 75. percentilem dřívějších, váha se vrátila na plnou",
                   "partial": "poslední označení bylo mezi mediánem a 75. percentilem dřívějších, váha stoupla o polovinu zbytku",
                   "kept": "poslední označení bylo pod mediánem dřívějších, váhu nezvýšilo",
                   "first": "váhu určuje první označení"}[ep["how"]]
            clean = f" Od posledního označení {ep['clean']}× bez bolesti na tomto místě, každý takový den váhu půlí, třetí ji ukončí." \
                if ep["clean"] else ""
            push("niggle", "Opakované bolestivé místo", "A", p, f"{ep['days']}× / 28 dní",
                 f"{ep['label']} — označeno ve {ep['days']} dnech, nejvýš {ep['ref']}/10. Body neroste s počtem označení: "
                 f"{how}.{clean} Teď se počítá {round(ep['level'] * 100)} % plné váhy.")
            sig[-1]["region"] = reg          # "region|side", for its sources
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
            # v0.9.3 — today's reading only: the recurrence is scored by the site's pain
            # episode ("Opakované bolestivé místo"), which never grows with the count of marks
            ci_regions = [p.get("region") for p in (ci.pain_points or []) if p.get("region")]
            rec = pain_recurrence(db, rid)
            d2 = day_ago(2)
            recent2 = max((sum(1 for d in rec.get(r, []) if d > d2) for r in ci_regions), default=0)  # last 2 days
            run_rel = any(_run_relevant(r) for r in ci_regions)
            site = ", ".join(ci_regions) if ci_regions else (ci.pain_site or "—")
            back_to_back = run_rel and recent2 >= 2
            if back_to_back:
                p = base
                push("pain", f"Neustupující bolest: {site}", "A", p, f"{ci.pain_score}/10",
                     f"{site} — hlášeno {recent2}× během 2 dnů. Bolest, která mezi běhy neustupuje, je varovný signál přetížení. "
                     "Body určuje dnešní intenzita, opakování počítá signál Opakované bolestivé místo.")
            else:
                p = base
                nm = "Bolest při běhu" if base == 44 else "Přetrvávající bolest" if base == 26 else "Mírný diskomfort"
                push("pain", nm, "A", p, f"{ci.pain_score}/10", site)
            symp_score += p
            # (pain at a previously injured site is scored below as "pain_prior",
            #  from any mark in the last 14 days, feedback railway#91)
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
        # v0.9.3 — check-in items count only here, no longer also through readiness
        # (owner feedback 2026-09-30); weights are working assumptions.
        ls = getattr(ci, "life_stress", None)
        if ls is not None and ls >= 6:
            p = rnd(clamp((ls - 5) * 1.5, 0, 8))
            symp_score += p
            push("life_stress", "Stres mimo trénink", "C", p, f"{ls}/10",
                 "Ze self-reportu v check-inu. Stres mimo trénink ubírá z regenerace (Saw et al., 2016), počítá se 0,6× únavy.")
        sq = getattr(ci, "sleep_quality", None)
        if sq in (0, 1):
            p = 6 if sq == 0 else 3
            symp_score += p
            push("sleep_self", "Špatně prospaná noc", "C", p, "velmi špatně" if sq == 0 else "špatně",
                 "Vaše hodnocení noci v check-inu.")
    # v0.9.3 — in the Kapacitní engine the watch's sleep scales capacity through readiness,
    # so it isn't scored on Příznaky as well (owner feedback 2026-09-30)
    sleep_on_symp = cap_v3 is None
    if sleep_on_symp and rcv and rcv["sleep"]["debt"] is not None and rcv["sleep"]["debt"] >= 4:
        p = rnd(clamp(rcv["sleep"]["debt"] * 2.5, 0, 16))
        symp_score += p
        push("sleep", "Spánkový dluh", "B", p, f"−{rcv['sleep']['debt']} h/týden",
             f"{rcv['sleep']['now']} h proti obvyklým {rcv['sleep']['base']} h")
    if sleep_on_symp and sreg and sreg["ratio"] is not None and sreg["ratio"] >= 1.5:
        p = rnd(clamp((sreg["ratio"] - 1.5) * 12, 0, 14))
        symp_score += p
        push("sleepreg", "Nepravidelná délka spánku", "C", p, f"SD ×{sreg['ratio']}",
             f"kolísání délky spánku {sreg['sdNow']} h proti obvyklým {sreg['sdBase']} h za 14 dní")
    # v0.5 — low sleep efficiency (fragmented sleep) beyond raw duration
    if sleep_on_symp and seff and seff["now"] is not None and seff["now"] < 0.85:
        p = rnd(clamp((0.85 - seff["now"]) * 60, 0, 16))
        if p:
            symp_score += p
            usual = f" (obvykle {round(seff['base'] * 100)} %)" if seff["base"] else ""  # no nested same-quote f-string (Python < 3.12)
            push("sleepeff", "Nízká efektivita spánku", "C", p, f"{round(seff['now'] * 100)} %",
                 f"Ze spánku prospáno {round(seff['now'] * 100)} %{usual} — "
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
    # Feedback railway#91 — the injury history no longer adds points on its own
    # (it used to add 6–18 every day for 12 months, so the symptom axis never
    # cleared). It keeps lowering load tolerance (frailty), and it multiplies the
    # response when the runner marks that site again: one mark at any intensity
    # is enough (a new site needs recurrence or pain ≥ 3 first), and the points
    # grow with the number of days it was marked in the last 14.
    ph = prior_site_hits(db, rid, prior_sites)
    if ph:
        # v0.9.3 — the weight follows the site's pain episode (graduated re-marks, clean
        # days halve it, the 3rd ends it), no longer ×1,5 / ×2 for more marked days
        lv = [ep["level"] for ep in episodes.values() if _site_matches(ep["region"], ep["side"] or None, ph["site"])]
        mult = max(lv) if lv else pain_fade(age_of(ph.get("last")), pstate["cleared"])
        if rnd(ph["weight"] * mult) < 1:
            ph = None                   # the episode has ended: nothing left to show
    if ph:
        fp = 1.0
        p = rnd(ph["weight"] * mult)
        symp_score += p
        st = ph["site"]
        side = _SIDE_CZ.get(getattr(r, "prior_injury_side", None) or "", "") if st.get("profile") else ""
        push("pain_prior", "Bolest v místě dřívějšího zranění", "A", p, f"{ph['days']}× / {PRIOR_HIT_WINDOW} dní",
             f"{', '.join(x for x in ph['labels'] if x)} — místo dřívějšího zranění ({st['label']}{f', {side}' if side else ''}) "
             f"jste označil {ph['days']}× za {PRIOR_HIT_WINDOW} dní. U dříve zraněného místa stačí jediné označení "
             f"bez ohledu na intenzitu. Počet označení váhu nezvyšuje, řídí ji průběh bolesti na místě: teď "
             f"{round(mult * 100)} % plné váhy (dny bez bolesti ji půlí, třetí ji ukončí). Samotné zranění v anamnéze "
             f"body nepřidává, jen snižuje toleranci zátěže (×{r2(frailty)})."
             + (" Datum zranění chybí — počítáme ho jako nedávné, doplňte ho v profilu." if prior_unknown and st.get("profile") else "")
             + (f" Slábne s odstupem od posledního označení (×{r2(fp)})." if fp < 0.99 else ""))

    # v0.6 — a live reported/confirmed injury (OSTRC-H). Weighted on the
    # symptom axis on a par with an in-run pain report, scaled by severity;
    # a physio-confirmed conclusion carries grade A and a higher ceiling than
    # a runner self-report (grade B). Stored regardless (see injury()), but
    # only an *active* report with severity moves the score.
    if inj and inj["active"]:
        ia = inj["active"]
        sub = "omezená účast, objem nebo výkon" if ia["substantial"] else "plná účast s obtížemi"
        lvl = "alert" if ia["substantial"] else "watch"
        if ia["confirmed"]:
            p = rnd(clamp(ia["severity"] * 0.5, 0, 46))
            push("injury", "Potvrzené zranění (fyzioterapeut)", "A", p, f"OSTRC {ia['severity']}/100",
                 f"{ia['site']} — {sub}", rule=lvl)
        else:
            p = rnd(clamp(ia["severity"] * 0.34, 0, 32))
            push("injury", "Nahlášené zranění", "B", p, f"OSTRC {ia['severity']}/100",
                 f"{ia['site']} — {sub} · self-report, nepotvrzeno fyziem", rule=lvl)

    # v0.6 — broad recent-complaint signal. Frandsen 2025: same-site recurrence is
    # rare before injury (6.9 % at 7d), but a problem in *any* location preceded
    # 39.6 % of injuries within 28 days — so a broad complaint tally is a more
    # sensitive (if less specific) early flag than same-site recurrence alone.
    rec_all = pain_recurrence(db, rid)
    run_complaint_days = len({d for reg, dts in rec_all.items() if _run_relevant(reg) for d in dts})
    # v0.9.3 — "napříč místy": only with at least two different sites (one site marked
    # again and again is the repeated sore spot above), and it fades with the episodes
    live_sites = [ep for ep in episodes.values() if ep["level"] > 0.01]
    if run_complaint_days >= 3 and len(live_sites) >= 2:
        fc = max(ep["level"] for ep in live_sites)
        p = rnd(clamp((run_complaint_days - 2) * 4, 0, 14) * fc)
        if p:
            symp_score += p
            push("complaints", "Opakované obtíže (napříč místy)", "B", p, f"{run_complaint_days} dní / 28",
                 faded("Bolest hlášená ve více dnech za poslední 4 týdny, i když se místo mění. Opakované obtíže "
                       "předcházejí zranění častěji než jednorázová bolest — širší, citlivější varování než jen "
                       "recidiva stejného místa.", fc))

    # Prevention plan A1–A3: function, acute overload right after a run, and
    # races / maximal efforts (the last two feed the v3 guidance and the Dnes banners).
    func = function_limit(db, rid)
    if func:
        p = 45 if func["severe"] else 22
        what = "omezený pohyb" if func["limitsMovement"] else "kulhání" if func["limping"] else "upravený běh"
        push("function", "Bolest omezuje pohyb" if func["severe"] else "Bolest omezila běh", "A", p, what,
             f"{func['site'] or 'Nahlášená bolest'} — omezení v pohybu je úroveň zranění i při nízkém čísle bolesti "
             "(OSTRC). Běh vynechat a nechat posoudit.", rule="alert" if func["severe"] else "watch")
    acute = acute_overload(db, rid)
    if acute:
        push("acute", "Akutní přetížení po běhu", "B", 20, f"{acute['daysSince']} d",
             ", ".join(acute["reasons"]) + " — hned po běhu; den dva bez běhu, pak jen volně.", rule="watch")
    rtr = return_to_run(db, rid)
    pmon = pain_monitor(db, rid)
    if pmon and pmon["morningWorse"]:
        mw = pmon["morningWorse"]
        push("pain_morning", "Bolest ráno horší než při běhu", "B", 25, f"{mw['morning']}/10 vs {mw['during']}/10",
             f"{mw['site'] or 'Bolest'}: ráno po běhu {mw['morning']}/10, při běhu {mw['during']}/10. Podle modelu "
             "sledování bolesti (Silbernagel 2007) má bolest do rána odeznít — když je horší, byla zátěž moc; dnes bez běhu.",
             rule="watch")
    if pmon and pmon["trend"]:
        tr = pmon["trend"]
        symp_score += 12
        push("pain_trend", "Bolest týden od týdne roste", "B", 12, f"{_cz_num(tr['before'])} → {_cz_num(tr['now'])}",
             f"Průměrná hlášená bolest za 7 dní {_cz_num(tr['now'])}/10 proti {_cz_num(tr['before'])}/10 týden předtím — "
             "bolest nemá z týdne na týden růst (Silbernagel 2007); odlehčit, bez intenzity a dlouhého běhu.")
    # v0.8.4 — screening: red flags, bone-stress warning signs, bone-typical pain,
    # illness and the fatigue / illness / performance cluster (section H review).
    scr = screening(db, rid)
    if scr["redFlag"]:
        rf = scr["redFlag"]
        push("red_flag", "Varovné příznaky u bolesti zad", "A", 60,
             "okamžitě k lékaři" if rf["kind"] == "cauda" else "k lékaři",
             ("Bolest zad se změnou močení nebo stolice nebo s necitlivostí v rozkroku patří k příznakům, které "
              "vyžadují okamžité lékařské vyšetření." if rf["kind"] == "cauda" else
              "Bolest zad s horečkou nebo po pádu či úrazu je důvod nechat se co nejdřív vyšetřit lékařem.")
             + " Tréninková doporučení jsou do té doby pozastavená (Finucane et al., 2020).", rule="alert")
    if scr["boneStress"]:
        bs = scr["boneStress"]
        push("bone_stress", "Bolest s varovnými znaky přetížení kosti", "B", 40, ", ".join(bs["what"]),
             f"{bs['site']}: {', '.join(bs['what'])}. Takový průběh bývá u únavového přetížení kosti a patří "
             "k posouzení fyzioterapeutem nebo lékařem, bez ohledu na číslo bolesti (Warden et al., 2014). Dnes bez běhu.",
             rule="alert")
    elif scr["bonePain"]:
        bp = scr["bonePain"]
        p = 22 if bp["repeated"] else 14
        push("bone_pain", "Bolest v místě typickém pro přetížení kosti", "B", p, f"{bp['pain']}/10 · {bp['days14']}× / 14 dní",
             f"{bp['site']}: {bp['pain']}/10. U kosti se bolest nepřechází, návrat k běhu se řídí úplnou absencí bolesti "
             "(Warden et al., 2014), na rozdíl od šlachy, kde je tolerovaná bolest do 5/10 (Silbernagel et al., 2007). "
             "Dnes bez běhu, jiný sport jen bez bolesti." + (" Bolest se vrací, nechte ji posoudit fyzioterapeutem." if bp["repeated"] else ""),
             rule="watch")
    cluster = overload_cluster(db, rid, scr["illDays28"], (cap_v3 or {}).get("relativeEffort"))
    if cluster:
        symp_score += 14
        lbl = {"fatigue": f"únava ≥ 6/10 ve {cluster['fatigueDays']} dnech", "illness": f"nemoc {cluster['illDays']}× za 28 dní",
               "performance": f"tep při obvyklém tempu +{_cz_num(cluster['hrDelta'] or 0)} tepu"}
        push("cluster", "Únava, nemoc a pokles výkonu zároveň", "C", 14, f"{len(cluster['parts'])} ze 3",
             "Současně: " + ", ".join(lbl[k] for k in cluster["parts"]) + ". Taková kombinace má mnoho možných příčin "
             "(zátěž, spánek, stres, výživa, nemoc), proto ji stojí za to probrat s fyzioterapeutem nebo lékařem, "
             "místo hledání jedné příčiny (Jeukendrup et al., 2024).")
    hrmax_all, _rhr = hr_bounds(acts(db, rid), daily(db, rid, 180), r.birth_year if r else None, r.hr_max if r else None)
    efforts = max_efforts(db, rid, hrmax_all)
    race_rec = next((e for e in sorted(efforts, key=lambda e: e["date"], reverse=True) if e["daysSince"] < e["days"]), None)
    races = None
    if r is not None:
        rs = (cap_v3 or {}).get("readiness", {}).get("score") if cap_v3 else None
        if rs is None and any(0 <= x["daysTo"] <= 1 for x in races_for(db, r)):
            from . import capacity as CAP
            rs = CAP.readiness_by_day(db, rid, [iso_date(today_date())]).get(iso_date(today_date()), (1.0, {}, None))[2]
        races = race_outlook(db, rid, r, efforts, rs)

    # Frailty (injury history) reduces load tolerance: same objective load/mechanics
    # count for more. Multiplicative, so it amplifies existing signals only. Rounded
    # so scores stay integer end-to-end (and the live-formula backtest matches exactly).
    raw_axes = {"mech": mech_score, "load": load_score, "symp": symp_score}
    mech_score = rnd(clamp(mech_score * frailty, 0, 100))
    # (v3 already applies injury history by shrinking the capacity margins —
    # multiplying its load score as well would count it twice.)
    load_score = rnd(clamp(load_score * (1.0 if _emode() == "v3" else frailty), 0, 100))
    symp_score = rnd(clamp(symp_score, 0, 100))
    # v3 gives the load axis more say in the overall state (0.30 → 0.40).
    w_load = W_LOAD_V3 if _emode() == "v3" else W_LOAD
    overall = rnd(clamp(mech_score * W_MECH + load_score * w_load + symp_score * W_SYMP, 0, 100))
    impact_scale = impact_scales(raw_axes, {"mech": mech_score, "load": load_score, "symp": symp_score},
                                 {"mech": W_MECH, "load": w_load, "symp": W_SYMP}, overall)
    prev_quadrant = data.prev_quadrant
    # v2 Phase 2: across-session evidence label (informational — shown to the
    # user, NOT yet a hard quadrant gate). "flag" = persistence (EWMA past its
    # control limit + same sign in ≥2 of last 3 sessions, rule A) or convergence
    # (≥2 registry metrics clear, rule B); "watch" = one clear metric. The EWMA
    # smoothing already damps one-off spikes and accumulates genuine slow drift,
    # so the quadrant follows the smoothed mech score; the hard flag-gate is
    # deferred to the segmentation phase, where within-session "clear" (a CI over
    # many segments) is reliable enough to gate on.
    #
    # All labels are one-sided (risk direction only — an improvement never raises
    # the chip). Metrics that are mechanically coupled count as ONE piece of
    # evidence for convergence: vertical ratio = oscillation / step length, and at
    # a given speed step length = speed / cadence, so a single cadence change moves
    # both cadence and stride. Rule A also needs a real magnitude (≥ "possible"),
    # not just statistical consistency.
    mech_flag, mech_watch = _mech_flags(tv, gc, cad, strd, vosc) if _sensitive() else (False, False)
    quadrant = quadrant_of(load_score, mech_score, prev_quadrant)
    tier = tier_of(overall)
    # Repeated pain at the same running-relevant site, even mild, is the classic
    # overuse pattern — never "low risk / carry on": at least "watch", and the v3
    # guidance treats it like moderate pain (odlehčit). Pain > 5 keeps its own path.
    pain_recur = recurring_pain(db, rid)
    if pain_recur and tier == "ok":
        tier = "watch"
    # A4 — the risk label never contradicts the state (Přetížení / Tichý drift are
    # not "low risk"); A1/A2 — limited function is injury-level, acute overload at least "watch".
    order = {"ok": 0, "watch": 1, "alert": 2}
    rule_lvl = max((s_["rule"] for s_ in sig if s_.get("rule")), key=order.get, default="ok")
    floor = "alert" if (quadrant == "critical" or rule_lvl == "alert") else \
        "watch" if (quadrant in ("overreaching", "silent") or rule_lvl == "watch" or pmon or cluster) else "ok"
    if order[floor] > order[tier]:
        tier = floor
    # v0.9.0 — the safety rules (red flags, bone stress, limited function, acute
    # overload, morning pain, an active injury) sit outside the calibrated score: the
    # model axes stay what the calibration sees (`sympModel`, `overallModel`), and the
    # displayed numbers never contradict the tier or a rule.
    # v0.9.2 — instead of one fixed floor (every flagged day showed Skóre 60) the tier
    # sets the band and the model plus the severity of what raised the tier set the
    # place in it; ordinary days are spread over the ok band (see display_scores).
    trig = [(s_["rule"], clamp(s_["pts"] / RULE_PTS_MAX, 0, 1), "rule") for s_ in sig if s_.get("rule")]
    if quadrant == "critical":
        trig.append(("alert", clamp((min(load_score, mech_score) - QUAD_THRESHOLD) / 50, 0, 1), "quadrant"))
    elif quadrant == "overreaching":
        trig.append(("watch", clamp((load_score - QUAD_THRESHOLD) / 50, 0, 1), "quadrant"))
    elif quadrant == "silent":
        trig.append(("watch", clamp((mech_score - QUAD_THRESHOLD) / 50, 0, 1), "quadrant"))
    if pain_recur:
        trig.append(("watch", clamp(pain_recur["level"] * (pain_recur["ref"] or 1) / 10, 0.05, 1), "painRecurring"))
    if pmon:
        trig.append(("watch", 0.4 if pmon.get("morningWorse") else 0.3, "painMonitor"))
    if cluster:
        trig.append(("watch", 0.35, "cluster"))
    symp_model, overall_model = symp_score, overall
    disp = display_scores(overall_model, symp_model, tier, rule_lvl, trig)
    overall, symp_score = disp["overall"], disp["symp"]
    # impacts in points of the displayed Skóre: the model's share of it, split by signal
    impact_scale = {k: round(v * disp["modelScale"], 4) for k, v in impact_scale.items()}
    for s_ in sig:
        s_["axis"] = signal_axis(s_["id"])
        # a safety rule is not a model term: it sets the band instead of adding points
        s_["impact"] = None if s_.get("rule") else round(s_["pts"] * impact_scale[s_["axis"]], 2)

    out = {
        "runner_id": rid, "computed_at": now_iso(), "engine": engine_version_for(_emode()),
        "engineMode": _emode(), "mechRes": mech_res, "mechFlag": mech_flag, "mechWatch": mech_watch, "segmentScored": seg_scored,
        "mech": mech_score, "load": load_score, "symp": symp_score, "overall": overall,
        "sympModel": symp_model, "overallModel": overall_model, "ruleLevel": rule_lvl, "scoreBand": disp["band"],
        "tier": tier, "quadrant": quadrant, "confidence": conf,
        "signals": sorted(sig, key=lambda s: -s["pts"]),
        "loadDetail": L, "tavr": tv, "gct": gc, "bal": bal, "dec": dec, "aer": aer, "rcv": rcv, "fb": fb,
        "cadence": cad, "stride": strd, "vosc": vosc, "duty": duty, "gaitCv": gcv, "painWarn": pain_warn,
        "hrvCv": hcv, "sleepReg": sreg, "sleepEff": seff, "stiffness": stiff, "gradientDescent": gdesc, "gradientAscent": gasc, "injury": inj,
        "painRecurring": pain_recur, "functionLimit": func, "acuteOverload": acute, "raceRecovery": race_rec,
        "maxEfforts": efforts, "painMonitor": pmon, "returnToRun": rtr, "races": races,
        "screening": scr, "cluster": cluster, "painState": pstate,
        # v0.6 — single-session paradigm surface + capacity/frailty transparency +
        # forward-looking guardrail (the safe next-long-run ceiling).
        "sessionSpike": L.get("sessionSpike"), "spikeLatent": L.get("spikeLatent"),
        "sessionSpikeBasis": L.get("sessionSpikeBasis"),
        "paceSpike": L.get("paceSpike"), "safeLongRunKm": L.get("safeLongRunKm"),
        "capacityDeficit": capacity_deficit, "frailty": r2(frailty), "priorRegions": sorted(prior_regions),
        "capacity": cap_v3, "impactScale": impact_scale,
        # v0.9.0 — Připravenost for every engine (it replaced the Regenerace ring)
        "readiness": (cap_v3 or {}).get("readiness") or _readiness_block(data, rid),
    }
    # railway#113 — the records behind each signal (not in the history replay: past days
    # show the signals without sources, and 180 replays stay as fast as before)
    if getattr(_today_override, "value", None) is None:
        from . import signal_sources as SRC
        SRC.attach(db, rid, out, r)
    return out


def _readiness_block(data, rid):
    from . import capacity as CAP
    return CAP.readiness_block(data, rid)


# Feedback railway#111 — a signal's effect shown as the percentage points it takes off
# the overall Skóre (displayed as 100 − overall), not as axis points.
MECH_SIGNALS = frozenset({"tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv"})
LOAD_SIGNALS = frozenset({"pace_spike", "mono", "hr_pace", "hrv_high", "session_spike", "spike_latent", "ewma", "hi_load",
                          "load_creep", "desc", "desc_steep", "aer", "hrv", "rhr", "hrvcv", "tsb", "load_capacity", "taper"})


# v0.9.0 — safety rules set floors instead of adding model points
RULE_SIGNALS = frozenset({"red_flag", "bone_stress", "bone_pain", "function", "acute", "pain_morning", "injury"})
RULE_FLOOR_PTS = {"ok": 0, "watch": 40, "alert": 70}      # lowest displayed symptom axis under a rule
TIER_FLOOR_PTS = {"ok": 0, "watch": 40, "alert": 70}      # lowest displayed overall under a tier (the tier cut-offs)

# v0.9.2 — displayed scores. The v0.9.0 floor put every flagged day on exactly 40
# (Skóre 60) and ordinary days on a model risk of 0–8 (Skóre 92–100), so the 6-month
# chart barely moved. Now:
#  • the tier sets the band: ok 0–39, watch 40–69, alert 70–100 (unchanged cut-offs);
#  • a tier the model reached itself shows the model value (ok days through display_ok);
#  • a tier raised by a trigger (safety rule, quadrant, repeated pain, pain monitoring,
#    fatigue cluster) is placed in its band by 0.65 × the trigger's severity + 0.35 ×
#    the model, never below the model value.
# A display choice of the product team (working assumption), not a calibration: the
# calibration keeps reading `overallModel` / `sympModel`.
SCORE_BANDS = {"ok": (0, 39), "watch": (40, 69), "alert": (70, 100)}
DISPLAY_TAU = 12.0        # ok band curve: model 3 → 9, 8 → 20, 15 → 29, 25 → 35, 39 → 39
RULE_PTS_MAX = 46.0       # the largest rule points (a confirmed injury) = severity 1
_TIER_ORDER = {"ok": 0, "watch": 1, "alert": 2}


def tier_of(overall) -> str:
    return "alert" if overall >= 70 else ("watch" if overall >= 40 else "ok")


def display_ok(m: float) -> float:
    """Model risk 0–40 → displayed 0–39, spread at the low end where ordinary days sit."""
    m = clamp(m, 0, 40)
    return 39 * (1 - math.exp(-m / DISPLAY_TAU)) / (1 - math.exp(-40 / DISPLAY_TAU))


def display_scores(overall_model: float, symp_model: float, tier: str, rule_lvl: str, triggers: list) -> dict:
    """Displayed overall and symptom scores for a day. `triggers` = [(tier it forces,
    severity 0–1, what)]. Returns {overall, symp, modelScale, band}: modelScale turns
    model impacts into points of the displayed Skóre (the model's share of it)."""
    base = tier_of(overall_model)
    model_disp = display_ok(overall_model) if base == "ok" else overall_model
    band = None
    lo, hi = SCORE_BANDS[tier]
    held = [t for t in triggers if _TIER_ORDER[t[0]] >= _TIER_ORDER[tier]]
    if tier == base and not (held and tier != "ok"):
        overall = model_disp
    else:
        # v0.10.0 — a trigger's position also holds when the model reaches the same tier
        # itself, so more load can never show a lower Skóre than the trigger alone did
        at = held or triggers or [(tier, 0.0, "rule")]
        top = max(at, key=lambda t: t[1])
        pos = clamp(0.65 * top[1] + 0.35 * (display_ok(overall_model) / 39 if overall_model < 40 else 1.0), 0, 1)
        overall = max(model_disp if tier == base else overall_model, lo + (hi - lo) * pos)
        if overall > model_disp or tier != base:
            band = {"by": top[2], "severity": round(top[1], 2)}
    symp = symp_model
    if rule_lvl != "ok":
        lo, hi = SCORE_BANDS[rule_lvl]
        rs = max((t[1] for t in triggers if t[2] == "rule" and t[0] == rule_lvl), default=0.0)
        symp = max(symp_model, lo + (hi - lo) * rs)
    return {"overall": rnd(clamp(overall, 0, 100)), "symp": rnd(clamp(symp, 0, 100)),
            "modelScale": (model_disp / overall_model) if overall_model > 0 else 1.0, "band": band}


def signal_axis(sid: str) -> str:
    if sid in MECH_SIGNALS:
        return "mech"
    if sid in LOAD_SIGNALS or sid.startswith("cap_"):
        return "load"
    return "symp"


def impact_scales(raw: dict, final: dict, weights: dict, overall: float) -> dict:
    """{axis: Skóre percentage points per axis point}: the share of the axis points that
    survive injury history and the 0–100 cap, × the axis weight, × the share of the
    weighted sum that survives the overall 0–100 cap."""
    ov_raw = sum(final[k] * weights[k] for k in final)
    ov_k = overall / ov_raw if ov_raw > 0 else 1.0
    return {k: round((final[k] / raw[k] if raw[k] > 0 else 1.0) * weights[k] * ov_k, 4) for k in final}


DECISION_HEAD = {
    "physio_48h": "Objednat fyzioterapeuta do 48 hodin",
    "physio_7d": "Vyšetření do 7 dnů — mechanika se mění a k tomu hlášené obtíže",
    "app_program": "Preventivní program v aplikaci, kontrola za 7 dnů",
    "self_managed": "Pokračovat podle plánu",
}


def mechanics_corroborated(a: dict) -> bool:
    """Symptoms point the same way as a mechanics drift: the symptom axis over its
    threshold, or pain recurring at one running-relevant site."""
    return (a.get("symp") or 0) >= QUAD_THRESHOLD or bool(a.get("painRecurring"))


def triage_decision(a: dict) -> str:
    """The engine's own referral decision for an assessment — shared by the triage
    queue and the v3 training guidance (whose physio override requires it).

    v0.9.0: a mechanics drift ALONE ("Tichý drift") no longer refers to a physio —
    the watch's running-dynamics metrics have no shown link to injury (Mason et al.,
    2023; Neal et al., 2024). It stays "watch" with lighter guidance; a referral
    needs symptoms (or, in the critical state, load) pointing the same way."""
    if a["quadrant"] == "critical" or a["tier"] == "alert":
        return "physio_48h"
    if a["quadrant"] == "silent" and mechanics_corroborated(a):
        return "physio_7d"
    if a["tier"] == "watch" or a["quadrant"] == "silent":
        return "app_program"
    return "self_managed"


# Feedback #165 — treadmill runs whose mechanics stand far off the runner's outdoor
# norm (belt speed calibration, no wind, a different footstrike) are taken out of
# mechanics automatically. Shown in the run history, and the runner can put them back.
_TREADMILL_TITLE = re.compile(r"treadmill|běžeck\w* pás|\bpás\b|\bpas\b|indoor run", re.I)
TREADMILL_Z = 2.5          # |z| in any metric against the outdoor norm (working assumption)
TREADMILL_FIELDS = ("vert_ratio_pct", "gct_ms", "cadence_spm", "vert_osc_cm", "stride_len_m")


def is_treadmill(a) -> bool:
    return (a.surface or "") == "treadmill" or bool(_TREADMILL_TITLE.search(a.title or ""))


def treadmill_outliers(acts_all) -> dict:
    """{activity id: (field, z)} for treadmill runs of the last 90 days whose metric is
    ≥ TREADMILL_Z SDs off the median of the runner's other runs (≥ 6 of them)."""
    since = day_ago(90)
    runs = [a for a in acts_all if is_run(a) and a.started_at > since]
    norm = [a for a in runs if not is_treadmill(a) and not (a.excluded and (a.excluded_scope or "all") in ("all", "mech"))]
    out = {}
    stats = {}
    for f in TREADMILL_FIELDS:
        v = [getattr(a, f) for a in norm if getattr(a, f) is not None]
        if len(v) >= 6:
            m = median(v)
            s = max(sd(v), abs(m) * 0.01)
            stats[f] = (m, s)
    for a in runs:
        if not is_treadmill(a) or a.mech_keep or a.excluded:
            continue
        worst = None
        for f, (m, s) in stats.items():
            x = getattr(a, f)
            if x is None:
                continue
            z = (x - m) / s
            if abs(z) >= TREADMILL_Z and (worst is None or abs(z) > abs(worst[1])):
                worst = (f, round(z, 1))
        if worst:
            out[a.id] = worst
    return out


def auto_exclude_treadmill(db: DBSession, rid: str) -> int:
    rows = db.query(models.Activity).filter(models.Activity.runner_id == rid).all()
    hits = treadmill_outliers(rows)
    for a in rows:
        if a.id in hits:
            a.excluded, a.excluded_scope, a.excluded_at, a.auto_excluded = True, "mech", now_iso(), "treadmill"
    if hits:
        db.flush()
    return len(hits)


def recompute_assessment(db: DBSession, rid: str, data_changed: bool = True) -> dict:
    """Recomputes assess() and persists it, mirroring core.js's top-level
    assess(db,rid) which also upserts the runner's triage row. Call this
    after any mutation that can move the score (checkin, activity rating,
    daily-metric edit, garmin import, program claim).

    `data_changed=False` is the day-rollover refresh from
    get_or_refresh_assessment: nothing was written, so the cached history
    stays valid and only needs extending by the new day."""
    if data_changed:
        auto_exclude_treadmill(db, rid)          # feedback #165, before the snapshot is read
    data = D.load_runner_data(db, rid)          # the one read; everything below is pure
    r = data.runner
    with engine_pinned((r.engine_mode if r else None) or "v1"):
        a = assess(data, rid)
        # v3: today's training guidance (Trénink tab) — computed on the live recompute
        # only (every sync / check-in / rating / new day), never in history replays.
        a["guidance"] = None
        if a.get("engineMode") == "v3":
            from . import guidance as G
            _engine_ctx.priors = data.priors
            try:
                a["guidance"] = cz_deep(G.build_guidance(data, rid, a, r))
            finally:
                _engine_ctx.priors = None
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
         "duty", "gaitCv", "painWarn", "hrvCv", "sleepReg", "sleepEff", "stiffness", "gradientDescent", "gradientAscent", "injury",
         "engineMode", "mechRes", "mechFlag", "mechWatch", "segmentScored", "capacity", "guidance", "painRecurring",
         "functionLimit", "acuteOverload", "raceRecovery", "maxEfforts", "painMonitor", "returnToRun", "races",
         "screening", "cluster", "painState", "impactScale",
         "readiness", "sympModel", "overallModel", "ruleLevel")          # v0.9.0
    }
    db.flush()

    decision = triage_decision(a)
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
    # A data change (sync, check-in, rating, edit…) makes the cached history
    # replays stale: flag the daily quadrant history for an incremental re-check
    # and drop the weekly ones. A plain day rollover leaves them alone (the
    # quadrant history is extended by the new day, the weekly ones are keyed by
    # date and rebuild on their own).
    if data_changed:
        from .. import history as H
        H.mark_dirty(db, rid)
    db.commit()
    if data_changed:
        # Rebuild the history in the background right away, so it's ready
        # before anyone opens the strip or the trend charts.
        from .. import precompute
        precompute.schedule(rid)
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
    return recompute_assessment(db, rid, data_changed=False) if stale else assessment_row_to_dict(row)


def assessment_row_to_dict(row: models.Assessment) -> dict:
    """Reconstructs the assess()-shaped dict from a persisted Assessment row,
    for read endpoints that shouldn't recompute on every GET."""
    if row is None:
        return None
    out = {
        "runner_id": row.runner_id, "computed_at": row.computed_at, "engine": row.engine_version,
        "engineMode": mode_of_version(row.engine_version),
        "mech": row.mech, "load": row.load, "symp": row.symp, "overall": row.overall,
        "tier": row.tier, "quadrant": row.quadrant, "confidence": row.confidence_json,
        "signals": row.signals_json,
    }
    out.update(row.detail_json or {})
    return out
