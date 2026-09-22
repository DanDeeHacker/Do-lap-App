"""Live surface / trail sampling for a run's GPS track (Phase 3b, unlocked by the
Phase-4 streams that now carry lat/lon).

Primary source is OpenStreetMap via the Overpass API — it works worldwide and
returns each nearby way's `surface` and `highway` tags. For Czech runs the
authoritative upgrade is ČÚZK ZABAGED (track/path denotation, forest layer);
`zabaged_surface()` is the CZ-preferred attempt and falls back to OSM on any
failure, so the feature always works even before the ZABAGED endpoint is pinned.

Network-guarded and best-effort: any failure returns a clean result rather than
raising. The classifier (_classify) is pure and unit-tested.
"""
import json
import urllib.parse
import urllib.request

# OSM surface tag → our class (spec Table 7).
_PAVED = {"asphalt", "concrete", "concrete:plates", "paving_stones", "sett", "cobblestone", "paved"}
_COMPACT = {"compacted", "fine_gravel", "gravel", "pebblestone"}
_SOFT = {"ground", "dirt", "earth", "grass", "grass_paver", "sand", "mud", "woodchips", "unpaved"}
# highway values that mean an off-road path rather than a road.
_TRAIL_HW = {"path", "footway", "track", "bridleway", "cycleway", "steps", "pedestrian"}

_CZ_BBOX = (48.5, 12.0, 51.1, 18.9)  # (min_lat, min_lon, max_lat, max_lon)
_UA = "dosslap/0.1 (+https://dosslap)"


def in_czech_republic(track) -> bool:
    if not track:
        return False
    lat = sum(p[0] for p in track) / len(track)
    lon = sum(p[1] for p in track) / len(track)
    return _CZ_BBOX[0] <= lat <= _CZ_BBOX[2] and _CZ_BBOX[1] <= lon <= _CZ_BBOX[3]


def downsample(track, n: int = 12):
    """Evenly spaced sample points along the track to keep the query small."""
    pts = [p for p in track if p and p[0] is not None and p[1] is not None]
    if len(pts) <= n:
        return pts
    step = len(pts) / n
    return [pts[int(i * step)] for i in range(n)]


def _surface_class(surface: str | None) -> str | None:
    if not surface:
        return None
    s = surface.lower()
    if s in _PAVED:
        return "paved"
    if s in _COMPACT:
        return "compact"
    if s in _SOFT:
        return "soft"
    return None


def _classify(ways: list[dict], source: str) -> dict:
    """Tally surface + highway tags from nearby ways into one classification."""
    surf_counts: dict[str, int] = {}
    trail = road = 0
    n_surf = 0
    for w in ways:
        tags = w.get("tags") or w
        cls = _surface_class(tags.get("surface"))
        if cls:
            surf_counts[cls] = surf_counts.get(cls, 0) + 1
            n_surf += 1
        hw = (tags.get("highway") or "").lower()
        if hw in _TRAIL_HW:
            trail += 1
        elif hw:
            road += 1
    surface_class = max(surf_counts, key=surf_counts.get) if surf_counts else "unknown"
    total_hw = trail + road
    return {
        "surfaceClass": surface_class,
        "onTrail": total_hw > 0 and trail >= road,
        "coverage": round(n_surf / len(ways), 2) if ways else 0.0,
        "n": len(ways),
        "source": source,
    }


def overpass_surface(track, timeout: int = 25) -> dict | None:
    """Query Overpass for ways near a handful of track points and classify.
    Returns None on any network/parse failure (caller falls back / reports)."""
    pts = downsample(track)
    if not pts:
        return None
    around = "".join(f"way(around:25,{lat:.5f},{lon:.5f})[highway];" for lat, lon in pts)
    query = f"[out:json][timeout:{timeout - 5}];({around});out tags;"
    body = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter", data=body,
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None
    els = [e for e in data.get("elements", []) if e.get("type") == "way"]
    if not els:
        return None
    return _classify(els, "osm")


def zabaged_surface(track, timeout: int = 20) -> dict | None:
    """CZ-preferred: ČÚZK ZABAGED communications/forest layer via its public
    service. Endpoint/layer names are [Verify] against current ČÚZK docs, so this
    is guarded — any failure returns None and the caller falls back to OSM."""
    try:  # pragma: no cover - live CZ service, endpoint to be pinned
        # Placeholder for the ČÚZK ZABAGED WFS GetFeature (bbox around the track)
        # → parse path type / surface. Until the endpoint is confirmed we return
        # None so Czech runs still get OSM classification.
        return None
    except Exception:  # noqa: BLE001
        return None


def sample_surface(track) -> dict | None:
    """Classify a run's surface from its GPS track. In CZ try ZABAGED first, then
    OSM; elsewhere OSM. Returns None only when nothing could be sampled."""
    if in_czech_republic(track):
        return zabaged_surface(track) or overpass_surface(track)
    return overpass_surface(track)


# Our four engine surface classes bucketing() understands.
def to_engine_surface(classification: dict | None) -> str | None:
    if not classification or classification.get("coverage", 0) < 0.4:
        return None
    if classification.get("onTrail") and classification.get("surfaceClass") != "paved":
        return "trail"
    return "road" if classification.get("surfaceClass") == "paved" else ("trail" if classification.get("surfaceClass") in ("soft", "compact") else None)
