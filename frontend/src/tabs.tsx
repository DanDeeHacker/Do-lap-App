import { Fragment, useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { AxisLineChart, Bars, Card, Chip, Field, InfoDot, Label, Metric, Ring, Sheet, Slider, Sparkline, useAsync, useToast } from "@/ui"
import { METRIC_INFO as MI, MECH_INFO_BY_LABEL } from "@/metricinfo"
import { clamp, czk, FEEL_LABEL, fmtD, fmtSlot, paceStr, PHASE, QUAD, sgn } from "@/lib"
import MuscleAnatomy, { PainHeatmap, type BodyPoint } from "@/components/MuscleAnatomy"
import { CAP_SIGNAL_IDS, CapacityPanel } from "@/capacity"

const surf = (s?: string) => ({ road: "silnice", trail: "terén", treadmill: "pás", track: "dráha" } as any)[s || ""] || s || "—"
const dayAgo = (n: number) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10)

export function Head({ kicker, title, sub }: { kicker: string; title: string; sub?: string }) {
  return (
    <div className="mb-6">
      <Label>{kicker}</Label>
      <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">{title}</h1>
      {sub && <p className="mt-3 max-w-2xl text-sm leading-6 text-[#64736e]">{sub}</p>}
    </div>
  )
}
function Empty({ children }: { children: any }) {
  return <div className="rounded-2xl border border-dashed border-white/15 p-6 text-center text-sm text-[#71837b]">{children}</div>
}

// A page gate that tells "still loading" apart from "the fetch failed". Without
// this a failed bootstrap keeps rendering "Načítám…" forever, since boot stays
// null. Surfaces store.error and offers a retry.
function LoadGate({ label = "Načítám…" }: { label?: string }) {
  const { error, refresh } = useApp()
  if (!error) return <Empty>{label}</Empty>
  return (
    <div className="rounded-2xl border border-[#e77a59]/40 bg-[#3c2922] p-6 text-center">
      <p className="text-sm font-bold text-[#ffc1ab]">Data se nepodařilo načíst</p>
      <p className="mt-1 text-xs leading-5 text-[#ffc1ab]/80">{error}</p>
      <button onClick={() => refresh()} className="mt-4 rounded-full bg-[#c7ff54] px-4 py-2 text-xs font-bold text-[#071313]">Zkusit znovu</button>
    </div>
  )
}

/* ============================ DENÍK ============================ */
export function Post() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const [rate, setRate] = useState<{ act: any; initial?: any } | null>(null)
  const fb = (boot?.activity_feedback || []) as any[]
  const acts = (boot?.activities || []) as any[]
  const cutoff = dayAgo(14)
  const rated = new Set(fb.map((f) => f.activity_id))
  const unrated = acts.filter((a) => a.started_at > cutoff && !rated.has(a.id))
  const actById = useMemo(() => new Map(acts.map((a) => [a.id, a])), [acts])
  const sorted = useMemo(() => fb.slice().sort((x, y) => y.submitted_at.localeCompare(x.submitted_at)), [fb])
  const ov = useMemo(() => diaryOverview(fb), [fb])

  // Daily (Checkin) + weekly (self-reported OSTRC InjuryReport) check-ins — the
  // self-report entries NOT tied to a specific run. Shown and summarised in the
  // Deník separately from the per-run diary above. Both already ship in bootstrap.
  const checkins = (boot?.checkins || []) as any[]
  const weeklyReports = ((boot?.injury_reports || []) as any[]).filter((r) => (r.source || "").startsWith("self"))
  const checkinItems = useMemo(() => {
    const daily = checkins.map((c) => ({
      id: `c${c.id}`, kind: "daily" as const, at: c.submitted_at,
      pain: c.pain_score, soreness: c.soreness, fatigue: c.stress, mood: c.mood, note: c.notes,
      regions: ((c.pain_points || []) as any[]).map((p) => p.region).filter(Boolean),
    }))
    const wk = weeklyReports.map((r) => ({
      id: `w${r.id}`, kind: "weekly" as const, at: r.submitted_at,
      severity: r.severity, status: r.status, adhoc: r.source === "self_adhoc", note: r.note,
      regions: [r.body_region, ...((r.pain_points || []) as any[]).map((p) => p.region)].filter(Boolean),
    }))
    return [...daily, ...wk].sort((x, y) => (y.at || "").localeCompare(x.at || ""))
  }, [checkins, weeklyReports])
  const ciSum = useMemo(() => {
    if (!checkinItems.length) return null
    const cut30 = dayAgo(30)
    const daily = checkinItems.filter((x) => x.kind === "daily")
    const wk = checkinItems.filter((x) => x.kind === "weekly")
    const painVals = daily.map((x: any) => x.pain).filter((v) => v != null)
    const moodVals = daily.map((x: any) => x.mood).filter((v) => v != null)
    const map: Record<string, number> = {}
    checkinItems.filter((x) => (x.at || "") >= cut30).forEach((x) => x.regions.forEach((r: string) => { map[r] = (map[r] || 0) + 1 }))
    const top = Object.entries(map).sort((a, b) => b[1] - a[1])
    return {
      nDaily: daily.length, nWeekly: wk.length, lastAt: checkinItems[0].at,
      painMean: painVals.length ? mean(painVals) : null, moodMean: moodVals.length ? mean(moodVals) : null,
      activeWeekly: wk.filter((x: any) => x.status === "active").length, top,
    }
  }, [checkinItems])

  // Open the editor for an existing entry, resolving its activity (or a stub
  // if the run has aged out of the bootstrap window).
  const editEntry = (f: any) => {
    const act = actById.get(f.activity_id) || { id: f.activity_id, title: "Běh", distance_km: "", started_at: f.submitted_at, pace_s_km: 0, surface: "", descent_m: 0, rpe: f.rpe }
    setRate({ act, initial: f })
  }

  return (
    <>
      <Head
        kicker="Deník běhů"
        title={unrated.length ? `${unrated.length} běhů čeká na zápis` : "Deník máte kompletní"}
      />
      {rate && <RateSheet act={rate.act} initial={rate.initial} rid={rid} onClose={() => setRate(null)} onDone={() => { setRate(null); refresh() }} />}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_.8fr]">
        <div className="grid gap-4">
          <Card>
            <Label>Čeká na zápis</Label>
            {unrated.length ? (
              <div className="mt-3 divide-y divide-white/10">
                {unrated.map((x) => (
                  <button key={x.id} onClick={() => setRate({ act: x })} className="flex w-full items-center gap-3 py-3 text-left">
                    <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#17382f] text-[10px] font-bold text-[#6ce6d3]">{surf(x.surface)}</span>
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-sm">{x.title} · {x.distance_km} km</b>
                      <em className="block truncate text-xs not-italic text-[#71837b]">{fmtD(x.started_at)} · {paceStr(x.pace_s_km)}/km · {x.descent_m} m klesání</em>
                    </span>
                    <span className="shrink-0 text-[#6ce6d3]">›</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="mt-3"><Empty>Nic nečeká. Další zápis se objeví po příštím běhu.</Empty></div>
            )}
          </Card>
          <Card>
            <div className="flex items-center justify-between">
              <Label>Poslední zápisy</Label>
              {fb.length > 0 && <span className="font-mono text-[10px] text-[#71837b]">klepnutím upravíte</span>}
            </div>
            {sorted.length ? (
              <div className="mt-3 divide-y divide-white/10">
                {sorted.slice(0, 10).map((f) => {
                  const act = actById.get(f.activity_id)
                  const hurt = f.pain_during >= 4
                  return (
                    <button key={f.id} onClick={() => editEntry(f)} className="group flex w-full items-center gap-3 py-3 text-left">
                      <span className="grid size-9 shrink-0 place-items-center rounded-xl text-[10px] font-bold" style={{ background: hurt ? "#3a1f18" : "#17382f", color: hurt ? "#e77a59" : "#6ce6d3" }}>{surf(act?.surface)}</span>
                      <span className="min-w-0 flex-1">
                        <b className="block truncate text-sm">{act ? `${act.title} · ${act.distance_km} km` : "Běh"}</b>
                        <em className="mt-0.5 block truncate text-xs not-italic text-[#71837b]">
                          {fmtD(f.submitted_at)} · pocit {FEEL_LABEL[f.feeling] || "—"} · nohy {f.legs}/5
                          {f.pain_during > 0 ? ` · bolest ${f.pain_during}/10` : ""}
                        </em>
                      </span>
                      {f.pain_site && <span className="hidden sm:block"><Chip tone="alert">{f.pain_site}</Chip></span>}
                      <span className="shrink-0 text-xs text-[#71837b] transition group-hover:text-[#6ce6d3]"><span className="hidden sm:inline">Upravit</span><span className="sm:hidden">›</span></span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="mt-3"><Empty>Zatím žádné zápisy.</Empty></div>
            )}
          </Card>
          <Card>
            <div className="flex items-center justify-between">
              <Label>Check-iny (denní a týdenní)</Label>
              <span className="font-mono text-[10px] text-[#71837b]">samostatně od běhů</span>
            </div>
            <p className="mt-1 text-xs text-[#71837b]">Váš self-report mimo konkrétní běh — denní pocit/bolest a týdenní kontrola (OSTRC). Přidáte je přes tlačítko Check-in.</p>
            {checkinItems.length ? (
              <div className="mt-3 divide-y divide-white/10">
                {checkinItems.slice(0, 10).map((x: any) => {
                  const daily = x.kind === "daily"
                  const hurt = daily ? (x.pain || 0) >= 4 : (x.severity || 0) >= 40
                  return (
                    <div key={x.id} className="flex items-center gap-3 py-3">
                      <span className={`grid size-9 shrink-0 place-items-center rounded-xl text-[9px] font-bold ${daily ? "bg-[#17382f] text-[#6ce6d3]" : "bg-[#1e2f3c] text-[#7fb0d6]"}`}>{daily ? "DEN" : "TÝD"}</span>
                      <span className="min-w-0 flex-1">
                        <b className="text-sm">{daily ? "Denní check-in" : x.adhoc ? "Týdenní check-in · mimořádný" : "Týdenní check-in"}</b>
                        <em className="mt-0.5 block truncate text-xs not-italic text-[#71837b]">
                          {fmtD(x.at)}
                          {daily
                            ? `${x.pain != null ? ` · bolest ${x.pain}/10` : ""}${x.mood != null ? ` · nálada ${x.mood}/4` : ""}${x.fatigue != null ? ` · únava ${x.fatigue}` : ""}`
                            : ` · OSTRC ${x.severity ?? 0}/100 · ${x.status === "active" ? "aktivní" : x.status === "resolved" ? "odezněl" : "bez potíží"}`}
                        </em>
                      </span>
                      {x.regions.length > 0 && <Chip tone={hurt ? "alert" : "muted"}>{x.regions.slice(0, 2).join(", ")}{x.regions.length > 2 ? "…" : ""}</Chip>}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="mt-3"><Empty>Zatím žádné check-iny. Přidejte první přes záložku Check-in na pravém okraji.</Empty></div>
            )}
          </Card>
        </div>
        <div className="grid gap-4">
          {ov ? (
            <>
              <Card>
                <Label>Souhrn deníku</Label>
                <div className="mt-3 flex items-baseline gap-2">
                  <p className="font-serif text-4xl">{mfmt(1, ov.feelingMean)}</p>
                  <span className="text-sm text-[#71837b]">/5 pocit</span>
                  {ov.feelingTrend !== 0 && <span className="ml-auto font-mono text-xs" style={{ color: ov.feelingTrend > 0 ? "#6ce6d3" : "#e77a59" }}>{sgn(ov.feelingTrend)} trend</span>}
                </div>
                <p className="mt-1 text-xs text-[#71837b]">{ov.n} zápisů · nohy v průměru {mfmt(1, ov.legsMean)}/5</p>
                <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/10 pt-4 text-center">
                  <div><p className="font-serif text-2xl">{ov.n21}</p><p className="text-[10px] text-[#71837b]">za 21 dní</p></div>
                  <div><p className="font-serif text-2xl" style={{ color: ov.niggleCount >= 3 ? "#e77a59" : undefined }}>{ov.niggleCount}×</p><p className="text-[10px] text-[#71837b]">s bolestí</p></div>
                  <div><p className="font-serif text-2xl" style={{ color: ov.painMax >= 4 ? "#e77a59" : undefined }}>{ov.painMax}</p><p className="text-[10px] text-[#71837b]">max bolest</p></div>
                </div>
                {Object.keys(ov.painMap).length > 0 && (
                  <div className="mt-4 border-t border-white/10 pt-4">
                    <Label>Kde to nejčastěji bolí</Label>
                    <p className="mt-1 text-xs text-[#71837b]">Podle zápisů za posledních 30 dní — čím výraznější místo, tím častěji jste ho označil jako bolestivé.</p>
                    <div className="mt-3"><PainHeatmap counts={ov.painMap} /></div>
                    <div className="mt-4 space-y-1.5">
                      {ov.topSites.slice(0, 5).map(([region, count]) => {
                        const w = Math.round((count / ov.topSites[0][1]) * 100)
                        return (
                          <div key={region} className="flex items-center gap-2 text-xs">
                            <span className="w-32 shrink-0 truncate text-[#c9dcd4]">{region}</span>
                            <div className="h-1.5 flex-1 rounded-full bg-white/10"><i className="block h-full rounded-full bg-[#e77a59]" style={{ width: `${w}%` }} /></div>
                            <span className="font-mono text-[#9bb3aa]">{count}×</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </Card>
              <Card>
                <Label>Co z toho čteme</Label>
                <ul className="mt-3 space-y-2.5">
                  {ov.insights.map((t, i) => (
                    <li key={i} className="flex gap-2 text-sm leading-5">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full" style={{ background: t.tone === "alert" ? "#e77a59" : t.tone === "watch" ? "#f6d69a" : "#6ce6d3" }} />
                      <span className="text-[#c9dcd4]">{t.text}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : (
            <Card><Empty>Zatím málo zápisů na to, aby z nich šel číst vzorec. Užitečné to začne být zhruba od čtvrtého.</Empty></Card>
          )}
          {ciSum && (
            <Card>
              <Label>Souhrn check-inů</Label>
              <p className="mt-1 text-xs text-[#71837b]">Odděleně od běhů · poslední {fmtD(ciSum.lastAt)}</p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                <div><p className="font-serif text-2xl text-[#6ce6d3]">{ciSum.nDaily}</p><p className="text-[10px] text-[#71837b]">denních</p></div>
                <div><p className="font-serif text-2xl text-[#7fb0d6]">{ciSum.nWeekly}</p><p className="text-[10px] text-[#71837b]">týdenních{ciSum.activeWeekly ? ` · ${ciSum.activeWeekly} akt.` : ""}</p></div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/10 pt-3 text-center">
                <div><p className="font-serif text-2xl" style={{ color: ciSum.painMean != null && ciSum.painMean >= 4 ? "#e77a59" : undefined }}>{ciSum.painMean != null ? mfmt(1, ciSum.painMean) : "—"}</p><p className="text-[10px] text-[#71837b]">ø bolest /10</p></div>
                <div><p className="font-serif text-2xl">{ciSum.moodMean != null ? mfmt(1, ciSum.moodMean) : "—"}</p><p className="text-[10px] text-[#71837b]">ø nálada /4</p></div>
              </div>
              {ciSum.top.length > 0 && (
                <div className="mt-4 border-t border-white/10 pt-3">
                  <Label>Nejčastější místo v check-inech</Label>
                  <p className="mt-1 text-[11px] text-[#71837b]">Za posledních 30 dní napříč denními i týdenními check-iny.</p>
                  <div className="mt-2 space-y-1.5">
                    {ciSum.top.slice(0, 4).map(([region, count]) => (
                      <div key={region} className="flex items-center gap-2 text-xs">
                        <span className="w-32 shrink-0 truncate text-[#c9dcd4]">{region}</span>
                        <div className="h-1.5 flex-1 rounded-full bg-white/10"><i className="block h-full rounded-full bg-[#7fb0d6]" style={{ width: `${Math.round((count / ciSum.top[0][1]) * 100)}%` }} /></div>
                        <span className="font-mono text-[#9bb3aa]">{count}×</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  )
}

// Digest the feedback log into a lay-readable diary overview + plain-language
// insights. All client-side so it stays in sync with edits without a round-trip.
function diaryOverview(fb: any[]) {
  if (!fb.length) return null
  const rows = fb.slice().sort((a, b) => a.submitted_at.localeCompare(b.submitted_at))
  const feelings = rows.map((f) => f.feeling).filter((v) => v != null)
  const legs = rows.map((f) => f.legs).filter((v) => v != null)
  const feelingMean = mean(feelings)
  const recent = feelings.slice(-4), prior = feelings.slice(-8, -4)
  const feelingTrend = recent.length && prior.length ? +(mean(recent) - mean(prior)).toFixed(1) : 0
  const cut21 = dayAgo(21)
  const n21 = rows.filter((f) => f.submitted_at >= cut21).length
  // A run counts as "with pain" if any pain was logged at all — a rating, a
  // niggle flag, or a marked body location. (The old ≥2 threshold silently
  // dropped mild pain=1 entries even when the runner marked where it hurt.)
  const hasPain = (f: any) => (f.pain_during || 0) > 0 || f.niggle || (f.pain_points && f.pain_points.length) || f.pain_site
  const niggleCount = rows.filter(hasPain).length
  const painMax = rows.reduce((m, f) => Math.max(m, f.pain_during || 0), 0)
  // Frequency of each painful body region over the last 30 days, for the map.
  const cut30 = dayAgo(30)
  const painMap: Record<string, number> = {}
  rows.filter((f) => f.submitted_at >= cut30).forEach((f) => {
    ((f.pain_points || []) as any[]).forEach((p) => { if (p?.region) painMap[p.region] = (painMap[p.region] || 0) + 1 })
  })
  const topSites = Object.entries(painMap).sort((a, b) => b[1] - a[1])
  const topSite = topSites[0]

  const insights: { text: string; tone: "ok" | "watch" | "alert" }[] = []
  if (niggleCount >= 3) insights.push({ text: `Bolest jste zapsal ${niggleCount}× — na náhodu už je toho dost. Stojí za to sledovat, u jakého typu běhu se vrací.`, tone: "alert" })
  else if (niggleCount > 0) insights.push({ text: `Bolest se objevila ${niggleCount}×, zatím ojediněle. Držte oči na tom, jestli se neopakuje.`, tone: "watch" })
  else insights.push({ text: "Žádnou bolest jste v zápisech neměl — pokračujte stejně.", tone: "ok" })
  if (topSite && topSite[1] >= 2) insights.push({ text: `Nejčastěji se ozývá ${topSite[0]} (${topSite[1]}×). Opakující se místo bereme vážněji než jednorázové.`, tone: "watch" })
  if (feelingTrend <= -0.6) insights.push({ text: "Pocit z běhů poslední týdny klesá. Bývá to první signál únavy dřív, než to ukážou čísla — zvažte lehčí týden.", tone: "watch" })
  else if (feelingTrend >= 0.6) insights.push({ text: "Pocit z běhů roste, forma jde nahoru.", tone: "ok" })
  if (mean(legs) <= 2.4 && legs.length >= 4) insights.push({ text: "Nohy hodnotíte často jako těžké. Zkuste přidat regenerační den nebo zkrátit dlouhý běh.", tone: "watch" })

  return { n: rows.length, n21, feelingMean, feelingTrend, legsMean: mean(legs), niggleCount, painMax, topSite, topSites, painMap, insights }
}

function RateSheet({ act, rid, initial, onClose, onDone }: { act: any; rid: string; initial?: any; onClose: () => void; onDone: () => void }) {
  const edit = !!initial
  const [feeling, setFeeling] = useState(initial?.feeling ?? 3)
  const [legs, setLegs] = useState(initial?.legs ?? 3)
  const [stiff, setStiff] = useState(initial?.stiffness_pre ?? 1)
  const [rpe, setRpe] = useState(initial?.rpe ?? act.rpe ?? 5)
  const [pain, setPain] = useState(initial?.pain_during ?? 0)
  const [note, setNote] = useState(initial?.note ?? "")
  const [points, setPoints] = useState<BodyPoint[]>([])
  const { busy, err, run } = useAsync()
  const toast = useToast()
  // Preload the body map from an existing entry's picked sites (edit mode).
  const initialRegions: string[] = ((initial?.pain_points as any[]) || []).map((p) => p.region).filter(Boolean)

  const submit = () =>
    run(async () => {
      const pts = points.map((p) => ({ region: p.region, side: p.side || null, severity: pain, type: p.kind }))
      const site = points.length ? points.map((p) => p.region).join(", ") : null
      await api.rateActivity(rid, act.id, {
        feeling, legs, stiffness_pre: stiff, rpe, pain_during: pain, pain_site: site,
        pain_points: pts, niggle: pain >= 2, note: note || null,
      })
      toast({ title: edit ? "Zápis upraven" : "Zápis uložen", msg: `${act.title}${act.distance_km ? ` · ${act.distance_km} km` : ""}` })
      onDone()
    })

  return (
    <Sheet
      open
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          <button onClick={submit} disabled={busy} className="flex-1 rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">{busy ? "Ukládám…" : edit ? "Uložit změny" : "Uložit zápis"}</button>
          <button onClick={onClose} className="rounded-full border border-white/15 px-5 py-3 text-sm font-bold text-[#a9c2b9]">Zrušit</button>
        </div>
      }
    >
      <h2 className="font-serif text-2xl leading-tight">{edit ? "Upravit zápis" : `${act.title}${act.distance_km ? ` · ${act.distance_km} km` : ""}`}</h2>
      <p className="mt-1 text-xs text-[#a9c2b9]">{fmtD(act.started_at)}{act.pace_s_km ? ` · ${paceStr(act.pace_s_km)}/km` : ""}{act.surface ? ` · ${surf(act.surface)}` : ""}{act.descent_m ? ` · ${act.descent_m} m sklesáno` : ""}</p>
      <div className="mt-4 grid gap-x-6 gap-y-4 md:grid-cols-2">
        <div>
          <Field label="Jak ztuhlé byly nohy PŘED během" hint="1 uvolněné · 5 ztuhlé"><Slider name="stiff" min={1} max={5} value={stiff} onChange={setStiff} /></Field>
          <Field label="Jak vám bylo"><Slider name="feeling" min={1} max={5} value={feeling} onChange={setFeeling} labels={FEEL_LABEL} /></Field>
          <Field label="Nohy" hint="1 těžké · 5 svěží"><Slider name="legs" min={1} max={5} value={legs} onChange={setLegs} /></Field>
          <Field label="Vnímaná námaha (RPE)" hint={`hodinky ${act.rpe || "—"}/10`}><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>
          <Field label="Bolest během běhu" hint="0 žádná"><Slider name="pain" min={0} max={10} value={pain} onChange={setPain} /></Field>
          <Field label="Poznámka">
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="Kdy se to ozvalo, co to zhoršilo…" />
          </Field>
        </div>
        <div className="min-w-0">
          <Label>Kde to bolelo</Label>
          <p className="mt-1 text-xs text-[#71837b]">Klepněte na všechna místa, která bolela — můžete vybrat víc, silueta rozliší levou a pravou stranu.</p>
          <div className="mx-auto mt-3 max-w-[280px] md:max-w-none"><MuscleAnatomy multi onSelect={setPoints} initialRegions={initialRegions} /></div>
        </div>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
    </Sheet>
  )
}

/* ============================ MECHANIKA (POHYB) ============================ */
const mfmt = (dec: number, v: number) => (dec > 0 ? v.toFixed(dec).replace(".", ",") : String(Math.round(v)))
const mean = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0)
const std = (a: number[]) => {
  if (a.length < 2) return 0
  const m = mean(a)
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1))
}
type Metric = { label: string; unit: string; dec: number; value: number; baseline: number; z: number; delta: string; hot: boolean; position: number; weeks: number[]; dates: string[]; series: number[]; seriesDates: string[]; terrain?: boolean; approx?: boolean }

// dates of the last `n` runs that carry `field` (to label the per-run charts)
function fieldDates(acts: any[], field: string, n: number): string[] {
  return acts.filter((a) => a[field] != null).sort((a, b) => a.started_at.localeCompare(b.started_at)).slice(-n).map((a) => a.started_at)
}

// Rough fallback for when the engine has no terrain-cleaned drift for a metric:
// a plain recent-vs-baseline mean straight off the raw activity fields, with NO
// terrain normalization. Flagged `approx` so the card can say so out loud instead
// of masquerading as an engine-grade, terrain-cleaned signal.
function metricFromActs(acts: any[], field: string, label: string, unit: string, dec: number): Metric | null {
  const rows = acts.filter((a) => a[field] != null).sort((a, b) => a.started_at.localeCompare(b.started_at))
  if (rows.length < 6) return null
  const vals = rows.map((a) => a[field] as number)
  const dates = rows.map((a) => a.started_at)
  const weeks = vals.slice(-8)
  const value = mean(vals.slice(-5))
  const baseVals = vals.slice(0, Math.max(3, vals.length - 8))
  const baseline = mean(baseVals)
  const sd = std(baseVals) || Math.abs(baseline * 0.02) || 1
  const z = (value - baseline) / sd
  const d = value - baseline
  const delta = `${d >= 0 ? "+" : "−"}${mfmt(dec, Math.abs(d))} ${unit}`
  return { label, unit, dec, value, baseline, z, delta, hot: false, position: clamp(50 + z * 18, 8, 92), weeks, dates: dates.slice(-8), series: vals.slice(-26), seriesDates: dates.slice(-26), terrain: false, approx: true }
}

// Usual range = baseline ± 1 SD, the SD backed out from the z-score — shared by
// the card's interval bar and the band in the full-trend chart.
function usualRange(m: Metric) {
  const isd = Math.abs(m.z) > 0.15 ? Math.abs(m.value - m.baseline) / Math.abs(m.z) : (Math.abs(m.baseline) * 0.03 || 1)
  return { lo: m.baseline - isd, hi: m.baseline + isd, isd }
}

function MechMetricCard({ m, onSelect }: { m: Metric; onSelect: () => void }) {
  const { label, unit, dec, value, baseline, delta, hot, approx } = m
  // Numeric axis for the interval bar, so the bar shows real numbers, not just a dot.
  const { lo: bLo, hi: bHi, isd } = usualRange(m)
  const dLo = Math.min(bLo, value) - isd * 0.8, dHi = Math.max(bHi, value) + isd * 0.8
  const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 4, 96)
  return (
    <div onClick={onSelect} role="button" tabIndex={0} className="group w-full cursor-pointer p-4 text-left">
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <Label>{label}</Label>
          {MECH_INFO_BY_LABEL[label] && <InfoDot text={MECH_INFO_BY_LABEL[label]} label={label} />}
          {approx && <span title="Málo dat v jednotlivých profilech terénu — hrubý odhad z průměru běhů napříč terénem, ne terénně očištěná odchylka enginu." className="rounded-full bg-white/[.06] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[#9bb3aa]">odhad</span>}
        </span>
        <span className={`rounded-full px-2 py-1 text-[9px] font-bold ${hot ? "bg-[#e77a59]/15 text-[#ffc1ab]" : "bg-[#c7ff54]/10 text-[#c7ff54]"}`}>{delta}</span>
      </div>
      <strong className="mt-4 block font-serif text-3xl tracking-[-.05em] text-[#f1f8f1]">
        {mfmt(dec, value)} <span className="text-lg text-[#71837b]">{unit}</span>
      </strong>
      <div className="mt-6">
        <div className="relative h-2 rounded-full bg-[#071313]">
          {/* usual range (baseline ± 1 SD) */}
          <i className="absolute top-0 h-full rounded-full bg-[#6ce6d3]/25" style={{ left: `${P(bLo)}%`, width: `${P(bHi) - P(bLo)}%` }} />
          {/* baseline center tick */}
          <i className="absolute top-[-3px] h-3.5 w-px bg-[#91b7a9]" style={{ left: `${P(baseline)}%` }} />
          {/* current value marker + number */}
          <i style={{ left: `${P(value)}%` }} className={`absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ${hot ? "bg-[#e77a59] ring-[#e77a59]/15" : "bg-[#6ce6d3] ring-[#6ce6d3]/15"}`} />
          <span className="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-[10px] font-bold" style={{ left: `${P(value)}%`, color: hot ? "#ffc1ab" : "#6ce6d3" }}>{mfmt(dec, value)}</span>
        </div>
        <div className="relative mt-1.5 h-3 text-[9px] text-[#71837b]">
          <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${P(bLo)}%` }}>{mfmt(dec, bLo)}</span>
          <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${P(bHi)}%` }}>{mfmt(dec, bHi)}</span>
        </div>
      </div>
    </div>
  )
}

// All mechanics metrics we can read straight off an activity, so the terrain
// comparison covers the same set as the cards above.
const M_DEFS: { field: string; label: string; unit: string; dec: number }[] = [
  { field: "vert_ratio_pct", label: "Vertikální poměr", unit: "%", dec: 1 },
  { field: "gct_ms", label: "Kontakt se zemí", unit: "ms", dec: 0 },
  { field: "gct_balance_l", label: "Symetrie kontaktu", unit: "%", dec: 1 },
  { field: "cadence_spm", label: "Kadence", unit: "spm", dec: 0 },
  { field: "stride_len_m", label: "Délka kroku", unit: "m", dec: 2 },
  { field: "vert_osc_cm", label: "Vertikální oscilace", unit: "cm", dec: 1 },
]
const _SURF: any = { road: "silnice", trail: "terén", treadmill: "pás", track: "dráha" }
const _GRADE: any = { up: "stoupání", flat: "rovina", down: "klesání", rolling: "kopcovitě" }
const _PACE: any = { fast: "rychle", mod: "středně", easy: "volně" }
// Mirror of engine.bucket(): surface | slope | pace — must match so profiles
// line up with the backend's terrain-aware baselines.
function bucketKey(a: any): string {
  const km = Math.max(a.distance_km || 0, 1)
  const asc = (a.ascent_m || 0) / km, desc = (a.descent_m || 0) / km
  const g = desc - asc > 12 ? "down" : asc - desc > 12 ? "up" : asc + desc >= 30 ? "rolling" : "flat"
  const p = ((a.duration_min || 0) / km) * 60
  const pb = p < 270 ? "fast" : p < 330 ? "mod" : "easy"
  return `${a.surface}|${g}|${pb}`
}
const bucketParts = (b: string) => { const [s, g, p] = b.split("|"); return { surf: _SURF[s] || s, grade: _GRADE[g] || g, pace: _PACE[p] || p } }

type Cell = { now: number | null; avg6: number; z: number | null } | null
const TERRAIN_DAYS = 182   // the terrain comparison looks 6 months back, so every profile has runs to show
// Per terrain profile × per metric: recent mean and its drift-z against the
// same profile's baseline — same windows/logic as engine._drift_z_core.
function terrainCompare(acts: any[]) {
  const since = dayAgo(TERRAIN_DAYS), rec = dayAgo(28)
  const byB: Record<string, any[]> = {}
  for (const a of acts) {
    if (!a.started_at || a.started_at <= since || (a.sport && a.sport !== "running")) continue
    ;(byB[bucketKey(a)] ||= []).push(a)
  }
  // every profile run at least twice in 6 months, most runs first
  const keys = Object.keys(byB).filter((b) => byB[b].length >= 2).sort((x, y) => byB[y].length - byB[x].length)
  const profiles = keys.map((b) => ({ key: b, ...bucketParts(b), n: byB[b].length, nNow: byB[b].filter((a) => a.started_at > rec).length }))
  const rows = M_DEFS.map((m) => ({
    ...m,
    cells: keys.map((b): Cell => {
      const vals = byB[b].filter((a) => a[m.field] != null).map((a) => ({ d: a.started_at as string, v: a[m.field] as number }))
      if (!vals.length) return null
      const recv = vals.filter((x) => x.d > rec).map((x) => x.v)
      const base = vals.filter((x) => x.d <= rec).map((x) => x.v)
      const now = recv.length ? mean(recv) : null
      const avg6 = mean(vals.map((x) => x.v))
      if (now == null || base.length < 3) return { now, avg6, z: null }
      const sd = Math.max(std(base), Math.abs(mean(base)) * 0.012) || 1
      return { now, avg6, z: (now - mean(base)) / sd }
    }),
  }))
  return { profiles, rows }
}

function TerrainMatrix({ acts }: { acts: any[] }) {
  const { profiles, rows } = useMemo(() => terrainCompare(acts), [acts])
  if (!profiles.length) return <Card><Empty>Zatím není dost běhů ve srovnatelných profilech terénu.</Empty></Card>
  const zTone = (z: number | null) => (z == null ? "#71837b" : Math.abs(z) >= 1 ? "#e77a59" : Math.abs(z) >= 0.5 ? "#f6d69a" : "#6ce6d3")
  const cols = `minmax(104px,1.1fr) repeat(${profiles.length}, minmax(92px,1fr))`
  return (
    <Card>
      <Label>Podle profilu terénu · 6 měsíců</Label>
      <p className="mt-1 text-xs leading-5 text-[#71837b]">Každý sloupec je jiný profil (povrch · sklon · tempo) — všechny, které jste za posledních 6 měsíců běželi aspoň dvakrát. Hodnota = průměr posledních 28 dní; šedě průměr za 6 měsíců, když jste profil poslední měsíc neběželi. Odchylka (z) = posledních 28 dní proti starším běhům stejného profilu.</p>
      <div className="-mx-1 mt-4 overflow-x-auto px-1 pb-1">
      <div className="grid min-w-max items-stretch gap-y-1" style={{ gridTemplateColumns: cols }}>
        <div />
        {profiles.map((p) => (
          <div key={p.key} className="rounded-xl bg-[#102724] px-2 py-2 text-center">
            <p className="text-[13px] font-semibold text-[#f1f8f1]">{p.surf}</p>
            <p className="text-[10px] text-[#9bb3aa]">{p.grade} · {p.pace}</p>
            <p className="mt-0.5 font-mono text-[9px] text-[#71837b]">{p.n} běhů · {p.nNow} za 28 d</p>
          </div>
        ))}
        {rows.map((r) => (
          <Fragment key={r.field}>
            <div className="col-span-full mt-1 h-px bg-white/5" />
            <div className="flex items-baseline gap-1 py-2.5 pr-2 text-[12px] text-[#a9c2b9]">{r.label}<span className="text-[10px] text-[#71837b]">{r.unit}</span></div>
            {r.cells.map((c, i) => (
              <div key={i} className="px-1 py-2.5 text-center">
                {c ? (
                  c.now != null ? (
                    <>
                      <p className="font-serif text-lg leading-none text-[#f1f8f1]">{mfmt(r.dec, c.now)}</p>
                      <p className="mt-1 font-mono text-[10px]" style={{ color: zTone(c.z) }}>{c.z != null ? `${sgn(Math.round(c.z * 100) / 100)} z` : "málo dat"}</p>
                    </>
                  ) : (
                    <>
                      <p className="font-serif text-lg leading-none text-[#71837b]">{mfmt(r.dec, c.avg6)}</p>
                      <p className="mt-1 font-mono text-[9px] text-[#71837b]">⌀ 6 měs.</p>
                    </>
                  )
                ) : (
                  <p className="text-[#71837b]">—</p>
                )}
              </div>
            ))}
          </Fragment>
        ))}
      </div>
      </div>
    </Card>
  )
}

// Terrain + weather context of one run (from /run-history), as one short line
// for the collapsed row and a detail block for the expanded one.
const cz1 = (v: number) => mfmt(1, v)
function terrainLine(t: any) {
  if (!t) return null
  const parts = [t.surfaceLabel, t.gradeLabel !== "—" ? t.gradeLabel : null]
  if (t.ascPerKm != null || t.descPerKm != null) parts.push(`↑${Math.round(t.ascPerKm ?? 0)} ↓${Math.round(t.descPerKm ?? 0)} m/km`)
  return parts.filter(Boolean).join(" · ")
}
function weatherLine(w: any) {
  if (!w) return null
  const temp = w.precision === "hour" ? `${w.tempC} °C` : `${w.tMin}–${w.tMax} °C`
  const extra = [w.windKmh != null && `${w.windKmh} km/h`, w.precipMm > 0 && `${cz1(w.precipMm)} mm`].filter(Boolean)
  return `${w.icon} ${temp}${extra.length ? " · " + extra.join(" · ") : ""}`
}
function RunContext({ x }: { x: any }) {
  const t = x.terrain
  const w = x.weather
  const row = (k: string, v: any) => v != null && v !== false && v !== "" && (
    <div className="flex justify-between gap-3 border-t border-white/5 py-1.5 first:border-0">
      <dt className="text-[#71837b]">{k}</dt><dd className="text-right font-mono text-[11px] text-[#f1f8f1]">{v}</dd>
    </div>
  )
  return (
    <div className="grid gap-3 border-t border-white/5 px-4 py-3 text-xs md:grid-cols-2">
      <section className="min-w-0">
        <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Terén</p>
        {t ? (
          <dl className="mt-1">
            {row("Profil srovnání", t.bucketLabel)}
            {row("Stoupání", t.ascentM != null && `${t.ascentM} m${t.ascPerKm != null ? ` · ${cz1(t.ascPerKm)} m/km` : ""}`)}
            {row("Klesání", t.descentM != null && `${t.descentM} m${t.descPerKm != null ? ` · ${cz1(t.descPerKm)} m/km` : ""}`)}
            {row("Strmé klesání (≤ −10 %)", t.steepDescentPct != null && `${t.steepDescentPct} % spádu`)}
            {row("Náročnost terénu", t.demand != null && `×${mfmt(2, t.demand)} oproti rovině`)}
            {row("Povrch z mapy", t.sampled && [t.sampled.surfaceLabel, t.sampled.onTrail && "stezka", t.sampled.forest && "les"].filter(Boolean).join(" · ") + (t.sampled.source ? ` (${t.sampled.source})` : ""))}
          </dl>
        ) : <p className="mt-1 text-[#71837b]">Bez údajů o terénu.</p>}
      </section>
      <section className="min-w-0">
        <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Počasí</p>
        {w ? (
          <>
            <dl className="mt-1">
              {row("Podmínky", `${w.icon} ${w.label}`)}
              {row("Teplota", w.precision === "hour" ? `${w.tempC} °C · pocitově ${w.feelsC} °C` : `${w.tMin}–${w.tMax} °C · pocitově až ${w.feelsC} °C`)}
              {row("Vlhkost", w.humidity != null && `${w.humidity} %`)}
              {row(w.precision === "hour" ? "Vítr" : "Vítr (max.)", w.windKmh != null && `${w.windKmh} km/h`)}
              {row("Srážky", `${cz1(w.precipMm || 0)} mm`)}
            </dl>
            <p className="mt-1.5 text-[10px] leading-4 text-[#71837b]">
              {w.precision === "hour" ? `Během běhu (start ${x.start_time}, ${Math.round(x.duration_min || 0)} min)` : "Denní souhrn (čas startu neznámý)"}
              {" · "}{w.place === "city" ? `přibližně — podle města ${w.city}` : "v místě startu (±10 km)"} · {w.source}
            </p>
            {w.hot && w.precision === "hour" && <p className="mt-1.5 rounded-lg bg-[#3a2a12] px-2 py-1 text-[10px] leading-4 text-[#f6d69a]">Pocitově přes 24 °C — vyšší tep při obvyklém tempu je v tomhle počasí očekávaný.</p>}
          </>
        ) : <p className="mt-1 text-[#71837b]">{x.weatherNote || "Počasí není k dispozici."}</p>}
      </section>
    </div>
  )
}

function RunHistoryReal({ acts }: { acts: any[] }) {
  const { me } = useApp()
  const rid = me?.runner_id
  const [open, setOpen] = useState(false)
  const [run, setRun] = useState<number | null>(null)
  const [cmp, setCmp] = useState<Record<number, any>>({})
  const [ctx, setCtx] = useState<any[] | null | false>(null) // null = not loaded, false = failed
  useEffect(() => {
    if (!open || !rid || ctx !== null) return
    let alive = true
    api.runHistory(rid, 20).then((d) => alive && setCtx(Array.isArray(d) ? d : false)).catch(() => alive && setCtx(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rid])
  useEffect(() => {
    if (run == null || !rid || cmp[run] !== undefined) return
    let alive = true
    setCmp((c) => ({ ...c, [run]: null })) // mark loading
    api.runCompare(rid, run).then((d) => alive && setCmp((c) => ({ ...c, [run]: d || false }))).catch(() => alive && setCmp((c) => ({ ...c, [run]: false })))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, rid])
  // the context endpoint when it answered, else the boot activities without context
  const rows: any[] = ctx ? ctx : acts.slice().sort((a, b) => (b.started_at || "").localeCompare(a.started_at || "")).slice(0, 20)
  return (
    <>
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-4 flex w-full items-center justify-between gap-4 rounded-[24px] border border-white/10 bg-[#102724] px-5 py-4 text-left text-[#f1f8f1] transition hover:border-[#6ce6d3]/40">
        <span><span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">Historie běhů</span><span className="mt-1 block font-serif text-xl">Běhy s terénem a počasím — rozklikni pro úseky a srovnání</span></span>
        <span className="text-[#6ce6d3]">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {ctx === null && <p className="px-1 text-[10px] text-[#71837b]">Načítám terén a počasí…</p>}
          {ctx === false && <p className="px-1 text-[10px] text-[#71837b]">Kontext terénu a počasí se nepodařilo načíst — zobrazuji jen statistiky.</p>}
          {rows.map((x) => {
            const isOpen = run === x.id
            const d = cmp[x.id]
            const tl = terrainLine(x.terrain)
            const wl = weatherLine(x.weather)
            return (
              <div key={x.id} className="overflow-hidden rounded-2xl border border-white/10 bg-[#0c201d]">
                <button onClick={() => setRun(isOpen ? null : x.id)} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left">
                  <span className="grid size-9 place-items-center rounded-xl bg-[#17382f] text-[10px] font-bold text-[#6ce6d3]">{surf(x.surface)}</span>
                  <span className="min-w-0">
                    <b className="text-sm">{x.title}</b>
                    <em className="block text-xs not-italic text-[#71837b]">{fmtD(x.started_at)}{x.start_time ? ` ${x.start_time}` : ""} · {x.distance_km} km · {paceStr(x.pace_s_km)}/km · {x.avg_hr} tep</em>
                    {(tl || wl) && (
                      <span className="mt-1 flex flex-wrap gap-1.5">
                        {tl && <span className="rounded-full bg-[#17382f] px-2 py-0.5 text-[10px] text-[#9bd8c6]">{tl}</span>}
                        {wl && <span className={`rounded-full px-2 py-0.5 text-[10px] ${x.weather?.hot && x.weather.precision === "hour" ? "bg-[#3a2a12] text-[#f6d69a]" : "bg-[#152a36] text-[#a9cde0]"}`}>{wl}</span>}
                      </span>
                    )}
                  </span>
                  <span className="whitespace-nowrap font-mono text-xs text-[#9bb3aa]">VR {x.vert_ratio_pct ?? "—"} · {isOpen ? "▴" : "▾"}</span>
                </button>
                {isOpen && ctx && <RunContext x={x} />}
                {isOpen && rid && <SegmentTimeline rid={rid} aid={x.id} />}
                {isOpen && (
                  d && d.metrics ? (
                    <MonthCompare data={d} />
                  ) : d === false ? (
                    <dl className="grid grid-cols-3 gap-2 border-t border-white/5 px-4 py-3 text-[10px] md:grid-cols-6">
                      {[["Kadence", x.cadence_spm && `${x.cadence_spm} spm`], ["Kontakt", x.gct_ms && `${x.gct_ms} ms`], ["Krok", x.stride_len_m && `${x.stride_len_m} m`], ["Osc.", x.vert_osc_cm && `${x.vert_osc_cm} cm`], ["Balance", x.gct_balance_l ? `${x.gct_balance_l} %` : "—"], ["Klesání", x.descent_m != null && `${x.descent_m} m`]].map(([k, v]) => (
                        <div key={k as string}><dt className="uppercase tracking-[.1em] text-[#71837b]">{k}</dt><dd className="mt-0.5 font-mono text-[11px] text-[#f1f8f1]">{v || "—"}</dd></div>
                      ))}
                    </dl>
                  ) : (
                    <p className="border-t border-white/5 px-4 py-3 text-xs text-[#71837b]">Načítám srovnání s během před měsícem…</p>
                  )
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}

// ---- Úseky běhu: per-segment test of one run vs the norm as of that run's day ----
// Each 20–60 s steady segment × metric is compared with what the runner's own
// baseline expects for that segment (speed, gradient, time in run, surface).
// Drawn as a timeline heatmap (x = time in the run, one row per metric), with a
// tap-to-inspect segment detail and a list of the stretches that stood out.
const SEG_METRICS: [string, string, string, string, number][] = [
  // key, full label, short label, unit, decimals
  ["gct_ms", "Kontakt se zemí", "Kontakt", "ms", 0],
  ["cadence_spm", "Kadence", "Kadence", "spm", 0],
  ["step_len_m", "Délka kroku", "Krok", "m", 2],
  ["vo_cm", "Vertikální oscilace", "Oscilace", "cm", 1],
  ["vratio_pct", "Vertikální poměr", "V. poměr", "%", 1],
  ["gct_bal_pct", "Symetrie kontaktu", "Symetrie", "%", 1],
]
const SEG_BAND: Record<string, [string, string]> = {
  B1: ["prudký sjezd", "#2f6f9f"], B2: ["sjezd", "#4f93b8"], B3: ["rovina", "#40615a"],
  B4: ["výjezd", "#c79a4a"], B5: ["prudký výjezd", "#d9783f"],
}
const UP = "#e77a59"
const DOWN = "#5fb4d9"
const mmss = (s: number) => {
  const t = Math.max(0, Math.round(s))
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), ss = String(t % 60).padStart(2, "0")
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`
}
const zStr = (z: number) => `${z > 0 ? "+" : z < 0 ? "−" : ""}${mfmt(1, Math.abs(z))}σ`
const pStr = (p: number) => (p < 0.001 ? "p < 0,001" : `p = ${mfmt(3, p)}`)
const segVal = (key: string, v: number | null | undefined) => {
  const m = SEG_METRICS.find((x) => x[0] === key)
  return v == null || !m ? "—" : `${mfmt(m[4], v)} ${m[3]}`
}

// consecutive significant segments of one metric in one direction (a single
// untested / non-significant segment inside a stretch doesn't break it)
function sigStretches(segs: any[]) {
  const out: any[] = []
  for (const [key, label] of SEG_METRICS) {
    let cur: any = null
    let gap = 0
    for (const s of segs) {
      const f = s.findings.find((x: any) => x.metric === key)
      if (f?.sig && (!cur || cur.dir === f.dir)) {
        if (!cur) cur = { key, label, dir: f.dir, segs: [] as any[], zs: [] as number[] }
        cur.segs.push(s)
        cur.zs.push(f.z)
        gap = 0
      } else if (cur && gap === 0 && !(f?.sig)) {
        gap = 1
      } else if (cur) {
        out.push(cur)
        cur = f?.sig ? { key, label, dir: f.dir, segs: [s], zs: [f.z] } : null
        gap = 0
      }
    }
    if (cur) out.push(cur)
  }
  return out
    .map((g) => {
      const first = g.segs[0], last = g.segs.at(-1)
      const bands = [...new Set(g.segs.map((s: any) => SEG_BAND[s.band]?.[0] || s.bandLabel))]
      const meanZ = g.zs.reduce((a: number, b: number) => a + b, 0) / g.zs.length
      const peak = g.segs[g.zs.reduce((bi: number, z: number, i: number) => (Math.abs(z) > Math.abs(g.zs[bi]) ? i : bi), 0)]
      return { ...g, from: first.idx + 1, to: last.idx + 1, t0: first.startS, t1: last.startS + (last.durationS || 0), bands, meanZ, peak, n: g.segs.length }
    })
    .sort((a, b) => b.n * Math.abs(b.meanZ) - a.n * Math.abs(a.meanZ))
}

function SegmentTimeline({ rid, aid }: { rid: string; aid: number }) {
  const [data, setData] = useState<any | null | false>(null)
  const [sel, setSel] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    api.runSegmentTest(rid, aid).then((d) => alive && setData(d || false)).catch(() => alive && setData(false))
    return () => { alive = false }
  }, [rid, aid])
  const run = data && data.available ? data.run : null
  const segs: any[] = run?.segments || []
  const rows = SEG_METRICS.filter(([k]) => segs.some((s) => s.findings.some((f: any) => f.metric === k)))
  const stretches = useMemo(() => sigStretches(segs), [segs])
  useEffect(() => { // open on the most notable segment
    if (!segs.length || sel != null) return
    setSel(stretches[0]?.peak.idx ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segs.length])
  const head = (
    <span className="flex items-center gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Úseky běhu vůči vaší normě</span>
      <InfoDot label="Úseky běhu" text="Běh je rozdělený na úseky po 20–60 s ustáleného běhu. Každý úsek se porovná s tím, co od vás čeká vaše vlastní norma přesně pro ten úsek — při jeho tempu, sklonu, čase v běhu a povrchu. Norma je z běhů 29–84 dní PŘED tímto během, takže i starší běh se posuzuje tím, jak jste běhali tehdy. σ = odchylka v násobcích vašeho obvyklého rozptylu. „Významné“ = po korekci na počet testů (FDR 5 %), ne jen p < 0,05. Úseky mimo vaši obvyklou rychlost / sklon / povrch se netestují." />
    </span>
  )
  const box = (children: any) => <div className="border-t border-white/5 px-4 py-3">{head}{children}</div>
  if (data === null) return box(<p className="mt-2 text-xs text-[#71837b]">Načítám úseky…</p>)
  if (data === false) return box(<p className="mt-2 text-xs text-[#71837b]">Úseky se nepodařilo načíst.</p>)
  if (!data.available)
    return box(<p className="mt-2 text-xs leading-5 text-[#71837b]">Zobrazí se po stažení <b className="text-[#a9c2b9]">Detailních dat</b> pro tento běh (Data a připojení → ⛰ Detailní data).</p>)
  if (!run.nTested)
    return box(<p className="mt-2 text-xs leading-5 text-[#71837b]">{data.reason === "no_baseline"
      ? "K datu tohoto běhu ještě nebyla dost dlouhá historie — norma potřebuje aspoň 5 běhů s detailními daty 29–84 dní před ním."
      : "Žádný úsek nešel otestovat — tempo, sklon nebo povrch byly mimo rozsah vaší normy."}</p>)

  const T = Math.max(60, ...segs.map((s) => s.startS + (s.durationS || 0)))
  const pick = (e: any) => {
    const r = e.currentTarget.getBoundingClientRect()
    const t = ((e.clientX - r.left) / r.width) * T
    const hit = segs.find((s) => t >= s.startS && t < s.startS + (s.durationS || 0))
      || segs.reduce((b, s) => (Math.abs(s.startS - t) < Math.abs(b.startS - t) ? s : b), segs[0])
    setSel(hit.idx)
  }
  const cur = sel != null ? segs[sel] : null
  const cell = (s: any, key: string) => {
    const f = s.findings.find((x: any) => x.metric === key)
    if (!f) return { fill: "#ffffff", op: 0.05 }
    return { fill: f.z > 0 ? UP : DOWN, op: f.sig ? 1 : Math.min(0.5, Math.max(0.1, Math.abs(f.z) / 4)) }
  }
  const strip = (key: string | null, h: number) => (
    <svg viewBox={`0 0 ${T} ${h}`} preserveAspectRatio="none" className="block w-full cursor-pointer" style={{ height: h }} onClick={pick} role="presentation">
      {segs.map((s) => {
        const w = Math.max((s.durationS || 0) * 0.94, T / 900)
        if (key === null) return <rect key={s.idx} x={s.startS} y={0} width={w} height={h} fill={SEG_BAND[s.band]?.[1] || "#40615a"} />
        const c = cell(s, key)
        return <rect key={s.idx} x={s.startS} y={0} width={w} height={h} fill={c.fill} fillOpacity={c.op} />
      })}
      {cur && <rect x={cur.startS} y={0.5} width={Math.max(cur.durationS || 0, T / 300)} height={h - 1} fill="none" stroke="#f1f8f1" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
    </svg>
  )
  const stepMin = [5, 10, 15, 20, 30, 60].find((st) => T / 60 / st <= 4) || 60
  const ticks = Array.from({ length: Math.floor(T / 60 / stepMin) + 1 }, (_, i) => i * stepMin * 60)
  const sigSegs = segs.filter((s) => s.sig).length
  return box(
    <>
      <p className="mt-1.5 text-[11px] leading-5 text-[#a9c2b9]">
        {run.nSeg} úseků · {run.nTested} testů · {run.sigCount
          ? <b className="text-[#f6b89f]">{run.sigCount} {run.sigCount === 1 ? "významná odchylka" : run.sigCount < 5 ? "významné odchylky" : "významných odchylek"} v {sigSegs} {sigSegs === 1 ? "úseku" : "úsecích"}</b>
          : <b className="text-[#9bd8c6]">bez významných odchylek</b>}
        <span className="text-[#71837b]"> · norma k datu běhu: {data.baseline.runs} běhů ({fmtD(data.baseline.from)} – {fmtD(data.baseline.to)})</span>
      </p>

      <div className="mt-3 grid grid-cols-[64px_minmax(0,1fr)] items-center gap-x-2 gap-y-[3px] sm:grid-cols-[112px_minmax(0,1fr)]">
        <span className="text-[9px] uppercase tracking-[.1em] text-[#71837b]">Terén</span>
        {strip(null, 8)}
        {rows.map(([k, label, short]) => (
          <Fragment key={k}>
            <span className="truncate text-[10px] text-[#a9c2b9]"><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{label}</span></span>
            {strip(k, 14)}
          </Fragment>
        ))}
        <span />
        <div className="relative h-4 font-mono text-[9px] text-[#71837b]">
          {ticks.map((t, i) => (
            <span key={i} className="absolute top-0.5 whitespace-nowrap" style={{ left: `${(t / T) * 100}%`, transform: i === 0 ? "none" : t / T > 0.9 ? "translateX(-100%)" : "translateX(-50%)" }}>
              {i === 0 ? "0" : `${t / 60} min`}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-[#71837b]">
        <span><i className="mr-1 inline-block size-2 rounded-sm align-middle" style={{ background: UP }} />nad normou</span>
        <span><i className="mr-1 inline-block size-2 rounded-sm align-middle" style={{ background: DOWN }} />pod normou</span>
        <span>sytá barva = významné · bledá = v normě · tmavá = netestováno</span>
        <span className="flex gap-2">{["B1", "B2", "B3", "B4", "B5"].map((b) => <span key={b}><i className="mr-0.5 inline-block size-2 rounded-sm align-middle" style={{ background: SEG_BAND[b][1] }} />{SEG_BAND[b][0]}</span>)}</span>
      </p>

      {stretches.length > 0 && (
        <div className="mt-3">
          <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Kde se běh lišil</p>
          <ol className="mt-1.5 space-y-1">
            {stretches.slice(0, 6).map((g, i) => (
              <li key={i}>
                <button onClick={() => setSel(g.peak.idx)} className="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-xl bg-black/20 px-2.5 py-1.5 text-left hover:bg-black/30">
                  <span className="grid size-5 place-items-center rounded-full text-[10px] font-bold text-[#0c201d]" style={{ background: g.dir === "up" ? UP : DOWN }}>{g.dir === "up" ? "↑" : "↓"}</span>
                  <span className="min-w-0 text-[11px] leading-4 text-[#c9dcd4]">
                    <b className="text-[#f1f8f1]">{g.label}</b> {g.dir === "up" ? "vyšší" : "nižší"} než norma
                    <span className="block text-[10px] text-[#71837b]">{g.n === 1 ? `úsek ${g.from}` : `úseky ${g.from}–${g.to}`} · {mmss(g.t0)}–{mmss(g.t1)} · {g.bands.join(", ")}</span>
                  </span>
                  <span className="whitespace-nowrap text-right font-mono text-[11px]" style={{ color: g.dir === "up" ? UP : DOWN }}>Ø {zStr(g.meanZ)}<span className="block text-[9px] text-[#71837b]">{g.n}× významné</span></span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {cur && (
        <div className="mt-3 rounded-2xl border border-white/10 bg-black/20 p-3">
          <div className="flex items-center justify-between gap-2">
            <button onClick={() => setSel(Math.max(0, cur.idx - 1))} disabled={cur.idx === 0} aria-label="Předchozí úsek" className="grid size-7 shrink-0 place-items-center rounded-lg bg-white/5 text-[#6ce6d3] disabled:opacity-30">‹</button>
            <p className="min-w-0 text-center text-[11px] leading-4 text-[#a9c2b9]">
              <b className="text-sm text-[#f1f8f1]">Úsek {cur.idx + 1}</b> <span className="text-[#71837b]">z {run.nSeg}</span>
              <span className="block">{mmss(cur.startS)}–{mmss(cur.startS + (cur.durationS || 0))} · {SEG_BAND[cur.band]?.[0] || cur.bandLabel} ({cur.gradePct > 0 ? "+" : cur.gradePct < 0 ? "−" : ""}{mfmt(1, Math.abs(cur.gradePct))} %){cur.paceSKm ? ` · ${paceStr(cur.paceSKm)}/km` : ""}</span>
            </p>
            <button onClick={() => setSel(Math.min(run.nSeg - 1, cur.idx + 1))} disabled={cur.idx >= run.nSeg - 1} aria-label="Další úsek" className="grid size-7 shrink-0 place-items-center rounded-lg bg-white/5 text-[#6ce6d3] disabled:opacity-30">›</button>
          </div>
          {cur.findings.length ? (
            <div className="mt-2.5 space-y-1.5">
              {SEG_METRICS.map(([k, label]) => {
                const f = cur.findings.find((x: any) => x.metric === k)
                if (!f) return null
                const pos = clamp(50 + (f.z / 4) * 50, 0, 100)
                const col = f.z > 0 ? UP : DOWN
                return (
                  <div key={k} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-[11px] sm:grid-cols-[150px_minmax(0,1fr)_17rem]">
                    <span className="text-[#c9dcd4]">{label}{f.sig && <span className="ml-1.5 rounded bg-[#e77a59]/20 px-1 text-[8px] font-bold uppercase tracking-wide text-[#f6b89f]">významné</span>}</span>
                    <span className="whitespace-nowrap text-right font-mono text-[10px] text-[#a9c2b9] sm:col-start-3 sm:row-start-1">
                      <span className="hidden sm:inline"><b className="text-[#f1f8f1]">{segVal(k, f.value)}</b> <span className="text-[#71837b]">vs {segVal(k, f.base)}</span> · </span><span style={{ color: f.sig ? col : undefined }}>{zStr(f.z)}</span><span className="hidden text-[#71837b] sm:inline"> {pStr(f.p)}</span>
                    </span>
                    <span className="relative col-span-2 h-2 rounded-full bg-white/[.06] sm:col-span-1 sm:col-start-2 sm:row-start-1">
                      <span className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
                      <span className="absolute inset-y-0 rounded-full" style={{ left: `${Math.min(50, pos)}%`, width: `${Math.abs(pos - 50)}%`, background: col, opacity: f.sig ? 1 : 0.45 }} />
                    </span>
                    <span className="col-span-2 font-mono text-[10px] text-[#71837b] sm:hidden"><b className="text-[#f1f8f1]">{segVal(k, f.value)}</b> vs {segVal(k, f.base)} · {pStr(f.p)}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-[#71837b]">Tento úsek se netestoval — tempo, sklon nebo povrch byly mimo rozsah vaší normy.</p>
          )}
        </div>
      )}
      <p className="mt-2 text-[9px] leading-4 text-[#71837b]">Klepněte do pásu na libovolné místo běhu. „vs“ = hodnota, kterou vaše norma čeká přesně pro takový úsek. σ = násobek vašeho obvyklého rozptylu.</p>
    </>,
  )
}

// This run next to the comparable run from a month before: the same kind of run
// (surface · grade · pace class), dated from the same day last month up to a
// week later — never older. Missing = no such run, and nothing older is used.
function MonthCompare({ data }: { data: any }) {
  const p = data.prev
  const val = (m: any, x: number | null) =>
    x == null ? "—" : m.key === "pace_s_km" ? `${paceStr(x)}/km` : `${mfmt(m.dec, x)}${m.unit ? ` ${m.unit}` : ""}`
  const diff = (m: any) => {
    if (m.diff == null) return <span className="text-[10px] text-[#71837b]">—</span>
    if (Math.abs(m.diff) < (m.dec ? 1 / 10 ** m.dec : 1)) return <span className="text-[10px] text-[#71837b]">beze změny</span>
    const sign = m.diff > 0 ? "+" : "−"
    const txt = m.key === "pace_s_km" ? `${sign}${Math.abs(m.diff)} s/km` : `${sign}${mfmt(m.dec, Math.abs(m.diff))} ${m.unit}`
    const note = m.key === "pace_s_km" ? (m.diff > 0 ? " pomaleji" : " rychleji") : ""
    return <span className="font-mono text-[11px] text-[#c9dcd4]"><span className="whitespace-nowrap">{m.diff > 0 ? "▲" : "▼"} {txt}</span><span className="block font-sans text-[10px] text-[#71837b] sm:inline">{note}</span></span>
  }
  return (
    <div className="border-t border-white/5 px-4 py-3">
      <span className="flex items-center gap-1.5">
        <span className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Srovnání s během před měsícem</span>
        <InfoDot label="Běh před měsícem" text="Srovnatelný běh = stejný povrch, sklon i tempová skupina. Hledá se od stejného dne minulý měsíc do týdne poté — nikdy starší než měsíc. Když je jich víc, vyhraje ten nejblíž měsíční hranici (při shodě podobnější vzdálenost). Rozdíl tak ukazuje změnu vás, ne trasy." />
      </span>
      {p ? (
        <>
          <p className="mt-1.5 text-[11px] leading-5 text-[#a9c2b9]">
            <b className="text-[#f1f8f1]">{fmtD(p.date)} · {p.title || "Běh"}</b> · {mfmt(1, p.distanceKm || 0)} km{p.paceSKm ? ` · ${paceStr(p.paceSKm)}/km` : ""}
            <span className="text-[#71837b]"> — {p.daysBefore} dní před tímto během · profil {data.bucketLabel}</span>
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left font-mono text-[10px] uppercase text-[#71837b]">
                <th className="py-1 pr-3 font-normal">Metrika</th><th className="pr-3 font-normal">Tento běh</th><th className="pr-3 font-normal">Před měsícem</th><th className="font-normal">Rozdíl</th>
              </tr></thead>
              <tbody>
                {data.metrics.map((m: any) => (
                  <tr key={m.key} className="border-t border-white/5">
                    <td className="py-2 pr-3 text-[#a9c2b9]">{m.label}</td>
                    <td className="whitespace-nowrap pr-3 font-mono"><b className="text-[#f1f8f1]">{val(m, m.value)}</b></td>
                    <td className="whitespace-nowrap pr-3 font-mono text-[#a9c2b9]">{val(m, m.prev)}</td>
                    <td>{diff(m)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="mt-1.5 text-xs leading-5 text-[#71837b]">
          Mezi {fmtD(data.window.from)} a {fmtD(data.window.to)} jste neběželi žádný srovnatelný běh ({data.bucketLabel}), takže srovnání chybí. Starší běhy se schválně nepoužívají.
        </p>
      )}
    </div>
  )
}

export function Mechanics() {
  const { me, boot } = useApp()
  const rid = me?.runner_id
  const a = boot?.assessment
  const acts = (boot?.activities || []) as any[]
  const [openMetric, setOpenMetric] = useState("Vertikální poměr")
  const [terr, setTerr] = useState(false)
  const [mechHist, setMechHist] = useState<any[] | null>(null)
  const gatedNow = (a?.confidence?.value ?? 0) < 0.6
  useEffect(() => {
    if (!rid || gatedNow) return
    let alive = true
    api.mechHistory(rid).then((h) => alive && setMechHist(h)).catch(() => alive && setMechHist([]))
    return () => { alive = false }
  }, [rid, gatedNow])
  if (!a) return <LoadGate />
  if ((a.confidence?.value ?? 0) < 0.6)
    return (
      <>
        <Head kicker="Mechanika" title="Baseline se zatím buduje" sub={`Spolehlivost ${Math.round((a.confidence?.value ?? 0) * 100)} % — ${a.confidence?.sessions} tréninků ve srovnatelných podmínkách, ${a.confidence?.days} dní historie. Než tohle číslo překročí 60 %, mechanické signály se nezobrazují.`} />
        <Card><Label>Co pomůže nejrychleji</Label><p className="mt-2 text-sm text-[#64736e]">Opakovat podobné běhy — stejný povrch, podobné tempo. Baseline se počítá po skupinách povrch × sklon × tempo.</p></Card>
      </>
    )

  // engine metric → card, aligning the value series with the run dates so the
  // per-run charts can show real dates on the x-axis
  const eng = (series0: number[], field: string, label: string, unit: string, dec: number, value: number, baseline: number, z: number, delta: string, hot: boolean, position: number, terrain = true): Metric => {
    const dts = fieldDates(acts, field, (series0 || []).length)
    const n = Math.min((series0 || []).length, dts.length)
    const series = (series0 || []).slice((series0 || []).length - n)
    const seriesDates = dts.slice(dts.length - n)
    return { label, unit, dec, value, baseline, z, delta, hot, position, weeks: series.slice(-8), dates: seriesDates.slice(-8), series, seriesDates, terrain }
  }
  // The card visualizes per-run numbers (baseMean → recMean over the run series),
  // so derive its deviation, interval bar and "hot" flag from *those same* numbers
  // via one helper. The engine's own z can be a segment/terrain-cleaned z that
  // diverges from baseMean→recMean under v2 segment scoring — reusing it here made
  // the card say "baseline X → teď Y · odchylka z" with a z that didn't match X→Y.
  // The engine's authoritative z still drives the mech score + the signal list below.
  const mk = (o: any, field: string, label: string, unit: string, dec: number, terrain = true): Metric => {
    const series = (o.series || []) as number[]
    const base = o.baseMean, rec = o.recMean
    // Pair the per-run means with a per-run z. Under v2 segment scoring `o.z` is the
    // segment z (kept for the score); the engine preserves the per-run drift as
    // `perRunZ`. Prefer that; else the plain per-run `o.z`; else derive one from the
    // series so "baseline X → teď Y · odchylka z" is always internally consistent.
    const z =
      o.perRunZ != null ? o.perRunZ
        : !o.segment && o.z != null ? o.z
          : (rec - base) / (std(series) || Math.abs(base * 0.02) || 1)
    return eng(series, field, label, unit, dec, rec, base, z, `${sgn(Math.round(z * 100) / 100)} z`, Math.abs(z) >= 1, clamp(50 + z * 18, 8, 92), terrain)
  }
  const metrics: Metric[] = []
  if (a.tavr) metrics.push(mk(a.tavr, "vert_ratio_pct", "Vertikální poměr", "%", 1))
  if (a.gct) metrics.push(mk(a.gct, "gct_ms", "Kontakt se zemí", "ms", 0))
  // Balance is intentionally terrain-agnostic and carries its own excursion (p.b.),
  // not a baseMean→recMean z — keep its own mapping, just with a symmetric |·| gate.
  if (a.bal) metrics.push(eng(a.bal.series, "gct_balance_l", "Symetrie kontaktu", "%", 1, a.bal.now, a.bal.baseline, a.bal.excursion, `${sgn(a.bal.excursion)} p.b.`, Math.abs(a.bal.excursion) >= 0.8, clamp(50 + a.bal.excursion * 22, 8, 92), false))
  // Prefer the backend's per-terrain drift; fall back to a plain (approx) mean
  // only when there isn't enough bucketed data.
  const engDrift = (d: any, field: string, label: string, unit: string, dec: number): Metric | null =>
    d ? mk(d, field, label, unit, dec) : metricFromActs(acts, field, label, unit, dec)
  for (const m of [
    engDrift(a.cadence, "cadence_spm", "Kadence", "spm", 0),
    engDrift(a.stride, "stride_len_m", "Délka kroku", "m", 2),
    engDrift(a.vosc, "vert_osc_cm", "Vertikální oscilace", "cm", 1),
  ]) if (m) metrics.push(m)

  // State label follows the quadrant (post-hysteresis), so Pohyb matches the
  // kvadrant exactly — not a separate ≥25 / tavr-z cutoff that could disagree.
  const drift = a.quadrant === "silent" || a.quadrant === "critical"
  const headline = drift ? "Mechanika se mění" : a.mech >= 12 ? "Jemný drift proti normě" : "Mechanika drží na normě"
  const mechSig = ((a.signals || []) as any[]).filter((s) => ["tavr", "gct", "bal", "dec", "gaitcv", "cad", "vosc"].includes(s.id))

  // Reconcile the trend's final point with the live score so the chart's last
  // value *and* date always equal the big number / quadrant — even if this
  // history fetch predates today's recompute (e.g. a tab left open overnight).
  const asOf = (a.computed_at || "").slice(0, 10)
  const mechPoints = (mechHist || []).map((h) => ({ t: h.date, v: h.mech }))
  if (mechPoints.length) mechPoints[mechPoints.length - 1] = { t: asOf || mechPoints[mechPoints.length - 1].t, v: a.mech ?? mechPoints[mechPoints.length - 1].v }

  return (
    <>
      <section className="overflow-hidden rounded-[28px] border border-[#6ce6d3]/20 bg-[#102724] p-5 md:p-7">
        <div className="grid gap-7 lg:grid-cols-[.9fr_1.1fr] lg:items-center">
          <div>
            <Label>Signál pohybu</Label>
            <h2 className="mt-2 font-serif text-3xl leading-tight text-[#f1f8f1]">{headline}</h2>
            <p className="mt-3 max-w-sm text-sm leading-6 text-[#a9c2b9]">
              {drift ? "Při stejném tempu se krok mírně prodlužuje a kontakt se zemí narůstá. Není to alarm, ale dobrý okamžik ubrat tlak." : "Ve srovnatelných podmínkách se vaše mechanika drží ve vlastním obvyklém rozsahu."}
            </p>
            <div className={`mt-5 inline-flex items-center gap-2 rounded-full px-3 py-2 text-[10px] font-bold ${drift ? "bg-[#e77a59]/12 text-[#ffc1ab]" : "bg-[#c7ff54]/12 text-[#c7ff54]"}`}>
              <i className={`size-2 rounded-full ${drift ? "bg-[#e77a59]" : "bg-[#c7ff54]"}`} />
              {drift ? "vyšší než váš obvyklý střed" : "v rámci obvyklého středu"}
            </div>
            {mechSig.length > 0 && (
              <div className="mt-4 border-t border-white/10 pt-3">
                <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Co tvoří skóre mechaniky</p>
                <div className="mt-2 space-y-1.5">
                  {mechSig.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 text-[12px]">
                      <span className="flex-1 truncate text-[#e7efe9]">{s.name}</span>
                      <span className="font-mono text-[#9bb3aa]">{s.val}</span>
                      <span className="font-mono text-[#6ce6d3]">+{s.pts}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="rounded-[22px] border border-white/10 bg-[#0c201d] p-5">
            <div className="flex items-center justify-between">
              <Label>Mechanická stabilita — trend</Label>
              <span className="font-mono text-[10px] text-[#71837b]">skóre driftu 0–100</span>
            </div>
            <div className="mt-2 flex items-end gap-2">
              <b className="font-serif text-4xl text-[#f1f8f1]">{a.mech}</b>
              <small className="pb-1 text-xs text-[#9bb3aa]">/ 100 · {drift ? "drift" : "stabilní"}</small>
            </div>
            {mechHist === null ? (
              <p className="mt-3 text-sm text-[#71837b]">Počítám trend v čase…</p>
            ) : mechHist.length > 1 ? (
              <AxisLineChart points={mechPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh driftu" color={drift ? "#e77a59" : "#6ce6d3"} height={140} />
            ) : (
              <p className="mt-3 text-sm text-[#71837b]">Na trend v čase je zatím málo historie.</p>
            )}
            <p className="mt-1 text-[10px] text-[#71837b]">skóre driftu mechaniky po týdnech · nad prahem 25 = drift</p>
          </div>
        </div>
      </section>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-full border border-white/10 bg-[#0c201d] p-1 text-xs font-semibold">
          {([["all", "Všechen terén"], ["terr", "Podle profilu terénu"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTerr(k === "terr")} className={`rounded-full px-4 py-1.5 transition ${(terr ? "terr" : "all") === k ? "bg-[#6ce6d3] text-[#071313]" : "text-[#9bb3aa] hover:text-[#f1f8f1]"}`}>{l}</button>
          ))}
        </div>
        <span className="font-mono text-[10px] text-[#71837b]">{terr ? "srovnání metrik napříč profily terénu" : "každá metrika proti vaší celkové normě"}</span>
      </div>

      {terr ? (
        <div className="mt-4"><TerrainMatrix acts={acts} /></div>
      ) : (
        <div className="mt-4 space-y-4">
          {metrics.map((m) => {
            const isOpen = openMetric === m.label
            return (
              <div key={m.label} className={`overflow-hidden rounded-[22px] border transition ${isOpen ? "border-[#6ce6d3]/60 bg-[#17382f]" : "border-white/10 bg-[#0c201d] hover:border-[#6ce6d3]/30"}`}>
                <MechMetricCard m={m} onSelect={() => setOpenMetric(isOpen ? "" : m.label)} />
                {isOpen && (
                  <div className="origin-top animate-[careReveal_.28s_ease-out] border-t border-white/10 px-4 py-4">
                    <p className="text-sm text-[#a9c2b9]">Baseline <b className="text-[#f1f8f1]">{mfmt(m.dec, m.baseline)} {m.unit}</b> → teď <b className="text-[#f1f8f1]">{mfmt(m.dec, m.value)} {m.unit}</b> · odchylka {sgn(Math.round(m.z * 100) / 100)}. {m.terrain !== false ? "Porovnává se jen ve stejném profilu terénu a tempa." : "Průměr proti vašemu dřívějšímu období (napříč terénem — málo dat na terénní očištění)."}</p>
                    {m.series.length > 1 && (
                      <div className="mt-3">
                        <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Celý trend · {m.series.length} běhů{m.seriesDates.length ? ` · ${fmtD(m.seriesDates[0])} → ${fmtD(m.seriesDates.at(-1)!)}` : ""}</p>
                        <AxisLineChart points={m.series.map((v, i) => ({ t: m.seriesDates[i] || m.seriesDates.at(-1) || "", v }))} dec={m.dec} unit={` ${m.unit}`} color="#c7ff54" height={150}
                          band={{ lo: usualRange(m).lo, hi: usualRange(m).hi, mid: m.baseline, label: "vaše obvyklé rozmezí" }} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      <RunHistoryReal acts={acts} />
    </>
  )
}

/* ============================ ZÁTĚŽ ============================ */
const LOAD_IDS = new Set([
  // v0.6 spine
  "session_spike", "spike_latent", "pace_spike", "load_capacity",
  // grade-C ACWR context + the rest of the load axis
  "ewma", "hi_load", "load_creep", "mono", "desc", "desc_steep", "aer", "hrv", "rhr", "hrvcv", "tsb", "taper",
  // engine v3 — load against the runner's own capacity, per channel
  ...CAP_SIGNAL_IDS,
])
export function Load() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const a = boot?.assessment
  const L = a?.loadDetail
  const rcv = a?.rcv
  const dm = (boot?.daily_metrics || []) as any[]
  const [edit, setEdit] = useState<{ date: string; field: string; val: number } | null>(null)
  const [hist, setHist] = useState<any[] | null>(null)
  useEffect(() => {
    if (!rid) return
    let alive = true
    api.mechHistory(rid).then((h) => alive && setHist(h)).catch(() => alive && setHist([]))
    return () => { alive = false }
  }, [rid])
  if (!L) return <LoadGate />

  // State follows the quadrant (post-hysteresis) so Zátěž matches it exactly.
  const loadHot = a.quadrant === "overreaching" || a.quadrant === "critical"
  const loadHeadline = loadHot ? "Zátěž je zvýšená" : (a.load ?? 0) >= 12 ? "Zátěž roste" : "Zátěž drží v normě"
  const loadDesc = loadHot
    ? "Akutní zátěž a související signály se zvedají nad vaši obvyklou úroveň — dobrý čas ubrat a hlídat regeneraci."
    : "Objem, intenzita, monotónnost i regenerace sedí na vaší obvyklé úrovni."
  const loadSig = ((a.signals || []) as any[]).filter((s) => LOAD_IDS.has(s.id))
  const capVol = a.capacity?.channels?.volume

  // Same reconciliation as Pohyb: pin the trend's final point to the live load
  // score + date so the chart end always equals the big number / quadrant.
  const loadAsOf = (a.computed_at || "").slice(0, 10)
  const loadPoints = (hist || []).map((h) => ({ t: h.date, v: h.load }))
  if (loadPoints.length) loadPoints[loadPoints.length - 1] = { t: loadAsOf || loadPoints[loadPoints.length - 1].t, v: a.load ?? loadPoints[loadPoints.length - 1].v }

  return (
    <>
      {edit && <EditDailySheet rid={rid} row={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); refresh() }} />}

      <section className="mb-4 overflow-hidden rounded-[28px] border border-[#f6d69a]/20 bg-[#102724] p-5 md:p-7">
        <div className="grid gap-7 lg:grid-cols-[.9fr_1.1fr] lg:items-center">
          <div>
            <Label>Signál zátěže</Label>
            <h2 className="mt-2 font-serif text-3xl leading-tight text-[#f1f8f1]">{loadHeadline}</h2>
            <p className="mt-3 max-w-sm text-sm leading-6 text-[#a9c2b9]">{loadDesc}</p>
            <div className={`mt-5 inline-flex items-center gap-2 rounded-full px-3 py-2 text-[10px] font-bold ${loadHot ? "bg-[#e77a59]/12 text-[#ffc1ab]" : "bg-[#c7ff54]/12 text-[#c7ff54]"}`}>
              <i className={`size-2 rounded-full ${loadHot ? "bg-[#e77a59]" : "bg-[#c7ff54]"}`} />
              {loadHot ? "nad obvyklou úrovní" : "v obvyklém rozsahu"}
            </div>
            {loadSig.length > 0 && (
              <div className="mt-4 border-t border-white/10 pt-3">
                <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Co tvoří skóre zátěže</p>
                <div className="mt-2 space-y-1.5">
                  {loadSig.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 text-[12px]">
                      <span className="flex-1 truncate text-[#e7efe9]">{s.name}</span>
                      <span className="font-mono text-[#9bb3aa]">{s.val}</span>
                      <span className="font-mono text-[#f6d69a]">+{s.pts}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(capVol?.ceilingToday != null || L?.safeLongRunKm) && (
              <div className="mt-4 flex items-center gap-2 rounded-xl bg-white/[.04] px-3 py-2.5">
                <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-[#17382f] text-[#6ce6d3]">⤢</span>
                <p className="text-[11px] leading-4 text-[#a9c2b9]">
                  Bezpečný nejdelší běh dnes: <b className="text-[#f1f8f1]">≈ {(capVol?.ceilingToday ?? L.safeLongRunKm).toLocaleString("cs-CZ")} km</b>
                  <span className="block text-[10px] text-[#71837b]">
                    {capVol?.ceilingToday != null
                      ? "vaše prokázaná kapacita + 10 %, snížená podle dnešní připravenosti"
                      : "≈ +10 % nad váš nejdelší běh 30 dní · nad +100 % prudce roste riziko"}
                  </span>
                </p>
              </div>
            )}
          </div>
          <div className="rounded-[22px] border border-white/10 bg-[#0c201d] p-5">
            <div className="flex items-center justify-between">
              <Label>Skóre zátěže — trend</Label>
              <span className="font-mono text-[10px] text-[#71837b]">0–100</span>
            </div>
            <div className="mt-2 flex items-end gap-2">
              <b className="font-serif text-4xl text-[#f1f8f1]">{a.load}</b>
              <small className="pb-1 text-xs text-[#9bb3aa]">/ 100 · {loadHot ? "zvýšená" : "v normě"}</small>
            </div>
            {hist === null ? (
              <p className="mt-3 text-sm text-[#71837b]">Počítám trend v čase…</p>
            ) : hist.length > 1 ? (
              <AxisLineChart points={loadPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh" color={loadHot ? "#e77a59" : "#f6d69a"} height={140} />
            ) : (
              <p className="mt-3 text-sm text-[#71837b]">Na trend je zatím málo historie.</p>
            )}
            <p className="mt-1 text-[10px] text-[#71837b]">skóre zátěže po týdnech · nad prahem 25 = zvýšená (vstupuje do kvadrantu)</p>
          </div>
        </div>
      </section>

      {a.capacity && <CapacityPanel cap={a.capacity} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Metric warm label="Zátěž 7 dní" value={`${L.acute}`} caption={`chronicky ${L.chronic} · j.z./týden`} info={MI.acute7} />
        <Metric label="Poměr 7:28" value={L.valid ? `×${L.ratio}` : "—"} caption={L.valid ? "vč. jiného sportu" : "zatím málo dat"} info={MI.ratio728} />
        <Metric label="Vysoká intenzita" value={L.valid && L.hiChronic ? `×${L.hiRatio}` : "—"} caption={L.valid && L.hiChronic ? `tvrdé běhy ${L.hiAcute}/${L.hiChronic}` : "žádné tvrdé běhy"} info={MI.hiIntensity} />
        <Metric label="Monotónnost" value={`${L.monotony}`} caption={`strain ${L.strain}`} info={MI.monotony} />
        <Metric label="Klesání 7 dní" value={`${L.descent7}`} caption={`obvykle ${L.descentBase} m${L.descentSpike ? ` · ×${L.descentSpike}` : ""}`} info={MI.descent7} />
        {L.gradeAdjKm7 != null && <Metric label="Efektivní km" value={`${L.gradeAdjKm7}`} caption={`plochý ekvivalent · reálně ${L.runKm7} km`} info={MI.gradeAdj} />}
        {L.downhillKm7 != null && <Metric label="Sbíhání" value={`${L.downhillKm7} km`} caption="v klesání ≥ 5 %" info={MI.downhill} />}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <Label>Týdenní objem běhu (Po–Ne), 12 týdnů</Label>
          <Bars vals={L.weekly || []} />
          <p className="mt-2 text-xs text-[#71837b]">Tento týden (Po–Ne) <b className="text-[#f1f8f1]">{L.weekKm ?? "—"} km</b> · posledních 7 dní <b className="text-[#f1f8f1]">{L.runKm7 ?? "—"} km</b></p>
        </Card>
        <Card><Label>Denní objem běhu, 28 dní</Label><Bars vals={L.daily || []} /></Card>
      </div>
      <CrossTrainingCard L={L} />
      {a?.gradientDescent?.buckets?.some((v: number) => v > 0) && (
        <Card className="mt-4">
          <Label>Klesání za 7 dní podle sklonu</Label>
          <Bars vals={a.gradientDescent.buckets} unit="m" labels={a.gradientDescent.labels} />
          <p className="mt-2 text-xs text-[#71837b]">{a.gradientDescent.total7} m celkem · {a.gradientDescent.steep7} m na sklonu ≥10 %.</p>
        </Card>
      )}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {rcv ? (
          <>
            <Card><span className="flex items-center gap-1.5"><Label>HRV 7 dní</Label><InfoDot text={MI.hrv} label="HRV 7 dní" /></span><p className="mt-2 font-serif text-3xl">{rcv.hrv.now}<small className="text-sm"> ms</small></p><p className="text-xs text-[#71837b]">baseline {rcv.hrv.base} ms · z {sgn(rcv.hrv.z)}</p><div className="mt-3"><Sparkline vals={rcv.hrv.series} color={rcv.hrv.z <= -1 ? "#e77a59" : "#6ce6d3"} /></div></Card>
            <Card><span className="flex items-center gap-1.5"><Label>Klidový tep</Label><InfoDot text={MI.rhr} label="Klidový tep" /></span><p className="mt-2 font-serif text-3xl">{rcv.rhr.now}</p><p className="text-xs text-[#71837b]">baseline {rcv.rhr.base} · z {sgn(rcv.rhr.z)}</p><div className="mt-3"><Sparkline vals={rcv.rhr.series} color={rcv.rhr.z >= 1.2 ? "#e77a59" : "#6ce6d3"} /></div></Card>
            <Card><span className="flex items-center gap-1.5"><Label>Spánek</Label><InfoDot text={MI.sleep} label="Spánek" /></span><p className="mt-2 font-serif text-3xl">{rcv.sleep.now}<small className="text-sm"> h</small></p><p className="text-xs text-[#71837b]">obvykle {rcv.sleep.base} h{rcv.sleep.debt > 0 ? ` · dluh ${rcv.sleep.debt} h/týd` : ""}</p><div className="mt-3"><Sparkline vals={rcv.sleep.series} color={rcv.sleep.debt >= 4 ? "#e77a59" : "#6ce6d3"} /></div></Card>
            {a.sleepEff && (
              <Card><Label>Efektivita spánku</Label><p className="mt-2 font-serif text-3xl" style={{ color: a.sleepEff.now < 0.85 ? "#e77a59" : undefined }}>{Math.round(a.sleepEff.now * 100)}<small className="text-sm"> %</small></p><p className="text-xs text-[#71837b]">{a.sleepEff.base ? `obvykle ${Math.round(a.sleepEff.base * 100)} %` : "prospáno z času v posteli"} · pod 85 % = roztříštěný</p></Card>
            )}
          </>
        ) : (
          <Card className="md:col-span-3"><Empty>Chybí souvislá data z hodinek za posledních 35 dní.</Empty></Card>
        )}
      </div>
      <Card className="mt-4">
        <Label>Data z hodinek · klepnutím opravíte</Label>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left font-mono text-[10px] uppercase text-[#71837b]"><th className="py-1">Datum</th><th>Spánek</th><th>HRV</th><th>Klid. tep</th><th>Zdroj</th></tr></thead>
            <tbody>{dm.slice().reverse().slice(0, 14).map((d) => (
              <tr key={d.date} className="border-t border-white/5">
                <td className="py-2 font-mono text-xs">{fmtD(d.date)}</td>
                <td><button onClick={() => setEdit({ date: d.date, field: "sleep_h", val: d.sleep_h })} className="font-mono text-[#6ce6d3]">{d.sleep_h} h</button></td>
                <td><button onClick={() => setEdit({ date: d.date, field: "hrv_ms", val: d.hrv_ms })} className="font-mono text-[#6ce6d3]">{d.hrv_ms} ms</button></td>
                <td><button onClick={() => setEdit({ date: d.date, field: "resting_hr", val: d.resting_hr })} className="font-mono text-[#6ce6d3]">{d.resting_hr}</button></td>
                <td>{d.source === "manual" ? <Chip tone="watch">ručně</Chip> : <Chip>hodinky</Chip>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

const SPORT_ICON: Record<string, string> = { cycling: "🚴", swimming: "🏊", strength: "🏋", rowing: "🚣", elliptical: "🌀", hiking: "🥾", walking: "🚶", other: "•" }

function CrossTrainingCard({ L }: { L: any }) {
  const list = (L.crossList || []) as any[]
  const run = L.runLoad7 || 0
  const cross = L.crossLoad7 || 0
  if (!list.length) {
    return <p className="mt-4 text-xs text-[#71837b]">Tento týden jen běh. Kolo, plavání nebo silovku z hodinek automaticky započítáme do zátěže jako tréninkovou zátěž (jednotky zátěže) — ovlivní poměr 7:28 dní i monotónnost, stejně jako běh.</p>
  }
  const tot = run + cross || 1
  const runPct = Math.round((run / tot) * 100)
  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between">
        <Label>Křížový trénink (7 dní)</Label>
        <span className="font-mono text-[10px] text-[#71837b]">započítáno do zátěže · j.z.</span>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-1">
        <p className="font-serif text-3xl text-[#c7ff54]">{L.runLoad7}<small className="text-sm text-[#71837b]"> běh</small></p>
        <span className="pb-2 text-lg text-[#71837b]">+</span>
        <p className="font-serif text-3xl text-[#6ce6d3]">{L.crossLoad7}<small className="text-sm text-[#71837b]"> jiný sport</small></p>
        <span className="pb-1 text-xs text-[#71837b]">j.z. za 7 dní · {L.crossCount7} {L.crossCount7 === 1 ? "aktivita" : L.crossCount7 < 5 ? "aktivity" : "aktivit"}</span>
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-white/10" title={`běh ${run} · jiný sport ${cross} j.z.`}>
        <i style={{ width: `${runPct}%` }} className="bg-[#c7ff54]" />
        <i style={{ width: `${100 - runPct}%` }} className="bg-[#6ce6d3]" />
      </div>
      <div className="mt-4 divide-y divide-white/10">
        {list.map((c, i) => (
          <div key={i} className="flex items-center gap-3 py-2.5 text-sm">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#17382f] text-base">{SPORT_ICON[c.sport] || "•"}</span>
            <span className="min-w-0 flex-1">
              <b className="text-[#f1f8f1]">{c.sportLabel}</b>
              <em className="block truncate text-xs not-italic text-[#71837b]">{fmtD(c.date)} · {c.durationMin} min{c.avgHr ? ` · ⌀ ${c.avgHr} tep` : ""}</em>
            </span>
            <span className="font-mono text-sm text-[#6ce6d3]">{c.load} j.z.</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs leading-5 text-[#71837b]">Neběžecké sporty nepočítáme do běžeckých kilometrů ani do mechaniky, ale přispívají do celkové tréninkové zátěže (poměr 7:28 dní, monotónnost) i únavy — proto je vidíte tady. Zátěž se počítá z tepové odezvy (TRIMP), takže je porovnatelná napříč sporty.</p>
    </Card>
  )
}

function EditDailySheet({ rid, row, onClose, onDone }: { rid: string; row: { date: string; field: string; val: number }; onClose: () => void; onDone: () => void }) {
  const LBL: any = { sleep_h: ["Spánek", "h"], hrv_ms: ["HRV", "ms"], resting_hr: ["Klidový tep", "tep/min"] }
  const [val, setVal] = useState(String(row.val ?? ""))
  const [note, setNote] = useState("")
  const { busy, err, run } = useAsync()
  const toast = useToast()
  const [lab, unit] = LBL[row.field]
  return (
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">Opravit: {lab}</h2>
      <p className="mt-1 text-xs text-[#a9c2b9]">{fmtD(row.date)} · hodinky naměřily {row.val} {unit}.</p>
      <Field label={`Skutečná hodnota (${unit})`}><input type="number" step="0.1" value={val} onChange={(e) => setVal(e.target.value)} className="w-full rounded-xl border px-3 py-2 text-sm" /></Field>
      <Field label="Proč opravujete" hint="uvidí fyzioterapeut"><input value={note} onChange={(e) => setNote(e.target.value)} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="např. hodinky nezachytily usnutí" /></Field>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
      <div className="mt-5 flex gap-2">
        <button disabled={busy} onClick={() => run(async () => { await api.editDaily(rid, row.date, { [row.field]: Number(val) }, note || undefined); toast({ title: "Hodnota přepsána, skóre přepočítáno" }); onDone() })} className="flex-1 rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">Uložit a přepočítat</button>
        <button onClick={onClose} className="rounded-full border border-white/15 px-5 py-3 text-sm font-bold text-[#a9c2b9]">Zrušit</button>
      </div>
    </Sheet>
  )
}

/* ============================ PROGRAM ============================ */
export function Program() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const p = boot?.program
  const nav = () => (location.hash = "")
  const toast = useToast()
  if (!p)
    return (
      <>
        <Head kicker="Program" title="Zatím vám nikdo program neposlal" sub="Program vzniká na straně fyzioterapeuta poté, co převezme váš případ. Objeví se tady i s pokyny u jednotlivých cviků." />
        <Card><Empty>Žádný aktivní program.</Empty></Card>
      </>
    )
  const ex = (p.exercises || []) as any[]
  const adh = ex.length ? Math.round((ex.reduce((s, e) => s + (e.done_count || 0) / (e.target_count || 12), 0) / ex.length) * 100) : 0
  return (
    <>
      <Head kicker={`${PHASE[p.phase] || p.phase} · ${p.weeks} týdny`} title={p.name} sub={`Vede ${boot?.physios?.[p.physio_id]?.name || "—"}. Odesláno ${fmtD(p.sent_at || p.started_on)}.`} />
      <div className="grid gap-4 lg:grid-cols-[1.5fr_.8fr]">
        <Card>
          <div className="flex items-center justify-between"><Label>Cviky</Label><Chip tone={adh >= 60 ? "ok" : "watch"}>{adh} % splněno</Chip></div>
          <div className="mt-3 divide-y divide-white/10">
            {ex.map((e) => (
              <div key={e.id} className="flex items-center gap-3 py-3">
                <div className="flex-1">
                  <b className="text-sm">{e.name}</b>
                  <em className="block text-xs not-italic text-[#71837b]">{e.dose} · {e.per_week}× týdně — {e.cue}</em>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/10"><i className="block h-full rounded-full bg-[#c7ff54]" style={{ width: `${Math.round(((e.done_count || 0) / (e.target_count || 12)) * 100)}%` }} /></div>
                </div>
                <span className="font-mono text-xs text-[#a9c2b9]">{e.done_count}/{e.target_count}</span>
                <button onClick={async () => { await api.logEx(rid, e.id); toast({ title: "Zapsáno" }); refresh() }} className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-bold text-[#c7ff54]">Hotovo</button>
              </div>
            ))}
          </div>
        </Card>
        <div className="grid gap-4">
          <Card><Label>Jak to funguje</Label><p className="mt-2 text-sm text-[#64736e]">Cíl je 12 opakování každého cviku za 4 týdny. Když cvik provokuje bolest nad 3/10, je to informace pro fyzioterapeuta, ne důvod ho zatnout zuby dodělat.</p></Card>
          {(p.revisions || []).length > 0 && (
            <Card><Label>Změny v programu</Label><div className="mt-2 space-y-3">{p.revisions.slice().reverse().map((rv: any) => (
              <div key={rv.id}><b className="text-sm">{fmtD(rv.at)}</b><p className="text-xs text-[#71837b]">{rv.note}</p>{(rv.changes || []).map((c: string, i: number) => <div key={i} className="mt-1"><Chip>{c}</Chip></div>)}</div>
            ))}</div></Card>
          )}
        </div>
      </div>
    </>
  )
}

// (Removed the unreachable `Messages` chat tab: the "messages" route renders
// <Care/>, whose PhysioChat is the live physio conversation. The old standalone
// Messages component had no import or route and only risked drifting out of sync.)
