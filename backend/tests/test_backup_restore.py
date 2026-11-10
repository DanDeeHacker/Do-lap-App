"""Physio brief 2026-11-09 R5.5 / R12: the verifier script, an encrypted backup and a restore test that runs the
verifier against the restored copy."""
import base64
import os

from app.scripts import backup_db, restore_test, verify_records


def test_backup_restores_and_verifies(client, tmp_path, monkeypatch, db_session):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    assert verify_records.main([]) == 0
    assert backup_db.main([]) == 0
    files = list(tmp_path.glob("dosslap-*.db.enc"))
    assert files and files[0].read_bytes()[:5] == b"DSLB1"
    assert b"clinical_records" not in files[0].read_bytes()          # encrypted, not a plain SQLite file
    assert restore_test.main([]) == 0
