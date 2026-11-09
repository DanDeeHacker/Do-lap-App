"""One vocabulary of body regions for visit records, injuries, programmes and the body map
(physio brief 2026-11-09 P0.5). Codes are English, labels Czech."""
REGIONS = [
    ("achilles", "Achillova šlacha"),
    ("calf", "Lýtko"),
    ("plantar", "Plantární fascie (pata)"),
    ("knee_anterior", "Koleno vpředu"),
    ("itband", "IT pás a vnější strana kolena"),
    ("shin", "Holeň"),
    ("hamstring", "Zadní strana stehna"),
    ("hip", "Kyčel a hýždě"),
    ("groin", "Tříslo (adduktory)"),
    ("lower_abdomen", "Dolní břicho"),
    ("other", "Jiné (upřesněte)"),
]
LABEL = dict(REGIONS)

# the exercise library's categories and the check-in sites, mapped onto the same codes
CATEGORY_TO_REGION = {"achilles": "achilles", "knee": "knee_anterior", "shin": "shin", "foot": "plantar",
                      "hip": "hip", "hamstring": "hamstring", "itband": "itband"}
_SITE_WORDS = [("achill", "achilles"), ("lýtk", "calf"), ("plant", "plantar"), ("pat", "plantar"),
               ("kolen", "knee_anterior"), ("čéšk", "knee_anterior"), ("it pás", "itband"), ("holen", "shin"),
               ("zadní stran", "hamstring"), ("hamstring", "hamstring"), ("kyč", "hip"), ("hýžď", "hip"),
               ("třísl", "groin"), ("addukt", "groin"), ("břich", "lower_abdomen")]


def region_for_site(site: str | None) -> str | None:
    """A check-in pain site or a free-text region (e.g. "Achillova šlacha (L)") → a region code."""
    s = (site or "").lower()
    if s in LABEL:
        return s
    return next((code for word, code in _SITE_WORDS if word in s), "other" if s else None)


def label(code: str | None) -> str | None:
    return LABEL.get(code or "", code)
