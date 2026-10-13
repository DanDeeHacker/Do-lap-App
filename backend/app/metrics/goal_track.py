"""Plan k cíli 2.0 (owner decision 2026-10-13) — the goal's record week by week.

#8  Adherence: each Monday the plan's week is kept as it stood (goals.track_json["weeks"]); a
    completed week is compared with what was run: kilometres, the long run and the strength
    sessions. Under 80 % two weeks in a row → the plan has been recalculated, here is what it
    means for the date; over 115 % → a spike like any other (Damsted et al., 2019): don't add.
#7  Checkpoints: halfway through the plan, 8 and 4 weeks before the race the app checks where the
    runner stands. Behind → the best safe goal or a later date now; the rest of the plan is never
    squeezed to catch up.
#9  Setbacks: an illness day or 5+ days without running → no hard sessions for 7 days after the
    illness (3 days after a break), and the plan's real date before and after, so the runner sees
    what the setback cost. The return lengths are working assumptions."""
from datetime import date, timedelta

from . import data as D
from . import engine as E

UNDER, OVER = 0.80, 1.15
ILL_HOLD, BREAK_DAYS, BREAK_HOLD = 7, 5, 3
CHECKS = (("half", "polovina plánu"), ("w8", "8 týdnů před závodem"), ("w4", "4 týdny před závodem"))


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def snapshot(g_row, gg: dict | None, today: date) -> bool:
    """Keep this week's plan and answer as they stand on the first computation of the week.
    Returns True when the record changed."""
    if g_row is None or not gg or not gg.get("week"):
        return False
    ws = _monday(today).isoformat()
    tr = dict(g_row.track_json or {})
    weeks = dict(tr.get("weeks") or {})
    changed = False
    if ws not in weeks:
        w = gg["week"]
        weeks[ws] = {"km": w.get("km"), "long": w.get("long"), "strength": w.get("strength"), "deload": bool(w.get("deload")),
                     "fuel": w.get("fuel"),
                     "taper": bool(w.get("taper")), "realDate": gg.get("realDate"), "status": gg.get("status")}
        tr["weeks"] = weeks
        changed = True
    if gg.get("ill"):
        if tr.get("illLast") != today.isoformat():
            tr["illLast"] = today.isoformat()
            changed = True
    if changed:
        g_row.track_json = tr
    return changed


def _done(db, rid: str, start: date) -> dict:
    """What was run in the week from `start`: km, the longest run, strength sessions."""
    end = start + timedelta(days=7)
    km = longest = 0.0
    strength = 0
    for a in D.of(db, rid).activities:
        if not a.started_at or not E.counts_for(a, "load"):
            continue
        d = a.started_at[:10]
        if not (start.isoformat() <= d < end.isoformat()):
            continue
        if E.is_run(a):
            km += a.distance_km or 0.0
            longest = max(longest, a.distance_km or 0.0)
        elif a.sport == "strength":
            strength += 1
    return {"km": round(km, 1), "long": round(longest, 1), "strength": strength}


def adherence(db, rid: str, g_row, today: date, n: int = 4) -> dict | None:
    """The last n completed weeks of the plan against what was run, and a flag."""
    weeks = ((g_row.track_json or {}) if g_row is not None else {}).get("weeks") or {}
    ws = _monday(today)
    rows = []
    for k in range(n, 0, -1):
        s = ws - timedelta(days=7 * k)
        p = weeks.get(s.isoformat())
        if not p or not p.get("km"):
            continue
        d = _done(db, rid, s)
        rows.append({"start": s.isoformat(), "planKm": p["km"], "km": d["km"], "pct": round(100 * d["km"] / p["km"]),
                     "planLong": p.get("long"), "long": d["long"], "planStrength": p.get("strength"), "strength": d["strength"],
                     "deload": p.get("deload")})
    if not rows:
        return None
    flag = text = None
    last2 = rows[-2:]
    if len(last2) == 2 and all(r["pct"] < UNDER * 100 for r in last2):
        flag, text = "under", "Dva týdny pod 80 % plánu. Plán se přepočítal z toho, co jste opravdu odběhli."
    elif rows[-1]["pct"] > OVER * 100 and not rows[-1]["deload"]:
        flag, text = "over", f"Minulý týden {rows[-1]['pct']} % plánu. Víc nepřidávejte: přeplnění je skok jako každý jiný."
    plan_s = sum(r["planStrength"] or 0 for r in rows)
    return {"weeks": rows, "flag": flag, "text": text,
            "strengthPct": round(100 * min(sum(r["strength"] for r in rows), plan_s) / plan_s) if plan_s else None}


def checkpoint(g_row, res: dict, today: date) -> dict | None:
    """The checkpoint due today and not yet answered: {key, label, behind}."""
    if g_row is None or not res or not g_row.created_at:
        return None
    try:
        c0 = _monday(date.fromisoformat(g_row.created_at[:10]))
        race = _monday(date.fromisoformat(g_row.date[:10]))
    except ValueError:
        return None
    total = (race - c0).days // 7
    at = {"half": c0 + timedelta(days=7 * (total // 2)), "w8": race - timedelta(days=56), "w4": race - timedelta(days=28)}
    done = (g_row.track_json or {}).get("checkpoints") or {}
    due = [(k, lab) for k, lab in CHECKS if at[k] > c0 and at[k] <= today and k not in done and (today - at[k]).days < 14]
    if not due:
        return None
    k, lab = due[-1]
    behind = (res.get("status") or res.get("verdict")) not in ("ok",)
    return {"key": k, "label": lab, "behind": behind}


def answer_checkpoint(g_row, key: str, today: date) -> None:
    tr = dict(g_row.track_json or {})
    cps = dict(tr.get("checkpoints") or {})
    cps[key] = today.isoformat()
    tr["checkpoints"] = cps
    g_row.track_json = tr


def returning(g_row, run_dates: list, today: date) -> dict | None:
    """Back after a setback: {why, until} while hard sessions wait (7 days after an illness day,
    3 days after 5+ days without running)."""
    ill = ((g_row.track_json or {}) if g_row is not None else {}).get("illLast")
    if ill:
        until = date.fromisoformat(ill) + timedelta(days=ILL_HOLD)
        if today <= until:
            return {"why": "nemoc", "until": until.isoformat()}
    ds = sorted({d for d in run_dates if d <= today.isoformat()})
    if ds:
        last = date.fromisoformat(ds[-1])
        if (today - last).days >= BREAK_DAYS:
            return {"why": "pauza", "until": (today + timedelta(days=BREAK_HOLD)).isoformat()}
        for i in range(len(ds) - 1, 0, -1):
            a, b = date.fromisoformat(ds[i - 1]), date.fromisoformat(ds[i])
            if (today - b).days > BREAK_HOLD:
                break
            if (b - a).days >= BREAK_DAYS:
                return {"why": "pauza", "until": (b + timedelta(days=BREAK_HOLD)).isoformat()}
    return None


def setback(g_row, gg: dict | None, today: date) -> dict | None:
    """What a setback cost: the real date at the start of the week vs now, when it moved ≥ 5 days."""
    if g_row is None or not gg:
        return None
    w = ((g_row.track_json or {}).get("weeks") or {}).get(_monday(today).isoformat()) or {}
    old, new = w.get("realDate"), gg.get("realDate")
    if not old or not new:
        return None
    moved = (date.fromisoformat(new) - date.fromisoformat(old)).days
    return {"from": old, "to": new, "days": moved} if moved >= 5 else None


# #19 — the outcome of every goal (owner decision 2026-10-13): after the goal's date three
# questions (started, finished, the time) and, on their own, an injury with lost training during
# the preparation and how the plan was kept; the data backtesting and calibration (#20) need
OUTCOME_DAYS = 30           # the question waits this long after the date, then the goal is closed without it
LOST_TRAINING = 17          # OSTRC-H participation / volume item: reduced training or worse


def prep_summary(db, rid: str, g_row) -> dict:
    """What happened in the preparation: the plan kept (km and strength over the recorded weeks)
    and injuries with lost training (an OSTRC-H report with reduced training, a return-to-run plan)."""
    from .. import models
    weeks = (g_row.track_json or {}).get("weeks") or {}
    end = (g_row.date or "")[:10]
    plan_km = done_km = plan_s = done_s = 0.0
    for k, p in sorted(weeks.items()):
        if k >= end or not p.get("km"):
            continue
        d = _done(db, rid, date.fromisoformat(k))
        plan_km += p["km"]
        done_km += min(d["km"], p["km"] * OVER)
        plan_s += p.get("strength") or 0
        done_s += min(d["strength"], p.get("strength") or 0)
    start = (g_row.created_at or end)[:10]
    inj = (db.query(models.InjuryReport)
           .filter(models.InjuryReport.runner_id == rid, models.InjuryReport.submitted_at >= start,
                   models.InjuryReport.submitted_at <= end + "T23:59:59")
           .all())
    lost = [r for r in inj if (r.q_participation or 0) >= LOST_TRAINING or (r.q_volume or 0) >= LOST_TRAINING]
    rtr = (db.query(models.ReturnToRun)
           .filter(models.ReturnToRun.runner_id == rid, models.ReturnToRun.created_at >= start,
                   models.ReturnToRun.created_at <= end + "T23:59:59").count())
    return {"weeks": sum(1 for k in weeks if k < end), "kmPct": round(100 * done_km / plan_km) if plan_km else None,
            "strengthPct": round(100 * done_s / plan_s) if plan_s else None,
            "injury": bool(lost) or rtr > 0, "injurySites": sorted({r.body_region for r in lost if r.body_region})}


def outcome_due(g_row, today: date) -> bool:
    """The goal's date is behind (up to 30 days) and the runner hasn't answered yet."""
    if g_row is None or g_row.outcome_json or not g_row.date:
        return False
    try:
        d = date.fromisoformat(g_row.date[:10])
    except ValueError:
        return False
    return 0 < (today - d).days <= OUTCOME_DAYS


def record_outcome(db, rid: str, g_row, started: bool, finished: bool | None, time_s: int | None,
                   today: date, skipped: bool = False) -> dict:
    res = g_row.projection_json or {}
    out = {"at": today.isoformat(), "skipped": skipped, "started": None if skipped else started,
           "finished": None if skipped else (bool(finished) if started else False),
           "timeS": time_s if (started and finished) else None,
           # what the plan said, for the calibration (#20)
           "verdict": res.get("verdict"), "status": res.get("status"), "path": g_row.path, "realDate": res.get("realDate"),
           "targetTimeS": g_row.target_time_s, "predTimeS": ((res.get("targetTime") or {}).get("predictedS")),
           **prep_summary(db, rid, g_row)}
    g_row.outcome_json = out
    return out


# #15 — after a long run in the fuelling weeks one question: was digestion fine? A "no" lowers the
# next long run's intake note (Costa 2017, Miall 2018: two weeks of gut training cut the symptoms)
GI_DAYS, GI_MIN = 3, 90


def gi_ask(db, rid: str, g_row, today: date) -> dict | None:
    if g_row is None:
        return None
    tr = g_row.track_json or {}
    weeks, done = tr.get("weeks") or {}, tr.get("gi") or {}
    for a in reversed(D.of(db, rid).activities):
        if not a.started_at or not E.is_run(a) or not E.counts_for(a, "load"):
            continue
        d = date.fromisoformat(a.started_at[:10])
        if (today - d).days > GI_DAYS:
            break
        if d > today or (a.duration_min or 0) < GI_MIN or d.isoformat() in done:
            continue
        if (weeks.get(_monday(d).isoformat()) or {}).get("fuel"):
            return {"date": d.isoformat(), "km": round(a.distance_km or 0, 1), "min": round(a.duration_min or 0)}
    return None


def answer_gi(g_row, day: str, ok: bool) -> None:
    tr = dict(g_row.track_json or {})
    gi = dict(tr.get("gi") or {})
    gi[day] = bool(ok)
    tr["gi"], tr["giLast"] = gi, {"date": day, "ok": bool(ok)}
    g_row.track_json = tr


def rebase(g_row, res: dict, today: date) -> None:
    """A change of the goal's settings (the runner's week, the energy screen) is not a setback:
    this week's record takes the new real date."""
    ws = _monday(today).isoformat()
    tr = dict(g_row.track_json or {})
    weeks = dict(tr.get("weeks") or {})
    if ws in weeks:
        weeks[ws] = {**weeks[ws], "realDate": res.get("realDate"), "status": res.get("status")}
        tr["weeks"] = weeks
        g_row.track_json = tr
