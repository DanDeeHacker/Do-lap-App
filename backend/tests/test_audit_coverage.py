"""Physio brief 2026-11-09 R7: every route of the audited routers declares how it is audited, and one
scripted workflow produces the expected event sequence."""
from fastapi.routing import APIRoute

from app import audit as AU
from app import models
from app.main import app

from .conftest import login


def _routes(rs):
    for r in rs:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from _routes(r.original_router.routes)
        elif hasattr(r, "routes"):
            yield from _routes(r.routes)


def test_every_audited_route_declares_its_audit():
    missing = []
    for r in _routes(app.router.routes):
        if not set(r.tags) & AU.AUDITED_TAGS or set(r.tags) & {"records"}:
            continue                                   # the records router logs inside every handler
        for m in r.methods - {"HEAD", "OPTIONS"}:
            d = AU.declaration(m, r.path)
            if d is None or (d[0] == "exempt" and not d[1]):
                missing.append(f"{m} {r.path}")
    assert not missing, missing


def test_a_workflow_leaves_the_expected_events(client, db_session):
    login(client, "havlickova@fyzioholesovice.cz")
    start = db_session.query(models.RecordEvent.id).order_by(models.RecordEvent.id.desc()).first()
    start = start[0] if start else 0
    client.get("/api/physios/me/clients/run-0001")
    pid = client.post("/api/programs", json={"runner_id": "run-0001", "site": "Achillova šlacha"}).json()["id"]
    client.post(f"/api/programs/{pid}/send", json={})
    client.get("/api/physios/me/clients/run-0001/documentation")
    ev = (db_session.query(models.RecordEvent).filter(models.RecordEvent.id > start, models.RecordEvent.runner_id == "run-0001")
          .order_by(models.RecordEvent.id).all())
    seq = [(e.action, e.resource_type) for e in ev]
    assert seq == [("read", "runner"), ("create", "program"), ("update", "program"), ("read", "documentation")], seq
    assert all(e.actor_type == "physio" and e.actor_id == "phy-0001" for e in ev)
