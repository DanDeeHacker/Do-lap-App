"""In-app Excel export: v1-vs-v2 engine backtest for one runner, on that runner's
own data (whatever DB the server is connected to — SQLite in dev, the runner's
Railway Postgres in production). Same layout as the standalone backtest script,
scoped to a single runner so it can be streamed as a download.

Each weekly/daily as-of date is scored twice on a throwaway in-memory DB holding
only the data that existed then (engine 'today' pinned), once per engine, with
each engine's own hysteresis carried forward.
"""
import io
import json
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import models
from .db import Base
from .metrics import engine as E

HOT = ("silent", "critical")
QUADL = {"stable": "Stabilní", "overreaching": "Přetížení", "silent": "Tichý drift", "critical": "Kritické přetížení"}
HEAD = PatternFill("solid", fgColor="0A2540")
GRP = PatternFill("solid", fgColor="1B4A6B")
QFILL = {"stable": "C6EFCE", "overreaching": "FFEB9C", "silent": "BDD7EE", "critical": "FFC7CE"}

AXFILL = {"mech": "E7F0FF", "load": "FFF1E0", "symp": "F3E8FF"}
AXLABEL = {"mech": "Mechanika", "load": "Zátěž", "symp": "Příznaky"}
SIG_AXIS = {
    **{k: "mech" for k in ("tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv")},
    **{k: "load" for k in ("session_spike", "spike_latent", "pace_spike", "ewma", "hi_load",
                           "load_creep", "mono", "desc", "desc_steep", "aer", "hrv", "rhr",
                           "hrvcv", "tsb", "load_capacity", "taper")},
    **{k: "symp" for k in ("niggle", "pain", "pain_prior", "sore", "fatigue", "sleep", "sleepreg",
                           "sleepeff", "feel", "stiffness", "hist", "injury", "complaints")},
}
LEGEND = [
    ("mech", "tavr", "Vertikální poměr roste", "clamp((z−0,2),0..4) × 17"),
    ("mech", "gct", "Prodloužený kontakt se zemí", "clamp((z−0,2),0..4) × 13"),
    ("mech", "cad", "Klesající kadence", "clamp((−z−0,2),0..4) × 10 (nižší kadence = riziko)"),
    ("mech", "vosc", "Vyšší vertikální oscilace", "clamp((z−0,2),0..4) × 10"),
    ("mech", "bal", "Posun symetrie kontaktu", "clamp((exkurze−0,4),0..3) × 22"),
    ("mech", "dec", "Klesající odolnost proti únavě", "clamp((trend−0,1),0..1,2) × 26 (>0,15)"),
    ("mech", "gaitcv", "Kolísavější mechanika", "(CV poměr−1,5) × 14, strop 14"),
    ("load", "session_spike", "Skok v jednom běhu", ">2×:14+; >1,3×:(s−1,3)×20→14; >1,1×:(s−1,1)×25→6"),
    ("load", "spike_latent", "Doznívající skok (8–28 dní)", "clamp(latent×22,0..16), mizí do 28. dne"),
    ("load", "pace_spike", "Skok v tempu", "(poměr−1,06) × 40, strop 10"),
    ("load", "ewma", "Poměr zátěže 7:28 (ACWR)", ">1,5:(r−1,5)×18→12,+2; <0,7:+10"),
    ("load", "hi_load", "Skok ve vysoké intenzitě", "(HI poměr−1,5)×20, strop 20 (HI akut≥60)"),
    ("load", "load_creep", "Postupný nárůst zátěže", "(creep−1,15)×30, strop 10 (ACWR<1,3)"),
    ("load", "mono", "Monotónní trénink", "(monotonie−2,4)×7, strop 20"),
    ("load", "desc", "Nárůst sbíhání", "(poměr−1,45)×15, strop 14"),
    ("load", "desc_steep", "Strmé klesání ≥10 %", "(poměr−1,5)×12, strop 12 (excentricky)"),
    ("load", "aer", "Aerobní decoupling", "(decoupling %−5,5)×3, strop 12"),
    ("load", "hrv", "Potlačená HRV", "clamp(−z×10,0..22) (z≤−1,0)"),
    ("load", "rhr", "Zvýšený klidový tep", "clamp(z×8,0..18) (z≥1,2)"),
    ("load", "hrvcv", "Kolísavá HRV mezi dny", "(poměr−1,4)×14, strop 10"),
    ("load", "tsb", "Nepříznivá bilance zátěže", "(−rel−0,12)×90, strop 12 (rel=TSB/chronic)"),
    ("load", "load_capacity", "Zátěž na sníženou regeneraci", "kapac. deficit × síla spiku × 34, strop 16"),
    ("symp", "niggle", "Opakované bolestivé místo", "eskaluje s počtem za 21 dní (A)"),
    ("symp", "pain", "Neustupující / opakující se bolest", "z check-inů; A/B dle přetrvání a lokality"),
    ("symp", "sore", "Vysoká svalová únava", "+10 (soreness ≥ práh)"),
    ("symp", "sleep", "Spánkový dluh", "clamp(dluh×2,5,0..16) (≥4 h/týden)"),
    ("symp", "feel", "Zhoršující se pocit z běhu", "+10"),
    ("symp", "stiffness", "Ztuhlost nohou před během", "+10 / eskalace"),
    ("symp", "hist", "Zranění v anamnéze", "dle měsíců od zranění (A)"),
    ("symp", "injury", "Nahlášené/potvrzené zranění", "dle OSTRC/100 (A/B)"),
    ("*", "osa/celkem", "Skládání", "osa = Σbody×frailty, ořez 0–100; celkem = mech·0,38+zátěž·0,30+příznaky·0,52"),
]

WCOLS = [
    ("datum", 11), ("conf", 6),
    ("v1 mech", 8), ("v1 load", 8), ("v1 symp", 8), ("v1 celk", 8), ("v1 kvadrant", 16),
    ("v2 mech", 8), ("v2 load", 8), ("v2 symp", 8), ("v2 celk", 8), ("v2 kvadrant", 16),
    ("Δ mech", 8), ("Δ load", 8), ("v2 flag", 8), ("v2 úseky", 8), ("v2 klíčové signály", 52),
]


def _hdr(ws, names, widths, row=1, fill=HEAD):
    for i, n in enumerate(names, 1):
        c = ws.cell(row=row, column=i, value=n)
        c.font = Font(bold=True, color="FFFFFF" if fill in (HEAD, GRP) else "000000")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[row].height = 26


def _copy(db, model, rid):
    cols = [c.name for c in model.__table__.columns]
    return [{c: getattr(r, c) for c in cols} for r in db.query(model).filter(model.runner_id == rid).all()]


def _replay_both(db, rid, step_days, warmup_days=7, start=None):
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if not runner:
        return []
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = _copy(db, models.Activity, rid)
    daily = _copy(db, models.DailyMetric, rid)
    devices = _copy(db, models.DeviceHistory, rid)
    streams = _copy(db, models.ActivityStream, rid)
    feedback = _copy(db, models.ActivityFeedback, rid)
    checkins = _copy(db, models.Checkin, rid)
    injuries = _copy(db, models.InjuryReport, rid)
    acts = [a for a in acts if a.get("started_at")]
    if not acts:
        return []
    first = min(a["started_at"][:10] for a in acts)
    last = max(a["started_at"][:10] for a in acts)
    # Small warm-up so the timeline starts near the first run (early weeks are
    # baseline-building: low confidence, mechanics gated → mostly load/stable).
    ad = date.fromisoformat(first) + timedelta(days=warmup_days)
    if start is not None and start > ad:
        ad = start  # cap the earliest as-of date (keeps the daily sheet bounded)
    end = date.fromisoformat(last)
    if ad > end:
        ad = end
    asofs = []
    while ad <= end:
        asofs.append(ad)
        ad += timedelta(days=step_days)
    if not asofs or asofs[-1] != end:
        asofs.append(end)

    out, prev1, prev2 = [], None, None
    for adate in asofs:
        with E.today_pinned(adate):
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            try:
                ts.add(models.Runner(**{k: v for k, v in rdata.items() if k != "engine_mode"}, engine_mode="v1"))
                cut = adate.isoformat()
                for a in acts:
                    if a["started_at"][:10] <= cut:
                        ts.add(models.Activity(**dict(a)))  # keep id so ActivityStream.activity_id joins
                for d in daily:
                    if (d.get("date") or "")[:10] <= cut:
                        ts.add(models.DailyMetric(**{k: v for k, v in d.items() if k != "id"}))
                for dv in devices:
                    if (dv.get("recorded_at") or "")[:10] <= cut:
                        ts.add(models.DeviceHistory(**{k: v for k, v in dv.items() if k != "id"}))
                kept_act_ids = {a["id"] for a in acts if a["started_at"][:10] <= cut}
                for s in streams:
                    if s.get("activity_id") in kept_act_ids:
                        ts.add(models.ActivityStream(**{k: v for k, v in s.items()}))
                for f in feedback:
                    if (f.get("submitted_at") or "")[:10] <= cut:
                        ts.add(models.ActivityFeedback(**{k: v for k, v in f.items() if k != "id"}))
                for c in checkins:
                    if (c.get("submitted_at") or "")[:10] <= cut:
                        ts.add(models.Checkin(**{k: v for k, v in c.items() if k != "id"}))
                for ij in injuries:
                    if (ij.get("submitted_at") or "")[:10] <= cut:
                        ts.add(models.InjuryReport(**{k: v for k, v in ij.items() if k != "id"}))
                ts.commit()
                arow = models.Assessment(runner_id=rid, quadrant=prev1, tier="ok", mech=0, load=0, symp=0, overall=0, engine_version="x")
                ts.add(arow)
                ts.commit()
                with E.engine_pinned("v1"):
                    v1 = E.assess(ts, rid)
                arow.quadrant = prev2
                ts.commit()
                with E.engine_pinned("v2"):
                    v2 = E.assess(ts, rid)
                prev1, prev2 = v1["quadrant"], v2["quadrant"]
                out.append((cut, v1, v2))
            finally:
                ts.close()
                eng.dispose()
    return out


def _qcell(ws, row, col, quad):
    c = ws.cell(row=row, column=col, value=QUADL.get(quad, quad))
    c.fill = PatternFill("solid", fgColor=QFILL.get(quad, "FFFFFF"))
    c.alignment = Alignment(horizontal="center")


def _fill_rows(ws, pts, start_row=2):
    row = start_row
    for cut, v1, v2 in pts:
        conf = round((v1.get("confidence") or {}).get("value", 0), 2)
        sig = " · ".join(f"{s['name']} (+{s['pts']})" for s in (v2.get("signals") or [])[:4]) or "—"
        vals = [cut, conf,
                v1["mech"], v1["load"], v1["symp"], v1["overall"], None,
                v2["mech"], v2["load"], v2["symp"], v2["overall"], None,
                v2["mech"] - v1["mech"], v2["load"] - v1["load"],
                "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else ""),
                "✓" if v2.get("segmentScored") else "", sig]
        for i, val in enumerate(vals, 1):
            if i in (7, 12):
                continue
            ws.cell(row=row, column=i, value=val)
        _qcell(ws, row, 7, v1["quadrant"])
        _qcell(ws, row, 12, v2["quadrant"])
        row += 1
    return row


# Runner-scoped tables safe to export. Deliberately EXCLUDES the secret tables
# (ingest_tokens, garmin_sessions) and never touches users/password hashes.
def _export_models():
    return [
        models.Integration, models.ActivityStream, models.DeviceHistory, models.Activity,
        models.ActivityFeedback, models.DailyMetric, models.Checkin, models.InjuryReport,
        models.Assessment, models.Triage, models.Booking, models.Referral, models.Conclusion,
        models.ReturnToRun, models.RtrSession, models.Program, models.Message, models.CareAssignment,
        models.Race,
    ]


def runner_export(db, rid: str) -> bytes:
    """Full per-runner data export as JSON — everything scoped to this runner
    EXCEPT credentials (no Garmin/ingest tokens, no password). Shareable for
    off-line analysis / backtesting."""
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()

    def rows(model):
        cols = [c.name for c in model.__table__.columns]
        return [{c: getattr(x, c) for c in cols}
                for x in db.query(model).filter(model.runner_id == rid).all()]

    tables = {}
    for model in _export_models():
        try:
            tables[model.__tablename__] = rows(model)
        except Exception:  # noqa: BLE001 — a missing optional table shouldn't break the export
            tables[model.__tablename__] = []
    data = {
        "schema": 1,
        "exportedAt": E.now_iso(),
        "engineVersion": E.ENGINE_VERSION,
        "note": "Osobní data běžce z Došlapu. NEOBSAHUJE přihlašovací tokeny, Garmin token ani hesla.",
        "runner": {c.name: getattr(r, c.name) for c in models.Runner.__table__.columns} if r else None,
        "counts": {name: len(rowlist) for name, rowlist in tables.items()},
        "tables": tables,
    }
    return json.dumps(data, ensure_ascii=False, default=str, indent=2).encode("utf-8")


def engine_compare_xlsx(db, rid: str) -> bytes:
    """Build the v1-vs-v2 backtest workbook for one runner and return xlsx bytes."""
    wb = Workbook()
    summ = wb.active
    summ.title = "Souhrn"
    weekly = _replay_both(db, rid, step_days=7)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    name = r.name if r else rid

    _hdr(summ, ["běžec", "období", "bodů", "shoda kvadrantů %", "rozdílů",
                "ø mech v1", "ø mech v2", "v1 první zvýšený", "v2 první zvýšený",
                "předstih v2 (dny)", "finále v1", "finále v2"],
         [22, 24, 7, 16, 8, 10, 10, 16, 16, 16, 18, 18])
    if not weekly:
        summ.cell(row=2, column=1, value=name)
        summ.cell(row=2, column=2, value="málo dat — potřeba aspoň ~6 týdnů historie běhů")
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

    diffs = sum(1 for _, v1, v2 in weekly if v1["quadrant"] != v2["quadrant"])
    m1 = sum(v1["mech"] for _, v1, _ in weekly) / len(weekly)
    m2 = sum(v2["mech"] for _, _, v2 in weekly) / len(weekly)
    f1 = next((c for c, v1, _ in weekly if v1["quadrant"] in HOT), None)
    f2 = next((c for c, _, v2 in weekly if v2["quadrant"] in HOT), None)
    lead = (date.fromisoformat(f1) - date.fromisoformat(f2)).days if (f1 and f2) else None
    agree = round(100 * (len(weekly) - diffs) / len(weekly), 1)
    for j, val in enumerate([name, f"{weekly[0][0]} → {weekly[-1][0]}", len(weekly), agree, diffs,
                             round(m1, 1), round(m2, 1), f1 or "—", f2 or "—",
                             lead if lead is not None else "—",
                             QUADL[weekly[-1][1]["quadrant"]], QUADL[weekly[-1][2]["quadrant"]]], 1):
        summ.cell(row=2, column=j, value=val)

    wk = wb.create_sheet("Týdně")
    _hdr(wk, [c[0] for c in WCOLS], [c[1] for c in WCOLS])
    _fill_rows(wk, weekly)

    # Daily sheet is bounded to the last ~8 weeks — a full-history daily replay
    # (one throwaway DB + 2× assess per day) would otherwise risk an HTTP timeout.
    daily = _replay_both(db, rid, step_days=1, start=E.today_date() - timedelta(days=56))
    if daily:
        dy = wb.create_sheet("Denně (8 týdnů)")
        _hdr(dy, [c[0] for c in WCOLS], [c[1] for c in WCOLS])
        _fill_rows(dy, daily)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _detail_souhrn(ws, pts):
    _hdr(ws, ["datum", "v1 mech", "v1 zátěž", "v1 přízn.", "v1 celkem", "v1 kvadrant",
              "v2 mech", "v2 zátěž", "v2 přízn.", "v2 celkem", "v2 kvadrant", "v2 úseky", "v2 flag"],
         [11, 8, 8, 8, 9, 16, 8, 8, 8, 9, 16, 8, 8])
    row = 2
    for cut, v1, v2 in pts:
        for i, v in enumerate([cut, v1["mech"], v1["load"], v1["symp"], v1["overall"], None,
                               v2["mech"], v2["load"], v2["symp"], v2["overall"], None,
                               "✓" if v2.get("segmentScored") else "",
                               "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else "")], 1):
            if i not in (6, 11):
                ws.cell(row=row, column=i, value=v)
        _qcell(ws, row, 6, v1["quadrant"])
        _qcell(ws, row, 11, v2["quadrant"])
        row += 1


def _detail_rozpad(ws, pts, which):
    _hdr(ws, ["datum", "osa", "signál", "+body", "hodnota", "proč"], [11, 12, 32, 7, 12, 74])
    row = 2
    for cut, v1, v2 in pts:
        a = v1 if which == 1 else v2
        gc = ws.cell(row=row, column=1,
                     value=f"{cut}  →  mech {a['mech']} · zátěž {a['load']} · příznaky {a['symp']} · CELKEM {a['overall']} · {QUADL.get(a['quadrant'])}")
        gc.font = Font(bold=True, color="FFFFFF"); gc.fill = GRP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1
        sigs = a.get("signals") or []
        if not sigs:
            ws.cell(row=row, column=3, value="— žádné signály (vše v normě) —").font = Font(italic=True, color="777777")
            row += 1; continue
        for s in sorted(sigs, key=lambda x: (SIG_AXIS.get(x["id"], "zzz"), -x["pts"])):
            ax = SIG_AXIS.get(s["id"], "?")
            ws.cell(row=row, column=1, value=cut)
            ac = ws.cell(row=row, column=2, value=AXLABEL.get(ax, ax)); ac.fill = PatternFill("solid", fgColor=AXFILL.get(ax, "FFFFFF"))
            ws.cell(row=row, column=3, value=f"{s['name']}  ({s['grade']})")
            ws.cell(row=row, column=4, value=s["pts"]).font = Font(bold=True)
            ws.cell(row=row, column=5, value=s.get("val"))
            ws.cell(row=row, column=6, value=(s.get("detail") or "")[:320])
            row += 1
        row += 1


def _detail_drivery(ws, pts):
    cols = ["datum", "conf", "tavr z", "gct z", "kad z", "vosc z", "stride z", "bal exk", "dec tr",
            "gaitCV×", "ACWR", "běh spike×", "tempo×", "doznívá", "HI×", "creep×", "mono", "sběh×",
            "strmé×", "HRV z", "tep z", "TSB", "eff.km7", "sběh km7", "úseky", "flag"]
    _hdr(ws, cols, [11, 6] + [8] * (len(cols) - 2))
    row = 2
    for cut, v1, v2 in pts:
        L = v2.get("loadDetail") or {}
        rcv = v2.get("rcv") or {}
        gd = v2.get("gradientDescent") or {}
        z = lambda k, s="z": (v2.get(k) or {}).get(s)
        vals = [cut, round((v2.get("confidence") or {}).get("value", 0), 2),
                z("tavr"), z("gct"), z("cadence"), z("vosc"), z("stride"),
                (v2.get("bal") or {}).get("excursion"), (v2.get("dec") or {}).get("trend"),
                (v2.get("gaitCv") or {}).get("ratio"),
                L.get("ratio"), L.get("sessionSpike"), L.get("paceSpike"), L.get("spikeLatent"),
                L.get("hiRatio"), L.get("loadCreep"), L.get("monotony"), L.get("descentSpike"),
                gd.get("steepSpike"), (rcv.get("hrv") or {}).get("z"), (rcv.get("rhr") or {}).get("z"),
                L.get("tsbBalance"), L.get("gradeAdjKm7"), L.get("downhillKm7"),
                "✓" if v2.get("segmentScored") else "", "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else "")]
        for i, v in enumerate(vals, 1):
            ws.cell(row=row, column=i, value=v)
        row += 1


def _detail_legenda(ws):
    _hdr(ws, ["osa", "signál (id)", "název", "jak vzniká skóre"], [10, 16, 30, 92])
    for row, (ax, sid, name, formula) in enumerate(LEGEND, 2):
        ac = ws.cell(row=row, column=1, value=AXLABEL.get(ax, ax))
        if ax in AXFILL:
            ac.fill = PatternFill("solid", fgColor=AXFILL[ax])
        ws.cell(row=row, column=2, value=sid)
        ws.cell(row=row, column=3, value=name)
        ws.cell(row=row, column=4, value=formula)


def engine_detail_xlsx(db, rid: str) -> bytes:
    """Detailed backtest workbook: per-date per-signal point contributions (v1 &
    v2), raw driver metrics, and a formula legend — on this runner's own data."""
    pts = _replay_both(db, rid, step_days=7)
    wb = Workbook()
    s = wb.active
    s.title = "Souhrn"
    if not pts:
        s.cell(row=1, column=1, value="Málo dat — potřeba aspoň ~6 týdnů historie běhů.")
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
    _detail_souhrn(s, pts)
    _detail_rozpad(wb.create_sheet("Rozpad v1"), pts, 1)
    _detail_rozpad(wb.create_sheet("Rozpad v2"), pts, 2)
    _detail_drivery(wb.create_sheet("Drivery v2"), pts)
    _detail_legenda(wb.create_sheet("Legenda"))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
