"""RunnerData: one immutable snapshot of everything the engine reads for a runner.

The engine (engine.assess, capacity.assess_capacity, guidance.build_guidance) is a
pure function of this snapshot, the engine day and the engine mode. The database is
read once, by load_runner_data(); every engine helper then filters these plain lists
instead of issuing its own query (an assessment used to run ~70 queries, 18 of them
loading the full activity table).

History replays no longer rebuild a throwaway database for every replay: they take
`data.as_of(day)`, the rows that were known on that day, and assess that.

Engine helpers accept either a RunnerData or a database session (`of(src, rid)`), so
routers and tests that call them with a session keep working; with a session the
snapshot is loaded on the spot.
"""
from dataclasses import dataclass, replace
from functools import cached_property
from types import SimpleNamespace

from .. import models


def _day(s) -> str:
    return (s or "")[:10]


def _copy(row, cols) -> SimpleNamespace:
    return SimpleNamespace(**{c: getattr(row, c) for c in cols})


def _cols(model) -> list[str]:
    return [c.key for c in model.__mapper__.column_attrs]


@dataclass(frozen=True)
class RunnerData:
    """Rows of one runner. Every table keeps its natural (id) order, except the
    activities, which are ordered by (started_at, id) like every engine query."""
    rid: str
    runner: SimpleNamespace | None
    activities: tuple = ()      # all activities, the excluded ones too (counts_for decides)
    feedback: tuple = ()        # ActivityFeedback
    checkins: tuple = ()
    daily: tuple = ()           # DailyMetric, by date
    injuries: tuple = ()        # InjuryReport
    devices: tuple = ()         # DeviceHistory, by recorded_at
    streams: tuple = ()         # ActivityStream
    races: tuple = ()
    rtr_plans: tuple = ()       # ReturnToRun
    shoes: tuple = ()           # Shoe (v0.12.0)
    tendon_checks: tuple = ()   # TendonCheck (morning tendon load tests, suggestion #7)
    prev_quadrant: str | None = None
    priors: dict | None = None  # population priors (reference.py), fixed for the snapshot

    # ---------------------------------------------------------------- lookups
    @cached_property
    def act_by_id(self) -> dict:
        return {a.id: a for a in self.activities}

    @cached_property
    def daily_by_date(self) -> dict:
        return {m.date[:10]: m for m in self.daily}

    def run_day(self, feedback_row) -> str | None:
        """The date of the run a rating belongs to (the join the engine used)."""
        a = self.act_by_id.get(feedback_row.activity_id)
        return a.started_at if a is not None else None

    # ---------------------------------------------------------------- replay
    def as_of(self, cut: str, prev_quadrant: str | None = None) -> "RunnerData":
        """The rows known on day `cut` (ISO date): activities, streams, nights and
        devices by their date, check-ins / ratings / injury reports by when they were
        submitted. The profile and the race calendar (a plan, known from the start)
        stay as they are. `prev_quadrant` seeds the hysteresis of that day."""
        acts = tuple(a for a in self.activities if _day(a.started_at) <= cut)
        ids = {a.id for a in acts}
        return replace(
            self,
            activities=acts,
            streams=tuple(s for s in self.streams if s.activity_id in ids),
            daily=tuple(m for m in self.daily if _day(m.date) <= cut),
            devices=tuple(d for d in self.devices if _day(d.recorded_at) <= cut),
            checkins=tuple(c for c in self.checkins if _day(c.submitted_at) <= cut),
            feedback=tuple(f for f in self.feedback if _day(f.submitted_at) <= cut and f.activity_id in ids),
            injuries=tuple(r for r in self.injuries if _day(r.submitted_at) <= cut),
            rtr_plans=tuple(p for p in self.rtr_plans if _day(p.created_at or p.started_on) <= cut),
            shoes=tuple(s for s in self.shoes if _day(s.first_used or s.created_at) <= cut),
            tendon_checks=tuple(t for t in self.tendon_checks if _day(t.date) <= cut),
            prev_quadrant=prev_quadrant,
        )


def _load(db, model, rid, *order):
    cols = _cols(model)
    q = db.query(model).filter(model.runner_id == rid)
    if order:
        q = q.order_by(*order)
    return tuple(_copy(r, cols) for r in q.all())


def load_priors(runner) -> dict:
    """This week's population priors (None entries until enough runners)."""
    from . import reference as REF
    device = getattr(runner, "device", None) if runner is not None else None
    mech = {}
    for f in (*REF.MECH_FIELDS, "stride_len_m"):      # every raw field the drift core asks priors for
        mech[(f, None)] = REF.mech_priors(field=f)
        if device:
            mech[(f, device)] = REF.mech_priors(field=f, device=device)
    return {"rec": {f: REF.recovery_priors(field=f) for f in REF.RECOVERY_FIELDS}, "mech": mech}


def load_runner_data(db, rid: str, priors: bool = True) -> RunnerData:
    """Read everything the engine needs for `rid` in one pass."""
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    runner = _copy(r, _cols(models.Runner)) if r is not None else None
    prev = db.query(models.Assessment.quadrant).filter(models.Assessment.runner_id == rid).first()
    A = models.Activity
    return RunnerData(
        rid=rid,
        runner=runner,
        activities=_load(db, A, rid, A.started_at.asc(), A.id.asc()),
        feedback=_load(db, models.ActivityFeedback, rid, models.ActivityFeedback.id.asc()),
        checkins=_load(db, models.Checkin, rid, models.Checkin.id.asc()),
        daily=_load(db, models.DailyMetric, rid, models.DailyMetric.date.asc(), models.DailyMetric.id.asc()),
        injuries=_load(db, models.InjuryReport, rid, models.InjuryReport.id.asc()),
        devices=_load(db, models.DeviceHistory, rid, models.DeviceHistory.recorded_at.asc(), models.DeviceHistory.id.asc()),
        streams=_load(db, models.ActivityStream, rid, models.ActivityStream.activity_id.asc()),
        races=_load(db, models.Race, rid, models.Race.id.asc()),
        rtr_plans=_load(db, models.ReturnToRun, rid, models.ReturnToRun.id.asc()),
        shoes=_load(db, models.Shoe, rid, models.Shoe.id.asc()),
        tendon_checks=_load(db, models.TendonCheck, rid, models.TendonCheck.date.asc(), models.TendonCheck.id.asc()),
        prev_quadrant=prev[0] if prev else None,
        priors=load_priors(runner) if priors else None,
    )


def of(src, rid: str) -> RunnerData:
    """The snapshot itself, or one loaded from a database session."""
    if isinstance(src, RunnerData):
        return src
    return load_runner_data(src, rid)


def is_data(src) -> bool:
    return isinstance(src, RunnerData)


def row_dict(x) -> dict:
    return dict(vars(x)) if isinstance(x, SimpleNamespace) else {c: getattr(x, c) for c in _cols(type(x))}


def stable_desc(rows, key):
    """Newest first by `key`; ties keep their (id) order, like the ORDER BY … DESC the
    engine used on SQLite."""
    return sorted(rows, key=key, reverse=True)
