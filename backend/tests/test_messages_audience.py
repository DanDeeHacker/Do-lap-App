"""Physio brief 2026-11-09 P0.10: the sender comes from the session, never from the request, and notes
meant for the physio never reach the runner."""
from app import models
from app.metrics import engine as E

from .conftest import login


def test_a_runner_cannot_post_as_physio_or_system(client, db_session):
    login(client, "adela@demo.cz")
    for claimed in ("physio", "system"):
        m = client.post("/api/runners/run-0001/messages", json={"sender": claimed, "body": f"jako {claimed}"}).json()
        assert m["sender"] == "runner"


def test_physio_only_notes_stay_with_the_physio(client, db_session):
    db_session.add(models.Message(runner_id="run-0001", physio_id="phy-0001", sender="system", audience="physio",
                                  body="Pacient požádal o termín — čeká na vaše potvrzení.", created_at=E.now_iso()))
    db_session.commit()
    login(client, "adela@demo.cz")
    bodies = [m["body"] for m in client.get("/api/runners/run-0001/messages").json()]
    assert not any(b.startswith("Pacient požádal") for b in bodies)
    boot = client.get("/api/runners/run-0001/bootstrap").json()
    assert not any((m["body"] or "").startswith("Pacient požádal") for m in boot["messages"])
    login(client, "havlickova@fyzioholesovice.cz")
    assert any(m["body"].startswith("Pacient požádal") for m in client.get("/api/runners/run-0001/messages").json())


def test_new_message_clears_once_the_physio_opens_the_thread(client, db_session):
    login(client, "adela@demo.cz")
    client.post("/api/runners/run-0001/messages", json={"body": "Dobrý den, mám dotaz."})
    login(client, "havlickova@fyzioholesovice.cz")
    row = lambda: next(c for c in client.get("/api/physios/me/clients").json()["items"] if c["runnerId"] == "run-0001")  # noqa: E731
    assert "message" in row()["attention"]
    client.get("/api/runners/run-0001/messages")
    assert "message" not in row()["attention"]
