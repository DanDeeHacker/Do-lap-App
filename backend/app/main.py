"""App assembly. Serves the API under /api/* and the existing static
frontend (index.html, core.js, ...) from the project root — one process,
one origin, no CORS to configure. Only an explicit whitelist of frontend
filenames is servable; nothing under backend/ (source, requirements.txt,
the SQLite file) is reachable over HTTP.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers ORM tables on Base before create_all)
from . import security
from . import seed as seed_module
from .db import Base, SessionLocal, engine
from .metrics import engine as E
from .routers import (
    ai, auth, booking, conclusions, employers, integrations, partners, physios, programs, rtr,
    runners, triage,
)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.dirname(BACKEND_DIR)

FRONTEND_FILES = {
    "auth.html", "runner.html", "physio.html", "employer.html", "partner.html", "data.html",
    "core.js", "bodymap.js", "styles.css",
}

# Built React SPA (frontend/dist). When present it is served as the primary app
# (client-side routes: /, /auth, /app/:tab, /data) via an SPA fallback below.
# Falls back to the legacy vanilla site when the bundle hasn't been built.
DIST_DIR = os.path.join(FRONTEND_DIR, "frontend", "dist")
HAS_SPA = os.path.isfile(os.path.join(DIST_DIR, "index.html"))


def _migrate_sqlite(engine):
    """Tiny additive migrations for columns added after a DB already exists —
    create_all never ALTERs. Safe/idempotent: only adds missing columns."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("activities")} if insp.has_table("activities") else set()
    if cols and "sport" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE activities ADD COLUMN sport VARCHAR"))
            conn.execute(text("UPDATE activities SET sport = 'running' WHERE sport IS NULL"))
    icols = {c["name"] for c in insp.get_columns("injury_reports")} if insp.has_table("injury_reports") else set()
    if icols and "pain_points" not in icols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE injury_reports ADD COLUMN pain_points JSON"))
    ccols = {c["name"] for c in insp.get_columns("checkins")} if insp.has_table("checkins") else set()
    if ccols and "pain_points" not in ccols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE checkins ADD COLUMN pain_points JSON"))
    if ccols and "mood" not in ccols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE checkins ADD COLUMN mood INTEGER"))
    dcols = {c["name"] for c in insp.get_columns("daily_metrics")} if insp.has_table("daily_metrics") else set()
    if dcols and "sleep_efficiency" not in dcols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE daily_metrics ADD COLUMN sleep_efficiency FLOAT"))
    # Clean sensor-dropout zeros in already-imported data: a 0 in a running-
    # dynamics / HR field is a missing reading, not a real value (see
    # garmin_live._pos). Set them NULL so the engine skips them instead of
    # dragging the metric's average toward zero. Gated so it's a no-op once clean.
    zcols = [c for c in ("cadence_spm", "stride_len_m", "vert_osc_cm", "vert_ratio_pct", "gct_ms", "gct_balance_l", "avg_hr") if c in cols]
    if zcols:
        cond = " OR ".join(f"{c} = 0" for c in zcols)
        with engine.begin() as conn:
            if conn.execute(text(f"SELECT 1 FROM activities WHERE {cond} LIMIT 1")).first():
                for c in zcols:
                    conn.execute(text(f"UPDATE activities SET {c} = NULL WHERE {c} = 0"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite(engine)
    db = SessionLocal()
    try:
        if db.query(models.Clinic).first() is None:
            seed_module.build_and_seed(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Došlap API", lifespan=lifespan)


def _record_access(db, rid: str, physio_id: str, method: str, resource: str) -> None:
    action = "read" if method == "GET" else "write"
    today, now = E.iso_date(E.today_date()), E.now_iso()
    row = (
        db.query(models.AccessLog)
        .filter_by(runner_id=rid, physio_id=physio_id, date=today, action=action).first()
    )
    if row:
        row.access_count = (row.access_count or 0) + 1
        row.last_at, row.resource = now, resource
    else:
        db.add(models.AccessLog(
            runner_id=rid, physio_id=physio_id, actor_role="physio", action=action,
            date=today, resource=resource, access_count=1, first_at=now, last_at=now,
        ))
    db.commit()


@app.middleware("http")
async def audit_access(request, call_next):
    """Logs a physio's access to a runner's record (GDPR right-of-access
    transparency). Runs after the response so it never blocks the request,
    and swallows its own errors — auditing must not break the API."""
    response = await call_next(request)
    try:
        path = request.url.path
        parts = path.split("/")
        # /api/runners/{rid}/...  (skip the access-log read itself would still
        # be a physio touching the record, so it's fine to log)
        if path.startswith("/api/runners/") and len(parts) > 3 and response.status_code < 400:
            rid = parts[3]
            token = request.cookies.get(security.SESSION_COOKIE)
            db = SessionLocal()
            try:
                user = security.get_user_for_token(db, token)
                if user and user.role == "physio" and user.physio_id:
                    _record_access(db, rid, user.physio_id, request.method,
                                   parts[4] if len(parts) > 4 else "profil")
            finally:
                db.close()
    except Exception:
        pass
    return response


app.include_router(auth.router)
app.include_router(runners.router)
app.include_router(physios.router)
app.include_router(triage.router)
app.include_router(programs.router)
app.include_router(booking.router)
app.include_router(rtr.router)
app.include_router(conclusions.router)
app.include_router(ai.router)
app.include_router(employers.router)
app.include_router(partners.router)
app.include_router(integrations.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Frontend is edited live (static HTML/JS, no build step) — tell the browser
# to always revalidate so a changed core.js/styles.css is never served stale
# from cache (which surfaces as "api.X is not a function" after an update).
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

# Hashed Vite bundle assets are content-addressed, so they can cache forever.
if HAS_SPA:
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(DIST_DIR, "assets")),
        name="assets",
    )


@app.get("/")
def serve_index():
    if HAS_SPA:
        return FileResponse(os.path.join(DIST_DIR, "index.html"), headers=_NO_CACHE)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"), headers=_NO_CACHE)


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    # Never let the catch-all shadow the API (unmatched /api/* → real 404).
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    # Legacy vanilla site: only the explicit whitelist is reachable.
    if full_path in FRONTEND_FILES:
        return FileResponse(os.path.join(FRONTEND_DIR, full_path), headers=_NO_CACHE)
    if HAS_SPA:
        # Serve a real built file (favicon, etc.) if it exists and stays inside
        # the bundle dir; otherwise fall back to the SPA shell for client routes.
        candidate = os.path.abspath(os.path.join(DIST_DIR, full_path))
        if os.path.isfile(candidate) and os.path.commonpath([DIST_DIR, candidate]) == DIST_DIR:
            return FileResponse(candidate, headers=_NO_CACHE)
        return FileResponse(os.path.join(DIST_DIR, "index.html"), headers=_NO_CACHE)
    raise HTTPException(status_code=404)
