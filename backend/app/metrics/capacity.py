"""Engine v3 ("Kapacitní") — the per-runner LOAD CAPACITY model.

One model, two views: the Zátěž axis scores how far recent training went past
what this runner has *demonstrated they tolerate* (this module), and the Trénink
tab (phase 2) spends the remaining headroom. Both read the same numbers, so they
can't contradict each other.

Channels (each scored per run AND per rolling 7 days):
  volume     km of running                               evidence B (RUNSAFE 2025, Nielsen 2014)
  intensity  minutes at ≥ 80 % heart-rate reserve (Z4+)  evidence B (effort, Neal 2024)
  descent    descent metres, weighted by steepness       evidence C (eccentric load, repeated-bout effect)
  ascent     ascent metres                               evidence C (calf / Achilles)
  systemic   HR training load (TRIMP) across all sports  evidence B (internal load)

Capacity = demonstrated tolerance:
  per run  — the largest single exposure in the last 30 days (runs 30–90 days old
             count with a 30-day half-life), ignoring runs that were followed
             within 72 h by running-relevant pain ≥ 3/10 (not actually tolerated);
             needs ≥ 3 prior runs in 30 days, else "unknown" (not scored).
             A jump (> 1.3× that run's own capacity) doesn't count for 14 days
             and afterwards only fully when a pain-free report confirmed it.
  per week — max(the average week of the previous 4 weeks, 0.9 × the best
             pain-free 7-day window of the previous 6 weeks, spike weeks
             > 1.3× their preceding 4 weeks excluded); needs 3 weeks.

Readiness (0.7–1.0) scales capacity DOWN on a poorly recovered day: that night's
HRV and resting HR against the runner's own 28-day baseline and sleep shortfall
(v0.9.3: check-in items are scored on Příznaky only). A normal run on a bad night therefore counts as an
exceedance; the same run on a good night doesn't. v0.10.0: the cardio channels take
the full factor, the musculoskeletal ones HRV and resting HR at half weight (see
channel_readiness). Injury history (frailty) shrinks the safety margins.

Body state (v0.10.0, see body_state): running-relevant pain and injury act on the
capacity itself by the pain-monitoring model (no margin while pain stays inside it,
one step back when it's over, no running on worse morning pain or an active injury,
the graded return caps the weekly capacity). Příznaky keeps its pain points.

Absorption (railway#100): a run's points and the weekly load fade night by night
instead of holding until the run leaves the 7-day window. The weekly figure that is
scored is an exponentially weighted acute load (Williams et al. 2017), equal to the
plain 7-day sum on steady training. Muscles / tendons (volume, descent, ascent)
absorb on a fixed half-life of 3.5 nights, the systemic side (HR load, Z4+ minutes)
by that night's readiness (2 nights at 90 %, 3 at 75 %, 5 at 60 %, 8 at 45 % and below, interpolated). The half-lives are working
assumptions of the product team, not measured values.

Scoring: ratio r = exposure / (capacity × readiness). Points start above the
margin (+10 % per run, +15 % per week), step smoothly up to a plateau (12–14 b) that
holds to 2×, then climb (24 b at 2.5×, up to 40 b) — the Garmin-RUNSAFE shape (see
band_points) — times the channel's evidence weight. The worst channel counts fully, the second 50 %, the rest 25 % —
so a run that is long AND hilly AND hard scores above any one of those alone,
without the same event being counted three times over.
"""
import math
from bisect import bisect_left
from datetime import date, timedelta
from functools import lru_cache

from . import data as D
from . import engine as E
from . import terrain

CHANNELS = {
    "volume": {"label": "Objem", "unit": "km", "dec": 1, "w": 1.0, "grade": "B",
               "floor_s": 3.0, "floor_w": 10.0},
    "intensity": {"label": "Intenzita", "unit": "min v Z4+", "dec": 0, "w": 0.9, "grade": "B",
                  "floor_s": 5.0, "floor_w": 10.0},
    "descent": {"label": "Klesání", "unit": "m", "dec": 0, "w": 0.8, "grade": "C",
                "floor_s": 50.0, "floor_w": 150.0},
    "ascent": {"label": "Stoupání", "unit": "m", "dec": 0, "w": 0.5, "grade": "C",
               "floor_s": 50.0, "floor_w": 150.0},
    "systemic": {"label": "Celková zátěž", "unit": "j.z.", "dec": 0, "w": 0.7, "grade": "B",
                 "floor_s": 30.0, "floor_w": 100.0},
    # Strength sessions (session RPE × minutes × body-region weight). Its own local
    # load with its own capacity, so a sudden first plyometric block shows up; low
    # weight because only indirect evidence supports it (grade C). Floors = one
    # 30-min session at RPE 4 / two a week (working assumptions).
    "strength": {"label": "Silová zátěž", "unit": "sRPE·min", "dec": 0, "w": 0.5, "grade": "C",
                 "floor_s": 120.0, "floor_w": 240.0},
}
RUN_CHANNELS = ("volume", "intensity", "descent", "ascent")
# v0.10.5 (feedback railway#192) — hard minutes are cardiovascular work in any sport: a
# cycling or swimming session's minutes in Z4+, against that sport's own heart-rate max
# (engine.sport_hr_max), go into Intenzita too — the weekly load, the per-session
# capacity and the spacing of hard days. The running tissues stay with running.
CROSS_CARDIO = ("cycling", "swimming")

MARGIN_SESSION = 0.10   # RUNSAFE: risk starts rising above +10 % of the 30-day longest run
MARGIN_WEEK = 0.15      # Nielsen 2014: > 30 %/week clearly risky; 10–15 % conservative
CAP_WINDOW, CAP_MAX_AGE, CAP_HALF_LIFE = 30, 90, 30.0   # days
MIN_PRIOR = 3           # prior runs in 30 days needed to know a per-run capacity
PAIN_AFTER = 3          # days after a run in which reported pain marks it "not tolerated"
BREAK_DECAY = 0.85      # v0.8.4: a best week older than 2 weeks counts 15 % less per extra week, so after a break an old peak can't carry the capacity (Gabbett 2016: spikes after troughs; rate = working assumption)
JUMP_RATIO = 1.3        # a session / week this far over its capacity is a jump, not proof (prevention plan B1)
JUMP_HOLD_DAYS = 14     # …a jump doesn't raise capacity for this long…
JUMP_UNCONFIRMED = 0.5  # …and afterwards counts fully only when a pain-free report confirmed it
READINESS_FLOOR = 0.7
Z4_HRR = 0.80           # Z4 starts at 80 % heart-rate reserve (Karvonen)
ECC_DEFAULT = 1.16      # descent weighting without a profile ≈ a typical −5 % descent
COMBO = (1.0, 0.5, 0.25, 0.25, 0.25, 0.25)
# Feedback railway#100 — load is absorbed night by night instead of vanishing when a
# run leaves the 7-day window. Half-lives (in nights) are the product team's working
# assumptions, not measured values: muscles / tendons / bone (volume, descent,
# ascent) on a fixed biological clock that HRV and sleep don't show, the systemic
# side (all-sport HR load, hard minutes) by how well that night recovered.
HALF_MSK = 3.5
CARDIO = ("systemic", "intensity")
HALF_CARDIO_REF, HALF_NO_DATA = 3.0, 3.5
RESIDUAL_CAP = 1.25     # poor nights may keep at most 25 % more than the nominal absorption would
ABSORB_DAYS = 42


def _k(half):
    """Share absorbed per night for a half-life in nights."""
    return 1 - 0.5 ** (1 / half)
TOP_N = {"intensity": 3}   # per-run capacity = mean of the N largest tolerated sessions (else the max)
ZONES = (("Z1", 0.50, 0.60), ("Z2", 0.60, 0.70), ("Z3", 0.70, 0.80), ("Z4", 0.80, 0.90), ("Z5", 0.90, 1.00))
# v0.9.0 — with a measured lactate-threshold heart rate (profile) the zones follow it
# instead of a percentage of heart-rate reserve from an estimated maximum: running
# zones as % of LTHR (Friel): Z4 95–99 %, Z5 from 100 %. Z1 starts at 75 % for display.
LTHR_ZONES = (("Z1", 0.75, 0.85), ("Z2", 0.85, 0.90), ("Z3", 0.90, 0.95), ("Z4", 0.95, 1.00), ("Z5", 1.00, None))
# …and heart rate lags behind short intervals (Seiler, 2010), so hard minutes also
# come from the run's segments: a flat-equivalent speed at or above the speed the
# runner's own HR↔speed line puts at the Z4 heart rate. The larger count is kept.
PACE_Z4_MAX_DOWN = -0.02   # downhill segments are fast without being hard: not counted


# ------------------------------------------------------------------ scoring
# v0.9.0 — the curve follows the Garmin-RUNSAFE dose-response for a single run over the
# longest of the last 30 days (Frandsen et al., 2025): HRR 1.64 at +10–30 %, 1.52 at
# +30–100 %, 2.28 above +100 %. Risk steps up just past the margin and then stays
# roughly flat until the run is double, so points rise smoothly to a plateau (in
# proportion to ln HRR: 0.49 → ~12–14 points) and climb again past 2× (ln 2.28 = 0.82
# → ~24 points at 2.5×). The old ramp scored a +20 % run at ~3 points, a tenth of a
# +150 % run, while the hazards differ by less than half. Scale factors = working
# assumptions; the shape is the evidence. The step spans the +10–40 % band (not a
# cliff: its slope stays under the engine's no-jump bound of 51 points per 1.0×).
BAND_RAMP = 0.30          # width of the smooth step above the margin
BAND_PLATEAU = (12.0, 14.0)
BAND_SLOPE_2X = 20.0      # points per 1.0× beyond 2×
BAND_MAX = 40.0


def band_points(r, margin):
    """Points for an exposure/capacity ratio, before the channel weight: 0 up to the
    margin, a smooth step to the plateau, nearly flat to 2×, then rising. Continuous
    and non-decreasing (Carey et al., 2018)."""
    if r is None or r <= 1 + margin:
        return 0.0
    x = r - 1 - margin
    if x <= BAND_RAMP:
        t = x / BAND_RAMP
        return BAND_PLATEAU[0] * t * t * (3 - 2 * t)          # smoothstep
    top = 1 + margin + BAND_RAMP
    if r <= 2.0:
        return BAND_PLATEAU[0] + (BAND_PLATEAU[1] - BAND_PLATEAU[0]) * (r - top) / max(2.0 - top, 1e-9)
    return min(BAND_PLATEAU[1] + (r - 2.0) * BAND_SLOPE_2X, BAND_MAX)


def latent_points(r, age):
    """A big exceedance 1–4 weeks ago still counts (IOC 2016: injury risk peaks
    1–4 weeks after a rapid rise), decaying linearly to zero at 28 days. Since
    railway#100 it is a floor from the day after the run (the acute part of the
    same run is absorbed night by night on top of it)."""
    if r is None or r <= 1.3 or age < 1 or age >= 28:
        return 0.0
    # capped first, then scaled, so a huge jump fades linearly from day 7 instead
    # of holding the cap for three weeks and dropping at the end
    return min((r - 1.3) * 22, 16.0) * min(1.0, (28 - age) / 21)


# Plan phase 2B: the half-life is interpolated linearly between these anchors
# (readiness score → nights) instead of jumping at 90 / 75 / 60.
HALF_ANCHORS = ((90, 2.0), (75, 3.0), (60, 5.0), (45, 8.0))


def half_for_readiness(score):
    """Systemic half-life in nights for a readiness score, continuous and non-increasing in the score."""
    pts = HALF_ANCHORS
    if score >= pts[0][0]:
        return pts[0][1]
    for (s1, h1), (s2, h2) in zip(pts, pts[1:]):
        if score >= s2:
            return h1 + (s1 - score) / (s1 - s2) * (h2 - h1)
    return pts[-1][1]


def night_rates(ch, days, ready, nights):
    """{day: share of the residual absorbed during the night before that morning}."""
    out = {}
    for d in days:
        if ch not in CARDIO:
            out[d] = _k(HALF_MSK)
            continue
        rd = ready.get(d)
        if d not in nights and not (rd and rd[1]):
            out[d] = _k(HALF_NO_DATA)
            continue
        score = rd[2] if rd else 100
        out[d] = _k(half_for_readiness(score))
    return out


def residual_week(daily, days, rates, ch):
    """Weekly-equivalent load still unabsorbed today: an exponentially weighted acute
    load (Williams et al. 2017) whose nightly decay follows `rates`. On steady
    training it equals the plain 7-day sum, and after the last run it falls every
    night instead of holding for a week and then dropping at once."""
    k_ref = _k(HALF_CARDIO_REF if ch in CARDIO else HALF_MSK)
    level = nominal = 0.0
    for d in days:
        x = daily.get(d, 0.0)
        level = level * (1 - rates[d]) + k_ref * x
        nominal = nominal * (1 - k_ref) + k_ref * x
    w, w_nom = 7 * level, 7 * nominal
    return min(w, w_nom * RESIDUAL_CAP) if ch in CARDIO else w


def absorbed_left(rates, since, today_iso, days):
    """Share of an exposure on `since` still unabsorbed this morning."""
    left = 1.0
    for d in days:
        if since < d <= today_iso:
            left *= 1 - rates[d]
    return left


def combine(scores: dict) -> dict:
    """Worst channel counts fully, the 2nd 50 %, the rest 25 % each."""
    order = sorted(scores, key=lambda c: -scores[c])
    return {c: scores[c] * COMBO[i] for i, c in enumerate(order)}


# ------------------------------------------------------------------ exposures
def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def zone_bounds(hrmax, rhr, lthr=None) -> list:
    """[(zone, lo bpm, hi bpm)] — by % of LTHR when the runner entered a plausible
    one, else by heart-rate reserve."""
    if lthr and rhr < lthr < hrmax:
        return [(z, lthr * a, hrmax if b is None else lthr * b) for z, a, b in LTHR_ZONES]
    return [(z, rhr + a * (hrmax - rhr), rhr + b * (hrmax - rhr)) for z, a, b in ZONES]


def z4_threshold(hrmax, rhr, lthr=None) -> float:
    return zone_bounds(hrmax, rhr, lthr)[3][1]


def z4_minutes(a, hist, hrmax, rhr, lthr=None):
    """Minutes at ≥ Z4. From the stream's HR histogram when fetched (exact), else
    from the run's thirds or its average HR, assuming HR spreads around the mean
    (so a tempo run averaging just under Z4 still counts its hard minutes)."""
    if hrmax <= rhr:
        return None
    thr = z4_threshold(hrmax, rhr, lthr)
    if hist:
        return sum(s for b, s in hist.items() if float(b) + 1.0 >= thr) / 60.0
    dur = a.duration_min or 0
    if dur <= 0:
        return None
    th = a.hr_thirds
    if th and len(th) == 3 and all(th):
        sdv = 0.04 * (hrmax - rhr)
        return sum(dur / 3 * (1 - _phi((thr - h) / sdv)) for h in th)
    if a.avg_hr:
        return dur * (1 - _phi((thr - a.avg_hr) / (0.06 * (hrmax - rhr))))
    return None


def zone_minutes(a, hist, hrmax, rhr, lthr=None):
    """Minutes in Z1–Z5 (zone_bounds) — exact from the stream's HR histogram, else
    estimated like z4_minutes (HR spread around the thirds / the average). Z4 + Z5
    equals z4_minutes. None without heart rate."""
    if hrmax <= rhr:
        return None
    bounds = [(lo, hi) for _, lo, hi in zone_bounds(hrmax, rhr, lthr)]
    bounds[-1] = (bounds[-1][0], math.inf)
    out = [0.0] * len(ZONES)
    if hist:
        for b, sec in hist.items():
            h = float(b) + 1.0
            for i, (lo, hi) in enumerate(bounds):
                if lo <= h < hi:
                    out[i] += sec / 60.0
                    break
        return out
    dur = a.duration_min or 0
    th = a.hr_thirds
    if dur <= 0:
        return None
    if th and len(th) == 3 and all(th):
        parts = [(dur / 3, h, 0.04 * (hrmax - rhr)) for h in th]
    elif a.avg_hr:
        parts = [(dur, a.avg_hr, 0.06 * (hrmax - rhr))]
    else:
        return None
    for d, h, sdv in parts:
        for i, (lo, hi) in enumerate(bounds):
            out[i] += d * ((1.0 if hi == math.inf else _phi((hi - h) / sdv)) - _phi((lo - h) / sdv))
    return out


def pace_z4_minutes(segments, v_thr: float) -> float:
    """Minutes of segments whose flat-equivalent speed (Minetti cost ratio) is at or
    above `v_thr` m/s; downhill segments are left out."""
    c0 = E.minetti_cost(0.0)
    sec = 0.0
    for sg in segments or ():
        v, g, dur = sg.get("meanSpeed"), sg.get("meanGradient") or 0.0, sg.get("durationS") or 0
        if not v or dur <= 0 or g < PACE_Z4_MAX_DOWN:
            continue
        if v * E.minetti_cost(g) / c0 >= v_thr:
            sec += dur
    return sec / 60.0


_FIT_CACHE: dict = {}


def _fit_at(runs, day: str):
    """hr_speed_fit memoised on the runs it would use (replays ask the same day often)."""
    d0 = _d(day)
    key = (day, tuple((p["date"], p["avgHr"], p["speed"]) for p in runs
                      if 7 <= (d0 - _d(p["date"])).days <= 56 and p["avgHr"] and p["speed"]))
    if key not in _FIT_CACHE:
        if len(_FIT_CACHE) > 20000:
            _FIT_CACHE.clear()
        _FIT_CACHE[key] = hr_speed_fit(runs, day)
    return _FIT_CACHE[key]


def add_pace_intensity(out, segs_by_id, hrmax, rhr, lthr, since: str):
    """Raise each recent run's Z4+ minutes to the pace-based count when that is larger."""
    runs = [s for s in out if s["run"]]
    thr_hr = z4_threshold(hrmax, rhr, lthr)
    for s in runs:
        segs = segs_by_id.get(s["id"])
        if not segs or s["date"] < since:
            continue
        fit = _fit_at(runs, s["date"])
        if not fit:
            continue
        v_thr = (thr_hr - fit[0]) / fit[1]
        pz = pace_z4_minutes(segs, v_thr)
        if pz > (s["exp"].get("intensity") or 0.0) + 0.5:
            s["exp"]["intensity"] = pz
            s["z4Source"] = "pace"


_ECC_CACHE: dict = {}


def _ecc_factor(profile, key=None):
    """weighted / raw descent for a profile (None when it barely descends).
    Memoised per activity — profiles don't change, and history replays ask daily."""
    if key is not None and key in _ECC_CACHE:
        return _ECC_CACHE[key]
    raw, weighted = terrain.descent_weighting(profile)
    val = (weighted / raw) if raw > 5 else None
    if key is not None:
        if len(_ECC_CACHE) > 20000:
            _ECC_CACHE.clear()
        _ECC_CACHE[key] = val
    return val


NT_USUAL_DAYS, NT_USUAL_MIN = 28, 7


def nontraining_daily(db, rid) -> dict:
    """{date: load outside training above the runner's usual day} (all-day heart rate,
    already × NT_WEIGHT; dayload.py) — added to the all-sport channel (Celková zátěž).
    Only the excess over the median of the previous 28 days counts: the usual daily life
    is part of the baseline the capacity was built on (and the history before all-day
    heart rate was imported has none), an unusually active day — moving house, a day on
    the feet — adds. Needs 7 earlier days with all-day data."""
    data = D.of(db, rid)
    days = sorted((m.date[:10], m.nt_load) for m in data.daily if getattr(m, "nt_load", None) is not None)
    out = {}
    for i, (d, v) in enumerate(days):
        lo = (_d(d) - timedelta(days=NT_USUAL_DAYS)).isoformat()
        prev = sorted(x for dd, x in days[:i] if dd >= lo)
        if len(prev) < NT_USUAL_MIN:
            continue
        usual = prev[len(prev) // 2]
        if v > usual:
            out[d] = round(v - usual, 1)
    return out


def run_exposures(db, rid, hrmax, rhr):
    """Every session → {id, date, run, title, km, exp{channel: value|None}}."""
    data = D.of(db, rid)
    lthr = getattr(data.runner, "threshold_hr", None)
    acts = E.all_acts(data, rid, "load")
    ctx = E.load_context(data, rid, acts, hrmax, rhr)
    hists = {st.activity_id: st.quality_json["hrHist"] for st in data.streams
             if st.quality_json and st.quality_json.get("hrHist")}
    fac = {a.id: _ecc_factor(a.elevation_profile, (a.id, len(a.elevation_profile or [])))
           for a in acts if E.is_run(a) and a.elevation_profile}
    facs = [f for f in fac.values() if f]
    default_fac = E.median(facs) if facs else ECC_DEFAULT
    out = []
    for a in acts:
        if not a.started_at:
            continue
        run = E.is_run(a)
        exp = {"systemic": E.session_load(a, hrmax, rhr, ctx) or None}
        if a.sport == "strength":
            exp["strength"] = E.strength_exposure(a, ctx)
        zones = None
        if not run and (a.sport or "") in CROSS_CARDIO and hrmax > rhr:
            hm = ctx["hr"].get(a.sport, hrmax)
            lt = lthr - (hrmax - hm) if lthr else None       # the threshold shifts with the sport's HR max
            exp["intensity"] = z4_minutes(a, hists.get(a.id), hm, rhr, lt)
            zones = zone_minutes(a, hists.get(a.id), hm, rhr, lt)
        if run:
            desc = a.descent_m
            if desc is None and a.elevation_profile:
                desc = terrain.descent_weighting(a.elevation_profile)[0]
            exp["volume"] = a.distance_km or 0.0
            exp["intensity"] = z4_minutes(a, hists.get(a.id), hrmax, rhr, lthr)
            exp["descent"] = (desc or 0.0) * (fac.get(a.id) or default_fac)
            exp["ascent"] = a.ascent_m or 0.0
            zones = zone_minutes(a, hists.get(a.id), hrmax, rhr, lthr)
        out.append({"id": a.id, "date": a.started_at[:10], "run": run, "title": a.title, "sport": a.sport or "running",
                    "heavyLower": E.heavy_lower(a, ctx), "rpe": E.session_rpe(a, ctx),
                    "durationMin": a.duration_min, "strengthFocus": a.strength_focus,
                    "km": a.distance_km, "exp": exp, "avgHr": a.avg_hr,
                    "zoneMin": zones, "zoneExact": bool(hists.get(a.id)),
                    "speed": E._speed_ms(a), "ascPerKm": ((a.ascent_m or 0) + (a.descent_m or 0)) / max(a.distance_km or 1, 0.1),
                    # v0.8.4: heat flag and the grade-adjusted (flat-equivalent) speed
                    "hot": E.hot_run(a), "gSpeed": (E._speed_ms(a) or 0) * E.grade_factor(a) if run else None})
    segs = {st.activity_id: st.segments_json for st in data.streams if st.segments_json}
    if segs:
        since = (E.today_date() - timedelta(days=ITEMS_LOOKBACK)).isoformat()
        add_pace_intensity(out, segs, hrmax, rhr, lthr, since)
    return out


def pain_dates(db, rid) -> set:
    """Days with running-relevant pain ≥ 3/10 (check-ins, run ratings, niggles)."""
    out = set()
    data = D.of(db, rid)
    for c in data.checkins:
        if (c.pain_score or 0) >= 3 and c.submitted_at:
            regions = [p.get("region") for p in (c.pain_points or []) if p.get("region")]
            if not regions or any(E._run_relevant(r) for r in regions):
                out.add(c.submitted_at[:10])
    for f in data.feedback:
        if ((f.pain_during or 0) >= 3 or f.niggle) and f.submitted_at:
            out.add(f.submitted_at[:10])
    return out


@lru_cache(maxsize=8192)
def _d(s):
    return date.fromisoformat(s[:10])


def tolerated(day: str, pain: set) -> bool:
    d0 = _d(day)
    return not any((d0 + timedelta(days=k)).isoformat() in pain for k in range(PAIN_AFTER + 1))


def report_dates(db, rid) -> set:
    """Days with any check-in or run rating — what "confirmed tolerated" needs."""
    data = D.of(db, rid)
    out = {c.submitted_at[:10] for c in data.checkins if c.submitted_at}
    out |= {f.submitted_at[:10] for f in data.feedback if f.submitted_at}
    return out


def confirmed(day: str, reports: set, pain: set) -> bool:
    """A report within 72 h after the session and no running pain ≥ 3 in that time."""
    d0 = _d(day)
    days = [(d0 + timedelta(days=k)).isoformat() for k in range(PAIN_AFTER + 1)]
    return any(d in reports for d in days) and not any(d in pain for d in days)


# ------------------------------------------------------------------ capacity
def _decay(age):
    return 1.0 if age <= CAP_WINDOW else 0.5 ** ((age - CAP_WINDOW) / CAP_HALF_LIFE)


# v0.9.0 — how far back the per-session items have to reach: sessions scored today are
# at most 27 days old, their capacity looks 90 days further back, and whether those
# sessions were jumps is judged against the 90 days before them (without any jump
# discount, so no older flag matters). Older sessions cannot change today's result.
ITEMS_LOOKBACK = 27 + 2 * CAP_MAX_AGE
REPEAT_WINDOW, REPEAT_SIMILAR = 28, 0.85


def channel_items(sessions, ch, pain: set, tol: dict | None = None, reports: set | None = None,
                  active_days: set | None = None, since: str | None = None):
    """Sorted (date, value, tolerated, jump, confirmed) of every session carrying
    channel `ch` — built once per assessment so capacity lookups are a bisect,
    not a full scan. `tol` (day → tolerated) can be shared across channels.

    `jump` (plan B1) = the session was > JUMP_RATIO × the largest tolerated session
    of the 90 days before it. v0.9.0: judged against that UNDISCOUNTED capacity.
    Judging it against the capacity that already halves unconfirmed jumps made a
    routine weekly workout a jump every week: each one sat above half of the last
    one, was halved in turn, and the runner's own habit never counted as tolerated.

    `confirmed` = a pain-free check-in / rating within 72 h (as before), OR a
    similar session (≥ 85 %) tolerated within 28 days after it (the repeat is the
    proof), OR passive confirmation: training went on within 72 h and no pain was
    reported in that time. `since` drops sessions too old to matter (ITEMS_LOOKBACK)."""
    tol = {} if tol is None else tol
    reports = reports or set()
    active_days = active_days or set()
    pool = sorted((s for s in sessions if s["exp"].get(ch) is not None and (since is None or s["date"] >= since)),
                  key=lambda s: s["date"])
    items, ords = [], []
    for s in pool:
        v = s["exp"][ch]
        if s["date"] not in tol:
            tol[s["date"]] = tolerated(s["date"], pain)
        ref = _d(s["date"]).toordinal()
        cap = _jump_capacity(items, ords, ref, ch)
        jump = cap is not None and v > JUMP_RATIO * cap
        items.append((s["date"], v, tol[s["date"]], jump, confirmed(s["date"], reports, pain)))
        ords.append(ref)
    for i, it in enumerate(items):
        if not (it[3] and it[2]) or it[4]:
            continue
        d0 = _d(it[0])
        after = [(d0 + timedelta(days=k)).isoformat() for k in range(1, PAIN_AFTER + 1)]
        repeated = any(0 < (_d(x[0]) - d0).days <= REPEAT_WINDOW and x[2] and x[1] >= REPEAT_SIMILAR * it[1]
                       for x in items[i + 1:])
        passive = any(d in active_days for d in after)          # tolerated() already excludes pain in 0–3 days
        items[i] = it[:4] + (repeated or passive,)
    return items


def _jump_capacity(items, ords, ref: int, ch):
    """session_capacity(items, day, ch, discount=False, top_n=1) for the jump judgement,
    on day ordinals (no date parsing, no sort) — it runs once per session per channel."""
    lo = bisect_left(ords, ref - CAP_MAX_AGE)
    hi = bisect_left(ords, ref)
    best, n30 = None, 0
    for j in range(lo, hi):
        age = ref - ords[j]
        if age <= CAP_WINDOW:
            n30 += 1
        it = items[j]
        if it[2]:
            v = it[1] * _decay(age)
            if best is None or v > best:
                best = v
    if n30 < MIN_PRIOR:
        return None
    return max(best or 0.0, CHANNELS[ch]["floor_s"])


def session_capacity(items, ref_day: str, ch, discount: bool = True, top_n: int | None = None):
    """Largest tolerated single-session exposure before `ref_day` (decayed), or
    None when fewer than MIN_PRIOR sessions in the last 30 days carry the channel.
    Intensity uses the mean of the TOP_N largest instead: Z4+ minutes of one
    session can be an outlier (a race, a hot day inflating heart rate), and a
    single such run must not open a huge per-run allowance. `items` from
    channel_items(). `discount=False` ignores the jump rule (the jump judgement)."""
    ref = _d(ref_day)
    lo = bisect_left(items, ((ref - timedelta(days=CAP_MAX_AGE)).isoformat(),))
    hi = bisect_left(items, (ref_day,))
    vals, n30 = [], 0
    for it in items[lo:hi]:
        day, v, ok = it[0], it[1], it[2]
        jump, conf = (it[3], it[4]) if len(it) > 3 else (False, True)
        age = (ref - _d(day)).days
        if age <= CAP_WINDOW:
            n30 += 1
        if not ok:
            continue
        if jump and discount:        # plan B1: a jump is not yet proof of capacity
            if age < JUMP_HOLD_DAYS:
                continue
            if not conf:
                v *= JUMP_UNCONFIRMED
        vals.append(v * _decay(age))
    if n30 < MIN_PRIOR:
        return None
    vals.sort(reverse=True)
    top = vals[:top_n or TOP_N.get(ch, 1)]
    best = sum(top) / len(top) if top else 0.0
    return max(best, CHANNELS[ch]["floor_s"])


def _daily_sums(sessions, ch):
    out = {}
    for s in sessions:
        v = s["exp"].get(ch)
        if v:
            out[s["date"]] = out.get(s["date"], 0.0) + v
    return out


def weekly_capacity(daily: dict, ref_day: str, first_day: str, pain: set, ch):
    """max(average week of the 4 weeks before the current 7-day window,
    0.9 × best pain-free 7-day window of the 6 weeks before it, decayed by BREAK_DECAY
    per week beyond its 2nd week, so after a break an old peak can't carry the capacity). A window more
    than JUMP_RATIO × the average week before it is a spike, not demonstrated
    tolerance, and is left out (plan B1)."""
    ref = _d(ref_day)
    known = (ref - _d(first_day)).days          # days of history before today
    if known < 27:
        return None
    iso = [(ref - timedelta(days=k)).isoformat() for k in range(77)]   # iso[k] = k days ago
    vals = [daily.get(d, 0.0) for d in iso]
    painful = [d in pain for d in iso]
    chronic = sum(vals[7:35]) / 4
    best = 0.0
    for back in range(7, 42):                 # window = days back … back+6
        if any(painful[back:back + 7]):
            continue
        w = sum(vals[back:back + 7])
        prior = vals[back + 7:min(back + 35, known + 1)]     # up to 4 weeks before it, within the history
        if len(prior) >= 14:
            before = sum(prior) / (len(prior) / 7)
            if before > 0 and w > JUMP_RATIO * before:
                continue
        best = max(best, w * BREAK_DECAY ** max(0.0, (back - 14) / 7))
    return max(chronic, 0.9 * best, CHANNELS[ch]["floor_w"])


# v0.10.1 — the weekly score compares the unabsorbed load (residual_week, an EWMA in
# weekly-equivalent units) with a capacity in THE SAME units: the runner's usual
# weekly PEAK of that residual. The EWMA jumps on the day of a session (7 × one step
# ≈ 1.3–1.5 × the session), so a once-a-week tempo or long run read as 1.5–1.85 ×
# the plain 7-day capacity on its own day, every week. Against the usual peak the
# habit scores 1.0, and only a real rise above it counts. On steady daily training
# the peak equals the plain 7-day sum, so nothing changes there. The reference series
# runs at the nominal rate (habit, not last week's nights); the plain capacity stays
# for the ceilings, the room left and the guidance, which are in km / min / m.
RES_WARMUP = 28        # days the EWMA runs before the oldest reference window


def _residual_series(daily: dict, days_oldest_first: list, k: float) -> list:
    level, out = 0.0, []
    for d in days_oldest_first:
        level = level * (1 - k) + k * daily.get(d, 0.0)
        out.append(7 * level)
    return out


def weekly_capacity_residual(daily: dict, ref_day: str, first_day: str, pain: set, ch):
    """weekly_capacity() in residual_week() units: the mean weekly peak of the residual
    over the 4 weeks before the current 7-day window, or 0.9 × the best pain-free
    window's peak of the 6 weeks before it (decayed, spikes left out by the same rule)."""
    ref = _d(ref_day)
    known = (ref - _d(first_day)).days
    if known < 27:
        return None
    n = 77
    iso = [(ref - timedelta(days=k)).isoformat() for k in range(n + RES_WARMUP)]   # iso[k] = k days ago
    k_ref = _k(HALF_CARDIO_REF if ch in CARDIO else HALF_MSK)
    res = _residual_series(daily, iso[::-1], k_ref)[::-1]                          # res[k] = k days ago
    vals = [daily.get(d, 0.0) for d in iso[:n]]
    painful = [d in pain for d in iso[:n]]

    def peak(back):
        return max(res[back:back + 7])
    chronic = sum(peak(b) for b in (7, 14, 21, 28)) / 4
    best = 0.0
    for back in range(7, 42):
        if any(painful[back:back + 7]):
            continue
        w = sum(vals[back:back + 7])
        prior = vals[back + 7:min(back + 35, known + 1)]
        if len(prior) >= 14:
            before = sum(prior) / (len(prior) / 7)
            if before > 0 and w > JUMP_RATIO * before:
                continue
        best = max(best, peak(back) * BREAK_DECAY ** max(0.0, (back - 14) / 7))
    return max(chronic, 0.9 * best, CHANNELS[ch]["floor_w"])


READY_BASE = (8, 56)    # baseline nights: 8–56 days back (a strained stretch doesn't become its own norm)
READY_TOLERANCE = 0.5   # SD — ordinary night-to-night noise costs nothing
READY_FULL = 3.0        # SD off the baseline = the whole deficit for that signal
READY_WEEK_BOOST = 1.25 # a 7-night mean is less noisy than one night: its deviation counts 1.25×
SLEEP_QUALITY_W = 0.5   # sleep quality (deep + REM share, efficiency) counts at most half a signal —
                        # watch sleep staging is only moderately accurate against PSG (de Zambotti 2019)
SLEEP_SD_FLOOR = {"rest_share": 0.03, "sleep_efficiency": 0.02}   # a near-constant baseline mustn't turn a 2 % dip into 4 SD
# v0.8.4 — single nights are unreliable (Plews et al. 2012: 64 % of a well-training
# athlete's single-day HRV values fell outside the SWC; 2013: 10 km performance
# tracked the weekly mean, r = −0.76, not single days, r = −0.17). A night's own
# deviation counts at 0.6× unless the 7-night mean points the same way.
READY_NIGHT_W = 0.6
# Valid nights a 7-night mean needs: ~5 for recreational runners, ≥ 3 for trained
# ones (Plews et al. 2014). "Trained" = ≥ 40 km a week over the last 4 weeks
# (working assumption).
READY_WEEK_MIN = {"rec": 5, "trained": 3}
TRAINED_KM_WEEK = 40.0
# Sleep over several nights (Halson 2014b: effects build up over consecutive
# nights) and an absolute floor (Watson et al. 2015: ≥ 7 h for adults), so a
# chronically short sleeper isn't normalised by their own baseline. Weights are
# working assumptions: a night < 7 h counts 0.5, < 6 h counts 1; over the last 4
# nights up to 1.5 is free and 4 points cost 0.6 of a signal.
SLEEP_NIGHTS = 3
SLEEP_ABS_H, SLEEP_ABS_LOW_H = 7.0, 6.0
SLEEP_ABS_MAX = 0.6
# Check-in items kept separate (Saw et al. 2016). Stress outside training counts
# 0.6 of a signal from 6/10, a poor / very poor subjective night 0.2 / 0.35
# (working assumptions, the review gives no weights).
LIFE_STRESS_W = 0.6
SLEEP_QUALITY_DEFICIT = {0: 0.35, 1: 0.2}


def _ln_hrv(fld, v):
    """HRV (ms) → Ln rMSSD; other fields as they are."""
    if fld != "hrv_ms" or v is None:
        return v
    return math.log(v) if v > 0 else None


READINESS_LABELS = ((85, "Plná"), (65, "Dobrá"), (45, "Snížená"), (0, "Nízká"))


def readiness_label(score) -> str | None:
    """A word for the readiness score (20–100 %)."""
    if score is None:
        return None
    return next(lbl for lo, lbl in READINESS_LABELS if score >= lo)


def rest_share(row):
    """Deep + REM share of the staged sleep (0–1), None without stages."""
    parts = [getattr(row, k, None) for k in ("deep_min", "rem_min", "light_min")]
    if any(p is None for p in parts) or sum(parts) <= 0:
        return None
    return (parts[0] + parts[1]) / sum(parts)


def _sleep_abs(nights) -> float | None:
    """Absolute short-sleep deficit from the last 4 nights (None with < 3 known)."""
    known = [h for h in nights if h is not None]
    if len(known) < 3:
        return None
    pts = sum(1.0 if h < SLEEP_ABS_LOW_H else 0.5 if h < SLEEP_ABS_H else 0.0 for h in known[:4])
    return SLEEP_ABS_MAX * E.clamp((pts - 1.5) / 2.5, 0, 1)


def readiness_parts(night: dict, week: dict, base: dict, zover: dict | None = None,
                    night_w: float | None = None) -> dict:
    """Per-signal deficits 0–1. `night` = that day's values, `week` = the last 7
    nights' means (HRV / resting HR, only with enough valid nights) plus
    `sleep_recent` (mean of the last 3 nights) and `sleep_nights` (last 4 nights'
    hours, newest first), `base` = {field: (mean, sd)} of the runner's baseline
    nights. `zover` = {field: (night z, week z)} from the individualised reference
    range (plan phase 1), which replaces the mean/SD deviation for that field.
    `night_w` fixes the single-night weight (default: 1 when the 7-night mean
    confirms the direction, READY_NIGHT_W otherwise)."""
    parts = {}
    for key, sign in (("hrv_ms", -1), ("resting_hr", 1)):
        zn = zw = None
        if zover and key in zover:
            zn, zw = zover[key]
            zn = None if zn is None else sign * zn
            zw = None if zw is None else sign * zw
        elif key in base:
            m, s = base[key]
            if night.get(key) is not None:
                zn = sign * (night[key] - m) / s
            if week.get(key) is not None:
                zw = sign * (week[key] - m) / s
        else:
            continue
        views = []
        if zw is not None:
            views.append(zw * READY_WEEK_BOOST)
        if zn is not None:
            w = night_w if night_w is not None else (1.0 if (zw is not None and zw >= READY_TOLERANCE) else READY_NIGHT_W)
            views.append(zn * w)
        if views:
            d = E.clamp((max(views) - READY_TOLERANCE) / (READY_FULL - READY_TOLERANCE), 0, 1)
            parts["hrv" if key == "hrv_ms" else "rhr"] = round(d, 2)
    dur = qual = None
    if "sleep_h" in base and night.get("sleep_h") is not None:
        recent = week.get("sleep_recent", night["sleep_h"])    # the last 3 nights, not one
        short = base["sleep_h"][0] - recent                     # hours below the usual
        dur = E.clamp((short - 0.5) / 2.0, 0, 1)
    ab = _sleep_abs(week.get("sleep_nights") or [])
    if ab:
        dur = max(dur or 0.0, ab)
    for key in ("rest_share", "sleep_efficiency"):             # quality: less deep + REM / more awake than usual
        if key in base and night.get(key) is not None:
            m, sdv = base[key]
            z = (m - night[key]) / max(sdv, SLEEP_SD_FLOOR[key])
            q = SLEEP_QUALITY_W * E.clamp((z - READY_TOLERANCE) / (READY_FULL - READY_TOLERANCE), 0, 1)
            qual = max(qual or 0.0, q)
    if dur is not None or qual is not None:                    # a long night of poor sleep still costs
        parts["sleep"] = round(1 - (1 - (dur or 0.0)) * (1 - (qual or 0.0)), 2)
    return parts


# Own logic, every device (dayload.py): yesterday's minutes of raised resting heart rate
# (awake, not moving, well above the runner's own still-awake level) against the usual
# day. A minor signal — heart rate at rest also rises with caffeine, heat or digestion —
# so it counts like the check-in's stress (× DAY_STRESS_W). Working assumption.
DAY_STRESS_W = 0.6
DAY_STRESS_MIN_DAYS = 7
DAY_STRESS_SD_FLOOR = 15.0


def raised_minutes(row) -> float | None:
    if row is None or getattr(row, "rest_high_min", None) is None:
        return None
    return (row.rest_high_min or 0) + 0.5 * (row.rest_mild_min or 0)


def day_stress_part(dm: dict, d0) -> float | None:
    """Deficit 0–DAY_STRESS_W from yesterday's raised resting HR vs the 28 days before."""
    y = raised_minutes(dm.get((d0 - timedelta(days=1)).isoformat()))
    if y is None:
        return None
    base = [v for v in (raised_minutes(dm.get((d0 - timedelta(days=j)).isoformat())) for j in range(2, 30)) if v is not None]
    if len(base) < DAY_STRESS_MIN_DAYS:
        return None
    m, sd = E.mean(base), max(E.sd(base) or 0.0, DAY_STRESS_SD_FLOOR)
    z = (y - m) / sd
    d = DAY_STRESS_W * E.clamp((z - READY_TOLERANCE) / (READY_FULL - READY_TOLERANCE), 0, 1)
    return round(d, 2) if d > 0 else None


def checkin_parts(c) -> dict:
    """v0.9.3 — a check-in's items as readiness-style deficits (the pre-v0.9.3 rules),
    for the training recommendation only: on the Skóre they count once, on Příznaky,
    and they no longer enter readiness (owner feedback 2026-09-30)."""
    parts = {}
    if c is None:
        return parts
    if c.soreness is not None and c.soreness >= 6:
        parts["soreness"] = round(E.clamp((c.soreness - 5) / 5, 0, 1), 2)
    if c.stress is not None and c.stress >= 6:
        parts["fatigue"] = round(E.clamp((c.stress - 5) / 5, 0, 1), 2)
    ls = getattr(c, "life_stress", None)
    if ls is not None and ls >= 6:
        parts["stress"] = round(LIFE_STRESS_W * E.clamp((ls - 5) / 5, 0, 1), 2)
    sq = getattr(c, "sleep_quality", None)
    if sq in SLEEP_QUALITY_DEFICIT:
        parts["sleepSelf"] = SLEEP_QUALITY_DEFICIT[sq]
    return parts


def with_checkin(parts: dict, ci: dict) -> dict:
    """Watch readiness parts + check-in parts; the runner's own night compounds with
    the watch's sleep, as it did inside readiness before v0.9.3."""
    out = {**parts, **{k: v for k, v in ci.items() if k != "sleepSelf"}}
    if "sleepSelf" in ci:
        out["sleep"] = round(1 - (1 - parts.get("sleep", 0.0)) * (1 - ci["sleepSelf"]), 2)
    return out


def readiness_from(parts: dict) -> tuple[float, int]:
    """(capacity factor 0.7–1.0, readiness score 20–100 %) from per-signal deficits.
    Agreeing signals compound: the worst counts fully, the 2nd half, the 3rd a quarter."""
    top = sorted(parts.values(), reverse=True) + [0.0, 0.0, 0.0]
    deficit = E.clamp(top[0] + 0.5 * top[1] + 0.25 * top[2], 0, 1)
    return round(1 - (1 - READINESS_FLOOR) * deficit, 3), round(100 * (1 - 0.8 * deficit))


COMBO_READY = (1.0, 0.5, 0.25)

# v0.10.0 — tissue-specific readiness. HRV and resting HR describe cardiac autonomic
# recovery, which returns within 24 h after easy, 24–48 h after threshold and ≥ 48 h after
# hard sessions (Stanley, Peake & Buchheit, 2013), while tendon collagen turnover stays
# raised for about 3 days after loading (Magnusson, Langberg & Kjaer, 2010). The two only
# partly move together: morning HR / HRV explained up to about 25 % of the change in
# creatine kinase during intensified endurance training (Weippert et al., 2018, r ≈ 0.49).
# So the cardio channels (systemic load, Z4+ minutes) take the full readiness factor and
# the muscle / tendon / bone channels take HRV and resting HR at half weight (the weight
# is our derivation from that correlation). Sleep keeps its full weight on every channel:
# shorter and more fragmented sleep went with musculoskeletal injury in athlete cohorts
# (e.g. Viegas et al., 2022; evidence mostly from adolescents). The displayed readiness
# score does not change.
MSK_CHANNELS = ("volume", "descent", "ascent", "strength")
MSK_AUTONOMIC_W = 0.5


def channel_readiness(entry, ch) -> float:
    """The readiness factor (0.7–1.0) a channel's capacity takes on a day: the plain
    factor for the cardio channels, HRV and resting HR at MSK_AUTONOMIC_W for the
    musculoskeletal ones. `entry` = a readiness_by_day value (factor, parts, score)."""
    factor, parts = entry[0], entry[1] if len(entry) > 1 else None
    if ch not in MSK_CHANNELS or not parts:
        return factor
    weighted = {k: v * (MSK_AUTONOMIC_W if k in ("hrv", "rhr") else 1.0) for k, v in parts.items() if k != "session"}
    return readiness_from(weighted)[0] if weighted else 1.0


def readiness_effects(parts: dict) -> dict:
    """Feedback railway#107 — points each signal takes off the readiness score, by the
    same rule as readiness_from (worst fully, 2nd half, 3rd a quarter, the rest nothing),
    so they add up to 100 − score (before rounding)."""
    order = sorted(((k, v) for k, v in parts.items() if v and v > 0), key=lambda kv: -kv[1])
    raw = {k: v * COMBO_READY[i] if i < len(COMBO_READY) else 0.0 for i, (k, v) in enumerate(order)}
    tot = sum(raw.values())
    scale = 1.0 / tot if tot > 1 else 1.0                  # the combined deficit is capped at 1
    return {k: round(80 * x * scale, 1) for k, x in raw.items()}


def _range(rows, fld, dec):
    """[low, high] = the baseline mean ± 1 SD (HRV: on the log scale, back in ms), or None."""
    vals = [v for v in (_ln_hrv(fld, getattr(r, fld)) for r in rows) if v is not None]
    if len(vals) < 10 or not E.sd(vals):
        return None
    m, s = E.mean(vals), E.sd(vals)
    lo, hi = (math.exp(m - s), math.exp(m + s)) if fld == "hrv_ms" else (m - s, m + s)
    return [round(lo, dec) if dec else round(lo), round(hi, dec) if dec else round(hi)]


def readiness_inputs(db, rid, day: str) -> dict:
    """The readings behind the readiness signals, for the detail (railway#107): last
    night, the 7-night means, the usual values (mean of the baseline nights 8–56 days
    back) and that day's check-in answers."""
    d0 = _d(day)
    lo = (d0 - timedelta(days=READY_BASE[1])).isoformat()
    data = D.of(db, rid)
    dm = {m.date[:10]: m for m in data.daily if m.date >= lo}

    def rows(a, b):
        return [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(a, b + 1)) if k in dm]

    def avg(rs, f, n_min=1):
        v = [x for x in ((rest_share(r) if f == "rest_share" else getattr(r, f)) for r in rs) if x is not None]
        return E.mean(v) if len(v) >= n_min else None

    base, week, recent = rows(*READY_BASE), rows(0, 6), rows(0, SLEEP_NIGHTS - 1)
    night = dm.get(day)

    def r0(v):
        return None if v is None else round(v)

    def r1(v):
        return None if v is None else round(v, 1)

    def r2(v):
        return None if v is None else round(v, 2)
    out = {
        "night": {"hrv": r0(night.hrv_ms) if night else None, "rhr": r0(night.resting_hr) if night else None,
                  "sleep": r1(night.sleep_h) if night else None,
                  "eff": r2(night.sleep_efficiency) if night else None, "rest": r2(rest_share(night)) if night else None},
        "week": {"hrv": r0(avg(week, "hrv_ms", 3)), "rhr": r0(avg(week, "resting_hr", 3)), "sleep": r1(avg(recent, "sleep_h", 2))},
        "base": {"hrv": r0(avg(base, "hrv_ms", 10)), "rhr": r0(avg(base, "resting_hr", 10)), "sleep": r1(avg(base, "sleep_h", 10)),
                 "eff": r2(avg(base, "sleep_efficiency", 10)), "rest": r2(avg(base, "rest_share", 10))},
        # v0.9.0 — the usual range (mean ± 1 SD of the baseline nights; HRV on the log
        # scale), for the Připravenost detail: where last week sits against the norm
        "range": {k: _range(base, f, dec) for k, f, dec in (("hrv", "hrv_ms", 0), ("rhr", "resting_hr", 0), ("sleep", "sleep_h", 1))},
        # the last 7 nights, oldest first (the dots behind the week's mean)
        "nights": [{"d": k, "hrv": r0(dm[k].hrv_ms), "rhr": r0(dm[k].resting_hr), "sleep": r1(dm[k].sleep_h)}
                   for k in sorted(x for x in ((d0 - timedelta(days=j)).isoformat() for j in range(7)) if x in dm)],
        "checkin": None,
    }
    # own all-day heart rate (dayload.py): yesterday's raised resting minutes vs the usual day
    dm_all = {m.date[:10]: m for m in data.daily}
    yv = raised_minutes(dm_all.get((d0 - timedelta(days=1)).isoformat()))
    bv = [v for v in (raised_minutes(dm_all.get((d0 - timedelta(days=j)).isoformat())) for j in range(2, 30)) if v is not None]
    if yv is not None:
        out["dayStress"] = {"yesterday": round(yv), "usual": round(E.mean(bv)) if bv else None, "n": len(bv)}
    cks = [c for c in data.checkins if day <= c.submitted_at < day + "T99"]
    if cks:
        c = max(cks, key=lambda x: x.submitted_at or "")
        out["checkin"] = {"soreness": c.soreness, "fatigue": c.stress, "stress": getattr(c, "life_stress", None),
                          "sleepQuality": getattr(c, "sleep_quality", None)}
    return out


def readiness_block(db, rid) -> dict | None:
    """v0.9.0 — Připravenost for the engines without the capacity model (Standardní /
    Citlivý): it replaced the single-night Regenerace ring on Dnes for every runner.
    The morning readiness with yesterday's for comparison (the Kapacitní engine builds
    the full block, today's session included, in assess_capacity). None without any
    night or check-in in the last 8 weeks."""
    data = D.of(db, rid)
    today = E.today_date()
    t_iso, y_iso = today.isoformat(), (today - timedelta(days=1)).isoformat()
    lo = (today - timedelta(days=READY_BASE[1])).isoformat()
    has_nights = any(m.date >= lo and (m.hrv_ms is not None or m.resting_hr is not None or m.sleep_h is not None)
                     for m in data.daily)
    if not has_nights and not any(c.submitted_at >= lo for c in data.checkins):
        return None
    ready = readiness_by_day(data, rid, [y_iso, t_iso])
    nights = {m.date[:10] for m in data.daily if m.date[:10] in (y_iso, t_iso)
              and (m.hrv_ms is not None or m.resting_hr is not None or m.sleep_h is not None)}
    r_today, parts, score = ready.get(t_iso, (1.0, {}, 100))
    _yf, y_parts, y_score = ready.get(y_iso, (1.0, {}, 100))
    eff = readiness_effects(parts)
    return {"today": r_today, "score": score, "label": readiness_label(score), "parts": parts,
            "morningScore": score, "afterSession": None, "effects": eff, "morningEffects": eff,
            "yesterday": {"score": y_score, "parts": y_parts, "effects": readiness_effects(y_parts),
                          "known": y_iso in nights or bool(y_parts)},
            "known": t_iso in nights or bool(parts), "inputs": readiness_inputs(data, rid, t_iso)}


def trained_runner(db, rid, ref_day: str) -> bool:
    """≥ TRAINED_KM_WEEK km of running a week over the 4 weeks before `ref_day`."""
    d0 = _d(ref_day)
    lo = (d0 - timedelta(days=28)).isoformat()
    km = sum(a.distance_km or 0 for a in D.of(db, rid).activities
             if lo <= a.started_at <= ref_day + "T23:59" and a.excluded is not True and (a.sport or "running") == "running")
    return km / 4 >= TRAINED_KM_WEEK


def _sleep_window(dm: dict, d0) -> dict:
    """Sleep of the last nights up to `d0`: mean of the last 3 known (≥ 2 needed) and
    the last 4 nights' hours, newest first."""
    nights = [getattr(dm.get((d0 - timedelta(days=j)).isoformat()), "sleep_h", None) for j in range(4)]
    out = {"sleep_nights": nights}
    rec = [h for h in nights[:SLEEP_NIGHTS] if h is not None]
    if len(rec) >= 2 and nights[0] is not None:
        out["sleep_recent"] = E.mean(rec)
    return out


def readiness_by_day(db, rid, days) -> dict:
    """{iso day: (capacity factor 0.7–1.0, parts, readiness score 20–100)}.

    Readiness = how far this runner's own recovery markers sit from THEIR normal
    (baseline nights 8–56 days back), scaled by the size of the deviation:
      • HRV (low) and resting HR (high): the worse of last night and the 7-night
        mean — the rolling mean is what HRV-guided training uses (Plews et al.
        2013) and what the watch's "HRV status" reflects; the mean's deviation
        counts 1.25× (it's less noisy than one night), and it needs 5 valid nights
        (3 for trained runners, Plews 2014). v0.8.4: the night alone counts 0.6×
        unless the 7-night mean confirms it;
      • sleep: hours below the usual over the last 3 nights, or repeated nights
        under 7 h (whichever is worse), compounded with its quality — a lower
        deep + REM share or efficiency than usual (at most half a signal) and the
        runner's own rating of the night;
      • (v0.9.3: check-in items are scored on Příznaky only, not here).
    Each signal: nothing within ±0.5 SD (normal noise), the full deficit at 3 SD.
    The score (shown as "připravenost") = 100 − 80 × combined deficit: ~70 % when
    HRV and resting HR are both ~1.1 SD off (7-night means ~0.9 SD) or HRV alone
    ~1.45 SD low, ~40 % at ~1.75 SD each, 20 % at the floor. The capacity factor that scales
    load capacity keeps the narrower 0.7–1.0 range. (1.0 / 100 without enough
    watch data to judge.)"""
    days = sorted(set(days))
    if not days:
        return {}
    lo = (_d(days[0]) - timedelta(days=READY_BASE[1] + 1)).isoformat()
    data = D.of(db, rid)
    dm = {d.date[:10]: d for d in data.daily if d.date >= lo}
    from . import reference as REF
    pri = {f: E.recovery_priors(f, data) for f in REF.RECOVERY_FIELDS}
    wk_min = READY_WEEK_MIN["trained" if trained_runner(data, rid, days[-1]) else "rec"]
    out = {}
    for day in days:
        d0 = _d(day)
        base_rows = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(READY_BASE[0], READY_BASE[1] + 1)) if k in dm]
        week_rows = [dm[k] for k in ((d0 - timedelta(days=j)).isoformat() for j in range(0, 7)) if k in dm]
        parts = {}
        night = dm.get(day)
        # Plan phase 1: with population priors, HRV and resting HR are judged against
        # the runner's individualised reference range, from the 3rd baseline night on
        # (the plain mean/SD needs 14). HRV on the log scale.
        zover = {}
        if night is not None:
            for fld in REF.RECOVERY_FIELDS:
                pr = pri.get(fld)
                bvals = [getattr(b, fld) for b in base_rows if getattr(b, fld) is not None]
                if not pr or len(bvals) < 3:
                    continue
                x = getattr(night, fld)
                zn = REF.recovery_deviation(fld, bvals, x, pr) if x is not None else None
                wv = [getattr(b, fld) for b in week_rows if getattr(b, fld) is not None]
                zw = None
                if len(wv) >= wk_min:
                    wm = E.mean([REF._t(fld, v) for v in wv if REF._t(fld, v) is not None])
                    back = math.exp(wm) if pr["log"] else wm
                    zw = REF.recovery_deviation(fld, bvals, back, pr)
                zover[fld] = (zn[0] if zn else None, zw[0] if zw else None)
        if night is not None and zover and len(base_rows) < 14:
            parts = readiness_parts({}, _sleep_window(dm, d0), {}, zover)
        elif night is not None and len(base_rows) >= 14:
            base = {}
            # v0.9.0 — HRV on the log scale (Ln rMSSD) here too, like the reference-range path
            for fld in ("hrv_ms", "resting_hr", "sleep_h", "sleep_efficiency", "rest_share"):
                vals = [v for v in (_ln_hrv(fld, rest_share(b) if fld == "rest_share" else getattr(b, fld)) for b in base_rows)
                        if v is not None]
                if len(vals) >= 10 and (E.sd(vals) or fld in SLEEP_SD_FLOOR):
                    base[fld] = (E.mean(vals), E.sd(vals) or 0.0)
            wk = {}
            for fld in ("hrv_ms", "resting_hr"):
                vals = [v for v in (_ln_hrv(fld, getattr(b, fld)) for b in week_rows) if v is not None]
                if len(vals) >= wk_min:
                    wk[fld] = E.mean(vals)
            wk.update(_sleep_window(dm, d0))
            parts = readiness_parts({**{f: _ln_hrv(f, getattr(night, f)) for f in ("hrv_ms", "resting_hr", "sleep_h", "sleep_efficiency")},
                                     "rest_share": rest_share(night)}, wk, base, zover)
        ds = day_stress_part(dm, d0)
        if ds:
            parts["dayStress"] = ds
        # v0.9.3 — check-in items (soreness, fatigue, stress outside training, the night's
        # rating) no longer enter readiness: they are scored once, on Příznaky (owner
        # feedback 2026-09-30). Readiness = the watch's recovery markers and today's session.
        factor, score = readiness_from(parts)
        out[day] = (factor, parts, score)
    return out


# ------------------------------------------------------------------ v0.8.6 after-session readiness
# A session done today lowers today's readiness until the next night's HRV, resting
# heart rate and sleep show the body's actual response. Complete cardiac autonomic
# recovery takes up to 24 h after low-intensity, 24–48 h after threshold and ≥ 48 h
# after high-intensity aerobic exercise, intensity matters more than duration and
# fitter people recover faster (Stanley et al., 2013); up to 2 h below the first
# threshold barely disturbs trained runners (Seiler et al., 2007). The effort is
# judged against the runner's own days, so the same session costs a fitter runner
# less. The point values are working assumptions of the product team.
EFFORT_CURVE = ((0.0, 0.0), (0.25, 0.05), (0.5, 0.10), (0.75, 0.20), (1.0, 0.35))   # own-day percentile → deficit
EFFORT_EASY_MAX = 0.05     # a session below the first threshold: at most ~4 points
EFFORT_Z4_BONUS = ((20, 0.15), (10, 0.10))   # minutes in Z4+ → extra deficit (above threshold)
EFFORT_CAP = 0.45          # at most ~36 points in total
EFFORT_CARRY = 0.5         # without a night's data, a hard session carries half into the next day
EFFORT_MIN_DAYS = 8        # active days in the last 8 weeks needed to judge "relative"
VT1_HRR = 0.70             # Z3 starts at 70 % HRR — a stand-in for the first threshold


def _interp(p, curve):
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if p <= x1:
            return y0 + (y1 - y0) * (p - x0) / (x1 - x0) if x1 > x0 else y1
    return curve[-1][1]


def day_effort(sessions, day: str, hrmax, rhr) -> dict | None:
    """The day's sessions (any sport) against the runner's own active days of the 56
    before: {deficit, pct, band, z4, easy, hard, sessions[]} or None without a session
    or with too little history."""
    todays = [s for s in sessions if s["date"] == day and s["exp"].get("systemic")]
    if not todays:
        return None
    d0 = _d(day)
    load = sum(s["exp"]["systemic"] for s in todays)
    daily = _daily_sums([s for s in sessions if s["exp"].get("systemic")], "systemic")
    past = [v for k, v in daily.items() if 0 < (d0 - _d(k)).days <= 56 and v > 0]
    if len(past) < EFFORT_MIN_DAYS:
        return None
    pct = min(1.0, _pct_rank(past, load))
    above_max = load > max(past)
    z4 = 0.0
    easy, hard = True, False
    for s in todays:
        mins = s.get("durationMin") or 0
        z = s["exp"].get("intensity")
        hrr = (s["avgHr"] - rhr) / (hrmax - rhr) if (s.get("avgHr") and hrmax and hrmax > rhr) else None
        rpe = s.get("rpe")
        if z is None and s.get("sport") not in ("strength",) and hrr is not None and hrr >= Z4_HRR:
            z = mins                                   # a cross session held in Z4+ on average
        z4 += z or 0.0
        s_easy = (rpe is not None and rpe <= 4) or (hrr is not None and hrr < VT1_HRR and not (z or 0))
        easy = easy and bool(s_easy)
        hard = hard or (rpe is not None and rpe >= 7)
    hard = hard or z4 >= EFFORT_Z4_BONUS[-1][0]
    deficit = _interp(pct, EFFORT_CURVE)
    if easy and not hard:
        deficit = min(deficit, EFFORT_EASY_MAX)
    else:
        deficit += next((b for m, b in EFFORT_Z4_BONUS if z4 >= m), 0.0)
    deficit = min(EFFORT_CAP, deficit)
    band = ("nejnáročnější za 8 týdnů" if above_max else "náročnější než obvykle" if pct > 0.75
            else "obvyklá náročnost" if pct >= 0.25 else "lehčí než obvykle")
    return {"deficit": round(deficit, 3), "pct": round(pct * 100), "band": band, "z4": round(z4),
            "easy": easy and not hard, "hard": hard,
            "sessions": [{"title": s["title"], "sport": s.get("sport"), "min": E.rnd(s.get("durationMin"))} for s in todays]}


def after_session(sessions, t_iso: str, night_today: bool, hrmax, rhr) -> dict | None:
    """Today's after-session readiness part: today's effort plus, before this night's
    data arrive, half of a hard session from yesterday."""
    today = day_effort(sessions, t_iso, hrmax, rhr)
    carry = None
    if not night_today:
        y = day_effort(sessions, (_d(t_iso) - timedelta(days=1)).isoformat(), hrmax, rhr)
        if y and y["hard"]:
            carry = {"deficit": round(y["deficit"] * EFFORT_CARRY, 3), "sessions": y["sessions"], "band": y["band"]}
    if not today and not carry:
        return None
    deficit = min(EFFORT_CAP, (today["deficit"] if today else 0.0) + (carry["deficit"] if carry else 0.0))
    return {"deficit": round(deficit, 3), "today": today, "carry": carry}


# v0.10.4 — the day outside training lowers today's readiness too, like a session does,
# until the night's HRV, resting HR and sleep show the actual response (dayload.py,
# every device). Load outside training above the usual day is judged on the same scale
# as the session: what it adds to the day's total (training + outside) against the
# runner's own days of the last 8 weeks, at most ~8 points (walking and daily life are
# low-intensity, below the first threshold — Seiler et al., 2007). Today's raised resting
# heart rate so far counts like yesterday's (× DAY_STRESS_W); it only grows during the
# day, so the morning shows nothing and the evening the whole day. Working assumptions.
NT_DAY_CAP = 0.10


def day_now(db, rid, sessions, nt_days: dict, t_iso: str) -> dict | None:
    """{nt: {deficit, excess, total}, stress: {deficit, min, usual}} for today, or None."""
    out = {}
    ex = nt_days.get(t_iso) or 0.0
    if ex > 0:
        d0 = _d(t_iso)
        train = _daily_sums([s for s in sessions if s["exp"].get("systemic")], "systemic")
        days = set(train) | set(nt_days)
        past = [v for v in ((train.get(k, 0.0) + nt_days.get(k, 0.0)) for k in days
                            if 0 < (d0 - _d(k)).days <= 56) if v > 0]
        if len(past) >= EFFORT_MIN_DAYS:
            t0 = train.get(t_iso, 0.0)
            d = (_interp(min(1.0, _pct_rank(past, t0 + ex)), EFFORT_CURVE)
                 - (_interp(min(1.0, _pct_rank(past, t0)), EFFORT_CURVE) if t0 > 0 else 0.0))
            d = E.clamp(d, 0.0, NT_DAY_CAP)
            if d >= 0.01:
                out["nt"] = {"deficit": round(d, 3), "excess": round(ex), "total": round(t0 + ex)}
    data = D.of(db, rid)
    lo = (_d(t_iso) - timedelta(days=31)).isoformat()
    dm = {m.date[:10]: m for m in data.daily if m.date >= lo}
    ds = day_stress_part(dm, _d(t_iso) + timedelta(days=1))
    if ds:
        base = [v for v in (raised_minutes(dm.get((_d(t_iso) - timedelta(days=j)).isoformat())) for j in range(1, 29)) if v is not None]
        out["stress"] = {"deficit": ds, "min": round(raised_minutes(dm.get(t_iso)) or 0),
                         "usual": round(E.mean(base)) if base else None}
    return out or None


def hr_zones(hrmax, rhr, lthr=None):
    return [{"z": z, "lo": round(lo), "hi": round(hi)} for z, lo, hi in zone_bounds(hrmax, rhr, lthr)]


# ------------------------------------------------------------------ relative effort
def _pct_rank(xs, v):
    return sum(1 for x in xs if x <= v) / len(xs) if xs else None


def _quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))] if xs else None


def hr_speed_fit(runs, ref_day: str, lo=7, hi=56):
    """The runner's own HR-vs-speed line (intercept, bpm per m/s) from flat-ish
    runs lo…hi days before `ref_day` — Theil–Sen, so odd runs don't bend it. None
    with < 8 runs, < 0.15 m/s of speed spread, or a non-rising slope."""
    d0 = _d(ref_day)
    base = [p for p in runs if lo <= (d0 - _d(p["date"])).days <= hi and p["avgHr"] and p["speed"]
            and p["ascPerKm"] < 15 and not p.get("hot")]      # v0.8.4: hot runs don't set the norm
    if len(base) < 8:
        return None
    pts = [(p["speed"], p["avgHr"]) for p in base]
    sl = [(h2 - h1) / (v2 - v1) for i, (v1, h1) in enumerate(pts) for (v2, h2) in pts[i + 1:] if abs(v2 - v1) >= 0.05]
    spread = max(p[0] for p in pts) - min(p[0] for p in pts)
    if len(sl) < 10 or spread < 0.15:
        return None
    b = E.median(sl)
    if b <= 0.5:
        return None
    return (E.median([h - b * v for v, h in pts]), b)


def relative_effort(sessions, ref_day: str, n_runs=6):
    """Strava-style relative effort against the runner's last 8 weeks: each recent
    run's HR training load vs the runs of the previous 56 days (below / usual /
    above / well above), HR at that pace vs the heart rate the runner usually
    needs for it (an easy run costing +8 bpm is a fatigue / heat / illness hint),
    and the last 7 days' total vs the usual weekly range."""
    ref = _d(ref_day)
    runs = [s for s in sessions if s["run"] and s["exp"].get("systemic")]
    recent = [s for s in runs if 0 <= (ref - _d(s["date"])).days <= 13][-n_runs:]
    out_runs = []
    for s in reversed(recent):
        d0 = _d(s["date"])
        past = [p["exp"]["systemic"] for p in runs if 0 < (d0 - _d(p["date"])).days <= 56]
        row = {"date": s["date"], "title": s["title"], "km": E.r1(s["km"]) if s["km"] else None,
               "effort": E.rnd(s["exp"]["systemic"]), "band": None, "pct": None, "hrDelta": None, "hrExpected": None}
        if len(past) >= 6:
            v = s["exp"]["systemic"]
            q1, q3 = _quantile(past, 0.25), _quantile(past, 0.75)
            row["band"] = ("pod" if v < q1 else "obvyklé" if v <= q3 else "nad" if v <= max(past) else "výrazně nad")
            row["pct"] = round(_pct_rank(past, v) * 100)
            row["usual"] = [E.rnd(q1), E.rnd(q3)]
            row["overMax"] = round(v / max(past), 2) if v > max(past) else None   # feedback #148: how far past the hardest
        fit = hr_speed_fit(runs, s["date"])
        spd = s.get("gSpeed") or s["speed"]          # v0.8.4: hills priced in (Minetti 2002)
        row["hot"] = bool(s.get("hot"))
        row["hilly"] = s["ascPerKm"] >= 30
        if s["avgHr"] and spd and fit:
            exp_hr = fit[0] + fit[1] * spd
            row["hrExpected"] = E.rnd(exp_hr)
            row["hrDelta"] = E.rnd(s["avgHr"] - exp_hr)
        out_runs.append(row)
    daily = _daily_sums([s for s in sessions if s["exp"].get("systemic")], "systemic")

    def win(end):
        return sum(daily.get((end - timedelta(days=k)).isoformat(), 0.0) for k in range(7))
    week = None
    past_w = [win(ref - timedelta(days=b)) for b in range(7, 57)]
    if sum(1 for x in past_w if x > 0) >= 20:
        now = win(ref)
        lo, hi = _quantile(past_w, 0.25), _quantile(past_w, 0.75)
        week = {"now": E.rnd(now), "lo": E.rnd(lo), "hi": E.rnd(hi),
                "band": "pod" if now < lo else "obvyklé" if now <= hi else "nad"}
    return {"runs": out_runs, "week": week}


# ------------------------------------------------------------------ assessment
def _cz(day: str) -> str:
    d0 = _d(day)
    return f"{d0.day}. {d0.month}."


def _fmt(v, ch):
    dec = CHANNELS[ch]["dec"]
    return None if v is None else (round(v, dec) if dec else round(v))


SPORT_CS = {"cycling": "kolo", "swimming": "plavání", "strength": "silový trénink", "rowing": "veslování",
            "elliptical": "orbitrek", "hiking": "turistika", "walking": "chůze", "other": "jiný sport"}
HISTORY_DAYS = 28      # Zátěž → Historie aktivit: a session can still add points for 28 days (latent floor)
SESSION_DAYS = 7       # …its own per-session points count for the first 7 (age 0–6)


def _band_word(r, margin):
    if r is None:
        return None
    return "v kapacitě" if r <= 1 + margin else "mírně nad" if r <= 1.3 else "nad" if r <= 2.0 else "výrazně nad"


def _history_rows(pool, ch, items, rates, ready, daily, first_day, pain, today, t_iso, absorb_days, m_s, m_w,
                  body_before=None) -> dict:
    """{session id: how that session loads channel `ch`} for the last HISTORY_DAYS days:
    its value against the per-run ceiling of its day (capacity × margin × that day's
    readiness, as the score does) and against the weekly ceiling with the other sessions
    of that 7-day window, the room left at the same pace (railway#110), the share still
    unabsorbed this morning and the points it would give on its own today."""
    spec = CHANNELS[ch]
    out, wcap = {}, {}
    for s in pool:
        v = s["exp"].get(ch)
        if v is None:
            continue
        age = (today - _d(s["date"])).days
        if age < 0 or age >= HISTORY_DAYS:
            continue
        d0 = _d(s["date"])
        cap = session_capacity(items, s["date"], ch)
        entry = ready.get(s["date"], (1.0, {}, 100))
        rd, rd_score = channel_readiness(entry, ch), entry[2]
        b = body_before(s["date"]) if body_before else None
        bf, bs, bh = (b["factor"][ch], b["score"][ch], b["hold"][ch]) if b else (1.0, 1.0, 1.0)
        r = v / (cap * rd * bs) if cap else None
        left = absorbed_left(rates, s["date"], t_iso, absorb_days) if s["date"] >= absorb_days[0] else 0.0
        p_ses = band_points(r, m_s * bh) * left if (r is not None and age < SESSION_DAYS) else 0.0
        p_lat = latent_points(r, age) if r is not None else 0.0
        if s["date"] not in wcap:
            wcap[s["date"]] = weekly_capacity(daily, s["date"], first_day, pain, ch)
        cw = wcap[s["date"]]
        # the 7-day window ending that day, as the weekly ceiling was then (week-average readiness)
        win = sum(daily.get((d0 - timedelta(days=k)).isoformat(), 0.0) for k in range(7))
        wk_rd = E.mean([channel_readiness(ready.get((d0 - timedelta(days=k)).isoformat(), (1.0, {}, 100)), ch)
                        for k in range(7)]) or 1.0
        ceil_s = cap * (1 + m_s * bh) * rd * bf if cap else None
        ceil_w = cw * (1 + m_w) * wk_rd if cw else None
        # room left at this session's pace: the nearer of the per-run and the weekly ceiling
        rooms = [x for x in ((ceil_s - v) if ceil_s is not None else None, (ceil_w - win) if ceil_w else None) if x is not None]
        room = min(rooms) if rooms else None
        mins = s.get("durationMin") or 0
        rate = v / mins if mins > 0 and v > 0 else None
        out[s["id"]] = {
            "ch": ch, "label": spec["label"], "unit": spec["unit"], "grade": spec["grade"],
            "value": _fmt(v, ch), "cap": _fmt(cap, ch) if cap else None,
            "ceiling": _fmt(ceil_s, ch) if cap else None,
            "over": _fmt(max(0.0, v - ceil_s), ch) if ceil_s is not None else None,
            "ratio": round(r, 2) if r is not None else None, "band": _band_word(r, m_s),
            "readinessScore": rd_score, "left": round(left, 2), "unabsorbed": _fmt(v * left, ch),
            "body": b["reasons"] if (b and (bf < 1 or bh < 1)) else None,
            "weekCap": _fmt(cw, ch) if cw else None, "weekPct": round(100 * v / cw) if cw else None,
            "weekBefore": _fmt(max(0.0, win - v), ch), "weekCeiling": _fmt(ceil_w, ch) if ceil_w else None,
            "weekOver": _fmt(max(0.0, win - ceil_w), ch) if ceil_w else None,
            "room": _fmt(max(0.0, room), ch) if room is not None else None,
            "roomBy": None if room is None else ("session" if ceil_s is not None and room == ceil_s - v else "week"),
            "extraMin": (round(max(0.0, room) / rate) if (rate and room is not None) else None),
            "pts": round(max(p_ses, p_lat) * spec["w"], 1),
            "ptsKind": "session" if p_ses > 0 and p_ses >= p_lat else "latent" if p_lat > 0 else None,
            "_resid": v * left,
        }
    return out


def _day_readiness(sessions, day, t_iso, ready, nights, hrmax, rhr, cache) -> dict | None:
    """Readiness around a day's training (railway#110): that morning, the estimate right
    after the day's sessions (the v0.8.6 after-session rule) and the next morning as the
    watch measured it. None without the day's data."""
    if day in cache:
        return cache[day]
    _f, parts, before = ready.get(day, (1.0, {}, 100))
    known = day in nights or bool(parts)
    eff = day_effort(sessions, day, hrmax, rhr)
    after = readiness_from({**parts, "session": eff["deficit"]})[1] if (known and eff and eff["deficit"] > 0) else (before if known else None)
    nd = (_d(day) + timedelta(days=1)).isoformat()
    nxt = None
    if nd <= t_iso:
        _nf, n_parts, n_score = ready.get(nd, (1.0, {}, 100))
        nxt = n_score if (nd in nights or n_parts) else None
    out = {"before": before if known else None, "after": after, "next": nxt,
           "band": eff["band"] if eff else None} if (known or nxt is not None) else None
    cache[day] = out
    return out


def _history(sessions, hist_ch, channels, today, ready=None, nights=frozenset(), hrmax=None, rhr=None) -> list:
    """The Zátěž tab's activity history (newest first). Each channel's points in today's
    score are attributed to the sessions behind them: the one session (or the one
    fading jump) that sets the channel, or, when the unabsorbed 7-day load sets it,
    every session by its share of that residual load. Runs list the running channels
    and the all-sport load, other sports only the all-sport load (strength also its
    own strength channel). Channels a session didn't load (0 m of descent) are left out."""
    for ch, rows in hist_ch.items():
        c = channels.get(ch) or {}
        pts, drv = c.get("pts") or 0, c.get("driver")
        resid = sum(x["_resid"] for x in rows.values())
        for sid, x in rows.items():
            share = 0.0
            if pts and drv == "session" and (c.get("session") or {}).get("id") == sid:
                share = 1.0
            elif pts and drv == "latent" and (c.get("latent") or {}).get("id") == sid:
                share = 1.0
            elif pts and drv == "week" and resid > 0:
                share = x["_resid"] / resid
            x["share"] = round(share, 2)
            x["scorePts"] = round(pts * share, 1)
            x["driver"] = drv if share else None
        for x in rows.values():
            x.pop("_resid", None)
    out = []
    t_iso = today.isoformat()
    rcache: dict = {}
    for s in sorted(sessions, key=lambda s: (s["date"], s["id"]), reverse=True):
        age = (today - _d(s["date"])).days
        if age < 0 or age >= HISTORY_DAYS:
            continue
        order = (RUN_CHANNELS + ("systemic",) if s["run"] else ("intensity", "systemic") if s.get("sport") in CROSS_CARDIO
                 else ("systemic", "strength"))
        chans = [hist_ch[ch][s["id"]] for ch in order
                 if s["id"] in hist_ch.get(ch, {}) and hist_ch[ch][s["id"]]["value"]]
        if not chans:
            continue
        known = [c for c in chans if c["ratio"] is not None]
        peak = max(known, key=lambda c: c["ratio"]) if known else None
        sport = s.get("sport") or "running"
        # railway#110 — over a ceiling already, or how much longer at the same pace
        over = [{"ch": c["ch"], "label": c["label"], "unit": c["unit"], "over": c["over"]} for c in chans if c.get("over")]
        wover = [{"ch": c["ch"], "label": c["label"], "unit": c["unit"], "over": c["weekOver"]} for c in chans if c.get("weekOver")]
        timed = [c for c in chans if c.get("extraMin") is not None]
        lim = min(timed, key=lambda c: c["extraMin"]) if timed and not over and not wover else None
        extra = None
        if lim is not None:
            km = (lim["extraMin"] * s["km"] / s["durationMin"]) if (s["run"] and s.get("km") and s.get("durationMin")) else None
            extra = {"min": lim["extraMin"], "km": E.r1(km) if km is not None else None, "ch": lim["ch"],
                     "label": lim["label"], "by": lim["roomBy"]}
        rdy = _day_readiness(sessions, s["date"], t_iso, ready, nights, hrmax, rhr, rcache) if ready is not None else None
        out.append({
            "id": s["id"], "date": s["date"], "title": s["title"], "sport": sport, "run": s["run"],
            "sportLabel": "běh" if s["run"] else SPORT_CS.get(sport, "jiný sport"),
            "km": E.r1(s["km"]) if s.get("km") else None, "durationMin": E.rnd(s.get("durationMin")),
            "avgHr": E.rnd(s.get("avgHr")), "rpe": s.get("rpe"), "age": age, "channels": chans,
            "peak": {k: peak[k] for k in ("ch", "label", "ratio", "band")} if peak else None,
            "scorePts": round(sum(c["scorePts"] for c in chans), 1),
            "over": over, "weekOver": wover, "extra": extra, "readiness": rdy,
        })
    return out


# v0.9.0 — running too little is a risk of its own: injured shares fell from 71.8 % at
# ≤ 1 run a week to 24.7 % at 7 (Abrahamson et al., 2025, n = 7 391), < 2 h a week
# had HR 3.29 and < 2 sessions HR 2.41, and both interacted with a previous injury
# (RERI 4.69; Malisoux et al., 2015). An under-conditioned runner's tissues tolerate
# less of a jump, so the safety margins shrink (more with an injury history). The
# factors are working assumptions; the thresholds are the cohorts'.
UNDER_RUNS_WEEK, UNDER_MIN_WEEK = 2.0, 120.0
UNDER_FACTOR, UNDER_WITH_INJURY = 0.8, 0.8
SHRINK_MIN = 0.4


def underconditioning(sessions, today, first_day: str) -> dict | None:
    """{runsPerWeek, minPerWeek, factor} when the last 4 weeks averaged < 2 runs or
    < 120 running minutes a week (needs 4 weeks of history), else None."""
    if (today - _d(first_day)).days < 28:
        return None
    runs = [s for s in sessions if s["run"] and 0 <= (today - _d(s["date"])).days < 28]
    per_week = len(runs) / 4
    minutes = sum(s.get("durationMin") or 0 for s in runs) / 4
    if per_week >= UNDER_RUNS_WEEK and minutes >= UNDER_MIN_WEEK:
        return None
    return {"runsPerWeek": round(per_week, 1), "minPerWeek": round(minutes), "factor": UNDER_FACTOR}


# v0.10.0 — pain and injury act on the capacity itself (owner decision 2026-09-30); the
# pain points on Příznaky stay as they are. The rules follow the pain-monitoring model:
# loading may continue with pain up to 5/10 as long as it settles by the next morning and
# doesn't grow week to week, which did no harm compared with rest in a randomised trial
# (Silbernagel et al., 2007; the engine's pain_monitor implements the same rules). So:
#   • pain inside the model → the capacity holds: no margin above what was demonstrated
#     (the margin shrinks with the site's pain episode, which v0.9.3 already fades),
#   • pain over the model (above 5/10 or growing week to week) → one step back on the
#     graded-return scale (75 %, working assumption), half of that on hard minutes,
#   • worse pain the morning after a run (the model's "no lasting reaction") or an active
#     injury → no running today (ceilings 0, as the recommendation already says),
#   • a resolved injury → the weekly capacity is capped at the graded return (50 / 75 / 90 %
#     of the pre-injury week, no hard minutes for 14 days), the same numbers the plan uses.
# The systemic channel (all-sport HR load) and strength are not touched: cross-training
# stays available. Sessions are judged by the state the day before (before the run).
RUN_CH = ("volume", "intensity", "descent", "ascent")
BODY_PAIN_OVER = 5
BODY_STEP = 0.75
BODY_INTENSITY_SHARE = 0.5
BODY_MIN_LEVEL = 0.1        # a site episode below this has practically ended
BODY_SCORE_FLOOR = 0.5      # a run done on a day with ceiling 0 still scores against half capacity (first return step)


def body_state(data, rid, day: str) -> dict:
    """{factor{ch}, hold{ch}, score{ch}, kind, reasons[], site, rtr} for the end of `day`:
    `factor` scales the capacity (0 = no running), `hold` scales the safety margin
    (0 = no room above the demonstrated capacity), `score` = factor floored for scoring."""
    with E.today_pinned(_d(day)):
        snap = data.as_of(day)
        inj = (E.injury(snap, rid) or {}).get("active")
        rtr = None if inj else E.return_to_run(snap, rid)
        eps = {} if inj else E.pain_episodes(snap, rid)
        pmon = {} if inj else (E.pain_monitor(snap, rid) or {})
    factor = {ch: 1.0 for ch in CHANNELS}
    hold = {ch: 1.0 for ch in CHANNELS}
    reasons, kind, site = [], None, None
    live = sorted((e for e in eps.values() if e["level"] >= BODY_MIN_LEVEL), key=lambda e: (-e["level"], -(e["ref"] or 0)))
    if inj:
        kind, site = "injury", inj.get("site")
        for ch in RUN_CH:
            factor[ch] = 0.0
        reasons.append(f"aktivní zranění ({site}), dnes bez běhu")
    elif pmon.get("morningWorse"):
        mw = pmon["morningWorse"]
        kind, site = "painMorning", mw.get("site")
        for ch in RUN_CH:
            factor[ch] = 0.0
        reasons.append(f"ráno po běhu víc bolesti ({mw.get('morning')}/10) než během něj, dnes bez běhu")
    elif live:
        ep = live[0]
        site, lvl = ep["label"], ep["level"]
        if pmon.get("trend") is not None or (ep["ref"] or 0) > BODY_PAIN_OVER:
            kind = "painOver"
            for ch in RUN_CH:
                share = BODY_INTENSITY_SHARE if ch == "intensity" else 1.0
                factor[ch] = 1 - (1 - BODY_STEP) * lvl * share
            why = "roste týden od týdne" if pmon.get("trend") is not None else f"{ep['ref']}/10"
            reasons.append(f"bolest {site} ({why}) nad hranicí sledování bolesti, kapacita ×{E.cz_text(str(round(factor['volume'], 2)))}")
        else:
            kind = "painHold"
            for ch in RUN_CH:
                hold[ch] = 1 - lvl
            reasons.append(f"bolest {site} ({ep['ref']}/10), kapacita drží bez rezervy navíc")
    if rtr:
        kind = kind or "return"
        if rtr.get("noQuality"):
            factor["intensity"] = 0.0
        reasons.append(f"návrat po zranění, {rtr['week']}. týden ({round(rtr['factor'] * 100)} % týdne před zraněním)")
    return {"factor": factor, "hold": hold, "score": {ch: max(f, BODY_SCORE_FLOOR) for ch, f in factor.items()},
            "kind": kind, "reasons": reasons, "site": site, "rtr": rtr}


def _rtr_week_cap(daily, rtr, ch):
    """The weekly capacity a graded return allows: the average week of the 4 weeks before
    the injury × this week's factor (guidance.reference uses the same numbers)."""
    if not rtr or ch not in RUN_CH:
        return None
    d0 = _d(rtr["injuryAt"])
    pre = sum(daily.get((d0 - timedelta(days=k)).isoformat(), 0.0) for k in range(1, 29)) / 4
    return pre * rtr["factor"] if pre > 0 else None


def assess_capacity(db, rid, frailty=1.0, runner=None, with_history=False) -> dict:
    """The v3 load axis + today's capacity picture. Returns
    {score, signals[], channels{}, readiness{}, zones[], relativeEffort{}, margins{}}
    (+ history[] — every session of the last 28 days broken down by the channels it
    loads — with `with_history`, for the Zátěž tab's activity history)."""
    today = E.today_date()
    t_iso = today.isoformat()
    db = D.of(db, rid)
    runs_only = E.acts(db, rid, "load")
    hrmax, rhr = E.hr_bounds(runs_only, E.daily(db, rid, 180), runner.birth_year if runner else None,
                             runner.hr_max if runner else None)
    sessions = run_exposures(db, rid, hrmax, rhr)
    nt_days = nontraining_daily(db, rid)
    pain = pain_dates(db, rid)
    reports = report_dates(db, rid)
    first_day = min((s["date"] for s in sessions), default=t_iso)
    shrink = E.clamp(1 - 2.5 * (frailty - 1), 0.5, 1.0)
    under = underconditioning(sessions, today, first_day)
    if under:
        shrink *= under["factor"] * (UNDER_WITH_INJURY if frailty > 1.0 else 1.0)
        under["withInjury"] = frailty > 1.0
    shrink = max(shrink, SHRINK_MIN)
    m_s, m_w = MARGIN_SESSION * shrink, MARGIN_WEEK * shrink
    recent_days = [(today - timedelta(days=k)).isoformat() for k in range(0, 28)]
    absorb_days = [(today - timedelta(days=k)).isoformat() for k in range(ABSORB_DAYS - 1, -1, -1)]   # oldest → today
    ready = readiness_by_day(db, rid, absorb_days)
    nights = {m.date[:10] for m in db.daily
              if m.date >= absorb_days[0] and (m.hrv_ms is not None or m.resting_hr is not None or m.sleep_h is not None)}
    r_today, parts_today, score_today = ready.get(t_iso, (1.0, {}, 100))
    # v0.8.6: the shown readiness also reflects today's sessions (the capacity factor that
    # sizes limits and drives absorption keeps the morning value, so nothing is cut twice)
    after = after_session(sessions, t_iso, t_iso in nights, hrmax, rhr)
    morning_score, parts_now = score_today, dict(parts_today)
    if after and after["deficit"] <= 0:
        after = None
    # v0.10.4: and the day outside training so far (load above the usual day, raised resting HR)
    dn = day_now(db, rid, sessions, nt_days, t_iso)
    if after or dn:
        after = after or {"deficit": 0.0, "today": None, "carry": None}
        if after["deficit"] > 0:
            parts_now["session"] = after["deficit"]
        sess_score = readiness_from(parts_now)[1]
        after["sessionDrop"] = morning_score - sess_score
        for key, k in (("dayLoad", "nt"), ("dayStressNow", "stress")):
            if dn and dn.get(k):
                parts_now[key] = dn[k]["deficit"]
        after["nt"] = (dn or {}).get("nt")
        after["stress"] = (dn or {}).get("stress")
        _f, score_now = readiness_from(parts_now)
        after["dayDrop"] = sess_score - score_now
        after["drop"] = morning_score - score_now
        score_today = score_now
        if not after["drop"]:
            after = None
    wk_ready = E.mean([ready.get(d, (1.0, {}))[0] for d in recent_days[:7]]) or 1.0
    # v0.10.0 — pain / injury per day (cached), judged the day before a session
    body_cache: dict = {}

    def body_on(day):
        if day not in body_cache:
            body_cache[day] = body_state(db, rid, day)
        return body_cache[day]

    def body_before(day):
        return body_on((_d(day) - timedelta(days=1)).isoformat())
    b_today = body_on(t_iso)

    channels, scores, drivers = {}, {}, {}
    hist_ch: dict = {}
    tol: dict = {}
    runs_pool = [s for s in sessions if s["run"]]
    cardio_pool = [s for s in sessions if s["run"] or s.get("sport") in CROSS_CARDIO]   # v0.10.5: Intenzita
    strength_pool = [s for s in sessions if s.get("sport") == "strength"]
    active_days = {s["date"] for s in sessions}
    since = (today - timedelta(days=ITEMS_LOOKBACK)).isoformat()
    for ch, spec in CHANNELS.items():
        pool = (sessions if ch == "systemic" else strength_pool if ch == "strength"
                else cardio_pool if ch == "intensity" else runs_pool)
        items = channel_items(pool, ch, pain, tol, reports, active_days, since)
        rates = night_rates(ch, absorb_days, ready, nights)
        # --- per session: the recent session whose exceedance is still the largest
        # after the nights since it (railway#100); a big jump keeps a latent floor
        worst = None
        worst_r = None          # unrounded, for the v3 sandbox's exact replay
        worst_p = 0.0
        latent = (0.0, None, None, None)
        for s in pool:
            v = s["exp"].get(ch)
            if v is None:
                continue
            age = (today - _d(s["date"])).days
            if age < 0 or age >= 28:
                continue
            cap = session_capacity(items, s["date"], ch)
            if cap is None:
                continue
            entry = ready.get(s["date"], (1.0, {}, 100))
            rd, rd_score = channel_readiness(entry, ch), entry[2]
            b = body_before(s["date"])
            r = v / (cap * rd * b["score"][ch])
            if age <= 6:
                left = absorbed_left(rates, s["date"], t_iso, absorb_days)
                p = band_points(r, m_s * b["hold"][ch]) * left
                if worst is None or p > worst_p or (p == worst_p and (worst_r is None or r > worst_r)):
                    worst_p, worst_r = p, r
                    worst = {"id": s["id"], "ratio": round(r, 2), "value": _fmt(v, ch), "cap": _fmt(cap, ch), "date": s["date"],
                             "title": s["title"], "readiness": rd, "readinessScore": rd_score,
                             "left": round(left, 2),
                             "body": b["reasons"] if (b["factor"][ch] < 1 or b["hold"][ch] < 1) else None,
                             "_hold": b["hold"][ch]}
            lp = latent_points(r, age)
            if lp > latent[0]:
                latent = (lp, s["date"], round(r, 2), s["id"])
        p_s = worst_p if worst else 0.0
        # --- rolling 7 days
        daily = _daily_sums(pool, ch)
        if ch == "systemic":                 # the day outside training counts in the all-sport load
            for d, v in nt_days.items():
                daily[d] = daily.get(d, 0.0) + v
        capw = weekly_capacity(daily, t_iso, first_day, pain, ch)
        rtr_cap = _rtr_week_cap(daily, b_today["rtr"], ch) if capw is not None else None
        cap_base = capw
        if rtr_cap is not None and rtr_cap < capw:
            capw = rtr_cap
        now_w = sum(daily.get((today - timedelta(days=k)).isoformat(), 0.0) for k in range(7))
        wk_ready_c = E.mean([channel_readiness(ready.get(d, (1.0, {}, 100)), ch) for d in recent_days[:7]]) or 1.0
        # v0.10.0 — the body state over the same 7 days, like readiness: one painful
        # morning mustn't swing the whole week (today's per-run ceiling takes it fully)
        wk_body = [body_on(d) for d in recent_days[:7]]
        wk_bscore = E.mean([b["score"][ch] for b in wk_body]) or 1.0
        wk_bfac = E.mean([b["factor"][ch] for b in wk_body])
        wk_hold = E.mean([b["hold"][ch] for b in wk_body])
        week = None
        p_w = 0.0
        rw = None
        resid_w = residual_week(daily, absorb_days, rates, ch)
        cap_peak = weekly_capacity_residual(daily, t_iso, first_day, pain, ch) if capw is not None else None
        if cap_peak is not None and cap_base:
            cap_peak *= capw / cap_base          # a return-to-run cap scales the peak the same way
        if capw is not None:
            rw = resid_w / ((cap_peak or capw) * wk_ready_c * wk_bscore)
            p_w = band_points(rw, m_w * wk_hold)
            # the ceiling is exactly where the weekly score starts: capacity × the
            # week's average readiness × (1 + margin) — not today's readiness, so
            # the weekly picture doesn't jump with one night's sleep; pain / injury
            # (v0.10.0) likewise by the week's average
            ceil_w = capw * (1 + m_w * wk_hold) * wk_ready_c * wk_bfac
            week = {"now": _fmt(now_w, ch), "residual": _fmt(resid_w, ch), "cap": _fmt(capw, ch), "ratio": round(rw, 2),
                    "capPeak": _fmt(cap_peak, ch) if cap_peak is not None else None,
                    "ceiling": _fmt(ceil_w, ch), "left": _fmt(max(0.0, ceil_w - now_w), ch)}
            if capw != cap_base:
                week["capBase"] = _fmt(cap_base, ch)
        # railway#113 — who carries the unabsorbed 7-day load (the same split as the history)
        contrib = [(s["exp"][ch] * absorbed_left(rates, s["date"], t_iso, absorb_days), s) for s in pool
                   if s["exp"].get(ch) and absorb_days[0] <= s["date"] <= t_iso]
        c_tot = sum(c for c, _ in contrib)
        week_src = [{"id": s["id"], "date": s["date"], "title": s["title"], "sport": s.get("sport"),
                     "value": _fmt(s["exp"][ch], ch), "share": round(c / c_tot, 3)}
                    for c, s in sorted(contrib, key=lambda x: -x[0])[:8] if c_tot > 0 and c / c_tot >= 0.01]
        # feedback #149 — every session of the last 7 days with what it added (the waterfall)
        d7 = (today - timedelta(days=6)).isoformat()
        week7 = [{"id": s["id"], "date": s["date"], "title": s["title"], "sport": s.get("sport"), "run": s["run"],
                  "value": _fmt(s["exp"][ch], ch)}
                 for s in sorted(pool, key=lambda x: (x["date"], str(x["id"])))
                 if s["exp"].get(ch) and d7 <= s["date"] <= t_iso]
        if ch == "systemic":
            week7 += [{"id": f"nt-{d}", "date": d, "title": "Aktivita mimo trénink nad obvyklý den", "sport": "daily", "run": False,
                       "value": _fmt(v, ch)} for d, v in nt_days.items() if d7 <= d <= t_iso]
            week7.sort(key=lambda x: (x["date"], str(x["id"])))
        if with_history:
            hist_ch[ch] = _history_rows(pool, ch, items, rates, ready, daily, first_day, pain, today, t_iso,
                                        absorb_days, m_s, m_w, body_before)
        # --- today's per-run ceiling (capacity from everything before today)
        cap_today = session_capacity(items, (today + timedelta(days=1)).isoformat(), ch)
        # --- the latest jump (plan B1) that doesn't count fully yet: held for
        # JUMP_HOLD_DAYS, then half unless a pain-free report confirmed it
        pending = None
        for day, v, ok, jump, conf in items:
            age = (today - _d(day)).days
            if jump and ok and 0 <= age < 28 and (age < JUMP_HOLD_DAYS or not conf):
                prev = session_capacity(items, day, ch)
                pending = {"date": day, "value": _fmt(v, ch), "ratio": round(v / prev, 2) if prev else None,
                           "countsFrom": (_d(day) + timedelta(days=JUMP_HOLD_DAYS)).isoformat(),
                           "confirmed": conf, "weight": 1.0 if conf else JUMP_UNCONFIRMED}
        raw = max(p_s, p_w, latent[0])
        driver = "session" if raw == p_s and p_s > 0 else "week" if raw == p_w and p_w > 0 else "latent" if raw > 0 else None
        scores[ch] = raw * spec["w"]
        drivers[ch] = driver
        r_today_c = channel_readiness(ready.get(t_iso, (1.0, {}, 100)), ch)
        b_touch = b_today["factor"][ch] < 1 or b_today["hold"][ch] < 1 or (week or {}).get("capBase") is not None
        channels[ch] = {
            "label": spec["label"], "unit": spec["unit"], "grade": spec["grade"], "weight": spec["w"],
            "session": worst, "week": week,
            "ceilingToday": (_fmt(cap_today * (1 + m_s * b_today["hold"][ch]) * r_today_c * b_today["factor"][ch], ch)
                             if cap_today is not None else None),
            "readinessFactor": round(r_today_c, 3),
            "body": ({"factor": round(b_today["factor"][ch], 3), "hold": round(b_today["hold"][ch], 3),
                      "kind": b_today["kind"], "reasons": b_today["reasons"]} if b_touch else None),
            "capSession": _fmt(cap_today, ch) if cap_today is not None else None,
            # the per-run ceiling on a normally recovered day — "this week", not scaled by today's readiness
            "ceilingSession": _fmt(cap_today * (1 + m_s), ch) if cap_today is not None else None,
            "latent": {"pts": round(latent[0], 1), "date": latent[1], "ratio": latent[2], "id": latent[3]} if latent[0] else None,
            "pendingJump": pending, "weekSources": week_src, "week7": week7,
            "raw": round(raw, 1), "driver": driver, "known": worst is not None or week is not None or cap_today is not None,
            "exact": {"rs": worst_r, "rw": rw, "lat": latent[0], "left": worst["left"] if worst else 1.0,
                      "hs": worst.pop("_hold", 1.0) if worst else 1.0, "hw": wk_hold},
        }
    contrib = combine(scores)
    signals = []
    total = 0
    for ch, c in sorted(contrib.items(), key=lambda kv: -kv[1]):
        pts = E.rnd(c)
        channels[ch]["pts"] = pts
        if not pts:
            continue
        total += pts
        info = channels[ch]
        spec = CHANNELS[ch]
        unit = spec["unit"]
        if drivers[ch] == "session":
            s = info["session"]
            val = f"×{s['ratio']}"
            what = "posilování" if ch == "strength" else "trénink" if ch == "systemic" else "běh"
            detail = (f"Nejnáročnější {what} 7 dní ({_cz(s['date'])}): {s['value']} {unit} proti vaší prokázané "
                      f"kapacitě {s['cap']} {unit}" + (f" · připravenost ten den {s['readinessScore']} %" if s["readinessScore"] < 97 else "")
                      + (f" · den předem: {'; '.join(s['body'])}" if s.get("body") else "")
                      + (f" · nevstřebáno zhruba {round(s['left'] * 100)} %" if s["left"] < 0.99 else ""))
        elif drivers[ch] == "week":
            w = info["week"]
            val = f"×{w['ratio']}"
            detail = (f"Nevstřebaná zátěž {w['residual']} {unit} (týdenní ekvivalent, za 7 dní celkem {w['now']} {unit}) "
                      + (f"proti vaší obvyklé týdenní špičce {w['capPeak']} {unit} (kapacita {w['cap']} {unit} za 7 dní)"
                         if w.get("capPeak") is not None else f"proti vaší týdenní kapacitě {w['cap']} {unit}")
                      + (f" (bez návratu po zranění {w['capBase']} {unit})" if w.get("capBase") is not None else "")
                      + (f" · dnes: {'; '.join(info['body']['reasons'])}" if info.get("body") and info["body"]["reasons"] else ""))
        else:
            lt = info["latent"]
            val = f"před {(today - _d(lt['date'])).days} dny"
            detail = (f"Doznívá skok ×{lt['ratio']} z {_cz(lt['date'])} — riziko vrcholí 1–4 týdny po prudkém nárůstu.")
        name = {"volume": "Objem nad kapacitou", "intensity": "Intenzita nad kapacitou",
                "descent": "Klesání nad kapacitou", "ascent": "Stoupání nad kapacitou",
                "systemic": "Celková zátěž nad kapacitou", "strength": "Silová zátěž nad kapacitou"}[ch]
        signals.append({"id": f"cap_{ch}", "name": name, "grade": spec["grade"], "pts": pts, "val": E.cz_text(val),
                        "detail": E.cz_text(detail)})
    week7 = [s for s in cardio_pool if 0 <= (today - _d(s["date"])).days < 7 and s.get("zoneMin")]
    zmin = [sum(s["zoneMin"][i] for s in week7) for i in range(len(ZONES))]
    zone7 = {"minutes": [{"z": z, "min": round(m)} for (z, _, _), m in zip(ZONES, zmin)],
             "runs": len([s for s in week7 if s["run"]]), "cross": len([s for s in week7 if not s["run"]]),
             "exact": all(s["zoneExact"] for s in week7)} if week7 else None
    # railway#107 — what lowers readiness now, and what changed since yesterday morning
    y_iso = (today - timedelta(days=1)).isoformat()
    _yf, y_parts, y_score = ready.get(y_iso, (1.0, {}, 100))
    readiness = {"today": r_today, "score": score_today, "label": readiness_label(score_today),
                 "parts": parts_now, "week": round(wk_ready, 3),
                 "morningScore": morning_score, "afterSession": after,
                 "effects": readiness_effects(parts_now), "morningEffects": readiness_effects(parts_today),
                 "yesterday": {"score": y_score, "parts": y_parts, "effects": readiness_effects(y_parts),
                               "known": y_iso in nights or bool(y_parts)},
                 "known": t_iso in nights or bool(parts_today),
                 "inputs": readiness_inputs(db, rid, t_iso)}
    out = {
        "score": total, "signals": signals, "channels": channels, "zones7d": zone7,
        "readiness": readiness,
        "margins": {"session": round(m_s, 3), "week": round(m_w, 3), "frailty": round(frailty, 2),
                    "underconditioned": under},
        "zones": hr_zones(hrmax, rhr, getattr(runner, "threshold_hr", None) if runner else None),
        "zoneBasis": "lthr" if (runner is not None and getattr(runner, "threshold_hr", None)
                                and rhr < runner.threshold_hr < hrmax) else "hrr", "hrMax": E.rnd(hrmax), "hrRest": E.rnd(rhr),
        "hrMaxMeasured": bool(runner and runner.hr_max),
        "relativeEffort": relative_effort(sessions, t_iso),
    }
    if with_history:
        out["history"] = _history(sessions, hist_ch, channels, today, ready, nights, hrmax, rhr)
    return out
