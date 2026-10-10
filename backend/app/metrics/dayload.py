"""The day outside training, from raw all-day heart rate and steps — own logic, the
same for every device (owner request 2026-10-03: no vendor metrics such as Garmin's
stress, Body Battery or sleep score, so Coros, Apple … work the same way).

Input: heart-rate samples at the watch's own resolution ([minute of the local day,
bpm]; Garmin every 2 min, Apple per sample) and steps per interval ([minute, steps];
Garmin 15 min). Each sample covers the time to the next one (at most 5 min), so the
load is summed per sample, not from 15-minute means (the HR → load curve is convex,
means would underestimate it).

Every sample is one of:
- training: inside a recorded activity (+10 min after it, when HR is still raised by it)
- sleep: before waking / after going to bed (the watch's sleep times)
- active: ≥ ACTIVE_SPM steps per minute (≈ 300 per 15 min, walking) — load outside
  training: Banister TRIMP above ACTIVE_HRR of the heart-rate reserve, × NT_WEIGHT
  (half of training, owner's decision 2026-10-03: walking is less demanding than
  running at the same heart rate)
- still: < STILL_SPM steps per minute, awake — raised resting heart rate: HR above the
  runner's own still-awake reference (median of the previous 14 days) by ≥ MILD / HIGH
  of the heart-rate reserve. Device stress scores use daytime HRV; heart rate alone is
  coarser and also rises with caffeine, heat, digestion or illness, so it is a minor
  readiness signal.
- light: in between (pottering about) — neither load nor stress.

From the same stream: an energy reserve curve for the reports (start = the morning's
readiness, training and the day's load and raised resting HR drain it, calm awake time
recharges a little; a visualisation only, the engine uses its parts) and an own sleep
score (duration vs need, efficiency, deep + REM vs norm, regularity, awakenings).
All thresholds and weights are working assumptions of the product team."""
import math
from datetime import date, timedelta

from .. import models

ACTIVE_SPM, STILL_SPM = 20.0, 3.3          # steps per minute (≈ 300 / 50 per 15 min)
ACTIVE_HRR = 0.25                          # load counts above 25 % of the HR reserve
NT_WEIGHT = 0.5
RUN_SPM, RUN_HRR = 120.0, 0.45             # running cadence and heart rate outside a recorded activity:
                                           # an unrecorded run, counted at full weight (not as walking)
MILD, HIGH = 0.08, 0.15                    # raised resting HR: share of the HR reserve above the own reference
POST_ACTIVITY_MIN = 10
MAX_GAP_MIN = 5.0
BUCKET = 15
REF_DAYS = 14
STATE = {"sleep": 0, "calm": 1, "mild": 2, "high": 3, "light": 4, "active": 5, "training": 6}
# energy reserve (visualisation): points per load unit come from the runner's own
# typical day (a median day drains ENERGY_DAY_DRAIN); raised resting HR per minute
ENERGY_DAY_DRAIN = 40.0
ENERGY_STRESS = {"high": 0.12, "mild": 0.04}
ENERGY_CALM = 0.03


def trimp(minutes: float, hrr: float, b: float = 1.92) -> float:
    return minutes * hrr * 0.64 * math.exp(b * hrr) if hrr > 0 else 0.0


def _spm_at(steps: list, minute: float) -> float | None:
    """Steps per minute of the step interval that holds `minute` (intervals run to the next entry)."""
    if not steps:
        return None
    for i, (m, n) in enumerate(steps):
        end = steps[i + 1][0] if i + 1 < len(steps) else m + BUCKET
        if m <= minute < end:
            return n / max(1.0, end - m)
    return 0.0


def _windows(acts: list) -> list:
    """[(start, end)] minutes of the recorded activities (end + the post-activity tail)."""
    return [(a, b + POST_ACTIVITY_MIN) for a, b in acts]


def compute(raw: dict | None, acts: list, wake: float | None, bed: float | None,
            hrmax: float, rhr: float, ref: float | None, b: float = 1.92) -> dict | None:
    """One day: totals and the 15-minute timeline. `acts` = [(start, end)] minutes."""
    hr = (raw or {}).get("hr") or []
    if len(hr) < 10 or hrmax <= rhr:
        return None
    steps = (raw or {}).get("steps") or []
    wins = _windows(acts)
    wake = 6 * 60 if wake is None else wake
    bed = 23 * 60 if bed is None else bed
    still_awake = [v for m, v in hr if wake <= m < bed and (_spm_at(steps, m) or 0) < STILL_SPM
                   and not any(a <= m < e for a, e in wins)]
    own_ref = ref if ref is not None else (sorted(still_awake)[len(still_awake) * 3 // 10] if len(still_awake) >= 10 else rhr + 8)
    tot = {"nt": 0.0, "train": 0.0, "active": 0.0, "mild": 0.0, "high": 0.0, "calm": 0.0, "light": 0.0, "sleep": 0.0, "training": 0.0}
    buckets: dict[int, dict] = {}
    span = hrmax - rhr
    for i, (m, v) in enumerate(hr):
        dt = min(MAX_GAP_MIN, (hr[i + 1][0] - m) if i + 1 < len(hr) else 2.0)
        if dt <= 0:
            continue
        hrr = (v - rhr) / span
        spm = _spm_at(steps, m)
        in_act = any(a <= m < e for a, e in wins)
        load_nt = load_tr = 0.0
        if in_act:
            st = "training"
            load_tr = trimp(dt, max(0.0, hrr), b)
            tot["train"] += load_tr
        elif m < wake or m >= bed:
            st = "sleep"
        elif spm is not None and spm >= ACTIVE_SPM:
            st = "active"
            if hrr >= ACTIVE_HRR:
                w = 1.0 / NT_WEIGHT if (spm >= RUN_SPM and hrr >= RUN_HRR) else 1.0   # an unrecorded run: full weight
                load_nt = trimp(dt, hrr, b) * w
                tot["nt"] += load_nt
        elif spm is None or spm < STILL_SPM:
            e = (v - own_ref) / span
            st = "high" if e >= HIGH else "mild" if e >= MILD else "calm"
        else:
            st = "light"
        tot[st] = tot.get(st, 0.0) + dt
        k = int(m // BUCKET * BUCKET)
        bk = buckets.setdefault(k, {"hr": [], "dur": {}, "nt": 0.0, "tr": 0.0})
        bk["hr"].append(v)
        bk["dur"][st] = bk["dur"].get(st, 0.0) + dt
        bk["nt"] += load_nt
        bk["tr"] += load_tr
    order = ("training", "active", "high", "mild", "light", "calm", "sleep")
    timeline = []
    for k in sorted(buckets):
        bk = buckets[k]
        st = max(bk["dur"], key=lambda s: (bk["dur"][s], -order.index(s)))
        if "training" in bk["dur"] and bk["dur"]["training"] >= 5:
            st = "training"
        # [minute, mean HR, state, load outside training (weighted), training load]
        timeline.append([k, round(sum(bk["hr"]) / len(bk["hr"])), STATE[st], round(bk["nt"] * NT_WEIGHT, 1), round(bk["tr"], 1)])
    still_med = sorted(still_awake)[len(still_awake) // 2] if still_awake else None
    return {"ntLoad": round(tot["nt"] * NT_WEIGHT, 1), "ntRaw": round(tot["nt"], 1), "trainLoad": round(tot["train"], 1),
            "activeMin": round(tot["active"]), "mildMin": round(tot["mild"]), "highMin": round(tot["high"]),
            "calmMin": round(tot["calm"]), "lightMin": round(tot["light"]), "trainingMin": round(tot["training"]),
            "restHrMed": still_med, "restRef": round(own_ref, 1), "wake": wake, "bed": bed,
            "timeline": timeline, "steps": sum(n for _, n in steps) if steps else None}


def energy_curve(timeline: list, start: float, k: float, wake: float, until: float | None = None) -> list:
    """[(minute, energy 0–100)] from waking: training and the day's load drain k points
    per load unit, raised resting HR drains per minute, calm awake time recharges."""
    e = max(5.0, min(100.0, start))
    out = [[int(wake // BUCKET * BUCKET), round(e)]]
    for m, _hr, st, nt, tr in timeline:
        if m < wake or (until is not None and m > until):
            continue
        if st == STATE["sleep"]:
            continue
        e -= k * (nt + tr)
        if st == STATE["high"]:
            e -= ENERGY_STRESS["high"] * BUCKET
        elif st == STATE["mild"]:
            e -= ENERGY_STRESS["mild"] * BUCKET
        elif st == STATE["calm"]:
            e += ENERGY_CALM * BUCKET
        e = max(5.0, min(100.0, e))
        out.append([m + BUCKET, round(e)])
    return out


def sleep_score(hours: float | None, eff: float | None, stages: dict | None, norm: dict, bed_dev: float | None,
                awakenings: int | None) -> dict | None:
    """Own sleep score 0–100 and its parts (points earned / available)."""
    if hours is None:
        return None
    need = max(7.0, norm.get("h") or 7.5)
    parts = [("Délka", 40, min(1.0, hours / need))]
    if eff is not None:
        parts.append(("Efektivita", 20, max(0.0, min(1.0, (eff - 0.80) / 0.15))))
    st = stages or {}
    tot = sum((st.get(x) or 0) for x in ("deep", "rem", "light"))
    n_tot = sum((norm.get(x) or 0) for x in ("deep", "rem", "light"))
    if tot > 0 and n_tot > 0:
        share = ((st.get("deep") or 0) + (st.get("rem") or 0)) / tot
        n_share = ((norm.get("deep") or 0) + (norm.get("rem") or 0)) / n_tot
        parts.append(("Hluboký a REM", 20, max(0.0, min(1.0, share / max(0.05, n_share)))))
    if bed_dev is not None:
        parts.append(("Pravidelnost", 10, max(0.0, 1 - bed_dev / 90)))
    if awakenings is not None:
        parts.append(("Klidnost", 10, max(0.0, 1 - max(0, awakenings - 1) / 6)))
    avail = sum(p[1] for p in parts)
    got = sum(p[1] * p[2] for p in parts)
    return {"score": round(100 * got / avail), "parts": [{"label": l, "max": mx, "pts": round(mx * f, 1)} for l, mx, f in parts]}


# ------------------------------------------------------------------ database glue
def _hm(s: str | None) -> float | None:
    try:
        h, m = (int(x) for x in s.split(":"))
        return h * 60 + m
    except (AttributeError, ValueError):
        return None


def sleep_window(db, rid: str, d: str) -> tuple:
    """(wake, bed) minutes of day `d` from the watch's sleep: waking = the end of the
    night stored under `d`, going to bed = the start of the night stored under d + 1."""
    rows = {r.date: r for r in db.query(models.DailyDetail).filter(
        models.DailyDetail.runner_id == rid,
        models.DailyDetail.date.in_([d, (date.fromisoformat(d) + timedelta(days=1)).isoformat()])).all()}
    wake = _hm(((rows.get(d).sleep if rows.get(d) else None) or {}).get("end"))
    nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    bs = _hm(((rows.get(nxt).sleep if rows.get(nxt) else None) or {}).get("start"))
    bed = bs if (bs is not None and bs >= 18 * 60) else (1440 if bs is not None else None)
    return wake, bed


def activity_windows(db, rid: str, d: str, raw: dict | None) -> list:
    """[(start, end)] minutes of the day's recorded activities. Without a start time
    (some imports give only the date) the window is the stretch of the activity's
    length with the highest heart rate."""
    from . import engine as E
    out = []
    hr = (raw or {}).get("hr") or []
    for a in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at >= d,
                                              models.Activity.started_at < (date.fromisoformat(d) + timedelta(days=1)).isoformat()).all():
        if not E.counts_for(a, "all") or not a.duration_min:
            continue
        # the start: `start_time` (HH:MM, Garmin and Apple imports), or a full timestamp in started_at
        t = _hm(getattr(a, "start_time", None) or "") if getattr(a, "start_time", None) else None
        if t is None and len(a.started_at or "") > 11:
            t = _hm(a.started_at[11:16])
        if t is not None:
            out.append((t, t + a.duration_min))
        elif hr:
            dur = a.duration_min
            best, best_m = -1.0, None
            for m, _ in hr:
                s = sum(v for mm, v in hr if m <= mm < m + dur)
                if s > best:
                    best, best_m = s, m
            if best_m is not None:
                out.append((best_m, best_m + dur))
    return out


def hr_bounds(db, rid: str) -> tuple:
    """(HR max, resting HR) the engine uses (the stored assessment), else safe defaults."""
    row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
    cap = ((row.detail_json or {}).get("capacity") or {}) if row is not None else {}
    hx = cap.get("hrExact") or ()
    hm, hr = (hx[0], hx[1]) if len(hx) == 2 else (cap.get("hrMax"), cap.get("hrRest"))
    if not hm:
        r = db.query(models.Runner).filter(models.Runner.id == rid).first()
        hm = getattr(r, "hr_max", None) or 190
    if not hr:
        vals = sorted(m.resting_hr for m in db.query(models.DailyMetric).filter(
            models.DailyMetric.runner_id == rid, models.DailyMetric.resting_hr.isnot(None)).all())
        hr = vals[len(vals) // 2] if vals else 55
    return float(hm), float(hr)


def own_reference(db, rid: str, d: str) -> float | None:
    """The runner's still-awake HR reference: median of the previous REF_DAYS days."""
    lo = (date.fromisoformat(d) - timedelta(days=REF_DAYS)).isoformat()
    vals = sorted(m.rest_hr_med for m in db.query(models.DailyMetric).filter(
        models.DailyMetric.runner_id == rid, models.DailyMetric.date >= lo, models.DailyMetric.date < d,
        models.DailyMetric.rest_hr_med.isnot(None)).all())
    return vals[len(vals) // 2] if len(vals) >= 3 else None


def day_result(db, rid: str, d: str) -> dict | None:
    row = db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid, models.DailyDetail.date == d).first()
    raw = row.raw if row is not None else None
    if not raw:
        return None
    hm, hr = hr_bounds(db, rid)
    wake, bed = sleep_window(db, rid, d)
    return compute(raw, activity_windows(db, rid, d, raw), wake, bed, hm, hr, own_reference(db, rid, d))


def update_day(db, rid: str, d: str) -> dict | None:
    """Computes day `d` and writes its totals to the day row (the engine reads those)."""
    res = day_result(db, rid, d)
    if res is None:
        return None
    dm = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == d).first()
    if dm is None:
        dm = models.DailyMetric(runner_id=rid, date=d, source="watch")
        db.add(dm)
    dm.nt_load, dm.nt_active_min = res["ntLoad"], res["activeMin"]
    dm.rest_mild_min, dm.rest_high_min, dm.rest_hr_med = res["mildMin"], res["highMin"], res["restHrMed"]
    if dm.steps is None and res.get("steps"):
        dm.steps = res["steps"]
    return res


def store_raw(db, rid: str, d: str, raw: dict, sleep: dict | None = None) -> None:
    row = db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid, models.DailyDetail.date == d).first()
    if row is None:
        row = models.DailyDetail(runner_id=rid, date=d)
        db.add(row)
    if raw is not None:                        # a night without all-day heart rate keeps what the row has
        row.raw = raw
    if sleep:
        row.sleep = sleep
    db.flush()
