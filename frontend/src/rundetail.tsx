// OPT-9 · Deník → run detail (/app/post/:aid). Everything here comes from data the
// app already has for each run (bootstrap activities + the diary entry): the
// downsampled elevation profile, the per-third pace / HR / vertical ratio, and the
// runner's own ratings. There are no per-km splits in the data, so the per-km table
// shows climb and descent computed from the elevation profile.
import { useMemo, useRef, useState } from "react"
import { Link, useParams } from "react-router"
import { ArrowLeft, Mountain, NotebookPen } from "lucide-react"
import { useApp } from "@/store"
import { Button, Card, ChartTip, Chip, Empty, Label } from "@/ui"
import { FEEL_LABEL, fmtD, paceStr } from "@/lib"
import { RateSheet } from "@/tabs"
import { C } from "@/tokens"

const SURF: Record<string, string> = { road: "silnice", trail: "terén", treadmill: "pás", track: "dráha" }
const n1 = (v: number) => { const r = Math.round(v * 10) / 10; return (r === 0 ? 0 : r).toLocaleString("cs-CZ") }
const n0 = (v: number) => Math.round(v).toLocaleString("cs-CZ")
const hmm = (min: number) => {
  const h = Math.floor(min / 60), m = Math.round(min % 60)
  return h ? `${h}:${String(m).padStart(2, "0")} h` : `${m} min`
}

type P = { km: number; alt: number }

// Climb / descent per whole km, interpolating the profile at each km boundary.
function perKm(pts: P[]) {
  if (pts.length < 2) return []
  const end = pts[pts.length - 1].km
  const at = (x: number) => {
    for (let i = 1; i < pts.length; i++) {
      if (pts[i].km >= x) {
        const a = pts[i - 1], b = pts[i]
        const t = b.km === a.km ? 0 : (x - a.km) / (b.km - a.km)
        return a.alt + (b.alt - a.alt) * t
      }
    }
    return pts[pts.length - 1].alt
  }
  const rows: { from: number; to: number; up: number; down: number; grade: number }[] = []
  for (let k = 0; k < end - 1e-6; k++) {
    const to = Math.min(k + 1, end)
    const xs = [k, ...pts.filter((p) => p.km > k && p.km < to).map((p) => p.km), to]
    let up = 0, down = 0
    for (let i = 1; i < xs.length; i++) {
      const d = at(xs[i]) - at(xs[i - 1])
      if (d > 0) up += d
      else down -= d
    }
    const dist = (to - k) * 1000
    rows.push({ from: k, to, up, down, grade: dist > 0 ? ((at(to) - at(k)) / dist) * 100 : 0 })
  }
  return rows
}

function ElevationChart({ pts, height = 170 }: { pts: P[]; height?: number }) {
  const [act, setAct] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const xMax = pts[pts.length - 1].km || 1
  const lo = Math.min(...pts.map((p) => p.alt)), hi = Math.max(...pts.map((p) => p.alt))
  const pad = Math.max(5, (hi - lo) * 0.2)
  const yMin = lo - pad, yMax = hi + pad
  const X = (km: number) => (km / xMax) * 100
  const Y = (alt: number) => height - ((alt - yMin) / (yMax - yMin)) * height
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.km).toFixed(2)} ${Y(p.alt).toFixed(2)}`).join(" ")
  const area = `${line} L100 ${height} L0 ${height} Z`
  const pick = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const km = ((clientX - r.left) / r.width) * xMax
    let best = 0
    pts.forEach((p, i) => { if (Math.abs(p.km - km) < Math.abs(pts[best].km - km)) best = i })
    setAct(best)
  }
  const cur = act != null ? pts[act] : null
  return (
    <div className="mt-4">
      <div className="flex gap-2">
        <div className="relative w-9 shrink-0 text-right" style={{ height }}>
          <span className="t-axis absolute right-0 top-0">{n0(hi)}</span>
          <span className="t-axis absolute bottom-0 right-0">{n0(lo)}</span>
        </div>
        <div
          ref={ref}
          className="relative min-w-0 flex-1 select-none"
          style={{ height, touchAction: "pan-y" }}
          onPointerMove={(e) => pick(e.clientX)}
          onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
          onPointerUp={() => setAct(null)}
          onPointerCancel={() => setAct(null)}
          onPointerLeave={() => setAct(null)}
        >
          <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
            {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2="100" y1={height * f} y2={height * f} stroke="rgb(255 255 255 / .07)" vectorEffect="non-scaling-stroke" />)}
            <path d={area} fill={`${C.info}1f`} />
            <path d={line} fill="none" stroke={C.info} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            {cur && <line x1={X(cur.km)} x2={X(cur.km)} y1="0" y2={height} stroke="rgb(255 255 255 / .45)" vectorEffect="non-scaling-stroke" />}
          </svg>
          {cur && (
            <>
              <i className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${X(cur.km)}%`, top: Y(cur.alt), background: C.info, boxShadow: `0 0 0 3px ${C.bg}` }} />
              <ChartTip value={`${n0(cur.alt)} m n. m.`} sub={`${n1(cur.km)} km`} color={C.info} leftPct={X(cur.km)} top={Math.max(0, Y(cur.alt) - 52)} />
            </>
          )}
        </div>
      </div>
      <div className="ml-11 mt-1.5 flex justify-between">
        <span className="t-axis">0 km</span>
        <span className="t-axis">{n1(xMax / 2)} km</span>
        <span className="t-axis">{n1(xMax)} km</span>
      </div>
    </div>
  )
}

function Dial({ value, max, label, caption, col }: { value: number | null | undefined; max: number; label: string; caption?: string; col: string }) {
  const R = 40, L = Math.PI * R
  const f = value == null ? 0 : Math.max(0, Math.min(1, value / max))
  const arc = "M10 52 A40 40 0 0 1 90 52"
  return (
    <div className="nest grid justify-items-center p-3 text-center">
      <p className="t-label !text-fg-3">{label}</p>
      <div className="relative mt-2 w-full max-w-[140px]">
        <svg viewBox="0 0 100 58" className="w-full" aria-hidden>
          <path d={arc} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth="9" strokeLinecap="round" />
          {f > 0 && <path d={arc} fill="none" stroke={col} strokeWidth="9" strokeLinecap="round" strokeDasharray={`${L * f} ${L}`} />}
        </svg>
        <span className="absolute inset-x-0 bottom-0 text-center">
          <b className="t-num text-[26px] leading-none" style={{ color: value == null ? C.fg3 : C.fg }}>{value ?? "—"}</b>
          <small className="text-[12px] font-semibold text-fg-3">/{max}</small>
        </span>
      </div>
      {caption && <p className="mt-1.5 text-[13px] font-bold" style={{ color: col }}>{caption}</p>}
    </div>
  )
}

function Tile({ label, value, sub, col }: { label: string; value: string; sub?: string; col?: string }) {
  return (
    <div className="nest p-3">
      <p className="t-label !text-fg-3">{label}</p>
      <p className="t-num mt-1 whitespace-nowrap text-[20px]" style={{ color: col || C.fg }}>{value}</p>
      {sub && <p className="text-[11px] text-fg-3">{sub}</p>}
    </div>
  )
}

export function RunDetail() {
  const { aid } = useParams()
  const { me, boot, refresh } = useApp()
  const rid = me?.runner_id
  const [editing, setEditing] = useState(false)
  const acts = (boot?.activities || []) as any[]
  const fbs = (boot?.activity_feedback || []) as any[]
  const act = acts.find((a) => String(a.id) === String(aid))
  const fb = fbs.filter((f) => String(f.activity_id) === String(aid)).sort((x, y) => (y.submitted_at || "").localeCompare(x.submitted_at || ""))[0]
  const pts: P[] = useMemo(
    () => ((act?.elevation_profile || []) as any[]).filter((p) => p && p.altitude_m != null).map((p) => ({ km: (p.distance_m || 0) / 1000, alt: p.altitude_m })),
    [act],
  )
  const kmRows = useMemo(() => perKm(pts), [pts])

  const back = (
    <Link to="/app/post" className="inline-flex items-center gap-1.5 text-[13px] font-bold text-fg-2 hover:text-fg">
      <ArrowLeft className="size-4" aria-hidden /> Deník
    </Link>
  )
  if (!boot) return <>{back}<div className="mt-4"><Empty>Načítám…</Empty></div></>
  if (!act) return <>{back}<div className="mt-4"><Empty>Tento běh už v přehledu není.</Empty></div></>

  const feelCol = (v?: number) => (v == null ? C.fg3 : v >= 4 ? C.ok : v === 3 ? C.info : v === 2 ? C.watch : C.alert)
  const painCol = (v?: number) => (v == null ? C.fg : v >= 4 ? C.alert : v >= 2 ? C.watch : C.ok)
  const thirds = [0, 1, 2].map((i) => ({ pace: act.pace_thirds?.[i], hr: act.hr_thirds?.[i], vr: act.vr_thirds?.[i] }))
  const hasThirds = thirds.some((t) => t.pace != null || t.hr != null || t.vr != null)
  const maxUp = Math.max(1, ...kmRows.map((r) => Math.max(r.up, r.down)))
  const regions: string[] = ((fb?.pain_points || []) as any[]).map((p) => `${p.region}${p.side ? ` (${p.side})` : ""}`).filter(Boolean)

  return (
    <>
      {editing && rid && <RateSheet act={act} initial={fb} rid={rid} onClose={() => setEditing(false)} onDone={() => { setEditing(false); refresh() }} />}
      {back}
      <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <Label>{`Detail běhu · ${fmtD(act.started_at)}${act.start_time ? ` · ${act.start_time}` : ""}`}</Label>
          <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">{act.title} · {n1(act.distance_km)} km</h1>
        </div>
        {rid && <Button variant={fb ? "outline" : "primary"} size="sm" icon={NotebookPen} onClick={() => setEditing(true)}>{fb ? "Upravit zápis" : "Zapsat"}</Button>}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Tile label="Čas" value={act.duration_min ? hmm(act.duration_min) : "—"} />
        <Tile label="Tempo" value={act.pace_s_km ? `${paceStr(act.pace_s_km)}` : "—"} sub="/km" />
        <Tile label="Tep" value={act.avg_hr ? n0(act.avg_hr) : "—"} sub="průměr, tep/min" />
        <Tile label="Terén" value={SURF[act.surface] || act.surface || "—"} sub={act.temp_c != null ? `${n0(act.temp_c)} °C` : undefined} />
      </div>

      <div className="mt-4 grid items-start gap-4 md:grid-cols-2">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Výškový profil</Label>
              <span className="flex gap-1.5">
                <Chip tone="info">↑ {act.ascent_m != null ? n0(act.ascent_m) : "—"} m</Chip>
                <Chip tone="info">↓ {act.descent_m != null ? n0(act.descent_m) : "—"} m</Chip>
              </span>
            </div>
            {pts.length >= 2 ? <ElevationChart pts={pts} /> : <div className="mt-4"><Empty icon={Mountain}>K tomuto běhu nemáme výškový profil.</Empty></div>}
          </Card>
          <Card>
            <Label>Jak se běh cítil</Label>
            {fb ? (
              <>
                <div className="mt-3 grid grid-cols-2 gap-2.5">
                  <Dial label="Pocit" value={fb.feeling} max={5} caption={FEEL_LABEL[fb.feeling]} col={feelCol(fb.feeling)} />
                  <Dial label="Nohy" value={fb.legs} max={5} caption={fb.legs != null ? (fb.legs <= 2 ? "těžké" : fb.legs >= 4 ? "svěží" : undefined) : undefined} col={feelCol(fb.legs)} />
                </div>
                <div className="mt-2.5 grid grid-cols-3 gap-2.5">
                  <Tile label="RPE" value={fb.rpe != null ? `${fb.rpe}/10` : "—"} sub={act.rpe ? `hodinky ${act.rpe}/10` : undefined} />
                  <Tile label="Bolest" value={fb.pain_during != null ? `${fb.pain_during}/10` : "—"} col={painCol(fb.pain_during)} />
                  <Tile label="Ztuhlost" value={fb.stiffness_pre != null ? `${fb.stiffness_pre}/5` : "—"} sub="před během" />
                </div>
                {regions.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{regions.map((r) => <Chip key={r} tone="alert">{r}</Chip>)}</div>}
                {fb.note && <p className="nest mt-3 p-3 text-[13px] leading-5 text-fg-soft">„{fb.note}“</p>}
              </>
            ) : (
              <div className="mt-3"><Empty>Tento běh ještě nemá zápis. Zapište, jak se cítil.</Empty></div>
            )}
          </Card>
      </div>
      <div className="mt-4 grid items-start gap-4 md:grid-cols-2">
          {kmRows.length > 0 && (
            <Card>
              <Label>Převýšení po kilometrech</Label>
              <p className="mt-1 text-[12px] text-fg-3">Spočítáno z výškového profilu běhu. Tempo po kilometrech v datech není.</p>
              <div className="mt-3 max-h-[420px] overflow-auto rounded-[12px] border border-white/[.07]">
                <table className="w-full text-[13px]">
                  <thead className="sticky top-0 bg-panel-2 text-left">
                    <tr className="text-[11px] font-bold uppercase tracking-[.1em] text-fg-3">
                      <th className="px-3 py-2 font-bold">Km</th>
                      <th className="px-3 py-2 text-right font-bold">Stoupání</th>
                      <th className="px-3 py-2 text-right font-bold">Klesání</th>
                      <th className="hidden px-3 py-2 font-bold sm:table-cell" aria-hidden />
                      <th className="px-3 py-2 text-right font-bold">Sklon</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {kmRows.map((r) => (
                      <tr key={r.from} className="border-t border-white/[.05]">
                        <td className="px-3 py-1.5 text-fg-2">{r.to - r.from < 0.999 ? `${r.from + 1} (${n1(r.to - r.from)})` : r.from + 1}</td>
                        <td className="px-3 py-1.5 text-right text-fg">{n0(r.up)} m</td>
                        <td className="px-3 py-1.5 text-right text-fg">{n0(r.down)} m</td>
                        <td className="hidden w-[30%] px-3 py-1.5 sm:table-cell">
                          <span className="flex h-2 items-center gap-px">
                            <i className="block h-full rounded-l-full" style={{ width: `${(r.down / maxUp) * 50}%`, marginLeft: `${50 - (r.down / maxUp) * 50}%`, background: C.self }} />
                            <i className="block h-full rounded-r-full" style={{ width: `${(r.up / maxUp) * 50}%`, background: C.alert }} />
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-right text-fg-2">{Math.round(r.grade * 10) > 0 ? "+" : ""}{n1(r.grade)} %</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          {hasThirds && (
            <Card>
              <Label>Po třetinách běhu</Label>
              <div className="mt-3 overflow-hidden rounded-[12px] border border-white/[.07]">
                <table className="w-full text-[13px] tabular-nums">
                  <thead className="bg-panel-2 text-left">
                    <tr className="text-[11px] font-bold uppercase tracking-[.1em] text-fg-3">
                      <th className="px-3 py-2 font-bold">Třetina</th>
                      <th className="px-3 py-2 text-right font-bold">Tempo</th>
                      <th className="px-3 py-2 text-right font-bold">Tep</th>
                      <th className="px-3 py-2 text-right font-bold">VR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {thirds.map((t, i) => (
                      <tr key={i} className="border-t border-white/[.05]">
                        <td className="px-3 py-2 text-fg-2">{i + 1}.</td>
                        <td className="px-3 py-2 text-right text-fg">{t.pace != null ? `${paceStr(t.pace)}/km` : "—"}</td>
                        <td className="px-3 py-2 text-right text-fg">{t.hr != null ? n0(t.hr) : "—"}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right text-fg">{t.vr != null ? `${n1(t.vr)} %` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] leading-4 text-fg-3">VR = vertikální poměr (kmitání vůči délce kroku).</p>
            </Card>
          )}
      </div>
    </>
  )
}
