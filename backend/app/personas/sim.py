"""Simulated runners on staging (owner request 2026-10-27): each persona lives on its own clock
and goes through its days the way a runner does — the night arrives from the watch, maybe a
check-in, the app's plan for the day, the run (or not), the evening. The persona follows the
app's own week plan with its habits (catalog.py, calibration.py) and its life events; after
each half-day checks.py compares what the app said with itself and with its own rules, and
filing.py turns what breaks into notes in Team Console → Inbox.

Only where DOSSLAP_PERSONAS is on, never in the Railway environment called production: the
personas write synthetic data into the database they run on."""
import copy
import os
import random
import threading
import traceback
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session as DBSession

from .. import models, security
from ..metrics import engine as E
from . import catalog as K
from . import calibration as CAL
from . import checks as CH
from . import filing as F

HISTORY_DAYS = 120          # the usual weeks before day 0, so the norms exist
SIM_DAYS = 84               # a 12-week block from day 0
MORNING, EVENING = time(7, 30), time(20, 15)
_lock = threading.Lock()


def enabled() -> bool:
    if (os.environ.get("DOSSLAP_PERSONAS") or "").lower() not in ("1", "on", "true", "yes"):
        return False
    return (os.environ.get("RAILWAY_ENVIRONMENT_NAME") or "").lower() != "production"


def _now_real() -> str:
    return datetime.now(E.LOCAL_TZ).isoformat(timespec="seconds")


def clock_of(run: models.PersonaRun) -> datetime:
    hh, mm = (int(x) for x in (run.sim_time or "07:30").split(":"))
    return datetime.combine(date.fromisoformat(run.sim_date), time(hh, mm), E.LOCAL_TZ)


def is_persona_rid(rid: str | None) -> bool:
    return bool(rid) and rid.startswith(K.RID.format(key=""))


def clock_for_runner(db: DBSession, rid: str) -> datetime | None:
    run = db.query(models.PersonaRun).filter(models.PersonaRun.runner_id == rid).first()
    return clock_of(run) if run else None


def clock_for_user(db: DBSession, user: models.User | None) -> datetime | None:
    """The simulated clock for a request signed in as a persona (main.persona_clock)."""
    if user is None or user.provider != K.PROVIDER:
        return None
    run = db.query(models.PersonaRun).filter(models.PersonaRun.user_id == user.id).first()
    return clock_of(run) if run else None


# ---------------------------------------------------------------- the body and the runs
PACE_F = {"easy": 1.0, "recovery": 1.06, "long": 1.03, "tempo": 0.86, "intervals": 0.89, "trail": 1.12, "long_trail": 1.15}
HR_F = {"easy": 0.75, "recovery": 0.71, "long": 0.78, "tempo": 0.89, "intervals": 0.86, "trail": 0.79, "long_trail": 0.8}
RPE = {"easy": 3, "recovery": 2, "long": 5, "tempo": 7, "intervals": 8, "trail": 4, "long_trail": 6}
TITLE = {"easy": "Lehký běh", "recovery": "Rozklusání", "long": "Dlouhý běh", "tempo": "Tempový běh",
         "intervals": "Intervaly", "trail": "Lesní běh", "long_trail": "Dlouhý běh v kopcích"}
HARD = {"tempo", "intervals"}
# the app's plan types → what the persona runs
FROM_PLAN = {"lehký": "easy", "regenerace": "recovery", "dlouhý": "long", "kvalitní": None}


def _load(kind: str, amount: float) -> float:
    if kind == "cycling":
        return amount / 6
    if kind in ("strength", "swim"):
        return amount / 10
    return amount * (1.4 if kind in HARD else 1.15 if kind in ("long_trail", "trail") else 1.0)


def usual_daily_load(p: dict) -> float:
    return sum(_load(k, a) for k, a in p["week"].values()) / 7 or 1.0


def run_activity(p: dict, day: date, kind: str, km: float, rnd: random.Random, pain: int = 0, fatigue: float = 0.0) -> dict:
    from ..seed import _synth_elevation_profile
    b = p["body"]
    trail = kind in ("trail", "long_trail")
    pace = b["easy_pace"] * PACE_F[kind] * (1 + 0.02 * fatigue) + rnd.gauss(0, 5)
    hr = p["hr_max"] * HR_F[kind] * (1 + 0.02 * fatigue) + rnd.gauss(0, 2)
    asc = round(km * (rnd.uniform(30, 45) if trail else rnd.uniform(2, 8)))
    dsc = round(asc * rnd.uniform(0.9, 1.1))
    stride = round(b["cad"] and (1000 / (pace / 60) / b["cad"]) or 1.0, 2)
    vr = b["vr"] + (0.3 if trail else 0) + (pace - b["easy_pace"]) / 500 + rnd.gauss(0, 0.12) + 0.05 * fatigue
    gct = b["gct"] + (10 if trail else 0) + (pace - b["easy_pace"]) * 0.16 + rnd.gauss(0, 3) + 2 * pain
    bal = b["bal"] + rnd.gauss(0, 0.2) - 0.25 * pain
    cad = b["cad"] - (3 if trail else 0) - (pace - b["easy_pace"]) * 0.03 + rnd.gauss(0, 1.1)
    drift = 1.06 if kind in ("long", "long_trail") else 1.03
    start = "18:10" if p["habits"]["hours"][-1] >= 20 else "07:00"
    return {
        "started_at": E.iso_date(day), "start_time": "08:30" if day.weekday() >= 5 else start,
        "title": TITLE[kind], "sport": "running", "distance_km": round(km, 1), "duration_min": round(km * pace / 60, 1),
        "pace_s_km": round(pace), "avg_hr": round(hr), "surface": "trail" if trail else "road",
        "ascent_m": asc, "descent_m": dsc, "temp_c": round(12 + rnd.gauss(0, 4)),
        "cadence_spm": round(cad), "stride_len_m": stride, "vert_osc_cm": round(vr * stride, 1),
        "vert_ratio_pct": round(vr, 2), "gct_ms": round(gct), "gct_balance_l": round(bal, 2),
        "vr_thirds": [round(vr * 0.99, 2), round(vr, 2), round(vr * 1.008, 2)],
        "hr_thirds": [round(hr * 0.97), round(hr), round(hr * drift)],
        "pace_thirds": [round(pace * 1.01), round(pace), round(pace * 0.99)],
        "rpe": int(E.clamp(RPE[kind] + (1 if fatigue > 0.5 else 0) + (1 if pain >= 3 else 0), 1, 10)),
        "elevation_profile": _synth_elevation_profile(rnd.random, km, asc, dsc, "trail" if trail else "road"),
    }


def other_activity(p: dict, day: date, kind: str, minutes: float, rnd: random.Random) -> dict:
    if kind == "cycling":
        return {"started_at": E.iso_date(day), "start_time": "17:30", "title": "Kolo", "sport": "cycling",
                "distance_km": round(minutes / 60 * rnd.uniform(24, 28), 1), "duration_min": round(minutes),
                "avg_hr": round(p["hr_max"] * 0.68 + rnd.gauss(0, 3)), "surface": "road",
                "ascent_m": round(minutes * 3), "descent_m": round(minutes * 3), "rpe": 3}
    if kind == "swim":
        return {"started_at": E.iso_date(day), "start_time": "19:00", "title": "Plavání", "sport": "swimming",
                "distance_km": round(minutes / 60 * 2.2, 1), "duration_min": round(minutes), "rpe": 3}
    return {"started_at": E.iso_date(day), "start_time": "19:00", "title": "Posilování", "sport": "strength",
            "duration_min": round(minutes), "strength_focus": "full", "strength_type": "circuit", "rpe": 5}


def night(p: dict, day: date, rnd: random.Random, load_ratio: float, events: list) -> dict:
    """Last night from the watch: sleep, HRV, resting HR, breathing — the usual body, moved by
    yesterday's load and the day's events."""
    b = p["body"]
    kinds = {e["kind"] for e in events}
    ill, bad = "illness" in kinds, "bad_sleep" in kinds
    z = E.clamp(load_ratio - 1, -1, 2)
    sleep = round(E.clamp(b["sleep"] + rnd.gauss(0, 0.4) - (1.9 if bad else 0) - (0.6 if ill else 0), 3.5, 10), 1)
    awake = round(rnd.uniform(15, 30) + (25 if bad or ill else 0))
    deep = round(sleep * 60 * rnd.uniform(0.15, 0.2))
    rem = round(sleep * 60 * rnd.uniform(0.19, 0.24))
    hrv = b["hrv"] * (1 - 0.07 * z - (0.3 if ill else 0) - (0.08 if bad else 0)) + rnd.gauss(0, b["hrv"] * 0.05)
    rhr = b["rhr"] + 2.0 * z + (8 if ill else 0) + (1.5 if bad else 0) + rnd.gauss(0, 0.9)
    return {"date": E.iso_date(day), "sleep_h": sleep, "deep_min": deep, "rem_min": rem,
            "light_min": max(0, round(sleep * 60 - deep - rem)), "awake_min": awake,
            "sleep_efficiency": round(sleep * 60 / (sleep * 60 + awake), 3), "hrv_ms": round(hrv),
            "resting_hr": round(rhr), "resp_rate": round(14.5 + (2.4 if ill else 0) + rnd.gauss(0, 0.3), 1),
            "body_battery": round(E.clamp(75 - 20 * max(z, 0) - (30 if ill else 0) + rnd.gauss(0, 6), 5, 100)),
            "stress_avg": round(27 + (12 if ill or bad else 0) + rnd.gauss(0, 3)), "steps": round(rnd.gauss(9000, 1800)),
            "source": "garmin"}


def checkin_row(p: dict, rid: str, day: date, rnd: random.Random, events: list, load_ratio: float) -> models.Checkin:
    from ..tutorial_demo import SITE, _pt
    pain = next((e for e in events if e["kind"] == "pain"), None)
    ill = any(e["kind"] == "illness" for e in events)
    score = int(pain["score"]) if pain else 0
    sore = int(E.clamp(round(2 + 1.5 * max(load_ratio - 1, 0) + rnd.gauss(0, 0.6)), 0, 10))
    return models.Checkin(
        runner_id=rid, submitted_at=datetime.combine(day, time(7, 15), E.LOCAL_TZ).isoformat(),
        pain_score=score, pain_site=pain["site"] if pain else None,
        pain_points=[{**_pt(SITE, score, "bolest", "ráno"), "region": pain["site"], "side": pain.get("side", "P")}] if pain else [],
        soreness=sore, stress=3 if ill else 2, mood=2 if ill or pain else 3, limits_movement=score >= 5,
        run_modified=score >= 3, limping=False, sleep_quality=1 if ill else 3, life_stress=5 if ill else 3,
        flags={"ill": True} if ill else None, notes=pain.get("note") if pain else None,
    )


# ---------------------------------------------------------------- accounts and reset
def behaviour(key: str, db: DBSession) -> dict:
    return CAL.blend(key, K.PERSONAS[key], CAL.current(db))


def ensure_account(db: DBSession, key: str, start: date) -> tuple[models.User, models.Runner]:
    p = K.PERSONAS[key]
    rid, email = K.RID.format(key=key), K.EMAIL.format(key=key)
    r = db.get(models.Runner, rid)
    if r is None:
        r = models.Runner(id=rid, name=p["name"])
        db.add(r)
    r.name, r.sex, r.birth_year, r.weight_kg, r.hr_max = f"{p['name']} (persona)", p["sex"], p["birth_year"], p["weight_kg"], p["hr_max"]
    r.city, r.device, r.engine_mode = "Praha", "Garmin Forerunner 265", "v3"
    r.running_since = E.iso_date(start - timedelta(days=round(p["running_months"] * 30.4)))
    r.onboarding_json = {"active": False, "dismissed": True, "tutorialDone": True, "persona": key}
    r.planner_json, r.cycle_override, r.coach_mode = None, None, False
    if p.get("prior_injury"):
        site, months, side = p["prior_injury"]
        r.prior_injury, r.prior_injury_months_ago, r.prior_injury_side = site, months, side
        r.prior_injury_date = E.iso_date(start - timedelta(days=round(months * 30.4)))
    if p.get("cycle"):
        c = p["cycle"]
        first = start - timedelta(days=HISTORY_DAYS) + timedelta(days=c["start_offset"])
        starts = [E.iso_date(first + timedelta(days=c["length"] * i)) for i in range((HISTORY_DAYS + SIM_DAYS) // c["length"] + 1)]
        r.menstrual_json = {"track": True, "hormonal": False, "length": c["length"], "starts": starts}
    u = db.query(models.User).filter(models.User.email == email).first()
    if u is None:
        u = models.User(email=email, password_hash=security.hash_password(os.urandom(24).hex()), name=r.name,
                        role="runner", runner_id=rid, provider=K.PROVIDER, lang="cs", created_at=_now_real())
        db.add(u)
        db.flush()
        db.add(models.Settings(user_id=u.id))
    db.flush()
    return u, r


def reset(db: DBSession, key: str, seed: int = 1, start: date | None = None) -> models.PersonaRun:
    """Wipe the persona and lay down its usual weeks before day 0 (the norms the engine needs)."""
    from ..tutorial_demo import _wipe
    if key not in K.PERSONAS:
        raise KeyError(key)
    p = K.PERSONAS[key]
    start = start or (datetime.now(E.LOCAL_TZ).date() - timedelta(days=SIM_DAYS))
    u, r = ensure_account(db, key, start)
    rid = r.id
    _wipe(db, rid)
    db.query(models.Goal).filter(models.Goal.runner_id == rid).delete(synchronize_session=False)
    run = db.query(models.PersonaRun).filter(models.PersonaRun.key == key).first()
    if run is not None:
        db.query(models.PersonaDay).filter(models.PersonaDay.run_id == run.id).delete(synchronize_session=False)
    else:
        run = models.PersonaRun(key=key, runner_id=rid, created_at=_now_real())
        db.add(run)
    run.user_id, run.seed, run.start_date, run.sim_date = u.id, seed, E.iso_date(start), E.iso_date(start)
    run.phase, run.sim_time, run.status, run.error = "night", "07:30", "idle", None
    run.behaviour_json = behaviour(key, db)
    run.stats_json = {"days": 0, "findings": 0, "filed": 0, "weeks": {}, "checks": {}}
    run.updated_at = _now_real()
    db.add(models.Integration(id=f"int_{rid}", runner_id=rid, provider="garmin", status="demo", last_sync_at=_now_real(),
                              fields=["vert_ratio_pct", "gct_ms", "gct_balance_l", "cadence_spm", "stride_len_m",
                                      "hrv_ms", "resting_hr", "sleep_h"]))
    db.add(models.DeviceHistory(runner_id=rid, device=r.device, source="registration",
                                recorded_at=E.iso_date(start - timedelta(days=HISTORY_DAYS))))
    rnd = random.Random(f"{key}-{seed}-history")
    usual = usual_daily_load(p)
    prev = usual
    for k in range(HISTORY_DAYS, 0, -1):
        day = start - timedelta(days=k)
        db.add(models.DailyMetric(runner_id=rid, **night(p, day, rnd, prev / usual, [])))
        cyc = [1.0, 1.05, 1.1, 0.8][((HISTORY_DAYS - k) // 7) % 4] * (0.85 + 0.15 * min(1, (HISTORY_DAYS - k) / 60))
        planned = p["week"].get(day.weekday())
        prev = 0.0
        if planned and rnd.random() < 0.92:
            kind, amount = planned
            if kind in ("cycling", "strength", "swim"):
                db.add(models.Activity(runner_id=rid, provider="persona", **other_activity(p, day, kind, amount, rnd)))
            else:
                amount = max(3.0, amount * cyc * rnd.uniform(0.93, 1.07))
                act = models.Activity(runner_id=rid, provider="persona", **run_activity(p, day, kind, amount, rnd))
                db.add(act)
                if k <= 35 and rnd.random() < p["habits"]["feedback"]:
                    db.flush()
                    db.add(models.ActivityFeedback(activity_id=act.id, runner_id=rid, submitted_at=act.started_at,
                                                   feeling=4, legs=4, rpe=act.rpe, pain_points=[]))
            prev = _load(kind, amount)
        if k <= 30 and rnd.random() < p["habits"]["checkin"]:
            db.add(checkin_row(p, rid, day, rnd, [], prev / usual))
    goal = p.get("goal")
    if goal:
        db.add(models.Goal(runner_id=rid, kind="race", name=goal["name"], date=E.iso_date(start + timedelta(days=goal["day"])),
                           distance_km=goal["km"], terrain="road", aim="finish", path="safe", status="active",
                           created_at=_now_real(), updated_at=_now_real()))
    db.commit()
    with E.sim_clock(datetime.combine(start, MORNING, E.LOCAL_TZ)):
        E.recompute_assessment(db, rid)
    return run


# ---------------------------------------------------------------- one simulated day
def _rnd(run: models.PersonaRun, day: date, salt: str) -> random.Random:
    return random.Random(f"{run.key}-{run.seed}-{day.isoformat()}-{salt}")


def _day_no(run: models.PersonaRun, day: date) -> int:
    return (day - date.fromisoformat(run.start_date)).days


def _yesterday_load(db: DBSession, rid: str, day: date) -> float:
    acts = db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                            models.Activity.started_at == E.iso_date(day - timedelta(days=1))).all()
    total = 0.0
    for a in acts:
        if a.sport == "running":
            kind = next((k for k, t in TITLE.items() if t == a.title), "easy")
            total += _load(kind, a.distance_km or 0)
        elif a.sport == "cycling":
            total += _load("cycling", a.duration_min or 0)
        else:
            total += _load("strength", a.duration_min or 0)
    return total


def _save_day(db: DBSession, run: models.PersonaRun, day: date, patch: dict) -> dict:
    row = db.query(models.PersonaDay).filter(models.PersonaDay.run_id == run.id, models.PersonaDay.date == E.iso_date(day)).first()
    if row is None:
        row = models.PersonaDay(run_id=run.id, date=E.iso_date(day), data_json={})
        db.add(row)
    data = dict(row.data_json or {})
    data.update(patch)
    row.data_json = data
    return data


def morning(db: DBSession, run: models.PersonaRun) -> dict:
    """The night arrives, perhaps a check-in, and the app's morning: what Dnes, Trénink and the
    morning report say, checked against each other."""
    p, beh, rid = K.PERSONAS[run.key], run.behaviour_json or K.PERSONAS[run.key]["habits"], run.runner_id
    if run.phase == "evening":                  # the night after yesterday's evening
        run.sim_date = E.iso_date(date.fromisoformat(run.sim_date) + timedelta(days=1))
    # the clock first: the precompute worker reads it from the database as soon as data land
    run.sim_time = MORNING.strftime("%H:%M")
    day = date.fromisoformat(run.sim_date)
    n = _day_no(run, day)
    events = K.events_on(p, n)
    kinds = {e["kind"] for e in events}
    rnd = _rnd(run, day, "morning")
    usual = usual_daily_load(p)
    ratio = _yesterday_load(db, rid, day) / usual
    with E.sim_clock(datetime.combine(day, time(6, 45), E.LOCAL_TZ)):
        if "no_watch" not in kinds:
            db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                models.DailyMetric.date == E.iso_date(day)).delete(synchronize_session=False)
            db.add(models.DailyMetric(runner_id=rid, **night(p, day, rnd, ratio, events)))
        must = bool(kinds & {"pain", "illness"})
        did_checkin = rnd.random() < (max(beh.get("checkin", 0.5), 0.9) if must else beh.get("checkin", 0.5))
        if did_checkin:
            db.add(checkin_row(p, rid, day, rnd, events, ratio))
        db.commit()
    with E.sim_clock(datetime.combine(day, MORNING, E.LOCAL_TZ)):
        crashes = CH.recompute(db, rid, "/app/today")       # what a sync or a check-in triggers in the app
        snap, more = CH.snapshot(db, rid, day)
        crashes += more
        ctx = {"persona": run.key, "name": p["name"], "label": p["label"], "day": n, "date": E.iso_date(day),
               "events": events, "checkin": did_checkin, "stats": run.stats_json or {}, "goal": p.get("goal"),
               "start": run.start_date}
        findings = crashes + CH.morning_checks(db, rid, snap, ctx)
    stats = copy.deepcopy(run.stats_json or {})   # nested JSON: a new object, or the change is lost
    if snap.get("weekStart") and snap.get("weekTotals") and day.weekday() == 0:
        stats.setdefault("weeks", {})[snap["weekStart"]] = (snap["weekTotals"] or {}).get("km")
    run.stats_json = stats
    data = _save_day(db, run, day, {"day": n, "events": [e.get("note") or e["kind"] for e in events], "checkin": did_checkin,
                                    "morning": CH.light(snap), "findings": [f["title"] for f in findings]})
    run.phase = "morning"
    _file(db, run, findings, ctx, passed=CH.MORNING_CHECKS)
    db.commit()
    return data


def _decide(p: dict, beh: dict, snap: dict, day: date, events: list, rnd: random.Random) -> list[tuple]:
    """What the persona does today: [(kind, amount, followed)]."""
    kinds = {e["kind"] for e in events}
    pain = max([e.get("score", 0) for e in events if e["kind"] == "pain"] or [0])
    plan = snap.get("planToday") or []
    run_item = next((i for i in plan if i.get("kind") == "run" and not i.get("optional")), None)
    template = p["week"].get(day.weekday())
    out: list[tuple] = []
    if "illness" in kinds and not beh.get("stubborn"):
        return []
    if run_item:
        km = run_item.get("km") or {}
        lo, hi = km.get("lo") or 0, km.get("hi") or 0
        kind = FROM_PLAN.get(run_item.get("type"), "easy") or ("intervals" if template and template[0] == "intervals" else "tempo")
        if template and template[0] in ("trail", "long_trail") and kind in ("easy", "long"):
            kind = "long_trail" if kind == "long" else "trail"
        if pain >= 4 and not beh.get("stubborn"):
            return []
        if rnd.random() < beh.get("compliance", 0.8):
            amount, followed = rnd.uniform(lo, hi) if hi > lo else hi, True
            if rnd.random() < beh.get("overshoot", 0):
                amount, followed = hi * 1.15, False
        elif rnd.random() < 0.5:
            return []
        else:
            amount, followed = hi * 1.1, False
        if amount >= 2:
            out.append((kind, round(amount, 1), followed))
    elif template and template[0] not in ("cycling", "strength", "swim") and rnd.random() > beh.get("compliance", 0.8):
        out.append((template[0], round(template[1], 1), False))       # runs on a planned rest day
    elif "illness" in kinds and beh.get("stubborn") and template and template[0] not in ("cycling", "strength", "swim"):
        out.append(("easy", round(template[1] * 0.7, 1), False))
    for i in plan:
        if i.get("kind") == "run":
            continue
        t = i.get("type") or i.get("kind")
        if t == "kolo":
            out.append(("cycling", (i.get("durationMin") or [60])[-1] if isinstance(i.get("durationMin"), list) else 60, True))
        elif t == "posilování" and rnd.random() < beh.get("compliance", 0.8):
            out.append(("strength", 40, True))
        elif t == "voda":
            out.append(("swim", 40, True))
    return out


def evening(db: DBSession, run: models.PersonaRun) -> dict:
    p, beh, rid = K.PERSONAS[run.key], run.behaviour_json or K.PERSONAS[run.key]["habits"], run.runner_id
    day = date.fromisoformat(run.sim_date)
    n = _day_no(run, day)
    events = K.events_on(p, n)
    kinds = {e["kind"] for e in events}
    rnd = _rnd(run, day, "evening")
    row = db.query(models.PersonaDay).filter(models.PersonaDay.run_id == run.id, models.PersonaDay.date == E.iso_date(day)).first()
    snap = ((row.data_json or {}).get("morning") if row else None) or {}
    pain = max([e.get("score", 0) for e in events if e["kind"] == "pain"] or [0])
    did = _decide(p, beh, snap, day, events, rnd)
    run.sim_time = EVENING.strftime("%H:%M")
    with E.sim_clock(datetime.combine(day, time(19, 30), E.LOCAL_TZ)):
        recorded = []
        if "no_watch" not in kinds:
            for kind, amount, _ in did:
                if kind in ("cycling", "strength", "swim"):
                    db.add(models.Activity(runner_id=rid, provider="persona", **other_activity(p, day, kind, amount, rnd)))
                else:
                    act = models.Activity(runner_id=rid, provider="persona",
                                          **run_activity(p, day, kind, amount, rnd, pain=pain, fatigue=1.0 if "illness" in kinds else 0.0))
                    db.add(act)
                    if rnd.random() < beh.get("feedback", 0.6):
                        db.flush()
                        db.add(models.ActivityFeedback(activity_id=act.id, runner_id=rid, submitted_at=E.now_iso(),
                                                       feeling=2 if "illness" in kinds else 4 if not pain else 3,
                                                       legs=3 if pain else 4, rpe=act.rpe, pain_during=pain,
                                                       pain_site=next((e["site"] for e in events if e["kind"] == "pain"), None),
                                                       niggle=pain >= 2, pain_points=[]))
                recorded.append(kind)
        db.commit()
    with E.sim_clock(datetime.combine(day, EVENING, E.LOCAL_TZ)):
        crashes = CH.recompute(db, rid, "/app/load") if recorded else []
        after, more = CH.snapshot(db, rid, day, light=True)
        crashes += more
        ctx = {"persona": run.key, "name": p["name"], "label": p["label"], "day": n, "date": E.iso_date(day),
               "events": events, "did": did, "recorded": recorded}
        findings = crashes + CH.evening_checks(snap, after, ctx)
    data = _save_day(db, run, day, {"did": [{"kind": k, "amount": a, "followed": f} for k, a, f in did],
                                    "recorded": recorded, "evening": CH.light(after),
                                    "findings": ((row.data_json or {}).get("findings") if row else []) + [f["title"] for f in findings]})
    stats = copy.deepcopy(run.stats_json or {})   # nested JSON: a new object, or the change is lost
    stats["days"] = stats.get("days", 0) + 1
    run.stats_json = stats
    _file(db, run, findings, ctx, passed=CH.EVENING_CHECKS)
    run.phase = "evening"                                   # the evening of the same day; morning() moves on
    run.updated_at = _now_real()
    db.commit()
    return data


def _file(db: DBSession, run: models.PersonaRun, findings: list, ctx: dict, passed: tuple) -> None:
    failed = {f["check"] for f in findings}
    res = F.file(db, run.key, findings, ctx["date"], passed=[c for c in passed if c not in failed])
    stats = copy.deepcopy(run.stats_json or {})   # nested JSON: a new object, or the change is lost
    stats["findings"] = stats.get("findings", 0) + len(findings)
    stats["filed"] = stats.get("filed", 0) + res.get("created", 0)
    checks = dict(stats.get("checks") or {})
    for f in findings:
        checks[f["check"]] = checks.get(f["check"], 0) + 1
    stats["checks"] = checks
    run.stats_json = stats


def step(db: DBSession, run: models.PersonaRun, to: str = "evening") -> None:
    """Advance by half a day: to "morning" (the night arrived, the run not yet done) or to
    "evening" (the day is done; the clock shows its evening until the next morning)."""
    if run.phase == "morning":
        evening(db, run)
        if to == "morning":
            morning(db, run)
        return
    morning(db, run)
    if to != "morning":
        evening(db, run)


def advance(db: DBSession, key: str, days: int, to: str = "evening") -> dict:
    run = db.query(models.PersonaRun).filter(models.PersonaRun.key == key).first()
    if run is None:
        run = reset(db, key)
    limit = date.fromisoformat(run.start_date) + timedelta(days=SIM_DAYS + 120)
    done = 0
    for _ in range(max(1, days)):
        if date.fromisoformat(run.sim_date) >= limit:
            break
        step(db, run, to if done == days - 1 else "evening")
        done += 1
    return {"key": key, "days": done, **run_out(run)}


def advance_in_background(key_list: list, days: int, session_factory) -> None:
    """Long simulations run beside the server (staging has one process); the status shows on
    Team Console → Persony."""
    def work():
        with _lock:
            for key in key_list:
                db = session_factory()
                try:
                    run = db.query(models.PersonaRun).filter(models.PersonaRun.key == key).first() or reset(db, key)
                    run.status, run.error = "running", None
                    db.commit()
                    advance(db, key, days)
                    run.status = "idle"
                    db.commit()
                except Exception:  # noqa: BLE001 — the run shows the error, the server stays up
                    db.rollback()
                    run = db.query(models.PersonaRun).filter(models.PersonaRun.key == key).first()
                    if run is not None:
                        run.status, run.error = "error", traceback.format_exc()[-1500:]
                        db.commit()
                finally:
                    db.close()
    threading.Thread(target=work, daemon=True, name="personas").start()


def run_out(run: models.PersonaRun | None) -> dict | None:
    if run is None:
        return None
    return {"key": run.key, "runnerId": run.runner_id, "seed": run.seed, "startDate": run.start_date, "simDate": run.sim_date,
            "simTime": run.sim_time, "phase": run.phase, "status": run.status, "error": run.error,
            "day": (date.fromisoformat(run.sim_date) - date.fromisoformat(run.start_date)).days,
            "stats": run.stats_json or {}, "behaviour": run.behaviour_json or {}, "updatedAt": run.updated_at}
