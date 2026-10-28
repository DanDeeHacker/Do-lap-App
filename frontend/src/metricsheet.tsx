// v0.12.13 — one detail sheet for every number card (Dnes → Moje čísla, the desktop rail): the
// latest value, the trend over 7 days to 6 months, min / average / max of the range and, where
// the app knows it, the runner's own usual range or the threshold. One pattern instead of a
// different trend card per metric (NOOP's metric screens).
import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router"
import { ChevronRight } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { useQuadHistory } from "@/history"
import { AxisLineChart, Label, Segmented, Sheet } from "@/ui"
import { readinessPct } from "@/capacity"
import { C } from "@/tokens"

export const METRIC_IDS = ["readiness", "load", "mech", "hrv", "rhr", "sleep", "week", "form", "fit", "fat"] as const
export type MetricId = (typeof METRIC_IDS)[number]
const RANGES = [["7", "7 dní"], ["30", "1 měsíc"], ["91", "3 měsíce"], ["183", "6 měsíců"]] as const
type Range = (typeof RANGES)[number][0]

type Def = { label: string; unit: string; dec: number; to: string; tab: string; about: string; source: "daily" | "hist" | "acts" | "fit";
  field?: string; yMin?: number; yMax?: number; threshold?: number; weekly?: boolean }
const DEFS: Record<MetricId, Def> = {
  readiness: { label: "Připravenost", unit: " %", dec: 0, to: "/app/training", tab: "Trénink", source: "hist", field: "readinessMorning", yMin: 0, yMax: 100,
    about: "Ranní připravenost po noci: HRV, klidový tep a spánek proti vaší normě." },
  load: { label: "Zátěž", unit: "", dec: 0, to: "/app/load", tab: "Zátěž", source: "hist", field: "load", yMin: 0, yMax: 100, threshold: 25,
    about: "Skóre zátěže 0–100. Nad prahem 25 je zátěž proti vaší obvyklé úrovni zvýšená." },
  mech: { label: "Mechanika", unit: "", dec: 0, to: "/app/mechanics", tab: "Mechanika", source: "hist", field: "mech", yMin: 0, yMax: 100, threshold: 25,
    about: "Jak se technika běhu odchyluje od vaší normy. Nad prahem 25 je odchylka výrazná." },
  hrv: { label: "HRV", unit: " ms", dec: 0, to: "/app/training", tab: "Trénink", source: "daily", field: "hrv_ms",
    about: "Variabilita srdečního tepu ve spánku. Vyšší než obvykle bývá po dobrém zotavení, nižší po zátěži, nemoci nebo stresu." },
  rhr: { label: "Klidový tep", unit: " tep/min", dec: 0, to: "/app/training", tab: "Trénink", source: "daily", field: "resting_hr",
    about: "Tep v klidu během noci. Několik nocí nad obvyklým rozmezím bývá známkou únavy nebo nastupující nemoci." },
  sleep: { label: "Spánek", unit: " h", dec: 1, to: "/app/training", tab: "Trénink", source: "daily", field: "sleep_h",
    about: "Délka spánku z hodinek. Rozhoduje vaše obvyklá délka, ne obecných 8 hodin." },
  week: { label: "Kilometry týdně", unit: " km", dec: 1, to: "/app/load", tab: "Zátěž", source: "acts", weekly: true,
    about: "Součet naběhaných kilometrů v každém týdnu (pondělí až neděle)." },
  // feedback #222 — the fitness trend of Trénink → Tělo a den, as cards
  form: { label: "Čerstvost", unit: " %", dec: 0, to: "/app/training", tab: "Trénink", source: "fit", field: "form",
    about: "Kondice minus Únava jako podíl Kondice. Kladná = poslední dny jste zatěžovali méně, než jste zvyklí. Záporná = poslední týden byl nad vaším průměrem." },
  fit: { label: "Kondice", unit: "", dec: 0, to: "/app/training", tab: "Trénink", source: "fit", field: "fit",
    about: "Průměr celkové zátěže všech aktivit za zhruba 6 týdnů. Pomalu se mění, ukazuje, na co jste zvyklí." },
  fat: { label: "Únava", unit: "", dec: 0, to: "/app/training", tab: "Trénink", source: "fit", field: "fat",
    about: "Průměr celkové zátěže všech aktivit za zhruba týden. Stoupá po náročných dnech a klesá, když zatížení povolí." },
}
const FIT_IDS: readonly string[] = ["form", "fit", "fat"]
export const isFitId = (id: string) => FIT_IDS.includes(id)

// the fitness trend (days + today + bands), one request per assessment, shared by the sheet, the
// tiles and their trend lines; rows get `date` so they read like the other sources
let fitCache: { key: string; data: any } | null = null
let fitInflight: { key: string; p: Promise<any> } | null = null
function loadFit(rid: string, asOf: string): Promise<any> {
  const key = `${rid}|${asOf}`
  if (fitCache?.key === key) return Promise.resolve(fitCache.data)
  if (fitInflight?.key === key) return fitInflight.p
  const p = api.fitnessTrend(rid).then((d: any) => {
    const data = d && d.available ? { ...d, days: (d.days || []).map((x: any) => ({ ...x, date: x.d })) } : { available: false, days: [] }
    fitCache = { key, data }
    return data
  }).catch(() => ({ available: false, days: [] })).finally(() => { if (fitInflight?.key === key) fitInflight = null })
  fitInflight = { key, p }
  return p
}
export function useFitnessTrend(rid: string, asOf: string, enabled = true): any | null {
  const key = `${rid}|${asOf}`
  const [data, setData] = useState<any | null>(fitCache?.key === key ? fitCache.data : null)
  useEffect(() => {
    if (!enabled || !rid) return
    let alive = true
    loadFit(rid, asOf).then((d) => alive && setData(d))
    return () => { alive = false }
  }, [rid, asOf, enabled])
  return data
}
// the usual range the readiness uses (mean ± 1 SD of the nights 8–56 days back)
const RANGE_KEY: Partial<Record<MetricId, string>> = { hrv: "hrv", rhr: "rhr", sleep: "sleep" }

const iso = (d: Date) => d.toLocaleDateString("sv-SE")
const monday = (s: string) => { const d = new Date(s.slice(0, 10) + "T12:00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d) }
const nf = (v: number, dec: number) => v.toLocaleString("cs-CZ", { maximumFractionDigits: dec, minimumFractionDigits: dec })

// half a year of nights (HRV, resting HR, sleep), one request per assessment, shared by the
// sheet and the tiles' trend lines
let dailyCache: { key: string; rows: any[] } | null = null
let dailyInflight: { key: string; p: Promise<any[]> } | null = null
function loadDaily(rid: string, asOf: string): Promise<any[]> {
  const key = `${rid}|${asOf}`
  if (dailyCache?.key === key) return Promise.resolve(dailyCache.rows)
  if (dailyInflight?.key === key) return dailyInflight.p
  const p = api.daily(rid, 183).then((rows: any) => {
    const r = Array.isArray(rows) ? [...rows].sort((x, y) => String(x.date).localeCompare(String(y.date))) : []
    dailyCache = { key, rows: r }
    return r
  }).catch(() => [] as any[]).finally(() => { if (dailyInflight?.key === key) dailyInflight = null })
  dailyInflight = { key, p }
  return p
}
export function useDailyRows(rid: string, asOf: string, enabled = true): any[] | null {
  const key = `${rid}|${asOf}`
  const [rows, setRows] = useState<any[] | null>(dailyCache?.key === key ? dailyCache.rows : null)
  useEffect(() => {
    if (!enabled || !rid) return
    let alive = true
    loadDaily(rid, asOf).then((r) => alive && setRows(r))
    return () => { alive = false }
  }, [rid, asOf, enabled])
  return rows
}

/** Running km per week (Monday–Sunday), the last `weeks` weeks, oldest first. */
export function weeklyKm(acts: any[], weeks: number): { t: string; v: number }[] {
  const wk = new Map<string, number>()
  for (const x of acts || []) {
    if ((x.sport && x.sport !== "running") || x.excluded || !x.started_at) continue
    const m = monday(String(x.started_at))
    wk.set(m, (wk.get(m) || 0) + (x.distance_km || 0))
  }
  const out: { t: string; v: number }[] = []
  const d = new Date(monday(iso(new Date())) + "T12:00:00")
  for (let k = weeks - 1; k >= 0; k--) { const m = new Date(d); m.setDate(d.getDate() - 7 * k); const s = iso(m); out.push({ t: s, v: Math.round((wk.get(s) || 0) * 10) / 10 }) }
  return out
}

const valueOf = (id: string, def: Def, r: any) => (r ? (r[def.field!] ?? (id === "readiness" ? r.readiness : null)) ?? null : null) as number | null

/** v0.12.14 — the tiles' trend lines (NOOP's stat tiles): the last 14 days of each number,
 *  weekly km over the last 8 weeks. {card id: values, oldest first; null = a day without data}. */
export function useTileTrends(ids: string[]): Record<string, (number | null)[]> {
  const { me, boot } = useApp()
  const rid = me?.runner_id || ""
  const asOf = boot?.assessment?.computed_at || ""
  const metric = ids.filter((id): id is MetricId => (METRIC_IDS as readonly string[]).includes(id))
  const daily = useDailyRows(rid, asOf, metric.some((id) => DEFS[id].source === "daily"))
  const hist = useQuadHistory(rid)
  const fit = useFitnessTrend(rid, asOf, metric.some((id) => DEFS[id].source === "fit"))
  const key = metric.join(",")
  return useMemo(() => {
    const out: Record<string, (number | null)[]> = {}
    const days = Array.from({ length: 14 }, (_, k) => iso(new Date(Date.now() - (13 - k) * 86400000)))
    for (const id of metric) {
      const def = DEFS[id]
      if (def.source === "acts") { out[id] = weeklyKm(boot?.activities || [], 8).map((p) => p.v); continue }
      const rows = def.source === "hist" ? hist : def.source === "fit" ? fit?.days : daily
      if (!rows) continue
      const by = new Map(rows.map((r: any) => [String(r.date).slice(0, 10), r]))
      out[id] = days.map((d) => valueOf(id, def, by.get(d)))
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, hist, daily, fit, boot?.activities])
}

export function MetricSheet({ id, onClose }: { id: MetricId; onClose: () => void }) {
  const { me, boot } = useApp()
  const rid = me?.runner_id || ""
  const def = DEFS[id]
  const a = boot?.assessment
  const hist = useQuadHistory(rid)
  const asOf = a?.computed_at || ""
  const daily = useDailyRows(rid, asOf, def.source === "daily")
  const fit = useFitnessTrend(rid, asOf, def.source === "fit")
  const [range, setRange] = useState<Range>(def.weekly ? "91" : "30")
  const all = useMemo((): { t: string; v: number | null }[] => {
    if (def.source === "hist") return (hist || []).map((h: any) => ({ t: String(h.date), v: valueOf(id, def, h) }))
    if (def.source === "fit") return (fit?.days || []).map((r: any) => ({ t: String(r.date), v: valueOf(id, def, r) }))
    if (def.source === "daily") return (daily || []).map((r: any) => ({ t: String(r.date), v: valueOf(id, def, r) }))
    return weeklyKm(boot?.activities || [], 27)
  }, [def, hist, daily, fit, boot?.activities, id])
  const lo = iso(new Date(Date.now() - (Number(range) - 1) * 86400000))
  const pts = all.filter((p) => p.t >= (def.weekly ? monday(lo) : lo))
  const vals = pts.map((p) => p.v).filter((v): v is number => v != null)
  // the latest value: the live number for the scores (as on Dnes), the last known day otherwise
  const rd = a?.readiness ?? a?.capacity?.readiness
  // (the same number the card shows, so a tap never changes it)
  const live: number | null = id === "load" ? a?.load ?? null : id === "mech" ? a?.mech ?? null
    : id === "readiness" ? (rd && rd.known !== false ? readinessPct(rd) : null)
    : id === "week" ? a?.loadDetail?.weekKm ?? null
    : def.source === "fit" ? fit?.today?.[def.field!] ?? null : a?.rcv?.[id]?.now ?? null
  const last = [...all].reverse().find((p) => p.v != null)
  const now = live ?? last?.v ?? null
  const rng = RANGE_KEY[id] ? rd?.inputs?.range?.[RANGE_KEY[id]!] : null
  const band = rng && rng.length === 2 ? { lo: rng[0], hi: rng[1], label: "vaše obvyklé rozmezí" }
    : id === "form" && fit?.bands ? { lo: fit.bands.tired ?? -10, hi: fit.bands.fresh ?? 5, label: "vyrovnaná zátěž" } : undefined
  const loading = (def.source === "daily" && daily === null) || (def.source === "hist" && hist === null) || (def.source === "fit" && fit === null)
  const stat = (label: string, v: number | null) => (
    <div className="min-w-0 rounded-[12px] bg-white/[.045] px-2.5 py-2">
      <span className="t-label block !text-fg-3">{label}</span>
      <b className="t-num mt-0.5 block whitespace-nowrap text-[17px] text-fg">{v == null ? "—" : `${nf(v, def.dec)}${def.unit}`}</b>
    </div>
  )
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="metric-sheet">
        <Label>{def.label}</Label>
        <div className="mt-1.5 flex items-end justify-between gap-3">
          {now == null ? <b className="pb-1 text-[15px] font-semibold text-fg-3">Zatím bez dat</b>
            : <b className="t-num text-[38px] leading-none text-fg">{nf(now, def.dec)}<small className="ml-1 text-[14px] font-semibold text-fg-3">{def.unit.trim()}</small></b>}
          {now != null && last && <span className="pb-1 text-[12px] text-fg-3">{def.weekly ? "tento týden" : live != null ? "dnes" : `naposledy ${new Date(last.t + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })}`}</span>}
        </div>
        <Segmented className="mt-4" size="sm" ariaLabel="Období" value={range} onChange={setRange}
          options={(def.weekly ? RANGES.slice(1) : RANGES) as any} />
        {loading ? <p className="mt-4 text-[12px] text-fg-3">Načítám…</p>
          : vals.length > 1 ? <AxisLineChart points={pts} yMin={def.yMin} yMax={def.yMax} threshold={def.threshold} thresholdLabel={def.threshold ? "práh" : undefined}
              unit={def.unit} dec={def.dec} color={C.info} height={150} band={band} />
          : <p className="mt-4 text-[12px] text-fg-3">Za toto období zatím málo dat.</p>}
        {vals.length > 0 && (
          <div className="mt-3 grid grid-cols-3 gap-1.5" data-testid="metric-stats">
            {stat("nejméně", Math.min(...vals))}
            {stat("průměr", vals.reduce((x, y) => x + y, 0) / vals.length)}
            {stat("nejvíc", Math.max(...vals))}
          </div>
        )}
        <p className="mt-3 text-[12.5px] leading-5 text-fg-2">{def.about}{id === "readiness" && " Graf ukazuje ranní hodnotu každého dne."}</p>
        <Link to={def.to} onClick={onClose} className="mt-3 inline-flex items-center gap-1 text-[13px] font-bold text-accent">{`Více na stránce ${def.tab}`}<ChevronRight className="size-4" aria-hidden /></Link>
      </div>
    </Sheet>
  )
}
