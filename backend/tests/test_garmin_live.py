"""Direct Garmin Connect import — pure mapping of Connect API activity/daily
payloads to the platform schema, plus the endpoint wiring (login itself is
network and is monkeypatched out; the mapping and _apply_seed path are real).
"""
import garmin_live
from app.routers import integrations
from .conftest import register

SAMPLE_RUN = {
    "activityId": 123, "activityName": "Ranní běh",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-08-01 07:30:00",
    "distance": 8200, "duration": 2550, "averageHR": 152,
    "elevationGain": 60, "elevationLoss": 55,
    "averageRunningCadenceInStepsPerMinute": 170, "avgStrideLength": 118,
    "avgVerticalOscillation": 8.9, "avgVerticalRatio": 7.2,
    "avgGroundContactTime": 245, "avgGroundContactBalance": 49.5,
}


def test_map_activity_running():
    a = garmin_live.map_activity(SAMPLE_RUN)
    assert a["distance_km"] == 8.2 and a["duration_min"] == 42.5
    assert 305 <= a["pace_s_km"] <= 315
    assert a["avg_hr"] == 152 and a["cadence_spm"] == 170
    assert a["stride_len_m"] == 1.18 and a["vert_ratio_pct"] == 7.2
    assert a["gct_ms"] == 245 and a["gct_balance_l"] == 49.5
    assert a["surface"] == "road" and a["provider"] == "garmin"
    assert a["started_at"] == "2026-08-01"


def test_map_activity_running_and_cross_and_short():
    # Cross-training is now mapped (load only), not skipped — sport tagged, no mechanics.
    bike = garmin_live.map_activity({"activityType": {"typeKey": "cycling"}, "activityId": 9, "distance": 30000, "duration": 3600, "activityTrainingLoad": 90})
    assert bike is not None and bike["sport"] == "cycling" and bike.get("surface") is None
    assert bike["training_load"] == 90 and "vert_ratio_pct" not in bike
    # Trivial entries still dropped: a short run and a <10 min cross-training session.
    assert garmin_live.map_activity({"activityType": {"typeKey": "running"}, "distance": 400, "duration": 120}) is None
    assert garmin_live.map_activity({"activityType": {"typeKey": "walking"}, "distance": 300, "duration": 300}) is None


def test_map_daily():
    row = garmin_live.map_daily(
        "2026-08-01",
        {"restingHeartRate": 48, "totalSteps": 9000},
        {"dailySleepDTO": {"sleepTimeSeconds": 27000}},   # 7.5 h
        {"hrvSummary": {"lastNightAvg": 58}},
    )
    assert row["resting_hr"] == 48 and row["steps"] == 9000
    assert row["sleep_h"] == 7.5 and row["hrv_ms"] == 58
    assert garmin_live.map_daily("2026-08-02", None, None, None) is None


def test_assemble_seed_coverage():
    seed = garmin_live.assemble_seed([garmin_live.map_activity(SAMPLE_RUN)], [], "Garmin FR965")
    assert seed["_meta"]["source"] == "garmin_live"
    assert seed["_meta"]["coverage_pct"]["gct_balance_l"] == 100
    assert seed["runners"][0]["device"] == "Garmin FR965"


def _seed(*runs):
    return garmin_live.assemble_seed([garmin_live.map_activity(r) for r in runs], [], "Garmin FR965")


def _run(ext_id, day):
    a = dict(SAMPLE_RUN)
    a["activityId"] = ext_id
    a["startTimeLocal"] = f"{day} 07:30:00"
    return a


class _FakeGarmin:
    def __init__(self, mfa=False, **kwargs):
        self._mfa = mfa
        self.display_name = None
        self.loaded = False

    def login(self):
        return ("needs_mfa", {"state": 1}) if self._mfa else (None, None)

    def _load_profile_and_settings(self):
        self.loaded = True
        self.display_name = "Runner Name"


def test_begin_login_loads_profile_on_clean_login(monkeypatch):
    """Regression: with return_on_mfa=True the library returns before loading
    the profile even on a clean login — begin_login must load it, or every
    later API call 403s on a null display name."""
    import garminconnect
    monkeypatch.setattr(garminconnect, "Garmin", lambda **k: _FakeGarmin(mfa=False, **k))
    g, needs_mfa, state = garmin_live.begin_login("x@y.z", "p")
    assert needs_mfa is False
    assert g.loaded is True and g.display_name       # profile was loaded


def test_begin_login_defers_profile_until_mfa(monkeypatch):
    import garminconnect
    monkeypatch.setattr(garminconnect, "Garmin", lambda **k: _FakeGarmin(mfa=True, **k))
    g, needs_mfa, state = garmin_live.begin_login("x@y.z", "p")
    assert needs_mfa is True and g.loaded is False and state == {"state": 1}


def test_connect_endpoint_applies_seed(client, monkeypatch):
    rid = register(client, "gl@test.cz", "Garmin Live", "runner").json()["runner_id"]
    monkeypatch.setattr(integrations.garmin_live, "begin_login", lambda e, p: (object(), False, None))
    monkeypatch.setattr(integrations.garmin_live, "download_seed", lambda g, **k: _seed(SAMPLE_RUN))

    r = client.post("/api/integrations/garmin/connect", json={"email": "x@y.z", "password": "secret"})
    assert r.status_code == 200 and r.json()["added_activities"] == 1
    acts = client.get(f"/api/runners/{rid}/activities").json()
    assert acts and acts[0]["provider"] == "garmin" and acts[0]["distance_km"] == 8.2


def test_connect_requires_runner_role(client):
    register(client, "glphysio@test.cz", "GL Fyzio", "physio", "testpass123")
    r = client.post("/api/integrations/garmin/connect", json={"email": "a@b.c", "password": "p"})
    assert r.status_code == 403


def test_mfa_two_step_flow(client, monkeypatch):
    rid = register(client, "glmfa@test.cz", "GL MFA", "runner").json()["runner_id"]
    monkeypatch.setattr(integrations.garmin_live, "begin_login", lambda e, p: (object(), True, {"state": 1}))
    r1 = client.post("/api/integrations/garmin/connect", json={"email": "x@y.z", "password": "p"})
    assert r1.status_code == 200 and r1.json()["mfa_required"] is True
    token = r1.json()["mfa_token"]

    monkeypatch.setattr(integrations.garmin_live, "resume_login", lambda g, s, code: None)
    monkeypatch.setattr(integrations.garmin_live, "download_seed", lambda g, **k: _seed(SAMPLE_RUN))
    r2 = client.post("/api/integrations/garmin/connect/mfa", json={"mfa_token": token, "mfa_code": "123456"})
    assert r2.status_code == 200 and r2.json()["added_activities"] == 1


def test_mfa_bad_code_rejected(client, monkeypatch):
    register(client, "glmfa2@test.cz", "GL MFA2", "runner")
    monkeypatch.setattr(integrations.garmin_live, "begin_login", lambda e, p: (object(), True, {"state": 1}))
    token = client.post("/api/integrations/garmin/connect", json={"email": "x@y.z", "password": "p"}).json()["mfa_token"]

    def _bad(g, s, code):
        raise garmin_live.AuthError("bad code")
    monkeypatch.setattr(integrations.garmin_live, "resume_login", _bad)
    r = client.post("/api/integrations/garmin/connect/mfa", json={"mfa_token": token, "mfa_code": "000000"})
    # 400 (not 401): a wrong MFA code is a bad request, so the SPA shows the
    # error in-place instead of the global 401 handler bouncing to /auth.
    assert r.status_code == 400


def test_incremental_import_no_duplicates(client, monkeypatch):
    rid = register(client, "glinc@test.cz", "GL Inc", "runner").json()["runner_id"]
    monkeypatch.setattr(integrations.garmin_live, "begin_login", lambda e, p: (object(), False, None))
    captured = {}

    # first import: two runs
    monkeypatch.setattr(integrations.garmin_live, "download_seed",
                        lambda g, **k: _seed(_run(1, "2026-08-01"), _run(2, "2026-08-02")))
    r1 = client.post("/api/integrations/garmin/connect", json={"email": "x@y.z", "password": "p"}).json()
    assert r1["added_activities"] == 2

    # second import: one already-seen run (id 2) + one new (id 3) → only 1 added
    def _cap(g, **k):
        captured.update(k)
        return _seed(_run(2, "2026-08-02"), _run(3, "2026-08-03"))
    monkeypatch.setattr(integrations.garmin_live, "download_seed", _cap)
    r2 = client.post("/api/integrations/garmin/connect", json={"email": "x@y.z", "password": "p"}).json()
    assert r2["added_activities"] == 1

    # the download was told where our history ends (incremental fetch)
    assert captured.get("since_date", "").startswith("2026-08-02")

    acts = client.get(f"/api/runners/{rid}/activities?limit=50").json()
    assert len({a["external_id"] for a in acts}) == 3   # 3 distinct, no duplicate
