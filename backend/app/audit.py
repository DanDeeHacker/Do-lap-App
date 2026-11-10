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
    # ---- physio brief Phase 2 (W1–W16)
    "GET /api/physios/me/clinic": EXEMPT("members and subscription, no client data"),
    "POST /api/physios/me/clinic/members": SELF,
    "PATCH /api/clinic-members/{mid}": SELF,
    "POST /api/physios/me/clients/{rid}/transfer": SELF,
    "PATCH /api/bookings/{bid}/payer": SELF,
    "POST /api/physios/me/invites": SELF,
    "GET /api/physios/me/invites": EXEMPT("the physio's own invitations, no health data"),
    "DELETE /api/physios/me/invites/{iid}": EXEMPT("the physio's own invitation"),
    "GET /api/invites/{token}": EXEMPT("public: physio and clinic name only"),
    "POST /api/invites/{token}/accept": SELF,
    "POST /api/physios/me/clients/no-app": SELF,
    "GET /api/physios/me/today": SELF,
    "PATCH /api/alerts/{aid}": EXEMPT("workflow state of an alert, no health data changes"),
    "PATCH /api/physios/me/settings": EXEMPT("own settings"),
    "PUT /api/physios/me/availability": EXEMPT("own working hours"),
    "GET /api/physios/me/availability": EXEMPT("own working hours"),
    "POST /api/physios/me/time-off": EXEMPT("own time off"),
    "DELETE /api/physios/me/time-off/{tid}": EXEMPT("own time off"),
    "GET /api/physios/me/services": EXEMPT("own services"),
    "POST /api/physios/me/services": EXEMPT("own services"),
    "PATCH /api/services/{sid}": EXEMPT("own services"),
    "GET /api/physios/{pid}/calendar": ("read", "booking"),
    "POST /api/physios/me/visits": SELF,
    "POST /api/physios/me/ics": EXEMPT("a feed token, no client data"),
    "GET /api/physio-calendar/{token}.ics": EXEMPT("initials and service only (W5.8)"),
    "GET /api/physios/me/clients/{rid}/timeline": SELF,
    "GET /api/physios/me/clients/{rid}/previsit": SELF,
    "GET /api/physios/me/note-templates": EXEMPT("templates, no client data"),
    "POST /api/physios/me/note-templates": EXEMPT("templates, no client data"),
    "GET /api/physios/me/clients/{rid}/last-note": ("read", "clinical_record"),
    "GET /api/physios/me/clients/{rid}/limits": ("read", "limit"),
    "POST /api/physios/me/clients/{rid}/limits": SELF,
    "PATCH /api/limits/{lid}": SELF,
    "DELETE /api/limits/{lid}": SELF,
    "GET /api/physios/me/inbox": ("read", "messages"),
    "POST /api/physios/me/clients/{rid}/messages/handled": ("update", "messages"),
    "POST /api/runners/{rid}/messages/attachment": SELF,
    "GET /api/messages/{mid}/attachment": SELF,
    "GET /api/notifications": EXEMPT("notifications carry no health details (W15.5)"),
    "POST /api/notifications/read": EXEMPT("read markers"),
    "POST /api/runners/{rid}/intake": SELF,
    "POST /api/programs/{pid}/order": ("update", "program"),
    "POST /api/programs/{pid}/phases": ("update", "program"),
    "DELETE /api/programs/{pid}/phases/{phid}": ("update", "program"),
    "GET /api/programs/custom-exercises": EXEMPT("exercise library, no client data"),
    "POST /api/programs/custom-exercises": EXEMPT("exercise library, no client data"),
    "POST /api/programs/{pid}/save-template": ("read", "program"),
    "GET /api/programs/templates": EXEMPT("templates, no client data"),
    "POST /api/programs/from-template": SELF,
    "GET /api/rtr/templates": EXEMPT("templates, no client data"),
    "POST /api/rtr/{pid}/sessions/{sid}/morning": ("update", "rtr"),
    "POST /api/rtr/{pid}/control": SELF,
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
