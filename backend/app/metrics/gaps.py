"""Plan k cíli 2.0 #4 (owner decision 2026-10-13): days without any data from the watch.

Three or more days in a row with no activity and no night or day reading from the watch read
as rest to the engine, so the capacity drops and the plan starts lower than it should. The app
asks: did you run without the watch? The answer "rest" is kept (runners.planner_json["gaps"]) so
the question doesn't come back; a run logged by hand fills the day. Without an answer the days
stay rest, as before."""
from datetime import date, timedelta

from . import data as D

LOOKBACK = 21      # days the question looks back
MIN_GAP = 3        # days in a row


def _watch_days(data) -> set:
    return {m.date[:10] for m in data.daily
            if any(getattr(m, f, None) is not None for f in ("sleep_h", "hrv_ms", "resting_hr", "stress_avg", "body_battery"))}


def data_gap(db, rid: str, today: date) -> dict | None:
    """The most recent unanswered gap of LOOKBACK days {from, to, days}, or None. Only for a runner
    whose watch sent readings in the last 60 days (someone who logs by hand has no gaps to explain)."""
    data = D.of(db, rid)
    watch = _watch_days(data)
    if not any((today - timedelta(days=k)).isoformat() in watch for k in range(1, 61)):
        return None
    acts = {a.started_at[:10] for a in data.activities if a.started_at}
    first = min(watch | acts) if (watch | acts) else today.isoformat()
    answered = set(((getattr(data.runner, "planner_json", None) or {}).get("gaps") or {}).keys()) if data.runner else set()
    run: list = []
    for k in range(1, LOOKBACK + 1):
        d = (today - timedelta(days=k)).isoformat()
        empty = d >= first and d not in watch and d not in acts and d not in answered
        if empty:
            run.append(d)
        elif len(run) >= MIN_GAP:
            break
        else:
            run = []
    if len(run) < MIN_GAP:
        return None
    return {"from": min(run), "to": max(run), "days": len(run)}
