# Došlap — platforma pro monitoring běžecké zátěže a mechaniky

Reálný backend (FastAPI + SQLite) se skutečným přihlášením, čtyřmi oddělenými
rolemi a enginem v0.4 pro monitoring rizikových signálů (interně „injury-risk
engine"). Frontend zůstal beze změny architektury — statické HTML/JS bez
buildu — jen teď mluví se skutečným API místo dat v paměti.

**Pozicování (MDR):** Došlap je nástroj pro monitoring tréninkové zátěže a
běžecké mechaniky a pro podporu rozhodování odborníka — **není zdravotnický
prostředek**, nestanovuje diagnózu ani neurčuje léčbu a nenahrazuje vyšetření.
Skóre je pravděpodobnostní vstup pro fyzioterapeuta, ne predikce ani prognóza
onemocnění. Persistentní disclaimer (`D.MDR_DISCLAIMER` v `core.js`) se
zobrazuje na každé stránce.

## Rychlý start

Vyžaduje Python 3.10+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Otevřete `http://127.0.0.1:8000/`. Backend při prvním spuštění sám vytvoří
`backend/dosslap.db` (SQLite) a naplní ho deterministickými demo daty —
stejná kohorta 10 běžců, jaká byla v čistě klientském prototypu, teď ale
uložená doopravdy.

### Demo účty

Všechny s heslem `demo1234`:

| Role | E-mail | Kdo |
|---|---|---|
| Běžec / pacient | `adela@demo.cz` | Adéla Kučerová, drift vertikálního poměru |
| Fyzioterapeut | `havlickova@fyzioholesovice.cz` | má už převzatý případ Adély |
| Zaměstnavatel | `hexanet@demo.cz` | Hexanet s.r.o. (kohorta pod prahem 8 — ukazuje blokovaný stav) |
| Partner | `letna@demo.cz` | Běžecká speciálka Letná |

### AI souhrn — volitelné napojení na skutečný model

`physio.html`'s AI souhrn počítá fakta vždy stejně (deterministicky, z
reálných čísel pacienta — viz Engine v0.4 níže). Bez nastaveného klíče se
zobrazí jen tahle strukturovaná fakta, přesně jako dřív. S klíčem přibyde
navíc přirozeně psané shrnutí od skutečného LLM (NVIDIA NIM,
build.nvidia.com) — model dostane jen už vypočítaná fakta a smí je jen
narativně shrnout, ne vymýšlet nová.

```bash
# 1. https://build.nvidia.com/nim → přihlásit se → vybrat model → "Get API Key"
# 2. nastavit před spuštěním backendu:
$env:NVIDIA_API_KEY = "nvapi-..."          # PowerShell, jen pro tuhle relaci
setx NVIDIA_API_KEY "nvapi-..."            # PowerShell, trvale pro nové okna
```

Výchozí model je `google/gemma-4-31b-it` (Llama 3.3 70B NVIDIA 26. 8. 2026
vyřadila); jiný lze nastavit přes `NVIDIA_MODEL`. Bez klíče appka funguje úplně stejně jako předtím — jde o
čistě přídavnou vrstvu.

### Závěr z prohlídky + přepis audia (v0.6)

Fyzioterapeut po sezení sepíše závěr vázaný ke konkrétnímu termínu
(`physio.html → detail pacienta → Termíny a závěry`): nahraje audio (nebo
soubor), to se přepíše přes ASR a **hned zahodí** — ukládá se jen text —,
LLM z přepisu navrhne shrnutí, fyzio ho upraví a **schválí**. Teprve
schválením se závěr sdílí s pacientem a — pokud fyzio vyplnil strukturovaný
OSTRC výsledek — zapíše se jako **potvrzené zranění stupně A**
(`source='physio_conclusion'`), hlavní podklad pro kalibraci enginu.

ASR je volitelné a oddělené od chat modelu — míří na jakýkoli
OpenAI-kompatibilní `/audio/transcriptions` endpoint:

```bash
$env:ASR_BASE_URL = "https://…/v1"     # host s /audio/transcriptions
$env:ASR_API_KEY  = "…"                # když chybí, padá na NVIDIA_API_KEY
$env:ASR_MODEL    = "whisper-1"        # výchozí
```

Bez `ASR_BASE_URL` appka nespadne — fyzio jen přepis doplní ručně.

### Návrat k běhu (v0.6)

Uzavírá smyčku po závěru: fyzioterapeut založí progresivní walk/run žebřík
(`physio.html → detail pacienta → Založit návrat k běhu`), pacient po každém
sezení nahlásí bolest (`runner.html`, karta „Návrat k běhu"). Plán se posune
o úroveň až po `sessions_per_level` sezeních s bolestí do `pain_threshold`;
sezení nad práh je zaznamenaný **setback**, který žebřík neposune a upozorní
fyzioterapeuta. Postup se počítá na serveru z celé historie (řadí úrovně po
pořadí, idempotentní). Výchozí žebřík má 6 úrovní od 1 min běhu / 2 min chůze
po 25 min souvislého lehkého běhu; fyzio ho může přepsat.

Registrace je otevřená pro všechny čtyři role přímo z `auth.html` — pro
testování není potřeba použít zrovna demo účty.

## Struktura

| Cesta | Co to je |
|---|---|
| `index.html` | Veřejná rozcestníková stránka, nevyžaduje přihlášení |
| `auth.html` | Přihlášení a registrace — čtyři oddělené „dveře" podle role |
| `runner.html` | Běžec / pacient — 6 záložek |
| `physio.html` | Fyzioterapeut — fronta + detail pacienta se 6 podzáložkami |
| `employer.html` | Zaměstnavatel — 4 záložky, jen serverem agregovaná kohorta |
| `partner.html` | Partner (prodejna, klub, pořadatel) — 3 záložky |
| `data.html` | Připojení Garminu, vlastní data, engine, log volání API |
| `core.js` | UI komponenty, navigace, reálné API/AUTH klienti, slovník signálů |
| `bodymap.js` | Anatomická silueta pro označení bolesti (beze změny) |
| `styles.css` | Designový systém, mobil jako primární rozhraní |
| `backend/app/` | FastAPI aplikace |
| `backend/app/models.py` | SQLAlchemy schéma (SQLite) |
| `backend/app/metrics/engine.py` | Injury-risk engine v0.4 — přepis `core.js`'s `metrics` do Pythonu |
| `backend/app/metrics/ai_brief.py` | Generátor AI souhrnu pro fyzioterapeuta |
| `backend/app/seed.py` | Deterministický demo dataset, seedovaný při prvním startu |
| `backend/app/routers/` | REST endpointy, jeden soubor na doménu |
| `backend/garmin_ingest.py` | Převod skutečného Garmin exportu do schématu platformy (CLI i import v aplikaci sdílejí `build_seed()`) |
| `backend/fitreader.py` | Dekodér FIT souborů bez závislostí |
| `backend/tests/` | pytest — pokrývá přihlášení a hranice přístupu mezi rolemi |

## Přihlášení a role

Čtyři role, čtyři oddělené vstupy na `auth.html`, žádné přepínání účtů z
menu jako v prototypu. Přihlášení běží na serverové relaci (httpOnly cookie,
heslo hashované Argon2), ne na simulaci. Google OAuth zůstává jen naznačený
souhlasový dialog — reálné napojení potřebuje vlastní OAuth klienta v Google
Cloud Console.

Každý endpoint na backendu ověřuje, že přihlášený uživatel smí vidět zrovna
tahle data:

- **Běžec** vidí a upravuje jen svůj vlastní záznam.
- **Fyzioterapeut** vidí pacienta až po převzetí případu z fronty triáže
  (vytvoří se `care_assignments` řádek). AI souhrn je jen pro tuhle roli.
- **Zaměstnavatel** nikdy nedostane řádek po jednotlivém běžci — endpoint
  `/api/employers/{id}/cohort` počítá agregáty na serveru a pod 8 zapojenými
  lidmi nevrátí nic. I nad prahem se malé buňky (1–2 lidé) zaokrouhlují na
  „≤2", aby se ani skládáním filtrů nedal dopočítat jednotlivec.
- **Partner** vidí jen svá vlastní doporučení.

### Přístupový audit (GDPR, v0.6)

Právo subjektu údajů vědět, kdo jeho zdravotní data četl: audit middleware
(`app/main.py`) zaznamenává každý přístup fyzioterapeuta k záznamu běžce
(`/api/runners/{rid}/*`) do `access_log`, deduplikovaně po dni a akci
(čtení/zápis) s počítadlem. Běžcovy vlastní požadavky se nelogují. Běžec
(i jeho fyzio) to vidí přes `GET /api/runners/{rid}/access-log` a v
`data.html` v kartě „Kdo přistupoval k vašim datům". Šifrování citlivých
polí at-rest a přechod na PostgreSQL zůstávají věcí nasazení (schéma je na
Postgres připravené, viz níže).

### Objednání fyzioterapie — souhlas, výběr termínu, potvrzení (v0.6)

Celý tok je řízený souhlasem a oboustranným potvrzením:

1. **Souhlas** — běžec musí nejdřív potvrdit zájem o službu
   (`POST /api/runners/{rid}/physio-interest`). Dokud nepotvrdí, je pro
   fyzioterapeuty **neviditelný** — fronta triáže ho vůbec nezobrazí
   (consent gate v `triage.py`). Zájem lze kdykoli vzít zpět.
2. **Dispozice fyzia** — každý fyzioterapeut spravuje své volné termíny
   (`PhysioSlot`, `POST/DELETE /api/physios/{pid}/slots`).
3. **Výběr** — běžec filtruje podle svých preferencí (dny + část dne) a vidí
   partnerské kliniky + fyzioterapeuty s popisem a zkušenostmi a jejich
   volnými termíny (`GET /api/booking/options?dow=&daypart=`).
4. **Žádost → potvrzení** — běžec požádá o konkrétní slot
   (`POST /api/booking/request`, stav `requested`), fyzio ji musí potvrdit
   (`POST /api/bookings/{bid}/confirm`) — teprve tím vznikne `care_assignment`
   (přístup k datům) a termín padne oběma do kalendáře. Fyzio může odmítnout
   (`/decline`), slot se uvolní.
5. **Odmítnutí fyzia** — běžec může kdykoli zrušit rezervaci
   (`/bookings/{bid}/cancel`) nebo úplně **odvolat spolupráci s fyziem**
   (`/physios/{pid}/decline`) — tím fyziovi odebere přístup ke svým datům
   (care assignment → `revoked`) a případ se vrátí do fronty.
6. **Připomínka den předem** — potvrzený termín do 24 h se objeví oběma
   stranám jako reminder s info, které spravuje fyzio/klinika
   (`PATCH /api/bookings/{bid}/prep`); počítá se v bootstrapu (`due_reminders`).

## Engine v0.4

18 signálů ve třech osách, které se nesčítají do jednoho čísla:

```
                  MECHANIKA →
                  stabilní      driftuje
  Z   vysoká   │ přetížení    │ kritické
  Á            │ deload       │ objednat fyzio
  T   ─────────────────────────────────────
  Ě   běžná    │ stabilní     │ TICHÝ DRIFT
  Ž            │              │ ← obchodní klín
```

Proti předchozí verzi (v0.3, 14 signálů) přibylo:

- **Dvoustupňové pásmo EWMA poměru zátěže** — 1,30–1,50 „mírně zvýšený",
  nad 1,50 „zvýšený", podle metaanalýzy 46 studií z roku 2025, která ukázala
  jen mírně zvýšené riziko ve středním pásmu.
- **Kolísavá HRV mezi dny** (`hrvcv`) — den-k-dni variabilita HRV jako
  signál odlišný od poklesu průměru, který už engine sledoval.
- **Nepravidelná délka spánku** (`sleepreg`) — variabilita délky spánku,
  ne jen dluh proti průměru.
- **Bilance zátěže fitness–fatigue** (`tsb`) — Banisterův impulz-odezva
  model jako doplňkový pohled na EWMA poměr, lépe se chová při nízké
  chronické zátěži.

Každý signál nese stupeň evidence A/B/C a jde rozkliknout na vzorec, důvod,
**kde selhává** a kdy zmizí (`backend/app/metrics/sig_doc.py`, zrcadlené
v `core.js` pro UI). Žádná metrika se neporovnává s populační normou — jen
s vlastní normou běžce ve shodném terénu a tempu. Pod 60 % spolehlivosti
baseline se mechanické signály nezobrazí vůbec.

## Napojení na skutečná data z Garminu

```bash
python backend/garmin_ingest.py export.zip -o user_seed.json --fit
```

Ověřeno na reálném GDPR exportu: 85 běhů, prosinec 2025 → srpen 2026.

V aplikaci: `data.html → Připojení` přijme ZIP export přímo (i s FIT
soubory), nebo jen `summarizedActivities.json`. Upload jde na
`POST /api/integrations/garmin/import`, který volá tu samou `build_seed()`
funkci jako CLI skript výše — jeden parser, ne dvě rozjíždějící se kopie.

### Co reálná data ukázala

| Pole | Pokrytí | Odemyká |
|---|---|---|
| `vert_ratio_pct` | 99 % | drift vertikálního poměru |
| `gct_ms` | 99 % | drift kontaktu se zemí |
| `cadence_spm` | 99 % | normalizace GCT |
| `descent_m` | 93 % | excentrická zátěž |
| `splits[]` | 54 % | rozpad techniky uvnitř běhu |
| `workoutFeel` / `workoutRpe` | 42 % | pocit po tréninku |
| **`gct_balance_l`** | **0 %** | **symetrie kontaktu — nedostupné** |

**Symetrie kontaktu se ze zápěstí neměří.** Pole `avg_stance_time_balance`
(číslo 133) je deklarované ve všech 195 session zprávách FIT souborů, ale
ani v jedné vyplněné. Vyžaduje hrudní pás HRM-Pro / HRM-Run nebo Running
Dynamics Pod. Platforma proto tento signál u takového účtu vůbec
nezobrazí, místo aby ho počítala z chybějících dat.

### Apple Health (v0.6)

Druhá reálná file-based integrace vedle Garminu. iPhone → Zdraví → profil →
Exportovat všechna data → `export.zip` (nebo rozbalený `export.xml`).

```bash
python backend/apple_health_ingest.py export.zip -o user_seed.json
```

V aplikaci: `data.html → Připojení → Nahrát export z Apple Health`, upload
jde na `POST /api/integrations/apple/import` a prochází stejnou `_apply_seed()`
funkcí jako Garmin (jeden zápisový path, `provider="apple"`). Parser
(`backend/apple_health_ingest.py`, streamovaný `iterparse` kvůli velikosti
exportu) mapuje běžecké workouty → aktivity a HRV / klidový tep / spánek /
kroky → denní metriky. Běžecká dynamika (vertikální poměr, kontakt se zemí)
se ze zápěstí neagreguje po bězích, takže se u Apple účtu mechanická osa
neukáže — stejně poctivě jako u Garminu bez hrudního pásu.

### Přímé stažení z Garmin Connect (v0.6)

Kromě uploadu exportu jde stáhnout data i **přímo přihlášením** ke Garmin
Connect (`data.html → Připojení → „Stáhnout data přímo z Garmin Connect"`):
běžec zadá e-mail + heslo, backend přes knihovnu `python-garminconnect`
(`backend/garmin_live.py`) stáhne běžecké aktivity (posledních ~180 dní) a
denní wellness (HRV, klidový tep, spánek, kroky za ~35 dní), namapuje je do
schématu platformy a projde stejnou `_apply_seed()` funkcí jako ostatní
importy.

Přihlašovací údaje se použijí **jen pro jedno přihlášení a nikam se
neukládají** (`POST /api/integrations/garmin/connect`, runner-scoped).
Mapování z Connect API (metry/sekundy) je oddělené od GDPR exportu
(centimetry/milisekundy) — `map_activity()` / `assemble_seed()` jsou čisté
funkce pokryté testy. Účty s dvoufázovým ověřením (MFA) tento jednorázový
tok zatím nepodporuje — vrátí srozumitelnou chybu a nasměruje na upload
exportu.

Vyžaduje `pip install ../python-garminconnect-master` (viz `requirements.txt`).

### Průběžné napojení

Garmin Health & Activity API (OAuth 2.0 + PKCE, webhook na nové aktivity)
vyžaduje schválení programu ze strany Garminu. Do té doby je jednorázový
export plnohodnotný pro validaci enginu — chybí mu jen průběžnost.

## Testy

```bash
cd backend
pytest
```

Pokrývá bezpečnostně kritické cesty: registraci/přihlášení/špatné
heslo/expirovanou relaci, že běžec nedostane data jiného běžce, že fyzio
nemá přístup před převzetím případu a má po něm, že zaměstnavatel pod
prahem 8 lidí nedostane nic a nad prahem nedostane nikdy per-runner řádek.

Od v0.6 navíc pokrývá: OSTRC-H sběr výsledku a jeho signál v enginu, celý
tok závěru z prohlídky (draft → schválení → grade-A InjuryReport), návrat
k běhu (postup, setback, dokončení, scoping), region-scope fronty triáže,
Apple Health import a GDPR přístupový audit. Ověřeno na Pythonu 3.13.

## Známá omezení

- Google OAuth i průběžné Garmin OAuth napojení jsou naznačené, ne funkční
  — chybí vlastní klient/schválení. Jednorázový upload exportu je funkční.
- SQLite je zvolené pro jednoduchost lokálního testování (žádný server
  navíc). Schéma nebrání pozdějšímu přechodu na PostgreSQL.
- Fronta triáže je od v0.6 scopovaná podle regionu kliniky — fyzioterapeut
  vidí ve výchozím stavu jen případy ze svého regionu (odvozeno z města,
  „Praha 7" i „Praha" spadají do regionu „praha"), s přepínačem „Celá
  platforma" pro záskok/přetok. Účet bez přiřazené kliniky vidí vše.
  Region je hrubý (podle města), ne skutečné spádové oblasti klinik.
- Prahové hodnoty jsou čitelné a auditovatelné, **ne validované cut-pointy**.
  Než se systém dotkne skutečného běžce, musí je podepsat klinický garant
  a kalibrovat je proti reálným výsledkům ve vlastní kohortě. Od v0.6 už
  platforma ten **výsledek sbírá** (OSTRC-H dotazník, `injury_reports` —
  týdenní nudge i ad-hoc hlášení, autoritativně pak závěr od fyzioterapeuta),
  takže label pro kalibraci vzniká průběžně. Samotná kalibrace prahů proti
  těmto datům je pořád největší otevřená položka — teď už ale máme proti
  čemu ji dělat.
- Modelovaná návratnost u zaměstnavatele je aritmetika nad předpoklady,
  označená jako taková. Do prezentace pro vedení patří jen s tou větou.
- Průběžné napojení Garminu i Strava OAuth zůstávají blokované schválením
  třetí strany; jednorázový file-import (Garmin, Apple Health) je funkční.
- Šifrování citlivých polí at-rest a přechod na PostgreSQL jsou věcí
  nasazení — schéma na Postgres připravené je, přístupový audit hotový.
