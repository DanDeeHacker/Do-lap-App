"""Weather context for runs (Pohyb → Historie běhů).

Historical weather from Open-Meteo at the run's start place and time: air and
feels-like temperature, humidity, wind, precipitation and conditions — averaged
over the hours the run lasted when the start time is known, else a day summary.
Stored once per run on Activity.weather_json.

Privacy: only coordinates rounded to 0.1° (~10 km) and the date leave the server
— enough for weather, useless for locating a runner's home. When a run has no
GPS start, the runner's profile city is geocoded instead (marked approximate).
Licence: Open-Meteo's free API is for non-commercial use; set OPEN_METEO_API_KEY
to use their commercial endpoints. DOSSLAP_WEATHER=off disables all lookups
(tests, offline review environments).
"""
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import engine as E

HOURLY = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,weather_code"
DAILY = ("temperature_2m_max,temperature_2m_min,apparent_temperature_max,precipitation_sum,"
         "wind_speed_10m_max,weather_code")
TIMEOUT_S = 6
RECENT_DAYS = 60     # the archive lags a few days; recent dates come from the forecast API
GRID = 1             # decimals of the coordinates that leave the server (0.1° ≈ 10 km)
MAX_WORKERS = 6
HOT_FEELS_C = 24     # above this, a higher heart rate at the usual pace is expected

# WMO weather codes → (Czech label, icon)
WMO = {
    0: ("jasno", "☀"), 1: ("skoro jasno", "🌤"), 2: ("polojasno", "⛅"), 3: ("zataženo", "☁"),
    45: ("mlha", "🌫"), 48: ("mlha s námrazou", "🌫"),
    51: ("slabé mrholení", "🌦"), 53: ("mrholení", "🌦"), 55: ("husté mrholení", "🌧"),
    56: ("mrznoucí mrholení", "🌧"), 57: ("mrznoucí mrholení", "🌧"),
    61: ("slabý déšť", "🌦"), 63: ("déšť", "🌧"), 65: ("silný déšť", "🌧"),
    66: ("mrznoucí déšť", "🌧"), 67: ("mrznoucí déšť", "🌧"),
    71: ("slabé sněžení", "🌨"), 73: ("sněžení", "🌨"), 75: ("silné sněžení", "🌨"), 77: ("sněhová zrna", "🌨"),
    80: ("přeháňky", "🌦"), 81: ("přeháňky", "🌧"), 82: ("silné přeháňky", "🌧"),
    85: ("sněhové přeháňky", "🌨"), 86: ("sněhové přeháňky", "🌨"),
    95: ("bouřka", "⛈"), 96: ("bouřka s kroupami", "⛈"), 99: ("bouřka s kroupami", "⛈"),
}


def enabled() -> bool:
    return os.environ.get("DOSSLAP_WEATHER", "on").strip().lower() not in ("off", "0", "false", "no")


def _get_json(url: str):
    """The only network call in this module (tests replace it)."""
    req = urllib.request.Request(url, headers={"User-Agent": "dosslap/1.0 (running load monitoring)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _endpoint(day: date, today: date) -> tuple[str, str | None]:
    key = os.environ.get("OPEN_METEO_API_KEY") or None
    recent = (today - day).days <= RECENT_DAYS
    host = ("api.open-meteo.com/v1/forecast" if recent else "archive-api.open-meteo.com/v1/archive")
    if key:
        host = "customer-" + host
    return f"https://{host}", key


def fetch_day(lat: float, lon: float, day: date, today: date | None = None):
    """Raw Open-Meteo response for one place and day, or None on any failure."""
    today = today or E.today_date()
    url, key = _endpoint(day, today)
    q = {"latitude": round(lat, GRID), "longitude": round(lon, GRID), "start_date": day.isoformat(),
         "end_date": day.isoformat(), "hourly": HOURLY, "daily": DAILY, "timezone": "Europe/Prague",
         "wind_speed_unit": "kmh"}
    if key:
        q["apikey"] = key
    for attempt in range(2):   # one retry: a burst of parallel requests is occasionally refused
        try:
            return _get_json(url + "?" + urllib.parse.urlencode(q))
        except Exception:  # noqa: BLE001 — network / quota / bad payload: just no weather
            if attempt == 0:
                time.sleep(0.4)
    return None


def _code(c):
    label, icon = WMO.get(int(c), ("—", "·")) if c is not None else ("—", "·")
    return int(c) if c is not None else None, label, icon


def _r(v, nd=0):
    return None if v is None else (round(v, nd) if nd else round(v))


def summarize(raw: dict, start_time: str | None, duration_min: float | None):
    """Weather during the run (hour-level when the start time is known) or the
    day summary. None when the payload has nothing usable."""
    if not raw:
        return None
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    if start_time and times:
        try:
            h0, m0 = (int(x) for x in start_time.split(":"))
        except ValueError:
            h0, m0 = None, None
        if h0 is not None:
            start = h0 + m0 / 60
            end = start + max(duration_min or 30, 1) / 60
            idx = [i for i, t in enumerate(times) if start - 0.5 <= int(t[11:13]) <= end]
            if idx:
                def avg(key):
                    vals = [hourly.get(key, [None] * len(times))[i] for i in idx]
                    vals = [v for v in vals if v is not None]
                    return sum(vals) / len(vals) if vals else None

                def total(key):
                    vals = [hourly.get(key, [None] * len(times))[i] for i in idx]
                    return sum(v for v in vals if v is not None)
                codes = [hourly.get("weather_code", [None] * len(times))[i] for i in idx]
                code, label, icon = _code(max((c for c in codes if c is not None), default=None))
                out = {"precision": "hour", "tempC": _r(avg("temperature_2m")), "feelsC": _r(avg("apparent_temperature")),
                       "humidity": _r(avg("relative_humidity_2m")), "windKmh": _r(avg("wind_speed_10m")),
                       "precipMm": round(total("precipitation"), 1), "code": code, "label": label, "icon": icon}
                if out["tempC"] is not None:
                    return out
    daily = raw.get("daily") or {}

    def first(key):
        v = daily.get(key) or []
        return v[0] if v else None
    if first("temperature_2m_max") is None:
        return None
    code, label, icon = _code(first("weather_code"))
    return {"precision": "day", "tMin": _r(first("temperature_2m_min")), "tMax": _r(first("temperature_2m_max")),
            "feelsC": _r(first("apparent_temperature_max")), "windKmh": _r(first("wind_speed_10m_max")),
            "precipMm": _r(first("precipitation_sum"), 1) or 0.0, "code": code, "label": label, "icon": icon}


_GEO_CACHE: dict = {}


def geocode_city(city: str):
    """(lat, lon) of a Czech-first city name via Open-Meteo geocoding; cached."""
    key = (city or "").strip().lower()
    if not key:
        return None
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    q = urllib.parse.urlencode({"name": city, "count": 1, "language": "cs", "format": "json"})
    try:
        res = (_get_json("https://geocoding-api.open-meteo.com/v1/search?" + q) or {}).get("results") or []
    except Exception:  # noqa: BLE001 — transient: not cached, retried next time
        return None
    val = (res[0]["latitude"], res[0]["longitude"]) if res else None
    _GEO_CACHE[key] = val
    return val


def enrich(db, runner, activities, limit: int = 20) -> int:
    """Fetch and store weather for the given activities that don't have it yet.
    One request per (rounded place, day), in parallel. Returns how many runs got
    weather. Failures leave the run without weather (retried next time)."""
    if not enabled():
        return 0
    today = E.today_date()
    todo = [a for a in activities if a.weather_json is None and a.started_at and a.started_at[:10] <= today.isoformat()][:limit]
    if not todo:
        return 0
    city_ll = None
    plan = {}
    for a in todo:
        if a.start_lat is not None and a.start_lon is not None:
            lat, lon, place = a.start_lat, a.start_lon, "start"
        else:
            if city_ll is None and runner is not None and runner.city:
                city_ll = geocode_city(runner.city) or False
            if not city_ll:
                continue
            lat, lon, place = city_ll[0], city_ll[1], "city"
        key = (round(lat, GRID), round(lon, GRID), a.started_at[:10])
        plan.setdefault(key, []).append((a, place))
    if not plan:
        return 0
    keys = list(plan)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(keys))) as ex:
        raws = list(ex.map(lambda k: fetch_day(k[0], k[1], date.fromisoformat(k[2]), today), keys))
    done = 0
    stamp = datetime.now(E.LOCAL_TZ).isoformat(timespec="seconds")
    for k, raw in zip(keys, raws):
        for a, place in plan[k]:
            w = summarize(raw, a.start_time, a.duration_min)
            if w is None:
                continue
            w.update({"source": "Open-Meteo", "place": place, "city": runner.city if (place == "city" and runner) else None,
                      "hot": w["precision"] == "hour" and (w.get("feelsC") or -99) >= HOT_FEELS_C,  # a day's peak says nothing about a morning run
                      "fetchedAt": stamp})
            a.weather_json = w
            done += 1
    if done:
        db.commit()
    return done
