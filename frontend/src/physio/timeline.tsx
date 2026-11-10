// Časová osa (physio brief 2026-11-09 W7): one date axis for everything the physio needs to read cause and
// effect — running volume, the engine's three domains, pain per place, exercise sessions, the return to
// running and markers for visits, programme changes, injuries and limits. Small multiples share the x axis,
// each with its own y scale (never two scales on one plot). Days without data are gaps, never interpolated;
// round 2 F4.3: a range without any data is shaded and labelled "bez dat" on every row.
import { useMemo, useState } from "react"
import { api } from "@/api"
import { Card, Chip, Segmented } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { Empty, Loading, REGIONS, useLoad } from "@/physio/common"

// fixed categorical order; text never wears these colours (labels stay in ink)
const SERIES: [string, string, string][] = [["load", "Zátěž", "#2F5F7A"], ["mech", "Mechanika", "#7A4FA0"], ["symp", "Příznaky", "#A0522D"]]
const EVENT: Record<string, string> = { visit: "Návštěva", program: "Program", injury: "Zranění", limit: "Omezení" }
const W = 720
const PAD = 108

export function Timeline({ rid }: { rid: string }) {
  const [weeks, setWeeks] = useState("12")
  const { d, err } = useLoad<any>(() => api.timeline(rid, Number(weeks)), [rid, weeks])
  const [hover, setHover] = useState<string | null>(null)
  const [table, setTable] = useState(false)
  const days: string[] = useMemo(() => {
    if (!d) return []
    const out: string[] = []
    const t0 = new Date(`${d.from}T12:00:00Z`).getTime()
    const t1 = new Date(`${d.to}T12:00:00Z`).getTime()
    for (let t = t0; t <= t1; t += 86400000) out.push(new Date(t).toISOString().slice(0, 10))
    return out
  }, [d])
  if (!d) return <Card><Loading err={err} /></Card>
  const by: Record<string, any> = Object.fromEntries(d.days.map((x: any) => [x.date, x]))
  const n = days.length
  const x = (i: number) => PAD + (i + 0.5) * ((W - PAD - 8) / n)
  const bw = Math.max(1.5, (W - PAD - 8) / n - 2)
  const maxKm = Math.max(5, ...d.days.map((v: any) => v.km || 0))
  const places = [...new Set(d.days.flatMap((v: any) => Object.keys(v.pain || {})))] as string[]
  const idx = (iso: string) => days.indexOf((iso || "").slice(0, 10))
  const h = hover ? by[hover] || { date: hover } : null
  const empty = d.days.length === 0 && d.events.length === 0
  const gaps: any[] = d.gaps || []
  const Markers = ({ height }: { height: number }) => (
    <>{gaps.map((g: any, k: number) => {
      const a = idx(g.from), b = idx(g.to)
      if (a < 0 || b < 0) return null
      const step = (W - PAD - 8) / n
      const x0 = x(a) - step / 2, w = x(b) - x(a) + step
      return <g key={`g${k}`} data-testid="timeline-gap"><rect x={x0} y={0} width={w} height={height} fill="currentColor" opacity={0.06} />
        {w > 40 && height >= 30 && <text x={x0 + w / 2} y={12} fontSize={9} textAnchor="middle" fill="currentColor" opacity={0.6}>bez dat</text>}</g>
    })}
    {d.events.map((e: any, k: number) => {
      const i = idx(e.at)
      return i < 0 ? null : <line key={k} x1={x(i)} x2={x(i)} y1={0} y2={height} stroke="currentColor" strokeOpacity={e.type === "injury" ? 0.55 : 0.22} strokeDasharray={e.type === "visit" ? "0" : "3 3"} />
    })}</>
  )
  const HoverHits = ({ height }: { height: number }) => (
    <>{days.map((dd, i) => <rect key={dd} x={x(i) - (W - PAD - 8) / n / 2} y={0} width={(W - PAD - 8) / n} height={height} fill="transparent"
      onMouseEnter={() => setHover(dd)} onFocus={() => setHover(dd)} />)}
      {hover && idx(hover) >= 0 && <line x1={x(idx(hover))} x2={x(idx(hover))} y1={0} y2={height} stroke="currentColor" strokeOpacity={0.5} />}</>
  )
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-xl">Časová osa</h2>
        <span className="flex items-center gap-2">
          <Segmented value={weeks} onChange={setWeeks} ariaLabel="Období" options={[["4", "4 týdny"], ["8", "8 týdnů"], ["12", "12 týdnů"], ["26", "26 týdnů"]] as const} />
          <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => setTable(!table)}>{table ? "Graf" : "Tabulka"}</button>
        </span>
      </div>
      {empty ? <Empty>V tomto období klient nemá data ani události.</Empty> : table ? <TimelineTable d={d} /> : (
        <div className="mt-3 text-fg" onMouseLeave={() => setHover(null)}>
          <div className="flex flex-wrap gap-3 text-[11.5px] text-fg-2" aria-label="Legenda">
            {SERIES.map(([k, l, c]) => <span key={k} className="inline-flex items-center gap-1"><i className="inline-block h-[2px] w-4" style={{ background: c }} />{l}</span>)}
            <span>{"svislé čáry: plná = návštěva, čárkovaná = program, omezení, zranění"}</span>
          </div>
          {/* row 1: km per day */}
          <p className="mt-2 text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Běh (km za den)</p>
          <svg viewBox={`0 0 ${W} 70`} className="w-full" role="img" aria-label="Kilometry za den">
            <Markers height={70} />
            <text x={2} y={10} fontSize={9} fill="currentColor" opacity={0.6}>{Math.round(maxKm)}</text>
            <line x1={PAD} x2={W - 8} y1={66} y2={66} stroke="currentColor" strokeOpacity={0.15} />
            {days.map((dd, i) => by[dd]?.km ? <rect key={dd} x={x(i) - bw / 2} y={66 - (by[dd].km / maxKm) * 60} width={bw} height={(by[dd].km / maxKm) * 60} rx={1.5} fill="#2F5F7A" /> : null)}
            <HoverHits height={70} />
          </svg>
          {/* row 2: engine domains, one 0–100 scale (0 = within the client's own norm) */}
          <p className="mt-2 text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Odchylka od vlastní normy (0 = v normě)</p>
          <svg viewBox={`0 0 ${W} 90`} className="w-full" role="img" aria-label="Zátěž, mechanika a příznaky">
            <Markers height={90} />
            {[0, 50, 100].map((v) => <g key={v}><line x1={PAD} x2={W - 8} y1={84 - v * 0.78} y2={84 - v * 0.78} stroke="currentColor" strokeOpacity={0.08} />
              <text x={2} y={87 - v * 0.78} fontSize={9} fill="currentColor" opacity={0.6}>{v}</text></g>)}
            {SERIES.map(([k, , c]) => {
              // break the line where a day has no value — no interpolation across gaps
              const segs: string[][] = []
              let cur: string[] = []
              days.forEach((dd, i) => {
                const v = by[dd]?.[k]
                if (v == null) { if (cur.length) segs.push(cur); cur = [] } else cur.push(`${x(i)},${84 - Math.min(100, v) * 0.78}`)
              })
              if (cur.length) segs.push(cur)
              return <g key={k}>{segs.map((s, j) => s.length > 1
                ? <polyline key={j} points={s.join(" ")} fill="none" stroke={c} strokeWidth={2} strokeLinejoin="round" />
                : <circle key={j} cx={Number(s[0].split(",")[0])} cy={Number(s[0].split(",")[1])} r={2.5} fill={c} />)}</g>
            })}
            <HoverHits height={90} />
          </svg>
          {/* row 3: pain per place */}
          <p className="mt-2 text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Bolest podle místa (0–10)</p>
          {places.length === 0 ? <p className="text-[12px] text-fg-3">Bez hlášené bolesti.</p> : (
            <svg viewBox={`0 0 ${W} ${places.length * 16 + 4}`} className="w-full" role="img" aria-label="Bolest podle místa">
              <Markers height={places.length * 16 + 4} />
              {places.map((pl, r) => {
                const name = PLACE_CS[pl] || pl  // region keys from return-to-run and exercise pain, not raw "achilles"
                return (
                <g key={pl}>
                  <text x={2} y={r * 16 + 12} fontSize={9} fill="currentColor" opacity={0.75}>{name.length > 22 ? `${name.slice(0, 21)}…` : name}</text>
                  {days.map((dd, i) => {
                    const v = by[dd]?.pain?.[pl]
                    return v == null ? null : <circle key={dd} cx={x(i)} cy={r * 16 + 9} r={v ? 2 + v * 0.45 : 1.5}
                      fill={v >= 5 ? "var(--color-alert)" : v >= 3 ? "var(--color-watch)" : "var(--color-fg-3)"} stroke="var(--color-panel)" strokeWidth={1.5} />
                  })}
                </g>
                )
              })}
              <HoverHits height={places.length * 16 + 4} />
            </svg>
          )}
          {/* row 4: exercise sessions and return to running */}
          <p className="mt-2 text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Cvičení a návrat k běhu</p>
          <svg viewBox={`0 0 ${W} 34`} className="w-full" role="img" aria-label="Cvičení a sezení návratu">
            <Markers height={34} />
            {days.map((dd, i) => <g key={dd}>
              {by[dd]?.exercises ? <rect x={x(i) - 3} y={4} width={6} height={8} rx={1.5} fill="#7A4FA0" /> : null}
              {by[dd]?.rtr ? <circle cx={x(i)} cy={24} r={4} fill={by[dd].rtr.counted ? "var(--color-ok)" : "var(--color-panel)"} stroke="var(--color-fg-2)" strokeWidth={1.2} /> : null}
            </g>)}
            <HoverHits height={34} />
          </svg>
          <div className="flex justify-between text-[11px] text-fg-3"><span>{fmtD(d.from)}</span><span>{fmtD(d.to)}</span></div>
          <div className="mt-2 min-h-10 rounded-lg bg-white/[.04] px-3 py-2 text-[12.5px]" aria-live="polite">
            {h ? <>
              <b>{fmtD(h.date)}</b>
              {h.km ? ` · ${String(h.km).replace(".", ",")} km` : " · bez běhu"}
              {SERIES.filter(([k]) => h[k] != null).map(([k, l]) => ` · ${l} ${Math.round(h[k])}`).join("")}
              {Object.entries(h.pain || {}).map(([pl, v]) => ` · bolest ${pl} ${v}/10`).join("")}
              {h.exercises ? ` · cvičení ${h.exercises}×` : ""}
              {h.rtr ? ` · návrat: úroveň ${h.rtr.level}, bolest ${h.rtr.pain}/10${h.rtr.morning != null ? `, ráno ${h.rtr.morning}/10` : ""}` : ""}
              {d.events.filter((e: any) => (e.at || "").slice(0, 10) === h.date).map((e: any) => ` · ${e.title}`).join("")}
            </> : <span className="text-fg-3">Najeďte na den v grafu.</span>}
          </div>
        </div>
      )}
      {d.events.length > 0 && (
        <ul className="mt-3 grid gap-1 text-[12.5px]" data-testid="timeline-events">
          {[...d.events].reverse().slice(0, 12).map((e: any, k: number) => (
            <li key={k} className="flex flex-wrap items-center gap-2">
              <span className="w-28 text-fg-3">{fmtDT(e.at)}</span>
              <Chip tone={e.severity === "high" ? "alert" : e.severity === "medium" ? "watch" : "muted"}>{EVENT[e.type] || e.type}</Chip>
              <span>{e.title}{e.detail ? ` — ${e.detail}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function TimelineTable({ d }: { d: any }) {
  return (
    <div className="mt-3 max-h-[420px] overflow-auto">
      <table className="w-full text-[12.5px]">
        <thead className="sticky top-0 bg-panel text-left text-fg-3"><tr><th className="py-1">Den</th><th>km</th><th>Zátěž</th><th>Mechanika</th><th>Příznaky</th><th>Bolest</th><th>Cvičení</th></tr></thead>
        <tbody>
          {[...d.days].reverse().map((v: any) => (
            <tr key={v.date} className="border-t border-white/[.07]">
              <td className="py-1">{fmtD(v.date)}</td><td>{v.km ? String(v.km).replace(".", ",") : "—"}</td>
              {SERIES.map(([k]) => <td key={k}>{v[k] != null ? Math.round(v[k]) : "—"}</td>)}
              <td>{Object.entries(v.pain || {}).map(([pl, s]) => `${pl} ${s}`).join(", ") || "—"}</td>
              <td>{v.exercises || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PLACE_CS: Record<string, string> = Object.fromEntries(REGIONS)
