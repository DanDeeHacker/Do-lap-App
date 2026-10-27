"""Team Console (owner request 2026-10-27): Admin → Tým, Inbox, Práce, Schválení, Vydání, Pilot.
The founders run the AI engineering team (gstack sprints on GitHub) from the app: who is on the
team, which feedback goes to the AI team, what is being built, the clinical sign-off of engine
and safety changes, what production runs, and the pilot's numbers. The logic is in app/team.py;
this module is the HTTP surface and the permission checks. Every write lands in the audit log."""
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.orm import Session as DBSession

from .. import models, team as T
from ..db import db_location_info, get_db
from ..deps import get_current_user, is_owner, owner_emails, verify_csrf
from ..metrics import engine as E
from ..schemas import Lenient

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
        models.User.email.in_([m.email for m in rows] + sorted(owner_emails()))).all()}
    env = [{"email": e, "role": "owner", "active": True, "env": True, "hasAccount": e in accounts} for e in sorted(owner_emails())]
    return {"env": env, "items": [{**T.member_out(m), "hasAccount": m.email in accounts} for m in rows], "roles": list(T.ROLES)}


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
    c.audit("member.add", email, role=body.role)
    c.db.commit()
    T.team_changed()
    return T.member_out(m)


@router.patch("/members/{mid}", dependencies=[Depends(verify_csrf)])
def patch_member(mid: int, body: MemberPatch, c: Ctx = Depends(ctx)):
    c.need("team.manage")
    m = c.db.get(models.TeamMember, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Člen týmu nenalezen")
    if body.role is not None and body.role not in T.ROLES:
        raise HTTPException(status_code=422, detail="Neznámá role")
    if m.email == (c.user.email or "").lower() and (body.active is False or (body.role and body.role != "owner")):
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
            # a name only for owners; the rest of the team sees the reporter's role
            "author": {"role": author.role if author else None, "isOwner": bool(author and is_owner(author)),
                       **({"name": author.name} if viewer_owner and author else {})}}


@router.get("/inbox")
def inbox(status: str = "open", c: Ctx = Depends(ctx)):
    c.need("inbox.read")
    q = c.db.query(models.Annotation, models.User).join(models.User, models.Annotation.user_id == models.User.id)
    if status in ("open", "done", "wontfix"):
        q = q.filter(models.Annotation.status == status)
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
