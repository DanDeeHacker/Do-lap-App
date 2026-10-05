"""v0.12.0 — a possible illness from the watch: resting heart rate and breathing rate
while asleep above the runner's own norm.

Resting heart rate rose above the person's baseline days before and during a viral
infection, and adding sleep and activity changes to it separated COVID-positive from
negative symptomatic people (AUC 0.80; Quer et al., 2021). The breathing rate during
sleep is very stable within a person and rose before symptoms in WHOOP users (Miller et
al., 2020). A single night is noisy (alcohol, a late hard session, heat), so the flag
needs two nights in a row with either sign, or one night with both:

  • resting HR ≥ own mean + max(2 SD, 3 bpm), breathing ≥ own mean + max(2 SD, 1 br/min),
    the norm = nights 8–56 days back (≥ 10 nights).

The flag doesn't diagnose anything: it makes the daily check-in ask at most two
questions (symptoms at all; symptoms below the neck — fever, aching muscles, chest
cough), and the recommendation follows the answers ("neck check", Eichner 1993; the
IOC consensus on illness in athletes, Schwellnus et al., 2016): below the neck → rest,
above the neck only → easy and short, nothing or no answer → no intensity today.
"""
from datetime import date, timedelta

from . import engine as E

BASE = (8, 56)
BASE_MIN = 10
RHR_Z, RHR_MIN_BPM, RHR_SD_FLOOR = 2.0, 3.0, 1.0
RESP_Z, RESP_MIN, RESP_SD_FLOOR = 2.0, 1.0, 0.3


def _norm(dm, d0, fld):
    vals = [getattr(dm.get((d0 - timedelta(days=j)).isoformat()), fld, None) for j in range(BASE[0], BASE[1] + 1)]
    vals = [v for v in vals if v is not None]
    if len(vals) < BASE_MIN:
        return None
    return E.mean(vals), E.sd(vals) or 0.0


def _night(dm, d0, norms) -> dict:
    row = dm.get(d0.isoformat())
    out = {"d": d0.isoformat(), "high": []}
    for fld, key, z, floor_, sdf in (("resting_hr", "rhr", RHR_Z, RHR_MIN_BPM, RHR_SD_FLOOR),
                                      ("resp_rate", "resp", RESP_Z, RESP_MIN, RESP_SD_FLOOR)):
        v = getattr(row, fld, None) if row is not None else None
        nm = norms.get(key)
        if v is None or nm is None:
            continue
        m, sd = nm
        out[key] = round(v, 1)
        out[key + "Norm"] = round(m, 1)
        if v >= m + max(z * max(sd, sdf), floor_):
            out["high"].append(key)
    return out


def illness_signal(data, day: str) -> dict | None:
    """{since, nights[2], kinds[]} when the last two nights look like an oncoming
    illness (see the module text), else None."""
    dm = data.daily_by_date
    d0 = date.fromisoformat(day[:10])
    norms = {k: _norm(dm, d0, f) for k, f in (("rhr", "resting_hr"), ("resp", "resp_rate"))}
    if not any(norms.values()):
        return None
    last, prev = _night(dm, d0, norms), _night(dm, d0 - timedelta(days=1), norms)
    if not last["high"]:
        return None
    two = bool(prev["high"])
    both = len(last["high"]) == 2
    if not (two or both):
        return None
    kinds = sorted(set(last["high"]) | set(prev["high"]))
    return {"since": prev["d"] if two else last["d"], "nights": [prev, last], "kinds": kinds}
