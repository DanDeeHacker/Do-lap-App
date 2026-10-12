"""Plán od trenéra (owner request 2026-10-12): the coach decides what is run, Došlap keeps
to what the body takes today and this week.

Every planned session goes through the checks of the app's own recommendation
(guidance.build_guidance), the body first:
  1. an override (injury, red flags, limited movement, a tendon / bone warning, acute
     overload), illness, pain > 5/10, readiness under 45 %, a race's first recovery days
     → "Dnes raději ne", with the app's own option for today as the replacement;
  2. the engine's other rules for the session's kind (readiness under 65 % for a quality
     or long session, < 48 h after a hard one, pain 3–5 or recurring, a heavy leg session,
     a race recovery, a return after injury …) → a lighter version or another day;
  3. the load: each channel (km, Z4+ minutes, descent, ascent, Celková zátěž) against
     today's SAFETY room — the absorbed load under the weekly ceiling and the per-run
     ceiling. The coach's plan is the week's target, never a limit. Over → the smallest
     change that fits (hard minutes, km, a flatter route) or a day with room.
Future days run through the outlook's coefficients (outlook.py) night by night, with
normal nights and the plan done as written — a forecast, recomputed every morning.

The app never changes or blocks the plan: it says by how much and why a session doesn't
fit, shows the modified version and a message for the coach. The runner decides; what is
run anyway counts, and tomorrow's limits follow.
"""
import re
from datetime import date, timedelta

from . import outlook as O

CHS = ("volume", "intensity", "descent", "ascent", "systemic")
KINDS = {
    "easy": {"label": "Lehký běh", "sport": "run", "app": "lehký"},
    "recovery": {"label": "Regenerační běh", "sport": "run", "app": "regenerace"},
    "long": {"label": "Dlouhý běh", "sport": "run", "app": "dlouhý"},
    "quality": {"label": "Intervaly / tempo", "sport": "run", "app": "kvalitní", "hard": True},
    "hills": {"label": "Kopce", "sport": "run", "app": "kvalitní", "hard": True},
    "race": {"label": "Závod", "sport": "run", "app": "závod", "hard": True},
    "ride": {"label": "Kolo", "sport": "cycling", "app": "kolo"},
    "swim": {"label": "Plavání", "sport": "swimming", "app": "voda"},
    "strength": {"label": "Posilování", "sport": "strength", "app": "posilování"},
    "other": {"label": "Jiný trénink", "sport": "other", "app": None},
    "rest": {"label": "Volno", "sport": None, "app": "volno"},
}
RUN = {k for k, v in KINDS.items() if v["sport"] == "run"}
HARD = {k for k, v in KINDS.items() if v.get("hard")}
SPORT_OF_ACT = {"running": "run", "trail_running": "run", "treadmill": "run", "cycling": "cycling",
                "swimming": "swimming", "strength": "strength"}
DEFAULT_Z4 = {"quality": 20.0, "hills": 12.0}   # hard minutes when the coach gave none (flagged as estimated)
DEFAULT_MIN = {"ride": 60.0, "swim": 30.0, "strength": 45.0, "other": 45.0}
ECC = 1.16                 # descent weighting of a typical run (capacity.ECC_DEFAULT): real metres ↔ load
TOL_REL = 0.05             # a plan within 5 % (+ a unit's worth) of the limit still fits — no nitpicking
TOL_ABS = {"volume": 0.3, "intensity": 2.0, "descent": 15.0, "ascent": 15.0, "systemic": 5.0}
MIN_HARD = 5.0             # fewer hard minutes left than this → the session goes easy
MIN_RUN_KM = 2.0
MIN_CROSS = 20.0
HARD_GAP = 2               # ≥ 48 h between hard sessions (guidance.HARD_GAP_DAYS)
HORIZON = 13               # days ahead the plan is projected (the rest of this week and the next)
MATCH_TOL = 0.10           # ± 10 % of the planned km = done (the doc)
EASY_SHARE = 0.80          # an easy run is easy with ≥ 80 % of its time in Z1–Z2
HARD_TOL = 0.20            # hard minutes within ± 20 % of the plan
PLAN_OK = 0.80             # ≥ 80 % of the sessions and the km of the plan = the plan was kept
NO_PERSIST = ("injury", "function", "bone_stress", "red_flag")   # these keep tomorrow off too


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _r(v, dec=1):
    return None if v is None else round(v, dec)


def _cz(v, dec=1):
    return "—" if v is None else (f"{v:.{dec}f}".replace(".", ",") if dec else str(round(v)))


WD = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
WD_ACC = ("pondělí", "úterý", "středu", "čtvrtek", "pátek", "sobotu", "neděli")
WD_WITH = ("pondělím", "úterým", "středou", "čtvrtkem", "pátkem", "sobotou", "nedělí")


# ------------------------------------------------------------------ the hard part from text
_PACE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_REP = re.compile(r"(\d{1,2})\s*[x×*]\s*\(?\s*(\d+(?:\.\d+)?)\s*(km|m\b|min|minut|mins|s\b|sec|sek|'|´|’|\")?", re.I)
_TEMPO_A = re.compile(r"(\d+(?:\.\d+)?)\s*(min|minut|'|´|km)\s*(?:v\s*|@\s*)?(?:tempo|tempu|tempový|threshold|prah|LT\b|T\b|"
                      r"závodní|race|Z4|Z5|rychle|svižně)", re.I)
_TEMPO_B = re.compile(r"(?:tempo|tempový běh|threshold|prahov\w*|fartlek|progres\w*)\D{0,8}(\d+(?:\.\d+)?)\s*(min|minut|'|´|km)", re.I)
_TEMPO_S = re.compile(r"(?:tempo|tempový běh|threshold|prahov\w*|fartlek)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(min|minut|'|´|km)", re.I)


def hard_minutes(text: str | None, easy_pace_s: float | None = None) -> float | None:
    """Minutes of the hard part from the coach's text: "6× 1 km v 4:30", "8x400 m",
    "5× 3 min", "tempo 20 min", "3 km v tempu". A distance takes the pace in the text,
    else ~18 % faster than the runner's easy pace. None when the text names no hard part."""
    if not text:
        return None
    t = text.replace(",", ".")
    pace = None
    for m in _PACE.finditer(t):
        p = int(m.group(1)) * 60 + int(m.group(2))
        if 150 <= p <= 540:
            pace = p
            break
    hp = pace or (easy_pace_s or 330.0) * 0.82
    total, found = 0.0, False
    for m in _REP.finditer(t):
        n, v, u = int(m.group(1)), float(m.group(2)), (m.group(3) or "").lower()
        if not 1 <= n <= 40:
            continue
        if u == "km":
            mins = v * hp / 60
        elif u == "m" or (not u and v >= 100):
            mins = v / 1000 * hp / 60
        elif u in ("s", "sec", "sek", '"'):
            mins = v / 60
        elif u in ("min", "minut", "mins", "'", "´", "’") or (not u and v <= 30):
            mins = v
        else:
            continue
        total += n * mins
        found = True
    if not found:
        for rx in (_TEMPO_S, _TEMPO_A, _TEMPO_B):
            m = rx.search(t)
            if m:
                v, u = float(m.group(1)), m.group(2).lower()
                total, found = (v * hp / 60 if u == "km" else v), True
                break
    return round(total, 1) if found else None


# ------------------------------------------------------------------ a session as load
def norm(s: dict, ctx: dict) -> dict:
    """A planned row → the session as evaluated: km, minutes, hard minutes (given, from the
    intervals text, or a typical value), hills in real metres; `est` lists what was estimated."""
    k = s.get("kind") if s.get("kind") in KINDS else "other"
    sp = KINDS[k]["sport"]
    ep = ctx.get("easyPace") or 360.0
    base = ctx.get("baseKm") or 6.0
    km, dur, z4 = s.get("km"), s.get("duration_min"), s.get("z4_min")
    est = []
    if sp == "run":
        fast = 0.92 if k in HARD else 1.0
        if not km and dur:
            km = dur * 60 / (ep * fast)
            est.append("km")
        if not km:
            km = (1.5 if k == "long" else 1.0) * base
            est.append("km")
        if z4 is None:
            txt = s.get("intervals") or " ".join(x for x in (s.get("title"), s.get("notes")) if x)
            if s.get("target") and not _PACE.search(txt or ""):
                txt = f"{txt} {s['target']}"
            z4 = hard_minutes(txt, ep) if (k in HARD or s.get("intervals")) else None
            if z4 is None and k in HARD:
                z4 = km * ep * 0.82 / 60 if k == "race" else DEFAULT_Z4[k]
                est.append("z4")
            elif z4 is not None:
                est.append("z4text")
        z4 = z4 or 0.0
        if not dur:
            dur = km * ep * fast / 60
    elif sp:
        if not dur:
            dur = DEFAULT_MIN.get(k, 45.0)
            est.append("min")
        z4 = z4 or 0.0
    else:
        km = dur = z4 = None
    return {"id": s.get("id"), "date": str(s.get("date"))[:10], "seq": s.get("seq") or 0, "kind": k,
            "label": KINDS[k]["label"], "title": s.get("title"), "km": km, "min": dur, "z4": z4,
            "desc": s.get("descent_m"), "asc": s.get("ascent_m"), "intervals": s.get("intervals"),
            "target": s.get("target"), "notes": s.get("notes"), "source": s.get("source") or "manual",
            "activityId": s.get("activity_id"), "est": est}


def load(sn: dict, conv: dict) -> dict:
    """Per-channel load of a session in the engine's units (km, Z4+ min, weighted descent
    m, ascent m, Celková zátěž) — the outlook's conversions (outlook.load_of) from the
    runner's own easy runs; hills from the plan or the runner's usual metres per km."""
    k, sp = sn["kind"], KINDS[sn["kind"]]["sport"]
    ol = {"conv": conv}
    z4pm = conv.get("z4PerMin") or 0.0
    if sp == "run":
        x = O.load_of(ol, {"runKm": sn["km"], "z4": sn["z4"]})
        if sn.get("desc") is not None:
            x["descent"] = sn["desc"] * ECC
        if sn.get("asc") is not None:
            x["ascent"] = sn["asc"]
        return x
    x = {c: 0.0 for c in CHS}
    if sp == "cycling":
        x["systemic"] = sn["min"] * (conv.get("perMinRide") or 0.0) + sn["z4"] * max(0.0, z4pm - (conv.get("perMinRide") or 0.0))
        x["intensity"] = sn["z4"]
    elif sp == "swimming":
        x["systemic"] = sn["min"] * (conv.get("perMinSwim") or 0.0) + sn["z4"] * max(0.0, z4pm - (conv.get("perMinSwim") or 0.0))
        x["intensity"] = sn["z4"]
    elif sp == "strength":
        x["systemic"] = sn["min"] * (conv.get("perMinSwim") or 0.0) / 4 * 6      # session RPE ~6 (sRPE × min)
    elif sp == "other":
        x["systemic"] = sn["min"] * (conv.get("perMinRide") or 0.0)
    return x


def act_of(sn: dict) -> dict:
    """The outlook's what-if input for a session (Výhled na zítra → Podle plánu)."""
    sp = KINDS[sn["kind"]]["sport"]
    if sp == "run":
        return {"runKm": sn["km"] or 0.0, "z4": sn["z4"] or 0.0}
    if sp == "cycling":
        return {"rideMin": sn["min"] or 0.0}
    if sp == "swimming":
        return {"swimMin": sn["min"] or 0.0}
    return {}


# ------------------------------------------------------------------ rooms
def today_room(ctx: dict) -> dict:
    """{channel: {"day", "run"}} — today's safety room (guidance: the absorbed load under the
    weekly ceiling after what was done today; the per-run ceiling), with today's cuts."""
    out = {}
    drift = ctx.get("drift") or {}
    for c in CHS:
        ch = (ctx.get("channels") or {}).get(c) or {}
        f = (drift.get(c) or 1.0) * ((ctx.get("intFactor") or 1.0) if c == "intensity" else 1.0)
        out[c] = {"day": None if ch.get("day") is None else ch["day"] * f,
                  "run": None if ch.get("run") is None else ch["run"] * f}
    return out


def _future_room(ol: dict, P: dict, night: str = "good") -> dict:
    out = {}
    drift = ol.get("drift") or {}
    for c in CHS:
        nb = ((ol.get("channels") or {}).get(c) or {}).get("byNight", {}).get(night) or {}
        f = drift.get(c) or 1.0
        day = None
        if P.get(c):
            day = max(0.0, max(t[0] - t[1] for t in P[c])) * f
        run = nb.get("run")
        out[c] = {"day": day, "run": None if run is None else run * f}
    return out


def _start_terms(ol: dict, night: str = "good") -> dict:
    """[[mx, P, q]] per channel this morning (P = this morning's unabsorbed load + today's done)."""
    out = {}
    for c in CHS:
        nb = ((ol.get("channels") or {}).get(c) or {}).get("byNight", {}).get(night) or {}
        if nb.get("terms"):
            out[c] = [[mx, b, q] for mx, b, q in nb["terms"]]
    return out


def _night(P: dict, x: dict) -> dict:
    """One night on: every term keeps (P + the day's load) × its share left."""
    return {c: [[mx, (b + (x.get(c) or 0.0)) * q, q] for mx, b, q in ts] for c, ts in P.items()}


def _cap(room: dict, c: str, run: bool) -> tuple:
    r = room.get(c) or {}
    lims = [(v, by) for v, by in ((r.get("day"), "7d"), (r.get("run") if run else None, "run")) if v is not None]
    return min(lims, key=lambda t: t[0]) if lims else (None, None)


def _over(v, mx, c) -> bool:
    return mx is not None and v > mx * (1 + TOL_REL) + TOL_ABS[c]


def check(sn: dict, ld: dict, room: dict) -> list:
    """The channels over today's safety room: [{ch, plan, max, by}] (by = 7d | run)."""
    run = KINDS[sn["kind"]]["sport"] == "run"
    out = []
    for c in CHS:
        if not run and c in ("volume", "descent", "ascent"):
            continue
        mx, by = _cap(room, c, run and c != "systemic")
        v = ld.get(c) or 0.0
        if _over(v, mx, c):
            out.append({"ch": c, "plan": v, "max": max(0.0, mx), "by": by})
    return out


def fit(sn: dict, room: dict, conv: dict, base_km: float, light: dict | None = None) -> dict:
    """The smallest change that fits today's room: the hard minutes first, then the km
    (Celková zátěž included), the hills by the route. {km, z4, min, descMax, ascMax,
    changes[], fits}. `light` = a lighter version the rules asked for (pain, readiness …)."""
    k = sn["kind"]
    sp = KINDS[k]["sport"]
    changes = []
    if sp != "run":
        m0 = sn["min"] or 0.0
        m = m0 * (light or {}).get("minFactor", 1.0)
        per = conv.get("perMinRide") if sp in ("cycling", "other") else conv.get("perMinSwim")
        if sp == "strength":
            per = (conv.get("perMinSwim") or 0.0) / 4 * 6
        cs, _ = _cap(room, "systemic", False)
        if cs is not None and per and _over(m * per, cs, "systemic"):
            m = max(0.0, cs / per)
        if m < m0 - 1:
            changes.append({"k": "min", "from": _r(m0, 0), "to": _r(m, 0)})
        return {"min": _r(m, 0), "changes": changes, "fits": m >= (MIN_CROSS if sp != "strength" else 15)}
    k0, z0 = sn["km"], sn["z4"]
    km, z4 = k0, z0
    flat = False
    if light:
        km = min(km, light.get("km", km))
        if light.get("easy"):
            z4 = 0.0
        flat = bool(light.get("flat"))
    zi, _ = _cap(room, "intensity", True)
    if _over(z4, zi, "intensity"):
        z4 = max(0.0, zi)
    if k in HARD and z4 < MIN_HARD:
        z4 = 0.0
    per_km = conv.get("runPerKm") or 0.0
    extra = max(0.0, (conv.get("z4PerMin") or 0.0) - (conv.get("easyPerMin") or 0.0))
    cands = [km]
    cv, _ = _cap(room, "volume", True)
    if _over(km, cv, "volume"):
        cands.append(cv)
    cs, _ = _cap(room, "systemic", False)
    if cs is not None and per_km and _over(km * per_km + z4 * extra, cs, "systemic"):
        k_sys = (cs - z4 * extra) / per_km
        if z4 > 0 and k_sys < 0.6 * k0:           # the hard part costs the run its length → go easy instead
            z4, k_sys = 0.0, cs / per_km
        cands.append(k_sys)
    km = max(0.0, min(cands))
    scale = km / k0 if k0 else 1.0
    desc_max = asc_max = None
    d_load = (sn["desc"] * ECC) if sn.get("desc") is not None else (conv.get("descPerKm") or 0.0) * k0
    a_load = sn["asc"] if sn.get("asc") is not None else (conv.get("ascPerKm") or 0.0) * k0
    cd, _ = _cap(room, "descent", True)
    if _over(d_load * scale * (0.5 if flat else 1.0), cd, "descent"):
        desc_max = max(0.0, cd) / ECC
        changes.append({"k": "desc", "from": _r(d_load * scale / ECC, -1), "to": _r(desc_max, -1)})
    ca, _ = _cap(room, "ascent", True)
    if _over(a_load * scale * (0.5 if flat else 1.0), ca, "ascent"):
        asc_max = max(0.0, ca)
        changes.append({"k": "asc", "from": _r(a_load * scale, -1), "to": _r(asc_max, -1)})
    if km < k0 - 0.1:
        changes.insert(0, {"k": "km", "from": _r(k0), "to": _r(km)})
    if k in HARD and z0 > 0 and z4 == 0:
        changes.insert(0, {"k": "easy", "from": _r(z0, 0)})
    elif z4 < z0 - 0.5:
        changes.insert(0, {"k": "z4", "from": _r(z0, 0), "to": _r(z4, 0)})
    if flat:
        changes.append({"k": "flat"})
    return {"km": _r(km), "z4": _r(z4, 0), "descMax": _r(desc_max, -1), "ascMax": _r(asc_max, -1),
            "changes": changes, "fits": km >= MIN_RUN_KM}


def _lighten(sn: dict, ctx: dict, rules: list) -> dict | None:
    """What the rules (not the load) ask of today's session: pain 3–5 → ~70 %, easy and flat;
    a quality session the rules don't allow today → its easy version; a long run → a usual
    easy run's length."""
    k = sn["kind"]
    if KINDS[k]["sport"] != "run":
        return {"minFactor": 0.7} if ctx.get("painMod") and KINDS[k]["sport"] in ("cycling", "other") else None
    out = {}
    if ctx.get("painMod"):
        out.update({"km": sn["km"] * 0.7, "easy": True, "flat": True})
    if rules and k in HARD and k != "race":
        out["easy"] = True
    if rules and k == "long":
        out["km"] = min(out.get("km", sn["km"]), 1.1 * (ctx.get("baseKm") or 6.0))
    return out or None


# ------------------------------------------------------------------ one pass through the days
def simulate(ctx: dict, ol: dict, days: list, persist_no: bool = True, night: str = "good") -> list:
    """days[n] = the sessions of day n (0 = today's not yet done) → per session
    {verdict, over, why, fit, room, load}. Today with today's rooms and rules; then night by
    night with the outlook's coefficients (normal nights), the plan done as written."""
    P = _start_terms(ol, night)
    last_hard = ctx.get("lastHardAge")
    last_hard = None if last_hard is None else -last_hard
    hard_days = [-a for a in (ctx.get("hardAges") or [])]
    t0 = _d(ctx["date"])
    nd = ctx.get("noDay")
    nscore = next((x["score"] for x in ol.get("nights") or [] if x["key"] == night), 100)
    out = []
    for n, sess in enumerate(days):
        d = t0 + timedelta(days=n)
        room = today_room(ctx) if n == 0 else _future_room(ol, P, night)
        room = {c: dict(v) for c, v in room.items()}
        day_load = {c: 0.0 for c in CHS}
        res_day = []
        for sn in sorted(sess, key=lambda s: s["seq"]):
            k = sn["kind"]
            sp = KINDS[k]["sport"]
            ld = load(sn, ctx.get("conv") or {})
            snap = {c: {kk: _r(vv, 2) for kk, vv in room[c].items()} for c in CHS}
            res = {"n": n, "date": d.isoformat(), "load": ld, "room": snap, "over": [], "why": [], "fit": None}
            if k == "rest":
                res["verdict"] = "rest"
                res_day.append(res)
                continue
            no = None
            if nd and (n == 0 or (persist_no and nd.get("kind") in NO_PERSIST)):
                if sp == "run" or nd.get("kind") == "red_flag" or (sp == "strength" and nd.get("kind") in NO_PERSIST):
                    no = nd["why"]
            if no:
                res.update({"verdict": "no", "why": [no]})
                res_day.append(res)
                continue
            rules = []
            if n == 0:
                rules = list((ctx.get("rules") or {}).get(KINDS[k]["app"] or "", []))
                if ctx.get("painMod") and sp == "run":
                    rules.insert(0, ctx["painMod"])
            else:
                if k in HARD and k != "race":
                    if last_hard is not None and n - last_hard < HARD_GAP:
                        rules.append("Méně než 48 h po tvrdém tréninku.")
                    cnt = sum(1 for h in hard_days if n - 7 < h < n)
                    if cnt >= (ctx.get("hardCap") or 3):
                        rules.append(f"Už {cnt} tvrdé tréninky za 7 dní.")
                    if ctx.get("noQualityUntil") and d.isoformat() <= ctx["noQualityUntil"]:
                        rules.append("Návrat po zranění — zatím bez intenzity.")
                if (k in HARD or k == "long") and ctx.get("raceRecoveryUntil") and d.isoformat() < ctx["raceRecoveryUntil"]:
                    rules.append("Zotavení po závodě — bez intenzity a dlouhého běhu.")
                if n == 1 and ((k in HARD and k != "race") or k == "long") and nscore < (ctx.get("readyQuality") or 65):
                    rules.append(f"Po takové noci připravenost kolem {nscore} % — na tvrdý nebo dlouhý trénink je potřeba "
                                 f"aspoň {ctx.get('readyQuality') or 65} %.")
            if k == "race":
                res.update({"verdict": "ok" if not rules else "mod", "why": rules})
            else:
                over = check(sn, ld, room)
                light = _lighten(sn, ctx, rules) if (rules or (n == 0 and ctx.get("painMod"))) else None
                f = fit(sn, room, ctx.get("conv") or {}, ctx.get("baseKm") or 6.0, light) if (over or light) else None
                res.update({"over": [{**o, "plan": _r(o["plan"], 1), "max": _r(o["max"], 1)} for o in over],
                            "why": rules, "fit": f, "verdict": "mod" if (over or rules) else "ok"})
            res_day.append(res)
            if k in HARD and res["verdict"] != "no":
                last_hard = n
                hard_days.append(n)
            for c in CHS:                       # the next session of the day has what is left
                day_load[c] += ld.get(c) or 0.0
                if room[c]["day"] is not None:
                    room[c]["day"] = max(0.0, room[c]["day"] - (ld.get(c) or 0.0))
        out.append(res_day)
        counted = {c: 0.0 for c in CHS}
        for sn, res in zip(sorted(sess, key=lambda s: s["seq"]), res_day):
            if res["verdict"] != "no":
                for c in CHS:
                    counted[c] += res["load"].get(c) or 0.0
        P = _night(P, counted)
    return out


def _fits_whole(res: dict) -> bool:
    return res["verdict"] in ("ok", "rest")


def find_move(ctx: dict, ol: dict, days: list, n0: int, i0: int, ahead: int = 6) -> dict | None:
    """The first day after n0 (within `ahead`) where the session fits whole — moved to an
    empty / rest day, or swapped with that day's sessions when those fit day n0."""
    sess = sorted(days[n0], key=lambda s: s["seq"])
    s = sess[i0]
    base = simulate(ctx, ol, days)
    for n in range(n0 + 1, min(len(days), n0 + ahead + 1)):
        other = [x for x in days[n] if x["kind"] != "rest"]
        new = [list(dd) for dd in days]
        new[n0] = [x for x in days[n0] if x is not s] + other
        new[n] = [s]
        sim = simulate(ctx, ol, new)
        moved = next((r for r, x in zip(sim[n], sorted(new[n], key=lambda q: q["seq"])) if x is s), None)
        if moved is None or not _fits_whole(moved):
            continue
        if other:
            back = [r for r, x in zip(sim[n0], sorted(new[n0], key=lambda q: q["seq"])) if any(x is o for o in other)]
            if not all(_fits_whole(r) for r in back):
                continue
        # nothing later in the plan may break because of the move
        later_bad = sum(1 for m in range(n + 1, len(sim)) for r in sim[m] if not _fits_whole(r) and r["verdict"] != "no")
        base_bad = sum(1 for m in range(n + 1, len(base)) for r in base[m] if not _fits_whole(r) and r["verdict"] != "no")
        if later_bad > base_bad:
            continue
        d = _d(ctx["date"]) + timedelta(days=n)
        return {"date": d.isoformat(), "n": n, "swap": bool(other),
                "with": [o["label"] for o in other]}
    return None


# ------------------------------------------------------------------ pairing with what was done
def _sport_ok(kind: str, act: dict) -> bool:
    sp = KINDS[kind]["sport"]
    a = "run" if act.get("run") else SPORT_OF_ACT.get(act.get("sport") or "", "other")
    if sp == "run":
        return a == "run"
    if sp == "other":
        return a != "run"
    return a == sp


def _size(sn: dict, act: dict) -> tuple:
    """(done, planned) of the session's main measure: km for runs, else minutes."""
    if KINDS[sn["kind"]]["sport"] == "run":
        return act.get("km") or 0.0, sn["km"] or 0.0
    return act.get("durationMin") or 0.0, sn["min"] or 0.0


def match(plan: list, acts: list, today: str) -> tuple:
    """Planned ↔ done, day by day: a pinned activity (activity_id; 0 = marked not done), else
    the same day's activity of the same sport, the closest in size. → (status by session id,
    activity by session id, extra activities)."""
    status, paired, used = {}, {}, set()
    by_day = {}
    for a in acts:
        if a.get("sport") == "walking":
            continue
        by_day.setdefault(a["date"], []).append(a)
    ids = {a["id"] for a in acts}
    for sn in sorted(plan, key=lambda s: (s["date"], s["seq"])):
        if sn["kind"] == "rest":
            continue
        aid = sn.get("activityId")
        if aid == 0:
            status[sn["id"]] = "missed"
            continue
        if aid and aid in ids and aid not in used:
            a = next(x for x in acts if x["id"] == aid)
        else:
            pool = [a for a in by_day.get(sn["date"], []) if a["id"] not in used and _sport_ok(sn["kind"], a)]
            if not pool:
                status[sn["id"]] = "missed" if sn["date"] < today else "planned"
                continue
            a = min(pool, key=lambda x: abs(_size(sn, x)[0] - _size(sn, x)[1]))
        used.add(a["id"])
        paired[sn["id"]] = a
        done, want = _size(sn, a)
        status[sn["id"]] = ("done" if not want or abs(done - want) <= MATCH_TOL * want
                            else "partial" if done < want else "more")
    extra = [a for a in acts if a["id"] not in used and a.get("sport") != "walking"]
    return status, paired, extra


# ------------------------------------------------------------------ the whole evaluation
def evaluate(ctx: dict, ol: dict, rows: list, acts: list, horizon: int = HORIZON) -> dict:
    """The plan from Monday of last week to `horizon` days ahead → days with their sessions,
    statuses, verdicts and suggestions; today's sessions; this week's sums."""
    today = ctx["date"]
    t0 = _d(today)
    ws = _d(ctx["weekStart"])
    first = ws - timedelta(days=7)
    last = t0 + timedelta(days=horizon)
    sns = [norm(r, ctx) for r in rows if first.isoformat() <= str(r.get("date"))[:10] <= last.isoformat()]
    acts = [a for a in acts if first.isoformat() <= a["date"] <= today]
    status, paired, extra = match([s for s in sns if s["date"] <= today], acts, today)
    days = [[] for _ in range(horizon + 1)]
    for s in sns:
        n = (_d(s["date"]) - t0).days
        if n < 0:
            continue
        if n == 0 and status.get(s["id"]) in ("done", "partial", "more", "missed"):
            continue                            # done (or marked not done) — its load is already counted
        days[n].append(s)
    sim = simulate(ctx, ol, days)
    res_by = {}
    for n, dd in enumerate(days):
        for s, r in zip(sorted(dd, key=lambda q: q["seq"]), sim[n]):
            res_by[id(s)] = (r, n)
    for n, dd in enumerate(days):
        for i, s in enumerate(sorted(dd, key=lambda q: q["seq"])):
            r, _ = res_by[id(s)]
            if r["verdict"] == "mod" and n <= 7 and s["kind"] != "race":
                r["move"] = find_move(ctx, ol, days, n, i, ahead=min(6, horizon - n))
            if r["verdict"] == "no" and n == 0:
                r["alt"] = ctx.get("alt")
    out_days = []
    d = first
    week_plan = {c: 0.0 for c in CHS}
    week_days = []
    ws_iso, we_iso = ws.isoformat(), (ws + timedelta(days=6)).isoformat()
    while d <= last:
        iso = d.isoformat()
        items = []
        for s in sorted((x for x in sns if x["date"] == iso), key=lambda q: q["seq"]):
            ld = load(s, ctx.get("conv") or {})
            item = {k: s[k] for k in ("id", "kind", "label", "title", "km", "min", "z4", "desc", "asc", "intervals",
                                      "target", "notes", "source", "est", "seq")}
            item.update({"km": _r(s["km"]), "min": _r(s["min"], 0), "z4": _r(s["z4"], 0),
                         "load": {c: _r(v, 1) for c, v in ld.items()}})
            st = status.get(s["id"]) if iso <= today else None
            if s["kind"] == "rest":
                st = "rest"
            item["status"] = st or "planned"
            a = paired.get(s["id"])
            if a:
                item["act"] = {"id": a["id"], "km": _r(a.get("km")), "min": _r(a.get("durationMin"), 0),
                               "title": a.get("title"), "z4": _r((a.get("exp") or {}).get("intensity"), 0)}
            got = res_by.get(id(s))
            if got:
                r, n = got
                item.update({"verdict": r["verdict"], "why": r["why"], "over": r["over"], "fit": r["fit"],
                             "move": r.get("move"), "alt": r.get("alt"),
                             "room": r["room"] if n == 0 else None})
            items.append(item)
            if ws_iso <= iso <= we_iso:
                for c in CHS:
                    week_plan[c] += ld.get(c) or 0.0
        ex = [{"id": a["id"], "title": a.get("title"), "sport": a.get("sport"), "run": a.get("run"),
               "km": _r(a.get("km")), "min": _r(a.get("durationMin"), 0)} for a in extra if a["date"] == iso]
        verdicts = [it.get("verdict") for it in items if it.get("verdict")]
        worst = ("no" if "no" in verdicts else "mod" if "mod" in verdicts else
                 "ok" if "ok" in verdicts else "rest" if verdicts else None)
        out_days.append({"date": iso, "wd": d.weekday(), "past": iso < today, "today": iso == today,
                         "sessions": items, "extra": ex, "verdict": worst})
        if ws_iso <= iso <= we_iso:
            week_days.append({"date": iso, "plan": {c: _r(sum((it["load"].get(c) or 0.0) for it in items), 1) for c in CHS}})
        d += timedelta(days=1)
    today_items = next((x for x in out_days if x["today"]), {"sessions": []})
    over_days = [x["date"] for x in out_days if x["date"] >= today and x["date"] <= we_iso and x["verdict"] == "mod"
                 and any(it.get("over") for it in x["sessions"])]
    return {"days": out_days, "today": today_items["sessions"], "todayExtra": today_items.get("extra") or [],
            "week": {"start": ws_iso, "plan": {c: _r(v, 1) for c, v in week_plan.items()}, "days": week_days,
                     "overDays": over_days, "has": any(x["sessions"] for x in out_days if ws_iso <= x["date"] <= we_iso)},
            "message": message(ctx, today_items["sessions"], over_days)}


# ------------------------------------------------------------------ for the coach
CH_TXT = {"volume": ("objem", "km"), "intensity": ("tvrdé minuty", "min"), "descent": ("klesání", "m"),
          "ascent": ("stoupání", "m"), "systemic": ("celková zátěž", "b.")}


def change_txt(c: dict) -> str:
    k = c["k"]
    if k == "km":
        return f"zkrátit na {_cz(c['to'])} km"
    if k == "z4":
        return f"tvrdých minut nejvýš {_cz(c['to'], 0)} místo {_cz(c['from'], 0)}"
    if k == "easy":
        return "bez tvrdé části"
    if k == "desc":
        return f"klesání do {_cz(c['to'], 0)} m"
    if k == "asc":
        return f"stoupání do {_cz(c['to'], 0)} m"
    if k == "min":
        return f"zkrátit na {_cz(c['to'], 0)} min"
    if k == "flat":
        return "po rovině"
    return ""


def message(ctx: dict, today: list, over_days: list) -> str | None:
    """A short message for the coach about today's plan (the app only suggests)."""
    s = next((x for x in today if x.get("verdict") in ("mod", "no")), None)
    if not s:
        if over_days:
            days = ", ".join(WD[_d(x).weekday()] for x in over_days[:3])
            return (f"Ahoj, Došlap mi u plánu na tento týden ukazuje, že se {days} nevejde do mých bezpečných limitů "
                    "(tělo ještě vstřebává zátěž z předchozích dní). Upravíme to?")
        return None
    what = s["label"].lower() + (f" {_cz(s['km'])} km" if s.get("km") and KINDS[s["kind"]]["sport"] == "run" else "")
    ready = ctx.get("readinessShown")
    head = f"Ahoj, dnes mám v plánu {what}"
    head += f" a připravenost {ready} %." if ready is not None else "."
    if s["verdict"] == "no":
        return f"{head} Došlap dnes doporučuje trénink vynechat ({(s.get('why') or [''])[0].rstrip('.')}). Co ty na to?"
    bits = [change_txt(c) for c in ((s.get("fit") or {}).get("changes") or [])]
    why = (s.get("why") or [None])[0]
    if s.get("over"):
        o = s["over"][0]
        lbl, unit = CH_TXT[o["ch"]]
        plan_v = o["plan"] / ECC if o["ch"] == "descent" else o["plan"]
        max_v = o["max"] / ECC if o["ch"] == "descent" else o["max"]
        why = why or f"{lbl} {_cz(plan_v, 0 if unit != 'km' else 1)} {unit} je nad dnešním bezpečným maximem {_cz(max_v, 0 if unit != 'km' else 1)} {unit}"
    mv = s.get("move")
    tail = ""
    if mv:
        wd = _d(mv["date"]).weekday()
        tail = f" Nebo ho prohodit s {WD_WITH[wd]}." if mv.get("swap") else f" Nebo ho přesunout na {WD_ACC[wd]}."
    if bits and (s.get("fit") or {}).get("fits", True):
        return f"{head} Došlap doporučuje {' · '.join(bits)} ({(why or '').rstrip('.')}).{tail} Co ty na to?"
    return f"{head} Došlap ukazuje, že se dnes nevejde ({(why or '').rstrip('.')}).{tail} Co ty na to?"


# ------------------------------------------------------------------ progress through keeping to it
def adherence(days: list, acts: list, safe_days: dict, readiness: dict, pain: dict) -> dict:
    """One week's keeping to the plan and to the limits (Fáze 3): the plan (sessions and
    km done), the safe days (each day within its morning's safety room), easy runs really
    easy (≥ 80 % of the time in Z1–Z2), hard minutes within ± 20 % of the plan, and how
    the body took it (readiness, pain from the diary). The 2×2 the owner set: plan ✓ limits ✗
    → fine if the body says so; neither → a warning; limits ✓ plan ✗ → well done, but a
    smaller training stimulus — talk to the coach."""
    planned = [s for d in days for s in d["sessions"] if s["kind"] != "rest"
               and (d["past"] or (d["today"] and s["status"] in ("done", "partial", "more")))]
    done = [s for s in planned if s["status"] in ("done", "more", "partial")]
    km_plan = sum(s["km"] or 0 for s in planned if KINDS[s["kind"]]["sport"] == "run")
    km_done = sum((s.get("act") or {}).get("km") or 0 for s in done if KINDS[s["kind"]]["sport"] == "run")
    by_id = {a["id"]: a for a in acts}
    easy_n = easy_ok = hard_n = hard_ok = 0
    for s in done:
        a = by_id.get((s.get("act") or {}).get("id"))
        if not a:
            continue
        if s["kind"] in ("easy", "recovery", "long") and a.get("zoneMin") and a.get("durationMin"):
            z = a["zoneMin"]
            easy_n += 1
            easy_ok += (1 - sum(z[2:]) / a["durationMin"]) >= EASY_SHARE
        if s["kind"] in ("quality", "hills") and s.get("z4"):
            hard_n += 1
            got = (a.get("exp") or {}).get("intensity") or 0.0
            hard_ok += abs(got - s["z4"]) <= HARD_TOL * s["z4"]
    days = [d for d in days if d["past"] or d["today"]]
    known = [safe_days.get(d["date"]) for d in days if safe_days.get(d["date"]) is not None]
    safe_n = sum(1 for v in known if v)
    n_pl = len(planned)
    pct_s = (len(done) / n_pl) if n_pl else None
    pct_km = (km_done / km_plan) if km_plan else None
    plan_ok = None if not n_pl else (pct_s >= PLAN_OK and (pct_km is None or PLAN_OK <= pct_km <= 1 + (1 - PLAN_OK)))
    safe_ok = None if not known else safe_n == len(known)
    rd = [readiness[d["date"]] for d in days if readiness.get(d["date"]) is not None]
    pn = [pain[d["date"]] for d in days if pain.get(d["date"]) is not None]
    feel_ok = (not rd or sum(rd) / len(rd) >= 65) and (not pn or max(pn) < 3)
    quad = None if plan_ok is None or safe_ok is None else \
        ("both" if plan_ok and safe_ok else "plan" if plan_ok else "safe" if safe_ok else "neither")
    msg = {
        "both": ("good", "Plán i bezpečné limity držíte — přesně tak se kapacita buduje."),
        "plan": (("ok", "Plán držíte, bezpečné limity ne. Pokud se cítíte dobře, je to v pořádku — sledujte připravenost a bolest.")
                 if feel_ok else
                 ("warn", "Plán držíte, ale bezpečné limity ne a tělo ukazuje únavu nebo bolest. Proberte s trenérem lehčí týden.")),
        "safe": ("praise", "Výborně, bezpečné limity držíte. Plán ale ne — menší tréninkový podnět může znamenat pomalejší "
                           "progres. Poraďte se s trenérem."),
        "neither": ("warn", "Pozor: týden nesedí s plánem a zároveň přetáhl bezpečné limity. Proberte to s trenérem."),
    }.get(quad)
    return {"start": days[0]["date"] if days else None, "sessions": [len(done), n_pl], "km": [_r(km_done), _r(km_plan)],
            "pct": _r(pct_s * 100, 0) if pct_s is not None else None, "pctKm": _r(pct_km * 100, 0) if pct_km is not None else None,
            "safe": [safe_n, len(known)], "easy": [easy_ok, easy_n], "hard": [hard_ok, hard_n],
            "readiness": _r(sum(rd) / len(rd), 0) if rd else None, "painMax": max(pn) if pn else None,
            "planOk": plan_ok, "safeOk": safe_ok, "quad": quad, "tone": msg[0] if msg else None, "msg": msg[1] if msg else None}
