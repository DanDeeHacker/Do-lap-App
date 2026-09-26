"""Per-run context for Pohyb → Historie běhů: the terrain each run was on and the
weather it was run in, next to its stats. Terrain uses the same buckets the
mechanics engine compares runs within, so the row says exactly which group of
runs a run is judged against."""
from .. import models
from . import engine as E
from . import terrain
from . import weather as W

_SURF = {"road": "silnice", "trail": "terén", "treadmill": "pás", "track": "dráha"}
_SURF_CLASS = {"paved": "zpevněný", "compact": "šotolina", "soft": "měkký", "unknown": "neznámý"}
_GRADE = {"up": "stoupání", "flat": "rovina", "down": "klesání", "rolling": "kopcovitě"}


def terrain_context(a, surface_json=None) -> dict:
    km = a.distance_km or 0
    asc, desc = a.ascent_m, a.descent_m
    grade = E.bucket(a).split("|")[1] if km else None
    out = {
        "surface": a.surface, "surfaceLabel": _SURF.get(a.surface or "", a.surface or "—"),
        "gradeClass": grade, "gradeLabel": _GRADE.get(grade or "", "—"),
        "bucketLabel": E.bucket_label(E.bucket(a)) if km else None,
        "ascentM": E.rnd(asc) if asc is not None else None, "descentM": E.rnd(desc) if desc is not None else None,
        "ascPerKm": E.r1(asc / km) if (asc is not None and km) else None,
        "descPerKm": E.r1(desc / km) if (desc is not None and km) else None,
        "steepDescentPct": None, "demand": None, "sampled": None,
    }
    prof = a.elevation_profile
    if prof and len(prof) >= 2 and km:
        raw, _weighted = terrain.descent_weighting(prof)
        steep = sum(-g * dd for dd, g in terrain._segments(prof) if g <= -0.10)
        if raw > 5:
            out["steepDescentPct"] = round(100 * steep / raw)
        lk = terrain.load_km(prof)
        if lk:
            out["demand"] = round(lk / km, 2)      # terrain-load km per real km (1.00 = flat)
    if surface_json and surface_json.get("coverage", 0) >= 0.4:
        out["sampled"] = {
            "surfaceClass": surface_json.get("surfaceClass"),
            "surfaceLabel": _SURF_CLASS.get(surface_json.get("surfaceClass") or "unknown", surface_json.get("surfaceClass")),
            "onTrail": bool(surface_json.get("onTrail")), "forest": bool(surface_json.get("forest")),
            "source": (surface_json.get("source") or "").upper() or None,
            "coverage": round(surface_json.get("coverage") or 0, 2),
        }
    return out


def _weather_note(a, runner) -> str:
    if not W.enabled():
        return "Počasí je vypnuté."
    if a.start_lat is None and not (runner and runner.city):
        return "Chybí místo běhu — doplňte město v profilu nebo znovu synchronizujte Garmin."
    return "Počasí se nepodařilo načíst — zkusíme to znovu."


def run_history(db, rid: str, limit: int = 20) -> list[dict]:
    """The latest runs with their stats, terrain and weather context. Missing
    weather is fetched on the way (bounded, stored, never blocks on failure)."""
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    runs = (db.query(models.Activity)
            .filter(models.Activity.runner_id == rid, (models.Activity.sport == "running") | (models.Activity.sport.is_(None)))
            .order_by(models.Activity.started_at.desc(), models.Activity.id.desc())
            .limit(limit).all())
    surf = {sid: sj for sid, sj in db.query(models.ActivityStream.activity_id, models.ActivityStream.surface_json)
            .filter(models.ActivityStream.runner_id == rid, models.ActivityStream.surface_json.isnot(None)).all()}
    try:
        W.enrich(db, runner, runs, limit=limit)
    except Exception:  # noqa: BLE001 — weather is context, never a reason to fail the list
        db.rollback()
    out = []
    for a in runs:
        out.append({
            "id": a.id, "started_at": a.started_at, "start_time": a.start_time, "title": a.title,
            "distance_km": a.distance_km, "duration_min": a.duration_min, "pace_s_km": a.pace_s_km,
            "avg_hr": a.avg_hr, "surface": a.surface, "vert_ratio_pct": a.vert_ratio_pct,
            "cadence_spm": a.cadence_spm, "gct_ms": a.gct_ms, "stride_len_m": a.stride_len_m,
            "vert_osc_cm": a.vert_osc_cm, "gct_balance_l": a.gct_balance_l, "descent_m": a.descent_m,
            "temp_watch_c": a.temp_c,
            "terrain": terrain_context(a, surf.get(a.id)),
            "weather": a.weather_json,
            "weatherNote": None if a.weather_json else _weather_note(a, runner),
            "excluded": bool(a.excluded),
            "excluded_scope": (a.excluded_scope or "all") if a.excluded else None,
        })
    return out
