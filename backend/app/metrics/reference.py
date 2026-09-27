"""Plan phases 1 and 2A: individual reference ranges and meaningful change.

Phase 1, Bayesian individualisation (Hecksteden et al., 2017, eqs. 1 and 2):
a population prior (mean m0, between-runner SD s0) is updated measurement by
measurement with the repeated-measures SD s_RM:

    m[n+1] = (s_RM² · m[n] + s[n]² · x[n+1]) / (s_RM² + s[n]²)
    s[n+1] = 1 / sqrt((n + 1) / s_RM² + 1 / s0²)

A new measurement is then judged against the predictive range m ± z·sqrt(s[n]² + s_RM²)
(the standard normal-normal predictive distribution, our derivation). Skewed
markers (HRV) are handled on the log scale, as the paper did for CK and urea.

The update runs only over the runner's rolling baseline window, so the range keeps
following fitness (Thornton et al., 2019, advise choosing the window for that) and
never narrows forever, which Hecksteden et al. themselves call implausible.

Phase 2A, meaningful change (Thornton et al., 2019): per metric and watch model,
the typical error TE = SD of the differences between comparable runs / √2 and the
smallest worthwhile change SWC = 0.2 × between-runner SD. A metric whose TE is not
below its SWC cannot resolve small changes and is down-weighted.

Priors, s_RM, TE and SWC come from the pooled Došlap data and are used only once at
least MIN_RUNNERS runners contribute (the 30-runner minimum is the product team's
proposal). Until then every function returns None and the engine keeps its
previous per-runner estimates.
"""
import math
import random
from datetime import date, datetime, timedelta

from .. import models
from . import engine as E

import os as _os
MIN_RUNNERS = int(_os.environ.get("DOSSLAP_REF_MIN_RUNNERS", "30"))   # proposal: runners before a prior is trusted
MIN_NIGHTS = 20         # nights per runner to enter the recovery priors
MIN_RUNS_BUCKET = 5     # runs in one terrain bucket to enter the mechanics priors
JACKKNIFE_SEED = 20170901
LOG_FIELDS = {"hrv_ms"}
RECOVERY_FIELDS = ("hrv_ms", "resting_hr")
MECH_FIELDS = ("vert_ratio_pct", "gct_ms", "cadence_spm", "vert_osc_cm")
_FIELD_ALIAS = {"gct_adj": "gct_ms", "vratio_pct": "vert_ratio_pct", "vo_cm": "vert_osc_cm"}
SHRINK_DF = 6           # pseudo degrees of freedom of the pooled s_RM when shrinking a runner's SD (proposal)
TE_PAIR_SPEED = 0.05    # comparable runs: same bucket, speeds within 5 %
LOW_RES_WEIGHT = 0.5    # weight of a metric whose TE is not below its SWC (proposal)

_cache: dict = {}       # (ISO week, key) → priors; recomputed once a week


# ---------------------------------------------------------------- the maths
def individualize(values, m0: float, s0: float, s_rm: float):
    """(m_n, s_n) after sequentially folding `values` into the prior (eqs. 1–2)."""
    m, s = m0, s0
    for n, x in enumerate(values):
        m = (s_rm ** 2 * m + s ** 2 * x) / (s_rm ** 2 + s ** 2)
        s = 1 / math.sqrt((n + 1) / s_rm ** 2 + 1 / s0 ** 2)
    return m, s


def predictive_sd(s_n: float, s_rm: float) -> float:
    return math.sqrt(s_n ** 2 + s_rm ** 2)


def _t(field, v):
    return math.log(v) if field in LOG_FIELDS and v and v > 0 else (None if field in LOG_FIELDS else v)


def pooled_sd(groups) -> float | None:
    """√(Σ var_i · df_i / Σ df_i): the within-runner (repeated-measures) SD."""
    num = den = 0.0
    for g in groups:
        if len(g) >= 2:
            num += E.sd(g) ** 2 * (len(g) - 1)
            den += len(g) - 1
    return math.sqrt(num / den) if den else None


def lmo_jackknife(groups, seed=JACKKNIFE_SEED):
    """(mean, SD) of the population distribution by 'leave multiple records out'
    jackknife (Hecksteden et al., 2017): leave one runner out, draw ONE record of
    every other runner (so within-runner variance is excluded), average the
    resamples' means and SDs."""
    rng = random.Random(seed)
    means, sds = [], []
    for i in range(len(groups)):
        draw = [rng.choice(g) for j, g in enumerate(groups) if j != i and g]
        if len(draw) >= 2:
            means.append(E.mean(draw))
            sds.append(E.sd(draw))
    return (E.mean(means), E.mean(sds)) if means else (None, None)


# ---------------------------------------------------------------- priors from the pooled data
def _real_today() -> date:
    """The wall-clock day, NOT the engine's pinned 'today': priors describe the
    population now and are the same for a live assessment and a history replay."""
    return datetime.now(E.LOCAL_TZ).date()


def _day_key():
    y, w, _ = _real_today().isocalendar()   # frozen per ISO week, so histories rebuild at most weekly
    return f"{y}-W{w:02d}"


def _since(days=120):
    return (_real_today() - timedelta(days=days)).isoformat()


def _main_session():
    """Priors always come from the main database, even when the engine runs on a
    history replay's throwaway in-memory copy of one runner."""
    from ..db import SessionLocal
    return SessionLocal()


# Generated tutorial runner (app.tutorial_demo): never part of population priors.
SYNTHETIC_RUNNERS = frozenset({"run_tutorial"})


def recovery_priors(db=None, field: str = "hrv_ms", min_runners: int | None = None):
    """{m0, s0, s_rm, n, log} for a recovery marker, or None below the runner minimum."""
    need = MIN_RUNNERS if min_runners is None else min_runners
    key = (_day_key(), "rec", field, need)
    if key in _cache:
        return _cache[key]
    since = _since()
    groups: dict[str, list[float]] = {}
    col = getattr(models.DailyMetric, field)
    mdb = _main_session()
    try:
        for rid, v in mdb.query(models.DailyMetric.runner_id, col).filter(models.DailyMetric.date >= since, col.isnot(None)):
            if rid in SYNTHETIC_RUNNERS:
                continue
            tv = _t(field, v)
            if tv is not None:
                groups.setdefault(rid, []).append(tv)
    finally:
        mdb.close()
    gs = [g for g in groups.values() if len(g) >= MIN_NIGHTS]
    out = None
    if len(gs) >= need:
        m0, s0 = lmo_jackknife(gs)
        s_rm = pooled_sd(gs)
        if m0 is not None and s0 and s_rm:
            out = {"m0": m0, "s0": s0, "s_rm": s_rm, "n": len(gs), "log": field in LOG_FIELDS}
    _cache[key] = out
    return out


def _speed(a):
    return E._speed_ms(a)


def mech_priors(db=None, field: str = "gct_ms", device: str | None = None, min_runners: int | None = None):
    """{s_rm, te, swc, between_sd, n, low_res} for a mechanics metric (optionally per
    watch model), or None below the runner minimum. Computed per (runner, terrain
    bucket) on raw values over the last 120 days."""
    field = _FIELD_ALIAS.get(field, field)   # derived drift fields borrow their raw column's priors
    if not hasattr(models.Activity, field):
        return None
    need = MIN_RUNNERS if min_runners is None else min_runners
    key = (_day_key(), "mech", field, device or "*", need)
    if key in _cache:
        return _cache[key]
    since = _since()
    mdb = _main_session()
    q = mdb.query(models.Activity).filter(models.Activity.started_at >= since, getattr(models.Activity, field).isnot(None))
    if device:
        q = q.join(models.Runner, models.Runner.id == models.Activity.runner_id).filter(models.Runner.device == device)
    by_rb: dict[tuple, list] = {}
    for a in q:
        if (a.excluded and a.excluded_scope != "load") or a.runner_id in SYNTHETIC_RUNNERS:
            continue
        by_rb.setdefault((a.runner_id, E.bucket(a)), []).append(a)
    mdb.close()
    groups, diffs, runner_means = [], [], {}
    for (rid, _b), acts in by_rb.items():
        if len(acts) < MIN_RUNS_BUCKET:
            continue
        vals = [getattr(a, field) for a in acts]
        groups.append(vals)
        runner_means.setdefault(rid, []).append(E.mean(vals))
        acts = sorted(acts, key=lambda a: a.started_at)
        for x, y in zip(acts, acts[1:]):          # consecutive comparable runs → typical error
            sx, sy = _speed(x), _speed(y)
            if sx and sy and abs(sx - sy) / max(sx, sy) <= TE_PAIR_SPEED:
                diffs.append(getattr(y, field) - getattr(x, field))
    out = None
    rmeans = [E.mean(v) for v in runner_means.values()]
    if len(rmeans) >= need and groups:
        s_rm = pooled_sd(groups)
        between = E.sd(rmeans)
        te = (E.sd(diffs) / math.sqrt(2)) if len(diffs) >= 10 else None
        swc = 0.2 * between if between else None
        out = {"s_rm": s_rm, "te": te, "swc": swc, "between_sd": between, "n": len(rmeans),
               "low_res": bool(te and swc and te >= swc)}
    _cache[key] = out
    return out


def clear_cache():
    _cache.clear()


def fingerprint() -> str:
    """Short digest of this week's priors, part of the history cache key (a new
    week's priors rebuild the cached histories in the background)."""
    import hashlib
    parts = [repr(recovery_priors(field=f)) for f in RECOVERY_FIELDS]
    parts += [repr(mech_priors(field=f)) for f in MECH_FIELDS]
    return hashlib.blake2b("|".join(parts).encode(), digest_size=4).hexdigest()


# ---------------------------------------------------------------- use in the engine
def shrunk_sd(sample_sd: float, n: int, s_rm: float | None) -> float:
    """A runner's SD from few runs, pulled towards the pooled s_RM (weights = degrees
    of freedom). Hecksteden et al. found no gain from individual repeated-measures
    SDs over the population one, so few runs lean on the pool (our adaptation)."""
    if not s_rm:
        return sample_sd
    df = max(n - 1, 0)
    return math.sqrt((df * sample_sd ** 2 + SHRINK_DF * s_rm ** 2) / (df + SHRINK_DF))


def recovery_deviation(field: str, baseline_values, x, priors):
    """(signed z of x against the individualised predictive range, posterior mean on
    the original scale) — or None when the value cannot be transformed."""
    tx = _t(field, x)
    if tx is None:
        return None
    tvals = [v for v in (_t(field, b) for b in baseline_values) if v is not None]
    m, s = individualize(tvals, priors["m0"], priors["s0"], priors["s_rm"])
    z = (tx - m) / predictive_sd(s, priors["s_rm"])
    return z, (math.exp(m) if priors["log"] else m), predictive_sd(s, priors["s_rm"])


def reference_band(field: str, baseline_values, priors, zq: float = 1.96):
    """(low, mid, high) of the individual 95 % reference range on the original scale."""
    tvals = [v for v in (_t(field, b) for b in baseline_values) if v is not None]
    m, s = individualize(tvals, priors["m0"], priors["s0"], priors["s_rm"])
    w = zq * predictive_sd(s, priors["s_rm"])
    if priors.get("log"):
        return math.exp(m - w), math.exp(m), math.exp(m + w)
    return m - w, m, m + w


def dead_zone_z(field: str, within_sd: float | None, mp) -> float:
    """Phase 2A: the mechanics dead zone in z units = SWC / within-runner SD, never
    below the previous 0.2 SD (Thornton et al., 2019: change must exceed the SWC)."""
    if not mp or not mp.get("swc") or not within_sd:
        return 0.2
    return max(0.2, min(1.0, mp["swc"] / within_sd))


def metric_weight_factor(mp) -> float:
    """Phase 2A: a metric whose typical error is not below its SWC counts at half weight."""
    return LOW_RES_WEIGHT if (mp and mp.get("low_res")) else 1.0


def days_back(day, lo, hi):
    return [(day - timedelta(days=j)).isoformat() for j in range(lo, hi + 1)]
