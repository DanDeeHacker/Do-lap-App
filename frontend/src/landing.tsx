// Landing page on /auth: what Došlap is, how it works and how to start.
// Sales copy for prospective runners, built from Documentation/DOSLAP_co_delame.md.
// Every number shown as a fact carries its source in the footer; illustrative
// values (watch, phone, flow, engine demo) are labelled as a demo. No medical claims:
// Došlap shows changes against the runner's own norm, it does not diagnose
// (MDR note in the project, enforced by backend/tests/test_wording.py).
//
// 2026-10 redesign: a sticky top bar with the sections and sign-in / sign-up always in
// reach, and a scroll story on one theme: the watch on the wrist → the data flowing
// in → the runner's own norm → today's state → the physiotherapist. Effects respect
// prefers-reduced-motion (index.css) and work without them.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import {
  Activity, ArrowRight, Bot, CalendarCheck, Check, ChevronDown, ClipboardList, Dumbbell, Footprints, Gauge, Heart,
  Menu, MessageCircle, Mountain, NotebookPen, Play, ShieldCheck, Smartphone, Sparkles, Stethoscope, Watch, X,
} from "lucide-react"
import { C } from "@/tokens"
import { QUAD } from "@/lib"
import { Mark, Wordmark } from "@/shell"
import { LangSwitch } from "@/i18n/LangSwitch"

const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))

/* ------------------------------------------------------------------ motion helpers */
function useInView<T extends Element>(threshold = 0.18) {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return }
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setSeen(true); io.disconnect() }
    }, { threshold, rootMargin: "0px 0px -6% 0px" })
    io.observe(el)
    return () => io.disconnect()
  }, [threshold])
  return [ref, seen] as const
}

function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const [ref, seen] = useInView<HTMLDivElement>()
  return (
    <div ref={ref} className={`reveal ${seen ? "in" : ""} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  )
}

/** How far the element has scrolled through the viewport: 0 when its top reaches the
 *  top of the screen, 1 when its bottom reaches the bottom (a pinned section's track). */
function useScrollTrack<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [p, setP] = useState(0)
  useEffect(() => {
    let raf = 0
    const on = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const el = ref.current
        if (!el) return
        const r = el.getBoundingClientRect()
        const v = clamp01(-r.top / Math.max(1, r.height - window.innerHeight))
        setP((old) => (Math.abs(old - v) > 0.002 ? v : old))
      })
    }
    on()
    window.addEventListener("scroll", on, { passive: true })
    window.addEventListener("resize", on)
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", on); window.removeEventListener("resize", on) }
  }, [])
  return [ref, p] as const
}

/** Counts up to `to` once the number scrolls into view. */
function CountUp({ to, decimals = 0, suffix = "" }: { to: number; decimals?: number; suffix?: string }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.5)
  const [v, setV] = useState(0)
  useEffect(() => {
    if (!seen) return
    if (reducedMotion()) { setV(to); return }
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 1300)
      setV(to * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [seen, to])
  return <span ref={ref}>{v.toLocaleString("cs-CZ", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>
}

function Kicker({ children }: { children: ReactNode }) {
  return <p className="t-label" style={{ color: C.accent }}>{children}</p>
}
function H2({ children }: { children: ReactNode }) {
  return <h2 className="mt-3 max-w-3xl font-serif text-[30px] leading-[1.08] tracking-[-.02em] text-fg md:text-5xl">{children}</h2>
}
function Lead({ children }: { children: ReactNode }) {
  return <p className="mt-4 max-w-2xl text-[15px] leading-7 text-fg-soft md:text-base">{children}</p>
}
function Section({ id, children, className = "" }: { id?: string; children: ReactNode; className?: string }) {
  return <section id={id} className={`mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-16 md:px-8 md:py-24 ${className}`}>{children}</section>
}

function goTo(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" })
  history.replaceState(null, "", `#${id}`)
}

/* ------------------------------------------------------------------ quadrant model (demo) */
// Same thresholds as the engine (QUAD_THRESHOLD = 25, without the hysteresis) and
// the same weights of the overall points (0.38·M + 0.40·Z + 0.52·S). The app shows
// 100 − points as the score, higher is better.
type Q = "stable" | "overreaching" | "silent" | "critical"
const QCOL: Record<Q, string> = { stable: C.ok, overreaching: C.watch, silent: C.self, critical: C.alert }
const QRECO: Record<Q, string> = {
  stable: "Pokračujte podle plánu. Tělo zátěž zvládá a technika drží vaši normu.",
  overreaching: "Uberte objem nebo intenzitu a dejte prostor regeneraci, než se zátěž usadí.",
  silent: "Technika se mění dřív, než to ucítíte. Zařaďte lehčí dny a sledujte, jestli se vrací k normě.",
  critical: "Zátěž i mechanika se hýbou naráz. Teď má smysl domluvit si konzultaci s fyzioterapeutem.",
}
const TH = 25
const AX_MAX = 60
const quadOf = (m: number, z: number): Q => (z >= TH && m >= TH ? "critical" : z >= TH ? "overreaching" : m >= TH ? "silent" : "stable")
const scoreOf = (m: number, z: number, s: number) => Math.max(0, 100 - Math.min(100, Math.round(0.38 * m + 0.4 * z + 0.52 * s)))
const TIERS = [{ t: "V pořádku", c: C.ok }, { t: "Sledovat", c: C.watch }, { t: "Jednat", c: C.alert }]
const QTIER: Record<Q, number> = { stable: 0, overreaching: 1, silent: 1, critical: 2 }
// UX audit F20 — the label follows the worse of the score and the state, as in the app
// (the demo read "v pořádku" next to "Přetížení")
const tierOf = (score: number, q: Q) => TIERS[Math.max(100 - score >= 70 ? 2 : 100 - score >= 40 ? 1 : 0, QTIER[q])]

function ScoreRing({ value, color, size = 132, label }: { value: number; color: string; size?: number; label?: string }) {
  const r = 44
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden className="shrink-0">
      <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="8" />
      <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={c * (1 - Math.min(100, value) / 100)} transform="rotate(-90 50 50)" style={{ transition: "stroke-dashoffset .6s cubic-bezier(.22,1,.36,1), stroke .4s" }} />
      <text x="50" y="58" textAnchor="middle" fontSize="28" fontWeight="800" fill={C.fg} fontFamily="Manrope, Arial, sans-serif">{label ?? value}</text>
    </svg>
  )
}

/* ------------------------------------------------------------------ top bar */
const NAV: [string, string][] = [
  ["jak-to-funguje", "Jak to funguje"],
  ["aplikace", "Aplikace"],
  ["vyzkousejte", "Vyzkoušet"],
  ["pripojeni", "Připojení"],
  ["fyzio", "Fyzioterapie"],
  ["faq", "Otázky"],
]
function LandingNav({ onRegister, onLogin, returning }: { onRegister: () => void; onLogin: () => void; returning: boolean }) {
  const [scrolled, setScrolled] = useState(false)
  const [active, setActive] = useState("")
  const [menu, setMenu] = useState(false)
  const bar = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = document.documentElement
    const on = () => {
      const y = window.scrollY
      const h = root.scrollHeight - window.innerHeight
      setScrolled(y > 8)
      if (bar.current) bar.current.style.transform = `scaleX(${h > 0 ? clamp01(y / h) : 0})`
      root.style.setProperty("--landing-sy", String(h > 0 ? clamp01(y / h) : 0))
    }
    on()
    window.addEventListener("scroll", on, { passive: true })
    return () => { window.removeEventListener("scroll", on); root.style.removeProperty("--landing-sy") }
  }, [])
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: "-45% 0px -50% 0px" })
    ;["uvod", ...NAV.map(([id]) => id), "zacit"].forEach((id) => { const el = document.getElementById(id); if (el) io.observe(el) })
    return () => io.disconnect()
  }, [])
  const link = (id: string) => (e: React.MouseEvent) => { e.preventDefault(); setMenu(false); goTo(id) }
  return (
    <header className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 ${scrolled || menu ? "border-b border-white/[.08] bg-bg/80 backdrop-blur-xl" : "border-b border-transparent"}`}
      data-testid="landing-nav">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4 md:px-8">
        <a href="#uvod" onClick={(e) => { e.preventDefault(); setMenu(false); window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" }); history.replaceState(null, "", location.pathname) }}
          className="flex shrink-0 items-center gap-2 text-lg font-extrabold tracking-[-.04em]" aria-label="Došlap — nahoru">
          <Mark size={30} /><span className="max-[359px]:hidden"><Wordmark /></span>
        </a>
        <nav className="ml-5 hidden items-center gap-0.5 lg:flex" aria-label="Sekce stránky">
          {NAV.map(([id, t]) => (
            <a key={id} href={`#${id}`} onClick={link(id)} aria-current={active === id ? "true" : undefined}
              className={`relative rounded-full px-3 py-1.5 text-[13px] font-bold transition-colors ${active === id ? "bg-white/[.08] text-fg" : "text-fg-2 hover:text-fg"}`}>
              {t}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <span className="hidden md:block"><LangSwitch /></span>
          <button type="button" onClick={onLogin} data-testid="nav-login"
            className={`btn btn-sm whitespace-nowrap px-3 ${returning ? "btn-primary" : "btn-outline"}`}>Přihlásit se</button>
          <button type="button" onClick={onRegister} data-testid="nav-register"
            className={`btn btn-sm whitespace-nowrap px-3 ${returning ? "btn-outline max-sm:hidden" : "btn-primary"}`}>
            <span className="sm:hidden">Registrace</span><span className="max-sm:hidden">Vytvořit účet</span>
          </button>
          <button type="button" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label={menu ? "Zavřít menu" : "Otevřít menu"}
            className="grid size-9 shrink-0 place-items-center rounded-full border border-white/12 text-fg-2 hover:text-fg lg:hidden" data-testid="nav-menu">
            {menu ? <X className="size-4" aria-hidden /> : <Menu className="size-4" aria-hidden />}
          </button>
        </div>
      </div>
      {menu && (
        <nav className="animate-[fadeIn_.2s_ease-out] border-t border-white/[.06] px-4 pb-4 pt-2 lg:hidden" aria-label="Sekce stránky">
          <div className="mx-auto grid max-w-6xl grid-cols-2 gap-1.5">
            {NAV.map(([id, t]) => (
              <a key={id} href={`#${id}`} onClick={link(id)}
                className={`rounded-2xl px-3.5 py-3 text-[14px] font-bold ${active === id ? "bg-accent/15 text-fg" : "bg-white/[.04] text-fg-soft"}`}>{t}</a>
            ))}
          </div>
          <div className="mx-auto mt-3 flex max-w-6xl items-center justify-between gap-2">
            <LangSwitch />
            {returning && <button type="button" onClick={() => { setMenu(false); onRegister() }} className="btn btn-outline btn-sm">Vytvořit účet</button>}
          </div>
        </nav>
      )}
      <div ref={bar} className="absolute bottom-[-1px] left-0 h-[2px] w-full origin-left" style={{ transform: "scaleX(0)", background: `linear-gradient(90deg, ${C.info}, ${C.accent})` }} aria-hidden />
    </header>
  )
}

/* ------------------------------------------------------------------ the watch */
// An illustrative smartwatch mid-run: live heart rate, distance and an ECG-like trace.
function SmartWatch({ className = "", style }: { className?: string; style?: CSSProperties }) {
  const [hr, setHr] = useState(148)
  useEffect(() => {
    if (reducedMotion()) return
    const t = setInterval(() => setHr((h) => Math.min(153, Math.max(143, h + Math.round(Math.random() * 4 - 2)))), 1100)
    return () => clearInterval(t)
  }, [])
  return (
    <div className={`watch-rig ${className || "relative"}`} style={style} aria-hidden>
      <div className="absolute inset-x-[19%] -top-[30%] h-[38%] rounded-t-[26px] border border-white/[.06] bg-gradient-to-b from-[#0b1514] to-[#13231f]" />
      <div className="absolute inset-x-[19%] -bottom-[30%] h-[38%] rounded-b-[26px] border border-white/[.06] bg-gradient-to-t from-[#0b1514] to-[#13231f]" />
      <div className="absolute -right-[4%] top-[30%] h-[16%] w-[6%] rounded-r-md bg-gradient-to-b from-[#3a4542] to-[#1a2220]" />
      <div className="relative aspect-[0.88] rounded-[30%/27%] bg-gradient-to-br from-[#36423f] via-[#151d1c] to-[#0a100f] p-[6.5%] shadow-[0_30px_60px_-20px_rgb(0_0_0_/_.8),inset_0_1px_0_rgb(255_255_255_/_.12)]">
        <div className="flex h-full w-full flex-col justify-between overflow-hidden rounded-[27%/24%] bg-black px-[11%] py-[12%]">
          <div className="flex items-center justify-between text-[10px] font-bold text-fg-3">
            <span className="flex items-center gap-1"><Footprints className="size-3" style={{ color: C.accent }} />Běh</span>
            <span className="t-num text-fg-2">8,42 km</span>
          </div>
          <div className="flex items-end gap-1.5">
            <Heart className="watch-beat mb-1.5 size-4 shrink-0" style={{ color: C.alert, fill: C.alert }} />
            <span className="t-num text-[34px] leading-none text-fg">{hr}</span>
            <span className="mb-1 text-[10px] font-bold text-fg-3">tep/min</span>
          </div>
          <svg viewBox="0 0 100 24" className="h-5 w-full" preserveAspectRatio="none">
            <path className="watch-ecg" d="M0 14 L18 14 L22 9 L26 18 L30 3 L34 20 L38 14 L58 14 L62 10 L66 17 L70 4 L74 19 L78 14 L100 14"
              fill="none" stroke={C.info} strokeWidth="2" strokeLinejoin="round" pathLength={100} />
          </svg>
          <div className="flex justify-between text-[9.5px] font-bold text-fg-3"><span>5:28 /km</span><span>172 kr.</span></div>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ hero phone */
const PHONE_STATES: { q: Q; score: number; drivers: [string, string][] }[] = [
  { q: "stable", score: 86, drivers: [["Objem týdne", "v normě"], ["Kontakt se zemí", "v normě"], ["Spánek", "7 h 40 min"]] },
  { q: "overreaching", score: 58, drivers: [["Objem týdne", "+38 % nad normou"], ["Klesání", "nad kapacitou"], ["HRV", "pod normou"]] },
  { q: "silent", score: 64, drivers: [["Vertikální poměr", "mimo normu"], ["Kadence", "na hraně"], ["Objem týdne", "v normě"]] },
  { q: "critical", score: 31, drivers: [["Objem týdne", "+45 % nad normou"], ["Kontakt se zemí", "mimo normu"], ["Bolest", "opakovaně Achilovka"]] },
]
function HeroPhone() {
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    if (paused || reducedMotion()) return
    const t = setInterval(() => setI((x) => (x + 1) % PHONE_STATES.length), 3600)
    return () => clearInterval(t)
  }, [paused])
  const st = PHONE_STATES[i]
  const col = QCOL[st.q]
  return (
    <div className="relative w-full" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="absolute -inset-10 -z-10 rounded-full blur-3xl transition-colors duration-700" style={{ background: `${col}24` }} aria-hidden />
      <div className="rounded-[38px] border border-white/12 bg-gradient-to-b from-panel-2 to-panel p-2.5 shadow-2xl shadow-black/60">
        <div className="rounded-[30px] bg-bg p-4">
          <div className="flex items-center justify-between text-[11px] text-fg-3">
            <span className="font-bold text-fg-2">Dnes</span>
            <span className="rounded-full bg-white/8 px-2 py-0.5">ukázková data</span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <ScoreRing value={st.score} color={col} size={92} />
            <div className="min-w-0">
              <p className="t-label">Stav</p>
              <p className="mt-1 font-serif text-xl leading-tight transition-colors duration-500" style={{ color: col }}>{QUAD[st.q].t}</p>
            </div>
          </div>
          <p key={st.q} className="mt-3 animate-[fadeIn_.5s_ease-out] rounded-2xl bg-white/5 p-3 text-[12.5px] leading-5 text-fg-soft">{QRECO[st.q]}</p>
          <div className="mt-3 space-y-1.5">
            {st.drivers.map(([k, v]) => (
              <div key={st.q + k} className="flex animate-[fadeIn_.5s_ease-out] items-center justify-between gap-2 rounded-xl border border-white/6 px-3 py-2 text-[12px]">
                <span className="text-fg-2">{k}</span>
                <b className="text-right text-fg">{v}</b>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-4 flex justify-center gap-2" role="tablist" aria-label="Stavy v ukázce">
        {PHONE_STATES.map((s, k) => (
          <button key={s.q} role="tab" aria-selected={k === i} aria-label={QUAD[s.q].t} onClick={() => { setI(k); setPaused(true) }}
            className="h-2 rounded-full transition-all duration-300" style={{ width: k === i ? 26 : 8, background: k === i ? QCOL[s.q] : "rgb(255 255 255 / .2)" }} />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ hero */
// Streams from the watch into the phone: (label, value, colour, y of the phone end in %)
const STREAMS: [string, string, string, number][] = [
  ["Tep", "148 tep/min", C.alert, 20],
  ["HRV", "56 ms", C.ok, 33],
  ["Kontakt se zemí", "248 ms", C.self, 46],
  ["Spánek", "7 h 12 min", C.load, 59],
]
function Hero({ onRegister, onLogin, onDemo, demoBusy, notice }: { onRegister: () => void; onLogin: () => void; onDemo?: () => void; demoBusy: boolean; notice?: string | null }) {
  const ref = useRef<HTMLElement>(null)
  // parallax: --hp goes 0 → 1 while the hero scrolls out of view
  useEffect(() => {
    if (reducedMotion()) return
    let raf = 0
    const on = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const el = ref.current
        if (!el) return
        el.style.setProperty("--hp", String(clamp01(window.scrollY / Math.max(1, el.offsetHeight))))
      })
    }
    on()
    window.addEventListener("scroll", on, { passive: true })
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", on) }
  }, [])
  return (
    <section id="uvod" ref={ref} className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-5 pb-10 pt-24 md:px-8 md:pb-20 md:pt-32">
      <div className="grid items-center gap-10 md:grid-cols-[1.05fr_1fr] md:gap-8">
        <div className="hero-copy">
          <Kicker>Pro běžce a jejich fyzioterapeuty</Kicker>
          <h1 className="mt-4 font-serif text-[40px] leading-[1.02] tracking-[-.025em] text-fg md:text-[64px]">
            Víte, kolik naběháte. Došlap vám ukáže, <span style={{ color: C.accent }}>kolik toho tělo unese.</span>
          </h1>
          <p className="mt-6 max-w-xl text-[16px] leading-7 text-fg-soft">
            Data z hodinek a krátký deník skládá každý den do jednoho srozumitelného stavu proti vaší vlastní normě. Řekne vám, kolik toho dnes unesete, a když je čas zpomalit nebo zajít za fyzioterapeutem, vysvětlí proč.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button onClick={onRegister} className="btn btn-primary px-6 py-3.5 text-[14px]" data-testid="hero-register">Vytvořit účet<ArrowRight className="size-4" aria-hidden /></button>
            {onDemo && (
              <button onClick={onDemo} disabled={demoBusy} className="btn btn-outline px-6 py-3.5 text-[14px]" data-testid="hero-demo">
                <Play className="size-4" aria-hidden />{demoBusy ? "Otevírám ukázku…" : "Vyzkoušet ukázku"}
              </button>
            )}
          </div>
          <p className="mt-3 text-[13px] text-fg-2">
            Už máte účet? <button type="button" onClick={onLogin} className="font-extrabold text-accent underline-offset-4 hover:underline" data-testid="hero-login">Přihlásit se</button>
            {onDemo && <span className="text-fg-3"> · ukázka je bez registrace, na běžci s vymyšlenými daty</span>}
          </p>
          {notice && <p role="alert" className="mt-3 text-[13px] font-bold text-alert">{notice}</p>}
          <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-fg-2">
            {["Osobní norma místo průměru", "Vysvětlitelné skóre", "Napojení na fyzioterapeuta"].map((t) => (
              <span key={t} className="flex items-center gap-2"><Check className="size-4" style={{ color: C.accent }} aria-hidden />{t}</span>
            ))}
          </div>
        </div>

        <div className="relative mx-auto aspect-[10/11] w-full max-w-[520px]" data-testid="hero-visual">
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 110" preserveAspectRatio="none" aria-hidden>
            {STREAMS.map(([, , col, y], k) => {
              const d = `M 20 66 C 18 ${44 - k * 4}, 30 ${y + 2}, 47 ${y}`
              return (
                <g key={k}>
                  <path d={d} fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
                  <path d={d} fill="none" stroke={col} strokeWidth="2.6" strokeLinecap="round" vectorEffect="non-scaling-stroke"
                    pathLength={100} className="stream-flow" style={{ animationDelay: `${k * -0.55}s` }} />
                </g>
              )
            })}
          </svg>
          <div className="hero-phone absolute right-0 top-0 w-[300px] origin-top-right max-sm:scale-[.74] sm:scale-90 md:scale-100 md:w-[285px]">
            <HeroPhone />
          </div>
          <SmartWatch className="hero-watch absolute bottom-[12%] left-[2%] w-[36%] max-w-[178px]" />
          {STREAMS.map(([t, v, col], k) => (
            <span key={t} className="stream-chip absolute left-[1%] hidden rounded-full border border-white/10 bg-bg/85 px-2.5 py-1 text-[11px] font-bold text-fg-soft shadow-lg shadow-black/40 backdrop-blur sm:inline-flex"
              style={{ top: `${6 + k * 9.5}%`, animationDelay: `${k * 0.4}s` }}>
              <span className="mr-1.5 mt-[3px] size-2 rounded-full" style={{ background: col }} />{t} <b className="ml-1 text-fg">{v}</b>
            </span>
          ))}
        </div>
      </div>
      <button type="button" onClick={() => goTo("jak-to-funguje")} className="group mx-auto mt-10 hidden flex-col items-center gap-1.5 text-fg-2 hover:text-accent md:flex" data-testid="scroll-cue">
        <span className="text-[12px] font-extrabold uppercase tracking-[.14em]">Jak to funguje</span>
        <span className="cue-bounce grid size-9 place-items-center rounded-full border border-white/15 bg-white/5 group-hover:border-accent"><ChevronDown className="size-5" aria-hidden /></span>
      </button>
    </section>
  )
}

/* ------------------------------------------------------------------ problem */
const STATS: { n: ReactNode; t: string; src: string }[] = [
  { n: <><CountUp to={19} />–<CountUp to={79} /> %</>, t: "běžců se během roku potýká s běžeckým zraněním dolní končetiny", src: "van Gent et al., 2007" },
  { n: <><CountUp to={2.3} decimals={1} /> mil.</>, t: "pacientů přijatých v Česku k léčbě v oboru rehabilitační a fyzikální medicíny za rok 2019", src: "ÚZIS podle Hrot24, 2021" },
  { n: <CountUp to={79} />, t: "fyzioterapeutů na 100 000 obyvatel Česka, v Německu je jich téměř třikrát víc", src: "Evropská komise podle HN, b.r." },
  { n: <>až <CountUp to={3} /> měs.</>, t: "může trvat čekání na volný termín u fyzioterapeuta", src: "Hrot24, 2021" },
]
const BEFORE_AFTER: { who: string; icon: typeof Footprints; before: string; after: string }[] = [
  { who: "Běžec", icon: Footprints, before: "Vidí kilometry a tempo, ale ne to, jak je jeho tělo snáší. Signál přichází, až když už bolí.", after: "Vidí zátěž, techniku i příznaky proti své vlastní normě a každý den ví, co s tím dělat." },
  { who: "Fyzioterapeut", icon: Stethoscope, before: "Formuláře v e-mailu, papírové dotazníky a žádná data o tom, co se dělo mezi návštěvami.", after: "Klient přichází i s historií, daty z hodinek a průběhem programu, takže práce nezačíná od nuly." },
  { who: "Mezi návštěvami", icon: CalendarCheck, before: "Měsíc bez kontaktu a plán na papíře. Když se něco změní, čeká se na další termín.", after: "Program v aplikaci, odškrtávání, chat a úprava plánu dřív než na další kontrole." },
]
function Problem() {
  const [after, setAfter] = useState(false)
  return (
    <Section id="problem">
      <Reveal>
        <Kicker>Proč vznikl Došlap</Kicker>
        <H2>Kilometry máte spočítané. To, jak je vaše tělo snáší, zatím ne.</H2>
        <Lead>Běžecká zranění jsou častá a cesta k fyzioterapeutovi bývá dlouhá. Mezi hodinkami na ruce a odborníkem, který by data uměl přečíst, dnes chybí most.</Lead>
      </Reveal>
      <div className="mt-10 grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        {STATS.map((s, k) => (
          <Reveal key={s.src} delay={k * 90}>
            <div className="card h-full p-4 md:p-5">
              <p className="t-num text-[30px] leading-none md:text-[40px]" style={{ color: C.accent }}>{s.n}</p>
              <p className="mt-3 text-[13px] leading-5 text-fg-soft">{s.t}</p>
              <p className="mt-2 text-[11px] text-fg-3">{s.src}</p>
            </div>
          </Reveal>
        ))}
      </div>
      <Reveal className="mt-12">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="font-serif text-2xl text-fg">Jak to vypadá dnes a jak s Došlapem</p>
          <div className="inline-flex rounded-full border border-white/12 bg-white/5 p-1" role="radiogroup" aria-label="Srovnání">
            {([["Dnes", false], ["S Došlapem", true]] as const).map(([l, v]) => (
              <button key={l} role="radio" aria-checked={after === v} onClick={() => setAfter(v)}
                className={`rounded-full px-4 py-2 text-[13px] font-extrabold transition ${after === v ? "bg-accent text-ink" : "text-fg-2 hover:text-fg"}`}>{l}</button>
            ))}
          </div>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-3 md:gap-4">
          {BEFORE_AFTER.map(({ who, icon: Icon, before, after: a }) => (
            <div key={who} className="card relative overflow-hidden p-5 transition-colors duration-500" style={{ borderColor: after ? `${C.accent}55` : undefined }}>
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl" style={{ background: after ? `${C.accent}1f` : "rgb(255 255 255 / .06)", color: after ? C.accent : C.fg2 }}>
                  <Icon className="size-5" aria-hidden />
                </span>
                <p className="font-bold text-fg">{who}</p>
                <span className="ml-auto" style={{ color: after ? C.ok : C.alert }}>{after ? <Check className="size-5" aria-label="s Došlapem" /> : <X className="size-5" aria-label="dnes" />}</span>
              </div>
              <p key={String(after)} className="mt-4 animate-[fadeIn_.45s_ease-out] text-[14px] leading-6 text-fg-soft">{after ? a : before}</p>
            </div>
          ))}
        </div>
      </Reveal>
    </Section>
  )
}

/* ------------------------------------------------------------------ the data flow (pinned scroll story) */
type FlowStep = { t: string; d: string; icon: typeof Footprints; col: string; x: number; y: number; label: string }
const FLOW_STEPS: FlowStep[] = [
  { t: "Hodinky měří", label: "Hodinky", icon: Watch, col: C.info, x: 70, y: 70,
    d: "Tep, HRV, spánek a běžecká dynamika přitečou z Garminu nebo Apple Health i s historií. Bez hodinek stačí krátký deník." },
  { t: "Srovnáváme srovnatelné", label: "Srovnatelné běhy", icon: Mountain, col: C.self, x: 318, y: 150,
    d: "Každý běh zařadíme podle povrchu, sklonu a tempa. Pomalý výklus tak nevypadá jako změna techniky a kopcovitý trail jako skok v zátěži." },
  { t: "Porovnání s vaší normou", label: "Vaše norma", icon: Activity, col: C.accent, x: 200, y: 262,
    d: "Mechanika, zátěž, příznaky a připravenost, vždy proti vaší vlastní normě z posledních týdnů, ne proti průměru ostatních." },
  { t: "Dnešní stav a limity", label: "Dnešní stav", icon: Gauge, col: C.ok, x: 82, y: 380,
    d: "Ráno víte, v jakém jste stavu a kolik toho dnes unesete: typ tréninku, kilometry, tep, tempo i převýšení." },
  { t: "Fyzioterapeut, když je potřeba", label: "Fyzioterapeut", icon: Stethoscope, col: C.watch, x: 318, y: 448,
    d: "Když se signály sčítají, Došlap doporučí konzultaci. Fyzioterapeut uvidí vaše data, až když o péči sami požádáte." },
]
// cubic segments between consecutive nodes (viewBox 400 × 520)
const FLOW_SEGS = [
  "M70 70 C 180 30, 320 60, 318 150",
  "M318 150 C 316 220, 240 215, 200 262",
  "M200 262 C 160 310, 60 300, 82 380",
  "M82 380 C 100 450, 250 480, 318 448",
]
function FlowDetail({ k }: { k: number }) {
  if (k === 0)
    return (
      <div className="grid grid-cols-2 gap-2">
        {[["Tep", "148", "tep/min", C.alert], ["HRV", "56", "ms", C.ok], ["Spánek", "7 h 12", "min", C.load], ["Kontakt se zemí", "248", "ms", C.self]].map(([t, v, u, c]) => (
          <div key={t} className="rounded-2xl border border-white/8 bg-bg/60 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[11px] font-bold text-fg-3"><span className="size-1.5 rounded-full" style={{ background: c }} />{t}</p>
            <p className="mt-1 text-[18px] font-extrabold text-fg">{v} <span className="text-[11px] font-bold text-fg-3">{u}</span></p>
          </div>
        ))}
      </div>
    )
  if (k === 1)
    return (
      <div className="rounded-2xl border border-white/8 bg-bg/60 p-3.5">
        <p className="text-[13px] font-extrabold text-fg">Lesní běh · 6,8 km</p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-bold">
          {[["trail", C.self], ["kopcovitý", C.watch], ["lehké tempo", C.ok], ["zóna 2", C.info]].map(([t, c]) => (
            <span key={t} className="rounded-full px-2 py-0.5" style={{ background: `${c}1f`, color: c }}>{t}</span>
          ))}
        </div>
        <p className="mt-2.5 text-[12px] leading-5 text-fg-2">porovnáno s 37 podobnými běhy, ne se všemi</p>
      </div>
    )
  if (k === 2)
    return (
      <div className="grid grid-cols-4 gap-1.5 text-center">
        {[["Mechanika", 22, C.self, "22"], ["Zátěž", 18, C.load, "18"], ["Příznaky", 4, C.watch, "0"], ["Připravenost", 89, C.ok, "89"]].map(([t, v, c, l]) => (
          <div key={t as string}><ScoreRing value={v as number} color={c as string} size={62} label={l as string} /><p className="t-axis mt-0.5 truncate">{t}</p></div>
        ))}
      </div>
    )
  if (k === 3)
    return (
      <div className="rounded-2xl border border-white/8 bg-bg/60 p-3.5">
        <div className="flex items-center justify-between">
          <span className="rounded-full px-2.5 py-1 text-[12px] font-extrabold" style={{ background: `${C.ok}1f`, color: C.ok }}>Stabilní</span>
          <span className="text-[11px] font-bold text-fg-3">doporučení na dnes</span>
        </div>
        <p className="mt-2 font-serif text-[22px] text-fg">Lehký běh 6–8 km</p>
        <p className="mt-1 text-[12px] text-fg-2">tep 132–149 · tempo 5:17–6:12 /km · klesání max 31 m</p>
      </div>
    )
  return (
    <div className="space-y-2 text-[12.5px]">
      <div className="w-[88%] rounded-2xl rounded-bl-md bg-white/8 px-3 py-2 text-fg-soft">Vidím skok v klesání. Tento týden zkraťte dlouhý běh a ve čtvrtek se podíváme na techniku.</div>
      <div className="flex items-center gap-2 rounded-xl border border-white/8 px-3 py-2 text-fg-2"><CalendarCheck className="size-4" style={{ color: C.accent }} aria-hidden />Analýza běhu · čt 17:30</div>
    </div>
  )
}
function DataFlow() {
  const [ref, p] = useScrollTrack<HTMLDivElement>()
  const segs = useRef<(SVGPathElement | null)[]>([])
  const n = FLOW_STEPS.length
  const q = p * (n - 1) * 1.08          // reach the last node a little before the pin ends
  const active = Math.min(n - 1, Math.round(Math.min(q, n - 1)))
  const step = FLOW_STEPS[active]
  // the packet travelling at the head of the line
  let packet: { x: number; y: number } | null = null
  const s = Math.min(n - 2, Math.floor(Math.min(q, n - 1.0001)))
  const el = segs.current[s]
  if (el && q < n - 1) {
    const L = el.getTotalLength()
    const pt = el.getPointAtLength(L * clamp01(q - s))
    packet = { x: pt.x, y: pt.y }
  }
  return (
    <section id="jak-to-funguje" className="relative scroll-mt-16" data-testid="data-flow">
      <div ref={ref} className="relative h-[460vh] md:h-[520vh]">
        <div className="sticky top-16 flex h-[calc(100svh-4rem)] items-center overflow-hidden">
          <div className="mx-auto grid w-full max-w-6xl items-center gap-6 px-5 md:grid-cols-[1fr_1.05fr] md:gap-10 md:px-8">
            <div className="order-2 md:order-1">
              <Kicker>Jak to funguje</Kicker>
              <p className="mt-2 hidden font-serif text-[22px] leading-tight text-fg-2 md:block">Od zápěstí k rozhodnutí</p>
              {/* mobile: a compact rail instead of the big diagram */}
              <ol className="mt-4 flex items-center md:hidden" aria-hidden>
                {FLOW_STEPS.map((f, k) => {
                  const Icon = f.icon
                  const on = k <= active
                  return (
                    <li key={f.t} className="flex flex-1 items-center last:flex-none">
                      <span className="grid size-10 shrink-0 place-items-center rounded-full border-2 transition-all duration-300"
                        style={{ borderColor: on ? f.col : "rgb(255 255 255 / .14)", background: k === active ? `${f.col}2a` : C.bg, color: on ? f.col : C.fg3, transform: k === active ? "scale(1.12)" : "none" }}>
                        <Icon className="size-[18px]" />
                      </span>
                      {k < n - 1 && <span className="mx-1 h-0.5 flex-1 rounded-full bg-white/10"><span className="block h-full rounded-full transition-[width] duration-150" style={{ width: `${clamp01(q - k) * 100}%`, background: `linear-gradient(90deg, ${f.col}, ${FLOW_STEPS[k + 1].col})` }} /></span>}
                    </li>
                  )
                })}
              </ol>
              <div key={active} className="mt-5 animate-[flowIn_.45s_cubic-bezier(.22,1,.36,1)_both] md:mt-6">
                <p className="t-label" style={{ color: step.col }}>{`Krok ${active + 1} z ${n}`}</p>
                <h2 className="mt-2 font-serif text-[30px] leading-[1.08] tracking-[-.02em] text-fg md:text-[44px]">{step.t}</h2>
                <p className="mt-3 max-w-lg text-[15px] leading-7 text-fg-soft md:text-[16px]">{step.d}</p>
                <div className="mt-5 max-w-md"><FlowDetail k={active} /></div>
              </div>
              <div className="mt-6 hidden items-center gap-2 md:flex" aria-hidden>
                {FLOW_STEPS.map((f, k) => (
                  <span key={f.t} className="h-1.5 rounded-full transition-all duration-300" style={{ width: k === active ? 34 : 10, background: k <= active ? f.col : "rgb(255 255 255 / .15)" }} />
                ))}
                <span className="ml-3 text-[12px] font-bold text-fg-3">scrollujte dál</span>
              </div>
            </div>

            <div className="order-1 hidden md:order-2 md:block">
              <div className="relative mx-auto aspect-[400/520] max-h-[calc(100svh-7rem)] w-full max-w-[460px]">
                <div className="absolute inset-[8%] rounded-full blur-3xl transition-colors duration-700" style={{ background: `${step.col}14` }} aria-hidden />
                <svg viewBox="0 0 400 520" className="absolute inset-0 h-full w-full" aria-hidden>
                  <defs>
                    <filter id="flowGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" /></filter>
                  </defs>
                  {FLOW_SEGS.map((d, k) => (
                    <g key={k}>
                      <path d={d} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth="2" strokeDasharray="3 7" />
                      <path ref={(e) => { segs.current[k] = e }} d={d} fill="none" stroke={FLOW_STEPS[k + 1].col} strokeWidth="3" strokeLinecap="round"
                        pathLength={1} strokeDasharray="1" strokeDashoffset={1 - clamp01(q - k)} />
                    </g>
                  ))}
                  {packet && (
                    <g>
                      <circle cx={packet.x} cy={packet.y} r="9" fill={FLOW_STEPS[Math.min(n - 1, s + 1)].col} opacity=".55" filter="url(#flowGlow)" />
                      <circle cx={packet.x} cy={packet.y} r="4.5" fill={C.fg} />
                    </g>
                  )}
                </svg>
                {FLOW_STEPS.map((f, k) => {
                  const Icon = f.icon
                  const reached = q >= k - 0.02
                  const on = k === active
                  return (
                    <div key={f.t} className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: `${(f.x / 400) * 100}%`, top: `${(f.y / 520) * 100}%` }}>
                      <span className="relative grid size-16 place-items-center rounded-full border-2 transition-all duration-500"
                        style={{ borderColor: reached ? f.col : "rgb(255 255 255 / .12)", background: on ? `${f.col}26` : C.bg, color: reached ? f.col : C.fg4,
                          transform: on ? "scale(1.18)" : "scale(1)", boxShadow: on ? `0 0 0 8px ${f.col}14, 0 0 40px ${f.col}40` : "none" }}>
                        {on && <span className="absolute inset-0 animate-ping rounded-full opacity-20" style={{ background: f.col }} />}
                        <Icon className="size-6" />
                      </span>
                      <span className={`mt-2 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12px] font-extrabold transition-colors ${on ? "bg-white/[.08] text-fg" : reached ? "text-fg-soft" : "text-fg-3"}`}>{f.label}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ interactive engine demo */
const PRESETS: { t: string; v: [number, number, number] }[] = [
  { t: "Pohodový týden", v: [10, 12, 4] },
  { t: "Nový objem", v: [14, 42, 10] },
  { t: "Únava v technice", v: [38, 14, 8] },
  { t: "Všechno naráz", v: [44, 46, 30] },
]
function DemoSlider({ label, hint, value, onChange, col }: { label: string; hint: string; value: number; onChange: (v: number) => void; col: string }) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-3">
        <span className="font-bold text-fg">{label}</span>
        <span className="t-num text-[15px]" style={{ color: value >= TH ? col : C.fg2 }}>{value} b.</span>
      </span>
      <span className="mt-0.5 block text-[12px] text-fg-3">{hint}</span>
      <input type="range" min={0} max={AX_MAX} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label}
        className="range mt-2 w-full" style={{ ["--fill" as string]: `${(value / AX_MAX) * 100}%`, ["--fill-color" as string]: col }} />
    </label>
  )
}
function EngineDemo({ onDemo, demoBusy }: { onDemo?: () => void; demoBusy: boolean }) {
  const [m, setM] = useState(14)
  const [z, setZ] = useState(42)
  const [s, setS] = useState(10)
  const q = quadOf(m, z)
  const score = scoreOf(m, z, s)
  const tier = tierOf(score, q)
  const pos = (v: number) => `${(Math.min(v, AX_MAX) / AX_MAX) * 100}%`
  const th = `${(TH / AX_MAX) * 100}%`
  const cells: { q: Q; style: CSSProperties }[] = [
    { q: "stable", style: { left: 0, bottom: 0, width: th, height: th } },
    { q: "silent", style: { left: th, bottom: 0, right: 0, height: th } },
    { q: "overreaching", style: { left: 0, top: 0, width: th, bottom: th } },
    { q: "critical", style: { left: th, top: 0, right: 0, bottom: th } },
  ]
  return (
    <Section id="vyzkousejte">
      <Reveal>
        <Kicker>Vyzkoušejte si to</Kicker>
        <H2>Posuňte jezdce a sledujte, jak se mění váš stav.</H2>
        <Lead>Každá osa sbírá body za odchylky od vaší normy. Nad hranicí 25 bodů je osa „horká“ a kombinace zátěže a mechaniky určí jeden ze čtyř stavů.</Lead>
      </Reveal>
      <Reveal className="mt-10">
        <div className="card grid gap-6 p-5 md:grid-cols-[1fr_1.1fr] md:gap-10 md:p-8">
          <div className="space-y-6">
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((pr) => {
                const on = pr.v[0] === m && pr.v[1] === z && pr.v[2] === s
                return (
                  <button key={pr.t} onClick={() => { setM(pr.v[0]); setZ(pr.v[1]); setS(pr.v[2]) }}
                    className={`rounded-full border px-3 py-1.5 text-[12.5px] font-bold transition ${on ? "border-accent bg-accent text-ink" : "border-white/15 text-fg-2 hover:border-white/30 hover:text-fg"}`}>{pr.t}</button>
                )
              })}
            </div>
            <DemoSlider label="Mechanika" hint="drift techniky proti vaší normě" value={m} onChange={setM} col={C.self} />
            <DemoSlider label="Zátěž" hint="skoky v objemu a intenzitě, regenerace" value={z} onChange={setZ} col={C.load} />
            <DemoSlider label="Příznaky" hint="bolest, ztuhlost a únava z deníku" value={s} onChange={setS} col={C.watch} />
            <p className="text-[12px] leading-5 text-fg-3">Zjednodušená ukázka. Skutečný výpočet pracuje s vaší osobní normou, desítkami signálů a hysterezí, aby stav zbytečně nepřeskakoval.</p>
          </div>
          <div>
            <div className="flex items-center gap-4">
              <ScoreRing value={score} color={tier.c} size={112} />
              <div className="min-w-0">
                <p className="t-label">Celkové skóre · {tier.t}</p>
                <p className="mt-1 font-serif text-[26px] leading-tight transition-colors duration-500" style={{ color: QCOL[q] }} data-testid="demo-quadrant">{QUAD[q].t}</p>
              </div>
            </div>
            <p key={q} className="mt-4 min-h-[3.5rem] animate-[fadeIn_.4s_ease-out] text-[14px] leading-6 text-fg-soft">{QRECO[q]}</p>
            <div className="mt-5 flex gap-2">
              <span className="t-axis flex w-4 items-center justify-center [writing-mode:vertical-rl] rotate-180">Zátěž →</span>
              <div className="flex-1">
                <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-white/10" aria-label="Kvadrant stavu" role="img">
                  {cells.map((c) => (
                    <div key={c.q} className="absolute flex items-start p-2 transition-all duration-500" style={{ ...c.style, background: q === c.q ? `${QCOL[c.q]}30` : `${QCOL[c.q]}0c` }}>
                      <span className="text-[10.5px] font-bold uppercase tracking-wider" style={{ color: q === c.q ? QCOL[c.q] : C.fg3 }}>{QUAD[c.q].t}</span>
                    </div>
                  ))}
                  <div className="absolute inset-y-0 border-l border-dashed border-white/25" style={{ left: th }} />
                  <div className="absolute inset-x-0 border-t border-dashed border-white/25" style={{ bottom: th }} />
                  <div className="absolute size-5 -translate-x-1/2 translate-y-1/2 rounded-full border-2 border-bg shadow-lg transition-all duration-500"
                    style={{ left: pos(m), bottom: pos(z), background: QCOL[q], boxShadow: `0 0 0 6px ${QCOL[q]}33` }} />
                </div>
                <p className="t-axis mt-1.5 text-right">Mechanika →</p>
              </div>
            </div>
          </div>
        </div>
      </Reveal>
      {onDemo && (
        <Reveal className="mt-4">
          <div className="card flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between md:p-6" style={{ backgroundImage: `radial-gradient(circle at 100% 0%, ${C.info}1a, transparent 18rem)` }}>
            <div className="flex items-start gap-3.5">
              <span className="grid size-11 shrink-0 place-items-center rounded-2xl" style={{ background: `${C.info}1c`, color: C.info }}><Smartphone className="size-5" aria-hidden /></span>
              <div>
                <p className="font-bold text-fg">Projděte si celou aplikaci na ukázkovém běžci</p>
                <p className="mt-1 text-[13.5px] leading-6 text-fg-soft">Půl roku běhů, deník, program od fyzioterapeuta i AI asistent. Bez registrace, jen pro čtení, s průvodcem.</p>
              </div>
            </div>
            <button onClick={onDemo} disabled={demoBusy} className="btn btn-outline shrink-0 px-5 py-3 text-[14px]" data-testid="demo-open">
              <Play className="size-4" aria-hidden />{demoBusy ? "Otevírám ukázku…" : "Otevřít ukázku"}
            </button>
          </div>
        </Reveal>
      )}
    </Section>
  )
}

/* ------------------------------------------------------------------ what you get: tabs tour in a phone */
type TabInfo = { t: string; title: string; body: string; points: string[]; viz: "rings" | "bars" | "journal" | "mech" | "load" | "care" | "ai" }
const TABS: TabInfo[] = [
  { t: "Dnes", title: "Ranní přehled za deset vteřin", viz: "rings", body: "Celkové skóre, připravenost, zátěž a mechanika na jednom místě s doporučením, co dnes běžet.",
    points: ["Kvadrant stavu a jeho vývoj za 6 měsíců", "Signály seřazené podle vlivu", "Denní check-in přímo z obrazovky"] },
  { t: "Trénink", title: "Kolik toho dnes unesete", viz: "bars", body: "Rozsah kilometrů, tepové zóny a tempo podle toho, co jste v posledních týdnech prokazatelně zvládli.",
    points: ["Dnešní kapacita objemu, intenzity a převýšení", "Čtyřtýdenní cyklus s odlehčovacím týdnem", "Kolo, plavání i posilování s konkrétní dávkou"] },
  { t: "Deník", title: "Vaše zkušenost jako nejcennější data", viz: "journal", body: "Po každém běhu krátce zapíšete, jak se běželo a jestli něco bolelo. Tyto zápisy aplikace používá nejvíc.",
    points: ["Běhy čekající na zápis", "Mapa těla s místy obtíží", "Souhrn posledních týdnů"] },
  { t: "Mechanika", title: "Technika proti vaší vlastní normě", viz: "mech", body: "Kontakt se zemí, kadence nebo vertikální poměr se štítkem v normě, na hraně nebo mimo normu.",
    points: ["Trend mechanické stability po dnech", "Běh rozdělený na srovnatelné úseky podle terénu", "Porovnání běhu s během před měsícem"] },
  { t: "Zátěž", title: "Skoky, které tělo nestihne vstřebat", viz: "load", body: "Objem, intenzita, stoupání a klesání, každý kanál proti vaší kapacitě, doplněné o spánek, HRV a klidový tep.",
    points: ["Týdenní kapacita po kanálech", "Co nejvíc tvoří dnešní skóre", "Regenerace proti vaší normě"] },
  { t: "Péče", title: "Fyzioterapeut na dosah", viz: "care", body: "Zprávy, schůzky a program cviků od fyzioterapeuta. Vaše data uvidí až ve chvíli, kdy potvrdíte zájem a on převezme váš případ.",
    points: ["Chat s fyzioterapeutem", "Rezervace vyšetření nebo analýzy běhu", "Program s rozpisem do týdne"] },
  { t: "AI asistent", title: "Odpovědi z vašich dat", viz: "ai", body: "Zeptejte se, proč vám aplikace dnes nedoporučuje intervaly. Asistent odpoví z vašich dat a z odborné literatury a uvede zdroj.",
    points: ["Otevře se z každé záložky", "Vysvětlí skóre, limity i doporučení", "Nenahrazuje fyzioterapeuta"] },
]
function TabViz({ kind }: { kind: TabInfo["viz"] }) {
  if (kind === "rings")
    return (
      <div className="flex items-center justify-center gap-3">
        {[[72, C.ok, "Připravenost"], [86, C.accent, "Skóre"], [61, C.watch, "Zátěž"]].map(([v, c, l]) => (
          <div key={l as string} className="text-center"><ScoreRing value={v as number} color={c as string} size={l === "Skóre" ? 96 : 64} /><p className="t-axis mt-1">{l}</p></div>
        ))}
      </div>
    )
  if (kind === "bars" || kind === "load") {
    const vals = kind === "bars" ? [38, 44, 49, 30, 42, 48, 55, 33] : [22, 26, 24, 31, 28, 46, 30, 27]
    const cap = kind === "bars" ? 0 : 36
    return (
      <div className="relative flex h-36 w-full items-end gap-2 px-1">
        {cap > 0 && <div className="absolute inset-x-0 border-t border-dashed" style={{ bottom: `${(cap / 56) * 100}%`, borderColor: `${C.watch}99` }}><span className="t-axis absolute -top-4 right-1">kapacita</span></div>}
        {vals.map((v, k) => (
          <div key={k} className="flex-1 origin-bottom animate-[barGrow_.7s_cubic-bezier(.22,1,.36,1)_both] rounded-t-md"
            style={{ height: `${(v / 56) * 100}%`, animationDelay: `${k * 60}ms`, background: kind === "bars" ? (k % 4 === 3 ? `${C.info}66` : C.info) : v > cap ? C.alert : C.load }} />
        ))}
      </div>
    )
  }
  if (kind === "journal")
    return (
      <div className="w-full space-y-2">
        {[["Út · 10 km klus", "Běželo se dobře", C.ok], ["Čt · intervaly", "Lýtko ztuhlé", C.watch], ["So · 18 km", "Čeká na zápis", C.fg3]].map(([a, b, c]) => (
          <div key={a} className="flex items-center justify-between gap-2 rounded-xl border border-white/8 px-3 py-2.5 text-[12.5px]">
            <span className="text-fg">{a}</span><span className="flex items-center gap-2 text-right text-fg-2"><span className="size-2 shrink-0 rounded-full" style={{ background: c }} />{b}</span>
          </div>
        ))}
      </div>
    )
  if (kind === "mech") {
    const pts = [8, 10, 9, 12, 11, 14, 18, 22, 27, 30, 26, 21]
    const d = pts.map((v, k) => `${k === 0 ? "M" : "L"}${(k / (pts.length - 1)) * 100},${100 - (v / 40) * 100}`).join(" ")
    return (
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-36 w-full" aria-hidden>
        <line x1="0" x2="100" y1={100 - (25 / 40) * 100} y2={100 - (25 / 40) * 100} stroke={C.self} strokeDasharray="2 2" strokeWidth=".6" />
        <path d={d} fill="none" stroke={C.self} strokeWidth="2" vectorEffect="non-scaling-stroke" className="animate-[drawLine_1.4s_ease-out_both]" pathLength={1} strokeDasharray="1" />
      </svg>
    )
  }
  if (kind === "ai")
    return (
      <div className="w-full space-y-2 text-[12.5px]">
        <div className="ml-auto w-[82%] rounded-2xl rounded-br-md bg-accent px-3 py-2 font-semibold text-ink">Proč dnes nemám dělat intervaly?</div>
        <div className="w-[92%] rounded-2xl rounded-bl-md bg-white/8 px-3 py-2 leading-5 text-fg-soft">
          <span className="mb-1 flex items-center gap-1.5 text-[10.5px] font-extrabold uppercase tracking-wider" style={{ color: C.accent }}><Bot className="size-3.5" aria-hidden />AI asistent</span>
          Před třemi dny jste běželi úsilí blízké závodu. Dejte si ještě den bez intenzity, lehký běh 6–8 km sedí. <b className="text-fg">[1]</b>
        </div>
        <p className="text-[11px] text-fg-3">[1] Seiler (2010) · nenahrazuje fyzioterapeuta</p>
      </div>
    )
  return (
    <div className="w-full space-y-2 text-[12.5px]">
      <div className="ml-auto w-4/5 rounded-2xl rounded-br-md bg-accent px-3 py-2 text-ink">Lýtko po intervalech ztuhlé, mám zítra běžet?</div>
      <div className="w-4/5 rounded-2xl rounded-bl-md bg-white/8 px-3 py-2 text-fg-soft">Vidím v datech skok v objemu. Dejte si zítra volno a zkuste cvik 3 z programu.</div>
      <div className="flex items-center gap-2 rounded-xl border border-white/8 px-3 py-2 text-fg-2"><CalendarCheck className="size-4" style={{ color: C.accent }} aria-hidden />Analýza běhu · čt 17:30</div>
    </div>
  )
}
function TabsTour() {
  const [i, setI] = useState(0)
  const [auto, setAuto] = useState(true)
  const [ref, seen] = useInView<HTMLDivElement>(0.3)
  useEffect(() => {
    if (!auto || !seen || reducedMotion()) return
    const t = setInterval(() => setI((x) => (x + 1) % TABS.length), 5500)
    return () => clearInterval(t)
  }, [auto, seen])
  const tab = TABS[i]
  return (
    <Section id="aplikace">
      <Reveal>
        <Kicker>Co v aplikaci dostanete</Kicker>
        <H2>Šest pohledů na jedno tělo a asistent, který je vysvětlí.</H2>
        <Lead>Každá záložka odpovídá na jednu otázku, kterou si běžec klade. Klepněte a projděte si je.</Lead>
      </Reveal>
      <div ref={ref} className="mt-8">
        <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-2 md:mx-0 md:flex-wrap md:px-0" role="tablist" aria-label="Záložky aplikace">
          {TABS.map((t, k) => (
            <button key={t.t} role="tab" aria-selected={k === i} onClick={() => { setI(k); setAuto(false) }}
              className={`relative shrink-0 overflow-hidden rounded-full border px-4 py-2 text-[13px] font-extrabold transition ${k === i ? "border-accent text-ink" : "border-white/12 text-fg-2 hover:text-fg"}`}
              style={{ background: k === i ? C.accent : "rgb(255 255 255 / .04)" }}>
              {t.t}
              {k === i && auto && seen && <span key={i} className="absolute inset-x-0 bottom-0 h-[3px] origin-left animate-[tabProgress_5.5s_linear_both] bg-ink/40" aria-hidden />}
            </button>
          ))}
        </div>
        <div className="mt-4 grid items-center gap-6 md:grid-cols-[1.1fr_1fr] md:gap-12">
          <div key={tab.t} className="animate-[fadeIn_.45s_ease-out]">
            <p className="font-serif text-[26px] leading-tight text-fg md:text-[34px]">{tab.title}</p>
            <p className="mt-3 text-[15px] leading-7 text-fg-soft">{tab.body}</p>
            <ul className="mt-5 space-y-2.5">
              {tab.points.map((pt) => (
                <li key={pt} className="flex gap-2.5 text-[14px] text-fg"><span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full" style={{ background: `${C.accent}22`, color: C.accent }}><Check className="size-3.5" aria-hidden /></span>{pt}</li>
              ))}
            </ul>
          </div>
          <div className="relative mx-auto w-full max-w-[330px]">
            <div className="absolute -inset-8 -z-10 rounded-full blur-3xl" style={{ background: `${C.accent}12` }} aria-hidden />
            <div className="rounded-[40px] border border-white/12 bg-gradient-to-b from-panel-2 to-panel p-2.5 shadow-2xl shadow-black/60">
              <div className="flex min-h-[360px] flex-col rounded-[32px] bg-bg p-4">
                <div className="flex items-center justify-between text-[11px] font-bold text-fg-3"><span className="text-fg-2">{tab.t}</span><span className="rounded-full bg-white/8 px-2 py-0.5">ukázka</span></div>
                <div key={tab.t} className="flex flex-1 animate-[flowIn_.45s_cubic-bezier(.22,1,.36,1)_both] items-center py-4"><TabViz kind={tab.viz} /></div>
                <div className="grid grid-cols-6 gap-1 border-t border-white/[.06] pt-2.5" aria-hidden>
                  {TABS.slice(0, 6).map((t, k) => (
                    <span key={t.t} className="flex justify-center"><span className="h-1.5 w-1.5 rounded-full" style={{ background: k === i ? C.accent : "rgb(255 255 255 / .18)" }} /></span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ connecting: devices → hub */
const DEVICES: { t: string; s: string; on: boolean; icon: typeof Footprints; x: number; y: number }[] = [
  { t: "Garmin", s: "propojení i historie", on: true, icon: Watch, x: 18, y: 18 },
  { t: "Apple Health", s: "běhy, spánek, tep", on: true, icon: Smartphone, x: 82, y: 18 },
  { t: "Deník", s: "i bez hodinek", on: true, icon: NotebookPen, x: 18, y: 82 },
  { t: "Suunto a Coros", s: "připravujeme", on: false, icon: Watch, x: 82, y: 82 },
]
const SYNC_PHASES: [string, number][] = [
  ["Připojuji Garmin…", 0.12],
  ["Načítám historii · 182 dní", 0.55],
  ["Skládám vaši osobní normu", 0.85],
  ["Hotovo · první stav je připravený", 1],
]
function Connect({ onRegister, onLogin }: { onRegister: () => void; onLogin: () => void }) {
  const [ref, seen] = useInView<HTMLDivElement>(0.35)
  const [phase, setPhase] = useState(0)
  useEffect(() => {
    if (!seen) return
    if (reducedMotion()) { setPhase(SYNC_PHASES.length - 1); return }
    const t = setInterval(() => setPhase((x) => (x + 1) % (SYNC_PHASES.length + 1)), 1700)
    return () => clearInterval(t)
  }, [seen])
  const ph = Math.min(phase, SYNC_PHASES.length - 1)
  const done = ph === SYNC_PHASES.length - 1
  return (
    <Section id="pripojeni">
      <Reveal>
        <Kicker>Připojení</Kicker>
        <H2>Funguje s tím, co už nosíte.</H2>
        <Lead>Připojte hodinky jednou a data budou přitékat sama. Načte se i historie, takže vaše norma se skládá od prvního dne. Bez hodinek začnete deníkem.</Lead>
      </Reveal>
      <div className="mt-10 grid items-center gap-10 md:grid-cols-[1.05fr_1fr] md:gap-12">
        <div ref={ref} className="relative mx-auto aspect-square w-full max-w-[460px]">
          <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden>
            <circle cx="50" cy="50" r="30" fill="none" stroke="rgb(255 255 255 / .07)" strokeWidth=".4" strokeDasharray="1.5 2.5" className="hub-orbit" />
            <circle cx="50" cy="50" r="42" fill="none" stroke="rgb(255 255 255 / .05)" strokeWidth=".3" />
            {DEVICES.map((dv, k) => {
              const d = `M ${dv.x} ${dv.y} L 50 50`
              return (
                <g key={dv.t}>
                  <path d={d} stroke={dv.on ? `${C.info}55` : "rgb(255 255 255 / .12)"} strokeWidth=".5" strokeDasharray={dv.on ? undefined : "1.2 1.6"} fill="none" />
                  {dv.on && seen && (
                    <circle r="1.3" fill={k === 0 ? C.accent : C.info}>
                      <animateMotion dur={`${2.2 + k * 0.35}s`} repeatCount="indefinite" path={d} begin={`${k * 0.5}s`} />
                    </circle>
                  )}
                </g>
              )
            })}
          </svg>
          <div className="absolute left-1/2 top-1/2 grid size-[30%] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border transition-shadow duration-700"
            style={{ borderColor: `${C.accent}66`, background: `radial-gradient(circle, ${C.accent}22, ${C.bg} 70%)`, boxShadow: done ? `0 0 60px ${C.accent}44` : `0 0 26px ${C.accent}22` }}>
            <Mark size={52} />
          </div>
          {DEVICES.map(({ t, s, on, icon: Icon, x, y }) => (
            <div key={t} className="absolute w-[34%] -translate-x-1/2 -translate-y-1/2" style={{ left: `${x}%`, top: `${y}%` }}>
              <div className={`rounded-2xl border p-2.5 text-center backdrop-blur ${on ? "border-white/12 bg-panel/90" : "border-dashed border-white/12 bg-bg/70"}`}>
                <Icon className="mx-auto size-5" style={{ color: on ? C.info : C.fg3 }} aria-hidden />
                <p className={`mt-1 text-[12.5px] font-extrabold ${on ? "text-fg" : "text-fg-2"}`}>{t}</p>
                <p className="text-[10.5px] text-fg-3">{s}</p>
              </div>
            </div>
          ))}
        </div>
        <div>
          <div className="card p-5" aria-live="polite">
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-[13px] font-extrabold text-fg">
                <span className={`size-2 rounded-full ${done ? "" : "animate-pulse"}`} style={{ background: done ? C.ok : C.info }} />{SYNC_PHASES[ph][0]}
              </p>
              <span className="text-[11px] font-bold text-fg-3">ukázka</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[.08]">
              <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${(phase >= SYNC_PHASES.length ? 0 : SYNC_PHASES[ph][1]) * 100}%`, background: `linear-gradient(90deg, ${C.info}, ${C.accent})` }} />
            </div>
          </div>
          <ol className="mt-6 space-y-3">
            {[
              ["Vytvořte si účet", "Jméno, e-mail a heslo. Zabere to minutu."],
              ["Připojte hodinky, nebo začněte deníkem", "Garmin i s historií, Apple Health exportem z iPhonu. Bez hodinek zapisujete běhy ručně."],
              ["Ráno se podívejte na svůj stav", "Průvodce vás provede aplikací a první stav uvidíte hned po načtení dat."],
            ].map(([t, d], k) => (
              <Reveal key={t} delay={k * 90}>
                <li className="flex gap-3.5">
                  <span className="grid size-9 shrink-0 place-items-center rounded-full text-[14px] font-extrabold" style={{ background: `${C.accent}1f`, color: C.accent }}>{k + 1}</span>
                  <div><p className="font-bold text-fg">{t}</p><p className="mt-0.5 text-[13.5px] leading-6 text-fg-soft">{d}</p></div>
                </li>
              </Reveal>
            ))}
          </ol>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button onClick={onRegister} className="btn btn-primary px-6 py-3 text-[14px]" data-testid="connect-register">Vytvořit účet<ArrowRight className="size-4" aria-hidden /></button>
            <button onClick={onLogin} className="text-[13px] font-bold text-fg-2 hover:text-accent">Už mám účet</button>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ physio continuity */
const FLOW: { t: string; d: string; icon: typeof Footprints }[] = [
  { t: "Prohlídka", d: "Fyzioterapeut vidí vaši historii, data z hodinek a zápisy z deníku ještě předtím, než přijdete.", icon: Stethoscope },
  { t: "Souhrn ze sezení", d: "Z přepisu prohlídky vznikne návrh souhrnu, který fyzioterapeut zkontroluje a upraví. Poslední slovo má vždy on.", icon: ClipboardList },
  { t: "Program v aplikaci", d: "Akční kroky a cviky s jednoduchým rozpisem do týdne. Odškrtáváte je a vidíte svůj progres.", icon: Dumbbell },
  { t: "Chat mezi návštěvami", d: "Když se něco změní, napíšete. Fyzioterapeut může plán upravit dřív než na další kontrole.", icon: MessageCircle },
  { t: "Další kontrola s kontextem", d: "Na příští návštěvě se nezačíná od nuly. Oba vidíte, co se mezitím dělo v datech i v programu.", icon: Sparkles },
]
function Continuity() {
  const [i, setI] = useState(0)
  return (
    <Section id="fyzio">
      <Reveal>
        <Kicker>Digitální kontinuita</Kicker>
        <H2>Z jednorázové prohlídky se stane průběžný vztah.</H2>
        <Lead>Dnes je klient po prohlídce často měsíc odkázaný sám na sebe a fyzioterapeut pracuje bez dat. Došlap drží spojení i mezi návštěvami, pokud o to stojíte.</Lead>
      </Reveal>
      <div className="mt-10 grid gap-4 md:grid-cols-[1fr_1.15fr] md:gap-8">
        <Reveal>
          <ol className="relative space-y-1">
            <span className="absolute bottom-6 left-[21px] top-6 w-px bg-white/10" aria-hidden />
            <span className="absolute left-[21px] top-6 w-px transition-all duration-500" style={{ height: `calc(${(i / (FLOW.length - 1)) * 100}% - ${(i / (FLOW.length - 1)) * 48}px)`, background: C.accent }} aria-hidden />
            {FLOW.map(({ t, icon: Icon }, k) => (
              <li key={t}>
                <button onClick={() => setI(k)} aria-current={k === i ? "step" : undefined}
                  className={`relative flex w-full items-center gap-3 rounded-2xl px-1 py-2.5 text-left transition ${k === i ? "text-fg" : "text-fg-2 hover:text-fg"}`}>
                  <span className="relative z-10 grid size-[42px] shrink-0 place-items-center rounded-full border transition-colors duration-300"
                    style={{ background: k <= i ? C.accent : C.panel, borderColor: k <= i ? C.accent : "rgb(255 255 255 / .14)", color: k <= i ? C.ink : C.fg2 }}>
                    <Icon className="size-[18px]" aria-hidden />
                  </span>
                  <span className="text-[15px] font-bold">{k + 1}. {t}</span>
                </button>
              </li>
            ))}
          </ol>
        </Reveal>
        <Reveal delay={120}>
          <div className="card flex h-full flex-col p-6 md:p-8">
            <p className="t-label">{`Krok ${i + 1} z ${FLOW.length}`}</p>
            <p key={i} className="mt-2 animate-[fadeIn_.4s_ease-out] font-serif text-[28px] leading-tight text-fg">{FLOW[i].t}</p>
            <p key={`d${i}`} className="mt-3 animate-[fadeIn_.5s_ease-out] text-[15px] leading-7 text-fg-soft">{FLOW[i].d}</p>
            <div className="mt-auto flex items-center gap-2 pt-6">
              <button onClick={() => setI((x) => Math.max(0, x - 1))} disabled={i === 0} className="btn btn-outline btn-sm">Zpět</button>
              <button onClick={() => setI((x) => (x + 1) % FLOW.length)} className="btn btn-primary btn-sm">{i === FLOW.length - 1 ? "Znovu od začátku" : "Další krok"}<ArrowRight className="size-4" aria-hidden /></button>
            </div>
          </div>
        </Reveal>
      </div>
      <Reveal className="mt-6">
        <p className="rounded-2xl border border-white/8 bg-white/3 px-4 py-3 text-[13px] leading-6 text-fg-2">
          Pro fyzioterapeuty připravujeme vlastní rozhraní: kalendář a rezervace, digitální registraci klientů, tvorbu programů, databázi cviků a přehled dat klientů. Je zatím ve vývoji.
        </p>
      </Reveal>
    </Section>
  )
}

/* ------------------------------------------------------------------ science + trust */
function Science() {
  const science: [string, string][] = [
    ["Osobní referenční rozsahy", "Hecksteden et al., 2017"],
    ["Nejmenší smysluplná změna", "Thornton et al., 2019"],
    ["Kapacita a skoky v objemu", "Nielsen et al., 2014"],
    ["Zátěž proti toleranci", "Bertelsen et al., 2017"],
    ["Hodnocení na skutečných událostech", "Carey et al., 2018"],
    ["Spojité modely místo prahů", "Bache-Mathiesen et al., 2021"],
  ]
  return (
    <Section id="veda">
      <div className="grid gap-10 md:grid-cols-[1.1fr_1fr] md:gap-12">
        <div>
          <Reveal>
            <Kicker>Věda místo dojmu</Kicker>
            <H2>Postaveno na výzkumu sportovní medicíny.</H2>
            <Lead>Každé pravidlo má v dokumentaci zdroj a sílu důkazů. Kde stavíme na vlastním předpokladu, říkáme to otevřeně a s daty ho budeme kalibrovat.</Lead>
          </Reveal>
          <Reveal delay={80}>
            <div className="mt-8 flex flex-wrap gap-2">
              {science.map(([t, a]) => (
                <span key={t} className="rounded-2xl border border-white/10 bg-white/4 px-3 py-2 text-[13px] text-fg">
                  {t} <span className="text-fg-3">· {a}</span>
                </span>
              ))}
            </div>
          </Reveal>
        </div>
        <div className="space-y-3 md:pt-10">
          {[
            [ShieldCheck, C.ok, "Vaše data vidíte vy", "Fyzioterapeut je uvidí až ve chvíli, kdy potvrdíte zájem o péči a on převezme váš případ."],
            [Gauge, C.info, "Vysvětlitelné skóre", "U každého čísla vidíte, co ho tvoří, jak silné jsou důkazy a kolik bodů to stojí."],
            [Stethoscope, C.watch, "Není to diagnóza", "Došlap není zdravotnický prostředek a nestanovuje diagnózu. Ukazuje změny proti vaší normě; rozhodnutí zůstává na vás a na odbornících."],
          ].map(([Icon, col, t, d], k) => {
            const I = Icon as typeof Footprints
            return (
              <Reveal key={t as string} delay={k * 90}>
                <div className="card flex gap-4 p-4">
                  <span className="grid size-11 shrink-0 place-items-center rounded-2xl" style={{ background: `${col as string}1c`, color: col as string }}><I className="size-5" aria-hidden /></span>
                  <div><p className="font-bold text-fg">{t as string}</p><p className="mt-1 text-[13.5px] leading-6 text-fg-soft">{d as string}</p></div>
                </div>
              </Reveal>
            )
          })}
        </div>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ FAQ */
const FAQ: [string, string][] = [
  ["Potřebuji chytré hodinky?", "Nepotřebujete. Nejvíc signálů přinesou hodinky s běžeckou dynamikou, ale Došlap umí pracovat i jen s deníkem běhů, bolestí a únavy."],
  ["Jak dlouho trvá, než mi Došlap porozumí?", "Když připojíte Garmin, načte se i vaše historie a osobní norma se skládá hned. Bez historie se zpřesňuje s každým dalším během a zápisem."],
  ["Nahrazuje Došlap fyzioterapeuta?", "Nenahrazuje. Pomáhá vám poznat, kdy je čas zpomalit nebo se poradit s odborníkem, a fyzioterapeutovi dává data a kontext pro jeho práci."],
  ["Co dělá AI asistent?", "Vysvětluje vaše skóre, limity a doporučení z čísel, která spočítala aplikace, a z odborné literatury, kterou cituje. Když by odpověď odporovala výpočtu, dostanete odpověď sestavenou podle pevných pravidel."],
  ["Kdo uvidí moje data?", "Vy. Fyzioterapeut je uvidí až ve chvíli, kdy potvrdíte zájem o péči a on převezme váš případ."],
  ["Pro koho je Došlap určený?", "Začínáme u běžců, protože mají bohatá data z hodinek a jasnou motivaci běhat dlouhodobě bez přerušení. Další sporty plánujeme."],
]
function Faq() {
  const [open, setOpen] = useState<number | null>(0)
  return (
    <Section id="faq" className="max-w-3xl">
      <Reveal>
        <Kicker>Časté otázky</Kicker>
        <H2>Na co se běžci ptají.</H2>
      </Reveal>
      <div className="mt-8 space-y-2">
        {FAQ.map(([qq, a], k) => {
          const on = open === k
          return (
            <Reveal key={qq} delay={k * 60}>
              <div className="card overflow-hidden">
                <button onClick={() => setOpen(on ? null : k)} aria-expanded={on} className="flex w-full items-center justify-between gap-4 p-4 text-left md:p-5">
                  <span className="font-bold text-fg">{qq}</span>
                  <ChevronDown className={`size-5 shrink-0 text-fg-2 transition-transform duration-300 ${on ? "rotate-180" : ""}`} aria-hidden />
                </button>
                <div className={`grid transition-all duration-300 ${on ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
                  <p className="overflow-hidden px-4 text-[14px] leading-6 text-fg-soft md:px-5"><span className="block pb-4 md:pb-5">{a}</span></p>
                </div>
              </div>
            </Reveal>
          )
        })}
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ page */
export function Landing({ onRegister, onLogin, onDemo, demoBusy = false, authSlot, returning = false, notice }: {
  onRegister: () => void; onLogin: () => void; onDemo?: () => void; demoBusy?: boolean; authSlot?: ReactNode; returning?: boolean; notice?: string | null
}) {
  return (
    <div className="landing relative" data-testid="landing">
      {/* ambient light that drifts with the scroll */}
      <div className="pointer-events-none fixed inset-0 -z-0 overflow-hidden" aria-hidden>
        <div className="landing-aurora absolute -left-[20%] top-[-10%] size-[70vmax] rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${C.accent}14, transparent 60%)` }} />
        <div className="landing-aurora-2 absolute -right-[25%] top-[30%] size-[70vmax] rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${C.info}12, transparent 60%)` }} />
      </div>
      <LandingNav onRegister={onRegister} onLogin={onLogin} returning={returning} />
      <div className="relative">
        <Hero onRegister={onRegister} onLogin={onLogin} onDemo={onDemo} demoBusy={demoBusy} notice={notice} />
        <Problem />
        <DataFlow />
        <TabsTour />
        <EngineDemo onDemo={onDemo} demoBusy={demoBusy} />
        <Connect onRegister={onRegister} onLogin={onLogin} />
        <Continuity />
        <Science />
        <Faq />

        <Section id="zacit">
          <Reveal>
            <div className="card relative grid items-center gap-8 overflow-hidden p-6 md:grid-cols-[1.1fr_1fr] md:gap-12 md:p-12" style={{ backgroundImage: `radial-gradient(circle at 15% 0%, ${C.accent}22, transparent 26rem)` }}>
              <div>
                <Kicker>Začněte</Kicker>
                <p className="mt-3 font-serif text-[32px] leading-[1.08] tracking-[-.02em] text-fg md:text-5xl">Začněte vidět, co se děje pod kilometry.</p>
                <p className="mt-4 max-w-xl text-[15px] leading-7 text-fg-soft">Registrace zabere minutu. Po ní vás průvodce provede připojením dat, profilem a ukázkou aplikace s vaším jménem.</p>
                <ul className="mt-6 space-y-2.5">
                  {["Funguje s hodinkami i bez nich", "Vaše data vidíte jen vy, dokud nepožádáte o péči", "Průvodce vás provede prvními kroky"].map((t) => (
                    <li key={t} className="flex gap-2.5 text-[14px] text-fg"><Check className="mt-0.5 size-4 shrink-0" style={{ color: C.accent }} aria-hidden />{t}</li>
                  ))}
                </ul>
              </div>
              <div>{authSlot ?? <button onClick={onRegister} className="btn btn-primary px-8 py-4 text-[15px]" data-testid="landing-cta">Vytvořit účet<ArrowRight className="size-4" aria-hidden /></button>}</div>
            </div>
          </Reveal>
        </Section>

        <footer className="mx-auto max-w-6xl px-5 pb-12 pt-4 text-[11.5px] leading-5 text-fg-3 md:px-8">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-t border-white/[.06] pt-6">
            <span className="flex items-center gap-2 text-base font-extrabold tracking-[-.04em] text-fg"><Mark size={26} /><Wordmark /></span>
            <span className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] font-bold">
              {NAV.map(([id, t]) => <a key={id} href={`#${id}`} onClick={(e) => { e.preventDefault(); goTo(id) }} className="text-fg-2 hover:text-fg">{t}</a>)}
              <button type="button" onClick={onLogin} className="text-accent">Přihlásit se</button>
            </span>
          </div>
          <p className="t-label mb-2">Zdroje čísel</p>
          <ul className="space-y-1">
            <li>van Gent, R. N., Siem, D., van Middelkoop, M., van Os, A. G., Bierma-Zeinstra, S. M. A., &amp; Koes, B. W. (2007). Incidence and determinants of lower extremity running injuries in long distance runners: A systematic review. <i>British Journal of Sports Medicine, 41</i>(8), 469–480.</li>
            <li>Hospodářské noviny. (b.r.). Česko zaostává v dostupnosti fyzioterapie za vyspělou Evropou. Data Evropské komise.</li>
            <li>Novák, T. (2021, 14. prosince). Ordinace fyzioterapeutů jsou plné, čekací lhůta je i čtvrt roku. <i>Hrot24.cz</i>. Data ÚZIS za rok 2019.</li>
          </ul>
          <p className="mt-4">Hodnoty v hodinkách, v telefonu a v interaktivních ukázkách jsou ilustrační. © Došlap</p>
        </footer>
      </div>
    </div>
  )
}
