"""Phase 3 (paid product) and Phase 4 (moat) endpoints — physio brief 2026-11-09 B1, B2, B4, B5, B6, M1–M4.
B3 (referral fee) is not built: the brief makes it wait for counsel. M5 (interoperability) waits for the
official standards to apply; the export in records.py stays the hand-over format until then."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session as DBSession

from .. import business as B
from .. import models
from .. import moat as M
from .. import records as R
from .. import work as W
from ..db import get_db
from ..deps import ensure_runner_self, get_current_user, has_care_assignment, is_owner, require_verified_physio, verify_csrf
from ..metrics import engine as E
from ..schemas import Lenient as Open
from ..serializers import to_dict, to_dicts

router = APIRouter(tags=["physio-work"])


def _me(db: DBSession, user: models.User) -> models.Physio:
    p = db.get(models.Physio, user.physio_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")
    W.ensure_clinic(db, p)
    return p


def _client(db: DBSession, p: models.Physio, rid: str) -> None:
    if not W.can(db, p.id, "clinical") or not has_care_assignment(db, p.id, rid):
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto klientovi")


def _period(start: str, end: str) -> tuple[date, date]:
    try:
        t = E.today_date()
        d0 = date.fromisoformat(start) if start else t.replace(day=1)
        d1 = date.fromisoformat(end) if end else t
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatné datum.")
    if d1 < d0 or (d1 - d0).days > 400:
        raise HTTPException(status_code=422, detail="Období nejvýš 400 dní.")
    return d0, d1


def _sees_clinic_money(db: DBSession, p: models.Physio) -> bool:
    return W.role_of(db, p.id) in ("owner", "admin", "reception")


# =============================================================================================== B1 receipts
def _inv_out(db: DBSession, i: models.Invoice) -> dict:
    r = db.get(models.Runner, i.runner_id)
    return {**to_dict(i), "client": r.name if r else i.runner_id}


@router.get("/api/physios/me/invoices")
def invoices(start: str = "", end: str = "", user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    d0, d1 = _period(start, end)
    q = db.query(models.Invoice).filter(models.Invoice.clinic_id == p.clinic_id,
                                        models.Invoice.issued_at >= d0.isoformat(),
                                        models.Invoice.issued_at < (d1 + timedelta(days=1)).isoformat())
    if not _sees_clinic_money(db, p):
        q = q.filter(models.Invoice.physio_id == p.id)
    items = [_inv_out(db, i) for i in q.order_by(models.Invoice.number.asc()).all()]
    db.commit()
    return {"items": items, "vat_note": "DPH není nastavené — potvrďte ho s účetní.", "provider_live": B.provider_live()}


@router.get("/api/physios/me/invoices.csv")
def invoices_csv(start: str = "", end: str = "", user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """B1.3: for the accountant — number, date, client, payer, amount, paid, status. No clinical content."""
    data = invoices(start, end, user, db)["items"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["cislo", "vystaveno", "klient", "platce", "castka_czk", "zaplaceno_czk", "stav", "polozky"])
    for i in data:
        w.writerow([i["number"], (i["issued_at"] or "")[:10], i["client"], i["payer"], i["amount_czk"], i["paid_czk"],
                    i["status"], " | ".join(x["text"] for x in (i["items"] or []))])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="doklady.csv"'})


@router.post("/api/bookings/{bid}/invoice", dependencies=[Depends(verify_csrf)])
def make_invoice(bid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    b = db.get(models.Booking, bid)
    if b is None:
        raise HTTPException(status_code=404, detail="Návštěva nenalezena")
    owner = db.get(models.Physio, b.physio_id)
    if b.physio_id != p.id and not (owner and owner.clinic_id == p.clinic_id and _sees_clinic_money(db, p)):
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    if b.status not in ("completed", "confirmed"):
        raise HTTPException(status_code=409, detail="Doklad jde vystavit jen k proběhlé nebo potvrzené návštěvě.")
    inv = B.issue_invoice(db, b, physio=owner or p)
    db.commit()
    return _inv_out(db, inv)


class InvoiceStatusIn(Open):
    status: str


@router.patch("/api/invoices/{iid}", dependencies=[Depends(verify_csrf)])
def invoice_status(iid: int, body: InvoiceStatusIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Paid on site, or cancelled (a cancelled receipt keeps its number; numbers are never reused)."""
    p = _me(db, user)
    i = db.get(models.Invoice, iid)
    if i is None or i.clinic_id != p.clinic_id or (i.physio_id != p.id and not _sees_clinic_money(db, p)):
        raise HTTPException(status_code=404, detail="Doklad nenalezen")
    if body.status not in ("paid", "cancelled"):
        raise HTTPException(status_code=422, detail="Stav: zaplaceno nebo zrušeno.")
    i.status = body.status
    if body.status == "paid":
        i.paid_czk, i.paid_at = i.amount_czk, E.now_iso()
    db.commit()
    return _inv_out(db, i)


@router.get("/api/physios/me/revenue")
def revenue(start: str = "", end: str = "", user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    d0, d1 = _period(start, end)
    out = B.revenue(db, p.clinic_id, d0, d1, None if _sees_clinic_money(db, p) else p.id)
    db.commit()
    return out


class PackageIn(Open):
    name: str
    visits_total: int
    price_czk: int
    paid: bool = False


@router.get("/api/physios/me/clients/{rid}/packages")
def packages(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    return {"items": to_dicts(db.query(models.Package).filter_by(runner_id=rid, clinic_id=p.clinic_id)
                              .order_by(models.Package.id.desc()).all())}


@router.post("/api/physios/me/clients/{rid}/packages", dependencies=[Depends(verify_csrf)])
def add_package(rid: str, body: PackageIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """B1.4: a package of visits; each completed visit with this physio takes one."""
    p = _me(db, user)
    _client(db, p, rid)
    if not body.name.strip() or not 2 <= body.visits_total <= 50 or not 0 <= body.price_czk <= 200000:
        raise HTTPException(status_code=422, detail="Balíček: název, 2 až 50 návštěv, cena 0 až 200 000 Kč.")
    pk = models.Package(clinic_id=p.clinic_id, physio_id=p.id, runner_id=rid, name=body.name.strip()[:80],
                        visits_total=body.visits_total, visits_used=0, price_czk=body.price_czk, status="open",
                        paid_at=E.now_iso() if body.paid else None, created_at=E.now_iso())
    db.add(pk)
    db.commit()
    return to_dict(pk)


# =============================================================================================== payments
@router.get("/api/runners/{rid}/payments")
def runner_payments(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    rows = db.query(models.Payment).filter_by(runner_id=rid).order_by(models.Payment.id.desc()).all()
    return {"items": to_dicts(rows), "provider_live": B.provider_live()}


@router.post("/api/payments/{pid}/mock-pay", dependencies=[Depends(verify_csrf)])
def mock_pay(pid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Only the mock provider has this endpoint; a real provider confirms through its webhook."""
    pay = db.get(models.Payment, pid)
    if pay is None or pay.provider != "mock":
        raise HTTPException(status_code=404, detail="Platba nenalezena")
    if pay.kind == "subscription":
        me = db.get(models.Physio, user.physio_id) if user.physio_id else None
        if me is None or me.clinic_id != pay.clinic_id or not W.can(db, me.id, "billing"):
            raise HTTPException(status_code=403, detail="Předplatné platí vlastník praxe.")
    elif user.runner_id != pay.runner_id:
        raise HTTPException(status_code=403, detail="Nemáte přístup")
    if pay.status == "paid":
        return to_dict(pay)
    B.PROVIDER.capture(db, pay)
    if pay.kind == "subscription":
        B.apply_subscription_payment(db, pay)
    db.commit()
    return to_dict(pay)


# =============================================================================================== B2 seats
@router.get("/api/physios/me/subscription")
def subscription(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    st = B.subscription_state(db, p.clinic_id)
    sub = db.query(models.Subscription).filter_by(clinic_id=p.clinic_id).first()
    seats = db.query(models.ClinicMember).filter(models.ClinicMember.clinic_id == p.clinic_id,
                                                 models.ClinicMember.active.is_(True),
                                                 models.ClinicMember.role != "reception").count()
    db.commit()
    return {**st, "seats": seats, "price_czk_per_seat": sub.price_czk_per_seat if sub else W.SEAT_PRICE_CZK,
            "trial_ends_at": sub.trial_ends_at if sub else None, "paid_until": sub.paid_until if sub else None,
            "can_pay": W.can(db, p.id, "billing"), "provider_live": B.provider_live()}


@router.post("/api/physios/me/subscription/pay", dependencies=[Depends(verify_csrf)])
def subscription_pay(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    if not W.can(db, p.id, "billing"):
        raise HTTPException(status_code=403, detail="Předplatné platí vlastník praxe.")
    sub = db.query(models.Subscription).filter_by(clinic_id=p.clinic_id).first()
    if sub is None:
        raise HTTPException(status_code=404, detail="Předplatné nenalezeno")
    seats = max(1, db.query(models.ClinicMember).filter(models.ClinicMember.clinic_id == p.clinic_id,
                                                        models.ClinicMember.active.is_(True),
                                                        models.ClinicMember.role != "reception").count())
    pay = B.seats_pay(db, sub, seats)
    db.commit()
    return {**to_dict(pay), "url": f"/api/payments/{pay.id}/mock-pay"}


# =============================================================================================== B4 waitlist
class WaitIn(Open):
    dow: str = ""
    dayparts: str = ""
    note: str = ""


@router.post("/api/physios/{pid}/waitlist", dependencies=[Depends(verify_csrf)])
def join_waitlist(pid: str, body: WaitIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    if user.role != "runner" or not user.runner_id:
        raise HTTPException(status_code=403, detail="Do pořadníku se zapisuje běžec.")
    if db.get(models.Physio, pid) is None:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")
    have = db.query(models.Waitlist).filter(models.Waitlist.physio_id == pid, models.Waitlist.runner_id == user.runner_id,
                                            models.Waitlist.status.in_(("waiting", "offered"))).first()
    if have is not None:
        return to_dict(have)
    w = models.Waitlist(physio_id=pid, runner_id=user.runner_id, dow=body.dow[:20], dayparts=body.dayparts[:40],
                        note=body.note.strip()[:300] or None, status="waiting", created_at=E.now_iso())
    db.add(w)
    db.commit()
    return to_dict(w)


@router.get("/api/runners/{rid}/waitlist")
def my_waitlist(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    B.expire_offers(db)
    db.commit()
    out = []
    for w in db.query(models.Waitlist).filter(models.Waitlist.runner_id == rid,
                                              models.Waitlist.status.in_(("waiting", "offered"))).all():
        ph = db.get(models.Physio, w.physio_id)
        out.append({**to_dict(w), "physio": ph.name if ph else None})
    return {"items": out}


@router.delete("/api/waitlist/{wid}", dependencies=[Depends(verify_csrf)])
def leave_waitlist(wid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    w = db.get(models.Waitlist, wid)
    if w is None or w.runner_id != user.runner_id:
        raise HTTPException(status_code=404, detail="Nenalezeno")
    w.status = "removed"
    db.commit()
    return {"ok": True}


@router.get("/api/physios/me/waitlist")
def physio_waitlist(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """Who waits, and for each free time in the next 14 days how many would take it."""
    p = _me(db, user)
    B.expire_offers(db, p.id)
    t = E.today_date()
    free = [f for f in W.free_times(db, p.id, t, t + timedelta(days=14)) if not f.get("slot_id")]
    items = []
    for w in (db.query(models.Waitlist).filter(models.Waitlist.physio_id == p.id,
                                               models.Waitlist.status.in_(("waiting", "offered")))
              .order_by(models.Waitlist.created_at.asc()).all()):
        r = db.get(models.Runner, w.runner_id)
        fits = [f["start"] for f in free if w in B.waitlist_matches(db, p.id, f["start"])][:5]
        items.append({**to_dict(w), "name": r.name if r else w.runner_id, "fits": fits})
    db.commit()
    return {"items": items}


class OfferIn(Open):
    starts_at: str


@router.post("/api/waitlist/{wid}/offer", dependencies=[Depends(verify_csrf)])
def offer(wid: int, body: OfferIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """One person at a time: a time already offered to someone (for the next 2 hours) is not offered again."""
    p = _me(db, user)
    w = db.get(models.Waitlist, wid)
    if w is None or w.physio_id != p.id or w.status != "waiting":
        raise HTTPException(status_code=404, detail="Nenalezeno")
    B.expire_offers(db, p.id)
    try:
        at = W._aware(body.starts_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatný čas.")
    if not W.is_free(db, p.id, at, 45):
        raise HTTPException(status_code=409, detail="Tento čas už není volný.")
    if db.query(models.Waitlist).filter_by(physio_id=p.id, status="offered", offered_slot_at=at.isoformat()).first():
        raise HTTPException(status_code=409, detail="Tento čas je už nabídnutý někomu jinému.")
    w.status, w.offered_slot_at, w.offered_at = "offered", at.isoformat(), E.now_iso()
    db.add(models.Message(runner_id=w.runner_id, physio_id=p.id, sender="system", audience="both", created_at=E.now_iso(),
                          body="Uvolnil se termín z pořadníku. Potvrďte ho do 2 hodin v záložce Péče."))
    W.NOTIFY.send(db, "waitlist_offer", "Uvolnil se termín z pořadníku", runner_id=w.runner_id)
    db.commit()
    return to_dict(w)


@router.post("/api/waitlist/{wid}/accept", dependencies=[Depends(verify_csrf)])
def accept_offer(wid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    B.expire_offers(db)
    w = db.get(models.Waitlist, wid)
    if w is None or w.runner_id != user.runner_id or w.status != "offered":
        db.commit()
        raise HTTPException(status_code=410, detail="Nabídka už neplatí.")
    at = W._aware(w.offered_slot_at)
    if not W.is_free(db, w.physio_id, at, 45):
        w.status, w.offered_slot_at = "waiting", None
        db.commit()
        raise HTTPException(status_code=409, detail="Termín mezitím obsadil někdo jiný.")
    b = models.Booking(runner_id=w.runner_id, physio_id=w.physio_id, slot_at=at.astimezone(timezone.utc).isoformat(),
                       duration_min=45, kind="follow_up", status="requested", payer="client", reason=w.note,
                       requested_at=E.now_iso(), created_at=E.now_iso())
    db.add(b)
    db.flush()
    w.status, w.booking_id = "booked", b.id
    W.NOTIFY.send(db, "booking_requested", "Termín z pořadníku přijat", physio_id=w.physio_id, runner_id=w.runner_id)
    db.commit()
    return {"booking_id": b.id, "slot_at": b.slot_at}


# =============================================================================================== B5 PROMs
@router.get("/api/proms/instruments")
def instruments():
    return {"items": [{"key": k, "name": v["name_cs"], "validated": v["validated"], "items": v["items"]}
                      for k, v in B.INSTRUMENTS.items()],
            "note": "Validované dotazníky (např. VISA-A) přidáme až s licencí a validovanou českou verzí."}


class PromIn(Open):
    instrument: str
    every_days: int = 14


@router.get("/api/physios/me/clients/{rid}/proms")
def client_proms(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    return {"schedules": to_dicts(db.query(models.PromSchedule).filter_by(runner_id=rid, physio_id=p.id, active=True).all()),
            "responses": to_dicts(db.query(models.PromResponse).filter_by(runner_id=rid)
                                  .order_by(models.PromResponse.answered_at.asc()).all())}


@router.post("/api/physios/me/clients/{rid}/proms", dependencies=[Depends(verify_csrf)])
def add_prom(rid: str, body: PromIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    if body.instrument not in B.INSTRUMENTS or not 7 <= body.every_days <= 90:
        raise HTTPException(status_code=422, detail="Neznámý dotazník nebo interval mimo 7 až 90 dní.")
    s = (db.query(models.PromSchedule).filter_by(runner_id=rid, physio_id=p.id, instrument=body.instrument).first()
         or models.PromSchedule(runner_id=rid, physio_id=p.id, instrument=body.instrument, created_at=E.now_iso()))
    s.every_days, s.active, s.next_due = body.every_days, True, E.today_date().isoformat()
    db.add(s)
    db.commit()
    return to_dict(s)


@router.delete("/api/proms/{sid}", dependencies=[Depends(verify_csrf)])
def stop_prom(sid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    s = db.get(models.PromSchedule, sid)
    if s is None or s.physio_id != user.physio_id:
        raise HTTPException(status_code=404, detail="Nenalezeno")
    s.active = False
    db.commit()
    return {"ok": True}


@router.get("/api/runners/{rid}/proms/due")
def proms_due(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    return {"items": B.prom_due(db, rid)}


@router.post("/api/proms/{sid}/answer", dependencies=[Depends(verify_csrf)])
def prom_answer(sid: int, body: dict, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    s = db.get(models.PromSchedule, sid)
    if s is None or s.runner_id != user.runner_id or not s.active:
        raise HTTPException(status_code=404, detail="Dotazník nenalezen")
    try:
        r = B.prom_answer(db, s, (body or {}).get("answers") or {})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Vyplňte: {e}")
    R.event(db, actor_type="runner", actor_id=s.runner_id, actor_name=user.name, action="create", resource_type="prom",
            runner_id=s.runner_id, detail={"instrument": s.instrument})
    db.commit()
    return to_dict(r)


# =============================================================================================== B6 reports
@router.get("/api/physios/me/clinic/report")
def clinic_report(start: str = "", end: str = "", user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    if not W.can(db, p.id, "practice"):
        raise HTTPException(status_code=403, detail="Přehled praxe vidí vlastník a správce.")
    d0, d1 = _period(start, end)
    out = B.clinic_report(db, p.clinic_id, d0, d1)
    db.commit()
    return out


# =============================================================================================== M1 outcomes
@router.get("/api/runners/{rid}/outcome-followups")
def followups(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    return {"items": [{"id": f.id, "due_on": f.due_on} for f in M.followups_due(db, rid)]}


class FollowIn(Open):
    running_normally: bool
    recurrence: bool
    pain: int


@router.post("/api/outcome-followups/{fid}", dependencies=[Depends(verify_csrf)])
def answer_followup(fid: int, body: FollowIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    f = db.get(models.OutcomeFollowup, fid)
    if f is None or f.runner_id != user.runner_id or f.status != "scheduled":
        raise HTTPException(status_code=404, detail="Nenalezeno")
    if not 0 <= body.pain <= 10:
        raise HTTPException(status_code=422, detail="Bolest 0 až 10.")
    f.running_normally, f.recurrence, f.pain = body.running_normally, body.recurrence, body.pain
    f.status, f.answered_at = "answered", E.now_iso()
    R.event(db, actor_type="runner", actor_id=f.runner_id, actor_name=user.name, action="create", resource_type="outcome",
            runner_id=f.runner_id, detail={"episode": f.episode_id})
    db.commit()
    return {"ok": True}


@router.get("/api/team/outcomes/export")
def outcomes_export(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """M1.3: owners only, only with a stated legal basis and a pseudonymisation key."""
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Jen pro vlastníky.")
    why = M.export_ready()
    if why:
        raise HTTPException(status_code=409, detail=why)
    rows = M.outcome_rows(db)
    db.commit()
    return {"rows": rows, "count": len(rows)}


# =============================================================================================== M2 recall
@router.get("/api/physios/me/recall")
def recall(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    items = M.recall_list(db, p.id)
    R.physio_event(db, p, "read", "recall", None, detail={"count": len(items)})
    db.commit()
    return {"items": items}


# =============================================================================================== M3 video review
class NoteIn(Open):
    t_seconds: float
    text: str


def _msg_access(db: DBSession, user: models.User, m: models.Message | None) -> None:
    if m is None:
        raise HTTPException(status_code=404, detail="Zpráva nenalezena")
    if user.runner_id == m.runner_id:
        return
    if user.physio_id and W.can(db, user.physio_id, "clinical") and has_care_assignment(db, user.physio_id, m.runner_id):
        return
    raise HTTPException(status_code=403, detail="Nemáte přístup")


@router.get("/api/messages/{mid}/annotations")
def annotations(mid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    m = db.get(models.Message, mid)
    _msg_access(db, user, m)
    return {"items": to_dicts(db.query(models.VideoNote).filter_by(message_id=mid).order_by(models.VideoNote.t_seconds).all())}


@router.post("/api/messages/{mid}/annotations", dependencies=[Depends(verify_csrf)])
def annotate(mid: int, body: NoteIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    m = db.get(models.Message, mid)
    _msg_access(db, user, m)
    if not (m.attachment_type or "").startswith("video/"):
        raise HTTPException(status_code=422, detail="Poznámky v čase jdou jen k videu.")
    if not body.text.strip() or not 0 <= body.t_seconds <= 3600:
        raise HTTPException(status_code=422, detail="Poznámka potřebuje text a čas ve videu.")
    n = models.VideoNote(message_id=mid, physio_id=user.physio_id, runner_id=m.runner_id, t_seconds=round(body.t_seconds, 1),
                         text=body.text.strip()[:500], created_at=E.now_iso())
    db.add(n)
    db.commit()
    return to_dict(n)


# =============================================================================================== M4 test battery
class TestIn(Open):
    test: str
    left: float | None = None
    right: float | None = None
    involved: str | None = None
    booking_id: int | None = None
    tested_on: str | None = None


@router.get("/api/clinic-tests")
def test_catalog():
    return {"items": [{"key": k, **v} for k, v in M.TESTS.items()]}


@router.get("/api/physios/me/clients/{rid}/tests")
def client_tests(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    return {"items": M.test_history(db, rid), "latest": M.latest_lsi(db, rid)}


@router.post("/api/physios/me/clients/{rid}/tests", dependencies=[Depends(verify_csrf)])
def add_test(rid: str, body: TestIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _me(db, user)
    _client(db, p, rid)
    if body.test not in M.TESTS:
        raise HTTPException(status_code=422, detail="Neznámý test")
    if body.involved not in (None, "", "L", "R"):
        raise HTTPException(status_code=422, detail="Postižená strana: L, P nebo nevyplněno.")
    for v in (body.left, body.right):
        if v is not None and not 0 <= v <= 1000:
            raise HTTPException(status_code=422, detail="Hodnota 0 až 1000.")
    if body.left is None and body.right is None:
        raise HTTPException(status_code=422, detail="Vyplňte alespoň jednu stranu.")
    t = models.ClinicTest(runner_id=rid, physio_id=p.id, booking_id=body.booking_id, test=body.test, left=body.left,
                          right=body.right, involved=body.involved or None,
                          tested_on=body.tested_on or E.today_date().isoformat(), created_at=E.now_iso())
    db.add(t)
    db.commit()
    return {**to_dict(t), "lsi": M.lsi(t.left, t.right, t.involved)}
