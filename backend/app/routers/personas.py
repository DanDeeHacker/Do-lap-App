"""Simulated runners on staging (owner request 2026-10-27), the HTTP side of app/personas:
Team Console → Persony (signed-in owner or engineer) and the browser journeys and AI review
(scripts/personas, with the X-Persona-Token header = DOSSLAP_PERSONA_TOKEN). Everything here
answers 404 unless DOSSLAP_PERSONAS is on, and never in the production environment."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session as DBSession

from .. import models, security, team as T
from ..db import SessionLocal, get_db
from ..deps import get_current_user_optional
from ..metrics import engine as E
from ..personas import calibration as CAL, catalog as K, filing as F, sim as S
from ..schemas import Lenient

router = APIRouter(prefix="/api/personas", tags=["personas"])
MAX_DAYS = 120


class Actor:
    def __init__(self, user: models.User | None, by_token: bool):
        self.user, self.by_token = user, by_token


def actor(request: Request, db: DBSession = Depends(get_db),
          user: models.User | None = Depends(get_current_user_optional)) -> Actor:
    if not S.enabled():
        raise HTTPException(status_code=404, detail="Persony jsou vypnuté (DOSSLAP_PERSONAS)")
    if T.persona_token_ok(request.headers.get("X-Persona-Token")):
        return Actor(user, True)
    if user is not None and T.role_of(db, user) in ("owner", "engineer"):
        if request.method != "GET" and not security.same_origin(request):
            raise HTTPException(status_code=403, detail="Neplatný požadavek (cross-origin)")
        return Actor(user, False)
    raise HTTPException(status_code=403, detail="Jen pro vlastníky a inženýry, nebo s tokenem person")


def _run(db: DBSession, key: str) -> models.PersonaRun | None:
    if key not in K.PERSONAS:
        raise HTTPException(status_code=404, detail="Neznámá persona")
    return db.query(models.PersonaRun).filter(models.PersonaRun.key == key).first()


@router.get("")
def overview(a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    cal = CAL.current(db)
    out = []
    for key, p in K.PERSONAS.items():
        run = _run(db, key)
        out.append({"key": key, "name": p["name"], "label": p["label"], "events": p.get("events", []),
                    "goal": p.get("goal"), "run": S.run_out(run)})
    return {"personas": out, "simDays": S.SIM_DAYS, "reportsTo": T.os.environ.get("DOSSLAP_PERSONA_REPORT_URL") or None,
            "calibration": {"generatedAt": cal.get("generatedAt"), "consenting": cal.get("consenting"),
                            "groups": {k: v.get("n") for k, v in (cal.get("groups") or {}).items()}} if cal else None}


class ResetIn(Lenient):
    seed: int = Field(default=1, ge=1, le=10_000)


@router.post("/{key}/reset")
def reset(key: str, body: ResetIn, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    run = _run(db, key)
    if run is not None and run.status == "running":
        raise HTTPException(status_code=409, detail="Simulace právě běží")
    run = S.reset(db, key, seed=body.seed)
    return S.run_out(run)


class AdvanceIn(Lenient):
    days: int = Field(default=1, ge=1, le=MAX_DAYS)
    to: str = "evening"          # evening = the day is over; morning = stop before the next run


@router.post("/{key}/advance")
def advance(key: str, body: AdvanceIn, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    """Up to 3 days in the request (the browser journeys step half a day at a time); longer
    stretches run beside the server and show their progress in the overview."""
    run = _run(db, key)
    if run is not None and run.status == "running":
        raise HTTPException(status_code=409, detail="Simulace právě běží")
    if body.to not in ("evening", "morning"):
        raise HTTPException(status_code=422, detail="to je evening nebo morning")
    if body.days <= 3:
        return S.advance(db, key, body.days, body.to)
    if run is None:
        run = S.reset(db, key)
    run.status = "running"
    db.commit()
    S.advance_in_background([key], body.days, SessionLocal)
    return S.run_out(run)


class AllIn(Lenient):
    days: int = Field(default=7, ge=1, le=MAX_DAYS)


@router.post("/advance-all")
def advance_all(body: AllIn, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    keys = list(K.PERSONAS)
    for key in keys:
        run = _run(db, key)
        if run is not None and run.status == "running":
            raise HTTPException(status_code=409, detail="Simulace právě běží")
    for key in keys:
        run = _run(db, key) or S.reset(db, key)
        run.status = "running"
    db.commit()
    S.advance_in_background(keys, body.days, SessionLocal)
    return {"started": keys, "days": body.days}


@router.get("/{key}/days")
def days(key: str, limit: int = 14, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    """The journal: what the persona's app said, what it did and what the checks found."""
    run = _run(db, key)
    if run is None:
        return {"run": None, "days": []}
    rows = (db.query(models.PersonaDay).filter(models.PersonaDay.run_id == run.id)
            .order_by(models.PersonaDay.date.desc()).limit(max(1, min(limit, 120))).all())
    p = K.PERSONAS[key]
    return {"run": S.run_out(run), "persona": {"name": p["name"], "label": p["label"], "events": p.get("events", [])},
            "days": [{"date": r.date, **(r.data_json or {})} for r in rows]}


@router.post("/{key}/session")
def session(key: str, response: Response, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    """Signs the browser in as the persona (journeys only, with the token): the app then runs on
    the persona's clock (main.persona_clock)."""
    if not a.by_token:
        raise HTTPException(status_code=403, detail="Přihlášení za personu jen s tokenem person")
    from .auth import _set_cookie
    run = _run(db, key) or S.reset(db, key)
    token, _ = security.create_session(db, run.user_id)
    _set_cookie(response, token, persistent=False)
    return {"ok": True, **S.run_out(run), "clock": S.clock_of(run).isoformat()}


class FindingIn(Lenient):
    check: str = Field(min_length=1, max_length=60)
    route: str = Field(min_length=1, max_length=200)
    key: str = Field(default="", max_length=200)
    title: str = Field(min_length=3, max_length=200)
    detail: str = Field(default="", max_length=1500)
    type: str = "bug"


class FindingsIn(Lenient):
    persona: str
    simDate: str | None = None
    source: str = "synthetic"
    items: list[FindingIn] = Field(default_factory=list, max_length=10)
    passed: list[str] = Field(default_factory=list, max_length=40)


@router.post("/findings")
def findings(body: FindingsIn, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    """Findings of the browser journeys (UI checks) and of the AI review — filed like the
    simulation's own (dedupe, the daily cap, an owner's approval before anyone builds them)."""
    if body.persona not in K.PERSONAS:
        raise HTTPException(status_code=404, detail="Neznámá persona")
    if body.source not in ("synthetic", "synthetic-ai"):
        raise HTTPException(status_code=422, detail="Zdroj je synthetic nebo synthetic-ai")
    run = _run(db, body.persona)
    sim_date = body.simDate or (run.sim_date if run else E.iso_date(E.today_date()))
    res = F.file(db, body.persona, [i.model_dump() for i in body.items], sim_date, passed=body.passed, source=body.source)
    db.commit()
    return res


@router.get("/calibration")
def get_calibration(a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    return {"profile": CAL.current(db), "behaviour": {k: S.behaviour(k, db) for k in K.PERSONAS}}


@router.post("/calibration")
async def put_calibration(request: Request, a: Actor = Depends(actor), db: DBSession = Depends(get_db)):
    """Personas stage 3: import the pilot's behaviour profile (Team Console → Pilot on production
    → "Stáhnout profil chování"). Each persona's habits are recomputed; the bodies don't change."""
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Neplatné JSON") from None
    if not CAL.valid(data):
        raise HTTPException(status_code=422, detail="Tohle není profil chování z Došlapu (nebo má skupinu pod 5 lidí)")
    db.add(models.PersonaCalibration(data_json=data, imported_by=(a.user.email if a.user else "token"), created_at=S._now_real()))
    db.flush()
    for run in db.query(models.PersonaRun).all():
        run.behaviour_json = S.behaviour(run.key, db)
    db.commit()
    return {"ok": True, "groups": {k: v.get("n") for k, v in (data.get("groups") or {}).items()}}
