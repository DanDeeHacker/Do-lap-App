"""Physio brief round 2 F2: older approved notes become part of the record — a card from the runner's name only
(incomplete, nothing invented), one care episode per pair opened at the earliest care, a legacy ledger row per
note in approval order through the same insert function, a flag (not a deletion) for a note approved before its
visit, past visits marked completed; a dry run writes nothing and a second run inserts nothing."""
import json
from datetime import datetime, timedelta, timezone

from app import models
from app import records as R
from app.metrics import engine as E
from app.scripts import backfill_round2 as B

from .conftest import login

PHYSIO = "havlickova@fyzioholesovice.cz"


def _runner(db, rid):
    if db.get(models.Runner, rid) is None:
        db.add(models.Runner(id=rid, name="Legacy Běžkyně"))
        db.commit()


def _legacy(db, rid, days, approved_days, minute):
    at = (datetime.now(timezone.utc).replace(hour=5, minute=minute, second=0, microsecond=0) + timedelta(days=days))
    b = models.Booking(runner_id=rid, physio_id="phy-0001", slot_at=at.isoformat(), kind="follow_up", status="confirmed",
                       created_at=E.now_iso())
    db.add(b)
    db.flush()
    c = models.Conclusion(booking_id=b.id, runner_id=rid, physio_id="phy-0001", status="approved",
                          summary=f"Shrnutí {minute}", finding=f"Nález {minute}", shared_at=E.now_iso(),
                          approved_at=(datetime.now(timezone.utc) + timedelta(days=approved_days)).isoformat())
    db.add(c)
    db.commit()
    return b.id, c.id


def test_backfill_brings_legacy_notes_into_the_record(client, db_session):
    rid = "run-legacy-f2"
    _runner(db_session, rid)
    old_b, old_c = _legacy(db_session, rid, -50, -50, 11)       # an ordinary older note
    early_b, early_c = _legacy(db_session, rid, 2, -1, 12)       # approved the day before its visit (round 1 bug)

    # the dry run counts and writes nothing
    res = B.run(db_session, dry_run=True, force=True)
    assert res["counts"]["clinical_records"] >= 2 and res["counts"]["patient_records"] >= 1
    db_session.expire_all()
    assert db_session.get(models.Conclusion, old_c).record_id is None
    assert db_session.get(models.MigrationApplied, B.NAME) is None

    res = B.run(db_session, force=True)
    db_session.expire_all()
    old, early = db_session.get(models.Conclusion, old_c), db_session.get(models.Conclusion, early_c)
    assert old.record_id and early.record_id
    rec_old = db_session.get(models.ClinicalRecord, old.record_id)
    body = json.loads(rec_old.content_json)
    assert body["legacy"] is True
    assert rec_old.authorised_at == old.approved_at                     # approval time, not the backfill time
    assert rec_old.encounter_at == db_session.get(models.Booking, old_b).slot_at
    flagged = json.loads(db_session.get(models.ClinicalRecord, early.record_id).content_json)
    assert flagged["flags"] == ["approved_before_encounter"]
    assert any(f["conclusion_id"] == early_c for f in res["flagged"])
    # the card: name only, incomplete, nothing invented
    card = db_session.query(models.PatientRecord).filter_by(runner_id=rid).one()
    assert card.incomplete == 1 and card.birth_date is None and card.sex_at_birth is None and card.permanent_city is None
    assert card.first_name == "Legacy"
    # the episode starts with the earliest care and links what had none
    ep = db_session.get(models.CareEpisode, old.episode_id)
    assert ep is not None and ep.opened_at[:10] == db_session.get(models.Booking, old_b).slot_at[:10]
    assert db_session.get(models.Booking, old_b).episode_id == ep.id
    # a past visit with an approved note took place; the future one keeps its status
    assert db_session.get(models.Booking, old_b).status == "completed"
    assert db_session.get(models.Booking, early_b).status == "confirmed"
    assert R.verify(db_session)["ok"]

    # a second run inserts nothing; without --force the guard row stops it outright
    n = db_session.query(models.ClinicalRecord).count()
    again = B.run(db_session, force=True)
    assert again["counts"].get("clinical_records", 0) == 0 and again["counts"].get("patient_records", 0) == 0
    assert B.run(db_session)["skipped"] is True
    assert db_session.query(models.ClinicalRecord).count() == n


def test_export_and_previsit_include_the_legacy_note(client, db_session):
    rid = "run-0001"
    _legacy(db_session, rid, -40, -40, 13)
    B.run(db_session, force=True)
    login(client, PHYSIO)
    r = client.get(f"/api/physios/me/clients/{rid}/documentation/export")
    assert r.status_code == 200, r.text
    assert any(x.get("legacy") or "Nález 13" in json.dumps(x, ensure_ascii=False) for x in r.json()["records"])
    docs = client.get(f"/api/physios/me/clients/{rid}/documentation").json()
    assert any(x["legacy"] for x in docs["records"])
    pre = client.get(f"/api/physios/me/clients/{rid}/previsit").json()
    assert pre["last_record"]["assessment"] and pre["last_record"]["plan"]


def test_main_dry_run_prints_counts(capsys):
    assert B.main(["--dry-run", "--force"]) == 0
    assert "Počty podle tabulek" in capsys.readouterr().out
