"""v0.10.0 — readiness per tissue and the body state (pain / injury) acting on the
capacity itself; the pain points on Příznaky and the readiness score stay as they were."""
from app import models
from app.metrics import capacity as C
from app.metrics import engine as E
from .test_guidance import _runner


def _cap(db, rid):
    with E.engine_pinned("v3"):
        return E.assess(db, rid)


def _ch(a, ch):
    return a["capacity"]["channels"][ch]


def test_msk_channels_take_hrv_and_resting_hr_at_half_weight():
    """Cardio channels keep the full factor, muscle / tendon / bone channels take HRV and
    resting HR at half weight, sleep at full weight on both."""
    auto = (0.82, {"hrv": 0.6, "rhr": 0.0, "sleep": 0.0}, 52)
    assert C.channel_readiness(auto, "systemic") == C.channel_readiness(auto, "intensity") == 0.82
    assert abs(C.channel_readiness(auto, "volume") - (1 - 0.3 * 0.3)) < 1e-9
    assert C.channel_readiness(auto, "descent") == C.channel_readiness(auto, "strength") == C.channel_readiness(auto, "volume")
    sleep = (0.85, {"sleep": 0.5}, 60)
    assert C.channel_readiness(sleep, "volume") == C.channel_readiness(sleep, "systemic") == 0.85
    assert C.channel_readiness((1.0, {}, 100), "volume") == 1.0


def test_pain_inside_the_model_holds_capacity_without_extra_margin(client, db_session):
    """Pain up to 5/10 (Silbernagel 2007): the capacity holds, only the margin above it goes;
    the systemic channel and the Příznaky points stay."""
    rid, _r = _runner(client, db_session, "body-hold@test.cz")
    before = _cap(db_session, rid)
    # 2/10: inside the model and under the 3/10 that marks runs as not tolerated, so the
    # demonstrated capacity itself stays the same and only the margin changes
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=2,
                                  pain_points=[{"region": "Koleno", "side": "L"}]))
    db_session.commit()
    after = _cap(db_session, rid)
    v0, v1 = _ch(before, "volume"), _ch(after, "volume")
    assert v1["body"]["kind"] == "painHold" and v1["body"]["factor"] == 1.0 and v1["body"]["hold"] < 0.05
    assert v1["ceilingToday"] < v0["ceilingToday"]
    assert v1["ceilingToday"] >= round(v1["capSession"] * v1["readinessFactor"], 1) - 0.1     # never below capacity
    assert v1["ceilingSession"] == v0["ceilingSession"]                                          # a normal day unchanged
    assert _ch(after, "systemic")["ceilingToday"] == _ch(before, "systemic")["ceilingToday"]


def test_pain_over_the_model_steps_capacity_back(client, db_session):
    """Pain above 5/10 → one step back (75 %), half of that on hard minutes."""
    rid, _r = _runner(client, db_session, "body-over@test.cz")
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=7,
                                  pain_points=[{"region": "Achillova šlacha", "side": "P"}]))
    db_session.commit()
    a = _cap(db_session, rid)
    vol, inten = _ch(a, "volume")["body"], _ch(a, "intensity")["body"]
    assert vol["kind"] == "painOver" and abs(vol["factor"] - 0.75) < 0.01
    assert abs(inten["factor"] - 0.875) < 0.01
    assert _ch(a, "systemic")["body"] is None
    assert any("sledování bolesti" in x for x in vol["reasons"])
    assert any(s["id"] == "pain" for s in a["signals"]) and a["symp"] > 0        # Příznaky keep the pain points


def test_worse_morning_pain_after_a_run_means_no_running_today(client, db_session):
    """The model's 'no lasting reaction': more pain this morning than during yesterday's run
    at the same site → today's running ceilings are 0 (the recommendation says rest)."""
    rid, _r = _runner(client, db_session, "body-morning@test.cz")
    y = E.day_ago(1)
    run = models.Activity(runner_id=rid, started_at=y, title="Běh", sport="running", distance_km=8.0,
                          duration_min=45.0, avg_hr=145.0)
    db_session.add(run)
    db_session.flush()
    db_session.add(models.ActivityFeedback(activity_id=run.id, runner_id=rid, submitted_at=y, pain_during=1,
                                           pain_points=[{"region": "Koleno", "side": "L"}]))
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=4,
                                  pain_points=[{"region": "Koleno", "side": "L"}]))
    db_session.commit()
    a = _cap(db_session, rid)
    assert a["painMonitor"] and a["painMonitor"]["morningWorse"]
    for ch in C.RUN_CH:
        c = _ch(a, ch)
        assert c["ceilingToday"] in (0, 0.0, None) and c["body"]["kind"] == "painMorning"
    assert (_ch(a, "systemic")["ceilingToday"] or 0) > 0


def test_active_injury_sets_running_ceilings_to_zero_and_keeps_its_symptom_points(client, db_session):
    rid, _r = _runner(client, db_session, "body-inj@test.cz")
    db_session.add(models.InjuryReport(runner_id=rid, submitted_at=E.now_iso(), source="self_adhoc", status="active",
                                       q_participation=17, q_volume=8, q_pain=8, severity=33, body_region="Koleno"))
    db_session.commit()
    a = _cap(db_session, rid)
    for ch in C.RUN_CH:
        assert _ch(a, ch)["ceilingToday"] in (0, 0.0, None) and _ch(a, ch)["body"]["kind"] == "injury"
    # the weekly ceiling follows the week's average state (one day of seven so far)
    wk = _ch(a, "volume")["week"]
    assert wk["ceiling"] < wk["cap"] * (1 + a["capacity"]["margins"]["week"])
    assert (_ch(a, "systemic")["ceilingToday"] or 0) > 0
    assert any(s["id"] == "injury" for s in a["signals"])                       # Příznaky still carry it


def test_graded_return_caps_the_weekly_capacity_and_blocks_hard_minutes(client, db_session):
    rid, _r = _runner(client, db_session, "body-rtr@test.cz")
    db_session.add(models.InjuryReport(runner_id=rid, submitted_at=E.day_ago(20), source="self_adhoc", status="resolved",
                                       q_participation=17, severity=17, body_region="Koleno", resolved_at=E.day_ago(2)))
    db_session.commit()
    a = _cap(db_session, rid)
    assert a["returnToRun"] and a["returnToRun"]["week"] == 1
    vol = _ch(a, "volume")
    wk = vol["week"]
    assert wk.get("capBase") is not None and wk["cap"] < wk["capBase"]
    assert vol["body"]["kind"] == "return"
    assert _ch(a, "intensity")["ceilingToday"] in (0, 0.0, None)                  # 14 days without hard minutes
    assert _ch(a, "systemic")["body"] is None


def test_readiness_block_and_channel_keys_stay_what_the_frontend_reads(client, db_session):
    rid, _r = _runner(client, db_session, "body-contract@test.cz")
    a = _cap(db_session, rid)
    rd = a["capacity"]["readiness"]
    assert {"today", "score", "label", "parts", "morningScore", "afterSession", "effects", "yesterday", "inputs"} <= set(rd)
    for ch in ("volume", "intensity", "descent", "ascent", "systemic"):
        c = _ch(a, ch)
        assert {"ceilingToday", "ceilingSession", "capSession", "week", "session", "pts", "readinessFactor", "body"} <= set(c)
        assert c["body"] is None                                                   # nothing to say without pain


def test_a_run_the_day_after_pain_scores_against_the_held_capacity():
    """body_state is read for the day before a session: pain inside the model removes the
    margin, so the same exceedance scores earlier."""
    assert C.band_points(1.08, C.MARGIN_SESSION * 0.0) > 0 == C.band_points(1.08, C.MARGIN_SESSION)
