"""v0.12.0 — critical speed and the high-speed exposure.

Critical speed (CS) is the boundary between the heavy and the severe intensity domain:
above it the work cannot be sustained in a steady state and draws on a finite reserve
(D′), so the minutes above it are a better measure of hard running than a heart rate
that lags behind short efforts (Jones et al., 2019; Poole et al., 2016). It can be
estimated from training data alone: the best efforts over a few durations of the last
weeks, fitted with distance = CS × time + D′ (Smyth & Muniz-Pumares, 2020: CS from raw
training data of 25 000 marathon runners, the marathon run at ~85 % of it).

Here the best efforts are the best mean flat-equivalent (Minetti) speeds over 3, 6, 10,
15 and 20 minutes of contiguous segments in the 90 days before a session, plus each
whole run's grade-adjusted average as a lower bound for every duration it covers. The
fit only counts when the short effort was genuinely harder than the long one (D′ 30–600 m
and the 3-minute best ≥ 5 % above the longest), and CS is never below the best ≥ 25-min
run (a speed held that long is at or under CS). Without a valid fit there is no CS.

Uses, per session:
  • csMin    — minutes at or above CS (into Intenzita, the larger count kept);
  • thrMin   — minutes in [0.90 × CS, CS): threshold work, which delays cardiac autonomic
               recovery by 24–48 h (Stanley et al., 2013) — ≥ 20 min makes a hard day;
  • speed    — minutes at or above 1.10 × CS (≈ 3 km race pace and faster): the high-speed
               channel "Rychlost". Spikes in high-speed running preceded hamstring injuries
               (Duhig et al., 2016) and regular exposure to it was protective (Malone et
               al., 2017). Without CS: 1.45 × the median run speed of the 8 weeks before
               (working assumption). Strides shorter than a 20-s segment are not seen.
"""
from datetime import date, timedelta

from . import engine as E

CS_WINDOW = 90
CS_DURS = (180, 360, 600, 900, 1200)
CS_LONG_S = 1500            # a run held this long bounds CS from below
CS_DPRIME = (30.0, 600.0)   # metres
CS_SHORT_OVER = 1.05        # the 3-min best must be this much faster than the longest best
CS_RANGE = (2.0, 7.0)       # m/s
SEG_GAP_S = 15              # segments closer than this are one contiguous stretch
THR_LO = 0.90               # threshold work: 0.90–1.00 × CS
SPEED_CS = 1.10             # high-speed running: ≥ 1.10 × CS
SPEED_FALLBACK = 1.45       # …or 1.45 × the median run speed without a CS (working assumption)
SPEED_FALLBACK_DAYS, SPEED_FALLBACK_RUNS = 56, 5
DOWN_SKIP = -0.02           # downhill segments are fast without being hard

_MM_CACHE: dict = {}
_CS_CACHE: dict = {}


def _d(s):
    return date.fromisoformat(s[:10])


def flat_speed(sg) -> float | None:
    v, g = sg.get("meanSpeed"), sg.get("meanGradient") or 0.0
    if not v or (sg.get("durationS") or 0) <= 0:
        return None
    return v * E.minetti_cost(g) / E.minetti_cost(0.0)


def mean_max(segs, key=None) -> dict:
    """{duration s: best mean flat-equivalent speed over contiguous segments ≥ that long}."""
    if key is not None and key in _MM_CACHE:
        return _MM_CACHE[key]
    pts = []
    for sg in sorted(segs or (), key=lambda x: x.get("elapsedS") or 0):
        fs = flat_speed(sg)
        if fs is None:
            continue
        pts.append((sg.get("elapsedS") or 0, sg["durationS"], fs * sg["durationS"]))
    # contiguous stretches
    runs, cur, end = [], [], None
    for t, dur, dist in pts:
        if cur and t - end > SEG_GAP_S:
            runs.append(cur)
            cur = []
        cur.append((dur, dist))
        end = t + dur
    if cur:
        runs.append(cur)
    out = {}
    for T in CS_DURS:
        best = None
        for st in runs:
            i, tot_t, tot_d = 0, 0.0, 0.0
            for j, (dur, dist) in enumerate(st):
                tot_t += dur
                tot_d += dist
                while i < j and tot_t - st[i][0] >= T:      # shortest window still ≥ T
                    tot_t -= st[i][0]
                    tot_d -= st[i][1]
                    i += 1
                if tot_t >= T:
                    v = tot_d / tot_t
                    best = v if best is None or v > best else best
        if best is not None:
            out[T] = best
    if key is not None:
        if len(_MM_CACHE) > 20000:
            _MM_CACHE.clear()
        _MM_CACHE[key] = out
    return out


def _runs_before(runs, day: str, days: int):
    d0 = _d(day)
    return [s for s in runs if 1 <= (d0 - _d(s["date"])).days <= days]


def fit_cs(points: dict, long_bound: float | None) -> dict | None:
    """{cs, dPrime, n} from {T: best speed}; None when the fit isn't a real one."""
    ts = sorted(points)
    if len(ts) < 3 or ts[0] > 180 or ts[-1] < 600:
        return None
    if points[ts[0]] < CS_SHORT_OVER * points[ts[-1]]:
        return None                                   # no genuinely hard short effort
    xs = [float(t) for t in ts]
    ys = [points[t] * t for t in ts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    cs = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    dp = my - cs * mx
    if not (CS_RANGE[0] <= cs <= CS_RANGE[1]) or not (CS_DPRIME[0] <= dp <= CS_DPRIME[1]):
        return None
    if long_bound and long_bound > cs:
        cs = long_bound
    return {"cs": round(cs, 3), "dPrime": round(dp), "n": n}


def critical_speed(runs, segs_by_id, day: str) -> dict | None:
    """CS from the runs of the CS_WINDOW days before `day` (that day itself excluded)."""
    pool = _runs_before(runs, day, CS_WINDOW)
    key = (day, tuple(s["id"] for s in pool))
    if key in _CS_CACHE:
        return _CS_CACHE[key]
    best: dict = {}
    long_bound = None
    for s in pool:
        segs = segs_by_id.get(s["id"])
        if segs:
            for T, v in mean_max(segs, (s["id"], len(segs))).items():
                if v > best.get(T, 0):
                    best[T] = v
        g, dur = s.get("gSpeed"), (s.get("durationMin") or 0) * 60
        if g and dur:
            for T in CS_DURS:                        # a whole run is a lower bound for any shorter best
                if dur >= T and g > best.get(T, 0):
                    best[T] = g
            if dur >= CS_LONG_S and (long_bound is None or g > long_bound):
                long_bound = g
    out = fit_cs(best, long_bound)
    if out:
        out["asOf"] = day
    if len(_CS_CACHE) > 20000:
        _CS_CACHE.clear()
    _CS_CACHE[key] = out
    return out


def fallback_speed(runs, day: str) -> float | None:
    """1.45 × the median grade-adjusted run speed of the 8 weeks before `day`."""
    sp = sorted(s["gSpeed"] for s in _runs_before(runs, day, SPEED_FALLBACK_DAYS) if s.get("gSpeed"))
    if len(sp) < SPEED_FALLBACK_RUNS:
        return None
    return SPEED_FALLBACK * sp[len(sp) // 2]


def minutes_in(segs, lo: float, hi: float | None = None) -> float:
    """Minutes of segments with flat-equivalent speed in [lo, hi); downhill ones skipped."""
    sec = 0.0
    for sg in segs or ():
        if (sg.get("meanGradient") or 0.0) < DOWN_SKIP:
            continue
        fs = flat_speed(sg)
        if fs is not None and fs >= lo and (hi is None or fs < hi):
            sec += sg["durationS"]
    return sec / 60.0


def whole_run_minutes(s, lo: float, hi: float | None = None) -> float:
    g = s.get("gSpeed")
    if not g or not s.get("durationMin"):
        return 0.0
    return s["durationMin"] if (g >= lo and (hi is None or g < hi)) else 0.0


def add_speed(out, segs_by_id, since: str) -> None:
    """Per run since `since`: cs, csMin (into intensity when larger), thrMin and the
    high-speed exposure exp["speed"] (None when no threshold is known)."""
    runs = [s for s in out if s["run"]]
    for s in runs:
        s["exp"]["speed"] = None
        if s["date"] < since:
            continue
        segs = segs_by_id.get(s["id"])
        cs = critical_speed(runs, segs_by_id, s["date"])
        v_cs = cs["cs"] if cs else None
        v_fast = SPEED_CS * v_cs if v_cs else fallback_speed(runs, s["date"])
        if v_cs:
            s["cs"] = v_cs
            above = minutes_in(segs, v_cs) if segs else whole_run_minutes(s, v_cs)
            s["csMin"] = round(above, 1)
            s["thrMin"] = round(minutes_in(segs, THR_LO * v_cs, v_cs) if segs else whole_run_minutes(s, THR_LO * v_cs, v_cs), 1)
            if above > (s["exp"].get("intensity") or 0.0) + 0.5:
                s["exp"]["intensity"] = above
                s["z4Source"] = "cs"
        if v_fast:
            s["exp"]["speed"] = round(minutes_in(segs, v_fast) if segs else whole_run_minutes(s, v_fast), 2)


def cs_summary(sessions, segs_by_id, today: str) -> dict | None:
    """Today's CS for the detail: {cs m/s, pace s/km, dPrime m, n points}."""
    runs = [s for s in sessions if s["run"]]
    cs = critical_speed(runs, segs_by_id, (_d(today) + timedelta(days=1)).isoformat())
    if not cs:
        return None
    return {**cs, "paceSKm": round(1000 / cs["cs"]), "thrPaceSKm": round(1000 / (THR_LO * cs["cs"])),
            "speedPaceSKm": round(1000 / (SPEED_CS * cs["cs"]))}


def no_speed_weeks(sessions, today, days=28) -> dict | None:
    """v0.12.0 — no high-speed running in the last `days` days though there is speed data
    (the channel is known for the recent runs) and ≥ 6 weeks of runs: {lastDate|None}."""
    runs = [s for s in sessions if s["run"] and s["exp"].get("speed") is not None]
    if not runs:
        return None
    first = min(_d(s["date"]) for s in sessions if s["run"])
    if (today - first).days < 42:
        return None
    recent = [s for s in runs if 0 <= (today - _d(s["date"])).days < days]
    if len(recent) < 3 or any((s["exp"].get("speed") or 0) >= 0.5 for s in recent):
        return None
    older = [s["date"] for s in runs if (s["exp"].get("speed") or 0) >= 0.5 and (today - _d(s["date"])).days >= days]
    return {"lastDate": max(older) if older else None, "days": days}
