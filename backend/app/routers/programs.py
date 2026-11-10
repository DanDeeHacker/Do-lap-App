"""Program authoring — draft, edit, send, and the revision trail that keeps
every post-send change visible to the patient with its reason. Every write
verifies deps.ensure_program_owner (program.physio_id == session physio).
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import content, models, records as R, schemas
from ..content import lib_for
from ..db import get_db
from ..deps import ensure_program_owner, has_care_assignment, or_404, require_role, verify_csrf
from ..metrics import engine as E
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/programs", tags=["programs"])


# ---- physio brief 2026-11-09 P0.8 -------------------------------------------------------------------
def _utc() -> str:
    """A revision's time as a full UTC timestamp (it used to be a date shown as 01:00 or 02:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def exercises_of(db: DBSession, pid: int) -> list:
    return (db.query(models.Exercise).filter(models.Exercise.program_id == pid)
            .order_by(models.Exercise.position.asc(), models.Exercise.id.asc()).all())


def ends_on(p: models.Program) -> str | None:
    try:
        return (date.fromisoformat((p.started_on or "")[:10]) + timedelta(weeks=p.weeks or 0)).isoformat() if p.weeks else None
    except ValueError:
        return None


def _weeks_left(p: models.Program) -> int:
    end = ends_on(p)
    if not end:
        return p.weeks or 0
    return max(0, -(-(date.fromisoformat(end) - E.today_date()).days // 7))


def program_out(db: DBSession, p: models.Program) -> dict:
    out = to_dict(p)
    out["exercises"] = to_dicts(exercises_of(db, p.id))
    out["revisions"] = to_dicts(db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == p.id)
                                .order_by(models.ProgramRevision.id.asc()).all())
    out["ends_on"] = ends_on(p)
    out["ended"] = bool(out["ends_on"] and out["ends_on"] < E.iso_date(E.today_date()))
    return out


def _check(dose: str | None, per_week) -> None:
    if dose is not None and not str(dose).strip():
        raise HTTPException(status_code=422, detail="Dávka nesmí být prázdná.")
    if per_week is not None and (not isinstance(per_week, int) or isinstance(per_week, bool) or not 1 <= per_week <= 7):
        raise HTTPException(status_code=422, detail="Počet za týden musí být 1 až 7.")


@router.get("/exercise-library")
def exercise_library(q: str = "", category: str = "", user: models.User = Depends(require_role("physio"))):
    """Browsable library — every exercise tagged with what it treats and
    what it targets, not just the 3-per-site auto-pick draftProgram() uses."""
    items = content.by_category(category) if category else content.EXERCISE_LIBRARY
    if q:
        wanted = {e["id"] for e in content.search(q)}
        items = [e for e in items if e["id"] in wanted]
    return {"categories": content.CATEGORIES, "exercises": items}


@router.post("", dependencies=[Depends(verify_csrf)])
def draft_program(body: schemas.DraftProgramRequest, user: models.User = Depends(require_role("physio")),
                   db: DBSession = Depends(get_db)):
    if not has_care_assignment(db, user.physio_id, body.runner_id):
        raise HTTPException(status_code=403, detail="Nejprve musíte tento případ převzít z fronty.")
    p = models.Program(
        runner_id=body.runner_id, physio_id=user.physio_id,
        name=f"{body.site or 'Preventivní'} — fáze 1", phase="offload" if body.site else "prevent",
        weeks=4, started_on=E.iso_date(E.today_date()), active=True, status="draft", sent_at=None,
        episode_id=R.episode_for(db, user.physio_id, body.runner_id).id,     # physio brief R3
    )
    db.add(p)
    db.flush()
    ph = db.get(models.Physio, user.physio_id)
    R.physio_event(db, ph, "create", "program", p.id, runner_id=body.runner_id)       # physio brief R7
    for k, (name, dose, per_week, cue) in enumerate(lib_for(body.site)):
        db.add(models.Exercise(program_id=p.id, name=name, dose=dose, per_week=per_week, cue=cue, position=k + 1,
                                done_count=0, target_count=(per_week or 1) * (p.weeks or 4)))
    db.commit()
    db.refresh(p)
    return to_dict(p)


@router.post("/{pid}/exercises", dependencies=[Depends(verify_csrf)])
def add_exercise(pid: int, body: schemas.AddExerciseRequest, user: models.User = Depends(require_role("physio")),
                  db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    _check(body.dose, body.per_week)
    if body.library_id and db.query(models.Exercise.id).filter(models.Exercise.program_id == pid,
                                                              models.Exercise.library_id == body.library_id).first():
        raise HTTPException(status_code=409, detail="Tento cvik už v programu je.")
    last = max([x.position or 0 for x in exercises_of(db, pid)] or [0])
    e = models.Exercise(program_id=pid, name=body.name, dose=body.dose, per_week=body.per_week, library_id=body.library_id,
                         cue=body.cue, done_count=0, position=last + 1, target_count=body.per_week * _weeks_left(p))
    db.add(e)
    if p.status == "sent":
        db.add(models.ProgramRevision(
            program_id=pid, physio_id=user.physio_id, at=_utc(),
            note="Přidán cvik.", changes=[f"Přidáno: {body.name}"],
        ))
    db.commit()
    db.refresh(e)
    return to_dict(e)


@router.patch("/exercises/{ex_id}", dependencies=[Depends(verify_csrf)])
def edit_exercise(ex_id: int, body: schemas.EditExerciseRequest, user: models.User = Depends(require_role("physio")),
                   db: DBSession = Depends(get_db)):
    e = or_404(db.query(models.Exercise).filter(models.Exercise.id == ex_id).first(), "Cvik nenalezen")
    p = or_404(db.query(models.Program).filter(models.Program.id == e.program_id).first())
    ensure_program_owner(user, p)
    patch = {k: v for k, v in body.patch.items() if k in {"dose", "per_week", "cue"}}
    _check(patch.get("dose", None) if "dose" in patch else None, patch.get("per_week"))
    note = (body.note or "").strip()
    if p.status == "sent" and not note:
        # physio brief 2026-11-09 P0.8: no invented "Úprava po zpětné vazbě pacienta."
        raise HTTPException(status_code=422, detail="Uveďte důvod změny, klient ho uvidí.")
    before = {"dose": e.dose, "per_week": e.per_week, "cue": e.cue}
    changes = []
    for k, v in patch.items():
        if k == "cue" and isinstance(v, str) and not v.strip():
            v = None
        if v == before[k]:
            continue
        setattr(e, k, v)
        if k == "per_week":
            changes.append(f"{e.name}: {before['per_week']}× → {v}× týdně")
            e.target_count = (e.done_count or 0) + v * _weeks_left(p)
        elif k == "dose":
            changes.append(f"{e.name}: dávka {before['dose']} → {v}")
        else:
            changes.append(f"{e.name}: pokyn odstraněn" if v is None else f"{e.name}: upraven pokyn")
    if p.status == "sent" and changes:
        db.add(models.ProgramRevision(program_id=p.id, physio_id=user.physio_id, at=_utc(), note=note, changes=changes))
    db.commit()
    db.refresh(e)
    return to_dict(e)


@router.delete("/exercises/{ex_id}", dependencies=[Depends(verify_csrf)])
def remove_exercise(ex_id: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    e = or_404(db.query(models.Exercise).filter(models.Exercise.id == ex_id).first(), "Cvik nenalezen")
    p = or_404(db.query(models.Program).filter(models.Program.id == e.program_id).first())
    ensure_program_owner(user, p)
    name = e.name
    db.delete(e)
    if p.status == "sent":
        db.add(models.ProgramRevision(
            program_id=p.id, physio_id=user.physio_id, at=_utc(),
            note="Odebrán cvik.", changes=[f"Odebráno: {name}"],
        ))
    db.commit()
    return {"ok": True}


@router.post("/{pid}/send", dependencies=[Depends(verify_csrf)])
def send_program(pid: int, body: schemas.SendProgramRequest, user: models.User = Depends(require_role("physio")),
                  db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    p.status = "sent"
    p.sent_at = E.iso_date(E.today_date())
    db.add(models.Message(
        runner_id=p.runner_id, physio_id=user.physio_id, sender="physio",
        body=body.note or f"Posílám vám program „{p.name}“. Projděte si pokyny u jednotlivých cviků.",
        created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(p)
    return to_dict(p)
