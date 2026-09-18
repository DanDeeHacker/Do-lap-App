"""Apple Health export → platform seed, the second real (file-based)
integration next to garmin_ingest.py. Takes the `export.zip` the iOS Health
app produces (Health → profile → Export All Health Data) — or a bare
`export.xml` — and returns the same seed dict shape build_seed() produces on
the Garmin side, so integrations._apply_seed() writes it through one code
path.

What a wrist Apple Watch export reliably carries, and what we map:
  - Running workouts        → activities (distance, duration, pace, avg HR)
  - HeartRateVariabilitySDNN→ daily_metrics.hrv_ms
  - RestingHeartRate        → daily_metrics.resting_hr
  - SleepAnalysis (asleep)  → daily_metrics.sleep_h
  - StepCount               → daily_metrics.steps

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
        if "run" not in name:
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
        if dist_km and dur_min and dist_km > 0:
            activities.append({
                "provider": "apple", "external_id": start,
                "started_at": _date(start), "title": "Běh",
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


def build_seed(path: str, runner_id: str, device: str = "Apple Watch") -> dict:
    src = _open_xml(path)
    daily: dict[str, dict] = {}
    sleep_secs: dict[str, float] = {}
    activities: list[dict] = []

    def day(dt: str) -> dict:
        return daily.setdefault(dt, {})

    try:
        for _event, el in ET.iterparse(src, events=("end",)):
            tag = el.tag
            if tag == "Record":
                rtype = el.get("type", "")
                try:
                    if rtype == "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":
                        day(_date(el.get("startDate"))).setdefault("hrv", []).append(float(el.get("value")))
                    elif rtype == "HKQuantityTypeIdentifierRestingHeartRate":
                        day(_date(el.get("startDate"))).setdefault("rhr", []).append(float(el.get("value")))
                    elif rtype == "HKQuantityTypeIdentifierStepCount":
                        d = day(_date(el.get("startDate")))
                        d["steps"] = d.get("steps", 0) + int(float(el.get("value")))
                    elif rtype == "HKCategoryTypeIdentifierSleepAnalysis" and "Asleep" in (el.get("value") or ""):
                        ed = el.get("endDate")
                        sleep_secs[_date(ed)] = sleep_secs.get(_date(ed), 0.0) + _duration_seconds(el.get("startDate"), ed)
                except (TypeError, ValueError):
                    pass
                el.clear()
            elif tag == "Workout":
                if el.get("workoutActivityType") == RUNNING:
                    dist, dist_u = el.get("totalDistance"), el.get("totalDistanceUnit")
                    avg_hr = None
                    for st in el.findall("WorkoutStatistics"):
                        t = st.get("type", "")
                        if t == "HKQuantityTypeIdentifierDistanceWalkingRunning" and dist is None:
                            dist, dist_u = st.get("sum"), st.get("unit")
                        elif t == "HKQuantityTypeIdentifierHeartRate" and st.get("average"):
                            try:
                                avg_hr = round(float(st.get("average")))
                            except (TypeError, ValueError):
                                pass
                    try:
                        dur_min = _to_min(el.get("duration"), el.get("durationUnit")) if el.get("duration") else None
                        dist_km = _to_km(dist, dist_u) if dist else None
                    except (TypeError, ValueError):
                        dur_min = dist_km = None
                    if dist_km and dur_min and dist_km > 0:
                        activities.append({
                            "provider": "apple", "external_id": el.get("startDate"),
                            "started_at": _date(el.get("startDate")), "title": "Běh",
                            "distance_km": round(dist_km, 2), "duration_min": round(dur_min, 1),
                            "pace_s_km": round(dur_min * 60 / dist_km), "avg_hr": avg_hr,
                            "surface": "road", "ascent_m": None, "descent_m": None,
                        })
                el.clear()
    finally:
        src.close()

    for dt, secs in sleep_secs.items():
        day(dt)["sleep_h"] = round(secs / 3600.0, 1)

    daily_metrics = []
    for dt, vals in sorted(daily.items()):
        row = {"date": dt, "source": "apple"}
        if vals.get("hrv"):
            row["hrv_ms"] = round(sum(vals["hrv"]) / len(vals["hrv"]), 1)
        if vals.get("rhr"):
            row["resting_hr"] = round(sum(vals["rhr"]) / len(vals["rhr"]), 1)
        if vals.get("steps"):
            row["steps"] = vals["steps"]
        if vals.get("sleep_h") is not None:
            row["sleep_h"] = vals["sleep_h"]
        if len(row) > 2:
            daily_metrics.append(row)

    if not activities and not daily_metrics:
        raise ValueError("V exportu nebyly nalezeny běžecké aktivity ani denní metriky.")
    activities.sort(key=lambda a: a["started_at"])

    def cov(field):
        return round(sum(1 for a in activities if a.get(field) is not None) / len(activities) * 100) if activities else 0

    return {
        "activities": activities, "daily_metrics": daily_metrics, "activity_feedback": [],
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
