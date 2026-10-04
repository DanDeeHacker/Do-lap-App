"""v0.12.0 — shoes: recognition from a photo and the standardised record.

The photo goes to the vision model once and is not stored. Its answer is normalised —
the brand to the manufacturer's spelling, the category to one of the app's seven, the
drop and stack to plausible millimetres — and comes back as a suggestion the runner
confirms or corrects before saving (the first-use date is always the runner's).
"""
import base64
import json
import re
import time

from . import llm
from .metrics.runner_factors import CATEGORIES

MAX_IMAGE_BYTES = 4_000_000
_IMG_RE = re.compile(r"^data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\s]+)$")
RATE_PER_HOUR = 20
_CALLS: dict[str, list] = {}

BRANDS = ("Nike", "adidas", "ASICS", "Brooks", "HOKA", "Saucony", "New Balance", "On", "PUMA", "Mizuno", "Altra",
          "Salomon", "inov-8", "Merrell", "Under Armour", "Reebok", "Skechers", "La Sportiva", "Topo Athletic",
          "Vivobarefoot", "Xero Shoes", "Kiprun", "Craft", "Scott", "Diadora", "361°", "Li-Ning", "Karhu", "Norda",
          "VJ", "Dynafit", "The North Face", "Joma", "Kalenji", "Newton", "Hylo", "Veja", "Allbirds")
_BRAND_KEY = {re.sub(r"[^a-z0-9]", "", b.lower()): b for b in BRANDS}
_BRAND_KEY.update({"hokaoneone": "HOKA", "onrunning": "On", "oncloud": "On", "newbalance": "New Balance",
                   "nb": "New Balance", "decathlon": "Kiprun", "ua": "Under Armour", "xero": "Xero Shoes",
                   "topo": "Topo Athletic", "inov8": "inov-8"})
ZERO_DROP = ("Altra", "Vivobarefoot", "Xero Shoes")       # the whole range is zero-drop
BAREFOOT = ("Vivobarefoot", "Xero Shoes")                  # …and minimal
CATEGORY_CS = {"daily": "každodenní", "cushioned": "s vysokým tlumením", "stability": "stabilní",
               "racing": "závodní", "minimal": "minimalistická", "trail": "trailová", "track": "tretry / dráha"}

PROMPT = (
    "Identify the running shoe in this photo. First read any text printed on the shoe (brand, model name, "
    "version number). Reply with one JSON object only, no other text:\n"
    '{"is_shoe": true|false, "brand": string|null, "model": string|null, "category": '
    '"daily"|"cushioned"|"stability"|"racing"|"minimal"|"trail"|"track"|null, '
    '"drop_mm": number|null, "stack_mm": number|null, "carbon": true|false|null, "confidence": 0..1}\n'
    "model = the manufacturer's official model name with its version number when you can read or clearly "
    "recognise it (e.g. \"Pegasus 41\", \"Gel-Nimbus 26\", \"Clifton 9\", \"Endorphin Speed 4\"). If you "
    "recognise the model line but not the version, give the line without a number (e.g. \"Pegasus\") and "
    "confidence at most 0.5. drop_mm / stack_mm = the published heel-to-toe drop and heel stack of that exact "
    "model, null unless you are sure. carbon = the model has a carbon plate. category: racing = race shoes "
    "(often carbon-plated), cushioned = max-cushion trainers, minimal = barefoot / minimalist, track = spikes. "
    "If the photo shows no shoe, is_shoe = false and the rest null. Never invent a model."
)


def throttle(rid: str) -> bool:
    now = time.time()
    xs = [t for t in _CALLS.get(rid, []) if now - t < 3600]
    if len(xs) >= RATE_PER_HOUR:
        _CALLS[rid] = xs
        return False
    _CALLS[rid] = xs + [now]
    return True


def check_image(data_url: str) -> str | None:
    """The data URL when it is a plausible image of a sane size, else None."""
    if not isinstance(data_url, str) or len(data_url) > MAX_IMAGE_BYTES * 4 // 3 + 100:
        return None
    m = _IMG_RE.match(data_url.strip())
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except ValueError:
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    if not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[8:12] == b"WEBP"):
        return None
    return data_url.strip()


def _json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 1) if lo <= x <= hi else None


def brand_name(b) -> str | None:
    if not b or not isinstance(b, str):
        return None
    key = re.sub(r"[^a-z0-9]", "", b.lower())
    return _BRAND_KEY.get(key) or b.strip()[:40]


def model_name(m, brand) -> str | None:
    if not m or not isinstance(m, str):
        return None
    m = re.sub(r"\s+", " ", m).strip()
    if brand and m.lower().startswith(brand.lower() + " "):
        m = m[len(brand) + 1:]
    return m[:60] or None


def standardise(raw: dict) -> dict:
    """The model's answer → {brand, model, category, drop_mm, stack_mm, carbon, confidence}."""
    brand = brand_name(raw.get("brand"))
    cat = str(raw.get("category") or "").lower().strip()
    cat = cat if cat in CATEGORIES else None
    drop = _num(raw.get("drop_mm"), 0, 16)
    stack = _num(raw.get("stack_mm"), 5, 60)
    carbon = raw.get("carbon") if isinstance(raw.get("carbon"), bool) else None
    if brand in ZERO_DROP:
        drop = 0.0
    if brand in BAREFOOT:
        cat = "minimal"
    if carbon and cat is None:
        cat = "racing"
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        conf = None
    model = model_name(raw.get("model"), brand)
    if model and not re.search(r"\d", model) and brand not in ZERO_DROP:
        # the model line without its version: drop and stack change between versions, so
        # they are left for the runner, and the suggestion can't be sure
        drop, stack = None, None
        conf = min(conf, 0.5) if conf is not None else 0.5
    return {"brand": brand, "model": model, "category": cat, "drop_mm": drop,
            "stack_mm": stack, "carbon": bool(carbon) if carbon is not None else False,
            "confidence": round(conf, 2) if conf is not None else None}


def recognise(data_url: str) -> dict:
    """{ok, suggestion|None, error|None, model} — never raises."""
    if not llm.available():
        return {"ok": False, "error": "unavailable", "suggestion": None}
    text, model = llm.vision(PROMPT, data_url)
    raw = _json(text or "")
    if raw is None:
        return {"ok": False, "error": "failed", "suggestion": None}
    if raw.get("is_shoe") is False:
        return {"ok": False, "error": "no_shoe", "suggestion": None, "model": model}
    sug = standardise(raw)
    if not sug["brand"] and not sug["model"]:
        return {"ok": False, "error": "unknown", "suggestion": sug, "model": model}
    return {"ok": True, "suggestion": sug, "model": model, "error": None}


def clean_fields(body: dict) -> dict:
    """A shoe from the form (after the suggestion was confirmed / edited)."""
    brand = brand_name(body.get("brand"))
    model = model_name(body.get("model"), brand)
    cat = str(body.get("category") or "").lower() or None
    cat = cat if cat in CATEGORIES else None
    drop = _num(body.get("drop_mm"), 0, 16)
    if brand in ZERO_DROP and drop is None:
        drop = 0.0
    if brand in BAREFOOT and cat is None:
        cat = "minimal"
    return {"brand": brand, "model": model, "category": cat, "drop_mm": drop,
            "stack_mm": _num(body.get("stack_mm"), 5, 60), "carbon": bool(body.get("carbon"))}
