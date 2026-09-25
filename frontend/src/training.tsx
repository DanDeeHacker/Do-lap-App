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
import { fmtD, paceStr } from "@/lib"

const ORDER = ["volno", "regenerace", "lehký", "dlouhý", "kvalitní", "závod"]
const MODE: Record<string, [string, string]> = {
  build: ["Budovací týden", "#6ce6d3"], recovery: ["Odlehčovací týden", "#f6d69a"], deload: ["Odlehčovací · zvýšená zátěž", "#e77a59"],
  taper: ["Ladění před závodem", "#c7ff54"], learning: ["Nastavuji cyklus", "#9bb3aa"], hold: ["Udržení", "#f6d69a"],
}
const CYCLE_PCT = [90, 100, 110, 55]
const LIMIT: Record<string, string> = {
  week: "zbytek týdenního cíle", "7d": "7denní strop kapacity", run: "strop jednoho běhu", systemic: "zbytek celkové zátěže",
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

function WeekRow({ c, id }: { c: any; id: string }) {
  const d = id === "volume" ? 1 : 0
  if (c.budget == null) return (
    <div><div className="mb-1 flex justify-between text-[11px]"><span className="text-[#e7efe9]">{c.label}</span><span className="text-[10px] text-[#71837b]">kapacitu poznáváme</span></div><div className="h-2 rounded-full bg-white/10" /></div>
  )
  const scale = Math.max(c.done ?? 0, c.budget) * 1.05 || 1
  const over = (c.done ?? 0) > c.budget
  return (
    <div>
      <div className="mb-1 flex justify-between gap-2 text-[11px]">
        <span className="text-[#e7efe9]">{c.label}</span>
        <span className="whitespace-nowrap font-mono text-[10px] text-[#9bb3aa]">{num(c.done, d)} / {num(c.budget, d)} {c.unit} · {over || c.left === 0 ? "splněno" : `zbývá ${num(c.left, d)}`}</span>
      </div>
      <div className="relative h-2 rounded-full bg-white/10">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${((c.done ?? 0) / scale) * 100}%`, background: over ? "#f6d69a" : "#6ce6d3" }} />
        <i className="absolute -inset-y-1 w-0.5 bg-[#f1f8f1]" style={{ left: `calc(${(c.budget / scale) * 100}% - 1px)` }} />
      </div>
      <p className="mt-1 text-[10px] leading-4 text-[#71837b]">
        7 dní {num(c.done7, d)} / strop {num(c.ceiling7, d)} {c.unit}
        {id !== "systemic" && c.todayMax != null && <> · dnes max <b className="text-[#c9dcd4]">{num(c.todayMax, d)}</b>{c.limitedBy ? ` (${LIMIT[c.limitedBy] || c.limitedBy})` : ""}</>}
      </p>
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
  const locked = wk.mode === "taper"
  const allowed = (p: number) => !locked && (wk.mode !== "deload" || p === 4)
  const [modeLabel, modeCol] = MODE[wk.mode] || MODE.build
  const pct = Math.round((wk.progression ?? 1) * 100)
  const vol = wk.channels?.volume || {}
  const how =
    wk.mode === "build" ? `Cíl = ${pct} % referenčního týdne (${num(cyc.refKm)} km${cyc.refWeek ? `, týden od ${fmtD(cyc.refWeek)}` : ""}).`
      : wk.mode === "recovery" ? "4. týden cyklu: 55 % vrcholového týdne — tělo vstřebá předchozí tři týdny zátěže."
        : wk.mode === "deload" ? "Zátěž je zvýšená, proto odlehčovací týden hned: 55 % minulého týdne."
          : wk.mode === "taper" ? `Ladění před závodem: ${pct} % referenčního týdne.`
            : "Cyklus nastavíme, až budou aspoň 4 týdny dat — do té doby je cílem vaše týdenní kapacita."
  return (
    <section className="mt-4 rounded-[24px] border border-white/10 bg-[#0c201d] p-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Tento týden</Label><InfoDot text={MI.weekBudget} label="Týdenní cíl a cyklus" /></span>
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
              title={locked ? "Před závodem řídí týden ladění formy." : !allowed(n) ? "Zátěž je zvýšená — nejdřív odlehčovací týden." : on ? "Aktuální týden cyklu" : "Přepnout tento týden"}
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
        {how} Cíl nikdy nepřekročí strop vaší týdenní kapacity z tabu Zátěž ({num(vol.ceiling7)} km za 7 dní) — a dnešek hlídá obojí: zbytek týdenního cíle i 7denní strop.
      </p>
      <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_1.3fr]">
        <div>
          <p className="mb-2 font-mono text-[9px] uppercase tracking-[.14em] text-[#71837b]">Objem po týdnech (od pondělí)</p>
          <CycleStrip cyc={cyc} />
        </div>
        <div className="space-y-3">{CH_ORDER.map((id) => wk.channels?.[id] && <WeekRow key={id} c={wk.channels[id]} id={id} />)}</div>
      </div>
    </section>
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
          <span className="flex items-center gap-1 rounded-full bg-white/[.06] py-1 pl-3 pr-1.5 text-[11px] font-bold text-[#a9c2b9]">
            připravenost {Math.round((g.readiness ?? 1) * 100)} %<InfoDot text={MI.readinessTraining} label="Připravenost" />
          </span>
        </div>
      </div>

      {g.override && (
        <div className="mt-5 rounded-2xl border border-[#e77a59]/45 bg-[#3c2922] p-4 text-[#ffc1ab]">
          <p className="text-sm font-bold">⚠ {g.override.title}</p>
          <p className="mt-1 text-xs leading-5">{g.override.text}</p>
          {g.override.kind === "physio" && (
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
          <p className="text-sm text-[#a9c2b9]">{kind === "závod" ? "Den závodu — žádné limity. Po závodě nechte tělo pár dní regenerovat." : "Odpočinek. Pokud chcete pohyb, zvolte lehkou chůzi, mobilitu nebo jiný sport bez nárazů a bez bolesti."}</p>
        )}
        {t.notes?.length > 0 && (
          <ul className="mt-4 space-y-1 text-xs text-[#a9c2b9]">{t.notes.map((n: string, i: number) => <li key={i}>• {n}</li>)}</ul>
        )}
      </section>

      <WeekPanel g={g} />

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
