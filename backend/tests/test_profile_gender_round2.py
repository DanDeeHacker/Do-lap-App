"""Physio brief round 2 F15: the public card (photo, title read-only from Praxe, services, verification) and the
physio's grammatical gender in client messages and the access history — neutral wording without one."""
import base64

from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RUNNER, RID = "havlickova@fyzioholesovice.cz", "adela@demo.cz", "run-0001"
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def test_public_card_fields(client):
    login(client, PHYSIO)
    me = client.get("/api/physios/me").json()
    assert "title" in me and "services" in me and "verified_at" in me
    assert client.patch("/api/physios/me", json={"photo": PNG}).status_code == 200
    assert client.get("/api/physios/me").json()["photo_url"] == PNG
    assert client.patch("/api/physios/me", json={"photo": "javascript:alert(1)"}).status_code == 422
    assert client.patch("/api/physios/me", json={"grammatical_gender": "x"}).status_code == 422
    client.patch("/api/physios/me", json={"photo": ""})


def test_gender_in_messages_and_history(client, db_session):
    login(client, PHYSIO)
    lim = {"kind": "no_downhill", "reason_cs": "Achillovka", "starts_on": E.today_date().isoformat()}
    for g, expect in (("f", "nastavila omezení"), ("m", "nastavil omezení"), ("", "Bylo nastaveno omezení")):
        assert client.patch("/api/physios/me", json={"grammatical_gender": g}).status_code == 200
        r = client.post(f"/api/physios/me/clients/{RID}/limits", json=lim)
        assert r.status_code == 200, r.text
        db_session.expire_all()
        m = db_session.query(models.Message).filter_by(runner_id=RID, sender="system").order_by(models.Message.id.desc()).first()
        assert expect in m.body and "(a)" not in m.body
    client.patch("/api/physios/me", json={"grammatical_gender": "f"})
    db_session.add(models.RecordEvent(at=E.now_iso(), actor_type="physio", actor_id="phy-0001", actor_name="T",
                                      runner_id=RID, action="read", resource_type="runner"))
    db_session.commit()
    login(client, RUNNER)
    items = client.get(f"/api/runners/{RID}/access-events").json()["items"]
    assert items[0]["text"].startswith("zobrazila ")
    for x in db_session.query(models.ClinicalLimit).filter_by(runner_id=RID, kind="no_downhill").all():
        x.active = False
    db_session.commit()
