"""Phase 5: S3 segmentation + S5 segment-level drift (removes within-run averaging)."""
import pytest
from app.metrics import segmentation as G, engine as E
from app import models
from .conftest import register


def _stream(down_gct=240.0, n_flat=90, n_down=90):
    recs, dist, alt = [], 0.0, 100.0
    for s in range(n_flat):          # flat, road, gct 240
        dist += 3.0
        recs.append({"elapsed_s": float(s), "distance_m": dist, "altitude_m": alt,
                     "speed_ms": 3.0, "gct_ms": 240.0, "cadence_spm": 172.0})
    for s in range(n_down):          # steep downhill, gct = down_gct
        dist += 3.0
        alt -= 0.4                    # -0.4 m / 3 m ≈ -13% → band B1
        recs.append({"elapsed_s": float(n_flat + s), "distance_m": dist, "altitude_m": alt,
                     "speed_ms": 3.0, "gct_ms": down_gct, "cadence_spm": 172.0})
    return recs


def test_segment_splits_by_band():
    segs = G.segment(_stream(), surface="road")
    bands = {s["band"] for s in segs}
    assert "B3" in bands and "B1" in bands       # a level and a steep-downhill segment
    assert all(s["steady"] for s in segs)         # constant speed → steady


def test_session_drift_isolates_downhill():
    base = []
    for _ in range(8):                            # baseline: gct 240 everywhere
        base += G.segment(_stream(down_gct=240.0), surface="road")
    stats = G.baseline_stats(base)
    # recent run: only the DOWNHILL gct drifts up; flat unchanged.
    recent = G.segment(_stream(down_gct=268.0), surface="road")
    d = G.session_drift(recent, stats, "gct_ms")
    assert d is not None
    assert d["byBand"]["down"] > 1.0              # downhill clearly elevated
    assert abs(d["byBand"].get("level", 0)) < 0.5  # flat essentially unchanged
    # a per-run average would sit between the two → the downhill signal is diluted;
    # the segment DI still surfaces it.
    assert d["di"] > 0.3


def test_segment_mechanics_endtoend(client, db_session):
    rid = register(client, "seg@test.cz", "Seg Runner", "runner").json()["runner_id"]
    db = db_session
    flat_seg = {"band": "B3", "surface": "road", "durationS": 60, "gct_ms": 240.0}
    down_base = {"band": "B1", "surface": "road", "durationS": 60, "gct_ms": 240.0}
    down_drift = {"band": "B1", "surface": "road", "durationS": 60, "gct_ms": 270.0}
    aid = 0
    def add(day, drift):
        nonlocal aid
        aid += 1
        a = models.Activity(runner_id=rid, provider="garmin", external_id=f"x{aid}",
                            started_at=E.day_ago(day), sport="running", distance_km=10.0, duration_min=55)
        db.add(a); db.flush()
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
               segments_json=[dict(flat_seg), dict(down_drift if drift else down_base)],
               created_at=E.now_iso()))
    for day in range(75, 30, -6):   # ~8 baseline sessions
        add(day, drift=False)
    add(5, drift=True); add(2, drift=True)   # recent: downhill drift
    db.commit()
    with E.engine_pinned("v2"):
        sm = E.segment_mechanics(db, rid)
    assert sm and "gct" in sm
    assert sm["gct"]["z"] > 0.5
    assert sm["gct"]["byBand"]["down"] > sm["gct"]["byBand"].get("level", 0)


def test_segment_significance(client, db_session):
    import random
    from app.metrics import engine as E
    from app import models
    from tests.conftest import register
    random.seed(3)
    rid = register(client, "sig@test.cz", "Sig Runner", "runner").json()["runner_id"]
    db = db_session
    def s(band, gct):
        return {"band": band, "surface": "road", "durationS": 60, "meanSpeed": 3.0,
                "meanGradient": -0.12 if band == "B1" else 0.0, "elapsedS": 0, "gct_ms": gct}
    aid = 0
    def add(day, segs):
        nonlocal aid; aid += 1
        a = models.Activity(runner_id=rid, provider="garmin", external_id=f"z{aid}",
                            started_at=E.day_ago(day), sport="running", distance_km=10.0, duration_min=55)
        db.add(a); db.flush()
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
               segments_json=segs, created_at=E.now_iso()))
    for day in range(78, 30, -6):   # baseline: flat gct ~240±5, downhill ~232±5
        add(day, [s("B3", 240 + random.gauss(0, 5)), s("B1", 232 + random.gauss(0, 5))])
    add(3, [s("B3", 241), s("B1", 262)])   # recent: downhill gct clearly elevated
    db.commit()
    res = E.segment_significance(db, rid, n_runs=1)
    run = res["runs"][0]
    downhill = next(sg for sg in run["segments"] if sg["band"] == "B1")
    gct = next(f for f in downhill["findings"] if f["metric"] == "gct_ms")
    assert gct["sig"] is True and gct["p"] < 0.05 and gct["z"] > 1.96 and gct["dir"] == "up"
    flat = next(sg for sg in run["segments"] if sg["band"] == "B3")
    assert not any(f["sig"] for f in flat["findings"])   # flat segment is normal
    assert run["sigCount"] >= 1


def test_significance_uses_context_model_not_raw_buckets(client, db_session):
    """A faster run's segments have shorter ground contact simply because they
    are faster. With enough baseline segments the test compares each segment
    with the runner's own speed/gradient model, so a tempo run is NOT flagged —
    but a genuine +20 ms change at the same speed is."""
    import random
    random.seed(4)
    rid = register(client, "sigreg@test.cz", "Sig Reg", "runner").json()["runner_id"]
    db = db_session

    def s(v, gct):
        return {"band": "B3", "surface": "road", "durationS": 60, "meanSpeed": v, "meanGradient": 0.0,
                "elapsedS": 0, "gct_ms": gct}
    aid = 0

    def add(day, segs):
        nonlocal aid
        aid += 1
        a = models.Activity(runner_id=rid, provider="garmin", external_id=f"sr{aid}",
                            started_at=E.day_ago(day), sport="running", distance_km=10.0, duration_min=55)
        db.add(a)
        db.flush()
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
                                     segments_json=segs, created_at=E.now_iso()))
    for day in range(80, 30, -5):   # 10 baseline runs × 8 segments, speeds 2.6–3.5 m/s
        add(day, [s(2.6 + 0.12 * i, 360 - 40 * (2.6 + 0.12 * i) + random.gauss(0, 3)) for i in range(8)])
    add(4, [s(3.45, 360 - 40 * 3.45 + random.gauss(0, 1)) for _ in range(6)])   # tempo, form unchanged
    add(2, [s(3.0, 360 - 40 * 3.0 + 20) for _ in range(6)])                     # same speed, +20 ms
    db.commit()
    res = E.segment_significance(db, rid, n_runs=2)
    assert res["method"] == "regression"
    shifted, tempo = res["runs"]           # newest first
    assert tempo["sigCount"] == 0, "a faster run must not look like a form change"
    assert shifted["sigCount"] == 6
    assert all(f["method"] == "regression" for sg in tempo["segments"] for f in sg["findings"])


def test_small_baseline_uses_t_prediction_interval():
    """n = 5 baseline segments: a value 2.5 SD out is NOT significant once the
    t distribution (df 4) and the prediction interval are used — the old normal
    z-test called it significant, and fired ~23 % of the time on pure noise."""
    t = 2.5 / (1 + 1 / 5) ** 0.5
    assert E.t_two_sided_p(t, 4) > 0.05
    assert E.t_two_sided_p(2.776, 4) == pytest.approx(0.05, abs=1e-3)


def test_small_baseline_false_positive_rate_is_nominal():
    import random
    rng = random.Random(8)
    hits, n_trials = 0, 4000
    for _ in range(n_trials):
        base = [rng.gauss(0, 1) for _ in range(5)]
        m, s, n = E.inlier_mean_sd(base)
        t = (rng.gauss(0, 1) - m) / (s * (1 + 1 / n) ** 0.5)
        hits += E.t_two_sided_p(t, n - 1) < 0.05
    assert hits / n_trials < 0.075      # ≈ 5 % (was ~23 % with median/MAD + normal p)


def _sessions(rng, n_sess, between, within, tag, shift=0.0):
    rows = []
    for i in range(n_sess):
        day = rng.gauss(0, between) + shift
        segs = [{"band": "B3", "surface": "road", "durationS": 60, "gct_ms": 240 + day + rng.gauss(0, within)}
                for _ in range(30)]
        rows.append({"aid": f"{tag}-{i}", "created": tag, "surface": "road", "started": "", "segs": segs})
    return rows


def test_segment_session_drift_is_in_session_units():
    """No real change: the standardised session DI has SD ≈ 1 whatever the
    runner's split between day-to-day and within-run noise. The raw DI (a mean
    of segment z-scores) did not — for a runner whose noise is mostly within the
    run its SD was ~0.2, so EWMA thresholds tuned for session units never fired."""
    import random
    for between, within in ((6.0, 10.0), (2.0, 10.0), (8.0, 3.0)):
        std_sds, raw_sds = [], []
        for seed in range(10):      # average over baselines: one 14-session baseline is itself noisy
            rng = random.Random(100 + seed)
            tag = f"t{seed}-{between}-{within}"
            base = _sessions(rng, 14, between, within, tag)
            stats = G.baseline_stats([s for r in base for s in r["segs"]])
            new = _sessions(rng, 120, between, within, tag + "n")
            res = [E._seg_session(r["segs"], base, stats, "gct_ms", "bucket") for r in new]
            std_sds.append(E.sd([x["di"] for x in res]))
            raw_sds.append(E.sd([x["rawDi"] for x in res]))
        assert 0.8 < E.mean(std_sds) < 1.25, (between, within, E.mean(std_sds))
        if between == 2.0:
            assert E.mean(raw_sds) < 0.45   # the unstandardised DI was far too small here


def test_segment_scoring_needs_enough_baseline_sessions():
    import random
    rng = random.Random(22)
    base = _sessions(rng, 3, 3.0, 5.0, "few")          # 90 segments but only 3 sessions
    stats = G.baseline_stats([s for r in base for s in r["segs"]])
    assert E._seg_session(base[0]["segs"], base, stats, "gct_ms", "bucket") is None


def _noisy_stream(grade, minutes=20, noise_m=0.3, seed=5):
    import random
    rng = random.Random(seed)
    recs, dist = [], 0.0
    for s in range(minutes * 60):
        dist += 3.0
        recs.append({"elapsed_s": float(s), "distance_m": dist,
                     "altitude_m": 200 + grade * dist + rng.gauss(0, noise_m),
                     "speed_ms": 3.0 + rng.gauss(0, 0.05), "gct_ms": 245.0, "cadence_spm": 172.0})
    return recs


def test_band_flicker_near_edge_does_not_drop_the_run():
    """A steady ~3 % climb (right on the B3/B4 edge) with barometric jitter:
    band persistence keeps it in long segments instead of chopping it into
    sub-20 s pieces that get thrown away."""
    recs = _noisy_stream(0.029)
    segs = G.segment(recs, surface="road")
    covered = sum(s["durationS"] for s in segs)
    assert covered >= 0.8 * 20 * 60, covered
    raw_bands = [G._band(g) for g in G._gradients(recs)]
    flips = sum(1 for a, b in zip(raw_bands, raw_bands[1:]) if a != b)
    assert flips > 20      # the raw per-record band really does flicker here


def test_cumulative_descent_ignores_altitude_jitter():
    flat = G.segment(_noisy_stream(0.0, minutes=30), surface="road")
    assert flat[-1]["cumDescentM"] < 10          # naive summing gave hundreds of metres
    down = G.segment(_noisy_stream(-0.04, minutes=10, noise_m=0.2), surface="road")
    true_drop = 0.04 * 3.0 * 10 * 60              # 72 m of real descent
    assert abs(down[-1]["cumDescentM"] - true_drop * (down[-1]["elapsedS"] / 600)) < 8


def test_segments_follow_the_activity_surface(client, db_session):
    """Segments are cut at fetch time with the surface known then; a later
    surface refinement on the activity must reach segment scoring."""
    rid = register(client, "segsurf@test.cz", "Seg Surf", "runner").json()["runner_id"]
    db = db_session
    a = models.Activity(runner_id=rid, provider="garmin", external_id="ss1", started_at=E.day_ago(3),
                        sport="running", distance_km=10.0, duration_min=55, surface="trail")
    db.add(a)
    db.flush()
    db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id="ss1", created_at=E.now_iso(),
                                 segments_json=[{"band": "B3", "surface": "road", "durationS": 60, "gct_ms": 250.0}]))
    db.commit()
    rows = E._stream_rows(db, rid)
    assert rows[0]["segs"][0]["surface"] == "trail"


def test_notable_run_rate_with_no_change():
    """With no real change, a run should rarely be marked notable on one metric
    (the thresholds are set for 6 metrics × 3 bands of looks per run)."""
    import random
    rng = random.Random(33)
    base = _sessions(rng, 14, 4.0, 8.0, "notable")
    stats = G.baseline_stats([s for r in base for s in r["segs"]])
    new = _sessions(rng, 400, 4.0, 8.0, "notable-n")
    hits = 0
    for r in new:
        d = E._seg_session(r["segs"], base, stats, "gct_ms", "bucket")
        hits += abs(d["di"]) >= E._NOTABLE_DI or any(abs(z) >= E._NOTABLE_BAND for z in d["byBand"].values())
    assert hits / len(new) < 0.04
