"""In-app Excel export: v1-vs-v2 engine backtest for one runner, on that runner's
own data (whatever DB the server is connected to — SQLite in dev, the runner's
Railway Postgres in production). Same layout as the standalone backtest script,
scoped to a single runner so it can be streamed as a download.

Each weekly/daily as-of date is scored twice on a throwaway in-memory DB holding
only the data that existed then (engine 'today' pinned), once per engine, with
each engine's own hysteresis carried forward.
"""
import io
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


def _replay_both(db, rid, step_days):
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if not runner:
        return []
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = _copy(db, models.Activity, rid)
    daily = _copy(db, models.DailyMetric, rid)
    devices = _copy(db, models.DeviceHistory, rid)
    acts = [a for a in acts if a.get("started_at")]
    if not acts:
        return []
    first = min(a["started_at"][:10] for a in acts)
    last = max(a["started_at"][:10] for a in acts)
    ad = date.fromisoformat(first) + timedelta(days=42)
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
                        ts.add(models.Activity(**{k: v for k, v in a.items() if k != "id"}))
                for d in daily:
                    if (d.get("date") or "")[:10] <= cut:
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

    daily = _replay_both(db, rid, step_days=1)
    if daily:
        dy = wb.create_sheet("Denně")
        _hdr(dy, [c[0] for c in WCOLS], [c[1] for c in WCOLS])
        _fill_rows(dy, daily)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
