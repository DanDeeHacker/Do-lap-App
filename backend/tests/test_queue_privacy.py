"""Physio brief 2026-11-09 P0.9: an unclaimed case carries no full name, claimed cases leave the queue,
a case can be passed on (hidden for me only) and released before — never after — a visit or record."""
import json

from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO = "havlickova@fyzioholesovice.cz"


def test_no_full_name_and_no_claimed_cases(client, db_session):
    login(client, PHYSIO)
    q = client.get("/api/triage?status=open&scope=all").json()
    assert q, "expected open cases"
    blob = json.dumps(q, ensure_ascii=False)
    for t in q:                       # the names of the runners behind these cases
        name = db_session.get(models.Runner, t["runner_id"]).name
        assert name and name not in blob, name
    assert all(t["claimed_by"] is None and t["display_name"].startswith("Klient") for t in q)
    claimed = {t.id for t in db_session.query(models.Triage).filter(models.Triage.claimed_by.isnot(None)).all()}
    assert not claimed & {t["id"] for t in q}


def test_pass_and_release(client, db_session):
    try:
        _pass_and_release(client, db_session)
    finally:                      # the seed DB is shared by the whole suite: leave the queue as it was
        db_session.rollback()
        db_session.query(models.TriagePass).filter_by(physio_id="phy-0001").delete()
        for t in db_session.query(models.Triage).filter(models.Triage.id.in_(_touched)).all():
            t.claimed_by, t.status = None, "open"
            db_session.query(models.CareAssignment).filter_by(physio_id="phy-0001", runner_id=t.runner_id).delete()
            db_session.query(models.Booking).filter_by(physio_id="phy-0001", runner_id=t.runner_id, status="completed").delete()
        db_session.commit()


_touched: list[int] = []


def _pass_and_release(client, db_session):
    login(client, PHYSIO)
    cared = {c.runner_id for c in db_session.query(models.CareAssignment).filter_by(physio_id="phy-0001").all()}
    q = [t for t in client.get("/api/triage?status=open&scope=all").json() if t["runner_id"] not in cared]
    a, b = q[0], q[1]
    _touched.extend([a["id"], b["id"]])
    assert client.post(f"/api/triage/{a['id']}/pass", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/triage/{a['id']}/pass", json={"reason": "mimo specializaci"}).status_code == 200
    assert a["id"] not in {t["id"] for t in client.get("/api/triage?status=open&scope=all").json()}
    # release right after claiming works
    assert client.patch(f"/api/triage/{b['id']}/claim").status_code == 200
    assert client.post(f"/api/triage/{b['id']}/release").status_code == 200
    assert client.get(f"/api/physios/me/clients/{b['runner_id']}").status_code == 403
    # once a visit exists it cannot go back
    t = db_session.query(models.Triage).filter(models.Triage.claimed_by.is_(None), models.Triage.status != "closed",
                                               models.Triage.id.notin_([a["id"], b["id"]]),
                                               models.Triage.runner_id.notin_(cared)).first()
    _touched.append(t.id)
    r = db_session.get(models.Runner, t.runner_id)
    r.physio_interest = True
    db_session.commit()
    assert client.patch(f"/api/triage/{t.id}/claim").status_code == 200
    db_session.add(models.Booking(runner_id=t.runner_id, physio_id="phy-0001", slot_at=E.now_iso(), kind="follow_up",
                                  status="completed", created_at=E.now_iso()))
    db_session.commit()
    assert client.post(f"/api/triage/{t.id}/release").status_code == 409
