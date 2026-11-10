"""Physio brief round 2 F17: Dnes counts the queue with Fronta's own query; the next visit includes one later
today; the header's phase is in Czech."""
from datetime import datetime, timedelta, timezone

from app import models
from app.metrics import engine as E
from app.routers.physios import next_visit

from .conftest import login

PHYSIO, PID, RID = "havlickova@fyzioholesovice.cz", "phy-0001", "run-0001"


def test_dnes_counts_what_fronta_shows(client):
    login(client, PHYSIO)
    fronta = client.get("/api/triage").json()
    dnes = client.get("/api/physios/me/today").json()
    assert dnes["new_cases"] == len(fronta)


def test_next_visit_includes_later_today(db_session):
    now = datetime.now(timezone.utc)
    later = models.Booking(runner_id=RID, physio_id=PID, slot_at=(now + timedelta(minutes=37)).replace(microsecond=0).isoformat(),
                           duration_min=30, kind="follow_up", status="confirmed", created_at=E.now_iso())
    db_session.add(later)
    db_session.commit()
    try:
        assert next_visit(db_session, RID, PID).id == later.id
    finally:
        later.status = "cancelled"
        db_session.commit()
