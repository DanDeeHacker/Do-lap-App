"""Apple Health import — the synthetic export.xml exercises the parser
(running workouts → activities, HRV/resting-HR/sleep/steps → daily_metrics)
end to end through the same _apply_seed path Garmin uses. A freshly
registered runner is used so the import (which replaces the runner's data)
can't disturb the shared seed the other tests assert against.
"""
from .conftest import register

EXPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="cs_CZ">
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" startDate="2026-08-01 06:00:00 +0000" endDate="2026-08-01 06:00:00 +0000" value="58"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" startDate="2026-08-01 05:00:00 +0000" endDate="2026-08-01 05:00:00 +0000" value="48"/>
 <Record type="HKQuantityTypeIdentifierStepCount" startDate="2026-08-01 09:00:00 +0000" endDate="2026-08-01 09:10:00 +0000" value="1200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2026-08-01 23:00:00 +0000" endDate="2026-08-02 06:30:00 +0000"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="42.5" durationUnit="min" totalDistance="8.2" totalDistanceUnit="km" startDate="2026-08-01 07:30:00 +0000" endDate="2026-08-01 08:12:00 +0000">
   <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="152"/>
 </Workout>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="3000" durationUnit="s" totalDistance="6.0" totalDistanceUnit="km" startDate="2026-08-03 07:00:00 +0000" endDate="2026-08-03 07:50:00 +0000"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeCycling" duration="60" durationUnit="min" totalDistance="30" totalDistanceUnit="km" startDate="2026-08-02 07:00:00 +0000" endDate="2026-08-02 08:00:00 +0000"/>
</HealthData>
"""


def _import(client, xml=EXPORT_XML, name="export.xml"):
    return client.post(
        "/api/integrations/apple/import",
        files={"file": (name, xml.encode("utf-8"), "application/xml")},
    )


def test_apple_import_parses_runs_and_daily(client):
    rid = register(client, "apple1@test.cz", "Apple Runner", "runner").json()["runner_id"]
    r = _import(client)
    assert r.status_code == 200
    body = r.json()
    assert body["activities"] == 3                       # two runs + the bike ride as cross-training
    assert body["meta"]["source"] == "apple_health"

    acts = client.get(f"/api/runners/{rid}/activities?limit=10").json()
    assert len(acts) == 3
    bike = next(a for a in acts if a["sport"] == "cycling")
    assert bike["duration_min"] == 60 and bike["pace_s_km"] is None     # load only, no running fields
    first = next(a for a in acts if a["started_at"] == "2026-08-01")
    assert first["distance_km"] == 8.2 and first["avg_hr"] == 152
    # 42.5 min over 8.2 km ≈ 311 s/km
    assert 300 <= first["pace_s_km"] <= 320

    boot = client.get(f"/api/runners/{rid}/bootstrap").json()
    days = {d["date"]: d for d in boot["daily_metrics"]}
    assert days["2026-08-01"]["hrv_ms"] == 58
    assert days["2026-08-01"]["resting_hr"] == 48
    assert days["2026-08-02"]["sleep_h"] == 7.5          # 23:00 → 06:30


def test_apple_import_rejects_empty(client):
    register(client, "apple2@test.cz", "Empty Apple", "runner")
    r = _import(client, xml='<?xml version="1.0"?><HealthData></HealthData>')
    assert r.status_code == 400


def test_apple_import_requires_runner_role(client):
    register(client, "appliephysio@test.cz", "Apple Fyzio", "physio", "testpass123")
    r = _import(client)
    assert r.status_code == 403


def _watch_export(d: str, prev: str) -> str:
    """An iPhone + Apple Watch export of one day (`d`), times on the local clock."""
    t = lambda day, hm: f"{day} {hm}:00 +0200"
    sleep = [("iPhone", "AsleepUnspecified", (prev, "22:30"), (d, "06:45"))] + [
        ("Watch", v, a, b) for v, a, b in (
            ("AsleepCore", (prev, "23:00"), (d, "01:00")), ("AsleepDeep", (d, "01:00"), (d, "02:00")),
            ("AsleepREM", (d, "02:00"), (d, "03:00")), ("Awake", (d, "03:00"), (d, "03:20")),
            ("AsleepCore", (d, "03:20"), (d, "06:30")))]
    recs = [f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="{s}" value="HKCategoryValueSleepAnalysis{v}" '
            f'startDate="{t(*a)}" endDate="{t(*b)}"/>' for s, v, a, b in sleep]
    recs += [
        f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" startDate="{t(d, "09:00")}" endDate="{t(d, "09:10")}" value="1000"/>',
        f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="{t(d, "09:02")}" endDate="{t(d, "09:12")}" value="1100"/>',
        f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="{t(d, "12:00")}" endDate="{t(d, "12:05")}" value="500"/>',
        f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Watch" startDate="{t(prev, "14:00")}" endDate="{t(prev, "14:01")}" value="40"/>',
        f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Watch" startDate="{t(d, "02:30")}" endDate="{t(d, "02:31")}" value="70"/>',
        f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Watch" startDate="{t(d, "15:00")}" endDate="{t(d, "15:01")}" value="30"/>',
    ]
    recs += [f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" startDate="{t(d, f"18:{m:02d}")}" '
             f'endDate="{t(d, f"18:{m:02d}")}" value="{140 + m // 5}"/>' for m in range(5, 30, 5)]
    recs += [f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" startDate="{t(d, f"{h:02d}:00")}" '
             f'endDate="{t(d, f"{h:02d}:00")}" value="55"/>' for h in range(8, 18)]
    work = f'''<Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="40" durationUnit="min" sourceName="Watch"
      startDate="{t(d, "07:30")}" endDate="{t(d, "08:10")}">
      <MetadataEntry key="HKElevationAscended" value="4521 cm"/>
      <WorkoutActivity uuid="x" startDate="{t(d, "07:30")}" endDate="{t(d, "08:10")}">
        <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="150" unit="count/min"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" sum="8" unit="km"/>
      </WorkoutActivity>
    </Workout>
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" totalDistance="5" totalDistanceUnit="km"
      sourceName="Another app" startDate="{t(d, "18:00")}" endDate="{t(d, "18:30")}"/>'''
    return '<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="cs_CZ">\n' + "\n".join(recs) + "\n" + work + "\n</HealthData>\n"


def test_apple_watch_export_counts_each_step_and_night_once(client, db_session):
    """iPhone + Apple Watch: the same steps and the same night come from both — taken
    once (the watch's night with its stages), never summed; the night's HRV, the start
    time, the climb and a heart rate from the samples of a workout without one."""
    from datetime import date, timedelta
    from app import models
    rid = register(client, "apple3@test.cz", "Apple Watch Runner", "runner").json()["runner_id"]
    d = (date.today() - timedelta(days=2)).isoformat()
    prev = (date.today() - timedelta(days=3)).isoformat()
    assert _import(client, xml=_watch_export(d, prev)).status_code == 200
    boot = client.get(f"/api/runners/{rid}/bootstrap").json()
    day = {x["date"][:10]: x for x in boot["daily_metrics"]}[d]
    assert day["steps"] == 1600                                       # 1 100 (one 15-min bucket, the watch) + 500
    assert day["sleep_h"] == 7.2                                      # the watch's 7 h 10 min, not + the iPhone's 8 h 15
    assert (day["deep_min"], day["rem_min"], day["light_min"], day["awake_min"]) == (60, 60, 310, 20)
    assert day["sleep_efficiency"] == round(430 / 450, 3)
    assert day["hrv_ms"] == 70                                        # the reading taken during the night
    runs = sorted((a for a in boot["activities"] if (a["sport"] or "running") == "running"), key=lambda a: a["start_time"])
    assert [r["start_time"] for r in runs] == ["07:30", "18:00"]
    assert runs[0]["avg_hr"] == 150 and runs[0]["ascent_m"] == 45.2 and runs[0]["distance_km"] == 8
    assert runs[1]["avg_hr"] == 143                                   # mean of the samples 18:05–18:25 (141–145)
    det = db_session.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid, models.DailyDetail.date == d).first()
    assert det is not None and det.sleep["start"] == "23:00" and det.sleep["stages"]["deep"] == 60
    assert det.sleep["hypnogram"][0] == [0, 120, "light"]
