// Engine v3 — the Trénink tab: today's session within this week's target (4-week
// loading cycle on the runner's own reference week, capped by the capacity the
// Zátěž tab shows): session type, distance, HR zone + pace, Z4+ minutes,
// ascent/descent, terrain, and why.
import { WhyButton } from "@/assistant"
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { useQuadHistory } from "@/history"
import { ReadinessTrend } from "@/tabs"
import { AlertBanner, Button, Card, Chip, InfoDot, Label, Segmented, Sheet, useToast } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { readinessCol } from "@/capacity"
import { fmtD, paceStr } from "@/lib"
import { C } from "@/tokens"
import { Bike, ChevronDown, ChevronRight, CircleCheck, Dumbbell, Flag, Footprints, Leaf, MoveDiagonal, Plus, Route, Sofa, Waves, X, Zap, type LucideIcon } from "lucide-react"

const ORDER = ["volno", "regenerace", "lehký", "dlouhý", "kvalitní", "závod"]
const CROSS = ["kolo", "voda", "posilování"]
const MODE: Record<string, [string, string]> = {
  build: ["Budovací týden", C.ok], recovery: ["Odlehčovací týden", C.watch], deload: ["Odlehčovací · zvýšená zátěž", C.alert],
  taper: ["Ladění před závodem", C.accent], learning: ["Nastavuji cyklus", C.fg2], hold: ["Udržení", C.watch],
  return: ["Návrat po zranění", C.watch],
}
const CYCLE_PCT = [90, 100, 110, 55]
const LIMIT: Record<string, string> = {
  week: "cíl tohoto týdne v cyklu", "7d": "týdenní kapacita (posledních 7 dní)", run: "strop jednoho běhu",
  systemic: "celková zátěž", mechanics: "mechanika nad prahem",
}
const CH_ICON: Record<string, string> = { volume: "Objem", intensity: "Intenzita", descent: "Klesání", ascent: "Stoupání", systemic: "Celková zátěž" }
const TYPE_ICON: Record<string, LucideIcon> = { volno: Sofa, regenerace: Leaf, "lehký": Footprints, "dlouhý": Route, "kvalitní": Zap, "závod": Flag, kolo: Bike, voda: Waves, "posilování": Dumbbell }

// Today's capacity: what today can hold so that the last 7 days stay within the
// weekly capacity the Zátěž tab shows, this week keeps to its place in the cycle,
// no single run exceeds its own capacity and load / mechanics stay under the
// threshold — each channel shows the numbers it was derived from.
// Half-gauge. Fill = the last 7 days on a scale from 0 to the higher of the 7-day
// ceiling and now. The only mark is the ceiling, a hollow white tick that stays
// inside the arc band (feedback railway#87/#92, percentile marks removed).
function HalfGauge({ value, scale, ceiling, col, size }: { value: number | null; scale: number; ceiling?: number | null; col: string; size: "lg" | "sm" }) {
  const lg = size === "lg"
  const W = lg ? 220 : 80, R = lg ? 90 : 32, SW = lg ? 14 : 7, cy = lg ? 108 : 40, x0 = (W - 2 * R) / 2
  const arc = `M${x0} ${cy} A${R} ${R} 0 0 1 ${x0 + 2 * R} ${cy}`
  const L = Math.PI * R
  const fr = (v: number | null | undefined) => (v == null || scale <= 0 ? 0 : Math.max(0, Math.min(1, v / scale)))
  const f = fr(value)
  const pt = (t: number, rr: number) => { const ang = Math.PI * (1 - t); return [W / 2 + rr * Math.cos(ang), cy - rr * Math.sin(ang)] }
  const ceil = (() => {
    if (ceiling == null || ceiling <= 0) return null
    const t = fr(ceiling)
    const [x1, y1] = pt(t, R - SW / 2), [x2, y2] = pt(t, R + SW / 2)
    return (
      <g>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgb(6 16 16 / .4)" strokeWidth={lg ? 5.4 : 3.5} strokeLinecap="butt" />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={C.fg} strokeWidth={lg ? 4 : 2.6} strokeLinecap="butt" />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgb(6 16 16)" strokeWidth={lg ? 1.4 : 0.9} strokeLinecap="butt" />
      </g>
    )
  })()
  return (
    <svg viewBox={`-2 -2 ${W + 4} ${lg ? 116 : 46}`} className={lg ? "w-full max-w-[230px]" : "w-[84px]"} aria-hidden>
      <path d={arc} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth={SW} strokeLinecap="butt" />
      {f > 0 && <path d={arc} fill="none" stroke={col} strokeWidth={SW} strokeLinecap="butt" strokeDasharray={`${L * f} ${L}`} />}
      {ceil}
    </svg>
  )
}
// legend swatch for the hollow ceiling mark
const CeilSw = () => (
  <svg viewBox="0 0 5 10" className="h-2.5 w-[7px] shrink-0" aria-hidden>
    <line x1="2.5" y1="0" x2="2.5" y2="10" stroke={C.fg} strokeWidth="3.6" />
    <line x1="2.5" y1="0" x2="2.5" y2="10" stroke="rgb(6 16 16)" strokeWidth="1.2" />
  </svg>
)

// feedback railway#93 — the longest safe run inside the Objem detail: every limit
// on one scale, the binding (shortest) one highlighted.
function SafeRunLimits({ limits, today }: { limits: [number, string][]; today: number | null }) {
  if (!limits.length) return null
  const bind = limits.reduce((m, x) => (x[0] < m[0] ? x : m))
  const scale = Math.max(...limits.map((x) => x[0]), 0.1)
  return (
    <div className="rounded-[14px] border border-white/[.07] bg-white/[.02] p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="flex items-center gap-1.5 whitespace-nowrap text-[12px] font-semibold text-fg-2"><MoveDiagonal className="size-3.5 text-info" aria-hidden />Nejdelší bezpečný běh</span>
        <span className="whitespace-nowrap tabular-nums text-[12px] text-fg-3">
          týden <b className="text-[15px] text-fg">≈ {num(bind[0])} km</b>{today != null ? <> · dnes <b className="text-fg">≈ {num(today)} km</b></> : null}
        </span>
      </div>
      <div className="mt-2.5 space-y-1.5">
        {limits.map(([v, label]) => {
          const on = label === bind[1]
          return (
            <div key={label} className="grid grid-cols-[1fr_auto] items-center gap-x-2 text-[11px]">
              <span className={on ? "font-semibold text-watch" : "text-fg-3"}>{label}{on ? " · omezuje" : ""}</span>
              <span className={`tabular-nums ${on ? "font-bold text-watch" : "text-fg-2"}`}>{num(v)} km</span>
              <div className="col-span-2 h-1.5 rounded-full bg-white/[.06]">
                <i className="block h-full rounded-full" style={{ width: `${Math.max(2, (v / scale) * 100)}%`, background: on ? C.watch : "rgb(181 211 202 / .45)" }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// feedback railway#65 — one interval bar: used vs total, with the numbers
function UsageBar({ label, used, total, unit, d, note, col }: { label: string; used: number | null | undefined; total: number | null | undefined; unit: string; d: number; note?: string; col?: string }) {
  if (total == null) return null
  const over = used != null && used > total
  const scale = Math.max(total, used || 0) || 1
  const c = col || (over ? C.alert : (used || 0) / (total || 1) > 0.85 ? C.watch : C.ok)
  const left = Math.max(0, total - (used || 0))
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-fg-2">{label}</span>
        <span className="tabular-nums text-fg-3"><b className="text-fg">{num(used ?? 0, d)}</b> / {num(total, d)} {unit}</span>
      </div>
      <div className="relative mt-1 h-2 rounded-full bg-white/[.08]">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, ((used || 0) / scale) * 100)}%`, background: c }} />
        <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${(total / scale) * 100}% - 1px)` }} />
      </div>
      <p className="mt-0.5 text-right tabular-nums text-[11px]" style={{ color: over ? C.alert : C.fg3 }}>{over ? `přes o ${num((used || 0) - total, d)}` : `zbývá ${num(left, d)}`}{note ? ` · ${note}` : ""}</p>
    </div>
  )
}
function TodayCapacity({ g, cycle }: { g: any; cycle?: React.ReactNode }) {
  const wk = g.week || {}
  const cyc = wk.cycle || {}
  const ax = g.axes || {}
  const th = ax.threshold ?? 25
  const loadHot = (ax.load ?? 0) >= th
  const mechHot = (ax.mech ?? 0) >= th
  const pct = Math.round((wk.progression ?? 1) * 100)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  // feedback railway#52 — the safe longest run lives here now and follows the plan:
  // the proven single-run capacity + 10 %, never above what this week / 7 days /
  // today still allow.
  const { boot } = useApp()
  const capVol = boot?.assessment?.capacity?.channels?.volume
  const vol = wk.channels?.volume || {}
  const safe = (() => {
    const base = capVol?.ceilingSession ?? boot?.assessment?.loadDetail?.safeLongRunKm
    if (base == null) return null
    const limits: [number, string][] = [[base, capVol?.ceilingSession != null ? "kapacita jednoho běhu + 10 %" : "nejdelší běh 30 dní + 10 %"]]
    if (vol.left != null) limits.push([vol.left, "zbytek cíle tohoto týdne"])
    if (vol.left7 != null) limits.push([vol.left7, "zbytek stropu 7 dní"])
    const week = Math.min(...limits.map((x) => x[0]))
    const todayCaps = [capVol?.ceilingToday, vol.todayMax].filter((v) => v != null) as number[]
    return { limits, today: todayCaps.length ? Math.min(week, ...todayCaps) : null }
  })()
  const status = loadHot
    ? { col: C.alert, text: `Zátěž ${ax.load} je nad prahem ${th} — tento týden odlehčovací, bez tvrdých úseků a dlouhého běhu.` }
    : mechHot
      ? { col: C.watch, text: `Mechanika ${ax.mech} je nad prahem ${th} — dnes o 20 % méně objemu, poloviční intenzita a klesání, raději rovina.` }
      : null   // railway#131 — nothing to say when both axes are under the threshold
  // feedback railway#94 — the channels sit one under another, each a full-width row
  const channel = (id: (typeof CH_ORDER)[number]) => {
    const c = wk.channels?.[id]
    if (!c) return null
    const d = id === "volume" ? 1 : 0
    const past6 = c.done7 != null ? c.done7 - (c.doneToday ?? 0) : null
    const ratio = c.done7 != null && c.ceiling7 ? c.done7 / c.ceiling7 : null
    const scale = Math.max(c.ceiling7 || 0, c.done7 || 0) * 1.08
    const col = id === "systemic" ? C.load : ratio == null ? C.fg3 : ratio > 1 ? C.alert : ratio > 0.85 ? C.watch : C.ok
    const big = id === "volume"
    const value = id === "systemic" ? (c.todayMax != null ? `${num(c.todayMax, 0)}` : "—") : c.todayMax != null ? `max ${num(c.todayMax, d)}` : "—"
    const isOpen = !!open[id]
    const limit = c.limitedBy ? <span className="text-[11px] font-semibold leading-4 text-watch">omezuje: {LIMIT[c.limitedBy] || c.limitedBy}</span> : null
    const ceilNote = c.ceiling7 != null && <span className="inline-flex items-center gap-1 tabular-nums text-[11px] text-fg-3"><CeilSw />strop 7 dní {num(c.ceiling7, d)} · teď {num(c.done7, d)}</span>
    const rows = (
      <div className="mt-3 w-full space-y-2.5 border-t border-white/[.07] pt-3 text-left">
        <UsageBar label="Posledních 7 dní · strop" used={c.done7} total={c.ceiling7} unit={c.unit} d={d}
          note={c.capacity != null ? `kapacita ${num(c.capacity, d)}${c.ceiling7 != null && c.ceiling7 < c.capacity ? " ↓" : ""}` : undefined} />
        <UsageBar label={`Tento týden v cyklu${cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? ` (${cyc.pos}. týden, ${pct} %)` : ""}`} used={c.done} total={c.budget} unit={c.unit} d={d} />
        {c.ceilingRun != null && <UsageBar label="Jeden běh · dnes max" used={c.todayMax} total={c.ceilingRun} unit={c.unit} d={d} col={C.info} />}
        {past6 != null && c.doneToday ? <p className="text-[11px] text-fg-3">z toho dnes {num(c.doneToday, d)} {c.unit}</p> : null}
        {id === "volume" && safe && <SafeRunLimits limits={safe.limits} today={safe.today} />}
        {/* railway#122 — the week's place in the 4-week cycle belongs to the volume */}
        {id === "volume" && cycle}
      </div>
    )
    return (
      <div key={id} className={`nest ${big ? "p-4" : "px-3.5 py-3"}`}>
        <button type="button" onClick={() => setOpen((o) => ({ ...o, [id]: !o[id] }))} aria-expanded={isOpen}
          title="Oblouk: posledních 7 dní · dutá bílá čárka: strop 7 dní · klepnutím zobrazíte výpočet" className="w-full text-left">
          {big ? (
            <span className="grid justify-items-center text-center">
              <span className="flex w-full items-center justify-between">
                <span className="t-label">{CH_ICON[id]}</span>
                <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180" : ""}`} aria-hidden />
              </span>
              <span className="relative mt-1 grid w-full justify-items-center">
                <HalfGauge value={c.done7} scale={scale} ceiling={c.ceiling7} col={col} size="lg" />
                <span className="absolute inset-x-0 bottom-1 text-center">
                  <b className="t-num text-[28px] leading-none text-fg">{value}</b>
                  <span className="text-[13px] font-semibold text-fg-3"> {c.unit}</span>
                </span>
              </span>
              <span className="mt-2 flex flex-col items-center gap-1">{limit}{ceilNote}</span>
            </span>
          ) : (
            <span className="flex items-center gap-3.5">
              <HalfGauge value={c.done7} scale={scale} ceiling={c.ceiling7} col={col} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-bold text-fg-2">{CH_ICON[id]}</span>
                <span className="mt-0.5 block"><b className="t-num text-[18px] leading-none text-fg">{value}</b> <span className="text-[11px] font-semibold text-fg-3">{c.unit}</span></span>
                <span className="mt-1 flex flex-col gap-0.5">{limit}{ceilNote}</span>
              </span>
              <ChevronDown className={`size-4 shrink-0 text-fg-3 transition ${isOpen ? "rotate-180" : ""}`} aria-hidden />
            </span>
          )}
        </button>
        {isOpen && rows}
      </div>
    )
  }
  return (
    <section className="card mt-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Dnešní kapacita</Label><InfoDot text={MI.todayCapacity} label="Dnešní kapacita" /></span>
        <span className="text-[12px] text-fg-2">kolik si dnes můžete dovolit</span>
      </div>
      {status && <p className="mt-2 flex items-start gap-2 text-[13px] leading-5 text-fg-soft" data-testid="capacity-status"><i className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: status.col }} />{status.text}</p>}
      <div className="mt-4 grid gap-3">
        {CH_ORDER.map((id) => channel(id))}
      </div>
      {cyc.next && (
        <p className="mt-3 text-[13px] leading-5 text-fg-2">
          <b className="text-fg">Příští týden:</b> {`${cyc.next.pos}. týden cyklu (${cyc.next.pct} %) — cíl objemu ≈ ${num(cyc.next.km)} km${cyc.next.pos === 1 ? ", nový cyklus na vyšší úrovni" : ""}.`} Kapacita se po každém týdnu přepočítá podle toho, co jste skutečně odběhli.
        </p>
      )}
    </section>
  )
}
const CH_ORDER = ["volume", "intensity", "descent", "ascent", "systemic"] as const
const num = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : v.toLocaleString("cs-CZ", { maximumFractionDigits: d, minimumFractionDigits: 0 })
const range = (lo?: number | null, hi?: number | null, d = 1) =>
  lo == null || hi == null ? "—" : Math.abs(lo - hi) < 0.05 ? num(hi, d) : `${num(lo, d)}–${num(hi, d)}`

function Stat({ label, value, sub, warn, text }: { label: string; value: string; sub?: string; warn?: boolean; text?: boolean }) {
  return (
    <div className="nest p-3.5">
      <p className="t-label !text-fg-3">{label}</p>
      <p className={`mt-1.5 leading-tight ${text ? "text-sm font-bold md:text-base" : "t-num whitespace-nowrap text-[20px] md:text-[22px]"}`} style={{ color: warn ? C.watch : C.fg }}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] leading-4 text-fg-2">{sub}</p>}
    </div>
  )
}

function CycleStrip({ cyc }: { cyc: any }) {
  const weeks: any[] = cyc?.weeks || []
  if (!weeks.length) return null
  const max = Math.max(1, ...weeks.map((w) => Math.max(w.km || 0, w.target || 0)))
  return (
    <div className="grid grid-cols-5 items-end gap-2">
      {weeks.map((w) => (
        <div key={w.start} className="min-w-0 text-center">
          <div className="relative mx-auto flex h-16 w-full max-w-[46px] items-end overflow-hidden rounded-[6px] bg-white/[.04]">
            <i className="relative block w-full rounded-[6px]" style={{ height: `${((w.km || 0) / max) * 100}%`, background: w.current ? C.accent : C.info, opacity: w.current ? 1 : 0.45 }} />
            {w.current && w.target != null && (
              <i className="absolute inset-x-0 bottom-0 rounded-[6px] border-[1.5px] border-dashed" style={{ height: `${(w.target / max) * 100}%`, borderColor: (w.km || 0) >= w.target ? C.ink : C.accent }} />
            )}
          </div>
          <p className={`mt-1 whitespace-nowrap tabular-nums text-[11px] ${w.current ? "font-bold text-accent" : "text-fg"}`}>{num(w.km)} km</p>
          <p className="truncate text-[11px] text-fg-3">{w.current ? (w.target != null ? `cíl ${num(w.target)}` : "tento týden") : `od ${fmtD(w.start)}`}</p>
        </div>
      ))}
    </div>
  )
}

function WeekPanel({ g, embedded = false }: { g: any; embedded?: boolean }) {
  const { me, refresh } = useApp()
  const toast = useToast()
  const wk = g.week || {}
  const cyc = wk.cycle || {}
  const [ask, setAsk] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setAsk(null) }, [cyc.pos, wk.mode])
  const pick = async (pos: number | null) => {
    if (!me?.runner_id || busy) return
    setBusy(true)
    try {
      await api.setCycle(me.runner_id, pos)
      await refresh()
      toast({ title: pos ? `Tento týden: ${pos}. týden cyklu` : "Cyklus zase běží automaticky" })
    } catch (e: any) {
      toast({ title: e?.message || "Změna se nepodařila" })
    } finally {
      setBusy(false)
      setAsk(null)
    }
  }
  // before a race the taper decides; with elevated load only a recovery week can be picked
  const locked = wk.mode === "taper" || wk.mode === "return" || !!wk.novice
  const allowed = (p: number) => !locked && (wk.mode !== "deload" || p === 4)
  const [modeLabel, modeCol] = MODE[wk.mode] || MODE.build
  const pct = Math.round((wk.progression ?? 1) * 100)
  const vol = wk.channels?.volume || {}
  const how =
    wk.mode === "build" ? `Cíl = ${pct} % referenčního týdne (${num(cyc.refKm)} km${cyc.refWeek ? `, týden od ${fmtD(cyc.refWeek)}` : ""}).`
      : wk.mode === "recovery" ? "4. týden cyklu: 55 % vrcholového týdne — tělo vstřebá předchozí tři týdny zátěže."
        : wk.mode === "deload" ? "Zátěž je zvýšená, proto odlehčovací týden hned: 55 % minulého týdne."
          : wk.mode === "taper" ? `Ladění před závodem: ${pct} % referenčního týdne.`
            : wk.mode === "return" ? `Návrat po zranění: ${pct} % průměrného týdne před zraněním (${num(cyc.refKm)} km) — 50 → 75 → 90 % během tří týdnů.`
              : wk.novice ? `Prvních 6 týdnů (do ${fmtD(wk.novice.until)}): cíl = minulý týden + 10 %, dlouhý běh nejvýš o 10 % delší než nejdelší za 30 dní. Cyklus a osobní kapacitu nastavíme potom.`
            : "Cyklus nastavíme, až budou aspoň 4 týdny dat — do té doby je cílem vaše týdenní kapacita."
  const Wrap = embedded ? "div" : "section"
  return (
    <Wrap className={embedded ? "rounded-[14px] border border-white/[.07] bg-white/[.02] p-3" : "card mt-4 p-4 md:p-6"} data-testid="week-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Cyklus · tento týden</Label><InfoDot text={MI.weekBudget} label="Týdenní cíl a cyklus" /></span>
        <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${modeCol}1f`, color: modeCol }}>
          {cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? `${cyc.pos}. týden ze 4 · ` : ""}{modeLabel}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-0.5 rounded-[14px] bg-white/[.06] p-[3px]" role="radiogroup" aria-label="Týden čtyřtýdenního cyklu">
        {CYCLE_PCT.map((p, i) => {
          const n = i + 1
          const on = cyc.pos === n
          return (
            <div key={n} className="relative">
            <button role="radio" aria-checked={on} disabled={busy || on || !allowed(n)}
              onClick={() => setAsk(n)}
              title={locked ? (wk.novice ? "Prvních 6 týdnů běží bez cyklu." : wk.mode === "return" ? "Návrat po zranění řídí týden sám." : "Před závodem řídí týden ladění formy.") : !allowed(n) ? "Zátěž je zvýšená — nejdřív odlehčovací týden." : on ? "Aktuální týden cyklu" : "Přepnout tento týden"}
              className={`w-full rounded-[11px] px-1.5 py-2 text-center text-[12px] font-bold leading-tight transition disabled:cursor-not-allowed ${on ? "!cursor-default bg-fg text-ink" : allowed(n) ? "text-fg-soft hover:bg-white/[.08]" : "text-fg-4"}`}>
              {n}. týden<span className="block text-[11px] font-medium opacity-80">{p} %</span>
            </button>
            </div>
          )
        })}
      </div>
      {/* railway#86 — how this week's target is set, outside the selector */}
      <p className="mt-1.5 flex items-center justify-end gap-1.5 text-[11px] text-fg-3">
        Jak se počítá cíl {cyc.pos ? `${cyc.pos}. týdne` : "tohoto týdne"}
        <InfoDot label="Cíl tohoto týdne" text={`${how} Cíl nikdy nepřekročí strop vaší týdenní kapacity z tabu Zátěž (${num(vol.ceiling7)} km za 7 dní).`} />
      </p>
      {ask != null && (
        <div className="nest mt-2 !border-accent/35 !bg-accent/[.06] p-3 text-[13px] leading-5 text-fg">
          Přepnout tento týden na <b>{`${ask}. týden cyklu (${CYCLE_PCT[ask - 1]} %)`}</b>{ask === 4 ? " — odlehčovací" : ""}? Týdenní cíle, dnešní limity i doporučení se hned přepočítají.
          Příští týden se cyklus nastaví sám podle toho, jak tenhle týden skutečně proběhne.
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => void pick(ask)} disabled={busy}>{busy ? "Přepočítávám…" : "Přepnout"}</Button>
            <Button size="sm" variant="secondary" onClick={() => setAsk(null)}>Zrušit</Button>
          </div>
        </div>
      )}
      {cyc.manual && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-watch">
          Ručně zvoleno pro tento týden{cyc.autoPos ? ` (automaticky by byl ${cyc.autoPos}. týden)` : ""}.
          <button onClick={() => void pick(null)} disabled={busy} className="rounded-full border border-watch/40 px-2.5 py-1 font-bold hover:bg-watch/10">Vrátit automaticky</button>
        </p>
      )}
      <div className="mt-4">
        <p className="t-label mb-2 !text-fg-3">Objem po týdnech (od pondělí)</p>
        <div className="max-w-md"><CycleStrip cyc={cyc} /></div>
      </div>
    </Wrap>
  )
}

// Plan B4 — the race calendar. A = the goal race (taper before it), B = run hard
// without a taper, C = run as training. The profile's goal race shows here too.
const PRIO: Record<string, [string, string]> = {
  A: ["A · cílový", C.accent], B: ["B · naplno bez ladění", C.ok], C: ["C · jako trénink", C.fg2],
}
const DIST = [["5", "5 km"], ["10", "10 km"], ["21.1", "půlmaraton"], ["42.2", "maraton"]]

// railway#123 — one race in detail: name, date, distance, elevation and planned pace, and in
// the race week how its distance and climb sit against this week's target and the per-run
// capacity (the same numbers as Dnešní kapacita and Zátěž).
const paceIn = (v: string) => { const m = v.trim().match(/^(\d{1,2})[:.,](\d{2})$/); return m ? +m[1] * 60 + +m[2] : null }
const hms = (sec: number) => { const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.round(sec % 60); return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}` }
function weekEnd(iso: string) {
  const d = new Date(iso + "T12:00:00")
  d.setDate(d.getDate() + (6 - ((d.getDay() + 6) % 7)))
  return d.toLocaleDateString("sv-SE")
}
// Feedback #151 — how hard to run the race: three effort levels, the one the app
// recommends from the remaining capacity, and the pace, heart rate and strategy for each.
const LEVEL_UI: Record<string, { label: string; col: string; sub: string }> = {
  "trénink": { label: "Tréninkově", col: C.ok, sub: "jako delší trénink" },
  "střední": { label: "Středně", col: C.watch, sub: "svižně, bez krajnosti" },
  naplno: { label: "Naplno", col: C.alert, sub: "závodní úsilí" },
}
function RacePlan({ rid, race }: { rid: string; race: any }) {
  const [plan, setPlan] = useState<any | null | false>(null)
  const [sel, setSel] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setPlan(null)
    api.racePlan(rid, race.id).then((p) => { if (alive) { setPlan(p || false); setSel(p?.recommended || null) } }).catch(() => alive && setPlan(false))
    return () => { alive = false }
  }, [rid, race.id, race.km, race.ascentM, race.priority, race.date])
  if (plan === null) return <p className="mt-4 text-[12px] text-fg-3">Počítám plán závodu…</p>
  if (!plan) return null
  const lv = plan.levels.find((l: any) => l.id === sel) || plan.levels[0]
  const ui = LEVEL_UI[lv.id]
  return (
    <div className="nest mt-4 p-3.5" data-testid="race-plan">
      <p className="t-label !text-fg-3">Jak závod běžet</p>
      <div className="mt-2 grid grid-cols-3 gap-1.5" role="radiogroup">
        {plan.levels.map((l: any) => {
          const u = LEVEL_UI[l.id]
          const on = l.id === lv.id
          return (
            <button key={l.id} role="radio" aria-checked={on} onClick={() => setSel(l.id)}
              className={`relative rounded-[12px] border px-2 py-2 text-left transition ${on ? "bg-white/[.06]" : "border-white/[.08] hover:border-white/20"}`}
              style={on ? { borderColor: u.col } : undefined}>
              <b className="block text-[13px]" style={{ color: on ? u.col : undefined }}>{u.label}</b>
              <span className="block text-[10.5px] leading-[13px] text-fg-3">{u.sub}</span>
              {l.id === plan.recommended && <span className="absolute -top-2 right-1.5 rounded-full bg-accent px-1.5 py-px text-[9.5px] font-extrabold text-ink">doporučeno</span>}
            </button>
          )
        })}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div><p className="t-num text-[19px]" style={{ color: ui.col }}>{lv.pace ? paceStr(lv.pace) : "—"}</p><p className="text-[10.5px] text-fg-3">tempo /km</p></div>
        <div><p className="t-num text-[19px] text-fg">{lv.time ? hms(lv.time) : "—"}</p><p className="text-[10.5px] text-fg-3">odhad času</p></div>
        <div><p className="t-num text-[19px] text-fg">{lv.hr[0]}–{lv.hr[1]}</p><p className="text-[10.5px] text-fg-3">tep</p></div>
      </div>
      <p className="mt-2 text-[12px] text-fg-2">Úsilí {lv.rpe}{lv.recoveryDays ? ` · zotavení ~${lv.recoveryDays} ${lv.recoveryDays === 1 ? "den" : lv.recoveryDays < 5 ? "dny" : "dní"}` : ""}</p>
      <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-fg-soft">
        {lv.strategy.map((t: string, i: number) => <li key={i} className="flex gap-2"><span style={{ color: ui.col }}>›</span><span>{t}</span></li>)}
      </ul>
      <p className="mt-3 border-t border-white/[.07] pt-2 text-[11px] leading-4 text-fg-3">
        Doporučení <b style={{ color: LEVEL_UI[plan.recommended]?.col }}>{LEVEL_UI[plan.recommended]?.label.toLowerCase()}</b>: {plan.why.join(" · ")}.
        {" "}{plan.paceKnown ? (lv.id === "naplno" && lv.basis ? `Tempo naplno z vašeho běhu ${fmtD(lv.basis.date)} (${String(lv.basis.km).replace(".", ",")} km) přepočtené na délku a převýšení závodu.` : "Tempa z vašeho vlastního vztahu tepu a rychlosti.") : "Na odhad tempa zatím chybí běhy s tepem."}
      </p>
    </div>
  )
}
function RaceSheet({ race, g, cap, rid, onClose, onSaved }: { race: any; g: any; cap: any; rid: string; onClose: () => void; onSaved: (races: any[]) => void }) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [f, setF] = useState({ name: race.name || "", km: race.km != null ? String(race.km).replace(".", ",") : "", ascent: race.ascentM != null ? String(Math.round(race.ascentM)) : "", pace: race.paceSKm ? paceStr(race.paceSKm) : "" })
  const [pl, pc] = PRIO[race.priority] || PRIO.B
  const inWeek = g?.date && race.daysTo >= 0 && race.date <= weekEnd(g.date)
  const capVol = cap?.channels?.volume?.ceilingSession as number | undefined
  const capAsc = cap?.channels?.ascent?.ceilingSession as number | undefined
  const vol = g?.week?.channels?.volume || {}
  const save = async () => {
    const pace = f.pace.trim() ? paceIn(f.pace) : null
    if (f.pace.trim() && pace == null) { toast({ title: "Tempo zadejte jako min:s, třeba 5:30" }); return }
    setBusy(true)
    try {
      const r = await api.updateRace(rid, race.id, { name: f.name, distance_km: f.km ? Number(f.km.replace(",", ".")) : null,
        ascent_m: f.ascent ? Number(f.ascent.replace(",", ".")) : null, target_pace_s_km: pace })
      onSaved(r.races); setEditing(false); toast({ title: "Závod uložen" })
    } catch (e: any) { toast({ title: e?.message || "Závod se nepodařilo uložit" }) } finally { setBusy(false) }
  }
  const inp = "mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg"
  const ratio = (v: number, c?: number) => (c ? v / c : null)
  const rv = race.km && capVol ? ratio(race.km, capVol) : null
  const ra = race.ascentM && capAsc ? ratio(race.ascentM, capAsc) : null
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="race-sheet">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-[12px] bg-white/[.05]" style={{ color: pc }}><Flag className="size-5" aria-hidden /></span>
          <div className="min-w-0">
            <h2 className="font-serif text-[24px] leading-tight text-fg">{race.name || (race.priority === "A" ? "Cílový závod" : "Závod")}</h2>
            <p className="mt-0.5 text-[12px] text-fg-2">{new Date(race.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · {race.daysTo === 0 ? "dnes" : race.daysTo > 0 ? `za ${race.daysTo} d` : "proběhl"}</p>
            <span className="mt-1.5 inline-block rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2.5">
          <Stat label="Délka" value={race.km ? `${num(race.km)} km` : "—"} />
          <Stat label="Převýšení" value={race.ascentM != null ? `${num(race.ascentM, 0)} m` : "—"} sub="celkové stoupání trati" />
          <Stat label="Plánované tempo" value={race.paceSKm ? `${paceStr(race.paceSKm)} /km` : "—"} />
          <Stat label="Odhad času" value={race.paceSKm && race.km ? hms(race.paceSKm * race.km) : "—"} sub={race.paceSKm && race.km ? "délka × plánované tempo" : undefined} />
        </div>
        {inWeek && race.km ? (
          <div className="nest mt-4 space-y-3 p-3.5" data-testid="race-week">
            <p className="t-label !text-fg-3">Tento týden a vaše kapacita</p>
            {g.week?.mode === "taper" && <p className="text-[13px] text-accent">Týden je v režimu ladění formy před závodem.</p>}
            {vol.budget != null && (
              <UsageBar label={`Cíl týdne (od pondělí) · závod ${num(race.km)} km`} used={(vol.done ?? 0) + race.km} total={vol.budget} unit="km" d={1}
                note={`odběhnuto ${num(vol.done ?? 0)} km + závod`} />
            )}
            {capVol != null && (
              <UsageBar label="Délka závodu · strop jednoho běhu" used={race.km} total={capVol} unit="km" d={1} col={C.info} />
            )}
            {race.ascentM != null && capAsc != null && (
              <UsageBar label="Stoupání závodu · strop jednoho běhu" used={race.ascentM} total={capAsc} unit="m" d={0} col={C.info} />
            )}
            <p className="text-[12px] leading-5 text-fg-soft">
              {rv == null ? "Kapacitu jednoho běhu zatím poznáváme." : rv <= 1 ? "Délka závodu je v rámci vaší kapacity jednoho běhu." :
                race.priority === "C" ? `Jako tréninkový závod by překročil strop jednoho běhu o ${num(race.km - capVol!)} km (×${num(rv, 2)}). Zvažte kratší trať.` :
                `Závod je o ${num(race.km - capVol!)} km delší než váš strop jednoho běhu (×${num(rv, 2)}). Závodní den je výjimka z tréninkových stropů, po něm nechte tělo zregenerovat.`}
              {ra != null && ra > 1 ? ` Stoupání přesahuje strop jednoho běhu ×${num(ra, 2)}.` : ""}
              {vol.budget != null && (vol.done ?? 0) + race.km > vol.budget ? ` Se závodem týden přesáhne cíl o ${num((vol.done ?? 0) + race.km - vol.budget)} km.` : ""}
            </p>
          </div>
        ) : race.daysTo >= 0 ? (
          <p className="mt-4 text-[12px] leading-5 text-fg-3">Porovnání s týdenním cílem a kapacitou se ukáže v týdnu závodu, kdy odpovídá aktuálním číslům.</p>
        ) : null}
        {race.daysTo >= 0 && race.km ? <RacePlan rid={rid} race={race} /> : null}
        {race.source === "calendar" ? (editing ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-[12px] font-semibold text-fg-2">Název<input className={inp} value={f.name} maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="text-[12px] font-semibold text-fg-2">Délka (km)<input className={inp} inputMode="decimal" value={f.km} onChange={(e) => setF({ ...f, km: e.target.value })} /></label>
            <label className="text-[12px] font-semibold text-fg-2">Převýšení (m)<input className={inp} inputMode="numeric" value={f.ascent} onChange={(e) => setF({ ...f, ascent: e.target.value })} /></label>
            <label className="text-[12px] font-semibold text-fg-2">Plánované tempo (min:s /km)<input className={inp} placeholder="5:30" value={f.pace} onChange={(e) => setF({ ...f, pace: e.target.value })} /></label>
            <div className="flex gap-2 sm:col-span-2">
              <Button size="sm" disabled={busy} onClick={save}>Uložit</Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)}>Zrušit</Button>
            </div>
          </div>
        ) : (
          <Button size="sm" variant="outline" className="mt-4" onClick={() => setEditing(true)} data-testid="race-edit">Upravit závod</Button>
        )) : (
          <p className="mt-4 text-[12px] text-fg-3">Závod pochází z profilu. Převýšení a tempo doplníte, když ho přidáte do kalendáře.</p>
        )}
      </div>
    </Sheet>
  )
}

function RacesCard({ outlook, g, cap }: { outlook: any; g?: any; cap?: any }) {
  const { me, refresh } = useApp()
  const rid = me?.runner_id
  const toast = useToast()
  const [races, setRaces] = useState<any[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ date: "", name: "", km: "", priority: "B" })
  const [busy, setBusy] = useState(false)
  const [openRace, setOpenRace] = useState<any | null>(null)
  useEffect(() => { if (rid) api.races(rid).then(setRaces).catch(() => setRaces([])) }, [rid, outlook?.next?.date])
  if (!rid) return null
  const save = async () => {
    if (!f.date) return
    setBusy(true)
    try {
      const r = await api.addRace(rid, { date: f.date, name: f.name || undefined, distance_km: f.km ? Number(f.km.replace(",", ".")) : null, priority: f.priority })
      setRaces(r.races); setAdding(false); setF({ date: "", name: "", km: "", priority: "B" }); refresh()
    } catch (e: any) {
      toast({ title: e?.message || "Závod se nepodařilo uložit" })
    } finally { setBusy(false) }
  }
  const del = async (id: number | string) => {
    setBusy(true)
    try { const r = await api.deleteRace(rid, id); setRaces(r.races); refresh() } finally { setBusy(false) }
  }
  const list = (races || []).filter((x) => x.daysTo >= -30)
  const warns = (outlook?.warnings || []).filter((w: any) => w.kind !== "race_day")
  const warnsFor = (date: string) => warns.filter((w: any) => w.race === date)
  const orphanWarns = warns.filter((w: any) => !(races || []).some((x: any) => x.date === w.race && x.daysTo >= -30))
  const inp = "mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg"
  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Závody</Label>
          {orphanWarns.length > 0 && <InfoDot variant="watch" label="Závody" text={<>{orphanWarns.map((w: any, i: number) => <span key={i} className="block">{w.text}</span>)}</>} />}
        </span>
        {!adding && <Button size="sm" variant="outline" icon={Plus} onClick={() => setAdding(true)}>Přidat závod</Button>}
      </div>
      {races === null ? <p className="mt-2 text-sm text-fg-3">Načítám…</p> : list.length === 0 && !adding ? (
        <p className="mt-2 text-sm text-fg-2">Zatím žádný závod. Přidejte ho — před cílovým závodem (A) plán zařadí ladění formy a hlídá, aby závod nepřišel moc brzy po jiném maximálním úsilí.</p>
      ) : (
        <ul className="mt-3 divide-y divide-white/[.06]">
          {list.map((x) => {
            const [pl, pc] = PRIO[x.priority] || PRIO.B
            return (
              <li key={x.id} className={`flex flex-wrap items-center gap-x-3 gap-y-1 py-3 ${x.daysTo < 0 ? "opacity-50" : ""}`}>
                <button type="button" onClick={() => setOpenRace(x)} data-testid="race-row" className="flex min-w-0 flex-1 items-center gap-3 text-left">
                <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-white/[.05]" style={{ color: pc }}><Flag className="size-4" aria-hidden /></span>
                <span className="min-w-0 flex-1">
                  <b className="flex items-center gap-1.5 text-sm font-bold text-fg"><span className="truncate">{x.name || (x.priority === "A" ? "Cílový závod" : "Závod")}</span>
                    {warnsFor(x.date).length > 0 && <InfoDot variant="watch" label={x.name || "Závod"} text={<>{warnsFor(x.date).map((w: any, i: number) => <span key={i} className="block">{w.text}</span>)}</>} />}</b>
                  <span className="block text-[12px] text-fg-2"><span className="tabular-nums">{fmtD(x.date)}</span>{x.km ? <> · {num(x.km)} km</> : null}{x.ascentM ? <> · ↑ {num(x.ascentM, 0)} m</> : null}{x.source === "profile" && <> · z profilu</>} · {x.daysTo === 0 ? "dnes" : x.daysTo > 0 ? `za ${x.daysTo} d` : "proběhl"}</span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
                </button>
                <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
                <button disabled={busy} onClick={() => del(x.id)} aria-label="Smazat závod" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-alert/10 hover:text-alert"><X className="size-4" aria-hidden /></button>
              </li>
            )
          })}
        </ul>
      )}
      {openRace && rid && <RaceSheet race={openRace} g={g} cap={cap} rid={rid} onClose={() => setOpenRace(null)}
        onSaved={(rs) => { setRaces(rs); setOpenRace(rs.find((r: any) => String(r.id) === String(openRace.id)) || null); refresh() }} />}
      {adding && (
        <div className="nest mt-3 grid gap-3 p-3.5 sm:grid-cols-2">
          <label className="text-[12px] font-semibold text-fg-2">Datum<input type="date" className={inp} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
          <label className="text-[12px] font-semibold text-fg-2">Název<input className={inp} value={f.name} placeholder="např. Pražský půlmaraton" maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="text-[12px] font-semibold text-fg-2">Délka (km)
            <input className={inp} inputMode="decimal" value={f.km} onChange={(e) => setF({ ...f, km: e.target.value })} />
            <span className="mt-1.5 flex flex-wrap gap-1">{DIST.map(([v, l]) => <button key={v} type="button" onClick={() => setF({ ...f, km: v })} aria-pressed={f.km === v} className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${f.km === v ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>{l}</button>)}</span>
          </label>
          <div className="text-[12px] font-semibold text-fg-2">Priorita
            <Segmented className="mt-1" size="sm" ariaLabel="Priorita závodu" options={Object.entries(PRIO).map(([k, [l]]) => [k, l] as const)} value={f.priority} onChange={(k) => setF({ ...f, priority: k })} />
            <p className="mt-1.5 text-[11px] font-normal leading-4 text-fg-3">A = hlavní cíl, 2 týdny před ním ladění formy. B = naplno, bez ladění. C = jako trénink.</p>
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button size="sm" disabled={busy || !f.date} onClick={save}>Uložit</Button>
            <Button size="sm" variant="outline" onClick={() => setAdding(false)}>Zrušit</Button>
          </div>
        </div>
      )}
    </Card>
  )
}

// The session content for one activity type: the inline card shows today's
// recommendation, the carousel opens the same for any other type (railway#119).
function SessionDetail({ g, a, kind }: { g: any; a: any; kind: string }) {
  const t = g.types[kind] || g.types[g.type]
  const cross = !!t.cross
  const run = kind !== "volno" && kind !== "závod" && !cross
  const st = g.strength || {}
  return (
    <>
      {!t.allowed && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-alert/30 bg-alert/10 px-3 py-2">
          <p className="text-[13px] font-bold text-alert-soft">Dnes nedoporučujeme: {t.why}</p>
          <WhyButton question={`Proč mi dnes nedoporučujete ${t.label.toLowerCase()}?`} context={{ kind: "type", id: kind }} />
        </div>
      )}
      {cross ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Délka" value={t.durationMin ? `${range(t.durationMin[0], t.durationMin[1], 0)} min` : "—"} sub={kind === "posilování" ? "včetně rozcvičení" : "souvislá jednotka"} />
          {t.hr ? <Stat label="Tep" value={`${t.hr[0]}–${t.hr[1]}`} sub={`tep/min · ${t.hrZones || ""}`} />
            : <Stat label="Náročnost" value={t.rpeTarget || "—"} sub="podle pocitu, 0 = klid, 10 = maximum" />}
          {t.hr && t.rpeTarget ? <Stat label="Náročnost" value={t.rpeTarget} sub="podle pocitu" /> : null}
          {kind === "posilování"
            ? <Stat label="Tento týden" value={`${st.done ?? 0} / ${st.target ?? 2}`} sub={st.target === 1 ? "závodní fáze: stačí jedno" : "posilování, dvě stačí"} warn={(st.done ?? 0) < (st.target ?? 2)} />
            : <Stat label="Běžecké km" text value="nepočítají se" sub="jen celková zátěž, bez nárazů" />}
        </div>
      ) : run ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Vzdálenost" value={`${range(t.km?.lo, t.km?.hi)} km`} sub={t.km?.max != null ? `strop dnes ${num(t.km.max)} km — nepřekračovat` : "kapacitu poznáváme"} />
          <Stat label="Čas" value={t.durationMin ? `≈ ${range(t.durationMin[0], t.durationMin[1], 0)} min` : "—"} sub="podle vašeho tempa" />
          <Stat label="Tep" value={t.hr ? `${t.hr[0]}–${t.hr[1]}` : "—"} sub={`tep/min · ${t.hrZones || ""}`} />
          <Stat label="Tempo" value={t.pace ? `${paceStr(t.pace[0])}–${paceStr(t.pace[1])}` : kind === "kvalitní" ? "dle tepu" : "—"} sub={t.pace ? `/km · ${g.hrSource === "fit" ? "z vašeho vztahu tep–tempo" : "z vašeho obvyklého tempa"}` : "úseky řiďte tepem"} />
          {kind === "kvalitní" && t.z4Target ? (
            <Stat label="Minuty v Z4+" value={`${range(t.z4Target.lo, t.z4Target.hi, 0)} min`} sub="součet tvrdých úseků" warn />
          ) : (
            <Stat label="Minuty v Z4+" value={t.z4Max != null ? `max ${num(t.z4Max, 0)}` : "—"} sub="tvrdá práce ≥ 80 % tepové rezervy" />
          )}
          <Stat label="Stoupání" value={t.ascentMax != null ? `max ${num(t.ascentMax, 0)} m` : "—"} />
          <Stat label="Klesání" value={t.descentMax != null ? `max ${num(t.descentMax, 0)} m` : "—"} sub="strmé klesání zatěžuje víc" />
          <Stat label="Terén" text value={t.terrain ? t.terrain.split(" — ")[0] : "—"} sub={t.terrain?.split(" — ")[1]} />
        </div>
      ) : (
        <p className="text-[14px] leading-6 text-fg-soft">{kind === "závod" ? ((a.races?.warnings || []).some((w: any) => w.kind === "race_day") ? "Den závodu — ale tělo dnes nehlásí plnou připravenost (viz níže). Běžte s rezervou." : "Den závodu — žádné limity. Po závodě nechte tělo pár dní regenerovat.") : "Odpočinek. Pokud chcete pohyb, zvolte lehkou chůzi, mobilitu nebo jiný sport bez nárazů a bez bolesti."}</p>
      )}
      {(run || cross) && t.notes?.length > 0 && (
        <p className="mt-4 text-[13px] leading-6 text-fg-soft">{t.notes.join(" ")}</p>
      )}
      {cross && (
        <Link to="/app/post#jiny-sport" className="btn btn-secondary btn-sm mt-4">Zapsat do deníku</Link>
      )}
    </>
  )
}

function badgeOf(g: any, k: string) {
  if (k === g.type) return ["doporučeno", "bg-accent/15 text-accent"] as const
  if (k === "posilování" && g.strength?.suggestToday) return ["vhodný den", "bg-ok/15 text-ok"] as const
  if (!g.types[k].allowed) return ["nedoporučeno", "bg-alert/15 text-alert-soft"] as const
  return null
}
function tileLine(t: any) {
  if (t.cross) return t.durationMin ? `${range(t.durationMin[0], t.durationMin[1], 0)} min` : null
  if (t.km?.lo != null && t.km?.hi != null && t.km.hi > 0) return `${range(t.km.lo, t.km.hi)} km`
  return null
}

// railway#129 — the activity carousel moves along a mild arc: the tile at the snap point
// sits on top, the ones further along dip and tilt a little, so scrolling reads as a wheel.
function useArcScroll(ref: React.RefObject<HTMLDivElement | null>, deps: unknown[]) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const kids = () => Array.from(el.children) as HTMLElement[]
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return
    let raf = 0
    const apply = () => {
      raf = 0
      const r = el.getBoundingClientRect()
      const pad = parseFloat(getComputedStyle(el).paddingLeft) || 0
      for (const c of kids()) {
        const b = c.getBoundingClientRect()
        const d = Math.max(-1.2, Math.min(1.6, (b.left - (r.left + pad)) / Math.max(1, r.width * 0.6)))
        c.style.transform = `translateY(${(d * d * 5).toFixed(1)}px) rotate(${(d * 2.2).toFixed(2)}deg)`
      }
    }
    const on = () => { if (!raf) raf = requestAnimationFrame(apply) }
    apply()
    el.addEventListener("scroll", on, { passive: true })
    window.addEventListener("resize", on)
    return () => {
      el.removeEventListener("scroll", on)
      window.removeEventListener("resize", on)
      if (raf) cancelAnimationFrame(raf)
      for (const c of kids()) c.style.transform = ""
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
}

export function Training() {
  const { boot, me, refresh, touring } = useApp()
  const rid = me?.runner_id
  const a = boot?.assessment
  const quadHist = useQuadHistory(rid)
  const g = a?.guidance
  const [sel, setSel] = useState<string | null>(null)
  const [why, setWhy] = useState(false)
  const carousel = useRef<HTMLDivElement | null>(null)
  useEffect(() => { setSel(null) }, [g?.date, g?.type])
  useArcScroll(carousel, [g?.date, g?.type, a?.engineMode, (g?.rank || []).length])
  if (!a) return <p className="text-sm text-fg-3">Načítám…</p>
  if (a.engineMode !== "v3" || !g) {
    return (
      <Card>
        <Label>Trénink</Label>
        <p className="mt-2 text-sm text-fg-2">Denní doporučení počítá Kapacitní engine. Zapnete ho v <Link to="/data" className="font-bold text-accent">Data a propojení → Engine hodnocení → Kapacitní</Link>.</p>
      </Card>
    )
  }
  const rec = g.types[g.type]
  const today = new Date(g.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
  const pat = g.pattern || {}
  // railway#119 — every type in one carousel, most to least suitable today (engine order)
  const order: string[] = (g.rank as string[] | undefined)?.filter((k) => g.types[k]) || [...ORDER, ...CROSS].filter((k) => g.types[k])
  const selT = sel ? g.types[sel] : null
  const SelIcon = sel ? TYPE_ICON[sel] || Footprints : Footprints
  const selBadge = sel ? badgeOf(g, sel) : null
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>{`Trénink · ${today}`}</Label>
          {/* railway#120 — an arrow opens the reasons under the heading */}
          <h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">
            <button type="button" onClick={() => setWhy((v) => !v)} aria-expanded={why} data-testid="why-toggle" className="flex items-center gap-2 text-left">
              {rec.label}
              <ChevronDown className={`size-6 shrink-0 text-fg-3 transition ${why ? "rotate-180 text-accent" : ""}`} aria-hidden />
            </button>
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <WhyButton question={`Proč mám dnes ${rec.label.toLowerCase()} a jak ho pojmout?`} context={{ kind: "guidance" }} label="Proč právě tohle?" />
          {g.provisional && <Chip tone="watch">předběžné · čeká na ranní data</Chip>}
          {(() => {
            const rp = g.readinessScore ?? Math.round((g.readiness ?? 1) * 100)
            const col = readinessCol(rp)
            return (
              <span className="flex items-center gap-1.5 rounded-full py-1 pl-3 pr-1.5 text-[12px] font-bold" style={{ background: `${col}1f`, color: col }}>
                připravenost {rp} %<InfoDot text={MI.readinessTraining} label="Připravenost" />
              </span>
            )
          })()}
        </div>
      </div>
      {why && (
        <div className="nest mt-3 origin-top animate-[careReveal_.28s_ease-out] p-3.5 text-[13px] leading-5 text-fg-soft" data-testid="why-panel">
          {g.reasons?.length ? (
            <span className="grid gap-1.5">{g.reasons.map((r: string, i: number) => <span key={i} className="flex gap-1.5"><ChevronRight className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden /><span>{r}</span></span>)}</span>
          ) : "Vše v normě — běžný tréninkový den."}
          <span className="mt-2 block border-t border-white/10 pt-2 text-[11px] text-fg-3">
            {pat.runDayNames?.length ? `Obvykle běháte: ${pat.runDayNames.join(", ")}` : "Pravidelné dny zatím nepoznáváme"}
            {pat.longDayName ? ` · dlouhý běh ${pat.longDayName}` : ""}
            {pat.hardDayNames?.length ? ` · tvrdé tréninky: ${pat.hardDayNames.join(", ")}` : ""}
            {pat.easyKm ? ` · typický lehký běh ${num(pat.easyKm)} km` : ""}
          </span>
        </div>
      )}

      {g.override && (
        <AlertBanner tone="stop" className="mt-5" title={g.override.title}
          action={(g.override.kind === "physio" || g.override.kind === "function" || g.override.kind === "bone_stress") ? <Link to="/app/messages" className="btn btn-primary btn-sm">Objednat fyzioterapeuta</Link>
            // railway#130 — the way to report the injury healed is always at hand; the app
            // only highlights it once the check-ins have been pain-free
            : (g.override.kind === "injury" && rid && !touring) ? <Link to="/app/messages?sub=health&healed=1" className={`btn btn-sm ${g.override.canResolve ? "btn-primary" : "btn-outline"}`} data-testid="injury-resolve">{g.override.canResolve ? "Zranění je zahojené" : "Ohlásit uzdravení"}</Link>
            : undefined}>
          {g.override.text}
        </AlertBanner>
      )}

      {g.done && (
        <AlertBanner tone="info" icon={CircleCheck} className="mt-3"
          title={<>Dnes už máte hotovo: {num(g.done.volume)} km{g.done.intensity ? ` · ${num(g.done.intensity, 0)} min v Z4+` : ""}{g.done.descent ? ` · klesání ${num(g.done.descent, 0)} m` : ""}.</>}>
          Limity níže ukazují, co ještě dnes zbývá.
        </AlertBanner>
      )}

      <section className="card mt-4 p-4 md:p-6" data-tour="training-session">
        <SessionDetail g={g} a={a} kind={g.type} />
      </section>

      {/* railway#119 — a swipeable carousel of every activity, ordered for today's capacity */}
      <div className="mt-4" data-tour="training-cross">
        <div className="mb-2 flex items-baseline justify-between gap-2">
          <p className="t-label !text-fg-3">Aktivity podle dnešní kapacity</p>
          <span className="text-[11px] text-fg-3">od nejvhodnější · posuňte</span>
        </div>
        <div ref={carousel} className="-mx-5 flex snap-x snap-mandatory gap-2 overflow-x-auto scroll-px-5 px-5 pb-4 pt-1 [scrollbar-width:none] md:-mx-0 md:px-0" role="list" aria-label="Aktivity" data-testid="activity-carousel">
          {order.map((k, i) => {
            const t = g.types[k]
            const Icon = TYPE_ICON[k] || Footprints
            const b = badgeOf(g, k)
            const line = tileLine(t)
            return (
              <button key={k} role="listitem" onClick={() => setSel(k)} data-testid="activity-tile"
                className={`relative grid min-h-[112px] w-[128px] shrink-0 snap-start content-between gap-2 rounded-[16px] border p-3 text-left transition-colors will-change-transform ${k === g.type ? "border-accent/70 bg-accent/[.08]" : "border-white/[.08] bg-white/[.03] hover:border-white/20"} ${t.allowed ? "" : "opacity-70"}`}>
                <span className="flex items-center justify-between">
                  <Icon className={`size-5 ${k === g.type ? "text-accent" : "text-fg-2"}`} aria-hidden />
                  <span className="text-[10px] font-bold tabular-nums text-fg-4">{i + 1}.</span>
                </span>
                <span className="grid gap-1">
                  <span className="text-[13px] font-bold leading-tight text-fg-soft">{t.label}</span>
                  {line && <span className="text-[11px] tabular-nums text-fg-3">{line}</span>}
                  {b && <span className={`w-fit rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none ${b[1]}`}>{b[0]}</span>}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {sel && selT && (
        <Sheet open onClose={() => setSel(null)}>
          <div data-testid="activity-sheet">
            <div className="flex items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-[12px] bg-white/[.06]"><SelIcon className="size-5 text-accent" aria-hidden /></span>
              <div className="min-w-0">
                <h2 className="font-serif text-[24px] leading-tight text-fg">{selT.label}</h2>
                <p className="text-[12px] text-fg-3">podle dnešní kapacity{selBadge ? " · " : ""}{selBadge && <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${selBadge[1]}`}>{selBadge[0]}</span>}</p>
              </div>
            </div>
            <div className="mt-4"><SessionDetail g={g} a={a} kind={sel} /></div>
          </div>
        </Sheet>
      )}

      {/* railway#142 — readiness (trend + the nights behind it) right above today's capacity */}
      <section className="card mt-4 p-4 md:p-6"><ReadinessTrend a={a} hist={quadHist} /></section>
      <TodayCapacity g={g} cycle={<WeekPanel g={g} embedded />} />
      <RacesCard outlook={a.races} g={g} cap={a.capacity} />

      <p className="mt-4 text-[11px] leading-5 text-fg-3">Došlap není zdravotnický prostředek. Doporučení jsou ochranné mantinely z vašich dat, ne léčba ani diagnóza. Při bolesti, která se vrací nebo zhoršuje, se poraďte s fyzioterapeutem.</p>
    </>
  )
}
