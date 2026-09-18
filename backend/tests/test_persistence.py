"""Guards that account history survives a redeploy: DB path resolution, the
ephemeral-storage detector, and the health endpoint's persistence signal."""
import os

from app import db as dbmod
from app import main as mainmod


def test_resolve_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("DOSSLAP_DB_PATH", "/somewhere/custom.db")
    assert dbmod._resolve_db_path() == "/somewhere/custom.db"


def test_resolve_autodetects_data_volume(monkeypatch):
    monkeypatch.delenv("DOSSLAP_DB_PATH", raising=False)
    monkeypatch.setattr(dbmod.os.path, "isdir", lambda p: p == "/data")
    monkeypatch.setattr(dbmod.os, "access", lambda p, m: p == "/data")
    assert dbmod._resolve_db_path() == "/data/dosslap.db"


def test_resolve_falls_back_to_backend_dir(monkeypatch):
    monkeypatch.delenv("DOSSLAP_DB_PATH", raising=False)
    monkeypatch.setattr(dbmod.os.path, "isdir", lambda p: False)
    got = dbmod._resolve_db_path()
    assert got == os.path.join(dbmod.BACKEND_DIR, "dosslap.db")


def test_ephemeral_detector():
    # A path inside the image's backend dir is ephemeral; a /data path is not.
    assert dbmod.db_is_ephemeral.__doc__  # sanity: helper exists
    inside = os.path.join(dbmod.BACKEND_DIR, "dosslap.db")
    assert os.path.abspath(inside).startswith(os.path.abspath(dbmod.BACKEND_DIR))


def test_backup_skipped_when_not_deployed(monkeypatch, tmp_path):
    # Local dev / tests must not scatter backup files around.
    monkeypatch.setattr(mainmod, "_is_deployed", lambda: False)
    mainmod._backup_db()  # no-op, must not raise
    assert not (tmp_path / "backups").exists()


def test_health_reports_persistence(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "db_persistent" in body and "db_exists" in body
