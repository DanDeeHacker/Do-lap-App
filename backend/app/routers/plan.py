"""Plán od trenéra (owner request 2026-10-12) — the runner's side and the coach's overview.

Runner (signed in): the coach mode switch, the plan's sessions, the import preview
(text / photo) and its confirmation, the calendar link (iCal), the pairing with what was
run, and the coach's overview link (explicit consent, revocable, every open logged).

Coach (/trener/<token>, no account): the runner's overview — readiness, sleep, HRV, resting
HR and pain trends, the days and activities, the plan with the app's verdicts — and the
plan itself, editable 6 months ahead; a day the coach saves replaces what was planned
there from other sources.

The app only evaluates the plan (metrics/coach_plan.py); it never changes it on its own.
"""
import logging
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import models, security
from .. import plan_import as PI
from ..db import SessionLocal, get_db
from ..deps import ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf
from ..metrics import coach_plan as CP
from ..metrics import engine as E

log = logging.getLogger("dosslap.plan")
router = APIRouter(tags=["plan"])

LINK_DAYS = 183                 # the overview link lasts 6 months (the plan's horizon), revocable any time
COACH_HORIZON = 183             # the coach plans up to 6 months ahead
FIELDS = ("kind", "title", "km", "duration_min", "z4_min", "intervals", "target", "ascent_m", "descent_m", "notes")


class SessionIn(BaseModel):
    date: str
    kind: str
    title: str | None = Field(None, max_length=120)
    km: float | None = Field(None, ge=0, le=200)
    duration_min: float | None = Field(None, ge=0, le=900)
    z4_min: float | None = Field(None, ge=0, le=300)
    intervals: str | None = Field(None, max_length=160)
    target: str | None = Field(None, max_length=120)
    ascent_m: float | None = Field(None, ge=0, le=9000)
    descent_m: float | None = Field(None, ge=0, le=9000)
    notes: str | None = Field(None, max_length=1000)
    seq: int | None = Field(None, ge=0, le=5)


class ModeIn(BaseModel):
    on: bool
    name: str | None = Field(None, max_length=80)


class ImportIn(BaseModel):
    text: str | None = Field(None, max_length=20000)
    image: str | None = Field(None, max_length=9_000_000)     # data:image/...;base64 (≈ 6 MB)
    week: str | None = None


class ConfirmIn(BaseModel):
    sessions: list[SessionIn] = Field(..., max_length=80)
    via: str | None = None


class PairIn(BaseModel):
    activity_id: int | None = None    # None = automatic again, 0 = not done


class CopyIn(BaseModel):
    source: str                       # Monday of the week to copy
    target: str                       # Monday of the week to fill
    repeat: int = Field(1, ge=1, le=26)


class FeedIn(BaseModel):
    url: str = Field(..., max_length=2000)


class LinkIn(BaseModel):
    coach_name: str | None = Field(None, max_length=80)
    consent: bool


class DayIn(BaseModel):
    sessions: list[SessionIn] = Field(..., max_length=4)


# ------------------------------------------------------------------ helpers
def _iso(v: str) -> str:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatné datum")


def _row(r: models.PlannedSession) -> dict:
    return {"id": r.id, "date": r.date, "seq": r.seq or 0, "kind": r.kind, "title": r.title, "km": r.km,
            "duration_min": r.duration_min, "z4_min": r.z4_min, "intervals": r.intervals, "target": r.target,
            "ascent_m": r.ascent_m, "descent_m": r.descent_m, "notes": r.notes, "source": r.source,
            "activity_id": r.activity_id}


def _rows(db: DBSession, rid: str, lo: str | None = None, hi: str | None = None) -> list:
    P = models.PlannedSession
    q = db.query(P).filter(P.runner_id == rid)
    if lo:
        q = q.filter(P.date >= lo)
    if hi:
        q = q.filter(P.date <= hi)
    return [_row(r) for r in q.order_by(P.date.asc(), P.seq.asc(), P.id.asc()).all()]


def _check_session(s: SessionIn) -> dict:
    if s.kind not in CP.KINDS:
        raise HTTPException(status_code=422, detail="Neznámý typ tréninku")
    d = _iso(s.date)
    t = E.today_date()
    if not -400 <= (date.fromisoformat(d) - t).days <= 370:
        raise HTTPException(status_code=422, detail="Datum je mimo rozsah plánu")
    out = {k: getattr(s, k) for k in FIELDS}
    out["date"] = d
    for k in ("title", "intervals", "target", "notes"):
        out[k] = (out[k] or "").strip() or None
    if s.kind == "rest":
        out.update({k: None for k in ("km", "duration_min", "z4_min", "intervals", "ascent_m", "descent_m")})
    return out


def _next_seq(db: DBSession, rid: str, d: str) -> int:
    P = models.PlannedSession
    n = db.query(P).filter(P.runner_id == rid, P.date == d).count()
    return min(n, 5)


def _recompute_bg(rid: str) -> None:
    """The guidance (this week's target = the plan, Výhled na zítra) follows a plan change."""
    db = SessionLocal()
    try:
        E.recompute_assessment(db, rid, data_changed=False)
    except Exception:  # noqa: BLE001
        log.exception("Recompute after a plan change failed for %s", rid)
    finally:
        db.close()


def _sync_bg(rid: str) -> None:
    db = SessionLocal()
    try:
        r = db.query(models.Runner).filter(models.Runner.id == rid).first()
        if r and r.plan_feed_url:
            PI.sync_feed(db, r, E.now_iso(), E.today_date())
            E.recompute_assessment(db, rid, data_changed=False)
    except Exception:  # noqa: BLE001
        log.exception("Plan feed sync failed for %s", rid)
    finally:
        db.close()


def sync_all_feeds(session_factory) -> dict:
    """Every runner's calendar link, once each morning (main._garmin_autosync_loop)."""
    db = session_factory()
    n = ok = 0
    try:
        for r in db.query(models.Runner).filter(models.Runner.plan_feed_url.isnot(None), models.Runner.coach_mode.is_(True)).all():
            n += 1
            try:
                st = PI.sync_feed(db, r, E.now_iso(), E.today_date())
                ok += bool(st.get("ok"))
                E.recompute_assessment(db, r.id, data_changed=False)
            except Exception:  # noqa: BLE001
                log.exception("Plan feed sync failed for %s", r.id)
                db.rollback()
    finally:
        db.close()
    return {"feeds": n, "ok": ok}


def _evaluation(db: DBSession, runner: models.Runner) -> tuple:
    """(guidance, coach block, the plan evaluated now) — the stored assessment's rooms and
    rules with the plan as it is this moment (an edit needs no recompute to show)."""
    a = E.get_or_refresh_assessment(db, runner.id)
    g = a.get("guidance") or {}
    coach = g.get("coach")
    if runner.coach_mode and g and not coach:
        a = E.recompute_assessment(db, runner.id, data_changed=False)
        g = a.get("guidance") or {}
        coach = g.get("coach")
    if not coach:
        return g, None, None
    ctx = coach["ctx"]
    lo = (date.fromisoformat(ctx["weekStart"]) - timedelta(days=7)).isoformat()
    ev = CP.evaluate(ctx, g.get("outlook") or {}, _rows(db, runner.id, lo=lo), ctx.get("acts") or [])
    return g, coach, ev


def _body_days(db: DBSession, rid: str, lo: str, hi: str) -> tuple:
    """(readiness by day from the daily engine snapshots, the day's highest pain from the diary)."""
    rd = {}
    for s in (db.query(models.EngineDailySnapshot).filter(models.EngineDailySnapshot.runner_id == rid,
                                                          models.EngineDailySnapshot.date >= lo,
                                                          models.EngineDailySnapshot.date <= hi).all()):
        v = (s.features_json or {}).get("readiness")
        if v is not None:
            rd[s.date] = v
    pain = {}
    for c in (db.query(models.Checkin).filter(models.Checkin.runner_id == rid, models.Checkin.submitted_at >= lo,
                                              models.Checkin.submitted_at <= hi + "T23:59:59").all()):
        d = (c.submitted_at or "")[:10]
        if c.pain_score is not None:
            pain[d] = max(pain.get(d, 0), c.pain_score)
    return rd, pain


def _adherence(db: DBSession, rid: str, g: dict, coach: dict, ev: dict) -> list:
    days = ev["days"]
    ws = coach["ctx"]["weekStart"]
    rd, pain = _body_days(db, rid, days[0]["date"], coach["ctx"]["date"])
    t_iso = coach["ctx"]["date"]
    score = g.get("readinessScore")
    if score is not None:
        rd[t_iso] = score
    out = []
    for wk in ([d for d in days if d["date"] < ws], [d for d in days if ws <= d["date"] <= t_iso]):
        if wk:
            out.append(CP.adherence(wk, coach["ctx"].get("acts") or [], coach.get("safeDays") or {}, rd, pain))
    return out


def _mask(url: str | None) -> str | None:
    if not url:
        return None
    u = url.split("?")[0]
    return (u[:38] + "…") if len(u) > 40 else u


def _links(db: DBSession, rid: str) -> list:
    now = E.now_iso()
    rows = (db.query(models.CoachLink).filter(models.CoachLink.runner_id == rid, models.CoachLink.revoked_at.is_(None))
            .order_by(models.CoachLink.created_at.desc()).all())
    return [{"token": r.token, "coachName": r.coach_name, "createdAt": r.created_at, "expiresAt": r.expires_at,
             "lastSeenAt": r.last_seen_at, "path": f"/trener/{r.token}"} for r in rows if (r.expires_at or "") > now]


def _state(db: DBSession, runner: models.Runner, background: BackgroundTasks | None = None) -> dict:
    out = {"on": bool(runner.coach_mode), "name": runner.coach_name,
           "feed": {"url": _mask(runner.plan_feed_url), "set": bool(runner.plan_feed_url),
                    "status": runner.plan_feed_status},
           "links": _links(db, runner.id), "kinds": {k: v["label"] for k, v in CP.KINDS.items()}}
    if not runner.coach_mode:
        return out
    if background is not None and PI.feed_stale(runner, datetime.now()):
        background.add_task(_sync_bg, runner.id)
        out["feed"]["refreshing"] = True
    g, coach, ev = _evaluation(db, runner)
    if not coach:
        out["unavailable"] = True
        return out
    ctx = coach["ctx"]
    out.update({"date": ctx["date"], "weekStart": ctx["weekStart"], "eval": ev,
                "adherence": _adherence(db, runner.id, g, coach, ev), "trend": coach.get("trend"),
                "readiness": ctx.get("readinessShown"), "alt": ctx.get("alt"),
                "limits": {c: ((g.get("week") or {}).get("channels") or {}).get(c, {}).get("ceiling7")
                           for c in CP.CHS},
                "acts": [{k: a.get(k) for k in ("id", "date", "run", "sport", "km", "durationMin", "title")}
                         for a in ctx.get("acts") or [] if a["date"] >= ctx["weekStart"]]})
    return out


def _runner(db: DBSession, rid: str) -> models.Runner:
    return or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")


# ------------------------------------------------------------------ the runner's side
@router.get("/api/runners/{rid}/plan")
def get_plan(rid: str, background: BackgroundTasks, user: models.User = Depends(get_current_user),
             db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    r = _runner(db, rid)
    out = _state(db, r, background if (user.runner_id == rid) else None)
    if user.runner_id != rid:
        out.pop("links", None)
        out["feed"].pop("url", None)
    return out


@router.put("/api/runners/{rid}/plan/mode", dependencies=[Depends(verify_csrf)])
def set_mode(rid: str, body: ModeIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Coach mode on → the app's own cycle steps aside and the plan is evaluated; off → the
    app's recommendation and cycle as before (the plan stays stored)."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    r.coach_mode = bool(body.on)
    if body.name is not None:
        r.coach_name = body.name.strip() or None
    db.commit()
    E.recompute_assessment(db, rid, data_changed=False)
    return _state(db, r)


@router.post("/api/runners/{rid}/plan/sessions", dependencies=[Depends(verify_csrf)])
def add_session(rid: str, body: SessionIn, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    v = _check_session(body)
    now = E.now_iso()
    db.add(models.PlannedSession(runner_id=rid, seq=body.seq if body.seq is not None else _next_seq(db, rid, v["date"]),
                                 source="manual", created_at=now, updated_at=now, **v))
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.patch("/api/runners/{rid}/plan/sessions/{sid}", dependencies=[Depends(verify_csrf)])
def edit_session(rid: str, sid: int, body: SessionIn, background: BackgroundTasks,
                 user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    s = or_404(db.query(models.PlannedSession).filter(models.PlannedSession.id == sid,
                                                      models.PlannedSession.runner_id == rid).first(), "Trénink nenalezen")
    for k, val in _check_session(body).items():
        setattr(s, k, val)
    if s.source == "ics":
        s.source = "manual"                     # the runner's edit survives the next calendar pull
    s.updated_at = E.now_iso()
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.delete("/api/runners/{rid}/plan/sessions/{sid}", dependencies=[Depends(verify_csrf)])
def delete_session(rid: str, sid: int, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                   db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    s = or_404(db.query(models.PlannedSession).filter(models.PlannedSession.id == sid,
                                                      models.PlannedSession.runner_id == rid).first(), "Trénink nenalezen")
    db.delete(s)
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.post("/api/runners/{rid}/plan/sessions/{sid}/pair", dependencies=[Depends(verify_csrf)])
def pair_session(rid: str, sid: int, body: PairIn, background: BackgroundTasks,
                 user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    s = or_404(db.query(models.PlannedSession).filter(models.PlannedSession.id == sid,
                                                      models.PlannedSession.runner_id == rid).first(), "Trénink nenalezen")
    if body.activity_id:
        or_404(db.query(models.Activity).filter(models.Activity.id == body.activity_id,
                                                models.Activity.runner_id == rid).first(), "Aktivita nenalezena")
    s.activity_id = body.activity_id
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.post("/api/runners/{rid}/plan/copy-week", dependencies=[Depends(verify_csrf)])
def copy_week(rid: str, body: CopyIn, background: BackgroundTasks, user: models.User = Depends(get_current_user),
              db: DBSession = Depends(get_db)):
    """Last week's plan into this one (or any week into the next N): fills only empty days."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    _copy(db, rid, body, "manual")
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


def _copy(db: DBSession, rid: str, body: CopyIn, source: str, overwrite: bool = False) -> int:
    src, dst = date.fromisoformat(_iso(body.source)), date.fromisoformat(_iso(body.target))
    src, dst = src - timedelta(days=src.weekday()), dst - timedelta(days=dst.weekday())
    rows = _rows(db, rid, src.isoformat(), (src + timedelta(days=6)).isoformat())
    P = models.PlannedSession
    now, n = E.now_iso(), 0
    for w in range(body.repeat):
        base = dst + timedelta(days=7 * w)
        for k in range(7):
            d_src, d_dst = (src + timedelta(days=k)).isoformat(), (base + timedelta(days=k)).isoformat()
            day = [x for x in rows if x["date"] == d_src]
            if not day:
                continue
            have = db.query(P).filter(P.runner_id == rid, P.date == d_dst)
            if have.count():
                if not overwrite:
                    continue
                have.delete(synchronize_session=False)
            for x in day:
                db.add(P(runner_id=rid, date=d_dst, seq=x["seq"], source=source, created_at=now, updated_at=now,
                         **{f: x[f] for f in FIELDS}))
                n += 1
    return n


@router.post("/api/runners/{rid}/plan/import", dependencies=[Depends(verify_csrf)])
def import_preview(rid: str, body: ImportIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Text or a photo → a PREVIEW of the sessions (nothing is saved), each day with the
    verdict it would get, and what would be replaced."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    t = E.today_date()
    ws = date.fromisoformat(_iso(body.week)) if body.week else t - timedelta(days=t.weekday())
    ws = ws - timedelta(days=ws.weekday())
    try:
        if body.image:
            res = PI.import_photo(body.image, ws)
        elif body.text and body.text.strip():
            res = PI.import_text(body.text, ws)
        else:
            raise HTTPException(status_code=422, detail="Vložte text plánu nebo fotku.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    sess = res["sessions"]
    if not sess:
        raise HTTPException(status_code=422, detail="V textu jsme nenašli žádný den s tréninkem. Začněte řádek dnem "
                                                    "(Po, Út … nebo 12. 10.).")
    res["preview"] = _preview(db, r, sess)
    res["week"] = ws.isoformat()
    return res


def _preview(db: DBSession, runner: models.Runner, sess: list) -> dict | None:
    """The verdicts the imported days would get, the rest of the plan kept as it is."""
    g, coach, _ev = _evaluation(db, runner)
    if not coach:
        return None
    ctx = coach["ctx"]
    dates = {s["date"] for s in sess}
    lo = (date.fromisoformat(ctx["weekStart"]) - timedelta(days=7)).isoformat()
    keep = [x for x in _rows(db, runner.id, lo=lo) if x["date"] not in dates or x["source"] == "coach"]
    coach_days = {x["date"] for x in keep if x["source"] == "coach"}
    new = [{**s, "id": -(i + 1), "source": "import"} for i, s in enumerate(sess) if s["date"] not in coach_days]
    ev = CP.evaluate(ctx, g.get("outlook") or {}, keep + new, ctx.get("acts") or [])
    verdicts = {}
    for d in ev["days"]:
        for it in d["sessions"]:
            if it["id"] is not None and it["id"] < 0:
                verdicts[str(-it["id"] - 1)] = {"verdict": it.get("verdict"), "over": it.get("over"), "fit": it.get("fit"),
                                                "why": it.get("why"), "move": it.get("move")}
    replaced = [x for x in _rows(db, runner.id, lo=lo) if x["date"] in dates and x["source"] != "coach"]
    return {"verdicts": verdicts, "overDays": ev["week"]["overDays"], "message": ev["message"],
            "replaced": len(replaced), "coachDays": sorted(coach_days & dates)}


@router.post("/api/runners/{rid}/plan/confirm", dependencies=[Depends(verify_csrf)])
def import_confirm(rid: str, body: ConfirmIn, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                   db: DBSession = Depends(get_db)):
    """Save the confirmed preview: the imported days replace what the runner had planned there
    (a day the coach set in the overview stays the coach's)."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    rows = [_check_session(s) for s in body.sessions]
    P = models.PlannedSession
    dates = {x["date"] for x in rows}
    coach_days = {x.date for x in db.query(P.date).filter(P.runner_id == rid, P.source == "coach", P.date.in_(dates))}
    (db.query(P).filter(P.runner_id == rid, P.date.in_(dates - coach_days), P.source != "coach")
     .delete(synchronize_session=False))
    src = "photo" if body.via == "photo" else "text"
    now, seq = E.now_iso(), {}
    for x in rows:
        if x["date"] in coach_days:
            continue
        seq[x["date"]] = seq.get(x["date"], -1) + 1
        db.add(P(runner_id=rid, seq=seq[x["date"]], source=src, created_at=now, updated_at=now, **x))
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.put("/api/runners/{rid}/plan/feed", dependencies=[Depends(verify_csrf)])
def set_feed(rid: str, body: FeedIn, background: BackgroundTasks, user: models.User = Depends(get_current_user),
             db: DBSession = Depends(get_db)):
    """The calendar link (iCal / webcal) — checked, then pulled right away."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    try:
        url = PI.check_url(body.url)
    except PI.FeedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    r.plan_feed_url = url
    r.plan_feed_status = None
    db.commit()
    st = PI.sync_feed(db, r, E.now_iso(), E.today_date())
    if st.get("ok"):
        background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.post("/api/runners/{rid}/plan/feed/sync", dependencies=[Depends(verify_csrf)])
def sync_feed_now(rid: str, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                  db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    if not r.plan_feed_url:
        raise HTTPException(status_code=422, detail="Kalendář není připojený.")
    PI.sync_feed(db, r, E.now_iso(), E.today_date())
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.delete("/api/runners/{rid}/plan/feed", dependencies=[Depends(verify_csrf)])
def drop_feed(rid: str, background: BackgroundTasks, user: models.User = Depends(get_current_user),
              db: DBSession = Depends(get_db)):
    """Disconnect the calendar: its upcoming sessions go, the past ones stay for the adherence."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    r.plan_feed_url, r.plan_feed_status = None, None
    P = models.PlannedSession
    db.query(P).filter(P.runner_id == rid, P.source == "ics", P.date >= E.iso_date(E.today_date())).delete(synchronize_session=False)
    db.commit()
    background.add_task(_recompute_bg, rid)
    return _state(db, r)


@router.post("/api/runners/{rid}/plan/coach-link", dependencies=[Depends(verify_csrf)])
def create_link(rid: str, body: LinkIn, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """The coach's overview link — only with the runner's explicit consent (health data,
    GDPR art. 9); valid 6 months, revocable at any time."""
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    if not body.consent:
        raise HTTPException(status_code=422, detail="Bez souhlasu odkaz nevytvoříme.")
    now = datetime.now(E.LOCAL_TZ)
    db.add(models.CoachLink(token=secrets.token_urlsafe(24), runner_id=rid,
                            coach_name=(body.coach_name or r.coach_name or "").strip() or None,
                            created_at=now.isoformat(timespec="seconds"),
                            expires_at=(now + timedelta(days=LINK_DAYS)).isoformat(timespec="seconds")))
    db.commit()
    return _state(db, r)


@router.delete("/api/runners/{rid}/plan/coach-link/{token}", dependencies=[Depends(verify_csrf)])
def revoke_link(rid: str, token: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    r = _runner(db, rid)
    link = or_404(db.query(models.CoachLink).filter(models.CoachLink.token == token,
                                                    models.CoachLink.runner_id == rid).first(), "Odkaz nenalezen")
    link.revoked_at = E.now_iso()
    db.commit()
    return _state(db, r)


# ------------------------------------------------------------------ the coach's overview
def _link(db: DBSession, token: str) -> models.CoachLink:
    link = db.query(models.CoachLink).filter(models.CoachLink.token == token).first()
    if link is None or link.revoked_at or (link.expires_at or "") <= E.now_iso():
        raise HTTPException(status_code=404, detail="Odkaz neplatí — běžec ho zrušil, nebo vypršel.")
    return link


def _log_coach(db: DBSession, link: models.CoachLink, action: str) -> None:
    today, now = E.iso_date(E.today_date()), E.now_iso()
    L = models.CoachAccessLog
    row = db.query(L).filter(L.token == link.token, L.date == today, L.action == action).first()
    if row:
        row.access_count = (row.access_count or 0) + 1
        row.last_at = now
    else:
        db.add(L(runner_id=link.runner_id, token=link.token, coach_name=link.coach_name, action=action, date=today,
                 access_count=1, first_at=now, last_at=now))
    link.last_seen_at = now
    db.commit()


def _same_origin(request: Request) -> None:
    if not security.same_origin(request):
        raise HTTPException(status_code=403, detail="Neplatný požadavek (cross-origin)")


def _health(db: DBSession, rid: str, days: int = 42) -> list:
    """Day by day: readiness, sleep, HRV, resting HR, the diary's pain."""
    t = E.today_date()
    lo = (t - timedelta(days=days - 1)).isoformat()
    rd, pain = _body_days(db, rid, lo, t.isoformat())
    dm = {m.date[:10]: m for m in db.query(models.DailyMetric).filter(models.DailyMetric.runner_id == rid,
                                                                       models.DailyMetric.date >= lo).all()}
    out = []
    for k in range(days):
        d = (t - timedelta(days=days - 1 - k)).isoformat()
        m = dm.get(d)
        out.append({"date": d, "readiness": rd.get(d), "pain": pain.get(d),
                    "sleep": round(m.sleep_h, 1) if (m and m.sleep_h) else None,
                    "hrv": round(m.hrv_ms) if (m and m.hrv_ms) else None,
                    "rhr": round(m.resting_hr) if (m and m.resting_hr) else None})
    return out


def _activities(db: DBSession, rid: str, days: int = 14) -> list:
    t = E.today_date()
    lo = (t - timedelta(days=days - 1)).isoformat()
    A = models.Activity
    rows = (db.query(A).filter(A.runner_id == rid, A.started_at >= lo).order_by(A.started_at.desc(), A.id.desc()).all())
    return [{"id": a.id, "date": a.started_at[:10], "title": a.title, "sport": a.sport or "running",
             "km": round(a.distance_km, 1) if a.distance_km else None, "min": round(a.duration_min) if a.duration_min else None,
             "pace": round(a.pace_s_km) if a.pace_s_km else None, "hr": round(a.avg_hr) if a.avg_hr else None,
             "ascent": round(a.ascent_m) if a.ascent_m else None, "rpe": a.rpe}
            for a in rows if not a.excluded]


def _weeks_ahead(db: DBSession, rid: str, ctx: dict) -> list:
    """Planned km and hard minutes per week for 6 months — next to the current weekly ceiling."""
    ws = date.fromisoformat(ctx["weekStart"])
    rows = _rows(db, rid, lo=ws.isoformat(), hi=(ws + timedelta(days=7 * 27)).isoformat())
    out = []
    for w in range(27):
        a, b = ws + timedelta(days=7 * w), ws + timedelta(days=7 * w + 6)
        km = z4 = 0.0
        n = 0
        for x in rows:
            if a.isoformat() <= x["date"] <= b.isoformat() and x["kind"] != "rest":
                sn = CP.norm(x, ctx)
                if CP.KINDS[sn["kind"]]["sport"] == "run":
                    km += sn["km"] or 0.0
                z4 += sn["z4"] or 0.0
                n += 1
        out.append({"start": a.isoformat(), "km": round(km, 1), "z4": round(z4), "n": n})
    return out


@router.get("/api/trener/{token}")
def coach_view(token: str, db: DBSession = Depends(get_db)):
    link = _link(db, token)
    r = _runner(db, link.runner_id)
    _log_coach(db, link, "read")
    g, coach, ev = _evaluation(db, r) if r.coach_mode else ({}, None, None)
    if coach is None:
        # the runner switched the mode off: the overview still shows the body and the activities
        a = E.get_or_refresh_assessment(db, r.id)
        g = a.get("guidance") or {}
    ctx = (coach or {}).get("ctx") or {}
    t = E.today_date()
    wk = (g.get("week") or {}).get("channels") or {}
    first = (r.name or "").split()[0] if r.name else "Běžec"
    plan = _rows(db, r.id, lo=(t - timedelta(days=14)).isoformat(), hi=(t + timedelta(days=COACH_HORIZON)).isoformat())
    return {
        "runner": {"name": first, "coachMode": bool(r.coach_mode)}, "coachName": link.coach_name,
        "expiresAt": link.expires_at, "date": t.isoformat(),
        "today": {"readiness": g.get("readinessScore"), "pain": g.get("pain"), "type": g.get("typeLabel"),
                  "override": (g.get("override") or {}).get("title")},
        "health": _health(db, r.id), "activities": _activities(db, r.id),
        "eval": ev, "adherence": _adherence(db, r.id, g, coach, ev) if coach else [],
        "trend": (coach or {}).get("trend"), "plan": plan, "weeks": _weeks_ahead(db, r.id, ctx) if ctx else [],
        "limits": {c: {"ceiling": (wk.get(c) or {}).get("ceiling7"), "capacity": (wk.get(c) or {}).get("capacity"),
                       "safeToday": (wk.get(c) or {}).get("safeMax")} for c in CP.CHS},
        "kinds": {k: v["label"] for k, v in CP.KINDS.items()},
    }


@router.put("/api/trener/{token}/day/{day}")
def coach_set_day(token: str, day: str, body: DayIn, request: Request, background: BackgroundTasks,
                  db: DBSession = Depends(get_db)):
    """The coach sets one day (0–4 sessions; none = rest): it replaces whatever was planned
    there from other sources."""
    _same_origin(request)
    link = _link(db, token)
    d = _iso(day)
    t = E.today_date()
    if not -14 <= (date.fromisoformat(d) - t).days <= COACH_HORIZON:
        raise HTTPException(status_code=422, detail="Plánovat lze na 6 měsíců dopředu.")
    rows = [_check_session(s) for s in body.sessions]
    P = models.PlannedSession
    db.query(P).filter(P.runner_id == link.runner_id, P.date == d).delete(synchronize_session=False)
    now = E.now_iso()
    if not rows:
        rows = [{**{f: None for f in FIELDS}, "kind": "rest", "date": d}]
    for i, x in enumerate(rows):
        x["date"] = d
        db.add(P(runner_id=link.runner_id, seq=i, source="coach", created_at=now, updated_at=now, **x))
    db.commit()
    _log_coach(db, link, "write")
    background.add_task(_recompute_bg, link.runner_id)
    return {"ok": True, "plan": _rows(db, link.runner_id, lo=d, hi=d)}


@router.delete("/api/trener/{token}/day/{day}")
def coach_clear_day(token: str, day: str, request: Request, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    """The coach takes a day back out of the plan (nothing planned there any more)."""
    _same_origin(request)
    link = _link(db, token)
    d = _iso(day)
    P = models.PlannedSession
    db.query(P).filter(P.runner_id == link.runner_id, P.date == d).delete(synchronize_session=False)
    db.commit()
    _log_coach(db, link, "write")
    background.add_task(_recompute_bg, link.runner_id)
    return {"ok": True}


@router.post("/api/trener/{token}/copy-week")
def coach_copy_week(token: str, body: CopyIn, request: Request, background: BackgroundTasks,
                    db: DBSession = Depends(get_db)):
    """A week of the plan copied into the next N weeks (the coach's edits override)."""
    _same_origin(request)
    link = _link(db, token)
    n = _copy(db, link.runner_id, body, "coach", overwrite=True)
    db.commit()
    _log_coach(db, link, "write")
    background.add_task(_recompute_bg, link.runner_id)
    return {"ok": True, "copied": n}
