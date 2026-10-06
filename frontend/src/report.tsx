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
import { ReadinessFactors } from "@/capacity"
import { ExerciseFigure } from "@/exfigure"
import { Bed, Bike, Bookmark, BookmarkCheck, Check, ChevronRight, Coffee, Dumbbell, Eye, Flag, Info, MessageCircle, Moon, Play, Sparkles, Sun, TriangleAlert, X } from "lucide-react"
import { useNavigate } from "react-router"
import { CARE_SUB_EVENT } from "@/onboarding"

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

// railway#197 — every stage with its time over the night; a finger on the chart picks
// one phase and shows when it ran and how long
function Hypnogram({ hyp, start, stages }: { hyp: [number, number, string][]; start?: string | null; stages?: Record<string, number | null> | null }) {
  const [pick, setPick] = useState<number | null>(null)
  const ref = useRef<SVGSVGElement>(null)
  const total = hyp[hyp.length - 1][1]
  const W = 340, L = 70, H = 132, top = 8, rowH = 26, x = (m: number) => L + (m / total) * (W - L)
  const s0 = toMin(start)
  const clock = (m: number) => hmShort(((s0 ?? 0) + m) % 1440)
  const ticks: number[] = []
  if (s0 != null) { for (let t = Math.ceil(s0 / 60) * 60; t < s0 + total; t += 60) ticks.push(t - s0) }
  // the watch's own totals; the hypnogram's sum where the watch sent none
  const sum = (st: string) => hyp.reduce((s, [a, b, k]) => s + (k === st ? b - a : 0), 0)
  const dur = (st: string) => stages?.[st] ?? sum(st)
  const seg = pick == null ? null : hyp.find(([a, b]) => pick >= a && pick < b) ?? null
  const move = (e: React.PointerEvent) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    const px = ((e.clientX - box.left) / box.width) * W
    setPick(px < L ? null : Math.max(0, Math.min(total - 0.01, ((px - L) / (W - L)) * total)))
  }
  return (
    <div data-no-tap>
      <div className="flex items-baseline justify-between gap-2">
        <Lbl>Průběh noci</Lbl>
        {seg ? (
          <span className="text-right text-[11.5px] text-fg" data-testid="hypnogram-tip">
            <b style={{ color: STAGE_COL[seg[2]] }}>{STAGE_LABEL[seg[2]]}</b>{` · ${s0 != null ? `${clock(seg[0])}–${clock(seg[1])}` : `${hmShort(seg[0])}–${hmShort(seg[1])} od usnutí`} · `}<b>{hm(seg[1] - seg[0])}</b>
          </span>
        ) : <span className="text-[10.5px] text-fg-3">táhněte prstem pro detail</span>}
      </div>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full touch-none select-none" role="img" aria-label="Průběh spánku přes noc" data-testid="hypnogram"
        onPointerDown={move} onPointerMove={(e) => (e.buttons || e.pointerType === "mouse") && move(e)} onPointerLeave={() => setPick(null)}>
        {Object.entries(STAGE_ROW).map(([st, row]) => (
          <g key={st}>
            <line x1={L} x2={W} y1={top + row * rowH + rowH / 2} y2={top + row * rowH + rowH / 2} stroke="rgb(255 255 255 / .05)" />
            <text x={0} y={top + row * rowH + 11} fontSize="10" fill={C.fg2}>{STAGE_LABEL[st]}</text>
            <text x={0} y={top + row * rowH + 23} fontSize="9.5" fontWeight="700" fill={C.fg}>{hm(dur(st))}</text>
          </g>
        ))}
        {hyp.map(([a, b, st], i) => (
          <rect key={i} x={x(a)} width={Math.max(0.8, x(b) - x(a))} y={top + STAGE_ROW[st] * rowH + 3} height={rowH - 6} rx={2.5} fill={STAGE_COL[st]}
            opacity={seg && seg !== hyp[i] ? 0.35 : 1} stroke={seg === hyp[i] ? C.fg : undefined} strokeWidth={seg === hyp[i] ? 1.2 : undefined} />
        ))}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top + 4 * rowH} y2={top + 4 * rowH + 4} stroke="rgb(255 255 255 / .3)" />
            <text x={x(t)} y={H - 2} textAnchor="middle" fontSize="9.5" fill={C.fg3}>{hmShort(((s0 ?? 0) + t) % 1440).replace(":00", "")}</text>
          </g>
        ))}
        {pick != null && <line x1={x(pick)} x2={x(pick)} y1={top} y2={top + 4 * rowH} stroke={C.fg} strokeWidth={1} />}
      </svg>
    </div>
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
        onTouchStart={(e) => {
          // a finger on a chart reads it (hypnogram, day timeline) — not a swipe to the next card
          touch.current = (e.target as HTMLElement).closest("[data-no-tap]") ? null : { x: e.touches[0].clientX, y: e.touches[0].clientY }
        }}
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

export function DayTimeline({ v, until, compact = false }: { v: any; until?: number | null; compact?: boolean }) {
  const tl: [number, number, number, number, number][] = v?.timeline || []
  const en: [number, number][] = v?.energy || []
  const [pick, setPick] = useState<number | null>(null)
  const ref = useRef<SVGSVGElement>(null)
  if (!tl.length) return null
  const W = 340, L = 64, R = 8, ew = compact ? 0 : 74, laneH = compact ? 9 : 12, gap = 3
  const top = compact ? 4 : 10, eTop = top, eBot = top + ew, lTop = eBot + (compact ? 0 : 12)
  const H = lTop + LANES.length * (laneH + gap) + 18
  const x = (m: number) => L + (m / 1440) * (W - L - R)
  const ey = (e: number) => eBot - (e / 100) * (ew - 6)
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
            <text x={L - 8} y={eTop + 10} fontSize="10" fill={C.fg2} textAnchor="end" fontWeight="700">Energie</text>
            <text x={L - 8} y={eTop + 22} fontSize="9" fill={C.fg3} textAnchor="end">0–100</text>
            <line x1={L} x2={W - R} y1={eBot} y2={eBot} stroke="rgb(255 255 255 / .12)" />
            {area && <path d={area} fill={C.accent} opacity={0.12} />}
            {line && <path d={line} fill="none" stroke={C.accent} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
            {en.length > 0 && (() => { const [m, e] = en[en.length - 1]; return <g><circle cx={x(m)} cy={ey(e)} r={4} fill={C.accent} stroke="#0c201d" strokeWidth={2} /><text x={Math.min(W - R - 2, x(m) + 6)} y={ey(e) - 6} fontSize="10.5" fontWeight="800" fill={C.fg} textAnchor={x(m) > W - 40 ? "end" : "start"}>{e}</text></g> })()}
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
          <b>{hmShort(at[0])}–{hmShort(at[0] + 15)}</b> · {STATE_NAME[at[2]]} · {at[1]} tepů/min{eAt ? ` · energie ${eAt[1]}` : ""}
        </div>
      )}
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
type Ctx = { onAsk: (q: string) => void; hasAssistant: boolean; notes: Record<string, string>; ai: boolean; pending: boolean
  onProgram: (key: string, go: boolean) => Promise<boolean>; rid?: string; onRefresh: () => void }
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
  // suggestion #7: the test first — its result changes today's recommendation
  if (r.tendon) cards.push({ key: "tendon", title: "Šlacha", body: <TendonCard t={r.tendon} rid={c.rid} onSaved={c.onRefresh} /> })
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
            <Hypnogram hyp={n.hypnogram} start={n.start} stages={n.stages} />
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
        {r.tagsLastNight && <LastNightTags x={r.tagsLastNight} />}
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
  if (r.weekPlan) cards.push({ key: "weekPlan", title: "Plán týdne", body: <WeekPlan p={r.weekPlan} text={c.notes.weekPlan} /> })
  if (c.hasAssistant) cards.push({ key: "ask", title: "Otázky", body: <><Big>Chcete vědět víc?</Big><Sub>Asistent odpoví z vašich dat a citované literatury.</Sub><Questions qs={r.questions || []} onAsk={c.onAsk} /></> })
  return cards
}

// ---- the week's plan (Monday morning, backend metrics/week_plan.py) ---------------------------
const PLAN_COL: Record<string, string> = { "dlouhý": C.load, "kvalitní": C.alert, "lehký": C.info, regenerace: C.ok }
const itemCol = (it: any) => (it.kind === "run" ? PLAN_COL[it.type] || C.info : it.kind === "strength" ? C.self
  : it.kind === "ride" || it.kind === "swim" ? C.watch : it.kind === "race" ? C.accent : it.kind === "done" ? C.fg2 : C.fg4)
const dayKm = (d: any) => d.items.reduce((a: number, it: any) => a + (it.kind === "run" ? it.km?.hi || 0 : it.kind === "done" ? it.km || 0 : 0), 0)
const dm = (iso: string) => { const [, m, dd] = iso.split("-"); return `${+dd}. ${+m}.` }

function itemSummary(it: any): string {
  if (it.kind === "run") return `${num(it.km?.lo)}–${num(it.km?.hi)} km${it.z4 ? ` · Z4+ ${num(it.z4.lo, 0)}–${num(it.z4.hi, 0)} min` : ""}`
  if (it.kind === "strength") return it.session || ""
  if (it.kind === "ride" || it.kind === "swim") return it.min ? `${it.min[0]}–${it.min[1]} min` : ""
  if (it.kind === "done" || it.kind === "race") return it.km ? `${num(it.km)} km` : ""
  return ""
}

function ItemDetail({ it }: { it: any }) {
  const rows: [string, ReactNode][] = []
  if (it.kind === "run") {
    if (it.session) rows.push(["Trénink", it.session])
    if (it.hr) rows.push(["Tep", `${it.hr[0]}–${it.hr[1]} tep/min${it.zones ? ` · ${it.zones}` : ""}`])
    if (it.pace) rows.push(["Tempo", `${paceS(it.pace[0])}–${paceS(it.pace[1])} /km`])
    if (it.durationMin) rows.push(["Čas", `${it.durationMin[0]}–${it.durationMin[1]} min`])
    if (it.descentMax != null) rows.push(["Klesání", `do ${num(it.descentMax, 0)} m`])
    if (it.ascentMax != null) rows.push(["Stoupání", `do ${num(it.ascentMax, 0)} m`])
  } else if (it.kind === "strength") {
    rows.push(["Program", `${it.program}${it.session ? ` · ${it.session}` : ""}`])
    rows.push(["Čas", `${it.min[0]}–${it.min[1]} min · náročnost ${it.rpe}`])
    if (it.when) rows.push(["Kdy", it.when])
  } else if (it.kind === "ride" || it.kind === "swim") {
    if (it.hr) rows.push(["Tep", `${it.hr[0]}–${it.hr[1]} tep/min${it.zones ? ` · ${it.zones}` : ""}`])
  }
  if (it.note) rows.push(["Pozn.", it.note])
  if (!rows.length) return null
  return (
    <dl className="mt-1 grid grid-cols-[64px_1fr] gap-x-2 gap-y-1 text-[12px] leading-[17px]">
      {rows.flatMap(([k, v], i) => [<dt key={`k${i}`} className="text-fg-3">{k}</dt>, <dd key={`v${i}`} className="text-fg-soft">{v}</dd>])}
    </dl>
  )
}

function PlanDay({ d }: { d: any }) {
  const [open, setOpen] = useState(!!d.today)
  const rich = d.items.some((it: any) => it.kind !== "rest" && it.kind !== "done")
  return (
    <li className={`py-2 ${d.today ? "rounded-[12px] bg-white/[.05] px-2 -mx-2" : ""}`} data-testid={`plan-day-${d.date}`}>
      <button type="button" onClick={() => rich && setOpen(!open)} aria-expanded={rich ? open : undefined} className="flex w-full items-start gap-3 text-left">
        <span className="w-9 shrink-0 pt-px">
          <b className={`block text-[13px] leading-4 ${d.today ? "text-accent" : d.past ? "text-fg-3" : "text-fg"}`}>{d.wd}</b>
          <span className="text-[10.5px] text-fg-3">{dm(d.date)}</span>
        </span>
        <span className="min-w-0 flex-1 space-y-0.5">
          {d.items.map((it: any, k: number) => (
            <span key={k} className="flex items-baseline gap-2 text-[13px] leading-[18px]">
              <i className="size-2 shrink-0 translate-y-[-1px] rounded-full" style={{ background: itemCol(it), opacity: it.optional ? 0.55 : 1 }} />
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <b className={it.kind === "rest" ? "font-semibold text-fg-3" : "text-fg"}>{it.label}</b>
                <span className="tabular-nums text-fg-2">{itemSummary(it)}</span>
              </span>
            </span>
          ))}
        </span>
        {rich && <ChevronRight className={`mt-0.5 size-4 shrink-0 text-fg-3 transition ${open ? "rotate-90" : ""}`} aria-hidden />}
      </button>
      {open && rich && (
        <div className="ml-12 mt-1 space-y-2 animate-[careReveal_.25s_ease-out]">
          {d.items.map((it: any, k: number) => <ItemDetail key={k} it={it} />)}
        </div>
      )}
    </li>
  )
}

function WeekStrip({ days }: { days: any[] }) {
  // the week at a glance: run kilometres per day (hatched = optional), strength and rides under them
  const H = 84
  const max = Math.max(1, ...days.map(dayKm))
  return (
    <div data-testid="plan-strip">
      <div className="flex items-end gap-1.5" style={{ height: H }}>
        {days.map((d) => {
          const run = d.items.find((it: any) => it.kind === "run" || it.kind === "done")
          const km = dayKm(d)
          return (
            <div key={d.date} className="flex min-w-0 flex-1 flex-col items-center justify-end" style={{ height: H }}>
              <span className="mb-1 text-[10px] tabular-nums text-fg-3">{km ? num(km, km >= 10 ? 0 : 1) : ""}</span>
              <i className="block w-full rounded-t-[5px]" style={{
                height: `${Math.max(km ? 4 : 0, (km / max) * (H - 18))}px`, background: run ? itemCol(run) : C.fg4,
                opacity: d.past ? 0.5 : 1,
                backgroundImage: run?.optional ? "repeating-linear-gradient(135deg, rgb(0 0 0 / .3) 0 3px, transparent 3px 6px)" : undefined,
                outline: d.today && km ? `2px solid ${C.fg}` : undefined, outlineOffset: 1,
              }} />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {days.map((d) => (
          <span key={d.date} className="flex min-w-0 flex-1 flex-col items-center gap-0.5">
            <span className={`text-[10.5px] ${d.today ? "font-bold text-fg" : "text-fg-3"}`}>{d.wd}</span>
            <span className="flex h-3.5 items-center gap-0.5">
              {d.items.some((it: any) => it.kind === "strength") && <Dumbbell className="size-3" style={{ color: C.self }} aria-label="posilování" />}
              {d.items.some((it: any) => it.kind === "ride" || it.kind === "swim") && <Bike className="size-3" style={{ color: C.watch }} aria-label="kolo" />}
              {d.items.some((it: any) => it.kind === "race") && <Flag className="size-3" style={{ color: C.accent }} aria-label="závod" />}
            </span>
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-3">
        {[["lehký", "lehký"], ["dlouhý", "dlouhý"], ["kvalitní", "tvrdý"]].map(([k, l]) => (
          <span key={k} className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: PLAN_COL[k] }} />{l}</span>
        ))}
      </div>
    </div>
  )
}

// planned vs the week's target, with the 7-day capacity ceiling as the edge
function PlanMeter({ label, value, target, ceil, unit, col, testid }: { label: string; value: number; target?: number | null; ceil?: number | null; unit: string; col: string; testid?: string }) {
  const top = Math.max(value, target || 0, ceil || 0) * 1.08 || 1
  const p = (v: number) => `${Math.min(100, (v / top) * 100)}%`
  return (
    <div data-testid={testid}>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="text-fg-2">{label}</span>
        <span className="tabular-nums text-fg-3"><b className="text-fg">{num(value)}</b>{target != null ? ` z cíle ${num(target)}` : ""} {unit}</span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-white/[.07]">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: p(value), background: col }} />
        {target != null && <i className="absolute -inset-y-1 w-0.5 rounded-full" style={{ left: `calc(${p(target)} - 1px)`, background: C.watch }} />}
        {ceil != null && <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${p(ceil)} - 1px)` }} />}
      </div>
      <div className="mt-1 flex gap-3 text-[10.5px] text-fg-3">
        {target != null && <span className="flex items-center gap-1"><i className="h-2.5 w-0.5 rounded-full" style={{ background: C.watch }} />cíl týdne</span>}
        {ceil != null && <span className="flex items-center gap-1"><i className="h-2.5 w-0.5 rounded-full bg-fg" />týdenní kapacita s rezervou</span>}
      </div>
    </div>
  )
}

function WeekPlan({ p, text }: { p: any; text?: string }) {
  const t = p.totals
  const days: any[] = p.days || []
  return (
    <div data-testid="week-plan">
      <Lbl>{`Plán týdne · ${dm(days[0]?.date || p.weekStart)}–${dm(days[6]?.date || p.weekStart)}`}</Lbl>
      <Big>{t ? `${num(t.km)} km · ${t.runs} ${t.runs === 1 ? "běh" : t.runs < 5 ? "běhy" : "běhů"}` : p.override || "Plán týdne"}</Big>
      <Sub>{p.headline}{t?.kmLastWeek != null ? ` · minulý týden ${num(t.kmLastWeek)} km` : ""}</Sub>
      {t && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Tile label="Tvrdé tréninky" value={`${t.hard}`} sub={`nejvýš ${t.hardCap}`} col={t.hard ? C.alert : undefined} />
          <Tile label="Posilování" value={`${t.strength}×`} sub={t.strengthTarget ? `cíl ${t.strengthTarget}×` : undefined} col={C.self} />
          <Tile label="Kolo" value={t.rides ? `${t.rides}×` : "—"} sub={t.rides ? `do ${t.rideMin} min` : "nezbývá zátěž"} col={t.rides ? C.watch : undefined} />
        </div>
      )}
      <Panel><WeekStrip days={days} /></Panel>
      <AiNote text={text} ai={false} pending={false} />
      <Panel>
        <Lbl>Den po dni</Lbl>
        <p className="mt-1 text-[11px] text-fg-3">Klepnutím na den zobrazíte tep, tempo, čas a převýšení.</p>
        <ul className="mt-1 divide-y divide-white/[.06]" data-no-tap>{days.map((d) => <PlanDay key={d.date} d={d} />)}</ul>
      </Panel>
      {t && (
        <Panel className="space-y-4">
          <PlanMeter label="Běh" value={t.km} target={t.kmBudget} ceil={t.kmCeiling7} unit="km" col={C.info} testid="plan-km" />
          {t.z4Budget != null && <PlanMeter label="Minuty v Z4+" value={t.z4} target={t.z4Budget} unit="min" col={C.alert} testid="plan-z4" />}
          {t.kmOptional ? <p className="text-[11px] text-fg-3">{`+ ${num(t.kmOptional)} km volitelný běh`}</p> : null}
        </Panel>
      )}
      {p.notes?.length > 0 && (
        <Panel>
          <Lbl>Co plán zohledňuje</Lbl>
          <ul className="mt-2 space-y-1.5 text-[13px] leading-5 text-fg-soft">
            {p.notes.map((x: string, k: number) => <li key={k} className="flex gap-2"><span className="text-accent">›</span><span>{x}</span></li>)}
          </ul>
        </Panel>
      )}
      {p.rules?.length > 0 && (
        <Panel>
          <Lbl>Pravidla plánu</Lbl>
          <ul className="mt-2 space-y-1 text-[12px] leading-[18px] text-fg-2">
            {p.rules.map((x: string, k: number) => <li key={k}>{x}</li>)}
          </ul>
        </Panel>
      )}
    </div>
  )
}

// ---- bedtime mobility (evening, backend metrics/mobility.py) -------------------------------
function MobilityEx({ x, i, done, onDone }: { x: any; i: number; done: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="py-2.5" data-testid="mobility-ex">
      <div className="flex items-start gap-3">
        <button type="button" onClick={onDone} aria-pressed={done} aria-label={done ? "Odznačit cvik" : "Cvik hotový"}
          className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border transition ${done ? "border-accent bg-accent text-ink" : "border-white/25 text-fg-3"}`}>
          {done ? <Check className="size-3.5" aria-hidden /> : <span className="text-[11px] font-bold tabular-nums">{i + 1}</span>}
        </button>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 flex-1 items-start gap-2 text-left">
          <span className="min-w-0 flex-1">
            <b className={`block text-[14px] leading-5 ${done ? "text-fg-3 line-through" : "text-fg"}`}>{x.name}</b>
            <span className="block text-[12px] tabular-nums text-fg-2">{x.dose}</span>
            {x.extraFrom && <span className="block text-[11px] text-fg-3">{`navíc z programu ${x.extraFrom}`}</span>}
            {x.careful && <span className="mt-0.5 block text-[11.5px] leading-4 text-watch">{`Bolest: ${x.careful}. Jen do velmi mírného tahu, nebo cvik vynechte.`}</span>}
          </span>
          <ChevronRight className={`mt-0.5 size-4 shrink-0 text-fg-3 transition ${open ? "rotate-90" : ""}`} aria-hidden />
        </button>
      </div>
      {open && (
        <div className="ml-9 mt-1.5 animate-[careReveal_.25s_ease-out]">
          <ol className="grid gap-1.5">
            {(x.steps?.length ? x.steps : [x.how]).map((st: string, k: number) => (
              <li key={k} className="flex gap-2 text-[12.5px] leading-[18px] text-fg-soft">
                <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-accent/15 text-[10.5px] font-bold text-accent">{k + 1}</span>
                <span>{st}</span>
              </li>
            ))}
          </ol>
          {x.caution && <p className="mt-1.5 rounded-[10px] bg-watch/10 px-2.5 py-1.5 text-[11.5px] leading-4 text-watch">{x.caution}</p>}
        </div>
      )}
    </li>
  )
}

function Mobility({ m, text, onProgram }: { m: any; text?: string; onProgram: (key: string, go: boolean) => Promise<boolean> }) {
  const [done, setDone] = useState<string[]>([])
  const [saved, setSaved] = useState<boolean>(!!m.saved)
  const [busy, setBusy] = useState(false)
  const n = m.exercises.length
  const run = async (go: boolean) => {
    setBusy(true)
    try { if (await onProgram(m.program.key, go)) setSaved(true) } finally { setBusy(false) }
  }
  return (
    <div data-testid="mobility">
      <Lbl>Mobilita před spaním</Lbl>
      <Big>{m.program.name}</Big>
      <Sub><span>{m.why}</span>{m.also && <span>{` ${m.also}`}</span>}</Sub>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Tile label="Cviků" value={n} sub={m.short ? `zkráceně z ${m.program.count}` : undefined} />
        <Tile label="Čas" value={`${m.minutes} min`} sub="zhruba" />
        <Tile label="Hotovo" value={`${done.length}/${n}`} col={done.length === n ? C.ok : undefined} />
      </div>
      <AiNote text={text} ai={false} pending={false} />
      <Panel>
        <Lbl>Cviky</Lbl>
        <p className="mt-1 text-[11px] text-fg-3">Klepnutím na cvik zobrazíte provedení, kroužkem ho odškrtnete.</p>
        <ul className="mt-1 divide-y divide-white/[.06]" data-no-tap>
          {m.exercises.map((x: any, i: number) => (
            <MobilityEx key={x.id} x={x} i={i} done={done.includes(x.id)}
              onDone={() => setDone(done.includes(x.id) ? done.filter((y) => y !== x.id) : [...done, x.id])} />
          ))}
        </ul>
      </Panel>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" disabled={busy} onClick={() => run(true)} data-testid="mobility-go"
          className="flex items-center justify-center gap-1.5 rounded-full bg-accent px-3 py-2.5 text-[13px] font-bold text-ink disabled:opacity-60">
          <Play className="size-4" aria-hidden />Cvičit s časovačem
        </button>
        <button type="button" disabled={busy || saved} onClick={() => run(false)} data-testid="mobility-save"
          className="flex items-center justify-center gap-1.5 rounded-full border border-white/20 px-3 py-2.5 text-[13px] font-bold text-fg disabled:opacity-70">
          {saved ? <><BookmarkCheck className="size-4 text-accent" aria-hidden />Uloženo</> : <><Bookmark className="size-4" aria-hidden />Uložit na později</>}
        </button>
      </div>
      <p className="mt-2 text-[11px] leading-4 text-fg-3">
        {saved ? `Program ${m.program.name} máte v Péči mezi svými programy, s časovačem výdrží.` : "Uložený program najdete v Péči mezi svými programy, s časovačem výdrží."}
      </p>
    </div>
  )
}

// ---- tonight: the sleep onset and wake trend and the bedtime derived from it ----------------
const clock = (m: number) => { const x = ((Math.round(m) % 1440) + 1440) % 1440; return `${Math.floor(x / 60)}:${String(x % 60).padStart(2, "0")}` }

function SleepTimes({ t }: { t: any }) {
  // each night a bar from falling asleep to waking (evening at the top), tonight's plan hatched;
  // the dashed line is tonight's sleep onset (bedtime + the minutes to fall asleep)
  const tm = t.timing
  const nights: any[] = tm.nights || []
  const planOn = tm.bedMin + (t.latency || 15), planWake = tm.wakeMin + 1440
  const lo = Math.floor((Math.min(planOn, ...nights.map((n) => n.onset)) - 30) / 60) * 60
  const hi = Math.ceil((Math.max(planWake, ...nights.map((n) => n.wake + 1440)) + 30) / 60) * 60
  const W = 300, H = 160, L = 30, T = 6, B = 16
  const cols = nights.length + 1
  const cw = (W - L) / cols
  const y = (m: number) => T + ((m - lo) / (hi - lo)) * (H - T - B)
  const hours = []
  for (let m = lo; m <= hi; m += (hi - lo) > 9 * 60 ? 120 : 60) hours.push(m)
  const trend = tm.trend
  return (
    <div data-testid="sleep-times">
      <Lbl>{`Usínání a vstávání · ${nights.length} nocí`}</Lbl>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label="Časy usínání a vstávání">
        {hours.map((m) => (
          <g key={m}>
            <line x1={L} x2={W} y1={y(m)} y2={y(m)} stroke="rgb(255 255 255 / .07)" />
            <text x={L - 4} y={y(m) + 3} textAnchor="end" fontSize="8.5" fill={C.fg3}>{clock(m)}</text>
          </g>
        ))}
        {nights.map((n, i) => (
          <g key={n.d}>
            <rect x={L + i * cw + cw * 0.22} width={cw * 0.56} y={y(n.onset)} height={Math.max(2, y(n.wake + 1440) - y(n.onset))} rx={2}
              fill={n.weekend ? C.info : C.load} opacity={0.85} />
            {i % 2 === nights.length % 2 && <text x={L + i * cw + cw / 2} y={H - 4} textAnchor="middle" fontSize="8" fill={C.fg3}>{n.wd}</text>}
          </g>
        ))}
        <rect x={L + nights.length * cw + cw * 0.22} width={cw * 0.56} y={y(planOn)} height={y(planWake) - y(planOn)} rx={2}
          fill={C.accent} fillOpacity={0.25} stroke={C.accent} strokeWidth={1} strokeDasharray="2 1.5" />
        <text x={L + nights.length * cw + cw / 2} y={H - 4} textAnchor="middle" fontSize="8" fontWeight="700" fill={C.accent}>dnes</text>
        <line x1={L} x2={W} y1={y(planOn)} y2={y(planOn)} stroke={C.accent} strokeWidth={1} strokeDasharray="3 2" opacity={0.8} />
        <line x1={L} x2={W} y1={y(tm.onset)} y2={y(tm.onset)} stroke={C.fg3} strokeWidth={1} strokeDasharray="1.5 2" />
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-3">
        <span className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: C.load }} />všední den</span>
        <span className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: C.info }} />víkend</span>
        <span className="flex items-center gap-1"><i className="h-0 w-3 border-t border-dashed" style={{ borderColor: C.accent }} />dnešní usnutí</span>
        <span className="flex items-center gap-1"><i className="h-0 w-3 border-t border-dotted" style={{ borderColor: C.fg3 }} />obvyklé usnutí</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Tile label="Usínáte" value={tm.usualOnset} sub={tm.basis === "same" ? (tm.tomorrowWeekend ? "před víkendem" : "před všedním dnem") : "obvykle"} />
        <Tile label="Vstáváte" value={tm.usualWake} sub={tm.basis === "same" ? (tm.tomorrowWeekend ? "o víkendu" : "ve všední den") : "obvykle"} />
        <Tile label="Kolísání" value={`±${tm.sd} min`} sub="čas usínání" col={tm.sd >= 45 ? C.watch : C.ok} />
      </div>
      {(trend != null && Math.abs(trend) >= 10) || (tm.jetlag != null && Math.abs(tm.jetlag) >= 60) ? (
        <ul className="mt-2 space-y-1 text-[12px] leading-[18px] text-fg-2">
          {trend != null && Math.abs(trend) >= 10 && <li>{trend > 0 ? `Usínáte čím dál později, zhruba o ${trend} min za týden.` : `Usínáte čím dál dřív, zhruba o ${-trend} min za týden.`}</li>}
          {tm.jetlag != null && Math.abs(tm.jetlag) >= 60 && <li>{`O víkendu spíte posunutě o ${Math.round(Math.abs(tm.jetlag) / 6) / 10} h ${tm.jetlag > 0 ? "později" : "dříve"} než ve všední dny.`}</li>}
        </ul>
      ) : null}
    </div>
  )
}

const WAKE_MIN_AT = 3 * 60, WAKE_MAX_AT = 12 * 60, WAKE_STEP = 15
const hhmm = (m: number) => { const x = ((Math.round(m) % 1440) + 1440) % 1440; return `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}` }

function withWake(t: any, wake: number) {
  // the same sum as the server's (daily_report._tonight) for another wake time: wake − target − falling
  // asleep; at most stepMax earlier than the usual bedtime, and no later than it when that's already enough
  const lat = t.latency || 15, step = t.stepMax || 30
  let ideal = wake - (t.target || 8) * 60 - lat + 1440, bed = ideal, mode = "ideal"
  if (t.usualBedMin != null) {
    const gap = t.usualBedMin - ideal
    if (gap > step) { bed = t.usualBedMin - step; mode = "step" } else if (gap < -step) { bed = t.usualBedMin; mode = "keep" }
  }
  bed = 5 * Math.floor(bed / 5); ideal = 5 * Math.round(ideal / 5)
  return {
    ...t, custom: true, wakeMin: wake, wake: clock(wake), bed: clock(bed), ideal: clock(ideal), mode,
    caffeine: clock(bed - (t.caffeineH || 6) * 60),
    timing: t.timing && { ...t.timing, bedMin: bed, idealMin: ideal, wakeMin: wake },
  }
}

function WakeEdit({ t, wake, usual, onChange }: { t: any; wake: number; usual: number; onChange: (m: number | null) => void }) {
  const set = (m: number) => onChange(Math.min(WAKE_MAX_AT, Math.max(WAKE_MIN_AT, m)))
  const btn = "grid size-9 shrink-0 place-items-center rounded-full bg-white/10 text-[18px] font-bold leading-none text-fg disabled:opacity-40"
  return (
    <div className="mt-3 rounded-[14px] bg-white/[.05] px-3 py-2.5" data-no-tap data-testid="wake-edit">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-fg">Zítra vstávám jindy?</p>
          <p className="text-[11px] leading-[14px] text-fg-3">{t.custom ? "Do postele i káva jsou přepočtené." : "Posuňte budík, čas do postele se přepočítá."}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" className={btn} aria-label="Vstávat o 15 minut dřív" disabled={wake <= WAKE_MIN_AT}
            onClick={() => set(wake - WAKE_STEP)} data-testid="wake-earlier">−</button>
          {/* the time as the app writes it (24 h); the native picker under it opens on a tap */}
          <label className="relative w-[60px] rounded-[10px] bg-white/[.06] py-1.5 text-center focus-within:ring-2 focus-within:ring-accent">
            <span className="t-num text-[16px] text-fg">{clock(wake)}</span>
            <input type="time" step={300} value={hhmm(wake)} aria-label="Zítřejší čas vstávání" data-testid="wake-input"
              onClick={(e) => { try { (e.currentTarget as HTMLInputElement & { showPicker?: () => void }).showPicker?.() } catch { /* not allowed here */ } }}
              onChange={(e) => { const [h, m] = e.target.value.split(":").map(Number); if (!Number.isNaN(h) && !Number.isNaN(m)) set(h * 60 + m) }}
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0 [color-scheme:dark]" />
          </label>
          <button type="button" className={btn} aria-label="Vstávat o 15 minut později" disabled={wake >= WAKE_MAX_AT}
            onClick={() => set(wake + WAKE_STEP)} data-testid="wake-later">+</button>
        </div>
      </div>
      {t.custom && (
        <button type="button" onClick={() => onChange(null)} className="mt-1.5 text-[12px] font-semibold text-accent" data-testid="wake-reset">
          {`Zpět na obvyklé vstávání v ${clock(usual)}`}
        </button>
      )}
    </div>
  )
}

function Tonight({ t, date, text }: { t: any; date?: string; text: ReactNode }) {
  // the runner can try another wake time for tomorrow (an early alarm); kept for this evening only
  const key = `dl-wake:${date || ""}`
  const usual = t.wakeMin ?? 390
  const [pick, setPick] = useState<number | null>(() => {
    try { const v = localStorage.getItem(key); return v == null ? null : Number(v) } catch { return null }
  })
  const choose = (m: number | null) => {
    const v = m == null || m === usual ? null : m
    setPick(v)
    try { if (v == null) localStorage.removeItem(key); else localStorage.setItem(key, String(v)) } catch { /* private mode */ }
  }
  const v = pick == null || Number.isNaN(pick) ? t : withWake(t, pick)
  return (
    <>
      <Lbl>Dnešní noc</Lbl>
      <Big>{`${hm((v.target || 8) * 60)} spánku`}</Big>
      {v.custom ? <p className="mt-2 text-[14px] leading-[21px] text-fg-soft" data-testid="wake-custom-note">{`Přepočteno pro zítřejší vstávání v ${v.wake}.`}</p> : text}
      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Bed className="mx-auto size-5 text-load" aria-hidden /><p className="t-num mt-1 text-[22px]" data-testid="tonight-bed">{v.bed}</p><p className="text-[10.5px] text-fg-3">do postele</p></div>
        <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Sun className="mx-auto size-5 text-watch" aria-hidden /><p className="t-num mt-1 text-[22px]">{v.wake}</p><p className="text-[10.5px] text-fg-3">{v.custom ? "váš čas vstávání" : v.wakeFromWatch ? (v.timing?.tomorrowWeekend ? "obvyklé víkendové vstávání" : "obvyklé vstávání") : "vstávání"}</p></div>
        <div className="rounded-[14px] bg-white/[.05] px-2 py-3"><Coffee className="mx-auto size-5 text-fg-2" aria-hidden /><p className="t-num mt-1 text-[22px]">{v.caffeine}</p><p className="text-[10.5px] text-fg-3">poslední káva</p></div>
      </div>
      <WakeEdit t={v} wake={v.wakeMin ?? usual} usual={usual} onChange={choose} />
      {v.timing && <Panel><SleepTimes t={v} /></Panel>}
      <Panel><BedtimeMath t={v} /></Panel>
    </>
  )
}

function BedtimeMath({ t }: { t: any }) {
  // how the bedtime was derived: tomorrow's wake − the sleep target − falling asleep
  const tm = t.timing
  const rows: [string, string][] = [
    [t.custom ? "Zítra vstáváte (váš čas)" : tm ? (tm.tomorrowWeekend ? "Zítra vstáváte (obvykle o víkendu)" : "Zítra vstáváte (obvykle ve všední den)") : "Zítra vstáváte", t.wake],
    ["− cíl spánku", hm((t.target || 8) * 60)],
    ["− usínání", `${t.latency || 15} min`],
    ["= ideálně do postele", t.ideal || t.bed],
  ]
  return (
    <div data-testid="bedtime-math">
      <Lbl>Jak jsme k času došli</Lbl>
      <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-[13px] leading-5">
        {rows.flatMap(([k, v], i) => [
          <dt key={`k${i}`} className={i === rows.length - 1 ? "font-bold text-fg" : "text-fg-2"}>{k}</dt>,
          <dd key={`v${i}`} className={`text-right tabular-nums ${i === rows.length - 1 ? "font-bold text-fg" : "text-fg-soft"}`}>{v}</dd>,
        ])}
      </dl>
      {t.mode === "step" && tm && t.custom && (() => {
        // one early morning: no use lying in bed long before the usual sleep onset, so a shorter night
        const sleep = t.wakeMin + 1440 - (tm.bedMin + (t.latency || 15)), short = (t.target || 8) * 60 - sleep
        return (
          <p className="mt-2 rounded-[12px] bg-watch/10 px-3 py-2 text-[12.5px] leading-[18px] text-watch-soft" data-testid="bedtime-step">
            <span>{`Dřív než v ${t.bed} do postele nedoporučujeme: obvykle usínáte až v ${tm.usualOnset} a hodinu před tím se usíná nejhůř.`}</span>
            {short >= 10 && <span>{` Spánek tak vyjde asi na ${hm(sleep)}, o ${hm(short)} méně než cíl.`}</span>}
          </p>
        )
      })()}
      {t.mode === "step" && tm && !t.custom && (
        <p className="mt-2 rounded-[12px] bg-watch/10 px-3 py-2 text-[12.5px] leading-[18px] text-watch-soft" data-testid="bedtime-step">
          {`Obvykle usínáte až v ${tm.usualOnset}. Hodinu před obvyklým usnutím se usíná nejhůř, proto dnes do postele v ${t.bed} (o půl hodiny dřív než obvykle) a další večery vždy o 15–30 min dřív, než dojdete k ${t.ideal}.`}
        </p>
      )}
      {t.mode === "keep" && tm && (
        <p className="mt-2 text-[12.5px] leading-[18px] text-fg-2">{`Obvykle chodíte spát už kolem ${tm.usualBed}, to na cíl stačí. Držte stejný čas.`}</p>
      )}
      {(t.debt || t.hardTomorrow) ? (
        <p className="mt-2 text-[11.5px] leading-4 text-fg-3">
          <span>{`Cíl: vaše norma ${hm((t.base || 7.5) * 60)}`}</span>
          {t.debt ? <span>{` + část spánkového dluhu (${num(t.debt)} h za 3 noci)`}</span> : null}
          {t.hardTomorrow ? <span>{" + půl hodiny před náročným dnem"}</span> : null}
        </p>
      ) : null}
    </div>
  )
}

// ---- suggestion #7: the morning tendon test (the 24-hour response of the pain-monitoring model) --
const SIDE_WORD: Record<string, string> = { L: "levá", P: "pravá" }
const TENDON_STATE: Record<string, { col: string; label: string }> = {
  red: { col: C.alert, label: "Dnes bez běhu" }, amber: { col: C.watch, label: "Držet zátěž" },
  green: { col: C.ok, label: "Šlacha zátěž snesla" }, base: { col: C.info, label: "Výchozí hodnota" },
}

function TendonLog({ log }: { log: any[] }) {
  // 14 mornings: the test (bar) and the pain during that day's run (dot); the dashed line is 5/10
  const [pick, setPick] = useState<number | null>(null)
  const W = 300, H = 118, L = 24, T = 6, B = 16
  const cw = (W - L) / log.length
  const y = (v: number) => T + (1 - v / 10) * (H - T - B)
  const at = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.floor(((e.clientX - r.left) / r.width * W - L) / cw)
    setPick(i >= 0 && i < log.length ? i : null)
  }
  const p = pick != null ? log[pick] : null
  return (
    <div className="mt-3" data-no-tap data-testid="tendon-log">
      <Lbl>{`Posledních ${log.length} dní`}</Lbl>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full touch-none" role="img" aria-label="Ranní test a bolest při běhu"
        onPointerDown={at} onPointerMove={(e) => (e.buttons || e.pointerType === "mouse") && at(e)} onPointerLeave={() => setPick(null)}>
        {[0, 5, 10].map((v) => (
          <g key={v}>
            <line x1={L} x2={W} y1={y(v)} y2={y(v)} stroke="rgb(255 255 255 / .07)" />
            <text x={L - 5} y={y(v) + 3} textAnchor="end" fontSize="8.5" fill={C.fg3}>{v}</text>
          </g>
        ))}
        <line x1={L} x2={W} y1={y(5)} y2={y(5)} stroke={C.alert} strokeWidth={1} strokeDasharray="3 2" opacity={0.75} />
        {log.map((d, i) => (
          <g key={d.d} opacity={pick == null || pick === i ? 1 : 0.45}>
            {d.test != null && (d.test > 0
              ? <rect x={L + i * cw + cw * 0.2} width={cw * 0.6} y={y(d.test)} height={y(0) - y(d.test)} rx={2} fill={C.load} />
              : <rect x={L + i * cw + cw * 0.2} width={cw * 0.6} y={y(0) - 2} height={2} rx={1} fill={C.load} />)}
            {d.during != null && <circle cx={L + i * cw + cw / 2} cy={y(d.during)} r={4} fill={C.info} stroke={C.panel} strokeWidth={2} />}
            {d.ran && d.during == null && <circle cx={L + i * cw + cw / 2} cy={y(0) + 6} r={2} fill={C.info} />}
            {(i % 3 === (log.length - 1) % 3) && <text x={L + i * cw + cw / 2} y={H - 2} textAnchor="middle" fontSize="8" fill={C.fg3}>{dm(d.d)}</text>}
          </g>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-3">
        <span className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: C.load }} />ranní test</span>
        <span className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: C.info }} />bolest při běhu</span>
        <span className="flex items-center gap-1"><i className="h-0 w-3 border-t border-dashed" style={{ borderColor: C.alert }} />hranice 5/10</span>
      </div>
      <p className="mt-1.5 min-h-[16px] text-[11.5px] text-fg-2" data-testid="tendon-pick">
        {p ? (
          <>
            <span>{dm(p.d)}</span>
            <span>{p.test != null ? ` · test ${p.test}/10` : " · bez testu"}</span>
            {p.ran && <span>{p.during != null ? ` · běh ${p.during}/10` : " · běh bez hodnocení"}</span>}
          </>
        ) : <span className="text-fg-3">Klepněte na den pro hodnoty.</span>}
      </p>
    </div>
  )
}

function TendonItem({ it, rid, onCard }: { it: any; rid?: string; onCard: (c: any) => void }) {
  const [edit, setEdit] = useState(!it.done)
  const [pain, setPain] = useState<number | null>(it.pain ?? null)
  const [stiff, setStiff] = useState<number | null>(it.stiffness ?? null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(false)
  const save = async () => {
    if (pain == null || !rid) return
    setBusy(true); setErr(false)
    try { onCard(await api.tendonCheck(rid, { site: it.site, side: it.side, pain, stiffness: stiff })); setEdit(false) }
    catch { setErr(true) }
    finally { setBusy(false) }
  }
  const st = TENDON_STATE[it.state] || TENDON_STATE.base
  const painCol = (v: number) => (v > 5 ? C.alert : v >= 3 ? C.watch : C.ok)
  return (
    <Panel>
      <div className="flex items-baseline justify-between gap-2" data-testid={`tendon-${it.site}-${it.side || "x"}`}>
        <p className="text-[15px] font-bold text-fg">{it.name}</p>
        {it.side && <span className="text-[12px] text-fg-3">{SIDE_WORD[it.side]}</span>}
      </div>
      {edit ? (
        <div data-no-tap>
          <div className="mt-2 flex gap-3">
            <div className="w-[96px] shrink-0 self-start overflow-hidden rounded-[12px] bg-white/[.04]"><ExerciseFigure id={it.figure} /></div>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-fg">{it.testName}</p>
              <ol className="mt-1 list-decimal space-y-1 pl-4 text-[12.5px] leading-[18px] text-fg-2">
                {(it.how || []).map((h: string, i: number) => <li key={i}>{h}</li>)}
              </ol>
            </div>
          </div>
          <p className="mt-3 text-[12px] font-semibold text-fg-2">Bolest během testu</p>
          <div className="mt-1.5 grid grid-cols-11 gap-1" role="radiogroup" aria-label="Bolest během testu">
            {Array.from({ length: 11 }, (_, v) => (
              <button key={v} type="button" role="radio" aria-checked={pain === v} onClick={() => setPain(v)} data-testid={`tendon-pain-${v}`}
                className="t-num grid h-9 place-items-center rounded-[9px] text-[13px] font-bold"
                style={pain === v ? { background: painCol(v), color: C.ink } : { background: "rgb(255 255 255 / .06)", color: C.fg }}>{v}</button>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[10.5px] text-fg-3"><span>žádná</span><span>nejhorší</span></div>
          <p className="mt-3 text-[12px] font-semibold text-fg-2">Ranní ztuhlost šlachy</p>
          <div className="mt-1.5 grid grid-cols-3 gap-1.5">
            {["žádná", "do 15 min", "déle"].map((l, v) => (
              <button key={l} type="button" onClick={() => setStiff(stiff === v ? null : v)} aria-pressed={stiff === v}
                className={`rounded-[10px] px-2 py-2 text-[12.5px] font-semibold ${stiff === v ? "bg-accent text-ink" : "bg-white/[.06] text-fg"}`}>{l}</button>
            ))}
          </div>
          <button type="button" onClick={save} disabled={pain == null || busy || !rid} data-testid="tendon-save"
            className="mt-3 w-full rounded-full bg-accent px-3 py-2.5 text-[13px] font-bold text-ink disabled:opacity-50">
            {busy ? "Ukládám…" : "Uložit test"}
          </button>
          {err && <p className="mt-2 text-[12px] text-alert">Uložení se nepovedlo, zkuste to znovu.</p>}
        </div>
      ) : (
        <>
          <div className="mt-2 rounded-[12px] px-3 py-2.5" style={{ background: `${st.col}1f` }} data-testid="tendon-verdict">
            <p className="flex items-center gap-1.5 text-[13px] font-bold" style={{ color: st.col }}>
              {it.state === "red" ? <TriangleAlert className="size-4" aria-hidden /> : it.state === "green" ? <Check className="size-4" aria-hidden /> : <Info className="size-4" aria-hidden />}
              {st.label}
            </p>
            <p className="mt-1 text-[12.5px] leading-[18px] text-fg-soft">{it.text}</p>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Tile label="Dnešní test" value={`${it.pain}/10`} col={painCol(it.pain)} />
            <Tile label="Před během" value={it.baseline != null ? `${it.baseline}/10` : "—"} sub={it.baselineDate ? dm(it.baselineDate) : undefined} />
            <Tile label="Při běhu" value={it.during != null ? `${it.during}/10` : "—"} sub={it.ran ? "včera" : "včera bez běhu"} />
          </div>
          <TendonLog log={it.log || []} />
          <button type="button" onClick={() => setEdit(true)} className="mt-2 text-[12px] font-semibold text-accent" data-testid="tendon-edit">Opravit dnešní odpověď</button>
        </>
      )}
    </Panel>
  )
}

function TendonCard({ t, rid, onSaved }: { t: any; rid?: string; onSaved: () => void }) {
  const [card, setCard] = useState(t)
  const onCard = (c: any) => { setCard(c); onSaved() }
  const items: any[] = card?.items || []
  return (
    <div data-testid="tendon-card">
      <Lbl>Ranní test šlachy</Lbl>
      <Big>{items.every((x) => x.done) ? "Jak šlacha snesla zátěž" : "Krátký test, než vyrazíte"}</Big>
      <Sub>Šlacha byla v posledních dnech bolavá. Stejný test každé ráno ukáže, jestli se po zátěži uklidnila: bolest smí být nejvýš 5/10 a do rána má odeznít.</Sub>
      {items.map((it) => <TendonItem key={`${it.site}-${it.side}-${it.done ? "d" : "n"}`} it={it} rid={rid} onCard={onCard} />)}
      <p className="mt-3 text-[11px] leading-4 text-fg-3">Model sledování bolesti (Silbernagel et al., 2007), test zátěží šlachy (Malliaras et al., 2015). Výsledek rovnou upraví dnešní doporučení.</p>
    </div>
  )
}

// ---- suggestion #10: what the day held, and what it does to this runner's night ----------
const OUT_LABEL: [string, string][] = [["hrv", "HRV"], ["rhr", "Klidový tep"], ["sleep", "Spánek"]]
const effVal = (k: string, v: number) =>
  k === "hrv" ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 0)} %` : k === "rhr" ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 1)} tepu/min` : `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 0)} min`
const effBad = (k: string, v: number) => (k === "rhr" ? v > 0 : v < 0)

function EffectChips({ eff }: { eff: any }) {
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {OUT_LABEL.map(([k, l]) => {
        const e = eff?.[k]
        if (!e || e.status === "collecting") return null
        const clear = e.status === "clear"
        return (
          <span key={k} className="rounded-full px-2 py-0.5 text-[11.5px] font-semibold"
            style={clear ? { background: `${effBad(k, e.value) ? C.watch : C.ok}24`, color: effBad(k, e.value) ? C.watchSoft : C.ok } : { background: "rgb(255 255 255 / .06)", color: C.fg3 }}>
            <span>{l}</span>{clear ? " " : ": "}<span className="t-num">{clear ? effVal(k, e.value) : e.status === "none" ? "beze změny" : "nejasné"}</span>
          </span>
        )
      })}
    </div>
  )
}

function HrvForest({ rows }: { rows: any[] }) {
  // the HRV effect of each tag with its 95 % interval; the band around zero is the smallest
  // worthwhile change (half of the night-to-night SD) — an interval inside it = no effect
  const W = 300, rowH = 24, L = 112, R = 8, T = 14
  const H = T + rows.length * rowH + 4
  const ext = Math.max(10, ...rows.flatMap((x) => [Math.abs(x.effects.hrv.lo), Math.abs(x.effects.hrv.hi)]))
  const dom = Math.ceil(ext / 5) * 5
  const x = (v: number) => L + ((v + dom) / (2 * dom)) * (W - L - R)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label="Vliv štítků na HRV" data-testid="hrv-forest">
      {[-dom, 0, dom].map((v) => (
        <g key={v}>
          <line x1={x(v)} x2={x(v)} y1={T - 4} y2={H} stroke={v === 0 ? "rgb(255 255 255 / .25)" : "rgb(255 255 255 / .07)"} />
          <text x={x(v)} y={9} textAnchor={v > 0 ? "end" : v < 0 ? "start" : "middle"} fontSize="8.5" fill={C.fg3}>{v === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v)} %`}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const e = r.effects.hrv, cy = T + i * rowH + rowH / 2
        const col = e.status === "clear" ? (e.value < 0 ? C.watch : C.ok) : C.fg3
        return (
          <g key={r.key}>
            <text x={0} y={cy + 3.5} fontSize="10" fill={C.fg2}>{r.label}</text>
            <line x1={x(e.lo)} x2={x(e.hi)} y1={cy} y2={cy} stroke={col} strokeWidth={2} strokeLinecap="round" />
            <circle cx={x(e.value)} cy={cy} r={4.5} fill={col} stroke={C.panel} strokeWidth={2} />
          </g>
        )
      })}
    </svg>
  )
}

function DayTags({ d, rid }: { d: any; rid?: string }) {
  const [data, setData] = useState(d)
  const [sel, setSel] = useState<string[]>(d.tags || [])
  const [answered, setAnswered] = useState<boolean>(d.tags != null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(false)
  const toggle = (k: string) => {
    setDirty(true)
    setSel((cur) => {
      if (cur.includes(k)) return cur.filter((x) => x !== k)
      const other = k === "alcohol" ? "alcohol_more" : k === "alcohol_more" ? "alcohol" : null
      return [...cur.filter((x) => x !== other), k]
    })
  }
  const save = async (tags: string[]) => {
    if (!rid) return
    setBusy(true); setErr(false)
    try { const x = await api.saveDayTags(rid, { tags }); setData(x); setSel(x.tags || []); setAnswered(true); setDirty(false) }
    catch { setErr(true) }
    finally { setBusy(false) }
  }
  const ins: any[] = data.insights || []
  const ready = ins.filter((x) => x.status !== "collecting" && x.effects?.hrv && x.effects.hrv.status !== "collecting")
  const collecting = ins.filter((x) => x.status === "collecting" && x.n > 0)
  return (
    <div data-testid="day-tags">
      <Lbl>Co dnes bylo</Lbl>
      <Big>Co vám hýbe nocí?</Big>
      <Sub>Označte, co dnes bylo. Po pár týdnech uvidíte, co z toho u vás opravdu mění HRV, klidový tep a spánek.</Sub>
      <div className="mt-4 flex flex-wrap gap-2" data-no-tap>
        {(data.options || []).map((o: any) => {
          const on = sel.includes(o.key)
          return (
            <button key={o.key} type="button" onClick={() => toggle(o.key)} aria-pressed={on} data-testid={`tag-${o.key}`}
              className={`rounded-full px-3 py-2 text-[13px] font-semibold transition ${on ? "bg-accent text-ink" : "bg-white/[.07] text-fg"}`}>{o.label}</button>
          )
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" disabled={busy} onClick={() => save([])} data-testid="tags-none"
          className={`rounded-full border px-3 py-2.5 text-[13px] font-bold disabled:opacity-60 ${answered && !sel.length && !dirty ? "border-accent text-accent" : "border-white/20 text-fg"}`}>
          Nic z toho
        </button>
        <button type="button" disabled={busy || !sel.length || (answered && !dirty)} onClick={() => save(sel)} data-testid="tags-save"
          className="rounded-full bg-accent px-3 py-2.5 text-[13px] font-bold text-ink disabled:opacity-50">
          {answered && !dirty && sel.length ? "Uloženo" : "Uložit"}
        </button>
      </div>
      <p className="mt-2 text-[11.5px] leading-4 text-fg-3" data-testid="tags-status">
        {err ? "Uložení se nepovedlo, zkuste to znovu." : answered && !dirty ? (sel.length ? "Dnešní večer je zapsaný." : "Zapsáno: dnes nic z toho. I takový večer je potřeba pro srovnání.") : "Večer bez odpovědi se do srovnání nepočítá."}
      </p>
      <Panel>
        <Lbl>{`Vaše data · ${data.answered} zapsaných večerů`}</Lbl>
        {ready.length ? (
          <>
            <p className="mt-2 text-[12px] leading-[17px] text-fg-2">Vliv na HRV další noci proti vašemu průměru, s 95% intervalem a po odečtení vlivu tréninku toho dne.</p>
            <HrvForest rows={ready.slice(0, 6)} />
            <ul className="mt-2 space-y-2.5">
              {ready.map((x) => (
                <li key={x.key}>
                  <p className="text-[13px] font-semibold text-fg"><span>{x.label}</span><span className="font-normal text-fg-3">{` · ${x.n} nocí`}</span></p>
                  <EffectChips eff={x.effects} />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-[12.5px] leading-[18px] text-fg-2">Ke každému štítku je potřeba aspoň 5 večerů s ním a 10 bez něj. Pak se tu objeví, jak u vás působí.</p>
        )}
        {collecting.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {collecting.map((x) => (
              <li key={x.key} className="flex items-center gap-2 text-[12px] text-fg-2">
                <span className="w-[112px] shrink-0 truncate">{x.label}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10"><b className="block h-full rounded-full bg-load" style={{ width: `${Math.min(100, (x.n / 5) * 100)}%` }} /></span>
                <span className="t-num w-9 text-right text-fg-3">{`${Math.min(x.n, 5)}/5`}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <p className="mt-3 text-[11px] leading-4 text-fg-3">Alkohol snižuje noční HRV podle množství (Pietilä et al., 2018); tady jde o to, jak je to právě u vás.</p>
    </div>
  )
}

function LastNightTags({ x }: { x: any }) {
  const now = x.now || {}
  return (
    <Panel>
      <Lbl>Včerejší večer</Lbl>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {x.items.map((it: any) => <span key={it.key} className="rounded-full bg-white/[.08] px-2.5 py-1 text-[12px] font-semibold text-fg">{it.label}</span>)}
      </div>
      {(now.hrv != null || now.rhr != null || now.sleep != null) && (
        <p className="mt-2 text-[12.5px] leading-[18px] text-fg-2">
          <span>Dnešní noc proti průměru 14 nocí před ní:</span>
          {now.hrv != null && <span className="t-num">{` HRV ${effVal("hrv", now.hrv)}`}</span>}
          {now.rhr != null && <span className="t-num">{` · tep ${effVal("rhr", now.rhr)}`}</span>}
          {now.sleep != null && <span className="t-num">{` · spánek ${effVal("sleep", now.sleep)}`}</span>}
        </p>
      )}
      {x.items.map((it: any) => (
        <div key={it.key} className="mt-2">
          {it.status === "clear" ? (
            <>
              <p className="text-[12px] text-fg-3"><span>{it.label}</span><span>: u vás obvykle</span><span>{` (${it.n} nocí)`}</span></p>
              <EffectChips eff={it.effects} />
            </>
          ) : (
            <p className="text-[12px] text-fg-3">
              <span>{it.label}</span><span>{": "}</span>
              <span>{it.status === "collecting" ? `zatím ${Math.min(it.n, 5)} z 5 večerů potřebných pro srovnání` : it.status === "none" ? "u vás bez znatelného vlivu na noc" : "vliv zatím nejasný"}</span>
            </p>
          )}
        </div>
      ))}
    </Panel>
  )
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
  if (r.mobility) cards.push({ key: "mobility", title: "Mobilita", body: <Mobility m={r.mobility} text={c.notes.mobility} onProgram={c.onProgram} /> })
  if (r.dayTags) cards.push({ key: "tags", title: "Co dnes bylo", body: <DayTags d={r.dayTags} rid={c.rid} /> })
  cards.push({
    key: "tonight", title: "Na noc", body: (
      <>
        <Tonight t={t} date={r.date} text={note(c, "tonight")} />
        <Panel>
          <ul className="space-y-1.5 text-[13px] leading-5 text-fg-soft">
            <li className="flex gap-2"><span className="text-load">›</span><span>Sportovcům se doporučuje 7–9 hodin spánku, při náročném tréninku spíš víc (Walsh et al., 2021).</span></li>
            <li className="flex gap-2"><span className="text-load">›</span><span>Pravidelný čas usínání a vstávání souvisel se zdravím víc než samotná délka spánku (Windred et al., 2024).</span></li>
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
  const navigate = useNavigate()
  const [now, setNow] = useState(() => new Date())
  const [rep, setRep] = useState<{ kind: Kind; day: string; data: any } | null>(null)
  const [show, setShow] = useState(false)
  const [bump, setBump] = useState(0)                 // an answer in the report (a tendon test) → the report again
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
  }, [rid, kind, day, stamp, bump])
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
  // owner request 2026-10-05: a programme from the report — saved among the runner's
  // programmes (the same one twice is the same), optionally opened in Péče right away
  const onProgram = async (key: string, go: boolean) => {
    if (!rid) return false
    let prog: any = null
    try { prog = await api.startSelfProgram(rid, { template: key }) } catch { return false }
    if (go) {
      // railway#201 — the programme's exercises fold until the session starts; from the report it has started
      try { if (prog?.id) localStorage.setItem(`dl-session-open:${prog.id}:${new Date().toLocaleDateString("sv-SE")}`, "1") } catch { /* private mode */ }
      setShow(false)
      navigate(`/app/messages?sub=program&prog=${key}`)
      setTimeout(() => window.dispatchEvent(new CustomEvent(CARE_SUB_EVENT, { detail: "program" })), 80)
    }
    return true
  }
  const aiNow = ai && ai.key === repKey ? ai : null
  const ctx = rep ? { onAsk, onProgram, rid, onRefresh: () => { setBump((x) => x + 1); refresh().catch(() => {}) }, hasAssistant: available, notes: { ...(rep.data?.notes || {}), ...(aiNow?.notes || {}) },
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
