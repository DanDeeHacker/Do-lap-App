"""Phase 3 terrain-aware load: Minetti grade-adjusted distance + downhill exposure."""
from app.metrics import terrain as T


def _flat(km):
    return [{"distance_m": i * 100, "altitude_m": 100.0} for i in range(int(km * 10) + 1)]


def _profile(steps):
    # steps: list of (segment_m, delta_alt_m)
    prof, d, a = [{"distance_m": 0, "altitude_m": 100.0}], 0, 100.0
    for seg, dz in steps:
        d += seg; a += dz
        prof.append({"distance_m": d, "altitude_m": a})
    return prof


def test_minetti_shape():
    assert abs(T.minetti_cr(0.0) - 3.6) < 0.01
    assert T.minetti_cr(-0.20) < T.minetti_cr(0.0)   # gentle downhill is cheapest region
    assert T.minetti_cr(0.15) > T.minetti_cr(0.0)    # uphill costs more
    assert T.minetti_cr(2.0) == T.minetti_cr(0.45)   # clipped at +0.45


def test_grade_adjusted_flat_equals_distance():
    ga = T.grade_adjusted_km(_flat(10.0))
    assert abs(ga - 10.0) < 0.05


def test_grade_adjusted_hilly_exceeds_distance():
    # 5 km up at +10% then 5 km down at -10% — net zero elevation, but costs more
    # flat-equivalent km than 10 raw km (uphill cost > downhill saving).
    prof = _profile([(5000, 500), (5000, -500)])
    ga = T.grade_adjusted_km(prof, fallback_km=10.0)
    assert ga > 10.0


def test_grade_adjusted_no_profile_falls_back():
    assert T.grade_adjusted_km(None, fallback_km=8.0) == 8.0
    assert T.grade_adjusted_km([], fallback_km=8.0) == 8.0


def test_downhill_exposure():
    prof = _profile([(2000, -200), (3000, 0), (1000, -20)])  # 2km @ -10%, flat, 1km @ -2%
    steep_km, weighted_km = T.downhill_exposure(prof)
    assert abs(steep_km - 2.0) < 0.01           # only the -10% km is ≤ -5%
    assert weighted_km > 0
