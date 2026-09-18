"""Program authoring — draft, edit, send, and the revision trail that keeps
every post-send change visible to the patient with its reason. Every write
verifies deps.ensure_program_owner (program.physio_id == session physio).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import content, models, schemas
from ..content import lib_for
from ..db import get_db
from ..deps import ensure_program_owner, has_care_assignment, or_404, require_role, verify_csrf
from ..metrics import engine as E
from ..serializers import to_dict

router = APIRouter(prefix="/api/programs", tags=["programs"])


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
    )
    db.add(p)
    db.flush()
    for name, dose, per_week, cue in lib_for(body.site):
        db.add(models.Exercise(program_id=p.id, name=name, dose=dose, per_week=per_week, cue=cue,
                                done_count=0, target_count=12))
    db.commit()
    db.refresh(p)
    return to_dict(p)


@router.post("/{pid}/exercises", dependencies=[Depends(verify_csrf)])
def add_exercise(pid: int, body: schemas.AddExerciseRequest, user: models.User = Depends(require_role("physio")),
                  db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    e = models.Exercise(program_id=pid, name=body.name, dose=body.dose, per_week=body.per_week,
                         cue=body.cue, done_count=0, target_count=12)
    db.add(e)
    if p.status == "sent":
        db.add(models.ProgramRevision(
            program_id=pid, physio_id=user.physio_id, at=E.iso_date(E.today_date()),
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
    before = {"dose": e.dose, "per_week": e.per_week, "cue": e.cue}
    allowed = {"dose", "per_week", "cue", "target_count"}
    for k, v in body.patch.items():
        if k in allowed:
            setattr(e, k, v)
    if p.status == "sent":
        changes = []
        if "per_week" in body.patch and body.patch["per_week"] != before["per_week"]:
            changes.append(f"{e.name}: {before['per_week']}× → {body.patch['per_week']}× týdně")
        if body.patch.get("dose") and body.patch["dose"] != before["dose"]:
            changes.append(f"{e.name}: dávka {before['dose']} → {body.patch['dose']}")
        if body.patch.get("cue") and body.patch["cue"] != before["cue"]:
            changes.append(f"{e.name}: upraven pokyn")
        if changes:
            db.add(models.ProgramRevision(
                program_id=p.id, physio_id=user.physio_id, at=E.iso_date(E.today_date()),
                note=body.note or "Úprava po zpětné vazbě pacienta.", changes=changes,
            ))
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
            program_id=p.id, physio_id=user.physio_id, at=E.iso_date(E.today_date()),
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
        body=body.note or f"Poslal jsem vám program „{p.name}“. Projděte si pokyny u jednotlivých cviků.",
        created_at=E.now_iso(),
    ))
    db.commit()
    db.refresh(p)
    return to_dict(p)
