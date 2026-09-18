"""Signal documentation — evidence grade, formula, why/limit/clear, Czech
text. Port of core.js's SIG_DOC/GRADE_NOTE/QUAD/TIER/PHASE (lines ~306-409),
extended with the v0.4 additions (ewma_mild, hrvcv, sleepreg, tsb) and an
updated `ewma` entry reflecting the 2025 46-study ACWR meta-analysis.
"""

GRADE_NOTE = {
    "A": "Konzistentní prospektivní evidence u běžců.",
    "B": "Smíšená nebo vznikající evidence — signál, ne důkaz.",
    "C": "Mechanistická úvaha. Generuje hypotézu, nic víc.",
}

SIG_DOC = {
    "tavr": {
        "t": "Terénně očištěný drift vertikálního poměru", "g": "B",
        "fx": "VR      = vertikální oscilace / délka kroku\n"
              "TAVR_z  = (průměr VR za 28 dní − baseline) / SD\n"
              "          baseline = dny 84 → 29\n"
              "          skupiny: povrch × sklon × pásmo tempa",
        "why": "Vertikální oscilace sama o sobě je špatná jednotka — kdo prodlouží krok, zvedne VO bez ztráty "
               "ekonomiky. Normalizovaný vertikální poměr to řeší. Menší vertikální oscilace trupu souvisí s "
               "lepší běžeckou ekonomikou a s nižší vertikální mírou zatížení, a ta je uznávaným rizikovým "
               "faktorem zranění dolní končetiny. Rostoucí VR ve srovnatelných podmínkách proto naznačuje "
               "ztrátu elastického odrazu dřív, než to začne bolet.",
        "limit": "Řetězec VO → zatížení → zranění je odvozený, ne prokázaný prospektivně. Hodnoty se navíc liší "
                 "mezi zařízeními, takže při výměně hodinek je nutné baseline resetovat.",
        "clear": "Signál zmizí, když se VR ve stejných podmínkách vrátí do pásma ±1 SD po dobu tří tréninků.",
    },
    "gct": {
        "t": "Prodloužený kontakt se zemí", "g": "B",
        "fx": "GCT_adj = GCT × (kadence / baseline_kadence)\nz       = (GCT_adj − baseline) / SD   [14 dní]",
        "why": "Doba kontaktu se zemí roste s únavou — měřitelně stoupá od 10. kilometru dlouhého běhu spolu s "
               "vyšším extenčním momentem kyčle a addukčním úhlem. Trvale zvýšená hodnota při shodném tempu a "
               "kadenci naznačuje, že se únava mezi tréninky nestíhá odbourávat.",
        "limit": "Citlivé na obuv. Přechod do vyšší tlumené boty GCT prodlouží bez jakékoli patologie — je "
                 "potřeba se zeptat, ne jen měřit.",
        "clear": "Dva až tři regenerační týdny obvykle vrátí GCT k baseline. Pokud ne, jde spíš o změnu techniky "
                 "nebo obuvi.",
    },
    "bal": {
        "t": "Posun v symetrii kontaktu", "g": "B",
        "fx": "excursion = |GCT_balance_teď − GCT_balance_baseline|\nNEporovnává se s populační normou",
        "why": "Sekundární analýza randomizované studie s více než 800 rekreačními běžci ukázala, že asymetrie "
               "chůze v prostorových a kinetických proměnných riziko zranění dolních končetin nezvyšuje. Často "
               "citovaný údaj o 75% výskytu zranění nad 10 % asymetrie pochází z vojenského základního výcviku "
               "a na rekreační běžce se nepřenáší. Platforma proto neoznačuje absolutní asymetrii — jen její "
               "změnu proti vlastní normě. Jemné posuny asymetrie, včetně obrácení poměru reakčních sil mezi "
               "končetinami, byly pozorovány před stresovým zraněním kosti u vysokoškolských běžců.",
        "limit": "Běžec, který je celý život na 47,5/52,5, není nález. Zajímavý je ten, kdo se tam právě posunul.",
        "clear": "Návrat do ±0,5 p.b. od vlastní normy po dobu 14 dnů.",
    },
    "dec": {
        "t": "Klesající odolnost proti únavě", "g": "C",
        "fx": "decoupling = (VR_poslední_třetina / VR_první_třetina − 1) × 100\n"
              "trend      = sklon přes 6+ srovnatelných dlouhých běhů",
        "why": "Běžec, jehož technika drží 90 minut, je odolnější než ten, kterému se vertikální poměr v "
               "poslední třetině zhorší o 8 %. Rostoucí trend napříč srovnatelnými běhy znamená klesající "
               "odolnost proti únavě.",
        "limit": "Stupeň C. Mechanisticky to dává smysl, prospektivní validace neexistuje. Zároveň je to "
                 "metrika, která se hýbe nejdřív.",
        "clear": "Trend se srovná, jakmile se doplní síla lýtka a hýždí nebo se sníží podíl dlouhých běhů.",
    },
    "cad": {
        "t": "Klesající kadence", "g": "C",
        "fx": "z = (kadence_teď − baseline) / SD   [na shodných profilech terénu × tempa]\nsignál při z ≤ −1",
        "why": "Nižší kadence při srovnatelném tempu znamená delší krok a delší kontakt se zemí — spojené s vyšším "
               "nárazem a brzdicí silou. Pokles proti vlastní normě bývá časný znak nastupující únavy nebo změny techniky.",
        "limit": "Stupeň C. Kadence přirozeně kolísá s tempem a terénem — proto se porovnává jen ve shodných profilech, "
                 "ne populační norma. Délka kroku je druhou stranou téže mince, proto se nezapočítává zvlášť.",
        "clear": "Návrat kadence k vlastní normě po několika během ve srovnatelných podmínkách.",
    },
    "vosc": {
        "t": "Vyšší vertikální oscilace", "g": "C",
        "fx": "z = (oscilace_teď − baseline) / SD   [na shodných profilech terénu × tempa]\nsignál při z ≥ 1",
        "why": "Vyšší vertikální oscilace znamená víc pohybu nahoru/dolů místo dopředu — méně ekonomický běh a vyšší "
               "nárazové zatížení na krok. Nárůst proti vlastní normě při shodném tempu naznačuje zhoršující se techniku nebo únavu.",
        "limit": "Stupeň C. Mechanisticky dává smysl, prospektivní validace pro riziko zranění je slabá. Citlivé na tempo a terén — proto per-profil.",
        "clear": "Návrat oscilace k vlastní normě po odlehčení nebo doplnění síly.",
    },
    "hi_load": {
        "t": "Skok ve vysoké intenzitě", "g": "B",
        "fx": "HI zátěž = TRIMP session, kde ⌀ tep ≥ 80 % HR rezervy (≈ práh / Z4+)\n"
              "hiRatio = EWMA(HI, 7) / max(EWMA(HI, 28), 0,15·chronic) · signál > 1,5",
        "why": "Prudký nárůst tvrdé práce na nízké chronické základně tvrdé práce je podle týmové evidence "
               "rizikovější než stejné navýšení celkové zátěže v lehké intenzitě. Odděluje intenzitu od pouhého objemu.",
        "limit": "Odvozeno z ⌀ tepu za celý běh, ne z času v zónách (ten se zatím neimportuje) — intervaly s "
                 "nízkým průměrem se mohou podhodnotit. Práh 80 % HRR je konvence, ne kalibrace na běžce.",
        "clear": "Poměr HI zátěže se vrátí k ~1 po pár dnech bez tvrdých běhů.",
    },
    "load_creep": {
        "t": "Postupný nárůst zátěže", "g": "C",
        "fx": "creep = akutní zátěž teď / akutní zátěž před 14 dny · signál ≥ 1,15 při ACWR < 1,3",
        "why": "Metaanalýzy a běžecké kohorty ukazují, že i malé, ale opakované dvoutýdenní nárůsty zátěže "
               "předcházejí zranění — ne jen velké skoky. Zachytí plíživé navyšování, které poměr 7:28 ještě neoznačí.",
        "limit": "Stupeň C — plíživý nárůst je normální součást budování formy; rizikový je hlavně v kombinaci s "
                 "potlačenou regenerací nebo příznaky. Sám o sobě není důvod k zásahu.",
        "clear": "Po týdnu stabilního nebo sníženého objemu.",
    },
    "gaitcv": {
        "t": "Kolísavější mechanika", "g": "C",
        "fx": "reziduum = GCT (norm. na kadenci) − baseline daného terénního bucketu\nratio = SD(reziduum, 28 dní) / SD(reziduum, baseline) · signál ≥ 1,5",
        "why": "Roste-li rozptyl kontaktu se zemí kolem vlastní normy z běhu na běh, bývá to časný signál "
               "nervosvalové únavy nebo kompenzace — objeví se dřív než posun průměru. Variabilita chůze je "
               "v patologii pohybu zavedený marker.",
        "limit": "Stupeň C. Je to variabilita mezi běhy z průměrů na běh, ne stride-to-stride CV z laboratoře "
                 "(per-krok streamy summary API nedává). Citlivé na pestrost terénu i počet běhů.",
        "clear": "Rozptyl se vrátí k baseline po pár konzistentních bězích ve srovnatelných podmínkách.",
    },
    "sleepeff": {
        "t": "Nízká efektivita spánku", "g": "C",
        "fx": "efektivita = čas spánku / (čas spánku + čas vzhůru), z hodinek\nsignál při 7denním průměru < 85 %",
        "why": "Roztříštěný spánek (nízká efektivita, WASO) je spojen s vyšším rizikem svalově-kosterních zranění "
               "nad rámec pouhého počtu naspaných hodin — kohorty u dospívajících i elitních sportovců.",
        "limit": "Stupeň C, závisí na kvalitě odhadu spánku z náramku. Práh 85 % je konvence; ideální je sledovat "
                 "i vlastní baseline. Importuje se jen z novějších Garminů/Apple, u starších dat chybí.",
        "clear": "Nad ~85 % po několika nocích klidnějšího spánku.",
    },
    "session_spike": {
        "t": "Skok v jednom běhu (single-session paradigm)", "g": "B",
        "fx": "spike = max(vzdálenost, vnitřní zátěž TRIMP) jednoho běhu / nejvyšší z předchozích 30 dní\n"
              "bere HORŠÍ z obou os · +10–30 % → až 6 b · +30–100 % → až 14 b · nad +100 % → 14–30 b",
        "why": "V zatím největší prospektivní kohortě (RUNSAFE, 5 205 běžců, 588 tis. běhů, BJSM 2025) je skok "
               "v délce JEDNOHO běhu proti nejdelšímu běhu předchozích 30 dní dávkově závislý rizikový faktor "
               "(HRR až 2,28 nad +100 %) — silnější a specifičtější než ACWR. v0.6.1 přidává i vnitřní zátěž "
               "(TRIMP/úsilí): Neal 2024 na stejných datech z běžeckých hodinek zjistil, že injury předpovídalo "
               "právě akutní ÚSILÍ, ne vzdálenost — a Paquette 2020 doporučuje kombinovat vnější + vnitřní zátěž. "
               "Bere se horší z obou os, takže skok v délce i skok v intenzitě spustí signál. Páteř osy zátěže.",
        "limit": "Stále je to proxy kumulativní zátěže tkáně, ne její přímé měření; opakované menší skoky ve "
                 "stejném týdnu zachytí spíš creep a doznívající paměť. Vnitřní zátěž chybí bez tepové křivky.",
        "clear": "Zmizí, jakmile nejnáročnější běh posledních 7 dní klesne k obvyklému maximu (délkou i intenzitou).",
    },
    "spike_latent": {
        "t": "Doznívající skok v zátěži", "g": "B",
        "fx": "z největšího skoku (>1,3) za 8–28 dní: (spike−1,3) × lineární pokles k nule ve 28 dnech × 22, max 16",
        "why": "Riziko zranění po prudkém nárůstu zátěže vrcholí 1–4 týdny PO něm, ne v den skoku (IOC konsenzus "
               "2016; efekt trvá až měsíc). Stav proto zůstává zvýšený, dokud se adaptace nedožene.",
        "limit": "Lineární rozpad je zjednodušení; skutečná doba zotavení tkáně je individuální.",
        "clear": "Doznívá lineárně do nuly 28 dní po skoku.",
    },
    "pace_spike": {
        "t": "Skok v tempu", "g": "C",
        "fx": "medián tempa (30 dní) / nejrychlejší běh (7 dní); nad ×1,06 → až 10 b",
        "why": "Prudké zrychlení je jiný mechanismus než nárůst vzdálenosti — Nielsen 2014 mapuje skoky v tempu "
               "spíš na Achillovku / plantární fascii / holeň, zatímco vzdálenost na koleno/holeň.",
        "limit": "Tempo z GPS je zašuměné; nerozlišuje intervaly od souvislého zrychlení.",
        "clear": "Zmizí, když se nejrychlejší běh vrátí k obvyklému tempu.",
    },
    "load_capacity": {
        "t": "Zátěž na sníženou regeneraci (interakce)", "g": "B",
        "fx": "kapac.deficit = průměr(potlačená HRV, zvýšený tep, spánkový dluh), 0–1\n"
              "body = deficit × závažnost_skoku × 34, max 16 (jen když deficit ≥ 0,3)",
        "why": "Zranění = kumulativní zátěž překročí kapacitu tkáně, a kapacitu snižuje regenerace "
               "(Bertelsen 2017). Stejný skok na unaveném těle přesáhne momentální kapacitu dřív než na "
               "odpočatém — proto se skóruje interakce, ne jen obě veličiny zvlášť.",
        "limit": "Kapacitu tkáně nelze měřit přímo; deficit je jen nepřímý proxy z regeneračních markerů.",
        "clear": "Zmizí, když se HRV/tep/spánek vrátí k baseline nebo skok odezní.",
    },
    "complaints": {
        "t": "Opakované obtíže (napříč místy)", "g": "B",
        "fx": "počet dnů s hlášenou bolestí (běžecky relevantní místa) za 28 dní; od 3 dnů → (n−2) × 4, max 14",
        "why": "Frandsen 2025: recidiva stejného místa je před zraněním vzácná (6,9 % za 7 dní), ale obtíž v "
               "JAKÉMKOLIV místě předcházela 39,6 % zranění do 28 dní — širší tally je citlivější (byť méně "
               "specifické) varování než jen recidiva stejného místa.",
        "limit": "Nižší specificita; self-report se v historickém replayi nepřehrává.",
        "clear": "Zmizí, když ustanou hlášené obtíže napříč 28denním oknem.",
    },
    "pain_prior": {
        "t": "Bolest v místě dřívějšího zranění", "g": "A",
        "fx": "+8 b, když aktuální bolest padne na dříve zraněnou oblast",
        "why": "Předchozí zranění je nejrobustnější rizikový faktor napříč literaturou (Hulme 2017; van Poppel "
               "2021); recidiva ve stejné oblasti je jeho nejsilnější projev.",
        "limit": "Závisí na kvalitě záznamu dřívějších zranění a na spolehlivé lokalizaci (koleno se sjednocuje).",
        "clear": "Zmizí, když bolest v daném místě ustoupí.",
    },
    "ewma": {
        "t": "EWMA poměr zátěže (ACWR) — jen kontext", "g": "C",
        "fx": "acute   = EWMA(denní tréninková zátěž, 7)\nchronic = EWMA(denní tréninková zátěž, 28)\nratio   = acute / chronic\n"
              "          zátěž = TRIMP (z tepu) přes všechny sporty, v jednotkách zátěže\n"
              "          potlačeno při málo datech · 1,30–1,50 = mírně zvýšený · nad 1,50 = zvýšený",
        "why": "v0.6 DEGRADOVÁNO na pouhý kontext (grade C). Stejná kohorta RUNSAFE (BJSM 2025) našla u běžců "
               "ACWR dokonce INVERZNĚ vztažený k přetíženostním zraněním a poměr týden-na-týden bez vztahu — "
               "„sweet spot\" z týmových sportů se na vytrvalostní běh nepřenáší. Hlavní signál zátěže je teď "
               "skok v jednom běhu (session_spike); ACWR zůstal jen jako mírný popis + příznak detréninku pod 0,70.",
        "limit": "Klasický ACWR má vážné problémy: teoretický základ postrádá robustní evidenci, poměry se "
                 "hroutí při nízké chronické zátěži a nálezy napříč studiemi si odporují. Známý obrázek „sweet "
                 "spotu\" byl publikován jen jako ilustrativní a pak opakovaně přetištěn, jako by byl "
                 "validovaný. I metaanalýza z roku 2025 mluví jen o „mírně zvýšeném\" riziku, ne o ostré "
                 "hranici — proto dvoustupňové pásmo místo jednoho prahu.",
        "clear": "Poměr se vrátí do 0,7–1,3 po dvou týdnech stabilního objemu.",
    },
    "ewma_mild": {
        "t": "Mírně zvýšený poměr zátěže", "g": "B",
        "fx": "stejný vzorec jako ewma, pásmo 1,30 < ratio ≤ 1,50",
        "why": "2025 metaanalýza 46 studií ukázala, že poměr mezi 1,3 a 1,5 nese jen mírně zvýšené riziko oproti "
               "středním hodnotám — proto nižší váha bodů než u zřetelně zvýšeného pásma nad 1,5.",
        "limit": "Hranice 1,3/1,5 jsou převzaté z agregátní evidence napříč sporty, ne kalibrované na běžeckou "
                 "kohortu specificky.",
        "clear": "Poměr klesne pod 1,3 po týdnu stabilizovaného objemu.",
    },
    "mono": {
        "t": "Monotónnost tréninku (Foster)", "g": "B",
        "fx": "monotony = průměr(denní zátěž) / SD(denní zátěž)   [14 dní]\nstrain   = Σ(zátěž) × monotony",
        "why": "Zachytí běžce, který nikdy nemá skutečně lehký den. Vysoká monotónnost při dostatečném objemu "
               "je jiný způsob selhání než objemový skok — metriky založené jen na objemu ji nevidí.",
        "limit": "Jeden opravdu volný den v týdnu monotónnost srazí, aniž by se cokoli změnilo na celkové "
                 "zátěži. Signál je citlivý na to, jak běžec plánuje, ne jen kolik naběhá.",
        "clear": "Zařazení jednoho úplného volna a jednoho výrazně kratšího běhu týdně.",
    },
    "desc": {
        "t": "Excentrická zátěž z klesání", "g": "C",
        "fx": "descent_load = Σ(klesání_m) za 7 dní\nspike        = descent_load / baseline",
        "why": "Sbíhání je hlavní zdroj excentrického poškození svalu. Pro trailovou část kohorty je celková "
               "vzdálenost zavádějící: 20 km po rovině a 20 km s 900 m klesání jsou stejná čísla a velmi odlišná "
               "mechanická zátěž.",
        "limit": "Nerozlišuje strmost — proto doplňkový signál desc_steep, který sklon už rozlišuje. 900 m "
                 "rozložených do dlouhého mírného sjezdu není totéž co 900 m technického srázu.",
        "clear": "Týden bez sbíhání nad baseline.",
    },
    "desc_steep": {
        "t": "Nárůst strmého klesání (≥10 % sklon)", "g": "C",
        "fx": "profil = vzdálenost/nadmořská výška po segmentech (z FIT záznamů nebo syntetizováno pro demo)\n"
              "buckety = klesání_m rozdělené po 2,5 % sklonu, 0–30 %+ \n"
              "steep_spike = (klesání_m v pásmech ≥10 % za 7 dní) / (týdenní průměr ≥10 % v baseline)",
        "why": "Doplňuje signál 'desc' o skutečný sklon místo jen celkových metrů. Excentrické poškození svalu "
               "roste se strmostí nelineárně — pozvolný sjezd a technický sráz se stejným celkovým převýšením "
               "nejsou mechanicky totéž. Tenhle signál to rozlišuje tam, kde k tomu jsou data (profil "
               "nadmořské výšky po segmentech, ne jen součet stoupání/klesání).",
        "limit": "Stupeň C — mechanistická úvaha, ne prospektivně validovaný práh. U reálných dat závisí na "
                 "hustotě GPS/výškových záznamů v exportu; u demo dat je profil syntetizovaný ze skutečného "
                 "celkového převýšení běhu, ne měřený.",
        "clear": "Týden bez strmého klesání nad baseline.",
    },
    "aer": {
        "t": "Aerobní decoupling", "g": "B",
        "fx": "decoupling = (tep:tempo 2. půle) / (tep:tempo 1. půle) − 1",
        "why": "Nad zhruba 5 % na aerobním běhu naznačuje nedoléčenou únavu. V monitoringu vytrvalců zavedené.",
        "limit": "Jako přímý prediktor zranění slabý — proto skóre jen dolaďuje, netvoří ho. Silně ovlivněno "
                 "horkem a dehydratací.",
        "clear": "Chladnější podmínky a týden nižší intenzity.",
    },
    "hrv": {
        "t": "Potlačená variabilita srdečního rytmu", "g": "B",
        "fx": "z = (HRV průměr 7 dní − baseline 28 dní) / SD\nzdroj: noční měření z hodinek",
        "why": "Pokles HRV proti vlastní normě je zavedený marker nedokončené regenerace a autonomní zátěže. "
               "Používá se jako modulátor zátěžové osy, ne jako samostatný důvod k zásahu.",
        "limit": "HRV reaguje na nemoc, alkohol, cestování i stres v práci stejně jako na trénink. Bez kontextu "
                 "z check-inu se přeceňuje.",
        "clear": "Návrat do ±1 SD po třech nocích.",
    },
    "hrvcv": {
        "t": "Kolísavá HRV mezi dny", "g": "C",
        "fx": "CV      = SD(HRV, 7 dní) / průměr(HRV, 7 dní) × 100\nratio   = CV_teď / CV_baseline (28 dní)",
        "why": "v0.4. Doplňuje signál potlačené HRV o jinou osu: ne kolik HRV klesla, ale jak nestabilní je "
               "den ku dni. Rostoucí den-k-dni variabilita bez poklesu průměru bývá raný marker autonomní "
               "nestability, který samotný z-score průměru přehlédne.",
        "limit": "Stupeň C — jde o rozšíření zavedeného HRV signálu o novou osu, ne o samostatně prospektivně "
                 "validovanou metriku. Citlivé na nepravidelné měření (vynechané noci).",
        "clear": "Poměr klesne pod 1,2 po týdnu pravidelného měření.",
    },
    "rhr": {
        "t": "Zvýšený klidový tep", "g": "B",
        "fx": "z = (klidový tep 7 dní − baseline 28 dní) / SD",
        "why": "Zvýšení klidového tepu proti vlastní normě obvykle předchází poklesu výkonu a doprovází "
               "nedoléčenou únavu nebo začínající infekt.",
        "limit": "Nespecifické. Rozlišit infekt od přetížení bez dalších dat nelze — proto se váže na check-in.",
        "clear": "Návrat k baseline po dvou až třech dnech.",
    },
    "tsb": {
        "t": "Nepříznivá bilance zátěže (fitness–fatigue)", "g": "C",
        "fx": "fitness = EWMA(denní tréninková zátěž, 42) × 7\nfatigue = EWMA(denní tréninková zátěž, 7) × 7   (stejné jako 'acute')\n"
              "balance = fitness − fatigue   (jednotky zátěže, práh −12 % chronické)",
        "why": "v0.4. Banisterův impulz-odezva model z výkonnostní literatury, přenesený sem jako doplňkový "
               "pohled na EWMA poměr — lépe funguje při nízké chronické zátěži, kde se ACWR poměr chová "
               "nestabilně. Výrazně záporná bilance znamená, že akutní zátěž dlouhodobě předbíhá vybudovanou "
               "kapacitu.",
        "limit": "Model je odvozený z výkonnosti vytrvalců, ne z prospektivní evidence o zraněních. Stupeň C — "
                 "doplňkový signál, ne samostatný důvod k zásahu.",
        "clear": "Bilance se vrátí nad práh po týdnu snížené zátěže.",
    },
    "niggle": {
        "t": "Opakované bolestivé místo", "g": "A",
        "fx": "niggle_count = počet hodnocení po tréninku\n                s příznakem na stejném místě za 21 dní",
        "why": "Sebehodnocená bolest zůstává nejsilnějším jednotlivým prediktorem. Opakované hlášení téhož "
               "místa po trénincích je klinicky významnější než jednorázová vysoká hodnota v týdenním "
               "check-inu, protože zachytí vzorec vázaný na konkrétní typ zátěže.",
        "limit": "Závisí na tom, jestli běžec hodnocení skutečně vyplňuje. Nízká adherence signál umlčí.",
        "clear": "Tři týdny bez hlášení na stejném místě.",
    },
    "pain": {
        "t": "Bolest při běhu", "g": "A", "fx": None,
        "why": "Sebehodnocená bolest je nejsilnější jednotlivý prediktor a jediný signál stupně A, který má "
               "platforma průběžně k dispozici. Biomechanika ho doplňuje, nenahrazuje.",
        "limit": "Retrospektivní a subjektivní. Běžci před závodem systematicky podhodnocují.",
        "clear": "Pod 3/10 po dobu dvou týdnů.",
    },
    "sore": {
        "t": "Svalová únava", "g": "B", "fx": None,
        "why": "Vysoká svalová bolestivost po tréninku jako doplňkový signál nedokončené regenerace.",
        "limit": "Silně závislá na typu tréninku v předchozích dnech.",
        "clear": "Pod 5/10.",
    },
    "fatigue": {
        "t": "Vnímaná únava", "g": "C", "fx": "self-report z denního check-inu (Únava 0–10), signál od 6",
        "why": "Subjektivní únava bývá časný signál — roste dřív, než se pohnou HRV nebo klidový tep. Bere se jen "
               "z posledních dnů (denní check-in je 'dnešní' signál), přetrvávající problémy jdou přes týdenní OSTRC.",
        "limit": "Stupeň C — čistě subjektivní, kolísá s náladou a kontextem. Doplňkový, ne samostatný důvod k zásahu.",
        "clear": "Pod 6/10 v dalším check-inu.",
    },
    "sleep": {
        "t": "Spánkový dluh", "g": "B",
        "fx": "debt = (baseline_h − průměr_7_dní_h) × 7",
        "why": "Spánek pod vlastní normou opakovaně snižuje toleranci zátěže a zhoršuje regeneraci měkkých "
               "tkání.",
        "limit": "Měření spánku z hodinek je nepřesné, zvlášť u fází. Proto je hodnota ručně přepsatelná.",
        "clear": "Týden na baseline.",
    },
    "sleepreg": {
        "t": "Nepravidelná délka spánku", "g": "C",
        "fx": "SD_teď      = SD(délka spánku, 14 dní)\nSD_baseline = SD(délka spánku, 35 dní před tím)\n"
              "ratio       = SD_teď / SD_baseline",
        "why": "v0.4. Doplňuje spánkový dluh o jinou osu: ne kolik spánku chybí proti průměru, ale jak "
               "nepravidelná je jeho délka den ku dni. Nepravidelný spánek je spojován s horší tolerancí "
               "zátěže i mimo běžeckou literaturu.",
        "limit": "Aproximace — schéma platformy nemá čas usnutí/probuzení, jen délku spánku, takže jde o "
                 "variabilitu délky, ne o skutečný index pravidelnosti spánkového režimu. Evidence je "
                 "extrapolovaná, ne přímá.",
        "clear": "Poměr klesne pod 1,2 po dvou týdnech pravidelnějšího režimu.",
    },
    "feel": {
        "t": "Zhoršující se pocit z běhu", "g": "C",
        "fx": "trend = sklon sebehodnocení (1–5) přes 21 dní",
        "why": "Klesající subjektivní pocit z běhu při nezměněné zátěži bývá první věc, které si běžec všimne "
               "— dřív než bolesti.",
        "limit": "Stupeň C. Ovlivněno počasím, motivací i tím, jak šel poslední závod.",
        "clear": "Stabilní nebo rostoucí trend po dvou týdnech.",
    },
    "stiffness": {
        "t": "Ztuhlost nohou před během", "g": "C",
        "fx": "ignoreRate = (běhů s vysokou ztuhlostí A RPE ≥ 6) / (běhů s vysokou ztuhlostí)\n"
              "trend      = sklon sebehodnocené ztuhlosti (1–5) přes 21 dní",
        "why": "v0.5. Ztuhlost nohou před během je subjektivní signál nedokončené regenerace, sbíraný retrospektivně "
               "při hodnocení běhu. Sama o sobě je to jen další symptom — zajímavější je vzorec, kdy běžec i "
               "přes hlášenou ztuhlost trénuje s vysokou vnímanou námahou: to naznačuje sníženou schopnost "
               "poslouchat vlastní tělo, ne jen únavu samotnou.",
        "limit": "Stupeň C, čistě sebehodnocené. Závisí na tom, jak poctivě a pravidelně běžec vyplňuje "
                 "hodnocení, a na tom, jak dobře umí ztuhlost od svalové bolesti rozeznat.",
        "clear": "Ztuhlost před během klesne pod 4/5, nebo se poměr trénování navzdory ztuhlosti vrátí pod 50 %.",
    },
    "taper": {
        "t": "Blízký závod při zvýšené zátěži", "g": "C",
        "fx": "aktivní jen když dní_do_závodu ≤ 21 A (zátěžové skóre ≥ 25 NEBO EWMA poměr > 1,3)",
        "why": "Cíl a termín se nikde v aplikaci nepoužívají jako primární rámec — jsou informační poznámka pod "
               "čarou. Tenhle signál je výjimka: kombinace blízkého závodu se zátěží, která už je zvýšená, je "
               "přesně situace, kdy běžci nejčastěji naskočí na trénink navzdory signálům místo odlehčení.",
        "limit": "Stupeň C — logická kombinace dvou already-existujících signálů (termín + zátěž), ne "
                 "samostatně validovaný prediktor. Nehodnotí kvalitu tréninkového plánu, jen jeho načasování.",
        "clear": "Buď zátěžové skóre klesne pod práh, nebo závod proběhne/termín se posune.",
    },
    "hist": {
        "t": "Zranění v anamnéze", "g": "A", "fx": None,
        "why": "Předchozí zranění je konzistentně nejsilnější prediktor dalšího zranění napříč studiemi.",
        "limit": "Neměnný faktor. Nedá se odstranit, jen zohlednit ve váze ostatních signálů.",
        "clear": "Po 12 měsících bez recidivy váha klesá.",
    },
}

QUAD = {
    "stable": {"t": "Stabilní", "d": "Zátěž i mechanika sedí na vlastní normě.", "c": "ok"},
    "overreaching": {"t": "Přetížení", "d": "Zátěž vyskočila, ale technika zatím drží. Deload obvykle stačí.", "c": "watch"},
    "silent": {"t": "Tichý drift", "d": "Mechanika se mění bez nárůstu objemu. Tohle čistě objemové aplikace nevidí.", "c": "info"},
    "critical": {"t": "Kritická kombinace", "d": "Zátěž i mechanika se hýbou naráz.", "c": "alert"},
}

TIER = {"ok": "Nízké riziko", "watch": "Sledovat", "alert": "Vysoké riziko"}
PHASE = {"offload": "odlehčení", "rebuild": "budování", "return": "návrat k běhu", "prevent": "prevence"}
