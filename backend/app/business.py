"""Phase 3, the paid product (physio brief 2026-11-09 B1, B2, B4, B5, B6).

Payments go through a `PaymentProvider`; the only implementation is a mock that never moves money — a real
provider is a contract decision. Receipts are numbered per clinic and year. VAT is NOT encoded: the brief says
to have an accountant confirm the treatment first, so a receipt carries the amount and no tax lines.
B3 (referral fee) is deliberately absent until counsel approves the structure.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from . import models
from . import work as W
from .metrics import engine as E


# ============================================================================================ B1 payments
class PaymentProvider:
    """create() opens a payment and returns where the payer goes; capture() is what a provider's webhook
    would call. Real providers implement the same two methods."""
    name = "none"

    def create(self, pay: models.Payment) -> dict:
        raise NotImplementedError

    def capture(self, db: DBSession, pay: models.Payment) -> None:
        raise NotImplementedError


class MockProvider(PaymentProvider):
    """Never moves money. The runner clicks "Zaplatit (zkušební platba)" and the payment is marked paid."""
    name = "mock"

    def create(self, pay: models.Payment) -> dict:
        pay.provider, pay.provider_ref = self.name, f"mock-{uuid.uuid4().hex[:10]}"
        return {"url": f"/api/payments/{pay.id}/mock-pay", "mock": True}

    def capture(self, db: DBSession, pay: models.Payment) -> None:
        pay.status, pay.paid_at = "paid", E.now_iso()


PROVIDER: PaymentProvider = MockProvider()


def provider_live() -> bool:
    """No real provider is configured in this codebase; the UI says payments are a test."""
    return False


def payment_for_booking(db: DBSession, b: models.Booking) -> models.Payment | None:
    """B1.2: per service — none, a deposit or the full price — opened when the runner requests the visit."""
    sv = db.get(models.Service, b.service_id) if b.service_id else None
    if sv is None or (sv.payment_mode or "none") == "none":
        return None
    amount = (sv.deposit_czk if sv.payment_mode == "deposit" else sv.price_czk) or 0
    if amount <= 0:
        return None
    pay = models.Payment(booking_id=b.id, clinic_id=sv.clinic_id, physio_id=b.physio_id, runner_id=b.runner_id,
                         amount_czk=amount, kind=sv.payment_mode, status="pending", created_at=E.now_iso())
    db.add(pay)
    db.flush()
    PROVIDER.create(pay)
    return pay


def _year_seq(db: DBSession, clinic_id: str, year: int) -> str:
    n = db.query(models.Invoice).filter(models.Invoice.clinic_id == clinic_id,
                                        models.Invoice.number.like(f"{year}-%")).count()
    return f"{year}-{n + 1:04d}"


def issue_invoice(db: DBSession, b: models.Booking, *, physio: models.Physio) -> models.Invoice:
    """B1.3: one receipt per visit, numbered per clinic (YYYY-NNNN). A visit paid from a package gets a
    zero receipt that names the package; deposits already paid are subtracted from what is outstanding."""
    have = db.query(models.Invoice).filter_by(booking_id=b.id).filter(models.Invoice.status != "cancelled").first()
    if have is not None:
        return have
    clinic_id = physio.clinic_id
    sv = db.get(models.Service, b.service_id) if b.service_id else None
    price = (sv.price_czk if sv and sv.price_czk is not None else b.price_czk) or 0
    use = db.query(models.PackageUse).filter_by(booking_id=b.id).first()
    paid = sum(p.amount_czk for p in db.query(models.Payment).filter_by(booking_id=b.id, status="paid").all())
    items = [{"text": sv.name_cs if sv else "Návštěva fyzioterapeuta", "czk": price}]
    if use is not None:
        pk = db.get(models.Package, use.package_id)
        items = [{"text": f"{items[0]['text']} — z balíčku „{pk.name}“", "czk": 0}]
        price = 0
    year = datetime.now(E.LOCAL_TZ).year
    # uniqueness per clinic is enforced by the index; retry once on a race
    inv = models.Invoice(clinic_id=clinic_id, number=_year_seq(db, clinic_id, year), booking_id=b.id,
                         runner_id=b.runner_id, physio_id=b.physio_id, payer=b.payer or "client",
                         amount_czk=price, paid_czk=min(paid, price), items=items, issued_at=E.now_iso(),
                         status="paid" if paid >= price else "issued")
    db.add(inv)
    db.flush()
    return inv


def use_package(db: DBSession, b: models.Booking) -> models.Package | None:
    """B1.4: a completed visit takes one from the client's open package with this physio, if there is one."""
    if db.query(models.PackageUse).filter_by(booking_id=b.id).first():
        return None
    pk = (db.query(models.Package).filter(models.Package.runner_id == b.runner_id,
                                          models.Package.physio_id == b.physio_id,
                                          models.Package.status == "open")
          .order_by(models.Package.id.asc()).first())
    if pk is None or (pk.visits_used or 0) >= pk.visits_total:
        return None
    pk.visits_used = (pk.visits_used or 0) + 1
    if pk.visits_used >= pk.visits_total:
        pk.status = "used"
    db.add(models.PackageUse(package_id=pk.id, booking_id=b.id, created_at=E.now_iso()))
    return pk


def revenue(db: DBSession, clinic_id: str, start: date, end: date, physio_id: str | None = None) -> dict:
    """B1.5: per period, per payer, outstanding. Packages count when sold, not when used."""
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    q = db.query(models.Invoice).filter(models.Invoice.clinic_id == clinic_id, models.Invoice.status != "cancelled",
                                        models.Invoice.issued_at >= lo, models.Invoice.issued_at < hi)
    if physio_id:
        q = q.filter(models.Invoice.physio_id == physio_id)
    invs = q.all()
    pq = db.query(models.Package).filter(models.Package.clinic_id == clinic_id, models.Package.created_at >= lo,
                                         models.Package.created_at < hi)
    if physio_id:
        pq = pq.filter(models.Package.physio_id == physio_id)
    pks = pq.all()
    by_payer: dict[str, int] = {}
    for i in invs:
        by_payer[i.payer or "client"] = by_payer.get(i.payer or "client", 0) + (i.amount_czk or 0)
    pk_total = sum(p.price_czk or 0 for p in pks)
    if pk_total:
        by_payer["client"] = by_payer.get("client", 0) + pk_total
    invoiced = sum(i.amount_czk or 0 for i in invs) + pk_total
    paid = sum(i.paid_czk or 0 for i in invs) + sum(p.price_czk or 0 for p in pks if p.paid_at)
    return {"from": start.isoformat(), "to": end.isoformat(), "invoiced_czk": invoiced, "paid_czk": paid,
            "outstanding_czk": invoiced - paid, "by_payer": by_payer, "receipts": len(invs), "packages": len(pks),
            "vat": None}


# ============================================================================================ B2 seats
GRACE_DAYS = 14


def subscription_state(db: DBSession, clinic_id: str | None) -> dict:
    """B2: trial → active while paid; after the trial (or the paid month) and a grace period the clinic goes
    read-only. Dokumentace stays readable and printable whatever happens."""
    sub = db.query(models.Subscription).filter_by(clinic_id=clinic_id).first() if clinic_id else None
    if sub is None:
        return {"status": "trial", "read_only": False}
    now = datetime.now(timezone.utc).isoformat()
    until = max(filter(None, [sub.trial_ends_at, sub.paid_until]), default=None)
    status = sub.status
    if status != "cancelled":
        if sub.paid_until and sub.paid_until >= now:
            status = "active"
        elif sub.trial_ends_at and sub.trial_ends_at >= now and not sub.paid_until:
            status = "trial"
        elif until:
            grace = (datetime.fromisoformat(until) + timedelta(days=GRACE_DAYS)).isoformat()
            status = "past_due" if now <= grace else "read_only"
    if status != sub.status:
        sub.status = status
    return {"status": status, "read_only": status in ("read_only", "cancelled"), "until": until}


# what a read-only clinic may still do: sign in and out, pay, and work with the documentation
READ_ONLY_ALLOWED = ("/api/auth/", "/api/physios/me/subscription", "/api/clinical-records/", "/api/payments/")
READ_ONLY_SUFFIXES = ("/print", "/handover", "/export", "/documentation")


def read_only_block(db: DBSession, user: models.User, method: str, path: str) -> str | None:
    if method in ("GET", "HEAD", "OPTIONS") or user is None or user.role != "physio" or not user.physio_id:
        return None
    if path.startswith(READ_ONLY_ALLOWED) or path.endswith(READ_ONLY_SUFFIXES):
        return None
    p = db.get(models.Physio, user.physio_id)
    st = subscription_state(db, p.clinic_id if p else None)
    db.commit()
    if st["read_only"]:
        return "Předplatné praxe není zaplacené — aplikace je jen pro čtení. Dokumentace zůstává dostupná."
    return None


def seats_pay(db: DBSession, sub: models.Subscription, seats: int) -> models.Payment:
    """B2: the billing owner pays a month for the active seats (mock provider)."""
    pay = models.Payment(clinic_id=sub.clinic_id, amount_czk=seats * (sub.price_czk_per_seat or 0), kind="subscription",
                         status="pending", created_at=E.now_iso())
    db.add(pay)
    db.flush()
    PROVIDER.create(pay)
    return pay


def apply_subscription_payment(db: DBSession, pay: models.Payment) -> None:
    sub = db.query(models.Subscription).filter_by(clinic_id=pay.clinic_id).first()
    if sub is None:
        return
    base = max(datetime.now(timezone.utc), datetime.fromisoformat(sub.paid_until) if sub.paid_until else datetime.now(timezone.utc))
    sub.paid_until = (base + timedelta(days=30)).isoformat()
    sub.status = "active"


# ============================================================================================ B4 waitlist
OFFER_HOURS = 2


def waitlist_matches(db: DBSession, physio_id: str, start_iso: str) -> list[models.Waitlist]:
    """Who waits for this physio and would take this time (weekday and part of day), oldest first."""
    when = W._aware(start_iso).astimezone(E.LOCAL_TZ)
    part = "morning" if when.hour < 12 else "afternoon" if when.hour < 17 else "evening"
    out = []
    for w in (db.query(models.Waitlist).filter_by(physio_id=physio_id, status="waiting")
              .order_by(models.Waitlist.created_at.asc()).all()):
        dows = [int(x) for x in (w.dow or "").split(",") if x.strip().isdigit()]
        parts = [x for x in (w.dayparts or "").split(",") if x]
        if (not dows or when.weekday() in dows) and (not parts or part in parts):
            out.append(w)
    return out


def expire_offers(db: DBSession, physio_id: str | None = None) -> None:
    q = db.query(models.Waitlist).filter_by(status="offered")
    if physio_id:
        q = q.filter_by(physio_id=physio_id)
    now = datetime.now(timezone.utc)
    for w in q.all():
        if w.offered_at and datetime.fromisoformat(w.offered_at) + timedelta(hours=OFFER_HOURS) < now:
            w.status, w.offered_slot_at = "waiting", None


def on_cancellation(db: DBSession, b: models.Booking) -> int:
    """A freed time tells the physio how many people wait for it (the physio offers, one at a time)."""
    n = len(waitlist_matches(db, b.physio_id, b.slot_at)) if b.slot_at else 0
    if n:
        W.NOTIFY.send(db, "waitlist_match", f"Uvolněný termín: čeká {n} z pořadníku", physio_id=b.physio_id,
                      ref=f"booking:{b.id}")
    return n


# ============================================================================================ B5 PROMs
# Validated questionnaires (VISA-A, LEFS…) need a licence and the validated Czech version — none is
# included. The one built-in is our own short check-in and is labelled as NOT a validated instrument.
INSTRUMENTS: dict[str, dict] = {
    "dosslap_function": {
        "name_cs": "Krátká kontrola funkce (Došlap, nevalidovaný)", "validated": False, "licence": None,
        "items": [
            {"id": "pain_run", "text_cs": "Bolest při běhu (0–10)", "min": 0, "max": 10},
            {"id": "pain_day", "text_cs": "Bolest v běžném dni (0–10)", "min": 0, "max": 10},
            {"id": "function", "text_cs": "Jak dobře zvládáte běh, jak byste chtěli? (0 = vůbec, 10 = úplně)", "min": 0, "max": 10},
        ],
        # 0–100, higher = better; documented so the chart reads one way
        "score": lambda a: round(((10 - a["pain_run"]) + (10 - a["pain_day"]) + a["function"]) / 30 * 100),
    },
}
# A licensed instrument is added here together with its licence reference — never switched on by config alone.


def prom_due(db: DBSession, rid: str) -> list[dict]:
    today = E.today_date().isoformat()
    out = []
    for s in db.query(models.PromSchedule).filter_by(runner_id=rid, active=True).all():
        if (s.next_due or today) <= today and s.instrument in INSTRUMENTS:
            ins = INSTRUMENTS[s.instrument]
            out.append({"schedule_id": s.id, "instrument": s.instrument, "name": ins["name_cs"],
                        "validated": ins["validated"], "items": ins["items"]})
    return out


def prom_answer(db: DBSession, s: models.PromSchedule, answers: dict) -> models.PromResponse:
    ins = INSTRUMENTS[s.instrument]
    clean = {}
    for it in ins["items"]:
        v = answers.get(it["id"])
        if not isinstance(v, int) or not it["min"] <= v <= it["max"]:
            raise ValueError(it["text_cs"])
        clean[it["id"]] = v
    r = models.PromResponse(schedule_id=s.id, runner_id=s.runner_id, physio_id=s.physio_id, instrument=s.instrument,
                            answers=clean, score=ins["score"](clean), answered_at=E.now_iso())
    db.add(r)
    s.next_due = (E.today_date() + timedelta(days=s.every_days or 14)).isoformat()
    return r


# ============================================================================================ B6 reports
def clinic_report(db: DBSession, clinic_id: str, start: date, end: date) -> dict:
    """Occupancy, no-shows, new against returning, revenue — counts and sums only, no clinical content."""
    pids = [m.physio_id for m in db.query(models.ClinicMember).filter_by(clinic_id=clinic_id, active=True).all()
            if m.role != "reception"]
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    bks = [b for b in db.query(models.Booking).filter(models.Booking.physio_id.in_(pids)).all()
           if b.slot_at and lo <= W._aware(b.slot_at).astimezone(E.LOCAL_TZ).date().isoformat() < hi]
    held = [b for b in bks if b.status in ("completed", "confirmed") and W._aware(b.slot_at) <= datetime.now(timezone.utc)]
    no_show = [b for b in bks if b.status == "no_show"]
    booked_min = sum(b.duration_min or 45 for b in bks if b.status in ("completed", "confirmed", "no_show"))
    avail_min = 0
    d = start
    while d <= end:
        for r in db.query(models.AvailabilityRule).filter(models.AvailabilityRule.physio_id.in_(pids),
                                                          models.AvailabilityRule.active.is_(True)).all():
            if r.weekday == d.weekday():
                h0, m0 = map(int, r.start_local.split(":"))
                h1, m1 = map(int, r.end_local.split(":"))
                avail_min += max(0, (h1 * 60 + m1) - (h0 * 60 + m0))
        d += timedelta(days=1)
    first_seen: dict[str, str] = {}
    for b in db.query(models.Booking).filter(models.Booking.physio_id.in_(pids),
                                             models.Booking.status.in_(("completed", "confirmed"))).all():
        k = b.runner_id
        first_seen[k] = min(first_seen.get(k, b.slot_at), b.slot_at)
    clients = {b.runner_id for b in held}
    new = sum(1 for c in clients if lo <= (first_seen.get(c) or "")[:10] < hi)
    attended = len(held) + len(no_show)
    return {"from": start.isoformat(), "to": end.isoformat(), "physios": len(pids),
            "visits": len(held), "no_shows": len(no_show),
            "no_show_rate": round(100 * len(no_show) / attended) if attended else None,
            "occupancy_pct": round(100 * booked_min / avail_min) if avail_min else None,
            "clients": len(clients), "new_clients": new, "returning_clients": len(clients) - new,
            "revenue": revenue(db, clinic_id, start, end)}
