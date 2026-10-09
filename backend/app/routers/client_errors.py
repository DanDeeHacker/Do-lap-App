"""Crash reports from the app in the browser. A render error in a tab used to leave
the runner with a broken page and nothing in the server logs (Trénink 2026-10-09);
the frontend now catches it, shows a fallback and posts the error here, and it lands
in the deploy log as one `client-error` line. Nothing is stored in the database.

Only technical details are accepted (message, stack, page path, app area, build), all
size-capped; the user is identified by account id only. Same-origin requests only,
and a small per-IP budget keeps a crash loop from flooding the log."""
import logging
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import models, security
from ..db import get_db
from ..deps import get_current_user_optional

router = APIRouter(prefix="/api/client-errors", tags=["client-errors"])
log = logging.getLogger("dosslap.client")

PER_IP_PER_MIN = 20
_seen: dict[str, deque] = {}


class ClientError(BaseModel):
    message: str = Field("", max_length=500)
    stack: str = Field("", max_length=4000)
    path: str = Field("", max_length=300)
    where: str = Field("", max_length=60)       # tab | route | window | promise
    build: str = Field("", max_length=60)
    ua: str = Field("", max_length=300)


def _allow(ip: str) -> bool:
    now = time.monotonic()
    q = _seen.setdefault(ip, deque())
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= PER_IP_PER_MIN:
        return False
    q.append(now)
    if len(_seen) > 5000:                       # forget idle addresses
        for k in [k for k, v in _seen.items() if not v][:2500]:
            _seen.pop(k, None)
    return True


@router.post("", status_code=204)
def report(body: ClientError, request: Request, db: DBSession = Depends(get_db),
           user: models.User | None = Depends(get_current_user_optional)) -> Response:
    if not security.same_origin(request):
        raise HTTPException(status_code=403, detail="Neplatný požadavek (cross-origin)")
    ip = (request.client.host if request.client else "") or "?"
    if _allow(ip):
        who = f"user={user.id} runner={user.runner_id}" if user else "user=-"
        stack = " | ".join(line.strip() for line in body.stack.splitlines()[:8])
        log.warning("client-error where=%s path=%s %s build=%s msg=%r stack=%r ua=%r",
                    body.where or "-", body.path or "-", who, body.build or "-", body.message, stack, body.ua)
    return Response(status_code=204)
