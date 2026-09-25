"""Phase 3 terrain-aware load: Minetti grade-adjusted distance + downhill exposure."""
from app.metrics import engine as E, terrain as T


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


def test_load_km_counts_steep_downhill_more_not_less():
    """Minetti's metabolic cost makes a −15 % descent cheaper than flat, but it is
    the most eccentric/impact-heavy running — the terrain-load km must count it
    MORE than its flat distance (Gottschall & Kram 2005)."""
    down = [{"distance_m": d, "altitude_m": 500 - 0.15 * d} for d in range(0, 5001, 100)]
    flat = [{"distance_m": d, "altitude_m": 500} for d in range(0, 5001, 100)]
    up = [{"distance_m": d, "altitude_m": 500 + 0.10 * d} for d in range(0, 5001, 100)]
    assert T.grade_adjusted_km(down, 5.0) < 5.0            # metabolic: cheaper
    assert T.load_km(down) > 1.3 * 5.0                      # load: heavier
    assert abs(T.load_km(flat) - 5.0) < 1e-6
    assert T.load_km(up) > 5.0
    assert T.load_km(None) is None and T.load_km([]) is None  # no profile → not comparable


def test_v2_terrain_spike_only_compares_runs_with_profiles(client, db_session):
    """A run with a profile must not be compared against profile-less runs (raw
    km) — and a steep downhill run raises the terrain component."""
    from app import models
    from .conftest import register
    rid = register(client, "tspike@test.cz", "T Spike", "runner").json()["runner_id"]
    db = db_session
    flat = [{"distance_m": d, "altitude_m": 300} for d in range(0, 10001, 100)]
    steep_down = [{"distance_m": d, "altitude_m": 1500 - 0.15 * d} for d in range(0, 10001, 100)]
    for d, prof in ((20, flat), (15, flat), (10, flat), (2, steep_down)):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"ts{d}", started_at=E.day_ago(d),
                               sport="running", distance_km=10.0, duration_min=55, avg_hr=140,
                               elevation_profile=prof))
    db.commit()
    with E.engine_pinned("v2"):
        L = E.load(db, rid)
    assert L["sessionSpike"] > 1.3 and "terén" in L["sessionSpikeBasis"]
    # same history but the older runs have NO profile → terrain part not compared
    rid2 = register(client, "tspike2@test.cz", "T Spike2", "runner").json()["runner_id"]
    for d, prof in ((20, None), (15, None), (10, None), (2, steep_down)):
        db.add(models.Activity(runner_id=rid2, provider="garmin", external_id=f"tt{d}", started_at=E.day_ago(d),
                               sport="running", distance_km=10.0, duration_min=55, avg_hr=140,
                               elevation_profile=prof))
    db.commit()
    with E.engine_pinned("v2"):
        L2 = E.load(db, rid2)
    assert L2["sessionSpike"] < 1.1 and "terén" not in (L2["sessionSpikeBasis"] or "")
