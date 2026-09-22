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
    "Efektivní „plochý ekvivalent\" kilometrů za 7 dní — vzdálenost přepočtená podle energetické náročnosti sklonu (Minetti). Kopcovitý běh stojí víc než stejně dlouhý po rovině, takže tohle číslo je vyšší než reálné km na členitém terénu. Citlivý engine z toho počítá i skok v zátěži, aby hilly běh nepodhodnotil.",
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
