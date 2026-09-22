"""_fetch_streams: success stores, per-activity error tombstones (advances),
rate-limit stalls (retryable, no tombstone)."""
from app.metrics import engine as E
from app.routers import integrations as I
from app import models
from .conftest import register


def _payload(n=40):
    keys = ["sumElapsedDuration", "sumDistance", "directElevation", "directSpeed", "directGroundContactTime"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    rows = [{"metrics": [float(s), s * 3.0, 100.0, 3.0, 240.0]} for s in range(n)]
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_backfill_tombstone_and_stall(client, db_session, monkeypatch):
    rid = register(client, "sb@test.cz", "SB Runner", "runner").json()["runner_id"]
    db = db_session
    for ext, day in (("ok", 30), ("bad", 20), ("rate", 10)):  # asc order = ok, bad, rate
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=ext,
                               started_at=E.day_ago(day), sport="running", distance_km=8.0, duration_min=45))
    db.commit()

    def fake_fetch(garmin, ext):
        if ext == "ok":
            return _payload()
        if ext == "bad":
            raise Exception("no details for this activity")
        raise Exception("429 Too Many Requests")
    monkeypatch.setattr(I.garmin_live, "fetch_details", fake_fetch)

    r = I._fetch_streams(db, rid, garmin=None, cap=25)
    assert r["stored"] == 1 and r["failed"] == 1 and r["stalled"] is True
    assert r["remaining"] == 1                      # only "rate" left; batch advanced past ok+bad
    # tombstone for "bad": a stream row with no segments so it's skipped, not retried
    bad = db.query(models.Activity).filter_by(runner_id=rid, external_id="bad").first()
    ts = db.query(models.ActivityStream).filter_by(activity_id=bad.id).first()
    assert ts is not None and ts.segments_json is None and (ts.quality_json or {}).get("failed") is True

    # second run: ok+bad already have rows → only "rate" retried → still stalls, no progress-loop
    r2 = I._fetch_streams(db, rid, garmin=None, cap=25)
    assert r2["stored"] == 0 and r2["stalled"] is True and r2["remaining"] == 1
