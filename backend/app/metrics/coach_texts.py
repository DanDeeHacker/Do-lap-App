"""AI texts for the runner — daily summary, daily training commentary (engine
v3) and weekly summary. Phase 1 of the AI coach plan: facts → model → validator
→ stored; the runner-facing surfaces come in phase 3.

  facts (coach_facts.py, engine-computed)  →  hosted model (llm.py) with a
  versioned prompt (app/prompts/)  →  validator (coach_validate.py)  →
  CoachText row. A text that fails validation, or no model at all, falls back
  to the deterministic text built here from the same facts — the runner always
  gets a correct text, and the model can never change the engine's advice.

Generated only for runners who opted in (Runner.coach_consent), because the
facts go to an externally hosted model. Texts are regenerated when their facts
or prompt change: after the 07:00 sync (generate_all), after a check-in or a
manual sync (refresh_bg), and when the runner opts in.
"""
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from .. import llm, models
from . import coach_facts as F
from . import coach_validate as V
from . import engine as E

KINDS = ("daily_summary", "daily_commentary", "weekly_summary")
PROMPTS = {"daily_summary": "daily_summary.v1", "daily_commentary": "daily_commentary.v1",
           "weekly_summary": "weekly_summary.v1"}
RULES = "_rules.v1"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
MAX_TOKENS = {"daily_summary": 400, "daily_commentary": 500, "weekly_summary": 800}
ASK = {"daily_summary": "Napiš dnešní shrnutí.", "daily_commentary": "Napiš komentář k dnešnímu doporučení.",
       "weekly_summary": "Napiš shrnutí uplynulého týdne."}
RETRY_LLM_ERROR_AFTER = timedelta(minutes=30)
LLM_TIMEOUT_S = 180     # background work, and the free hosted tier can take a minute or more
RETENTION_DAYS = 400
PARALLEL_RUNNERS = 3

log = logging.getLogger("dosslap.coach")


# ---------------------------------------------------------------- prompts
def prompt(kind: str) -> tuple[str, str]:
    """(version, system prompt) — the version names the prompt file and the
    shared rules it includes, so a stored text says exactly what produced it."""
    name = PROMPTS[kind]
    body = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    rules = (PROMPT_DIR / f"{RULES}.md").read_text(encoding="utf-8")
    return f"{name}+{RULES}", body.replace("{rules}", rules.strip()).strip()


def facts_hash(facts: dict) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _user_message(kind: str, facts: dict) -> str:
    return f"Fakta (JSON):\n```json\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n```\n\n{ASK[kind]}"


_LABEL_PREFIX = re.compile(r"^\s*(shrnutí|komentář|denní shrnutí|týdenní shrnutí|odpověď)\s*:\s*", re.I)


def clean(text: str) -> str:
    t = text.strip().strip('"„“”').strip()
    t = _LABEL_PREFIX.sub("", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)          # no markdown bold in plain-text surfaces
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ---------------------------------------------------------------- deterministic texts
def _plural(n: int, one: str, few: str, many: str) -> str:
    return one if n == 1 else few if 2 <= n <= 4 else many


def _referral_sentence(f: dict) -> str | None:
    r = f.get("referral") or {}
    return f"Aplikace doporučuje fyzioterapeuta: {r.get('text', '').lower()}." if r.get("physio") else None


def fallback_daily_summary(f: dict) -> str:
    st = f["state"]
    out = [f"Dnes jste ve stavu {st['quadrant']} ({st['risk'].lower()}): {st['quadrantMeaning']}"]
    if f.get("signals"):
        s = f["signals"][0]
        out.append(f"Nejvíc ho ovlivňuje {s['name'].lower()} ({s['value']})" + (f" — {s['detail']}" if s.get("detail") else "") + ".")
    r = f.get("recovery") or {}
    rec = []
    if r.get("readinessPct") is not None:
        rec.append(f"připravenost {r['readinessPct']} %")
    if r.get("sleepH"):
        rec.append(f"spánek {r['sleepH']['now']} h (obvykle {r['sleepH']['usual']} h)")
    if rec:
        out.append(f"Regenerace: {', '.join(rec)}.")
    if f.get("today"):
        out.append(f"Dnešní doporučení: {f['today']['label'].lower()}.")
    if st.get("baselineConfidencePct", 100) < 60:
        out.append("Vaše norma se teprve buduje, závěry jsou zatím předběžné.")
    ref = _referral_sentence(f)
    if ref:
        out.append(ref)
    return " ".join(out)


def fallback_daily_commentary(f: dict) -> str:
    t = f["today"]
    out = []
    if t.get("override"):
        o = t["override"]
        out.append(f"Dnes: {t['label'].lower()}. {o['title']}. {o['text']}")
    else:
        out.append(f"Dnes: {t['label'].lower()}" + (f", {t['km']}" if t.get("km") else "")
                   + (f" ({t['durationMin']})" if t.get("durationMin") else "") + ".")
    if t.get("hrZones") and t.get("hr"):
        out.append(f"Tep držte v {t['hrZones']} ({t['hr']})" + (f", tempo zhruba {t['pace']}" if t.get("pace") else "") + ".")
    if t.get("terrain"):
        out.append(f"Terén: {t['terrain']}.")
    out += t.get("reasons", [])[:2]
    out += t.get("notes", [])[:1]
    ref = _referral_sentence(f)
    if ref and not re.search("fyzio", " ".join(out), re.I):
        out.append(ref)
    return " ".join(x.strip() for x in out if x)


def fallback_weekly_summary(f: dict) -> str:
    tr, cmp_ = f["training"], f["comparison"]
    n = tr["runs"]
    out = [f"Týden {f['weekFrom']}–{f['weekTo']}: {n} {_plural(n, 'běh', 'běhy', 'běhů')}, {tr['km']} km"
           + (f" ({'+' if cmp_['changeVsPreviousPct'] > 0 else '−' if cmp_['changeVsPreviousPct'] < 0 else ''}"
              f"{abs(cmp_['changeVsPreviousPct'])} % proti předchozímu týdnu)" if cmp_.get("changeVsPreviousPct") is not None else "")
           + f"; průměr posledních 4 týdnů je {cmp_['avg4WeeksKm']} km."]
    if tr.get("longestRun"):
        out.append(f"Nejdelší běh měl {tr['longestRun']['km']} km ({tr['longestRun']['date']}).")
    if tr.get("hardMinutesZ4"):
        out.append(f"V Z4+ jste strávili {tr['hardMinutesZ4']} min.")
    rec = f.get("recovery") or {}
    if rec.get("sleepH"):
        s = rec["sleepH"]
        out.append(f"Spánek v průměru {s['week']} h" + (f" (předchozí 4 týdny {s['previous4Weeks']} h)" if s.get("previous4Weeks") else "") + ".")
    if f.get("pain"):
        p = f["pain"]
        out.append(f"Bolest jste hlásili {p['reports']}×, nejvýš {p['max']}/10" + (f" ({p['site']})" if p.get("site") else "") + ".")
    st = f["stateNow"]
    out.append(f"Aktuální stav: {st['quadrant']} ({st['risk'].lower()}).")
    plan = f.get("thisWeekPlan") or {}
    if plan.get("mode"):
        out.append(f"Tento týden: {plan['mode']}"
                   + (f" s rozpočtem {plan['volumeBudgetKm']} km" if plan.get("volumeBudgetKm") else "") + ".")
    ref = _referral_sentence(f)
    if ref:
        out.append(ref)
    return " ".join(out)


FALLBACK = {"daily_summary": fallback_daily_summary, "daily_commentary": fallback_daily_commentary,
            "weekly_summary": fallback_weekly_summary}


# ---------------------------------------------------------------- generation
def plan(db, rid: str, a: dict) -> list[tuple[str, str, dict]]:
    """(kind, period, facts) for everything the runner should have right now."""
    today = E.today_date()
    daily = F.daily_facts(db, rid, a)
    items = [("daily_summary", today.isoformat(), daily)]
    if daily.get("today"):
        items.append(("daily_commentary", today.isoformat(), daily))
    ws, _ = F.week_bounds(today)
    items.append(("weekly_summary", ws.isoformat(), F.weekly_facts(db, rid, a, ws)))
    return items


def latest(db, rid: str, kind: str, period: str | None = None):
    q = db.query(models.CoachText).filter(models.CoachText.runner_id == rid, models.CoachText.kind == kind)
    if period:
        q = q.filter(models.CoachText.period == period)
    return q.order_by(models.CoachText.id.desc()).first()


def is_stale(row, facts: dict, kind: str) -> bool:
    if row is None or row.facts_hash != facts_hash(facts) or row.prompt_version != prompt(kind)[0]:
        return True
    if row.source == "fallback":
        codes = {i.get("code") for i in row.issues_json or []}
        if "llm_unavailable" in codes and llm.available():
            return True
        if "llm_error" in codes and datetime.fromisoformat(row.created_at) < datetime.now(E.LOCAL_TZ) - RETRY_LLM_ERROR_AFTER:
            return True
    return False


def generate_one(db, rid: str, kind: str, period: str, facts: dict):
    version, system = prompt(kind)
    fallback = FALLBACK[kind](facts)
    llm_text, issues, model = None, [], None
    t0 = time.monotonic()
    if not llm.available():
        issues = [{"code": "llm_unavailable"}]
    else:
        model = llm.NVIDIA_MODEL
        out = llm.chat(system, _user_message(kind, facts), temperature=0.3, max_tokens=MAX_TOKENS[kind],
                       timeout=LLM_TIMEOUT_S)
        if out is None:
            issues = [{"code": "llm_error"}]
        else:
            llm_text = clean(out)
            issues = V.validate(kind, llm_text, facts)["issues"]
    ok = llm_text is not None and not issues
    row = models.CoachText(
        runner_id=rid, kind=kind, period=period, facts_json=facts, facts_hash=facts_hash(facts),
        prompt_version=version, model=model, llm_text=llm_text, text=llm_text if ok else fallback,
        source="llm" if ok else "fallback", issues_json=issues, cards_json=[],
        latency_ms=round((time.monotonic() - t0) * 1000), created_at=E.now_iso(),
    )
    db.add(row)
    db.commit()
    return row


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(rid: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(rid, threading.Lock())


def refresh_runner(db, rid: str) -> dict:
    """Generate whatever is missing or stale for one consenting runner. A refresh
    already running for the runner makes this a no-op (no duplicate texts)."""
    runner = db.query(models.Runner).filter(models.Runner.id == rid).first()
    if runner is None or not runner.coach_consent:
        return {"skipped": "no_consent"}
    lk = _lock(rid)
    if not lk.acquire(blocking=False):
        return {"skipped": "busy"}
    try:
        a = E.get_or_refresh_assessment(db, rid)
        done = {}
        for kind, period, facts in plan(db, rid, a):
            if is_stale(latest(db, rid, kind, period), facts, kind):
                done[kind] = generate_one(db, rid, kind, period, facts).source
        return {"generated": done}
    finally:
        lk.release()


def refresh_bg(rid: str) -> None:
    """For BackgroundTasks after a check-in / sync / opt-in: own session, never raises."""
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        refresh_runner(db, rid)
    except Exception:  # noqa: BLE001 — a failed text must never break the request that triggered it
        log.exception("coach refresh failed for %s", rid)
    finally:
        db.close()


def generate_all(session_factory) -> dict:
    """Daily run after the 07:00 sync: every consenting runner, then old texts pruned."""
    db = session_factory()
    try:
        rids = [r.id for r in db.query(models.Runner).filter(models.Runner.coach_consent == True).all()]  # noqa: E712

        def one(rid):
            s = session_factory()
            try:
                return rid, refresh_runner(s, rid)
            except Exception:  # noqa: BLE001
                log.exception("coach generation failed for %s", rid)
                return rid, {"error": True}
            finally:
                s.close()
        # a hosted model takes a minute or more per text — a few runners at a time
        with ThreadPoolExecutor(max_workers=PARALLEL_RUNNERS) as ex:
            results = dict(ex.map(one, rids))
        cut = (datetime.now(E.LOCAL_TZ) - timedelta(days=RETENTION_DAYS)).isoformat()
        db.query(models.CoachText).filter(models.CoachText.created_at < cut).delete()
        db.commit()
        return {"runners": len(rids), "results": results}
    finally:
        db.close()


def forget(db, rid: str) -> int:
    """Consent withdrawn: the runner's generated texts go too."""
    n = db.query(models.CoachText).filter(models.CoachText.runner_id == rid).delete()
    db.commit()
    return n


def texts_for(db, rid: str) -> dict:
    """The current texts: today's daily ones and the latest weekly one."""
    today = E.today_date().isoformat()
    out = {}
    for kind in KINDS:
        row = latest(db, rid, kind, None if kind == "weekly_summary" else today)
        out[kind] = None if row is None else {
            "text": row.text, "source": row.source, "period": row.period, "createdAt": row.created_at,
            "promptVersion": row.prompt_version, "model": row.model if row.source == "llm" else None,
        }
    return out
