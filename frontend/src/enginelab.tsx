import { useEffect, useMemo, useRef, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, InfoDot, Label } from "@/ui"
import { clamp, QUAD } from "@/lib"

// Engine transparency sandbox ("Citlivostní analýza"): change any metric and see
// live how it moves the three axis scores and the resulting quadrant. Every number
// here is produced by the SAME scoring as the live engine (backend simulate() is
// fidelity-tested against assess()), so it's a faithful place to feel out the
// thresholds and how signals combine.

type Knob = {
  id: string; axis: string; label: string; grade: string; kind?: string
  unit?: string; min?: number; max?: number; step?: number; default: any
  thr?: number | null; dir?: string; desc: string
  engine?: "v12" | "v3"; hidden?: boolean
}
type Mode = "v1" | "v3"
type Spec = {
  knobs: Knob[]; defaults: Record<string, any>
  axes: { id: string; label: string; color: string }[]
  quadrants: Record<string, string>; thresholds: { quadHi: number; quadLo: number }
}
type SimResult = {
  signals: { id: string; axis: string; name: string; grade: string; pts: number; val: string }[]
  mech: number; load: number; symp: number; overall: number
  tier: string; quadrant: string; frailty: number
}
type Sweep = {
  knob: string; axis: string; label: string; unit: string; threshold: number | null
  dir: string; current: number; min: number; max: number
  series: { value: number; mech: number; load: number; symp: number; overall: number; quadrant: string }[]
}

const QCOL: Record<string, string> = { stable: "#6ce6d3", overreaching: "#f6d69a", silent: "#7fb0d6", critical: "#e77a59" }
const AXIS_COL: Record<string, string> = { load: "#f6d69a", mech: "#6ce6d3", symp: "#e77a59" }
const GRADE_COL: Record<string, string> = { A: "#e77a59", B: "#f6d69a", C: "#6ce6d3", "—": "#71837b" }
const TIER_WORD: Record<string, string> = { alert: "vysoké riziko", watch: "sledovat", ok: "nízké riziko" }

// knob id → the engine signal it drives, so each row can show its live points.
const SIG_BY_KNOB: Record<string, string> = {
  sessionSpike: "session_spike", spikeLatent: "spike_latent", paceSpike: "pace_spike", ratio: "ewma",
  hiRatio: "hi_load", loadCreep: "load_creep", monotony: "mono", descentSpike: "desc", steepSpike: "desc_steep",
  aerMean: "aer", hrvZ: "hrv", rhrZ: "rhr", hrvCvRatio: "hrvcv", tsbRel: "tsb", daysToRace: "taper",
  tavrZ: "tavr", gctZ: "gct", cadZ: "cad", voscZ: "vosc", balExcursion: "bal", decTrend: "dec", gaitCvRatio: "gaitcv",
  checkinPain: "pain", painRecent2: "pain", painRecurrence28: "pain", priorRegionOverlap: "pain_prior",
  soreness: "sore", stress: "fatigue", sleepDebt: "sleep", sleepRegRatio: "sleepreg", sleepEff: "sleepeff",
  feelingTrend: "feel", stiffnessIgnore: "stiffness", injurySeverity: "injury", complaintDays: "complaints",
  priorInjuryMonths: "hist",
  // engine v3 — both the per-run and the 7-day ratio drive one channel signal
  v3_volume_s: "cap_volume", v3_volume_w: "cap_volume", v3_intensity_s: "cap_intensity", v3_intensity_w: "cap_intensity",
  v3_descent_s: "cap_descent", v3_descent_w: "cap_descent", v3_ascent_s: "cap_ascent", v3_ascent_w: "cap_ascent",
  v3_systemic_s: "cap_systemic", v3_systemic_w: "cap_systemic",
}
// signals that come from an interaction / gate, shown as read-only derived rows.
const DERIVED_LABEL: Record<string, string> = { load_capacity: "Zátěž × regenerace (interakce)" }

function fmtVal(k: Knob, v: any): string {
  if (k.kind === "bool") return v ? "ano" : "ne"
  const n = Number(v)
  if (k.id === "daysToRace" && n < 0) return "žádný"
  if (k.id === "priorInjuryMonths" && n < 0) return "žádné"
  const dec = (k.step ?? 1) < 1 ? 2 : 0
  const s = dec ? n.toFixed(dec).replace(".", ",") : String(Math.round(n))
  return `${s}${k.unit ? ` ${k.unit}` : ""}`
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      role="switch"
      aria-checked={on}
      className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "bg-[#c7ff54]" : "bg-white/15"}`}
    >
      <span className={`absolute top-0.5 size-5 rounded-full bg-[#071313] transition-all ${on ? "left-[1.375rem]" : "left-0.5"}`} />
    </button>
  )
}

function KnobRow({ k, value, pts, active, onChange, selected, onSelect }: {
  k: Knob; value: any; pts: number; active: boolean; selected: boolean
  onChange: (v: any) => void; onSelect: () => void
}) {
  const isBool = k.kind === "bool"
  const thrPct = k.thr != null && k.min != null && k.max != null
    ? clamp(((k.thr - k.min) / (k.max - k.min)) * 100, 0, 100) : null
  return (
    <div className={`min-w-0 rounded-xl border px-3 py-2.5 transition ${selected ? "border-[#c7ff54]/60 bg-[#c7ff54]/[.05]" : "border-white/8 bg-white/[.02]"}`}>
      <div className="flex items-center gap-2">
        {isBool ? (
          <span className="flex min-w-0 flex-1 items-center gap-1.5">
            <span className="grid size-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" style={{ background: `${GRADE_COL[k.grade] || "#71837b"}26`, color: GRADE_COL[k.grade] || "#71837b" }}>{k.grade}</span>
            <span className="text-[13px] leading-tight text-[#e7efe9]">{k.label}</span>
          </span>
        ) : (
          <button onClick={onSelect} className="flex min-w-0 flex-1 items-center gap-1.5 text-left" title="Zobrazit citlivostní křivku">
            <span className="grid size-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" style={{ background: `${GRADE_COL[k.grade] || "#71837b"}26`, color: GRADE_COL[k.grade] || "#71837b" }}>{k.grade}</span>
            <span className="text-[13px] leading-tight text-[#e7efe9]">{k.label}</span>
          </button>
        )}
        <InfoDot text={k.desc} label={k.label} />
        <span className="w-16 shrink-0 text-right font-mono text-[11px] text-[#9bb3aa]">{fmtVal(k, value)}</span>
        {!isBool && (
          <span
            className="w-9 shrink-0 rounded-full px-1.5 py-0.5 text-center font-mono text-[10px] font-bold"
            style={pts > 0 ? { background: `${AXIS_COL[k.axis]}22`, color: AXIS_COL[k.axis] } : { color: "#4c5b55" }}
            title="Body, kterými tato metrika teď přispívá do své osy"
          >
            {pts > 0 ? `+${pts}` : "0"}
          </span>
        )}
      </div>
      {isBool ? (
        <div className="mt-2 flex justify-end"><Toggle on={!!value} onChange={onChange} /></div>
      ) : (
        <div className="relative mt-2">
          <input
            type="range" min={k.min} max={k.max} step={k.step} value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full accent-[#c7ff54]"
            style={{ background: active ? `${AXIS_COL[k.axis]}44` : "#ffffff14" }}
          />
          {thrPct != null && (
            <span
              className="pointer-events-none absolute -top-0.5 h-2.5 w-px bg-[#e77a59]"
              style={{ left: `${thrPct}%` }}
              title={`práh ${k.thr} (${k.dir === "below" ? "aktivní pod" : "aktivní nad"})`}
            />
          )}
        </div>
      )}
    </div>
  )
}

function AxisBar({ label, score, color, hi, lo, showQuad }: {
  label: string; score: number; color: string; hi: number; lo: number; showQuad: boolean
}) {
  const hot = showQuad && score >= hi
  return (
    <div>
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="text-[#a9c2b9]">{label}</span>
        <b className="font-mono" style={{ color: hot ? color : "#f1f8f1" }}>{score}<span className="text-[9px] text-[#71837b]"> / 100</span></b>
      </div>
      <div className="relative mt-1 h-2 rounded-full bg-white/[.07]">
        <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${clamp(score, 0, 100)}%`, background: color, opacity: hot ? 1 : 0.7 }} />
        {showQuad && (
          <>
            <i className="absolute top-[-2px] h-3 w-px bg-[#e77a59]" style={{ left: `${hi}%` }} title={`práh kvadrantu ${hi}`} />
            <i className="absolute top-[-1px] h-2.5 w-px bg-white/30" style={{ left: `${lo}%` }} title={`výstupní práh ${lo} (hystereze)`} />
          </>
        )}
      </div>
    </div>
  )
}

function QuadrantMini({ quadrant }: { quadrant: string }) {
  const cells: [string, string][] = [
    ["stable", "Stabilní"], ["silent", "Tichý drift"],
    ["overreaching", "Přetížení"], ["critical", "Kritická"],
  ]
  return (
    <div>
      <div className="grid grid-cols-2 gap-1.5">
        {cells.map(([key, lbl]) => {
          const on = key === quadrant
          const c = QCOL[key]
          return (
            <div key={key} className="relative overflow-hidden rounded-lg border p-2.5" style={{ borderColor: on ? c : "rgba(255,255,255,.08)", background: on ? `${c}22` : "rgba(255,255,255,.03)" }}>
              <span className="flex items-center gap-1.5">
                <i className="size-2 rounded-full" style={{ background: on ? c : `${c}55` }} />
                <b className="text-[12px]" style={{ color: on ? "#f1f8f1" : "#8ba59d" }}>{lbl}</b>
              </span>
              {on && <small className="mt-0.5 block text-[9px] font-bold uppercase tracking-wide" style={{ color: c }}>aktuální stav</small>}
            </div>
          )
        })}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[8px] uppercase tracking-[.14em] text-[#5f7268]">
        <span>← mechanika</span><span>zátěž ↑</span>
      </div>
    </div>
  )
}

type PlotLine = { key: "load" | "mech" | "symp" | "overall"; color: string; label: string }
const PLOT_LINES: Record<string, PlotLine[]> = {
  load: [{ key: "load", color: AXIS_COL.load, label: "zátěž" }, { key: "mech", color: AXIS_COL.mech, label: "mechanika" }],
  mech: [{ key: "load", color: AXIS_COL.load, label: "zátěž" }, { key: "mech", color: AXIS_COL.mech, label: "mechanika" }],
  symp: [{ key: "symp", color: AXIS_COL.symp, label: "příznaky" }, { key: "overall", color: "#cbd5cc", label: "celkové" }],
}

function SweepChart({ sweep }: { sweep: Sweep }) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const s = sweep.series
  if (s.length < 2) return null
  // Plot the axis the selected metric actually drives: load & mechanics for the
  // quadrant axes; symptoms & overall for symptom metrics (which don't move the
  // quadrant — only overall risk).
  const lines = PLOT_LINES[sweep.axis] || PLOT_LINES.load
  const W = 320, H = 150, padL = 26, padR = 8, padT = 10, padB = 26
  const maxY = Math.max(30, ...s.map((p) => Math.max(...lines.map((l) => p[l.key])))) * 1.1
  const x = (i: number) => padL + (i / (s.length - 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - v / maxY) * (H - padT - padB)
  const line = (key: PlotLine["key"]) => s.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ")
  const vx = (val: number) => padL + clamp((val - sweep.min) / (sweep.max - sweep.min || 1), 0, 1) * (W - padL - padR)
  const fmtx = (v: number) => (Math.abs(v) >= 100 ? String(Math.round(v)) : (Math.round(v * 100) / 100).toString().replace(".", ","))
  const cur = act ?? s.findIndex((p) => p.value >= sweep.current)
  const curP = s[cur >= 0 ? cur : s.length - 1]
  return (
    <div
      ref={wrapRef}
      className="relative mt-2 select-none"
      style={{ touchAction: "pan-y" }}
      onPointerMove={(e) => {
        const r = wrapRef.current?.getBoundingClientRect(); if (!r) return
        const i = Math.round((((e.clientX - r.left) / r.width) * W - padL) / (W - padL - padR) * (s.length - 1))
        setAct(Math.max(0, Math.min(s.length - 1, i)))
      }}
      onPointerLeave={() => setAct(null)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" style={{ height: H }} preserveAspectRatio="none">
        {/* quadrant threshold + y ticks */}
        {[0, 25, Math.round(maxY)].map((t, i) => (
          <g key={i}>
            <line x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={t === 25 ? "#e77a59" : "#6ce6d3"} strokeOpacity={t === 25 ? 0.5 : 0.12} strokeDasharray={t === 25 ? "4 3" : undefined} />
            <text x={padL - 4} y={y(t) + 3} textAnchor="end" fill={t === 25 ? "#e77a59" : "#71837b"} fontSize="7">{t}</text>
          </g>
        ))}
        {/* per-x quadrant strip along the bottom */}
        {s.map((p, i) => (
          <rect key={i} x={x(i) - (W - padL - padR) / (s.length - 1) / 2} y={H - padB + 3} width={(W - padL - padR) / (s.length - 1) + 0.5} height="5" fill={QCOL[p.quadrant]} opacity={0.85} />
        ))}
        {/* metric threshold (vertical) */}
        {sweep.threshold != null && sweep.threshold >= sweep.min && sweep.threshold <= sweep.max && (
          <line x1={vx(sweep.threshold)} y1={padT} x2={vx(sweep.threshold)} y2={H - padB} stroke="#e77a59" strokeOpacity="0.5" strokeDasharray="3 3" />
        )}
        {/* current value marker */}
        <line x1={vx(sweep.current)} y1={padT} x2={vx(sweep.current)} y2={H - padB} stroke="#f1f8f1" strokeOpacity="0.55" strokeWidth="1.4" />
        {lines.map((l) => <path key={l.key} d={line(l.key)} fill="none" stroke={l.color} strokeWidth="2" strokeLinejoin="round" />)}
        {act != null && <line x1={x(act)} y1={padT} x2={x(act)} y2={H - padB} stroke="#f1f8f1" strokeOpacity="0.3" />}
        {/* x labels */}
        {[0, Math.floor((s.length - 1) / 2), s.length - 1].map((idx, i) => (
          <text key={i} x={x(idx)} y={H - 4} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} fill="#71837b" fontSize="7">{fmtx(s[idx].value)}</text>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3 text-[10px]">
        <span className="flex items-center gap-3">
          {lines.map((l) => (
            <span key={l.key} className="flex items-center gap-1"><i className="h-0.5 w-3" style={{ background: l.color }} />{l.label}</span>
          ))}
        </span>
        {curP && (
          <span className="font-mono text-[#9bb3aa]">
            {sweep.label} {fmtx(curP.value)} → {lines.map((l) => `${l.label} ${curP[l.key]}`).join(" · ")} · <b style={{ color: QCOL[curP.quadrant] }}>{(QUAD[curP.quadrant] || QUAD.stable).t}</b>
          </span>
        )}
      </div>
      {sweep.axis === "symp" && (
        <p className="mt-1 text-[10px] leading-4 text-[#71837b]">Příznaky nemění kvadrant (ten určuje jen zátěž × mechanika) — zvedají celkové skóre a tím tier rizika.</p>
      )}
    </div>
  )
}

export function EngineLab() {
  const { me, boot } = useApp()
  const rid = me?.runner_id
  const isV3 = (boot?.assessment?.engineMode || boot?.runner?.engine_mode) === "v3"
  // Which engine's load axis the sandbox models — follows the runner's engine,
  // switchable to compare.
  const [mode, setMode] = useState<Mode>(isV3 ? "v3" : "v1")
  const [spec, setSpec] = useState<Spec | null>(null)
  const [inputs, setInputs] = useState<Record<string, any>>({})
  const [prev, setPrev] = useState<string>("stable")
  const [sel, setSel] = useState<string>(isV3 ? "v3_volume_s" : "sessionSpike")
  useEffect(() => { setMode(isV3 ? "v3" : "v1"); setSel(isV3 ? "v3_volume_s" : "sessionSpike") }, [isV3])
  const [res, setRes] = useState<SimResult | null>(null)
  const [sweep, setSweep] = useState<Sweep | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [seeded, setSeeded] = useState(false)

  useEffect(() => {
    let alive = true
    api.engineKnobs().then((sp: Spec) => {
      if (!alive) return
      setSpec(sp)
      setInputs({ ...sp.defaults })
    }).catch(() => alive && setErr("Nepodařilo se načíst definici enginu."))
    return () => { alive = false }
  }, [])

  const key = useMemo(() => JSON.stringify(inputs) + "|" + prev + "|" + mode, [inputs, prev, mode])
  const dKey = useDebounced(key, 80)
  useEffect(() => {
    if (!spec || !Object.keys(inputs).length) return
    let alive = true
    api.engineSimulate(inputs, prev, mode).then((r: SimResult) => alive && (setRes(r), setErr(null))).catch(() => alive && setErr("Výpočet selhal."))
    api.engineSweep(inputs, sel, prev, 49, mode).then((s: Sweep) => alive && setSweep(s)).catch(() => {})
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dKey, sel, spec])

  const setVal = (id: string, v: any) => setInputs((p) => ({ ...p, [id]: v }))
  const reset = () => spec && (setInputs({ ...spec.defaults }), setPrev("stable"), setSeeded(false))
  const loadMine = async () => {
    if (!rid) return
    try {
      const d = await api.engineInputs(rid)
      setInputs({ ...spec!.defaults, ...d.inputs })
      if (d.prevQuadrant) setPrev(d.prevQuadrant)
      if (d.mode === "v3" || d.mode === "v1") {
        setMode(d.mode)
        setSel(d.mode === "v3" ? "v3_volume_s" : "sessionSpike")
      }
      setSeeded(true)
    } catch { setErr("Nepodařilo se načíst vaše hodnoty.") }
  }

  const sigPts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const s of res?.signals || []) m[s.id] = s.pts
    return m
  }, [res])
  // derived signals (interactions) that have no direct slider — shown read-only.
  const derived = useMemo(() => (res?.signals || []).filter((s) => DERIVED_LABEL[s.id]), [res])

  if (!spec) return <div className="rounded-2xl border border-dashed border-white/15 p-6 text-center text-sm text-[#71837b]">{err || "Načítám engine…"}</div>

  const visible = (k: Knob) => !k.hidden && (!k.engine || (mode === "v3" ? k.engine === "v3" : k.engine === "v12"))
  const byAxis = (ax: string) => spec.knobs.filter((k) => k.axis === ax && visible(k))
  const axisScore = (ax: string) => (ax === "load" ? res?.load : ax === "mech" ? res?.mech : res?.symp) ?? 0
  const quad = res ? QUAD[res.quadrant] || QUAD.stable : QUAD.stable

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>Engine · transparentnost</Label>
          <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">Citlivostní analýza</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#64736e]">
            Posuňte kteroukoli metriku a sledujte, jak mění skóre jednotlivých os a výsledný kvadrant. Čísla počítá stejný
            engine jako v aplikaci — je to věrné místo, kde nahmatat prahy a pochopit, jak se signály skládají. Klepnutím na
            název metriky ji zvolíte pro citlivostní křivku.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-full border border-white/15 p-0.5 text-[11px] font-bold">
            {([["v1", "Standardní / Citlivý"], ["v3", "Kapacitní"]] as [Mode, string][]).map(([m, l]) => (
              <button key={m} onClick={() => {
                setMode(m)
                const k = spec.knobs.find((x) => x.id === sel)
                if (k && k.engine && k.engine !== (m === "v3" ? "v3" : "v12")) setSel(m === "v3" ? "v3_volume_s" : "sessionSpike")
              }}
                className={`rounded-full px-3 py-1.5 transition ${mode === m ? "bg-[#c7ff54] text-[#071313]" : "text-[#a9c2b9] hover:text-[#f1f8f1]"}`}>
                {l}
              </button>
            ))}
          </div>
          {rid && (
            <button onClick={loadMine} className={`rounded-full px-4 py-2 text-xs font-bold transition ${seeded ? "bg-[#c7ff54] text-[#071313]" : "border border-[#c7ff54]/50 text-[#c7ff54] hover:bg-[#c7ff54]/10"}`}>
              Načíst moje data
            </button>
          )}
          <button onClick={reset} className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-[#a9c2b9] hover:text-[#f1f8f1]">Výchozí (0)</button>
        </div>
      </div>

      {err && <p className="mb-3 text-xs font-bold text-[#e77a59]">{err}</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(320px,380px)_1fr] lg:items-start">
        {/* ---------------- live summary + sweep (sticky) ---------------- */}
        <div className="grid min-w-0 gap-4 lg:sticky lg:top-24">
          <Card className="min-w-0 border-white/10 bg-[#0c201d] text-[#f1f8f1]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label>Výsledný stav</Label>
                <h2 className="mt-1 font-serif text-2xl leading-tight">{quad.t}</h2>
              </div>
              <div className="text-right">
                <p className="font-serif text-4xl leading-none">{res?.overall ?? 0}<small className="text-xs text-[#71837b]">/100</small></p>
                <span className="mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${QCOL[res?.quadrant || "stable"]}22`, color: QCOL[res?.quadrant || "stable"] }}>{TIER_WORD[res?.tier || "ok"]}</span>
              </div>
            </div>
            <p className="mt-2 text-[11px] leading-4 text-[#a9c2b9]">{quad.d}</p>
            <div className="mt-4"><QuadrantMini quadrant={res?.quadrant || "stable"} /></div>
            <div className="mt-5 space-y-3 border-t border-white/10 pt-4">
              <AxisBar label="Zátěž" score={res?.load ?? 0} color={AXIS_COL.load} hi={spec.thresholds.quadHi} lo={spec.thresholds.quadLo} showQuad />
              <AxisBar label="Mechanika" score={res?.mech ?? 0} color={AXIS_COL.mech} hi={spec.thresholds.quadHi} lo={spec.thresholds.quadLo} showQuad />
              <AxisBar label="Příznaky" score={res?.symp ?? 0} color={AXIS_COL.symp} hi={spec.thresholds.quadHi} lo={spec.thresholds.quadLo} showQuad={false} />
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-3 text-[10px] text-[#71837b]">
              <span>kvadrant = zátěž × mechanika · práh {spec.thresholds.quadHi} (hystereze {spec.thresholds.quadLo})</span>
              {res && res.frailty > 1 && <span title="Násobitel z anamnézy — zesiluje zátěž i mechaniku">×{res.frailty} křehkost</span>}
            </div>
            <div className="mt-3 flex items-center gap-2 border-t border-white/10 pt-3">
              <span className="text-[10px] uppercase tracking-wide text-[#71837b]">Předchozí kvadrant</span>
              <select value={prev} onChange={(e) => setPrev(e.target.value)} className="rounded-lg border border-white/15 bg-[#102724] px-2 py-1 text-[11px] text-[#e7efe9]" title="Hystereze: osa už „horká“ zůstane horká, dokud neklesne pod výstupní práh">
                {Object.entries(spec.quadrants).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}
              </select>
            </div>
          </Card>

          <Card className="min-w-0 border-white/10 bg-[#0c201d] text-[#f1f8f1]">
            <div className="flex items-center justify-between">
              <Label>Citlivostní křivka</Label>
              <span className="font-mono text-[10px] text-[#71837b]">osy 0–100 · práh 25</span>
            </div>
            <p className="mt-1 text-[11px] text-[#a9c2b9]">{sweep ? sweep.label : "—"} napříč rozsahem, ostatní metriky drženy. Svislá bílá = aktuální hodnota, oranžová = práh metriky, pruh dole = kvadrant.</p>
            {sweep ? <SweepChart sweep={sweep} /> : <p className="mt-3 text-xs text-[#71837b]">Vyberte metriku klepnutím na její název.</p>}
          </Card>
        </div>

        {/* ---------------- knob sections ---------------- */}
        <div className="grid min-w-0 gap-4">
          {spec.axes.map((ax) => (
            <Card key={ax.id} className="min-w-0 border-white/10 bg-[#0c201d] text-[#f1f8f1]">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <i className="size-2.5 rounded-full" style={{ background: ax.color }} />
                  <Label>{ax.label}</Label>
                </span>
                <span className="font-mono text-sm" style={{ color: ax.color }}>{axisScore(ax.id)}<span className="text-[10px] text-[#71837b]"> / 100</span></span>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {byAxis(ax.id).map((k) => (
                  <KnobRow
                    key={k.id}
                    k={k}
                    value={inputs[k.id]}
                    pts={sigPts[SIG_BY_KNOB[k.id]] || 0}
                    active={(() => {
                      if (k.kind === "bool" || k.thr == null) return false
                      const n = Number(inputs[k.id])
                      return k.dir === "below" ? n <= k.thr : n >= k.thr
                    })()}
                    selected={sel === k.id}
                    onSelect={() => setSel(k.id)}
                    onChange={(v) => setVal(k.id, v)}
                  />
                ))}
              </div>
              {ax.id === "load" && derived.length > 0 && (
                <div className="mt-2 rounded-xl border border-dashed border-white/12 px-3 py-2">
                  <p className="font-mono text-[9px] uppercase tracking-[.14em] text-[#71837b]">Odvozené (interakce)</p>
                  {derived.map((s) => (
                    <div key={s.id} className="mt-1 flex items-center gap-2 text-[12px]">
                      <span className="flex-1 truncate text-[#e7efe9]">{DERIVED_LABEL[s.id]}</span>
                      <span className="font-mono text-[#9bb3aa]">{s.val}</span>
                      <span className="font-mono font-bold" style={{ color: ax.color }}>+{s.pts}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      </div>
    </>
  )
}
