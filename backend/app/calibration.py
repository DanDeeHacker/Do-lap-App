"""Plan phase 4: calibration of the engine against health events.

Runs only after the gate in app.outcomes (at least 200 events, no runner above 5 %
of them); before that the report just says how far away the gate is. Nothing here
changes what runners see: the report tells the product team how today's points map
to observed event rates and whether a spline model predicts better, and the
threshold decision stays with the team and a physiotherapist. The probabilities
are internal only (MDR, see the project's regulatory note).

Method, following the provided literature:
* predictors stay continuous and enter through restricted cubic splines (Harrell's
  basis), recommended for prediction by Bache-Mathiesen et al. (2021); knots at
  Harrell's default quantiles, which the authors warn can misplace knots on very
  skewed data, so the report prints them for a visual check;
* evaluation by cross-validation grouped by runner, with the Brier score, the
  logarithmic score and a calibration table as the primary metrics and AUC only
  as a supplement (Carey et al., 2018);
* the in-app fit is a plain logistic regression (point estimates). The runner-level
  random intercept the plan asks for is fitted offline from the CSV export
  (`/api/engine/calibration/export`), because the app ships without a statistics
  library.
"""
import math
from collections import defaultdict

from sqlalchemy.orm import Session as DBSession

from . import models, outcomes

KNOT_QUANTILES = {3: (0.10, 0.50, 0.90), 4: (0.05, 0.35, 0.65, 0.95), 5: (0.05, 0.275, 0.50, 0.725, 0.95)}
FOLDS = 5
RIDGE = 1e-3


# ---------------------------------------------------------------- data
def mech_composite(r: dict):
    zs = [r.get("tavr_z"), r.get("gct_z"), -r["cadence_z"] if r.get("cadence_z") is not None else None, r.get("vosc_z")]
    zs = [z for z in zs if z is not None]
    return max(zs) if zs else 0.0


def load_ratio(r: dict):
    rs = [v for k, v in r.items() if k.startswith("cap_") and k.endswith("_ratio") and v is not None]
    return max(rs) if rs else None


def dataset(db: DBSession) -> list[dict]:
    rows = []
    rids = [x for (x,) in db.query(models.EngineDailySnapshot.runner_id).distinct()]
    for rid in rids:
        for r in outcomes.labelled_snapshots(db, rid):
            r["mech_z"] = mech_composite(r)
            r["load_x"] = load_ratio(r) if load_ratio(r) is not None else (r.get("load") or 0) / 25
            r["ready_def"] = 100 - (r.get("readiness") if r.get("readiness") is not None else 100)
            rows.append(r)
    return rows


def to_csv(rows: list[dict]) -> str:
    cols = ["runner_id", "date", "event", "overall", "mech", "load", "symp", "mech_z", "load_x", "ready_def"]
    extra = sorted({k for r in rows for k in r} - set(cols))
    out = [",".join(cols + extra)]
    for r in rows:
        out.append(",".join("" if r.get(c) is None else str(int(r[c]) if isinstance(r[c], bool) else r[c]) for c in cols + extra))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- restricted cubic splines
def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return 0.0
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def knots_for(xs, k=4):
    ks = [quantile(xs, q) for q in KNOT_QUANTILES[k]]
    out = []
    for v in ks:                    # identical knots (a spike of ties) are merged
        if not out or v > out[-1] + 1e-9:
            out.append(v)
    return out


def rcs_basis(x, knots):
    """Harrell's restricted cubic spline: x plus k−2 non-linear terms, linear beyond the outer knots."""
    k = len(knots)
    if k < 3:
        return [x]
    t_last, t_prev = knots[-1], knots[-2]
    norm = (t_last - knots[0]) ** 2 or 1.0
    p = lambda u: max(u, 0.0) ** 3   # noqa: E731
    terms = [x]
    for j in range(k - 2):
        tj = knots[j]
        v = p(x - tj) - p(x - t_prev) * (t_last - tj) / (t_last - t_prev) + p(x - t_last) * (t_prev - tj) / (t_last - t_prev)
        terms.append(v / norm)
    return terms


# ---------------------------------------------------------------- logistic regression (IRLS)
def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                if f:
                    for k in range(c, n + 1):
                        M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def _sig(z):
    return 1 / (1 + math.exp(-max(min(z, 35), -35)))


def fit_logistic(X, y, iters=50):
    p = len(X[0])
    beta = [0.0] * p
    for _ in range(iters):
        H = [[0.0] * p for _ in range(p)]
        g = [0.0] * p
        for xi, yi in zip(X, y):
            mu = _sig(sum(b * v for b, v in zip(beta, xi)))
            w = mu * (1 - mu)
            for a in range(p):
                g[a] += (yi - mu) * xi[a]
                for c in range(a, p):
                    H[a][c] += w * xi[a] * xi[c]
        for a in range(p):
            for c in range(a):
                H[a][c] = H[c][a]
            if a:                                   # ridge on the slopes, not the intercept
                H[a][a] += RIDGE
                g[a] -= RIDGE * beta[a]
        step = _solve(H, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return beta


def predict(beta, X):
    return [_sig(sum(b * v for b, v in zip(beta, xi))) for xi in X]


# ---------------------------------------------------------------- designs
def design_baseline(rows):
    """Today's engine, recalibrated: the logistic of the overall points."""
    return [[1.0, (r.get("overall") or 0) / 10] for r in rows]


def design_spline(rows, knots):
    X = []
    for r in rows:
        x = [1.0]
        for key in ("load_x", "mech_z", "ready_def", "symp"):
            x += rcs_basis(float(r.get(key) or 0.0), knots[key])
        X.append(x)
    return X


# ---------------------------------------------------------------- metrics
def brier(p, y):
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y)


def log_score(p, y):
    eps = 1e-9
    return sum(math.log(max(pi if yi else 1 - pi, eps)) for pi, yi in zip(p, y)) / len(y)


def auc(p, y):
    pos = [pi for pi, yi in zip(p, y) if yi]
    neg = [pi for pi, yi in zip(p, y) if not yi]
    if not pos or not neg:
        return None
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def calibration_table(p, y, bins=10):
    pairs = sorted(zip(p, y))
    n = len(pairs)
    out = []
    for b in range(bins):
        chunk = pairs[b * n // bins:(b + 1) * n // bins]
        if chunk:
            out.append({"predicted": round(sum(c[0] for c in chunk) / len(chunk), 4),
                        "observed": round(sum(c[1] for c in chunk) / len(chunk), 4), "n": len(chunk)})
    return out


def grouped_folds(rows, k=FOLDS):
    rids = sorted({r["runner_id"] for r in rows})
    fold_of = {rid: i % k for i, rid in enumerate(rids)}
    return [fold_of[r["runner_id"]] for r in rows]


def cross_validate(rows, make_design):
    """Out-of-fold predictions with every runner wholly in one fold."""
    folds = grouped_folds(rows)
    preds = [None] * len(rows)
    for f in sorted(set(folds)):
        tr = [r for r, g in zip(rows, folds) if g != f]
        te_idx = [i for i, g in enumerate(folds) if g == f]
        if not tr or not any(r["event"] for r in tr):
            continue
        Xtr, design_te = make_design(tr)
        beta = fit_logistic(Xtr, [1.0 if r["event"] else 0.0 for r in tr])
        for i, pi in zip(te_idx, predict(beta, design_te([rows[i] for i in te_idx]))):
            preds[i] = pi
    return preds


def _eval(preds, y):
    pairs = [(p, t) for p, t in zip(preds, y) if p is not None]
    if not pairs:
        return None
    p, t = [a for a, _ in pairs], [b for _, b in pairs]
    return {"brier": round(brier(p, t), 5), "logScore": round(log_score(p, t), 5),
            "auc": round(auc(p, t), 3) if auc(p, t) is not None else None,
            "calibration": calibration_table(p, t)}


def report(db: DBSession, force: bool = False, target_p: float | None = None) -> dict:
    ov = outcomes.overview(db)
    if not ov["gate"]["passed"] and not force:
        return {"status": "gated", "overview": ov}
    rows = dataset(db)
    if len(rows) < 20 or not any(r["event"] for r in rows):
        return {"status": "insufficient", "overview": ov, "rows": len(rows)}
    y = [1 if r["event"] else 0 for r in rows]

    def base_design(tr):
        return design_baseline(tr), design_baseline

    def spline_design(tr):
        kn = {key: knots_for([float(r.get(key) or 0.0) for r in tr]) for key in ("load_x", "mech_z", "ready_def", "symp")}
        return design_spline(tr, kn), (lambda rs: design_spline(rs, kn))

    base = _eval(cross_validate(rows, base_design), y)
    spl = _eval(cross_validate(rows, spline_design), y)
    null_p = sum(y) / len(y)
    beta = fit_logistic(design_baseline(rows), [float(v) for v in y])
    at = lambda pts: _sig(beta[0] + beta[1] * pts / 10)   # noqa: E731
    mapping = {"probAt25": round(at(25), 4), "probAt18": round(at(18), 4)}
    if target_p and beta[1] > 0 and 0 < target_p < 1:
        mapping["pointsForTarget"] = round((math.log(target_p / (1 - target_p)) - beta[0]) / beta[1] * 10, 1)
    better = bool(spl and base and spl["brier"] < base["brier"] and spl["logScore"] > base["logScore"])
    knots = {key: [round(v, 3) for v in knots_for([float(r.get(key) or 0.0) for r in rows])] for key in ("load_x", "mech_z", "ready_def", "symp")}
    return {"status": "ok", "overview": ov, "rows": len(rows), "eventRate": round(null_p, 4),
            "nullBrier": round(brier([null_p] * len(y), y), 5),
            "baseline": base, "spline": spl, "splineBetter": better, "knots": knots, "mapping": mapping,
            "note": "Pravděpodobnosti jsou jen interní. Náhodný intercept běžce se fituje offline z exportu."}


def per_runner_counts(rows):
    c = defaultdict(int)
    for r in rows:
        c[r["runner_id"]] += bool(r["event"])
    return dict(c)
