// Data a připojení → Porovnání enginů: what each engine — Standardní (v1),
// Citlivý (v2), Kapacitní (v3) — scores for this runner today, what goes into
// it, and its weekly history over ~6 months, replayed on the runner's own data
// (GET /api/runners/{rid}/engine-compare). The runner's own engine is untouched.
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, Label } from "@/ui"
import { fmtD, QUAD } from "@/lib"
import { C } from "@/tokens"

const ENGINES: { id: "v1" | "v2" | "v3"; name: string; color: string; inputs: string }[] = [
  {
    id: "v1", name: "Standardní", color: C.fg2,
    inputs: "Mechanika: průměr vašich běhů za posledních 28 dní proti normě (dny 29–84) ve stejném profilu terénu a tempa. Zátěž: poměr 7:28 dní, prudké skoky objemu a délky běhu, klesání, intenzita, monotónnost. Symptomy: bolest, check-iny a hodnocení běhů.",
  },
  {
    id: "v2", name: "Citlivý", color: C.info,
    inputs: "Mechanika: každý běh zvlášť proti vaší typické chybě, s vyhlazením (EWMA), po úsecích běhu a s korekcí na tempo — změnu zachytí dřív; bolestivá období se do normy nepočítají. Zátěž a symptomy jako Standardní.",
  },
  {
    id: "v3", name: "Kapacitní", color: C.accent,
    inputs: "Mechanika jako Citlivý. Zátěž: proti vaší prokázané kapacitě v pěti kanálech (objem, intenzita v Z4+, klesání, stoupání, celková zátěž) — jednotlivé běhy i 7 dní, snížená podle připravenosti. Zátěž má v celkovém skóre větší váhu.",
  },
]
const METRICS: [string, string][] = [["overall", "Celkové skóre"], ["load", "Zátěž"], ["mech", "Mechanika"]]
const TIER_WORD: Record<string, string> = { ok: "nízké riziko", watch: "sledovat", alert: "vysoké riziko" }
const TIER_COL: Record<string, string> = { ok: C.ok, watch: C.watch, alert: C.alert }

function Axis({ label, v }: { label: string; v: number }) {
  return (
    <div>
      <div className="flex justify-between text-[11px]"><span className="text-fg-2">{label}</span><span className="tabular-nums text-fg">{v}</span></div>
      <div className="mt-0.5 h-1.5 rounded-full bg-white/10"><i className="block h-full rounded-full bg-info" style={{ width: `${Math.min(100, v)}%`, opacity: 0.4 + Math.min(v, 100) / 170 }} /></div>
    </div>
  )
}

function TodayCard({ e, s, active }: { e: (typeof ENGINES)[number]; s: any; active: boolean }) {
  if (!s) return null
  const q = QUAD[s.quadrant] || { t: s.quadrant, d: "" }
  return (
    <div className={`rounded-[22px] border p-4 ${active ? "border-accent/60 bg-accent/[.05]" : "border-white/10 bg-panel"}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2"><i className="size-2.5 rounded-full" style={{ background: e.color }} /><b className="text-sm text-fg">{e.name}</b></span>
        {active && <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-ink">váš engine</span>}
      </div>
      <div className="mt-3 flex items-end gap-3">
        <b className="font-serif text-4xl leading-none" style={{ color: TIER_COL[s.tier] || C.fg }}>{s.overall}</b>
        <span className="pb-0.5 text-xs leading-4 text-fg-2"><b className="block text-fg">{q.t}</b>{TIER_WORD[s.tier] || s.tier}</span>
      </div>
      <div className="mt-3 space-y-1.5">
        <Axis label="Zátěž" v={s.load} />
        <Axis label="Mechanika" v={s.mech} />
        <Axis label="Symptomy" v={s.symp} />
      </div>
      <p className="mt-3 font-sans font-bold text-[11px] uppercase tracking-[.12em] text-fg-3">Co teď vstupuje</p>
      {s.signals?.length ? (
        <ul className="mt-1.5 space-y-1">
          {s.signals.map((x: any, i: number) => (
            <li key={i} className="flex items-center gap-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate text-fg" title={x.name}>{x.name}</span>
              {x.val && <span className="shrink-0 tabular-nums text-[11px] text-fg-2">{String(x.val).replace(/(\d)\.(\d)/g, "$1,$2")}</span>}
              <span className="w-8 shrink-0 text-right tabular-nums text-[11px] text-watch">+{x.pts}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-1.5 text-[11px] text-fg-3">Nic nad prahem.</p>}
      <p className="mt-2 text-[11px] text-fg-3">spolehlivost normy {s.confidence} % · {s.version}</p>
    </div>
  )
}

function MultiLine({ series, metric }: { series: any[]; metric: string }) {
  const [act, setAct] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const W = 640, H = 220, padL = 30, padR = 10, padT = 10, padB = 24
  const n = series.length
  if (n < 2) return <p className="mt-2 text-xs text-fg-3">Na historii je zatím málo dat.</p>
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - Math.min(v, 100) / 100) * (H - padT - padB)
  const pick = (cx: number) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const i = Math.round(((((cx - r.left) / r.width) * W - padL) / (W - padL - padR)) * (n - 1))
    setAct(Math.max(0, Math.min(n - 1, i)))
  }
  const pct = (px: number, total: number) => `${(px / total) * 100}%`
  const threshold = metric === "overall" ? null : 25
  return (
    <div ref={ref} className="relative mt-3 select-none" style={{ touchAction: "pan-y" }}
      onPointerMove={(e) => pick(e.clientX)} onPointerDown={(e) => pick(e.clientX)} onPointerLeave={() => setAct(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-56 w-full">
        {[0, 25, 50, 75, 100].map((t) => (
          <line key={t} x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke={C.info} strokeOpacity={t === 0 ? 0.25 : 0.08} vectorEffect="non-scaling-stroke" />
        ))}
        {threshold != null && <line x1={padL} x2={W - padR} y1={y(threshold)} y2={y(threshold)} stroke={C.alert} strokeOpacity=".55" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
        {ENGINES.map((e) => (
          <path key={e.id} fill="none" stroke={e.color} strokeWidth="2.2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
            d={series.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[e.id]?.[metric] ?? 0).toFixed(1)}`).join(" ")} />
        ))}
        {act != null && <line x1={x(act)} x2={x(act)} y1={padT} y2={H - padB} stroke={C.fg} strokeOpacity=".35" vectorEffect="non-scaling-stroke" />}
      </svg>
      {[0, 50, 100].map((t) => (
        <span key={t} className="absolute left-0 -translate-y-1/2 tabular-nums text-[11px] text-fg-3" style={{ top: pct(y(t), H) }}>{t}</span>
      ))}
      {threshold != null && <span className="absolute right-1 -translate-y-full tabular-nums text-[11px] text-alert" style={{ top: pct(y(threshold), H) }}>práh 25</span>}
      {[0, Math.floor((n - 1) / 2), n - 1].map((i, k) => (
        <span key={k} className="absolute bottom-0 whitespace-nowrap tabular-nums text-[11px] text-fg-3"
          style={{ left: pct(x(i), W), transform: k === 0 ? "none" : k === 2 ? "translateX(-100%)" : "translateX(-50%)" }}>{fmtD(series[i].date)}</span>
      ))}
      {act != null && (
        <div className="pointer-events-none absolute top-0 z-10 rounded-lg border border-white/12 bg-panel px-2.5 py-1.5 text-[11px] shadow-lg"
          style={{ left: pct(x(act), W), transform: `translateX(${x(act) / W > 0.7 ? "-100%" : x(act) / W < 0.3 ? "0%" : "-50%"})` }}>
          <b className="block tabular-nums text-fg">{fmtD(series[act].date)}</b>
          {ENGINES.map((e) => (
            <span key={e.id} className="flex items-center gap-1.5 whitespace-nowrap"><i className="size-2 rounded-full" style={{ background: e.color }} />{e.name} <b className="tabular-nums text-fg">{series[act][e.id]?.[metric] ?? "—"}</b></span>
          ))}
        </div>
      )}
    </div>
  )
}

export function EngineCompare() {
  const { me, boot } = useApp()
  const rid = me?.runner_id
  const [data, setData] = useState<any | null | false>(null)
  const [metric, setMetric] = useState("overall")
  const current = boot?.assessment?.engineMode || boot?.runner?.engine_mode || "v1"
  useEffect(() => {
    if (!rid) return
    let alive = true
    api.engineCompare(rid).then((d) => alive && setData(d || false)).catch(() => alive && setData(false))
    return () => { alive = false }
  }, [rid])
  return (
    <>
      <Link to="/data" className="text-xs font-bold text-info">← Data a připojení</Link>
      <div className="mb-5 mt-3">
        <Label>Engine hodnocení</Label>
        <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">Porovnání enginů</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-fg-2">Stejná vaše data, tři způsoby hodnocení. Dnešní skóre, co do něj vstupuje, a jak by se každý engine vyvíjel posledních 6 měsíců — přepočteno zpětně, týden po týdnu. Váš zvolený engine se tím nemění.</p>
      </div>
      {data === null ? (
        <Card><p className="text-sm text-fg-2">Přepočítávám historii všech tří enginů… první načtení dne může trvat i desítky sekund.</p></Card>
      ) : data === false ? (
        <Card><p className="text-sm text-alert">Porovnání se nepodařilo načíst.</p></Card>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {ENGINES.map((e) => <TodayCard key={e.id} e={e} s={data.today?.[e.id]} active={current === e.id} />)}
          </div>
          <Card className="mt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Label>Posledních 6 měsíců · po týdnech</Label>
              <div className="inline-flex rounded-full border border-white/10 bg-panel p-1 text-[11px] font-semibold">
                {METRICS.map(([k, l]) => (
                  <button key={k} onClick={() => setMetric(k)} className={`rounded-full px-3 py-1 transition ${metric === k ? "bg-info text-ink" : "text-fg-2 hover:text-fg"}`}>{l}</button>
                ))}
              </div>
            </div>
            <MultiLine series={data.series || []} metric={metric} />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-2">
              {ENGINES.map((e) => <span key={e.id} className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded" style={{ background: e.color }} />{e.name}</span>)}
              {metric !== "overall" && <span className="text-fg-3">nad prahem 25 = osa vstupuje do kvadrantu</span>}
            </div>
          </Card>
          <Card className="mt-4">
            <Label>Co do enginů vstupuje</Label>
            <div className="mt-3 grid gap-4 md:grid-cols-3">
              {ENGINES.map((e) => (
                <div key={e.id}>
                  <p className="flex items-center gap-2 text-sm font-bold text-fg"><i className="size-2.5 rounded-full" style={{ background: e.color }} />{e.name}</p>
                  <p className="mt-1.5 text-xs leading-5 text-fg-2">{e.inputs}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[11px] leading-5 text-fg-3">Celkové skóre = 0,38 × mechanika + 0,30 × zátěž (Kapacitní 0,40) + 0,52 × symptomy, nejvýš 100. Kvadrant se řídí osami zátěže a mechaniky (práh 25), riziko celkovým skóre; opakovaná bolest na stejném místě zvedne riziko nejméně na „sledovat“.</p>
          </Card>
        </>
      )}
    </>
  )
}
