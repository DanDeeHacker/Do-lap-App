"""v0.12.16 (owner feedback 2026-10-19) — mechanics changes only with a new run: every
mechanics window counts back from the last run, not from today. Counted from today, the
baseline and the pace classes slid every morning without a run and the same last run read
as a different drift each day (18 → 22 → 26 over three days without running)."""
import random
from datetime import timedelta

from app import models
from app.metrics import engine as E
from .conftest import register


def _drifting_runner(client, db, email, last_ago=3):
    rid = register(client, email, "Anchor", "runner").json()["runner_id"]
    rng = random.Random(3)
    for d in range(100, last_ago - 1, -1):
        if rng.random() > 0.6 and d != last_ago:
            continue
        pace = rng.uniform(335, 380)
        drift = d <= 14                                  # the last two weeks: longer contact, more bounce
        cad = 172 - 0.12 * (pace - 355) + rng.gauss(0, 1.5)
        stride = 1000 / pace * 60 / cad * 2
        vosc = 8.5 + rng.gauss(0, 0.3) + (0.45 if drift else 0)
        db.add(models.Activity(
            runner_id=rid, provider="garmin", external_id=f"{email}-{d}", started_at=E.day_ago(d), sport="running",
            title="Běh", distance_km=10, duration_min=pace * 10 / 60, pace_s_km=pace, avg_hr=145, surface="road",
            ascent_m=20, descent_m=20, cadence_spm=cad, stride_len_m=stride, vert_osc_cm=vosc,
            vert_ratio_pct=vosc / (stride / 2 * 100) * 100,
            gct_ms=250 + 0.5 * (pace - 355) + rng.gauss(0, 5) + (8 if drift else 0), gct_balance_l=50))
    db.query(models.Runner).filter_by(id=rid).one().engine_mode = "v3"
    db.commit()
    return rid


def _mech(db, rid, day):
    with E.today_pinned(day), E.engine_pinned("v3"):
        a = E.assess(db, rid)
    mech_ids = {"tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv"}
    return a["mech"], sorted((s["id"], s["pts"]) for s in a["signals"] if s["id"] in mech_ids), a["confidence"].get("asOf")


def test_no_run_no_change_in_mechanics(client, db_session):
    rid = _drifting_runner(client, db_session, "anchor1@test.cz")
    last = E.today_date() - timedelta(days=3)
    first = _mech(db_session, rid, last)
    assert first[0] > 0 and first[2] == last.isoformat()
    for k in range(1, 9):                               # a week and more without running
        assert _mech(db_session, rid, last + timedelta(days=k)) == first
    # four weeks without a run: nothing recent to judge
    gone = _mech(db_session, rid, last + timedelta(days=E.RECENT + 1))
    assert gone[0] == 0 and gone[1] == [] and gone[2] is None
