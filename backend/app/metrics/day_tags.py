"""Suggestion #10 (owner request 2026-10-05): what moves the runner's readiness.

In the evening report the runner taps what the day and evening held: alcohol, a late meal,
stress, travel, a sauna … or "nothing of it". Each tag is then compared, in the runner's own
data, with the night after it: HRV, resting heart rate and sleep length, the night's parts
of readiness.

  • one night = the watch's night after day D (the DailyMetric dated D + 1);
  • every value against the runner's own baseline, the mean of the 14 nights before it (at
    least 7), HRV on the log scale (a percentage), so a slow drift of fitness or season
    doesn't count as an effect;
  • only evenings the runner answered: an evening without an answer is unknown, not
    "without alcohol"; "nothing of it" is the control night;
  • the day's training load is in the model too (y = b0 + b·tag + c·load): a hard session
    lowers the night's HRV on its own, and a sauna or a beer often follows one;
  • an effect is shown when at least 5 tagged and 10 untagged nights exist, with its 95 %
    interval; "clear" = the interval excludes zero and the effect is at least the smallest
    worthwhile change, half of the runner's own night-to-night SD (Plews et al., 2013);
    "no meaningful effect" = the whole interval is inside that band.

The tags are the usual suspects of the literature, e.g. alcohol lowers the night's HRV
dose-dependently (Pietilä et al., 2018) and caffeine late in the day shortens sleep (Drake
et al., 2013); the analysis only asks whether it is so for this runner. Window, minimums and
thresholds are working assumptions."""
import math
from datetime import date, timedelta

from .. import models

TAGS = [("alcohol", "Alkohol 1–2"), ("alcohol_more", "Alkohol 3 a víc"), ("late_meal", "Pozdní jídlo"),
        ("caffeine_late", "Káva odpoledne"), ("stress", "Stres"), ("travel", "Cestování"), ("sauna", "Sauna"),
        ("nap", "Spánek přes den"), ("screens", "Obrazovka v posteli")]
TAG_LABEL = dict(TAGS)
WINDOW_DAYS = 180
BASE_DAYS, BASE_MIN = 14, 7
MIN_TAG, MIN_CTRL = 5, 10
SWC_SD = 0.5
OUTCOMES = (("hrv", "HRV"), ("rhr", "klidový tep"), ("sleep", "spánek"))


def _t975(df: int) -> float:
    tab = ((1, 12.71), (2, 4.30), (3, 3.18), (4, 2.78), (5, 2.57), (6, 2.45), (7, 2.36), (8, 2.31), (9, 2.26),
           (10, 2.23), (12, 2.18), (15, 2.13), (20, 2.09), (25, 2.06), (30, 2.04), (40, 2.02), (60, 2.00), (120, 1.98))
    if df <= 1:
        return tab[0][1]
    for (d0, t0), (d1, t1) in zip(tab, tab[1:]):
        if d0 <= df <= d1:
            return t0 + (t1 - t0) * (df - d0) / (d1 - d0)
    return 1.96


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss–Jordan for the small normal equations (no numpy in the backend)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(y: list[float], cols: list[list[float]]) -> dict | None:
    """y ~ 1 + cols; the first column's coefficient with its standard error."""
    n, k = len(y), len(cols) + 1
    if n <= k:
        return None
    X = [[1.0] + [c[i] for c in cols] for i in range(n)]
    xtx = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None
    res = [y[r] - sum(beta[j] * X[r][j] for j in range(k)) for r in range(n)]
    s2 = sum(e * e for e in res) / (n - k)
    # the variance of beta[1] = s2 · (X'X)^-1[1][1]
    e1 = [1.0 if i == 1 else 0.0 for i in range(k)]
    inv1 = _solve(xtx, e1)
    if inv1 is None or inv1[1] <= 0:
        return None
    return {"b": beta[1], "se": math.sqrt(s2 * inv1[1]), "df": n - k}


def _sd(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def nights(db, rid: str, today: date) -> list[dict]:
    """Every answered evening D with the night after it, as deviations from the baseline:
    {d, tags, load, hrv (log), rhr (bpm), sleep (min)}."""
    start = today - timedelta(days=WINDOW_DAYS + BASE_DAYS + 1)
    dm = {m.date[:10]: m for m in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                                      models.DailyMetric.date >= start.isoformat()).all()}
    tags = {t.date: list(t.tags or []) for t in db.query(models.DayTag).filter(
        models.DayTag.runner_id == rid, models.DayTag.date >= (today - timedelta(days=WINDOW_DAYS)).isoformat()).all()}
    load: dict[str, float] = {}
    for a in db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                              models.Activity.started_at >= start.isoformat()).all():
        if a.excluded and (a.excluded_scope in (None, "all", "load")):
            continue
        d = (a.started_at or "")[:10]
        load[d] = load.get(d, 0.0) + float(a.training_load if a.training_load is not None else (a.duration_min or 0))

    def val(m, k):
        if m is None:
            return None
        if k == "hrv":
            return math.log(m.hrv_ms) if m.hrv_ms and m.hrv_ms > 0 else None
        if k == "rhr":
            return m.resting_hr
        return m.sleep_h * 60 if m.sleep_h else None

    out = []
    for d, tg in sorted(tags.items()):
        n_day = (date.fromisoformat(d) + timedelta(days=1))
        m = dm.get(n_day.isoformat())
        row = {"d": d, "tags": [t for t in tg if t in TAG_LABEL], "load": load.get(d, 0.0)}
        any_val = False
        for k, _ in OUTCOMES:
            v = val(m, k)
            base = [x for x in (val(dm.get((n_day - timedelta(days=j)).isoformat()), k) for j in range(1, BASE_DAYS + 1))
                    if x is not None]
            row[k] = (v - sum(base) / len(base)) if (v is not None and len(base) >= BASE_MIN) else None
            any_val = any_val or row[k] is not None
        if any_val:
            out.append(row)
    return out


def _effect(rows: list[dict], tag: str, k: str) -> dict:
    pts = [r for r in rows if r[k] is not None]
    if tag == "alcohol":                   # 1–2 drinks against evenings without alcohol (3+ is its own tag)
        pts = [r for r in pts if "alcohol_more" not in r["tags"]]
    if tag == "alcohol_more":
        pts = [r for r in pts if "alcohol" not in r["tags"]]
    y = [r[k] for r in pts]
    x = [1.0 if tag in r["tags"] else 0.0 for r in pts]
    n_tag, n_ctrl = int(sum(x)), len(x) - int(sum(x))
    out = {"n": n_tag, "nCtrl": n_ctrl, "status": "collecting"}
    if n_tag < MIN_TAG or n_ctrl < MIN_CTRL:
        return out
    loads = [r["load"] for r in pts]
    sd_l = _sd(loads)
    cols = [x] + ([[(v - sum(loads) / len(loads)) / sd_l for v in loads]] if sd_l > 0 else [])
    fit = ols(y, cols)
    if fit is None:
        return out
    t = _t975(fit["df"])
    b, lo, hi = fit["b"], fit["b"] - t * fit["se"], fit["b"] + t * fit["se"]
    swc = SWC_SD * _sd(y)
    status = ("clear" if (lo > 0 or hi < 0) and abs(b) >= swc else
              "none" if (lo > -swc and hi < swc) else "unclear")
    if k == "hrv":                         # log → percent
        b, lo, hi = ((math.exp(v) - 1) * 100 for v in (b, lo, hi))
    nd = 0 if k == "sleep" else 1
    return {**out, "status": status, "value": round(b, nd), "lo": round(lo, nd), "hi": round(hi, nd),
            "worse": (b < 0) if k in ("hrv", "sleep") else (b > 0)}


def _cz(v: float, d: int = 0) -> str:
    s = f"{abs(v):.{d}f}".replace(".", ",")
    return s[:-2] if d and s.endswith(",0") else s


def effect_text(k: str, e: dict) -> str:
    v = e["value"]
    if k == "hrv":
        return f"HRV o {_cz(v)} % {'níž' if v < 0 else 'výš'}"
    if k == "rhr":
        txt = _cz(v, 1)
        unit = "tepu" if "," in txt else "tep" if txt == "1" else "tepy" if txt in ("2", "3", "4") else "tepů"
        return f"klidový tep o {txt} {unit} {'výš' if v > 0 else 'níž'}"
    return f"spánek o {_cz(v)} min {'kratší' if v < 0 else 'delší'}"


def insights(db, rid: str, today: date, rows: list[dict] | None = None) -> list[dict]:
    rows = nights(db, rid, today) if rows is None else rows
    out = []
    for key, lab in TAGS:
        eff = {k: _effect(rows, key, k) for k, _ in OUTCOMES}
        n = max(e["n"] for e in eff.values())
        n_ctrl = max(e["nCtrl"] for e in eff.values())
        ready = [k for k, e in eff.items() if e["status"] != "collecting"]
        clear = [k for k in ready if eff[k]["status"] == "clear"]
        if not ready:
            need = max(0, MIN_TAG - n)
            text = (f"Zatím {n} {'večer' if n == 1 else 'večery' if 2 <= n <= 4 else 'večerů'} s tímto štítkem, "
                    f"potřeba aspoň {MIN_TAG}" + (f" a {MIN_CTRL} večerů bez něj." if n_ctrl < MIN_CTRL else "."))
            if n == 0:
                text = "Zatím žádný večer s tímto štítkem."
            status = "collecting"
        elif clear:
            text = ", ".join(effect_text(k, eff[k]) for k in clear) + f" ({n} nocí)."
            status = "clear"
            need = 0
        elif all(eff[k]["status"] == "none" for k in ready):
            text, status, need = f"U vás bez znatelného vlivu na noc ({n} nocí).", "none", 0
        else:
            text, status, need = f"Zatím nejasné, data se rozcházejí ({n} nocí). Další večery to upřesní.", "unclear", 0
        worse = any(eff[k].get("worse") for k in clear)
        out.append({"key": key, "label": lab, "n": n, "nCtrl": n_ctrl, "status": status, "need": need,
                    "text": text, "worse": worse, "effects": eff})
    rank = {"clear": 0, "unclear": 1, "none": 2, "collecting": 3}
    out.sort(key=lambda x: (rank[x["status"]], -x["n"]))
    return out


def evening(db, rid: str, today: date) -> dict:
    row = db.query(models.DayTag).filter(models.DayTag.runner_id == rid, models.DayTag.date == today.isoformat()).first()
    rows = nights(db, rid, today)
    return {"date": today.isoformat(), "tags": list(row.tags or []) if row is not None else None,
            "options": [{"key": k, "label": lab} for k, lab in TAGS], "answered": len(rows),
            "insights": insights(db, rid, today, rows)}


def last_night(db, rid: str, today: date) -> dict | None:
    """The morning report: yesterday's tags, what they usually do to this runner's night and
    how last night compares with the baseline."""
    y = (today - timedelta(days=1)).isoformat()
    row = db.query(models.DayTag).filter(models.DayTag.runner_id == rid, models.DayTag.date == y).first()
    if row is None or not row.tags:
        return None
    rows = nights(db, rid, today)
    ins = {x["key"]: x for x in insights(db, rid, today, rows)}
    me = next((r for r in rows if r["d"] == y), None)
    now = {}
    if me:
        if me["hrv"] is not None:
            now["hrv"] = round((math.exp(me["hrv"]) - 1) * 100)
        if me["rhr"] is not None:
            now["rhr"] = round(me["rhr"], 1)
        if me["sleep"] is not None:
            now["sleep"] = round(me["sleep"])
    items = [{"key": t, "label": TAG_LABEL[t], "status": ins[t]["status"], "text": ins[t]["text"], "n": ins[t]["n"],
              "effects": ins[t]["effects"]} for t in row.tags if t in TAG_LABEL]
    return {"date": y, "items": items, "now": now} if items else None


def note_last_night(x: dict | None) -> str | None:
    if not x:
        return None
    parts = []
    for it in x["items"]:
        if it["status"] == "clear":
            parts.append(f"{it['label']}: u vás obvykle {it['text']}")
    head = f"Včera: {', '.join(it['label'].lower() for it in x['items'])}."
    return " ".join([head] + parts) if parts else head + " Jak to u vás působí na noc, ukážou další večery."
