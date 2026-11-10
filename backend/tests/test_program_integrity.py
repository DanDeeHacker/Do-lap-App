"""Physio brief 2026-11-09 P0.8: no invented reason, no blank dose, per_week 1–7, every change logged
with a full timestamp, a stable order, one library item once, targets per_week × weeks, an end date."""
from app import models
from app.metrics import engine as E

from .conftest import login

PHYSIO, RID = "havlickova@fyzioholesovice.cz", "run-0001"


def _program(client, db):
    login(client, PHYSIO)
    pid = client.post("/api/programs", json={"runner_id": RID, "site": "Achillova šlacha"}).json()["id"]
    client.post(f"/api/programs/{pid}/send", json={})
    return pid


def test_validation_and_the_reason(client, db_session):
    pid = _program(client, db_session)
    ex = client.get(f"/api/runners/{RID}/program").json()
    assert ex["id"] == pid
    first = ex["exercises"][0]
    eid = first["id"]
    assert first["target_count"] == first["per_week"] * 4
    r = client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"dose": "  "}, "note": "x"})
    assert r.status_code == 422
    for bad in (0, 8):
        assert client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": bad}, "note": "x"}).status_code == 422
    # W10: edits to a sent programme are a draft; publishing asks for the reason the client sees (P0.8)
    assert client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"cue": ""}}).status_code == 200
    r = client.post(f"/api/programs/{pid}/send", json={})
    assert r.status_code == 422 and "důvod" in r.json()["detail"]
    assert client.post(f"/api/programs/{pid}/send", json={"note": "Pokyn už není potřeba"}).status_code == 200
    revs = db_session.query(models.ProgramRevision).filter_by(program_id=pid).all()
    assert revs[-1].note == "Pokyn už není potřeba" and "pokyn odstraněn" in revs[-1].changes[0]
    assert "T" in revs[-1].at and not any(rv.note == "Úprava po zpětné vazbě pacienta." for rv in revs)
    assert all(rv.note for rv in revs)                     # nothing pending after the publish


def test_order_is_stable_and_a_library_item_is_added_once(client, db_session):
    pid = _program(client, db_session)
    order = [e["id"] for e in client.get(f"/api/runners/{RID}/program").json()["exercises"]]
    client.patch(f"/api/programs/exercises/{order[0]}", json={"patch": {"dose": "3 × 10"}, "note": "Méně opakování"})
    client.post(f"/api/programs/{pid}/send", json={"note": "Méně opakování"})
    login(client, "adela@demo.cz")
    client.patch(f"/api/runners/{RID}/exercises/{order[1]}/log")
    assert [e["id"] for e in client.get(f"/api/runners/{RID}/program").json()["exercises"]] == order
    login(client, PHYSIO)
    body = {"name": "Most na jedné noze", "dose": "3 × 10", "per_week": 3, "library_id": "lib-bridge-1"}
    assert client.post(f"/api/programs/{pid}/exercises", json=body).status_code == 200
    assert client.post(f"/api/programs/{pid}/exercises", json=body).status_code == 409
    prog = client.get(f"/api/runners/{RID}/program").json()
    assert prog["exercises"][-1]["library_id"] == "lib-bridge-1" and prog["ends_on"]


def test_changing_per_week_keeps_what_is_done(client, db_session):
    pid = _program(client, db_session)
    eid = client.get(f"/api/runners/{RID}/program").json()["exercises"][0]["id"]
    e = db_session.get(models.Exercise, eid)
    e.done_count = 2
    db_session.commit()
    client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": 2}, "note": "Méně často"})
    db_session.expire_all()
    e = db_session.get(models.Exercise, eid)
    assert e.target_count == 2 + 2 * 4 and E.today_date()


# ---------------------------------------------------------------- round 2 F6
def test_two_publishes_make_version_3_and_the_runner_sees_the_new_date(client, db_session):
    pid = _program(client, db_session)                      # sent once: version 1
    eid = client.get(f"/api/runners/{RID}/program").json()["exercises"][0]["id"]
    for k, note in ((4, "Méně často"), (3, "Ještě méně")):
        assert client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": k}}).status_code == 200
        assert client.post(f"/api/programs/{pid}/send", json={"note": note}).status_code == 200
    p = db_session.get(models.Program, pid)
    db_session.refresh(p)
    assert p.version == 3
    latest = db_session.query(models.ProgramVersion).filter_by(program_id=pid).order_by(models.ProgramVersion.version.desc()).first()
    login(client, "adela@demo.cz")
    mine = client.get(f"/api/runners/{RID}/program").json()
    assert mine["published_at"] == latest.published_at
    # one history entry per publish (two on the same day group into one entry with both notes)
    hist = mine["history"]
    assert len(hist) == len({(h["at"] or "")[:10] for h in hist})
    assert any("Ještě méně" in (h["note"] or "") for h in hist)
    assert any("4× → 3× týdně" in c for h in hist for c in h["changes"])


def test_a_seeded_sent_programme_without_versions_publishes_as_version_2(client, db_session):
    pid = _program(client, db_session)
    db_session.query(models.ProgramVersion).filter_by(program_id=pid).delete()
    db_session.get(models.Program, pid).version = None
    db_session.commit()
    eid = client.get(f"/api/runners/{RID}/program").json()["exercises"][0]["id"]
    client.patch(f"/api/programs/exercises/{eid}", json={"patch": {"per_week": 2}})
    assert client.post(f"/api/programs/{pid}/send", json={"note": "Úprava"}).json()["version"] == 2


def test_target_is_per_week_times_weeks_on_read(client, db_session):
    pid = _program(client, db_session)
    p = db_session.get(models.Program, pid)
    db_session.query(models.ProgramPhase).filter_by(program_id=pid).delete()
    p.weeks = 4
    e = db_session.query(models.Exercise).filter_by(program_id=pid).first()
    e.per_week, e.target_count, e.target_set = 5, 12, False          # the stored /12 from the evidence
    db_session.commit()
    out = client.get(f"/api/runners/{RID}/program").json()
    assert next(x for x in out["exercises"] if x["id"] == e.id)["target_count"] == 20


def test_a_patch_without_change_writes_nothing_and_per_leg_dose_keeps_its_suffix(client, db_session):
    pid = _program(client, db_session)
    e = db_session.query(models.Exercise).filter_by(program_id=pid).first()
    e.dose, e.sets, e.reps, e.side = "3 × 15 / noha", 3, 15, None
    db_session.commit()
    n_rev = db_session.query(models.ProgramRevision).filter_by(program_id=pid).count()
    n_msg = db_session.query(models.Message).filter_by(runner_id=RID).count()
    r = client.patch(f"/api/programs/exercises/{e.id}", json={"patch": {"sets": 3, "reps": 15}, "note": "nic"})
    assert r.status_code == 200 and r.json()["dose"] == "3 × 15 / noha"
    db_session.expire_all()
    assert db_session.query(models.ProgramRevision).filter_by(program_id=pid).count() == n_rev
    assert db_session.query(models.Message).filter_by(runner_id=RID).count() == n_msg
    # a real change regenerates the dose with the side suffix
    r = client.patch(f"/api/programs/exercises/{e.id}", json={"patch": {"reps": 12}}).json()
    assert r["dose"] == "3 × 12 / noha" and r["side"] == "per_leg"
    rv = db_session.query(models.ProgramRevision).filter_by(program_id=pid).order_by(models.ProgramRevision.id.desc()).first()
    assert rv.changes == [f"{e.name}: nová dávka 3 × 12 / noha"]


def test_programme_ends_after_the_latest_publish():
    from app.routers.programs import ends_on
    p = models.Program(weeks=4, started_on="2026-09-01", sent_at="2026-09-01")
    assert ends_on(p) == "2026-09-29"            # without a session: the first send
