"""One-shot pull of the FULL Garmin palette to a local JSON cache, so the
Excel builder can iterate without re-hitting the API. Credentials come from
env vars GARMIN_EMAIL / GARMIN_PASSWORD (never stored).

Pulls: every activity (all types, all summary fields) + daily wellness via the
range endpoints (HRV, resting HR, sleep-with-stages, steps, VO2max, calories).
"""
import json
import os
from datetime import date

import garmin_live

CACHE = os.environ.get("GARMIN_CACHE", "/tmp/garmin_export_cache.json")


def main():
    email = os.environ["GARMIN_EMAIL"]
    pw = os.environ["GARMIN_PASSWORD"]
    g, mfa, st = garmin_live.begin_login(email, pw)
    if mfa:
        raise SystemExit("Účet vyžaduje MFA — tenhle skript MFA neřeší.")
    print("login ok")

    end = date.today().isoformat()
    acts_all = g.get_activities_by_date("2010-01-01", end) or []
    print("activities (all types):", len(acts_all))
    start = min((a.get("startTimeLocal") or a.get("startTimeGMT") or end)[:10] for a in acts_all) if acts_all else "2025-01-01"
    print("history start:", start)

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001
            print(f"  {fn.__name__} failed: {e}")
            return None

    hrv = safe(g.get_hrv_data_range, start, end)
    daily = {
        "hrv": (hrv or {}).get("hrvSummaries") if isinstance(hrv, dict) else None,
        "rhr": safe(g.get_rhr_daily, start, end),
        "sleep": safe(g.get_sleep_daily, start, end),
        "steps": safe(g.get_daily_steps, start, end),
        "vo2max": safe(g.get_max_metrics_range, start, end),
        "calories": safe(g.get_calories_daily, start, end),
    }
    for k, v in daily.items():
        print(f"  daily.{k}: {len(v) if isinstance(v, list) else ('dict' if v else 'none')}")

    device = "Garmin"
    dev = safe(g.get_device_last_used)
    if isinstance(dev, dict) and dev.get("lastUsedDeviceName"):
        device = dev["lastUsedDeviceName"]

    json.dump({"activities": acts_all, "daily": daily, "device": device,
               "history_start": start, "pulled_end": end},
              open(CACHE, "w"), ensure_ascii=False)
    print("cached →", CACHE)


if __name__ == "__main__":
    main()
