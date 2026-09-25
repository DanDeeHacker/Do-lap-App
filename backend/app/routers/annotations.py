"""In-app feedback loop: annotation mode.

A logged-in user switches annotation mode on in the top bar, clicks any part of
the UI and leaves a note pinned to it. Notes live in the app's own database
(Railway in production). Each user sees and edits only their own notes; the
app owner(s) — emails in DOSSLAP_OWNER_EMAILS — see everyone's.

For Claude Code, scripts/feedback_sync.py pulls every note through the
token-protected export (Authorization: Bearer $DOSSLAP_FEEDBACK_TOKEN) into a
local mirror, and marks notes resolved once they are implemented. Without the
token configured the export and resolve endpoints don't exist (404).
"""
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import get_current_user, verify_csrf
from ..metrics import engine as E

router = APIRouter(prefix="/api/annotations", tags=["annotations"])

KINDS = {"bug", "idea", "copy", "other"}
STATUSES = {"open", "done", "wontfix"}
MAX_OPEN_PER_USER = 300


def _owner_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("DOSSLAP_OWNER_EMAILS", "").split(",") if e.strip()}


def is_owner(user: models.User) -> bool:
    return (user.email or "").lower() in _owner_emails()


def _out(a: models.Annotation, author: models.User | None, viewer: models.User | None = None) -> dict:
    return {
        "id": a.id, "route": a.route, "selector": a.selector, "anchorText": a.anchor_text,
        "context": a.context_json or {}, "note": a.note, "kind": a.kind, "status": a.status,
        "resolution": a.resolution, "createdAt": a.created_at, "updatedAt": a.updated_at,
        "resolvedAt": a.resolved_at,
        "author": {"name": author.name if author else None, "role": author.role if author else None,
                   "isOwner": bool(author and is_owner(author))},
        **({"own": a.user_id == viewer.id} if viewer is not None else {}),
    }


def _visible(db: DBSession, user: models.User):
    q = db.query(models.Annotation, models.User).join(models.User, models.Annotation.user_id == models.User.id)
    return q if is_owner(user) else q.filter(models.Annotation.user_id == user.id)


class AnnotationIn(BaseModel):
    route: str = Field(min_length=1, max_length=200)
    selector: str | None = Field(default=None, max_length=1500)
    anchorText: str | None = Field(default=None, max_length=300)
    context: dict = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=4000)
    kind: str = "idea"


class AnnotationPatch(BaseModel):
    note: str | None = Field(default=None, min_length=1, max_length=4000)
    kind: str | None = None
    status: str | None = None


def _check_kind_status(kind: str | None, status: str | None):
    if kind is not None and kind not in KINDS:
        raise HTTPException(status_code=422, detail="Neznámý typ poznámky")
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail="Neznámý stav poznámky")


def _clean_context(ctx: dict) -> dict:
    """Keep only the known, small context fields — this is stored and later read
    by tooling, so nothing arbitrary or large gets in."""
    allowed = {"heading": str, "tag": str, "fx": float, "fy": float, "pageX": float, "pageY": float,
               "vw": int, "vh": int, "device": str, "bundle": str, "engine": str}
    out = {}
    for k, t in allowed.items():
        v = ctx.get(k)
        if v is None:
            continue
        try:
            v = t(v)
        except (TypeError, ValueError):
            continue
        out[k] = v[:200] if isinstance(v, str) else v
    return out


@router.get("")
def list_annotations(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """The viewer's notes (the owner: everyone's), newest first."""
    rows = _visible(db, user).order_by(models.Annotation.id.desc()).limit(1000).all()
    return {"owner": is_owner(user), "items": [_out(a, u, user) for a, u in rows]}


@router.post("", dependencies=[Depends(verify_csrf)])
def create_annotation(body: AnnotationIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    _check_kind_status(body.kind, None)
    if not body.route.startswith("/"):
        raise HTTPException(status_code=422, detail="Neplatná stránka")
    n_open = (db.query(models.Annotation)
              .filter(models.Annotation.user_id == user.id, models.Annotation.status == "open").count())
    if n_open >= MAX_OPEN_PER_USER:
        raise HTTPException(status_code=429, detail="Příliš mnoho otevřených poznámek — nejdřív některé vyřešte.")
    now = E.now_iso()
    a = models.Annotation(user_id=user.id, route=body.route, selector=body.selector,
                          anchor_text=(body.anchorText or "").strip() or None, context_json=_clean_context(body.context),
                          note=body.note.strip(), kind=body.kind, status="open", created_at=now, updated_at=now)
    db.add(a)
    db.commit()
    return _out(a, user, user)


def _editable(db: DBSession, aid: int, user: models.User) -> models.Annotation:
    a = db.query(models.Annotation).filter(models.Annotation.id == aid).first()
    if a is None or (a.user_id != user.id and not is_owner(user)):
        raise HTTPException(status_code=404, detail="Poznámka nenalezena")
    return a


@router.patch("/{aid}", dependencies=[Depends(verify_csrf)])
def update_annotation(aid: int, body: AnnotationPatch, user: models.User = Depends(get_current_user),
                      db: DBSession = Depends(get_db)):
    a = _editable(db, aid, user)
    _check_kind_status(body.kind, body.status)
    if body.note is not None:
        a.note = body.note.strip()
    if body.kind is not None:
        a.kind = body.kind
    if body.status is not None and body.status != a.status:
        a.status = body.status
        a.resolved_at = E.now_iso() if body.status != "open" else None
    a.updated_at = E.now_iso()
    db.commit()
    author = db.query(models.User).filter(models.User.id == a.user_id).first()
    return _out(a, author, user)


@router.delete("/{aid}", dependencies=[Depends(verify_csrf)], status_code=204)
def delete_annotation(aid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    db.delete(_editable(db, aid, user))
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- tooling (token)
def require_feedback_token(authorization: str | None = Header(default=None)) -> None:
    """Bearer token for scripts/feedback_sync.py. Disabled (404) unless
    DOSSLAP_FEEDBACK_TOKEN is set to something reasonably long."""
    expected = os.environ.get("DOSSLAP_FEEDBACK_TOKEN", "")
    if len(expected) < 24:
        raise HTTPException(status_code=404, detail="Not Found")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not got or not hmac.compare_digest(got.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Neplatný token")


@router.get("/export", dependencies=[Depends(require_feedback_token)])
def export_annotations(status: str = "all", since: str | None = None, db: DBSession = Depends(get_db)):
    """Every note (no author e-mails) for the local Claude Code mirror."""
    q = db.query(models.Annotation, models.User).join(models.User, models.Annotation.user_id == models.User.id)
    if status != "all":
        _check_kind_status(None, status)
        q = q.filter(models.Annotation.status == status)
    if since:
        q = q.filter(models.Annotation.updated_at > since)
    return {"items": [_out(a, u) for a, u in q.order_by(models.Annotation.id.asc()).all()]}


class ResolveIn(BaseModel):
    status: str = "done"
    resolution: str = Field(default="", max_length=2000)


@router.post("/{aid}/resolve", dependencies=[Depends(require_feedback_token)])
def resolve_annotation(aid: int, body: ResolveIn, db: DBSession = Depends(get_db)):
    """Set by the sync script once a note is implemented (or deliberately not)."""
    _check_kind_status(None, body.status)
    a = db.query(models.Annotation).filter(models.Annotation.id == aid).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Poznámka nenalezena")
    now = E.now_iso()
    a.status, a.resolution, a.updated_at = body.status, body.resolution.strip() or None, now
    a.resolved_at = now if body.status != "open" else None
    db.commit()
    author = db.query(models.User).filter(models.User.id == a.user_id).first()
    return _out(a, author)
