"""Annotation mode — feedback notes pinned to the UI, and the token-protected
export / resolve the Claude Code sync script uses."""
from .conftest import register

TOKEN = "t" * 32
NOTE = {"route": "/app/mechanics", "selector": "main > div:nth-of-type(2) > section", "anchorText": "Historie běhů",
        "context": {"heading": "Pohyb", "fx": 0.4, "fy": 0.5, "vw": 400, "device": "phone", "secret": "x" * 5000},
        "note": "Tady by se hodil graf tempa.", "kind": "idea"}


def _login(client, email):
    register(client, email, email.split("@")[0], "runner")
    client.post("/api/auth/session", json={"email": email, "password": "testpass123"})


def test_notes_are_private_to_their_author(client):
    _login(client, "ann1@test.cz")
    a = client.post("/api/annotations", json=NOTE).json()
    assert a["own"] and a["status"] == "open" and a["context"] == {
        "heading": "Pohyb", "fx": 0.4, "fy": 0.5, "vw": 400, "device": "phone"}   # unknown keys dropped
    assert [x["id"] for x in client.get("/api/annotations").json()["items"]] == [a["id"]]
    _login(client, "ann2@test.cz")
    assert client.get("/api/annotations").json()["items"] == []
    assert client.patch(f"/api/annotations/{a['id']}", json={"note": "hack"}).status_code == 404
    assert client.delete(f"/api/annotations/{a['id']}").status_code == 404


def test_author_edits_resolves_and_deletes(client):
    _login(client, "ann3@test.cz")
    a = client.post("/api/annotations", json={**NOTE, "kind": "bug"}).json()
    b = client.patch(f"/api/annotations/{a['id']}", json={"note": "Opraveno znění", "status": "done"}).json()
    assert b["note"] == "Opraveno znění" and b["status"] == "done" and b["resolvedAt"]
    assert client.patch(f"/api/annotations/{a['id']}", json={"kind": "weird"}).status_code == 422
    assert client.post("/api/annotations", json={**NOTE, "note": ""}).status_code == 422
    assert client.post("/api/annotations", json={**NOTE, "route": "http://evil"}).status_code == 422
    assert client.delete(f"/api/annotations/{a['id']}").status_code == 204
    assert client.get("/api/annotations").json()["items"] == []


def test_cross_origin_writes_are_refused(client):
    _login(client, "ann4@test.cz")
    r = client.post("/api/annotations", json=NOTE, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_owner_sees_everyones_notes(client, monkeypatch):
    _login(client, "ann5@test.cz")
    mine = client.post("/api/annotations", json=NOTE).json()
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "Boss@test.cz")
    _login(client, "boss@test.cz")
    res = client.get("/api/annotations").json()
    assert res["owner"] is True
    row = next(x for x in res["items"] if x["id"] == mine["id"])
    assert row["own"] is False and row["author"] == {"name": "ann5", "role": "runner", "isOwner": False}
    assert client.patch(f"/api/annotations/{mine['id']}", json={"status": "wontfix"}).json()["status"] == "wontfix"


def test_export_and_resolve_need_the_token(client, monkeypatch):
    _login(client, "ann6@test.cz")
    a = client.post("/api/annotations", json=NOTE).json()
    client.cookies.clear()
    assert client.get("/api/annotations/export").status_code == 404          # no token configured → no endpoint
    monkeypatch.setenv("DOSSLAP_FEEDBACK_TOKEN", TOKEN)
    assert client.get("/api/annotations/export").status_code == 401
    assert client.get("/api/annotations/export", headers={"Authorization": "Bearer nope"}).status_code == 401
    auth = {"Authorization": f"Bearer {TOKEN}"}
    items = client.get("/api/annotations/export?status=open", headers=auth).json()["items"]
    row = next(x for x in items if x["id"] == a["id"])
    assert "email" not in str(row) and row["anchorText"] == "Historie běhů"
    r = client.post(f"/api/annotations/{a['id']}/resolve", json={"status": "done", "resolution": "abc123: graf tempa"},
                    headers=auth).json()
    assert r["status"] == "done" and r["resolution"] == "abc123: graf tempa"
    assert all(x["id"] != a["id"] for x in client.get("/api/annotations/export?status=open", headers=auth).json()["items"])
    assert client.post(f"/api/annotations/{a['id']}/resolve", json={"status": "done"}).status_code == 401


def test_sync_script_mirrors_both_sources_and_resolves(client, monkeypatch, tmp_path):
    import feedback_sync as FS
    _login(client, "ann7@test.cz")
    a = client.post("/api/annotations", json={**NOTE, "kind": "bug", "note": "Chybí jednotka\nu tempa"}).json()
    monkeypatch.setattr(FS, "OUT_DIR", tmp_path)
    monkeypatch.setattr(FS, "MIRROR", tmp_path / "annotations.db")
    monkeypatch.setattr(FS, "DIGEST", tmp_path / "OPEN.md")
    monkeypatch.setattr(FS, "ROOT", tmp_path.parent)
    monkeypatch.setenv("DOSSLAP_FEEDBACK_TOKEN", TOKEN)
    monkeypatch.setenv("DOSSLAP_PROD_URL", "https://prod.example")
    client.cookies.clear()

    def fake_http(method, url, token, body=None):   # "Railway" = this same test app
        path = url.removeprefix("https://prod.example")
        r = client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        return r.json()
    monkeypatch.setattr(FS, "_http", fake_http)
    assert FS.main(["pull"]) == 0
    md = (tmp_path / "OPEN.md").read_text(encoding="utf-8")
    assert f"railway#{a['id']} · Chyba · `/app/mechanics`" in md          # third-party on "Railway" …
    assert f"local#{a['id']} · Chyba" in md                                # … and trusted in the local DB
    others = md.split("## Od ostatních uživatelů")[1]
    assert f"railway#{a['id']}" in others and "> Chybí jednotka\n> u tempa" in others
    assert FS.main(["resolve", f"railway#{a['id']}", "--note", "abc123: jednotka doplněna"]) == 0
    md = (tmp_path / "OPEN.md").read_text(encoding="utf-8")
    assert f"railway#{a['id']}" not in md and f"local#{a['id']}" not in md   # same row in both sources here
    assert FS.main(["resolve", "bogus"]) == 2
