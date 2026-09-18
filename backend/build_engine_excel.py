"""Build the Garmin-palette + engine-v0.4 workbook for due-diligence.

Reads the cached Garmin pull (garmin_export_pull.py) and the runner's rows in
dosslap.db, and writes one .xlsx with:
  1. Návod                    — how to use + how to hand back new metrics
  2. Aktivity (raw)           — every activity, every field Garmin returns
  3. Denní wellness (raw)     — merged daily palette (HRV/RHR/sleep/steps/VO2max/kcal)
  4. Zdroje & API             — what's imported now vs what else Garmin offers
  5. Engine — dokumentace     — every signal: axis, práh, body, grade, vzorec, why/limit/clear
  6. Engine — týdenní osa     — assess() replay over the whole history (weekly)
  7. Engine — per-aktivita    — engine-derived inputs per run (bucket, VR, GCT…)
  8. Engine — mechanika detail— per-terrain-bucket baseline/now/z internals (latest)
"""
import json
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import Base
from app.metrics import engine as E
from app.metrics import sig_doc as SD

CACHE = "/tmp/garmin_export_cache.json"
DB = "dosslap.db"
RID = "run-0012"
OUT = "/Users/danieltrnovec/Downloads/dosslap_garmin_engine.xlsx"

HEAD = PatternFill("solid", fgColor="0A2540")
SUB = PatternFill("solid", fgColor="1B4A6B")
QFILL = {"stable": "C6EFCE", "overreaching": "FFEB9C", "silent": "BDD7EE", "critical": "FFC7CE"}


def _flat(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def header(ws, names, widths=None, row=1):
    ws.append(names)
    for i, n in enumerate(names, 1):
        c = ws.cell(row=row, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = (widths[i - 1] if widths else 14)
    ws.freeze_panes = f"A{row + 1}"
    ws.row_dimensions[row].height = 30


# ---------------------------------------------------------------- raw activities
ACT_PRIORITY = [
    "startTimeLocal", "__type", "activityName", "distance", "duration", "movingDuration",
    "averageHR", "maxHR", "averageSpeed", "maxSpeed", "avgGradeAdjustedSpeed",
    "elevationGain", "elevationLoss", "minElevation", "maxElevation",
    "averageRunningCadenceInStepsPerMinute", "maxRunningCadenceInStepsPerMinute",
    "avgStrideLength", "avgVerticalOscillation", "avgVerticalRatio",
    "avgGroundContactTime", "avgGroundContactBalance",
    "avgPower", "maxPower", "normPower", "avgDoubleCadence",
    "vO2MaxValue", "activityTrainingLoad", "aerobicTrainingEffect", "anaerobicTrainingEffect",
    "trainingEffectLabel", "calories", "bmrCalories", "waterEstimated",
    "minTemperature", "maxTemperature", "steps", "activityId",
]


def sheet_activities(wb, cache):
    acts = []
    for a in cache["activities"]:
        a = dict(a)
        a["__type"] = (a.get("activityType") or {}).get("typeKey")
        acts.append(a)
    acts.sort(key=lambda a: a.get("startTimeLocal") or "")
    allk = set()
    for a in acts:
        allk |= set(a.keys())
    cols = [k for k in ACT_PRIORITY if k in allk] + sorted(k for k in allk if k not in ACT_PRIORITY)
    ws = wb.create_sheet("Aktivity (raw)")
    header(ws, cols, widths=[20 if c == "startTimeLocal" else 16 for c in cols])
    for a in acts:
        ws.append([_flat(a.get(c)) for c in cols])
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(acts) + 1}"
    # tint running rows
    ti = cols.index("__type")
    for r in range(2, len(acts) + 2):
        if "running" in str(ws.cell(r, ti + 1).value or ""):
            ws.cell(r, ti + 1).fill = PatternFill("solid", fgColor="EAF1F8")


# ---------------------------------------------------------------- raw daily
def sheet_daily(wb, cache):
    d = cache["daily"]
    rows = {}

    def row(dt):
        return rows.setdefault(dt, {"date": dt})

    for r in d.get("hrv") or []:
        x = row(r["calendarDate"])
        x.update(hrv_lastNight=r.get("lastNightAvg"), hrv_weekly=r.get("weeklyAvg"),
                 hrv_baseline=r.get("baseline"), hrv_status=r.get("status"),
                 hrv_5min_high=r.get("lastNight5MinHigh"))
    for r in d.get("rhr") or []:
        row(r["calendarDate"])["resting_hr"] = r.get("value")
    for r in d.get("sleep") or []:
        v = r.get("values") or {}
        x = row(r["calendarDate"])
        s = v.get("totalSleepTimeInSeconds")
        x.update(sleep_h=round(s / 3600, 2) if s else None,
                 deep_min=(v.get("deepTime") or 0) // 60 or None,
                 light_min=(v.get("lightTime") or 0) // 60 or None,
                 rem_min=(v.get("remTime") or 0) // 60 or None,
                 awake_min=(v.get("awakeTime") or 0) // 60 or None,
                 sleep_score=v.get("sleepScore"), sleep_need_min=v.get("sleepNeed"),
                 avg_overnight_hrv=v.get("avgOvernightHrv"), hrv_7d_avg=v.get("hrv7dAverage"),
                 hrv_status_sleep=v.get("hrvStatus"), sleep_resting_hr=v.get("restingHeartRate"),
                 sleep_avg_hr=v.get("avgHeartRate"), respiration=v.get("respiration"),
                 spo2=v.get("spO2"), body_battery_change=v.get("bodyBatteryChange"),
                 skin_temp_c=v.get("skinTempC"))
    for r in d.get("steps") or []:
        x = row(r["calendarDate"])
        x.update(steps=r.get("totalSteps"), step_distance_m=r.get("totalDistance"), step_goal=r.get("stepGoal"))
    for r in d.get("vo2max") or []:
        gen = r.get("generic") or {}
        if gen.get("calendarDate"):
            row(gen["calendarDate"])["vo2max"] = gen.get("vo2MaxValue")
    for r in d.get("calories") or []:
        x = row(r["calendarDate"])
        x.update(cal_active=r.get("active"), cal_resting=r.get("resting"), cal_total=r.get("total"))

    cols = ["date", "hrv_lastNight", "hrv_weekly", "hrv_baseline", "hrv_5min_high", "hrv_status",
            "resting_hr", "sleep_h", "deep_min", "light_min", "rem_min", "awake_min",
            "sleep_score", "sleep_need_min", "avg_overnight_hrv", "hrv_7d_avg", "hrv_status_sleep",
            "sleep_resting_hr", "sleep_avg_hr", "respiration", "spo2", "body_battery_change",
            "skin_temp_c", "steps", "step_distance_m", "step_goal", "vo2max",
            "cal_active", "cal_resting", "cal_total"]
    ws = wb.create_sheet("Denní wellness (raw)")
    header(ws, cols, widths=[12] + [12] * (len(cols) - 1))
    for dt in sorted(rows):
        ws.append([_flat(rows[dt].get(c)) for c in cols])
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"


# ---------------------------------------------------------------- sources / API
def sheet_sources(wb):
    ws = wb.create_sheet("Zdroje & API")
    ws.append(["Co engine dnes bere z importu (garmin_live.map_activity / download_seed)"])
    ws["A1"].font = Font(bold=True, size=12)
    header(ws, ["Vrstva", "Pole platformy", "Zdroj z Garmin API"], widths=[16, 26, 44], row=3)
    imp = [
        ("aktivita", "distance_km", "distance (m)/1000"),
        ("aktivita", "duration_min / pace_s_km", "duration (s)"),
        ("aktivita", "avg_hr", "averageHR"),
        ("aktivita", "ascent_m / descent_m", "elevationGain / elevationLoss"),
        ("aktivita", "cadence_spm", "averageRunningCadenceInStepsPerMinute"),
        ("aktivita", "stride_len_m", "avgStrideLength (cm)/100"),
        ("aktivita", "vert_osc_cm", "avgVerticalOscillation"),
        ("aktivita", "vert_ratio_pct", "avgVerticalRatio"),
        ("aktivita", "gct_ms", "avgGroundContactTime"),
        ("aktivita", "gct_balance_l", "avgGroundContactBalance"),
        ("aktivita", "vo2max", "vO2MaxValue"),
        ("aktivita", "surface", "activityType.typeKey → road/trail/treadmill/track"),
        ("denní", "hrv_ms", "get_hrv_data_range → hrvSummaries.lastNightAvg"),
        ("denní", "resting_hr", "get_rhr_daily → value"),
        ("denní", "sleep_h", "get_sleep_daily → values.totalSleepTimeInSeconds"),
        ("denní", "steps", "get_daily_steps → totalSteps"),
    ]
    for r in imp:
        ws.append(list(r))
    start = ws.max_row + 2
    ws.cell(start, 1, "Co je dál k dispozici (zatím se nemapuje) — kandidáti na nové metriky").font = Font(bold=True, size=12)
    header(ws, ["Oblast", "Garmin API metoda", "Co dává / potenciál pro metriku"], widths=[16, 30, 60], row=start + 1)
    avail = [
        ("aktivita", "avgPower / normPower / maxPower", "běžecký výkon — objem/intenzita výkonu, W/kg trend"),
        ("aktivita", "aerobic/anaerobicTrainingEffect", "TE 0–5 na běh — akutní zátěžová dávka bez km"),
        ("aktivita", "activityTrainingLoad", "Garmin training load per běh — alternativa/doplněk k EWMA km"),
        ("aktivita", "avgGradeAdjustedSpeed", "GAP — tempo očištěné o sklon, čistší pace bucket"),
        ("aktivita", "get_activity_splits(id)", "laps/splity — vnitroběhový rozpad tempa/HR/dynamiky"),
        ("aktivita", "get_activity_details(id)", "record streamy (HR, kadence, výška po vteřinách) — decoupling, drift v běhu"),
        ("aktivita", "get_activity_hr_in_timezones(id)", "čas v HR zónách — rozložení intenzity"),
        ("denní", "get_training_readiness(date)", "Garmin readiness 0–100 (spánek+HRV+zátěž) — hotový recovery index"),
        ("denní", "get_training_status()", "Acute/Chronic load + load balance (anaerob/vysoká/nízká aerobní)"),
        ("denní", "get_stress_data(date)", "denní stres time-series — autonomní zátěž mimo běh"),
        ("denní", "get_body_battery(start,end)", "body battery křivka — nabití/vybití energie"),
        ("denní", "get_max_metrics_range", "VO2max + fitness age + heat/altitude acclimation trend"),
        ("denní", "get_hrv_data(date)", "HRV 5-min noční detail — kromě lastNightAvg i rozptyl v noci"),
        ("denní", "get_respiration_data / spo2", "dýchání a SpO2 (už i v sleep_daily) — nemoc/výška"),
        ("denní", "get_race_predictions()", "predikce časů 5k/10k/HM/M — proxy formy v čase"),
        ("denní", "get_floors / intensity_minutes", "nesouvisející aktivita — celkové denní zatížení"),
    ]
    for r in avail:
        ws.append(list(r))


# ---------------------------------------------------------------- engine docs
# axis, trigger condition, points formula (mirrors app/metrics/engine.py assess())
SIG_META = {
    "tavr": ("mechanika", "z ≥ 1.0", "round(clamp(z,0,4)·17)"),
    "gct": ("mechanika", "z ≥ 1.0", "round(clamp(z,0,4)·13)"),
    "bal": ("mechanika", "excursion ≥ 0.8", "round(clamp(excursion,0,3)·22)"),
    "dec": ("mechanika", "trend > 0.35", "round(clamp(trend·26,0,30))"),
    "ewma": ("zátěž", "ratio > 1.5  (nebo < 0.7)", "round(clamp((ratio−1.5)·70,0,42)+10)  ·  <0.7 ⇒ 22"),
    "ewma_mild": ("zátěž", "1.3 < ratio ≤ 1.5", "round(clamp((ratio−1.3)·35,0,14))"),
    "mono": ("zátěž", "monotony > 2.4", "round(clamp((mono−2.4)·7,0,26))"),
    "desc": ("zátěž", "descentSpike > 1.45", "round(clamp((spike−1.45)·30,0,26))"),
    "desc_steep": ("zátěž", "steepSpike > 1.5", "round(clamp((spike−1.5)·20,0,22))"),
    "aer": ("zátěž", "aer.mean > 5.5 %", "round(clamp((mean−5.5)·3,0,12))"),
    "hrv": ("zátěž", "hrv.z ≤ −1.0", "round(clamp(−z·10,0,22))"),
    "rhr": ("zátěž", "rhr.z ≥ 1.2", "round(clamp(z·8,0,18))"),
    "hrvcv": ("zátěž", "CV ratio ≥ 1.4", "round(clamp((ratio−1.4)·20,0,16))"),
    "tsb": ("zátěž", "tsbBalance ≤ −8", "round(clamp((−tsb−8)·2,0,18))"),
    "taper": ("zátěž", "≤21 dní do závodu A (load≥25 || ratio>1.3)", "round(clamp((21−d)/21·14,4,14))"),
    "niggle": ("příznaky", "niggleCount ≥ 3 / 21 dní", "round(clamp(niggleCount·9,0,40))"),
    "pain": ("příznaky", "pain ≥6 / ≥3 / ≥1", "44 / 26 / 8"),
    "sore": ("příznaky", "soreness ≥ 7", "10"),
    "sleep": ("příznaky", "debt ≥ 4 h/týd", "round(clamp(debt·2.5,0,16))"),
    "sleepreg": ("příznaky", "SD ratio ≥ 1.5", "round(clamp((ratio−1.5)·12,0,14))"),
    "feel": ("příznaky", "n≥6 A feelingTrend ≤ −0.12", "10"),
    "stiffness": ("příznaky", "ignoreRate ≥0.5 (≥3×) / trend ≥0.15", "round(clamp(ignoreRate·20,0,18)) / 10"),
    "injury": ("příznaky", "aktivní OSTRC report", "potvrzeno: clamp(sev·0.5,0,46) [A] · self: clamp(sev·0.34,0,32) [B]"),
    "hist": ("příznaky", "prior_injury ≤ 12 měs.", "16"),
}
SIG_ORDER = ["tavr", "gct", "bal", "dec", "ewma", "ewma_mild", "mono", "desc", "desc_steep",
             "aer", "hrv", "rhr", "hrvcv", "tsb", "taper", "niggle", "pain", "sore",
             "sleep", "sleepreg", "feel", "stiffness", "injury", "hist"]


def sheet_engine_doc(wb):
    ws = wb.create_sheet("Engine — dokumentace")
    ws.append(["Engine v0.4 — jak se skóre počítá"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Osy (nesčítají se do jednoho čísla):",
               "overall = mechanika·0.38 + zátěž·0.30 + příznaky·0.52  (každá osa 0–100, clamp)"])
    ws.append(["Kvadrant (s hysterezí):",
               "osa „hoří\" při skóre ≥ 25 (QUAD_THRESHOLD), „chladne\" až pod 18 (QUAD_EXIT). "
               "critical=obě · overreaching=zátěž · silent=mechanika · stable=nic"])
    ws.append(["Konfidence baseline:",
               "min(1, matched/8) · min(1, dnů/84) · min(1, baseline_běhů/15). Pod 0.6 se mechanické signály (tavr,gct,bal,dec) NEZOBRAZÍ."])
    ws.append(["Tier:", "overall ≥ 70 = vysoké riziko · ≥ 40 = sledovat · jinak nízké"])
    ws.append(["Evidence grade:", " · ".join(f"{k}: {v}" for k, v in SD.GRADE_NOTE.items())])
    ws.append([])
    r0 = ws.max_row + 1
    header(ws, ["id", "signál", "osa", "grade", "práh (trigger)", "body (formula)", "vzorec",
                "proč", "kde selhává (limit)", "kdy zmizí (clear)"],
           widths=[11, 30, 11, 7, 30, 34, 40, 60, 55, 40], row=r0)
    for sid in SIG_ORDER:
        doc = SD.SIG_DOC.get(sid, {})
        axis, trig, pts = SIG_META.get(sid, ("", "", ""))
        ws.append([sid, doc.get("t", ""), axis, doc.get("g", ""), trig, pts,
                   doc.get("fx") or "", doc.get("why", ""), doc.get("limit", ""), doc.get("clear", "")])
    for r in range(r0 + 1, ws.max_row + 1):
        for c in range(1, 11):
            ws.cell(r, c).alignment = Alignment(vertical="top", wrap_text=True)


# ---------------------------------------------------------------- engine timeline
def _rows_of(session, model, rid):
    cols = [c.name for c in model.__table__.columns]
    return [{c: getattr(r, c) for c in cols} for r in session.query(model).filter(model.runner_id == rid).all()]


def _weekly_backtest():
    src = sessionmaker(bind=create_engine(f"sqlite:///{DB}"))()
    runner = src.query(models.Runner).filter(models.Runner.id == RID).first()
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = _rows_of(src, models.Activity, RID)
    daily = _rows_of(src, models.DailyMetric, RID)
    src.close()
    first = min(a["started_at"][:10] for a in acts)
    last = max(a["started_at"][:10] for a in acts)
    ad = date.fromisoformat(first) + timedelta(days=42)
    end = date.fromisoformat(last)
    asofs = []
    while ad <= end:
        asofs.append(ad)
        ad += timedelta(days=7)
    if asofs[-1] != end:
        asofs.append(end)

    orig = E.today_date
    out = []
    try:
        for ad in asofs:
            E.today_date = (lambda d: (lambda: d))(ad)
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            ts.add(models.Runner(**rdata))
            cut = ad.isoformat()
            for a in acts:
                if a["started_at"][:10] <= cut:
                    ts.add(models.Activity(**{k: v for k, v in a.items() if k != "id"}))
            for d in daily:
                if d["date"][:10] <= cut:
                    ts.add(models.DailyMetric(**{k: v for k, v in d.items() if k != "id"}))
            ts.commit()
            if out:
                ts.add(models.Assessment(runner_id=RID, quadrant=out[-1]["_q"], tier="ok",
                                         mech=0, load=0, symp=0, overall=0, engine_version="v0.4"))
                ts.commit()
            a = E.assess(ts, RID)
            conf, L = a["confidence"] or {}, a.get("loadDetail") or {}
            tv, gc, bal, dec, aer, rcv = (a.get(k) for k in ("tavr", "gct", "bal", "dec", "aer", "rcv"))
            hcv, sreg = a.get("hrvCv"), a.get("sleepReg")
            sig = {s["id"]: s["pts"] for s in a.get("signals") or []}
            out.append({
                "as_of": cut, "runs": sum(1 for x in acts if x["started_at"][:10] <= cut),
                "conf": conf.get("value"), "days": conf.get("days"), "base": conf.get("baseSessions"),
                "acute": L.get("acute"), "chronic": L.get("chronic"),
                "ewma": L.get("ratio") if L.get("valid") else None, "mono": L.get("monotony"),
                "tsb": L.get("tsbBalance"), "desc7": L.get("descent7"),
                "tavr_z": (tv or {}).get("z"), "gct_z": (gc or {}).get("z"),
                "bal_exc": (bal or {}).get("excursion"), "dec_trend": (dec or {}).get("trend"),
                "aer": (aer or {}).get("mean"),
                "hrv_z": ((rcv or {}).get("hrv") or {}).get("z"),
                "rhr_z": ((rcv or {}).get("rhr") or {}).get("z"),
                "sleep_debt": ((rcv or {}).get("sleep") or {}).get("debt"),
                "hrvcv": (hcv or {}).get("ratio"), "sleepreg": (sreg or {}).get("ratio"),
                "mech": a["mech"], "load": a["load"], "symp": a["symp"], "overall": a["overall"],
                "tier": a["tier"], "quad": SD.QUAD[a["quadrant"]]["t"], "_q": a["quadrant"],
                "signals": " · ".join(f"{s['id']}+{s['pts']}" for s in (a.get("signals") or [])[:4]) or "—",
            })
            ts.close()
            eng.dispose()
    finally:
        E.today_date = orig
    return out


def sheet_timeline(wb, rows):
    ws = wb.create_sheet("Engine — týdenní osa")
    cols = [("as_of", "datum", 12), ("runs", "běhů", 7), ("conf", "konfidence", 10),
            ("days", "dnů hist.", 9), ("base", "baseline běhů", 12),
            ("acute", "akut km", 9), ("chronic", "chron km", 9), ("ewma", "EWMA", 8),
            ("mono", "monoton.", 9), ("tsb", "TSB", 8),
            ("tavr_z", "vert.pom. z", 10), ("gct_z", "GCT z", 8), ("dec_trend", "decoupl. trend", 12),
            ("aer", "aerob %", 8), ("hrv_z", "HRV z", 8), ("rhr_z", "klid.tep z", 10),
            ("sleep_debt", "spánek dluh", 11), ("hrvcv", "HRV CV", 8), ("sleepreg", "spánek SD", 9),
            ("mech", "MECH", 7), ("load", "ZÁTĚŽ", 7), ("symp", "PŘÍZN.", 7), ("overall", "CELKEM", 8),
            ("tier", "tier", 9), ("quad", "kvadrant", 13), ("signals", "aktivní signály (+body)", 46)]
    header(ws, [c[1] for c in cols], widths=[c[2] for c in cols])
    for r in rows:
        ws.append([round(r[c[0]], 2) if isinstance(r.get(c[0]), float) else r.get(c[0]) for c in cols])
        qi = [c[0] for c in cols].index("quad") + 1
        ws.cell(ws.max_row, qi).fill = PatternFill("solid", fgColor=QFILL.get(r["_q"], "FFFFFF"))


# ---------------------------------------------------------------- per-activity engine inputs
def sheet_per_activity(wb):
    s = sessionmaker(bind=create_engine(f"sqlite:///{DB}"))()
    acts = s.query(models.Activity).filter(models.Activity.runner_id == RID).order_by(models.Activity.started_at).all()
    ws = wb.create_sheet("Engine — per-aktivita")
    cols = ["datum", "název", "povrch", "bucket (engine)", "km", "min", "tempo s/km", "kadence",
            "vert_ratio %", "GCT ms", "vert_osc cm", "krok m", "GCT balance", "stoupání m",
            "klesání m", "avg HR"]
    header(ws, cols, widths=[12, 20, 10, 26, 7, 7, 10, 9, 11, 8, 10, 8, 11, 11, 11, 8])
    for a in acts:
        try:
            b = E.bucket(a)
            blab = E.bucket_label(b)
        except Exception:
            b = blab = ""
        ws.append([a.started_at, a.title, a.surface, f"{b}  ({blab})", a.distance_km, a.duration_min,
                   a.pace_s_km, a.cadence_spm, a.vert_ratio_pct, a.gct_ms, a.vert_osc_cm,
                   a.stride_len_m, a.gct_balance_l, a.ascent_m, a.descent_m, a.avg_hr])
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(acts) + 1}"
    s.close()


def sheet_mech_detail(wb):
    s = sessionmaker(bind=create_engine(f"sqlite:///{DB}"))()
    ws = wb.create_sheet("Engine — mechanika detail")
    ws.append(["Vnitřek mechanických z-skóre k poslednímu datu (jak engine počítá drift po terénních skupinách)"])
    ws["A1"].font = Font(bold=True, size=12)
    for name, fn in (("Vertikální poměr (tavr)", E.tavr), ("Kontakt se zemí (gct)", E.gct_drift)):
        d = fn(s, RID)
        ws.append([])
        ws.append([name, f"celkové z = {d['z'] if d else '—'}", f"baseline {d['baseMean'] if d else ''} → teď {d['recMean'] if d else ''}" if d else ""])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        r0 = ws.max_row + 1
        header(ws, ["terénní skupina (povrch·sklon·tempo)", "baseline", "teď", "z", "n baseline", "n teď"],
               widths=[34, 12, 12, 8, 12, 8], row=r0)
        for x in (d["detail"] if d else []):
            ws.append([x["label"], x["base"], x["now"], x["z"], x["nBase"], x["nNow"]])
    s.close()


# ---------------------------------------------------------------- návod
def sheet_navod(wb, cache, n_weeks):
    ws = wb.create_sheet("Návod")
    for row in [
        ["Garmin paleta + Engine v0.4 — podklad pro due diligence", ""],
        ["", ""],
        ["Historie", f"{cache['history_start']} → {cache['pulled_end']} · {len(cache['activities'])} aktivit (vč. jiných sportů) · {n_weeks} týdenních snímků enginu"],
        ["Běžec v enginu", "run-0012 (tvá reálná data z Garminu)"],
        ["", ""],
        ["Listy", ""],
        ["Aktivity (raw)", "Každá aktivita, VŠECHNA pole z Garmin API (147 sloupců). Filtr na __type=running. Palety pro nové metriky."],
        ["Denní wellness (raw)", "HRV / klidový tep / spánek vč. fází / kroky / VO2max / kalorie, sloučeno po dnech."],
        ["Zdroje & API", "Co engine dnes bere vs. co dalšího Garmin nabízí (metody + potenciál) — kde brát nová data."],
        ["Engine — dokumentace", "Každý signál: osa, práh, vzorec bodů, grade, proč/kde selhává/kdy zmizí. Osy, kvadrant, konfidence, tier."],
        ["Engine — týdenní osa", "assess() přehraný týden po týdnu přes celou historii — všechny metriky + skóre + kvadrant v čase."],
        ["Engine — per-aktivita", "Engine-vstupy na každý běh: bucket terén×sklon×tempo, vert.poměr, GCT, kadence, klesání…"],
        ["Engine — mechanika detail", "Vnitřek z-skóre po terénních skupinách k poslednímu datu — jak vzniká drift."],
        ["", ""],
        ["Co s tím ty", ""],
        ["1.", "Projdi raw listy — uvidíš, s jakými daty se dá pracovat (i ta, co engine zatím ignoruje: výkon, TE, training load, readiness, GAP, splity…)."],
        ["2.", "V listu Engine — dokumentace vidíš přesně, co a jak se počítá dnes."],
        ["3.", "Vytvoř NOVÝ list (klidně zkopíruj týdenní osu nebo per-aktivitu) a v něm: uprav prahy/váhy, nebo navrhni úplně nové metriky ze sloupců raw dat."],
        ["4.", "Pošli mi zpět tenhle soubor s tvým novým listem — přepíšu podle něj engine (vzorce, prahy, váhy, nové signály) a znovu ověřím backtestem."],
        ["Pozn.", "Excel neumí 1:1 replikovat rolling z-skóre po bucketech (to je kód) — proto máš vzorce textově + mezivýpočty. Klidně navrhuj i logiku slovy."],
    ]:
        ws.append(row)
    ws["A1"].font = Font(bold=True, size=13)
    for r in (6, 15):
        ws.cell(r, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 118
    wb.move_sheet("Návod", -(len(wb.sheetnames) - 1))


def main():
    cache = json.load(open(CACHE))
    wb = Workbook()
    wb.remove(wb.active)
    sheet_activities(wb, cache)
    sheet_daily(wb, cache)
    sheet_sources(wb)
    sheet_engine_doc(wb)
    tl = _weekly_backtest()
    sheet_timeline(wb, tl)
    sheet_per_activity(wb)
    sheet_mech_detail(wb)
    sheet_navod(wb, cache, len(tl))
    wb.save(OUT)
    print(f"Hotovo → {OUT}")
    print("Listy:", wb.sheetnames)


if __name__ == "__main__":
    main()
