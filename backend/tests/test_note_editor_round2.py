"""Physio brief round 2 F1: the note editor loses nothing — every save stamps autosaved_at on the server,
a PATCH carries only the changed fields and leaves the others alone, the follow-up knows the visit's service,
and "Zkopírovat z minula" copies from the same care episode, never the OSTRC."""
from datetime import datetime, timedelta, timezone

from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


_n = iter(range(1, 59))


def _booking(db, days=-2, episode_id=None, service_id=None):
    # an odd minute, so no other test's 09:00 booking collides on (physio, slot_at)
    at = (datetime.now(timezone.utc).replace(hour=6, minute=next(_n), second=0, microsecond=0)
          + timedelta(days=days)).isoformat()
    b = models.Booking(runner_id=RID, physio_id="phy-0001", slot_at=at, kind="follow_up", status="confirmed",
                       created_at=E.now_iso(), episode_id=episode_id, service_id=service_id)
    db.add(b)
    db.commit()
    return b.id


def test_every_save_stamps_autosaved_at_and_patch_is_partial(client, db_session):
    bid = _booking(db_session)
    login(client, PHYSIO)
    r = client.post(f"/api/bookings/{bid}/conclusion/draft", json={"objective": "Citlivost úponu"}).json()
    assert r["autosaved_at"], "the first save is stamped"
    first = r["autosaved_at"]
    r = client.patch(f"/api/conclusions/{r['id']}", json={"plan": "Výpony 3 × 15"})
    assert r.status_code == 200
    out = r.json()
    assert out["autosaved_at"] >= first
    assert out["objective"] == "Citlivost úponu", "a field that was not sent stays as it was"
    assert out["plan"] == "Výpony 3 × 15"
    assert db_session.get(models.Conclusion, out["id"]).autosaved_at == out["autosaved_at"]


def test_the_record_carries_the_visit_service_for_the_follow_up(client, db_session):
    svc = models.Service(physio_id="phy-0001", name_cs="Kontrola", duration_minutes=30, price_czk=600)
    db_session.add(svc)
    db_session.commit()
    bid = _booking(db_session, service_id=svc.id)
    login(client, PHYSIO)
    r = client.post(f"/api/bookings/{bid}/conclusion").json()
    assert r["service_id"] == svc.id and r["kind"] == "follow_up"


def test_copy_from_last_stays_in_the_episode_and_never_copies_ostrc(client, db_session):
    login(client, PHYSIO)
    ep_old = models.CareEpisode(physio_id="phy-0001", runner_id=RID, status="discharged", opened_at=E.now_iso())
    ep_new = models.CareEpisode(physio_id="phy-0001", runner_id=RID, status="open", opened_at=E.now_iso())
    db_session.add_all([ep_old, ep_new])
    db_session.commit()
    old_b, new_b, cur_b = _booking(db_session, -30, ep_old.id), _booking(db_session, -9, ep_new.id), _booking(db_session, -1, ep_new.id)
    now = datetime.now(timezone.utc)
    for b, text, ep, ago in ((old_b, "Stará epizoda", ep_old.id, 3), (new_b, "Tato epizoda", ep_new.id, 8)):
        db_session.add(models.Conclusion(booking_id=b, runner_id=RID, physio_id="phy-0001", status="approved",
                                         assessment=text, episode_id=ep,
                                         approved_at=(now - timedelta(days=ago)).isoformat(),
                                         outcome_kind="injury", out_pain=17))
    db_session.commit()
    # the old episode's record is newer, but the visit belongs to the new episode
    r = client.get(f"/api/physios/me/clients/{RID}/last-note", params={"bid": cur_b}).json()
    assert r["fields"]["assessment"] == "Tato epizoda"
    assert not any(k.startswith("out_") or k == "outcome_kind" for k in r["fields"])
