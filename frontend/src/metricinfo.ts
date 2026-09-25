// Plain-language explanations for every metric shown in the app: what it
// measures and — crucially — how to read it against YOUR OWN baseline, not a
// population average. Surfaced via the "?" InfoDot next to each metric.

export const METRIC_INFO: Record<string, string> = {
  // — Zátěž (load) —
  acute7: "Součet tréninkové zátěže (běh i jiný sport) za posledních 7 dní v jednotkách zátěže. Čím výš nad vaším obvyklým týdnem, tím větší akutní nálož. Sledujte hlavně skok proti předchozím týdnům, ne absolutní číslo.",
  ratio728:
    "Poměr posledních 7 dní ku vašemu 28dennímu průměru. Kolem ×1,0 znamená, že jedete jako obvykle. Výrazně nad ×1,3 = rychlý nárůst (rizikovější); pod ×0,8 = odlehčení nebo výpadek. U běžců to bereme jen jako kontext, ne jako hlavní varování.",
  hiIntensity:
    "Kolik z vaší zátěže tvoří tvrdé/rychlé běhy za 7 dní vůči vaší normě. Nárůst tvrdých tréninků zvedá riziko víc než kilometry navíc v lehkém tempu. Interpretujte podle toho, kolik intenzity obvykle snesete.",
  monotony:
    "Jak jednotvárná byla zátěž v týdnu (vysoká = každý den skoro stejně, žádné volno). Vysoká monotónnost + vysoký objem = „strain\", spojený s přetížením. Ideál je střídat těžké a lehké dny.",
  descent7:
    "Nametrážované klesání (sbíhání) za 7 dní v metrech. Klesání víc zatěžuje svaly excentricky než rovina — proto ho sledujeme zvlášť. Porovnejte s „obvykle\": prudký skok bývá spouštěč bolesti kolen/stehen.",
  sessionSpike:
    "Nejtěžší jednotlivý trénink vůči vašemu maximu za posledních 30 dní — podle vzdálenosti i podle intenzity (bere se horší z obou). Jeden výrazně větší běh než na co jste zvyklí je nejsilnější spouštěč přetížení.",
  safeLongRun:
    "Odhad délky nejdelšího běhu, který teď zvládnete bez velkého skoku v zátěži — odvozeno z vaší nedávné historie. Slouží jako strop pro plánování víkendového dlouhého běhu.",
  gradeAdj:
    "Efektivní „plochý ekvivalent\" kilometrů za 7 dní — vzdálenost přepočtená podle energetické náročnosti sklonu (Minetti). Kopcovitý běh stojí víc než stejně dlouhý po rovině, takže tohle číslo je vyšší než reálné km na členitém terénu. Citlivý engine pro skok v zátěži počítá náročnost terénu zvlášť: stoupání podle energetické náročnosti, klesání podle excentrické zátěže — strmý sjezd stojí méně energie, ale nohy zatěžuje víc.",
  downhill:
    "Kilometry naběhané v klesání od −5 % sklonu za 7 dní. Klesání zatěžuje svaly excentricky (brzdění) víc, než odpovídá jeho nízké metabolické ceně — proto ho sledujeme zvlášť. Prudký nárůst bývá spouštěč bolesti stehen a kolen.",

  // — Regenerace (recovery) —
  hrv: "Variabilita tepové frekvence přes noc (ms). Vyšší = lépe zregenerováno. Důležitá je odchylka od VAŠÍ baseline (z-skóre), ne absolutní hodnota — pokles o víc než ~1 SD napovídá únavu nebo blížící se nemoc.",
  rhr: "Klidový tep přes noc. Trvale zvýšený proti vaší baseline = tělo se nedostalo zpět (únava, stres, nemoc). Jednorázový výkyv nevadí; sledujte trend.",
  sleep: "Doba spánku a jeho efektivita. Vztahujeme k vašemu obvyklému množství — kumulovaný spánkový dluh snižuje toleranci k zátěži a zhoršuje regeneraci.",
  recoveryScore:
    "Souhrn regenerace přes noc (0–100) z HRV, klidového tepu a spánku proti vaší baseline. Vyšší = tělo je připravenější. Sledujte hlavně změnu oproti včerejšku.",

  // — Mechanika (running form) —
  vertRatio:
    "Poměr vertikálního pohybu k délce kroku (%). Nižší = ekonomičtější, „plošší\" běh. Zajímá nás posun proti vaší baseline ve srovnatelném tempu a terénu — zhoršení bývá známka únavy formy.",
  vertOsc: "Vertikální oscilace — o kolik se při každém kroku „nadskakuje\" (cm). Nižší bývá ekonomičtější. Hodnotí se proti vašim vlastním běhům, ne proti tabulkám.",
  cadence: "Kadence — počet kroků za minutu. Pokles kadence při stejném tempu často doprovází únavu. Neexistuje jedno správné číslo; klíčová je stabilita vůči vaší normě.",
  gct: "Doba kontaktu se zemí (ms) — jak dlouho je noha na zemi. Prodloužení proti baseline (při srovnatelném tempu) naznačuje únavu nebo ztrátu opory.",
  gctBalance: "Symetrie doby kontaktu levá/pravá (%). Ideál kolem 50/50. Rostoucí nesymetrie může souviset s jednostranným přetížením — sledujte trend, ne jeden běh.",
  strideLen: "Délka kroku (m). Kratší krok při stejném tempu = vyšší kadence a naopak. Zajímá nás změna proti vaší baseline ve srovnatelných podmínkách.",
  mechStability: "Souhrn stability běžecké formy v čase. Klesající křivka = forma se rozpadá (typicky únava); stabilní = držíte techniku.",

  // — Stav / kvadrant —
  overall: "Celkové skóre stavu (0–100) složené z mechaniky, zátěže a příznaků, vážené podle síly důkazů. Vyšší = víc signálů k pozornosti. Vždy proti vaší vlastní historii.",
  confidence: "Spolehlivost — nakolik je už postavená vaše baseline (počet srovnatelných tréninků a dní historie). Dokud je nízká, mechanické signály se raději nezobrazují, aby nemátly.",
  // — Kapacitní engine (v3) —
  capacity:
    "Kapacita = co jste prokazatelně zvládli bez obtíží. Za týden: průměrný týden posledních 4 týdnů, nebo 90 % nejlepšího týdne za 6 týdnů (týden o víc než 30 % nad těmi před ním se nepočítá) — zvlášť pro objem, intenzitu (minuty v Z4+), klesání, stoupání a celkovou zátěž (tep × čas ze všech aktivit). Na jeden běh: nejnáročnější běh posledních 30 dní, u intenzity průměr tří nejtvrdších (jeden závod nebo horký den kapacitu nenafoukne). Běhy, po kterých do 3 dnů přišla bolest ≥ 3/10, se nepočítají. Skok o víc než 30 % nad dosavadní kapacitu se 14 dní nepočítá vůbec a potom celý jen tehdy, když ho potvrdí hodnocení nebo check-in bez bolesti (jinak napůl) — kapacita roste jen z toho, co tělo prokazatelně zvládlo. Strop = kapacita + rezerva (+15 % za týden, +10 % na běh), snížená podle připravenosti. Nad stropem přibývají body zátěže. Kolik z kapacity je v plánu na tento týden, ukazuje Trénink.",
  readiness:
    "Připravenost (20–100 %) = jak daleko jsou dnes vaše ukazatele regenerace od VAŠÍ normy (posledních 8 týdnů): HRV pod normou a klidový tep nad normou — z poslední noci i z průměru 7 nocí, který je spolehlivější a počítá se o čtvrtinu silněji (to, co hodinky ukazují jako stav HRV) — kratší nebo méně kvalitní spánek (méně hlubokého a REM spánku nebo nižší efektivita než obvykle — počítá se nejvýš napůl, protože hodinky fáze spánku jen odhadují) a svalová bolest / únava z check-inu. Odchylka do 0,5 SD je běžný šum a nic nestojí; čím větší odchylka, tím nižší připravenost. Shodné signály se sčítají: HRV i klidový tep asi 1,1 SD mimo normu (průměr 7 nocí ~0,9 SD) → kolem 70 %, ~1,75 SD → kolem 40 %, nejníž 20 %. Kapacitu (Zátěž) připravenost zmenšuje nejvýš o 30 %.",
  sleepQuality:
    "Kvalita spánku = podíl hlubokého a REM spánku z celého spánku a efektivita (čas spánku / čas v posteli), průměr 7 nocí proti vaší normě za 8 týdnů. Hluboký spánek slouží hlavně regeneraci těla, REM zotavení nervové soustavy. Když je podíl nebo efektivita zřetelně pod vaší normou, sníží se dnešní připravenost — i když jste spali dost dlouho. Fáze spánku hodinky jen odhadují, proto má kvalita nejvýš poloviční váhu signálu.",
  relEffort:
    "Relativní úsilí porovná tepovou zátěž běhu s vašimi běhy za posledních 8 týdnů (pod / obvyklé / nad / výrazně nad obvyklým). ‚Tep při tempu' ukazuje, o kolik byl tep vyšší nebo nižší, než kolik obvykle potřebujete na stejné tempo — výrazně vyšší tep při lehkém tempu bývá známkou únavy, horka nebo nemoci.",
  hrZones:
    "Tepové zóny z tepové rezervy (Karvonen): maximální tep bereme z profilu, pokud ho zadáte (změřený v testu nebo závodě), jinak ho odhadujeme z vašich nejtěžších běhů a věku — pak je u zón štítek „odhad“. Klidový tep je z nočních měření. Z4+ (≥ 80 % rezervy) = tvrdá práce — z ní se počítá kanál intenzity.",
  todayCapacity:
    "Dnešní kapacita = kolik si dnes můžete dovolit, aby: (1) posledních 7 dní nepřekročilo vaši týdenní kapacitu — tu samou, kterou ukazuje Zátěž (kapacita + 15 % rezerva, podle připravenosti v týdnu), (2) tento týden zůstal v cíli podle cyklu (90 / 100 / 110 / 55 %), (3) žádný jednotlivý běh nepřesáhl kapacitu jednoho běhu, (4) celková zátěž (tep × čas ze všech aktivit) zůstala pod stropem. Platí nejpřísnější z nich — u každého kanálu je vidět, který. Když je mechanika nad prahem 25, dnešek se dál zmenšuje (objem −20 %, intenzita a klesání na polovinu); když je nad prahem zátěž, přichází odlehčovací týden. Tak obě osy zůstanou pod prahem.",
  weekBudget:
    "Týdenní cíl jede ve 4týdenním cyklu: 1. týden 90 %, 2. týden 100 %, 3. týden 110 % referenčního týdne (posledního plného týdne před minulým odlehčovacím), 4. týden odlehčovací — 55 % třetího týdne. Kde v cyklu jste, pozná aplikace z posledního odlehčovacího týdne, jinak z toho, jak náročný byl minulý týden proti vaší normě. Cíl nikdy nepřekročí strop vaší týdenní kapacity (Zátěž); při zvýšené zátěži přijde odlehčovací týden dřív, před závodem ladění. Prvních 6 týdnů dat cyklus ještě neběží: cílem je minulý týden + 10 %, dlouhý běh nejvýš o 10 % delší než nejdelší za 30 dní a intenzita ani převýšení nic neblokují. Po zranění, které označíte jako zahojené, jdou 3 týdny postupného návratu (50 / 75 / 90 % týdne před zraněním). Vzorec 3 + 1 je běžná praxe periodizace ve vytrvalostních sportech (Issurin 2010, Mujika 2018): zátěž musí střídat regenerace (Meeusen 2013); přesná procenta jsou zavedená konvence, proto ji pořád hlídá kapacita a denní připravenost.",
  readinessTraining:
    "Připravenost (20–100 %) = odchylka HRV, klidového tepu (poslední noc i průměr 7 nocí), spánku a check-inu od vaší normy za 8 týdnů. HRV i klidový tep ~1,1 SD mimo normu → kolem 70 %, ~1,75 SD → kolem 40 %. Pod 65 % dnes bez tvrdého tréninku a dlouhého běhu, pod 45 % jen regenerace; zmenšuje i dnešní strop na jeden běh. Týdenní cíl z cyklu nemění.",
}

// Mechanika cards are keyed by their Czech label at the call site.
export const MECH_INFO_BY_LABEL: Record<string, string> = {
  "Vertikální poměr": METRIC_INFO.vertRatio,
  "Kontakt se zemí": METRIC_INFO.gct,
  "Symetrie kontaktu": METRIC_INFO.gctBalance,
  Kadence: METRIC_INFO.cadence,
  "Délka kroku": METRIC_INFO.strideLen,
  "Vertikální oscilace": METRIC_INFO.vertOsc,
  "Poměr kontaktu": "Podíl doby kontaktu se zemí na celkové délce kroku (duty factor). Nižší bývá pružnější, ekonomičtější běh. Hodnotí se proti vaší baseline ve srovnatelném tempu — nárůst doprovází únavu.",
}
