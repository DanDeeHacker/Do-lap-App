"""Knowledge base of the Physio AI Assistant (implementation plan, step A).

Three tiers, preferred in this order when answering:
  1. evidence cards (knowledge/cards.json): Czech claims with limits, strength and
     sources — what the app is willing to say;
  2. literature summaries (knowledge/summaries.json): the 54 structured entries of
     the project's literature summary — grounding detail;
  3. full texts: PDFs uploaded by an admin, split into passages.
plus the app guide (knowledge/app_guide.json) for "where do I find …" questions.

Everything is stored as KnowledgeChunk rows so one search covers all tiers. The
search is hybrid: BM25 over diacritic-free, prefix-stemmed tokens (with a small
Czech → English dictionary, because questions are Czech and most sources are
English) fused with cosine similarity of multilingual embeddings when the
embedding API is configured (llm.embed). Without embeddings it is BM25 only, which
is what the test suite runs.
"""
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import unicodedata
from collections import Counter
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .. import llm, models

log = logging.getLogger("dosslap.assistant")
KB_DIR = Path(__file__).resolve().parent.parent / "knowledge"
CHUNK_WORDS, CHUNK_OVERLAP = 380, 40
STRENGTH_ORDER = {"silné": 3, "střední": 2, "slabé": 1}


# ------------------------------------------------------------------ built-in sources
@lru_cache(maxsize=1)
def summaries() -> dict:
    return json.loads((KB_DIR / "summaries.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def summary_by_id() -> dict:
    return {e["id"]: e for e in summaries()["entries"]}


@lru_cache(maxsize=1)
def cards() -> list[dict]:
    return json.loads((KB_DIR / "cards.json").read_text(encoding="utf-8"))["cards"]


@lru_cache(maxsize=1)
def card_by_id() -> dict:
    return {c["id"]: c for c in cards()}


@lru_cache(maxsize=1)
def guide() -> list[dict]:
    return json.loads((KB_DIR / "app_guide.json").read_text(encoding="utf-8"))["sections"]


@lru_cache(maxsize=1)
def guide_by_id() -> dict:
    return {g["id"]: g for g in guide()}


def card_sources(card: dict) -> list[dict]:
    """APA reference, DOI and short citation of a card's sources."""
    out = []
    for sid in card.get("sources") or []:
        e = summary_by_id().get(sid)
        if e:
            out.append({"id": sid, "cite": e["cite"], "apa": e["apa"], "doi": e.get("doi")})
    return out


def card_status(db) -> dict:
    return {r.card_id: r.status for r in db.query(models.CardReview).all()}


# ------------------------------------------------------------------ text processing
_STOP = set("""a aby ale an and ani are as at az be bez by byl byla bylo byt ci co do for from ho i in is it
ja je jeho jej jen jeste jsem jsme jsou jste k kde kdy kdyz ke ktera ktere ktery kteri me mi mne mu my na nad
nam nas ne nebo neni nez o od of on ona oni ono or po pod pokud pri pro proc proto protoze s se si sve ta tak take
tam te tedy tem ten tento tery the their them there these this those to toho tom tu ty u uz v ve vam vas ve vy
was were what when which who why will with z za ze zda""".split())
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")

# Czech (diacritics removed) word starts → English search terms. Questions are Czech,
# most sources English; the dictionary covers the domain vocabulary only.
CS_EN = {
    "holen": "shin tibia tibial bone", "holn": "shin tibia", "berec": "shin lower leg", "chodid": "foot",
    "nart": "foot metatarsal navicular", "pata": "heel calcaneus", "paty": "heel", "patu": "heel",
    "prst": "toe metatarsal", "kost": "bone stress fracture", "zlomen": "fracture bone stress",
    "bolest": "pain", "bolav": "pain sore", "boli": "pain", "zad": "back spinal", "bedr": "lumbar back spinal",
    "kolen": "knee", "achill": "achilles tendon tendinopathy", "slach": "tendon tendinopathy",
    "lytk": "calf", "kycl": "hip", "kycel": "hip", "stehn": "thigh hamstring quadriceps", "trisl": "groin",
    "spanek": "sleep", "spank": "sleep", "spat": "sleep", "spal": "sleep", "nespav": "sleep insomnia",
    "hrv": "hrv heart rate variability", "variabil": "variability hrv", "klidov": "resting heart rate",
    "tep": "heart rate", "srdc": "heart rate", "zatez": "load training load", "objem": "volume distance",
    "kapacit": "capacity load", "skok": "spike increase sudden", "narust": "increase progression",
    "navys": "increase progression", "intenzit": "intensity", "interval": "interval high intensity",
    "tempo": "pace tempo threshold", "lehk": "easy low intensity", "tvrd": "hard high intensity",
    "dlouh": "long run", "kopc": "hill uphill downhill", "stoupa": "uphill incline ascent",
    "klesa": "downhill descent decline", "sebeh": "downhill descent", "teren": "terrain trail",
    "trail": "trail terrain", "horko": "heat hot", "horc": "heat hot", "vedr": "heat hot", "tepl": "heat temperature",
    "pit": "hydration fluid", "posil": "strength training resistance", "silov": "strength resistance",
    "cvik": "exercise", "strecink": "stretching", "unav": "fatigue tired", "stres": "stress",
    "nemoc": "illness sick", "nachlaz": "illness cold", "horeck": "fever illness", "zavod": "race competition",
    "marat": "marathon", "pulmarat": "half marathon", "ladeni": "taper", "odleh": "deload recovery reduce",
    "regener": "recovery", "pripraven": "readiness", "priprav": "preparation build", "techni": "technique mechanics biomechanics",
    "kadenc": "cadence step rate", "krok": "stride step", "dopad": "foot strike impact", "mechanik": "mechanics biomechanics",
    "drift": "drift mechanics fatigue", "pauz": "break detraining", "navrat": "return to sport running",
    "zranen": "injury", "fyzio": "physiotherapy physiotherapist", "narocn": "effort rpe exertion",
    "rpe": "rpe perceived exertion", "kolo": "cycling", "plav": "swimming", "cyklus": "periodization cycle",
    "tyden": "week weekly", "pravidl": "rule", "zacatec": "novice beginner", "rekreac": "recreational",
    "vzdalen": "distance", "rychl": "speed pace", "zeny": "women female", "zena": "women female",
    "vitamin": "vitamin", "vyziv": "nutrition energy", "energie": "energy availability",
}


def fold(text: str) -> str:
    """Lowercase, diacritics removed."""
    return unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()


def stem(tok: str) -> str:
    return tok if len(tok) < 5 or tok[0].isdigit() else tok[:5]


def tokens(text: str) -> list[str]:
    return [stem(t) for t in _WORD.findall(fold(text)) if t not in _STOP and len(t) > 1]


def expand_query(text: str) -> list[str]:
    """Query tokens plus the English terms of the Czech domain words it contains."""
    raw = [t for t in _WORD.findall(fold(text)) if t not in _STOP and len(t) > 1]
    extra = []
    for t in raw:
        hit = max((k for k in CS_EN if t.startswith(k)), key=len, default=None)   # the most specific word start
        if hit:
            extra += CS_EN[hit].split()
    return [stem(t) for t in raw] + [stem(t) for t in extra]


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ chunk builders
def builtin_chunks() -> list[dict]:
    """(source_kind, source_id, section, ord, text) for cards, summaries and guide."""
    out = []
    for c in cards():
        cites = "; ".join(s["cite"] for s in card_sources(c))
        text = f"{c['title']}. {c['claim']} Omezení: {c['limits']} Zdroje: {cites}."
        out.append({"source_kind": "card", "source_id": c["id"], "section": c["cat"], "ord": 0, "text": text})
    for e in summaries()["entries"]:
        facts = "; ".join(f"{k}: {v}" for k, v in (e.get("facts") or {}).items())
        out.append({"source_kind": "summary", "source_id": e["id"], "section": "findings", "ord": 0,
                    "text": f"{e['cite']}. {facts}. Key findings: " + " ".join(e.get("findings") or [])})
        out.append({"source_kind": "summary", "source_id": e["id"], "section": "relevance", "ord": 1,
                    "text": f"{e['cite']}. Relevance: {e.get('relevance', '')} Limits: {e.get('limits', '')}"})
    for g in guide():
        out.append({"source_kind": "guide", "source_id": g["id"], "section": g["app"], "ord": 0,
                    "text": f"{g['title']}. {g['text']}"})
    return out


def sync_builtin(db) -> int:
    """Upsert the built-in chunks (cards, summaries, guide) from the repo JSON:
    a changed text replaces the row (and drops its embedding), a removed source
    is deleted. Returns how many rows changed."""
    want = {(c["source_kind"], c["source_id"], c["ord"]): c for c in builtin_chunks()}
    have = {(r.source_kind, r.source_id, r.ord or 0): r for r in db.query(models.KnowledgeChunk).filter(
        models.KnowledgeChunk.source_kind.in_(("card", "summary", "guide"))).all()}
    changed = 0
    for key, c in want.items():
        h = _hash(c["text"])
        r = have.get(key)
        if r is None:
            db.add(models.KnowledgeChunk(**c, text_hash=h))
            changed += 1
        elif r.text_hash != h:
            r.text, r.text_hash, r.section, r.embedding, r.embed_model = c["text"], h, c["section"], None, None
            changed += 1
    for key, r in have.items():
        if key not in want:
            db.delete(r)
            changed += 1
    if changed:
        db.commit()
        INDEX.invalidate()
    return changed


# ------------------------------------------------------------------ PDF ingestion
_DROP_FROM = re.compile(r"^\s*(references|bibliography|literature cited|acknowledg(e)?ments?|conflicts? of interest|"
                        r"funding|author contributions|supplementary material)\s*$", re.I)
_SECTION = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(abstract|introduction|background|methods?|materials and methods|"
                      r"results|discussion|conclusions?|limitations|practical applications|summary|"
                      r"key points)\s*$", re.I)


def pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return "\n".join(pages), len(pages)


def clean_sections(text: str) -> list[tuple[str, str]]:
    """[(section, text)]: running headers/footers (lines repeated on many pages and
    page numbers) removed, everything from the reference list on dropped."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    counts = Counter(ln.strip() for ln in lines if ln.strip())
    repeated = {ln for ln, n in counts.items() if n >= 4 and len(ln) < 90}
    out, cur, name = [], [], "text"
    for ln in lines:
        s = ln.strip()
        if not s or s in repeated or re.fullmatch(r"\d{1,4}", s):
            continue
        if _DROP_FROM.match(s):
            break
        m = _SECTION.match(s)
        if m:
            if cur:
                out.append((name, " ".join(cur)))
            name, cur = m.group(1).lower(), []
            continue
        cur.append(s)
    if cur:
        out.append((name, " ".join(cur)))
    # de-hyphenate words broken at line ends
    return [(n, re.sub(r"(\w)- (\w)", r"\1\2", t)) for n, t in out]


def chunk(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Passages of about CHUNK_WORDS words with a small overlap, per section."""
    out = []
    for name, text in sections:
        words = text.split()
        if len(words) < 25:
            continue
        step = CHUNK_WORDS - CHUNK_OVERLAP
        for i in range(0, len(words), step):
            part = words[i:i + CHUNK_WORDS]
            if len(part) < 40 and out:
                out[-1] = (out[-1][0], out[-1][1] + " " + " ".join(part))
                break
            out.append((name, " ".join(part)))
            if i + CHUNK_WORDS >= len(words):
                break
    return out


_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def match_summary(doi: str | None, text: str) -> dict | None:
    if doi:
        d = doi.lower().rstrip(".")
        for e in summaries()["entries"]:
            if e.get("doi") and e["doi"].lower() == d:
                return e
    return None


def ingest_pdf(db, data: bytes, filename: str, meta: dict | None = None, user: str | None = None) -> dict:
    """Store one uploaded article as passages. `meta` may carry doi, cite, apa, year,
    category, licence; missing ones come from the matching literature-summary entry
    (by DOI) or from the PDF text. Re-uploading the same DOI replaces the old copy."""
    meta = dict(meta or {})
    text, pages = pdf_text(data)
    if len(text.split()) < 200:
        raise ValueError("V PDF není čitelný text (sken bez textové vrstvy?).")
    doi = meta.get("doi") or (m.group(1).rstrip(".);,") if (m := _DOI.search(text[:6000])) else None)
    entry = match_summary(doi, text)
    if doi:
        for old in db.query(models.KnowledgeDoc).filter(models.KnowledgeDoc.doi == doi).all():
            delete_doc(db, old.id, commit=False)
    doc = models.KnowledgeDoc(
        title=meta.get("title") or (entry["apa"].split(").", 1)[-1].split(".")[0].strip() if entry else filename),
        cite=meta.get("cite") or (entry["cite"] if entry else filename), apa=meta.get("apa") or (entry["apa"] if entry else None),
        doi=doi, year=meta.get("year"), category=meta.get("category") or (entry["category"] if entry else None),
        summary_id=entry["id"] if entry else None, licence=meta.get("licence") or "uploaded",
        filename=filename, pages=pages, uploaded_by=user, uploaded_at=datetime.utcnow().isoformat(timespec="seconds"))
    db.add(doc)
    db.flush()
    parts = chunk(clean_sections(text))
    for i, (sec, t) in enumerate(parts):
        db.add(models.KnowledgeChunk(source_kind="fulltext", source_id=str(doc.id), doc_id=doc.id, section=sec,
                                     ord=i, text=t, text_hash=_hash(t)))
    doc.n_chunks = len(parts)
    db.commit()
    INDEX.invalidate()
    return {"id": doc.id, "cite": doc.cite, "doi": doi, "chunks": len(parts), "pages": pages,
            "matchedSummary": doc.summary_id}


def delete_doc(db, doc_id: int, commit: bool = True) -> bool:
    doc = db.query(models.KnowledgeDoc).filter(models.KnowledgeDoc.id == doc_id).first()
    if doc is None:
        return False
    db.query(models.KnowledgeChunk).filter(models.KnowledgeChunk.doc_id == doc_id).delete()
    db.delete(doc)
    if commit:
        db.commit()
        INDEX.invalidate()
    return True


def embed_pending(db, limit: int = 256, batch: int = 32) -> int:
    """Compute missing embeddings (background work). 0 without an embedding API."""
    if not llm.embed_available():
        return 0
    import numpy as np
    rows = (db.query(models.KnowledgeChunk)
            .filter((models.KnowledgeChunk.embedding.is_(None)) | (models.KnowledgeChunk.embed_model != llm.EMBED_MODEL))
            .limit(limit).all())
    done = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = llm.embed([r.text for r in part], kind="passage")
        if not vecs:
            break
        for r, v in zip(part, vecs):
            a = np.asarray(v, dtype=np.float32)
            r.embedding = (a / (np.linalg.norm(a) or 1.0)).tobytes()
            r.embed_model = llm.EMBED_MODEL
            done += 1
        db.commit()
    if done:
        INDEX.invalidate()
    return done


# ------------------------------------------------------------------ the index
# weight of the embedding ranking in the fusion (keyword ranking = 1); set from the
# Gate 1 comparison on the live knowledge base (evaluate.retrieval)
# (llama-nemotron-embed-vl-1b-v2, 2026-09-28: dense alone 20/20 tuning and 18/18
# holdout, keyword 18/20 and 12/18, fusion with dense 3 and no topic boost 20/20, 18/18)
DENSE_WEIGHT = float(os.environ.get("ASSISTANT_DENSE_WEIGHT", "3.0"))
TOPIC_WEIGHT_DENSE = float(os.environ.get("ASSISTANT_TOPIC_WEIGHT_DENSE", "0.0"))


class _Index:
    """In-memory search index over all chunks, rebuilt on demand after a change."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stale = True
        self.rows = []

    def invalidate(self):
        self._stale = True

    def ensure(self, db):
        if not self._stale and self.rows:
            return
        with self._lock:
            if not self._stale and self.rows:
                return
            import numpy as np
            rows = db.query(models.KnowledgeChunk).all()
            self.rows = [{"id": r.id, "kind": r.source_kind, "sid": r.source_id, "section": r.section, "text": r.text,
                          "doc_id": r.doc_id} for r in rows]
            # Czech sources (cards, guide) also carry the English terms of their domain
            # words, so a Czech question meets them through the same concept terms
            self.toks = [Counter(expand_query(r["text"]) if r["kind"] in ("card", "guide") else tokens(r["text"]))
                         for r in self.rows]
            self.len = [sum(t.values()) for t in self.toks]
            self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
            df = Counter()
            for t in self.toks:
                df.update(t.keys())
            n = len(self.rows)
            self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
            vecs = [(i, r.embedding) for i, r in enumerate(rows) if r.embedding and r.embed_model == llm.EMBED_MODEL]
            if vecs:
                dim = len(np.frombuffer(vecs[0][1], dtype=np.float32))
                self.vec_idx = [i for i, b in vecs if len(b) == dim * 4]
                self.mat = np.vstack([np.frombuffer(b, dtype=np.float32) for i, b in vecs if len(b) == dim * 4])
            else:
                self.vec_idx, self.mat = [], None
            self._stale = False

    def bm25(self, q: list[str], k1=1.2, b=0.75) -> list[tuple[int, float]]:
        qc = Counter(q)
        out = []
        for i, t in enumerate(self.toks):
            s = 0.0
            for w, qn in qc.items():
                f = t.get(w)
                if f:
                    s += self.idf.get(w, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / self.avg)) * (1 + 0.2 * (qn - 1))
            if s > 0:
                out.append((i, s))
        return sorted(out, key=lambda x: -x[1])

    def dense(self, qvec) -> list[tuple[int, float]]:
        if self.mat is None or qvec is None:
            return []
        import numpy as np
        v = np.asarray(qvec, dtype=np.float32)
        if v.shape[0] != self.mat.shape[1]:
            return []
        v = v / (np.linalg.norm(v) or 1.0)
        sims = self.mat @ v
        order = np.argsort(-sims)[:60]
        return [(self.vec_idx[j], float(sims[j])) for j in order]


INDEX = _Index()


def search(db, query: str, topics: list[str] | None = None, signals: list[str] | None = None,
           want_guide: bool = False, n_cards: int = 3, n_passages: int = 4, n_guide: int = 2,
           active: list[str] | None = None, dense: list | None = None, dense_weight: float | None = None) -> dict:
    """Hybrid search. Returns {cards, passages, guide, mode}: cards are card dicts
    (+ status, score), passages are summary / full-text chunks, guide are app-guide
    sections. Cards triggered by the runner's active signals or matching the
    question's topics are boosted (reciprocal rank fusion, k = 60). `signals` are the
    ones the runner asked about (strong boost), `active` the runner's other active
    signals (weak boost, so a specific question still finds its own cards)."""
    INDEX.ensure(db)
    if not INDEX.rows:
        return {"cards": [], "passages": [], "guide": [], "mode": "empty"}
    q = expand_query(query)
    bm = INDEX.bm25(q)[:60]
    if dense is not None:                          # evaluation: a ranking from a candidate model
        dn = dense
    else:
        qvec = None
        if INDEX.mat is not None:
            got = llm.embed([query], kind="query")
            qvec = got[0] if got else None
        dn = INDEX.dense(qvec)
    k = 60.0
    score = {}
    for rank, (i, _s) in enumerate(bm):
        score[i] = score.get(i, 0) + 1 / (k + rank + 1)
    dw = DENSE_WEIGHT if dense_weight is None else dense_weight
    # with a good embedding ranking the question's meaning is covered and the
    # intent-topic boost only pulls in look-alike cards (Gate 1 holdout)
    tw = TOPIC_WEIGHT_DENSE if dn else 1.0
    for rank, (i, _s) in enumerate(dn):
        score[i] = score.get(i, 0) + dw / (k + rank + 1)
    status = card_status(db)
    topics, signals, active = set(topics or []), set(signals or []), set(active or []) - set(signals or [])
    for i, r in enumerate(INDEX.rows):
        if r["kind"] != "card":
            continue
        c = card_by_id().get(r["sid"])
        if not c or status.get(c["id"]) == "rejected":
            score.pop(i, None)
            continue
        ap = c.get("applies") or {}
        if signals & set(ap.get("signals") or []):
            score[i] = score.get(i, 0) + 2 / (k + 1)
        elif active & set(ap.get("signals") or []):
            score[i] = score.get(i, 0) + 0.5 / (k + 1)
        overlap = len(topics & set(ap.get("topics") or []))
        if overlap and tw:
            score[i] = score.get(i, 0) + tw * overlap / (k + 1)
    ranked = sorted(score.items(), key=lambda x: -x[1])
    out_cards, out_pass, out_guide, per_src = [], [], [], Counter()
    for i, s in ranked:
        r = INDEX.rows[i]
        if r["kind"] == "card" and len(out_cards) < n_cards:
            c = card_by_id()[r["sid"]]
            out_cards.append({**c, "status": status.get(c["id"], "draft"), "score": round(s, 4),
                              "sourcesMeta": card_sources(c)})
        elif r["kind"] in ("summary", "fulltext") and len(out_pass) < n_passages and per_src[(r["kind"], r["sid"])] < 2:
            per_src[(r["kind"], r["sid"])] += 1
            out_pass.append({**r, "score": round(s, 4), **_passage_meta(db, r)})
        elif r["kind"] == "guide" and want_guide and len(out_guide) < n_guide:
            out_guide.append({**guide_by_id()[r["sid"]], "score": round(s, 4)})
    return {"cards": out_cards, "passages": out_pass, "guide": out_guide,
            "mode": "hybrid" if dn else "keyword"}


def _passage_meta(db, r: dict) -> dict:
    if r["kind"] == "summary":
        e = summary_by_id().get(r["sid"]) or {}
        return {"cite": e.get("cite"), "apa": e.get("apa"), "doi": e.get("doi"), "strengthNote": e.get("strength")}
    doc = db.query(models.KnowledgeDoc).filter(models.KnowledgeDoc.id == r["doc_id"]).first()
    return {"cite": doc.cite if doc else None, "apa": doc.apa if doc else None, "doi": doc.doi if doc else None,
            "strengthNote": None}
