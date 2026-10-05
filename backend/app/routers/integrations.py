"""Garmin data connection — the one real (non-simulated) integration.
Accepts either a GDPR export .zip, a bare summarizedActivities.json, or an
already-built seed .json (garmin_ingest.py's own output format), and runs
them all through the exact same backend/garmin_ingest.py code path the CLI
uses (build_seed()) so there is one parser, not two drifting copies.

runner_id is always taken from the session — never trusted from the
upload — since the endpoint is a write into that runner's own history.
"""
import datetime as _dt
import json
import os
import secrets
import shutil
import sys
import tempfile
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role, verify_csrf
from ..metrics import coach_texts
from ..metrics import engine as E

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
import garmin_ingest  # noqa: E402  (backend/garmin_ingest.py, top-level script next to app/)
import apple_health_ingest  # noqa: E402  (backend/apple_health_ingest.py, same location)
import garmin_live  # noqa: E402  (backend/garmin_live.py — direct Connect download)

from .. import schemas  # noqa: E402

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _apply_hr_hist(db: DBSession, rid: str, seed: dict) -> int:
    """Time at each heart rate per workout (seed["hr_hist"] = {external_id: {bin: s}}, the
    Apple Health export) → an HR-only stream row, so Intenzita counts real hard minutes
    for runs, rides and swims alike (railway#199). Never overwrites a Garmin stream."""
    hh = seed.get("hr_hist") or {}
    if not hh:
        return 0
    from ..metrics import segmentation
    acts = {a.external_id: a for a in db.query(models.Activity).filter(
        models.Activity.runner_id == rid, models.Activity.external_id.in_(list(hh))).all()}
    rows = {st.activity_id: st for st in db.query(models.ActivityStream).filter(
        models.ActivityStream.runner_id == rid,
        models.ActivityStream.activity_id.in_([a.id for a in acts.values()] or [-1])).all()}
    n = 0
    for ext, hist in hh.items():
        a = acts.get(ext)
        if a is None or not hist:
            continue
        st = rows.get(a.id)
        if st is None:
            db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=ext, segments_json=None, gps=False,
                                         quality_json={"hrHist": hist, "source": "apple",
                                                       "segVersion": segmentation.SEG_VERSION},
                                         created_at=E.now_iso()))
            n += 1
        elif not (st.quality_json or {}).get("hrHist"):
            st.quality_json = {**(st.quality_json or {}), "hrHist": hist}
            n += 1
    return n


def _apply_day_raw(db: DBSession, rid: str, seed: dict) -> int:
    """All-day heart rate and steps from any source (seed["day_raw"] = {date: {hr, steps}})
    and the night in detail where the source has it (seed["day_sleep"], the Apple Health
    export: hypnogram, falling asleep / waking), stored per day and computed by the own
    day metrics (dayload.py), oldest first."""
    raw = seed.get("day_raw") or {}
    nights = seed.get("day_sleep") or {}
    days = sorted(set(raw) | set(nights))
    if not days:
        return 0
    from ..metrics import dayload as DL
    for d in days:
        DL.store_raw(db, rid, d, raw.get(d), sleep=nights.get(d))
    for d in days:
        DL.update_day(db, rid, d)
    db.flush()
    return len(days)


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
    _apply_day_raw(db, rid, seed)
    _apply_hr_hist(db, rid, seed)
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
    # feedback #167 — today and yesterday are always fetched again: a sync early in the
    # morning stores the day before the watch has uploaded the night (sleep, HRV), and
    # a skipped date would stay without them all day ("předběžné · čeká na ranní data")
    fresh = {E.iso_date(E.today_date()), E.iso_date(E.today_date() - _dt.timedelta(days=1))}
    dates = frozenset(
        row[0] for row in db.query(models.DailyMetric.date).filter(models.DailyMetric.runner_id == rid).all()
        if row[0] not in fresh
    )
    last_act = db.query(func.max(models.Activity.started_at)).filter(models.Activity.runner_id == rid).scalar()
    return dates, last_act


def _refresh_recent_day(db: DBSession, rid: str, d: dict) -> None:
    """Feedback #167 — a day already stored (today / yesterday) gets the values that
    arrived since: empty fields are filled, the step count only grows, and a value the
    runner corrected by hand (original_* kept) is never overwritten."""
    row = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                              models.DailyMetric.date == d["date"]).first()
    if row is None:
        return
    for k, v in d.items():
        if k in ("id", "date", "runner_id", "source") or v is None or not hasattr(row, k):
            continue
        if getattr(row, f"original_{k}", None) is not None:
            continue                                  # hand-corrected
        cur = getattr(row, k)
        if cur is None or (k == "steps" and v > cur):
            setattr(row, k, v)


def _stored_twin(db: DBSession, rid: str, a: dict) -> bool:
    """A non-manual activity of the same sport on the same day and within 3 % of the
    duration (and distance, when both have one) — e.g. a run first imported from a file
    export under a different id. Keeps the wider sync window from duplicating sessions."""
    day, dur = str(a.get("started_at") or "")[:10], a.get("duration_min") or 0
    if not day or not dur:
        return False
    for x in db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.started_at == day,
                                              models.Activity.sport == (a.get("sport") or "running")):
        if x.provider == "manual" or not x.duration_min:
            continue
        if abs(x.duration_min - dur) > 0.03 * max(x.duration_min, dur):
            continue
        km, xkm = a.get("distance_km"), x.distance_km
        if km and xkm and abs(km - xkm) > 0.03 * max(km, xkm):
            continue
        return True
    return False


def _merge_seed(db: DBSession, rid: str, seed: dict, provider: str = "garmin") -> dict:
    """Additive, idempotent import: inserts only activities whose external_id
    is new and daily rows for dates the runner doesn't have yet. Nothing is
    deleted or overwritten — re-running an export never duplicates rows and
    never clobbers a manually edited day (unlike _apply_seed's full replace,
    which is right for a one-shot file export but wrong for repeat syncs)."""
    existing_rows = {
        a.external_id: a for a in db.query(models.Activity).filter(models.Activity.runner_id == rid).all() if a.external_id
    }
    existing_ext = set(existing_rows)
    existing_dates = {
        row[0] for row in db.query(models.DailyMetric.date).filter(models.DailyMetric.runner_id == rid).all()
    }
    added_a = added_d = 0
    for a in seed.get("activities", []):
        ext = a.get("external_id")
        if ext and ext in existing_ext:
            # Never overwrite an existing activity — but fill in run context it
            # was imported without (start time / place arrived in a later version).
            old = existing_rows.get(ext)
            if old is not None:
                for k in ("start_time", "start_lat", "start_lon"):
                    if getattr(old, k, None) is None and a.get(k) is not None:
                        setattr(old, k, a[k])
            continue
        if _stored_twin(db, rid, a):
            continue                                  # the same session already stored under another id
        row = {k: v for k, v in a.items() if k != "id"}
        row["runner_id"] = rid
        db.add(models.Activity(**row))
        db.flush()
        added_a += 1
        if ext:
            existing_ext.add(ext)
    recent = {E.iso_date(E.today_date()), E.iso_date(E.today_date() - _dt.timedelta(days=1))}
    for d in seed.get("daily_metrics", []):
        if d["date"] in existing_dates:
            if d["date"] in recent:
                _refresh_recent_day(db, rid, d)
            continue
        row = {k: v for k, v in d.items() if k != "id"}
        row["runner_id"] = rid
        db.add(models.DailyMetric(**row))
        added_d += 1
        existing_dates.add(d["date"])
    # sleep stages / efficiency for days already stored: only into empty fields
    fill = {f["date"]: f for f in seed.get("daily_fill") or []}
    if fill:
        for row in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                       models.DailyMetric.date.in_(list(fill))):
            for k, v in fill[row.date].items():
                if k != "date" and v is not None and getattr(row, k, None) is None:
                    setattr(row, k, v)
    db.flush()
    E.absorb_manual(db, rid)       # a watch recording replaces the same hand-logged session

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
    _apply_day_raw(db, rid, seed)
    _apply_hr_hist(db, rid, seed)
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


SYNC_LOOKBACK_DAYS = 14     # activities that reach Garmin late (another device, a later upload) still arrive
CROSS_BACKFILL_DAYS = 180   # one-time re-pull: cross-training before 2026-09-25 was never requested


def _download_and_merge(db: DBSession, rid: str, garmin) -> dict:
    skip_dates, since = _runner_history(db, rid)
    # v0.8.6: each sync starts SYNC_LOOKBACK_DAYS before the newest stored activity (merging is
    # idempotent by activity id), and once per runner the whole CROSS_BACKFILL_DAYS window is
    # requested again, so rides, swims and strength sessions from before cross-training was
    # imported arrive as well (summary only: sport, duration, heart rate, Garmin load)
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    meta = dict((runner.onboarding_json or {}) if runner else {})
    backfill = runner is not None and not meta.get("crossBackfill")
    if backfill:
        since = None
    elif since:
        try:
            since = (_dt.date.fromisoformat(since[:10]) - _dt.timedelta(days=SYNC_LOOKBACK_DAYS)).isoformat()
        except ValueError:
            pass
    # no sleep stages stored yet → pull 180 days of them once (feedback railway#33)
    has_stages = db.query(models.DailyMetric.id).filter(models.DailyMetric.runner_id == rid,
                                                         models.DailyMetric.deep_min.isnot(None)).first() is not None
    # v0.12.0 — the breathing rate while asleep: pulled once for the stored nights too
    resp_backfill = runner is not None and not meta.get("respBackfill")
    try:
        seed = garmin_live.download_seed(garmin, activity_days=CROSS_BACKFILL_DAYS, skip_dates=skip_dates,
                                         since_date=since,
                                         sleep_backfill_days=0 if (has_stages and not resp_backfill) else 180)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Nepodařilo se stáhnout data z Garminu: {e}")
    added = _merge_seed(db, rid, seed, provider="garmin")
    added["dayDetails"] = fetch_day_details(db, rid, garmin)
    if added["dayDetails"]:
        E.recompute_assessment(db, rid)        # the day's own load / resting HR feed the engine
    if backfill or resp_backfill:
        if backfill:
            meta["crossBackfill"] = E.iso_date(E.today_date())
        if resp_backfill:
            meta["respBackfill"] = E.iso_date(E.today_date())
        runner.onboarding_json = meta
        db.commit()
    return {"ok": True, "runner_id": rid, **added, "meta": seed.get("_meta")}


DAY_DETAIL_RECENT, DAY_DETAIL_BACKFILL = 3, 14
DAY_RAW_RETRY = _dt.timedelta(hours=20)


def _raw_done(row, now) -> bool:
    """An older day needs no new download: it has the all-day heart rate, or it was asked
    for it in the last DAY_RAW_RETRY (raw = {} — the watch had nothing for that day)."""
    if row is None or row.raw is None:
        return False
    if row.raw:
        return True
    try:
        return now - _dt.datetime.fromisoformat(row.fetched_at) < DAY_RAW_RETRY
    except (TypeError, ValueError):
        return False


def fetch_day_details(db: DBSession, rid: str, garmin, today=None) -> int:
    """Morning / evening report and the day outside training: the last nights and days in
    detail (hypnogram, all-day heart rate and steps). Today and the two days before are
    fetched again on every sync (the night and the day keep filling in); older days of the
    last 14 until each has its all-day heart rate. (Rows saved by the first reports had the
    night and the day but no heart rate, so "a row exists" is not "done": the day outside
    training needs 7 earlier days with it, v0.10.4.) Fills the daily Body Battery and
    stress average when the day row has none. Never raises."""
    try:
        today = today or E.today_date()
        rows = {r.date: r for r in db.query(models.DailyDetail).filter(models.DailyDetail.runner_id == rid).all()}
        now = _dt.datetime.fromisoformat(E.now_iso())
        days = DAY_DETAIL_BACKFILL
        n = 0
        for k in range(days):
            d = (today - _dt.timedelta(days=k)).isoformat()
            row = rows.get(d)
            if k >= DAY_DETAIL_RECENT and _raw_done(row, now):
                continue
            det = garmin_live.fetch_day_detail(garmin, d)
            got = bool(det.get("sleep") or det.get("day") or det.get("raw"))
            if not got and k < DAY_DETAIL_RECENT:
                continue
            if row is None:
                row = models.DailyDetail(runner_id=rid, date=d)
                db.add(row)
            row.sleep = det.get("sleep") or row.sleep
            row.day = det.get("day") or row.day
            # an older day the watch has no heart rate for: {} remembers the attempt (DAY_RAW_RETRY)
            row.raw = det.get("raw") or row.raw or ({} if k >= DAY_DETAIL_RECENT else None)
            row.fetched_at = E.now_iso()
            if not got:
                continue
            dm = db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid, models.DailyMetric.date == d).first()
            day = det.get("day") or {}
            if dm is not None:
                if dm.body_battery is None and (day.get("bbWake") or day.get("bbHigh")) is not None:
                    dm.body_battery = day.get("bbWake") or day.get("bbHigh")
                if dm.stress_avg is None and day.get("stressAvg") is not None:
                    dm.stress_avg = day["stressAvg"]
            n += 1
        db.flush()
        # own day metrics (dayload.py), oldest first: each day's reference uses the days before it
        from ..metrics import dayload as DL
        for k in range(days - 1, -1, -1):
            DL.update_day(db, rid, (today - _dt.timedelta(days=k)).isoformat())
        db.commit()
        return n
    except Exception:  # noqa: BLE001 — the report data must never break the sync
        db.rollback()
        return 0


def _store_session(db: DBSession, rid: str, garmin, auto_sync: bool = True) -> None:
    """Persist (or refresh) the runner's Garmin OAuth *session tokens* — never
    the password — so daily auto-sync and one-tap sync work without re-login.
    Called after a successful connect/MFA (opt-in) and after every token-based
    sync (to save the refreshed access token)."""
    try:
        blob, enc = garmin_live.seal_token(garmin)
    except Exception:  # noqa: BLE001 — a serialization failure must not break the import
        return
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
    now = E.now_iso()
    if row is None:
        row = models.GarminSession(runner_id=rid, token_blob=blob, encrypted=enc,
                                   auto_sync=auto_sync, created_at=now, last_sync_at=now, last_error=None)
        db.add(row)
    else:
        row.token_blob = blob
        row.encrypted = enc
        row.last_sync_at = now
        row.last_error = None
    db.commit()


DETAIL_DAYS, DETAIL_CAP = 60, 12   # every sync also fetches detailed data for recent runs missing it
HR_ONLY_SPORTS = ("cycling", "swimming")   # railway#199: their heart-rate trace for Intenzita


def fetch_new_details(db: DBSession, rid: str, garmin=None) -> dict | None:
    """Detailed per-second data (track, elevation, mechanics) for the last
    DETAIL_DAYS of runs that don't have it yet — part of every sync, so segment
    mechanics, terrain and weather context stay current without the "Detailní
    data" button (which remains for backfilling older history). Never raises:
    the sync itself has already succeeded."""
    try:
        own = None
        if garmin is None:
            own = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
            if own is None:
                return None
            garmin = garmin_live.resume_session(own.token_blob, bool(own.encrypted))
        out = _fetch_streams(db, rid, garmin, since_days=DETAIL_DAYS, cap=DETAIL_CAP)
        if own is not None:
            _store_session(db, rid, garmin, auto_sync=bool(own.auto_sync))   # keep a refreshed token
        return out
    except Exception:  # noqa: BLE001
        db.rollback()
        return None


def fetch_new_details_bg(rid: str) -> None:
    """BackgroundTasks wrapper for the one-tap sync: own session, never raises."""
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        fetch_new_details(db, rid)
    finally:
        db.close()


def _sync_from_stored(db: DBSession, rid: str, details: bool = True) -> dict:
    """Resume Garmin from the stored token, download+merge, fetch detailed data
    for new runs (details=True), then re-persist the (possibly refreshed) token.
    Raises 409 if there's no stored session and marks last_error + drops
    auto_sync on an auth failure so a revoked token stops retrying every morning."""
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
    if row is None:
        raise HTTPException(status_code=409, detail="Garmin není připojen pro automatickou synchronizaci — připojte ho nejdřív na stránce Data.")
    try:
        garmin = garmin_live.resume_session(row.token_blob, bool(row.encrypted))
    except garmin_live.AuthError as e:
        row.last_error = "Uložené přihlášení ke Garminu vypršelo — připojte ho prosím znovu."
        row.auto_sync = False
        db.commit()
        raise HTTPException(status_code=401, detail=row.last_error) from e
    result = _download_and_merge(db, rid, garmin)
    if details:
        result["details"] = fetch_new_details(db, rid, garmin)
    _store_session(db, rid, garmin, auto_sync=bool(row.auto_sync))
    return result


def auto_sync_all(session_factory) -> dict:
    """Called by the pre-07:00 scheduler: sync every runner who opted in. Runs
    each in isolation so one revoked token doesn't abort the rest."""
    db = session_factory()
    try:
        rids = [r.runner_id for r in db.query(models.GarminSession).filter(models.GarminSession.auto_sync == True).all()]  # noqa: E712
    finally:
        db.close()
    synced = failed = 0
    for rid in rids:
        db = session_factory()
        try:
            _sync_from_stored(db, rid)
            synced += 1
        except Exception:  # noqa: BLE001 — per-runner isolation; error already recorded on the row
            failed += 1
        finally:
            db.close()
    return {"synced": synced, "failed": failed, "total": len(rids)}


@router.post("/garmin/connect", dependencies=[Depends(verify_csrf)])
def garmin_connect(body: schemas.GarminCredsRequest,
                   user: models.User = Depends(require_role("runner")),
                   db: DBSession = Depends(get_db)):
    """Step 1 of the direct Garmin download. Logs in with the runner's own
    credentials. The password is used only here and never stored. If the
    account needs MFA, returns {mfa_required, mfa_token} and the client posts
    the code to /garmin/connect/mfa. Otherwise downloads + merges straight away.
    The download is incremental — only days without history are fetched. When
    `remember` is set, the resulting OAuth session tokens (not the password) are
    saved for daily auto-sync + one-tap sync."""
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
        _PENDING_MFA[token] = {"garmin": garmin, "state": state, "rid": rid, "at": time.time(), "remember": bool(body.remember)}
        return {"mfa_required": True, "mfa_token": token}
    result = _download_and_merge(db, rid, garmin)
    if body.remember:
        _store_session(db, rid, garmin, auto_sync=True)
    return {**result, "remembered": bool(body.remember)}


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
    remember = bool(body.remember or pending.get("remember"))
    result = _download_and_merge(db, user.runner_id, pending["garmin"])
    if remember:
        _store_session(db, user.runner_id, pending["garmin"], auto_sync=True)
    return {**result, "remembered": remember}


def _garmin_status(db: DBSession, rid: str) -> dict:
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
    if row is None:
        return {"connected": False, "auto_sync": False, "last_sync_at": None, "last_error": None}
    return {"connected": True, "auto_sync": bool(row.auto_sync),
            "last_sync_at": row.last_sync_at, "last_error": row.last_error,
            "encrypted": bool(row.encrypted)}


@router.get("/garmin/status")
def garmin_status(user: models.User = Depends(require_role("runner")),
                  db: DBSession = Depends(get_db)):
    """Whether a stored Garmin session exists, whether daily auto-sync is on,
    and the last sync time / error — drives the Dnes sync button + Data panel."""
    return _garmin_status(db, user.runner_id)


@router.post("/garmin/sync", dependencies=[Depends(verify_csrf)])
def garmin_sync(background: BackgroundTasks, user: models.User = Depends(require_role("runner")),
                db: DBSession = Depends(get_db)):
    """One-tap 'Synchronizovat' — resume from the stored session token (no
    password) and pull anything new. Requires a prior connect with 'remember'."""
    result = _sync_from_stored(db, user.runner_id, details=False)
    background.add_task(fetch_new_details_bg, user.runner_id)     # detailed data for new runs, off the request
    background.add_task(coach_texts.refresh_bg, user.runner_id)   # new data → the day's AI texts follow
    return {**result, "status": _garmin_status(db, user.runner_id)}


@router.post("/garmin/auto-sync", dependencies=[Depends(verify_csrf)])
def garmin_auto_sync(body: schemas.GarminAutoSyncRequest,
                     user: models.User = Depends(require_role("runner")),
                     db: DBSession = Depends(get_db)):
    """Turn the daily pre-07:00 auto-sync on/off without disconnecting."""
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == user.runner_id).first()
    if row is None:
        raise HTTPException(status_code=409, detail="Garmin není připojen — připojte ho nejdřív.")
    row.auto_sync = bool(body.enabled)
    db.commit()
    return _garmin_status(db, user.runner_id)


@router.delete("/garmin/session", dependencies=[Depends(verify_csrf)])
def garmin_disconnect(user: models.User = Depends(require_role("runner")),
                      db: DBSession = Depends(get_db)):
    """Forget the stored Garmin session tokens (stops auto-sync). The account's
    refresh token can additionally be revoked from Garmin's own settings."""
    db.query(models.GarminSession).filter(models.GarminSession.runner_id == user.runner_id).delete()
    db.commit()
    return {"connected": False, "auto_sync": False, "last_sync_at": None, "last_error": None}


def _backfill_start(a, records: list[dict]) -> None:
    """Fill a run's missing start place (first GPS fix, rounded to ~1 km) and local
    start time (first absolute timestamp) from its detail stream — gives older
    runs the context the weather lookup needs."""
    if a.start_lat is None:
        fix = next((r for r in records if r.get("lat") is not None and r.get("lon") is not None), None)
        if fix:
            a.start_lat, a.start_lon = round(fix["lat"], 2), round(fix["lon"], 2)
    if a.start_time is None:
        t0 = next((r.get("t_ms") for r in records if r.get("t_ms")), None)
        if t0:
            from datetime import datetime
            a.start_time = datetime.fromtimestamp(t0 / 1000, tz=E.LOCAL_TZ).strftime("%H:%M")


def _fetch_streams(db: DBSession, rid: str, garmin, since_days: int = 3650, cap: int = 25, retry_failed: bool = False) -> dict:
    """Phase 4 — pull the 1 Hz stream for running activities that don't yet have
    one (oldest-first within the window), run Stage-S1 quality control, store the
    derived elevation profile + segments, and back-fill Activity.elevation_profile.

    Fetches at most `cap` per call (each Garmin detail request is slow, so a batch
    keeps the HTTP request from timing out) and reports `remaining` so the caller
    can loop until the whole window is backfilled. Idempotent: already-fetched
    activities are skipped, so repeated calls progressively fill the history.
    Rows segmented by an older segmenter (quality_json.segVersion below
    segmentation.SEG_VERSION) are re-fetched and overwritten in place, so every
    run is scored by the same code. Streams that fail Stage-S1 quality control
    (too little running / poor coverage) keep their elevation profile but get no
    segments, so they never reach mechanics scoring. Per-activity errors are
    isolated."""
    from ..metrics import segmentation, stream_qc
    if retry_failed:
        # Drop failure tombstones (no segments + quality.failed) so they're retried.
        for st in db.query(models.ActivityStream).filter(
                models.ActivityStream.runner_id == rid,
                models.ActivityStream.segments_json.is_(None)).all():
            if (st.quality_json or {}).get("failed"):
                db.delete(st)
        db.commit()
    cut = E.day_ago(since_days)
    activities = (
        db.query(models.Activity)
        .filter(models.Activity.runner_id == rid, models.Activity.external_id.isnot(None),
                models.Activity.started_at > cut, models.Activity.sport.in_(("running",) + HR_ONLY_SPORTS))
        .order_by(models.Activity.started_at.asc()).all()  # oldest first → baseline fills first
    )
    rows = {st.activity_id: st for st in db.query(models.ActivityStream)
            .filter(models.ActivityStream.runner_id == rid).all()}

    def current(st):
        q = st.quality_json or {}
        return bool(q.get("failed")) or (q.get("segVersion") or 1) >= segmentation.SEG_VERSION

    todo = [a for a in activities if a.id not in rows or not current(rows[a.id])]
    have_before = len(activities) - len(todo)
    fetched = stored = failed = rejected = 0
    stalled = False
    for a in todo[:cap]:
        old = rows.get(a.id)
        if a.sport in HR_ONLY_SPORTS:
            # railway#199 — cycling / swimming: only the time at each heart rate, for the
            # hard minutes in Intenzita (no mechanics, no segments)
            try:
                hist = stream_qc.hr_histogram(garmin_live.fetch_details(garmin, a.external_id))
                fetched += 1
            except Exception as e:  # noqa: BLE001
                if any(x in str(e).lower() for x in ("429", "too many", "rate")):
                    stalled = True
                    break
                failed += 1
                hist = None
            st = old or models.ActivityStream(activity_id=a.id, runner_id=rid)
            st.external_id = a.external_id
            st.quality_json = {"hrHist": hist, "sport": a.sport, "segVersion": segmentation.SEG_VERSION,
                               **({} if hist else {"failed": True})}
            st.segments_json = None
            st.gps = False
            st.created_at = E.now_iso()
            if old is None:
                db.add(st)
            stored += 1 if hist else 0
            continue
        try:
            res = stream_qc.process(garmin_live.fetch_details(garmin, a.external_id))
            segs = segmentation.segment(res.get("records") or [], surface=a.surface) if res.get("accepted") else []
            fetched += 1
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "429" in msg or "too many" in msg or "rate" in msg:
                # Rate-limited by Garmin — stop the batch WITHOUT a tombstone so
                # these retry later; the caller shows "try again shortly".
                stalled = True
                break
            failed += 1
            if old is not None:
                # A stale row whose refresh failed keeps its previous segments;
                # stamp it current so the backfill doesn't retry it forever.
                old.quality_json = {**(old.quality_json or {}), "segVersion": segmentation.SEG_VERSION,
                                    "refreshFailed": str(e)[:200]}
                continue
            # A specific activity has no usable detail (manual entry, odd type,
            # deleted stream…). Tombstone it (segments_json NULL) so the backfill
            # advances instead of retrying the same run forever.
            db.add(models.ActivityStream(
                activity_id=a.id, runner_id=rid, external_id=a.external_id,
                elevation_profile=None, quality_json={"failed": True, "error": str(e)[:200]},
                segments_json=None, gps=False, created_at=E.now_iso(),
            ))
            continue
        prof = res.get("elevation_profile") or None
        quality = {**(res.get("quality") or {}), "accepted": bool(res.get("accepted")),
                   "segVersion": segmentation.SEG_VERSION}
        if not res.get("accepted"):
            rejected += 1
        st = old or models.ActivityStream(activity_id=a.id, runner_id=rid)
        st.external_id = a.external_id
        st.elevation_profile = prof
        st.quality_json = quality
        st.segments_json = segs or None
        st.gps = bool(res.get("gps"))
        st.created_at = E.now_iso()
        if old is None:
            db.add(st)
        if prof and not a.elevation_profile:
            a.elevation_profile = prof
        _backfill_start(a, res.get("records") or [])
        stored += 1
    db.commit()
    if stored:
        E.recompute_assessment(db, rid)
    processed = stored + failed  # tombstoned / refreshed / stored are consumed from `todo`
    return {"fetched": fetched, "stored": stored, "failed": failed, "rejected": rejected, "stalled": stalled,
            "remaining": max(0, len(todo) - processed), "total": len(activities),
            "have": have_before + processed}


@router.post("/garmin/terrain", dependencies=[Depends(verify_csrf)])
def garmin_terrain(user: models.User = Depends(require_role("runner")),
                   db: DBSession = Depends(get_db)):
    """Live-sample the surface/trail of the runner's NEWEST run from its GPS track
    (OSM via Overpass worldwide; ČÚZK ZABAGED preferred in CZ). Stores the
    classification and refines the run's surface bucket. Requires a stored Garmin
    session (streams carry the lat/lon track)."""
    from ..metrics import geo_sample, stream_qc
    rid = user.runner_id
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
    if row is None:
        raise HTTPException(status_code=409, detail="Garmin není připojen — připojte ho nejdřív na stránce Data.")
    try:
        garmin = garmin_live.resume_session(row.token_blob, bool(row.encrypted))
    except garmin_live.AuthError as e:
        raise HTTPException(status_code=401, detail="Uložené přihlášení ke Garminu vypršelo — připojte ho prosím znovu.") from e
    newest = (
        db.query(models.Activity)
        .filter(models.Activity.runner_id == rid, models.Activity.external_id.isnot(None),
                models.Activity.sport == "running")
        .order_by(models.Activity.started_at.desc()).first()
    )
    if newest is None:
        raise HTTPException(status_code=404, detail="Žádný běh k analýze.")
    try:
        records = stream_qc.process(garmin_live.fetch_details(garmin, newest.external_id)).get("records") or []
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Nepodařilo se stáhnout trať z Garminu: {e}")
    track = [(r["lat"], r["lon"]) for r in records if r.get("lat") is not None and r.get("lon") is not None]
    if not track:
        raise HTTPException(status_code=422, detail="Tento běh nemá GPS trať (např. běžecký pás).")
    result = geo_sample.sample_surface(track)
    if not result:
        raise HTTPException(status_code=502, detail="Nepodařilo se určit povrch trasy (služba nedostupná).")
    st = db.query(models.ActivityStream).filter(models.ActivityStream.activity_id == newest.id).first()
    if st is None:
        st = models.ActivityStream(activity_id=newest.id, runner_id=rid, external_id=newest.external_id,
                                   created_at=E.now_iso())
        db.add(st)
    st.surface_json = result
    eng_surface = geo_sample.to_engine_surface(result)
    if eng_surface:
        newest.surface = eng_surface
        if st.segments_json:  # keep the stored segments in step with the refined surface
            st.segments_json = [{**sg, "surface": eng_surface} for sg in st.segments_json]
    db.commit()
    E.recompute_assessment(db, rid)
    return {"ok": True, "activity": {"title": newest.title, "date": newest.started_at},
            "surface": result, "appliedSurface": eng_surface}


@router.post("/garmin/streams", dependencies=[Depends(verify_csrf)])
def garmin_streams(days: int = 3650, cap: int = 25, retry: int = 0,
                   user: models.User = Depends(require_role("runner")),
                   db: DBSession = Depends(get_db)):
    """Fetch detailed per-second data (track, elevation, mechanics) for runs using
    the stored Garmin session — unlocks terrain-aware load and within-run
    segmentation. Backfills the whole window (default ~10 y) in batches of `cap`;
    the response's `remaining` lets the client loop until done. Requires a prior
    connect with 'remember'."""
    rid = user.runner_id
    row = db.query(models.GarminSession).filter(models.GarminSession.runner_id == rid).first()
    if row is None:
        raise HTTPException(status_code=409, detail="Garmin není připojen — připojte ho nejdřív na stránce Data.")
    try:
        garmin = garmin_live.resume_session(row.token_blob, bool(row.encrypted))
    except garmin_live.AuthError as e:
        raise HTTPException(status_code=401, detail="Uložené přihlášení ke Garminu vypršelo — připojte ho prosím znovu.") from e
    return _fetch_streams(db, rid, garmin, since_days=days, cap=max(1, min(cap, 60)), retry_failed=bool(retry))
