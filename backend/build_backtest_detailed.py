"""Detailed backtest from a runner-export JSON — shows exactly how each metric
feeds the score and how v1 vs v2 differ, on the runner's OWN data.

Loads dosslap_data.json (the in-app "Stáhnout moje data") into a throwaway DB,
replays assess() weekly under BOTH engines with each date scored only on the
data that existed then, and writes an Excel with:

  1. Souhrn         — per date: v1/v2 mech·load·symp·celkem·kvadrant.
  2. Rozpad v1 / v2 — per date × signal: axis, name, +points, value, why. This
                      is the per-metric contribution to the score.
  3. Drivery v2     — raw drivers per date (z-scores, ACWR, spikes, HRV, terén…).
  4. Legenda        — metric → threshold → points formula for every signal.

Run:  .venv_posix/bin/python build_backtest_detailed.py [path/to/dosslap_data.json]
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ.setdefault("DOSSLAP_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="btd_"), "bt.db"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import models  # noqa: E402
from app.db import Base  # noqa: E402
from app.metrics import engine as E  # noqa: E402

IN = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/dosslap_data.json")
OUT = os.path.expanduser("~/Downloads/dosslap_backtest_detailed.xlsx")

QUADL = {"stable": "Stabilní", "overreaching": "Přetížení", "silent": "Tichý drift", "critical": "Kritické přetížení"}
QFILL = {"stable": "C6EFCE", "overreaching": "FFEB9C", "silent": "BDD7EE", "critical": "FFC7CE"}
HEAD = PatternFill("solid", fgColor="0A2540")
GRP = PatternFill("solid", fgColor="1B4A6B")
AXFILL = {"mech": "E7F0FF", "load": "FFF1E0", "symp": "F3E8FF"}

# signal id → axis (from engine.assess push() calls)
SIG_AXIS = {
    **{k: "mech" for k in ("tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv")},
    **{k: "load" for k in ("session_spike", "spike_latent", "pace_spike", "ewma", "hi_load",
                           "load_creep", "mono", "desc", "desc_steep", "aer", "hrv", "rhr",
                           "hrvcv", "tsb", "load_capacity", "taper")},
    **{k: "symp" for k in ("niggle", "pain", "pain_prior", "sore", "fatigue", "sleep", "sleepreg",
                           "sleepeff", "feel", "stiffness", "hist", "injury", "complaints")},
}
AXLABEL = {"mech": "Mechanika", "load": "Zátěž", "symp": "Příznaky"}

LEGEND = [
    ("mech", "tavr", "Vertikální poměr roste", "body = clamp((z − 0,2) , 0..4) × 17  → strop 17"),
    ("mech", "gct", "Prodloužený kontakt se zemí", "clamp((z − 0,2),0..4) × 13  → strop 13"),
    ("mech", "cad", "Klesající kadence", "clamp((−z − 0,2),0..4) × 10  → strop 10 (nižší kadence = riziko)"),
    ("mech", "vosc", "Vyšší vertikální oscilace", "clamp((z − 0,2),0..4) × 10  → strop 10"),
    ("mech", "bal", "Posun symetrie kontaktu", "clamp((exkurze − 0,4),0..3) × 22  → strop 22"),
    ("mech", "dec", "Klesající odolnost proti únavě", "clamp((trend − 0,1),0..1,2) × 26 (jen když >0,15)"),
    ("mech", "gaitcv", "Kolísavější mechanika", "(poměr CV − 1,5) × 14, strop 14 (od ×1,5)"),
    ("load", "session_spike", "Skok v jednom běhu", ">2,0×: 14+; >1,3×: (s−1,3)×20 do 14; >1,1×: (s−1,1)×25 do 6"),
    ("load", "spike_latent", "Doznívající skok (8–28 dní)", "clamp(latent × 22, 0..16), lineárně mizí do 28. dne"),
    ("load", "pace_spike", "Skok v tempu", "(poměr − 1,06) × 40, strop 10"),
    ("load", "ewma", "Poměr zátěže 7:28 (ACWR)", ">1,5: (r−1,5)×18 do 12, +2; <0,7: +10"),
    ("load", "hi_load", "Skok ve vysoké intenzitě", "(HI poměr − 1,5) × 20, strop 20 (když HI akut ≥60)"),
    ("load", "load_creep", "Postupný nárůst zátěže", "(creep − 1,15) × 30, strop 10 (když ACWR<1,3)"),
    ("load", "mono", "Monotónní trénink", "(monotonie − 2,4) × 7, strop 20"),
    ("load", "desc", "Nárůst sbíhání", "(poměr − 1,45) × 15, strop 14"),
    ("load", "desc_steep", "Strmé klesání ≥10 %", "(poměr − 1,5) × 12, strop 12 — excentrická zátěž"),
    ("load", "aer", "Aerobní decoupling", "(decoupling % − 5,5) × 3, strop 12"),
    ("load", "hrv", "Potlačená HRV", "clamp(−z × 10, 0..22) (když z ≤ −1,0)"),
    ("load", "rhr", "Zvýšený klidový tep", "clamp(z × 8, 0..18) (když z ≥ 1,2)"),
    ("load", "hrvcv", "Kolísavá HRV mezi dny", "(poměr − 1,4) × 14, strop 10"),
    ("load", "tsb", "Nepříznivá bilance zátěže", "(−rel − 0,12) × 90, strop 12 (rel = TSB/chronic)"),
    ("load", "load_capacity", "Zátěž na sníženou regeneraci", "kapacitní deficit × síla spiku × 34, strop 16"),
    ("symp", "niggle", "Opakované bolestivé místo", "eskaluje s počtem výskytů za 21 dní (grade A)"),
    ("symp", "pain", "Neustupující / opakující se bolest", "z check-inů; A/B podle přetrvání a lokality"),
    ("symp", "sore", "Vysoká svalová únava", "+10 (soreness ≥ práh)"),
    ("symp", "sleep", "Spánkový dluh", "clamp(dluh × 2,5, 0..16) (když ≥ 4 h/týden)"),
    ("symp", "feel", "Zhoršující se pocit z běhu", "+10 (klesající feeling)"),
    ("symp", "stiffness", "Ztuhlost nohou před během", "+10 / eskalace"),
    ("symp", "hist", "Zranění v anamnéze", "podle měsíců od zranění (grade A)"),
    ("symp", "injury", "Nahlášené/potvrzené zranění", "podle OSTRC/100 (A/B)"),
    ("*", "osa", "Osa = součet bodů × frailty, ořez 0–100", "mech·0,38 + load·0,30 + symp·0,52 → celkem; kvadrant z (load, mech)"),
]


def load_json_to_db(db, data):
    r = data["runner"]
    rcols = {c.name for c in models.Runner.__table__.columns}
    db.add(models.Runner(**{k: v for k, v in r.items() if k in rcols}))
    tbl = data.get("tables", {})
    for model in (models.Activity, models.DailyMetric, models.DeviceHistory, models.ActivityStream,
                  models.ActivityFeedback, models.Checkin, models.InjuryReport):
        cols = {c.name for c in model.__table__.columns}
        for row in tbl.get(model.__tablename__, []) or []:
            db.add(model(**{k: v for k, v in row.items() if k in cols}))
    db.commit()


def _dated(rows, field):
    return [(r, (r.get(field) or "")[:10]) for r in rows]


def replay(data, step_days=7):
    """Yield (as_of, v1, v2) full assessments, each on data up to that date."""
    rid = data["runner"]["id"]
    tbl = data.get("tables", {})
    acts = tbl.get("activities", [])
    dates = sorted(a["started_at"][:10] for a in acts if a.get("started_at"))
    if not dates:
        return
    ad = date.fromisoformat(dates[0]) + timedelta(days=7)  # small warm-up → near first run
    end = date.fromisoformat(dates[-1])
    asofs = []
    while ad <= end:
        asofs.append(ad); ad += timedelta(days=step_days)
    if not asofs or asofs[-1] != end:
        asofs.append(end)

    def rows(name):
        return tbl.get(name, []) or []
    prev1 = prev2 = None
    for adate in asofs:
        cut = adate.isoformat()
        with E.today_pinned(adate):
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            try:
                sub = {"runner": data["runner"], "tables": {}}
                # activities up to cut (+ their streams), daily/device/feedback/checkin/injury up to cut
                keep_ids = set()
                a_keep = []
                for a in rows("activities"):
                    if (a.get("started_at") or "")[:10] <= cut:
                        a_keep.append(a); keep_ids.add(a.get("id"))
                sub["tables"]["activities"] = a_keep
                sub["tables"]["activity_streams"] = [s for s in rows("activity_streams") if s.get("activity_id") in keep_ids]
                sub["tables"]["daily_metrics"] = [d for d in rows("daily_metrics") if (d.get("date") or "")[:10] <= cut]
                sub["tables"]["device_history"] = [d for d in rows("device_history") if (d.get("recorded_at") or "")[:10] <= cut]
                sub["tables"]["activity_feedback"] = [f for f in rows("activity_feedback") if (f.get("submitted_at") or "")[:10] <= cut]
                sub["tables"]["checkins"] = [c for c in rows("checkins") if (c.get("submitted_at") or "")[:10] <= cut]
                sub["tables"]["injury_reports"] = [i for i in rows("injury_reports") if (i.get("submitted_at") or "")[:10] <= cut]
                load_json_to_db(ts, sub)
                arow = models.Assessment(runner_id=rid, quadrant=prev1, tier="ok", mech=0, load=0, symp=0, overall=0, engine_version="x")
                ts.add(arow); ts.commit()
                with E.engine_pinned("v1"):
                    v1 = E.assess(ts, rid)
                arow.quadrant = prev2; ts.commit()
                with E.engine_pinned("v2"):
                    v2 = E.assess(ts, rid)
                prev1, prev2 = v1["quadrant"], v2["quadrant"]
                yield cut, v1, v2
            finally:
                ts.close(); eng.dispose()


def _hdr(ws, names, widths, row=1, fill=HEAD):
    for i, n in enumerate(names, 1):
        c = ws.cell(row=row, column=i, value=n)
        c.font = Font(bold=True, color="FFFFFF" if fill in (HEAD, GRP) else "000000")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[row].height = 24


def souhrn_sheet(ws, pts):
    _hdr(ws, ["datum", "v1 mech", "v1 zátěž", "v1 přízn.", "v1 celkem", "v1 kvadrant",
              "v2 mech", "v2 zátěž", "v2 přízn.", "v2 celkem", "v2 kvadrant", "v2 úseky", "v2 flag"],
         [11, 8, 8, 8, 9, 16, 8, 8, 8, 9, 16, 8, 8])
    row = 2
    for cut, v1, v2 in pts:
        vals = [cut, v1["mech"], v1["load"], v1["symp"], v1["overall"], None,
                v2["mech"], v2["load"], v2["symp"], v2["overall"], None,
                "✓" if v2.get("segmentScored") else "", "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else "")]
        for i, v in enumerate(vals, 1):
            if i in (6, 11):
                continue
            ws.cell(row=row, column=i, value=v)
        c1 = ws.cell(row=row, column=6, value=QUADL.get(v1["quadrant"])); c1.fill = PatternFill("solid", fgColor=QFILL[v1["quadrant"]])
        c2 = ws.cell(row=row, column=11, value=QUADL.get(v2["quadrant"])); c2.fill = PatternFill("solid", fgColor=QFILL[v2["quadrant"]])
        row += 1


def rozpad_sheet(ws, pts, which):
    _hdr(ws, ["datum", "osa", "signál", "+body", "hodnota", "proč"], [11, 12, 30, 7, 12, 70])
    row = 2
    for cut, v1, v2 in pts:
        a = v1 if which == 1 else v2
        sigs = a.get("signals") or []
        axtot = {"mech": a["mech"], "load": a["load"], "symp": a["symp"]}
        gc = ws.cell(row=row, column=1, value=f"{cut}  →  mech {axtot['mech']} · zátěž {axtot['load']} · příznaky {axtot['symp']} · CELKEM {a['overall']} · {QUADL.get(a['quadrant'])}")
        gc.font = Font(bold=True, color="FFFFFF"); gc.fill = GRP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1
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
            ws.cell(row=row, column=6, value=(s.get("detail") or "")[:300])
            row += 1
        row += 1


def drivery_sheet(ws, pts):
    cols = ["datum", "conf",
            "tavr z", "gct z", "kad z", "vosc z", "stride z", "bal exk", "dec tr", "gaitCV×",
            "ACWR", "běh spike×", "tempo×", "doznívá", "HI×", "creep×", "mono", "sběh×", "strmé×",
            "HRV z", "tep z", "TSB", "grade-adj km7", "sběh km7", "úseky", "flag"]
    _hdr(ws, cols, [11, 6] + [8] * (len(cols) - 2))
    row = 2
    for cut, v1, v2 in pts:
        L = v2.get("loadDetail") or {}
        rcv = v2.get("rcv") or {}
        gd = v2.get("gradientDescent") or {}
        def z(k, s="z"):
            return (v2.get(k) or {}).get(s)
        vals = [cut, round((v2.get("confidence") or {}).get("value", 0), 2),
                z("tavr"), z("gct"), z("cadence"), z("vosc"), z("stride"),
                (v2.get("bal") or {}).get("excursion"), (v2.get("dec") or {}).get("trend"),
                (v2.get("gaitCv") or {}).get("ratio"),
                L.get("ratio"), L.get("sessionSpike"), L.get("paceSpike"), L.get("spikeLatent"),
                L.get("hiRatio"), L.get("loadCreep"), L.get("monotony"),
                L.get("descentSpike"), gd.get("steepSpike"),
                (rcv.get("hrv") or {}).get("z"), (rcv.get("rhr") or {}).get("z"), L.get("tsbBalance"),
                L.get("gradeAdjKm7"), L.get("downhillKm7"),
                "✓" if v2.get("segmentScored") else "", "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else "")]
        for i, v in enumerate(vals, 1):
            ws.cell(row=row, column=i, value=v)
        row += 1


def legenda_sheet(ws):
    _hdr(ws, ["osa", "signál (id)", "název", "jak vzniká skóre"], [10, 16, 30, 90])
    row = 2
    for ax, sid, name, formula in LEGEND:
        ac = ws.cell(row=row, column=1, value=AXLABEL.get(ax, ax))
        if ax in AXFILL:
            ac.fill = PatternFill("solid", fgColor=AXFILL[ax])
        ws.cell(row=row, column=2, value=sid)
        ws.cell(row=row, column=3, value=name)
        ws.cell(row=row, column=4, value=formula)
        row += 1


def main():
    if not os.path.exists(IN):
        print(f"Soubor nenalezen: {IN}"); sys.exit(1)
    with open(IN, encoding="utf-8") as f:
        data = json.load(f)
    print(f"Načteno: {data['runner']['name']} ({data['runner']['id']}) · "
          f"{len(data['tables'].get('activities', []))} aktivit, "
          f"{len(data['tables'].get('activity_streams', []))} streamů")

    pts = list(replay(data, step_days=7))
    if not pts:
        print("Málo dat."); sys.exit(1)

    wb = Workbook()
    souhrn_sheet(wb.active, pts); wb.active.title = "Souhrn"
    rozpad_sheet(wb.create_sheet("Rozpad v1"), pts, 1)
    rozpad_sheet(wb.create_sheet("Rozpad v2"), pts, 2)
    drivery_sheet(wb.create_sheet("Drivery v2"), pts)
    legenda_sheet(wb.create_sheet("Legenda"))
    wb.save(OUT)

    print(f"\n{'datum':12} {'v1 m/l/s/Σ':>16} {'v1 kvadrant':14} {'v2 m/l/s/Σ':>16} {'v2 kvadrant':14} seg")
    for cut, v1, v2 in pts:
        s1 = f"{v1['mech']}/{v1['load']}/{v1['symp']}/{v1['overall']}"
        s2 = f"{v2['mech']}/{v2['load']}/{v2['symp']}/{v2['overall']}"
        seg = "✓" if v2.get("segmentScored") else ""
        print(f"{cut:12} {s1:>16} {v1['quadrant']:14} {s2:>16} {v2['quadrant']:14} {seg}")
    print(f"\nUloženo: {OUT}")


if __name__ == "__main__":
    main()
