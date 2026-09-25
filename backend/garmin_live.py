"""Direct Garmin Connect download via the bundled `garminconnect` library
(python-garminconnect-master), the live counterpart to garmin_ingest.py's
file import. The runner enters their Garmin Connect e-mail + password once;
we log in, pull running activities and recent daily wellness, map them into
the platform's activity/daily schema and hand the result to the same
integrations._apply_seed() path every other importer uses.

Credentials are used only for this one login and are never stored or logged
(garminconnect logging is silenced below). Two-factor (MFA) accounts aren't
supported by this one-shot flow — they raise MfaRequired and the caller
points the user at the file export instead.

Unit note: the Connect *API* returns metres/seconds and camelCase field
names — different from the GDPR export's centimetre/millisecond encoding in
garmin_ingest.py — so this has its own mapping rather than reusing that one.
"""
import base64
import hashlib
import logging
import os
from datetime import date, timedelta

logging.getLogger("garminconnect").setLevel(logging.CRITICAL)

_SURFACE = {"trail_running": "trail", "treadmill_running": "treadmill", "track_running": "track"}
# Garmin activityType.typeKey → our cross-training sport. Running is handled
# separately (full mechanics); these carry only load / duration / HR.
_SPORT = {
    "cycling": "cycling", "road_biking": "cycling", "mountain_biking": "cycling",
    "indoor_cycling": "cycling", "virtual_ride": "cycling", "gravel_cycling": "cycling",
    "lap_swimming": "swimming", "open_water_swimming": "swimming", "swimming": "swimming",
    "strength_training": "strength", "rowing": "rowing", "indoor_rowing": "rowing",
    "elliptical": "elliptical", "hiking": "hiking", "walking": "walking",
}


def _sport_of(tk: str) -> str:
    if "running" in tk:
        return "running"
    for key, s in _SPORT.items():
        if key in tk:
            return s
    if "cycl" in tk or "biking" in tk:
        return "cycling"
    if "swim" in tk:
        return "swimming"
    if "strength" in tk:
        return "strength"
    if "row" in tk:
        return "rowing"
    if "walk" in tk:
        return "walking"
    if "hik" in tk:
        return "hiking"
    return "other"


class GarminLiveError(Exception):
    pass


class AuthError(GarminLiveError):
    pass


class MfaRequired(GarminLiveError):
    pass


def _r(v, nd=None):
    if v is None:
        return None
    return round(v, nd) if nd is not None else round(v)


def _pos(v, nd=None):
    """Like _r, but treats 0 / negative as a *missing* reading rather than a
    real value. Running-dynamics fields (cadence, GCT, oscillation, vertical
    ratio, HR, balance) can't legitimately be 0 during a run — a 0 means the
    sensor (pod / wrist) didn't capture it that session, so store None and let
    the engine skip it instead of dragging that metric's average toward zero."""
    if v is None or v <= 0:
        return None
    return round(v, nd) if nd is not None else round(v)


def map_activity(a: dict) -> dict | None:
    """One Garmin Connect activity summary → platform activity dict, or None
    if it's not a real run. Distances are metres, durations seconds here."""
    tk = ((a.get("activityType") or {}).get("typeKey") or "").lower()
    sport = _sport_of(tk)
    dist_m = a.get("distance") or 0
    dur_s = a.get("duration") or 0
    tl = a.get("activityTrainingLoad")
    if tl is None:
        tl = a.get("trainingLoad")
    if sport != "running":
        # Cross-training: only what feeds systemic load — no running mechanics.
        if dur_s < 600:                        # drop trivial < 10 min entries
            return None
        km = dist_m / 1000 if dist_m else None
        return {
            "provider": "garmin", "external_id": str(a.get("activityId")),
            "started_at": (a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:10],
            "title": a.get("activityName") or sport, "sport": sport,
            "distance_km": round(km, 2) if km else None,
            "duration_min": round(dur_s / 60, 1),
            "avg_hr": _pos(a.get("averageHR")),
            "training_load": _r(tl, 0),
        }
    if dist_m < 800 or dur_s < 240:            # drop warm-ups / GPS errors
        return None
    km = dist_m / 1000
    strd = a.get("avgStrideLength")            # cm on the Connect API
    return {
        "provider": "garmin", "external_id": str(a.get("activityId")),
        "started_at": (a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:10],
        "title": a.get("activityName") or "Běh", "sport": "running",
        "distance_km": round(km, 2), "duration_min": round(dur_s / 60, 1),
        "pace_s_km": round(dur_s / km) if km else None,
        "avg_hr": _pos(a.get("averageHR")),
        "surface": _SURFACE.get(tk, "road"),
        "ascent_m": _r(a.get("elevationGain")),
        "descent_m": _r(a.get("elevationLoss")),
        "temp_c": _r(a.get("minTemperature"), 0),
        "cadence_spm": _pos(a.get("averageRunningCadenceInStepsPerMinute")),
        "stride_len_m": _pos((strd / 100) if strd else None, 2),
        "vert_osc_cm": _pos(a.get("avgVerticalOscillation"), 1),
        "vert_ratio_pct": _pos(a.get("avgVerticalRatio"), 1),
        "gct_ms": _pos(a.get("avgGroundContactTime")),
        # Balance IS sometimes populated on the Connect API (with a pod/strap);
        # unlike the wrist FIT it's not always empty, so map it when present.
        "gct_balance_l": _pos(a.get("avgGroundContactBalance"), 1),
        "training_load": _r(tl, 0),
        "vo2max": _r(a.get("vO2MaxValue"), 1),
    }


def _sleep_eff(v: dict):
    """Sleep efficiency = total sleep / (total sleep + awake time), 0-1.
    Approximates TST / time-in-bed from the fields the sleep API exposes."""
    tst = v.get("totalSleepTimeInSeconds") or v.get("sleepTimeSeconds")
    awake = v.get("awakeTime")
    if awake is None:
        awake = v.get("awakeSleepSeconds")
    if tst and awake is not None and (tst + awake) > 0:
        return round(tst / (tst + awake), 3)
    return None


def map_daily(cdate: str, summary: dict | None, sleep: dict | None, hrv: dict | None) -> dict | None:
    """Per-day wellness → platform daily_metrics row (only fields present)."""
    row = {"date": cdate, "source": "garmin"}
    if summary:
        if summary.get("restingHeartRate") is not None:
            row["resting_hr"] = _r(summary.get("restingHeartRate"))
        if summary.get("totalSteps") is not None:
            row["steps"] = int(summary["totalSteps"])
    if sleep:
        dto = sleep.get("dailySleepDTO") or {}
        secs = dto.get("sleepTimeSeconds")
        if secs:
            row["sleep_h"] = round(secs / 3600, 1)
        eff = _sleep_eff(dto)
        if eff is not None:
            row["sleep_efficiency"] = eff
    if hrv:
        avg = (hrv.get("hrvSummary") or {}).get("lastNightAvg") or (hrv.get("hrvSummary") or {}).get("weeklyAvg")
        if avg is not None:
            row["hrv_ms"] = _r(avg, 1)
    return row if len(row) > 2 else None


def assemble_seed(activities: list[dict], daily_rows: list[dict], device: str = "Garmin") -> dict:
    activities = sorted(activities, key=lambda a: a["started_at"])
    daily_rows = sorted(daily_rows, key=lambda d: d["date"])

    def cov(field):
        vals = [a for a in activities if a.get(field) is not None]
        return round(len(vals) / len(activities) * 100) if activities else 0

    return {
        "activities": activities, "daily_metrics": daily_rows, "activity_feedback": [],
        "runners": [{"device": device}],
        "_meta": {
            "source": "garmin_live", "n_activities": len(activities), "daily": len(daily_rows),
            "first_run": activities[0]["started_at"] if activities else None,
            "last_run": activities[-1]["started_at"] if activities else None,
            "coverage_pct": {
                "vert_ratio_pct": cov("vert_ratio_pct"), "gct_ms": cov("gct_ms"),
                "gct_balance_l": cov("gct_balance_l"), "avg_hr": cov("avg_hr"),
            },
        },
    }


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def _ensure_profile(garmin) -> None:
    """With return_on_mfa=True the library returns from login() *before*
    loading the profile — even on a clean, no-MFA login — so display_name
    stays None and every later API call builds a URL with 'None' and 403s.
    Load it explicitly on the clean path (the MFA resume path already does)."""
    if getattr(garmin, "display_name", None):
        return
    loader = getattr(garmin, "_load_profile_and_settings", None)
    if callable(loader):
        loader()


def begin_login(email: str, password: str):
    """Start a login. Returns (garmin, needs_mfa, client_state). When
    needs_mfa is True the caller must keep `garmin` + `client_state` and call
    resume_login() with the code; the same Garmin object (its session
    cookies) is required to finish. Raises AuthError on bad credentials."""
    from garminconnect import Garmin, GarminConnectAuthenticationError
    try:
        garmin = Garmin(email=email, password=password, return_on_mfa=True)
        mfa_status, client_state = garmin.login()
    except GarminConnectAuthenticationError as e:
        raise AuthError(str(e))
    except Exception as e:
        raise GarminLiveError(str(e))
    needs_mfa = (mfa_status == "needs_mfa")
    if not needs_mfa:
        try:
            _ensure_profile(garmin)
        except GarminConnectAuthenticationError as e:
            raise AuthError(str(e))
        except Exception as e:
            raise GarminLiveError(str(e))
    return garmin, needs_mfa, client_state


def resume_login(garmin, client_state, mfa_code: str) -> None:
    """Finish an MFA login with the code. Raises AuthError if the code is
    wrong or the session has expired."""
    from garminconnect import GarminConnectAuthenticationError
    try:
        garmin.resume_login(client_state, mfa_code)
        _ensure_profile(garmin)
    except GarminConnectAuthenticationError as e:
        raise AuthError(str(e))
    except Exception as e:
        raise AuthError(str(e))


def _index(rows, val_fn, date_key="calendarDate"):
    out = {}
    for r in rows or []:
        d = r.get(date_key)
        if not d:
            continue
        v = val_fn(r)
        if v is not None:
            out[d] = v
    return out


def download_seed(garmin, activity_days: int = 180,
                  skip_dates: frozenset = frozenset(), since_date: str | None = None) -> dict:
    """Download from an already-logged-in Garmin object. Daily wellness (HRV,
    resting HR, sleep, steps) is pulled with the *range* endpoints — one call
    each, auto-chunked by the library — so it covers the whole history cheaply
    instead of a per-day loop that previously only reached ~6 weeks back (why
    older HRV was missing). Incremental: `skip_dates` are days we already have
    (skipped), `since_date` starts the activity window at our last activity."""
    end = date.today()
    start = end - timedelta(days=activity_days)
    if since_date:
        try:
            sd = date.fromisoformat(since_date[:10])
            if sd > start:
                start = sd
        except ValueError:
            pass
    s_iso, e_iso = start.isoformat(), end.isoformat()

    try:
        # No type filter — pull every sport; map_activity tags running (full
        # mechanics) vs. cross-training (load only) and drops trivial entries.
        raw = garmin.get_activities_by_date(s_iso, e_iso) or []
    except Exception as e:  # surface a real auth/connection failure instead of a silent empty import
        raise GarminLiveError(str(e))
    activities = [m for a in raw if (m := map_activity(a))]

    rhr = _index(_safe(garmin.get_rhr_daily, s_iso, e_iso), lambda r: r.get("value"))
    steps = _index(_safe(garmin.get_daily_steps, s_iso, e_iso), lambda r: r.get("totalSteps"))
    hrv_resp = _safe(garmin.get_hrv_data_range, s_iso, e_iso)
    hrv_list = hrv_resp.get("hrvSummaries") if isinstance(hrv_resp, dict) else None
    hrv = _index(hrv_list, lambda r: r.get("lastNightAvg") or r.get("weeklyAvg"))
    sleep_raw = _safe(garmin.get_sleep_daily, s_iso, e_iso)
    sleep = _index(sleep_raw, lambda r: (r.get("values") or {}).get("totalSleepTimeInSeconds"))
    sleep_eff = _index(sleep_raw, lambda r: _sleep_eff(r.get("values") or {}))

    daily_rows = []
    for d in sorted((set(rhr) | set(steps) | set(hrv) | set(sleep)) - set(skip_dates)):
        row = {"date": d, "source": "garmin"}
        if d in rhr:
            row["resting_hr"] = _r(rhr[d])
        if d in steps:
            row["steps"] = int(steps[d])
        if d in hrv:
            row["hrv_ms"] = _r(hrv[d], 1)
        if d in sleep:
            row["sleep_h"] = round(sleep[d] / 3600, 1)
        if d in sleep_eff:
            row["sleep_efficiency"] = sleep_eff[d]
        if len(row) > 2:
            daily_rows.append(row)

    device = "Garmin"
    dev = _safe(garmin.get_device_last_used)
    if isinstance(dev, dict) and dev.get("lastUsedDeviceName"):
        device = dev["lastUsedDeviceName"]

    return assemble_seed(activities, daily_rows, device)


# --- Session-token persistence (for opt-in daily auto-sync + one-tap sync) ---
# We persist ONLY the OAuth tokens garminconnect emits (di_token /
# di_refresh_token / di_client_id via .dumps()) — never the account password.
# The blob is encrypted at rest with a key derived from DOSSLAP_SECRET when the
# `cryptography` package is available; otherwise it falls back to plaintext on
# the app's private volume (a logged warning, not a crash) so a missing secret
# doesn't silently break sync on a friends-test deploy.

def _fernet():
    secret = os.environ.get("DOSSLAP_SECRET")
    if not secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:  # cryptography not installed → plaintext fallback
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def seal_token(garmin) -> tuple[str, bool]:
    """Serialize a logged-in Garmin object's session tokens for storage.
    Returns (blob, encrypted). The blob contains OAuth tokens only, no password."""
    raw = garmin.client.dumps()
    f = _fernet()
    if f is not None:
        return f.encrypt(raw.encode()).decode(), True
    logging.getLogger(__name__).warning(
        "Garmin token stored WITHOUT encryption at rest (set DOSSLAP_SECRET + install cryptography to encrypt)."
    )
    return raw, False


def _unseal_token(blob: str, encrypted: bool) -> str:
    if not encrypted:
        return blob
    f = _fernet()
    if f is None:
        raise GarminLiveError("Uložený token je zašifrovaný, ale chybí DOSSLAP_SECRET pro dešifrování.")
    return f.decrypt(blob.encode()).decode()


# Garmin's /details endpoint returns at most `maxChartSize` rows (the library
# default is 2000), decimating longer activities — a 2 h run came back at ~4 s per
# row, which the segmenter then dropped entirely. Ask for full resolution (covers
# ~14 h at 1 Hz); the stream parser is time-based, so a coarser answer still works.
FULL_RES_ROWS = 50000


def fetch_details(garmin, activity_id) -> dict:
    """Phase 4 — pull the per-record sample stream for one activity
    (metricDescriptors + activityDetailMetrics) at full resolution. Parsed by
    app.metrics.stream_qc. Raises GarminLiveError on a network/API failure."""
    try:
        return garmin.get_activity_details(str(activity_id), maxchart=FULL_RES_ROWS) or {}
    except TypeError:
        pass  # a client without the maxchart parameter → default resolution below
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "429" in msg or "too many" in msg or "rate" in msg:
            raise GarminLiveError(str(e))
        # Some other refusal of the large chart size → retry at the default size.
    try:
        return garmin.get_activity_details(str(activity_id)) or {}
    except Exception as e:  # noqa: BLE001
        raise GarminLiveError(str(e))


def resume_session(blob: str, encrypted: bool):
    """Rebuild an authenticated Garmin client from a stored token blob (no
    password, no login round-trip). The client auto-refreshes an expiring
    access token from the refresh token on first use. Raises AuthError if the
    stored tokens are no longer valid (revoked / expired refresh token)."""
    from garminconnect import Garmin, GarminConnectAuthenticationError
    token_json = _unseal_token(blob, encrypted)
    try:
        garmin = Garmin()
        # tokenstore = inline JSON → loads the tokens and proactively refreshes
        # an expiring access token from the refresh token (no password, no SSO).
        garmin.login(tokenstore=token_json)
        _ensure_profile(garmin)
    except GarminConnectAuthenticationError as e:
        raise AuthError(str(e))
    except Exception as e:
        raise AuthError(str(e))
    return garmin
