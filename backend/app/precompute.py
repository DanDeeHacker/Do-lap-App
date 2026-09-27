"""Background precompute of per-runner derived data, so screens never wait on it.

One worker thread drains a priority queue of runner ids. A job brings the
runner's stored assessment up to date for today (engine.get_or_refresh_assessment)
and incrementally refreshes the daily quadrant history (app.history). Jobs are
queued by

* engine.recompute_assessment after any data change (priority 0),
* a history read that finds the cache dirty (priority 0, the reader waits),
* the warm-up at startup and just after local midnight for every recently
  active runner (priority 5), so the first open of a new day is instant.

A runner has at most one job pending or running. A data change that arrives
while its job runs makes the job loop once more before it reports done, so a
waiting reader never gets a history built from data older than its request.
Disabled with DOSSLAP_PRECOMPUTE=0 (the test suite does this and builds inline).
"""
import itertools
import logging
import os
import queue
import threading

log = logging.getLogger("dosslap.precompute")

PRIO_NOW = 0
PRIO_WARM = 5


def enabled() -> bool:
    return os.environ.get("DOSSLAP_PRECOMPUTE", "1") != "0"


class _Job:
    __slots__ = ("rid", "prio", "running", "again", "done")

    def __init__(self, rid: str, prio: int):
        self.rid, self.prio = rid, prio
        self.running = False
        self.again = False
        self.done = threading.Event()


_lock = threading.Lock()
_jobs: dict[str, _Job] = {}
_q: "queue.PriorityQueue[tuple[int, int, _Job]]" = queue.PriorityQueue()
_seq = itertools.count()
_worker: threading.Thread | None = None


def schedule(rid: str, prio: int = PRIO_NOW) -> _Job | None:
    """Queue a refresh for `rid` (deduplicated). Returns the job, or None when
    precompute is disabled."""
    global _worker
    if not enabled() or not rid:
        return None
    with _lock:
        j = _jobs.get(rid)
        if j is not None:
            if j.running:
                j.again = True          # inputs changed mid-run: one more pass
            elif prio < j.prio:         # still queued: move it up (stale entry is skipped)
                j.prio = prio
                _q.put((prio, next(_seq), j))
            return j
        j = _Job(rid, prio)
        _jobs[rid] = j
        _q.put((prio, next(_seq), j))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="dosslap-precompute", daemon=True)
            _worker.start()
        return j


def wait(rid: str, timeout: float) -> bool:
    """Block until `rid` has no pending/running job (True) or the timeout passes."""
    with _lock:
        j = _jobs.get(rid)
    return True if j is None else j.done.wait(timeout)


def pending(rid: str) -> bool:
    with _lock:
        return rid in _jobs


def _run(rid: str) -> None:
    from .db import SessionLocal
    from .history import refresh_quadrant_history
    from .metrics import engine as E
    db = SessionLocal()
    try:
        E.get_or_refresh_assessment(db, rid)
        st = refresh_quadrant_history(db, rid)
        log.info("precomputed %s: %d days (%d replayed)", rid, len(st["rows"]), st["replayed"])
    finally:
        db.close()


def _loop() -> None:
    while True:
        _prio, _n, j = _q.get()
        with _lock:
            if j.running or j.done.is_set() or _jobs.get(j.rid) is not j:
                continue  # duplicate entry left behind by a priority bump
            j.running = True
        while True:
            with _lock:
                j.again = False
            try:
                _run(j.rid)
            except Exception:  # noqa: BLE001, a failed job must never kill the worker
                log.exception("precompute failed for %s", j.rid)
            with _lock:
                if not j.again:
                    _jobs.pop(j.rid, None)
                    j.done.set()
                    break


def active_runner_ids(days: int = 90) -> list[str]:
    """Runners with an activity, check-in or daily metric in the last `days`."""
    from .db import SessionLocal
    from . import models
    from .metrics import engine as E
    since = E.day_ago(days)
    db = SessionLocal()
    try:
        ids = {r for (r,) in db.query(models.Activity.runner_id).filter(models.Activity.started_at >= since).distinct()}
        ids |= {r for (r,) in db.query(models.Checkin.runner_id).filter(models.Checkin.submitted_at >= since).distinct()}
        ids |= {r for (r,) in db.query(models.DailyMetric.runner_id).filter(models.DailyMetric.date >= since[:10]).distinct()}
        return sorted(i for i in ids if i)
    finally:
        db.close()


def warm_all() -> int:
    """Queue a low-priority refresh for every recently active runner."""
    if not enabled():
        return 0
    ids = active_runner_ids()
    for rid in ids:
        schedule(rid, PRIO_WARM)
    return len(ids)
