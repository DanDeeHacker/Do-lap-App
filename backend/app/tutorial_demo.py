"""The synthetic runner behind the getting-started tour.

The tour used to borrow the public "Kritické přetížení" demo login. That runner
is deliberately in the critical quadrant, so its Trénink tab shows a rest day
with no numbers, it never had post-run ratings, and its data aged from the day
it was created. This module keeps a dedicated runner instead:

* rebuilt deterministically relative to *today* (Europe/Prague) whenever the
  stored build date or BUILD_VERSION differs, so every tab always has recent data;
* a realistic, instructive state: a new training block pushed the load up
  (quadrant "Přetížení"), mechanics hold with one metric at the edge, a mild
  Achilles niggle in the journal, and an easy run with concrete limits as today's
  recommendation;
* a full journal (rated runs with body-map points, two runs awaiting a rating,
  daily and weekly check-ins), races, and a physiotherapist relationship
  (messages, program, a past visit with an approved summary, an upcoming booking).

It has no login. Any signed-in user may read it (deps.ensure_runner_read_access),
nobody can write to it, and it is kept out of population priors and outcome
snapshots so synthetic data never leaks into calibration.
"""
import math
import random
import threading
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session as DBSession

from . import models
from .content import lib_for
from .metrics import engine as E

TUTORIAL_RID = "run_tutorial"
BUILD_VERSION = 1
_lock = threading.Lock()

DAYS = 182
SITE = {"region": "Achillova šlacha", "side": "P", "view": "back", "x": 96, "y": 362}
CALF = {"region": "Gastrocnemius med.", "side": "P", "view": "back", "x": 68, "y": 314}
NOTES_OK = ["Lehce, nohy svěží.", "Běželo se výborně, tempo samo.", "Trochu vítr, jinak v pohodě.",
            "Po práci, hlava se vyčistila.", "Kopce šly lépe než minulý týden."]
NOTES_TIRED = ["Nohy těžké od začátku, druhá půlka dřina.", "Delší než obvykle, ke konci jsem to cítil.",
               "Achilovka ráno ztuhlá, po rozběhání povolila.", "Spal jsem špatně, tep vyšší než normálně."]


def _stale(r: models.Runner | None) -> bool:
    if r is None:
        return True
    meta = r.onboarding_json or {}
    return meta.get("demoBuiltFor") != E.iso_date(E.today_date()) or meta.get("v") != BUILD_VERSION


def ensure(db: DBSession) -> str:
    """Return the tutorial runner id, rebuilding its data first when it is stale."""
    r = db.query(models.Runner).filter(models.Runner.id == TUTORIAL_RID).first()
    if not _stale(r):
        return TUTORIAL_RID
    with _lock:
        db.expire_all()
        r = db.query(models.Runner).filter(models.Runner.id == TUTORIAL_RID).first()
        if _stale(r):
            _rebuild(db)
    return TUTORIAL_RID


# ------------------------------------------------------------------ wipe
_BY_RUNNER = [
    models.Conclusion, models.InjuryReport, models.ActivityFeedback, models.ActivityStream, models.Activity,
    models.DailyMetric, models.Checkin, models.Assessment, models.EngineHistoryCache, models.Triage,
    models.CareAssignment, models.AccessLog, models.Booking, models.RtrSession, models.ReturnToRun,
    models.Message, models.Race, models.CoachText, models.EngineDailySnapshot, models.EngineAlert,
    models.DeviceHistory, models.Integration, models.IngestToken, models.GarminSession,
]


def _wipe(db: DBSession, rid: str) -> None:
    pids = [p for (p,) in db.query(models.Program.id).filter(models.Program.runner_id == rid)]
    if pids:
        db.query(models.Exercise).filter(models.Exercise.program_id.in_(pids)).delete(synchronize_session=False)
        db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id.in_(pids)).delete(synchronize_session=False)
        db.query(models.Program).filter(models.Program.id.in_(pids)).delete(synchronize_session=False)
    for m in _BY_RUNNER:
        db.query(m).filter(m.runner_id == rid).delete(synchronize_session=False)
    db.flush()


# ------------------------------------------------------------------ build
def _rebuild(db: DBSession) -> None:
    rid = TUTORIAL_RID
    rnd = random.Random(20260927)
    today = E.today_date()
    iso = lambda d: E.iso_date(today - timedelta(days=d))   # noqa: E731
    _wipe(db, rid)

    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is None:
        r = models.Runner(id=rid, name="Ukázkový běžec")
        db.add(r)
    r.name, r.bib, r.birth_year, r.sex, r.city = "Ukázkový běžec", "0000", 1990, "m", "Praha"
    r.goal_race, r.goal_date = "Podzimní maraton", iso(-56)
    r.prior_injury, r.prior_injury_months_ago, r.prior_injury_side = "Holenní kost", 26, "left"
    r.prior_injury_date = iso(790)
    r.hr_max, r.device, r.engine_mode = 188, "Garmin Forerunner 965", "v3"
    r.physio_interest, r.physio_interest_at = True, iso(20)
    monday = today - timedelta(days=today.weekday())
    r.coach_consent, r.cycle_override = False, {"week": E.iso_date(monday), "pos": 2}   # 2nd build week
    r.onboarding_json = {"demoBuiltFor": E.iso_date(today), "v": BUILD_VERSION}
    db.flush()

    db.add(models.Integration(id="int_tutorial", runner_id=rid, provider="garmin", status="demo", last_sync_at=E.now_iso(),
                              fields=["vert_ratio_pct", "gct_ms", "gct_balance_l", "cadence_spm", "stride_len_m",
                                      "hrv_ms", "resting_hr", "sleep_h"]))
    db.add(models.DeviceHistory(runner_id=rid, device=r.device, source="registration", recorded_at=iso(DAYS)))

    acts = _activities(rnd, today)
    rows = []
    for a in acts:
        row = models.Activity(runner_id=rid, provider="demo", **a)
        db.add(row)
        rows.append(row)
    db.flush()

    _daily_metrics(db, rid, rnd, iso)
    _feedback(db, rid, rnd, rows, today)
    _checkins(db, rid, rnd, iso)
    _races(db, rid, iso)
    db.flush()
    _care(db, rid, iso)
    db.commit()
    E.recompute_assessment(db, rid)


def _activities(rnd: random.Random, today) -> list[dict]:
    from .seed import _synth_elevation_profile
    out = []
    b_cad, b_vr, b_gct, b_bal = 172.0, 7.4, 248.0, 49.8
    for d in range(DAYS, 0, -1):          # nothing today, so the day's limits stay whole
        day = today - timedelta(days=d)
        wd = day.weekday()
        block = ((today - timedelta(days=today.weekday())) - (day - timedelta(days=wd))).days // 7
        cyc = [1.0, 0.9, 0.75, 1.08][block % 4]   # this week = 2nd build week of the 4-week cycle
        mult = cyc * (0.9 + 0.1 * min(1, (DAYS - d) / 60))
        # The runner's week is laid out so that *today* is their long-run day (vwd 5),
        # whatever weekday the tour is opened on: the Trénink tab then always has a
        # full session with limits to show.
        vwd = (5 - d) % 7
        plan = None
        if vwd == 1:
            plan = ("easy", 9.0)
        elif vwd == 2:
            plan = ("tempo", 11.0) if block % 2 else ("intervals", 10.0)
        elif vwd == 3 and (d <= 7 or block % 4 != 2):
            plan = ("easy", 8.0)
        elif vwd == 4 and d % 14 < 7 and d > 7:
            out.append(_cycling(day, rnd))
            continue
        elif vwd == 5:
            plan = ("long", 18.0)
        elif vwd == 6:
            plan = ("trail", 8.0) if d <= 7 else ("trail" if rnd.random() < 0.5 else "recovery", 6.5)
        if plan is None:
            continue
        kind, km = plan
        dist = round(max(4.0, km * mult * rnd.uniform(0.93, 1.07)), 1)
        pace = {"easy": 328, "recovery": 342, "long": 335, "tempo": 282, "intervals": 292, "trail": 372}[kind] + rnd.gauss(0, 6)
        surface = "trail" if kind == "trail" else ("treadmill" if (kind == "easy" and rnd.random() < 0.08) else "road")
        steep = surface == "trail" and d <= 7        # last week's steep trail: descent above capacity
        asc = round(dist * (rnd.uniform(52, 60) if steep else rnd.uniform(22, 38))) if surface == "trail" else round(dist * rnd.uniform(1, 7))
        dsc = round(asc * rnd.uniform(0.9, 1.1))
        prog = E.clamp((20 - d) / 20, 0, 1)
        stride = round(1.02 + (330 - pace) / 700 + rnd.gauss(0, 0.015), 2)
        vr = b_vr + (0.3 if surface == "trail" else 0) + (pace - 320) / 500 + rnd.gauss(0, 0.12) + prog * 0.03
        gct = b_gct + (10 if surface == "trail" else 0) + (pace - 320) * 0.16 + rnd.gauss(0, 3) + prog * 6
        bal = b_bal + rnd.gauss(0, 0.2) - prog * 0.8
        cad = b_cad - (3 if surface == "trail" else 0) - (pace - 320) * 0.03 + rnd.gauss(0, 1.2) - prog * 0.8
        hr = {"easy": 142, "recovery": 136, "long": 148, "tempo": 168, "intervals": 160, "trail": 147}[kind] + rnd.gauss(0, 2.5)
        rpe = {"easy": 3, "recovery": 2, "long": 5, "tempo": 7, "intervals": 8, "trail": 4}[kind] + (1 if steep else 0)
        title = {"easy": "Ranní klus", "recovery": "Rozklusání", "long": "Dlouhý běh", "tempo": "Tempo",
                 "intervals": "Intervaly 6× 1 km", "trail": "Lesní běh"}[kind]
        if surface == "treadmill":
            title = "Pás"
        drift = 1.06 if kind == "long" else 1.035
        out.append({
            "started_at": E.iso_date(day), "start_time": ["06:40", "07:10", "17:45", "18:20"][rnd.randrange(4)] if wd < 5 else "08:30",
            "title": title, "sport": "running", "distance_km": dist, "duration_min": round(dist * pace / 60, 1),
            "pace_s_km": round(pace), "avg_hr": round(hr), "surface": surface, "ascent_m": asc, "descent_m": dsc,
            "temp_c": round(12 + 9 * math.sin((day.timetuple().tm_yday - 100) / 365 * 2 * math.pi) + rnd.gauss(0, 3)),
            "cadence_spm": round(cad), "stride_len_m": stride, "vert_osc_cm": round(vr * stride, 1),
            "vert_ratio_pct": round(vr, 2), "gct_ms": round(gct), "gct_balance_l": round(bal, 2),
            "vr_thirds": [round(vr * 0.99, 2), round(vr, 2), round(vr * (1.012 if kind == "long" else 1.006), 2)],
            "hr_thirds": [round(hr * 0.97), round(hr), round(hr * drift)],
            "pace_thirds": [round(pace * 1.01), round(pace), round(pace * 0.99)],
            "rpe": int(E.clamp(rpe, 1, 10)),
            "elevation_profile": _synth_elevation_profile(rnd.random, dist, asc, dsc, surface),
        })
    return out


def _cycling(day, rnd) -> dict:
    return {"started_at": E.iso_date(day), "start_time": "17:30", "title": "Kolo", "sport": "cycling",
            "distance_km": round(rnd.uniform(28, 38), 1), "duration_min": round(rnd.uniform(70, 90)),
            "avg_hr": round(rnd.uniform(122, 132)), "surface": "road", "ascent_m": round(rnd.uniform(150, 320)),
            "descent_m": round(rnd.uniform(150, 320)), "rpe": 3}


def _daily_metrics(db, rid, rnd, iso) -> None:
    for d in range(DAYS, -1, -1):
        stress = E.clamp((8 - d) / 8, 0, 1) * 0.35
        sleep = round(7.4 + rnd.gauss(0, 0.45) - stress * 0.7, 1)
        deep = round(sleep * 60 * rnd.uniform(0.16, 0.2) * (1 - stress * 0.2))
        rem = round(sleep * 60 * rnd.uniform(0.2, 0.24))
        awake = round(rnd.uniform(15, 30) + stress * 15)
        if d <= 2:                                   # fixed recent nights: a steady readiness in the tour
            sleep = [7.1, 6.9, 7.2][d]
        db.add(models.DailyMetric(
            runner_id=rid, date=iso(d), sleep_h=sleep, deep_min=deep, rem_min=rem,
            light_min=max(0, round(sleep * 60 - deep - rem)), awake_min=awake,
            sleep_efficiency=round(sleep * 60 / (sleep * 60 + awake), 3),
            hrv_ms=[54, 55, 57][d] if d <= 2 else round(58 * (1 - stress * 0.13) + rnd.gauss(0, 3.5)),
            resting_hr=[50, 50, 49][d] if d <= 2 else round(49 * (1 + stress * 0.07) + rnd.gauss(0, 1.2)),
            body_battery=round(E.clamp(78 - stress * 22 + rnd.gauss(0, 7), 10, 100)),
            stress_avg=round(26 + stress * 9 + rnd.gauss(0, 3)), steps=round(rnd.gauss(9500, 1800)), source="garmin",
        ))


def _pt(base, sev, kind, when, note=None, pid="pa", jitter=None):
    return {"id": pid, "region": base["region"], "side": base["side"], "view": base["view"],
            "x": base["x"] + (jitter or (0, 0))[0], "y": base["y"] + (jitter or (0, 0))[1],
            "severity": sev, "type": kind, "when": when, "note": note}


def _feedback(db, rid, rnd, rows, today) -> None:
    runs = sorted([a for a in rows if a.sport == "running"], key=lambda a: a.started_at)
    recent = [a for a in runs if E.days_between(a.started_at, E.iso_date(today)) <= 35]
    niggles = 0
    for a in recent[:-2]:                               # the last two runs wait for a rating
        d = E.days_between(a.started_at, E.iso_date(today))
        spike = d <= 8                                  # the steep trail week
        nig = a.title == "Dlouhý běh" and d == 7 and not niggles   # one sore long run, not a pattern
        niggles += nig
        pts = []
        if nig:
            sev = 2
            pts.append(_pt(SITE, sev, "ztuhlost", "na začátku",
                           "Prvních pár kilometrů ztuhlá, pak povolila.", jitter=(rnd.uniform(-2, 2), rnd.uniform(-3, 3))))
            if a.title == "Dlouhý běh":
                pts.append(_pt(CALF, 2, "ztuhlost", "ráno po", "Spíš ztuhlost než bolest.", pid="pb"))
        tired = spike and a.title in ("Dlouhý běh", "Lesní běh")
        db.add(models.ActivityFeedback(
            activity_id=a.id, runner_id=rid, submitted_at=a.started_at, pain_points=pts,
            feeling=3 if tired else (4 if rnd.random() < 0.75 else 5), legs=3 if tired else 4,
            stiffness_pre=3 if nig else 2, pain_during=2 if nig else 0,
            pain_site="Achillova šlacha (P)" if nig else None, niggle=nig, rpe=a.rpe,
            note=(rnd.choice(NOTES_TIRED) if (tired or nig) else rnd.choice(NOTES_OK)) if rnd.random() < 0.7 else None,
        ))


def _checkins(db, rid, rnd, iso) -> None:
    for d in range(20, -1, -1):
        if d in (3, 7, 11, 16):
            continue
        pain = 1 if d == 2 else 0
        db.add(models.Checkin(
            runner_id=rid, submitted_at=datetime.combine(date.fromisoformat(iso(d)), time(7, 15), E.LOCAL_TZ).isoformat(), pain_score=pain,
            pain_site="Achillova šlacha" if pain else None,
            pain_points=[_pt(SITE, pain, "ztuhlost", "ráno")] if pain else [],
            soreness=int(E.clamp(round(2 + (8 - min(d, 8)) * 0.35 + rnd.gauss(0, 0.5)), 0, 10)),
            stress=2 if d > 6 else 3, mood=3 if d > 6 else 2,
            limits_movement=False, run_modified=False, limping=False,
            notes="Ráno ztuhlá Achilovka, po pár minutách chůze v pohodě." if d == 2 else None,
        ))
    for w, sev in ((3, 0), (2, 0), (1, 0), (0, 0)):
        qp = sev and 8
        db.add(models.InjuryReport(
            runner_id=rid, submitted_at=datetime.combine(date.fromisoformat(iso(w * 7 + 1)), time(19, 0), E.LOCAL_TZ).isoformat(), source="self_weekly",
            status="active" if sev else "none", q_participation=0, q_volume=0,
            q_performance=8 if sev >= 17 else 0, q_pain=qp or 0, severity=sev,
            body_region="Achillova šlacha" if sev else None, body_side="P" if sev else None,
            pain_points=[{"region": "Achillova šlacha", "side": "P", "kind": "pain"}] if sev else [],
        ))


def _races(db, rid, iso) -> None:
    now = E.now_iso()
    db.add(models.Race(runner_id=rid, date=iso(-20), name="Kontrolní půlmaraton", distance_km=21.1, priority="B", created_at=now))
    db.add(models.Race(runner_id=rid, date=iso(-56), name="Podzimní maraton", distance_km=42.2, priority="A", created_at=now))


def _care(db, rid, iso) -> None:
    physio = db.query(models.Physio).order_by(models.Physio.id.asc()).first()
    if physio is None:
        return
    pid = physio.id
    def at(d, hm="10:00"):                        # timezone-aware, like every stored timestamp
        h, m = map(int, hm.split(":"))
        return datetime.combine(date.fromisoformat(iso(d)), time(h, m), E.LOCAL_TZ).isoformat()
    db.add(models.CareAssignment(physio_id=pid, runner_id=rid, status="active", created_at=at(20)))
    past = models.Booking(runner_id=rid, physio_id=pid, slot_at=at(13, "16:00"), kind="exam", status="confirmed",
                          price_czk=1290, payer="self", created_at=at(18))
    upcoming = models.Booking(runner_id=rid, physio_id=pid, slot_at=at(-3, "17:30"), kind="gait_analysis",
                              status="confirmed", price_czk=1490, payer="self", created_at=at(2),
                              prep_info="Vezměte si běžecké boty, ve kterých nejčastěji běháte, a kraťasy.")
    db.add_all([past, upcoming])
    db.flush()
    db.add(models.Conclusion(
        booking_id=past.id, runner_id=rid, physio_id=pid, status="approved", created_at=at(13, "17:00"), approved_at=at(13, "18:10"),
        transcript_source="asr",
        finding="Přetížení pravé Achillovy šlachy bez známek poškození, snížená síla lýtka vpravo.",
        summary="Achillova šlacha vpravo reaguje na rychlé zvýšení objemu. Doporučuji excentrické posilování lýtka "
                "5× týdně, zvyšovat objem nejvýše o 10 až 15 % týdně a bolest při běhu držet do 3/10. "
                "Kontrola s analýzou běhu za dva týdny.",
    ))
    prog = models.Program(runner_id=rid, physio_id=pid, name="Lýtko a Achillova šlacha: posílení", phase="rebuild",
                          weeks=4, started_on=iso(12), active=True, status="sent", sent_at=at(12))
    db.add(prog)
    db.flush()
    for k, (n, dose, pw, cue) in enumerate(lib_for("Achillova šlacha")):
        db.add(models.Exercise(program_id=prog.id, name=n, dose=dose, per_week=pw, cue=cue,
                               done_count=[9, 7, 5, 8, 6][k % 5], target_count=12))
    db.add(models.ProgramRevision(program_id=prog.id, physio_id=pid, at=at(5),
                                  note="Po zprávě o ranní ztuhlosti jsem snížil zátěž výponů a přidal mobilitu hlezna.",
                                  changes=["Excentrické výpony: 3× 15 → 3× 12", "Přidána mobilita hlezna 1× denně"]))
    for sender, body, d, hm in [
        ("physio", "Posílám program na lýtko a Achillovku. Výpony dělejte pomalu, 3 vteřiny dolů.", 12, "09:10"),
        ("runner", "Díky. Od pondělí začínám maratonský blok, přidám jeden běh týdně. Je to v pořádku?", 9, "20:05"),
        ("physio", "Ano, ale objem zvedejte postupně. V datech hlídejte zátěž, ať nejde nad kapacitu.", 9, "21:30"),
        ("runner", "Po sobotním dlouhém běhu mám ráno ztuhlou Achilovku, po rozchození to povolí.", 5, "07:40"),
        ("physio", "Vidím skok v objemu i klesání. Upravil jsem program a tento týden zkraťte dlouhý běh. "
                   "Ve čtvrtek se podíváme na techniku při analýze běhu.", 5, "12:15"),
    ]:
        db.add(models.Message(runner_id=rid, physio_id=pid, sender=sender, body=body, created_at=at(d, hm)))
