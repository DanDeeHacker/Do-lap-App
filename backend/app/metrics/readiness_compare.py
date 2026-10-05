"""Readiness before and after engine v0.11.0 (sleep rules), side by side.

    python -m app.metrics.readiness_compare                 # every runner in the app database, last 56 days
    python -m app.metrics.readiness_compare --days 120 --runner run-0011
    python -m app.metrics.readiness_compare --synthetic     # a simulated runner with known fatigue episodes
    GET /api/runners/{rid|me}/readiness-compare?days=56     # the same for one runner, as JSON (report())

v0.11.0 changed only the sleep part of readiness (owner request 2026-10-04): sleep
length and sleep quality are separate parts, quality is the sleep efficiency of the last
3 nights (the deep + REM share is no longer scored), at most a quarter of a signal and
half of that without HRV / resting HR confirming, and the 7-hour floor applies only
until the runner's own norm is known. HRV, resting HR and the day's heart rate are the
same in both columns, so every difference here comes from sleep.

The "v0.10" column re-creates the earlier rule below (legacy_sleep). Per runner the
script prints the mean score, the days a sleep part cost ≥ 10 points, and — where the
runner filled in check-ins — how each score tracks the check-in's fatigue and sleep
rating (Spearman ρ; fatigue should go against readiness, i.e. ρ < 0).

Read-only: it never writes to the database.
"""
import argparse
import math
import random
from datetime import date, timedelta
from types import SimpleNamespace

from . import capacity as C
from . import data as D
from . import engine as E

# ---------------------------------------------------------------- the v0.10 sleep rule
OLD_QUALITY_W = 0.5
OLD_SD_FLOOR = {"rest_share": 0.03, "sleep_efficiency": 0.02}


def legacy_sleep(dm: dict, d0: date) -> float | None:
    """The v0.10.x sleep part for day d0 (runners with ≥ 14 baseline nights): length
    over the last 3 nights or the 7-hour floor, compounded with last night's quality
    (deep + REM share and efficiency, at most half a signal)."""
    day = d0.isoformat()
    night = dm.get(day)
    if night is None:
        return None
    base_rows = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(C.READY_BASE[0], C.READY_BASE[1] + 1)) if k in dm]
    if len(base_rows) < 14:
        return None
    base = {}
    for fld in ("sleep_h", "sleep_efficiency", "rest_share"):
        vals = [v for v in ((C.rest_share(b) if fld == "rest_share" else getattr(b, fld, None)) for b in base_rows) if v is not None]
        if len(vals) >= 10 and (E.sd(vals) or fld in OLD_SD_FLOOR):
            base[fld] = (E.mean(vals), E.sd(vals) or 0.0)
    nights = [getattr(dm.get((d0 - timedelta(days=j)).isoformat()), "sleep_h", None) for j in range(4)]
    rec = [h for h in nights[:3] if h is not None]
    recent = E.mean(rec) if len(rec) >= 2 and nights[0] is not None else night.sleep_h
    dur = qual = None
    if "sleep_h" in base and night.sleep_h is not None:
        dur = E.clamp((base["sleep_h"][0] - recent - 0.5) / 2.0, 0, 1)
    ab = C._sleep_abs(nights)
    if ab:
        dur = max(dur or 0.0, ab)
    now = {"rest_share": C.rest_share(night), "sleep_efficiency": night.sleep_efficiency}
    for key in ("rest_share", "sleep_efficiency"):
        if key in base and now[key] is not None:
            m, sdv = base[key]
            z = (m - now[key]) / max(sdv, OLD_SD_FLOOR[key])
            q = OLD_QUALITY_W * E.clamp((z - C.READY_TOLERANCE) / (C.READY_FULL - C.READY_TOLERANCE), 0, 1)
            qual = max(qual or 0.0, q)
    if dur is None and qual is None:
        return None
    return round(1 - (1 - (dur or 0.0)) * (1 - (qual or 0.0)), 2)


# ---------------------------------------------------------------- comparison
def compare(data, rid: str, days: list[str]) -> list[dict]:
    """[{day, old, new, oldSleep, newSleep, parts}] for the days with a night."""
    dm = {m.date[:10]: m for m in data.daily}
    new = C.readiness_by_day(data, rid, days)
    out = []
    for day in days:
        if day not in new or day not in dm:
            continue
        _f, parts, score = new[day]
        old_sleep = legacy_sleep(dm, date.fromisoformat(day))
        if old_sleep is None:
            continue
        old_parts = {k: v for k, v in parts.items() if k not in ("sleep", "sleepQuality")}
        old_parts["sleep"] = old_sleep
        oeff, neff = C.readiness_effects(old_parts), C.readiness_effects(parts)
        out.append({"day": day, "old": C.readiness_from(old_parts)[1], "new": score,
                    "oldSleep": oeff.get("sleep", 0.0), "newSleep": neff.get("sleep", 0.0) + neff.get("sleepQuality", 0.0),
                    "parts": parts})
    return out


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 5:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 2) if den else None


def summary(name: str, rows: list[dict], checkins=()) -> None:
    if not rows:
        print(f"{name}: bez nocí s vlastní normou (≥ 14 nocí 8–56 dní zpět)")
        return
    n = len(rows)
    mo, mn = sum(r["old"] for r in rows) / n, sum(r["new"] for r in rows) / n
    so = sum(1 for r in rows if r["oldSleep"] >= 10)
    sn = sum(1 for r in rows if r["newSleep"] >= 10)
    low_o = sum(1 for r in rows if r["old"] < 70)
    low_n = sum(1 for r in rows if r["new"] < 70)
    big = sorted(rows, key=lambda r: r["old"] - r["new"])[:3]
    print(f"{name}: {n} dní · průměr v0.10 {mo:.1f} % → v0.11 {mn:.1f} % · spánek ubral ≥ 10 bodů: {so} → {sn} dní"
          f" · pod 70 %: {low_o} → {low_n} dní")
    for r in big:
        if r["old"] != r["new"]:
            print(f"    {r['day']}: {r['old']} → {r['new']} %  (spánek −{r['oldSleep']:.0f} → −{r['newSleep']:.0f} b.)")
    by_day = {r["day"]: r for r in rows}
    ck = [c for c in checkins if (c.submitted_at or "")[:10] in by_day]
    for label, fld in (("únava z check-inu", "stress"), ("hodnocení noci", "sleep_quality")):
        pairs = [(by_day[c.submitted_at[:10]], getattr(c, fld, None)) for c in ck if getattr(c, fld, None) is not None]
        if len(pairs) >= 5:
            ro = spearman([p[0]["old"] for p in pairs], [p[1] for p in pairs])
            rn = spearman([p[0]["new"] for p in pairs], [p[1] for p in pairs])
            print(f"    ρ připravenost × {label} (n = {len(pairs)}): v0.10 {ro} · v0.11 {rn}")


def report(db, rid: str, n_days: int = 56) -> dict:
    """The comparison for one runner, as JSON (the readiness-compare endpoint)."""
    today = E.today_date()
    days = [(today - timedelta(days=k)).isoformat() for k in range(n_days - 1, -1, -1)]
    data = D.load_runner_data(db, rid)
    rows = compare(data, rid, days)
    n = len(rows)
    by_day = {r["day"]: r for r in rows}
    corr = {}
    for label, fld in (("fatigue", "stress"), ("sleepRating", "sleep_quality")):
        pairs = [(by_day[c.submitted_at[:10]], getattr(c, fld, None)) for c in data.checkins
                 if (c.submitted_at or "")[:10] in by_day and getattr(c, fld, None) is not None]
        corr[label] = {"n": len(pairs), "v010": spearman([p[0]["old"] for p in pairs], [p[1] for p in pairs]),
                       "v011": spearman([p[0]["new"] for p in pairs], [p[1] for p in pairs])}
    return {
        "days": n,
        "mean": {"v010": round(sum(r["old"] for r in rows) / n, 1) if n else None,
                 "v011": round(sum(r["new"] for r in rows) / n, 1) if n else None},
        "sleepCost10": {"v010": sum(1 for r in rows if r["oldSleep"] >= 10), "v011": sum(1 for r in rows if r["newSleep"] >= 10)},
        "below70": {"v010": sum(1 for r in rows if r["old"] < 70), "v011": sum(1 for r in rows if r["new"] < 70)},
        "checkinCorrelation": corr,
        "rows": [{k: r[k] for k in ("day", "old", "new", "oldSleep", "newSleep")} for r in rows],
    }


# ---------------------------------------------------------------- simulation
def simulate(seed: int = 7, n_days: int = 150):
    """A runner whose true state is known: three 5-day fatigue blocks lower HRV
    (−1.3 SD), raise resting HR (+1.2 SD) and cut sleep efficiency a little (−1 SD),
    while the watch adds its own noise — the deep + REM share is mostly staging error
    (SD 6 points, unrelated to the state) and now and then a night logs extra wake
    that wasn't there (Garmin's wake detection, Chinoy et al. 2021)."""
    rnd = random.Random(seed)
    start = date(2026, 5, 1)
    fatigue = set()
    for s in (70, 100, 130):
        fatigue.update(range(s, s + 5))
    daily = []
    for k in range(n_days):
        tired = k in fatigue
        hrv = math.exp(math.log(55) + rnd.gauss(0, 0.12) - (1.3 * 0.12 if tired else 0))
        rhr = 50 + rnd.gauss(0, 2.0) + (2.4 if tired else 0)
        sleep = max(4.5, rnd.gauss(7.4, 0.6) - (0.3 if tired else 0))
        eff = min(0.99, rnd.gauss(0.94, 0.015) - (0.015 if tired else 0) - (0.05 if rnd.random() < 0.07 else 0))
        share = min(0.6, max(0.2, rnd.gauss(0.42, 0.06)))
        tst = sleep * 60
        deep, rem = tst * share * 0.45, tst * share * 0.55
        daily.append(SimpleNamespace(date=(start + timedelta(days=k)).isoformat(), hrv_ms=hrv, resting_hr=rhr, sleep_h=sleep,
                                     sleep_efficiency=eff, deep_min=deep, rem_min=rem, light_min=tst - deep - rem,
                                     awake_min=tst * (1 / eff - 1), rest_high_min=None, rest_mild_min=None))
    data = D.RunnerData(rid="sim", runner=None, daily=tuple(daily),
                        priors={"rec": {"hrv_ms": None, "resting_hr": None}, "mech": {}})
    return data, start, fatigue, n_days


def run_synthetic():
    data, start, fatigue, n = simulate()
    days = [(start + timedelta(days=k)).isoformat() for k in range(60, n)]
    rows = compare(data, "sim", days)
    summary("simulace (150 dní, 3 bloky únavy po 5 dnech)", rows)
    tired = {(start + timedelta(days=k)).isoformat() for k in fatigue}
    for label, key in (("v0.10", "old"), ("v0.11", "new")):
        hit = [r for r in rows if r["day"] in tired]
        calm = [r for r in rows if r["day"] not in tired]
        det = sum(1 for r in hit if r[key] < 85) / max(1, len(hit))
        fa = sum(1 for r in calm if r[key] < 85) / max(1, len(calm))
        mh = sum(r[key] for r in hit) / max(1, len(hit))
        mc = sum(r[key] for r in calm) / max(1, len(calm))
        print(f"    {label}: dny únavy průměr {mh:.0f} %, pod 85 % {det:.0%} · klidné dny průměr {mc:.0f} %, pod 85 % {fa:.0%}")


def run_db(runner: str | None, n_days: int):
    from ..db import SessionLocal
    from .. import models
    db = SessionLocal()
    try:
        today = E.today_date()
        days = [(today - timedelta(days=k)).isoformat() for k in range(n_days - 1, -1, -1)]
        rids = [runner] if runner else [r.id for r in db.query(models.Runner).all()]
        for rid in rids:
            data = D.load_runner_data(db, rid)
            if sum(1 for m in data.daily if m.sleep_h is not None) < 20:
                continue
            summary(f"{rid} ({(data.runner.name if data.runner else '') or ''})".strip(), compare(data, rid, days), data.checkins)
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--runner")
    ap.add_argument("--days", type=int, default=56)
    a = ap.parse_args()
    run_synthetic() if a.synthetic else run_db(a.runner, a.days)
