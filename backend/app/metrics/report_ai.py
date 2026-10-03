"""A few sentences per morning / evening report card, written by the model from that
card's facts and validated like the assistant's daily commentary (coach_validate:
every number from the facts, no diagnosis or medication, nothing harder than today's
recommendation, Czech, 8–80 words). A card whose text fails keeps the rule-based one
(daily_report._notes_*). One call writes all cards (JSON); cached per day, report and
facts."""
import hashlib
import json
import re

from .. import llm, models
from . import coach_validate as V
from . import engine as E

SYSTEM = (
    "Jsi zkušený běžecký trenér v aplikaci Došlap. Dostaneš fakta z ranního nebo večerního reportu běžce, "
    "rozdělená po listech. Ke KAŽDÉMU listu napiš 2–3 krátké věty česky, tykání ne, vykej: nejdřív stručně zhodnoť, "
    "co fakta říkají (dobře / pozor), pak dej jeden konkrétní, proveditelný tip, jak se zlepšit nebo na co si dát pozor. "
    "Používej jen čísla, která jsou ve faktech (nic nepočítej, nezaokrouhluj jinak). Žádné diagnózy, žádné léky, "
    "nikdy nedoporučuj běhat přes bolest a nenavrhuj náročnější trénink, než je dnešní doporučení. Bez nadpisů a odkazů. "
    "Odpověz POUZE platným JSON objektem {\"klíč listu\": \"text\"} se stejnými klíči, jaké dostaneš."
)


def _facts_morning(r: dict) -> dict:
    n, rec, sl = r.get("night") or {}, r.get("recovery") or {}, (r.get("sleep") or {}).get("scores") or [{}]
    rn = r.get("recent") or {}
    y = rn.get("yesterday") or {}
    yv = y.get("view") or {}
    p = r.get("plan") or {}
    return {
        "intro": {"pripravenost": rec.get("score"), "vcera_pripravenost": rec.get("yesterday"), "spanek_h": n.get("hours"),
                  "dnes": p.get("label")},
        "sleep": {"spanek_h": n.get("hours"), "potreba_h": n.get("need"), "obvykle_h": (n.get("norm") or {}).get("h"),
                  "skore_spanku": sl[-1].get("score"), "usnuti": n.get("start"), "probuzeni": n.get("end"),
                  "hluboky_min": (n.get("stages") or {}).get("deep"), "rem_min": (n.get("stages") or {}).get("rem"),
                  "hluboky_obvykle_min": (n.get("norm") or {}).get("deep"), "rem_obvykle_min": (n.get("norm") or {}).get("rem"),
                  "probuzeni_pocet": n.get("awakeCount"), "spankovy_dluh_h": n.get("debt")},
        "readiness": {"pripravenost": rec.get("score"), "vcera": rec.get("yesterday"),
                      "hrv": (rec.get("night") or {}).get("hrv"), "hrv_obvykle": (rec.get("base") or {}).get("hrv"),
                      "klidovy_tep": (rec.get("night") or {}).get("rhr"), "klidovy_tep_obvykle": (rec.get("base") or {}).get("rhr"),
                      "co_snizuje": {k: v for k, v in ((rec.get("readiness") or {}).get("morningEffects") or {}).items() if v}},
        "recent": {"vcera_treninky": [x.get("title") for x in y.get("activities") or []],
                   "vcera_zatez_trenink": yv.get("trainLoad"), "vcera_zatez_mimo_trenink": yv.get("ntLoad"),
                   "vcera_aktivni_min": yv.get("activeMin"), "vcera_zvyseny_tep_v_klidu_min": yv.get("highMin"),
                   "tyden_km": rn.get("weekKm"), "tyden_cil_km": rn.get("budget"),
                   "nevstrebano": {c["label"]: c["share"] for c in rn.get("carry") or []}},
        "plan": {"doporuceni": p.get("label"), "km": p.get("km"), "tep": p.get("hr"),
                 "pozor": [w["text"] for w in r.get("watch") or []]},
    }


def _facts_evening(r: dict) -> dict:
    v = r.get("dayView") or {}
    ld = r.get("load") or {}
    t = r.get("tomorrow") or {}
    tn = r.get("tonight") or {}
    wk = r.get("week") or {}
    return {
        "intro": {"energie_ted": r.get("energyNow"), "zatez_dne": ld.get("total"), "tyden_km": wk.get("done"), "tyden_cil_km": wk.get("budget")},
        "day": {"vstavani": v.get("wake") and f"{int(v['wake']) // 60}:{int(v['wake']) % 60:02d}",
                "treninky": [x.get("title") for x in v.get("activities") or []], "aktivni_pohyb_min": v.get("activeMin"),
                "zvyseny_tep_v_klidu_min": v.get("highMin"), "mirne_zvyseny_min": v.get("mildMin"), "klid_min": v.get("calmMin"),
                "kroky": v.get("steps"), "energie_ted": r.get("energyNow")},
        "load": {"zatez_celkem": ld.get("total"), "trenink": ld.get("train"), "mimo_trenink": ld.get("nt"),
                 "mimo_trenink_obvykle": ld.get("usualNt"), "dnes_zbyva": ld.get("left"), "doporuceni": (ld.get("plan") or {}).get("label")},
        "tomorrow": {"vlivy": [e["text"] for e in t.get("effects") or []], "zitra_plan": t.get("plan")},
        "week": {"km": wk.get("done"), "cil_km": wk.get("budget"), "zbyva_km": wk.get("left"),
                 "navrh": [f"{d['wd']} {d['type']}" for d in (r.get("restOfWeek") or {}).get("days") or []]},
        "tonight": {"spanek_cil_h": tn.get("target"), "do_postele": tn.get("bed"), "vstavani": tn.get("wake"),
                    "posledni_kava": tn.get("caffeine"), "zitra_narocne": tn.get("hardTomorrow")},
    }


def facts(r: dict) -> dict:
    return _facts_morning(r) if r.get("kind") == "morning" else _facts_evening(r)


def _hash(f: dict) -> str:
    return hashlib.sha1(json.dumps(f, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _parse(txt: str | None) -> dict:
    if not txt:
        return {}
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except (ValueError, AttributeError):
        return {}
    return {k: str(v).strip() for k, v in out.items() if isinstance(v, (str, int, float))}


def cached(db, rid: str, r: dict) -> dict | None:
    f = facts(r)
    row = db.query(models.ReportNote).filter(models.ReportNote.runner_id == rid, models.ReportNote.date == r["date"],
                                             models.ReportNote.kind == r["kind"]).first()
    return row.notes if (row is not None and row.facts_hash == _hash(f)) else None


def generate(db, rid: str, r: dict) -> dict:
    """{card: text} — validated model sentences where they pass, else the rule-based ones."""
    f = facts(r)
    h = _hash(f)
    row = db.query(models.ReportNote).filter(models.ReportNote.runner_id == rid, models.ReportNote.date == r["date"],
                                             models.ReportNote.kind == r["kind"]).first()
    if row is not None and row.facts_hash == h:
        return {"notes": {**r.get("notes", {}), **(row.notes or {})}, "source": "ai" if row.notes else "rules"}
    out, rejected = {}, {}
    if llm.assistant_available():
        txt = llm.chat_messages([{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": json.dumps(f, ensure_ascii=False, default=str)}],
                                temperature=0.3, max_tokens=900, timeout=60, model=llm.ASSISTANT_MODEL,
                                base_url=llm.ASSISTANT_BASE_URL, api_key=llm.ASSISTANT_API_KEY)
        today_type = ((r.get("plan") or {}).get("type") or ((r.get("load") or {}).get("plan") or {}).get("type"))
        for card, text in _parse(txt).items():
            if card not in f:
                continue
            res = V.validate("report_card", text, {**f[card], "rok": int(r["date"][:4]), "today": {"type": today_type}})
            if res["ok"]:
                out[card] = text
            else:
                rejected[card] = res["issues"]
    if row is None:
        row = models.ReportNote(runner_id=rid, date=r["date"], kind=r["kind"])
        db.add(row)
    row.facts_hash, row.notes, row.rejected, row.created_at = h, out, rejected, E.now_iso()
    db.commit()
    return {"notes": {**r.get("notes", {}), **out}, "source": "ai" if out else "rules"}
