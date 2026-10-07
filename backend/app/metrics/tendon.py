"""Suggestion #7 (owner request 2026-10-05): the 24-hour tendon check.

The engine already follows the pain-monitoring model (engine.pain_monitor, Silbernagel et
al., 2007): pain during a run up to 5/10 is acceptable when it settles by the next morning
and doesn't grow week to week. What it lacked is a measure of "settled" that is the same
every morning: a check-in asks about pain in general, and a tendon often hurts only under
load. So for a marked Achilles or patellar tendon the morning report asks for one standard
load test, the same every day. Monitoring the 24-hour response with a load test is the
clinical recommendation for tendinopathy (Malliaras et al., 2015): single-leg heel raises
for the Achilles tendon, a single-leg squat for the patellar tendon.

  • asked when the tendon was marked painful (check-in or run rating) in the last 7 days,
    or tested in the last 7 days (the monitoring goes on until it's quiet);
  • baseline = the latest test of the same tendon before the run (the morning of the run
    day or up to 7 days before it);
  • the morning after a run: 2 or more points above the baseline → the tendon didn't settle,
    no running today (the engine's morningWorse, running ceilings 0); 1 point above → hold,
    no progression; at or below the baseline → it took the load;
  • a test above 5/10 → no running today either (over the model's limit);
  • the weekly mean of the tests at least 1 point above the week before (2 or more tests in
    each week, reaching 2/10) → rising week to week (the engine's trend, one step back).

The test is not a check-in: it doesn't change the pain episodes on Příznaky. Two points is
the smallest change of a 0–10 pain rating that is more than noise (Farrar et al., 2001);
the 7-day windows and "no running above 5/10 in the test" are working assumptions."""
from datetime import date, timedelta
from statistics import mean

from . import data as D

TENDONS = {
    "achilles": {"match": ("achill",), "name": "Achillova šlacha", "test": "heel_raise",
                 "testName": "10 výponů na jedné noze", "figure": "heel_raise_1",
                 "how": ["Stoupněte si na nohu s bolavou šlachou, druhou pokrčte a rukou se lehce přidržte zdi.",
                         "Desetkrát pomalu nahoru na špičku a zpět dolů na celou plosku.",
                         "Ohodnoťte nejhorší bolest ve šlaše během testu: 0 žádná, 10 nejhorší představitelná."]},
    "patellar": {"match": ("patel",), "name": "Patelární šlacha", "test": "sl_squat",
                 "testName": "5 pomalých dřepů na jedné noze", "figure": "sl_squat",
                 "how": ["Stoupněte si na nohu s bolavou šlachou a rukou se lehce přidržte opěradla.",
                         "Pětkrát pomalu do dřepu, koleno nad špičkou, jen tak hluboko, jak to jde, a zpět.",
                         "Ohodnoťte nejhorší bolest pod čéškou během testu: 0 žádná, 10 nejhorší představitelná."]},
}
ASK_DAYS = 7          # marked or tested in this many days → the test is asked
BASE_DAYS = 7         # the baseline test is at most this old at the run
RISE_RED = 2          # points above the baseline the morning after a run → no running today
RISE_HOLD = 1         # → hold, no progression
OVER = 5              # above this in the test (or during the run) = over the model's limit
TREND_RISE, TREND_MIN = 1.0, 2.0
LOG_DAYS = 14
SIDE_CZ = {"L": "levá", "P": "pravá"}


def tendon_of(region: str | None, side: str | None = None):
    """(tendon key, side L/P/"") of a body-map point, None when it isn't a monitored tendon."""
    low = (region or "").lower()
    for key, t in TENDONS.items():
        if any(m in low for m in t["match"]):
            s = (region or "").strip()
            sd = "P" if s.endswith("(P)") else "L" if s.endswith("(L)") else ""
            if not sd:
                sd = {"P": "P", "L": "L", "right": "P", "left": "L"}.get((side or "").strip(), "")
            return key, sd
    return None


def label(key: str, side: str) -> str:
    return f"{TENDONS[key]['name']} ({side})" if side in ("L", "P") else TENDONS[key]["name"]


def _points(row) -> list[tuple[str, str]]:
    out = []
    for p in (getattr(row, "pain_points", None) or []):
        t = tendon_of(p.get("region"), p.get("side"))
        if t:
            out.append(t)
    if not out and getattr(row, "pain_site", None):
        for part in str(row.pain_site).split(","):
            t = tendon_of(part)
            if t:
                out.append(t)
    return list(dict.fromkeys(out))


def _is_run(a) -> bool:
    return (a.sport or "running") == "running" and not (getattr(a, "excluded", False) and getattr(a, "excluded_scope", None) in (None, "all"))


def _same(t, key, side) -> bool:
    # a side-less mark matches either side and vice versa (an old mark without the side)
    return t[0] == key and (t[1] == side or not t[1] or not side)


def _run_pain(data, key, side, day: str):
    """Pain during the runs of `day` at the tendon: the rating's number when it marked the
    tendon, 0 when it was rated without it, None when no run of that day was rated."""
    vals = []
    for f in data.feedback:
        a = data.act_by_id.get(f.activity_id)
        if a is None or (a.started_at or "")[:10] != day or not _is_run(a):
            continue
        pts = _points(f)
        vals.append((f.pain_during or 0) if any(_same(t, key, side) for t in pts) else 0)
    return max(vals) if vals else None


def _ran(data, day: str) -> bool:
    return any((a.started_at or "")[:10] == day and _is_run(a) for a in data.activities)


def _tests(data, key, side, test):
    return [t for t in data.tendon_checks if t.site == key and (t.side or "") == side and (t.test or TENDONS[key]["test"]) == test]


def watched(data, today: date) -> list[tuple[str, str]]:
    """The tendons the test is asked for today: marked in a check-in or a run rating, or
    tested, in the last ASK_DAYS days."""
    cut = (today - timedelta(days=ASK_DAYS - 1)).isoformat()
    t_iso = today.isoformat()
    out = []
    for c in data.checkins:
        if cut <= (c.submitted_at or "")[:10] <= t_iso:
            out += _points(c)
    for f in data.feedback:
        a = data.act_by_id.get(f.activity_id)
        day = (a.started_at if a is not None else f.submitted_at or "")[:10]
        if cut <= day <= t_iso:
            out += _points(f)
    for t in data.tendon_checks:
        if cut <= t.date <= t_iso:
            out.append((t.site, t.side or ""))
    # a side-less mark of a tendon that is also marked with a side is the same tendon
    sided = {k for k, s in out if s}
    out = [(k, s) for k, s in out if s or k not in sided]
    return list(dict.fromkeys(out))


def verdict(data, today: date, key: str, side: str) -> dict:
    """Today's test of one tendon against its baseline and yesterday's run."""
    t_iso, y_iso = today.isoformat(), (today - timedelta(days=1)).isoformat()
    test = TENDONS[key]["test"]
    rows = sorted(_tests(data, key, side, test), key=lambda t: t.date)
    now = next((t for t in rows if t.date == t_iso), None)
    ran = _ran(data, y_iso)
    during = _run_pain(data, key, side, y_iso) if ran else None
    # the baseline: the latest earlier test — before the run when there was one (the run
    # day's morning counts, the test is done before the run)
    base_row = next((t for t in reversed(rows) if t.date < t_iso and
                     t.date >= (today - timedelta(days=BASE_DAYS + (1 if ran else 0))).isoformat()), None)
    base = base_row.pain if base_row is not None else None
    out = {"site": key, "side": side, "name": TENDONS[key]["name"], "label": label(key, side), "test": test, "testName": TENDONS[key]["testName"],
           "figure": TENDONS[key]["figure"], "how": TENDONS[key]["how"], "done": now is not None,
           "pain": now.pain if now else None, "stiffness": now.stiffness if now else None,
           "baseline": base, "baselineDate": base_row.date if base_row is not None else None,
           "ran": ran, "during": during, "state": None, "text": None, "trend": trend(data, today, key, side)}
    if now is None:
        return out
    rise = None if base is None else now.pain - base
    p, b, d = now.pain, base, during
    tr = out["trend"]
    # every text whole, with only numbers in it (the page translates whole sentences)
    if p > OVER:
        out["state"], out["text"] = "red", (f"Test {p}/10 je nad hranicí 5/10. Dnes bez běhu, kolo nebo plavání jen tehdy, "
                                            "když při nich šlacha nebolí. Pokud to tak zůstane i zítra, k fyzioterapeutovi.")
    elif ran and rise is not None and rise >= RISE_RED:
        out["state"], out["text"] = "red", (f"Šlacha se do rána neuklidnila: test {p}/10, před během {b}/10. Zátěž byla moc. "
                                            "Dnes bez běhu, další běh kratší a volnější.")
    elif d is not None and d > OVER:
        out["state"], out["text"] = "amber", (f"Držte zátěž, nepřidávejte: bolest při včerejším běhu byla {d}/10, nad hranicí "
                                              "5/10. Další běh stejný nebo o kus lehčí.")
    elif tr:
        out["state"], out["text"] = "amber", (f"Držte zátěž, nepřidávejte: ranní test se týden od týdne zhoršuje "
                                              f"({_cz(tr['before'])} → {_cz(tr['now'])}/10). Další běh stejný nebo o kus lehčí.")
    elif ran and rise == RISE_HOLD:
        out["state"], out["text"] = "amber", (f"Držte zátěž, nepřidávejte: test {p}/10, o bod horší než před během ({b}/10). "
                                              "Další běh stejný nebo o kus lehčí.")
    elif ran and b is not None:
        out["state"], out["text"] = "green", (f"Šlacha zátěž snesla: test {p}/10, před během {b}/10. "
                                              "Můžete pokračovat podle plánu.")
    elif b is None:
        out["state"], out["text"] = "base", ("Výchozí hodnota je uložená. Po dalším běhu ji ráno porovnáme, test dělejte "
                                             "vždy stejně a ve stejnou dobu.")
    else:
        out["state"], out["text"] = "green", (f"Test {p}/10, minule {b}/10. Včera bez běhu, takže jen pro srovnání; "
                                              "rozhodne ranní test po příštím běhu.")
    return out


def _cz(v) -> str:
    t = f"{v:.1f}".replace(".", ",")
    return t[:-2] if t.endswith(",0") else t


def trend(data, today: date, key: str, side: str):
    rows = _tests(data, key, side, TENDONS[key]["test"])
    now = [t.pain for t in rows if 0 <= (today - date.fromisoformat(t.date)).days < 7]
    before = [t.pain for t in rows if 7 <= (today - date.fromisoformat(t.date)).days < 14]
    if len(now) >= 2 and len(before) >= 2:
        mn, mb = mean(now), mean(before)
        if mn - mb >= TREND_RISE and mn >= TREND_MIN:
            return {"now": round(mn, 1), "before": round(mb, 1), "daysNow": len(now), "daysBefore": len(before)}
    return None


def log(data, today: date, key: str, side: str) -> list[dict]:
    """The last LOG_DAYS days: the morning test and the pain during that day's run."""
    out = []
    by_day = {t.date: t for t in _tests(data, key, side, TENDONS[key]["test"])}
    for k in range(LOG_DAYS - 1, -1, -1):
        d = today - timedelta(days=k)
        iso = d.isoformat()
        t = by_day.get(iso)
        ran = _ran(data, iso)
        out.append({"d": iso, "test": t.pain if t else None, "ran": ran,
                    "during": _run_pain(data, key, side, iso) if ran else None})
    return out


def monitor(src, rid: str, today: date) -> dict:
    """For engine.pain_monitor: {morningWorse, trend} from today's tests (None when quiet)."""
    data = D.of(src, rid)
    if not data.tendon_checks:
        return {"morningWorse": None, "trend": None}
    morning, tr = None, None
    for key, side in watched(data, today):
        v = verdict(data, today, key, side)
        if v["state"] == "red" and morning is None:
            morning = {"at": today.isoformat(), "runDate": (today - timedelta(days=1)).isoformat() if v["ran"] else None,
                       "site": v["label"], "morning": v["pain"], "during": v["during"] if v["during"] is not None else 0,
                       "source": "tendonTest", "baseline": v["baseline"], "test": v["testName"]}
        if v["trend"] and tr is None and not (v["pain"] is not None and v["pain"] <= 1):
            tr = {**v["trend"], "source": "tendonTest", "site": v["label"]}
    return {"morningWorse": morning, "trend": tr}


def card(data, today: date) -> dict | None:
    """The morning report's tendon card: every watched tendon with today's verdict and log."""
    items = []
    for key, side in watched(data, today):
        v = verdict(data, today, key, side)
        v["log"] = log(data, today, key, side)
        items.append(v)
    if not items:
        return None
    return {"items": items, "allDone": all(x["done"] for x in items)}


def note(c: dict | None) -> str | None:
    if not c:
        return None
    parts = []
    for x in c["items"]:
        if x["done"]:
            parts.append(f"{x['label']}: {x['text']}")
        else:
            parts.append(f"{x['label']}: ranní test ({x['testName']}) ještě chybí. Ukáže, jestli se šlacha po zátěži uklidnila.")
    return " ".join(parts)
