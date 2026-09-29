// Landing page shown below the sign-up form on /auth ("Co Došlap umí").
// Sales copy for prospective runners, built from Documentation/DOSLAP_co_delame.md.
// Every number shown as a fact carries its source in the footer; illustrative
// values (hero phone, engine demo) are labelled as a demo. No medical claims:
// Došlap shows changes against the runner's own norm, it does not diagnose
// (MDR note in the project, enforced by backend/tests/test_wording.py).
import { useEffect, useRef, useState, type ReactNode } from "react"
import {
  Activity, ArrowRight, BookOpen, CalendarCheck, Check, ChevronDown, ClipboardList, Dumbbell,
  Footprints, MessageCircle, NotebookPen, ShieldCheck, Smartphone, Sparkles, Stethoscope, Watch, X,
} from "lucide-react"
import { C } from "@/tokens"
import { QUAD } from "@/lib"

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

/** Counts up to `to` once the number scrolls into view. */
function CountUp({ to, decimals = 0, suffix = "" }: { to: number; decimals?: number; suffix?: string }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.5)
  const [v, setV] = useState(0)
  useEffect(() => {
    if (!seen) return
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    if (reduce) { setV(to); return }
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
  return <section id={id} className={`mx-auto w-full max-w-6xl scroll-mt-6 px-5 py-16 md:px-8 md:py-24 ${className}`}>{children}</section>
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
const tierOf = (score: number) => (100 - score >= 70 ? { t: "Jednat", c: C.alert } : 100 - score >= 40 ? { t: "Sledovat", c: C.watch } : { t: "V pořádku", c: C.ok })

function ScoreRing({ value, color, size = 132 }: { value: number; color: string; size?: number }) {
  const r = 44
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden className="shrink-0">
      <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="8" />
      <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={c * (1 - value / 100)} transform="rotate(-90 50 50)" style={{ transition: "stroke-dashoffset .6s cubic-bezier(.22,1,.36,1), stroke .4s" }} />
      <text x="50" y="58" textAnchor="middle" fontSize="28" fontWeight="800" fill={C.fg} fontFamily="Manrope, Arial, sans-serif">{value}</text>
    </svg>
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
    if (paused) return
    const t = setInterval(() => setI((x) => (x + 1) % PHONE_STATES.length), 3200)
    return () => clearInterval(t)
  }, [paused])
  const st = PHONE_STATES[i]
  const col = QCOL[st.q]
  return (
    <div className="relative mx-auto w-full max-w-[330px]" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="absolute -inset-10 -z-10 rounded-full blur-3xl transition-colors duration-700" style={{ background: `${col}24` }} aria-hidden />
      <div className="rounded-[36px] border border-white/12 bg-panel p-3 shadow-2xl shadow-black/50">
        <div className="rounded-[28px] bg-bg p-4">
          <div className="flex items-center justify-between text-[11px] text-fg-3">
            <span className="font-bold text-fg-2">Dnes</span>
            <span className="rounded-full bg-white/8 px-2 py-0.5">ukázková data</span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <ScoreRing value={st.score} color={col} size={96} />
            <div className="min-w-0">
              <p className="t-label">Stav</p>
              <p className="mt-1 font-serif text-xl leading-tight transition-colors duration-500" style={{ color: col }}>{QUAD[st.q].t}</p>
            </div>
          </div>
          <p key={st.q} className="mt-3 animate-[fadeIn_.5s_ease-out] rounded-2xl bg-white/5 p-3 text-[12.5px] leading-5 text-fg-soft">{QRECO[st.q]}</p>
          <div className="mt-3 space-y-1.5">
            {st.drivers.map(([k, v]) => (
              <div key={st.q + k} className="flex animate-[fadeIn_.5s_ease-out] items-center justify-between rounded-xl border border-white/6 px-3 py-2 text-[12px]">
                <span className="text-fg-2">{k}</span>
                <b className="text-fg">{v}</b>
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

/* ------------------------------------------------------------------ three axes */
const AXES: { key: string; t: string; icon: typeof Footprints; col: string; short: string; items: string[] }[] = [
  { key: "mech", t: "Mechanika", icon: Footprints, col: C.self, short: "Mění se vaše technika?",
    items: ["Vertikální poměr, kontakt se zemí, kadence a vertikální oscilace", "Srovnání ve stejném tempu a terénu, ne napříč všemi běhy", "Drift techniky bývá časný znak únavy, který ještě necítíte"] },
  { key: "load", t: "Zátěž", icon: Activity, col: C.load, short: "Unesete to, co běháte?",
    items: ["Objem, intenzita, stoupání a klesání proti vaší kapacitě", "Prudké skoky oproti posledním týdnům", "Spánek, HRV a klidový tep jako ranní regenerace"] },
  { key: "symp", t: "Symptomy", icon: NotebookPen, col: C.watch, short: "Co říká vaše tělo?",
    items: ["Denní check-in za pár vteřin: bolest, ztuhlost, únava", "Bolest označená přímo na mapě těla", "Opakující se obtíže mají větší váhu než jednorázové"] },
]
function Axes() {
  const [open, setOpen] = useState("mech")
  return (
    <Section id="jak-to-funguje">
      <Reveal>
        <Kicker>Jak to funguje</Kicker>
        <H2>Tři osy, jeden srozumitelný stav. Porovnáváme vás s vámi, ne s průměrem.</H2>
        <Lead>Došlap si z vašich běhů složí osobní normu. Každý den pak sleduje, jak daleko se od ní vzdalujete ve třech osách, a ukáže nejen výsledek, ale i to, co ho tvoří.</Lead>
      </Reveal>
      <div className="mt-10 grid gap-3 md:grid-cols-3 md:gap-4">
        {AXES.map(({ key, t, icon: Icon, col, short, items }, k) => {
          const on = open === key
          return (
            <Reveal key={key} delay={k * 100}>
              <button onClick={() => setOpen(key)} aria-expanded={on}
                className="card h-full w-full p-5 text-left transition-all duration-300"
                style={{ borderColor: on ? `${col}88` : undefined, background: on ? `linear-gradient(160deg, ${col}1c, rgb(255 255 255 / .015))` : undefined }}>
                <span className="grid size-11 place-items-center rounded-2xl" style={{ background: `${col}22`, color: col }}><Icon className="size-5" aria-hidden /></span>
                <p className="mt-4 font-serif text-2xl text-fg">{t}</p>
                <p className="mt-1 text-[14px] text-fg-2">{short}</p>
                <ul className={`grid transition-all duration-500 ${on ? "mt-4 grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0 md:mt-4 md:grid-rows-[1fr] md:opacity-60"}`}>
                  <div className="space-y-2 overflow-hidden">
                    {items.map((it) => (
                      <li key={it} className="flex gap-2 text-[13.5px] leading-5 text-fg-soft">
                        <Check className="mt-0.5 size-4 shrink-0" style={{ color: col }} aria-hidden />{it}
                      </li>
                    ))}
                  </div>
                </ul>
              </button>
            </Reveal>
          )
        })}
      </div>
    </Section>
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
function EngineDemo() {
  const [m, setM] = useState(14)
  const [z, setZ] = useState(42)
  const [s, setS] = useState(10)
  const q = quadOf(m, z)
  const score = scoreOf(m, z, s)
  const tier = tierOf(score)
  const pos = (v: number) => `${(Math.min(v, AX_MAX) / AX_MAX) * 100}%`
  const th = `${(TH / AX_MAX) * 100}%`
  const cells: { q: Q; style: React.CSSProperties }[] = [
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
              {PRESETS.map((p) => {
                const on = p.v[0] === m && p.v[1] === z && p.v[2] === s
                return (
                  <button key={p.t} onClick={() => { setM(p.v[0]); setZ(p.v[1]); setS(p.v[2]) }}
                    className={`rounded-full border px-3 py-1.5 text-[12.5px] font-bold transition ${on ? "border-accent bg-accent text-ink" : "border-white/15 text-fg-2 hover:border-white/30 hover:text-fg"}`}>{p.t}</button>
                )
              })}
            </div>
            <DemoSlider label="Mechanika" hint="drift techniky proti vaší normě" value={m} onChange={setM} col={C.self} />
            <DemoSlider label="Zátěž" hint="skoky v objemu a intenzitě, regenerace" value={z} onChange={setZ} col={C.load} />
            <DemoSlider label="Symptomy" hint="bolest, ztuhlost a únava z deníku" value={s} onChange={setS} col={C.watch} />
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
    </Section>
  )
}

/* ------------------------------------------------------------------ tabs tour */
type TabInfo = { t: string; title: string; body: string; points: string[]; viz: "rings" | "bars" | "journal" | "mech" | "load" | "care" }
const TABS: TabInfo[] = [
  { t: "Dnes", title: "Ranní přehled za deset vteřin", viz: "rings", body: "Celkové skóre, připravenost, zátěž a mechanika na jednom místě s doporučením, co dnes běžet.",
    points: ["Kvadrant stavu a jeho vývoj za 6 měsíců", "Signály seřazené podle vlivu", "Denní check-in přímo z obrazovky"] },
  { t: "Trénink", title: "Kolik toho dnes unesete", viz: "bars", body: "Rozsah kilometrů, tepové zóny a tempo podle toho, co jste v posledních týdnech prokazatelně zvládli.",
    points: ["Dnešní kapacita objemu, intenzity a převýšení", "Čtyřtýdenní cyklus s odlehčovacím týdnem", "Kolo, plavání i posilování s konkrétní dávkou"] },
  { t: "Deník", title: "Vaše zkušenost jako nejcennější data", viz: "journal", body: "Po každém běhu krátce zapíšete, jak se běželo a jestli něco bolelo. Tyto zápisy engine používá nejvíc.",
    points: ["Běhy čekající na zápis", "Mapa těla s místy obtíží", "Souhrn posledních týdnů"] },
  { t: "Pohyb", title: "Technika proti vaší vlastní normě", viz: "mech", body: "Kontakt se zemí, kadence nebo vertikální poměr se štítkem v normě, na hraně nebo mimo normu.",
    points: ["Trend mechanické stability po dnech", "Srovnání na rovině, v kopcích a v tempu", "Porovnání běhu s během před měsícem"] },
  { t: "Zátěž", title: "Skoky, které tělo nestihne vstřebat", viz: "load", body: "Objem, intenzita, stoupání a klesání, každý kanál proti vaší kapacitě, doplněné o spánek, HRV a klidový tep.",
    points: ["Týdenní kapacita po kanálech", "Co nejvíc tvoří dnešní skóre", "Regenerace proti vaší normě"] },
  { t: "Péče", title: "Fyzioterapeut na dosah", viz: "care", body: "Zprávy, schůzky a program cviků od fyzioterapeuta. Vaše data uvidí až ve chvíli, kdy potvrdíte zájem a on převezme váš případ.",
    points: ["Chat s fyzioterapeutem", "Rezervace vyšetření nebo analýzy běhu", "Program s rozpisem do týdne"] },
]
function TabViz({ kind }: { kind: TabInfo["viz"] }) {
  if (kind === "rings")
    return (
      <div className="flex items-center justify-center gap-4">
        {[[72, C.ok, "Připravenost"], [86, C.accent, "Skóre"], [61, C.watch, "Zátěž"]].map(([v, c, l]) => (
          <div key={l as string} className="text-center"><ScoreRing value={v as number} color={c as string} size={l === "Skóre" ? 104 : 72} /><p className="t-axis mt-1">{l}</p></div>
        ))}
      </div>
    )
  if (kind === "bars" || kind === "load") {
    const vals = kind === "bars" ? [38, 44, 49, 30, 42, 48, 55, 33] : [22, 26, 24, 31, 28, 46, 30, 27]
    const cap = kind === "bars" ? 0 : 36
    return (
      <div className="relative flex h-36 items-end gap-2 px-2">
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
      <div className="space-y-2">
        {[["Út · 10 km klus", "Běželo se dobře", C.ok], ["Čt · intervaly", "Lýtko ztuhlé", C.watch], ["So · 18 km", "Čeká na zápis", C.fg3]].map(([a, b, c]) => (
          <div key={a} className="flex items-center justify-between rounded-xl border border-white/8 px-3 py-2.5 text-[13px]">
            <span className="text-fg">{a}</span><span className="flex items-center gap-2 text-fg-2"><span className="size-2 rounded-full" style={{ background: c }} />{b}</span>
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
  return (
    <div className="space-y-2 text-[13px]">
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
    if (!auto || !seen) return
    const t = setInterval(() => setI((x) => (x + 1) % TABS.length), 5500)
    return () => clearInterval(t)
  }, [auto, seen])
  const tab = TABS[i]
  return (
    <Section id="aplikace">
      <Reveal>
        <Kicker>Co najdete v aplikaci</Kicker>
        <H2>Šest pohledů na jedno tělo.</H2>
        <Lead>Každá záložka odpovídá na jednu otázku, kterou si běžec klade. Klepněte a projděte si je.</Lead>
      </Reveal>
      <div ref={ref} className="mt-8">
        <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-2 md:mx-0 md:px-0" role="tablist" aria-label="Záložky aplikace">
          {TABS.map((t, k) => (
            <button key={t.t} role="tab" aria-selected={k === i} onClick={() => { setI(k); setAuto(false) }}
              className={`relative shrink-0 overflow-hidden rounded-full border px-4 py-2 text-[13px] font-extrabold transition ${k === i ? "border-accent text-ink" : "border-white/12 text-fg-2 hover:text-fg"}`}
              style={{ background: k === i ? C.accent : "rgb(255 255 255 / .04)" }}>
              {t.t}
              {k === i && auto && seen && <span key={i} className="absolute inset-x-0 bottom-0 h-[3px] origin-left animate-[tabProgress_5.5s_linear_both] bg-ink/40" aria-hidden />}
            </button>
          ))}
        </div>
        <div key={tab.t} className="card mt-4 grid animate-[fadeIn_.45s_ease-out] gap-6 p-5 md:grid-cols-2 md:gap-10 md:p-8">
          <div>
            <p className="font-serif text-[26px] leading-tight text-fg md:text-3xl">{tab.title}</p>
            <p className="mt-3 text-[14.5px] leading-6 text-fg-soft">{tab.body}</p>
            <ul className="mt-5 space-y-2.5">
              {tab.points.map((p) => (
                <li key={p} className="flex gap-2.5 text-[14px] text-fg"><span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full" style={{ background: `${C.accent}22`, color: C.accent }}><Check className="size-3.5" aria-hidden /></span>{p}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-white/8 bg-bg/60 p-4 md:p-6"><TabViz kind={tab.viz} /></div>
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
            <p className="t-label">Krok {i + 1} z {FLOW.length}</p>
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

/* ------------------------------------------------------------------ data sources + trust */
function DataAndTrust() {
  const sources: { t: string; d: string; icon: typeof Footprints }[] = [
    { t: "Garmin", d: "Přihlášení nebo export z Garmin Connect. Načte i historii, takže norma se skládá od prvního dne.", icon: Watch },
    { t: "Apple Health", d: "Běhy, spánek a tepová data z iPhonu a Apple Watch.", icon: Smartphone },
    { t: "Bez hodinek", d: "Strukturovaný deník běhů, bolestí a únavy stačí k základnímu vyhodnocení.", icon: BookOpen },
  ]
  const science: [string, string][] = [
    ["Osobní referenční rozsahy", "Hecksteden et al., 2017"],
    ["Nejmenší smysluplná změna", "Thornton et al., 2019"],
    ["Kapacita a skoky v objemu", "Nielsen et al., 2014"],
    ["Zátěž proti toleranci", "Bertelsen et al., 2017"],
    ["Hodnocení na skutečných událostech", "Carey et al., 2018"],
    ["Spojité modely místo prahů", "Bache-Mathiesen et al., 2021"],
  ]
  return (
    <Section id="data">
      <div className="grid gap-12 md:grid-cols-2 md:gap-10">
        <div>
          <Reveal>
            <Kicker>Data</Kicker>
            <H2>Funguje s tím, co už nosíte.</H2>
          </Reveal>
          <div className="mt-8 space-y-3">
            {sources.map(({ t, d, icon: Icon }, k) => (
              <Reveal key={t} delay={k * 90}>
                <div className="card flex gap-4 p-4">
                  <span className="grid size-11 shrink-0 place-items-center rounded-2xl" style={{ background: `${C.info}1c`, color: C.info }}><Icon className="size-5" aria-hidden /></span>
                  <div><p className="font-bold text-fg">{t}</p><p className="mt-1 text-[13.5px] leading-5 text-fg-soft">{d}</p></div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
        <div>
          <Reveal>
            <Kicker>Věda místo dojmu</Kicker>
            <H2>Postaveno na výzkumu sportovní medicíny.</H2>
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
          <Reveal delay={160}>
            <div className="mt-5 flex gap-3 rounded-2xl border p-4" style={{ borderColor: `${C.ok}40`, background: `${C.ok}0d` }}>
              <ShieldCheck className="mt-0.5 size-5 shrink-0" style={{ color: C.ok }} aria-hidden />
              <p className="text-[13.5px] leading-6 text-fg-soft">
                Došlap není zdravotnický prostředek a nestanovuje diagnózu. Ukazuje změny proti vaší vlastní normě a vysvětluje, co je tvoří. Rozhodnutí zůstává na vás a na odbornících.
              </p>
            </div>
          </Reveal>
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
        {FAQ.map(([q, a], k) => {
          const on = open === k
          return (
            <Reveal key={q} delay={k * 60}>
              <div className="card overflow-hidden">
                <button onClick={() => setOpen(on ? null : k)} aria-expanded={on} className="flex w-full items-center justify-between gap-4 p-4 text-left md:p-5">
                  <span className="font-bold text-fg">{q}</span>
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
export function scrollToLanding() {
  document.getElementById("co-doslap-umi")?.scrollIntoView({ behavior: "smooth", block: "start" })
}

export function Landing({ onCta }: { onCta: () => void }) {
  // Floating "Vytvořit účet" pill once the visitor has scrolled past the form.
  const [pill, setPill] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const on = () => {
      const end = endRef.current?.getBoundingClientRect().top ?? Infinity
      setPill(window.scrollY > window.innerHeight * 0.9 && end > window.innerHeight * 0.85)
    }
    on()
    window.addEventListener("scroll", on, { passive: true })
    return () => window.removeEventListener("scroll", on)
  }, [])

  return (
    <div className="relative border-t border-white/8" data-testid="landing">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[40rem]" style={{ background: `radial-gradient(circle at 20% 0%, ${C.accent}14, transparent 30rem), radial-gradient(circle at 90% 30%, ${C.info}12, transparent 26rem)` }} aria-hidden />

      <Section id="co-doslap-umi" className="relative">
        <div className="grid items-center gap-12 md:grid-cols-[1.15fr_1fr]">
          <Reveal>
            <Kicker>Co Došlap umí</Kicker>
            <h2 className="mt-4 font-serif text-[38px] leading-[1.02] tracking-[-.025em] text-fg md:text-[64px]">
              Víte, kolik naběháte. Došlap vám ukáže, <span style={{ color: C.accent }}>kolik toho tělo unese.</span>
            </h2>
            <p className="mt-6 max-w-xl text-[16px] leading-7 text-fg-soft">
              Došlap propojuje běžce a fyzioterapeuty. Každý den skládá data z hodinek a krátký deník do jednoho srozumitelného stavu. Když je čas zpomalit nebo zajít za odborníkem, řekne vám to a vysvětlí proč.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button onClick={onCta} className="btn btn-primary px-6 py-3.5 text-[14px]">Vytvořit účet<ArrowRight className="size-4" aria-hidden /></button>
              <a href="#vyzkousejte" className="btn btn-outline px-6 py-3.5 text-[14px]">Vyzkoušet ukázku</a>
            </div>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-fg-2">
              {["Osobní norma místo průměru", "Vysvětlitelné skóre", "Napojení na fyzioterapeuta"].map((t) => (
                <span key={t} className="flex items-center gap-2"><Check className="size-4" style={{ color: C.accent }} aria-hidden />{t}</span>
              ))}
            </div>
          </Reveal>
          <Reveal delay={150}><HeroPhone /></Reveal>
        </div>
      </Section>

      <Problem />
      <Axes />
      <EngineDemo />
      <TabsTour />
      <Continuity />
      <DataAndTrust />
      <Faq />

      <Section>
        <div ref={endRef} />
        <Reveal>
          <div className="card relative overflow-hidden p-8 text-center md:p-14" style={{ backgroundImage: `radial-gradient(circle at 50% 0%, ${C.accent}26, transparent 24rem)` }}>
            <p className="mx-auto max-w-2xl font-serif text-[32px] leading-[1.08] tracking-[-.02em] text-fg md:text-5xl">Začněte vidět, co se děje pod kilometry.</p>
            <p className="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-fg-soft">Registrace zabere minutu. Po ní vás průvodce provede připojením dat, profilem a ukázkou aplikace s vaším jménem.</p>
            <button onClick={onCta} className="btn btn-primary mt-8 px-8 py-4 text-[15px]" data-testid="landing-cta">Vytvořit účet<ArrowRight className="size-4" aria-hidden /></button>
          </div>
        </Reveal>
      </Section>

      <footer className="mx-auto max-w-6xl px-5 pb-28 pt-4 text-[11.5px] leading-5 text-fg-3 md:px-8 md:pb-12">
        <p className="t-label mb-2">Zdroje čísel</p>
        <ul className="space-y-1">
          <li>van Gent, R. N., Siem, D., van Middelkoop, M., van Os, A. G., Bierma-Zeinstra, S. M. A., &amp; Koes, B. W. (2007). Incidence and determinants of lower extremity running injuries in long distance runners: A systematic review. <i>British Journal of Sports Medicine, 41</i>(8), 469–480.</li>
          <li>Hospodářské noviny. (b.r.). Česko zaostává v dostupnosti fyzioterapie za vyspělou Evropou. Data Evropské komise.</li>
          <li>Novák, T. (2021, 14. prosince). Ordinace fyzioterapeutů jsou plné, čekací lhůta je i čtvrt roku. <i>Hrot24.cz</i>. Data ÚZIS za rok 2019.</li>
        </ul>
        <p className="mt-4">Hodnoty v telefonu a v interaktivní ukázce jsou ilustrační. © Došlap</p>
      </footer>

      <div className={`fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 transition-all duration-300 md:bottom-6 md:justify-end md:px-8 ${pill ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-6 opacity-0"}`}>
        <button onClick={onCta} tabIndex={pill ? 0 : -1} className="btn btn-primary px-6 py-3 text-[14px] shadow-xl shadow-black/40" data-testid="landing-pill">
          Vytvořit účet<ArrowRight className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  )
}
