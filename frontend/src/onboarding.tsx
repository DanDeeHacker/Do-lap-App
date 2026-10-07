// Getting started — the checklist a new runner sees first after registering
// (connect data → take the tour), and the clickable tour itself on a demo account
// personalised with the runner's own name: six core steps, and a short tour of each
// tab behind the compass in the top bar (UX audit F06). Closing the checklist keeps it under the profile icon until both
// steps are done. v0.12.0: the profile is asked before it (profile.tsx ProfileGate),
// of every account that misses a required item, so it can't be skipped.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { useLocation, useNavigate } from "react-router"
import { ArrowLeft, ArrowRight, Check, Compass, PlugZap, X } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { ProfileGate } from "@/profile"

type Step = { id: "data" | "tutorial"; done: boolean }
type ObState = { active: boolean; dismissed: boolean; completed: boolean; steps: Step[]; profileMissing?: string[] }

type ObCtx = {
  state: ObState | null
  openCard: () => void
  pending: number
  /** public demo session (no account) */
  guest: boolean
  exitDemo: () => void
  restartTour: () => void
  /** UX audit F06 — the short tour of one tab (on the demo runner) */
  startTabTour: (route: string) => void
}
const Ctx = createContext<ObCtx>({ state: null, openCard: () => {}, pending: 0, guest: false, exitDemo: () => {}, restartTour: () => {}, startTabTour: () => {} })
export const useOnboarding = () => useContext(Ctx)

export const EDIT_PROFILE_EVENT = "doslap:edit-profile"

const STEP_UI: Record<Step["id"], { title: string; sub: string; icon: typeof PlugZap }> = {
  data: { title: "Připojit data", sub: "Garmin nebo Apple Health v Data a připojení", icon: PlugZap },
  tutorial: { title: "Projít průvodce aplikací", sub: "šest krátkých kroků na ukázkovém účtu s vaším jménem", icon: Compass },
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { realMe, touring, boot, startTour, endTour, logout, viewing } = useApp()
  const rid = realMe?.runner_id
  const guest = !!realMe?.guest
  const [state, setState] = useState<ObState | null>(null)
  const [manual, setManual] = useState(false)
  const [tourOn, setTourOn] = useState(false)
  // null = the core tour; a route = that tab's own tour
  const [tabTour, setTabTour] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const { pathname } = useLocation()

  const load = useCallback(() => {
    if (!rid) return
    api.onboarding(rid).then((s) => setState(s)).catch(() => {})
  }, [rid])
  // re-check whenever the runner's own data changes (a sync ticks off "data", a saved profile "profile")
  const ver = touring ? null : `${boot?.runner?.birth_year}|${boot?.runner?.sex}|${boot?.runner?.running_since}|${boot?.integration?.status}|${(boot?.activities || []).length}|${(boot?.daily_metrics || []).length}`
  useEffect(() => { if (ver !== null) load() }, [ver, load])

  // v0.12.0 — the profile first: nothing else opens until the required items are in
  const gate = !!state?.profileMissing?.length && !guest && !viewing && !touring && !tourOn && pathname.startsWith("/app/")
  const auto = !!state && state.active && !state.completed && !state.dismissed
  const show = !touring && !tourOn && !gate && pathname.startsWith("/app/") && (manual || auto)
  const pending = state && state.active && !state.completed ? state.steps.filter((s) => !s.done).length : 0

  const close = () => {
    setManual(false)
    if (auto && rid) api.updateOnboarding(rid, { dismissed: true }).then(setState).catch(() => {})
  }
  const act = async (id: Step["id"]) => {
    if (id === "data") { setManual(false); nav("/data") }
    if (id === "tutorial") {
      setBusy(true)
      const ok = await startTour()
      setBusy(false)
      if (ok) { setManual(false); setTabTour(null); setTourOn(true); nav("/app/today") }
    }
  }
  const startTabTour = useCallback(async (route: string) => {
    if (!TAB_TOURS[route]) return
    if (!guest) {
      const ok = await startTour()
      if (!ok) return
    }
    setManual(false)
    setTabTour(route)
    setTourOn(true)
  }, [guest, startTour])
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
    const tab = tabTour
    setTabTour(null)
    if (tab) {                                    // a tab's tour returns to that tab
      if (!guest) endTour()
      nav(tab)
      return
    }
    if (guest) { nav("/app/today"); return }       // the guest keeps browsing the demo
    endTour()
    nav("/app/today")
    if (done && rid) api.updateOnboarding(rid, { tutorialDone: true }).then((s) => { setState(s); setManual(true) }).catch(() => {})
    else setManual(true)
  }

  return (
    <Ctx.Provider value={{ state, openCard: () => setManual(true), pending, guest, exitDemo, restartTour: () => { setTabTour(null); setTourOn(true) }, startTabTour }}>
      {children}
      {gate && state && <ProfileGate missing={state.profileMissing || []} onDone={load} />}
      {show && state && <GetStartedCard state={state} name={realMe?.name} busy={busy} onAct={act} onClose={close} />}
      {tourOn && touring && <Tour key={tabTour || "core"} steps={tabTour ? TAB_TOURS[tabTour] : CORE_TOUR} tabTour={!!tabTour} name={guest ? null : realMe?.name} guest={guest} onFinish={finishTour} onExitDemo={exitDemo} />}
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

// UX audit F06 — the first tour is the six things a new runner needs (it used to be 31
// steps over every tab, without the reports or the programmes); the rest of each tab
// lives in a short tour behind the compass in the top bar. `body` says what the feature
// shows and how to use it, `value` why it is worth the runner's attention. No medical claims.
export const CORE_TOUR: TourStep[] = [
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-score"]' }, title: "Skóre dne a čtyři oblasti",
    body: "Velké číslo je skóre dne od 0 do 100, čím vyšší, tím lépe. Kolem něj jsou čtyři oblasti: připravenost po noci, příznaky z check-inu, zátěž a technika běhu. Klepnutím na kruh otevřete detail, klepnutím na skóre jeho vývoj za 6 měsíců.",
    value: "Za pár vteřin víte, jak na tom tělo dnes je a co skóre táhne dolů." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-reco"]' }, title: "Co dnes běžet",
    body: "Doporučení na dnešek. Tlačítko Trénink otevře podrobnosti: kolik kilometrů, jaký tep a tempo, kolik stoupání a klesání a co dalšího se dnes hodí.",
    value: "Nemusíte hádat, jestli přidat, nebo ubrat. Doporučení se každé ráno přepočítá podle noci a posledních dnů." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="checkin"]' }, title: "Denní check-in",
    body: "Tlačítko Check-in otevře krátký dotazník na bolest, ztuhlost a únavu. Bolest označíte přímo na mapě těla a celé to zabere pár vteřin.",
    value: "Hodinky vaši bolest neznají. Check-in doplní to nejdůležitější a zpřesní hodnocení i doporučení." },
  { route: "/app/today", tab: "Dnes", title: "Ranní a večerní report",
    body: "Ráno, jakmile se stáhne noc z hodinek, a večer po 20. hodině se sám otevře krátký report: jak jste spali, co vás dnes čeká a co ovlivní zítřek. Znovu ho otevřete ikonou slunce nebo měsíce vedle stavu na Dnes.",
    value: "Nejrychlejší cesta, jak se v datech vyznat: jedna myšlenka na kartu." },
  { route: "/app/post", tab: "Deník", target: { text: "Čeká na zápis" }, title: "Zápis po běhu",
    body: "Nové běhy z hodinek čekají na krátký zápis: jak se běželo, jak se cítily nohy a jestli něco bolelo. Zabere asi dvacet vteřin.",
    value: "Váš pocit z běhu je jeden z nejcitlivějších signálů únavy. Aplikace ho váží nejvíc." },
  { route: "/app/messages", tab: "Péče", care: "program", target: { sel: '[data-tour="care-programs"]' }, title: "Cviky a posilování",
    body: "Programy cviků pro běžce: posilování, mobilita a cviky při konkrétních potížích, třeba s Achillovkou. Spustíte je jedním klepnutím a po cvičení odškrtnete.",
    value: "Posilování je podle výzkumu jedna z mála věcí, po kterých mají sportovci méně zranění (Lauersen et al., 2014). Tady ho máte rozepsané do týdne." },
]

// The rest of each tab, behind the compass in the top bar (on the demo runner too).
export const TAB_TOURS: Record<string, TourStep[]> = {
  "/app/today": [
    { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-quadrant"]' }, title: "Stav podle zátěže a techniky",
      body: "Zátěž a technika běhu společně určí jeden ze čtyř stavů: stabilní, přetížení (zátěž nad normou), tichý drift (technika se mění, i když to necítíte) a kritická kombinace (obojí naráz). Klepnutím zobrazíte vývoj za 6 měsíců.",
      value: "Odliší obyčejnou únavu z objemu od změny techniky, kterou zatím necítíte. Každá chce jinou reakci." },
    { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-drivers"]' }, title: "Co ovlivňuje skóre",
      body: "Signály seřazené podle toho, kolik bodů ubírají ze skóre dne. Písmeno A, B nebo C u signálu říká, jak silné jsou pro něj důkazy z výzkumu. Po rozkliknutí uvidíte, které běhy nebo záznamy k němu přispívají.",
      value: "Skóre není černá skříňka. Vidíte, co ho tvoří, a víte, na co se zaměřit." },
  ],
  "/app/training": [
    { route: "/app/training", tab: "Trénink", target: { sel: '[data-tour="training-session"]' }, title: "Dnešní trénink",
      body: "Doporučený typ dne s mantinely: vzdálenost, čas, tep, tempo, minuty tvrdé práce a maximum stoupání i klesání. Dlaždicemi pod ním přepnete na jiný typ a limity se přepočítají.",
      value: "Víte nejen, co běžet, ale i kde je dnes strop. Tempo a tep jsou spočítané z vašich vlastních běhů." },
    { route: "/app/training", tab: "Trénink", target: { text: "Ranní připravenost" }, title: "Připravenost",
      body: "Připravenost po dnech. Pod grafem otevřete spánek, HRV a klidový tep z hodinek, vždy proti vaší vlastní normě. Dny bez noci z hodinek zůstanou v grafu prázdné.",
      value: "Po špatné noci unesete méně. Došlap podle toho ráno sníží dnešní stropy." },
    { route: "/app/training", tab: "Trénink", target: { text: "Dnešní kapacita" }, title: "Dnešní kapacita",
      body: "Kolik si dnes můžete dovolit v objemu, intenzitě, stoupání, klesání a celkové zátěži. Každý pruh ukazuje, kolik z týdne už máte za sebou a kolik zbývá.",
      value: "Kapacita roste s tím, co prokazatelně zvládáte, a hlídá prudké skoky, které tělo nestihne vstřebat." },
    { route: "/app/training", tab: "Trénink", target: { text: "Cyklus · tento týden" }, title: "Týdenní cyklus",
      body: "Trénink běží ve čtyřtýdenních cyklech, tři týdny budovací a jeden odlehčovací. Sloupce ukazují objem posledních týdnů a cíl toho aktuálního.",
      value: "Postupné zvyšování s pravidelným odlehčením je osvědčený tréninkový princip. Došlap ho drží za vás." },
    { route: "/app/training", tab: "Trénink", target: { text: "Závody" }, title: "Závody",
      body: "Kalendář závodů s prioritou A, B nebo C.",
      value: "Před závodem s prioritou A se trénink sám zklidní, abyste na start přišli odpočatí." },
  ],
  "/app/post": [
    { route: "/app/post", tab: "Deník", target: { text: "Poslední zápisy" }, title: "Poslední zápisy",
      body: "Přehled ohodnocených běhů s vaším pocitem a poznámkou. Klepnutím zápis upravíte, ikonou vpravo otevřete detail běhu s terénem, počasím a úseky.",
      value: "Když se něco změní, snadno dohledáte, kdy to začalo a na jakém běhu." },
    { route: "/app/post", tab: "Deník", target: { sel: '[data-tour="journal-summary"]' }, title: "Souhrn deníku",
      body: "Průměrný pocit z běhů a jeho trend, počet zápisů za 21 dní, kolikrát něco bolelo a nejvyšší nahlášená bolest.",
      value: "Zhoršující se pocit z běhů se často objeví dřív než změna v datech z hodinek." },
    { route: "/app/post", tab: "Deník", target: { sel: '[data-tour="journal-sites"]' }, title: "Kde to nejčastěji bolí",
      body: "Mapa těla a žebříček míst, která jste v posledních 30 dnech označili.",
      value: "Místo, které se ozývá opakovaně, stojí za pozornost dřív, než začne omezovat trénink." },
  ],
  "/app/mechanics": [
    { route: "/app/mechanics", tab: "Mechanika", target: { text: "Signál mechaniky" }, title: "Technika běhu",
      body: "Souhrn vaší běžecké techniky. Porovnává se vždy se srovnatelnými běhy ve stejném tempu a terénu, nikdy s průměrem ostatních.",
      value: "Změna techniky bývá časným znakem únavy, často dřív, než ji ucítíte." },
    { route: "/app/mechanics", tab: "Mechanika", target: { text: "Mechanická stabilita — trend" }, title: "Trend techniky",
      body: "Skóre techniky po dnech za 6 měsíců. Nad čárkovanou hranicí 25 se technika drží mimo vaši normu.",
      value: "Rozlišíte jednorázový výkyv po náročném běhu od plíživého trendu." },
    { route: "/app/mechanics", tab: "Mechanika", target: { sel: "[data-norm]", box: ".overflow-hidden" }, title: "Jednotlivé metriky",
      body: "Kontakt se zemí, kadence, odraz, vyváženost a další. Každá metrika má štítek v normě, na hraně nebo mimo normu a klepnutím otevřete její trend.",
      value: "Víte přesně, která část kroku se mění." },
    { route: "/app/mechanics", tab: "Mechanika", target: { text: "Historie běhů" }, title: "Historie běhů",
      body: "Všechny běhy s metrikami techniky. Každý lze otevřít, porovnat s během před měsícem nebo vyřadit z výpočtů, třeba když hodinky změřily nesmysl.",
      value: "Máte pod kontrolou, z jakých běhů se vaše norma počítá." },
  ],
  "/app/load": [
    { route: "/app/load", tab: "Zátěž", target: { text: "Signál zátěže" }, title: "Stav zátěže",
      body: "Jestli trénink v posledních dnech nepřekračuje to, co jste v předchozích týdnech prokazatelně zvládli. Skóre zátěže po dnech, nad hranicí 25 je zvýšená.",
      value: "Prudký nárůst objemu je podle výzkumu spojený s častějšími běžeckými obtížemi (Nielsen et al., 2014). Tady ho uvidíte hned." },
    { route: "/app/load", tab: "Zátěž", target: { text: "Týdenní kapacita" }, title: "Kapacita po kanálech",
      body: "Objem, intenzita, klesání, stoupání a celková zátěž za posledních 7 dní proti vaší kapacitě. Rozkliknutím řádku uvidíte čísla.",
      value: "Tělo nezatěžují jen kilometry. Seběh z kopce působí jinak než rovina, a proto se počítá zvlášť." },
  ],
  "/app/messages": [
    { route: "/app/messages", tab: "Péče", care: "program", target: { sel: '[data-tour="care-tabs"]' }, title: "Tři části péče",
      body: "Program s cviky, Fyzioterapeut pro zprávy a schůzky, pokud ho máte, a Zranění pro nahlášení obtíží a postupný návrat k běhu.",
      value: "Všechno kolem péče o tělo je na jednom místě a navazuje na vaše data." },
    { route: "/app/messages", tab: "Péče", care: "program", target: { sel: '[data-testid="program-tabs"]' }, title: "Všechny programy",
      body: "Programy podle zaměření: při potížích, síla a technika, mobilita. U každého je zdroj a odhad času; sestavit si můžete i vlastní trénink.",
      value: "Vyberete program, který odpovídá tomu, co vás zrovna trápí nebo co chcete zlepšit." },
    { route: "/app/messages", tab: "Péče", care: "health", target: { sel: '[data-tour="care-tabs"]' }, title: "Zranění",
      body: "Když vás něco omezuje v běhu, nahlaste to tady. Plán se přizpůsobí a po zahojení vás aplikace vrátí k běhu postupně.",
      value: "Návrat po zranění po krocích snižuje riziko, že se obtíž vrátí." },
  ],
}

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

function Tour({ steps: TOUR, tabTour = false, name, guest = false, onFinish, onExitDemo }: { steps: TourStep[]; tabTour?: boolean; name?: string | null; guest?: boolean; onFinish: (done: boolean) => void; onExitDemo?: () => void }) {
  const nav = useNavigate()
  const { pathname } = useLocation()
  // step −1 = welcome, TOUR.length = done (a tab's tour starts on its first step)
  const [i, setI] = useState(tabTour ? 0 : -1)
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
    // a step without a target (the reports) is a centred card over the page
    if (!step.target) {
      if (step.care) window.dispatchEvent(new CustomEvent(CARE_SUB_EVENT, { detail: step.care }))
      return
    }
    let tries = 0
    let scrolled = false
    const tick = () => {
      if (step.care) window.dispatchEvent(new CustomEvent(CARE_SUB_EVENT, { detail: step.care }))
      const el = findTarget(step.target)
      if (el) {
        // a tall target scrolls to the top, so the card can take the bottom half without covering it
        if (!scrolled) { el.scrollIntoView({ block: el.getBoundingClientRect().height > window.innerHeight * 0.45 ? "start" : "center", behavior: "auto" }); scrolled = true }
        setRect(el.getBoundingClientRect())
        setMissing(false)
      } else if (++tries > 12) setMissing(true)
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [step])

  const go = useCallback((d: number) => setI((v) => Math.max(tabTour ? 0 : -1, Math.min(TOUR.length, v + d))), [TOUR.length, tabTour])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1)
      if (e.key === "ArrowLeft") go(-1)
      if (e.key === "Escape") onFinish(false)
    }
    window.addEventListener("keydown", k)
    return () => window.removeEventListener("keydown", k)
  }, [go, onFinish])

  const stepNo = step ? i + 1 : 0

  // tooltip placement: below the target when it fits, else above; a target too tall for
  // either gets the card docked on the half of the screen away from it (UX audit F06)
  const vw = typeof window !== "undefined" ? window.innerWidth : 390
  const vh = typeof window !== "undefined" ? window.innerHeight : 800
  const cw = Math.min(360, vw - 32)
  const pad = 8
  const r = rect && !missing ? { top: Math.max(rect.top - pad, 60), bottom: Math.min(rect.bottom + pad, vh - 8), left: Math.max(rect.left - pad, 6), right: Math.min(rect.right + pad, vw - 6) } : null
  const ch = cardRef.current?.offsetHeight ?? 220
  let place: "below" | "above" | "dock" | "center" = "center"
  let dockTop = false
  if (r) {
    place = r.bottom + ch + 24 < vh ? "below" : r.top - ch - 24 > 60 ? "above" : "dock"
    if (place === "dock") {
      // the side with more free room; ties go to the bottom
      const roomTop = r.top - 60, roomBottom = vh - r.bottom
      dockTop = roomTop > roomBottom + 40
    }
  }
  const cx = r ? (r.left + r.right) / 2 : vw / 2
  const left = place === "center" || place === "dock" ? (vw - cw) / 2 : Math.max(16, Math.min(vw - cw - 16, cx - cw / 2))
  const top = place === "below" ? r!.bottom + 14 : place === "above" ? r!.top - ch - 14 : place === "dock" ? (dockTop ? 72 : vh - ch - 16) : Math.max(80, (vh - ch) / 2)
  const arrowX = Math.max(18, Math.min(cw - 18, cx - left))

  const fn = firstName(name)
  const intro = i === -1
  const outro = i === TOUR.length
  const title = intro ? `Vítejte${fn ? `, ${fn}` : ""}!` : outro ? (tabTour ? "To je celá záložka" : "Máte hotovo") : step!.title
  const body = intro
    ? guest
      ? "Ukážeme vám to nejdůležitější na ukázkovém běžci s vymyšlenými daty, bez registrace. Šest krátkých kroků, u každého uvidíte, co ukazuje a proč vám pomůže. Ukázku můžete kdykoli ukončit."
      : "Ukážeme vám to nejdůležitější na ukázkovém účtu s vaším jménem. Šest krátkých kroků, u každého uvidíte, co ukazuje a proč vám pomůže."
    : outro
      ? tabTour
        ? "Další záložku vám ukáže ikona kompasu nahoře, když na ní budete."
        : guest
          ? "To nejdůležitější znáte. Ukázku můžete dál volně procházet, nebo si založte účet a připojte vlastní data z hodinek. Co je na které záložce, ukáže ikona kompasu nahoře."
          : "To nejdůležitější znáte. Průvodce se vrátí na vaše vlastní data. Co je na které záložce, vám kdykoli ukáže ikona kompasu nahoře."
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
          <p className="t-label">{intro ? "Průvodce aplikací" : outro ? "Hotovo" : `${tabTour ? `${step!.tab} · ` : ""}${stepNo}/${TOUR.length}`}</p>
          <button type="button" onClick={() => onFinish(false)} aria-label="Ukončit průvodce" className="grid size-7 place-items-center rounded-full text-fg-2 hover:bg-white/[.07]"><X className="size-4" aria-hidden /></button>
        </div>
        <h3 className="mt-1 text-[17px] font-extrabold tracking-[-.01em]">{title}</h3>
        <p className="mt-1.5 text-[13.5px] leading-[1.5] text-fg-2">{body}</p>
        {step && !missing && (
          <p className="mt-2.5 rounded-xl border border-accent/25 bg-accent/[.08] px-3 py-2 text-[13px] leading-[1.45] text-fg">
            <b className="text-accent">Proč to pomáhá: </b>{step.value}
          </p>
        )}
        {/* where we are: one dot per step */}
        <div className="mt-3 flex items-center gap-1.5" aria-hidden>
          {TOUR.map((_, k) => (
            <span key={k} className={`h-1.5 rounded-full transition-all ${k === i ? "w-5 bg-accent" : k < i || outro ? "w-1.5 bg-accent/60" : "w-1.5 bg-white/20"}`} />
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <button type="button" onClick={() => go(-1)} disabled={intro || (tabTour && i === 0)} aria-label="Zpět" className="btn btn-outline btn-sm disabled:opacity-40"><ArrowLeft className="size-4" aria-hidden /></button>
          {outro && guest && !tabTour
            ? <span className="flex gap-2">
                <button type="button" onClick={() => onFinish(true)} className="btn btn-outline btn-sm">Procházet ukázku</button>
                <button type="button" onClick={onExitDemo} className="btn btn-primary btn-sm" data-testid="demo-register">Založit účet</button>
              </span>
            : outro
            ? <button type="button" onClick={() => onFinish(true)} className="btn btn-primary btn-sm">{tabTour ? "Zpět na záložku" : "Dokončit průvodce"}</button>
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
  return useMemo(() => ({ show: !!state?.active && !state.completed, done: state ? state.steps.filter((s) => s.done).length : 0, total: state?.steps.length ?? 2, pending, openCard }), [state, pending, openCard])
}
