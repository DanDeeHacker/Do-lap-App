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
}
const Ctx = createContext<ObCtx>({ state: null, openCard: () => {}, pending: 0 })
export const useOnboarding = () => useContext(Ctx)

export const EDIT_PROFILE_EVENT = "doslap:edit-profile"

const STEP_UI: Record<Step["id"], { title: string; sub: string; icon: typeof PlugZap }> = {
  data: { title: "Připojit data", sub: "Garmin nebo Apple Health v Data a připojení", icon: PlugZap },
  profile: { title: "Vyplnit profil", sub: "rok narození, pohlaví, zranění, cílový závod", icon: UserPen },
  tutorial: { title: "Projít průvodce aplikací", sub: "ukázkový účet s vaším jménem, záložku po záložce", icon: Compass },
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { realMe, touring, boot, startTour, endTour } = useApp()
  const rid = realMe?.runner_id
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
  const finishTour = (done: boolean) => {
    setTourOn(false)
    endTour()
    nav("/app/today")
    if (done && rid) api.updateOnboarding(rid, { tutorialDone: true }).then((s) => { setState(s); setManual(true) }).catch(() => {})
    else setManual(true)
  }

  return (
    <Ctx.Provider value={{ state, openCard: () => setManual(true), pending }}>
      {children}
      {show && state && <GetStartedCard state={state} name={realMe?.name} busy={busy} onAct={act} onClose={close} />}
      {tourOn && touring && <Tour name={realMe?.name} onFinish={finishTour} />}
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
type TourStep = { route: string; tab: string; target?: Target; title: string; body: string }

const TABS: [string, string][] = [["/app/today", "Dnes"], ["/app/training", "Trénink"], ["/app/post", "Deník"], ["/app/mechanics", "Pohyb"], ["/app/load", "Zátěž"], ["/app/messages", "Péče"]]

// At most five features per tab. Texts describe what the runner can do with the
// feature, not how the engine computes it.
export const TOUR: TourStep[] = [
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-score"]' }, title: "Skóre a osy stavu",
    body: "Velké číslo je celkové skóre, čím vyšší, tím lépe. Kolem něj jsou Regenerace, Příznaky, Zátěž a Mechanika. Klepnutím na kteroukoli otevřete detail s trendem." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-reco"]' }, title: "Dnešní doporučení",
    body: "Co dnes běžet a v jakém rozsahu. Podrobné mantinely najdete v záložce Trénink." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-quadrant"]' }, title: "Kvadrant stavu",
    body: "Zátěž a mechanika dávají jeden ze čtyř stavů: stabilní, přetížení, tichý drift nebo kritická kombinace. Klepnutím zobrazíte vývoj za posledních 6 měsíců." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="today-drivers"]' }, title: "Co ovlivňuje stav",
    body: "Signály seřazené podle vlivu, například skok v objemu nebo opakovaná bolest. Vysvětlují, proč je stav právě takový." },
  { route: "/app/today", tab: "Dnes", target: { sel: '[data-tour="checkin"]' }, title: "Denní check-in",
    body: "Pár vteřin denně: bolest, ztuhlost a únava. Zpřesňuje hodnocení i doporučení a bolest můžete označit přímo na mapě těla." },

  { route: "/app/training", tab: "Trénink", target: { text: "Trénink ·" }, title: "Dnešní trénink",
    body: "Typ dne, rozsah kilometrů, tepové zóny a tempo. Typ si můžete přepnout a limity se přepočítají." },
  { route: "/app/training", tab: "Trénink", target: { text: "Dnešní kapacita" }, title: "Dnešní kapacita",
    body: "Kolik objemu, intenzity a převýšení dnes unesete podle toho, co jste v posledních týdnech zvládli, a podle ranní regenerace." },
  { route: "/app/training", tab: "Trénink", target: { text: "Cyklus · tento týden" }, title: "Týdenní cyklus",
    body: "Týdenní rozpočet ve čtyřtýdenním cyklu s odlehčovacím týdnem. Ukazuje, kolik z něj už máte za sebou." },
  { route: "/app/training", tab: "Trénink", target: { text: "Závody" }, title: "Závody",
    body: "Přidejte své závody a trénink se před nimi sám zklidní." },

  { route: "/app/post", tab: "Deník", target: { text: "Čeká na zápis" }, title: "Běhy k ohodnocení",
    body: "Po každém běhu krátce zapište, jak se běželo a jestli něco bolelo. Tyto zápisy engine používá nejvíc." },
  { route: "/app/post", tab: "Deník", target: { text: "Poslední zápisy" }, title: "Poslední zápisy",
    body: "Přehled běhů s vaším hodnocením. Klepnutím otevřete detail běhu s terénem, počasím a úseky." },
  { route: "/app/post", tab: "Deník", target: { text: "Souhrn deníku" }, title: "Souhrn deníku",
    body: "Jak se vám běhá v posledních týdnech a kde vás to nejčastěji bolí, včetně mapy těla." },
  { route: "/app/post", tab: "Deník", target: { text: "Check-iny (denní a týdenní)" }, title: "Historie check-inů",
    body: "Všechny denní a týdenní check-iny na jednom místě." },

  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Signál pohybu" }, title: "Stav mechaniky",
    body: "Jestli vaše technika drží normu, nebo se začíná měnit, což bývá časný znak únavy." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Mechanická stabilita — trend" }, title: "Trend mechaniky",
    body: "Vývoj po dnech za posledních 6 měsíců. Nad prahem 25 jde o drift." },
  { route: "/app/mechanics", tab: "Pohyb", target: { sel: "[data-norm]", box: ".overflow-hidden" }, title: "Jednotlivé metriky",
    body: "Vertikální poměr, kontakt se zemí, kadence a další, vždy proti vaší normě se štítkem v normě, na hraně nebo mimo normu. Klepnutím uvidíte celý trend." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Podle profilu terénu", box: "div" }, title: "Podle terénu",
    body: "Srovnání metrik na rovině, v kopcích a v různém tempu." },
  { route: "/app/mechanics", tab: "Pohyb", target: { text: "Historie běhů" }, title: "Historie běhů",
    body: "Každý běh lze otevřít, porovnat s během před měsícem nebo vyřadit z výpočtů." },

  { route: "/app/load", tab: "Zátěž", target: { text: "Signál zátěže" }, title: "Stav zátěže",
    body: "Jestli trénink nepřekračuje to, co jste prokazatelně zvládli." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Skóre zátěže — trend" }, title: "Trend zátěže",
    body: "Vývoj skóre zátěže po dnech za posledních 6 měsíců." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Týdenní kapacita" }, title: "Kapacita po kanálech",
    body: "Objem, intenzita, klesání, stoupání a celková zátěž, každý proti vaší kapacitě. Nejvíc riskantní jsou prudké skoky." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Co tvoří skóre zátěže" }, title: "Co tvoří zátěž",
    body: "Které kanály nejvíc přispívají k dnešnímu skóre, od objemu po klesání." },
  { route: "/app/load", tab: "Zátěž", target: { text: "Spánek" }, title: "Regenerace",
    body: "Spánek, HRV a klidový tep proti vaší normě. Špatná noc dočasně snižuje, kolik toho unesete." },

  { route: "/app/messages", tab: "Péče", target: { sel: '[data-tour="care-tabs"]' }, title: "Tři části péče",
    body: "Fyzioterapeut pro zprávy a schůzky, Program s cviky od fyzioterapeuta a Zdraví pro nahlášení obtíží a návrat k běhu po zranění." },
  { route: "/app/messages", tab: "Péče", target: { sel: '[data-tour="care-chat"]' }, title: "Zprávy fyzioterapeutovi",
    body: "Napište fyzioterapeutovi přímo z aplikace. Vaše data uvidí, až potvrdíte zájem a on převezme váš případ." },
  { route: "/app/messages", tab: "Péče", target: { text: "Schůzka" }, title: "Schůzka",
    body: "Potvrďte zájem o fyzioterapii a vyberte termín vyšetření, analýzy běhu nebo videokonzultace." },
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

function Tour({ name, onFinish }: { name?: string | null; onFinish: (done: boolean) => void }) {
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
    ? "Ukážeme vám aplikaci na ukázkovém účtu s vaším jménem. Projdeme šest záložek a u každé nejvýš pět věcí, které stojí za to znát. Šipkami se posunete dál nebo zpět."
    : outro
      ? "Teď už víte, kde co najdete. Průvodce se vrátí na vaše vlastní data a můžete ho kdykoli spustit znovu přes ikonu profilu → Začínáme."
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
        {/* where we are: one dot per tab */}
        <div className="mt-3 flex items-center gap-1.5" aria-hidden>
          {TABS.map(([rt, lbl], k) => (
            <span key={rt} title={lbl} className={`h-1.5 rounded-full transition-all ${k === tabIdx ? "w-5 bg-accent" : k < tabIdx || outro ? "w-1.5 bg-accent/60" : "w-1.5 bg-white/20"}`} />
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <button type="button" onClick={() => go(-1)} disabled={intro} aria-label="Zpět" className="btn btn-outline btn-sm disabled:opacity-40"><ArrowLeft className="size-4" aria-hidden /></button>
          {outro
            ? <button type="button" onClick={() => onFinish(true)} className="btn btn-primary btn-sm">Dokončit průvodce</button>
            : <button type="button" onClick={() => go(1)} aria-label="Další" className="btn btn-primary btn-sm">{intro ? "Začít" : "Další"} <ArrowRight className="size-4" aria-hidden /></button>}
        </div>
      </div>
      <TourBanner />
    </div>,
    document.body,
  )
}

function TourBanner() {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[calc(10px+env(safe-area-inset-top))] z-[101] flex justify-center">
      <span className="rounded-full bg-accent px-3 py-1 text-[11px] font-extrabold uppercase tracking-[.08em] text-ink shadow">Ukázka · data nejsou vaše</span>
    </div>
  )
}

// small helper used by the profile menu
export function useObSummary() {
  const { state, pending, openCard } = useOnboarding()
  return useMemo(() => ({ show: !!state?.active && !state.completed, done: state ? state.steps.filter((s) => s.done).length : 0, total: state?.steps.length ?? 3, pending, openCard }), [state, pending, openCard])
}
