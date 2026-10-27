"""Team Console (owner request 2026-10-27): roles and audit, inbox → GitHub issue, the webhook's
work queue, the clinical sign-off, releases and the pilot gates. GitHub is faked: tests never
reach the network."""
import hashlib
import hmac
import json

import pytest

from app import models, team as T
from app.deps import reset_team_cache

from .conftest import login, register


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("DOSSLAP_GITHUB_TOKEN", "")
    monkeypatch.setenv("DOSSLAP_GITHUB_WEBHOOK_SECRET", "")
    reset_team_cache()
    yield
    reset_team_cache()


class FakeGH:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, json=None, params=None):
        self.calls.append((method, path, json))
        if method == "POST" and path == "/issues":
            return {"number": 41, "html_url": "https://github.com/x/y/issues/41", "title": json["title"],
                    "labels": [{"name": n} for n in json["labels"]], "state": "open", "user": {"login": "app"}}
        return {}


def _owner(client, monkeypatch, email="tc-majitel@tc.test.cz"):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", email)
    register(client, email, "Majitel", "runner")
    return email


def test_only_the_team_gets_in(client, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "")
    register(client, "tc-cizi@tc.test.cz", "Cizí", "runner")
    assert client.get("/api/team/me").status_code == 403
    _owner(client, monkeypatch)
    me = client.get("/api/team/me").json()
    assert me["role"] == "owner" and "team.manage" in me["perms"] and me["config"]["github"] is False


def test_owner_adds_a_clinical_guarantor_and_the_role_limits_them(client, db_session, monkeypatch):
    _owner(client, monkeypatch, "majitel2@tc.test.cz")
    r = client.post("/api/team/members", json={"email": "Garant@TC.test.cz", "name": "MUDr. Garant", "role": "clinical"})
    assert r.status_code == 200 and r.json()["email"] == "garant@tc.test.cz"
    assert client.post("/api/team/members", json={"email": "x@tc.test.cz", "role": "boss"}).status_code == 422
    register(client, "garant@tc.test.cz", "Garant", "physio")
    me = client.get("/api/team/me").json()
    assert me["role"] == "clinical" and "approvals.decide" in me["perms"]
    assert client.post("/api/team/members", json={"email": "y@tc.test.cz", "role": "owner"}).status_code == 403
    assert client.get("/api/team/pilot").status_code == 403
    assert client.get("/api/team/approvals").status_code == 200
    audit = db_session.query(models.TeamAudit).filter(models.TeamAudit.action == "member.add").all()
    assert any(a.target == "garant@tc.test.cz" and a.actor_email == "majitel2@tc.test.cz" for a in audit)


def test_a_team_owner_is_an_app_owner(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "")
    register(client, "spolutc-majitel@tc.test.cz", "Spolumajitel", "runner")
    assert client.get("/api/auth/me").json()["owner"] is False
    db_session.add(models.TeamMember(email="spolutc-majitel@tc.test.cz", role="owner", active=True, created_at=T.E.now_iso()))
    db_session.commit()
    reset_team_cache()
    assert client.get("/api/auth/me").json()["owner"] is True
    assert client.get("/api/admin/runners").status_code == 200


def _note(client, email, text="Na Dnes se graf překrývá s tlačítkem", kind="bug"):
    register(client, email, "Běžkyně Eva", "runner")
    r = client.post("/api/annotations", json={"route": "/app/today", "note": text, "kind": kind,
                                              "anchorText": "Připravenost", "context": {"heading": "Dnes"}})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_inbox_send_needs_owner_approval_and_redacts(client, db_session, monkeypatch):
    nid = _note(client, "eva@tc.test.cz")
    owner = "majitel3@tc.test.cz"
    _owner(client, monkeypatch, owner)
    client.post("/api/team/members", json={"email": "podpora@tc.test.cz", "role": "support"})
    client.post("/api/team/members", json={"email": "inzenyr@tc.test.cz", "role": "engineer"})

    # support triages, cannot approve; the inbox shows the reporter's role, not the name
    register(client, "podpora@tc.test.cz", "Podpora", "runner")
    items = client.get("/api/team/inbox").json()["items"]
    mine = next(x for x in items if x["id"] == nid)
    assert mine["author"] == {"role": "runner", "isOwner": False} and not mine["ready"]
    assert client.patch(f"/api/team/inbox/{nid}", json={"priority": "P1", "type": "bug"}).status_code == 200
    assert client.patch(f"/api/team/inbox/{nid}", json={"approved": True}).status_code == 403

    # an engineer cannot send an unapproved user note
    register(client, "inzenyr@tc.test.cz", "Inženýr", "runner")
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    r = client.post(f"/api/team/inbox/{nid}/send", json={"title": "Graf se překrývá", "text": "Graf přes tlačítko"})
    assert r.status_code == 409 and not fake.calls

    # the owner sends it: approval, labels, the edited text, no name or e-mail
    login(client, owner, "testpass123")
    r = client.post(f"/api/team/inbox/{nid}/send", json={"title": "Graf se překrývá", "text": "Graf přes tlačítko na Dnes"})
    assert r.status_code == 200 and r.json()["issueNumber"] == 41
    (_, path, payload), = fake.calls
    assert path == "/issues" and set(payload["labels"]) == {"ai-ready", "from-app", "bug"}
    body = payload["body"]
    assert "Graf přes tlačítko na Dnes" in body and f"<!-- doslap-note:{nid} -->" in body and "/app/today" in body
    assert "eva@tc.test.cz" not in body and "Eva" not in body and "priorita P1" in body
    db_session.expire_all()
    a = db_session.get(models.Annotation, nid)
    assert a.approved_at and a.issue_number == 41
    assert client.post(f"/api/team/inbox/{nid}/send", json={"title": "znovu", "text": "x"}).status_code == 409


def test_send_without_github_says_what_is_missing(client, monkeypatch):
    nid = _note(client, "eva2@tc.test.cz")
    _owner(client, monkeypatch, "majitel4@tc.test.cz")
    r = client.post(f"/api/team/inbox/{nid}/send", json={"title": "Něco", "text": "Text"})
    assert r.status_code == 503 and "DOSSLAP_GITHUB_TOKEN" in r.json()["detail"]


def _signed(client, event, payload, secret="tajne"):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/api/github/webhook", content=raw, headers={
        "X-Hub-Signature-256": sig, "X-GitHub-Event": event, "Content-Type": "application/json"})


def test_webhook_tracks_work_and_a_merged_pr_resolves_the_note(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_GITHUB_WEBHOOK_SECRET", "tajne")
    nid = _note(client, "eva3@tc.test.cz")
    assert client.post("/api/github/webhook", json={}, headers={"X-GitHub-Event": "ping"}).status_code == 401
    assert _signed(client, "ping", {}, secret="spatne").status_code == 401
    repo = {"full_name": T.repo()}
    issue = {"number": 77, "title": "Graf", "state": "open", "labels": [{"name": "ai-ready"}],
             "body": f"…\n<!-- doslap-note:{nid} -->", "html_url": "u", "user": {"login": "app"}}
    assert _signed(client, "issues", {"action": "opened", "issue": issue, "repository": repo}).json()["handled"] == "issue #77"
    pr = {"number": 78, "title": "Fix graf", "state": "open", "draft": False, "labels": [{"name": "engine"}],
          "body": "## What and why\nx\n\n## Change for runners\nGraf už nepřekrývá tlačítko.\n\nCloses #77",
          "head": {"sha": "abc"}, "merged_at": None, "html_url": "p", "user": {"login": "claude"}}
    _signed(client, "pull_request", {"action": "opened", "pull_request": pr, "repository": repo})
    _signed(client, "check_suite", {"check_suite": {"status": "completed", "conclusion": "success", "head_sha": "abc"}, "repository": repo})
    _owner(client, monkeypatch, "majitel5@tc.test.cz")
    items = {(x["kind"], x["number"]): x for x in client.get("/api/team/work").json()["items"]}
    p = items[("pr", 78)]
    assert p["stage"] == "needs_clinical" and p["checks"] == "success" and p["closes"] == [77]
    assert p["summary"] == "Graf už nepřekrývá tlačítko."
    assert items[("issue", 77)]["stage"] == "needs_clinical" and items[("issue", 77)]["annotationId"] == nid

    merged = {**pr, "state": "closed", "merged_at": "2026-10-27T10:00:00Z", "merge_commit_sha": "def1234567",
              "labels": [{"name": "engine"}, {"name": "clinical-approved"}]}
    _signed(client, "pull_request", {"action": "closed", "pull_request": merged, "repository": repo})
    db_session.expire_all()
    a = db_session.get(models.Annotation, nid)
    assert a.status == "done" and "#78" in a.resolution
    # another repository's events are ignored
    assert _signed(client, "issues", {"issue": issue, "repository": {"full_name": "someone/else"}}).json()["handled"] == "other repository"


def test_clinical_sign_off_labels_the_pr(client, db_session, monkeypatch):
    db_session.add(models.WorkItem(kind="pr", number=90, title="Práh únavy", state="open", labels=["engine"],
                                   created_at=T.E.now_iso(), updated_at=T.E.now_iso(), head_sha="h90"))
    db_session.commit()
    _owner(client, monkeypatch, "majitel6@tc.test.cz")
    client.post("/api/team/members", json={"email": "inz2@tc.test.cz", "role": "engineer"})
    client.post("/api/team/members", json={"email": "garant2@tc.test.cz", "role": "clinical"})
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    assert client.post("/api/team/approvals/90", json={"decision": "approve"}).status_code == 403   # owner is not the guarantor
    register(client, "inz2@tc.test.cz", "Inženýr", "runner")
    assert client.post("/api/team/approvals/90", json={"decision": "approve"}).status_code == 403
    register(client, "garant2@tc.test.cz", "Garant", "physio")
    pend = client.get("/api/team/approvals").json()
    assert [x["number"] for x in pend["pending"]] == [90] and pend["canDecide"]
    assert client.post("/api/team/approvals/90", json={"decision": "changes"}).status_code == 422
    r = client.post("/api/team/approvals/90", json={"decision": "approve", "note": "Prahy odpovídají literatuře."})
    assert r.status_code == 200 and r.json()["clinical"] == "approved" and "clinical-approved" in r.json()["labels"]
    paths = [(m, p) for m, p, _ in fake.calls]
    assert ("POST", "/issues/90/labels") in paths and ("DELETE", "/issues/90/labels/clinical-changes") in paths
    comment = next(j for m, p, j in fake.calls if p == "/issues/90/comments")["body"]
    assert "Clinical sign-off" in comment and "Prahy odpovídají literatuře." in comment
    assert client.get("/api/team/approvals").json()["pending"] == []
    db_session.expire_all()
    assert db_session.query(models.TeamAudit).filter(models.TeamAudit.action == "approval.approve",
                                                     models.TeamAudit.target == "pr:90").count() == 1


def test_releases_and_pilot(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "0123456789abcdef")
    _owner(client, monkeypatch, "majitel7@tc.test.cz")
    client.post("/api/client-errors", json={"message": "TypeError: x", "path": "/app/today", "where": "tab", "build": "b1"})
    rel = client.get("/api/team/releases").json()
    assert rel["production"]["sha"] == "0123456789abcdef" and rel["production"]["engine"] == T.E.ENGINE_VERSION
    assert rel["clientErrors"]["last24h"] >= 1 and rel["clientErrors"]["recent"][0]["message"] == "TypeError: x"
    assert "user" not in rel["clientErrors"]["recent"][0]
    assert rel["deployments"] == {"configured": False, "items": []}
    pil = client.get("/api/team/pilot").json()
    keys = {g["key"] for g in pil["gates"]}
    assert {"runners", "activation", "weekly", "retained", "physios", "churn", "events"} <= keys
    assert pil["history"] and pil["history"][-1]["runners"] >= 1   # the owner's own account counts


def test_stage_order():
    pr = models.WorkItem(kind="pr", number=1, state="open", labels=["safety"], draft=False)
    assert T.stage(pr, {}) == "needs_clinical"
    pr.clinical = "approved"
    assert T.stage(pr, {}) == "in_review"
    pr.state, pr.deployed = "merged", False
    assert T.stage(pr, {}) == "merged"
    pr.deployed = True
    assert T.stage(pr, {}) == "deployed"
    issue = models.WorkItem(kind="issue", number=2, state="open", labels=["ai-ready"])
    assert T.stage(issue, {}) == "queued" and T.stage(issue, {2: pr}) == "deployed"


def test_a_physio_guarantor_signs_in_through_the_runner_form(client, monkeypatch):
    _owner(client, monkeypatch, "majitel8@tc.test.cz")
    client.post("/api/team/members", json={"email": "garant3@tc.test.cz", "role": "clinical"})
    register(client, "garant3@tc.test.cz", "Garant", "physio")
    register(client, "fyzio-cizi@tc.test.cz", "Cizí fyzio", "physio")
    assert login(client, "fyzio-cizi@tc.test.cz", "testpass123", expected_role="runner").status_code == 403
    r = login(client, "garant3@tc.test.cz", "testpass123", expected_role="runner")
    assert r.status_code == 200 and r.json()["team"] == "clinical" and r.json()["role"] == "physio"
