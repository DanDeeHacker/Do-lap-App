"""Program authoring — draft, edit, send, and the revision trail that keeps
every post-send change visible to the patient with its reason. Every write
verifies deps.ensure_program_owner (program.physio_id == session physio).
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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


def program_out(db: DBSession, p: models.Program, runner: bool = False) -> dict:
    """The physio sees the working copy; the runner sees the latest published version (W10.1) and only the
    published change entries."""
    from .. import work as W
    out = to_dict(p)
    ver = (db.query(models.ProgramVersion).filter_by(program_id=p.id, status="published")
           .order_by(models.ProgramVersion.version.desc()).first())
    live = {e.id: e for e in exercises_of(db, p.id)}
    if runner and ver is not None:
        snap = ver.snapshot or {}
        out["exercises"] = [{**x, "done_count": live[x["id"]].done_count if x.get("id") in live else x.get("done_count"),
                             "target_count": live[x["id"]].target_count if x.get("id") in live else x.get("target_count")}
                            for x in snap.get("exercises") or []]
        out["phases"] = snap.get("phases") or []
    else:
        out["exercises"] = to_dicts(list(live.values()))
        out["phases"] = to_dicts(db.query(models.ProgramPhase).filter_by(program_id=p.id).order_by(models.ProgramPhase.position).all())
    q = db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == p.id)
    if runner:
        q = q.filter(models.ProgramRevision.note.isnot(None))
    out["revisions"] = to_dicts(q.order_by(models.ProgramRevision.id.asc()).all())
    out["pending_changes"] = 0 if runner else db.query(models.ProgramRevision).filter(
        models.ProgramRevision.program_id == p.id, models.ProgramRevision.note.is_(None)).count()
    out["adherence"] = W.adherence(db, p)
    out["ends_on"] = ends_on(p)
    out["ended"] = bool(out["ends_on"] and out["ends_on"] < E.iso_date(E.today_date()))
    return out


def _check(dose: str | None, per_week) -> None:
    if dose is not None and not str(dose).strip():
        raise HTTPException(status_code=422, detail="Dávka nesmí být prázdná.")
    if per_week is not None and (not isinstance(per_week, int) or isinstance(per_week, bool) or not 1 <= per_week <= 7):
        raise HTTPException(status_code=422, detail="Počet za týden musí být 1 až 7.")


@router.get("/exercise-library")
def exercise_library(q: str = "", category: str = "", level: str = "", user: models.User = Depends(require_role("physio")),
                     db: DBSession = Depends(get_db)):
    """Browsable library — every exercise tagged with what it treats and what it targets (W10.7: filters by
    region and level, media fields ready; the library has no media yet, so the UI shows a placeholder).
    The physio's and clinic's own exercises come first."""
    items = content.by_category(category) if category else content.EXERCISE_LIBRARY
    if q:
        wanted = {e["id"] for e in content.search(q)}
        items = [e for e in items if e["id"] in wanted]
    if level:
        items = [e for e in items if e.get("level") == level]
    items = [{"media_url": None, "thumbnail_url": None, **e} for e in items]
    ph = db.get(models.Physio, user.physio_id)
    own = db.query(models.CustomExercise).filter((models.CustomExercise.physio_id == ph.id) |
                                                 (models.CustomExercise.clinic_id == ph.clinic_id)).all() if ph else []
    own_items = [{"id": f"custom-{c.id}", "name": c.name, "category": "custom", "dose": "", "per_week": 3, "cue": c.description,
                  "treats": [], "targets": [], "level": "custom", "media_url": c.media_url, "thumbnail_url": None}
                 for c in own if not q or q.lower() in c.name.lower()]
    return {"categories": content.CATEGORIES, "levels": sorted({e.get("level") for e in content.EXERCISE_LIBRARY if e.get("level")}),
            "exercises": own_items + items}


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


class ExerciseIn(BaseModel):
    """physio brief W10.3: the structured dose; `dose` is generated for display when it is not given."""
    model_config = {"extra": "ignore"}
    name: str
    dose: str | None = None
    per_week: int
    cue: str | None = None
    library_id: str | None = None
    phase_id: int | None = None
    sets: int | None = None
    reps: int | None = None
    duration_s: int | None = None
    load_text: str | None = None
    tempo: str | None = None
    side: str | None = None
    pain_limit: int | None = None
    media_url: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None


STRUCT = ("phase_id", "sets", "reps", "duration_s", "load_text", "tempo", "side", "pain_limit", "media_url",
          "thumbnail_url", "description")
SIDE_CS = {"L": "levá", "P": "pravá", "both": "obě strany", "each": "každá strana"}


def dose_text(sets, reps, duration_s, load_text=None, side=None) -> str | None:
    if not (sets or reps or duration_s):
        return None
    core = f"{sets} × " if sets else ""
    core += f"{reps}" if reps else (f"{duration_s} s" if duration_s else "")
    if reps and duration_s:
        core += f" ({duration_s} s)"
    parts = [core.strip(" ×")]
    if load_text:
        parts.append(load_text)
    if side and side in SIDE_CS:
        parts.append(SIDE_CS[side])
    return " · ".join(p for p in parts if p)


def _pending(db: DBSession, p: models.Program, physio_id: str, change: str) -> None:
    """W10: an edit to a sent programme is a draft — collected here and published as one entry (W10.10)."""
    if p.status == "sent":
        db.add(models.ProgramRevision(program_id=p.id, physio_id=physio_id, at=_utc(), note=None, changes=[change]))


@router.post("/{pid}/exercises", dependencies=[Depends(verify_csrf)])
def add_exercise(pid: int, body: ExerciseIn, user: models.User = Depends(require_role("physio")),
                  db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    dose = body.dose or dose_text(body.sets, body.reps, body.duration_s, body.load_text, body.side)
    _check(dose if dose is not None else "", body.per_week)
    if body.pain_limit is not None and not 0 <= body.pain_limit <= 10:
        raise HTTPException(status_code=422, detail="Hranice bolesti je 0 až 10.")
    if body.library_id and db.query(models.Exercise.id).filter(models.Exercise.program_id == pid,
                                                              models.Exercise.library_id == body.library_id).first():
        raise HTTPException(status_code=409, detail="Tento cvik už v programu je.")
    last = max([x.position or 0 for x in exercises_of(db, pid)] or [0])
    e = models.Exercise(program_id=pid, name=body.name, dose=dose, per_week=body.per_week, library_id=body.library_id,
                         cue=body.cue, done_count=0, position=last + 1, target_count=body.per_week * _weeks_left(p),
                         **{k: getattr(body, k) for k in STRUCT})
    db.add(e)
    _pending(db, p, user.physio_id, f"Přidáno: {body.name}")
    db.commit()
    db.refresh(e)
    return to_dict(e)


@router.patch("/exercises/{ex_id}", dependencies=[Depends(verify_csrf)])
def edit_exercise(ex_id: int, body: schemas.EditExerciseRequest, user: models.User = Depends(require_role("physio")),
                   db: DBSession = Depends(get_db)):
    e = or_404(db.query(models.Exercise).filter(models.Exercise.id == ex_id).first(), "Cvik nenalezen")
    p = or_404(db.query(models.Program).filter(models.Program.id == e.program_id).first())
    ensure_program_owner(user, p)
    patch = {k: v for k, v in body.patch.items() if k in {"dose", "per_week", "cue", *STRUCT}}
    _check(patch.get("dose", None) if "dose" in patch else None, patch.get("per_week"))
    before = {k: getattr(e, k) for k in ("dose", "per_week", "cue", *STRUCT)}
    changes = []
    for k, v in patch.items():
        if isinstance(v, str) and not v.strip():
            v = None
        if v == before[k]:
            continue
        setattr(e, k, v)
        if k == "per_week":
            changes.append(f"{e.name}: {before['per_week']}× → {v}× týdně")
            e.target_count = (e.done_count or 0) + v * _weeks_left(p)
        elif k == "dose":
            changes.append(f"{e.name}: dávka {before['dose']} → {v}")
        elif k == "cue":
            changes.append(f"{e.name}: pokyn odstraněn" if v is None else f"{e.name}: upraven pokyn")
        elif k in ("sets", "reps", "duration_s", "load_text", "side"):
            changes.append(f"{e.name}: upravena dávka")
        elif k == "pain_limit":
            changes.append(f"{e.name}: hranice bolesti {v}/10")
    if any(k in patch for k in ("sets", "reps", "duration_s", "load_text", "side")) and "dose" not in patch:
        e.dose = dose_text(e.sets, e.reps, e.duration_s, e.load_text, e.side) or e.dose
    for c in dict.fromkeys(changes):
        _pending(db, p, user.physio_id, c)
    # physio brief P0.8 → W10: the reason is asked once, when the change is published to the client
    if body.note and changes:
        p.draft_note = body.note.strip()
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
    _pending(db, p, user.physio_id, f"Odebráno: {name}")
    db.commit()
    return {"ok": True}


class OrderIn(BaseModel):
    ids: list[int]


@router.post("/{pid}/order", dependencies=[Depends(verify_csrf)])
def reorder(pid: int, body: OrderIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """W10.4: drag or up/down — the order is stored, never re-sorted."""
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    ex = {e.id: e for e in exercises_of(db, pid)}
    if set(body.ids) != set(ex):
        raise HTTPException(status_code=422, detail="Pořadí musí obsahovat všechny cviky programu.")
    for k, i in enumerate(body.ids):
        ex[i].position = k + 1
    _pending(db, p, user.physio_id, "Změněno pořadí cviků")
    db.commit()
    return {"ids": body.ids}


class PhaseIn(BaseModel):
    name: str
    weeks: int = 2


@router.post("/{pid}/phases", dependencies=[Depends(verify_csrf)])
def add_phase(pid: int, body: PhaseIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    """W10.2: programme → phases (name, weeks) → exercises."""
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    if not body.name.strip() or not 1 <= body.weeks <= 26:
        raise HTTPException(status_code=422, detail="Fáze potřebuje název a 1 až 26 týdnů.")
    n = db.query(models.ProgramPhase).filter_by(program_id=pid).count()
    ph = models.ProgramPhase(program_id=pid, name=body.name.strip(), weeks=body.weeks, position=n + 1)
    db.add(ph)
    p.weeks = sum(x.weeks or 0 for x in db.query(models.ProgramPhase).filter_by(program_id=pid).all()) + body.weeks
    _pending(db, p, user.physio_id, f"Přidána fáze: {ph.name}")
    db.commit()
    return to_dict(ph)


@router.delete("/{pid}/phases/{phid}", dependencies=[Depends(verify_csrf)])
def remove_phase(pid: int, phid: int, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    ph = db.get(models.ProgramPhase, phid)
    if ph is None or ph.program_id != pid:
        raise HTTPException(status_code=404, detail="Fáze nenalezena")
    for e in exercises_of(db, pid):
        if e.phase_id == phid:
            e.phase_id = None
    db.delete(ph)
    _pending(db, p, user.physio_id, f"Odebrána fáze: {ph.name}")
    db.commit()
    return {"ok": True}


def snapshot(db: DBSession, p: models.Program) -> dict:
    return {"name": p.name, "phase": p.phase, "weeks": p.weeks, "started_on": p.started_on,
            "phases": [to_dict(x) for x in db.query(models.ProgramPhase).filter_by(program_id=p.id)
                       .order_by(models.ProgramPhase.position).all()],
            "exercises": to_dicts(exercises_of(db, p.id))}


@router.post("/{pid}/send", dependencies=[Depends(verify_csrf)])
def send_program(pid: int, body: schemas.SendProgramRequest, user: models.User = Depends(require_role("physio")),
                  db: DBSession = Depends(get_db)):
    """`Odeslat klientovi` publishes a version (W10.1); the changes since the last one become one entry with the
    reason the client sees (P0.8 + W10.10)."""
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    pending = (db.query(models.ProgramRevision).filter(models.ProgramRevision.program_id == pid,
                                                       models.ProgramRevision.note.is_(None))
               .order_by(models.ProgramRevision.id).all())
    first = p.status != "sent"
    note = (body.note or p.draft_note or "").strip()
    if not first:
        if not pending:
            raise HTTPException(status_code=409, detail="Od posledního odeslání se nic nezměnilo.")
        if not note:
            raise HTTPException(status_code=422, detail="Uveďte důvod změny, klient ho uvidí.")
        changes = list(dict.fromkeys(c for r in pending for c in (r.changes or [])))
        for r in pending:
            db.delete(r)
        db.add(models.ProgramRevision(program_id=pid, physio_id=user.physio_id, at=_utc(), note=note, changes=changes))
    else:
        for r in pending:
            db.delete(r)
    p.status = "sent"
    p.sent_at = p.sent_at if not first else E.iso_date(E.today_date())
    p.version = (p.version or 0) + 1
    p.draft_note = None
    db.add(models.ProgramVersion(program_id=pid, version=p.version, status="published", published_at=_utc(),
                                 note=note or None, snapshot=snapshot(db, p)))
    db.add(models.Message(
        runner_id=p.runner_id, physio_id=user.physio_id, sender="physio",
        body=(body.note if first and body.note else
              f"Posílám vám program „{p.name}“. Projděte si pokyny u jednotlivých cviků." if first else
              f"Upravil(a) jsem váš program „{p.name}“: {note}"),
        created_at=E.now_iso(),
    ))
    from .. import work as W
    W.NOTIFY.send(db, "program_published", "Nová verze programu", runner_id=p.runner_id, ref=f"program:{p.id}")
    db.commit()
    db.refresh(p)
    return to_dict(p)


# ---- W10.5–7 custom exercises and templates -----------------------------------------------------------------
class CustomIn(BaseModel):
    name: str
    description: str | None = None
    media_url: str | None = None


@router.get("/custom-exercises")
def list_custom(user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    ph = db.get(models.Physio, user.physio_id)
    rows = db.query(models.CustomExercise).filter((models.CustomExercise.physio_id == ph.id) |
                                                  (models.CustomExercise.clinic_id == ph.clinic_id)).all()
    return {"items": to_dicts(rows)}


@router.post("/custom-exercises", dependencies=[Depends(verify_csrf)])
def add_custom(body: CustomIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Cvik potřebuje název.")
    ph = db.get(models.Physio, user.physio_id)
    if body.media_url and not body.media_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="Odkaz na video musí začínat https://")
    x = models.CustomExercise(physio_id=ph.id, clinic_id=ph.clinic_id, name=body.name.strip(), description=body.description,
                              media_url=body.media_url, created_at=E.now_iso())
    db.add(x)
    db.commit()
    return to_dict(x)


class TemplateIn(BaseModel):
    name: str


@router.post("/{pid}/save-template", dependencies=[Depends(verify_csrf)])
def save_template(pid: int, body: TemplateIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    p = or_404(db.query(models.Program).filter(models.Program.id == pid).first(), "Program nenalezen")
    ensure_program_owner(user, p)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Šablona potřebuje název.")
    snap = snapshot(db, p)
    for e in snap["exercises"]:          # a template carries no client progress
        for k in ("id", "program_id", "done_count", "target_count"):
            e.pop(k, None)
    t = models.ProgramTemplate(physio_id=user.physio_id, clinic_id=p and db.get(models.Physio, user.physio_id).clinic_id,
                               name=body.name.strip(), data=snap, created_at=E.now_iso())
    db.add(t)
    db.commit()
    return to_dict(t)


@router.get("/templates")
def list_templates(user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    ph = db.get(models.Physio, user.physio_id)
    rows = db.query(models.ProgramTemplate).filter((models.ProgramTemplate.physio_id == ph.id) |
                                                   (models.ProgramTemplate.clinic_id == ph.clinic_id)).all()
    return {"items": [{"id": t.id, "name": t.name, "phases": len((t.data or {}).get("phases") or []),
                       "exercises": len((t.data or {}).get("exercises") or [])} for t in rows]}


class FromTemplateIn(BaseModel):
    runner_id: str
    template_id: int


@router.post("/from-template", dependencies=[Depends(verify_csrf)])
def from_template(body: FromTemplateIn, user: models.User = Depends(require_role("physio")), db: DBSession = Depends(get_db)):
    if not has_care_assignment(db, user.physio_id, body.runner_id):
        raise HTTPException(status_code=403, detail="Nejprve musíte tento případ převzít z fronty.")
    t = db.get(models.ProgramTemplate, body.template_id)
    ph = db.get(models.Physio, user.physio_id)
    if t is None or (t.physio_id != ph.id and t.clinic_id != ph.clinic_id):
        raise HTTPException(status_code=404, detail="Šablona nenalezena")
    d = t.data or {}
    p = models.Program(runner_id=body.runner_id, physio_id=ph.id, name=d.get("name") or t.name, phase=d.get("phase") or "rebuild",
                       weeks=d.get("weeks") or 4, started_on=E.iso_date(E.today_date()), active=True, status="draft",
                       episode_id=R.episode_for(db, ph.id, body.runner_id).id)
    db.add(p)
    db.flush()
    phase_map = {}
    for k, x in enumerate(d.get("phases") or []):
        np_ = models.ProgramPhase(program_id=p.id, name=x.get("name"), weeks=x.get("weeks") or 2, position=k + 1)
        db.add(np_)
        db.flush()
        phase_map[x.get("id")] = np_.id
    for k, e in enumerate(d.get("exercises") or []):
        db.add(models.Exercise(program_id=p.id, name=e.get("name"), dose=e.get("dose"), per_week=e.get("per_week") or 3,
                               cue=e.get("cue"), library_id=e.get("library_id"), position=k + 1, done_count=0,
                               target_count=(e.get("per_week") or 3) * (p.weeks or 4),
                               **{f: (phase_map.get(e.get(f)) if f == "phase_id" else e.get(f)) for f in STRUCT}))
    R.physio_event(db, ph, "create", "program", p.id, runner_id=body.runner_id, detail={"template": t.id})
    db.commit()
    return to_dict(p)
