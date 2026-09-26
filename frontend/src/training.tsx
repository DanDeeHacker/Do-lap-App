// Engine v3 — the Trénink tab: today's session within this week's target (4-week
// loading cycle on the runner's own reference week, capped by the capacity the
// Zátěž tab shows): session type, distance, HR zone + pace, Z4+ minutes,
// ascent/descent, terrain, and why.
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { AlertBanner, Button, Card, Chip, InfoDot, Label, Segmented, useToast } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { readinessCol } from "@/capacity"
import { fmtD, paceStr } from "@/lib"
import { C } from "@/tokens"
import { ChevronDown, ChevronRight, CircleCheck, Flag, Footprints, Leaf, MoveDiagonal, Plus, Route, Sofa, X, Zap, type LucideIcon } from "lucide-react"

const ORDER = ["volno", "regenerace", "lehký", "dlouhý", "kvalitní", "závod"]
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
const TYPE_ICON: Record<string, LucideIcon> = { volno: Sofa, regenerace: Leaf, "lehký": Footprints, "dlouhý": Route, "kvalitní": Zap, "závod": Flag }

// Today's capacity: what today can hold so that the last 7 days stay within the
// weekly capacity the Zátěž tab shows, this week keeps to its place in the cycle,
// no single run exceeds its own capacity and load / mechanics stay under the
// threshold — each channel shows the numbers it was derived from.
// Half-gauge. Fill = the last 7 days; the scale runs from 0 to the highest of your
// own rolling 7-day max, the ceiling and now. Marks (feedback railway#43/#87) stay
// inside the arc band: 25th / 75th percentile of rolling 7-day totals dashed, the
// median solid and thick, your max red and thick, the 7-day ceiling a hollow white mark.
const MARK = {
  pct: { col: C.fg, w: [1.5, 1], dash: [3, 2] as [number, number] | null },
  med: { col: C.fg, w: [3.2, 2], dash: null },
  max: { col: C.alert, w: [3.2, 2], dash: null },
  ceil: { col: C.fg, w: [4, 2.6], dash: null },
}
function HalfGauge({ value, scale, ceiling, dist, col, size }: { value: number | null; scale: number; ceiling?: number | null; dist?: any; col: string; size: "lg" | "sm" }) {
  const lg = size === "lg"
  const W = lg ? 220 : 80, R = lg ? 90 : 32, SW = lg ? 14 : 7, cy = lg ? 108 : 40, x0 = (W - 2 * R) / 2
  const arc = `M${x0} ${cy} A${R} ${R} 0 0 1 ${x0 + 2 * R} ${cy}`
  const L = Math.PI * R
  const fr = (v: number | null | undefined) => (v == null || scale <= 0 ? 0 : Math.max(0, Math.min(1, v / scale)))
  const f = fr(value)
  // point on the arc at fraction t (0 = left end, 1 = right end), at radius rr
  const pt = (t: number, rr: number) => { const ang = Math.PI * (1 - t); return [W / 2 + rr * Math.cos(ang), cy - rr * Math.sin(ang)] }
  // a radial mark spanning exactly the band (butt caps, so nothing pokes out of the arc)
  const mark = (v: number | null | undefined, key: string, m: (typeof MARK)[keyof typeof MARK]) => {
    if (v == null) return null
    const t = fr(v)
    const [x1, y1] = pt(t, R - SW / 2), [x2, y2] = pt(t, R + SW / 2)
    const w = m.w[lg ? 0 : 1]
    const dash = m.dash ? (lg ? m.dash.join(" ") : m.dash.map((x) => x * 0.6).join(" ")) : undefined
    return (
      <g key={key}>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgb(6 16 16 / .4)" strokeWidth={w + (lg ? 1.4 : 0.9)} strokeLinecap="butt" />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={m.col} strokeWidth={w} strokeLinecap="butt" strokeDasharray={dash} />
        {m === MARK.ceil && <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgb(6 16 16)" strokeWidth={lg ? 1.4 : 0.9} strokeLinecap="butt" />}
      </g>
    )
  }
  return (
    <svg viewBox={`${lg ? -2 : -2} ${lg ? -2 : -2} ${W + (lg ? 4 : 4)} ${lg ? 116 : 46}`} className={lg ? "w-full max-w-[230px]" : "w-[84px]"} aria-hidden>
      <path d={arc} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth={SW} strokeLinecap="butt" />
      {f > 0 && <path d={arc} fill="none" stroke={col} strokeWidth={SW} strokeLinecap="butt" strokeDasharray={`${L * f} ${L}`} />}
      {dist && mark(dist.p25, "p25", MARK.pct)}
      {dist && mark(dist.p75, "p75", MARK.pct)}
      {dist && mark(dist.p50, "p50", MARK.med)}
      {dist && mark(dist.max, "max", MARK.max)}
      {ceiling != null && ceiling > 0 && mark(ceiling, "ceil", MARK.ceil)}
    </svg>
  )
}
// legend swatches drawn like the marks on the arc
const Sw = ({ kind }: { kind: keyof typeof MARK }) => (
  <svg viewBox="0 0 5 10" className="h-2.5 w-[7px] shrink-0" aria-hidden>
    <line x1="2.5" y1="0" x2="2.5" y2="10" stroke={MARK[kind].col} strokeWidth={kind === "pct" ? 1.2 : kind === "ceil" ? 3.6 : 2.6} strokeDasharray={MARK[kind].dash ? "2.4 1.6" : undefined} />
    {kind === "ceil" && <line x1="2.5" y1="0" x2="2.5" y2="10" stroke="rgb(6 16 16)" strokeWidth="1.2" />}
  </svg>
)
const pctRow = (dist: any, d: number, ceil?: number | null) => dist && (
  <span className="mt-1.5 flex flex-wrap justify-center gap-x-2.5 gap-y-0.5 tabular-nums text-[11px] text-fg-3">
    <span className="inline-flex items-center gap-1"><Sw kind="pct" />P25 <b className="font-bold text-fg-2">{num(dist.p25, d)}</b></span>
    <span className="inline-flex items-center gap-1"><Sw kind="med" />medián <b className="font-bold text-fg-2">{num(dist.p50, d)}</b></span>
    <span className="inline-flex items-center gap-1"><Sw kind="pct" />P75 <b className="font-bold text-fg-2">{num(dist.p75, d)}</b></span>
    <span className="inline-flex items-center gap-1"><Sw kind="max" />max <b className="font-bold text-fg-2">{num(dist.max, d)}</b></span>
    {ceil != null && <span className="inline-flex items-center gap-1"><Sw kind="ceil" />strop <b className="font-bold text-fg-2">{num(ceil, d)}</b></span>}
  </span>
)
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
function TodayCapacity({ g }: { g: any }) {
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
    const caps: [number, string][] = [[base, capVol?.ceilingSession != null ? "vaše prokázaná kapacita jednoho běhu + 10 %" : "≈ +10 % nad váš nejdelší běh 30 dní"]]
    if (vol.left != null) caps.push([vol.left, "zbytek cíle tohoto týdne v cyklu"])
    if (vol.left7 != null) caps.push([vol.left7, "zbytek stropu 7 dní"])
    const [week, why] = caps.reduce((m, x) => (x[0] < m[0] ? x : m))
    const todayCaps = [capVol?.ceilingToday, vol.todayMax].filter((v) => v != null) as number[]
    return { week, why: caps.length > 1 && why !== caps[0][1] ? `omezeno: ${why}` : why, today: todayCaps.length ? Math.min(week, ...todayCaps) : null }
  })()
  const status = loadHot
    ? { col: C.alert, text: `Zátěž ${ax.load} je nad prahem ${th} — tento týden odlehčovací, bez tvrdých úseků a dlouhého běhu.` }
    : mechHot
      ? { col: C.watch, text: `Mechanika ${ax.mech} je nad prahem ${th} — dnes o 20 % méně objemu, poloviční intenzita a klesání, raději rovina.` }
      : { col: C.ok, text: `Zátěž ${ax.load ?? 0} a mechanika ${ax.mech ?? 0} jsou pod prahem ${th} — dnešní limity drží obě osy pod prahem i po tréninku.` }
  const channel = (id: (typeof CH_ORDER)[number]) => {
    const c = wk.channels?.[id]
    if (!c) return null
    const d = id === "volume" ? 1 : 0
    const past6 = c.done7 != null ? c.done7 - (c.doneToday ?? 0) : null
    const ratio = c.done7 != null && c.ceiling7 ? c.done7 / c.ceiling7 : null
    const scale = Math.max(c.dist?.max || 0, c.ceiling7 || 0, c.done7 || 0) * 1.05
    const col = id === "systemic" ? C.load : ratio == null ? C.fg3 : ratio > 1 ? C.alert : ratio > 0.85 ? C.watch : C.ok
    const big = id === "volume"
    const value = id === "systemic" ? (c.todayMax != null ? `${num(c.todayMax, 0)}` : "—") : c.todayMax != null ? `max ${num(c.todayMax, d)}` : "—"
    const isOpen = !!open[id]
    const rows = (
      <div className="mt-3 w-full space-y-2.5 border-t border-white/[.07] pt-3 text-left">
        <UsageBar label="Posledních 7 dní · strop" used={c.done7} total={c.ceiling7} unit={c.unit} d={d}
          note={c.capacity != null ? `kapacita ${num(c.capacity, d)}${c.ceiling7 != null && c.ceiling7 < c.capacity ? " ↓" : ""}` : undefined} />
        <UsageBar label={`Tento týden v cyklu${cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? ` (${cyc.pos}. týden, ${pct} %)` : ""}`} used={c.done} total={c.budget} unit={c.unit} d={d} />
        {c.ceilingRun != null && <UsageBar label="Jeden běh · dnes max" used={c.todayMax} total={c.ceilingRun} unit={c.unit} d={d} col={C.info} />}
        {past6 != null && c.doneToday ? <p className="text-[11px] text-fg-3">z toho dnes {num(c.doneToday, d)} {c.unit}</p> : null}
      </div>
    )
    return (
      <div key={id} className={`nest ${big ? "p-4" : "p-3"}`}>
        <button type="button" onClick={() => setOpen((o) => ({ ...o, [id]: !o[id] }))} aria-expanded={isOpen}
          title="Oblouk: posledních 7 dní · čárkovaně 25. a 75. percentil 7denních součtů · silně medián · červeně maximum · dutá bílá: strop · klepnutím zobrazíte výpočet"
          className="grid w-full justify-items-center text-center">
          <span className={`flex w-full items-center justify-between ${big ? "" : "text-[12px]"}`}>
            <span className={big ? "t-label" : "font-bold text-fg-2"}>{CH_ICON[id]}</span>
            <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180" : ""}`} aria-hidden />
          </span>
          {big ? (
            <span className="relative mt-1 grid w-full justify-items-center">
              <HalfGauge value={c.done7} scale={scale} ceiling={c.ceiling7} dist={c.dist} col={col} size="lg" />
              <span className="absolute inset-x-0 bottom-1 text-center">
                <b className="t-num text-[28px] leading-none text-fg">{value}</b>
                <span className="text-[13px] font-semibold text-fg-3"> {c.unit}</span>
              </span>
            </span>
          ) : (
            <>
              <span className="mt-2"><HalfGauge value={c.done7} scale={scale} ceiling={c.ceiling7} dist={c.dist} col={col} size="sm" /></span>
              <b className="t-num mt-1 text-[16px] leading-none text-fg">{value}</b>
              <span className="mt-0.5 text-[11px] font-semibold text-fg-3">{c.unit}</span>
            </>
          )}
          {c.limitedBy ? <span className={`mt-2 text-[11px] font-semibold text-watch ${big ? "" : "leading-4"}`}>omezuje: {LIMIT[c.limitedBy] || c.limitedBy}</span> : <span className="mt-2 h-4" />}
          {pctRow(c.dist, d, c.ceiling7)}
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
      <p className="mt-2 flex items-start gap-2 text-[13px] leading-5 text-fg-soft"><i className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: status.col }} />{status.text}</p>
      {safe && (
        <div className="nest mt-3 flex items-center gap-3 px-3.5 py-3">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-info/15 text-info"><MoveDiagonal className="size-4" aria-hidden /></span>
          <p className="text-[13px] leading-5 text-fg-2">
            Bezpečný nejdelší běh tento týden: <b className="text-fg">≈ {num(safe.week)} km</b>
            <span className="block text-[11px] text-fg-3">{safe.why}{safe.today != null ? ` · dnes ≈ ${num(safe.today)} km` : ""}</span>
          </p>
        </div>
      )}
      <div className="mt-4 grid items-start gap-3 md:grid-cols-[1.1fr_1fr]">
        {channel("volume")}
        <div className="grid grid-cols-2 items-start gap-3">
          {CH_ORDER.filter((id) => id !== "volume").map((id) => channel(id))}
        </div>
      </div>
      {cyc.next && (
        <p className="mt-3 text-[13px] leading-5 text-fg-2">
          <b className="text-fg">Příští týden:</b> {cyc.next.pos}. týden cyklu ({cyc.next.pct} %) — cíl objemu ≈ {num(cyc.next.km)} km{cyc.next.pos === 1 ? ", nový cyklus na vyšší úrovni" : ""}. Kapacita se po každém týdnu přepočítá podle toho, co jste skutečně odběhli.
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

function WeekPanel({ g }: { g: any }) {
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
  return (
    <section className="card mt-4 p-4 md:p-6">
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
          Přepnout tento týden na <b>{ask}. týden cyklu ({CYCLE_PCT[ask - 1]} %)</b>{ask === 4 ? " — odlehčovací" : ""}? Týdenní cíle, dnešní limity i doporučení se hned přepočítají.
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
    </section>
  )
}

// Plan B4 — the race calendar. A = the goal race (taper before it), B = run hard
// without a taper, C = run as training. The profile's goal race shows here too.
const PRIO: Record<string, [string, string]> = {
  A: ["A · cílový", C.accent], B: ["B · naplno bez ladění", C.ok], C: ["C · jako trénink", C.fg2],
}
const DIST = [["5", "5 km"], ["10", "10 km"], ["21.1", "půlmaraton"], ["42.2", "maraton"]]

function RacesCard({ outlook }: { outlook: any }) {
  const { me, refresh } = useApp()
  const rid = me?.runner_id
  const toast = useToast()
  const [races, setRaces] = useState<any[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ date: "", name: "", km: "", priority: "B" })
  const [busy, setBusy] = useState(false)
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
                <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-white/[.05]" style={{ color: pc }}><Flag className="size-4" aria-hidden /></span>
                <span className="min-w-0 flex-1">
                  <b className="flex items-center gap-1.5 text-sm font-bold text-fg"><span className="truncate">{x.name || (x.priority === "A" ? "Cílový závod" : "Závod")}</span>
                    {warnsFor(x.date).length > 0 && <InfoDot variant="watch" label={x.name || "Závod"} text={<>{warnsFor(x.date).map((w: any, i: number) => <span key={i} className="block">{w.text}</span>)}</>} />}</b>
                  <span className="block text-[12px] text-fg-2"><span className="tabular-nums">{fmtD(x.date)}</span>{x.km ? <> · {num(x.km)} km</> : null}{x.source === "profile" && <> · z profilu</>} · {x.daysTo === 0 ? "dnes" : x.daysTo > 0 ? `za ${x.daysTo} d` : "proběhl"}</span>
                </span>
                <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
                <button disabled={busy} onClick={() => del(x.id)} aria-label="Smazat závod" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-alert/10 hover:text-alert"><X className="size-4" aria-hidden /></button>
              </li>
            )
          })}
        </ul>
      )}
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

export function Training() {
  const { boot } = useApp()
  const a = boot?.assessment
  const g = a?.guidance
  const [sel, setSel] = useState<string | null>(null)
  useEffect(() => { setSel(null) }, [g?.date, g?.type])
  if (!a) return <p className="text-sm text-fg-3">Načítám…</p>
  if (a.engineMode !== "v3" || !g) {
    return (
      <Card>
        <Label>Trénink</Label>
        <p className="mt-2 text-sm text-fg-2">Denní doporučení počítá Kapacitní engine. Zapnete ho v <Link to="/data" className="font-bold text-accent">Data a propojení → Engine hodnocení → Kapacitní</Link>.</p>
      </Card>
    )
  }
  const kind = sel || g.type
  const t = g.types[kind] || g.types[g.type]
  const today = new Date(g.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
  const run = kind !== "volno" && kind !== "závod"
  const pat = g.pattern || {}
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>{`Trénink · ${today}`}</Label>
          <h1 className="mt-1 flex items-center gap-2 font-serif text-[30px] tracking-[-.03em] md:text-4xl">{t.label}
            <InfoDot wide label="Proč" text={
              <span className="block">
                {g.reasons?.length ? (
                  <span className="grid gap-1.5">{g.reasons.map((r: string, i: number) => <span key={i} className="flex gap-1.5"><ChevronRight className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden /><span>{r}</span></span>)}</span>
                ) : "Vše v normě — běžný tréninkový den."}
                <span className="mt-2 block border-t border-white/10 pt-2 text-[11px] text-fg-3">
                  {pat.runDayNames?.length ? `Obvykle běháte: ${pat.runDayNames.join(", ")}` : "Pravidelné dny zatím nepoznáváme"}
                  {pat.longDayName ? ` · dlouhý běh ${pat.longDayName}` : ""}
                  {pat.hardDayNames?.length ? ` · tvrdé tréninky: ${pat.hardDayNames.join(", ")}` : ""}
                  {pat.easyKm ? ` · typický lehký běh ${num(pat.easyKm)} km` : ""}
                </span>
              </span>} />
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
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

      {g.override && (
        <AlertBanner tone="stop" className="mt-5" title={g.override.title}
          action={(g.override.kind === "physio" || g.override.kind === "function") ? <Link to="/app/messages" className="btn btn-primary btn-sm">Objednat fyzioterapeuta</Link> : undefined}>
          {g.override.text}
        </AlertBanner>
      )}

      {g.done && (
        <AlertBanner tone="info" icon={CircleCheck} className="mt-3"
          title={<>Dnes už máte hotovo: {num(g.done.volume)} km{g.done.intensity ? ` · ${num(g.done.intensity, 0)} min v Z4+` : ""}{g.done.descent ? ` · klesání ${num(g.done.descent, 0)} m` : ""}.</>}>
          Limity níže ukazují, co ještě dnes zbývá.
        </AlertBanner>
      )}

      {/* Session tiles: every type stays selectable, including the not-recommended ones. */}
      <div className="mt-5 grid grid-cols-3 gap-2" role="group" aria-label="Typ tréninku">
        {ORDER.filter((k) => g.types[k]).map((k) => {
          const on = k === kind
          const rec = k === g.type
          const ok = g.types[k].allowed
          const Icon = TYPE_ICON[k] || Footprints
          return (
            <button key={k} onClick={() => setSel(k)} aria-pressed={on}
              className={`relative grid min-h-[96px] content-between gap-2.5 rounded-[14px] border p-2.5 text-left transition sm:p-3 ${on ? "border-accent bg-accent/[.12]" : rec ? "border-accent/60 bg-white/[.03] hover:bg-white/[.06]" : "border-white/[.08] bg-white/[.03] hover:border-white/20"} ${ok ? "" : "opacity-70"}`}>
              <Icon className={`size-5 ${on ? "text-accent" : "text-fg-2"}`} aria-hidden />
              <span className="grid gap-1.5">
                <span className={`text-[13px] font-bold leading-tight sm:text-[14px] ${on ? "text-fg" : "text-fg-soft"}`}>{g.types[k].label}</span>
                {rec ? <span className="w-fit rounded-full bg-accent/15 px-1.5 py-0.5 text-[11px] font-bold leading-none text-accent">doporučeno</span>
                  : !ok ? <span className="w-fit rounded-full bg-alert/15 px-1.5 py-0.5 text-[11px] font-bold leading-none text-alert-soft">nedoporučeno</span> : null}
              </span>
            </button>
          )
        })}
      </div>

      <section className="card mt-4 p-4 md:p-6">
        {!t.allowed && (
          <p className="mb-4 rounded-[12px] border border-alert/30 bg-alert/10 px-3 py-2 text-[13px] font-bold text-alert-soft">Dnes nedoporučujeme: {t.why}</p>
        )}
        {run ? (
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
        {run && t.notes?.length > 0 && (
          <p className="mt-4 text-[13px] leading-6 text-fg-soft">{t.notes.join(" ")}</p>
        )}
      </section>

      <TodayCapacity g={g} />
      <WeekPanel g={g} />
      <RacesCard outlook={a.races} />

      <p className="mt-4 text-[11px] leading-5 text-fg-3">Došlap není zdravotnický prostředek. Doporučení jsou ochranné mantinely z vašich dat, ne léčba ani diagnóza. Při bolesti, která se vrací nebo zhoršuje, se poraďte s fyzioterapeutem.</p>
    </>
  )
}
