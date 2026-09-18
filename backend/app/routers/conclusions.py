"""Post-visit conclusion — drafted by the physio right after a booked
session, shared with the runner only once the physio approves it.

Flow: POST /api/bookings/{bid}/conclusion opens (or returns) a draft →
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
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session as DBSession

from .. import llm, models, schemas
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


@router.post("/api/bookings/{bid}/conclusion", dependencies=[Depends(verify_csrf)])
def open_conclusion(bid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Open — or return the already-open — draft conclusion for a booking."""
    bk = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Termín nenalezen")
    if bk.physio_id != user.physio_id or not has_care_assignment(db, user.physio_id, bk.runner_id):
        raise HTTPException(status_code=403, detail="Tento termín nepatří vám nebo jste nepřevzali případ.")
    existing = db.query(models.Conclusion).filter(models.Conclusion.booking_id == bid).first()
    if existing:
        return to_dict(existing)
    c = models.Conclusion(
        booking_id=bid, runner_id=bk.runner_id, physio_id=user.physio_id,
        status="draft", created_at=E.now_iso(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return to_dict(c)


@router.get("/api/conclusions/{cid}")
def get_conclusion(cid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    c = or_404(db.query(models.Conclusion).filter(models.Conclusion.id == cid).first(), "Závěr nenalezen")
    if user.role == "physio" and c.physio_id == user.physio_id and has_care_assignment(db, user.physio_id, c.runner_id):
        return to_dict(c)
    if user.role == "runner" and c.runner_id == user.runner_id and c.status == "approved":
        return to_dict(c)
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
    raw = await file.read()
    transcript = llm.transcribe(raw, filename=file.filename or "session.webm",
                                mime=file.content_type or "application/octet-stream")
    del raw  # data-minimisation: drop the audio bytes immediately
    if not transcript:
        return {"conclusion": to_dict(c), "asr_available": llm.asr_available(),
                "note": "Přepis se nezdařil nebo není nakonfigurován ASR — doplňte přepis ručně."}
    c.transcript = transcript
    c.transcript_source = "asr"
    draft = ai_brief.draft_conclusion(db, c.runner_id, transcript)
    if draft and not (c.summary or "").strip():
        c.summary = draft
    db.commit()
    db.refresh(c)
    return {"conclusion": to_dict(c), "asr_available": True, "llm_draft": bool(draft)}


@router.patch("/api/conclusions/{cid}", dependencies=[Depends(verify_csrf)])
def edit_conclusion(cid: int, body: schemas.ConclusionPatch,
                    user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status != "draft":
        raise HTTPException(status_code=409, detail="Schválený závěr už nelze upravovat.")
    for field in ("transcript", "summary", "finding", "out_region", "out_side"):
        v = getattr(body, field)
        if v is not None:
            setattr(c, field, v)
    if body.transcript is not None:
        c.transcript_source = "manual"
    if body.has_outcome is not None:
        c.has_outcome = body.has_outcome
    for src, dst in (("out_participation", "out_participation"), ("out_volume", "out_volume"),
                     ("out_performance", "out_performance"), ("out_pain", "out_pain")):
        v = getattr(body, src)
        if v is not None:
            if v not in OSTRC_VALUES:
                raise HTTPException(status_code=422, detail=f"Neplatná OSTRC hodnota u {src}")
            setattr(c, dst, v)
    c.out_severity = (c.out_participation or 0) + (c.out_volume or 0) + (c.out_performance or 0) + (c.out_pain or 0)
    db.commit()
    db.refresh(c)
    return to_dict(c)


@router.post("/api/conclusions/{cid}/approve", dependencies=[Depends(verify_csrf)])
def approve_conclusion(cid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Finalise: share with the runner and, if a structured outcome was
    filled, write the authoritative grade-A InjuryReport (a severity-0
    outcome is a physio-confirmed *negative* — a valuable calibration
    datapoint, so it's written too)."""
    c = _owned_conclusion(db, cid, user.physio_id)
    if c.status == "approved":
        return to_dict(c)
    if not (c.summary or "").strip():
        raise HTTPException(status_code=422, detail="Závěr nelze schválit prázdný — doplňte shrnutí.")

    if c.has_outcome:
        for f in ("out_participation", "out_volume", "out_performance", "out_pain"):
            if (getattr(c, f) or 0) not in OSTRC_VALUES:
                raise HTTPException(status_code=422, detail=f"Neplatná OSTRC hodnota u {f}")
        severity = (c.out_participation or 0) + (c.out_volume or 0) + (c.out_performance or 0) + (c.out_pain or 0)
        rep = models.InjuryReport(
            runner_id=c.runner_id, submitted_at=E.now_iso(), source="physio_conclusion",
            status="active" if severity > 0 else "none",
            q_participation=c.out_participation or 0, q_volume=c.out_volume or 0,
            q_performance=c.out_performance or 0, q_pain=c.out_pain or 0, severity=severity,
            body_region=c.out_region, body_side=c.out_side, note=(c.finding or "")[:500],
            physio_id=c.physio_id, confirmed=True,
        )
        db.add(rep)
        db.flush()
        c.out_severity = severity
        c.injury_report_id = rep.id

    c.status = "approved"
    c.approved_at = E.now_iso()
    db.add(models.Message(
        runner_id=c.runner_id, physio_id=c.physio_id, sender="physio",
        body="Sdílel jsem s vámi závěr z dnešní prohlídky — najdete ho u termínu.",
        created_at=E.now_iso(),
    ))
    db.commit()
    E.recompute_assessment(db, c.runner_id)
    db.refresh(c)
    return to_dict(c)
