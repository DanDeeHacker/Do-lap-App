"""Phase 5: S3 segmentation + S5 segment-level drift (removes within-run averaging)."""
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
