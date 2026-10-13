// Trénink k cíli, stage 1 (owner request and decisions 2026-10-12): the goal card on Trénink and
// the 3-step entry (goal and date → what it requires → the verdict). The answer comes from
// backend metrics/goal_plan.py: requirements from the studies, the week-by-week projection
// under the app's own limits, Reálné / Těsné / Nereálné, the real date and the alternatives.
// Advice only — the daily recommendation and the week's plan don't follow the goal yet.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, InfoDot, Label, Segmented, Sheet, useToast } from "@/ui"
import { fmtD } from "@/lib"
import { num } from "@/outlook"
import { C } from "@/tokens"
import { ChevronLeft, ChevronRight, Flag, Target } from "lucide-react"

const VCOL: Record<string, string> = { ok: C.ok, tight: C.watch, no: C.alert, unknown: C.fg3 }
const DIST: [string, string][] = [["5", "5 km"], ["10", "10 km"], ["21.1", "půlmaraton"], ["42.2", "maraton"]]
const inp = "mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg"
const lbl = "text-[12px] font-semibold text-fg-2"

type Form = {
  kind: "race" | "free"; raceId: number | null; name: string; date: string; km: string; ascent: string; descent: string
  terrain: "" | "road" | "trail"; aim: "finish" | "time"; target: string
  weekly: string; long: string; climb: string; scope: "week" | "run"
}
const EMPTY: Form = { kind: "race", raceId: null, name: "", date: "", km: "", ascent: "", descent: "", terrain: "", aim: "finish",
  target: "", weekly: "", long: "", climb: "", scope: "week" }

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
    target: timeStr(goal.targetTimeS), weekly: strNum(f.weeklyKm), long: strNum(f.longKm), climb: strNum(f.climbM), scope: f.climbScope || "week" }
}

function bodyOf(f: Form) {
  return {
    kind: f.kind, race_id: f.kind === "race" ? f.raceId : null, name: f.name.trim() || null, date: f.date,
    km: f.kind === "race" ? nIn(f.km) : null, ascent_m: f.kind === "race" ? nIn(f.ascent) : null,
    descent_m: f.kind === "race" ? nIn(f.descent) : null, terrain: f.terrain || null, aim: f.aim,
    target_time_s: f.aim === "time" ? timeIn(f.target) : null,
    free: f.kind === "free" ? { weekly_km: nIn(f.weekly), long_km: nIn(f.long), climb_m: nIn(f.climb), climb_scope: f.scope } : null,
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

// one requirement: where the runner is now against what the goal needs, and when the safe path gets there
function ReqRow({ r, res }: { r: any; res: any }) {
  const now = r.now ?? 0
  const pct = r.need ? Math.min(100, (now / r.need) * 100) : 0
  const when = res?.safe?.firstMet?.[r.key]
  const d = r.unit === "km" ? 1 : 0
  const isCount = r.unit === "×"
  return (
    <div className="py-2.5" data-testid="goal-req">
      <div className="flex items-baseline justify-between gap-2 text-[12px]">
        <span className="flex items-center gap-1.5 font-semibold text-fg">{r.label}{r.key === "longCount" && r.km ? ` ≥ ${num(r.km, 0)} km` : ""}
          <Sources ids={r.sources} info={res?.sourceInfo} />
          {r.assumption && <span className="rounded-full bg-white/[.06] px-1.5 py-0.5 text-[10px] font-bold text-fg-3">předpoklad</span>}
        </span>
        <span className="tabular-nums text-fg-3">{isCount ? <>{now ? <><b className="text-fg">{num(now, 0)}</b> / </> : null}<b className="text-fg">{num(r.need, 0)}×</b></> : <><b className="text-fg">{num(now, d)}</b> / {num(r.need, d)} {r.unit}</>}</span>
      </div>
      {!isCount && (
        <div className="relative mt-1 h-2 rounded-full bg-white/[.08]">
          <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: pct >= 99.5 ? C.ok : C.info }} />
        </div>
      )}
      <p className="mt-1 text-[11px] leading-4 text-fg-3">{r.why}{r.base != null ? ` (tabulka ${num(r.base, 0)} km)` : ""}
        {when ? ` · bezpečně za ${weeksCz(when)} (týden od ${fmtDY(addDays(res.start, 7 * (when - 1)))})` : res?.safe ? " · bezpečně do 2 let ne" : ""}</p>
    </div>
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
        <span className="text-fg-3">Na ose jsou týdny, u každé značky datum jejich pondělí. Čára ukazuje, kolik zvládnete, když poroste jen tak rychle, jak dovolí vaše limity v aplikaci. Čárkovaná vodorovná čára je požadavek cíle, svislá týden závodu, šedé pole ladění. Prstem po grafu uvidíte hodnoty týdne.</span>
        <span className="text-fg-3" data-testid="goal-chart-why">{why.map((t, i) => <span key={i}>{i ? " " : ""}{t}</span>)}</span>
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

function Verdict({ res, onApply }: { res: any; onApply?: (patch: Partial<Form>) => void }) {
  if (!res) return null
  const col = VCOL[res.verdict] || C.fg3
  return (
    <div data-testid="goal-result">
      <div className="nest p-3.5" style={{ borderColor: `${col}55` }}>
        <div className="flex items-center gap-2"><VerdictChip res={res} />
          {res.realDate && res.verdict !== "ok" && <span className="text-[12px] text-fg-2">reálně od <b className="text-fg">{fmtDY(res.realDate)}</b></span>}
        </div>
        <p className="mt-2 text-[13px] leading-5 text-fg-soft">{res.text}</p>
      </div>
      <ProjectionChart res={res} />
      {res.alternatives?.length > 0 && (
        <div className="mt-4">
          <p className="t-label !text-fg-3">Možnosti</p>
          <ul className="mt-1.5 space-y-2">
            {res.alternatives.map((x: any, i: number) => {
              const patch: Partial<Form> | null = x.kind === "later" ? { date: x.date } : x.kind === "finish" ? { aim: "finish" }
                : x.kind === "shorter" ? { km: strNum(x.goal.km), ascent: "", descent: "" } : x.kind === "best" ? bestPatch(x.goal) : null
              const best = x.kind === "best"
              return (
                <li key={i} className={`flex items-start gap-3 rounded-xl p-3 text-[12px] leading-5 text-fg-soft ${best ? "border border-accent/40 bg-accent/[.06]" : "bg-white/[.04]"}`}
                  data-testid={best ? "goal-alt-best" : "goal-alt"}>
                  <span className="min-w-0 flex-1">{best && <b className="mb-0.5 block text-[11px] uppercase tracking-wide text-accent">Nejlepší bezpečný cíl</b>}
                    {x.text}{x.sources ? <> <Sources ids={x.sources} info={res.sourceInfo} /></> : null}</span>
                  {patch && onApply && <Button size="sm" variant="outline" onClick={() => onApply(patch)}>Použít</Button>}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}

function Requirements({ res }: { res: any }) {
  if (!res) return null
  return (
    <div>
      <div className="divide-y divide-white/[.06]">{(res.requirements || []).map((r: any) => <ReqRow key={r.key} r={r} res={res} />)}</div>
      {res.notes?.length > 0 && (
        <ul className="mt-3 space-y-2">
          {res.notes.map((n: any) => (
            <li key={n.key} className="rounded-xl bg-white/[.04] p-3 text-[12px] leading-5 text-fg-soft" data-testid="goal-note">
              {n.text} {n.sources?.length ? <Sources ids={n.sources} info={res.sourceInfo} /> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const STEPS = ["Cíl a datum", "Co cíl vyžaduje", "Jde to stihnout?"]

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
      {step < 2 ? <Button size="sm" disabled={!valid || busy} busy={busy} onClick={next} data-testid="goal-next">Další<ChevronRight className="size-4" aria-hidden /></Button>
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
                <p className={`${lbl} flex items-center gap-1.5`}>Co je cílem<InfoDot label="Doběhnout nebo cílový čas" text="Pro cílový čas aplikace počítá s vyšším objemem a delšími dlouhými běhy (horní čísla tabulky). Tempa k cílovému času přijdou v další etapě." /></p>
                <Segmented className="mt-1" size="sm" ariaLabel="Co je cílem" options={[["finish", "Doběhnout"], ["time", "Cílový čas"]] as const} value={f.aim} onChange={(k) => set({ aim: k })} />
                {f.aim === "time" && <label className={`${lbl} mt-2 block max-w-[200px]`}>Cílový čas (h:mm)<input className={inp} placeholder="3:59" value={f.target} onChange={(e) => set({ target: e.target.value })} /></label>}
              </div>
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
          <div className="mt-4">
            <p className="text-[13px] leading-5 text-fg-soft">Tohle musíte do data cíle zvládnout. Čísla vycházejí ze studií rekreačních běžců (ⓘ u každého řádku), kde studie chybí, je to označený předpoklad.</p>
            <div className="mt-2"><Requirements res={res} /></div>
          </div>
        )}

        {step === 2 && res && (
          <div className="mt-4">
            <Verdict res={res} onApply={apply} />
            {res.targetTime && <p className="nest mt-4 p-3.5 text-[12px] leading-5 text-fg-soft" data-testid="goal-target-time">{res.targetTime.text}</p>}
            {blocked && <p className="mt-4 text-[12px] leading-5 text-alert" data-testid="goal-blocked">Tento cíl v termínu nestihne ani riziková cesta, proto ho aplikace neuloží. Použijte pozdější termín nebo menší cíl.</p>}
            {res?.plan?.length > 0 && !blocked && <><p className="mt-4 t-label !text-fg-3">Plán po týdnech</p><PlanList plan={res.plan} today={res.start} /></>}
            <p className="mt-4 text-[11px] leading-5 text-fg-3">Po uložení se týdenní cíl na Tréninku a v plánu týdne řídí tímto plánem. Rizikovou cestu můžete zvolit v detailu cíle, jen s výslovným souhlasem.</p>
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
                  {w.deload ? " · odlehčovací" : ""}{w.taper ? ` · ${num((w.factor ?? 0) * 100, 0)} % vrcholu` : ""}{w.milestone === "half" ? " · mezicíl 21 km" : ""}{on ? " · tento týden" : ""}</span>
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

function GoalDetail({ rid, data, gg, onClose, onEdit, onCancel, onChange, busy }: { rid: string; data: any; gg?: any; onClose: () => void; onEdit: () => void; onCancel: () => void; onChange: (d: any) => void; busy: boolean }) {
  const { goal, result: res } = data
  const footer = (
    <div className="flex items-center justify-between gap-2">
      <Button size="sm" variant="outline" disabled={busy} onClick={onCancel} data-testid="goal-cancel">Zrušit cíl</Button>
      <Button size="sm" onClick={onEdit}>Změnit cíl</Button>
    </div>
  )
  const scol = SCOL[res?.status] || C.fg3
  return (
    <Sheet open onClose={onClose} footer={footer}>
      <div data-testid="goal-detail">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-[12px] bg-white/[.06]"><Target className="size-5 text-accent" aria-hidden /></span>
          <div className="min-w-0">
            <h2 className="font-serif text-[24px] leading-tight text-fg">{goalTitle(goal)}</h2>
            <p className="text-[12px] text-fg-3">{`${fmtDY(goal.date)} · za ${weeksCz(res?.weeksToGoal)}`}{goal.km ? ` · ${num(goal.km)} km` : ""}{goal.ascentM ? ` · ↑ ${num(goal.ascentM, 0)} m` : ""}{goal.kind === "race" ? ` · ${goal.aim === "time" ? "cílový čas" : "doběhnout"}` : ""}</p>
          </div>
        </div>
        {res?.statusLabel && <p className="mt-3 flex items-center gap-2 text-[12px] text-fg-2">Stav plánu
          <span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${scol}1f`, color: scol }} data-testid="goal-status">{res.statusLabel}</span>
          {res.path === "risk" && <span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${C.alert}1f`, color: C.alert }}>riziková cesta</span>}</p>}
        <div className="mt-3"><Verdict res={res} /></div>
        {res?.targetTime && (
          <div className="nest mt-4 p-3.5" data-testid="goal-target-time">
            <p className="text-[12px] font-bold text-fg">{`Cílový čas ${res.targetTime.timeText} · tempo ${res.targetTime.paceText}`}</p>
            <p className="mt-1 text-[12px] leading-5 text-fg-soft">{res.targetTime.text}</p>
            {res.targetTime.basis && <p className="mt-1 text-[11px] text-fg-3">{`Odhad z běhu ${res.targetTime.basis.title || ""} (${fmtD(res.targetTime.basis.date)}, ${num(res.targetTime.basis.km)} km) Riegelovým vzorcem.`}</p>}
          </div>
        )}
        {gg?.coachCheck && <p className="nest mt-4 p-3.5 text-[12px] leading-5 text-fg-soft" data-testid="goal-coach-check">{gg.coachCheck.text}</p>}
        <RiskPanel rid={rid} goal={goal} res={res} onChange={onChange} />
        {res?.plan?.length > 0 && <>
          <p className="mt-5 t-label !text-fg-3">Plán po týdnech</p>
          <PlanList plan={res.plan} today={res.computedOn || res.start} />
        </>}
        <p className="mt-5 t-label !text-fg-3">Co cíl vyžaduje</p>
        <div className="mt-1"><Requirements res={res} /></div>
        <p className="mt-4 text-[11px] leading-5 text-fg-3">Týdenní cíl na Tréninku a v plánu týdne se řídí tímto plánem. Denní doporučení dál hlídá připravenost, bolest a bezpečnostní limity, takže konkrétní den může vyjít méně. Plán se přepočítá každý týden z toho, co jste opravdu odběhli.</p>
      </div>
    </Sheet>
  )
}

export function GoalCard({ rid, gg }: { rid: string; gg?: any }) {
  const toast = useToast()
  const { refresh } = useApp()
  const [data, setData] = useState<any>(null)
  const [mode, setMode] = useState<"" | "setup" | "detail">("")
  const [busy, setBusy] = useState(false)
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
      {!goal ? (
        <>
          <p className="mt-2 text-sm text-fg-2">Chystáte se na závod nebo máte vlastní cíl v kilometrech? Aplikace spočítá, jestli ho stihnete zdravě, sestaví k němu plán, a když to nejde, řekne reálný termín.</p>
          <Button size="sm" className="mt-3" icon={Target} onClick={() => setMode("setup")} data-testid="goal-start">Nastavit cíl</Button>
        </>
      ) : (
        <button type="button" className="mt-2 block w-full text-left" onClick={() => setMode("detail")} data-testid="goal-open">
          <b className="flex items-center gap-1.5 text-[15px] text-fg">{goalTitle(goal)}<ChevronRight className="size-4 text-fg-3" aria-hidden /></b>
          <span className="block text-[12px] text-fg-2"><span className="tabular-nums">{fmtDY(goal.date)}</span>{` · za ${weeksCz(res?.weeksToGoal)}`}{res?.realDate && res.verdict !== "ok" ? <> · reálně od <b className="text-fg">{fmtDY(res.realDate)}</b></> : null}</span>
          {wk && (
            <span className="nest mt-2.5 block px-3 py-2" data-testid="goal-week">
              <span className="block text-[11px] font-bold uppercase tracking-wide" style={{ color: (PHASE[wk.phase] || PHASE.base)[1] }}>{`${(PHASE[wk.phase] || PHASE.base)[0]} · ${wk.i}. týden z ${gg?.weeks || res?.plan?.length}`}</span>
              <span className="mt-0.5 block text-[13px] text-fg">{wk.race ? "Týden závodu" : <>Tento týden <b>{num(gg?.budgetKm ?? wk.km, 0)} km</b></>}{wk.long ? <>, dlouhý běh <b>{num(wk.long, 0)} km</b></> : null}{wk.deload ? " · odlehčovací" : ""}</span>
              {wk.milestone === "half" && <span className="mt-0.5 block text-[12px] text-accent">Mezicíl: běh na 21 km, nebo B‑závod na půlmaraton.</span>}
              {gg?.runs && <span className="mt-0.5 block text-[11px] text-fg-3">{`${gg.runs} běhy týdně (první maraton)`}</span>}
            </span>
          )}
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
          <span className="mt-2 block text-[12px] leading-5 text-fg-soft">{res?.text}</span>
          {gg?.coachCheck && !gg.coachCheck.ok && <span className="mt-1 block text-[12px] text-watch">{gg.coachCheck.text}</span>}
          {gg?.riskEnded && <span className="mt-1 block text-[12px] text-watch">{`Riziková cesta skončila (${gg.riskEnded.reason}), plán pokračuje bezpečnou cestou.`}</span>}
        </button>
      )}
      {mode === "setup" && <GoalSetup rid={rid} races={data.races || []} initial={formOf(goal)} onClose={() => setMode("")}
        onSaved={(d) => { setData(d); setMode("detail"); refresh() }} />}
      {mode === "detail" && goal && <GoalDetail rid={rid} data={data} gg={gg} busy={busy} onClose={() => setMode("")} onEdit={() => setMode("setup")} onCancel={cancel} onChange={setData} />}
    </Card>
  )
}
