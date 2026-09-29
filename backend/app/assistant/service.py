"""The Physio AI Assistant pipeline (implementation plan, architecture):

  gate (fixed safety replies) → selector (intent, data slices, topics) →
  facts (engine output) + knowledge search (cards → summaries → full texts,
  app guide) → model (prompt assistant.v2) → validator → answer, or one retry,
  or a deterministic answer built from the same facts and cards.

The engine stays the source of truth: the model only explains and plans inside
today's recommendation, and the validator rejects anything that contradicts it.
"""
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .. import llm, models
from ..metrics import engine as E
from . import facts as FA
from . import gate as GATE
from . import knowledge as K
from . import selector as SEL
from . import validate as VAL

log = logging.getLogger("dosslap.assistant")
PROMPT_VERSION = "assistant.v2"
PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8")
NAME = "Physio AI Assistant"
VISIBLE_DAYS = 7          # the runner sees a week of conversation (product decision 2026-09-28)
KEEP_DAYS = 365           # kept for answer-quality review, deletable by the runner any time
HISTORY_TURNS = 6
LLM_TIMEOUT_S = 30
# circuit breaker: after a failure the assistant answers from the fallback for a
# while instead of making every runner wait for a timeout
_LLM_PAUSE = {"until": 0.0}
PAUSE_MISSING_S, PAUSE_SLOW_S = 3600, 300


def _pause_for(err: dict) -> float:
    """How long to answer from the fallback after a failed call: a missing model or
    key for an hour, a rate limit for as long as the host asks (free tiers count
    tokens per minute), a timeout or server error for five minutes."""
    status = err.get("status")
    if status in (401, 403, 404, 410):
        return PAUSE_MISSING_S
    if status == 429:
        m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", err.get("body") or "")
        wait = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else float(err.get("retryAfter") or 30)
        return min(120.0, wait + 1)
    return PAUSE_SLOW_S
PASSAGE_CHARS = 800                                # keeps the prompt short enough for free-tier hosts
DISCLAIMER = "Odpověď napsala AI z vašich dat a z odborné literatury. Může se mýlit a nenahrazuje fyzioterapeuta."


def daily_limit() -> int:
    try:
        return int(os.environ.get("ASSISTANT_DAILY_LIMIT", "20"))
    except ValueError:
        return 20


def mode() -> str:
    """off | demo (demo and tutorial accounts only) | on. Rollout switch and kill switch."""
    m = os.environ.get("DOSSLAP_ASSISTANT", "demo").strip().lower()
    return m if m in ("off", "demo", "on") else "demo"


def is_demo(db, rid: str, user=None) -> bool:
    from ..tutorial_demo import TUTORIAL_RID
    if rid == TUTORIAL_RID:
        return True
    emails = [user.email] if user is not None and getattr(user, "email", None) else [
        u.email for u in db.query(models.User).filter(models.User.runner_id == rid).all()]
    return any((e or "").lower().endswith("@demo.cz") for e in emails)


def access(db, runner, user=None) -> dict:
    """{enabled, reason, needsConsent}. Demo data is synthetic, so demo accounts need
    no AI consent; real runners do (their facts go to the hosted model)."""
    m = mode()
    demo = is_demo(db, runner.id, user)
    if m == "off":
        return {"enabled": False, "reason": "off", "needsConsent": False}
    if m == "demo" and not demo:
        return {"enabled": False, "reason": "rollout", "needsConsent": False}
    if not demo and not runner.coach_consent:
        return {"enabled": False, "reason": "consent", "needsConsent": True}
    return {"enabled": True, "reason": None, "needsConsent": False}


def _now() -> str:
    return datetime.now(E.LOCAL_TZ).isoformat(timespec="seconds")


def _used_today(db, rid: str) -> int:
    start = datetime.combine(E.today_date(), datetime.min.time(), E.LOCAL_TZ).isoformat(timespec="seconds")
    return db.query(models.AssistantMessage).filter(models.AssistantMessage.runner_id == rid,
                                                     models.AssistantMessage.role == "user",
                                                     models.AssistantMessage.created_at >= start).count()


def purge(db, rid: str | None = None) -> int:
    cut = (datetime.now(E.LOCAL_TZ) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    q = db.query(models.AssistantMessage).filter(models.AssistantMessage.created_at < cut)
    if rid:
        q = q.filter(models.AssistantMessage.runner_id == rid)
    n = q.delete(synchronize_session=False)
    db.commit()
    return n


def _visible_cut() -> str:
    return (datetime.now(E.LOCAL_TZ) - timedelta(days=VISIBLE_DAYS)).isoformat(timespec="seconds")


def history(db, rid: str) -> list[dict]:
    rows = (db.query(models.AssistantMessage)
            .filter(models.AssistantMessage.runner_id == rid, models.AssistantMessage.created_at >= _visible_cut())
            .order_by(models.AssistantMessage.id.asc()).all())
    return [public(r) for r in rows]


def public(r: models.AssistantMessage) -> dict:
    return {"id": r.id, "threadId": r.thread_id, "role": r.role, "text": r.text, "sources": r.sources_json or [],
            "links": r.links_json or [], "source": r.source, "createdAt": r.created_at, "feedback": r.feedback,
            "context": r.context_json}


def delete_history(db, rid: str) -> int:
    n = db.query(models.AssistantMessage).filter(models.AssistantMessage.runner_id == rid).delete(synchronize_session=False)
    db.commit()
    return n


# ------------------------------------------------------------------ sources
def _number_sources(kb: dict) -> list[dict]:
    out = []
    for c in kb["cards"]:
        refs = c.get("sourcesMeta") or []
        text = f"{c['title']}. {c['claim']} Omezení: {c['limits']} Síla důkazů: {c['strength']}."
        out.append({"n": len(out) + 1, "kind": "card", "id": c["id"], "title": c["title"], "claim": c["claim"],
                    "limits": c["limits"], "strength": c["strength"], "status": c.get("status", "draft"),
                    "app": c.get("app"), "refs": [{"cite": r["cite"], "apa": r["apa"], "doi": r.get("doi")} for r in refs],
                    "cite": "; ".join(r["cite"] for r in refs), "text": text})
    for p in kb["passages"]:
        body = p["text"] if len(p["text"]) <= PASSAGE_CHARS else p["text"][:PASSAGE_CHARS].rsplit(" ", 1)[0] + " …"
        out.append({"n": len(out) + 1, "kind": p["kind"], "id": p["sid"], "title": p.get("cite"), "cite": p.get("cite"),
                    "section": p.get("section"), "strength": None,
                    "refs": [{"cite": p.get("cite"), "apa": p.get("apa"), "doi": p.get("doi")}], "text": body})
    return out


def _public_sources(sources: list[dict], cited: set) -> list[dict]:
    keep = [s for s in sources if s["n"] in cited]
    return [{k: v for k, v in s.items() if k != "text"} for s in keep]


def _compact(x):
    """Facts without empty fields: fewer tokens, nothing lost."""
    if isinstance(x, dict):
        out = {k: _compact(v) for k, v in x.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(x, list):
        return [_compact(v) for v in x if v not in (None, "", [], {})]
    return x


def _user_message(question: str, facts: dict, sources: list[dict], guide: list[dict]) -> str:
    src = "\n".join(
        f"[{s['n']}] ({'důkazní karta' if s['kind'] == 'card' else 'shrnutí studie' if s['kind'] == 'summary' else 'pasáž článku'}"
        f"{', síla důkazů: ' + s['strength'] if s.get('strength') else ''}; {s.get('cite') or ''}) {s['text']}"
        for s in sources) or "(žádné zdroje k této otázce)"
    gd = "\n".join(f"- {g['title']}: {g['text']}" for g in guide) or "(není potřeba)"
    return (f"OTÁZKA BĚŽCE:\n{question}\n\nFAKTA (JSON):\n{json.dumps(_compact(facts), ensure_ascii=False, separators=(',', ':'))}\n\n"
            f"ZDROJE:\n{src}\n\nPRŮVODCE APLIKACÍ:\n{gd}")


# ------------------------------------------------------------------ fallback
def fallback_answer(sel: dict, facts: dict, sources: list[dict], guide: list[dict]) -> str:
    """A short, always-correct answer from the same facts and the top card."""
    parts = []
    if sel.get("wantGuide") and guide:
        parts.append(guide[0]["text"])
    if sel.get("intents") == ["app"]:
        return " ".join(parts) or "Tohle v průvodci aplikací nenacházím. Zkuste otázku položit jinak."
    today = facts.get("today") or {}
    if today and not (sel.get("wantGuide") and len(sel.get("intents") or []) == 1):
        line = f"Dnes aplikace doporučuje: {today.get('label')}"
        if today.get("km"):
            line += f", {today['km']}"
        parts.append(line + ".")
        if today.get("override"):
            parts.append(today["override"]["text"])
        elif today.get("reasons"):
            parts.append(today["reasons"][0])
        typ = (facts.get("sessionTypes") or {}).get(sel.get("askedType") or "")
        if typ and sel.get("askedType") != today.get("type"):
            if typ.get("whyNot"):
                parts.append(f"{typ['label']} dnes nedoporučujeme: {typ['whyNot'].rstrip('.')}.")
            elif typ.get("allowed"):
                parts.append(f"{typ['label']} dnes jde" + (f", {typ['km']}." if typ.get("km") else "."))
    ref = facts.get("referral") or {}
    if ref.get("physio"):
        parts.append(f"Aplikace doporučuje fyzioterapeuta: {ref.get('text')}.")
    rd = facts.get("readiness") or {}
    if rd.get("readinessPct") is not None and "readiness" in (sel.get("intents") or []):
        low = ", ".join(rd.get("whatLowersReadiness") or {})
        parts.append(f"Ve vašich datech: připravenost {rd['readinessPct']} %" + (f", snižuje ji {low}." if low else "."))
    card = next((s for s in sources if s["kind"] == "card"), None)
    if card:
        first = card["claim"].split(". ")[0].rstrip(".")
        parts.append(f"Co říká výzkum: {first} [{card['n']}].")
    if "pain" in (sel.get("intents") or []) and not ref.get("physio"):
        parts.append("Pokud bolest při běhu sílí, mění váš krok nebo do druhého dne neodezní, běh vynechte "
                     "a poraďte se s fyzioterapeutem.")
    if not parts:
        parts.append("K tomu teď nemám dost dat ani ověřený zdroj. Zkuste otázku upřesnit, nebo se podívejte do záložky Trénink.")
    return " ".join(parts)


# ------------------------------------------------------------------ the pipeline
def _store(db, rid, thread, role, text, **kw) -> models.AssistantMessage:
    row = models.AssistantMessage(runner_id=rid, thread_id=thread, role=role, text=text, created_at=_now(), **kw)
    db.add(row)
    return row


def ask(db, runner, question: str, context: dict | None = None, thread_id: str | None = None, user=None,
        dry_run: bool = False, model_override: str | None = None) -> dict:
    """The whole pipeline. `dry_run` (ops model comparison on the demo runner)
    stores nothing, ignores the daily limit and the circuit breaker, and returns
    the raw model text and the validator's issues as well."""
    t0 = time.time()
    rid = runner.id
    question = (question or "").strip()[:800]
    thread = thread_id or uuid.uuid4().hex[:16]
    if not question:
        return {"error": "empty"}
    if not dry_run:
        purge(db, rid)

    def fixed(text, source="gate", issues=None):
        if dry_run:
            return {"text": text, "source": source, "issues": issues}
        _store(db, rid, thread, "user", question, context_json=context)
        row = _store(db, rid, thread, "assistant", text, source=source, issues_json=issues, context_json=context,
                     prompt_version=PROMPT_VERSION, latency_ms=int((time.time() - t0) * 1000))
        db.commit()
        return {**public(row), "disclaimer": DISCLAIMER}

    if not dry_run and _used_today(db, rid) >= daily_limit():
        return {**fixed(GATE.LIMIT_REPLY, issues=[{"code": "daily_limit"}]), "limited": True}
    g = GATE.check(question)
    if g:
        return fixed(g["reply"], issues=[{"code": f"gate_{g['kind']}"}])
    a = E.get_or_refresh_assessment(db, rid)
    eb = GATE.engine_block(a)
    if eb:
        return fixed(eb["reply"], issues=[{"code": "gate_engine_red_flag"}])

    sel = SEL.classify(question, context)
    active = [s["id"] for s in a.get("signals") or [] if (s.get("pts") or 0) > 0]
    facts = FA.build(db, rid, a, sel)
    kb = K.search(db, question, topics=sel["topics"], signals=sel["signals"], active=active,
                  want_guide=sel["wantGuide"] or not sel["intents"], n_passages=2)
    if sel["wantGuide"] and len(sel["intents"]) == 1:
        kb["passages"] = []                         # an app question needs the guide, not papers
    sources = _number_sources(kb)
    guide = kb["guide"]

    text, llm_text, issues, source, model = None, None, [], "fallback", None
    paused = time.time() < _LLM_PAUSE["until"] and not dry_run
    if paused and llm.assistant_available():
        issues.append({"code": "llm_paused"})
    if llm.assistant_available() and not paused:
        msgs = [{"role": "system", "content": PROMPT}]
        prev = (db.query(models.AssistantMessage)
                .filter(models.AssistantMessage.runner_id == rid, models.AssistantMessage.thread_id == thread,
                        models.AssistantMessage.created_at >= _visible_cut())
                .order_by(models.AssistantMessage.id.desc()).limit(HISTORY_TURNS).all())
        for r in reversed(prev):
            msgs.append({"role": r.role, "content": r.text})
        msgs.append({"role": "user", "content": _user_message(question, facts, sources, guide)})
        model = model_override or llm.ASSISTANT_MODEL
        for attempt in range(2):
            out = llm.chat_messages(msgs, temperature=0.2, max_tokens=600, timeout=LLM_TIMEOUT_S, model=model,
                                    base_url=llm.ASSISTANT_BASE_URL, api_key=llm.ASSISTANT_API_KEY)
            if not out:
                err = llm.LAST_ERROR.get("chat") or {}
                issues.append({"code": "llm_error", "detail": err})
                if not dry_run:
                    _LLM_PAUSE["until"] = time.time() + _pause_for(err)
                break
            out = VAL.tidy(out)
            llm_text = out
            clean, _ = VAL.strip_links(out)
            v = VAL.validate(clean, facts, sources)
            if v["ok"]:
                text, source = out, "llm"
                break
            fixed = VAL.repair(out, v["issues"])
            if fixed:
                fclean, _ = VAL.strip_links(fixed)
                if VAL.validate(fclean, facts, sources)["ok"]:
                    text, source = fixed, "llm"
                    issues = [{"code": "repaired", "detail": [i["code"] for i in v["issues"]]}]
                    break
            issues = v["issues"]
            msgs += [{"role": "assistant", "content": out},
                     {"role": "user", "content": "Odpověď neprošla kontrolou: "
                      + "; ".join(f"{i['code']}{': ' + str(i['detail']) if i.get('detail') else ''}" for i in issues)
                      + ". Napiš ji znovu podle pravidel, jen s čísly z FAKT a ZDROJŮ."}]
    else:
        issues.append({"code": "no_llm"})
    if text is None:
        text = fallback_answer(sel, facts, sources, guide)
        links = []
    clean, links = VAL.strip_links(text)
    clean = E.cz_text(clean)          # Czech decimal comma, whatever the model copied from the facts
    if source == "fallback":
        app_links = {"today": "Dnes", "training": "Trénink", "post": "Deník", "mechanics": "Pohyb", "load": "Zátěž",
                     "messages": "Péče", "data": "Data"}
        first = (guide[0]["app"] if sel["wantGuide"] and guide else
                 next((s.get("app") for s in sources if s["kind"] == "card" and s.get("app")), None))
        links = [app_links[first]] if first in app_links else []
    cited = {int(x) for x in VAL._CITE.findall(clean)}
    if dry_run:
        return {"text": clean, "source": source, "issues": issues, "llmText": llm_text, "model": model,
                "latencyMs": int((time.time() - t0) * 1000), "sources": _public_sources(sources, cited),
                "links": links, "searchMode": kb.get("mode")}
    _store(db, rid, thread, "user", question, context_json=context, intent_json=sel)
    row = _store(db, rid, thread, "assistant", clean, context_json=context, intent_json=sel,
                 sources_json=_public_sources(sources, cited), facts_json=facts, links_json=links, source=source,
                 issues_json=issues or None, llm_text=llm_text, prompt_version=PROMPT_VERSION, model=model,
                 latency_ms=int((time.time() - t0) * 1000))
    db.commit()
    return {**public(row), "disclaimer": DISCLAIMER, "searchMode": kb.get("mode")}


def suggestions(a: dict) -> list[str]:
    """Up to three questions that fit today's state (rule-based)."""
    out = []
    g = a.get("guidance") or {}
    types = g.get("types") or {}
    scr = a.get("screening") or {}
    rs = g.get("readinessScore")
    if scr.get("bonePain") or scr.get("boneStress"):
        out.append("Co mám dělat s bolestí holeně nebo chodidla?")
    if isinstance(rs, (int, float)) and rs < 65:
        out.append("Proč mám dnes nižší připravenost?")
    if types.get("kvalitní") and not types["kvalitní"].get("allowed"):
        out.append("Proč dnes nemůžu dát intervaly?")
    if a.get("quadrant") == "silent":
        out.append("Co znamená tichý drift?")
    elif a.get("quadrant") in ("overreaching", "critical"):
        out.append("Proč je moje zátěž zvýšená?")
    if g.get("heat"):
        out.append("Jak dnes běhat v horku?")
    if (g.get("strength") or {}).get("lastAge") in (None,) or ((g.get("strength") or {}).get("lastAge") or 0) >= 21:
        out.append("Jak zařadit posilování do týdne?")
    out += ["Co mám dnes běžet a proč?", "Jak vypadá můj tréninkový týden?", "Kde v aplikaci najdu svou kapacitu?"]
    return list(dict.fromkeys(out))[:3]
