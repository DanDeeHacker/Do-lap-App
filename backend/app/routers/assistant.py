"""Physio AI Assistant endpoints (app/assistant/). The runner's chat, history,
feedback and the evidence card sheet; plus admin endpoints for the knowledge base
(full-text upload, card review) for accounts listed in DOSSLAP_ADMIN_EMAILS."""
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from .. import llm, models
from .. import translate as T
from ..assistant import knowledge as K
from ..assistant import service as S
from ..db import SessionLocal, get_db
from ..deps import ensure_runner_self, get_current_user, request_lang, verify_csrf
from ..metrics import engine as E
from .annotations import require_feedback_token

router = APIRouter(tags=["assistant"])
MAX_PDF_BYTES = 25 * 1024 * 1024


class AskRequest(BaseModel):
    question: str
    context: dict | None = None
    thread_id: str | None = None


class FeedbackRequest(BaseModel):
    value: int
    note: str | None = None


class CardReviewRequest(BaseModel):
    status: str
    note: str | None = None


def _runner(db, rid):
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if r is None:
        raise HTTPException(404, "Běžec nenalezen")
    return r


def is_admin(user) -> bool:
    allowed = {e.strip().lower() for e in os.environ.get("DOSSLAP_ADMIN_EMAILS", "").split(",") if e.strip()}
    return bool(user and (user.email or "").lower() in allowed)


def _admin(user):
    if not is_admin(user):
        raise HTTPException(403, "Jen pro správce znalostní báze")


@router.get("/api/runners/{rid}/assistant")
def assistant_status(rid: str, request: Request, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    acc = S.access(db, r, user)
    out = {"name": S.NAME, "access": acc, "limit": S.daily_limit(), "used": S._used_today(db, rid),
           "visibleDays": S.VISIBLE_DAYS, "disclaimer": S.DISCLAIMER, "llm": llm.assistant_available(), "admin": is_admin(user)}
    if acc["enabled"]:
        a = E.get_or_refresh_assessment(db, rid)
        out["suggestions"] = S.suggestions(a)
        out["history"] = S.history(db, rid)
        if request_lang(request, user) == "en":
            out["history"] = [T.message_en(db, m) for m in out["history"]]
            out["suggestions"] = [T.SUGGESTIONS_EN.get(q, q) for q in out["suggestions"]]
    if request_lang(request, user) == "en":
        out["disclaimer"] = T.DISCLAIMER_EN
    return out


@router.post("/api/runners/{rid}/assistant/ask", dependencies=[Depends(verify_csrf)])
def assistant_ask(rid: str, body: AskRequest, request: Request, user: models.User = Depends(get_current_user),
                  db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    acc = S.access(db, r, user)
    if not acc["enabled"]:
        raise HTTPException(403, {"reason": acc["reason"]})
    if not (body.question or "").strip():
        raise HTTPException(400, "Prázdná otázka")
    if request_lang(request, user) == "en":
        q_cs = T.to_cs(db, body.question)
        return T.message_en(db, S.ask(db, r, q_cs, body.context, body.thread_id, user, shown_question=body.question))
    return S.ask(db, r, body.question, body.context, body.thread_id, user)


@router.get("/api/runners/{rid}/assistant/summary")
def assistant_summary(rid: str, request: Request, tab: str = "today", user: models.User = Depends(get_current_user),
                      db: DBSession = Depends(get_db)):
    """The summary the assistant opens with on a tab (cached per day until the data change)."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    acc = S.access(db, r, user)
    if not acc["enabled"]:
        raise HTTPException(403, {"reason": acc["reason"]})
    out = S.tab_summary(db, r, tab, user)
    if request_lang(request, user) == "en":
        en = T.to_en(db, out.get("text"))
        out = {**out, "text": en or out.get("text"), "lang": "en" if en else "cs", "sources": T.sources_en(out.get("sources")),
               "title": T.SUMMARY_TITLES_EN.get(out.get("title"), out.get("title"))}
    return out


@router.delete("/api/runners/{rid}/assistant/history", dependencies=[Depends(verify_csrf)])
def assistant_forget(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    return {"deleted": S.delete_history(db, rid)}


@router.post("/api/runners/{rid}/assistant/messages/{mid}/feedback", dependencies=[Depends(verify_csrf)])
def assistant_feedback(rid: str, mid: int, body: FeedbackRequest, user: models.User = Depends(get_current_user),
                       db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    row = db.query(models.AssistantMessage).filter(models.AssistantMessage.id == mid,
                                                   models.AssistantMessage.runner_id == rid).first()
    if row is None or row.role != "assistant":
        raise HTTPException(404, "Odpověď nenalezena")
    row.feedback = 1 if body.value > 0 else -1
    row.feedback_note = (body.note or "")[:1000] or None
    db.commit()
    return {"ok": True}


@router.get("/api/assistant/cards/{card_id}")
def assistant_card(card_id: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    c = K.card_by_id().get(card_id)
    if c is None:
        raise HTTPException(404, "Karta nenalezena")
    st = K.card_status(db).get(card_id, "draft")
    return {**c, "status": st, "refs": K.card_sources(c)}


# ------------------------------------------------------------------ admin: knowledge base
@router.get("/api/assistant/admin/knowledge")
def admin_knowledge(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    _admin(user)
    docs = db.query(models.KnowledgeDoc).order_by(models.KnowledgeDoc.id.desc()).all()
    st = K.card_status(db)
    counts = {}
    for kind, n in db.query(models.KnowledgeChunk.source_kind, models.KnowledgeChunk.id).all():
        counts[kind] = counts.get(kind, 0) + 1
    embedded = db.query(models.KnowledgeChunk).filter(models.KnowledgeChunk.embed_model == llm.EMBED_MODEL).count()
    return {"docs": [{"id": d.id, "cite": d.cite, "doi": d.doi, "category": d.category, "chunks": d.n_chunks,
                      "pages": d.pages, "summary": d.summary_id, "uploadedAt": d.uploaded_at} for d in docs],
            "cards": [{"id": c["id"], "cat": c["cat"], "title": c["title"], "status": st.get(c["id"], "draft")} for c in K.cards()],
            "chunks": counts, "embedded": embedded, "embedModel": llm.EMBED_MODEL if llm.embed_available() else None}


def _llm_check(model: str | None, embed_model: str | None = None) -> dict:
    for m in (model, embed_model):
        if m is not None and not re.fullmatch(r"[\w./:-]{1,100}", m):
            raise HTTPException(400, "Neplatný název modelu")
    return {"chat": llm.probe("chat", model), "embed": llm.probe("embed", embed_model),
            "host": llm.ASSISTANT_BASE_URL, "embedHost": llm.EMBED_BASE_URL, "mode": S.mode()}


@router.get("/api/assistant/admin/llm-check")
def admin_llm_check(model: str | None = None, embed_model: str | None = None,
                    user: models.User = Depends(get_current_user)):
    """Is the assistant's model reachable, how fast, and why not (status + short body)."""
    _admin(user)
    return _llm_check(model, embed_model)


@router.get("/api/assistant/ops/llm-check", dependencies=[Depends(require_feedback_token)])
def ops_llm_check(model: str | None = None, embed_model: str | None = None):
    """The same check for the operator token (no user data involved)."""
    return _llm_check(model, embed_model)


@router.get("/api/assistant/ops/models", dependencies=[Depends(require_feedback_token)])
def ops_models(q: str = ""):
    """The provider's model ids (to pick a vision model); operator token."""
    return {"models": llm.list_models(q[:40]), "vision": llm.VISION_MODELS, "error": llm.LAST_ERROR.get("models")}


@router.post("/api/assistant/ops/shoe-check", dependencies=[Depends(require_feedback_token)])
def ops_shoe_check(body: dict):
    """v0.12.0 — the shoe recogniser on a test photo (operator token; nothing stored).
    `models` (optional list) tries those vision models instead of the configured ones."""
    from .. import shoes as S
    img = S.check_image((body or {}).get("image"))
    if not img:
        raise HTTPException(422, "Neplatný obrázek")
    models = [m for m in (body or {}).get("models") or [] if isinstance(m, str) and re.fullmatch(r"[\w./:-]{1,100}", m)]
    saved, saved_t = list(llm.VISION_MODELS), llm.VISION_TIMEOUT
    if models:
        llm.VISION_MODELS[:] = models[:4]
    try:
        llm.VISION_TIMEOUT = min(120.0, float((body or {}).get("timeout") or saved_t))
        out = S.recognise(img)
    finally:
        llm.VISION_MODELS[:] = saved
        llm.VISION_TIMEOUT = saved_t
    out["lastError"] = llm.LAST_ERROR.get("vision") if not out.get("ok") else None
    return out


@router.get("/api/assistant/admin/retrieval-eval")
def admin_retrieval_eval(embed_model: str | None = None, user: models.User = Depends(get_current_user),
                         db: DBSession = Depends(get_db)):
    """Gate 1 on the live knowledge base: keyword vs a candidate embedding model."""
    _admin(user)
    return _retrieval_eval(db, embed_model)


@router.get("/api/assistant/ops/retrieval-eval", dependencies=[Depends(require_feedback_token)])
def ops_retrieval_eval(embed_model: str | None = None, weights: str | None = None, detail: bool = False,
                       db: DBSession = Depends(get_db)):
    return _retrieval_eval(db, embed_model, weights, detail)


def _retrieval_eval(db, embed_model, weights=None, detail=False):
    from ..assistant import evaluate
    if embed_model is not None and not re.fullmatch(r"[\w./:-]{1,100}", embed_model):
        raise HTTPException(400, "Neplatný název modelu")
    try:
        ws = tuple(float(x) for x in weights.split(",")[:6]) if weights else (1.0, 3.0, 5.0)
    except ValueError:
        raise HTTPException(400, "Neplatné váhy")
    return evaluate.retrieval(db, embed_model, ws, detail)


@router.get("/api/assistant/ops/sample", dependencies=[Depends(require_feedback_token)])
def ops_sample(q: str, model: str | None = None, db: DBSession = Depends(get_db)):
    """One dry-run answer on the tutorial runner (nothing stored): compares models
    on the real prompt, facts, sources and validator."""
    if model is not None and not re.fullmatch(r"[\w./:-]{1,100}", model):
        raise HTTPException(400, "Neplatný název modelu")
    from ..tutorial_demo import ensure
    r = _runner(db, ensure(db))
    return S.ask(db, r, q[:800], dry_run=True, model_override=model)


def _embed_bg():
    db = SessionLocal()
    try:
        while K.embed_pending(db):
            pass
    finally:
        db.close()


@router.post("/api/assistant/admin/docs", dependencies=[Depends(verify_csrf)])
async def admin_upload(background: BackgroundTasks, file: UploadFile = File(...), doi: str | None = Form(None),
                       cite: str | None = Form(None), category: str | None = Form(None),
                       user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    _admin(user)
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF je větší než 25 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Soubor není PDF")
    try:
        out = K.ingest_pdf(db, data, file.filename or "clanek.pdf", {"doi": doi, "cite": cite, "category": category},
                           user=user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    background.add_task(_embed_bg)
    return out


@router.delete("/api/assistant/admin/docs/{doc_id}", dependencies=[Depends(verify_csrf)])
def admin_delete_doc(doc_id: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    _admin(user)
    if not K.delete_doc(db, doc_id):
        raise HTTPException(404, "Článek nenalezen")
    return {"ok": True}


@router.put("/api/assistant/admin/cards/{card_id}", dependencies=[Depends(verify_csrf)])
def admin_review_card(card_id: str, body: CardReviewRequest, user: models.User = Depends(get_current_user),
                      db: DBSession = Depends(get_db)):
    _admin(user)
    if card_id not in K.card_by_id() or body.status not in ("draft", "approved", "rejected"):
        raise HTTPException(400, "Neplatná karta nebo stav")
    row = db.query(models.CardReview).filter(models.CardReview.card_id == card_id).first()
    if row is None:
        row = models.CardReview(card_id=card_id)
        db.add(row)
    row.status, row.note, row.reviewer = body.status, body.note, user.email
    row.reviewed_at = E.now_iso()
    db.commit()
    return {"id": card_id, "status": row.status}
