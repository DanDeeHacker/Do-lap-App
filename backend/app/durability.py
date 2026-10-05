"""Runner's must-have — a 6-month strength programme for durability and injury
prevention (owner request 2026-10-03): two sessions, A (heavy strength) and B
(resilience: single-leg, reactive and tendon work), twice a week, alternating.

How a session is picked: A and B take turns, but A only on a day that can carry it
— the running plan isn't in a recovery state, Celková zátěž has room left, no hard
or long run yesterday and no hard run tomorrow (Doma et al., 2017: heavy leg work
blunts the next 24–48 h of intensive running). Otherwise B, and A moves to the next
session.

How a session progresses: by how the runner felt at the end (session RPE, Foster et
al., 2001; RIR-based effort, Helms et al., 2016). Each session has a level 0–2 that
picks the reps (or seconds) inside the phase's range; at the top of the range the
load goes up ("load step") and the reps start again at the bottom (double
progression). Easy → up a level; just right twice in a row → up; hard twice in a
row → down; pain → down at once.

The 26 weeks in five phases: basics → strength and volume → heavy strength →
reactive strength → maintenance and re-test. After the basics every 4th week (or the running cycle's
recovery week, taper or graded return) is a deload: one set less, the bottom of the
range, same load. The doses of the two sessions are sized against the runner's
weekly strength capacity (Silová zátěž, sRPE·min): if two sessions would go over the
7-day ceiling, sets come off until they fit.

Doses beyond the cited principles are the product team's working assumptions."""
from datetime import date, timedelta

from . import models
from .metrics import engine as E

WEEKS = 26
PER_WEEK = 2
MIN_GAP_DAYS = 2                 # 48 h between two sessions of the programme
FEEL = {"easy": 4, "ok": 6, "hard": 8, "pain": 7}    # → session RPE (0–10) for the load
FEEL_CS = {"easy": "lehké", "ok": "akorát", "hard": "těžké", "pain": "něco bolelo"}

# (first week, last week, key, name, goal, target RPE)
PHASES = [
    (1, 4, "base", "Základ a technika", "Naučit se pohyby, zvyknout šlachy na zátěž. Dvě až tři opakování vždy v záloze.", "5–6"),
    (5, 10, "volume", "Síla a objem", "Víc sérií a opakování, zátěž roste po malých krocích. Dvě opakování v záloze.", "6–7"),
    (11, 18, "strength", "Těžká síla", "Méně opakování s těžší zátěží, plná kontrola pohybu. Jedno až dvě opakování v záloze.", "7–8"),
    (19, 24, "power", "Reaktivní síla", "Rychlý pohyb nahoru, krátký kontakt se zemí u poskoků. Síla se drží těžkou zátěží s menším objemem.", "7–8"),
    (25, 26, "maintain", "Udržení a kontrolní test", "Menší objem, stejná zátěž. Zapište si, kolik zvládnete, a začněte nový cyklus na vyšší úrovni.", "6–7"),
]
PHASE_KEYS = [p[2] for p in PHASES]

# exercise → phase → (sets, lo, hi, unit). unit: "" reps, "/noha", "/strana", "s", "s/strana",
# "kroků/směr". `secs` = seconds per rep (time under load) for the duration estimate.
SESSIONS = {
    "A": {"name": "Síla", "label": "A · Síla (těžší)", "type": "heavy", "focus": "lower",
          "rest": {"main": 120, "acc": 60},
          "plan": [
              ("pogo_hops", "acc", {"base": (2, 15, 20, "s"), "volume": (3, 20, 20, "s"), "strength": (3, 20, 25, "s"),
                                    "power": (4, 20, 25, "s"), "maintain": (3, 20, 20, "s")}),
              ("monster_walk", "acc", {"base": (2, 10, 12, "kroků/směr"), "volume": (2, 12, 15, "kroků/směr"),
                                       "strength": (2, 15, 15, "kroků/směr"), "power": (2, 12, 15, "kroků/směr"),
                                       "maintain": (2, 12, 12, "kroků/směr")}),
              ("bulgarian_ss", "main", {"base": (2, 8, 10, "/noha"), "volume": (3, 8, 10, "/noha"), "strength": (3, 6, 8, "/noha"),
                                        "power": (3, 5, 6, "/noha"), "maintain": (2, 6, 6, "/noha")}),
              ("rdl", "main", {"base": (2, 10, 10, ""), "volume": (3, 8, 10, ""), "strength": (3, 6, 8, ""),
                               "power": (3, 4, 6, ""), "maintain": (2, 6, 6, "")}),
              ("seated_calf", "main", {"base": (3, 12, 15, ""), "volume": (4, 10, 12, ""), "strength": (4, 8, 12, ""),
                                       "power": (4, 6, 8, ""), "maintain": (3, 8, 10, "")}),
              ("copenhagen_hold", "acc", {"base": (2, 15, 20, "s/strana"), "volume": (2, 20, 30, "s/strana"),
                                          "strength": (3, 20, 30, "s/strana"), "power": (3, 25, 30, "s/strana"),
                                          "maintain": (2, 25, 25, "s/strana")}),
              ("pallof", "acc", {"base": (2, 8, 10, "/strana"), "volume": (2, 10, 12, "/strana"), "strength": (3, 10, 10, "/strana"),
                                 "power": (2, 10, 12, "/strana"), "maintain": (2, 10, 10, "/strana")}),
          ]},
    "B": {"name": "Odolnost", "label": "B · Odolnost", "type": "plyo", "focus": "lower",
          "rest": {"main": 60, "acc": 40},
          "plan": [
              ("sl_hops", "acc", {"base": (2, 8, 10, "/noha"), "volume": (2, 12, 15, "/noha"), "strength": (2, 15, 15, "/noha"),
                                  "power": (3, 12, 15, "/noha"), "maintain": (2, 15, 15, "/noha")}),
              ("step_down", "main", {"base": (2, 8, 10, "/noha"), "volume": (3, 10, 10, "/noha"), "strength": (3, 10, 12, "/noha"),
                                     "power": (3, 8, 10, "/noha"), "maintain": (2, 10, 10, "/noha")}),
              # owner request 2026-10-04 — pelvic control on one leg: contralateral pelvic drop goes
              # with running injuries (Bramah et al., 2018) and functional hip abductor training
              # reduced it in runners with shin pain (Lashien et al., 2024)
              ("pelvic_drop", "acc", {"base": (2, 10, 12, "/noha"), "volume": (2, 12, 15, "/noha"), "strength": (3, 12, 15, "/noha"),
                                      "power": (2, 15, 15, "/noha"), "maintain": (2, 12, 12, "/noha")}),
              ("sl_rdl", "main", {"base": (2, 8, 8, "/noha"), "volume": (3, 8, 10, "/noha"), "strength": (3, 8, 8, "/noha"),
                                  "power": (3, 6, 8, "/noha"), "maintain": (2, 8, 8, "/noha")}),
              ("sl_calf_slow", "main", {"base": (2, 10, 12, "/noha"), "volume": (3, 10, 15, "/noha"), "strength": (3, 12, 15, "/noha"),
                                        "power": (3, 12, 15, "/noha"), "maintain": (2, 12, 12, "/noha")}),
              ("toe_raise", "acc", {"base": (2, 15, 20, ""), "volume": (2, 20, 20, ""), "strength": (2, 20, 25, ""),
                                    "power": (2, 20, 25, ""), "maintain": (2, 20, 20, "")}),
              ("side_plank_abd", "acc", {"base": (2, 20, 25, "s/strana"), "volume": (2, 25, 30, "s/strana"),
                                         "strength": (2, 30, 35, "s/strana"), "power": (2, 30, 40, "s/strana"),
                                         "maintain": (2, 30, 30, "s/strana")}),
              ("dead_bug", "acc", {"base": (2, 8, 8, "/strana"), "volume": (2, 8, 10, "/strana"), "strength": (2, 10, 10, "/strana"),
                                   "power": (2, 10, 10, "/strana"), "maintain": (2, 10, 10, "/strana")}),
          ]},
}
# how the load goes up at the top of the range (per exercise; working assumptions)
LOAD_STEP = {
    "pogo_hops": "výš a s kratším kontaktem se zemí",
    "monster_walk": "silnější guma",
    "bulgarian_ss": "+2 kg v každé ruce",
    "rdl": "+2,5–5 kg",
    "seated_calf": "+5 kg",
    "copenhagen_hold": "delší páka: kotník na lavici místo kolena",
    "pallof": "silnější guma nebo dál od úchytu",
    "sl_hops": "poskoky dopředu a do stran",
    "step_down": "vyšší schod nebo činka v ruce",
    "pelvic_drop": "pomalé spouštění 3 s, pak činka v ruce na straně volné nohy",
    "sl_rdl": "+2 kg",
    "sl_calf_slow": "batoh nebo činka, dolů 3 s",
    "toe_raise": "paty dál od zdi nebo závaží na špičkách",
    "side_plank_abd": "zvednutá noha s gumou nad koleny",
    "dead_bug": "natažené nohy a pomalejší tempo",
}
SECS_PER_REP = 4.0               # controlled tempo, ~1 s up / 2–3 s down
WARMUP_MIN = 8
TRANSITION_S = 60                # between exercises


def phase_of(week: int) -> tuple:
    w = max(1, min(WEEKS, week))
    return next(p for p in PHASES if p[0] <= w <= p[1])


def week_of(started_on: str | None, today: date) -> int:
    try:
        return (today - date.fromisoformat(started_on)).days // 7 + 1
    except (TypeError, ValueError):
        return 1


def _amount(lo: int, hi: int, level: int) -> int:
    return round(lo + (hi - lo) * max(0, min(2, level)) / 2)


def _dose(sets: int, n: int, unit: str) -> str:
    """'3 × 20 s', '2 × 25 s/strana', '3 × 8 /noha' → readable: '3 × 8 každá noha'."""
    if unit == "s":
        return f"{sets} × {n} s"
    if unit == "s/strana":
        return f"{sets} × {n} s každá strana"
    if unit == "/noha":
        return f"{sets} × {n} každá noha"
    if unit == "/strana":
        return f"{sets} × {n} každá strana"
    if unit == "kroků/směr":
        return f"{sets} × {n} kroků každým směrem"
    return f"{sets} × {n}"


def session_plan(key: str, week: int, level: int, deload: bool, scale: float = 1.0) -> list[dict]:
    """The exercises of session A/B for this week: sets, reps / seconds, dose text."""
    ph = phase_of(week)[2]
    s = SESSIONS[key]
    out = []
    for ex, kind, doses in s["plan"]:
        sets, lo, hi, unit = doses[ph]
        n = lo if deload else _amount(lo, hi, level)
        k = sets - 1 if deload else sets
        if scale < 1.0:
            k = round(k * scale)
        k = max(1, min(sets, k))
        out.append({"id": ex, "kind": kind, "sets": k, "n": n, "unit": unit, "range": [lo, hi],
                    "dose": _dose(k, n, unit), "loadStep": LOAD_STEP.get(ex)})
    return out


def estimate_min(key: str, plan: list[dict]) -> float:
    """Session length: warm-up + work (reps × tempo or the hold, both sides) + rests."""
    rest = SESSIONS[key]["rest"]
    tot = WARMUP_MIN * 60.0
    for x in plan:
        sides = 2 if ("noha" in x["unit"] or "strana" in x["unit"] or "směr" in x["unit"]) else 1
        work = x["n"] * (1.0 if x["unit"].startswith("s") else SECS_PER_REP) * sides
        tot += x["sets"] * work + (x["sets"] - 1) * rest[x["kind"]] + TRANSITION_S
    return round(tot / 60.0)


def target_rpe(week: int) -> float:
    lo, hi = (float(v) for v in phase_of(week)[5].split("–"))
    return (lo + hi) / 2


def capacity_scale(a: dict | None, week: int, level: int, deload: bool) -> tuple[float, dict | None]:
    """Sets factor so that two sessions a week stay inside the 7-day strength ceiling."""
    wk = ((((a or {}).get("capacity") or {}).get("channels") or {}).get("strength") or {}).get("week") or {}
    ceil = wk.get("ceiling")
    if not ceil:
        return 1.0, None
    r = target_rpe(week)
    weekly = sum(estimate_min(k, session_plan(k, week, level, deload)) * r for k in ("A", "B"))
    if weekly <= ceil:
        return 1.0, {"weekly": round(weekly), "ceiling": round(ceil)}
    return max(0.5, ceil / weekly), {"weekly": round(weekly), "ceiling": round(ceil)}


def _hard_run(db, rid: str, day: date) -> bool:
    """A run on `day` that was hard or long: rated ≥ 7, ≥ 80 min, or Z4-level heart rate."""
    d = day.isoformat()
    acts = [x for x in db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                                       models.Activity.started_at >= d,
                                                       models.Activity.started_at < (day + timedelta(days=1)).isoformat()).all()
            if (x.sport or "running") == "running" and E.counts_for(x, "all")]
    if not acts:
        return False
    rpe = {f.activity_id: f.rpe for f in db.query(models.ActivityFeedback).filter(
        models.ActivityFeedback.activity_id.in_([x.id for x in acts])).all()}
    for x in acts:
        if (rpe.get(x.id) or x.rpe or 0) >= 7 or (x.duration_min or 0) >= 80:
            return True
    return False


def choose(db, rid: str, a: dict | None, state: dict, today: date) -> dict:
    """Which session today (A / B) and why; None-able `blocked` when not today."""
    g = (a or {}).get("guidance") or {}
    hist = state.get("history") or []
    last = hist[-1] if hist else None
    due = "B" if (last and last["session"] == "A") else "A"
    reasons = []
    t_iso = today.isoformat()
    # not today at all
    blocked = None
    if last and last["date"] == t_iso:
        blocked = "Dnešní trénink programu máte hotový."
    elif last and (today - date.fromisoformat(last["date"])).days < MIN_GAP_DAYS:
        blocked = "Mezi dvěma tréninky programu nechte aspoň 48 hodin."
    else:
        ws = (today - timedelta(days=today.weekday())).isoformat()
        if sum(1 for h in hist if h["date"] >= ws) >= PER_WEEK:
            blocked = f"Tento týden máte {PER_WEEK} z {PER_WEEK} tréninků hotové."
    pos = (g.get("types") or {}).get("posilování") or {}
    why_block = pos.get("why") or ""
    if not blocked and "závod" in why_block.lower():
        blocked = why_block
    # A only on a day that can carry it
    if due == "A":
        wk = g.get("week") or {}
        sysc = (wk.get("channels") or {}).get("systemic") or {}
        ax = g.get("axes") or {}
        th = ax.get("threshold") or 25
        if wk.get("mode") in ("recovery", "deload", "taper", "return"):
            reasons.append({"recovery": "běžecký plán má odlehčovací týden", "deload": "zátěž je zvýšená, týden je odlehčovací",
                            "taper": "blíží se závod", "return": "vracíte se po zranění"}[wk["mode"]])
        if (ax.get("load") or 0) >= th:
            reasons.append("zátěž je nad prahem")
        if (ax.get("mech") or 0) >= th:
            reasons.append("mechanika je nad prahem")
        if sysc.get("todayMax") is not None and sysc.get("budget") and sysc["todayMax"] < 0.25 * sysc["budget"]:
            reasons.append("celková zátěž má na dnešek málo místa")
        if (g.get("readinessScore") or 100) < 55:
            reasons.append("připravenost je nízká")
        if g.get("type") in ("volno", "regenerace"):
            reasons.append("dnes je doporučený odpočinek nebo regenerace")
        if why_block.startswith("Zítra"):
            reasons.append("zítra vás čeká tvrdý běh")
        if _hard_run(db, rid, today - timedelta(days=1)):
            reasons.append("včera byl tvrdý nebo dlouhý běh")
        if _hard_run(db, rid, today):
            reasons.append("dnes už byl tvrdý nebo dlouhý běh")
    session = "B" if (due == "A" and reasons) else due
    if session == "A":
        why = "Na řadě je silová session A a den ji unese."
    elif due == "A":
        why = f"Místo A dnes lehčí B: {', '.join(reasons)}. Silová A přijde příště."
    else:
        why = "Na řadě je B, po minulé A se střídají."
    return {"session": session, "due": due, "why": why, "reasons": reasons, "blocked": blocked}


def progress(state: dict, session: str, feel: str, week: int) -> dict:
    """Moves the session's level (and load steps) by how the end of the session felt."""
    lv = dict(state.get("levels") or {"A": 0, "B": 0})
    steps = dict(state.get("steps") or {"A": 0, "B": 0})
    hist = list(state.get("history") or [])
    prev = next((h for h in reversed(hist) if h["session"] == session), None)
    ph = phase_of(week)[2]
    if prev and prev.get("phase") != ph:
        lv[session] = 0                         # a new phase starts at the bottom of its ranges
    cur = lv.get(session, 0)
    same_prev = prev and prev.get("phase") == ph and prev.get("level") == cur
    note = None
    if feel == "easy":
        up = True
    elif feel == "ok":
        up = bool(same_prev and prev.get("feel") == "ok")
    else:
        up = False
    if up:
        if cur >= 2:
            lv[session], steps[session] = 0, steps.get(session, 0) + 1
            note = "Příště přidejte zátěž a začněte znovu na spodní hranici opakování."
        else:
            lv[session] = cur + 1
            note = "Příště o něco víc opakování."
    elif feel == "pain" or (feel == "hard" and same_prev and prev.get("feel") == "hard"):
        lv[session] = max(0, cur - 1)
        note = ("Příště méně opakování. Bolest při cviku do 5 z 10 je v pořádku, do rána musí odeznít."
                if feel == "pain" else "Dvakrát po sobě těžké: příště méně opakování.")
    else:
        note = "Příště stejně, ať se tělo přizpůsobí."
    hist.append({"date": E.today_date().isoformat(), "session": session, "feel": feel, "level": cur, "phase": ph, "week": week})
    return {**state, "levels": lv, "steps": steps, "history": hist[-120:], "note": note}


def is_deload(week: int, a: dict | None) -> bool:
    if week <= PHASES[0][1]:                    # the basics are light already
        return False
    g = (a or {}).get("guidance") or {}
    mode = (g.get("week") or {}).get("mode")
    if mode in ("recovery", "deload", "taper", "return"):
        return True
    if mode in ("build",):
        return False
    return week % 4 == 0 and week < 25
