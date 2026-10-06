// The day so far on Trénink (owner request 2026-10-03): what the evening report shows,
// live — readiness from the morning to now (today's sessions and the day outside
// training, engine v0.10.4), the day's timeline (energy, states by the quarter hour) and
// the load outside training against the usual day. Backend: daily_report.day_today.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { InfoDot } from "@/ui"
import { Waterfall, type WStep } from "@/waterfall"
import { DayTimeline } from "@/report"
import { readinessCol } from "@/capacity"
import { C } from "@/tokens"

const TRAIN_COL = "#b08a22", NT_COL = "#2c8cc6"
const num = (v: number | null | undefined, d = 0) => (v == null ? "—" : (Math.round(v * 10 ** d) / 10 ** d).toLocaleString("cs-CZ"))
const INFO =
  "Připravenost ráno vychází z noci (HRV, klidový tep, spánek). Během dne ji snižuje dnešní trénink podle náročnosti proti vašim obvyklým dnům a od v0.10.4 i den mimo trénink: pohyb nad váš obvyklý den (nejvýš asi 8 bodů) a zvýšený tep v klidu. Druhý den ráno ji nahradí noční data. Mimo trénink se počítá chůze a pohyb s tepem nad 25 % tepové rezervy, poloviční vahou; do Celkové zátěže jde jen to, co je nad mediánem vašich posledních 28 dní. Obvyklý den potřebuje aspoň 7 dní celodenního tepu z hodinek."

function Tile({ label, value, col }: { label: string; value: string; col?: string }) {
  return (
    <div className="rounded-[14px] bg-white/[.05] px-2 py-2 text-center">
      <p className="text-[10.5px] text-fg-3">{label}</p>
      <p className="t-num mt-0.5 text-[18px] leading-tight" style={col ? { color: col } : undefined}>{value}</p>
    </div>
  )
}

export function DayToday({ rid, stamp }: { rid?: string; stamp?: string }) {
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    if (!rid) return
    let alive = true
    setErr(false)
    api.dayToday(rid).then((x: any) => alive && setD(x)).catch(() => alive && setErr(true))
    return () => { alive = false }
  }, [rid, stamp])
  if (!rid || err) return null
  if (!d) return <section className="card mt-4 p-4 md:p-6"><p className="animate-pulse text-[12px] text-fg-3">Načítám průběh dne…</p></section>
  const r = d.readiness || {}, v = d.view, ld = d.load || {}
  const steps: WStep[] = []
  if (r.morning != null) {
    steps.push({ key: "m", label: "Ráno", sub: "po noci", total: r.morning })
    if (r.sessionDrop >= 0.5)
      steps.push({ key: "s", label: r.carry ? "Včerejší trénink doznívá" : "Dnešní trénink", sub: [...(r.sessions || []), r.band].filter(Boolean).join(" · ") || undefined, delta: -r.sessionDrop })
    if (r.dayDrop >= 0.5) {
      const bits = [r.nt && `pohyb +${num(r.nt.excess)} bodů zátěže nad obvyklý den`, r.stress && `${num(r.stress.min)} min zvýšeného tepu v klidu`].filter(Boolean)
      steps.push({ key: "d", label: "Mimo trénink", sub: bits.join(" · ") || undefined, delta: -r.dayDrop })
    }
    const now = r.now ?? r.morning
    steps.push({ key: "now", label: steps.length > 1 ? "Teď" : "Dnes", total: now, color: readinessCol(now) })
  }
  let run = 0, min = 100
  for (const st of steps) { run = st.total ?? run + (st.delta || 0); min = Math.min(min, run) }
  const lo = Math.max(0, Math.floor((min - 10) / 10) * 10)
  // why the day outside training does (not) lower readiness right now
  const why = !v ? "Celodenní tep z hodinek za dnešek zatím nedorazil. Po synchronizaci se průběh dne doplní."
    : ld.usualNt == null ? "Váš obvyklý den se teprve skládá: potřebuje aspoň 7 dní celodenního tepu z hodinek. Do té doby se den mimo trénink do připravenosti nepočítá."
    : r.dayDrop >= 0.5 ? null
    : (ld.excess || 0) > 0 ? "Pohybu mimo trénink je dnes víc než obvykle, připravenost to zatím nesnižuje o celý bod."
    : "Mimo trénink zatím běžný den, připravenost nesnižuje."
  const tr = ld.train || 0, nt = ld.nt || 0
  const scale = Math.max(1, tr + nt, tr + (ld.usualNt || 0))
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="day-today">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><span className="t-label !text-fg-3">Dnešní den · do teď</span><InfoDot text={INFO} label="Dnešní den" /></span>
        {v?.steps ? <span className="text-[11px] text-fg-3">{num(v.steps)} kroků</span> : null}
      </div>

      {steps.length > 0 && (
        <div className="nest mt-3 p-3.5">
          <p className="t-label !text-fg-3">Připravenost během dne</p>
          <Waterfall steps={steps} lo={lo} hi={100} unit=" %" testid="day-readiness" wrapSub />
          {why && <p className="mt-2 text-[11.5px] leading-[17px] text-fg-3">{why}</p>}
        </div>
      )}

      {v ? (
        <>
          <div className="nest mt-3 p-3.5">
            <div className="flex items-baseline justify-between gap-2">
              <p className="t-label !text-fg-3">Průběh dne</p>
              <span className="text-[10.5px] text-fg-3">táhněte prstem pro detail</span>
            </div>
            <div className="mt-3"><DayTimeline v={v} until={d.nowMin} /></div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              <Tile label="Trénink" value={`${num(v.trainingMin)}′`} />
              <Tile label="Pohyb" value={`${num(v.activeMin)}′`} />
              <Tile label="Zvýšený tep" value={`${num((v.highMin || 0) + (v.mildMin || 0))}′`} col={v.highMin >= 30 ? C.watch : undefined} />
              <Tile label="Klid" value={`${num(v.calmMin)}′`} />
            </div>
          </div>

          <div className="nest mt-3 p-3.5" data-testid="day-load">
            <div className="flex items-baseline justify-between gap-2">
              <p className="t-label !text-fg-3">Zátěž dne</p>
              <b className="text-[13px] tabular-nums text-fg">{num(tr + nt)} bodů</b>
            </div>
            <div className="relative mt-2.5 flex h-4 overflow-hidden rounded-full bg-white/[.06]">
              {tr > 0 && <i style={{ width: `${(tr / scale) * 100}%`, background: TRAIN_COL }} title={`trénink ${num(tr)} bodů`} />}
              {nt > 0 && <i style={{ width: `${(nt / scale) * 100}%`, background: NT_COL, marginLeft: tr > 0 ? 2 : 0 }} title={`mimo trénink ${num(nt)} bodů`} />}
              {ld.usualNt != null && <i className="absolute inset-y-0 w-0.5 bg-fg" style={{ left: `calc(${((tr + ld.usualNt) / scale) * 100}% - 1px)` }} title="obvyklý den mimo trénink" />}
            </div>
            <ul className="mt-2.5 space-y-1.5 text-[12.5px]">
              <li className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 text-fg-2"><i className="size-2.5 rounded-sm" style={{ background: TRAIN_COL }} />Trénink</span>
                <b className="tabular-nums text-fg">{num(tr)} bodů</b>
              </li>
              <li className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 text-fg-2"><i className="size-2.5 rounded-sm" style={{ background: NT_COL }} />Mimo trénink{ld.usualNt != null ? <span className="text-fg-3">{` · obvykle ${num(ld.usualNt)}`}</span> : null}</span>
                <b className="tabular-nums text-fg">{num(nt)} bodů</b>
              </li>
              <li className="flex items-baseline justify-between gap-2 border-t border-white/[.07] pt-1.5">
                <span className="text-fg-2">Nad obvyklý den, do Celkové zátěže</span>
                <b className="tabular-nums" style={{ color: (ld.excess || 0) > 0 ? NT_COL : C.fg3 }}>{(ld.excess || 0) > 0 ? `+${num(ld.excess)} bodů` : "0"}</b>
              </li>
            </ul>
            <p className="mt-2 text-[11px] leading-4 text-fg-3">Mimo trénink se počítá chůze a pohyb s tepem nad 25 % tepové rezervy, poloviční vahou. Bílá čárka je váš obvyklý den mimo trénink. Body zátěže = tep × čas.</p>
          </div>
        </>
      ) : null}
    </section>
  )
}
