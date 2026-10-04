"""Feedback 2026-10-04: railway#199 — hard minutes of cycling and swimming from the real
heart-rate trace (Garmin detail, Apple Health samples), not from the session average."""
from datetime import date, timedelta

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from app.metrics import stream_qc as S
from app.routers import integrations as I
from .conftest import register


def _ride_payload(hard_min=15, easy_min=45, hard=172.0, easy=125.0):
    keys = ["sumElapsedDuration", "sumDistance", "directSpeed", "directHeartRate"]
    descs = [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)]
    n = (hard_min + easy_min) * 60
    rows = [{"metrics": [float(t), t * 8.0, 8.0, hard if (t // 300) % 4 == 0 and t < hard_min * 240 else easy]}
            for t in range(n)]
    return {"metricDescriptors": descs, "activityDetailMetrics": rows}


def test_hr_histogram_counts_every_sample():
    h = S.hr_histogram(_ride_payload())
    assert sum(h.values()) > 3500 and h.get("172", 0) > 60


def test_garmin_ride_gets_its_hr_trace_and_counts_hard_minutes(client, db_session, monkeypatch):
    rid = register(client, "ride1004@test.cz", "Cyklista", "runner").json()["runner_id"]
    db = db_session
    for k in range(40, 0, -3):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"r{k}", started_at=E.day_ago(k),
                               sport="running", distance_km=8.0, duration_min=45, avg_hr=145))
    db.add(models.Activity(runner_id=rid, provider="garmin", external_id="ride", started_at=E.day_ago(1),
                           sport="cycling", duration_min=60, avg_hr=138, title="Kolo"))
    db.commit()
    monkeypatch.setattr(I.garmin_live, "fetch_details",
                        lambda g, ext: _ride_payload() if ext == "ride" else (_ for _ in ()).throw(Exception("no details")))
    I._fetch_streams(db, rid, garmin=None, cap=60)
    ride = db.query(models.Activity).filter_by(runner_id=rid, external_id="ride").first()
    st = db.query(models.ActivityStream).filter_by(activity_id=ride.id).first()
    assert st is not None and st.quality_json["hrHist"] and st.segments_json is None
    data = __import__("app.metrics.data", fromlist=["of"]).of(db, rid)
    runs = E.acts(data, rid, "load")
    hrmax, rhr = E.hr_bounds(runs, E.daily(data, rid, 180), None, None)
    ses = {s["id"]: s for s in C.run_exposures(data, rid, hrmax, rhr)}
    with_trace = ses[ride.id]["exp"]["intensity"]
    st.quality_json = {}
    db.commit()
    data = __import__("app.metrics.data", fromlist=["of"]).of(db, rid)
    without = {s["id"]: s for s in C.run_exposures(data, rid, hrmax, rhr)}[ride.id]["exp"]["intensity"]
    assert with_trace > without + 5                          # the intervals no longer vanish in the average


def test_apple_workouts_get_their_hr_trace(client, db_session):
    rid = register(client, "ride1004a@test.cz", "Apple Cyklista", "runner").json()["runner_id"]
    d = (date.today() - timedelta(days=2)).isoformat()
    samples = "\n".join(
        f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" startDate="{d} 07:{m:02d}:{s:02d} +0000" '
        f'endDate="{d} 07:{m:02d}:{s:02d} +0000" value="{170 if m < 15 else 120}"/>'
        for m in range(0, 50) for s in range(0, 60, 5))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="cs_CZ">
{samples}
 <Workout workoutActivityType="HKWorkoutActivityTypeCycling" duration="50" durationUnit="min" totalDistance="25" totalDistanceUnit="km" startDate="{d} 07:00:00 +0000" endDate="{d} 07:50:00 +0000">
   <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="135"/>
 </Workout>
</HealthData>"""
    r = client.post("/api/integrations/apple/import", files={"file": ("export.xml", xml.encode(), "application/xml")})
    assert r.status_code == 200
    ride = db_session.query(models.Activity).filter_by(runner_id=rid, sport="cycling").first()
    st = db_session.query(models.ActivityStream).filter_by(activity_id=ride.id).first()
    hist = st.quality_json["hrHist"]
    assert abs(hist["170"] - 15 * 60) < 30 and abs(hist["120"] - 35 * 60) < 60
