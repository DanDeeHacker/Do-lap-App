"""Synthetic runner histories for engine tests: enough per-run data to pass the
mechanics confidence gate, plus optional stored segment streams."""
import random

from app import models
from app.metrics import engine as E


def seed_runs(db, rid, days=100, p_run=0.75, seed=1, pace_fn=None):
    """~`p_run` runs/day over `days` days of flat road running with realistic
    per-run noise. `pace_fn(days_ago) -> s/km` overrides the default pace."""
    rng = random.Random(seed)
    out = []
    for d in range(days, -1, -1):
        if rng.random() > p_run:
            continue
        pace = pace_fn(d) if pace_fn else rng.uniform(335, 380)
        km = 10.0
        cad = 172 - 0.12 * (pace - 355) + rng.gauss(0, 1.5)
        speed = 1000 / pace
        stride = speed * 60 / cad * 2
        vosc = 8.5 + rng.gauss(0, 0.3)
        a = models.Activity(
            runner_id=rid, provider="garmin", external_id=f"{rid}-{d}", started_at=E.day_ago(d),
            sport="running", title="Běh", distance_km=km, duration_min=pace * km / 60, pace_s_km=pace,
            avg_hr=145 + rng.gauss(0, 3), surface="road", ascent_m=20, descent_m=20,
            cadence_spm=cad, stride_len_m=stride, vert_osc_cm=vosc,
            vert_ratio_pct=vosc / (stride / 2 * 100) * 100,
            gct_ms=250 + 0.5 * (pace - 355) + rng.gauss(0, 5), gct_balance_l=50 + rng.gauss(0, 0.3),
        )
        db.add(a)
        out.append(a)
    db.commit()
    return out


def seg(g, gct, t=0, v=3.0, surface="road", vr=8.0):
    band = "B1" if g < -0.10 else "B2" if g < -0.03 else "B3" if g < 0.03 else "B4" if g < 0.10 else "B5"
    return {"band": band, "surface": surface, "durationS": 60, "meanSpeed": v, "meanGradient": g,
            "elapsedS": t, "cumDescentM": 0.0, "gct_ms": gct, "vratio_pct": vr, "cadence_spm": 172.0}


def add_streams(db, rid, shift_fn, seed=2, n_seg=10):
    """One stored stream per running activity; `shift_fn(started_at) -> ms` is
    added to every segment's GCT (0 = baseline behaviour)."""
    rng = random.Random(seed)
    for a in E.acts(db, rid):
        shift = shift_fn(a.started_at)
        day_off = rng.gauss(0, 2.0)  # session-level (day-to-day) variation
        segs = []
        for i in range(n_seg):
            g = -0.08 + i * 0.018
            v = 2.9 + (i % 3) * 0.1
            segs.append(seg(g, 240 + 100 * g + 8 * (v - 3.0) + day_off + shift + rng.gauss(0, 3), t=i * 60, v=v))
        db.add(models.ActivityStream(activity_id=a.id, runner_id=rid, external_id=a.external_id,
                                     segments_json=segs, created_at=E.now_iso()))
    db.commit()
