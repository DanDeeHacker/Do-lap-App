"""Garmin data connection — the one real (non-simulated) integration.
Accepts either a GDPR export .zip, a bare summarizedActivities.json, or an
already-built seed .json (garmin_ingest.py's own output format), and runs
them all through the exact same backend/garmin_ingest.py code path the CLI
uses (build_seed()) so there is one parser, not two drifting copies.

runner_id is always taken from the session — never trusted from the
upload — since the endpoint is a write into that runner's own history.
"""
import json
import os
import secrets
import shutil
import sys
import tempfile
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role, verify_csrf
from ..metrics import engine as E

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
import garmin_ingest  # noqa: E402  (backend/garmin_ingest.py, top-level script next to app/)
import apple_health_ingest  # noqa: E402  (backend/apple_health_ingest.py, same location)
import garmin_live  # noqa: E402  (backend/garmin_live.py — direct Connect download)

from .. import schemas  # noqa: E402

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _apply_seed(db: DBSession, rid: str, seed: dict, provider: str = "garmin") -> None:
    db.query(models.Activity).filter(models.Activity.runner_id == rid).delete()
    db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid).delete()
    db.query(models.ActivityFeedback).filter(models.ActivityFeedback.runner_id == rid).delete()
    db.flush()

    for a in seed.get("activities", []):
        a = {k: v for k, v in a.items() if k != "id"}
        a["runner_id"] = rid
        db.add(models.Activity(**a))
    for d in seed.get("daily_metrics", []):
        d = {k: v for k, v in d.items() if k != "id"}
        d["runner_id"] = rid
        db.add(models.DailyMetric(**d))
    db.flush()

    # activity_feedback references the seed's own 1..N activity id (assigned
    # by garmin_ingest.py in started_at order) — re-fetching with the same
    # sort order reproduces that same numbering against the real DB ids.
    act_rows = (
        db.query(models.Activity).filter(models.Activity.runner_id == rid)
        .order_by(models.Activity.started_at.asc(), models.Activity.id.asc()).all()
    )
    for f in seed.get("activity_feedback", []):
        f = dict(f)
        f.pop("id", None)
        orig_activity_id = f.pop("activity_id", None)
        if not orig_activity_id or not (1 <= orig_activity_id <= len(act_rows)):
            continue
        f["runner_id"] = rid
        f["activity_id"] = act_rows[orig_activity_id - 1].id
        f.setdefault("pain_points", [])
        db.add(models.ActivityFeedback(**f))

    integ = db.query(models.Integration).filter(models.Integration.runner_id == rid).first()
    if integ:
        integ.status = "connected"
        integ.provider = provider
        integ.last_sync_at = E.now_iso()
        integ.coverage_json = (seed.get("_meta") or {}).get("coverage_pct")
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    synced_device = (seed.get("runners") or [{}])[0].get("device") or provider.capitalize()
    if r and r.device != synced_device:
        r.device = synced_device
        db.add(models.DeviceHistory(runner_id=rid, device=synced_device, source=f"{provider}_sync", recorded_at=E.now_iso()))
    db.commit()
    E.recompute_assessment(db, rid)


@router.post("/garmin/import", dependencies=[Depends(verify_csrf)])
async def garmin_import(file: UploadFile = File(...), fit: bool = False,
                         user: models.User = Depends(require_role("runner")),
                         db: DBSession = Depends(get_db)):
    rid = user.runner_id
    raw = await file.read()
    tmpdir = tempfile.mkdtemp(prefix="dosslap_upload_")
    try:
        fname = (file.filename or "upload").lower()
        if fname.endswith(".zip"):
            path = os.path.join(tmpdir, "export.zip")
            with open(path, "wb") as fh:
                fh.write(raw)
            try:
                seed = garmin_ingest.build_seed(path, runner_id=rid, do_fit=fit)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        elif fname.endswith(".json"):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Neplatný JSON soubor.")
            if isinstance(payload, dict) and "activities" in payload and "_meta" in payload:
                seed = payload  # already garmin_ingest.py's own seed schema
            else:
                with open(os.path.join(tmpdir, "summarizedActivities.json"), "wb") as fh:
                    fh.write(raw)
                try:
                    seed = garmin_ingest.build_seed(tmpdir, runner_id=rid, do_fit=fit)
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
        else:
            raise HTTPException(
                status_code=400,
                detail="Nahrajte .zip export z Garmin Connect nebo summarizedActivities.json.",
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    _apply_seed(db, rid, seed, provider="garmin")
    return {"ok": True, "runner_id": rid, "activities": len(seed.get("activities", [])), "meta": seed.get("_meta")}


@router.post("/apple/import", dependencies=[Depends(verify_csrf)])
async def apple_import(file: UploadFile = File(...),
                       user: models.User = Depends(require_role("runner")),
                       db: DBSession = Depends(get_db)):
    """Apple Health export (.zip or bare export.xml). runner_id is always the
    session's own — never trusted from the upload — same as garmin_import."""
    rid = user.runner_id
    raw = await file.read()
    tmpdir = tempfile.mkdtemp(prefix="dosslap_apple_")
    try:
        fname = (file.filename or "export.xml").lower()
        path = os.path.join(tmpdir, "export.zip" if fname.endswith(".zip") else "export.xml")
        with open(path, "wb") as fh:
            fh.write(raw)
        try:
            seed = apple_health_ingest.build_seed(path, runner_id=rid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    _apply_seed(db, rid, seed, provider="apple")
    return {"ok": True, "runner_id": rid, "activities": len(seed.get("activities", [])), "meta": seed.get("_meta")}


# ---------------------------------------------------------------------------
# Apple Health "connect" — Apple has no cloud API (HealthKit is on-device), so
# the closest equivalent to Garmin's server-side pull is a device-initiated
# push: the phone auto-POSTs HealthKit data on a schedule (Health Auto Export
# app or an Apple Shortcut) to the token-authed webhook below. Set up once, then
# it syncs without any manual export/upload.
# ---------------------------------------------------------------------------
def _apple_token_row(db: DBSession, rid: str):
    return (
        db.query(models.IngestToken)
        .filter(models.IngestToken.runner_id == rid, models.IngestToken.provider == "apple")
        .first()
    )


@router.get("/apple/push-token")
def apple_push_token(request: Request, user: models.User = Depends(require_role("runner")),
                     db: DBSession = Depends(get_db)):
    """Return (creating on first call) the runner's Apple push token + webhook
    URL to paste into Health Auto Export / a Shortcut on their phone."""
    rid = user.runner_id
    row = _apple_token_row(db, rid)
    if not row:
        row = models.IngestToken(token=secrets.token_urlsafe(32), runner_id=rid,
                                 provider="apple", created_at=E.now_iso())
        db.add(row)
        db.commit()
    base = str(request.base_url).rstrip("/")
    return {"token": row.token, "url": f"{base}/api/integrations/apple/push",
            "last_used_at": row.last_used_at}


@router.post("/apple/push-token/rotate", dependencies=[Depends(verify_csrf)])
def apple_push_token_rotate(request: Request, user: models.User = Depends(require_role("runner")),
                            db: DBSession = Depends(get_db)):
    """Rotate the token — invalidates any device still using the old one."""
    rid = user.runner_id
    db.query(models.IngestToken).filter(
        models.IngestToken.runner_id == rid, models.IngestToken.provider == "apple"
    ).delete()
    row = models.IngestToken(token=secrets.token_urlsafe(32), runner_id=rid,
                             provider="apple", created_at=E.now_iso())
    db.add(row)
    db.commit()
    base = str(request.base_url).rstrip("/")
    return {"token": row.token, "url": f"{base}/api/integrations/apple/push", "last_used_at": None}


@router.post("/apple/push")
async def apple_push(request: Request, db: DBSession = Depends(get_db),
                     authorization: str | None = Header(default=None)):
    """Token-authed HealthKit ingest (no browser session/CSRF — it's a
    machine-to-machine webhook). Accepts the Health Auto Export JSON body and
    merges it additively/idempotently, exactly like the Garmin live sync. Auth:
    `Authorization: Bearer <token>` (or `?token=` for clients that can't set
    headers). Never trusts a runner_id from the body — it's derived from the
    token."""
    tok = None
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
    tok = tok or request.query_params.get("token")
    row = db.query(models.IngestToken).filter(models.IngestToken.token == tok).first() if tok else None
    if not row:
        raise HTTPException(status_code=401, detail="Neplatný nebo chybějící token.")
    rid = row.runner_id

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Tělo požadavku není platné JSON.")
    try:
        seed = apple_health_ingest.build_seed_from_json(payload, runner_id=rid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    added = _merge_seed(db, rid, seed, provider="apple")
    row.last_used_at = E.now_iso()
    db.commit()
    return {"ok": True, "runner_id": rid, **added, "meta": seed.get("_meta")}


def _runner_history(db: DBSession, rid: str):
    """Dates the runner already has daily metrics for, and the date of their
    most recent activity — the two anchors that make the live download
    incremental (only fetch days without history)."""
    dates = frozenset(
        row[0] for row in db.query(models.DailyMetric.date).filter(models.DailyMetric.runner_id == rid).all()
    )
    last_act = db.query(func.max(models.Activity.started_at)).filter(models.Activity.runner_id == rid).scalar()
    return dates, last_act


def _merge_seed(db: DBSession, rid: str, seed: dict, provider: str = "garmin") -> dict:
    """Additive, idempotent import: inserts only activities whose external_id
    is new and daily rows for dates the runner doesn't have yet. Nothing is
    deleted or overwritten — re-running an export never duplicates rows and
    never clobbers a manually edited day (unlike _apply_seed's full replace,
    which is right for a one-shot file export but wrong for repeat syncs)."""
    existing_ext = {
        row[0] for row in db.query(models.Activity.external_id).filter(models.Activity.runner_id == rid).all() if row[0]
    }
    existing_dates = {
        row[0] for row in db.query(models.DailyMetric.date).filter(models.DailyMetric.runner_id == rid).all()
    }
    added_a = added_d = 0
    for a in seed.get("activities", []):
        ext = a.get("external_id")
        if ext and ext in existing_ext:
            continue
        row = {k: v for k, v in a.items() if k != "id"}
        row["runner_id"] = rid
        db.add(models.Activity(**row))
        added_a += 1
        if ext:
            existing_ext.add(ext)
    for d in seed.get("daily_metrics", []):
        if d["date"] in existing_dates:
            continue
        row = {k: v for k, v in d.items() if k != "id"}
        row["runner_id"] = rid
        db.add(models.DailyMetric(**row))
        added_d += 1
        existing_dates.add(d["date"])
    db.flush()

    integ = db.query(models.Integration).filter(models.Integration.runner_id == rid).first()
    if integ:
        integ.status = "connected"
        integ.provider = provider
        integ.last_sync_at = E.now_iso()
        integ.coverage_json = (seed.get("_meta") or {}).get("coverage_pct")
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    synced_device = (seed.get("runners") or [{}])[0].get("device") or provider.capitalize()
    if r and synced_device and r.device != synced_device:
        r.device = synced_device
        db.add(models.DeviceHistory(runner_id=rid, device=synced_device, source=f"{provider}_sync", recorded_at=E.now_iso()))
    db.commit()
    E.recompute_assessment(db, rid)
    return {"added_activities": added_a, "added_daily": added_d}


# Pending MFA logins — the Garmin object (with its session cookies) must
# survive between the credential step and the code step. In-process only,
# short-lived, and scoped to the runner who started it.
_PENDING_MFA: dict[str, dict] = {}
_MFA_TTL = 300  # seconds


def _prune_pending():
    now = time.time()
    for k in [k for k, v in _PENDING_MFA.items() if now - v["at"] > _MFA_TTL]:
        _PENDING_MFA.pop(k, None)


def _download_and_merge(db: DBSession, rid: str, garmin) -> dict:
    skip_dates, since = _runner_history(db, rid)
    try:
        seed = garmin_live.download_seed(garmin, skip_dates=skip_dates, since_date=since)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Nepodařilo se stáhnout data z Garminu: {e}")
    added = _merge_seed(db, rid, seed, provider="garmin")
    return {"ok": True, "runner_id": rid, **added, "meta": seed.get("_meta")}


@router.post("/garmin/connect", dependencies=[Depends(verify_csrf)])
def garmin_connect(body: schemas.GarminCredsRequest,
                   user: models.User = Depends(require_role("runner")),
                   db: DBSession = Depends(get_db)):
    """Step 1 of the direct Garmin download. Logs in with the runner's own
    credentials (used only here, never stored). If the account needs MFA,
    returns {mfa_required, mfa_token} and the client posts the code to
    /garmin/connect/mfa. Otherwise downloads + merges straight away. The
    download is incremental — only days without history are fetched."""
    rid = user.runner_id
    try:
        garmin, needs_mfa, state = garmin_live.begin_login(body.email, body.password)
    except garmin_live.AuthError:
        # 400, not 401 — 401 would make the SPA treat it as an expired Došlap
        # session and bounce the user to the login page instead of showing
        # "wrong Garmin credentials".
        raise HTTPException(status_code=400, detail="Přihlášení k Garmin Connect selhalo — zkontrolujte e-mail a heslo.")
    except garmin_live.GarminLiveError as e:
        raise HTTPException(status_code=502, detail=f"Nepodařilo se přihlásit ke Garminu: {e}")
    if needs_mfa:
        _prune_pending()
        token = secrets.token_urlsafe(24)
        _PENDING_MFA[token] = {"garmin": garmin, "state": state, "rid": rid, "at": time.time()}
        return {"mfa_required": True, "mfa_token": token}
    return _download_and_merge(db, rid, garmin)


@router.post("/garmin/connect/mfa", dependencies=[Depends(verify_csrf)])
def garmin_connect_mfa(body: schemas.GarminMfaRequest,
                       user: models.User = Depends(require_role("runner")),
                       db: DBSession = Depends(get_db)):
    """Step 2: finish an MFA login with the code, then download + merge."""
    _prune_pending()
    pending = _PENDING_MFA.get(body.mfa_token)
    if not pending or pending["rid"] != user.runner_id:
        raise HTTPException(status_code=410, detail="Přihlášení vypršelo nebo neplatí — začněte znovu.")
    try:
        garmin_live.resume_login(pending["garmin"], pending["state"], body.mfa_code)
    except garmin_live.AuthError:
        raise HTTPException(status_code=400, detail="Neplatný nebo prošlý ověřovací kód.")
    _PENDING_MFA.pop(body.mfa_token, None)
    return _download_and_merge(db, user.runner_id, pending["garmin"])
