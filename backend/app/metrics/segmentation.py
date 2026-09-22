"""Stage S3 + S5 of the Per-Run Measurement Engine (Phase 5): split a cleaned
1 Hz stream into short, gradient-homogeneous segments and score each segment
against the runner's OWN baseline for that terrain, then aggregate to one
duration-weighted session drift index per metric.

This is what removes within-run averaging: a drift that only shows on the
downhills or late in a run produces high-z SEGMENTS that surface in the session
drift, instead of being flattened into a single per-run mean.

Context is adjusted by comparing each segment only with baseline segments in the
same (surface, gradient-band) bucket. The full continuous regression (spec S4,
speed/grade quadratics + partial pooling) is deferred — it needs numpy and a
user base — but the segment-vs-own-baseline design already realises the core
principle. Pure and deterministic; the stream fetch lives in garmin_live.
"""

MECH_FIELDS = ("cadence_spm", "gct_ms", "vo_cm", "vratio_pct", "step_len_m", "gct_bal_pct")

# Gradient bands (spec Table 8), fraction (e.g. 0.05 = +5%).
_BANDS = ((-1e9, -0.10, "B1"), (-0.10, -0.03, "B2"), (-0.03, 0.03, "B3"),
          (0.03, 0.10, "B4"), (0.10, 1e9, "B5"))
_BAND_GROUP = {"B1": "down", "B2": "down", "B3": "level", "B4": "up", "B5": "up"}
MAX_SEG_S = 60
MIN_SEG_S = 20
STEADY_CV = 0.10


def _band(g: float) -> str:
    for lo, hi, name in _BANDS:
        if lo <= g < hi:
            return name
    return "B3"


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if not n:
        return None
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2


def _mad(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    m = _median(xs)
    return 1.4826 * _median([abs(x - m) for x in xs])


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _times(records):
    if records and records[0].get("elapsed_s") is not None:
        return [r.get("elapsed_s", i) for i, r in enumerate(records)]
    return [float(i) for i in range(len(records))]  # assume ~1 Hz


def _gradients(records):
    """Centred ~30 m gradient per record from the distance/altitude columns."""
    d = [r.get("distance_m") for r in records]
    a = [r.get("altitude_m") for r in records]
    n = len(records)
    out = [0.0] * n
    for i in range(n):
        if d[i] is None or a[i] is None:
            continue
        j = i
        while j + 1 < n and d[j] is not None and d[i] is not None and d[j] - d[i] < 15:
            j += 1
        k = i
        while k - 1 >= 0 and d[k] is not None and d[i] is not None and d[i] - d[k] < 15:
            k -= 1
        if d[j] is None or d[k] is None or a[j] is None or a[k] is None:
            continue
        dd = d[j] - d[k]
        out[i] = (a[j] - a[k]) / dd if dd > 0 else 0.0
    return out


def _running(records):
    has_mech = any(r.get("gct_ms") is not None for r in records)
    def ok(r):
        s = r.get("speed_ms")
        if has_mech:
            return r.get("gct_ms") is not None and s is not None and s > 0.5
        return s is not None and s >= 1.6
    return [ok(r) for r in records]


def _features(chunk, surface):
    spds = [r.get("speed_ms") for r in chunk if r.get("speed_ms") is not None]
    dur = len(chunk)  # ~seconds at 1 Hz
    dist = 0.0
    if chunk[0].get("distance_m") is not None and chunk[-1].get("distance_m") is not None:
        dist = chunk[-1]["distance_m"] - chunk[0]["distance_m"]
    cv = (_std(spds) / _mean(spds)) if _mean(spds) else 1.0
    feat = {
        "band": chunk[0]["_band"], "surface": surface or "unknown",
        "durationS": dur, "distanceM": round(dist, 1),
        "meanSpeed": round(_mean(spds), 3), "meanGradient": round(_mean([r["_grade"] for r in chunk]), 4),
        "elapsedS": chunk[0]["_t"], "cumDescentM": round(chunk[0].get("_cumdesc", 0.0), 1),
        "steady": cv <= STEADY_CV,
    }
    for f in MECH_FIELDS:
        feat[f] = _median([r.get(f) for r in chunk])
    return feat


def _std(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def segment(records, surface=None):
    """Split a cleaned 1 Hz stream into steady ~60 s gradient-band segments.
    Returns a list of segment feature dicts (only steady, running segments)."""
    if not records:
        return []
    ts = _times(records)
    grades = _gradients(records)
    run = _running(records)
    # Cumulative descent (metres) up to each record — fatigue/eccentric-load proxy
    # that the S4 regression uses as a covariate (later in the run runs downhill-
    # tired legs differently even at the same speed/gradient).
    cum = 0.0
    prev_alt = None
    for i, r in enumerate(records):
        a = r.get("altitude_m")
        if a is not None and prev_alt is not None and a < prev_alt:
            cum += prev_alt - a
        if a is not None:
            prev_alt = a
        r["_t"], r["_grade"], r["_band"], r["_cumdesc"] = ts[i], grades[i], _band(grades[i]), cum
    segs, cur = [], []
    for i, r in enumerate(records):
        if not run[i]:
            if len(cur) >= MIN_SEG_S:
                segs.append(cur)
            cur = []
            continue
        if cur:
            band_change = r["_band"] != cur[-1]["_band"] and (ts[i] - cur[-1]["_t"]) >= 0  # persistence handled by min-length merge
            gap = (ts[i] - cur[-1]["_t"]) > 5
            full = (ts[i] - cur[0]["_t"]) >= MAX_SEG_S
            if gap or full or band_change:
                if len(cur) >= MIN_SEG_S:
                    segs.append(cur)
                cur = []
        cur.append(r)
    if len(cur) >= MIN_SEG_S:
        segs.append(cur)
    feats = [_features(c, surface) for c in segs]
    return [f for f in feats if f["steady"]]


# --- S5: score segments against the runner's own per-bucket baseline ----------

def baseline_stats(baseline_segments):
    """Per (field, surface, band) → (median, mad) over all baseline segments.
    This is the runner's own norm and typical error for that exact terrain."""
    groups = {}
    for s in baseline_segments:
        key = (s["surface"], s["band"])
        for f in MECH_FIELDS:
            if s.get(f) is not None:
                groups.setdefault((f, key), []).append(s[f])
    stats = {}
    for k, vals in groups.items():
        if len(vals) >= 3:
            c = _median(vals)
            stats[k] = (c, max(_mad(vals), abs(c) * 0.012, 1e-6))
    return stats


def session_drift(session_segments, stats, field):
    """Duration-weighted mean of segment z-scores for one metric in one session,
    plus the drift split by gradient group (the within-run decomposition)."""
    num = den = 0.0
    by = {"down": [0.0, 0.0], "level": [0.0, 0.0], "up": [0.0, 0.0]}
    n = 0
    for s in session_segments:
        v = s.get(field)
        st = stats.get((field, (s["surface"], s["band"])))
        if v is None or st is None:
            continue
        z = max(-4.0, min(4.0, (v - st[0]) / st[1]))
        w = max(1, s["durationS"])
        num += z * w
        den += w
        g = by[_BAND_GROUP[s["band"]]]
        g[0] += z * w
        g[1] += w
        n += 1
    if not den:
        return None
    by_out = {k: round(v[0] / v[1], 2) for k, v in by.items() if v[1] > 0}
    return {"di": round(num / den, 3), "nSeg": n, "byBand": by_out}
