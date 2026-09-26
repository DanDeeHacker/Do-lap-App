"""Engine history replay: the quadrant/mech trend endpoints must (a) end on
today's live score, (b) replay self-report so the symptom axis shows in history
(previously it was silently dropped, so a painful day rendered green), and
(c) be cached — invalidated on a data change so a new check-in shows up.
"""
from app import models
from app.metrics import engine as E
from .conftest import login

RUNNER_EMAIL = "adela@demo.cz"


def _rid(client):
    r = login(client, RUNNER_EMAIL)
    assert r.status_code == 200
    return r.json()["runner_id"]


def test_quadrant_history_ends_today_and_matches_live(client):
    rid = _rid(client)
    hist = client.get(f"/api/runners/{rid}/quadrant-history").json()
    assert hist, "expected a non-empty quadrant history"
    today = E.iso_date(E.today_date())
    assert hist[-1]["date"] == today  # the strip ends on today
    for k in ("quadrant", "overall", "tier", "mech", "load", "symp", "signals", "rcv", "readiness", "painRecurring"):
        assert k in hist[-1]
    # the Dnes overview in the history (railway#88) draws recovery and the drivers' values
    live_rcv = client.get(f"/api/runners/{rid}/assessment").json().get("rcv") or {}
    assert hist[-1]["rcv"] == live_rcv.get("score")
    assert all({"id", "name", "pts", "grade", "val"} <= set(s) for s in hist[-1]["signals"])

    # The pinned last point is computed from the same data as the live assessment,
    # so the axis scores must line up (this is what makes the trend end coherent).
    live = client.get(f"/api/runners/{rid}/assessment").json()
    for axis in ("mech", "load", "symp", "overall"):
        assert hist[-1][axis] == live[axis], f"{axis} history-end != live"


def test_symptom_axis_is_replayed_and_cache_invalidates(client, db_session):
    rid = _rid(client)
    before = client.get(f"/api/runners/{rid}/quadrant-history").json()
    assert before[-1]["date"] == E.iso_date(E.today_date())

    # A fresh, painful check-in today must (1) invalidate the cached history and
    # (2) show up on the symptom axis of today's replayed point — proof the
    # self-report is actually replayed, not dropped as it used to be.
    r = client.post(f"/api/runners/{rid}/checkins", json={"pain_score": 6, "pain_site": "koleno"})
    assert r.status_code == 200

    after = client.get(f"/api/runners/{rid}/quadrant-history").json()
    assert after[-1]["date"] == E.iso_date(E.today_date())
    assert after[-1]["symp"] > 0
    assert after[-1]["symp"] >= before[-1]["symp"]

    # The cache row exists and is stamped for today after the read.
    row = (
        db_session.query(models.EngineHistoryCache)
        .filter(models.EngineHistoryCache.runner_id == rid, models.EngineHistoryCache.kind == "quadrant")
        .first()
    )
    assert row is not None and row.computed_for == E.iso_date(E.today_date())


def test_mech_history_is_cached_and_stable(client):
    rid = _rid(client)
    a = client.get(f"/api/runners/{rid}/mech-history").json()
    b = client.get(f"/api/runners/{rid}/mech-history").json()
    assert a == b  # second read is served from cache, identical
    if a:
        assert a[-1]["date"] == E.iso_date(E.today_date())


def test_v2_history_replays_segment_streams(client, db_session):
    """A v2 runner with stored streams is scored per SEGMENT live; the history
    replay must see the same streams, or its trend/today point silently falls
    back to per-run drift and disagrees with the live score."""
    from .conftest import register
    from .synth import add_streams, seed_runs
    rid = register(client, "histseg@test.cz", "Hist Seg", "runner").json()["runner_id"]
    db = db_session
    seed_runs(db, rid)
    recent = E.day_ago(E.RECENT)
    add_streams(db, rid, lambda started: 18.0 if started > recent else 0.0)
    db.query(models.Runner).filter(models.Runner.id == rid).first().engine_mode = "v2"
    db.commit()
    live = E.recompute_assessment(db, rid)
    assert live["segmentScored"] is True

    hist = client.get(f"/api/runners/{rid}/quadrant-history").json()
    assert hist[-1]["date"] == E.iso_date(E.today_date())
    for axis in ("mech", "load", "symp", "overall", "quadrant"):
        assert hist[-1][axis] == live[axis], f"{axis}: history-end {hist[-1][axis]} != live {live[axis]}"
    mh = client.get(f"/api/runners/{rid}/mech-history").json()
    assert mh[-1]["mech"] == live["mech"]


def test_engine_compare_today_and_six_months_for_all_three(client, db_session):
    from app import models as M
    from app.metrics import engine as EN
    from tests.conftest import register as reg
    from tests.synth import seed_runs as seed
    rid = reg(client, "ecmp@test.cz", "Compare", "runner").json()["runner_id"]
    seed(db_session, rid, days=100)
    client.post("/api/auth/session", json={"email": "ecmp@test.cz", "password": "testpass123"})
    out = client.get(f"/api/runners/{rid}/engine-compare").json()
    assert set(out["today"]) == {"v1", "v2", "v3"}
    assert all(v["version"] and "signals" in v and v["quadrant"] for v in out["today"].values())
    assert out["series"][-1]["date"] == EN.iso_date(EN.today_date()) and 2 <= len(out["series"]) <= 27
    assert all({"v1", "v2", "v3"} <= set(p) for p in out["series"])
    db_session.expire_all()
    assert db_session.query(M.EngineHistoryCache).filter_by(runner_id=rid, kind="engines").first() is not None
    assert db_session.query(M.Runner).filter(M.Runner.id == rid).first().engine_mode in (None, "v1")   # untouched
    reg(client, "ecmp2@test.cz", "Other", "runner")
    client.post("/api/auth/session", json={"email": "ecmp2@test.cz", "password": "testpass123"})
    assert client.get(f"/api/runners/{rid}/engine-compare").status_code in (403, 404)
