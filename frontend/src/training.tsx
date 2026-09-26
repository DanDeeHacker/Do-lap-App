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
import { ChevronDown, ChevronRight, CircleCheck, Flag, Footprints, Leaf, Plus, Route, Sofa, X, Zap, type LucideIcon } from "lucide-react"

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
// Half-gauge. Fill = the last 7 days against this channel's 7-day ceiling (how full the
// weekly capacity is); the centre shows what today can still hold.
function HalfGauge({ ratio, col, size }: { ratio: number | null; col: string; size: "lg" | "sm" }) {
  const lg = size === "lg"
  const W = lg ? 220 : 80, R = lg ? 90 : 32, SW = lg ? 14 : 7, cy = lg ? 108 : 40, x0 = (W - 2 * R) / 2
  const arc = `M${x0} ${cy} A${R} ${R} 0 0 1 ${x0 + 2 * R} ${cy}`
  const L = Math.PI * R
  const f = ratio == null ? 0 : Math.max(0, Math.min(1, ratio))
  return (
    <svg viewBox={`0 0 ${W} ${lg ? 116 : 46}`} className={lg ? "w-full max-w-[220px]" : "w-[76px]"} aria-hidden>
      <path d={arc} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth={SW} strokeLinecap="round" />
      {f > 0 && <path d={arc} fill="none" stroke={col} strokeWidth={SW} strokeLinecap="round" strokeDasharray={`${L * f} ${L}`} />}
    </svg>
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
    const col = id === "systemic" ? C.load : ratio == null ? C.fg3 : ratio > 1 ? C.alert : ratio > 0.85 ? C.watch : C.ok
    const big = id === "volume"
    const value = id === "systemic" ? (c.todayMax != null ? `${num(c.todayMax, 0)}` : "—") : c.todayMax != null ? `max ${num(c.todayMax, d)}` : "—"
    const isOpen = !!open[id]
    // Small tiles stack label over value so narrow columns stay readable.
    const rowCls = big ? "flex justify-between gap-2" : "grid gap-0.5"
    const rows = (
      <dl className="mt-3 w-full space-y-1 border-t border-white/[.07] pt-2.5 text-left text-[11px] leading-4 text-fg-3">
        {c.capacity != null && <div className={rowCls}><dt>Týdenní kapacita (Zátěž)</dt><dd className="tabular-nums text-fg-soft">{num(c.capacity, d)} · strop {num(c.ceiling7, d)}{c.ceiling7 != null && c.ceiling7 < c.capacity ? " ↓" : ""}</dd></div>}
        {past6 != null && <div className={rowCls}><dt>Posledních 6 dní{c.doneToday ? " + dnes" : ""}</dt><dd className="tabular-nums text-fg-soft">{num(c.done7, d)} → zbývá {num(c.left7, d)}</dd></div>}
        {c.budget != null && <div className={rowCls}><dt>Tento týden v cyklu{cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? ` (${cyc.pos}. týden, ${pct} %)` : ""}</dt><dd className="tabular-nums text-fg-soft">{num(c.done, d)} / {num(c.budget, d)} → zbývá {num(c.left, d)}</dd></div>}
        {c.ceilingRun != null && <div className={rowCls}><dt>Jeden běh</dt><dd className="tabular-nums text-fg-soft">max {num(c.ceilingRun, d)}</dd></div>}
      </dl>
    )
    return (
      <div key={id} className={`nest ${big ? "p-4" : "p-3"}`}>
        <button type="button" onClick={() => setOpen((o) => ({ ...o, [id]: !o[id] }))} aria-expanded={isOpen}
          title="Oblouk: posledních 7 dní proti týdennímu stropu · klepnutím zobrazíte výpočet"
          className="grid w-full justify-items-center text-center">
          <span className={`flex w-full items-center justify-between ${big ? "" : "text-[12px]"}`}>
            <span className={big ? "t-label" : "font-bold text-fg-2"}>{CH_ICON[id]}</span>
            <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180" : ""}`} aria-hidden />
          </span>
          {big ? (
            <span className="relative mt-1 grid w-full justify-items-center">
              <HalfGauge ratio={ratio} col={col} size="lg" />
              <span className="absolute inset-x-0 bottom-1 text-center">
                <b className="t-num text-[28px] leading-none text-fg">{value}</b>
                <span className="text-[13px] font-semibold text-fg-3"> {c.unit}</span>
              </span>
            </span>
          ) : (
            <>
              <span className="mt-2"><HalfGauge ratio={ratio} col={col} size="sm" /></span>
              <b className="t-num mt-1 text-[16px] leading-none text-fg">{value}</b>
              <span className="mt-0.5 text-[11px] font-semibold text-fg-3">{c.unit}</span>
            </>
          )}
          {c.limitedBy ? <span className={`mt-2 text-[11px] font-semibold text-watch ${big ? "" : "leading-4"}`}>omezuje: {LIMIT[c.limitedBy] || c.limitedBy}</span> : <span className="mt-2 h-4" />}
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
      <div className="mt-4 grid items-start gap-3 md:grid-cols-[1.1fr_1fr]">
        {channel("volume")}
        <div className="grid grid-cols-2 items-start gap-3">
          {CH_ORDER.filter((id) => id !== "volume").map((id) => channel(id))}
        </div>
      </div>
      {wk.channels?.volume?.ceiling7 != null && wk.channels.volume.ceiling7 < wk.channels.volume.capacity && (
        <p className="mt-3 text-[11px] leading-4 text-fg-3">↓ strop je nižší než kapacita: připravenost byla tento týden snížená (HRV / klidový tep / spánek mimo vaši normu), a tak se týdenní strop zmenšuje — nejvýš o 30 %.</p>
      )}
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
            <button key={n} role="radio" aria-checked={on} disabled={busy || on || !allowed(n)}
              onClick={() => setAsk(n)}
              title={locked ? (wk.novice ? "Prvních 6 týdnů běží bez cyklu." : wk.mode === "return" ? "Návrat po zranění řídí týden sám." : "Před závodem řídí týden ladění formy.") : !allowed(n) ? "Zátěž je zvýšená — nejdřív odlehčovací týden." : on ? "Aktuální týden cyklu" : "Přepnout tento týden"}
              className={`rounded-[11px] px-1.5 py-2 text-center text-[12px] font-bold leading-tight transition disabled:cursor-not-allowed ${on ? "!cursor-default bg-fg text-ink" : allowed(n) ? "text-fg-soft hover:bg-white/[.08]" : "text-fg-4"}`}>
              {n}. týden<span className="block text-[11px] font-medium opacity-80">{p} %</span>
            </button>
          )
        })}
      </div>
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
      <p className="mt-3 text-[13px] leading-5 text-fg-2">
        {how} Cíl nikdy nepřekročí strop vaší týdenní kapacity z tabu Zátěž ({num(vol.ceiling7)} km za 7 dní).
      </p>
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
  const inp = "mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg"
  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between gap-2">
        <Label>Závody</Label>
        {!adding && <Button size="sm" variant="outline" icon={Plus} onClick={() => setAdding(true)}>Přidat závod</Button>}
      </div>
      {warns.map((w: any, i: number) => (
        <AlertBanner key={i} tone="watch" className="mt-3" title={w.text} />
      ))}
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
                  <b className="block truncate text-sm font-bold text-fg">{x.name || (x.priority === "A" ? "Cílový závod" : "Závod")}</b>
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
          <h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">{t.label}</h1>
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
        {t.notes?.length > 0 && (
          <ul className="mt-4 space-y-1.5 text-[13px] text-fg-2">{t.notes.map((n: string, i: number) => <li key={i} className="flex gap-2"><i className="mt-[7px] size-1.5 shrink-0 rounded-full bg-info" />{n}</li>)}</ul>
        )}
      </section>

      <TodayCapacity g={g} />
      <WeekPanel g={g} />
      <RacesCard outlook={a.races} />

      <Card className="mt-4">
        <Label>Proč</Label>
        {g.reasons?.length ? (
          <ul className="mt-3 space-y-2.5 text-sm text-fg-soft">{g.reasons.map((r: string, i: number) => <li key={i} className="flex gap-2"><ChevronRight className="mt-0.5 size-4 shrink-0 text-info" aria-hidden /><span>{r}</span></li>)}</ul>
        ) : <p className="mt-2 text-sm text-fg-2">Vše v normě — běžný tréninkový den.</p>}
        <p className="mt-4 border-t border-white/[.07] pt-3 text-[12px] leading-5 text-fg-3">
          {pat.runDayNames?.length ? `Obvykle běháte: ${pat.runDayNames.join(", ")}` : "Pravidelné dny zatím nepoznáváme"}
          {pat.longDayName ? ` · dlouhý běh ${pat.longDayName}` : ""}
          {pat.hardDayNames?.length ? ` · tvrdé tréninky: ${pat.hardDayNames.join(", ")}` : ""}
          {pat.easyKm ? ` · typický lehký běh ${num(pat.easyKm)} km` : ""}
        </p>
      </Card>
      <p className="mt-4 text-[11px] leading-5 text-fg-3">Došlap není zdravotnický prostředek. Doporučení jsou ochranné mantinely z vašich dat, ne léčba ani diagnóza. Při bolesti, která se vrací nebo zhoršuje, se poraďte s fyzioterapeutem.</p>
    </>
  )
}
