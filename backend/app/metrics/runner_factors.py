"""v0.12.0 — risk factors from the profile: running experience and shoes.

Experience. Novice runners got injured more than twice as often per 1000 h of running
as recreational runners (17.8 vs 7.7; Videbæk et al., 2015, meta-analysis), so in the
first year of regular running the margins above the demonstrated capacity are narrower:
× 0.8 in the first 6 months, × 0.9 from 6 to 12 months (the factors are working
assumptions, the split the meta-analysis's). The start date comes from the profile gate.

Shoes. In a randomised trial of a 26-week switch to minimalist shoes, the injury risk
rose with body mass above ~71 kg and was about doubled at 85.7 kg (HR 2.00), and pain
rose above 35 km a week (Fuller et al., 2017); a partial / full minimalist shoe brought
more injuries and shin and calf pain within 12 weeks (Ryan et al., 2014). Across
transition studies the difference is small (Warne & Gruber, 2017), so this is a
precaution: the calf, Achilles tendon and foot take the extra load of a lower drop. So for 6 weeks after
the first use of a shoe that is minimal or ≥ 4 mm lower in drop than the shoes before it,
the running channels keep a narrower margin (× 0.75, × 0.65 over 85 kg), and after a
carbon-plated racing shoe × 0.9 (case reports only: Tenforde et al., 2023 — working
assumption). Using two or more pairs in parallel went with a 39 % lower injury risk
(Malisoux et al., 2015): shown as protective, not scored.

v0.12.13 — shoes per run (run_shoe_id: the runner's pick, else the shoe paired with the run's
Garmin gear, else the default shoe). When runs are known by shoe, the transition window opens
on the first run in the new shoe (a shoe bought and left in the box isn't a transition yet),
and rotation counts the pairs actually run in: at least 2 runs each in the last 28 days.
"""
from datetime import date, timedelta

NOVICE_MONTHS = 12
EXPERIENCE_FACTORS = ((6, 0.8), (12, 0.9))   # (months below, margin factor)
TRANSITION_DAYS = 42
DROP_STEP_MM = 4.0
MINIMAL_DROP_MM = 4.0
HEAVY_KG = 85.0
SHOE_FACTOR = {"minimal": 0.75, "drop": 0.75, "carbon": 0.9}
HEAVY_FACTOR = 0.65                        # minimal / lower drop over 85 kg
CATEGORIES = ("daily", "cushioned", "stability", "racing", "minimal", "trail", "track")


def _d(s):
    return date.fromisoformat(str(s)[:10])


def experience(runner, today) -> dict | None:
    """{months, factor} for a runner in the first year of regular running, else None."""
    rs = getattr(runner, "running_since", None) if runner is not None else None
    if not rs:
        return None
    try:
        months = (today - _d(rs)).days / 30.44
    except ValueError:
        return None
    for below, f in EXPERIENCE_FACTORS:
        if months < below:
            return {"months": max(0, round(months)), "factor": f, "since": str(rs)[:10]}
    return None


ROTATION_DAYS, ROTATION_RUNS = 28, 2


def run_shoe_id(a, shoes) -> int | None:
    """The shoe of one run (Shoe.id) or None: the runner's pick (0 = none of theirs), else the
    shoe paired with the run's Garmin gear, else the default shoe in use that day."""
    if (getattr(a, "sport", None) or "running") != "running":
        return None
    pick = getattr(a, "shoe_id", None)
    if pick is not None:
        return pick or None
    gear = getattr(a, "gear_uuid", None)
    if gear:
        for s in shoes or ():
            if getattr(s, "garmin_uuid", None) == gear:
                return s.id
    day = str(a.started_at or "")[:10]
    for s in shoes or ():
        if getattr(s, "is_default", False) and s.first_used and str(s.first_used)[:10] <= day \
                and not (s.retired_at and str(s.retired_at)[:10] <= day):
            return s.id
    return None


def shoe_runs(runs, shoes) -> dict:
    """{shoe id: [run dates]} of the runs whose shoe is known."""
    out: dict = {}
    for a in runs or ():
        sid = run_shoe_id(a, shoes)
        if sid is not None and a.started_at:
            out.setdefault(sid, []).append(str(a.started_at)[:10])
    return out


def _active(s, day) -> bool:
    if not s.first_used:
        return False
    if _d(s.first_used) > day:
        return False
    return not (s.retired_at and _d(s.retired_at) <= day)


def shoe_kind(shoe, before) -> str | None:
    """Why a new shoe needs a transition: "minimal", "drop", "carbon" or None."""
    cat = (shoe.category or "").lower()
    if cat == "minimal" and not any((b.category or "").lower() == "minimal" for b in before):
        return "minimal"
    drops = [b.drop_mm for b in before if b.drop_mm is not None]
    if shoe.drop_mm is not None:
        if drops and max(drops) - shoe.drop_mm >= DROP_STEP_MM:
            return "drop"
        if not drops and shoe.drop_mm <= MINIMAL_DROP_MM:
            return "drop"                  # a low drop, the shoes before it unknown (usually 8–12 mm)
    if (shoe.carbon or cat == "racing") and not any(b.carbon or (b.category or "").lower() == "racing" for b in before):
        return "carbon"
    return None


def shoe_state(shoes, runner, today, runs=None) -> dict:
    """{transition: {...}|None, rotation: {...}|None, factor} for `today`. `runs` (the runs with
    their shoes, v0.12.13) refine both when runs are known by shoe."""
    shoes = [s for s in shoes or () if s.first_used]
    used = shoe_runs([a for a in runs or () if a.started_at and _d(a.started_at) <= today], shoes)
    trans = None
    for s in sorted(shoes, key=lambda x: x.first_used, reverse=True):
        start = min(used[s.id]) if used.get(s.id) else s.first_used
        age = (today - _d(start)).days
        if not 0 <= age < TRANSITION_DAYS or (s.retired_at and _d(s.retired_at) <= today):
            continue
        first = _d(s.first_used)
        before = [b for b in shoes if b is not s and _d(b.first_used) < first
                  and not (b.retired_at and _d(b.retired_at) < first)]
        kind = shoe_kind(s, before)
        if not kind:
            continue
        w = getattr(runner, "weight_kg", None) if runner is not None else None
        heavy = bool(w and w > HEAVY_KG and kind in ("minimal", "drop"))
        f = HEAVY_FACTOR if heavy else SHOE_FACTOR[kind]
        if trans is None or f < trans["factor"]:
            trans = {"id": s.id, "name": f"{s.brand} {s.model}".strip(), "kind": kind, "factor": f, "heavy": heavy,
                     "since": str(start)[:10], "day": age + 1, "days": TRANSITION_DAYS,
                     "until": (_d(start) + timedelta(days=TRANSITION_DAYS - 1)).isoformat(),
                     "dropFrom": max((b.drop_mm for b in before if b.drop_mm is not None), default=None),
                     "dropTo": s.drop_mm}
    active = [s for s in shoes if _active(s, today)]
    lo = (today - timedelta(days=ROTATION_DAYS - 1)).isoformat()
    recent = {sid: sum(1 for d in ds if d >= lo) for sid, ds in used.items()}
    if any(recent.values()):                   # runs known by shoe: the pairs actually run in
        active = [s for s in active if recent.get(s.id, 0) >= ROTATION_RUNS]
    rotation = {"n": len(active), "names": [f"{s.brand} {s.model}".strip() for s in active]} if len(active) >= 2 else None
    return {"transition": trans, "rotation": rotation, "factor": trans["factor"] if trans else 1.0,
            "active": len(active), "byRun": bool(used)}
