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
    assert body["activities"] == 2                       # two runs, the bike ride is ignored
    assert body["meta"]["source"] == "apple_health"

    acts = client.get(f"/api/runners/{rid}/activities?limit=10").json()
    assert len(acts) == 2
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
