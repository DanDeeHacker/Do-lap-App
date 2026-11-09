"""Clean test leftovers out of the demo accounts (physio brief 2026-11-09 P0.12).

    ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo            # dry run: lists what it would do
    ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo --apply    # does it
    … --extra conclusions=47,48 --extra injury_reports=189 --extra bookings=95 --extra rtr=1 --extra slots=93
      --extra messages_from=240 --extra revisions_from=48 --extra release=<triage id>

It touches only demo runners (an @demo.cz login or the tour runner) and the demo physio's slots; one
target that belongs to anyone else aborts the whole run before anything changes. Running it twice gives
the same state. It restores what the seed defines (prior injury, programme order) and removes:
anything containing "TEST (Claude)", the rows named with --extra, and the demo physio's past open slots.
Never point it at production health data of real users — the guard refuses non-demo rows, but the
decision to run it on an environment is the owner's.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from .. import models
from ..assistant.service import is_demo
from ..db import SessionLocal
from ..metrics import engine as E

MARK = "TEST (Claude)"
DEMO_PHYSIO = "phy-0001"


class Refused(Exception):
    pass


def _ids(v: str) -> list[int]:
    return [int(x) for x in v.split(",") if x.strip()]


def plan(db, extra: dict[str, str]) -> list[tuple[str, object]]:
    """Every change as (description, action). Raises Refused when a target is not demo data."""
    demo = {r.id for r in db.query(models.Runner).all() if is_demo(db, r.id)}
    out: list[tuple[str, object]] = []

    def own(rid: str, what: str):
        if rid not in demo:
            raise Refused(f"{what} patří běžci {rid}, který není demo účet — nic se nezměnilo.")

    def drop(row, what):
        own(row.runner_id, what)
        out.append((f"smazat {what}", lambda r=row: db.delete(r)))

    for m in db.query(models.Message).filter(models.Message.body.contains(MARK)).all():
        drop(m, f"zprávu {m.id}")
    for c in db.query(models.Conclusion).all():
        if MARK in " ".join(filter(None, (c.summary, c.finding, c.transcript))):
            drop(c, f"záznam z návštěvy {c.id}")
    for rv in db.query(models.ProgramRevision).filter(models.ProgramRevision.note.contains(MARK)).all():
        p = db.get(models.Program, rv.program_id)
        own(p.runner_id, f"revize {rv.id}")
        out.append((f"smazat revizi programu {rv.id}", lambda r=rv: db.delete(r)))
    for key, model in (("conclusions", models.Conclusion), ("injury_reports", models.InjuryReport),
                       ("bookings", models.Booking)):
        for i in _ids(extra.get(key, "")):
            row = db.get(model, i)
            if row is not None:
                drop(row, f"{key} {i}")
    for i in _ids(extra.get("rtr", "")):
        plan_row = db.get(models.ReturnToRun, i)
        if plan_row is not None:
            own(plan_row.runner_id, f"plán návratu {i}")
            for s in db.query(models.RtrSession).filter(models.RtrSession.plan_id == i).all():
                out.append((f"smazat sezení {s.id} plánu {i}", lambda r=s: db.delete(r)))
            out.append((f"smazat plán návratu {i}", lambda r=plan_row: db.delete(r)))
    for i in _ids(extra.get("slots", "")):
        sl = db.get(models.PhysioSlot, i)
        if sl is not None:
            if sl.physio_id != DEMO_PHYSIO:
                raise Refused(f"Termín {i} nepatří demo fyzioterapeutce — nic se nezměnilo.")
            out.append((f"smazat termín {i}", lambda r=sl: db.delete(r)))
    if extra.get("messages_from"):
        start = int(extra["messages_from"])
        for m in db.query(models.Message).filter(models.Message.id >= start, models.Message.runner_id == "run-0001").all():
            drop(m, f"zprávu {m.id}")
    if extra.get("revisions_from"):
        start = int(extra["revisions_from"])
        for rv in db.query(models.ProgramRevision).filter(models.ProgramRevision.id >= start).all():
            p = db.get(models.Program, rv.program_id)
            if p and p.runner_id == "run-0001":
                out.append((f"smazat revizi programu {rv.id}", lambda r=rv: db.delete(r)))
    for i in _ids(extra.get("release", "")):
        t = db.get(models.Triage, i)
        if t is not None and t.claimed_by:
            own(t.runner_id, f"převzetí případu {i}")

            def rel(t=t):
                ca = db.query(models.CareAssignment).filter_by(physio_id=t.claimed_by, runner_id=t.runner_id).first()
                if ca:
                    db.delete(ca)
                t.claimed_by, t.status = None, "open"
            out.append((f"vrátit případ {i} do fronty", rel))
    now = datetime.now(timezone.utc)
    for sl in db.query(models.PhysioSlot).filter(models.PhysioSlot.physio_id == DEMO_PHYSIO,
                                                 models.PhysioSlot.status == "open").all():
        try:
            past = datetime.fromisoformat(sl.slot_at).replace(tzinfo=datetime.fromisoformat(sl.slot_at).tzinfo or timezone.utc) < now
        except ValueError:
            past = True
        if past:
            out.append((f"smazat prošlý volný termín {sl.id}", lambda r=sl: db.delete(r)))
    # what the seed defines for Adéla
    r = db.get(models.Runner, "run-0001")
    if r is not None and "run-0001" in demo and (r.prior_injury, r.prior_injury_months_ago) != ("Achillova šlacha", 8):
        def restore(r=r):
            r.prior_injury, r.prior_injury_months_ago = "Achillova šlacha", 8
        out.append(("obnovit dřívější zranění Adély (Achillova šlacha, před 8 měsíci)", restore))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--extra", action="append", default=[], help="key=ids, e.g. conclusions=47,48")
    a = ap.parse_args(argv)
    if os.environ.get("ALLOW_DEMO_RESET") != "1":
        print("Odmítnuto: nastavte ALLOW_DEMO_RESET=1.", file=sys.stderr)
        return 2
    extra = dict(x.split("=", 1) for x in a.extra)
    db = SessionLocal()
    try:
        try:
            steps = plan(db, extra)
        except Refused as e:
            print(f"Odmítnuto: {e}", file=sys.stderr)
            return 3
        for what, _ in steps:
            print(("" if a.apply else "[nanečisto] ") + what)
        if a.apply:
            for _, act in steps:
                act()
            db.commit()
            for rid in {"run-0001"}:
                E.recompute_assessment(db, rid)
        print(f"{len(steps)} změn" + ("" if a.apply else " (nic se nezměnilo, přidejte --apply)"))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
