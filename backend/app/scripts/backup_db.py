"""Daily encrypted database backup (physio brief R12). Writes BACKUP_DIR/dosslap-YYYY-MM-DD.db.enc,
AES-GCM with BACKUP_ENCRYPTION_KEY (base64, 32 bytes). SQLite uses the online backup API; Postgres uses
pg_dump when it is installed.

    BACKUP_DIR=/mnt/backup BACKUP_ENCRYPTION_KEY=… python -m app.scripts.backup_db

What code cannot do (owner, see docs/physio-brief-map.md): storage in the EU separate from the database,
the retention policy in writing, and a yearly copy that cannot be altered (object lock).
"""
from __future__ import annotations

import base64
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date

from ..db import engine


def _key() -> bytes:
    raw = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    k = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)) if raw else b""
    if len(k) != 32:
        raise SystemExit("BACKUP_ENCRYPTION_KEY musí být 32 bajtů v base64.")
    return k


def encrypt_file(src: str, dst: str, key: bytes) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    data = open(src, "rb").read()
    with open(dst, "wb") as f:
        f.write(b"DSLB1" + nonce + AESGCM(key).encrypt(nonce, data, b"dosslap-backup-v1"))


def decrypt_file(src: str, dst: str, key: bytes) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = open(src, "rb").read()
    if not blob.startswith(b"DSLB1"):
        raise ValueError("neznámý formát zálohy")
    with open(dst, "wb") as f:
        f.write(AESGCM(key).decrypt(blob[5:17], blob[17:], b"dosslap-backup-v1"))


def main(argv=None) -> int:
    out_dir = os.environ.get("BACKUP_DIR")
    if not out_dir:
        print("Nastavte BACKUP_DIR.", file=sys.stderr)
        return 2
    os.makedirs(out_dir, exist_ok=True)
    key = _key()
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "backup")
        if engine.dialect.name == "sqlite":
            src = sqlite3.connect(engine.url.database)
            dst = sqlite3.connect(plain)
            src.backup(dst)
            dst.close()
            src.close()
            name = f"dosslap-{date.today().isoformat()}.db.enc"
        else:
            if not shutil.which("pg_dump"):
                print("pg_dump není nainstalovaný.", file=sys.stderr)
                return 3
            subprocess.run(["pg_dump", "--format=custom", "--file", plain, str(engine.url.render_as_string(hide_password=False))],
                           check=True)
            name = f"dosslap-{date.today().isoformat()}.pgdump.enc"
        encrypt_file(plain, os.path.join(out_dir, name), key)
    print(f"Záloha zapsána: {os.path.join(out_dir, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
