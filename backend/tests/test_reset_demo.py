"""Physio brief 2026-11-09 P0.12: the demo reset needs ALLOW_DEMO_RESET=1, refuses rows of a real
account, cleans the demo accounts and gives the same state when run twice."""
from datetime import datetime, timedelta

from app import models
from app.metrics import engine as E
from app.scripts import reset_demo as RD

from .conftest import register


def test_refuses_without_the_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_DEMO_RESET", raising=False)
    assert RD.main([]) == 2


def test_refuses_a_real_account(client, db_session, monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_RESET", "1")
    rid = register(client, "skutecny-bezec@test.cz", "Skutečný Běžec", "runner").json()["runner_id"]
    db_session.add(models.Message(runner_id=rid, sender="runner", body="TEST (Claude) ahoj", created_at=E.now_iso()))
    db_session.commit()
    assert RD.main(["--apply"]) == 3
    assert db_session.query(models.Message).filter_by(runner_id=rid).count() == 1     # nothing changed
    db_session.query(models.Message).filter_by(runner_id=rid).delete()
    db_session.commit()


def test_cleans_demo_and_is_idempotent(db_session, monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_RESET", "1")
    db_session.add(models.Message(runner_id="run-0001", sender="physio", body="TEST (Claude) zkouška", created_at=E.now_iso()))
    r = db_session.get(models.Runner, "run-0001")
    r.prior_injury = None
    db_session.commit()
    assert RD.main(["--apply"]) == 0
    db_session.expire_all()
    assert db_session.query(models.Message).filter(models.Message.body.contains("TEST (Claude)")).count() == 0
    assert db_session.get(models.Runner, "run-0001").prior_injury == "Achillova šlacha"
    assert RD.plan(db_session, {}) == []            # a second run has nothing left to do


# ---------------------------------------------------------------- round 2 F8
def test_round2_leftovers_are_removed_and_a_second_run_does_nothing(db_session, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setenv("ALLOW_DEMO_RESET", "1")
    now = datetime.fromisoformat(E.now_iso())
    svc = models.Service(physio_id="phy-0001", name_cs="TEST (Claude) Kontrola", duration_minutes=30, price_czk=600)
    lim = models.ClinicalLimit(runner_id="run-0001", physio_id="phy-0001", kind="max_km_week", value=20,
                               reason_cs="TEST (Claude) důvod", active=True, created_at=E.now_iso())
    plan = models.ReturnToRun(runner_id="run-0001", physio_id="phy-0001", created_at=E.now_iso(), status="completed",
                              current_level=1, pain_threshold=3, sessions_per_level=3, levels_json=[{"level": 1}])
    msg = models.Message(runner_id="run-0001", physio_id="phy-0001", sender="physio", body="Sdílel jsem s vámi plán.",
                         created_at=E.now_iso())
    db_session.add_all([svc, lim, plan, msg])
    db_session.flush()
    for k in range(3):        # three counted sessions within one minute
        db_session.add(models.RtrSession(plan_id=plan.id, runner_id="run-0001", level=1, pain=0, completed=True,
                                         counted=True, state="counted", logged_at=(now + timedelta(seconds=20 * k)).isoformat()))
    r = db_session.get(models.Runner, "run-0001")
    r.sex, r.birth_year = "m", 2001                     # "25 let · muž"
    db_session.commit()
    ids = (svc.id, lim.id, plan.id, msg.id)
    assert RD.main(["--apply"]) == 0
    db_session.expire_all()
    assert db_session.get(models.Service, ids[0]) is None and db_session.get(models.ClinicalLimit, ids[1]) is None
    assert db_session.query(models.RtrSession).filter_by(plan_id=ids[2]).count() == 1
    assert db_session.get(models.Message, ids[3]).body == "Sdílela jsem s vámi plán."
    r = db_session.get(models.Runner, "run-0001")
    assert (r.sex, r.birth_year) == ("f", 1991)
    assert RD.plan(db_session, {}) == []             # the same state after a second run


def test_recreate_refuses_a_database_with_real_runners(client, monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_RESET", "1")
    register(client, "realny-bezec-f8@test.cz", "Reálný Běžec", "runner")
    assert RD.main(["--recreate", "--apply"]) == 3
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    assert RD.main(["--recreate"]) == 3


def test_confirming_an_injury_does_not_write_prior_injury(client, db_session):
    """P0.5.9: the confirmed injury is current, not prior — runner.prior_injury* stays as it was."""
    from datetime import timezone
    from .conftest import login
    r = db_session.get(models.Runner, "run-0001")
    before = (r.prior_injury, r.prior_injury_date, r.prior_injury_side)
    at = (datetime.now(timezone.utc).replace(hour=4, minute=17, second=0, microsecond=0) - timedelta(days=3)).isoformat()
    b = models.Booking(runner_id="run-0001", physio_id="phy-0001", slot_at=at, kind="follow_up", status="confirmed",
                       created_at=E.now_iso())
    db_session.add(b)
    db_session.commit()
    login(client, "havlickova@fyzioholesovice.cz")
    client.put("/api/physios/me/clients/run-0001/card", json={"first_name": "Adéla", "last_name": "Kučerová",
               "birth_date": "1991-05-14", "sex_at_birth": "f", "permanent_street": "Ukázková 12",
               "permanent_city": "Praha", "permanent_postal_code": "17000"})
    cid = client.post(f"/api/bookings/{b.id}/conclusion/draft", json={
        "summary": "S", "outcome_kind": "injury", "out_participation": 8, "out_volume": 8, "out_performance": 8,
        "out_pain": 8, "out_region": "hamstring", "out_side": "L"}).json()["id"]
    assert client.post(f"/api/conclusions/{cid}/approve", json={"send_summary": False}).status_code == 200
    db_session.expire_all()
    r = db_session.get(models.Runner, "run-0001")
    assert (r.prior_injury, r.prior_injury_date, r.prior_injury_side) == before
