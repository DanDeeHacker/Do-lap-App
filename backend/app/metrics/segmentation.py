"""Stage S3 + S5 of the Per-Run Measurement Engine (Phase 5): split a cleaned
stream (~1 Hz or decimated — durations always come from timestamps) into short,
gradient-homogeneous segments and score each segment against the runner's OWN
baseline for that terrain, then aggregate to one duration-weighted session drift
index per metric.

This is what removes within-run averaging: a drift that only shows on the
downhills or late in a run produces high-z SEGMENTS that surface in the session
drift, instead of being flattened into a single per-run mean.

Context is adjusted here by comparing each segment only with baseline segments in
the same (surface, gradient-band) bucket; the continuous S4 context regression
(regression.py) replaces this once there are enough baseline segments. Pure and
deterministic; the stream fetch lives in garmin_live.
"""
from .stream_qc import _time_s, sample_weights

# Bump whenever segmentation/QC logic changes: stored streams carry the version in
# quality_json["segVersion"], and the stream backfill re-fetches older rows so
# every run is scored by the same segmenter. v2 = time-based durations (decimated
# Garmin streams), QC gate enforced, band persistence, de-noised descent, units.
SEG_VERSION = 2

MECH_FIELDS = ("cadence_spm", "gct_ms", "vo_cm", "vratio_pct", "step_len_m", "gct_bal_pct")

# Gradient bands (spec Table 8), fraction (e.g. 0.05 = +5%).
_BANDS = ((-1e9, -0.10, "B1"), (-0.10, -0.03, "B2"), (-0.03, 0.03, "B3"),
          (0.03, 0.10, "B4"), (0.10, 1e9, "B5"))
_BAND_GROUP = {"B1": "down", "B2": "down", "B3": "level", "B4": "up", "B5": "up"}
# Segment lengths are in SECONDS from the timestamps — Garmin may return ~1 Hz or
# a decimated stream (several s per row), so counting rows as seconds made long
# runs lose every segment.
MAX_SEG_S = 60
MIN_SEG_S = 20
MIN_SEG_SAMPLES = 5   # enough samples for a stable per-segment median
STEADY_CV = 0.10
GRADE_HALF_WINDOW_M = 25   # gradient over ~50 m: barometric noise (±~0.3 m) over 30 m was ±1–2 % grade
BAND_HOLD_S = 10           # a gradient band must hold this long before it counts as a band change
DESC_HYST_M = 1.0          # cumulative-descent dead-band — altitude jitter must not accumulate as descent
ALT_SMOOTH_HALF_S = 10     # altitude smoothing (± s) before gradients / descent


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


def _gradients(records, alts=None):
    """Centred ~50 m gradient per record from the distance and (smoothed, when
    given) altitude columns."""
    d = [r.get("distance_m") for r in records]
    a = alts if alts is not None else [r.get("altitude_m") for r in records]
    n = len(records)
    out = [0.0] * n
    for i in range(n):
        if d[i] is None or a[i] is None:
            continue
        j = i
        while j + 1 < n and d[j] is not None and d[i] is not None and d[j] - d[i] < GRADE_HALF_WINDOW_M:
            j += 1
        k = i
        while k - 1 >= 0 and d[k] is not None and d[i] is not None and d[i] - d[k] < GRADE_HALF_WINDOW_M:
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
    dur = sum(r["_w"] for r in chunk)  # seconds, from timestamps
    dist = 0.0
    if chunk[0].get("distance_m") is not None and chunk[-1].get("distance_m") is not None:
        dist = chunk[-1]["distance_m"] - chunk[0]["distance_m"]
    cv = (_std(spds) / _mean(spds)) if _mean(spds) else 1.0
    feat = {
        "band": chunk[0]["_band"], "surface": surface or "unknown",
        "durationS": round(dur), "distanceM": round(dist, 1),
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


def _debounce_bands(bands, ts, step):
    """Band persistence (hysteresis): stay in the current band until a different
    band has held for ≥ BAND_HOLD_S; shorter excursions keep the current band. On
    gentle terrain the gradient hovers around a ±3 % band edge and used to flicker
    between bands every few seconds, chopping the run into pieces shorter than
    MIN_SEG_S that were then discarded — biasing the data toward long uniform
    slopes. The starting band is the most common one over the first ~30 s."""
    n = len(bands)
    if not n:
        return []
    head = [b for b, t in zip(bands, ts) if t - ts[0] <= 30] or bands[:1]
    cur = max(set(head), key=head.count)
    out, i = [None] * n, 0
    while i < n:
        if bands[i] == cur:
            out[i] = cur
            i += 1
            continue
        j = i
        while j + 1 < n and bands[j + 1] == bands[i]:
            j += 1
        if ts[j] - ts[i] + step >= BAND_HOLD_S:
            cur = bands[i]
        for x in range(i, j + 1):
            out[x] = cur
        i = j + 1
    return out


def _smooth_alt(records, ts):
    """Centred moving average of altitude over ±ALT_SMOOTH_HALF_S seconds, so
    sample-to-sample barometric jitter doesn't turn into gradient noise or phantom
    descent. None where the record has no altitude."""
    n = len(records)
    a = [r.get("altitude_m") for r in records]
    out = [None] * n
    lo = hi = 0
    tot, cnt = 0.0, 0
    for i in range(n):
        while hi < n and ts[hi] <= ts[i] + ALT_SMOOTH_HALF_S:
            if a[hi] is not None:
                tot += a[hi]
                cnt += 1
            hi += 1
        while lo < n and ts[lo] < ts[i] - ALT_SMOOTH_HALF_S:
            if a[lo] is not None:
                tot -= a[lo]
                cnt -= 1
            lo += 1
        if a[i] is not None and cnt:
            out[i] = tot / cnt
    return out


def _cum_descent(alts):
    """Cumulative descent (m) up to each record from the smoothed altitude, with a
    DESC_HYST_M dead-band: only drops of ≥ 1 m below the last reference altitude
    count, and a rise of ≥ 1 m moves the reference up. Summing every tiny
    decrease of the raw altitude added jitter as phantom descent on flat ground."""
    out, cum, ref = [], 0.0, None
    for a in alts:
        if a is not None:
            if ref is None:
                ref = a
            elif a <= ref - DESC_HYST_M:
                cum += ref - a
                ref = a
            elif a >= ref + DESC_HYST_M:
                ref = a
        out.append(cum)
    return out


def segment(records, surface=None):
    """Split a cleaned stream into steady ≤60 s gradient-band segments.
    Returns a list of segment feature dicts (only steady, running segments)."""
    if not records:
        return []
    ts = _time_s(records)
    w, step, gap_s = sample_weights(ts)
    alts = _smooth_alt(records, ts)
    grades = _gradients(records, alts)
    bands = _debounce_bands([_band(g) for g in grades], ts, step)
    run = _running(records)
    # Cumulative descent (metres) up to each record — fatigue/eccentric-load proxy
    # that the S4 regression uses as a covariate (later in the run runs downhill-
    # tired legs differently even at the same speed/gradient).
    cum = _cum_descent(alts)
    for i, r in enumerate(records):
        r["_t"], r["_w"], r["_grade"], r["_band"], r["_cumdesc"] = ts[i], w[i], grades[i], bands[i], cum[i]
    segs, cur = [], []

    def close(chunk):
        if len(chunk) >= MIN_SEG_SAMPLES and sum(x["_w"] for x in chunk) >= MIN_SEG_S:
            segs.append(chunk)

    for i, r in enumerate(records):
        if not run[i]:
            close(cur)
            cur = []
            continue
        if cur:
            band_change = r["_band"] != cur[-1]["_band"]  # bands already debounced (_debounce_bands)
            gap = (ts[i] - cur[-1]["_t"]) > gap_s
            full = (ts[i] - cur[0]["_t"]) >= MAX_SEG_S
            if gap or full or band_change:
                close(cur)
                cur = []
        cur.append(r)
    close(cur)
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
