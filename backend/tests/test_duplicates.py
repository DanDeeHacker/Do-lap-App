"""v0.12.11 — one recording is stored once: two syncs at once, copies stored before the
lock, and an imported activity the runner deleted."""
import threading
import time

from app import main as M
from app import models
from app.db import SessionLocal
from app.metrics import engine as E
from app.routers import integrations as I
from .test_guidance import _runner


def _seed(ext="g-77", day=1, minutes=96, provider="garmin"):
    return {"activities": [{"provider": provider, "external_id": ext, "started_at": E.day_ago(day), "title": "Strength",
                            "sport": "strength", "duration_min": minutes, "avg_hr": 96}], "daily_metrics": []}


def _strength_rows(db, rid, day=1):
    db.expire_all()
    return db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == "strength",
                                            models.Activity.started_at == E.day_ago(day)).all()


def _garmin(db, rid, ext="g-9", **kw):
    a = models.Activity(runner_id=rid, provider="garmin", external_id=ext, started_at=E.day_ago(2), title="Strength",
                        sport="strength", duration_min=60, **kw)
    db.add(a)
    db.flush()
    return a


def test_two_syncs_at_once_store_one_row(client, db_session, monkeypatch):
    rid, _ = _runner(client, db_session, "dup1@test.cz", days=20)
    twin = I._stored_twin

    def slow_twin(db, r, a):        # the window between "is it new?" and the commit
        out = twin(db, r, a)
        time.sleep(0.3)
        return out
    monkeypatch.setattr(I, "_stored_twin", slow_twin)
    monkeypatch.setattr(E, "dedupe_activities", lambda db, r: 0)   # the lock alone, without the merge of copies
    errors = []

    def sync():
        db = SessionLocal()
        try:
            I._merge_seed(db, rid, _seed())
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            db.close()
    threads = [threading.Thread(target=sync) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(_strength_rows(db_session, rid)) == 1


def test_copies_are_merged_into_the_rated_one(client, db_session):
    rid, _ = _runner(client, db_session, "dup2@test.cz", days=20)
    old = _garmin(db_session, rid, start_time="07:10")
    streamed = _garmin(db_session, rid)
    rated = _garmin(db_session, rid, excluded=True, excluded_at=E.now_iso(), excluded_scope="all")
    db_session.add(models.ActivityStream(activity_id=streamed.id, runner_id=rid, external_id="g-9", created_at=E.now_iso()))
    db_session.add(models.ActivityFeedback(activity_id=rated.id, runner_id=rid, submitted_at=E.day_ago(2), rpe=7,
                                           pain_points=[]))
    db_session.add(models.PlannedSession(runner_id=rid, date=E.day_ago(2), seq=0, kind="strength", activity_id=old.id))
    other = _garmin(db_session, rid, ext="g-10")
    db_session.commit()
    assert E.dedupe_activities(db_session, rid) == 2
    db_session.commit()
    left = db_session.query(models.Activity).filter_by(runner_id=rid, external_id="g-9").all()
    assert [a.id for a in left] == [rated.id]
    keep = left[0]
    # the copies were counted, so the merged session counts too; their details move over
    assert not keep.excluded and keep.excluded_scope is None and keep.start_time == "07:10"
    assert db_session.query(models.ActivityStream).filter_by(activity_id=keep.id).first() is not None
    assert db_session.query(models.ActivityFeedback).filter_by(activity_id=keep.id).first().rpe == 7
    assert db_session.query(models.PlannedSession).filter_by(runner_id=rid).first().activity_id == keep.id
    assert db_session.query(models.Activity).filter_by(id=other.id).first() is not None
    assert E.dedupe_activities(db_session, rid) == 0


def test_boot_merges_copies(client, db_session):
    rid, _ = _runner(client, db_session, "dup3@test.cz", days=20)
    _garmin(db_session, rid, ext="g-boot")
    _garmin(db_session, rid, ext="g-boot")
    db_session.commit()
    M._dedupe_activities(db_session)
    db_session.expire_all()
    assert db_session.query(models.Activity).filter_by(runner_id=rid, external_id="g-boot").count() == 1


def test_deleted_import_stays_deleted(client, db_session):
    rid, _ = _runner(client, db_session, "dup4@test.cz", days=20)
    I._merge_seed(db_session, rid, _seed())
    (a,) = _strength_rows(db_session, rid)
    aid = a.id
    db_session.add(models.ActivityFeedback(activity_id=aid, runner_id=rid, submitted_at=E.day_ago(1), rpe=6,
                                           pain_points=[]))
    db_session.commit()
    res = client.delete(f"/api/runners/{rid}/activities/{aid}")
    assert res.status_code == 200
    assert not _strength_rows(db_session, rid)
    assert db_session.query(models.ActivityFeedback).filter_by(activity_id=aid).first() is None
    gone = db_session.query(models.DeletedActivity).filter_by(runner_id=rid).one()
    assert gone.external_id == "g-77" and gone.provider == "garmin"
    # the next sync skips it, also the same session under another id (an Apple Health copy)
    I._merge_seed(db_session, rid, _seed())
    I._merge_seed(db_session, rid, _seed(ext="2026-10-13 07:00:00 +0200", minutes=97, provider="apple"))
    assert not _strength_rows(db_session, rid)
    # another session that day still arrives, from Garmin also one of the same length
    I._merge_seed(db_session, rid, _seed(ext="g-78", minutes=45))
    I._merge_seed(db_session, rid, _seed(ext="g-79", minutes=96))
    assert sorted(x.external_id for x in _strength_rows(db_session, rid)) == ["g-78", "g-79"]


def test_file_import_skips_deleted(client, db_session):
    rid, _ = _runner(client, db_session, "dup5@test.cz", days=5)
    db_session.add(models.DeletedActivity(runner_id=rid, provider="garmin", external_id="g-77", started_at=E.day_ago(1),
                                          sport="strength", duration_min=96, deleted_at=E.now_iso()))
    db_session.commit()
    seed = _seed()
    seed["activities"].append({**seed["activities"][0], "external_id": "g-80", "started_at": E.day_ago(3)})
    I._apply_seed(db_session, rid, seed)
    db_session.expire_all()
    left = db_session.query(models.Activity).filter_by(runner_id=rid).all()
    assert [a.external_id for a in left] == ["g-80"]


def test_manual_delete_leaves_no_tombstone(client, db_session):
    rid, _ = _runner(client, db_session, "dup6@test.cz", days=5)
    body = {"sport": "strength", "date": E.day_ago(1), "duration_min": 40, "rpe": 7, "legs": 3}
    aid = client.post(f"/api/runners/{rid}/activities/manual", json=body).json()["id"]
    assert client.delete(f"/api/runners/{rid}/activities/{aid}").status_code == 200
    assert db_session.query(models.DeletedActivity).filter_by(runner_id=rid).count() == 0
