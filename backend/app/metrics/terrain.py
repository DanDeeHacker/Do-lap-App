"""Terrain-aware load (Phase 3 of the Per-Run Measurement Engine spec).

Minetti grade-adjusted distance (L2) and downhill exposure (L3), computed from a
run's elevation profile — a list of {"distance_m", "altitude_m"} points the
activity already carries. No GPS track needed for these.

The authoritative Czech terrain source the product wants — ČÚZK DMR 5G elevation
+ ZABAGED track/surface denotation (open CC BY 4.0, CZ only) — plugs in at the
two seams below once per-point GPS tracks are ingested (Phase 4). Until then we
use the device elevation profile. ZABAGED gives the runner's on-trail/path type
(and a forest-canopy flag that says when to trust DMR 5G over a surface DEM),
which fixes OSM's ~30% surface coverage for Czech runs.
"""


def minetti_cr(i: float) -> float:
    """Energy cost of running (J·kg⁻¹·m⁻¹) at gradient fraction i, from the
    polynomial fitted by Minetti et al. (2002) over i ∈ [−0.45, +0.45]. Clipped
    to that range because the cost function is only defined there. [Evidence]"""
    i = max(-0.45, min(0.45, i))
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


_CR0 = minetti_cr(0.0)  # flat cost, ≈ 3.6 J·kg⁻¹·m⁻¹


def _segments(profile):
    """Yield (segment_metres, gradient_fraction) for each step of the profile."""
    for i in range(len(profile) - 1):
        d0, a0 = profile[i].get("distance_m"), profile[i].get("altitude_m")
        d1, a1 = profile[i + 1].get("distance_m"), profile[i + 1].get("altitude_m")
        if None in (d0, a0, d1, a1):
            continue
        dd = d1 - d0
        if dd > 0:
            yield dd, (a1 - a0) / dd


def grade_adjusted_km(profile, fallback_km: float = 0.0) -> float:
    """L2 — distance scaled by Minetti cost relative to flat, i.e. flat-equivalent
    kilometres. A hilly km costs more than a flat km, so this reflects true
    metabolic/musculoskeletal demand instead of raw distance. Falls back to the
    raw distance when the run has no usable elevation profile."""
    if not profile or len(profile) < 2:
        return fallback_km or 0.0
    metres = 0.0
    seen = False
    for dd, g in _segments(profile):
        metres += dd * minetti_cr(g) / _CR0
        seen = True
    return metres / 1000.0 if seen else (fallback_km or 0.0)


# Downhill running costs LESS energy (Minetti: ≈ 0.6× flat at −10 %) but loads the
# legs MORE: braking/impact forces and eccentric quadriceps work rise with downhill
# grade — normal impact-force peaks +32 % at −6° (≈ −10.5 %) and +54 % at −9°
# (≈ −15.8 %) (Gottschall & Kram 2005), i.e. ≈ +3.2 % per 1 % of downhill grade.
_ECC_PER_GRADE = 3.2


def _load_factor(g: float) -> float:
    if g >= 0:
        return minetti_cr(g) / _CR0
    return max(minetti_cr(g) / _CR0, 1.0 + _ECC_PER_GRADE * min(-g, 0.45))


def load_km(profile):
    """Terrain-LOAD-weighted kilometres for the single-session spike: uphill by
    Minetti's cost (metabolic + propulsive demand), downhill by eccentric/impact
    load. grade_adjusted_km() alone counted a steep downhill run as LESS than its
    flat distance, so the most eccentric-heavy runs could never raise the terrain
    spike. None when the run has no usable elevation profile — such runs must not
    be compared against profile-based ones (raw km vs weighted km)."""
    if not profile or len(profile) < 2:
        return None
    metres, seen = 0.0, False
    for dd, g in _segments(profile):
        metres += dd * _load_factor(g)
        seen = True
    return metres / 1000.0 if seen else None


def descent_weighting(profile):
    """(raw descent m, steepness-weighted descent m) from an elevation profile —
    each metre of drop counts (1 + 3.2·|grade|), the same eccentric/impact factor
    as load_km, so steep descending weighs more than the same drop taken gently.
    (0, 0) without a usable profile."""
    if not profile or len(profile) < 2:
        return (0.0, 0.0)
    raw = weighted = 0.0
    for dd, g in _segments(profile):
        if g < 0:
            drop = -g * dd
            raw += drop
            weighted += drop * (1.0 + _ECC_PER_GRADE * min(-g, 0.45))
    return (raw, weighted)


def downhill_exposure(profile):
    """L3 — (km run at gradient ≤ −5%, gradient-weighted downhill Σ|g|·Δd in km).
    Downhill running is eccentric-heavy and underweighted by metabolic cost
    (Lu et al., 2025), so it is tracked separately from L2."""
    if not profile or len(profile) < 2:
        return (0.0, 0.0)
    steep = weighted = 0.0
    for dd, g in _segments(profile):
        if g <= -0.05:
            steep += dd
        if g < 0:
            weighted += dd * (-g)
    return (steep / 1000.0, weighted / 1000.0)


# --- Phase 4 seams: authoritative Czech terrain (ČÚZK DMR 5G + ZABAGED) -------
# These activate once GPS tracks (lat/lon per point) are ingested. Until then the
# engine uses the device elevation profile above.

def elevation_from_track(track):  # pragma: no cover - Phase 4
    """Sample ČÚZK DMR 5G (2 m raster, bare-earth) along a GPS track inside CZ;
    Copernicus GLO-30 elsewhere. Returns an elevation profile like the one the
    functions above consume. Not yet wired — needs per-point GPS (Phase 4)."""
    raise NotImplementedError("DMR 5G sampling needs GPS tracks (Phase 4)")


def surface_from_track(track):  # pragma: no cover - Phase 4
    """Classify surface/path type by snapping the GPS track to ZABAGED
    communication lines (cesty/pěšiny) + forest layer. CZ only; OSM/Copernicus
    fallback abroad. Not yet wired — needs per-point GPS (Phase 4)."""
    raise NotImplementedError("ZABAGED snapping needs GPS tracks (Phase 4)")
