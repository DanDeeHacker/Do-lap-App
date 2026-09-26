// Shared presentational primitives (redesign v2 — DOSLAP_REDESIGN_BRIEF.md §4).
// Every colour comes from the design tokens (index.css @theme / tokens.ts).
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { ChevronDown, CircleMinus, Info, LoaderCircle, TriangleAlert, type LucideIcon } from "lucide-react"
import { C } from "@/tokens"

export type Tone = "ok" | "watch" | "alert" | "muted" | "accent" | "info" | "load" | "self"
const TONE_COL: Record<Tone, string> = { ok: C.ok, watch: C.watch, alert: C.alert, muted: C.fg3, accent: C.accent, info: C.info, load: C.load, self: C.self }
export const toneCol = (t: Tone) => TONE_COL[t] || C.fg3

export function Label({ children }: { children: ReactNode }) {
  return <p className="t-label">{children}</p>
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`group card p-4 transition duration-200 md:p-5 ${className}`}>{children}</section>
}

/* ---------- Button ---------- */
type BtnVariant = "primary" | "secondary" | "outline" | "danger"
// full class names (Tailwind only generates utilities it can find verbatim in source)
const BTN: Record<BtnVariant, string> = { primary: "btn btn-primary", secondary: "btn btn-secondary", outline: "btn btn-outline", danger: "btn btn-danger" }
export function Button({
  children, variant = "primary", size = "md", busy = false, icon: Icon, className = "", type = "button", ...rest
}: {
  children?: ReactNode; variant?: BtnVariant; size?: "md" | "sm"; busy?: boolean; icon?: LucideIcon; className?: string
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  return (
    <button type={type} className={`${BTN[variant]} ${size === "sm" ? "btn-sm" : ""} ${className}`} aria-busy={busy || undefined} {...rest}>
      {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : Icon ? <Icon className="size-4" aria-hidden /> : null}
      {children}
    </button>
  )
}

/* ---------- InfoDot ---------- */
// Small "?" affordance: shows what a metric measures + how to read it against
// your own baseline. Works on desktop (hover) and phones (tap toggles; tapping
// elsewhere closes). The bubble is portaled to <body> and fixed-positioned next
// to the icon, clamped to the viewport, so it's never clipped by a card's
// overflow/transform and never dumped off-screen at the bottom.
export function InfoDot({ text, label, className = "" }: { text: ReactNode; label?: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number; width: number; below: boolean } | null>(null)

  const place = () => {
    const el = btnRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const width = Math.min(280, window.innerWidth - 24)
    const left = Math.max(12, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 12))
    const below = r.top < 210 // too close to the top → drop the bubble below the icon
    setPos({ left, top: below ? r.bottom + 10 : r.top - 10, width, below })
  }
  const show = () => { place(); setOpen(true) }

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node
      if (!btnRef.current?.contains(t) && !tipRef.current?.contains(t)) setOpen(false)
    }
    const onScroll = () => setOpen(false)
    window.addEventListener("pointerdown", onDown)
    window.addEventListener("scroll", onScroll, true)
    window.addEventListener("resize", onScroll)
    return () => {
      window.removeEventListener("pointerdown", onDown)
      window.removeEventListener("scroll", onScroll, true)
      window.removeEventListener("resize", onScroll)
    }
  }, [open])

  return (
    <span className={`relative inline-flex shrink-0 align-middle ${className}`} onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <button
        ref={btnRef}
        type="button"
        aria-label={label ? `Co znamená: ${label}` : "Nápověda k metrice"}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); open ? setOpen(false) : show() }}
        className={`grid size-5 place-items-center rounded-full border text-[11px] font-extrabold leading-none transition active:scale-90 ${open ? "border-accent bg-accent/15 text-accent" : "border-accent/60 text-accent/90 hover:border-accent hover:text-accent"}`}
      >
        ?
      </button>
      {open && pos && createPortal(
        <span
          ref={tipRef}
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          style={{ position: "fixed", left: pos.left, top: pos.top, width: pos.width, transform: pos.below ? undefined : "translateY(-100%)" }}
          className="z-[130] animate-[infoPop_.14s_ease-out] rounded-xl border border-white/14 bg-raised p-3 text-left text-[12px] font-normal normal-case leading-[1.5] tracking-normal text-fg-soft shadow-[0_16px_44px_rgba(0,0,0,.55)]"
        >
          {label && <b className="mb-1 block text-[13px] font-bold text-fg">{label}</b>}
          {text}
        </span>,
        document.body,
      )}
    </span>
  )
}

export function Metric({ label, value, caption, warm = false, info }: { label: string; value: ReactNode; caption?: string; warm?: boolean; info?: ReactNode }) {
  return (
    <Card className={warm ? "!bg-panel-2" : ""}>
      <span className="flex items-center gap-1.5">
        <Label>{label}</Label>
        {info && <InfoDot text={info} label={label} />}
      </span>
      <p className="t-num mt-3 text-4xl text-fg">{value}</p>
      {caption && <p className="mt-2 text-xs text-fg-2">{caption}</p>}
    </Card>
  )
}

/* ---------- Chip ---------- */
const CHIP: Record<Tone, string> = {
  ok: "bg-ok/15 text-ok", watch: "bg-watch/15 text-watch", alert: "bg-alert/16 text-alert-soft", accent: "bg-accent text-ink",
  muted: "bg-white/[.07] text-fg-2", info: "bg-info/14 text-info", load: "bg-load/18 text-load", self: "bg-self/16 text-self",
}
export function Chip({ children, tone = "muted", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold leading-none ${CHIP[tone]} ${className}`}>{children}</span>
}

/* ---------- Segmented ---------- */
// One segmented control for Pohyb (terrain), Péče sub-tabs, Data sources, sheet toggles.
export function Segmented<K extends string>({ options, value, onChange, ariaLabel, className = "", size = "md" }: {
  options: readonly (readonly [K, string])[]; value: K; onChange: (k: K) => void; ariaLabel?: string; className?: string; size?: "md" | "sm"
}) {
  return (
    <div role="group" aria-label={ariaLabel} className={`inline-flex max-w-full gap-0.5 overflow-x-auto rounded-full bg-white/[.06] p-[3px] ${className}`}>
      {options.map(([k, l]) => {
        const on = k === value
        return (
          <button key={k} type="button" aria-pressed={on} onClick={() => onChange(k)}
            className={`whitespace-nowrap rounded-full font-bold transition ${size === "sm" ? "px-3 py-1.5 text-[11px]" : "px-4 py-2 text-[12px]"} ${on ? "bg-fg text-ink" : "text-fg-2 hover:text-fg"}`}>
            {l}
          </button>
        )
      })}
    </div>
  )
}

/* ---------- Switch ---------- */
export function Switch({ checked, onChange, label, tone = "accent", disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; tone?: "accent" | "alert"; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition disabled:opacity-50 ${checked ? (tone === "alert" ? "bg-alert" : "bg-accent") : "bg-white/15"}`}>
      <span className={`absolute top-[3px] size-[18px] rounded-full transition-all ${checked ? "left-[19px] bg-ink" : "left-[3px] bg-fg-2"}`} />
    </button>
  )
}

/* ---------- AlertBanner ---------- */
// Tones: stop (always open, "dnes neběhat"), alert, watch, info. Collapsible banners
// show only the title when closed; the chevron toggles the text in place.
const AB: Record<string, { box: string; ico: string; Icon: LucideIcon }> = {
  stop: { box: "border-alert/60 bg-alert/16 text-alert-soft", ico: "bg-alert/20 text-alert-soft", Icon: CircleMinus },
  alert: { box: "border-alert/35 bg-alert/10 text-alert-soft", ico: "bg-alert/16 text-alert-soft", Icon: TriangleAlert },
  watch: { box: "border-watch/30 bg-watch/[.08] text-watch-soft", ico: "bg-watch/15 text-watch", Icon: TriangleAlert },
  info: { box: "border-info/28 bg-info/[.07] text-fg-soft", ico: "bg-info/13 text-info", Icon: Info },
}
export function AlertBanner({ tone = "alert", icon, title, children, action, collapsible = false, open = true, onToggle, className = "" }: {
  tone?: "stop" | "alert" | "watch" | "info"; icon?: LucideIcon; title: ReactNode; children?: ReactNode; action?: ReactNode
  collapsible?: boolean; open?: boolean; onToggle?: () => void; className?: string
}) {
  const t = AB[tone] || AB.alert
  const Icon = icon || t.Icon
  const expanded = !collapsible || open
  const head = (
    <>
      <span className={`grid size-[30px] shrink-0 place-items-center rounded-[10px] ${t.ico}`}><Icon className="size-4" aria-hidden /></span>
      <span className="min-w-0 flex-1 text-left">
        <b className="block text-[13px] font-bold leading-5">{title}</b>
        {expanded && children && <span className="mt-0.5 block text-xs leading-5 opacity-90">{children}</span>}
      </span>
    </>
  )
  return (
    <div className={`rounded-2xl border ${t.box} ${className}`}>
      {collapsible ? (
        <button type="button" onClick={onToggle} aria-expanded={expanded} className="flex w-full items-start gap-3 p-3 text-left">
          {head}
          <ChevronDown className={`mt-1.5 size-4 shrink-0 transition ${expanded ? "rotate-180" : ""}`} aria-hidden />
        </button>
      ) : (
        <div className="flex items-start gap-3 p-3">{head}</div>
      )}
      {expanded && action && <div className="-mt-1 px-3 pb-3 pl-[54px]">{action}</div>}
    </div>
  )
}

/* ---------- FactorBar ---------- */
// "Co tvoří skóre …" rows: label, value, +points, bar relative to the largest factor.
export function FactorBar({ label, value, pts, pct, tone = "info", grade }: { label: ReactNode; value?: ReactNode; pts?: number; pct: number; tone?: Tone; grade?: string }) {
  const col = toneCol(tone)
  return (
    <div>
      <div className="flex items-center gap-2">
        {grade && <span className="grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-extrabold" style={{ background: `${col}26`, color: col }}>{grade}</span>}
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{label}</span>
        {value != null && <span className="tabular-nums text-[12px] text-fg-2">{value}</span>}
        {pts != null && <b className="tabular-nums text-[12px]" style={{ color: col }}>+{pts}</b>}
      </div>
      <div className={`mt-1.5 h-1.5 rounded-full bg-white/[.08] ${grade ? "ml-7" : ""}`}>
        <i className="block h-full rounded-full" style={{ width: `${Math.max(6, Math.min(100, pct))}%`, background: col }} />
      </div>
    </div>
  )
}

/* ---------- ListRow ---------- */
// 34 px icon tile, title, meta line, trailing slot. Button when onClick is given.
const LR_TONE: Record<string, string> = {
  info: "bg-info/15 text-info", ok: "bg-ok/15 text-ok", alert: "bg-alert/15 text-alert", watch: "bg-watch/15 text-watch",
  self: "bg-self/15 text-self", accent: "bg-accent/15 text-accent", muted: "bg-white/[.06] text-fg-2",
}
export function ListRow({ icon: Icon, tileText, tone = "info", title, meta, extra, trailing, onClick, className = "" }: {
  icon?: LucideIcon; tileText?: ReactNode; tone?: string; title: ReactNode; meta?: ReactNode; extra?: ReactNode; trailing?: ReactNode; onClick?: () => void; className?: string
}) {
  const inner = (
    <>
      <span className={`grid size-[34px] shrink-0 place-items-center rounded-[10px] text-[11px] font-extrabold ${LR_TONE[tone] || LR_TONE.info}`}>
        {Icon ? <Icon className="size-4" aria-hidden /> : tileText}
      </span>
      <span className="min-w-0 flex-1">
        <b className="block truncate text-sm font-bold text-fg">{title}</b>
        {meta && <span className="mt-0.5 block truncate text-[12px] text-fg-3">{meta}</span>}
        {extra}
      </span>
      {trailing}
    </>
  )
  const cls = `flex w-full min-w-0 items-center gap-3 py-3 text-left ${className}`
  return onClick ? <button type="button" onClick={onClick} className={`group ${cls}`}>{inner}</button> : <div className={cls}>{inner}</div>
}

/* ---------- Empty ---------- */
export function Empty({ children, icon: Icon }: { children: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="grid justify-items-center gap-2 rounded-[14px] border border-dashed border-white/15 p-6 text-center text-sm text-fg-2">
      {Icon && <Icon className="size-6 text-fg-3" aria-hidden />}
      <div>{children}</div>
    </div>
  )
}

export function Ring({ value, label, max = 100, size = 64 }: { value: number; label?: string; max?: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, value / max))
  const r = 42
  const c = 2 * Math.PI * r
  const col = pct >= 0.7 ? C.ok : pct >= 0.4 ? C.accent : pct >= 0.2 ? C.watch : C.alert
  return (
    <div className="flex items-center gap-3">
      <svg width={size} height={size} viewBox="0 0 100 100" className="shrink-0">
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(255 255 255 / .1)" strokeWidth="10" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={col} strokeWidth="10" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} transform="rotate(-90 50 50)" />
        <text x="50" y="60" textAnchor="middle" fontSize="30" fontWeight="800" fill={C.fg} fontFamily="Manrope, Arial, sans-serif">{Math.round(value)}</text>
      </svg>
      {label && <div className="text-sm text-fg-2">{label}</div>}
    </div>
  )
}

/* shared tooltip card used by every chart scrub */
export function ChartTip({ value, sub, color, leftPct, top = 0 }: { value: ReactNode; sub?: ReactNode; color?: string; leftPct: number; top?: number }) {
  return (
    <div className="pointer-events-none absolute z-10 rounded-[10px] border border-white/14 bg-raised px-2 py-1 text-center shadow-[0_10px_28px_rgba(0,0,0,.5)]"
      style={{ top, left: `${leftPct}%`, transform: `translateX(${leftPct > 74 ? "-100%" : leftPct < 26 ? "0%" : "-50%"})` }}>
      <b className="block whitespace-nowrap text-[12px] font-extrabold leading-tight tabular-nums" style={{ color: color || C.fg }}>{value}</b>
      {sub != null && <span className="t-axis block whitespace-nowrap leading-tight">{sub}</span>}
    </div>
  )
}

export function Sparkline({ vals, color = C.info, h = 48 }: { vals: number[]; color?: string; h?: number }) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  if (!vals || vals.length < 2) return null
  const w = 300
  const mx = Math.max(...vals)
  const mn = Math.min(...vals)
  const rg = mx - mn || 1
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, h - ((v - mn) / rg) * (h - 8) - 4])
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ")
  const fnum = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1).replace(".", ","))
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const i = Math.round(((clientX - el.getBoundingClientRect().left) / el.getBoundingClientRect().width) * (vals.length - 1))
    setAct(Math.max(0, Math.min(vals.length - 1, i)))
  }
  const aPct = act != null ? (pts[act][0] / w) * 100 : 0
  const last = pts.at(-1)!
  return (
    <div
      ref={wrapRef}
      className="relative select-none"
      style={{ touchAction: "pan-y" }}
      onPointerMove={(e) => pick(e.clientX)}
      onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
      onPointerUp={() => setAct(null)}
      onPointerCancel={() => setAct(null)}
      onPointerLeave={() => setAct(null)}
    >
      <div className="relative h-12">
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="block h-12 w-full" aria-hidden="true">
          <path d={`M0 ${h} L${pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L")} L${w} ${h} Z`} fill={color} opacity="0.12" />
          <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {act != null && <line x1={pts[act][0]} y1={0} x2={pts[act][0]} y2={h} stroke={color} strokeOpacity=".45" vectorEffect="non-scaling-stroke" />}
        </svg>
        <i className="pointer-events-none absolute size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(last[0] / w) * 100}%`, top: `${(last[1] / h) * 100}%`, background: color }} />
        {act != null && <i className="pointer-events-none absolute size-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${aPct}%`, top: `${(pts[act][1] / h) * 100}%`, background: color, boxShadow: `0 0 0 2px ${C.panel}` }} />}
        {act != null && <ChartTip value={fnum(vals[act])} color={color} leftPct={aPct} top={-30} />}
      </div>
      <div className="mt-1 flex justify-between text-[11px] tabular-nums text-fg-3">
        <span>min {fnum(mn)}</span>
        <span className="font-bold text-fg">nyní {fnum(vals.at(-1)!)}</span>
        <span>max {fnum(mx)}</span>
      </div>
    </div>
  )
}

// Numbered bar chart: value above each bar, the scrubbed bar in lime, the current
// bar in alert (or per-bar status tones when the caller passes them).
export function Bars({ vals, unit = "km", labels, axisLabels, tones }: { vals: number[]; unit?: string; labels?: string[]; axisLabels?: string[]; tones?: Tone[] }) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  if (!vals?.length) return null
  const n = vals.length
  const mx = Math.max(...vals, 1)
  const dense = n > 14
  const per = n <= 13 ? "t" : "d"
  const num = (v: number) => (Number.isInteger(v) ? v : String(Math.round(v * 10) / 10).replace(".", ","))
  const xlab = (i: number) => (labels ? labels[i] || "" : i === n - 1 ? "teď" : i === 0 ? `−${n - 1}${per}` : i === Math.floor((n - 1) / 2) ? `−${n - 1 - i}${per}` : "")
  // FIX-8: with many custom labels, show every other one on narrow screens
  const thinLabels = !!labels && n > 8
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setAct(Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left) / r.width) * n))))
  }
  const fill = (i: number) => {
    if (act === i) return C.accent
    if (tones?.[i]) return tones[i] === "muted" ? "rgb(181 211 202 / .55)" : toneCol(tones[i])
    return i === n - 1 ? C.alert : "rgb(181 211 202 / .6)"
  }
  return (
    <div className="mt-6">
      <div
        ref={wrapRef}
        className="relative flex h-32 select-none items-end gap-1.5 border-b border-line pb-1"
        style={{ touchAction: "pan-y" }}
        onPointerMove={(e) => pick(e.clientX)}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
        onPointerUp={() => setAct(null)}
        onPointerCancel={() => setAct(null)}
        onPointerLeave={() => setAct(null)}
      >
        {vals.map((v, i) => {
          const last = i === n - 1
          const on = act === i
          const showv = !dense || last || v === mx || on
          return (
            <div key={i} className="relative flex h-full min-w-0 flex-1 items-end">
              {on && (
                <div className="pointer-events-none absolute -top-8 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-[10px] border border-white/14 bg-raised px-2 py-1 text-[12px] font-extrabold tabular-nums text-fg shadow-[0_10px_28px_rgba(0,0,0,.5)]">
                  {num(v)} {unit}{xlab(i) ? <span className="t-axis ml-1 font-normal">{xlab(i)}</span> : null}
                </div>
              )}
              {showv && !on && <span className={`absolute left-1/2 top-0 -translate-x-1/2 text-[11px] font-bold tabular-nums ${!last && v !== mx && n > 8 ? "hidden sm:block" : ""}`} style={{ color: last ? (tones?.[i] && tones[i] !== "muted" ? toneCol(tones[i]) : tones?.[i] ? C.fg : C.alert) : C.fg2 }}>{num(v)}</span>}
              <i className="block min-h-1 w-full self-end rounded-t-[3px] transition-colors" style={{ height: `${Math.max(3, (v / mx) * 88)}%`, background: fill(i) }} />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {vals.map((_, i) => (
          <span key={i} className={`t-axis min-w-0 flex-1 whitespace-nowrap text-center ${i === 0 && !labels ? "text-left" : i === n - 1 && !labels ? "text-right" : ""} ${thinLabels && !axisLabels ? "truncate" : ""} ${thinLabels && i % 2 === 1 ? "invisible sm:visible" : ""}`}>{axisLabels ? axisLabels[i] : xlab(i)}</span>
        ))}
      </div>
    </div>
  )
}

// Line chart with real axes: Y ticks (values) + X ticks (dates), optional
// threshold line. Used for the drift-score-over-time trend and metric trends.
export function AxisLineChart({
  points,
  yMin,
  yMax,
  threshold,
  thresholdLabel,
  unit = "",
  dec = 0,
  color = C.info,
  height = 128,
  band,
  zone = false,
}: {
  points: { t: string; v: number }[]
  yMin?: number
  yMax?: number
  threshold?: number
  thresholdLabel?: string
  unit?: string
  dec?: number
  color?: string
  height?: number
  /** a shaded reference range (e.g. the runner's usual range) with an optional midline */
  band?: { lo: number; hi: number; mid?: number; label?: string }
  /** tint the area above `threshold` (the "over threshold" zone) */
  zone?: boolean
}) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  if (!points || points.length < 2) return <p className="mt-2 text-xs text-fg-3">Zatím málo dat pro trend v čase.</p>
  const W = 320
  const H = height
  const padL = 32
  const padR = 10
  const padT = 12
  const padB = 22
  const vs = points.map((p) => p.v)
  let mn = yMin ?? Math.min(...vs, ...(band ? [band.lo] : []))
  let mx = yMax ?? Math.max(...vs, ...(band ? [band.hi] : []))
  if (band && yMin == null && yMax == null) {
    const pad = (mx - mn) * 0.08
    mn -= pad
    mx += pad
  }
  if (mn === mx) {
    mn -= 1
    mx += 1
  }
  const x = (i: number) => padL + (i / (points.length - 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - mn) / (mx - mn)) * (H - padT - padB)
  const nf = (v: number) => (dec > 0 ? v.toFixed(dec).replace(".", ",") : String(Math.round(v)))
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ")
  const area = `M${x(0).toFixed(1)} ${(H - padB).toFixed(1)} ` + points.map((p, i) => `L${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ") + ` L${x(points.length - 1).toFixed(1)} ${(H - padB).toFixed(1)} Z`
  const ticks = [mx, (mx + mn) / 2, mn]
  const xi = [0, Math.floor((points.length - 1) / 2), points.length - 1]
  const fmt = (d: string) => new Date(d.length <= 10 ? d + "T00:00:00" : d).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })
  // Map a pointer's clientX to the nearest data index. Works for mouse hover and
  // touch scrub (drag your finger along the line to read each point on iPhone).
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const i = Math.round(((((clientX - r.left) / r.width) * W - padL) / (W - padL - padR)) * (points.length - 1))
    setAct(Math.max(0, Math.min(points.length - 1, i)))
  }
  const aPct = act != null ? (x(act) / W) * 100 : 0
  return (
    <div
      ref={wrapRef}
      className="relative mt-2 select-none"
      style={{ touchAction: "pan-y" }}
      onPointerMove={(e) => pick(e.clientX)}
      onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
      onPointerUp={() => setAct(null)}
      onPointerCancel={() => setAct(null)}
      onPointerLeave={() => setAct(null)}
    >
      {/* Lines/areas stretch with the container; every label and dot is HTML on top,
          so text is never distorted (FIX-2) and strokes keep their width. */}
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" style={{ height }} preserveAspectRatio="none" aria-hidden="true">
        {ticks.map((t, i) => (
          <line key={i} x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={C.info} strokeOpacity=".1" vectorEffect="non-scaling-stroke" />
        ))}
        {band && (
          <g>
            <rect x={padL} y={y(band.hi)} width={W - padL - padR} height={Math.max(1, y(band.lo) - y(band.hi))} fill={color} opacity=".09" />
            <line x1={padL} y1={y(band.hi)} x2={W - padR} y2={y(band.hi)} stroke={color} strokeOpacity=".35" vectorEffect="non-scaling-stroke" />
            <line x1={padL} y1={y(band.lo)} x2={W - padR} y2={y(band.lo)} stroke={color} strokeOpacity=".35" vectorEffect="non-scaling-stroke" />
            {band.mid != null && <line x1={padL} y1={y(band.mid)} x2={W - padR} y2={y(band.mid)} stroke={color} strokeOpacity=".5" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
          </g>
        )}
        {zone && threshold != null && threshold >= mn && threshold <= mx && (
          <rect x={padL} y={padT} width={W - padL - padR} height={Math.max(0, y(threshold) - padT)} fill={C.alert} opacity=".07" />
        )}
        {threshold != null && threshold >= mn && threshold <= mx && (
          <line x1={padL} y1={y(threshold)} x2={W - padR} y2={y(threshold)} stroke={C.alert} strokeOpacity=".55" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        )}
        <path d={area} fill={color} opacity=".12" />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {act != null && <line x1={x(act)} y1={padT} x2={x(act)} y2={H - padB} stroke={color} strokeOpacity=".45" vectorEffect="non-scaling-stroke" />}
      </svg>
      {ticks.map((t, i) => (
        <span key={i} className="t-axis pointer-events-none absolute left-0 -translate-y-1/2 leading-none" style={{ top: (y(t) / H) * height, width: `${((padL - 4) / W) * 100}%`, textAlign: "right" }}>{nf(t)}</span>
      ))}
      {threshold != null && threshold >= mn && threshold <= mx && thresholdLabel && (
        <span className="pointer-events-none absolute -translate-y-full whitespace-nowrap pb-0.5 text-[11px] leading-none text-alert" style={{ top: (y(threshold) / H) * height, left: `${((padL + 4) / W) * 100}%` }}>{thresholdLabel}</span>
      )}
      {xi.map((idx, i) => (
        <span key={i} className="t-axis pointer-events-none absolute whitespace-nowrap leading-none" style={{ top: ((H - 12) / H) * height, left: `${(x(idx) / W) * 100}%`, transform: i === 0 ? "none" : i === xi.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>{fmt(points[idx].t)}</span>
      ))}
      {/* endpoint + scrub dots as HTML so they stay round */}
      <i className="pointer-events-none absolute size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(x(points.length - 1) / W) * 100}%`, top: (y(points.at(-1)!.v) / H) * height, background: color }} />
      {act != null && (
        <i className="pointer-events-none absolute size-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${aPct}%`, top: (y(points[act].v) / H) * height, background: color, boxShadow: `0 0 0 2px ${C.panel}` }} />
      )}
      {act == null && (
        <span className="pointer-events-none absolute -translate-x-full -translate-y-full whitespace-nowrap pb-1 pr-1 text-[11px] font-bold leading-none tabular-nums" style={{ left: `${(x(points.length - 1) / W) * 100}%`, top: (y(points.at(-1)!.v) / H) * height, color }}>{nf(points.at(-1)!.v)}{unit}</span>
      )}
      {band?.label && (
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-3">
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-4 rounded-sm border" style={{ background: `${color}22`, borderColor: `${color}66` }} />
            {band.label} {nf(band.lo)}–{nf(band.hi)}{unit}
          </span>
          {band.mid != null && (
            <span className="inline-flex items-center gap-1.5">
              <i className="inline-block w-4 border-t border-dashed" style={{ borderColor: `${color}99` }} />střed {nf(band.mid)}{unit}
            </span>
          )}
        </p>
      )}
      {act != null && <ChartTip value={<>{nf(points[act].v)}{unit}</>} sub={fmt(points[act].t)} color={color} leftPct={aPct} top={-6} />}
    </div>
  )
}

export function Slider({
  name,
  min,
  max,
  value,
  onChange,
  labels,
  tone,
}: {
  name: string
  min: number
  max: number
  value: number
  onChange: (v: number) => void
  labels?: string[]
  /** "pain": fill runs ok → watch → alert with the value; default lime */
  tone?: "pain"
}) {
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0
  const fillCol = tone === "pain" ? (pct >= 50 ? C.alert : pct >= 25 ? C.watch : C.ok) : C.accent
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        name={name}
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="range flex-1"
        style={{ ["--fill" as any]: `${pct}%`, ["--fill-color" as any]: fillCol }}
      />
      <span className="w-16 shrink-0 text-right text-sm font-extrabold tabular-nums" style={{ color: fillCol }}>{labels ? labels[value] ?? value : value}</span>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="mt-4 block">
      <span className="text-[13px] font-bold text-fg-soft">
        {label} {hint && <span className="text-xs font-normal text-fg-3">{hint}</span>}
      </span>
      <div className="mt-2">{children}</div>
    </label>
  )
}

export function Sheet({ open, onClose, children, footer }: { open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  if (!open) return null
  // Portalled to <body>: inside <main> (isolation: isolate) the sheet sat under the
  // fixed tab bar and Check-in button, which covered its footer on phones.
  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 backdrop-blur-sm animate-[fadeIn_.2s_ease-out] md:items-center md:p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[93dvh] w-full max-w-xl flex-col overflow-hidden rounded-t-[26px] border border-white/12 bg-raised text-fg shadow-[0_-12px_48px_rgba(0,0,0,.55)] animate-[sheetUp_.28s_cubic-bezier(.22,1,.36,1)] md:max-h-[88dvh] md:rounded-[26px] md:animate-[fadeIn_.2s_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* grab handle (phone) */}
        <span className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-white/25 md:hidden" aria-hidden="true" />
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pt-3 md:px-6 md:pt-4" style={{ overscrollBehavior: "contain" }}>
          {children}
          {!footer && <div className="h-[max(1.25rem,env(safe-area-inset-bottom))]" />}
        </div>
        {footer && (
          <div className="shrink-0 border-t border-white/10 bg-raised/95 px-5 py-3 pb-[max(.85rem,env(safe-area-inset-bottom))] backdrop-blur md:px-6">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

// tiny toast
type Toast = { id: number; title: string; msg?: string }
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {})
export function useToast() {
  return useContext(ToastCtx)
}
export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = (t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { ...t, id }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3600)
  }
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 left-1/2 z-[60] flex w-[min(92vw,26rem)] -translate-x-1/2 flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="animate-[careReveal_.28s_ease-out] rounded-2xl border border-white/14 bg-raised px-4 py-3 text-fg shadow-[0_16px_44px_rgba(0,0,0,.55)]">
            <b className="text-sm">{t.title}</b>
            {t.msg && <p className="mt-0.5 text-xs text-fg-2">{t.msg}</p>}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useAsync() {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async (fn: () => Promise<any>) => {
    setBusy(true)
    setErr(null)
    try {
      return await fn()
    } catch (e: any) {
      setErr(e?.message || "Něco se nepovedlo")
      throw e
    } finally {
      setBusy(false)
    }
  }
  return { busy, err, run, setErr }
}

// bind slider live label update helper for uncontrolled forms is unnecessary;
// keep a no-op export to satisfy potential imports
export function noop() {}
export type { ReactNode }
export { useEffect }
