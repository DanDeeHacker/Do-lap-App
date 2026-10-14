"""v0.12.13 — the run detail's route, pace/HR series, km splits and aerobic decoupling, and the
route staying the runner's alone."""
import math

from app import models
from app.metrics import engine as E
from app.metrics import run_track as RT
from app.routers import integrations as I
from .conftest import login, register


def _recs(minutes=30, speed=3.0, hr=(140, 140), lat0=50.08, loop=True, speed_fn=None, alt_fn=None):
    """1 Hz records: an out-and-back or a loop, the heart rate drifting linearly between hr[0] and hr[1]."""
    n = minutes * 60
    out, d = [], 0.0
    for s in range(n):
        v = speed_fn(s) if speed_fn else speed
        d += v
        ang = d / 2000.0
        lat = lat0 + (0.01 * math.sin(ang) if loop else d / 111_320)
        lon = 14.42 + (0.015 * (1 - math.cos(ang)) if loop else 0.0)
        out.append({"elapsed_s": float(s), "distance_m": d, "speed_ms": v, "lat": lat, "lon": lon,
                    "hr": hr[0] + (hr[1] - hr[0]) * s / n, "altitude_m": alt_fn(s) if alt_fn else 250.0})
    return out


def test_route_is_simplified_and_needs_gps():
    straight = RT.route(_recs(minutes=10, loop=False))
    assert straight and len(straight) <= 5                          # a straight line keeps its ends
    loop = RT.route(_recs(minutes=40))
    assert 20 < len(loop) <= RT.ROUTE_MAX
    assert RT.route([{**r, "lat": None} for r in _recs(minutes=5)]) is None


def test_splits_and_series():
    recs = _recs(minutes=31, speed=3.0)                              # 5.58 km at 5:33 /km
    sp = RT.splits(recs)
    assert [s["km"] for s in sp[:5]] == [1, 2, 3, 4, 5] and all(abs(s["pace"] - 333) <= 2 for s in sp[:5])
    assert 5.4 < sp[-1]["km"] < 5.7 and sp[-1]["hr"] == 140
    se = RT.series(recs)
    assert 100 < len(se) <= RT.SERIES_MAX and abs(se[10]["pace"] - 333) <= 2 and se[-1]["km"] > 5.5


def test_decoupling_only_for_steady_long_runs():
    drift = RT.decoupling(_recs(minutes=70, hr=(140, 150)))
    assert drift and 2 < drift["pct"] < 6 and drift["minutes"] == 60
    flat = RT.decoupling(_recs(minutes=70, hr=(145, 145)))
    assert abs(flat["pct"]) < 0.5 and flat["stable"]
    assert RT.decoupling(_recs(minutes=40, hr=(140, 150))) is None                         # too short
    intervals = RT.decoupling(_recs(minutes=70, speed_fn=lambda s: 4.6 if (s // 60) % 2 else 2.4))
    assert intervals is None                                                               # not steady
    # climbing at the same heart rate is not decoupling: the speed is grade-adjusted
    hill = RT.decoupling(_recs(minutes=70, hr=(145, 145), speed_fn=lambda s: 3.0 if s < 2400 else 2.6,
                               alt_fn=lambda s: 250.0 if s < 2400 else 250.0 + (s - 2400) * 2.6 * 0.03))
    assert hill is not None and abs(hill["pct"]) < 4


def _payload(minutes=70):
    keys = ["sumElapsedDuration", "sumDistance", "directElevation", "directSpeed", "directHeartRate",
            "directLatitude", "directLongitude", "directGroundContactTime"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    rows = [{"metrics": [r["elapsed_s"], r["distance_m"], r["altitude_m"], r["speed_ms"], r["hr"], r["lat"], r["lon"], 240.0]}
            for r in _recs(minutes=minutes, hr=(140, 150))]
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_fetch_stores_route_and_track(client, db_session, monkeypatch):
    rid = register(client, "rt1@test.cz", "RT Runner", "runner").json()["runner_id"]
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="g1", started_at=E.day_ago(2),
                                   sport="running", distance_km=12.6, duration_min=70, avg_hr=145))
    db_session.commit()
    monkeypatch.setattr(I.garmin_live, "fetch_details", lambda garmin, ext: _payload())
    assert I._fetch_streams(db_session, rid, garmin=None)["stored"] == 1
    a = db_session.query(models.Activity).filter_by(runner_id=rid, external_id="g1").one()
    d = client.get(f"/api/runners/{rid}/activities/{a.id}/track").json()
    assert d["available"] and len(d["splits"]) == 13 and d["route"] and d["decoupling"]["pct"] > 2
    # the engine's snapshot never carries them
    from app.metrics import data as D
    st = D.of(db_session, rid).streams[0]
    assert not hasattr(st, "route_json") and not hasattr(st, "track_json")


def test_route_only_for_the_runner():
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    with TestClient(app) as c:
        db = SessionLocal()
        a = (db.query(models.Activity).filter(models.Activity.runner_id == "run-0001", models.Activity.sport == "running")
             .order_by(models.Activity.started_at.desc()).first())
        st = db.query(models.ActivityStream).filter_by(activity_id=a.id).first()
        if st is None:
            st = models.ActivityStream(activity_id=a.id, runner_id="run-0001", created_at=E.now_iso())
            db.add(st)
        st.route_json = [[50.08, 14.42], [50.09, 14.43]]
        st.track_json = {"v": 1, "series": [{"km": 1, "t": 300, "pace": 300, "hr": 140, "alt": 200}], "splits": None,
                         "decoupling": None}
        db.commit()
        login(c, "havlickova@fyzioholesovice.cz", expected_role="physio")
        seen = c.get(f"/api/runners/run-0001/activities/{a.id}/track").json()
        assert seen["available"] and seen["route"] is None                     # the physio sees no route
        assert c.get("/api/runners/run-0001/route-thumbs").json()["thumbs"] == {}   # nor its outline
        login(c, "adela@demo.cz")
        own = c.get(f"/api/runners/run-0001/activities/{a.id}/track").json()
        assert own["route"] == [[50.08, 14.42], [50.09, 14.43]]
        t = c.get("/api/runners/run-0001/route-thumbs").json()["thumbs"][str(a.id)]
        assert t[1::2] == [100, 0] and t[0] + t[2] == 100                 # taller than wide: centred
        db.close()


def test_thumb_is_the_shape_only():
    """v0.12.14 — a list thumbnail: at most 40 points in 0–100, north up, aspect kept, centred."""
    t = RT.thumb(RT.route(_recs(minutes=40)))
    assert len(t) <= 2 * (RT.THUMB_PTS + 1) and min(t) >= 0 and max(t) <= 100
    xs, ys = t[0::2], t[1::2]
    assert max(xs) - min(xs) == 100 or max(ys) - min(ys) == 100          # the longer side fills the box
    north = RT.thumb([[50.0, 14.0], [50.01, 14.0]])                      # a run due north: centred, bottom → top
    assert north == [50, 100, 50, 0]
    assert RT.thumb(None) is None and RT.thumb([[50.0, 14.0], [50.0, 14.0]]) is None


def test_sync_backfills_routes_of_older_runs(client, db_session, monkeypatch):
    """v0.12.14 — runs stored before the route was kept get it a few per sync, newest first."""
    rid = register(client, "rt2@test.cz", "RT Two", "runner").json()["runner_id"]
    for k in range(8):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"o{k}", started_at=E.day_ago(2 + k),
                                       sport="running", distance_km=8, duration_min=45, avg_hr=140))
    db_session.commit()
    for a in db_session.query(models.Activity).filter_by(runner_id=rid):
        db_session.add(models.ActivityStream(activity_id=a.id, runner_id=rid, created_at=E.now_iso(),
                                             quality_json={"accepted": True}))
    db_session.commit()
    monkeypatch.setattr(I.garmin_live, "fetch_details", lambda garmin, ext: _payload(minutes=30))
    assert I.fetch_tracks(db_session, rid, garmin=None) == I.TRACK_CAP
    done = {a.external_id for a, st in db_session.query(models.Activity, models.ActivityStream)
            .join(models.ActivityStream, models.ActivityStream.activity_id == models.Activity.id)
            .filter(models.Activity.runner_id == rid, models.ActivityStream.track_json.isnot(None))}
    assert done == {f"o{k}" for k in range(I.TRACK_CAP)}                  # the newest first
    assert I.fetch_tracks(db_session, rid, garmin=None) == 8 - I.TRACK_CAP
    assert I.fetch_tracks(db_session, rid, garmin=None) == 0
    thumbs = client.get(f"/api/runners/{rid}/route-thumbs").json()["thumbs"]
    assert len(thumbs) == 8
