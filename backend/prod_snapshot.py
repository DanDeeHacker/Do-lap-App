"""Local copy of the production database for development — so changes can be
checked on real data before they ship, not only on the seeded demo runners.

  python prod_snapshot.py                 → backend/prod_copy.db (git-ignored)
  python prod_snapshot.py --out /tmp/x.db

Reads DOSSLAP_PROD_DB_URL (backend/.env, git-ignored) — deliberately NOT
DATABASE_URL, which would make the app itself run against production. Every
session is opened with default_transaction_read_only=on, so production can't
be written to from here even by mistake.

Left out of the copy: login sessions, Garmin tokens and ingest tokens (secrets
the local app doesn't need), and the engine-history cache (rebuilt on demand).
Every password hash is replaced by the local-only password LOCAL_PASSWORD, so
any account can be opened on the local copy — the copy never goes anywhere.

Run the app on the copy with an explicit empty DATABASE_URL:
  DATABASE_URL= DOSSLAP_DB_PATH=backend/prod_copy.db DOSSLAP_AUTOSYNC=0 uvicorn app.main:app --port 8765
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent
SKIP = {"sessions", "garmin_sessions", "ingest_tokens", "engine_history_cache"}
LOCAL_PASSWORD = "local-dev-only"


def prod_engine():
    from sqlalchemy import create_engine
    load_dotenv(BACKEND / ".env")
    url = os.environ.get("DOSSLAP_PROD_DB_URL")
    if not url:
        sys.exit("DOSSLAP_PROD_DB_URL není nastavené v backend/.env")
    url = url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, connect_args={
        "options": "-c default_transaction_read_only=on -c statement_timeout=120000", "connect_timeout": 15})


def snapshot(out: Path) -> dict:
    os.environ["DATABASE_URL"] = ""                 # this process's app imports stay on SQLite
    os.environ["DOSSLAP_DB_PATH"] = str(out)
    from sqlalchemy import create_engine, inspect, select
    from app.db import Base
    from app import models  # noqa: F401 — registers every table on Base
    from app.security import hash_password

    if out.exists():
        out.unlink()
    src = prod_engine()
    dst = create_engine(f"sqlite:///{out}")
    Base.metadata.create_all(dst)
    prod_cols = {t: {c["name"] for c in inspect(src).get_columns(t)} for t in inspect(src).get_table_names()}
    local_pw = hash_password(LOCAL_PASSWORD)
    counts = {}
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:          # parents before children
            if table.name in SKIP or table.name not in prod_cols:
                continue
            cols = [c for c in table.columns if c.name in prod_cols[table.name]]
            rows = [dict(r._mapping) for r in s.execute(select(*cols))]
            if table.name == "users":
                for r in rows:
                    r["password_hash"] = local_pw
            if rows:
                d.execute(table.insert(), rows)
            counts[table.name] = len(rows)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only copy of production into a local SQLite file.")
    ap.add_argument("--out", default=str(BACKEND / "prod_copy.db"))
    args = ap.parse_args(argv)
    counts = snapshot(Path(args.out))
    print(f"→ {args.out}")
    for t, n in counts.items():
        if n:
            print(f"  {t:22s} {n}")
    print(f"Lokální heslo pro všechny účty v kopii: {LOCAL_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
