// Owner feedback 2026-10-10 — the week's plan and the safety limits read apart:
//  • "Týden od pondělí": the calendar week's running total per channel, by where the load
//    came from (run, other sport, strength, outside training), against the week's target,
//    with today's allowance on top and what the weekly ceiling is made of;
//  • "Nevstřebaná zátěž": how the load of the last 14 days fades, against its ceiling;
//  • "Výhled na zítra": tomorrow's limits after what is still done today and the night —
//    evaluated here from the engine's coefficients (backend metrics/outlook.py, `evaluate`
//    is the reference this file mirrors; its `grid` holds the precomputed presets).
import { useState, type ReactNode } from "react"
import { InfoDot, Label, Segmented } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { C } from "@/tokens"

export const CHS = ["volume", "intensity", "descent", "ascent", "systemic"] as const
export type Ch = (typeof CHS)[number]
const CH_LABEL: Record<Ch, string> = { volume: "Objem", intensity: "Intenzita", descent: "Klesání", ascent: "Stoupání", systemic: "Celková zátěž" }
const CH_SHORT: Record<Ch, string> = { volume: "Objem", intensity: "Z4+", descent: "Klesání", ascent: "Stoupání", systemic: "Celková" }
export const DEC: Record<string, number> = { volume: 1, intensity: 0, descent: 0, ascent: 0, systemic: 0 }
export const num = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : v.toLocaleString("cs-CZ", { maximumFractionDigits: d, minimumFractionDigits: 0 })

// where a day's load came from — fixed order and colour (validated on the dark surface:
// lightness band, chroma, CVD and normal-vision separation all pass)
export const SRC = [
  { key: "run", label: "běh", col: "#7ea42c" },
  { key: "sport", label: "jiný sport", col: "#1592a6" },
  { key: "strength", label: "posilování", col: "#8f7ff2" },
  { key: "daily", label: "mimo trénink", col: "#de5a8e" },
] as const
type SrcKey = (typeof SRC)[number]["key"]
const srcOf = (k: string): SrcKey => (k === "run" ? "run" : k === "strength" ? "strength" : k === "daily" ? "daily" : "sport")

// the binding limit in words — the plan (this calendar week's target) or a safety limit
export function limitText(lim?: string | null, bound?: string | null, nextWeek = false): string | null {
  if (!lim) return null
  if (lim === "systemic") return bound === "plan" ? "cíl týdne celkové zátěže (od pondělí)" : "nevstřebaná celková zátěž (týdenní strop)"
  if (lim === "week") return nextWeek ? "cíl příštího týdne v cyklu" : "cíl týdne v cyklu (od pondělí)"
  return ({ "7d": "týdenní strop (nevstřebaná zátěž posledních dní)", run: "strop jednoho běhu", mechanics: "odchylka mechaniky" } as Record<string, string>)[lim] || lim
}
export function BoundTag({ bound }: { bound?: string | null }) {
  if (!bound) return null
  const plan = bound === "plan"
  return (
    <span className="inline-flex shrink-0 items-center rounded-full px-1.5 py-[1px] text-[10px] font-bold leading-4"
      style={{ background: `${plan ? C.info : C.watch}1f`, color: plan ? C.info : C.watch }}
      title={plan ? "Plán týdne: kolik je naplánováno, ne kolik tělo unese" : "Bezpečnostní limit: kolik tělo podle vašich dat unese"}>
      {plan ? "plán" : "bezpečnost"}
    </span>
  )
}

/* ------------------------------------------------------------------ the week from Monday */
const WD_SHORT = ["po", "út", "st", "čt", "pá", "so", "ne"]

export function WeekLoadCard({ g, cap }: { g: any; cap: any }) {
  const wk = g.week || {}
  const days: any[] = wk.days || []
  const [ch, setCh] = useState<Ch>("volume")
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const [inputs, setInputs] = useState(false)
  if (days.length !== 7 || !wk.channels) return null
  const c = wk.channels[ch] || {}
  const capW = cap?.channels?.[ch]?.week || null
  const d = DEC[ch]
  const unit = c.unit || ""
  const ti = days.findIndex((x) => x.date === g.date)
  const acc: Record<SrcKey, number> = { run: 0, sport: 0, strength: 0, daily: 0 }
  const rows = days.map((x, i) => {
    const add: Record<SrcKey, number> = { run: 0, sport: 0, strength: 0, daily: 0 }
    for (const [k, v] of Object.entries(x.by?.[ch] || {})) add[srcOf(k)] += (v as number) || 0
    const past = ti < 0 || i <= ti
    if (past) for (const s of SRC) acc[s.key] += add[s.key]
    const total = SRC.reduce((a, s) => a + acc[s.key], 0)
    return { date: x.date as string, add, cum: past ? { ...acc } : null, total: past ? total : null, dayTotal: SRC.reduce((a, s) => a + add[s.key], 0) }
  })
  const present = SRC.filter((s) => rows.some((r) => r.add[s.key] > 0))
  const done = c.done ?? rows[Math.max(0, ti)]?.total ?? 0
  const allow = c.todayMax != null && c.todayMax > 0 ? c.todayMax : 0
  const safeExtra = c.bound === "plan" && c.safeMax != null && c.safeMax > allow + 0.05 ? c.safeMax - allow : 0
  const target: number | null = c.budget ?? null
  const top = Math.max(target || 0, done + allow + safeExtra, ...rows.map((r) => r.total || 0), 0.1) * 1.1
  const h = (v: number) => `${(v / top) * 100}%`
  const nothing = rows.every((r) => !r.dayTotal) && !allow
  const hv = hover != null ? rows[hover] : null
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="week-load">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Týden od pondělí</Label><InfoDot text={MI.weekLoad} label="Týden od pondělí" /></span>
        <button type="button" onClick={() => setTable((v) => !v)} className="text-[11px] font-bold text-accent hover:underline" aria-pressed={table}>{table ? "graf" : "tabulka"}</button>
      </div>
      <Segmented size="sm" className="mt-3" ariaLabel="Kanál" value={ch} onChange={(k) => { setCh(k); setHover(null) }}
        options={CHS.filter((k) => wk.channels[k]).map((k) => [k, CH_SHORT[k]] as const)} />
      <p className="mt-3 text-[13px] leading-5 text-fg-2" data-testid="week-load-summary">
        <span>{CH_LABEL[ch]}</span><span>{" · od pondělí "}</span><b className="text-fg">{num(done, d)}</b>
        {target != null && <><span>{" z cíle "}</span><b className="text-fg">{num(target, d)}</b></>}{" "}<span>{unit}</span>
        {c.todayMax != null && <><span>{" · dnes ještě nejvýš "}</span><b className="text-fg">{num(c.todayMax, d)}</b></>}
      </p>
      {c.limitedBy && (
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] leading-4 text-fg-3">
          <span>{`omezuje: ${limitText(c.limitedBy, c.bound)}`}</span><BoundTag bound={c.bound} />
          {safeExtra > 0 && <span>{`bezpečnostní limity by dovolily ${num(c.safeMax, d)} ${unit}`}</span>}
        </p>
      )}
      {table ? (
        <table className="mt-3 w-full text-left text-[12px] tabular-nums" data-testid="week-load-table">
          <thead className="text-fg-3"><tr><th className="py-1 font-semibold">Den</th>{present.map((s) => <th key={s.key} className="py-1 text-right font-semibold">{s.label}</th>)}<th className="py-1 text-right font-semibold">od pondělí</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.date} className={`border-t border-white/[.06] ${i === ti ? "font-bold text-fg" : "text-fg-2"}`}>
                <td className="py-1">{WD_SHORT[i]}</td>
                {present.map((s) => <td key={s.key} className="py-1 text-right">{r.add[s.key] ? num(r.add[s.key], d) : "—"}</td>)}
                <td className="py-1 text-right">{r.total != null ? num(r.total, d) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative mt-4" onMouseLeave={() => setHover(null)}>
          <div className="relative h-[168px]">
            {/* the week's target: one dashed line across, labelled at the right */}
            {target != null && target > 0 && (
              <div className="pointer-events-none absolute inset-x-0 z-10 border-t-[1.5px] border-dashed" style={{ bottom: h(target), borderColor: C.fg2 }} data-testid="week-target">
                <span className="absolute -top-[17px] right-0 rounded bg-panel px-1 text-[10.5px] font-bold text-fg-2">{`cíl ${num(target, d)}`}</span>
              </div>
            )}
            <div className="absolute inset-0 grid grid-cols-7 items-end gap-1.5 border-b border-white/15">
              {rows.map((r, i) => {
                const isT = i === ti
                const future = r.cum == null
                return (
                  <button key={r.date} type="button" className="group relative flex h-full flex-col justify-end outline-none" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => setHover(hover === i ? null : i)}
                    aria-label={`${WD_SHORT[i]}: od pondělí ${r.total != null ? num(r.total, d) : "—"} ${unit}`}>
                    {isT && safeExtra > 0 && (
                      <i className="block w-full rounded-t-[4px] border border-dashed" style={{ height: h(safeExtra), borderColor: `${C.fg3}`, background: `repeating-linear-gradient(135deg, ${C.fg3}33 0 3px, transparent 3px 7px)` }} title="nad cíl týdne, jen v rámci bezpečnostních limitů" />
                    )}
                    {isT && allow > 0 && (
                      <i className={`block w-full border-[1.5px] border-dashed ${safeExtra > 0 ? "" : "rounded-t-[4px]"}`} style={{ height: h(allow), borderColor: C.accent, background: `${C.accent}14` }} data-testid="week-allow" />
                    )}
                    {!future && SRC.slice().reverse().map((s, k, arr) => {
                      const v = r.cum?.[s.key] || 0
                      if (v <= 0) return null
                      const topmost = arr.slice(0, k).every((t) => !(r.cum?.[t.key] || 0)) && !(isT && (allow > 0 || safeExtra > 0))
                      return <i key={s.key} className={`mt-[2px] block w-full ${topmost ? "rounded-t-[4px]" : ""}`} style={{ height: h(v), background: s.col, opacity: hover == null || hover === i ? 1 : 0.55 }} />
                    })}
                    {future && <i className="block h-full w-full rounded-t-[4px] bg-white/[.025]" />}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1.5 text-center text-[11px]">
            {rows.map((r, i) => <span key={r.date} className={i === ti ? "font-bold text-accent" : "text-fg-3"}>{WD_SHORT[i]}</span>)}
          </div>
          {hv && (
            <div className="pointer-events-none absolute left-1/2 top-0 z-20 w-[220px] -translate-x-1/2 rounded-[12px] border border-white/10 bg-raised/95 p-2.5 text-[11.5px] shadow-xl" data-testid="week-tip">
              <p className="font-bold text-fg">{`${WD_SHORT[hover!]} ${new Date(hv.date + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })}`}</p>
              {hv.cum == null ? <p className="mt-1 text-fg-3">Ještě nenastal.</p> : (
                <>
                  {present.filter((s) => hv.add[s.key] > 0).map((s) => (
                    <p key={s.key} className="mt-1 flex items-center justify-between gap-2 text-fg-2"><span className="flex items-center gap-1.5"><i className="size-2 rounded-full" style={{ background: s.col }} />{s.label}</span><b className="tabular-nums text-fg">{`+${num(hv.add[s.key], d)}`}</b></p>
                  ))}
                  {!hv.dayTotal && <p className="mt-1 text-fg-3">Bez zátěže v tomto kanálu.</p>}
                  <p className="mt-1.5 flex justify-between gap-2 border-t border-white/10 pt-1.5 text-fg-2"><span>od pondělí</span><b className="tabular-nums text-fg">{`${num(hv.total, d)} ${unit}`}</b></p>
                  {hover === ti && c.todayMax != null && <p className="mt-0.5 flex justify-between gap-2 text-fg-2"><span>dnes ještě nejvýš</span><b className="tabular-nums text-fg">{num(c.todayMax, d)}</b></p>}
                </>
              )}
            </div>
          )}
        </div>
      )}
      {nothing && <p className="mt-2 text-[12px] text-fg-3">Tento týden zatím žádná zátěž v tomto kanálu.</p>}
      {/* legend: always with two or more sources; the marks for today's allowance and the target */}
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-3" data-testid="week-legend">
        {present.length >= 2 && present.map((s) => <span key={s.key} className="flex items-center gap-1"><i className="size-2.5 rounded-[3px]" style={{ background: s.col }} />{s.label}</span>)}
        {present.length === 1 && <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px]" style={{ background: present[0].col }} />{present[0].label}</span>}
        {allow > 0 && <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px] border border-dashed" style={{ borderColor: C.accent }} />dnes ještě</span>}
        {safeExtra > 0 && <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px] border border-dashed" style={{ borderColor: C.fg3 }} />navíc jen volitelně</span>}
        {target != null && <span className="flex items-center gap-1"><i className="h-0 w-3 border-t-[1.5px] border-dashed" style={{ borderColor: C.fg2 }} />cíl týdne</span>}
      </div>
      <button type="button" onClick={() => setInputs((v) => !v)} aria-expanded={inputs} className="mt-3 text-[12px] font-bold text-accent hover:underline" data-testid="week-inputs-toggle">
        {inputs ? "Skrýt, z čeho cíl a strop vychází" : "Z čeho cíl a strop vychází"}
      </button>
      {inputs && <WeekInputs c={c} capW={capW} g={g} unit={unit} d={d} ch={ch} />}
    </section>
  )
}

function Row({ label, value, sub, strong }: { label: ReactNode; value: ReactNode; sub?: ReactNode; strong?: boolean }) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 py-1">
      <span className={strong ? "font-semibold text-fg-soft" : "text-fg-2"}>{label}</span>
      <span className={`tabular-nums ${strong ? "font-bold text-fg" : "text-fg"}`}>{value}</span>
      {sub && <span className="col-span-2 text-[11px] leading-4 text-fg-3">{sub}</span>}
    </div>
  )
}

const BASIS: Record<string, string> = { avg4: "průměr 4 týdnů", best: "0,9 × nejlepší týden (6 týdnů)", floor: "minimum aplikace" }
const MODE_TXT: Record<string, string> = { build: "týden cyklu", recovery: "odlehčovací týden", deload: "odlehčení (zvýšená zátěž)", taper: "ladění před závodem", return: "návrat po zranění", learning: "bez cyklu" }

// the plan and the safety ceiling side by side, with the numbers each is made of
function WeekInputs({ c, capW, g, unit, d, ch }: { c: any; capW: any; g: any; unit: string; d: number; ch: Ch }) {
  const inp = capW?.inputs
  const plan = c.plan || {}
  const cyc = g.week?.cycle || {}
  const mode = g.week?.mode
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2" data-testid="week-inputs">
      <div className="nest p-3 text-[12px]">
        <p className="flex items-center gap-1.5 font-bold text-fg"><BoundTag bound="plan" /><span>Cíl týdne (plán)</span></p>
        {c.budget != null ? (
          <div className="mt-1.5">
            <Row label="Referenční týden" value={`${num(plan.ref, d)} ${unit}`} />
            <Row label={<><span>{"× "}</span><span>{MODE_TXT[mode] || "cyklus"}</span>{cyc.pos && (mode === "build" || mode === "recovery") ? <span>{` ${cyc.pos}`}</span> : null}</>} value={`${num((plan.factor ?? 1) * 100, 0)} %`} />
            <Row label="= cíl týdne" value={`${num(c.budget, d)} ${unit}`} strong sub={plan.capped ? "omezený týdenním stropem — plán nikdy nenaplánuje víc, než tělo unese" : undefined} />
            <Row label="od pondělí hotovo" value={`${num(c.done, d)} ${unit}`} />
            <Row label="zbývá do neděle" value={`${num(c.left, d)} ${unit}`} strong />
            <p className="mt-1 text-[11px] leading-4 text-fg-3">Plán říká, kolik je rozumné tento týden udělat. Splněný cíl neznamená přetížení.</p>
          </div>
        ) : <p className="mt-1.5 text-fg-3">Pro tento kanál se týdenní cíl zatím nestanovuje.</p>}
      </div>
      <div className="nest p-3 text-[12px]">
        <p className="flex items-center gap-1.5 font-bold text-fg"><BoundTag bound="safety" /><span>Týdenní strop (bezpečnost)</span></p>
        {capW && inp ? (
          <div className="mt-1.5">
            <Row label="Týdenní kapacita" value={`${num(capW.cap, d)} ${unit}`}
              sub={<><span>{`vyšší z: průměr 4 týdnů ${num(inp.avg4, d)} · 0,9 × nejlepší týden ${num(inp.best, d)} · minimum ${num(inp.floor, d)}`}</span>{" "}<span>{`→ ${BASIS[inp.basis] || "—"}`}</span>{inp.rtr != null ? <span>{` · návrat po zranění: nejvýš ${num(inp.rtr, d)}`}</span> : null}</>} />
            <Row label="× připravenost týdne" value={num(inp.ready, 2)} sub="průměr posledních 7 dní" />
            {inp.body != null && inp.body < 0.999 && <Row label="× bolest a stav těla" value={num(inp.body, 2)} />}
            <Row label="× (1 + rezerva)" value={`+${num(inp.margin * 100, 0)} %`} />
            <Row label="= týdenní strop" value={`${num(capW.ceiling, d)} ${unit}`} strong sub="ve stejných jednotkách jako součet 7 dní" />
            <Row label="za posledních 7 dní" value={`${num(capW.now, d)} ${unit}`} />
            {capW.absorbedMax != null && (
              <Row label="nevstřebáno / strop nevstřebané zátěže" value={`${num(capW.absorbed, d)} / ${num(capW.absorbedMax, d)}`} strong
                sub="Hlídá se nevstřebaná zátěž: starší dny se počítají jen zčásti, jak je tělo vstřebává. Proto má vlastní strop, nižší než součet 7 dní." />
            )}
            {c.left7 != null && <Row label="zbývá pod stropem" value={`${num(c.left7, d)} ${unit}`} strong />}
            {c.ceilingRun != null && <Row label="strop jednoho běhu dnes" value={`${num(c.ceilingRun, d)} ${unit}`} sub="nejvíc za posledních 30 dní bez bolesti + 10 %, podle dnešní připravenosti" />}
          </div>
        ) : <p className="mt-1.5 text-fg-3">Týdenní kapacitu teprve poznáváme (stačí 4 týdny dat).</p>}
      </div>
      {capW?.series?.length > 0 && capW.absorbedMax != null && (
        <div className="nest p-3 md:col-span-2"><AbsorbedChart w={capW} unit={unit} d={d} label={CH_LABEL[ch]} /></div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ the absorbed load */
export function AbsorbedChart({ w, unit, d, label }: { w: any; unit: string; d: number; label?: string }) {
  const s: any[] = w?.series || []
  const [hover, setHover] = useState<number | null>(null)
  if (!s.length || w.absorbedMax == null) return null
  const max = w.absorbedMax
  const top = Math.max(max, ...s.map((p) => p.v || 0), 0.1) * 1.12
  const col = C.info
  const hv = hover != null ? s[hover] : null
  const lastPast = s.filter((p) => !p.rest).length - 1
  return (
    <div data-testid="absorbed-chart">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[12px] font-bold text-fg-soft">{label ? `Nevstřebaná zátěž · ${label}` : "Nevstřebaná zátěž"}</span>
        <span className="text-[11px] text-fg-3">14 dní a 3 dny volna dopředu</span>
      </div>
      <div className="relative mt-3" onMouseLeave={() => setHover(null)}>
        <div className="relative h-[120px]">
          <div className="pointer-events-none absolute inset-x-0 z-10 border-t-[1.5px]" style={{ bottom: `${(max / top) * 100}%`, borderColor: C.fg }}>
            <span className="absolute -top-[17px] left-0 rounded bg-panel px-1 text-[10.5px] font-bold text-fg">{`strop ${num(max, d)}`}</span>
          </div>
          <div className="absolute inset-0 flex items-end gap-[3px] border-b border-white/15">
            {s.map((p, i) => (
              <button key={p.date} type="button" className="relative flex h-full flex-1 flex-col justify-end outline-none" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => setHover(hover === i ? null : i)}
                aria-label={`${p.date}: ${num(p.v, d)} ${unit}`}>
                <i className="block w-full rounded-t-[4px]" style={{ height: `${Math.max(1.5, ((p.v || 0) / top) * 100)}%`, background: p.rest ? "transparent" : col, border: p.rest ? `1.5px dashed ${col}` : undefined, opacity: hover == null || hover === i ? 1 : 0.6, outline: i === lastPast ? `1.5px solid ${C.fg}` : undefined, outlineOffset: 1 }} />
              </button>
            ))}
          </div>
        </div>
        <div className="relative mt-1 h-4 text-[10.5px] text-fg-3">
          <span className="absolute left-0">{new Date(s[0].date + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })}</span>
          <span className="absolute -translate-x-1/2 font-bold text-fg-2" style={{ left: `${((lastPast + 0.5) / s.length) * 100}%` }}>dnes</span>
          <span className="absolute right-0">{new Date(s[s.length - 1].date + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })}</span>
        </div>
        {hv && (
          <div className="pointer-events-none absolute left-1/2 top-0 z-20 -translate-x-1/2 rounded-[10px] border border-white/10 bg-raised/95 px-2.5 py-1.5 text-[11.5px] shadow-xl">
            <span className="text-fg-2">{new Date(hv.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric" })}</span>
            <b className="ml-2 tabular-nums text-fg">{`${num(hv.v, d)} ${unit}`}</b>
            {hv.rest && <span className="ml-1 text-fg-3">· bez tréninku</span>}
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-3">
        <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px]" style={{ background: col }} />nevstřebáno na konci dne</span>
        <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px] border border-dashed" style={{ borderColor: col }} />odhad bez dalšího tréninku</span>
        <span className="flex items-center gap-1"><i className="h-0 w-3 border-t-[1.5px]" style={{ borderColor: C.fg }} />dnešní strop</span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ tomorrow */
type Act = { runKm?: number; z4?: number; rideMin?: number; swimMin?: number }
type Ev = { max: number | null; lim: string | null; bound: string | null; safe: number | null }

export function loadOf(ol: any, act: Act): Record<string, number> {
  const cv = ol.conv || {}
  const km = act.runKm || 0, z4 = act.z4 || 0
  return {
    volume: km, intensity: z4, descent: km * (cv.descPerKm || 0), ascent: km * (cv.ascPerKm || 0),
    systemic: km * (cv.runPerKm || 0) + z4 * Math.max(0, (cv.z4PerMin || 0) - (cv.easyPerMin || 0))
      + (act.rideMin || 0) * (cv.perMinRide || 0) + (act.swimMin || 0) * (cv.perMinSwim || 0),
  }
}

// mirrors outlook.evaluate (backend): today's rules on the n-th day from today
export function evaluate(ol: any, x: Record<string, number>, night: string, n = 1): Record<string, Ev> {
  const out: Record<string, Ev> = {}
  const newWeek = n >= ol.toMonday
  for (const [c, ch] of Object.entries<any>(ol.channels || {})) {
    const nb = ch.byNight[night]
    const xc = x[c] || 0
    const room = nb.terms ? Math.max(0, Math.max(...nb.terms.map(([mx, b, q]: number[]) => mx - (b + xc) * q ** n))) : null
    const plan = newWeek ? ch.planNext : ch.planLeft == null ? null : Math.max(0, ch.planLeft - xc)
    const lims = ([["week", plan], ["7d", room], ["run", nb.run]] as [string, number | null][]).filter(([, v]) => v != null) as [string, number][]
    // on a tie the safety limit is the one named (as in the engine)
    const best = lims.length ? lims.reduce((m, l) => (l[1] < m[1] || (l[1] === m[1] && m[0] === "week") ? l : m)) : null
    const safe = [room, nb.run].filter((v) => v != null) as number[]
    out[c] = { max: best ? best[1] : null, lim: best ? best[0] : null, bound: best ? (best[0] === "week" ? "plan" : "safety") : null, safe: safe.length ? Math.min(...safe) : null }
  }
  if (!ol.novice && out.systemic) {
    const cv = ol.conv || {}, sys = out.systemic
    for (const [c, per] of [["volume", cv.perKm], ["intensity", cv.z4PerMin]] as [string, number | null][]) {
      if (!per || !out[c]) continue
      if (sys.max != null && (out[c].max == null || sys.max / per < out[c].max!)) out[c] = { ...out[c], max: sys.max / per, lim: "systemic", bound: sys.bound }
      if (sys.safe != null && (out[c].safe == null || sys.safe / per < out[c].safe!)) out[c].safe = sys.safe / per
    }
    const vol = out.volume
    for (const c of ["descent", "ascent"]) {
      const p90 = cv.hillP90?.[c]
      if (p90 != null && vol?.lim === "systemic" && vol.max != null && out[c] && (out[c].max == null || vol.max * p90 < out[c].max!))
        out[c] = { ...out[c], max: vol.max * p90, lim: "systemic", bound: vol.bound }
    }
  }
  for (const [c, f] of Object.entries<number>(ol.drift || {})) {
    if (!out[c]) continue
    if (out[c].max != null) out[c] = { ...out[c], max: out[c].max! * f, lim: "mechanics", bound: "safety" }
    if (out[c].safe != null) out[c].safe = out[c].safe! * f
  }
  return out
}

function verdict(ol: any, x: Record<string, number>, night: string) {
  const ev = evaluate(ol, x, night)
  const score = (ol.nights || []).find((n: any) => n.key === night)?.score ?? 100
  const vol = ev.volume?.max, z4 = ev.intensity?.max
  const hard = ol.hard || {}
  const hardToday = (x.intensity || 0) >= (hard.z4Min ?? 10)
  const age = hardToday ? 0 : hard.lastAge
  const gapOk = age == null || age + 1 >= (hard.gap ?? 2)
  const run = vol == null || vol >= ol.minRunKm
  return {
    ev, run, gapOk, score,
    quality: !!(z4 != null && z4 >= (hard.z4Min ?? 10) && gapOk && score >= (hard.readyQuality ?? 65) && (vol == null || vol >= Math.max(ol.minRunKm, 0.5 * (ol.baseKm || 0)))),
    long: !!((vol == null || vol >= 1.2 * (ol.baseKm || 0)) && score >= (hard.readyQuality ?? 65)),
  }
}

function nextRunDay(ol: any, x: Record<string, number>, night: string) {
  for (let n = 2; n <= 7; n++) {
    const v = evaluate(ol, x, night, n).volume
    if (v && (v.max == null || v.max >= ol.minRunKm)) {
      const dt = new Date(ol.date + "T12:00:00")
      dt.setDate(dt.getDate() + n - 1)
      return { date: dt, km: v.max, lim: v.lim, newWeek: n >= ol.toMonday }
    }
  }
  return null
}

const KIND_LABEL: Record<string, string> = { regenerace: "Regenerační běh", "lehký": "Lehký běh", "dlouhý": "Dlouhý běh", "kvalitní": "Kvalitní trénink", kolo: "Kolo", voda: "Plavání" }

function presetLabel(p: any): ReactNode {
  if (p.key === "none") return "Dnes už nic dalšího"
  const a = p.act || {}
  const what = p.key === "extra" ? "Volitelný regenerační běh" : p.key === "rec" ? `Doporučené: ${(KIND_LABEL[p.kind] || p.kind || "").toLowerCase()}` : KIND_LABEL[p.kind] || p.kind
  const size = a.runKm ? `${num(a.runKm)} km${a.z4 ? ` · ${num(a.z4, 0)} min Z4+` : ""}` : a.rideMin ? `${num(a.rideMin, 0)} min` : a.swimMin ? `${num(a.swimMin, 0)} min` : ""
  return <><span>{what}</span>{size && <span className="text-fg-3">{` · ${size}`}</span>}</>
}

function Slider({ label, value, onChange, max, step, unit }: { label: string; value: number; onChange: (v: number) => void; max: number; step: number; unit: string }) {
  return (
    <label className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 text-[12px]">
      <span className="text-fg-2">{label}</span>
      <b className="tabular-nums text-fg">{`${num(value, step < 1 ? 1 : 0)} ${unit}`}</b>
      <input type="range" min={0} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="col-span-2 w-full accent-[#c7ff54]" aria-label={label} />
    </label>
  )
}

export function TomorrowCard({ g }: { g: any }) {
  const ol = g.outlook
  const presets: any[] = ol?.presets || []
  const [pk, setPk] = useState<string>("none")
  const [night, setNight] = useState<string>("today")
  const [custom, setCustom] = useState<Act>({ runKm: 0, z4: 0, rideMin: 0, swimMin: 0 })
  if (!ol?.channels) return null
  const preset = presets.find((p) => p.key === pk)
  const x = pk === "custom" ? loadOf(ol, custom) : preset?.x || {}
  const v = verdict(ol, x, night)
  const dt = new Date(ol.date + "T12:00:00")
  const tomorrow = dt.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" })
  const newWeek = ol.toMonday === 1
  const vol = v.ev.volume
  const later = !v.run ? nextRunDay(ol, x, night) : null
  const todayCh = g.week?.channels || {}
  const nights: any[] = ol.nights || []
  const shown = (["volume", "intensity", "descent", "ascent", "systemic"] as const).filter((c) => v.ev[c] && todayCh[c])
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="tomorrow">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Výhled na zítra</Label><InfoDot text={MI.tomorrow} label="Výhled na zítra" /></span>
        <span className="text-[12px] text-fg-2">{tomorrow}{newWeek ? " · nový týden" : ""}</span>
      </div>
      <p className="mt-3 text-[12px] font-semibold text-fg-3">Co ještě dnes</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5" role="group" aria-label="Co ještě dnes">
        {[...presets.map((p) => [p.key, presetLabel(p)] as const), ["custom", "Vlastní…"] as const].map(([k, l]) => (
          <button key={k} type="button" aria-pressed={pk === k} onClick={() => setPk(k)} data-testid={`tomorrow-preset-${k}`}
            className={`rounded-full border px-3 py-1.5 text-left text-[12px] font-semibold transition ${pk === k ? "border-fg bg-fg text-ink [&_span]:!text-ink/70" : "border-white/10 bg-white/[.03] text-fg-2 hover:text-fg"}`}>
            {l}
          </button>
        ))}
      </div>
      {pk === "custom" && (
        <div className="nest mt-2 grid gap-3 p-3 sm:grid-cols-2" data-testid="tomorrow-custom">
          <Slider label="Běh" value={custom.runKm || 0} onChange={(n) => setCustom((c) => ({ ...c, runKm: n, z4: Math.min(c.z4 || 0, Math.round(n * 6)) }))} max={30} step={0.5} unit="km" />
          <Slider label="z toho tvrdě (Z4+)" value={custom.z4 || 0} onChange={(n) => setCustom((c) => ({ ...c, z4: n }))} max={Math.max(0, Math.min(60, Math.round((custom.runKm || 0) * 6)))} step={1} unit="min" />
          <Slider label="Kolo v Z2" value={custom.rideMin || 0} onChange={(n) => setCustom((c) => ({ ...c, rideMin: n }))} max={180} step={5} unit="min" />
          <Slider label="Plavání v klidném tempu" value={custom.swimMin || 0} onChange={(n) => setCustom((c) => ({ ...c, swimMin: n }))} max={90} step={5} unit="min" />
        </div>
      )}
      <p className="mt-3 text-[12px] font-semibold text-fg-3">Jaká bude noc</p>
      <Segmented size="sm" className="mt-1.5" ariaLabel="Noc" value={night} onChange={setNight}
        options={nights.map((n) => [n.key, n.key === "today" ? `jako dnes · ${n.score} %` : n.key === "good" ? "dobrá" : `slabší · ${n.score} %`] as const)} />

      <div className="nest mt-4 p-3.5" data-testid="tomorrow-verdict">
        <p className="text-[15px] font-bold leading-6 text-fg">
          {v.run ? <><span>Zítra běh do </span><span className="tabular-nums">{num(vol?.max, 1)}</span><span> km</span></> : <span>Zítra bez běhu</span>}
        </p>
        {!v.run && vol?.lim && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] text-fg-2"><span>{`omezuje: ${limitText(vol.lim, vol.bound, newWeek)}`}</span><BoundTag bound={vol.bound} /></p>
        )}
        {v.run && vol?.lim && vol.bound === "plan" && vol.safe != null && vol.safe > (vol.max || 0) + 0.5 && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] text-fg-2"><span>{`omezuje: ${limitText(vol.lim, vol.bound, newWeek)}`}</span><BoundTag bound={vol.bound} /><span className="text-fg-3">{`bezpečnostně až ${num(vol.safe)} km`}</span></p>
        )}
        {!v.run && vol?.bound === "plan" && vol.safe != null && vol.safe >= ol.minRunKm && (
          <p className="mt-1 text-[12px] text-fg-3">{`Je to plán týdne, ne strop — bezpečnostní limity by dovolily až ${num(vol.safe)} km, pokud bude připravenost aspoň 80 %.`}</p>
        )}
        {later && <p className="mt-1 text-[12px] text-fg-2">{`Nejbližší den s prostorem na běh: ${later.date.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" })} · ≈ ${num(later.km)} km${later.newWeek ? " (nový týden)" : ""}`}</p>}
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11.5px] font-bold">
          <span className={`rounded-full px-2 py-0.5 ${v.quality ? "bg-ok/15 text-ok" : "bg-white/[.06] text-fg-3"}`}>{v.quality ? "kvalitní trénink možný" : "bez kvalitního tréninku"}</span>
          <span className={`rounded-full px-2 py-0.5 ${v.long && v.run ? "bg-ok/15 text-ok" : "bg-white/[.06] text-fg-3"}`}>{v.long && v.run ? "dlouhý běh možný" : "bez dlouhého běhu"}</span>
        </div>
        {!v.quality && v.run && (
          <p className="mt-1.5 text-[11.5px] leading-4 text-fg-3">
            {!v.gapOk ? "Mezi tvrdými tréninky aspoň 48 hodin." : v.score < (ol.hard?.readyQuality ?? 65) ? `Na tvrdý trénink je potřeba připravenost aspoň ${ol.hard?.readyQuality ?? 65} %.`
              : (vol?.max ?? 99) < 0.5 * (ol.baseKm || 0) ? "Na kvalitní trénink zítra nezbude dost kilometrů." : "Na tvrdé minuty (aspoň 10 min v Z4+) zítra nezbude prostor."}
          </p>
        )}
      </div>

      <div className="mt-3 grid gap-2.5" data-testid="tomorrow-channels">
        {shown.map((c) => {
          const e = v.ev[c]
          const t = todayCh[c]
          const d = DEC[c]
          const scale = Math.max(e.max || 0, t.todayMax || 0, e.bound === "plan" ? e.safe || 0 : 0, 0.1) * 1.05
          return (
            <div key={c}>
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="font-bold text-fg-soft">{CH_LABEL[c]}</span>
                <span className="tabular-nums text-fg-3"><span>zítra </span><b className="text-fg">{num(e.max, d)}</b>{" "}<span>{t.unit}</span><span>{" · dnes "}</span><span>{num(t.todayMax, d)}</span></span>
              </div>
              <div className="relative mt-1 h-2 rounded-full bg-white/[.07]">
                {e.bound === "plan" && e.safe != null && e.safe > (e.max || 0) && (
                  <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(e.safe / scale) * 100}%`, background: `repeating-linear-gradient(135deg, ${C.fg3}55 0 3px, transparent 3px 7px)` }} />
                )}
                <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(e.max ? 2 : 0, ((e.max || 0) / scale) * 100)}%`, background: (e.max || 0) <= 0 ? C.watch : C.ok }} />
                {t.todayMax != null && <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg/80" style={{ left: `calc(${(Math.min(t.todayMax, scale) / scale) * 100}% - 1px)` }} title="dnešní maximum" />}
              </div>
              {e.lim && <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] leading-4 text-fg-3"><span>{`omezuje: ${limitText(e.lim, e.bound, newWeek)}`}</span><BoundTag bound={e.bound} /></p>}
            </div>
          )
        })}
      </div>
      <p className="mt-3 text-[11px] leading-4 text-fg-3">
        Odhad podle stejných pravidel jako dnešní kapacita: co dnes ještě přidáte, se přes noc vstřebá jen zčásti (svaly a šlachy asi o pětinu za noc, srdce a plíce podle toho, jak se vyspíte), cíl týdne se sníží o to, co dnes uděláte, a v pondělí začne nový. Ráno ho upřesní skutečná noc z hodinek.
      </p>
    </section>
  )
}
