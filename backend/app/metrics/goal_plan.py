"""Trénink k cíli, stage 1 — feasibility (owner request 2026-10-12, decisions of the same
day; the proposal is the page "Trénink k cíli", version 3).

The runner picks a goal: a race (distance, climb, date, "finish" or a target time) or a
free goal (weekly km, longest run, climb by a date). This module turns it into
requirements in the channels the engine measures, projects week by week how the
runner's capacity can grow under the app's own rules, and says whether the goal can be
reached healthily by the date: Reálné / Těsné / Nereálné, the real date, the bottleneck,
and the alternatives (later date, finish instead of a time, a shorter race, the risk
path). Stage 1 is advice only — the daily recommendation and the week's plan don't change.

Requirements (sources = ids in knowledge/summaries.json; observational studies, so the
numbers show an association, not a sure effect):
  10 km      peak week 25–35 km, longest run 12–14 km   (Abrahamson 2024: < 25 km/week → more
             injuries; the rest is a working assumption)
  half       37–45 km, 18–21 km   (Fokkema 2020: > 32 km/week and a long run > 21 km → faster;
             Mohseni 2019: > 23 miles ≈ 37 km/week → fewer race injuries)
  marathon   55–65 km, 29–32 km and the count of long runs: finish 1 × ≥ 29 km (Toresdahl 2021:
             no runner with a ≥ 29 km run had a race-ending injury), a target time 2 × ≥ 32 km
             (Doherty 2019: the count of runs ≥ 32 km predicted the time best, R² 0.81);
             Fokkema 2020: < 40 km/week and a longest run < 25 km → slower, > 65 km → faster;
             Rasmussen 2013: < 30 km/week → twice the injury risk (never accepted);
             Mohseni 2019: > 40 miles ≈ 64 km/week → fewer race injuries
  trail      peak week ≈ 1.5 × D but at least the road requirement of the flat-equivalent
             distance (Scarf 2007: 7.92 m of flat per metre of climb), longest run ≈ 0.7 × D
             (at most 50 km), climb and descent per run ≈ 0.6 × H and per week ≈ H for a target
             time, ≈ 0.6 × H to finish (owner decision 2026-10-12: walking the climbs), and ≥ 10
             descent sessions at least 7 days apart (Marqueste 2008: weekly bouts protected,
             4-day ones didn't; Bontemps 2025: quadriceps soreness fell only after 10 sessions).
             The multipliers are working assumptions. Ultras (where 1.5 × D or 0.7 × D would go
             past it): the week at most 70 km to finish / 90 km for a time, the long run 35 / 45 km,
             one run's climb the race's climb per km over the long run (see ULTRA_WEEK).
The lower number is the "finish" goal, the upper one a target time; distances in between
are interpolated. The long run may be up to 50 % of the week (owner decision; no study looks
at the share as such — the per-run ceiling over the longest run of 30 days stays the safety
rule, Frandsen et al. 2025), so a 29 km long run needs a 58 km week.

Projection (one row per calendar week from next Monday):
  safe — the week's volume up to the weekly ceiling (capacity × (1 + the runner's weekly
         margin, 15 % narrowed for the first year, injuries, new shoes)), the capacity
         recomputed every projected week by capacity.weekly_capacity's rule (max of the
         4-week average and 0.9 × the best of the 6 weeks before, decayed after a break),
         the week's rise counted from the last 2 weeks but never from below that capacity;
         the long run ≤ the per-run capacity (the engine's: the longest run of 30 days, older
         ones up to 90 days at a 30-day half-life) + the per-run margin (10 %) and ≤ 50 % of the
         week; every 4th week a recovery week (55 % of the week before, the app's cycle);
  risk — margin 25 %, weekly rise ≤ 20 % (Damsted 2019: 20–60 % → +22.6 percentage points of
         injuries at 21 days), the long run +15 % (Frandsen 2025: HRR 1.64 at +10–30 %),
         a lighter recovery week (75 %; working assumption);
  both — never a week over 1.5 × the average week of the previous 4 (Toresdahl 2022: every
         day with ACWR ≥ 1.5 raised the odds of injury by 6 %).
Taper: 1 week up to 12 km, else 2 (owner decision, Bosquet 2007, Wang 2023). Reserve for
illness and bad weeks: 2 weeks, 3 for plans over 16 weeks (Toresdahl 2022: 40 % injured and
27 % ill within 16 weeks of marathon training). Verdict: ready + taper + reserve fits →
Reálné; ready + taper fits → Těsné; else Nereálné with the real date.
"""
import math
from datetime import date, timedelta

from . import capacity as C
from . import data as D
from . import engine as E
from . import terrain
from .race_plan import SCARF_M

# distance km → (peak week finish, time), (long run finish, time)
ROAD = ((5.0, (15.0, 25.0), (8.0, 10.0)),
        (10.0, (25.0, 35.0), (12.0, 14.0)),
        (21.1, (37.0, 45.0), (18.0, 21.0)),
        (42.2, (55.0, 65.0), (29.0, 32.0)))
LONG_COUNT = {"finish": (29.0, 1), "time": (32.0, 2)}   # marathon: runs ≥ km, how many
COUNT_FROM_KM = 35.0            # road races from this distance count the long runs
MARATHON_FLOOR = 30.0           # never a marathon plan peaking under this (Rasmussen 2013)
TRAIL_M_PER_KM = 15.0           # climb per km from which a race is a trail
TRAIL_WEEK, TRAIL_LONG, TRAIL_RUN_CLIMB = 1.5, 0.7, 0.6
WEEK_CLIMB = {"finish": 0.6, "time": 1.0}   # the week's climb and descent, × the course's (working assumption)
# ultra (owner report 2026-10-12: 101 km / 5 500 m asked for 152 km a week and a 50 km long run): the
# linear multipliers stop at what ultra runners actually train — the ULTRA cohort's median 3 347 km a
# year ≈ 64 km a week (Hoffman & Krishnan 2014), an elite ultra-trail runner's season average 87 km
# a week (Jaén-Carrillo et al. 2024), recreational 24-h runners' longest run ~60 km for the most
# distance (Knechtle et al. 2011). Finish / target time; working assumptions on those anchors.
ULTRA_WEEK = {"finish": 70.0, "time": 90.0}
ULTRA_LONG = {"finish": 35.0, "time": 45.0}
TRAIL_LONG_MAX = ULTRA_LONG["time"]
DESC_SESSIONS = 10              # Bontemps 2025
DESC_SESSION_MIN = 150.0        # m of descent that make a descent session …
DESC_SESSION_SHARE = 0.3        # … or this share of the per-run requirement, whichever is more
LONG_SHARE = 0.50               # the long run's share of the week in the goal's specific phase
LONG_SHARE_BASE = 0.30          # … and before it (guidance.LONG_SHARE)
SPECIFIC_MIN = 8                # weeks of the specific phase at least …
SPECIFIC_SLACK = 4              # … and the weeks the long run needs + the reserve and a week to spare
SPECIFIC_MAX = 12               # the phase labels (and the sessions, #11): the specific phase at most 12 weeks
# taper: share of the peak week, week by week (owner decision 2026-10-12: 2 weeks for the marathon;
# Bosquet 2007: −41–60 %; Smyth & Lawlor 2021: every week less than the one before)
TAPER = {1: [0.55], 2: [0.65, 0.45], "M": [0.60, 0.40]}
TAPER_LONG = 0.6                # the taper's first-week long run, share of the required long run
SAFE = {"key": "safe", "week": None, "run": None, "rise": 0.15, "deload": 0.55}   # 0.55 = guidance.CYCLE[4] / CYCLE[3]
RISK = {"key": "risk", "weekX": 25 / 15, "runX": 15 / 10, "rise": 0.20, "deload": 0.75}
ACWR_MAX = 1.5                  # Toresdahl 2022
HORIZON = 104                   # weeks projected at most
TAPER_SHORT_KM = 12.0
RESERVE_LONG_PLAN = 16
DAYS_HIST = C.FORMER_SPAN + 7    # days of history the engine's weekly capacity reaches back
WEEK_PATTERN = (0.0, 0.2, 0.0, 0.2, 0.0, 0.4, 0.2)   # a simulated week's days (Mon…Sun): long run on Saturday
HIST_WEEKS = 12                 # completed weeks of history: the former level looks 12 weeks back (capacity._former)

SRC = {
    "week10": ["abrahamson-et-al-2024"],
    "week21": ["fokkema-et-al-2020", "mohseni-et-al-2019"],
    "week42": ["fokkema-et-al-2020", "mohseni-et-al-2019", "rasmussen-et-al-2013", "doherty-et-al-2019"],
    "long": ["fokkema-et-al-2020", "toresdahl-et-al-2021", "yamaguchi-et-al-2022"],
    "count": ["doherty-et-al-2019", "toresdahl-et-al-2021"],
    "trail": ["soppelsa-et-al-2025"],
    "ultra": ["hoffman-and-krishnan-2014", "jaen-carrillo-et-al-2024", "knechtle-et-al-2011"],
    "descent": ["marqueste-et-al-2008", "bontemps-et-al-2025", "mchugh-2003", "nosaka-et-al-2001"],
    "taper": ["bosquet-et-al-2007", "wang-et-al-2023", "smyth-and-lawlor-2021"],
    "reserve": ["toresdahl-et-al-2022"],
    "risk": ["damsted-et-al-2019", "nielsen-et-al-2014", "toresdahl-et-al-2022"],
    "first": ["toresdahl-et-al-2021"],
}
VERDICT = {"ok": "Reálné", "tight": "Těsné", "no": "Nereálné", "unknown": "Zatím nelze spočítat"}
STATUS = {"ok": "Na cestě", "tight": "Zaostává", "no": "V ohrožení"}   # an active goal, checked again every day


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


def _r(v, dec=1):
    return None if v is None else round(v, dec)


def _cz(v, dec=0):
    if v is None:
        return "—"
    return (f"{v:.{dec}f}".replace(".", ",") if dec else str(int(round(v))))


def _weeks_cz(n: int) -> str:
    return f"{n} {'týden' if n == 1 else 'týdny' if 2 <= n <= 4 else 'týdnů'}"


def _dcz(d: date) -> str:
    return f"{d.day}. {d.month}. {d.year}"


def _interp(km: float, i: int, j: int) -> float:
    """Road requirement i (0 week, 1 long) for aim j (0 finish, 1 time) at a distance."""
    rows = ROAD
    if km <= rows[0][0]:
        return rows[0][1 + i][j]
    if km >= rows[-1][0]:
        return rows[-1][1 + i][j]
    for (k0, *a), (k1, *b) in zip(rows, rows[1:]):
        if k0 <= km <= k1:
            t = (km - k0) / (k1 - k0)
            return a[i][j] + t * (b[i][j] - a[i][j])
    return rows[-1][1 + i][j]


def taper_weeks(goal: dict) -> int:
    if goal.get("kind") == "free":
        return 0
    return 1 if (goal.get("km") or 0) <= TAPER_SHORT_KM else 2


def is_trail(goal: dict) -> bool:
    km, up = goal.get("km") or 0, goal.get("ascentM") or 0
    if goal.get("terrain") in ("trail", "road"):
        return goal["terrain"] == "trail"
    return km > 0 and (up / km >= TRAIL_M_PER_KM or km > 42.5)


# ------------------------------------------------------------------ requirements
def requirements(goal: dict) -> dict:
    """{week, long, longCount?, ascentRun, ascentWeek, descentRun, descentWeek, descSessions}
    — each {need, base?, why, sources}, None where the goal asks nothing of that channel."""
    aim = 1 if goal.get("aim") == "time" else 0
    aim_k = "time" if aim else "finish"
    out: dict = {}
    if goal.get("kind") == "free":
        f = goal.get("free") or {}
        if f.get("weeklyKm"):
            out["week"] = {"need": float(f["weeklyKm"]), "why": "váš cíl", "sources": []}
        if f.get("longKm"):
            out["long"] = {"need": float(f["longKm"]), "why": "váš cíl", "sources": []}
        if f.get("climbM"):
            per = "Run" if f.get("climbScope") == "run" else "Week"
            for ch in ("ascent", "descent"):
                out[ch + per] = {"need": float(f["climbM"]), "why": "váš cíl", "sources": []}
    else:
        km = float(goal.get("km") or 0)
        up = float(goal.get("ascentM") or 0)
        down = float(goal.get("descentM") if goal.get("descentM") is not None else up)
        if is_trail(goal):
            flat = km + SCARF_M * up / 1000.0
            road = _interp(flat, 0, aim)
            w = max(min(TRAIL_WEEK * km, ULTRA_WEEK[aim_k]), road)
            lg = min(TRAIL_LONG * km, ULTRA_LONG[aim_k])
            capped_w, capped_l = TRAIL_WEEK * km > ULTRA_WEEK[aim_k], TRAIL_LONG * km > ULTRA_LONG[aim_k]
            out["week"] = {"need": w, "sources": SRC["ultra"] if capped_w else SRC["trail"], "assumption": True,
                           "why": (f"ultra: nejvýš {_cz(ULTRA_WEEK[aim_k])} km ({'cílový čas' if aim else 'doběhnout'}), "
                                   f"aspoň jako maraton" if capped_w else
                                   f"trail: 1,5 × délka, aspoň jako silnice o {_cz(min(flat, 42.2))} km (stoupání převedené na rovinu)")}
            out["long"] = {"need": lg, "sources": SRC["ultra"] if capped_l else [], "assumption": True,
                           "why": (f"ultra: nejvýš {_cz(ULTRA_LONG[aim_k])} km, delší úseky závodu chůzí nebo dva dlouhé dny po sobě"
                                   if capped_l else "trail: 0,7 × délka (pracovní předpoklad)")}
            # one run's climb: the race's climb per km over the long run, at most 0.6 × the race's
            per_run = lambda h: min(TRAIL_RUN_CLIMB * h, h / km * lg) if km else TRAIL_RUN_CLIMB * h
            if up > 0:
                out["ascentRun"] = {"need": per_run(up), "sources": [], "assumption": True,
                                    "why": "0,6 × stoupání závodu v jednom běhu" if per_run(up) >= TRAIL_RUN_CLIMB * up - 0.5
                                    else "stoupání trati na délku dlouhého běhu"}
                out["ascentWeek"] = {"need": WEEK_CLIMB[aim_k] * up, "sources": [], "assumption": True,
                                     "why": "stoupání závodu za týden" if aim else "doběhnout: 0,6 × stoupání závodu za týden"}
            if down > 0:
                out["descentRun"] = {"need": per_run(down), "sources": [], "assumption": True,
                                     "why": "0,6 × klesání závodu v jednom běhu" if per_run(down) >= TRAIL_RUN_CLIMB * down - 0.5
                                     else "klesání trati na délku dlouhého běhu"}
                out["descentWeek"] = {"need": WEEK_CLIMB[aim_k] * down, "sources": [], "assumption": True,
                                      "why": "klesání závodu za týden" if aim else "doběhnout: 0,6 × klesání závodu za týden"}
                out["descSessions"] = {"need": DESC_SESSIONS, "why": "aspoň 10 seběhů, nejvýš jeden za 7 dní",
                                       "sources": SRC["descent"]}
        else:
            w, lg = _interp(km, 0, aim), _interp(km, 1, aim)
            src = SRC["week42"] if km >= 30 else SRC["week21"] if km >= 15 else SRC["week10"]
            out["week"] = {"need": w, "why": ("cílový čas" if aim else "doběhnout") + f" · {_cz(km, 1 if km % 1 else 0)} km",
                           "sources": src}
            out["long"] = {"need": lg, "why": "nejdelší běh v přípravě", "sources": SRC["long"]}
            if km >= COUNT_FROM_KM:
                thr, n = LONG_COUNT[aim_k]
                out["longCount"] = {"need": n, "km": thr, "why": f"dlouhé běhy aspoň {_cz(thr)} km",
                                    "sources": SRC["count"]}
            if up > 0:
                out["ascentWeek"] = {"need": WEEK_CLIMB[aim_k] * up, "sources": [], "assumption": True,
                                     "why": "stoupání trati za týden" if aim else "doběhnout: 0,6 × stoupání trati za týden"}
            if down > 0:
                out["descentWeek"] = {"need": WEEK_CLIMB[aim_k] * down, "sources": [], "assumption": True,
                                      "why": "klesání trati za týden" if aim else "doběhnout: 0,6 × klesání trati za týden"}
    lg = (out.get("long") or {}).get("need")
    # a free goal's long run never asks for more than an ultra week (owner report 2026-10-13: a 100 km
    # long run made a 200 km week); a run that long is a race, the note says so
    share_w = min(lg / LONG_SHARE, ULTRA_WEEK["time"]) if goal.get("kind") == "free" and lg else (lg / LONG_SHARE if lg else 0)
    if lg and out.get("week") and share_w > out["week"]["need"]:
        out["week"]["base"] = out["week"]["need"]
        out["week"]["need"] = share_w
        out["week"]["why"] += f" · aby dlouhý běh {_cz(lg)} km byl nejvýš 50 % týdne"
    elif lg and not out.get("week"):
        out["week"] = {"need": share_w, "why": f"aby dlouhý běh {_cz(lg)} km byl nejvýš 50 % týdne",
                       "sources": [], "derived": True}
    return out


# ------------------------------------------------------------------ the runner today
def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def runner_state(db, rid: str, a: dict | None = None, today: date | None = None, cycle_pos: int | None = None) -> dict:
    """Weekly history (6 completed calendar weeks before this Monday, oldest first) of km, the
    longest run, the descent and ascent sums and per-run maxima, the per-run capacities before
    this Monday as the engine reckons them (long30/down30/up30: the largest run of 30 days, older
    ones up to 90 days at a 30-day half-life; Monday, so the plan stays the same all week), the margins the capacity model
    uses for this runner, the place of this week in the 4-week cycle, the race experience and
    today's limits. Week 1 of the projection is this calendar week."""
    today = today or E.today_date()
    mon = _monday(today)
    lo = mon - timedelta(days=7 * HIST_WEEKS)
    d0 = mon - timedelta(days=DAYS_HIST)
    runs = E.acts(db, rid, "load")
    # the descent in the engine's steepness-weighted units (capacity.run_exposures): each run's own
    # profile factor, else the runner's median (plan k cíli 2.0 #2)
    fac = {x.id: C._ecc_factor(x.elevation_profile, (x.id, len(x.elevation_profile or [])))
           for x in runs if x.elevation_profile}
    facs = [f for f in fac.values() if f]
    ecc = E.median(facs) if facs else C.ECC_DEFAULT
    days = {"km": [0.0] * DAYS_HIST, "up": [0.0] * DAYS_HIST, "down": [0.0] * DAYS_HIST}
    first = None
    wk = [{"km": 0.0, "long": 0.0, "down": 0.0, "up": 0.0, "downRun": 0.0, "upRun": 0.0, "runs": 0}
          for _ in range(HIST_WEEKS)]
    l30, d30, u30, ever_long, ever_half = 0.0, 0.0, 0.0, 0.0, False
    for x in runs:
        try:
            dd = _d(x.started_at)
        except ValueError:
            continue
        first = dd if first is None or dd < first else first
        raw_down = x.descent_m
        if raw_down is None and x.elevation_profile:
            raw_down = terrain.descent_weighting(x.elevation_profile)[0]
        km, down, up = x.distance_km or 0.0, (raw_down or 0.0) * (fac.get(x.id) or ecc), x.ascent_m or 0.0
        if d0 <= dd < mon:
            i = (dd - d0).days
            days["km"][i] += km
            days["up"][i] += up
            days["down"][i] += down
        ever_long = max(ever_long, km)
        if km >= 20.5:
            ever_half = True
        age = (mon - dd).days
        if 0 < age <= C.CAP_MAX_AGE:      # the engine's per-run capacity: 30 days in full, then a 30-day half-life up to 90 days
            f = C._decay(age)
            l30, d30, u30 = max(l30, km * f), max(d30, down * f), max(u30, up * f)
        if lo <= dd < mon:
            w = wk[(dd - lo).days // 7]
            w["km"] += km
            w["down"] += down
            w["up"] += up
            w["long"] = max(w["long"], km)
            w["downRun"] = max(w["downRun"], down)
            w["upRun"] = max(w["upRun"], up)
            w["runs"] += 1
    rd = D.of(db, rid)
    hike = _hike_state(rd, d0, lo, mon, fac, ecc)
    train8 = _train8(runs, mon)
    races = rd.races
    past = [x for x in races if x.date and x.date[:10] < today.isoformat() and x.distance_km]
    if any((x.distance_km or 0) >= 21.0 for x in past):
        ever_half = True
    m = ((a or {}).get("capacity") or {}).get("margins") or {}
    g = (a or {}).get("guidance") or {}
    if cycle_pos is None:
        cycle_pos = (((g.get("week") or {}).get("cycle") or {}).get("autoPos"))
    pain = C.pain_dates(db, rid)
    from . import energy as EN                 # plan k cíli 2.0 #17: the energy & bone screen
    en = EN.state(rd.runner, today)
    pj = (getattr(rd.runner, "planner_json", None) or {}) if rd.runner is not None else {}
    bsi = EN.BSI_MARGIN if en["bsi"] else 1.0
    return {
        "today": today.isoformat(), "start": mon.isoformat(), "weeks": wk, "cyclePos": cycle_pos,
        "long30": l30, "down30": d30, "up30": u30,
        # the days before this Monday (oldest first) for the engine's own weekly capacity
        "days": days, "pain": [(d0 + timedelta(days=i)).isoformat() in pain for i in range(DAYS_HIST)],
        "known": (mon - first).days if first else 0, "eccFac": ecc,
        "marginWeek": float(m.get("runWeek") or C.MARGIN_WEEK) * bsi, "marginRun": float(m.get("runSession") or C.MARGIN_SESSION) * bsi,
        "experience": m.get("experience"), "everHalf": ever_half, "energy": en, "reserveExtra": 1 if en["bsi"] else 0,
        "marginWhy": [t for t, on in (("první rok běhání", m.get("experience")), ("dřívější zranění", (m.get("frailty") or 1.0) > 1.0),
                                      ("návrat po pauze", m.get("underconditioned")),
                                      ("přechod na nové boty", ((((a or {}).get("capacity") or {}).get("shoes") or {}).get("factor") or 1.0) < 1.0),
                                      ("dřívější únavová zlomenina", en["bsi"]),
                                      ("nárůsty vás často bolely", ((m.get("tolerance") or {}).get("factor") or 1.0) < 1.0))
                      if on],
        "everMarathon": ever_long >= 40.0 or any((x.distance_km or 0) >= 40.0 for x in past),
        "limited": g.get("override") or (g.get("mode") == "return"),
        # plan k cíli 2.0 stage B: hiking climb (#3), training km and pace of 8 weeks (#13), the
        # runner's week (#10), sleep (#18), how the plan has been kept (#6), sex (the Tanda note)
        "hike": hike, "train8": train8, "prefs": pj.get("prefs") or {}, "sleep14": _sleep14(rd, today),
        "missRate": _miss_rate(rd, wk, lo), "tolerance": m.get("tolerance"), "sex": getattr(rd.runner, "sex", None) if rd.runner is not None else None,
    }


HIKE_SPORTS = ("hiking", "walking")
HIKE_UP, HIKE_DOWN = 1.0, 0.5         # owner decision 2026-10-13: a hike's climb counts in full, its descent half


def _hike_state(rd, d0: date, lo: date, mon: date, fac: dict, ecc: float) -> dict | None:
    """Plan k cíli 2.0 #3: the climb of hikes and walks (ascent × 1, descent × 0.5 in the engine's
    weighted units) for a trail goal — days before this Monday, per-week sums and per-hike maxima,
    and the per-run capacity (30 days in full, then the 30-day half-life)."""
    days = {"up": [0.0] * DAYS_HIST, "down": [0.0] * DAYS_HIST}
    weeks = [{"up": 0.0, "down": 0.0, "upRun": 0.0, "downRun": 0.0} for _ in range(HIST_WEEKS)]
    u30 = d30 = 0.0
    n = 0
    for x in rd.activities:
        if (x.sport or "") not in HIKE_SPORTS or not E.counts_for(x, "load") or not x.started_at:
            continue
        up = (x.ascent_m or 0.0) * HIKE_UP
        raw = x.descent_m if x.descent_m is not None else x.ascent_m
        down = (raw or 0.0) * (fac.get(x.id) or ecc) * HIKE_DOWN
        if up <= 0 and down <= 0:
            continue
        try:
            dd = _d(x.started_at)
        except ValueError:
            continue
        if d0 <= dd < mon:
            i = (dd - d0).days
            days["up"][i] += up
            days["down"][i] += down
            n += 1
        age = (mon - dd).days
        if 0 < age <= C.CAP_MAX_AGE:
            f = C._decay(age)
            u30, d30 = max(u30, up * f), max(d30, down * f)
        if lo <= dd < mon:
            w = weeks[(dd - lo).days // 7]
            w["up"] += up
            w["down"] += down
            w["upRun"] = max(w["upRun"], up)
            w["downRun"] = max(w["downRun"], down)
    return {"days": days, "weeks": weeks, "up30": u30, "down30": d30, "n": n} if n else None


def with_hikes(st: dict) -> dict:
    """The runner state with the hikes' climb added (trail goals)."""
    h = st.get("hike")
    if not h:
        return st
    days = dict(st.get("days") or {})
    for k in ("up", "down"):
        if days.get(k):
            days[k] = [a + b for a, b in zip(days[k], h["days"][k])]
    weeks = [{**w, "up": w["up"] + hw["up"], "down": w["down"] + hw["down"],
              "upRun": max(w["upRun"], hw["upRun"]), "downRun": max(w["downRun"], hw["downRun"])}
             for w, hw in zip(st["weeks"], h["weeks"])] if len(h["weeks"]) == len(st["weeks"]) else st["weeks"]
    return {**st, "days": days, "weeks": weeks, "up30": max(st["up30"], h["up30"]), "down30": max(st["down30"], h["down30"]),
            "hikesIn": True}


def _train8(runs, mon: date) -> dict | None:
    """Plan k cíli 2.0 #13: the mean weekly km and the mean training pace (s/km) of the 8 weeks
    before this Monday — the inputs of Tanda's marathon formula."""
    lo8 = mon - timedelta(days=56)
    km = sec = km_t = 0.0
    for x in runs:
        try:
            dd = _d(x.started_at)
        except ValueError:
            continue
        if lo8 <= dd < mon and x.distance_km:
            km += x.distance_km
            if x.duration_min and x.distance_km >= 1.0:
                sec += x.duration_min * 60.0
                km_t += x.distance_km
    if km <= 0 or km_t <= 0:
        return None
    return {"km": km / 8.0, "pace": sec / km_t}


SLEEP_HOLD_H = 7.0           # #18: a 14-night mean under 7 hours holds the week (Huang & Ihm 2021)
SLEEP_NIGHTS_MIN = 10


def _sleep14(rd, today: date) -> float | None:
    """The mean sleep of the last 14 nights from the watch (at least 10 nights), else None."""
    lo = (today - timedelta(days=14)).isoformat()
    vals = [x.sleep_h for x in rd.daily if x.date and lo <= str(x.date)[:10] <= today.isoformat() and x.sleep_h]
    return sum(vals) / len(vals) if len(vals) >= SLEEP_NIGHTS_MIN else None


MISS_PRIOR, MISS_PRIOR_N = 0.03, 4     # #6: a week lost to life — the prior, shrunk to the runner's own record


def _miss_rate(rd, wk: list, lo: date) -> float:
    """The share of the active goal's recorded weeks run under 80 % of the plan, shrunk towards
    3 % with 4 pseudo-weeks (plan k cíli 2.0 #6: the misses follow the runner's real adherence)."""
    g = next((x for x in reversed(rd.goals) if x.status == "active"), None)
    rec = ((g.track_json or {}).get("weeks") or {}) if g is not None else {}
    n = miss = 0
    for i, w in enumerate(wk):
        p = rec.get((lo + timedelta(days=7 * i)).isoformat())
        if p and p.get("km") and not p.get("deload") and not p.get("taper"):
            n += 1
            miss += int(w["km"] < 0.8 * p["km"])
    return (miss + MISS_PRIOR * MISS_PRIOR_N) / (n + MISS_PRIOR_N)


# ------------------------------------------------------------------ projection
def _week_days(w: float, run: float = 0.0) -> list:
    """A simulated week's 7 days: the long run (or the biggest climb) on Saturday, the rest spread."""
    if run <= 0 or w <= 0:
        return [w * f for f in WEEK_PATTERN]
    rest = max(0.0, w - min(run, w)) / 3
    return [0.0, rest, 0.0, rest, 0.0, min(run, w), rest]


def _days_of(hist: list) -> list:
    """Days for a weekly history (synthetic states, the tests): each week spread by WEEK_PATTERN."""
    return [v for w in hist for v in _week_days(w)]


def _engine_cap(days: list, pain: list, known: int, ch: str) -> float | None:
    """capacity.weekly_capacity_vals on the days before a projected week (oldest first): the engine's
    own weekly capacity, so the plan's ceiling is the one Trénink shows (plan k cíli 2.0 #1)."""
    span = C.FORMER_SPAN
    vals = [0.0] * 7 + days[:-span - 1:-1] if len(days) >= span else [0.0] * 7 + days[::-1]
    pv = [False] * 7 + (pain[:-span - 1:-1] if len(pain) >= span else pain[::-1])
    vals += [0.0] * (span + 7 - len(vals))
    pv += [False] * (span + 7 - len(pv))
    return C.weekly_capacity_vals(vals, pv, known, ch)


def _cap(hist: list) -> float:
    """The engine's weekly capacity for a weekly history (spread over days by WEEK_PATTERN)."""
    days = _days_of(hist)
    return _engine_cap(days, [False] * len(days), 7 * len(hist), "volume") or sum(hist[-4:]) / 4


def former_level(hist: list) -> float:
    """The former level kept today (capacity._former before its 1.3 × limit): the best 3 weeks
    in a row of the last 12, × _decay of the days since the block (its last week = 7 days back)."""
    n, former = len(hist), 0.0
    for end in range(n - 1, max(C.FORMER_BLOCK - 2, n - 1 - (C.FORMER_WEEKS - C.FORMER_BLOCK)) - 1, -1):
        if end - C.FORMER_BLOCK + 1 >= 0:
            blk = hist[end - C.FORMER_BLOCK + 1:end + 1]
            former = max(former, sum(blk) / C.FORMER_BLOCK * C._decay(7 + 7 * (n - 1 - end)))
    return former


def deload_week(n: int, st: dict) -> bool:
    """Week n (1 = this calendar week) is a recovery week: the app's 4-week cycle goes on from
    the place this week has in it (guidance.cycle_position), else every 4th week."""
    if n in (st.get("vacWeeks") or ()):        # plan k cíli 2.0 #10: a holiday week runs like a recovery week
        return True
    pos0 = st.get("cyclePos") or 1
    return (pos0 - 1 + n - 1) % 4 == 3


def vac_weeks(st: dict) -> set:
    """Plan k cíli 2.0 #10: the plan's weeks (1 = this week) with 3+ days of the runner's holidays."""
    start = _d(st["start"])
    out = set()
    for v in (st.get("prefs") or {}).get("vacations") or []:
        try:
            a, b = _d(v["from"]), _d(v["to"])
        except (KeyError, ValueError, TypeError):
            continue
        d = max(a, start)
        while d <= b:
            n = (d - start).days // 7 + 1
            mon = start + timedelta(days=7 * (n - 1))
            if sum(1 for k in range(7) if a <= mon + timedelta(days=k) <= b) >= 3:
                out.add(n)
            d = mon + timedelta(days=7)
    return out


# plan k cíli 2.0 #6 (owner decision 2026-10-13): the chance of being ready by the date replaces the
# fixed reserve. Week by week the plan moves on unless an illness (27 % of marathon runners fell ill
# within 16 weeks, Toresdahl 2022 → 2 % a week, a week lost), an injury with lost training (40 %
# injured within 16 weeks → 3.1 % a week, 2 weeks lost) or a week of life (the runner's own record
# of weeks under 80 % of the plan, 3 % without one) gets in the way. Every combination is counted,
# not sampled. The rates and the lost weeks are working assumptions the goals' outcomes calibrate (#20).
HAZ_ILL = (0.0195, 1)
HAZ_INJURY = (0.031, 2)
CHANCE_OK, CHANCE_TIGHT = 0.80, 0.50
CHANCE_MAX = 95             # shown "více než 95 %": the model never knows a runner's future for sure
REAL_Q = 0.80               # the real date: the week 80 % of the runs of the plan are ready by
RANGE_Q = (0.10, 0.90)


def hazards(st: dict, path: str = "safe") -> list:
    """(probability a week, weeks lost) of an illness, an injury and a missed week for this runner:
    a past injury, the first year of running, a past bone stress injury and the risk path raise the
    injury rate (van Poppel 2020, Videbæk 2015, Damsted 2019; working multipliers)."""
    why = st.get("marginWhy") or []
    k = 1.0
    if "dřívější zranění" in why:
        k *= 1.5
    if "první rok běhání" in why:
        k *= 1.3
    if (st.get("energy") or {}).get("bsi"):
        k *= 1.5
    if path == "risk":
        k *= 1.5
    miss = min(0.3, max(0.0, st.get("missRate", MISS_PRIOR)))
    return [HAZ_ILL, (min(0.2, HAZ_INJURY[0] * k), HAZ_INJURY[1]), (miss, 1)]


def ready_cdf(ready: int | None, st: dict, path: str = "safe", horizon: int = HORIZON + 52) -> list:
    """P(ready by the end of week t), t = 0…horizon: the plan needs `ready` good weeks."""
    out = [0.0] * (horizon + 1)
    if not ready:
        return out
    hz = hazards(st, path)
    ok = max(0.0, 1.0 - sum(p for p, _ in hz))
    layers = {0: {0: 1.0}}
    for t in range(horizon):
        layer = layers.pop(t, None)
        if not layer:
            continue
        for done, pr in layer.items():
            if done + 1 >= ready:
                out[t + 1] += pr * ok
            else:
                nxt = layers.setdefault(t + 1, {})
                nxt[done + 1] = nxt.get(done + 1, 0.0) + pr * ok
            for p, lost in hz:
                if t + lost <= horizon:
                    nxt = layers.setdefault(t + lost, {})
                    nxt[done] = nxt.get(done, 0.0) + pr * p
    acc = 0.0
    for t in range(horizon + 1):
        acc += out[t]
        out[t] = acc
    return out


def _quant(cdf: list, q: float) -> int | None:
    return next((t for t, v in enumerate(cdf) if v >= q - 1e-9), None)


def chance_of(ready: int | None, taper: int, weeks: int, st: dict, path: str = "safe") -> dict:
    """{chance 0–1, real: the week ready at the 80th percentile, lo/hi: the 10th–90th}."""
    if not ready:
        return {"chance": 0.0, "real": None, "lo": None, "hi": None}
    cdf = ready_cdf(ready, st, path)
    t = weeks - taper
    return {"chance": cdf[t] if 0 <= t < len(cdf) else (1.0 if t >= len(cdf) else 0.0),
            "real": _quant(cdf, REAL_Q), "lo": _quant(cdf, RANGE_Q[0]), "hi": _quant(cdf, RANGE_Q[1])}


def verdict_of(chance: float) -> str:
    return "ok" if chance >= CHANCE_OK - 1e-9 else "tight" if chance >= CHANCE_TIGHT - 1e-9 else "no"


def _channel(hist_w: list, run0: float, need_w: float | None, need_run: float | None, path: dict,
             st: dict, floor_w: float = 0.0, floor_run: float = 0.0, share_from: int = 1,
             days: list | None = None, ch: str = "volume"):
    """One channel week by week: (weekly totals, per-run maxima), each list from week 1. The weekly
    ceiling is the engine's own weekly capacity (capacity.weekly_capacity_vals) on the history's
    days and the simulated ones before each week × (1 + the weekly margin). The long run (volume,
    floor_run == 0) is at most LONG_SHARE of the week from `share_from` (the specific phase),
    LONG_SHARE_BASE before it."""
    mw = st["marginWeek"] * path.get("weekX", 1.0)
    mr = st["marginRun"] * path.get("runX", 1.0)
    hist = [max(v, 0.0) for v in hist_w]
    if days is None:
        dd, pain, known = _days_of(hist), None, 7 * len(hist)
    else:
        dd, pain, known = list(days), list(st.get("pain") or [False] * len(days)), st.get("known") or 0
    pain = pain if pain is not None else [False] * len(dd)
    runs = [run0] * 4
    out_w, out_r = [], []
    full = hist[-1]                           # the last week that wasn't a recovery week
    for n in range(1, HORIZON + 1):
        last = hist[-1]
        avg4 = sum(hist[-4:]) / 4
        share = LONG_SHARE if n >= share_from else LONG_SHARE_BASE
        if deload_week(n, st):
            # two lighter weeks in a row (a holiday next to a recovery week) don't compound
            w = (full if deload_week(n - 1, st) and n > 1 else last) * path["deload"]
            r = min(runs[-1], max(w * (share if floor_run == 0.0 else 1.0), 0.0)) if need_run is not None else 0.0
        else:
            cap = _engine_cap(dd, pain, known + 7 * (n - 1), ch)
            cap = cap if cap is not None else sum(hist[-4:]) / 4
            ceil = max(cap * (1 + mw), floor_w)
            # the rise counts from the last 2 weeks (after a recovery week from the week before it), but
            # never from below the capacity the app already credits: after a few lighter weeks the plan
            # may climb back as fast as the app's own weekly ceiling allows (owner report 2026-10-13:
            # 50 km weeks in September, the plan started at 19 km — less than Trénink without a goal)
            ref = max(max(hist[-2:]), floor_w, cap)
            w = min(ceil, ref * (1 + path["rise"]), max(avg4 * ACWR_MAX, floor_w))
            if need_w is not None:
                w = min(w, max(need_w, last))
            r = 0.0
            if need_run is not None:
                r = min(max(max(runs[-4:]), floor_run) * (1 + mr), max(need_run, runs[-1]))
                if floor_run == 0.0:          # before the specific phase: no growth over 30 %, but no cut below today's long run
                    r = min(r, w * share if share == LONG_SHARE else max(w * share, min(run0, w * LONG_SHARE)))
                else:
                    r = min(r, w)
        if not deload_week(n, st):
            full = w
        hist.append(w)
        dd += _week_days(w, r)
        pain += [False] * 7
        runs.append(r)
        out_w.append(w)
        out_r.append(r)
    return out_w, out_r


def avg_rise(st: dict, path: dict = SAFE) -> float:
    """The weekly volume's average growth on this path, recovery weeks included: the peak of the
    6th 4-week cycle over the peak of the 1st, per week (the chart says why the plan takes the
    weeks it does — owner feedback 2026-10-12 read them as days). 15 % margin ≈ 4.4 % a week."""
    w, _ = _channel([40.0] * HIST_WEEKS, 12.0, None, None, path, {**st, "cyclePos": 1})   # above every floor
    return (max(w[20:24]) / max(w[0:4])) ** (1 / 20) - 1


def project(req: dict, st: dict, path: dict, share_from: int = 1, until: int = 0) -> dict:
    """Week rows (1 = this calendar week) and the first week every requirement is met (None if
    not within HORIZON). Rows are kept up to max(until, ready + 2)."""
    wk = st["weeks"]
    need_w = (req.get("week") or {}).get("need")
    need_l = (req.get("long") or {}).get("need")
    sd = st.get("days") or {}
    km_w, long_r = _channel([w["km"] for w in wk], st["long30"],
                            need_w, need_l if need_l else 0.0, path, st, share_from=share_from, days=sd.get("km"), ch="volume")
    rows = [{"km": km_w[i], "long": long_r[i], "deload": deload_week(i + 1, st)} for i in range(HORIZON)]
    for ch, key in (("descent", "down"), ("ascent", "up")):
        nw = (req.get(ch + "Week") or {}).get("need")
        nr = (req.get(ch + "Run") or {}).get("need")
        if nw is None and nr is None:
            continue
        spec = C.CHANNELS[ch]
        rf = st.get("descFac", 1.0) if ch == "descent" else 1.0        # the race's metres → the engine's weighted metres
        nw2 = nw * rf if nw is not None else None
        nr2 = (nr if nr is not None else (nw or 0) * TRAIL_RUN_CLIMB) * rf
        vw, vr = _channel([w[key] for w in wk], st[key + "30"], nw2, nr2, path, st,
                          floor_w=spec["floor_w"], floor_run=spec["floor_s"], days=sd.get(key), ch=ch)
        for i, row in enumerate(rows):
            row[ch], row[ch + "Run"] = vw[i] / rf, vr[i] / rf
    count_thr = (req.get("longCount") or {}).get("km")
    desc_min = _desc_min(req)
    n_long, n_desc = 0, desc_done(req, st)
    ready, first = None, {}
    for i, row in enumerate(rows):
        if count_thr and row["long"] >= count_thr - 0.05:
            n_long += 1
        if req.get("descSessions") and not row["deload"] and row.get("descentRun", 0) >= desc_min:
            n_desc += 1
        row["longCount"], row["descSessions"] = n_long, n_desc
        met = {
            "week": row["km"] >= (req.get("week") or {}).get("need", 0) - 0.05,
            "long": row["long"] >= (req.get("long") or {}).get("need", 0) - 0.05,
            "longCount": n_long >= (req.get("longCount") or {}).get("need", 0),
            "descSessions": n_desc >= (req.get("descSessions") or {}).get("need", 0),
        }
        for ch in ("ascentWeek", "ascentRun", "descentWeek", "descentRun"):
            if req.get(ch):
                v = row.get(ch[:-4] if ch.endswith("Week") else ch, 0)
                met[ch] = v >= req[ch]["need"] - 0.5
        for k, ok in met.items():
            if ok and k not in first:
                first[k] = i + 1
        if ready is None and all(met.values()):
            ready = i + 1
        if ready is not None and i + 1 >= max(until, ready + 2):
            break
    keys = [k for k in req if k in ("week", "long", "longCount", "descSessions", "ascentWeek", "ascentRun",
                                    "descentWeek", "descentRun")]
    last = {k: first.get(k) for k in keys}
    bottleneck = max(keys, key=lambda k: last[k] or HORIZON + 1) if keys else None
    shown = rows[:min(len(rows), max(until, (ready or 26) + 2))]
    return {"path": path["key"], "readyWeek": ready, "firstMet": last, "bottleneck": bottleneck, "shareFrom": share_from,
            "rows": [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()} for r in shown]}


def phased(req: dict, st: dict, path: dict, weeks: int, taper: int) -> dict:
    """The projection with the long-run share of the plan's phases: 50 % only in the specific
    phase — the last weeks before the taper, as many as the long run needs to reach the race
    distance (at least SPECIFIC_MIN) — 30 % before it (owner decision 2026-10-12). Falls back
    to 50 % throughout when a shorter specific phase would miss the date."""
    build = max(0, weeks - taper)
    p0 = project(req, st, path, 1, until=weeks)
    # the earliest the runner can be ready (the plan itself may peak later, just before the race):
    # the good weeks the chance (#6) counts
    p0["earliest"] = p0["readyWeek"]
    k = p0["firstMet"].get("long") or p0["readyWeek"] or build
    spec = min(build, max(SPECIFIC_MIN, k + SPECIFIC_SLACK))
    start = max(1, build - spec + 1)
    if start == 1:
        return p0
    p1 = project(req, st, path, start, until=weeks)
    if p1["readyWeek"] is None or (p0["readyWeek"] and p0["readyWeek"] <= build < p1["readyWeek"]):
        return p0
    p1["earliest"] = min(x for x in (p0["readyWeek"], p1["readyWeek"]) if x) if (p0["readyWeek"] or p1["readyWeek"]) else None
    return p1


def taper_factors(goal: dict) -> list:
    t = taper_weeks(goal)
    if not t:
        return []
    km = goal.get("km") or 0
    return TAPER[1] if t == 1 else TAPER["M"] if km >= COUNT_FROM_KM else TAPER[2]


def plan_weeks(goal: dict, st: dict, proj: dict, weeks: int) -> list:
    """The plan towards the goal, one row per calendar week from this Monday to the goal's week:
    phase, the week's km, the long run, climbing where the goal has it, the recovery weeks,
    the taper and the milestones. The weeks before the taper follow the projection; the taper
    cuts the peak week (the highest of the last 4 before it) step by step, intensity and the
    number of runs stay (Bosquet 2007, Wang 2023)."""
    start = _d(st["start"])
    gd = _d(goal["date"])
    tf = taper_factors(goal)
    build = max(0, weeks - len(tf))
    rows = proj["rows"]
    req = requirements(goal)
    spec_from = proj.get("shareFrom") or 1
    if spec_from == 1:
        spec_from = max(1, build - max(SPECIFIC_MIN, (proj["firstMet"].get("long") or build) + SPECIFIC_SLACK) + 1)
    # a long plan whose long run needs every week is "specific" for the long run's share, but its
    # sessions and strength (#11, #14) follow a build phase until the last 12 weeks before the taper
    sess_from = max(spec_from, build - SPECIFIC_MAX + 1)
    first_m = (goal.get("kind") != "free" and not is_trail(goal) and (goal.get("km") or 0) >= COUNT_FROM_KM
               and not st.get("everMarathon"))
    rest = spec_from - 1
    base_end = (rest + 1) // 2
    out = []
    peak = None
    half_done = st.get("everHalf")
    for i in range(1, weeks + 1):
        w = {"i": i, "start": (start + timedelta(days=7 * (i - 1))).isoformat()}
        if i <= build:
            r = rows[min(i, len(rows)) - 1]
            w.update({k: r.get(k) for k in ("km", "long", "descent", "descentRun", "ascent", "ascentRun") if r.get(k) is not None})
            w["deload"] = r["deload"]
            w["phase"] = "specific" if i >= spec_from else "base" if i <= base_end else "build"
            if w["phase"] == "specific" and i < sess_from:
                w["sessionPhase"] = "build"
            if not half_done and first_m and (w.get("long") or 0) >= 20.5:
                w["milestone"] = "half"
                half_done = True
        else:
            if peak is None:
                prev = [x for x in out[-4:] if not x.get("deload")] or out[-4:] or [{"km": rows[0]["km"], "long": rows[0]["long"]}]
                peak = {"km": max(x.get("km") or 0 for x in prev), "long": max(x.get("long") or 0 for x in prev)}
            j = len(tf) - (weeks - i)               # counted from the goal's week, also when fewer weeks are left than the taper
            f = tf[j - 1]
            w.update({"phase": "taper", "taper": j, "factor": f, "km": _r(peak["km"] * f),
                      "long": _r(min(peak["long"], (req.get("long") or {}).get("need") or peak["long"]) * TAPER_LONG) if j < len(tf) else None,
                      "deload": False})
            if j == len(tf):
                w["race"] = True
        if first_m:
            w["runs"] = 3
        if i in (st.get("vacWeeks") or ()) and not w.get("taper"):
            w["vacation"] = True
        to_race = weeks - i                        # weeks before the race week
        if (goal.get("kind") != "free" and goal.get("aim") == "time" and not is_trail(goal)
                and (goal.get("km") or 0) >= 10 and to_race == TEST_WEEKS_OUT and not w.get("milestone")):
            w["milestone"] = "test"
        if goal.get("hot") and goal.get("kind") != "free":
            # #16: heat acclimation over the days 21–8 before the race (10–14 days, done a week before
            # the start), short reminders in the last week (Tyler 2016; Daanen 2017: ~2.5 % lost a day)
            ds = [(gd - (_d(w["start"]) + timedelta(days=k))).days for k in range(7)]
            if any(HEAT_FROM >= x >= HEAT_TO for x in ds):
                w["heat"] = "acclim"
            elif any(0 < x < HEAT_TO for x in ds):
                w["heat"] = "remind"
        if goal.get("kind") != "free" and 0 < to_race <= FUEL_WEEKS and w.get("long") \
                and w["long"] * _long_pace(st) / 60 >= FUEL_MIN:
            ultra = (goal.get("km") or 0) >= 50
            w["fuel"] = int(round(FUEL_G[0] + ((FUEL_G[1] - FUEL_G[0]) * (FUEL_WEEKS - to_race) / (FUEL_WEEKS - 1) if ultra else 0), -1))
        # plan k cíli 2.0 #14: strength is part of the plan — 2× a week in the base and build, 1× in the
        # specific phase and the recovery weeks, a light one in the taper, none in the race week
        # (Lauersen 2018; it protects only when done: Desai 2023, Wu 2024)
        w["strength"] = (0 if w.get("race") else 1 if w.get("taper") or w.get("deload")
                         or (w.get("sessionPhase") or w["phase"]) == "specific" else 2)
        out.append(w)
    return out


# ------------------------------------------------------------------ the verdict
LABEL = {"week": "Týdenní objem ve vrcholu", "long": "Nejdelší běh", "longCount": "Počet dlouhých běhů",
         "ascentWeek": "Stoupání za týden", "ascentRun": "Stoupání v jednom běhu",
         "descentWeek": "Klesání za týden", "descentRun": "Klesání v jednom běhu", "descSessions": "Seběhy"}
FIELD = {"week": "km", "long": "long", "longCount": "longCount", "ascentWeek": "ascent", "ascentRun": "ascentRun",
         "descentWeek": "descent", "descentRun": "descentRun", "descSessions": "descSessions"}
UNIT = {"week": "km", "long": "km", "longCount": "×", "ascentWeek": "m", "ascentRun": "m", "descentWeek": "m",
        "descentRun": "m", "descSessions": "×"}


def _desc_min(req: dict) -> float:
    """The descent that makes a run a descent session: 150 m or 30 % of the per-run requirement,
    never more than the requirement itself (a short trail's 120 m could never count before)."""
    need = (req.get("descentRun") or {}).get("need") or 0
    return min(max(DESC_SESSION_MIN, DESC_SESSION_SHARE * need), need) if need else DESC_SESSION_MIN


def desc_done(req: dict, st: dict) -> int:
    """Descent sessions already done: the weeks of the history (12) with a run of that much descent,
    at most one a week. The protection of a downhill bout lasts at least 6 months (Nosaka et al.,
    2001); before, the count started at zero every time (owner report 2026-10-13)."""
    if not req.get("descSessions"):
        return 0
    m = _desc_min(req) * st.get("descFac", 1.0)          # the weeks' runs are in the engine's weighted metres
    return min(DESC_SESSIONS, sum(1 for w in st["weeks"][-HIST_WEEKS:] if (w.get("downRun") or 0) >= m - 0.5))


def _now(k: str, st: dict, req: dict | None = None) -> float | None:
    if k == "descSessions":
        return desc_done(req or {}, st)
    wk = st["weeks"]
    if k == "week":
        return max(w["km"] for w in wk[-4:])
    if k == "long":
        return st["long30"]
    rf = st.get("descFac", 1.0)
    if k == "ascentWeek":
        return max(w["up"] for w in wk[-4:])
    if k == "descentWeek":
        return max(w["down"] for w in wk[-4:]) / rf
    if k in ("ascentRun", "descentRun"):
        return st["up30"] if k.startswith("a") else st["down30"] / rf
    return 0


def _weeks_to(goal_date: date, start: date) -> int:
    """Calendar weeks from `start` (a Monday) up to and including the goal's week."""
    return (goal_date - start).days // 7 + 1


def reserve_weeks(ready, taper, st: dict | None = None) -> int:
    """The weeks kept for illness and bad weeks: 2, 3 in a plan over 16 weeks, one more after a
    bone stress injury (plan k cíli 2.0 #17)."""
    return (3 if (ready or 0) + taper > RESERVE_LONG_PLAN else 2) + int((st or {}).get("reserveExtra") or 0)


def _fit(ready, taper, weeks, st: dict | None = None) -> str:
    if ready is None:
        return "no"
    reserve = reserve_weeks(ready, taper, st)
    if ready + taper + reserve <= weeks:
        return "ok"
    return "tight" if ready + taper <= weeks else "no"


def descent_factor(goal: dict, st: dict) -> float:
    """The goal's descent in the engine's steepness-weighted units per metre (1 + 3.2 × grade, as
    terrain.descent_weighting): a race's grade from its descent over half its distance, a free goal
    at the runner's own training steepness; 1 for a state without the engine's units (plan k cíli 2.0 #2)."""
    if not st.get("eccFac"):
        return 1.0
    km = goal.get("km") or 0
    down = goal.get("descentM") if goal.get("descentM") is not None else goal.get("ascentM")
    if goal.get("kind") == "free" or not km or not down:
        return st["eccFac"]
    return 1.0 + terrain._ECC_PER_GRADE * min(down / (km * 500.0), 0.45)


def evaluate(goal: dict, st: dict, alternatives: bool = True) -> dict:
    """The whole feasibility answer for one goal."""
    if is_trail(goal) or (goal.get("kind") == "free" and (goal.get("free") or {}).get("climbM")):
        st = with_hikes(st)                    # plan k cíli 2.0 #3: the hikes' climb counts towards a trail goal
    st = {**st, "descFac": descent_factor(goal, st)}
    st["vacWeeks"] = vac_weeks(st) if (st.get("prefs") or {}).get("vacations") else set()
    start = _d(st["start"])
    gdate = _d(goal["date"])
    weeks = _weeks_to(gdate, start)
    taper = taper_weeks(goal)
    req = requirements(goal)
    known = sum(1 for w in st["weeks"][-6:] if w["runs"]) >= 3
    out = {"goal": goal, "start": st["start"], "weeksToGoal": weeks, "taperWeeks": taper,
           # the chart says why it takes these weeks
           "margins": {"week": _r(st["marginWeek"] * 100), "run": _r(st["marginRun"] * 100), "avgRise": _r(avg_rise(st) * 100),
                       # the former level the way back heads for, when it is above the last 4 weeks (v0.12.6)
                       "former": _r(_fl) if (_fl := former_level([w["km"] for w in st["weeks"]]))
                       > 1.05 * sum(w["km"] for w in st["weeks"][-4:]) / 4 + 1 else None},
           "requirements": [], "notes": [], "sources": sorted({s for r in req.values() for s in r.get("sources", [])})}
    for k, r in req.items():
        out["requirements"].append({"key": k, "label": LABEL[k], "unit": UNIT[k], "need": _r(r["need"]),
                                    "base": _r(r.get("base")), "km": r.get("km"), "now": _r(_now(k, st, req)),
                                    "why": r["why"], "sources": r.get("sources", []), "assumption": bool(r.get("assumption"))})
    if not req:
        out.update(verdict="unknown", verdictLabel=VERDICT["unknown"], text="Cíl zatím nemá žádný požadavek. Zadejte aspoň jedno číslo.")
        return out
    if not known:
        out.update(verdict="unknown", verdictLabel=VERDICT["unknown"],
                   text="Na projekci potřebuji aspoň 3 z posledních 6 týdnů s běháním z hodinek. Zatím aplikace neví, z čeho by kapacita rostla.")
        return out
    # the last 4 completed weeks in the projection's channels (the chart's history)
    rf = st["descFac"]
    out["history"] = [{"km": _r(w["km"]), "long": _r(w["long"]), "ascent": _r(w["up"]), "descent": _r(w["down"] / rf),
                       "ascentRun": _r(w["upRun"]), "descentRun": _r(w["downRun"] / rf)} for w in st["weeks"][-4:]]
    safe = phased(req, st, SAFE, weeks, taper)
    risk = phased(req, st, RISK, weeks, taper)
    rr = risk["readyWeek"]
    se, re_ = safe.get("earliest") or safe["readyWeek"], risk.get("earliest") or rr
    cs, cr = chance_of(se, taper, weeks, st), chance_of(re_, taper, weeks, st, "risk")
    v = verdict_of(cs["chance"])
    out["riskPossible"] = bool(re_ and re_ + taper <= weeks)
    out["feasible"] = bool(se and se + taper <= weeks)
    # a chance is never a certainty (the proposal: "nevydávat šanci za jistotu"): at most 95 %
    out["chance"], out["riskChance"] = min(CHANCE_MAX, round(cs["chance"] * 100)), min(CHANCE_MAX, round(cr["chance"] * 100))
    path = "risk" if goal.get("path") == "risk" else "safe"
    chosen = risk if path == "risk" else safe
    pv = v if path == "safe" else verdict_of(cr["chance"])
    out.update(path=path, status=pv, statusLabel=STATUS[pv])
    if weeks <= HORIZON:
        out["plan"] = plan_weeks(goal, st, chosen, weeks)
    reserve = (cs["real"] - se) if cs["real"] else reserve_weeks(se, taper, st)
    out.update(safe=safe, risk=risk, reserveWeeks=reserve, verdict=v, verdictLabel=VERDICT[v])
    # the gauges (owner feedback 2026-10-13: pictures, not sentences): the safe path at its peak
    # before the taper ("na startu") and the week each requirement is met
    peak = safe["rows"][:max(1, weeks - taper)]
    for q in out["requirements"]:
        f = FIELD[q["key"]]
        vals = [w.get(f) for w in peak if w.get(f) is not None]
        q["atRace"] = (vals[-1] if q["unit"] == "×" else max(vals)) if vals else None
        q["metWeek"] = safe["firstMet"].get(q["key"])
    if se:
        real = start + timedelta(days=7 * (se + taper + reserve) - 1)
        out["realDate"] = real.isoformat()
        out["readyDate"] = (start + timedelta(days=7 * se - 1)).isoformat()
        if cs["lo"] and cs["hi"]:                   # when the runner is ready, 10th–90th percentile
            out["readyRange"] = {"from": (start + timedelta(days=7 * cs["lo"] - 1)).isoformat(),
                                 "to": (start + timedelta(days=7 * cs["hi"] - 1)).isoformat()}
    bn = safe["bottleneck"]
    bn_txt = None
    if bn:
        r = next(x for x in out["requirements"] if x["key"] == bn)
        when = safe["firstMet"].get(bn)
        # a sentence starts with a word, so the English dictionary can split the text into sentences
        what = (f"Dlouhé běhy aspoň {_cz(r['km'])} km ({_cz(r['need'])}×)" if bn == "longCount"
                else f"Seběhy ({_cz(r['need'])}×)" if bn == "descSessions" else f"{r['label']} {_cz(r['need'])} {r['unit']}")
        bn_txt = what + (f" stihnete bezpečně za {_weeks_cz(when)}" if when else " bezpečně nestihnete do 2 let")
        out["bottleneckText"] = bn_txt
    gd = _dcz(gdate)
    # one sentence per template, so the app's English dictionary can translate each
    bn_s = f" {bn_txt}." if bn_txt else ""
    ch_s = (f"Šance, že do {gd} budete bezpečně připraveni: více než {CHANCE_MAX} %." if out["chance"] >= CHANCE_MAX
            else f"Šance, že do {gd} budete bezpečně připraveni: {out['chance']} %.")
    if v == "ok":
        n = _weeks_cz(se)
        out["text"] = (ch_s + " " + (f"Bez výpadku budete připraveni zhruba za {n}, pak {_weeks_cz(taper)} ladění." if taper
                                     else f"Bez výpadku budete připraveni zhruba za {n}.")
                       + " Šance počítá s nemocí, zraněním i horšími týdny.")
    elif v == "tight":
        out["text"] = (ch_s + f" Bez výpadku budete připraveni za {_weeks_cz(se)} z {weeks}, "
                       "na nemoc a horší týdny zbývá málo času." + bn_s)
    elif out["feasible"]:
        out["text"] = (ch_s + " Vyšlo by to jen bez výpadku." + bn_s
                       + (f" Reálný termín je od {_dcz(_d(out['realDate']))}." if out.get("realDate") else ""))
    else:
        out["text"] = (f"Do {gd} to bezpečně nestihnete." + bn_s
                       + (f" Reálný termín je od {_dcz(_d(out['realDate']))}." if out.get("realDate") else ""))
    hz = hazards(st, path)
    out["notes"].append({"key": "chance", "sources": SRC["reserve"],
                         "text": f"Šance počítá s nemocí ({_cz(hz[0][0] * 100, 1)} % týdně, týden výpadku), zraněním "
                                 f"({_cz(hz[1][0] * 100, 1)} % týdně, 2 týdny) a týdny, kdy se plán nepodaří splnit "
                                 f"({_cz(hz[2][0] * 100, 0)} % týdně podle vašeho plnění)."})
    if goal.get("kind") != "free" and not is_trail(goal) and (goal.get("km") or 0) >= COUNT_FROM_KM:
        if not st["everHalf"]:
            out["notes"].append({"key": "half", "text": "Půlmaraton ještě v historii nemáte. Plán k cíli do přípravy vloží běh na 21 km "
                                 "nebo nabídne B‑závod na půlmaraton: běžci s půlmaratonem za sebou se při přípravě na první "
                                 "maraton zranili méně často (OR 0,40).", "sources": SRC["first"]})
        if not st["everMarathon"]:
            out["notes"].append({"key": "freq", "text": "U prvního maratonu bude plán stavět na 3 bězích týdně a čtvrtý přidá jen tehdy, "
                                 "když se objem jinak nedá postavit. Kdo běhal aspoň 4× týdně, zranil se o 36 % častěji. "
                                 "Další aerobní trénink nabídne jako kolo.", "sources": SRC["first"]})
    if taper:
        out["notes"].append({"key": "taper", "text": f"Ladění {_weeks_cz(taper)} před závodem: objem dolů o 40–60 %, "
                             "intenzita a počet běhů zůstanou.", "sources": SRC["taper"]})
    from . import goal_sessions as GS          # plan k cíli 2.0 #11: the intensity distribution
    if goal.get("kind") != "free":
        out["notes"].append({"key": "intensity", "sources": GS.SOURCES[:4],
                             "text": GS.distribution(GS.ctx_of(goal, "specific", experienced(st)))})
    if goal.get("kind") == "free" and ((goal.get("free") or {}).get("longKm") or 0) > TRAIL_LONG_MAX:
        out["notes"].append({"key": "ultra", "sources": SRC["ultra"],
                             "text": f"Běh delší než {_cz(TRAIL_LONG_MAX, 0)} km je spíš závod než trénink. Pro přípravu na ultra zvolte Závod: "
                                     "aplikace pak počítá s dlouhými běhy 35–45 km."})
    if st.get("limited"):
        out["notes"].append({"key": "limited", "text": "Teď máte omezení tréninku (bolest, zranění nebo návrat po něm). Projekce počítá "
                             "s tím, že trénink půjde bez přerušení, takže skutečný termín bude nejspíš později.", "sources": []})
    if st["marginWeek"] < C.MARGIN_WEEK - 0.001:
        why = st.get("marginWhy") or []
        out["notes"].append({"key": "margin", "sources": [], "pct": _r(st["marginWeek"] * 100), "why": why,
                             "text": f"Týdenní rezerva je u vás teď {_cz(st['marginWeek'] * 100)} % místo 15 %"
                                     + (f" ({' · '.join(why)})" if why else "") + ", proto kapacita v projekci roste pomaleji."})
    tol = st.get("tolerance") or {}
    if tol.get("personal"):                    # v0.12.8 (#5): the runner's own record of rises
        out["notes"].append({"key": "tolerance", "sources": [], "n": tol["n"], "painful": tol["painful"],
                             "text": f"Z vaší historie: po {tol['painful']} z {tol['n']} týdenních nárůstů nad 15 % přišla do 21 dní "
                                     f"bolest. Rezervy proto násobí {_cz(tol['factor'], 2)}."})
    en = st.get("energy") or {}
    if en.get("hold"):                         # plan k cíli 2.0 #17: no period for 90+ days
        out["hold"] = {"kind": "energy", "why": en["hold"]["why"]}
        out["notes"].insert(0, {"key": "energy", "sources": ["heikura-et-al-2017", "gallant-et-al-2024"],
                                "text": f"Plán teď neroste ({en['hold']['why']}). Chybějící menstruace bývá známkou nízké "
                                        "energetické dostupnosti a ta zvyšuje riziko únavové zlomeniny. Objednejte se ke "
                                        "sportovnímu lékaři. Týdny zatím drží vaši současnou úroveň."})
    elif (st.get("sleep14") or 99) < SLEEP_HOLD_H:   # plan k cíli 2.0 #18: short sleep holds the week
        sl = _cz(st["sleep14"], 1)
        out["hold"] = {"kind": "sleep", "why": f"spánek 14 nocí v průměru {sl} h"}
        out["notes"].insert(0, {"key": "sleep", "sources": ["huang-and-ihm-2021", "dobrosielski-et-al-2021"],
                                "text": f"Spíte v průměru {sl} h (14 nocí). Plán teď neroste, ale ani neklesá: spánek pod "
                                        "7 hodin šel v některých studiích s vyšším rizikem zranění. Jakmile průměr přesáhne "
                                        "7 hodin, plán poroste dál."})
    if en.get("fuel"):
        out["notes"].append({"key": "fuel", "sources": ["gallant-et-al-2024", "kraus-et-al-2018"],
                             "text": "Uvedli jste známky nedostatku energie. Jezte víc kolem tréninku, hlavně sacharidy "
                                     "před dlouhým během a po něm, a poraďte se se sportovním lékařem nebo nutričním terapeutem."})
    if goal.get("hot") and goal.get("kind") != "free":
        out["notes"].append({"key": "heat", "sources": HEAT_SOURCES,
                             "text": "Horký závod: 21 až 8 dní před startem 10–14 dní aklimatizace na horko (lehký běh v teple "
                                     "nebo ve vrstvách oblečení, případně sauna po běhu), v posledním týdnu 1–2 krátké připomínky. "
                                     "Bez horka se adaptace ztrácí asi o 2,5 % za den."})
    if st.get("hikesIn"):
        out["notes"].append({"key": "hike", "sources": [],
                             "text": "K trailovému cíli se počítá i stoupání z turistiky: celé, klesání z poloviny."})
    out["notes"] += _life_notes(goal, st, req, out)
    te = train_estimate(goal, st, out.get("plan"))
    if te:
        out["trainEstimate"] = te
    if alternatives and v != "ok":
        out["alternatives"] = _alternatives(goal, st, out, risk, taper, weeks)
    return out


def experienced(st: dict) -> bool:
    """A runner past the first year with a half marathon behind them (#11: a time goal goes polarised)."""
    return bool(st.get("everHalf")) and not st.get("experience")


def _long_pace(st: dict) -> float:
    """The long run's pace (s/km): the 8 weeks' training pace + 8 %, 6:40 /km without one."""
    p = (st.get("train8") or {}).get("pace")
    return p * 1.08 if p else 400.0


def _life_notes(goal: dict, st: dict, req: dict, out: dict) -> list:
    """Plan k cíli 2.0 #10: the runner's week — holidays, the time for the long run and the week."""
    pr = st.get("prefs") or {}
    notes = []
    vw = sorted(st.get("vacWeeks") or [])
    if vw:
        notes.append({"key": "vacation", "sources": [], "weeks": vw,
                      "text": f"Dovolená: {len(vw)} {'týden' if len(vw) == 1 else 'týdny' if len(vw) <= 4 else 'týdnů'} "
                              "plán počítá jako odlehčené, kapacita pak roste dál."})
    pace = _long_pace(st)
    need_l = (req.get("long") or {}).get("need")
    long_min = pr.get("longMin")
    if need_l and long_min and need_l * pace / 60 > long_min + 5:
        notes.append({"key": "time", "sources": [],
                      "text": f"Dlouhý běh {_cz(need_l, 0)} km zabere asi {round(need_l * pace / 60 / 5) * 5} min, "
                              f"na dlouhý běh máte {long_min} min. Najděte víc času, nebo zvolte kratší cíl."})
    days, day_min = pr.get("days") or [], pr.get("dayMin")
    need_w = (req.get("week") or {}).get("need")
    if need_w and days and day_min:
        avail = (len(days) - (1 if long_min else 0)) * day_min + (long_min or 0)
        week_min = need_w * pace / 0.92 / 60                # easy runs a little quicker than the long one
        if week_min > avail + 10:
            notes.append({"key": "time", "sources": [],
                          "text": f"Na {_cz(need_w, 0)} km týdně potřebujete asi {_cz(week_min / 60, 1)} h běhu, "
                                  f"ve vašem týdnu je {_cz(avail / 60, 1)} h."})
    return notes


# plan k cíli 2.0 #13: the marathon time from training (Tanda 2011: mean weekly km and mean training
# pace of the 8 weeks before; SEE ≈ 4 min, RMSE 5.4 min for 2:47–3:36 in the 2022 validation)
def tanda_pace(km_week: float, pace: float) -> float:
    return 17.1 + 140.0 * math.exp(-0.0053 * km_week) + 0.55 * pace


def train_estimate(goal: dict, st: dict, plan: list | None) -> dict | None:
    """A road marathon's time from the plan's 8 peak weeks and today's training pace."""
    t8 = st.get("train8")
    km = goal.get("km") or 0
    if not t8 or goal.get("kind") == "free" or is_trail(goal) or not (40.0 <= km <= 43.0):
        return None
    pre = [w for w in (plan or []) if not w.get("taper")][-8:]
    k_plan = sum(w.get("km") or 0 for w in pre) / len(pre) if pre else t8["km"]
    t_now = tanda_pace(t8["km"], t8["pace"]) * 42.195
    t_plan = tanda_pace(k_plan, t8["pace"]) * 42.195
    return {"kmWeek": _r(k_plan), "kmNow": _r(t8["km"]), "pace": round(t8["pace"]), "timeS": round(t_plan), "nowS": round(t_now),
            "sources": ["tanda-2011"],
            "text": f"S {_cz(k_plan, 0)} km týdně ve vrcholu přípravy a dnešním tréninkovým tempem {_hms(t8['pace'])} /km "
                    f"vychází zhruba {_hms(t_plan)}.",
            "note": "Odhad z tréninku (Tandův vzorec) má chybu kolem 4–5 minut u časů 2:47–3:36. Pro ženy a rychlejší "
                    "nebo pomalejší časy platí jen orientačně."}


TEST_WEEKS_OUT = 7          # the control test 6–8 weeks before the race (#13)
HEAT_FROM, HEAT_TO = 21, 8  # #16: heat acclimation from day 21 to day 8 before a hot race
HEAT_SOURCES = ["tyler-et-al-2016", "daanen-et-al-2017", "racinais-et-al-2015"]
FUEL_WEEKS = 8              # #15: from 8 weeks out, long runs over 90 min train the intake
FUEL_MIN = 90
FUEL_G = (60, 90)           # g of carbohydrate an hour: 60, rising to 90 for an ultra


# owner request 2026-10-13: when the goal isn't safe by its date, the best goal that is — the largest
# one of the same kind the safe path reaches with the taper and the reserve: at the edge of what the
# runner's limits allow, and only when it still moves them on (a requirement above today's level)
ROAD_STEPS = (5.0, 10.0, 15.0, 21.1, 30.0, 42.2)
TRAIL_STEPS = (5, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100, 110, 120, 140, 160)
FREE_STEPS = tuple(k / 20 for k in range(19, 5, -1))          # 95 % … 30 % of each number
PROGRESS = (("week", "týdenní objem z {} na {} km"), ("long", "nejdelší běh z {} na {} km"),
            ("ascentWeek", "stoupání za týden z {} na {} m"), ("ascentRun", "stoupání v jednom běhu z {} na {} m"))


def _r50(v: float) -> int:
    return int(round(v / 50.0) * 50)


def _th(v: float) -> str:
    """A whole number with a thousands space, as the app shows it (1 350)."""
    return f"{int(round(v)):,}".replace(",", "\u00a0")


def _best_label(g: dict) -> str:
    if g.get("kind") == "free":
        f = g.get("free") or {}
        parts = ([f"týdně {_cz(f['weeklyKm'], 0)} km"] if f.get("weeklyKm") else []) \
            + ([f"dlouhý běh {_cz(f['longKm'], 0)} km"] if f.get("longKm") else []) \
            + ([f"převýšení {_th(f['climbM'])} m " + ("za týden" if f.get("climbScope", "week") == "week" else "v jednom běhu")]
               if f.get("climbM") else [])
        return " · ".join(parts)
    if is_trail(g):
        return f"trail {_cz(g['km'], 0)} km · ↑ {_th(g.get('ascentM') or 0)} m"
    return goal_name(g)


def _free_edge(goal: dict, res: dict) -> dict | None:
    """A free goal at the edge: each number as far as the safe path gets it with the reserve
    before the date (never above what was asked), floored to whole km / 50 m."""
    rows, weeks = (res.get("safe") or {}).get("rows") or [], res.get("weeksToGoal") or 0
    cut = rows[:max(0, weeks - (res.get("reserveWeeks") or 2))]
    if not cut:
        return None
    f0 = goal.get("free") or {}
    top = lambda k: max((r.get(k) or 0) for r in cut)
    fr = dict(f0)
    if f0.get("weeklyKm"):
        fr["weeklyKm"] = int(min(f0["weeklyKm"], top("km")))
    if f0.get("longKm"):
        fr["longKm"] = int(min(f0["longKm"], top("long")))
    if f0.get("climbM"):
        k = "Run" if f0.get("climbScope") == "run" else ""
        fr["climbM"] = int(min(f0["climbM"], min(top("ascent" + k), top("descent" + k))) // 50 * 50)
    return dict(goal, free=fr)


def best_safe(goal: dict, st: dict, res: dict | None = None) -> dict | None:
    """The largest goal of the same kind (road distances, a trail scaled with its climb per km, or
    the free goal's numbers where the safe path gets them) whose verdict is "ok" by the same date,
    with the original aim, else to finish; None when none is, or when it wouldn't move the runner
    on. Binary search over the candidates, largest first (the verdict only gets better as they shrink)."""
    if goal.get("kind") == "free":
        edge = _free_edge(goal, res or evaluate(goal, st, alternatives=False))
        f0 = goal.get("free") or {}
        cands = [
            dict(goal, free={**f0, **({"weeklyKm": round(f0["weeklyKm"] * k)} if f0.get("weeklyKm") else {}),
                             **({"longKm": round(f0["longKm"] * k)} if f0.get("longKm") else {}),
                             **({"climbM": _r50(f0["climbM"] * k)} if f0.get("climbM") else {})})
            for k in FREE_STEPS]
        aims = [goal.get("aim")]
    else:
        km = goal.get("km") or 0
        if is_trail(goal):
            up = goal.get("ascentM") or 0
            down = goal["descentM"] if goal.get("descentM") is not None else up
            cands = [dict(goal, km=float(d), ascentM=_r50(up * d / km), descentM=_r50(down * d / km), terrain="trail")
                     for d in reversed(TRAIL_STEPS) if d < km - 0.5]
        else:
            cands = [dict(goal, km=d, ascentM=None, descentM=None) for d in reversed(ROAD_STEPS) if d < km - 0.5]
        cands = [dict(c, raceId=None, name=None, targetTimeS=None) for c in cands]
        aims = [goal.get("aim"), "finish"] if goal.get("aim") == "time" else [goal.get("aim")]
    for aim in aims:
        lo, hi, best = 0, len(cands) - 1, None
        if goal.get("kind") == "free" and edge:           # the free goal's edge first, the scaled ones if it fails
            r = evaluate(edge, st, alternatives=False)
            if r["verdict"] == "ok":
                best, hi = (edge, r), -1
        while lo <= hi:
            mid = (lo + hi) // 2
            g = dict(cands[mid], aim=aim)
            r = evaluate(g, st, alternatives=False)
            if r["verdict"] == "ok":
                best, hi = (g, r), mid - 1
            else:
                lo = mid + 1
        if best:
            g, r = best
            up = [(k, q) for k, q in ((q["key"], q) for q in r["requirements"]) if q.get("now") is not None
                  and q["unit"] != "×" and q["need"] > (q["now"] or 0) + (0.5 if q["unit"] == "km" else 25)]
            if not up:
                return None
            prog = [t.format(_cz(dict(up)[k]["now"], 0), _cz(dict(up)[k]["need"], 0)) for k, t in PROGRESS if k in dict(up)][:2]
            if g.get("kind") == "free":                     # the label shows what the goal really asks (the long run sets the week)
                need = {q["key"]: q["need"] for q in r["requirements"]}
                f = g.get("free") or {}
                g = dict(g, free={**f, **({"weeklyKm": int(round(need["week"]))} if need.get("week") else {})})
            return {"kind": "best", "goal": g, "verdict": r["verdict"], "verdictLabel": r["verdictLabel"],
                    "label": _best_label(g), "readyDate": r.get("readyDate"),
                    "progress": [{"key": k, "label": LABEL[k], "now": q["now"], "need": q["need"], "unit": q["unit"]}
                                 for k, q in up if k in ("week", "long", "ascentWeek", "ascentRun", "descentWeek", "descentRun")][:3],
                    "chance": r.get("chance"),
                    "text": f"Nejlepší cíl, který do {_dcz(_d(goal['date']))} stihnete bezpečně (šance {r.get('chance')} %): {_best_label(g)}"
                            + (" · doběhnout" if aim != goal.get("aim") else "") + ". "
                            + (f"Je na hraně vašich limitů a posune vás: {' · '.join(prog)}." if prog else
                               "Je na hraně vašich limitů a posune vás dál.")}
    return None


def _alternatives(goal: dict, st: dict, res: dict, risk: dict, taper: int, weeks: int) -> list:
    alts = []
    if res.get("verdict") != "ok":
        b = best_safe(goal, st, res)
        if b:
            alts.append(b)
    if res.get("realDate"):
        alts.append({"kind": "later", "date": res["realDate"],
                     "text": f"Posunout termín na {_dcz(_d(res['realDate']))} nebo později, nebo plánovaný závod běžet jako trénink."})
    if goal.get("kind") != "free" and goal.get("aim") == "time":
        g2 = dict(goal, aim="finish")
        r2 = evaluate(g2, st, alternatives=False)
        alts.append({"kind": "finish", "goal": g2, "verdict": r2["verdict"], "verdictLabel": r2["verdictLabel"],
                     "text": f"Cíl doběhnout místo cílového času: {r2['verdictLabel'].lower()}."})
    if goal.get("kind") != "free" and not is_trail(goal):
        km = goal.get("km") or 0
        shorter = next((d for d in (21.1, 10.0, 5.0) if d < km - 0.5), None)
        if shorter:
            g3 = dict(goal, km=shorter, ascentM=None, descentM=None)
            r3 = evaluate(g3, st, alternatives=False)
            name = {21.1: "půlmaraton", 10.0: "10 km", 5.0: "5 km"}[shorter]
            alts.append({"kind": "shorter", "goal": g3, "verdict": r3["verdict"], "verdictLabel": r3["verdictLabel"],
                         "text": f"Kratší trať ve stejném termínu ({name}): {r3['verdictLabel'].lower()}."})
    if goal.get("kind") != "free" and is_trail(goal):
        alts.append({"kind": "walk", "text": "Na trailu počítat se střídáním běhu a chůze v kopcích a cíl brát jako doběhnutí."})
    rr = risk.get("readyWeek")
    if res.get("riskPossible"):
        alts.append({"kind": "risk", "readyWeek": rr, "sources": SRC["risk"],
                     "text": f"Riziková cesta (jen s výslovným souhlasem, zvolíte ji po uložení v detailu cíle): připraveni za {_weeks_cz(rr)}. "
                             "Týden by rostl až o 20 % a dlouhý běh o 15 %. Při nárůstu týdne o 20–60 % se během 3 týdnů "
                             "zranilo o 23 procentních bodů víc běžců."})
    else:
        alts.append({"kind": "risk", "readyWeek": rr, "possible": False,
                     "text": "Ani riziková cesta by termín nestihla, takže ji aplikace nenabídne."})
    return alts


def _hms(sec: float) -> str:
    sec = int(round(sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def target_time(goal: dict, predicted_s: float | None, basis: dict | None) -> dict | None:
    """Stage 4 — a target time: the race pace it means and how far today's form is from it (the
    best run of 120 days carried to the race by Riegel's formula, race_plan.py). Today's form, not
    the form on race day: the gap is what the plan has to close."""
    t, km = goal.get("targetTimeS"), goal.get("km")
    if goal.get("aim") != "time" or not t or not km:
        return None
    pace = t / km
    out = {"targetS": t, "pace": round(pace), "paceText": f"{_hms(pace)} /km", "timeText": _hms(t)}
    lines = [f"Cílový čas {_hms(t)} znamená průměrné tempo {_hms(pace)} /km."]
    if predicted_s:
        gap = (predicted_s - t) / t
        out.update(predictedS=round(predicted_s), predictedText=_hms(predicted_s), gapPct=round(gap * 100, 1))
        if gap <= 0.01:
            lines.append(f"Podle dnešní formy je cíl v dosahu: odhad {_hms(predicted_s)}.")
        else:
            lines.append(f"Podle dnešní formy odhad {_hms(predicted_s)}, o {_cz(gap * 100, 0)} % pomaleji.")
            lines.append("Takový rozdíl může příprava překlenout." if gap <= 0.06 else "Cíl je ambiciózní, zvažte i cíl doběhnout.")
        if basis:
            out["basis"] = basis
    lines.append("Ve specifické fázi patří do dlouhých běhů úseky v cílovém tempu, ostatní běhy zůstávají lehké.")
    out["text"] = " ".join(lines)
    return out


PHASE = {"base": "Základ", "build": "Rozvoj", "specific": "Specifická příprava", "taper": "Ladění"}


def goal_name(goal: dict) -> str:
    if goal.get("kind") == "free":
        return "vlastní cíl"
    km = goal.get("km") or 0
    return "maraton" if abs(km - 42.2) < 0.3 else "půlmaraton" if abs(km - 21.1) < 0.3 else f"závod {_cz(km, 1 if km % 1 else 0)} km"


def goal_dict(g, race=None) -> dict:
    """The stored goal row as the dict evaluate() takes."""
    return {"id": g.id, "kind": g.kind, "raceId": g.race_id, "name": g.name or (race.name if race else None),
            "date": (g.date or "")[:10], "km": g.distance_km, "ascentM": g.ascent_m, "descentM": g.descent_m,
            "terrain": g.terrain, "aim": g.aim or "finish", "targetTimeS": g.target_time_s, "free": g.free_json or {},
            "path": g.path or "safe", "riskConsentAt": g.risk_consent_at, "hot": bool(getattr(g, "hot", False)),
            "riskEndedAt": getattr(g, "risk_ended_at", None), "riskEndReason": getattr(g, "risk_end_reason", None)}


def risk_end_reason(a: dict) -> str | None:
    """Stage 3 — the daily watch of the risk path: running pain from 3/10, a stop (injury, red
    flag), an illness day, or readiness under 65 % two mornings in a row send the plan back to
    the safe path (owner decision 2026-10-12). None = the risk path may go on."""
    g = (a or {}).get("guidance") or {}
    if g.get("override"):
        return g["override"].get("title") or "omezení tréninku"
    if (g.get("pain") or 0) >= 3:
        return f"bolest {g['pain']}/10"
    x = g.get("planCtx") or {}
    if x.get("ill") or x.get("illLight"):
        return "nemoc"
    rd = ((a or {}).get("capacity") or {}).get("readiness") or {}
    y = rd.get("yesterday") or {}
    if rd.get("known") and y.get("known") and (rd.get("score") or 100) < 65 and (y.get("score") or 100) < 65:
        return "připravenost pod 65 % dva dny po sobě"
    return None
