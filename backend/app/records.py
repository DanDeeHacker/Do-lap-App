"""The clinical record (physio brief 2026-11-09, Phase 1): the provider's patient card, care episodes, the
append-only ledger with its hash chain, the activity log, retention and field encryption.

The legal mapping (zákon 372/2011 Sb. as amended by 240/2024 Sb., vyhláška 444/2024 Sb.) still needs a
lawyer's confirmation (brief Appendix C), so every rule sits in a named constant or one function here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import date, datetime, time

from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import engine as E

# ---- rules (Appendix C: confirm with counsel) -------------------------------------------------------
PATIENT_REQUIRED = ("first_name", "last_name", "birth_date", "sex_at_birth",
                    "permanent_street", "permanent_city", "permanent_postal_code")     # brief C.4
PROVIDER_REQUIRED = ("legal_name", "ico", "care_site_street", "care_site_city", "care_site_postal_code")
PATIENT_LABEL = {"first_name": "jméno", "last_name": "příjmení", "birth_date": "datum narození",
                 "sex_at_birth": "pohlaví při narození", "permanent_address": "adresa trvalého pobytu"}


def ico_valid(ico: str) -> bool:
    """Round 2 F10.1: the IČO checksum — weights 8…2 over the first 7 digits, r = sum % 11, check = (11 - r) % 10."""
    if not (ico.isdigit() and len(ico) == 8):
        return False
    r = sum(int(d) * w for d, w in zip(ico[:7], range(8, 1, -1))) % 11
    return (11 - r) % 10 == int(ico[7])


def provider_name(legal_name: str | None, legal_form: str | None) -> str:
    """Round 2 F10.3: never 's.r.o., s.r.o.' — the form is appended only when the name does not already end with it."""
    name = (legal_name or "").strip()
    form = (legal_form or "").strip()
    if not form:
        return name
    squash = lambda x: "".join(ch for ch in x.lower() if ch not in ". ,")   # noqa: E731
    return name if squash(name).endswith(squash(form)) else f"{name}, {form}"


def missing_grouped(p) -> list[str]:
    """The approval gate's missing list with the address as one item (F10.4)."""
    out = []
    for k in patient_missing(p):
        k = "permanent_address" if k.startswith("permanent_") else k
        if k not in out:
            out.append(k)
    return out


RETENTION_YEARS = 5           # vyhl. 444/2024 § 13/2, příloha 3 bod 2: from 1 January after the last service
DESTRUCTION_LOG_YEARS = 40    # vyhl. § 17/2
ENC_FIELDS = ("rodne_cislo", "insurance_no", "id_doc_no")
CARD_FIELDS = ("first_name", "last_name", "birth_date", "sex_at_birth", "insurer_code", "id_doc_type",
               "permanent_street", "permanent_city", "permanent_postal_code", "delivery_street", "delivery_city",
               "delivery_postal_code", "phone", "email", "gp_name", "gp_contact", "legal_representative")
SEX_LABEL = {"f": "žena", "m": "muž"}


# ---- field encryption (R2) ---------------------------------------------------------------------------
def _parse_key(raw: str | None) -> bytes | None:
    if not raw:
        return None
    try:
        k = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        return None
    return k if len(k) in (16, 24, 32) else None


def _key() -> bytes | None:
    return _parse_key(os.environ.get("FIELD_ENCRYPTION_KEY"))


def _previous_key() -> bytes | None:
    """Round 2 F9.1: during a rotation the old key still reads what it wrote (docs/field-encryption.md)."""
    return _parse_key(os.environ.get("FIELD_ENCRYPTION_KEY_PREVIOUS"))


def crypto_on() -> bool:
    return _key() is not None


def encrypt(value: str | None) -> str | None:
    """AES-GCM with the field key. Without the key nothing is stored (the inputs are hidden)."""
    if value in (None, ""):
        return None
    key = _key()
    if key is None:
        raise RuntimeError("Šifrování citlivých údajů není zapnuté — nelze je uložit.")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, value.encode("utf-8"), b"dosslap-field-v1")
    return "v1:" + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(blob: str | None) -> str | None:
    if not blob or not blob.startswith("v1:"):
        return None
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(blob[3:])
    for key in (_key(), _previous_key()):
        if key is None:
            continue
        try:
            return AESGCM(key).decrypt(raw[:12], raw[12:], b"dosslap-field-v1").decode("utf-8")
        except InvalidTag:
            continue
    return None


# ---- identity -----------------------------------------------------------------------------------------
def new_record_id() -> str:
    """§ 55a/1 refers to a format in the eHealth standard (Appendix C.5); until then a UUID, made only here."""
    return str(uuid.uuid4())


def clinic_of(db: DBSession, physio: models.Physio) -> models.Clinic:
    """W1: every physio belongs to a clinic; a physio without one gets a solo practice."""
    c = db.get(models.Clinic, physio.clinic_id) if physio.clinic_id else None
    if c is None:
        c = models.Clinic(id=f"cln-{uuid.uuid4().hex[:10]}", name=f"Praxe {physio.name}", is_solo=True)
        db.add(c)
        db.flush()
        physio.clinic_id = c.id
    return c


def provider_missing(c: models.Clinic | None) -> list[str]:
    return list(PROVIDER_REQUIRED) if c is None else [k for k in PROVIDER_REQUIRED if not (getattr(c, k) or "").strip()]


def provider_snapshot(c: models.Clinic) -> dict:
    return {k: getattr(c, k) for k in ("id", "name", "legal_name", "legal_form", "ico", "registered_street",
                                       "registered_city", "registered_postal_code", "care_site_street",
                                       "care_site_city", "care_site_postal_code")}


def author_snapshot(p: models.Physio) -> dict:
    return {"id": p.id, "name": p.name, "title": p.title, "qualification": p.qualification,
            "hcp_identifier": p.hcp_identifier}


# ---- patient card (R2) ----------------------------------------------------------------------------------
def _split_name(name: str | None) -> tuple[str, str]:
    parts = (name or "").strip().split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ((parts[0] if parts else ""), "")


def runner_snapshot(r: models.Runner) -> dict:
    first, last = _split_name(r.name)
    return {"first_name": first, "last_name": last, "sex_at_birth": r.sex, "birth_year": r.birth_year,
            "permanent_city": r.city}


def card(db: DBSession, clinic_id: str, runner_id: str) -> models.PatientRecord | None:
    return db.query(models.PatientRecord).filter_by(clinic_id=clinic_id, runner_id=runner_id).first()


def card_prefill(r: models.Runner) -> dict:
    """What the runner profile offers; the physio confirms it. A birth date is never guessed from the year."""
    snap = runner_snapshot(r)
    return {k: snap.get(k) for k in ("first_name", "last_name", "sex_at_birth", "permanent_city")} | {
        "birth_year_hint": r.birth_year}


def patient_missing(p: models.PatientRecord | None) -> list[str]:
    return list(PATIENT_REQUIRED) if p is None else [k for k in PATIENT_REQUIRED if not (getattr(p, k) or "").strip()]


def profile_changes(p: models.PatientRecord, r: models.Runner | None) -> list[str]:
    """R2.4: the runner changed their profile after the card was confirmed — never applied silently."""
    if r is None or not p.source_snapshot:
        return []
    now = runner_snapshot(r)
    return [k for k, v in now.items() if (p.source_snapshot or {}).get(k) != v]


def patient_snapshot(p: models.PatientRecord) -> dict:
    return {"identifier": p.id, "first_name": p.first_name, "last_name": p.last_name, "birth_date": p.birth_date,
            "sex_at_birth": p.sex_at_birth, "permanent_address": {
                "street": p.permanent_street, "city": p.permanent_city, "postal_code": p.permanent_postal_code},
            "insurer_code": p.insurer_code, "has_rodne_cislo": bool(p.rodne_cislo_enc),
            "has_insurance_no": bool(p.insurance_no_enc)}


def card_out(p: models.PatientRecord, r: models.Runner | None = None) -> dict:
    out = {k: getattr(p, k) for k in ("id", "clinic_id", "runner_id", *CARD_FIELDS, "anamnesis", "red_flags",
                                      "retain_until", "created_at", "updated_at")}
    for f in ENC_FIELDS:
        try:
            out[f] = decrypt(getattr(p, f"{f}_enc"))
        except Exception:
            out[f] = None
        out[f"{f}_stored"] = bool(getattr(p, f"{f}_enc"))
    out["missing"] = patient_missing(p)
    out["profile_changed"] = profile_changes(p, r)
    out["crypto"] = crypto_on()
    return out


# ---- episodes (R3) --------------------------------------------------------------------------------------
def episode_for(db: DBSession, physio_id: str, runner_id: str, create: bool = True) -> models.CareEpisode | None:
    ep = (db.query(models.CareEpisode).filter_by(physio_id=physio_id, runner_id=runner_id, status="open")
          .order_by(models.CareEpisode.id.desc()).first())
    if ep is None and create:
        p = db.get(models.Physio, physio_id)
        c = clinic_of(db, p) if p else None
        pr = card(db, c.id, runner_id) if c else None
        ep = models.CareEpisode(clinic_id=c.id if c else None, physio_id=physio_id, runner_id=runner_id,
                                patient_record_id=pr.id if pr else None, opened_at=E.now_iso(), status="open")
        db.add(ep)
        db.flush()
    return ep


# ---- the ledger (R5) ------------------------------------------------------------------------------------
def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def retain_until_for(last_service: date) -> str:
    return date(last_service.year + 1 + RETENTION_YEARS, 1, 1).isoformat()


def _last_chain(db: DBSession, clinic_id: str) -> str:
    last = (db.query(models.ClinicalRecord.chain_sha256).filter_by(clinic_id=clinic_id)
            .order_by(models.ClinicalRecord.created_at.desc(), models.ClinicalRecord.id.desc()).first())
    return last[0] if last else ""


def write_record(db: DBSession, *, clinic: models.Clinic, patient: models.PatientRecord, author: models.Physio,
                 kind: str, encounter_at: str, content: dict, booking_id=None, conclusion_id=None, episode_id=None,
                 corrects: str | None = None, reason: str | None = None, at_patient_request: bool = False,
                 legacy: bool = False, authorised_at: str | None = None,
                 flags: list[str] | None = None) -> models.ClinicalRecord:
    """One ledger row, in the caller's transaction (flush only). The content carries provider, author and
    patient identity as they are now, so the record reads the same years later."""
    now = E.now_iso()
    try:
        last_service = date.fromisoformat(encounter_at[:10])
    except ValueError:
        last_service = E.today_date()
    body = {"kind": kind, "provider": provider_snapshot(clinic), "author": author_snapshot(author),
            "patient": patient_snapshot(patient), "encounter_at": encounter_at, "content": content,
            "episode_id": episode_id, "booking_id": booking_id}
    if legacy:
        body["legacy"] = True
    if flags:
        body["flags"] = list(flags)        # round 2 F2.4, e.g. approved_before_encounter
    text = canonical(body)
    h = sha256(text)
    rec = models.ClinicalRecord(
        id=new_record_id(), clinic_id=clinic.id, patient_record_id=patient.id, episode_id=episode_id,
        booking_id=booking_id, conclusion_id=conclusion_id, kind=kind, encounter_at=encounter_at,
        content_json=text, content_sha256=h, chain_sha256=sha256(_last_chain(db, clinic.id) + h),
        corrects_record_id=corrects, correction_reason=reason, at_patient_request=1 if at_patient_request else 0,
        author_physio_id=author.id, author_name=author.name, author_identifier=author.hcp_identifier,
        # round 2 F2.3: a legacy note keeps the time it was approved; created_at stays the insert time (chain order)
        authorised_at=authorised_at or now, retain_until=retain_until_for(last_service), created_at=now)
    db.add(rec)
    # R11: the card's retention follows the last service in the record
    ru = retain_until_for(last_service)
    if not patient.retain_until or ru > patient.retain_until:
        patient.retain_until = ru
    db.flush()
    return rec


def verify(db: DBSession) -> dict:
    """Recompute every hash and chain per clinic; report the first mismatch (R5.5)."""
    rows = db.query(models.ClinicalRecord).order_by(models.ClinicalRecord.clinic_id, models.ClinicalRecord.created_at,
                                                    models.ClinicalRecord.id).all()
    chain, n = {}, 0
    for r in rows:
        n += 1
        if sha256(r.content_json) != r.content_sha256:
            return {"ok": False, "checked": n, "record_id": r.id, "problem": "content"}
        expect = sha256(chain.get(r.clinic_id, "") + r.content_sha256)
        if expect != r.chain_sha256:
            return {"ok": False, "checked": n, "record_id": r.id, "problem": "chain"}
        chain[r.clinic_id] = r.chain_sha256
    return {"ok": True, "checked": n}


def content_of(r: models.ClinicalRecord) -> dict:
    return json.loads(r.content_json)


def versions(db: DBSession, root_id: str) -> list[models.ClinicalRecord]:
    """The original and its corrections in order (each correction points at the version it corrects)."""
    out, cur = [], db.get(models.ClinicalRecord, root_id)
    while cur is not None:
        out.append(cur)
        cur = (db.query(models.ClinicalRecord).filter_by(corrects_record_id=cur.id, kind="correction")
               .order_by(models.ClinicalRecord.created_at.asc()).first())
    return out


def root_of(db: DBSession, rec: models.ClinicalRecord) -> models.ClinicalRecord:
    while rec.kind == "correction" and rec.corrects_record_id:
        nxt = db.get(models.ClinicalRecord, rec.corrects_record_id)
        if nxt is None:
            break
        rec = nxt
    return rec


# ---- authorisation deadline (R8) ------------------------------------------------------------------------
def sign_by(slot_at: str | None) -> str | None:
    """§ 11/3: authorised during the day of the visit — the end of its local day."""
    if not slot_at:
        return None
    try:
        d = datetime.fromisoformat(slot_at)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=E.LOCAL_TZ)
    loc = d.astimezone(E.LOCAL_TZ).date()
    return datetime.combine(loc, time(23, 59, 59), E.LOCAL_TZ).isoformat()


# ---- the activity log (R7) ------------------------------------------------------------------------------
def event(db: DBSession, *, actor_type: str, action: str, resource_type: str, actor_id=None, actor_name=None,
          resource_id=None, runner_id=None, clinic_id=None, patient_record_id=None, detail: dict | None = None,
          request_id=None) -> None:
    """detail carries field names and flags, never clinical text or message bodies."""
    db.add(models.RecordEvent(at=E.now_iso(), actor_type=actor_type, actor_id=actor_id, actor_name=actor_name,
                              clinic_id=clinic_id, runner_id=runner_id, patient_record_id=patient_record_id,
                              action=action, resource_type=resource_type,
                              resource_id=str(resource_id) if resource_id is not None else None,
                              detail_json=canonical(detail) if detail else None, request_id=request_id))


def physio_event(db: DBSession, physio: models.Physio, action: str, resource_type: str, resource_id=None,
                 runner_id=None, detail=None) -> None:
    pr = card(db, physio.clinic_id, runner_id) if (physio.clinic_id and runner_id) else None
    event(db, actor_type="physio", actor_id=physio.id, actor_name=physio.name, action=action,
          resource_type=resource_type, resource_id=resource_id, runner_id=runner_id, clinic_id=physio.clinic_id,
          patient_record_id=pr.id if pr else None, detail=detail)
