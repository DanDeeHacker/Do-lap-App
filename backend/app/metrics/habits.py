"""Owner decision 2026-10-14 — engagement that rewards the habits the app is about, never volume.
Gamified physical-activity interventions help a little and fade (Hedges g 0.42 short-term, 0.15
at ~14 weeks; Mazeas et al., 2022), and rewards for more running would work against an injury-
prevention app. So nothing here counts kilometres, pace or daily streaks.

Consistency weeks — every calendar week (Monday–Sunday) of the last WEEKS:
  kept    at least one training, the load score under THRESHOLD on every day of the week, and the
          Runner's must-have programme's sessions done while it runs (2 a week, 1 in its lighter
          weeks);
  paused  an illness or a limiting pain in a check-in, or no training at all: the week neither
          counts nor breaks the run of weeks, so nobody trains ill or hurt to keep it;
  missed  otherwise (a day over the threshold, the programme's sessions left out).
The run of weeks counts kept weeks back from the last completed one, skipping paused ones.

Milestones — habits, earned once and kept (runner.onboarding_json["milestones"]): 4 and 12 kept
weeks in a row, 24 sessions of the must-have programme, 20 diary notes, 30 nights from the watch,
a shoe transition completed, two pairs in rotation, a return-to-run plan finished. All counts are
working assumptions of the product team."""
from datetime import date, timedelta

from . import data as D
from . import engine as E
from . import runner_factors as RF

THRESHOLD = 25          # the load score's line ("nad prahem" on Zátěž)
WEEKS = 26
PROG_TEMPLATE, PROG_WEEKS, PROG_PER_WEEK = "durability", 26, 2
NEW_DAYS = 14           # a milestone earned in the last 14 days is announced once on Dnes


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _prog_need(started_on: str | None, monday: date, last_session: str | None, active: bool) -> int | None:
    """Sessions the must-have programme asks for in the week from `monday`, or None outside it."""
    try:
        st = date.fromisoformat(started_on)
    except (TypeError, ValueError):
        return None
    if monday < _monday(st) + timedelta(days=7):            # the week it started in is not a full week
        return None
    k = (monday - st).days // 7 + 1                        # the programme's week number
    if k > PROG_WEEKS:
        return None
    if not active and (not last_session or monday.isoformat() > last_session):
        return None                                         # stopped: its weeks after the last session don't ask
    return 1 if (k % 4 == 0 and 4 < k < 25) else PROG_PER_WEEK


def weeks(today: date, acts: list, load_by_day: dict, ill_days: set, programmes: list) -> list:
    """[{start, end, status, why, over, strength}] oldest first; the current week has status "now".
    `acts` = (date, is_run) of the trainings, `programmes` = [(started_on, [session dates], active)]."""
    if not acts and not load_by_day:
        return []
    first = min([d for d, _ in acts] + list(load_by_day)) if (acts or load_by_day) else today.isoformat()
    m0 = max(_monday(date.fromisoformat(first)), _monday(today) - timedelta(days=7 * WEEKS))
    out = []
    m = m0
    while m <= _monday(today):
        lo, hi = m.isoformat(), (m + timedelta(days=6)).isoformat()
        days = [(m + timedelta(days=k)).isoformat() for k in range(7)]
        trained = any(lo <= d <= hi for d, _ in acts)
        over = sum(1 for d in days if (load_by_day.get(d) or 0) >= THRESHOLD)
        need = done = 0
        for started, sessions, active in programmes:
            n = _prog_need(started, m, max(sessions) if sessions else None, active)
            if n:
                need += n
                done += sum(1 for s in sessions if lo <= s <= hi)
        trained = trained or done > 0
        strength = [min(done, need), need] if need else None
        ill = any(d in ill_days for d in days)
        known = any(d in load_by_day for d in days)
        if m == _monday(today):
            status, why = "now", None
        elif trained and known and over == 0 and (not need or done >= need):
            status, why = "kept", None
        elif ill:
            status, why = "paused", "nemoc nebo bolest"
        elif not trained:
            status, why = "paused", "bez tréninku"
        elif not known:
            status, why = "paused", "bez dat"
        else:
            status = "missed"
            why = f"zátěž nad prahem {over}×" if over else f"posilování {min(done, need)} z {need}"
        out.append({"start": lo, "end": hi, "status": status, "why": why, "over": over, "strength": strength})
        m += timedelta(days=7)
    return out


def chain(ws: list) -> int:
    """Kept weeks counted back from the last completed week; paused weeks are skipped."""
    n = 0
    for w in reversed(ws):
        if w["status"] in ("now", "paused"):
            continue
        if w["status"] != "kept":
            break
        n += 1
    return n


def chain_runs(ws: list) -> tuple[int, dict]:
    """(the longest run of kept weeks, {length: the end date of the week the run first reached it})."""
    best = cur = 0
    reached = {}
    for w in ws:
        if w["status"] in ("now", "paused"):
            continue
        cur = cur + 1 if w["status"] == "kept" else 0
        best = max(best, cur)
        reached.setdefault(cur, w["end"])
    return best, reached


def _nth_date(dates: list, n: int) -> str | None:
    ds = sorted(d for d in dates if d)
    return ds[n - 1] if len(ds) >= n else None


def _shoe_done(shoes: list, runs: list, today: date) -> tuple[str | None, str | None]:
    """(the date the first shoe transition ended, the shoe) — a shoe that needed one (RF.shoe_kind),
    its 6 weeks since the first run in it over, with at least 4 runs in it when runs are known by shoe."""
    shoes = [s for s in shoes if s.first_used]
    used = RF.shoe_runs(runs, shoes)
    best = (None, None)
    for s in shoes:
        first = RF._d(s.first_used)
        before = [b for b in shoes if b is not s and RF._d(b.first_used) < first
                  and not (b.retired_at and RF._d(b.retired_at) < first)]
        if not RF.shoe_kind(s, before):
            continue
        ds = sorted(used.get(s.id) or [])
        if used and len(ds) < 4:
            continue
        start = RF._d(ds[0]) if ds else first
        end = start + timedelta(days=RF.TRANSITION_DAYS)
        if end <= today and (best[0] is None or end.isoformat() < best[0]):
            best = (end.isoformat(), f"{s.brand} {s.model}".strip())
    return best


def _rotation_since(shoes: list, runs: list, today: date) -> str | None:
    """The first day two pairs were in rotation (each run in ≥ 2× in 28 days; by date of first use
    without runs known by shoe)."""
    shoes = [s for s in shoes if s.first_used]
    used = RF.shoe_runs(runs, shoes)
    if used:
        events = sorted((d, sid) for sid, ds in used.items() for d in ds)
        for d, _ in events:
            lo = (date.fromisoformat(d) - timedelta(days=RF.ROTATION_DAYS - 1)).isoformat()
            n = sum(1 for ds in used.values() if sum(1 for x in ds if lo <= x <= d) >= RF.ROTATION_RUNS)
            if n >= 2:
                return d
        return None
    starts = sorted(s.first_used[:10] for s in shoes if not (s.retired_at and RF._d(s.retired_at) <= today))
    return starts[1] if len(starts) >= 2 else None


MILESTONES = [
    # id, icon, title, text, need
    ("chain4", "calendar", "Měsíc v bezpečném pásmu", "4 týdny v řadě bez zátěže nad prahem a s posilováním podle programu.", 4),
    ("chain12", "trophy", "Čtvrt roku v bezpečném pásmu", "12 týdnů v řadě bez zátěže nad prahem a s posilováním podle programu.", 12),
    ("strength24", "dumbbell", "Runner's must-have: 12 týdnů", "24 tréninků programu odolnosti, tedy 12 týdnů po dvou.", 24),
    ("diary20", "notebook", "20 zápisů v deníku", "Jak se běh běžel, jak se cítily nohy a jestli něco bolelo. Ze zápisů aplikace pozná, co vám sedí.", 20),
    ("nights30", "moon", "30 nocí s hodinkami", "Z nocí aplikace zná vaši normu HRV, klidového tepu a spánku a z ní připravenost.", 30),
    ("shoes", "footprints", "Nové boty zaběhnuté", "6 týdnů přechodu na botu s nižším dropem, minimalistickou nebo karbonovou za vámi.", 1),
    ("rotation", "repeat", "Dva páry na střídání", "Dva páry, ve kterých běháte aspoň dvakrát za 4 týdny. Střídání bot souviselo s menším rizikem zranění.", 2),
    ("return", "heart", "Návrat k běhu dokončen", "Celý plán návratu k běhu od fyzioterapeuta je za vámi.", 1),
]


def build(db, rid: str, today: date | None = None, load_rows: list | None = None, own: bool = False) -> dict:
    """{weeks, chain, best, milestones} for the Trénink card; `own` stores newly earned milestones."""
    from .. import durability as DU
    from .. import models
    today = today or E.today_date()
    dd = D.of(db, rid)
    acts = [(a.started_at[:10], E.is_run(a)) for a in dd.activities if a.started_at and E.counts_for(a, "load")]
    load_by_day = {str(r["date"])[:10]: r.get("load") for r in (load_rows or []) if r.get("load") is not None}
    ill_days = {c.submitted_at[:10] for c in dd.checkins
                if (c.flags or {}).get("ill") or c.limping or c.limits_movement}
    progs = []
    for p in db.query(models.SelfProgram).filter(models.SelfProgram.runner_id == rid,
                                                 models.SelfProgram.template == PROG_TEMPLATE).all():
        hist = [h["date"] for h in ((p.state or {}).get("history") or []) if h.get("date")]
        progs.append((p.started_on, hist, bool(p.active)))
    ws = weeks(today, acts, load_by_day, ill_days, progs)
    best, reached = chain_runs(ws)
    now_chain = chain(ws)
    runs = [a for a in dd.activities if a.started_at and E.is_run(a) and E.counts_for(a, "load")]
    shoes = list(dd.shoes)
    sessions = [h for _, hs, _ in progs for h in hs]
    nights = [m.date[:10] for m in dd.daily if m.hrv_ms is not None or m.sleep_h is not None]
    notes = [f.submitted_at[:10] for f in dd.feedback if getattr(f, "submitted_at", None)]
    shoe_end, _shoe = _shoe_done(shoes, runs, today)
    rtr_done = [p for p in dd.rtr_plans if p.status == "completed"]
    rtr_date = None
    if rtr_done:
        logs = [s.logged_at[:10] for s in db.query(models.RtrSession).filter(
            models.RtrSession.plan_id.in_([p.id for p in rtr_done])).all() if s.logged_at]
        rtr_date = max(logs) if logs else (rtr_done[0].started_on or today.isoformat())[:10]
    have = {"chain4": now_chain, "chain12": now_chain, "strength24": len(sessions), "diary20": len(notes),
            "nights30": len(nights), "shoes": 1 if shoe_end else 0,
            "rotation": (RF.shoe_state(shoes, None, today, runs).get("rotation") or {}).get("n", 0) if shoes else 0,
            "return": 1 if rtr_done else 0}
    earned = {"chain4": reached.get(4), "chain12": reached.get(12), "strength24": _nth_date(sessions, 24),
              "diary20": _nth_date(notes, 20), "nights30": _nth_date(nights, 30), "shoes": shoe_end,
              "rotation": _rotation_since(shoes, runs, today) if shoes else None, "return": rtr_date}
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    meta = dict((runner.onboarding_json or {}) if runner else {})
    kept = dict(meta.get("milestones") or {})
    changed = False
    for k, v in earned.items():
        if v and k not in kept:
            kept[k] = v
            changed = True
    if own and changed and runner is not None:
        meta["milestones"] = kept
        runner.onboarding_json = meta
        db.commit()
    lo_new = (today - timedelta(days=NEW_DAYS)).isoformat()
    ms = []
    for mid, icon, title, text, need in MILESTONES:
        if mid in ("shoes", "rotation") and not shoes and mid not in kept:
            continue                                        # no shoes in the profile: not relevant
        if mid == "return" and not dd.rtr_plans and mid not in kept:
            continue                                        # only with a return-to-run plan
        e = kept.get(mid)
        ms.append({"id": mid, "icon": icon, "title": title, "text": text, "need": need,
                   "have": min(need, have.get(mid) or 0) if not e else need, "earned": e,
                   "recent": bool(e and e >= lo_new)})
    return {"weeks": ws, "chain": now_chain, "best": best, "threshold": THRESHOLD, "milestones": ms}
