"""Plan phase 4: gated calibration report on synthetic snapshots and events."""
import math
import random
from datetime import timedelta

from app import calibration as CAL
from app import models
from app.metrics import engine as E
from .conftest import register


def test_rcs_basis_is_linear_beyond_the_outer_knots():
    kn = [0.0, 1.0, 2.0, 3.0]
    a, b, c = (CAL.rcs_basis(x, kn) for x in (4.0, 5.0, 6.0))
    for j in range(len(a)):
        assert abs((c[j] - b[j]) - (b[j] - a[j])) < 1e-9     # second difference zero past the last knot
    assert CAL.rcs_basis(-1.0, kn)[1:] == [0.0, 0.0]


def test_logistic_recovers_a_known_slope():
    rng = random.Random(3)
    X, y = [], []
    for _ in range(3000):
        x = rng.uniform(-3, 3)
        X.append([1.0, x])
        y.append(1.0 if rng.random() < 1 / (1 + math.exp(-(-1 + 1.5 * x))) else 0.0)
    b = CAL.fit_logistic(X, y)
    assert abs(b[0] + 1) < 0.2 and abs(b[1] - 1.5) < 0.2


def test_report_is_gated_then_scores_a_signal(client, db_session, monkeypatch):
    db = db_session
    rng = random.Random(7)
    today = E.today_date()
    for i in range(12):
        rid = register(client, f"cal{i}@test.cz", "Cal", "runner").json()["runner_id"]
        overall = 0
        for back in range(120, 0, -1):
            d = (today - timedelta(days=back)).isoformat()
            if back % 7 == 0:                                   # points hold for a week, like real load blocks
                overall = rng.choice((5, 10, 15, 45, 55))
            db.add(models.EngineDailySnapshot(runner_id=rid, date=d, overall=overall, load=overall, mech=0, symp=0,
                                              features_json={"readiness": 90}))
            if rng.random() < (0.05 if overall > 40 else 0.004):     # events follow high points
                db.add(models.InjuryReport(runner_id=rid, source="self_adhoc", status="active", severity=25,
                                           submitted_at=(today - timedelta(days=back - 3)).isoformat()))
    db.commit()
    assert CAL.report(db)["status"] == "gated"
    rep = CAL.report(db, force=True, target_p=0.1)
    assert rep["status"] == "ok" and rep["baseline"]["brier"] <= rep["nullBrier"] + 1e-6
    assert rep["mapping"]["probAt25"] > 0 and "pointsForTarget" in rep["mapping"]
    assert rep["baseline"]["calibration"] and rep["spline"] is not None
    csv = CAL.to_csv(CAL.dataset(db))
    assert csv.splitlines()[0].startswith("runner_id,date,event")

    register(client, "calowner@test.cz", "Owner", "runner")
    client.post("/api/auth/session", json={"email": "calowner@test.cz", "password": "testpass123"})
    assert client.get("/api/engine/calibration").status_code == 403
    monkeypatch.setenv("DOSSLAP_OWNER_EMAILS", "calowner@test.cz")
    assert client.get("/api/engine/calibration").json()["status"] in ("gated", "ok")
    assert client.get("/api/engine/calibration/export").text.startswith("runner_id")
