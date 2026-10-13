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
