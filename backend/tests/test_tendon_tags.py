"""Suggestions #7 and #10 (owner request 2026-10-05): the morning tendon test (the 24-hour
response of the pain-monitoring model) and the evening tags with their personal effect on
the night (HRV, resting heart rate, sleep)."""
import math
import random
from datetime import date, timedelta

from app import models
from app.metrics import data as D
from app.metrics import day_tags as DT
from app.metrics import engine as E
from app.metrics import tendon as TD

from .conftest import register

TODAY = date(2026, 10, 5)
ACH = [{"region": "Achillova šlacha (P)", "side": "P", "kind": "tendon"}]


def _pin(monkeypatch, d=TODAY):
    monkeypatch.setattr(E, "today_date", lambda: d)


def _run(db, rid, day: date, pain=None, points=None, km=8.0):
    a = models.Activity(runner_id=rid, started_at=f"{day.isoformat()}T07:00:00", sport="running", distance_km=km,
                        duration_min=km * 6, title="Běh")
    db.add(a)
    db.flush()
    if pain is not None:
        db.add(models.ActivityFeedback(activity_id=a.id, runner_id=rid, submitted_at=f"{day.isoformat()}T09:00:00",
                                       pain_during=pain, pain_points=points or []))
    return a


def _test(db, rid, day: date, pain, site="achilles", side="P"):
    db.add(models.TendonCheck(runner_id=rid, date=day.isoformat(), site=site, side=side, test=TD.TENDONS[site]["test"],
                              pain=pain, submitted_at=f"{day.isoformat()}T06:30:00"))


def _verdict(db, rid, site="achilles", side="P", today=TODAY):
    db.commit()
    return TD.verdict(D.load_runner_data(db, rid, priors=False), today, site, side)


def test_tendon_regions_and_watch_list(client, db_session):
    assert TD.tendon_of("Achillova šlacha (P)") == ("achilles", "P")
    assert TD.tendon_of("Patelární šlacha", "left") == ("patellar", "L")
    assert TD.tendon_of("Lýtko (gastrocnemius) (P)") is None
    rid = register(client, "tnd1@test.cz", "Šlacha", "runner").json()["runner_id"]
    _run(db_session, rid, TODAY - timedelta(days=1), pain=3, points=ACH)
    db_session.commit()
    data = D.load_runner_data(db_session, rid, priors=False)
    assert TD.watched(data, TODAY) == [("achilles", "P")]
    assert TD.watched(data, TODAY + timedelta(days=8)) == []         # quiet after a week without a mark or a test
    c = TD.card(data, TODAY)
    assert c and not c["allDone"] and c["items"][0]["testName"] == "10 výponů na jedné noze"


def test_the_morning_after_a_run_against_the_baseline(client, db_session):
    rid = register(client, "tnd2@test.cz", "Šlacha", "runner").json()["runner_id"]
    y = TODAY - timedelta(days=1)
    _run(db_session, rid, y, pain=3, points=ACH)
    _test(db_session, rid, y, 2)                                    # the run day's morning = the baseline
    _test(db_session, rid, TODAY, 4)
    v = _verdict(db_session, rid)
    assert v["state"] == "red" and v["baseline"] == 2 and v["during"] == 3 and v["ran"]
    m = TD.monitor(D.load_runner_data(db_session, rid, priors=False), rid, TODAY)
    assert m["morningWorse"]["source"] == "tendonTest" and m["morningWorse"]["morning"] == 4
    row = db_session.query(models.TendonCheck).filter_by(runner_id=rid, date=TODAY.isoformat()).first()
    row.pain = 3
    assert _verdict(db_session, rid)["state"] == "amber"            # 1 point worse: hold
    row.pain = 2
    v = _verdict(db_session, rid)
    assert v["state"] == "green" and "snesla" in v["text"]
    assert TD.monitor(D.load_runner_data(db_session, rid, priors=False), rid, TODAY)["morningWorse"] is None


def test_over_five_and_over_five_during_the_run(client, db_session):
    rid = register(client, "tnd3@test.cz", "Šlacha", "runner").json()["runner_id"]
    _test(db_session, rid, TODAY - timedelta(days=2), 3)
    _test(db_session, rid, TODAY, 6)                                # no run yesterday, but over the limit
    v = _verdict(db_session, rid)
    assert v["state"] == "red" and not v["ran"]
    m = TD.monitor(D.load_runner_data(db_session, rid, priors=False), rid, TODAY)["morningWorse"]
    assert m and m["runDate"] is None
    rid2 = register(client, "tnd3b@test.cz", "Šlacha", "runner").json()["runner_id"]
    y = TODAY - timedelta(days=1)
    _run(db_session, rid2, y, pain=7, points=ACH)
    _test(db_session, rid2, y, 2)
    _test(db_session, rid2, TODAY, 2)
    v = _verdict(db_session, rid2)
    assert v["state"] == "amber" and "7/10" in v["text"]            # settled, but the run went over 5/10


def test_tests_rising_week_to_week(client, db_session):
    rid = register(client, "tnd4@test.cz", "Šlacha", "runner").json()["runner_id"]
    for k, p in ((12, 1), (10, 1), (8, 2), (5, 3), (3, 3), (0, 3)):
        _test(db_session, rid, TODAY - timedelta(days=k), p)
    v = _verdict(db_session, rid)
    assert v["trend"] and v["trend"]["now"] == 3.0 and v["state"] == "amber"
    assert TD.monitor(D.load_runner_data(db_session, rid, priors=False), rid, TODAY)["trend"]["source"] == "tendonTest"


def test_the_api_saves_and_the_engine_stops_running(client, db_session, monkeypatch):
    _pin(monkeypatch)
    rid = register(client, "tnd5@test.cz", "Šlacha", "runner").json()["runner_id"]
    y = TODAY - timedelta(days=1)
    _run(db_session, rid, y, pain=3, points=ACH)
    _test(db_session, rid, y, 1)
    db_session.commit()
    assert client.post(f"/api/runners/{rid}/tendon-checks", json={"site": "hamstring", "pain": 2}).status_code == 422
    assert client.post(f"/api/runners/{rid}/tendon-checks", json={"site": "achilles", "side": "P", "pain": 11}).status_code == 422
    r = client.post(f"/api/runners/{rid}/tendon-checks", json={"site": "achilles", "side": "P", "pain": 4, "stiffness": 1})
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["done"] and it["state"] == "red" and it["stiffness"] == 1 and len(it["log"]) == TD.LOG_DAYS
    # the same morning again replaces the answer
    client.post(f"/api/runners/{rid}/tendon-checks", json={"site": "achilles", "side": "P", "pain": 3})
    assert db_session.query(models.TendonCheck).filter_by(runner_id=rid, date=TODAY.isoformat()).count() == 1
    client.post(f"/api/runners/{rid}/tendon-checks", json={"site": "achilles", "side": "P", "pain": 4})
    pm = E.pain_monitor(db_session, rid)
    assert pm and pm["morningWorse"]["source"] == "tendonTest" and pm["morningWorse"]["baseline"] == 1
    db_session.expire_all()
    a = E.get_or_refresh_assessment(db_session, rid)
    assert (a.get("painMonitor") or {}).get("morningWorse", {}).get("source") == "tendonTest"


# ---------------------------------------------------------------- evening tags
def _nights(db, rid, n=70, tag=None, tag_days=(), hard_days=(), hrv_tag=1.0, rhr_tag=0.0, hrv_hard=1.0, seed=1):
    """n days of nights; the evening of each day answered; `tag` on `tag_days`."""
    rnd = random.Random(seed)
    start = TODAY - timedelta(days=n)
    for k in range(n + 1):
        d = start + timedelta(days=k)
        prev = (d - timedelta(days=1)).isoformat()
        f_hrv = (hrv_tag if prev in tag_days else 1.0) * (hrv_hard if prev in hard_days else 1.0)
        db.add(models.DailyMetric(runner_id=rid, date=d.isoformat(), hrv_ms=60 * f_hrv * math.exp(rnd.gauss(0, 0.05)),
                                  resting_hr=50 + (rhr_tag if prev in tag_days else 0) + rnd.gauss(0, 1.0),
                                  sleep_h=7.5 + rnd.gauss(0, 0.3)))
        if k < n:
            db.add(models.DayTag(runner_id=rid, date=d.isoformat(), tags=[tag] if (tag and d.isoformat() in tag_days) else []))
            if d.isoformat() in hard_days:
                db.add(models.Activity(runner_id=rid, started_at=f"{d.isoformat()}T17:00:00", sport="running",
                                       distance_km=15, duration_min=80, training_load=300, title="Tvrdý běh"))
            else:
                db.add(models.Activity(runner_id=rid, started_at=f"{d.isoformat()}T17:00:00", sport="running",
                                       distance_km=6, duration_min=35, training_load=50, title="Lehký běh"))
    db.commit()


def test_a_tag_with_a_real_effect_is_found(client, db_session):
    rid = register(client, "tag1@test.cz", "Štítky", "runner").json()["runner_id"]
    days = [(TODAY - timedelta(days=k)).isoformat() for k in range(5, 60, 6)]      # 10 evenings
    _nights(db_session, rid, tag="alcohol_more", tag_days=days, hrv_tag=0.85, rhr_tag=3.0)
    ins = {x["key"]: x for x in DT.insights(db_session, rid, TODAY)}
    al = ins["alcohol_more"]
    assert al["status"] == "clear" and al["worse"] and al["n"] == 10
    hrv, rhr, sl = al["effects"]["hrv"], al["effects"]["rhr"], al["effects"]["sleep"]
    assert hrv["status"] == "clear" and -22 < hrv["value"] < -8 and hrv["lo"] < hrv["value"] < hrv["hi"] < 0
    assert rhr["status"] == "clear" and 1.5 < rhr["value"] < 4.5
    assert sl["status"] != "clear"
    assert "HRV o" in al["text"] and "nocí" in al["text"]
    assert ins["sauna"]["status"] == "collecting" and ins["sauna"]["n"] == 0


def test_training_load_is_not_blamed_on_the_tag(client, db_session):
    """A sauna only after hard sessions: the hard session lowers HRV, not the sauna."""
    rid = register(client, "tag2@test.cz", "Štítky", "runner").json()["runner_id"]
    hard = [(TODAY - timedelta(days=k)).isoformat() for k in range(3, 66, 3)]          # 21 hard days
    sauna = hard[::3]                                                                 # 7 of them with a sauna
    _nights(db_session, rid, tag="sauna", tag_days=sauna, hard_days=hard, hrv_hard=0.85, seed=3)
    s = next(x for x in DT.insights(db_session, rid, TODAY) if x["key"] == "sauna")
    assert s["n"] == 7 and s["effects"]["hrv"]["status"] != "clear"
    assert abs(s["effects"]["hrv"]["value"]) < 8


def test_unanswered_evenings_dont_count_and_the_api(client, db_session, monkeypatch):
    _pin(monkeypatch)
    rid = register(client, "tag3@test.cz", "Štítky", "runner").json()["runner_id"]
    for k in range(1, 40):
        db_session.add(models.DailyMetric(runner_id=rid, date=(TODAY - timedelta(days=k)).isoformat(), hrv_ms=60, resting_hr=50, sleep_h=7.5))
    db_session.commit()
    r = client.put(f"/api/runners/{rid}/day-tags", json={"tags": ["alcohol", "alcohol_more", "bogus", "stress"]})
    assert r.status_code == 200 and r.json()["tags"] == ["alcohol_more", "stress"]
    assert client.put(f"/api/runners/{rid}/day-tags",
                      json={"date": (TODAY - timedelta(days=3)).isoformat(), "tags": []}).status_code == 422
    y = (TODAY - timedelta(days=1)).isoformat()
    client.put(f"/api/runners/{rid}/day-tags", json={"date": y, "tags": ["late_meal"]})
    ev = client.get(f"/api/runners/{rid}/day-tags").json()
    assert ev["tags"] == ["alcohol_more", "stress"] and len(ev["options"]) == len(DT.TAGS)
    # one answered evening with its night (yesterday → tonight is not here yet): only that one counts
    rows = DT.nights(db_session, rid, TODAY)
    assert [x["d"] for x in rows] == []                                # tonight's night (dated tomorrow) isn't there
    db_session.add(models.DailyMetric(runner_id=rid, date=TODAY.isoformat(), hrv_ms=50, resting_hr=53, sleep_h=6.5))
    db_session.commit()
    rows = DT.nights(db_session, rid, TODAY)
    assert [x["d"] for x in rows] == [y] and rows[0]["rhr"] == 3.0
    ln = DT.last_night(db_session, rid, TODAY)
    assert ln["items"][0]["key"] == "late_meal" and ln["now"]["hrv"] == -17 and ln["now"]["sleep"] == -60
    assert DT.note_last_night(ln).startswith("Včera: pozdní jídlo.")
