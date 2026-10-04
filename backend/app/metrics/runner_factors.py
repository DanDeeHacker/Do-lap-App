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


def shoe_state(shoes, runner, today) -> dict:
    """{transition: {...}|None, rotation: {...}|None, factor} for `today`."""
    shoes = [s for s in shoes or () if s.first_used]
    trans = None
    for s in sorted(shoes, key=lambda x: x.first_used, reverse=True):
        age = (today - _d(s.first_used)).days
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
                     "since": s.first_used[:10], "day": age + 1, "days": TRANSITION_DAYS,
                     "until": (first + timedelta(days=TRANSITION_DAYS - 1)).isoformat(),
                     "dropFrom": max((b.drop_mm for b in before if b.drop_mm is not None), default=None),
                     "dropTo": s.drop_mm}
    active = [s for s in shoes if _active(s, today)]
    rotation = {"n": len(active), "names": [f"{s.brand} {s.model}".strip() for s in active]} if len(active) >= 2 else None
    return {"transition": trans, "rotation": rotation, "factor": trans["factor"] if trans else 1.0,
            "active": len(active)}
