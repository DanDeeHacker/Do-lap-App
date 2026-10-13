"""Plan k cíli 2.0 #11 (owner decision 2026-10-13): the hard sessions by the goal's phase, its kind
and the runner's level, in place of the generic intervals / tempo pair.

  base      easy running, strides and short hill sprints (one hard session at most)
  build     1–2 quality sessions: tempo, threshold, intervals
  specific  a road race: race-pace blocks (the marathon's inside the long run); a trail: uphill
            intervals and descent technique; an ultra: two long days in a row
  taper     intensity and the number of runs stay, the sessions get shorter (Bosquet 2007)

A recreational goal is pyramidal (about 75–80 % easy, 15–20 % moderate, up to 10 % hard; at least
70 % easy: Campos 2021; recreational runners train pyramidal and their performance goes with the
moderate volume: Bonato 2026); a time goal of an experienced runner pyramidal in the base and
polarised in the specific phase (Filipas 2021; Rosenblat 2025). Everything stays under the day's
intensity ceiling — these only shape the minutes the guidance already allows."""

ULTRA_KM = 50.0
SOURCES = ["campos-et-al-2021", "bonato-et-al-2026", "filipas-et-al-2021", "rosenblat-et-al-2025", "bosquet-et-al-2007"]


def _hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def ctx_of(goal: dict, phase: str | None, experienced: bool, taper: bool = False) -> dict:
    """What the session texts need from the goal: its kind, aim, race pace and the phase."""
    from .goal_plan import is_trail
    km = goal.get("km") or 0
    kind = "free" if goal.get("kind") == "free" else "ultra" if km >= ULTRA_KM else "trail" if is_trail(goal) else "road"
    mp = (goal["targetTimeS"] / km) if (goal.get("aim") == "time" and goal.get("targetTimeS") and km) else None
    return {"phase": "taper" if taper else (phase or "base"), "kind": kind, "aim": goal.get("aim") or "finish",
            "km": km, "mp": round(mp) if mp else None, "polar": bool(experienced and goal.get("aim") == "time")}


def _reps(m: float, rep: int, lo: int = 2) -> int:
    return max(lo, int(m) // rep)


def session(ctx: dict | None, m: float, k: int) -> str | None:
    """The k-th hard session of the week for `m` minutes of hard running; None = the generic one."""
    if not ctx:
        return None
    m = max(6.0, float(m))
    ph, kind = ctx["phase"], ctx["kind"]
    tail = "; rozklus 15 min a výklus 10 min v Z1–Z2"
    if ph == "base":
        return ("8–10 × 10–15 s do kopce svižně (ne naplno), dolů chůzí; zbytek běhu lehce v Z2. "
                "Krátké kopce budují sílu bez velké únavy" + tail)
    if ph == "taper":
        if ctx.get("mp"):
            return f"{_reps(m, 4, 3)} × 3–4 min v závodním tempu {_hms(ctx['mp'])} /km, mezi úseky 2 min volně" + tail
        return f"{_reps(m, 4, 3)} × 3 min v Z4, mezi úseky 2 min volně — intenzita zůstává, úseky jsou kratší" + tail
    if ph == "specific":
        if kind in ("trail", "ultra") and k % 2 == 0:
            n = max(4, min(10, int(m) // 3))
            return (f"{n} × 3 min do kopce v Z4, dolů volným klusem a s technikou seběhu: krátké rychlé kroky, "
                    "pohled 3–4 m dopředu, paže do stran" + tail)
        if kind == "road" and ctx.get("mp") and k % 2 == 0:
            rep = 10 if ctx["km"] >= 40 else 8
            return f"{_reps(m, rep)} × {rep} min v závodním tempu {_hms(ctx['mp'])} /km, mezi úseky 2–3 min volně" + tail
        if ctx.get("polar"):
            return f"{_reps(m, 4, 4)} × 4 min v Z5, mezi úseky 3 min volným klusem" + tail
    # build (and the specific phase's second session): pyramidal = threshold first
    if ctx.get("polar") and k % 2 == 0:
        rep = 2 if m < 12 else 3 if m < 20 else 4
        return f"{_reps(m, rep, 3)} × {rep} min v Z4–Z5, mezi úseky 2–3 min volným klusem" + tail
    if k % 2 == 0 or not ctx.get("polar"):
        rep = 6 if m < 20 else 8 if m < 32 else 10
        return (f"{_reps(m, rep)} × {rep} min na prahu (Z3–Z4: zvládnete krátké věty), mezi úseky 2 min volně"
                + tail)
    return None


def long_note(ctx: dict | None, long_km: float | None, fuel: int | None = None, gi_bad: bool = False) -> str | None:
    """The long run's purpose in the goal's specific phase, and the fuelling practice (#15)."""
    if not ctx or not long_km:
        return None
    parts = []
    if ctx["phase"] == "specific":
        if ctx["kind"] == "road" and ctx["km"] >= 40 and ctx.get("mp"):
            x = max(3, min(12, round(0.3 * long_km)))
            parts.append(f"Posledních {x} km dlouhého běhu v závodním tempu {_hms(ctx['mp'])} /km, jen když se cítíte dobře.")
        elif ctx["kind"] == "road" and ctx.get("mp"):
            parts.append(f"Ke konci dlouhého běhu 2 × 10 min v závodním tempu {_hms(ctx['mp'])} /km.")
        elif ctx["kind"] == "ultra":
            parts.append("Dva dlouhé dny po sobě: druhý den středně dlouhý běh (asi 60 % prvního) pomalu, i s chůzí do kopců.")
        elif ctx["kind"] == "trail":
            parts.append("V terénu s převýšením: do prudkých kopců klidně svižnou chůzí, seběhy s kontrolou.")
    if fuel:
        parts.append(f"Trénink příjmu: {fuel} g sacharidů za hodinu (gely, nápoj), první dávka po 20–30 min, pak každých 15–20 min.")
        if gi_bad:
            parts.append("Minule potíže s trávením: o 10–20 g/h méně a přidávejte postupně.")
    return " ".join(parts) or None


def distribution(ctx: dict | None) -> str | None:
    if not ctx:
        return None
    if ctx.get("polar"):
        return ("Rozložení intenzity: v základu pyramidově (hodně lehce, část tempa a prahu, málo tvrdě), ve specifické fázi "
                "polarizovaně: víc lehkého běhu a krátké tvrdé úseky, méně středního tempa.")
    return "Rozložení intenzity: zhruba 75–80 % lehce, 15–20 % středně (tempo, práh), do 10 % tvrdě."
