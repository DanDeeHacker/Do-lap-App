"""Backtest: original engine (v1) vs new sensitive engine (v2) on the same data.

Replays each runner's history week by week from the first usable date to today.
At every as-of date it scores the runner TWICE — once pinned to v1, once to v2 —
on a throwaway in-memory DB holding only the data that existed up to that date
(engine 'today' pinned to it), exactly like the app's mech-history replay. It
then compares mech / load / overall / quadrant, counts divergences and measures
lead time (how much earlier v2 reaches Silent/Critical than v1).

Note: v2 within-run SEGMENT scoring needs fetched streams, which the demo seed
doesn't have — so on this dataset v2 = per-run recency-EWMA + robust noise scale
+ pain-excluded baseline + grade-adjusted load. That's the part of the new
engine that is comparable on the data available here.

Run:  .venv_posix/bin/python build_backtest_engine_compare.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ.setdefault("DOSSLAP_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="bt_"), "bt.db"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, SessionLocal, engine as main_engine  # noqa: E402
from app import models, seed as seed_module  # noqa: E402
from app.metrics import engine as E  # noqa: E402

HOT = ("silent", "critical")  # mechanics-elevated quadrants


def _copy(rows, model):
    return [{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in rows]


def replay_both(db, rid, asofs):
    """Yield (as_of, v1_assessment, v2_assessment) for each date."""
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    acts = _copy(db.query(models.Activity).filter(models.Activity.runner_id == rid).all(), models.Activity)
    daily = _copy(db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid).all(), models.DailyMetric)
    devices = _copy(db.query(models.DeviceHistory).filter(models.DeviceHistory.runner_id == rid).all(), models.DeviceHistory)
    if not acts:
        return
    for adate in asofs:
        cut = adate.isoformat()
        with E.today_pinned(adate):
            eng = create_engine("sqlite://")
            Base.metadata.create_all(eng)
            ts = sessionmaker(bind=eng)()
            try:
                ts.add(models.Runner(**{k: v for k, v in rdata.items() if k != "engine_mode"}, engine_mode="v1"))
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
                with E.engine_pinned("v1"):
                    v1 = E.assess(ts, rid)
                with E.engine_pinned("v2"):
                    v2 = E.assess(ts, rid)
                yield adate, v1, v2
            finally:
                ts.close()
                eng.dispose()


def weekly_asofs(db, rid):
    dates = [a[0][:10] for a in db.query(models.Activity.started_at).filter(models.Activity.runner_id == rid).all()]
    if not dates:
        return []
    start = date.fromisoformat(min(dates)) + timedelta(days=42)  # need a baseline first
    end = E.today_date()
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    if not out or out[-1] != end:
        out.append(end)
    return out


def main():
    Base.metadata.create_all(bind=main_engine)
    db = SessionLocal()
    if db.query(models.Clinic).first() is None:
        seed_module.build_and_seed(db)

    import openpyxl
    wb = openpyxl.Workbook()
    detail = wb.active
    detail.title = "detail"
    detail.append(["runner", "as_of", "v1_mech", "v2_mech", "v1_load", "v2_load",
                   "v1_overall", "v2_overall", "v1_quadrant", "v2_quadrant", "quadrant_diff"])
    summ = wb.create_sheet("summary")
    summ.append(["runner", "points", "quadrant_diffs", "diff_%",
                 "mean_mech_v1", "mean_mech_v2", "v1_first_hot", "v2_first_hot", "lead_days",
                 "v1_final", "v2_final"])

    runners = db.query(models.Runner).order_by(models.Runner.id).all()
    print(f"{'runner':22} {'pts':>3} {'diff':>5} {'Δmech':>7} {'v1 first hot':>12} {'v2 first hot':>12} {'lead':>5} {'final v1→v2'}")
    tot_pts = tot_diff = 0
    for r in runners:
        asofs = weekly_asofs(db, r.id)
        if not asofs:
            continue
        pts = list(replay_both(db, r.id, asofs))
        if not pts:
            continue
        diffs = 0
        v1_first = v2_first = None
        m1 = m2 = 0.0
        for adate, v1, v2 in pts:
            qd = v1["quadrant"] != v2["quadrant"]
            diffs += qd
            m1 += v1["mech"]; m2 += v2["mech"]
            if v1_first is None and v1["quadrant"] in HOT:
                v1_first = adate
            if v2_first is None and v2["quadrant"] in HOT:
                v2_first = adate
            detail.append([r.name, adate.isoformat(), v1["mech"], v2["mech"], v1["load"], v2["load"],
                           v1["overall"], v2["overall"], v1["quadrant"], v2["quadrant"], "yes" if qd else ""])
        n = len(pts)
        lead = (v1_first - v2_first).days if (v1_first and v2_first) else (
            (E.today_date() - v2_first).days if (v2_first and not v1_first) else None)
        summ.append([r.name, n, diffs, round(100 * diffs / n, 1), round(m1 / n, 1), round(m2 / n, 1),
                     v1_first.isoformat() if v1_first else "—", v2_first.isoformat() if v2_first else "—",
                     lead if lead is not None else "—", pts[-1][1]["quadrant"], pts[-1][2]["quadrant"]])
        tot_pts += n; tot_diff += diffs
        print(f"{r.name:22} {n:>3} {diffs:>5} {round(m2/n-m1/n,1):>+7} "
              f"{(v1_first.isoformat() if v1_first else '—'):>12} {(v2_first.isoformat() if v2_first else '—'):>12} "
              f"{(str(lead) if lead is not None else '—'):>5} {pts[-1][1]['quadrant']}→{pts[-1][2]['quadrant']}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_engine_compare.xlsx")
    wb.save(out)
    print(f"\nTotal points {tot_pts} · quadrant diffs {tot_diff} ({round(100*tot_diff/max(tot_pts,1),1)}%)")
    print(f"Saved {out}")
    db.close()


if __name__ == "__main__":
    main()
