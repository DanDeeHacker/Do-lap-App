"""Physio brief round 2 F7: one adherence number. One fixture gives the same percentage and label in Klienti,
the Dnes alert, Přehled, Plán, Příprava and the runner's Péče; undated legacy ticks make it a capped total
estimate labelled "odhad"; a log without logged_on takes its created_at."""
from datetime import timedelta

from app import models
from app import work as W
from app.metrics import engine as E

from .conftest import login

PHYSIO, RUNNER, RID = "havlickova@fyzioholesovice.cz", "adela@demo.cz", "run-0001"


def _fixture(db):
    p = (db.query(models.Program).filter_by(runner_id=RID, active=True).order_by(models.Program.id.desc()).first())
    start = E.today_date() - timedelta(days=13)
    p.sent_at, p.status = start.isoformat(), "sent"
    ex = db.query(models.Exercise).filter_by(program_id=p.id).all()
    db.query(models.ExerciseLog).filter_by(program_id=p.id).delete()
    for e in ex:
        e.done_count = 0
    e0 = ex[0]
    e0.done_count = 5 + 3                                   # 5 dated logs + 3 ticks from before dated logs
    for k in range(5):
        db.add(models.ExerciseLog(exercise_id=e0.id, program_id=p.id, runner_id=RID,
                                  logged_on=None if k == 0 else (start + timedelta(days=k)).isoformat(),
                                  created_at=(start + timedelta(days=k)).isoformat() + "T10:00:00+01:00"))
    db.commit()
    return p


def test_one_number_on_every_surface(client, db_session):
    p = _fixture(db_session)
    a = W.program_adherence(db_session, p)
    assert a["method"] == "total_estimate" and a["undated_logs"] == 3 and a["done"] == 8
    assert a["pct"] <= 100 and a["text"].endswith("(odhad)")
    login(client, PHYSIO)
    clients = client.get("/api/physios/me/clients").json()
    row = next(c for c in (clients if isinstance(clients, list) else clients.get("items", clients.get("clients", [])))
               if c["runnerId"] == RID)
    assert row["program"]["adherence"] == a["pct"] and row["program"]["adherence_method"] == "total_estimate"
    ov = client.get(f"/api/physios/me/clients/{RID}").json()
    assert ov["adherence"]["pct"] == a["pct"] and ov["adherence"]["text"] == a["text"]
    pre = client.get(f"/api/physios/me/clients/{RID}/previsit").json()
    assert pre["plan_vs_reality"]["adherence"]["text"] == a["text"]
    plan = client.get(f"/api/runners/{RID}/program").json()
    assert plan["adherence"]["pct"] == a["pct"]
    assert W.alert_title("adherence_drop", {"pct": a["pct"], "method": a["method"]}) == a["text"]
    login(client, RUNNER)
    mine = client.get(f"/api/runners/{RID}/program").json()
    assert mine["adherence"]["pct"] == a["pct"] and mine["adherence"]["method"] == a["method"]


def test_weekly_when_every_tick_has_a_date(db_session):
    p = _fixture(db_session)
    e0 = db_session.query(models.Exercise).filter_by(program_id=p.id).order_by(models.Exercise.id).first()
    e0.done_count = 5
    db_session.commit()
    a = W.program_adherence(db_session, p)
    assert a["method"] == "weekly" and a["done"] == 5          # the log without logged_on counted by created_at
    assert a["text"] == f"Program splněn na {a['pct']} %"
