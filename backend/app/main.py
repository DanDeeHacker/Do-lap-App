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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers ORM tables on Base before create_all)
from . import security
from . import seed as seed_module
from . import db as dbmod
from .db import Base, SessionLocal, engine
from .deps import is_owner, tutorial_demo_runner_id
from .metrics import engine as E
from .routers import (
    admin, ai, annotations, auth, booking, calendar, client_errors, coach, conclusions, employers, goals, integrations, partners, physios,
    personas, plan, programs, records, rtr, work, business, runners, self_programs, shoes, simulate, team, triage, assistant, usage,
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


def _booking_guard(engine):
    """physio brief 2026-11-09 P0.6: the database refuses a second requested/confirmed visit at the same
    start for one physio. Existing duplicates are reported, never cancelled silently — the index then
    waits until someone resolves them."""
    from sqlalchemy import inspect, text
    if not inspect(engine).has_table("bookings"):
        return
    with engine.begin() as conn:
        dups = conn.execute(text(
            "SELECT physio_id, slot_at, COUNT(*) FROM bookings WHERE status IN ('requested','confirmed') "
            "GROUP BY physio_id, slot_at HAVING COUNT(*) > 1")).fetchall()
        if dups:
            for pid, at, n in dups:
                logging.getLogger("dosslap.db").warning(
                    "bookings: %s active visits of %s at %s — resolve them; the unique index waits", n, pid, at)
            return
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_bookings_active_start ON bookings(physio_id, slot_at) "
            "WHERE status IN ('requested','confirmed')"))


APPEND_ONLY = ("clinical_records", "record_events", "record_destructions")


def _ledger_guard(engine):
    """physio brief 2026-11-09 R5/R7/R11: the ledger, the activity log and the destruction log refuse UPDATE
    and DELETE in the database itself. The one exception: a clinical record past its retention whose patient
    card has a logged destruction (record_destructions) can be deleted. Idempotent, SQLite and Postgres."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if not all(insp.has_table(t) for t in APPEND_ONLY):
        return
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            for t in APPEND_ONLY:
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t} "
                                  f"BEGIN SELECT RAISE(ABORT, '{t} are append-only'); END"))
            for t in ("record_events", "record_destructions"):
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t} "
                                  f"BEGIN SELECT RAISE(ABORT, '{t} are append-only'); END"))
            conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS clinical_records_no_delete BEFORE DELETE ON clinical_records "
                "WHEN OLD.retain_until > date('now') OR NOT EXISTS (SELECT 1 FROM record_destructions d "
                "WHERE d.patient_record_id = OLD.patient_record_id) "
                "BEGIN SELECT RAISE(ABORT, 'clinical_records are append-only'); END"))
        elif engine.dialect.name == "postgresql":
            conn.execute(text(
                "CREATE OR REPLACE FUNCTION dosslap_append_only() RETURNS trigger AS $$ BEGIN "
                "IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'clinical_records' AND OLD.retain_until <= to_char(now(), 'YYYY-MM-DD') "
                "AND EXISTS (SELECT 1 FROM record_destructions d WHERE d.patient_record_id = OLD.patient_record_id) "
                "THEN RETURN OLD; END IF; "
                "RAISE EXCEPTION '% are append-only', TG_TABLE_NAME; END $$ LANGUAGE plpgsql"))
            for t in APPEND_ONLY:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}"))
                conn.execute(text(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
                                  f"FOR EACH ROW EXECUTE FUNCTION dosslap_append_only()"))


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
    for col in ("deep_min", "rem_min", "light_min", "awake_min"):
        add("daily_metrics", col, f"{col} FLOAT")
    add("runners", "engine_mode", "engine_mode VARCHAR", "UPDATE runners SET engine_mode = 'v1' WHERE engine_mode IS NULL")
    # One-time move of the accounts from before v3 (27. 9. 2026) onto the Kapacitní engine:
    # the Trénink tab exists only with v3, and since feedback #182 the engine choice is for
    # the owners only, so those runners could never get it. Runs once, when the column is
    # added; the previous mode is kept for a rollback and owners can still switch afterwards.
    add("runners", "engine_mode_before_v3", "engine_mode_before_v3 VARCHAR",
        "UPDATE runners SET engine_mode_before_v3 = engine_mode, engine_mode = 'v3' "
        "WHERE engine_mode IS NULL OR engine_mode <> 'v3'")
    # activity_streams may pre-date these two columns on a Postgres provisioned at Phase 4.
    add("activity_streams", "segments_json", "segments_json JSON")
    add("activity_streams", "surface_json", "surface_json JSON")
    # Run context: start time/place for weather, cached weather summary.
    add("activities", "start_time", "start_time VARCHAR")
    add("activities", "start_lat", "start_lat FLOAT")
    add("activities", "start_lon", "start_lon FLOAT")
    add("activities", "weather_json", "weather_json JSON")
    add("activities", "excluded", "excluded BOOLEAN")
    add("activities", "excluded_at", "excluded_at VARCHAR")
    add("activities", "excluded_scope", "excluded_scope VARCHAR")
    add("activities", "auto_excluded", "auto_excluded VARCHAR")
    add("activities", "mech_keep", "mech_keep BOOLEAN")
    add("runners", "coach_consent", "coach_consent BOOLEAN", "UPDATE runners SET coach_consent = FALSE WHERE coach_consent IS NULL")
    add("runners", "coach_consent_at", "coach_consent_at VARCHAR")
    add("runners", "cycle_override", "cycle_override JSON")
    add("runners", "prior_injury_date", "prior_injury_date VARCHAR")
    add("runners", "prior_injury_side", "prior_injury_side VARCHAR")
    add("runners", "hr_max", "hr_max INTEGER")
    add("runners", "threshold_hr", "threshold_hr INTEGER")
    add("runners", "onboarding_json", "onboarding_json JSON")
    # cross-training (strength sessions): what was trained and how
    add("activities", "strength_focus", "strength_focus VARCHAR")
    add("activities", "strength_type", "strength_type VARCHAR")
    add("self_programs", "state", "state JSON")
    add("daily_details", "raw", "raw JSON")
    for col in ("nt_load", "nt_active_min", "rest_mild_min", "rest_high_min", "rest_hr_med"):
        add("daily_metrics", col, f"{col} FLOAT")
    add("checkins", "limits_movement", "limits_movement BOOLEAN")
    add("checkins", "run_modified", "run_modified BOOLEAN")
    add("checkins", "limping", "limping BOOLEAN")
    add("checkins", "life_stress", "life_stress INTEGER")
    add("checkins", "sleep_quality", "sleep_quality INTEGER")
    add("checkins", "flags", "flags JSON")
    add("settings", "rail_cards", "rail_cards JSON")
    add("settings", "today_cards", "today_cards JSON")
    add("settings", "news_seen", "news_seen VARCHAR")
    add("usage_days", "hour", "hour INTEGER")
    add("settings", "badges_seen", "badges_seen JSON")
    add("races", "ascent_m", "ascent_m FLOAT")
    add("races", "target_pace_s_km", "target_pace_s_km INTEGER")
    add("goals", "risk_ended_at", "risk_ended_at VARCHAR")
    add("goals", "risk_end_reason", "risk_end_reason VARCHAR")
    add("goals", "track_json", "track_json JSON")
    add("goals", "outcome_json", "outcome_json JSON")
    add("goals", "hot", "hot BOOLEAN")
    add("runners", "planner_json", "planner_json JSON")
    # v0.9.0 — the calibration record: the day's recommendation and a post-run flag
    add("engine_daily_snapshots", "guidance_json", "guidance_json JSON")
    add("engine_daily_snapshots", "post_session", "post_session BOOLEAN")
    # feedback #152 — notes from other users wait for the owner's approval
    add("annotations", "approved_at", "approved_at VARCHAR")
    # Team Console → Inbox (owner request 2026-10-27)
    for col in ("priority", "triage_type", "assignee", "issue_url"):
        add("annotations", col, f"{col} VARCHAR")
    add("annotations", "issue_number", "issue_number INTEGER")
    # simulated runners (app/personas): synthetic notes and their dedupe key; usage consent
    add("annotations", "source", "source VARCHAR")
    add("annotations", "fingerprint", "fingerprint VARCHAR")
    add("settings", "share_usage", "share_usage BOOLEAN")
    add("settings", "share_usage_at", "share_usage_at VARCHAR")
    # British English: the account's language (UI and AI assistant)
    add("users", "lang", "lang VARCHAR", "UPDATE users SET lang = 'cs' WHERE lang IS NULL")
    # v0.12.0 — profile gate (experience, body mass, menstrual cycle), breathing rate
    add("runners", "running_since", "running_since VARCHAR")
    add("runners", "weight_kg", "weight_kg FLOAT")
    add("runners", "menstrual_json", "menstrual_json JSON")
    add("daily_metrics", "resp_rate", "resp_rate FLOAT")
    # Plán od trenéra (2026-10-12)
    add("runners", "coach_mode", "coach_mode BOOLEAN", "UPDATE runners SET coach_mode = FALSE WHERE coach_mode IS NULL")
    add("runners", "coach_name", "coach_name VARCHAR")
    add("runners", "plan_feed_url", "plan_feed_url VARCHAR")
    add("runners", "plan_feed_status", "plan_feed_status JSON")
    # v0.12.13 — run detail (route, series, splits) and shoes per run
    add("activity_streams", "route_json", "route_json JSON")
    add("activity_streams", "track_json", "track_json JSON")
    add("activities", "shoe_id", "shoe_id INTEGER")
    add("activities", "gear_uuid", "gear_uuid VARCHAR")
    add("shoes", "is_default", "is_default BOOLEAN", "UPDATE shoes SET is_default = FALSE WHERE is_default IS NULL")
    add("shoes", "garmin_uuid", "garmin_uuid VARCHAR")
    # review 2026-10-30 F1: physio accounts need an owner's verification; the ones that exist when
    # this ships keep working (Team Console → Tým lists them, an owner can withdraw it)
    add("physios", "verified_by", "verified_by VARCHAR")
    add("physios", "verified_at", "verified_at VARCHAR",
        "UPDATE physios SET verified_at = '2026-10-30', verified_by = 'stávající účet' WHERE verified_at IS NULL")
    # review 2026-10-30 N1: a team role belongs to an account. A member row binds to the account
    # with its e-mail only when that account is older than the invitation (it can't be a squatter
    # who registered the invited address); the rest need a new invitation link.
    add("work_items", "clinical_sha", "clinical_sha VARCHAR")
    add("conclusions", "ai_draft", "ai_draft BOOLEAN")
    add("conclusions", "outcome_kind", "outcome_kind VARCHAR")
    add("conclusions", "shared_at", "shared_at VARCHAR",
        "UPDATE conclusions SET shared_at = approved_at WHERE status = 'approved' AND shared_at IS NULL")
    add("team_members", "extra_roles", "extra_roles JSON")
    add("team_members", "invite_hash", "invite_hash VARCHAR")
    add("team_members", "invite_expires_at", "invite_expires_at VARCHAR")
    add("team_members", "user_id", "user_id INTEGER",
        "UPDATE team_members SET user_id = (SELECT users.id FROM users WHERE lower(users.email) = team_members.email "
        "AND users.created_at IS NOT NULL AND users.created_at <= team_members.created_at)")
    # physio brief 2026-11-09 P0.6: a visit knows its length, and one physio has one active visit per start
    add("bookings", "duration_min", "duration_min INTEGER",
        "UPDATE bookings SET duration_min = COALESCE((SELECT physio_slots.duration_min FROM physio_slots "
        "WHERE physio_slots.id = bookings.slot_id), 45) WHERE duration_min IS NULL")
    add("bookings", "cancel_reason", "cancel_reason VARCHAR")
    _booking_guard(engine)
    add("rtr_sessions", "count_reason", "count_reason VARCHAR")      # physio brief P0.7
    add("return_to_run", "paused_reason", "paused_reason VARCHAR")
    # physio brief P0.10: message audience; the old system notes meant for the physio stay with the physio
    add("messages", "audience", "audience VARCHAR",
        "UPDATE messages SET audience = CASE WHEN sender = 'system' AND (body LIKE 'Pacient %' OR body LIKE 'Návrat k běhu:%' "
        "OR body LIKE 'Triáž%') THEN 'physio' ELSE 'both' END WHERE audience IS NULL")
    # physio brief P0.8: exercise order and library origin
    add("exercises", "position", "position INTEGER", "UPDATE exercises SET position = id WHERE position IS NULL")
    add("exercises", "library_id", "library_id VARCHAR")
    # physio brief Phase 1: provider identity (R1), structured visit content (R4), episodes (R3)
    for col in ("legal_name", "legal_form", "ico", "registered_street", "registered_city", "registered_postal_code",
                "care_site_street", "care_site_city", "care_site_postal_code", "provider_details_confirmed_at"):
        add("clinics", col, f"{col} VARCHAR")
    add("clinics", "is_solo", "is_solo BOOLEAN")
    for col in ("title", "qualification", "hcp_identifier"):
        add("physios", col, f"{col} VARCHAR")
    for col in ("subjective", "objective", "assessment", "plan", "services_provided"):
        add("conclusions", col, f"{col} TEXT")
    for col in ("diagnosis_code", "diagnosis_label", "autosaved_at", "record_id"):
        add("conclusions", col, f"{col} VARCHAR")
    for t in ("conclusions", "bookings", "programs", "return_to_run", "injury_reports"):
        add(t, "episode_id", "episode_id INTEGER")
    _ledger_guard(engine)
    # physio brief Phase 2: triage request (W4), physio work settings (W4/W13/W14/W15), booking intake (W16),
    # programme builder (W10), return to run v2 (W11), messaging (W13)
    for col, ddl in (("request_reason", "TEXT"), ("request_duration", "VARCHAR"), ("red_flags", "JSON")):
        add("triage", col, f"{col} {ddl}")
    for col, ddl in (("accepting_new_clients", "BOOLEAN"), ("max_new_per_week", "INTEGER"), ("response_time_text", "VARCHAR"),
                     ("cancellation_policy", "TEXT"), ("notify_settings", "JSON"), ("ics_token", "VARCHAR"),
                     ("rating_count", "INTEGER"), ("photo_url", "VARCHAR"), ("quick_replies", "JSON"),
                     ("dark_mode", "BOOLEAN")):
        add("physios", col, f"{col} {ddl}")
    for col, ddl in (("service_id", "INTEGER"), ("reason", "TEXT"), ("questions", "TEXT"), ("recurring_group", "VARCHAR")):
        add("bookings", col, f"{col} {ddl}")
    if inspect(engine).has_table("bookings"):    # W1.6: payer is client | employer | insurer | other
        with engine.begin() as conn:
            conn.execute(text("UPDATE bookings SET payer = 'client' WHERE payer = 'self' OR payer IS NULL"))
    for col, ddl in (("phase_id", "INTEGER"), ("sets", "INTEGER"), ("reps", "INTEGER"), ("duration_s", "INTEGER"),
                     ("load_text", "VARCHAR"), ("tempo", "VARCHAR"), ("side", "VARCHAR"), ("pain_limit", "INTEGER"),
                     ("media_url", "VARCHAR"), ("thumbnail_url", "VARCHAR"), ("description", "TEXT")):
        add("exercises", col, f"{col} {ddl}")
    add("programs", "version", "version INTEGER")
    add("programs", "draft_note", "draft_note TEXT")
    for col, ddl in (("next_morning_pain", "INTEGER"), ("morning_stiffness_min", "INTEGER"),
                     ("matched_activity_id", "INTEGER"), ("state", "VARCHAR")):
        add("rtr_sessions", col, f"{col} {ddl}")
    for col, ddl in (("attachment_path", "VARCHAR"), ("attachment_type", "VARCHAR"), ("attachment_name", "VARCHAR"),
                     ("handled_at", "VARCHAR")):
        add("messages", col, f"{col} {ddl}")
    add("messages", "read_at_physio", "read_at_physio VARCHAR")
    add("messages", "read_at_runner", "read_at_runner VARCHAR")

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


AUTOSYNC_LAST: dict = {}   # Team Console → Vydání: the morning sync's last counts (no runner ids)


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
            AUTOSYNC_LAST.update(at=E.now_iso(), synced=(result or {}).get("synced"),
                                 failed=(result or {}).get("failed"), total=(result or {}).get("total"))
            # fresh data → the day's AI texts for runners who opted in (metrics/coach_texts.py)
            from .metrics.coach_texts import generate_all
            coach = await asyncio.to_thread(generate_all, SessionLocal)
            log.info("AI texts: %s runners", coach.get("runners"))
            # Plán od trenéra: the calendar links (TrainingPeaks, Final Surge, …) refresh too
            from .routers.plan import sync_all_feeds
            feeds = await asyncio.to_thread(sync_all_feeds, SessionLocal)
            log.info("Plan feeds: %s", feeds)
        except Exception:  # noqa: BLE001
            log.exception("Garmin auto-sync loop failed")
        await asyncio.sleep(60)  # step past the trigger minute so we don't re-fire


def _seconds_until_local_midnight(after_s: int = 0) -> float:
    """Seconds until the next midnight in the engine's zone (Europe/Prague, the
    zone engine.today_date() uses), plus `after_s`, independent of the
    container's TZ setting."""
    from .metrics.engine import LOCAL_TZ
    now = datetime.now(LOCAL_TZ)
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), LOCAL_TZ)
    return (nxt - now).total_seconds() + after_s


def _refresh_tutorial_demo():
    """Rebuild the getting-started tour's runner for the new day (app.tutorial_demo)."""
    from . import tutorial_demo
    db = SessionLocal()
    try:
        tutorial_demo.ensure(db)
    finally:
        db.close()


async def _precompute_loop():
    """Warm every recently active runner's derived data (today's assessment and
    the daily quadrant history) shortly after startup and again just after each
    local midnight, so the first open of a new day never waits on a replay. The
    work itself runs on the precompute worker thread (app.precompute)."""
    from . import precompute
    log = logging.getLogger("dosslap.precompute")
    first = True
    while True:
        try:
            # a short delay at boot lets the app answer its first requests first
            await asyncio.sleep(20 if first else _seconds_until_local_midnight(120))
        except asyncio.CancelledError:
            raise
        first = False
        try:
            await asyncio.to_thread(_refresh_tutorial_demo)
        except Exception:  # noqa: BLE001
            log.exception("Tutorial demo rebuild failed")
        try:
            n = await asyncio.to_thread(precompute.warm_all)
            log.info("Precompute warm-up queued for %s runners", n)
        except Exception:  # noqa: BLE001
            log.exception("Precompute warm-up failed")
        await asyncio.sleep(60)


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


async def _knowledge_embed_task():
    """Embeddings for the assistant's knowledge chunks, in the background once
    after boot (no-op without an embedding API key)."""
    try:
        await asyncio.sleep(30)
        from .assistant import knowledge as KB

        def run():
            db = SessionLocal()
            try:
                total = 0
                while True:
                    n = KB.embed_pending(db)
                    total += n
                    if not n:
                        return total
            finally:
                db.close()
        n = await asyncio.to_thread(run)
        if n:
            logging.getLogger("dosslap.assistant").info("Embedded %s knowledge chunks", n)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logging.getLogger("dosslap.assistant").exception("Knowledge embedding failed")


def _dedupe_activities(db) -> None:
    """v0.12.11 — one recording stored twice by two syncs at once (before the per-runner
    lock): the copies are merged on boot, so the history and the load count it once."""
    from sqlalchemy import func
    from .metrics import engine as E
    try:
        rids = {r for (r,) in db.query(models.Activity.runner_id)
                .filter(models.Activity.external_id.isnot(None), models.Activity.provider != "manual")
                .group_by(models.Activity.runner_id, models.Activity.provider, models.Activity.external_id)
                .having(func.count(models.Activity.id) > 1)}
        for rid in sorted(rids):
            n = E.dedupe_activities(db, rid)
            db.commit()
            logging.getLogger("dosslap").info("Merged %s duplicate activities of runner %s", n, rid)
    except Exception:  # noqa: BLE001 — never blocks startup
        db.rollback()
        logging.getLogger("dosslap").exception("Duplicate activity merge failed")


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
        _dedupe_activities(db)
        # Physio AI Assistant: built-in knowledge (cards, summaries, app guide) from the repo
        try:
            from .assistant import knowledge as KB
            KB.sync_builtin(db)
        except Exception:  # noqa: BLE001 — the assistant must never block startup
            logging.getLogger("dosslap.assistant").exception("Knowledge sync failed")
    finally:
        db.close()
    tasks = []
    tasks.append(asyncio.create_task(_knowledge_embed_task()))
    if os.environ.get("DOSSLAP_AUTOSYNC", "1") != "0":
        tasks.append(asyncio.create_task(_garmin_autosync_loop()))
    from . import precompute
    if precompute.enabled():
        tasks.append(asyncio.create_task(_precompute_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# physio brief 2026-11-09 P0.10: the API description is for development, not for anyone on production
_PROD = os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production"
app = FastAPI(title="Došlap API", lifespan=lifespan, docs_url=None if _PROD else "/docs",
              redoc_url=None if _PROD else "/redoc", openapi_url=None if _PROD else "/openapi.json")
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


def _record_admin_access(db, rid: str, user_id: int, resource: str) -> None:
    today, now = E.iso_date(E.today_date()), E.now_iso()
    row = db.query(models.AdminAccessLog).filter_by(runner_id=rid, admin_user_id=user_id, date=today).first()
    if row:
        row.access_count = (row.access_count or 0) + 1
        row.last_at, row.resource = now, resource
    else:
        db.add(models.AdminAccessLog(runner_id=rid, admin_user_id=user_id, date=today, resource=resource,
                                     access_count=1, first_at=now, last_at=now))
    db.commit()


@app.middleware("http")
async def audit_access(request, call_next):
    """Logs access to a runner's record: the daily access_log roll-up the runner sees (GDPR transparency)
    and, physio brief 2026-11-09 R7, one record_events row per successful request on every route declared
    in app/audit.py. Runs after the response so it never blocks the request, and swallows its own errors —
    auditing must not break the API."""
    response = await call_next(request)
    try:
        if response.status_code < 400 and request.url.path.startswith("/api/"):
            await asyncio.to_thread(_audit_after, request.scope, request.method, request.url.path,
                                    request.cookies.get(security.SESSION_COOKIE))
    except Exception:
        pass
    return response


def _audit_after(scope, method: str, path: str, token: str | None) -> None:
    from . import audit as AU
    from . import records as RC
    route = scope.get("route")
    template = getattr(route, "path", None)
    params = scope.get("path_params") or {}
    decl = AU.declaration(method, template) if template else None
    parts = path.split("/")
    db = SessionLocal()
    try:
        user = security.get_user_for_token(db, token)
        if user is None:
            return
        # the daily roll-up, as before, for /api/runners/{rid}/…
        if path.startswith("/api/runners/") and len(parts) > 3:
            rid = parts[3]
            if user.role == "physio" and user.physio_id:
                _record_access(db, rid, user.physio_id, method, parts[4] if len(parts) > 4 else "profil")
            elif user.runner_id != rid and is_owner(user) and rid != tutorial_demo_runner_id():
                _record_admin_access(db, rid, user.id, parts[4] if len(parts) > 4 else "profil")
        if decl is None and template and template.startswith("/api/runners/{rid}") and user.role == "physio":
            decl = ("read" if method == "GET" else "update", "runner")
        if not decl or decl[0] in ("self", "exempt"):
            return
        action, rtype = decl
        rid = AU.runner_of(db, template, params)
        if user.role == "physio" and user.physio_id:
            ph = db.get(models.Physio, user.physio_id)
            if ph is None:
                return
            RC.physio_event(db, ph, action, rtype, AU.resource_id(params), runner_id=rid,
                            detail={"route": f"{method} {template}"})
            if rid and not path.startswith("/api/runners/"):
                _record_access(db, rid, ph.id, method, rtype)
        elif user.role == "runner" and method != "GET":
            RC.event(db, actor_type="runner", actor_id=user.runner_id, actor_name=user.name, action=action,
                     resource_type=rtype, resource_id=AU.resource_id(params), runner_id=user.runner_id,
                     detail={"route": f"{method} {template}"})
        else:
            return
        db.commit()
    finally:
        db.close()


def _persona_clock_for(token: str | None):
    from .personas import sim as PS
    db = SessionLocal()
    try:
        return PS.clock_for_user(db, security.get_user_for_token(db, token))
    finally:
        db.close()


@app.middleware("http")
async def persona_clock(request, call_next):
    """Simulated runners (app/personas, staging only): a request signed in as a persona runs on
    the persona's own clock, so its app shows the simulated day."""
    from .personas import sim as PS
    token = request.cookies.get(security.SESSION_COOKIE)
    if not token or not request.url.path.startswith("/api/") or not PS.enabled():
        return await call_next(request)
    clock = await asyncio.to_thread(_persona_clock_for, token)
    if clock is None:
        return await call_next(request)
    tok = E._sim_now.set(clock)
    try:
        return await call_next(request)
    finally:
        E._sim_now.reset(tok)


@app.middleware("http")
async def read_only_practice(request, call_next):
    """physio brief 2026-11-09 B2: an unpaid practice (after the trial, the paid month and 14 days' grace)
    may read everything but change nothing — except the documentation (corrections, print, export),
    signing in and paying."""
    token = request.cookies.get(security.SESSION_COOKIE)
    if token and request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        why = await asyncio.to_thread(_read_only_why, token, request.method, request.url.path)
        if why:
            return JSONResponse({"detail": why}, status_code=402)
    return await call_next(request)


def _read_only_why(token: str, method: str, path: str) -> str | None:
    from . import business as B
    db = SessionLocal()
    try:
        return B.read_only_block(db, security.get_user_for_token(db, token), method, path)
    except Exception:
        return None                    # never lock a practice out because the check itself failed
    finally:
        db.close()


app.include_router(auth.router)
app.include_router(runners.router)
app.include_router(shoes.router)
app.include_router(shoes.catalog_router)
app.include_router(physios.router)
app.include_router(records.router)
app.include_router(work.router)
app.include_router(business.router)   # physio brief 2026-11-09 Phases 3 and 4
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
app.include_router(coach.router)
app.include_router(plan.router)
app.include_router(goals.router)
app.include_router(assistant.router)
app.include_router(self_programs.router)
app.include_router(admin.router)
app.include_router(usage.router)
app.include_router(client_errors.router)
app.include_router(calendar.router)
app.include_router(team.router)
app.include_router(team.hook_router)
app.include_router(personas.router)


@app.get("/api/health")
def health():
    # `persistent` lets you verify from the running app that account history
    # will survive a redeploy (i.e. the DB is on a mounted volume, not the image).
    info = dbmod.db_location_info()
    from .metrics import engine as _E    # the running engine version, to confirm a deploy landed
    return {"ok": True, "db_persistent": info["persistent"], "db_exists": info["exists"], "engine": _E.ENGINE_VERSION}


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
