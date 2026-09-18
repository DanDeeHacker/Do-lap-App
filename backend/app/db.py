"""SQLAlchemy engine/session setup. SQLite file lives next to this package."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_db_path() -> str:
    """Where the SQLite file lives. Resolution order, chosen so account history
    survives a redeploy without relying on a single env var being remembered:

    1. DOSSLAP_DB_PATH  — explicit override (also how the test suite points at
       an isolated temp file; see tests/conftest.py).
    2. /data/dosslap.db — when a persistent volume is mounted at /data (the
       documented Railway/Fly setup). Auto-detected so mounting the volume is
       enough; you don't ALSO have to set the env var.
    3. backend/dosslap.db — local dev fallback (NOT persistent in a container:
       it lives inside the image and is wiped on every redeploy — main.py logs
       a loud warning if this path is used in a deployed environment)."""
    explicit = os.environ.get("DOSSLAP_DB_PATH")
    if explicit:
        return explicit
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/dosslap.db"
    return os.path.join(BACKEND_DIR, "dosslap.db")


def _build_engine():
    """Postgres when DATABASE_URL is set (Railway/managed → persistent, survives
    redeploys with NO volume needed), else a local SQLite file (dev + tests).

    Returns (engine, db_path_or_None). Railway/Heroku hand out `postgres://` or
    `postgresql://`; SQLAlchemy 2 needs an explicit driver, so we normalize to
    psycopg (v3)."""
    url = os.environ.get("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        # pool_pre_ping recycles connections a managed PG may have dropped
        # (idle timeout) so the first request after a quiet spell doesn't 500.
        return create_engine(url, pool_pre_ping=True), None
    path = _resolve_db_path()
    # First boot on a fresh volume: the file's parent must exist before open.
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}), path


engine, DB_PATH = _build_engine()
DATABASE_URL = str(engine.url)
IS_SQLITE = engine.dialect.name == "sqlite"
IS_POSTGRES = engine.dialect.name == "postgresql"
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_exists() -> bool:
    if IS_SQLITE:
        return os.path.exists(DB_PATH)
    return True  # managed Postgres always exists once provisioned


def db_is_ephemeral() -> bool:
    """True when the DB would be wiped on the next redeploy. A managed Postgres
    is always persistent; a SQLite file is ephemeral only when it lives inside
    the image's backend dir (no volume mounted)."""
    if not IS_SQLITE:
        return False
    return os.path.abspath(DB_PATH).startswith(os.path.abspath(BACKEND_DIR))


def db_location_info() -> dict:
    if IS_SQLITE:
        return {"backend": "sqlite", "path": DB_PATH, "persistent": not db_is_ephemeral(), "exists": db_exists()}
    return {"backend": "postgresql", "path": None, "persistent": True, "exists": True}
