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

# Written after the keyword dictionary was tuned on RETRIEVAL and never used for
# tuning: the fair comparison between keyword, dense and hybrid search.
HOLDOUT = [
    ("Minulý týden jsem naběhal 30 km, tento chci 45, je to moc?", "a-tydenni-skok"),
    ("Hodinky ukazují nízké HRV jen dnes ráno, mám zrušit trénink?", "c-tydenni-hrv"),
    ("Kolik nocí dat potřebuje aplikace, než pozná můj normál HRV?", "c-pocet-noci"),
    ("Proč mám většinu běhů běhat pomalu?", "d-vetsina-lehce"),
    ("Je lepší běhat hodně intervalů, nebo spíš dlouhé pomalé běhy?", "d-polarizace"),
    ("Jaká kadence je ideální?", "e-kadence"),
    ("Běhám hodně do kopce, jak to ovlivní zátěž?", "e-stoupani"),
    ("Je v létě normální, že mám vyšší tep při stejném tempu?", "f-horko"),
    ("Spím špatně už celý týden, jak to ovlivní výkon?", "g-vice-noci"),
    ("Bolí mě kříž a necitlivost v rozkroku", "h-zada"),
    ("Můžu dělat rehabilitační cviky, i když to trochu bolí?", "h-rehab-bolest"),
    ("Dělá silový trénink běžce rychlejším?", "i-sila-ekonomika"),
    ("Stačí před závodem posilovat jednou týdně?", "i-udrzovani"),
    ("Mám posilovat hned po intervalech?", "i-odstup"),
    ("Co znamená poměr akutní a chronické zátěže?", "b-acwr"),
    ("Chystám se na první ultra, na co si dát pozor?", "a-ultra-zkusenost"),
    ("Začal jsem posilovat a nohy mám jak z olova", "i-novy-blok"),
    ("Proč mi HRV klesá, když piju alkohol nebo jsem nemocný?", "c-hrv-zivot"),
]


def _cards(db, q: str, dense=None, n=5, weight=None) -> list[str]:
    sel = SEL.classify(q)
    return [c["id"] for c in K.search(db, q, topics=sel["topics"], n_cards=n, dense=dense, dense_weight=weight)["cards"]]


def retrieval(db, embed_model: str | None = None, weights: tuple = (1.0, 3.0, 5.0), detail: bool = False) -> dict:
    """Top-5 hit rate on the labelled questions (tuning set and holdout): keyword
    search, and with `embed_model` also dense-only and hybrid rankings (fusion
    weights `weights`) over the card texts."""
    import numpy as np
    from .. import llm

    K.INDEX.ensure(db)
    sets = {"tuning": RETRIEVAL, "holdout": HOLDOUT}
    out = {name: {"n": len(qs), "keyword": 0, "misses": {"keyword": []}} for name, qs in sets.items()}
    for name, qs in sets.items():
        for q, want in qs:
            if want in _cards(db, q, dense=[]):
                out[name]["keyword"] += 1
            else:
                out[name]["misses"]["keyword"].append(want)
    if not embed_model:
        return out
    idx = [i for i, r in enumerate(K.INDEX.rows) if r["kind"] == "card"]
    vecs = llm.embed([K.INDEX.rows[i]["text"] for i in idx], kind="passage", model=embed_model)
    if not vecs:
        out["error"] = llm.LAST_ERROR.get("embed")
        return out
    m = np.asarray(vecs, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    out["model"] = embed_model
    for name, qs in sets.items():
        qv = llm.embed([q for q, _ in qs], kind="query", model=embed_model)
        if not qv:
            out["error"] = llm.LAST_ERROR.get("embed")
            return out
        r = out[name]
        r.update({"dense": 0, "hybrid": {str(w): 0 for w in weights}})
        r["misses"].update({"dense": [], "hybrid": {str(w): [] for w in weights}})
        for (q, want), v in zip(qs, qv):
            v = np.asarray(v, dtype=np.float32)
            sims = m @ (v / (np.linalg.norm(v) + 1e-9))
            order = np.argsort(-sims)
            if want in [K.INDEX.rows[idx[j]]["sid"] for j in order[:5]]:
                r["dense"] += 1
            else:
                r["misses"]["dense"].append(want)
            dn = [(idx[j], float(sims[j])) for j in order[:60]]
            if detail:
                r.setdefault("rankings", {})[q] = [(K.INDEX.rows[i]["sid"], round(sc, 4)) for i, sc in dn]
            for w in weights:
                if want in _cards(db, q, dense=dn, weight=w):
                    r["hybrid"][str(w)] += 1
                else:
                    r["misses"]["hybrid"][str(w)].append(want)
    return out
