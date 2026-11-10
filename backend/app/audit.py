"""Physio brief 2026-11-09 R7: every route that reads or changes clinical or runner health data declares
how it is audited. The audit middleware (main.audit_access) writes a record_events row after a successful
response for routes declared here as ("action", "resource"); routes that log inside the handler say
SELF; the rest give an EXEMPT reason. tests/test_audit_coverage.py walks app.routes and fails on any
route of the audited routers without a declaration."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from . import models

AUDITED_TAGS = {"physios", "programs", "return-to-run", "conclusions", "booking", "triage", "records", "physio-work"}
SELF = ("self", "the handler writes its own record_events row")


def EXEMPT(reason: str) -> tuple:
    return ("exempt", reason)


ROUTES: dict[str, tuple] = {
    # physios
    "GET /api/physios/{pid}/bootstrap": ("read", "runner"),
    "GET /api/physios/me": EXEMPT("own profile, no client data"),
    "PATCH /api/physios/me": EXEMPT("own profile, no client data"),
    "GET /api/physios/me/clients": ("read", "runner"),
    "GET /api/physios/me/clients/{rid}": ("read", "runner"),
    "POST /api/physios/me/clients/{rid}/injuries/{iid}/close": ("close", "injury"),
    # triage
    "GET /api/triage": EXEMPT("anonymised queue (P0.9), no identifiable client"),
    "PATCH /api/triage/{tid}/claim": ("create", "triage"),
    "POST /api/triage/{tid}/release": ("update", "triage"),
    "POST /api/triage/{tid}/pass": ("update", "triage"),
    # programmes
    "GET /api/programs/exercise-library": EXEMPT("exercise library, no personal data"),
    "POST /api/programs": SELF,
    "POST /api/programs/{pid}/exercises": ("update", "program"),
    "PATCH /api/programs/exercises/{ex_id}": ("update", "program"),
    "DELETE /api/programs/exercises/{ex_id}": ("update", "program"),
    "POST /api/programs/{pid}/send": ("update", "program"),
    # booking
    "POST /api/runners/{rid}/physio-interest": ("consent", "runner"),
    "GET /api/booking/options": EXEMPT("public free slots, no client data"),
    "POST /api/booking/request": SELF,
    "POST /api/runners/{rid}/bookings/{bid}/cancel": ("update", "booking"),
    "POST /api/runners/{rid}/physios/{pid}/decline": ("consent", "runner"),
    "GET /api/physios/{pid}/slots": EXEMPT("the physio's own free slots"),
    "POST /api/physios/{pid}/slots": EXEMPT("the physio's own free slots"),
    "DELETE /api/physios/slots/{sid}": EXEMPT("the physio's own free slots"),
    "POST /api/bookings/{bid}/confirm": ("update", "booking"),
    "POST /api/bookings/{bid}/decline": ("update", "booking"),
    "PATCH /api/bookings/{bid}/prep": ("update", "booking"),
    "POST /api/bookings/{bid}/cancel": SELF,
    "POST /api/bookings/{bid}/reschedule": SELF,
    "POST /api/bookings/{bid}/complete": SELF,
    "POST /api/bookings/{bid}/no-show": SELF,
    # return to run
    "POST /api/rtr": SELF,
    "GET /api/rtr/{pid}": ("read", "rtr"),
    "POST /api/rtr/{pid}/session": ("update", "rtr"),
    "PATCH /api/rtr/{pid}": ("update", "rtr"),
    # visit records
    "POST /api/bookings/{bid}/conclusion": ("read", "conclusion"),
    "POST /api/bookings/{bid}/conclusion/draft": ("update", "conclusion"),
    "GET /api/conclusions/{cid}": ("read", "conclusion"),
    "POST /api/conclusions/{cid}/audio": ("transcribe", "conclusion"),
    "PATCH /api/conclusions/{cid}": ("update", "conclusion"),
    "POST /api/conclusions/{cid}/approve": SELF,
    "POST /api/conclusions/{cid}/share": ("message", "conclusion"),
}


def declaration(method: str, path: str) -> tuple | None:
    return ROUTES.get(f"{method} {path}")


def runner_of(db: DBSession, path: str, params: dict) -> str | None:
    """The runner behind a request, from its path parameters."""
    if params.get("rid"):
        return params["rid"]
    if params.get("runner_id"):
        return params["runner_id"]
    if params.get("bid"):
        b = db.get(models.Booking, int(params["bid"]))
        return b.runner_id if b else None
    if params.get("cid"):
        c = db.get(models.Conclusion, int(params["cid"]))
        return c.runner_id if c else None
    if params.get("tid"):
        t = db.get(models.Triage, int(params["tid"]))
        return t.runner_id if t else None
    if params.get("ex_id"):
        e = db.get(models.Exercise, int(params["ex_id"]))
        p = db.get(models.Program, e.program_id) if e else None
        return p.runner_id if p else None
    if params.get("pid") and path.startswith("/api/programs/"):
        p = db.get(models.Program, int(params["pid"]))
        return p.runner_id if p else None
    if params.get("pid") and path.startswith("/api/rtr/"):
        p = db.get(models.ReturnToRun, int(params["pid"]))
        return p.runner_id if p else None
    if params.get("lid"):
        lim = db.get(models.ClinicalLimit, int(params["lid"])) if hasattr(models, "ClinicalLimit") else None
        return lim.runner_id if lim else None
    return None


def resource_id(params: dict) -> str | None:
    for k in ("cid", "bid", "pid", "ex_id", "tid", "iid", "lid", "rid"):
        if params.get(k):
            return str(params[k])
    return None
