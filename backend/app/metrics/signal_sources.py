"""Feedback railway#113 — what each signal on Dnes comes from.

Every signal gets `sources`: the activities, check-ins, run ratings, nights or injury
reports behind it, newest or largest first. Where the engine itself splits a signal
between records, a source carries `share` (0–1) and the popup shows that share of the
signal's effect on the Skóre:
  • a capacity channel set by one run or one fading jump → that activity, share 1;
  • a capacity channel set by the unabsorbed 7-day load → every session by its share of
    that residual load (the same split as Zátěž → Historie aktivit);
  • higher heart rate at the usual pace → each run by its share of the excess;
  • repeated niggles → each rated run equally (the engine counts them).
Elsewhere (pain, recovery, mechanics) the engine scores a pattern, not a sum of records.
railway#132 asked to see every item's p. b. there too, so those records get an
approximate share: by pain intensity, by the night's or run's deviation from the
runner's norm, by the value in the record, by activity duration, or equally where the
engine only counts records. `shareNote` tells the popup which split it shows.
"""
from datetime import timedelta

from . import data as D
from . import engine as E

MAX_SOURCES = 8
PAIN_DAYS = {"pain": 28, "complaints": 28, "pain_prior": E.PRIOR_HIT_WINDOW, "function": 14, "acute": 14,
             "pain_morning": 14, "pain_trend": 14, "bone_stress": 14, "bone_pain": 14, "red_flag": 14}
MECH_FIELD = {"tavr": ("vert_ratio_pct", "%", 1), "gct": ("gct_ms", "ms", 0), "gaitcv": ("gct_ms", "ms", 0),
              "cad": ("cadence_spm", "spm", 0), "vosc": ("vert_osc_cm", "cm", 1), "bal": ("gct_balance_l", "% vlevo", 1)}
MECH_BASE = {"tavr": "tavr", "gct": "gct", "cad": "cadence", "vosc": "vosc"}
RECOVERY = {"hrv", "rhr", "hrv_high", "hrvcv", "sleep", "sleepreg", "sleepeff", "load_capacity", "tsb"}
SPORT_CS = {"running": "běh", "cycling": "kolo", "swimming": "plavání", "strength": "silový trénink", "rowing": "veslování",
            "elliptical": "orbitrek", "hiking": "turistika", "walking": "chůze", "other": "jiný sport"}


def _num(v, dec=0):
    if v is None:
        return "—"
    return (f"{v:.{dec}f}" if dec else str(round(v))).replace(".", ",")


def _val(v):
    return _num(v, 1) if isinstance(v, float) and v != int(v) else _num(v)


def _mmss(sec):
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def _src(kind, date, title, detail, share=None, aid=None, w=None):
    return {"kind": kind, "date": (date or "")[:10], "title": title, "detail": detail,
            "share": None if share is None else round(share, 3), "aid": aid, "_w": w}


# railway#132 — how the approximate shares are split, per kind of signal
SHARE_NOTE = {
    "pain": "Podíl je přibližný. Signál hodnotí vzorec bolesti, ne součet záznamů, proto ho dělíme podle síly bolesti v záznamu.",
    "count": "Podíl je přibližný. Signál počítá záznamy stejnou vahou, proto má každý stejný díl.",
    "equal": "Podíl je přibližný. Záznamy se od vaší normy liší podobně, proto má každý stejný díl.",
    "night": "Podíl je přibližný. Dělíme ho podle toho, jak moc se noc odchýlila od vaší normy za 4 týdny.",
    "mech": "Podíl je přibližný. Dělíme ho podle toho, jak moc se běh odchýlil od vaší normy.",
    "value": "Podíl je přibližný. Dělíme ho podle hodnoty v záznamu.",
    "duration": "Podíl je přibližný. Dělíme ho podle délky aktivity.",
}


def _region(p):
    lbl = E._REGION_LABEL.get(p.get("region"), p.get("region") or "")
    side = E._SIDE_CZ.get(p.get("side") or "", "")
    return f"{lbl} {side}".strip()


def pain_entries(db, rid, days, match=None):
    """Check-ins, run ratings and injury reports with pain in the last `days` days,
    newest first; `match(point)` keeps only records marking a matching site."""
    cut = E.day_ago(days)
    out = []
    data = D.of(db, rid)
    fbs = [f for f in data.feedback if f.submitted_at > cut]
    titles = {a.id: a.title for a in data.activities}

    def pts(points):
        ps = [p for p in (points or []) if p.get("region")]
        return [p for p in ps if match(p)] if match else ps

    for c in (c for c in data.checkins if c.submitted_at > cut):
        ps = pts(c.pain_points)
        if (match and ps) or (not match and ((c.pain_score or 0) > 0 or ps)):
            where = ", ".join(_region(p) for p in ps) or (c.pain_site or "bez místa")
            out.append(_src("checkin", c.submitted_at, "Check-in", f"{where} · bolest {c.pain_score or 0}/10", w=max(1, c.pain_score or 0)))
    for f in fbs:
        ps = pts(f.pain_points)
        if (match and ps) or (not match and ((f.pain_during or 0) > 0 or f.niggle or ps)):
            where = ", ".join(_region(p) for p in ps) or (f.pain_site or "bez místa")
            out.append(_src("rating", f.submitted_at, titles.get(f.activity_id) or "Hodnocení běhu",
                            f"{where} · bolest při běhu {f.pain_during or 0}/10", aid=f.activity_id, w=max(1, f.pain_during or 0)))
    for rep in (x for x in data.injuries if x.submitted_at > cut):
        ps = pts(rep.pain_points)
        if (match and ps) or (not match and (ps or rep.body_region)):
            where = ", ".join(_region(p) for p in ps) or E._REGION_LABEL.get(rep.body_region, rep.body_region or "")
            out.append(_src("report", rep.submitted_at, "Hlášení zranění", where or "bez místa", w=5))
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:MAX_SOURCES]


# signal → (DailyMetric field, +1 when a lower value is worse, −1 when a higher one is)
NIGHT_DEV = {"hrv": ("hrv_ms", 1), "hrv_high": ("hrv_ms", -1), "rhr": ("resting_hr", -1), "sleep": ("sleep_h", 1),
             "sleepeff": ("sleep_efficiency", 1)}


def _nights(db, rid, n=7, sid=None):
    lo = E.day_ago(28)[:10]
    rows = [m for m in D.of(db, rid).daily if m.date >= lo]
    fld, sign = NIGHT_DEV.get(sid, (None, 0))
    vals = [getattr(m, fld) for m in rows if fld and getattr(m, fld) is not None]
    ref = sum(vals) / len(vals) if vals else None
    out = []
    for m in sorted(rows, key=lambda x: x.date, reverse=True)[:n]:
        bits = [m.hrv_ms is not None and f"HRV {_num(m.hrv_ms)} ms", m.resting_hr is not None and f"klidový tep {_num(m.resting_hr)}",
                m.sleep_h is not None and f"spánek {_num(m.sleep_h, 1)} h",
                m.sleep_efficiency is not None and f"efektivita {_num(m.sleep_efficiency * 100)} %"]
        bits = [b for b in bits if b]
        if bits:
            v = getattr(m, fld) if fld else None
            w = max(0.0, sign * (ref - v)) if (v is not None and ref is not None) else (0.0 if fld else None)
            out.append(_src("night", m.date, "Noc", " · ".join(bits), w=w))
    return out


def _capacity(cap, ch, titles):
    c = (cap or {}).get("channels", {}).get(ch) or {}
    unit, drv = c.get("unit", ""), c.get("driver")
    if drv == "session" and c.get("session"):
        s = c["session"]
        return [_src("activity", s["date"], s["title"], f"{_val(s['value'])} {unit} proti kapacitě {_val(s['cap'])} {unit} "
                     f"(×{_num(s['ratio'], 2)})", 1.0, s.get("id"))]
    if drv == "latent" and c.get("latent"):
        lt = c["latent"]
        return [_src("activity", lt["date"], titles.get(lt.get("id")) or "Aktivita",
                     f"skok ×{_num(lt['ratio'], 2)} proti kapacitě, doznívá do 28 dnů", 1.0, lt.get("id"))]
    if drv == "week":
        return [_src("activity", w["date"], w["title"], f"{_val(w['value'])} {unit} · {round(w['share'] * 100)} % nevstřebané "
                     "zátěže za 7 dní", w["share"], w["id"]) for w in (c.get("weekSources") or [])]
    return []


def _pace_spike(db, rid, a):
    """The fastest recent run against the runner's own fast runs (engine.load)."""
    L = a.get("loadDetail") or {}
    aid = L.get("paceSpikeId")
    x = next((r for r in D.of(db, rid).activities if r.id == aid), None) if aid is not None else None
    if x is None or not x.distance_km or not x.duration_min:
        return []
    pace = x.duration_min / x.distance_km * 60
    ref = L.get("paceSpikeRefSKm")
    return [_src("activity", x.started_at, x.title, f"{_mmss(pace)}/km" + (f" proti vašim obvykle nejrychlejším {_mmss(ref)}/km"
                 if ref else "") + " (s přepočtem na převýšení)", 1.0, x.id)]


def _hr_pace(cap):
    rows = [x for x in ((cap or {}).get("relativeEffort") or {}).get("runs") or []
            if x.get("hrDelta") is not None and not x.get("hot") and not x.get("hilly")][:4]
    pos = sum(max(0, x["hrDelta"]) for x in rows)
    return [_src("activity", x["date"], x["title"], f"tep {'+' if x['hrDelta'] > 0 else ''}{_num(x['hrDelta'])} proti obvyklému "
                 f"při tomto tempu (čekaný {_num(x.get('hrExpected'))})", max(0, x["hrDelta"]) / pos if pos > 0 else None)
            for x in rows]


def _week_acts(db, rid):
    out = []
    for a in sorted((a for a in E.all_acts(db, rid, "load") if a.started_at and a.started_at > E.day_ago(7)),
                    key=lambda a: a.started_at, reverse=True):
        bits = [SPORT_CS.get(a.sport or "running", a.sport), a.distance_km and f"{_num(a.distance_km, 1)} km",
                a.duration_min and f"{_num(a.duration_min)} min"]
        out.append(_src("activity", a.started_at, a.title, " · ".join(b for b in bits if b), aid=a.id, w=a.duration_min or 0))
    return out[:MAX_SOURCES]


def _mech(db, rid, sid, a):
    fld, unit, dec = MECH_FIELD.get(sid, (None, None, 0))
    base = ((a.get(MECH_BASE.get(sid, "")) or {}).get("baseMean")) if sid in MECH_BASE else None
    out = []
    runs = [x for x in E.acts(db, rid, "mech") if x.started_at and x.started_at > E.day_ago(E.RECENT)]
    for x in sorted(runs, key=lambda x: x.started_at, reverse=True):
        v = getattr(x, fld, None) if fld else None
        if fld and v is None:
            continue
        detail = f"{_num(v, dec)} {unit}" + (f" (vaše norma {_num(base, dec)} {unit})" if base is not None else "") if fld else \
            f"{_num(x.distance_km, 1)} km"
        out.append(_src("activity", x.started_at, x.title, detail, aid=x.id,
                        w=abs(v - base) if (v is not None and base is not None) else None))
    return out[:MAX_SOURCES]


def _ratings(db, rid, sid):
    cut = E.day_ago(21)
    data = D.of(db, rid)
    fbs = [f for f in data.feedback if f.submitted_at > cut]
    if sid == "niggle":
        fbs = [f for f in fbs if f.niggle]
    titles = {x.id: x.title for x in data.activities}
    out = []
    for f in sorted(fbs, key=lambda f: f.submitted_at, reverse=True):
        w = None
        if sid == "niggle":
            d = f"{f.pain_site or 'bolestivé místo'} · bolest při běhu {f.pain_during or 0}/10"
        elif sid == "feel":
            d = f"pocit z běhu {f.feeling}/5" if f.feeling is not None else None
            w = max(0, 5 - (f.feeling or 5))
        else:
            d = f"ztuhlost před během {f.stiffness_pre}/5" + (f" · RPE {f.rpe}" if f.rpe is not None else "") if f.stiffness_pre is not None else None
            w = f.stiffness_pre or 0
        if d:
            out.append(_src("rating", f.submitted_at, titles.get(f.activity_id) or "Hodnocení běhu", d,
                            1 / len(fbs) if sid == "niggle" else None, f.activity_id, w=w))
    return out[:MAX_SOURCES]


def _checkins(db, rid, days, pick, weight=None):
    out = []
    for c in (c for c in D.of(db, rid).checkins if c.submitted_at > E.day_ago(days)):
        d = pick(c)
        if d:
            out.append(_src("checkin", c.submitted_at, "Check-in", d, w=weight(c) if weight else None))
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:MAX_SOURCES]


def sources_for(db, rid, sid, a, cap, runner, titles):
    if sid.startswith("cap_"):
        return _capacity(cap, sid[4:], titles)
    if sid == "pace_spike":
        return _pace_spike(db, rid, a)
    if sid == "hr_pace":
        return _hr_pace(cap)
    if sid in ("mono", "session_spike", "spike_latent", "ewma", "hi_load", "load_creep", "desc", "desc_steep", "aer", "taper"):
        return _week_acts(db, rid)
    if sid in RECOVERY:
        return _nights(db, rid, sid=sid)
    if sid in MECH_FIELD or sid == "dec":
        return _mech(db, rid, sid, a)
    if sid == "niggle":            # v0.9.3: the repeated sore spot's marks (check-ins and run ratings)
        reg, _, side = (a.get("_niggleRegion") or "").partition("|")
        return pain_entries(db, rid, 28, lambda p: (E._norm_region(p.get("region")) or "") == reg
                            and E._SIDE_KEY.get(p.get("side") or "", "") == side) if reg else []
    if sid in ("feel", "stiffness"):
        return _ratings(db, rid, sid)
    if sid == "life_stress":
        return _checkins(db, rid, 1, lambda c: getattr(c, "life_stress", None) is not None and c.life_stress >= 6
                         and f"stres mimo trénink {c.life_stress}/10", lambda c: c.life_stress)
    if sid == "sleep_self":
        return _checkins(db, rid, 1, lambda c: getattr(c, "sleep_quality", None) in (0, 1)
                         and f"noc {'velmi špatně' if c.sleep_quality == 0 else 'špatně'}")
    if sid == "sore":
        return _checkins(db, rid, 4, lambda c: c.soreness is not None and c.soreness >= 7 and f"svalová únava {c.soreness}/10", lambda c: c.soreness)
    if sid == "fatigue":
        return _checkins(db, rid, 4, lambda c: c.stress is not None and c.stress >= 6 and f"únava {c.stress}/10", lambda c: c.stress)
    if sid == "cluster":
        return _checkins(db, rid, 28, lambda c: c.stress is not None and c.stress >= 6 and f"únava {c.stress}/10")
    if sid == "pain_prior":
        sites = E.prior_injury_sites(db, runner, rid)
        return pain_entries(db, rid, PAIN_DAYS[sid], lambda p: any(E._site_matches(p.get("region"), p.get("side"), s) for s in sites))
    if sid == "complaints":
        return pain_entries(db, rid, PAIN_DAYS[sid], lambda p: E._run_relevant(p.get("region")))
    if sid == "injury":
        return pain_entries(db, rid, 28, lambda p: True) or []
    if sid in PAIN_DAYS:
        return pain_entries(db, rid, PAIN_DAYS[sid])
    return []


def _note_kind(sid: str) -> str:
    if sid in ("pain_prior", "complaints", "cluster"):
        return "count"
    if sid in PAIN_DAYS or sid == "injury":
        return "pain"
    if sid in RECOVERY:
        return "night"
    if sid in MECH_FIELD or sid == "dec":
        return "mech"
    if sid in ("feel", "stiffness", "sore", "fatigue", "life_stress"):
        return "value"
    return "duration"


def split_shares(sid: str, src: list) -> str | None:
    """railway#132 — fills an approximate `share` where the engine gives none; returns
    the key of the note that says how (None when the shares are the engine's own)."""
    if not src:
        return None
    if any(x.get("share") is not None for x in src):
        for x in src:
            x.pop("_w", None)
        return None
    kind = _note_kind(sid)
    ws = [x.get("_w") for x in src]
    if kind != "count" and (any(w is None for w in ws) or sum(ws) <= 0):
        kind = "equal"
    if kind in ("count", "equal"):
        ws = [1.0] * len(src)
    tot = sum(ws)
    for x, w in zip(src, ws):
        x["share"] = round(w / tot, 3)
        x.pop("_w", None)
    return kind


def attach(db, rid, a: dict, runner=None) -> None:
    """Adds `sources` to every signal of an assessment (in place)."""
    cap = a.get("capacity")
    titles = {}
    ids = [((cap or {}).get("channels", {}).get(ch[4:]) or {}).get("latent", {}) or {} for ch in
           (s["id"] for s in a.get("signals") or []) if ch.startswith("cap_")]
    want = {x.get("id") for x in ids if x.get("id")}
    db = D.of(db, rid)
    if want:
        titles = {x.id: x.title for x in db.activities if x.id in want}
    for s in a.get("signals") or []:
        if s["id"] == "niggle":
            a["_niggleRegion"] = s.get("region")
        try:
            s["sources"] = sources_for(db, rid, s["id"], a, cap, runner, titles)
            note = split_shares(s["id"], s["sources"])
            s["shareNote"] = SHARE_NOTE.get(note) if note else None
        except Exception:             # a source list is a convenience — never break the assessment
            s["sources"] = []
            s["shareNote"] = None
    a.pop("_niggleRegion", None)
