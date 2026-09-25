"""Engine v3, phase 2 — daily training GUIDANCE (the Trénink tab).

A guardrail, not a coach: it turns the runner's capacity model (capacity.py) into
safe ranges for today — which kind of session fits, how far, how hard (HR zones
and the matching pace), how much climbing/descending, on what terrain, and why.
Weekly targets follow a 4-week loading cycle; there is no day-by-day plan
(an AI coach may come later).

Rules, in order:
  1. Overrides (as agreed with the product owner):
     • active injury (OSTRC) → volno;
     • pain > 5/10 AND the engine's own physio referral (critical quadrant,
       alert tier or silent drift → triage physio_48h / physio_7d) → volno +
       book the physio;
     • pain > 5 without a referral → regenerace / cross-training, no physio push;
     • pain 3–5, or the same site hurting on ≥ 3 days in 4 weeks (even mildly)
       → the session is MODIFIED (shorter, easier, flat/soft, no long run or
       quality), never cancelled.
  2. This calendar week's TARGET per channel follows a 4-week loading cycle:
     90 % / 100 % / 110 % of the reference week (the last loaded week before the
     previous recovery week), then a recovery week at 55 % of week 3 (see
     CYCLE, cycle_position). Load ≥ 25 forces a recovery week (55 % of last
     week); taper 0.70 / 0.50 of the reference 8–14 / ≤ 7 days to the goal race.
     The runner may pick this week's place in the cycle (Runner.cycle_override,
     that calendar week only); next week the cycle re-anchors on what was run.
     A target never exceeds the capacity ceiling the Zátěž tab shows (weekly
     capacity × the week's readiness × (1 + margin)), so following the plan
     can't itself create a load exceedance.
  3. Today's allowance = the tightest of: what's left of this week's target, the
     rolling 7-day ceiling minus the last 6 days, the per-run ceiling
     (capacity.ceilingToday, scaled by today's readiness) and what's left of the
     overall load (Celková zátěž = HR × time, all sports) turned into km / Z4+
     minutes. `limitedBy` names the binding one. With the week's target met but
     the 7-day ceiling open, a short easy run stays available (not recommended).
  4. Session type by default from the runner's own pattern (usual run days,
     long-run weekday, hard days over the last 8 weeks); a quality session only
     ≥ 48 h after the last hard one, readiness ≥ 85 %, intensity budget left,
     no pain ≥ 3, Zátěž < 25 and no mechanics drift. The runner can switch type;
     every type carries its own limits and, if not advisable today, why.
Recomputed on every live recompute (sync, check-in, run rating); provisional
until today's sleep / HRV has arrived.
"""
from datetime import date, timedelta

from .. import models
from . import capacity as C
from . import engine as E

TYPES = ("volno", "regenerace", "lehký", "dlouhý", "kvalitní")
TYPE_LABEL = {"volno": "Volno", "regenerace": "Regenerační běh", "lehký": "Lehký běh",
              "dlouhý": "Dlouhý běh", "kvalitní": "Kvalitní trénink", "závod": "Den závodu"}
WD = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
WD_IN = ("v pondělí", "v úterý", "ve středu", "ve čtvrtek", "v pátek", "v sobotu", "v neděli")
HARD_Z4_MIN = 10        # a run with ≥ 10 min in Z4+ counts as a hard session
HARD_GAP_DAYS = 2       # ≥ 48 h between hard sessions
READY_QUALITY = 65      # readiness score (%) needed for a quality / long session
READY_EASY_ONLY = 45    # below this readiness score the default is a regeneration run
READY_EXTRA_EASY = 80   # the optional easy run after the week's target needs a well-recovered day
DRIFT_CUT = {"volume": 0.8, "intensity": 0.5, "descent": 0.5}   # mechanics above threshold → less today
LONG_SHARE = 0.30       # a long run ≤ 30 % of the weekly volume budget
Z4_SESSION_MAX = 45     # a quality session's hard minutes are capped here whatever the capacity says
MIN_RUN_KM = 2.0        # below this there's no meaningful run left today → volno
# heart-rate-reserve bands per session type (Karvonen)
HRR = {"regenerace": (0.50, 0.65), "lehký": (0.60, 0.72), "dlouhý": (0.60, 0.75), "kvalitní": (0.80, 0.92)}
PACE_FALLBACK = {"regenerace": (1.06, 1.15), "lehký": (0.97, 1.05), "dlouhý": (1.00, 1.08)}
CHS = ("volume", "intensity", "descent", "ascent")
# 4-week loading cycle (3 build weeks on a reference week + 1 recovery week), as
# asked by the product owner: 90 % / 100 % / 110 % of the last loaded week before
# the previous recovery week, then 50–60 % of week 3. The 3:1 pattern is standard
# endurance periodization practice (Issurin 2010; Mujika et al. 2018) — planned
# overload must alternate with recovery (Meeusen et al. 2013 ECSS/ACSM consensus);
# the exact percentages are convention, not trial-tested, so the capacity ceiling
# (Zátěž) and daily readiness stay in charge (Kiely 2012: adapt to the response).
CYCLE = {1: 0.90, 2: 1.00, 3: 1.10, 4: 0.55 * 1.10}
CYCLE_PCT_OF = {1: 90, 2: 100, 3: 110, 4: 55}
RECOVERY_BELOW = 0.70      # a completed week under 70 % of the 4 before it = a recovery week
CYCLE_MIN_WEEKS = 4        # completed weeks with data needed to place the runner in the cycle
Z4_TRIMP_PER_MIN = 0.85 * 0.64 * 2.718281828 ** (1.92 * 0.85)   # Banister TRIMP of a minute at 85 % HRR


def _d(s):
    return date.fromisoformat(s[:10])


def _r(v, dec=1):
    return None if v is None else (round(v, dec) if dec else round(v))


def _cz(v, dec=1):
    """A number for a Czech sentence (decimal comma)."""
    return "—" if v is None else f"{round(v, dec):.{dec}f}".replace(".", ",") if dec else str(round(v))


def _pattern(hist, today):
    """Usual run days, long-run weekday, hard days, runs/week — last 8 weeks."""
    weeks = 8
    days = {}
    for s in hist:
        days.setdefault(s["date"], []).append(s)
    wd_days = [0] * 7
    hard_wd = [0] * 7
    per_week = {}
    for day, ss in days.items():
        dd = _d(day)
        wd_days[dd.weekday()] += 1
        if any((s["exp"].get("intensity") or 0) >= HARD_Z4_MIN for s in ss):
            hard_wd[dd.weekday()] += 1
        wk = (today - dd).days // 7
        per_week.setdefault(wk, []).append((dd, sum(s["km"] or 0 for s in ss)))
    counts = [len(per_week.get(k, [])) for k in range(weeks)]
    rpw = E.median(counts) if counts else 0
    run_days = [wd for wd in range(7) if wd_days[wd] / weeks >= 0.4]
    if len(run_days) < round(rpw):
        run_days = sorted(sorted(range(7), key=lambda w: -wd_days[w])[:int(round(rpw))])
    long_votes = []
    for runs_wk in per_week.values():
        if len(runs_wk) >= 2:
            runs_wk = sorted(runs_wk, key=lambda t: -t[1])
            others = [km for _, km in runs_wk[1:]]
            if runs_wk[0][1] >= 1.25 * E.median(others):
                long_votes.append(runs_wk[0][0].weekday())
    long_day = None
    if len(long_votes) >= 3:
        top = max(set(long_votes), key=long_votes.count)
        if long_votes.count(top) >= 0.5 * len(long_votes):
            long_day = top
    hard_days = [wd for wd in range(7) if hard_wd[wd] / weeks >= 0.3]
    long_kms = [max(km for _, km in r) for r in per_week.values() if r]
    return {"runsPerWeek": rpw, "runDays": run_days, "longDay": long_day, "hardDays": hard_days,
            "hardPerWeek": round(sum(hard_wd) / weeks, 2), "longKm": E.median(long_kms) if long_kms else None}


def _easy_km(hist, long_day_km):
    easy = [s["km"] for s in hist if s["km"] and (s["exp"].get("intensity") or 0) < HARD_Z4_MIN
            and (long_day_km is None or s["km"] < 0.9 * long_day_km)]
    pool = easy or [s["km"] for s in hist if s["km"]]
    return E.median(pool) if pool else None


def _easy_pace(hist):
    paces = [1000 / s["speed"] for s in hist if s["speed"] and (s["exp"].get("intensity") or 0) < HARD_Z4_MIN]
    return E.median(paces) if paces else None


def _hr_band(kind, hrmax, rhr):
    lo, hi = HRR[kind]
    return (round(rhr + lo * (hrmax - rhr)), round(rhr + hi * (hrmax - rhr)))


def _pace_band(kind, hr, fit, easy_pace, speed_range=None):
    """(fast, slow) s/km for the HR band — from the runner's own HR↔speed line
    when it exists AND stays inside the speeds they actually run (±15 %); a flat
    or noisy line extrapolates to absurd paces, so then the usual easy pace is
    used instead."""
    if fit and hr and speed_range:
        a0, b = fit
        v_hi, v_lo = (hr[1] - a0) / b, (hr[0] - a0) / b
        lo_ok, hi_ok = speed_range[0] * 0.85, speed_range[1] * 1.15
        if lo_ok <= v_lo <= hi_ok and lo_ok <= v_hi <= hi_ok and v_lo > 0:
            return (round(1000 / v_hi), round(1000 / v_lo))
    if easy_pace and kind in PACE_FALLBACK:
        f0, f1 = PACE_FALLBACK[kind]
        return (round(easy_pace * f0), round(easy_pace * f1))
    return None


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def cycle_position(weeks: list[float]) -> dict | None:
    """Where this calendar week sits in the 4-week cycle. `weeks` = the runner's
    completed weekly volume, newest first (weeks[0] = last week).

    • The latest recovery week (< 70 % of the 4 weeks before it) within the last
      4 weeks anchors the cycle: recovery last week → this is week 1, two weeks
      ago → week 2 … four weeks ago → week 4. The reference is the loaded week
      just before that recovery week.
    • Without one, last week's strain against the runner's baseline (mean of the
      4 weeks before it) places the cycle: ≥ 105 % → recover now (week 4),
      ≥ 95 % → week 3, ≥ 85 % → week 2, else start at week 1 on the baseline.
    None with less than CYCLE_MIN_WEEKS of history."""
    if len([w for w in weeks if w > 0]) < CYCLE_MIN_WEEKS:
        return None

    def base(i):
        prev = weeks[i + 1:i + 5]
        return sum(prev) / len(prev) if len(prev) >= 3 and sum(prev) > 0 else None
    for j in range(4):
        b = base(j)
        if b and weeks[j] <= RECOVERY_BELOW * b:
            ref_i = j + 1
            real = ref_i < len(weeks) and weeks[ref_i] > 0
            return {"pos": j + 1, "how": "recovery", "recoveryBack": j + 1,
                    "refBack": ref_i + 1 if real else None, "refScale": None,
                    "ref": weeks[ref_i] if real else b}
    b = base(0)
    if not b:
        return None
    strain = weeks[0] / b
    if strain >= 1.05:
        pos, prev = 4, 3
    elif strain >= 0.95:
        pos, prev = 3, 2
    elif strain >= 0.85:
        pos, prev = 2, 1
    else:
        return {"pos": 1, "how": "strain", "strain": round(strain, 2), "refBack": None, "refScale": None, "ref": b}
    # last week counts as the previous cycle week → reference = last week / its factor
    return {"pos": pos, "how": "strain", "strain": round(strain, 2), "refBack": 1, "refScale": 1 / CYCLE[prev],
            "ref": weeks[0] / CYCLE[prev]}


def _latest_pain(db, rid, today):
    """Worst running pain reported today or yesterday (check-in or run rating)."""
    cut = (today - timedelta(days=1)).isoformat()
    best, site = 0, None
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at >= cut).all():
        if (c.pain_score or 0) > best:
            best = c.pain_score
            regs = [p.get("region") for p in (c.pain_points or []) if p.get("region")]
            site = ", ".join(regs) if regs else (c.pain_site or None)
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid,
                                                      models.ActivityFeedback.submitted_at >= cut).all():
        if (f.pain_during or 0) > best:
            best, site = f.pain_during, f.pain_site
    return best, site


def build_guidance(db, rid, a, runner=None) -> dict | None:
    cap = a.get("capacity")
    if not cap:
        return None
    today = E.today_date()
    t_iso = today.isoformat()
    hrmax, rhr = cap.get("hrMax") or 185, cap.get("hrRest") or 50
    sessions = C.run_exposures(db, rid, hrmax, rhr)
    runs = [s for s in sessions if s["run"] and s["date"] <= t_iso]
    hist = [s for s in runs if 0 < (today - _d(s["date"])).days <= 56]
    today_runs = [s for s in runs if s["date"] == t_iso]
    pat = _pattern(hist, today)
    easy_km = _easy_km(hist, pat["longKm"])
    easy_pace = _easy_pace(hist)
    fit = C.hr_speed_fit(runs, t_iso, lo=1, hi=56)
    speeds = sorted(s["speed"] for s in hist if s["speed"])
    speed_range = (speeds[int(0.05 * (len(speeds) - 1))], speeds[int(0.95 * (len(speeds) - 1))]) if len(speeds) >= 5 else None
    ready = cap["readiness"]["today"]                      # capacity factor 0.7–1.0 (scales sizes)
    rscore = cap["readiness"].get("score", round(ready * 100))   # readiness shown to the runner, 20–100 %
    ch = cap["channels"]

    # ---- context ---------------------------------------------------------
    dm_today = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                   models.DailyMetric.date == t_iso).first()
    provisional = not (dm_today and (dm_today.sleep_h is not None or dm_today.hrv_ms is not None))
    pain, pain_site = _latest_pain(db, rid, today)
    decision = E.triage_decision(a)
    referral = decision in ("physio_48h", "physio_7d")
    inj = (a.get("injury") or {}).get("active")
    drift = a.get("quadrant") in ("silent", "critical") or bool(a.get("mechFlag"))
    load = a.get("load") or 0
    days_to_race = None
    if runner and runner.goal_date:
        try:
            days_to_race = (_d(runner.goal_date) - today).days
        except ValueError:
            days_to_race = None
    hard_dates = [s["date"] for s in runs if (s["exp"].get("intensity") or 0) >= HARD_Z4_MIN and s["date"] < t_iso]
    days_since_hard = (today - _d(max(hard_dates))).days if hard_dates else None

    # ---- this week's target: the 4-week cycle, never above capacity -------------
    ws = week_start(today)

    def sums(pool, c):
        out = {}
        for s in pool:
            v = s["exp"].get(c)
            if v:
                out[s["date"]] = out.get(s["date"], 0.0) + v
        return out
    daily = {c: sums(runs, c) for c in CHS}
    daily["systemic"] = sums([s for s in sessions if s["date"] <= t_iso], "systemic")   # all sports
    vol_daily = daily["volume"]

    def week_sum(c, start):
        return sum(daily[c].get((start + timedelta(days=k)).isoformat(), 0.0) for k in range(7))
    past = {c: [week_sum(c, ws - timedelta(days=7 * k)) for k in range(1, 17)] for c in daily}
    cyc = cycle_position(past["volume"])
    ov = (runner.cycle_override or {}) if runner is not None else {}
    manual = ov.get("pos") if ov.get("week") == ws.isoformat() and ov.get("pos") in CYCLE else None
    if days_to_race is not None and 0 < days_to_race <= 14:
        mode, factor = "taper", (0.50 if days_to_race <= 7 else 0.70)
    elif load >= 25 and (manual or (cyc or {}).get("pos")) != 4 and (cyc is not None or manual):
        mode, factor = "deload", CYCLE[4]          # elevated load: recovery comes first, whatever was picked
    elif manual is not None:
        mode, factor = ("recovery" if manual == 4 else "build"), CYCLE[manual]
    elif cyc is None:
        mode, factor = "learning", 1.0
    else:
        mode, factor = ("recovery" if cyc["pos"] == 4 else "build"), CYCLE[cyc["pos"]]
    pos_now = manual if (manual is not None and mode in ("build", "recovery")) else (cyc or {}).get("pos")

    def reference(c):
        """The channel's reference week for the cycle (None → use the capacity)."""
        if cyc is None:
            return None
        w = past[c]
        if mode == "deload":                  # forced: 55 % of last week, whatever the cycle said
            return (w[0] / CYCLE[3]) if w[0] else None
        if cyc["refBack"]:
            return w[cyc["refBack"] - 1] * (cyc["refScale"] or 1.0)
        lo = cyc.get("recoveryBack") if cyc["how"] == "recovery" else 1
        vals = w[lo:lo + 4]
        return sum(vals) / len(vals) if vals else None

    week = {}
    for c in (*CHS, "systemic"):
        info = ch.get(c) or {}
        wcap = info.get("week") or {}
        ceil7 = wcap.get("ceiling")           # Zátěž's weekly threshold (capacity × readiness × (1 + margin))
        ref = reference(c)
        if ref is None:
            ref = wcap.get("cap")
        target = None if ref is None else ref * factor
        if target is not None and ceil7 is not None:
            target = min(target, ceil7)       # the plan never schedules a load exceedance
        done_week = sum(daily[c].get((ws + timedelta(days=k)).isoformat(), 0.0) for k in range((today - ws).days + 1))
        done6 = sum(daily[c].get((today - timedelta(days=k)).isoformat(), 0.0) for k in range(1, 7))
        done_today = daily[c].get(t_iso, 0.0)
        left_week = None if target is None else max(0.0, target - done_week)
        left7 = None if ceil7 is None else max(0.0, ceil7 - done6 - done_today)
        ceil_run = info.get("ceilingToday") if c != "systemic" else None
        limits = {k: v for k, v in (("week", left_week), ("7d", left7), ("run", ceil_run)) if v is not None}
        lim = min(limits, key=limits.get) if limits else None
        week[c] = {"label": info.get("label", C.CHANNELS[c]["label"]), "unit": info.get("unit", C.CHANNELS[c]["unit"]),
                   "capacity": wcap.get("cap"), "ceiling7": ceil7, "done7": done6 + done_today, "left7": left7,
                   "budget": target, "done": done_week, "doneToday": done_today, "left": left_week,
                   "ceilingRun": ceil_run, "todayMax": limits[lim] if lim else None, "limitedBy": lim}
    # Celková zátěž (HR × time, all sports) is volume × intensity in one number —
    # what's left of it also bounds today's kilometres and hard minutes
    sys_left = week["systemic"]["todayMax"]
    easy_rate = [s["exp"]["systemic"] / s["km"] for s in hist
                 if s["km"] and s["exp"].get("systemic") and (s["exp"].get("intensity") or 0) < 5]
    per_km = E.median(easy_rate) if len(easy_rate) >= 3 else None
    km_by_sys = sys_left / per_km if (sys_left is not None and per_km) else None
    for c, cap_c in (("volume", km_by_sys), ("intensity", None if sys_left is None else sys_left / Z4_TRIMP_PER_MIN)):
        if cap_c is not None and (week[c]["todayMax"] is None or cap_c < week[c]["todayMax"]):
            week[c]["todayMax"], week[c]["limitedBy"] = cap_c, "systemic"
    if drift:                                  # mechanics over its threshold: keep today well inside capacity
        for c, f in DRIFT_CUT.items():
            if week[c]["todayMax"] is not None:
                week[c]["todayMax"] *= f
                week[c]["limitedBy"] = "mechanics"
    for c, wc in week.items():
        dec = C.CHANNELS[c]["dec"]
        for k in ("capacity", "ceiling7", "done7", "left7", "budget", "done", "doneToday", "left", "todayMax"):
            wc[k] = _r(wc[k], dec)
    nxt = None
    if pos_now and mode in ("build", "recovery"):
        p2 = pos_now % 4 + 1
        ref_v = reference("volume") if cyc else week["volume"]["capacity"]
        if ref_v is not None:
            # after a recovery week a new cycle starts on its 3rd (peak) week
            f2 = CYCLE[1] * CYCLE[3] if pos_now == 4 else CYCLE[p2]
            km2 = ref_v * f2
            if week["volume"]["ceiling7"] is not None:
                km2 = min(km2, week["volume"]["ceiling7"])
            nxt = {"pos": p2, "pct": CYCLE_PCT_OF[p2], "km": _r(km2)}
    cycle = {
        "next": nxt,
        "pos": pos_now, "autoPos": cyc["pos"] if cyc else None, "manual": manual is not None and mode in ("build", "recovery"),
        "how": cyc["how"] if cyc else None, "factor": round(factor, 3),
        "refKm": _r(reference("volume")) if cyc else _r(week["volume"]["capacity"]),
        "refWeek": (ws - timedelta(days=7 * cyc["refBack"])).isoformat() if cyc and cyc["refBack"] else None,
        "weeks": [{"start": (ws - timedelta(days=7 * k)).isoformat(), "km": _r(past["volume"][k - 1])} for k in (4, 3, 2, 1)]
        + [{"start": ws.isoformat(), "km": week["volume"]["done"], "target": week["volume"]["budget"], "current": True}],
    }

    # ---- limits per session type --------------------------------------------
    vol_max = week["volume"]["todayMax"]
    int_max = week["intensity"]["todayMax"]
    desc_max = week["descent"]["todayMax"]
    asc_max = week["ascent"]["todayMax"]
    base_km = easy_km or 6.0
    recurring = a.get("painRecurring")
    pain_mod = 3 <= pain <= 5 or (bool(recurring) and pain <= 5)
    pain_why = (f"Bolest {pain}/10" if pain >= 3 else
                f"Opakovaná bolest ({recurring['site']}, {recurring['days']}× za 28 dní)" if recurring else "")
    km_scale = (0.7 if pain_mod else 1.0) * max(ready, 0.75)
    # weekly target reached but the 7-day ceiling still has room: a short easy run
    # stays available (not the default) — a rested body may move, the plan isn't risk
    vw = week["volume"]
    sys7 = week["systemic"]["left7"]           # safety only — the week's plan targets don't bound this extra run
    km_by_sys7 = sys7 / per_km if (sys7 is not None and per_km) else None
    easy_room = [x for x in (vw["left7"], vw["ceilingRun"], km_by_sys7) if x is not None]
    easy_room = min(easy_room) if easy_room else None
    extra_easy = (vw["limitedBy"] == "week" and (vol_max or 0) < MIN_RUN_KM and easy_room is not None
                  and easy_room >= MIN_RUN_KM and rscore >= READY_EXTRA_EASY and not pain_mod and pain < 3)

    def cap_km(x):
        return x if vol_max is None else min(x, vol_max)

    def mk(kind, lo, hi, z4max=None, z4t=None, dfac=1.0, terrain=None, notes=None, vmax=None):
        hr = _hr_band(kind, hrmax, rhr) if kind in HRR else None
        pace = _pace_band(kind, hr, fit, easy_pace, speed_range) if kind != "kvalitní" else None
        lo, hi = (cap_km(lo), cap_km(hi)) if vmax is None else (min(lo, vmax), min(hi, vmax))
        lo = min(lo, hi)
        mid_pace = ((pace[0] + pace[1]) / 2) if pace else easy_pace
        dur = (round(lo * mid_pace / 60), round(hi * mid_pace / 60)) if mid_pace else None
        d_max = None if desc_max is None else desc_max * dfac * (0.5 if (pain_mod or drift) else 1.0)
        return {"label": TYPE_LABEL[kind], "km": {"lo": _r(lo), "hi": _r(hi), "max": _r(vol_max if vmax is None else vmax)},
                "durationMin": dur, "hr": hr, "hrZones": {"regenerace": "Z1–Z2", "lehký": "Z2", "dlouhý": "Z2",
                                                          "kvalitní": "Z4–Z5 v úsecích, jinak Z1–Z2"}[kind],
                "pace": pace, "z4Max": _r(z4max, 0), "z4Target": z4t, "descentMax": _r(d_max, 0),
                "ascentMax": _r(None if asc_max is None else asc_max * dfac, 0),
                "terrain": terrain or ("rovina nebo měkký povrch" if (pain_mod or drift) else "libovolný, do stropu klesání"),
                "notes": notes or [], "allowed": True, "why": None}

    types = {"volno": {"label": TYPE_LABEL["volno"], "km": {"lo": 0, "hi": 0, "max": _r(vol_max)}, "allowed": True,
                       "why": None, "notes": ["Odpočinek nebo lehká chůze, protažení, mobilita."],
                       "terrain": None, "hr": None, "pace": None, "durationMin": None, "z4Max": 0, "z4Target": None,
                       "descentMax": 0, "ascentMax": 0}}
    extra_cap = min(easy_room, 0.6 * base_km) if extra_easy else None
    types["regenerace"] = mk("regenerace", 0.5 * base_km * km_scale, 0.75 * base_km * km_scale, z4max=0, dfac=0.5,
                             terrain="rovina nebo měkký povrch", vmax=extra_cap,
                             notes=["Velmi volně, konverzační tempo — cílem je prokrvit, ne trénovat."]
                             + (["Nad rámec týdenního cíle — jen pokud máte chuť; pod 7denním stropem nic nezhorší."]
                                if extra_easy else []))
    types["lehký"] = mk("lehký", 0.85 * base_km * km_scale, 1.1 * base_km * km_scale,
                        z4max=min(5, int_max) if int_max is not None else 5, dfac=0.8)
    long_target = max(base_km * 1.2, LONG_SHARE * (week["volume"]["budget"] or 0))
    long_target = cap_km(long_target * (1.0 if not pain_mod else 0.7))
    types["dlouhý"] = mk("dlouhý", 0.85 * long_target, long_target,
                         z4max=min(10, int_max) if int_max is not None else 10,
                         notes=[f"Nejvýš {round(LONG_SHARE * 100)} % týdenního rozpočtu objemu; stejnoměrně, v Z2."])
    z4hi = None if int_max is None else min(int_max, Z4_SESSION_MAX) * (0.5 if drift else 1.0)
    z4t = None if z4hi is None else {"lo": _r(0.6 * z4hi, 0), "hi": _r(z4hi, 0)}
    types["kvalitní"] = mk("kvalitní", 0.9 * base_km * km_scale, 1.1 * base_km * km_scale, z4max=z4hi, z4t=z4t,
                           dfac=0.6, terrain="rovina / dráha — tvrdé úseky ne z kopce",
                           notes=["Rozklus a výklus v Z1–Z2; tvrdé úseky v Z4–Z5 do stropu minut."])
    if days_to_race == 0:
        types["závod"] = {"label": TYPE_LABEL["závod"], "km": None, "allowed": True, "why": None,
                          "notes": ["Hodně štěstí! Dnes bez limitů — po závodě nechte tělo regenerovat."],
                          "terrain": None, "hr": None, "pace": None, "durationMin": None, "z4Max": None,
                          "z4Target": None, "descentMax": None, "ascentMax": None}

    # ---- why a type isn't advisable today --------------------------------
    def block(kind, why):
        if types[kind]["allowed"]:
            types[kind]["allowed"], types[kind]["why"] = False, why
    override = None
    if inj:
        override = {"kind": "injury", "title": "Aktivní zranění — dnes bez běhu",
                    "text": f"{inj.get('site') or 'Nahlášené zranění'} (OSTRC {inj.get('severity')}/100). "
                            "Běh odložte, dokud se zranění nezlepší; řiďte se doporučením fyzioterapeuta."}
    elif pain > 5 and referral:
        override = {"kind": "physio", "title": "Dnes neběhat — objednejte se k fyzioterapeutovi",
                    "text": f"Bolest {pain}/10{f' · {pain_site}' if pain_site else ''} a zároveň engine doporučuje "
                            f"fyzioterapeuta ({'do 48 hodin' if decision == 'physio_48h' else 'do 7 dnů'}). "
                            "Kombinace bolesti a rizikového stavu je důvod běh vynechat a nechat to posoudit."}
    if override:
        for k in ("regenerace", "lehký", "dlouhý", "kvalitní"):
            block(k, override["title"])
    if pain > 5 and not override:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, f"Bolest {pain}/10 — dnes jen velmi volně nebo jiný sport bez bolesti.")
    if pain_mod:
        block("dlouhý", f"{pain_why} — dnes bez dlouhého běhu.")
        block("kvalitní", f"{pain_why} — dnes bez intenzity.")
    if rscore < READY_QUALITY:
        block("kvalitní", f"Připravenost {rscore} % — na tvrdý trénink je potřeba aspoň {READY_QUALITY} %.")
        block("dlouhý", f"Připravenost {rscore} % — dlouhý běh přesuňte na odpočatější den.")
    if load >= 25:
        block("kvalitní", "Zátěž je zvýšená — týden odlehčujeme, bez tvrdých úseků.")
        block("dlouhý", "Zátěž je zvýšená — bez dlouhého běhu, dokud neklesne.")
    if days_since_hard is not None and days_since_hard < HARD_GAP_DAYS:
        block("kvalitní", "Poslední tvrdý trénink byl před méně než 48 h.")
    if int_max is None:
        block("kvalitní", "Kapacitu intenzity zatím neznáme — chybí běhy s tepem.")
    elif (z4hi or 0) < 10:
        block("kvalitní", "Na tento týden už nezbývá rozpočet intenzity (min v Z4+).")
    if drift:
        types["kvalitní"]["notes"].append("Mechanika se odchyluje — strop minut v Z4+ je poloviční.")
    if vol_max is not None and vol_max < 1.2 * base_km:
        block("dlouhý", f"Strop na jeden běh je dnes {_cz(vol_max)} km — na dlouhý běh nezbývá.")
    if days_to_race is not None and 0 < days_to_race <= 7:
        block("dlouhý", "Týden před závodem — bez dlouhého běhu.")
    no_room = {"week": "Týdenní cíl objemu je splněný.", "7d": "Posledních 7 dní jste na stropu týdenní kapacity.",
               "systemic": "Celková zátěž (tep × čas) je na stropu.", "run": "Na dnešek už nezbývá objem."}
    if vw["left"] is not None and vw["left"] < 0.5 * base_km:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, "Týdenní cíl objemu je splněný.")
    if vol_max is not None and vol_max < 0.5 * base_km:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, no_room.get(vw["limitedBy"], "Na dnešek už nezbývá objem."))
    if vol_max is not None and vol_max < MIN_RUN_KM and not extra_easy:
        block("regenerace", no_room.get(vw["limitedBy"], "Na dnešek už nezbývá objem.")
              + " Volno, případně jiný sport bez nárazů (kolo, plavání).")

    # ---- default type -------------------------------------------------------
    wd = today.weekday()
    ran_recent = sum(1 for k in (1, 2) if vol_daily.get((today - timedelta(days=k)).isoformat()))
    runs_last6 = sum(1 for k in range(1, 7) if vol_daily.get((today - timedelta(days=k)).isoformat()))
    if days_to_race == 0:
        typ = "závod"
    elif override:
        typ = "volno"
    elif pain > 5:
        typ = "regenerace"
    elif rscore < READY_EASY_ONLY:
        typ = "regenerace" if types["regenerace"]["allowed"] else "volno"
    elif pat["runDays"] and wd not in pat["runDays"] and runs_last6 >= pat["runsPerWeek"] - 1:
        typ = "volno"
    elif not pat["runDays"] and ran_recent >= 2:
        typ = "volno"
    elif pat["longDay"] == wd and types["dlouhý"]["allowed"]:
        typ = "dlouhý"
    elif (wd in pat["hardDays"] or (pat["hardPerWeek"] >= 0.5 and (days_since_hard or 99) >= 4)) \
            and types["kvalitní"]["allowed"] and not drift:
        typ = "kvalitní"
    elif types["lehký"]["allowed"]:
        typ = "lehký"
    else:
        typ = "regenerace" if types["regenerace"]["allowed"] else "volno"
    if len(hist) < 3 and typ not in ("volno", "závod") and not override:
        typ = "lehký"
    if extra_easy and typ == "regenerace":
        typ = "volno"                     # the optional easy run is offered, not recommended

    # ---- reasons (most important first) -------------------------------------
    reasons = []  # the override itself is shown as the banner, not repeated here
    if override:
        pass
    elif pain > 5:
        reasons.append(f"Bolest {pain}/10{f' · {pain_site}' if pain_site else ''} — dnes jen velmi volně nebo jiný sport, "
                       "který nebolí. Pokud potrvá, proberte ji s fyzioterapeutem.")
    elif pain_mod:
        reasons.append(f"{pain_why}{f' · {pain_site}' if (pain >= 3 and pain_site) else ''} — odlehčit: běh jen kratší "
                       "a volnější, po rovině nebo měkkém povrchu, bez dlouhého běhu a intenzity.")
    if typ == "volno" and not override and vol_max is not None and vol_max < MIN_RUN_KM:
        lim = vw["limitedBy"]
        if lim == "week":
            reasons.append(f"Týdenní cíl je splněný ({_cz(vw['done'])} z {_cz(vw['budget'])} km) — dnes volno.")
        elif lim == "7d":
            reasons.append(f"Posledních 7 dní {_cz(vw['done7'])} km — na stropu vaší týdenní kapacity "
                           f"({_cz(vw['ceiling7'])} km), dnes volno.")
        elif lim == "systemic":
            reasons.append("Celková zátěž (tep × čas ze všech aktivit) je na stropu týdenní kapacity — dnes volno.")
        else:
            reasons.append("Na dnešek už nezbývá objem — dnes volno, případně jiný sport bez nárazů.")
    parts = cap["readiness"].get("parts") or {}
    part_lbl = {"hrv": "nižší HRV", "rhr": "vyšší klidový tep", "sleep": "kratší spánek",
                "soreness": "svalová bolest", "fatigue": "únava"}
    low = [part_lbl[k] for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v > 0.1 and k in part_lbl]
    if rscore < 90 and low:
        reasons.append(f"Připravenost {rscore} % ({', '.join(low[:3])} proti vaší normě) — dnešní stropy jsou úměrně nižší"
                       + (", bez tvrdého tréninku a dlouhého běhu." if rscore < READY_QUALITY else "."))
    elif typ == "volno" and not override and rscore >= READY_EXTRA_EASY:
        reasons.append(f"Připravenost {rscore} % — tělo je zregenerované, volno je kvůli týdennímu plánu, "
                       "ne kvůli únavě." + (f" Pokud máte chuť, krátký regenerační běh do {_cz(extra_cap)} km nic nezhorší."
                                            if extra_easy else ""))
    if provisional:
        reasons.append("Ještě nemáme dnešní spánek a HRV — doporučení je předběžné a po synchronizaci se upřesní.")
    if mode == "deload":
        reasons.append("Zátěž je zvýšená — odlehčovací týden (55 % minulého týdne), dokud neklesne.")
    elif mode == "taper":
        reasons.append(f"{(runner.goal_race if runner and runner.goal_race else 'Závod')} za {days_to_race} dní — "
                       f"ladění formy, objem ×{_cz(factor, 2)} referenčního týdne.")
    elif mode == "recovery":
        reasons.append("4. týden cyklu — odlehčovací týden (55 % vrcholového týdne), ať se trénink vstřebá.")
    elif mode == "build":
        reasons.append(f"{cycle['pos']}. týden cyklu — cíl {round(factor * 100)} % referenčního týdne "
                       f"({_cz(cycle['refKm'])} km).")
    if cycle["manual"]:
        reasons.append(f"Tento týden jste ručně zvolili {cycle['pos']}. týden cyklu — příští týden se cyklus nastaví "
                       "sám podle toho, jak týden skutečně proběhne.")
    else:
        reasons.append("Čtyřtýdenní cyklus nastavíme po 4 týdnech dat — zatím je cílem vaše týdenní kapacita.")
    if drift:
        reasons.append("Mechanika se odchyluje od vaší normy — bez intenzity a prudkých seběhů, raději rovina.")
    if vw["budget"] and not (typ == "volno" and vw["limitedBy"] == "week"):
        reasons.append(f"Tento týden (od pondělí) {_cz(vw['done'])} z cíle {_cz(vw['budget'])} km.")
    if typ == "kvalitní" and days_since_hard is not None:
        reasons.append(f"Poslední tvrdý trénink před {days_since_hard} dny — prostor na kvalitu.")
    if typ == "dlouhý":
        reasons.append(f"Dlouhý běh obvykle běháte {WD_IN[pat['longDay']]}.")
    if typ == "volno" and not override and pat["runDays"] and wd not in pat["runDays"]:
        reasons.append("Dnes obvykle neběháte — den volna pro regeneraci.")

    done = None
    if today_runs:
        done = {c: week[c]["doneToday"] for c in CHS}
        done["runs"] = len(today_runs)

    return {
        "date": t_iso, "engine": "v3", "type": typ, "typeLabel": TYPE_LABEL[typ],
        "provisional": provisional, "override": override, "referral": decision if referral else None,
        "pain": pain or 0, "readiness": ready, "readinessScore": rscore, "types": types,
        "axes": {"load": load, "mech": a.get("mech") or 0, "threshold": E.QUAD_THRESHOLD},
        "week": {"channels": week, "mode": mode, "progression": round(factor, 3), "cycle": cycle},
        "pattern": {**pat, "runDayNames": [WD[w] for w in pat["runDays"]],
                    "longDayName": WD[pat["longDay"]] if pat["longDay"] is not None else None,
                    "hardDayNames": [WD[w] for w in pat["hardDays"]], "easyKm": _r(easy_km), "easyPace": _r(easy_pace, 0)},
        "reasons": reasons[:5], "done": done,
        "zones": cap.get("zones"), "hrSource": "fit" if fit else "fallback",
    }
