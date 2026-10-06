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
The splits are the product team's working assumptions on the cited principles."""
from datetime import date, timedelta
from itertools import combinations

from .guidance import (CROSS_MIN, HARD_Z4_MIN, KOLO_MAX, LONG_SHARE, MIN_RUN_KM, NOVICE_LONG, NOVICE_Z4,
                       READY_QUALITY, TYPE_LABEL, WD_IN, Z4_SESSION_MAX)

WD = ("po", "út", "st", "čt", "pá", "so", "ne")
WD_LONG = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
RUN_TYPES = ("regenerace", "lehký", "dlouhý", "kvalitní")
# usual run days when the runner has no pattern yet (Mon = 0)
DEFAULT_RUN_DAYS = {1: (5,), 2: (1, 5), 3: (1, 3, 6), 4: (1, 3, 5, 6), 5: (0, 1, 3, 5, 6), 6: (0, 1, 2, 3, 5, 6),
                    7: (0, 1, 2, 3, 4, 5, 6)}
STRENGTH_MIN, STRENGTH_RPE = (30, 45), 6.5
QUALITY_SYS = 0.5          # a hard minute's all-sport load above an easy one, share of a Z4 minute (working assumption)
SESSION_NAME = {"A": "A · Síla (těžší)", "B": "B · Odolnost"}


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
             "z4": z4, "session": session_text(z4["hi"], 0) if (typ == "kvalitní" and z4 and z4.get("hi")) else None,
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
    if w.get("novice"):
        return "Prvních 6 týdnů · opatrné navyšování"
    return "Cyklus nastavíme po 4 týdnech dat · cílem je vaše kapacita"


def build(a: dict | None, today: date, program: dict | None = None) -> dict | None:
    """The calendar week of `today`, day by day. `program` = the active Runner's
    must-have {name, due: "A"|"B", last: iso|None} or None."""
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
           "notes": notes, "rules": [], "override": None}

    def finish(totals=None):
        out["days"] = [{"date": d.isoformat(), "wd": WD[d.weekday()], "wdLong": WD_LONG[d.weekday()],
                        "today": d == today, "past": d < today, "items": items[d]} for d in days]
        out["totals"] = totals
        return out

    # ---- a stop: no running plan, only what doesn't hurt
    ov = g.get("override")
    if ov or x.get("ill"):
        out["override"] = ov["title"] if ov else "Hlásíte nemoc — tento týden nejdřív odpočinek"
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
        notes.append("Na plán týdne zatím chybí data o vaší týdenní kapacitě — stačí pár týdnů běhů.")
        for d in future:
            items[d].append({"kind": "rest", "label": "Podle ranního doporučení", "note": None})
        return finish()
    left = max(0.0, budget - (vol.get("done") or 0) - today_km)

    # ---- run days: the runner's own pattern
    n_runs = int(round(pat.get("runsPerWeek") or 0)) or 3
    usual = set(pat.get("runDays") or []) or set(DEFAULT_RUN_DAYS[min(7, max(1, n_runs))])
    before = sum(1 for d in days if d < today and pvol.get(d.isoformat()))
    allowed = max(0, max(n_runs, before + int(today_run or bool(g.get("done")))) - before - int(today_run or bool(g.get("done"))))
    run_days = [d for d in future if d.weekday() in usual and d not in races]
    long_wd = pat.get("longDay")
    hard_wd = set(pat.get("hardDays") or [])

    lday = ws + timedelta(days=long_wd) if long_wd is not None else None
    if lday in future and lday not in run_days and lday not in races:
        run_days = sorted(run_days + [lday])         # the usual long-run day even when it isn't a usual run day

    def neighbours(d, pool):
        return sum(1 for e in pool if abs((e - d).days) == 1) + (1 if (d - today).days == 1 and (today_run or g.get("done")) else 0)
    while len(run_days) > allowed:
        drop = max((d for d in run_days if d.weekday() != long_wd), key=lambda d: (neighbours(d, run_days), d), default=None)
        run_days.remove(drop if drop is not None else run_days[-1])
    if len(run_days) < allowed:
        for wd in DEFAULT_RUN_DAYS[min(7, max(1, n_runs))]:
            d = ws + timedelta(days=wd)
            if len(run_days) >= allowed:
                break
            if d in future and d not in run_days and d not in races:
                run_days.append(d)
        run_days.sort()

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

    # ---- the long run
    long_done = typ == "dlouhý" or any((pvol.get(d.isoformat()) or 0) >= 1.25 * easy for d in days if d < today)
    long_day = None
    L = min(ceil, max(1.2 * easy, LONG_SHARE * budget))
    if x.get("novice") and x.get("longest30"):
        L = min(L, NOVICE_LONG * x["longest30"])
    if not long_done and len(run_days) + before + int(today_run) >= 3 and L >= 1.2 * easy:
        cand = [d for d in run_days if ok_long(d)]
        long_day = next((d for d in cand if d.weekday() == long_wd), None)
        if long_day is None and long_wd is None:
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
    nq = max(0, nq - hard_done)
    anchors = {d for d in (_d(x["lastHard"]) if x.get("lastHard") else None, long_day) if d}
    anchors |= {_d(h) for h in x.get("hardThisWeek") or []} | set(races)
    if typ in ("kvalitní", "závod") or x.get("todayHard"):
        anchors.add(today)
    q_days = []
    for _ in range(nq):
        cand = [d for d in run_days if d != long_day and d not in q_days and ok_hard(d)
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
    easy_days = [d for d in run_days if d != long_day and d not in q_days]
    q_km = min(ceil, easy)
    need = (L if long_day else 0) + q_km * len(q_days)
    if need > left:
        easy_days = []
        f = left / need if need else 0
        L, q_km = L * f, q_km * f
        if long_day and L < 1.2 * easy:
            easy_days.append(long_day)
            long_day = None
        need = (L if long_day else 0) + q_km * len(q_days)
    rem = max(0.0, left - need)
    while easy_days and rem / len(easy_days) < min_run:
        easy_days.remove(max(easy_days, key=lambda d: (neighbours(d, run_days), d)))
    e_cap = min(ceil, 1.5 * easy, 0.9 * L if long_day else 1e9)
    e_km = min(e_cap, rem / len(easy_days)) if easy_days else 0.0
    plan_km = {d: e_km for d in easy_days}
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
        if d in q_days or d == long_day:
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
        busy = set(plan_km) | {today}
        hard_next = set(q_days) | ({long_day} if long_day else set()) | set(races)
        cand = [d for d in future if d not in busy and d not in races and (d + timedelta(days=1)) not in hard_next]
        rest_after = sum(1 for d in days if d not in busy and d > today) - 1
        cand = [d for d in cand if room_at(d) >= min_run]
        if cand and rest_after >= 1:
            extra = min(cand, key=lambda d: (neighbours(d, list(busy)), d))
            km = min(leftover, 0.8 * easy, ceil, room_at(extra))
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
        kind = "dlouhý" if d == long_day else "kvalitní" if d in q_days else "lehký"
        zq = None
        if kind == "kvalitní":
            zq = {"lo": _r(0.6 * z4[d], 0), "hi": _r(z4[d], 0)}
        items[d].append(_run(kind, plan_km[d], types, x, z4=zq,
                             sess=session_text(z4[d], q_days.index(d) + (1 if typ == "kvalitní" else 0)) if kind == "kvalitní" else None,
                             desc=hills("descent", d), asc=hills("ascent", d), optional=d == extra,
                             strides=d == strides_day,
                             note=("4–6 stupňovaných rovinek po 15–20 s na konci (ne naplno) — pravidelný kontakt "
                                   "s rychlostí chrání zadní stehenní svaly." if d == strides_day else None)))
    for d, r in races.items():
        if d > today:
            items[d].append({"kind": "race", "label": r.get("name") or "Závod", "km": r.get("km"), "note": None})

    # ---- strength
    st = g.get("strength") or {}
    n_s = max(0, (st.get("target") or 0) - (st.get("done") or 0) - int(bool(st.get("today"))))
    pos_t = types.get("posilování") or {}
    hard_set = set(q_days) | ({long_day} if long_day else set()) | set(races) | (
        {today} if (typ in ("kvalitní", "dlouhý", "závod") or x.get("todayHard")) else set())
    if x.get("lastHard"):
        hard_set.add(_d(x["lastHard"]))
    hard_set |= {_d(k) for k, v in pvol.items() if (v or 0) >= 1.25 * easy}      # a long run in the last days
    last_s = _d(program["last"]) if (program and program.get("last")) else (
        today - timedelta(days=st["lastAge"]) if st.get("lastAge") is not None else None)
    s_cand = ([today] if (pos_t.get("allowed") and not st.get("today")) else []) + future
    due = (program or {}).get("due") or "A"
    seq0 = [due, "B" if due == "A" else "A"]

    def s_ok(d, kind):
        if (d + timedelta(days=1)) in hard_set or d == long_day or d in races:
            return False
        if any(0 <= (r - d).days <= 3 for r in all_races) or (early(d) and x.get("illWatch")):
            return False
        if last_s and (d - last_s).days < 2:
            return False
        return not (kind == "A" and (d in hard_set or (d - timedelta(days=1)) in hard_set))

    def rest_days(extra_busy=()):
        return sum(1 for d in days if d >= today and d not in extra_busy
                   and all(it["kind"] == "rest" for it in items[d]))
    best, best_sc, swapped = None, None, False
    for n in range(n_s, 0, -1):
        for combo, (order, seq) in ((c_, o_) for c_ in combinations(s_cand, n) for o_ in enumerate((seq0, seq0[::-1]))):
            if any((b - a_).days < 2 for a_, b in zip(combo, combo[1:])):
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
    if swapped:
        notes.append("Těžší silová A se tento týden nevejde mezi tvrdé dny — místo ní lehčí B, A přijde příště.")
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
        cand = [d for d in future if not items[d] and d not in races and (d + timedelta(days=1)) not in races]
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
        notes.append(f"Návrat po zranění — bez intenzity do {_d(x['noQualityUntil']).day}. {_d(x['noQualityUntil']).month}.")
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
        "strength": len(best or []) + (st.get("done") or 0) + int(bool(st.get("today"))), "strengthTarget": st.get("target"),
        "rides": len(rides), "rideMin": sum(it["min"][1] for d in rides for it in items[d] if it["kind"] == "ride"),
    })


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
