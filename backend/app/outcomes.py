"""Plan phase 0: prospective daily record of the engine's output and the health
events it will be calibrated against.

* `record_snapshot` stores what the engine said about a runner today (axes,
  quadrant, the continuous inputs behind them) and logs an `EngineAlert` when a
  load or mechanics axis newly turns elevated. The precompute worker calls it
  once a day per active runner, so it never runs on a user's request.
* `health_events` derives the outcome events from what runners report. The
  definition is the product team's working proposal (to be reviewed by a
  physiotherapist before calibration): a new ad-hoc or physio-written injury
  report, an OSTRC answer with reduced participation or volume, or pain of at
  least 3/10 at the same running-relevant site in two reports within 7 days.
  Events of one runner closer than EPISODE_GAP days merge into one episode.
* `overview` is the internal progress report towards the calibration gate
  (Bache-Mathiesen et al., 2021, cite > 200 injuries as the minimum to detect a
  small to moderate effect).
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import engine as E

PAIN_MIN = 3            # pain level that counts towards an event
PAIN_PAIR_DAYS = 7      # two painful reports at one site within this many days
EPISODE_GAP = 14        # events closer than this belong to one episode
OUTCOME_WINDOW = 7      # a snapshot's outcome = an event within the next 7 days (proposal)
GATE_EVENTS = 200       # calibration gate
GATE_MAX_SHARE = 0.05   # no runner may contribute more than 5 % of the events (proposal)
MECH_FEATURES = ("tavr", "gct", "cadence", "vosc")


def features_of(a: dict) -> dict:
    """The continuous inputs behind today's points, for the calibration model."""
    f = {}
    for k in MECH_FEATURES:
        v = a.get(k)
        if isinstance(v, dict) and v.get("z") is not None:
            f[f"{k}_z"] = v["z"]
    bal = a.get("bal")
    if isinstance(bal, dict) and bal.get("excursion") is not None:
        f["bal_exc"] = bal["excursion"]
    cap = a.get("capacity") or {}
    for ch, v in (cap.get("channels") or {}).items():
        if isinstance(v, dict) and v.get("known") and v.get("raw") is not None and v.get("ceilingToday"):
            f[f"cap_{ch}_ratio"] = round(v["raw"] / v["ceilingToday"], 3)
    rd = cap.get("readiness") or {}
    if rd.get("score") is not None:
        f["readiness"] = rd["score"]
    L = a.get("loadDetail") or {}
    for k in ("ratio", "sessionSpike", "monotony"):
        if L.get(k) is not None:
            f[f"load_{k}"] = L[k]
    rcv = a.get("rcv") or {}
    for k in ("hrv", "rhr"):
        z = (rcv.get(k) or {}).get("z") if isinstance(rcv.get(k), dict) else None
        if z is not None:
            f[f"{k}_z"] = z
    return f


def _hot(quadrant: str | None) -> set:
    return {"overreaching": {"load"}, "silent": {"mech"}, "critical": {"load", "mech"}}.get(quadrant or "", set())


def record_snapshot(db: DBSession, rid: str, a: dict) -> models.EngineDailySnapshot:
    """Upsert today's snapshot from an assessment dict and log newly hot axes."""
    from .history import CODE_FP
    today = E.iso_date(E.today_date())
    row = (db.query(models.EngineDailySnapshot)
             .filter(models.EngineDailySnapshot.runner_id == rid, models.EngineDailySnapshot.date == today).first())
    prev = (db.query(models.EngineDailySnapshot)
              .filter(models.EngineDailySnapshot.runner_id == rid, models.EngineDailySnapshot.date < today)
              .order_by(models.EngineDailySnapshot.date.desc()).first())
    if row is None:
        row = models.EngineDailySnapshot(runner_id=rid, date=today)
        db.add(row)
    row.engine_version, row.code_fp = a.get("engine"), CODE_FP
    row.mech, row.load, row.symp, row.overall = a.get("mech"), a.get("load"), a.get("symp"), a.get("overall")
    row.quadrant, row.tier = a.get("quadrant"), a.get("tier")
    row.confidence = (a.get("confidence") or {}).get("value")
    row.features_json = features_of(a)
    row.signals_json = [{"id": s.get("id"), "pts": s.get("pts"), "val": s.get("val")} for s in (a.get("signals") or [])]
    row.created_at = E.now_iso()
    if prev is not None:
        for axis in sorted(_hot(row.quadrant) - _hot(prev.quadrant)):
            exists = (db.query(models.EngineAlert)
                        .filter(models.EngineAlert.runner_id == rid, models.EngineAlert.date == today,
                                models.EngineAlert.axis == axis).first())
            if not exists:
                db.add(models.EngineAlert(runner_id=rid, date=today, axis=axis,
                                          quadrant_from=prev.quadrant, quadrant_to=row.quadrant))
    db.commit()
    return row


def _site(region: str | None, side: str | None = None) -> str | None:
    r = E._norm_region((region or "").strip())
    if not r or not E._run_relevant(r):
        return None
    base = str(r).split(" (")[0].strip().lower()
    s = side or (str(r)[-2] if str(r).endswith(")") and " (" in str(r) else None)
    return f"{base}|{s or ''}"


def _pain_reports(db: DBSession, rid: str):
    """(date, site, level) for every painful report of a running-relevant site."""
    out = []
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid):
        pts = c.pain_points or []
        if pts:
            for p in pts:
                lvl = p.get("severity", c.pain_score)
                if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                    out.append((c.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
        elif (c.pain_score or 0) >= PAIN_MIN and _site(c.pain_site):
            out.append((c.submitted_at[:10], _site(c.pain_site), c.pain_score))
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid):
        pts = f.pain_points or []
        if pts:
            for p in pts:
                lvl = p.get("severity", f.pain_during)
                if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                    out.append((f.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
        elif (f.pain_during or 0) >= PAIN_MIN and _site(f.pain_site):
            out.append((f.submitted_at[:10], _site(f.pain_site), f.pain_during))
    for r in db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid):
        for p in (r.pain_points or []):
            lvl = p.get("severity")
            if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                out.append((r.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
    return sorted(out)


def health_events(db: DBSession, rid: str) -> list[dict]:
    """Episode starts [{date, source, site?}], ascending (see the module docstring)."""
    raw = []
    for r in db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid):
        if r.status == "none":
            continue
        if r.source in ("self_adhoc", "physio_conclusion"):
            raw.append({"date": r.submitted_at[:10], "source": r.source, "site": r.body_region})
        elif (r.q_participation or 0) > 0 or (r.q_volume or 0) > 0:
            raw.append({"date": r.submitted_at[:10], "source": "ostrc_limit", "site": r.body_region})
    by_site: dict[str, list[str]] = {}
    for d, site, _lvl in _pain_reports(db, rid):
        by_site.setdefault(site, []).append(d)
    for site, days in by_site.items():
        days = sorted(set(days))
        for i in range(1, len(days)):
            if (date.fromisoformat(days[i]) - date.fromisoformat(days[i - 1])).days <= PAIN_PAIR_DAYS:
                raw.append({"date": days[i], "source": "pain_repeat", "site": site.split("|")[0]})
    raw.sort(key=lambda e: e["date"])
    episodes, last = [], None
    for e in raw:
        if last is None or (date.fromisoformat(e["date"]) - date.fromisoformat(last)).days >= EPISODE_GAP:
            episodes.append(e)
        last = e["date"]
    return episodes


def labelled_snapshots(db: DBSession, rid: str) -> list[dict]:
    """Snapshots with their outcome: an episode start in the next OUTCOME_WINDOW days.
    Days inside an ongoing episode (up to EPISODE_GAP after its start) are left out,
    since the runner is already injured then."""
    events = [date.fromisoformat(e["date"]) for e in health_events(db, rid)]
    out = []
    for s in (db.query(models.EngineDailySnapshot).filter(models.EngineDailySnapshot.runner_id == rid)
                .order_by(models.EngineDailySnapshot.date)):
        d = date.fromisoformat(s.date)
        if any(0 <= (d - e).days < EPISODE_GAP for e in events):
            continue
        y = any(0 < (e - d).days <= OUTCOME_WINDOW for e in events)
        out.append({"runner_id": rid, "date": s.date, "event": y, "mech": s.mech, "load": s.load,
                    "symp": s.symp, "overall": s.overall, **(s.features_json or {})})
    return out


def overview(db: DBSession) -> dict:
    """Progress towards the calibration gate, for the owner-only report."""
    rids = [r for (r,) in db.query(models.EngineDailySnapshot.runner_id).distinct()]
    per = {rid: len(health_events(db, rid)) for rid in rids}
    total = sum(per.values())
    snaps = db.query(models.EngineDailySnapshot).count()
    first = db.query(models.EngineDailySnapshot.date).order_by(models.EngineDailySnapshot.date).first()
    expected = 0
    for rid in rids:
        f0 = (db.query(models.EngineDailySnapshot.date).filter(models.EngineDailySnapshot.runner_id == rid)
                .order_by(models.EngineDailySnapshot.date).first())
        expected += (E.today_date() - date.fromisoformat(f0[0])).days + 1
    top_share = (max(per.values()) / total) if total else 0.0
    alerts = db.query(models.EngineAlert).count()
    rated = db.query(models.EngineAlert).filter(models.EngineAlert.feedback.isnot(None)).count()
    no_fit = db.query(models.EngineAlert).filter(models.EngineAlert.feedback == "no_fit").count()
    return {
        "runners": len(rids), "snapshots": snaps, "events": total,
        "missingShare": round(1 - snaps / expected, 3) if expected else None,
        "topRunnerShare": round(top_share, 3),
        "gate": {"events": GATE_EVENTS, "maxShare": GATE_MAX_SHARE,
                 "passed": total >= GATE_EVENTS and top_share <= GATE_MAX_SHARE},
        "alerts": {"total": alerts, "rated": rated, "noFit": no_fit},
        "since": first[0] if first else None,
    }


def recent_unrated_alert(db: DBSession, rid: str, days: int = 3):
    since = (E.today_date() - timedelta(days=days)).isoformat()
    return (db.query(models.EngineAlert)
              .filter(models.EngineAlert.runner_id == rid, models.EngineAlert.date >= since,
                      models.EngineAlert.feedback.is_(None))
              .order_by(models.EngineAlert.date.desc()).first())
