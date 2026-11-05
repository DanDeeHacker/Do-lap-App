"""Issue #8 (note #224): several roles for one person, editing members, and the self-sign-off
flag (option b: allowed, marked on the merge screen and in the audit log)."""
import pytest

from app import models, team as T
from app.deps import is_owner, reset_team_cache

from .conftest import login, register


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("DOSSLAP_GITHUB_TOKEN", "")
    monkeypatch.setenv("DOSSLAP_GITHUB_MERGE_TOKEN", "merge-token")
    reset_team_cache()
    yield
    reset_team_cache()


def _owner(client, monkeypatch, email):
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", email)
    register(client, email, "Majitel", "runner")
    return email


def _accept(client, invite_path):
    r = client.post("/api/team/invite/accept", json={"token": invite_path.rsplit("/", 1)[1]})
    assert r.status_code == 200, r.text
    reset_team_cache()
    return r.json()


def test_one_person_can_be_owner_and_clinical_guarantor(client, db_session, monkeypatch):
    boss = _owner(client, monkeypatch, "roles-boss1@tc.test.cz")
    r = client.post("/api/team/members", json={"email": "roles-co1@tc.test.cz", "roles": ["clinical", "owner"]})
    assert r.status_code == 200 and r.json()["roles"] == ["owner", "clinical"] and r.json()["role"] == "owner"
    invite = r.json()["invitePath"]
    register(client, "roles-co1@tc.test.cz", "Spolumajitel", "runner")
    _accept(client, invite)
    me = client.get("/api/team/me").json()
    assert me["roles"] == ["owner", "clinical"] and me["role"] == "owner"
    assert "team.manage" in me["perms"] and "approvals.decide" in me["perms"] and "pr.merge" in me["perms"]
    user = db_session.query(models.User).filter_by(email="roles-co1@tc.test.cz").one()
    assert is_owner(user)
    assert boss                                                       # the env owner is unchanged
    audit = db_session.query(models.TeamAudit).filter_by(action="member.accept", target="roles-co1@tc.test.cz").one()
    assert audit.actor_role == "owner+clinical"


def test_an_owner_from_the_railway_variable_can_get_an_extra_role(client, monkeypatch):
    boss = _owner(client, monkeypatch, "roles-boss2@tc.test.cz")
    assert client.post("/api/team/members", json={"email": boss, "roles": ["owner"]}).status_code == 409
    r = client.post("/api/team/members", json={"email": boss, "roles": ["owner", "clinical"]})
    assert r.status_code == 200 and r.json()["roles"] == ["clinical"]          # owner stays implicit
    assert client.get("/api/team/me").json()["roles"] == ["owner"]             # until the link is opened
    _accept(client, r.json()["invitePath"])
    me = client.get("/api/team/me").json()
    assert me["roles"] == ["owner", "clinical"] and "approvals.decide" in me["perms"]


def test_roles_are_validated_and_replaced(client, monkeypatch):
    _owner(client, monkeypatch, "roles-boss3@tc.test.cz")
    m = client.post("/api/team/members", json={"email": "roles-eng3@tc.test.cz", "role": "engineer"}).json()
    assert m["roles"] == ["engineer"]
    assert client.patch(f"/api/team/members/{m['id']}", json={"roles": []}).status_code == 422
    assert client.patch(f"/api/team/members/{m['id']}", json={"roles": ["engineer", "boss"]}).status_code == 422
    r = client.patch(f"/api/team/members/{m['id']}", json={"roles": ["auditor", "engineer"]})
    assert r.status_code == 200 and r.json()["roles"] == ["engineer", "auditor"] and r.json()["role"] == "engineer"
    assert client.post("/api/team/members", json={"email": "roles-x3@tc.test.cz", "roles": ["support", "nope"]}).status_code == 422
    assert client.post("/api/team/members", json={"email": "roles-y3@tc.test.cz"}).status_code == 422


def test_name_edit_and_email_correction_while_the_invitation_is_pending(client, monkeypatch):
    _owner(client, monkeypatch, "roles-boss4@tc.test.cz")
    m = client.post("/api/team/members", json={"email": "roles-typo4@tc.test.cz", "role": "support"}).json()
    old = m["invitePath"]
    r = client.patch(f"/api/team/members/{m['id']}", json={"name": "Eva Podpora"})
    assert r.status_code == 200 and r.json()["name"] == "Eva Podpora" and "invitePath" not in r.json()
    r = client.patch(f"/api/team/members/{m['id']}", json={"email": "Roles-Right4@TC.test.cz"})
    assert r.status_code == 200 and r.json()["email"] == "roles-right4@tc.test.cz"
    new = r.json()["invitePath"]
    assert new != old
    assert client.post("/api/team/invite/accept", json={"token": old.rsplit("/", 1)[1]}).status_code == 404   # old link is dead
    assert client.patch(f"/api/team/members/{m['id']}", json={"email": "no-at-sign"}).status_code == 422
    other = client.post("/api/team/members", json={"email": "roles-other4@tc.test.cz", "role": "auditor"}).json()
    assert client.patch(f"/api/team/members/{other['id']}", json={"email": "roles-right4@tc.test.cz"}).status_code == 409
    # once accepted the address is tied to the account and cannot be changed
    register(client, "roles-right4@tc.test.cz", "Eva", "runner")
    _accept(client, new)
    login(client, "roles-boss4@tc.test.cz", "testpass123")
    assert client.patch(f"/api/team/members/{m['id']}", json={"email": "roles-else4@tc.test.cz"}).status_code == 409


def test_nobody_removes_their_own_owner_role(client, monkeypatch):
    _owner(client, monkeypatch, "roles-boss5@tc.test.cz")
    m = client.post("/api/team/members", json={"email": "roles-co5@tc.test.cz", "role": "owner"}).json()
    register(client, "roles-co5@tc.test.cz", "Spolumajitel", "runner")
    _accept(client, m["invitePath"])
    assert client.patch(f"/api/team/members/{m['id']}", json={"roles": ["engineer"]}).status_code == 409
    assert client.patch(f"/api/team/members/{m['id']}", json={"active": False}).status_code == 409
    assert client.patch(f"/api/team/members/{m['id']}", json={"roles": ["owner", "clinical"]}).status_code == 200


class _GH:
    def __call__(self, method, path, json=None, params=None, token=None):
        if method == "GET" and path == "/pulls/7":
            return {"number": 7, "title": "T", "state": "open", "draft": False, "mergeable": True, "base": {"ref": "main"},
                    "head": {"sha": "abc1234def", "ref": "ai/x"}, "user": {"login": "bot"}, "labels": [{"name": "engine"}, {"name": "clinical-approved"}],
                    "body": "## Change for runners\nText\n", "html_url": "u", "changed_files": 1, "additions": 1, "deletions": 0}
        if path.endswith("/check-runs"):
            return {"check_runs": [{"name": "backend", "status": "completed", "conclusion": "success"}]}
        return {}


def test_self_signoff_is_flagged_on_the_review_screen(client, db_session, monkeypatch):
    boss = _owner(client, monkeypatch, "roles-boss6@tc.test.cz")
    monkeypatch.setattr(T, "gh", _GH())
    db_session.add(models.WorkItem(kind="pr", number=7, title="T", state="open", labels=["engine", "clinical-approved"],
                                   clinical="approved", clinical_by="someone-else@tc.test.cz", clinical_sha="abc1234def"))
    db_session.commit()
    assert client.get("/api/team/pr/7").json()["selfSignoff"] is False
    row = db_session.query(models.WorkItem).filter_by(kind="pr", number=7).one()
    row.clinical_by = boss
    db_session.commit()
    assert client.get("/api/team/pr/7").json()["selfSignoff"] is True
