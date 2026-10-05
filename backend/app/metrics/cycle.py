"""v0.12.0 — the menstrual cycle in readiness (women who turn tracking on in the profile).

Cardiac vagal activity is lower in the luteal than in the follicular phase (meta-analysis
of 37 studies, d ≈ 0.39 for high-frequency HRV; Schmalenberger et al., 2019), and resting
heart rate is a few beats higher in the luteal phase, so a luteal night compared with a
norm built from both phases looks like poorer recovery when it isn't. With tracking on
(and no hormonal contraception, which flattens the cycle), HRV and resting HR are
compared with the norm of the same phase:

  • the phase from the logged period starts and the cycle length (median of the last
    gaps, else the profile's): luteal = the last 14 days of the cycle (working
    approximation of the luteal phase), the rest follicular (the period included);
  • with ≥ 5 baseline nights in each phase, the runner's own difference: the norm is
    moved by the same-phase mean minus the all-nights mean;
  • otherwise a quarter of an SD, the half-difference d/2 ≈ 0.2 of the meta-analysis
    rounded up to the side of not alarming (HRV lower / HR higher in the luteal phase).

Without a logged start in the last cycle + 7 days the phase is unknown and nothing moves.
"""
from datetime import date, timedelta

LUTEAL_DAYS = 14
PERIOD_DAYS = 5
OWN_MIN = 5
DEFAULT_SD = 0.25
LATE_DAYS = 7


def _d(s):
    return date.fromisoformat(str(s)[:10])


def tracking(mj) -> bool:
    return bool(mj) and bool(mj.get("track")) and not mj.get("hormonal") and bool(mj.get("starts"))


def cycle_length(mj) -> int:
    starts = sorted(_d(x) for x in (mj or {}).get("starts") or [])
    gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if 20 <= (b - a).days <= 45][-6:]
    if gaps:
        g = sorted(gaps)
        return g[len(g) // 2]
    try:
        return int((mj or {}).get("length") or 28)
    except (TypeError, ValueError):
        return 28


def phase_on(mj, day) -> dict | None:
    """{day, length, phase: menstrual|follicular|luteal, group: follicular|luteal} or None."""
    if not tracking(mj):
        return None
    d0 = day if isinstance(day, date) else _d(day)
    prev = [s for s in (_d(x) for x in mj["starts"]) if s <= d0]
    if not prev:
        return None
    s0 = max(prev)
    length = cycle_length(mj)
    k = (d0 - s0).days + 1
    if k > length + LATE_DAYS:
        return None
    luteal = k > length - LUTEAL_DAYS
    phase = "menstrual" if k <= PERIOD_DAYS else "luteal" if luteal else "follicular"
    return {"day": k, "length": length, "phase": phase, "group": "luteal" if luteal else "follicular",
            "start": s0.isoformat()}


def shift(mj, d0, base_rows, fld, transform) -> tuple[float, str] | None:
    """How far to move the norm of `fld` (in the transformed units the readiness compares:
    Ln ms for HRV, bpm for resting HR) for the phase of `d0`: (shift, "own" | "default")."""
    ph = phase_on(mj, d0)
    if ph is None:
        return None
    same, other, allv = [], [], []
    for r in base_rows:
        v = transform(getattr(r, fld, None))
        if v is None:
            continue
        allv.append(v)
        p = phase_on(mj, _d(r.date))
        if p is None:
            continue
        (same if p["group"] == ph["group"] else other).append(v)
    if len(allv) < 3:
        return None
    m_all = sum(allv) / len(allv)
    if len(same) >= OWN_MIN and len(other) >= OWN_MIN:
        return sum(same) / len(same) - m_all, "own"
    sd = (sum((v - m_all) ** 2 for v in allv) / max(1, len(allv) - 1)) ** 0.5
    sign = 1 if ph["group"] == "luteal" else -1
    if fld == "hrv_ms":
        sign = -sign                      # HRV lower in the luteal phase
    return sign * DEFAULT_SD * sd, "default"


def next_start(mj, today) -> str | None:
    ph = phase_on(mj, today)
    if not ph:
        return None
    return (_d(ph["start"]) + timedelta(days=ph["length"])).isoformat()
