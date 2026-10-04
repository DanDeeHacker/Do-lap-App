"""Engine v0.12.0 — profile gate risk factors, critical speed, Rychlost, illness signal,
menstrual-cycle-aware readiness and shoes."""
import base64
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import models
from app import shoes as SH
from app.metrics import capacity as C
from app.metrics import cycle as CY
from app.metrics import engine as E
from app.metrics import guidance as G
from app.metrics import illness as IL
from app.metrics import runner_factors as RF
from app.metrics import speed as SP
from .conftest import register


def _day(n):
    return (E.today_date() - timedelta(days=n)).isoformat()


def _segs(*blocks, start=0):
    """Contiguous 60-s flat segments: blocks of (minutes, m/s)."""
    out, t = [], start
    for mins, v in blocks:
        for _ in range(int(mins)):
            out.append({"durationS": 60, "meanSpeed": v, "meanGradient": 0.0, "elapsedS": t})
            t += 60
    return out


# ------------------------------------------------------------------ critical speed
def test_mean_max_uses_contiguous_segments_only():
    segs = _segs((3, 5.0), (20, 3.0))
    mm = SP.mean_max(segs)
    assert mm[180] == pytest.approx(5.0)
    assert mm[1200] == pytest.approx((3 * 5.0 + 17 * 3.0) / 20)
    gap = _segs((2, 5.0)) + _segs((2, 5.0), start=10_000)       # two 2-min reps far apart
    assert 180 not in SP.mean_max(gap)


def test_cs_fit_needs_a_real_short_effort():
    # 3 min at 5.0, 6 at 4.7, 10 at 4.5, 15 at 4.4, 20 at 4.33 → CS ≈ 4.2 m/s, D′ ≈ 180 m
    pts = {180: 5.0, 360: 4.7, 600: 4.5, 900: 4.4, 1200: 4.33}
    cs = SP.fit_cs(pts, None)
    assert 4.1 < cs["cs"] < 4.3 and 100 < cs["dPrime"] < 300
    flat = {180: 3.3, 360: 3.3, 600: 3.25, 900: 3.25, 1200: 3.2}  # only easy running: no CS
    assert SP.fit_cs(flat, None) is None
    # a long run faster than the fitted CS lifts it (efforts in training are not maximal)
    assert SP.fit_cs(pts, 4.35)["cs"] == 4.35


def _run(n, sid, km, mins, g=None, **extra):
    return {"id": sid, "date": _day(n), "run": True, "title": "Běh", "km": km, "durationMin": mins,
            "gSpeed": g if g is not None else km * 1000 / (mins * 60), "exp": {"volume": km, "intensity": 0.0}, **extra}


def test_minutes_above_cs_count_as_intensity_and_threshold_work_is_a_hard_day():
    hard = _segs((10, 3.0), (3, 5.0), (2, 3.0), (6, 4.7), (2, 3.0), (10, 4.5), (2, 3.0), (20, 4.33))
    runs = [_run(40, 1, 12.0, 60), _run(30, 2, 10.0, 50)]
    segs = {1: hard}
    tempo = _run(1, 3, 10.0, 45)                                # 25 min at 0.95 × CS
    segs[3] = _segs((10, 3.0), (25, 4.0), (10, 3.0))
    intervals = _run(0, 4, 8.0, 40)
    segs[4] = _segs((10, 3.0), (8, 4.8), (10, 3.0))             # 8 min above CS (≈ 1.14 × CS)
    out = runs + [tempo, intervals]
    SP.add_speed(out, segs, _day(200))
    assert 4.1 < tempo["cs"] < 4.3
    assert tempo["thrMin"] == pytest.approx(25, abs=0.1) and tempo["csMin"] == 0
    assert G.is_hard(tempo)                                      # ≥ 20 min of threshold work
    assert intervals["exp"]["intensity"] == pytest.approx(8, abs=0.1) and intervals["z4Source"] == "cs"
    assert intervals["exp"]["speed"] == pytest.approx(8, abs=0.1)   # ≥ 1.10 × CS
    assert tempo["exp"]["speed"] == 0
    # a run without segments: its whole average decides
    race = _run(0, 5, 5.0, 18.5)                                 # 4.5 m/s ≥ CS → all of it hard
    out.append(race)
    SP.add_speed(out, segs, _day(200))
    assert race["csMin"] == pytest.approx(18.5)


def test_speed_channel_exists_and_strides_note_after_four_weeks():
    assert "speed" in C.CHANNELS and len(C.COMBO) >= len(C.CHANNELS)
    ses = [_run(n, n, 10.0, 55) for n in range(60, 0, -3)]
    for s in ses:
        s["exp"]["speed"] = 0.0
    ses[2]["exp"]["speed"] = 3.0                                 # some fast reps ~54 days ago
    nsw = SP.no_speed_weeks(ses, E.today_date())
    assert nsw and nsw["lastDate"] == ses[2]["date"]
    ses[-1]["exp"]["speed"] = 1.0
    assert SP.no_speed_weeks(ses, E.today_date()) is None


# ------------------------------------------------------------------ illness
def _dm(days):
    return SimpleNamespace(daily_by_date={d: SimpleNamespace(date=d, **v) for d, v in days.items()})


def test_illness_signal_needs_two_nights_or_both_signs():
    base = {_day(k): {"resting_hr": 48 + (k % 3) * 0.5, "resp_rate": 14.0 + (k % 2) * 0.2} for k in range(8, 50)}
    one = {**base, _day(0): {"resting_hr": 55, "resp_rate": 14.1}, _day(1): {"resting_hr": 48.5, "resp_rate": 14.0}}
    assert IL.illness_signal(_dm(one), _day(0)) is None           # one night, one sign: noise
    two = {**base, _day(0): {"resting_hr": 55, "resp_rate": 14.1}, _day(1): {"resting_hr": 54, "resp_rate": 14.0}}
    sig = IL.illness_signal(_dm(two), _day(0))
    assert sig and sig["kinds"] == ["rhr"] and sig["since"] == _day(1)
    both = {**base, _day(0): {"resting_hr": 55, "resp_rate": 16.2}, _day(1): {"resting_hr": 48, "resp_rate": 14.0}}
    assert IL.illness_signal(_dm(both), _day(0))["kinds"] == ["resp", "rhr"]


def test_watch_illness_signal_asks_and_limits_the_day(client, db_session):
    rid = register(client, "ill012@test.cz", "Nemocná", "runner").json()["runner_id"]
    for k in range(60, 1, -1):
        db_session.add(models.DailyMetric(runner_id=rid, date=_day(k), resting_hr=48 + (k % 3) * 0.5,
                                          resp_rate=14.0, hrv_ms=60, sleep_h=7.5))
    db_session.add(models.DailyMetric(runner_id=rid, date=_day(1), resting_hr=55, resp_rate=14.1, hrv_ms=50, sleep_h=7.2))
    db_session.add(models.DailyMetric(runner_id=rid, date=_day(0), resting_hr=56, resp_rate=15.6, hrv_ms=48, sleep_h=7.0))
    for k in range(40, 0, -2):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", started_at=_day(k) + "T07:00:00", title="Běh",
                                       distance_km=8.0, duration_min=45, avg_hr=140, sport="running"))
    db_session.commit()
    a = E.recompute_assessment(db_session, rid)
    sig = a["screening"]["illSignal"]
    assert sig and sig["answer"] is None and set(sig["kinds"]) == {"resp", "rhr"}
    g = a.get("guidance") or E.get_or_refresh_assessment(db_session, rid).get("guidance")
    if g:
        assert not g["types"]["kvalitní"]["allowed"]
    # the two check-in questions: symptoms only above the neck → a short easy run at most
    client.post(f"/api/runners/{rid}/checkins", json={"pain_score": 0, "flags": {"ill": True, "ill_systemic": False}})
    a = E.get_or_refresh_assessment(db_session, rid)
    assert a["screening"]["illSignal"]["answer"] == "above"
    assert a["screening"]["ill"]["systemic"] is False


# ------------------------------------------------------------------ menstrual cycle
def test_cycle_phase_and_own_offset():
    t = E.today_date()
    mj = {"track": True, "hormonal": False, "length": 28,
          "starts": [(t - timedelta(days=d)).isoformat() for d in (73, 45, 17)]}
    assert CY.cycle_length(mj) == 28
    assert CY.phase_on(mj, t)["phase"] == "luteal" and CY.phase_on(mj, t)["day"] == 18
    assert CY.phase_on(mj, t - timedelta(days=15))["phase"] == "menstrual"
    assert CY.phase_on({**mj, "hormonal": True}, t) is None
    # own data: resting HR 3 bpm higher in the luteal nights
    rows = []
    for k in range(8, 57):
        d = t - timedelta(days=k)
        lut = CY.phase_on(mj, d)
        rows.append(SimpleNamespace(date=d.isoformat(), resting_hr=50.0 + (3.0 if lut and lut["group"] == "luteal" else 0.0)))
    sh, src = CY.shift(mj, t, rows, "resting_hr", lambda v: v)
    assert src == "own" and 1.0 < sh < 2.0


def test_luteal_nights_are_judged_against_the_luteal_norm(db_session):
    t = E.today_date()
    rid = "cyc-run"
    mj = {"track": True, "hormonal": False, "length": 28, "starts": [(t - timedelta(days=d)).isoformat() for d in (73, 45, 17)]}
    db_session.add(models.Runner(id=rid, name="Cyklus", sex="f", birth_year=1992, menstrual_json=mj))
    for k in range(0, 57):
        d = t - timedelta(days=k)
        lut = CY.phase_on(mj, d)["group"] == "luteal"
        db_session.add(models.DailyMetric(runner_id=rid, date=d.isoformat(), resting_hr=50 + (4 if lut else 0) + (k % 2) * 0.5,
                                          hrv_ms=70 - (8 if lut else 0) + (k % 3), sleep_h=7.5))
    db_session.commit()
    with_cycle = C.readiness_by_day(db_session, rid, [t.isoformat()])[t.isoformat()]
    r = db_session.query(models.Runner).get(rid)
    r.menstrual_json = {**mj, "track": False}
    db_session.commit()
    without = C.readiness_by_day(db_session, rid, [t.isoformat()])[t.isoformat()]
    assert with_cycle[2] > without[2]                    # the luteal rise isn't read as poor recovery
    inp = C.readiness_inputs(db_session, rid, t.isoformat())
    assert "cycle" not in inp
    r.menstrual_json = mj
    db_session.commit()
    inp = C.readiness_inputs(db_session, rid, t.isoformat())
    assert inp["cycle"]["phase"] == "luteal" and inp["cycle"]["source"] == "own" and inp["cycle"]["rhrShift"] > 1


# ------------------------------------------------------------------ experience & shoes
def test_experience_factor_first_year():
    t = date(2026, 10, 4)
    assert RF.experience(SimpleNamespace(running_since="2026-07-01"), t)["factor"] == 0.8
    assert RF.experience(SimpleNamespace(running_since="2026-01-01"), t)["factor"] == 0.9
    assert RF.experience(SimpleNamespace(running_since="2020-01-01"), t) is None
    assert RF.experience(SimpleNamespace(running_since=None), t) is None


def _shoe(sid, first, drop=10.0, cat="daily", carbon=False, retired=None, brand="Brand", model="M"):
    return SimpleNamespace(id=sid, brand=brand, model=model, category=cat, drop_mm=drop, carbon=carbon,
                           first_used=first, retired_at=retired)


def test_shoe_transition_and_rotation():
    t = date(2026, 10, 4)
    old = _shoe(1, "2026-03-01", drop=10)
    new_low = _shoe(2, "2026-09-20", drop=4, cat="daily")
    st = RF.shoe_state([old, new_low], SimpleNamespace(weight_kg=70), t)
    assert st["transition"]["kind"] in ("minimal", "drop") and st["factor"] == 0.75
    assert st["rotation"]["n"] == 2
    heavy = RF.shoe_state([old, new_low], SimpleNamespace(weight_kg=92), t)
    assert heavy["factor"] == 0.65 and heavy["transition"]["heavy"]
    later = RF.shoe_state([old, new_low], SimpleNamespace(weight_kg=70), date(2026, 11, 15))
    assert later["transition"] is None                       # 6 weeks are over
    same = RF.shoe_state([old, _shoe(3, "2026-09-25", drop=10)], None, t)
    assert same["transition"] is None                        # same kind of shoe: nothing to adapt
    carbon = RF.shoe_state([old, _shoe(4, "2026-09-25", drop=8, cat="racing", carbon=True)], None, t)
    assert carbon["transition"]["kind"] == "carbon" and carbon["factor"] == 0.9


def test_shoe_suggestion_is_standardised():
    s = SH.standardise({"brand": "hoka one one", "model": "HOKA Clifton 9", "category": "Cushioned",
                        "drop_mm": "5", "stack_mm": 32, "carbon": False, "confidence": 0.8})
    assert s == {"brand": "HOKA", "model": "Clifton 9", "category": "cushioned", "drop_mm": 5.0, "stack_mm": 32.0,
                 "carbon": False, "confidence": 0.8}
    v = SH.standardise({"brand": "vivobarefoot", "model": "Primus Lite", "drop_mm": 6})
    assert v["drop_mm"] == 0 and v["category"] == "minimal"
    assert SH.standardise({"brand": "Nike", "model": "Vaporfly 3", "carbon": True})["category"] == "racing"
    line = SH.standardise({"brand": "Nike", "model": "Pegasus", "drop_mm": 8, "confidence": 1.0})
    assert line["drop_mm"] is None and line["confidence"] == 0.5            # no version: no guessed drop
    assert SH._json('Here: {"is_shoe": true, "brand": "Nike"} done')["brand"] == "Nike"
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 50).decode()
    assert SH.check_image(png) and not SH.check_image("data:text/html;base64,PGI+")


def test_shoes_api_and_transition_narrows_running_margins(client, db_session, monkeypatch):
    rid = register(client, "shoe012@test.cz", "Botař", "runner").json()["runner_id"]
    for k in range(80, 0, -2):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", started_at=_day(k) + "T07:00:00", title="Běh",
                                       distance_km=8.0 + (k % 4), duration_min=45, avg_hr=140, sport="running"))
    db_session.commit()
    act = db_session.query(models.Activity).filter_by(runner_id=rid).order_by(models.Activity.started_at.desc()).first()
    r = client.post(f"/api/runners/{rid}/shoes", json={"brand": "asics", "model": "Gel-Nimbus 26", "category": "cushioned",
                                                       "drop_mm": 8, "first_used": _day(200)})
    assert r.status_code == 200 and r.json()["shoes"][0]["brand"] == "ASICS"
    base = E.recompute_assessment(db_session, rid)["capacity"]["margins"]
    assert client.post(f"/api/runners/{rid}/shoes", json={"brand": "Altra", "model": "Escalante 4",
                                                          "first_activity_id": act.id}).status_code == 200
    out = client.get(f"/api/runners/{rid}/shoes").json()
    assert out["transition"]["name"] == "Altra Escalante 4" and out["rotation"]["n"] == 2
    assert out["shoes"][1]["first_used"] == act.started_at[:10] and out["shoes"][1]["drop_mm"] == 0
    cap = E.get_or_refresh_assessment(db_session, rid)["capacity"]
    assert cap["margins"]["runWeek"] < base["runWeek"]
    assert cap["channels"]["volume"]["margins"]["week"] < cap["channels"]["systemic"]["margins"]["week"]
    sid = out["shoes"][1]["id"]
    assert client.patch(f"/api/runners/{rid}/shoes/{sid}", json={"retired": True}).json()["transition"] is None
    assert client.post(f"/api/runners/{rid}/shoes", json={"brand": "Nike", "model": "X"}).status_code == 422
    # recognition without a model key: a clear "unavailable", never a crash
    monkeypatch.setattr(SH.llm, "available", lambda: False)
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 50).decode()
    rec = client.post(f"/api/runners/{rid}/shoes/recognize", json={"image": png}).json()
    assert rec["ok"] is False and rec["error"] == "unavailable"
    monkeypatch.setattr(SH.llm, "available", lambda: True)
    monkeypatch.setattr(SH.llm, "vision", lambda *a, **k: ('{"is_shoe": true, "brand": "saucony", "model": "Endorphin Speed 4", '
                                                         '"category": "racing", "drop_mm": 8, "carbon": false, "confidence": 0.7}', "m"))
    rec = client.post(f"/api/runners/{rid}/shoes/recognize", json={"image": png}).json()
    assert rec["ok"] and rec["suggestion"]["brand"] == "Saucony" and rec["suggestion"]["model"] == "Endorphin Speed 4"
    assert client.delete(f"/api/runners/{rid}/shoes/{sid}").json()["shoes"][0]["model"] == "Gel-Nimbus 26"


def test_novice_runner_gets_narrower_margins(client, db_session):
    rid = register(client, "nov012@test.cz", "Nováček", "runner").json()["runner_id"]
    for k in range(80, 0, -2):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", started_at=_day(k) + "T07:00:00", title="Běh",
                                       distance_km=6.0, duration_min=36, avg_hr=140, sport="running"))
    db_session.commit()
    m0 = E.recompute_assessment(db_session, rid)["capacity"]["margins"]
    client.patch(f"/api/runners/{rid}", json={"patch": {"running_since": _day(90)}})
    m1 = E.get_or_refresh_assessment(db_session, rid)["capacity"]["margins"]
    assert m1["experience"]["factor"] == 0.8 and m1["week"] == pytest.approx(m0["week"] * 0.8, abs=0.002)


def test_period_start_from_the_checkin(client, db_session):
    rid = register(client, "per012@test.cz", "Běžkyně", "runner").json()["runner_id"]
    client.patch(f"/api/runners/{rid}", json={"patch": {"sex": "f", "menstrual_json": {"track": True, "length": 29}}})
    client.post(f"/api/runners/{rid}/checkins", json={"pain_score": 0, "period_start": True})
    r = db_session.query(models.Runner).get(rid)
    db_session.refresh(r)
    assert r.menstrual_json["starts"] == [E.iso_date(E.today_date())]
