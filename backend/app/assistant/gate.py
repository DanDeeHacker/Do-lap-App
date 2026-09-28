"""Safety gate of the Physio AI Assistant: questions that must never depend on a
model get a fixed, reviewed reply (implementation plan, safety section).

The patterns run on diacritic-free lowercase text and err towards triggering:
a false alarm costs one unnecessary sentence, a miss could cost much more.
"""
import re

from .knowledge import fold

EMERGENCY = "155"      # Czech medical emergency number (112 = EU general emergency)
CRISIS_LINE = "116 123"  # Linka první psychické pomoci

_RULES = [
    ("cauda", re.compile(
        r"(nemuzu|nejde|neumim|problem\w*|zmen\w*|ztrat\w*|potiz\w*)\W+(\w+\W+){0,3}(mocit|moceni|mocem|stolic\w*|vyprazd\w*)|"
        r"inkontinen\w*|necitliv\w*\W+(\w+\W+){0,3}(rozkrok\w*|trisl\w*|genital\w*|konecnik\w*|hyzd\w*)|"
        r"(brni|brneni|mravenceni)\W+(\w+\W+){0,3}(rozkrok\w*|genital\w*)"),
     "Změna močení nebo stolice nebo necitlivost v oblasti rozkroku patří k příznakům, které vyžadují okamžité "
     "lékařské vyšetření. Prosím, nečekejte a vyhledejte pohotovost nebo volejte " + EMERGENCY + " (případně 112). "
     "Tréninková doporučení jsou do vyšetření pozastavená."),
    ("chest", re.compile(
        r"bolest\w*\W+(\w+\W+){0,2}(na\W+|v\W+)?hrud\w*|tlak\w*\W+(\w+\W+){0,2}hrud\w*|omdl\w*|kolaps\w*|bezvedom\w*|"
        r"(nemohl\w*|nemuzu|nemuze\w*)\W+(\w+\W+){0,2}dychat|nepravideln\w*\W+(\w+\W+){0,2}(tep|srdc)\w*|bus\w* srdce"),
     "Bolest na hrudi, mdloba nebo výrazná dušnost při běhu jsou důvod přestat a vyhledat lékařskou pomoc hned, "
     "při akutních potížích volejte " + EMERGENCY + " (případně 112). Do vyšetření prosím netrénujte."),
    ("acute_injury", re.compile(
        r"\b(luplo|lup\w*|prasklo|praskl\w*|kruplo|rupnuti)\b.{0,40}(bol\w*|koleno|kotnik|noha|lytko|slach\w*)|"
        r"(nemuzu|nedokazu|nejde)\W+(\w+\W+){0,3}(doslapnout|stoupnout|postavit|chodit|nest vahu)|deformac\w*|"
        r"otok\w*\W+(\w+\W+){0,3}(nejde|nemuzu)"),
     "Když při běhu něco lupne nebo prasklo, nebo se nemůžete postavit na nohu či ji zatížit, nechte to co nejdřív "
     "vyšetřit lékařem (úrazová pohotovost). Do vyšetření nohu nezatěžujte a nebězte."),
    ("self_harm", re.compile(
        r"sebevra\w*|zabit se|zabiju se|nechci (uz )?zit|ublizit si|ublizim si|sebeposkoz\w*|skoncovat se (zivotem|sebou)"),
     "Je mi líto, že je vám tak těžko. S tím vám tady neporadím, ale nemusíte na to být sami: zavolejte Linku první "
     "psychické pomoci " + CRISIS_LINE + " (nonstop, zdarma), a pokud jste v ohrožení, volejte " + EMERGENCY + " nebo 112."),
]


def check(question: str) -> dict | None:
    """{kind, reply} when the question must get a fixed reply, else None."""
    t = fold(question)
    for kind, pat, reply in _RULES:
        if pat.search(t):
            return {"kind": kind, "reply": reply}
    return None


def engine_block(a: dict) -> dict | None:
    """The engine's own red-flag state stops the chat too (the screening answers
    in the check-in, Finucane et al., 2020)."""
    scr = (a or {}).get("screening") or {}
    rf = scr.get("redFlag")
    if not rf:
        return None
    g = (a or {}).get("guidance") or {}
    ov = g.get("override") or {}
    text = ov.get("text") if ov.get("kind") == "red_flag" else None
    return {"kind": "red_flag", "reply": (text or "V check-inu jste uvedli varovné příznaky u bolesti zad.")
            + " Dokud vás nevyšetří lékař, tréninkové rady nedávám. Pokud už jste vyšetření měli, upravte prosím "
              "odpovědi v dalším check-inu."}


OFF_TOPIC_REPLY = ("S tím vám neporadím. Pomůžu s vašimi daty z běhu, dnešním tréninkem a plánováním, zátěží, "
                   "bolestí a zotavením, technikou a s tím, kde co v aplikaci najdete.")
LIMIT_REPLY = ("Pro dnešek jste vyčerpali počet otázek pro asistenta. Zítra se můžete ptát znovu, a doporučení "
               "na dnešek najdete v záložce Trénink.")
CONSENT_REPLY = ("Asistent potřebuje váš souhlas se zpracováním dat AI. Zapnete ho v Data a připojení v části AI texty.")
