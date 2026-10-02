"""Feedback #151 — how hard to run a race: three effort levels (training, moderate,
all-out), the level the app recommends from the runner's remaining capacity, and for
each level the pace, heart rate, perceived effort and a short strategy.

Pace per level:
  • training and moderate — the runner's own heart-rate ↔ speed line (capacity.hr_speed_fit)
    read at 75 % and 85 % of heart-rate reserve (Karvonen et al., 1957);
  • all-out — the best recent run carried to the race distance by Riegel's endurance
    formula T2 = T1 × (D2 / D1)^1.06 (Riegel, 1981), else the heart-rate line read at
    a distance-specific share of HR max (working assumption).
Climb is turned into flat-equivalent distance at 7.92 m per metre of ascent (Scarf,
2007; a rule of thumb for hill running). Effort levels, thresholds and the strategy
texts are the product team's working assumptions; the recovery days follow the
engine's max-effort rule (≈ 1 day per 3 km, 2–14 days).
"""
from datetime import date, timedelta

from . import capacity as C
from . import data as D
from . import engine as E

LEVELS = ("trénink", "střední", "naplno")
LEVEL_HRR = {"trénink": (0.65, 0.75), "střední": (0.75, 0.84)}
SLOWER = {"trénink": 1.17, "střední": 1.07}   # pace vs all-out without a HR line (working assumption)
LEVEL_RPE = {"trénink": "5–6 z 10 (dá se mluvit v krátkých větách)", "střední": "7–8 z 10 (tempo, mluvit jen pár slov)",
             "naplno": "9–10 z 10 (závodní úsilí)"}
RIEGEL = 1.06
SCARF_M = 7.92                  # flat metres per metre of ascent
BEST_DAYS, BEST_MIN_KM = 120, 3.0


def _flat_km(km, ascent):
    return (km or 0) + SCARF_M * (ascent or 0) / 1000.0


def _max_hrr(km):
    """Heart-rate-reserve band a well-paced all-out race sits in (working assumption)."""
    return (0.90, 0.97) if km <= 6 else (0.87, 0.94) if km <= 12 else (0.84, 0.91) if km <= 25 else (0.78, 0.86)


def _max_hr_share(km):
    """Share of HR max a well-paced all-out race holds on average (working assumption)."""
    return 0.95 if km <= 6 else 0.92 if km <= 12 else 0.88 if km <= 25 else 0.84


def _pace_from_speed(v):
    return round(1000 / v) if v and v > 0 else None


def _speed_at(fit, hr):
    a, b = fit
    return (hr - a) / b if b else None


def _riegel_pace(runs, km_flat, today):
    """Best predicted all-out pace for the flat-equivalent race distance from the
    runs of the last 120 days (each run's flat-equivalent distance and time)."""
    best = None
    lo = (today - timedelta(days=BEST_DAYS)).isoformat()
    for s in runs:
        if s["date"] < lo or not s.get("km") or s["km"] < BEST_MIN_KM or not s.get("durationMin"):
            continue
        d1 = s["km"] * ((s.get("gSpeed") or s.get("speed") or 0) / (s.get("speed") or 1)) if s.get("speed") else s["km"]
        t1 = s["durationMin"] * 60
        t2 = t1 * (km_flat / d1) ** RIEGEL
        if best is None or t2 < best[0]:
            best = (t2, s)
    if not best:
        return None, None
    return best[0] / km_flat, best[1]


def build(db, rid: str, runner, race: dict, assessment: dict) -> dict:
    """The race plan for one race of races_for()."""
    data = D.of(db, rid)
    today = E.today_date()
    runs_only = E.acts(data, rid, "load")
    hrmax, rhr = E.hr_bounds(runs_only, E.daily(data, rid, 180), getattr(runner, "birth_year", None),
                             getattr(runner, "hr_max", None))
    sessions = [s for s in C.run_exposures(data, rid, hrmax, rhr) if s["run"]]
    fit = C.hr_speed_fit(sessions, today.isoformat(), lo=1, hi=56)
    km = race.get("km")
    asc = race.get("ascentM") or 0
    km_flat = _flat_km(km, asc) if km else None

    levels = {}
    for lv in ("trénink", "střední"):
        lo, hi = LEVEL_HRR[lv]
        hr_lo, hr_hi = rhr + lo * (hrmax - rhr), rhr + hi * (hrmax - rhr)
        pace = None
        if fit:
            v = _speed_at(fit, (hr_lo + hr_hi) / 2)
            pace = _pace_from_speed(v)
        levels[lv] = {"hr": [E.rnd(hr_lo), E.rnd(hr_hi)], "flatPace": pace}
    rp, basis = (_riegel_pace(sessions, km_flat, today) if km_flat else (None, None))
    all_pace = round(rp) if rp else None
    if all_pace is None and fit and km:
        all_pace = _pace_from_speed(_speed_at(fit, _max_hr_share(km) * hrmax))
    m_lo, m_hi = _max_hrr(km or 10)
    levels["naplno"] = {"hr": [E.rnd(rhr + m_lo * (hrmax - rhr)), E.rnd(rhr + m_hi * (hrmax - rhr))],
                        "flatPace": all_pace,
                        "basis": ({"date": basis["date"], "km": E.r1(basis["km"]), "title": basis["title"]} if basis else None)}
    for lv in ("trénink", "střední"):            # no HR line yet: scale the all-out pace
        if levels[lv]["flatPace"] is None and all_pace:
            levels[lv]["flatPace"] = round(all_pace * SLOWER[lv])
    # a slower level can't be faster than a harder one
    if levels["naplno"]["flatPace"] and levels["střední"]["flatPace"]:
        levels["střední"]["flatPace"] = max(levels["střední"]["flatPace"], levels["naplno"]["flatPace"] + 8)
    if levels["střední"]["flatPace"] and levels["trénink"]["flatPace"]:
        levels["trénink"]["flatPace"] = max(levels["trénink"]["flatPace"], levels["střední"]["flatPace"] + 8)
    for lv in LEVELS:
        p = levels[lv]["flatPace"]
        # course pace = flat-equivalent time spread over the real distance
        levels[lv]["pace"] = round(p * km_flat / km) if p and km else p
        levels[lv]["time"] = round(p * km_flat) if p and km_flat else None
        levels[lv]["rpe"] = LEVEL_RPE[lv]
        levels[lv]["recoveryDays"] = (int(E.clamp(round(km / 3), 2, 14)) if lv == "naplno" else
                                      int(E.clamp(round(km / 6), 1, 5)) if lv == "střední" else 1) if km else None
        levels[lv]["strategy"] = _strategy(lv, km, asc, levels[lv])

    rec, why = _recommend(race, assessment, km, today)
    return {"raceId": race.get("id"), "date": race["date"], "km": km, "ascentM": asc or None,
            "levels": [{"id": lv, **levels[lv]} for lv in LEVELS],
            "recommended": rec, "why": why, "paceKnown": bool(fit or rp)}


def _strategy(lv, km, asc, L) -> list[str]:
    long = bool(km and L.get("time") and L["time"] > 75 * 60)
    out = []
    if lv == "trénink":
        out.append("Běžte celý závod v tempu, ve kterém byste zvládli ještě pár kilometrů navíc, bez finiše.")
        out.append("Hlídejte tep, ne tempo. Když tep vyleze nad horní hranici, zpomalte.")
    elif lv == "střední":
        out.append("Prvních 15 % trati lehce, pak držte rovnoměrné tempo na horní hranici pohodlí.")
        out.append("Poslední 2–3 km můžete zrychlit, jen pokud se cítíte dobře.")
    else:
        out.append("Rozklus 10–15 min a pár krátkých zrychlení. Start o 5–10 s/km pomaleji, než je cílové tempo.")
        out.append("Od poloviny držte rovnoměrné nebo mírně zrychlující tempo (negativní split).")
    if asc and km and asc / km >= 15:
        out.append("Do kopců držte úsilí, ne tempo. Z kopce volně, kontrolovaně, ať šetříte stehna.")
    if long:
        out.append("Nad 75 min pijte průběžně a doplňujte sacharidy, zhruba 30–60 g za hodinu. Vyzkoušejte to nejdřív v tréninku.")
    if lv == "naplno" and km:
        out.append(f"Po závodě počítejte s asi {L['recoveryDays']} dny lehčího tréninku, z toho první třetinu volno nebo jen procházka.")
    return out


def _recommend(race, a, km, today):
    """(level, [reasons]) from the race priority, the per-run capacity, what is left of
    the week and today's readiness / pain (the engine's own numbers)."""
    why = []
    prio = race.get("priority") or "B"
    level = "naplno" if prio in ("A", "B") else "trénink"
    why.append({"A": "cílový závod (A)", "B": "závod naplno bez ladění (B)", "C": "závod jako trénink (C)"}[prio])
    cap = (a or {}).get("capacity") or {}
    vol = (cap.get("channels") or {}).get("volume") or {}
    ceil = vol.get("ceilingSession")
    if km and ceil:
        r = km / ceil
        if r > 1.6:
            level = "trénink" if prio != "A" else "střední"
            why.append(f"trať je ×{E._cz_num(round(r, 2))} vašeho stropu jednoho běhu")
        elif r > 1.3 and level == "naplno" and prio != "A":
            level = "střední"
            why.append(f"trať je ×{E._cz_num(round(r, 2))} vašeho stropu jednoho běhu")
    g = (a or {}).get("guidance") or {}
    wk = ((g.get("week") or {}).get("channels") or {}).get("volume") or {}
    days_to = race.get("daysTo")
    try:
        d = date.fromisoformat(race["date"])
        same_week = d - timedelta(days=d.weekday()) == today - timedelta(days=today.weekday())
    except (KeyError, ValueError):
        same_week = False
    if same_week and km and wk.get("budget") is not None:
        left = (wk.get("budget") or 0) - (wk.get("done") or 0)
        if km > max(left, 0) * 1.3 and level != "trénink":
            level = "střední" if level == "naplno" else "trénink"
            why.append(f"z týdenního cíle zbývá {E._cz_num(round(max(left, 0), 1))} km")
        else:
            why.append(f"v týdnu zbývá {E._cz_num(round(max(left, 0), 1))} km z cíle")
    rd = ((cap.get("readiness") or (a or {}).get("readiness") or {}).get("score"))
    if days_to is not None and days_to <= 1 and rd is not None and rd < 65 and level != "trénink":
        level = LEVELS[LEVELS.index(level) - 1]
        why.append(f"připravenost dnes {rd} %")
    outlook = (a or {}).get("races") or {}
    if any(w.get("race") == race.get("date") for w in outlook.get("warnings") or []):
        level = "trénink"
        why.append("málo času na zotavení po předchozím maximálním úsilí")
    ps = (a or {}).get("painState") or {}
    scr = (a or {}).get("screening") or {}
    if (ps.get("daysSincePain") is not None and ps["daysSincePain"] <= 7 and not ps.get("cleared")) or scr.get("bonePain") or scr.get("boneStress"):
        level = "trénink"
        why.append("bolest v posledních 7 dnech")
    if (a or {}).get("injury", {}) and ((a or {}).get("injury") or {}).get("active"):
        level = "trénink"
        why.append("aktivní zranění: závod jen pokud ho fyzioterapeut povolí")
    if days_to is not None and days_to > 7:
        why.append("doporučení se zpřesní v týdnu závodu")
    return level, why
