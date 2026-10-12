"""The runner facts packet for the assistant: engine output only, sliced by the
question's intent (selector.py). Same privacy rule as the Phase 1 packets
(coach_facts.py): derived values only — no name, e-mail, place, coordinates,
activity titles or free-text notes leave the server. Numbers are Czech-formatted
so the model copies them instead of recomputing."""
from datetime import date, timedelta

from .. import models
from ..metrics import coach_facts as F
from ..metrics import coach_plan as CP
from ..metrics import engine as E
from ..metrics import guidance as G
from ..metrics import outlook as O

PART_LABEL = {"hrv": "HRV pod normou", "rhr": "klidový tep nad normou", "sleep": "kratší spánek než obvykle (3 noci)",
              "sleepQuality": "víc bdění v noci než obvykle (efektivita spánku, 3 noci)",
              "soreness": "svalová bolest z check-inu", "fatigue": "únava z check-inu", "stress": "stres mimo trénink",
              "dayStress": "zvýšený tep v klidu včera", "sleepSelf": "horší noc podle check-inu",
              # UX audit F14 — parts added after the morning; an unknown key is left out, never printed
              "session": "dnešní trénink", "dayLoad": "pohyb mimo trénink nad obvyklý den",
              "dayStressNow": "zvýšený tep v klidu dnes"}
MECH_IDS = {"tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv", "stiffness"}
CH_LABEL = {"volume": "objem", "intensity": "intenzita", "descent": "klesání", "ascent": "stoupání",
            "systemic": "celková zátěž", "strength": "silová zátěž"}


def _state(db, rid, a) -> dict:
    d = F.daily_facts(db, rid, a)
    out = {"date": d["date"], "weekday": d["weekday"], "state": d["state"], "referral": d["referral"],
           "signals": d["signals"]}
    scr = a.get("screening") or {}
    flags = {}
    if scr.get("boneStress"):
        flags["boneStressWarning"] = {"site": scr["boneStress"]["site"], "what": scr["boneStress"]["what"]}
    if scr.get("bonePain"):
        flags["bonePain"] = {"site": scr["bonePain"]["site"], "pain": scr["bonePain"]["pain"],
                             "repeated": scr["bonePain"]["repeated"]}
    if scr.get("ill"):
        flags["illToday"] = True
        if scr["ill"].get("systemic") is not None:
            flags["illBelowNeck"] = bool(scr["ill"]["systemic"])
    if scr.get("illSignal"):
        flags["watchIllnessSignal"] = {"signs": scr["illSignal"]["kinds"], "since": scr["illSignal"]["since"],
                                       "answer": scr["illSignal"].get("answer")}
    if a.get("cluster"):
        flags["fatigueIllnessCluster"] = a["cluster"]["parts"]
    if flags:
        out["safety"] = flags
    return out


def _types(a) -> dict | None:
    g = a.get("guidance") or {}
    types = g.get("types") or {}
    if not types:
        return None
    out = {}
    for k, t in types.items():
        row = {"label": t.get("label"), "allowed": bool(t.get("allowed"))}
        if not t.get("allowed") and t.get("why"):
            row["whyNot"] = F.cz_text(t["why"])
        km = t.get("km") if isinstance(t.get("km"), dict) else ({"lo": t["km"], "hi": t["km"]} if isinstance(t.get("km"), (int, float)) else {})  # race day: one number
        if t.get("allowed") and (km.get("hi") or 0) > 0:
            row["km"] = f"{G._cz(km.get('lo'), 1)}–{G._cz(km.get('hi'), 1)} km"
        if t.get("allowed") and t.get("hr"):
            row["hr"] = f"{t['hr'][0]}–{t['hr'][1]} tepů/min"
        if t.get("durationMin") and t.get("cross"):
            row["durationMin"] = f"{t['durationMin'][0]}–{t['durationMin'][1]} min"
        if t.get("rpeTarget"):
            row["rpeTarget"] = t["rpeTarget"]
        out[k] = row
    return out


def _today_extra(a) -> dict:
    g = a.get("guidance") or {}
    out = {}
    if g.get("heat"):
        out["heat"] = {"feelsMaxC": g["heat"]["feelsMax"], "hotRuns14d": g["heat"]["hot14"], "stage": g["heat"]["stage"]}
    if g.get("hardWeek"):
        out["hardSessionsLast7d"] = {"done": g["hardWeek"]["done"], "weeklyCap": g["hardWeek"]["cap"]}
    s = g.get("strength") or {}
    if s:
        out["strengthThisWeek"] = {"done": s.get("done"), "target": s.get("target"),
                                   "lastDaysAgo": s.get("lastAge"), "newBlock": bool(s.get("newBlock"))}
    pat = g.get("pattern") or {}
    if pat:
        out["pattern"] = {"runDays": pat.get("runDayNames"), "longRunDay": pat.get("longDayName"),
                          "hardDays": pat.get("hardDayNames"), "runsPerWeek": pat.get("runsPerWeek"),
                          "easyKm": G._cz(pat.get("easyKm"), 1) if pat.get("easyKm") else None}
    return out


LIMITED_BY = {"week": "zbytek týdenního cíle (kalendářní týden od pondělí)", "7d": "nevstřebaná zátěž posledních dní proti týdenní kapacitě",
              "run": "strop jednoho běhu", "systemic": "celková zátěž ze všech sportů",
              "mechanics": "mechanika nad vaším prahem"}


def _why_today_max(a, today) -> None:
    """Today's cap is the smallest of several limits. The week budget goes to the
    model as one plain sentence per channel, with the binding limit and the rolling
    7-day room named, so it cannot read "today's cap" as "what is left this week"."""
    chans = ((a.get("guidance") or {}).get("week") or {}).get("channels") or {}
    wb = (today or {}).get("weekBudget")
    if not isinstance(wb, dict):
        return
    lines = []
    for key, row in wb.items():
        c = chans.get(key) or {}
        u = row.get("unit") or ""
        parts = [f"{row.get('label')} ({u}): týdenní cíl {row.get('weekTarget')}",
                 f"tento týden (od pondělí) hotovo {row.get('doneThisWeek')}", f"do neděle zbývá {row.get('leftThisWeek')}"]
        if row.get("todayMax") not in (None, "", "–"):
            why = LIMITED_BY.get(c.get("limitedBy"))
            if why and c.get("limitedBy") == "systemic" and c.get("bound"):
                why += " — její " + ("týdenní cíl (plán, ne bezpečnostní strop)" if c["bound"] == "plan"
                                     else "nevstřebaná zátěž pod týdenním stropem")
            parts.append(f"dnešní strop {row.get('todayMax')}" + (f" (určuje ho {why})" if why else ""))
        if c.get("bound") == "plan" and c.get("safeMax") is not None:
            parts.append(f"bez týdenního cíle by bezpečnostní limity dovolily {G._cz(c['safeMax'], 1 if key == 'volume' else 0)}")
        if c.get("left7") is not None:
            parts.append(f"pod stropem nevstřebané zátěže zbývá {G._cz(c['left7'], 1 if key == 'volume' else 0)}")
        lines.append(", ".join(parts) + ".")
    today["weekBudget"] = lines


def _readiness(a) -> dict:
    out = F._recovery(a)
    cr = a.get("readiness") or (a.get("capacity") or {}).get("readiness") or {}
    parts = {PART_LABEL[k]: f"{round(v * 100)} %" for k, v in (cr.get("parts") or {}).items() if v and v > 0.05 and k in PART_LABEL}
    if parts:
        out["whatLowersReadiness"] = parts
    hab = (cr.get("inputs") or {}).get("sleepHabit")
    if hab:                                      # v0.11.0 — a habit beside readiness, not inside it
        out["sleepHabit"] = (f"dlouhodobě spí v průměru {G._cz(hab['avg'], 1)} h, {hab['under']} z {hab['n']} nocí pod 7 h "
                             "(do připravenosti se nepočítá, ta sleduje odchylky od vlastní normy)")
    return out


def _load(a) -> dict:
    out = F._load(a)
    cap = (a.get("capacity") or {}).get("channels") or {}
    for key in ("systemic", "strength"):
        c = cap.get(key) or {}
        wk = c.get("week") or {}
        if wk.get("cap"):
            out.setdefault("vsCapacity", {})[key] = {"label": c.get("label"), "unit": c.get("unit"),
                                                     "last7": G._cz(wk.get("now"), 0), "weeklyCapacity": G._cz(wk.get("cap"), 0),
                                                     "ratio": G._cz(wk.get("ratio"), 2)}
    g = a.get("guidance") or {}
    wk = g.get("week") or {}
    if wk:
        out["weekMode"] = F.WEEK_MODE.get(wk.get("mode"), wk.get("mode"))
        out["cycleWeek"] = (wk.get("cycle") or {}).get("pos")
    return out


def _runs(db, rid, a, sel) -> dict:
    acts = [x for x in E.acts(db, rid) if x.started_at]
    acts.sort(key=lambda x: x.started_at, reverse=True)
    rel = {r["date"]: r for r in ((a.get("capacity") or {}).get("relativeEffort") or {}).get("runs") or []}

    def row(x):
        r = rel.get(x.started_at[:10]) or {}
        w = x.weather_json or {}
        return {"date": F.cz_date(x.started_at), "daysAgo": (E.today_date() - date.fromisoformat(x.started_at[:10])).days,
                "km": G._cz(x.distance_km, 1) if x.distance_km else None, "pace": F.pace(x.pace_s_km),
                "avgHr": round(x.avg_hr) if x.avg_hr else None,
                "ascentM": round(x.ascent_m) if x.ascent_m else None, "descentM": round(x.descent_m) if x.descent_m else None,
                "hrVsUsualForPace": (f"{'+' if r['hrDelta'] > 0 else ''}{r['hrDelta']} tepů" if r.get("hrDelta") is not None else None),
                "effortVsUsual": r.get("band"), "hot": bool(w.get("hot")),
                "feelsC": w.get("feelsC") if w.get("precision") == "hour" else None}
    pick = None
    if sel.get("runPick", "") and str(sel["runPick"]).startswith("id:"):
        pick = next((x for x in acts if str(x.id) == str(sel["runPick"])[3:]), None)
    elif sel.get("runDay"):
        pick = next((x for x in acts if x.started_at[:10] == sel["runDay"]), None)
    elif sel.get("runPick") == "long":
        recent = [x for x in acts if (E.today_date() - date.fromisoformat(x.started_at[:10])).days <= 14]
        pick = max(recent, key=lambda x: x.distance_km or 0, default=None)
    out = {"recentRuns": [row(x) for x in acts[:5]]}
    if pick is not None:
        out["askedRun"] = row(pick)
    elif sel.get("runDay"):
        out["askedRun"] = f"V den {F.cz_date(sel['runDay'])} žádný běh nemáme."
    return out


def _plan(a) -> dict:
    out = {"races": F._races(a), "raceRecovery": F._race_recovery(a)}
    g = a.get("guidance") or {}
    wk = g.get("week") or {}
    cyc = wk.get("cycle") or {}
    if cyc:
        out["cycle"] = {"week": cyc.get("pos"), "manual": bool(cyc.get("manual"))}
    chs = wk.get("channels") or {}
    vol = chs.get("volume") or {}
    if vol:
        out["thisWeekKm"] = {"target": G._cz(vol.get("budget"), 1), "done": G._cz(vol.get("done"), 1)}
    return out


def _mechanics(a) -> dict:
    q = F.QUAD.get(a.get("quadrant"), (a.get("quadrant"), ""))
    sig = [s for s in a.get("signals") or [] if s.get("id") in MECH_IDS and (s.get("pts") or 0) > 0]
    return {"quadrant": q[0], "mechanicsScore": a.get("mech"), "flag": bool(a.get("mechFlag")),
            "signals": [{"name": s.get("name"), "value": F.cz_text(s.get("val")), "detail": F.cz_text(s.get("detail"))}
                        for s in sig[:4]]}


def _tomorrow(a) -> list | None:
    """Owner feedback 2026-10-10 — the outlook for tomorrow (guidance.outlook) as plain sentences:
    after nothing more today / the recommended session, a night like the last one or a weaker one."""
    ol = (a.get("guidance") or {}).get("outlook") or {}
    grid, presets = ol.get("grid") or {}, ol.get("presets") or []
    nights = {n["key"]: n for n in ol.get("nights") or []}
    lines = []
    for p in presets:
        if p["key"] not in ("none", "rec", "extra"):
            continue
        act = p.get("act") or {}
        what = ("dnes už nic dalšího" if p["key"] == "none" else
                f"dnes ještě {G.TYPE_LABEL.get(p.get('kind'), p.get('kind') or '').lower()} "
                + (f"{G._cz(act.get('runKm'))} km" if act.get("runKm") else f"{act.get('rideMin') or act.get('swimMin') or 0} min"))
        for nk in ("today", "weak"):
            v = (grid.get(p["key"]) or {}).get(nk)
            if not v:
                continue
            vol = v["ch"].get("volume") or {}
            lim = LIMITED_BY.get(vol.get("lim"))
            lines.append(f"Když {what} a noc {'jako dnešní' if nk == 'today' else 'slabší'} ({nights.get(nk, {}).get('score')} %): zítra "
                         + (f"běh nejvýš {G._cz(vol['max'])} km" if v["run"] and vol.get("max") is not None else "bez běhu")
                         + (f" (určuje {lim}, {'plán týdne' if vol.get('bound') == 'plan' else 'bezpečnostní limit'})" if lim else "")
                         + f", kvalitní trénink {'ano' if v['quality'] else 'ne'}.")
    rr = ol.get("restRun")
    if rr and grid.get("none", {}).get("today", {}).get("run") is False:
        lines.append(f"Bez dalšího tréninku je nejbližší den s prostorem na běh {G._dm(rr['date'])} (≈ {G._cz(rr['km'])} km).")
    return lines or None


def _coach(a) -> list | None:
    """Plán od trenéra (2026-10-12): the coach's sessions of today and the next days with the
    app's verdicts, as plain sentences — the coach's plan comes first, the app only suggests."""
    c = (a.get("guidance") or {}).get("coach") or {}
    ev = c.get("eval") or {}
    if not c.get("on"):
        return None
    who = f" ({c['name']})" if c.get("name") else ""
    lines = [f"Běžec trénuje podle plánu trenéra{who}: plán určuje trenér, aplikace hlídá bezpečnostní limity "
             "a jen doporučuje úpravy, nic neblokuje."]
    verdict = {"ok": "sedí", "mod": "sedí s úpravou", "no": "dnes raději ne", "rest": "volno"}
    for d in (ev.get("days") or []):
        if d["date"] < (ev.get("week") or {}).get("start", "") or not d["sessions"]:
            continue
        if d.get("past"):
            continue
        for s in d["sessions"][:2]:
            what = s["label"] + (f" {G._cz(s['km'])} km" if s.get("km") else f" {G._cz(s.get('min'), 0)} min" if s.get("min") else "")
            when = "dnes" if d.get("today") else G._dm(d["date"])
            if s.get("status") in ("done", "partial", "more"):
                lines.append(f"{when}: {what} — odběhnuto.")
                continue
            line = f"{when}: {what} — {verdict.get(s.get('verdict'), '—')}"
            ch = [CP.change_txt(x) for x in ((s.get("fit") or {}).get("changes") or [])]
            if ch:
                line += f" (doporučená úprava: {', '.join(ch)})"
            if s.get("why"):
                line += f"; důvod: {s['why'][0].rstrip('.')}"
            lines.append(line + ".")
        if len(lines) >= 8:
            break
    return lines


# ------------------------------------------------------------------ options and their consequences
# Owner request 2026-10-12: the assistant explains what the data and the engine imply for the
# next activities — for every option today: whether it fits and how big, what limits it, what it
# takes from today's limits and what it leaves for tomorrow (outlook.py, the same estimate as
# "Výhled na zítra" on Trénink); the week's plan (week_plan.py, as on Trénink and in the reports).
RUN_KINDS = ("regenerace", "lehký", "dlouhý", "kvalitní")


def _act_of(kind: str, t: dict) -> dict | None:
    """What-if inputs for outlook.load_of: the option at its upper size."""
    if kind in RUN_KINDS:
        return {"runKm": (t.get("km") or {}).get("hi") or 0.0,
                "z4": ((t.get("z4Target") or {}).get("hi") or 0) if kind == "kvalitní" else 0}
    if kind in ("kolo", "voda") and t.get("durationMin"):
        return {("rideMin" if kind == "kolo" else "swimMin"): t["durationMin"][1]}
    if kind == "volno":
        return {}
    return None


def _verdict_text(v: dict) -> str:
    vol = v["ch"].get("volume") or {}
    lim = LIMITED_BY.get(vol.get("lim"))
    if not v["run"]:
        run = "zítra bez běhu" + (f" (nestačí {lim})" if lim else "")
    elif vol.get("max") is None:
        run = "zítra běh bez omezení objemu"
    else:
        run = f"zítra běh nejvýš {G._cz(vol['max'])} km" + (
            f" (určuje {lim}, {'plán týdne' if vol.get('bound') == 'plan' else 'bezpečnostní limit'})" if lim else "")
    return run + (", kvalitní trénink možný" if v["quality"] else ", bez kvalitního tréninku") + (
        ", dlouhý běh možný" if v["long"] and v["run"] else "")


def _options(a) -> dict | None:
    """One sentence per activity, most to least suitable today (the engine's order), and how
    to read them. After a session today (guidance.afterDone) the rest of the day is what the
    engine says it is: the other runs are a second run the app doesn't recommend."""
    g = a.get("guidance") or {}
    types = g.get("types") or {}
    if not types:
        return None
    ol = g.get("outlook") or None
    chs = (g.get("week") or {}).get("channels") or {}
    vol_max = (chs.get("volume") or {}).get("todayMax")
    sys_max = (chs.get("systemic") or {}).get("todayMax")
    order = [k for k in (g.get("rank") or []) if k in types] or list(types)
    ad = g.get("afterDone") or {}
    out = []
    for k in order:
        t = types[k]
        label = t.get("label") or k
        tag = (" (doporučení na dnešek)" if k == g.get("type") else " (volitelně, nad rámec cíle týdne)" if t.get("optional")
               else " (navíc k dnešnímu tréninku)" if ad and k in ("kolo", "voda", "posilování") else "")
        if ad and k in RUN_KINDS and k != ad.get("type"):
            out.append(f"{label}: dnes už ne — dnešní trénink je hotový a zbytek dne aplikace doporučuje "
                       f"{'volno' if ad.get('type') == 'volno' else G.TYPE_LABEL.get(ad.get('type'), '').lower()}.")
            continue
        if not t.get("allowed"):
            out.append(f"{label}: dnes ne — {F.cz_text(t.get('why') or 'aplikace ho dnes nedoporučuje').rstrip('.')}.")
            continue
        bits = []
        km = t.get("km") if isinstance(t.get("km"), dict) else {}
        if k in RUN_KINDS and (km.get("hi") or 0) > 0:
            bits.append(f"{G._cz(km.get('lo'))}–{G._cz(km.get('hi'))} km"
                        + (f" z dnešního stropu {G._cz(vol_max)} km" if vol_max is not None else ""))
            if k == "kvalitní" and t.get("z4Target"):
                bits.append(f"{t['z4Target']['lo']}–{t['z4Target']['hi']} min v Z4+")
        elif t.get("durationMin") and t.get("cross"):
            bits.append(f"{t['durationMin'][0]}–{t['durationMin'][1]} min")
            if k in ("kolo", "voda"):
                bits.append("běžecké kilometry, klesání a šlachy šetří, počítá se jen do celkové zátěže")
        act = _act_of(k, t)
        if ol and act is not None and ol.get("channels"):
            try:
                x = O.load_of(ol, act)
                if k in ("kolo", "voda") and sys_max is not None:
                    bits.append(f"celková zátěž ≈ {G._cz(x['systemic'], 0)} z dnešních {G._cz(sys_max, 0)} bodů")
                bits.append(_verdict_text(O.verdict(ol, {"x": x}, "today")))
            except (KeyError, TypeError, ValueError, StopIteration):
                pass
        if k == "posilování" and t.get("notes"):
            bits.append(F.cz_text(t["notes"][0]).rstrip("."))
        out.append(f"{label}{tag}: " + ("; ".join(bits) if bits else "dnes jde") + ".")
    if not out:
        return None
    res = {"howToRead": "Možnosti od nejvhodnější. „Zítra …“ je odhad dnešních pravidel pro noc jako dnešní, "
                        "když dnes uděláte tu možnost v horní velikosti; ráno ho upřesní noční data.",
           "list": out}
    if ad.get("text"):
        res["doneToday"] = F.cz_text(ad["text"])
    return res


def _week_plan(db, rid, a) -> dict | None:
    """This week's plan — the same planner as Trénink, the Monday sheet and the evening report."""
    from ..metrics import daily_report as DR
    today = E.today_date()
    try:
        plan = DR._week_plan(a, db, rid, today)
    except Exception:                              # the answer stands without the plan rather than fail
        return None
    if not plan:
        return None
    if plan.get("override"):
        return {"override": F.cz_text(plan["override"]), "notes": [F.cz_text(n) for n in plan.get("notes") or []]}
    rest = DR._rest_of_week(plan, today, {"left": ((((a.get("guidance") or {}).get("week") or {}).get("channels") or {})
                                                   .get("volume") or {}).get("left")})
    days = [f"{d['wd']} {d['text']}" for d in rest.get("days") or []]
    t = plan.get("totals") or {}
    out = {"restOfWeek": days or None,
           "tomorrow": next((f"{d['wd']} {d['text']}" for d in rest.get("days") or []
                             if d["date"] == (today + timedelta(days=1)).isoformat()), None),
           "weekKmPlanned": G._cz(t.get("km")) if t.get("km") is not None else None,
           "weekKmTarget": G._cz(t.get("kmBudget")) if t.get("kmBudget") is not None else None,
           "hardSessions": f"{t.get('hard')} z nejvýš {t.get('hardCap')}" if t.get("hardCap") else None,
           "notes": [F.cz_text(n) for n in plan.get("notes") or []] or None}
    if today.weekday() == 6:
        out["tomorrow"] = "zítra začíná nový týden, plán přinese pondělní ranní report"
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def build(db, rid: str, a: dict, sel: dict) -> dict:
    """The facts packet for one question."""
    out = _state(db, rid, a)
    sl = set(sel.get("slices") or [])
    if sl & {"today", "types", "strength", "heat", "plan", "options", "weekplan"}:
        coach = _coach(a)
        if coach:
            out["coachPlan"] = coach
    if "today" in sl or "types" in sl or "strength" in sl or "heat" in sl:
        out["today"] = F._today(a)
        _why_today_max(a, out["today"])
        if isinstance(out["today"], dict):
            out["today"]["tomorrow"] = _tomorrow(a)
        out.update(_today_extra(a))
    if "types" in sl or "strength" in sl:
        out["sessionTypes"] = _types(a)
    if "options" in sl:
        out["options"] = _options(a)
    if "weekplan" in sl:
        out["weekPlan"] = _week_plan(db, rid, a)
    if "readiness" in sl:
        out["readiness"] = _readiness(a)
    if "load" in sl:
        out["load"] = _load(a)
    if "pain" in sl:
        out["pain"] = F._pain(a)
    if "runs" in sl:
        out["runs"] = _runs(db, rid, a, sel)
    if "plan" in sl:
        out["plan"] = _plan(a)
    if "mechanics" in sl:
        out["mechanics"] = _mechanics(a)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is not None and r.prior_injury and ("pain" in sl or "load" in sl):
        out["priorInjury"] = {"site": r.prior_injury, "monthsAgo": E.injury_months(r)}
    return {k: v for k, v in out.items() if v not in (None, {}, [])}
