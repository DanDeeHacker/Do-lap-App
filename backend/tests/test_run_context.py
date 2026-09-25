"""Run context on Pohyb → Historie běhů: terrain + weather per run, and the
start time / place captured at import that the weather lookup needs."""
import urllib.parse
from datetime import timedelta

import pytest

from app import models
from app.metrics import engine as E
from app.metrics import run_context as RC
from app.metrics import weather as W
from .conftest import register


def _raw(temp=12.0, code=3):
    hours = [f"2026-09-20T{h:02d}:00" for h in range(24)]
    return {
        "hourly": {"time": hours, "temperature_2m": [temp + (h - 12) * 0.5 for h in range(24)],
                   "apparent_temperature": [temp - 2] * 24, "relative_humidity_2m": [70] * 24,
                   "precipitation": [0.2 if h == 8 else 0.0 for h in range(24)], "wind_speed_10m": [9] * 24,
                   "weather_code": [code if h != 8 else 61 for h in range(24)]},
        "daily": {"temperature_2m_max": [18.0], "temperature_2m_min": [6.0], "apparent_temperature_max": [17.0],
                  "precipitation_sum": [1.4], "wind_speed_10m_max": [22.0], "weather_code": [61]},
    }


@pytest.fixture()
def weather_on(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return {"results": [{"latitude": 50.0880, "longitude": 14.4208}]} if "geocoding" in url else _raw()
    monkeypatch.setenv("DOSSLAP_WEATHER", "on")
    monkeypatch.setattr(W, "_get_json", fake)
    W._GEO_CACHE.clear()
    return calls


def test_summary_covers_the_hours_of_the_run():
    w = W.summarize(_raw(), "07:30", 60)                  # 07:30–08:30 → hours 7 and 8
    assert w["precision"] == "hour" and w["tempC"] == round((12 - 2.5 + 12 - 2) / 2)
    assert w["precipMm"] == 0.2 and w["label"] == "slabý déšť"   # the worst weather during the run
    day = W.summarize(_raw(), None, 60)                    # no start time → day summary
    assert day["precision"] == "day" and (day["tMin"], day["tMax"]) == (6, 18) and day["precipMm"] == 1.4
    assert W.summarize({}, "07:00", 30) is None


def test_only_rounded_coordinates_leave_the_server(weather_on):
    today = E.today_date()
    W.fetch_day(50.0873, 14.4213, today - timedelta(days=3), today)
    W.fetch_day(50.0873, 14.4213, today - timedelta(days=300), today)
    q_recent = urllib.parse.parse_qs(urllib.parse.urlparse(weather_on[0]).query)
    assert q_recent["latitude"] == ["50.1"] and q_recent["longitude"] == ["14.4"]
    assert "api.open-meteo.com/v1/forecast" in weather_on[0]          # recent → forecast API
    assert "archive-api.open-meteo.com/v1/archive" in weather_on[1]   # older → archive


def test_commercial_key_switches_endpoint(weather_on, monkeypatch):
    monkeypatch.setenv("OPEN_METEO_API_KEY", "k123")
    W.fetch_day(50.1, 14.4, E.today_date(), E.today_date())
    assert "customer-api.open-meteo.com" in weather_on[0] and "apikey=k123" in weather_on[0]


def _runner_with_runs(client, db, email, **kw):
    rid = register(client, email, "Ctx Runner", "runner").json()["runner_id"]
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    runner.city = "Praha"
    prof = [{"distance_m": d, "altitude_m": 300 - (0.12 * d if 2000 <= d <= 3000 else 0) + (0.02 * d if d < 2000 else 40)}
            for d in range(0, 8001, 100)]
    for k, extra in enumerate(({"start_time": "07:40", "start_lat": 50.09, "start_lon": 14.42},
                               {"start_time": "18:05", "start_lat": 50.09, "start_lon": 14.42},
                               {})):
        db.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"{email}-{k}", started_at=E.day_ago(k and 1),
                               sport="running", title=f"Běh {k}", distance_km=8.0, duration_min=45, pace_s_km=337,
                               avg_hr=148, surface="trail", ascent_m=160, descent_m=150, elevation_profile=prof,
                               **extra, **kw))
    db.commit()
    return rid, runner


def test_enrich_groups_requests_and_falls_back_to_city(client, db_session, weather_on):
    rid, runner = _runner_with_runs(client, db_session, "ctx1@test.cz")
    runs = db_session.query(models.Activity).filter(models.Activity.runner_id == rid).all()
    n = W.enrich(db_session, runner, runs)
    assert n == 3
    forecast_calls = [u for u in weather_on if "geocoding" not in u]
    assert len(forecast_calls) == 2        # today@start place, yesterday@start place, yesterday@city = same grid → shared
    no_gps = next(a for a in runs if a.start_lat is None)
    assert no_gps.weather_json["place"] == "city" and no_gps.weather_json["city"] == "Praha"
    assert no_gps.weather_json["precision"] == "day"
    assert W.enrich(db_session, runner, runs) == 0   # stored → never fetched twice


def test_failures_and_disabled_store_nothing(client, db_session, monkeypatch):
    rid, runner = _runner_with_runs(client, db_session, "ctx2@test.cz")
    runs = db_session.query(models.Activity).filter(models.Activity.runner_id == rid).all()
    assert W.enrich(db_session, runner, runs) == 0   # DOSSLAP_WEATHER=off in tests
    monkeypatch.setenv("DOSSLAP_WEATHER", "on")

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(W, "_get_json", boom)
    W._GEO_CACHE.clear()
    assert W.enrich(db_session, runner, runs) == 0
    assert all(a.weather_json is None for a in runs)
    runner.city = None
    no_gps = next(a for a in runs if a.start_lat is None)
    assert RC._weather_note(no_gps, runner).startswith("Chybí místo běhu")   # a retry can't fix this one
    assert RC._weather_note(next(a for a in runs if a.start_lat), runner).endswith("zkusíme to znovu.")


def test_run_history_endpoint_has_terrain_and_weather(client, db_session, weather_on):
    rid, _ = _runner_with_runs(client, db_session, "ctx3@test.cz")
    client.post("/api/auth/session", json={"email": "ctx3@test.cz", "password": "testpass123"})
    rows = client.get(f"/api/runners/{rid}/run-history").json()
    assert len(rows) == 3
    r = next(x for x in rows if x["start_time"] == "07:40")
    t = r["terrain"]
    assert t["surfaceLabel"] == "terén" and t["ascPerKm"] == 20.0 and t["descPerKm"] == 18.8
    assert t["bucketLabel"].startswith("terén · ") and t["gradeLabel"] in ("rovina", "kopcovitě", "stoupání", "klesání")
    assert t["steepDescentPct"] and t["steepDescentPct"] > 50      # most of the drop is the steep 12 % section
    assert t["demand"] and t["demand"] > 1.0
    assert r["weather"]["precision"] == "hour" and r["weather"]["source"] == "Open-Meteo"
    # a stranger can't read someone else's run history
    register(client, "ctx3b@test.cz", "Stranger", "runner")
    client.post("/api/auth/session", json={"email": "ctx3b@test.cz", "password": "testpass123"})
    assert client.get(f"/api/runners/{rid}/run-history").status_code in (403, 404)


def test_import_captures_start_time_and_place():
    import garmin_ingest
    import garmin_live
    a = garmin_live.map_activity({"activityType": {"typeKey": "running"}, "distance": 8000, "duration": 2700,
                                  "startTimeLocal": "2026-09-20 07:41:12", "startLatitude": 50.08734,
                                  "startLongitude": 14.42131, "activityId": 1})
    assert (a["start_time"], a["start_lat"], a["start_lon"]) == ("07:41", 50.09, 14.42)
    ms = int(__import__("datetime").datetime(2026, 9, 20, 18, 5, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
    assert garmin_ingest.start_fields({"startTimeLocal": ms, "startLatitude": 49.1951, "startLongitude": 16.6068}) == \
        {"start_time": "18:05", "start_lat": 49.2, "start_lon": 16.61}


def test_resync_and_streams_backfill_start_context(client, db_session):
    from app.routers import integrations as I
    rid = register(client, "ctx4@test.cz", "Backfill", "runner").json()["runner_id"]
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="old1", started_at=E.day_ago(3),
                                   sport="running", distance_km=5.0, duration_min=30))
    db_session.commit()
    I._merge_seed(db_session, rid, {"activities": [{"external_id": "old1", "started_at": E.day_ago(3), "start_time": "06:30",
                                                     "start_lat": 50.1, "start_lon": 14.4, "distance_km": 99.0}]})
    a = db_session.query(models.Activity).filter_by(runner_id=rid, external_id="old1").first()
    assert (a.start_time, a.start_lat, a.distance_km) == ("06:30", 50.1, 5.0)   # context filled, data untouched
    b = models.Activity(runner_id=rid, provider="garmin", external_id="old2", started_at=E.day_ago(2), sport="running")
    I._backfill_start(b, [{"t_ms": 1758348000000}, {"lat": 49.19513, "lon": 16.60684, "t_ms": 1758348001000}])
    assert (b.start_lat, b.start_lon) == (49.2, 16.61) and b.start_time is not None


def test_heat_flag_only_when_the_run_hours_are_known(client, db_session, monkeypatch):
    rid, runner = _runner_with_runs(client, db_session, "ctx5@test.cz")
    hot = _raw(temp=30)
    hot["hourly"]["apparent_temperature"] = [31] * 24
    hot["daily"]["apparent_temperature_max"] = [33.0]
    monkeypatch.setenv("DOSSLAP_WEATHER", "on")
    monkeypatch.setattr(W, "_get_json", lambda url: {"results": [{"latitude": 50.09, "longitude": 14.42}]} if "geocoding" in url else hot)
    W._GEO_CACHE.clear()
    runs = db_session.query(models.Activity).filter(models.Activity.runner_id == rid).all()
    W.enrich(db_session, runner, runs)
    by_precision = {a.weather_json["precision"]: a.weather_json["hot"] for a in runs}
    assert by_precision == {"hour": True, "day": False}   # a hot afternoon says nothing about a morning run


# ---- comparable run a month ago (the comparison table in each expanded run) ----

def _act(rid, day, km=10.0, surface="road", dur=55, ext=None, **kw):
    return models.Activity(runner_id=rid, provider="garmin", external_id=ext or f"{rid}-{day}-{km}-{surface}-{dur}",
                           started_at=day, sport="running", distance_km=km, duration_min=dur * km / 10,
                           surface=surface, ascent_m=10, descent_m=10, **kw)


def test_month_before_is_calendar_aware():
    from datetime import date
    assert E.month_before(date(2026, 9, 25)) == date(2026, 8, 25)
    assert E.month_before(date(2026, 3, 31)) == date(2026, 2, 28)
    assert E.month_before(date(2026, 1, 15)) == date(2025, 12, 15)


def test_comparable_run_is_a_month_ago_never_older(client, db_session):
    rid = register(client, "cmp1@test.cz", "Cmp", "runner").json()["runner_id"]
    db = db_session
    run = _act(rid, "2026-09-25", cadence_spm=176, gct_ms=250)
    db.add_all([
        run,
        _act(rid, "2026-08-20", cadence_spm=170, gct_ms=262),                  # same kind, but 36 days old → never
        _act(rid, "2026-08-24", cadence_spm=171, gct_ms=261),                  # one day older than a month → never
        _act(rid, "2026-08-25", dur=40, cadence_spm=180, gct_ms=240),          # the mark, but a different pace class
        _act(rid, "2026-08-26", surface="trail", cadence_spm=168, gct_ms=270),  # different surface
        _act(rid, "2026-08-27", cadence_spm=174, gct_ms=255),                  # ✓ comparable, 2 days after the mark
        _act(rid, "2026-08-29", cadence_spm=173, gct_ms=256),                  # comparable but further from the mark
        _act(rid, "2026-09-10", cadence_spm=175, gct_ms=252),                  # too recent to be "a month ago"
    ])
    db.commit()
    res = E.run_compare(db, rid, run.id)
    assert res["prev"]["date"] == "2026-08-27" and res["prev"]["daysBefore"] == 29
    assert res["window"] == {"from": "2026-08-25", "to": "2026-09-01"}
    cad = next(m for m in res["metrics"] if m["key"] == "cadence_spm")
    assert (cad["value"], cad["prev"], cad["diff"]) == (176, 174, 2)


def test_comparable_run_tie_prefers_similar_distance_and_none_when_missing(client, db_session):
    rid = register(client, "cmp2@test.cz", "Cmp2", "runner").json()["runner_id"]
    db = db_session
    run = _act(rid, "2026-09-25", km=20.0, gct_ms=250)
    lonely = _act(rid, "2026-07-01", gct_ms=250)
    db.add_all([run, lonely, _act(rid, "2026-08-26", km=6.0, gct_ms=240), _act(rid, "2026-08-26", km=18.0, gct_ms=245)])
    db.commit()
    assert E.run_compare(db, rid, run.id)["prev"]["distanceKm"] == 18.0
    none = E.run_compare(db, rid, lonely.id)   # nothing between 1 and 8 June
    assert none["prev"] is None and all(m["prev"] is None and m["diff"] is None for m in none["metrics"])


# ---- per-segment test of any run in the history, vs the norm as of its own day ----

def test_historic_run_segments_use_the_baseline_of_their_own_day(client, db_session):
    import random
    random.seed(7)
    rid = register(client, "seghist@test.cz", "SegHist", "runner").json()["runner_id"]
    db = db_session

    def seg(band, gct, t):
        return {"band": band, "surface": "road", "durationS": 60, "meanSpeed": 3.0,
                "meanGradient": -0.12 if band == "B1" else 0.0, "elapsedS": t, "gct_ms": gct}

    def add(day, gct_down):
        a = _act(rid, E.day_ago(day), ext=f"sh{day}")
        db.add(a)
        db.flush()
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id, created_at=E.now_iso(),
                                     segments_json=[seg("B3", 240 + random.gauss(0, 4), 0), seg("B1", gct_down, 60)]))
        return a
    for day in range(130, 80, -6):              # the norm back then: downhill contact ~232 ms
        add(day, 232 + random.gauss(0, 4))
    old = add(50, 262)                          # the run in question: +30 ms downhill
    for day in range(44, 26, -3):               # afterwards the runner stays at ~262 ms
        add(day, 262 + random.gauss(0, 4))
    db.commit()
    res = E.run_segment_test(db, rid, old.id)
    assert res["available"] and res["baseline"]["runs"] >= 5
    assert res["baseline"]["to"] == E.iso_date(E.today_date() - timedelta(days=50 + 29))   # 29 days before the run
    down = next(s for s in res["run"]["segments"] if s["band"] == "B1")
    assert down["sig"] and down["startS"] == 60 and down["durationS"] == 60 and down["paceSKm"] == 333
    assert down["gradePct"] == -12.0
    # judged by TODAY's norm (which already contains ~262 ms runs) it would not stand out
    today_view = E.segment_significance(db, rid, n_runs=20)
    same = next(r for r in today_view["runs"] if r["aid"] == old.id)
    assert not next(s for s in same["segments"] if s["band"] == "B1")["sig"]


def test_run_segments_endpoint(client, db_session):
    rid, _ = _runner_with_runs(client, db_session, "ctx6@test.cz")
    client.post("/api/auth/session", json={"email": "ctx6@test.cz", "password": "testpass123"})
    aid = db_session.query(models.Activity).filter(models.Activity.runner_id == rid).first().id
    assert client.get(f"/api/runners/{rid}/run-segments/{aid}").json() == {"available": False, "reason": "no_stream"}
    r = client.get(f"/api/runners/{rid}/run-compare/{aid}").json()
    assert "window" in r and "prev" in r and "baseNow" not in (r["metrics"] or [{}])[0]
