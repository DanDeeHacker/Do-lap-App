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


DB_PATH = _resolve_db_path()
# First boot on a fresh volume: the file's parent must exist before SQLite opens it.
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_exists() -> bool:
    return os.path.exists(DB_PATH)


def db_is_ephemeral() -> bool:
    """True when the DB lives inside the image's backend dir rather than a
    mounted volume — i.e. it would be wiped on the next redeploy."""
    return os.path.abspath(DB_PATH).startswith(os.path.abspath(BACKEND_DIR))


def db_location_info() -> dict:
    return {"path": DB_PATH, "persistent": not db_is_ephemeral(), "exists": db_exists()}
