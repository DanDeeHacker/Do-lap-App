"""Phase 4 Stage-S1: parse Garmin per-record details → clean 1 Hz table + profile."""
from app.metrics import stream_qc as S, terrain as T


def _details(n=800, climb_to=400):
    keys = ["sumElapsedDuration", "sumDistance", "directSpeed", "directElevation",
            "directLatitude", "directLongitude", "directGroundContactTime", "directHeartRate"]
    descs = [{"key": k, "metricsIndex": i, "unit": {}} for i, k in enumerate(keys)]
    rows = []
    dist = 0.0
    for s in range(n):
        dist += 3.0  # 3 m/s
        alt = 100.0 + (s if s < climb_to else (2 * climb_to - s))  # up then down
        lat = 50.08 + s * 1e-5
        rows.append({"metrics": [float(s), dist, 3.0, alt, lat, 14.42, 240.0, 150.0]})
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_parse_and_process():
    r = S.process(_details())
    assert r["accepted"] is True                    # ~13 min running, full coverage
    assert r["gps"] is True
    assert r["quality"]["hasMechanics"] is True
    assert r["quality"]["runningSeconds"] >= 600
    prof = r["elevation_profile"]
    assert len(prof) >= 5 and prof[0]["distance_m"] < prof[-1]["distance_m"]
    # profile drives Minetti terrain load: a hilly run > its flat distance
    assert T.grade_adjusted_km(prof, fallback_km=r["quality"]["distanceKm"]) > r["quality"]["distanceKm"]


def test_plausibility_nulls_bad_values():
    recs = [{"hr": 300, "gct_ms": 90, "cadence_spm": 175, "speed_ms": 3.0},
            {"hr": 150, "gct_ms": 240, "cadence_spm": 175, "speed_ms": 3.0}]
    S.clean_signals(recs)
    assert recs[0]["hr"] is None and recs[0]["gct_ms"] is None   # out of range
    assert recs[1]["hr"] == 150 and recs[1]["gct_ms"] == 240


def test_running_mask_uses_gct_then_speed():
    recs = [{"gct_ms": 240, "speed_ms": 3.0}, {"gct_ms": None, "speed_ms": 3.0}]
    assert S.running_mask(recs) == [True, False]      # mechanics present → GCT gates
    recs2 = [{"speed_ms": 2.0}, {"speed_ms": 1.0}]
    assert S.running_mask(recs2) == [True, False]     # no mechanics → speed fallback


def _long_details(minutes, step_s):
    """A steady run recorded every `step_s` seconds (Garmin decimates long
    activities when it caps the row count)."""
    keys = ["sumElapsedDuration", "sumDistance", "directSpeed", "directElevation",
            "directGroundContactTime", "directRunCadence", "directHeartRate"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    rows = []
    for s in range(0, minutes * 60, step_s):
        rows.append({"metrics": [float(s), s * 3.0, 3.0 + (s % 7) * 0.01, 300.0, 245.0, 172.0, 150.0]})
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_decimated_long_run_is_measured_in_seconds_not_rows():
    from app.metrics import segmentation as G
    for minutes, step in ((60, 2), (120, 4), (150, 5)):
        r = S.process(_long_details(minutes, step))
        assert r["accepted"] is True, (minutes, r["quality"])        # full coverage, not rows/span
        assert abs(r["quality"]["runningSeconds"] - minutes * 60) <= 2 * step
        segs = G.segment(r["records"], surface="road")
        assert segs, f"{minutes} min @ {step}s/row produced no segments"
        assert all(50 <= s["durationS"] <= 66 for s in segs[:-1])     # ~60 s by the clock
        assert abs(sum(s["durationS"] for s in segs) - minutes * 60) < 120


def test_dropout_lowers_coverage():
    d = _long_details(30, 1)
    # remove 15 minutes in the middle (watch lost signal)
    d["activityDetailMetrics"] = [r for r in d["activityDetailMetrics"] if not (600 <= r["metrics"][0] < 1500)]
    r = S.process(d)
    assert r["quality"]["coverage"] < 0.6 and r["accepted"] is False


def _mech_details(step_unit, step_vals, vo_unit, vo_vals, cad_key, cad_vals, speed=3.0):
    keys = ["sumElapsedDuration", "directSpeed", "directStepLength", "directVerticalOscillation", cad_key]
    units = [None, None, step_unit, vo_unit, None]
    descs = [{"key": k, "metricsIndex": i, **({"unit": {"key": u}} if u else {})} for i, (k, u) in enumerate(zip(keys, units))]
    rows = [{"metrics": [float(i), speed, sv, vv, cv]} for i, (sv, vv, cv) in enumerate(zip(step_vals, vo_vals, cad_vals))]
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_units_from_descriptor_and_magnitude():
    # unit keys present: step length in mm, oscillation in mm
    recs = S.parse_garmin_details(_mech_details("mm", [1100.0] * 5, "mm", [85.0] * 5, "directDoubleCadence", [172.0] * 5))
    assert abs(recs[0]["step_len_m"] - 1.1) < 1e-9 and abs(recs[0]["vo_cm"] - 8.5) < 1e-9
    # no unit keys: step length in cm, oscillation in mm → magnitude check
    recs = S.parse_garmin_details(_mech_details(None, [110.0] * 5, None, [85.0] * 5, "directDoubleCadence", [172.0] * 5))
    assert abs(recs[0]["step_len_m"] - 1.1) < 1e-9 and abs(recs[0]["vo_cm"] - 8.5) < 1e-9
    # already in engine units → unchanged
    recs = S.parse_garmin_details(_mech_details(None, [1.1] * 5, None, [8.5] * 5, "directDoubleCadence", [172.0] * 5))
    assert recs[0]["step_len_m"] == 1.1 and recs[0]["vo_cm"] == 8.5


def test_cadence_prefers_double_and_fixes_single_leg():
    d = _mech_details(None, [1.1] * 5, None, [8.5] * 5, "directRunCadence", [86.0] * 5)
    assert S.parse_garmin_details(d)[0]["cadence_spm"] == 172.0          # single-leg → steps/min
    # both keys present, single-leg listed LAST: the double cadence must win
    d = _mech_details(None, [1.1] * 5, None, [8.5] * 5, "directDoubleCadence", [172.0] * 5)
    d["metricDescriptors"].append({"key": "directRunCadence", "metricsIndex": 5})
    for r in d["activityDetailMetrics"]:
        r["metrics"].append(86.0)
    assert S.parse_garmin_details(d)[0]["cadence_spm"] == 172.0
    # walking pace (< 2 m/s) at ~115 steps/min is not mistaken for single-leg
    d = _mech_details(None, [0.7] * 5, None, [6.0] * 5, "directDoubleCadence", [115.0] * 5, speed=1.4)
    assert S.parse_garmin_details(d)[0]["cadence_spm"] == 115.0
