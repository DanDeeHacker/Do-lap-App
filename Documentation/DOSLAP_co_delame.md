# Došlap — co náš startup dělá

## Shrnutí

Došlap propojuje sportovce a fyzioterapeuty do jednoho digitálního prostředí, které dnes
mezi nimi chybí. Sportovcům dává den co den srozumitelný obraz o tom, jak jejich pohyb
zatěžuje pohybový aparát a kdy je čas jednat. Fyzioterapeutům dává provozní infrastrukturu,
která nahrazuje dnešní roztříštěné a papírové procesy, a napojuje je přímo na klienty se
skutečnými daty. Klíčovou hodnotou je **digitální kontinuita** mezi klientem a fyziem — od
prohlídky, přes plán a jeho průběžné úpravy, až po další kontrolu.

Jako vstupní klín (wedge) používáme **běžce**: mají hustá data z wearables, jasnou motivaci
předcházet zraněním a přirozený cyklus, ve kterém se problémy dají zachytit včas.

---

## Rozhraní 1 — Sportovec (běžec)

Cílem je, aby běžec **transparentně věděl o dopadu svého pohybu na pohybový aparát** a měl
včas signál, jestli je potřeba zpomalit nebo vyhledat odborníka.

**Sběr dat.** V ideálním režimu aplikace čerpá data z wearables (běžecká dynamika, tepová
odezva, spánek a regenerace). V omezeném režimu — bez chytrých hodinek — sportovec vede
alespoň strukturovaný **deník** (běhy, bolesti, nálada, subjektivní zátěž), který sám o sobě
stačí k základnímu vyhodnocení.

**Denní vyhodnocení stavu.** Z dat se každý den skládá aktuální stav do jednoho ze čtyř polí
kvadrantu:

- **Stabilní** — zátěž i mechanika sedí na vlastní normě.
- **Tichý drift** — mechanika se mění, aniž by to sportovec cítil (časný, „tichý" signál).
- **Odlehčit** — zátěž vyskočila nad obvyklou úroveň, je čas ubrat a hlídat regeneraci.
- **Domluvit schůzku s fyziem** — kritická kombinace, kdy má smysl vyhledat odborníka.

Stav vzniká ze tří os: **mechaniky pohybu** (drift běžecké techniky proti vlastní normě ve
srovnatelném tempu a terénu — ne proti populačnímu průměru), **zátěže** (akutní vs. chronická
zátěž, monotónnost, vysoká intenzita, sbíhání, regenerace přes noc) a **výsledků z deníku**
(bolesti a jejich opakování, subjektivní příznaky). Sportovec vidí nejen výsledné skóre, ale i
**co ho tvoří** a jak se vyvíjelo v čase, takže rozhodnutí je pochopitelné, ne černá skříňka.

Tím se běžec dostává od pouhého „naběhal jsem X km" k porozumění, **kolik toho unese a jak se
z toho dostává** — a hlavně ke včasnému varování dřív, než se z mikrozměny stane zranění.

---

## Rozhraní 2 — Fyzioterapeut (jednotlivci i sportovní kliniky)

Na straně fyzioterapie stavíme **infrastrukturu**, protože dnešní procesy jsou z vlastní
zkušenosti zastaralé: online formuláře a e-maily pro registraci, papírové dotazníky na místě,
žádné digitální záznamy z prohlídek, žádná kontinuita mezi návštěvami a žádná přímá digitální
konzultace nastaveného plánu.

Došlap pro fyzio nabízí jednotné prostředí pro:

- **Plánování a objednávání** — kalendář, sloty, rezervace.
- **Komunikaci s klienty** — chat a sdílení navázané přímo na klientská data.
- **Registraci nových klientů** — digitálně, bez papírů a přepisování.
- **Akvizici nových klientů** — v pozdější fázi jako jeden z kanálů přes Rozhraní 1
  (sportovci, jejichž stav ukazuje potřebu odborníka, se propojí s vhodným fyziem).
- **Tvorbu programů** pro klienty s rozpisem do týdne.
- **Souhrn ze sezení** — s možností nahrát transcript prohlídky.
- **Databázi cviků** — výběr z odborné databáze fyzio cviků (externí partner přes API /
  spolupráci).
- **Přehled dat z wearables** — ve zkrácené verzi (bez detailu jednotlivých běhů).
- **Vyhodnocení aktuálního stavu klienta** s možností **AI souhrnu**, který experta provede
  pohybovými vzorci klienta a nasměruje ho k potenciálním úskalím — jako asistent, ne náhrada
  úsudku.

Fyzio má tak před sebou klienta i s kontextem: historii, data, progres a vývoj v čase.

*Poznámka: v této verzi rozhraní pro fyzioterapeuty zatím není plně dodělané.*

---

## Digitální kontinuita — jádro hodnoty

U obou rozhraní je cílem **udržet spojení mezi klientem a fyziem i mezi návštěvami**, pokud je
to žádané. Konkrétně po prohlídce:

1. Klient obdrží **soupis z prohlídky** — nejprve vytvořený z transcriptu a AI, poté
   **potvrzený a upravený expertem** (expert má vždy poslední slovo).
2. Dostane **akční kroky a tipy** a **program v aplikaci** s jednoduchým rozpisem do týdne.
3. Program si **dynamicky odklikává**, vidí **progres** a může si dělat **poznámky**.
4. Přes **chat** může poslat zprávu fyziovi, který v omezené míře odpoví na danou strukturu
   tréninku a **přizpůsobí plán dřív než na další prohlídce** (typicky až za měsíc).
5. Fyzio na své straně vidí **progres klienta, chat a další vývoj v jeho datech**.

Tím se z jednorázové prohlídky stává **průběžný, datově podložený vztah** — klient není
odkázán měsíc na sebe a fyzio nepracuje naslepo.

---

## Proč to dává smysl

- **Pro sportovce:** včasné varování a srozumitelný obraz o vlastním těle, ne jen kilometry.
- **Pro fyzio:** moderní provoz, méně administrativy, klient s kontextem a nový kanál akvizice.
- **Pro celý systém:** prevence a kontinuita místo hašení už vzniklých zranění.

Běžci jsou ideálním prvním trhem; odtud se model rozšiřuje na další sporty a na širší
spolupráci se sportovními i individuálními fyzio klinikami.
