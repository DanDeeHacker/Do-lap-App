// Getting started — the checklist a new runner sees first after registering
// (connect data → fill in the profile → take the tour), and the clickable tour
// itself: every tab of a demo account, personalised with the runner's own name,
// with at most five highlighted features per tab. Closing the checklist keeps it
// under the profile icon until all three steps are done.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { useLocation, useNavigate } from "react-router"
import { ArrowLeft, ArrowRight, Check, Compass, PlugZap, UserPen, X } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"

type Step = { id: "data" | "profile" | "tutorial"; done: boolean }
type ObState = { active: boolean; dismissed: boolean; completed: boolean; steps: Step[] }

type ObCtx = {
  state: ObState | null
  openCard: () => void
  pending: number
  /** public demo session (no account) */
  guest: boolean
  exitDemo: () => void
  restartTour: () => void
}
const Ctx = createContext<ObCtx>({ state: null, openCard: () => {}, pending: 0, guest: false, exitDemo: () => {}, restartTour: () => {} })
export const useOnboarding = () => useContext(Ctx)

export const EDIT_PROFILE_EVENT = "doslap:edit-profile"

const STEP_UI: Record<Step["id"], { title: string; sub: string; icon: typeof PlugZap }> = {
  data: { title: "Připojit data", sub: "Garmin nebo Apple Health v Data a připojení", icon: PlugZap },
  profile: { title: "Vyplnit profil", sub: "rok narození, pohlaví, zranění, cílový závod", icon: UserPen },
  tutorial: { title: "Projít průvodce aplikací", sub: "ukázkový účet s vaším jménem, záložku po záložce", icon: Compass },
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { realMe, touring, boot, startTour, endTour, logout } = useApp()
  const rid = realMe?.runner_id
  const guest = !!realMe?.guest
  const [state, setState] = useState<ObState | null>(null)
  const [manual, setManual] = useState(false)
  const [tourOn, setTourOn] = useState(false)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const { pathname } = useLocation()

  const load = useCallback(() => {
    if (!rid) return
    api.onboarding(rid).then((s) => setState(s)).catch(() => {})
  }, [rid])
  // re-check whenever the runner's own data changes (a sync ticks off "data", a saved profile "profile")
  const ver = touring ? null : `${boot?.runner?.birth_year}|${boot?.runner?.sex}|${boot?.integration?.status}|${(boot?.activities || []).length}|${(boot?.daily_metrics || []).length}`
  useEffect(() => { if (ver !== null) load() }, [ver, load])

  // "Vyplnit profil" opens the profile sheet: step aside until it's saved or the page changes
  const [hold, setHold] = useState(false)
  useEffect(() => { setHold(false) }, [ver, pathname])
  const auto = !!state && state.active && !state.completed && !state.dismissed
  const show = !touring && !tourOn && !hold && pathname.startsWith("/app/") && (manual || auto)
  const pending = state && state.active && !state.completed ? state.steps.filter((s) => !s.done).length : 0

  const close = () => {
    setManual(false)
    if (auto && rid) api.updateOnboarding(rid, { dismissed: true }).then(setState).catch(() => {})
  }
  const act = async (id: Step["id"]) => {
    if (id === "data") { setManual(false); nav("/data") }
    if (id === "profile") { setHold(true); window.dispatchEvent(new Event(EDIT_PROFILE_EVENT)) }
    if (id === "tutorial") {
      setBusy(true)
      const ok = await startTour()
      setBusy(false)
      if (ok) { setManual(false); setTourOn(true); nav("/app/today") }
    }
  }
  // public demo: the tour starts on its own; leaving the demo returns to sign-up
  const guestStarted = useRef(false)
  useEffect(() => {
    if (!guest || guestStarted.current) return
    guestStarted.current = true
    // once per demo visit: a page reload keeps the visitor where they were
    let seen = false
    try { seen = sessionStorage.getItem("doslap-demo-tour") === "1"; sessionStorage.setItem("doslap-demo-tour", "1") } catch { /* storage blocked */ }
    if (!seen) { setTourOn(true); nav("/app/today") }
  }, [guest, nav])
  const exitDemo = useCallback(async () => {
    setTourOn(false)
    try { sessionStorage.removeItem("doslap-demo-tour") } catch { /* storage blocked */ }
    await logout()
    nav("/auth")
    window.scrollTo({ top: 0 })
  }, [logout, nav])
  const finishTour = (done: boolean) => {
    setTourOn(false)
    if (guest) { nav("/app/today"); return }       // the guest keeps browsing the demo
    endTour()
    nav("/app/today")
    if (done && rid) api.updateOnboarding(rid, { tutorialDone: true }).then((s) => { setState(s); setManual(true) }).catch(() => {})
    else setManual(true)
  }

  return (
    <Ctx.Provider value={{ state, openCard: () => setManual(true), pending, guest, exitDemo, restartTour: () => setTourOn(true) }}>
      {children}
      {show && state && <GetStartedCard state={state} name={realMe?.name} busy={busy} onAct={act} onClose={close} />}
      {tourOn && touring && <Tour name={guest ? null : realMe?.name} guest={guest} onFinish={finishTour} onExitDemo={exitDemo} />}
    </Ctx.Provider>
  )
}

function firstName(name?: string | null) {
  return (name || "").trim().split(/\s+/)[0] || ""
}

// ---------------------------------------------------------------- the checklist
function GetStartedCard({ state, name, busy, onAct, onClose }: { state: ObState; name?: string | null; busy: boolean; onAct: (id: Step["id"]) => void; onClose: () => void }) {
  const doneN = state.steps.filter((s) => s.done).length
  const next = state.steps.find((s) => !s.done)?.id
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", k)
    return () => window.removeEventListener("keydown", k)
  }, [onClose])
  return createPortal(
    <div className="fixed inset-0 z-[95] grid place-items-center bg-black/55 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <section role="dialog" aria-modal="true" aria-label="Začínáme" data-testid="get-started" onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[440px] animate-[careReveal_.28s_ease-out] overflow-hidden rounded-[24px] border border-white/10 bg-raised text-fg shadow-[0_24px_70px_rgb(0_0_0_/_0.55)]">
        <div className="px-5 pb-4 pt-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-[20px] font-extrabold tracking-[-.02em]">Začínáme</h2>
              <p className="mt-0.5 text-[14px] text-fg-2">
                {state.completed ? `Hotovo, ${firstName(name)}. Aplikace je připravená.` : `${firstName(name) ? `${firstName(name)}, d` : "D"}okončeme nastavení vašeho účtu`}
              </p>
            </div>
            <button type="button" onClick={onClose} aria-label="Zavřít" className="grid size-8 place-items-center rounded-full text-fg-2 hover:bg-white/[.07]"><X className="size-4" aria-hidden /></button>
          </div>
          {/* one segment per step, the check sits where the done part ends */}
          <div className="relative mt-4 flex gap-1" aria-label={`Hotovo ${doneN} ze ${state.steps.length}`}>
            {state.steps.map((s, i) => (
              <span key={s.id} className={`h-3 flex-1 ${i === 0 ? "rounded-l-full" : ""} ${i === state.steps.length - 1 ? "rounded-r-full" : ""} ${s.done ? "bg-ok" : "bg-white/[.12]"}`} />
            ))}
            {doneN > 0 && (
              <span className="absolute top-1/2 grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-2 border-raised bg-ok text-ink"
                style={{ left: `${(doneN / state.steps.length) * 100}%`, ...(doneN === state.steps.length ? { left: "calc(100% - 14px)" } : {}) }}>
                <Check className="size-3.5" strokeWidth={3} aria-hidden />
              </span>
            )}
          </div>
        </div>
        <ul className="border-t border-white/[.07]">
          {state.steps.map((s) => {
            const ui = STEP_UI[s.id]
            const Icon = ui.icon
            const isNext = s.id === next
            return (
              <li key={s.id} className="border-b border-white/[.07] last:border-b-0">
                <button type="button" onClick={() => onAct(s.id)} disabled={busy && s.id === "tutorial"} data-step={s.id}
                  className={`flex w-full items-center gap-3.5 px-5 py-4 text-left transition hover:bg-white/[.04] ${isNext ? "bg-accent/[.06]" : ""}`}>
                  <span className={`grid size-9 shrink-0 place-items-center rounded-full ${s.done ? "bg-ok/15 text-ok" : "bg-white/[.06] text-accent"}`}><Icon className="size-4.5" aria-hidden /></span>
                  <span className="min-w-0 flex-1">
                    <span className={`block text-[15px] font-bold ${s.done ? "text-fg-3 line-through" : "text-fg"}`}>{ui.title}</span>
                    <span className="block text-[12px] text-fg-3">{busy && s.id === "tutorial" ? "načítám ukázku…" : ui.sub}</span>
                  </span>
                  {s.done
                    ? <span className="grid size-7 shrink-0 place-items-center rounded-full bg-ok text-ink" aria-label="hotovo"><Check className="size-4" strokeWidth={3} aria-hidden /></span>
                    : <span className="size-7 shrink-0 rounded-full bg-white/[.1]" aria-label="zbývá" />}
                </button>
              </li>
            )
          })}
        </ul>
        <p className="px-5 py-3 text-[11px] text-fg-3">Kdykoli se sem vrátíte přes ikonu profilu → Začínáme.</p>
      </section>
    </div>,
    document.body,
  )
}

// ---------------------------------------------------------------- the tour
type Target = { sel?: string; text?: string; box?: string }
type CareSub = "physio" | "program" | "health"
type TourStep = { route: string; tab: string; target?: Target; title: string; body: string; value: string; care?: CareSub }
/** Péče keeps its sub-tab in local state; the tour asks it to switch with this event. */
export const CARE_SUB_EVENT = "doslap:care-sub"

const TABS: [string, string][] = [["/app/today", "Dnes"], ["/app/training", "Trénink"], ["/app/post", "Deník"], ["/app/mechanics", "Pohyb"], ["/app/load", "Zátěž"], ["/app/messages", "Péče"]]

// At most five features per tab. `body` says what the feature shows and how to use
// it, `value` why it is worth the runner's attention. No medical claims.
export const TOUR: TourStep[] = [
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-score"]' }, title: "Skóre a osy stavu",
    body: "Velké číslo je celkové skóre dne od 0 do 100, čím vyšší, tím lépe. Kolem něj jsou čtyři kruhy: připravenost, příznaky, zátěž a mechanika. Klepnutím na kteroukoli otevřete její trend.",
    value: "Za pár vteřin víte, jak na tom tělo dnes je, a hned vidíte, která oblast skóre táhne dolů." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-reco"]' }, title: "Dnešní doporučení",
    body: "Konkrétní typ tréninku na dnešek s rozsahem kilometrů. Vychází z vaší kapacity, ranní připravenosti a z toho, co jste odběhli v posledních dnech.",
    value: "Nemusíte hádat, jestli dnes přidat, nebo ubrat. Doporučení se každé ráno přepočítá podle nových dat." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-quadrant"]' }, title: "Kvadrant stavu",
    body: "Zátěž a mechanika společně určí jeden ze čtyř stavů: stabilní, přetížení, tichý drift nebo kritická kombinace. Klepnutím zobrazíte vývoj stavu za posledních 6 měsíců.",
    value: "Odliší obyčejnou únavu z objemu od změny techniky, kterou zatím necítíte. Každá z těch situací chce jinou reakci." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-drivers"]' }, title: "Co ovlivňuje stav",
    body: "Signály seřazené podle toho, o kolik procentních bodů snižují celkové Skóre, například klesání nad kapacitou nebo prodloužený kontakt se zemí. Po rozkliknutí uvidíte, které aktivity nebo záznamy k signálu přispívají.",
    value: "Skóre není černá skříňka. Vidíte, co přesně ho tvoří, a víte, na co se zaměřit." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="checkin"]' }, title: "Denní check-in",
    body: "Tlačítko Check-in otevře krátký dotazník na bolest, ztuhlost a únavu. Bolest označíte přímo na mapě těla a celé to zabere pár vteřin.",
    value: "Hodinky vaši bolest neznají. Check-in doplní to nejdůležitější a zpřesní hodnocení i doporučení." },

  { route: "/app/training", tab: "Trénink", target: { sel: '[data-tour="training-session"]' }, title: "Dnešní trénink",
    body: "Doporučený typ dne s konkrétními mantinely: vzdálenost, čas, tepové pásmo, tempo, minuty v Z4+ a maximum stoupání i klesání. Dlaždicemi přepnete na jiný typ a limity se přepočítají.",
    value: "Víte nejen, co běžet, ale i kde je dnes strop. Tempo a tep jsou spočítané z vašich vlastních běhů." },
  { route: "/app/training", tab: "Trénink", target: { text: "Dnešní kapacita" }, title: "Dnešní kapacita",
    body: "Pět kanálů zátěže: objem, intenzita, klesání, stoupání a celková zátěž. U každého vidíte, kolik z týdenní kapacity máte za sebou a kolik si dnes ještě můžete dovolit.",
    value: "Kapacita roste s tím, co prokazatelně zvládáte, a hlídá prudké skoky, které tělo nestihne vstřebat." },
  { route: "/app/training", tab: "Trénink", target: { text: "Cyklus · tento týden" }, title: "Týdenní cyklus",
    body: "Trénink běží ve čtyřtýdenních cyklech, tři týdny budovací a jeden odlehčovací. Sloupce ukazují objem posledních týdnů a cíl toho aktuálního, pozici v cyklu si můžete upravit.",
    value: "Postupné zvyšování s pravidelným odlehčením je osvědčený tréninkový princip. Došlap ho drží za vás." },
  { route: "/app/training", tab: "Trénink", target: { text: "Závody" }, title: "Závody",
    body: "Kalendář závodů s prioritou A, B nebo C. V ukázce je kontrolní půlmaraton a cílový maraton.",
    value: "Před závodem s prioritou A se trénink sám zklidní, abyste na start přišli odpočatí." },
  { route: "/app/training", tab: "Trénink", target: { sel: '[data-tour="training-cross"]' }, title: "Jiný sport",
    body: "Kolo, plavání a posilování, každý s délkou a tepovým pásmem nebo cílovou náročností. Když je běžecký objem vyčerpaný, doporučí kolo. Tréninky bez hodinek zapíšete v Deníku.",
    value: "Aerobní trénink pokračuje i ve dnech, kdy nohy potřebují pauzu od nárazů, a posilování, které zlepšuje běžeckou ekonomiku, má v týdnu své místo." },

  { route: "/app/post", tab: "Deník", target: { text: "Čeká na zápis" }, title: "Běhy k ohodnocení",
    body: "Nové běhy z hodinek čekají na krátký zápis: jak se běželo, jak se cítily nohy a jestli něco bolelo. Zápis zabere asi dvacet vteřin.",
    value: "Váš vlastní pocit z běhu je jeden z nejcitlivějších signálů únavy. Tyto zápisy engine váží nejvíc." },
  { route: "/app/post", tab: "Deník", target: { text: "Poslední zápisy" }, title: "Poslední zápisy",
    body: "Přehled ohodnocených běhů s vaším pocitem a poznámkou. Klepnutím otevřete detail běhu s terénem, počasím a úseky.",
    value: "Když se něco změní, snadno dohledáte, kdy to začalo a na jakém běhu." },
  { route: "/app/post", tab: "Deník", target: { sel: '[data-tour="journal-summary"]' }, title: "Souhrn deníku",
    body: "Průměrný pocit z běhů a jeho trend, počet zápisů za 21 dní, kolikrát něco bolelo a nejvyšší nahlášená bolest.",
    value: "Zhoršující se pocit z běhů se často objeví dřív než změna v datech z hodinek. Tady ho uvidíte přehledně na jednom místě." },
  { route: "/app/post", tab: "Deník", target: { sel: '[data-tour="journal-sites"]' }, title: "Kde to nejčastěji bolí",
    body: "Mapa těla a žebříček míst, která jste v posledních 30 dnech označili. V ukázce je to ztuhlá pravá Achillova šlacha po dlouhém běhu.",
    value: "Místo, které se ozývá opakovaně, stojí za pozornost dřív, než začne omezovat trénink." },
  { route: "/app/post", tab: "Deník", target: { text: "Check-iny (denní a týdenní)" }, title: "Historie check-inů",
    body: "Všechny denní check-iny a týdenní dotazníky na jednom místě, s bolestí, ztuhlostí a únavou.",
    value: "Vývoj za několik týdnů ukáže trend, který z jednoho dne nepoznáte. Fyzioterapeut v něm uvidí souvislosti." },

  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Signál pohybu" }, title: "Stav mechaniky",
    body: "Souhrnný signál vaší běžecké techniky. Porovnává se vždy se srovnatelnými běhy ve stejném tempu a terénu, nikdy s průměrem ostatních.",
    value: "Změna techniky bývá časným znakem únavy, často dřív, než ji vůbec ucítíte." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Mechanická stabilita — trend" }, title: "Trend mechaniky",
    body: "Skóre driftu po dnech za posledních 6 měsíců. Hodnoty nad prahem 25 znamenají, že se technika drží mimo vaši normu.",
    value: "Rozlišíte jednorázový výkyv po náročném běhu od plíživého trendu." },
  { route: "/app/mechanics", tab: "Pohyb", target: { sel: "[data-norm]", box: ".overflow-hidden" }, title: "Jednotlivé metriky",
    body: "Vertikální poměr, kontakt se zemí, kadence, vyváženost a další. Každá metrika má štítek v normě, na hraně nebo mimo normu a klepnutím otevřete její trend.",
    value: "Víte přesně, která část kroku se mění, a právě s tím může pracovat fyzioterapeut." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Podle profilu terénu", box: "div" }, title: "Podle terénu",
    body: "Srovnání metrik na rovině, do kopce, z kopce a v různém tempu.",
    value: "V kopci běžíte jinak než na rovině. Porovnání ve stejných podmínkách odfiltruje falešné poplachy." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Historie běhů" }, title: "Historie běhů",
    body: "Všechny běhy s metrikami techniky. Každý lze otevřít, porovnat s během před měsícem nebo vyřadit z výpočtů, třeba když hodinky změřily nesmysl.",
    value: "Máte pod kontrolou, z jakých běhů se vaše norma počítá." },

  { route: "/app/load", tab: "Zátěž", target: { text: "Signál zátěže" }, title: "Stav zátěže",
    body: "Jestli trénink v posledních dnech nepřekračuje to, co jste v předchozích týdnech prokazatelně zvládli.",
    value: "Prudký nárůst objemu je podle výzkumu spojený s častějšími běžeckými obtížemi (Nielsen et al., 2014). Tady ho uvidíte hned." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Skóre zátěže — trend" }, title: "Trend zátěže",
    body: "Skóre zátěže po dnech za posledních 6 měsíců. Nad prahem 25 je zátěž zvýšená.",
    value: "Uvidíte, jak rychle se po náročných týdnech vracíte do normy." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Týdenní kapacita" }, title: "Kapacita po kanálech",
    body: "Týdenní součet objemu, intenzity, klesání, stoupání a celkové zátěže proti vaší kapacitě, u posilování i silová zátěž. V ukázce je vidět klesání navýšené prudkým trailovým během.",
    value: "Tělo nezatěžují jen kilometry. Seběh z kopce působí jinak než rovina, a proto se počítá zvlášť." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Co tvoří skóre zátěže" }, title: "Co tvoří zátěž",
    body: "Kanály seřazené podle toho, kolik přidávají k dnešnímu skóre zátěže.",
    value: "Hned víte, čím ubrat, jestli objemem, intenzitou, nebo seběhy." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Spánek" }, title: "Regenerace",
    body: "Spánek, HRV a klidový tep z hodinek, vždy proti vaší vlastní normě.",
    value: "Po špatné noci unesete méně. Došlap podle toho ráno sníží dnešní stropy." },

  { route: "/app/messages", tab: "Péče", care: "physio", target: { sel: '[data-tour="care-tabs"]' }, title: "Tři části péče",
    body: "Fyzioterapeut pro zprávy a schůzky, Program s cviky na míru a Zranění pro nahlášení obtíží a závěry z prohlídek.",
    value: "Všechno kolem péče o tělo je na jednom místě a navazuje na vaše data." },
  { route: "/app/messages", tab: "Péče", care: "physio", target: { sel: '[data-tour="care-chat"]' }, title: "Zprávy fyzioterapeutovi",
    body: "Chat s fyzioterapeutem přímo v aplikaci. V ukázce fyzioterapeut podle dat upravil program ještě před další kontrolou. Vaše data uvidí až poté, co potvrdíte zájem a on převezme váš případ.",
    value: "Nemusíte čekat měsíc na další termín. Plán se upraví hned, když se něco změní." },
  { route: "/app/messages", tab: "Péče", care: "physio", target: { text: "Schůzka" }, title: "Schůzka",
    body: "Nadcházející termín i s informacemi, co si vzít s sebou. Nové vyšetření, analýzu běhu nebo videokonzultaci domluvíte tady.",
    value: "Žádné telefonování ani e-maily. Fyzioterapeut má kontext ještě před schůzkou." },
  { route: "/app/messages", tab: "Péče", care: "program", target: { text: "Cviky" }, title: "Program cviků",
    body: "Cviky od fyzioterapeuta s dávkováním a pokyny. Po cvičení je odškrtnete a vidíte, kolik máte splněno i jak se program upravoval.",
    value: "Vidíte svůj progres a fyzioterapeut ví, jestli program funguje, aniž by se musel ptát." },
  { route: "/app/messages", tab: "Péče", care: "health", target: { text: "Závěr z prohlídky" }, title: "Závěr z prohlídky",
    body: "Souhrn poslední prohlídky, který fyzioterapeut zkontroloval a schválil, s nálezem a doporučením.",
    value: "Doporučení se neztratí na papírku a můžete se k nim kdykoli vrátit." },
]

function visible(el: Element) {
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0
}

export function findTarget(t?: Target): HTMLElement | null {
  if (!t) return null
  let el: Element | null = null
  if (t.sel) el = [...document.querySelectorAll(t.sel)].find(visible) || null
  else if (t.text) {
    const cands = document.querySelectorAll("main .t-label, main h1, main h2, main h3, main button, main p, main span")
    el = [...cands].find((c) => visible(c) && (c.textContent || "").trim().startsWith(t.text!)) || null
  }
  if (!el) return null
  // a selector names the exact element; a text match is a label, so highlight its card
  let box = t.box ? el.closest(t.box) : t.sel ? null : (el.closest(".nest, .card") || el.closest("section"))
  // a whole page-tall section is no highlight: fall back to the label's own block
  if (box && box.getBoundingClientRect().height > window.innerHeight * 0.75) box = el.parentElement
  return ((box && box.tagName !== "MAIN" ? box : el) as HTMLElement)
}

function Tour({ name, guest = false, onFinish, onExitDemo }: { name?: string | null; guest?: boolean; onFinish: (done: boolean) => void; onExitDemo?: () => void }) {
  const nav = useNavigate()
  const { pathname } = useLocation()
  // step −1 = welcome, TOUR.length = done
  const [i, setI] = useState(-1)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [missing, setMissing] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)
  const step = i >= 0 && i < TOUR.length ? TOUR[i] : null

  useEffect(() => { if (step && pathname !== step.route) nav(step.route) }, [step, pathname, nav])

  // wait for the page to render its target, bring it into view, then track it
  useEffect(() => {
    setRect(null)
    setMissing(false)
    if (!step) return
    let tries = 0
    let scrolled = false
    const tick = () => {
      if (step.care) window.dispatchEvent(new CustomEvent(CARE_SUB_EVENT, { detail: step.care }))
      const el = findTarget(step.target)
      if (el) {
        if (!scrolled) { el.scrollIntoView({ block: "center", behavior: "auto" }); scrolled = true }
        setRect(el.getBoundingClientRect())
        setMissing(false)
      } else if (++tries > 12) setMissing(true)
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [step])

  const go = useCallback((d: number) => setI((v) => Math.max(-1, Math.min(TOUR.length, v + d))), [])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1)
      if (e.key === "ArrowLeft") go(-1)
      if (e.key === "Escape") onFinish(false)
    }
    window.addEventListener("keydown", k)
    return () => window.removeEventListener("keydown", k)
  }, [go, onFinish])

  const tabIdx = step ? TABS.findIndex(([r]) => r === step.route) : -1
  const inTab = step ? TOUR.filter((s) => s.route === step.route) : []
  const posInTab = step ? inTab.indexOf(step) + 1 : 0

  // tooltip placement: below the target when it fits, else above, else docked at the bottom
  const vw = typeof window !== "undefined" ? window.innerWidth : 390
  const vh = typeof window !== "undefined" ? window.innerHeight : 800
  const cw = Math.min(360, vw - 32)
  const pad = 8
  const r = rect && !missing ? { top: Math.max(rect.top - pad, 60), bottom: Math.min(rect.bottom + pad, vh - 8), left: Math.max(rect.left - pad, 6), right: Math.min(rect.right + pad, vw - 6) } : null
  const ch = cardRef.current?.offsetHeight ?? 220
  let place: "below" | "above" | "dock" | "center" = "center"
  if (r) place = r.bottom + ch + 24 < vh ? "below" : r.top - ch - 24 > 60 ? "above" : "dock"
  const cx = r ? (r.left + r.right) / 2 : vw / 2
  const left = place === "center" || place === "dock" ? (vw - cw) / 2 : Math.max(16, Math.min(vw - cw - 16, cx - cw / 2))
  const top = place === "below" ? r!.bottom + 14 : place === "above" ? r!.top - ch - 14 : place === "dock" ? vh - ch - 16 : Math.max(80, (vh - ch) / 2)
  const arrowX = Math.max(18, Math.min(cw - 18, cx - left))

  const fn = firstName(name)
  const intro = i === -1
  const outro = i === TOUR.length
  const title = intro ? `Vítejte${fn ? `, ${fn}` : ""}!` : outro ? "Máte hotovo" : step!.title
  const body = intro
    ? guest
      ? "Ukážeme vám aplikaci na ukázkovém běžci s vymyšlenými daty, bez registrace. Projdeme šest záložek a u každé nejvýš pět funkcí. U každé uvidíte, co ukazuje a proč vám pomůže. Šipkami se posunete dál nebo zpět a ukázku můžete kdykoli ukončit."
      : "Ukážeme vám aplikaci na ukázkovém účtu s vaším jménem. Projdeme šest záložek a u každé nejvýš pět funkcí. U každé uvidíte, co ukazuje a proč vám pomůže. Šipkami se posunete dál nebo zpět."
    : outro
      ? guest
        ? "Teď už víte, kde co najdete. Ukázku můžete dál volně procházet, nebo si založte účet a připojte vlastní data z hodinek."
        : "Teď už víte, kde co najdete. Průvodce se vrátí na vaše vlastní data a můžete ho kdykoli spustit znovu přes ikonu profilu → Začínáme."
      : missing ? `${step!.body} (V ukázkovém účtu teď tato část není vidět.)` : step!.body

  return createPortal(
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label="Průvodce aplikací" data-testid="tour">
      {/* dimmer with a hole over the highlighted feature; clicks on the page are blocked */}
      {r ? (
        <div className="pointer-events-none fixed rounded-[18px] ring-2 ring-accent transition-all duration-200"
          style={{ top: r.top, left: r.left, width: r.right - r.left, height: r.bottom - r.top, boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.66)" }} />
      ) : <div className="fixed inset-0 bg-black/66" />}
      <div className="fixed inset-0" onClick={(e) => e.stopPropagation()} />
      <div ref={cardRef} className="fixed rounded-[20px] border border-white/10 bg-raised p-4 text-fg shadow-[0_24px_60px_rgb(0_0_0_/_0.55)] transition-[top,left] duration-200"
        style={{ top, left, width: cw }}>
        {(place === "below" || place === "above") && (
          <i className="absolute size-3.5 rotate-45 border-white/10 bg-raised"
            style={{ left: arrowX - 7, ...(place === "below" ? { top: -7, borderLeftWidth: 1, borderTopWidth: 1 } : { bottom: -7, borderRightWidth: 1, borderBottomWidth: 1 }) }} />
        )}
        <div className="flex items-center justify-between gap-2">
          <p className="t-label">{intro ? "Průvodce aplikací" : outro ? "Hotovo" : `${step!.tab} · ${posInTab}/${inTab.length}`}</p>
          <button type="button" onClick={() => onFinish(false)} aria-label="Ukončit průvodce" className="grid size-7 place-items-center rounded-full text-fg-2 hover:bg-white/[.07]"><X className="size-4" aria-hidden /></button>
        </div>
        <h3 className="mt-1 text-[17px] font-extrabold tracking-[-.01em]">{title}</h3>
        <p className="mt-1.5 text-[13.5px] leading-[1.5] text-fg-2">{body}</p>
        {step && !missing && (
          <p className="mt-2.5 rounded-xl border border-accent/25 bg-accent/[.08] px-3 py-2 text-[13px] leading-[1.45] text-fg">
            <b className="text-accent">Proč to pomáhá: </b>{step.value}
          </p>
        )}
        {/* where we are: one dot per tab */}
        <div className="mt-3 flex items-center gap-1.5" aria-hidden>
          {TABS.map(([rt, lbl], k) => (
            <span key={rt} title={lbl} className={`h-1.5 rounded-full transition-all ${k === tabIdx ? "w-5 bg-accent" : k < tabIdx || outro ? "w-1.5 bg-accent/60" : "w-1.5 bg-white/20"}`} />
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <button type="button" onClick={() => go(-1)} disabled={intro} aria-label="Zpět" className="btn btn-outline btn-sm disabled:opacity-40"><ArrowLeft className="size-4" aria-hidden /></button>
          {outro && guest
            ? <span className="flex gap-2">
                <button type="button" onClick={() => onFinish(true)} className="btn btn-outline btn-sm">Procházet ukázku</button>
                <button type="button" onClick={onExitDemo} className="btn btn-primary btn-sm" data-testid="demo-register">Založit účet</button>
              </span>
            : outro
            ? <button type="button" onClick={() => onFinish(true)} className="btn btn-primary btn-sm">Dokončit průvodce</button>
            : <button type="button" onClick={() => go(1)} aria-label="Další" className="btn btn-primary btn-sm">{intro ? "Začít" : "Další"} <ArrowRight className="size-4" aria-hidden /></button>}
        </div>
      </div>
      <TourBanner onExitDemo={guest ? onExitDemo : undefined} />
    </div>,
    document.body,
  )
}

function TourBanner({ onExitDemo }: { onExitDemo?: () => void }) {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[calc(10px+env(safe-area-inset-top))] z-[101] flex justify-center">
      {onExitDemo ? (
        <span className="flex items-center gap-2 rounded-full bg-accent py-1 pl-3 pr-1 text-[11px] font-extrabold uppercase tracking-[.08em] text-ink shadow">
          Ukázka · vymyšlená data
          <button type="button" onClick={onExitDemo} data-testid="demo-exit-tour" className="pointer-events-auto rounded-full bg-ink/90 px-2.5 py-0.5 text-[11px] normal-case tracking-normal text-accent hover:bg-ink">Ukončit ukázku</button>
        </span>
      ) : (
        <span className="rounded-full bg-accent px-3 py-1 text-[11px] font-extrabold uppercase tracking-[.08em] text-ink shadow">Ukázka · data nejsou vaše</span>
      )}
    </div>
  )
}

// small helper used by the profile menu
export function useObSummary() {
  const { state, pending, openCard } = useOnboarding()
  return useMemo(() => ({ show: !!state?.active && !state.completed, done: state ? state.steps.filter((s) => s.done).length : 0, total: state?.steps.length ?? 3, pending, openCard }), [state, pending, openCard])
}
