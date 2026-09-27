"""Cross-training in the load model and the Trénink guidance (cycling, swimming, strength)."""
from types import SimpleNamespace

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from .test_guidance import _guide, _runner


def _act(**kw):
    base = dict(id=1, sport="running", duration_min=60, avg_hr=None, rpe=None, training_load=None,
                strength_focus=None, strength_type=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _strength(db, rid, days_ago, rpe=8, focus="lower", typ="heavy", minutes=45):
    a = models.Activity(runner_id=rid, provider="manual", started_at=E.day_ago(days_ago), sport="strength",
                        title="Posilování", duration_min=minutes, strength_focus=focus, strength_type=typ)
    db.add(a)
    db.flush()
    db.add(models.ActivityFeedback(activity_id=a.id, runner_id=rid, submitted_at=E.day_ago(days_ago), rpe=rpe,
                                   pain_points=[]))
    db.commit()
    return a


def test_sport_hr_max_uses_literature_offsets_then_own_sessions():
    hm = E.sport_hr_max([], 190)
    assert hm["cycling"] == 182 and hm["swimming"] == 178          # −8 (Millet 2009), −12 (DiCarlo 1991)
    rides = [_act(id=i, sport="cycling", avg_hr=178) for i in range(5)]
    assert E.sport_hr_max(rides, 190)["cycling"] == 188              # 5 hard rides raise it (avg + 10)
    assert E.sport_hr_max(rides[:4], 190)["cycling"] == 182          # 4 aren't enough


def test_session_load_per_sport():
    ctx = {"hr": {"cycling": 182, "swimming": 178}, "k": 0.45, "rpe": {7: 6}}
    lift = _act(id=7, sport="strength", avg_hr=110)
    assert E.session_load(lift, 190, 50, ctx) == 60 * 6 * 0.45       # sRPE, never heart rate
    assert E.session_load(_act(id=8, sport="strength"), 190, 50, ctx) == 60 * E.STRENGTH_DEFAULT_RPE * 0.45
    swim = _act(id=7, sport="swimming", avg_hr=140)
    assert E.session_load(swim, 190, 50, ctx) == 60 * 6 * 0.45       # a rated swim goes by sRPE
    ride = _act(id=9, sport="cycling", avg_hr=140)
    # the same heart rate is a larger share of the lower cycling HR max → more load than on the running scale
    assert E.session_load(ride, 190, 50, ctx) > E.session_load(ride, 190, 50)


def test_srpe_k_is_learned_from_rated_runs():
    runs = [_act(id=i, duration_min=50, avg_hr=150) for i in range(10)]
    k, n = E.srpe_k(runs, {i: 4 for i in range(10)}, 190, 50)
    assert n == 10 and E.SRPE_K_BOUNDS[0] <= k <= E.SRPE_K_BOUNDS[1]
    trimp = E._trimp(50, 150, 190, 50)
    assert abs(k - E.clamp(trimp / 200, *E.SRPE_K_BOUNDS)) < 1e-9
    assert E.srpe_k(runs[:5], {i: 4 for i in range(5)}, 190, 50) == (E.SRPE_K_DEFAULT, 5)


def test_heavy_lower_rule():
    assert E.heavy_lower(_act(sport="strength", strength_focus="lower", rpe=7), None)
    assert E.heavy_lower(_act(sport="strength", strength_focus="full", strength_type="plyo"), None)
    assert not E.heavy_lower(_act(sport="strength", strength_focus="upper", rpe=9), None)
    assert not E.heavy_lower(_act(sport="strength", strength_focus="lower", strength_type="circuit", rpe=5), None)


def test_manual_entry_twin_and_absorb(client, db_session):
    rid, r = _runner(client, db_session, "xt1@test.cz", days=40)
    body = {"sport": "strength", "date": E.day_ago(1), "duration_min": 40, "rpe": 7, "legs": 3,
            "strength_focus": "lower", "strength_type": "heavy"}
    res = client.post(f"/api/runners/{rid}/activities/manual", json=body)
    assert res.status_code == 200
    manual_id = res.json()["id"]
    # the watch recording of the same session arrives later → it takes the rating over
    watch = models.Activity(runner_id=rid, provider="garmin", external_id="g-lift", started_at=E.day_ago(1),
                            sport="strength", title="Strength", duration_min=44)
    db_session.add(watch)
    db_session.commit()
    assert E.absorb_manual(db_session, rid) == 1
    db_session.commit()
    assert db_session.query(models.Activity).filter_by(id=manual_id).first() is None
    fb = db_session.query(models.ActivityFeedback).filter_by(activity_id=watch.id).first()
    assert fb and fb.rpe == 7 and watch.strength_focus == "lower"
    # logging it again by hand is refused, the imported one is there
    assert client.post(f"/api/runners/{rid}/activities/manual", json=body).status_code == 409
    # imported activities can't be deleted, only excluded
    assert client.delete(f"/api/runners/{rid}/activities/{watch.id}").status_code == 400


def test_strength_channel_and_carry_over(client, db_session):
    rid, r = _runner(client, db_session, "xt2@test.cz", days=100)
    for d in range(30, 1, -4):                                   # a regular strength routine…
        _strength(db_session, rid, d, rpe=5, focus="full", typ="circuit")
    _strength(db_session, rid, 1, rpe=8)                          # …and a heavy leg session yesterday
    with E.engine_pinned("v3"):
        a = E.assess(db_session, rid)
    ch = a["capacity"]["channels"]["strength"]
    assert ch["label"] == "Silová zátěž" and ch["known"]
    g = _guide(db_session, rid, r)
    assert g["strength"]["carry"]["age"] == 1 and g["strength"]["carry"]["factor"] == 0.5
    assert not g["types"]["kvalitní"]["allowed"] and "Posilování nohou" in g["types"]["kvalitní"]["why"]
    assert any("Posilování nohou" in x for x in g["reasons"])
    # the run after it counts half in the mechanics drift and is labelled
    assert E.day_ago(0) in E.post_strength_dates(db_session, rid)
    assert E.day_ago(3) not in E.post_strength_dates(db_session, rid)


def test_cross_types_have_a_dose(client, db_session):
    rid, r = _runner(client, db_session, "xt3@test.cz", days=100)
    g = _guide(db_session, rid, r)
    kolo, voda, sila = g["types"]["kolo"], g["types"]["voda"], g["types"]["posilování"]
    assert kolo["cross"] and kolo["durationMin"][0] >= 20 and kolo["hr"][1] < g["types"]["lehký"]["hr"][1] + 1
    assert voda["rpeTarget"] and sila["rpeTarget"] == "6–7 z 10"
    assert g["strength"]["target"] == 2 and g["strength"]["done"] == 0
    # strength is not suggested the day before a usual hard day
    tomorrow = (E.today_date().weekday() + 1) % 7
    if tomorrow in g["pattern"]["hardDays"]:
        assert not sila["allowed"]


def test_capacity_pool_keeps_running_channels_running_only(client, db_session):
    rid, r = _runner(client, db_session, "xt4@test.cz", days=60)
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="ride", started_at=E.day_ago(2),
                                   sport="cycling", title="Kolo", duration_min=120, distance_km=60, avg_hr=140))
    db_session.commit()
    hm, rhr = 190, 50
    ride = [s for s in C.run_exposures(db_session, rid, hm, rhr) if s["sport"] == "cycling"][0]
    assert ride["exp"]["systemic"] and "volume" not in ride["exp"] and not ride["run"]
