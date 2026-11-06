"""The week's plan — a sheet of the Monday morning report (owner request 2026-10-04).

Every Monday the morning report lays the calendar week out day by day: which runs
(type, kilometres, heart-rate zone and pace, hard minutes with a concrete session,
descent), which strength sessions (Runner's must-have A / B) and which rides, sized so
the week reaches this week's targets from Trénink — the runner moves on — but never
goes over the capacity ceilings Zátěž shows.

How the week is built, in order:
  1. The targets are Trénink's (guidance.py): the 4-week cycle's 90 / 100 / 110 / 55 %
     of the runner's reference week, the taper, the graded return or the deload, each
     already capped at the 7-day capacity ceiling. Today is exactly today's
     recommendation (readiness, check-in, pain and illness included).
  2. Run days follow the runner's own pattern of the last 8 weeks (usual run days,
     long-run day, hard days).
  3. Hard sessions: at most 2 a week with ≤ 4 runs, else 3 (Seiler 2010; Casado et al.,
     2022), never more than every other run, ≥ 48 h apart and not next to the long run,
     each with at least 10 min of the week's hard-minute budget. None with pain, a
     mechanics drift, an elevated load, in a graded return's first 14 days or the
     recovery after a race; with low readiness or an illness signal not in the first
     2 days; none within 2 days of a race.
  4. Kilometres: the long run ≤ 30 % of the week and ≤ the single-run ceiling, the hard
     runs at the usual easy distance, the easy runs share the rest. Each day is checked
     against the rolling 7-day ceiling together with the last days of the previous week,
     so no 7 days in a row go over it.
  5. Strength: the week's 2 sessions (1 within 14 days of a race; Blagrove et al., 2018),
     ≥ 48 h apart, never the day before a hard or long run, the heavy session A not on or
     the day after one either (Doma et al., 2017), none in the 3 days before a race.
  6. Rides fill what the all-sport load (HR × time) has left after the runs and the
     strength sessions, in Z2 of the cycling HR max, on days without a run, keeping at
     least one day of full rest.
Every morning Trénink re-sizes the day by readiness; the plan assumes normal recovery.
The splits are the product team's working assumptions on the cited principles.

Owner request 2026-10-26 — the runner can change a day ("pins", runners.planner_json["dayPins"]):
a pinned day is laid first and the rest of the week is re-laid around it under the same rules
and ceilings. A pin the rules don't allow is never placed (options() offers alternatives
instead); one that new data makes impossible later falls back to what the day can take, with
the reason in `pins`."""
import math
from datetime import date, timedelta
from itertools import combinations

from . import goal_sessions as GS

from .guidance import (HEAT_NOTE, CROSS_MIN, HARD_Z4_MIN, KOLO_MAX, LONG_SHARE, MIN_RUN_KM, NOVICE_LONG, NOVICE_Z4,
                       READY_QUALITY, TYPE_LABEL, VODA_MAX, WD_IN, Z4_SESSION_MAX)

WD = ("po", "út", "st", "čt", "pá", "so", "ne")
WD_LONG = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
RUN_TYPES = ("regenerace", "lehký", "dlouhý", "kvalitní")
# usual run days when the runner has no pattern yet (Mon = 0)
DEFAULT_RUN_DAYS = {1: (5,), 2: (1, 5), 3: (1, 3, 6), 4: (1, 3, 5, 6), 5: (0, 1, 3, 5, 6), 6: (0, 1, 2, 3, 5, 6),
                    7: (0, 1, 2, 3, 4, 5, 6)}
STRENGTH_MIN, STRENGTH_RPE = (30, 45), 6.5
QUALITY_SYS = 0.5          # a hard minute's all-sport load above an easy one, share of a Z4 minute (working assumption)
SESSION_NAME = {"A": "A · Síla (těžší)", "B": "B · Odolnost"}
STRENGTH_A_RACE = 7         # no heavier session A in the last 7 days before a race
PIN_TYPES = ("lehký", "dlouhý", "kvalitní", "regenerace", "kolo", "voda", "posilování", "volno")
PIN_RUN = ("lehký", "dlouhý", "kvalitní", "regenerace")


def _r(v, d=1):
    return None if v is None else round(v, d)


def _cz(v, d=1) -> str:
    txt = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    return txt[:-2] if d and txt.endswith(",0") else txt


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def session_text(m: float, k: int) -> str:
    """A concrete hard session for `m` minutes in Z4+; the week's first is intervals,
    the second tempo, so the two hard days differ."""
    m = int(m)
    if k % 2 == 0:
        rep = 2 if m < 12 else 3 if m < 20 else 4 if m < 30 else 5
        reps = max(3, m // rep)
        main = f"{reps} × {rep} min v Z4–Z5, mezi úseky {'2–3' if rep >= 4 else '2'} min volným klusem"
    else:
        rep = 5 if m < 20 else 8 if m < 32 else 10
        reps = max(2, m // rep)
        main = f"{reps} × {rep} min v Z4 (tempo, ještě se dá říct pár slov), mezi úseky 2 min volně"
    return f"{main}; rozklus 15 min a výklus 10 min v Z1–Z2"


def _run(kind, km, types, x, *, z4=None, sess=None, desc=None, asc=None, optional=False, strides=False, note=None):
    t = types.get(kind) or {}
    pace = t.get("pace")
    mid = ((pace[0] + pace[1]) / 2) if pace else x.get("easyPace")
    lo = km * (0.85 if kind == "dlouhý" else 0.8)
    return {"kind": "run", "type": kind, "label": TYPE_LABEL[kind] + (" (volitelně)" if optional else ""),
            "km": {"lo": _r(lo), "hi": _r(km)},
            "durationMin": [round(lo * mid / 60), round(km * mid / 60)] if mid else None,
            "hr": t.get("hr"), "zones": t.get("hrZones"), "pace": pace if kind != "kvalitní" else None,
            "z4": z4, "session": sess, "descentMax": desc, "ascentMax": asc, "optional": optional,
            "strides": strides, "note": note}


def _today_items(g, types, wk) -> list:
    typ = g.get("type")
    if g.get("done"):
        return [{"kind": "done", "label": "Odběhnuto", "km": wk["volume"].get("doneToday")}]
    t = types.get(typ) or {}
    if typ == "volno":
        return [{"kind": "rest", "label": "Volno", "note": (g.get("override") or {}).get("title")}]
    if typ in ("kolo", "voda"):
        return [{"kind": "ride" if typ == "kolo" else "swim", "label": t.get("label"), "min": t.get("durationMin"),
                 "hr": t.get("hr"), "zones": t.get("hrZones"), "optional": False, "note": None}]
    if typ == "závod":
        return [{"kind": "race", "label": t.get("label"), "km": t.get("km"), "note": None}]
    km = t.get("km") or {}
    z4 = t.get("z4Target")
    return [{"kind": "run", "type": typ, "label": t.get("label"), "km": {"lo": km.get("lo"), "hi": km.get("hi")},
             "durationMin": t.get("durationMin"), "hr": t.get("hr"), "zones": t.get("hrZones"), "pace": t.get("pace"),
             "z4": z4, "session": ((GS.session((g.get("planCtx") or {}).get("goalCtx"), z4["hi"], 0) or session_text(z4["hi"], 0))
                                   if (typ == "kvalitní" and z4 and z4.get("hi")) else None),
             "descentMax": t.get("descentMax"), "ascentMax": t.get("ascentMax"), "optional": False, "strides": False,
             "note": None}]


def _roll_left(day: date, past: dict, planned: dict, ceil7) -> float | None:
    """What the 7-day ceiling leaves for `day` after the 6 days before it (done or planned)."""
    if ceil7 is None:
        return None
    used = 0.0
    for k in range(1, 7):
        d = day - timedelta(days=k)
        used += planned.get(d, past.get(d.isoformat(), 0.0)) or 0.0
    return max(0.0, ceil7 - used)


def _room(day: date, today: date, chw: dict, past: dict, planned: dict) -> float | None:
    """What the weekly ceiling leaves for `day`. Owner request 2026-10-06: under the
    absorbed load, like the score and today's limit — this morning's unabsorbed load and
    today's and the planned days' sessions, each fading by the nightly share — so a long
    run keeps counting less and less instead of fully for 6 days. The plain 7-day ceiling
    minus the 6 days before only when the absorbed figures are missing."""
    mx, k, base = chw.get("absorbedMax"), chw.get("absorbK"), chw.get("absorbedPast")
    if mx is None or not k or base is None:
        return _roll_left(day, past, planned, chw.get("ceiling7"))
    q = 1 - k
    used = base * q ** (day - today).days + sum((v or 0) * q ** (day - e).days for e, v in planned.items() if today <= e < day)
    return max(0.0, mx - used)


def _headline(g) -> str:
    w = g.get("week") or {}
    mode, cyc = w.get("mode"), w.get("cycle") or {}
    if mode == "build":
        return f"{cyc.get('pos')}. týden cyklu · {round((w.get('progression') or 1) * 100)} % referenčního týdne"
    if mode == "recovery":
        return "4. týden cyklu · odlehčovací týden"
    if mode == "deload":
        return "Odlehčovací týden · zátěž je zvýšená"
    if mode == "taper":
        return "Ladění formy před závodem"
    if mode == "return":
        return f"Návrat po zranění · {cyc.get('returnWeek')}. týden ze 3"
    gw = (g.get("goal") or {}).get("week") or {}
    if mode == "goal" and gw:
        from .goal_plan import PHASE
        return (f"Plán k cíli · {PHASE.get(gw.get('phase'), '').lower()}, {gw['i']}. týden z {(g.get('goal') or {}).get('weeks')}"
                + (" · odlehčovací týden" if gw.get("deload") else ""))
    if w.get("novice"):
        return "Prvních 6 týdnů · opatrné navyšování"
    return "Cyklus nastavíme po 4 týdnech dat · cílem je vaše kapacita"


def build(a: dict | None, today: date, program: dict | None = None, pins: dict | None = None) -> dict | None:
    """The calendar week of `today`, day by day. `program` = the active Runner's
    must-have {name, due: "A"|"B", last: iso|None} or None. `pins` = the runner's own
    changes {iso: {"type", "km"?, "min"?, "session"?}} (today's is applied by guidance)."""
    g = (a or {}).get("guidance") or {}
    x = g.get("planCtx")
    if not x:
        return None
    types = g.get("types") or {}
    wk = (g.get("week") or {}).get("channels") or {}
    pat = g.get("pattern") or {}
    vol, inten, sysw = wk.get("volume") or {}, wk.get("intensity") or {}, wk.get("systemic") or {}
    ws = today - timedelta(days=today.weekday())
    days = [ws + timedelta(days=k) for k in range(7)]
    future = [d for d in days if d > today]
    items: dict = {d: [] for d in days}
    notes: list = []
    easy = x.get("easyKm") or 6.0
    min_run = max(MIN_RUN_KM, 0.5 * easy)
    ceil = (x.get("ceilRun") or {}).get("volume") or 1e9
    rscore = x.get("readiness") or 100
    races = {_d(r["date"]): r for r in x.get("races") or [] if ws <= _d(r["date"]) <= days[-1]}
    fixed = {_d(k): v for k, v in (pins or {}).items()
             if v and v.get("type") in PIN_TYPES and _d(k) in future and _d(k) not in races}
    pin_why: dict = {}                              # a pin that couldn't be placed as asked → why
    all_races = [_d(r["date"]) for r in x.get("races") or []]
    race_pri = {_d(r["date"]): r.get("priority") or "A" for r in x.get("races") or []}

    # ---- days already behind (the plan from Monday shows none) and today
    pvol, psys = x["past"]["volume"], x["past"]["systemic"]
    for d in days:
        if d < today:
            km = pvol.get(d.isoformat()) or 0
            if km:
                items[d].append({"kind": "done", "label": "Odběhnuto", "km": _r(km)})
            elif psys.get(d.isoformat()):
                items[d].append({"kind": "done", "label": "Jiný trénink", "km": None})
    items[today] = _today_items(g, types, wk)
    typ = g.get("type")
    today_run = typ in RUN_TYPES and not g.get("done")
    today_km = ((types.get(typ) or {}).get("km") or {}).get("hi") or 0 if today_run else 0
    today_z4 = (((types.get(typ) or {}).get("z4Target") or {}).get("hi") or 0) if (today_run and typ == "kvalitní") else 0

    out = {"weekStart": ws.isoformat(), "headline": _headline(g), "mode": (g.get("week") or {}).get("mode"),
           "notes": notes, "rules": [], "override": None, "pins": {}}
    tp = g.get("pin") or {}
    if tp.get("type"):                            # today's change, applied (or not) by the morning's guidance
        out["pins"][today.isoformat()] = {"type": tp["type"], "status": "ok" if tp.get("applied") else "no",
                                          "why": tp.get("why")}

    def finish(totals=None):
        for d, p in fixed.items():
            if d.isoformat() not in out["pins"]:
                out["pins"][d.isoformat()] = _pin_status(p, items[d], pin_why.get(d))
        for d in fixed:
            for it in items[d]:
                it["pinned"] = True
        if tp.get("applied"):
            for it in items[today]:
                it["pinned"] = True
        out["days"] = [{"date": d.isoformat(), "wd": WD[d.weekday()], "wdLong": WD_LONG[d.weekday()],
                        "today": d == today, "past": d < today, "items": items[d],
                        "pinned": (d.isoformat() in out["pins"]) and out["pins"][d.isoformat()]["status"] != "no",
                        "pin": out["pins"].get(d.isoformat())}
                       for d in days]
        out["totals"] = totals
        return out

    # ---- Plán od trenéra (2026-10-12): the coach's week with the app's verdicts, not its own layout
    coach = g.get("coach") or {}
    if coach.get("on") and coach.get("eval"):
        fixed.clear()                          # the coach's week is changed in the coach's plan
        return _coach_week(coach, out, days, today, items, finish)

    # ---- a stop: no running plan, only what doesn't hurt
    ov = g.get("override")
    if ov or x.get("ill"):
        out["override"] = ov["title"] if ov else "Hlásíte nemoc — tento týden nejdřív odpočinek"
        for d in fixed:
            pin_why[d] = f"Plán běhu je teď pozastavený: {out['override'][0].lower() + out['override'][1:]}"
        fixed_keep = {d: p for d, p in fixed.items() if p["type"] == "volno"}
        for d in fixed_keep:
            items[d].append({"kind": "rest", "label": "Volno", "note": None})
            pin_why.pop(d, None)
        notes.append("Plán běhu je pozastavený. Každé ráno ho Trénink znovu posoudí a jakmile to půjde, "
                     "vrátí běh postupně.")
        if x.get("kolo") and (not ov or ov.get("kind") != "red_flag") and not x.get("ill"):
            kolo = types.get("kolo") or {}
            for d in future[1::2]:
                items[d].append({"kind": "ride", "label": "Kolo nebo plavání (volitelně)", "min": kolo.get("durationMin"),
                                 "hr": kolo.get("hr"), "zones": kolo.get("hrZones"), "optional": True,
                                 "note": "Jen pokud při tom nic nebolí."})
        for d in future:
            if not items[d]:
                items[d].append({"kind": "rest", "label": "Volno", "note": None})
        return finish()

    budget = vol.get("budget")
    if budget is None:
        for d in fixed:
            pin_why[d] = "Na plán týdne zatím chybí data o vaší týdenní kapacitě."
        notes.append("Na plán týdne zatím chybí data o vaší týdenní kapacitě — stačí pár týdnů běhů.")
        for d in future:
            items[d].append({"kind": "rest", "label": "Podle ranního doporučení", "note": None})
        return finish()
    left = max(0.0, budget - (vol.get("done") or 0) - today_km)

    # ---- run days: the runner's own pattern
    n_runs = int(round(pat.get("runsPerWeek") or 0)) or 3
    if x.get("goalRuns"):                          # a first marathon (Trénink k cíli): 3 runs, a 4th only when needed
        n_runs = x["goalRuns"]
    usual = set(pat.get("runDays") or []) or set(DEFAULT_RUN_DAYS[min(7, max(1, n_runs))])
    before = sum(1 for d in days if d < today and pvol.get(d.isoformat()))
    allowed = max(0, max(n_runs, before + int(today_run or bool(g.get("done")))) - before - int(today_run or bool(g.get("done"))))
    pin_run = sorted(d for d, p in fixed.items() if p["type"] in PIN_RUN)
    run_days = [d for d in future if d.weekday() in usual and d not in races and d not in fixed]
    long_wd = pat.get("longDay")
    hard_wd = set(pat.get("hardDays") or [])

    lday = ws + timedelta(days=long_wd) if long_wd is not None else None
    if lday in future and lday not in run_days and lday not in races and lday not in fixed:
        run_days = sorted(run_days + [lday])         # the usual long-run day even when it isn't a usual run day

    def neighbours(d, pool):
        return sum(1 for e in pool if abs((e - d).days) == 1) + (1 if (d - today).days == 1 and (today_run or g.get("done")) else 0)
    free = max(0, allowed - len(pin_run))           # the runner's own run days count first
    while len(run_days) > free:
        drop = max((d for d in run_days if d.weekday() != long_wd), key=lambda d: (neighbours(d, run_days + pin_run), d), default=None)
        run_days.remove(drop if drop is not None else run_days[-1])
    if len(run_days) < free:
        for wd in DEFAULT_RUN_DAYS[min(7, max(1, n_runs))]:
            d = ws + timedelta(days=wd)
            if len(run_days) >= free:
                break
            if d in future and d not in run_days and d not in races and d not in fixed:
                run_days.append(d)
        if fixed:                                    # a day the runner took off moves the run to another free day
            spare = [d for d in future if d not in run_days and d not in races and d not in fixed]
            while len(run_days) < free and spare:
                d = min(spare, key=lambda e: (neighbours(e, run_days + pin_run), e))
                spare.remove(d)
                run_days.append(d)
    run_days = sorted(run_days + pin_run)

    # ---- what the context allows on a day
    def early(d):                          # low readiness / illness signal → nothing hard in the first 2 days
        return (rscore < READY_QUALITY or x.get("illWatch") or x.get("illLight")) and (d - today).days < 2

    def ok_hard(d):
        if x.get("painMod") or x.get("drift") or x.get("deload") or x.get("overreaching") or early(d):
            return False
        if x.get("noQualityUntil") and d < _d(x["noQualityUntil"]):
            return False
        if x.get("raceRecoveryUntil") and d < _d(x["raceRecoveryUntil"]):
            return False
        return not any(abs((r - d).days) <= 2 for r in all_races)

    def ok_long(d):
        if x.get("painMod") or x.get("overreaching") or early(d):
            return False
        if x.get("raceRecoveryUntil") and d < _d(x["raceRecoveryUntil"]):
            return False
        return not any(0 <= (r - d).days <= 7 and race_pri[r] in ("A", "B") for r in all_races) and not any(0 < (d - r).days <= 2 for r in all_races)

    def why_ctx(d, what):                  # why a pinned hard / long day can't stand (the rules above, in words)
        if x.get("painMod"):
            return f"{x.get('painWhy') or 'Bolest'} — tento týden bez {what}."
        if what == "intenzity" and x.get("drift"):
            return "Mechanika se odchyluje od vaší normy — tento týden bez intenzity."
        if x.get("deload") or x.get("overreaching"):
            return f"Zátěž je zvýšená — tento týden bez {what}."
        if early(d):
            return f"Nízká připravenost nebo možný začátek nemoci — první dva dny bez {what}."
        if what == "intenzity" and x.get("noQualityUntil") and d < _d(x["noQualityUntil"]):
            q = _d(x["noQualityUntil"])
            return f"Návrat po {x.get('noQualityWhy') or 'zranění'} — bez intenzity do {q.day}. {q.month}."
        if x.get("raceRecoveryUntil") and d < _d(x["raceRecoveryUntil"]):
            return f"Po závodě ještě regenerace — bez {what} do {_d(x['raceRecoveryUntil']).day}. {_d(x['raceRecoveryUntil']).month}."
        if what == "intenzity" and any(abs((r - d).days) <= 2 for r in all_races):
            return "Dva dny před závodem a po něm bez tvrdého tréninku."
        if any(0 <= (r - d).days <= 7 and race_pri[r] in ("A", "B") for r in all_races):
            return "Týden před závodem bez dlouhého běhu."
        return "Dva dny po závodě bez dlouhého běhu."

    # ---- the long run
    long_done = typ == "dlouhý" or any((pvol.get(d.isoformat()) or 0) >= 1.25 * easy for d in days if d < today)
    long_day = None
    L = min(ceil, max(1.2 * easy, LONG_SHARE * budget))
    if x.get("goalLong"):                          # the goal's plan sets the long run (≤ 50 % in its specific phase)
        L = min(ceil, max(1.2 * easy, x["goalLong"]))
    if x.get("novice") and x.get("longest30"):
        L = min(L, NOVICE_LONG * x["longest30"])
    pin_long = [d for d in pin_run if fixed[d]["type"] == "dlouhý"]
    for d in pin_long[1:] if not long_done else pin_long:
        pin_why[d] = ("Dlouhý běh už tento týden máte za sebou." if long_done else
                      "Dlouhý běh se do týdne vejde jen jednou.")
    for d in list(pin_long):
        if d in pin_why:
            continue
        if not ok_long(d):
            pin_why[d] = why_ctx(d, "dlouhého běhu")
        elif L < 1.2 * easy:
            pin_why[d] = "Na dlouhý běh tento týden nezbývá objem."
    pin_long_ok = [d for d in pin_long if d not in pin_why]
    if pin_long_ok:
        long_day = pin_long_ok[0]
        if fixed[long_day].get("km"):
            L = min(L, max(1.2 * easy, float(fixed[long_day]["km"])))
    elif not long_done and len(run_days) + before + int(today_run) >= 3 and L >= 1.2 * easy:
        cand = [d for d in run_days if ok_long(d) and d not in fixed]
        long_day = next((d for d in cand if d.weekday() == long_wd), None)
        if long_day is None and (long_wd is None or (fixed and (ws + timedelta(days=long_wd)) in fixed)):
            wkend = [d for d in cand if d.weekday() >= 5]
            long_day = wkend[-1] if wkend else (cand[-1] if cand else None)

    # ---- hard sessions
    i_budget = inten.get("budget")
    i_left = None if i_budget is None else max(0.0, i_budget - (inten.get("done") or 0) - today_z4)
    total_runs = before + int(today_run or bool(g.get("done"))) + len(run_days)
    hard_done = len(x.get("hardThisWeek") or []) + int(typ == "kvalitní" or x.get("todayHard"))
    if x.get("novice"):
        nq = 1 if (pat.get("hardPerWeek") or 0) >= 0.5 else 0
    elif i_left is None or i_left < HARD_Z4_MIN:
        nq = 0
    else:
        nq = min(x.get("hardCap") or 2, max(1, round(pat.get("hardPerWeek") or 0)), max(1, (total_runs - 1) // 2))
        if (g.get("week") or {}).get("mode") in ("taper", "recovery", "return"):
            nq = min(nq, 1)
        gw = (g.get("goal") or {}).get("week") or {}
        if (g.get("week") or {}).get("mode") == "goal" and (gw.get("deload") or gw.get("taper") or gw.get("phase") == "base"):
            nq = min(nq, 1)                    # the goal's base phase, recovery and taper weeks: one hard session at most
    nq = max(0, nq - hard_done)
    anchors = {d for d in (_d(x["lastHard"]) if x.get("lastHard") else None, long_day) if d}
    anchors |= {_d(h) for h in x.get("hardThisWeek") or []} | set(races)
    if typ in ("kvalitní", "závod") or x.get("todayHard"):
        anchors.add(today)
    q_days = []
    for d in [d for d in pin_run if fixed[d]["type"] == "kvalitní"]:
        if not ok_hard(d):
            pin_why[d] = why_ctx(d, "intenzity")
        elif len(q_days) >= nq:
            pin_why[d] = ("Na tvrdý trénink tento týden nezbývá rozpočet intenzity." if (i_left is not None and i_left < HARD_Z4_MIN)
                          else f"Tvrdých tréninků už je tento týden dost — nejvýš {x.get('hardCap') or 2} za týden.")
        elif any(abs((d - a_).days) < 2 for a_ in anchors | set(q_days)):
            pin_why[d] = "Tvrdé dny musí být aspoň 48 hodin od sebe a ne vedle dlouhého běhu nebo závodu."
        else:
            q_days.append(d)
    for _ in range(nq - len(q_days)):
        cand = [d for d in run_days if d != long_day and d not in q_days and ok_hard(d) and d not in fixed
                and all(abs((d - a_).days) >= 2 for a_ in anchors | set(q_days))]
        if not cand:
            break
        q_days.append(max(cand, key=lambda d: (d.weekday() in hard_wd,
                                               min([min(3, abs((d - a_).days)) for a_ in anchors | set(q_days)] or [3]),
                                               -d.toordinal())))
    q_days.sort()
    z4 = {}
    if q_days:
        cap_i = min((x.get("ceilRun") or {}).get("intensity") or Z4_SESSION_MAX, Z4_SESSION_MAX)
        while q_days:
            per = NOVICE_Z4 if (x.get("novice") and i_left is None) else min(cap_i, (i_left or 0) / len(q_days))
            if per >= HARD_Z4_MIN or x.get("novice"):
                break
            q_days.pop()
        for d in q_days:
            z4[d] = per

    # ---- kilometres
    # the runner's own easy / recovery runs keep their size (within the single-run ceiling)
    pin_easy = {}
    for d in pin_run:
        p = fixed[d]
        if p["type"] == "lehký":
            pin_easy[d] = min(ceil, 1.5 * easy, float(p.get("km") or easy))
        elif p["type"] == "regenerace":
            pin_easy[d] = min(ceil, 0.8 * easy, float(p.get("km") or max(min_run, 0.6 * easy)))
    easy_days = [d for d in run_days if d != long_day and d not in q_days and d not in pin_easy]
    q_km = min(ceil, easy)
    pace_e = x.get("easyPace") or 400
    if x.get("dayMin"):                         # plan k cíli 2.0 #10: the runner's time on a weekday
        q_km = min(q_km, x["dayMin"] * 60 / pace_e)
    if long_day and x.get("longMin"):
        L = min(L, x["longMin"] * 60 / (pace_e * 1.05))
    need = (L if long_day else 0) + q_km * len(q_days) + sum(pin_easy.values())
    if need > left:
        easy_days = []
        f = left / need if need else 0
        L, q_km = L * f, q_km * f
        pin_easy = {d: v * f for d, v in pin_easy.items()}
        if long_day and L < 1.2 * easy:
            if long_day in fixed:
                pin_why[long_day] = "Na dlouhý běh tento týden nezbývá objem — týdenní cíl je skoro splněný."
            easy_days.append(long_day)
            long_day = None
        need = (L if long_day else 0) + q_km * len(q_days) + sum(pin_easy.values())
    rem = max(0.0, left - need)
    while easy_days and rem / len(easy_days) < min_run:
        easy_days.remove(max(easy_days, key=lambda d: (neighbours(d, run_days), d)))
    e_cap = min(ceil, 1.5 * easy, 0.9 * L if long_day else 1e9, x["dayMin"] * 60 / pace_e if x.get("dayMin") else 1e9)
    e_km = min(e_cap, rem / len(easy_days)) if easy_days else 0.0
    plan_km = {d: e_km for d in easy_days}
    plan_km.update(pin_easy)
    plan_km.update({d: q_km for d in q_days})
    if long_day:
        plan_km[long_day] = L
    # the rolling 7 days, with the end of last week
    planned = {}

    def fit_rolling():
        planned.clear()
        planned[today] = (vol.get("doneToday") or 0) if g.get("done") else today_km
        for d in sorted(plan_km):
            room = _room(d, today, vol, pvol, planned)
            if room is not None and plan_km[d] > room:
                plan_km[d] = room
            if plan_km[d] < min_run:
                del plan_km[d]
                continue
            if d in q_days and plan_km[d] < 0.75 * q_km:
                q_days.remove(d)               # too little room for a hard session → an easy run
                z4.pop(d, None)
            planned[d] = plan_km[d]
    fit_rolling()
    # intensity the same way
    planned_i = {today: (inten.get("doneToday") or 0) if g.get("done") else today_z4}
    for d in sorted(z4):
        if d not in plan_km:
            del z4[d]
            continue
        room = _room(d, today, inten, x["past"]["intensity"], planned_i)
        if room is not None and z4[d] > room:
            z4[d] = room
        if z4[d] < HARD_Z4_MIN and not x.get("novice"):
            del z4[d]                      # not enough room for a hard session → an easy run
            continue
        planned_i[d] = z4[d]
    q_days = [d for d in q_days if d in z4]
    leftover = max(0.0, left - sum(plan_km.values()))
    ceil7 = vol.get("ceiling7")

    def window(e):                          # the 7 days ending on `e`, done or planned
        return sum((planned.get(e - timedelta(days=j)) if (e - timedelta(days=j)) in planned
                    else pvol.get((e - timedelta(days=j)).isoformat(), 0.0)) or 0.0 for j in range(7))

    def room_at(d):                         # how much more `d` can take without any later day going over
        if vol.get("absorbedMax") is not None and vol.get("absorbK"):
            q = 1 - vol["absorbK"]
            ends = [d] + [e for e in planned if e > d]
            return max(0.0, min((_room(e, today, vol, pvol, planned) - (planned.get(e) or 0)) / q ** (e - d).days for e in ends))
        if ceil7 is None:
            return 1e9
        ends = [d] + [e for e in planned if d < e <= d + timedelta(days=6)]
        return max(0.0, min(ceil7 - window(e) for e in ends))
    # what a cut day couldn't take goes to the other easy runs, up to their size and the room left
    for d in sorted(plan_km):
        if leftover < 0.1:
            break
        if d in q_days or d == long_day or d in pin_easy:
            continue
        add = min(leftover, e_cap - plan_km[d], room_at(d))
        if add >= 0.1:
            plan_km[d] += add
            planned[d] = plan_km[d]
            leftover -= add

    # an extra short easy run when the usual days can't carry the week (more often before longer)
    extra = None
    if (leftover >= max(min_run, 0.6 * easy) and rscore >= READY_QUALITY and not x.get("painMod")
            and not x.get("drift") and len(plan_km) + 1 <= 6):
        busy = set(plan_km) | {today} | set(fixed)
        hard_next = set(q_days) | ({long_day} if long_day else set()) | set(races)
        cand = [d for d in future if d not in busy and d not in races and (d + timedelta(days=1)) not in hard_next]
        rest_after = sum(1 for d in days if d not in busy and d > today) - 1
        cand = [d for d in cand if room_at(d) >= min_run]
        if cand and rest_after >= 1:
            extra = min(cand, key=lambda d: (neighbours(d, list(busy)), d))
            km = min(leftover, 0.8 * easy, ceil, room_at(extra), x["dayMin"] * 60 / pace_e if x.get("dayMin") else 1e9)
            if km >= min_run:
                plan_km[extra] = km
                fit_rolling()                  # the days after it may now have less room
                if extra not in plan_km:
                    extra = None
                leftover = max(0.0, left - sum(plan_km.values()))
            else:
                extra = None

    # descent / ascent: the week's budget by kilometres, never over the single-run ceiling
    tot_km = sum(plan_km.values()) or 1.0

    def hills(c, d):
        b = (wk.get(c) or {}).get("budget")
        if b is None:
            return None
        lft = max(0.0, b - ((wk.get(c) or {}).get("done") or 0))
        v = lft * plan_km[d] / tot_km * (0.6 if d in q_days else 1.0)
        cr = (x.get("ceilRun") or {}).get(c)
        return _r(min(v, cr) if cr else v, 0)

    strides_day = None
    if (x.get("noSpeedWeeks") or not q_days) and not (x.get("painMod") or x.get("drift") or x.get("noQualityUntil")):
        nxt_hard = set(q_days) | ({long_day} if long_day else set())
        strides_day = next((d for d in sorted(plan_km) if d not in nxt_hard and d != extra
                            and (d + timedelta(days=1)) not in nxt_hard), None)
    for k, d in enumerate(sorted(plan_km)):
        kind = ("dlouhý" if d == long_day else "kvalitní" if d in q_days else
                "regenerace" if (d in pin_easy and fixed[d]["type"] == "regenerace") else "lehký")
        zq = None
        if kind == "kvalitní":
            zq = {"lo": _r(0.6 * z4[d], 0), "hi": _r(z4[d], 0)}
        kq = q_days.index(d) + (1 if typ == "kvalitní" else 0) if kind == "kvalitní" else 0
        sess = (GS.session(x.get("goalCtx"), z4[d], kq) or session_text(z4[d], kq)) if kind == "kvalitní" else None
        note = ("4–6 stupňovaných rovinek po 15–20 s na konci (ne naplno) — pravidelný kontakt "
                "s rychlostí chrání zadní stehenní svaly." if d == strides_day else None)
        if kind == "dlouhý":
            note = GS.long_note(x.get("goalCtx"), plan_km[d], x.get("goalFuel"), x.get("giBad")) or note
        elif kind == "lehký" and x.get("goalHeat") and d != strides_day:
            note = HEAT_NOTE[x["goalHeat"]]
        items[d].append(_run(kind, plan_km[d], types, x, z4=zq, sess=sess,
                             desc=hills("descent", d), asc=hills("ascent", d), optional=d == extra,
                             strides=d == strides_day, note=note))
    if x.get("hrvLow") and q_days and typ != "kvalitní":
        notes.append(f"Tvrdý trénink se z dneška přesunul na {WD_LONG[q_days[0].weekday()].lower()}: HRV je dnes "
                     "pod vaším běžným pásmem.")
    for d, r in races.items():
        if d > today:
            items[d].append({"kind": "race", "label": r.get("name") or "Závod", "km": r.get("km"), "note": None})

    # ---- strength
    st = g.get("strength") or {}
    # "done" (guidance: strength sessions since Monday) already holds today's — counting "today" on top
    # of it counted one session twice: the week said 2× after one session, and the second went unplanned
    n_s = max(0, (st.get("target") or 0) - (st.get("done") or 0))
    pos_t = types.get("posilování") or {}
    hard_set = set(q_days) | ({long_day} if long_day else set()) | set(races) | (
        {today} if (typ in ("kvalitní", "dlouhý", "závod") or x.get("todayHard")) else set())
    if x.get("lastHard"):
        hard_set.add(_d(x["lastHard"]))
    hard_set |= {_d(k) for k, v in pvol.items() if (v or 0) >= 1.25 * easy}      # a long run in the last days
    last_s = _d(program["last"]) if (program and program.get("last")) else (
        today - timedelta(days=st["lastAge"]) if st.get("lastAge") is not None else None)
    s_cand = ([today] if (pos_t.get("allowed") and not st.get("today")) else []) + future
    s_cand = [d for d in s_cand if fixed.get(d, {}).get("type") != "volno"]
    due = (program or {}).get("due") or "A"
    seq0 = [due, "B" if due == "A" else "A"]

    def s_ok(d, kind):
        if (d + timedelta(days=1)) in hard_set or d == long_day or d in races:
            return False
        if any(0 <= (r - d).days <= 3 for r in all_races) or (early(d) and x.get("illWatch")):
            return False
        if last_s and (d - last_s).days < 2:
            return False
        if kind == "A" and any(0 <= (r - d).days < STRENGTH_A_RACE for r in all_races):
            return False                      # the last heavier session 7–10 days before a race (plan k cíli 2.0 #14)
        return not (kind == "A" and (d in hard_set or (d - timedelta(days=1)) in hard_set))

    def rest_days(extra_busy=()):
        return sum(1 for d in days if d >= today and d not in extra_busy
                   and all(it["kind"] == "rest" for it in items[d]))
    # the runner's own strength days: placed when the rules allow them, the others around them
    pin_s = []
    for d in sorted(d for d, p in fixed.items() if p["type"] == "posilování"):
        if not (s_ok(d, "A") or s_ok(d, "B")):
            pin_why[d] = (_why_strength(d, hard_set, long_day, races, all_races, last_s, early(d) and x.get("illWatch")))
        elif any(abs((d - e).days) < 2 for e in pin_s):
            pin_why[d] = "Posilování aspoň 48 hodin od sebe."
        else:
            pin_s.append(d)
    n_s = max(n_s, len(pin_s))
    best, best_sc, swapped = None, None, False
    for n in range(n_s, 0, -1):
        if n < len(pin_s):
            break
        for combo, (order, seq) in ((c_, o_) for c_ in combinations(s_cand, n) for o_ in enumerate((seq0, seq0[::-1]))):
            if any((b - a_).days < 2 for a_, b in zip(combo, combo[1:])) or not set(pin_s) <= set(combo):
                continue
            # the due session first; B first and A after it is what the programme itself does
            # when the day can't carry A (durability.choose), so it costs a little
            kinds, sc, sw = [], -0.5 * order, False
            for d, kind in zip(combo, seq):
                if not s_ok(d, kind):
                    if kind == "A" and s_ok(d, "B"):
                        kind, sw = "B", True
                        sc -= 2
                    else:
                        sc = None
                        break
                kinds.append(kind)
                runs_d = [it for it in items[d] if it["kind"] == "run"]
                sc += 1.0 if not runs_d else 0.8 if runs_d[0]["type"] in ("lehký", "regenerace") else 0.3
            if sc is None:
                continue
            if rest_days(set(combo)) < 1 and rest_days(set()) >= 1:
                sc -= 1.5
            if len(combo) == 2:
                sc += 0.3 * min(3, (combo[1] - combo[0]).days)
            if best_sc is None or sc > best_sc:
                best, best_sc, swapped = list(zip(combo, kinds)), sc, sw
        if best:
            break
    if n_s and (not best or len(best) < n_s):
        notes.append(f"Posilování se tento týden vejde jen {len(best or [])}× — kolem tvrdých a dlouhých běhů "
                     "a závodů na něj nezbývá den, který by ho unesl.")
    if swapped and any(0 <= (r - d).days < STRENGTH_A_RACE for d, _k in best or [] for r in all_races):
        notes.append("Týden před závodem jen lehčí silová B: poslední těžší posilování má být 7–10 dní před startem.")
    elif swapped:
        notes.append("Těžší silová A se tento týden nevejde mezi tvrdé dny — místo ní lehčí B, A přijde příště.")
    want = {d: fixed[d].get("session") for d in pin_s if fixed[d].get("session") in ("A", "B")}
    best = [(d, want[d] if (d in want and s_ok(d, want[d])) else k_) for d, k_ in best or []]
    for d in want:
        if not s_ok(d, want[d]):
            pin_why[d] = f"Těžší silová A se na tento den nehodí (vedle tvrdého nebo dlouhého běhu) — místo ní B."
    for d, kind in best or []:
        same = any(it["kind"] == "run" for it in items[d])
        items[d].append({"kind": "strength", "label": "Posilování", "session": SESSION_NAME[kind], "sessionKey": kind,
                         "program": (program or {}).get("name") or "Runner's must-have", "min": list(STRENGTH_MIN),
                         "rpe": "6–7 z 10", "when": "s odstupem aspoň 3 hodin od běhu" if same else None})

    # ---- rides: what the all-sport load has left
    rides = []
    s_budget, per_km, per_min = sysw.get("budget"), x.get("perKm"), x.get("perMinRide")
    if s_budget is not None and per_km and per_min and x.get("kolo"):
        z4pm = x.get("z4PerMin") or 0
        k_s = x.get("kSrpe") or 0
        day_sys = {d: plan_km[d] * per_km + z4.get(d, 0) * z4pm * QUALITY_SYS for d in plan_km}
        day_sys[today] = (sysw.get("doneToday") or 0) if g.get("done") else (today_km * per_km + today_z4 * z4pm * QUALITY_SYS)
        for d, _k in best or []:
            day_sys[d] = day_sys.get(d, 0) + k_s * STRENGTH_RPE * sum(STRENGTH_MIN) / 2
        room = s_budget - (sysw.get("done") or 0) - sum(v for d, v in day_sys.items() if d != today or not g.get("done"))
        n_max = 3 if (x.get("rides8w") or 0) >= 4 else 2 if (x.get("rides8w") or 0) >= 1 else 1
        after_hard = set()
        for d in hard_set:
            after_hard.add(d + timedelta(days=1))
        for d in sorted(d for d, p in fixed.items() if p["type"] in ("kolo", "voda")):
            p, kt = fixed[d], fixed[d]["type"]
            t_ = types.get(kt) or {}
            want_m = float(p.get("min") or ((t_.get("durationMin") or [0, 45])[1]) or 45)
            m = min(want_m, KOLO_MAX if kt == "kolo" else VODA_MAX, max(0.0, room) / per_min)
            r7 = _room(d, today, sysw, psys, day_sys)
            if r7 is not None:
                m = min(m, r7 / per_min)
            if m < CROSS_MIN:
                pin_why[d] = "Celková zátěž tento týden už další trénink neunese."
                continue
            m = int(m // 5 * 5)
            if m < want_m - 4:
                pin_why[d] = "Kratší, než jste chtěli — víc celková zátěž týdne neunese."
            day_sys[d] = m * per_min
            room -= m * per_min
            items[d].append({"kind": "ride" if kt == "kolo" else "swim", "label": TYPE_LABEL[kt],
                             "min": [max(CROSS_MIN, int(0.75 * m // 5 * 5)), m], "hr": t_.get("hr") or (x.get("rideHr") if kt == "kolo" else None),
                             "zones": t_.get("hrZones") or ("Z2 na kole" if kt == "kolo" else None), "optional": False,
                             "note": x.get("koloNote") if kt == "kolo" else None})
        cand = [d for d in future if not items[d] and d not in races and (d + timedelta(days=1)) not in races and d not in fixed]
        cand.sort(key=lambda d: (d not in after_hard, d))
        n = min(n_max, max(0, rest_days() - 1), len(cand))
        while n > 0:
            mins = min(KOLO_MAX, room / n / per_min)
            if mins >= CROSS_MIN:
                break
            n -= 1
        for d in sorted(cand[:n]):
            m = min(KOLO_MAX, room / n / per_min)
            r7 = _room(d, today, sysw, psys, day_sys)
            if r7 is not None:
                m = min(m, r7 / per_min)
            if m < CROSS_MIN:
                continue
            m = int(m // 5 * 5)
            day_sys[d] = m * per_min
            rides.append(d)
            items[d].append({"kind": "ride", "label": "Kolo" + ("" if (x.get("rides8w") or 0) >= 2 else " (volitelně)"),
                             "min": [max(CROSS_MIN, int(0.75 * m // 5 * 5)), m], "hr": x.get("rideHr"),
                             "zones": "Z2 na kole", "optional": (x.get("rides8w") or 0) < 2, "note": x.get("koloNote")})
    for d in sorted(d for d, p in fixed.items() if p["type"] in ("kolo", "voda")):
        if d not in pin_why and not any(it["kind"] in ("ride", "swim") for it in items[d]):
            # no all-sport load to check against (no rides in the history yet): the runner's own minutes
            kt, t_ = fixed[d]["type"], types.get(fixed[d]["type"]) or {}
            m = int(min(float(fixed[d].get("min") or ((t_.get("durationMin") or [0, 45])[1]) or 45), KOLO_MAX if kt == "kolo" else VODA_MAX))
            items[d].append({"kind": "ride" if kt == "kolo" else "swim", "label": TYPE_LABEL[kt],
                             "min": [max(CROSS_MIN, int(0.75 * m // 5 * 5)), m], "hr": t_.get("hr"), "zones": t_.get("hrZones"),
                             "optional": False, "note": None})
    for d in future:
        if not items[d]:
            items[d].append({"kind": "rest", "label": "Volno", "note": None})

    # ---- what shaped the week
    if rscore < READY_QUALITY:
        first = min([d for d in q_days] or [None], key=lambda d: d or date.max)
        notes.append(f"Připravenost dnes {rscore} % — první dva dny lehce, tvrdý trénink až {WD_IN[first.weekday()]}."
                     if first else f"Připravenost dnes {rscore} % — první dva dny lehce.")
    if x.get("illWatch") or x.get("illLight"):
        notes.append("Hodinky nebo check-in ukazují možný začátek nemoci — první dva dny bez náročného tréninku.")
    if x.get("painMod"):
        notes.append(f"{x.get('painWhy') or 'Bolest'} — tento týden bez intenzity a dlouhého běhu, běhy kratší a po rovině, "
                     "dokud se to neuklidní.")
    if x.get("drift"):
        notes.append("Mechanika se odchyluje od vaší normy — bez intenzity a prudkých seběhů.")
    if x.get("deload") or x.get("overreaching"):
        notes.append("Zátěž je zvýšená — týden bez tvrdých úseků, ať klesne pod práh.")
    if x.get("noQualityUntil") and _d(x["noQualityUntil"]) > today:
        notes.append(f"Návrat po {x.get('noQualityWhy') or 'zranění'} — bez intenzity do {_d(x['noQualityUntil']).day}. {_d(x['noQualityUntil']).month}.")
    for d, r in sorted(races.items()):
        notes.append(f"Závod {WD_IN[d.weekday()]}: {r.get('name') or 'závod'} — dva dny před ním a po něm bez tvrdého "
                     "tréninku, tři dny před ním bez posilování, týden bez dlouhého běhu.")
    if leftover > 2:
        notes.append(f"Zbylých {_cz(leftover)} km se do týdne nevejde bez překročení stropu jednoho běhu nebo týdenní kapacity. "
                     "Cíl je horní hranice, ne povinnost.")
    if extra:
        notes.append(f"Navíc volitelný krátký lehký běh {WD_IN[extra.weekday()]}, když se budete cítit dobře — zbytek "
                     "týdenního cíle se jinak do stropů nevejde.")
    out["rules"] = [
        f"Tvrdé tréninky aspoň 48 hodin od sebe a ne vedle dlouhého běhu, nejvýš {x.get('hardCap') or 2} za týden.",
        "Posilování ne den před tvrdým nebo dlouhým během, těžší A ani v ten den a den po něm.",
        ("Nevstřebaná zátěž z posledních dní ani jeden den nepřesáhne strop týdenní kapacity: starší běhy se počítají "
         "jen zčásti, jak je tělo vstřebává." if vol.get("absorbedMax") is not None else
         f"Žádných 7 dní po sobě nepřesáhne strop kapacity {_cz(vol['ceiling7'])} km." if vol.get("ceiling7") else
         "Týdenní objem roste nejvýš o 10 % proti minulému týdnu."),
        "Každé ráno Trénink den upraví podle připravenosti — plán počítá s běžným zotavením.",
    ]
    km_plan = (vol.get("done") or 0) + today_km + sum(v for d, v in plan_km.items() if d != extra)
    z4_plan = (inten.get("done") or 0) + today_z4 + sum(z4.values())
    return finish({
        "km": _r(km_plan), "kmOptional": _r(plan_km.get(extra)) if extra else None, "kmBudget": _r(budget),
        "kmCeiling7": vol.get("ceiling7"), "kmDone": vol.get("done"),
        "z4": _r(z4_plan, 0), "z4Budget": _r(i_budget, 0) if i_budget is not None else None,
        "hard": len(q_days) + hard_done, "hardCap": x.get("hardCap"),
        "runs": sum(1 for d in days for it in items[d] if it["kind"] in ("run", "done") and not it.get("optional")
                    and it.get("km") not in (None, 0)),
        "kmLastWeek": ((((g.get("week") or {}).get("cycle") or {}).get("weeks") or [{}] * 2)[-2] or {}).get("km"),
        "strength": len(best or []) + (st.get("done") or 0), "strengthTarget": st.get("target"),
        "rides": len(rides), "rideMin": sum(it["min"][1] for d in rides for it in items[d] if it["kind"] == "ride"),
    })


def _why_strength(d, hard_set, long_day, races, all_races, last_s, ill) -> str:
    if d in races or any(0 <= (r - d).days <= 3 for r in all_races):
        return "Tři dny před závodem bez posilování."
    if d == long_day:
        return "V den dlouhého běhu bez posilování."
    if (d + timedelta(days=1)) in hard_set:
        return "Posilování ne den před tvrdým nebo dlouhým během."
    if last_s and (d - last_s).days < 2:
        return "Posilování aspoň 48 hodin od toho posledního."
    if ill:
        return "Možný začátek nemoci — první dva dny bez posilování."
    return "Na tento den se posilování podle pravidel nehodí."


def _pin_status(p: dict, its: list, why: str | None) -> dict:
    """Did the runner's change land as asked: ok, mod (smaller / B instead of A) or no (+ why)."""
    t = p["type"]
    out = {"type": t, "status": "no", "why": why, "km": p.get("km"), "min": p.get("min")}
    if t == "volno":
        ok = all(it["kind"] == "rest" for it in its)
        out["status"] = "ok" if ok else "no"
        return out
    if t in PIN_RUN:
        hit = next((it for it in its if it["kind"] == "run" and it.get("type") == t), None)
        if hit is None:
            out["why"] = why or "Pod stropy kapacity na tento den už běh nezbývá."
            return out
        asked = p.get("km")
        got = (hit.get("km") or {}).get("hi") or 0
        out["status"] = "mod" if (asked and got < 0.95 * float(asked)) or why else "ok"
        if out["status"] == "mod" and not why:
            out["why"] = "Kratší, než jste chtěli — víc nedovolí týdenní cíl nebo strop kapacity."
        return out
    kind = {"kolo": "ride", "voda": "swim", "posilování": "strength"}[t]
    hit = next((it for it in its if it["kind"] == kind), None)
    if hit is None:
        out["why"] = why or "Na tento den se to podle pravidel týdne nevejde."
        return out
    out["status"] = "mod" if why else "ok"
    return out


COACH_VERDICT = {"ok": "sedí", "mod": "sedí s úpravou", "no": "dnes raději ne"}
COACH_TYPE = {"easy": "lehký", "recovery": "regenerace", "long": "dlouhý", "quality": "kvalitní", "hills": "kvalitní"}


def _coach_week(coach: dict, out: dict, days: list, today: date, items: dict, finish):
    """The week as the coach planned it: every session with its verdict and the change the
    app suggests (metrics/coach_plan.py); what was run on the days behind."""
    from . import coach_plan as CP
    by = {d["date"]: d for d in coach["eval"].get("days") or []}
    out["mode"] = "coach"
    out["headline"] = "Týden podle plánu trenéra" + (f" ({coach['name']})" if coach.get("name") else "")
    over = (coach["eval"].get("week") or {}).get("overDays") or []
    if over:
        out["notes"].append("Nad bezpečnými limity: " + ", ".join(WD_LONG[_d(x).weekday()] for x in over)
                            + " — u dne je upravená verze, rozhoduje trenér.")
    if not coach.get("hasWeek"):
        out["notes"].append("Na tento týden zatím není plán od trenéra — vložte ho v Tréninku. Do té doby platí jen bezpečnostní limity.")
    for d in days:
        day = by.get(d.isoformat()) or {}
        if d < today:
            continue
        items[d] = []
        for s in day.get("sessions") or []:
            k = s["kind"]
            note = None
            if s.get("verdict") in COACH_VERDICT:
                bits = [CP.change_txt(c) for c in ((s.get("fit") or {}).get("changes") or [])]
                note = COACH_VERDICT[s["verdict"]] + (f": {', '.join(bits)}" if bits and s["verdict"] == "mod" else "")
                if s.get("why"):
                    note += f" — {s['why'][0].rstrip('.')}"
            if s.get("status") in ("done", "partial", "more"):
                items[d].append({"kind": "done", "label": "Odběhnuto", "km": (s.get("act") or {}).get("km")})
            elif k == "rest":
                items[d].append({"kind": "rest", "label": "Volno", "note": None})
            elif CP.KINDS[k]["sport"] == "run" and k != "race":
                km = s.get("km") or 0
                fit_km = (s.get("fit") or {}).get("km") if s.get("verdict") == "mod" else None
                items[d].append({"kind": "run", "type": COACH_TYPE.get(k, "lehký"), "label": s.get("title") or s["label"],
                                 "km": {"lo": _r(fit_km if fit_km is not None and fit_km < km else km), "hi": _r(km)},
                                 "durationMin": None, "hr": None, "zones": None, "pace": None,
                                 "z4": {"lo": _r(s.get("z4"), 0), "hi": _r(s.get("z4"), 0)} if s.get("z4") else None,
                                 "session": s.get("intervals"), "descentMax": None, "ascentMax": None, "optional": False,
                                 "strides": False, "note": note})
            elif k == "race":
                items[d].append({"kind": "race", "label": s.get("title") or s["label"], "km": s.get("km"), "note": note})
            elif k in ("ride", "swim"):
                m = s.get("min")
                items[d].append({"kind": k, "label": s.get("title") or s["label"], "min": [m, m] if m else None,
                                 "hr": None, "zones": None, "optional": False, "note": note})
            else:
                items[d].append({"kind": "rest", "label": s.get("title") or s["label"], "note": note})
        if not items[d]:
            items[d].append({"kind": "rest", "label": "Nic v plánu", "note": None})
    return finish()


def note(p: dict | None) -> str | None:
    """The sheet's rule-based rating + tip (the model doesn't write this one: its numbers must match the plan)."""
    if not p or not p.get("totals"):
        return (p or {}).get("override") or None
    t = p["totals"]
    hard = [d for d in p["days"] for it in d["items"] if it.get("type") == "kvalitní" and not d["past"]]
    long_ = [d for d in p["days"] for it in d["items"] if it.get("type") == "dlouhý" and not d["past"]]
    bits = [f"Týden na {_cz(t['km'])} km" + (f" z cíle {_cz(t['kmBudget'])} km" if t.get("kmBudget") else "")]
    if hard:
        bits.append(f"tvrdý trénink {', '.join(WD_IN[_d(d['date']).weekday()] for d in hard)}")
    if long_:
        bits.append(f"dlouhý běh {WD_IN[_d(long_[0]['date']).weekday()]}")
    if t.get("strength"):
        bits.append(f"{t['strength']}× posilování")
    if t.get("rides"):
        bits.append(f"{t['rides']}× kolo")
    tip = ("Nejdůležitější jsou lehké dny opravdu lehké — tvrdé tréninky pak dají víc a tělo zůstane pod stropem kapacity."
           if hard else "Držte lehké běhy v Z2 — objem roste bezpečně a tělo zůstává pod stropem kapacity.")
    return ", ".join(bits) + ". " + tip


# ---------------------------------------------------------------- changing a day (owner request 2026-10-26)
# what the sheet offers in place of a type the day can't take, nearest first
FALLBACK = {"kvalitní": ("lehký", "regenerace", "kolo", "volno"), "dlouhý": ("lehký", "regenerace", "kolo", "volno"),
            "lehký": ("regenerace", "kolo", "voda", "volno"), "regenerace": ("lehký", "kolo", "voda", "volno"),
            "kolo": ("voda", "regenerace", "volno"), "voda": ("kolo", "regenerace", "volno"),
            "posilování": ("lehký", "kolo", "volno"), "volno": ()}


def _it_txt(it: dict) -> str:
    k = it.get("kind")
    if k == "run":
        km = it.get("km") or {}
        lo, hi = km.get("lo"), km.get("hi")
        return f"{TYPE_LABEL.get(it.get('type'), it.get('label'))} " + (
            f"{_cz(lo)}–{_cz(hi)} km" if lo and hi and abs(hi - lo) >= 0.1 else f"{_cz(hi or 0)} km")
    if k in ("ride", "swim"):
        m = it.get("min") or [0, 0]
        return f"{it.get('label')} {m[0]}–{m[1]} min" if m[0] != m[1] else f"{it.get('label')} {m[1]} min"
    if k == "strength":
        return f"Posilování {it.get('session') or ''}".strip()
    if k == "done":
        return f"{it.get('label')} {_cz(it['km'])} km" if it.get("km") else it.get("label") or ""
    return it.get("label") or ""


def _day_txt(day: dict) -> str:
    return " + ".join(_it_txt(it) for it in day["items"] if not (it.get("kind") == "rest" and len(day["items"]) > 1))


def changes(old: dict | None, new: dict | None, skip=()) -> list:
    """What else the change moves in the week: one line per day whose sessions differ."""
    if not old or not new or not old.get("days") or not new.get("days"):
        return []
    out = []
    for a_, b_ in zip(old["days"], new["days"]):
        if a_["past"] or a_["date"] in skip:
            continue
        ta, tb = _day_txt(a_), _day_txt(b_)
        if ta != tb:
            d = _d(a_["date"])
            out.append({"date": a_["date"], "wd": a_["wd"], "text": f"{a_['wd']} {d.day}. {d.month}.: {ta} → {tb}"})
    return out


def _with_today(a: dict, typ: str | None, km=None) -> dict:
    """The assessment as if today were `typ` (today's change is applied by guidance; this is its preview)."""
    import copy
    a2 = dict(a)
    g = copy.deepcopy(a.get("guidance") or {})
    if typ:
        t = (g.get("types") or {}).get(typ) or {}
        g["type"], g["pin"] = typ, {"type": typ, "applied": True}
        k = t.get("km") if isinstance(t.get("km"), dict) else None
        if km and k and k.get("hi") and typ in PIN_RUN:
            hi = min(float(km), k.get("pinMax") or k["hi"])     # review 2026-10-30 N2: as guidance caps it
            k["hi"], k["lo"] = _r(hi), _r(min(k.get("lo") or hi, 0.85 * hi))
    a2["guidance"] = g
    return a2


def simulate(a: dict, today: date, program: dict | None, pins: dict) -> dict | None:
    t = pins.get(today.isoformat())
    rest = {k: v for k, v in pins.items() if k != today.isoformat()}
    if t:
        return build(_with_today(a, t["type"], t.get("km")), today, program, rest)
    return build(a, today, program, rest)


def _main(day: dict | None) -> dict | None:
    """The day's session the runner would move: a run first, then a ride / swim / strength."""
    if not day:
        return None
    for kinds in (("run",), ("ride", "swim"), ("strength",)):
        it = next((i for i in day["items"] if i["kind"] in kinds and not i.get("optional")), None)
        if it:
            return it
    return None


def _main_pin(it: dict) -> dict | None:
    if it["kind"] == "run":
        return {"type": it.get("type"), "km": (it.get("km") or {}).get("hi")}
    if it["kind"] in ("ride", "swim"):
        return {"type": "kolo" if it["kind"] == "ride" else "voda", "min": (it.get("min") or [0, 0])[1]}
    if it["kind"] == "strength":
        return {"type": "posilování", "session": it.get("sessionKey")}
    return None


def _status(a, today, program, pins, day_iso, pin):
    """(status, why, plan) of putting `pin` on the day."""
    p2 = {**pins, day_iso: pin}
    plan = simulate(a, today, program, p2)
    if day_iso == today.isoformat():
        g = (a.get("guidance") or {})
        t = (g.get("types") or {}).get(pin["type"]) or {}
        if g.get("done"):
            return "no", "Dnešní trénink už máte hotový.", plan
        if not t.get("allowed"):
            return "no", t.get("why") or (g.get("override") or {}).get("title") or "Podle ranních dat to dnes nejde.", plan
        if g.get("override") and pin["type"] != "volno":
            return "no", g["override"].get("title"), plan
        return "ok", None, plan
    st = ((plan or {}).get("pins") or {}).get(day_iso) or {"status": "no", "why": None}
    return st["status"], st.get("why"), plan


def _range(a, today, program, pins, day_iso, typ, plan) -> dict | None:
    """The slider: from the shortest sensible size to the most the day can take as asked."""
    g = a.get("guidance") or {}
    x = g.get("planCtx") or {}
    easy = x.get("easyKm") or 6.0
    if typ in ("lehký", "regenerace", "dlouhý"):
        lo = max(MIN_RUN_KM, 0.5 * easy) if typ != "dlouhý" else 1.2 * easy
        if day_iso == today.isoformat():
            k = ((g.get("types") or {}).get(typ) or {}).get("km") or {}
            hi = k.get("pinMax") or k.get("hi")
        else:
            big = simulate(a, today, program, {**pins, day_iso: {"type": typ, "km": 999}})
            day = next((d for d in (big or {}).get("days") or [] if d["date"] == day_iso), None)
            it = next((i for i in (day or {}).get("items") or [] if i["kind"] == "run" and i.get("type") == typ), None)
            hi = ((it or {}).get("km") or {}).get("hi")
        cur = next((i for i in next((d for d in (plan or {}).get("days") or [] if d["date"] == day_iso), {"items": []})["items"]
                    if i["kind"] == "run"), None)
        lo, hi = math.ceil(lo * 2) / 2, math.floor((hi or 0) * 2) / 2          # the slider's 0.5 km steps reach both ends
        if not hi or hi < lo:
            return None
        val = ((cur or {}).get("km") or {}).get("hi") or hi
        return {"unit": "km", "lo": lo, "hi": hi, "step": 0.5, "value": min(hi, max(lo, round(val * 2) / 2))}
    if typ in ("kolo", "voda") and day_iso != today.isoformat():
        big = simulate(a, today, program, {**pins, day_iso: {"type": typ, "min": 999}})
        day = next((d for d in (big or {}).get("days") or [] if d["date"] == day_iso), None)
        it = next((i for i in (day or {}).get("items") or [] if i["kind"] in ("ride", "swim")), None)
        hi = ((it or {}).get("min") or [0, 0])[1]
        hi = int(hi // 5 * 5) if hi else 0
        if not hi or hi < CROSS_MIN:
            return None
        cur = next((i for i in next((d for d in (plan or {}).get("days") or [] if d["date"] == day_iso), {"items": []})["items"]
                    if i["kind"] in ("ride", "swim")), None)
        return {"unit": "min", "lo": CROSS_MIN, "hi": hi, "step": 5, "value": ((cur or {}).get("min") or [0, hi])[1]}
    return None


def options(a: dict | None, today: date, program: dict | None, pins: dict, day_iso: str) -> dict:
    """Everything the 'Změnit trénink' sheet shows for one day: each type with its verdict
    (ok / mod / no + why), its size, the slider range, what else in the week it moves, the
    alternatives for a type the day can't take, and the days its current session can move to."""
    base = simulate(a, today, program, pins) if a else None
    d0 = _d(day_iso)
    if not base or not base.get("totals") or d0 < today or d0 > _d(base["weekStart"]) + timedelta(days=6):
        return {"date": day_iso, "editable": False, "why": "Tento den se změnit nedá.", "types": [], "moves": []}
    day = next(d for d in base["days"] if d["date"] == day_iso)
    if any(it["kind"] in ("race", "done") for it in day["items"]) or (d0 == today and (a.get("guidance") or {}).get("done")):
        return {"date": day_iso, "editable": False, "why": "Den se závodem nebo s hotovým tréninkem se nemění.",
                "types": [], "moves": []}
    others = {k: v for k, v in pins.items() if k != day_iso}
    cur = _main(day)
    mp = _main_pin(cur) if cur else None
    res = {}
    for t in PIN_TYPES:
        pin = {k: v for k, v in mp.items() if v is not None} if (mp and mp["type"] == t) else {"type": t}  # the same type keeps its size
        st, why, plan = _status(a, today, program, others, day_iso, pin)
        nd = next((d for d in (plan or {}).get("days") or [] if d["date"] == day_iso), None)
        res[t] = {"type": t, "label": TYPE_LABEL[t], "status": st, "why": why,
                  "text": _day_txt(nd) if nd and st != "no" else None,
                  "range": _range(a, today, program, others, day_iso, t, plan) if st != "no" else None,
                  "changes": changes(base, plan, skip=(day_iso,)) if st != "no" else [], "alts": []}
    future = [d for d in base["days"] if not d["past"] and d["date"] != day_iso
              and not any(it["kind"] in ("race", "done") for it in d["items"]) and d["date"] != today.isoformat()]
    for t, r in res.items():
        if r["status"] != "no":
            continue
        alts = [{"kind": "type", "type": f, "label": TYPE_LABEL[f], "text": res[f]["text"]}
                for f in FALLBACK[t] if res[f]["status"] != "no"][:1]
        for d in future:
            if len(alts) >= 3:
                break
            st, _w, _p = _status(a, today, program, others, d["date"], {"type": t})
            if st != "no" and others.get(d["date"]) is None:
                alts.append({"kind": "day", "type": t, "label": TYPE_LABEL[t], "date": d["date"], "wd": d["wd"], "wdLong": d["wdLong"]})
        r["alts"] = alts
    moves = []
    if mp and mp["type"] in PIN_TYPES:
        for d in future:
            if others.get(d["date"]) is not None:
                continue
            p2 = {**others, day_iso: {"type": "volno"}}
            st, why, plan = _status(a, today, program, p2, d["date"], mp)
            moves.append({"date": d["date"], "wd": d["wd"], "wdLong": d["wdLong"], "status": st, "why": why,
                          "changes": changes(base, plan, skip=(day_iso, d["date"])) if st != "no" else []})
    return {"date": day_iso, "editable": True, "today": d0 == today, "current": _day_txt(day),
            "currentType": (mp or {}).get("type") or ("volno" if all(it["kind"] == "rest" for it in day["items"]) else None),
            "pinned": day_iso in pins, "types": [res[t] for t in PIN_TYPES], "moves": moves}


def preview(a: dict | None, today: date, program: dict | None, pins: dict, day_iso: str, pin: dict,
            move_to: str | None = None) -> dict:
    """One concrete change (with the slider's size, or a move): its verdict and what else it moves."""
    base = simulate(a, today, program, pins) if a else None
    others = {k: v for k, v in pins.items() if k != day_iso}
    if move_to:
        p2 = {**{k: v for k, v in others.items() if k != move_to}, day_iso: {"type": "volno"}}
        st, why, plan = _status(a, today, program, p2, move_to, pin)
        target = move_to
    else:
        st, why, plan = _status(a, today, program, others, day_iso, pin)
        target = day_iso
    nd = next((d for d in (plan or {}).get("days") or [] if d["date"] == target), None)
    return {"status": st, "why": why, "text": _day_txt(nd) if nd else None,
            "changes": changes(base, plan, skip=(day_iso, target)) if st != "no" else []}
