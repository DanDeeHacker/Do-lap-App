"""Retrieval check for the Physio AI Assistant (implementation plan, Gate 1):
does the right evidence card land in the top five for a set of labelled Czech
questions? Used by the test suite (keyword search) and by the ops / admin check
to compare embedding models before one is switched on (keyword, dense, hybrid)."""
from . import knowledge as K
from . import selector as SEL

RETRIEVAL = [
    ("Je pravidlo 10 % bezpečné?", "a-10-procent"),
    ("Zvýšil jsem týdenní objem o polovinu, vadí to?", "a-tydenni-skok"),
    ("Loni jsem měl zranění kolene, co to znamená pro trénink?", "a-predchozi-zraneni"),
    ("Proč stejný běh jednou zvládnu snadno a jindy mám vysoký tep?", "b-vnitrni-vnejsi"),
    ("Proč mám hodnotit náročnost po běhu?", "b-rpe"),
    ("Má můj check-in vůbec nějakou váhu?", "b-subjektivni"),
    ("Proč aplikace nebere jednu špatnou noc HRV tak vážně?", "c-tydenni-hrv"),
    ("Mám vysoké HRV, ale jsem unavený", "c-vysoka-hrv"),
    ("Kolik tvrdých tréninků týdně je rozumné?", "d-vetsina-lehce"),
    ("Proč mám lehký běh držet v tepovém rozmezí?", "d-lehky-tep"),
    ("Po trailu z kopce mě bolí stehna, proč seběh tolik zatěžuje?", "e-seby"),
    ("Mám zkracovat krok a běhat po špičkách?", "e-technika"),
    ("V horku mám o deset tepů víc, ztrácím kondici?", "f-horko"),
    ("Kolik mám pít, když je vedro?", "f-piti"),
    ("Stačí mi šest hodin spánku?", "g-7-hodin"),
    ("Bolí mě Achillovka, můžu běhat?", "h-slacha"),
    ("Bolí mě holeň i při chůzi", "h-kost"),
    ("Kdy se můžu po zranění vrátit k běhu?", "h-navrat"),
    ("Kolikrát týdně posilovat?", "i-sila-ekonomika"),
    ("Pomáhá strečink proti zraněním?", "i-sila-zraneni"),
]


def _cards(db, q: str, dense=None, n=5) -> list[str]:
    sel = SEL.classify(q)
    return [c["id"] for c in K.search(db, q, topics=sel["topics"], n_cards=n, dense=dense)["cards"]]


def retrieval(db, embed_model: str | None = None) -> dict:
    """Top-5 hit rate of the labelled questions: keyword search, and with
    `embed_model` also dense-only and hybrid rankings over the card texts."""
    import numpy as np
    from .. import llm

    K.INDEX.ensure(db)
    out = {"n": len(RETRIEVAL), "keyword": 0, "misses": {"keyword": []}}
    for q, want in RETRIEVAL:
        if want in _cards(db, q, dense=[]):
            out["keyword"] += 1
        else:
            out["misses"]["keyword"].append(want)
    if not embed_model:
        return out
    idx = [i for i, r in enumerate(K.INDEX.rows) if r["kind"] == "card"]
    vecs = llm.embed([K.INDEX.rows[i]["text"] for i in idx], kind="passage", model=embed_model)
    qv = llm.embed([q for q, _ in RETRIEVAL], kind="query", model=embed_model)
    if not vecs or not qv:
        out["error"] = llm.LAST_ERROR.get("embed")
        return out
    m = np.asarray(vecs, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    out.update({"model": embed_model, "dense": 0, "hybrid": 0})
    out["misses"].update({"dense": [], "hybrid": []})
    for (q, want), v in zip(RETRIEVAL, qv):
        v = np.asarray(v, dtype=np.float32)
        sims = m @ (v / (np.linalg.norm(v) + 1e-9))
        order = np.argsort(-sims)
        top = [K.INDEX.rows[idx[j]]["sid"] for j in order[:5]]
        if want in top:
            out["dense"] += 1
        else:
            out["misses"]["dense"].append(want)
        dn = [(idx[j], float(sims[j])) for j in order[:60]]
        if want in _cards(db, q, dense=dn):
            out["hybrid"] += 1
        else:
            out["misses"]["hybrid"].append(want)
    return out
