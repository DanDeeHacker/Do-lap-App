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


def _run_payload(minutes=20):
    keys = ["sumElapsedDuration", "sumDistance", "directElevation", "directSpeed", "directGroundContactTime"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    rows = [{"metrics": [float(s), s * 3.0, 100.0, 3.0 + (s % 5) * 0.01, 240.0]} for s in range(minutes * 60)]
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_backfill_enforces_qc_and_refreshes_stale_segments(client, db_session, monkeypatch):
    from app.metrics import segmentation as G
    rid = register(client, "sb2@test.cz", "SB2 Runner", "runner").json()["runner_id"]
    db = db_session
    for ext, day in (("short", 30), ("good", 20), ("old", 10)):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=ext,
                               started_at=E.day_ago(day), sport="running", distance_km=8.0, duration_min=45))
    db.commit()
    old = db.query(models.Activity).filter_by(runner_id=rid, external_id="old").first()
    # a row segmented by the previous (row-counting) segmenter: no segVersion
    db.add(models.ActivityStream(activity_id=old.id, runner_id=rid, external_id="old",
                                 segments_json=[{"band": "B3"}], quality_json={"nRecords": 10},
                                 surface_json={"source": "osm"}, created_at=E.now_iso()))
    db.commit()
    calls = []

    def fake_fetch(garmin, ext):
        calls.append(ext)
        return _payload(40) if ext == "short" else _run_payload()
    monkeypatch.setattr(I.garmin_live, "fetch_details", fake_fetch)

    r = I._fetch_streams(db, rid, garmin=None, cap=25)
    assert sorted(calls) == ["good", "old", "short"]            # stale row re-fetched too
    assert r["stored"] == 3 and r["rejected"] == 1 and r["remaining"] == 0 and r["have"] == 3
    short = db.query(models.Activity).filter_by(runner_id=rid, external_id="short").first()
    st = db.query(models.ActivityStream).filter_by(activity_id=short.id).first()
    assert st.segments_json is None and st.quality_json["accepted"] is False   # failed QC → never scored
    ost = db.query(models.ActivityStream).filter_by(activity_id=old.id).first()
    assert ost.quality_json["segVersion"] == G.SEG_VERSION and ost.segments_json and ost.segments_json != [{"band": "B3"}]
    assert ost.surface_json == {"source": "osm"}                # refresh keeps the surface sample
    calls.clear()
    r2 = I._fetch_streams(db, rid, garmin=None, cap=25)
    assert calls == [] and r2["remaining"] == 0                  # everything current → nothing re-fetched


def test_fetch_details_asks_for_full_resolution():
    import garmin_live

    class G:
        def __init__(self, fail_big=False):
            self.calls, self.fail_big = [], fail_big

        def get_activity_details(self, aid, maxchart=2000, maxpoly=4000):
            self.calls.append(maxchart)
            if self.fail_big and maxchart > 2000:
                raise Exception("400 bad request")
            return {"ok": maxchart}

    g = G()
    assert garmin_live.fetch_details(g, 1) == {"ok": garmin_live.FULL_RES_ROWS} and g.calls == [garmin_live.FULL_RES_ROWS]
    g2 = G(fail_big=True)                                         # refused → default resolution
    assert garmin_live.fetch_details(g2, 1) == {"ok": 2000} and g2.calls == [garmin_live.FULL_RES_ROWS, 2000]
