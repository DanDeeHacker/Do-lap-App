"""Intent and data selection for the Physio AI Assistant (implementation plan,
retrieval section). Rules, not a model: the question and an optional "Why?"
context decide which runner-data slices go to the model and which topics boost
the evidence cards. A question with no recognisable intent gets a compact
default (today, readiness, load)."""
import re
from datetime import timedelta

from ..metrics import engine as E
from .knowledge import card_by_id, fold

INTENTS = {
    "today": r"\bdnes\w*|\bted\b|\bzitr\w*|mam (dnes )?bezet|muzu (dnes |si )?(dat|bezet|zabehnout)|interval\w*|tempov\w*|"
             r"dnesni trenink|jaky trenink|co (mam|si dat)|volno|regeneracni",
    "readiness": r"pripraven\w*|regener\w*|\bhrv\b|variabil\w*|klidov\w*|spal\w*|spanek|spank\w*|nevyspal\w*|unav\w*|"
                 r"vycerpan\w*|stres\w*",
    "load": r"zatez\w*|kapacit\w*|objem\w*|kilometr\w*|\bkm\b|skok\w*|narust\w*|navys\w*|pretiz\w*|odlehc\w*|acwr|pomer",
    "pain": r"\bbol\w*|zranen\w*|holen\w*|kolen\w*|achill\w*|slach\w*|\bkost\w*|\bzad\b|zada|zadech|kotnik\w*|chodid\w*|nart\w*|"
            r"\bpat[ayu]\b|kycl\w*|kycel|lytk\w*|kulh\w*|natazen\w*|zanet\w*|tendin\w*|fyzio\w*",
    "run": r"vcer\w*|posledn\w* beh|dlouh\w* beh|minul\w* beh|dnesni beh|ten beh|muj beh|beh z|"
           r"\b(bezel|bezela|bezeli|bezelo|zabehl\w*|odbehl\w*|ubehl\w*)\b",
    "plan": r"\bplan\w*|pristi tyden|tento tyden|zavod\w*|maraton\w*|pulmaraton\w*|ladeni|priprav[aeuy]\b|cyklus|periodiz\w*",
    "strength": r"posil\w*|silov\w*|cvik\w*|\bkolo\b|\bkole\b|plav\w*|jiny sport|cross",
    "heat": r"horko|horku|vedr\w*|tepl[oe]|horc\w*|\bhydrat\w*|\bpit\b|pitny",
    "mechanics": r"techni\w*|kadenc\w*|\bkrok\w*|drift|mechanik\w*|kontakt\w*|vertikal\w*|oscil\w*|vyvazen\w*|dopad\w*",
    "app": r"kde (najdu|je|se|mam)|jak (zapnu|vypnu|pripojim|nastavim|zadam|zapisu|smazu|vyradim)|zalozk\w*|aplikac\w*|garmin|"
           r"apple|synchron\w*|check.?in|kvadrant\w*|co znamena|co je to|jak funguje|asistent",
}
_RX = {k: re.compile(v) for k, v in INTENTS.items()}
# "where do I find / how do I …" — a navigation question: the app guide answers it alone
_NAV = re.compile(r"^\W*(kde (v aplikaci |v appce )?(najdu|je|se|mam|vidim|zjistim)|jak (v aplikaci )?(zapnu|vypnu|pripojim|nastavim|zadam|zapisu|smazu|vyradim|"
                  r"najdu|zmenim|upravim))\b")

TOPICS = {
    "today": ["intensity", "hard", "easy", "planning"],
    "readiness": ["readiness", "hrv", "sleep", "checkin", "fatigue", "stress"],
    "load": ["load", "capacity", "progression", "spike"],
    "pain": ["pain"],
    "run": ["heart_rate", "terrain"],
    "plan": ["planning", "race", "progression", "taper"],
    "strength": ["strength", "cross_training"],
    "heat": ["heat", "hydration"],
    "mechanics": ["mechanics", "technique", "cadence"],
    "app": [],
}
SLICES = {
    "today": ["today", "types"], "readiness": ["readiness"], "load": ["load"], "pain": ["pain"],
    "run": ["runs"], "plan": ["plan", "load"], "strength": ["strength", "types"], "heat": ["heat", "runs"],
    "mechanics": ["mechanics"], "app": [],
}
_PAIN_SUB = [
    (re.compile(r"holen\w*|chodid\w*|nart\w*|\bpat[ayu]\b|metatar\w*|kost\w*"), ["bone", "shin", "foot"]),
    (re.compile(r"achill\w*|slach\w*|tendin\w*"), ["tendon"]),
    (re.compile(r"\bzad\b|zada|zadech|bedr\w*|pater\w*"), ["back"]),
    (re.compile(r"navrat\w*|po zraneni"), ["return"]),
]
_WD = {"pondeli": 0, "utery": 1, "stredu": 2, "ctvrtek": 3, "patek": 4, "sobotu": 5, "nedeli": 6}
_TYPE_RX = [(re.compile(r"interval\w*|tempov\w*|kvalitn\w*|tvrd\w* trenink"), "kvalitní"), (re.compile(r"dlouh\w* beh"), "dlouhý"),
            (re.compile(r"posil\w*|silov\w*"), "posilování"), (re.compile(r"\bkol[oe]\b"), "kolo"), (re.compile(r"plav\w*"), "voda")]
CONTEXT_KINDS = ("guidance", "type", "signal", "readiness", "run", "summary", "card", "tab")
# A question asked from a tab is about that tab unless it names its own subject.
TAB_INTENTS = {
    "today": ["today", "readiness", "load", "mechanics", "pain"],
    "training": ["today", "plan"],
    "load": ["load", "readiness"],
    "mechanics": ["mechanics"],
    "post": ["run", "pain"],
    "messages": ["pain"],
}


def classify(question: str, context: dict | None = None) -> dict:
    """{intents, topics, slices, signals, wantGuide, runDay, runPick, context}."""
    t = fold(question)
    intents = [k for k, rx in _RX.items() if rx.search(t)]
    ctx = context if isinstance(context, dict) and context.get("kind") in CONTEXT_KINDS else None
    tab = str(ctx.get("id")) if ctx and ctx.get("kind") == "tab" else None
    if tab is not None:
        # the tab only sets the default focus: a navigation question or one with its
        # own subject keeps it, a vague one ("co s tím?") is about what's on screen
        if not intents:
            intents = list(TAB_INTENTS.get(tab, []))
        elif intents == ["app"] and not _NAV.search(t):     # "co znamená tohle?" — the guide and what's on screen
            intents = ["app"] + TAB_INTENTS.get(tab, [])
        ctx = None
    signals = []
    if ctx:
        kind = ctx["kind"]
        if kind in ("guidance", "type"):
            intents.append("today")
        elif kind == "readiness":
            intents.append("readiness")
        elif kind == "run":
            intents.append("run")
        elif kind == "signal" and ctx.get("id"):
            signals.append(str(ctx["id"]))
            intents.append("load")
        elif kind == "summary":
            intents += ["today", "readiness"]
    intents = list(dict.fromkeys(intents))
    if _NAV.search(t) and not ctx:
        intents = ["app"]
    if not intents:
        intents = ["today", "readiness", "load"]
    # a specific subject (heat, pain, strength …) decides the evidence; "today"
    # only adds the day's data, not its generic intensity topics
    specific = {"pain", "heat", "strength", "mechanics", "plan", "run"} & set(intents)
    topics = []
    for i in intents:
        if not (specific and i == "today"):
            topics += TOPICS[i]
    if "pain" in intents:
        for rx, extra in _PAIN_SUB:
            if rx.search(t):
                topics += extra
    if ctx and ctx.get("kind") == "card" and card_by_id().get(str(ctx.get("id"))):
        topics += (card_by_id()[str(ctx["id"])].get("applies") or {}).get("topics") or []
    slices = []
    for i in intents:
        slices += SLICES[i]
    slices = list(dict.fromkeys(["state"] + slices))
    run_day, run_pick = None, None
    if "run" in intents:
        today = E.today_date()
        if re.search(r"vcer\w*", t):
            run_day = (today - timedelta(days=1)).isoformat()
        elif re.search(r"dnesni beh|dnes jsem (bezel|bezela|bezeli)", t):
            run_day = today.isoformat()
        else:
            m = re.search(r"\bv (pondeli|utery|stredu|ctvrtek|patek|sobotu|nedeli)\b", t)
            if m:
                back = (today.weekday() - _WD[m.group(1)]) % 7 or 7
                run_day = (today - timedelta(days=back)).isoformat()
        if re.search(r"dlouh\w* beh", t):
            run_pick = "long"
        if ctx and ctx.get("kind") == "run" and ctx.get("id"):
            run_pick = f"id:{ctx['id']}"
    asked_type = str(ctx["id"]) if ctx and ctx.get("kind") == "type" and ctx.get("id") else None
    if asked_type is None and "today" in intents:
        asked_type = next((k for rx, k in _TYPE_RX if rx.search(t)), None)
    return {"intents": intents, "topics": list(dict.fromkeys(topics)), "slices": slices, "signals": signals,
            "wantGuide": "app" in intents, "runDay": run_day, "runPick": run_pick, "context": ctx, "askedType": asked_type}
