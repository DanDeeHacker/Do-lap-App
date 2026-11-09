"""Post-visit conclusion — drafted by the physio right after a booked
session, shared with the runner only once the physio approves it.

Flow: POST /api/bookings/{bid}/conclusion returns the record (an unsaved skeleton until the
first save, physio brief 2026-11-09 P0.5) → POST .../conclusion/draft stores it →
POST .../audio uploads session audio, which is transcribed by ASR and used
to draft a narrative, then discarded (only the transcript text is kept) →
PATCH edits the draft → POST .../approve finalises it: the runner can now
read it, and if the physio filled the structured OSTRC outcome an
authoritative grade-A InjuryReport is written (the engine's main
calibration lever, see metrics/engine.py's injury()).

Every write is scoped to the physio who owns the booking *and* has claimed
the patient; the runner may only ever read their own, and only after
approval.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session as DBSession

from .. import llm, models, schemas
from .. import regions as REG
from ..db import get_db
from ..deps import get_current_user, has_care_assignment, or_404, require_role, verify_csrf
from ..metrics import ai_brief, engine as E
from ..serializers import to_dict

router = APIRouter(tags=["conclusions"])

OSTRC_VALUES = {0, 8, 17, 25}


def _owned_conclusion(db: DBSession, cid: int, physio_id: str) -> models.Conclusion:
    c = or_404(db.query(models.Conclusion).filter(models.Conclusion.id == cid).first(), "Závěr nenalezen")
    if c.physio_id != physio_id or not has_care_assignment(db, physio_id, c.runner_id):
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto závěru")
    return c


def _booking_owned(db: DBSession, bid: int, physio_id: str) -> models.Booking:
    bk = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Termín nenalezen")
    if bk.physio_id != physio_id or not has_care_assignment(db, physio_id, bk.runner_id):
        raise HTTPException(status_code=403, detail="Tento termín nepatří vám nebo jste nepřevzali případ.")
    return bk


def _out(c: models.Conclusion, bk: models.Booking | None) -> dict:
    d = to_dict(c)
    d["slot_at"] = bk.slot_at if bk else None
    d["severity_complete"] = c.outcome_kind == "injury" and all(
        getattr(c, f) in OSTRC_VALUES for f in ("out_participation", "out_volume", "out_performance", "out_pain"))
    return d


def runner_view(c: models.Conclusion) -> dict:
    """What a client ever receives: the summary written for them, never the clinical finding, the
    transcript or the OSTRC answers (physio brief 2026-11-09 P0.5 / D6)."""
    return {"id": c.id, "booking_id": c.booking_id, "physio_id": c.physio_id, "summary": c.summary,
            "shared_at": c.shared_at, "approved_at": c.approved_at, "status": c.status}


@router.post("/api/bookings/{bid}/conclusion", dependencies=[Depends(verify_csrf)])
def open_conclusion(bid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """The booking's record, or an empty one that is NOT stored: physio brief 2026-11-09 P0.5 — merely
    opening the sheet used to create a draft and flip the visit to "rozepsaný závěr"."""
    bk = _booking_owned(db, bid, user.physio_id)
    existing = db.query(models.Conclusion).filter(models.Conclusion.booking_id == bid).first()
    if existing:
        return _out(existing, bk)
    return {"id": None, "booking_id": bid, "runner_id": bk.runner_id, "physio_id": user.physio_id, "status": "new",
            "transcript": None, "summary": None, "finding": None, "outcome_kind": None, "has_outcome": False,
            "out_participation": None, "out_volume": None, "out_performance": None, "out_pain": None,
            "out_region": None, "out_side": None, "slot_at": bk.slot_at, "severity_complete": False}


def _visit_started(bk: models.Booking) -> bool:
    """Compare instants, not strings: slots are stored in UTC, the engine clock in local time."""
    if not bk.slot_at:
        return True
    try:
        at = datetime.fromisoformat(bk.slot_at)
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at <= datetime.fromisoformat(E.now_iso())


def _apply(c: models.Conclusion, body: schemas.ConclusionPatch) -> None:
    given = body.model_fields_set
    for field in ("transcript", "summary", "finding", "out_region", "out_side"):
        if field in given:
            setattr(c, field, getattr(body, field))
    if body.transcript is not None:
        c.transcript_source = "manual"
    if "outcome_kind" in given:
        kind = body.outcome_kind or None
        if kind not in (None, "injury", "no_injury"):
            raise HTTPException(status_code=422, detail="Neplatný typ výsledku")
        c.outcome_kind, c.has_outcome = kind, kind is not None
        if kind != "injury":
            c.out_participation = c.out_volume = c.out_performance = c.out_pain = None
    for f in ("out_participation", "out_volume", "out_performance", "out_pain"):
        if f in given:
            v = getattr(body, f)
            if v is not None and v not in OSTRC_VALUES:
                raise HTTPException(status_code=422, detail=f"Neplatná OSTRC hodnota u {f}")
            setattr(c, f, v)
    if c.out_region is not None and c.out_region and c.out_region not in REG.LABEL:
        raise HTTPException(status_code=422, detail="Oblast vyberte ze seznamu")
    vals = [getattr(c, f) for f in ("out_participation", "out_volume", "out_performance", "out_pain")]
    c.out_severity = sum(vals) if c.outcome_kind == "injury" and all(v is not None for v in vals) else None


@router.post("/api/bookings/{bid}/conclusion/draft", dependencies=[Depends(verify_csrf)])
def save_new_conclusion(bid: int, body: schemas.ConclusionPatch,
                        user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """The first save stores the draft (physio brief 2026-11-09 P0.5)."""
    bk = _booking_owned(db, bid, user.physio_id)
    c = db.query(models.Conclusion).filter(models.Conclusion.booking_id == bid).first()
    if c is None:
        c = models.Conclusion(booking_id=bid, runner_id=bk.runner_id, physio_id=user.physio_id, status="draft",
                              created_at=E.now_iso(), has_outcome=False)
        c.out_participation = c.out_volume = c.out_performance = c.out_pain = c.out_severity = None
        db.add(c)
    elif c.status != "draft":
        raise HTTPException(status_code=409, detail="Schválený závěr už nelze upravovat.")
    _apply(c, body)
    db.commit()
    db.refresh(c)
    return _out(c, bk)


@router.get("/api/conclusions/{cid}")
def get_conclusion(cid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    c = or_404(db.query(models.Conclusion).filter(models.Conclusion.id == cid).first(), "Závěr nenalezen")
    if user.role == "physio" and c.physio_id == user.physio_id and has_care_assignment(db, user.physio_id, c.runner_id):
        return _out(c, db.get(models.Booking, c.booking_id))
    if user.role == "runner" and c.runner_id == user.runner_id and c.status == "approved" and c.shared_at:
        return runner_view(c)
    raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto závěru")


@router.post("/api/conclusions/{cid}/audio", dependencies=[Depends(verify_csrf)])
async def upload_audio(cid: int, file: UploadFile = File(...),
                       user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Transcribe session audio and draft a narrative from it. The audio is
    held only in memory for the transcription call and never persisted; only
    the resulting transcript is stored. If no ASR endpoint is configured the
    physio is asked to type the transcript instead (asr_available=False)."""
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status != "draft":
        raise HTTPException(status_code=409, detail="Závěr je už schválený a nelze měnit.")
    # physio brief 2026-11-09 P0.1: not configured = no upload, no call, an instant honest answer
    if not llm.asr_available():
        return {"conclusion": to_dict(c), "asr_available": False,
                "note": "Přepis zatím není zapnutý. Závěr napište ručně."}
    raw = await file.read()
    try:
        transcript = llm.transcribe(raw, filename=file.filename or "session.webm",
                                    mime=file.content_type or "application/octet-stream")
    finally:
        del raw  # data-minimisation: the audio never outlives the call, success or failure
    if not transcript:
        return {"conclusion": to_dict(c), "asr_available": True,
                "note": "Přepis se nezdařil. Zkuste to znovu, nebo závěr napište ručně."}
    c.transcript = transcript
    c.transcript_source = "asr"
    draft = ai_brief.draft_conclusion(db, c.runner_id, transcript)
    if draft and not (c.summary or "").strip():
        c.summary, c.ai_draft = draft, True   # fills only an empty field; never approved automatically
    db.commit()
    db.refresh(c)
    return {"conclusion": to_dict(c), "asr_available": True, "llm_draft": bool(draft)}


@router.patch("/api/conclusions/{cid}", dependencies=[Depends(verify_csrf)])
def edit_conclusion(cid: int, body: schemas.ConclusionPatch,
                    user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status != "draft":
        raise HTTPException(status_code=409, detail="Schválený závěr už nelze upravovat.")
    _apply(c, body)
    db.commit()
    db.refresh(c)
    return _out(c, db.get(models.Booking, c.booking_id))


def _share(db: DBSession, c: models.Conclusion, bk: models.Booking | None) -> None:
    when = (bk.slot_at if bk and bk.slot_at else c.approved_at or "")[:10]
    d = f"{int(when[8:10])}. {int(when[5:7])}." if len(when) == 10 else ""
    c.shared_at = E.now_iso()
    # gender-neutral, and the visit's own date (not "z dnešní prohlídky" for a September visit)
    db.add(models.Message(runner_id=c.runner_id, physio_id=c.physio_id, sender="physio",
                          body=f"Shrnutí z návštěvy {d} je připravené. Najdete ho v záložce Péče.", created_at=E.now_iso()))


@router.post("/api/conclusions/{cid}/approve", dependencies=[Depends(verify_csrf)])
def approve_conclusion(cid: int, body: schemas.ConclusionApprove | None = None,
                       user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Approve the record (physio brief 2026-11-09 P0.5). Not before the visit has started; the injury
    is dated by the visit, not by the approval; the OSTRC outcome counts only when the physio chose it
    (an injury with all four answers, region and side, or an explicit "bez zranění"); sending the
    summary to the client is a separate choice (D5) and the clinical finding is never sent (D6)."""
    body = body or schemas.ConclusionApprove()
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status == "approved":
        return _out(c, db.get(models.Booking, c.booking_id))
    bk = db.get(models.Booking, c.booking_id)
    if bk and not _visit_started(bk):
        raise HTTPException(status_code=409, detail="Závěr lze schválit až po začátku návštěvy.")
    if not ((c.summary or "").strip() or (c.finding or "").strip()):
        raise HTTPException(status_code=422, detail="Záznam nelze schválit prázdný — doplňte nález nebo shrnutí.")
    if body.send_summary and not (c.summary or "").strip():
        raise HTTPException(status_code=422, detail="Pro odeslání klientovi doplňte shrnutí.")
    visit_day = (bk.slot_at if bk and bk.slot_at else E.now_iso())[:10]
    if c.outcome_kind == "injury":
        vals = [getattr(c, f) for f in ("out_participation", "out_volume", "out_performance", "out_pain")]
        if any(v not in OSTRC_VALUES for v in vals):
            raise HTTPException(status_code=422, detail="Vyplňte všechny čtyři otázky strukturovaného hodnocení.")
        if not c.out_region or c.out_region not in REG.LABEL or c.out_side not in ("L", "P", "both"):
            raise HTTPException(status_code=422, detail="U zranění vyberte oblast a stranu.")
        severity = sum(vals)
    elif c.outcome_kind == "no_injury":
        severity = 0
    else:
        severity = None
    if severity is not None:
        rep = models.InjuryReport(
            runner_id=c.runner_id, submitted_at=visit_day, source="physio_conclusion",
            status="active" if severity > 0 else "none",
            q_participation=c.out_participation or 0, q_volume=c.out_volume or 0,
            q_performance=c.out_performance or 0, q_pain=c.out_pain or 0, severity=severity,
            body_region=REG.label(c.out_region) if c.out_region else None, body_side=c.out_side,
            note=(c.finding or "")[:500], physio_id=c.physio_id, confirmed=True,
        )
        db.add(rep)
        db.flush()
        E.record_injury(db, c.runner_id, rep)   # plan B3: a confirmed injury becomes the injury history
        c.out_severity = severity
        c.injury_report_id = rep.id

    c.status = "approved"
    c.approved_at = E.now_iso()
    if bk and bk.status == "confirmed":
        bk.status = "completed"                 # an approved record means the visit took place
    if body.send_summary:
        _share(db, c, bk)
    db.commit()
    E.recompute_assessment(db, c.runner_id)
    db.refresh(c)
    return _out(c, bk)


@router.post("/api/conclusions/{cid}/share", dependencies=[Depends(verify_csrf)])
def share_conclusion(cid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Send the summary of an approved record to the client later."""
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status != "approved":
        raise HTTPException(status_code=409, detail="Nejdřív záznam schvalte.")
    if not (c.summary or "").strip():
        raise HTTPException(status_code=422, detail="Záznam nemá shrnutí pro klienta.")
    if not c.shared_at:
        _share(db, c, db.get(models.Booking, c.booking_id))
        db.commit()
        db.refresh(c)
    return _out(c, db.get(models.Booking, c.booking_id))
