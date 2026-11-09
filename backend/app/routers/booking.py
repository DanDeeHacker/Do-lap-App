"""Consent-driven physio booking flow.

The runner first opts into the service (consent) — only then do they appear
to physios (triage/candidate gate lives in triage.py). The runner browses
partner clinics + physios (with bio/experience) and their open slots,
filtered by the runner's preferred days/parts-of-day, requests one slot, and
the physio must confirm before it lands in both calendars. Either the physio
(decline) or the runner (cancel, or fully decline the physio — revoking data
access) can back out. A confirmed booking within 24 h surfaces a day-before
reminder to both sides, with prep info the physio/clinic manages.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models, schemas
from ..db import get_db
from ..deps import ensure_runner_self, get_current_user, or_404, physio_verified, require_role, require_verified_physio, verify_csrf
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(tags=["booking"])

KIND_PRICE = {"gait_analysis": 1490, "video_call": 690, "follow_up": 1190, "assessment": 1190}


# ---------------------------------------------------------------- helpers
def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _aware(iso: str) -> datetime:
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def overlaps(a_start: datetime, a_min: int, b_start: datetime, b_min: int) -> bool:
    """physio brief 2026-11-09 P0.6: two visits clash when their time ranges intersect."""
    a_end = a_start + timedelta(minutes=a_min or 45)
    b_end = b_start + timedelta(minutes=b_min or 45)
    return a_start < b_end and b_start < a_end


def _hm(d: datetime) -> str:
    loc = d.astimezone(E.LOCAL_TZ)
    return f"{loc.day}. {loc.month}. {loc.strftime('%H:%M')}"


def booking_conflict(db: DBSession, pid: str, start: datetime, mins: int, *, slots: bool = False,
                     statuses=("requested", "confirmed"), skip_booking: int | None = None,
                     skip_slot: int | None = None) -> str | None:
    """The first clash with this physio's active visits (and open slots when `slots`), as a Czech sentence."""
    for b in db.query(models.Booking).filter(models.Booking.physio_id == pid, models.Booking.status.in_(statuses)).all():
        if b.id == skip_booking or not b.slot_at:
            continue
        try:
            at = _aware(b.slot_at)
        except ValueError:
            continue
        if overlaps(start, mins, at, b.duration_min or 45):
            r = db.get(models.Runner, b.runner_id)
            return f"Koliduje s návštěvou {r.name if r else 'klienta'} v {_hm(at)}."
    if slots:
        for sl in db.query(models.PhysioSlot).filter(models.PhysioSlot.physio_id == pid, models.PhysioSlot.status == "open").all():
            if sl.id == skip_slot:
                continue
            try:
                at = _aware(sl.slot_at)
            except ValueError:
                continue
            if overlaps(start, mins, at, sl.duration_min or 45):
                return f"Překrývá se s volným termínem v {_hm(at)}."
    return None


def _daypart(hour: int) -> str:
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def _physio_public(p: models.Physio, clinic: models.Clinic | None) -> dict:
    return {
        "id": p.id, "name": p.name, "credential": p.credential, "rating": p.rating,
        "bio": p.bio, "years_exp": p.years_exp, "specialties": p.specialties or [],
        "price_czk": p.price_czk, "clinic": to_dict(clinic) if clinic else None,
    }


def due_reminders(db: DBSession, runner_id: str = None, physio_id: str = None) -> list[dict]:
    """Confirmed bookings whose slot is within the next 24 h — the in-app
    equivalent of the day-before notification. Visible to both sides; the
    physio/clinic owns `prep_info`."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=24)
    q = db.query(models.Booking).filter(models.Booking.status == "confirmed")
    if runner_id:
        q = q.filter(models.Booking.runner_id == runner_id)
    if physio_id:
        q = q.filter(models.Booking.physio_id == physio_id)
    out = []
    for b in q.all():
        if not b.slot_at:
            continue
        try:
            when = _dt(b.slot_at)
        except ValueError:
            continue
        if now <= when <= horizon:
            physio = db.query(models.Physio).filter(models.Physio.id == b.physio_id).first()
            runner = db.query(models.Runner).filter(models.Runner.id == b.runner_id).first()
            out.append({
                "booking_id": b.id, "slot_at": b.slot_at, "kind": b.kind,
                "physio_name": physio.name if physio else None,
                "runner_name": runner.name if runner else None,
                "prep_info": b.prep_info,
            })
    out.sort(key=lambda r: r["slot_at"])
    return out


# ---------------------------------------------------------------- runner: consent
@router.post("/api/runners/{rid}/physio-interest", dependencies=[Depends(verify_csrf)])
def set_interest(rid: str, body: schemas.PhysioInterestRequest,
                 user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    r.physio_interest = bool(body.interested)
    r.physio_interest_at = E.now_iso() if body.interested else None
    if not body.interested:
        # withdrawing interest releases any pending (not yet confirmed) requests
        for b in db.query(models.Booking).filter(
            models.Booking.runner_id == rid, models.Booking.status == "requested"
        ).all():
            b.status = "cancelled"
            if b.slot_id:
                slot = db.query(models.PhysioSlot).filter(models.PhysioSlot.id == b.slot_id).first()
                if slot and slot.status == "held":
                    slot.status = "open"
    db.commit()
    return {"physio_interest": r.physio_interest, "physio_interest_at": r.physio_interest_at}


# ---------------------------------------------------------------- runner: browse + request
@router.get("/api/booking/options")
def booking_options(dow: str = "", daypart: str = "",
                    user: models.User = Depends(require_role("runner")), db: DBSession = Depends(get_db)):
    """Partner clinics + physios with their open future slots, filtered by the
    runner's preferred weekdays (`dow`, 0=Mon comma list) and parts of day
    (`daypart`, morning|afternoon|evening comma list). Requires consent."""
    r = db.query(models.Runner).filter(models.Runner.id == user.runner_id).first()
    if not r or not r.physio_interest:
        raise HTTPException(status_code=409, detail="Nejprve potvrďte zájem o fyzioterapii.")
    want_dow = {int(x) for x in dow.split(",") if x.strip().isdigit()}
    want_part = {x.strip() for x in daypart.split(",") if x.strip()}
    now_iso = E.now_iso()
    slots = (
        db.query(models.PhysioSlot)
        .filter(models.PhysioSlot.status == "open", models.PhysioSlot.slot_at > now_iso)
        .order_by(models.PhysioSlot.slot_at.asc()).all()
    )
    by_physio: dict[str, list[dict]] = {}
    for s in slots:
        try:
            when = _dt(s.slot_at)
        except ValueError:
            continue
        if want_dow and when.weekday() not in want_dow:
            continue
        if want_part and _daypart(when.hour) not in want_part:
            continue
        d = to_dict(s)
        d["weekday"] = when.weekday()
        d["daypart"] = _daypart(when.hour)
        by_physio.setdefault(s.physio_id, []).append(d)
    out = []
    for pid, plist in by_physio.items():
        p = db.query(models.Physio).filter(models.Physio.id == pid).first()
        if not p or not p.verified_at:           # review 2026-10-30 F1: only verified physios take bookings
            continue
        clinic = db.query(models.Clinic).filter(models.Clinic.id == p.clinic_id).first()
        item = _physio_public(p, clinic)
        item["slots"] = plist[:12]
        out.append(item)
    out.sort(key=lambda x: -(x["rating"] or 0))
    return out


@router.post("/api/booking/request", dependencies=[Depends(verify_csrf)])
def request_slot(body: schemas.SlotBookRequest,
                 user: models.User = Depends(require_role("runner")), db: DBSession = Depends(get_db)):
    rid = user.runner_id
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if not r or not r.physio_interest:
        raise HTTPException(status_code=409, detail="Nejprve potvrďte zájem o fyzioterapii.")
    slot = or_404(db.query(models.PhysioSlot).filter(models.PhysioSlot.id == body.slot_id).first(), "Termín nenalezen")
    if slot.status != "open" or not physio_verified(db, slot.physio_id):
        raise HTTPException(status_code=409, detail="Tento termín už není volný.")
    # physio brief 2026-11-09 P0.6: never a past slot, never on top of another visit
    if _aware(slot.slot_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Tento termín už proběhl.")
    clash = booking_conflict(db, slot.physio_id, _aware(slot.slot_at), slot.duration_min or 45)
    if clash:
        raise HTTPException(status_code=409, detail="Tento termín už není volný.")
    slot.status = "held"
    b = models.Booking(
        runner_id=rid, physio_id=slot.physio_id, slot_id=slot.id, slot_at=slot.slot_at,
        duration_min=slot.duration_min or 45, kind=body.kind, status="requested",
        price_czk=KIND_PRICE.get(body.kind, 1190),
        payer="employer" if r.employer_id else "self",
        requested_at=E.now_iso(), created_at=E.now_iso(),
    )
    db.add(b)
    db.add(models.Message(
        runner_id=rid, physio_id=slot.physio_id, sender="system", audience="physio",
        body="Pacient požádal o termín — čeká na vaše potvrzení.", created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.post("/api/runners/{rid}/bookings/{bid}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_booking(rid: str, bid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    b = or_404(
        db.query(models.Booking).filter(models.Booking.id == bid, models.Booking.runner_id == rid).first(),
        "Rezervace nenalezena",
    )
    if b.status in ("cancelled", "declined"):
        return to_dict(b)
    b.status = "cancelled"
    if b.slot_id:
        slot = db.query(models.PhysioSlot).filter(models.PhysioSlot.id == b.slot_id).first()
        if slot and slot.status in ("held", "booked"):
            slot.status = "open"
    db.add(models.Message(
        runner_id=rid, physio_id=b.physio_id, sender="system", audience="physio",
        body="Pacient zrušil rezervaci termínu.", created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.post("/api/runners/{rid}/physios/{pid}/decline", dependencies=[Depends(verify_csrf)])
def decline_physio(rid: str, pid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Runner rejects a physio outright: revokes the physio's access to their
    data (care assignment) and cancels every open booking with them; the
    triage case returns to the unclaimed queue."""
    ensure_runner_self(user, rid)
    revoked = 0
    for ca in db.query(models.CareAssignment).filter(
        models.CareAssignment.runner_id == rid, models.CareAssignment.physio_id == pid,
        models.CareAssignment.status == "active",
    ).all():
        ca.status = "revoked"
        revoked += 1
    for b in db.query(models.Booking).filter(
        models.Booking.runner_id == rid, models.Booking.physio_id == pid,
        models.Booking.status.in_(("requested", "confirmed")),
    ).all():
        b.status = "cancelled"
        if b.slot_id:
            slot = db.query(models.PhysioSlot).filter(models.PhysioSlot.id == b.slot_id).first()
            if slot and slot.status in ("held", "booked"):
                slot.status = "open"
    tri = db.query(models.Triage).filter(
        models.Triage.runner_id == rid, models.Triage.claimed_by == pid
    ).first()
    if tri:
        tri.claimed_by = None
        tri.status = "open"
    db.add(models.Message(
        runner_id=rid, physio_id=pid, sender="system", audience="physio",
        body="Pacient odvolal spolupráci s tímto fyzioterapeutem.", created_at=E.now_iso(),
    ))
    db.commit()
    return {"ok": True, "revoked": revoked}


# ---------------------------------------------------------------- physio: slots + confirm/decline
@router.get("/api/physios/{pid}/slots")
def list_slots(pid: str, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if user.physio_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    rows = (
        db.query(models.PhysioSlot)
        .filter(models.PhysioSlot.physio_id == pid, models.PhysioSlot.slot_at > E.now_iso())
        .order_by(models.PhysioSlot.slot_at.asc()).all()
    )
    return to_dicts(rows)


@router.post("/api/physios/{pid}/slots", dependencies=[Depends(verify_csrf)])
def add_slot(pid: str, body: schemas.AddSlotRequest,
             user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if user.physio_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    try:
        start = _aware(body.slot_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatný formát termínu.")
    mins = body.duration_min or 45
    if not 10 <= mins <= 240:
        raise HTTPException(status_code=422, detail="Délka termínu musí být 10 až 240 minut.")
    # physio brief 2026-11-09 P0.6: a past slot used to return success and vanish; duplicates and slots
    # on top of a visit were accepted
    if start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Termín je v minulosti.")
    clash = booking_conflict(db, pid, start, mins, slots=True)
    if clash:
        raise HTTPException(status_code=409, detail=clash)
    s = models.PhysioSlot(
        physio_id=pid, slot_at=body.slot_at, duration_min=body.duration_min or 45,
        status="open", created_at=E.now_iso(),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return to_dict(s)


@router.delete("/api/physios/slots/{sid}", dependencies=[Depends(verify_csrf)])
def remove_slot(sid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    s = or_404(db.query(models.PhysioSlot).filter(models.PhysioSlot.id == sid).first(), "Termín nenalezen")
    if s.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    if s.status == "booked":
        raise HTTPException(status_code=409, detail="Obsazený termín nelze smazat — nejdřív zrušte rezervaci.")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/api/bookings/{bid}/confirm", dependencies=[Depends(verify_csrf)])
def confirm_booking(bid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    b = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Rezervace nenalezena")
    if b.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    if b.status != "requested":
        raise HTTPException(status_code=409, detail="Tuto rezervaci nelze potvrdit.")
    if b.slot_at:
        clash = booking_conflict(db, b.physio_id, _aware(b.slot_at), b.duration_min or 45,
                                 statuses=("confirmed",), skip_booking=b.id)
        if clash:
            raise HTTPException(status_code=409, detail=clash)
    b.status = "confirmed"
    if b.slot_id:
        slot = db.query(models.PhysioSlot).filter(models.PhysioSlot.id == b.slot_id).first()
        if slot:
            slot.status = "booked"
    existing = (
        db.query(models.CareAssignment)
        .filter(models.CareAssignment.physio_id == user.physio_id, models.CareAssignment.runner_id == b.runner_id)
        .first()
    )
    if not existing:
        db.add(models.CareAssignment(
            physio_id=user.physio_id, runner_id=b.runner_id, status="active", created_at=E.now_iso(),
        ))
    elif existing.status != "active":
        existing.status = "active"
    db.add(models.Message(
        runner_id=b.runner_id, physio_id=user.physio_id, sender="physio",
        body="Váš termín je potvrzený. Uvidíme se — den předem vám přijde připomenutí.", created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.post("/api/bookings/{bid}/decline", dependencies=[Depends(verify_csrf)])
def decline_booking(bid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    b = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Rezervace nenalezena")
    if b.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    if b.status != "requested":
        raise HTTPException(status_code=409, detail="Tuto rezervaci nelze odmítnout.")
    b.status = "declined"
    if b.slot_id:
        slot = db.query(models.PhysioSlot).filter(models.PhysioSlot.id == b.slot_id).first()
        if slot and slot.status == "held":
            slot.status = "open"
    db.add(models.Message(
        runner_id=b.runner_id, physio_id=user.physio_id, sender="physio",
        body="Bohužel tento termín nemohu potvrdit — vyberte prosím jiný.", created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.patch("/api/bookings/{bid}/prep", dependencies=[Depends(verify_csrf)])
def set_prep(bid: int, body: schemas.PrepInfoRequest,
             user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    b = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Rezervace nenalezena")
    if b.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    b.prep_info = body.prep_info
    db.commit()
    db.refresh(b)
    return to_dict(b)


# ---- physio brief 2026-11-09 P0.6: the physio cancels, moves, completes or marks a no-show ---------------
def _physio_booking(db: DBSession, bid: int, user: models.User) -> models.Booking:
    b = or_404(db.query(models.Booking).filter(models.Booking.id == bid).first(), "Rezervace nenalezena")
    if b.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    return b


def _audit(db: DBSession, b: models.Booking, what: str) -> None:
    from ..main import _record_access
    _record_access(db, b.runner_id, b.physio_id, "POST", what)


def _free_slot(db: DBSession, b: models.Booking) -> None:
    if b.slot_id:
        slot = db.get(models.PhysioSlot, b.slot_id)
        if slot and slot.status in ("held", "booked") and _aware(slot.slot_at) > datetime.now(timezone.utc):
            slot.status = "open"


@router.post("/api/bookings/{bid}/cancel", dependencies=[Depends(verify_csrf)])
def physio_cancel(bid: int, body: schemas.BookingCancelRequest, user: models.User = Depends(require_verified_physio),
                  db: DBSession = Depends(get_db)):
    b = _physio_booking(db, bid, user)
    if b.status not in ("requested", "confirmed"):
        raise HTTPException(status_code=409, detail="Tuto návštěvu nelze zrušit.")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Uveďte důvod zrušení, klient ho uvidí.")
    b.status, b.cancel_reason = "cancelled", reason
    _free_slot(db, b)
    db.add(models.Message(runner_id=b.runner_id, physio_id=b.physio_id, sender="physio", created_at=E.now_iso(),
                          body=f"Návštěvu {_hm(_aware(b.slot_at))} musím zrušit: {reason}"))
    _audit(db, b, "zrušení návštěvy")
    db.commit()
    return to_dict(b)


@router.post("/api/bookings/{bid}/reschedule", dependencies=[Depends(verify_csrf)])
def physio_reschedule(bid: int, body: schemas.BookingRescheduleRequest,
                      user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    b = _physio_booking(db, bid, user)
    if b.status not in ("requested", "confirmed"):
        raise HTTPException(status_code=409, detail="Tuto návštěvu nelze přesunout.")
    new_slot = None
    if body.slot_id:
        new_slot = db.get(models.PhysioSlot, body.slot_id)
        if not new_slot or new_slot.physio_id != b.physio_id or new_slot.status != "open":
            raise HTTPException(status_code=409, detail="Tento termín není volný.")
        start, mins = _aware(new_slot.slot_at), new_slot.duration_min or 45
    elif body.starts_at:
        try:
            start = _aware(body.starts_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="Neplatný formát termínu.")
        mins = b.duration_min or 45
    else:
        raise HTTPException(status_code=422, detail="Vyberte nový termín.")
    if start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Termín je v minulosti.")
    clash = booking_conflict(db, b.physio_id, start, mins, skip_booking=b.id)
    if clash:
        raise HTTPException(status_code=409, detail=clash)
    old = b.slot_at
    _free_slot(db, b)
    if new_slot:
        new_slot.status = "booked" if b.status == "confirmed" else "held"
        b.slot_id = new_slot.id
    else:
        b.slot_id = None
    b.slot_at, b.duration_min, b.reminded = start.isoformat(), mins, False
    db.add(models.Message(runner_id=b.runner_id, physio_id=b.physio_id, sender="physio", created_at=E.now_iso(),
                          body=f"Návštěvu přesouvám z {_hm(_aware(old))} na {_hm(start)}."))
    _audit(db, b, "přesun návštěvy")
    db.commit()
    return to_dict(b)


def _past_visit(db: DBSession, bid: int, user: models.User) -> models.Booking:
    b = _physio_booking(db, bid, user)
    if b.status not in ("confirmed", "completed", "no_show"):
        raise HTTPException(status_code=409, detail="Tuto návštěvu nelze takto označit.")
    if b.slot_at and _aware(b.slot_at) > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Návštěva ještě nezačala.")
    return b


@router.post("/api/bookings/{bid}/complete", dependencies=[Depends(verify_csrf)])
def physio_complete(bid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    b = _past_visit(db, bid, user)
    b.status = "completed"
    _audit(db, b, "návštěva proběhla")
    db.commit()
    return to_dict(b)


@router.post("/api/bookings/{bid}/no-show", dependencies=[Depends(verify_csrf)])
def physio_no_show(bid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    b = _past_visit(db, bid, user)
    b.status = "no_show"
    _audit(db, b, "nedostavil(a) se")
    db.commit()
    return to_dict(b)
