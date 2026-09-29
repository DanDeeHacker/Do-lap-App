"""Plan phase 0: prospective daily record of the engine's output and the health
events it will be calibrated against.

* `record_snapshot` stores what the engine said about a runner in the morning
  (axes, quadrant, the continuous inputs behind them, the model scores without the
  safety-rule floors, and the day's recommendation) and logs an `EngineAlert` when
  a load or mechanics axis newly turns elevated. v0.9.0: the snapshot is FROZEN
  once the runner has run that day — an assessment recomputed after the run
  already contains it, so it would predict an outcome from its own exposure. A
  snapshot first taken after a run is kept but marked `post_session`.
* `health_events` derives the outcome events. v0.9.0 separates them:
    primary   — defined independently of the engine's predictors: a self-reported
                ad-hoc injury, a physio conclusion, an OSTRC answer with a
                substantial problem (participation, volume or performance ≥ 17;
                Clarsen et al., 2013), and a time-loss event (a running-relevant
                pain ≥ 3/10 or injury report followed by ≥ 7 days without running,
                for a runner who averaged ≥ 2 runs a week in the 28 days before it,
                and who kept syncing through that week);
    secondary — the old proposal's extras: any OSTRC limitation and pain ≥ 3/10
                at the same running-relevant site in two reports within 7 days.
                Pain reports are themselves engine inputs (symptom axis), so an
                outcome built from them would partly predict itself; it is kept
                only as a secondary analysis.
  Events of one runner closer than EPISODE_GAP days merge into one episode.
* `labelled_snapshots` labels each at-risk day (discrete-time: `event1` = an
  episode starting the next day; `event` = within OUTCOME_WINDOW days) and
  CENSORS days whose follow-up window isn't covered by data yet (the last 7 days,
  or after the runner stopped syncing) instead of counting them as event-free.
* `session_rows` is the session-scale dataset (one row per run, outcome before the
  next run or within 7 days) — the scale of the Garmin-RUNSAFE analysis
  (Frandsen et al., 2025) — with the run's ratio to the longest run of the
  preceding 30 days.
* `overview` is the internal progress report towards the calibration gate
  (Bache-Mathiesen et al., 2021, cite > 200 injuries as the minimum to detect a
  small to moderate effect).
"""
from bisect import bisect_left
from datetime import date, timedelta

from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import data as D
from .metrics import engine as E

PAIN_MIN = 3            # pain level that counts towards an event
PAIN_PAIR_DAYS = 7      # two painful reports at one site within this many days
EPISODE_GAP = 14        # events closer than this belong to one episode
OUTCOME_WINDOW = 7      # a snapshot's outcome = an event within the next 7 days (proposal)
OSTRC_SUBSTANTIAL = 17  # OSTRC item ≥ 17 = moderate/severe reduction (Clarsen et al., 2013)
TIME_LOSS_DAYS = 7      # no run for this many days after a report = time loss
TIME_LOSS_MIN_RUNS = 8  # …for a runner with ≥ 2 runs a week in the 28 days before it
TIME_LOSS_PRESENT = 3   # …who synced nights or check-ins on ≥ 3 of those days (not just away)
SESSION_REF_DAYS = 30   # RUNSAFE: a run vs the longest run of the preceding 30 days
GATE_EVENTS = 200       # calibration gate
GATE_MAX_SHARE = 0.05   # no runner may contribute more than 5 % of the events (proposal)
MECH_FEATURES = ("tavr", "gct", "cadence", "vosc")
PRIMARY_SOURCES = ("self_adhoc", "physio_conclusion", "ostrc_substantial", "time_loss")


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
    rd = a.get("readiness") or cap.get("readiness") or {}
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
    # v0.9.0 — the scores the calibration sees: without the safety-rule floors
    for k, key in (("overallModel", "overall_model"), ("sympModel", "symp_model")):
        if a.get(k) is not None:
            f[key] = a[k]
    if a.get("ruleLevel"):
        f["rule"] = a["ruleLevel"]
    return f


def guidance_summary(a: dict) -> dict | None:
    """What the app recommended that day: the session type, the running-km ceiling
    and hard minutes, and the override (rest) if any — stored with the snapshot so
    the calibration can tell a recommendation that was followed from one that wasn't
    (a warning that works changes the behaviour it predicts)."""
    g = a.get("guidance") or {}
    if not g.get("type"):
        return None
    t = (g.get("types") or {}).get(g["type"]) or {}
    km = t.get("km") if isinstance(t.get("km"), dict) else {}
    ov = g.get("override")
    return {"type": g["type"], "override": ov.get("kind") if isinstance(ov, dict) else ov,
            "kmHi": km.get("hi"), "kmMax": km.get("max"), "z4Max": t.get("z4Max"),
            "provisional": bool(g.get("provisional"))}


ADHERENCE_SLACK = 1.10    # up to 10 % over the recommended kilometres still counts as followed


def adherence(guid: dict | None, runs_km: list[float]) -> str | None:
    """followed / exceeded / less / rested / ran_on_rest for one day."""
    if not guid:
        return None
    km = sum(runs_km)
    rest = guid.get("type") == "volno" or bool(guid.get("override"))
    if rest:
        return "rested" if not runs_km else "ran_on_rest"
    if guid.get("type") in ("kolo", "voda", "posilování"):
        return "followed" if not runs_km else "exceeded"
    if not runs_km:
        return "less"
    hi = guid.get("kmHi")
    if hi is None:
        return "followed"
    return "followed" if km <= hi * ADHERENCE_SLACK else "exceeded"


def _hot(quadrant: str | None) -> set:
    return {"overreaching": {"load"}, "silent": {"mech"}, "critical": {"load", "mech"}}.get(quadrant or "", set())


def _ran_today(db: DBSession, rid: str, today: str) -> bool:
    return db.query(models.Activity.id).filter(
        models.Activity.runner_id == rid, models.Activity.started_at >= today,
        models.Activity.started_at < E.iso_date(date.fromisoformat(today) + timedelta(days=1))).first() is not None


def record_snapshot(db: DBSession, rid: str, a: dict) -> models.EngineDailySnapshot:
    """Upsert today's snapshot from an assessment dict and log newly hot axes. The
    morning snapshot is frozen once a run of that day exists (see the docstring)."""
    from .history import CODE_FP
    today = E.iso_date(E.today_date())
    row = (db.query(models.EngineDailySnapshot)
             .filter(models.EngineDailySnapshot.runner_id == rid, models.EngineDailySnapshot.date == today).first())
    ran = _ran_today(db, rid, today)
    if row is not None and ran:
        return row                               # frozen: the pre-run state stays what was recorded
    prev = (db.query(models.EngineDailySnapshot)
              .filter(models.EngineDailySnapshot.runner_id == rid, models.EngineDailySnapshot.date < today)
              .order_by(models.EngineDailySnapshot.date.desc()).first())
    if row is None:
        row = models.EngineDailySnapshot(runner_id=rid, date=today)
        db.add(row)
    row.post_session = ran
    row.engine_version, row.code_fp = a.get("engine"), CODE_FP
    row.mech, row.load, row.symp, row.overall = a.get("mech"), a.get("load"), a.get("symp"), a.get("overall")
    row.quadrant, row.tier = a.get("quadrant"), a.get("tier")
    row.confidence = (a.get("confidence") or {}).get("value")
    row.features_json = features_of(a)
    row.guidance_json = guidance_summary(a)
    row.signals_json = [{"id": s.get("id"), "pts": s.get("pts"), "val": s.get("val"), **({"rule": s["rule"]} if s.get("rule") else {})}
                        for s in (a.get("signals") or [])]
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


def _data(db, rid) -> D.RunnerData:
    return db if D.is_data(db) else D.load_runner_data(db, rid, priors=False)


def _pain_reports(db, rid: str):
    """(date, site, level) for every painful report of a running-relevant site."""
    data = _data(db, rid)
    out = []
    for c in data.checkins:
        pts = c.pain_points or []
        if pts:
            for p in pts:
                lvl = p.get("severity", c.pain_score)
                if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                    out.append((c.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
        elif (c.pain_score or 0) >= PAIN_MIN and _site(c.pain_site):
            out.append((c.submitted_at[:10], _site(c.pain_site), c.pain_score))
    for f in data.feedback:
        pts = f.pain_points or []
        if pts:
            for p in pts:
                lvl = p.get("severity", f.pain_during)
                if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                    out.append((f.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
        elif (f.pain_during or 0) >= PAIN_MIN and _site(f.pain_site):
            out.append((f.submitted_at[:10], _site(f.pain_site), f.pain_during))
    for r in data.injuries:
        for p in (r.pain_points or []):
            lvl = p.get("severity")
            if (lvl or 0) >= PAIN_MIN and _site(p.get("region"), p.get("side")):
                out.append((r.submitted_at[:10], _site(p.get("region"), p.get("side")), lvl))
    return sorted(out)


def _run_days(data) -> list[str]:
    return sorted({a.started_at[:10] for a in data.activities if E.is_run(a) and E.counts_for(a, "load")})


def _present_days(data) -> set:
    """Days with any synced trace of the runner (nights, check-ins, ratings, activities)."""
    return ({m.date[:10] for m in data.daily} | {c.submitted_at[:10] for c in data.checkins}
            | {f.submitted_at[:10] for f in data.feedback} | {a.started_at[:10] for a in data.activities})


def followup_end(data) -> date:
    """The last day this runner's outcomes are observed: today, or earlier when the
    runner stopped syncing (their last trace of any kind)."""
    seen = _present_days(data) | {r.submitted_at[:10] for r in data.injuries}
    last = max(seen) if seen else None
    today = E.today_date()
    return min(today, date.fromisoformat(last)) if last else today


def time_loss_events(db, rid: str) -> list[dict]:
    """A running-relevant pain ≥ PAIN_MIN or injury report followed by ≥ 7 days
    without running, for a regular runner who kept syncing through that week."""
    data = _data(db, rid)
    runs = _run_days(data)
    present = _present_days(data)
    today = E.today_date()
    starts = {d for d, _s, _l in _pain_reports(data, rid)}
    starts |= {r.submitted_at[:10] for r in data.injuries if r.status != "none" and r.source != "self_weekly"}
    out = []
    for d in sorted(starts):
        d0 = date.fromisoformat(d)
        end = d0 + timedelta(days=TIME_LOSS_DAYS)
        if end > today:
            continue                                        # the week after isn't over yet
        lo, hi = (d0 - timedelta(days=28)).isoformat(), d
        before = bisect_left(runs, hi) - bisect_left(runs, lo)
        if before < TIME_LOSS_MIN_RUNS:
            continue
        gap = [(d0 + timedelta(days=k)).isoformat() for k in range(1, TIME_LOSS_DAYS + 1)]
        if any(x in runs for x in gap):
            continue
        if sum(x in present for x in gap) < TIME_LOSS_PRESENT:
            continue                                        # not synced — away, not necessarily injured
        out.append({"date": d, "source": "time_loss", "site": None})
    return out


def _episodes(raw: list[dict]) -> list[dict]:
    raw = sorted(raw, key=lambda e: e["date"])
    episodes, last = [], None
    for e in raw:
        if last is None or (date.fromisoformat(e["date"]) - date.fromisoformat(last)).days >= EPISODE_GAP:
            episodes.append(e)
        last = e["date"]
    return episodes


def ostrc_substantial(r) -> bool:
    return max(r.q_participation or 0, r.q_volume or 0, r.q_performance or 0) >= OSTRC_SUBSTANTIAL


def health_events(db, rid: str, outcome: str = "primary") -> list[dict]:
    """Episode starts [{date, source, site?}], ascending. outcome = "primary" or
    "secondary" (primary + the predictor-dependent extras; see the module docstring)."""
    data = _data(db, rid)
    raw = []
    for r in data.injuries:
        if r.status == "none":
            continue
        if r.source in ("self_adhoc", "physio_conclusion"):
            raw.append({"date": r.submitted_at[:10], "source": r.source, "site": r.body_region})
        elif ostrc_substantial(r):
            raw.append({"date": r.submitted_at[:10], "source": "ostrc_substantial", "site": r.body_region})
        elif outcome == "secondary" and ((r.q_participation or 0) > 0 or (r.q_volume or 0) > 0):
            raw.append({"date": r.submitted_at[:10], "source": "ostrc_limit", "site": r.body_region})
    raw += time_loss_events(data, rid)
    if outcome == "secondary":
        by_site: dict[str, list[str]] = {}
        for d, site, _lvl in _pain_reports(data, rid):
            by_site.setdefault(site, []).append(d)
        for site, days in by_site.items():
            days = sorted(set(days))
            for i in range(1, len(days)):
                if (date.fromisoformat(days[i]) - date.fromisoformat(days[i - 1])).days <= PAIN_PAIR_DAYS:
                    raw.append({"date": days[i], "source": "pain_repeat", "site": site.split("|")[0]})
    return _episodes(raw)


def _label(d: date, events: list[date]) -> dict | None:
    """None inside an ongoing episode (the runner is already injured then)."""
    if any(0 <= (d - e).days < EPISODE_GAP for e in events):
        return None
    return {"event": any(0 < (e - d).days <= OUTCOME_WINDOW for e in events),
            "event1": any((e - d).days == 1 for e in events)}


def labelled_snapshots(db: DBSession, rid: str) -> list[dict]:
    """Snapshots with their outcome (primary: `event` within OUTCOME_WINDOW days,
    `event1` the next day; secondary: `event2`) and the day's adherence. Days inside
    an ongoing episode are left out; days whose follow-up isn't observed are censored."""
    data = _data(db, rid)
    prim = [date.fromisoformat(e["date"]) for e in health_events(data, rid)]
    sec = [date.fromisoformat(e["date"]) for e in health_events(data, rid, "secondary")]
    fend = followup_end(data)
    km_by_day: dict[str, list[float]] = {}
    for a in data.activities:
        if E.is_run(a):
            km_by_day.setdefault(a.started_at[:10], []).append(a.distance_km or 0.0)
    out = []
    for s in (db.query(models.EngineDailySnapshot).filter(models.EngineDailySnapshot.runner_id == rid)
                .order_by(models.EngineDailySnapshot.date)):
        d = date.fromisoformat(s.date)
        lab = _label(d, prim)
        if lab is None:
            continue
        if not lab["event"] and d + timedelta(days=OUTCOME_WINDOW) > fend:
            continue                                         # censored: the week after isn't observed
        lab2 = _label(d, sec)
        f = s.features_json or {}
        out.append({"runner_id": rid, "date": s.date, **lab, "event2": bool(lab2 and lab2["event"]),
                    "mech": s.mech, "load": s.load, "symp": f.get("symp_model", s.symp),
                    "overall": f.get("overall_model", s.overall), "overall_shown": s.overall,
                    "post_session": bool(getattr(s, "post_session", False)),
                    "adherence": adherence(getattr(s, "guidance_json", None), km_by_day.get(s.date, [])),
                    **{k: v for k, v in f.items() if k not in ("overall_model", "symp_model")}})
    return out


def session_rows(db: DBSession, rid: str) -> list[dict]:
    """One row per run day: the RUNSAFE exposure (the day's longest run over the
    longest run of the preceding 30 days) and whether a primary event followed
    before the next run day (at most 7 days) — a discrete-time hazard on the session
    scale. The morning snapshot's features are attached when one was recorded
    before the run. Runs without a 30-day reference, inside an episode or with an
    unobserved interval are left out."""
    data = _data(db, rid)
    prim = [date.fromisoformat(e["date"]) for e in health_events(data, rid)]
    fend = followup_end(data)
    by_day: dict[str, float] = {}
    for a in data.activities:
        if E.is_run(a) and E.counts_for(a, "load") and (a.distance_km or 0) > 0:
            k = a.started_at[:10]
            by_day[k] = max(by_day.get(k, 0.0), a.distance_km)
    days = sorted(by_day)
    snaps = {s.date: s for s in db.query(models.EngineDailySnapshot).filter(models.EngineDailySnapshot.runner_id == rid)}
    out = []
    for i, k in enumerate(days):
        d = date.fromisoformat(k)
        ref_lo = (d - timedelta(days=SESSION_REF_DAYS)).isoformat()
        ref = [by_day[x] for x in days[bisect_left(days, ref_lo):i]]
        if not ref or any(0 <= (d - e).days < EPISODE_GAP for e in prim):
            continue
        nxt = date.fromisoformat(days[i + 1]) if i + 1 < len(days) else None
        end = min(nxt, d + timedelta(days=OUTCOME_WINDOW)) if nxt else d + timedelta(days=OUTCOME_WINDOW)
        event = any(d < e <= end for e in prim)
        if not event and end > fend:
            continue
        row = {"runner_id": rid, "date": k, "event": event, "km": round(by_day[k], 2),
               "session_ratio": round(by_day[k] / max(ref), 3), "interval_days": (end - d).days}
        s = snaps.get(k)
        if s is not None and not getattr(s, "post_session", False):
            row.update({kk: v for kk, v in (s.features_json or {}).items() if isinstance(v, (int, float))})
        out.append(row)
    return out


def overview(db: DBSession) -> dict:
    """Progress towards the calibration gate, for the owner-only report."""
    rids = [r for (r,) in db.query(models.EngineDailySnapshot.runner_id).distinct()]
    ev = {rid: health_events(db, rid) for rid in rids}
    per = {rid: len(x) for rid, x in ev.items()}
    total = sum(per.values())
    by_source: dict[str, int] = {}
    for x in ev.values():
        for e in x:
            by_source[e["source"]] = by_source.get(e["source"], 0) + 1
    secondary = sum(len(health_events(db, rid, "secondary")) for rid in rids)
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
        "runners": len(rids), "snapshots": snaps, "events": total, "eventsBySource": by_source,
        "eventsSecondary": secondary,
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
