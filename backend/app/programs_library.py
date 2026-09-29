"""Feedback railway#116 — ready-made exercise programs for the most common running
problems, which the runner can start on their own, and the exercise library a runner
builds their own session from.

No free exercise database fits a commercial physio product as it is: free-exercise-db
(Unlicense) covers gym exercises and its images have no known licence, wger data are
Creative Commons per entry and mostly gym exercises, Physiopedia is non-commercial. So
the exercises and the programs are written here, from published protocols, each with its
source. Doses that no source fixes are the product team's working assumptions and are
marked as such (`assumption`). The programs are for self-management of mild complaints,
not a replacement for an examination; they wait for review by a Došlap physiotherapist
(`reviewed` = False until then).

Pain rule for every program: pain up to 5/10 during an exercise is acceptable, it must
settle by the next morning and must not grow from week to week (Silbernagel et al.,
2007); bone pain follows the complete absence of pain instead (Warden et al., 2014).
"""

PAIN_RULE = ("Bolest při cvičení do 5 z 10 je v pořádku, do druhého rána musí odeznít a nesmí týden od týdne růst. "
             "Když roste nebo je ráno horší, uberte počet opakování.")

# id → exercise. `how` = execution in two or three short sentences, `dose` = default dose.
EXERCISES = {
    "heel_raise_2": {"name": "Výpony na obou nohách", "area": "lýtko a Achillova šlacha",
                     "how": "Stoupněte si na špičky plynule nahoru a pomalu dolů, kolena propnutá. Držte se lehce zdi.",
                     "dose": "3 × 15", "perWeek": 7},
    "heel_raise_1": {"name": "Výpony na jedné noze", "area": "lýtko a Achillova šlacha",
                     "how": "Na jedné noze nahoru za 2 s, nahoře krátká výdrž, dolů za 3 s. Postupně přidejte batoh se zátěží.",
                     "dose": "3 × 15", "perWeek": 7},
    "ecc_straight": {"name": "Spouštění paty ze schodu, propnuté koleno", "area": "Achillova šlacha",
                     "how": "Na hraně schodu se zvedněte na obou nohách, pak se pomalu spouštějte jen na bolavé noze pod úroveň schodu. Nahoru zase oběma.",
                     "dose": "3 × 15, 2× denně", "perWeek": 14},
    "ecc_bent": {"name": "Spouštění paty ze schodu, pokrčené koleno", "area": "Achillova šlacha a soleus",
                 "how": "Stejně jako se spouštěním paty, jen s mírně pokrčeným kolenem, aby pracoval hlubší lýtkový sval.",
                 "dose": "3 × 15, 2× denně", "perWeek": 14},
    "seated_calf": {"name": "Výpony vsedě se zátěží", "area": "soleus (hluboké lýtko)",
                    "how": "Vsedě s koleny v pravém úhlu a se zátěží na stehnech zvedejte paty. Pomalu nahoru i dolů.",
                    "dose": "3 × 12", "perWeek": 3},
    "hops": {"name": "Poskoky na místě", "area": "lýtko a šlacha, pružnost",
             "how": "Lehké rytmické poskoky na obou nohách, později na jedné. Jen když při výponech nic nebolí.",
             "dose": "3 × 20 s", "perWeek": 3},
    "towel_raise": {"name": "Výpon na jedné noze s ručníkem pod prsty", "area": "plantární fascie",
                    "how": "Srolovaný ručník pod prsty, aby byly zvednuté. Nahoru 3 s, nahoře 2 s výdrž, dolů 3 s. Zátěž přidejte batohem.",
                    "dose": "3 × 12 (max. zátěž na 12 opakování)", "perWeek": 3},
    "side_abd": {"name": "Unožování vleže na boku", "area": "hýžďové svaly (abduktory kyčle)",
                 "how": "Vleže na boku zvedněte horní propnutou nohu mírně za tělo, špička dopředu. Pomalu dolů.",
                 "dose": "3 × 15", "perWeek": 4},
    "clamshell": {"name": "Mušle", "area": "hýžďové svaly",
                  "how": "Vleže na boku s pokrčenými koleny a spojenými chodidly otvírejte horní koleno, pánev se neotáčí. Zesílíte gumou.",
                  "dose": "3 × 15", "perWeek": 4},
    "bridge": {"name": "Most", "area": "hýždě a zadní strana stehen",
               "how": "Vleže na zádech s pokrčenými koleny zvedněte pánev do přímky, nahoře 2 s výdrž. Pokročile na jedné noze.",
               "dose": "3 × 12", "perWeek": 4},
    "wall_squat": {"name": "Dřep u zdi", "area": "kvadriceps",
                   "how": "Zády u zdi sjeďte do hloubky, která nebolí, a vydržte. Kolena míří nad špičky.",
                   "dose": "5 × 30 s", "perWeek": 4},
    "step_up": {"name": "Výstup na schod", "area": "kvadriceps a hýždě",
                "how": "Vystupte na schod jednou nohou a pomalu sestupte zpět. Koleno nepadá dovnitř, pánev zůstává rovně.",
                "dose": "3 × 10 každá noha", "perWeek": 3},
    "knee_ext": {"name": "Předkopávání vsedě", "area": "kvadriceps",
                 "how": "Vsedě propněte koleno proti odporu gumy nebo zátěže na kotníku a pomalu povolte.",
                 "dose": "3 × 12", "perWeek": 3},
    "pelvic_drop": {"name": "Spouštění pánve na schodu", "area": "střední hýžďový sval",
                    "how": "Stůjte bokem na schodu na jedné noze, druhou nechte volně viset. Spusťte pánev na volné straně dolů a zvedněte ji zpět silou stojné kyčle.",
                    "dose": "3 × 15", "perWeek": 4},
    "sl_squat": {"name": "Dřep na jedné noze", "area": "kyčel a koleno, kontrola",
                 "how": "Pomalý mělký dřep na jedné noze před zrcadlem, koleno nad špičkou, pánev rovně.",
                 "dose": "3 × 8", "perWeek": 3},
    "toe_raise": {"name": "Zvedání špiček", "area": "přední sval holeně",
                  "how": "Zády u zdi s patami kousek od ní zvedejte špičky co nejvýš a pomalu dolů.",
                  "dose": "3 × 20", "perWeek": 4},
    "balance": {"name": "Stoj na jedné noze", "area": "kotník a stabilita",
                "how": "Stoj na jedné noze s mírně pokrčeným kolenem. Ztížíte zavřenýma očima nebo na polštáři.",
                "dose": "3 × 30 s", "perWeek": 5},
    "nordic": {"name": "Nordický hamstring", "area": "zadní strana stehen",
               "how": "Vkleče s fixovanými kotníky se pomalu naklánějte dopředu s rovnými zády, brzděte zadní stranou stehen, pak se zachyťte rukama.",
               "dose": "2–3 × 5–8", "perWeek": 2},
    "sl_rdl": {"name": "Rumunský mrtvý tah na jedné noze", "area": "hamstring a hýždě",
               "how": "Na jedné noze s mírně pokrčeným kolenem se předkloňte s rovnými zády, druhá noha jde dozadu. Zpět silou hýždě.",
               "dose": "3 × 8 každá noha", "perWeek": 2},
    "bridge_iso": {"name": "Výdrž v mostu na patách", "area": "hamstring, šetrný začátek",
                   "how": "Most s patami dál od těla, pánev nahoru a výdrž. Na začátek při bolesti zadní strany stehna.",
                   "dose": "5 × 30 s", "perWeek": 5},
}

# key → program. `match` = lower-case fragments of the body-map regions the program fits.
PROGRAMS = [
    {"key": "achilles", "name": "Achillova šlacha", "weeks": 12,
     "match": ["achill"],
     "summary": "Postupně rostoucí zátěž šlachy výpony. Běhat se může dál, když bolest drží pravidlo níže.",
     "exercises": ["heel_raise_2", "heel_raise_1", "ecc_straight", "ecc_bent", "hops"],
     "evidence": "Zatěžování šlachy s průběžným sledováním bolesti vedlo ke zlepšení a pokračování v běhu mu neuškodilo "
                 "(Silbernagel et al., 2007). Spouštění paty ze schodu 3 × 15 dvakrát denně po 12 týdnů (Alfredson et al., 1998).",
     "refs": ["Silbernagel et al., 2007", "Alfredson et al., 1998"], "assumption": "Pořadí a poskoky až v závěru jsou pracovní předpoklad."},
    {"key": "calf", "name": "Lýtko", "weeks": 6,
     "match": ["lýtk", "lytk", "gastrocnem", "soleus", "bérec"],
     "summary": "Síla lýtka propnutým i pokrčeným kolenem, na závěr pružnost poskoky.",
     "exercises": ["heel_raise_2", "heel_raise_1", "seated_calf", "hops"],
     "evidence": "Výpony vsedě, na dvou a na jedné noze a poskoky zatěžují lýtko a šlachu postupně víc, od půl násobku po sedminásobek tělesné hmotnosti "
                 "(Baxter et al., 2021).",
     "refs": ["Baxter et al., 2021"], "assumption": "Dávkování je pracovní předpoklad produktového týmu."},
    {"key": "plantar", "name": "Plantární fascie (pata)", "weeks": 12,
     "match": ["plantár", "plantar", "pata"],
     "summary": "Výpon s ručníkem pod prsty s velkou zátěží, pomalu, obden.",
     "exercises": ["towel_raise"],
     "evidence": "Výpon na jedné noze s ručníkem pod prsty obden po 3 měsíce: 3 × 12 opakování s maximální zátěží, po 2 týdnech 4 × 10, "
                 "od 5. týdne 5 × 8 (Rathleff et al., 2015). Po 3 měsících byl výsledek lepší než po samotném protahování.",
     "refs": ["Rathleff et al., 2015"], "assumption": None},
    {"key": "knee", "name": "Koleno vpředu", "weeks": 6,
     "match": ["kolen", "patel", "kvadricepsová šlacha"],
     "summary": "Posílení kyčle a kolena dohromady.",
     "exercises": ["side_abd", "clamshell", "bridge", "wall_squat", "step_up", "knee_ext"],
     "evidence": "U bolesti kolena vpředu odborný konsenzus doporučuje cvičení, nejlépe kombinaci cviků na kyčel a na koleno "
                 "(Collins et al., 2018). Kombinace ulevila od bolesti víc než samotné cviky na koleno (van der Heijden et al., 2016).",
     "refs": ["Collins et al., 2018", "van der Heijden et al., 2016"],
     "assumption": "Dávkování je pracovní předpoklad. Při bolesti přímo na šlaše pod čéškou se postup liší, poraďte se s fyzioterapeutem."},
    {"key": "itb", "name": "IT pás a vnější strana kolena", "weeks": 6,
     "match": ["iliotib", "it band", "it pás", "hýžd", "glute"],
     "summary": "Síla a vytrvalost abduktorů kyčle, kontrola pánve na jedné noze.",
     "exercises": ["side_abd", "pelvic_drop", "clamshell", "sl_squat"],
     "evidence": "Běžci s bolestí IT pásu měli slabší abduktory kyčle a po 6 týdnech jejich posilování se 22 z 24 vrátilo k běhu bez bolesti "
                 "(Fredericson et al., 2000). Posilování abduktorů je nejčastější složkou úspěšné léčby (Sanchez-Alvarado et al., 2024).",
     "refs": ["Fredericson et al., 2000", "Sanchez-Alvarado et al., 2024"], "assumption": "Dávkování je pracovní předpoklad."},
    {"key": "shin", "name": "Holeň", "weeks": 6,
     "match": ["holen", "holeň", "tibial"],
     "summary": "Úprava zátěže a postupné posílení lýtka a holeně.",
     "exercises": ["heel_raise_2", "heel_raise_1", "toe_raise", "balance"],
     "evidence": "Žádná léčba bolesti holeně zatím není spolehlivě prokázaná (Winters et al., 2013). Nejlogičtější je úprava zátěže, postupné zatěžování "
                 "a posílení lýtka (Winters, 2017).",
     "refs": ["Winters et al., 2013", "Winters, 2017"],
     "assumption": "Slabší důkazy, dávkování je pracovní předpoklad. Bolest přímo na kosti nechte posoudit."},
    {"key": "hamstring", "name": "Zadní strana stehna", "weeks": 8,
     "match": ["hamstring", "zákolen", "sedací hrbol"],
     "summary": "Šetrný začátek výdrží v mostu, pak síla v prodloužení.",
     "exercises": ["bridge_iso", "bridge", "sl_rdl", "nordic"],
     "evidence": "Programy s nordickým hamstringem snížily výskyt zranění zadní strany stehna zhruba na polovinu (van Dyk et al., 2019), "
                 "přesnější rozbor ale účinek za jistý nepovažuje (Impellizzeri et al., 2021). Mrtvý tah na jedné noze zlepšil sílu stejně jako nordický "
                 "hamstring (Behan et al., 2024).",
     "refs": ["van Dyk et al., 2019", "Impellizzeri et al., 2021", "Behan et al., 2024"],
     "assumption": "Nordický hamstring až bez bolesti. Dávkování je pracovní předpoklad."},
]
PROGRAM_BY_KEY = {p["key"]: p for p in PROGRAMS}

REFERENCES = {
    "Alfredson et al., 1998": "Alfredson, H., Pietilä, T., Jonsson, P., & Lorentzon, R. (1998). Heavy-load eccentric calf muscle training for the treatment of chronic Achilles tendinosis. The American Journal of Sports Medicine, 26(3), 360–366.",
    "Silbernagel et al., 2007": "Silbernagel, K. G., Thomeé, R., Eriksson, B. I., & Karlsson, J. (2007). Continued sports activity, using a pain-monitoring model, during rehabilitation in patients with Achilles tendinopathy. The American Journal of Sports Medicine, 35(6), 897–906.",
    "Baxter et al., 2021": "Baxter, J. R., Corrigan, P., Hullfish, T. J., O'Rourke, P., & Silbernagel, K. G. (2021). Exercise progression to incrementally load the Achilles tendon. Medicine & Science in Sports & Exercise, 53(1), 124–130.",
    "Rathleff et al., 2015": "Rathleff, M. S., Mølgaard, C. M., Fredberg, U., Kaalund, S., Andersen, K. B., Jensen, T. T., Aaskov, S., & Olesen, J. L. (2015). High-load strength training improves outcome in patients with plantar fasciitis. Scandinavian Journal of Medicine & Science in Sports, 25(3), e292–e300.",
    "Collins et al., 2018": "Collins, N. J., Barton, C. J., van Middelkoop, M., et al. (2018). 2018 Consensus statement on exercise therapy and physical interventions to treat patellofemoral pain. British Journal of Sports Medicine, 52(18), 1170–1178.",
    "van der Heijden et al., 2016": "van der Heijden, R. A., Lankhorst, N. E., van Linschoten, R., Bierma-Zeinstra, S. M., & van Middelkoop, M. (2016). Exercise for treating patellofemoral pain syndrome: An abridged version of Cochrane systematic review. European Journal of Physical and Rehabilitation Medicine, 52(1), 110–133.",
    "Fredericson et al., 2000": "Fredericson, M., Cookingham, C. L., Chaudhari, A. M., Dowdell, B. C., Oestreicher, N., & Sahrmann, S. A. (2000). Hip abductor weakness in distance runners with iliotibial band syndrome. Clinical Journal of Sport Medicine, 10(3), 169–175.",
    "Sanchez-Alvarado et al., 2024": "Sanchez-Alvarado, A., Bokil, C., Cassel, M., & Engel, T. (2024). Effects of conservative treatment strategies for iliotibial band syndrome on pain and function in runners: A systematic review. Frontiers in Sports and Active Living, 6.",
    "Winters et al., 2013": "Winters, M., Eskes, M., Weir, A., Moen, M. H., Backx, F. J., & Bakker, E. W. (2013). Treatment of medial tibial stress syndrome: A systematic review. Sports Medicine, 43(12), 1315–1333.",
    "Winters, 2017": "Winters, M. (2017). Medial tibial stress syndrome: Diagnosis, treatment and outcome assessment (PhD Academy Award). British Journal of Sports Medicine.",
    "van Dyk et al., 2019": "van Dyk, N., Behan, F. P., & Whiteley, R. (2019). Including the Nordic hamstring exercise in injury prevention programmes halves the rate of hamstring injuries. British Journal of Sports Medicine, 53(21), 1362–1370.",
    "Impellizzeri et al., 2021": "Impellizzeri, F. M., McCall, A., & van Smeden, M. (2021). Why methods matter in a meta-analysis: A reappraisal showed inconclusive injury preventive effect of Nordic hamstring exercise. Journal of Clinical Epidemiology.",
    "Behan et al., 2024": "Behan, F. P., et al. (2024). Implementing hamstring injury prevention programmes remotely: A randomised proof of concept trial. BMJ Open Sport & Exercise Medicine.",
    "Warden et al., 2014": "Warden, S. J., Davis, I. S., & Fredericson, M. (2014). Management and prevention of bone stress injuries in long-distance runners. Journal of Orthopaedic & Sports Physical Therapy, 44(10), 749–765.",
}


def programs_for_regions(regions: list[str]) -> list[str]:
    """Program keys that fit the marked pain regions, most marked first."""
    hits: dict[str, int] = {}
    for reg in regions:
        r = (reg or "").lower()
        for p in PROGRAMS:
            if any(m in r for m in p["match"]):
                hits[p["key"]] = hits.get(p["key"], 0) + 1
    return sorted(hits, key=lambda k: -hits[k])


def library() -> dict:
    return {"exercises": EXERCISES, "programs": PROGRAMS, "painRule": PAIN_RULE, "references": REFERENCES, "reviewed": False}
