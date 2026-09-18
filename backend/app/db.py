"""SQLAlchemy engine/session setup. SQLite file lives next to this package."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Overridable so the test suite can point at an isolated temp file instead
# of the real dev database (see tests/conftest.py, which sets this before
# app.main is imported).
DB_PATH = os.environ.get("DOSSLAP_DB_PATH") or os.path.join(BACKEND_DIR, "dosslap.db")
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
