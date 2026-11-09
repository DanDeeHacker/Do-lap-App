"""Physio brief 2026-11-09 P0.12: the demo reset needs ALLOW_DEMO_RESET=1, refuses rows of a real
account, cleans the demo accounts and gives the same state when run twice."""
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
