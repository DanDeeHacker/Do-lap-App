"""Precomputed, incremental quadrant history (app.history + app.precompute).

The daily history must (a) survive a plain day rollover and be extended by only
the new day, (b) replay only from the first changed input date after a data
change, (c) always equal a full rebuild, and (d) be rebuilt by the background
worker right after a data change, so a read finds it ready.
"""
from datetime import timedelta

from app import history as H
from app import models, precompute
from app.metrics import engine as E
from .conftest import register
from .synth import seed_runs


def _runner(client, db, email):
    rid = register(client, email, "Hist Inc", "runner").json()["runner_id"]
    seed_runs(db, rid, days=60)
    E.recompute_assessment(db, rid)
    return rid


def test_day_rollover_extends_by_one_day_and_matches_full(client, db_session):
    db = db_session
    rid = _runner(client, db, "histinc1@test.cz")
    today = E.today_date()
    with E.today_pinned(today - timedelta(days=1)):
        st = H.refresh_quadrant_history(db, rid)
        assert st["kept"] == 0 and st["rows"][-1]["date"] == (today - timedelta(days=1)).isoformat()
        # the day-rollover refresh of the assessment must not drop the cached history
        E.recompute_assessment(db, rid, data_changed=False)
    row = db.query(models.EngineHistoryCache).filter_by(runner_id=rid, kind="quadrant").first()
    assert row is not None and row.payload_json["rows"]
    E.get_or_refresh_assessment(db, rid)       # new day → stale assessment → recompute without invalidation
    db.expire_all()
    assert db.query(models.EngineHistoryCache).filter_by(runner_id=rid, kind="quadrant").first().payload_json["rows"]

    st = H.refresh_quadrant_history(db, rid)
    assert st["replayed"] == 1 and st["rows"][-1]["date"] == today.isoformat()
    assert st["rows"] == H.build_quadrant_history(db, rid)
    assert H.refresh_quadrant_history(db, rid)["replayed"] == 0   # nothing changed → nothing replayed


def test_data_change_replays_from_first_changed_day(client, db_session):
    db = db_session
    rid = _runner(client, db, "histinc2@test.cz")
    H.refresh_quadrant_history(db, rid)

    # a check-in today: the cache is flagged dirty and only today is replayed
    db.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=6, pain_site="koleno"))
    db.commit()
    E.recompute_assessment(db, rid)
    assert H.quadrant_cache_fresh(db, rid) is None
    st = H.refresh_quadrant_history(db, rid)
    assert st["replayed"] == 1
    assert st["rows"] == H.build_quadrant_history(db, rid)
    assert st["rows"][-1]["symp"] > 0

    # an edit of a run 20 days back replays from that run's day onward
    a = (db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at < E.day_ago(19))
           .order_by(models.Activity.started_at.desc()).first())
    a.distance_km = (a.distance_km or 5) + 8
    db.commit()
    E.recompute_assessment(db, rid)
    st = H.refresh_quadrant_history(db, rid)
    assert st["replayed"] == E.days_between(a.started_at[:10], E.iso_date(E.today_date())) + 1
    assert st["rows"] == H.build_quadrant_history(db, rid)


def test_background_worker_rebuilds_after_a_data_change(client, db_session, monkeypatch):
    db = db_session
    rid = _runner(client, db, "histinc3@test.cz")
    monkeypatch.setenv("DOSSLAP_PRECOMPUTE", "1")
    db.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=3, pain_site="lýtko"))
    db.commit()
    E.recompute_assessment(db, rid)            # marks the cache dirty and queues the worker
    assert precompute.wait(rid, 60)
    db.expire_all()
    rows = H.quadrant_cache_fresh(db, rid)
    assert rows and rows[-1]["date"] == E.iso_date(E.today_date())
    # the endpoint serves the precomputed rows as they are
    client.post("/api/auth/session", json={"email": "histinc3@test.cz", "password": "testpass123"})
    assert client.get(f"/api/runners/{rid}/quadrant-history").json() == rows
