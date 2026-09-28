"""The runner facts packet for the assistant: engine output only, sliced by the
question's intent (selector.py). Same privacy rule as the Phase 1 packets
(coach_facts.py): derived values only — no name, e-mail, place, coordinates,
activity titles or free-text notes leave the server. Numbers are Czech-formatted
so the model copies them instead of recomputing."""
from datetime import date

from .. import models
from ..metrics import coach_facts as F
from ..metrics import engine as E
from ..metrics import guidance as G

PART_LABEL = {"hrv": "HRV pod normou", "rhr": "klidový tep nad normou", "sleep": "kratší nebo horší spánek",
              "soreness": "svalová bolest z check-inu", "fatigue": "únava z check-inu", "stress": "stres mimo trénink"}
MECH_IDS = {"tavr", "gct", "cad", "vosc", "bal", "dec", "gaitcv", "stiffness"}
CH_LABEL = {"volume": "objem", "intensity": "intenzita", "descent": "klesání", "ascent": "stoupání",
            "systemic": "celková zátěž", "strength": "silová zátěž"}


def _state(db, rid, a) -> dict:
    d = F.daily_facts(db, rid, a)
    out = {"date": d["date"], "weekday": d["weekday"], "state": d["state"], "referral": d["referral"],
           "signals": d["signals"]}
    scr = a.get("screening") or {}
    flags = {}
    if scr.get("boneStress"):
        flags["boneStressWarning"] = {"site": scr["boneStress"]["site"], "what": scr["boneStress"]["what"]}
    if scr.get("bonePain"):
        flags["bonePain"] = {"site": scr["bonePain"]["site"], "pain": scr["bonePain"]["pain"],
                             "repeated": scr["bonePain"]["repeated"]}
    if scr.get("ill"):
        flags["illToday"] = True
    if a.get("cluster"):
        flags["fatigueIllnessCluster"] = a["cluster"]["parts"]
    if flags:
        out["safety"] = flags
    return out


def _types(a) -> dict | None:
    g = a.get("guidance") or {}
    types = g.get("types") or {}
    if not types:
        return None
    out = {}
    for k, t in types.items():
        row = {"label": t.get("label"), "allowed": bool(t.get("allowed"))}
        if not t.get("allowed") and t.get("why"):
            row["whyNot"] = F.cz_text(t["why"])
        km = t.get("km") or {}
        if t.get("allowed") and (km.get("hi") or 0) > 0:
            row["km"] = f"{G._cz(km.get('lo'), 1)}–{G._cz(km.get('hi'), 1)} km"
        if t.get("allowed") and t.get("hr"):
            row["hr"] = f"{t['hr'][0]}–{t['hr'][1]} tepů/min"
        if t.get("durationMin") and t.get("cross"):
            row["durationMin"] = f"{t['durationMin'][0]}–{t['durationMin'][1]} min"
        if t.get("rpeTarget"):
            row["rpeTarget"] = t["rpeTarget"]
        out[k] = row
    return out


def _today_extra(a) -> dict:
    g = a.get("guidance") or {}
    out = {}
    if g.get("heat"):
        out["heat"] = {"feelsMaxC": g["heat"]["feelsMax"], "hotRuns14d": g["heat"]["hot14"], "stage": g["heat"]["stage"]}
    if g.get("hardWeek"):
        out["hardSessionsLast7d"] = {"done": g["hardWeek"]["done"], "weeklyCap": g["hardWeek"]["cap"]}
    s = g.get("strength") or {}
    if s:
        out["strengthThisWeek"] = {"done": s.get("done"), "target": s.get("target"),
                                   "lastDaysAgo": s.get("lastAge"), "newBlock": bool(s.get("newBlock"))}
    pat = g.get("pattern") or {}
    if pat:
        out["pattern"] = {"runDays": pat.get("runDayNames"), "longRunDay": pat.get("longDayName"),
                          "hardDays": pat.get("hardDayNames"), "runsPerWeek": pat.get("runsPerWeek"),
                          "easyKm": G._cz(pat.get("easyKm"), 1) if pat.get("easyKm") else None}
    return out


def _readiness(a) -> dict:
    out = F._recovery(a)
    cr = (a.get("capacity") or {}).get("readiness") or {}
    parts = {PART_LABEL.get(k, k): f"{round(v * 100)} %" for k, v in (cr.get("parts") or {}).items() if v and v > 0.05}
    if parts:
        out["whatLowersReadiness"] = parts
    return out


def _load(a) -> dict:
    out = F._load(a)
    cap = (a.get("capacity") or {}).get("channels") or {}
    for key in ("systemic", "strength"):
        c = cap.get(key) or {}
        wk = c.get("week") or {}
        if wk.get("cap"):
            out.setdefault("vsCapacity", {})[key] = {"label": c.get("label"), "unit": c.get("unit"),
                                                     "last7": G._cz(wk.get("now"), 0), "weeklyCapacity": G._cz(wk.get("cap"), 0),
                                                     "ratio": G._cz(wk.get("ratio"), 2)}
    g = a.get("guidance") or {}
    wk = g.get("week") or {}
    if wk:
        out["weekMode"] = F.WEEK_MODE.get(wk.get("mode"), wk.get("mode"))
        out["cycleWeek"] = (wk.get("cycle") or {}).get("pos")
    return out


def _runs(db, rid, a, sel) -> dict:
    acts = [x for x in E.acts(db, rid) if x.started_at]
    acts.sort(key=lambda x: x.started_at, reverse=True)
    rel = {r["date"]: r for r in ((a.get("capacity") or {}).get("relativeEffort") or {}).get("runs") or []}

    def row(x):
        r = rel.get(x.started_at[:10]) or {}
        w = x.weather_json or {}
        return {"date": F.cz_date(x.started_at), "daysAgo": (E.today_date() - date.fromisoformat(x.started_at[:10])).days,
                "km": G._cz(x.distance_km, 1) if x.distance_km else None, "pace": F.pace(x.pace_s_km),
                "avgHr": round(x.avg_hr) if x.avg_hr else None,
                "ascentM": round(x.ascent_m) if x.ascent_m else None, "descentM": round(x.descent_m) if x.descent_m else None,
                "hrVsUsualForPace": (f"{'+' if r['hrDelta'] > 0 else ''}{r['hrDelta']} tepů" if r.get("hrDelta") is not None else None),
                "effortVsUsual": r.get("band"), "hot": bool(w.get("hot")),
                "feelsC": w.get("feelsC") if w.get("precision") == "hour" else None}
    pick = None
    if sel.get("runPick", "") and str(sel["runPick"]).startswith("id:"):
        pick = next((x for x in acts if str(x.id) == str(sel["runPick"])[3:]), None)
    elif sel.get("runDay"):
        pick = next((x for x in acts if x.started_at[:10] == sel["runDay"]), None)
    elif sel.get("runPick") == "long":
        recent = [x for x in acts if (E.today_date() - date.fromisoformat(x.started_at[:10])).days <= 14]
        pick = max(recent, key=lambda x: x.distance_km or 0, default=None)
    out = {"recentRuns": [row(x) for x in acts[:5]]}
    if pick is not None:
        out["askedRun"] = row(pick)
    elif sel.get("runDay"):
        out["askedRun"] = f"V den {F.cz_date(sel['runDay'])} žádný běh nemáme."
    return out


def _plan(a) -> dict:
    out = {"races": F._races(a), "raceRecovery": F._race_recovery(a)}
    g = a.get("guidance") or {}
    wk = g.get("week") or {}
    cyc = wk.get("cycle") or {}
    if cyc:
        out["cycle"] = {"week": cyc.get("pos"), "manual": bool(cyc.get("manual"))}
    chs = wk.get("channels") or {}
    vol = chs.get("volume") or {}
    if vol:
        out["thisWeekKm"] = {"target": G._cz(vol.get("budget"), 1), "done": G._cz(vol.get("done"), 1)}
    return out


def _mechanics(a) -> dict:
    q = F.QUAD.get(a.get("quadrant"), (a.get("quadrant"), ""))
    sig = [s for s in a.get("signals") or [] if s.get("id") in MECH_IDS and (s.get("pts") or 0) > 0]
    return {"quadrant": q[0], "mechanicsScore": a.get("mech"), "flag": bool(a.get("mechFlag")),
            "signals": [{"name": s.get("name"), "value": F.cz_text(s.get("val")), "detail": F.cz_text(s.get("detail"))}
                        for s in sig[:4]]}


def build(db, rid: str, a: dict, sel: dict) -> dict:
    """The facts packet for one question."""
    out = _state(db, rid, a)
    sl = set(sel.get("slices") or [])
    if "today" in sl or "types" in sl or "strength" in sl or "heat" in sl:
        out["today"] = F._today(a)
        out.update(_today_extra(a))
    if "types" in sl or "strength" in sl:
        out["sessionTypes"] = _types(a)
    if "readiness" in sl:
        out["readiness"] = _readiness(a)
    if "load" in sl:
        out["load"] = _load(a)
    if "pain" in sl:
        out["pain"] = F._pain(a)
    if "runs" in sl:
        out["runs"] = _runs(db, rid, a, sel)
    if "plan" in sl:
        out["plan"] = _plan(a)
    if "mechanics" in sl:
        out["mechanics"] = _mechanics(a)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is not None and r.prior_injury and ("pain" in sl or "load" in sl):
        out["priorInjury"] = {"site": r.prior_injury, "monthsAgo": E.injury_months(r)}
    return {k: v for k, v in out.items() if v not in (None, {}, [])}
