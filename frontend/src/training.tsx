// Engine v3 — the Trénink tab: today's session within this week's target (4-week
// loading cycle on the runner's own reference week, capped by the capacity the
// Zátěž tab shows): session type, distance, HR zone + pace, Z4+ minutes,
// ascent/descent, terrain, and why.
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, InfoDot, Label, useToast } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { readinessCol } from "@/capacity"
import { fmtD, paceStr } from "@/lib"

const ORDER = ["volno", "regenerace", "lehký", "dlouhý", "kvalitní", "závod"]
const MODE: Record<string, [string, string]> = {
  build: ["Budovací týden", "#6ce6d3"], recovery: ["Odlehčovací týden", "#f6d69a"], deload: ["Odlehčovací · zvýšená zátěž", "#e77a59"],
  taper: ["Ladění před závodem", "#c7ff54"], learning: ["Nastavuji cyklus", "#9bb3aa"], hold: ["Udržení", "#f6d69a"],
  return: ["Návrat po zranění", "#f6d69a"],
}
const CYCLE_PCT = [90, 100, 110, 55]
const LIMIT: Record<string, string> = {
  week: "cíl tohoto týdne v cyklu", "7d": "týdenní kapacita (posledních 7 dní)", run: "strop jednoho běhu",
  systemic: "celková zátěž", mechanics: "mechanika nad prahem",
}
const CH_ICON: Record<string, string> = { volume: "Objem", intensity: "Intenzita", descent: "Klesání", ascent: "Stoupání", systemic: "Celková zátěž" }

// Today's capacity: what today can hold so that the last 7 days stay within the
// weekly capacity the Zátěž tab shows, this week keeps to its place in the cycle,
// no single run exceeds its own capacity and load / mechanics stay under the
// threshold — each channel shows the numbers it was derived from.
function TodayCapacity({ g }: { g: any }) {
  const wk = g.week || {}
  const cyc = wk.cycle || {}
  const ax = g.axes || {}
  const th = ax.threshold ?? 25
  const loadHot = (ax.load ?? 0) >= th
  const mechHot = (ax.mech ?? 0) >= th
  const pct = Math.round((wk.progression ?? 1) * 100)
  const status = loadHot
    ? { col: "#e77a59", text: `Zátěž ${ax.load} je nad prahem ${th} — tento týden odlehčovací, bez tvrdých úseků a dlouhého běhu.` }
    : mechHot
      ? { col: "#f6d69a", text: `Mechanika ${ax.mech} je nad prahem ${th} — dnes o 20 % méně objemu, poloviční intenzita a klesání, raději rovina.` }
      : { col: "#6ce6d3", text: `Zátěž ${ax.load ?? 0} a mechanika ${ax.mech ?? 0} jsou pod prahem ${th} — dnešní limity drží obě osy pod prahem i po tréninku.` }
  return (
    <section className="mt-4 rounded-[24px] border border-white/10 bg-[#0c201d] p-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Dnešní kapacita</Label><InfoDot text={MI.todayCapacity} label="Dnešní kapacita" /></span>
        <span className="text-[11px] text-[#a9c2b9]">kolik si dnes můžete dovolit</span>
      </div>
      <p className="mt-2 flex items-start gap-2 text-xs leading-5 text-[#c9dcd4]"><i className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: status.col }} />{status.text}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {CH_ORDER.map((id) => {
          const c = wk.channels?.[id]
          if (!c) return null
          const d = id === "volume" ? 1 : 0
          const past6 = c.done7 != null ? c.done7 - (c.doneToday ?? 0) : null
          return (
            <div key={id} className="rounded-2xl border border-white/10 bg-white/[.02] p-3.5">
              <p className="text-[11px] text-[#a9c2b9]">{CH_ICON[id]}</p>
              <p className="mt-0.5 font-serif text-2xl leading-tight text-[#f1f8f1]">
                {id === "systemic" ? (c.todayMax != null ? `${num(c.todayMax, 0)}` : "—") : c.todayMax != null ? `max ${num(c.todayMax, d)}` : "—"}
                <span className="text-sm text-[#71837b]"> {c.unit}</span>
              </p>
              {c.limitedBy && <p className="text-[10px] text-[#f6d69a]">omezuje: {LIMIT[c.limitedBy] || c.limitedBy}</p>}
              <dl className="mt-2 space-y-0.5 text-[10px] leading-4 text-[#71837b]">
                {c.capacity != null && <div className="flex justify-between gap-2"><dt>Týdenní kapacita (Zátěž)</dt><dd className="font-mono text-[#c9dcd4]">{num(c.capacity, d)} · strop {num(c.ceiling7, d)}{c.ceiling7 != null && c.ceiling7 < c.capacity ? " ↓" : ""}</dd></div>}
                {past6 != null && <div className="flex justify-between gap-2"><dt>Posledních 6 dní{c.doneToday ? " + dnes" : ""}</dt><dd className="font-mono text-[#c9dcd4]">{num(c.done7, d)} → zbývá {num(c.left7, d)}</dd></div>}
                {c.budget != null && <div className="flex justify-between gap-2"><dt>Tento týden v cyklu{cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? ` (${cyc.pos}. týden, ${pct} %)` : ""}</dt><dd className="font-mono text-[#c9dcd4]">{num(c.done, d)} / {num(c.budget, d)} → zbývá {num(c.left, d)}</dd></div>}
                {c.ceilingRun != null && <div className="flex justify-between gap-2"><dt>Jeden běh</dt><dd className="font-mono text-[#c9dcd4]">max {num(c.ceilingRun, d)}</dd></div>}
              </dl>
            </div>
          )
        })}
      </div>
      {wk.channels?.volume?.ceiling7 != null && wk.channels.volume.ceiling7 < wk.channels.volume.capacity && (
        <p className="mt-2 text-[10px] text-[#71837b]">↓ strop je nižší než kapacita: připravenost byla tento týden snížená (HRV / klidový tep / spánek mimo vaši normu), a tak se týdenní strop zmenšuje — nejvýš o 30 %.</p>
      )}
      {cyc.next && (
        <p className="mt-3 text-xs leading-5 text-[#a9c2b9]">
          <b className="text-[#f1f8f1]">Příští týden:</b> {cyc.next.pos}. týden cyklu ({cyc.next.pct} %) — cíl objemu ≈ {num(cyc.next.km)} km{cyc.next.pos === 1 ? ", nový cyklus na vyšší úrovni" : ""}. Kapacita se po každém týdnu přepočítá podle toho, co jste skutečně odběhli.
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
    <div className="rounded-2xl border border-white/10 bg-white/[.03] p-3.5">
      <p className="font-mono text-[9px] uppercase tracking-[.14em] text-[#71837b]">{label}</p>
      <p className={`mt-1 leading-tight ${text ? "text-sm font-bold md:text-base" : "whitespace-nowrap font-serif text-xl md:text-2xl"}`} style={{ color: warn ? "#f6d69a" : "#f1f8f1" }}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] leading-4 text-[#a9c2b9]">{sub}</p>}
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
          <div className="relative mx-auto flex h-16 w-full max-w-[46px] items-end overflow-hidden rounded-md bg-white/[.04]">
            {w.current && w.target != null && (
              <i className="absolute inset-x-0 bottom-0 rounded-md border border-dashed border-[#c7ff54]/80" style={{ height: `${(w.target / max) * 100}%` }} />
            )}
            <i className="relative block w-full rounded-md" style={{ height: `${((w.km || 0) / max) * 100}%`, background: w.current ? "#c7ff54" : "#6ce6d3", opacity: w.current ? 1 : 0.5 }} />
          </div>
          <p className="mt-1 whitespace-nowrap font-mono text-[10px] text-[#f1f8f1]">{num(w.km)} km</p>
          <p className="truncate text-[9px] text-[#71837b]">{w.current ? (w.target != null ? `cíl ${num(w.target)}` : "tento týden") : `od ${fmtD(w.start)}`}</p>
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
    <section className="mt-4 rounded-[24px] border border-white/10 bg-[#0c201d] p-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Cyklus · tento týden</Label><InfoDot text={MI.weekBudget} label="Týdenní cíl a cyklus" /></span>
        <span className="rounded-full px-2.5 py-1 text-[10px] font-bold" style={{ background: `${modeCol}1f`, color: modeCol }}>
          {cyc.pos && (wk.mode === "build" || wk.mode === "recovery") ? `${cyc.pos}. týden ze 4 · ` : ""}{modeLabel}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-1.5" role="radiogroup" aria-label="Týden čtyřtýdenního cyklu">
        {CYCLE_PCT.map((p, i) => {
          const n = i + 1
          const on = cyc.pos === n
          return (
            <button key={n} role="radio" aria-checked={on} disabled={busy || on || !allowed(n)}
              onClick={() => setAsk(n)}
              title={locked ? (wk.novice ? "Prvních 6 týdnů běží bez cyklu." : wk.mode === "return" ? "Návrat po zranění řídí týden sám." : "Před závodem řídí týden ladění formy.") : !allowed(n) ? "Zátěž je zvýšená — nejdřív odlehčovací týden." : on ? "Aktuální týden cyklu" : "Přepnout tento týden"}
              className={`rounded-lg px-1.5 py-1.5 text-center text-[10px] font-bold leading-tight transition ${on ? "bg-[#c7ff54] text-[#071313]" : allowed(n) ? "bg-white/[.06] text-[#c9dcd4] hover:bg-white/[.12]" : "bg-white/[.03] text-[#5f7268]"}`}>
              {n}. týden<span className="block font-normal opacity-80">{p} %</span>
            </button>
          )
        })}
      </div>
      {ask != null && (
        <div className="mt-2 rounded-xl border border-[#c7ff54]/30 bg-[#c7ff54]/[.06] p-3 text-xs leading-5 text-[#e7efe9]">
          Přepnout tento týden na <b>{ask}. týden cyklu ({CYCLE_PCT[ask - 1]} %)</b>{ask === 4 ? " — odlehčovací" : ""}? Týdenní cíle, dnešní limity i doporučení se hned přepočítají.
          Příští týden se cyklus nastaví sám podle toho, jak tenhle týden skutečně proběhne.
          <div className="mt-2 flex gap-2">
            <button onClick={() => void pick(ask)} disabled={busy} className="rounded-full bg-[#c7ff54] px-3 py-1.5 text-[11px] font-bold text-[#071313] disabled:opacity-50">{busy ? "Přepočítávám…" : "Přepnout"}</button>
            <button onClick={() => setAsk(null)} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#a9c2b9]">Zrušit</button>
          </div>
        </div>
      )}
      {cyc.manual && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[#f6d69a]">
          Ručně zvoleno pro tento týden{cyc.autoPos ? ` (automaticky by byl ${cyc.autoPos}. týden)` : ""}.
          <button onClick={() => void pick(null)} disabled={busy} className="rounded-full border border-[#f6d69a]/40 px-2.5 py-0.5 font-bold">Vrátit automaticky</button>
        </p>
      )}
      <p className="mt-3 text-xs leading-5 text-[#a9c2b9]">
        {how} Cíl nikdy nepřekročí strop vaší týdenní kapacity z tabu Zátěž ({num(vol.ceiling7)} km za 7 dní).
      </p>
      <div className="mt-4">
        <p className="mb-2 font-mono text-[9px] uppercase tracking-[.14em] text-[#71837b]">Objem po týdnech (od pondělí)</p>
        <div className="max-w-md"><CycleStrip cyc={cyc} /></div>
      </div>
    </section>
  )
}

// Plan B4 — the race calendar. A = the goal race (taper before it), B = run hard
// without a taper, C = run as training. The profile's goal race shows here too.
const PRIO: Record<string, [string, string]> = {
  A: ["A · cílový", "#c7ff54"], B: ["B · naplno bez ladění", "#6ce6d3"], C: ["C · jako trénink", "#9bb3aa"],
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
  const inp = "w-full rounded-xl border border-white/10 bg-white/[.04] px-3 py-2 text-sm text-[#f1f8f1]"
  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between gap-2">
        <Label>Závody</Label>
        {!adding && <button onClick={() => setAdding(true)} className="rounded-full border border-white/15 px-3 py-1 text-[11px] font-bold text-[#c7ff54]">+ Přidat závod</button>}
      </div>
      {warns.map((w: any, i: number) => (
        <p key={i} className="mt-3 rounded-xl border border-[#f6d69a]/35 bg-[#33301f] px-3 py-2 text-xs leading-5 text-[#f6e2b3]">⚠ {w.text}</p>
      ))}
      {races === null ? <p className="mt-2 text-sm text-[#71837b]">Načítám…</p> : list.length === 0 && !adding ? (
        <p className="mt-2 text-sm text-[#a9c2b9]">Zatím žádný závod. Přidejte ho — před cílovým závodem (A) plán zařadí ladění formy a hlídá, aby závod nepřišel moc brzy po jiném maximálním úsilí.</p>
      ) : (
        <ul className="mt-3 divide-y divide-white/5">
          {list.map((x) => {
            const [pl, pc] = PRIO[x.priority] || PRIO.B
            return (
              <li key={x.id} className={`flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 ${x.daysTo < 0 ? "opacity-50" : ""}`}>
                <span className="w-16 shrink-0 font-mono text-xs text-[#9bb3aa]">{fmtD(x.date)}</span>
                <span className="min-w-0 flex-1 text-sm text-[#f1f8f1]">
                  {x.name || (x.priority === "A" ? "Cílový závod" : "Závod")}{x.km ? <span className="text-[#71837b]"> · {num(x.km)} km</span> : null}
                  {x.source === "profile" && <span className="text-[10px] text-[#71837b]"> · z profilu</span>}
                </span>
                <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
                <span className="w-16 text-right text-[11px] text-[#9bb3aa]">{x.daysTo === 0 ? "dnes" : x.daysTo > 0 ? `za ${x.daysTo} d` : "proběhl"}</span>
                <button disabled={busy} onClick={() => del(x.id)} aria-label="Smazat závod" className="text-xs text-[#71837b] hover:text-[#e77a59]">✕</button>
              </li>
            )
          })}
        </ul>
      )}
      {adding && (
        <div className="mt-3 grid gap-2 rounded-2xl border border-white/10 p-3 sm:grid-cols-2">
          <label className="text-[11px] text-[#9bb3aa]">Datum<input type="date" className={inp} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
          <label className="text-[11px] text-[#9bb3aa]">Název<input className={inp} value={f.name} placeholder="např. Pražský půlmaraton" maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="text-[11px] text-[#9bb3aa]">Délka (km)
            <input className={inp} inputMode="decimal" value={f.km} onChange={(e) => setF({ ...f, km: e.target.value })} />
            <span className="mt-1 flex flex-wrap gap-1">{DIST.map(([v, l]) => <button key={v} type="button" onClick={() => setF({ ...f, km: v })} className="rounded-full bg-white/[.06] px-2 py-0.5 text-[10px] text-[#a9c2b9]">{l}</button>)}</span>
          </label>
          <div className="text-[11px] text-[#9bb3aa]">Priorita
            <div className="mt-1 flex flex-wrap gap-1">{Object.entries(PRIO).map(([k, [l, c]]) => (
              <button key={k} type="button" onClick={() => setF({ ...f, priority: k })} className="rounded-full border px-2.5 py-1 text-[10px] font-bold"
                style={f.priority === k ? { borderColor: c, color: c, background: `${c}1f` } : { borderColor: "rgb(255 255 255 / .12)", color: "#a9c2b9" }}>{l}</button>
            ))}</div>
            <p className="mt-1 text-[10px] leading-4 text-[#71837b]">A = hlavní cíl, 2 týdny před ním ladění formy. B = naplno, bez ladění. C = jako trénink.</p>
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <button disabled={busy || !f.date} onClick={save} className="rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313] disabled:opacity-50">Uložit</button>
            <button onClick={() => setAdding(false)} className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-[#a9c2b9]">Zrušit</button>
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
  if (!a) return <p className="text-sm text-[#71837b]">Načítám…</p>
  if (a.engineMode !== "v3" || !g) {
    return (
      <Card>
        <Label>Trénink</Label>
        <p className="mt-2 text-sm text-[#a9c2b9]">Denní doporučení počítá Kapacitní engine. Zapnete ho v <Link to="/data" className="font-bold text-[#c7ff54]">Data a propojení → Engine hodnocení → Kapacitní</Link>.</p>
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
          <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">{t.label}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {g.provisional && <span className="rounded-full bg-[#f6d69a]/15 px-3 py-1.5 text-[11px] font-bold text-[#f6d69a]">předběžné · čeká na ranní data</span>}
          {(() => {
            const rp = g.readinessScore ?? Math.round((g.readiness ?? 1) * 100)
            const col = readinessCol(rp)
            return (
              <span className="flex items-center gap-1 rounded-full py-1 pl-3 pr-1.5 text-[11px] font-bold" style={{ background: `${col}1f`, color: col }}>
                připravenost {rp} %<InfoDot text={MI.readinessTraining} label="Připravenost" />
              </span>
            )
          })()}
        </div>
      </div>

      {g.override && (
        <div className="mt-5 rounded-2xl border border-[#e77a59]/45 bg-[#3c2922] p-4 text-[#ffc1ab]">
          <p className="text-sm font-bold">⚠ {g.override.title}</p>
          <p className="mt-1 text-xs leading-5">{g.override.text}</p>
          {(g.override.kind === "physio" || g.override.kind === "function") && (
            <Link to="/app/messages" className="mt-3 inline-block rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313]">Objednat fyzioterapeuta</Link>
          )}
        </div>
      )}

      {g.done && (
        <div className="mt-4 rounded-2xl border border-[#6ce6d3]/30 bg-[#6ce6d3]/[.06] p-3.5 text-xs text-[#cfe9e2]">
          Dnes už máte hotovo: <b>{num(g.done.volume)} km</b>{g.done.intensity ? ` · ${num(g.done.intensity, 0)} min v Z4+` : ""}{g.done.descent ? ` · klesání ${num(g.done.descent, 0)} m` : ""}. Limity níže ukazují, co ještě dnes zbývá.
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        {ORDER.filter((k) => g.types[k]).map((k) => {
          const on = k === kind
          const rec = k === g.type
          const ok = g.types[k].allowed
          return (
            <button key={k} onClick={() => setSel(k)}
              className={`rounded-full border px-3.5 py-2 text-xs font-bold transition ${on ? "border-[#c7ff54] bg-[#c7ff54]/12 text-[#f1f8f1]" : "border-white/12 text-[#a9c2b9] hover:border-white/25"} ${ok ? "" : "opacity-55"}`}>
              {g.types[k].label}{rec ? " · doporučeno" : ""}{!ok ? " ⊘" : ""}
            </button>
          )
        })}
      </div>

      <section className="mt-4 rounded-[24px] border border-white/10 bg-[#0c201d] p-5 md:p-6">
        {!t.allowed && (
          <p className="mb-4 rounded-xl bg-[#3c2922] px-3 py-2 text-xs font-bold text-[#ffc1ab]">Dnes nedoporučujeme: {t.why}</p>
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
          <p className="text-sm text-[#a9c2b9]">{kind === "závod" ? ((a.races?.warnings || []).some((w: any) => w.kind === "race_day") ? "Den závodu — ale tělo dnes nehlásí plnou připravenost (viz níže). Běžte s rezervou." : "Den závodu — žádné limity. Po závodě nechte tělo pár dní regenerovat.") : "Odpočinek. Pokud chcete pohyb, zvolte lehkou chůzi, mobilitu nebo jiný sport bez nárazů a bez bolesti."}</p>
        )}
        {t.notes?.length > 0 && (
          <ul className="mt-4 space-y-1 text-xs text-[#a9c2b9]">{t.notes.map((n: string, i: number) => <li key={i}>• {n}</li>)}</ul>
        )}
      </section>

      <TodayCapacity g={g} />
      <WeekPanel g={g} />
      <RacesCard outlook={a.races} />

      <Card className="mt-4">
        <Label>Proč</Label>
        {g.reasons?.length ? (
          <ul className="mt-2 space-y-2 text-sm text-[#e7efe9]">{g.reasons.map((r: string, i: number) => <li key={i} className="flex gap-2"><span className="text-[#6ce6d3]">›</span><span>{r}</span></li>)}</ul>
        ) : <p className="mt-2 text-sm text-[#a9c2b9]">Vše v normě — běžný tréninkový den.</p>}
        <p className="mt-4 text-[11px] leading-4 text-[#71837b]">
          {pat.runDayNames?.length ? `Obvykle běháte: ${pat.runDayNames.join(", ")}` : "Pravidelné dny zatím nepoznáváme"}
          {pat.longDayName ? ` · dlouhý běh ${pat.longDayName}` : ""}
          {pat.hardDayNames?.length ? ` · tvrdé tréninky: ${pat.hardDayNames.join(", ")}` : ""}
          {pat.easyKm ? ` · typický lehký běh ${num(pat.easyKm)} km` : ""}
        </p>
      </Card>
      <p className="mt-4 text-[10px] leading-4 text-[#71837b]">Došlap není zdravotnický prostředek. Doporučení jsou ochranné mantinely z vašich dat, ne léčba ani diagnóza. Při bolesti, která se vrací nebo zhoršuje, se poraďte s fyzioterapeutem.</p>
    </>
  )
}
