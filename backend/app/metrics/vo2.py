"""v0.12.22 (owner feedback 2026-11-04, #226) — an estimate of VO2max from the best efforts, shown
beside Kondice. It is the app's own estimate from the runner's own runs (no watch value: owner
decision 2026-10-03, no vendor metrics), never a measurement.

Method: Daniels & Gilbert's running equations (Daniels, Daniels' Running Formula): the oxygen cost
of a speed, VO2 = -4.60 + 0.182258·v + 0.000104·v² (v in m/min), divided by the share of VO2max
that can be held for that long, 0.8 + 0.1894393·e^(-0.012778·t) + 0.2989558·e^(-0.1932605·t)
(t in minutes). It is applied to the best flat-equivalent speed held for 6, 10, 15 and 20
minutes in the last 90 days (the best-effort curve of the Rychlost detail, speed.best_curve);
the highest of the four is the estimate, because a best effort can only under-state what the
body can do. The 3-minute best is left out (anaerobic share too large for the equations).

The range is the estimate ± 10 % (the usual error of such field estimates). Cooper's 12-minute
formula was considered as a cross-check and left out: on a fast runner it reads about 15 % above
Daniels' equations (58 against 50 for the same efforts), so it would only widen the range.
Without at least one of the four bests there is no estimate. All limits are working assumptions
of the product team."""
import math

USED = (360, 600, 900, 1200)         # seconds
RANGE = (25.0, 85.0)                 # ml/kg/min: outside it the input is not a running effort
ERR = 0.10


def vo2_cost(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min ** 2


def share_held(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def from_effort(speed_ms: float, t_s: float) -> float:
    """VO2max implied by holding `speed_ms` for `t_s` seconds."""
    return vo2_cost(speed_ms * 60.0) / share_held(t_s / 60.0)


def estimate(best_curve: dict | None) -> dict | None:
    """{value, low, high, basisMin, windowDays} from speed.best_curve(...)['now'], or None."""
    if not best_curve:
        return None
    paces = dict(zip(best_curve.get("durs") or (), best_curve.get("now") or ()))
    speed = {T: 1000.0 / p for T, p in paces.items() if p}
    cand = {T: from_effort(speed[T], T) for T in USED if T in speed}
    cand = {T: v for T, v in cand.items() if RANGE[0] <= v <= RANGE[1]}
    if not cand:
        return None
    basis = max(cand, key=cand.get)
    value = cand[basis]
    return {"value": round(value, 1), "low": round(value * (1 - ERR), 1), "high": round(value * (1 + ERR), 1),
            "basisMin": basis // 60, "windowDays": 90}
