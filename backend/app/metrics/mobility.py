"""Bedtime mobility in the evening report (owner request 2026-10-05).

The day's activities pick a mobility programme from the library (mobility_library.py):
a long run (≥ 1.25 × the usual easy run or ≥ 90 min), a hard run (≥ 10 min in Z4+ or
rated ≥ 7/10), an easy run, a ride, a swim, strength only, or a day without training
(the sitting day). A second sport of the day adds up to two of its exercises before the
closing breath. 3–8 exercises in all; when it's already close to the night's bedtime
target, a short version (the first two and the slow breathing). A body part the runner
marked as painful in the last 3 days is flagged on its exercises: only a mild pull, or
leave it out. Why mobility and not more: see mobility_library.py (range of motion and
the way into sleep, not injury prevention). The thresholds are working assumptions."""
from datetime import timedelta

from .. import models
from .. import programs_library as PL
from . import engine as E

MIN_EX, MAX_EX = 3, 8
SHORT_BEFORE_BED_MIN = 20     # this close to the bedtime target (or later) → the short version
LONG_KM_FACTOR, LONG_MIN = 1.25, 90
HARD_Z4_MIN, HARD_RPE = 10, 7
PAIN_DAYS = 3
DAY_PROGRAM = {"dlouhý": "mob_long", "kvalitní": "mob_quality", "lehký": "mob_run", "kolo": "mob_bike",
               "plavání": "mob_swim", "posilování": "mob_full", "sedavý": "mob_sedentary"}
KIND_LABEL = {"dlouhý": "Dlouhý běh", "kvalitní": "Tvrdý trénink", "lehký": "Lehký běh", "kolo": "Kolo",
              "plavání": "Plavání", "posilování": "Posilování", "sedavý": "Den bez tréninku"}
# painful region (as marked on the body map) → the exercise areas it touches
PAIN_AREAS = (("achill", ("lýtko", "Achillova")), ("lýtk", ("lýtko",)), ("pat", ("chodidlo", "Achillova")),
              ("plantár", ("chodidlo",)), ("chodid", ("chodidlo",)), ("kotník", ("kotník", "lýtko")),
              ("kolen", ("přední strana stehna", "kyčle (rotace)")), ("třísl", ("vnitřní strana stehen", "přední strana kyčle")),
              ("hamstring", ("zadní strana stehna",)), ("zadní strana steh", ("zadní strana stehna",)),
              ("kyčel", ("kyčle", "přední strana kyčle", "vnější strana kyčle")), ("hýžď", ("hýždě",)),
              ("bedr", ("bederní páteř", "záda", "páteř")), ("kříž", ("bederní páteř", "záda", "páteř")),
              ("záda", ("záda", "páteř", "hrudní páteř")), ("rame", ("ramen", "zadní strana ramene")), ("krk", ("krk",)))


def _cz(v, d=1) -> str:
    txt = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    return txt[:-2] if d and txt.endswith(",0") else txt


def day_kinds(acts: list, a: dict | None, today) -> list[str]:
    """The day's kinds, the main one first: the run (long / hard / easy), then a ride, a swim,
    strength; "sedavý" without any training."""
    g = (a or {}).get("guidance") or {}
    easy = ((g.get("planCtx") or {}).get("easyKm") or (g.get("pattern") or {}).get("easyKm") or 6.0)
    t_iso = today.isoformat()
    week7 = (((a or {}).get("capacity") or {}).get("channels") or {}).get("intensity", {}).get("week7") or []
    hard_ids = {x["id"] for x in week7 if x.get("date") == t_iso and (x.get("value") or 0) >= HARD_Z4_MIN}
    runs = [t for t in acts if t["run"]]
    kinds = []
    if runs:
        km = sum(t["km"] or 0 for t in runs)
        mins = sum(t["min"] or 0 for t in runs)
        if km >= LONG_KM_FACTOR * easy or mins >= LONG_MIN:
            kinds.append("dlouhý")
        elif any(t["id"] in hard_ids or (t.get("rpe") or 0) >= HARD_RPE for t in runs):
            kinds.append("kvalitní")
        else:
            kinds.append("lehký")
    sports = {t["sport"] for t in acts if not t["run"]}
    for sp, k in (("cycling", "kolo"), ("swimming", "plavání"), ("strength", "posilování")):
        if sp in sports:
            kinds.append(k)
    return kinds or ["sedavý"]


def _pain_regions(db, rid, today) -> list[str]:
    cut = (today - timedelta(days=PAIN_DAYS - 1)).isoformat()
    out = []
    for m in (models.Checkin, models.ActivityFeedback):
        for r in db.query(m).filter(m.runner_id == rid, m.submitted_at >= cut).all():
            out += [p.get("region") for p in (r.pain_points or []) if p.get("region") and (p.get("level") or p.get("pain") or 1) > 0]
    return list(dict.fromkeys(out))


def _careful(area: str, regions: list[str]) -> str | None:
    for reg in regions:
        low = reg.lower()
        for key, areas in PAIN_AREAS:
            if key in low and any(x.lower() in area.lower() for x in areas):
                return reg
    return None


def _short(now_min: int | None, bed: str | None) -> bool:
    try:
        h, m = (int(x) for x in (bed or "").split(":"))
    except ValueError:
        return False
    if now_min is None:
        return False
    bed_min = h * 60 + m + (1440 if h < 12 else 0)
    now = now_min + (1440 if now_min < 12 * 60 else 0)
    return now >= bed_min - SHORT_BEFORE_BED_MIN


def evening(db, rid: str, a: dict | None, today, acts: list, bed: str | None = None, now_min: int | None = None,
            steps: int | None = None) -> dict:
    kinds = day_kinds(acts, a, today)
    kind = kinds[0]
    prog = PL.PROGRAM_BY_KEY[DAY_PROGRAM[kind]]
    ids = list(prog["exercises"])
    extra_from = {}
    for k in kinds[1:]:
        other = PL.PROGRAM_BY_KEY[DAY_PROGRAM[k]]
        add = [x for x in other["exercises"] if x not in ids and x != "mob_breathing"][:2]
        for x in add:
            if len(ids) >= MAX_EX:
                break
            pos = ids.index("mob_breathing") if "mob_breathing" in ids else len(ids)
            ids.insert(pos, x)
            extra_from[x] = other["name"]
    short = _short(now_min, bed)
    if short:
        ids = ids[:2] + (["mob_breathing"] if "mob_breathing" in ids else ids[2:3])
    ids = ids[:MAX_EX]
    regions = _pain_regions(db, rid, today)
    out_ex = []
    for x in ids:
        e = PL.EXERCISES[x]
        careful = _careful(e["area"], regions)
        out_ex.append({"id": x, "name": e["name"], "area": e["area"], "dose": e["dose"], "how": e["how"],
                       "steps": e.get("steps") or [], "caution": e.get("caution"), "min": e["min"],
                       "extraFrom": extra_from.get(x), "careful": careful})
    runs = [t for t in acts if t["run"]]
    km = sum(t["km"] or 0 for t in runs)
    mins = {sp: sum(t["min"] or 0 for t in acts if t["sport"] == sp) for sp in ("cycling", "swimming")}
    why = {"dlouhý": f"Dnes dlouhý běh, {_cz(km)} km.", "kvalitní": "Dnes tvrdý trénink.",
           "lehký": f"Dnes lehký běh, {_cz(km)} km.", "kolo": f"Dnes kolo, {round(mins['cycling'])} min.",
           "plavání": f"Dnes plavání, {round(mins['swimming'])} min.", "posilování": "Dnes posilování.",
           "sedavý": (f"Dnes bez tréninku, {steps} kroků." if steps else "Dnes bez tréninku.")}[kind]
    also = f"K tomu {', '.join(KIND_LABEL[k].lower() for k in kinds[1:])}." if len(kinds) > 1 else None
    saved = db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid, models.SelfProgram.active.is_(True),
                                                models.SelfProgram.template == prog["key"]).first()
    minutes = sum(x["min"] for x in out_ex)
    return {"kind": kind, "kindLabel": KIND_LABEL[kind], "kinds": kinds, "why": why, "also": also, "short": short,
            "program": {"key": prog["key"], "name": prog["name"], "summary": prog["summary"], "minutes": prog["minutes"],
                        "count": len(prog["exercises"])},
            "exercises": out_ex, "minutes": minutes, "saved": saved is not None, "savedId": saved.id if saved else None,
            "painRegions": [r for r in regions if any(x["careful"] == r for x in out_ex)]}


def note(m: dict | None) -> str | None:
    if not m:
        return None
    tail = ("Do plánovaného spánku zbývá málo času, proto zkrácená verze." if m["short"] else
            "V klidu, každý cvik jen do mírného tahu, nikdy do bolesti.")
    why = f"{m['why']} {m['also']}" if m.get("also") else m["why"]
    return f"{why} {m['program']['name']}: {m['program']['summary']} Zhruba {m['minutes']} minut. {tail}"
