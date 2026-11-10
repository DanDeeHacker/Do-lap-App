"""Physio brief round 2 F1 e2e helper: add a confirmed visit two hours ago for a demo runner, with no record yet,
to the local database the e2e server uses (DOSSLAP_DB_PATH). Prints the booking id. Demo data only."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.metrics import engine as E  # noqa: E402

rid = sys.argv[1] if len(sys.argv) > 1 else "run-0001"
db = SessionLocal()
at = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)
while db.query(models.Booking).filter_by(physio_id="phy-0001", slot_at=at.isoformat()).first():
    at -= timedelta(minutes=7)
b = models.Booking(runner_id=rid, physio_id="phy-0001", slot_at=at.isoformat(), kind="follow_up",
                   status="confirmed", created_at=E.now_iso(), duration_min=45)
db.add(b)
db.commit()
print(b.id)
