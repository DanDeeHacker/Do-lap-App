// Shared presentational primitives, styled with the same light-hex Tailwind
// classes the v2 mockup uses so the Motion Atlas skin (index.css) remaps them
// to the dark theme automatically.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"

export function Label({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[10px] font-medium uppercase tracking-[.16em] text-[#a8c7bd]">{children}</p>
  )
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`group rounded-[24px] border border-[#dfe2da] bg-white p-5 transition duration-200 ${className}`}
    >
      {children}
    </section>
  )
}

// Small "?" affordance: shows what a metric measures + how to read it against
// your own baseline. Works on both desktop (hover) and phones (tap toggles;
// tapping elsewhere closes). Self-positioning above the icon.
export function InfoDot({ text, label, className = "" }: { text: ReactNode; label?: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("pointerdown", onDown)
    return () => window.removeEventListener("pointerdown", onDown)
  }, [open])
  return (
    <span
      ref={ref}
      className={`relative inline-flex shrink-0 align-middle ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label ? `Co znamená: ${label}` : "Nápověda k metrice"}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen((v) => !v) }}
        className="grid size-[18px] place-items-center rounded-full border border-[#8fb0a5]/50 text-[10px] font-bold leading-none text-[#8fb0a5] transition hover:border-[#c7ff54] hover:text-[#c7ff54] active:scale-90"
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute bottom-[calc(100%+8px)] left-1/2 z-[95] w-64 max-w-[78vw] -translate-x-1/2 rounded-2xl border border-white/12 bg-[#0c201d] p-3 text-left text-[11px] font-normal normal-case leading-[1.45] tracking-normal text-[#cfe2da] shadow-[0_16px_40px_rgba(0,0,0,.5)] max-sm:fixed max-sm:inset-x-3 max-sm:bottom-[calc(1rem+env(safe-area-inset-bottom))] max-sm:left-3 max-sm:right-3 max-sm:top-auto max-sm:w-auto max-sm:max-w-none max-sm:translate-x-0"
          onClick={(e) => e.stopPropagation()}
        >
          {label && <b className="mb-1 block text-[13px] text-[#f1f8f1]">{label}</b>}
          {text}
        </span>
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
    <Card className={warm ? "border-0 bg-[#235e59] text-[#f8f7f1]" : ""}>
      <span className="flex items-center gap-1.5">
        <Label>{label}</Label>
        {info && <InfoDot text={info} label={label} />}
      </span>
      <p className={`mt-4 font-serif text-4xl tracking-[-.07em] ${warm ? "text-white" : ""}`}>{value}</p>
      {caption && <p className={`mt-2 text-xs ${warm ? "text-[#c9dfd8]" : "text-[#6b7b76]"}`}>{caption}</p>}
    </Card>
  )
}

export function Chip({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "ok" | "watch" | "alert" | "accent" }) {
  const cls =
    tone === "ok"
      ? "bg-[#17382f] text-[#6ce6d3]"
      : tone === "watch"
        ? "bg-[#3c2922] text-[#ffc1ab]"
        : tone === "alert"
          ? "bg-[#3c2922] text-[#e77a59]"
          : tone === "accent"
            ? "bg-[#c7ff54] text-[#071313]"
            : "bg-[#edf0e9] text-[#64736e]"
  return <span className={`inline-block rounded-full px-2.5 py-1 text-[11px] font-bold ${cls}`}>{children}</span>
}

export function Ring({ value, label, max = 100, size = 64 }: { value: number; label?: string; max?: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, value / max))
  const r = 42
  const c = 2 * Math.PI * r
  const col = pct >= 0.7 ? "#6ce6d3" : pct >= 0.4 ? "#c7ff54" : pct >= 0.2 ? "#f6d69a" : "#e77a59"
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
        <text x="50" y="58" textAnchor="middle" fontSize="30" fontWeight="700" fill="#f1f8f1" fontFamily="serif">
          {Math.round(value)}
        </text>
      </svg>
      {label && <div className="text-sm text-[#a9c2b9]">{label}</div>}
    </div>
  )
}

export function Sparkline({ vals, color = "#6ce6d3", h = 48 }: { vals: number[]; color?: string; h?: number }) {
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
        {act != null && <circle cx={pts[act][0]} cy={pts[act][1]} r="4" fill={color} stroke="#0c201d" strokeWidth="1.5" />}
      </svg>
      {act != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-md border border-white/12 bg-[#0c201d] px-1.5 py-0.5 font-mono text-[10px] shadow-lg"
          style={{ left: `${aPct}%`, color, transform: `translateX(${aPct > 74 ? "-100%" : aPct < 26 ? "0%" : "-50%"})` }}
        >
          {fnum(vals[act])}
        </div>
      )}
      <div className="mt-1 flex justify-between font-mono text-[9px] text-[#71837b]">
        <span>min {fnum(mn)}</span>
        <span className="font-bold text-[#c7ff54]">nyní {fnum(vals.at(-1)!)}</span>
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
        className="relative flex h-32 select-none items-end gap-1.5 border-b border-[#dae2dd] pb-1"
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
                <div className="pointer-events-none absolute -top-6 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/12 bg-[#0c201d] px-1.5 py-0.5 font-mono text-[10px] text-[#f1f8f1] shadow-lg">
                  {xlab(i) ? `${xlab(i)}: ` : ""}{num(v)} {unit}
                </div>
              )}
              {showv && <span className={`absolute left-1/2 top-0 -translate-x-1/2 text-[9px] font-bold ${last ? "text-[#e77a59]" : "text-[#9bb3aa]"}`}>{num(v)}</span>}
              <i className={`block min-h-1 w-full self-end rounded-t-sm ${on ? "bg-[#c7ff54]" : last ? "bg-[#cf6542]" : "bg-[#b5d3ca]"}`} style={{ height: `${Math.max(3, (v / mx) * 88)}%` }} />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {vals.map((_, i) => (
          <span key={i} className="min-w-0 flex-1 text-center font-mono text-[9px] text-[#71837b]">{xlab(i)}</span>
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
  color = "#6ce6d3",
  height = 128,
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
}) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  if (!points || points.length < 2) return <p className="mt-2 text-xs text-[#71837b]">Zatím málo dat pro trend v čase.</p>
  const W = 320
  const H = height
  const padL = 32
  const padR = 10
  const padT = 12
  const padB = 22
  const vs = points.map((p) => p.v)
  let mn = yMin ?? Math.min(...vs)
  let mx = yMax ?? Math.max(...vs)
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
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" style={{ height }} preserveAspectRatio="none">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke="#6ce6d3" strokeOpacity=".1" />
            <text x={padL - 5} y={y(t) + 3} textAnchor="end" fill="#71837b" fontSize="8">{nf(t)}</text>
          </g>
        ))}
        {threshold != null && threshold >= mn && threshold <= mx && (
          <g>
            <line x1={padL} y1={y(threshold)} x2={W - padR} y2={y(threshold)} stroke="#e77a59" strokeOpacity=".55" strokeDasharray="4 3" />
            {thresholdLabel && <text x={W - padR} y={y(threshold) - 3} textAnchor="end" fill="#e77a59" fontSize="8">{thresholdLabel}</text>}
          </g>
        )}
        <path d={area} fill={color} opacity=".12" />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {act != null && <line x1={x(act)} y1={padT} x2={x(act)} y2={H - padB} stroke={color} strokeOpacity=".45" strokeWidth="1" />}
        <circle cx={x(points.length - 1)} cy={y(points.at(-1)!.v)} r="3.5" fill={color} />
        {act != null && (
          <circle cx={x(act)} cy={y(points[act].v)} r="4" fill={color} stroke="#0c201d" strokeWidth="1.5" />
        )}
        {act == null && (
          <text x={x(points.length - 1)} y={y(points.at(-1)!.v) - 6} textAnchor="end" fill={color} fontSize="9" fontWeight="bold">{nf(points.at(-1)!.v)}{unit}</text>
        )}
        {xi.map((idx, i) => (
          <text key={i} x={x(idx)} y={H - 6} textAnchor={i === 0 ? "start" : i === xi.length - 1 ? "end" : "middle"} fill="#71837b" fontSize="8">{fmt(points[idx].t)}</text>
        ))}
      </svg>
      {act != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-lg border border-white/12 bg-[#0c201d] px-2 py-1 text-center shadow-lg"
          style={{ left: `${aPct}%`, transform: `translateX(${aPct > 74 ? "-100%" : aPct < 26 ? "0%" : "-50%"})` }}
        >
          <b className="block font-mono text-[11px] leading-tight" style={{ color }}>{nf(points[act].v)}{unit}</b>
          <span className="block font-mono text-[9px] leading-tight text-[#71837b]">{fmt(points[act].t)}</span>
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
        className="h-1.5 flex-1 accent-[#c7ff54]"
      />
      <span className="w-16 shrink-0 text-right font-mono text-sm text-[#c7ff54]">{labels ? labels[value] ?? value : value}</span>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="mt-4 block">
      <span className="text-xs font-bold text-[#a9c2b9]">
        {label} {hint && <span className="font-normal text-[#71837b]">{hint}</span>}
      </span>
      <div className="mt-2">{children}</div>
    </label>
  )
}

export function Sheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 md:items-center md:p-6" onClick={onClose}>
      <div
        className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-[28px] border border-white/10 bg-[#0c201d] p-6 text-[#f1f8f1] md:rounded-[28px]"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
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
          <div key={t.id} className="animate-[careReveal_.28s_ease-out] rounded-2xl border border-white/10 bg-[#102724] px-4 py-3 text-[#f1f8f1] shadow-2xl">
            <b className="text-sm">{t.title}</b>
            {t.msg && <p className="mt-0.5 text-xs text-[#a9c2b9]">{t.msg}</p>}
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
