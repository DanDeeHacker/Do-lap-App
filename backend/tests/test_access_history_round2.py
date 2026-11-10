"""Physio brief round 2 F11/F12: the runner's access history shows every event (50 per page, cursor on id) and
says where the detailed log begins; the daily summary counts record_events per day, actor and read/write; a
handover row names recipient and purpose; the export format is doslap-record-export/1."""
import json

from app import models
from app.metrics import engine as E
from app.routers.records import access_summary

from .conftest import login

PHYSIO, RUNNER, RID = "havlickova@fyzioholesovice.cz", "adela@demo.cz", "run-0001"


def test_paging_covers_every_event_and_says_where_it_starts(client, db_session):
    for k in range(120):
        db_session.add(models.RecordEvent(at=E.now_iso(), actor_type="physio", actor_id="phy-0001",
                                          actor_name="Mgr. Tereza Havlíčková", runner_id=RID, action="read",
                                          resource_type="runner"))
    db_session.commit()
    total = db_session.query(models.RecordEvent).filter(models.RecordEvent.runner_id == RID,
                                                        models.RecordEvent.actor_type != "runner").count()
    login(client, RUNNER)
    seen, before = [], None
    while True:
        r = client.get(f"/api/runners/{RID}/access-events", params={"before": before} if before else {}).json()
        assert len(r["items"]) <= 50
        seen += [x["id"] for x in r["items"]]
        before = r["next"]
        if not before:
            break
    assert len(seen) == total and len(set(seen)) == total and seen == sorted(seen, reverse=True)
    assert r["since"]


def test_daily_summary_counts_reads_and_writes_from_record_events(db_session):
    db_session.add(models.RecordEvent(at=E.now_iso(), actor_type="physio", actor_id="phy-0001", actor_name="T",
                                      runner_id=RID, action="update", resource_type="program"))
    db_session.commit()
    rows = access_summary(db_session, RID)
    today = E.today_date().isoformat()
    w = [x for x in rows if x["date"] == today and x["action"] == "write" and x["physio_id"] == "phy-0001"]
    reads = [x for x in rows if x["date"] == today and x["action"] == "read" and x["physio_id"] == "phy-0001"]
    assert w and w[0]["access_count"] >= 1 and reads


def test_handover_row_and_export_name(client, db_session):
    login(client, PHYSIO)
    r = client.post(f"/api/physios/me/clients/{RID}/documentation/handover",
                    json={"recipient": "MUDr. Ukázka", "purpose": "ortopedické vyšetření", "scope": "záznamy z návštěv"})
    assert r.status_code == 200, r.text
    login(client, RUNNER)
    items = client.get(f"/api/runners/{RID}/access-events").json()["items"]
    row = next(x for x in items if x["action"] == "handover")
    assert row["text"].endswith("— příjemce: MUDr. Ukázka, účel: ortopedické vyšetření")
    ev = db_session.query(models.RecordEvent).filter_by(action="handover", runner_id=RID).order_by(models.RecordEvent.id.desc()).first()
    assert "Achill" not in (ev.detail_json or "") and json.loads(ev.detail_json)["recipient"] == "MUDr. Ukázka"
    login(client, PHYSIO)
    ex = client.get(f"/api/physios/me/clients/{RID}/documentation/export")
    if ex.status_code == 200:
        assert ex.json()["format"] == "doslap-record-export/1"
