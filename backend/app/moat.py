"""Phase 4, the moat (physio brief 2026-11-09 M1–M5).

M1 complements app/outcomes.py (engine snapshots against self-reported events) with labels a physio
confirmed. They come from what the physio already records (the episode's diagnosis code, side, onset,
discharge outcome and return date) plus the runner's 3-month answer. The pseudonymised export runs only when
the owner has stated the legal basis (`DOSSLAP_OUTCOME_EXPORT_BASIS`) and set a pseudonymisation key
(`DOSSLAP_PSEUDO_KEY`); without both it refuses. Only confirmed (coded) diagnoses with an outcome are exported.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import timedelta

from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import engine as E


# ============================================================================================ M1 outcomes
def followups_due(db: DBSession, rid: str) -> list[models.OutcomeFollowup]:
    today = E.today_date().isoformat()
    return (db.query(models.OutcomeFollowup).filter(models.OutcomeFollowup.runner_id == rid,
                                                    models.OutcomeFollowup.status == "scheduled",
                                                    models.OutcomeFollowup.due_on <= today).all())


def export_ready() -> str | None:
    """None when the export may run, else why not (shown to the owner)."""
    if not os.environ.get("DOSSLAP_OUTCOME_EXPORT_BASIS", "").strip():
        return "Chybí právní základ exportu (DOSSLAP_OUTCOME_EXPORT_BASIS) — nejdřív ho potvrďte s právníkem."
    if len(os.environ.get("DOSSLAP_PSEUDO_KEY", "")) < 32:
        return "Chybí klíč pro pseudonymizaci (DOSSLAP_PSEUDO_KEY, alespoň 32 znaků)."
    return None


def pseudo(rid: str) -> str:
    return hmac.new(os.environ["DOSSLAP_PSEUDO_KEY"].encode(), rid.encode(), hashlib.sha256).hexdigest()[:20]


def outcome_rows(db: DBSession) -> list[dict]:
    """M1.3/M1.4: confirmed diagnosis with an outcome; no names, no free text, dates as they are (the
    calibration needs onset and return dates)."""
    rows = []
    for ep in (db.query(models.CareEpisode).filter(models.CareEpisode.discharge_outcome.isnot(None),
                                                   models.CareEpisode.diagnosis_code.isnot(None)).all()):
        fu = (db.query(models.OutcomeFollowup).filter_by(episode_id=ep.id, status="answered")
              .order_by(models.OutcomeFollowup.id.desc()).first())
        rows.append({"subject": pseudo(ep.runner_id), "episode": ep.id, "diagnosis_code": ep.diagnosis_code,
                     "region": ep.region, "side": ep.side, "onset_date": ep.onset_date,
                     "opened_at": (ep.opened_at or "")[:10], "closed_at": (ep.closed_at or "")[:10],
                     "outcome_kind": ep.discharge_outcome, "return_to_run_date": ep.return_to_run_date,
                     "followup_running_normally": fu.running_normally if fu else None,
                     "followup_recurrence": fu.recurrence if fu else None,
                     "followup_pain": fu.pain if fu else None})
    return rows


# ============================================================================================ M2 recall
def recall_list(db: DBSession, physio_id: str) -> list[dict]:
    """Discharged clients who still share data with this physio (active consent) and whose current
    assessment says high load risk or new pain. The consent text tells runners this can happen."""
    out = []
    eps = (db.query(models.CareEpisode).filter_by(physio_id=physio_id, status="discharged")
           .order_by(models.CareEpisode.closed_at.desc()).all())
    seen = set()
    for ep in eps:
        if ep.runner_id in seen:
            continue
        seen.add(ep.runner_id)
        if db.query(models.CareEpisode).filter_by(physio_id=physio_id, runner_id=ep.runner_id, status="open").first():
            continue                       # already back in care
        if not db.query(models.CareAssignment).filter_by(physio_id=physio_id, runner_id=ep.runner_id, status="active").first():
            continue                       # no consent, no recall
        r = db.get(models.Runner, ep.runner_id)
        a = db.query(models.Assessment).filter_by(runner_id=ep.runner_id).order_by(models.Assessment.id.desc()).first()
        tier = getattr(a, "tier", None) if a else None
        since = (ep.closed_at or "")[:10]
        pain = (db.query(models.Checkin).filter(models.Checkin.runner_id == ep.runner_id,
                                                models.Checkin.submitted_at >= since,
                                                models.Checkin.pain_score >= 3).count() if since else 0)
        if tier == "alert" or pain:
            out.append({"runner_id": ep.runner_id, "name": r.name if r else ep.runner_id,
                        "discharged_on": since, "diagnosis": ep.diagnosis_label, "tier": tier, "pain_checkins": pain})
    return out


# ============================================================================================ M4 test battery
TESTS: dict[str, dict] = {
    "heel_raise_sl": {"name_cs": "Výpony na jedné noze do únavy", "unit": "opakování", "higher_better": True},
    "hop_sl": {"name_cs": "Skok na jedné noze do dálky", "unit": "cm", "higher_better": True},
    "triple_hop": {"name_cs": "Trojskok na jedné noze", "unit": "cm", "higher_better": True},
    "sl_squat": {"name_cs": "Dřep na jedné noze", "unit": "opakování", "higher_better": True},
    "hop_endurance": {"name_cs": "Poskoky na jedné noze 30 s", "unit": "počet", "higher_better": True},
}


def lsi(left: float | None, right: float | None, involved: str | None) -> int | None:
    """Limb symmetry index: involved side / uninvolved × 100; without a marked side the weaker / stronger."""
    if not left or not right:
        return None
    if involved == "L":
        return round(100 * left / right)
    if involved == "R":
        return round(100 * right / left)
    return round(100 * min(left, right) / max(left, right))


def test_history(db: DBSession, rid: str) -> list[dict]:
    out = []
    for t in db.query(models.ClinicTest).filter_by(runner_id=rid).order_by(models.ClinicTest.tested_on.asc()).all():
        out.append({"id": t.id, "test": t.test, "name": TESTS.get(t.test, {}).get("name_cs", t.test),
                    "unit": TESTS.get(t.test, {}).get("unit"), "left": t.left, "right": t.right,
                    "involved": t.involved, "lsi": lsi(t.left, t.right, t.involved), "tested_on": t.tested_on,
                    "booking_id": t.booking_id})
    return out


def latest_lsi(db: DBSession, rid: str) -> dict:
    """For W11's readiness gate: the newest LSI per test."""
    last: dict[str, dict] = {}
    for h in test_history(db, rid):
        last[h["test"]] = h
    return last
