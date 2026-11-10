"""Physio brief 2026-11-09 R13: after withdrawal, Přehled, Program and Zprávy return 403 while the documentation
returns 200 with the banner; open programmes and plans end; both are logged."""
from app import models

from .conftest import login, register
from .test_records_ledger import approve_one


def test_withdrawal_leaves_only_the_documentation(client, db_session):
    approve_one(client, db_session)
    login(client, "havlickova@fyzioholesovice.cz")
    client.post("/api/programs", json={"runner_id": "run-0001", "site": "Achillova šlacha"})
    login(client, "adela@demo.cz")
    try:
        assert client.post("/api/runners/run-0001/physios/phy-0001/decline").status_code == 200
        login(client, "havlickova@fyzioholesovice.cz")
        assert client.get("/api/physios/me/clients/run-0001").status_code == 403
        assert client.get("/api/runners/run-0001/program").status_code == 403
        assert client.get("/api/runners/run-0001/messages").status_code == 403
        doc = client.get("/api/physios/me/clients/run-0001/documentation")
        assert doc.status_code == 200 and doc.json()["banner"].startswith("Klient odvolal")
        assert not db_session.query(models.Program).filter_by(runner_id="run-0001", physio_id="phy-0001", active=True).count()
        ev = db_session.query(models.RecordEvent).filter_by(runner_id="run-0001").order_by(models.RecordEvent.id.desc()).limit(5).all()
        assert any(e.action == "consent" and e.actor_type == "runner" for e in ev)
        assert any(e.action == "read" and e.resource_type == "documentation" for e in ev)
    finally:   # the shared seed DB: give the demo physio Adéla back (a new consent, as on a new booking)
        ca = db_session.query(models.CareAssignment).filter_by(physio_id="phy-0001", runner_id="run-0001").first()
        ca.status = "active"
        t = db_session.query(models.Triage).filter_by(runner_id="run-0001").first()
        t.claimed_by, t.status = "phy-0001", "claimed"
        db_session.commit()
