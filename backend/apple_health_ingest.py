"""Apple Health export → platform seed, the second real (file-based)
integration next to garmin_ingest.py. Takes the `export.zip` the iOS Health
app produces (Health → profile → Export All Health Data) — or a bare
`export.xml` — and returns the same seed dict shape build_seed() produces on
the Garmin side, so integrations._apply_seed() writes it through one code
path.

What a wrist Apple Watch export reliably carries, and what we map:
  - Running workouts        → activities (distance, duration, pace, avg HR, start time,
                              climb from HKElevationAscended; avg HR from the heart-rate
                              samples when the workout has no statistic)
  - HeartRateVariabilitySDNN→ daily_metrics.hrv_ms (the readings taken during the night first)
  - RestingHeartRate        → daily_metrics.resting_hr
  - RespiratoryRate         → daily_metrics.resp_rate (the readings taken during the night)
  - SleepAnalysis           → daily_metrics.sleep_h, stages and efficiency, the night's detail
  - StepCount               → daily_metrics.steps

The export holds every source's copy (the watch, the iPhone, other apps): steps are
de-duplicated per 15 minutes and each night comes from one source — never summed
(owner check 2026-10-04: summed nights read 13 h, steps doubled).

Running *dynamics* (vertical ratio, ground-contact time, contact balance)
aren't in this mapping: Apple exposes them only as separate high-frequency
record streams, not per-run aggregates, and contact balance isn't measured
at all. That's fine — the engine's confidence gate simply won't surface the
mechanical axis for such an account, exactly as it does for a Garmin wrist
export without a chest strap. Honest-about-missing-data, not invented.

The XML is parsed with iterparse + element.clear() so a multi-hundred-MB
export streams in constant memory instead of being built into a full tree.
"""
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

RUNNING = "HKWorkoutActivityTypeRunning"
# Cross-training workouts feed the load model only (no running mechanics).
CROSS_XML = {
    "HKWorkoutActivityTypeCycling": "cycling", "HKWorkoutActivityTypeHandCycling": "cycling",
    "HKWorkoutActivityTypeSwimming": "swimming", "HKWorkoutActivityTypeWaterFitness": "swimming",
    "HKWorkoutActivityTypeTraditionalStrengthTraining": "strength",
    "HKWorkoutActivityTypeFunctionalStrengthTraining": "strength",
}
CROSS_TITLE = {"cycling": "Kolo", "swimming": "Plavání", "strength": "Posilování"}


def cross_sport(name: str) -> str | None:
    """A Health Auto Export workout name → our cross-training sport, or None."""
    n = (name or "").lower()
    # English names plus the Czech ones a phone in Czech may export (v0.8.6)
    if "cycl" in n or "bik" in n or "cykl" in n or "kolo" in n:
        return "cycling"
    if "swim" in n or "water fitness" in n or "plav" in n:
        return "swimming"
    if "strength" in n or "posil" in n or "silov" in n:
        return "strength"
    return None


def is_run_name(name: str) -> bool:
    """A running workout by its (English or Czech) name."""
    n = (name or "").lower()
    return "run" in n or "běh" in n or "beh" in n
_FMT = "%Y-%m-%d %H:%M:%S %z"


def _date(s: str | None) -> str:
    return (s or "")[:10]


def _to_km(v, unit) -> float:
    v = float(v)
    u = (unit or "km").lower()
    if u in ("mi", "mile", "miles"):
        return v * 1.60934
    if u in ("m", "meter", "metre", "meters"):
        return v / 1000.0
    return v  # km


def _to_min(v, unit) -> float:
    v = float(v)
    u = (unit or "min").lower()
    if u.startswith("s"):
        return v / 60.0
    if u.startswith("h"):
        return v * 60.0
    return v  # min


def _duration_seconds(sd: str, ed: str) -> float:
    return (datetime.strptime(ed, _FMT) - datetime.strptime(sd, _FMT)).total_seconds()


def _open_xml(path: str):
    if path.lower().endswith(".zip") or (os.path.isfile(path) and zipfile.is_zipfile(path)):
        z = zipfile.ZipFile(path)
        name = next(
            (n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n.lower()), None
        )
        if not name:
            raise ValueError("V ZIPu chybí export.xml — nahrajte celý Apple Health export.")
        return z.open(name)
    if os.path.isdir(path):
        for cand in (os.path.join(path, "apple_health_export", "export.xml"),
                     os.path.join(path, "export.xml")):
            if os.path.exists(cand):
                return open(cand, "rb")
        raise ValueError("Ve složce nebyl nalezen export.xml.")
    return open(path, "rb")


def _num(v):
    """Health Auto Export sends some values as bare numbers and some as
    {"qty": .., "units": ..}. Return (value, units) from either."""
    if isinstance(v, dict):
        return v.get("qty", v.get("value")), v.get("units")
    return v, None


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def build_seed_from_json(payload: dict, runner_id: str, device: str = "Apple Watch") -> dict:
    """Map a Health Auto Export (HealthyApps) REST payload into the same seed
    shape build_seed() returns, so the push webhook flows through the identical
    merge pipeline as the file import. Tolerant of the format's variations:
    metric values may be bare numbers or {qty, units}; running workouts are
    matched by name; missing fields are simply skipped, never invented.

    Expected top level: {"data": {"metrics": [...], "workouts": [...]}}
    (a bare {"metrics", "workouts"} is also accepted)."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    metrics = data.get("metrics") or []
    workouts = data.get("workouts") or []

    daily: dict[str, dict] = {}

    def day(dt: str) -> dict:
        return daily.setdefault(dt, {})

    for m in metrics:
        key = _norm(m.get("name", ""))
        for pt in m.get("data") or []:
            dt = _date(pt.get("date"))
            if not dt:
                continue
            try:
                if key in ("heart_rate_variability", "heart_rate_variability_sdnn"):
                    val, _ = _num(pt.get("qty", pt))
                    if val is not None:
                        day(dt).setdefault("hrv", []).append(float(val))
                elif key == "resting_heart_rate":
                    val, _ = _num(pt.get("qty", pt))
                    if val is not None:
                        day(dt).setdefault("rhr", []).append(float(val))
                elif key == "respiratory_rate":
                    val, _ = _num(pt.get("qty", pt))
                    if val is not None and 5 <= float(val) <= 40:
                        day(dt).setdefault("resp", []).append(float(val))
                elif key == "step_count":
                    val, _ = _num(pt.get("qty", pt))
                    if val is not None:
                        d = day(dt)
                        d["steps"] = d.get("steps", 0) + int(float(val))
                elif key == "sleep_analysis":
                    # Prefer an explicit asleep total (hours); fall back to qty.
                    hours = pt.get("totalSleep")
                    if hours is None:
                        hours = pt.get("asleep")
                    if hours is None:
                        hours, _ = _num(pt.get("qty", pt))
                    if hours is not None:
                        d = day(dt)
                        d["sleep_h"] = round(d.get("sleep_h", 0.0) + float(hours), 1)
            except (TypeError, ValueError):
                pass

    activities: list[dict] = []
    for w in workouts:
        name = _norm(w.get("name", "") or w.get("workoutActivityType", ""))
        cross = None if is_run_name(name) else cross_sport(name)
        if not is_run_name(name) and not cross:
            continue
        try:
            start = w.get("start") or w.get("startDate")
            dist_v, dist_u = _num(w.get("distance"))
            dur_v, dur_u = _num(w.get("duration"))
            dist_km = _to_km(dist_v, dist_u) if dist_v else None
            # HAE workout duration is seconds unless a unit says otherwise.
            dur_min = _to_min(dur_v, dur_u or "s") if dur_v else None
            hr = w.get("heartRate") or {}
            avg_hr = hr.get("avg") if isinstance(hr, dict) else None
            if avg_hr is None:
                avg_hr = w.get("avgHeartRate")
            avg_hr = round(float(avg_hr)) if avg_hr else None
        except (TypeError, ValueError):
            continue
        if cross:
            if dur_min and dur_min >= 10:          # trivial < 10 min entries are dropped, like Garmin's
                activities.append({
                    "provider": "apple", "external_id": start, "started_at": _date(start),
                    "start_time": (start or "")[11:16] or None,
                    "title": CROSS_TITLE[cross], "sport": cross,
                    "distance_km": round(dist_km, 2) if dist_km else None,
                    "duration_min": round(dur_min, 1), "avg_hr": avg_hr,
                })
            continue
        if dist_km and dur_min and dist_km > 0:
            activities.append({
                "provider": "apple", "external_id": start,
                "started_at": _date(start), "start_time": (start or "")[11:16] or None, "title": "Běh",
                "distance_km": round(dist_km, 2), "duration_min": round(dur_min, 1),
                "pace_s_km": round(dur_min * 60 / dist_km), "avg_hr": avg_hr,
                "surface": "road", "ascent_m": None, "descent_m": None,
            })

    daily_metrics = []
    for dt, vals in sorted(daily.items()):
        row = {"date": dt, "source": "apple"}
        if vals.get("hrv"):
            row["hrv_ms"] = round(sum(vals["hrv"]) / len(vals["hrv"]), 1)
        if vals.get("rhr"):
            row["resting_hr"] = round(sum(vals["rhr"]) / len(vals["rhr"]), 1)
        if vals.get("resp"):
            row["resp_rate"] = round(sorted(vals["resp"])[len(vals["resp"]) // 2], 1)
        if vals.get("steps"):
            row["steps"] = vals["steps"]
        if vals.get("sleep_h") is not None:
            row["sleep_h"] = vals["sleep_h"]
        if len(row) > 2:
            daily_metrics.append(row)

    if not activities and not daily_metrics:
        raise ValueError("V datech nebyly nalezeny běžecké aktivity ani denní metriky.")
    activities.sort(key=lambda a: a["started_at"])

    def cov(field):
        return round(sum(1 for a in activities if a.get(field) is not None) / len(activities) * 100) if activities else 0

    return {
        "activities": activities, "daily_metrics": daily_metrics, "activity_feedback": [],
        "runners": [{"device": device}],
        "_meta": {
            "source": "apple_health_push",
            "n_activities": len(activities), "daily": len(daily_metrics),
            "first_run": activities[0]["started_at"] if activities else None,
            "last_run": activities[-1]["started_at"] if activities else None,
            "coverage_pct": {"distance_km": cov("distance_km"), "avg_hr": cov("avg_hr")},
        },
    }


DAY_RAW_DAYS = 21     # all-day heart rate, steps and the night's detail kept for the reports and dayload.py
STEP_BUCKET = 15      # minutes — steps from several sources are de-duplicated per bucket

# Sleep categories → our stages. Apple Watch (iOS 16+) writes Core / Deep / REM / Awake;
# older watches, the iPhone's bedtime and other apps write "Asleep" (unspecified) or "InBed".
SLEEP_STAGE = {
    "HKCategoryValueSleepAnalysisAsleepCore": "light", "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem", "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleep": "asleep", "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisInBed": "inbed",
}
ASLEEP = ("light", "deep", "rem", "asleep")


def _minute(ts: str | None) -> int | None:
    """'2026-10-03 07:12:00 +0200' → 432 (the local minute of the day, the export's own clock)."""
    try:
        h, m = ts[11:13], ts[14:16]
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def _local(ts: str | None) -> str:
    """'2026-10-03 07:12:00 +0200' → '2026-10-03 07:12:00' (the export's own local clock)."""
    return (ts or "")[:19]


def _union(intervals: list) -> list:
    """Merge overlapping [start, end) intervals (datetimes)."""
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _secs(intervals: list) -> float:
    return sum((b - a).total_seconds() for a, b in _union(intervals))


def _nights(sleep: list) -> dict:
    """One night per wake date from the sleep records of every source. The night is
    taken from ONE source (the export holds the watch's, the iPhone's and other apps'
    copies of the same night, and summing them doubled the hours): the source with
    sleep stages (the Apple Watch), else the one with the most sleep. Overlapping
    records of that source are merged, never added."""
    by_night: dict[str, dict[str, list]] = {}
    for src, stage, a, b in sleep:
        by_night.setdefault(b.date().isoformat(), {}).setdefault(src, []).append((stage, a, b))
    out = {}
    for d, sources in by_night.items():
        def rank(item):
            recs = item[1]
            staged = any(st in ("light", "deep", "rem") for st, _, _ in recs)
            return (staged, _secs([[a, b] for st, a, b in recs if st in ASLEEP]))
        src, recs = max(sources.items(), key=rank)
        asleep = [[a, b] for st, a, b in recs if st in ASLEEP]
        if not asleep:
            continue
        tot = _secs(asleep)
        stages = {k: round(_secs([[a, b] for st, a, b in recs if st == k]) / 60) for k in ("deep", "rem", "light", "awake")}
        staged = stages["deep"] + stages["rem"] + stages["light"] > 0
        inbed = _secs([[a, b] for st, a, b in recs if st == "inbed"])
        awake = stages["awake"] * 60.0
        eff = tot / (tot + awake) if awake > 0 else (min(1.0, tot / inbed) if inbed > tot * 0.8 else None)
        u = _union(asleep)
        out[d] = {"source": src, "start": u[0][0], "end": u[-1][1], "secs": tot, "stages": stages if staged else None,
                  "eff": eff, "recs": sorted(recs, key=lambda r: r[1])}
    return out


def _hypnogram(n: dict) -> dict:
    """The night as the morning report reads it (garmin_live.compact_sleep's shape)."""
    t0 = n["start"]
    hyp = []
    for st, a, b in n["recs"]:
        stage = {"asleep": "light"}.get(st, st)
        if stage not in ("deep", "rem", "light", "awake"):
            continue
        f, t = max(0, round((a - t0).total_seconds() / 60)), round((b - t0).total_seconds() / 60)
        if t <= f:
            continue
        if hyp and hyp[-1][2] == stage and hyp[-1][1] >= f:
            hyp[-1][1] = max(hyp[-1][1], t)
        else:
            hyp.append([f, t, stage])
    st = n["stages"] or {}
    awake_n = sum(1 for x in hyp if x[2] == "awake")
    out = {"start": n["start"].strftime("%H:%M"), "end": n["end"].strftime("%H:%M"), "sleepMin": round(n["secs"] / 60),
           "inBedMin": round((n["end"] - n["start"]).total_seconds() / 60), "awakeCount": awake_n or None}
    if n["stages"]:
        out["stages"] = {k: st.get(k, 0) for k in ("deep", "light", "rem", "awake")}
        out["hypnogram"] = hyp
    return out


def _workout_hr_pass(path: str, windows: list) -> dict:
    """Second pass over the heart-rate samples inside each workout: {key: {"avg", "hist"}},
    the average (for workouts without a heart-rate statistic: another workout app, an
    older iOS) and the seconds at each heart rate in 2-bpm bins (railway#199: hard
    minutes from the real trace, not the average). Each sample counts until the next,
    at most 10 s. `windows` = [(start_local, end_local, key)], 'YYYY-MM-DD HH:MM:SS'."""
    import bisect
    windows = sorted(windows)
    starts = [w[0] for w in windows]
    days = {w[0][:10] for w in windows} | {w[1][:10] for w in windows}
    acc: dict = {}
    src = _open_xml(path)
    try:
        for _event, el in ET.iterparse(src, events=("end",)):
            if el.tag == "Record" and el.get("type") == "HKQuantityTypeIdentifierHeartRate":
                ts = _local(el.get("startDate"))
                if ts[:10] in days:
                    i = bisect.bisect_right(starts, ts) - 1
                    if i >= 0 and ts <= windows[i][1]:
                        try:
                            acc.setdefault(windows[i][2], []).append((ts, float(el.get("value"))))
                        except (TypeError, ValueError):
                            pass
            if el.tag in ("Record", "Workout"):
                el.clear()
    finally:
        src.close()
    out = {}
    for k, xs in acc.items():
        if len(xs) < 5:
            continue
        xs.sort()
        hist: dict = {}
        for (t, v), (t2, _v2) in zip(xs, xs[1:] + [xs[-1]]):
            try:
                dt = (datetime.strptime(t2, "%Y-%m-%d %H:%M:%S") - datetime.strptime(t, "%Y-%m-%d %H:%M:%S")).total_seconds()
            except ValueError:
                dt = 5.0
            dt = min(max(dt, 0.0), 10.0) or 5.0
            b = str(int(v // 2 * 2))
            hist[b] = round(hist.get(b, 0.0) + dt, 1)
        out[k] = {"avg": round(sum(v for _t, v in xs) / len(xs)), "hist": hist}
    return out


def _elevation(el, key: str) -> float | None:
    """Workout metadata 'HKElevationAscended' = '4521 cm' → 45.2 m (Apple Watch, iOS 11.2+)."""
    for md in el.iter("MetadataEntry"):
        if md.get("key") == key:
            v = (md.get("value") or "").split()
            try:
                n = float(v[0])
            except (IndexError, ValueError):
                return None
            unit = v[1].lower() if len(v) > 1 else "m"
            return round(n / 100.0 if unit == "cm" else n * 0.3048 if unit == "ft" else n, 1)
    return None


def build_seed(path: str, runner_id: str, device: str = "Apple Watch") -> dict:
    """Export → seed. The export holds every source's copy of the same data (the Apple
    Watch, the iPhone and other apps): steps are taken per 15 minutes from the source
    that counted the most (the watch and the phone count the same steps), the night
    from one source (_nights) — never summed across sources."""
    src = _open_xml(path)
    daily: dict[str, dict] = {}
    from datetime import date as _date_cls, timedelta as _td
    raw_from = (_date_cls.today() - _td(days=DAY_RAW_DAYS)).isoformat()
    hr_raw: dict[str, list] = {}
    steps_b: dict[str, dict] = {}             # day → {(bucket, source): steps}
    hrv: list = []                            # (local datetime, value)
    resp: list = []                           # (local datetime, breaths/min) — measured during sleep
    sleep: list = []                          # (source, stage, start, end)
    activities: list[dict] = []
    no_hr: list = []                          # every workout: its heart-rate samples are read in a 2nd pass

    def day(dt: str) -> dict:
        return daily.setdefault(dt, {})

    try:
        for _event, el in ET.iterparse(src, events=("end",)):
            tag = el.tag
            if tag == "Record":
                rtype = el.get("type", "")
                sd = el.get("startDate") or ""
                try:
                    if rtype == "HKQuantityTypeIdentifierHeartRate":
                        if sd[:10] >= raw_from:
                            mm = _minute(sd)
                            if mm is not None:
                                hr_raw.setdefault(sd[:10], []).append([mm, int(round(float(el.get("value"))))])
                    elif rtype == "HKQuantityTypeIdentifierStepCount":
                        mm = _minute(sd)
                        if mm is not None:
                            k = (mm // STEP_BUCKET * STEP_BUCKET, el.get("sourceName") or "")
                            b = steps_b.setdefault(sd[:10], {})
                            b[k] = b.get(k, 0) + int(float(el.get("value")))
                    elif rtype == "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":
                        hrv.append((datetime.strptime(_local(sd), "%Y-%m-%d %H:%M:%S"), float(el.get("value"))))
                    elif rtype == "HKQuantityTypeIdentifierRestingHeartRate":
                        day(_date(sd)).setdefault("rhr", []).append(float(el.get("value")))
                    elif rtype == "HKQuantityTypeIdentifierRespiratoryRate":
                        resp.append((datetime.strptime(_local(sd), "%Y-%m-%d %H:%M:%S"), float(el.get("value"))))
                    elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                        stage = SLEEP_STAGE.get(el.get("value") or "")
                        if stage is None and "Asleep" in (el.get("value") or ""):
                            stage = "asleep"
                        if stage:
                            a = datetime.strptime(_local(sd), "%Y-%m-%d %H:%M:%S")
                            b2 = datetime.strptime(_local(el.get("endDate")), "%Y-%m-%d %H:%M:%S")
                            if b2 > a:
                                sleep.append((el.get("sourceName") or "", stage, a, b2))
                except (TypeError, ValueError):
                    pass
                el.clear()
            elif tag == "Workout":
                wtype = el.get("workoutActivityType") or ""
                cross = CROSS_XML.get(wtype)
                if cross or wtype == RUNNING:
                    dist, dist_u = el.get("totalDistance"), el.get("totalDistanceUnit")
                    avg_hr = None
                    for st in el.iter("WorkoutStatistics"):        # iOS 16+ nests them under WorkoutActivity
                        t = st.get("type", "")
                        if t == "HKQuantityTypeIdentifierDistanceWalkingRunning" and dist is None:
                            dist, dist_u = st.get("sum"), st.get("unit")
                        elif t == "HKQuantityTypeIdentifierHeartRate" and st.get("average") and avg_hr is None:
                            try:
                                avg_hr = round(float(st.get("average")))
                            except (TypeError, ValueError):
                                pass
                    try:
                        dur_min = _to_min(el.get("duration"), el.get("durationUnit")) if el.get("duration") else None
                        dist_km = _to_km(dist, dist_u) if dist else None
                    except (TypeError, ValueError):
                        dur_min = dist_km = None
                    sd = el.get("startDate") or ""
                    common = {"provider": "apple", "external_id": sd, "started_at": _date(sd),
                              "start_time": sd[11:16] or None, "duration_min": round(dur_min, 1) if dur_min else None,
                              "avg_hr": avg_hr}
                    act = None
                    if cross and dur_min and dur_min >= 10:
                        act = {**common, "title": CROSS_TITLE[cross], "sport": cross,
                               **({"distance_km": round(dist_km, 2)} if (dist_km and cross != "strength") else {})}
                    elif not cross and dist_km and dur_min and dist_km > 0:
                        act = {**common, "title": "Běh", "distance_km": round(dist_km, 2),
                               "pace_s_km": round(dur_min * 60 / dist_km), "surface": "road",
                               "ascent_m": _elevation(el, "HKElevationAscended"),
                               "descent_m": _elevation(el, "HKElevationDescended")}
                    if act:
                        activities.append(act)
                        if el.get("endDate"):
                            no_hr.append((_local(sd), _local(el.get("endDate")), sd))
                el.clear()
    finally:
        src.close()

    # the heart-rate samples inside each workout: its time at each heart rate, and the
    # average for workouts without a heart-rate statistic
    hr_hist: dict = {}
    if no_hr:
        filled = _workout_hr_pass(path, no_hr)
        for a in activities:
            f = filled.get(a["external_id"])
            if not f:
                continue
            if a.get("avg_hr") is None:
                a["avg_hr"] = f["avg"]
            if f["hist"]:
                hr_hist[a["external_id"]] = f["hist"]

    # steps: per 15 minutes the source that counted the most, summed over the day
    day_steps: dict[str, dict] = {}
    for d, b in steps_b.items():
        best: dict[int, int] = {}
        for (q, _src), n in b.items():
            best[q] = max(best.get(q, 0), n)
        day_steps[d] = best
        day(d)["steps"] = sum(best.values())

    # nights: one source, stages and efficiency from the watch
    nights = _nights(sleep)
    for d, n in nights.items():
        row = day(d)
        row["sleep_h"] = round(n["secs"] / 3600.0, 1)
        if n["stages"]:
            row.update({f"{k}_min": n["stages"][k] for k in ("deep", "rem", "light", "awake")})
        if n["eff"] is not None:
            row["sleep_efficiency"] = round(n["eff"], 3)

    # HRV: the watch measures it several times a day; the readings taken during the night
    # describe recovery like the overnight HRV of other watches, so they win when there are any
    by_day: dict[str, list] = {}
    for t, v in hrv:
        by_day.setdefault(t.date().isoformat(), []).append(v)
    for d, vs in by_day.items():
        day(d)["hrv"] = vs
    for d, n in nights.items():
        inside = [v for t, v in hrv if n["start"] <= t <= n["end"]]
        if inside:
            day(d)["hrv"] = inside
        # v0.12.0 — breathing rate while asleep (the watch measures it only during sleep)
        br = [v for t, v in resp if n["start"] <= t <= n["end"] and 5 <= v <= 40]
        if len(br) >= 3:
            day(d)["resp_rate"] = round(sorted(br)[len(br) // 2], 1)

    daily_metrics = []
    for dt, vals in sorted(daily.items()):
        row = {"date": dt, "source": "apple"}
        if vals.get("hrv"):
            row["hrv_ms"] = round(sum(vals["hrv"]) / len(vals["hrv"]), 1)
        if vals.get("rhr"):
            row["resting_hr"] = round(sum(vals["rhr"]) / len(vals["rhr"]), 1)
        for k in ("steps", "sleep_h", "deep_min", "rem_min", "light_min", "awake_min", "sleep_efficiency", "resp_rate"):
            if vals.get(k) is not None:
                row[k] = vals[k]
        if len(row) > 2:
            daily_metrics.append(row)

    if not activities and not daily_metrics:
        raise ValueError("V exportu nebyly nalezeny běžecké aktivity ani denní metriky.")
    activities.sort(key=lambda a: (a["started_at"], a.get("start_time") or ""))

    def cov(field):
        return round(sum(1 for a in activities if a.get(field) is not None) / len(activities) * 100) if activities else 0

    raw_out = {}
    for d in sorted(set(hr_raw) | {d for d in day_steps if d >= raw_from}):
        hr = sorted(hr_raw.get(d) or [])
        if len(hr) >= 10:
            raw_out[d] = {"hr": hr, "steps": sorted([m, n] for m, n in (day_steps.get(d) or {}).items())}
    sleep_out = {d: _hypnogram(n) for d, n in nights.items() if d >= raw_from}
    return {
        "activities": activities, "daily_metrics": daily_metrics, "activity_feedback": [],
        "day_raw": raw_out, "day_sleep": sleep_out, "hr_hist": hr_hist,
        "runners": [{"device": device}],
        "_meta": {
            "source": "apple_health",
            "n_activities": len(activities), "daily": len(daily_metrics),
            "first_run": activities[0]["started_at"] if activities else None,
            "last_run": activities[-1]["started_at"] if activities else None,
            "coverage_pct": {"distance_km": cov("distance_km"), "avg_hr": cov("avg_hr")},
        },
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: python apple_health_ingest.py export.zip [-o out.json]")
        sys.exit(1)
    out = build_seed(sys.argv[1], runner_id="run-0001")
    dest = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
    if dest:
        json.dump(out, open(dest, "w"), ensure_ascii=False, indent=2)
        print(f"wrote {dest}: {out['_meta']}")
    else:
        print(json.dumps(out["_meta"], ensure_ascii=False, indent=2))
