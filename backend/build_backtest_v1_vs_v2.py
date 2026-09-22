"""Backtest workbook — original engine (v1) vs new sensitive engine (v2), same
style as the v0.6.1 backtest: chronological weekly (and daily) replay with the
engine's numbers per date, colour-coded quadrants, plus per-driver detail.

Every as-of date is scored twice on a throwaway DB holding only the data that
existed then (engine 'today' pinned to it): once with the runner pinned to v1,
once to v2, with each engine's own hysteresis carried forward. Sheets:

  1. Souhrn        — per runner: points, quadrant diffs, lead time, means, finals.
  2. Týdně         — weekly rows, v1 vs v2 axes + quadrant + Δ + v2 drivers/signals.
  3. Denně (case)  — daily replay for the two demo cases (Tichý drift, Kritické).

Note: v2 within-run segment scoring needs fetched streams (the seed has none),
so here v2 = per-run recency-EWMA + robust noise + pain-excluded baseline +
grade-adjusted load. Self-report isn't replayed (objective wearable engine).

Run:  .venv_posix/bin/python build_backtest_v1_vs_v2.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ.setdefault("DOSSLAP_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="bt2_"), "bt.db"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import models, seed as seed_module  # noqa: E402
from app.db import Base, SessionLocal, engine as main_engine  # noqa: E402
from app.metrics import engine as E  # noqa: E402

OUT = "/Users/danieltrnovec/Downloads/dosslap_backtest_v1_vs_v2.xlsx"
HOT = ("silent", "critical")
QUADL = {"stable": "Stabilní", "overreaching": "Přetížení", "silent": "Tichý drift", "critical": "Kritické přetížení"}
HEAD = PatternFill("solid", fgColor="0A2540")
GRP = PatternFill("solid", fgColor="1B4A6B")
QFILL = {"stable": "C6EFCE", "overreaching": "FFEB9C", "silent": "BDD7EE", "critical": "FFC7CE"}


def _hdr(ws, names, widths, row, fill=HEAD):
    for i, n in enumerate(names, 1):
        c = ws.cell(row=row, column=i, value=n)
        c.font = Font(bold=True, color="FFFFFF" if fill in (HEAD, GRP) else "000000")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if row == 1 or fill == HEAD:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[row].height = 26


def _copy(src, model, rid):
    cols = [c.name for c in model.__table__.columns]
    return [{c: getattr(r, c) for c in cols} for r in src.query(model).filter(model.runner_id == rid).all()]


def replay_both(src, rid, step_days=7):
    """Yield per-date (as_of, v1, v2) dicts of the full assessment for a runner."""
    runner = src.query(models.Runner).filter(models.Runner.id == rid).first()
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = _copy(src, models.Activity, rid)
    daily = _copy(src, models.DailyMetric, rid)
    devices = _copy(src, models.DeviceHistory, rid)
    if not acts:
        return
    first = min(a["started_at"][:10] for a in acts)
    last = max(a["started_at"][:10] for a in acts)
    ad = date.fromisoformat(first) + timedelta(days=42)
    end = date.fromisoformat(last)
    asofs = []
    while ad <= end:
        asofs.append(ad)
        ad += timedelta(days=step_days)
    if not asofs or asofs[-1] != end:
        asofs.append(end)

    prev1 = prev2 = None
    for ad in asofs:
        with E.today_pinned(ad):
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            try:
                ts.add(models.Runner(**{k: v for k, v in rdata.items() if k != "engine_mode"}, engine_mode="v1"))
                cut = ad.isoformat()
                for a in acts:
                    if a["started_at"][:10] <= cut:
                        ts.add(models.Activity(**{k: v for k, v in a.items() if k != "id"}))
                for d in daily:
                    if d["date"][:10] <= cut:
                        ts.add(models.DailyMetric(**{k: v for k, v in d.items() if k != "id"}))
                for dv in devices:
                    if (dv.get("recorded_at") or "")[:10] <= cut:
                        ts.add(models.DeviceHistory(**{k: v for k, v in dv.items() if k != "id"}))
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
                yield cut, v1, v2
            finally:
                ts.close()
                eng.dispose()


WCOLS = [
    ("datum", 11), ("běhů", 6), ("conf", 6),
    ("v1 mech", 8), ("v1 load", 8), ("v1 symp", 8), ("v1 celk", 8), ("v1 kvadrant", 16),
    ("v2 mech", 8), ("v2 load", 8), ("v2 symp", 8), ("v2 celk", 8), ("v2 kvadrant", 16),
    ("Δ mech", 8), ("Δ load", 8), ("v2 flag", 8), ("v2 úseky", 8), ("v2 klíčové signály", 52),
]


def _qcell(ws, row, col, quad):
    c = ws.cell(row=row, column=col, value=QUADL.get(quad, quad))
    c.fill = PatternFill("solid", fgColor=QFILL.get(quad, "FFFFFF"))
    c.alignment = Alignment(horizontal="center")


def weekly_sheet(ws, runs_data):
    _hdr(ws, [c[0] for c in WCOLS], [c[1] for c in WCOLS], 1)
    row = 2
    for name, rng, pts in runs_data:
        gc = ws.cell(row=row, column=1, value=f"{name}   ({rng})")
        gc.font = Font(bold=True, color="FFFFFF")
        gc.fill = GRP
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(WCOLS))
        row += 1
        for cut, v1, v2 in pts:
            runs = sum(1 for _ in [0])  # placeholder; count from v1 load if present
            conf = round((v1.get("confidence") or {}).get("value", 0), 2)
            sig = " · ".join(f"{s['name']} (+{s['pts']})" for s in (v2.get("signals") or [])[:4]) or "—"
            vals = [cut, (v1.get("loadDetail") or {}).get("valid") and "✓" or "", conf,
                    v1["mech"], v1["load"], v1["symp"], v1["overall"], None,
                    v2["mech"], v2["load"], v2["symp"], v2["overall"], None,
                    v2["mech"] - v1["mech"], v2["load"] - v1["load"],
                    "⚑" if v2.get("mechFlag") else ("◔" if v2.get("mechWatch") else ""),
                    "✓" if v2.get("segmentScored") else "", sig]
            for i, val in enumerate(vals, 1):
                if i in (8, 13):
                    continue
                ws.cell(row=row, column=i, value=val)
            _qcell(ws, row, 8, v1["quadrant"])
            _qcell(ws, row, 13, v2["quadrant"])
            row += 1
        row += 1


def main():
    Base.metadata.create_all(bind=main_engine)
    db = SessionLocal()
    if db.query(models.Clinic).first() is None:
        seed_module.build_and_seed(db)

    wb = Workbook()
    summ = wb.active
    summ.title = "Souhrn"
    _hdr(summ, ["běžec", "bodů", "shoda kvadrantů %", "rozdílů", "ø mech v1", "ø mech v2",
                "v1 první zvýšený", "v2 první zvýšený", "předstih v2 (dny)", "finále v1", "finále v2"],
         [22, 7, 16, 8, 10, 10, 16, 16, 16, 18, 18], 1)
    weekly = wb.create_sheet("Týdně")
    daily_sheets = {}

    runners = db.query(models.Runner).order_by(models.Runner.id).all()
    runs_weekly = []
    srow = 2
    tot_pts = tot_diff = 0
    print(f"{'běžec':22} {'body':>4} {'shoda%':>7} {'Δmech':>7} {'předstih':>8} {'finále v1→v2'}")
    for r in runners:
        pts = list(replay_both(db, r.id, step_days=7))
        if not pts:
            continue
        rng = f"{pts[0][0]} → {pts[-1][0]}"
        runs_weekly.append((r.name, rng, pts))
        diffs = sum(1 for _, v1, v2 in pts if v1["quadrant"] != v2["quadrant"])
        m1 = sum(v1["mech"] for _, v1, _ in pts) / len(pts)
        m2 = sum(v2["mech"] for _, _, v2 in pts) / len(pts)
        f1 = next((c for c, v1, _ in pts if v1["quadrant"] in HOT), None)
        f2 = next((c for c, _, v2 in pts if v2["quadrant"] in HOT), None)
        lead = (date.fromisoformat(f1) - date.fromisoformat(f2)).days if (f1 and f2) else None
        agree = round(100 * (len(pts) - diffs) / len(pts), 1)
        for j, val in enumerate([r.name, len(pts), agree, diffs, round(m1, 1), round(m2, 1),
                                 f1 or "—", f2 or "—", lead if lead is not None else "—",
                                 QUADL[pts[-1][1]["quadrant"]], QUADL[pts[-1][2]["quadrant"]]], 1):
            summ.cell(row=srow, column=j, value=val)
        srow += 1
        tot_pts += len(pts); tot_diff += diffs
        print(f"{r.name:22} {len(pts):>4} {agree:>7} {round(m2-m1,1):>+7} "
              f"{(str(lead) if lead is not None else '—'):>8} {pts[-1][1]['quadrant']}→{pts[-1][2]['quadrant']}")
        # daily detail for the two demo cases
        if r.name in ("Tichý drift", "Kritické přetížení"):
            dpts = list(replay_both(db, r.id, step_days=1))
            ws = wb.create_sheet(f"Denně · {r.name[:12]}")
            weekly_sheet(ws, [(r.name, rng, dpts)])
            daily_sheets[r.name] = len(dpts)

    weekly_sheet(weekly, runs_weekly)
    summ.cell(row=srow + 1, column=1, value=f"Celkem {tot_pts} bodů · shoda kvadrantů {round(100*(tot_pts-tot_diff)/max(tot_pts,1),1)} %").font = Font(bold=True)
    wb.save(OUT)
    print(f"\nCelkem {tot_pts} bodů · shoda {round(100*(tot_pts-tot_diff)/max(tot_pts,1),1)} % · rozdílů {tot_diff}")
    print(f"Uloženo: {OUT}")
    db.close()


if __name__ == "__main__":
    main()
