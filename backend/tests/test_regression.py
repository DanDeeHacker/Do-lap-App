"""Stage S4: per-runner context regression removes the speed/gradient confound."""
from app.metrics import regression as R


def _seg(v, g, gct, t=0, surface="road"):
    band = "B1" if g <= -0.10 else "B2" if g <= -0.03 else "B3" if g < 0.03 else "B4" if g < 0.10 else "B5"
    return {"meanSpeed": v, "meanGradient": g, "elapsedS": t, "surface": surface,
            "band": band, "durationS": 60, "gct_ms": gct}


def _baseline():
    # gct truly depends on gradient: gct = 240 + 100*g (+ tiny structured noise)
    segs = []
    for i in range(60):
        v = 2.8 + (i % 5) * 0.25
        g = -0.10 + (i % 9) * 0.025
        gct = 240 + 100 * g + ((i % 3) - 1) * 1.5
        segs.append(_seg(v, g, gct, t=(i % 10) * 120))
    return segs


def test_fit_needs_enough_data():
    assert R.fit_metric([_seg(3.0, 0.0, 240) for _ in range(10)], "gct_ms") is None


def test_regression_ignores_terrain_but_catches_real_shift():
    model = R.fit_metric(_baseline(), "gct_ms")
    assert model is not None and model["sigma"] > 0
    # a hillier run that STILL follows the runner's own gct↔gradient relationship
    hilly_same = [_seg(3.0, g, 240 + 100 * g) for g in (0.05, 0.07, 0.09, 0.06, 0.08)]
    d_same = R.session_residual_drift(hilly_same, model)
    # the same hills but with a genuine +15 ms form change on top
    hilly_shift = [_seg(3.0, g, 240 + 100 * g + 15) for g in (0.05, 0.07, 0.09, 0.06, 0.08)]
    d_shift = R.session_residual_drift(hilly_shift, model)
    assert d_same and d_shift
    assert abs(d_same["di"]) < 0.8            # terrain alone → no false drift
    assert d_shift["di"] > 2.0                # real change → clear drift
    assert d_shift["di"] > abs(d_same["di"]) + 1.5


def test_out_of_domain_not_scored():
    model = R.fit_metric(_baseline(), "gct_ms")
    # gradient far outside the baseline range → not scored
    assert R.residual_z(model, _seg(3.0, 0.40, 300)) is None


def test_segment_mechanics_uses_regression(client, db_session):
    from app.metrics import engine as E
    from app import models
    from tests.conftest import register
    rid = register(client, "s4@test.cz", "S4 Runner", "runner").json()["runner_id"]
    db = db_session
    def segs(shift):
        out = []
        for i in range(8):
            g = -0.08 + i * 0.02
            out.append(_seg(3.0, g, 240 + 100 * g + shift, t=i * 60))
        return out
    aid = 0
    def add(day, shift):
        nonlocal aid; aid += 1
        a = models.Activity(runner_id=rid, provider="garmin", external_id=f"s{aid}",
                            started_at=E.day_ago(day), sport="running", distance_km=10.0, duration_min=55)
        db.add(a); db.flush()
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
               segments_json=segs(shift), created_at=E.now_iso()))
    for day in range(78, 30, -8):   # 6 baseline sessions × 8 segs = 48 ≥ 30
        add(day, shift=0)
    add(4, shift=15); add(2, shift=15)   # recent: genuine +15 ms shift
    db.commit()
    with E.engine_pinned("v2"):
        sm = E.segment_mechanics(db, rid)
    assert sm and "gct" in sm
    assert sm["gct"]["method"] == "regression"   # enough data → S4 model used
    assert sm["gct"]["z"] > 1.0                    # the real shift is caught


def test_cumdescent_covariate_used_when_present():
    # baseline WITH cumDescentM on every segment → model includes the "d" column
    segs = []
    for i in range(40):
        s = _seg(2.8 + (i % 5) * 0.2, -0.05 + (i % 7) * 0.02, 240 + i % 3)
        s["cumDescentM"] = (i % 10) * 25.0
        segs.append(s)
    m = R.fit_metric(segs, "gct_ms")
    assert m and "d" in m["cols"]
    # baseline WITHOUT cumDescentM → "d" dropped (dimension-safe for old streams)
    m2 = R.fit_metric([_seg(3.0, 0.0, 240 + i % 3) for i in range(40)], "gct_ms")
    assert m2 and "d" not in m2["cols"]
