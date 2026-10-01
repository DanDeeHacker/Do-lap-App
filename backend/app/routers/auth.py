"""Registration/login/session — the real security boundary. Google/Garmin
OAuth stay UI-accurate simulations elsewhere (see auth.html); this is the
only auth path that's actually real.
"""
import secrets
import threading
import time
from collections import deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DBSession

from .. import models, schemas
from ..db import get_db
from ..deps import GUEST_PROVIDER, get_current_user, is_owner, verify_csrf
from ..metrics import engine as E
from ..security import (
    COOKIE_SECURE, SESSION_COOKIE, SESSION_TTL_DAYS, client_ip, create_session, hash_password,
    login_throttle, revoke_session, verify_password,
)
from ..security import now_iso as security_now
from ..serializers import to_dict

# New accounts start on the newest engine, v3 "Kapacitní" (decision 27. 9. 2026).
NEW_RUNNER_ENGINE = "v3"

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLES = ("runner", "physio", "employer", "partner")
ROLE_LABEL = {"runner": "běžec / pacient", "physio": "fyzioterapeut", "employer": "zaměstnavatel", "partner": "partner"}
COOKIE_MAX_AGE = 60 * 60 * 24 * SESSION_TTL_DAYS

_PROFILE_MODEL = {
    "runner": (models.Runner, "runner_id"), "physio": (models.Physio, "physio_id"),
    "employer": (models.Employer, "employer_id"), "partner": (models.Partner, "partner_id"),
}


def _user_dict(db: DBSession, u: models.User) -> dict:
    profile = None
    spec = _PROFILE_MODEL.get(u.role)
    if spec:
        model, fk_attr = spec
        fk_val = getattr(u, fk_attr)
        if fk_val:
            profile = to_dict(db.query(model).filter(model.id == fk_val).first())
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "runner_id": u.runner_id, "physio_id": u.physio_id,
        "employer_id": u.employer_id, "partner_id": u.partner_id,
        "provider": u.provider, "profile": profile, "owner": is_owner(u),
        **({"guest": True, "demo_rid": _demo_rid()} if u.provider == GUEST_PROVIDER else {}),
    }


def _demo_rid() -> str:
    from ..tutorial_demo import TUTORIAL_RID
    return TUTORIAL_RID


def _next_id(db: DBSession, model, prefix: str) -> str:
    n = db.query(model).count()
    return f"{prefix}-{n + 1:04d}"


def _set_cookie(response: Response, token: str) -> None:
    # No max_age/expires → a *session* cookie: the browser keeps it while it's
    # open (sign-in is remembered across tabs/navigations) and drops it when the
    # browser is fully closed, returning the user to the sign-up screen. The
    # server-side UserSession still has SESSION_TTL_DAYS as a hard safety cap.
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", secure=COOKIE_SECURE,
        path="/",
    )


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(body: schemas.RegisterRequest, response: Response, db: DBSession = Depends(get_db)):
    email = body.email.lower().strip()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(status_code=400, detail="Tento e-mail už je zaregistrovaný.")
    role = body.role if body.role in ROLES else "runner"
    fk: dict = {}

    if role == "runner":
        rid = _next_id(db, models.Runner, "run")
        db.add(models.Runner(id=rid, bib=None, name=body.name, prior_injury=None, prior_injury_months_ago=None,
                              engine_mode=NEW_RUNNER_ENGINE,
                              onboarding_json={"active": True, "dismissed": False, "tutorialDone": False}))
        db.flush()
        db.add(models.Integration(id=f"int-{rid}", runner_id=rid, provider=None, status="disconnected", fields=[]))
        fk["runner_id"] = rid
    elif role == "physio":
        pid = _next_id(db, models.Physio, "phy")
        db.add(models.Physio(id=pid, clinic_id=None, name=body.name, credential=None, rating=None))
        fk["physio_id"] = pid
    elif role == "employer":
        eid = _next_id(db, models.Employer, "emp")
        db.add(models.Employer(id=eid, name=body.name, city=None, seats=0, plan="trial", contract_value_czk=0))
        fk["employer_id"] = eid
    elif role == "partner":
        parid = _next_id(db, models.Partner, "par")
        db.add(models.Partner(id=parid, name=body.name, kind="other", city=None, referral_code=None, commission_pct=0))
        fk["partner_id"] = parid
    db.flush()

    user = models.User(
        email=email, password_hash=hash_password(body.password), name=body.name, role=role,
        provider=body.provider or "password", created_at=E.now_iso(), **fk,
    )
    db.add(user)
    db.flush()
    db.add(models.Settings(user_id=user.id))
    if role == "runner":
        E.recompute_assessment(db, fk["runner_id"])
    db.commit()
    db.refresh(user)

    token, _ = create_session(db, user.id)
    _set_cookie(response, token)
    return _user_dict(db, user)


@router.post("/session", dependencies=[Depends(verify_csrf)])
def sign_in(body: schemas.LoginRequest, request: Request, response: Response, db: DBSession = Depends(get_db)):
    email = body.email.lower().strip()
    ip = client_ip(request)
    if not login_throttle.check(email, ip):
        raise HTTPException(status_code=429, detail="Příliš mnoho pokusů o přihlášení. Zkuste to za chvíli.")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(body.password, user.password_hash):
        login_throttle.record_failure(email, ip)
        raise HTTPException(status_code=401, detail="Nesprávný e-mail nebo heslo.")
    if body.expected_role and body.expected_role in ROLES and user.role != body.expected_role:
        login_throttle.record_failure(email, ip)
        raise HTTPException(
            status_code=403,
            detail=f"Tento účet je typu „{ROLE_LABEL.get(user.role, user.role)}“, ne "
                   f"„{ROLE_LABEL.get(body.expected_role, body.expected_role)}“.",
        )
    login_throttle.reset(email, ip)
    token, _ = create_session(db, user.id)
    _set_cookie(response, token)
    return _user_dict(db, user)


# ---------------------------------------------------------------- public demo
# "Vyzkoušej hned!" on the sign-up page: a short guest session on one shared,
# password-less account. The guest sees the tutorial runner (read-only for
# everyone, deps.ensure_runner_read_access) and cannot write anything
# (deps.verify_csrf). No personal data is involved.
GUEST_EMAIL = "ukazka@guest.doslap.invalid"
GUEST_TTL = timedelta(hours=12)
_guest_hits: dict[str, deque] = {}
_guest_lock = threading.Lock()
GUEST_MAX_PER_IP, GUEST_WINDOW_S = 30, 600


def _guest_allowed(ip: str) -> bool:
    now = time.monotonic()
    with _guest_lock:
        q = _guest_hits.setdefault(ip, deque())
        while q and now - q[0] > GUEST_WINDOW_S:
            q.popleft()
        if len(q) >= GUEST_MAX_PER_IP:
            return False
        q.append(now)
        return True


@router.post("/guest", dependencies=[Depends(verify_csrf)])
def guest_session(request: Request, response: Response, db: DBSession = Depends(get_db)):
    if not _guest_allowed(client_ip(request)):
        raise HTTPException(status_code=429, detail="Příliš mnoho pokusů. Zkuste to za chvíli.")
    from .. import tutorial_demo
    tutorial_demo.ensure(db)                     # the demo data are rebuilt for today when stale
    user = db.query(models.User).filter(models.User.email == GUEST_EMAIL).first()
    if user is None:
        user = models.User(email=GUEST_EMAIL, password_hash=hash_password(secrets.token_urlsafe(32)),
                           name="Host", role="runner", provider=GUEST_PROVIDER, created_at=E.now_iso())
        db.add(user)
        db.commit()
        db.refresh(user)
    # expired guest sessions are never presented again, so tidy them up here
    db.query(models.UserSession).filter(models.UserSession.user_id == user.id,
                                        models.UserSession.expires_at < security_now()).delete()
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        revoke_session(db, old)
    token, _ = create_session(db, user.id, ttl=GUEST_TTL)
    _set_cookie(response, token)
    return _user_dict(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    return _user_dict(db, user)


# Card ids the desktop stat rail understands (frontend Layout → StatRail).
RAIL_CARD_IDS = {"recovery", "week", "load", "mech", "hrv", "rhr", "sleep", "readiness", "race"}


@router.get("/settings")
def get_settings(user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    s = db.query(models.Settings).filter(models.Settings.user_id == user.id).first()
    if not s:
        s = models.Settings(user_id=user.id)
        db.add(s)
        db.commit()
        db.refresh(s)
    return {
        "share_with_physio": s.share_with_physio, "share_bodymap": s.share_bodymap,
        "employer_aggregate": s.employer_aggregate, "notify_drift": s.notify_drift,
        "notify_checkin": s.notify_checkin, "rail_cards": s.rail_cards,
    }


@router.patch("/settings", dependencies=[Depends(verify_csrf)])
def patch_settings(body: schemas.SettingsPatch, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    s = db.query(models.Settings).filter(models.Settings.user_id == user.id).first()
    if not s:
        s = models.Settings(user_id=user.id)
        db.add(s)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "rail_cards" and v is not None:
            v = [c for c in dict.fromkeys(v) if c in RAIL_CARD_IDS][:8]
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return {
        "share_with_physio": s.share_with_physio, "share_bodymap": s.share_bodymap,
        "employer_aggregate": s.employer_aggregate, "notify_drift": s.notify_drift,
        "notify_checkin": s.notify_checkin, "rail_cards": s.rail_cards,
    }
