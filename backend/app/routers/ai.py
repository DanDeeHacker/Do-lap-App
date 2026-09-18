"""Clinician-facing AI brief. require_role("physio") alone is sufficient to
keep this off the runner surface entirely; ensure_runner_read_access still
gates it to patients the physio has actually claimed.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from .. import models, schemas
from ..db import get_db
from ..deps import ensure_runner_read_access, require_role, verify_csrf
from ..metrics.ai_brief import brief, chat_reply

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/brief", dependencies=[Depends(verify_csrf)])
def ai_brief(body: schemas.AIBriefRequest, user: models.User = Depends(require_role("physio")),
             db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, body.runner_id)
    return brief(db, body.runner_id, body.intent)


@router.post("/chat", dependencies=[Depends(verify_csrf)])
def ai_chat(body: schemas.AiChatRequest, user: models.User = Depends(require_role("physio")),
            db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, body.runner_id)
    return chat_reply(db, body.runner_id, body.message, body.history)
