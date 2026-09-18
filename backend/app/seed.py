"""One-time deterministic demo-data seeder — port of core.js's build(),
CLIN/PHYS/EMPS/PARS/RUNS and genActs() (original lines ~550-754). Also
creates one real login per seeded contact (all password "demo1234", see
README) so the app is testable immediately without registering fresh.
"""
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from . import models
from .content import lib_for
from .metrics import engine as E
from .security import hash_password

DEMO_PASSWORD = "demo1234"


def mulberry32(seed: int):
    """Same PRNG as the original prototype's core.js — 32-bit-wrapping
    xorshift-multiply, seeded for a reproducible demo dataset."""
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t ^= t >> 14
        return (t & 0xFFFFFFFF) / 4294967296

    return rand


def uid(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


CLIN = [
    ("Fyzio Holešovice", "Praha 7"), ("Pohyb Lab Smíchov", "Praha 5"),
    ("Sportfyzio Brno-střed", "Brno"), ("Rehab Ostrava Poruba", "Ostrava"),
]
PHYS = [
    ("Mgr. Tereza Havlíčková", 0, "Běžecká biomechanika", 4.9, 11,
     ["Achillova šlacha", "běžecká technika", "návrat k běhu"], 1190,
     "Specializuji se na běžeckou biomechaniku a analýzu chůze. 11 let praxe, spolupráce s běžeckými kluby."),
    ("Mgr. Jan Doubrava", 1, "MSK fyzioterapie", 4.7, 8,
     ["koleno", "kyčel", "silový trénink"], 1090,
     "Muskuloskeletální fyzioterapie a silová rehabilitace. Vedu pacienty od akutní fáze po plný návrat."),
    ("Mgr. Petra Nováková", 2, "Sportovní fyzioterapie", 4.8, 13,
     ["stresové zlomeniny", "holeň", "prevence"], 1150,
     "Sportovní fyzioterapie se zaměřením na kostní stres a přetížení dolní končetiny."),
    ("Mgr. Ondřej Vaněk", 3, "Trail a ultra", 4.6, 7,
     ["trail", "excentrická zátěž", "IT pás"], 990,
     "Trailoví a ultra běžci — excentrická kapacita, klesání, dlouhé objemy. Sám běhám ultra."),
]
EMPS = [
    ("Hexanet s.r.o.", "Praha", 180, "outcome", 486000),
    ("Moravia Logistics", "Brno", 95, "standard", 212000),
    ("Kolbe Engineering", "Ostrava", 60, "pilot", 0),
]
PARS = [
    ("Běžecká speciálka Letná", "shop", "Praha 7", "LETNA15", 15),
    ("Trailpoint", "shop", "Praha 5", "TRAILP", 15),
    ("RunClub Stromovka", "club", "Praha 7", "STROM", 10),
    ("Běhej lesy", "race", "—", "BLESY", 8),
]
RUNS = [
    dict(n="Adéla Kučerová", by=1991, sx="f", city="Praha", race="Pražský půlmaraton", gd=42, base=46, rpw=5,
         pat="steady", sig="vr_drift", emp=0, par=0, pi="Achillova šlacha", pim=8, pain=4,
         site="Achillova šlacha (P)", sore=6, sleep=6.2, stress=3, trail=.15, fbRate=.85),
    dict(n="Marek Beneš", by=1985, sx="m", city="Praha", race="ORLEN Pražský maraton", gd=70, base=58, rpw=6,
         pat="steady", sig="clean", emp=0, par=2, pi=None, pim=None, pain=1, site=None,
         sore=3, sleep=7.4, stress=2, trail=.1, fbRate=.55),
    dict(n="Lucie Horáková", by=1996, sx="f", city="Brno", race="Běhej lesy Brdy", gd=28, base=31, rpw=4,
         pat="return", sig="gct_asym", emp=1, par=3, pi="Stresová reakce holeně", pim=5, pain=2,
         site="Holeň (L)", sore=4, sleep=7.1, stress=3, trail=.4, fbRate=.9),
    dict(n="Tomáš Řehák", by=1979, sx="m", city="Ostrava", race="Krkonošská 50", gd=96, base=60, rpw=6,
         pat="steady", sig="decouple", emp=2, par=1, pi="IT band", pim=14, pain=2, site=None,
         sore=5, sleep=6.8, stress=3, trail=.75, fbRate=.6),
    dict(n="Veronika Šimková", by=2000, sx="f", city="Praha", race="První 10 km", gd=35, base=14, rpw=3,
         pat="beginner", sig="lowdata", emp=0, par=0, pi=None, pim=None, pain=1, site=None,
         sore=4, sleep=7.2, stress=2, trail=.1, fbRate=.4),
    dict(n="Pavel Urban", by=1988, sx="m", city="Brno", race="Moravský půlmaraton", gd=21, base=45, rpw=5,
         pat="taper", sig="clean", emp=1, par=2, pi=None, pim=None, pain=0, site=None,
         sore=2, sleep=7.6, stress=2, trail=.15, fbRate=.7),
    dict(n="Klára Bártová", by=1993, sx="f", city="Praha", race="UniCredit Prague Relay", gd=14, base=26, rpw=4,
         pat="steady", sig="clean", emp=0, par=2, pi=None, pim=None, pain=0, site=None,
         sore=3, sleep=7.3, stress=3, trail=.1, fbRate=.5),
    dict(n="Jiří Málek", by=1975, sx="m", city="Ostrava", race="Ostravský maraton", gd=56, base=50, rpw=6,
         pat="spike", sig="load_spike", emp=2, par=1, pi="Plantární fascie", pim=3, pain=7,
         site="Chodidlo (L)", sore=8, sleep=5.6, stress=4, trail=.1, fbRate=.95),
    dict(n="Nikola Pešková", by=1998, sx="f", city="Praha", race="Valentýnský běh", gd=60, base=38, rpw=5,
         pat="steady", sig="clean", emp=0, par=0, pi=None, pim=None, pain=0, site=None,
         sore=2, sleep=7.5, stress=1, trail=.15, fbRate=.45),
    dict(n="Radek Souček", by=1990, sx="m", city="Brno", race="Běhej lesy Klínovec", gd=49, base=56, rpw=7,
         pat="steady", sig="mono", emp=1, par=3, pi=None, pim=None, pain=1, site=None,
         sore=4, sleep=6.9, stress=3, trail=.5, fbRate=.65),
    # --- Demo login cases (appended so existing indices stay stable) ---------
    # #9 „Tichý drift": mechanika se plíživě mění (drift), ale zátěž i regenerace
    # drží v normě → kvadrant SILENT. Předchozí zranění = frailty, které drift
    # zesílí; žádný objemový skok, dobrý spánek → zátěžová osa nízko.
    dict(n="Tichý drift", by=1992, sx="m", city="Praha", race="Demo", gd=42, base=40, rpw=5,
         pat="steady", sig="gct_asym", emp=None, par=None, pi="Achillova šlacha", pim=6, pain=1,
         site="Achillova šlacha (P)", sore=3, sleep=7.6, stress=1, trail=.15, fbRate=.5),
    # #10 „Kritické přetížení": objemový skok + drift mechaniky + rozbitá
    # regenerace + čerstvé zranění → obě osy vysoko → kvadrant CRITICAL.
    dict(n="Kritické přetížení", by=1986, sx="m", city="Praha", race="Demo", gd=56, base=64, rpw=6,
         pat="spike", sig="load_spike", emp=None, par=None, pi="Achillova šlacha", pim=2, pain=8,
         site="Achillova šlacha (P)", sore=8, sleep=5.2, stress=5, trail=.1, fbRate=.9),
]

DAY_TITLES = {
    "road": ["Ranní klus", "Tempo", "Volný běh", "Dlouhý běh", "Rozklusání", "Intervaly"],
    "trail": ["Terén", "Kopce", "Trailový okruh", "Lesní běh"],
    "treadmill": ["Pás"],
}

SITE_MAP = {
    "Achillova šlacha (P)": {"region": "Achillova šlacha", "side": "P", "view": "back", "x": 96, "y": 362},
    "Holeň (L)": {"region": "Holenní kost", "side": "L", "view": "front", "x": 74, "y": 322},
    "Chodidlo (L)": {"region": "Nárt", "side": "L", "view": "front", "x": 92, "y": 381},
    "Koleno (L)": {"region": "Přední koleno", "side": "L", "view": "front", "x": 92, "y": 283},
}
PAIN_TYPES = ["ostrá", "tupá", "píchavá", "ztuhlost"]
PAIN_WHENS = ["na začátku", "v průběhu", "ke konci", "ráno po"]


def _synth_elevation_profile(rand, distance_km, ascent_m, descent_m, surface):
    """Synthetic distance/altitude stream, scaled so its cumulative
    ascent/descent matches the activity's real totals but spread across
    segments of varying gradient — trail runs get rougher, more varied
    segments than road, so the gradient-bucket histogram has real texture
    to show instead of one flat average slope. Mirrors what a downsampled
    real FIT elevation stream would look like (see fitreader.py)."""
    dist_m = (distance_km or 0) * 1000
    if dist_m < 200:
        return None
    n_seg = max(6, min(30, round(dist_m / 400)))
    seg_len = dist_m / n_seg
    variability = 2.4 if surface == "trail" else 0.7
    flat_chance = 0.2 if surface == "trail" else 0.5
    raw_desc = [0.0] * n_seg
    raw_asc = [0.0] * n_seg
    for i in range(n_seg):
        if rand() >= flat_chance:
            raw_desc[i] = rand() ** variability
        if rand() >= flat_chance:
            raw_asc[i] = rand() ** variability
    sum_desc, sum_asc = sum(raw_desc), sum(raw_asc)
    scale_desc = (descent_m or 0) / sum_desc if sum_desc else 0
    scale_asc = (ascent_m or 0) / sum_asc if sum_asc else 0
    altitude = 220 + rand() * 350
    points = [{"distance_m": 0.0, "altitude_m": round(altitude, 1)}]
    dist = 0.0
    for i in range(n_seg):
        dist += seg_len
        altitude += raw_asc[i] * scale_asc - raw_desc[i] * scale_desc
        points.append({"distance_m": round(dist, 1), "altitude_m": round(altitude, 1)})
    return points


def gen_activities(r: dict, rand, start_id: int) -> list[dict]:
    out = []
    aid = start_id
    days = 26 if r["sig"] == "lowdata" else 84
    b_cad = 168 + round(rand() * 12)
    b_vr = 6.9 + rand() * 1.4
    b_gct = 246 + rand() * 26
    b_bal = 49.4 + rand() * 1.1
    for d in range(days - 1, -1, -1):
        wk = (days - 1 - d) // 7
        mult = 1.0
        if r["pat"] == "spike":
            mult = 2.1 if d < 7 else (0.9 if d < 28 else 0.88)
        elif r["pat"] == "return":
            mult = 0.45 + min(1, (11 - wk) / 9) * 0.55
        elif r["pat"] == "taper":
            mult = 0.55 if d < 12 else 1
        elif r["pat"] == "beginner":
            mult = 0.6 + wk * 0.06
        elif r["pat"] == "steady":
            mult = 0.94 + math.sin(wk / 2) * 0.07
        if r["sig"] == "mono":
            mult = 0.97
        if r["sig"] == "decouple" and d < 7:
            mult *= 1.35
        if r["sig"] != "mono" and rand() > (r["rpw"] / 7) * (0.85 if r["pat"] == "return" else 1):
            continue
        is_trail = rand() < (0.95 if (r["sig"] == "decouple" and d < 7) else r["trail"])
        long_run = False if r["sig"] == "mono" else (rand() < 0.18)
        tgt = (r["base"] * mult) / r["rpw"] * (1.85 if long_run else 0.92)
        dist = max(3, E.r1(tgt * ((0.99 + rand() * 0.03) if r["sig"] == "mono" else (0.78 + rand() * 0.44))))
        pace_s = (330 if is_trail else 282) + rand() * (26 if r["sig"] == "mono" else 74) + (18 if long_run else 0)
        if is_trail:
            asc = round(dist * (16 + rand() * 26) * (1.5 if (r["sig"] == "decouple" and d < 7) else 1))
        else:
            asc = round(dist * (rand() * 7))
        dsc = round(asc * (0.85 + rand() * 0.3)) if is_trail else round(asc * 0.9)
        prog = E.clamp((21 - d) / 21, 0, 1)
        vr = b_vr + (0.35 if is_trail else 0) + (pace_s - 282) / 500 + (rand() - 0.5) * 0.3
        gct = b_gct + (11 if is_trail else 0) + (pace_s - 282) * 0.16 + (rand() - 0.5) * 8
        bal = b_bal + (rand() - 0.5) * 0.5
        cad = b_cad - (4 if is_trail else 0) + (rand() - 0.5) * 4
        if r["sig"] == "vr_drift":
            vr += prog * 0.85
        if r["sig"] == "gct_asym":
            bal -= prog * 1.9
            gct += prog * 7
        if r["sig"] == "load_spike":
            gct += prog * 11
        if r["sig"] == "decouple":
            vr += prog * 0.18
        dcp = (3.5 + prog * 6.5) if r["sig"] == "decouple" else (2.2 + rand() * 1.6)
        hr_b = 136 + rand() * 22
        surface = "trail" if is_trail else ("treadmill" if rand() < 0.06 else "road")
        titles = DAY_TITLES[surface]
        title = "Dlouhý běh" if (long_run and surface == "road") else titles[math.floor(rand() * len(titles))]
        out.append({
            "id": aid, "runner_id": r["id"], "provider": "demo", "started_at": E.day_ago(d),
            "title": title, "distance_km": dist, "duration_min": round(dist * pace_s / 60),
            "pace_s_km": round(pace_s), "avg_hr": round(hr_b + 8), "surface": surface,
            "ascent_m": asc, "descent_m": dsc, "temp_c": round(4 + rand() * 18),
            "cadence_spm": round(cad), "stride_len_m": E.r2(0.85 + rand() * 0.25 + (300 - pace_s) / 900),
            "vert_osc_cm": E.r1(vr * 1.28), "vert_ratio_pct": E.r2(vr), "gct_ms": round(gct),
            "gct_balance_l": E.r2(bal),
            "vr_thirds": [E.r2(vr * 0.985), E.r2(vr * (1 + dcp / 300)), E.r2(vr * (1 + dcp / 100))],
            "hr_thirds": [round(hr_b), round(hr_b * 1.03),
                          round(hr_b * (1 + (0.085 if r["sig"] == "load_spike" else 0.045)))],
            "pace_thirds": [round(pace_s * 0.99), round(pace_s), round(pace_s * 1.01)],
            "rpe": int(E.clamp(round(3 + rand() * 4 + (1.5 if mult > 1.3 else 0)), 1, 10)),
            "elevation_profile": _synth_elevation_profile(rand, dist, asc, dsc, surface),
        })
        aid += 1
    return out


def _mk_user(db, email, name, role, hashed, **fk):
    u = models.User(email=email, password_hash=hashed, name=name, role=role, provider="password",
                     created_at=E.now_iso(), **fk)
    db.add(u)
    db.flush()
    db.add(models.Settings(user_id=u.id))
    return u


def build_and_seed(db: DBSession) -> None:
    rand = mulberry32(20260812)

    clinics = []
    for i, (n, c) in enumerate(CLIN):
        clinic = models.Clinic(id=uid("cli", i + 1), name=n, city=c)
        db.add(clinic)
        clinics.append(clinic)

    physios = []
    for i, (n, ci, cr, rt, yrs, spec, price, bio) in enumerate(PHYS):
        physio = models.Physio(
            id=uid("phy", i + 1), clinic_id=clinics[ci].id, name=n, credential=cr, rating=rt,
            bio=bio, years_exp=yrs, specialties=spec, price_czk=price,
        )
        db.add(physio)
        physios.append(physio)

    employers = []
    for i, (n, c, s, p, v) in enumerate(EMPS):
        emp = models.Employer(id=uid("emp", i + 1), name=n, city=c, seats=s, plan=p, contract_value_czk=v)
        db.add(emp)
        employers.append(emp)

    partners = []
    for i, (n, k, c, code, pct) in enumerate(PARS):
        par = models.Partner(id=uid("par", i + 1), name=n, kind=k, city=c, referral_code=code, commission_pct=pct)
        db.add(par)
        partners.append(par)
    db.flush()

    # Availability slots per physio — next ~2 weeks of weekdays, a few times
    # a day, not every slot offered (so the browse view looks realistic).
    slot_base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for physio in physios:
        for d in range(1, 15):
            day = slot_base + timedelta(days=d)
            if day.weekday() >= 5:  # weekend
                continue
            for hour in (9, 11, 14, 16):
                if rand() < 0.45:
                    continue
                db.add(models.PhysioSlot(
                    physio_id=physio.id, slot_at=day.replace(hour=hour).isoformat(),
                    duration_min=45, status="open", created_at=E.now_iso(),
                ))
    db.flush()

    devices = ["Garmin Forerunner 965", "Garmin Fenix 8", "Coros Pace Pro"]
    providers = ["garmin", "garmin", "coros"]
    # A subset has already opted into the physio service (consent gate); the
    # rest demonstrate the gate — invisible to physios until they opt in.
    consented = {0, 2, 3, 6, 8}
    runner_rows = []

    for i, s in enumerate(RUNS):
        rid = uid("run", i + 1)
        goal_date = E.iso_date(E.today_date() + timedelta(days=s["gd"]))
        r = models.Runner(
            id=rid, bib=str(1041 + i * 7), name=s["n"], birth_year=s["by"], sex=s["sx"], city=s["city"],
            goal_race=s["race"], goal_date=goal_date,
            employer_id=employers[s["emp"]].id if s["emp"] is not None else None,
            partner_id=partners[s["par"]].id if s["par"] is not None else None,
            prior_injury=s["pi"], prior_injury_months_ago=s["pim"], device=devices[i % 3],
            physio_interest=(i in consented),
            physio_interest_at=(E.now_iso() if i in consented else None),
        )
        db.add(r)
        db.flush()
        runner_rows.append(r)

        db.add(models.Integration(
            id=uid("int", i + 1), runner_id=rid, provider=providers[i % 3], status="demo",
            last_sync_at=E.now_iso(),
            fields=["vert_ratio_pct", "gct_ms", "gct_balance_l", "cadence_spm", "stride_len_m",
                    "hrv_ms", "resting_hr", "sleep_h"],
        ))
        if i == 8:  # Nikola — one demo case of a mid-baseline watch swap, see confidence()'s deviceChanged flag
            db.add(models.DeviceHistory(runner_id=rid, device="Garmin Forerunner 965", source="registration",
                                         recorded_at=E.day_ago(E.BASE_FROM)))
            db.add(models.DeviceHistory(runner_id=rid, device=r.device, source="garmin_sync",
                                         recorded_at=E.day_ago(20)))
        else:
            db.add(models.DeviceHistory(runner_id=rid, device=r.device, source="registration",
                                         recorded_at=E.day_ago(E.BASE_FROM)))

        rgen = dict(s, id=rid, base=s["base"], rpw=s["rpw"], pat=s["pat"], sig=s["sig"], trail=s["trail"])
        acts = gen_activities(rgen, rand, 1)
        for a in acts:
            a = dict(a)
            a.pop("id", None)
            db.add(models.Activity(**a))
        db.flush()
        act_rows = (
            db.query(models.Activity).filter(models.Activity.runner_id == rid)
            .order_by(models.Activity.started_at.asc(), models.Activity.id.asc()).all()
        )

        # denní metriky z hodinek — 40 dní, u některých ručně opravené
        hrv_b = 42 + rand() * 28
        rhr_b = 46 + rand() * 10
        for d in range(39, -1, -1):
            prog = E.clamp((14 - d) / 14, 0, 1)
            stress = prog if s["sig"] == "load_spike" else 0
            manual = (s["sig"] == "load_spike" and d == 1) or (s["sig"] == "vr_drift" and d == 3)
            sleep_raw = E.r1(s["sleep"] + (rand() - 0.5) * 1.5 - stress * 1.1)
            db.add(models.DailyMetric(
                runner_id=rid, date=E.day_ago(d),
                sleep_h=E.r1(sleep_raw + 1.3) if manual else sleep_raw,
                hrv_ms=round(hrv_b * (1 - stress * 0.22) + (rand() - 0.5) * 7),
                resting_hr=round(rhr_b * (1 + stress * 0.13) + (rand() - 0.5) * 3),
                body_battery=round(E.clamp(70 - stress * 30 + (rand() - 0.5) * 22, 5, 100)),
                source="manual" if manual else "garmin",
                original_sleep_h=sleep_raw if manual else None,
                edited_at=E.now_iso() if manual else None,
                edit_note="Hodinky nezachytily usnutí, spal jsem déle." if manual else None,
            ))

        # hodnocení po tréninku
        cutoff28 = E.day_ago(28)
        for a in act_rows:
            if a.started_at <= cutoff28:
                continue
            if rand() > s["fbRate"]:
                continue
            days_ago_n = E.days_between(a.started_at, E.iso_date(E.today_date()))
            prog = E.clamp((21 - days_ago_n) / 21, 0, 1)
            nig = (rand() < (0.25 + prog * 0.5)) if s["pain"] >= 4 else (rand() < 0.06)
            base_site = SITE_MAP.get(s["site"]) if (nig and s["site"]) else None
            pts = []
            if base_site:
                pts.append({
                    "id": "pa", "region": base_site["region"], "side": base_site["side"], "view": base_site["view"],
                    "x": base_site["x"] + (rand() - 0.5) * 6, "y": base_site["y"] + (rand() - 0.5) * 8,
                    "severity": int(E.clamp(round(3 + prog * 4 + (rand() - 0.5) * 2), 1, 10)),
                    "type": PAIN_TYPES[math.floor(rand() * len(PAIN_TYPES))],
                    "when": PAIN_WHENS[math.floor(rand() * len(PAIN_WHENS))],
                    "note": "Ozvalo se to hlavně první dva kilometry, pak to povolilo." if rand() < 0.4 else None,
                })
                if nig and rand() < 0.25:
                    pts.append({
                        "id": "pb", "region": "Gastrocnemius med.", "side": base_site["side"], "view": "back",
                        "x": 92 if base_site["side"] == "L" else 68, "y": 314,
                        "severity": int(E.clamp(round(2 + prog * 2), 1, 10)), "type": "ztuhlost", "when": "ráno po",
                        "note": "Spíš ztuhlost než bolest.",
                    })
            db.add(models.ActivityFeedback(
                activity_id=a.id, runner_id=rid, submitted_at=a.started_at, pain_points=pts,
                feeling=int(E.clamp(round(4 - prog * (1.4 if s["pain"] >= 4 else 0) + (rand() - 0.5) * 1.2), 1, 5)),
                legs=int(E.clamp(round(4 - prog * (1.2 if s["pain"] >= 4 else 0.2) + (rand() - 0.5)), 1, 5)),
                pain_during=int(E.clamp(round(2 + prog * 4 + (rand() - 0.5) * 2), 0, 10)) if nig
                else int(E.clamp(round(rand() * 1.4), 0, 10)),
                pain_site=s["site"] if nig else None, niggle=nig, rpe=a.rpe,
                note="Ozvalo se to hlavně v prvních kilometrech, pak to povolilo." if (nig and rand() < 0.35) else None,
            ))

        for w in range(2, -1, -1):
            dr = w * (rand() * 0.8 + 0.4)
            db.add(models.Checkin(
                runner_id=rid, submitted_at=E.day_ago(w * 7 + 1),
                pain_score=int(E.clamp(round(s["pain"] - dr), 0, 10)),
                pain_site=s["site"] if s["pain"] > 0 else None,
                soreness=int(E.clamp(round(s["sore"] - dr * 0.7), 0, 10)),
                stress=int(E.clamp(round(s["stress"] - (0.4 if w else 0)), 1, 5)),
                notes="Bolí to první 2 km a pak zase po doběhu." if (w == 0 and s["pain"] >= 5) else None,
            ))

        if s["par"] is not None:
            db.add(models.Referral(
                partner_id=partners[s["par"]].id, runner_id=rid,
                created_at=E.day_ago(60 + math.floor(rand() * 50)),
                status="subscribed" if rand() > 0.35 else "signed_up",
                value_czk=390 if rand() > 0.35 else 0,
            ))

    db.commit()

    for r in runner_rows:
        E.recompute_assessment(db, r.id)

    # jeden pacient už v péči + jeden rozpracovaný draft
    a0, p0 = runner_rows[0], physios[0]
    prog = models.Program(
        runner_id=a0.id, physio_id=p0.id, name="Achillova šlacha — odlehčení", phase="offload", weeks=4,
        started_on=E.day_ago(9), active=True, status="sent", sent_at=E.day_ago(9),
    )
    db.add(prog)
    db.flush()
    for n, dose, pw, cue in lib_for(a0.prior_injury):
        db.add(models.Exercise(
            program_id=prog.id, name=n, dose=dose, per_week=pw, cue=cue,
            done_count=math.floor(rand() * 7) + 2, target_count=12,
        ))
    db.add(models.ProgramRevision(
        program_id=prog.id, physio_id=p0.id, at=E.day_ago(4),
        note="Pacientka hlásila bolest 4/10 po výponech — snížena frekvence z 6 na 5× týdně.",
        changes=["Excentrické výpony na schodu: 6× → 5× týdně"],
    ))
    db.add(models.CareAssignment(physio_id=p0.id, runner_id=a0.id, status="active", created_at=E.day_ago(9)))
    # recompute_assessment() above already created an (auto) triage row for a0 —
    # update it to 'claimed' rather than inserting a second row for the same runner.
    existing_triage = (
        db.query(models.Triage).filter(models.Triage.runner_id == a0.id)
        .order_by(models.Triage.id.desc()).first()
    )
    if existing_triage:
        existing_triage.status = "claimed"
        existing_triage.claimed_by = p0.id
    else:
        db.add(models.Triage(
            runner_id=a0.id, decision="physio_48h", headline="Objednat fyzioterapeuta do 48 hodin",
            status="claimed", claimed_by=p0.id, created_at=E.day_ago(9),
        ))
    db.add(models.Booking(
        runner_id=a0.id, physio_id=p0.id,
        slot_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        kind="gait_analysis", status="confirmed", price_czk=1490, payer="employer", created_at=E.day_ago(9),
    ))
    for sender, body, d in [
        ("system", "Triáž zachytila drift vertikálního poměru dřív, než se objevila bolest.", 9),
        ("physio", "Dobrý den Adélo, vertikální poměr vám za tři týdny vyskočil o 0,8 na srovnatelných "
                   "trasách. Vysadíme intervaly na 10 dní. Zvládnete video ze strany?", 9),
        ("runner", "Video pošlu zítra. Můžu zatím plavat?", 8),
        ("physio", "Plavání a kolo ano, bez odrazu z přední nohy. Bolest při běhu držte pod 3/10.", 8),
        ("runner", "Po výponech to včera bolelo 4/10, tak jsem jeden den vynechala.", 4),
        ("physio", "Dobře, snížil jsem frekvenci na 5× týdně. Uvidíme se ve čtvrtek.", 4),
    ]:
        db.add(models.Message(runner_id=a0.id, physio_id=p0.id, sender=sender, body=body, created_at=E.day_ago(d)))
    db.commit()

    # ---------------------------------------------------------- demo logins
    hashed = hash_password(DEMO_PASSWORD)
    _mk_user(db, "adela@demo.cz", "Adéla Kučerová", "runner", hashed, runner_id=runner_rows[0].id)
    _mk_user(db, "havlickova@fyzioholesovice.cz", "Mgr. Tereza Havlíčková", "physio", hashed, physio_id=physios[0].id)
    _mk_user(db, "hexanet@demo.cz", "Hexanet s.r.o. (HR)", "employer", hashed, employer_id=employers[0].id)
    _mk_user(db, "letna@demo.cz", "Běžecká speciálka Letná", "partner", hashed, partner_id=partners[0].id)
    # Two runner-only demo logins the app actually uses — password "demo",
    # e-mail derived from the name. #9 = silent drift, #10 = critical overload.
    demo_hashed = hash_password("demo")
    _mk_user(db, "tichydrift@demo.cz", "Tichý drift", "runner", demo_hashed, runner_id=runner_rows[10].id)
    _mk_user(db, "kritickepretizeni@demo.cz", "Kritické přetížení", "runner", demo_hashed, runner_id=runner_rows[11].id)
    db.commit()
