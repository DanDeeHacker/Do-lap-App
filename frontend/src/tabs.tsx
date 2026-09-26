import { Fragment, useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { AlertBanner, AxisLineChart, Bars, Button, Card, Chip, Empty as UiEmpty, FactorBar, toneCol, type Tone, Field, InfoDot, Label, ListRow, Metric, Ring, Segmented, Sheet, Slider, Sparkline, useAsync, useToast } from "@/ui"
import { Activity as ActivityIcon, Bike, ChevronDown, ChevronLeft, ChevronRight, CloudSun, Dumbbell, FileText, Footprints, Gauge, History, LoaderCircle, Mountain, Orbit, Ship, Waves, type LucideIcon } from "lucide-react"
import { Link } from "react-router"
import { METRIC_INFO as MI, MECH_INFO_BY_LABEL } from "@/metricinfo"
import { clamp, czk, FEEL_LABEL, fmtD, fmtSlot, paceStr, PHASE, plural, QUAD, sgn } from "@/lib"
import MuscleAnatomy, { PainHeatmap, type BodyPoint } from "@/components/MuscleAnatomy"
import { CAP_SIGNAL_IDS, CapacityPanel } from "@/capacity"
import { C } from "@/tokens"

const surf = (s?: string) => ({ road: "silnice", trail: "terén", treadmill: "pás", track: "dráha" } as any)[s || ""] || s || "—"
const dayAgo = (n: number) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10)

export function Head({ kicker, title, sub }: { kicker: string; title: string; sub?: string }) {
  return (
    <div className="mb-6">
      <Label>{kicker}</Label>
      <h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">{title}</h1>
      {sub && <p className="mt-3 max-w-2xl text-sm leading-6 text-fg-2">{sub}</p>}
    </div>
  )
}
function Empty({ children }: { children: any }) {
  return <UiEmpty icon={FileText}>{children}</UiEmpty>
}

// A page gate that tells "still loading" apart from "the fetch failed". Without
// this a failed bootstrap keeps rendering "Načítám…" forever, since boot stays
// null. Surfaces store.error and offers a retry.
function LoadGate({ label = "Načítám…" }: { label?: string }) {
  const { error, refresh } = useApp()
  if (!error) return <UiEmpty icon={LoaderCircle}>{label}</UiEmpty>
  return (
    <AlertBanner tone="alert" title="Data se nepodařilo načíst" action={<Button size="sm" onClick={() => refresh()}>Zkusit znovu</Button>}>
      {error}
    </AlertBanner>
  )
}

/* ============================ DENÍK ============================ */
export function Post() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const [rate, setRate] = useState<{ act: any; initial?: any } | null>(null)
  const [insOpen, setInsOpen] = useState(false)
  const fb = (boot?.activity_feedback || []) as any[]
  const acts = (boot?.activities || []) as any[]
  const cutoff = dayAgo(14)
  const rated = new Set(fb.map((f) => f.activity_id))
  const unrated = acts.filter((a) => a.started_at > cutoff && !rated.has(a.id) && !a.excluded)
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
        title={unrated.length ? `${unrated.length} ${plural(unrated.length, "běh čeká", "běhy čekají", "běhů čeká")} na zápis` : "Deník máte kompletní"}
      />
      {rate && <RateSheet act={rate.act} initial={rate.initial} rid={rid} onClose={() => setRate(null)} onDone={() => { setRate(null); refresh() }} />}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_.8fr]">
        <div className="grid content-start gap-4">
          <Card>
            <Label>Čeká na zápis</Label>
            {unrated.length ? (
              <div className="mt-2 divide-y divide-white/[.07]">
                {unrated.map((x) => (
                  <ListRow key={x.id} onClick={() => setRate({ act: x })} icon={x.surface === "trail" ? Mountain : Footprints} tone="info"
                    title={`${x.title} · ${x.distance_km} km`}
                    meta={`${fmtD(x.started_at)} · ${surf(x.surface)} · ${paceStr(x.pace_s_km)}/km · ${x.descent_m} m klesání`}
                    trailing={<span className="btn btn-primary btn-sm shrink-0">Zapsat</span>} />
                ))}
              </div>
            ) : (
              <div className="mt-3"><Empty>Nic nečeká. Další zápis se objeví po příštím běhu.</Empty></div>
            )}
          </Card>
          <Card>
            <div className="flex items-center justify-between">
              <Label>Poslední zápisy</Label>
              {fb.length > 0 && <span className="text-[12px] text-fg-3">klepnutím upravíte</span>}
            </div>
            {sorted.length ? (
              <div className="mt-2 divide-y divide-white/[.07]">
                {sorted.slice(0, 10).map((f) => {
                  const act = actById.get(f.activity_id)
                  const hurt = f.pain_during >= 4
                  return (
                    <div key={f.id} className="flex items-center gap-1">
                      <ListRow onClick={() => editEntry(f)} icon={act?.surface === "trail" ? Mountain : Footprints} tone={hurt ? "alert" : "ok"}
                        title={act ? `${act.title} · ${act.distance_km} km` : "Běh"}
                        meta={<>{fmtD(f.submitted_at)}{act?.surface ? ` · ${surf(act.surface)}` : ""} · pocit {FEEL_LABEL[f.feeling] || "—"} · nohy {f.legs}/5{f.pain_during > 0 ? ` · bolest ${f.pain_during}/10` : ""}</>}
                        extra={f.pain_site ? <span className="mt-1.5 block sm:hidden"><Chip tone="alert">{f.pain_site}</Chip></span> : undefined}
                        trailing={<>
                          {f.pain_site && <span className="hidden shrink-0 sm:block"><Chip tone="alert">{f.pain_site}</Chip></span>}
                          <span className="flex shrink-0 items-center gap-1 text-[12px] font-bold text-fg-3 transition group-hover:text-info">
                            <span className="hidden opacity-0 transition group-hover:opacity-100 md:inline">Upravit</span>
                            <ChevronRight className="size-4" aria-hidden />
                          </span>
                        </>} />
                      {act && (
                        <Link to={`/app/post/${act.id}`} aria-label="Detail běhu" title="Detail běhu"
                          className="grid size-9 shrink-0 place-items-center rounded-full text-fg-3 hover:bg-info/10 hover:text-info">
                          <ActivityIcon className="size-4" aria-hidden />
                        </Link>
                      )}
                    </div>
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
              <span className="text-[12px] text-fg-3">samostatně od běhů</span>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-fg-3">Váš self-report mimo konkrétní běh — denní pocit/bolest a týdenní kontrola (OSTRC). Přidáte je přes tlačítko Check-in.</p>
            {checkinItems.length ? (
              <div className="mt-2 divide-y divide-white/[.07]">
                {checkinItems.slice(0, 10).map((x: any) => {
                  const daily = x.kind === "daily"
                  const hurt = daily ? (x.pain || 0) >= 4 : (x.severity || 0) >= 40
                  return (
                    <ListRow key={x.id} tileText={daily ? "DEN" : "TÝD"} tone={daily ? "info" : "self"}
                      title={daily ? "Denní check-in" : x.adhoc ? "Týdenní check-in · mimořádný" : "Týdenní check-in"}
                      meta={<>{fmtD(x.at)}{daily
                        ? `${x.pain != null ? ` · bolest ${x.pain}/10` : ""}${x.mood != null ? ` · nálada ${x.mood}/4` : ""}${x.fatigue != null ? ` · únava ${x.fatigue}` : ""}`
                        : ` · OSTRC ${x.severity ?? 0}/100 · ${x.status === "active" ? "aktivní" : x.status === "resolved" ? "odezněl" : "bez potíží"}`}</>}
                      extra={x.regions.length > 0 ? <span className="mt-1.5 block sm:hidden"><Chip tone={hurt ? "alert" : "muted"}>{x.regions.slice(0, 2).join(", ")}{x.regions.length > 2 ? "…" : ""}</Chip></span> : undefined}
                      trailing={x.regions.length > 0 ? <span className="hidden shrink-0 sm:block"><Chip tone={hurt ? "alert" : "muted"}>{x.regions.slice(0, 2).join(", ")}{x.regions.length > 2 ? "…" : ""}</Chip></span> : undefined} />
                  )
                })}
              </div>
            ) : (
              <div className="mt-3"><Empty>Zatím žádné check-iny. Přidejte první přes tlačítko Check-in vpravo dole.</Empty></div>
            )}
          </Card>
        </div>
        <div className="grid content-start gap-4">
          {/* feedback railway#44/#45 — one summary box: diary (with the reading behind a
              detail toggle) and the check-in summary under it, for comparison */}
          <Card>
            <Label>Souhrn deníku</Label>
            {ov ? (
              <>
                <div className="mt-3 flex items-baseline gap-2">
                  <p className="t-num text-[44px] leading-none">{mfmt(1, ov.feelingMean)}</p>
                  <span className="text-sm text-fg-3">/5 pocit</span>
                  {ov.feelingTrend !== 0 && <span className="ml-auto rounded-full px-2.5 py-1 tabular-nums text-[12px] font-bold" style={{ color: ov.feelingTrend > 0 ? C.ok : C.alert, background: `${ov.feelingTrend > 0 ? C.ok : C.alert}1f` }}>{sgn(ov.feelingTrend)} trend</span>}
                </div>
                <p className="mt-1.5 text-[12px] text-fg-3">{ov.n} {plural(ov.n, "zápis", "zápisy", "zápisů")} · nohy v průměru {mfmt(1, ov.legsMean)}/5</p>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div className="nest px-2 py-3"><p className="t-num text-[22px]">{ov.n21}</p><p className="text-[11px] text-fg-3">za 21 dní</p></div>
                  <div className="nest px-2 py-3"><p className="t-num text-[22px]" style={{ color: ov.niggleCount >= 3 ? C.alert : undefined }}>{ov.niggleCount}×</p><p className="text-[11px] text-fg-3">s bolestí</p></div>
                  <div className="nest px-2 py-3"><p className="t-num text-[22px]" style={{ color: ov.painMax >= 4 ? C.alert : undefined }}>{ov.painMax}</p><p className="text-[11px] text-fg-3">max bolest</p></div>
                </div>
                {Object.keys(ov.painMap).length > 0 && (
                  <div className="mt-4 border-t border-white/[.08] pt-4">
                    <Label>Kde to nejčastěji bolí</Label>
                    <p className="mt-1 text-[12px] leading-5 text-fg-3">Podle zápisů za posledních 30 dní — čím výraznější místo, tím častěji jste ho označil jako bolestivé.</p>
                    <div className="mt-3"><PainHeatmap counts={ov.painMap} /></div>
                    <div className="mt-4 space-y-1.5">
                      {ov.topSites.slice(0, 5).map(([region, count]) => {
                        const w = Math.round((count / ov.topSites[0][1]) * 100)
                        return (
                          <div key={region} className="flex items-center gap-2 text-[12px]">
                            <span className="w-32 shrink-0 truncate text-fg-soft">{region}</span>
                            <div className="h-1.5 flex-1 rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-alert" style={{ width: `${w}%` }} /></div>
                            <span className="tabular-nums text-fg-2">{count}×</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
                <button type="button" onClick={() => setInsOpen((v) => !v)} aria-expanded={insOpen}
                  className="nest mt-4 flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left transition hover:border-white/20">
                  <span className="t-label">Co z toho čteme</span>
                  <ChevronDown className={`size-4 text-fg-3 transition ${insOpen ? "rotate-180 text-accent" : ""}`} aria-hidden />
                </button>
                {insOpen && (
                  <ul className="mt-3 origin-top animate-[careReveal_.28s_ease-out] space-y-2.5">
                    {ov.insights.map((t, i) => (
                      <li key={i} className="flex gap-2.5 text-sm leading-5">
                        <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: t.tone === "alert" ? C.alert : t.tone === "watch" ? C.watch : C.ok }} />
                        <span className="text-fg-soft">{t.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <div className="mt-3"><Empty>Zatím málo zápisů na to, aby z nich šel číst vzorec. Užitečné to začne být zhruba od čtvrtého.</Empty></div>
            )}
            {ciSum && (
              <div className="mt-5 border-t border-white/[.08] pt-4">
                <Label>Souhrn check-inů</Label>
                <p className="mt-1 text-[12px] text-fg-3">Odděleně od běhů · poslední {fmtD(ciSum.lastAt)}</p>
                <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                  <div className="nest px-2 py-3"><p className="t-num text-[22px] text-info">{ciSum.nDaily}</p><p className="text-[11px] text-fg-3">denních</p></div>
                  <div className="nest px-2 py-3"><p className="t-num text-[22px] text-self">{ciSum.nWeekly}</p><p className="text-[11px] text-fg-3">týdenních{ciSum.activeWeekly ? ` · ${ciSum.activeWeekly} akt.` : ""}</p></div>
                  <div className="nest px-2 py-3"><p className="t-num text-[22px]" style={{ color: ciSum.painMean != null && ciSum.painMean >= 4 ? C.alert : undefined }}>{ciSum.painMean != null ? mfmt(1, ciSum.painMean) : "—"}</p><p className="text-[11px] text-fg-3">ø bolest /10</p></div>
                  <div className="nest px-2 py-3"><p className="t-num text-[22px]">{ciSum.moodMean != null ? mfmt(1, ciSum.moodMean) : "—"}</p><p className="text-[11px] text-fg-3">ø nálada /4</p></div>
                </div>
                {ciSum.top.length > 0 && (
                  <div className="mt-4">
                    <Label>Nejčastější místo v check-inech</Label>
                    <p className="mt-1 text-[11px] text-fg-3">Za posledních 30 dní napříč denními i týdenními check-iny.</p>
                    <div className="mt-2 space-y-1.5">
                      {ciSum.top.slice(0, 4).map(([region, count]) => (
                        <div key={region} className="flex items-center gap-2 text-[12px]">
                          <span className="w-32 shrink-0 truncate text-fg-soft">{region}</span>
                          <div className="h-1.5 flex-1 rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-self" style={{ width: `${Math.round((count / ciSum.top[0][1]) * 100)}%` }} /></div>
                          <span className="tabular-nums text-fg-2">{count}×</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
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

export function RateSheet({ act, rid, initial, onClose, onDone }: { act: any; rid: string; initial?: any; onClose: () => void; onDone: () => void }) {
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
          <button onClick={submit} disabled={busy} className="btn btn-primary flex-1 py-3 text-sm">{busy ? "Ukládám…" : edit ? "Uložit změny" : "Uložit zápis"}</button>
          <button onClick={onClose} className="btn btn-outline px-5 py-3 text-sm">Zrušit</button>
        </div>
      }
    >
      <h2 className="font-serif text-2xl leading-tight">{edit ? "Upravit zápis" : `${act.title}${act.distance_km ? ` · ${act.distance_km} km` : ""}`}</h2>
      <p className="mt-1 text-[13px] text-fg-2">{fmtD(act.started_at)}{act.pace_s_km ? ` · ${paceStr(act.pace_s_km)}/km` : ""}{act.surface ? ` · ${surf(act.surface)}` : ""}{act.descent_m ? ` · ${act.descent_m} m sklesáno` : ""}</p>
      <div className="mt-4 grid gap-x-6 gap-y-4 md:grid-cols-2">
        <div>
          <Field label="Jak ztuhlé byly nohy PŘED během" hint="1 uvolněné · 5 ztuhlé"><Slider name="stiff" min={1} max={5} value={stiff} onChange={setStiff} /></Field>
          <Field label="Jak vám bylo"><Slider name="feeling" min={1} max={5} value={feeling} onChange={setFeeling} labels={FEEL_LABEL} /></Field>
          <Field label="Nohy" hint="1 těžké · 5 svěží"><Slider name="legs" min={1} max={5} value={legs} onChange={setLegs} /></Field>
          <Field label="Vnímaná námaha (RPE)" hint={`hodinky ${act.rpe || "—"}/10`}><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>
          <Field label="Bolest během běhu" hint="0 žádná"><Slider name="pain" min={0} max={10} value={pain} onChange={setPain} tone="pain" /></Field>
          <Field label="Poznámka">
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="Kdy se to ozvalo, co to zhoršilo…" />
          </Field>
        </div>
        <div className="min-w-0">
          <Label>Kde to bolelo</Label>
          <p className="mt-1 text-[12px] leading-5 text-fg-3">Klepněte na všechna místa, která bolela — můžete vybrat víc, silueta rozliší levou a pravou stranu.</p>
          <div className="mx-auto mt-3 max-w-[280px] md:max-w-none"><MuscleAnatomy multi onSelect={setPoints} initialRegions={initialRegions} /></div>
        </div>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
    </Sheet>
  )
}

/* ============================ MECHANIKA (POHYB) ============================ */
// feedback railway#50 — changes shown as % of the runner's own baseline, not z / σ
export const pctStr = (now: number | null | undefined, base: number | null | undefined) => {
  if (now == null || base == null || base === 0) return "—"
  const v = Math.round(((now - base) / Math.abs(base)) * 1000) / 10
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${String(Math.abs(v)).replace(".", ",")} %`
}
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
  const delta = pctStr(value, baseline)
  return { label, unit, dec, value, baseline, z, delta, hot: false, position: clamp(50 + z * 18, 8, 92), weeks, dates: dates.slice(-8), series: vals.slice(-26), seriesDates: dates.slice(-26), terrain: false, approx: true }
}

// Usual range = baseline ± 1 SD, the SD backed out from the z-score — shared by
// the card's interval bar and the band in the full-trend chart.
function usualRange(m: Metric) {
  const isd = Math.abs(m.z) > 0.15 ? Math.abs(m.value - m.baseline) / Math.abs(m.z) : (Math.abs(m.baseline) * 0.03 || 1)
  return { lo: m.baseline - isd, hi: m.baseline + isd, isd }
}

function MechMetricCard({ m, open, onSelect }: { m: Metric; open: boolean; onSelect: () => void }) {
  const { label, unit, dec, value, baseline, delta, hot, approx } = m
  // Numeric axis for the interval bar, so the bar shows real numbers, not just a dot.
  const { lo: bLo, hi: bHi, isd } = usualRange(m)
  const dLo = Math.min(bLo, value) - isd * 0.8, dHi = Math.max(bHi, value) + isd * 0.8
  const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 4, 96)
  const showBar = open || Math.abs(m.z) >= 1
  const col = hot ? C.alert : C.ok
  return (
    <div onClick={onSelect} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect() } }}
      role="button" tabIndex={0} aria-expanded={open} className="group w-full cursor-pointer p-4 text-left">
      <div className="flex items-center gap-3">
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <span className="text-[14px] font-bold text-fg">{label}</span>
          {MECH_INFO_BY_LABEL[label] && <InfoDot text={MECH_INFO_BY_LABEL[label]} label={label} />}
          {approx && <span title="Málo dat v jednotlivých profilech terénu — hrubý odhad z průměru běhů napříč terénem, ne terénně očištěná odchylka enginu." className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-fg-2">odhad</span>}
        </span>
        <strong className="t-num shrink-0 whitespace-nowrap text-[20px] leading-none text-fg">
          {mfmt(dec, value)} <span className="text-[13px] font-semibold tracking-normal text-fg-3">{unit}</span>
        </strong>
        <span className={`shrink-0 whitespace-nowrap rounded-full px-2 py-1 text-[11px] font-bold ${hot ? "bg-alert/15 text-alert-soft" : "bg-ok/12 text-ok"}`}>{delta}</span>
        <ChevronDown className={`size-4 shrink-0 text-fg-3 transition ${open ? "rotate-180 text-accent" : "group-hover:text-fg-2"}`} aria-hidden />
      </div>
      {showBar && (
        <div className="mt-7">
          <div className="relative h-2 rounded-full bg-white/[.06]">
            {/* usual range (baseline ± 1 SD) */}
            <i className="absolute top-0 h-full rounded-full" style={{ left: `${P(bLo)}%`, width: `${P(bHi) - P(bLo)}%`, background: `${C.ok}52` }} />
            {/* baseline center tick */}
            <i className="absolute top-[-3px] h-3.5 w-px bg-fg-2" style={{ left: `${P(baseline)}%` }} />
            {/* current value marker + number */}
            <i style={{ left: `${P(value)}%`, background: col, boxShadow: `0 0 0 3px ${C.bg}, 0 0 0 6px ${col}40` }} className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full" />
            <span className="absolute -top-6 -translate-x-1/2 whitespace-nowrap tabular-nums text-[12px] font-extrabold" style={{ left: `${P(value)}%`, color: hot ? C.alertSoft : C.ok }}>{mfmt(dec, value)}</span>
          </div>
          <div className="relative mt-1.5 h-3.5 tabular-nums text-[11px] text-fg-3">
            <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${P(bLo)}%` }}>{mfmt(dec, bLo)}</span>
            <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${P(bHi)}%` }}>{mfmt(dec, bHi)}</span>
          </div>
        </div>
      )}
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

type Cell = { now: number | null; avg6: number; z: number | null; base: number | null } | null
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
      if (now == null || base.length < 3) return { now, avg6, z: null, base: null }
      const sd = Math.max(std(base), Math.abs(mean(base)) * 0.012) || 1
      return { now, avg6, z: (now - mean(base)) / sd, base: mean(base) }
    }),
  }))
  return { profiles, rows }
}

function TerrainMatrix({ acts }: { acts: any[] }) {
  const { profiles, rows } = useMemo(() => terrainCompare(acts), [acts])
  if (!profiles.length) return <Card><Empty>Zatím není dost běhů ve srovnatelných profilech terénu.</Empty></Card>
  const zTone = (z: number | null) => (z == null ? C.fg3 : Math.abs(z) >= 1 ? C.alert : Math.abs(z) >= 0.5 ? C.watch : C.ok)
  const cols = `minmax(104px,1.1fr) repeat(${profiles.length}, minmax(92px,1fr))`
  return (
    <Card>
      <Label>Podle profilu terénu · 6 měsíců</Label>

      <div className="-mx-1 mt-4 overflow-x-auto px-1 pb-1">
      <div className="grid min-w-max items-stretch gap-y-1" style={{ gridTemplateColumns: cols }}>
        <div />
        {profiles.map((p) => (
          <div key={p.key} className="nest px-2 py-2 text-center">
            <p className="text-[13px] font-semibold text-fg">{p.surf}</p>
            <p className="text-[11px] text-fg-2">{p.grade} · {p.pace}</p>
            <p className="mt-0.5 tabular-nums text-[11px] text-fg-3">{p.n} {plural(p.n, "běh", "běhy", "běhů")} · {p.nNow} za 28 d</p>
          </div>
        ))}
        {rows.map((r) => (
          <Fragment key={r.field}>
            <div className="col-span-full mt-1 h-px bg-white/[.06]" />
            <div className="flex items-baseline gap-1 py-2.5 pr-2 text-[12px] text-fg-2">{r.label}<span className="text-[11px] text-fg-3">{r.unit}</span></div>
            {r.cells.map((c, i) => (
              <div key={i} className="px-1 py-2.5 text-center">
                {c ? (
                  c.now != null ? (
                    <>
                      <p className="t-num text-[17px] leading-none text-fg">{mfmt(r.dec, c.now)}</p>
                      <p className="mt-1 tabular-nums text-[11px]" style={{ color: zTone(c.z) }}>{c.z != null ? pctStr(c.now, c.base) : "málo dat"}</p>
                    </>
                  ) : (
                    <>
                      <p className="t-num text-[17px] leading-none text-fg-3">{mfmt(r.dec, c.avg6)}</p>
                      <p className="mt-1 tabular-nums text-[11px] text-fg-3">⌀ 6 měs.</p>
                    </>
                  )
                ) : (
                  <p className="text-fg-3">—</p>
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
    <div className="flex justify-between gap-3 border-t border-white/[.06] py-1.5 first:border-0">
      <dt className="text-fg-3">{k}</dt><dd className="text-right tabular-nums text-[12px] text-fg">{v}</dd>
    </div>
  )
  return (
    <div className="grid gap-3 border-t border-white/[.07] px-4 py-3 text-[12px] md:grid-cols-2">
      <section className="min-w-0">
        <p className="t-label">Terén</p>
        {t ? (
          <dl className="mt-1">
            {row("Profil srovnání", t.bucketLabel)}
            {row("Stoupání", t.ascentM != null && `${t.ascentM} m${t.ascPerKm != null ? ` · ${cz1(t.ascPerKm)} m/km` : ""}`)}
            {row("Klesání", t.descentM != null && `${t.descentM} m${t.descPerKm != null ? ` · ${cz1(t.descPerKm)} m/km` : ""}`)}
            {row("Strmé klesání (≤ −10 %)", t.steepDescentPct != null && `${t.steepDescentPct} % spádu`)}
            {row("Náročnost terénu", t.demand != null && `×${mfmt(2, t.demand)} oproti rovině`)}
            {row("Povrch z mapy", t.sampled && [t.sampled.surfaceLabel, t.sampled.onTrail && "stezka", t.sampled.forest && "les"].filter(Boolean).join(" · ") + (t.sampled.source ? ` (${t.sampled.source})` : ""))}
          </dl>
        ) : <p className="mt-1 text-fg-3">Bez údajů o terénu.</p>}
      </section>
      <section className="min-w-0">
        <p className="t-label">Počasí</p>
        {w ? (
          <>
            <dl className="mt-1">
              {row("Podmínky", `${w.icon} ${w.label}`)}
              {row("Teplota", w.precision === "hour" ? `${w.tempC} °C · pocitově ${w.feelsC} °C` : `${w.tMin}–${w.tMax} °C · pocitově až ${w.feelsC} °C`)}
              {row("Vlhkost", w.humidity != null && `${w.humidity} %`)}
              {row(w.precision === "hour" ? "Vítr" : "Vítr (max.)", w.windKmh != null && `${w.windKmh} km/h`)}
              {row("Srážky", `${cz1(w.precipMm || 0)} mm`)}
            </dl>
            <p className="mt-1.5 text-[11px] leading-4 text-fg-3">
              {w.precision === "hour" ? `Během běhu (start ${x.start_time}, ${Math.round(x.duration_min || 0)} min)` : "Denní souhrn (čas startu neznámý)"}
              {" · "}{w.place === "city" ? `přibližně — podle města ${w.city}` : "v místě startu (±10 km)"} · {w.source}
            </p>
            {w.hot && w.precision === "hour" && <p className="mt-1.5 rounded-[10px] border border-watch/25 bg-watch/[.08] px-2 py-1 text-[11px] leading-4 text-watch">Pocitově přes 24 °C — vyšší tep při obvyklém tempu je v tomhle počasí očekávaný.</p>}
          </>
        ) : <p className="mt-1 text-fg-3">{x.weatherNote || "Počasí není k dispozici."}</p>}
      </section>
    </div>
  )
}

// Feedback railway#36 — take a run out of every calculation (or put it back).
// The run stays listed (faded) so it can be restored; nothing is deleted.
const SCOPE_TXT: Record<string, string> = { all: "ze všech výpočtů", mech: "jen z mechaniky", load: "jen ze zátěže" }
function ExcludeRun({ rid, x, onDone }: { rid: string; x: any; onDone: (excluded: boolean, scope?: string | null) => void }) {
  const [ask, setAsk] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const go = async (excluded: boolean, scope: string = "all") => {
    setBusy(true)
    try {
      await api.excludeActivity(rid, x.id, excluded, excluded ? scope : undefined)
      onDone(excluded, excluded ? scope : null)
      toast({ title: excluded ? `Běh vyřazen ${SCOPE_TXT[scope]}` : "Běh se zase počítá" })
    } catch (e: any) {
      toast({ title: e?.message || "Nepodařilo se" })
    } finally { setBusy(false); setAsk(false) }
  }
  if (x.excluded)
    return (
      <div className="flex flex-wrap items-center gap-2 border-t border-white/[.07] px-4 py-3 text-[12px] text-fg-2">
        <span className="flex-1">{(x.excluded_scope || "all") === "all"
          ? "Tento běh je vyřazený — nepočítá se do skóre, kapacity, srovnání ani AI textů."
          : x.excluded_scope === "mech" ? "Tento běh je vyřazený jen z mechaniky — do zátěže a kapacity se dál počítá."
            : "Tento běh je vyřazený jen ze zátěže a kapacity — do mechaniky se dál počítá."}</span>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => go(false)}>Vrátit do výpočtů</Button>
      </div>
    )
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-white/[.07] px-4 py-3 text-[12px] text-fg-2">
      {ask ? (
        <>
          <span className="w-full">Vyřadit „{x.title}“ ({fmtD(x.started_at)}) — z čeho? Kdykoli ho vrátíte.</span>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => go(true, "mech")}>Jen z mechaniky</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => go(true, "load")}>Jen ze zátěže</Button>
          <Button size="sm" variant="danger" disabled={busy} onClick={() => go(true, "all")}>Ze všech výpočtů</Button>
          <Button size="sm" variant="secondary" onClick={() => setAsk(false)}>Zrušit</Button>
        </>
      ) : (
        <button onClick={() => setAsk(true)} className="ml-auto text-[12px] text-fg-3 underline decoration-dotted underline-offset-2 hover:text-alert">Vyřadit běh z výpočtů</button>
      )}
    </div>
  )
}

function RunHistoryReal({ acts }: { acts: any[] }) {
  const { me, refresh } = useApp()
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
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="card mt-4 flex w-full items-center gap-4 px-4 py-4 text-left text-fg transition hover:border-info/45 md:px-5">
        <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-info/15 text-info"><History className="size-4" aria-hidden /></span>
        <span className="min-w-0 flex-1"><span className="t-label">Historie běhů</span><span className="mt-1 block font-serif text-[19px] leading-snug">Běhy s terénem a počasím — rozklikni pro úseky a srovnání</span></span>
        <ChevronDown className={`size-5 shrink-0 text-info transition ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {ctx === null && <p className="px-1 text-[12px] text-fg-3">Načítám terén a počasí…</p>}
          {ctx === false && <p className="px-1 text-[12px] text-fg-3">Kontext terénu a počasí se nepodařilo načíst — zobrazuji jen statistiky.</p>}
          {rows.map((x) => {
            const isOpen = run === x.id
            const d = cmp[x.id]
            const tl = terrainLine(x.terrain)
            const wl = weatherLine(x.weather)
            return (
              <div key={x.id} className={`overflow-hidden rounded-[18px] border transition ${isOpen ? "border-info/40 bg-panel-2" : "border-white/[.08] bg-white/[.03] hover:border-white/15"} ${x.excluded ? "opacity-60" : ""}`}>
                <button onClick={() => setRun(isOpen ? null : x.id)} aria-expanded={isOpen} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left">
                  <span className="grid size-[34px] place-items-center rounded-[10px] bg-info/15 text-info">{x.surface === "trail" ? <Mountain className="size-4" aria-hidden /> : <Footprints className="size-4" aria-hidden />}</span>
                  <span className="min-w-0">
                    <b className="text-sm font-bold">{x.title}</b>
                    {x.excluded && <span className="ml-2 rounded-full bg-white/[.08] px-2 py-0.5 align-middle text-[11px] font-bold uppercase tracking-[.08em] text-fg-2">{(x.excluded_scope || "all") === "all" ? "vyřazeno" : x.excluded_scope === "mech" ? "bez mechaniky" : "bez zátěže"}</span>}
                    <span className="block text-[12px] text-fg-3">{fmtD(x.started_at)}{x.start_time ? ` ${x.start_time}` : ""} · {surf(x.surface)} · {x.distance_km} km · {paceStr(x.pace_s_km)}/km · {x.avg_hr} tep</span>
                    {(tl || wl) && (
                      <span className="mt-1.5 flex flex-wrap gap-1.5">
                        {tl && <span className="inline-flex items-center gap-1 rounded-full bg-info/12 px-2 py-0.5 text-[11px] font-semibold text-info"><Mountain className="size-3" aria-hidden />{tl}</span>}
                        {wl && <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${x.weather?.hot && x.weather.precision === "hour" ? "bg-watch/12 text-watch" : "bg-self/12 text-self"}`}><CloudSun className="size-3" aria-hidden />{wl}</span>}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-2 whitespace-nowrap tabular-nums text-[12px] text-fg-2">VR {x.vert_ratio_pct ?? "—"} <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180 text-info" : ""}`} aria-hidden /></span>
                </button>
                {isOpen && ctx && <RunContext x={x} />}
                {isOpen && rid && !x.excluded && <SegmentTimeline rid={rid} aid={x.id} />}
                {isOpen && (
                  d && d.metrics ? (
                    <MonthCompare data={d} />
                  ) : d === false ? (
                    <dl className="grid grid-cols-3 gap-2 border-t border-white/[.07] px-4 py-3 text-[11px] md:grid-cols-6">
                      {[["Kadence", x.cadence_spm && `${x.cadence_spm} spm`], ["Kontakt", x.gct_ms && `${x.gct_ms} ms`], ["Krok", x.stride_len_m && `${x.stride_len_m} m`], ["Osc.", x.vert_osc_cm && `${x.vert_osc_cm} cm`], ["Balance", x.gct_balance_l ? `${x.gct_balance_l} %` : "—"], ["Klesání", x.descent_m != null && `${x.descent_m} m`]].map(([k, v]) => (
                        <div key={k as string}><dt className="uppercase tracking-[.1em] text-fg-3">{k}</dt><dd className="mt-0.5 tabular-nums text-[11px] text-fg">{v || "—"}</dd></div>
                      ))}
                    </dl>
                  ) : (
                    <p className="border-t border-white/[.07] px-4 py-3 text-[12px] text-fg-3">Načítám srovnání s během před měsícem…</p>
                  )
                )}
                {isOpen && rid && ctx && (
                  <ExcludeRun rid={rid} x={x} onDone={(ex, scope) => {
                    setCtx((c) => (c ? c.map((r: any) => (r.id === x.id ? { ...r, excluded: ex, excluded_scope: scope } : r)) : c))
                    setCmp({})
                    refresh()
                  }} />
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
  B1: ["prudký sjezd", C.self], B2: ["sjezd", `${C.self}99`], B3: ["rovina", C.fg4],
  B4: ["výjezd", `${C.watch}99`], B5: ["prudký výjezd", C.watch],
}
const UP = C.alert
const DOWN = C.self
const mmss = (s: number) => {
  const t = Math.max(0, Math.round(s))
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), ss = String(t % 60).padStart(2, "0")
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`
}
const meanPct = (g: any) => {
  const v = g.segs.map((s: any) => s.findings.find((f: any) => f.metric === g.key)).filter((f: any) => f && f.base).map((f: any) => (f.value - f.base) / Math.abs(f.base) * 100)
  if (!v.length) return "—"
  const m = Math.round((v.reduce((a: number, b: number) => a + b, 0) / v.length) * 10) / 10
  return `${m > 0 ? "+" : m < 0 ? "−" : "±"}${String(Math.abs(m)).replace(".", ",")} %`
}
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
      <span className="t-label">Úseky běhu vůči vaší normě</span>
      <InfoDot label="Úseky běhu" text="Běh je rozdělený na úseky po 20–60 s ustáleného běhu. Každý úsek se porovná s tím, co od vás čeká vaše vlastní norma přesně pro ten úsek — při jeho tempu, sklonu, čase v běhu a povrchu. Norma je z běhů 29–84 dní PŘED tímto během, takže i starší běh se posuzuje tím, jak jste běhali tehdy. Procenta = o kolik se úsek liší od hodnoty, kterou pro něj čeká vaše norma. „Významné“ = po korekci na počet testů (FDR 5 %), ne jen p < 0,05. Úseky mimo vaši obvyklou rychlost / sklon / povrch se netestují." />
    </span>
  )
  const box = (children: any) => <div className="border-t border-white/[.07] px-4 py-3">{head}{children}</div>
  if (data === null) return box(<p className="mt-2 text-xs text-fg-3">Načítám úseky…</p>)
  if (data === false) return box(<p className="mt-2 text-xs text-fg-3">Úseky se nepodařilo načíst.</p>)
  if (!data.available)
    return box(<p className="mt-2 text-xs leading-5 text-fg-3">Zobrazí se po stažení <b className="text-fg-2">Detailních dat</b> pro tento běh (Data a připojení → ⛰ Detailní data).</p>)
  if (!run.nTested)
    return box(<p className="mt-2 text-xs leading-5 text-fg-3">{data.reason === "no_baseline"
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
    if (!f) return { fill: C.fg, op: 0.05 }
    return { fill: f.z > 0 ? UP : DOWN, op: f.sig ? 1 : Math.min(0.5, Math.max(0.1, Math.abs(f.z) / 4)) }
  }
  const strip = (key: string | null, h: number) => (
    <svg viewBox={`0 0 ${T} ${h}`} preserveAspectRatio="none" className="block w-full cursor-pointer" style={{ height: h }} onClick={pick} role="presentation">
      {segs.map((s) => {
        const w = Math.max((s.durationS || 0) * 0.94, T / 900)
        if (key === null) return <rect key={s.idx} x={s.startS} y={0} width={w} height={h} fill={SEG_BAND[s.band]?.[1] || C.fg4} />
        const c = cell(s, key)
        return <rect key={s.idx} x={s.startS} y={0} width={w} height={h} fill={c.fill} fillOpacity={c.op} />
      })}
      {cur && <rect x={cur.startS} y={0.5} width={Math.max(cur.durationS || 0, T / 300)} height={h - 1} fill="none" stroke={C.fg} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
    </svg>
  )
  const stepMin = [5, 10, 15, 20, 30, 60].find((st) => T / 60 / st <= 4) || 60
  const ticks = Array.from({ length: Math.floor(T / 60 / stepMin) + 1 }, (_, i) => i * stepMin * 60)
  const sigSegs = segs.filter((s) => s.sig).length
  return box(
    <>
      <p className="mt-1.5 text-[11px] leading-5 text-fg-2">
        {run.nSeg} úseků · {run.nTested} testů · {run.sigCount
          ? <b className="text-alert-soft">{run.sigCount} {run.sigCount === 1 ? "významná odchylka" : run.sigCount < 5 ? "významné odchylky" : "významných odchylek"} v {sigSegs} {sigSegs === 1 ? "úseku" : "úsecích"}</b>
          : <b className="text-info">bez významných odchylek</b>}
        <span className="text-fg-3"> · norma k datu běhu: {data.baseline.runs} běhů ({fmtD(data.baseline.from)} – {fmtD(data.baseline.to)})</span>
      </p>

      <div className="mt-3 grid grid-cols-[64px_minmax(0,1fr)] items-center gap-x-2 gap-y-[3px] sm:grid-cols-[112px_minmax(0,1fr)]">
        <span className="text-[11px] uppercase tracking-[.1em] text-fg-3">Terén</span>
        {strip(null, 8)}
        {rows.map(([k, label, short]) => (
          <Fragment key={k}>
            <span className="truncate text-[11px] text-fg-2"><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{label}</span></span>
            {strip(k, 14)}
          </Fragment>
        ))}
        <span />
        <div className="relative h-4 tabular-nums text-[11px] text-fg-3">
          {ticks.map((t, i) => (
            <span key={i} className="absolute top-0.5 whitespace-nowrap" style={{ left: `${(t / T) * 100}%`, transform: i === 0 ? "none" : t / T > 0.9 ? "translateX(-100%)" : "translateX(-50%)" }}>
              {i === 0 ? "0" : `${t / 60} min`}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-3">
        <span><i className="mr-1 inline-block size-2 rounded-sm align-middle" style={{ background: UP }} />nad normou</span>
        <span><i className="mr-1 inline-block size-2 rounded-sm align-middle" style={{ background: DOWN }} />pod normou</span>
        <span>sytá barva = významné · bledá = v normě · tmavá = netestováno</span>
        <span className="flex gap-2">{["B1", "B2", "B3", "B4", "B5"].map((b) => <span key={b}><i className="mr-0.5 inline-block size-2 rounded-sm align-middle" style={{ background: SEG_BAND[b][1] }} />{SEG_BAND[b][0]}</span>)}</span>
      </p>

      {stretches.length > 0 && (
        <div className="mt-3">
          <p className="t-label">Kde se běh lišil</p>
          <ol className="mt-1.5 space-y-1">
            {stretches.slice(0, 6).map((g, i) => (
              <li key={i}>
                <button onClick={() => setSel(g.peak.idx)} className="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-[12px] border border-white/[.06] bg-white/[.03] px-2.5 py-1.5 text-left hover:bg-white/[.06]">
                  <span className="grid size-5 place-items-center rounded-full text-[11px] font-bold text-ink" style={{ background: g.dir === "up" ? UP : DOWN }}>{g.dir === "up" ? "↑" : "↓"}</span>
                  <span className="min-w-0 text-[11px] leading-4 text-fg-soft">
                    <b className="text-fg">{g.label}</b> {g.dir === "up" ? "vyšší" : "nižší"} než norma
                    <span className="block text-[11px] text-fg-3">{g.n === 1 ? `úsek ${g.from}` : `úseky ${g.from}–${g.to}`} · {mmss(g.t0)}–{mmss(g.t1)} · {g.bands.join(", ")}</span>
                  </span>
                  <span className="whitespace-nowrap text-right tabular-nums text-[11px]" style={{ color: g.dir === "up" ? UP : DOWN }}>Ø {meanPct(g)}<span className="block text-[11px] text-fg-3">{g.n}× významné</span></span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {cur && (
        <div className="nest mt-3 p-3">
          <div className="flex items-center justify-between gap-2">
            <button onClick={() => setSel(Math.max(0, cur.idx - 1))} disabled={cur.idx === 0} aria-label="Předchozí úsek" className="grid size-8 shrink-0 place-items-center rounded-full bg-white/[.06] text-info hover:bg-white/10 disabled:opacity-30"><ChevronLeft className="size-4" aria-hidden /></button>
            <p className="min-w-0 text-center text-[11px] leading-4 text-fg-2">
              <b className="text-sm text-fg">Úsek {cur.idx + 1}</b> <span className="text-fg-3">z {run.nSeg}</span>
              <span className="block">{mmss(cur.startS)}–{mmss(cur.startS + (cur.durationS || 0))} · {SEG_BAND[cur.band]?.[0] || cur.bandLabel} ({cur.gradePct > 0 ? "+" : cur.gradePct < 0 ? "−" : ""}{mfmt(1, Math.abs(cur.gradePct))} %){cur.paceSKm ? ` · ${paceStr(cur.paceSKm)}/km` : ""}</span>
            </p>
            <button onClick={() => setSel(Math.min(run.nSeg - 1, cur.idx + 1))} disabled={cur.idx >= run.nSeg - 1} aria-label="Další úsek" className="grid size-8 shrink-0 place-items-center rounded-full bg-white/[.06] text-info hover:bg-white/10 disabled:opacity-30"><ChevronRight className="size-4" aria-hidden /></button>
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
                    <span className="text-fg-soft">{label}{f.sig && <span className="ml-1.5 rounded bg-alert/20 px-1 text-[11px] font-bold uppercase tracking-wide text-alert-soft">významné</span>}</span>
                    <span className="whitespace-nowrap text-right tabular-nums text-[11px] text-fg-2 sm:col-start-3 sm:row-start-1">
                      <span className="hidden sm:inline"><b className="text-fg">{segVal(k, f.value)}</b> <span className="text-fg-3">vs {segVal(k, f.base)}</span> · </span><span style={{ color: f.sig ? col : undefined }}>{pctStr(f.value, f.base)}</span>
                    </span>
                    <span className="relative col-span-2 h-2 rounded-full bg-white/[.06] sm:col-span-1 sm:col-start-2 sm:row-start-1">
                      <span className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
                      <span className="absolute inset-y-0 rounded-full" style={{ left: `${Math.min(50, pos)}%`, width: `${Math.abs(pos - 50)}%`, background: col, opacity: f.sig ? 1 : 0.45 }} />
                    </span>
                    <span className="col-span-2 tabular-nums text-[11px] text-fg-3 sm:hidden"><b className="text-fg">{segVal(k, f.value)}</b> vs {segVal(k, f.base)}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-fg-3">Tento úsek se netestoval — tempo, sklon nebo povrch byly mimo rozsah vaší normy.</p>
          )}
        </div>
      )}
      <p className="mt-2 text-[11px] leading-4 text-fg-3">Klepněte do pásu na libovolné místo běhu. „vs“ = hodnota, kterou vaše norma čeká přesně pro takový úsek; procenta = rozdíl proti ní.</p>
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
    if (m.diff == null) return <span className="text-[11px] text-fg-3">—</span>
    if (Math.abs(m.diff) < (m.dec ? 1 / 10 ** m.dec : 1)) return <span className="text-[11px] text-fg-3">beze změny</span>
    const sign = m.diff > 0 ? "+" : "−"
    const txt = m.key === "pace_s_km" ? `${sign}${Math.abs(m.diff)} s/km` : `${sign}${mfmt(m.dec, Math.abs(m.diff))} ${m.unit}`
    const note = m.key === "pace_s_km" ? (m.diff > 0 ? " pomaleji" : " rychleji") : ""
    return <span className="tabular-nums text-[11px] text-fg-soft"><span className="whitespace-nowrap">{m.diff > 0 ? "▲" : "▼"} {txt}</span><span className="block font-sans text-[11px] text-fg-3 sm:inline">{note}</span></span>
  }
  return (
    <div className="border-t border-white/[.07] px-4 py-3">
      <span className="flex items-center gap-1.5">
        <span className="t-label">Srovnání s během před měsícem</span>
        <InfoDot label="Běh před měsícem" text="Srovnatelný běh = stejný povrch, sklon i tempová skupina. Hledá se od stejného dne minulý měsíc do týdne poté — nikdy starší než měsíc. Když je jich víc, vyhraje ten nejblíž měsíční hranici (při shodě podobnější vzdálenost). Rozdíl tak ukazuje změnu vás, ne trasy." />
      </span>
      {p ? (
        <>
          <p className="mt-1.5 text-[11px] leading-5 text-fg-2">
            <b className="text-fg">{fmtD(p.date)} · {p.title || "Běh"}</b> · {mfmt(1, p.distanceKm || 0)} km{p.paceSKm ? ` · ${paceStr(p.paceSKm)}/km` : ""}
            <span className="text-fg-3"> — {p.daysBefore} dní před tímto během · profil {data.bucketLabel}</span>
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-[11px] font-bold uppercase tracking-[.1em] text-fg-3">
                <th className="py-1 pr-3 font-normal">Metrika</th><th className="pr-3 font-normal">Tento běh</th><th className="pr-3 font-normal">Před měsícem</th><th className="font-normal">Rozdíl</th>
              </tr></thead>
              <tbody>
                {data.metrics.map((m: any) => (
                  <tr key={m.key} className="border-t border-white/[.06]">
                    <td className="py-2 pr-3 text-fg-2">{m.label}</td>
                    <td className="whitespace-nowrap pr-3 tabular-nums"><b className="text-fg">{val(m, m.value)}</b></td>
                    <td className="whitespace-nowrap pr-3 tabular-nums text-fg-2">{val(m, m.prev)}</td>
                    <td>{diff(m)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="mt-1.5 text-xs leading-5 text-fg-3">
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
  const allActs = (boot?.activities || []) as any[]
  // excluded runs don't count for mechanics — unless they were excluded from load only (railway#47)
  const acts = useMemo(() => allActs.filter((x) => !x.excluded || x.excluded_scope === "load"), [allActs])
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
        <Head kicker="Mechanika" title="Baseline se zatím buduje" />
        <AlertBanner tone="info" icon={Gauge} title={`Spolehlivost ${Math.round((a.confidence?.value ?? 0) * 100)} %`}>
          — {a.confidence?.sessions} tréninků ve srovnatelných podmínkách, {a.confidence?.days} dní historie. Než tohle číslo překročí 60 %, mechanické signály se nezobrazují.
          <span className="relative mt-2.5 block h-2 rounded-full bg-white/[.08]" aria-hidden>
            <i className="absolute inset-y-0 left-0 rounded-full bg-info" style={{ width: `${clamp((a.confidence?.value ?? 0) * 100, 2, 100)}%` }} />
            <i className="absolute -inset-y-1 left-[60%] w-0.5 bg-fg" title="60 %" />
          </span>
        </AlertBanner>
        <Card className="mt-4"><Label>Co pomůže nejrychleji</Label><p className="mt-2 text-sm text-fg-2">Opakovat podobné běhy — stejný povrch, podobné tempo. Baseline se počítá po skupinách povrch × sklon × tempo.</p></Card>
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
    return eng(series, field, label, unit, dec, rec, base, z, pctStr(rec, base), Math.abs(z) >= 1, clamp(50 + z * 18, 8, 92), terrain)
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

  // OPT-6: worst deviation first, measured against each card's own "hot" gate
  // (|z| ≥ 1; balance carries its excursion in p.b. with a 0.8 gate). Array.sort is
  // stable, so ties keep the engine's order.
  const devKey = (m: Metric) => Math.abs(m.z) / (m.label === "Symetrie kontaktu" ? 0.8 : 1)
  metrics.sort((x, y) => devKey(y) - devKey(x))

  // State label follows the quadrant (post-hysteresis), so Pohyb matches the
  // kvadrant exactly — not a separate ≥25 / tavr-z cutoff that could disagree.
  const drift = a.quadrant === "silent" || a.quadrant === "critical"
  const headline = drift ? "Mechanika se mění" : a.mech >= 12 ? "Jemný drift proti normě" : "Mechanika drží na normě"
  const mechSig = ((a.signals || []) as any[]).filter((s) => MECH_IDS.has(s.id))

  // Reconcile the trend's final point with the live score so the chart's last
  // value *and* date always equal the big number / quadrant — even if this
  // history fetch predates today's recompute (e.g. a tab left open overnight).
  const asOf = (a.computed_at || "").slice(0, 10)
  const mechPoints = (mechHist || []).map((h) => ({ t: h.date, v: h.mech }))
  if (mechPoints.length) mechPoints[mechPoints.length - 1] = { t: asOf || mechPoints[mechPoints.length - 1].t, v: a.mech ?? mechPoints[mechPoints.length - 1].v }

  return (
    <>
      <section className="card overflow-hidden p-4 md:p-6">
        <div className="grid gap-6 lg:grid-cols-[.9fr_1.1fr] lg:items-start">
          <div>
            <Label>Signál pohybu</Label>
            <h2 className="mt-2 font-serif text-[28px] leading-tight tracking-[-.02em] text-fg">{headline}</h2>

            <div className={`mt-4 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] font-bold ${drift ? "bg-alert/12 text-alert-soft" : "bg-ok/12 text-ok"}`}>
              <i className={`size-2 rounded-full ${drift ? "bg-alert" : "bg-ok"}`} />
              {drift ? "vyšší než váš obvyklý střed" : "v rámci obvyklého středu"}
            </div>
            {mechSig.length > 0 && (
              <div className="mt-5 border-t border-white/[.08] pt-4">
                <p className="t-label !text-fg-3">Co tvoří skóre mechaniky</p>
                <div className="mt-3 space-y-3">
                  {mechSig.map((s) => (
                    <FactorBar key={s.id} label={s.name} value={s.val} pts={s.pts} tone="info" pct={(s.pts / Math.max(1, ...mechSig.map((x) => x.pts || 0))) * 100} />
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="nest p-4 md:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Mechanická stabilita — trend</Label>
              <span className="text-[12px] text-fg-3">skóre driftu 0–100</span>
            </div>
            <div className="mt-2 flex items-end gap-2">
              <b className="t-num text-[40px] leading-none" style={{ color: drift ? C.alert : C.fg }}>{a.mech}</b>
              <small className="pb-1 text-[13px] text-fg-2">/ 100 · {drift ? "drift" : "stabilní"}</small>
            </div>
            {mechHist === null ? (
              <p className="mt-3 text-sm text-fg-3">Počítám trend v čase…</p>
            ) : mechHist.length > 1 ? (
              <AxisLineChart points={mechPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh driftu" color={drift ? C.alert : C.ok} height={150} zone />
            ) : (
              <p className="mt-3 text-sm text-fg-3">Na trend v čase je zatím málo historie.</p>
            )}
            <p className="mt-1 text-[11px] text-fg-3">skóre driftu mechaniky po týdnech · nad prahem 25 = drift</p>
          </div>
        </div>
      </section>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <Segmented ariaLabel="Srovnání metrik" options={[["all", "Všechen terén"], ["terr", "Podle profilu terénu"]] as const} value={terr ? "terr" : "all"} onChange={(k) => setTerr(k === "terr")} />
        <span className="text-[12px] text-fg-3">{terr ? "srovnání metrik napříč profily terénu" : "každá metrika proti vaší celkové normě · seřazeno od největší odchylky"}</span>
      </div>

      {terr ? (
        <div className="mt-4"><TerrainMatrix acts={acts} /></div>
      ) : (
        <div className="mt-4 space-y-2.5">
          {metrics.map((m) => {
            const isOpen = openMetric === m.label
            return (
              <div key={m.label} className={`overflow-hidden rounded-[20px] border transition ${isOpen ? "border-accent/70 bg-accent/[.05]" : "border-white/[.08] bg-white/[.03] hover:border-white/20"}`}>
                <MechMetricCard m={m} open={isOpen} onSelect={() => setOpenMetric(isOpen ? "" : m.label)} />
                {isOpen && (
                  <div className="origin-top animate-[careReveal_.28s_ease-out] border-t border-white/[.08] px-4 py-4">

                    {m.series.length > 1 && (
                      <div className="mt-3">
                        <p className="t-label !text-fg-3">Celý trend · {m.series.length} {plural(m.series.length, "běh", "běhy", "běhů")}{m.seriesDates.length ? ` · ${fmtD(m.seriesDates[0])} → ${fmtD(m.seriesDates.at(-1)!)}` : ""}</p>
                        <AxisLineChart points={m.series.map((v, i) => ({ t: m.seriesDates[i] || m.seriesDates.at(-1) || "", v }))} dec={m.dec} unit={` ${m.unit}`} color={C.accent} height={150}
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
export const MECH_IDS = new Set(["tavr", "gct", "bal", "dec", "gaitcv", "cad", "vosc"])
export const LOAD_IDS = new Set([
  // v0.6 spine
  "session_spike", "spike_latent", "pace_spike", "load_capacity",
  // grade-C ACWR context + the rest of the load axis
  "ewma", "hi_load", "load_creep", "mono", "desc", "desc_steep", "aer", "hrv", "rhr", "hrvcv", "tsb", "taper",
  // engine v3 — load against the runner's own capacity, per channel
  ...CAP_SIGNAL_IDS,
])
// ADD · 7:28 load ratio on a graded bar: <0,8 nízká · 0,8–1,3 v normě · 1,3–1,5 zvýšená · >1,5 vysoká.
const RATIO_SEG: [number, number, string][] = [[0.4, 0.8, C.self], [0.8, 1.3, C.ok], [1.3, 1.5, C.watch], [1.5, 2.2, C.alert]]
const ratioTone = (r: number): Tone => (r < 0.8 ? "muted" : r <= 1.3 ? "ok" : r <= 1.5 ? "watch" : "alert")
function RatioBar({ ratio }: { ratio: number }) {
  const lo = 0.4, hi = 2.2
  const P = (v: number) => clamp(((v - lo) / (hi - lo)) * 100, 1.5, 98.5)
  const tone = ratioTone(ratio)
  const col = tone === "muted" ? C.self : toneCol(tone)
  const word = ratio < 0.8 ? "nižší než obvykle" : ratio <= 1.3 ? "v normě" : ratio <= 1.5 ? "zvýšená" : "vysoká"
  return (
    <div className="nest p-3.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="t-label !text-fg-3">Poměr zátěže (7:28 dní)</span>
        <span className="text-[13px] font-bold" style={{ color: col }}><span className="t-num text-[18px]">×{mfmt(2, ratio)}</span> · {word}</span>
      </div>
      <div className="relative mt-3 h-2.5">
        <div className="absolute inset-0 flex gap-0.5 overflow-hidden rounded-full">
          {RATIO_SEG.map(([a, b, c]) => <i key={a} className="block h-full" style={{ width: `${((b - a) / (hi - lo)) * 100}%`, background: c, opacity: 0.55 }} />)}
        </div>
        <i className="absolute top-1/2 h-4.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg shadow-[0_0_0_3px_rgb(6_16_16_/_0.9)]" style={{ left: `${P(ratio)}%`, height: 18 }} />
      </div>
      <div className="relative mt-1.5 h-3.5 tabular-nums text-[11px] text-fg-3">
        {[0.8, 1.3, 1.5].map((v) => <span key={v} className="absolute -translate-x-1/2" style={{ left: `${P(v)}%` }}>{mfmt(1, v)}</span>)}
      </div>
    </div>
  )
}
// Weekly bar colour: each week against the mean of the four weeks before it (same bands as the 7:28 ratio).
function weekTones(w: number[]): Tone[] {
  return w.map((v, i) => {
    const prev = w.slice(Math.max(0, i - 4), i).filter((x) => x > 0)
    if (prev.length < 2) return "muted"
    const t = ratioTone(v / mean(prev))
    return t === "ok" ? "info" : t
  })
}
// OPT-7 · the 13 descent bins (2,5 % steps) grouped into 4 slope bands; ≥ 10 % matches the "steep" total.
const SLOPE_BANDS: [string, number, number, Tone][] = [["0–5 %", 0, 2, "muted"], ["5–10 %", 2, 4, "info"], ["10–20 %", 4, 8, "watch"], ["20 % +", 8, 13, "alert"]]
function DescentBySlope({ g }: { g: any }) {
  const [detail, setDetail] = useState(false)
  const b: number[] = g.buckets || []
  const bands = SLOPE_BANDS.map(([l, a, z, t]) => ({ l, t, v: b.slice(a, z).reduce((s: number, x: number) => s + (x || 0), 0) }))
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Klesání za 7 dní podle sklonu</Label>
        <Segmented size="sm" ariaLabel="Rozlišení sklonu" options={[["bands", "4 pásma"], ["bins", "po 2,5 %"]] as const} value={detail ? "bins" : "bands"} onChange={(k) => setDetail(k === "bins")} />
      </div>
      {detail
        ? <Bars vals={b} unit="m" labels={g.labels} axisLabels={(g.labels || []).map((l: string) => (l.includes("–") ? l.split("–")[0] : l))}
            tones={b.map((_, i) => SLOPE_BANDS.find(([, a, z]) => i >= a && i < z)?.[3] || "muted")} />
        : <Bars vals={bands.map((x) => x.v)} unit="m" labels={bands.map((x) => x.l)} tones={bands.map((x) => x.t)} />}
      <p className="mt-2 text-[12px] text-fg-3">{g.total7} m celkem · {g.steep7} m na sklonu ≥10 %.</p>
    </div>
  )
}

export function Load() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const a = boot?.assessment
  const L = a?.loadDetail
  const rcv = a?.rcv
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
  const loadSig = ((a.signals || []) as any[]).filter((s) => LOAD_IDS.has(s.id))

  // Same reconciliation as Pohyb: pin the trend's final point to the live load
  // score + date so the chart end always equals the big number / quadrant.
  const loadAsOf = (a.computed_at || "").slice(0, 10)
  const loadPoints = (hist || []).map((h) => ({ t: h.date, v: h.load }))
  if (loadPoints.length) loadPoints[loadPoints.length - 1] = { t: loadAsOf || loadPoints[loadPoints.length - 1].t, v: a.load ?? loadPoints[loadPoints.length - 1].v }

  return (
    <>

      {/* Signál zátěže: the score and its trend first, then what makes it up (feedback railway#34/#35) */}
      <section className="card mb-4 overflow-hidden p-4 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <Label>Signál zátěže</Label>
            <h2 className="mt-2 font-serif text-[28px] leading-tight tracking-[-.02em] text-fg">{loadHeadline}</h2>
          </div>
          <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] font-bold ${loadHot ? "bg-alert/12 text-alert-soft" : "bg-ok/12 text-ok"}`}>
            <i className={`size-2 rounded-full ${loadHot ? "bg-alert" : "bg-ok"}`} />
            {loadHot ? "nad obvyklou úrovní" : "v obvyklém rozsahu"}
          </div>
        </div>
        <div className="nest mt-5 p-4 md:p-5">
          <div className="flex items-center justify-between">
            <Label>Skóre zátěže — trend</Label>
            <span className="text-[12px] text-fg-3">0–100</span>
          </div>
          <div className="mt-2 flex items-end gap-2">
            <b className="t-num text-[40px] leading-none" style={{ color: loadHot ? C.alert : C.load }}>{a.load}</b>
            <small className="pb-1 text-[13px] text-fg-2">/ 100 · {loadHot ? "zvýšená" : "v normě"}</small>
          </div>
          {hist === null ? (
            <p className="mt-3 text-sm text-fg-3">Počítám trend v čase…</p>
          ) : hist.length > 1 ? (
            <AxisLineChart points={loadPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh" color={C.load} height={150} zone />
          ) : (
            <p className="mt-3 text-sm text-fg-3">Na trend je zatím málo historie.</p>
          )}
          <p className="mt-1 text-[11px] text-fg-3">skóre zátěže po týdnech · nad prahem 25 = zvýšená (vstupuje do kvadrantu)</p>
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <div>
            <p className="t-label !text-fg-3">Co tvoří skóre zátěže</p>
            {loadSig.length > 0 ? (
              <div className="mt-3 space-y-3">
                {loadSig.map((s) => (
                  <FactorBar key={s.id} label={s.name} value={s.val} pts={s.pts} tone="load" pct={(s.pts / Math.max(1, ...loadSig.map((x) => x.pts || 0))) * 100} />
                ))}
              </div>
            ) : <p className="mt-2 text-[13px] text-fg-2">Nic nad vaší obvyklou úrovní — skóre je 0.</p>}
          </div>
          <div className="grid content-start gap-3">
            {L.valid && L.ratio != null && <RatioBar ratio={L.ratio} />}
            {/* railway#63 — recovery signals sit under the 7:28 ratio, sized to this column */}
            {rcv ? <RecoveryTiles rcv={rcv} sleepEff={a.sleepEff} /> : <p className="nest px-3.5 py-3 text-[12px] text-fg-3">Chybí souvislá data z hodinek za posledních 35 dní (HRV, klidový tep, spánek).</p>}
          </div>
        </div>
      </section>

      {a.capacity && (
        <CapacityPanel cap={a.capacity} extra={{
          // railway#58/#59 — weekly and daily run volume feed the Objem channel
          volume: (
            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <Label>Týdenní objem běhu (Po–Ne), 12 týdnů</Label>
                <Bars vals={L.weekly || []} tones={weekTones(L.weekly || [])} />
                <p className="mt-2 text-[12px] text-fg-3">Tento týden (Po–Ne) <b className="text-fg">{L.weekKm ?? "—"} km</b> · posledních 7 dní <b className="text-fg">{L.runKm7 ?? "—"} km</b></p>
                <p className="mt-1 text-[11px] text-fg-3">barva = týden proti průměru 4 předchozích (nad ×1,3 žlutě, nad ×1,5 červeně)</p>
              </div>
              <div>
                <Label>Denní objem běhu, 28 dní</Label>
                <Bars vals={L.daily || []} tones={(L.daily || []).map((_: number, i: number, arr: number[]) => (i >= arr.length - 7 ? (L.valid && L.ratio != null ? (ratioTone(L.ratio) === "ok" ? "info" : ratioTone(L.ratio)) : "info") : "muted"))} />
                <p className="mt-2 text-[11px] text-fg-3">barevně posledních 7 dní podle poměru 7 : 28</p>
              </div>
            </div>
          ),
          // railway#60 — cross-training is part of the all-activity (systemic) load
          systemic: <CrossTraining L={L} />,
          // railway#61 — descent by slope belongs to the Klesání channel
          ...(a?.gradientDescent?.buckets?.some((v: number) => v > 0) ? { descent: <DescentBySlope g={a.gradientDescent} /> } : {}),
        }} />
      )}
    </>
  )
}

function RecoveryTiles({ rcv, sleepEff }: { rcv: any; sleepEff: any }) {
  const [sleepOpen, setSleepOpen] = useState(false)
  const hrvBad = rcv.hrv.z <= -1, rhrBad = rcv.rhr.z >= 1.2, sleepBad = rcv.sleep.debt >= 4
  const tile = (label: string, info: string, now: any, unit: string, sub: string, bad: boolean, series: number[], extra?: any) => (
    <div className="nest flex min-w-0 flex-col p-3">
      <span className="flex items-start gap-1"><span className="t-label leading-4 !text-fg-3">{label}</span><InfoDot text={info} label={label} /></span>
      <p className="t-num mt-1.5 text-[24px] leading-none" style={{ color: bad ? C.alert : C.fg }}>{now}{unit && <small className="text-[12px] font-semibold text-fg-3"> {unit}</small>}</p>
      <p className="mt-1 text-[11px] leading-4 text-fg-3">{sub}</p>
      <div className="mt-auto pt-2"><Sparkline vals={series} color={bad ? C.alert : C.ok} /></div>
      {extra}
    </div>
  )
  return (
    <div>
      <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-3">
        {tile("HRV 7 dní", MI.hrv, rcv.hrv.now, "ms", `baseline ${rcv.hrv.base} ms · ${pctStr(rcv.hrv.now, rcv.hrv.base)}`, hrvBad, rcv.hrv.series)}
        {tile("Klidový tep", MI.rhr, rcv.rhr.now, "", `baseline ${rcv.rhr.base} · ${pctStr(rcv.rhr.now, rcv.rhr.base)}`, rhrBad, rcv.rhr.series)}
        {tile("Spánek", MI.sleep, rcv.sleep.now, "h", `obvykle ${rcv.sleep.base} h${rcv.sleep.debt > 0 ? ` · dluh ${rcv.sleep.debt} h/týd` : ""}`, sleepBad, rcv.sleep.series,
          sleepEff && (
            <button type="button" onClick={() => setSleepOpen((v) => !v)} aria-expanded={sleepOpen}
              className="mt-2 flex items-center justify-between gap-1 border-t border-white/[.07] pt-2 text-left text-[11px] font-semibold text-fg-2 transition hover:text-fg">
              <span>Kvalita spánku</span>
              <ChevronDown className={`size-3.5 transition ${sleepOpen ? "rotate-180 text-accent" : "text-fg-3"}`} aria-hidden />
            </button>
          ))}
      </div>
      {/* railway#62 — sleep quality opens under the sleep chart */}
      {sleepEff && sleepOpen && <div className="nest mt-2 origin-top animate-[careReveal_.28s_ease-out] p-3.5"><SleepQuality s={sleepEff} /></div>}
    </div>
  )
}

// Feedback railway#33 — sleep quality, not only length: efficiency (asleep / in bed)
// and the deep + REM share of the staged night against the runner's 8-week normal.
// Both feed readiness (at most half a signal — watch staging is approximate).
function SleepQuality({ s }: { s: any }) {
  const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)} %`)
  const restLow = s.restNow != null && s.restBase != null && s.restNow < s.restBase - 0.03
  const effLow = s.now != null && (s.now < 0.85 || (s.base != null && s.now < s.base - 0.02))
  const ln = s.lastNight
  const total = ln ? ln.deepMin + ln.remMin + ln.lightMin : 0
  const seg = (m: number, col: string, key: string) => total > 0 && <i key={key} className="block h-full" style={{ width: `${(m / total) * 100}%`, background: col }} />
  return (
    <div>
      <span className="flex items-center gap-1.5"><Label>Kvalita spánku</Label><InfoDot text={MI.sleepQuality} label="Kvalita spánku" /></span>
      <div className="mt-2 flex items-end gap-4">
        <div>
          <p className="t-num text-[30px]" style={{ color: restLow ? C.alert : undefined }}>{pct(s.restNow)}</p>
          <p className="text-[11px] text-fg-3">hluboký + REM{s.restBase != null ? ` · obvykle ${pct(s.restBase)}` : ""}</p>
        </div>
        <div>
          <p className="t-num text-[24px]" style={{ color: effLow ? C.alert : undefined }}>{pct(s.now)}</p>
          <p className="text-[11px] text-fg-3">efektivita{s.base != null ? ` · obvykle ${pct(s.base)}` : ""}</p>
        </div>
      </div>
      {ln && total > 0 && (
        <div className="mt-3">
          <div className="flex h-2 gap-px overflow-hidden rounded-full bg-white/[.08]">
            {seg(ln.deepMin, C.info, "d")}{seg(ln.remMin, C.accent, "r")}{seg(ln.lightMin, C.fg3, "l")}
          </div>
          <p className="mt-1 text-[11px] text-fg-3">poslední noc: hluboký {ln.deepMin} min · REM {ln.remMin} min · lehký {ln.lightMin} min{ln.awakeMin ? ` · vzhůru ${ln.awakeMin} min` : ""}</p>
        </div>
      )}
      <p className="mt-2 text-[11px] leading-4 text-fg-3">
        {s.restNow == null ? "Fáze spánku se načtou při další synchronizaci s Garminem. " : ""}
        {restLow || effLow ? "Méně kvalitní spánek než obvykle snižuje dnešní připravenost." : "Průměr 7 nocí proti vaší normě za 8 týdnů."}
      </p>
    </div>
  )
}

const SPORT_ICON: Record<string, LucideIcon> = { cycling: Bike, swimming: Waves, strength: Dumbbell, rowing: Ship, elliptical: Orbit, hiking: Mountain, walking: Footprints, other: ActivityIcon }

const CROSS_INFO = "Neběžecké sporty nepočítáme do běžeckých kilometrů ani do mechaniky, ale přispívají do celkové tréninkové zátěže (poměr 7:28 dní, monotónnost) i únavy. Zátěž se počítá z tepové odezvy (TRIMP), takže je porovnatelná napříč sporty."

// railway#55 — share of run vs other sport as a pie
function LoadPie({ run, cross }: { run: number; cross: number }) {
  const tot = run + cross || 1
  const f = cross / tot
  const R = 42, cx = 50, cy = 50
  const ang = f * 2 * Math.PI
  const x = cx + R * Math.sin(ang), y = cy - R * Math.cos(ang)
  const large = f > 0.5 ? 1 : 0
  return (
    <svg viewBox="0 0 100 100" className="size-28 shrink-0" role="img" aria-label={`běh ${Math.round((1 - f) * 100)} %, jiný sport ${Math.round(f * 100)} %`}>
      <circle cx={cx} cy={cy} r={R} fill={C.accent} />
      {f >= 0.999 ? <circle cx={cx} cy={cy} r={R} fill={C.info} />
        : f > 0.001 && <path d={`M${cx},${cy} L${cx},${cy - R} A${R},${R} 0 ${large} 1 ${x},${y} Z`} fill={C.info} />}
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="rgb(6 16 16)" strokeWidth="1.5" />
    </svg>
  )
}

function CrossTraining({ L }: { L: any }) {
  const list = (L.crossList || []) as any[]
  const run = L.runLoad7 || 0
  const cross = L.crossLoad7 || 0
  const head = (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <span className="flex items-center gap-1.5 whitespace-nowrap"><Label>Křížový trénink (7 dní)</Label><InfoDot text={CROSS_INFO} label="Křížový trénink" /></span>
      <span className="text-[12px] text-fg-3">započítáno do zátěže · j.z.</span>
    </div>
  )
  if (!list.length) {
    return <div>{head}<p className="mt-2 text-[12px] text-fg-3">Tento týden jen běh. Kolo, plavání nebo silovku z hodinek automaticky započítáme do celkové zátěže stejně jako běh.</p></div>
  }
  const tot = run + cross || 1
  const runPct = Math.round((run / tot) * 100)
  return (
    <div>
      {head}
      <div className="mt-3 flex flex-wrap items-center gap-5">
        <LoadPie run={run} cross={cross} />
        <div className="space-y-2">
          <p className="flex items-center gap-2"><i className="size-2.5 rounded-full bg-accent" /><span className="t-num text-[22px] text-accent">{L.runLoad7}</span><span className="text-[12px] text-fg-3">běh · {runPct} %</span></p>
          <p className="flex items-center gap-2"><i className="size-2.5 rounded-full bg-info" /><span className="t-num text-[22px] text-info">{L.crossLoad7}</span><span className="text-[12px] text-fg-3">jiný sport · {100 - runPct} %</span></p>
          <p className="text-[11px] text-fg-3">j.z. za 7 dní · {L.crossCount7} {L.crossCount7 === 1 ? "aktivita" : L.crossCount7 < 5 ? "aktivity" : "aktivit"}</p>
        </div>
      </div>
      <div className="mt-3 divide-y divide-white/[.07]">
        {list.map((c, i) => (
          <ListRow key={i} icon={SPORT_ICON[c.sport] || ActivityIcon} tone="info" title={c.sportLabel}
            meta={`${fmtD(c.date)} · ${c.durationMin} min${c.avgHr ? ` · ⌀ ${c.avgHr} tep` : ""}`}
            trailing={<span className="shrink-0 tabular-nums text-sm font-bold text-info">{c.load} j.z.</span>} />
        ))}
      </div>
    </div>
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
        <Card><UiEmpty icon={Dumbbell}>Žádný aktivní program.</UiEmpty></Card>
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
          <div className="mt-2 divide-y divide-white/[.07]">
            {ex.map((e) => (
              <div key={e.id} className="flex items-center gap-3 py-3">
                <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-accent/15 text-accent"><Dumbbell className="size-4" aria-hidden /></span>
                <div className="min-w-0 flex-1">
                  <b className="text-sm font-bold">{e.name}</b>
                  <span className="block text-[12px] text-fg-3">{e.dose} · {e.per_week}× týdně — {e.cue}</span>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(((e.done_count || 0) / (e.target_count || 12)) * 100)}%` }} /></div>
                </div>
                <span className="tabular-nums text-[12px] text-fg-2">{e.done_count}/{e.target_count}</span>
                <Button size="sm" variant="outline" onClick={async () => { await api.logEx(rid, e.id); toast({ title: "Zapsáno" }); refresh() }}>Hotovo</Button>
              </div>
            ))}
          </div>
        </Card>
        <div className="grid gap-4">
          <Card><Label>Jak to funguje</Label><p className="mt-2 text-sm text-fg-2">Cíl je 12 opakování každého cviku za 4 týdny. Když cvik provokuje bolest nad 3/10, je to informace pro fyzioterapeuta, ne důvod ho zatnout zuby dodělat.</p></Card>
          {(p.revisions || []).length > 0 && (
            <Card><Label>Změny v programu</Label><div className="mt-2 space-y-3">{p.revisions.slice().reverse().map((rv: any) => (
              <div key={rv.id}><b className="text-sm">{fmtD(rv.at)}</b><p className="text-[12px] text-fg-3">{rv.note}</p>{(rv.changes || []).map((c: string, i: number) => <div key={i} className="mt-1"><Chip>{c}</Chip></div>)}</div>
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
