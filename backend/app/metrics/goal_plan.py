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
         4-week average and 0.9 × the best of the 6 weeks before, decayed after a break);
         the long run ≤ the longest of 30 days + the per-run margin (10 %) and ≤ 50 % of the
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
from datetime import date, timedelta

from . import capacity as C
from . import data as D
from . import engine as E
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
HIST_WEEKS = 6

SRC = {
    "week10": ["abrahamson-et-al-2024"],
    "week21": ["fokkema-et-al-2020", "mohseni-et-al-2019"],
    "week42": ["fokkema-et-al-2020", "mohseni-et-al-2019", "rasmussen-et-al-2013", "doherty-et-al-2019"],
    "long": ["fokkema-et-al-2020", "toresdahl-et-al-2021", "yamaguchi-et-al-2022"],
    "count": ["doherty-et-al-2019", "toresdahl-et-al-2021"],
    "trail": ["soppelsa-et-al-2025"],
    "ultra": ["hoffman-and-krishnan-2014", "jaen-carrillo-et-al-2024", "knechtle-et-al-2011"],
    "descent": ["marqueste-et-al-2008", "bontemps-et-al-2025", "mchugh-2003"],
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
    if lg and out.get("week") and lg / LONG_SHARE > out["week"]["need"]:
        out["week"]["base"] = out["week"]["need"]
        out["week"]["need"] = lg / LONG_SHARE
        out["week"]["why"] += f" · aby dlouhý běh {_cz(lg)} km byl nejvýš 50 % týdne"
    elif lg and not out.get("week"):
        out["week"] = {"need": lg / LONG_SHARE, "why": f"aby dlouhý běh {_cz(lg)} km byl nejvýš 50 % týdne",
                       "sources": [], "derived": True}
    return out


# ------------------------------------------------------------------ the runner today
def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def runner_state(db, rid: str, a: dict | None = None, today: date | None = None, cycle_pos: int | None = None) -> dict:
    """Weekly history (6 completed calendar weeks before this Monday, oldest first) of km, the
    longest run, the descent and ascent sums and per-run maxima, the longest run of the 30 days
    before this Monday (so the plan stays the same all week), the margins the capacity model
    uses for this runner, the place of this week in the 4-week cycle, the race experience and
    today's limits. Week 1 of the projection is this calendar week."""
    today = today or E.today_date()
    mon = _monday(today)
    lo = mon - timedelta(days=7 * HIST_WEEKS)
    runs = E.acts(db, rid, "load")
    wk = [{"km": 0.0, "long": 0.0, "down": 0.0, "up": 0.0, "downRun": 0.0, "upRun": 0.0, "runs": 0}
          for _ in range(HIST_WEEKS)]
    l30, d30, u30, ever_long, ever_half = 0.0, 0.0, 0.0, 0.0, False
    for x in runs:
        try:
            dd = _d(x.started_at)
        except ValueError:
            continue
        km, down, up = x.distance_km or 0.0, x.descent_m or 0.0, x.ascent_m or 0.0
        ever_long = max(ever_long, km)
        if km >= 20.5:
            ever_half = True
        if 0 < (mon - dd).days <= 30:
            l30, d30, u30 = max(l30, km), max(d30, down), max(u30, up)
        if lo <= dd < mon:
            w = wk[(dd - lo).days // 7]
            w["km"] += km
            w["down"] += down
            w["up"] += up
            w["long"] = max(w["long"], km)
            w["downRun"] = max(w["downRun"], down)
            w["upRun"] = max(w["upRun"], up)
            w["runs"] += 1
    races = D.of(db, rid).races
    past = [x for x in races if x.date and x.date[:10] < today.isoformat() and x.distance_km]
    if any((x.distance_km or 0) >= 21.0 for x in past):
        ever_half = True
    m = ((a or {}).get("capacity") or {}).get("margins") or {}
    g = (a or {}).get("guidance") or {}
    if cycle_pos is None:
        cycle_pos = (((g.get("week") or {}).get("cycle") or {}).get("autoPos"))
    return {
        "today": today.isoformat(), "start": mon.isoformat(), "weeks": wk, "cyclePos": cycle_pos,
        "long30": l30, "down30": d30, "up30": u30,
        "marginWeek": float(m.get("runWeek") or C.MARGIN_WEEK), "marginRun": float(m.get("runSession") or C.MARGIN_SESSION),
        "experience": m.get("experience"), "everHalf": ever_half,
        "marginWhy": [t for t, on in (("první rok běhání", m.get("experience")), ("dřívější zranění", (m.get("frailty") or 1.0) > 1.0),
                                      ("návrat po pauze", m.get("underconditioned")),
                                      ("přechod na nové boty", ((((a or {}).get("capacity") or {}).get("shoes") or {}).get("factor") or 1.0) < 1.0))
                      if on],
        "everMarathon": ever_long >= 40.0 or any((x.distance_km or 0) >= 40.0 for x in past),
        "limited": g.get("override") or (g.get("mode") == "return"),
    }


# ------------------------------------------------------------------ projection
def _cap(hist: list, planned: list | None = None) -> float:
    """capacity.weekly_capacity on calendar weeks: max(average of the last 4 weeks, 0.9 ×
    the best of the last 6, decayed beyond its 2nd week, a spike over 1.3 × its 4 weeks
    before left out). `planned` marks the projection's own recovery weeks: a planned recovery
    week is not a loss of capacity, so the average is taken over the last 4 loaded weeks —
    with it in the average a narrowed weekly margin (under ~11 %) made the projection shrink
    week after week (owner report 2026-10-12: a trail goal "not within 2 years")."""
    planned = planned or [False] * len(hist)
    loaded = [w for w, p in zip(hist, planned) if not p]
    chronic = sum(loaded[-4:]) / 4 if len(loaded) >= 4 else sum(hist[-4:]) / 4
    best = 0.0
    n = len(hist)
    for k in range(1, 7):
        if n - k < 0:
            break
        w = hist[n - k]
        if planned[n - k]:
            continue
        prior = hist[max(0, n - k - 4):n - k]
        if len(prior) >= 2:
            before = sum(prior) / len(prior)
            if before > 0 and w > C.JUMP_RATIO * before:
                continue
        best = max(best, w * C.BREAK_DECAY ** max(0, k - 2))
    return max(chronic, 0.9 * best)


def deload_week(n: int, st: dict) -> bool:
    """Week n (1 = this calendar week) is a recovery week: the app's 4-week cycle goes on from
    the place this week has in it (guidance.cycle_position), else every 4th week."""
    pos0 = st.get("cyclePos") or 1
    return (pos0 - 1 + n - 1) % 4 == 3


def _channel(hist_w: list, run0: float, need_w: float | None, need_run: float | None, path: dict,
             st: dict, floor_w: float = 0.0, floor_run: float = 0.0, share_from: int = 1):
    """One channel week by week: (weekly totals, per-run maxima), each list from week 1. The
    long run (volume, floor_run == 0) is at most LONG_SHARE of the week from `share_from` (the
    specific phase), LONG_SHARE_BASE before it."""
    mw = st["marginWeek"] * path.get("weekX", 1.0)
    mr = st["marginRun"] * path.get("runX", 1.0)
    hist = [max(v, 0.0) for v in hist_w]
    planned = [False] * len(hist)
    runs = [run0] * 4
    out_w, out_r = [], []
    for n in range(1, HORIZON + 1):
        last = hist[-1]
        avg4 = sum(hist[-4:]) / 4
        share = LONG_SHARE if n >= share_from else LONG_SHARE_BASE
        if deload_week(n, st):
            w = last * path["deload"]
            r = min(runs[-1], max(w * (share if floor_run == 0.0 else 1.0), 0.0)) if need_run is not None else 0.0
        else:
            ceil = max(_cap(hist, planned) * (1 + mw), floor_w)
            ref = max(max(hist[-2:]), floor_w)        # after a recovery week the rise counts from the week before it
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
        hist.append(w)
        planned.append(deload_week(n, st))
        runs.append(r)
        out_w.append(w)
        out_r.append(r)
    return out_w, out_r


def project(req: dict, st: dict, path: dict, share_from: int = 1, until: int = 0) -> dict:
    """Week rows (1 = this calendar week) and the first week every requirement is met (None if
    not within HORIZON). Rows are kept up to max(until, ready + 2)."""
    wk = st["weeks"]
    need_w = (req.get("week") or {}).get("need")
    need_l = (req.get("long") or {}).get("need")
    km_w, long_r = _channel([w["km"] for w in wk], max(st["long30"], max(w["long"] for w in wk)),
                            need_w, need_l if need_l else 0.0, path, st, share_from=share_from)
    rows = [{"km": km_w[i], "long": long_r[i], "deload": deload_week(i + 1, st)} for i in range(HORIZON)]
    for ch, key in (("descent", "down"), ("ascent", "up")):
        nw = (req.get(ch + "Week") or {}).get("need")
        nr = (req.get(ch + "Run") or {}).get("need")
        if nw is None and nr is None:
            continue
        spec = C.CHANNELS[ch]
        vw, vr = _channel([w[key] for w in wk], max(st[key + "30"], max(w[key + "Run"] for w in wk)),
                          nw, nr if nr is not None else (nw or 0) * TRAIL_RUN_CLIMB, path, st,
                          floor_w=spec["floor_w"], floor_run=spec["floor_s"])
        for i, row in enumerate(rows):
            row[ch], row[ch + "Run"] = vw[i], vr[i]
    count_thr = (req.get("longCount") or {}).get("km")
    desc_min = max(DESC_SESSION_MIN, DESC_SESSION_SHARE * ((req.get("descentRun") or {}).get("need") or 0))
    n_long = n_desc = 0
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
    k = p0["firstMet"].get("long") or p0["readyWeek"] or build
    spec = min(build, max(SPECIFIC_MIN, k + SPECIFIC_SLACK))
    start = max(1, build - spec + 1)
    if start == 1:
        return p0
    p1 = project(req, st, path, start, until=weeks)
    if p1["readyWeek"] is None or (p0["readyWeek"] and p0["readyWeek"] <= build < p1["readyWeek"]):
        return p0
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
    tf = taper_factors(goal)
    build = max(0, weeks - len(tf))
    rows = proj["rows"]
    req = requirements(goal)
    spec_from = proj.get("shareFrom") or 1
    if spec_from == 1:
        spec_from = max(1, build - max(SPECIFIC_MIN, (proj["firstMet"].get("long") or build) + SPECIFIC_SLACK) + 1)
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
        out.append(w)
    return out


# ------------------------------------------------------------------ the verdict
LABEL = {"week": "Týdenní objem ve vrcholu", "long": "Nejdelší běh", "longCount": "Počet dlouhých běhů",
         "ascentWeek": "Stoupání za týden", "ascentRun": "Stoupání v jednom běhu",
         "descentWeek": "Klesání za týden", "descentRun": "Klesání v jednom běhu", "descSessions": "Seběhy"}
UNIT = {"week": "km", "long": "km", "longCount": "×", "ascentWeek": "m", "ascentRun": "m", "descentWeek": "m",
        "descentRun": "m", "descSessions": "×"}


def _now(k: str, st: dict) -> float | None:
    wk = st["weeks"]
    if k == "week":
        return max(w["km"] for w in wk[-4:])
    if k == "long":
        return st["long30"]
    if k in ("ascentWeek", "descentWeek"):
        return max(w["up" if k.startswith("a") else "down"] for w in wk[-4:])
    if k in ("ascentRun", "descentRun"):
        return st["up30" if k.startswith("a") else "down30"]
    return 0


def _weeks_to(goal_date: date, start: date) -> int:
    """Calendar weeks from `start` (a Monday) up to and including the goal's week."""
    return (goal_date - start).days // 7 + 1


def _fit(ready, taper, weeks) -> str:
    if ready is None:
        return "no"
    reserve = 3 if ready + taper > RESERVE_LONG_PLAN else 2
    if ready + taper + reserve <= weeks:
        return "ok"
    return "tight" if ready + taper <= weeks else "no"


def evaluate(goal: dict, st: dict, alternatives: bool = True) -> dict:
    """The whole feasibility answer for one goal."""
    start = _d(st["start"])
    gdate = _d(goal["date"])
    weeks = _weeks_to(gdate, start)
    taper = taper_weeks(goal)
    req = requirements(goal)
    known = sum(1 for w in st["weeks"] if w["runs"]) >= 3
    out = {"goal": goal, "start": st["start"], "weeksToGoal": weeks, "taperWeeks": taper,
           "requirements": [], "notes": [], "sources": sorted({s for r in req.values() for s in r.get("sources", [])})}
    for k, r in req.items():
        out["requirements"].append({"key": k, "label": LABEL[k], "unit": UNIT[k], "need": _r(r["need"]),
                                    "base": _r(r.get("base")), "km": r.get("km"), "now": _r(_now(k, st)),
                                    "why": r["why"], "sources": r.get("sources", []), "assumption": bool(r.get("assumption"))})
    if not req:
        out.update(verdict="unknown", verdictLabel=VERDICT["unknown"], text="Cíl zatím nemá žádný požadavek. Zadejte aspoň jedno číslo.")
        return out
    if not known:
        out.update(verdict="unknown", verdictLabel=VERDICT["unknown"],
                   text="Na projekci potřebuji aspoň 3 z posledních 6 týdnů s běháním z hodinek. Zatím aplikace neví, z čeho by kapacita rostla.")
        return out
    # the last 4 completed weeks in the projection's channels (the chart's history)
    out["history"] = [{"km": _r(w["km"]), "long": _r(w["long"]), "ascent": _r(w["up"]), "descent": _r(w["down"]),
                       "ascentRun": _r(w["upRun"]), "descentRun": _r(w["downRun"])} for w in st["weeks"][-4:]]
    safe = phased(req, st, SAFE, weeks, taper)
    risk = phased(req, st, RISK, weeks, taper)
    v = _fit(safe["readyWeek"], taper, weeks)
    rr = risk["readyWeek"]
    out["riskPossible"] = bool(rr and rr + taper <= weeks)
    path = "risk" if goal.get("path") == "risk" else "safe"
    chosen = risk if path == "risk" else safe
    pv = v if path == "safe" else ("tight" if out["riskPossible"] else "no")
    out.update(path=path, status=pv, statusLabel=STATUS[pv])
    if weeks <= HORIZON:
        out["plan"] = plan_weeks(goal, st, chosen, weeks)
    reserve = 3 if (safe["readyWeek"] or 0) + taper > RESERVE_LONG_PLAN else 2
    out.update(safe=safe, risk=risk, reserveWeeks=reserve, verdict=v, verdictLabel=VERDICT[v])
    if safe["readyWeek"]:
        real = start + timedelta(days=7 * (safe["readyWeek"] + taper + reserve) - 1)
        out["realDate"] = real.isoformat()
        out["readyDate"] = (start + timedelta(days=7 * safe["readyWeek"] - 1)).isoformat()
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
    if v == "ok":
        n = _weeks_cz(safe["readyWeek"])
        out["text"] = (f"Do {gd} to stihnete bezpečně i s rezervou {reserve} týdnů na nemoc a horší týdny. "
                       + (f"Připraveni budete zhruba za {n}, pak {_weeks_cz(taper)} ladění." if taper
                          else f"Připraveni budete zhruba za {n}."))
    elif v == "tight":
        out["text"] = (f"Do {gd} to stihnete jen bez výpadku: připraveni budete za {_weeks_cz(safe['readyWeek'])} z {weeks}, "
                       f"rezerva na nemoc a horší týdny chybí." + bn_s)
    else:
        out["text"] = (f"Do {gd} to bezpečně nestihnete." + bn_s
                       + (f" Reálný termín je od {_dcz(_d(out['realDate']))}." if out.get("realDate") else ""))
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
    if st.get("limited"):
        out["notes"].append({"key": "limited", "text": "Teď máte omezení tréninku (bolest, zranění nebo návrat po něm). Projekce počítá "
                             "s tím, že trénink půjde bez přerušení, takže skutečný termín bude nejspíš později.", "sources": []})
    if st["marginWeek"] < C.MARGIN_WEEK - 0.001:
        why = st.get("marginWhy") or []
        out["notes"].append({"key": "margin", "sources": [],
                             "text": f"Týdenní rezerva je u vás teď {_cz(st['marginWeek'] * 100)} % místo 15 %"
                                     + (f" ({' · '.join(why)})" if why else "") + ", proto kapacita v projekci roste pomaleji."})
    if alternatives and v != "ok":
        out["alternatives"] = _alternatives(goal, st, out, risk, taper, weeks)
    return out


def _alternatives(goal: dict, st: dict, res: dict, risk: dict, taper: int, weeks: int) -> list:
    alts = []
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
                     "text": f"Riziková cesta (přijde v další etapě, jen s výslovným souhlasem): připraveni za {_weeks_cz(rr)}. "
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
            "path": g.path or "safe", "riskConsentAt": g.risk_consent_at,
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
