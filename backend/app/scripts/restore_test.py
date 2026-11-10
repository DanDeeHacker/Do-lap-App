"""Restore test (physio brief R12.4): decrypt the newest SQLite backup into a temporary file, open it and run
the ledger verifier against it. Exit 0 when the backup restores and the records are intact.

    BACKUP_DIR=/mnt/backup BACKUP_ENCRYPTION_KEY=… python -m app.scripts.restore_test
"""
from __future__ import annotations

import glob
import os
import sys
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .. import records as R
from .backup_db import _key, decrypt_file


def main(argv=None) -> int:
    files = sorted(glob.glob(os.path.join(os.environ.get("BACKUP_DIR", "."), "dosslap-*.db.enc")))
    if not files:
        print("Žádná záloha k obnově.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "restored.db")
        decrypt_file(files[-1], target, _key())
        eng = create_engine(f"sqlite:///{target}")
        db = sessionmaker(bind=eng)()
        try:
            res = R.verify(db)
        finally:
            db.close()
            eng.dispose()
    print(f"Obnoveno z {os.path.basename(files[-1])}: " + ("záznamy sedí" if res["ok"] else f"NESEDÍ {res}"))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
