"""Engine history replays and the precomputed daily quadrant history.

The quadrant history (the Dnes strip, the Pohyb and Zátěž daily trend charts)
replays assess() once per calendar day over ~6 months. A full replay costs
roughly 50 ms per day, so rebuilding it on a page view made the runner wait
several seconds. This module keeps it off the hot path:

* Incremental. The replay of day X depends only on the rows dated on or before
  X (plus the runner profile and the race calendar). The cache therefore stores
  a digest of the input rows per calendar day next to the result. On the next
  build only the days from the first changed date onward are replayed, seeded
  with the stored quadrant of the day before so hysteresis carries over. A new
  day costs one replayed day, a check-in today costs one replayed day, and an
  edit of an old run replays from that run's date.
* Precomputed. engine.recompute_assessment marks the cache dirty on a data
  change and hands the runner to app.precompute, whose background worker
  rebuilds it right away, so the history is ready before anyone opens it. A
  nightly warm-up extends every active runner's history for the new day.
"""
import hashlib
import json
import os
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import data as D
from .metrics import engine as E

# ~6 months of daily state, so the quadrant strip shows the long arc.
QUAD_HISTORY_DAYS = 183

# Bump when the history *shape/window* logic changes. The code fingerprint below
# also turns the key over whenever the engine sources change, so a deploy that
# alters scoring without an ENGINE_VERSION bump can't serve an outdated history.
HISTORY_VERSION = "h10"


# v0.9.0 — modules that never change a replayed day (texts, coach, the sandbox, the
# signal sources, today's guidance): editing them no longer throws away every cached
# history. A denylist, so a new scoring module is fingerprinted by default.
NON_SCORING = frozenset({"ai_brief.py", "coach_facts.py", "coach_texts.py", "coach_validate.py", "sig_doc.py",
                         "signal_sources.py", "sensitivity.py", "validation.py", "geo_sample.py", "guidance.py"})


def _code_fingerprint() -> str:
    h = hashlib.blake2b(digest_size=6)
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics")
    paths = sorted(os.path.join(base, f) for f in os.listdir(base) if f.endswith(".py") and f not in NON_SCORING)
    for p in paths + [os.path.abspath(__file__)]:
        with open(p, "rb") as f:
            h.update(os.path.basename(p).encode())
            h.update(f.read())
    return h.hexdigest()


CODE_FP = _code_fingerprint()


def history_key(mode: str | None) -> str:
    """Cache validity key: engine version for the runner's mode + history shape + code."""
    from .metrics import reference as REF
    return f"{E.engine_version_for(mode or 'v1')}|{HISTORY_VERSION}|{CODE_FP}|{REF.fingerprint()}"


def _kd(v) -> str:  # date key from an ISO date or datetime string
    return (v or "")[:10]


def load_inputs(db: DBSession, rid: str):
    """Everything a replay needs, read once as the runner's RunnerData snapshot
    (metrics/data.py), plus the per-date row streams the incremental cache digests.
    Returns None when the runner doesn't exist or has no activities."""
    data = D.load_runner_data(db, rid)
    if data.runner is None or not data.activities:
        return None
    acts = [dict(vars(a)) for a in data.activities]
    act_day = {a["id"]: _kd(a["started_at"]) for a in acts}
    # Stored per-run streams (segments) enter on their activity's day, so a v2
    # runner's history (and its "today" point) sees the segment scoring live does.
    stream_rows = [dict(vars(s)) for s in data.streams if s.activity_id in act_day]

    def rows(xs):
        return [dict(vars(x)) for x in xs]
    # (name, rows sorted by date, date-key fn, keep id?) — the digest of each day's
    # rows decides from which day an incremental rebuild has to replay.
    streams = [
        ("act", sorted(acts, key=lambda a: a["started_at"]), lambda a: _kd(a["started_at"]), True),
        ("str", sorted(stream_rows, key=lambda s: act_day[s["activity_id"]]), lambda s: act_day[s["activity_id"]], True),
        ("day", sorted(rows(data.daily), key=lambda d: d["date"]), lambda d: _kd(d["date"]), False),
        ("dev", sorted(rows(data.devices), key=lambda x: x.get("recorded_at") or ""), lambda x: _kd(x.get("recorded_at")), False),
        ("chk", sorted(rows(data.checkins), key=lambda x: x.get("submitted_at") or ""), lambda x: _kd(x.get("submitted_at")), False),
        ("fb", sorted(rows(data.feedback), key=lambda x: x.get("submitted_at") or ""), lambda x: _kd(x.get("submitted_at")), False),
        ("inj", sorted(rows(data.injuries), key=lambda x: x.get("submitted_at") or ""), lambda x: _kd(x.get("submitted_at")), False),
    ]
    return {
        "rdata": dict(vars(data.runner)),
        "races": rows(data.races),   # the race calendar is a plan, known from the start
        "streams": streams,
        "mode": data.runner.engine_mode or "v1",
        "first_act": min(act_day.values()),
        "data": data,
    }


def engine_replay(db: DBSession, rid: str, asofs, mode: str | None = None,
                  prev_q: str | None = None, inputs=None):
    """Replay assess() as of each date in `asofs` (ascending) with the engine
    'today' pinned to it. Each day is assessed on `data.as_of(day)`: the runner's
    objective data AND self-report (check-ins, run ratings, injury reports) known
    on that day, so each historical point matches the state the runner saw then.
    No database is touched after the one read in load_inputs.

    `prev_q` seeds the quadrant of the day before the first date (hysteresis),
    which lets an incremental build continue a cached chain exactly."""
    inp = inputs if inputs is not None else load_inputs(db, rid)
    if inp is None or not asofs:
        return []
    data = inp["data"]
    mode = mode or inp["mode"]
    out = []
    for adate in asofs:
        cut = adate.isoformat()
        # Pin "today" thread-locally (not a module global) so concurrent
        # requests in FastAPI's threadpool can't corrupt each other's clock.
        with E.today_pinned(adate), E.engine_pinned(mode):
            av = E.assess(data.as_of(cut, prev_q), rid)
        av["_cut"] = cut
        out.append(av)
        prev_q = av["quadrant"]
    return out


def input_digests(inp) -> tuple[str, dict]:
    """(global digest, {date: digest}) of the replay inputs. The global part is
    what every day sees (profile, races), the per-day part is the rows keyed to
    that date. A row the replay strips of its id is digested without it too."""
    per_day: dict[str, list[str]] = {}
    for name, rows, keyf, keep_id in inp["streams"]:
        for r in rows:
            data = r if keep_id else {k: v for k, v in r.items() if k != "id"}
            per_day.setdefault(keyf(r), []).append(name + ":" + json.dumps(data, sort_keys=True, default=str))
    days = {d: hashlib.blake2b("\n".join(sorted(v)).encode(), digest_size=8).hexdigest()
            for d, v in per_day.items()}
    races = sorted(json.dumps(x, sort_keys=True, default=str) for x in inp["races"])
    glob = hashlib.blake2b(json.dumps([inp["rdata"], races], sort_keys=True, default=str).encode(),
                           digest_size=8).hexdigest()
    return glob, days


def first_changed_day(old: dict, new: dict) -> str | None:
    changed = [d for d in set(old) | set(new) if old.get(d) != new.get(d)]
    return min(changed) if changed else None


def _quad_row(av: dict) -> dict:
    """Everything the Dnes overview draws (feedback railway#88), so a past day
    renders the same rings, verdict and drivers as today."""
    pr = av.get("painRecurring")
    rd = av.get("readiness") or (av.get("capacity") or {}).get("readiness") or {}
    rs = rd.get("score")
    return {"date": av["_cut"], "quadrant": av["quadrant"], "overall": av["overall"],
            "tier": av["tier"], "mech": av["mech"], "load": av["load"], "symp": av["symp"],
            # railway#194: the morning's readiness (after the night, before the day lowered it) for the trend
            "readiness": rs, "readinessMorning": rd.get("morningScore") if rd.get("morningScore") is not None else rs,
            "painRecurring": {"site": pr.get("site"), "days": pr.get("days")} if pr else None,
            "signals": [{"id": s.get("id"), "name": s["name"], "pts": s["pts"], "grade": s["grade"], "val": s.get("val")}
                        for s in (av.get("signals") or [])[:5]]}


def _window_start(first_act: str, today: date, days: int) -> date:
    # Back the full window (default ~6 months), bounded only by when the runner's
    # data actually starts (no 42-day baseline warmup offset).
    return max(date.fromisoformat(first_act), today - timedelta(days=days - 1))


def _day_range(a: date, b: date) -> list[date]:
    out = []
    while a <= b:
        out.append(a)
        a += timedelta(days=1)
    return out


def build_quadrant_history(db: DBSession, rid: str, days: int = QUAD_HISTORY_DAYS) -> list:
    """Full, uncached replay of a custom window (the endpoint's non-default `days`)."""
    inp = load_inputs(db, rid)
    if inp is None:
        return []
    today = E.today_date()
    asofs = _day_range(_window_start(inp["first_act"], today, days), today)
    return [_quad_row(av) for av in engine_replay(db, rid, asofs, inputs=inp)]


def _cache_row(db: DBSession, rid: str, kind: str):
    return (db.query(models.EngineHistoryCache)
              .filter(models.EngineHistoryCache.runner_id == rid, models.EngineHistoryCache.kind == kind)
              .first())


def store_cache(db: DBSession, rid: str, kind: str, key: str, computed_for, payload) -> None:
    row = _cache_row(db, rid, kind)
    if row is None:
        row = models.EngineHistoryCache(runner_id=rid, kind=kind)
        db.add(row)
    row.engine_version, row.computed_for, row.payload_json, row.updated_at = key, computed_for, payload, E.now_iso()
    try:
        db.commit()
    except IntegrityError:
        # Two builders filled the same cold cache at once and the other one
        # inserted first; the payload is computed, so update that row instead.
        db.rollback()
        (db.query(models.EngineHistoryCache)
           .filter(models.EngineHistoryCache.runner_id == rid, models.EngineHistoryCache.kind == kind)
           .update({"engine_version": key, "computed_for": computed_for, "payload_json": payload,
                    "updated_at": E.now_iso()}))
        db.commit()


def quadrant_cache_fresh(db: DBSession, rid: str):
    """The cached rows when they are valid for today and not marked dirty, else None."""
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    row = _cache_row(db, rid, "quadrant")
    if (row and r and row.engine_version == history_key(r.engine_mode)
            and row.computed_for == E.iso_date(E.today_date()) and isinstance(row.payload_json, dict)):
        return row.payload_json.get("rows") or []
    return None


def quadrant_cache_any(db: DBSession, rid: str):
    """Whatever rows are cached (possibly stale), or None. A fallback only."""
    row = _cache_row(db, rid, "quadrant")
    if row and isinstance(row.payload_json, dict):
        return row.payload_json.get("rows")
    return None


def refresh_quadrant_history(db: DBSession, rid: str) -> dict:
    """Bring the cached daily quadrant history up to date and return stats
    {"rows", "replayed", "kept"}. Only the days from the first changed input date
    (or the first day not cached yet) through today are replayed."""
    today = E.today_date()
    tiso = today.isoformat()
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is None:
        return {"rows": [], "replayed": 0, "kept": 0}
    key = history_key(r.engine_mode)
    row = _cache_row(db, rid, "quadrant")
    cached = row.payload_json if (row and row.engine_version == key and isinstance(row.payload_json, dict)) else None

    inp = load_inputs(db, rid)
    if inp is None:
        store_cache(db, rid, "quadrant", key, tiso, {"rows": [], "glob": None, "days": {}})
        return {"rows": [], "replayed": 0, "kept": 0}
    glob, digests = input_digests(inp)
    start = _window_start(inp["first_act"], today, QUAD_HISTORY_DAYS)
    siso = start.isoformat()

    keep = []
    if cached is not None and cached.get("glob") == glob:
        ch = first_changed_day(cached.get("days") or {}, digests)
        keep = [x for x in (cached.get("rows") or [])
                if siso <= x["date"] <= tiso and (ch is None or x["date"] < ch)]
        # The kept prefix must start on the window's first day and have no gaps,
        # else fall back to a full replay.
        if keep and [x["date"] for x in keep] != [d.isoformat() for d in _day_range(start, date.fromisoformat(keep[-1]["date"]))]:
            keep = []
    first = date.fromisoformat(keep[-1]["date"]) + timedelta(days=1) if keep else start
    asofs = _day_range(first, today)
    new = [_quad_row(av) for av in engine_replay(db, rid, asofs, inputs=inp,
                                                 prev_q=keep[-1]["quadrant"] if keep else None)]
    rows = keep + new
    store_cache(db, rid, "quadrant", key, tiso, {"rows": rows, "glob": glob, "days": digests})
    return {"rows": rows, "replayed": len(new), "kept": len(keep)}


def mark_dirty(db: DBSession, rid: str) -> None:
    """Called (uncommitted) from engine.recompute_assessment on a data change: the
    quadrant history keeps its rows as the base for an incremental rebuild but is
    flagged for a re-check, and the full-rebuild kinds (weekly mech, engine
    compare) are dropped."""
    (db.query(models.EngineHistoryCache)
       .filter(models.EngineHistoryCache.runner_id == rid, models.EngineHistoryCache.kind == "quadrant")
       .update({"computed_for": None, "updated_at": E.now_iso()}, synchronize_session=False))
    (db.query(models.EngineHistoryCache)
       .filter(models.EngineHistoryCache.runner_id == rid, models.EngineHistoryCache.kind != "quadrant")
       .delete(synchronize_session=False))


def cached_history(db: DBSession, rid: str, kind: str, builder):
    """Whole-payload cache for the weekly histories (mech, engine compare): valid
    while it matches the key and was computed today, else rebuilt once."""
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    key = history_key(r.engine_mode if r else None)
    today = E.iso_date(E.today_date())
    row = _cache_row(db, rid, kind)
    if row and row.engine_version == key and row.computed_for == today and row.payload_json is not None:
        return row.payload_json
    payload = builder()
    store_cache(db, rid, kind, key, today, payload)
    return payload
