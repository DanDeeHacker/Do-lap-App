"""Stage S4 of the Per-Run Measurement Engine (Phase 5b): a per-runner, per-metric
context regression that predicts what a mechanics value *should* be for this
runner at a given speed, gradient, fatigue-time and surface — so the residual is
a genuine change in form, not just a hillier or faster route.

y = β0 + β1·v + β2·v² + β3·g + β4·g² + β5·v·g + β6·t + Σ surface dummies

Estimated by ridge regression (closed form, pure Python — no numpy) on the
runner's baseline segments, shrinking slopes toward zero when data is thin (with
little data the model ≈ the baseline mean, matching the simpler bucket method).
A population prior (partial pooling, spec 8.3 Phase B) plugs in via `beta_prior`
once there is a user base. Noise scale = robust SD of baseline residuals;
out-of-domain segments (unfamiliar speed/gradient) are not scored (spec 8.6).

Covariates limited to what stored segments carry (speed, gradient, elapsed time,
surface); cumulative descent D and apparent temperature H are deferred until
segment enrichment / weather (spec S2) land.
"""
_NUM_COLS = ("v", "v2", "g", "g2", "vg", "t")
_RIDGE_LAMBDA = 1.0      # penalty on standardised slopes [Calibrate]
_MIN_FIT_SEGMENTS = 30   # below this, caller should use the bucket method
_DOMAIN_PAD_V = 0.2      # m/s widening of the speed domain [Calibrate]
_DOMAIN_PAD_G = 0.03     # gradient widening [Calibrate]


def _raw(seg):
    v = seg.get("meanSpeed") or 0.0
    g = seg.get("meanGradient") or 0.0
    t = (seg.get("elapsedS") or 0) / 600.0  # per 10 minutes
    return {"v": v, "v2": v * v, "g": g, "g2": g * g, "vg": v * g, "t": t}


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return 0.0 if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def _pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, max(0, int(round(p / 100 * (len(xs) - 1)))))
    return xs[i]


def _solve(A, b):
    """Solve A x = b by Gaussian elimination with partial pivoting (k ≲ 10)."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for r in range(n):
            if r != col:
                f = M[r][col] / pv
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    return [M[i][n] / M[i][i] for i in range(n)]


def fit_metric(baseline_segments, field, lam=_RIDGE_LAMBDA, beta_prior=None):
    """Fit the ridge model for one metric on the runner's baseline segments.
    Returns a model dict, or None if there isn't enough data for a stable fit."""
    rows = [(s, _raw(s)) for s in baseline_segments if s.get(field) is not None]
    if len(rows) < _MIN_FIT_SEGMENTS:
        return None
    means = {c: sum(r[c] for _, r in rows) / len(rows) for c in _NUM_COLS}
    stds = {}
    for c in _NUM_COLS:
        var = sum((r[c] - means[c]) ** 2 for _, r in rows) / len(rows)
        stds[c] = (var ** 0.5) or 1.0
    # surface dummies: reference = most common; others with ≥3 segments
    surf_counts = {}
    for s, _ in rows:
        surf_counts[s.get("surface") or "unknown"] = surf_counts.get(s.get("surface") or "unknown", 0) + 1
    ref = max(surf_counts, key=surf_counts.get)
    dummies = [su for su, n in surf_counts.items() if su != ref and n >= 3]

    def design(seg, raw):
        row = [1.0] + [(raw[c] - means[c]) / stds[c] for c in _NUM_COLS]
        row += [1.0 if (seg.get("surface") or "unknown") == su else 0.0 for su in dummies]
        return row

    X = [design(s, r) for s, r in rows]
    y = [s[field] for s, _ in rows]
    k = len(X[0])
    # normal equations XᵀX + λP  (P = identity but 0 for the intercept)
    XtX = [[sum(X[m][i] * X[m][j] for m in range(len(X))) for j in range(k)] for i in range(k)]
    prior = beta_prior or [0.0] * k
    Xty = [sum(X[m][i] * y[m] for m in range(len(X))) for i in range(k)]
    for i in range(1, k):
        XtX[i][i] += lam
        Xty[i] += lam * prior[i]
    beta = _solve(XtX, Xty)
    if beta is None:
        return None
    resid = [y[m] - sum(beta[i] * X[m][i] for i in range(k)) for m in range(len(X))]
    sigma = 1.4826 * _median([abs(r - _median(resid)) for r in resid])
    vs = [r["v"] for _, r in rows]
    gs = [r["g"] for _, r in rows]
    return {
        "field": field, "beta": beta, "means": means, "stds": stds, "dummies": dummies,
        "sigma": max(sigma, 1e-6), "n": len(rows),
        "domain": {"vLo": _pct(vs, 5) - _DOMAIN_PAD_V, "vHi": _pct(vs, 95) + _DOMAIN_PAD_V,
                   "gLo": _pct(gs, 5) - _DOMAIN_PAD_G, "gHi": _pct(gs, 95) + _DOMAIN_PAD_G},
    }


def _design_row(model, seg):
    raw = _raw(seg)
    row = [1.0] + [(raw[c] - model["means"][c]) / model["stds"][c] for c in _NUM_COLS]
    row += [1.0 if (seg.get("surface") or "unknown") == su else 0.0 for su in model["dummies"]]
    return row, raw


def in_domain(model, seg):
    raw = _raw(seg)
    d = model["domain"]
    return d["vLo"] <= raw["v"] <= d["vHi"] and d["gLo"] <= raw["g"] <= d["gHi"]


def residual_z(model, seg):
    """Standardised residual for one segment, or None if out of domain."""
    if seg.get(model["field"]) is None or not in_domain(model, seg):
        return None
    row, _ = _design_row(model, seg)
    pred = sum(model["beta"][i] * row[i] for i in range(len(row)))
    return max(-4.0, min(4.0, (seg[model["field"]] - pred) / model["sigma"]))


_BAND_GROUP = {"B1": "down", "B2": "down", "B3": "level", "B4": "up", "B5": "up"}


def session_residual_drift(session_segments, model):
    """Duration-weighted mean segment residual for one session + gradient split."""
    num = den = 0.0
    by = {"down": [0.0, 0.0], "level": [0.0, 0.0], "up": [0.0, 0.0]}
    n = 0
    for s in session_segments:
        z = residual_z(model, s)
        if z is None:
            continue
        w = max(1, s.get("durationS", 1))
        num += z * w
        den += w
        g = by[_BAND_GROUP.get(s.get("band", "B3"), "level")]
        g[0] += z * w
        g[1] += w
        n += 1
    if not den:
        return None
    return {"di": round(num / den, 3), "nSeg": n,
            "byBand": {k: round(v[0] / v[1], 2) for k, v in by.items() if v[1] > 0}}
