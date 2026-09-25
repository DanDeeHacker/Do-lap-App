"""AI texts for the runner (metrics/coach_texts.py): consent, the current texts
and an on-demand refresh. Generation always runs in the background — a hosted
70B model takes tens of seconds — so these endpoints answer immediately."""
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from .. import llm, models
from ..db import get_db
from ..deps import ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf
from ..metrics import coach_texts as CT
from ..metrics import engine as E

router = APIRouter(prefix="/api/runners", tags=["coach"])


def _status(db: DBSession, runner: models.Runner, with_texts: bool = True) -> dict:
    out = {"consent": bool(runner.coach_consent), "consentAt": runner.coach_consent_at,
           "llm": llm.available(), "model": llm.NVIDIA_MODEL if llm.available() else None}
    if runner.coach_consent and with_texts:
        out["texts"] = CT.texts_for(db, runner.id)
    return out


@router.get("/{rid}/coach")
def coach_status(rid: str, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                 db: DBSession = Depends(get_db)):
    """Consent state and, with consent, the current texts. Stale or missing texts
    are regenerated in the background (`pending` tells the client to look again)."""
    ensure_runner_read_access(db, user, rid)
    runner = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    out = _status(db, runner)
    if runner.coach_consent:
        a = E.get_or_refresh_assessment(db, rid)
        stale = [k for k, period, facts in CT.plan(db, rid, a) if CT.is_stale(CT.latest(db, rid, k, period), facts, k)]
        out["pending"] = stale
        if stale:
            background.add_task(CT.refresh_bg, rid)
    return out


class ConsentIn(BaseModel):
    consent: bool


@router.put("/{rid}/coach/consent", dependencies=[Depends(verify_csrf)])
def coach_consent(rid: str, body: ConsentIn, background: BackgroundTasks,
                  user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Opt in → texts are generated right away. Opt out → the stored texts are deleted."""
    ensure_runner_self(user, rid)
    runner = or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")
    if body.consent and not runner.coach_consent:
        runner.coach_consent, runner.coach_consent_at = True, E.now_iso()
        db.commit()
        background.add_task(CT.refresh_bg, rid)
    elif not body.consent and runner.coach_consent:
        runner.coach_consent, runner.coach_consent_at = False, None
        db.commit()
        CT.forget(db, rid)
    return _status(db, runner, with_texts=False)


@router.post("/{rid}/coach/refresh", dependencies=[Depends(verify_csrf)], status_code=202)
def coach_refresh(rid: str, background: BackgroundTasks, user: models.User = Depends(get_current_user),
                  db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    background.add_task(CT.refresh_bg, rid)
    return {"queued": True}
