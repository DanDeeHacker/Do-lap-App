"""Synthetic runner histories for engine tests: enough per-run data to pass the
mechanics confidence gate, plus optional stored segment streams."""
import random

from app import models
from app.metrics import engine as E


def seed_runs(db, rid, days=100, p_run=0.75, seed=1, pace_fn=None):
    """~`p_run` runs/day over `days` days of flat road running with realistic
    per-run noise. `pace_fn(days_ago) -> s/km` overrides the default pace."""
    rng = random.Random(seed)
    out = []
    for d in range(days, -1, -1):
        if rng.random() > p_run:
            continue
        pace = pace_fn(d) if pace_fn else rng.uniform(335, 380)
        km = 10.0
        cad = 172 - 0.12 * (pace - 355) + rng.gauss(0, 1.5)
        speed = 1000 / pace
        stride = speed * 60 / cad * 2
        vosc = 8.5 + rng.gauss(0, 0.3)
        a = models.Activity(
            runner_id=rid, provider="garmin", external_id=f"{rid}-{d}", started_at=E.day_ago(d),
            sport="running", title="Běh", distance_km=km, duration_min=pace * km / 60, pace_s_km=pace,
            avg_hr=145 + rng.gauss(0, 3), surface="road", ascent_m=20, descent_m=20,
            cadence_spm=cad, stride_len_m=stride, vert_osc_cm=vosc,
            vert_ratio_pct=vosc / (stride / 2 * 100) * 100,
            gct_ms=250 + 0.5 * (pace - 355) + rng.gauss(0, 5), gct_balance_l=50 + rng.gauss(0, 0.3),
        )
        db.add(a)
        out.append(a)
    db.commit()
    return out


def seg(g, gct, t=0, v=3.0, surface="road", vr=8.0):
    band = "B1" if g < -0.10 else "B2" if g < -0.03 else "B3" if g < 0.03 else "B4" if g < 0.10 else "B5"
    return {"band": band, "surface": surface, "durationS": 60, "meanSpeed": v, "meanGradient": g,
            "elapsedS": t, "cumDescentM": 0.0, "gct_ms": gct, "vratio_pct": vr, "cadence_spm": 172.0}


def add_streams(db, rid, shift_fn, seed=2, n_seg=10):
    """One stored stream per running activity; `shift_fn(started_at) -> ms` is
    added to every segment's GCT (0 = baseline behaviour)."""
    rng = random.Random(seed)
    for a in E.acts(db, rid):
        shift = shift_fn(a.started_at)
        day_off = rng.gauss(0, 2.0)  # session-level (day-to-day) variation
        segs = []
        for i in range(n_seg):
            g = -0.08 + i * 0.018
            v = 2.9 + (i % 3) * 0.1
            segs.append(seg(g, 240 + 100 * g + 8 * (v - 3.0) + day_off + shift + rng.gauss(0, 3), t=i * 60, v=v))
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
                                     segments_json=segs, created_at=E.now_iso()))
    db.commit()


def garmin_sleep_payload(day, start_min=22 * 60 + 50, sleep_min=440, seed=0):
    """A Garmin get_sleep_data(day) payload: ~90-minute cycles, more deep sleep early,
    more REM late, a few short awakenings (for the morning report)."""
    import datetime as dt
    rng = random.Random(seed)
    d = dt.date.fromisoformat(day)
    s = dt.datetime.combine(d - dt.timedelta(days=1), dt.time()) + dt.timedelta(minutes=start_min)
    gmt = s - dt.timedelta(hours=2)
    lv, t, k = [], 0, 0
    while t < sleep_min:
        cyc = [(1, 15), (0, max(5, 45 - 10 * k + rng.randint(-5, 5))), (1, 20), (2, 10 + 8 * k + rng.randint(-3, 3))]
        if rng.random() < 0.35:
            cyc.append((3, rng.randint(2, 6)))
        for level, m in cyc:
            m = min(m, sleep_min - t)
            if m <= 0:
                break
            a = gmt + dt.timedelta(minutes=t)
            lv.append({"startGMT": a.isoformat() + ".0", "endGMT": (a + dt.timedelta(minutes=m)).isoformat() + ".0", "activityLevel": float(level)})
            t += m
        k += 1
    secs = {0: 0, 1: 0, 2: 0, 3: 0}
    for x in lv:
        a, b = dt.datetime.fromisoformat(x["startGMT"][:19]), dt.datetime.fromisoformat(x["endGMT"][:19])
        secs[int(x["activityLevel"])] += (b - a).seconds
    ms = lambda x: int(x.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)  # noqa: E731
    return {"dailySleepDTO": {"calendarDate": day, "sleepTimeSeconds": secs[0] + secs[1] + secs[2],
                              "sleepStartTimestampGMT": ms(gmt), "sleepEndTimestampGMT": ms(gmt + dt.timedelta(minutes=t)),
                              "sleepStartTimestampLocal": ms(s), "sleepEndTimestampLocal": ms(s + dt.timedelta(minutes=t)),
                              "deepSleepSeconds": secs[0], "lightSleepSeconds": secs[1], "remSleepSeconds": secs[2],
                              "awakeSleepSeconds": secs[3], "awakeCount": sum(1 for x in lv if x["activityLevel"] == 3),
                              "averageRespirationValue": 14.2, "avgSleepStress": 17.0,
                              "sleepScores": {"overall": {"value": 70 + rng.randint(0, 20), "qualifierKey": "GOOD"}}},
            "sleepLevels": lv,
            "hrvData": [{"startGMT": (gmt + dt.timedelta(minutes=m)).isoformat() + ".0", "value": 48 + rng.randint(-8, 10)} for m in range(0, t, 10)],
            "avgOvernightHrv": 51.0, "bodyBatteryChange": 55}


def garmin_day_payloads(day, run_at=7 * 60 + 30, seed=0):
    """get_stress_data(day) + get_user_summary(day) payloads for a day with a morning run."""
    import datetime as dt
    rng = random.Random(seed)
    d0 = dt.datetime.combine(dt.date.fromisoformat(day), dt.time())
    g0 = d0 - dt.timedelta(hours=2)
    ms = lambda x: int(x.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)  # noqa: E731
    stress, bb, lvl = [], [], 30
    for m in range(0, 24 * 60, 3):
        if m < 6 * 60 + 30 or m > 23 * 60:
            v = rng.randint(8, 20)
        elif run_at <= m < run_at + 60:
            v = -2                                              # activity: no stress value
        else:
            v = rng.randint(20, 45) + (25 if 13 * 60 < m < 16 * 60 else 0)
        stress.append([ms(g0 + dt.timedelta(minutes=m)), v])
        lvl = min(100, lvl + 0.35) if m < 6 * 60 + 30 else max(5, lvl - (0.9 if run_at <= m < run_at + 60 else 0.12))
        bb.append([ms(g0 + dt.timedelta(minutes=m)), "MEASURED", int(lvl), 2.0])
    return ({"calendarDate": day, "startTimestampGMT": g0.isoformat() + ".0", "startTimestampLocal": d0.isoformat() + ".0",
             "avgStressLevel": 29, "maxStressLevel": 88, "stressValuesArray": stress, "bodyBatteryValuesArray": bb},
            {"bodyBatteryHighestValue": 82, "bodyBatteryLowestValue": 24, "bodyBatteryChargedValue": 52,
             "bodyBatteryDrainedValue": 60, "bodyBatteryMostRecentValue": 26, "bodyBatteryAtWakeTime": 80,
             "totalSteps": 11840, "dailyStepGoal": 9000, "averageStressLevel": 29,
             "restStressDuration": 25000, "lowStressDuration": 18000, "mediumStressDuration": 9000, "highStressDuration": 2400})


def seed_details(db, rid, days=14, today=None):
    """DailyDetail rows (and matching day rows) for the report, built through the real
    garmin_live compaction."""
    import datetime as dt
    import garmin_live as GL
    from app import models
    from app.metrics import engine as E
    today = today or E.today_date()
    for k in range(days):
        d = (today - dt.timedelta(days=k)).isoformat()
        sl = GL.compact_sleep(garmin_sleep_payload(d, start_min=22 * 60 + 40 + (k * 7) % 40, sleep_min=400 + (k * 23) % 90, seed=k))
        st, su = garmin_day_payloads(d, seed=k)
        dy = GL.compact_day(st, su)
        row = db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid, models.DailyDetail.date == d).first()
        if row is None:
            row = models.DailyDetail(runner_id=rid, date=d)
            db.add(row)
        row.sleep, row.day = sl, dy
        dm = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == d).first()
        if dm is None:
            dm = models.DailyMetric(runner_id=rid, date=d)
            db.add(dm)
        dm.sleep_h = round(sl["sleepMin"] / 60, 1)
        dm.deep_min, dm.rem_min, dm.light_min, dm.awake_min = (sl["stages"][x] for x in ("deep", "rem", "light", "awake"))
        dm.sleep_efficiency = round(sl["sleepMin"] / (sl["sleepMin"] + sl["stages"]["awake"]), 3)
        dm.steps, dm.stress_avg, dm.body_battery = dy["steps"] - k * 300, dy["stressAvg"], dy["bbWake"]
        dm.hrv_ms = dm.hrv_ms or 52 + (k % 5) - 2
        dm.resting_hr = dm.resting_hr or 48 + (k % 3)
    db.commit()
