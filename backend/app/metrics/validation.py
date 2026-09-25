"""Engine validation against real injuries (prevention plan C3).

For an injury date, replay the engine day by day — each morning with only the
data known then — from `before` days ahead of the injury to `after` days past
it, and summarise whether and how early it warned:

  • activities, ratings, check-ins and injury reports enter the day AFTER they
    happen (the morning's view is "before today's run");
  • the watch's overnight data (sleep, HRV, resting HR) enters on its own day —
    it is known in the morning, before the run;
  • the race calendar is a plan, known from the start.

"Warned" = the risk label was at least "watch" (A4 keeps it consistent with the
quadrant) or, with the Kapacitní engine, today's guidance stopped or cut running
for a risk reason (an override, or only a recovery run / rest while the weekly
plan still had room).

  python -m app.metrics.validation run-0011 2026-04-25 [--mode v3] [--before 42]
"""
import argparse
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .. import models
from ..db import Base
from . import engine as E

# (model, day-of-row, enters on its own day?) — see the module docstring
_STREAMS = (
    (models.Activity, "started_at", False),
    (models.DailyMetric, "date", True),
    (models.DeviceHistory, "recorded_at", False),
    (models.Checkin, "submitted_at", False),
    (models.ActivityFeedback, "submitted_at", False),
    (models.InjuryReport, "submitted_at", False),
)
_KEEP_ID = {models.Activity, models.ActivityStream}   # feedback / streams point at activity ids


def _rows(db, model, rid):
    return [{c.name: getattr(x, c.name) for c in model.__table__.columns}
            for x in db.query(model).filter(model.runner_id == rid).all()]


def replay_days(db, rid: str, days: list[date], mode: str | None = None) -> list[tuple[date, dict]]:
    """The engine's assessment (plus v3 guidance) on each morning in `days`
    (ascending), from a private in-memory copy of the runner's data."""
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if runner is None or not days:
        return []
    mode = mode or runner.engine_mode or "v1"
    rdata = {c.name: getattr(runner, c.name) for c in models.Runner.__table__.columns}
    rdata["cycle_override"] = None                  # a manual pick belongs to its own week, not the replay
    streams = []
    for model, col, same_day in _STREAMS:
        rows = sorted((r for r in _rows(db, model, rid) if r.get(col)), key=lambda r, c=col: str(r[c])[:10])
        streams.append((model, rows, lambda r, c=col: str(r[c])[:10], same_day))
    act_day = {r["id"]: str(r["started_at"])[:10] for r in streams[0][1]}
    stream_rows = [s for s in _rows(db, models.ActivityStream, rid) if s["activity_id"] in act_day]
    stream_rows.sort(key=lambda s: act_day.get(s["activity_id"], ""))
    streams.append((models.ActivityStream, stream_rows, lambda s: act_day.get(s["activity_id"], ""), False))

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    ts = sessionmaker(bind=eng)()
    out, prev_q = [], None
    ptr = [0] * len(streams)
    try:
        ts.add(models.Runner(**rdata))
        for x in _rows(db, models.Race, rid):
            ts.add(models.Race(**x))
        ts.commit()
        for day in days:
            cut = day.isoformat()
            with E.today_pinned(day), E.engine_pinned(mode):
                for i, (model, rows, keyf, same_day) in enumerate(streams):
                    p = ptr[i]
                    while p < len(rows) and (keyf(rows[p]) <= cut if same_day else keyf(rows[p]) < cut):
                        row = rows[p] if model in _KEEP_ID else {k: v for k, v in rows[p].items() if k != "id"}
                        ts.add(model(**row))
                        p += 1
                    ptr[i] = p
                # the profile's prior injury exists only from its date on (without a
                # date it can't be placed and stays, like the live engine treats it)
                inj_day = str(rdata.get("prior_injury_date") or "")[:10]
                rr = ts.query(models.Runner).filter(models.Runner.id == rid).first()
                hide = bool(inj_day) and inj_day >= cut
                for k in ("prior_injury", "prior_injury_date", "prior_injury_side", "prior_injury_months_ago"):
                    setattr(rr, k, None if hide else rdata.get(k))
                ts.query(models.Assessment).delete()
                if prev_q:              # the quadrant has hysteresis — carry yesterday's
                    ts.add(models.Assessment(runner_id=rid, quadrant=prev_q, tier="ok", mech=0, load=0, symp=0,
                                             overall=0, engine_version=E.ENGINE_VERSION))
                ts.commit()
                a = E.assess(ts, rid)
                a["guidance"] = None
                if mode == "v3":
                    from . import guidance as G
                    a["guidance"] = G.build_guidance(ts, rid, a, ts.query(models.Runner).filter(models.Runner.id == rid).first())
            out.append((day, a))
            prev_q = a["quadrant"]
    finally:
        ts.close()
        eng.dispose()
    return out


def _warned(a: dict) -> bool:
    if a.get("tier") in ("watch", "alert"):
        return True
    g = a.get("guidance") or {}
    if g.get("override"):
        return True
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    return g.get("type") in ("volno", "regenerace") and vol.get("limitedBy") not in ("week", None)


def _day_row(day: date, a: dict) -> dict:
    g = a.get("guidance") or {}
    return {"date": day.isoformat(), "quadrant": a["quadrant"], "tier": a["tier"], "overall": a["overall"],
            "load": a["load"], "mech": a["mech"], "symp": a["symp"], "warned": _warned(a),
            "type": g.get("type"), "override": (g.get("override") or {}).get("kind"),
            "signals": [f"{s['name']} +{s['pts']}" for s in (a.get("signals") or [])[:3]]}


def injury_timeline(db, rid: str, injury_date: str, before: int = 42, after: int = 7, mode: str | None = None) -> dict:
    """How the engine behaved around one injury. Returns
    {injuryDate, mode, days[], firstWarning, leadDays, warnedDaysBefore,
    daysBefore, onInjuryDay} — `firstWarning` is the start of the warning run
    that was still on when the injury happened (an earlier warning that ended
    doesn't count as lead time)."""
    d0 = date.fromisoformat(injury_date[:10])
    days = [d0 + timedelta(days=k) for k in range(-before, after + 1)]
    days = [d for d in days if d <= E.today_date()]
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    mode = mode or (runner.engine_mode if runner else None) or "v1"
    rows = [_day_row(d, a) for d, a in replay_days(db, rid, days, mode)]
    pre = [r for r in rows if r["date"] <= d0.isoformat()]
    first = None
    for r in reversed(pre):            # walk back from the injury day while it kept warning
        if not r["warned"]:
            break
        first = r["date"]
    return {
        "injuryDate": d0.isoformat(), "mode": mode, "days": rows,
        "firstWarning": first,
        "leadDays": (d0 - date.fromisoformat(first)).days if first else None,
        "warnedDaysBefore": sum(1 for r in pre if r["warned"] and r["date"] < d0.isoformat()),
        "daysBefore": sum(1 for r in pre if r["date"] < d0.isoformat()),
        "onInjuryDay": next((r for r in rows if r["date"] == d0.isoformat()), None),
    }


def injury_dates(db, rid: str) -> list[str]:
    """Known injuries of a runner: the start of each reported episode (OSTRC
    severity > 0) and the profile's prior-injury date."""
    out = set()
    reps = sorted(db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid,
                                                       models.InjuryReport.severity > 0).all(),
                  key=lambda x: x.submitted_at)
    last_end = None
    for x in reps:
        start = x.submitted_at[:10]
        if last_end is None or start > last_end:        # a new episode
            out.add(start)
        last_end = max(last_end or "", (x.resolved_at or E.iso_date(E.today_date()))[:10])
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r and r.prior_injury_date:
        out.add(str(r.prior_injury_date)[:10])
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay the engine around an injury.")
    ap.add_argument("runner_id")
    ap.add_argument("injury_date", nargs="?", help="YYYY-MM-DD (default: every known injury)")
    ap.add_argument("--mode", default=None)
    ap.add_argument("--before", type=int, default=42)
    ap.add_argument("--after", type=int, default=7)
    args = ap.parse_args(argv)
    from ..db import SessionLocal
    db = SessionLocal()
    for d in ([args.injury_date] if args.injury_date else injury_dates(db, args.runner_id)):
        t = injury_timeline(db, args.runner_id, d, args.before, args.after, args.mode)
        print(f"\n=== {args.runner_id} · zranění {t['injuryDate']} · engine {t['mode']} ===")
        for r in t["days"]:
            mark = "!" if r["warned"] else " "
            print(f"{r['date']} {mark} {r['quadrant'][:5]:5s} {r['tier']:5s} ov{r['overall']:3d} "
                  f"L{r['load']:3d} M{r['mech']:3d} S{r['symp']:3d} {r['type'] or '':10s} {r['override'] or '':12s} "
                  + "; ".join(r["signals"]))
        print(f"→ varování od {t['firstWarning'] or '—'} (předstih {t['leadDays'] if t['leadDays'] is not None else '—'} dní), "
              f"varovných dní před zraněním {t['warnedDaysBefore']}/{t['daysBefore']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
