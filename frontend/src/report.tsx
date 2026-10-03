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
import { Bed, ChevronRight, Coffee, Footprints, MessageCircle, Moon, Sun, X } from "lucide-react"

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

function DayCurve({ stress, bb }: { stress?: [number, number][]; bb?: [number, number][] }) {
  const W = 320, H = 120, x = (m: number) => (m / 1440) * W, y = (v: number) => H - 16 - (v / 100) * (H - 26)
  const col = (v: number) => (v <= 25 ? "#5c9df5" : v <= 50 ? "#f5c26b" : v <= 75 ? "#f0954a" : C.alert)
  const line = (bb || []).map(([m, v], i) => `${i ? "L" : "M"}${x(m).toFixed(1)} ${y(v).toFixed(1)}`).join(" ")
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Stres a Body Battery během dne" data-testid="day-curve">
      {[0, 6, 12, 18, 24].map((h) => (
        <g key={h}>
          <line x1={x(h * 60)} x2={x(h * 60)} y1={6} y2={H - 14} stroke="rgb(255 255 255 / .05)" />
          <text x={x(h * 60)} y={H - 2} textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"} fontSize="9.5" fill={C.fg3}>{h}:00</text>
        </g>
      ))}
      {(stress || []).map(([m, v]) => (
        <rect key={m} x={x(m) + 0.3} width={Math.max(0.6, x(15) - 0.6)} y={y(v)} height={H - 16 - y(v)} fill={col(v)} opacity={0.85} />
      ))}
      {line && <path d={line} fill="none" stroke={C.accent} strokeWidth="2.2" strokeLinejoin="round" />}
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

// ---- morning ------------------------------------------------------------------------------
function morningCards(r: any, onAsk: (q: string) => void, hasAssistant: boolean): Card[] {
  const n = r.night, rec = r.recovery || {}, p = r.plan || {}
  const cards: Card[] = [{
    key: "intro", title: "Úvod", body: (
      <div className="flex h-full flex-col justify-center">
        <Sunrise />
        <p className="mt-6 text-[13px] font-semibold text-fg-2">{fmtDay(r.date)}</p>
        <Big>{r.greeting}</Big>
        <Sub>{r.summary}</Sub>
      </div>
    ),
  }]
  cards.push({
    key: "night", title: "Noc", body: !n ? <><Big>Noc zatím chybí</Big><Sub>{r.nightText}</Sub></> : (
      <>
        <div className="flex items-center gap-4">
          <Ring value={n.hours} max={Math.max(9, n.need || 8)} col={n.hours >= (n.need || 7) ? C.ok : n.hours >= (n.need || 7) - 1 ? C.watch : C.alert}>
            <b className="t-num block text-[22px] leading-none">{num(n.hours)}</b><span className="text-[10px] text-fg-3">hodin</span>
          </Ring>
          <div className="min-w-0">
            <Big>{n.start && n.end ? `${n.start} – ${n.end}` : `${num(n.hours)} h spánku`}</Big>
            <p className="mt-1 text-[12px] text-fg-3">{[n.score != null && `skóre spánku ${n.score}`, n.awakeCount != null && `${n.awakeCount}× probuzení`, n.respiration && `dech ${num(n.respiration)}/min`].filter(Boolean).join(" · ")}</p>
          </div>
        </div>
        <Sub>{r.nightText}</Sub>
        {n.hypnogram?.length ? (
          <Panel>
            <Lbl>Průběh noci</Lbl>
            <div className="mt-2 grid grid-cols-[46px_1fr] gap-1">
              <div className="grid grid-rows-4 pt-[3px] text-[10.5px] text-fg-3" style={{ height: 112 }}>{["awake", "rem", "light", "deep"].map((s) => <span key={s} className="flex items-center">{STAGE_LABEL[s]}</span>)}</div>
              <Hypnogram hyp={n.hypnogram} start={n.start} />
            </div>
          </Panel>
        ) : null}
        <Panel className="space-y-2.5">
          <Lbl>Fáze proti vaší normě (4 týdny)</Lbl>
          {["deep", "rem", "light", "awake"].map((s) => (
            <VsNorm key={s} label={STAGE_LABEL[s]} v={n.stages?.[s]} norm={n.norm?.[s]} unit="min" col={STAGE_COL[s]}
              max={Math.max(n.stages?.[s] || 0, n.norm?.[s] || 0, 1) * 1.25} />
          ))}
        </Panel>
        <Panel>
          <Lbl>Posledních 7 nocí</Lbl>
          <div className="mt-2">
            <Bars items={(n.nights || []).map((x: any, k: number) => ({ label: new Date(x.d + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "short" }), v: x.h,
              col: x.h == null ? C.fg4 : x.h >= (n.need || 7) ? "#5c7cfa" : x.h >= (n.need || 7) - 1 ? C.watch : C.alert, on: k === (n.nights || []).length - 1 }))}
              max={Math.max(10, ...(n.nights || []).map((x: any) => x.h || 0))} ref={n.need} refLabel={`potřeba ${num(n.need)} h`} />
          </div>
          {n.debt ? <p className="mt-2 text-[12px] text-fg-2">{`Spánkový dluh za 3 noci: ${hm(n.debt * 60)}.`}</p> : null}
        </Panel>
      </>
    ),
  })
  const night = rec.night || {}, base = rec.base || {}
  cards.push({
    key: "recovery", title: "Regenerace", body: (
      <>
        <div className="flex items-center gap-4">
          <Ring value={rec.score} col={goodCol(rec.score)}>
            <b className="t-num block text-[24px] leading-none">{rec.score ?? "—"}</b><span className="text-[10px] text-fg-3">%</span>
          </Ring>
          <div>
            <Big>{rec.label ? rec.label.charAt(0).toUpperCase() + rec.label.slice(1) : "Připravenost"}</Big>
            {rec.yesterday != null && rec.score != null && <p className="mt-1 text-[12px] text-fg-3">{`ráno · včera ${rec.yesterday} % (${rec.score - rec.yesterday >= 0 ? "+" : "−"}${Math.abs(rec.score - rec.yesterday)})`}</p>}
            {rec.now != null && rec.now !== rec.score && <p className="text-[12px] text-fg-3">{`po dnešním tréninku ${rec.now} %`}</p>}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          {[["HRV", night.hrv, base.hrv, "ms", true], ["Klidový tep", night.rhr, base.rhr, "tepů/min", false], ["Body Battery", rec.bbWake, null, "ráno", true]].map(([l, v, b, u, up]: any) => {
            const d = v != null && b != null ? v - b : null
            const good = d == null ? null : up ? d >= 0 : d <= 0
            return (
              <div key={l} className="rounded-[14px] bg-white/[.05] px-2 py-2.5">
                <p className="text-[10.5px] text-fg-3">{l}</p>
                <p className="t-num mt-0.5 text-[22px] leading-none">{v ?? "—"}</p>
                <p className="mt-1 text-[10.5px]" style={{ color: good == null ? C.fg3 : good ? C.ok : C.watch }}>{d != null ? `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d)} proti normě` : u}</p>
              </div>
            )
          })}
        </div>
        {rec.readiness && <div data-no-tap><ReadinessFactors r={rec.readiness} /></div>}
      </>
    ),
  })
  const y = r.yesterday || {}
  cards.push({
    key: "yesterday", title: "Včerejšek", body: (
      <>
        <Big>{y.activities?.length ? "Včera jste trénovali" : "Včera bez tréninku"}</Big>
        <Sub>{y.activities?.length ? "Co z toho tělo ještě zpracovává:" : "Tělo mělo den na regeneraci."}</Sub>
        {y.activities?.length ? (
          <Panel className="divide-y divide-white/[.06] !py-1">
            {y.activities.map((x: any) => (
              <div key={x.id} className="flex items-center justify-between gap-3 py-2.5">
                <span className="min-w-0"><b className="block truncate text-[14px]">{x.title}</b><span className="text-[11.5px] text-fg-3">{[x.time, x.min && `${x.min} min`, x.hr && `⌀ ${x.hr} tepů`, x.rpe && `náročnost ${x.rpe}/10`].filter(Boolean).join(" · ")}</span></span>
                <span className="t-num shrink-0 text-[18px]">{x.km ? `${num(x.km)} km` : ""}</span>
              </div>
            ))}
          </Panel>
        ) : null}
        {y.carry?.length ? (
          <Panel className="space-y-2.5">
            <Lbl>Ještě nevstřebáno z posledních dní</Lbl>
            {y.carry.map((c: any) => (
              <VsNorm key={c.ch} label={c.label} v={c.residual} unit={c.unit} col={c.share > 0.6 ? C.watch : C.info} max={c.cap} norm={null} />
            ))}
            <p className="text-[11px] leading-4 text-fg-3">Pruh je zbytek zátěže proti vaší týdenní kapacitě. Vstřebává se noc po noci, rychleji po dobrém spánku.</p>
          </Panel>
        ) : null}
        {y.axes && <p className="mt-3 text-[12px] text-fg-2">{`Zátěž ${num(y.axes.load, 0)} · mechanika ${num(y.axes.mech, 0)} (práh ${y.axes.threshold})`}</p>}
      </>
    ),
  })
  const km = p.km && typeof p.km === "object" ? p.km : null
  cards.push({
    key: "plan", title: "Plán dne", body: (
      <>
        <Lbl>Doporučení na dnešek</Lbl>
        <Big>{p.override || p.label || "—"}</Big>
        {km && km.hi > 0 && <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-[14px] bg-white/[.05] px-2 py-2.5"><p className="text-[10.5px] text-fg-3">Kilometry</p><p className="t-num mt-0.5 text-[20px]">{km && km.hi > 0 ? `${num(km.lo)}–${num(km.hi)}` : "—"}</p></div>
          <div className="rounded-[14px] bg-white/[.05] px-2 py-2.5"><p className="text-[10.5px] text-fg-3">Tep</p><p className="t-num mt-0.5 text-[20px]">{p.hr ? `${p.hr[0]}–${p.hr[1]}` : "—"}</p></div>
          <div className="rounded-[14px] bg-white/[.05] px-2 py-2.5"><p className="text-[10.5px] text-fg-3">Tempo</p><p className="t-num mt-0.5 text-[20px]">{p.pace ? `${paceS(p.pace[0])}–${paceS(p.pace[1])}` : "—"}</p></div>
        </div>}
        {p.terrain && <p className="mt-3 text-[13px] text-fg-2">{`Terén: ${p.terrain}`}</p>}
        {(p.notes?.length || p.reasons?.length) ? (
          <Panel>
            <ul className="space-y-1.5 text-[13px] leading-5 text-fg-soft">
              {[...(p.notes || []), ...(p.reasons || [])].slice(0, 5).map((t: string, k: number) => <li key={k} className="flex gap-2"><span className="text-accent">›</span><span>{t}</span></li>)}
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
  if (hasAssistant) cards.push({ key: "ask", title: "Otázky", body: <><Big>Chcete vědět víc?</Big><Sub>Asistent odpoví z vašich dat a citované literatury.</Sub><Questions qs={r.questions || []} onAsk={onAsk} /></> })
  return cards
}

// ---- evening ------------------------------------------------------------------------------
const TYPE_COL: Record<string, string> = { "dlouhý": C.load, "kvalitní": C.alert, "lehký": C.info, volno: C.fg4, "lehce / volno": C.fg4 }

function eveningCards(r: any, onAsk: (q: string) => void, hasAssistant: boolean): Card[] {
  const d = r.day || {}, w = r.week || {}, rw = r.restOfWeek || {}, t = r.tonight || {}, vs = r.vsPlan || {}
  const cards: Card[] = [{
    key: "intro", title: "Úvod", body: (
      <div className="flex h-full flex-col justify-center">
        <NightSky />
        <p className="mt-6 text-[13px] font-semibold text-fg-2">{fmtDay(r.date)}</p>
        <Big>{r.greeting}</Big>
        <Sub>{r.summary}</Sub>
      </div>
    ),
  }]
  const sm = d.stressMin || null
  const smTot = sm ? sm.rest + sm.low + sm.medium + sm.high : 0
  cards.push({
    key: "day", title: "Den", body: (
      <>
        <div className="flex items-center gap-4">
          <Ring value={d.steps} max={d.stepGoal || d.stepsNorm || 10000} col={C.accent}>
            <Footprints className="mx-auto size-4 text-fg-3" aria-hidden />
            <b className="t-num block text-[18px] leading-tight">{num(d.steps, 0)}</b>
          </Ring>
          <div>
            <Big>{d.steps ? `${num(d.steps, 0)} kroků` : "Den"}</Big>
            <p className="mt-1 text-[12px] text-fg-3">{[d.stepsNorm && `obvykle ${num(d.stepsNorm, 0)}`, d.stepGoal && `cíl ${num(d.stepGoal, 0)}`].filter(Boolean).join(" · ")}</p>
          </div>
        </div>
        {(d.stress?.length || d.bb?.length) ? (
          <Panel>
            <div className="flex items-baseline justify-between"><Lbl>Stres a Body Battery</Lbl><span className="text-[11px] text-fg-3">{`⌀ stres ${d.stressAvg ?? "—"}${d.stressNorm ? ` (obvykle ${d.stressNorm})` : ""}`}</span></div>
            <div className="mt-2"><DayCurve stress={d.stress} bb={d.bb} /></div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-3">
              <span className="flex items-center gap-1"><i className="h-0.5 w-3 rounded" style={{ background: C.accent }} />Body Battery</span>
              {[["#5c9df5", "klid"], ["#f5c26b", "nízký"], ["#f0954a", "střední"], [C.alert, "vysoký"]].map(([c, l]) => <span key={l} className="flex items-center gap-1"><i className="size-2 rounded-sm" style={{ background: c }} />{l}</span>)}
            </div>
          </Panel>
        ) : null}
        {sm && smTot > 0 && (
          <Panel>
            <Lbl>Čas ve stresu</Lbl>
            <div className="mt-2 flex h-3 overflow-hidden rounded-full">
              {[["rest", "#5c9df5"], ["low", "#f5c26b"], ["medium", "#f0954a"], ["high", C.alert]].map(([k, c]) => <i key={k} style={{ width: `${(sm[k] / smTot) * 100}%`, background: c }} />)}
            </div>
            <p className="mt-1.5 text-[12px] text-fg-2">{`Klid ${hm(sm.rest)} · vysoký stres ${hm(sm.high)}`}</p>
          </Panel>
        )}
        {(d.bbHigh != null || d.bbNow != null) && (
          <p className="mt-3 text-[13px] text-fg-2">{`Body Battery: ráno ${d.bbHigh ?? "—"}, teď ${d.bbNow ?? "—"}${d.bbDrained != null ? ` · vybito ${d.bbDrained}, nabito ${d.bbCharged ?? 0}` : ""}.`}</p>
        )}
      </>
    ),
  })
  cards.push({
    key: "vsplan", title: "Dnes vs. plán", body: (
      <>
        <Lbl>Doporučení na dnešek bylo</Lbl>
        <Big>{vs.label || "—"}</Big>
        {d.activities?.length ? (
          <Panel className="divide-y divide-white/[.06] !py-1">
            {d.activities.map((x: any) => (
              <div key={x.id} className="flex items-center justify-between gap-3 py-2.5">
                <span className="min-w-0"><b className="block truncate text-[14px]">{x.title}</b><span className="text-[11.5px] text-fg-3">{[x.time, x.min && `${x.min} min`, x.hr && `⌀ ${x.hr} tepů`].filter(Boolean).join(" · ")}</span></span>
                <span className="t-num shrink-0 text-[18px]">{x.km ? `${num(x.km)} km` : ""}</span>
              </div>
            ))}
          </Panel>
        ) : <Sub>Dnes bez tréninku.</Sub>}
        {vs.afterDone?.text && <Sub>{vs.afterDone.text}</Sub>}
        {vs.channels?.length ? (
          <Panel className="space-y-2.5">
            <Lbl>Dnes odvedeno · zbývá</Lbl>
            {vs.channels.filter((c: any) => c.doneToday != null).map((c: any) => (
              <div key={c.ch} className="flex items-baseline justify-between text-[13px]">
                <span className="text-fg-2">{c.label}</span>
                <span className="tabular-nums text-fg-3"><b className="text-fg">{num(c.doneToday, c.ch === "volume" ? 1 : 0)}</b>{` ${c.unit}${c.left != null ? ` · zbývá ${num(c.left, c.ch === "volume" ? 1 : 0)}` : ""}`}</span>
              </div>
            ))}
          </Panel>
        ) : null}
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
        <p className="mt-1 text-[12px] text-fg-3">{[w.left != null && w.left > 0.5 && `zbývá ${num(w.left)} km`, w.cycle && `${w.cycle}. týden cyklu`, w.mode === "recovery" && "odlehčovací týden"].filter(Boolean).join(" · ")}</p>
        <Panel>
          <Bars max={maxKm} items={days.map((x) => {
            const pl = planned[x.date]
            return x.past || x.today ? { label: x.wd, v: x.km || (x.other?.length ? 0.01 : null), col: x.today ? C.accent : C.info, on: x.today }
              : { label: x.wd, v: pl?.km ?? null, col: TYPE_COL[pl?.type] || C.fg4, hatch: true }
          })} />
          <p className="mt-2 text-[11px] text-fg-3">Plné sloupce: odběhnuto. Šrafované: návrh na zbytek týdne.</p>
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
          <p className="mt-2 text-[11px] leading-4 text-fg-3">Podle vašich obvyklých běžeckých dnů. Každý den ho upřesní ranní připravenost.</p>
        </Panel>
      </>
    ),
  })
  cards.push({
    key: "tonight", title: "Na noc", body: (
      <>
        <Lbl>Dnešní noc</Lbl>
        <Big>{`${hm((t.target || 8) * 60)} spánku`}</Big>
        <Sub>{[t.hardTomorrow && "Zítra vás čeká náročnější trénink, proto o půl hodiny víc.", t.debt >= 1 && `Doháníte i spánkový dluh ${hm(t.debt * 60)}.`].filter(Boolean).join(" ") || "Podle vaší obvyklé délky spánku."}</Sub>
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
  if (hasAssistant) cards.push({ key: "ask", title: "Otázky", body: <><Big>Chcete se na něco zeptat?</Big><Sub>Asistent odpoví z vašich dat a citované literatury.</Sub><Questions qs={r.questions || []} onAsk={onAsk} /></> })
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
  const { me, boot, viewing, touring } = useApp()
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
  const value = useMemo<ReportApi>(() => ({ kind: rep ? rep.kind : null, open: () => setShow(true) }), [rep])
  const onAsk = (q: string) => { setShow(false); setTimeout(() => ask(q), 50) }
  const cards = show && rep ? (rep.kind === "morning" ? morningCards(rep.data, onAsk, available) : eveningCards(rep.data, onAsk, available)) : null
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
