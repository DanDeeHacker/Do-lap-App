"""v0.12.12 — the values the load is computed with, where each comes from, and when to update one.

Every load in the app rests on the heart-rate maximum, the resting heart rate, the threshold
heart rate (optional) and critical speed: TRIMP and the Z4+ minutes come from the heart-rate
reserve, Intenzita and Rychlost from critical speed. A maximum set too low inflates every hard
session's load, one set too high hides it ("accurate metrics need accurate zones"). The check
says which value is used and why, and flags: a recording that held a higher heart rate than the
maximum used, a maximum that is only an estimate, a threshold outside rest–max (then unused),
and critical speed that moved by 3 % or more in 6 weeks (Intenzita follows it by itself)."""
from datetime import date, timedelta

from . import engine as E

PEAK_SECONDS = 30            # the highest heart rate held ≥ 30 s in one recording: spikes and drop-outs left out
PEAK_DAYS = 180
PEAK_OVER = 3                # bpm above the maximum in use before a recording is flagged
PEAK_RANGE = (120, 225)      # outside it a "peak" is a sensor error
CS_SHIFT = 0.03
CS_BACK = 42
_PEAK_CACHE: dict = {}


def hist_peak(aid, hist: dict | None) -> float | None:
    """The highest heart rate (2-bpm bin middle) with ≥ PEAK_SECONDS at or above it."""
    if not hist:
        return None
    key = (aid, len(hist), round(sum(hist.values())))
    if key in _PEAK_CACHE:
        return _PEAK_CACHE[key]
    acc, out = 0.0, None
    for b, sec in sorted(((int(k), v or 0) for k, v in hist.items()), reverse=True):
        acc += sec
        if acc >= PEAK_SECONDS:
            out = b + 1.0
            break
    if len(_PEAK_CACHE) > 50000:
        _PEAK_CACHE.clear()
    _PEAK_CACHE[key] = out
    return out


def check(data, runner, runs: list, dailies: list, hrmax: float, rhr: float, cs_now: dict | None,
          cs_prev: dict | None, today: date) -> dict:
    measured = getattr(runner, "hr_max", None) if runner is not None else None
    birth = getattr(runner, "birth_year", None) if runner is not None else None
    lthr = getattr(runner, "threshold_hr", None) if runner is not None else None
    hardest = max((a.avg_hr for a in runs if a.avg_hr), default=None)
    age_est = None
    if birth:
        age = today.year - int(birth)
        if 8 < age < 100:
            age_est = round(E.clamp(208 - 0.7 * age, 150.0, 210.0))
    if measured:
        src = "profile" if measured >= (hardest or 0) else "runs"
    else:
        src = "runs" if hardest and hardest + 10 > (age_est or 185) else "age" if age_est else "default"
    # the highest heart rate a recording held, over the last half year
    since = (today - timedelta(days=PEAK_DAYS)).isoformat()
    peak = None
    for st in data.streams:
        hist = (st.quality_json or {}).get("hrHist")
        a = data.act_by_id.get(st.activity_id)
        if not hist or a is None or not a.started_at or a.started_at[:10] < since or getattr(a, "excluded", False):
            continue
        p = hist_peak(st.activity_id, hist)
        if p is not None and PEAK_RANGE[0] <= p <= PEAK_RANGE[1] and (peak is None or p > peak["hr"]):
            peak = {"hr": round(p), "date": a.started_at[:10], "title": a.title, "sport": a.sport or "running", "id": a.id}
    rests = [d.resting_hr for d in dailies if d.resting_hr]
    flags = []
    if peak and peak["hr"] >= hrmax + PEAK_OVER:
        flags.append({"key": "hrAbove", "tone": "watch", "hr": peak["hr"], "used": round(hrmax)})
    elif not measured:
        flags.append({"key": "hrEstimated", "tone": "info"})
    if lthr and not (rhr < lthr < hrmax):
        flags.append({"key": "lthrOut", "tone": "watch", "lthr": lthr})
    cs = None
    if cs_now:
        cs = {"paceSKm": cs_now.get("paceSKm"), "prevPaceSKm": (cs_prev or {}).get("paceSKm")}
        if cs_prev and cs_prev.get("cs"):
            ch = cs_now["cs"] / cs_prev["cs"] - 1
            cs["changePct"] = round(ch * 100, 1)
            if abs(ch) >= CS_SHIFT:
                flags.append({"key": "csShift", "tone": "info", "faster": ch > 0})
    return {"hrMax": {"value": round(hrmax), "source": src, "measured": measured, "ageEstimate": age_est,
                      "hardestAvg": round(hardest) if hardest else None},
            "hrRest": {"value": round(rhr), "nights": len(rests), "days": 180},
            "lthr": {"value": lthr, "used": bool(lthr and rhr < lthr < hrmax)},
            "cs": cs, "peak": peak, "flags": flags}
