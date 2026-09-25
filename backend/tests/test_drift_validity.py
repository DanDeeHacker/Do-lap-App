"""Validity of the per-run mechanics drift core (both engines): pace confound
removed, v2 noise calibrated, v2 narrative consistent with its z."""
import random
from datetime import timedelta
from types import SimpleNamespace

from app.metrics import engine as E


def _run(days_ago, pace, rng, drift=0.0):
    """Mechanics that depend on SPEED (like real running), plus optional drift in
    form that is independent of speed."""
    cad = 172 - 0.12 * (pace - 355) + rng.gauss(0, 1.5) - drift * 1.5
    speed = 1000 / pace
    stride = speed * 60 / cad * 2
    vosc = 8.5 + rng.gauss(0, 0.3)
    return SimpleNamespace(
        started_at=E.iso_date(E.today_date() - timedelta(days=days_ago)), distance_km=10.0,
        ascent_m=20, descent_m=20, duration_min=pace * 10 / 60, surface="road",
        cadence_spm=cad, stride_len_m=stride, vert_osc_cm=vosc,
        vert_ratio_pct=vosc / (stride / 2 * 100) * 100,
    )


def _history(slow=0.0, drift=0.0, seed=1):
    rng = random.Random(seed)
    out = []
    for d in range(90, -1, -1):
        if rng.random() > 0.7:
            continue
        pace = rng.uniform(335, 385) + (slow if d <= 21 else 0.0)   # all inside the "easy" bucket
        out.append(_run(d, pace, rng, drift if d <= 21 else 0.0))
    return out


def test_slower_easy_runs_are_not_mechanical_drift():
    """Easy runs 25 s/km slower (heat, fatigue, running easier) with unchanged
    form: cadence falls and vertical ratio rises *because of speed*. Before the
    pace adjustment this read as drift ~75 % of the time (→ 'silent drift' →
    physio referral); the runner's own speed sensitivity now removes it."""
    for mode in ("v1", "v2"):
        zs = {"cadence_spm": [], "vert_ratio_pct": []}
        for seed in range(12):
            A = _history(slow=25.0, seed=seed)
            with E.engine_pinned(mode):
                for f in zs:
                    r = E._drift_z_core(A, f, 28)
                    assert r["paceAdjusted"] is True
                    zs[f].append(r["z"])
        assert abs(E.mean(zs["cadence_spm"])) < 0.3, (mode, zs)
        assert abs(E.mean(zs["vert_ratio_pct"])) < 0.3, (mode, zs)


def test_real_drift_at_same_pace_still_detected():
    for mode in ("v1", "v2"):
        zs = []
        for seed in range(8):
            with E.engine_pinned(mode):
                zs.append(E._drift_z_core(_history(drift=1.5, seed=seed), "cadence_spm", 28)["z"])
        assert E.mean(zs) < -0.8, (mode, zs)       # cadence clearly down


def _null_history(rng):
    out = []
    for d in range(90, -1, -1):
        if rng.random() > 0.6:
            continue
        out.append(SimpleNamespace(
            started_at=E.iso_date(E.today_date() - timedelta(days=d)), distance_km=10.0, ascent_m=20,
            descent_m=20, duration_min=50.0, surface="road", vert_ratio_pct=8.0 + 0.3 * rng.gauss(0, 1)))
    return out


def test_v2_false_signal_rate_is_calibrated():
    """No real change: v2 shows a signal (z ≥ 0.6) about 5 % of the time (was
    ~12 % before the noise-scale fix + λ calibration)."""
    rng = random.Random(11)
    n, shown = 500, 0
    with E.engine_pinned("v2"):
        for _ in range(n):
            shown += E._drift_z_core(_null_history(rng), "vert_ratio_pct", 28)["z"] >= 0.6
    assert shown / n < 0.08


def test_v2_detail_and_means_are_consistent_with_z():
    rng = random.Random(3)
    A = _null_history(rng)
    for a in A[-6:]:
        a.vert_ratio_pct += 0.5            # recent rise
    with E.engine_pinned("v2"):
        r = E._drift_z_core(A, "vert_ratio_pct", 28)
    assert r["z"] > 0 and r["recMean"] > r["baseMean"]      # narrative sign matches z
    recon = sum(d["weight"] * d["z"] for d in r["detail"])
    assert abs(recon - r["z"]) < 0.02                         # bucket detail decomposes z
