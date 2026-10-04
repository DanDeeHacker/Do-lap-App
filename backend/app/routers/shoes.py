"""v0.12.0 — the runner's shoes (profile → Obuv): the list, a photo recognised by the AI
as a suggestion, the first use typed in or taken from a run, retiring a pair."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models
from .. import shoes as S
from ..db import get_db
from ..deps import ensure_runner_read_access, ensure_runner_self, get_current_user, or_404, verify_csrf
from ..metrics import engine as E
from ..metrics import runner_factors as RF
from ..serializers import to_dict

router = APIRouter(prefix="/api/runners", tags=["shoes"])


def _runner(db, rid):
    return or_404(db.query(models.Runner).filter(models.Runner.id == rid).first(), "Běžec nenalezen")


def _list(db, rid) -> dict:
    rows = db.query(models.Shoe).filter(models.Shoe.runner_id == rid).order_by(models.Shoe.id.asc()).all()
    r = _runner(db, rid)
    today = E.today_date()
    state = RF.shoe_state(rows, r, today)
    runs = (db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.excluded.isnot(True))
            .order_by(models.Activity.started_at.asc()).all())
    out = []
    for s in rows:
        d = to_dict(s)
        d["categoryLabel"] = S.CATEGORY_CS.get(s.category or "")
        if s.first_used:
            end = s.retired_at or "9999"
            mine = [a for a in runs if (a.sport or "running") == "running" and s.first_used <= a.started_at[:10] < end]
            # with several pairs in use the runs can't be told apart: an upper bound
            d["kmSince"] = round(sum(a.distance_km or 0 for a in mine), 1)
            d["runsSince"] = len(mine)
            d["weeks"] = max(0, (today - date.fromisoformat(s.first_used[:10])).days // 7)
        d["transition"] = state["transition"] if state["transition"] and state["transition"]["id"] == s.id else None
        out.append(d)
    return {"shoes": out, "rotation": state["rotation"], "transition": state["transition"],
            "kmShared": (state["active"] or 0) >= 2}


def _first_use(db, rid, body) -> tuple[str | None, int | None]:
    aid = body.get("first_activity_id")
    if aid:
        a = db.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.id == int(aid)).first()
        if a is None:
            raise HTTPException(status_code=422, detail="Běh nenalezen")
        return a.started_at[:10], a.id
    fu = body.get("first_used")
    if not fu:
        return None, None
    try:
        d = date.fromisoformat(str(fu)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Neplatné datum prvního použití") from None
    if d > E.today_date():
        raise HTTPException(status_code=422, detail="Datum prvního použití nesmí být v budoucnosti")
    return d.isoformat(), None


@router.get("/{rid}/shoes")
def list_shoes(rid: str, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_read_access(db, user, rid)
    return _list(db, rid)


@router.post("/{rid}/shoes/recognize", dependencies=[Depends(verify_csrf)])
def recognise_shoe(rid: str, body: dict, user: models.User = Depends(get_current_user)):
    """A photo (data URL) → a standardised suggestion; the photo is not stored."""
    ensure_runner_self(user, rid)
    img = S.check_image((body or {}).get("image"))
    if not img:
        raise HTTPException(status_code=422, detail="Fotku se nepodařilo načíst (JPEG, PNG nebo WebP do 4 MB)")
    if not S.throttle(rid):
        raise HTTPException(status_code=429, detail="Příliš mnoho fotek za hodinu, zkuste to později")
    return S.recognise(img)


@router.post("/{rid}/shoes", dependencies=[Depends(verify_csrf)])
def add_shoe(rid: str, body: dict, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    _runner(db, rid)
    f = S.clean_fields(body or {})
    if not f["brand"] or not f["model"]:
        raise HTTPException(status_code=422, detail="Vyplňte značku a model boty")
    first, aid = _first_use(db, rid, body or {})
    if not first:
        raise HTTPException(status_code=422, detail="Zadejte datum prvního použití, nebo vyberte běh")
    db.add(models.Shoe(runner_id=rid, **f, first_used=first, first_activity_id=aid,
                       source="photo" if (body or {}).get("source") == "photo" else "manual", created_at=E.now_iso()))
    db.commit()
    E.recompute_assessment(db, rid)
    return _list(db, rid)


@router.patch("/{rid}/shoes/{sid}", dependencies=[Depends(verify_csrf)])
def update_shoe(rid: str, sid: int, body: dict, user: models.User = Depends(get_current_user),
                db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    s = or_404(db.query(models.Shoe).filter(models.Shoe.runner_id == rid, models.Shoe.id == sid).first(), "Bota nenalezena")
    body = body or {}
    if any(k in body for k in ("brand", "model", "category", "drop_mm", "stack_mm", "carbon")):
        f = S.clean_fields({**to_dict(s), **body})
        if not f["brand"] or not f["model"]:
            raise HTTPException(status_code=422, detail="Vyplňte značku a model boty")
        for k, v in f.items():
            setattr(s, k, v)
    if "first_used" in body or "first_activity_id" in body:
        first, aid = _first_use(db, rid, body)
        if first:
            s.first_used, s.first_activity_id = first, aid
    if "retired" in body:
        s.retired_at = E.iso_date(E.today_date()) if body["retired"] else None
    db.commit()
    E.recompute_assessment(db, rid)
    return _list(db, rid)


@router.delete("/{rid}/shoes/{sid}", dependencies=[Depends(verify_csrf)])
def delete_shoe(rid: str, sid: int, user: models.User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    ensure_runner_self(user, rid)
    s = or_404(db.query(models.Shoe).filter(models.Shoe.runner_id == rid, models.Shoe.id == sid).first(), "Bota nenalezena")
    db.delete(s)
    db.commit()
    E.recompute_assessment(db, rid)
    return _list(db, rid)
