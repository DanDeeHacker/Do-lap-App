"""Clinician-facing AI brief — deterministic facts, computed the same way
regardless of whether an LLM is configured (port of core.js's `ai.brief` +
`DIRECTIONS`). When llm.available() (see ../llm.py, needs NVIDIA_API_KEY),
those facts are handed to a real model to narrate as natural prose; without
a key, the structured sections are returned exactly as before. The LLM
narrates already-true facts — it's never the sole source of one, so it has
nothing to hallucinate that would change what the clinician acts on.
"""
import re

from sqlalchemy.orm import Session as DBSession

from .. import models
from .. import llm
from . import engine

AI_INTENTS = [
    ("summary", "Shrň posledních 28 dní"),
    ("change", "Co se změnilo od minulé kontroly"),
    ("where", "Kde může být problém"),
    ("program", "Co upravit v programu"),
    ("missing", "Jaká data chybí"),
]
AI_INTENT_LABEL = dict(AI_INTENTS)


def _g(ctx: dict, *path, default=None):
    cur = ctx
    for k in path:
        if not isinstance(cur, dict) or cur.get(k) is None:
            return default
        cur = cur[k]
    return cur


def _match_marked(ctx):
    return _g(ctx, "_topPoint", "n", default=0) >= 2


def _name_marked(ctx):
    return f"Lokalizovaná tkáň: {ctx['_topPoint']['label']}"


def _because_marked(ctx):
    tp = ctx["_topPoint"]
    type_txt = f", charakter {tp['type']}" if tp.get("type") else ""
    return f"pacient označil toto místo {tp['n']}× za 28 dní, nejvyšší intenzita {tp['max']}/10{type_txt}"


def _match_achilles(ctx):
    return _g(ctx, "tavr", "z", default=0) >= 1.2 or bool(re.search("achill", ctx.get("_injury") or "", re.I))


def _because_achilles(ctx):
    return f"vertikální poměr roste (z {engine.sgn(_g(ctx, 'tavr', 'z', default=0))}) při nezměněném tempu — ubývá elastický odraz"


def _match_tibial(ctx):
    return _g(ctx, "bal", "excursion", default=0) >= 0.9


def _because_tibial(ctx):
    return f"symetrie se posunula o {_g(ctx, 'bal', 'excursion')} p.b. — {_g(ctx, 'bal', 'direction')}"


def _match_lateral(ctx):
    spike = _g(ctx, "loadDetail", "descentSpike")
    return spike is not None and spike > 1.45


def _because_lateral(ctx):
    return f"sbíhání skočilo na ×{_g(ctx, 'loadDetail', 'descentSpike')} proti obvyklému týdnu"


def _match_plantar(ctx):
    site_text = ctx.get("_injury") or ctx.get("_site") or ""
    return _g(ctx, "gct", "z", default=0) >= 1.2 and bool(re.search("chodid|plantár", site_text, re.I))


def _because_plantar(ctx):
    return f"kontakt se zemí se prodloužil (z {engine.sgn(_g(ctx, 'gct', 'z', default=0))}) — mění se odrazová fáze"


def _match_systemic(ctx):
    return _g(ctx, "rcv", "hrv", "z", default=0) <= -1 or _g(ctx, "rcv", "rhr", "z", default=0) >= 1.2


def _because_systemic(ctx):
    return (f"HRV {_g(ctx, 'rcv', 'hrv', 'now')} ms proti baseline {_g(ctx, 'rcv', 'hrv', 'base')} ms, "
            f"klidový tep {_g(ctx, 'rcv', 'rhr', 'now')}")


def _match_durability(ctx):
    return _g(ctx, "dec", "trend", default=0) > 0.35


def _because_durability(ctx):
    return f"rozpad techniky uvnitř běhu má trend {engine.sgn(_g(ctx, 'dec', 'trend'))} na běh"


DIRECTIONS = [
    {"id": "marked", "match": _match_marked, "name": _name_marked, "because": _because_marked,
     "confirm": "Reprodukovatelnost palpací a zátěžovým testem cílícím na tuto strukturu.",
     "refute": "Nebolestivá palpace i zátěž — pak jde spíš o přenesenou bolest odjinud."},
    {"id": "achilles", "match": _match_achilles, "name": "Tolerance zátěže lýtkového komplexu a Achillovy šlachy",
     "because": _because_achilles,
     "confirm": "Bolest při jednonožných výponech, ranní ztuhlost prvních kroků, palpační citlivost 2–6 cm nad úponem.",
     "refute": "Plná bezbolestná zátěž při 25 jednonožných výponech a žádná ranní ztuhlost."},
    {"id": "tibial", "match": _match_tibial, "name": "Kostní stres tibie na straně s delším kontaktem",
     "because": _because_tibial,
     "confirm": "Ohraničená bolestivost na hraně tibie, bolest při hopsání na jedné noze, noční bolest.",
     "refute": "Difuzní bolest svalového charakteru, která se během rozběhání ztrácí."},
    {"id": "lateral", "match": _match_lateral, "name": "Laterální koleno a excentrická kapacita kvadricepsu",
     "because": _because_lateral,
     "confirm": "Bolest se objevuje až v klesání a při chůzi ze schodů, ne do kopce.",
     "refute": "Symptomy stejné do kopce i z kopce."},
    {"id": "plantar", "match": _match_plantar, "name": "Plantární fascie a tolerance klenby",
     "because": _because_plantar,
     "confirm": "Bolest prvních kroků po ránu a po delším sezení, palpace mediálního úponu.",
     "refute": "Bolest bez ranního maxima, zhoršující se v průběhu dne bez zátěže."},
    {"id": "systemic", "match": _match_systemic, "name": "Systémová únava, ne lokální tkáň",
     "because": _because_systemic,
     "confirm": "Únava napříč dny, zhoršený spánek, žádné ohraničené bolestivé místo.",
     "refute": "Jasně lokalizovaný bod bolesti reprodukovatelný palpací nebo zátěží."},
    {"id": "durability", "match": _match_durability, "name": "Klesající odolnost proti únavě, ne akutní léze",
     "because": _because_durability,
     "confirm": "Symptomy až v druhé polovině dlouhých běhů, krátké běhy bezbolestné.",
     "refute": "Bolest hned od začátku bez ohledu na délku."},
]


def _grouped_top_point(pts: list[dict]):
    if not pts:
        return None
    grp: dict[str, list[dict]] = {}
    for p in pts:
        suffix = " vpravo" if p.get("side") == "P" else (" vlevo" if p.get("side") == "L" else "")
        key = f"{p.get('region')}{suffix}"
        grp.setdefault(key, []).append(p)
    label, group = max(grp.items(), key=lambda kv: len(kv[1]))
    return {"label": label, "n": len(group), "max": max(p.get("severity", 0) for p in group), "type": group[0].get("type")}


def _compute(db: DBSession, rid: str, intent: str = "summary") -> dict:
    """The deterministic half of brief() — same numerically-exact sections
    regardless of whether an LLM is configured. Split out so chat_reply()
    can pull the full fact set (intent="all") without also triggering
    brief()'s own narrative call, which would waste a second LLM round
    trip narrating facts that are about to be handed to the chat model
    anyway."""
    row = db.query(models.Assessment).filter(models.Assessment.runner_id == rid).first()
    a = engine.assessment_row_to_dict(row) if row else engine.assess(db, rid)
    r = db.query(models.Runner).filter(models.Runner.id == rid).first()
    ci = (
        db.query(models.Checkin).filter(models.Checkin.runner_id == rid)
        .order_by(models.Checkin.submitted_at.desc()).first()
    )
    cutoff = engine.day_ago(28)
    fb_rows = (
        db.query(models.ActivityFeedback)
        .filter(models.ActivityFeedback.runner_id == rid, models.ActivityFeedback.submitted_at > cutoff)
        .all()
    )
    all_pts: list[dict] = []
    for f in fb_rows:
        all_pts.extend(f.pain_points or [])
    top_point = _grouped_top_point(all_pts)

    ctx = dict(a)
    ctx["_injury"] = r.prior_injury if r else None
    ctx["_site"] = ci.pain_site if ci else None
    ctx["_topPoint"] = top_point

    L = a.get("loadDetail") or {}
    fb = a.get("fb")
    rcv = a.get("rcv")
    S = []

    def grade_tag(g):
        return f"[{g}]"

    if intent in ("summary", "change", "all"):
        items = []
        ratio_txt = f" (poměr ×{L.get('ratio')})" if L.get("valid") else " — chronická zátěž je zatím nízká, poměr se nepočítá"
        items.append(f"Tréninková zátěž za 7 dní {L.get('acute')} proti chronickému průměru {L.get('chronic')} j.z./týden (vč. jiného sportu){ratio_txt}.")
        tv = a.get("tavr")
        if tv:
            items.append(f"Vertikální poměr {tv['baseMean']} % → {tv['recMean']} % ve srovnatelných podmínkách, "
                          f"z {engine.sgn(tv['z'])} {grade_tag('B')}.")
        bal = a.get("bal")
        if bal:
            items.append(f"Symetrie kontaktu {bal['baseline']} % → {bal['now']} % vlevo, posun {bal['excursion']} p.b. {grade_tag('B')}.")
        gc = a.get("gct")
        if gc:
            items.append(f"Kontakt se zemí {gc['baseMean']} → {gc['recMean']} ms po normalizaci na kadenci {grade_tag('B')}.")
        if rcv:
            edited_txt = f" — {rcv['edited']} dní ručně opraveno pacientem" if rcv.get("edited") else ""
            items.append(f"Z hodinek: HRV {rcv['hrv']['now']} ms (baseline {rcv['hrv']['base']}), "
                          f"klidový tep {rcv['rhr']['now']}, spánek {rcv['sleep']['now']} h{edited_txt}.")
        if fb:
            niggle_txt = f", {fb['niggleCount']}× hlášeno bolestivé místo" if fb.get("niggleCount") else ", bez hlášené bolesti"
            items.append(f"Hodnocení po tréninku: {fb['n']} z posledních běhů ohodnoceno, "
                          f"průměrný pocit {fb['feelingMean']}/5{niggle_txt}.")
        if all_pts and top_point:
            type_txt = f", charakter {top_point['type']}" if top_point.get("type") else ""
            items.append(f"Na siluetě označil pacient {len(all_pts)} bodů, nejčastěji {top_point['label']} "
                          f"({top_point['n']}×, nejvyšší {top_point['max']}/10{type_txt}) [A].")
        S.append({"h": "Co data ukazují", "items": items})

    if intent in ("change", "all"):
        ch = []
        tv = a.get("tavr")
        if tv and tv.get("detail"):
            d = tv["detail"][0]
            ch.append(f"Největší posun na profilu „{d['label']}“: {d['base']} → {d['now']} "
                      f"({d['nNow']} běhů proti {d['nBase']} v baseline).")
        dec = a.get("dec")
        if dec:
            ch.append(f"Rozpad techniky uvnitř běhu: poslední hodnota {engine.sgn(dec['latest'])} %, "
                      f"trend {engine.sgn(dec['trend'])} na běh přes {dec['n']} srovnatelných dlouhých běhů.")
        if fb and fb.get("feelingTrend"):
            ch.append(f"Subjektivní pocit z běhu má trend {engine.sgn(fb['feelingTrend'])} za 21 dní.")
        if not ch:
            ch.append("Žádná metrika se od minulé kontroly nepohnula nad prahovou hodnotu.")
        S.append({"h": "Změny", "items": ch})

    if intent in ("summary", "where", "all"):
        dirs = []
        for d in DIRECTIONS:
            try:
                if d["match"](ctx):
                    dirs.append(d)
            except Exception:
                continue
        if dirs:
            items = []
            for d in dirs:
                name = d["name"](ctx) if callable(d["name"]) else d["name"]
                items.append(f"<b>{name}</b><br><span class=\"muted\">Proč: {d['because'](ctx)}."
                             f"<br>Podpořilo by: {d['confirm']}<br>Vyvrátilo by: {d['refute']}</span>")
            S.append({"h": "Směry ke zvážení — seřazeno podle síly dat, ne podle pravděpodobnosti", "items": items})
        else:
            S.append({"h": "Směry ke zvážení",
                       "items": ["Žádný vzorec v datech nesměřuje k jedné tkáni. Pokud pacient hlásí obtíže, "
                                 "vyšetření začíná u anamnézy, ne u těchto metrik."]})

    if intent in ("program", "all"):
        prog = (
            db.query(models.Program)
            .filter(models.Program.runner_id == rid, models.Program.active.is_(True))
            .first()
        )
        items = []
        if not prog:
            items.append("Pacient zatím nemá aktivní program.")
        else:
            ex = db.query(models.Exercise).filter(models.Exercise.program_id == prog.id).all()
            ratios = [(e.done_count or 0) / e.target_count for e in ex if e.target_count]
            adh = round(engine.mean(ratios) * 100) if ratios else 0
            low_txt = " — nízká, změna dávkování má smysl řešit až po tomhle" if adh < 50 else ""
            items.append(f"Adherence programu „{prog.name}“ je {adh} %{low_txt}.")
            if ex:
                worst = min(ex, key=lambda e: ((e.done_count or 0) / e.target_count) if e.target_count else 1)
                if worst.target_count and (worst.done_count or 0) / worst.target_count < 0.4:
                    items.append(f"Nejhůř plněné je „{worst.name}“ ({worst.done_count}/{worst.target_count}). "
                                 "Stojí za zvážení, jestli je dávka reálná nebo jestli cvik provokuje.")
        dec = a.get("dec")
        if dec and dec.get("trend", 0) > 0.35:
            items.append("Rozpad techniky v druhé půli běhu obvykle reaguje spíš na sílu a objem než na mobilitu "
                         "— posun váhy k excentrice a jednonožné stabilitě.")
        if (L.get("monotony") or 0) > 2.4:
            items.append(f"Monotónnost {L['monotony']}: zařazení jednoho úplného volna týdně sníží zátěžovou "
                         "osu víc než jakákoli úprava cviků.")
        if L.get("descentSpike") and L["descentSpike"] > 1.45:
            items.append("Při zvýšeném sbíhání dává smysl dočasně omezit klesání dřív než sáhnout na celkový objem.")
        if _g(a, "confidence", "value", default=1) < 0.6:
            items.append("Mechanické signály jsou umlčené kvůli nízké spolehlivosti baseline — úpravy programu "
                         "stavte na klinickém nálezu, ne na těchto číslech.")
        S.append({"h": "K programu", "items": items})

    if intent in ("missing", "summary", "all"):
        miss = []
        conf = a.get("confidence") or {}
        if (conf.get("value") or 0) < 0.6:
            miss.append(f"Spolehlivost baseline {round((conf.get('value') or 0) * 100)} % — "
                       f"{conf.get('sessions')} shodných tréninků za 28 dní, {conf.get('days')} dní historie. "
                       "Mechanické signály se nezobrazují.")
        if not fb or fb.get("n", 0) < 4:
            miss.append("Málo hodnocení po trénincích. Bez nich chybí vazba symptomu na konkrétní typ zátěže "
                       "— nejužitečnější věc, kterou pacient může doplnit.")
        if not rcv:
            miss.append("Chybí souvislá data o spánku a HRV z hodinek za posledních 35 dní.")
        has_any = db.query(models.Activity.id).filter(models.Activity.runner_id == rid).first()
        has_trail = db.query(models.Activity.id).filter(
            models.Activity.runner_id == rid, models.Activity.surface == "trail"
        ).first()
        if has_any and not has_trail:
            miss.append("Žádné běhy v terénu — baseline pro trailový profil neexistuje, po prvním trailu budou "
                       "hodnoty nesrovnatelné.")
        if not miss:
            miss.append("Dataset je pro tuto sadu metrik kompletní.")
        S.append({"h": "Co chybí v datech", "items": miss})

    return {
        "title": AI_INTENT_LABEL.get(intent, intent),
        "runner": r.name if r else None,
        "sections": S,
        "generated_at": engine.now_iso(),
        "caveat": "Souhrn dat, ne diagnóza. Nezohledňuje anamnézu, palpaci ani funkční testy a nenavrhuje léčbu. "
                 "Rozhoduje fyzioterapeut.",
        "llm": False,
    }


def brief(db: DBSession, rid: str, intent: str = "summary") -> dict:
    result = _compute(db, rid, intent)
    narrative = _llm_narrative(result) if llm.available() else None
    if narrative:
        result["sections"] = [{"h": "AI shrnutí", "items": [narrative]}] + result["sections"]
        result["llm"] = True
    return result


_TAG_RE = re.compile(r"<[^>]+>")


def _facts_text(sections: list[dict]) -> str:
    blocks = []
    for s in sections:
        items = "\n".join(f"- {_TAG_RE.sub(' ', i).strip()}" for i in s["items"])
        blocks.append(f"### {s['h']}\n{items}")
    return "\n\n".join(blocks)


_CHAT_INTENT_MAP = [
    (re.compile(r"zmen|změn|kontrol", re.I), "change"),
    (re.compile(r"kde|problém|proc|proč|příčin", re.I), "where"),
    (re.compile(r"program|cvik|dávk|davk", re.I), "program"),
    (re.compile(r"chyb|data|dost", re.I), "missing"),
]


def _match_intent(text: str) -> str:
    for rx, intent in _CHAT_INTENT_MAP:
        if rx.search(text or ""):
            return intent
    return "summary"


def _fallback_reply(db: DBSession, rid: str, message: str) -> str:
    """Used when no LLM is configured (or a call fails): buckets the
    free-text question into the closest structured intent and renders its
    sections as plain text, same content the old chip-only UI showed."""
    b = _compute(db, rid, _match_intent(message))
    lines = []
    for s in b["sections"]:
        lines.append(s["h"] + ":")
        lines.extend(f"- {_TAG_RE.sub(' ', it).strip()}" for it in s["items"])
        lines.append("")
    lines.append("Bez nakonfigurovaného AI modelu odpovídám nejbližší strukturovanou sekcí, ne na míru dotazu.")
    return "\n".join(lines).strip()


def chat_reply(db: DBSession, rid: str, message: str, history: list[dict] | None = None) -> dict:
    """Free-form multi-turn chat grounded in the same computed facts as
    brief() — the LLM answers the patient's actual question instead of
    being bucketed into one of the five fixed intents. history is the
    prior turns from this browser session (role/content dicts), replayed
    so follow-up questions keep context; nothing is persisted server-side."""
    if not llm.available():
        return {"reply": _fallback_reply(db, rid, message), "llm": False}

    full = _compute(db, rid, "all")
    facts_text = _facts_text(full["sections"])
    system = (
        "Jsi klinický asistent pro fyzioterapeuty v běžecké aplikaci Došlap, která sleduje riziko běžeckých "
        "zranění. Fyzioterapeut se tě ptá na jednoho konkrétního pacienta ve volné konverzaci. Dostaneš přesná, "
        "už vypočítaná fakta o tomto pacientovi — čísla, evidence grades (A/B/C), signály. Odpovídej stručně, "
        "věcně a konkrétně k tomuto pacientovi, v češtině, prostým textem bez markdownu.\n\n"
        "PRAVIDLA, která nikdy neporušíš:\n"
        "1. Nikdy nevymýšlej ani neodhaduj čísla, data nebo fakta, která nejsou doslova v datech níže.\n"
        "2. Nikdy nestanovuj diagnózu ani nenavrhuj konkrétní léčbu — jen popiš data a naznač, čemu věnovat "
        "pozornost. Rozhoduje vždy fyzioterapeut.\n"
        "3. Pokud fakta pro odpověď na dotaz chybí nebo jsou řídká, řekni to otevřeně — nedomýšlej si je.\n"
        "4. Zmiň stupeň evidence (A/B/C) u signálů, které ho mají, a nezacházej s nimi jako se stejně silnými.\n"
        "5. Pokud se dotaz netýká tohoto pacienta nebo běžeckých dat vůbec, zdvořile řekni, že odpovídáš jen "
        "na otázky o datech tohoto pacienta.\n\n"
        f"Pacient: {full['runner']}\n\nVypočítaná fakta o tomto pacientovi:\n{facts_text}"
    )
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-8:]:
        role, content = h.get("role"), h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)[:2000]})
    messages.append({"role": "user", "content": str(message)[:1000]})

    reply = llm.chat_messages(messages)
    if not reply:
        return {"reply": _fallback_reply(db, rid, message), "llm": False}
    return {"reply": reply, "llm": True}


def draft_conclusion(db: DBSession, rid: str, transcript: str):
    """Draft a post-visit conclusion for the physio to edit, grounded in the
    real session transcript plus this patient's computed data. Returns None
    when no LLM is configured or the transcript is empty — the physio then
    writes the conclusion from scratch. Unlike the risk engine (where the LLM
    may never be the sole source of a fact), the transcript *is* the source
    here: it's a record of what was actually said in the room, and the physio
    edits and approves before anything reaches the runner."""
    if not llm.available() or not (transcript or "").strip():
        return None
    facts = _compute(db, rid, "summary")
    facts_text = _facts_text(facts["sections"])
    system = (
        "Jsi klinický asistent pro fyzioterapeuty v běžecké aplikaci Došlap. Dostaneš přepis "
        "fyzioterapeutického sezení a doplňková vypočítaná data pacienta. Napiš NÁVRH závěru z "
        "prohlídky v češtině, prostým textem bez markdownu, ve třech krátkých částech: shrnutí "
        "nálezu, doporučení, a další kroky. Toto je pouze návrh — fyzioterapeut ho upraví a schválí "
        "předtím, než ho pacient uvidí.\n\n"
        "PRAVIDLA:\n"
        "1. Vycházej jen z toho, co v přepisu skutečně zaznělo, a z dodaných dat. Nevymýšlej nálezy, "
        "diagnózy ani měření, které tam nejsou.\n"
        "2. Pokud přepis něco neobsahuje, nedomýšlej to — raději to vynech.\n"
        "3. Piš stručně a konkrétně k tomuto pacientovi."
    )
    user = f"Pacient: {facts['runner']}\n\nPřepis sezení:\n{transcript}\n\nDoplňková data pacienta:\n{facts_text}"
    return llm.chat(system, user, max_tokens=650)


def _llm_narrative(result: dict):
    """One extra section, prepended — never a replacement for the
    structured facts below it, which stay exactly as computed. Strips HTML
    from the facts before sending them (the DIRECTIONS section embeds
    <b>/<br> markup for the UI) so the model sees clean text, not markup it
    might imitate or misparse."""
    facts_text = _facts_text(result["sections"])

    system = (
        "Jsi klinický asistent pro fyzioterapeuty v běžecké aplikaci Došlap, která sleduje riziko běžeckých "
        "zranění. Dostaneš přesná, už vypočítaná fakta o jednom pacientovi — čísla, evidence grades (A/B/C), "
        "signály. Napiš krátké (3-6 vět), přirozeně plynoucí shrnutí v češtině pro fyzioterapeuta, který má "
        "málo času před konzultací. Piš věcně a konkrétně k tomuto pacientovi, ne obecně.\n\n"
        "PRAVIDLA, která nikdy neporušíš:\n"
        "1. Nikdy nevymýšlej ani neodhaduj čísla, data nebo fakta, která nejsou doslova v datech níže.\n"
        "2. Nikdy nestanovuj diagnózu ani nenavrhuj konkrétní léčbu — jen shrň data a naznač, čemu věnovat "
        "pozornost. Rozhoduje vždy fyzioterapeut.\n"
        "3. Pokud fakta pro odpověď na dotaz chybí nebo jsou řídká, řekni to otevřeně — nedomýšlej si je.\n"
        "4. Zmiň stupeň evidence (A/B/C) u signálů, které ho mají, a nezacházej s nimi jako se stejně silnými.\n"
        "5. Odpovídej výhradně v češtině, prostým textem bez markdownu."
    )
    user = f"Pacient: {result['runner']}\nDotaz: {result['title']}\n\nVypočítaná fakta:\n{facts_text}"
    return llm.chat(system, user)
