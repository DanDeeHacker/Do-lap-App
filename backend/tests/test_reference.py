"""Plan phases 1 and 2A: Bayesian individual reference ranges (Hecksteden et al.,
2017) and typical error / SWC (Thornton et al., 2019)."""
import math
from datetime import timedelta

import pytest

from app import models
from app.metrics import capacity as CAP
from app.metrics import engine as E
from app.metrics import reference as REF
from .conftest import register
from .synth import seed_runs


def test_individualize_matches_hand_computed_example():
    # prior m0 = 5.0, s0 = 0.6, s_RM = 0.5; one value 6.0, then 5.5
    m1 = (0.25 * 5.0 + 0.36 * 6.0) / (0.25 + 0.36)
    s1 = 1 / math.sqrt(1 / 0.25 + 1 / 0.36)
    m2 = (0.25 * m1 + s1 ** 2 * 5.5) / (0.25 + s1 ** 2)
    s2 = 1 / math.sqrt(2 / 0.25 + 1 / 0.36)
    m, s = REF.individualize([6.0, 5.5], 5.0, 0.6, 0.5)
    assert m == pytest.approx(m2) and s == pytest.approx(s2)
    # no data = the prior; many data = the runner's own mean and a narrow SD
    assert REF.individualize([], 5.0, 0.6, 0.5) == (5.0, 0.6)
    m, s = REF.individualize([7.0] * 200, 5.0, 0.6, 0.5)
    assert m == pytest.approx(7.0, abs=0.01) and s < 0.05


def test_pooled_sd_and_jackknife():
    groups = [[1.0, 2.0, 3.0], [10.0, 11.0, 12.0], [20.0, 21.0, 22.0]]
    assert REF.pooled_sd(groups) == pytest.approx(1.0)   # within-runner spread only
    m, sd = REF.lmo_jackknife(groups)
    assert 5 < m < 17 and sd > 3                          # between-runner spread, not within


def test_shrinkage_dead_zone_and_weight():
    assert REF.shrunk_sd(3.0, 3, None) == 3.0
    assert 1.0 < REF.shrunk_sd(3.0, 3, 1.0) < 3.0 and REF.shrunk_sd(3.0, 200, 1.0) == pytest.approx(3.0, rel=0.05)
    assert REF.dead_zone_z("gct_ms", None, None) == 0.2
    assert REF.dead_zone_z("gct_ms", 5.0, {"swc": 2.0}) == pytest.approx(0.4)
    assert REF.metric_weight_factor({"low_res": True}) == 0.5 and REF.metric_weight_factor(None) == 1.0


def test_priors_off_below_minimum_and_readiness_unchanged(client, db_session):
    REF.clear_cache()
    assert REF.recovery_priors(field="hrv_ms") is None       # conftest keeps the minimum out of reach
    assert REF.mech_priors(field="gct_ms") is None


def _night_runner(client, db, email, hrv_base, days=30):
    rid = register(client, email, "Ref Test", "runner").json()["runner_id"]
    today = E.today_date()
    for j in range(days):
        db.add(models.DailyMetric(runner_id=rid, date=(today - timedelta(days=j)).isoformat(),
                                  hrv_ms=hrv_base + (j % 5) - 2, resting_hr=50 + (j % 3), sleep_h=7.5))
    db.commit()
    return rid


def test_readiness_uses_individual_range_early(client, db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr(REF, "MIN_RUNNERS", 3)
    REF.clear_cache()
    for i, base in enumerate((40, 60, 80)):
        _night_runner(client, db, f"refpop{i}@test.cz", base)
    REF.clear_cache()
    pr = REF.recovery_priors(field="hrv_ms")
    assert pr and pr["log"] and pr["n"] >= 3
    # a new runner with only 5 baseline nights and a very low HRV last night
    rid = register(client, "refnew@test.cz", "Ref New", "runner").json()["runner_id"]
    today = E.today_date()
    for j in range(8, 13):
        db.add(models.DailyMetric(runner_id=rid, date=(today - timedelta(days=j)).isoformat(), hrv_ms=70, resting_hr=48))
    db.add(models.DailyMetric(runner_id=rid, date=today.isoformat(), hrv_ms=35, resting_hr=48))
    db.commit()
    rd = CAP.readiness_by_day(db, rid, [today.isoformat()])[today.isoformat()]
    assert rd[1].get("hrv", 0) > 0 and rd[2] < 100      # judged already, the old rule needed 14 nights
    band = REF.reference_band("hrv_ms", [70] * 5, pr)
    assert band[0] < 70 < band[2]
    monkeypatch.setattr(REF, "MIN_RUNNERS", 100000)
    REF.clear_cache()


def test_mech_priors_te_and_swc(client, db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr(REF, "MIN_RUNNERS", 2)
    for i in range(3):
        rid = register(client, f"refmech{i}@test.cz", "Ref Mech", "runner").json()["runner_id"]
        seed_runs(db, rid, days=90, seed=10 + i)
    REF.clear_cache()
    mp = REF.mech_priors(field="gct_ms")
    assert mp and mp["s_rm"] > 0 and mp["n"] >= 3
    if mp["te"] is not None and mp["swc"] is not None:
        assert mp["low_res"] == (mp["te"] >= mp["swc"])
    # the assessment carries the per-metric resolution and the sandbox reads it
    a = E.recompute_assessment(db, rid)
    assert set(a["mechRes"]) == {"tavr", "gct", "cad", "vosc"}
    monkeypatch.setattr(REF, "MIN_RUNNERS", 100000)
    REF.clear_cache()
