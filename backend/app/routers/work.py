"""A physio's working day (physio brief 2026-11-09, Phase 2). Every handler that touches client data writes
its own record_events row (app/audit.py marks these routes SELF)."""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from .. import models
from .. import records as R
from .. import work as W
from ..db import get_db
from ..deps import (ensure_runner_read_access, ensure_runner_self, get_current_user, has_care_assignment,
                    require_role, require_verified_physio, verify_csrf)
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(tags=["physio-work"])


class Open(BaseModel):
    model_config = {"extra": "ignore"}


def _me(db: DBSession, user: models.User) -> models.Physio:
    p = db.get(models.Physio, user.physio_id)
    if p is None:
        raise HTTPException(status_code=403, detail="Účet fyzioterapeuta nenalezen")
    return p


def _client(db: DBSession, p: models.Physio, rid: str) -> None:
    if not has_care_assignment(db, p.id, rid):
        raise HTTPException(status_code=403, detail="Klienta nejdřív převezměte z fronty nebo potvrďte jeho termín.")


def _need(db: DBSession, p: models.Physio, what: str) -> None:
    if not W.can(db, p.id, what):
        raise HTTPException(status_code=403, detail="Na tuto akci nemáte v praxi oprávnění.")


# =============================================================================================== W1 clinic
@router.get("/api/physios/me/clinic")
def clinic(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    c = W.ensure_clinic(db, p)
    members = db.query(models.ClinicMember).filter_by(clinic_id=c.id).all()
    sub = db.query(models.Subscription).filter_by(clinic_id=c.id).first()
    role = W.role_of(db, p.id)
    out = {"id": c.id, "name": c.name, "is_solo": bool(c.is_solo), "role": role,
           "members": [{"id": m.id, "physio_id": m.physio_id, "name": (db.get(models.Physio, m.physio_id).name
                                                                      if db.get(models.Physio, m.physio_id) else m.physio_id),
                        "role": m.role, "active": bool(m.active)} for m in members],
           "subscription": None}
    if sub is not None and role in W.PERMS["billing"]:
        active_seats = sum(1 for m in members if m.active and m.role != "reception")
        out["subscription"] = {"status": sub.status, "seats": active_seats, "trial_ends_at": sub.trial_ends_at,
                               "price_czk_per_seat": sub.price_czk_per_seat, "paid_until": sub.paid_until,
                               "monthly_czk": active_seats * (sub.price_czk_per_seat or 0)}
    db.commit()
    return out


class MemberIn(Open):
    email: str
    role: str = "physio"


@router.post("/api/physios/me/clinic/members", dependencies=[Depends(verify_csrf)])
def add_member(body: MemberIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """An existing physio account joins the clinic (owner or admin)."""
    p = _me(db, user)
    _need(db, p, "members")
    if body.role not in W.ROLES or body.role == "owner":
        raise HTTPException(status_code=422, detail="Role: admin, fyzioterapeut nebo recepce.")
    u = db.query(models.User).filter(models.User.email == body.email.strip().lower(), models.User.role == "physio").first()
    if u is None or not u.physio_id:
        raise HTTPException(status_code=404, detail="Fyzioterapeut s tímto e-mailem nemá účet v Došlapu.")
    c = W.ensure_clinic(db, p)
    other = db.get(models.Physio, u.physio_id)
    for m in db.query(models.ClinicMember).filter_by(physio_id=other.id).all():
        m.active = False
    db.add(models.ClinicMember(clinic_id=c.id, physio_id=other.id, role=body.role, active=True, created_at=E.now_iso()))
    other.clinic_id = c.id
    c.is_solo = False
    R.physio_event(db, p, "update", "practice", c.id, detail={"member_added": other.id, "role": body.role})
    db.commit()
    return {"ok": True}


class RoleIn(Open):
    role: str
    active: bool | None = None


@router.patch("/api/clinic-members/{mid}", dependencies=[Depends(verify_csrf)])
def edit_member(mid: int, body: RoleIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _need(db, p, "members")
    m = db.get(models.ClinicMember, mid)
    if m is None or m.clinic_id != p.clinic_id:
        raise HTTPException(status_code=404, detail="Člen nenalezen")
    if body.role not in W.ROLES:
        raise HTTPException(status_code=422, detail="Neznámá role")
    if m.role == "owner" and body.role != "owner" and not db.query(models.ClinicMember).filter(
            models.ClinicMember.clinic_id == m.clinic_id, models.ClinicMember.role == "owner",
            models.ClinicMember.id != m.id).first():
        raise HTTPException(status_code=409, detail="Praxe musí mít vlastníka.")
    m.role = body.role
    if body.active is not None:
        m.active = body.active
    R.physio_event(db, p, "update", "practice", m.clinic_id, detail={"member": m.physio_id, "role": body.role})
    db.commit()
    return {"ok": True}


class TransferIn(Open):
    to_physio_id: str


@router.post("/api/physios/me/clients/{rid}/transfer", dependencies=[Depends(verify_csrf)])
def transfer(rid: str, body: TransferIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """W1.5: hand a client to a colleague in the clinic; the client is told, the record stays with the clinic."""
    p = _me(db, user)
    _client(db, p, rid)
    to = db.get(models.Physio, body.to_physio_id)
    member = db.query(models.ClinicMember).filter_by(clinic_id=p.clinic_id, physio_id=body.to_physio_id, active=True).first()
    if to is None or member is None or member.role == "reception":
        raise HTTPException(status_code=422, detail="Klienta lze předat jen fyzioterapeutovi z vaší praxe.")
    for ca in db.query(models.CareAssignment).filter_by(physio_id=p.id, runner_id=rid, status="active").all():
        ca.status = "transferred"
    ex = db.query(models.CareAssignment).filter_by(physio_id=to.id, runner_id=rid).first()
    if ex is None:
        db.add(models.CareAssignment(physio_id=to.id, runner_id=rid, status="active", created_at=E.now_iso()))
    else:
        ex.status = "active"
    for t in db.query(models.Triage).filter_by(runner_id=rid, claimed_by=p.id).all():
        t.claimed_by = to.id
    for ep in db.query(models.CareEpisode).filter_by(physio_id=p.id, runner_id=rid, status="open").all():
        ep.physio_id = to.id
    db.add(models.Message(runner_id=rid, physio_id=to.id, sender="system", created_at=E.now_iso(),
                          body=f"Vaši péči převzal(a) {to.name} ze stejné praxe. Záznamy z návštěv zůstávají v praxi. "
                               "Pokud s tím nesouhlasíte, můžete sdílení dat odvolat v záložce Péče."))
    R.physio_event(db, p, "handover", "runner", rid, runner_id=rid, detail={"to": to.id})
    db.commit()
    return {"ok": True}


class PayerIn(Open):
    payer: str


@router.patch("/api/bookings/{bid}/payer", dependencies=[Depends(verify_csrf)])
def set_payer(bid: int, body: PayerIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """W1.6: client | employer | insurer | other — visible and changeable, never set silently."""
    p = _me(db, user)
    b = db.get(models.Booking, bid)
    if b is None or b.physio_id != p.id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    if body.payer not in ("client", "employer", "insurer", "other"):
        raise HTTPException(status_code=422, detail="Plátce: klient, zaměstnavatel, pojišťovna nebo jiný.")
    b.payer = body.payer
    R.physio_event(db, p, "update", "booking", bid, runner_id=b.runner_id, detail={"payer": body.payer})
    db.commit()
    return to_dict(b)


# =============================================================================================== W2 invites
INVITE_DAYS = 14


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InviteIn(Open):
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""


@router.post("/api/physios/me/invites", dependencies=[Depends(verify_csrf)])
def create_invite(body: InviteIn, request: Request, user: models.User = Depends(require_verified_physio),
                  db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _need(db, p, "clinical")
    token = secrets.token_urlsafe(24)
    inv = models.ClientInvite(token_hash=_hash(token), clinic_id=p.clinic_id, physio_id=p.id, name=body.name.strip() or None,
                              email=body.email.strip() or None, phone=body.phone.strip() or None,
                              message=body.message.strip() or None, status="open", created_at=E.now_iso(),
                              expires_at=(datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)).isoformat())
    db.add(inv)
    R.physio_event(db, p, "create", "invite", None, detail={"has_email": bool(body.email)})
    db.commit()
    link = f"{str(request.base_url).rstrip('/')}/pozvani/{token}"
    return {"id": inv.id, "link": link, "token": token, "expires_at": inv.expires_at}


@router.get("/api/physios/me/invites")
def list_invites(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    rows = db.query(models.ClientInvite).filter_by(physio_id=user.physio_id).order_by(models.ClientInvite.id.desc()).all()
    now = datetime.now(timezone.utc).isoformat()
    return {"items": [{"id": i.id, "name": i.name, "email": i.email, "created_at": i.created_at, "expires_at": i.expires_at,
                       "status": "expired" if i.status == "open" and i.expires_at < now else i.status} for i in rows]}


@router.delete("/api/physios/me/invites/{iid}", dependencies=[Depends(verify_csrf)])
def revoke_invite(iid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    inv = db.get(models.ClientInvite, iid)
    if inv is None or inv.physio_id != user.physio_id:
        raise HTTPException(status_code=404, detail="Pozvánka nenalezena")
    inv.status = "revoked"
    db.commit()
    return {"ok": True}


def _open_invite(db: DBSession, token: str) -> models.ClientInvite:
    inv = db.query(models.ClientInvite).filter_by(token_hash=_hash(token)).first()
    if inv is None or inv.status != "open" or inv.expires_at < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=410, detail="Pozvánka už neplatí. Požádejte fyzioterapeuta o novou.")
    return inv


@router.get("/api/invites/{token}")
def invite_info(token: str, db: DBSession = Depends(get_db)):
    """Public: only who invites you."""
    inv = _open_invite(db, token)
    p = db.get(models.Physio, inv.physio_id)
    c = db.get(models.Clinic, p.clinic_id) if p and p.clinic_id else None
    return {"physio": p.name if p else None, "clinic": c.name if c else None, "message": inv.message}


@router.post("/api/invites/{token}/accept", dependencies=[Depends(verify_csrf)])
def accept_invite(token: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Signed in and consenting: the care relationship starts directly, without the queue (W2.4)."""
    if user.role != "runner" or not user.runner_id:
        raise HTTPException(status_code=403, detail="Pozvánku přijímá účet běžce.")
    inv = _open_invite(db, token)
    rid = user.runner_id
    revoked = db.query(models.CareAssignment).filter_by(physio_id=inv.physio_id, runner_id=rid).first()
    if revoked is None:
        db.add(models.CareAssignment(physio_id=inv.physio_id, runner_id=rid, status="active", created_at=E.now_iso()))
    else:
        revoked.status = "active"          # accepting the invite is the new consent (R13.5)
    r = db.get(models.Runner, rid)
    r.physio_interest, r.physio_interest_at = True, E.now_iso()
    inv.status, inv.accepted_runner_id = "accepted", rid
    R.event(db, actor_type="runner", actor_id=rid, actor_name=user.name, action="consent", resource_type="runner",
            runner_id=rid, detail={"invite": inv.id, "physio": inv.physio_id})
    db.add(models.Message(runner_id=rid, physio_id=inv.physio_id, sender="system", audience="both", created_at=E.now_iso(),
                          body="Pozvánka přijata. Fyzioterapeut teď vidí vaše běhy, zátěž, spánek a HRV, deník a hlášené bolesti."))
    W.NOTIFY.send(db, "invite_accepted", "Klient přijal pozvánku", physio_id=inv.physio_id, runner_id=rid)
    db.commit()
    return {"ok": True, "physio_id": inv.physio_id}


class NoAppIn(Open):
    first_name: str
    last_name: str
    birth_date: str | None = None
    sex_at_birth: str | None = None
    phone: str | None = None
    email: str | None = None


@router.post("/api/physios/me/clients/no-app", dependencies=[Depends(verify_csrf)])
def add_client_without_app(body: NoAppIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """W2.7: a client without the app — a patient card and the documentation, no runner data."""
    p = _me(db, user)
    _need(db, p, "clinical")
    if not body.first_name.strip() or not body.last_name.strip():
        raise HTTPException(status_code=422, detail="Vyplňte jméno a příjmení.")
    rid = f"cli-{uuid.uuid4().hex[:10]}"
    db.add(models.Runner(id=rid, name=f"{body.first_name.strip()} {body.last_name.strip()}", onboarding_json={"no_app": True}))
    db.flush()
    db.add(models.CareAssignment(physio_id=p.id, runner_id=rid, status="active", created_at=E.now_iso()))
    c = W.ensure_clinic(db, p)
    card = models.PatientRecord(id=R.new_record_id(), clinic_id=c.id, runner_id=rid, first_name=body.first_name.strip(),
                                last_name=body.last_name.strip(), birth_date=body.birth_date, sex_at_birth=body.sex_at_birth,
                                phone=body.phone, email=body.email, created_at=E.now_iso(), updated_at=E.now_iso())
    db.add(card)
    R.physio_event(db, p, "create", "patient_card", card.id, runner_id=rid, detail={"no_app": True})
    db.commit()
    return {"runner_id": rid, "card_id": card.id}


# =============================================================================================== W3 Dnes
def _visit_out(db: DBSession, b: models.Booking) -> dict:
    r = db.get(models.Runner, b.runner_id)
    c = db.query(models.Conclusion).filter_by(booking_id=b.id).first()
    sv = db.get(models.Service, b.service_id) if b.service_id else None
    return {"id": b.id, "runner_id": b.runner_id, "name": r.name if r else b.runner_id, "slot_at": b.slot_at,
            "duration_min": b.duration_min, "kind": b.kind, "service": sv.name_cs if sv else None, "status": b.status,
            "prep": bool(b.prep_info), "reason": b.reason, "record": c.status if c else None, "payer": b.payer}


@router.get("/api/physios/me/today")
def today(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Who do I see, who needs me, what is unfinished."""
    from .records import unsigned_for
    p = _me(db, user)
    W.refresh_alerts(db, p.id)
    from .booking import send_due_reminders
    send_due_reminders(db)
    W.unsigned_reminders(db, p.id)
    t = E.today_date()
    day0 = datetime.combine(t, datetime.min.time(), E.LOCAL_TZ).astimezone(timezone.utc).isoformat()
    day1 = datetime.combine(t + timedelta(days=1), datetime.min.time(), E.LOCAL_TZ).astimezone(timezone.utc).isoformat()
    visits = [b for b in db.query(models.Booking).filter(models.Booking.physio_id == p.id,
                                                         models.Booking.status.in_(("confirmed", "completed", "no_show"))).all()
              if b.slot_at and day0 <= W._aware(b.slot_at).isoformat() < day1]
    now = E.now_iso()
    alerts = (db.query(models.PhysioAlert).filter(models.PhysioAlert.physio_id == p.id,
                                                  models.PhysioAlert.status.in_(("active", "snoozed"))).all())
    alerts = [a for a in alerts if a.status == "active" or (a.snoozed_until or "") <= now]
    sev = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (sev.get(a.severity, 3), a.created_at or ""))
    clients = W._clients(db, p.id)
    unread = (db.query(models.Message).filter(models.Message.runner_id.in_(clients), models.Message.sender == "runner",
                                              models.Message.read_at_physio.is_(None)).all()) if clients else []
    requests = db.query(models.Booking).filter_by(physio_id=p.id, status="requested").all()
    new_cases = (db.query(models.Triage).filter(models.Triage.claimed_by.is_(None), models.Triage.status != "closed").count())
    names = {rid: (db.get(models.Runner, rid).name if db.get(models.Runner, rid) else rid)
             for rid in {a.runner_id for a in alerts if a.runner_id} | {m.runner_id for m in unread}}
    R.physio_event(db, p, "read", "runner", None, detail={"screen": "today"})
    db.commit()
    return {"visits": sorted([_visit_out(db, b) for b in visits], key=lambda x: x["slot_at"]),
            "alerts": [{"id": a.id, "runner_id": a.runner_id, "name": names.get(a.runner_id), "rule": a.rule,
                        "title": W.ALERT_CS.get(a.rule, a.rule), "severity": a.severity, "payload": a.payload_json,
                        "created_at": a.created_at} for a in alerts],
            "unread": [{"runner_id": m.runner_id, "name": names.get(m.runner_id), "at": m.created_at,
                        "preview": (m.body or "")[:120]} for m in sorted(unread, key=lambda m: m.created_at, reverse=True)],
            "unsigned": unsigned_for(db, p.id),
            "requests": [_visit_out(db, b) for b in requests],
            "new_cases": new_cases}


class AlertIn(Open):
    action: str
    hours: int = 24


@router.patch("/api/alerts/{aid}", dependencies=[Depends(verify_csrf)])
def alert_action(aid: int, body: AlertIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    a = db.get(models.PhysioAlert, aid)
    if a is None or a.physio_id != user.physio_id:
        raise HTTPException(status_code=404, detail="Upozornění nenalezeno")
    if body.action == "snooze":
        a.status, a.snoozed_until = "snoozed", (datetime.fromisoformat(E.now_iso()) + timedelta(hours=body.hours)).isoformat()
    elif body.action == "resolve":
        a.status, a.resolved_at = "resolved", E.now_iso()
    else:
        raise HTTPException(status_code=422, detail="Akce: odložit nebo vyřešeno.")
    db.commit()
    return {"ok": True}


# =============================================================================================== W4 capacity
class CapacityIn(Open):
    accepting_new_clients: bool | None = None
    max_new_per_week: int | None = None
    response_time_text: str | None = None
    cancellation_policy: str | None = None
    notify_settings: dict | None = None
    quick_replies: list | None = None
    dark_mode: bool | None = None
    photo_url: str | None = None


@router.patch("/api/physios/me/settings", dependencies=[Depends(verify_csrf)])
def settings(body: CapacityIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """W4 capacity, W13 response time and quick replies, W14 cancellation policy, W15 notification settings."""
    p = _me(db, user)
    if body.max_new_per_week is not None and not 0 <= body.max_new_per_week <= 50:
        raise HTTPException(status_code=422, detail="Nových klientů za týden: 0 až 50.")
    if body.photo_url and not body.photo_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="Fotka musí být odkaz https://")
    for k in body.model_fields_set:
        setattr(p, k, getattr(body, k))
    db.commit()
    return {k: getattr(p, k) for k in ("accepting_new_clients", "max_new_per_week", "response_time_text",
                                       "cancellation_policy", "notify_settings", "quick_replies", "dark_mode", "photo_url")}


def capacity_full(db: DBSession, p: models.Physio) -> str | None:
    """W4.2: a full physio gets no new matches; the reason is shown to them."""
    if p.accepting_new_clients is False:
        return "Nové klienty teď nepřijímáte (Praxe → kapacita)."
    if p.max_new_per_week:
        since = (datetime.fromisoformat(E.now_iso()) - timedelta(days=7)).isoformat()
        n = db.query(models.CareAssignment).filter(models.CareAssignment.physio_id == p.id,
                                                   models.CareAssignment.created_at >= since).count()
        if n >= p.max_new_per_week:
            return f"Tento týden už máte {n} nových klientů z {p.max_new_per_week}."
    return None


# =============================================================================================== W5 calendar
class RuleIn(Open):
    weekday: int
    start_local: str
    end_local: str
    slot_minutes: int = 45
    valid_from: str | None = None
    valid_until: str | None = None


class RulesIn(Open):
    rules: list[RuleIn]


def _hm(s: str) -> bool:
    try:
        h, m = s.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except ValueError:
        return False


@router.put("/api/physios/me/availability", dependencies=[Depends(verify_csrf)])
def put_availability(body: RulesIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Pracovní doba: the week's rules replace the old ones."""
    p = _me(db, user)
    for r in body.rules:
        if not 0 <= r.weekday <= 6 or not _hm(r.start_local) or not _hm(r.end_local) or r.start_local >= r.end_local:
            raise HTTPException(status_code=422, detail="Zkontrolujte dny a časy pracovní doby.")
        if not 10 <= r.slot_minutes <= 240:
            raise HTTPException(status_code=422, detail="Délka termínu musí být 10 až 240 minut.")
    db.query(models.AvailabilityRule).filter_by(physio_id=p.id).delete()
    for r in body.rules:
        db.add(models.AvailabilityRule(physio_id=p.id, clinic_id=p.clinic_id, active=True, **r.model_dump()))
    db.commit()
    return {"rules": to_dicts(db.query(models.AvailabilityRule).filter_by(physio_id=p.id).all())}


@router.get("/api/physios/me/availability")
def get_availability(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    t = E.today_date()
    return {"rules": to_dicts(db.query(models.AvailabilityRule).filter_by(physio_id=user.physio_id).all()),
            "preview": W.free_times(db, user.physio_id, t, t + timedelta(days=13)),
            "time_off": to_dicts(db.query(models.TimeOff).filter_by(physio_id=user.physio_id).all())}


class TimeOffIn(Open):
    starts_at: str
    ends_at: str
    reason: str = ""
    all_day: bool = False


@router.post("/api/physios/me/time-off", dependencies=[Depends(verify_csrf)])
def add_time_off(body: TimeOffIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    try:
        s, e = W._aware(body.starts_at), W._aware(body.ends_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatný čas.")
    if e <= s:
        raise HTTPException(status_code=422, detail="Konec musí být po začátku.")
    x = models.TimeOff(physio_id=user.physio_id, starts_at=s.isoformat(), ends_at=e.isoformat(), reason=body.reason or None,
                       all_day=body.all_day)
    db.add(x)
    db.commit()
    return to_dict(x)


@router.delete("/api/physios/me/time-off/{tid}", dependencies=[Depends(verify_csrf)])
def del_time_off(tid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    x = db.get(models.TimeOff, tid)
    if x is None or x.physio_id != user.physio_id:
        raise HTTPException(status_code=404, detail="Nenalezeno")
    db.delete(x)
    db.commit()
    return {"ok": True}


class ServiceIn(Open):
    name_cs: str
    duration_minutes: int = 45
    price_czk: int | None = None
    buffer_minutes: int = 0
    code: str | None = None
    payment_mode: str = "none"
    deposit_czk: int | None = None
    active: bool = True


@router.get("/api/physios/me/services")
def services(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    return {"items": to_dicts(db.query(models.Service).filter_by(physio_id=user.physio_id)
                              .order_by(models.Service.sort_order, models.Service.id).all())}


@router.post("/api/physios/me/services", dependencies=[Depends(verify_csrf)])
def add_service(body: ServiceIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    if not body.name_cs.strip() or not 10 <= body.duration_minutes <= 240:
        raise HTTPException(status_code=422, detail="Služba potřebuje název a délku 10 až 240 minut.")
    if body.price_czk is not None and not 0 <= body.price_czk <= 20000:
        raise HTTPException(status_code=422, detail="Cena 0 až 20 000 Kč.")
    if body.payment_mode not in ("none", "deposit", "full"):
        raise HTTPException(status_code=422, detail="Platba: žádná, záloha nebo celá.")
    p = _me(db, user)
    n = db.query(models.Service).filter_by(physio_id=p.id).count()
    sv = models.Service(physio_id=p.id, clinic_id=p.clinic_id, sort_order=n + 1, **body.model_dump())
    db.add(sv)
    db.commit()
    return to_dict(sv)


@router.patch("/api/services/{sid}", dependencies=[Depends(verify_csrf)])
def edit_service(sid: int, body: ServiceIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    sv = db.get(models.Service, sid)
    if sv is None or sv.physio_id != user.physio_id:
        raise HTTPException(status_code=404, detail="Služba nenalezena")
    for k in body.model_fields_set:
        setattr(sv, k, getattr(body, k))
    db.commit()
    return to_dict(sv)


@router.get("/api/physios/{pid}/calendar")
def calendar(pid: str, start: str = "", end: str = "", user: models.User = Depends(require_verified_physio),
             db: DBSession = Depends(get_db)):
    """Bookings, free intervals and time off in one payload (W5.5). Reception sees the clinic's calendar; a
    physio sees their own."""
    me = _me(db, user)
    if pid != me.id:
        other = db.get(models.Physio, pid)
        if other is None or other.clinic_id != me.clinic_id or not W.can(db, me.id, "clinic_calendar"):
            raise HTTPException(status_code=403, detail="Nemáte přístup")
    try:
        d0 = date.fromisoformat(start) if start else E.today_date() - timedelta(days=E.today_date().weekday())
        d1 = date.fromisoformat(end) if end else d0 + timedelta(days=6)
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatné datum.")
    d1 = min(d1, d0 + timedelta(days=W.MAX_HORIZON_DAYS))
    lo = datetime.combine(d0, datetime.min.time(), E.LOCAL_TZ).astimezone(timezone.utc).isoformat()
    hi = datetime.combine(d1 + timedelta(days=1), datetime.min.time(), E.LOCAL_TZ).astimezone(timezone.utc).isoformat()
    bks = [b for b in db.query(models.Booking).filter(models.Booking.physio_id == pid).all()
           if b.slot_at and lo <= W._aware(b.slot_at).isoformat() < hi and b.status not in ("declined",)]
    clinical = W.can(db, me.id, "clinical")
    out_b = []
    for b in bks:
        v = _visit_out(db, b)
        if not clinical:               # reception: who and when, no clinical status
            v.pop("record", None)
        out_b.append(v)
    return {"bookings": out_b, "free": W.free_times(db, pid, max(d0, E.today_date()), d1),
            "time_off": to_dicts([t for t in db.query(models.TimeOff).filter_by(physio_id=pid).all()
                                  if t.ends_at >= lo and t.starts_at < hi]),
            "from": d0.isoformat(), "to": d1.isoformat()}


class VisitIn(Open):
    runner_id: str
    starts_at: str
    service_id: int | None = None
    kind: str = "follow_up"
    weeks: int = 1                      # W5.7 recurring: same weekday and time for N weeks
    reason: str | None = None


@router.post("/api/physios/me/visits", dependencies=[Depends(verify_csrf)])
def add_visit(body: VisitIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Add a visit (or a series); conflicts are reported per date and never booked over."""
    p = _me(db, user)
    _client(db, p, body.runner_id)
    if not 1 <= body.weeks <= 26:
        raise HTTPException(status_code=422, detail="Opakování 1 až 26 týdnů.")
    try:
        first = W._aware(body.starts_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatný čas.")
    sv = db.get(models.Service, body.service_id) if body.service_id else None
    mins = (sv.duration_minutes if sv else 45)
    group = uuid.uuid4().hex[:12] if body.weeks > 1 else None
    made, conflicts = [], []
    local = first.astimezone(E.LOCAL_TZ)
    for k in range(body.weeks):
        at = datetime.combine(local.date() + timedelta(weeks=k), local.timetz().replace(tzinfo=None), E.LOCAL_TZ)
        if at <= datetime.now(timezone.utc):
            conflicts.append({"at": at.isoformat(), "why": "v minulosti"})
            continue
        if not W.is_free(db, p.id, at, mins):
            conflicts.append({"at": at.isoformat(), "why": "koliduje s jinou návštěvou nebo volnem"})
            continue
        b = models.Booking(runner_id=body.runner_id, physio_id=p.id, slot_at=at.astimezone(timezone.utc).isoformat(),
                           duration_min=mins, kind=body.kind, status="confirmed", service_id=sv.id if sv else None,
                           price_czk=sv.price_czk if sv else None, payer="client", reason=body.reason,
                           recurring_group=group, created_at=E.now_iso(),
                           episode_id=R.episode_for(db, p.id, body.runner_id).id)
        db.add(b)
        db.flush()
        made.append(b.id)
    if made:
        db.add(models.Message(runner_id=body.runner_id, physio_id=p.id, sender="physio", created_at=E.now_iso(),
                              body=f"Naplánoval(a) jsem vám {len(made)} {'návštěvu' if len(made) == 1 else 'návštěvy'}. "
                                   "Termíny najdete v záložce Péče."))
        W.NOTIFY.send(db, "booking_confirmed", "Nový termín u fyzioterapeuta", runner_id=body.runner_id)
        R.physio_event(db, p, "create", "booking", made[0], runner_id=body.runner_id, detail={"count": len(made)})
    db.commit()
    return {"created": made, "conflicts": conflicts}


@router.post("/api/physios/me/ics", dependencies=[Depends(verify_csrf)])
def ics_link(request: Request, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """W5.8: the physio's calendar feed — initials and service only."""
    p = _me(db, user)
    token = secrets.token_urlsafe(24)
    p.ics_token = hashlib.sha256(token.encode()).hexdigest()
    db.commit()
    url = f"{str(request.base_url).rstrip('/')}/api/physio-calendar/{token}.ics"
    return {"url": url, "webcal": "webcal://" + url.split("://", 1)[1]}


@router.get("/api/physio-calendar/{token}.ics")
def ics_feed(token: str, db: DBSession = Depends(get_db)):
    p = db.query(models.Physio).filter_by(ics_token=hashlib.sha256(token.encode()).hexdigest()).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Kalendář nenalezen")
    from .calendar import _esc, _fold
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dosslap//Physio//CS", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Došlap"]
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for b in db.query(models.Booking).filter(models.Booking.physio_id == p.id,
                                             models.Booking.status.in_(("confirmed", "requested", "completed"))).all():
        if not b.slot_at or W._aware(b.slot_at).isoformat() < since:
            continue
        r = db.get(models.Runner, b.runner_id)
        ini = "".join(x[0] for x in (r.name if r else "?").split()[:2]).upper()
        sv = db.get(models.Service, b.service_id) if b.service_id else None
        s = W._aware(b.slot_at).astimezone(timezone.utc)
        e = s + timedelta(minutes=b.duration_min or 45)
        lines += ["BEGIN:VEVENT", f"UID:booking-{b.id}@dosslap", f"DTSTAMP:{stamp}",
                  f"DTSTART:{s.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{e.strftime('%Y%m%dT%H%M%SZ')}",
                  _fold(f"SUMMARY:{_esc(ini + ' · ' + (sv.name_cs if sv else 'Návštěva'))}"),
                  f"STATUS:{'TENTATIVE' if b.status == 'requested' else 'CONFIRMED'}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar; charset=utf-8")


# =============================================================================================== W7 timeline
@router.get("/api/physios/me/clients/{rid}/timeline")
def timeline(rid: str, weeks: int = 12, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """One date axis: load against capacity, volume, mechanics, readiness, pain per region, adherence and
    markers for visits, programme changes, injuries and limits. Days without data are absent, never
    interpolated."""
    p = _me(db, user)
    _client(db, p, rid)
    if weeks not in (4, 8, 12, 26):
        weeks = 12
    t = E.today_date()
    d0 = (t - timedelta(weeks=weeks)).isoformat()
    days: dict[str, dict] = {}

    def day(d):
        return days.setdefault(d, {"date": d})
    for a in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at >= d0).all():
        x = day((a.started_at or "")[:10])
        if (a.sport or "running") == "running":
            x["km"] = round((x.get("km") or 0) + (a.distance_km or 0), 2)
    for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at >= d0).all():
        x = day(c.submitted_at[:10])
        if c.pain_score is not None:
            x.setdefault("pain", {})[c.pain_site or "bez místa"] = c.pain_score
    for f in db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid,
                                                      models.ActivityFeedback.submitted_at >= d0).all():
        if f.pain_during:
            x = day(f.submitted_at[:10])
            x.setdefault("pain", {})[f.pain_site or "při běhu"] = max(f.pain_during, (x.get("pain") or {}).get(f.pain_site or "při běhu", 0))
    from .. import history as H
    try:
        hist = H.quadrant_cache_fresh(db, rid) or H.build_quadrant_history(db, rid, min(190, weeks * 7 + 1))
    except Exception:
        hist = []
    for h in hist or []:
        d = (h.get("date") or "")[:10]
        if d >= d0:
            x = day(d)
            for k in ("load", "mech", "symp", "overall", "readiness", "quadrant"):
                if h.get(k) is not None:
                    x[k] = h[k]
    for lg in db.query(models.ExerciseLog).filter(models.ExerciseLog.runner_id == rid, models.ExerciseLog.logged_on >= d0).all():
        x = day(lg.logged_on)
        x["exercises"] = (x.get("exercises") or 0) + 1
    events = []
    for b in db.query(models.Booking).filter(models.Booking.runner_id == rid, models.Booking.status.in_(("completed", "confirmed"))).all():
        if (b.slot_at or "")[:10] >= d0:
            events.append({"at": b.slot_at, "type": "visit", "title": "Návštěva", "severity": "info", "ref": f"booking:{b.id}"})
    for prog in db.query(models.Program).filter_by(runner_id=rid).all():
        for rv in db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == prog.id,
                                                          models.ProgramRevision.note.isnot(None)).all():
            if (rv.at or "")[:10] >= d0:
                events.append({"at": rv.at, "type": "program", "title": "Změna programu", "detail": rv.note,
                               "severity": "info", "ref": f"program:{prog.id}"})
        if (prog.sent_at or "")[:10] >= d0:
            events.append({"at": prog.sent_at, "type": "program", "title": f"Program „{prog.name}“", "severity": "info",
                           "ref": f"program:{prog.id}"})
    for inj in db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid,
                                                    models.InjuryReport.submitted_at >= d0).all():
        if inj.status == "active":
            events.append({"at": inj.submitted_at, "type": "injury", "title": f"Zranění {inj.body_region or ''}".strip(),
                           "detail": f"OSTRC {inj.severity}/100", "severity": "high", "ref": f"injury:{inj.id}"})
    for lim in db.query(models.ClinicalLimit).filter_by(runner_id=rid).all():
        if (lim.starts_on or "") >= d0:
            events.append({"at": lim.starts_on, "type": "limit", "title": W.limit_text(lim), "detail": lim.reason_cs,
                           "severity": "medium", "ref": f"limit:{lim.id}"})
    for s in db.query(models.RtrSession).filter(models.RtrSession.runner_id == rid, models.RtrSession.logged_at >= d0).all():
        x = day(s.logged_at[:10])
        x["rtr"] = {"level": s.level, "pain": s.pain, "morning": s.next_morning_pain, "counted": bool(s.counted)}
    R.physio_event(db, p, "read", "runner", rid, runner_id=rid, detail={"screen": "timeline"})
    db.commit()
    return {"from": d0, "to": t.isoformat(), "weeks": weeks, "days": sorted(days.values(), key=lambda x: x["date"]),
            "events": sorted(events, key=lambda e: e["at"] or "")}


# =============================================================================================== W8 previsit
@router.get("/api/physios/me/clients/{rid}/previsit")
def previsit(rid: str, booking_id: int | None = None, user: models.User = Depends(require_verified_physio),
             db: DBSession = Depends(get_db)):
    """Příprava: reason and questions, since the last visit, plan against reality, last record, missing data.
    Works without a language model. Tissue hypotheses only with D10's flag."""
    from .. import care_view as CV
    from ..metrics import ai_brief as AB
    from .programs import program_out
    p = _me(db, user)
    _client(db, p, rid)
    b = db.get(models.Booking, booking_id) if booking_id else None
    last = (db.query(models.Conclusion).filter_by(runner_id=rid, physio_id=p.id, status="approved")
            .order_by(models.Conclusion.approved_at.desc()).first())
    since = (last.approved_at if last else (E.today_date() - timedelta(days=28)).isoformat())[:10]
    runs = [a for a in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at >= since).all()
            if (a.sport or "running") == "running"]
    pains = [c for c in db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at >= since).all()
             if (c.pain_score or 0) > 0]
    prog = (db.query(models.Program).filter_by(runner_id=rid, physio_id=p.id, active=True).order_by(models.Program.id.desc()).first())
    po = program_out(db, prog) if prog else None
    a = CV.present(db, rid, E.get_or_refresh_assessment(db, rid)) or {}
    intake = db.query(models.IntakeForm).filter_by(runner_id=rid).order_by(models.IntakeForm.id.desc()).first()
    missing = []
    if (a.get("freshness") or {}).get("status") in ("stale", "none"):
        missing.append("Aktuální data z hodinek")
    if not pains and not db.query(models.Checkin.id).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at >= since).first():
        missing.append("Check-iny od poslední návštěvy")
    out = {"reason": b.reason if b else None, "questions": b.questions if b else None,
           "intake": intake.data if intake else None,
           "since": {"from": since, "runs": len(runs), "km": round(sum(r.distance_km or 0 for r in runs), 1),
                     "pain_days": len({c.submitted_at[:10] for c in pains}),
                     "pain_max": max((c.pain_score for c in pains), default=None),
                     "sites": sorted({c.pain_site for c in pains if c.pain_site})},
           "plan_vs_reality": ({"program": po["name"], "adherence": po["adherence"],
                                "exercises": [{"name": e["name"], "per_week": e["per_week"], "done": e["done_count"],
                                               "target": e["target_count"]} for e in po["exercises"]]} if po else None),
           "limits": [W.limit_text(x) for x in W.active_limits(db, rid)],
           "last_record": ({"at": last.approved_at, "assessment": last.assessment, "plan": last.plan, "summary": last.summary}
                           if last else None),
           "missing": missing, "care_directive": a.get("careDirective"),
           "hypotheses": None}
    if AB.hypotheses_on():
        out["hypotheses"] = {"label": "Hypotéza z dat, nenahrazuje vyšetření", "items": []}
    R.physio_event(db, p, "read", "runner", rid, runner_id=rid, detail={"screen": "previsit"})
    db.commit()
    return out


# =============================================================================================== W9 templates
class NoteTplIn(Open):
    name: str
    fields: dict


DEFAULT_TEMPLATES = [
    {"name": "Vstupní vyšetření", "fields": {
        "subjective": "Hlavní obtíž:\nZačátek a průběh:\nCo zhoršuje / ulevuje:\nBěžecký objem a změny:\nDřívější zranění:",
        "objective": "Aspekce:\nPalpace:\nRozsah pohybu:\nSvalová síla:\nFunkční testy:",
        "assessment": "", "plan": "Edukace:\nCvičení:\nÚprava tréninku:\nKontrola:", "services_provided": "Vstupní kineziologické vyšetření"}},
    {"name": "Kontrola", "fields": {
        "subjective": "Od minulé návštěvy:\nBolest (0–10):\nPlnění programu:",
        "objective": "Kontrola nálezu:", "assessment": "", "plan": "Pokračovat / upravit:\nDalší kontrola:",
        "services_provided": "Kontrolní vyšetření"}},
]


@router.get("/api/physios/me/note-templates")
def note_templates(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    rows = db.query(models.NoteTemplate).filter((models.NoteTemplate.physio_id == p.id) |
                                                (models.NoteTemplate.clinic_id == p.clinic_id)).all()
    return {"items": [{"id": None, **t} for t in DEFAULT_TEMPLATES] + [{"id": t.id, "name": t.name, "fields": t.fields} for t in rows]}


@router.post("/api/physios/me/note-templates", dependencies=[Depends(verify_csrf)])
def add_note_template(body: NoteTplIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    allowed = {"subjective", "objective", "assessment", "plan", "services_provided"}
    if not body.name.strip() or not set(body.fields) <= allowed:
        raise HTTPException(status_code=422, detail="Šablona potřebuje název a jen pole záznamu.")
    t = models.NoteTemplate(physio_id=p.id, clinic_id=p.clinic_id, name=body.name.strip(), fields=body.fields, created_at=E.now_iso())
    db.add(t)
    db.commit()
    return {"id": t.id, "name": t.name, "fields": t.fields}


@router.get("/api/physios/me/clients/{rid}/last-note")
def last_note(rid: str, bid: int | None = None, user: models.User = Depends(require_verified_physio),
              db: DBSession = Depends(get_db)):
    """W9.6: Zkopírovat z minula — the text fields of the last approved record, never the OSTRC.
    Round 2 F1.9: from the same care episode as the visit being written (bid); without one, the open episode."""
    p = _me(db, user)
    _client(db, p, rid)
    bk = db.get(models.Booking, bid) if bid else None
    ep_id = bk.episode_id if bk is not None and bk.runner_id == rid else None
    if ep_id is None:
        ep = (db.query(models.CareEpisode).filter_by(runner_id=rid, physio_id=p.id, status="open")
              .order_by(models.CareEpisode.id.desc()).first())
        ep_id = ep.id if ep else None
    q = db.query(models.Conclusion).filter_by(runner_id=rid, physio_id=p.id, status="approved")
    if ep_id is not None:
        q = q.filter(models.Conclusion.episode_id == ep_id)
    if bid:
        q = q.filter(models.Conclusion.booking_id != bid)
    c = q.order_by(models.Conclusion.approved_at.desc()).first()
    if c is None:
        return {"fields": None}
    return {"fields": {k: getattr(c, k) for k in ("subjective", "objective", "assessment", "plan", "services_provided",
                                                  "diagnosis_code", "diagnosis_label")}, "at": c.approved_at}


# =============================================================================================== W12 limits
class LimitIn(Open):
    kind: str
    value: float | None = None
    starts_on: str | None = None
    ends_on: str | None = None
    reason_cs: str = ""


def _limit_out(x: models.ClinicalLimit) -> dict:
    return {**to_dict(x), "text": W.limit_text(x)}


@router.get("/api/physios/me/clients/{rid}/limits")
def list_limits(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    return {"items": [_limit_out(x) for x in db.query(models.ClinicalLimit).filter_by(runner_id=rid).order_by(
        models.ClinicalLimit.id.desc()).all()], "kinds": W.LIMIT_KINDS}


@router.post("/api/physios/me/clients/{rid}/limits", dependencies=[Depends(verify_csrf)])
def add_limit(rid: str, body: LimitIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    if body.kind not in W.LIMIT_KINDS:
        raise HTTPException(status_code=422, detail="Neznámý druh omezení")
    if "{v}" in W.LIMIT_KINDS[body.kind] and (body.value is None or body.value < 0):
        raise HTTPException(status_code=422, detail="Omezení potřebuje hodnotu.")
    if not body.reason_cs.strip():
        raise HTTPException(status_code=422, detail="Uveďte důvod, klient ho uvidí.")
    x = models.ClinicalLimit(runner_id=rid, physio_id=p.id, kind=body.kind, value=body.value,
                             starts_on=body.starts_on or E.iso_date(E.today_date()), ends_on=body.ends_on,
                             reason_cs=body.reason_cs.strip(), active=True, created_at=E.now_iso(),
                             episode_id=R.episode_for(db, p.id, rid).id)
    db.add(x)
    db.flush()
    R.physio_event(db, p, "create", "limit", x.id, runner_id=rid, detail={"kind": body.kind})
    db.add(models.Message(runner_id=rid, physio_id=p.id, sender="system", created_at=E.now_iso(),
                          body=f"Fyzioterapeut nastavil omezení tréninku: {W.limit_text(x)} — {x.reason_cs}"))
    db.commit()
    E.recompute_assessment(db, rid)
    return _limit_out(x)


@router.patch("/api/limits/{lid}", dependencies=[Depends(verify_csrf)])
def edit_limit(lid: int, body: LimitIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    x = db.get(models.ClinicalLimit, lid)
    if x is None or x.physio_id != p.id:
        raise HTTPException(status_code=404, detail="Omezení nenalezeno")
    for k in body.model_fields_set - {"kind"}:
        setattr(x, k, getattr(body, k))
    R.physio_event(db, p, "update", "limit", x.id, runner_id=x.runner_id, detail={"fields": sorted(body.model_fields_set)})
    db.commit()
    return _limit_out(x)


@router.delete("/api/limits/{lid}", dependencies=[Depends(verify_csrf)])
def end_limit(lid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Deletion only deactivates (W12.1)."""
    p = _me(db, user)
    x = db.get(models.ClinicalLimit, lid)
    if x is None or x.physio_id != p.id:
        raise HTTPException(status_code=404, detail="Omezení nenalezeno")
    x.active = False
    x.ends_on = x.ends_on or E.iso_date(E.today_date())
    R.physio_event(db, p, "close", "limit", x.id, runner_id=x.runner_id)
    db.add(models.Message(runner_id=x.runner_id, physio_id=p.id, sender="system", created_at=E.now_iso(),
                          body=f"Omezení tréninku skončilo: {W.limit_text(x)}."))
    db.commit()
    return _limit_out(x)


# =============================================================================================== W13 messages
UPLOAD_DIR = os.environ.get("DOSSLAP_UPLOAD_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "uploads")
MAX_IMAGE, MAX_VIDEO = 8 * 1024 * 1024, 50 * 1024 * 1024
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4", "video/quicktime": ".mov",
           "video/webm": ".webm"}


@router.get("/api/physios/me/inbox")
def inbox(q: str = "", unread: bool = False, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    out = []
    for rid in W._clients(db, p.id):
        r = db.get(models.Runner, rid)
        if q and q.lower() not in (r.name if r else "").lower():
            continue
        last = (db.query(models.Message).filter(models.Message.runner_id == rid).order_by(models.Message.created_at.desc()).first())
        n = db.query(models.Message).filter(models.Message.runner_id == rid, models.Message.sender == "runner",
                                            models.Message.read_at_physio.is_(None)).count()
        if unread and not n:
            continue
        open_ = last is not None and last.sender == "runner" and not last.handled_at
        out.append({"runner_id": rid, "name": r.name if r else rid, "unread": n, "needs_reply": open_,
                    "last": {"at": last.created_at, "sender": last.sender, "body": (last.body or "")[:140]} if last else None})
    out.sort(key=lambda x: (-(x["unread"] > 0), -(x["needs_reply"]), -(datetime.fromisoformat(x["last"]["at"]).timestamp()
                                                                         if x["last"] else 0)))
    return {"items": out, "quick_replies": p.quick_replies or [], "response_time_text": p.response_time_text}


@router.post("/api/physios/me/clients/{rid}/messages/handled", dependencies=[Depends(verify_csrf)])
def handled(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Vyřízeno: the last client message needs no reply."""
    p = _me(db, user)
    _client(db, p, rid)
    for m in db.query(models.Message).filter(models.Message.runner_id == rid, models.Message.sender == "runner",
                                             models.Message.handled_at.is_(None)).all():
        m.handled_at = E.now_iso()
        m.read_at_physio = m.read_at_physio or E.now_iso()
    db.commit()
    return {"ok": True}


@router.post("/api/runners/{rid}/messages/attachment", dependencies=[Depends(verify_csrf)])
async def attach(rid: str, file: UploadFile = File(...), body: str = "", user: models.User = Depends(get_current_user),
                 db: DBSession = Depends(get_db)):
    """An image or a short video (W13.2), size-limited, stored privately and served only through an access check."""
    from ..deps import ensure_runner_write_access
    ensure_runner_write_access(db, user, rid)
    ext = ALLOWED.get(file.content_type or "")
    if not ext:
        raise HTTPException(status_code=415, detail="Povolené jsou obrázky (JPG, PNG, WebP) a krátká videa (MP4, MOV, WebM).")
    data = await file.read()
    limit = MAX_VIDEO if (file.content_type or "").startswith("video/") else MAX_IMAGE
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Soubor je větší než {limit // (1024 * 1024)} MB.")
    os.makedirs(os.path.join(UPLOAD_DIR, rid), exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, rid, name), "wb") as f:
        f.write(data)
    sender = "physio" if user.role == "physio" else "runner"
    physio_id = user.physio_id if sender == "physio" else (
        db.query(models.CareAssignment.physio_id).filter_by(runner_id=rid, status="active").limit(1).scalar())
    m = models.Message(runner_id=rid, physio_id=physio_id, sender=sender, body=body or "",
                       attachment_path=f"{rid}/{name}", attachment_type=file.content_type,
                       attachment_name=(file.filename or name)[:120], created_at=E.now_iso(),
                       **{"read_at_physio" if sender == "physio" else "read_at_runner": E.now_iso()})
    db.add(m)
    if sender == "physio":
        R.physio_event(db, db.get(models.Physio, user.physio_id), "message", "messages", None, runner_id=rid, detail={"attachment": True})
    db.commit()
    return to_dict(m)


@router.get("/api/messages/{mid}/attachment")
def attachment(mid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    m = db.get(models.Message, mid)
    if m is None or not m.attachment_path:
        raise HTTPException(status_code=404, detail="Příloha nenalezena")
    ensure_runner_read_access(db, user, m.runner_id)
    path = os.path.realpath(os.path.join(UPLOAD_DIR, m.attachment_path))
    if not path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep) or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Příloha nenalezena")
    if user.role == "physio":
        R.physio_event(db, db.get(models.Physio, user.physio_id), "read", "messages", mid, runner_id=m.runner_id,
                       detail={"attachment": True})
        db.commit()
    return FileResponse(path, media_type=m.attachment_type, headers={"Cache-Control": "private, no-store"})


# =============================================================================================== W15 notifications
@router.get("/api/notifications")
def notifications(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    q = db.query(models.Notification).filter(models.Notification.channel == "in_app")
    if user.role == "physio":
        q = q.filter(models.Notification.physio_id == user.physio_id)
    elif user.runner_id:
        q = q.filter(models.Notification.runner_id == user.runner_id, models.Notification.physio_id.is_(None))
    else:
        return {"items": []}
    rows = q.order_by(models.Notification.id.desc()).limit(50).all()
    return {"items": [{"id": n.id, "event": n.event, "title": n.title, "at": n.created_at, "read": bool(n.read_at),
                       "ref": n.ref} for n in rows]}


@router.post("/api/notifications/read", dependencies=[Depends(verify_csrf)])
def notifications_read(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    q = db.query(models.Notification).filter(models.Notification.read_at.is_(None))
    q = q.filter(models.Notification.physio_id == user.physio_id) if user.role == "physio" else \
        q.filter(models.Notification.runner_id == user.runner_id, models.Notification.physio_id.is_(None))
    for n in q.all():
        n.read_at = E.now_iso()
    db.commit()
    return {"ok": True}


# =============================================================================================== W16 intake
class IntakeIn(Open):
    booking_id: int | None = None
    data: dict


@router.post("/api/runners/{rid}/intake", dependencies=[Depends(verify_csrf)])
def intake(rid: str, body: IntakeIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """W16.4: the first-visit intake (history, red flags, consent), attached to the patient card."""
    ensure_runner_self(user, rid)
    if not body.data.get("consent"):
        raise HTTPException(status_code=422, detail="Potvrďte souhlas se zpracováním údajů pro péči.")
    b = db.get(models.Booking, body.booking_id) if body.booking_id else None
    if b is not None and b.runner_id != rid:
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    x = models.IntakeForm(runner_id=rid, physio_id=b.physio_id if b else None, booking_id=b.id if b else None,
                          data={k: v for k, v in body.data.items() if k in INTAKE_FIELDS}, created_at=E.now_iso())
    db.add(x)
    R.event(db, actor_type="runner", actor_id=rid, actor_name=user.name, action="create", resource_type="intake",
            runner_id=rid, detail={"fields": sorted(x.data)})
    db.commit()
    return {"id": x.id}


INTAKE_FIELDS = ("history", "medications", "surgeries", "red_flags", "goals", "consent", "birth_date", "address", "gp")
