"""Exercise library — rehab and conditioning exercises for running injuries,
each tagged with what it treats (clinical indication) and what it targets
(muscle/structure it trains). Used two ways: `lib_for(site)` auto-picks a
starter set for a new program (unchanged behaviour, used by seed.py and the
draftProgram endpoint); `search()`/`by_category()` back a browsable library
so a physio can add any exercise to a program, not just the auto-picked
ones (see routers/exercise_library.py).
"""

CATEGORIES = {
    "achilles": "Achillova šlacha a lýtko",
    "knee": "Koleno",
    "shin": "Holeň a bérec",
    "foot": "Chodidlo a plantární fascie",
    "hip": "Kyčel a hýždě",
    "hamstring": "Hamstring a zadní řetězec",
    "itband": "IT band a laterální koleno",
    "core": "Trup a pánevní stabilita",
    "conditioning": "Obecná kondice a síla",
    "mobility": "Mobilita",
}

# (id, name, category, dose, per_week, cue, treats[], targets[], level)
# level: "rehab" (dávkuje se podle bolesti, nižší zátěž) | "strength" (běžný silový trénink)
_RAW = [
    ("ach-ecc-heel-drop", "Excentrické výpony na schodu", "achilles", "3 × 15 / noha", 5,
     "Spouštěj 3 vteřiny dolů, bolest do 3/10.",
     ["Achillova tendinopatie", "Achillova šlacha"], ["m. triceps surae", "Achillova šlacha"], "rehab"),
    ("ach-iso-plantar", "Izometrická výdrž v plantární flexi", "achilles", "5 × 45 s", 4,
     "Drž tah, ne bolest.",
     ["Achillova tendinopatie — akutní fáze"], ["Achillova šlacha", "m. soleus"], "rehab"),
    ("ach-soleus-bent", "Soleus výpon s pokrčeným kolenem", "achilles", "3 × 12", 4,
     "Koleno v 30°, cílí hluboký lýtkový sval.",
     ["Achillova tendinopatie", "insercní bolest paty"], ["m. soleus"], "rehab"),
    ("ach-straight-heel-raise", "Výpony na rovné noze", "achilles", "4 × 15", 3,
     "Plný rozsah, nahoře krátká výdrž.",
     ["prevence Achillovy tendinopatie"], ["m. gastrocnemius", "Achillova šlacha"], "strength"),
    ("ach-jump-rope", "Poskoky přes švihadlo, nízké", "achilles", "3 × 30 s", 2,
     "Krátký kontakt se zemí, měkké přistání.",
     ["návrat k běhu po Achillově tendinopatii"], ["Achillova šlacha", "reaktivní síla lýtka"], "strength"),

    ("shin-heel-walk", "Chůze po patách", "shin", "3 × 40 m", 4,
     "Aktivace předního bérce.",
     ["stresová reakce holenní kosti", "mediální tibiální stresový syndrom"], ["m. tibialis anterior"], "rehab"),
    ("shin-paused-raise", "Výpony s pauzou", "shin", "4 × 12", 4,
     "Pauza 2 s nahoře.",
     ["stresová reakce holenní kosti"], ["m. triceps surae", "kostní adaptace tibie"], "rehab"),
    ("shin-cadence-drill", "Kadence drill 175–180", "shin", "2 × 6 min", 2,
     "Kratší krok, vyšší frekvence.",
     ["přetížení holeně z dlouhého kroku"], ["technika běhu, zkrácení kroku"], "strength"),
    ("shin-toe-raise-resisted", "Dorzální flexe s odporovou gumou", "shin", "3 × 15 / noha", 4,
     "Pomalu, plný rozsah.",
     ["mediální tibiální stresový syndrom", "shin splints"], ["m. tibialis anterior"], "rehab"),

    ("foot-short-foot", "Short foot cvičení", "foot", "3 × 12", 5,
     "Aktivní klenba, prsty uvolněné.",
     ["plantární fasciitida", "propadlá klenba"], ["mm. intrinseci nohy"], "rehab"),
    ("foot-ball-roll", "Roll na míčku", "foot", "2 × 3 min", 6,
     "Ráno před prvním krokem.",
     ["plantární fasciitida — ranní bolest"], ["plantární fascie"], "rehab"),
    ("foot-towel-curl", "Výpony s ručníkem pod prsty", "foot", "3 × 15", 4,
     "Zvyšuje tah plantární fascie.",
     ["plantární fasciitida"], ["plantární fascie", "flexory prstů"], "rehab"),
    ("foot-calf-stretch-wall", "Protažení lýtka o zeď, koleno propnuté i pokrčené", "foot", "3 × 30 s / poloha", 5,
     "Bez odrazu, statický tah.",
     ["plantární fasciitida — přidružené zkrácení lýtka"], ["m. gastrocnemius", "m. soleus"], "mobility"),

    ("knee-bulgarian-split", "Bulharský dřep", "knee", "3 × 10 / noha", 3,
     "Koleno nad špičkou, klid v pánvi.",
     ["patelofemorální bolest", "obecná síla dolní končetiny"], ["m. quadriceps", "m. gluteus maximus"], "strength"),
    ("knee-copenhagen", "Copenhagen plank", "knee", "3 × 20 s", 3,
     "Nezvedej bok.",
     ["prevence tříselných a adduktorových potíží"], ["adduktory", "pánevní stabilita"], "strength"),
    ("knee-step-down", "Step-down z bedny", "knee", "3 × 12", 3,
     "Sleduj propad kolena dovnitř.",
     ["patelofemorální bolest"], ["m. quadriceps", "kontrola valgozity kolena"], "rehab"),
    ("knee-wall-sit", "Výdrž ve dřepu o zeď", "knee", "3 × 40 s", 3,
     "Kolena v 60°, netlač do bolesti.",
     ["patelofemorální bolest — časná fáze"], ["m. quadriceps (izometricky)"], "rehab"),
    ("knee-terminal-extension", "Terminální extenze kolena s gumou", "knee", "3 × 15 / noha", 4,
     "Poslední 20° extenze, pomalu.",
     ["patelofemorální bolest", "po artroskopii"], ["m. vastus medialis"], "rehab"),

    ("itb-clamshell", "Clamshell s gumou", "itband", "3 × 15 / noha", 4,
     "Pánev nehýbat, pohyb jen v kyčli.",
     ["IT band syndrom", "slabost gluteus medius"], ["m. gluteus medius"], "rehab"),
    ("itb-side-plank-abd", "Side plank s abdukcí", "itband", "3 × 12", 3,
     "Gluteus medius, klíčový pro běh.",
     ["IT band syndrom", "laterální koleno"], ["m. gluteus medius", "boční trup"], "strength"),
    ("itb-monster-walk", "Monster walk s minibandem", "itband", "3 × 10 kroků", 3,
     "Kolena mírně pokrčená, malé kroky do stran.",
     ["IT band syndrom"], ["m. gluteus medius", "m. gluteus minimus"], "rehab"),
    ("itb-foam-roll", "Foam rolling laterálního stehna", "itband", "2 × 60 s", 4,
     "Tlak do nepohodlí, ne do ostré bolesti.",
     ["IT band syndrom — akutní podráždění"], ["fascia lata, m. tensor fasciae latae"], "mobility"),

    ("hip-single-leg-rdl", "Single-leg deadlift", "hip", "3 × 10 / noha", 3,
     "Pánev vodorovně, tah v hamstringu.",
     ["obecná stabilita pánve", "prevence zranění hamstringu"], ["m. gluteus maximus", "hamstring", "rovnováha"], "strength"),
    ("hip-glute-bridge", "Glute bridge na jedné noze", "hip", "3 × 12 / noha", 4,
     "Nahoře krátká výdrž, bez prohnutí zad.",
     ["slabost hýžďového svalstva", "bolest dolní části zad při běhu"], ["m. gluteus maximus"], "strength"),
    ("hip-lateral-band-walk", "Boční chůze s minibandem", "hip", "3 × 10 kroků / stranu", 4,
     "Nízký dřep, kontrolovaný pohyb.",
     ["slabost abduktorů kyčle"], ["m. gluteus medius"], "rehab"),
    ("hip-hip-flexor-stretch", "Protažení flexorů kyčle v kleku", "hip", "3 × 30 s / noha", 5,
     "Pánev podsadit, tah vpředu na stehně.",
     ["zkrácení flexorů kyčle u sedavého zaměstnání"], ["m. iliopsoas"], "mobility"),

    ("ham-nordic-curl", "Nordická flexe (Nordic curl)", "hamstring", "3 × 6", 2,
     "Kontrolovaný sestup, pomoz si rukama na konci.",
     ["prevence natažení hamstringu", "po zranění hamstringu"], ["hamstring (excentricky)"], "strength"),
    ("ham-single-leg-bridge", "Glute-ham bridge na jedné noze", "hamstring", "3 × 10 / noha", 4,
     "Pata na podložce, zvedej pánev.",
     ["rehabilitace hamstringu"], ["hamstring", "m. gluteus maximus"], "rehab"),
    ("ham-good-morning", "Good morning s vlastní vahou", "hamstring", "3 × 12", 3,
     "Záda rovná, pohyb z kyčle.",
     ["obecná síla zadního řetězce"], ["hamstring", "vzpřimovače trupu"], "strength"),

    ("core-side-plank", "Boční plank", "core", "3 × 30 s / strana", 4,
     "Rovná linie od ramene po kotník.",
     ["nestabilita trupu při únavě", "kompenzační bolest zad"], ["boční trup, m. quadratus lumborum"], "strength"),
    ("core-dead-bug", "Dead bug", "core", "3 × 10 / stranu", 4,
     "Bederní páteř přitisknutá k zemi.",
     ["nízká pánevní stabilita"], ["hluboký stabilizační systém trupu"], "rehab"),
    ("core-pallof-press", "Pallof press s gumou", "core", "3 × 12 / stranu", 3,
     "Odolávej rotaci trupu.",
     ["rotační nestabilita trupu při běhu"], ["šikmé břišní svaly, anti-rotační stabilita"], "strength"),

    ("cond-calf-raise-general", "Výpony", "conditioning", "3 × 15", 3,
     "Tolerance zátěže lýtka.",
     ["obecná prevence přetížení lýtka"], ["m. triceps surae"], "strength"),
    ("cond-squat", "Dřep s vlastní vahou", "conditioning", "3 × 12", 2,
     "Kolena ve směru špiček, záda rovná.",
     ["obecná síla dolních končetin"], ["m. quadriceps", "m. gluteus maximus"], "strength"),
    ("cond-lunge", "Výpady vpřed", "conditioning", "3 × 10 / noha", 2,
     "Koleno se nedotýká země, kontrolovaný návrat.",
     ["obecná síla a rovnováha"], ["m. quadriceps", "m. gluteus maximus", "rovnováha"], "strength"),
    ("cond-single-leg-balance", "Výdrž na jedné noze", "conditioning", "3 × 30 s / noha", 5,
     "Oči nejdřív otevřené, pak zavřené.",
     ["propriocepce po zranění kotníku", "obecná stabilita"], ["proprioceptivní kontrola kotníku"], "rehab"),
    ("cond-plyo-pogo", "Pogo skoky", "conditioning", "3 × 20", 2,
     "Krátký kontakt se zemí, jako na horké podlaze.",
     ["reaktivní síla před návratem k rychlejšímu běhu"], ["reaktivní síla lýtka a Achillovy šlachy"], "strength"),

    ("mob-hip-90-90", "Mobilita kyčle 90/90", "mobility", "3 × 8 přechodů", 4,
     "Pomalu, hruď zůstává vzpřímená.",
     ["omezená rotace kyčle"], ["rozsah pohybu kyčle"], "mobility"),
    ("mob-thoracic-rotation", "Rotace hrudní páteře v kleku", "mobility", "3 × 10 / stranu", 4,
     "Pánev zůstává fixovaná.",
     ["omezená rotace trupu při běhu"], ["rozsah pohybu hrudní páteře"], "mobility"),
]

EXERCISE_LIBRARY = [
    {
        "id": r[0], "name": r[1], "category": r[2], "dose": r[3], "per_week": r[4], "cue": r[5],
        "treats": r[6], "targets": r[7], "level": r[8],
    }
    for r in _RAW
]
_BY_ID = {e["id"]: e for e in EXERCISE_LIBRARY}

# Legacy tuple shape (name, dose, per_week, cue), grouped by the same site
# keywords lib_for() has always matched on — kept so seed.py's demo program
# and draftProgram's auto-pick behave exactly as before.
EXLIB = {}
for _e in EXERCISE_LIBRARY:
    EXLIB.setdefault(_e["category"], []).append((_e["name"], _e["dose"], _e["per_week"], _e["cue"]))
EXLIB["gen"] = EXLIB["conditioning"]


def lib_for(site: str | None):
    if not site:
        return EXLIB["gen"]
    t = site.lower()
    if "achill" in t:
        return EXLIB["achilles"]
    if "kolen" in t or "band" in t:
        return EXLIB["knee"] if "band" not in t else EXLIB["itband"]
    if "holeň" in t or "lýtk" in t or "tibi" in t:
        return EXLIB["shin"]
    if "chodid" in t or "plantár" in t:
        return EXLIB["foot"]
    if "hamstring" in t or "zadní stehna" in t:
        return EXLIB["hamstring"]
    if "kyčel" in t or "hýžď" in t or "gluteus" in t:
        return EXLIB["hip"]
    return EXLIB["gen"]


def by_category(category: str):
    return [e for e in EXERCISE_LIBRARY if e["category"] == category]


def search(query: str):
    q = (query or "").strip().lower()
    if not q:
        return EXERCISE_LIBRARY
    def hit(e):
        haystack = " ".join([e["name"], e["category"], *e["treats"], *e["targets"]]).lower()
        return q in haystack
    return [e for e in EXERCISE_LIBRARY if hit(e)]


def get(exercise_id: str):
    return _BY_ID.get(exercise_id)
