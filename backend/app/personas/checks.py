"""What a simulated day is checked against (owner request 2026-10-27). The app's screens must
agree with each other and with the engine's own rules; each check says in Czech what broke, for
the notes in Team Console → Inbox. A check names the screen it is about (route) and a stable
key, so the same problem on another day or in another persona lands on the same note."""
import traceback
from datetime import date, timedelta

from ..metrics import engine as E

MORNING_CHECKS = ("crash", "plan-forbidden", "plan-over-limit", "report-mismatch", "readiness-range",
                  "week-budget", "illness-allows-hard", "pain-allows-hard", "data-gap-not-asked", "taper")
EVENING_CHECKS = ("crash",)
HARD_TYPES = ("kvalitní", "dlouhý")
TOL_KM = 0.3


def _crash(part: str, route: str, exc: BaseException) -> dict:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    where = next((ln.strip() for ln in reversed(tb) if 'File "' in ln and "/app/" in ln), "")
    return {"check": "crash", "route": route, "key": f"{part}:{type(exc).__name__}:{where[-80:]}", "type": "bug",
            "title": f"Chyba při výpočtu: {part} ({type(exc).__name__})",
            "detail": f"{exc}\n{where}"}


def recompute(db, rid: str, route: str) -> list:
    try:
        E.recompute_assessment(db, rid)
        return []
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return [_crash("přepočet po nových datech", route, exc)]


def snapshot(db, rid: str, day: date, light: bool = False) -> tuple[dict, list]:
    """What the persona's app shows at this moment: Dnes (guidance), Trénink (the week plan) and
    the morning report — the same functions the endpoints call."""
    from ..metrics import daily_report as DR
    out: dict = {"date": E.iso_date(day)}
    crashes: list = []
    try:
        a = E.get_or_refresh_assessment(db, rid)
    except Exception as exc:  # noqa: BLE001
        return out, [_crash("hodnocení (engine)", "/app/today", exc)]
    g = a.get("guidance") or {}
    vol = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    out.update({
        "type": g.get("type"), "typeLabel": g.get("typeLabel"), "readiness": g.get("readinessScore"),
        "provisional": g.get("provisional"), "reasons": (g.get("reasons") or [])[:5],
        "types": {k: {"allowed": v.get("allowed"), "km": v.get("km"), "label": v.get("label")} for k, v in (g.get("types") or {}).items()},
        "todayMax": vol.get("todayMax"), "ceiling7": vol.get("ceiling7"), "done7": vol.get("done7"),
        "left7": vol.get("left7"), "pin": g.get("pin"), "goal": bool(g.get("goal")),
        "goalPhase": (g.get("goal") or {}).get("phase") if isinstance(g.get("goal"), dict) else None,
    })
    if light:
        return out, crashes
    try:
        wp = DR._week_plan(a, db, rid, day)
    except Exception as exc:  # noqa: BLE001
        wp = None
        crashes.append(_crash("plán týdne", "/app/training", exc))
    if wp:
        today = next((d for d in wp.get("days") or [] if d.get("date") == E.iso_date(day)), None) or {}
        out.update({
            "weekStart": wp.get("weekStart"), "weekTotals": wp.get("totals"), "weekNotes": (wp.get("notes") or [])[:4],
            "planToday": [{"kind": i.get("kind"), "type": i.get("type"), "label": i.get("label"), "km": i.get("km"),
                           "optional": i.get("optional"), "durationMin": i.get("durationMin")} for i in today.get("items") or []],
            "pinnedToday": bool(today.get("pinned")),
        })
    try:
        rep = DR.build(db, rid, "morning")
        plan = rep.get("plan") or {}
        out["report"] = {"type": plan.get("type"), "label": plan.get("label"), "km": plan.get("km")}
    except Exception as exc:  # noqa: BLE001
        crashes.append(_crash("ranní report", "/app/today", exc))
    return out, crashes


def light(snap: dict) -> dict:
    """The part of a snapshot kept in the journal."""
    keep = ("type", "typeLabel", "readiness", "provisional", "reasons", "todayMax", "ceiling7", "done7", "left7",
            "weekStart", "weekTotals", "weekNotes", "planToday", "report", "goal", "goalPhase", "pinnedToday")
    out = {k: snap.get(k) for k in keep if k in snap}
    if "types" in snap:
        out["allowed"] = sorted(k for k, v in snap["types"].items() if v.get("allowed"))
        out["types"] = snap["types"]
    return out


def _f(check, route, key, title, detail, kind="bug") -> dict:
    return {"check": check, "route": route, "key": key, "title": title, "detail": detail, "type": kind}


def _who(ctx: dict) -> str:
    return f"Persona {ctx['name']} ({ctx['label']}), simulovaný den {ctx['day']} ({ctx['date']})"


def morning_checks(db, rid: str, s: dict, ctx: dict) -> list:
    out = []
    types = s.get("types") or {}
    who = _who(ctx)
    for item in s.get("planToday") or []:
        if item.get("kind") != "run" or s.get("pinnedToday"):
            continue
        t = types.get(item.get("type")) or {}
        hi = ((item.get("km") or {}).get("hi")) or 0
        if t and t.get("allowed") is False and not item.get("optional"):
            out.append(_f("plan-forbidden", "/app/training", item.get("type"),
                          f"Trénink plánuje na dnešek „{item.get('label')}“, který Dnes nedovoluje",
                          f"{who}: Dnes má typ „{item.get('type')}“ jako nedovolený, Plán týdne ho na dnešek přesto ukazuje "
                          f"({hi} km)."))
        lim = s.get("todayMax")
        if lim is not None and hi > lim + TOL_KM:
            out.append(_f("plan-over-limit", "/app/training", item.get("type"),
                          "Plán týdne na dnešek je nad dnešním bezpečnostním limitem",
                          f"{who}: Plán týdne ukazuje {item.get('label')} až {hi} km, Dnes dovoluje nejvýš {lim} km."))
    rep = s.get("report") or {}
    if rep.get("type") and s.get("type") and rep["type"] != s["type"]:
        out.append(_f("report-mismatch", "/app/today", f"{s['type']}>{rep['type']}",
                      "Ranní report doporučuje jiný trénink než Dnes",
                      f"{who}: Dnes doporučuje „{s.get('typeLabel')}“, ranní report „{rep.get('label')}“."))
    r = s.get("readiness")
    if r is not None and not 0 <= r <= 100:
        out.append(_f("readiness-range", "/app/today", "range", "Připravenost mimo rozsah 0–100",
                      f"{who}: připravenost {r}."))
    tot = s.get("weekTotals") or {}
    if tot.get("km") is not None and tot.get("kmBudget") is not None:
        # what is still to come against what is left of the week's target (km already run can't be planned away)
        done = tot.get("kmDone") or 0
        ahead, room = tot["km"] - done, max(0.0, tot["kmBudget"] - done)
        if done <= tot["kmBudget"] and ahead > room + 0.5:      # past the target the plan only keeps safety
            out.append(_f("week-budget", "/app/training", "km", "Plán týdne je nad týdenním rozpočtem",
                          f"{who}: do konce týdne plán ještě počítá s {round(ahead, 1)} km, z týdenního cíle "
                          f"{tot['kmBudget']} km zbývá {round(room, 1)} km (hotovo {done} km)."))
    ill = next((e for e in ctx["events"] if e["kind"] == "illness"), None)
    if ill and ctx["day"] > ill["from"]:
        allowed = [k for k in HARD_TYPES if (types.get(k) or {}).get("allowed")]
        if allowed or s.get("type") in HARD_TYPES:
            out.append(_f("illness-allows-hard", "/app/today", ",".join(allowed) or s.get("type"),
                          "Při nemoci aplikace dovoluje kvalitní trénink nebo dlouhý běh",
                          f"{who}: {ctx['day'] - ill['from'] + 1}. den nemoci (klidový tep zhruba +8 tepů, HRV −30 %, "
                          f"zrychlený dech{', check-in hlásí nemoc' if ctx.get('checkin') else ''}); Dnes dovoluje: "
                          f"{', '.join(allowed) or s.get('typeLabel')}.", kind="engine"))
    pain = next((e for e in ctx["events"] if e["kind"] == "pain" and e.get("score", 0) >= 4), None)
    if pain and ctx.get("checkin"):
        allowed = [k for k in HARD_TYPES if (types.get(k) or {}).get("allowed")]
        if allowed:
            out.append(_f("pain-allows-hard", "/app/today", ",".join(allowed),
                          "Při bolesti 4/10 a víc aplikace dovoluje kvalitní trénink nebo dlouhý běh",
                          f"{who}: check-in hlásí bolest {pain['score']}/10 ({pain['site']}); Dnes dovoluje: {', '.join(allowed)}.",
                          kind="engine"))
    from . import catalog as K
    gaps = [e for e in K.PERSONAS[ctx["persona"]].get("events", []) if e["kind"] == "no_watch" and e["to"] - e["from"] >= 2]
    if any(ctx["day"] == e["to"] + 1 for e in gaps):        # the first morning with the watch back
        from ..metrics import gaps as GA
        if GA.data_gap(db, rid, date.fromisoformat(ctx["date"])) is None:
            out.append(_f("data-gap-not-asked", "/app/today", "gap",
                          "Po třech dnech bez hodinek se aplikace nezeptala, co se dělo",
                          f"{who}: tři dny bez dat z hodinek, ráno se otázka na mezeru v datech neobjevila."))
    goal = ctx.get("goal")
    if goal and tot.get("km") is not None and s.get("weekStart"):
        race = date.fromisoformat(ctx["start"]) + timedelta(days=goal["day"])
        ws = date.fromisoformat(s["weekStart"])
        weeks = (ctx.get("stats") or {}).get("weeks") or {}
        if ws <= race < ws + timedelta(days=7) and date.fromisoformat(ctx["date"]) == ws:
            prior = [v for k, v in weeks.items() if v and ws - timedelta(days=42) <= date.fromisoformat(k) < ws]
            if prior and tot["km"] > 0.8 * max(prior) + 1:
                out.append(_f("taper", "/app/training", "race-week",
                              "V závodním týdnu plán neubírá",
                              f"{who}: závodní týden {E.iso_date(ws)} má v plánu {tot['km']} km, nejvyšší z předchozích "
                              f"6 týdnů {max(prior)} km (čekali bychom nejvýš 80 %).", kind="engine"))
    return out


def evening_checks(morning: dict, after: dict, ctx: dict) -> list:
    """After the run. The weekly ceiling counts absorbed load (older runs only in part), so a plain
    7-day sum is no test of it; the plan's own limits are checked in the morning (plan-over-limit)."""
    return []
