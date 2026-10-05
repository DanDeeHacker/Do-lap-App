// Morning and evening report (owner request 2026-10-03, form A): full-screen story
// cards — tap the right side (or swipe) for the next card, the left side for the
// previous one — with a way into the assistant on the last card. The numbers come
// from backend/app/metrics/daily_report.py; every chart here is drawn in SVG.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { api } from "@/api"
import { useApp } from "@/store"
import { useAssistant } from "@/assistant"
import { C, goodCol } from "@/tokens"
import { ReadinessFactors, readinessCol } from "@/capacity"
import { InfoDot, Label } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { Bed, ChevronRight, Coffee, Eye, Info, MessageCircle, Moon, Sparkles, Sun, TriangleAlert, X } from "lucide-react"

const STAGE_COL: Record<string, string> = { deep: "#4c6ef5", light: "#74c0fc", rem: "#c084fc", awake: C.watch }
const STAGE_LABEL: Record<string, string> = { deep: "Hluboký", light: "Lehký", rem: "REM", awake: "Bdění" }
const STAGE_ROW: Record<string, number> = { awake: 0, rem: 1, light: 2, deep: 3 }
const num = (v: number | null | undefined, d = 1) => (v == null ? "—" : v.toLocaleString("cs-CZ", { maximumFractionDigits: d, minimumFractionDigits: 0 }))
const hm = (min: number | null | undefined) => (min == null ? "—" : min < 60 ? `${Math.round(min)} min` : `${Math.floor(min / 60)} h ${String(Math.round(min % 60)).padStart(2, "0")} min`)
const hmShort = (min: number) => `${Math.floor(min / 60)}:${String(Math.round(min % 60)).padStart(2, "0")}`
const paceS = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`
const toMin = (s?: string | null) => { const m = s?.match(/^(\d+):(\d+)$/); return m ? +m[1] * 60 + +m[2] : null }
const fmtDay = (iso: string) => { const t = new Date(iso + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" }); return t.charAt(0).toUpperCase() + t.slice(1) }

// ---- small visuals --------------------------------------------------------------------
function Ring({ value, max = 100, size = 108, col, children }: { value: number | null | undefined; max?: number; size?: number; col: string; children?: ReactNode }) {
  const r = size / 2 - 7, L = 2 * Math.PI * r
  const f = value == null ? 0 : Math.max(0, Math.min(1, value / max))
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="9" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth="9" strokeLinecap="round" strokeDasharray={`${L * f} ${L}`} />
      </svg>
      <div className="relative text-center">{children}</div>
    </div>
  )
}

function Hypnogram({ hyp, start }: { hyp: [number, number, string][]; start?: string | null }) {
  const total = hyp[hyp.length - 1][1]
  const W = 320, H = 132, top = 8, rowH = 26, x = (m: number) => (m / total) * W
  const s0 = toMin(start)
  const ticks: number[] = []
  if (s0 != null) { for (let t = Math.ceil(s0 / 60) * 60; t < s0 + total; t += 60) ticks.push(t - s0) }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Průběh spánku přes noc" data-testid="hypnogram">
      {Object.entries(STAGE_ROW).map(([st, row]) => (
        <g key={st}>
          <line x1={0} x2={W} y1={top + row * rowH + rowH / 2} y2={top + row * rowH + rowH / 2} stroke="rgb(255 255 255 / .05)" />
        </g>
      ))}
      {hyp.map(([a, b, st], i) => (
        <rect key={i} x={x(a)} width={Math.max(0.8, x(b) - x(a))} y={top + STAGE_ROW[st] * rowH + 3} height={rowH - 6} rx={2.5} fill={STAGE_COL[st]} />
      ))}
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={top + 4 * rowH} y2={top + 4 * rowH + 4} stroke="rgb(255 255 255 / .3)" />
          <text x={x(t)} y={H - 2} textAnchor="middle" fontSize="9.5" fill={C.fg3}>{hmShort(((s0 ?? 0) + t) % 1440).replace(":00", "")}</text>
        </g>
      ))}
    </svg>
  )
}

function Bars({ items, max, ref: refLine, refLabel }: { items: { label: string; v: number | null; col?: string; hatch?: boolean; on?: boolean }[]; max: number; ref?: number | null; refLabel?: string }) {
  const H = 96
  return (
    <div className="relative">
      <div className="flex items-end gap-1.5" style={{ height: H }}>
        {items.map((it, i) => (
          <div key={i} className="flex min-w-0 flex-1 flex-col items-center justify-end" style={{ height: H }}>
            <span className="mb-1 text-[10px] tabular-nums text-fg-3">{it.v ? num(it.v) : ""}</span>
            <i className="block w-full rounded-t-[5px]" style={{
              height: `${Math.max(it.v ? 3 : 0, ((it.v || 0) / max) * (H - 18))}px`, background: it.col || C.info,
              backgroundImage: it.hatch ? "repeating-linear-gradient(135deg, rgb(0 0 0 / .25) 0 3px, transparent 3px 6px)" : undefined,
              outline: it.on ? `2px solid ${C.fg}` : undefined, outlineOffset: 1,
            }} />
          </div>
        ))}
      </div>
      {refLine != null && refLine > 0 && (
        <div className="pointer-events-none absolute inset-x-0 border-t border-dashed border-fg-3" style={{ bottom: `${(refLine / max) * (H - 18)}px` }}>
          {refLabel && <span className="absolute -top-[15px] left-0 rounded bg-black/40 px-1 text-[10px] text-fg-2">{refLabel}</span>}
        </div>
      )}
      <div className="mt-1 flex gap-1.5">{items.map((it, i) => <span key={i} className={`flex-1 text-center text-[10.5px] ${it.on ? "font-bold text-fg" : "text-fg-3"}`}>{it.label}</span>)}</div>
    </div>
  )
}

function VsNorm({ label, v, norm, unit, col, max }: { label: string; v: number | null | undefined; norm?: number | null; unit: string; col: string; max: number }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="flex items-center gap-1.5 text-fg-2"><i className="size-2 rounded-full" style={{ background: col }} />{label}</span>
        <span className="tabular-nums text-fg-3"><b className="text-fg">{num(v, 0)}</b> {unit}{norm != null ? ` · obvykle ${num(norm, 0)}` : ""}</span>
      </div>
      <div className="relative mt-1 h-2 rounded-full bg-white/[.07]">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, ((v || 0) / max) * 100)}%`, background: col }} />
        {norm != null && <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${Math.min(100, (norm / max) * 100)}% - 1px)` }} />}
      </div>
    </div>
  )
}

// ---- story frame ------------------------------------------------------------------------
type Card = { key: string; title: string; body: ReactNode }

function Stories({ kind, cards, onClose }: { kind: "morning" | "evening"; cards: Card[]; onClose: () => void }) {
  const [i, setI] = useState(0)
  const touch = useRef<{ x: number; y: number } | null>(null)
  const go = useCallback((d: number) => setI((x) => Math.max(0, Math.min(cards.length - 1, x + d))), [cards.length])
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1); else if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", key)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => { window.removeEventListener("keydown", key); document.body.style.overflow = prev }
  }, [go, onClose])
  const bg = kind === "morning"
    ? "radial-gradient(120% 70% at 85% -10%, rgb(255 190 110 / .30), transparent 60%), radial-gradient(90% 60% at 0% 110%, rgb(108 230 211 / .16), transparent 60%), #071313"
    : "radial-gradient(120% 70% at 85% -10%, rgb(138 149 255 / .32), transparent 60%), radial-gradient(90% 60% at 0% 110%, rgb(192 132 252 / .14), transparent 60%), #060b14"
  const tap = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button, a, [data-no-tap]")) return
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    go(e.clientX - r.left < r.width * 0.3 ? -1 : 1)
  }
  const c = cards[i]
  return createPortal(
    <div className="fixed inset-0 z-[200] flex justify-center bg-black/70" role="dialog" aria-modal="true" aria-label={kind === "morning" ? "Ranní report" : "Večerní report"} data-testid="report-stories">
      <div className="relative flex h-full w-full max-w-[480px] flex-col overflow-hidden text-fg" style={{ background: bg }}
        onClick={tap}
        onTouchStart={(e) => { touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY } }}
        onTouchEnd={(e) => {
          const t = touch.current; touch.current = null
          if (!t) return
          const dx = e.changedTouches[0].clientX - t.x, dy = e.changedTouches[0].clientY - t.y
          if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) { e.preventDefault(); go(dx < 0 ? 1 : -1) }
        }}>
        <div className="flex gap-1 px-4 pt-[max(12px,env(safe-area-inset-top))]">
          {cards.map((x, k) => <i key={x.key} className="h-[3px] flex-1 overflow-hidden rounded-full bg-white/15"><b className="block h-full rounded-full bg-fg transition-all duration-300" style={{ width: k <= i ? "100%" : "0%" }} /></i>)}
        </div>
        <div className="flex items-center justify-between px-4 pt-3">
          <span className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[.14em] text-fg-2">
            {kind === "morning" ? <Sun className="size-4 text-watch" aria-hidden /> : <Moon className="size-4 text-load" aria-hidden />}
            {kind === "morning" ? "Ranní report" : "Večerní report"} · {c.title}
          </span>
          <button type="button" onClick={onClose} aria-label="Zavřít report" className="grid size-9 place-items-center rounded-full bg-white/10 text-fg" data-testid="report-close"><X className="size-4" aria-hidden /></button>
        </div>
        <div key={c.key} className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 pt-4 animate-[careReveal_.3s_ease-out]" data-testid={`report-card-${c.key}`}>
          {c.body}
        </div>
        <div className="flex items-center justify-between px-5 pb-[max(14px,env(safe-area-inset-bottom))] text-[11px] text-fg-3">
          <span>{i + 1} / {cards.length}</span>
          {i < cards.length - 1 ? <button type="button" onClick={() => go(1)} className="flex items-center gap-1 font-bold text-fg-2" data-testid="report-next">Další<ChevronRight className="size-3.5" aria-hidden /></button>
            : <button type="button" onClick={onClose} className="font-bold text-fg-2">Hotovo</button>}
        </div>
      </div>
    </div>,
    document.body,
  )
}

const Big = ({ children }: { children: ReactNode }) => <p className="font-serif text-[30px] leading-[1.1] tracking-[-.02em] text-fg">{children}</p>
const Sub = ({ children }: { children: ReactNode }) => <p className="mt-2 text-[14px] leading-6 text-fg-soft">{children}</p>
const Panel = ({ children, className = "" }: { children: ReactNode; className?: string }) => <div className={`mt-4 rounded-[18px] border border-white/[.08] bg-white/[.04] p-3.5 ${className}`}>{children}</div>
const Lbl = ({ children }: { children: ReactNode }) => <p className="text-[11px] font-bold uppercase tracking-[.12em] text-fg-3">{children}</p>

function Questions({ qs, onAsk }: { qs: string[]; onAsk: (q: string) => void }) {
  return (
    <div className="mt-4 grid gap-2" data-testid="report-questions">
      {qs.map((q) => (
        <button key={q} type="button" onClick={() => onAsk(q)}
          className="flex items-center gap-2.5 rounded-[14px] border border-white/10 bg-white/[.05] px-3.5 py-3 text-left text-[14px] font-semibold text-fg transition hover:border-accent/50">
          <MessageCircle className="size-4 shrink-0 text-accent" aria-hidden />{q}
        </button>
      ))}
    </div>
  )
}

// ---- the day from morning to night ---------------------------------------------------------
// Owner request 2026-10-03 (v2): one shared time axis, two panels (never two y-scales): the
// energy reserve on top, below it the day's states as lanes — position carries the state, the
// colour only repeats it (palette checked for colour-blind separation of neighbouring lanes).
// Tap / drag reads the moment: time, state, heart rate, energy.
const LANES: { st: number[]; label: string; col: string }[] = [
  { st: [6], label: "Trénink", col: "#b08a22" },
  { st: [5], label: "Pohyb", col: "#2c8cc6" },
  { st: [2, 3], label: "Zvýšený tep", col: "#d4643c" },
  { st: [1, 4], label: "Klid", col: "#2f9a6e" },
  { st: [0], label: "Spánek", col: "#6476e6" },
]
const STATE_NAME = ["spánek", "klid", "mírně zvýšený tep v klidu", "výrazně zvýšený tep v klidu", "lehký pohyb", "pohyb", "trénink"]

type Curve = { label: string; sub: string; data: [number, number][]; col: string; unit?: string; lo?: number }

export function DayTimeline({ v, until, compact = false, curve }: { v: any; until?: number | null; compact?: boolean; curve?: Curve }) {
  const tl: [number, number, number, number, number][] = v?.timeline || []
  const cv: Curve = curve || { label: "Energie", sub: "0–100", data: v?.energy || [], col: C.accent, lo: 0 }
  const en: [number, number][] = cv.data
  const lo = cv.lo ?? 0
  const [pick, setPick] = useState<number | null>(null)
  const ref = useRef<SVGSVGElement>(null)
  if (!tl.length) return null
  const W = 340, L = curve ? 76 : 64, R = 8, ew = compact ? 0 : 74, laneH = compact ? 9 : 12, gap = 3
  const top = compact ? 4 : 10, eTop = top, eBot = top + ew, lTop = eBot + (compact ? 0 : 12)
  const H = lTop + LANES.length * (laneH + gap) + 18
  const x = (m: number) => L + (m / 1440) * (W - L - R)
  const ey = (e: number) => eBot - (Math.max(0, e - lo) / (100 - lo)) * (ew - 6)
  const area = en.length > 1 ? `M${x(en[0][0])} ${eBot} ` + en.map(([m, e]) => `L${x(m).toFixed(1)} ${ey(e).toFixed(1)}`).join(" ") + ` L${x(en[en.length - 1][0])} ${eBot} Z` : ""
  const line = en.map(([m, e], i) => `${i ? "L" : "M"}${x(m).toFixed(1)} ${ey(e).toFixed(1)}`).join(" ")
  const at = pick == null ? null : tl.reduce((b, t) => (Math.abs(t[0] + 7.5 - pick) < Math.abs(b[0] + 7.5 - pick) ? t : b), tl[0])
  const eAt = pick == null || !en.length ? null : en.reduce((b, t) => (Math.abs(t[0] - pick) < Math.abs(b[0] - pick) ? t : b), en[0])
  const move = (e: React.PointerEvent) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    const px = ((e.clientX - box.left) / box.width) * W
    if (px < L) return setPick(null)
    setPick(Math.max(0, Math.min(1439, ((px - L) / (W - L - R)) * 1440)))
  }
  return (
    <div className="relative" data-no-tap>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full touch-none select-none" role="img" aria-label="Průběh dne" data-testid="day-timeline"
        onPointerDown={move} onPointerMove={(e) => (e.buttons || e.pointerType === "mouse") && move(e)} onPointerLeave={() => setPick(null)}>
        {/* hours */}
        {[0, 6, 12, 18, 24].map((h) => (
          <g key={h}>
            <line x1={x(h * 60)} x2={x(h * 60)} y1={top} y2={H - 16} stroke="rgb(255 255 255 / .06)" />
            <text x={x(h * 60)} y={H - 3} fontSize="9.5" fill={C.fg3} textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>{h}:00</text>
          </g>
        ))}
        {!compact && (
          <g>
            <text x={L - 8} y={eTop + 10} fontSize="10" fill={C.fg2} textAnchor="end" fontWeight="700">{cv.label}</text>
            <text x={L - 8} y={eTop + 22} fontSize="9" fill={C.fg3} textAnchor="end">{cv.sub}</text>
            <line x1={L} x2={W - R} y1={eBot} y2={eBot} stroke="rgb(255 255 255 / .12)" />
            {area && <path d={area} fill={cv.col} opacity={0.12} />}
            {line && <path d={line} fill="none" stroke={cv.col} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
            {en.length > 0 && (() => { const [m, e] = en[en.length - 1]; return <g><circle cx={x(m)} cy={ey(e)} r={4} fill={cv.col} stroke="#0c201d" strokeWidth={2} /><text x={Math.min(W - R - 2, x(m) + 6)} y={ey(e) - 6} fontSize="10.5" fontWeight="800" fill={C.fg} textAnchor={x(m) > W - 40 ? "end" : "start"}>{e}{cv.unit || ""}</text></g> })()}
          </g>
        )}
        {/* lanes */}
        {LANES.map((ln, i) => {
          const y = lTop + i * (laneH + gap)
          return (
            <g key={ln.label}>
              <text x={L - 8} y={y + laneH - 2} fontSize={compact ? 8.5 : 9.5} fill={C.fg2} textAnchor="end">{ln.label}</text>
              <rect x={L} y={y} width={W - L - R} height={laneH} rx={3} fill="rgb(255 255 255 / .035)" />
              {tl.filter((t) => ln.st.includes(t[2])).map((t) => (
                <rect key={t[0]} x={x(t[0]) + 0.3} y={y} width={Math.max(1, x(t[0] + 15) - x(t[0]) - 0.6)} height={laneH} rx={2}
                  fill={ln.col} opacity={t[2] === 2 || t[2] === 4 ? 0.5 : 1} />
              ))}
            </g>
          )
        })}
        {/* the recorded activities, named */}
        {!compact && (v.activities || []).filter((a: any) => a.from != null).map((a: any) => (
          <text key={a.id} x={x((a.from + a.to) / 2)} y={lTop - 3} fontSize="9" fontWeight="700" fill={C.fg} textAnchor="middle">{a.title.length > 14 ? a.title.slice(0, 13) + "…" : a.title}</text>
        ))}
        {until != null && <line x1={x(until)} x2={x(until)} y1={top} y2={H - 16} stroke={C.fg} strokeDasharray="2 3" opacity={0.5} />}
        {pick != null && <line x1={x(pick)} x2={x(pick)} y1={top} y2={H - 16} stroke={C.fg} strokeWidth={1} />}
      </svg>
      {at && (
        <div className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 -translate-y-[110%] whitespace-nowrap rounded-[10px] border border-white/10 bg-[#0c201d] px-2.5 py-1.5 text-[11.5px] text-fg shadow-lg" data-testid="timeline-tip">
          <b>{hmShort(at[0])}–{hmShort(at[0] + 15)}</b> · {STATE_NAME[at[2]]} · {at[1]} tepů/min{eAt ? ` · ${cv.label.toLowerCase()} ${eAt[1]}${cv.unit || ""}` : ""}
        </div>
      )}
    </div>
  )
}

// Trénink tab: today's course — readiness from waking to now (training and the day
// outside it, as the engine counts them), the states lanes and the outside-training load
// against the usual day
export function DayCourse() {
  const { boot } = useApp()
  const rid = boot?.runner?.id
  const [d, setD] = useState<any>(null)
  const computed = boot?.assessment?.computed_at
  useEffect(() => {
    if (!rid) return
    let live = true
    api.dayCourse(rid).then((x: any) => live && setD(x)).catch(() => live && setD({ available: false }))
    return () => { live = false }
  }, [rid, computed])
  const inp = boot?.assessment?.capacity?.readiness?.inputs || {}
  const dd = inp.dayData
  if (!d) return null
  const r = d.readiness
  const v = d.view
  const collecting = dd && dd.days < dd.need
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="day-course">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Váš den · připravenost a zátěž</Label><InfoDot text={MI.dayCourse} label="Váš den" /></span>
        <span className="text-[12px] text-fg-3">od probuzení do teď</span>
      </div>
      {!d.available || !r ? (
        <p className="mt-3 text-[13px] leading-5 text-fg-2">Celodenní tep z hodinek za dnešek zatím nedorazil. Po synchronizaci se tu ukáže, jak se během dne měnila připravenost a kolik zátěže přinesl den mimo trénink.</p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-2">
            <div><p className="text-[11px] text-fg-3">Ráno</p><p className="t-num text-[26px] leading-none" style={{ color: readinessCol(r.morning) }}>{r.morning}<small className="text-[13px] text-fg-3"> %</small></p></div>
            <span className="pb-1 text-fg-3">→</span>
            <div><p className="text-[11px] text-fg-3">Teď</p><p className="t-num text-[26px] leading-none" style={{ color: readinessCol(r.now) }}>{r.now}<small className="text-[13px] text-fg-3"> %</small></p></div>
            <div className="ml-auto flex flex-wrap gap-1.5 pb-0.5">
              <DropChip label="trénink" v={r.sessionDrop} col={LANES[0].col} />
              <DropChip label="den mimo trénink" v={r.dayDrop} col={LANES[2].col} />
            </div>
          </div>
          <div className="mt-3">
            <DayTimeline v={v} curve={{ label: "Připravenost", sub: "%", data: r.series.map((p: number[]) => [p[0], p[1]]), col: readinessCol(r.now), unit: " %", lo: Math.max(0, Math.min(60, Math.floor((Math.min(...r.series.map((p: number[]) => p[1])) - 10) / 10) * 10)) }} />
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2">
            <Tile label="Trénink" value={`${Math.round(v.trainingMin || 0)}′`} />
            <Tile label="Pohyb" value={`${Math.round(v.activeMin || 0)}′`} />
            <Tile label="Zvýšený tep" value={`${Math.round((v.highMin || 0) + (v.mildMin || 0))}′`} />
            <Tile label="Klid" value={`${Math.round(v.calmMin || 0)}′`} />
          </div>
          <NtVsUsual nt={r.nt} />
        </>
      )}
      {collecting && (
        <p className="mt-3 rounded-[12px] bg-white/[.04] px-3 py-2 text-[12px] leading-5 text-fg-2" data-testid="day-collecting">
          Sbírám data o vašem obvyklém dni: {dd.days} ze {dd.need} dní celodenního tepu. Do té doby se den mimo trénink do připravenosti ani do Celkové zátěže nepočítá.
        </p>
      )}
    </section>
  )
}

function DropChip({ label, v, col }: { label: string; v: number; col: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[.06] px-2.5 py-1 text-[11.5px] font-bold text-fg-2">
      <i className="size-2 rounded-full" style={{ background: col }} />{label} <b className={v > 0 ? "text-alert-soft" : "text-fg-3"}>{v > 0 ? `−${v}` : "0"}</b>
    </span>
  )
}

function NtVsUsual({ nt }: { nt: any }) {
  if (!nt || nt.today == null) return null
  const max = Math.max(1, nt.today, nt.usual || 0) * 1.15
  const over = nt.usual != null && nt.today > nt.usual
  return (
    <div className="mt-4" data-testid="nt-vs-usual">
      <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
        <span className="font-semibold text-fg-soft">Zátěž mimo trénink</span>
        <span className="tabular-nums text-fg-2"><b className="text-fg">{nt.today}</b> j.z.{nt.usual != null ? ` · obvykle ${nt.usual}` : ""}</span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-white/[.06]">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(Math.min(nt.today, nt.usual ?? nt.today) / max) * 100}%`, background: LANES[1].col }} />
        {over && <i className="absolute inset-y-0 rounded-r-full" style={{ left: `${(nt.usual / max) * 100}%`, width: `${((nt.today - nt.usual) / max) * 100}%`, background: LANES[2].col }} />}
        {nt.usual != null && <i className="absolute -top-1 h-[18px] w-0.5 bg-fg" style={{ left: `calc(${(nt.usual / max) * 100}% - 1px)` }} />}
      </div>
      <p className="mt-1.5 text-[11.5px] leading-[17px] text-fg-3">
        {nt.usual == null ? "Obvyklý den se teprve učím." : over ? `Nad obvyklý den +${nt.excess} j.z. — to se počítá do Celkové zátěže a snižuje připravenost.` : "V rámci obvyklého dne — připravenost ani Celkovou zátěž to nemění."}
      </p>
    </div>
  )
}

function Tile({ label, value, sub, col }: { label: string; value: ReactNode; sub?: ReactNode; col?: string }) {
  return (
    <div className="rounded-[14px] bg-white/[.05] px-2.5 py-2.5 text-center">
      <p className="text-[10.5px] text-fg-3">{label}</p>
      <p className="t-num mt-0.5 text-[20px] leading-tight" style={col ? { color: col } : undefined}>{value}</p>
      {sub && <p className="mt-0.5 text-[10.5px] leading-[13px] text-fg-3">{sub}</p>}
    </div>
  )
}

// a model-written (validated) or rule-based rating + tip on every card
function AiNote({ text, ai, pending }: { text?: string; ai: boolean; pending: boolean }) {
  if (!text) return null
  return (
    <div className="mt-4 rounded-[16px] border border-accent/25 bg-accent/[.06] p-3" data-testid="ai-note">
      <p className="flex items-center gap-1.5 text-[10.5px] font-extrabold uppercase tracking-[.12em] text-accent">
        <Sparkles className="size-3.5" aria-hidden />{ai ? "Hodnocení AI" : "Hodnocení"}
        {pending && <span className="ml-1 font-semibold normal-case tracking-normal text-fg-3">· AI ho ještě upřesňuje…</span>}
      </p>
      <p key={text} className="mt-1 text-[13.5px] leading-[21px] text-fg animate-[careReveal_.3s_ease-out]">{text}</p>
    </div>
  )
}

function StackBars({ days }: { days: any[] }) {
  // all-sport load per day: training (solid) + outside training above the usual day (light),
  // one scale; the run kilometres written under each day
  const max = Math.max(1, ...days.map((d) => (d.train || 0) + (d.nt || 0)))
  const H = 92
  return (
    <div>
      <div className="flex items-end gap-1.5" style={{ height: H }}>
        {days.map((d) => {
          const t = d.train || 0, n = d.nt || 0
          return (
            <div key={d.date} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-[2px]" style={{ height: H }} title={`${d.wd}: trénink ${t}, mimo trénink ${n} j.z.`}>
              <span className="mb-0.5 text-[10px] tabular-nums text-fg-3">{t + n ? Math.round(t + n) : ""}</span>
              {n > 0 && <i className="block w-full rounded-t-[4px]" style={{ height: (n / max) * (H - 16), background: "#2c8cc6", opacity: 0.55 }} />}
              <i className={`block w-full ${n > 0 ? "" : "rounded-t-[4px]"}`} style={{ height: Math.max(t ? 3 : 0, (t / max) * (H - 16)), background: d.today ? C.accent : "#b08a22", outline: d.today ? `2px solid ${C.fg}` : undefined, outlineOffset: 1 }} />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex gap-1.5">{days.map((d) => (
        <span key={d.date} className={`flex-1 text-center text-[10.5px] leading-tight ${d.today ? "font-bold text-fg" : "text-fg-3"}`}>{d.wd}{d.km ? <span className="block text-[9.5px] text-fg-3">{num(d.km)} km</span> : <span className="block text-[9.5px]">&nbsp;</span>}</span>
      ))}</div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-3">
        <span className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: "#b08a22" }} />trénink</span>
        <span className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: "#2c8cc6", opacity: 0.55 }} />mimo trénink nad obvyklý den</span>
        <span>j.z. = tep × čas</span>
      </div>
    </div>
  )
}

const LEVEL_COL: Record<string, string> = { alert: C.alert, watch: C.watch, info: C.info }
const LEVEL_ICON: Record<string, any> = { alert: TriangleAlert, watch: Eye, info: Info }

// ---- morning ------------------------------------------------------------------------------
type Ctx = { onAsk: (q: string) => void; hasAssistant: boolean; notes: Record<string, string>; ai: boolean; pending: boolean }
const note = (c: Ctx, k: string) => <AiNote text={c.notes[k]} ai={c.ai} pending={c.pending} />

function morningCards(r: any, c: Ctx): Card[] {
  const n = r.night, rec = r.recovery || {}, p = r.plan || {}, sl = r.sleep || {}
  const scores: any[] = sl.scores || []
  const last = scores[scores.length - 1] || {}
  const km = p.km && typeof p.km === "object" ? p.km : null
  const cards: Card[] = [{
    key: "intro", title: "Úvod", body: (
      <div className="flex h-full flex-col justify-center">
        <Sunrise />
        <p className="mt-5 text-[13px] font-semibold text-fg-2">{fmtDay(r.date)}</p>
        <Big>{r.greeting}</Big>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Tile label="Připravenost" value={rec.score != null ? `${rec.score} %` : "—"} col={goodCol(rec.score)} sub={rec.yesterday != null && rec.score != null ? `včera ${rec.yesterday} %` : undefined} />
          <Tile label="Spánek" value={n?.hours != null ? `${num(n.hours)} h` : "—"} sub={last.score != null ? `skóre ${last.score}` : undefined} />
          <Tile label="Dnes" value={<span className="text-[15px]">{p.label || "—"}</span>} sub={km && km.hi > 0 ? `${num(km.lo)}–${num(km.hi)} km` : undefined} />
        </div>
        {note(c, "intro")}
      </div>
    ),
  }]
  cards.push({
    key: "sleep", title: "Spánek", body: !n ? <><Big>Noc zatím chybí</Big>{note(c, "sleep")}</> : (
      <>
        <div className="flex items-center gap-4">
          <Ring value={last.score} col={goodCol(last.score)}>
            <b className="t-num block text-[26px] leading-none">{last.score ?? "—"}</b><span className="text-[10px] text-fg-3">skóre spánku</span>
          </Ring>
          <div className="min-w-0">
            <Big>{`${num(n.hours)} h`}</Big>
            <p className="mt-1 text-[12.5px] text-fg-2">{n.start && n.end ? `${n.start} – ${n.end}` : ""}{n.awakeCount != null ? ` · ${n.awakeCount}× probuzení` : ""}</p>
            <p className="text-[12px] text-fg-3">{`potřeba ${num(n.need)} h · obvykle ${num(n.norm?.h)} h`}</p>
          </div>
        </div>
        {note(c, "sleep")}
        {n.hypnogram?.length ? (
          <Panel>
            <Lbl>Průběh noci</Lbl>
            <div className="mt-2 grid grid-cols-[46px_1fr] gap-1">
              <div className="grid grid-rows-4 pt-[3px] text-[10.5px] text-fg-3" style={{ height: 112 }}>{["awake", "rem", "light", "deep"].map((s) => <span key={s} className="flex items-center">{STAGE_LABEL[s]}</span>)}</div>
              <Hypnogram hyp={n.hypnogram} start={n.start} />
            </div>
          </Panel>
        ) : null}
        {last.parts?.length ? (
          <Panel className="space-y-2">
            <Lbl>Z čeho se skóre skládá</Lbl>
            {last.parts.map((pt: any) => (
              <div key={pt.label}>
                <div className="flex justify-between text-[12px]"><span className="text-fg-2">{pt.label}</span><span className="tabular-nums text-fg-3"><b className="text-fg">{num(pt.pts, 0)}</b> / {pt.max}</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-white/[.07]"><i className="block h-full rounded-full" style={{ width: `${(pt.pts / pt.max) * 100}%`, background: pt.pts / pt.max >= 0.8 ? C.ok : pt.pts / pt.max >= 0.5 ? C.watch : C.alert }} /></div>
              </div>
            ))}
          </Panel>
        ) : null}
        <Panel>
          <Lbl>Posledních 7 nocí · hodiny a skóre</Lbl>
          <div className="mt-2">
            <Bars items={scores.map((x: any, k: number) => ({ label: new Date(x.d + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "short" }), v: x.h,
              col: x.score == null ? C.fg4 : x.score >= 80 ? "#6476e6" : x.score >= 60 ? C.watch : C.alert, on: k === scores.length - 1 }))}
              max={Math.max(10, ...scores.map((x: any) => x.h || 0))} ref={n.need} refLabel={`potřeba ${num(n.need)} h`} />
          </div>
          <div className="mt-1 flex gap-1.5">{scores.map((x: any) => <span key={x.d} className="flex-1 text-center text-[9.5px] tabular-nums text-fg-3">{x.score ?? ""}</span>)}</div>
        </Panel>
      </>
    ),
  })
  const night = rec.night || {}, base = rec.base || {}
  cards.push({
    key: "readiness", title: "Noc → připravenost", body: (
      <>
        <div className="flex items-center gap-4">
          <Ring value={rec.score} col={goodCol(rec.score)}>
            <b className="t-num block text-[26px] leading-none">{rec.score ?? "—"}</b><span className="text-[10px] text-fg-3">% připravenost</span>
          </Ring>
          <div>
            <Big>{rec.label ? rec.label.charAt(0).toUpperCase() + rec.label.slice(1) : "Připravenost"}</Big>
            {rec.yesterday != null && rec.score != null && <p className="mt-1 text-[12px] text-fg-3">{`včera ráno ${rec.yesterday} % (${rec.score - rec.yesterday >= 0 ? "+" : "−"}${Math.abs(rec.score - rec.yesterday)})`}</p>}
          </div>
        </div>
        {note(c, "readiness")}
        <div className="mt-4 grid grid-cols-3 gap-2">
          {([["HRV", night.hrv, base.hrv, "ms", true], ["Klidový tep", night.rhr, base.rhr, "tepů/min", false], ["Spánek", n?.hours, n?.norm?.h, "h", true]] as const).map(([l, v, b, u, up]) => {
            const d = v != null && b != null ? Math.round(((v as number) - (b as number)) * 10) / 10 : null
            const good = d == null ? null : up ? d >= 0 : d <= 0
            return <Tile key={l} label={l} value={v != null ? num(v as number) : "—"} col={good == null ? undefined : good ? C.ok : C.watch}
              sub={d != null ? `${d > 0 ? "+" : d < 0 ? "−" : "±"}${num(Math.abs(d))} proti normě` : u} />
          })}
        </div>
        {rec.readiness && <div data-no-tap><ReadinessFactors r={rec.readiness} /></div>}
      </>
    ),
  })
  const rn = r.recent || {}
  const yv = rn.yesterday?.view
  cards.push({
    key: "recent", title: "Včera a tento týden", body: (
      <>
        <Lbl>Včera</Lbl>
        <Big>{rn.yesterday?.activities?.length ? rn.yesterday.activities.map((x: any) => x.title).join(", ") : "Bez tréninku"}</Big>
        {note(c, "recent")}
        {yv && (
          <Panel>
            <div className="flex items-baseline justify-between"><Lbl>Průběh včerejška</Lbl><span className="text-[10.5px] text-fg-3">klepnutím zobrazíte detail</span></div>
            <div className="mt-2"><DayTimeline v={yv} compact={false} /></div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <Tile label="Pohyb mimo trénink" value={`${yv.activeMin} min`} />
              <Tile label="Zvýšený tep v klidu" value={`${yv.highMin + yv.mildMin} min`} col={yv.highMin >= 30 ? C.watch : undefined} />
              <Tile label="Kroky" value={yv.steps ? num(yv.steps, 0) : "—"} />
            </div>
          </Panel>
        )}
        <Panel>
          <div className="flex items-baseline justify-between"><Lbl>Celková zátěž po dnech</Lbl><span className="text-[11px] text-fg-3">{rn.budget ? `${num(rn.weekKm || 0)} z ${num(rn.budget, 0)} km` : ""}</span></div>
          <div className="mt-2"><StackBars days={rn.week || []} /></div>
        </Panel>
        {rn.carry?.length ? (
          <Panel className="space-y-2.5">
            <Lbl>Co se ještě vstřebává</Lbl>
            {rn.carry.map((x: any) => <VsNorm key={x.ch} label={x.label} v={x.residual} unit={x.unit} col={x.share > 0.6 ? C.watch : C.info} max={x.cap} norm={null} />)}
            <p className="text-[11px] leading-4 text-fg-3">Zbytek zátěže proti týdenní kapacitě. Vstřebává se noc po noci, rychleji po dobrém spánku.</p>
          </Panel>
        ) : null}
      </>
    ),
  })
  const w: any[] = r.watch || []
  cards.push({
    key: "plan", title: "Dnešní trénink", body: (
      <>
        <Lbl>Doporučení na dnešek</Lbl>
        <Big>{p.override || p.label || "—"}</Big>
        {km && km.hi > 0 && <div className="mt-4 grid grid-cols-3 gap-2">
          <Tile label="Kilometry" value={`${num(km.lo)}–${num(km.hi)}`} />
          <Tile label="Tep" value={p.hr ? `${p.hr[0]}–${p.hr[1]}` : "—"} />
          <Tile label="Tempo" value={p.pace ? `${paceS(p.pace[0])}–${paceS(p.pace[1])}` : "—"} />
        </div>}
        {note(c, "plan")}
        <Panel>
          <Lbl>Na co si dát pozor</Lbl>
          {w.length ? (
            <ul className="mt-2 space-y-2" data-testid="watchouts">
              {w.map((x: any, i: number) => { const I = LEVEL_ICON[x.level] || Info; return (
                <li key={i} className="flex gap-2.5 text-[13px] leading-5 text-fg-soft"><I className="mt-0.5 size-4 shrink-0" style={{ color: LEVEL_COL[x.level] }} aria-hidden /><span>{x.text}</span></li>
              ) })}
            </ul>
          ) : <p className="mt-1.5 text-[13px] text-fg-2">Nic zvláštního k hlídání.</p>}
        </Panel>
        {(p.notes?.length || p.reasons?.length) ? (
          <Panel>
            <Lbl>Proč právě takhle</Lbl>
            <ul className="mt-2 space-y-1.5 text-[13px] leading-5 text-fg-soft">
              {[...(p.reasons || []), ...(p.notes || [])].slice(0, 4).map((t: string, k: number) => <li key={k} className="flex gap-2"><span className="text-accent">›</span><span>{t}</span></li>)}
            </ul>
          </Panel>
        ) : null}
        {p.strength && (
          <Panel>
            <Lbl>Posilování</Lbl>
            <p className="mt-1 text-[14px] font-bold">{p.strength.session ? `${p.strength.name}: ${p.strength.session}` : p.strength.name}</p>
            {(p.strength.blocked || p.strength.why) && <p className="mt-0.5 text-[12px] text-fg-3">{p.strength.blocked || p.strength.why}</p>}
          </Panel>
        )}
      </>
    ),
  })
  if (c.hasAssistant) cards.push({ key: "ask", title: "Otázky", body: <><Big>Chcete vědět víc?</Big><Sub>Asistent odpoví z vašich dat a citované literatury.</Sub><Questions qs={r.questions || []} onAsk={c.onAsk} /></> })
  return cards
}

// ---- evening ------------------------------------------------------------------------------
const TYPE_COL: Record<string, string> = { "dlouhý": C.load, "kvalitní": C.alert, "lehký": C.info, volno: C.fg4, "lehce / volno": C.fg4 }

function eveningCards(r: any, c: Ctx): Card[] {
  const v = r.dayView, ld = r.load || {}, w = r.week || {}, rw = r.restOfWeek || {}, t = r.tonight || {}, tm = r.tomorrow || {}
  const nowMin = (() => { const d = new Date(); return d.getHours() * 60 + d.getMinutes() })()
  const cards: Card[] = [{
    key: "intro", title: "Úvod", body: (
      <div className="flex h-full flex-col justify-center">
        <NightSky />
        <p className="mt-5 text-[13px] font-semibold text-fg-2">{fmtDay(r.date)}</p>
        <Big>{r.greeting}</Big>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Tile label="Energie teď" value={r.energyNow ?? "—"} col={goodCol(r.energyNow)} sub="ze 100" />
          <Tile label="Zátěž dne" value={ld.total != null ? num(ld.total, 0) : "—"} sub="j.z." />
          <Tile label="Na noc" value={`${num(t.target)} h`} sub={`do postele ${t.bed}`} />
        </div>
        {note(c, "intro")}
      </div>
    ),
  }]
  cards.push({
    key: "day", title: "Váš den", body: (
      <>
        <Lbl>Od rána do teď</Lbl>
        <Big>{v ? `Energie ${v.energy?.[0]?.[1] ?? "—"} → ${r.energyNow ?? "—"}` : "Průběh dne"}</Big>
        {note(c, "day")}
        {v ? (
          <>
            <Panel>
              <div className="flex items-baseline justify-between"><Lbl>Průběh dne</Lbl><span className="text-[10.5px] text-fg-3">táhněte prstem pro detail</span></div>
              <div className="mt-3"><DayTimeline v={v} until={nowMin} /></div>
            </Panel>
            <div className="mt-3 grid grid-cols-4 gap-2">
              <Tile label="Trénink" value={`${v.trainingMin}′`} />
              <Tile label="Pohyb" value={`${v.activeMin}′`} />
              <Tile label="Zvýšený tep" value={`${v.highMin + v.mildMin}′`} col={v.highMin >= 30 ? C.watch : undefined} />
              <Tile label="Klid" value={`${v.calmMin}′`} />
            </div>
            {v.stepsHourly?.length ? (
              <Panel>
                <Lbl>Kroky po hodinách{v.steps ? ` · ${num(v.steps, 0)}` : ""}</Lbl>
                <div className="mt-2 flex h-12 items-end gap-[2px]">
                  {Array.from({ length: 24 }, (_, h) => { const n = (v.stepsHourly.find((x: any) => x[0] === h) || [0, 0])[1]; const mx = Math.max(1, ...v.stepsHourly.map((x: any) => x[1])); return (
                    <i key={h} className="block flex-1 rounded-t-[2px]" title={`${h}:00 · ${n} kroků`} style={{ height: `${Math.max(n ? 6 : 2, (n / mx) * 100)}%`, background: n ? "#2c8cc6" : "rgb(255 255 255 / .06)" }} />
                  ) })}
                </div>
                <div className="mt-1 flex justify-between text-[9.5px] text-fg-3"><span>0:00</span><span>12:00</span><span>23:00</span></div>
              </Panel>
            ) : null}
          </>
        ) : <Sub>Celodenní tep z hodinek zatím nedorazil. Po synchronizaci se průběh doplní.</Sub>}
      </>
    ),
  })
  const tot = Math.max(1, (ld.train || 0) + (ld.nt || 0), ld.usualNt || 0)
  cards.push({
    key: "load", title: "Zátěž dne", body: (
      <>
        <Lbl>Celková zátěž dne</Lbl>
        <Big>{ld.total != null ? `${num(ld.total, 0)} j.z.` : "—"}</Big>
        {note(c, "load")}
        <Panel>
          <div className="flex h-5 overflow-hidden rounded-full bg-white/[.06]" data-testid="load-split">
            {ld.train ? <i style={{ width: `${(ld.train / tot) * 100}%`, background: "#b08a22" }} title={`trénink ${ld.train}`} /> : null}
            {ld.nt ? <i style={{ width: `${(ld.nt / tot) * 100}%`, background: "#2c8cc6", marginLeft: 2 }} title={`mimo trénink ${ld.nt}`} /> : null}
          </div>
          <div className="mt-2 flex flex-wrap justify-between gap-2 text-[12px]">
            <span className="flex items-center gap-1.5 text-fg-2"><i className="size-2.5 rounded-sm" style={{ background: "#b08a22" }} />trénink <b className="text-fg">{num(ld.train || 0, 0)}</b></span>
            <span className="flex items-center gap-1.5 text-fg-2"><i className="size-2.5 rounded-sm" style={{ background: "#2c8cc6" }} />mimo trénink <b className="text-fg">{num(ld.nt || 0, 0)}</b>{ld.usualNt != null ? <span className="text-fg-3">{` (obvykle ${num(ld.usualNt, 0)})`}</span> : null}</span>
          </div>
          <p className="mt-2 text-[11px] leading-4 text-fg-3">Mimo trénink se počítá chůze a pohyb s tepem nad 25 % tepové rezervy, poloviční vahou. Do Celkové zátěže jde jen to, co je nad vaším obvyklým dnem.</p>
        </Panel>
        {ld.channels?.length ? (
          <Panel className="space-y-2">
            <Lbl>Dnes odvedeno · dnes ještě smíte</Lbl>
            {ld.channels.filter((x: any) => x.doneToday != null).map((x: any) => (
              <div key={x.ch} className="flex items-baseline justify-between text-[13px]">
                <span className="text-fg-2">{x.label}</span>
                <span className="tabular-nums text-fg-3"><b className="text-fg">{num(x.doneToday, x.ch === "volume" ? 1 : 0)}</b>{` ${x.unit}${x.left != null ? ` · ještě ${num(x.left, x.ch === "volume" ? 1 : 0)}` : ""}`}</span>
              </div>
            ))}
          </Panel>
        ) : null}
      </>
    ),
  })
  const eff: any[] = tm.effects || []
  cards.push({
    key: "tomorrow", title: "Co ovlivní zítřek", body: (
      <>
        <Lbl>Zítřek</Lbl>
        <Big>{tm.plan ? `${tm.plan.wd}: ${tm.plan.type}${tm.plan.km ? ` ≈ ${num(tm.plan.km)} km` : ""}` : "Co ovlivní zítřek"}</Big>
        {note(c, "tomorrow")}
        <Panel>
          <ul className="space-y-2.5" data-testid="tomorrow-effects">
            {eff.map((e, i) => (
              <li key={i} className="flex gap-2.5 text-[13px] leading-5 text-fg-soft">
                <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[12px] font-extrabold" style={{ background: `${e.dir < 0 ? C.alert : e.dir > 0 ? C.ok : C.fg3}26`, color: e.dir < 0 ? C.alert : e.dir > 0 ? C.ok : C.fg2 }}>{e.dir < 0 ? "↓" : e.dir > 0 ? "↑" : "→"}</span>
                <span>{e.text}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-4 text-fg-3">↓ zítřejší připravenost a kapacitu spíš sníží · ↑ spíš pomůže · → plán. Ráno to přesně ukáže noc.</p>
        </Panel>
      </>
    ),
  })
  const days: any[] = w.days || []
  const planned: Record<string, any> = Object.fromEntries((rw.days || []).map((x: any) => [x.date, x]))
  const maxKm = Math.max(10, ...days.map((x) => Math.max(x.km || 0, planned[x.date]?.km || 0)))
  cards.push({
    key: "week", title: "Týden", body: (
      <>
        <Lbl>Tento týden</Lbl>
        <Big>{w.budget ? `${num(w.done || 0)} z ${num(w.budget, 0)} km` : `${num(w.done || 0)} km`}</Big>
        {note(c, "week")}
        <Panel>
          <Bars max={maxKm} items={days.map((x) => {
            const pl = planned[x.date]
            return x.past || x.today ? { label: x.wd, v: x.km || (x.other?.length ? 0.01 : null), col: x.today ? C.accent : C.info, on: x.today }
              : { label: x.wd, v: pl?.km ?? null, col: TYPE_COL[pl?.type] || C.fg4, hatch: true }
          })} />
          <p className="mt-2 text-[11px] text-fg-3">Plné: odběhnuto · šrafované: návrh na zbytek týdne.</p>
        </Panel>
        <Panel>
          <Lbl>Zbytek týdne</Lbl>
          {rw.note && <p className="mt-1 text-[13px] text-fg-2">{rw.note}</p>}
          <div className="mt-1 divide-y divide-white/[.06]">
            {(rw.days || []).map((x: any) => (
              <div key={x.date} className="flex items-center justify-between py-2 text-[13px]">
                <span className="flex items-center gap-2"><b className="w-6 text-fg-2">{x.wd}</b><i className="size-2 rounded-full" style={{ background: TYPE_COL[x.type] || C.fg4 }} /><span className="text-fg">{x.type}</span></span>
                <span className="tabular-nums text-fg-2">{x.km ? `≈ ${num(x.km)} km` : ""}</span>
              </div>
            ))}
          </div>
        </Panel>
      </>
    ),
  })
  cards.push({
    key: "tonight", title: "Na noc", body: (
      <>
        <Lbl>Dnešní noc</Lbl>
        <Big>{`${hm((t.target || 8) * 60)} spánku`}</Big>
        {note(c, "tonight")}
        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Bed className="mx-auto size-5 text-load" aria-hidden /><p className="t-num mt-1 text-[22px]">{t.bed}</p><p className="text-[10.5px] text-fg-3">do postele</p></div>
          <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Sun className="mx-auto size-5 text-watch" aria-hidden /><p className="t-num mt-1 text-[22px]">{t.wake}</p><p className="text-[10.5px] text-fg-3">{t.wakeFromWatch ? "obvyklé vstávání" : "vstávání"}</p></div>
          <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Coffee className="mx-auto size-5 text-fg-2" aria-hidden /><p className="t-num mt-1 text-[22px]">{t.caffeine}</p><p className="text-[10.5px] text-fg-3">poslední káva</p></div>
        </div>
        <Panel>
          <ul className="space-y-1.5 text-[13px] leading-5 text-fg-soft">
            <li className="flex gap-2"><span className="text-load">›</span><span>Sportovcům se doporučuje 7–9 hodin spánku, při náročném tréninku spíš víc (Walsh et al., 2021).</span></li>
            <li className="flex gap-2"><span className="text-load">›</span><span>Kofein ještě 6 hodin před spaním zkracuje a zhoršuje spánek (Drake et al., 2013).</span></li>
            <li className="flex gap-2"><span className="text-load">›</span><span>Hodinu před spaním ztlumit světlo a obrazovky, v ložnici chladno a tma.</span></li>
          </ul>
        </Panel>
      </>
    ),
  })
  if (c.hasAssistant) cards.push({ key: "ask", title: "Otázky", body: <><Big>Chcete se na něco zeptat?</Big><Sub>Asistent odpoví z vašich dat a citované literatury.</Sub><Questions qs={r.questions || []} onAsk={c.onAsk} /></> })
  return cards
}

// ---- illustrations (own SVG) ----------------------------------------------------------------
function Sunrise() {
  return (
    <svg viewBox="0 0 240 120" className="w-[220px]" aria-hidden>
      <defs>
        <radialGradient id="sun" cx="50%" cy="50%" r="50%"><stop offset="0" stopColor="#ffe8a3" /><stop offset=".6" stopColor="#ffbe6e" /><stop offset="1" stopColor="#ff9a5a" stopOpacity="0" /></radialGradient>
      </defs>
      <circle cx="120" cy="92" r="70" fill="url(#sun)" opacity=".55" />
      <circle cx="120" cy="92" r="34" fill="#ffd27a" />
      {Array.from({ length: 9 }, (_, k) => { const a = Math.PI * (k / 8); return <line key={k} x1={120 - Math.cos(a) * 46} y1={92 - Math.sin(a) * 46} x2={120 - Math.cos(a) * 58} y2={92 - Math.sin(a) * 58} stroke="#ffd27a" strokeWidth="3.5" strokeLinecap="round" opacity=".8" /> })}
      <path d="M0 96 Q60 78 120 92 T240 88 V120 H0Z" fill="#0c201d" />
      <path d="M0 106 Q70 92 140 104 T240 100 V120 H0Z" fill="#071313" />
    </svg>
  )
}
function NightSky() {
  const stars = useMemo(() => Array.from({ length: 22 }, (_, k) => [(k * 53) % 240, (k * 37) % 90, 0.6 + ((k * 7) % 10) / 10]), [])
  return (
    <svg viewBox="0 0 240 120" className="w-[220px]" aria-hidden>
      {stars.map(([x, y, r], k) => <circle key={k} cx={x} cy={y} r={r} fill="#eef6f2" opacity={0.35 + (k % 4) * 0.15} />)}
      <circle cx="150" cy="52" r="30" fill="#e8e6ff" />
      <circle cx="164" cy="44" r="27" fill="#0b1020" />
      <path d="M0 98 Q60 84 120 96 T240 92 V120 H0Z" fill="#101a2c" />
      <path d="M0 108 Q70 96 140 106 T240 102 V120 H0Z" fill="#060b14" />
    </svg>
  )
}

// ---- when a report is offered -------------------------------------------------------------
// Owner request 2026-10-03: the report pops up when the app is opened (once a day per
// report, remembered on this device), the morning one from 6:00 to 10:00 once the night
// is synced, the evening one from 20:00 to midnight. Once closed it stays available as a
// small icon next to the state on Dnes until its window ends.
type Kind = "morning" | "evening"
export const reportWindow = (d: Date): Kind | null => {
  const h = d.getHours()
  return h >= 6 && h < 10 ? "morning" : h >= 20 ? "evening" : null
}
const seenKey = (rid: string, day: string, k: Kind) => `dl-report-seen:${rid}:${day}:${k}`
const wasSeen = (key: string) => { try { return !!localStorage.getItem(key) } catch { return false } }
const markSeen = (key: string) => { try { localStorage.setItem(key, "1") } catch { /* private mode */ } }

type ReportApi = { kind: Kind | null; open: () => void }
const ReportCtx = createContext<ReportApi>({ kind: null, open: () => {} })
export const useReport = () => useContext(ReportCtx)

export function ReportProvider({ children }: { children: ReactNode }) {
  const { me, boot, viewing, touring, refresh } = useApp()
  const rid = (viewing || touring) ? undefined : (me?.runner_id as string | undefined)
  const { available, open: ask } = useAssistant()
  const [now, setNow] = useState(() => new Date())
  const [rep, setRep] = useState<{ kind: Kind; day: string; data: any } | null>(null)
  const [show, setShow] = useState(false)
  const stamp = boot?.assessment?.computed_at          // a sync recomputes it → the night may have arrived
  // re-check the window every minute and whenever the app comes back to the front
  useEffect(() => {
    const tick = () => setNow(new Date())
    const t = setInterval(tick, 60_000)
    const vis = () => { if (document.visibilityState === "visible") tick() }
    document.addEventListener("visibilitychange", vis)
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", vis) }
  }, [])
  // owner request 2026-10-03: the watch's data is pulled when the app is opened (at most every
  // 30 minutes), so the reports and the day's load are current without the sync button
  useEffect(() => {
    if (!rid) return
    let alive = true
    api.garminStatus().then(async (st: any) => {
      if (!alive || !st?.connected || st.last_error) return
      const age = st.last_sync_at ? Date.now() - new Date(st.last_sync_at).getTime() : Infinity
      if (age < 30 * 60_000) return
      try { await api.garminSync(); if (alive) await refresh() } catch { /* the Dnes sync button reports errors */ }
    }).catch(() => {})
    return () => { alive = false }
  }, [rid]) // eslint-disable-line react-hooks/exhaustive-deps
  const kind = reportWindow(now)
  const day = now.toLocaleDateString("sv-SE")
  useEffect(() => {
    if (!rid || !kind) { setRep(null); setShow(false); return }
    let alive = true
    api.report(rid, kind).then((r: any) => {
      if (!alive) return
      // the morning report waits for the synced night
      if (kind === "morning" && !r?.night) { setRep(null); return }
      setRep({ kind, day, data: r })
      if (!wasSeen(seenKey(rid, day, kind))) { setShow(true); markSeen(seenKey(rid, day, kind)) }
    }).catch(() => alive && setRep(null))
    return () => { alive = false }
  }, [rid, kind, day, stamp])
  // the model-written sentences come after the report (validated on the server; the rule-based ones meanwhile)
  const [ai, setAi] = useState<{ key: string; notes: Record<string, string>; source: string } | null>(null)
  const repKey = rep ? `${rep.kind}:${rep.day}:${rep.data?.generatedAt}` : ""
  useEffect(() => {
    if (!rid || !rep || !rep.data?.aiPending) return
    let alive = true
    api.reportAi(rid, rep.kind).then((x: any) => alive && setAi({ key: repKey, notes: x.notes || {}, source: x.source })).catch(() => {})
    return () => { alive = false }
  }, [rid, repKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const value = useMemo<ReportApi>(() => ({ kind: rep ? rep.kind : null, open: () => setShow(true) }), [rep])
  const onAsk = (q: string) => { setShow(false); setTimeout(() => ask(q), 50) }
  const aiNow = ai && ai.key === repKey ? ai : null
  const ctx = rep ? { onAsk, hasAssistant: available, notes: { ...(rep.data?.notes || {}), ...(aiNow?.notes || {}) },
    ai: aiNow ? aiNow.source === "ai" : !rep.data?.aiPending, pending: !!rep.data?.aiPending && !aiNow } : null
  const cards = show && rep && ctx ? (rep.kind === "morning" ? morningCards(rep.data, ctx) : eveningCards(rep.data, ctx)) : null
  return (
    <ReportCtx.Provider value={value}>
      {children}
      {cards && rep && <Stories kind={rep.kind} cards={cards} onClose={() => setShow(false)} />}
    </ReportCtx.Provider>
  )
}

/** The small icon next to the state on Dnes while a report is available. */
export function ReportIcon() {
  const { kind, open } = useReport()
  if (!kind) return null
  const morning = kind === "morning"
  return (
    <button type="button" onClick={open} data-testid="report-icon" aria-label={morning ? "Ranní report" : "Večerní report"} title={morning ? "Ranní report" : "Večerní report"}
      className="relative inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[12px] font-extrabold transition"
      style={morning ? { background: "rgb(255 210 122 / .16)", color: C.watch, boxShadow: "inset 0 0 0 1px rgb(255 210 122 / .4)" }
        : { background: "rgb(138 149 255 / .18)", color: C.load, boxShadow: "inset 0 0 0 1px rgb(138 149 255 / .45)" }}>
      {morning ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
    </button>
  )
}
