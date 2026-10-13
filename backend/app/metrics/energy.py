"""Plan k cíli 2.0 #17 (owner decision 2026-10-13): energy availability and bone health.

Elite distance runners without a period or with low testosterone had about 4.5× more bone
stress injuries (Heikura et al., 2017); low energy availability is common, around 45 % of
athletes (Gallant et al., 2024); in men each point of the risk score raised the bone stress
injury risk by 37 % (Kraus et al., 2018). So for a long or a high-volume goal plan (over 12
weeks or over 40 km a week) the app offers a short screen — opt-in, the runner may decline:

  • a past bone stress injury (stress fracture or stress reaction) → the plan's weekly and
    per-run margins × 0.8 and one more reserve week for illness and bad weeks;
  • no period for 90 days or more (the answer, or the cycle log in the profile without
    hormonal contraception) → the plan stops growing (the weeks hold the runner's level)
    and recommends a sports doctor; the hold ends with an answer "no" or a logged period;
  • signs of low energy (unintended weight loss, eating less than training needs, tired or
    ill often) → a note with the recommendation, no change to the plan.

Stored in runners.planner_json["energy"] = {"at", "bsi", "period", "fuel", "declined"}.
"""
from datetime import date

AMEN_DAYS = 90
ASK_WEEKS = 12
ASK_KM = 40.0
BSI_MARGIN = 0.8
SOURCES = ["heikura-et-al-2017", "gallant-et-al-2024", "kraus-et-al-2018"]


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def answers(runner) -> dict:
    return dict(((getattr(runner, "planner_json", None) or {}).get("energy")) or {})


def period_gap(runner, today: date) -> int | None:
    """Days since the last logged period start for a woman logging her cycle without hormonal
    contraception; None without the log."""
    if (getattr(runner, "sex", None) or "") != "female":
        return None
    mj = getattr(runner, "menstrual_json", None) or {}
    if not mj.get("track") or mj.get("hormonal") or not mj.get("starts"):
        return None
    try:
        last = max(_d(x) for x in mj["starts"])
    except ValueError:
        return None
    return (today - last).days


def state(runner, today: date) -> dict:
    """{bsi, hold: {why, auto} | None, fuel, answered, declined} for the plan and the card."""
    e = answers(runner) if runner is not None else {}
    gap = period_gap(runner, today) if runner is not None else None
    auto = gap is not None and gap >= AMEN_DAYS
    # a period logged after the answer ends a "yes"
    logged_after = gap is not None and bool(e.get("at")) and gap < (today - _d(e["at"])).days
    said = bool(e.get("period")) and not logged_after
    hold = None
    if auto or said:
        hold = {"auto": auto, "days": gap if auto else None,
                "why": (f"podle záznamu cyklu {gap} dní bez menstruace" if auto else "menstruace chybí 3 měsíce a déle")}
    return {"bsi": bool(e.get("bsi")), "fuel": bool(e.get("fuel")), "hold": hold,
            "answered": bool(e.get("at")) and not e.get("declined"), "declined": bool(e.get("declined")),
            "at": e.get("at")}


def ask(runner, res: dict | None) -> bool:
    """Offer the screen: a plan over 12 weeks or over 40 km a week, not answered or declined yet."""
    if runner is None or not res:
        return False
    e = answers(runner)
    if e.get("at"):
        return False
    plan = res.get("plan") or []
    weeks = res.get("weeksToGoal") or len(plan)
    peak = max((w.get("km") or 0 for w in plan), default=0)
    return weeks > ASK_WEEKS or peak > ASK_KM
