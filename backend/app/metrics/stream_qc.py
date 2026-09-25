"""Stage S1 of the Per-Run Measurement Engine (Phase 4): turn a raw Garmin
activity-details payload (per-record samples) into a clean, time-ordered record
table with validity flags, then derive a compact elevation profile that Phase 3's
terrain load consumes and Phase 5's segmentation will build on.

Pure and deterministic — the network fetch lives in garmin_live.fetch_details().
The elevation profile is the guaranteed output (distance_m + altitude_m are in
metres, unambiguous). Mechanics units are normalised from the descriptor's unit
key, with a magnitude check as the fallback (_normalize_units).
"""
import math

# Garmin details metric key → engine record field (spec Table 3). Cadence has two
# keys: directDoubleCadence is steps/min (both feet); directRunCadence may be
# either, so it is only a fallback — they used to both map to cadence_spm and
# whichever descriptor came last silently won.
_KEYMAP = {
    "sumElapsedDuration": "elapsed_s", "directTimestamp": "t_ms",
    "sumDistance": "distance_m", "directSpeed": "speed_ms",
    "directElevation": "altitude_m", "directLatitude": "lat", "directLongitude": "lon",
    "directHeartRate": "hr", "directDoubleCadence": "cadence_spm",
    "directGroundContactTime": "gct_ms", "directVerticalOscillation": "vo_cm",
    "directVerticalRatio": "vratio_pct", "directStepLength": "step_len_m",
    "directGroundContactBalanceLeft": "gct_bal_pct",
}
_FALLBACK_KEYS = {"directRunCadence": "cadence_spm"}

# Unit keys Garmin puts in metricDescriptors[].unit.key → multiplier into the
# engine's unit for that field. Unknown / missing units fall back to a magnitude
# check (_UNIT_GUESS) so a mm-vs-cm-vs-m payload can't null a whole metric via the
# plausibility limits.
_UNIT_FACTORS = {
    "step_len_m": {"mm": 0.001, "millimeter": 0.001, "cm": 0.01, "centimeter": 0.01, "m": 1.0, "meter": 1.0},
    "vo_cm": {"mm": 0.1, "millimeter": 0.1, "cm": 1.0, "centimeter": 1.0, "m": 100.0, "meter": 100.0},
}
# (field, typical median in engine units) → candidate factors tried in order
_UNIT_GUESS = {
    "step_len_m": (1.0, (1.0, 0.01, 0.001)),       # ~1 m; cm ~100; mm ~1000
    "vo_cm": (8.0, (1.0, 0.1, 100.0)),             # ~8 cm; mm ~80; m ~0.08
}

# Plausibility limits (spec Table 5) — remove sensor artefacts, not normal running.
_LIMITS = {
    "hr": (40, 220), "cadence_spm": (120, 230), "gct_ms": (150, 400),
    "vo_cm": (3, 15), "step_len_m": (0.4, 2.5), "vratio_pct": (3, 20), "gct_bal_pct": (35, 65),
}
RUN_SPEED_FLOOR = 0.5        # m/s, with GCT present [Calibrate]
RUN_SPEED_FALLBACK = 1.6     # m/s, no mechanics source [Calibrate]
MIN_RUNNING_S = 600          # 10 min valid running required to score mechanics
MIN_COVERAGE = 0.80          # ≥80% timestamp coverage


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def _normalize_units(out: list[dict], units: dict) -> None:
    """Bring step length to metres, vertical oscillation to cm and cadence to
    steps/min (both feet), in place. Uses the descriptor's unit key when it is a
    known one, else picks the scale that puts the run's median closest to a
    typical value."""
    for field, (typical, cands) in _UNIT_GUESS.items():
        vals = [r[field] for r in out if r.get(field) is not None]
        if not vals:
            continue
        f = _UNIT_FACTORS[field].get((units.get(field) or "").lower())
        if f is None:
            med = abs(_median(vals)) or 1e-9
            f = min(cands, key=lambda c: abs(math.log(med * c / typical)))
        if f != 1.0:
            for r in out:
                if r.get(field) is not None:
                    r[field] = r[field] * f
    # Judge the cadence scale on RUNNING samples only (≥ 2 m/s): walking breaks in
    # a run-walk session have ~110–120 steps/min and must not trigger doubling.
    cad = [r["cadence_spm"] for r in out
           if r.get("cadence_spm") is not None and (r.get("speed_ms") or 0) >= 2.0]
    if cad and _median(cad) < 120:  # single-leg strides/min (~85) → steps/min
        for r in out:
            if r.get("cadence_spm") is not None:
                r["cadence_spm"] = r["cadence_spm"] * 2


def parse_garmin_details(details: dict) -> list[dict]:
    """Flatten Garmin's metricDescriptors + activityDetailMetrics into per-record
    dicts keyed by engine field names, in engine units."""
    descs = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []
    idx, units = {}, {}
    for keymap in (_KEYMAP, _FALLBACK_KEYS):
        for d in descs:
            k, i = d.get("key"), d.get("metricsIndex")
            if k in keymap and i is not None and keymap[k] not in idx:
                idx[keymap[k]] = i
                units[keymap[k]] = ((d.get("unit") or {}).get("key") or "") if isinstance(d.get("unit"), dict) else ""
    out = []
    for r in rows:
        m = r.get("metrics") or []
        rec = {field: m[i] for field, i in idx.items() if i < len(m) and m[i] is not None}
        out.append(rec)
    _normalize_units(out, units)
    return out


def _time_s(records: list[dict]) -> list[float]:
    """Seconds from start for each record (elapsed field preferred, else timestamp)."""
    if records and "elapsed_s" in records[0]:
        return [r.get("elapsed_s", i) for i, r in enumerate(records)]
    if records and "t_ms" in records[0]:
        t0 = records[0]["t_ms"]
        return [(r.get("t_ms", t0) - t0) / 1000.0 for r in records]
    return [float(i) for i in range(len(records))]  # assume ~1 Hz


def sample_weights(ts: list[float]) -> tuple[list[float], float, float]:
    """Seconds each record stands for, the typical sample interval, and the gap
    limit. Garmin may return ~1 Hz or a decimated stream (a few s per row), so
    durations must come from timestamps, never from counting rows. A record
    followed by a drop-out longer than the gap limit only counts one interval."""
    n = len(ts)
    if n < 2:
        return [1.0] * n, 1.0, 5.0
    dts = [ts[i + 1] - ts[i] for i in range(n - 1)]
    pos = sorted(d for d in dts if d > 0)
    step = pos[len(pos) // 2] if pos else 1.0
    gap = max(5.0, 3.0 * step)
    w = [(d if d <= gap else step) if d > 0 else 0.0 for d in dts] + [step]
    return w, step, gap


def clean_signals(records: list[dict]) -> list[dict]:
    """Null out implausible values (they're sensor artefacts) and drop position
    points whose implied speed exceeds 10 m/s."""
    ts = _time_s(records)
    prev_pos = None
    for i, r in enumerate(records):
        for f, (lo, hi) in _LIMITS.items():
            if f in r and not (lo <= r[f] <= hi):
                r[f] = None
        if "lat" in r and "lon" in r and prev_pos is not None:
            dt = max(ts[i] - prev_pos[2], 1e-6)
            # cheap degrees→metres (~111 km/deg) is enough for an artefact check
            dm = (((r["lat"] - prev_pos[0]) ** 2 + (r["lon"] - prev_pos[1]) ** 2) ** 0.5) * 111_000
            if dm / dt > 10:
                r["lat"] = r["lon"] = None
        if r.get("lat") is not None:
            prev_pos = (r["lat"], r["lon"], ts[i])
    return records


def running_mask(records: list[dict]) -> list[bool]:
    """Per-record running state: GCT present and moving, else a speed fallback —
    mirrors Garmin suppressing ground-contact metrics while walking (spec 5.2)."""
    has_mech = any(r.get("gct_ms") is not None for r in records)
    out = []
    for r in records:
        spd = r.get("speed_ms")
        if has_mech:
            out.append(r.get("gct_ms") is not None and spd is not None and spd > RUN_SPEED_FLOOR)
        else:
            out.append(spd is not None and spd >= RUN_SPEED_FALLBACK)
    return out


def elevation_profile(records: list[dict], step_m: float = 100.0) -> list[dict]:
    """Compact [{distance_m, altitude_m}] sampled ~every `step_m` (plus first/last)
    — the shape terrain.grade_adjusted_km / downhill_exposure consume."""
    pts = [(r["distance_m"], r["altitude_m"]) for r in records
           if r.get("distance_m") is not None and r.get("altitude_m") is not None]
    if len(pts) < 2:
        return []
    prof = [{"distance_m": round(pts[0][0], 1), "altitude_m": round(pts[0][1], 1)}]
    last_d = pts[0][0]
    for d, a in pts[1:]:
        if d - last_d >= step_m:
            prof.append({"distance_m": round(d, 1), "altitude_m": round(a, 1)})
            last_d = d
    if prof[-1]["distance_m"] != round(pts[-1][0], 1):
        prof.append({"distance_m": round(pts[-1][0], 1), "altitude_m": round(pts[-1][1], 1)})
    return prof


def process(details: dict) -> dict:
    """Run S1 end-to-end. Returns the elevation profile, an accept-for-mechanics
    flag and quality stats. `records` (cleaned, time-ordered) is returned for the
    later segmentation phase but not persisted here."""
    records = clean_signals(parse_garmin_details(details))
    ts = _time_s(records)
    mask = running_mask(records)
    w, step, _gap = sample_weights(ts)
    running_s = sum(wi for wi, m in zip(w, mask) if m)
    span = (ts[-1] - ts[0] + step) if len(ts) >= 2 else 0
    # Share of the recording's time actually covered by samples (drop-outs longer
    # than the gap limit are uncovered) — independent of the sample rate.
    coverage = (sum(w) / span) if span > 0 else (1.0 if records else 0.0)
    dist_m = max((r.get("distance_m") or 0) for r in records) if records else 0
    prof = elevation_profile(records)
    # Seconds spent at each heart rate (2-bpm bins) while running — lets the v3
    # intensity channel count real minutes per HR zone instead of estimating them
    # from the run's average. Bins, not zones: zones depend on HRmax / resting HR,
    # which the engine re-estimates over time.
    hr_hist = {}
    for r, wi, m in zip(records, w, mask):
        if m and r.get("hr") is not None:
            b = str(int(r["hr"] // 2 * 2))
            hr_hist[b] = hr_hist.get(b, 0.0) + wi
    hr_hist = {k: round(v, 1) for k, v in hr_hist.items()}
    accepted = running_s >= MIN_RUNNING_S and coverage >= MIN_COVERAGE
    return {
        "accepted": accepted,
        "gps": any(r.get("lat") is not None for r in records),
        "elevation_profile": prof,
        "quality": {
            "nRecords": len(records), "runningSeconds": round(running_s),
            "sampleIntervalS": round(step, 2),
            "coverage": round(min(coverage, 1.0), 3), "distanceKm": round(dist_m / 1000.0, 2),
            "hasMechanics": any(r.get("gct_ms") is not None for r in records),
            "hrHist": hr_hist or None,
        },
        "records": records,
    }
