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
       alert tier, or silent drift together with symptoms → triage physio_48h /
       physio_7d; a mechanics drift alone never refers, v0.9.0) → volno +
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
  3. Today's allowance = the tightest of: what's left of this week's target (the
     calendar week from Monday), the room under the weekly ceiling of the last days'
     absorbed load (owner request 2026-10-06: every earlier day counts with what is
     still unabsorbed of it, the same load and ceiling as the weekly score — not a plain
     7-day sum that drops a long run all at once on day 8), the per-run ceiling
     (capacity.ceilingToday, scaled by today's readiness) and what's left of the
     overall load (Celková zátěž = HR × time, all sports) turned into km / Z4+
     minutes. `limitedBy` names the binding one. With the week's target met but
     the 7-day ceiling open, a short easy run stays available (not recommended).
  4. Session type by default from the runner's own pattern (usual run days,
     long-run weekday, hard days over the last 8 weeks); a quality session only
     ≥ 48 h after the last hard one, readiness ≥ READY_QUALITY (65 %), intensity budget left,
     no pain ≥ 3, Zátěž < 25 and no mechanics drift. The runner can switch type;
     every type carries its own limits and, if not advisable today, why.
Recomputed on every live recompute (sync, check-in, run rating); provisional
until today's sleep / HRV has arrived.
"""
from datetime import date, timedelta

from . import capacity as C
from . import data as D
from . import engine as E
from . import outlook as O
from . import speed as SP
from . import weather as W

TYPES = ("volno", "regenerace", "lehký", "dlouhý", "kvalitní")
TYPE_LABEL = {"volno": "Volno", "regenerace": "Regenerační běh", "lehký": "Lehký běh",
              "dlouhý": "Dlouhý běh", "kvalitní": "Kvalitní trénink", "závod": "Den závodu",
              "kolo": "Kolo", "voda": "Plavání", "posilování": "Posilování"}
CROSS_TYPES = ("kolo", "voda", "posilování")
# Cross-training (see engine.py "cross-training" and the design doc):
#  • kolo — physiological load without running impact (Vanrenterghem et al., 2017), dosed from
#    what's left of the overall load at Z2 of the cycling HR max (Millet et al., 2009);
#  • voda — swimming when pain or mechanics limit running (railway#118: only swimming is offered,
#    a deep-water running pool is rarely available; deep-water running kept VO2max over 6 weeks,
#    Wilber et al., 1996);
#  • posilování — 2 sessions a week (Blagrove et al., 2018: 2–3, two likely enough), 1 in the
#    race phase, ≥ 24 h before an intensive run (Blagrove 2018); a heavy lower-body session
#    blunts intensive running for 24–48 h (Doma et al., 2017) → lower Z4+ caps, no quality.
CYCLE_Z2 = (0.60, 0.70)          # HRR band for an easy ride
CROSS_MIN, KOLO_MAX, VODA_MAX = 20, 90, 45
EXTRA_RIDE_MAX = 60     # the optional ride over a met weekly target stays shorter (working assumption)
STRENGTH_TARGET, STRENGTH_TARGET_RACE = 2, 1
STRENGTH_CARRY = {0: 0.5, 1: 0.5, 2: 0.75}   # Z4+ cap factor by days since a heavy lower-body session (working assumption)
WD = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
WD_IN = ("v pondělí", "v úterý", "ve středu", "ve čtvrtek", "v pátek", "v sobotu", "v neděli")
HARD_Z4_MIN = 10        # a run with ≥ 10 min in Z4+ counts as a hard session
# v0.8.4 — heart rate lags behind short intervals, so time in zone under-counts
# them (Seiler 2010, "session goal approach"): a run rated RPE ≥ 7 that is no
# longer than 75 min counts as hard as well (a long run rated 7 doesn't).
HARD_RPE, HARD_RPE_MAX_MIN = 7, 75
# v0.12.0 — ≥ 20 min of threshold work (0.90–1.00 × critical speed) delays cardiac
# autonomic recovery by 24–48 h like a hard session (Stanley et al., 2013), so it counts
# as one for the spacing of hard days (speed.py)
HARD_THR_MIN = 20
# At most 2–3 hard sessions a week within a hard-day / easy-day pattern (Seiler
# 2010, Casado et al. 2022); 2 for runners with ≤ 4 runs a week (working assumption).
HARD_CAP_FEW, HARD_CAP = 2, 3
# Heat (Périard et al. 2015, Racinais et al. 2015): most adaptation within ~1–2
# weeks of repeated exercise in the heat. Fewer than 5 hot runs in 14 days =
# not yet acclimatised (working assumption) → intensity cap ×0.8.
HEAT_ACCLIM_RUNS, HEAT_ACCLIM_FULL, HEAT_INT_FACTOR = 5, 10, 0.8
# Strength (Lauersen et al. 2014; Rønnestad & Mujika 2014): a nudge after 3 weeks
# without it; the first 2 weeks of a new block (none in the 4 weeks before) easy
# running ×0.9 (working assumption).
STRENGTH_GAP_DAYS, STRENGTH_NEW_BLOCK_DAYS = 21, 14
HARD_GAP_DAYS = 2       # ≥ 48 h between hard sessions
READY_QUALITY = 65      # readiness score (%) needed for a quality / long session
READY_EASY_ONLY = 45    # below this readiness score the default is a regeneration run
READY_EXTRA_EASY = 80   # the optional easy run after the week's target needs a well-recovered day
DRIFT_CUT = {"volume": 0.8, "intensity": 0.5, "descent": 0.5}   # mechanics above threshold → less today
LONG_SHARE = 0.30       # a long run ≤ 30 % of the weekly volume budget
Z4_SESSION_MAX = 45     # a quality session's hard minutes are capped here whatever the capacity says
MIN_RUN_KM = 2.0        # below this there's no meaningful run left today → volno
NOVICE_DAYS = 42        # plan C1: the first 6 weeks of data run on generic rules…
# v0.9.0: the 10 % steps are the app's own cautious rule, not an evidence-based threshold —
# the 10 % rule did not prevent injuries in novices (Buist et al., 2008) and no universal
# progression rule is supported (Fredette et al., 2022); the text says so to the runner.
NOVICE_STEP = 1.10      # …weekly volume ≤ +10 % on the last completed week (Nielsen 2014: > 30 % clearly risky)…
NOVICE_LONG = 1.10      # …a long run ≤ 10 % over the longest run of the last 30 days (RUNSAFE)…
NOVICE_Z4 = 10          # …and a generic 10 min of hard work in a quality session while intensity capacity is unknown
# heart-rate-reserve bands per session type (Karvonen)
HRR = {"regenerace": (0.50, 0.65), "lehký": (0.60, 0.72), "dlouhý": (0.60, 0.75), "kvalitní": (0.80, 0.92)}
PACE_FALLBACK = {"regenerace": (1.06, 1.15), "lehký": (0.97, 1.05), "dlouhý": (1.00, 1.08)}
DIST_DAYS = 84        # feedback railway#43: window for the rolling 7-day percentiles
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


def z4_trimp_per_min(b: float = E.TRIMP_B_DEFAULT) -> float:
    """Banister TRIMP of a minute at 85 % HRR (b = the runner's sex coefficient)."""
    return E._trimp(1.0, 85.0, 100.0, 0.0, b)


Z4_TRIMP_PER_MIN = z4_trimp_per_min()


def _d(s):
    return date.fromisoformat(s[:10])


def _r(v, dec=1):
    return None if v is None else (round(v, dec) if dec else round(v))


def _dm(iso: str) -> str:
    """'2026-09-25' → '25. 9.'"""
    d = _d(iso)
    return f"{d.day}. {d.month}."


def _cz(v, dec=1):
    """A number for a Czech sentence (decimal comma)."""
    return "—" if v is None else f"{round(v, dec):.{dec}f}".replace(".", ",") if dec else str(round(v))


def sys_txt(w: dict, gscore=None) -> str:
    """Why Celková zátěž leaves nothing more today — its weekly TARGET (the plan) or the
    safety room under the weekly ceiling (owner feedback 2026-10-10: a met plan read as
    "na stropu")."""
    if w.get("bound") == "plan":
        room = w.get("safeMax")
        return (f"Týdenní cíl celkové zátěže je splněný (od pondělí {_cz(w.get('done'), 0)} z {_cz(w.get('budget'), 0)} bodů)"
                + (f" — do bezpečnostního stropu zbývá {_cz(room, 0)} bodů" if room else "")
                + (f", navíc nad cíl ale jen při připravenosti aspoň {READY_EXTRA_EASY} %." if (room and gscore is not None
                                                                                          and gscore < READY_EXTRA_EASY) else "."))
    return "Nevstřebaná celková zátěž (tep × čas ze všech aktivit) je na stropu týdenní kapacity."


def _ill_what(sig) -> str:
    """"<what> <when>" — two parts, each its own dictionary entry for the English UI."""
    k = sig.get("kinds") or []
    two = sig["since"] != sig["nights"][-1]["d"]
    what = ("zvýšený klidový tep i dech" if len(k) == 2 else "zvýšený klidový tep" if k == ["rhr"]
            else "zvýšenou dechovou frekvenci ve spánku")
    return what, ("dvě noci po sobě" if two else "v noci")


def is_hard(s) -> bool:
    """A hard session: ≥ HARD_Z4_MIN min in Z4+, ≥ HARD_THR_MIN min of threshold work
    just below critical speed (v0.12.0), or rated RPE ≥ 7 when not a long run."""
    if (s["exp"].get("intensity") or 0) >= HARD_Z4_MIN:
        return True
    if (s.get("thrMin") or 0) >= HARD_THR_MIN:
        return True
    return (s.get("rpe") or 0) >= HARD_RPE and 0 < (s.get("durationMin") or 999) <= HARD_RPE_MAX_MIN


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
        if any(is_hard(s) for s in ss):
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
    easy = [s["km"] for s in hist if s["km"] and not is_hard(s)
            and (long_day_km is None or s["km"] < 0.9 * long_day_km)]
    pool = easy or [s["km"] for s in hist if s["km"]]
    return E.median(pool) if pool else None


def _easy_pace(hist):
    paces = [1000 / s["speed"] for s in hist if s["speed"] and not is_hard(s)]
    return E.median(paces) if paces else None


# v0.9.0 — the same session bands as % of a measured LTHR (Friel's running zones;
# band edges = working assumptions matching the HRR bands above)
LTHR_BANDS = {"regenerace": (0.75, 0.85), "lehký": (0.82, 0.89), "dlouhý": (0.82, 0.90), "kvalitní": (0.95, 1.02)}


def _hr_band(kind, hrmax, rhr, lthr=None):
    if lthr and rhr < lthr < hrmax:
        lo, hi = LTHR_BANDS[kind]
        return (round(lthr * lo), round(min(hrmax, lthr * hi)))
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
    """v0.8.5 — today's check-in decides (pain-monitoring model: pain has to settle
    by the next morning, Silbernagel et al., 2007). With a check-in today: its pain
    and the pain of runs done today. Without one yet: the worst running pain of
    today and yesterday, as before, until the morning check-in says otherwise.
    Returns (pain, site, {"checkedIn", "yRun": (pain, site) of yesterday's rated run})."""
    t_iso = today.isoformat()
    cut = (today - timedelta(days=1)).isoformat()
    data = D.of(db, rid)
    cks = [c for c in data.checkins if c.submitted_at >= cut]
    rated = E._rated_runs(data, cut)

    def ck_site(c):
        regs = [p.get("region") for p in (c.pain_points or []) if p.get("region")]
        return ", ".join(regs) if regs else (c.pain_site or None)

    def run_site(f):
        regs = [p.get("region") for p in (f.pain_points or []) if p.get("region")]
        return ", ".join(regs) if regs else (f.pain_site or None)

    y_run = max(((f.pain_during or 0, run_site(f)) for f, st in rated if (st or "")[:10] < t_iso),
                key=lambda x: x[0], default=None)
    today_cks = [c for c in cks if c.submitted_at[:10] == t_iso]
    best, site = 0, None
    if today_cks:
        for c in today_cks:
            if (c.pain_score or 0) > best:
                best, site = c.pain_score, ck_site(c)
        for f, st in rated:
            if (st or "")[:10] == t_iso and (f.pain_during or 0) > best:
                best, site = f.pain_during, run_site(f)
        return best, site, {"checkedIn": True, "yRun": y_run}
    for c in cks:
        if (c.pain_score or 0) > best:
            best, site = c.pain_score, ck_site(c)
    for f in (f for f in data.feedback if f.submitted_at >= cut):
        if (f.pain_during or 0) > best:
            best, site = f.pain_during, f.pain_site
    return best, site, {"checkedIn": False, "yRun": y_run}


# v0.8.5 — cross-training by painful site: which non-running option does not load it.
# Order matters (first match wins per spot). kolo: ok | caution | avoid.
XT_SITES = [
    (("sedací hrbol", "úpon hamstring", "upon hamstring"), "avoid",
     "Při bolesti úponu hamstringů kolo zatím vynechte: ohnutá kyčel v sedle úpon stlačuje, a toho se "
     "v první fázi rehabilitace fyzioterapeuti vyhýbají (Nasser et al., 2020).", None),
    (("lýtk", "lytk", "gastrocnem", "soleus"), "avoid",
     "Při bolesti lýtka kolo vynechte: lýtkové svaly patří při šlapání k nejvíc zapojeným (Ericson et al., 1985).",
     "Plavání s pull-buoyem (bez práce nohou)."),
    (("iliotib", "it band", "it pás", "it pas"), "avoid",
     "Při bolesti IT pásu kolo vynechte: šlapání opakovaně ohýbá koleno kolem 30°, kde se IT pás "
     "stlačuje (Farrell et al., 2003).", None),
    (("achill",), "ok",
     "Kolo zatěžuje Achillovu šlachu mnohem méně než běh (Gregor et al., 1987). Bolest do 5/10, která do rána "
     "odezní, je v pořádku.", None),
    (("patel", "kvadricepsová", "kvadricepsova", "kolen", "čéšk", "cesk"), "caution",
     "Na kole s výše nastaveným sedlem a lehkým převodem zůstává tlak v čéšce nízký (Ericson & Nisell, 1987).", None),
    (("metatar", "prsty", "nárt", "nart"), "caution",
     "Pedál tlačí do přednoží; pokud to v nártu cítíte, zvolte vodu.", None),
    (("holeň", "holen", "tibial", "bérec", "berec", "pata", "plantár", "plantar", "fasci", "chodid"), "ok",
     "Bez nárazů, ale jen pokud nebolí při jízdě, po ní ani druhý den (Warden et al., 2021).", None),
    (("třísl", "trisl", "adduktor"), "caution", "Jen pokud při jízdě nic nebolí.", "Plavání bez prsového kopu."),
    (("kyčl", "kycl", "kyčel", "ohýbač", "bederní", "bederni", "si kloub", "vzpřimovač", "hamstring", "zákolen",
      "hlezen", "kotník", "kotnik"), "caution", "Jen pokud při jízdě nic nebolí.", None),
]
_XT_RANK = {"ok": 0, "caution": 1, "avoid": 2}


def cross_for_sites(sites) -> dict | None:
    """{"kolo": ok|caution|avoid, "koloNote", "vodaNote", "sites"} for the painful spots, or None."""
    spots = [x.strip() for s in (sites or []) for x in str(s or "").split(",") if x.strip()]
    if not spots:
        return None
    kolo, knotes, vnotes, hit = "ok", [], [], []
    for spot in spots:
        low = spot.lower()
        for keys, verdict, knote, vnote in XT_SITES:
            if any(k in low for k in keys):
                hit.append(spot)
                if _XT_RANK[verdict] > _XT_RANK[kolo]:
                    kolo = verdict
                if knote and knote not in knotes:
                    knotes.append(knote)
                if vnote and vnote not in vnotes:
                    vnotes.append(vnote)
                break
    if not hit:
        return None
    return {"kolo": kolo, "koloNotes": knotes, "vodaNotes": vnotes, "sites": list(dict.fromkeys(hit))}


def _rolling7_dist(day_vals: dict, today, first_day, days: int = DIST_DAYS) -> dict | None:
    """feedback railway#43 — the runner's own rolling 7-day totals over the last
    `days` days (windows that start after the first recorded session): 25th
    percentile, median, 75th percentile and max, for the Trénink gauges."""
    tot = []
    for back in range(days):
        end = today - timedelta(days=back)
        if end - timedelta(days=6) < first_day:
            break
        tot.append(sum(day_vals.get((end - timedelta(days=k)).isoformat(), 0.0) for k in range(7)))
    if len(tot) < 14:
        return None
    v = sorted(tot)

    def q(p):
        i = p * (len(v) - 1)
        lo, hi = int(i), min(int(i) + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (i - lo)
    return {"p25": q(0.25), "p50": q(0.5), "p75": q(0.75), "max": v[-1], "n": len(v)}


# railway#119 — the activity carousel on Trénink, most to least suitable today: the
# recommended type, a strength session that is due, then the other allowed types by how
# close their load is to today's recommendation (a light day puts regeneration and
# non-impact sports ahead of long and quality runs, a quality day the reverse), then the
# types not recommended today. Cycling that loads today's painful site comes after the
# other options. The load ladder is the product team's ordering, a working assumption.
LOAD_LADDER = {"volno": 0.0, "regenerace": 1.0, "voda": 1.5, "kolo": 2.0, "posilování": 2.5,
               "lehký": 3.0, "dlouhý": 4.0, "kvalitní": 5.0, "závod": 6.0}


RUN_TYPES = ("regenerace", "lehký", "dlouhý", "kvalitní")
DONE_ENOUGH = 0.8        # a run of ≥ 80 % of today's recommended distance counts as today's session (working assumption)


def _after_done(typ, types, today_runs, today_other, vol_max, override, race_today) -> dict | None:
    """Feedback #154/#158 — today's recommendation once something was already done today:
    a run that covered the recommendation (or a hard one) closes the running day, a short
    run leaves the rest as an easy top-up, a hard session in another sport takes today's
    quality session down to an easy run. None when nothing was done or nothing changes."""
    if override or race_today or not (today_runs or today_other):
        return None
    km = sum(x.get("km") or 0 for x in today_runs)
    hard_run = any(is_hard(x) for x in today_runs)
    hard_other = any(is_hard(x) or (x.get("rpe") or 0) >= HARD_RPE for x in today_other)
    names = [f"běh {_cz(km)} km"] if today_runs else []
    names += [f"{(x.get('title') or x.get('sport') or 'aktivita').lower()} {round(x['durationMin'])} min"
              for x in today_other if x.get("durationMin")][:2]
    what = ", ".join(names) or "dnešní aktivita"
    rec = types.get(typ) or {}
    lo = ((rec.get("km") or {}).get("lo") or 0) if typ in RUN_TYPES else 0
    room = vol_max if vol_max is not None else None
    if today_runs:
        if hard_run or typ not in RUN_TYPES or (lo and km >= DONE_ENOUGH * lo) or (room is not None and room < MIN_RUN_KM):
            why = ("byl to tvrdý trénink" if hard_run else
                   "pokryl dnešní doporučení" if (lo and km >= DONE_ENOUGH * lo) else
                   "na další běh už dnes nezbývá objem" if (room is not None and room < MIN_RUN_KM) else
                   "dnes byl naplánovaný den volna")
            return {"type": "volno", "doneKm": _r(km), "hard": hard_run,
                    "text": f"Dnes už máte hotovo ({what}) a {why} — zbytek dne volno, nanejvýš procházka nebo protažení."}
        # a short run: the rest of today's distance as an easy, separate top-up
        top = typ if typ != "kvalitní" else "lehký"
        if not types.get(top, {}).get("allowed"):
            top = "regenerace" if types.get("regenerace", {}).get("allowed") else "volno"
        if top == "volno":
            return {"type": "volno", "doneKm": _r(km), "hard": False,
                    "text": f"Dnes už máte hotovo ({what}) — zbytek dne volno."}
        return {"type": top, "doneKm": _r(km), "hard": False,
                "text": f"Dnes už máte hotovo ({what}). Pokud chcete, zbývá ještě krátký lehký běh do "
                        f"{_cz(room if room is not None else (rec.get('km') or {}).get('hi'))} km — bez intenzity."}
    if hard_other and typ == "kvalitní":
        top = "lehký" if types.get("lehký", {}).get("allowed") else "volno"
        return {"type": top, "doneKm": 0, "hard": True,
                "text": f"Dnes už máte za sebou náročný trénink ({what}) — místo kvalitního tréninku jen "
                        + ("lehký běh." if top == "lehký" else "volno.")}
    if hard_other and typ == "dlouhý":
        top = "lehký" if types.get("lehký", {}).get("allowed") else "volno"
        return {"type": top, "doneKm": 0, "hard": True,
                "text": f"Dnes už máte za sebou náročný trénink ({what}) — dlouhý běh přesuňte na odpočatější den."}
    return None


def rank_types(types: dict, typ: str, strength_due: bool, xt: dict | None = None) -> list:
    base = LOAD_LADDER.get(typ, 3.0)
    kolo_v = (xt or {}).get("kolo", "ok")

    def key(k):
        t = types[k]
        allowed = t.get("allowed") and not (k == "kolo" and kolo_v == "avoid")
        group = 0 if k == typ else 1 if (k == "posilování" and strength_due and allowed) else 2 if allowed else 3
        dist = abs(LOAD_LADDER.get(k, 3.0) - base) + (1.0 if (k == "kolo" and kolo_v == "caution") else 0.0)
        return (group, dist, LOAD_LADDER.get(k, 3.0))
    return sorted(types, key=key)


def build_guidance(db, rid, a, runner=None) -> dict | None:
    cap = a.get("capacity")
    if not cap:
        return None
    today = E.today_date()
    t_iso = today.isoformat()
    db = D.of(db, rid)                           # the runner's snapshot (data.py): no queries below
    tb = E.trimp_b(db.runner)                    # Banister b: 1.92 men / 1.67 women
    # the unrounded bounds capacity used: the rounded ones moved Celková zátěž by ~0.5 %, so
    # the week from Monday could read more than the 7-day sum it is part of
    hrmax, rhr = C.hr_exact(cap)
    sessions = C.run_exposures(db, rid, hrmax, rhr)
    runs = [s for s in sessions if s["run"] and s["date"] <= t_iso]
    hist = [s for s in runs if 0 < (today - _d(s["date"])).days <= 56]
    hist_days = (today - _d(min((s["date"] for s in runs), default=t_iso))).days
    novice = hist_days < NOVICE_DAYS            # plan C1: too little history for a personal model
    today_runs = [s for s in runs if s["date"] == t_iso]
    pat = _pattern(hist, today)
    easy_km = _easy_km(hist, pat["longKm"])
    easy_pace = _easy_pace(hist)
    fit = C.hr_speed_fit(runs, t_iso, lo=1, hi=56)
    speeds = sorted(s["speed"] for s in hist if s["speed"])
    speed_range = (speeds[int(0.05 * (len(speeds) - 1))], speeds[int(0.95 * (len(speeds) - 1))]) if len(speeds) >= 5 else None
    ready = cap["readiness"]["today"]                      # capacity factor 0.7–1.0 (scales sizes)
    rscore = cap["readiness"].get("score", round(ready * 100))   # readiness shown to the runner, 20–100 %
    # v0.9.3 — today's check-in (soreness, fatigue, stress, the night's rating) no longer
    # lowers readiness (it is scored on Příznaky only), but the recommendation still
    # follows it: the same deficits as before, combined with the watch's, decide the
    # session type and scale its size (owner feedback 2026-09-30).
    ci_today = max((c for c in db.checkins if (c.submitted_at or "")[:10] == t_iso),
                   key=lambda c: c.submitted_at or "", default=None)
    ci_parts = C.checkin_parts(ci_today)
    gready, gscore = ready, rscore
    if ci_parts:
        f2, s2 = C.readiness_from(C.with_checkin(cap["readiness"].get("parts") or {}, ci_parts))
        gready, gscore = min(ready, f2), min(rscore, s2)
    ci_lbl = {"soreness": "svalová bolest", "fatigue": "únava", "stress": "stres mimo trénink", "sleepSelf": "špatně prospaná noc"}
    ci_note = ", ".join(ci_lbl[k] for k in sorted(ci_parts, key=lambda k: -ci_parts[k]) if k in ci_lbl)

    def rtxt():
        return f"Připravenost {rscore} %" + (f", s dnešním check-inem ({ci_note}) {gscore} %" if gscore < rscore else "")
    ch = cap["channels"]

    # ---- context ---------------------------------------------------------
    dm_today = db.daily_by_date.get(t_iso)
    provisional = not (dm_today and (dm_today.sleep_h is not None or dm_today.hrv_ms is not None))
    pain, pain_site, pinfo = _latest_pain(db, rid, today)
    pstate = a.get("painState") or {}
    y_run_pain = (pinfo.get("yRun") or (0, None))[0] or 0
    # yesterday's run hurt more than 5/10 but this morning is calm: the load was too
    # much, the tissue settled → a lighter day rather than rest (Silbernagel et al., 2007)
    settled_after_run = pinfo["checkedIn"] and pain < 1 and y_run_pain > 5
    recurring = a.get("painRecurring")
    rec_bone = bool(recurring) and E.bone_site(recurring.get("site"))
    rec_cleared = bool(recurring) and bool(pstate.get("boneCleared") if rec_bone else pstate.get("cleared"))
    rec_active = bool(recurring) and not rec_cleared
    decision = E.triage_decision(a)
    referral = decision in ("physio_48h", "physio_7d")
    inj = (a.get("injury") or {}).get("active")
    drift = a.get("quadrant") in ("silent", "critical") or bool(a.get("mechFlag"))
    load = a.get("load") or 0
    # plan B4: the race calendar — taper and the pre-race week follow the next A
    # race; race day is any race; the profile's goal race counts as an A race
    ro = a.get("races") or {}
    if not ro and runner is not None:
        ro = E.race_outlook(db, rid, runner, a.get("maxEfforts") or []) or {}
    next_a, next_any = ro.get("nextA"), ro.get("next")
    days_to_race = next_a["daysTo"] if next_a else None
    race_today = bool(next_any) and next_any["daysTo"] == 0
    race_warn = [w for w in ro.get("warnings") or [] if w["kind"] == "race_day"]
    # v0.10.5 (railway#192): a hard ride or swim is a hard day too
    cardio = [s for s in sessions if (s["run"] or s.get("sport") in C.CROSS_CARDIO) and s["date"] <= t_iso]
    hard_dates = [s["date"] for s in cardio if is_hard(s) and s["date"] < t_iso]
    days_since_hard = (today - _d(max(hard_dates))).days if hard_dates else None
    hard7 = len({d for d in hard_dates if (today - _d(d)).days <= 6}
                | ({t_iso} if any(is_hard(s) for s in cardio if s["date"] == t_iso) else set()))
    hard_cap = HARD_CAP_FEW if (pat["runsPerWeek"] or 0) <= 4 else HARD_CAP

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
    daily["intensity"] = sums(cardio, "intensity")          # v0.10.5: hard minutes of every cardio sport
    daily["systemic"] = sums([s for s in sessions if s["date"] <= t_iso], "systemic")   # all sports
    for d, v in C.nontraining_daily(db, rid).items():                                      # + the day outside training
        if d <= t_iso:
            daily["systemic"][d] = daily["systemic"].get(d, 0.0) + v
    vol_daily = daily["volume"]

    def week_sum(c, start):
        return sum(daily[c].get((start + timedelta(days=k)).isoformat(), 0.0) for k in range(7))
    past = {c: [week_sum(c, ws - timedelta(days=7 * k)) for k in range(1, 17)] for c in daily}
    cyc = cycle_position(past["volume"])
    ov = (runner.cycle_override or {}) if runner is not None else {}
    manual = ov.get("pos") if ov.get("week") == ws.isoformat() and ov.get("pos") in CYCLE else None
    rtr = a.get("returnToRun")                  # plan B3 — graded return after a resolved injury
    rtr_all = rtr                               # the no-intensity weeks stay even in the normal cycle
    rtr_skipped = bool(rtr and ov.get("noReturn") and ov.get("noReturn") == rtr.get("injuryAt"))
    if rtr_skipped:                             # feedback #190 — the runner chose the normal cycle
        rtr = None
    if rtr:
        mode, factor = "return", rtr["factor"]
    elif days_to_race is not None and 0 < days_to_race <= 14:
        mode, factor = "taper", (0.50 if days_to_race <= 7 else 0.70)
    elif novice:                                # no cycle yet: last week + 10 %
        mode, factor = "learning", NOVICE_STEP
    elif load >= 25 and (manual or (cyc or {}).get("pos")) != 4 and (cyc is not None or manual):
        mode, factor = "deload", CYCLE[4]          # elevated load: recovery comes first, whatever was picked
    elif manual is not None:
        mode, factor = ("recovery" if manual == 4 else "build"), CYCLE[manual]
    elif cyc is None:
        mode, factor = "learning", 1.0
    else:
        mode, factor = ("recovery" if cyc["pos"] == 4 else "build"), CYCLE[cyc["pos"]]
    rec_hold = rec_cleared and mode == "build" and factor > 1.0
    if rec_hold:                                 # recurring pain settled: follow the plan, no step up yet
        factor = 1.0
    pos_now = manual if (manual is not None and mode in ("build", "recovery")) else (cyc or {}).get("pos")

    def reference(c):
        """The channel's reference week for the cycle (None → use the capacity)."""
        if mode == "return":                  # the average week of the 4 weeks before the injury
            d0 = _d(rtr["injuryAt"])
            pre = sum(daily[c].get((d0 - timedelta(days=k)).isoformat(), 0.0) for k in range(1, 29)) / 4
            return pre or None
        if novice and mode == "learning":     # the last completed week that had running
            return next((x for x in past[c][:4] if x > 0), None)
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

    first_day = _d(min((s["date"] for s in sessions if s["date"] <= t_iso), default=t_iso))
    week = {}
    for c in (*CHS, "systemic"):
        info = ch.get(c) or {}
        wcap = info.get("week") or {}
        ceil7 = wcap.get("ceiling")           # Zátěž's weekly threshold (capacity × readiness × (1 + margin))
        ref = reference(c)
        if ref is None:
            ref = wcap.get("cap")
        target = None if ref is None else ref * factor
        if novice and c != "volume":          # plan C1: only volume plans / limits the first 6 weeks
            target, ceil7 = None, None
        capped = target is not None and ceil7 is not None and target > ceil7
        if target is not None and ceil7 is not None:
            target = min(target, ceil7)       # the plan never schedules a load exceedance
        done_week = sum(daily[c].get((ws + timedelta(days=k)).isoformat(), 0.0) for k in range((today - ws).days + 1))
        done6 = sum(daily[c].get((today - timedelta(days=k)).isoformat(), 0.0) for k in range(1, 7))
        done_today = daily[c].get(t_iso, 0.0)
        left_week = None if target is None else max(0.0, target - done_week)
        # owner request 2026-10-06: the room from the absorbed load (capacity.absorbed_room);
        # the plain 7-day sum only without it
        ab_left = wcap.get("absorbedLeft")
        left7 = None if ceil7 is None else (ab_left if ab_left is not None else max(0.0, ceil7 - done6 - done_today))
        ceil_run = info.get("ceilingToday") if (c != "systemic" and not (novice and c != "volume")) else None
        limits = {k: v for k, v in (("week", left_week), ("7d", left7), ("run", ceil_run)) if v is not None}
        # on a tie (both used up) the safety limit is the one named — the plan alone would
        # offer the optional easy run
        lim = min(limits, key=lambda k: (limits[k], k == "week")) if limits else None
        safe = [v for v in (left7, ceil_run) if v is not None]
        week[c] = {"label": info.get("label", C.CHANNELS[c]["label"]), "unit": info.get("unit", C.CHANNELS[c]["unit"]),
                   # owner feedback 2026-10-10: the plan (this calendar week's target) and the safety
                   # limits (absorbed load under the weekly ceiling, the per-run ceiling) read apart —
                   # `bound` says which of the two sets today's max, `safeMax` = the safety limits alone
                   "bound": None if lim is None else "plan" if lim == "week" else "safety",
                   "safeMax": min(safe) if safe else None,
                   "plan": {"ref": _r(ref, C.CHANNELS[c]["dec"]), "factor": round(factor, 3), "capped": capped},
                   "capacity": wcap.get("cap"), "ceiling7": ceil7, "done7": done6 + done_today, "left7": left7,
                   "absorbed": wcap.get("absorbed") if ceil7 is not None else None,
                   "absorbedPast": wcap.get("absorbedPast") if ceil7 is not None else None,
                   "absorbedMax": wcap.get("absorbedMax") if ceil7 is not None else None,
                   "absorbK": wcap.get("absorbK") if ceil7 is not None else None,
                   "budget": target, "done": done_week, "doneToday": done_today, "left": left_week,
                   "ceilingRun": ceil_run, "todayMax": limits[lim] if lim else None, "limitedBy": lim,
                   "dist": _rolling7_dist(daily[c], today, first_day)}
    # Celková zátěž (HR × time, all sports) is volume × intensity in one number —
    # what's left of it also bounds today's kilometres and hard minutes
    sysw = week["systemic"]
    sys_left, sys_safe = sysw["todayMax"], sysw["safeMax"]
    easy_rate = [s["exp"]["systemic"] / s["km"] for s in hist
                 if s["km"] and s["exp"].get("systemic") and (s["exp"].get("intensity") or 0) < 5]
    per_km = E.median(easy_rate) if len(easy_rate) >= 3 else None
    z4pm = z4_trimp_per_min(tb)
    km_by_sys = sys_left / per_km if (sys_left is not None and per_km) else None
    km_by_sys_safe = sys_safe / per_km if (sys_safe is not None and per_km) else None
    vol_safe_sys = False
    for c, cap_c, cap_s in (() if novice else (("volume", km_by_sys, km_by_sys_safe),
                                               ("intensity", None if sys_left is None else sys_left / z4pm,
                                                None if sys_safe is None else sys_safe / z4pm))):
        week[c]["sysCap"] = cap_c             # Celková zátěž's room in this channel's units (the limits ladder)
        if cap_c is not None and (week[c]["todayMax"] is None or cap_c < week[c]["todayMax"]):
            # the bound follows what set Celková zátěž's own limit (its weekly target or its safety room)
            week[c]["todayMax"], week[c]["limitedBy"], week[c]["bound"] = cap_c, "systemic", sysw["bound"]
        if cap_s is not None and (week[c]["safeMax"] is None or cap_s < week[c]["safeMax"]):
            week[c]["safeMax"] = cap_s
            vol_safe_sys = vol_safe_sys or c == "volume"
    week["volume"]["sysKm"] = None if novice else km_by_sys
    # the hills ride on the kilometres: with Celková zátěž cutting today's km, the
    # descent / ascent follow at the runner's hilliest usual metres per km (p90)
    vw0 = week["volume"]
    hill_p90 = {}
    for c in ("descent", "ascent"):
        rates = sorted(s["exp"][c] / s["km"] for s in hist if s["km"] and s["exp"].get(c) is not None)
        if rates:
            hill_p90[c] = rates[min(len(rates) - 1, int(0.9 * len(rates)))]
    if not novice:
        for c, p90 in hill_p90.items():
            if vw0["limitedBy"] == "systemic" and vw0["todayMax"] is not None:
                cap_c = vw0["todayMax"] * p90
                week[c]["sysCap"] = cap_c
                if week[c]["todayMax"] is None or cap_c < week[c]["todayMax"]:
                    week[c]["todayMax"], week[c]["limitedBy"], week[c]["bound"] = cap_c, "systemic", vw0["bound"]
            if vol_safe_sys and vw0["safeMax"] is not None:
                cap_s = vw0["safeMax"] * p90
                if week[c]["safeMax"] is None or cap_s < week[c]["safeMax"]:
                    week[c]["safeMax"] = cap_s
    if drift:                                 # mechanics over its threshold: keep today well inside capacity
        for c, f in DRIFT_CUT.items():
            if week[c]["todayMax"] is not None:
                week[c]["todayMax"] *= f
                week[c]["limitedBy"], week[c]["bound"] = "mechanics", "safety"
            if week[c]["safeMax"] is not None:
                week[c]["safeMax"] *= f
    for c, wc in week.items():
        dec = C.CHANNELS[c]["dec"]
        for k in ("capacity", "ceiling7", "done7", "left7", "budget", "done", "doneToday", "left", "todayMax", "sysKm",
                  "safeMax", "sysCap"):
            if k in wc:
                wc[k] = _r(wc[k], dec)
        if wc.get("dist"):
            wc["dist"] = {k: (_r(v, dec) if k != "n" else v) for k, v in wc["dist"].items()}
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
        # feedback #169 — after an injury the weeks follow the return steps, not the cycle
        "returnSteps": ([round(x * 100) for x in E.RTR_FACTORS] if mode == "return" else None),
        "returnWeek": (rtr["week"] if mode == "return" else None),
        "next": nxt,
        "pos": pos_now, "autoPos": cyc["pos"] if cyc else None, "manual": manual is not None and mode in ("build", "recovery"), "returnSkipped": rtr_skipped,
        "how": cyc["how"] if cyc else None, "factor": round(factor, 3),
        "refKm": _r(reference("volume") or week["volume"]["capacity"]) if (cyc or mode == "return") else _r(week["volume"]["capacity"]),
        "refWeek": (ws - timedelta(days=7 * cyc["refBack"])).isoformat() if cyc and cyc["refBack"] else None,
        "weeks": [{"start": (ws - timedelta(days=7 * k)).isoformat(), "km": _r(past["volume"][k - 1])} for k in (4, 3, 2, 1)]
        + [{"start": ws.isoformat(), "km": week["volume"]["done"], "target": week["volume"]["budget"], "current": True}],
    }

    # ---- limits per session type --------------------------------------------
    vol_max = week["volume"]["todayMax"]
    int_max = week["intensity"]["todayMax"]
    # ---- strength carry-over (Doma et al., 2017): the latest heavy lower-body session
    strength = [x for x in sessions if x.get("sport") == "strength" and x["date"] <= t_iso]
    heavy = [x for x in strength if x.get("heavyLower") and (today - _d(x["date"])).days in STRENGTH_CARRY]
    carry = None
    if heavy:
        hs = max(heavy, key=lambda x: x["date"])
        age_h = (today - _d(hs["date"])).days
        carry = {"date": hs["date"], "age": age_h, "factor": STRENGTH_CARRY[age_h], "rpe": hs.get("rpe"),
                 "focus": hs.get("strengthFocus")}
        if int_max is not None:
            int_max *= carry["factor"]
    # ---- heat (v0.8.4): today's forecast vs. how many runs were in the heat lately
    hot14 = sum(1 for x in runs if x.get("hot") and 0 <= (today - _d(x["date"])).days <= 13)
    fc = W.forecast_cached(rid, t_iso)
    heat = None
    if fc and fc["feelsMax"] >= W.HOT_FEELS_C:
        heat = {"feelsMax": fc["feelsMax"], "hot14": hot14,
                "stage": "new" if hot14 < HEAT_ACCLIM_RUNS else "adapting" if hot14 < HEAT_ACCLIM_FULL else "adapted"}
        if heat["stage"] == "new" and int_max is not None:
            int_max *= HEAT_INT_FACTOR
    # ---- strength habit (v0.8.4): long gap / a new block just started
    s_dates = sorted({x["date"] for x in strength})
    s_last_age = (today - _d(s_dates[-1])).days if s_dates else None
    new_block = None
    recent_s = [d for d in s_dates if (today - _d(d)).days < STRENGTH_NEW_BLOCK_DAYS]
    if recent_s:
        first = recent_s[0]
        before = [d for d in s_dates if 0 < (_d(first) - _d(d)).days <= 28]
        if not before and len(hist) >= 8:
            new_block = {"since": first, "day": (today - _d(first)).days + 1}
    desc_max = week["descent"]["todayMax"]
    asc_max = week["ascent"]["todayMax"]
    base_km = easy_km or 6.0
    func = a.get("functionLimit")               # plan A1 — pain that limits movement / changed a run
    acute = a.get("acuteOverload")              # plan A2 — "too much" right after a run
    race = a.get("raceRecovery")                # plan A3 — recovery block after a race / maximal effort
    pmon = a.get("painMonitor") or {}           # plan B2 — pain-monitoring model (Silbernagel 2007)
    morning, ptrend = pmon.get("morningWorse"), pmon.get("trend")
    scr = a.get("screening") or {}               # v0.8.4 — red flags, bone stress, bone pain, illness
    red, bstress, bpain, ill = scr.get("redFlag"), scr.get("boneStress"), scr.get("bonePain"), scr.get("ill")
    # v0.12.0 — the "neck check": reported symptoms only above the neck (asked when the watch
    # flagged an illness) allow a short easy run; below the neck or not asked → rest
    ill_light = bool(ill) and ill.get("systemic") is False
    ill_sig = scr.get("illSignal")
    ill_watch = bool(ill_sig) and not ill                     # flagged, no symptoms reported (or no answer)
    cluster = a.get("cluster")
    acute_mod = bool(acute) and 2 <= acute["daysSince"] <= 3
    pain_mod = (3 <= pain <= 5 or (rec_active and pain <= 5) or (bool(func) and not func["severe"])
                or acute_mod or bool(ptrend) or settled_after_run)
    need = (f"{E.CLEAR_BONE_DAYS} dní bez bolesti" if rec_bone else f"{E.CLEAR_CHECKINS} check-iny bez bolesti")
    pain_why = (f"Bolest {pain}/10" if pain >= 3 else
                "Bolest omezila běh" if (func and not func["severe"]) else
                "Po akutním přetížení" if acute_mod else
                (f"Ranní test šlachy se týden od týdne zhoršuje ({_cz(ptrend['before'])} → {_cz(ptrend['now'])}/10)"
                 if ptrend.get("source") == "tendonTest" else
                 f"Bolest roste týden od týdne ({_cz(ptrend['before'])} → {_cz(ptrend['now'])}/10)") if ptrend else
                f"Včerejší běh bolel {y_run_pain}/10, ráno je klid" if settled_after_run else
                f"Opakovaná bolest ({recurring['site']}, {recurring['days']}× za 28 dní; uvolní se po: {need})"
                if rec_active else "")
    km_scale = (0.7 if pain_mod else 1.0) * max(gready, 0.75) * (0.9 if new_block else 1.0)
    # weekly target reached but the safety limits still have room: a short easy run
    # stays available (not the default) — a rested body may move, the plan isn't risk.
    # Owner feedback 2026-10-10: also when it's Celková zátěž's weekly target that is met
    # (the plan, not the absorbed load) — before, that read as a safety ceiling.
    vw = week["volume"]
    easy_room = vw["safeMax"]                  # safety only — the week's plan targets don't bound this extra run
    extra_easy = (vw["bound"] == "plan" and (vol_max or 0) < MIN_RUN_KM and easy_room is not None
                  and easy_room >= MIN_RUN_KM and gscore >= READY_EXTRA_EASY and not pain_mod and pain < 3)

    def cap_km(x):
        return x if vol_max is None else min(x, vol_max)

    def mk(kind, lo, hi, z4max=None, z4t=None, dfac=1.0, terrain=None, notes=None, vmax=None):
        hr = _hr_band(kind, hrmax, rhr, getattr(db.runner, "threshold_hr", None)) if kind in HRR else None
        pace = _pace_band(kind, hr, fit, easy_pace, speed_range) if kind != "kvalitní" else None
        lo, hi = (cap_km(lo), cap_km(hi)) if vmax is None else (min(lo, vmax), min(hi, vmax))
        lo = min(lo, hi)
        mid_pace = ((pace[0] + pace[1]) / 2) if pace else easy_pace
        dur = (round(lo * mid_pace / 60), round(hi * mid_pace / 60)) if mid_pace else None
        # the optional run over the week's target (vmax) keeps to the safety room of the hills
        # too — the plan's 0 m left would otherwise forbid any descent at all
        d_room = week["descent"]["safeMax"] if vmax is not None else desc_max
        a_room = week["ascent"]["safeMax"] if vmax is not None else asc_max
        d_max = None if d_room is None else d_room * dfac * (0.5 if (pain_mod or drift) else 1.0)
        return {"label": TYPE_LABEL[kind], "km": {"lo": _r(lo), "hi": _r(hi), "max": _r(vol_max if vmax is None else vmax)},
                "durationMin": dur, "hr": hr, "hrZones": {"regenerace": "Z1–Z2", "lehký": "Z2", "dlouhý": "Z2",
                                                          "kvalitní": "Z4–Z5 v úsecích, jinak Z1–Z2"}[kind],
                "pace": pace, "z4Max": _r(z4max, 0), "z4Target": z4t, "descentMax": _r(d_max, 0),
                "ascentMax": _r(None if a_room is None else a_room * dfac, 0),
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
                             + (["Nad rámec týdenního cíle — jen pokud máte chuť; vejde se pod bezpečnostní strop "
                                 "(nevstřebaná zátěž i strop jednoho běhu)."]
                                if extra_easy else []))
    types["lehký"] = mk("lehký", 0.85 * base_km * km_scale, 1.1 * base_km * km_scale,
                        z4max=min(5, int_max) if int_max is not None else 5, dfac=0.8)
    long_target = max(base_km * 1.2, LONG_SHARE * (week["volume"]["budget"] or 0))
    if novice:                                   # plan C1: ≤ 10 % over the longest run of the last 30 days
        longest30 = max((s["km"] or 0 for s in runs if 0 < (today - _d(s["date"])).days <= 30), default=0)
        if longest30:
            long_target = min(long_target, NOVICE_LONG * longest30)
    long_target = cap_km(long_target * (1.0 if not pain_mod else 0.7))
    types["dlouhý"] = mk("dlouhý", 0.85 * long_target, long_target,
                         z4max=min(10, int_max) if int_max is not None else 10,
                         notes=[f"Nejvýš {round(LONG_SHARE * 100)} % týdenního rozpočtu objemu; stejnoměrně, v Z2."])
    z4hi = None if int_max is None else min(int_max, Z4_SESSION_MAX) * (0.5 if drift else 1.0)
    if novice and (z4hi is None or z4hi < NOVICE_Z4):
        z4hi = NOVICE_Z4 * (0.5 if drift else 1.0)          # plan C1: intensity doesn't block the first 6 weeks
    z4t = None if z4hi is None else {"lo": _r(0.6 * z4hi, 0), "hi": _r(z4hi, 0)}
    types["kvalitní"] = mk("kvalitní", 0.9 * base_km * km_scale, 1.1 * base_km * km_scale, z4max=z4hi, z4t=z4t,
                           dfac=0.6, terrain="rovina / dráha — tvrdé úseky ne z kopce",
                           notes=["Rozklus a výklus v Z1–Z2; tvrdé úseky v Z4–Z5 do stropu minut."])
    # ---- cross-training types -------------------------------------------------
    all_list = E.all_acts(db, rid, "load")
    sport_hr = E.sport_hr_max(all_list, hrmax)
    k_srpe, _k_runs = E.srpe_k(all_list, E.feedback_rpe(db, rid), hrmax, rhr, tb)
    sys_left = week["systemic"]["todayMax"]

    def xmk(kind, lo, hi, *, hr=None, zones=None, rpe=None, notes=None, sport=None):
        return {"label": TYPE_LABEL[kind], "cross": True, "sport": sport, "km": None,
                "durationMin": (round(lo), round(hi)), "hr": hr, "hrZones": zones, "rpeTarget": rpe, "pace": None,
                "z4Max": None, "z4Target": None, "descentMax": None, "ascentMax": None, "terrain": None,
                "notes": notes or [], "allowed": True, "why": None}
    hm_c = sport_hr.get("cycling", hrmax - 8)
    hr_c = (round(rhr + CYCLE_Z2[0] * (hm_c - rhr)), round(rhr + CYCLE_Z2[1] * (hm_c - rhr)))
    per_min_c = E._trimp(1.0, rhr + sum(CYCLE_Z2) / 2 * (hm_c - rhr), hm_c, rhr, tb)
    sys_plan_met = sysw["bound"] == "plan" and sys_safe is not None

    def cross_hi(per_min, cap_max, extra_max):
        """(minutes, optional) — the session's length from what's left of Celková zátěž; with
        only its weekly TARGET met (owner feedback 2026-10-10) a shorter optional session
        inside the safety room on a well-recovered day, like the optional easy run."""
        hi = cap_max if sys_left is None else min(cap_max, sys_left / per_min)
        if sys_left is None or hi >= CROSS_MIN or not sys_plan_met or gscore < READY_EXTRA_EASY:
            return hi, False
        hi2 = min(extra_max, sys_safe / per_min)
        return (hi2, True) if hi2 >= CROSS_MIN else (hi, False)
    kolo_hi, kolo_extra = cross_hi(per_min_c, KOLO_MAX, EXTRA_RIDE_MAX)
    extra_note = ["Nad rámec týdenního cíle celkové zátěže — jen pokud máte chuť; vejde se pod bezpečnostní strop."]
    types["kolo"] = xmk("kolo", max(CROSS_MIN, 0.6 * kolo_hi), max(CROSS_MIN, kolo_hi), hr=hr_c, zones="Z2 na kole",
                        sport="cycling",
                        notes=(extra_note if kolo_extra else [])
                        + ["Tepové pásmo je z maxima pro kolo, které bývá o 6–10 tepů nižší než při běhu.",
                           "Běžecké kilometry se nepočítají, zátěž jde jen do celkové zátěže."])
    voda_hi, voda_extra = cross_hi(4 * k_srpe, VODA_MAX, VODA_MAX)
    types["voda"] = xmk("voda", max(CROSS_MIN, 0.66 * voda_hi), max(CROSS_MIN, voda_hi), rpe="3–4 z 10",
                        zones="podle pocitu", sport="swimming",
                        notes=(extra_note if voda_extra else [])
                        + ["Plynulé plavání ve stálém tempu, klidně s přestávkami na okraji bazénu.",
                           "Tep ve vodě bývá nižší, řiďte se pocitem námahy. Jen pokud při tom nic nebolí."])
    types["kolo"]["optional"], types["voda"]["optional"] = kolo_extra, voda_extra
    types["regenerace"]["optional"] = extra_easy
    types["posilování"] = xmk("posilování", 30, 45, rpe="6–7 z 10", zones=None, sport="strength",
                              notes=["Po tvrdém běhu až s odstupem aspoň 3 hodin, před tvrdým během aspoň 24 hodin."])
    # railway#196 — the exercises come from the Runner's must-have programme (Péče → Program),
    # not a generic list; Trénink links there, the assistant gets the pointer
    types["posilování"]["program"] = {"key": "durability",
                                      "note": "Cviky podle programu Runner's must-have v Péči (2× týdně, session A síla a B odolnost)."}
    sys_full = sys_txt(sysw, gscore)
    if sys_left is not None and kolo_hi < CROSS_MIN:
        types["kolo"]["allowed"], types["kolo"]["why"] = False, sys_full
    if sys_left is not None and voda_hi < CROSS_MIN:
        types["voda"]["allowed"], types["voda"]["why"] = False, sys_full
    # strength: this calendar week, the race phase, spacing before an intensive run
    ws_iso = week_start(today).isoformat()
    s_target = STRENGTH_TARGET_RACE if (days_to_race is not None and 0 < days_to_race <= 14) else STRENGTH_TARGET
    s_done = sum(1 for x in strength if x["date"] >= ws_iso)
    s_today = any(x["date"] == t_iso for x in strength)
    tomorrow_hard = (wd_next := (today.weekday() + 1) % 7) in pat["hardDays"]
    if s_today:
        types["posilování"]["allowed"], types["posilování"]["why"] = False, "Posilování už dnes máte hotové."
    elif days_to_race is not None and 0 < days_to_race <= 3:
        types["posilování"]["allowed"], types["posilování"]["why"] = False, "Pár dní před závodem bez posilování."
    elif tomorrow_hard:
        types["posilování"]["allowed"] = False
        types["posilování"]["why"] = (f"Zítra ({WD[wd_next]}) obvykle trénujete tvrdě. Mezi posilováním a intenzivním "
                                      "během nechte aspoň 24 hodin.")
    if s_target and s_done < s_target:
        types["posilování"]["notes"].insert(0, f"Tento týden {s_done} z {s_target} posilování.")
    if race_today:
        types["závod"] = {"label": TYPE_LABEL["závod"], "km": next_any.get("km"), "allowed": True, "why": None,
                          "notes": [race_warn[0]["text"]] if race_warn else
                                   ["Hodně štěstí! Dnes bez limitů — po závodě nechte tělo regenerovat."],
                          "terrain": None, "hr": None, "pace": None, "durationMin": None, "z4Max": None,
                          "z4Target": None, "descentMax": None, "ascentMax": None}

    # ---- why a type isn't advisable today --------------------------------
    def block(kind, why):
        if types[kind]["allowed"]:
            types[kind]["allowed"], types[kind]["why"] = False, why
    override = None
    if red:
        override = ({"kind": "red_flag", "title": "Varovné příznaky — vyhledejte hned lékaře",
                     "text": f"Bolest zad ({red['site']}) se změnou močení nebo stolice nebo s necitlivostí v rozkroku je "
                             "důvod k okamžitému lékařskému vyšetření (pohotovost). Tréninková doporučení jsou pozastavená."}
                    if red["kind"] == "cauda" else
                    {"kind": "red_flag", "title": "Bolest zad s horečkou nebo po úrazu — nejdřív k lékaři",
                     "text": f"Bolest zad ({red['site']}) s horečkou nebo po pádu či úrazu je důvod nechat se co nejdřív "
                             "vyšetřit lékařem. Do té doby bez tréninku."})
    elif inj:
        # v0.8.5: after pain-free check-ins with normal movement the app asks whether it has
        # healed instead of silently keeping the rest day (the answer stays the runner's / physio's)
        can_resolve = bool(pstate.get("cleared")) and not func
        override = {"kind": "injury", "title": "Aktivní zranění — dnes bez běhu",
                    "text": f"{inj.get('site') or 'Nahlášené zranění'} (OSTRC {inj.get('severity')}/100). "
                            "Běh odložte, dokud se zranění nezlepší; řiďte se doporučením fyzioterapeuta."
                            + (f" Posledních {pstate.get('cleanCheckins')} check-inů je bez bolesti — pokud je zranění "
                               "zahojené, označte ho, a trénink se vrátí postupně (50 → 75 → 90 %)." if can_resolve else ""),
                    "canResolve": can_resolve}
    elif func and func["severe"]:
        override = {"kind": "function", "title": "Bolest omezuje pohyb — dnes neběhat",
                    "text": f"{func['site'] or 'Nahlášená bolest'}: " + ("omezuje běžný pohyb" if func["limitsMovement"]
                                                                        else "kulháte") +
                            ". Omezený pohyb je úroveň zranění, i když je číslo bolesti nízké. Běh vynechte, hýbejte se "
                            "jen tak, aby to nebolelo, a nechte to posoudit fyzioterapeutem (do 48 hodin)."}
    elif bstress:
        override = {"kind": "bone_stress", "title": "Bolest s varovnými znaky přetížení kosti — dnes neběhat",
                    "text": f"{bstress['site']}: {', '.join(bstress['what'])}. Takový průběh bývá u únavového přetížení "
                            "kosti, a to i při nízkém čísle bolesti. Běh vynechte a nechte to posoudit fyzioterapeutem "
                            "(do 48 hodin). Kolo nebo plavání jen tehdy, když při nich nic nebolí."}
    elif pain > 5 and referral:
        override = {"kind": "physio", "title": "Dnes neběhat — objednejte se k fyzioterapeutovi",
                    "text": f"Bolest {pain}/10{f' · {pain_site}' if pain_site else ''} a zároveň engine doporučuje "
                            f"fyzioterapeuta ({'do 48 hodin' if decision == 'physio_48h' else 'do 7 dnů'}). "
                            "Kombinace bolesti a rizikového stavu je důvod běh vynechat a nechat to posoudit."}
    elif morning and morning.get("source") == "tendonTest":
        base = (f", před během {morning['baseline']}/10" if morning.get("baseline") is not None and morning.get("runDate") else "")
        override = {"kind": "pain_monitor",
                    "title": ("Šlacha se do rána neuklidnila — dnes neběhat" if morning.get("runDate") and morning["morning"] <= 5
                              else "Ranní test šlachy nad 5/10 — dnes neběhat"),
                    "text": f"{morning['site']}: ranní test ({morning['test']}) {morning['morning']}/10{base}. Bolest šlachy má "
                            "do rána odeznít a nepřekročit 5/10; když ne, byla zátěž moc. Dnes bez běhu, kolo nebo plavání "
                            "jen bez bolesti, další běh kratší a volnější. Když se to zopakuje, k fyzioterapeutovi."}
    elif morning:
        override = {"kind": "pain_monitor", "title": "Bolest je ráno horší než při běhu — dnes neběhat",
                    "text": f"{morning['site'] or 'Bolest'}: ráno {morning['morning']}/10, při včerejším běhu "
                            f"{morning['during']}/10. Bolest má do rána odeznít; když je horší, byla zátěž moc. Dnes bez "
                            "běhu, další běh kratší a volnější — a pokud se to zopakuje, k fyzioterapeutovi."}
    elif acute and acute["daysSince"] <= 1:
        override = {"kind": "acute", "title": "Akutní přetížení po běhu — dnes neběhat",
                    "text": f"{', '.join(acute['reasons']).capitalize()} ({acute['at'][8:10].lstrip('0')}. "
                            f"{acute['at'][5:7].lstrip('0')}.). Den dva bez běhu, pak jen volně a krátce; "
                            "pokud bolest do 3 dnů neustoupí, proberte to s fyzioterapeutem."}
    if override:
        for k in ("regenerace", "lehký", "dlouhý", "kvalitní", "závod", "posilování"):
            if k in types:
                block(k, override["title"])
        for k in ("kolo", "voda"):
            if override["kind"] == "red_flag":
                block(k, override["title"])
            else:
                types[k]["notes"].insert(0, "Jen pokud při tom nic nebolí a fyzioterapeut s tím souhlasí.")
    if carry:
        when = "dnes" if carry["age"] == 0 else "včera" if carry["age"] == 1 else "předevčírem"
        if carry["age"] <= 1:
            block("kvalitní", f"Posilování nohou {when}: 24–48 hodin po silovém tréninku bývá horší výkon "
                              "v intenzitě. Klidný běh je v pořádku.")
        else:
            types["kvalitní"]["notes"].append(f"Posilování nohou {when} — strop minut v Z4+ je o čtvrtinu nižší.")
    race_rest = bool(race) and race["daysSince"] < race["restDays"]
    if race and not override:
        left_days = race["days"] - race["daysSince"]
        why_r = (f"Zotavení po závodním úsilí ({_cz(race['km'])} km, {race['date'][8:10].lstrip('0')}. "
                 f"{race['date'][5:7].lstrip('0')}.) — ještě {left_days} {'den' if left_days == 1 else 'dny' if left_days < 5 else 'dní'}")
        block("kvalitní", f"{why_r} bez intenzity.")
        block("dlouhý", f"{why_r} bez dlouhého běhu.")
        if race_rest:
            block("lehký", f"{why_r}; první dny jen odpočinek nebo velmi volně.")
    bone_block = bool(bpain) and not override
    if bone_block:
        for k in ("regenerace", "lehký", "dlouhý", "kvalitní"):
            block(k, f"Bolest {bpain['pain']}/10 v místě typickém pro přetížení kosti ({bpain['site']}) — "
                     "u kosti se bolest nepřechází, dnes bez běhu.")
        for k in ("kolo", "voda"):
            types[k]["notes"].insert(0, "Jen pokud při tom nic nebolí.")
    if ill and not override:
        for k in ("dlouhý", "kvalitní", "posilování"):
            block(k, "Hlásíte nemoc — dnes bez náročného tréninku.")
        if ill_light:
            types["regenerace"]["notes"].insert(0, "Příznaky jen nad krkem: nanejvýš krátce a velmi volně, a jen když "
                                                   "se při tom cítíte dobře.")
    if ill_watch and not override:
        what, when = _ill_what(ill_sig)
        for k in ("kvalitní", "dlouhý"):
            block(k, f"Hodinky ukazují {what} {when} — dnes bez náročného tréninku, než se ukáže, jestli nejde o nemoc.")
    if pain > 5 and not override:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, f"Bolest {pain}/10 — dnes jen velmi volně nebo jiný sport bez bolesti.")
    if pain_mod:
        block("dlouhý", f"{pain_why} — dnes bez dlouhého běhu.")
        block("kvalitní", f"{pain_why} — dnes bez intenzity.")
    if rtr_all and rtr_all["noQuality"]:
        block("kvalitní", f"Návrat po zranění — bez intenzity do {_dm(rtr_all['noQualityUntil'])}.")
    if gscore < READY_QUALITY:
        block("kvalitní", f"{rtxt()} — na tvrdý trénink je potřeba aspoň {READY_QUALITY} %.")
        block("dlouhý", f"{rtxt()} — dlouhý běh přesuňte na odpočatější den.")
    if load >= 25:
        block("kvalitní", "Zátěž je zvýšená — týden odlehčujeme, bez tvrdých úseků.")
    if a.get("quadrant") in ("overreaching", "critical"):     # A4: the recommendation follows the state label
        block("kvalitní", "Stav Přetížení — dokud se zátěž nevrátí pod práh, bez tvrdého tréninku.")
        block("dlouhý", "Zátěž je zvýšená — bez dlouhého běhu, dokud neklesne.")
    if days_since_hard is not None and days_since_hard < HARD_GAP_DAYS:
        block("kvalitní", "Poslední tvrdý trénink byl před méně než 48 h.")
    if hard7 >= hard_cap:
        block("kvalitní", f"Za posledních 7 dní už {hard7} tvrdé tréninky — víc než {hard_cap} týdně obvykle nic nepřidá, "
                          "většina běhů má zůstat lehká.")
    if heat:
        msg = {"new": f"Dnes pocitově až {heat['feelsMax']} °C a na horko ještě nejste zvyklí — strop minut v Z4+ je nižší, "
                      "úseky raději ráno nebo večer.",
               "adapting": f"Dnes pocitově až {heat['feelsMax']} °C — tělo si na horko zvyká, tep bude o něco vyšší.",
               "adapted": f"Dnes pocitově až {heat['feelsMax']} °C."}[heat["stage"]]
        types["kvalitní"]["notes"].append(msg)
        for k in ("lehký", "dlouhý", "regenerace"):
            types[k]["notes"].append("V horku je tep při stejném tempu vyšší — držte se tepového rozmezí, ne tempa.")
    nsw = SP.no_speed_weeks(sessions, today)
    if nsw and not novice and "lehký" in types:
        types["lehký"]["notes"].append("Poslední 4 týdny žádný rychlý úsek. Pokud jste neběželi ani rovinky, přidejte po "
                                      "lehkém běhu 4–6 stupňovaných rovinek po 15–20 s (ne naplno): pravidelný kontakt "
                                      "s rychlostí chrání zadní stehenní svaly, prudký návrat k ní je riziko (Malone et al., "
                                      "2017; Duhig et al., 2016).")
    if new_block:
        types["posilování"]["notes"].append(f"Nový silový blok (den {new_block['day']}): první 2–3 týdny bývají nohy "
                                            "těžké a bolavé, běh je proto o něco kratší.")
    elif s_last_age is None or s_last_age >= STRENGTH_GAP_DAYS:
        types["posilování"]["notes"].insert(0, ("Posilování zatím nemáte zapsané" if s_last_age is None else
                                                f"Poslední posilování před {s_last_age} dny")
                                            + " — dvakrát týdně zlepšuje běžeckou ekonomiku.")
    if novice:
        pass                                     # plan C1: generic hard-minute cap instead of a block
    elif int_max is None:
        block("kvalitní", "Kapacitu intenzity zatím neznáme — chybí běhy s tepem.")
    elif (z4hi or 0) < 10:
        # say which limit is binding: the calendar week, the rolling 7 days, the
        # all-sport load or mechanics (the assistant repeats this sentence)
        block("kvalitní", {
            "7d": "Nevstřebané minuty v Z4+ z posledních dní jsou na hranici kapacity, tvrdý trénink počká pár dní.",
            "systemic": ("Týdenní cíl celkové zátěže je splněný — tvrdý trénink se do plánu tohoto týdne nevejde."
                         if week["intensity"].get("bound") == "plan" else
                         "Nevstřebaná celková zátěž ze všech sportů nenechává místo na tvrdý trénink."),
            "mechanics": "Mechanika se odchyluje od normy, dnešní strop minut v Z4+ na kvalitní trénink nestačí.",
            "run": "Dnešní strop minut v Z4+ na kvalitní trénink nestačí.",
        }.get(week["intensity"].get("limitedBy"), "Na tento týden už nezbývá rozpočet intenzity (min v Z4+)."))
    if drift:
        types["kvalitní"]["notes"].append("Mechanika se odchyluje — strop minut v Z4+ je poloviční.")
    if vol_max is not None and vol_max < 1.2 * base_km:
        block("dlouhý", f"Strop na jeden běh je dnes {_cz(vol_max)} km — na dlouhý běh nezbývá.")
    if days_to_race is not None and 0 < days_to_race <= 7:
        block("dlouhý", "Týden před závodem — bez dlouhého běhu.")
    no_room = {"week": "Týdenní cíl objemu je splněný.", "7d": "Nevstřebaná zátěž z posledních dní je na stropu týdenní kapacity.",
               "systemic": ("Týdenní cíl celkové zátěže je splněný." if vw["bound"] == "plan" else
                            "Nevstřebaná celková zátěž (tep × čas) je na stropu týdenní kapacity."),
               "run": "Na dnešek už nezbývá objem."}
    if vw["left"] is not None and vw["left"] < 0.5 * base_km:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, "Týdenní cíl objemu je splněný.")
    if vol_max is not None and vol_max < 0.5 * base_km:
        for k in ("lehký", "dlouhý", "kvalitní"):
            block(k, no_room.get(vw["limitedBy"], "Na dnešek už nezbývá objem."))
    if vol_max is not None and vol_max < MIN_RUN_KM and not extra_easy:
        block("regenerace", no_room.get(vw["limitedBy"], "Na dnešek už nezbývá objem.")
              + " Volno, případně jiný sport bez nárazů (kolo, plavání).")

    # ---- cross-training by painful site (v0.8.5) --------------------------------
    xt_sites = []
    if pain >= 1 and pain_site:
        xt_sites.append(pain_site)
    if bpain:
        xt_sites.append(bpain["site"])
    if rec_active:
        xt_sites.append(recurring["site"])
    if inj and inj.get("site"):
        xt_sites.append(inj["site"])
    xt = cross_for_sites(xt_sites)
    if xt:
        if xt["kolo"] == "avoid":
            block("kolo", xt["koloNotes"][0])
        else:
            types["kolo"]["notes"] = [n for n in xt["koloNotes"] if n not in types["kolo"]["notes"]] + types["kolo"]["notes"]
        types["voda"]["notes"] = [n for n in xt["vodaNotes"] if n not in types["voda"]["notes"]] + types["voda"]["notes"]

    # ---- default type -------------------------------------------------------
    wd = today.weekday()
    ran_recent = sum(1 for k in (1, 2) if vol_daily.get((today - timedelta(days=k)).isoformat()))
    runs_last6 = sum(1 for k in range(1, 7) if vol_daily.get((today - timedelta(days=k)).isoformat()))
    if race_today and not override:
        typ = "závod"
    elif override or race_rest or bone_block or (ill and not ill_light):
        typ = "volno"
    elif ill_light:
        typ = "regenerace" if types["regenerace"]["allowed"] else "volno"
    elif pain > 5:
        typ = "regenerace"
    elif gscore < READY_EASY_ONLY:
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
    run_blocked = vol_max is not None and vol_max < MIN_RUN_KM and not extra_easy
    ride_day = (not pat["runDays"]) or wd in pat["runDays"]
    if (typ == "volno" and not override and not race_rest and run_blocked and ride_day
            and gscore >= READY_EASY_ONLY and types["kolo"]["allowed"] and not kolo_extra and vw["limitedBy"] != "systemic"):
        typ = "kolo"                      # running tissues are at their limit, the aerobic side isn't
    # v0.8.5: a rest day because of pain → the non-running option that spares the painful
    # spot (deep-water running keeps aerobic fitness for 4–6 weeks: Wilber et al., 1996;
    # Reilly et al., 2003). Not with illness, red flags, limited movement, bone-stress
    # warning signs, an active injury or a physio referral — those stay rest.
    pain_rest = (pain > 5 and not override) or bone_block or \
        (bool(override) and override["kind"] in ("pain_monitor", "acute"))
    xt_pick = None
    if typ in ("volno", "regenerace") and pain_rest and not ill and not race_rest and not race_today:
        kolo_v = (xt or {}).get("kolo", "ok")
        if kolo_v == "ok" and types["kolo"]["allowed"]:
            xt_pick = "kolo"
        elif types["voda"]["allowed"]:
            xt_pick = "voda"
        elif kolo_v == "caution" and types["kolo"]["allowed"]:
            xt_pick = "kolo"
    if xt_pick:
        typ = xt_pick

    # ---- feedback #154/#158: an activity already done today shapes the rest of the day
    today_other = [x for x in sessions if not x["run"] and x["date"] == t_iso and x.get("sport") != "walking"]
    after_done = _after_done(typ, types, today_runs, today_other, vol_max, override, race_today)
    if after_done:
        typ = after_done["type"]

    # ---- reasons (most important first) -------------------------------------
    reasons = []  # the override itself is shown as the banner, not repeated here
    if after_done:
        reasons.append(after_done["text"])
    if override:
        pass
    elif bone_block:
        reasons.append(f"Bolest {bpain['pain']}/10 · {bpain['site']}: u kosti se návrat k běhu řídí úplnou absencí bolesti, "
                       "proto dnes bez běhu. Kolo nebo plavání jen bez bolesti."
                       + (" Bolest se v posledních dvou týdnech vrací, nechte ji posoudit fyzioterapeutem." if bpain["repeated"] else ""))
    elif ill and ill_light:
        reasons.append("Hlásíte příznaky jen nad krkem (rýma, škrábání v krku) — nanejvýš krátký volný běh bez "
                       "intenzity, a jen když se při tom cítíte dobře. Kdyby přišla horečka nebo bolest svalů, odpočinek.")
    elif ill:
        reasons.append("Hlásíte nemoc — dnes odpočinek. Při horečce, bolesti svalů nebo kašli z hrudníku netrénujte, "
                       "k tréninku se vraťte postupně až den po odeznění horečky.")
    elif ill_watch:
        what, when = _ill_what(ill_sig)
        reasons.append(f"Hodinky ukazují {what} {when} — bývá to první známka nemoci, ale i únavy, alkoholu "
                       "nebo horka. Dnes jen lehce a bez intenzity; "
                       + ("v check-inu jste žádné příznaky nehlásili, zítra se to ukáže." if ill_sig.get("answer") == "none"
                          else "check-in se zeptá na příznaky."))
    elif pain > 5:
        reasons.append(f"Bolest {pain}/10{f' · {pain_site}' if pain_site else ''} — dnes jen velmi volně nebo jiný sport, "
                       "který nebolí. Pokud potrvá, proberte ji s fyzioterapeutem.")
    elif pain_mod:
        reasons.append(f"{pain_why}{f' · {pain_site}' if (pain >= 3 and pain_site) else ''} — odlehčit: běh jen kratší "
                       "a volnější, po rovině nebo měkkém povrchu, bez dlouhého běhu a intenzity.")
    if xt_pick:
        reasons.append(f"Místo běhu dnes {types[xt_pick]['label'].lower()}"
                       + (f" — {', '.join(xt['sites'])} při něm není zatížené" if xt else "")
                       + ". Jen pokud při tom nic nebolí; ranní check-in ukáže, jestli to tělu sedlo.")
    if pain >= 1 and not pinfo["checkedIn"]:
        reasons.append("Bolest ze včerejška platí, dokud nevyplníte dnešní check-in — když bude ráno klid, "
                       "doporučení se uvolní.")
    if rec_cleared and not pain_mod:
        reasons.append(f"Opakovaná bolest ({recurring['site']}, {recurring['days']}× za 28 dní) se uklidnila, "
                       "trénink jde podle plánu" + (", zatím bez navyšování nad 100 %." if rec_hold else "."))
    if race and not override:
        d = race["daysSince"] + 1
        reasons.append(f"Zotavení po závodním úsilí {_cz(race['km'])} km ({', '.join(race['why'])}) — den {d} z {race['days']}: "
                       + ("odpočinek nebo velmi volný pohyb." if race_rest else "bez intenzity a dlouhého běhu."))
    if typ == "volno" and not override and vol_max is not None and vol_max < MIN_RUN_KM:
        lim = vw["limitedBy"]
        if lim == "week":
            reasons.append(f"Týdenní cíl je splněný (od pondělí {_cz(vw['done'])} z {_cz(vw['budget'])} km) — dnes volno.")
        elif lim == "7d" and vw.get("absorbedMax") is not None:
            reasons.append(f"Nevstřebaná zátěž z posledních dní {_cz(vw['absorbed'])} km je na stropu týdenní kapacity "
                           f"({_cz(vw['absorbedMax'])} km), dnes volno. Starší běhy se počítají jen zčásti, jak tělo zátěž vstřebává.")
        elif lim == "7d":
            reasons.append(f"Posledních 7 dní {_cz(vw['done7'])} km — na stropu vaší týdenní kapacity "
                           f"({_cz(vw['ceiling7'])} km), dnes volno.")
        elif lim == "systemic" and vw["bound"] == "plan":
            sw = week["systemic"]
            reasons.append(f"Týdenní cíl celkové zátěže (tep × čas ze všech aktivit) je splněný — od pondělí "
                           f"{_cz(sw['done'], 0)} z {_cz(sw['budget'], 0)} bodů, dnes volno. Je to plán týdne, ne strop: "
                           + (f"do bezpečnostního stropu zbývá {_cz(sw['safeMax'], 0)} bodů." if sw.get("safeMax")
                              else "bezpečnostní strop je také vyčerpaný."))
        elif lim == "systemic":
            reasons.append("Nevstřebaná celková zátěž (tep × čas ze všech aktivit) je na stropu týdenní kapacity — dnes volno.")
        else:
            reasons.append("Na dnešek už nezbývá objem — dnes volno, případně jiný sport bez nárazů.")
    parts = cap["readiness"].get("parts") or {}
    after = cap["readiness"].get("afterSession") or {}
    day_bits = [b for b in (
        after.get("nt") and f"pohyb mimo trénink nad obvyklý den (+{after['nt']['excess']} bodů zátěže)",
        after.get("stress") and f"{after['stress']['min']} min zvýšeného tepu v klidu") if b]
    if after.get("dayDrop") and day_bits:
        reasons.append(f"Den mimo trénink ({', '.join(day_bits)}) ubral připravenosti {after['dayDrop']} "
                       f"{'bod' if after['dayDrop'] == 1 else 'body' if after['dayDrop'] < 5 else 'bodů'}.")
    if after.get("sessionDrop") and (after.get("today") or after.get("carry")):
        src = after.get("today") or after.get("carry") or {}
        what = ", ".join(f"{x['title'] or x['sport']} {x['min']} min" for x in src.get("sessions", [])[:2] if x.get("min"))
        reasons.append((f"Po dnešním tréninku ({what}; {src.get('band')}) je připravenost {rscore} % (ráno "
                        f"{cap['readiness'].get('morningScore')} %) — další náročný trénink dnes už ne."
                        if after.get("today") else
                        f"Včerejší náročný trénink ({what}) ještě doznívá — bez nočních dat počítáme s polovinou "
                        f"jeho vlivu, připravenost {rscore} %.")
                       + " Zítra ji upřesní noční HRV, klidový tep a spánek.")
    part_lbl = {"hrv": "nižší HRV", "rhr": "vyšší klidový tep", "sleep": "kratší spánek", "sleepQuality": "víc bdění v noci",
                "soreness": "svalová bolest", "fatigue": "únava", "stress": "stres mimo trénink"}
    low = [part_lbl[k] for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v > 0.1 and k in part_lbl]
    mscore = cap["readiness"].get("morningScore", rscore) if after.get("drop") else rscore   # the night's part
    if mscore < 90 and low:
        reasons.append(f"Připravenost {'ráno ' if after.get('drop') else ''}{mscore} % ({', '.join(low[:3])} proti vaší "
                       "normě) — dnešní stropy jsou úměrně nižší"
                       + (", bez tvrdého tréninku a dlouhého běhu." if rscore < READY_QUALITY else "."))
    elif typ == "volno" and not override and gscore >= READY_EXTRA_EASY:
        opt = [x for x in (f"krátký regenerační běh do {_cz(extra_cap)} km" if extra_easy else None,
                           f"lehké kolo do {types['kolo']['durationMin'][1]} min"
                           if (kolo_extra and types["kolo"]["allowed"]) else None) if x]
        reasons.append(f"Připravenost {rscore} % — tělo je zregenerované, "
                       + ("volno je kvůli zátěži z posledních dní, kterou tělo ještě vstřebává."
                          if (vw["bound"] == "safety" and vol_max is not None and vol_max < MIN_RUN_KM) else
                          "volno je kvůli týdennímu plánu, ne kvůli únavě.")
                       + (f" Pokud máte chuť, {' nebo '.join(opt)} nic nezhorší." if opt else ""))
    if gscore < rscore:
        reasons.append(f"Dnešní check-in ({ci_note}) doporučení snižuje, jako by připravenost byla {gscore} % místo {rscore} %"
                       + (", proto bez tvrdého tréninku a dlouhého běhu" if gscore < READY_QUALITY <= rscore else "")
                       + ". Do Skóre se check-in počítá jen v Příznacích.")
    for w in ro.get("warnings") or []:            # plan B4: a race too close to a maximal effort / race-day state
        if w["kind"] != "race_day" or race_today or w["gap"] == 1:
            reasons.append(w["text"])
    if heat and heat["stage"] != "adapted" and not override and typ not in ("volno",):
        reasons.append(f"Dnes pocitově až {heat['feelsMax']} °C a za posledních 14 dní jste v horku běželi {heat['hot14']}× — "
                       "tep bude vyšší než obvykle, to není ztráta kondice. Řiďte se tepem, ne tempem"
                       + (", kvalitu raději v chladnější části dne." if heat["stage"] == "new" else "."))
    shoe_tr = ((cap or {}).get("shoes") or {}).get("transition")
    if shoe_tr and not override and typ not in ("volno", "kolo", "voda"):
        why_s = {"minimal": "minimalistická bota",
                 "drop": (f"nižší drop ({_cz(shoe_tr['dropFrom'], 0)} → {_cz(shoe_tr['dropTo'], 0)} mm)"
                          if shoe_tr.get("dropFrom") is not None else f"nízký drop ({_cz(shoe_tr['dropTo'], 0)} mm)"),
                 "carbon": "závodní bota s karbonovou deskou"}[shoe_tr["kind"]]
        reasons.append(f"Nová obuv {shoe_tr['name']} ({why_s}) od {_dm(shoe_tr['since'])}: lýtka, Achillovy šlachy a chodidla "
                       f"si na ni zvykají, proto jsou do {_dm(shoe_tr['until'])} rezervy na běh užší. Střídejte ji s dosavadní "
                       "obuví a začněte kratšími běhy"
                       + (" — při vyšší hmotnosti je přechod rizikovější (Fuller et al., 2017)." if shoe_tr.get("heavy") else
                          " (Fuller et al., 2017)." if shoe_tr["kind"] != "carbon" else "."))
    if new_block and not override:
        reasons.append(f"Nový silový blok od {_dm(new_block['since'])}: první 2–3 týdny bývají nohy těžké, běh je proto "
                       "o desetinu kratší (Rønnestad & Mujika, 2014).")
    under = (cap.get("margins") or {}).get("underconditioned")
    if under and not override and not novice:
        reasons.append(f"Za poslední 4 týdny průměrně {_cz(under['runsPerWeek'])} běhu a {under['minPerWeek']} min týdně — "
                       "při malé běžecké základně stačí ke zranění menší skok, proto jsou rezervy užší"
                       + (" (a kvůli dřívějšímu zranění ještě víc)" if under.get("withInjury") else "")
                       + ". Nejdřív přidávejte četnost krátkých lehkých běhů, teprve potom délku dlouhého běhu "
                         "(Abrahamson et al., 2025).")
    if cluster and not override:
        reasons.append("Poslední týdny se sešla únava, nemoc nebo pomalejší zotavení najednou — to má mnoho možných "
                       "příčin, proto to stojí za to probrat s fyzioterapeutem nebo lékařem.")
    if provisional:
        reasons.append("Ještě nemáme dnešní spánek a HRV — doporučení je předběžné a po synchronizaci se upřesní.")
    if mode == "return":
        reasons.append(f"Návrat po zranění ({rtr['site']}): {rtr['week']}. týden ze 3 — cíl {round(factor * 100)} % "
                       f"průměrného týdne před zraněním" + (f", bez intenzity do {_dm(rtr['noQualityUntil'])}" if rtr["noQuality"] else "")
                       + (". Řiďte se i plánem návratu od fyzioterapeuta." if rtr["physioPlan"] else "."))
    elif mode == "deload":
        reasons.append("Zátěž je zvýšená — odlehčovací týden (55 % minulého týdne), dokud neklesne.")
    elif mode == "taper":
        reasons.append(f"{(next_a.get('name') or 'Cílový závod')} za {days_to_race} dní — "
                       f"ladění formy, objem ×{_cz(factor, 2)} referenčního týdne.")
    elif mode == "recovery":
        reasons.append("4. týden cyklu — odlehčovací týden (55 % vrcholového týdne), ať se trénink vstřebá.")
    elif mode == "build":
        reasons.append(f"{cycle['pos']}. týden cyklu — cíl {round(factor * 100)} % referenčního týdne "
                       f"({_cz(cycle['refKm'])} km).")
    elif mode == "learning" and novice:
        reasons.append(f"Prvních 6 týdnů (máte {hist_days} dní dat) platí opatrné výchozí pravidlo aplikace: týdenní objem "
                       "nejvýš o 10 % víc než minulý týden, dlouhý běh nejvýš o 10 % delší než nejdelší za 30 dní. Je to "
                       "vlastní pojistka aplikace, ne ověřená hranice — výzkum žádné univerzální tempo navyšování nepotvrdil. "
                       "Intenzita a převýšení zatím nic neblokují — osobní kapacitu a cyklus poznáme z dalších týdnů.")
    elif mode == "learning":
        reasons.append("Čtyřtýdenní cyklus nastavíme po 4 týdnech dat — zatím je cílem vaše týdenní kapacita.")
    if cycle["manual"]:
        reasons.append(f"Tento týden jste ručně zvolili {cycle['pos']}. týden cyklu — příští týden se cyklus nastaví "
                       "sám podle toho, jak týden skutečně proběhne.")
    if typ == "kolo" and not xt_pick:
        reasons.insert(0, "Běžecký objem je na dnešek vyčerpaný, ale celková zátěž má rezervu — kolo zatíží srdce "
                          "a plíce bez nárazů do nohou.")
    if carry and not override:
        reasons.append(f"Posilování nohou {_dm(carry['date'])}" + (f" (náročnost {carry['rpe']}/10)" if carry["rpe"] else "")
                       + ": 24–48 hodin po něm bývá horší výkon v intenzitě, strop minut v Z4+ je dnes nižší.")
    if (pain_mod or pain > 5) and not override:
        reasons.append("Místo běhu můžete zvolit plavání, pokud při tom nic nebolí.")
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

    strength_due = bool(types["posilování"]["allowed"] and s_done < s_target and typ != "kolo")
    rank = rank_types(types, typ, strength_due, xt)

    done = None
    if today_runs:
        done = {c: week[c]["doneToday"] for c in CHS}
        done["runs"] = len(today_runs)

    # ---- owner feedback 2026-10-10: this calendar week day by day, by sport (the plan's
    # running total) — the same daily loads as `done`, split by where they came from
    nt_days = C.nontraining_daily(db, rid)
    week_days = []
    for k in range(7):
        d = (ws + timedelta(days=k)).isoformat()
        by = {c: {} for c in (*CHS, "systemic")}
        if d <= t_iso:
            for s in sessions:
                if s["date"] != d:
                    continue
                src = "run" if s["run"] else s.get("sport") if s.get("sport") in ("cycling", "swimming", "strength") else "other"
                for c in by:
                    v = s["exp"].get(c)
                    if not v or (c in ("volume", "descent", "ascent") and not s["run"]) \
                            or (c == "intensity" and not (s["run"] or s.get("sport") in C.CROSS_CARDIO)):
                        continue
                    by[c][src] = by[c].get(src, 0.0) + v
            if nt_days.get(d):
                by["systemic"]["daily"] = nt_days[d]
        week_days.append({"date": d, "by": {c: {s: _r(v, C.CHANNELS[c]["dec"]) for s, v in b.items()} for c, b in by.items()}})

    # ---- owner feedback 2026-10-10: the outlook for tomorrow (outlook.py)
    def next_target(c):
        wc = week[c]
        if novice and c != "volume":
            return None
        t = wc["budget"]
        if pos_now and mode in ("build", "recovery"):
            f2 = CYCLE[1] * CYCLE[3] if pos_now == 4 else CYCLE[pos_now % 4 + 1]
            ref_c = (reference(c) if cyc else None) or ((ch.get(c) or {}).get("week") or {}).get("cap")
            t = None if ref_c is None else ref_c * f2
        return t if (t is None or wc["ceiling7"] is None) else min(t, wc["ceiling7"])
    all_rate = [s["exp"]["systemic"] / s["km"] for s in hist if s["km"] and s["exp"].get("systemic")]

    def med_rate(c):
        xs = [s["exp"][c] / s["km"] for s in hist if s["km"] and s["exp"].get(c) is not None]
        return E.median(xs) if xs else None
    conv = {"perKm": None if novice else per_km, "runPerKm": per_km or (E.median(all_rate) if all_rate else None),
            "z4PerMin": z4pm, "easyPerMin": (per_km * 60 / easy_pace) if (per_km and easy_pace) else None,
            "perMinRide": per_min_c, "perMinSwim": 4 * k_srpe,
            "descPerKm": med_rate("descent"), "ascPerKm": med_rate("ascent"),
            "hillP90": None if novice else hill_p90}
    presets = [{"key": "none", "kind": None, "act": {}}]
    rec_t = types.get(typ) or {}
    if typ in ("regenerace", "lehký", "dlouhý", "kvalitní") and rec_t.get("allowed") and not after_done:
        presets.append({"key": "rec", "kind": typ,
                        "act": {"runKm": (rec_t.get("km") or {}).get("hi") or 0.0,
                                "z4": ((rec_t.get("z4Target") or {}).get("hi") or 0) if typ == "kvalitní" else 0}})
    elif typ in ("kolo", "voda") and rec_t.get("allowed") and not after_done:
        presets.append({"key": "rec", "kind": typ,
                        "act": {("rideMin" if typ == "kolo" else "swimMin"): (rec_t.get("durationMin") or (0, 0))[1]}})
    if extra_easy and types["regenerace"]["allowed"]:
        presets.append({"key": "extra", "kind": "regenerace", "act": {"runKm": types["regenerace"]["km"]["hi"] or 0.0}})
    if typ != "kolo" and types["kolo"]["allowed"]:
        presets.append({"key": "kolo", "kind": "kolo", "act": {"rideMin": types["kolo"]["durationMin"][1]}})
    today_hard = any(is_hard(s) for s in cardio if s["date"] == t_iso)
    outlook = O.build(cap=cap, week=week, today=today, plan_next={c: next_target(c) for c in week},
                      conv=conv, novice=novice, drift=drift, presets=presets, min_run=MIN_RUN_KM, base_km=base_km,
                      last_hard_age=0 if today_hard else days_since_hard, hard_gap=HARD_GAP_DAYS,
                      ready_quality=READY_QUALITY)

    # ---- what the week's plan (Monday morning report, week_plan.py) needs from today's context
    longest30 = max((s["km"] or 0 for s in runs if 0 < (today - _d(s["date"])).days <= 30), default=0)
    plan_ctx = {
        "past": {c: {(today - timedelta(days=k)).isoformat(): _r(daily[c].get((today - timedelta(days=k)).isoformat(), 0.0),
                                                                C.CHANNELS[c]["dec"]) for k in range(1, 7)}
                 for c in ("volume", "intensity", "descent", "ascent", "systemic")},
        "lastHard": max(hard_dates) if hard_dates else None,
        "hardThisWeek": sorted({d for d in hard_dates if d >= ws.isoformat()}),
        "todayHard": any(is_hard(s) for s in cardio if s["date"] == t_iso),
        "hardCap": hard_cap, "readiness": gscore, "novice": novice,
        "painMod": bool(pain_mod), "painWhy": pain_why or None, "pain": pain or 0,
        "ill": bool(ill) and not ill_light, "illLight": ill_light, "illWatch": ill_watch,
        "drift": drift, "deload": load >= 25, "overreaching": a.get("quadrant") in ("overreaching", "critical"),
        "raceRecoveryUntil": ((_d(race["date"]) + timedelta(days=race["days"])).isoformat() if race else None),
        "noQualityUntil": rtr_all["noQualityUntil"] if (rtr_all and rtr_all["noQuality"]) else None,
        "races": [{"date": x["date"], "name": x.get("name"), "km": x.get("km"), "priority": x.get("priority")}
                  for x in ro.get("upcoming") or [] if 0 <= (x.get("daysTo") or -1) <= 13],
        "perKm": _r(per_km, 2), "perMinRide": _r(per_min_c, 3), "z4PerMin": _r(z4_trimp_per_min(tb), 3),
        "kSrpe": _r(k_srpe, 3), "rideHr": list(hr_c),
        "rides8w": sum(1 for s in sessions if s.get("sport") == "cycling" and 0 <= (today - _d(s["date"])).days <= 56),
        "longest30": _r(longest30), "easyKm": _r(easy_km), "easyPace": _r(easy_pace, 0),
        "ceilRun": {c: (ch.get(c) or {}).get("ceilingSession") for c in CHS},
        "noSpeedWeeks": bool(nsw) and not novice,
        "kolo": not ((xt or {}).get("kolo") == "avoid" or (override or {}).get("kind") == "red_flag"),
        "koloNote": ((xt or {}).get("koloNotes") or [None])[0],
    }

    return {
        "date": t_iso, "engine": "v3", "type": typ, "typeLabel": TYPE_LABEL[typ],
        "provisional": provisional, "override": override, "referral": decision if referral else None,
        "pain": pain or 0, "readiness": ready, "readinessScore": rscore, "checkinReadiness": gscore if gscore < rscore else None,
        "types": types,
        "axes": {"load": load, "mech": a.get("mech") or 0, "threshold": E.QUAD_THRESHOLD},
        "outlook": outlook,
        "week": {"channels": week, "mode": mode, "progression": round(factor, 3), "cycle": cycle, "days": week_days,
                 "start": ws.isoformat(),
                 "novice": {"days": hist_days, "until": (today + timedelta(days=NOVICE_DAYS - hist_days)).isoformat()} if novice else None},
        "pattern": {**pat, "runDayNames": [WD[w] for w in pat["runDays"]],
                    "longDayName": WD[pat["longDay"]] if pat["longDay"] is not None else None,
                    "hardDayNames": [WD[w] for w in pat["hardDays"]], "easyKm": _r(easy_km), "easyPace": _r(easy_pace, 0)},
        "reasons": reasons[:5], "done": done, "rank": rank, "afterDone": after_done,
        "heat": heat, "hardWeek": {"done": hard7, "cap": hard_cap},
        "strength": {"done": s_done, "target": s_target, "today": s_today, "lastAge": s_last_age, "newBlock": new_block,
                     "suggestToday": strength_due,
                     "carry": carry},
        "zones": cap.get("zones"), "hrSource": "fit" if fit else "fallback",
        "planCtx": plan_ctx,
    }
