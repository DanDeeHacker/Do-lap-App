# Došlap redesign brief (v2), for Claude Code

This brief is the build spec for restyling the Došlap runner app in `frontend/src` (React 19, Tailwind 4, Vite). The visual companion is the "Došlap Redesign" artifact, which has mockups of every screen. When the two disagree, **this file wins**.

Change tags used below:

| Tag | Meaning |
|---|---|
| KEEP | Behaviour and content stay exactly as they are. |
| RESTYLE | Same behaviour, new look. |
| ADD | New visual element that uses only data the frontend already has. |
| FIX | A small bug fix. Do it. |
| OPT | Structural change. **Do not build it** unless the owner names it explicitly ("implement OPT-3"). |

---

## 1. Ground rules

1. **Restyle, don't restructure.** Keep every route (`/auth`, `/app/:tab` with `today|training|post|mechanics|load|messages`, the `program` redirect, `/data`, `/engine`, `/engines`) and every tab in its current order: Dnes · Trénink (v3 engine only) · Deník · Pohyb · Zátěž · Péče. Both navigation bars keep reading from `useRunnerNav()`.
2. Keep **every module on every tab, in its current order** (see the module maps in section 6). Nothing is removed, merged away or moved to another tab.
3. Keep all data calls (`api.ts`), the store (`store.tsx`), calculations, thresholds, tier and quadrant logic, and the chart-endpoint reconciliation (the last point pinned to the live score).
4. Keep all Czech copy, the MDR disclaimer and every `metricinfo.ts` text. The only exceptions are the FIX items.
5. Keep every interaction in section 5.
6. Keep app-level features: notes mode (`annotate.tsx`, including `data-annot-ui`), the update banner (`updateCheck.ts`), toasts, the Garmin one-tap sync, and the PWA hardening in `index.css` (safe areas, 16 px inputs on coarse pointers, dvh, `overflow-x: clip`, the grid `min-width: 0` rule, reduced motion).
7. Only the visual layer changes: tokens, shared component styling, icons (`lucide-react`), chart styling, and arrangement *inside* a module where this brief says so.

---

## 2. Tokens (put them in `index.css` `@theme`)

```css
@theme {
  --font-serif: "Libre Baskerville", Georgia, serif;
  --font-sans: "Manrope", Arial, sans-serif;
  --font-mono: "DM Mono", monospace;

  --color-bg: #061010;
  --color-raised: #17302a;            /* sheets, tooltips, menus, toasts */
  --color-text: #eef6f2;
  --color-text-2: #a9bfb7;            /* secondary, ≥ 4.5:1 on bg */
  --color-text-3: #7f958e;            /* captions/axes, ≥ 12px only */
  --color-accent: #c7ff54;            /* primary action, active tab, selected, Check-in, switch on */
  --color-ok: #4fd69c;                /* status: normal / stable / ready */
  --color-watch: #f2c46d;
  --color-alert: #f0795a;
  --color-load: #8a95ff;              /* ADD: training load lines/gauges */
  --color-info: #6ce6d3;              /* neutral data lines, links in cards (brand teal) */
  --color-self: #7fb0d6;              /* weekly OSTRC, silent-drift quadrant */
}
```

- **Card surface:** `background: linear-gradient(160deg, rgb(255 255 255 / .055), rgb(255 255 255 / .015)); border: 1px solid rgb(255 255 255 / .08); border-radius: 20px`. Make it a utility or a component class.
- **Nested surface** (rows, stat tiles, channel cards): `rgb(255 255 255 / .035)`, 1px `rgb(255 255 255 / .07)`, radius 14.
- **Delete** the repaint rules in `index.css` (the `.bg-\[#…\]`, `.text-\[#…\]` and `.border-\[#…\]` remaps, currently lines 40–63). Replace every hard-coded hex class in the components with the tokens above.
- **Quadrant colours** stay: stable = ok, silent drift = self, overreaching = watch, critical = alert. Grade chips: A = alert, B = watch, C = ok.
- **Type scale:**
  - Page title: serif 28 px (phone) / 36 px (desktop), −0.02em.
  - Card title / verdict: serif 19–22 px.
  - Hero number: Manrope 800, 40–44 px, tabular, −0.03em.
  - KPI number: Manrope 800, 20–28 px.
  - Body: 13–14 px (phone) / 14–15 px (desktop).
  - Label: Manrope 700, 11 px, caps, +0.12em.
  - Caption: 11 px.
  - DM Mono: axes and small numeric tables only.
  - **Minimum text size is 11 px.** Numbers that are currently serif (`font-serif text-4xl` values) become Manrope 800 tabular.
- **Spacing:** 4 px grid. Card padding 14 / 20. Gap between cards 12 / 16. Gutters as today.
- **Radius:** card 20, nested 14, input 12, pill 999, sheet 26.
- **Elevation:** cards are flat. Only sheets, menus, tooltips and the Check-in button have shadows.
- **Motion:**
  - Keep the scroll reveal, but use `cardRevealLite` at every width.
  - Hover lift 1–2 px, 180 ms.
  - Sheet slides up in 280 ms `cubic-bezier(.22,1,.36,1)`.
  - Tooltip fades in over 140 ms.
  - Under reduced motion, everything becomes a fade.
- **Focus:** 2 px lime outline, 3 px offset (replaces `#e47d51`).

---

## 3. App shell (identical on every routed page)

| Part | Component | Spec | Tag |
|---|---|---|---|
| Top bar | `Topbar` | 68 px + safe area. Bg at 92% with blur, 1 px bottom line. Phone: logo mark. Desktop (`md+`): mark and "došlap", centred tab pills (active = lime fill), notes toggle, avatar. | RESTYLE |
| Profile menu | `Topbar` | Same items and order: header (name, "běžecký profil", data status, goal) · Upravit profil (ProfileSheet) · Data a připojení · Citlivostní analýza · Odhlásit se. Raised surface with icons. Closes on outside tap. | KEEP / RESTYLE |
| Tab bar (phone) | `AtlasNav` | Lucide icons: house, target, notebook-pen, footprints, activity, heart-handshake. 10 px bold labels. Active tab: lime icon and label with a 40×26 pill at 14% lime. Tap targets ≥ 44 px. Hidden from `md` up. | RESTYLE |
| Check-in button | `AtlasBubble` | Bottom-right pill, same position (phone `bottom: calc(4.75rem + safe-area)`, desktop 28 px from the corner). Heart icon and "Check-in". | RESTYLE |
| Notes toggle | `AnnotateToggle` | 32 px round. On = lime. Red count badge. Keep `data-annot-ui`. | KEEP |
| Update banner | `Layout` | Raised pill under the top bar with the lime "Aktualizovat" button. | RESTYLE |
| Main | `Layout > main` | Remove the decorative orbit ring (`main::before`). Keep the radial glow on the background. **FIX-5:** bottom padding = tab bar + Check-in button + 16 px. | RESTYLE / FIX |

`/data`, `/engine` and `/engines` use the same shell with no tab active.

---

## 4. Shared components (`ui.tsx` plus new small components)

| Component | Spec |
|---|---|
| **Button** | Variants: primary (lime), secondary (white 8%), outline (1 px white 20%), danger (alert). Sizes: md (10/14 px padding), sm (7/11). States: hover lifts 1 px and brightens; pressed scales to .97; focus shows the ring; disabled at 40% opacity; busy keeps the width and swaps the label (existing texts like "Ukládám…"), with a spinning icon for sync. |
| **Chip** (`Chip`) | Tones ok / watch / alert / load / info / self / muted / accent. 10.5–11 px bold, pill. |
| **Segmented** (new) | Track white 6%, active = `--color-text` fill with dark text. Used for Pohyb terrain, Péče sub-tabs, Data sources, RateSheet front/back and race priority. Trénink cycle keeps `role="radiogroup"` and `role="radio"`. |
| **Card** | Card surface. The `Card` in App.tsx keeps its hover lift; hover gives a brighter outline (`info` 45%) and a soft shadow. |
| **ListRow** | 34 px icon tile, title, meta line, trailing chevron, chip or button. Used in Deník, run history, Data. |
| **AlertBanner** (new) | Tones `stop` (always open), `alert`, `watch`, `info`. Icon tile, title, text, chevron. Collapsed = title only; tap toggles in place. |
| **FactorBar** (new) | Label, value, `+pts`, and a 6 px bar with width relative to the largest factor, coloured by grade or tone. Replaces the "Co tvoří skóre …" number lists. |
| **InfoDot** | KEEP all logic (portal, clamp, flip, close on outside / scroll / resize). 20 px ring button in lime 70%. Tooltip on the raised surface, radius 12, 11–12 px text. |
| **Charts** (`AxisLineChart`, `Bars`, `Sparkline`, `NumberedChart`) | KEEP the pointer logic. Tooltip = raised card, value in the series colour, date in mono. Guide line at 45%. Endpoint dot with a dark halo. Grid lines at 6–10%. Area fill at 12%. **FIX-2:** no stretched text (move text out of `preserveAspectRatio="none"` SVGs into HTML overlays). Optional zone bands via `<rect>` above the thresholds. Bars coloured by status when a tier is known; the scrubbed bar is lime. |
| **RangeBar** (`RecoveryRanges`, `MechMetricCard`) | Band = usual range (ok at 32%), tick = midpoint, dot plus value = today in its tone colour, and a numeric axis below. |
| **HeadroomBar** | Fill in tone colour, white ceiling marker. |
| **Ring** | Stroke 10, tone colour, Manrope number in the centre. |
| **Slider** | KEEP the native `input[type=range]`. Styled 8 px track, 22 px thumb, value label on the right in the meaning colour (pain uses an ok → alert gradient). |
| **Sheet** | KEEP the behaviour (bottom on phone, centred on desktop, backdrop close, handle, sticky footer). Raised surface, radius 26, serif title. |
| **Toast** | Raised surface. Bottom centre as today. |
| **Empty / LoadGate** | `Empty` gets an icon and a dashed border. The loading text keeps its wording, with a skeleton behind it. `LoadGate` error uses AlertBanner with "Zkusit znovu". |
| **Switch** | 40×24. On = lime (alert for the pain function questions). Keep `role="switch"` and `aria-checked`. |

---

## 5. Interaction inventory (must keep working)

- **InfoDot everywhere:** hover on desktop, tap on phone, portal, viewport clamp, flip near the top, close on outside tap, scroll or resize.
- **Chart scrub:** `AxisLineChart`, `Bars`, `Sparkline`, `NumberedChart` use pointer capture with `touch-action: pan-y`, a guide line and a tooltip, and hide on pointer up or leave.
- **Card hover lift** (desktop).
- **Top bar:** avatar opens the profile menu → ProfileSheet (10 fields) / Data / Engine / Logout. The notes toggle turns on notes mode (click to pin, Esc to exit).
- **Check-in** (`AtlasBubble`):
  - Mood (5 options) and 3 sliders.
  - When pain > 0: body map (multi-select) and 3 function switches.
  - When movement is limited or the runner limps: an inline warning.
  - When pain > 3: a warning box.
  - Note, 3 mini stats, save → toast → refresh.
- **Dnes:**
  - Garmin sync button: disabled without a token, with a tooltip; spinning while syncing; result line after.
  - "historie 6 měsíců" and the 2×2 grid open `QuadrantHistory`: a full panel under the top bar; hover or tap a bar to see that day's axes and signals; × closes it.
  - `InjuryPrompt` → `InjurySheet`, pre-filled with sites and answers.
  - `WeeklyCheckButton`: "Bez obtíží" saves in one tap; "Obtíže" opens `InjurySheet`; the buttons are hidden once the check is done.
- **Trénink:**
  - Every session chip is selectable, **including not-allowed ones** (they show their parameters and the reason).
  - Cycle week radio → inline confirm (Přepnout / Zrušit), tooltips on locked states, "Vrátit automaticky".
  - Races: "+ Přidat závod" inline form (date, name, km with quick-distance chips, priority A/B/C, save / cancel) and ✕ to delete.
- **Deník:** a pending run opens RateSheet (new); an entry opens RateSheet (edit). The sheet has 5 sliders, a note, a body map (front/back, multi, L/R), save and cancel.
- **Pohyb:**
  - Metric accordion: one open at a time, the whole card toggles, and the open card shows baseline text plus the full trend with band and scrub.
  - Terrain segmented switch ↔ `TerrainMatrix` (horizontal scroll).
  - "Historie běhů" toggle (lazy fetch) → tap a run (one open) → `RunContext`, `SegmentTimeline` (tap a strip to select a segment, ‹ › stepping, "Kde se běh lišil" list), `MonthCompare`, and `ExcludeRun` (inline confirm / restore).
- **Péče:**
  - Sub-tabs.
  - Interest → confirmed with "zrušit" undo → "Naplánovat schůzku" → `FindSlotSheet` (day and part-of-day chips reload results; tapping a slot requests it, shows a toast and closes the sheet).
  - Bookings with "Zrušit". Spolupráce with "Odvolat".
  - Chat send (Enter or button).
  - Program "Hotovo".
  - Zdraví: report, mark healed, `RtrSheet`.
- **Data:** engine switch, "Porovnat enginy" link, 3 downloads, AI consent switch and text previews, source tabs, file uploads, Garmin login / 2FA / sync / detailed data / terrain / auto-sync / disconnect, Apple copy URL / copy token / rotate token.

---

## 6. Tabs: module maps (current order is kept)

### Dnes (`App.tsx → TodayV2`)
1. Date label and greeting (serif): RESTYLE.
2. Error banner: RESTYLE with AlertBanner and "Zkusit znovu".
3. **Alert stack** (RESTYLE):
   - Covers painWarn, functionLimit.severe, acuteOverload, painMonitor.morningWorse, painMonitor.trend, races.warnings and raceRecovery, in the same order and with the same conditions as the code.
   - `functionLimit.severe` and `morningWorse` use tone `stop` and are always expanded.
   - Of the rest, the first is expanded and the others are collapsed (tap to expand in place, one open at a time).
   - All text is kept.
4. InjuryPrompt: the last row of the stack, with a danger "Nahlásit zranění" button. RESTYLE.
5. **State card** (RESTYLE):
   - Top row: quadrant chip (colour dot and name) · sync button (icon, with the same tooltip and states) · "6 měs." history button.
   - Centre: overall ring (`a.overall`, tier colour, number and "celkový stav").
   - Left side stats: Regenerace (`rcv.score`) and Mechanika (`a.mech`). Right side stats: Zátěž (`a.load`, load colour) and Příznaky (`a.symp`). The axis values are ADD.
   - Below the ring: the verdict title (the `recur` override logic stays), tier word, recurrence note.
   - Compact 2×2 quadrant grid (tap opens history) with axis captions.
   - "Co teď nejvíc ovlivňuje stav" as FactorBars with grade chips.
   - Gated note.
   - **FIX-4:** the quadrant name appears once (in the chip); the ring title shows the verdict.
6. Regenerace přes noc: RESTYLE. Big number, label, delta chip, bar with the yesterday marker, scale labels, the "včera" line, HRV row, priority row, InfoDot.
7. Regenerace vs. norma: RESTYLE. Range rows with plain status words ("v normě / sledovat / pod normou / nad normou"). WeeklyCheckButton goes in the header.
8. Tréninková zátěž: RESTYLE. Headline and chip, text, weekly bars coloured by status (scrub kept), 3 stats, CapacityMini as headroom bars with the readiness %.

Desktop grid is unchanged: 5 full width; 6 and 7 at `lg:grid-cols-[1.45fr_.8fr]`; 8 full width. `QuadrantHistory` is RESTYLED (raised panel, bars by quadrant colour, the selected-day card with axis bars; load in the load colour).

### Trénink (`training.tsx`)
0. Engine gate card (non-v3): RESTYLE.
1. Header: label, h1 session name, "předběžné" chip, readiness chip with InfoDot. RESTYLE.
2. Override: AlertBanner `stop` with the "Objednat fyzioterapeuta" link (physio / function kinds only). RESTYLE.
3. "Dnes už máte hotovo": AlertBanner `info`. RESTYLE.
4. Session chips become **tiles**, 3 per row. Recommended = lime outline and a "doporučeno" chip. Not allowed = 70% opacity and a "nedoporučeno" chip, **still selectable**. RESTYLE.
5. Session card: the "Dnes nedoporučujeme: {why}" line, 8 stat tiles (2×4 on phone, 4×2 from `lg`), or the rest / race text, and notes. RESTYLE.
6. TodayCapacity (RESTYLE):
   - Status line with a dot.
   - Volume as a large semicircle gauge ("max X km", "omezuje: …"). Intensity, descent, ascent and systemic as small half-gauges (systemic in the load colour).
   - Tapping any gauge expands its full `dl` rows in place (kapacita/strop, 6 dní + dnes, tento týden v cyklu, jeden běh). **No row is dropped.**
   - The ceiling note and the next-week text stay.
7. WeekPanel: mode chip, segmented radio with 4 weeks (%, disabled and locked states with tooltips), inline confirm card, manual note with "Vrátit automaticky", the "how" text, CycleStrip (current week lime with a dashed target). RESTYLE.
8. RacesCard: warnings, list rows (date · name · km · priority chip · days · ✕), inline add form (priority as segmented). RESTYLE.
9. Proč and disclaimer: KEEP text, RESTYLE.

### Deník (`tabs.tsx → Post`)
1. Head. **FIX-3:** `plural(n,"běh","běhy","běhů")` → "1 běh čeká na zápis".
2. Čeká na zápis: ListRows with a lime "Zapsat" button → RateSheet. RESTYLE.
3. Poslední zápisy: ListRows. Tone icon (alert if pain ≥ 4). Pain-site chip **also on phones**. Trailing chevron. "Upravit" appears on desktop hover. → RateSheet edit. RESTYLE.
4. Check-iny: ListRows with DEN (info) / TÝD (self) tiles and region chips. **FIX-6:** empty text "Přidejte první přes tlačítko Check-in vpravo dole."
5. Souhrn deníku: big mean and trend chip, 3 stat tiles, PainHeatmap, top-site bars. RESTYLE.
6. Co z toho čteme: tone dots. RESTYLE.
7. Souhrn check-inů: 2×2 stat tiles, top places. RESTYLE.

Desktop grid unchanged: `lg:grid-cols-[1.4fr_.8fr]`. RateSheet is RESTYLED (section 4 Slider and Sheet).

### Pohyb (`tabs.tsx → Mechanics`)
0. Baseline gate: AlertBanner `info` with a reliability progress bar. RESTYLE.
1. Signál pohybu: label, serif headline, text, status chip, "Co tvoří skóre mechaniky" as FactorBars. RESTYLE.
2. Trend card: score 0–100, `AxisLineChart` with a zone band above threshold 25 and no stretched text (scrub kept). RESTYLE.
3. Segmented Všechen terén / Podle profilu terénu and caption. RESTYLE.
4. Metric accordion. **Order unchanged** (OPT-6 would sort it). Default open metric unchanged. RESTYLE:
   - Collapsed: label, InfoDot, "odhad" chip, value, delta chip, chevron. The range bar is shown only when |z| ≥ 1.
   - Open: lime outline and tint, range bar, baseline sentence, full trend with the band and scrub, `careReveal`.
5. TerrainMatrix: RESTYLE, horizontal scroll kept.
6. RunHistoryReal: toggle card, ListRows (terrain chip, weather chip, VR, chevron), and in the open run `RunContext` (two `dl` blocks), `SegmentTimeline` (heatmap strips, legend, stretches list, segment detail with ‹ ›), `MonthCompare` table and `ExcludeRun`. RESTYLE.

### Zátěž (`tabs.tsx → Load`, `capacity.tsx`)
1. Signál zátěže: headline and status chip, score trend (**load colour**, zone band above 25), "Co tvoří skóre zátěže" as FactorBars, safe longest run row. RESTYLE.
   - **ADD:** a graded bar for the 7:28 ratio (`loadDetail.ratio`) with segments <0.8 low / 0.8–1.3 ok / 1.3–1.5 watch / >1.5 alert, and a white marker.
2. CapacityPanel: readiness chip and part chips, 5 ChannelRows (HeadroomBar, texts, pending jump, latent), frailty note, relative effort list with band chips, HR zones (5 columns, Z4–Z5 in alert). RESTYLE.
3. Weekly (12 weeks) and daily (28 days) Bars, coloured by status, scrub kept. RESTYLE.
4. Cross-training card or line: Lucide sport icons instead of emoji. RESTYLE.
5. Descent by slope: the 13 bins stay (OPT-7 would group them). **FIX-8:** show every other label on phones. RESTYLE.
6. HRV / RHR / Sleep sparkline cards (scrub kept) and SleepQualityCard. RESTYLE.

### Péče (`care.tsx`)
- **Segmented sub-tabs:** Fyzioterapeut / Program / Zdraví. RESTYLE.
- **Fyzioterapeut:** head; PhysioChat (header avatar, bubbles: runner = lime, physio = `#17382f`, system = centred muted); input and send.
  - **FIX-7:** when no physio has taken the case, the input is disabled with the placeholder "Chat se otevře po převzetí případu".
  - Schůzka card: reminders (alert tone), interest CTA → "Zájem potvrzen ✓ zrušit" → "Naplánovat schůzku" (primary with a calendar icon), booking ListRows with status chips and "Zrušit", Spolupráce with "Odvolat".
- **FindSlotSheet:** day and part-of-day chips (lime when selected), physio cards (avatar initials, name, clinic · city · years · ★, price chip, bio, slot chips). KEEP the flow.
- **Program:** empty state with an icon; exercise rows with a progress bar and a "Hotovo" button, adherence chip, "Jak to funguje", revisions. RESTYLE.
- **Zdraví:** report card (danger button) or active injury (mark healed), RTR card (level chip, progress bar, "Zaznamenat sezení" → RtrSheet), Závěr card. RESTYLE.

### Data (`datapage.tsx`)
1. Head and **one status strip** replacing the 3 Metric tiles (same values: activities with date range, status with source, profile). "nepřipojeno" in watch colour. RESTYLE.
2. Engine hodnocení: 3 selectable cards (radio dot, name, "beta", description), "Porovnat enginy" row → `/engines`, explanation text, 3 download buttons (primary + 2 outline) with their busy texts, and the legend. RESTYLE.
3. CoachConsentCard: switch, texts, disclosure, pending note, text-preview chips. RESTYLE.
4. Sources card: segmented (Garmin – soubor / Garmin – přihlášení / Apple Health) and each panel. RESTYLE:
   - Connected Garmin block becomes a button row: Synchronizovat teď (primary), Detailní data, Povrch trasy, Zapnout/Vypnout ranní sync, Odpojit (danger outline). Lucide icons replace ⟳ ⛰ 🗺. Tooltips are kept.
   - Login fields, the remember checkbox, the 2FA step.
   - Apple URL and token with copy buttons, rotate token, manual upload.
   - Result chips.
5. Access log and device history as ListRows. RESTYLE.

### Auth (`App.tsx → Auth`)
**FIX-1:** the primary button is lime. KEEP the register/login toggle, validation, error text, and the desktop split layout (brand panel left). RESTYLE inputs (focused = lime border and glow).

### Secondary routes
`/engine` and `/engines`: RESTYLE only through tokens and shared components. Layout unchanged.

---

## 7. OPT (do not build unless named)

**Approved by the owner on 26 Sep 2026: OPT-1, OPT-3, OPT-5, OPT-6, OPT-7, OPT-9.** OPT-2, OPT-4, OPT-8 and OPT-10 stay off.

| ID | Change |
|---|---|
| OPT-1 | Decision card at the top of Dnes (repeats the Trénink guidance) |
| OPT-2 | Remove the 2×2 quadrant grid from Dnes (history only) |
| OPT-3 | Check-in as 3 steps |
| OPT-4 | Move engine / backtests / JSON export to `/settings/advanced` |
| OPT-5 | Desktop left sidebar and a customisable right stat rail |
| OPT-6 | Sort Pohyb metrics by deviation |
| OPT-7 | Group the descent bins into 4 slope bands |
| OPT-8 | Merge Pohyb and Zátěž into one "Data" tab, with a centre "+" Check-in in the tab bar |
| OPT-9 | Deník run detail screen (elevation, feel and legs dials, per-km table) |
| OPT-10 | Dnes dual ring (readiness outer, load inner) as the hero |

## 8. FIX list

| ID | Fix |
|---|---|
| FIX-1 | Auth primary button is dark on dark → lime primary. |
| FIX-2 | Stretched chart text (`preserveAspectRatio="none"` with `<text>`: `ui.tsx` AxisLineChart, `enginelab.tsx`, `enginecompare.tsx`) → HTML text overlays. |
| FIX-3 | Czech plural helper in `lib.ts`, used for counted nouns (`tabs.tsx:101` and others). |
| FIX-4 | Show "Kritická kombinace" (quadrant name) once on Dnes. |
| FIX-5 | Bottom padding so the Check-in button never covers content. |
| FIX-6 | Deník empty-state copy points to "tlačítko Check-in vpravo dole". |
| FIX-7 | Disable the chat input until a physio has taken the case. |
| FIX-8 | Descent-bin axis labels: every other label on phones. |
| FIX-9 | No text below 11 px. |

## 9. Build order (one PR per step; stop after each with screenshots at 390 px and 1440 px)

| Step | Scope |
|---|---|
| 1 | Tokens, delete the repaint CSS, type scale, focus ring (FIX-1, FIX-2, FIX-9) |
| 2 | Shared components and `lucide-react` (new: AlertBanner, FactorBar, Segmented) |
| 3 | App shell (FIX-5) |
| 4 | Dnes (FIX-4) |
| 5 | Trénink |
| 6 | Deník (FIX-3, FIX-6) |
| 7 | Pohyb |
| 8 | Zátěž (FIX-8) |
| 9 | Péče, Data, Auth, global sheets (FIX-7) |

## 10. Acceptance checklist (every step)

- [ ] `npm run build` passes. No console errors.
- [ ] Every module in this file's module map for the touched tab is present, in order.
- [ ] Every interaction in section 5 for the touched area still works on mouse **and** touch (InfoDot, chart scrub, accordions, sheets, confirms).
- [ ] No hard-coded hex colours remain in touched files (tokens only). Chart series colours come from tokens.
- [ ] No text under 11 px. Focus ring is visible. Secondary text contrast is ≥ 4.5:1.
- [ ] No horizontal page scroll at 390 px. Tables and matrices scroll inside their own container.
- [ ] Nothing marked OPT was implemented.
