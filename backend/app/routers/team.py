"""Team Console (owner request 2026-10-27): Admin → Tým, Inbox, Práce, Schválení, Vydání, Pilot.
The founders run the AI engineering team (gstack sprints on GitHub) from the app: who is on the
team, which feedback goes to the AI team, what is being built, the clinical sign-off of engine
and safety changes, what production runs, and the pilot's numbers. The logic is in app/team.py;
this module is the HTTP surface and the permission checks. Every write lands in the audit log."""
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.orm import Session as DBSession

from .. import models, team as T
from ..db import db_location_info, get_db
from ..deps import get_current_user, is_owner, owner_emails, verify_csrf
from ..metrics import engine as E
from ..schemas import Lenient
from ..security import verify_password

router = APIRouter(prefix="/api/team", tags=["team"])
hook_router = APIRouter(tags=["team"])

PRIORITIES = ("P1", "P2", "P3")
TYPES = ("bug", "feature", "engine", "safety", "copy")


class Ctx:
    def __init__(self, user: models.User, role: str | None, db: DBSession):
        self.user, self.role, self.db = user, role, db

    def need(self, perm: str) -> "Ctx":
        if not T.can(self.role, perm):
            raise HTTPException(status_code=403, detail="Na tuto část Team Console nemáte oprávnění")
        return self

    def audit(self, action: str, target: str | None = None, **detail) -> None:
        T.audit(self.db, self.user, self.role, action, target, detail)


def ctx(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)) -> Ctx:
    role = T.role_of(db, user)
    if role is None:
        raise HTTPException(status_code=403, detail="Jen pro tým Došlapu")
    return Ctx(user, role, db)


def _gh(fn):
    try:
        return fn()
    except T.GitHubError as e:
        raise HTTPException(status_code=e.status if e.status in (409, 422, 503) else 502, detail=str(e)) from None


# ---------------------------------------------------------------- me / team / audit
@router.get("/me")
def me(c: Ctx = Depends(ctx)):
    return {"role": c.role, "perms": sorted(T.PERMS[c.role]), "config": T.config(), "email": c.user.email}


class MemberIn(Lenient):
    email: str = Field(min_length=3, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    role: str


class MemberPatch(Lenient):
    name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    active: bool | None = None


@router.get("/members")
def members(c: Ctx = Depends(ctx)):
    if not (T.can(c.role, "team.manage") or T.can(c.role, "audit.read")):
        c.need("team.manage")
    rows = c.db.query(models.TeamMember).order_by(models.TeamMember.active.desc(), models.TeamMember.role,
                                                  models.TeamMember.email).all()
    accounts = {(u.email or "").lower() for u in c.db.query(models.User).filter(
        models.User.email.in_(sorted(owner_emails()))).all()}
    env = [{"email": e, "role": "owner", "active": True, "env": True, "hasAccount": e in accounts} for e in sorted(owner_emails())]
    return {"env": env, "items": [{**T.member_out(m), "hasAccount": m.user_id is not None} for m in rows], "roles": list(T.ROLES)}


@router.post("/members", dependencies=[Depends(verify_csrf)])
def add_member(body: MemberIn, c: Ctx = Depends(ctx)):
    c.need("team.manage")
    email = body.email.strip().lower()
    if body.role not in T.ROLES or "@" not in email:
        raise HTTPException(status_code=422, detail="Neplatný e-mail nebo role")
    if email in owner_emails():
        raise HTTPException(status_code=409, detail="Tento e-mail je vlastník z proměnné DOSSLAP_OWNER_EMAILS")
    m = c.db.query(models.TeamMember).filter(models.TeamMember.email == email).first()
    now = E.now_iso()
    if m is None:
        m = models.TeamMember(email=email, created_at=now, invited_by=c.user.email)
        c.db.add(m)
    m.name, m.role, m.active, m.updated_at = body.name or m.name, body.role, True, now
    # review 2026-10-30 N1: the role starts only when the person opens the single-use link with
    # their own account; the owner passes the link on themselves (the app sends no e-mail)
    token = T.new_invite(m) if m.user_id is None else None
    c.audit("member.add", email, role=body.role)
    c.db.commit()
    T.team_changed()
    return {**T.member_out(m), **({"invitePath": f"/pozvanka/{token}"} if token else {})}


@router.post("/members/{mid}/invite", dependencies=[Depends(verify_csrf)])
def reinvite(mid: int, c: Ctx = Depends(ctx)):
    """A new invitation link (the old one stops working) for a member who hasn't accepted yet."""
    c.need("team.manage")
    m = c.db.get(models.TeamMember, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Člen týmu nenalezen")
    if m.user_id is not None:
        raise HTTPException(status_code=409, detail="Pozvánku už přijal")
    token = T.new_invite(m)
    m.updated_at = E.now_iso()
    c.audit("member.invite", m.email)
    c.db.commit()
    return {**T.member_out(m), "invitePath": f"/pozvanka/{token}"}


class InviteAccept(Lenient):
    token: str = Field(min_length=10, max_length=200)


@router.post("/invite/accept", dependencies=[Depends(verify_csrf)])
def accept_invite(body: InviteAccept, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """The invited person opens the link signed in with the account the invitation names."""
    m = T.find_invite(db, body.token)
    if m is None:
        raise HTTPException(status_code=404, detail="Pozvánka neplatí — je použitá, zrušená nebo starší než 7 dní.")
    if (user.email or "").lower() != m.email:
        raise HTTPException(status_code=403, detail="Pozvánka je pro jiný e-mail. Přihlaste se účtem, na který byla poslaná.")
    if db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id, models.TeamMember.id != m.id).first():
        raise HTTPException(status_code=409, detail="Tento účet už v týmu je.")
    m.user_id, m.invite_hash, m.invite_expires_at, m.updated_at = user.id, None, None, E.now_iso()
    T.audit(db, user, m.role, "member.accept", m.email, {"role": m.role})
    db.commit()
    T.team_changed()
    return {"role": m.role}


@router.patch("/members/{mid}", dependencies=[Depends(verify_csrf)])
def patch_member(mid: int, body: MemberPatch, c: Ctx = Depends(ctx)):
    c.need("team.manage")
    m = c.db.get(models.TeamMember, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Člen týmu nenalezen")
    if body.role is not None and body.role not in T.ROLES:
        raise HTTPException(status_code=422, detail="Neznámá role")
    if m.user_id == c.user.id and (body.active is False or (body.role and body.role != "owner")):
        raise HTTPException(status_code=409, detail="Sami sobě roli vlastníka neodeberete")
    changes = {}
    for k in ("name", "role", "active"):
        v = getattr(body, k)
        if v is not None and v != getattr(m, k):
            changes[k] = [getattr(m, k), v]
            setattr(m, k, v)
    m.updated_at = E.now_iso()
    c.audit("member.update", m.email, **changes)
    c.db.commit()
    T.team_changed()
    return T.member_out(m)


# ---------------------------------------------------------------- physio accounts (review 2026-10-30 F1)
@router.get("/physios")
def physio_accounts(c: Ctx = Depends(ctx)):
    """Every physio account with its e-mail, profile and whether an owner has verified it."""
    c.need("team.manage")
    users = {u.physio_id: u for u in c.db.query(models.User).filter(models.User.physio_id.isnot(None)).all()}
    out = []
    for p in c.db.query(models.Physio).order_by(models.Physio.verified_at.isnot(None), models.Physio.id).all():
        u = users.get(p.id)
        clinic = c.db.get(models.Clinic, p.clinic_id) if p.clinic_id else None
        out.append({"id": p.id, "name": p.name, "email": u.email if u else None, "credential": p.credential,
                    "clinic": clinic.name if clinic else None, "city": clinic.city if clinic else None,
                    "createdAt": u.created_at if u else None, "verified": bool(p.verified_at),
                    "verifiedAt": p.verified_at, "verifiedBy": p.verified_by})
    return {"items": out}


class PhysioVerifyIn(Lenient):
    verified: bool


@router.post("/physios/{pid}/verify", dependencies=[Depends(verify_csrf)])
def verify_physio(pid: str, body: PhysioVerifyIn, c: Ctx = Depends(ctx)):
    """An owner checked the person and their professional registration outside the app."""
    c.need("team.manage")
    p = c.db.get(models.Physio, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")
    p.verified_at, p.verified_by = (E.now_iso(), c.user.email) if body.verified else (None, None)
    c.audit("physio.verify" if body.verified else "physio.unverify", pid)
    c.db.commit()
    return {"id": p.id, "verified": bool(p.verified_at)}


@router.get("/audit")
def audit_log(limit: int = 200, c: Ctx = Depends(ctx)):
    c.need("audit.read")
    rows = c.db.query(models.TeamAudit).order_by(models.TeamAudit.id.desc()).limit(max(1, min(limit, 1000))).all()
    return {"items": [{"id": r.id, "at": r.at, "actor": r.actor_email, "role": r.actor_role, "action": r.action,
                       "target": r.target, "detail": r.detail_json or {}} for r in rows]}


# ---------------------------------------------------------------- inbox
def _note_out(a: models.Annotation, author: models.User | None, viewer_owner: bool) -> dict:
    ready = bool(author and is_owner(author)) or bool(a.approved_at)
    return {"id": a.id, "route": a.route, "anchorText": a.anchor_text, "note": a.note, "kind": a.kind,
            "status": a.status, "priority": a.priority, "type": a.triage_type, "assignee": a.assignee,
            "issueNumber": a.issue_number, "issueUrl": a.issue_url, "ready": ready, "approvedAt": a.approved_at,
            "createdAt": a.created_at, "resolution": a.resolution, "heading": (a.context_json or {}).get("heading"),
            # simulated runners (app/personas): which persona, how often it recurred, re-verified after a fix
            "synthetic": {k: (a.context_json or {}).get(k) for k in ("persona", "simDate", "check", "repeats", "lastSeen", "verifiedAt")}
            if a.source else None, "source": a.source,
            # a name only for owners; the rest of the team sees the reporter's role
            "author": {"role": author.role if author else None, "isOwner": bool(author and is_owner(author)),
                       **({"name": author.name} if viewer_owner and author else {})}}


@router.get("/inbox")
def inbox(status: str = "open", source: str = "all", c: Ctx = Depends(ctx)):
    c.need("inbox.read")
    q = c.db.query(models.Annotation, models.User).join(models.User, models.Annotation.user_id == models.User.id)
    if status in ("open", "done", "wontfix"):
        q = q.filter(models.Annotation.status == status)
    if source == "people":
        q = q.filter(models.Annotation.source.is_(None))
    elif source == "synthetic":
        q = q.filter(models.Annotation.source.isnot(None))
    rows = q.order_by(models.Annotation.id.desc()).limit(300).all()
    owner = c.role == "owner"
    items = [_note_out(a, u, owner) for a, u in rows]
    rank = {"P1": 0, "P2": 1, "P3": 2}
    items.sort(key=lambda x: (x["issueNumber"] is not None, rank.get(x["priority"], 3), -x["id"]))
    members = [m.email for m in c.db.query(models.TeamMember).filter(models.TeamMember.active.is_(True)).all()]
    return {"items": items, "assignees": sorted(set(members) | owner_emails()), "types": list(TYPES),
            "priorities": list(PRIORITIES), "github": T.config()["github"]}


class TriageIn(Lenient):
    priority: str | None = None
    type: str | None = None
    assignee: str | None = None
    status: str | None = None
    approved: bool | None = None


@router.patch("/inbox/{aid}", dependencies=[Depends(verify_csrf)])
def triage(aid: int, body: TriageIn, c: Ctx = Depends(ctx)):
    c.need("inbox.triage")
    a = c.db.get(models.Annotation, aid)
    if a is None:
        raise HTTPException(status_code=404, detail="Poznámka nenalezena")
    changes = {}
    if body.priority is not None:
        if body.priority not in PRIORITIES + ("",):
            raise HTTPException(status_code=422, detail="Neznámá priorita")
        changes["priority"], a.priority = body.priority or None, body.priority or None
    if body.type is not None:
        if body.type not in TYPES + ("",):
            raise HTTPException(status_code=422, detail="Neznámý typ")
        changes["type"], a.triage_type = body.type or None, body.type or None
    if body.assignee is not None:
        changes["assignee"], a.assignee = body.assignee or None, body.assignee or None
    if body.status is not None:
        if body.status not in ("open", "done", "wontfix"):
            raise HTTPException(status_code=422, detail="Neznámý stav")
        changes["status"], a.status = body.status, body.status
        a.resolved_at = E.now_iso() if body.status != "open" else None
    if body.approved is not None:
        # CLAUDE.md: a note from anyone but an owner is implemented only after an owner approved it
        if c.role != "owner":
            raise HTTPException(status_code=403, detail="Schválit poznámku k implementaci může jen vlastník")
        a.approved_at = E.now_iso() if body.approved else None
        changes["approved"] = body.approved
    a.updated_at = E.now_iso()
    c.audit("inbox.triage", f"note:{a.id}", **changes)
    c.db.commit()
    author = c.db.get(models.User, a.user_id)
    return _note_out(a, author, c.role == "owner")


class SendIn(Lenient):
    title: str = Field(min_length=3, max_length=140)
    text: str = Field(min_length=1, max_length=4000)


@router.post("/inbox/{aid}/send", dependencies=[Depends(verify_csrf)])
def send_to_ai(aid: int, body: SendIn, c: Ctx = Depends(ctx)):
    """“Poslat AI týmu”: the note becomes a GitHub issue labelled ai-ready, which starts the
    @claude workflow (.github/workflows/claude.yml). The person sending edits the text first —
    the issue leaves the app, so nothing identifying or clinical about a runner may stay in it."""
    c.need("inbox.send")
    a = c.db.get(models.Annotation, aid)
    if a is None:
        raise HTTPException(status_code=404, detail="Poznámka nenalezena")
    if a.issue_number:
        raise HTTPException(status_code=409, detail=f"Už je na GitHubu jako #{a.issue_number}")
    author = c.db.get(models.User, a.user_id)
    if not (author and is_owner(author)) and not a.approved_at:
        if c.role != "owner":
            raise HTTPException(status_code=409, detail="Poznámku od uživatele musí nejdřív schválit vlastník")
        a.approved_at = E.now_iso()        # an owner sending it approves it
    labels = ["ai-ready", "from-app"]
    t = a.triage_type or ("bug" if a.kind == "bug" else "feature")
    labels.append({"bug": "bug", "feature": "feature", "copy": "feature", "engine": "engine", "safety": "safety"}[t])
    if t in T.GATED and "feature" not in labels:
        labels.append("feature")
    issue = _gh(lambda: T.gh("POST", "/issues", json={
        "title": body.title.strip(), "body": T.issue_body(a, author.role if author else None, body.text), "labels": labels}))
    a.issue_number, a.issue_url, a.updated_at = issue.get("number"), issue.get("html_url"), E.now_iso()
    T.upsert_issue(c.db, {**issue, "body": f"<!-- doslap-note:{a.id} -->"})
    c.audit("inbox.send", f"note:{a.id}", issue=a.issue_number, labels=labels)
    c.db.commit()
    return {"issueNumber": a.issue_number, "issueUrl": a.issue_url}


# ---------------------------------------------------------------- work queue
@router.get("/work")
def work(c: Ctx = Depends(ctx)):
    c.need("work.read")
    rows = c.db.query(models.WorkItem).order_by(models.WorkItem.updated_at.desc()).limit(300).all()
    by_issue = T.prs_by_issue(rows)
    items = [T.work_out(w, by_issue) for w in rows]
    last = c.db.query(models.TeamAudit).filter(models.TeamAudit.action == "work.sync").order_by(models.TeamAudit.id.desc()).first()
    return {"items": items, "config": T.config(), "lastSync": last.at if last else None}


@router.post("/work/sync", dependencies=[Depends(verify_csrf)])
def work_sync(c: Ctx = Depends(ctx)):
    c.need("work.sync")
    out = _gh(lambda: T.sync(c.db))
    c.audit("work.sync", None, **out)
    c.db.commit()
    return out


@hook_router.post("/api/github/webhook")
async def github_webhook(request: Request, db: DBSession = Depends(get_db)):
    """GitHub → Settings → Webhooks: content type JSON, secret DOSSLAP_GITHUB_WEBHOOK_SECRET,
    events Issues, Pull requests, Check suites, Statuses. Signed requests only."""
    body = await request.body()
    if not T.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Neplatný podpis")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Neplatné JSON") from None
    full = ((payload.get("repository") or {}).get("full_name") or "").lower()
    if full and full != T.repo().lower():
        return {"ok": True, "handled": "other repository"}
    handled = T.handle_event(db, request.headers.get("X-GitHub-Event", ""), payload)
    db.commit()
    return {"ok": True, "handled": handled}


# ---------------------------------------------------------------- review and merge (issue #3)
@router.get("/pr/{number}")
def pr_review(number: int, cso: bool = False, c: Ctx = Depends(ctx)):
    """The review screen: the pull request as GitHub has it right now, with what blocks a merge."""
    c.need("work.read")
    out = _gh(lambda: T.pr_review(number, cso_linked=cso))
    return {**out, "canMerge": T.can(c.role, "pr.merge"), "mergeToken": bool(T.merge_token()),
            "needsPassword": True}           # review 2026-10-30 N1: every account confirms with its password


class MergeIn(Lenient):
    sha: str = Field(min_length=7, max_length=64)       # the head commit the owner reviewed
    confirm: str = Field(max_length=40)                 # "MERGE #<n>"
    password: str = Field(default="", max_length=200)
    cso: bool = False                                   # a /cso report is linked (label security)


def _merge_refused(c: Ctx, number: int, status: int, why: str, action: str = "pr.merge.blocked", **detail) -> HTTPException:
    """Every refusal is audited. Only a wrong confirmation or password ("pr.merge.refused") counts
    toward the lockout; a gate that is not met ("pr.merge.blocked") is not the owner's fault."""
    c.audit(action, f"pr:{number}", why=why[:200], **detail)
    c.db.commit()
    return HTTPException(status_code=status, detail=why)


def _too_many_refusals(c: Ctx) -> bool:
    rows = (c.db.query(models.TeamAudit).filter(models.TeamAudit.action == "pr.merge.refused",
                                                models.TeamAudit.actor_email == (c.user.email or "").lower())
            .order_by(models.TeamAudit.id.desc()).limit(T.MERGE_TRIES).all())
    if len(rows) < T.MERGE_TRIES:
        return False
    oldest = datetime.fromisoformat(rows[-1].at)
    return oldest >= datetime.now(E.LOCAL_TZ) - timedelta(minutes=T.MERGE_WINDOW_MIN)


@router.post("/pr/{number}/merge", dependencies=[Depends(verify_csrf)])
def pr_merge(number: int, body: MergeIn, c: Ctx = Depends(ctx)):
    """Owner merges a pull request from the app (issue #3). Every gate is read from GitHub again
    here; what the screen showed is not trusted. A push after the owner looked changes the head
    commit, which cancels the merge (409), and GitHub itself refuses the merge for a different
    head (the `sha` field) and, as the backstop, by branch protection."""
    c.need("pr.merge")
    token = T.merge_token()
    if not token:
        raise HTTPException(status_code=503, detail="Sloučení z aplikace není zapnuté: nastavte DOSSLAP_GITHUB_MERGE_TOKEN v proměnných Railway.")
    if _too_many_refusals(c):
        raise _merge_refused(c, number, 429, f"Příliš mnoho zamítnutých pokusů, zkuste to za {T.MERGE_WINDOW_MIN} minut.", action="pr.merge.locked")
    if body.confirm.strip() != f"MERGE #{number}":
        raise _merge_refused(c, number, 422, f"Napište přesně: MERGE #{number}", action="pr.merge.refused")
    if not verify_password(body.password or "", c.user.password_hash):
        raise _merge_refused(c, number, 403, "Heslo nesouhlasí.", action="pr.merge.refused")
    pr = _gh(lambda: T.gh("GET", f"/pulls/{number}")) or {}
    live = (pr.get("head") or {}).get("sha") or ""
    if live != body.sha:
        raise _merge_refused(c, number, 409, "PR se mezitím změnil (nový commit). Otevřete kontrolu znovu.", seen=body.sha[:7], live=live[:7])
    ci = _gh(lambda: T.ci_detail(live))
    blockers = T.merge_blockers(pr, ci["state"], cso_linked=body.cso)
    if blockers:
        raise _merge_refused(c, number, 409, " ".join(blockers), head=live[:7])
    try:
        done = T.gh("PUT", f"/pulls/{number}/merge", json={"merge_method": T.MERGE_METHOD, "sha": live,
                                                         "commit_title": f"{pr.get('title')} (#{number})"}, token=token) or {}
    except T.GitHubError as e:
        raise _merge_refused(c, number, 409 if e.status in (403, 405, 409, 422) else 502, str(e), head=live[:7]) from None
    w = c.db.query(models.WorkItem).filter(models.WorkItem.kind == "pr", models.WorkItem.number == number).first()
    if w is not None:
        w.state, w.merged_at, w.merge_sha, w.updated_at = "merged", E.now_iso(), done.get("sha"), E.now_iso()
        c.db.flush()
        T.resolve_notes_for(c.db, w)
    c.audit("pr.merge", f"pr:{number}", head=live[:7], merge=(done.get("sha") or "")[:7], title=(pr.get("title") or "")[:120],
            labels=T._labels(pr), cso=body.cso)
    c.db.commit()
    return {"merged": True, "sha": done.get("sha")}


class RemarkIn(Lenient):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/pr/{number}/comment", dependencies=[Depends(verify_csrf)])
def pr_comment(number: int, body: RemarkIn, c: Ctx = Depends(ctx)):
    """The owner's remark from the review screen: a comment on the pull request, which the AI
    team answers like any review comment."""
    c.need("pr.merge")
    name = c.user.name or c.user.email
    _gh(lambda: T.gh("POST", f"/issues/{number}/comments", json={"body": f"**Owner review** — {name} (Team Console)\n\n{body.text.strip()}"}))
    c.audit("pr.comment", f"pr:{number}", text=body.text.strip()[:300])
    c.db.commit()
    return {"ok": True}


@router.post("/work/{number}/go", dependencies=[Depends(verify_csrf)])
def plan_go(number: int, c: Ctx = Depends(ctx)):
    """An owner's “go” on a plan the AI team posted (label ai-plan): the issue goes back to ai-ready."""
    c.need("pr.merge")
    w = c.db.query(models.WorkItem).filter(models.WorkItem.kind == "issue", models.WorkItem.number == number).first()
    if w is None or "ai-plan" not in (w.labels or []):
        raise HTTPException(status_code=404, detail="Plán čekající na vlastníka nenalezen (zkuste Synchronizovat)")
    name = c.user.name or c.user.email
    _gh(lambda: T.gh("POST", f"/issues/{number}/comments", json={"body": f"go — schváleno vlastníkem {name} (Team Console)"}))
    _gh(lambda: T.gh("POST", f"/issues/{number}/labels", json={"labels": ["ai-ready"]}))
    try:
        T.gh("DELETE", f"/issues/{number}/labels/ai-plan")
    except T.GitHubError as e:
        if e.status != 404:
            raise HTTPException(status_code=502, detail=str(e)) from None
    w.labels = sorted((set(w.labels or []) - {"ai-plan"}) | {"ai-ready"})
    c.audit("plan.go", f"issue:{number}")
    c.db.commit()
    return T.work_out(w, {})


# ---------------------------------------------------------------- clinical approvals
@router.get("/approvals")
def approvals(c: Ctx = Depends(ctx)):
    c.need("approvals.read")
    rows = c.db.query(models.WorkItem).filter(models.WorkItem.kind == "pr").order_by(models.WorkItem.updated_at.desc()).all()
    gated = [w for w in rows if set(w.labels or []) & set(T.GATED)]
    pending = [T.work_out(w, {}) for w in gated if w.state == "open" and w.clinical != "approved"]
    decided = [T.work_out(w, {}) for w in gated if w.clinical_at][:30]
    return {"pending": pending, "decided": decided, "canDecide": T.can(c.role, "approvals.decide"),
            "github": T.config()["github"]}


class DecisionIn(Lenient):
    decision: str
    note: str = Field(default="", max_length=2000)


@router.post("/approvals/{number}", dependencies=[Depends(verify_csrf)])
def decide(number: int, body: DecisionIn, c: Ctx = Depends(ctx)):
    """The clinical guarantor's sign-off: the label clinical-approved lets the clinical-gate
    check pass (.github/workflows/clinical-gate.yml); clinical-changes keeps it red."""
    c.need("approvals.decide")
    if body.decision not in ("approve", "changes"):
        raise HTTPException(status_code=422, detail="Rozhodnutí je approve nebo changes")
    if body.decision == "changes" and not body.note.strip():
        raise HTTPException(status_code=422, detail="Napište, co je potřeba změnit")
    w = c.db.query(models.WorkItem).filter(models.WorkItem.kind == "pr", models.WorkItem.number == number).first()
    if w is None or not (set(w.labels or []) & set(T.GATED)):
        raise HTTPException(status_code=404, detail="PR s klinickou bránou nenalezen (zkuste Synchronizovat)")
    add, drop = ("clinical-approved", "clinical-changes") if body.decision == "approve" else ("clinical-changes", "clinical-approved")
    name = c.user.name or c.user.email
    verdict = "✅ Clinical sign-off" if body.decision == "approve" else "✋ Clinical changes requested"
    comment = f"**{verdict}** — {name} (Team Console)\n\n{body.note.strip() or '—'}"
    _gh(lambda: T.gh("POST", f"/issues/{number}/labels", json={"labels": [add]}))
    try:
        T.gh("DELETE", f"/issues/{number}/labels/{drop}")
    except T.GitHubError as e:
        if e.status != 404:
            raise HTTPException(status_code=502, detail=str(e)) from None
    _gh(lambda: T.gh("POST", f"/issues/{number}/comments", json={"body": comment}))
    w.labels = sorted((set(w.labels or []) - {drop}) | {add})
    w.clinical = "approved" if body.decision == "approve" else "changes"
    w.clinical_by, w.clinical_at, w.clinical_note = c.user.email, E.now_iso(), body.note.strip() or None
    c.audit("approval." + body.decision, f"pr:{number}", note=body.note.strip()[:300], head=w.head_sha)
    c.db.commit()
    return T.work_out(w, {})


# ---------------------------------------------------------------- releases and health
@router.get("/releases")
def releases(c: Ctx = Depends(ctx)):
    c.need("releases.read")
    import os

    from ..main import AUTOSYNC_LAST
    from . import client_errors as CE
    sha = T.running_sha()
    day_ago = time.time() - 86400
    errs = [e for e in CE.RECENT if e["at"] >= day_ago]
    merged = (c.db.query(models.WorkItem).filter(models.WorkItem.kind == "pr", models.WorkItem.state == "merged")
              .order_by(models.WorkItem.merged_at.desc()).limit(15).all())
    return {
        "production": {
            "sha": sha, "environment": os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_ENVIRONMENT"),
            "deploymentId": os.environ.get("RAILWAY_DEPLOYMENT_ID"), "engine": E.ENGINE_VERSION, "bootedAt": T.BOOTED_AT,
            "db": db_location_info().get("persistent"), "url": os.environ.get("DOSSLAP_PROD_URL") or None,
        },
        "clientErrors": {"sinceBoot": CE.COUNT["total"], "last24h": len(errs),
                         "recent": [{**e, "at": datetime.fromtimestamp(e["at"], E.LOCAL_TZ).isoformat()} for e in list(errs)[-8:][::-1]]},
        "autosync": AUTOSYNC_LAST or None,
        "staging": T.staging_health(),
        "deployments": T.railway_deployments(),
        "merged": [T.work_out(w, {}) for w in merged],
    }


# ---------------------------------------------------------------- pilot gates
@router.get("/pilot")
def pilot(c: Ctx = Depends(ctx)):
    c.need("pilot.read")
    data = T.pilot(c.db)
    T.snapshot_pilot(c.db, data)
    c.db.commit()
    hist = c.db.query(models.PilotSnapshot).order_by(models.PilotSnapshot.week.desc()).limit(26).all()
    return {**data, "history": [{"week": h.week, **(h.data_json or {})} for h in hist][::-1]}


# ---------------------------------------------------------------- simulated runners (personas)
@hook_router.post("/api/team/synthetic-notes")
async def synthetic_notes(request: Request, db: DBSession = Depends(get_db)):
    """Staging's simulated runners report here (app/personas/filing.py) with the shared
    DOSSLAP_PERSONA_TOKEN; the notes wait in Inbox for an owner like anyone else's."""
    if not T.persona_token_ok(request.headers.get("X-Persona-Token")):
        raise HTTPException(status_code=401, detail="Neplatný token person")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Neplatné JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Čekám objekt s items")
    out = T.ingest_synthetic(db, body)
    db.commit()
    return out


@router.get("/behaviour-profile")
def behaviour_profile(c: Ctx = Depends(ctx)):
    """Personas stage 3: the anonymous behaviour profile of runners who agreed to it (groups of
    5 and more, no health data) — downloaded here, imported on staging (Persony)."""
    c.need("pilot.read")
    from ..personas import calibration as CAL
    prof = CAL.profile(c.db)
    c.audit("behaviour.export", None, groups={k: v.get("n") for k, v in prof["groups"].items()},
            consenting=prof["consenting"])
    c.db.commit()
    return prof
