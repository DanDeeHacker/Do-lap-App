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
