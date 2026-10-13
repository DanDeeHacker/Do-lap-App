// Trénink k cíli, stage 1 (owner request and decisions 2026-10-12): the goal card on Trénink and
// the 3-step entry (goal and date → what it requires → the verdict). The answer comes from
// backend metrics/goal_plan.py: requirements from the studies, the week-by-week projection
// under the app's own limits, Reálné / Těsné / Nereálné, the real date and the alternatives.
// Advice only — the daily recommendation and the week's plan don't follow the goal yet.
import { useEffect, useRef, useState } from "react"
import { track } from "@/usage"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, InfoDot, Label, Segmented, Sheet, useToast } from "@/ui"
import { fmtD } from "@/lib"
import { num } from "@/outlook"
import { C } from "@/tokens"
import { useLang } from "@/i18n/lang"
import { ChevronLeft, ChevronRight, Flag, Target } from "lucide-react"

const VCOL: Record<string, string> = { ok: C.ok, tight: C.watch, no: C.alert, unknown: C.fg3 }
const DIST: [string, string][] = [["5", "5 km"], ["10", "10 km"], ["21.1", "půlmaraton"], ["42.2", "maraton"]]
const inp = "mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg"
const lbl = "text-[12px] font-semibold text-fg-2"

type Form = {
  kind: "race" | "free"; raceId: number | null; name: string; date: string; km: string; ascent: string; descent: string
  terrain: "" | "road" | "trail"; aim: "finish" | "time"; target: string
  weekly: string; long: string; climb: string; scope: "week" | "run"; hot: boolean
}
const EMPTY: Form = { kind: "race", raceId: null, name: "", date: "", km: "", ascent: "", descent: "", terrain: "", aim: "finish",
  target: "", weekly: "", long: "", climb: "", scope: "week", hot: false }

const nIn = (v: string) => (v.trim() ? Number(v.replace(",", ".")) : null)
const timeIn = (v: string) => {
  const m = v.trim().match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  return m ? +m[1] * 3600 + +m[2] * 60 + (m[3] ? +m[3] : 0) : null
}
const timeStr = (s?: number | null) => (s ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}` : "")
const strNum = (v?: number | null) => (v == null ? "" : String(v).replace(".", ","))

function formOf(goal: any): Form {
  if (!goal) return EMPTY
  const f = goal.free || {}
  return { ...EMPTY, kind: goal.kind, raceId: goal.raceId ?? null, name: goal.name || "", date: goal.date, km: strNum(goal.km),
    ascent: strNum(goal.ascentM), descent: strNum(goal.descentM), terrain: goal.terrain || "", aim: goal.aim || "finish",
    target: timeStr(goal.targetTimeS), weekly: strNum(f.weeklyKm), long: strNum(f.longKm), climb: strNum(f.climbM), scope: f.climbScope || "week",
    hot: !!goal.hot }
}

function bodyOf(f: Form) {
  return {
    kind: f.kind, race_id: f.kind === "race" ? f.raceId : null, name: f.name.trim() || null, date: f.date,
    km: f.kind === "race" ? nIn(f.km) : null, ascent_m: f.kind === "race" ? nIn(f.ascent) : null,
    descent_m: f.kind === "race" ? nIn(f.descent) : null, terrain: f.terrain || null, aim: f.aim,
    target_time_s: f.aim === "time" ? timeIn(f.target) : null,
    free: f.kind === "free" ? { weekly_km: nIn(f.weekly), long_km: nIn(f.long), climb_m: nIn(f.climb), climb_scope: f.scope } : null,
    hot: f.kind === "race" && f.hot,
  }
}

export function goalTitle(goal: any): string {
  if (!goal) return ""
  if (goal.name) return goal.name
  if (goal.kind === "free") return "Vlastní cíl"
  const km = goal.km
  return km === 42.2 ? "Maraton" : km === 21.1 ? "Půlmaraton" : `Závod ${num(km)} km`
}

function VerdictChip({ res }: { res: any }) {
  const col = VCOL[res?.verdict] || C.fg3
  return <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${col}1f`, color: col }} data-testid="goal-verdict">{res?.verdictLabel}</span>
}

function Sources({ ids, info }: { ids: string[]; info: any }) {
  const list = (ids || []).filter((i) => info?.[i])
  if (!list.length) return null
  return (
    <InfoDot label="Zdroje" wide text={<>
      {list.map((i) => <span key={i} className="block">{info[i].url ? <a href={info[i].url} target="_blank" rel="noreferrer" className="underline">{info[i].cite}</a> : info[i].cite}</span>)}
      <span className="mt-1 block opacity-80">Observační studie: ukazují souvislost, ne jistý účinek.</span>
    </>} />
  )
}

// The projection chart (owner feedback 2026-10-12: clearer and described). One metric at a
// time — the bottleneck first, the others a tap away; the last 4 weeks as history; the safe
// path (solid) and the risk path (dashed) through the loaded weeks, the recovery weeks as dots;
// the requirement, the goal's week with its date and the taper; when each path gets there or
// where it stands in the goal's week, labelled on the chart; a crosshair readout and a table.
const SERIES: Record<string, { field: string; label: string; req: string; unit: string; axis: string }> = {
  week: { field: "km", label: "Týdenní objem", req: "week", unit: "km", axis: "km za týden" },
  long: { field: "long", label: "Nejdelší běh", req: "long", unit: "km", axis: "km v jednom běhu" },
  ascentWeek: { field: "ascent", label: "Stoupání za týden", req: "ascentWeek", unit: "m", axis: "m stoupání za týden" },
  descentWeek: { field: "descent", label: "Klesání za týden", req: "descentWeek", unit: "m", axis: "m klesání za týden" },
  ascentRun: { field: "ascentRun", label: "Stoupání v jednom běhu", req: "ascentRun", unit: "m", axis: "m stoupání v jednom běhu" },
  descentRun: { field: "descentRun", label: "Klesání v jednom běhu", req: "descentRun", unit: "m", axis: "m klesání v jednom běhu" },
}
const SERIES_OF: Record<string, string> = { longCount: "long", descSessions: "descentRun" }
const addDays = (iso: string, d: number) => { const t = new Date(iso + "T12:00:00"); t.setDate(t.getDate() + d); return t.toISOString().slice(0, 10) }
// a date with its year (owner feedback 2026-10-12: "20. 3." without a year read as this spring, the weeks as days)
const fmtDY = (iso?: string) => (iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" }) : "—")
const weeksCz = (n: number) => `${n} ${n === 1 ? "týden" : n >= 2 && n <= 4 ? "týdny" : "týdnů"}`
const niceStep = (mx: number) => { const raw = mx / 4, p = 10 ** Math.floor(Math.log10(raw || 1)), f = raw / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p }

function ProjectionChart({ res }: { res: any }) {
  const reqs: any[] = res?.requirements || []
  const keys = Object.keys(SERIES).filter((k) => reqs.some((r) => r.key === k))
  const bn = res?.safe?.bottleneck || "week"
  const first = SERIES_OF[bn] || bn
  const [key, setKey] = useState<string>(keys.includes(first) ? first : keys[0])
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const sp = SERIES[key]
  const safe: any[] = res?.safe?.rows || []
  const risk: any[] = res?.risk?.rows || []
  const hist: any[] = res?.history || []
  const req = reqs.find((r) => r.key === sp?.req)
  if (!sp || !req || !safe.length || safe[0][sp.field] == null) return null
  const need = req.need as number
  const goalW = res.weeksToGoal as number
  const taper = res.taperWeeks || 0
  const sr = res.safe?.firstMet?.[key] ?? null, rr = res.risk?.firstMet?.[key] ?? null
  // weeks shown: to the goal, or to the week the safe path gets there when that is later (≤ 2 years)
  const N = Math.min(104, Math.max(goalW, sr && sr > goalW ? sr + 1 : 0, 8), Math.max(safe.length, goalW))
  const H0 = -hist.length + 1                             // history weeks: H0 … 0 (0 = last week)
  const W = 360, H = 232, pl = 36, pr = 12, pt = 24, pb = 38
  const val = (r: any) => (r?.[sp.field] ?? null) as number | null
  const sRows = safe.slice(0, N), rRows = risk.slice(0, N)
  const ymax0 = Math.max(need, ...sRows.map((r) => val(r) || 0), ...rRows.map((r) => val(r) || 0), ...hist.map((r) => val(r) || 0))
  const step = niceStep(ymax0 * 1.1)
  const ymax = Math.ceil((ymax0 * 1.08) / step) * step
  const x = (w: number) => pl + ((w - H0) / (N - H0)) * (W - pl - pr)
  const y = (v: number) => pt + (1 - v / ymax) * (H - pt - pb)
  const pts = (rows: any[], loaded: boolean) => rows.map((r, i) => ({ w: i + 1, v: val(r), d: r.deload }))
    .filter((p) => p.v != null && (loaded ? !p.d : p.d)).map((p) => `${x(p.w)},${y(p.v as number)}`).join(" ")
  const ticks = Array.from({ length: Math.round(ymax / step) + 1 }, (_, i) => i * step)
  const xstep = N > 60 ? 12 : N > 30 ? 8 : N > 14 ? 4 : 2
  const wdate = (w: number) => addDays(res.start, 7 * (w - 1))       // Monday of plan week w
  const xt = Array.from({ length: Math.floor((N - 1) / xstep) + 1 }, (_, i) => 1 + i * xstep)   // evenly from this week, so "tento týden" has room
  // why the safe path takes the weeks it does: the app's own growth limits for this runner
  const mg = res.margins || {}
  const perRun = sp.field === "long" || sp.field.endsWith("Run")
  const why = perRun
    ? (sp.field === "long"
      ? [`Nejdelší běh smí bezpečně růst nejvýš o ${num(mg.run ?? 10, 0)} % za týden.`, "Smí mít nejvýš 30 % týdenního objemu, ve specifické fázi 50 %, takže ho brzdí i týdenní objem."]
      : [`Převýšení v jednom běhu smí bezpečně růst nejvýš o ${num(mg.run ?? 10, 0)} % za týden.`, "Nepřesáhne týdenní součet, takže ho brzdí i převýšení za týden."])
    : [`Týden smí bezpečně růst nejvýš o ${num(mg.week ?? 15, 0)} % nad průměr posledních 4 týdnů, ne nad minulý týden.`, mg.avgRise != null ? `Každý 4. týden je odlehčovací, takže v průměru týden roste zhruba o ${num(mg.avgRise, 1)} %.` : "Každý 4. týden je odlehčovací.",
       ...(mg.former && sp.field === "km" ? [`Po lehčích týdnech se vracíte k dřívější úrovni (asi ${num(mg.former, 0)} km týdně) rychleji, nejvýš na 1,3× průměru posledních 4 týdnů.`] : [])]
  const atGoal = (rows: any[]) => val(rows[Math.min(goalW, rows.length) - 1])
  const fmt = (v: number | null) => (v == null ? "—" : `${num(v, sp.unit === "km" ? 0 : 0)} ${sp.unit}`)
  const sGoal = atGoal(safe), rGoal = atGoal(risk)
  const summary = sr != null
    ? `Bezpečně dosáhnete ${num(need, 0)} ${sp.unit} v týdnu ${sr} (od ${fmtDY(wdate(sr))})` + (sr + taper <= goalW ? ", před laděním." : `, závod je v týdnu ${goalW}.`)
    : `Bezpečně se ${num(need, 0)} ${sp.unit} do 2 let nedosáhne; v týdnu závodu ${fmt(sGoal)}.`
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * W
    const w = Math.round(H0 + ((px - pl) / (W - pl - pr)) * (N - H0))
    setHover(Math.max(H0, Math.min(N, w)))
  }
  const hv = hover == null ? null : hover <= 0 ? { w: hover, h: val(hist[hist.length - 1 + hover]) } : { w: hover, s: val(safe[hover - 1]), r: val(risk[hover - 1]), d: safe[hover - 1]?.deload }
  const lbl = (xx: number, yy: number, text: string, anchor: "start" | "end" | "middle" = "start", col: string = C.fgSoft) => (
    <text x={xx} y={yy} textAnchor={anchor} fontSize="10.5" fill={col} stroke={C.raised} strokeWidth="3" paintOrder="stroke">{text}</text>
  )
  return (
    <figure className="mt-4" data-testid="goal-chart">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-bold text-fg">{sp.label}{(SERIES_OF[bn] || bn) === key ? <span className="ml-1.5 rounded-full bg-white/[.07] px-2 py-0.5 text-[10px] font-bold text-fg-2">úzké hrdlo</span> : null}</p>
        <button type="button" onClick={() => setTable((v) => !v)} className="text-[11px] font-semibold text-accent" data-testid="goal-chart-table-toggle">{table ? "Graf" : "Tabulka"}</button>
      </div>
      {keys.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Co graf ukazuje">
          {keys.map((k) => (
            <button key={k} type="button" onClick={() => setKey(k)} aria-pressed={k === key}
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${k === key ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>{SERIES[k].label}</button>
          ))}
        </div>
      )}
      <p className="mt-2 text-[12px] leading-5 text-fg-soft" data-testid="goal-chart-summary">{summary}</p>
      {!table ? (
        <div className="relative mt-2">
          <p className="text-[10.5px] text-fg-3">{sp.axis}</p>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full touch-pan-y" role="img" onPointerMove={onMove} onPointerLeave={() => setHover(null)}
            aria-label={`${sp.label}: ${summary}`}>
            {ticks.map((t) => <g key={t}><line x1={pl} x2={W - pr} y1={y(t)} y2={y(t)} stroke="rgba(255,255,255,.08)" />
              <text x={pl - 6} y={y(t) + 3.5} textAnchor="end" fontSize="10" fill={C.fg3}>{t >= 1000 ? `${num(t / 1000, 1)}k` : t}</text></g>)}
            {/* history band */}
            {hist.length > 0 && <rect x={x(H0) - 4} y={pt} width={x(0) - x(H0) + 8} height={H - pt - pb} fill="rgba(255,255,255,.035)" />}
            {/* taper and the goal's week */}
            {goalW <= N && <>
              {taper > 0 && <rect x={x(goalW - taper + 0.5)} y={pt} width={x(goalW + 0.5) - x(goalW - taper + 0.5)} height={H - pt - pb} fill="rgba(255,255,255,.07)" />}
              {taper > 0 && lbl(x(goalW - taper / 2 + 0.5), pt + 11, "ladění", "middle", C.fg3)}
              <line x1={x(goalW + 0.5)} x2={x(goalW + 0.5)} y1={pt - 8} y2={H - pb} stroke={C.fg2} strokeWidth="1" />
              {lbl(x(goalW + 0.5), pt - 12, `závod ${fmtDY(res.goal?.date)}`, x(goalW) > W * 0.7 ? "end" : "middle", C.fg)}
            </>}
            {/* the requirement */}
            <line x1={pl} x2={W - pr} y1={y(need)} y2={y(need)} stroke={C.fg} strokeWidth="1" strokeDasharray="5 4" />
            {lbl(pl + 4, y(need) - 5, `požadavek ${num(need, 0)} ${sp.unit}`, "start", C.fg)}
            {/* history */}
            {hist.length > 1 && <polyline points={hist.map((r, i) => `${x(H0 + i)},${y(val(r) || 0)}`).join(" ")} fill="none" stroke={C.fg3} strokeWidth="2" strokeLinejoin="round" />}
            {hist.map((r, i) => <circle key={i} cx={x(H0 + i)} cy={y(val(r) || 0)} r="3" fill={C.fg3} />)}
            {/* paths: the loaded weeks as lines, the recovery weeks as dots */}
            {rRows.length > 0 && <polyline points={pts(rRows, true)} fill="none" stroke={C.alert} strokeWidth="2" strokeDasharray="5 4" strokeLinejoin="round" strokeLinecap="round" />}
            <polyline points={pts(sRows, true)} fill="none" stroke={C.ok} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {sRows.map((r, i) => r.deload && val(r) != null ? <circle key={i} cx={x(i + 1)} cy={y(val(r) as number)} r="2.5" fill="none" stroke={C.ok} strokeWidth="1.5" /> : null)}
            {/* when each path gets there, or where it stands in the goal's week */}
            {rr != null && rr <= N && <><circle cx={x(rr)} cy={y(val(risk[rr - 1]) || need)} r="4" fill={C.alert} stroke={C.raised} strokeWidth="2" />
              {lbl(x(rr) + (x(rr) > W * 0.75 ? -6 : 0), y(val(risk[rr - 1]) || need) + 16, `rizikově týden ${rr}`, x(rr) > W * 0.75 ? "end" : "middle", C.fgSoft)}</>}
            {sr != null && sr <= N && <><circle cx={x(sr)} cy={y(val(safe[sr - 1]) || need)} r="4" fill={C.ok} stroke={C.raised} strokeWidth="2" />
              {lbl(x(sr) + (x(sr) > W * 0.75 ? -6 : 0), y(val(safe[sr - 1]) || need) - 10, `bezpečně týden ${sr}`, x(sr) > W * 0.75 ? "end" : "middle", C.fgSoft)}</>}
            {(sr == null || sr > goalW) && goalW <= N && sGoal != null && <><circle cx={x(goalW)} cy={y(sGoal)} r="4" fill={C.ok} stroke={C.raised} strokeWidth="2" />
              {lbl(x(goalW) + (x(goalW) < W * 0.45 ? 8 : -8), y(sGoal) - 9, `v týdnu závodu ${fmt(sGoal)}`, x(goalW) < W * 0.45 ? "start" : "end", C.fgSoft)}</>}
            {/* x axis: the Monday of each week, the year under the first tick of each year */}
            {xt.map((w, i) => (
              <g key={w}><line x1={x(w)} x2={x(w)} y1={H - pb} y2={H - pb + 4} stroke={C.fg4} />
                <text x={x(w)} y={H - pb + 15} textAnchor="middle" fontSize="10" fill={C.fg3}>{w === 1 ? "tento týden" : fmtD(wdate(w))}</text>
                {(i === 0 || wdate(w).slice(0, 4) !== wdate(xt[i - 1]).slice(0, 4)) && <text x={x(w)} y={H - pb + 28} textAnchor="middle" fontSize="10" fontWeight="700" fill={C.fg2}>{wdate(w).slice(0, 4)}</text>}</g>
            ))}
            {/* crosshair */}
            {hover != null && <line x1={x(hover)} x2={x(hover)} y1={pt} y2={H - pb} stroke={C.fg2} strokeWidth="1" />}
          </svg>
          {hv && (
            <div className="pointer-events-none absolute top-6 z-10 rounded-[10px] border border-white/14 bg-raised px-2.5 py-1.5 text-[11px] shadow-[0_10px_28px_rgba(0,0,0,.5)]"
              style={{ left: `${(x(hv.w) / W) * 100}%`, transform: `translateX(${x(hv.w) > W * 0.6 ? "-105%" : "5%"})` }} data-testid="goal-chart-tip">
              <span className="block text-fg-3">{hv.w <= 0 ? `před ${1 - hv.w} týd.` : <>{`týden ${hv.w} · od ${fmtDY(wdate(hv.w))}`}{hv.d ? <span>{" · odlehčovací"}</span> : null}{hv.w > goalW - taper && hv.w <= goalW ? <span>{" · ladění"}</span> : null}</>}</span>
              {hv.w <= 0 ? <b className="block tabular-nums text-fg">{fmt(hv.h ?? null)}</b> : <>
                <span className="flex items-center gap-1.5"><i className="inline-block h-[2px] w-3" style={{ background: C.ok }} /><b className="tabular-nums text-fg">{fmt(hv.s ?? null)}</b><span className="text-fg-3">bezpečně</span></span>
                {hv.r != null && <span className="flex items-center gap-1.5"><i className="inline-block h-[2px] w-3" style={{ background: C.alert }} /><b className="tabular-nums text-fg">{fmt(hv.r)}</b><span className="text-fg-3">rizikově</span></span>}
              </>}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-2 max-h-[260px] overflow-y-auto rounded-xl border border-white/[.07]" data-testid="goal-chart-table">
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-raised text-fg-3"><tr><th className="px-2 py-1.5 text-left font-semibold">Týden</th><th className="px-2 text-right font-semibold">Bezpečně</th><th className="px-2 text-right font-semibold">Rizikově</th></tr></thead>
            <tbody>
              {hist.map((r, i) => <tr key={`h${i}`} className="text-fg-3"><td className="px-2 py-1">{`před ${hist.length - i} týd.`}</td><td className="px-2 text-right" colSpan={2}>{fmt(val(r))}</td></tr>)}
              {sRows.map((r, i) => (
                <tr key={i} className={`border-t border-white/[.05] ${i + 1 === goalW ? "text-fg" : "text-fg-soft"}`}>
                  <td className="px-2 py-1">{`${i + 1}. · ${fmtDY(wdate(i + 1))}`}{r.deload ? " · odlehčovací" : ""}{i + 1 === goalW ? " · závod" : ""}</td>
                  <td className="px-2 text-right">{fmt(val(r))}</td><td className="px-2 text-right">{fmt(val(rRows[i]))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <figcaption className="mt-2 grid gap-1 text-[11px] leading-4 text-fg-2">
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span><i className="mr-1.5 inline-block h-[2px] w-4 align-middle" style={{ background: C.fg3 }} />poslední 4 týdny</span>
          <span><i className="mr-1.5 inline-block h-[2px] w-4 align-middle" style={{ background: C.ok }} />bezpečná cesta</span>
          {rRows.length > 0 && <span><i className="mr-1.5 inline-block w-4 border-t-2 border-dashed align-middle" style={{ borderColor: C.alert }} />riziková cesta</span>}
          <span><i className="mr-1.5 inline-block size-2 rounded-full border-[1.5px] align-middle" style={{ borderColor: C.ok }} />odlehčovací týden</span>
        </span>
        <details className="text-fg-3"><summary className="cursor-pointer font-semibold text-fg-2">Jak se to počítá</summary>
        <span className="mt-1 block">Na ose jsou týdny, u každé značky datum jejich pondělí. Čára ukazuje, kolik zvládnete, když poroste jen tak rychle, jak dovolí vaše limity v aplikaci. Čárkovaná vodorovná čára je požadavek cíle, svislá týden závodu, šedé pole ladění. Prstem po grafu uvidíte hodnoty týdne.</span>
        <span className="mt-1 block" data-testid="goal-chart-why">{why.map((t, i) => <span key={i}>{i ? " " : ""}{t}</span>)}</span></details>
      </figcaption>
    </figure>
  )
}

// the best safe goal into the form: a new goal of its own (not the calendar race any more)
function bestPatch(g: any): Partial<Form> {
  if (g.kind === "free") {
    const f = g.free || {}
    return { weekly: strNum(f.weeklyKm), long: strNum(f.longKm), climb: strNum(f.climbM) }
  }
  return { raceId: null, name: "", km: strNum(g.km), ascent: strNum(g.ascentM), descent: strNum(g.descentM),
    terrain: g.terrain || "", aim: g.aim || "finish", ...(g.aim === "time" ? {} : { target: "" }) }
}

// ---- the answer at a glance (owner feedback 2026-10-13: pictures, not sentences) -------------
const readyW = (p: any): number | null => p?.earliest ?? p?.readyWeek ?? null
const chanceTxt = (c: number) => (c >= 95 ? "více než 95 %" : `${c} %`)
function headline(res: any, withChance = true): { title: string; sub: string | null } {
  const sr = readyW(res?.safe), goalW = res?.weeksToGoal
  const ch = res?.chance != null && withChance ? `Šance ${chanceTxt(res.chance)}. ` : ""
  if (res?.verdict === "ok") return { title: "Stihnete to bezpečně", sub: `${ch}Bez výpadku připraveni v týdnu ${sr} z ${goalW}.` }
  if (res?.verdict === "tight") return { title: "Těsné: vyjde jen bez větších výpadků", sub: `${ch}Bez výpadku připraveni v týdnu ${sr} z ${goalW}.` }
  if (res?.verdict === "no") return { title: res.feasible ? "Spíš to nestihnete" : "Bezpečně to nestihnete",
    sub: `${res.feasible ? ch : ""}${res.realDate ? `Reálně od ${fmtDY(res.realDate)}.` : "Ani do 2 let."}` }
  return { title: "Zatím to nejde spočítat", sub: res?.text || null }
}

// plan k cíli 2.0 #6 — the chance on a bar with the verdict's zones (Nereálné < 50 % ≤ Těsné < 80 % ≤ Reálné)
function ChanceBar({ res }: { res: any }) {
  if (res?.chance == null) return null
  const c = Math.max(0, Math.min(100, res.chance))
  const col = c >= 80 ? C.ok : c >= 50 ? C.watch : C.alert
  return (
    <div className="mt-3" data-testid="goal-chance">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] text-fg-2">Šance být včas připraven/a</span>
        <b className="text-[22px] tabular-nums leading-none" style={{ color: col }}>{c >= 95 ? "> 95 %" : `${c} %`}</b>
      </div>
      <div className="relative mt-1.5 flex h-2.5 overflow-hidden rounded-full">
        <i className="h-full" style={{ width: "50%", background: `${C.alert}33` }} />
        <i className="h-full" style={{ width: "30%", background: `${C.watch}33` }} />
        <i className="h-full" style={{ width: "20%", background: `${C.ok}33` }} />
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${c}%`, background: col }} />
      </div>
      <div className="relative mt-0.5 h-3 text-[10px] text-fg-3">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2" style={{ left: "50%" }}>50</span>
        <span className="absolute -translate-x-1/2" style={{ left: "80%" }}>80</span>
        <span className="absolute right-0">100</span>
      </div>
      {res.readyRange && <p className="mt-1 text-[11.5px] text-fg-2">{`Připraveni nejspíš mezi ${fmtDY(res.readyRange.from)} a ${fmtDY(res.readyRange.to)}.`}</p>}
    </div>
  )
}

// preparation as bars against the race line: a bar ending before the line = in time
function Timeline({ res }: { res: any }) {
  const goalW = res.weeksToGoal as number
  const taper = res.taperWeeks || 0
  const sr: number | null = readyW(res.safe)
  const rr: number | null = readyW(res.risk)
  const showRisk = rr != null && res.verdict !== "ok" && (res.riskPossible || res.path === "risk")
  const lanes = [{ key: "safe", label: "Bezpečná cesta", ready: sr, col: C.ok, dash: false },
    ...(showRisk ? [{ key: "risk", label: "Riziková cesta", ready: rr, col: C.alert, dash: true }] : [])]
  const M = Math.min(106, Math.max(goalW + 3, ...lanes.map((l) => (l.ready ?? 104) + taper + 3), 10))
  const W = 340, pl = 2, pr = 2, laneH = 30, top = 22
  const H = top + lanes.length * laneH + 18
  const x = (w: number) => pl + (Math.min(w, M) / M) * (W - pl - pr)
  const date = (w: number) => fmtDY(addDays(res.start, 7 * (w - 1)))
  const gx = x(goalW)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" data-testid="goal-timeline"
      aria-label={`Závod v týdnu ${goalW}; bezpečně připraveni ${sr ? `v týdnu ${sr}` : "ne do 2 let"}`}>
      {lanes.map((l, i) => {
        const y = top + i * laneH
        const end = l.ready != null ? x(l.ready) : x(M)
        const late = l.ready == null || l.ready + taper > goalW
        const lab = l.ready != null ? `týden ${l.ready} · ${date(l.ready)}` : "do 2 let ne"
        return (
          <g key={l.key}>
            <text x={pl} y={y + 9} fontSize="10.5" fill={C.fg3}>{l.label}</text>
            <text x={W - pr} y={y + 9} fontSize="10.5" textAnchor="end" fill={late ? C.alert : C.ok} fontWeight="700">{lab}</text>
            <rect x={pl} y={y + 14} width={W - pl - pr} height="8" rx="4" fill="rgba(255,255,255,.06)" />
            <rect x={pl} y={y + 14} width={Math.max(4, end - pl)} height="8" rx="4" fill={l.col} opacity={l.dash ? 0.75 : 1} />
            {l.ready != null && taper > 0 && <rect x={end} y={y + 14} width={Math.max(2, x(l.ready + taper) - end)} height="8" rx="2" fill={l.col} opacity=".35" />}
          </g>
        )
      })}
      <line x1={gx} x2={gx} y1={top + 12} y2={H - 14} stroke={C.fg} strokeWidth="1.5" />
      <text x={gx > W * 0.7 ? gx + 4 : gx} y={top - 8} fontSize="10.5" fontWeight="700" textAnchor={gx > W * 0.7 ? "end" : "middle"} fill={C.fg}>{`⚑ závod ${fmtDY(res.goal?.date)}`}</text>
      <text x={pl} y={H - 3} fontSize="10" fill={C.fg3}>dnes</text>
      <text x={W - pr} y={H - 3} fontSize="10" textAnchor="end" fill={C.fg3}>{date(M)}</text>
    </svg>
  )
}

function VerdictHero({ res }: { res: any }) {
  if (!res) return null
  const col = VCOL[res.verdict] || C.fg3
  const h = headline(res, false)
  return (
    <div className="nest p-3.5" style={{ borderColor: `${col}55` }} data-testid="goal-result">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[17px] font-bold leading-6" style={{ color: col }} data-testid="goal-headline">{h.title}</p>
          {h.sub && <p className="mt-0.5 text-[12px] leading-5 text-fg-2">{h.sub}</p>}
        </div>
        <VerdictChip res={res} />
      </div>
      <ChanceBar res={res} />
      {res.safe && res.weeksToGoal && <Timeline res={res} />}
      {res.safe && res.taperWeeks > 0 && <p className="mt-1 text-[10.5px] text-fg-3">Světlejší konec pruhu je ladění před závodem.</p>}
    </div>
  )
}

// what the goal needs: today, where the safe path gets by the start, and the need
const isMet = (r: any) => r.atRace != null && r.atRace >= r.need - (r.unit === "km" ? 0.05 : 0.5)
const PAIRS: [string, string, string][] = [["ascentRun", "descentRun", "Stoupání a klesání v jednom běhu"], ["ascentWeek", "descentWeek", "Stoupání a klesání za týden"]]
function merged(list: any[]): any[] {
  let out = [...list]
  for (const [a, d, label] of PAIRS) {
    const ra = out.find((r) => r.key === a), rd = out.find((r) => r.key === d)
    if (!ra || !rd || Math.abs(ra.need - rd.need) > 1) continue
    const lo = (u?: number | null, v?: number | null) => (u == null || v == null ? null : Math.min(u, v))
    const m = { ...ra, key: `${a}+${d}`, label, now: Math.min(ra.now ?? 0, rd.now ?? 0), atRace: lo(ra.atRace, rd.atRace),
      metWeek: ra.metWeek == null || rd.metWeek == null ? null : Math.max(ra.metWeek, rd.metWeek) }
    out = out.flatMap((r) => (r.key === a ? [m] : r.key === d ? [] : [r]))
  }
  return out
}
function Gauges({ res, title = true }: { res: any; title?: boolean }) {
  const reqs: any[] = merged(res?.requirements || [])
  if (!reqs.length) return null
  const build = (res.weeksToGoal || 0) - (res.taperWeeks || 0)
  return (
    <div data-testid="goal-gauges">
      {title && <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label !text-fg-3">Co cíl potřebuje</p>
        <span className="flex flex-wrap gap-3 text-[10.5px] text-fg-3">
          <span><i className="mr-1 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: C.info }} />dnes</span>
          {res.safe && <span><i className="mr-1 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: `${C.ok}66` }} />na startu</span>}
          <span><i className="mr-1 inline-block h-3 w-[2px] align-middle" style={{ background: C.fg }} />potřeba</span>
        </span>
      </div>}
      <div className="mt-1 divide-y divide-white/[.06]">
        {reqs.map((r) => {
          const count = r.unit === "×"
          const d = r.unit === "km" ? 0 : 0
          const now = r.now ?? 0
          const at = r.atRace
          const mx = Math.max(r.need, at ?? 0, now) * 1.04 || 1
          const pct = (v: number) => `${Math.min(100, (v / mx) * 100)}%`
          const met = isMet(r)
          const done = now >= r.need - 0.05
          const inTime = r.metWeek != null && r.metWeek <= build
          const status = done ? { t: "✓ už teď", c: C.ok } : inTime ? { t: `✓ v týdnu ${r.metWeek}`, c: C.ok }
            : at != null ? { t: `✕ ke startu chybí ${num(Math.max(0, r.need - at), d)} ${count ? "×" : r.unit}`, c: C.alert }
              : res.safe ? { t: "✕ do 2 let ne", c: C.alert } : null
          return (
            <div key={r.key} className="py-2" data-testid="goal-req">
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="flex min-w-0 items-center gap-1.5 font-semibold text-fg">{r.label}{r.key === "longCount" && r.km ? ` ≥ ${num(r.km, 0)} km` : ""}
                  <InfoDot label={r.label} wide text={<>
                    <span className="block">{r.why}{r.base != null ? ` (tabulka ${num(r.base, 0)} km)` : ""}</span>
                    {r.assumption && <span className="mt-1 block opacity-80">Pracovní předpoklad, přímou studii nemáme.</span>}
                    {(r.sources || []).filter((i: string) => res.sourceInfo?.[i]).map((i: string) => <span key={i} className="mt-1 block">{res.sourceInfo[i].url ? <a href={res.sourceInfo[i].url} target="_blank" rel="noreferrer" className="underline">{res.sourceInfo[i].cite}</a> : res.sourceInfo[i].cite}</span>)}
                  </>} /></span>
                <span className="whitespace-nowrap tabular-nums text-fg-3"><b className="text-fg">{num(now, d)}</b>{` → ${num(r.need, d)} ${count ? "×" : r.unit}`}</span>
              </div>
              <div className="relative mt-1.5 h-2.5 rounded-full bg-white/[.07]">
                {at != null && <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: pct(at), background: met ? `${C.ok}66` : `${C.alert}55` }} />}
                <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: pct(now), background: C.info }} />
                <i className="absolute -inset-y-1 w-[2px] rounded" style={{ left: `calc(${pct(r.need)} - 1px)`, background: C.fg }} />
              </div>
              {status && <p className="mt-1 text-[11px] font-semibold" style={{ color: status.c }}>{status.t}</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// the notes: the narrowed margin as numbers, the rest folded away
function Notes({ res }: { res: any }) {
  const notes: any[] = res?.notes || []
  if (!notes.length) return null
  const m = notes.find((n) => n.key === "margin")
  const rest = notes.filter((n) => n.key !== "margin")
  return (
    <div className="mt-3 grid gap-2">
      {m && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-xl bg-watch/[.08] px-3 py-2 text-[12px]" data-testid="goal-note">
          <b className="text-watch">{`Rezerva růstu ${num(m.pct, 0)} % místo 15 %`}</b>
          {(m.why || []).map((w: string) => <span key={w} className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] text-fg-2">{w}</span>)}
          <InfoDot label="Rezerva růstu" text={m.text} />
        </div>
      )}
      {rest.length > 0 && (
        <details className="rounded-xl bg-white/[.04] px-3 py-2 text-[12px] text-fg-soft">
          <summary className="cursor-pointer font-semibold text-fg-2">{`Na co plán myslí (${rest.length})`}</summary>
          <ul className="mt-2 grid gap-2">{rest.map((n) => <li key={n.key} data-testid="goal-note">{n.text} {n.sources?.length ? <Sources ids={n.sources} info={res.sourceInfo} /> : null}</li>)}</ul>
        </details>
      )}
    </div>
  )
}

// the options when the goal isn't safe by its date: one card each, the numbers as chips
function Options({ res, onApply }: { res: any; onApply?: (patch: Partial<Form>) => void }) {
  const alts: any[] = res?.alternatives || []
  if (!alts.length) return null
  const card = "rounded-xl p-3"
  const use = (patch: Partial<Form> | null) => patch && onApply ? <Button size="sm" variant="outline" onClick={() => onApply(patch)}>Použít</Button> : null
  return (
    <div className="mt-4" data-testid="goal-options">
      <p className="t-label !text-fg-3">Možnosti</p>
      <div className="mt-1.5 grid gap-2">
        {alts.map((x, i) => {
          if (x.kind === "best") return (
            <div key={i} className={`${card} border border-accent/40 bg-accent/[.06]`} data-testid="goal-alt-best">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-accent">Nejlepší bezpečný cíl</p>
                  <p className="mt-0.5 text-[15px] font-bold text-fg">{x.label}</p>
                  <p className="text-[11px] text-fg-3">{x.chance != null ? `do ${fmtDY(res.goal?.date)} · šance ${x.chance} %` : `do ${fmtDY(res.goal?.date)}`}</p>
                </div>
                {use(bestPatch(x.goal))}
              </div>
              {x.progress?.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">
                {x.progress.map((p: any) => <span key={p.key} className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] text-fg-2">{`${p.label} `}<b className="tabular-nums text-fg">{`${num(p.now, 0)} → ${num(p.need, 0)} ${p.unit}`}</b></span>)}
              </div>}
            </div>
          )
          if (x.kind === "later") return (
            <div key={i} className={`${card} flex items-center justify-between gap-3 bg-white/[.04]`} data-testid="goal-alt">
              <div><p className="text-[11px] font-bold uppercase tracking-wide text-fg-3">Pozdější termín</p><p className="text-[15px] font-bold text-fg">{fmtDY(x.date)}</p></div>
              {use({ date: x.date })}
            </div>
          )
          if (x.kind === "finish" || x.kind === "shorter") return (
            <div key={i} className={`${card} flex items-center justify-between gap-3 bg-white/[.04]`} data-testid="goal-alt">
              <div className="min-w-0"><p className="text-[11px] font-bold uppercase tracking-wide text-fg-3">{x.kind === "finish" ? "Cíl doběhnout" : "Kratší trať"}</p>
                <p className="flex flex-wrap items-center gap-2 text-[14px] font-bold text-fg">{x.kind === "finish" ? goalTitle(res.goal) : goalTitle({ ...x.goal, name: null })}<VerdictChip res={x} /></p></div>
              {use(x.kind === "finish" ? { aim: "finish" } : { km: strNum(x.goal.km), ascent: "", descent: "" })}
            </div>
          )
          if (x.kind === "risk") return (
            <div key={i} className={`${card} flex items-center justify-between gap-3 bg-white/[.04]`} data-testid="goal-alt">
              <div className="min-w-0"><p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-alert">Riziková cesta<InfoDot label="Riziková cesta" wide text={x.text} /></p>
                <p className="text-[13px] text-fg">{x.possible === false ? "Termín nestihne ani ona." : `Připraveni v týdnu ${x.readyWeek}, jen se souhlasem v detailu cíle.`}</p></div>
            </div>
          )
          return <p key={i} className="px-1 text-[12px] text-fg-3" data-testid="goal-alt">{x.text}</p>
        })}
      </div>
    </div>
  )
}

// the target time in three numbers
function TrainEstimate({ te }: { te: any }) {
  if (!te) return null
  return (
    <div className="mt-2 flex items-center justify-between gap-3 rounded-xl bg-white/[.04] px-3 py-2" data-testid="goal-train-estimate">
      <span className="min-w-0 text-[12px] text-fg-2">{`Z tréninku: ${num(te.kmWeek, 0)} km týdně ve vrcholu, tempo ${Math.floor(te.pace / 60)}:${String(te.pace % 60).padStart(2, "0")} /km`}</span>
      <span className="flex items-center gap-1.5"><b className="text-[15px] tabular-nums text-fg">{`${Math.floor(te.timeS / 3600)}:${String(Math.floor((te.timeS % 3600) / 60)).padStart(2, "0")}`}</b>
        <InfoDot label="Odhad z tréninku" wide text={<>{te.text}<span className="mt-1 block opacity-80">{te.note}</span></>} /></span>
    </div>
  )
}

function TargetTime({ tt, te }: { tt: any; te?: any }) {
  if (!tt && !te) return null
  if (!tt) return <div className="nest mt-4 p-3.5"><p className="t-label !text-fg-3">Odhad času</p><TrainEstimate te={te} /></div>
  const gap = tt.gapPct as number | undefined
  return (
    <div className="nest mt-4 p-3.5" data-testid="goal-target-time">
      <div className="flex items-center justify-between gap-2"><p className="t-label !text-fg-3">Cílový čas</p><InfoDot label="Cílový čas" wide text={<>{tt.text}{tt.basis ? <span className="mt-1 block opacity-80">{`Odhad z běhu ${tt.basis.title || ""} (${fmtD(tt.basis.date)}, ${num(tt.basis.km)} km) Riegelovým vzorcem.`}</span> : null}</>} /></div>
      <div className="mt-1.5 grid grid-cols-3 gap-2 text-center">
        <div><p className="text-[16px] font-bold tabular-nums text-fg">{tt.timeText}</p><p className="text-[10.5px] text-fg-3">cíl</p></div>
        <div><p className="text-[16px] font-bold tabular-nums text-fg">{tt.paceText}</p><p className="text-[10.5px] text-fg-3">tempo</p></div>
        <div><p className="text-[16px] font-bold tabular-nums" style={{ color: gap == null ? C.fg3 : gap <= 1 ? C.ok : gap <= 5 ? C.watch : C.alert }}>{tt.predictedText || "—"}</p>
          <p className="text-[10.5px] text-fg-3">{gap == null ? "dnes neznámé" : gap <= 1 ? "dnes v dosahu" : `dnes o ${num(gap, 0)} % pomaleji`}</p></div>
      </div>
      <TrainEstimate te={te} />
    </div>
  )
}

// the plan as bars, one a week, coloured by phase; a tap shows the week
function PlanBars({ plan, today }: { plan: any[]; today: string }) {
  const cur = Math.max(0, plan.findIndex((w, i) => w.start <= today && today < (plan[i + 1]?.start ?? "9999")))
  const [sel, setSel] = useState(cur)
  const [list, setList] = useState(false)
  if (!plan?.length) return null
  const W = 340, H = 110, pt = 14, pb = 16
  const n = plan.length
  const mx = Math.max(...plan.map((w) => w.km || 0), 1)
  const bw = (W / n) * 0.78, gap = W / n
  const xs = (i: number) => i * gap + (gap - bw) / 2
  const hy = (v: number) => ((v || 0) / mx) * (H - pt - pb)
  const w = plan[sel] || plan[0]
  const [pl, pc] = PHASE[w.phase] || PHASE.base
  const phases = [...new Set(plan.map((p) => p.phase))]
  const pick = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
    setSel(Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n))))
  }
  return (
    <div data-testid="goal-plan">
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full touch-pan-y" role="img" aria-label={`Plán po týdnech, ${n} týdnů`} onPointerDown={pick} onPointerMove={(e) => e.buttons && pick(e)}>
        {plan.map((p, i) => {
          const col = (PHASE[p.phase] || PHASE.base)[1]
          const h = Math.max(2, hy(p.km))
          return (
            <g key={p.i}>
              <rect x={xs(i)} y={H - pb - h} width={bw} height={h} rx={Math.min(3, bw / 2)} fill={col} opacity={p.deload || p.taper ? 0.45 : 1}
                stroke={i === sel ? C.fg : "none"} strokeWidth="1.5" strokeDasharray={p.vacation ? "2 2" : undefined} />
              {p.milestone && <circle cx={xs(i) + bw / 2} cy={H - pb - h - 6} r="2.5" fill={p.milestone === "test" ? C.watch : C.accent} />}
              {p.race && <text x={xs(i) + bw / 2} y={H - pb - h - 4} fontSize="11" textAnchor="middle" fill={C.fg}>⚑</text>}
            </g>
          )
        })}
        {cur >= 0 && <text x={xs(cur) + bw / 2} y={H - 3} fontSize="9.5" textAnchor={cur < 3 ? "start" : "middle"} fill={C.fg3}>dnes</text>}
        <text x={W} y={H - 3} fontSize="9.5" textAnchor="end" fill={C.fg3}>závod</text>
        <text x={0} y={10} fontSize="9.5" fill={C.fg3}>{`${num(mx, 0)} km`}</text>
      </svg>
      <div className="mt-1 flex flex-wrap gap-2 text-[10.5px] text-fg-3">
        {phases.map((ph) => <span key={ph}><i className="mr-1 inline-block size-2 rounded-sm align-middle" style={{ background: (PHASE[ph] || PHASE.base)[1] }} />{(PHASE[ph] || PHASE.base)[0]}</span>)}
        <span><i className="mr-1 inline-block size-2 rounded-sm align-middle opacity-45" style={{ background: C.fg3 }} />odlehčení</span>
        {plan.some((p) => p.milestone) && <span><i className="mr-1 inline-block size-2 rounded-full align-middle" style={{ background: C.accent }} />mezicíl / test</span>}
      </div>
      <div className="nest mt-2 flex items-center gap-3 px-3 py-2" data-testid="goal-plan-sel">
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] text-fg-3">{`${w.i}. týden · od ${fmtDY(w.start)}`}{sel === cur ? " · tento týden" : ""}</span>
          <span className="block text-[13px] font-semibold text-fg">{w.race ? "Týden závodu" : `${num(w.km, 0)} km`}{w.long ? ` · dlouhý ${num(w.long, 0)} km` : ""}{w.descentRun ? ` · ↓ ${num(w.descentRun, 0)} m` : ""}</span>
          {weekTags(w).length > 0 && <span className="block text-[11px] text-fg-3">{weekTags(w).join(" · ")}</span>}
        </span>
        <span className="whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
      </div>
      <button type="button" className="mt-1.5 text-[12px] font-semibold text-accent" onClick={() => setList((v) => !v)}>{list ? "Skrýt seznam" : "Seznam týdnů"}</button>
      {list && <PlanList plan={plan} today={today} />}
    </div>
  )
}

const STEPS = ["Cíl a datum", "Jde to stihnout?", "Plán"]

function GoalSetup({ rid, races, initial, onClose, onSaved }: { rid: string; races: any[]; initial: Form; onClose: () => void; onSaved: (d: any) => void }) {
  const toast = useToast()
  const [step, setStep] = useState(0)
  const [f, setF] = useState<Form>(initial)
  const [res, setRes] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const set = (p: Partial<Form>) => setF((o) => ({ ...o, ...p }))
  const valid = !!f.date && (f.kind === "race" ? !!nIn(f.km) : !!(nIn(f.weekly) || nIn(f.long) || nIn(f.climb)))
  const preview = async (form: Form = f) => {
    setBusy(true)
    try { setRes(await api.goalPreview(rid, bodyOf(form))); return true }
    catch (e: any) { toast({ title: e?.message || "Cíl se nepodařilo spočítat" }); return false }
    finally { setBusy(false) }
  }
  const next = async () => {
    if (step === 0) { if (await preview()) setStep(1) } else setStep(2)
  }
  const apply = async (p: Partial<Form>) => { const nf = { ...f, ...p }; setF(nf); await preview(nf) }
  const save = async () => {
    setBusy(true)
    try { const d = await api.saveGoal(rid, bodyOf(f)); onSaved(d); toast({ title: "Cíl uložen" }) }
    catch (e: any) { toast({ title: e?.message || "Cíl se nepodařilo uložit" }) }
    finally { setBusy(false) }
  }
  const blocked = res?.verdict === "no" && !res?.riskPossible
  const pickRace = (x: any) => set({ raceId: x.id, name: x.name || "", date: x.date, km: strNum(x.km), ascent: strNum(x.ascentM) })
  const footer = (
    <div className="flex items-center justify-between gap-2">
      {step > 0 ? <Button size="sm" variant="outline" icon={ChevronLeft} onClick={() => setStep(step - 1)}>Zpět</Button> : <span />}
      {step < 2 ? <Button size="sm" disabled={!valid || busy || (step === 1 && blocked)} busy={busy} onClick={next} data-testid="goal-next">Další<ChevronRight className="size-4" aria-hidden /></Button>
        : <Button size="sm" disabled={busy || blocked} busy={busy} onClick={save} data-testid="goal-save">Uložit cíl</Button>}
    </div>
  )
  return (
    <Sheet open onClose={onClose} footer={footer}>
      <div data-testid="goal-setup">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-[12px] bg-white/[.06]"><Target className="size-5 text-accent" aria-hidden /></span>
          <div className="min-w-0">
            <h2 className="font-serif text-[24px] leading-tight text-fg">Trénink k cíli</h2>
            <p className="text-[12px] text-fg-3">krok {step + 1} ze 3 · {STEPS[step]}</p>
          </div>
        </div>
        <ol className="mt-3 flex gap-1.5" aria-hidden>{STEPS.map((_, i) => <li key={i} className="h-1 flex-1 rounded-full" style={{ background: i <= step ? C.accent : "rgba(255,255,255,.1)" }} />)}</ol>

        {step === 0 && (
          <div className="mt-4 space-y-4">
            <Segmented ariaLabel="Druh cíle" options={[["race", "Závod"], ["free", "Vlastní cíl"]] as const} value={f.kind} onChange={(k) => set({ kind: k })} />
            {f.kind === "race" ? (<>
              {races.length > 0 && (
                <div>
                  <p className={lbl}>Závod z kalendáře</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {races.map((x) => (
                      <button key={x.id} type="button" onClick={() => pickRace(x)} aria-pressed={f.raceId === x.id}
                        className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-semibold ${f.raceId === x.id ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>
                        <Flag className="size-3.5" aria-hidden />{x.name || "Závod"} · {fmtDY(x.date)}{x.km ? ` · ${num(x.km)} km` : ""}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <label className={lbl}>Název<input className={inp} value={f.name} maxLength={120} placeholder="např. Pražský maraton" onChange={(e) => set({ name: e.target.value, raceId: null })} /></label>
                <label className={lbl}>Datum závodu<input type="date" className={inp} value={f.date} onChange={(e) => set({ date: e.target.value })} data-testid="goal-date" /></label>
                <label className={lbl}>Délka (km)
                  <input className={inp} inputMode="decimal" value={f.km} onChange={(e) => set({ km: e.target.value })} data-testid="goal-km" />
                  <span className="mt-1.5 flex flex-wrap gap-1">{DIST.map(([v, l]) => <button key={v} type="button" onClick={() => set({ km: v.replace(".", ",") })} aria-pressed={f.km === v.replace(".", ",")} className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${f.km === v.replace(".", ",") ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>{l}</button>)}</span>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className={lbl}>Stoupání (m)<input className={inp} inputMode="numeric" value={f.ascent} onChange={(e) => set({ ascent: e.target.value })} /></label>
                  <label className={lbl}>Klesání (m)<input className={inp} inputMode="numeric" placeholder={f.ascent || "jako stoupání"} value={f.descent} onChange={(e) => set({ descent: e.target.value })} /></label>
                </div>
              </div>
              <div>
                <p className={`${lbl} flex items-center gap-1.5`}>Co je cílem<InfoDot label="Doběhnout nebo cílový čas" text="Pro cílový čas aplikace počítá s vyšším objemem a delšími dlouhými běhy (horní čísla tabulky), ukáže závodní tempo a u maratonu i odhad času z tréninku." /></p>
                <Segmented className="mt-1" size="sm" ariaLabel="Co je cílem" options={[["finish", "Doběhnout"], ["time", "Cílový čas"]] as const} value={f.aim} onChange={(k) => set({ aim: k })} />
                {f.aim === "time" && <label className={`${lbl} mt-2 block max-w-[200px]`}>Cílový čas (h:mm)<input className={inp} placeholder="3:59" value={f.target} onChange={(e) => set({ target: e.target.value })} /></label>}
              </div>
              <label className="flex items-center gap-2 text-[13px] text-fg" data-testid="goal-hot">
                <input type="checkbox" checked={f.hot} onChange={(e) => set({ hot: e.target.checked })} />
                Čekám horko (letní závod)
                <InfoDot label="Horký závod" text="Plán přidá 10–14 dní aklimatizace na horko 21 až 8 dní před startem a v posledním týdnu krátké připomínky. Bez horka se adaptace ztrácí asi o 2,5 % za den." />
              </label>
            </>) : (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className={lbl}>Do kdy<input type="date" className={inp} value={f.date} onChange={(e) => set({ date: e.target.value })} data-testid="goal-date" /></label>
                <label className={lbl}>Týdenní objem (km)<input className={inp} inputMode="decimal" placeholder="např. 50" value={f.weekly} onChange={(e) => set({ weekly: e.target.value })} /></label>
                <label className={lbl}>Nejdelší běh v kuse (km)<input className={inp} inputMode="decimal" placeholder="např. 25" value={f.long} onChange={(e) => set({ long: e.target.value })} /></label>
                <div>
                  <label className={lbl}>Převýšení nahoru i dolů (m)<input className={inp} inputMode="numeric" placeholder="např. 1200" value={f.climb} onChange={(e) => set({ climb: e.target.value })} /></label>
                  <Segmented className="mt-1.5" size="sm" ariaLabel="Převýšení za" options={[["week", "za týden"], ["run", "v jednom běhu"]] as const} value={f.scope} onChange={(k) => set({ scope: k })} />
                </div>
                <p className="text-[11px] leading-4 text-fg-3 sm:col-span-2">Vyplňte jedno nebo víc čísel.</p>
              </div>
            )}
          </div>
        )}

        {step === 1 && res && (
          <div className="mt-4 grid gap-4">
            <VerdictHero res={res} />
            <div><Gauges res={res} /><Notes res={res} /></div>
            <Options res={res} onApply={apply} />
            {blocked && <p className="text-[12px] leading-5 text-alert" data-testid="goal-blocked">Tento cíl v termínu nestihne ani riziková cesta, proto ho aplikace neuloží. Použijte nejlepší bezpečný cíl nebo pozdější termín.</p>}
          </div>
        )}

        {step === 2 && res && (
          <div className="mt-4">
            {res.plan?.length > 0 && <><p className="t-label !text-fg-3">Plán po týdnech</p><PlanBars plan={res.plan} today={res.start} /></>}
            <TargetTime tt={res.targetTime} />
            {res.safe && <details className="mt-5" data-testid="goal-growth">
              <summary className="cursor-pointer t-label !text-fg-3">Jak poroste (graf)</summary>
              <ProjectionChart res={res} />
            </details>}
            <p className="mt-4 text-[11px] leading-5 text-fg-3">Po uložení se týdenní cíl na Tréninku řídí tímto plánem. Rizikovou cestu zvolíte v detailu cíle, jen s výslovným souhlasem.</p>
          </div>
        )}
      </div>
    </Sheet>
  )
}

const PHASE: Record<string, [string, string]> = {
  base: ["Základ", C.info], build: ["Rozvoj", C.ok], specific: ["Specifická příprava", C.accent], taper: ["Ladění", C.watch],
}
const SCOL: Record<string, string> = { ok: C.ok, tight: C.watch, no: C.alert }
const weekTags = (w: any): string[] => [
  ...(w.vacation ? ["dovolená"] : w.deload ? ["odlehčovací týden"] : []),
  ...(w.taper ? [`ladění, ${num((w.factor ?? 0) * 100, 0)} % vrcholu`] : []),
  ...(w.milestone === "half" ? ["mezicíl: běh na 21 km"] : w.milestone === "test" ? ["kontrolní test 5–10 km"] : []),
  ...(w.fuel ? [`výživa ${w.fuel} g/h na dlouhém běhu`] : []),
  ...(w.heat === "acclim" ? ["aklimatizace na horko"] : w.heat === "remind" ? ["připomínka horka"] : []),
  ...(w.strength != null && !w.race ? [`posilování ${w.strength}×`] : []),
]

// stage 2 — the plan towards the goal, week by week (backend goal_plan.plan_weeks)
function PlanList({ plan, today }: { plan: any[]; today: string }) {
  const [all, setAll] = useState(false)
  if (!plan?.length) return null
  const cur = plan.findIndex((w) => w.start <= today && today < (plan[plan.indexOf(w) + 1]?.start ?? "9999"))
  const from = all ? 0 : Math.max(0, cur - 1)
  const shown = all ? plan : plan.slice(from, from + 6)
  return (
    <div data-testid="goal-plan">
      <ul className="mt-2 divide-y divide-white/[.06]">
        {shown.map((w) => {
          const [pl, pc] = PHASE[w.phase] || PHASE.base
          const on = w.i === cur + 1
          return (
            <li key={w.i} className={`flex items-center gap-3 py-2 text-[12px] ${on ? "rounded-lg bg-white/[.05] px-2" : ""}`} data-testid="goal-plan-week">
              <span className="w-[52px] shrink-0 tabular-nums text-fg-3">{`${w.i}. týd.`}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-fg">{w.race ? "Týden závodu" : `${num(w.km, 0)} km`}{w.long ? ` · dlouhý ${num(w.long, 0)} km` : ""}{w.descentRun ? ` · ↓ ${num(w.descentRun, 0)} m` : ""}</span>
                <span className="block text-[11px] text-fg-3"><span className="tabular-nums">{fmtDY(w.start)}</span>
                  {weekTags(w).length > 0 && <> · <span>{weekTags(w).join(" · ")}</span></>}{on && <> · <span>tento týden</span></>}</span>
              </span>
              <span className="whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${pc}1f`, color: pc }}>{pl}</span>
            </li>
          )
        })}
      </ul>
      {plan.length > 6 && <button type="button" className="mt-1 text-[12px] font-semibold text-accent" onClick={() => setAll((v) => !v)}>{all ? "Ukázat méně" : `Celý plán (${plan.length} týdnů)`}</button>}
    </div>
  )
}

// stage 3 — the risk path: only with an explicit consent, revocable, ended by the daily watch
function RiskPanel({ rid, goal, res, onChange }: { rid: string; goal: any; res: any; onChange: (d: any) => void }) {
  const toast = useToast()
  const { refresh } = useApp()
  const [ask, setAsk] = useState(false)
  const [ok, setOk] = useState(false)
  const [busy, setBusy] = useState(false)
  const set = async (path: "safe" | "risk") => {
    setBusy(true)
    try { onChange(await api.goalPath(rid, { path, consent: path === "risk" ? ok : false })); setAsk(false); refresh()
      toast({ title: path === "risk" ? "Riziková cesta zapnutá" : "Zpět na bezpečné cestě" }) }
    catch (e: any) { toast({ title: e?.message || "Změna se nepodařila" }) }
    finally { setBusy(false) }
  }
  const risk = res?.risk
  if (res?.path === "risk") {
    return (
      <div className="nest mt-4 p-3.5" style={{ borderColor: `${C.alert}55` }} data-testid="goal-risk-on">
        <p className="text-[13px] font-bold text-alert">Riziková cesta</p>
        <p className="mt-1 text-[12px] leading-5 text-fg-soft">{`Souhlas jste dali ${fmtD(goal.riskConsentAt)}.`} Týden smí růst rychleji a dlouhý běh o 15 %. Aplikace každý den hlídá bolest, nemoc a připravenost a při potížích plán sama vrátí na bezpečnou cestu.</p>
        <Button size="sm" variant="outline" className="mt-2" disabled={busy} onClick={() => set("safe")} data-testid="goal-risk-off">Vrátit na bezpečnou cestu</Button>
      </div>
    )
  }
  return (
    <div className="mt-4">
      {goal.riskEndedAt && <p className="mb-2 text-[12px] leading-5 text-fg-3">{`Riziková cesta skončila ${fmtD(goal.riskEndedAt)}${goal.riskEndReason ? ` (${goal.riskEndReason})` : ""}.`} Plán běží bezpečnou cestou.</p>}
      {res?.riskPossible && res?.verdict !== "ok" && (!ask ? (
        <Button size="sm" variant="outline" onClick={() => setAsk(true)} data-testid="goal-risk-ask">Zvolit rizikovou cestu</Button>
      ) : (
        <div className="nest p-3.5" style={{ borderColor: `${C.alert}55` }} data-testid="goal-risk-consent">
          <p className="flex items-center gap-1.5 text-[13px] font-bold text-alert">Riziková cesta: co to znamená <Sources ids={["damsted-et-al-2019", "nielsen-et-al-2014", "toresdahl-et-al-2022"]} info={res.sourceInfo} /></p>
          <ul className="mt-2 grid gap-1.5 text-[12px] leading-5 text-fg-soft">
            <li>{`Připraveni budete za ${risk?.readyWeek} týdnů místo ${res.safe?.readyWeek ?? "více než 104"}.`}</li>
            <li>Týdenní objem smí růst až o 20 % a týdenní strop má rezervu 25 % místo 15 %. Při nárůstu týdne o 20–60 % se během 3 týdnů zranilo o 23 procentních bodů víc běžců.</li>
            <li>Dlouhý běh smí být o 15 % delší než nejdelší za 30 dní (místo 10 %). Už nárůst o 10–30 % zvyšoval riziko zranění zhruba 1,6×.</li>
            <li>Nikdy: týden nad 1,5× průměru 4 týdnů, běh přes bolest, trénink při nemoci, dva vynechané odlehčovací týdny.</li>
            <li>Bolest od 3/10, nemoc nebo připravenost pod 65 % dva dny po sobě vrátí plán na bezpečnou cestu.</li>
          </ul>
          <label className="mt-3 flex items-start gap-2 text-[12px] text-fg"><input type="checkbox" className="mt-0.5" checked={ok} onChange={(e) => setOk(e.target.checked)} data-testid="goal-risk-check" />
            Rozumím vyššímu riziku zranění a souhlasím s rizikovou cestou. Souhlas můžu kdykoli vzít zpět.</label>
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={!ok || busy} onClick={() => set("risk")} data-testid="goal-risk-confirm">Souhlasím</Button>
            <Button size="sm" variant="outline" onClick={() => setAsk(false)}>Zpět</Button>
          </div>
        </div>
      ))}
    </div>
  )
}

// the goal's detail in four tabs (owner request 2026-10-13: intuitive and easy to navigate):
// where I stand, the plan, what the goal needs, and the settings
type DetailTab = "overview" | "plan" | "needs" | "settings"
const DETAIL_TABS: [DetailTab, string][] = [["overview", "Přehled"], ["plan", "Plán"], ["needs", "Co je potřeba"], ["settings", "Nastavení"]]
const TAB_HINT: Record<DetailTab, string> = {
  overview: "", plan: "týden po týdnu, fáze, odlehčení a ladění", needs: "objem, dlouhý běh, převýšení a cílový čas",
  settings: "můj týden, energie a kosti, riziková cesta",
}

function WeekNow({ w, weeks, budgetKm }: { w: any; weeks?: number; budgetKm?: number | null }) {
  if (!w) return null
  const [pl, pc] = PHASE[w.phase] || PHASE.base
  const tags = weekTags(w).filter((t) => !t.startsWith("posilování"))
  return (
    <div className="nest px-3 py-2.5" data-testid="goal-week">
      <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: pc }}>{`${pl} · ${w.i}. týden z ${weeks}`}</p>
      <p className="mt-0.5 text-[14px] text-fg">{w.race ? "Týden závodu" : <>Tento týden <b>{num(budgetKm ?? w.km, 0)} km</b></>}{w.long ? <>, dlouhý běh <b>{num(w.long, 0)} km</b></> : null}</p>
      <p className="mt-0.5 flex flex-wrap gap-x-3 text-[11.5px] text-fg-3">
        {w.strength != null && !w.race && <span>{`posilování ${w.strength}×`}</span>}
        {tags.map((t) => <span key={t}>{t}</span>)}
      </p>
    </div>
  )
}

function GoalDetail({ rid, data, gg, onClose, onEdit, onCancel, onChange, busy, initialTab = "overview" }: { rid: string; data: any; gg?: any; onClose: () => void; onEdit: () => void; onCancel: () => void; onChange: (d: any) => void; busy: boolean; initialTab?: DetailTab }) {
  const { goal, result: res } = data
  const [tab, setTab] = useState<DetailTab>(initialTab)
  const bar = useRef<HTMLDivElement | null>(null)
  const footer = (
    <div className="flex items-center justify-between gap-2">
      <Button size="sm" variant="outline" disabled={busy} onClick={onCancel} data-testid="goal-cancel">Zrušit cíl</Button>
      <Button size="sm" onClick={onEdit}>Změnit cíl</Button>
    </div>
  )
  const scol = SCOL[res?.status] || C.fg3
  const plan: any[] = res?.plan || []
  const today = res?.computedOn || res?.start
  const cur = plan.findIndex((w, i) => w.start <= today && today < (plan[i + 1]?.start ?? "9999"))
  const wk = gg?.week || plan[Math.max(0, cur)]
  const tr = data.track || {}
  const dot: Partial<Record<DetailTab, boolean>> = {
    overview: !!(tr.checkpoint || tr.setback || tr.gi || res?.hold),
    settings: !!data.energy?.ask,
  }
  const pick = (t: DetailTab) => {
    setTab(t)
    const el = bar.current, sc = el?.closest(".overflow-y-auto") as HTMLElement | null
    if (el && sc && sc.scrollTop > el.offsetTop) sc.scrollTo({ top: el.offsetTop })
  }
  return (
    <Sheet open onClose={onClose} footer={footer}>
      <div data-testid="goal-detail" className="min-h-[72dvh] md:min-h-[66dvh]">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-[12px] bg-white/[.06]"><Target className="size-5 text-accent" aria-hidden /></span>
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-[24px] leading-tight text-fg">{goalTitle(goal)}</h2>
            <p className="text-[12px] text-fg-3">{`${fmtDY(goal.date)} · za ${weeksCz(res?.weeksToGoal)}`}{goal.km ? ` · ${num(goal.km)} km` : ""}{goal.ascentM ? ` · ↑ ${num(goal.ascentM, 0)} m` : ""}{goal.kind === "race" ? <> · <span>{goal.aim === "time" ? "cílový čas" : "doběhnout"}</span></> : ""}</p>
          </div>
          {res?.statusLabel && <span className="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${scol}1f`, color: scol }} data-testid="goal-status">{res.statusLabel}</span>}
        </div>
        <div ref={bar} className="sticky top-0 z-10 -mx-5 mt-3 bg-raised/95 px-5 py-2 backdrop-blur md:-mx-6 md:px-6" data-testid="goal-tabs">
          <div role="tablist" aria-label="Části cíle" className="flex gap-1 overflow-x-auto rounded-full bg-white/[.06] p-[3px]">
            {DETAIL_TABS.map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => pick(k)} data-testid={`goal-tab-${k}`}
                className={`relative flex-1 whitespace-nowrap rounded-full px-3 py-1.5 text-[12.5px] font-bold transition ${tab === k ? "bg-fg text-ink" : "text-fg-2 hover:text-fg"}`}>
                {l}
                {dot[k] && tab !== k && <i className="ml-1 inline-block size-1.5 -translate-y-1.5 rounded-full bg-accent align-middle" aria-hidden />}
              </button>
            ))}
          </div>
        </div>
        {tab === "overview" && (
          <div role="tabpanel">
            {res?.path === "risk" && <p className="mt-2"><span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${C.alert}1f`, color: C.alert }}>riziková cesta</span></p>}
            <TrackBanners rid={rid} track={data.track} res={res} onData={onChange} onEdit={onEdit} />
            <div className="mt-3"><VerdictHero res={res} /></div>
            {wk && <div className="mt-4"><WeekNow w={wk} weeks={gg?.weeks || plan.length} budgetKm={gg?.budgetKm} /></div>}
            {tr.adherence && <div className="mt-5"><Adherence ad={tr.adherence} /></div>}
            <div className="mt-5 grid gap-1.5">
              {DETAIL_TABS.slice(1).map(([k, l]) => (
                <button key={k} type="button" onClick={() => pick(k)} className="flex items-center justify-between gap-3 rounded-xl bg-white/[.05] px-3.5 py-2.5 text-left hover:bg-white/[.08]">
                  <span className="min-w-0">
                    <b className="block text-[13px] text-fg">{l}{dot[k] && <i className="ml-1.5 inline-block size-1.5 rounded-full bg-accent align-middle" aria-hidden />}</b>
                    <span className="block text-[11.5px] text-fg-3">{TAB_HINT[k]}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
                </button>
              ))}
            </div>
          </div>
        )}
        {tab === "plan" && (
          <div role="tabpanel" className="mt-2">
            {plan.length > 0 ? <PlanBars plan={plan} today={today} /> : <p className="mt-2 text-[13px] text-fg-2">Plán po týdnech se ukáže, až bude cíl do 2 let.</p>}
            {res?.safe && <details className="mt-5" data-testid="goal-growth">
              <summary className="cursor-pointer t-label !text-fg-3">Jak poroste (graf)</summary>
              <ProjectionChart res={res} />
            </details>}
            <p className="mt-4 text-[11px] leading-5 text-fg-3">Plán se přepočítá každý týden z toho, co jste opravdu odběhli. Denní doporučení dál hlídá připravenost, bolest a limity.</p>
          </div>
        )}
        {tab === "needs" && (
          <div role="tabpanel" className="mt-2">
            <Gauges res={res} />
            <TargetTime tt={res?.targetTime} te={res?.trainEstimate} />
            <Notes res={res} />
          </div>
        )}
        {tab === "settings" && (
          <div role="tabpanel" className="mt-1">
            <MyWeek rid={rid} onSaved={() => api.goal(rid).then(onChange).catch(() => {})} />
            <EnergyRow rid={rid} en={data.energy} onData={onChange} />
            {gg?.coachCheck && <p className="nest mt-4 p-3.5 text-[12px] leading-5 text-fg-soft" data-testid="goal-coach-check">{gg.coachCheck.text}</p>}
            <RiskPanel rid={rid} goal={goal} res={res} onChange={onChange} />
            <p className="mt-4 text-[11px] leading-5 text-fg-3">Datum, trať nebo cílový čas změníte tlačítkem Změnit cíl dole.</p>
          </div>
        )}
      </div>
    </Sheet>
  )
}

// plan k cíli 2.0 #8 — the last weeks of the plan against what was run
function Adherence({ ad, compact = false }: { ad: any; compact?: boolean }) {
  if (!ad?.weeks?.length) return null
  const col = (p: number) => (p < 80 ? C.watch : p > 115 ? C.alert : C.ok)
  return (
    <div data-testid="goal-adherence">
      <div className="flex items-center justify-between gap-2">
        <p className="t-label !text-fg-3">Plnění plánu</p>
        {ad.strengthPct != null && <span className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] text-fg-2">{`posilování ${ad.strengthPct} %`}</span>}
      </div>
      <div className="mt-1.5 grid gap-1">
        {ad.weeks.map((w: any) => (
          <div key={w.start} className="grid grid-cols-[64px_1fr_44px] items-center gap-2 text-[11px]">
            <span className="tabular-nums text-fg-3">{fmtD(w.start)}</span>
            <span className="relative h-2 rounded-full bg-white/[.07]">
              <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, w.pct / 1.3)}%`, background: col(w.pct) }} />
              <i className="absolute -inset-y-0.5 w-[2px] rounded" style={{ left: `${100 / 1.3}%`, background: C.fg }} />
            </span>
            <b className="text-right tabular-nums" style={{ color: col(w.pct) }}>{`${w.pct} %`}</b>
          </div>
        ))}
      </div>
      {!compact && <p className="mt-1 text-[10.5px] text-fg-3">Svislá čárka = plán týdne. Kilometry proti plánu, jak stál v pondělí.</p>}
      {ad.text && <p className="mt-1.5 text-[12px] font-semibold" style={{ color: ad.flag === "over" ? C.alert : C.watch }}>{ad.text}</p>}
      {!compact && ad.strengthPct != null && ad.strengthPct < 50 && <p className="mt-1.5 text-[12px] text-fg-2" data-testid="goal-strength-low">Posilování chrání před zraněním, jen když se opravdu dělá. Bez něj plán ochranu neslibuje.</p>}
    </div>
  )
}

// plan k cíli 2.0 #17 — the energy & bone screen: opt-in, it says why it asks
function YesNo({ v, on, id }: { v: boolean | null; on: (b: boolean) => void; id: string }) {
  return (
    <span className="flex shrink-0 gap-1">
      {([[true, "Ano"], [false, "Ne"]] as [boolean, string][]).map(([b, t]) => (
        <button key={t} type="button" aria-pressed={v === b} onClick={() => on(b)} data-testid={`${id}-${b ? "yes" : "no"}`}
          className={`rounded-full px-3 py-1 text-[12px] font-semibold ${v === b ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2"}`}>{t}</button>
      ))}
    </span>
  )
}

function EnergyScreen({ rid, en, onData, onDone }: { rid: string; en: any; onData: (d: any) => void; onDone?: () => void }) {
  const [busy, setBusy] = useState(false)
  const was = en?.answered
  const [a, setA] = useState<Record<string, boolean | null>>({
    bsi: was ? !!en.bsi : null, period: was ? !!(en.hold && !en.hold.auto) : null, fuel: was ? !!en.fuel : null })
  const qs: [string, string][] = [
    ["bsi", "Měl/a jste někdy únavovou zlomeninu nebo stresovou reakci kosti?"],
    ...(en?.askPeriod ? [["period", "Chybí vám menstruace 3 měsíce nebo déle (mimo těhotenství a kojení)?"] as [string, string]] : []),
    ["fuel", "Hubnete bez záměru, jíte méně, než trénink potřebuje, nebo jste často unavený/á či nemocný/á?"],
  ]
  const ready = qs.every(([k]) => a[k] != null)
  const send = async (body: any) => {
    setBusy(true)
    try { onData(await api.goalEnergy(rid, body)); onDone?.() } finally { setBusy(false) }
  }
  return (
    <div className="nest mt-3 p-3.5" data-testid="goal-energy">
      <p className="text-[11px] font-bold uppercase tracking-wide text-accent">Energie a kosti · nepovinné</p>
      <p className="mt-1 text-[12px] leading-5 text-fg-2">Dlouhá příprava zatěžuje kosti. Málo energie z jídla a dřívější únavová zlomenina zvyšují riziko další, proto se ptáme. Podle odpovědí plán nastaví větší rezervy.</p>
      <div className="mt-2.5 grid gap-2.5">
        {qs.map(([k, q]) => (
          <div key={k} className="flex items-center justify-between gap-3">
            <span className="text-[13px] leading-5 text-fg">{q}</span>
            <YesNo v={a[k]} on={(b) => setA((x) => ({ ...x, [k]: b }))} id={`energy-${k}`} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={!ready || busy} onClick={() => send({ bsi: !!a.bsi, period: !!a.period, fuel: !!a.fuel })} data-testid="energy-save">Uložit</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => send({ declined: true })} data-testid="energy-decline">Nechci odpovídat</Button>
      </div>
    </div>
  )
}

// on the card: one line instead of the whole screen; the questions open in the detail's settings
function EnergyPrompt({ rid, onOpen, onData }: { rid: string; onOpen: () => void; onData: (d: any) => void }) {
  const [busy, setBusy] = useState(false)
  const decline = async () => { setBusy(true); try { onData(await api.goalEnergy(rid, { declined: true })) } finally { setBusy(false) } }
  return (
    <div className="nest mt-3 flex flex-wrap items-center justify-between gap-2 px-3 py-2.5" data-testid="goal-energy-prompt">
      <span className="min-w-0 text-[12.5px] leading-5 text-fg-2"><b className="text-fg">Energie a kosti</b> · 2–3 nepovinné otázky, aby plán nastavil správné rezervy</span>
      <span className="flex gap-1.5">
        <Button size="sm" onClick={onOpen} data-testid="energy-open">Vyplnit</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={decline}>Ne, díky</Button>
      </span>
    </div>
  )
}

function EnergyRow({ rid, en, onData }: { rid: string; en: any; onData: (d: any) => void }) {
  const [edit, setEdit] = useState(false)
  if (!en || (!en.answered && !en.declined && !en.ask)) return null
  if (edit || en.ask) return <EnergyScreen rid={rid} en={en} onData={onData} onDone={() => setEdit(false)} />
  const parts = en.declined ? ["bez odpovědí"] : [
    ...(en.bsi ? ["dřívější únavová zlomenina: větší rezervy"] : []),
    ...(en.hold ? ["plán neroste"] : []),
    ...(en.fuel ? ["známky nedostatku energie"] : []),
  ]
  return (
    <div className="nest mt-3 flex items-start justify-between gap-3 px-3.5 py-3" data-testid="goal-energy-row">
      <span className="min-w-0">
        <b className="block text-[13px] text-fg">Energie a kosti</b>
        <span className="mt-0.5 block text-[12px] leading-5 text-fg-2">{parts.length ? parts.join(" · ") : "bez rizika"}</span>
      </span>
      <Button size="sm" variant="outline" onClick={() => setEdit(true)}>Upravit</Button>
    </div>
  )
}

// plan k cíli 2.0 #10 — the runner's week: the days, the time, the holidays
const WDS_CS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"], WDS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
function MyWeek({ rid, onSaved }: { rid: string; onSaved: () => void }) {
  const toast = useToast()
  const { refresh } = useApp()
  const WDS = useLang() === "en" ? WDS_EN : WDS_CS
  const [p, setP] = useState<any>(null)
  const [edit, setEdit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [f, setF] = useState({ days: [] as number[], longDay: null as number | null, dayMin: "", longMin: "", vac: [] as { from: string; to: string }[] })
  useEffect(() => {
    let alive = true
    api.goalPrefs(rid).then((d: any) => alive && setP(d.prefs || {})).catch(() => alive && setP({}))
    return () => { alive = false }
  }, [rid])
  if (!p) return null
  const open = () => {
    setF({ days: p.days || [], longDay: p.longDay ?? null, dayMin: p.dayMin ? String(p.dayMin) : "", longMin: p.longMin ? String(p.longMin) : "", vac: p.vacations || [] })
    setEdit(true)
  }
  const toggle = (d: number) => setF((x) => ({ ...x, days: x.days.includes(d) ? x.days.filter((k) => k !== d) : [...x.days, d].sort() }))
  const save = async () => {
    if (f.days.length === 1) { toast({ title: "Vyberte aspoň 2 dny v týdnu" }); return }
    setBusy(true)
    try {
      const d: any = await api.setGoalPrefs(rid, { days: f.days, long_day: f.longDay, day_min: nIn(f.dayMin), long_min: nIn(f.longMin),
        vacations: f.vac.filter((v) => v.from && v.to) })
      setP(d.prefs); setEdit(false); onSaved(); refresh()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se uložit" }) }
    finally { setBusy(false) }
  }
  const parts = [
    ...(p.days?.length ? [p.days.map((d: number) => WDS[d]).join(" ")] : []),
    ...(p.longDay != null ? [`dlouhý ${WDS[p.longDay]}`] : []),
    ...(p.dayMin ? [`všední den ${p.dayMin} min`] : []), ...(p.longMin ? [`dlouhý ${p.longMin} min`] : []),
    ...(p.vacations?.length ? [`dovolená ${p.vacations.length}×`] : []),
  ]
  if (!edit) return (
    <div className="nest mt-3 flex items-start justify-between gap-3 px-3.5 py-3" data-testid="goal-week-prefs">
      <span className="min-w-0">
        <b className="block text-[13px] text-fg">Můj týden</b>
        <span className="mt-0.5 block text-[12px] leading-5 text-fg-2">{parts.length ? parts.join(" · ") : "Podle toho, jak běháte. Nastavte dny, čas a dovolenou."}</span>
      </span>
      <Button size="sm" variant="outline" onClick={open} data-testid="prefs-edit">Upravit</Button>
    </div>
  )
  return (
    <div className="nest mt-3 p-3.5" data-testid="goal-prefs">
      <p className="text-[11px] font-bold uppercase tracking-wide text-accent">Můj týden</p>
      <p className="mt-1 text-[12px] leading-5 text-fg-2">Plán se přizpůsobí: běhy jen v dny, kdy můžete, délka podle času, dovolená jako lehčí týden.</p>
      <p className={`${lbl} mt-2.5`}>Kdy můžete běhat</p>
      <div className="mt-1 flex flex-wrap gap-1.5">{WDS.map((w, d) => (
        <button key={w} type="button" aria-pressed={f.days.includes(d)} onClick={() => toggle(d)} data-testid={`prefs-day-${d}`}
          className={`min-w-9 rounded-full px-2.5 py-1 text-[12px] font-semibold ${f.days.includes(d) ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2"}`}>{w}</button>))}</div>
      <p className={`${lbl} mt-2.5`}>Dlouhý běh</p>
      <div className="mt-1 flex flex-wrap gap-1.5">{WDS.map((w, d) => (f.days.length === 0 || f.days.includes(d)) && (
        <button key={w} type="button" aria-pressed={f.longDay === d} onClick={() => setF((x) => ({ ...x, longDay: x.longDay === d ? null : d }))}
          className={`min-w-9 rounded-full px-2.5 py-1 text-[12px] font-semibold ${f.longDay === d ? "bg-accent text-ink" : "bg-white/[.06] text-fg-2"}`}>{w}</button>))}</div>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <label className={lbl}>Všední den, min<input className={inp} inputMode="numeric" value={f.dayMin} placeholder="např. 60" onChange={(e) => setF((x) => ({ ...x, dayMin: e.target.value }))} data-testid="prefs-daymin" /></label>
        <label className={lbl}>Dlouhý běh, min<input className={inp} inputMode="numeric" value={f.longMin} placeholder="např. 150" onChange={(e) => setF((x) => ({ ...x, longMin: e.target.value }))} data-testid="prefs-longmin" /></label>
      </div>
      <p className={`${lbl} mt-2.5`}>Dovolená (lehčí týden)</p>
      <div className="mt-1 grid gap-1.5">
        {f.vac.map((v, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-center gap-1.5">
            <input type="date" className={inp + " !mt-0"} value={v.from} onChange={(e) => setF((x) => ({ ...x, vac: x.vac.map((y, k) => (k === i ? { ...y, from: e.target.value } : y)) }))} />
            <input type="date" className={inp + " !mt-0"} value={v.to} onChange={(e) => setF((x) => ({ ...x, vac: x.vac.map((y, k) => (k === i ? { ...y, to: e.target.value } : y)) }))} />
            <button type="button" className="px-2 text-[13px] text-fg-3" aria-label="Odebrat" onClick={() => setF((x) => ({ ...x, vac: x.vac.filter((_, k) => k !== i) }))}>✕</button>
          </div>
        ))}
        <button type="button" className="justify-self-start text-[12px] font-semibold text-accent" onClick={() => setF((x) => ({ ...x, vac: [...x.vac, { from: "", to: "" }] }))}>+ Přidat dovolenou</button>
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={busy} onClick={save} data-testid="prefs-save">Uložit</Button>
        <Button size="sm" variant="outline" onClick={() => setEdit(false)}>Zpět</Button>
      </div>
    </div>
  )
}

// plan k cíli 2.0 #19 — how the goal went, after its date
export function OutcomeCard({ rid, oc, onData }: { rid: string; oc: any; onData: (d: any) => void }) {
  const [busy, setBusy] = useState(false)
  const [started, setStarted] = useState<boolean | null>(null)
  const [fin, setFin] = useState<boolean | null>(null)
  const [t, setT] = useState("")
  if (!oc) return null
  const free = oc.kind === "free"
  const timeS = timeIn(t)
  const ready = free ? fin != null : started === false || (started === true && fin === false) || (started === true && fin === true && (!!timeS || !t.trim()))
  const send = async (body: any) => {
    setBusy(true)
    try { onData(await api.goalOutcome(rid, { goal_id: oc.goalId, ...body })) } finally { setBusy(false) }
  }
  const save = () => send(free ? { started: true, finished: fin } : { started, finished: started ? fin : false, time_s: started && fin ? timeS : null })
  return (
    <div className="nest mt-2.5 p-3.5" data-testid="goal-outcome">
      <p className="text-[11px] font-bold uppercase tracking-wide text-accent">{`Jak to dopadlo · ${fmtDY(oc.date)}`}</p>
      <p className="mt-0.5 text-[14px] font-semibold text-fg">{oc.name}</p>
      <div className="mt-2.5 grid gap-2.5">
        {!free && <div className="flex items-center justify-between gap-3"><span className="text-[13px] text-fg">Stál/a jste na startu?</span><YesNo v={started} on={setStarted} id="outcome-started" /></div>}
        {(free || started) && <div className="flex items-center justify-between gap-3"><span className="text-[13px] text-fg">{free ? "Splnil/a jste cíl?" : "Doběhl/a jste?"}</span><YesNo v={fin} on={setFin} id="outcome-finished" /></div>}
        {!free && started && fin && (
          <label className={lbl}>{`Čas (h:mm:ss)${oc.targetTimeS ? ` · cíl ${timeStr(oc.targetTimeS)}` : ""}`}
            <input className={inp} inputMode="numeric" placeholder="3:45:00" value={t} onChange={(e) => setT(e.target.value)} data-testid="outcome-time" />
          </label>
        )}
      </div>
      <p className="mt-2 text-[11px] leading-5 text-fg-3">Výsledky ukazují, jak přesně plán odhaduje. Plnění plánu a případné zranění v přípravě se doplní samy.</p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="sm" disabled={!ready || busy} onClick={save} data-testid="outcome-save">Uložit</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => send({ skipped: true })} data-testid="outcome-skip">Nechci uvádět</Button>
      </div>
    </div>
  )
}

// plan k cíli 2.0 #7, #9 — a checkpoint due and what a setback cost
function TrackBanners({ rid, track, res, onData, onEdit }: { rid: string; track: any; res: any; onData: (d: any) => void; onEdit?: () => void }) {
  const [busy, setBusy] = useState(false)
  const cp = track?.checkpoint, sb = track?.setback, hold = res?.hold, gi = track?.gi
  if (!cp && !sb && !hold && !gi) return null
  const ack = async () => { setBusy(true); try { onData(await api.goalCheckpoint(rid, cp.key)) } finally { setBusy(false) } }
  const giAns = async (ok: boolean) => { setBusy(true); try { onData(await api.goalGi(rid, gi.date, ok)) } finally { setBusy(false) } }
  return (
    <div className="mt-3 grid gap-2">
      {hold && (
        <div className="nest p-3" style={{ borderColor: `${C.alert}55` }} data-testid="goal-hold">
          <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: C.alert }}>Plán teď neroste</p>
          <p className="mt-0.5 text-[13px] text-fg">{hold.kind === "sleep" ? `Důvod: ${hold.why}. Týden neroste, ale ani neklesá, dokud průměr nepřesáhne 7 h.` : `Důvod: ${hold.why}. Týdny drží vaši současnou úroveň.`}</p>
          {hold.kind === "energy" && <p className="mt-0.5 text-[12px] text-fg-2">Objednejte se ke sportovnímu lékaři. Chybějící menstruace bývá známkou nedostatku energie a zvyšuje riziko únavové zlomeniny.</p>}
        </div>
      )}
      {cp && (
        <div className="nest p-3" style={{ borderColor: `${cp.behind ? C.watch : C.ok}55` }} data-testid="goal-checkpoint">
          <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: cp.behind ? C.watch : C.ok }}>{`Kontrolní bod · ${cp.label}`}</p>
          <p className="mt-0.5 text-[13px] text-fg">{cp.behind ? "Zaostáváte za plánem. Zmeškané se nedohání: buď cíl upravit, nebo počítat s pozdějším termínem." : "Jste na cestě. Plán pokračuje beze změny."}</p>
          {cp.behind && res?.alternatives?.find((x: any) => x.kind === "best") && <p className="mt-1 text-[12px] text-fg-2">{`Nejlepší bezpečný cíl: ${res.alternatives.find((x: any) => x.kind === "best").label}`}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            {cp.behind && onEdit && <Button size="sm" onClick={onEdit}>Upravit cíl</Button>}
            <Button size="sm" variant="outline" disabled={busy} onClick={ack} data-testid="goal-checkpoint-ok">{cp.behind ? "Ponechat cíl" : "Rozumím"}</Button>
          </div>
        </div>
      )}
      {gi && (
        <div className="nest flex flex-wrap items-center justify-between gap-2 p-3" data-testid="goal-gi">
          <span className="text-[13px] text-fg">{`Dlouhý běh ${fmtD(gi.date)} (${num(gi.km, 0)} km): trávení v pořádku?`}</span>
          <span className="flex gap-1.5">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => giAns(true)} data-testid="gi-ok">Ano</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => giAns(false)} data-testid="gi-bad">Ne, potíže</Button>
          </span>
        </div>
      )}
      {sb && <p className="rounded-xl bg-watch/[.08] px-3 py-2 text-[12px] text-fg" data-testid="goal-setback">{`Výpadek posunul reálný termín o ${sb.days} dní: ${fmtDY(sb.from)} → ${fmtDY(sb.to)}.`}</p>}
    </div>
  )
}

// plan k cíli 2.0 #4 — days without any data from the watch: rest, or a run logged by hand
export function DataGapCard({ rid }: { rid: string }) {
  const toast = useToast()
  const { refresh } = useApp()
  const [gap, setGap] = useState<any>(null)
  const [form, setForm] = useState(false)
  const [run, setRun] = useState({ date: "", km: "", min: "", rpe: "4" })
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let alive = true
    api.gaps(rid).then((d: any) => alive && setGap(d.gap)).catch(() => {})
    return () => { alive = false }
  }, [rid])
  if (!gap) return null
  const rest = async () => {
    setBusy(true)
    try { const d: any = await api.answerGap(rid, { from: gap.from, to: gap.to, answer: "rest" }); setGap(d.gap) } finally { setBusy(false) }
  }
  const save = async () => {
    const km = nIn(run.km), min = nIn(run.min)
    if (!run.date || !km || !min) { toast({ title: "Vyplňte den, kilometry a minuty" }); return }
    setBusy(true)
    try {
      await api.addManualActivity(rid, { sport: "running", date: run.date, distance_km: km, duration_min: min, rpe: Number(run.rpe) || 4 })
      const d: any = await api.gaps(rid); setGap(d.gap); setForm(false); setRun({ date: "", km: "", min: "", rpe: "4" }); refresh()
      toast({ title: "Běh zapsán" })
    } catch (e: any) { toast({ title: e?.message || "Běh se nepodařilo zapsat" }) }
    finally { setBusy(false) }
  }
  const days = Array.from({ length: gap.days }, (_, i) => addDays(gap.from, i))
  return (
    <Card className="mt-4" data-testid="data-gap">
      <p className="text-[13px] font-semibold text-fg">{`${fmtDY(gap.from)} – ${fmtDY(gap.to)}: z hodinek nic`}</p>
      <p className="mt-0.5 text-[12px] leading-5 text-fg-3">Běhal/a jste bez hodinek? Jinak to aplikace počítá jako volno a kapacita i plán vyjdou nižší.</p>
      {!form ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={rest} data-testid="gap-rest">Neběhal/a jsem</Button>
          <Button size="sm" disabled={busy} onClick={() => { setRun((r) => ({ ...r, date: days[days.length - 1] })); setForm(true) }} data-testid="gap-log">Zapsat běh</Button>
        </div>
      ) : (
        <div className="mt-2.5 grid gap-2">
          <div className="flex flex-wrap gap-1.5">{days.map((d) => (
            <button key={d} type="button" onClick={() => setRun((r) => ({ ...r, date: d }))} aria-pressed={run.date === d}
              className={`rounded-full px-2.5 py-1 text-[12px] font-semibold ${run.date === d ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2"}`}>{fmtD(d)}</button>))}</div>
          <div className="grid grid-cols-3 gap-2">
            <label className={lbl}>km<input className={inp} inputMode="decimal" value={run.km} onChange={(e) => setRun((r) => ({ ...r, km: e.target.value }))} data-testid="gap-km" /></label>
            <label className={lbl}>minut<input className={inp} inputMode="numeric" value={run.min} onChange={(e) => setRun((r) => ({ ...r, min: e.target.value }))} data-testid="gap-min" /></label>
            <label className={lbl}>náročnost 0–10<input className={inp} inputMode="numeric" value={run.rpe} onChange={(e) => setRun((r) => ({ ...r, rpe: e.target.value }))} /></label>
          </div>
          <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={save} data-testid="gap-save">Uložit běh</Button><Button size="sm" variant="outline" onClick={() => setForm(false)}>Zpět</Button></div>
        </div>
      )}
    </Card>
  )
}

export function GoalCard({ rid, gg }: { rid: string; gg?: any }) {
  const toast = useToast()
  const { refresh } = useApp()
  const [data, setData] = useState<any>(null)
  const [mode, setMode] = useState<"" | "setup" | "detail">("")
  const [tab0, setTab0] = useState<DetailTab>("overview")
  const openDetail = (t: DetailTab) => { setTab0(t); setMode("detail") }
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (mode) track(mode === "setup" ? "goal-setup" : "goal") }, [mode])
  useEffect(() => {
    let alive = true
    api.goal(rid).then((d: any) => alive && setData(d)).catch(() => alive && setData({ goal: null, races: [] }))
    return () => { alive = false }
  }, [rid])
  if (!data) return null
  const { goal, result: res } = data
  const cancel = async () => {
    setBusy(true)
    try { setData(await api.cancelGoal(rid)); setMode(""); refresh(); toast({ title: "Cíl zrušen" }) } finally { setBusy(false) }
  }
  const reqs = (res?.requirements || []).filter((r: any) => r.unit !== "×").slice(0, 2)
  const cnt = (res?.requirements || []).find((r: any) => r.key === "longCount")
  const wk = gg?.week || (res?.plan || [])[0]
  const chip = res?.statusLabel ? { verdict: res.status, verdictLabel: res.statusLabel } : res
  return (
    <Card className="mt-4" data-testid="goal-card">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Cíl</Label>
          <InfoDot label="Trénink k cíli" text="Zvolte závod nebo vlastní cíl. Aplikace z vašich dat spočítá, jak rychle mohou kapacity bezpečně růst, řekne, jestli cíl stihnete zdravě, a sestaví k němu plán po týdnech. Týdenní cíl se pak řídí tímto plánem, denní doporučení dál hlídá připravenost, bolest a limity." /></span>
        {goal && <span className="flex items-center gap-1.5">{res?.path === "risk" && <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ background: `${C.alert}1f`, color: C.alert }}>riziková cesta</span>}<VerdictChip res={chip} /></span>}
      </div>
      <OutcomeCard rid={rid} oc={data.outcome} onData={setData} />
      {!goal ? (
        <>
          <p className="mt-2 text-sm text-fg-2">Chystáte se na závod nebo máte vlastní cíl v kilometrech? Aplikace spočítá, jestli ho stihnete zdravě, sestaví k němu plán, a když to nejde, řekne reálný termín.</p>
          <Button size="sm" className="mt-3" icon={Target} onClick={() => setMode("setup")} data-testid="goal-start">Nastavit cíl</Button>
        </>
      ) : (
        <button type="button" className="mt-2 block w-full text-left" onClick={() => openDetail("overview")} data-testid="goal-open">
          <b className="flex items-center gap-1.5 text-[15px] text-fg">{goalTitle(goal)}<ChevronRight className="size-4 text-fg-3" aria-hidden /></b>
          <span className="block text-[12px] text-fg-2"><span className="tabular-nums">{fmtDY(goal.date)}</span>{` · za ${weeksCz(res?.weeksToGoal)}`}{res?.realDate && res.verdict !== "ok" ? <> · reálně od <b className="text-fg">{fmtDY(res.realDate)}</b></> : null}</span>
          {res && <span className="mt-2 flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-bold" style={{ color: VCOL[res.verdict] || C.fg3 }}>{headline(res).title}</span>
            {res.chance != null && <span className="shrink-0 text-[12px] tabular-nums text-fg-2">{`šance ${res.chance >= 95 ? "> 95" : res.chance} %`}</span>}
          </span>}
          {wk && <span className="mt-2.5 block"><WeekNow w={wk} weeks={gg?.weeks || res?.plan?.length} budgetKm={gg?.budgetKm} /></span>}
          {wk?.milestone === "half" && <span className="mt-1 block text-[12px] text-accent">Mezicíl: běh na 21 km, nebo B‑závod na půlmaraton.</span>}
          {gg?.runs && <span className="mt-1 block text-[11px] text-fg-3">{`${gg.runs} běhy týdně (první maraton)`}</span>}
          {res?.verdict !== "unknown" && reqs.length > 0 && (
            <span className="mt-2.5 grid gap-2">
              {reqs.map((r: any) => {
                const pct = r.need ? Math.min(100, ((r.now ?? 0) / r.need) * 100) : 0
                return (
                  <span key={r.key} className="block">
                    <span className="flex items-baseline justify-between gap-2 text-[11px]"><span className="text-fg-2">{r.label}</span>
                      <span className="tabular-nums text-fg-3"><b className="text-fg">{num(r.now, 1)}</b> / {num(r.need, 1)} {r.unit}</span></span>
                    <span className="relative mt-1 block h-1.5 rounded-full bg-white/[.08]"><i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: pct >= 99.5 ? C.ok : C.info }} /></span>
                  </span>
                )
              })}
              {cnt && <span className="text-[11px] text-fg-3">a {num(cnt.need, 0)}× dlouhý běh aspoň {num(cnt.km, 0)} km</span>}
            </span>
          )}
          {gg?.coachCheck && !gg.coachCheck.ok && <span className="mt-1 block text-[12px] text-watch">{gg.coachCheck.text}</span>}
          {gg?.riskEnded && <span className="mt-1 block text-[12px] text-watch">{`Riziková cesta skončila (${gg.riskEnded.reason}), plán pokračuje bezpečnou cestou.`}</span>}
          <span className="mt-3 flex items-center justify-end gap-1 text-[12px] font-bold text-accent">Plán, požadavky a nastavení<ChevronRight className="size-3.5" aria-hidden /></span>
        </button>
      )}
      {goal && <TrackBanners rid={rid} track={data.track} res={res} onData={setData} onEdit={() => setMode("setup")} />}
      {goal && data.track?.adherence && <div className="mt-3"><Adherence ad={data.track.adherence} compact /></div>}
      {goal && data.energy?.ask && <EnergyPrompt rid={rid} onOpen={() => openDetail("settings")} onData={setData} />}
      {mode === "setup" && <GoalSetup rid={rid} races={data.races || []} initial={formOf(goal)} onClose={() => setMode("")}
        onSaved={(d) => { setData(d); setMode("detail"); refresh() }} />}
      {mode === "detail" && goal && <GoalDetail rid={rid} data={data} gg={gg} busy={busy} initialTab={tab0} onClose={() => setMode("")} onEdit={() => setMode("setup")} onCancel={cancel} onChange={setData} />}
    </Card>
  )
}
