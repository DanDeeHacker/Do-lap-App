// v0.12.12 — Zátěž → Kondice a únava: the 42- and 7-day averages of the total load and their
// balance (Čerstvost), the picture Strava calls Fitness & Freshness and TrainingPeaks the PMC.
// A trend to read: today's training follows Připravenost and the capacity channels.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { AxisLineChart, InfoDot, Label, Segmented, useToast } from "@/ui"
import { fmtD, paceStr } from "@/lib"
import { num } from "@/outlook"
import { C } from "@/tokens"
import { ChevronDown, HeartPulse, TrendingUp } from "lucide-react"

// two slots of the app's validated categorical palette (outlook.SRC): lightness band, chroma,
// CVD and normal-vision separation and contrast all pass on the dark surface
export const FIT_COL = "#8f7ff2"
export const FAT_COL = "#1592a6"
const WORD: Record<string, [string, string]> = {
  fresh: ["odpočatý", C.ok], even: ["vyrovnaný", C.fgSoft], tired: ["unavený", C.watch],
}
export const formWord = (w?: string | null) => (w ? WORD[w] : null)
export const signed = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), d)}`)
const RANGES = [["90", "3 měsíce"], ["182", "6 měsíců"], ["365", "1 rok"]] as const
type Range = (typeof RANGES)[number][0]
const niceStep = (mx: number) => { const raw = mx / 4, p = 10 ** Math.floor(Math.log10(raw || 1)), f = raw / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p }

export function FitnessTrend({ rid }: { rid: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<any | null | false>(null)   // null = not loaded, false = failed
  const [range, setRange] = useState<Range>("90")
  useEffect(() => {
    if (!open || data !== null) return
    let alive = true
    api.fitnessTrend(rid).then((d) => alive && setData(d || false)).catch(() => alive && setData(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rid])
  const t = data && data.available ? data.today : null
  return (
    <section className="mt-4" data-testid="fitness-trend">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="card flex w-full items-center gap-4 px-4 py-4 text-left text-fg transition hover:border-load/45 md:px-5">
        <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-load/15 text-load"><TrendingUp className="size-4" aria-hidden /></span>
        <span className="min-w-0 flex-1"><span className="t-label">Kondice a únava</span><span className="mt-1 block font-serif text-[19px] leading-snug">Dlouhodobý trend celkové zátěže · rozklikni graf</span></span>
        <ChevronDown className={`size-5 shrink-0 text-load transition ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div className="card mt-3 p-4 md:p-5">
          {data === null && <p className="text-[12px] text-fg-3">Počítám trend zátěže…</p>}
          {data === false && <p className="text-[12px] text-fg-3">Trend se nepodařilo načíst. Zkuste to prosím později.</p>}
          {data && !data.available && <p className="text-[12px] text-fg-3">Trend uvidíte po prvních aktivitách z hodinek.</p>}
          {t && <TrendBody data={data} t={t} range={range} setRange={setRange} />}
        </div>
      )}
    </section>
  )
}

function TrendBody({ data, t, range, setRange }: { data: any; t: any; range: Range; setRange: (r: Range) => void }) {
  const [table, setTable] = useState(false)
  const days: any[] = (data.days || []).slice(-Number(range))
  const w = formWord(t.word)
  return (
    <>
      <div className="grid grid-cols-3 gap-2" data-testid="fitness-stats">
        <Stat label="Kondice" col={FIT_COL} value={num(t.fit, 0)} sub={t.fitChange != null ? `${signed(t.fitChange)} % za 4 týdny` : "průměr ~6 týdnů"} />
        <Stat label="Únava" col={FAT_COL} value={num(t.fat, 0)} sub="průměr ~7 dní" />
        <Stat label="Čerstvost" value={t.form != null ? `${signed(t.form)} %` : "—"} sub={w ? w[0] : "málo zátěže na srovnání"} />
      </div>
      {data.settling && <p className="mt-2 text-[12px] text-fg-3">Historie je zatím kratší než 6 týdnů, takže se Kondice teprve ustaluje.</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <Segmented options={RANGES} value={range} onChange={setRange} ariaLabel="Období" size="sm" />
        <button type="button" onClick={() => setTable((v) => !v)} className="text-[11px] font-semibold text-accent" data-testid="fitness-table-toggle">{table ? "Graf" : "Tabulka"}</button>
      </div>
      {table ? <WeekTable days={days} /> : (
        <>
          <TwoLines days={days} />
          <div className="mt-4">
            <span className="flex items-center gap-1.5"><Label>Čerstvost</Label>
              <InfoDot label="Čerstvost" text="Kondice minus Únava jako podíl Kondice. Kladná = poslední dny jste zatěžovali méně, než jste zvyklí, a jste odpočatější. Záporná = poslední týden byl nad vaším průměrem." /></span>
            <AxisLineChart points={days.map((d) => ({ t: d.d, v: d.form }))} unit=" %" color={C.fgSoft} height={96} {...formAxis(days)}
              band={{ lo: data.bands?.tired ?? -10, hi: data.bands?.fresh ?? 5, label: "vyrovnaná zátěž" }} />
          </div>
        </>
      )}
      <div className="mt-3 grid gap-1 text-[11px] leading-4 text-fg-3">
        <p>Trend jako Fitness &amp; Freshness ve Stravě nebo PMC v TrainingPeaks, z celkové zátěže všech aktivit. Jak dnes trénovat, ukazuje Připravenost a kapacita kanálů výše.</p>
        <details><summary className="cursor-pointer font-semibold text-fg-2">Jak se to počítá</summary>
          <span className="mt-1 block">Zátěž dne je součet zátěže všech aktivit (u běhu z tepu, u posilování z náročnosti, stejná jako v Celkové zátěži). Kondice je její vážený průměr s časovou konstantou 42 dní, Únava se 7 dny: včerejšek váží nejvíc a starší dny postupně méně. Čerstvost je (Kondice − Únava) ÷ Kondice. Hranice „vyrovnané“ zátěže (−10 až +5 %) jsou zvyklost aplikace, ne výsledek výzkumu. Model kondice a únavy dobře popisuje skupiny, u jednotlivce je hrubší, proto o dnešním tréninku nerozhoduje.</span>
        </details>
      </div>
    </>
  )
}

// the freshness chart on round tens, always with room for the balanced band
function formAxis(days: any[]) {
  const vs = days.map((d) => d.form).filter((v) => v != null) as number[]
  if (!vs.length) return {}
  return { yMin: Math.floor(Math.min(-20, ...vs) / 20) * 20, yMax: Math.ceil(Math.max(20, ...vs) / 20) * 20 }
}

function Stat({ label, value, sub, col }: { label: string; value: string; sub: string; col?: string }) {
  return (
    <div className="nest min-w-0 px-2.5 py-2.5">
      <span className="flex items-center gap-1.5">{col && <i className="inline-block h-[3px] w-3 shrink-0 rounded-full" style={{ background: col }} />}<span className="t-label !text-fg-3">{label}</span></span>
      <b className="t-num mt-1 block text-[24px] leading-none text-fg">{value}</b>
      <span className="mt-1 block text-[11px] leading-4 text-fg-2">{sub}</span>
    </div>
  )
}

function TwoLines({ days }: { days: any[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (days.length < 2) return <p className="mt-3 text-[12px] text-fg-3">Zatím málo dat pro trend v čase.</p>
  const W = 360, H = 200, pl = 32, pr = 12, pt = 14, pb = 24
  const n = days.length
  const mx0 = Math.max(1, ...days.map((d) => Math.max(d.fit || 0, d.fat || 0)))
  const stepY = niceStep(mx0 * 1.1)
  const ymax = Math.ceil((mx0 * 1.08) / stepY) * stepY
  const x = (i: number) => pl + (i / (n - 1)) * (W - pl - pr)
  const y = (v: number) => pt + (1 - v / ymax) * (H - pt - pb)
  const path = (k: "fit" | "fat") => days.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(d[k] || 0).toFixed(1)}`).join(" ")
  const ticks = Array.from({ length: Math.round(ymax / stepY) + 1 }, (_, i) => i * stepY)
  // x ticks on the first day of each month (every other month over a year)
  const months = days.map((d, i) => ({ i, d: d.d })).filter((p) => p.d.slice(8) === "01")
  const xt = months.length > 7 ? months.filter((_, k) => k % 2 === 0) : months
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
    const i = Math.round((((e.clientX - r.left) / r.width) * W - pl) / (W - pl - pr) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const last = days[n - 1]
  const hv = hover != null ? days[hover] : null
  const endLbl = (v: number, col: string, text: string, dy: number) => (
    <text x={x(n - 1) - 4} y={y(v) + dy} textAnchor="end" fontSize="10.5" fontWeight="700" fill={col} stroke={C.panel} strokeWidth="3" paintOrder="stroke">{text}</text>
  )
  const fitAbove = (last.fit || 0) >= (last.fat || 0)
  return (
    <figure className="relative mt-3" data-testid="fitness-chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full touch-pan-y" role="img" onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)}
        aria-label={`Kondice ${num(last.fit, 0)}, Únava ${num(last.fat, 0)} k ${fmtD(last.d)}`}>
        {ticks.map((tk) => <g key={tk}><line x1={pl} x2={W - pr} y1={y(tk)} y2={y(tk)} stroke="rgba(255,255,255,.08)" />
          <text x={pl - 6} y={y(tk) + 3.5} textAnchor="end" fontSize="10" fill={C.fg3}>{tk}</text></g>)}
        {xt.map((p) => <g key={p.i}><line x1={x(p.i)} x2={x(p.i)} y1={H - pb} y2={H - pb + 4} stroke={C.fg4} />
          <text x={x(p.i)} y={H - pb + 15} textAnchor="middle" fontSize="10" fill={C.fg3}>{fmtD(p.d)}</text></g>)}
        <path d={path("fat")} fill="none" stroke={FAT_COL} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <path d={path("fit")} fill="none" stroke={FIT_COL} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {endLbl(last.fit || 0, FIT_COL, `Kondice ${num(last.fit, 0)}`, fitAbove ? -7 : 14)}
        {endLbl(last.fat || 0, FAT_COL, `Únava ${num(last.fat, 0)}`, fitAbove ? 14 : -7)}
        {hover != null && <>
          <line x1={x(hover)} x2={x(hover)} y1={pt} y2={H - pb} stroke={C.fg2} strokeWidth="1" />
          <circle cx={x(hover)} cy={y(hv.fit || 0)} r="3.5" fill={FIT_COL} stroke={C.panel} strokeWidth="2" />
          <circle cx={x(hover)} cy={y(hv.fat || 0)} r="3.5" fill={FAT_COL} stroke={C.panel} strokeWidth="2" />
        </>}
      </svg>
      {hv && (
        <div className="pointer-events-none absolute top-1 z-10 rounded-[10px] border border-white/14 bg-raised px-2.5 py-1.5 text-[11px] shadow-[0_10px_28px_rgba(0,0,0,.5)]"
          style={{ left: `${(x(hover!) / W) * 100}%`, transform: `translateX(${x(hover!) > W * 0.6 ? "-105%" : "5%"})` }} data-testid="fitness-tip">
          <span className="block text-fg-3">{fmtD(hv.d)} · zátěž dne {num(hv.load, 0)}</span>
          <span className="flex items-center gap-1.5"><i className="inline-block h-[2px] w-3" style={{ background: FIT_COL }} /><b className="tabular-nums text-fg">{num(hv.fit, 0)}</b><span className="text-fg-3">Kondice</span></span>
          <span className="flex items-center gap-1.5"><i className="inline-block h-[2px] w-3" style={{ background: FAT_COL }} /><b className="tabular-nums text-fg">{num(hv.fat, 0)}</b><span className="text-fg-3">Únava</span></span>
          {hv.form != null && <span className="block text-fg-2">Čerstvost <b className="tabular-nums text-fg">{signed(hv.form)} %</b></span>}
        </div>
      )}
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-2">
        <span><i className="mr-1.5 inline-block h-[2px] w-4 align-middle" style={{ background: FIT_COL }} />Kondice (42 dní)</span>
        <span><i className="mr-1.5 inline-block h-[2px] w-4 align-middle" style={{ background: FAT_COL }} />Únava (7 dní)</span>
        <span className="text-fg-3">body zátěže za den</span>
      </figcaption>
    </figure>
  )
}

function WeekTable({ days }: { days: any[] }) {
  // the last day of each week (Sunday) and today
  const rows = days.filter((d, i) => new Date(d.d + "T12:00:00").getDay() === 0 || i === days.length - 1).reverse()
  return (
    <div className="mt-3 max-h-[280px] overflow-y-auto rounded-xl border border-white/[.07]" data-testid="fitness-table">
      <table className="w-full text-[11px] tabular-nums">
        <thead className="sticky top-0 bg-raised text-fg-3">
          <tr><th className="px-2 py-1.5 text-left font-semibold">Den</th><th className="px-2 text-right font-semibold">Kondice</th>
            <th className="px-2 text-right font-semibold">Únava</th><th className="px-2 text-right font-semibold">Čerstvost</th></tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.d} className="border-t border-white/[.05] text-fg-soft">
              <td className="px-2 py-1">{fmtD(d.d)}</td><td className="px-2 text-right">{num(d.fit, 0)}</td>
              <td className="px-2 text-right">{num(d.fat, 0)}</td><td className="px-2 text-right">{d.form != null ? `${signed(d.form)} %` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// v0.12.12 — the values every load is computed with and where each comes from ("accurate metrics
// need accurate zones"): a recording above the maximum in use, an estimated maximum, a threshold
// outside rest–max, critical speed that moved
const HR_SRC: Record<string, (h: any) => string> = {
  profile: () => "zadaný v profilu",
  runs: (h) => `z nejtvrdšího běhu (průměr ${h.hardestAvg} + 10)${h.measured ? `, zadaných ${h.measured} je méně` : ""}`,
  age: (h) => `odhad z věku (208 − 0,7 × věk = ${h.ageEstimate})`,
  default: () => "obecný odhad, bez roku narození a tvrdých běhů",
}

export function ZoneCheck({ rid, zc }: { rid: string; zc: any }) {
  const { refresh, touring } = useApp()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!zc) return null
  const flags: any[] = zc.flags || []
  const above = flags.find((f) => f.key === "hrAbove")
  const warn = flags.find((f) => f.tone === "watch")
  const h = zc.hrMax || {}
  const save = async (hr: number) => {
    setBusy(true)
    try { await api.updateProfile(rid, { hr_max: hr }); toast({ title: "Maximální tep uložen", msg: `${hr} tep/min` }); refresh() } finally { setBusy(false) }
  }
  const sub = above ? "Naměřili jsme vyšší tep, než s jakým aplikace počítá" : warn ? "Tep na prahu se nepoužívá" : "Z čeho se počítá zátěž · rozklikni detail"
  return (
    <section className="mt-4" data-testid="zone-check">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="card flex w-full items-center gap-4 px-4 py-4 text-left text-fg transition hover:border-load/45 md:px-5">
        <span className={`grid size-[34px] shrink-0 place-items-center rounded-[10px] ${warn ? "bg-watch/15 text-watch" : "bg-load/15 text-load"}`}><HeartPulse className="size-4" aria-hidden /></span>
        <span className="min-w-0 flex-1"><span className="t-label">Tepové hodnoty a prahy</span>
          <span className={`mt-1 block font-serif text-[19px] leading-snug ${warn ? "text-watch" : ""}`}>{sub}</span></span>
        <ChevronDown className="size-5 shrink-0 text-load transition" style={{ transform: open ? "rotate(180deg)" : undefined }} aria-hidden />
      </button>
      {open && (
        <div className="card mt-3 space-y-3 p-4 md:p-5">
          {flags.map((f) => <Flag key={f.key} f={f} zc={zc} busy={busy} canSave={!touring} onSave={save} />)}
          <div className="divide-y divide-white/[.07]">
            <Row label="Maximální tep" value={`${h.value} tep/min`} sub={(HR_SRC[h.source] || HR_SRC.default)(h)} />
            <Row label="Klidový tep" value={`${zc.hrRest?.value} tep/min`} sub={zc.hrRest?.nights ? `medián z ${zc.hrRest.nights} nocí za 6 měsíců` : "bez nočních dat obecných 50"} />
            <Row label="Tep na prahu" value={zc.lthr?.value ? `${zc.lthr.value} tep/min` : "nezadán"}
              sub={zc.lthr?.used ? "zóny a tvrdé minuty se počítají od prahu" : zc.lthr?.value ? "mimo rozsah klid–maximum, nepoužívá se" : "zóny se počítají z tepové rezervy (klid až maximum)"} />
            <Row label="Kritická rychlost" value={zc.cs?.paceSKm ? `${paceStr(zc.cs.paceSKm)} /km` : "zatím neznámá"}
              sub={zc.cs?.paceSKm ? (zc.cs.prevPaceSKm ? `před 6 týdny ${paceStr(zc.cs.prevPaceSKm)} /km · počítá se z nejrychlejších úseků za 90 dní` : "z nejrychlejších úseků za 90 dní") : "potřebuje rychlejší úseky různé délky z detailních dat"} />
          </div>
          <p className="text-[11px] leading-4 text-fg-3">Z maximálního a klidového tepu se počítá zátěž každého běhu i minuty v Z4+, z kritické rychlosti Intenzita a Rychlost. Když maximum neodpovídá, zátěž tvrdých tréninků je nadhodnocená (nízké maximum) nebo schovaná (vysoké).</p>
        </div>
      )}
    </section>
  )
}

function Row({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
      <span className="min-w-0"><b className="block text-[13px] text-fg">{label}</b><span className="block text-[11.5px] leading-4 text-fg-3">{sub}</span></span>
      <b className="t-num shrink-0 text-[14px] text-fg">{value}</b>
    </div>
  )
}

function Flag({ f, zc, busy, canSave, onSave }: { f: any; zc: any; busy: boolean; canSave: boolean; onSave: (hr: number) => void }) {
  const p = zc.peak
  const tone = f.tone === "watch" ? "border-watch/30 bg-watch/10" : "border-info/25 bg-info/[.07]"
  const text = f.key === "hrAbove"
    ? `${fmtD(p?.date)} jste aspoň 30 s měli tep ${f.hr} (${p?.title || "aktivita"}), víc než maximum ${f.used}, se kterým aplikace počítá. Tvrdé úseky se pak počítají jako těžší, než byly. Pokud to nebyla chyba snímače, uložte si ${f.hr} jako maximální tep.`
    : f.key === "hrEstimated" ? "Maximální tep je odhad. Změřený (z testu nebo ze závodu do kopce) zadejte v profilu, zóny i zátěž budou přesnější."
    : f.key === "lthrOut" ? `Tep na prahu ${f.lthr} je mimo rozsah klidového a maximálního tepu, proto ho aplikace nepoužívá. Opravte ho v profilu.`
    : `Kritická rychlost se za 6 týdnů posunula z ${paceStr(zc.cs?.prevPaceSKm)} na ${paceStr(zc.cs?.paceSKm)} /km (${f.faster ? "rychleji" : "pomaleji"}). Intenzita a Rychlost s ní počítají samy.`
  return (
    <div className={`rounded-[12px] border px-3 py-2.5 ${tone}`} data-testid={`zone-flag-${f.key}`}>
      <p className={`text-[12.5px] leading-[1.45] ${f.tone === "watch" ? "text-watch" : "text-fg-2"}`}>{text}</p>
      {f.key === "hrAbove" && canSave && (
        <button type="button" disabled={busy} onClick={() => onSave(f.hr)} data-testid="zone-save-hrmax"
          className="mt-2 rounded-full bg-watch/15 px-3 py-1.5 text-[12px] font-bold text-watch transition hover:bg-watch/25 disabled:opacity-60">
          {busy ? "Ukládám…" : `Uložit ${f.hr} jako maximální tep`}
        </button>
      )}
    </div>
  )
}
