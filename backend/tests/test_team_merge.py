"""Issue #3 (owner request 2026-10-28): the owner reviews and merges a pull request from Team
Console. GitHub is faked; the point is that every gate is re-checked on the server at click time
and that nothing is merged unless all of them hold."""
import pytest

from app import models, team as T
from app.deps import reset_team_cache

from .conftest import register

BODY = "## What and why\nCloses #1\n\n## Change for runners\nTři nová čísla.\n\n## Gates\n"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("DOSSLAP_GITHUB_TOKEN", "read-token")
    monkeypatch.setenv("DOSSLAP_GITHUB_MERGE_TOKEN", "merge-token")
    monkeypatch.setenv("DOSSLAP_GITHUB_WEBHOOK_SECRET", "")
    reset_team_cache()
    yield
    reset_team_cache()


class FakeGH:
    """One open pull request #2; `pr` and `runs` can be changed per test."""
    def __init__(self, **over):
        self.pr = {"number": 2, "title": "Moje čísla", "state": "open", "draft": False, "mergeable": True,
                   "base": {"ref": "main"}, "head": {"sha": "abc1234def", "ref": "ai/x"}, "user": {"login": "bot"},
                   "labels": [{"name": "feature"}], "body": BODY, "html_url": "https://github.com/x/y/pull/2",
                   "changed_files": 3, "additions": 10, "deletions": 2, **over}
        self.runs = [{"name": "backend", "status": "completed", "conclusion": "success"}]
        self.calls = []

    def __call__(self, method, path, json=None, params=None, token=None):
        self.calls.append((method, path, json, token))
        if method == "GET" and path == "/pulls/2":
            return self.pr
        if method == "GET" and path.endswith("/check-runs"):
            return {"check_runs": self.runs}
        if method == "PUT" and path == "/pulls/2/merge":
            return {"merged": True, "sha": "9999999aaaa"}
        return {}

    def merged(self):
        return [c for c in self.calls if c[0] == "PUT"]


_n = iter(range(1000))


def _owner(client, monkeypatch, email=None):
    email = email or f"merge-majitel{next(_n)}@tc.test.cz"      # one account per test
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", email)
    register(client, email, "Majitel", "runner")
    return email


def _go(client, **over):
    body = {"sha": "abc1234def", "confirm": "MERGE #2", "password": "testpass123", **over}
    return client.post("/api/team/pr/2/merge", json=body)


def test_review_shows_what_github_says_now(client, monkeypatch):
    _owner(client, monkeypatch)
    monkeypatch.setattr(T, "gh", FakeGH())
    r = client.get("/api/team/pr/2").json()
    assert r["sha"] == "abc1234def" and r["checks"] == "success" and r["blockers"] == []
    assert r["summary"] == "Tři nová čísla." and r["canMerge"] and r["mergeToken"] and r["needsPassword"]
    assert r["files"] == 3 and r["closes"] == [1]


def test_happy_path_merges_once_with_the_merge_token_and_audits(client, db_session, monkeypatch):
    owner = _owner(client, monkeypatch)
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    db_session.add(models.WorkItem(kind="pr", number=2, title="Moje čísla", state="open", closes=[1], labels=[]))
    db_session.commit()
    r = _go(client)
    assert r.status_code == 200 and r.json()["merged"]
    (_, path, payload, token), = fake.merged()
    assert path == "/pulls/2/merge" and token == "merge-token"
    assert payload["merge_method"] == "squash" and payload["sha"] == "abc1234def"
    reads = [c for c in fake.calls if c[0] == "GET"]
    assert reads and all(c[3] is None for c in reads)              # only the merge itself uses the merge token
    db_session.expire_all()
    assert db_session.query(models.WorkItem).filter_by(kind="pr", number=2).one().state == "merged"
    a = db_session.query(models.TeamAudit).filter_by(action="pr.merge").one()
    assert a.target == "pr:2" and a.actor_email == owner


@pytest.mark.parametrize("over,words", [
    ({"state": "closed"}, "není otevřený"),
    ({"draft": True}, "draft"),
    ({"mergeable": False}, "konfliktu"),
    ({"mergeable": None}, "počítá"),
    ({"base": {"ref": "release"}}, "main"),
    ({"body": "## What and why\nbez shrnutí"}, "Change for runners"),
    ({"labels": [{"name": "engine"}]}, "klinické schválení"),
    ({"labels": [{"name": "safety"}, {"name": "clinical-approved"}, {"name": "clinical-changes"}]}, "klinické schválení"),
    ({"labels": [{"name": "security"}]}, "/cso"),
])
def test_a_gate_blocks_the_merge(client, db_session, monkeypatch, over, words):
    owner = _owner(client, monkeypatch)
    fake = FakeGH(**over)
    monkeypatch.setattr(T, "gh", fake)
    r = _go(client)
    assert r.status_code == 409 and words in r.json()["detail"]
    assert not fake.merged()
    assert db_session.query(models.TeamAudit).filter_by(action="pr.merge.blocked", actor_email=owner).count() == 1


def test_gated_labels_pass_with_the_sign_off_and_security_with_the_cso_box(client, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH(labels=[{"name": "engine"}, {"name": "clinical-approved"}, {"name": "security"}])
    monkeypatch.setattr(T, "gh", fake)
    assert _go(client).status_code == 409                     # security without the /cso box
    assert _go(client, cso=True).status_code == 200 and len(fake.merged()) == 1


@pytest.mark.parametrize("runs", [
    [{"name": "backend", "status": "completed", "conclusion": "failure"}],
    [{"name": "backend", "status": "in_progress", "conclusion": None}],
    [],
])
def test_ci_must_be_green_on_the_head(client, monkeypatch, runs):
    _owner(client, monkeypatch)
    fake = FakeGH()
    fake.runs = runs
    monkeypatch.setattr(T, "gh", fake)
    assert _go(client).status_code == 409 and not fake.merged()


def test_a_new_push_cancels_the_merge(client, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH(head={"sha": "ffff000aaaa", "ref": "ai/x"})
    monkeypatch.setattr(T, "gh", fake)
    r = _go(client)
    assert r.status_code == 409 and "nový commit" in r.json()["detail"] and not fake.merged()


def test_confirmation_and_password_are_required(client, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    assert _go(client, confirm="MERGE #3").status_code == 422
    assert _go(client, confirm="merge").status_code == 422
    assert _go(client, password="spatne-heslo").status_code == 403
    assert _go(client, password="").status_code == 403
    assert not fake.merged()


def test_only_an_owner_can_merge_and_nobody_without_the_token(client, db_session, monkeypatch):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "")
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    register(client, "merge-inzenyr@tc.test.cz", "Inženýr", "runner")
    db_session.add(models.TeamMember(email="merge-inzenyr@tc.test.cz", role="engineer", active=True, created_at=T.E.now_iso()))
    db_session.commit()
    reset_team_cache()
    assert client.get("/api/team/pr/2").status_code == 200       # may look
    assert _go(client).status_code == 403 and client.get("/api/team/pr/2").json()["canMerge"] is False
    assert client.post("/api/team/work/9/go", json={}).status_code == 403
    _owner(client, monkeypatch)
    monkeypatch.setenv("DOSSLAP_GITHUB_MERGE_TOKEN", "")
    r = _go(client)
    assert r.status_code == 503 and "DOSSLAP_GITHUB_MERGE_TOKEN" in r.json()["detail"]
    assert not fake.merged()


def test_refused_attempts_lock_the_owner_out_for_a_while(client, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    for _ in range(T.MERGE_TRIES):
        assert _go(client, password="spatne-heslo").status_code == 403
    assert _go(client).status_code == 429 and not fake.merged()


def test_github_refusing_the_merge_is_reported_and_audited(client, db_session, monkeypatch):
    owner = _owner(client, monkeypatch)
    fake = FakeGH()

    def refuse(method, path, json=None, params=None, token=None):
        if method == "PUT":
            raise T.GitHubError(405, "GitHub 405: Required status check is expected")
        return fake(method, path, json, params, token)
    monkeypatch.setattr(T, "gh", refuse)
    r = _go(client)
    assert r.status_code == 409 and "405" in r.json()["detail"]
    assert db_session.query(models.TeamAudit).filter_by(action="pr.merge.blocked", actor_email=owner).count() == 1


def test_owner_remark_and_go_on_a_plan(client, db_session, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH()
    monkeypatch.setattr(T, "gh", fake)
    assert client.post("/api/team/pr/2/comment", json={"text": "Přejmenujte kartu"}).status_code == 200
    assert any(c[1] == "/issues/2/comments" and "Přejmenujte kartu" in c[2]["body"] for c in fake.calls)
    assert client.post("/api/team/work/3/go", json={}).status_code == 404       # not a plan
    db_session.add(models.WorkItem(kind="issue", number=3, title="Plán", state="open", labels=["feature", "ai-plan"]))
    db_session.commit()
    r = client.post("/api/team/work/3/go", json={})
    assert r.status_code == 200 and "ai-ready" in r.json()["labels"] and "ai-plan" not in r.json()["labels"]
    assert ("DELETE", "/issues/3/labels/ai-plan", None, None) in fake.calls
    assert db_session.query(models.TeamAudit).filter_by(action="plan.go", target="issue:3").count() >= 1


def test_blocked_gates_do_not_lock_the_owner_out(client, monkeypatch):
    _owner(client, monkeypatch)
    fake = FakeGH()
    fake.runs = [{"name": "backend", "status": "completed", "conclusion": "failure"}]
    monkeypatch.setattr(T, "gh", fake)
    for _ in range(T.MERGE_TRIES + 2):
        assert _go(client).status_code == 409                # red CI, again and again: never 429
    fake.runs = [{"name": "backend", "status": "completed", "conclusion": "success"}]
    assert _go(client).status_code == 200
