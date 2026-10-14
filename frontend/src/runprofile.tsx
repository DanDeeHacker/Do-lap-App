// v0.12.13 — run detail from the detailed data: the route (the runner's own session only), pace and
// heart rate along the run (two small charts, one shared crosshair — never two scales on one axis),
// the km splits and, for a steady run of an hour or more, the aerobic decoupling.
import { Suspense, lazy, useEffect, useRef, useState } from "react"
import { Footprints, Maximize2 } from "lucide-react"
import { api } from "@/api"
import { Card, ChartTip, InfoDot, Label, Segmented, Sheet } from "@/ui"
import { paceStr } from "@/lib"
import { C } from "@/tokens"

const RouteMap = lazy(() => import("@/routemap"))
const HR_COL = "#de5a8e"      // the app's validated palette (outlook.SRC)
const n1 = (v: number) => (Math.round(v * 10) / 10).toLocaleString("cs-CZ")
const n0 = (v: number) => Math.round(v).toLocaleString("cs-CZ")

export function useRunTrack(rid?: string, aid?: string | number) {
  const [d, setD] = useState<any | null | false>(null)   // null = loading, false = nothing to show
  useEffect(() => {
    if (!rid || aid == null) return
    let alive = true
    setD(null)
    api.runTrack(rid, aid).then((x: any) => alive && setD(x || false)).catch(() => alive && setD(false))
    return () => { alive = false }
  }, [rid, aid])
  return d
}

export function RouteCard({ route }: { route: [number, number][] }) {
  const [big, setBig] = useState(false)
  return (
    <Card className="mt-4" data-testid="run-route">
      <div className="flex items-center justify-between gap-2">
        <Label>Trasa</Label>
        <button type="button" onClick={() => setBig(true)} className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-accent" data-testid="run-route-open">
          <Maximize2 className="size-3.5" aria-hidden />Zvětšit
        </button>
      </div>
      <button type="button" onClick={() => setBig(true)} className="mt-3 block w-full text-left" aria-label="Zvětšit mapu trasy">
        <Suspense fallback={<div className="h-[220px] rounded-[14px] bg-white/[.04]" />}><RouteMap route={route} /></Suspense>
      </button>
      <p className="mt-2 text-[11px] text-fg-3">Trasu vidíte jen vy, fyzioterapeut ani trenér ji nevidí.</p>
      {big && (
        <Sheet open onClose={() => setBig(false)}>
          <Label>Trasa</Label>
          <div className="mt-3"><Suspense fallback={<div className="h-[60vh] rounded-[14px] bg-white/[.04]" />}><RouteMap route={route} interactive height="62vh" /></Suspense></div>
        </Sheet>
      )}
    </Card>
  )
}

type Pt = { km: number; t: number; pace: number | null; hr: number | null; alt: number | null }

const pct = (vs: number[], q: number) => { const s = [...vs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.max(0, Math.round(q * (s.length - 1))))] }

// one small line chart over the distance; `invert` puts the lower value on top (faster pace up)
function Strip({ pts, field, col, label, fmt, unit, invert, hover, onHover, height = 92 }: {
  pts: Pt[]; field: "pace" | "hr"; col: string; label: string; fmt: (v: number) => string; unit: string; invert?: boolean
  hover: number | null; onHover: (i: number | null) => void; height?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const vs = pts.map((p) => p[field]).filter((v): v is number => v != null)
  if (vs.length < 2) return null
  // the axis from the 3rd to 97th percentile: a stop or a sprint doesn't flatten the line
  let lo = pct(vs, 0.03), hi = pct(vs, 0.97)
  if (hi - lo < 4) { lo -= 2; hi += 2 }
  const pad = (hi - lo) * 0.12
  lo -= pad; hi += pad
  const xMax = pts[pts.length - 1].km || 1
  const X = (km: number) => (km / xMax) * 100
  const Y = (v: number) => { const c = Math.max(lo, Math.min(hi, v)); const f = (c - lo) / (hi - lo); return (invert ? f : 1 - f) * height }
  let d = "", pen = false
  pts.forEach((p) => {
    const v = p[field]
    if (v == null) { pen = false; return }
    d += `${pen ? "L" : "M"}${X(p.km).toFixed(2)} ${Y(v).toFixed(2)} `
    pen = true
  })
  const avg = vs.reduce((a, b) => a + b, 0) / vs.length
  const pick = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const km = ((clientX - r.left) / r.width) * xMax
    let best = 0
    pts.forEach((p, i) => { if (Math.abs(p.km - km) < Math.abs(pts[best].km - km)) best = i })
    onHover(best)
  }
  const cur = hover != null ? pts[hover] : null
  const cv = cur ? cur[field] : null
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] font-semibold text-fg-2"><i className="mr-1.5 inline-block h-[3px] w-3 rounded-full align-middle" style={{ background: col }} />{label}</span>
        <span className="text-[11px] text-fg-3">{`průměr ${fmt(avg)} ${unit}`}</span>
      </div>
      <div className="mt-1 flex gap-2">
        <div className="relative w-9 shrink-0 text-right" style={{ height }}>
          <span className="t-axis absolute right-0 top-0">{fmt(invert ? lo + pad : hi - pad)}</span>
          <span className="t-axis absolute bottom-0 right-0">{fmt(invert ? hi - pad : lo + pad)}</span>
        </div>
        <div ref={ref} className="relative min-w-0 flex-1 select-none" style={{ height, touchAction: "pan-y" }}
          onPointerMove={(e) => pick(e.clientX)}
          onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
          onPointerUp={() => onHover(null)} onPointerCancel={() => onHover(null)} onPointerLeave={() => onHover(null)}>
          <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
            {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2="100" y1={height * f} y2={height * f} stroke="rgb(255 255 255 / .07)" vectorEffect="non-scaling-stroke" />)}
            <line x1="0" x2="100" y1={Y(avg)} y2={Y(avg)} stroke={col} strokeOpacity=".45" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
            <path d={d} fill="none" stroke={col} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            {cur && <line x1={X(cur.km)} x2={X(cur.km)} y1="0" y2={height} stroke="rgb(255 255 255 / .45)" vectorEffect="non-scaling-stroke" />}
          </svg>
          {cur && cv != null && <i className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${X(cur.km)}%`, top: Y(cv), background: col, boxShadow: `0 0 0 3px ${C.panel}` }} />}
        </div>
      </div>
    </div>
  )
}

const fmtPace = (v: number) => paceStr(v)
const hms = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.round(s % 60); return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}` }

export function ProgressCard({ tr }: { tr: any }) {
  const pts: Pt[] = tr.series || []
  const splits: any[] = tr.splits || []
  const [tab, setTab] = useState<"g" | "s">(pts.length > 1 ? "g" : "s")
  const [hover, setHover] = useState<number | null>(null)
  const cur = hover != null ? pts[hover] : null
  const xMax = pts.length ? pts[pts.length - 1].km : 0
  const fast = Math.min(...splits.filter((s) => s.pace && s.km === Math.round(s.km)).map((s) => s.pace))
  return (
    <Card className="mt-4" data-testid="run-progress">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Průběh běhu</Label>
        {pts.length > 1 && splits.length > 0 && <Segmented size="sm" ariaLabel="Průběh běhu" value={tab} onChange={setTab} options={[["g", "Graf"], ["s", "Mezičasy"]] as const} />}
      </div>
      {tab === "g" && pts.length > 1 ? (
        <div className="relative mt-3 grid gap-3">
          <Strip pts={pts} field="pace" col={C.info} label="Tempo" fmt={fmtPace} unit="/km" invert hover={hover} onHover={setHover} />
          <Strip pts={pts} field="hr" col={HR_COL} label="Tep" fmt={n0} unit="tep/min" hover={hover} onHover={setHover} />
          <div className="ml-11 flex justify-between">
            <span className="t-axis">0 km</span><span className="t-axis">{n1(xMax / 2)} km</span><span className="t-axis">{n1(xMax)} km</span>
          </div>
          {cur && (
            <ChartTip leftPct={(cur.km / (xMax || 1)) * 100} top={-8} color={C.fg}
              value={<>{cur.pace != null ? `${paceStr(cur.pace)} /km` : "stání"}{cur.hr != null ? ` · ${cur.hr} tep` : ""}</>}
              sub={`${n1(cur.km)} km${cur.alt != null ? ` · ${n0(cur.alt)} m n. m.` : ""}`} />
          )}
        </div>
      ) : (
        <div className="mt-3 max-h-[420px] overflow-auto rounded-[12px] border border-white/[.07]" data-testid="run-splits">
          <table className="w-full text-[13px] tabular-nums">
            <thead className="sticky top-0 bg-panel-2 text-left">
              <tr className="text-[11px] font-bold uppercase tracking-[.1em] text-fg-3">
                <th className="px-3 py-2 font-bold">Km</th><th className="px-3 py-2 text-right font-bold">Tempo</th>
                <th className="px-3 py-2 text-right font-bold">Tep</th><th className="px-3 py-2 text-right font-bold">↑ / ↓ m</th>
              </tr>
            </thead>
            <tbody>
              {splits.map((s) => (
                <tr key={s.km} className="border-t border-white/[.05]">
                  <td className="px-3 py-1.5 text-fg-2">{s.km === Math.round(s.km) ? s.km : n1(s.km)}</td>
                  <td className="px-3 py-1.5 text-right" style={{ color: s.pace === fast ? C.ok : C.fg }}>{s.pace ? paceStr(s.pace) : "—"}<span className="text-fg-3">{s.km === Math.round(s.km) ? "" : ` · ${hms(s.s)}`}</span></td>
                  <td className="px-3 py-1.5 text-right text-fg">{s.hr ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right text-fg-2">{`${s.up} / ${s.down}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "s" && splits.length > 0 && <p className="mt-1.5 text-[11px] text-fg-3">Nejrychlejší celý kilometr je zeleně. Tempo je z času v pohybu, stání se nepočítá.</p>}
      {tr.decoupling && <Decoupling d={tr.decoupling} />}
    </Card>
  )
}

function Decoupling({ d }: { d: any }) {
  const up = d.pct > 0.5
  const col = d.stable ? C.ok : C.watch
  return (
    <div className="nest mt-3 px-3 py-2.5" data-testid="run-decoupling">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><span className="text-[12px] font-semibold text-fg-2">Stabilita tepu</span>
          <InfoDot label="Stabilita tepu" text="U rovnoměrného běhu od hodiny: kolik rychlosti (přepočtené na rovinu) dal jeden úder srdce ve druhé polovině proti první, bez prvních 10 minut. Čím menší posun, tím lépe tělo drží tempo bez stoupání tepu. U maratonců šel menší posun s rychlejším časem (Smyth 2022). Hranice 5 % je trenérská zvyklost. Horko a ztráta tekutin zvedají tep i bez únavy." /></span>
        <b className="text-[13px] tabular-nums" style={{ color: col }}>{up ? `+${n1(d.pct)} %` : "bez posunu"}</b>
      </div>
      <p className="mt-0.5 text-[12px] leading-[1.45] text-fg-3">
        {up ? `Ve druhé polovině stejné tempo stálo víc tepu (${d.hr1} → ${d.hr2} tep/min). ${d.stable ? "Do 5 % je to stabilní." : "Nad 5 % tělo tempo drželo hůř."}` : "Tep vůči tempu zůstal po celý běh stejný."}
        {d.hot ? " Běh byl v horku, tep stoupá i bez únavy." : ""}
      </p>
    </div>
  )
}

// v0.12.13 — the run's shoes: from the Garmin gear, the default pair, or the runner's pick; one
// quiet row under the run's numbers (hidden for a runner with no shoes in the profile)
const SHOE_SRC: Record<string, string> = { garmin: "z Garminu", default: "výchozí", pick: "vybrané" }
export function RunShoe({ rid, aid, shoe, canEdit }: { rid: string; aid: string | number; shoe: any; canEdit: boolean }) {
  const [list, setList] = useState<any[] | null>(null)
  const [cur, setCur] = useState<any>(shoe)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setCur(shoe) }, [shoe])
  useEffect(() => {
    let alive = true
    api.shoes(rid).then((d: any) => alive && setList(d?.shoes || [])).catch(() => alive && setList([]))
    return () => { alive = false }
  }, [rid])
  if (!list || (!list.length && !cur?.id)) return null
  const active = list.filter((s) => !s.retired_at || s.id === cur?.id)
  const value = cur?.source === "pick" ? String(cur.id) : cur?.source === "none" ? "0" : ""
  const pick = async (v: string) => {
    setBusy(true)
    try {
      const r: any = await api.setRunShoe(rid, aid, v === "" ? null : Number(v))
      setCur(r?.shoe ?? null)
    } finally { setBusy(false) }
  }
  return (
    <div className="nest mt-2.5 flex items-center gap-3 px-3 py-2.5" data-testid="run-shoe">
      <Footprints className="size-4 shrink-0 text-fg-3" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="t-label !text-fg-3">Boty</p>
        <p className="truncate text-[13.5px] font-semibold text-fg">{cur?.name || (cur?.source === "none" ? "jiné než moje" : "nevybrané")}
          {cur?.name && cur?.source !== "pick" && <span className="ml-1.5 text-[11.5px] font-normal text-fg-3">{SHOE_SRC[cur.source] || ""}</span>}</p>
      </div>
      {canEdit && (
        <select aria-label="Boty tohoto běhu" disabled={busy} value={value} onChange={(e) => pick(e.target.value)} data-testid="run-shoe-select"
          className="max-w-[46%] shrink-0 rounded-full border border-white/12 bg-transparent px-2.5 py-1.5 text-[12px] font-semibold text-accent">
          <option value="">Automaticky</option>
          {active.map((s) => <option key={s.id} value={String(s.id)}>{`${s.brand} ${s.model}`}</option>)}
          <option value="0">Jiné než moje</option>
        </select>
      )}
    </div>
  )
}
