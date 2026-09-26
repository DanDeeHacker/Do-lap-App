// Shared presentational primitives, styled with the same light-hex Tailwind
// classes the v2 mockup uses so the Motion Atlas skin (index.css) remaps them
// to the dark theme automatically.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { C } from "@/tokens"

export function Label({ children }: { children: ReactNode }) {
  return (
    <p className="t-label">{children}</p>
  )
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`group rounded-[24px] border border-line bg-panel p-5 transition duration-200 ${className}`}
    >
      {children}
    </section>
  )
}

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
    <span
      className={`relative inline-flex shrink-0 align-middle ${className}`}
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={btnRef}
        type="button"
        aria-label={label ? `Co znamená: ${label}` : "Nápověda k metrice"}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); open ? setOpen(false) : show() }}
        className="grid size-[18px] place-items-center rounded-full border border-fg-2/50 text-[11px] font-bold leading-none text-fg-2 transition hover:border-accent hover:text-accent active:scale-90"
      >
        ?
      </button>
      {open && pos && createPortal(
        <span
          ref={tipRef}
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          style={{ position: "fixed", left: pos.left, top: pos.top, width: pos.width, transform: pos.below ? undefined : "translateY(-100%)" }}
          className="z-[130] animate-[infoPop_.14s_ease-out] rounded-2xl border border-white/12 bg-panel p-3 text-left text-[11px] font-normal normal-case leading-[1.45] tracking-normal text-fg-soft shadow-[0_16px_44px_rgba(0,0,0,.55)]"
        >
          {label && <b className="mb-1 block text-[13px] text-fg">{label}</b>}
          {text}
        </span>,
        document.body,
      )}
    </span>
  )
}

export function Metric({
  label,
  value,
  caption,
  warm = false,
  info,
}: {
  label: string
  value: ReactNode
  caption?: string
  warm?: boolean
  info?: ReactNode
}) {
  return (
    <Card className={warm ? "border-0 bg-panel-2 text-fg" : ""}>
      <span className="flex items-center gap-1.5">
        <Label>{label}</Label>
        {info && <InfoDot text={info} label={label} />}
      </span>
      <p className={`mt-4 font-serif text-4xl tracking-[-.07em] ${warm ? "text-white" : ""}`}>{value}</p>
      {caption && <p className={`mt-2 text-xs ${warm ? "text-fg-soft" : "text-fg-2"}`}>{caption}</p>}
    </Card>
  )
}

export function Chip({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "ok" | "watch" | "alert" | "accent" }) {
  const cls =
    tone === "ok"
      ? "bg-info-bg text-info"
      : tone === "watch"
        ? "bg-alert-bg text-alert-soft"
        : tone === "alert"
          ? "bg-alert-bg text-alert"
          : tone === "accent"
            ? "bg-accent text-ink"
            : "bg-panel-2 text-fg-2"
  return <span className={`inline-block rounded-full px-2.5 py-1 text-[11px] font-bold ${cls}`}>{children}</span>
}

export function Ring({ value, label, max = 100, size = 64 }: { value: number; label?: string; max?: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, value / max))
  const r = 42
  const c = 2 * Math.PI * r
  const col = pct >= 0.7 ? C.ok : pct >= 0.4 ? C.accent : pct >= 0.2 ? C.watch : C.alert
  return (
    <div className="flex items-center gap-3">
      <svg width={size} height={size} viewBox="0 0 100 100" className="shrink-0">
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(255 255 255 / .12)" strokeWidth="10" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={col}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          transform="rotate(-90 50 50)"
        />
        <text x="50" y="58" textAnchor="middle" fontSize="30" fontWeight="700" fill={C.fg} fontFamily="serif">
          {Math.round(value)}
        </text>
      </svg>
      {label && <div className="text-sm text-fg-2">{label}</div>}
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
  const fnum = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1))
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const i = Math.round(((clientX - el.getBoundingClientRect().left) / el.getBoundingClientRect().width) * (vals.length - 1))
    setAct(Math.max(0, Math.min(vals.length - 1, i)))
  }
  const aPct = act != null ? (pts[act][0] / w) * 100 : 0
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
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="block h-12 w-full">
        <path d={`M0 ${h} L${pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L")} L${w} ${h} Z`} fill={color} opacity="0.12" />
        <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {act != null && <line x1={pts[act][0]} y1={0} x2={pts[act][0]} y2={h} stroke={color} strokeOpacity=".4" />}
        <circle cx={pts.at(-1)![0]} cy={pts.at(-1)![1]} r="3.5" fill={color} />
        {act != null && <circle cx={pts[act][0]} cy={pts[act][1]} r="4" fill={color} stroke={C.panel} strokeWidth="1.5" />}
      </svg>
      {act != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-md border border-white/12 bg-panel px-1.5 py-0.5 tabular-nums text-[11px] shadow-lg"
          style={{ left: `${aPct}%`, color, transform: `translateX(${aPct > 74 ? "-100%" : aPct < 26 ? "0%" : "-50%"})` }}
        >
          {fnum(vals[act])}
        </div>
      )}
      <div className="mt-1 flex justify-between tabular-nums text-[11px] text-fg-3">
        <span>min {fnum(mn)}</span>
        <span className="font-bold text-accent">nyní {fnum(vals.at(-1)!)}</span>
        <span>max {fnum(mx)}</span>
      </div>
    </div>
  )
}

// Numbered bar chart in the v2 design language: value above each bar, light
// teal fills, the current bar in warm accent, a drawn baseline axis.
export function Bars({ vals, unit = "km", labels }: { vals: number[]; unit?: string; labels?: string[] }) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  if (!vals?.length) return null
  const n = vals.length
  const mx = Math.max(...vals, 1)
  const dense = n > 14
  const per = n <= 13 ? "t" : "d"
  const num = (v: number) => (Number.isInteger(v) ? v : Math.round(v * 10) / 10)
  const xlab = (i: number) => (labels ? labels[i] || "" : i === n - 1 ? "teď" : i === 0 ? `−${n - 1}${per}` : i === Math.floor((n - 1) / 2) ? `−${n - 1 - i}${per}` : "")
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setAct(Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left) / r.width) * n))))
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
                <div className="pointer-events-none absolute -top-6 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/12 bg-panel px-1.5 py-0.5 tabular-nums text-[11px] text-fg shadow-lg">
                  {xlab(i) ? `${xlab(i)}: ` : ""}{num(v)} {unit}
                </div>
              )}
              {showv && <span className={`absolute left-1/2 top-0 -translate-x-1/2 text-[11px] font-bold ${last ? "text-alert" : "text-fg-2"}`}>{num(v)}</span>}
              <i className={`block min-h-1 w-full self-end rounded-t-sm ${on ? "bg-accent" : last ? "bg-alert" : "bg-viz"}`} style={{ height: `${Math.max(3, (v / mx) * 88)}%` }} />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {vals.map((_, i) => (
          <span key={i} className="min-w-0 flex-1 text-center tabular-nums text-[11px] text-fg-3">{xlab(i)}</span>
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
        <span className="pointer-events-none absolute right-0 -translate-y-full pb-0.5 text-[11px] leading-none text-alert" style={{ top: (y(threshold) / H) * height }}>{thresholdLabel}</span>
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
        <span className="pointer-events-none absolute -translate-x-full -translate-y-full pb-1 pr-1 text-[11px] font-bold leading-none tabular-nums" style={{ left: `${(x(points.length - 1) / W) * 100}%`, top: (y(points.at(-1)!.v) / H) * height, color }}>{nf(points.at(-1)!.v)}{unit}</span>
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
      {act != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-lg border border-white/12 bg-panel px-2 py-1 text-center shadow-lg"
          style={{ left: `${aPct}%`, transform: `translateX(${aPct > 74 ? "-100%" : aPct < 26 ? "0%" : "-50%"})` }}
        >
          <b className="block tabular-nums text-[11px] leading-tight" style={{ color }}>{nf(points[act].v)}{unit}</b>
          <span className="block tabular-nums text-[11px] leading-tight text-fg-3">{fmt(points[act].t)}</span>
        </div>
      )}
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
}: {
  name: string
  min: number
  max: number
  value: number
  onChange: (v: number) => void
  labels?: string[]
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        name={name}
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 flex-1 accent-accent"
      />
      <span className="w-16 shrink-0 text-right tabular-nums text-sm text-accent">{labels ? labels[value] ?? value : value}</span>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="mt-4 block">
      <span className="text-xs font-bold text-fg-2">
        {label} {hint && <span className="font-normal text-fg-3">{hint}</span>}
      </span>
      <div className="mt-2">{children}</div>
    </label>
  )
}

export function Sheet({ open, onClose, children, footer }: { open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 backdrop-blur-sm animate-[fadeIn_.2s_ease-out] md:items-center md:p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[93dvh] w-full max-w-xl flex-col overflow-hidden rounded-t-[28px] border border-white/10 bg-panel text-fg shadow-[0_-8px_40px_rgba(0,0,0,.5)] animate-[sheetUp_.28s_cubic-bezier(.22,1,.36,1)] md:max-h-[88dvh] md:rounded-[28px] md:animate-[fadeIn_.2s_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* grab handle (phone) */}
        <span className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-white/20 md:hidden" />
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pt-3 md:px-6 md:pt-4" style={{ overscrollBehavior: "contain" }}>
          {children}
          {!footer && <div className="h-[max(1.25rem,env(safe-area-inset-bottom))]" />}
        </div>
        {footer && (
          <div className="shrink-0 border-t border-white/10 bg-panel/95 px-5 py-3 pb-[max(.85rem,env(safe-area-inset-bottom))] backdrop-blur md:px-6">
            {footer}
          </div>
        )}
      </div>
    </div>
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
      <div className="fixed bottom-5 left-1/2 z-[60] flex w-[min(92vw,26rem)] -translate-x-1/2 flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className="animate-[careReveal_.28s_ease-out] rounded-2xl border border-white/10 bg-panel-2 px-4 py-3 text-fg shadow-2xl">
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
