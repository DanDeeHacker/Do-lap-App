"""Plan k cíli 2.0 #20 (owner decision 2026-10-13): backtesting and calibration.

Studies on training and injury disagree (Fredette et al., 2022), so the planner's margins and
thresholds have to be confirmed by its own data. Two checks, both read-only:

  • the projection against reality — the engine replays history to any day: from a day 8 weeks
    back the planner projects the weekly capacity a runner following the plan would have today, and
    the engine computes the capacity the runner really has, on the same core
    (capacity.weekly_capacity_vals). Only runners who ran at least 80 % of the projected volume count;
  • the goals' outcomes (#19) — at the start without an injury, finished, the time against the
    estimate, and the chance's calibration: of the runners given about 80 %, about 80 % should get
    there (75–85 %).

Targets (the proposal): ≥ 90 % at the start without an injury, ≥ 93 % of the starters finish (7.3 %
don't on average, Doherty 2019), the time estimate within ± 3 %, the 80 % bin within 75–85 %.
The margins and thresholds change only on this data."""
from datetime import date, timedelta

from . import engine as E
from . import goal_plan as GP

TARGETS = {"startNoInjury": 90.0, "finishOfStarters": 93.0, "timeErrPct": 3.0, "calib80": (75.0, 85.0)}
BINS = ((0, 50), (50, 80), (80, 101))
REPLAY_WEEKS = 8
FOLLOWED = 0.8
MIN_HIST_WEEKS = 12


def _pct(a: int, n: int) -> float | None:
    return round(100.0 * a / n, 1) if n else None


def outcome_kpis(db, rids: list | None = None) -> dict:
    """The goals' outcomes against the targets (all runners, or `rids`)."""
    from .. import models
    q = db.query(models.Goal).filter(models.Goal.outcome_json.isnot(None))
    if rids is not None:
        q = q.filter(models.Goal.runner_id.in_(rids))
    rows = [g.outcome_json for g in q.all() if g.outcome_json and not g.outcome_json.get("skipped")]
    n = len(rows)
    started = [r for r in rows if r.get("started")]
    ok_start = [r for r in started if not r.get("injury")]
    finished = [r for r in started if r.get("finished")]
    errs = [abs(r["timeS"] - r["predTimeS"]) / r["timeS"] * 100 for r in finished
            if r.get("timeS") and r.get("predTimeS")]
    calib = []
    for lo, hi in BINS:
        b = [r for r in rows if r.get("chanceFirst") is not None and lo <= r["chanceFirst"] < hi]
        calib.append({"from": lo, "to": min(hi, 100), "n": len(b),
                      "ready": _pct(sum(1 for r in b if r.get("started") and not r.get("injury")), len(b))})
    return {"goals": n, "startNoInjury": _pct(len(ok_start), n), "finishOfStarters": _pct(len(finished), len(started)),
            "timeErrPct": round(sorted(errs)[len(errs) // 2], 1) if errs else None, "timeN": len(errs),
            "kmPct": round(sum(r["kmPct"] for r in rows if r.get("kmPct") is not None)
                           / max(1, sum(1 for r in rows if r.get("kmPct") is not None)), 1) if rows else None,
            "calibration": calib, "targets": TARGETS}


def replay_projection(db, rid: str, today: date | None = None) -> dict | None:
    """The planner's 8-week projection from a day 8 weeks back against the capacity the runner has
    today: {predicted, actual, errPct, followed}. None without 12 weeks of history before."""
    today = today or E.today_date()
    mon = today - timedelta(days=today.weekday())
    anchor = mon - timedelta(days=7 * REPLAY_WEEKS)
    st0 = GP.runner_state(db, rid, None, anchor)
    if sum(1 for w in st0["weeks"] if w["runs"]) < MIN_HIST_WEEKS * 0.75 or not st0.get("days"):
        return None
    big = {"week": {"need": 1e6}}
    proj = GP.project(big, st0, GP.SAFE, 1, until=REPLAY_WEEKS)
    rows = proj["rows"][:REPLAY_WEEKS]
    dd = list(st0["days"]["km"])
    for r in rows:
        dd += GP._week_days(r["km"], r.get("long") or 0.0)
    known0 = st0.get("known") or 0
    pain0 = list(st0.get("pain") or []) + [False] * (7 * REPLAY_WEEKS)
    predicted = GP._engine_cap(dd, pain0, known0 + 7 * REPLAY_WEEKS, "volume")
    st1 = GP.runner_state(db, rid, None, today)
    actual = GP._engine_cap(st1["days"]["km"], st1.get("pain"), st1.get("known") or 0, "volume")
    if not predicted or not actual:
        return None
    ran = sum(w["km"] for w in st1["weeks"][-REPLAY_WEEKS:])
    planned = sum(r["km"] for r in rows)
    return {"anchor": anchor.isoformat(), "predicted": round(predicted, 1), "actual": round(actual, 1),
            "errPct": round((actual - predicted) / predicted * 100, 1),
            "followed": planned > 0 and ran >= FOLLOWED * planned, "ranPct": round(100 * ran / planned) if planned else None}


def projection_kpis(db, limit: int = 200) -> dict:
    """The replay over every runner with enough history; the error counts only those who followed."""
    from .. import models
    out = []
    for (rid,) in db.query(models.Runner.id).limit(limit).all():
        try:
            r = replay_projection(db, rid)
        except Exception:                    # one runner's odd data never takes the report down
            r = None
        if r:
            out.append(r)
    fol = [r["errPct"] for r in out if r["followed"]]
    fol.sort()
    return {"runners": len(out), "followed": len(fol),
            "medianErrPct": fol[len(fol) // 2] if fol else None,
            "medianAbsErrPct": sorted(abs(x) for x in fol)[len(fol) // 2] if fol else None}
