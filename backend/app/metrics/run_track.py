"""v0.12.13 — what the run detail draws from the detailed (per-second) data: the route, the pace
and heart rate along the run, the km splits and, for a steady long run, the aerobic decoupling.

Stored once per run on ActivityStream (route_json, series_json, splits_json) when the detailed
data is fetched, so the detail never needs the full stream again. The route is the runner's
alone: only their own session can read it (runners.run_route), never a physio, coach link or
the admin view.

Aerobic decoupling (Pa:HR): how much less speed each heartbeat buys in the second half of a
steady run than in the first. Less decoupling went with faster marathons in 82,303 runners
(Smyth et al. 2022). Heat and fluid loss raise the heart rate as well (cardiac drift), so a hot
run is flagged. "Under 5 %" as stable is a coaching convention (Friel), not a research threshold."""
import math

from . import stream_qc as QC
from . import terrain

ROUTE_TOL_M = 6.0          # Douglas–Peucker tolerance
ROUTE_MAX = 700            # points kept at most
SERIES_MAX = 240           # chart points at most
SPEED_MOVING = 1.0         # m/s: slower is a stop (no pace)
DEC_MIN_S = 60 * 60        # decoupling only for runs of at least 60 min
DEC_SKIP_S = 10 * 60       # the warm-up stays out
DEC_STEADY_CV = 0.12       # 1-min speed variation above this = not a steady run (intervals, fartlek)
DEC_STABLE = 5.0           # % — the convention for "stable"


def _xy(lat0, lat, lon):
    k = 111_320.0
    return lon * k * math.cos(math.radians(lat0)), lat * k


def _dp(pts: list, tol: float) -> list:
    """Douglas–Peucker on [(x, y, i)] → kept indices (iterative)."""
    if len(pts) < 3:
        return [p[2] for p in pts]
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay, _ = pts[a]
        bx, by, _ = pts[b]
        dx, dy = bx - ax, by - ay
        den = math.hypot(dx, dy) or 1e-9
        best, bi = -1.0, None
        for i in range(a + 1, b):
            px, py, _ = pts[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / den
            if d > best:
                best, bi = d, i
        if bi is not None and best > tol:
            keep.add(bi)
            stack += [(a, bi), (bi, b)]
    return [pts[i][2] for i in sorted(keep)]


def route(records: list) -> list | None:
    """[[lat, lon], …] simplified to ROUTE_TOL_M, at most ROUTE_MAX points; None without GPS."""
    pos = [(r["lat"], r["lon"]) for r in records if r.get("lat") is not None and r.get("lon") is not None]
    if len(pos) < 10:
        return None
    lat0 = pos[0][0]
    pts = [(*_xy(lat0, la, lo), i) for i, (la, lo) in enumerate(pos)]
    tol = ROUTE_TOL_M
    idx = _dp(pts, tol)
    while len(idx) > ROUTE_MAX:
        tol *= 1.6
        idx = _dp(pts, tol)
    return [[round(pos[i][0], 5), round(pos[i][1], 5)] for i in idx]


def _moving(recs: list):
    """(time s, distance m, speed m/s, hr, altitude) per record of the cleaned stream
    (stream_qc.process returns it cleaned)."""
    ts = QC._time_s(recs)
    out = []
    for r, t in zip(recs, ts):
        d = r.get("distance_m")
        if d is None:
            continue
        out.append((t, d, r.get("speed_ms"), r.get("hr"), r.get("altitude_m")))
    return out


def series(records: list) -> list | None:
    """Chart points along the distance: {km, t, pace s/km | None (a stop), hr, alt}, each the mean
    of its stretch (at most SERIES_MAX stretches)."""
    pts = _moving(records)
    if len(pts) < 20 or (pts[-1][1] - pts[0][1]) < 500:
        return None
    total = pts[-1][1] - pts[0][1]
    step = max(25.0, total / SERIES_MAX)
    out, cur, start = [], [], pts[0][1]
    for p in pts:
        cur.append(p)
        if p[1] - start >= step or p is pts[-1]:
            dt = cur[-1][0] - cur[0][0]
            dd = cur[-1][1] - cur[0][1]
            sp = dd / dt if dt > 0 else None
            hrs = [x[3] for x in cur if x[3]]
            alts = [x[4] for x in cur if x[4] is not None]
            out.append({"km": round(cur[-1][1] / 1000, 3), "t": round(cur[-1][0]),
                        "pace": round(1000 / sp) if sp and sp >= SPEED_MOVING else None,
                        "hr": round(sum(hrs) / len(hrs)) if hrs else None,
                        "alt": round(sum(alts) / len(alts), 1) if alts else None})
            cur, start = [p], p[1]
    return out


def splits(records: list) -> list | None:
    """Per km: {km, s (moving time), pace s/km, hr, up, down}; the last part km when ≥ 200 m."""
    pts = _moving(records)
    if len(pts) < 20:
        return None
    out = []
    k, acc = 1, {"s": 0.0, "d": 0.0, "hr": 0.0, "hs": 0.0, "up": 0.0, "down": 0.0}
    for a, b in zip(pts, pts[1:]):
        dt, dd = b[0] - a[0], b[1] - a[1]
        if dt <= 0 or dt > 30:
            continue
        if dd / dt >= SPEED_MOVING:
            acc["s"] += dt
        acc["d"] += dd
        if b[3]:
            acc["hr"] += b[3] * dt
            acc["hs"] += dt
        if a[4] is not None and b[4] is not None:
            dz = b[4] - a[4]
            acc["up" if dz > 0 else "down"] += abs(dz)
        if b[1] >= k * 1000:
            out.append(_split(k, acc))
            k, acc = k + 1, {"s": 0.0, "d": 0.0, "hr": 0.0, "hs": 0.0, "up": 0.0, "down": 0.0}
    if acc["d"] >= 200:
        out.append(_split(round(k - 1 + acc["d"] / 1000, 2), acc))
    return out or None


def _split(k, acc) -> dict:
    return {"km": k, "s": round(acc["s"]), "pace": round(acc["s"] / acc["d"] * 1000) if acc["d"] > 0 and acc["s"] > 0 else None,
            "hr": round(acc["hr"] / acc["hs"]) if acc["hs"] else None, "up": round(acc["up"]), "down": round(acc["down"])}


def decoupling(records: list, hot: bool = False) -> dict | None:
    """Pa:HR for a steady run of ≥ 60 min: grade-adjusted speed per heartbeat, first half vs second
    half of the moving time after the first 10 minutes. None for short or unsteady runs."""
    pts = _moving(records)
    if len(pts) < 60 or pts[-1][0] - pts[0][0] < DEC_MIN_S:
        return None
    flat = terrain.minetti_cr(0.0)
    rows = []                                 # (t, dt, grade-adjusted speed, hr)
    for a, b in zip(pts, pts[1:]):
        dt, dd = b[0] - a[0], b[1] - a[1]
        if dt <= 0 or dt > 30 or not b[3] or dd / dt < SPEED_MOVING:
            continue
        g = ((b[4] - a[4]) / dd) if (a[4] is not None and b[4] is not None and dd > 0) else 0.0
        g = max(-0.3, min(0.3, g))
        rows.append((b[0], dt, dd / dt * terrain.minetti_cr(g) / flat, b[3]))
    rows = [r for r in rows if r[0] - pts[0][0] >= DEC_SKIP_S]
    if len(rows) < 40:
        return None
    # steady? the variation of 1-minute speeds
    mins: dict = {}
    for t, dt, v, _ in rows:
        m = mins.setdefault(int(t // 60), [0.0, 0.0])
        m[0] += v * dt
        m[1] += dt
    sp = [s / w for s, w in mins.values() if w >= 30]
    if len(sp) < 20:
        return None
    mean = sum(sp) / len(sp)
    cv = (sum((x - mean) ** 2 for x in sp) / len(sp)) ** 0.5 / mean
    if cv > DEC_STEADY_CV:
        return None
    total = sum(r[1] for r in rows)
    half, acc = total / 2, 0.0
    first, second = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]          # Σ v·dt, Σ hr·dt, Σ dt
    for t, dt, v, hr in rows:
        h = first if acc < half else second
        h[0] += v * dt
        h[1] += hr * dt
        h[2] += dt
        acc += dt
    if not first[2] or not second[2]:
        return None
    ef1 = (first[0] / first[2]) / (first[1] / first[2])
    ef2 = (second[0] / second[2]) / (second[1] / second[2])
    pct = round((ef1 - ef2) / ef1 * 100, 1)
    return {"pct": pct, "stable": pct < DEC_STABLE, "hot": bool(hot), "minutes": round(total / 60),
            "hr1": round(first[1] / first[2]), "hr2": round(second[1] / second[2])}


def build(records: list, hot: bool = False) -> dict:
    """Everything the run detail stores from one detailed stream."""
    return {"route": route(records), "series": series(records), "splits": splits(records),
            "decoupling": decoupling(records, hot)}
