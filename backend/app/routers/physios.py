"""Physio-scoped bootstrap for the practitioner-level views (calendar,
programs, candidates) in physio.html — self only. The triage *queue* itself
stays on GET /api/triage (platform-wide, see triage.py); this covers what's
specifically "mine": my bookings, my programs, my claimed-but-not-yet-
programmed candidates.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/physios", tags=["physios"])


@router.get("/{pid}/bootstrap")
def bootstrap(pid: str, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if user.physio_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto profilu")
    physio = db.query(models.Physio).filter(models.Physio.id == pid).first()
    if not physio:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")

    def _with_runner_and_assessment(row, runner_id):
        out = to_dict(row)
        r = db.query(models.Runner).filter(models.Runner.id == runner_id).first()
        out["runner"] = to_dict(r)
        a = db.query(models.Assessment).filter(models.Assessment.runner_id == runner_id).first()
        out["assessment"] = E.assessment_row_to_dict(a)
        return out

    conclusions = db.query(models.Conclusion).filter(models.Conclusion.physio_id == pid).all()
    concl_by_booking = {c.booking_id: c for c in conclusions}

    bookings = db.query(models.Booking).filter(models.Booking.physio_id == pid).order_by(models.Booking.slot_at.asc()).all()
    bookings_out = []
    for b in bookings:
        item = _with_runner_and_assessment(b, b.runner_id)
        c = concl_by_booking.get(b.id)
        item["conclusion"] = to_dict(c) if c else None
        bookings_out.append(item)

    programs = db.query(models.Program).filter(models.Program.physio_id == pid).order_by(models.Program.id.desc()).all()
    programs_out = []
    for p in programs:
        item = _with_runner_and_assessment(p, p.runner_id)
        item["exercises"] = to_dicts(db.query(models.Exercise).filter(models.Exercise.program_id == p.id).all())
        item["revision_count"] = db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == p.id).count()
        programs_out.append(item)
    programmed_runner_ids = {p.runner_id for p in programs}

    triage_mine = (
        db.query(models.Triage).filter(models.Triage.claimed_by == pid, models.Triage.status != "closed").all()
    )
    triage_out = []
    for t in triage_mine:
        item = _with_runner_and_assessment(t, t.runner_id)
        ci = (
            db.query(models.Checkin).filter(models.Checkin.runner_id == t.runner_id)
            .order_by(models.Checkin.submitted_at.desc()).first()
        )
        item["checkin_latest"] = to_dict(ci)
        item["has_program"] = t.runner_id in programmed_runner_ids
        triage_out.append(item)

    requests = (
        db.query(models.Booking)
        .filter(models.Booking.physio_id == pid, models.Booking.status == "requested")
        .order_by(models.Booking.slot_at.asc()).all()
    )
    requests_out = [_with_runner_and_assessment(b, b.runner_id) for b in requests]
    slots = (
        db.query(models.PhysioSlot)
        .filter(models.PhysioSlot.physio_id == pid, models.PhysioSlot.slot_at > E.now_iso())
        .order_by(models.PhysioSlot.slot_at.asc()).all()
    )
    from ..routers.booking import due_reminders
    reminders = due_reminders(db, physio_id=pid)

    return {
        "physio": to_dict(physio), "bookings": bookings_out, "programs": programs_out, "triage_mine": triage_out,
        "requests": requests_out, "slots": to_dicts(slots), "reminders": reminders,
    }


# ---------------------------------------------------------------- the physio app (owner request 2026-10-27)
# Report v6, Section 6.2.7–6.2.8: the physio application follows a client's case — the queue,
# the calendar, the client overview before a visit, the programme and the return to running,
# the conclusion after it. These endpoints give the React app (frontend/src/physio) one call per
# screen; every read stays behind the care assignment (deps.has_care_assignment) and lands in the
# runner's access log (main.audit_access covers /api/runners/... only, so it is written here).
from datetime import date, timedelta

from pydantic import Field

from .. import schemas
from ..deps import has_care_assignment, verify_csrf


def _pid(user: models.User) -> str:
    if not user.physio_id:
        raise HTTPException(status_code=403, detail="Účet není fyzioterapeut")
    return user.physio_id


def _log_read(db: DBSession, rid: str, pid: str, resource: str) -> None:
    from ..main import _record_access
    _record_access(db, rid, pid, "GET", resource)


def _profile_out(db: DBSession, p: models.Physio, user: models.User) -> dict:
    clinic = db.get(models.Clinic, p.clinic_id) if p.clinic_id else None
    return {"id": p.id, "name": p.name, "credential": p.credential, "bio": p.bio, "years_exp": p.years_exp,
            "specialties": p.specialties or [], "price_czk": p.price_czk, "rating": p.rating,
            "clinic": {"id": clinic.id, "name": clinic.name, "city": clinic.city} if clinic else None,
            "email": user.email, "complete": bool(p.credential and clinic and clinic.city)}


@router.get("/me")
def my_profile(user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    p = db.get(models.Physio, _pid(user))
    if p is None:
        raise HTTPException(status_code=404, detail="Fyzioterapeut nenalezen")
    return _profile_out(db, p, user)


class PhysioProfileIn(schemas.Lenient):
    name: str | None = Field(default=None, max_length=120)
    credential: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=800)
    years_exp: int | None = Field(default=None, ge=0, le=60)
    specialties: list[str] | None = Field(default=None, max_length=12)
    price_czk: int | None = Field(default=None, ge=0, le=20000)
    clinic_name: str | None = Field(default=None, max_length=160)
    clinic_city: str | None = Field(default=None, max_length=80)


@router.patch("/me", dependencies=[Depends(verify_csrf)])
def update_profile(body: PhysioProfileIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """The physio's own card the runners pick from (Care tab) and the clinic whose city sets the
    region of the case queue (triage._physio_region)."""
    p = db.get(models.Physio, _pid(user))
    for k in ("name", "credential", "bio", "years_exp", "price_czk"):
        v = getattr(body, k)
        if v is not None:
            setattr(p, k, v.strip() if isinstance(v, str) else v)
    if body.specialties is not None:
        p.specialties = [s.strip()[:40] for s in body.specialties if s.strip()]
    if body.clinic_name or body.clinic_city:
        clinic = db.get(models.Clinic, p.clinic_id) if p.clinic_id else None
        if clinic is None:
            clinic = models.Clinic(id=f"cli_{p.id}", name=(body.clinic_name or "Praxe").strip())
            db.add(clinic)
            p.clinic_id = clinic.id
        if body.clinic_name:
            clinic.name = body.clinic_name.strip()
        if body.clinic_city is not None:
            clinic.city = body.clinic_city.strip()
    if body.name:
        user.name = body.name.strip()
    db.commit()
    return _profile_out(db, p, user)


def _a_summary(a: dict | None) -> dict:
    a = a or {}
    sig = sorted(a.get("signals") or [], key=lambda s: -(s.get("pts") or 0))
    ps = a.get("painState") or {}
    rd = a.get("readiness") or {}
    return {"overall": a.get("overall"), "quadrant": a.get("quadrant"), "tier": a.get("tier"),
            "readiness": rd.get("score") if isinstance(rd, dict) else None,
            "signal": ({"name": sig[0].get("name"), "grade": sig[0].get("grade"), "val": sig[0].get("val")} if sig else None),
            "todayPain": ps.get("todayPain"), "lastPainDay": ps.get("lastPainDay")}


@router.get("/me/clients")
def my_clients(user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Everyone in my care, the most urgent first: state, pain, next visit, programme adherence,
    the return to running and the last message."""
    pid = _pid(user)
    rows = db.query(models.CareAssignment).filter(models.CareAssignment.physio_id == pid,
                                                  models.CareAssignment.status == "active").all()
    now = E.now_iso()
    since = E.iso_date(E.today_date() - timedelta(days=3))
    out = []
    for ca in rows:
        rid = ca.runner_id
        r = db.get(models.Runner, rid)
        if r is None:
            continue
        a_row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
        a = _a_summary(E.assessment_row_to_dict(a_row) if a_row else None)
        ci = (db.query(models.Checkin).filter(models.Checkin.runner_id == rid)
              .order_by(models.Checkin.submitted_at.desc()).first())
        nxt = (db.query(models.Booking).filter(models.Booking.runner_id == rid, models.Booking.physio_id == pid,
                                               models.Booking.status.in_(("confirmed", "requested")),
                                               models.Booking.slot_at >= now[:16])
               .order_by(models.Booking.slot_at.asc()).first())
        prog = (db.query(models.Program).filter(models.Program.runner_id == rid, models.Program.active.is_(True))
                .order_by(models.Program.id.desc()).first())
        adher = None
        if prog is not None:
            ex = db.query(models.Exercise).filter(models.Exercise.program_id == prog.id).all()
            tgt = sum(e.target_count or 0 for e in ex)
            adher = round(100 * sum(e.done_count or 0 for e in ex) / tgt) if tgt else None
        rtr = (db.query(models.ReturnToRun).filter(models.ReturnToRun.runner_id == rid,
                                                    models.ReturnToRun.status != "completed").first())
        msg = (db.query(models.Message).filter(models.Message.runner_id == rid)
               .order_by(models.Message.created_at.desc()).first())
        pain_recent = bool(ci and (ci.pain_score or 0) >= 4 and (ci.submitted_at or "") >= since)
        setback = bool(msg and msg.sender == "system" and "bolest" in (msg.body or "") and (msg.created_at or "") >= since)
        attention = [x for x, on in (("pain", pain_recent), ("alert", a.get("tier") == "alert"), ("setback", setback),
                                     ("message", bool(msg and msg.sender == "runner"))) if on]
        out.append({
            "runnerId": rid, "name": r.name, "city": r.city, "since": ca.created_at, "a": a,
            "checkin": {"at": ci.submitted_at, "pain": ci.pain_score, "site": ci.pain_site} if ci else None,
            "next": {"id": nxt.id, "at": nxt.slot_at, "kind": nxt.kind, "status": nxt.status} if nxt else None,
            "program": {"id": prog.id, "name": prog.name, "status": prog.status, "adherence": adher} if prog else None,
            "rtr": {"level": rtr.current_level, "levels": len(rtr.levels_json or []), "status": rtr.status} if rtr else None,
            "lastMessage": {"sender": msg.sender, "at": msg.created_at, "body": (msg.body or "")[:120]} if msg else None,
            "attention": attention,
        })
    out.sort(key=lambda x: (-len(x["attention"]), -(x["a"].get("overall") or 0)))
    return {"items": out}


def _weeks_km(acts: list, today: date, n: int = 12) -> list:
    monday = today - timedelta(days=today.weekday())
    out = []
    for k in range(n - 1, -1, -1):
        ws = monday - timedelta(weeks=k)
        we = ws + timedelta(days=7)
        km = sum(a.distance_km or 0 for a in acts if (a.sport or "running") == "running"
                 and ws.isoformat() <= (a.started_at or "")[:10] < we.isoformat())
        out.append({"week": ws.isoformat(), "km": round(km, 1)})
    return out


@router.get("/me/clients/{rid}")
def client_overview(rid: str, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """The client overview before a visit (report Figure A9): the history, the symptom record and
    the data trends; the AI summary comes separately (POST /api/ai/brief) because it can be slow."""
    pid = _pid(user)
    if not has_care_assignment(db, pid, rid):
        raise HTTPException(status_code=403, detail="Klienta nejdřív převezměte z fronty nebo potvrďte jeho termín.")
    r = db.get(models.Runner, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="Běžec nenalezen")
    _log_read(db, rid, pid, "přehled klienta")
    a = E.get_or_refresh_assessment(db, rid)
    today = E.today_date()
    u = db.query(models.User).filter(models.User.runner_id == rid).first()
    st = db.query(models.Settings).filter(models.Settings.user_id == u.id).first() if u else None
    share = True if st is None or st.share_with_physio is None else bool(st.share_with_physio)
    acts = (db.query(models.Activity).filter(models.Activity.runner_id == rid,
                                             models.Activity.started_at >= E.iso_date(today - timedelta(weeks=12)))
            .order_by(models.Activity.started_at.desc()).all())
    fb = {f.activity_id: f for f in db.query(models.ActivityFeedback).filter(
        models.ActivityFeedback.runner_id == rid, models.ActivityFeedback.activity_id.in_([x.id for x in acts[:20]])).all()} if acts else {}
    cis = (db.query(models.Checkin).filter(models.Checkin.runner_id == rid,
                                           models.Checkin.submitted_at >= E.iso_date(today - timedelta(days=42)))
           .order_by(models.Checkin.submitted_at.asc()).all())
    inj = (db.query(models.InjuryReport).filter(models.InjuryReport.runner_id == rid)
           .order_by(models.InjuryReport.submitted_at.desc()).limit(8).all())
    bks = (db.query(models.Booking).filter(models.Booking.runner_id == rid, models.Booking.physio_id == pid)
           .order_by(models.Booking.slot_at.desc()).all())
    concl = {c.booking_id: c for c in db.query(models.Conclusion).filter(models.Conclusion.runner_id == rid,
                                                                          models.Conclusion.physio_id == pid).all()}
    rtr = (db.query(models.ReturnToRun).filter(models.ReturnToRun.runner_id == rid)
           .order_by(models.ReturnToRun.id.desc()).first())
    from .rtr import _plan_dict
    sig = sorted(a.get("signals") or [], key=lambda s: -(s.get("pts") or 0))
    age = (today.year - r.birth_year) if r.birth_year else None
    return {
        "runner": {"id": rid, "name": r.name, "age": age, "sex": r.sex, "city": r.city, "weight_kg": r.weight_kg,
                   "running_since": r.running_since, "device": r.device, "goal_race": r.goal_race, "goal_date": r.goal_date,
                   "prior_injury": r.prior_injury, "prior_injury_date": r.prior_injury_date,
                   "prior_injury_side": r.prior_injury_side, "physio_interest": bool(r.physio_interest)},
        "share": share,
        "a": {**_a_summary(a), "signals": [{k: s.get(k) for k in ("id", "name", "grade", "pts", "val", "detail", "axis")}
                                          for s in sig[:6]],
              "painState": a.get("painState"), "load": (a.get("load") or {}).get("score") if isinstance(a.get("load"), dict) else a.get("load"),
              "mech": (a.get("mech") or {}).get("score") if isinstance(a.get("mech"), dict) else a.get("mech"),
              "symp": (a.get("symp") or {}).get("score") if isinstance(a.get("symp"), dict) else a.get("symp"),
              "guidance": {k: (a.get("guidance") or {}).get(k) for k in ("type", "typeLabel", "reasons")}},
        "weeks": _weeks_km(acts, today) if share else [],
        "activities": [{"id": x.id, "date": x.started_at, "title": x.title, "sport": x.sport or "running",
                        "km": x.distance_km, "min": x.duration_min, "hr": x.avg_hr,
                        "rpe": (fb.get(x.id).rpe if fb.get(x.id) else None) or x.rpe,
                        "pain": fb.get(x.id).pain_during if fb.get(x.id) else None} for x in acts[:14]] if share else [],
        "checkins": [{"date": c.submitted_at[:10], "pain": c.pain_score, "site": c.pain_site, "soreness": c.soreness,
                      "limits": c.limits_movement, "modified": c.run_modified, "note": c.notes} for c in cis],
        "injuries": [{"at": i.submitted_at, "source": i.source, "status": i.status, "severity": i.severity,
                      "region": i.body_region, "side": i.body_side, "confirmed": bool(i.confirmed)} for i in inj],
        "bookings": [{"id": b.id, "at": b.slot_at, "kind": b.kind, "status": b.status, "prep_info": b.prep_info,
                      "conclusion": ({"id": concl[b.id].id, "status": concl[b.id].status} if b.id in concl else None)}
                     for b in bks],
        "rtr": _plan_dict(db, rtr) if rtr else None,
    }


@router.get("/me/clients/{rid}/documentation")
def documentation(rid: str, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """Standardised client documentation (report Figure A11): the approved conclusions with the
    structured outcome, in date order — the printable record a practice keeps."""
    pid = _pid(user)
    if not has_care_assignment(db, pid, rid):
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto klientovi")
    _log_read(db, rid, pid, "dokumentace")
    r = db.get(models.Runner, rid)
    p = db.get(models.Physio, pid)
    rows = (db.query(models.Conclusion).filter(models.Conclusion.runner_id == rid, models.Conclusion.physio_id == pid,
                                               models.Conclusion.status == "approved")
            .order_by(models.Conclusion.approved_at.asc()).all())
    bk = {b.id: b for b in db.query(models.Booking).filter(models.Booking.id.in_([c.booking_id for c in rows])).all()} if rows else {}
    return {"runner": {"name": r.name if r else rid, "birth_year": r.birth_year if r else None, "sex": r.sex if r else None},
            "physio": _profile_out(db, p, user),
            "visits": [{"at": (bk.get(c.booking_id).slot_at if bk.get(c.booking_id) else c.created_at),
                        "kind": bk.get(c.booking_id).kind if bk.get(c.booking_id) else None,
                        "summary": c.summary, "finding": c.finding, "approved_at": c.approved_at,
                        "outcome": ({"severity": c.out_severity, "region": c.out_region, "side": c.out_side,
                                     "participation": c.out_participation, "volume": c.out_volume,
                                     "performance": c.out_performance, "pain": c.out_pain} if c.has_outcome else None)}
                       for c in rows],
            "generated_at": E.now_iso()}
