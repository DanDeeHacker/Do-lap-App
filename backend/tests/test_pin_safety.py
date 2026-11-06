"""Review 2026-10-30 N2 / N3: a day pinned in Plán týdne never overrides the morning's no-run or
easy-only default (illness, pain above 5/10, check-in readiness under 45 %), and on a day the app
shortens, a pinned run goes up to the day's recommendation, not to the safety ceiling. A pinned
long run works for a runner without a usual long-run day."""
import pytest

from app import models
from app.metrics import engine as E
from app.metrics import guidance as G

from .test_prevention import _assess, _checkin, _runner

STATES = {
    "ill": dict(flags={"ill": True, "ill_systemic": True}),
    "ill_light": dict(flags={"ill": True, "ill_systemic": False}),
    "pain6": dict(pain_score=6, pain_site="Achillova šlacha", pain_points=[{"region": "Achillova šlacha (L)"}]),
    "pain4": dict(pain_score=4, pain_site="Achillova šlacha", pain_points=[{"region": "Achillova šlacha (L)"}]),
    "low_ready": dict(soreness=10, stress=10, life_stress=10, sleep_quality=0),
}


def _pin(db, rid, typ, km):
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    r.planner_json = {**(r.planner_json or {}), "dayPins": {E.today_date().isoformat(): {"type": typ, "km": km}}}
    db.commit()


@pytest.mark.parametrize("state", list(STATES))
@pytest.mark.parametrize("pin", ["lehký", "regenerace"])
def test_pin_respects_illness_pain_readiness(client, db_session, state, pin):
    rid, _ = _runner(client, db_session, f"pin-{state}-{pin}@test.cz".replace("ý", "y").replace("_", ""))
    _checkin(db_session, rid, **STATES[state])
    g0 = _assess(db_session, rid)["guidance"]
    if state == "low_ready":
        assert (g0.get("checkinReadiness") or g0["readinessScore"]) < G.READY_EASY_ONLY
    hi0 = ((g0["types"].get(pin) or {}).get("km") or {}).get("hi")
    _pin(db_session, rid, pin, 40.0)
    g1 = _assess(db_session, rid)["guidance"]
    if g1.get("pin", {}).get("applied"):
        assert g0["types"][pin]["allowed"]
        # a pin never sizes above what the app recommends on a shortened day
        assert g1["types"][pin]["km"]["hi"] <= hi0 + 1e-9
        assert state in ("pain4", "ill_light") or (state == "low_ready" and pin == "regenerace")
    else:
        assert g1["type"] == g0["type"]
    if state in ("ill", "pain6"):
        assert g1["type"] == g0["type"] and g1["type"] not in ("lehký",)
        assert not g1["types"]["lehký"]["allowed"]
    if state == "ill":
        assert not g1["types"]["regenerace"]["allowed"] and g1["type"] == "volno"


def test_long_run_pin_without_usual_long_day(client, db_session, monkeypatch):
    """Demo Pavel Urban (v3) has room for a long run today; without a usual long-run day the
    pinned long run's reason used to raise TypeError at WD_IN[None] on every recompute."""
    r = db_session.query(models.Runner).filter(models.Runner.id == "run-0006").first()
    mode, planner = r.engine_mode, r.planner_json
    r.engine_mode = "v3"
    db_session.commit()
    real = G._pattern
    monkeypatch.setattr(G, "_pattern", lambda *x, **k: {**real(*x, **k), "longDay": None})
    try:
        _pin(db_session, "run-0006", "dlouhý", 14.0)
        g = _assess(db_session, "run-0006")["guidance"]
        assert g["types"]["dlouhý"]["allowed"] and g["type"] == "dlouhý" and g["pin"]["applied"]
    finally:
        r.engine_mode, r.planner_json = mode, planner
        db_session.commit()
        monkeypatch.undo()
        _assess(db_session, "run-0006")
