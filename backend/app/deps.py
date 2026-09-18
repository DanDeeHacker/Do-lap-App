"""Auth + scoping dependencies and helpers.

Scoping (who may touch which runner's data) is deliberately done as plain
functions called inside route bodies rather than parametrized FastAPI
Depends — path params name the resource differently per route (runner id,
program id, exercise id...), and an explicit `ensure_*` call at the top of
each handler is easier to audit than dependency-injection indirection.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from . import models, security
from .db import get_db


def get_current_user(
    request: Request, db: DBSession = Depends(get_db)
) -> models.User:
    token = request.cookies.get(security.SESSION_COOKIE)
    user = security.get_user_for_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Nepřihlášeno")
    return user


def get_current_user_optional(
    request: Request, db: DBSession = Depends(get_db)
):
    token = request.cookies.get(security.SESSION_COOKIE)
    return security.get_user_for_token(db, token)


def require_role(*roles: str):
    def _check(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Tento účet nemá k tomuto přístup")
        return user

    return _check


def verify_csrf(request: Request) -> None:
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and not security.same_origin(request):
        raise HTTPException(status_code=403, detail="Neplatný požadavek (cross-origin)")


# ------------------------------------------------------------ scoping
def has_care_assignment(db: DBSession, physio_id: str, runner_id: str) -> bool:
    return (
        db.query(models.CareAssignment)
        .filter(
            models.CareAssignment.physio_id == physio_id,
            models.CareAssignment.runner_id == runner_id,
            models.CareAssignment.status == "active",
        )
        .first()
        is not None
    )


def ensure_runner_read_access(db: DBSession, user: models.User, runner_id: str) -> None:
    """Runner reading their own data, or a physio who has claimed this patient."""
    if user.role == "runner" and user.runner_id == runner_id:
        return
    if user.role == "physio" and has_care_assignment(db, user.physio_id, runner_id):
        return
    raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto běžci")


def ensure_runner_self(user: models.User, runner_id: str) -> None:
    """Writes that only the runner themself may perform."""
    if user.role != "runner" or user.runner_id != runner_id:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto běžci")


def ensure_program_owner(user: models.User, program: models.Program) -> None:
    if user.role != "physio" or program.physio_id != user.physio_id:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto programu")


def or_404(obj, msg: str = "Nenalezeno"):
    if obj is None:
        raise HTTPException(status_code=404, detail=msg)
    return obj
