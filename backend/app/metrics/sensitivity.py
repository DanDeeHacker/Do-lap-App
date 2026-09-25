"""Engine sensitivity sandbox — a pure, DB-free re-expression of assess()'s
scoring, so the transparency UI can show how each metric drives the individual
axis scores (mechanika / zátěž / příznaky) and the resulting quadrant, and let
you experiment with the thresholds.

Single source of truth guard: the scoring math here MUST match
engine.assess(). tests/test_sensitivity.py replays the seeded runners through
BOTH and asserts the load + mechanics axes (the two that determine the
quadrant) come out identical — so any drift from the live engine fails CI.
"""
from . import capacity as CAP
from .engine import QUAD_EXIT, QUAD_THRESHOLD, clamp, days_between, iso_date, quadrant_of, rnd, today_date

# Canonical load-axis signal ids (some are derived, not tied to one knob) — used
# by the fidelity test to compare simulate() against the live engine per-signal.
_LOAD_SIGNAL_IDS = {
    "session_spike", "spike_latent", "pace_spike", "ewma", "hi_load", "load_creep",
    "mono", "desc", "desc_steep", "aer", "hrv", "rhr", "hrvcv", "tsb", "load_capacity", "taper",
}

AXES = [
    {"id": "load", "label": "Zátěž", "color": "#f6d69a"},
    {"id": "mech", "label": "Mechanika", "color": "#6ce6d3"},
    {"id": "symp", "label": "Příznaky", "color": "#e77a59"},
]

# Each knob: a scalar (or bool) input to the scorer, with the metadata the UI
# needs to render a slider, mark its threshold, and explain what it means.
# `thr` / `dir` describe where the signal switches on ("above"/"below").
KNOBS = [
    # ---------------------------------------------------------------- ZÁTĚŽ
    {"id": "valid", "axis": "load", "label": "Dost dat pro zátěž", "grade": "—", "kind": "bool",
     "default": True, "desc": "Zátěžová osa se počítá až s dostatečnou historií. Vypnuto = některé zátěžové signály se neuplatní."},
    {"id": "sessionSpike", "engine": "v12", "axis": "load", "label": "Skok v jednom běhu", "grade": "B", "unit": "×",
     "min": 0.8, "max": 2.6, "step": 0.01, "default": 1.0, "thr": 1.1, "dir": "above",
     "desc": "Nejnáročnější běh vs. nejnáročnější za předchozích 30 dní (délka nebo intenzita). Nejsilnější jednotlivý signál rizika. Pásma: >1,3 mírné, >2,0 (+100 %) výrazné."},
    {"id": "spikeLatent", "engine": "v12", "axis": "load", "label": "Doznívající skok", "grade": "B", "unit": "",
     "min": 0.0, "max": 1.2, "step": 0.01, "default": 0.0, "thr": 0.0, "dir": "above",
     "desc": "Zbytkové riziko z velkého skoku před 1–4 týdny (dozní­vá lineárně do 28 dní)."},
    {"id": "paceSpike", "axis": "load", "label": "Skok v tempu", "grade": "C", "unit": "×",
     "min": 0.9, "max": 1.5, "step": 0.01, "default": 1.0, "thr": 1.06, "dir": "above",
     "desc": "Nejrychlejší běh za 7 dní vs. medián tempa za 30 dní. Jiný mechanismus než délka (Achillovka/planta/holeň)."},
    {"id": "ratio", "axis": "load", "label": "Poměr zátěže 7:28 (ACWR)", "grade": "C", "unit": "×",
     "min": 0.4, "max": 2.2, "step": 0.01, "default": 1.0, "thr": 1.5, "dir": "above",
     "desc": "Akutní:chronická zátěž. Demoted na kontext — u běžců sám nepředpovídá. >1,5 zvýšené, <0,7 náhlý pokles."},
    {"id": "hiAcute", "engine": "v12", "axis": "load", "label": "Tvrdá práce 7 dní", "grade": "B", "unit": "j.z.",
     "min": 0, "max": 200, "step": 1, "default": 0, "thr": 60, "dir": "above",
     "desc": "Objem vysoké intenzity za 7 dní. Brána pro skok ve vysoké intenzitě (musí být ≥ 60)."},
    {"id": "hiRatio", "engine": "v12", "axis": "load", "label": "Skok ve vysoké intenzitě", "grade": "B", "unit": "×",
     "min": 0.8, "max": 2.5, "step": 0.01, "default": 1.0, "thr": 1.5, "dir": "above",
     "desc": "Poměr akutní:chronické tvrdé práce. Prudký nárůst intenzity na nízké základně. Platí jen když tvrdá práce ≥ 60."},
    {"id": "loadCreep", "engine": "v12", "axis": "load", "label": "Postupný nárůst zátěže", "grade": "C", "unit": "×",
     "min": 0.9, "max": 1.6, "step": 0.01, "default": 1.0, "thr": 1.15, "dir": "above",
     "desc": "Akutní zátěž teď vs. před 2 týdny. Plíživé navyšování. Platí jen když poměr 7:28 < 1,3."},
    {"id": "monotony", "axis": "load", "label": "Monotónnost", "grade": "B", "unit": "",
     "min": 0.5, "max": 4.0, "step": 0.05, "default": 1.0, "thr": 2.4, "dir": "above",
     "desc": "Průměr/SD denní zátěže. Chybí skutečně lehké dny."},
    {"id": "descentSpike", "engine": "v12", "axis": "load", "label": "Nárůst sbíhání", "grade": "C", "unit": "×",
     "min": 0.8, "max": 3.0, "step": 0.01, "default": 1.0, "thr": 1.45, "dir": "above",
     "desc": "Klesání za 7 dní vs. obvyklý týden. Excentrická zátěž kvadricepsů."},
    {"id": "steepSpike", "engine": "v12", "axis": "load", "label": "Strmé klesání (≥10 %)", "grade": "C", "unit": "×",
     "min": 0.8, "max": 3.0, "step": 0.01, "default": 1.0, "thr": 1.5, "dir": "above",
     "desc": "Klesání nad 10% sklonem za 7 dní vs. obvyklý týden."},
    {"id": "aerMean", "engine": "v12", "axis": "load", "label": "Aerobní decoupling", "grade": "B", "unit": "%",
     "min": 0.0, "max": 15.0, "step": 0.1, "default": 0.0, "thr": 5.5, "dir": "above",
     "desc": "Tep se v druhé půli odpojuje od tempa — kardiovaskulární drift."},
    {"id": "hrvZ", "engine": "v12", "axis": "load", "label": "HRV (z-skóre)", "grade": "B", "unit": "z",
     "min": -3.0, "max": 3.0, "step": 0.1, "default": 0.0, "thr": -1.0, "dir": "below",
     "desc": "Odchylka HRV od baseline. Potlačená HRV (z ≤ −1) = únava/přetížení. Vstupuje i do interakce zátěž×kapacita."},
    {"id": "rhrZ", "engine": "v12", "axis": "load", "label": "Klidový tep (z-skóre)", "grade": "B", "unit": "z",
     "min": -3.0, "max": 3.0, "step": 0.1, "default": 0.0, "thr": 1.2, "dir": "above",
     "desc": "Odchylka klidového tepu od baseline. Zvýšený (z ≥ 1,2) = zátěž/nemoc. Vstupuje i do interakce zátěž×kapacita."},
    {"id": "hrvCvRatio", "engine": "v12", "axis": "load", "label": "Kolísání HRV mezi dny", "grade": "C", "unit": "×",
     "min": 0.6, "max": 2.5, "step": 0.01, "default": 1.0, "thr": 1.4, "dir": "above",
     "desc": "Den-k-dni variabilita HRV vs. obvyklá."},
    {"id": "tsbRel", "engine": "v12", "axis": "load", "label": "Bilance zátěže (TSB/chronická)", "grade": "C", "unit": "",
     "min": -0.6, "max": 0.4, "step": 0.01, "default": 0.0, "thr": -0.12, "dir": "below",
     "desc": "Fitness (42d) − akutní zátěž, poměrem k chronické. Záporná = akutní předbíhá vybudovanou."},
    {"id": "daysToRace", "axis": "load", "label": "Dní do závodu", "grade": "C", "unit": "dní",
     "min": -1, "max": 30, "step": 1, "default": -1, "thr": 21, "dir": "below",
     "desc": "−1 = žádný závod. Blízký závod (≤ 21 dní) přitíží jen když je zátěž už zvýšená."},
    # ---------------------------------------------------------------- MECHANIKA
    {"id": "tavrZ", "axis": "mech", "label": "Vertikální poměr (z)", "grade": "B", "unit": "z",
     "min": -2.0, "max": 4.0, "step": 0.05, "default": 0.0, "thr": 0.2, "dir": "above",
     "desc": "Drift vertikálního poměru proti vaší normě (terénně očištěný). Mrtvá zóna 0,2, strop z = 4, váha 17."},
    {"id": "gctZ", "axis": "mech", "label": "Kontakt se zemí (z)", "grade": "B", "unit": "z",
     "min": -2.0, "max": 4.0, "step": 0.05, "default": 0.0, "thr": 0.2, "dir": "above",
     "desc": "Drift doby kontaktu se zemí (normalizováno na kadenci). Mrtvá zóna 0,2, váha 13."},
    {"id": "cadZ", "axis": "mech", "label": "Kadence (z)", "grade": "C", "unit": "z",
     "min": -4.0, "max": 2.0, "step": 0.05, "default": 0.0, "thr": -0.2, "dir": "below",
     "desc": "Drift kadence. Klesající kadence (záporné z) je rizikový směr. Mrtvá zóna 0,2, váha 10."},
    {"id": "voscZ", "axis": "mech", "label": "Vertikální oscilace (z)", "grade": "C", "unit": "z",
     "min": -2.0, "max": 4.0, "step": 0.05, "default": 0.0, "thr": 0.2, "dir": "above",
     "desc": "Drift vertikální oscilace. Mrtvá zóna 0,2, váha 10."},
    {"id": "balExcursion", "axis": "mech", "label": "Symetrie kontaktu (odchylka)", "grade": "B", "unit": "p.b.",
     "min": 0.0, "max": 4.0, "step": 0.05, "default": 0.0, "thr": 0.4, "dir": "above",
     "desc": "Posun symetrie kontaktu vlevo/vpravo v procentních bodech. Mrtvá zóna 0,4, strop 3, váha 22."},
    {"id": "decTrend", "axis": "mech", "label": "Odolnost proti únavě (trend)", "grade": "C", "unit": "/běh",
     "min": -0.5, "max": 1.0, "step": 0.01, "default": 0.0, "thr": 0.15, "dir": "above",
     "desc": "Roste-li rozpad techniky v poslední třetině běhu z běhu na běh."},
    {"id": "gaitCvRatio", "axis": "mech", "label": "Kolísavější mechanika", "grade": "C", "unit": "×",
     "min": 0.7, "max": 3.0, "step": 0.01, "default": 1.0, "thr": 1.5, "dir": "above",
     "desc": "Rozptyl mechaniky kolem vlastní normy vs. dřív — časná nervosvalová únava."},
    # ---------------------------------------------------------------- PŘÍZNAKY
    {"id": "checkinPain", "axis": "symp", "label": "Bolest v check-inu", "grade": "A", "unit": "/10",
     "min": 0, "max": 10, "step": 1, "default": 0, "thr": 1, "dir": "above",
     "desc": "Základ: 1–2 → 8 b., 3–5 → 26 b., ≥6 → 44 b. Lokalizace/recidiva přidává bonus níže."},
    {"id": "painRunRelevant", "axis": "symp", "label": "Bolest je běžecky relevantní", "grade": "A", "kind": "bool",
     "default": True, "desc": "Dolní končetina / běžecké přetížení. Brána pro bonusy za recidivu."},
    {"id": "painRecent2", "axis": "symp", "label": "Bolest — stejné místo za 2 dny", "grade": "A", "unit": "×",
     "min": 0, "max": 5, "step": 1, "default": 0, "thr": 2, "dir": "above",
     "desc": "Neustupující bolest mezi běhy (back-to-back). ≥ 2 přidává silný bonus."},
    {"id": "painRecurrence28", "axis": "symp", "label": "Bolest — recidiva za 28 dní", "grade": "A", "unit": "×",
     "min": 0, "max": 10, "step": 1, "default": 0, "thr": 3, "dir": "above",
     "desc": "Opakování na stejném místě za 28 dní. ≥ 3 přidává bonus (mírnější než back-to-back)."},
    {"id": "priorRegionOverlap", "axis": "symp", "label": "Bolest v místě dřívějšího zranění", "grade": "A", "kind": "bool",
     "default": False, "desc": "Recidiva ve stejné oblasti — v literatuře nejsilnější rizikový faktor (+8 b.)."},
    {"id": "soreness", "axis": "symp", "label": "Svalová únava", "grade": "B", "unit": "/10",
     "min": 0, "max": 10, "step": 1, "default": 0, "thr": 7, "dir": "above",
     "desc": "Self-report po tréninku. ≥ 7 přidává 10 b."},
    {"id": "stress", "axis": "symp", "label": "Vnímaná únava", "grade": "C", "unit": "/10",
     "min": 0, "max": 10, "step": 1, "default": 0, "thr": 6, "dir": "above",
     "desc": "Self-report únavy v check-inu. Předchází poklesu HRV/RHR."},
    {"id": "sleepDebt", "axis": "symp", "label": "Spánkový dluh", "grade": "B", "unit": "h/týd",
     "min": -4.0, "max": 14.0, "step": 0.5, "default": 0.0, "thr": 4, "dir": "above",
     "desc": "Deficit spánku za týden. ≥ 4 h přidává body. Vstupuje i do interakce zátěž×kapacita."},
    {"id": "sleepRegRatio", "axis": "symp", "label": "Nepravidelnost spánku", "grade": "C", "unit": "×",
     "min": 0.6, "max": 3.0, "step": 0.01, "default": 1.0, "thr": 1.5, "dir": "above",
     "desc": "Kolísání délky spánku vs. obvyklé."},
    {"id": "sleepEff", "axis": "symp", "label": "Efektivita spánku", "grade": "C", "unit": "podíl",
     "min": 0.6, "max": 1.0, "step": 0.01, "default": 1.0, "thr": 0.85, "dir": "below",
     "desc": "Prospáno / v posteli. Pod 0,85 = roztříštěný spánek."},
    {"id": "feelingTrend", "axis": "symp", "label": "Pocit z běhu (trend)", "grade": "C", "unit": "/běh",
     "min": -0.6, "max": 0.6, "step": 0.01, "default": 0.0, "thr": -0.12, "dir": "below",
     "desc": "Klesající sebehodnocení po trénincích (≥ 6 zápisů). ≤ −0,12 přidává 10 b."},
    {"id": "stiffnessIgnore", "axis": "symp", "label": "Trénink navzdory ztuhlosti", "grade": "C", "unit": "podíl",
     "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.0, "thr": 0.5, "dir": "above",
     "desc": "Podíl běhů, kdy runner při ztuhlých nohou přesto tvrdě trénoval (RPE ≥ 6). ≥ 0,5 přidává body."},
    {"id": "injurySeverity", "axis": "symp", "label": "Nahlášené zranění (OSTRC)", "grade": "A", "unit": "/100",
     "min": 0, "max": 100, "step": 1, "default": 0, "thr": 1, "dir": "above",
     "desc": "Závažnost aktivního zranění. Potvrzené fyziem váží víc (×0,5, strop 46) než self-report (×0,34, strop 32)."},
    {"id": "injuryConfirmed", "axis": "symp", "label": "Zranění potvrzené fyziem", "grade": "A", "kind": "bool",
     "default": False, "desc": "Fyzioterapeutem potvrzené zranění (grade A, vyšší strop)."},
    {"id": "complaintDays", "axis": "symp", "label": "Obtíže napříč místy (dní/28)", "grade": "B", "unit": "dní",
     "min": 0, "max": 15, "step": 1, "default": 0, "thr": 3, "dir": "above",
     "desc": "Počet dní s bolestí (jakékoli místo) za 28 dní. Citlivější (méně specifický) signál než recidiva."},
    {"id": "priorInjuryMonths", "axis": "symp", "label": "Zranění v anamnéze (před měsíci)", "grade": "A", "unit": "měs.",
     "min": -1, "max": 24, "step": 1, "default": -1, "thr": 12, "dir": "below",
     "desc": "−1 = žádné. ≤ 12 měsíců přidává body a zvyšuje křehkost (frailty) — násobí zátěž i mechaniku."},
]

# `engine`: "v12" = only the Standardní/Citlivý load axis, "v3" = only the Kapacitní
# one; no key = shared. `hidden` knobs carry exact live values (so "Načíst moje
# data" reproduces the live score) but get no slider.
_V3_NAME = {"volume": "Objem nad kapacitou", "intensity": "Intenzita nad kapacitou", "descent": "Klesání nad kapacitou",
            "ascent": "Stoupání nad kapacitou", "systemic": "Celková zátěž nad kapacitou"}


def _v3_knobs():
    ks = [
        {"id": "v3ready", "engine": "v3", "axis": "load", "label": "Připravenost dne", "grade": "B", "unit": "",
         "min": 0.7, "max": 1.0, "step": 0.01, "default": 1.0, "thr": 0.95, "dir": "below",
         "desc": "Noční HRV, klidový tep, spánek a check-in (70–100 %). Snižuje kapacitu — stejný běh po špatné "
                 "noci je větší podíl kapacity. Posun přepočítá všechny poměry níže."},
        {"id": "v3readySeed", "engine": "v3", "hidden": True, "axis": "load", "label": "", "grade": "—",
         "min": 0.5, "max": 1.0, "step": 0.01, "default": 1.0, "desc": ""},
    ]
    for ch, spec in CAP.CHANNELS.items():
        w = str(spec["w"]).replace(".", ",")
        ks += [
            {"id": f"v3_{ch}_s", "engine": "v3", "axis": "load", "label": f"{spec['label']} · jeden běh",
             "grade": spec["grade"], "unit": "× kap.", "min": 0.0, "max": 3.2, "step": 0.01, "default": 0.0,
             "thr": 1 + CAP.MARGIN_SESSION, "dir": "above",
             "desc": f"Nejnáročnější běh 7 dní vs. vaše prokázaná kapacita (× připravenost dne). Body nad +10 %: do 1,3× "
                     f"mírné, do 2× střední, nad 2× vysoké. Váha {w}."},
            {"id": f"v3_{ch}_w", "engine": "v3", "axis": "load", "label": f"{spec['label']} · 7 dní",
             "grade": spec["grade"], "unit": "× kap.", "min": 0.0, "max": 3.2, "step": 0.01, "default": 0.0,
             "thr": 1 + CAP.MARGIN_WEEK, "dir": "above",
             "desc": f"Součet posledních 7 dní vs. vaše týdenní kapacita (× připravenost). Body nad +15 %. Váha {w}."},
            {"id": f"v3_{ch}_lat", "engine": "v3", "hidden": True, "axis": "load", "label": "", "grade": "—",
             "min": 0.0, "max": 16.0, "step": 0.1, "default": 0.0, "desc": ""},
        ]
    return ks


_i = max(i for i, k in enumerate(KNOBS) if k["axis"] == "load") + 1
KNOBS[_i:_i] = _v3_knobs()   # right after the v1/v2 load knobs

DEFAULTS = {k["id"]: k["default"] for k in KNOBS}
_BOOL_IDS = {k["id"] for k in KNOBS if k.get("kind") == "bool"}


def _coerce(inp: dict) -> dict:
    """Fill defaults + coerce types, so a partial/garbled payload can't crash the
    scorer or silently score a string."""
    out = dict(DEFAULTS)
    for k, v in (inp or {}).items():
        if k not in DEFAULTS:
            continue
        if k in _BOOL_IDS:
            out[k] = bool(v)
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def _frailty(g) -> float:
    """Injury-history frailty exactly as assess(): 1.04–1.20 for an injury ≤ 12 months ago."""
    pm = g["priorInjuryMonths"]
    return 1 + clamp(0.20 * (1 - pm / 12), 0.04, 0.20) if (pm is not None and 0 <= pm <= 12) else 1.0


def simulate(inp: dict, prev_quadrant: str | None = None, mode: str = "v1") -> dict:
    """Score one hypothetical runner-state from the knob values. Mirrors
    engine.assess()'s scoring (same thresholds, weights, caps, order and the
    frailty multiply), returning the per-signal breakdown, the three axis scores,
    overall/tier and the quadrant. mode="v3" scores the load axis like the
    Kapacitní engine (capacity channels, readiness, co-occurrence; frailty via
    the margins, load weight 0.40)."""
    g = _coerce(inp)
    v3 = mode == "v3"
    valid = bool(g["valid"])
    signals = []
    mech = load = symp = 0.0

    def push(sid, axis, name, grade, pts, val, detail=""):
        nonlocal mech, load, symp
        p = rnd(pts)
        if not p:
            return
        if axis == "mech":
            mech += p
        elif axis == "load":
            load += p
        else:
            symp += p
        signals.append({"id": sid, "axis": axis, "name": name, "grade": grade, "pts": p, "val": val, "detail": detail})

    # ------------------------------------------------------------------ LOAD
    ratio = g["ratio"]
    if v3:
        shrink = clamp(1 - 2.5 * (_frailty(g) - 1), 0.5, 1.0)
        m_s, m_w = CAP.MARGIN_SESSION * shrink, CAP.MARGIN_WEEK * shrink
        scale = g["v3readySeed"] / max(g["v3ready"], 0.5)
        scores, shown = {}, {}
        for ch, spec in CAP.CHANNELS.items():
            rs, rw = g[f"v3_{ch}_s"] * scale, g[f"v3_{ch}_w"] * scale
            ps, pw = CAP.band_points(rs, m_s), CAP.band_points(rw, m_w)
            scores[ch] = max(ps, pw, g[f"v3_{ch}_lat"]) * spec["w"]
            shown[ch] = f"×{round(rs if ps >= pw else rw, 2)}"
        contrib = CAP.combine(scores)
        for ch in sorted(contrib, key=lambda c: -contrib[c]):
            push(f"cap_{ch}", "load", _V3_NAME[ch], CAP.CHANNELS[ch]["grade"], contrib[ch], shown[ch],
                 "Zátěž proti vaší prokázané kapacitě.")
        if valid and g["paceSpike"] > 1.06:
            push("pace_spike", "load", "Skok v tempu", "C", clamp((g["paceSpike"] - 1.06) * 40, 0, 10), f"×{round(g['paceSpike'], 2)}", "Prudké zrychlení proti obvyklému tempu.")
        if g["monotony"] > 2.4:
            push("mono", "load", "Monotónní trénink", "B", clamp((g["monotony"] - 2.4) * 7, 0, 12), f"{round(g['monotony'], 2)}", "Chybí skutečně lehké dny.")
    else:
        s = g["sessionSpike"]
        if valid and s > 1.1:
            if s > 2.0:
                p, band = clamp((s - 2.0) * 16, 0, 16) + 14, "nad +100 %"
            elif s > 1.3:
                p, band = clamp((s - 1.3) * 20, 0, 14), "+30–100 %"
            else:
                p, band = clamp((s - 1.1) * 25, 0, 6), "+10–30 %"
            push("session_spike", "load", "Skok v jednom běhu", "B", p, f"×{round(s, 2)}", f"Nejnáročnější běh je {band} proti 30 dnům.")
        if valid and g["spikeLatent"] > 0:
            push("spike_latent", "load", "Doznívající skok v zátěži", "B", clamp(g["spikeLatent"] * 22, 0, 16), f"{round(g['spikeLatent'], 2)}", "Doznívá 1–4 týdny po velkém skoku.")
        if valid and g["paceSpike"] > 1.06:
            push("pace_spike", "load", "Skok v tempu", "C", clamp((g["paceSpike"] - 1.06) * 40, 0, 10), f"×{round(g['paceSpike'], 2)}", "Prudké zrychlení proti obvyklému tempu.")
        ratio = g["ratio"]
        if valid and ratio > 1.5:
            push("ewma", "load", "Zvýšený poměr zátěže (7:28)", "C", clamp((ratio - 1.5) * 18, 0, 12) + 2, f"×{round(ratio, 2)}", "Akutní zátěž nad chronickou.")
        elif valid and ratio < 0.7:
            push("ewma", "load", "Náhlý pokles zátěže", "C", 10, f"×{round(ratio, 2)}", "Prudké snížení objemu — riziko při návratu.")
        if valid and g["hiAcute"] >= 60 and g["hiRatio"] > 1.5:
            push("hi_load", "load", "Skok ve vysoké intenzitě", "B", clamp((g["hiRatio"] - 1.5) * 20, 0, 20), f"×{round(g['hiRatio'], 2)}", "Prudký nárůst tvrdé práce na nízké základně.")
        if valid and ratio < 1.3 and g["loadCreep"] >= 1.15:
            push("load_creep", "load", "Postupný nárůst zátěže", "C", clamp((g["loadCreep"] - 1.15) * 30, 0, 10), f"+{round((g['loadCreep'] - 1) * 100)} %", "Plíživé navyšování dva týdny po sobě.")
        if g["monotony"] > 2.4:
            push("mono", "load", "Monotónní trénink", "B", clamp((g["monotony"] - 2.4) * 7, 0, 20), f"{round(g['monotony'], 2)}", "Chybí skutečně lehké dny.")
        if g["descentSpike"] > 1.45:
            push("desc", "load", "Nárůst sbíhání", "C", clamp((g["descentSpike"] - 1.45) * 15, 0, 14), f"×{round(g['descentSpike'], 2)}", "Víc klesání než obvykle.")
        if g["steepSpike"] > 1.5:
            push("desc_steep", "load", "Nárůst strmého klesání (≥10 %)", "C", clamp((g["steepSpike"] - 1.5) * 12, 0, 12), f"×{round(g['steepSpike'], 2)}", "Strmé klesání zatěžuje excentricky víc.")
        if g["aerMean"] > 5.5:
            push("aer", "load", "Aerobní decoupling", "B", clamp((g["aerMean"] - 5.5) * 3, 0, 12), f"{round(g['aerMean'], 1)} %", "Tep se v druhé půli odpojuje od tempa.")
        if g["hrvZ"] <= -1.0:
            push("hrv", "load", "Potlačená HRV", "B", clamp(-g["hrvZ"] * 10, 0, 22), f"z {round(g['hrvZ'], 1)}", "HRV pod baseline.")
        if g["rhrZ"] >= 1.2:
            push("rhr", "load", "Zvýšený klidový tep", "B", clamp(g["rhrZ"] * 8, 0, 18), f"z {round(g['rhrZ'], 1)}", "Klidový tep nad baseline.")
        if g["hrvCvRatio"] >= 1.4:
            push("hrvcv", "load", "Kolísavá HRV mezi dny", "C", clamp((g["hrvCvRatio"] - 1.4) * 14, 0, 10), f"×{round(g['hrvCvRatio'], 2)}", "Den-k-dni variabilita HRV nad obvyklou.")
        if valid and g["tsbRel"] <= -0.12:
            push("tsb", "load", "Nepříznivá bilance zátěže", "C", clamp((-g["tsbRel"] - 0.12) * 90, 0, 12), f"{round(g['tsbRel'], 2)}", "Akutní zátěž předbíhá vybudovanou fitness.")

        # Interaction: a spike on depleted recovery (Bertelsen 2017). Derived from the
        # HRV / RHR / sleep knobs, so the sandbox shows it emerge, not a separate slider.
        cap_parts = [clamp(-g["hrvZ"] / 2.0, 0, 1), clamp(g["rhrZ"] / 2.0, 0, 1), clamp(g["sleepDebt"] / 8.0, 0, 1)]
        capacity_deficit = round(sum(cap_parts) / len(cap_parts), 2)
        spike_sev = max(g["sessionSpike"] - 1, ratio - 1, 0)
        if valid and capacity_deficit >= 0.3 and spike_sev > 0.1:
            push("load_capacity", "load", "Zátěž na sníženou regeneraci", "B", clamp(capacity_deficit * spike_sev * 34, 0, 16),
                 f"deficit {round(capacity_deficit * 100)} %", "Skok v zátěži padá na oslabenou regeneraci.")
    # Taper: gated on the running load total (pre-frailty), like assess().
    dtr = g["daysToRace"]
    if dtr is not None and 0 <= dtr <= 21 and (load >= QUAD_THRESHOLD or ratio > 1.3):
        push("taper", "load", "Blízký závod při zvýšené zátěži", "C", clamp((21 - dtr) / 21 * 14, 4, 14), f"{int(dtr)} dní do závodu", "Zátěž zvýšená těsně před závodem.")

    # ------------------------------------------------------------------ MECH
    # (mag, dead, weight, cap) exactly as engine.assess()'s mech_terms.
    for sid, name, grade, mag, dead, weight, cap, unit, raw in (
        ("tavr", "Vertikální poměr roste", "B", g["tavrZ"], 0.2, 17, 4.0, "z", g["tavrZ"]),
        ("gct", "Prodloužený kontakt se zemí", "B", g["gctZ"], 0.2, 13, 4.0, "z", g["gctZ"]),
        ("cad", "Klesající kadence", "C", -g["cadZ"], 0.2, 10, 4.0, "z", g["cadZ"]),
        ("vosc", "Vyšší vertikální oscilace", "C", g["voscZ"], 0.2, 10, 4.0, "z", g["voscZ"]),
        ("bal", "Posun v symetrii kontaktu", "B", g["balExcursion"], 0.4, 22, 3.0, "p.b.", g["balExcursion"]),
    ):
        push(sid, "mech", name, grade, clamp(mag - dead, 0, cap) * weight, f"{round(raw, 2)} {unit}")
    if g["decTrend"] > 0.15:
        push("dec", "mech", "Klesající odolnost proti únavě", "C", clamp(g["decTrend"] - 0.1, 0, 1.2) * 26, f"{round(g['decTrend'], 2)}/běh")
    if g["gaitCvRatio"] >= 1.5:
        push("gaitcv", "mech", "Kolísavější mechanika", "C", clamp((g["gaitCvRatio"] - 1.5) * 14, 0, 14), f"×{round(g['gaitCvRatio'], 2)}")

    # ------------------------------------------------------------------ SYMP
    pain = g["checkinPain"]
    run_rel = bool(g["painRunRelevant"])
    base = 44 if pain >= 6 else 26 if pain >= 3 else 8 if pain >= 1 else 0
    if base:
        recent2, rec_n = g["painRecent2"], g["painRecurrence28"]
        if run_rel and recent2 >= 2:
            p = base + clamp(recent2 * 8, 8, 26)
            push("pain", "symp", "Neustupující bolest — možné přetížení", "A", p, f"{int(pain)}/10", "Stejné místo opakovaně během ~2 dnů.")
        elif run_rel and rec_n >= 3:
            p = base + clamp((rec_n - 2) * 6, 0, 18)
            push("pain", "symp", "Opakující se bolest", "A", p, f"{int(pain)}/10", "Opakování na stejném místě za 28 dní.")
        else:
            nm = "Bolest při běhu" if base == 44 else "Přetrvávající bolest" if base == 26 else "Mírný diskomfort"
            push("pain", "symp", nm, "A", base, f"{int(pain)}/10")
        if run_rel and bool(g["priorRegionOverlap"]):
            push("pain_prior", "symp", "Bolest v místě dřívějšího zranění", "A", 8, f"{int(pain)}/10", "Recidiva ve stejné oblasti.")
    if g["soreness"] >= 7:
        push("sore", "symp", "Vysoká svalová únava", "B", 10, f"{int(g['soreness'])}/10")
    if g["stress"] >= 6:
        push("fatigue", "symp", "Vysoká vnímaná únava", "C", clamp((g["stress"] - 5) * 2.5, 0, 12), f"{int(g['stress'])}/10")
    if g["sleepDebt"] >= 4:
        push("sleep", "symp", "Spánkový dluh", "B", clamp(g["sleepDebt"] * 2.5, 0, 16), f"−{round(g['sleepDebt'], 1)} h/týd")
    if g["sleepRegRatio"] >= 1.5:
        push("sleepreg", "symp", "Nepravidelná délka spánku", "C", clamp((g["sleepRegRatio"] - 1.5) * 12, 0, 14), f"×{round(g['sleepRegRatio'], 2)}")
    if g["sleepEff"] < 0.85:
        push("sleepeff", "symp", "Nízká efektivita spánku", "C", clamp((0.85 - g["sleepEff"]) * 60, 0, 16), f"{round(g['sleepEff'] * 100)} %")
    if g["feelingTrend"] <= -0.12:
        push("feel", "symp", "Zhoršující se pocit z běhu", "C", 10, f"{round(g['feelingTrend'], 2)}/běh")
    if g["stiffnessIgnore"] >= 0.5:
        push("stiffness", "symp", "Trénink navzdory ztuhlosti nohou", "C", clamp(g["stiffnessIgnore"] * 20, 0, 18), f"{round(g['stiffnessIgnore'] * 100)} %")
    pm = g["priorInjuryMonths"]
    has_prior = pm is not None and 0 <= pm <= 12
    if has_prior:
        push("hist", "symp", "Zranění v anamnéze", "A", clamp(18 * (1 - pm / 12), 6, 18), f"{int(pm)} měs.")
    sev = g["injurySeverity"]
    if sev > 0:
        if bool(g["injuryConfirmed"]):
            push("injury", "symp", "Potvrzené zranění (fyzioterapeut)", "A", clamp(sev * 0.5, 0, 46), f"OSTRC {int(sev)}/100")
        else:
            push("injury", "symp", "Nahlášené zranění", "B", clamp(sev * 0.34, 0, 32), f"OSTRC {int(sev)}/100")
    if g["complaintDays"] >= 3:
        push("complaints", "symp", "Opakované obtíže (napříč místy)", "B", clamp((g["complaintDays"] - 2) * 4, 0, 14), f"{int(g['complaintDays'])} dní / 28")

    # Frailty (injury history) amplifies the objective axes, exactly as assess().
    frailty = 1.0
    if has_prior:
        frailty = 1 + clamp(0.20 * (1 - pm / 12), 0.04, 0.20)
    mech_f = rnd(clamp(mech * frailty, 0, 100))
    load_f = rnd(clamp(load * (1.0 if v3 else frailty), 0, 100))   # v3 applies frailty via the margins
    symp_f = rnd(clamp(symp, 0, 100))
    overall = rnd(clamp(mech_f * 0.38 + load_f * (0.40 if v3 else 0.30) + symp_f * 0.52, 0, 100))
    tier = "alert" if overall >= 70 else ("watch" if overall >= 40 else "ok")
    quadrant = quadrant_of(load_f, mech_f, prev_quadrant)
    return {
        "signals": sorted(signals, key=lambda s: -s["pts"]),
        "mech": mech_f, "load": load_f, "symp": symp_f, "overall": overall,
        "tier": tier, "quadrant": quadrant, "frailty": round(frailty, 2),
        "thresholds": {"quadHi": QUAD_THRESHOLD, "quadLo": QUAD_EXIT},
    }


def sweep(inp: dict, knob_id: str, n: int = 41, prev_quadrant: str | None = None, mode: str = "v1") -> dict:
    """Vary one knob across its full range (others held fixed) and return the axis
    scores + quadrant at each step — the sensitivity curve for that metric."""
    spec = next((k for k in KNOBS if k["id"] == knob_id), None)
    if spec is None:
        return {"knob": knob_id, "series": []}
    base = _coerce(inp)
    if spec.get("kind") == "bool":
        values = [False, True]
    else:
        lo, hi = float(spec["min"]), float(spec["max"])
        values = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    series = []
    for v in values:
        r = simulate({**base, knob_id: v}, prev_quadrant, mode)
        series.append({"value": v, "mech": r["mech"], "load": r["load"], "symp": r["symp"],
                       "overall": r["overall"], "quadrant": r["quadrant"]})
    return {
        "knob": knob_id, "axis": spec["axis"], "label": spec["label"], "unit": spec.get("unit", ""),
        "threshold": spec.get("thr"), "dir": spec.get("dir"), "current": base.get(knob_id),
        "min": spec.get("min"), "max": spec.get("max"), "series": series,
    }


def inputs_from_assessment(a: dict, runner=None) -> dict:
    """Best-effort mapping of a live assessment (+ the runner row for injury
    history) onto the sandbox knobs, so the UI can seed with the runner's own
    current values. Symptom self-report is only partially recoverable from the
    assessment, so those knobs stay at their neutral defaults."""
    def gv(obj, *path, default=None):
        cur = obj
        for p in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(p)
        return cur if cur is not None else default

    L = a.get("loadDetail") or {}
    out = dict(DEFAULTS)
    out.update({
        "valid": bool(L.get("valid")),
        "sessionSpike": L.get("sessionSpike") or 1.0,
        "spikeLatent": L.get("spikeLatent") or 0.0,
        "paceSpike": L.get("paceSpike") or 1.0,
        "ratio": L.get("ratio") or 1.0,
        "hiAcute": L.get("hiAcute") or 0,
        "hiRatio": L.get("hiRatio") or 1.0,
        "loadCreep": L.get("loadCreep") or 1.0,
        "monotony": L.get("monotony") or 1.0,
        "descentSpike": L.get("descentSpike") or 1.0,
        "steepSpike": gv(a, "gradientDescent", "steepSpike", default=1.0) or 1.0,
        "aerMean": gv(a, "aer", "mean", default=0.0) or 0.0,
        "hrvZ": gv(a, "rcv", "hrv", "z", default=0.0) or 0.0,
        "rhrZ": gv(a, "rcv", "rhr", "z", default=0.0) or 0.0,
        "hrvCvRatio": gv(a, "hrvCv", "ratio", default=1.0) or 1.0,
        "sleepDebt": gv(a, "rcv", "sleep", "debt", default=0.0) or 0.0,
        "tsbRel": (L.get("tsbBalance") / L["chronic"]) if L.get("chronic") and L.get("tsbBalance") is not None else 0.0,
        "tavrZ": gv(a, "tavr", "z", default=0.0) or 0.0,
        "gctZ": gv(a, "gct", "z", default=0.0) or 0.0,
        "cadZ": gv(a, "cadence", "z", default=0.0) or 0.0,
        "voscZ": gv(a, "vosc", "z", default=0.0) or 0.0,
        "balExcursion": gv(a, "bal", "excursion", default=0.0) or 0.0,
        "decTrend": gv(a, "dec", "trend", default=0.0) or 0.0,
        "gaitCvRatio": gv(a, "gaitCv", "ratio", default=1.0) or 1.0,
        "sleepRegRatio": gv(a, "sleepReg", "ratio", default=1.0) or 1.0,
        "sleepEff": gv(a, "sleepEff", "now", default=1.0) or 1.0,
    })
    cap = a.get("capacity") or {}
    if cap.get("channels"):
        ready = (cap.get("readiness") or {}).get("today") or 1.0
        out["v3ready"] = out["v3readySeed"] = ready
        for ch in CAP.CHANNELS:
            ex = (cap["channels"].get(ch) or {}).get("exact") or {}
            out[f"v3_{ch}_s"] = ex.get("rs") or 0.0
            out[f"v3_{ch}_w"] = ex.get("rw") or 0.0
            out[f"v3_{ch}_lat"] = ex.get("lat") or 0.0
    inj = a.get("injury") or {}
    active = inj.get("active") or {}
    if active:
        out["injurySeverity"] = active.get("severity") or 0
        out["injuryConfirmed"] = bool(active.get("confirmed"))
    if runner is not None and getattr(runner, "prior_injury", None) and getattr(runner, "prior_injury_months_ago", None) is not None:
        out["priorInjuryMonths"] = runner.prior_injury_months_ago
    if runner is not None and getattr(runner, "goal_date", None):
        d = days_between(iso_date(today_date()), runner.goal_date)
        if d is not None and 0 <= d <= 21:
            out["daysToRace"] = d
    return out
