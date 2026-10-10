"""Owner feedback 2026-10-10 — the Trénink tab's outlook for TOMORROW.

Today's allowance (guidance.py) is the tightest of this calendar week's target, the room
under the weekly ceiling of the absorbed load and the per-run ceiling, with Celková zátěž
(HR × time, all sports) turned into km / Z4+ minutes. The outlook carries the same limits
one night forward, for what is still done today and how the night goes:

  • absorbed load (capacity.absorbed_room): tomorrow morning every channel keeps
    (this morning's unabsorbed load + today's sessions + what is still done today) × the
    night's share left — muscles / tendons on the fixed 3.5-night half-life, the cardio
    channels (Celková zátěž, Z4+) by the night's readiness (half_for_readiness) and never
    more than RESIDUAL_CAP × the nominal absorption;
  • the weekly ceiling follows the 7-day mean readiness, which gains tomorrow's night and
    loses the day that leaves the window; the per-run ceiling takes tomorrow's readiness;
  • the plan: what's left of this week's target after today, or next week's target on a
    Monday (the cycle's next step).

Exported as coefficients — room(x) = max(0, max_i(mx_i − (base_i + x) · q_i^n)) per
channel and night — so the app can answer any "what if" (run X km, ride Y min) on the
spot; `evaluate` is the reference the app mirrors, `grid` its precomputed answers. An
estimate: the capacity itself, the body state and new pain can still change overnight.
"""
from datetime import date, timedelta

from . import capacity as C

CHS = ("volume", "intensity", "descent", "ascent", "systemic")
MSK = ("volume", "descent", "ascent")
# the night scenarios: signals in the runner's norm, like this morning, a weaker night
# (shorter sleep and lower HRV — readiness_from of these deficits ≈ 64 %)
WEAK_PARTS = {"hrv": 0.3, "sleep": 0.3}
DRIFT_CUT = {"volume": 0.8, "intensity": 0.5, "descent": 0.5}


def night_scenarios(cap: dict) -> list:
    """[{key, label, score, factor{channel}}] — the readiness tomorrow morning in three cases."""
    rd = cap.get("readiness") or {}
    chs = cap.get("channels") or {}
    m_score = rd.get("morningScore", rd.get("score", 100))
    wf, ws = C.readiness_from(WEAK_PARTS)
    weak = {c: C.channel_readiness((wf, WEAK_PARTS, ws), c) for c in CHS}
    return [
        {"key": "good", "label": "Noc v normě", "score": 100, "factor": {c: 1.0 for c in CHS}},
        {"key": "today", "label": "Jako dnešní noc", "score": m_score,
         "factor": {c: (chs.get(c) or {}).get("readinessFactor") or 1.0 for c in CHS}},
        {"key": "weak", "label": "Slabší noc", "score": ws, "factor": weak},
    ]


def _terms(c, gw: dict, cw: dict, night: dict) -> list | None:
    """[[mx, base, q]] — tomorrow's room under the weekly ceiling as max(mx − (base + x)·q)."""
    mx, k = cw.get("absorbedMax"), cw.get("absorbK")
    if mx is None or not k or gw.get("ceiling7") is None:
        return None
    inp = cw.get("inputs") or {}
    wr, drop = inp.get("ready") or 1.0, inp.get("readyDrop") or 1.0
    f = night["factor"][c]
    mx_t = mx * (wr + (f - drop) / 7) / wr
    t0 = gw.get("doneToday") or 0.0
    if c in MSK:
        return [[mx_t, (gw.get("absorbedPast") or 0.0) + t0, 1 - k]]
    r = C._k(C.half_for_readiness(night["score"]))
    lvl = cw.get("absorbedLevel", gw.get("absorbedPast") or 0.0)
    nom = cw.get("absorbedNominal", lvl)
    return [[mx_t, lvl + t0, 1 - r], [mx_t / C.RESIDUAL_CAP, nom + t0, 1 - k]]


def build(*, cap: dict, week: dict, today: date, plan_next: dict, conv: dict, novice: bool, drift: bool,
          presets: list, min_run: float, base_km: float, last_hard_age: int | None, hard_gap: int,
          ready_quality: int) -> dict:
    chs = cap.get("channels") or {}
    nights = night_scenarios(cap)
    to_monday = 7 - today.weekday()                  # days from today to next Monday (1–7)
    channels = {}
    for c in CHS:
        gw, info = week.get(c) or {}, chs.get(c) or {}
        cw = info.get("week") or {}
        rf = info.get("readinessFactor") or 1.0
        ceil_run = info.get("ceilingToday") if (c != "systemic" and not (novice and c != "volume")) else None
        by = {}
        for n in nights:
            by[n["key"]] = {"terms": _terms(c, gw, cw, n),
                            "run": None if ceil_run is None else ceil_run / rf * n["factor"][c]}
        left = None if gw.get("budget") is None else max(0.0, gw["budget"] - (gw.get("done") or 0.0))
        channels[c] = {"unit": gw.get("unit"), "dec": C.CHANNELS[c]["dec"], "planLeft": left,
                       "planNext": plan_next.get(c), "byNight": by}
    ol = {"date": (today + timedelta(days=1)).isoformat(), "toMonday": to_monday, "minRunKm": min_run,
          "baseKm": base_km, "novice": novice, "drift": DRIFT_CUT if drift else None,
          "nights": [{k: n[k] for k in ("key", "label", "score")} for n in nights],
          "conv": conv, "channels": channels,
          "hard": {"lastAge": last_hard_age, "gap": hard_gap, "readyQuality": ready_quality, "z4Min": 10}}
    for p in presets:
        p["x"] = load_of(ol, p["act"])
    ol["presets"] = presets
    ol["grid"] = {p["key"]: {n["key"]: verdict(ol, p, n["key"]) for n in ol["nights"]} for p in presets}
    ol["restRun"] = next_run_day(ol, "today")
    return _round(ol)


def load_of(ol: dict, act: dict) -> dict:
    """Per-channel load of what is still done today — act = {runKm, z4, rideMin, swimMin}
    (the app's what-if inputs; a run's Celková zátěž from the runner's own easy runs plus
    the extra of its Z4+ minutes, its hills at the usual metres per km)."""
    cv = ol["conv"]
    run_km, z4 = act.get("runKm") or 0.0, act.get("z4") or 0.0
    ride_min, swim_min = act.get("rideMin") or 0.0, act.get("swimMin") or 0.0
    per_km = cv.get("runPerKm") or 0.0
    easy_pm = cv.get("easyPerMin") or 0.0
    return {"volume": run_km, "intensity": z4,
            "descent": run_km * (cv.get("descPerKm") or 0.0), "ascent": run_km * (cv.get("ascPerKm") or 0.0),
            "systemic": run_km * per_km + z4 * max(0.0, (cv.get("z4PerMin") or 0.0) - easy_pm)
            + ride_min * (cv.get("perMinRide") or 0.0) + swim_min * (cv.get("perMinSwim") or 0.0)}


def evaluate(ol: dict, x: dict, night: str, n: int = 1) -> dict:
    """{channel: {max, lim, bound, safe}} on the n-th day from today (tomorrow = 1) after `x`
    more today and nights like `night` — today's rules (guidance.build_guidance) on that day."""
    out = {}
    new_week = n >= ol["toMonday"]
    for c, ch in ol["channels"].items():
        nb = ch["byNight"][night]
        xc = x.get(c, 0.0) or 0.0
        room = None
        if nb["terms"]:
            room = max(0.0, max(mx - (b + xc) * q ** n for mx, b, q in nb["terms"]))
        plan = ch["planNext"] if new_week else (None if ch["planLeft"] is None else max(0.0, ch["planLeft"] - xc))
        lims = {k: v for k, v in (("week", plan), ("7d", room), ("run", nb["run"])) if v is not None}
        lim = min(lims, key=lambda k: (lims[k], k == "week")) if lims else None
        safe = [v for v in (room, nb["run"]) if v is not None]
        out[c] = {"max": lims[lim] if lim else None, "lim": lim,
                  "bound": None if lim is None else "plan" if lim == "week" else "safety",
                  "safe": min(safe) if safe else None}
    if not ol["novice"]:
        cv, sysw = ol["conv"], out["systemic"]
        for c, per in (("volume", cv.get("perKm")), ("intensity", cv.get("z4PerMin"))):
            if not per:
                continue
            if sysw["max"] is not None and (out[c]["max"] is None or sysw["max"] / per < out[c]["max"]):
                out[c].update({"max": sysw["max"] / per, "lim": "systemic", "bound": sysw["bound"]})
            if sysw["safe"] is not None and (out[c]["safe"] is None or sysw["safe"] / per < out[c]["safe"]):
                out[c]["safe"] = sysw["safe"] / per
        vol = out["volume"]
        for c in ("descent", "ascent"):
            p90 = (cv.get("hillP90") or {}).get(c)
            if p90 is not None and vol["lim"] == "systemic" and vol["max"] is not None:
                if out[c]["max"] is None or vol["max"] * p90 < out[c]["max"]:
                    out[c].update({"max": vol["max"] * p90, "lim": "systemic", "bound": vol["bound"]})
    for c, f in (ol.get("drift") or {}).items():
        if out[c]["max"] is not None:
            out[c].update({"max": out[c]["max"] * f, "lim": "mechanics", "bound": "safety"})
        if out[c]["safe"] is not None:
            out[c]["safe"] *= f
    return out


def verdict(ol: dict, preset: dict, night: str) -> dict:
    """Tomorrow after `preset` today: the channels plus whether a run / a quality session /
    a long run fit (the load side of guidance's rules — the session spacing and readiness)."""
    ev = evaluate(ol, preset["x"], night)
    score = next(n["score"] for n in ol["nights"] if n["key"] == night)
    vol, z4 = ev["volume"]["max"], ev["intensity"]["max"]
    hard = ol["hard"]
    hard_today = (preset["x"].get("intensity") or 0) >= hard["z4Min"]
    age = 0 if hard_today else hard["lastAge"]
    gap_ok = age is None or age + 1 >= hard["gap"]
    # a quality session needs at least half a usual easy run of room, as today (guidance)
    return {"ch": ev, "run": vol is None or vol >= ol["minRunKm"],
            "quality": bool(z4 is not None and z4 >= hard["z4Min"] and gap_ok and score >= hard["readyQuality"]
                            and (vol is None or vol >= max(ol["minRunKm"], 0.5 * ol["baseKm"]))),
            "long": bool((vol is None or vol >= 1.2 * ol["baseKm"]) and score >= hard["readyQuality"])}


def next_run_day(ol: dict, night: str, x: dict | None = None, horizon: int = 7) -> dict | None:
    """The first day (tomorrow on) whose volume allowance fits a run, with nothing more today."""
    x = x or {}
    for n in range(1, horizon + 1):
        v = evaluate(ol, x, night, n)["volume"]
        if v["max"] is None or v["max"] >= ol["minRunKm"]:
            d = date.fromisoformat(ol["date"]) + timedelta(days=n - 1)
            return {"date": d.isoformat(), "n": n, "km": v["max"], "lim": v["lim"]}
    return None


def _round(o):
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    return o
