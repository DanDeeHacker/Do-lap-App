"""v0.12.17 (owner feedback 2026-10-22): a mechanics metric is a signal only when its drift is
both beyond the noise and worthwhile — the run means must shift by more than the smallest
worthwhile change, so a consistent but trivial shift no longer reads "na hraně"."""
from app import models
from app.metrics import engine as E

from .conftest import register
from .synth import seed_runs


def _vosc_after_shift(client, db, email, shift):
    rid = register(client, email, "Mech", "runner").json()["runner_id"]
    seed_runs(db, rid, days=100)
    cut = E.day_ago(28)
    for a in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at > cut):
        a.vert_osc_cm += shift
    db.commit()
    a = E.assess(db, rid)
    return a.get("vosc") or {}, {s["id"] for s in a.get("signals") or []}


def test_trivial_shift_is_not_a_signal(client, db_session):
    v, sig = _vosc_after_shift(client, db_session, "mech-small@test.cz", 0.1)   # < ½ SWC (0.31 cm)
    assert v.get("worth") == 0 and v.get("norm") == 0
    assert "vosc" not in sig


def test_worthwhile_shift_is_caught(client, db_session):
    v, sig = _vosc_after_shift(client, db_session, "mech-big@test.cz", 1.0)     # > 1.5 SWC
    assert v.get("worth") == 1 and v.get("norm") >= 1
    assert "vosc" in sig
