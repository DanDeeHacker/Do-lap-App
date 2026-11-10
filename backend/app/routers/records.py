"""The physio's documentation (physio brief 2026-11-09, Phase 1): provider identity (R1), the patient card
(R2), care episodes (R3), the ledger's documentation view, corrections and addenda (R5/R6), activity history
(R7), unsigned records (R8), printout, handover and export (R9), recording consent (R10), retention and
destruction (R11) and what stays after the client withdraws consent (R13)."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from .. import models
from .. import records as R
from ..db import get_db
from ..deps import ensure_runner_self, get_current_user, has_care_assignment, require_verified_physio, verify_csrf
from ..metrics import engine as E

router = APIRouter(tags=["records"])


class Open(BaseModel):
    model_config = {"extra": "ignore"}


def _physio(db: DBSession, user: models.User) -> models.Physio:
    p = db.get(models.Physio, user.physio_id)
    if p is None:
        raise HTTPException(status_code=403, detail="Účet fyzioterapeuta nenalezen")
    return p


def doc_access(db: DBSession, physio: models.Physio, rid: str) -> tuple[models.PatientRecord | None, bool]:
    """Live care, or (R13) documentation only: a client who withdrew consent leaves the provider the records
    it must keep by law, nothing else."""
    from .. import work as W
    if not W.can(db, physio.id, "clinical"):          # W1: reception never reads clinical records
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto klientovi")
    clinic = R.clinic_of(db, physio)
    card = R.card(db, clinic.id, rid)
    live = has_care_assignment(db, physio.id, rid)
    if live:
        return card, True
    if card is not None and db.query(models.ClinicalRecord.id).filter_by(patient_record_id=card.id).first():
        return card, False
    raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto klientovi")


# ---- R1 Praxe: provider identity ---------------------------------------------------------------------------
class PracticeIn(Open):
    legal_name: str | None = None
    legal_form: str | None = None
    ico: str | None = None
    registered_street: str | None = None
    registered_city: str | None = None
    registered_postal_code: str | None = None
    care_site_street: str | None = None
    care_site_city: str | None = None
    care_site_postal_code: str | None = None
    title: str | None = None
    qualification: str | None = None
    hcp_identifier: str | None = None
    confirm: bool = False


CLINIC_FIELDS = ("legal_name", "legal_form", "ico", "registered_street", "registered_city", "registered_postal_code",
                 "care_site_street", "care_site_city", "care_site_postal_code")


def practice_out(c: models.Clinic, p: models.Physio) -> dict:
    return {"clinic": {"id": c.id, "name": c.name, "is_solo": bool(c.is_solo), **{k: getattr(c, k) for k in CLINIC_FIELDS},
                       "confirmed_at": c.provider_details_confirmed_at},
            "physio": {"title": p.title, "qualification": p.qualification, "hcp_identifier": p.hcp_identifier,
                       "credential": p.credential},
            "missing": R.provider_missing(c)}


@router.get("/api/physios/me/practice")
def get_practice(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    c = R.clinic_of(db, p)
    db.commit()
    return practice_out(c, p)


@router.put("/api/physios/me/practice", dependencies=[Depends(verify_csrf)])
def put_practice(body: PracticeIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    c = R.clinic_of(db, p)
    given = body.model_fields_set
    if body.ico is not None and body.ico.strip() and not (body.ico.strip().isdigit() and len(body.ico.strip()) == 8):
        raise HTTPException(status_code=422, detail="IČO má 8 číslic.")
    changed = []
    for k in CLINIC_FIELDS:
        if k in given:
            setattr(c, k, (getattr(body, k) or "").strip() or None)
            changed.append(k)
    for k in ("title", "qualification", "hcp_identifier"):
        if k in given:
            setattr(p, k, (getattr(body, k) or "").strip() or None)
            changed.append(k)
    if body.confirm:
        if R.provider_missing(c):
            raise HTTPException(status_code=422, detail="Doplňte název, IČO a adresu místa poskytování.")
        c.provider_details_confirmed_at = E.now_iso()
    R.physio_event(db, p, "update", "practice", c.id, detail={"fields": changed})
    db.commit()
    return practice_out(c, p)


# ---- R2 patient card ---------------------------------------------------------------------------------------
class CardIn(Open):
    first_name: str | None = None
    last_name: str | None = None
    birth_date: str | None = None
    sex_at_birth: str | None = None
    rodne_cislo: str | None = None
    insurance_no: str | None = None
    insurer_code: str | None = None
    id_doc_type: str | None = None
    id_doc_no: str | None = None
    permanent_street: str | None = None
    permanent_city: str | None = None
    permanent_postal_code: str | None = None
    delivery_street: str | None = None
    delivery_city: str | None = None
    delivery_postal_code: str | None = None
    phone: str | None = None
    email: str | None = None
    gp_name: str | None = None
    gp_contact: str | None = None
    legal_representative: dict | None = None
    anamnesis: str | None = None
    red_flags: list | None = None


@router.get("/api/physios/me/clients/{rid}/card")
def get_card(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    card, live = doc_access(db, p, rid)
    r = db.get(models.Runner, rid)
    if card is None:
        db.commit()
        return {"id": None, "prefill": R.card_prefill(r) if r else {}, "missing": list(R.PATIENT_REQUIRED),
                "crypto": R.crypto_on(), "live": live}
    R.physio_event(db, p, "read", "patient_card", card.id, runner_id=rid)
    db.commit()
    return {**R.card_out(card, r if live else None), "live": live}


@router.put("/api/physios/me/clients/{rid}/card", dependencies=[Depends(verify_csrf)])
def put_card(rid: str, body: CardIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    card, live = doc_access(db, p, rid)
    clinic = R.clinic_of(db, p)
    r = db.get(models.Runner, rid)
    created = card is None
    if card is None:
        if not live:
            raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto klientovi")
        card = models.PatientRecord(id=R.new_record_id(), clinic_id=clinic.id, runner_id=rid, first_name="", last_name="",
                                    created_at=E.now_iso())
        db.add(card)
    given = body.model_fields_set
    if body.birth_date:
        try:
            if date.fromisoformat(body.birth_date) > E.today_date():
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=422, detail="Datum narození není platné.")
    if body.sex_at_birth not in (None, "", "f", "m"):
        raise HTTPException(status_code=422, detail="Pohlaví při narození: žena nebo muž.")
    changed = []
    for k in (*R.CARD_FIELDS, "anamnesis", "red_flags"):
        if k in given:
            v = getattr(body, k)
            setattr(card, k, v.strip() if isinstance(v, str) else v)
            changed.append(k)
    for f in R.ENC_FIELDS:
        if f in given:
            if not R.crypto_on():
                raise HTTPException(status_code=409, detail="Šifrování citlivých údajů není nastavené — pole nelze uložit.")
            setattr(card, f"{f}_enc", R.encrypt((getattr(body, f) or "").strip() or None))
            changed.append(f)
    if r is not None and live:
        card.source_snapshot = R.runner_snapshot(r)
    card.updated_at = E.now_iso()
    card.incomplete = 1 if R.patient_missing(card) else 0      # round 2 F2.1
    db.flush()
    R.physio_event(db, p, "create" if created else "update", "patient_card", card.id, runner_id=rid,
                   detail={"fields": changed})
    ep = R.episode_for(db, p.id, rid, create=False)
    if ep is not None and ep.patient_record_id is None:
        ep.patient_record_id = card.id
    db.commit()
    return R.card_out(card, r)


# ---- R3 episodes and diagnoses -----------------------------------------------------------------------------
def _ep_out(ep: models.CareEpisode) -> dict:
    return {k: getattr(ep, k) for k in ("id", "region", "side", "diagnosis_code", "diagnosis_label", "onset_date",
                                         "opened_at", "closed_at", "status", "discharge_outcome", "return_to_run_date",
                                         "closing_note")}


@router.get("/api/physios/me/clients/{rid}/episodes")
def list_episodes(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    doc_access(db, p, rid)
    rows = (db.query(models.CareEpisode).filter_by(physio_id=p.id, runner_id=rid)
            .order_by(models.CareEpisode.id.desc()).all())
    return {"items": [_ep_out(e) for e in rows]}


class EpisodeIn(Open):
    region: str | None = None
    side: str | None = None
    diagnosis_code: str | None = None
    diagnosis_label: str | None = None
    onset_date: str | None = None


def _own_episode(db, p, eid) -> models.CareEpisode:
    ep = db.get(models.CareEpisode, eid)
    if ep is None or ep.physio_id != p.id:
        raise HTTPException(status_code=404, detail="Epizoda nenalezena")
    return ep


@router.patch("/api/episodes/{eid}", dependencies=[Depends(verify_csrf)])
def edit_episode(eid: int, body: EpisodeIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    ep = _own_episode(db, p, eid)
    from .. import regions as REG
    if body.region and body.region not in REG.LABEL:
        raise HTTPException(status_code=422, detail="Oblast vyberte ze seznamu")
    if body.side not in (None, "", "L", "P", "both"):
        raise HTTPException(status_code=422, detail="Strana: L, P nebo obě")
    if body.diagnosis_code and db.get(models.DiagnosisCode, body.diagnosis_code) is None \
            and db.query(models.DiagnosisCode.code).first() is not None:
        raise HTTPException(status_code=422, detail="Kód MKN-10 není v číselníku.")
    for k in body.model_fields_set:
        setattr(ep, k, getattr(body, k) or None)
    R.physio_event(db, p, "update", "episode", ep.id, runner_id=ep.runner_id, detail={"fields": sorted(body.model_fields_set)})
    db.commit()
    return _ep_out(ep)


class DischargeIn(Open):
    outcome: str
    return_to_run_date: str | None = None
    note: str = ""


@router.post("/api/episodes/{eid}/close", dependencies=[Depends(verify_csrf)])
def close_episode(eid: int, body: DischargeIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R3.4: Ukončit péči — the outcome, the return date and a closing note; it writes a discharge record."""
    p = _physio(db, user)
    ep = _own_episode(db, p, eid)
    if ep.status != "open":
        raise HTTPException(status_code=409, detail="Epizoda už je ukončená.")
    if body.outcome not in ("returned_full", "returned_reduced", "referred", "stopped"):
        raise HTTPException(status_code=422, detail="Vyberte výsledek péče.")
    clinic = R.clinic_of(db, p)
    if R.provider_missing(clinic):
        raise HTTPException(status_code=409, detail="Před prvním záznamem doplňte údaje poskytovatele v Praxi.")
    card = db.get(models.PatientRecord, ep.patient_record_id) if ep.patient_record_id else R.card(db, clinic.id, ep.runner_id)
    if R.patient_missing(card):
        raise HTTPException(status_code=409, detail="Doplňte identifikační údaje klienta.")
    ep.status, ep.closed_at = "discharged", E.now_iso()
    ep.discharge_outcome, ep.return_to_run_date, ep.closing_note = body.outcome, body.return_to_run_date, body.note
    rec = R.write_record(db, clinic=clinic, patient=card, author=p, kind="discharge", encounter_at=E.now_iso(),
                         content={"episode": _ep_out(ep)}, episode_id=ep.id)
    R.physio_event(db, p, "close", "episode", ep.id, runner_id=ep.runner_id, detail={"record_id": rec.id, "outcome": body.outcome})
    _schedule_followup(db, ep)
    db.commit()
    return {**_ep_out(ep), "record_id": rec.id}


def _schedule_followup(db: DBSession, ep: models.CareEpisode) -> None:
    """M1: a discharge schedules a 3-month check in the runner app (outcome labels for calibration)."""
    if not ep.runner_id:
        return
    from datetime import timedelta
    due = (E.today_date() + timedelta(days=91)).isoformat()
    db.add(models.OutcomeFollowup(episode_id=ep.id, runner_id=ep.runner_id, due_on=due, status="scheduled",
                                  created_at=E.now_iso()))


@router.get("/api/diagnoses")
def search_diagnoses(q: str = "", user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R3.3: the imported MKN-10 list. Empty until the official ÚZIS file is imported."""
    qs = db.query(models.DiagnosisCode)
    if q:
        like = f"%{q.strip()}%"
        qs = qs.filter((models.DiagnosisCode.code.ilike(like)) | (models.DiagnosisCode.label.ilike(like)))
    rows = qs.order_by(models.DiagnosisCode.running_shortlist.desc(), models.DiagnosisCode.code).limit(30).all()
    return {"items": [{"code": d.code, "label": d.label, "shortlist": bool(d.running_shortlist)} for d in rows],
            "imported": db.query(models.DiagnosisCode.code).first() is not None}


# ---- R5/R6/R9 documentation --------------------------------------------------------------------------------
def _version_out(db: DBSession, rec: models.ClinicalRecord) -> dict:
    vs = R.versions(db, rec.id)
    cur = vs[-1]
    addenda = (db.query(models.ClinicalRecord).filter_by(corrects_record_id=rec.id, kind="addendum")
               .order_by(models.ClinicalRecord.created_at).all())
    body = R.content_of(rec)
    return {"id": rec.id, "kind": rec.kind, "encounter_at": rec.encounter_at, "episode_id": rec.episode_id,
            # round 2 F2.7: notes brought in from before the ledger, and what the backfill flagged
            "legacy": bool(body.get("legacy")), "flags": body.get("flags") or [],
            "booking_id": rec.booking_id, "current_id": cur.id, "current": R.content_of(cur)["content"],
            "author": rec.author_name, "author_identifier": rec.author_identifier, "authorised_at": rec.authorised_at,
            "corrections": [{"id": v.id, "at": v.authorised_at, "by": v.author_name, "reason": v.correction_reason,
                             "at_patient_request": bool(v.at_patient_request)} for v in vs[1:]],
            "original": R.content_of(rec)["content"] if len(vs) > 1 else None,
            "addenda": [{"id": a.id, "at": a.authorised_at, "by": a.author_name,
                         "text": R.content_of(a)["content"].get("text")} for a in addenda]}


@router.get("/api/physios/me/clients/{rid}/documentation")
def documentation(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    card, live = doc_access(db, p, rid)
    clinic = R.clinic_of(db, p)
    roots = []
    if card is not None:
        roots = (db.query(models.ClinicalRecord)
                 .filter(models.ClinicalRecord.patient_record_id == card.id,
                         models.ClinicalRecord.kind.in_(("visit_note", "discharge")))
                 .order_by(models.ClinicalRecord.encounter_at.asc()).all())
    R.physio_event(db, p, "read", "documentation", card.id if card else rid, runner_id=rid)
    events = (db.query(models.RecordEvent).filter_by(runner_id=rid).order_by(models.RecordEvent.id.desc()).limit(60).all())
    db.commit()
    return {"live": live,
            "banner": None if live else "Klient odvolal sdílení dat. Vidíte pouze zdravotnickou dokumentaci.",
            "provider": R.provider_snapshot(clinic), "provider_missing": R.provider_missing(clinic),
            "author": R.author_snapshot(p),
            "patient": R.patient_snapshot(card) if card else None,
            "patient_missing": R.patient_missing(card),
            "records": [_version_out(db, r) for r in roots],
            "access": [_event_out(e) for e in events],
            "can_send_electronically": SIGNING.configured(),
            "generated_at": E.now_iso()}


class CorrectionIn(Open):
    changes: dict
    reason: str = ""
    at_patient_request: bool = False


EDITABLE = ("subjective", "objective", "assessment", "plan", "services_provided", "diagnosis_code",
            "diagnosis_label", "summary", "finding")


def _own_record(db, p, record_id) -> models.ClinicalRecord:
    rec = db.get(models.ClinicalRecord, record_id)
    if rec is None or rec.clinic_id != p.clinic_id:
        raise HTTPException(status_code=404, detail="Záznam nenalezen")
    return rec


@router.post("/api/clinical-records/{record_id}/corrections", dependencies=[Depends(verify_csrf)])
def correct(record_id: str, body: CorrectionIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R6: a correction is a new entry that points at the version it corrects; the original stays readable."""
    p = _physio(db, user)
    rec = _own_record(db, p, record_id)
    if rec.kind not in ("visit_note", "correction", "discharge"):
        raise HTTPException(status_code=409, detail="Tento záznam nelze opravit.")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Uveďte důvod opravy.")
    bad = [k for k in body.changes if k not in EDITABLE]
    if bad or not body.changes:
        raise HTTPException(status_code=422, detail="Opravit lze jen obsah záznamu.")
    root = R.root_of(db, rec)
    latest = R.versions(db, root.id)[-1]
    content = dict(R.content_of(latest)["content"])
    content.update(body.changes)
    if body.at_patient_request:
        # § 55a/7: a correction asked for by the patient says so
        content["note_patient_request"] = "Oprava provedena na žádost pacienta."
    card = db.get(models.PatientRecord, rec.patient_record_id)
    clinic = R.clinic_of(db, p)
    new = R.write_record(db, clinic=clinic, patient=card, author=p, kind="correction", encounter_at=rec.encounter_at,
                         content=content, booking_id=rec.booking_id, conclusion_id=rec.conclusion_id,
                         episode_id=rec.episode_id, corrects=latest.id, reason=reason,
                         at_patient_request=body.at_patient_request)
    R.physio_event(db, p, "correct", "clinical_record", new.id, runner_id=card.runner_id,
                   detail={"corrects": latest.id, "fields": sorted(body.changes), "at_patient_request": body.at_patient_request})
    # R6.6: a corrected client summary goes to the client again, marked as corrected
    if "summary" in body.changes and rec.conclusion_id:
        c = db.get(models.Conclusion, rec.conclusion_id)
        if c is not None and c.shared_at and card.runner_id:
            db.add(models.Message(runner_id=card.runner_id, physio_id=p.id, sender="system", created_at=E.now_iso(),
                                  body="Shrnutí z návštěvy bylo opraveno. Aktuální znění najdete v záložce Péče."))
    db.commit()
    return _version_out(db, root)


class AddendumIn(Open):
    text: str


@router.post("/api/clinical-records/{record_id}/addenda", dependencies=[Depends(verify_csrf)])
def addendum(record_id: str, body: AddendumIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    rec = R.root_of(db, _own_record(db, p, record_id))
    if not (body.text or "").strip():
        raise HTTPException(status_code=422, detail="Doplněk je prázdný.")
    card = db.get(models.PatientRecord, rec.patient_record_id)
    new = R.write_record(db, clinic=R.clinic_of(db, p), patient=card, author=p, kind="addendum",
                         encounter_at=rec.encounter_at, content={"text": body.text.strip()}, booking_id=rec.booking_id,
                         episode_id=rec.episode_id, corrects=rec.id)
    R.physio_event(db, p, "create", "addendum", new.id, runner_id=card.runner_id, detail={"to": rec.id})
    db.commit()
    return _version_out(db, rec)


class HandoverIn(Open):
    recipient: str
    purpose: str
    scope: str


@router.post("/api/physios/me/clients/{rid}/documentation/print", dependencies=[Depends(verify_csrf)])
def print_doc(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    card, _ = doc_access(db, p, rid)
    R.physio_event(db, p, "print", "documentation", card.id if card else rid, runner_id=rid)
    db.commit()
    return {"ok": True}


@router.post("/api/physios/me/clients/{rid}/documentation/handover", dependencies=[Depends(verify_csrf)])
def handover(rid: str, body: HandoverIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R9.4 (§ 4/1 i): who received the documentation, why and in what scope."""
    p = _physio(db, user)
    card, _ = doc_access(db, p, rid)
    if not all((x or "").strip() for x in (body.recipient, body.purpose, body.scope)):
        raise HTTPException(status_code=422, detail="Vyplňte příjemce, účel a rozsah.")
    R.physio_event(db, p, "handover", "documentation", card.id if card else rid, runner_id=rid,
                   detail={"recipient": body.recipient.strip()[:120], "purpose": body.purpose.strip()[:200],
                           "scope": body.scope.strip()[:200]})
    db.commit()
    return {"ok": True}


@router.get("/api/physios/me/clients/{rid}/documentation/export")
def export_doc(rid: str, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R9.7: a structured export per patient (JSON now, the standard format later — §§ 55c, 7/9)."""
    p = _physio(db, user)
    card, _ = doc_access(db, p, rid)
    if card is None:
        raise HTTPException(status_code=404, detail="Klient nemá kartu ani záznamy.")
    rows = db.query(models.ClinicalRecord).filter_by(patient_record_id=card.id).order_by(models.ClinicalRecord.created_at).all()
    R.physio_event(db, p, "export", "documentation", card.id, runner_id=rid, detail={"records": len(rows)})
    db.commit()
    return {"format": "dosslap-record-export/1", "patient": R.patient_snapshot(card),
            "records": [{"id": r.id, "kind": r.kind, "encounter_at": r.encounter_at, "authorised_at": r.authorised_at,
                         "author": r.author_name, "corrects": r.corrects_record_id, "content": json.loads(r.content_json),
                         "content_sha256": r.content_sha256, "chain_sha256": r.chain_sha256} for r in rows],
            "exported_at": E.now_iso()}


class SigningProvider:
    """R9.5: electronic transfer needs a time stamp plus an electronic seal or a qualified-type signature
    (§ 55a/4). Nothing is configured, so `Odeslat elektronicky` stays hidden."""
    def configured(self) -> bool:
        return False

    def seal(self, payload: bytes) -> bytes:
        raise NotImplementedError


SIGNING = SigningProvider()


# ---- R7 activity history -----------------------------------------------------------------------------------
ACTION_CS = {"read": "zobrazil(a)", "create": "vytvořil(a)", "update": "upravil(a)", "approve": "schválil(a)",
             "correct": "opravil(a)", "print": "vytiskl(a)", "export": "exportoval(a)", "handover": "předal(a)",
             "transcribe": "nechal(a) přepsat", "message": "napsal(a)", "consent": "zaznamenal(a) souhlas",
             "close": "uzavřel(a)"}
RESOURCE_CS = {"documentation": "dokumentaci", "patient_card": "kartu klienta", "clinical_record": "záznam z návštěvy",
               "program": "program", "rtr": "plán návratu k běhu", "booking": "návštěvu", "conclusion": "záznam z návštěvy",
               "runner": "data z aplikace", "triage": "případ", "episode": "epizodu péče", "addendum": "doplněk záznamu",
               "practice": "údaje praxe", "messages": "zprávy", "limit": "omezení tréninku", "injury": "zranění",
               # physio brief Phases 3 and 4: the history showed the raw keys (clinic_test, prom, package)
               "clinic_test": "test v ordinaci", "prom": "dotazník", "package": "balíček návštěv", "invoice": "doklad",
               "waitlist": "pořadník", "video_note": "poznámku k videu", "outcomes": "výsledky", "recall": "seznam k oslovení"}


def _event_out(e: models.RecordEvent) -> dict:
    return {"at": e.at, "who": e.actor_name or e.actor_type, "actor_type": e.actor_type, "action": e.action,
            "resource": e.resource_type,
            "text": f"{ACTION_CS.get(e.action, e.action)} {RESOURCE_CS.get(e.resource_type, e.resource_type)}"}


@router.get("/api/runners/{rid}/access-events")
def runner_access_events(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """R7.5: Kdo přistupoval k vašim datům → Zobrazit detail."""
    ensure_runner_self(user, rid)
    rows = (db.query(models.RecordEvent).filter(models.RecordEvent.runner_id == rid,
                                                models.RecordEvent.actor_type != "runner")
            .order_by(models.RecordEvent.id.desc()).limit(200).all())
    return {"items": [_event_out(e) for e in rows]}


# ---- R8 unsigned ---------------------------------------------------------------------------------------------
def unsigned_for(db: DBSession, physio_id: str) -> list[dict]:
    now = E.now_iso()
    out = []
    rows = (db.query(models.Booking).filter(models.Booking.physio_id == physio_id,
                                            models.Booking.status.in_(("confirmed", "completed"))).all())
    approved = {c.booking_id for c in db.query(models.Conclusion.booking_id)
                .filter(models.Conclusion.physio_id == physio_id, models.Conclusion.status == "approved").all()}
    from .conclusions import _visit_started
    for b in rows:
        if b.id in approved or not _visit_started(b):
            continue
        r = db.get(models.Runner, b.runner_id)
        deadline = R.sign_by(b.slot_at)
        out.append({"booking_id": b.id, "runner_id": b.runner_id, "name": r.name if r else b.runner_id,
                    "slot_at": b.slot_at, "sign_by": deadline, "overdue": bool(deadline and now > deadline)})
    return sorted(out, key=lambda x: x["slot_at"] or "")


@router.get("/api/physios/me/unsigned")
def unsigned(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    return {"items": unsigned_for(db, user.physio_id)}


# ---- R10 recording consent -------------------------------------------------------------------------------------
@router.post("/api/bookings/{bid}/recording-consent", dependencies=[Depends(verify_csrf)])
def recording_consent(bid: int, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    p = _physio(db, user)
    b = db.get(models.Booking, bid)
    if b is None or b.physio_id != p.id:
        raise HTTPException(status_code=403, detail="Tato rezervace nepatří vám.")
    R.physio_event(db, p, "consent", "booking", bid, runner_id=b.runner_id, detail={"kind": "recording"})
    db.commit()
    return {"ok": True, "at": E.now_iso()}


def has_recording_consent(db: DBSession, bid: int) -> bool:
    return db.query(models.RecordEvent.id).filter_by(action="consent", resource_type="booking",
                                                     resource_id=str(bid)).first() is not None


# ---- R11 retention and destruction -----------------------------------------------------------------------------
@router.get("/api/physios/me/retention-due")
def retention_due(user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R11.3: cards past retention, for the provider's assessment (§ 14). Nothing is deleted automatically."""
    p = _physio(db, user)
    today = E.iso_date(E.today_date())
    rows = (db.query(models.PatientRecord).filter(models.PatientRecord.clinic_id == p.clinic_id,
                                                  models.PatientRecord.retain_until.isnot(None),
                                                  models.PatientRecord.retain_until <= today).all())
    destroyed = {d.patient_record_id for d in db.query(models.RecordDestruction.patient_record_id).all()}
    return {"items": [{"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "retain_until": c.retain_until,
                       "records": db.query(models.ClinicalRecord.id).filter_by(patient_record_id=c.id).count()}
                      for c in rows if c.id not in destroyed]}


class DestructionIn(Open):
    patient_record_ids: list[str]
    method: str
    approved_by: str
    approval_ref: str = ""


@router.post("/api/physios/me/destructions", dependencies=[Depends(verify_csrf)])
def destroy(body: DestructionIn, user: models.User = Depends(require_verified_physio), db: DBSession = Depends(get_db)):
    """R11.4: only an approved list, only past retention; the log row comes first, then the records go."""
    p = _physio(db, user)
    if not (body.method or "").strip() or not (body.approved_by or "").strip():
        raise HTTPException(status_code=422, detail="Uveďte způsob skartace a kdo ji schválil.")
    today = E.today_date()
    keep = date(today.year + R.DESTRUCTION_LOG_YEARS, today.month, min(today.day, 28)).isoformat()
    done = []
    for pid_ in body.patient_record_ids:
        card = db.get(models.PatientRecord, pid_)
        if card is None or card.clinic_id != p.clinic_id:
            raise HTTPException(status_code=404, detail="Karta nenalezena")
        if not card.retain_until or card.retain_until > today.isoformat():
            raise HTTPException(status_code=409, detail="Doba uchování ještě neuplynula.")
        recs = db.query(models.ClinicalRecord).filter_by(patient_record_id=card.id).all()
        db.add(models.RecordDestruction(patient_record_id=card.id, clinic_id=card.clinic_id, records_count=len(recs),
                                        method=body.method.strip(), approved_by=body.approved_by.strip(),
                                        approval_ref=body.approval_ref.strip() or None, executed_by=p.name,
                                        executed_at=E.now_iso(), keep_until=keep))
        db.flush()
        for r in recs:
            db.delete(r)
        db.flush()
        done.append({"id": card.id, "records": len(recs)})
    db.commit()
    return {"destroyed": done}


# ---- R11.2 account deletion -----------------------------------------------------------------------------------
KEPT_TABLES = {"patient_records", "care_episodes", "clinical_records", "record_events", "record_destructions",
               "outcome_followups"}


class DeleteAccountIn(Open):
    confirm: str = ""


@router.post("/api/runners/{rid}/account/delete", dependencies=[Depends(verify_csrf)])
def delete_account(rid: str, body: DeleteAccountIn, user: models.User = Depends(get_current_user),
                   db: DBSession = Depends(get_db)):
    """Removes the runner's data and login. Patient cards and clinical records stay with the providers for the
    retention period (zákon 372/2011 § 65, vyhl. 444/2024 § 13), unlinked from the deleted account."""
    ensure_runner_self(user, rid)
    if (body.confirm or "").strip().upper() != "SMAZAT":
        raise HTTPException(status_code=422, detail="Pro smazání napište SMAZAT.")
    from sqlalchemy import delete, select, update
    from ..db import Base
    R.event(db, actor_type="runner", actor_id=rid, actor_name=user.name, action="close", resource_type="runner",
            runner_id=rid, detail={"account_deleted": True})
    db.execute(update(models.PatientRecord).where(models.PatientRecord.runner_id == rid).values(runner_id=None))
    db.execute(update(models.CareEpisode).where(models.CareEpisode.runner_id == rid).values(runner_id=None))
    db.execute(update(models.OutcomeFollowup).where(models.OutcomeFollowup.runner_id == rid).values(status="skipped"))
    tables = [t for t in Base.metadata.sorted_tables if t.name not in KEPT_TABLES]
    owned = {t.name for t in tables if "runner_id" in t.c} | {"runners"}
    for t in reversed(tables):                       # children first
        if t.name == "runners":
            continue
        if "runner_id" in t.c:
            db.execute(delete(t).where(t.c.runner_id == rid))
            continue
        for fk in t.foreign_keys:
            parent = fk.column.table
            if parent.name in owned and parent.name != "runners" and "runner_id" in parent.c:
                db.execute(delete(t).where(fk.parent.in_(select(fk.column).where(parent.c.runner_id == rid))))
    runners = Base.metadata.tables["runners"]
    db.execute(delete(runners).where(runners.c.id == rid))
    db.commit()
    return {"ok": True, "kept": "Záznamy z návštěv zůstávají u poskytovatelů po dobu stanovenou zákonem."}
