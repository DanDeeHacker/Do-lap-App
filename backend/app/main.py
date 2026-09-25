"""App assembly. Serves the API under /api/* and the existing static
frontend (index.html, core.js, ...) from the project root — one process,
one origin, no CORS to configure. Only an explicit whitelist of frontend
filenames is servable; nothing under backend/ (source, requirements.txt,
the SQLite file) is reachable over HTTP.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers ORM tables on Base before create_all)
from . import security
from . import seed as seed_module
from . import db as dbmod
from .db import Base, SessionLocal, engine
from .metrics import engine as E
from .routers import (
    ai, annotations, auth, booking, conclusions, employers, integrations, partners, physios, programs, rtr,
    runners, simulate, triage,
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


def _migrate(engine):
    """Additive column back-fills for columns added after a table already exists —
    create_all() never ALTERs. `ALTER TABLE ... ADD COLUMN` is standard SQL, so
    this runs on BOTH SQLite (dev) and Postgres (deploy): on a redeploy over an
    existing Postgres, new columns would otherwise be missing and every query on
    that table would 500. Safe/idempotent — re-checks each column before adding."""
    from sqlalchemy import inspect, text

    def has_col(table, col):
        insp = inspect(engine)  # fresh each call so it sees columns added above
        if not insp.has_table(table):
            return True  # table doesn't exist yet → create_all will build it fully
        return col in {c["name"] for c in insp.get_columns(table)}

    def add(table, col, ddl, backfill=None):
        if has_col(table, col):
            return
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
            if backfill:
                conn.execute(text(backfill))

    add("activities", "sport", "sport VARCHAR", "UPDATE activities SET sport = 'running' WHERE sport IS NULL")
    add("injury_reports", "pain_points", "pain_points JSON")
    add("checkins", "pain_points", "pain_points JSON")
    add("checkins", "mood", "mood INTEGER")
    add("daily_metrics", "sleep_efficiency", "sleep_efficiency FLOAT")
    add("runners", "engine_mode", "engine_mode VARCHAR", "UPDATE runners SET engine_mode = 'v1' WHERE engine_mode IS NULL")
    # activity_streams may pre-date these two columns on a Postgres provisioned at Phase 4.
    add("activity_streams", "segments_json", "segments_json JSON")
    add("activity_streams", "surface_json", "surface_json JSON")
    # Run context: start time/place for weather, cached weather summary.
    add("activities", "start_time", "start_time VARCHAR")
    add("activities", "start_lat", "start_lat FLOAT")
    add("activities", "start_lon", "start_lon FLOAT")
    add("activities", "weather_json", "weather_json JSON")

    # SQLite-only data cleanup: sensor-dropout zeros → NULL so the engine skips
    # them (Postgres deploys never imported those raw zeros). Idempotent.
    if engine.dialect.name == "sqlite":
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("activities")} if insp.has_table("activities") else set()
        zcols = [c for c in ("cadence_spm", "stride_len_m", "vert_osc_cm", "vert_ratio_pct", "gct_ms", "gct_balance_l", "avg_hr") if c in cols]
        if zcols:
            cond = " OR ".join(f"{c} = 0" for c in zcols)
            with engine.begin() as conn:
                if conn.execute(text(f"SELECT 1 FROM activities WHERE {cond} LIMIT 1")).first():
                    for c in zcols:
                        conn.execute(text(f"UPDATE activities SET {c} = NULL WHERE {c} = 0"))


_SYNC_HOUR = int(os.environ.get("DOSSLAP_AUTOSYNC_HOUR", "6"))
_SYNC_MIN = int(os.environ.get("DOSSLAP_AUTOSYNC_MIN", "30"))  # 06:30 local → "before 7 AM"


def _seconds_until_next(hour: int, minute: int) -> float:
    """Seconds from now until the next local HH:MM. The container clock is
    assumed to be the deploy's local zone (set TZ=Europe/Prague on Railway so
    'before 7 AM' means the runner's morning)."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _garmin_autosync_loop():
    """Fire integrations.auto_sync_all once a day just before 7 AM for every
    runner who opted into 'remember' on their Garmin connect. Errors per runner
    are isolated inside auto_sync_all; a failure here never crashes the app."""
    from .routers.integrations import auto_sync_all
    log = logging.getLogger("dosslap.autosync")
    while True:
        try:
            await asyncio.sleep(_seconds_until_next(_SYNC_HOUR, _SYNC_MIN))
        except asyncio.CancelledError:
            raise
        try:
            result = await asyncio.to_thread(auto_sync_all, SessionLocal)
            log.info("Garmin auto-sync: %s", result)
        except Exception:  # noqa: BLE001
            log.exception("Garmin auto-sync loop failed")
        await asyncio.sleep(60)  # step past the trigger minute so we don't re-fire


def _is_deployed() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("FLY_APP_NAME") or os.path.exists("/.dockerenv")
    )


def _persistence_guard():
    """Log where the DB lives and shout if a deployed instance is writing to
    ephemeral image storage — the one config mistake that silently wipes all
    account history on the next redeploy."""
    log = logging.getLogger("dosslap.db")
    info = dbmod.db_location_info()
    log.info("Database: %s %s (persistent=%s, exists=%s)", info["backend"], info["path"] or "(managed)", info["persistent"], info["exists"])
    if _is_deployed() and not info["persistent"]:
        log.warning(
            "\n" + "!" * 72 +
            "\n! DATABASE IS ON EPHEMERAL CONTAINER STORAGE: %s"
            "\n! Account history WILL BE LOST on the next redeploy."
            "\n! Fix: add a Railway Postgres and reference its DATABASE_URL,"
            "\n!      or attach a persistent volume mounted at /data.\n" + "!" * 72,
            info["path"],
        )


def _backup_db():
    """Copy the SQLite file to <db_dir>/backups/ before migrations run, keeping
    the last N. Cheap insurance: a redeploy, a bad migration, or an accidental
    reset can be rolled back to the pre-boot snapshot. Deploy-only (skipped in
    local dev / tests) and never blocks startup."""
    if not dbmod.IS_SQLITE:
        return  # managed Postgres → provider handles backups; nothing to copy
    if os.environ.get("DOSSLAP_BACKUPS", "1") == "0" or not _is_deployed():
        return
    if not dbmod.db_exists() or dbmod.db_is_ephemeral():
        return  # nothing to protect, or the backup would be ephemeral too
    try:
        import glob
        import shutil
        db_path = dbmod.DB_PATH
        bdir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(db_path, os.path.join(bdir, f"dosslap-{stamp}.db"))
        keep = int(os.environ.get("DOSSLAP_BACKUP_KEEP", "10"))
        for old in sorted(glob.glob(os.path.join(bdir, "dosslap-*.db")))[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
        logging.getLogger("dosslap.db").info("DB backup written to %s (keep %d)", bdir, keep)
    except Exception:  # noqa: BLE001
        logging.getLogger("dosslap.db").exception("DB backup failed (continuing without it)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _persistence_guard()
    _backup_db()  # snapshot BEFORE create_all/migrate touch the file
    Base.metadata.create_all(bind=engine)
    # Additive column back-fills — runs on SQLite AND Postgres, because a redeploy
    # over an existing Postgres won't have columns added since it was provisioned.
    _migrate(engine)
    db = SessionLocal()
    try:
        if db.query(models.Clinic).first() is None:
            seed_module.build_and_seed(db)
        # Runs on every boot (not just an empty DB) so the demo logins also
        # appear on an already-seeded / redeployed database. Idempotent.
        seed_module.ensure_demo_accounts(db)
    finally:
        db.close()
    task = None
    if os.environ.get("DOSSLAP_AUTOSYNC", "1") != "0":
        task = asyncio.create_task(_garmin_autosync_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Došlap API", lifespan=lifespan)
# Compress responses for clients that accept it (every mobile browser) — the
# JS bundle drops ~445 KB → ~140 KB on the wire, a big win on phone networks.
# Applies to API JSON and the served SPA assets alike.
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=700)


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
app.include_router(simulate.router)
app.include_router(annotations.router)


@app.get("/api/health")
def health():
    # `persistent` lets you verify from the running app that account history
    # will survive a redeploy (i.e. the DB is on a mounted volume, not the image).
    info = dbmod.db_location_info()
    return {"ok": True, "db_persistent": info["persistent"], "db_exists": info["exists"]}


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
