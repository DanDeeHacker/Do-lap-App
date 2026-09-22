"""Stage S1 of the Per-Run Measurement Engine (Phase 4): turn a raw Garmin
activity-details payload (per-record samples) into a clean, time-ordered record
table with validity flags, then derive a compact elevation profile that Phase 3's
terrain load consumes and Phase 5's segmentation will build on.

Pure and deterministic — the network fetch lives in garmin_live.fetch_details().
The elevation profile is the guaranteed output (distance_m + altitude_m are in
metres, unambiguous). Mechanics units from the details API are marked [Verify]
and should be checked against a real payload before being scored per-second.
"""

# Garmin details metric key → engine record field (spec Table 3). [Verify] units.
_KEYMAP = {
    "sumElapsedDuration": "elapsed_s", "directTimestamp": "t_ms",
    "sumDistance": "distance_m", "directSpeed": "speed_ms",
    "directElevation": "altitude_m", "directLatitude": "lat", "directLongitude": "lon",
    "directHeartRate": "hr", "directRunCadence": "cadence_spm", "directDoubleCadence": "cadence_spm",
    "directGroundContactTime": "gct_ms", "directVerticalOscillation": "vo_cm",
    "directVerticalRatio": "vratio_pct", "directStepLength": "step_len_m",
    "directGroundContactBalanceLeft": "gct_bal_pct",
}

# Plausibility limits (spec Table 5) — remove sensor artefacts, not normal running.
_LIMITS = {
    "hr": (40, 220), "cadence_spm": (120, 230), "gct_ms": (150, 400),
    "vo_cm": (3, 15), "step_len_m": (0.4, 2.5),
}
RUN_SPEED_FLOOR = 0.5        # m/s, with GCT present [Calibrate]
RUN_SPEED_FALLBACK = 1.6     # m/s, no mechanics source [Calibrate]
MIN_RUNNING_S = 600          # 10 min valid running required to score mechanics
MIN_COVERAGE = 0.80          # ≥80% timestamp coverage


def parse_garmin_details(details: dict) -> list[dict]:
    """Flatten Garmin's metricDescriptors + activityDetailMetrics into per-record
    dicts keyed by engine field names."""
    descs = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []
    idx = {}
    for d in descs:
        k, i = d.get("key"), d.get("metricsIndex")
        if k in _KEYMAP and i is not None:
            idx[_KEYMAP[k]] = i
    out = []
    for r in rows:
        m = r.get("metrics") or []
        rec = {field: m[i] for field, i in idx.items() if i < len(m) and m[i] is not None}
        out.append(rec)
    return out


def _time_s(records: list[dict]) -> list[float]:
    """Seconds from start for each record (elapsed field preferred, else timestamp)."""
    if records and "elapsed_s" in records[0]:
        return [r.get("elapsed_s", i) for i, r in enumerate(records)]
    if records and "t_ms" in records[0]:
        t0 = records[0]["t_ms"]
        return [(r.get("t_ms", t0) - t0) / 1000.0 for r in records]
    return [float(i) for i in range(len(records))]  # assume ~1 Hz


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
    running_s = sum(1 for m in mask if m)  # ~1 Hz → seconds
    span = (ts[-1] - ts[0]) if len(ts) >= 2 else 0
    coverage = (len(records) / span) if span > 0 else (1.0 if records else 0.0)
    dist_m = max((r.get("distance_m") or 0) for r in records) if records else 0
    prof = elevation_profile(records)
    accepted = running_s >= MIN_RUNNING_S and coverage >= MIN_COVERAGE
    return {
        "accepted": accepted,
        "gps": any(r.get("lat") is not None for r in records),
        "elevation_profile": prof,
        "quality": {
            "nRecords": len(records), "runningSeconds": running_s,
            "coverage": round(min(coverage, 1.0), 3), "distanceKm": round(dist_m / 1000.0, 2),
            "hasMechanics": any(r.get("gct_ms") is not None for r in records),
        },
        "records": records,
    }
