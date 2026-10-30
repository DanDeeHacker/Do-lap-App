"""Review 2026-10-30 F1 (carried S1 since 2026-10-05): anyone can register as a physio, so a physio
account reads no runner until an owner verifies it, and a case is claimed once, while open, for a
runner who asked for a physio and hasn't declined this one."""
from app import models
from app.metrics import engine as E

from .conftest import login, register


def _new_physio(client, db, email, verify=True):
    pid = register(client, email, "Nová Fyzio", "physio").json()["physio_id"]
    if verify:
        p = db.get(models.Physio, pid)
        p.verified_at, p.verified_by = E.now_iso(), "test"
        db.commit()
    return pid


def _triage(db, rid, claimed_by=None, status="open"):
    t = models.Triage(runner_id=rid, decision="physio_48h", headline="test", status=status, claimed_by=claimed_by,
                      created_at=E.now_iso())
    db.add(t)
    db.commit()
    return t.id


def test_an_unverified_physio_sees_no_runner(client, db_session):
    _new_physio(client, db_session, "neovereny@f1.test.cz", verify=False)
    tid = _triage(db_session, "run-0001")
    assert client.get("/api/triage").status_code == 403
    assert client.patch(f"/api/triage/{tid}/claim").status_code == 403
    assert client.get("/api/physios/me/clients/run-0001").status_code == 403
    assert client.get("/api/runners/run-0001").status_code == 403
    assert client.get("/api/physios/me").json()["verified"] is False


def test_claim_requires_consent_open_unclaimed_unrevoked(client, db_session):
    _new_physio(client, db_session, "overeny@f1.test.cz")
    consented = db_session.query(models.Runner).filter(models.Runner.physio_interest.is_(True)).first()
    no_consent = db_session.query(models.Runner).filter(models.Runner.physio_interest.isnot(True)).first()
    taken = _triage(db_session, consented.id, claimed_by="phy-0001", status="claimed")
    closed = _triage(db_session, consented.id, status="closed")
    nocons = _triage(db_session, no_consent.id)
    assert client.patch(f"/api/triage/{taken}/claim").status_code == 409          # someone else's case
    assert client.patch(f"/api/triage/{closed}/claim").status_code == 409
    assert client.patch(f"/api/triage/{nocons}/claim").status_code == 403
    assert client.get(f"/api/physios/me/clients/{no_consent.id}").status_code == 403
    free = _triage(db_session, consented.id)
    assert client.patch(f"/api/triage/{free}/claim").status_code == 200


def test_an_owner_verifies_and_withdraws_a_physio(client, db_session, monkeypatch):
    pid = _new_physio(client, db_session, "kontrola@f1.test.cz", verify=False)
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "majitel-f1@f1.test.cz")
    register(client, "majitel-f1@f1.test.cz", "Majitel", "runner")
    items = client.get("/api/team/physios").json()["items"]
    assert any(x["id"] == pid and not x["verified"] and x["email"] == "kontrola@f1.test.cz" for x in items)
    assert client.post(f"/api/team/physios/{pid}/verify", json={"verified": True}).json()["verified"]
    login(client, "kontrola@f1.test.cz", "testpass123")
    assert client.get("/api/triage").status_code == 200
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "majitel-f1@f1.test.cz")
    login(client, "majitel-f1@f1.test.cz", "testpass123")
    assert not client.post(f"/api/team/physios/{pid}/verify", json={"verified": False}).json()["verified"]
    login(client, "kontrola@f1.test.cz", "testpass123")
    assert client.get("/api/triage").status_code == 403
