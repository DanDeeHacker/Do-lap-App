import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { useQuadHistory } from "@/history"
import { AlertBanner, AxisLineChart, Bars, Button, Card, Chip, Empty as UiEmpty, FactorBar, toneCol, type Tone, Field, InfoDot, Label, ListRow, Metric, Ring, Segmented, Sheet, Slider, Sparkline, useAsync, useToast } from "@/ui"
import { Activity as ActivityIcon, Bike, ChevronDown, ChevronLeft, ChevronRight, CloudSun, Dumbbell, FileText, Footprints, Gauge, History, LoaderCircle, Mountain, Orbit, Ship, TriangleAlert, Waves, type LucideIcon } from "lucide-react"
import { Link } from "react-router"
import { METRIC_INFO as MI, MECH_INFO_BY_LABEL } from "@/metricinfo"
import { clamp, cz, czk, FEEL_LABEL, fmtD, fmtImpact, fmtSlot, paceStr, PHASE, plural, QUAD, sgn, toImpact } from "@/lib"
import MuscleAnatomy, { PainHeatmap, painKey, type BodyPoint } from "@/components/MuscleAnatomy"
import { CAP_SIGNAL_IDS, CapacityPanel, readinessCol, readinessPct } from "@/capacity"
import { C, goodCol } from "@/tokens"
import { SelfPrograms } from "@/selfprograms"
import { FirstSteps, NoData, useDataStage } from "@/firstday"

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
// Cross-training in the journal: cycling, swimming and strength (rated by session RPE,
// Foster et al. 2001, plus how the legs feel — the "breathing vs legs" split of
// Vanrenterghem et al. 2017). Strength sessions also say what was trained.
const SPORT_OPTS = [["cycling", "Kolo"], ["swimming", "Plavání"], ["strength", "Posilování"]] as const
const FOCUS_OPTS = [["lower", "Nohy"], ["full", "Celé tělo"], ["upper", "Horní polovina"]] as const
const STYPE_OPTS = [["heavy", "Těžké"], ["explosive", "Výbušné"], ["plyo", "Plyometrie"], ["circuit", "Kruhový"]] as const
const isCross = (a: any) => !!a && !!a.sport && a.sport !== "running"
const actTitle = (a: any) => (isCross(a) ? `${a.title} · ${Math.round(a.duration_min || 0)} min` : `${a.title} · ${cz(a.distance_km)} km`)
const actIcon = (a: any) => (isCross(a) ? SPORT_ICON[a.sport] || ActivityIcon : a?.surface === "trail" ? Mountain : Footprints)

function CrossSheet({ rid, onClose, onDone }: { rid: string; onClose: () => void; onDone: () => void }) {
  const [sport, setSport] = useState<"cycling" | "swimming" | "strength">("strength")
  const [date, setDate] = useState(dayAgo(0))
  const [dur, setDur] = useState(45)
  const [rpe, setRpe] = useState(6)
  const [legs, setLegs] = useState(3)
  const [focus, setFocus] = useState<"lower" | "full" | "upper">("lower")
  const [stype, setStype] = useState<"heavy" | "explosive" | "plyo" | "circuit">("heavy")
  const [note, setNote] = useState("")
  const { busy, err, run } = useAsync()
  const toast = useToast()
  const submit = () => run(async () => {
    await api.addManualActivity(rid, {
      sport, date, duration_min: dur, rpe, legs, note: note || null,
      ...(sport === "strength" ? { strength_focus: focus, strength_type: stype } : {}),
    })
    toast({ title: "Trénink zapsán", msg: `${SPORT_OPTS.find((o) => o[0] === sport)![1]} · ${dur} min` })
    onDone()
  })
  return (
    <Sheet open onClose={onClose} footer={
      <div className="flex gap-2">
        <button onClick={submit} disabled={busy} className="btn btn-primary flex-1 py-3 text-sm">{busy ? "Ukládám…" : "Uložit trénink"}</button>
        <button onClick={onClose} className="btn btn-outline px-5 py-3 text-sm">Zrušit</button>
      </div>
    }>
      <h2 className="font-serif text-2xl leading-tight">Jiný sport</h2>
      <p className="mt-1 text-[13px] text-fg-2">Trénink, který hodinky nezaznamenaly. Když ho později naimportují, zápis se k němu přesune.</p>
      <div className="mt-4 grid gap-4">
        <Segmented ariaLabel="Sport" options={SPORT_OPTS as any} value={sport} onChange={setSport as any} />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Datum"><input type="date" value={date} max={dayAgo(0)} onChange={(e) => setDate(e.target.value)} className="w-full rounded-xl border px-3 py-2 text-sm" /></Field>
          <Field label="Délka (min)"><input type="number" inputMode="numeric" min={5} max={600} value={dur} onChange={(e) => setDur(Number(e.target.value))} className="w-full rounded-xl border px-3 py-2 text-sm" /></Field>
        </div>
        <Field label="Náročnost celého tréninku" hint="0 klid · 10 maximum, ohodnoťte asi půl hodiny po tréninku"><Slider name="xrpe" min={0} max={10} value={rpe} onChange={setRpe} /></Field>
        <Field label="Nohy po tréninku" hint="1 těžké · 5 svěží"><Slider name="xlegs" min={1} max={5} value={legs} onChange={setLegs} /></Field>
        {sport === "strength" && (
          <>
            <Field label="Co jste posilovali"><Segmented ariaLabel="Zaměření" options={FOCUS_OPTS as any} value={focus} onChange={setFocus as any} /></Field>
            <Field label="Typ tréninku"><Segmented ariaLabel="Typ posilování" size="sm" options={STYPE_OPTS as any} value={stype} onChange={setStype as any} /></Field>
          </>
        )}
        <Field label="Poznámka"><textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="Co jste dělali…" /></Field>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
    </Sheet>
  )
}

export function Post() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const [rate, setRate] = useState<{ act: any; initial?: any } | null>(null)
  const [crossOpen, setCrossOpen] = useState(false)
  const toastX = useToast()
  // railway#193 — no "Jiný sport" block here any more (other sports sit in the lists with
  // the runs); Trénink's "Zapsat do deníku" for a cross session still opens the form
  useEffect(() => {
    if (window.location.hash === "#jiny-sport") {
      setCrossOpen(true)
      history.replaceState(null, "", window.location.pathname)
    }
  }, [])
  // feedback #155: the "Zapsat běh" button opens the note for that activity straight away
  const wantRate = window.location.hash.startsWith("#zapsat-") ? window.location.hash.slice(8) : null
  useEffect(() => {
    if (!wantRate) return
    const x = ((boot?.activities || []) as any[]).find((a) => String(a.id) === wantRate)
    if (x) {
      setRate({ act: x })
      history.replaceState(null, "", window.location.pathname)
    }
  }, [wantRate, boot?.activities])
  const [insOpen, setInsOpen] = useState(false)
  const [latestOpen, setLatestOpen] = useState(false)
  const [ciOpen, setCiOpen] = useState(false)
  const fb = (boot?.activity_feedback || []) as any[]
  const acts = (boot?.activities || []) as any[]
  const cutoff = dayAgo(14)
  const rated = new Set(fb.map((f) => f.activity_id))
  const unrated = acts.filter((a) => a.started_at > cutoff && !rated.has(a.id) && (!a.excluded || a.excluded_scope === "mech"))
  const actById = useMemo(() => new Map(acts.map((a) => [a.id, a])), [acts])
  const sorted = useMemo(() => fb.slice().sort((x, y) => y.submitted_at.localeCompare(x.submitted_at)), [fb])
  const ov = useMemo(() => diaryOverview(fb), [fb])
  const crossRecent = acts.filter((a) => isCross(a) && a.started_at > cutoff).sort((x, y) => y.started_at.localeCompare(x.started_at))
  const rpeOf = useMemo(() => new Map(fb.map((f) => [f.activity_id, f.rpe])), [fb])

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

  // railway#144 — the check-in summary sits under the diary summary, above the pain map
  const ciBlock = (
    <>
            {!ciSum && (
              <div className="mt-5 border-t border-white/[.08] pt-4">
                <Label>Souhrn check-inů</Label>
                <p className="mt-2 text-[12px] text-fg-3">Zatím žádné check-iny. Přidejte první přes tlačítko Check-in vpravo dole.</p>
              </div>
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
                {/* railway#134 — every check-in opens as a detail of their summary */}
                <button type="button" onClick={() => setCiOpen((v) => !v)} aria-expanded={ciOpen} data-testid="checkins-toggle"
                  className="nest mt-4 flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left transition hover:border-white/20">
                  <span className="t-label">Check-iny (denní a týdenní)</span>
                  <span className="flex items-center gap-2 text-[12px] text-fg-3">{Math.min(10, checkinItems.length)}<ChevronDown className={`size-4 transition ${ciOpen ? "rotate-180 text-accent" : ""}`} aria-hidden /></span>
                </button>
                {ciOpen && (
                  <div className="mt-1 origin-top animate-[careReveal_.28s_ease-out]" data-testid="checkins-list">
                    <div className="divide-y divide-white/[.07]">
                      {checkinItems.slice(0, 10).map((x: any) => {
                        const daily = x.kind === "daily"
                        const hurt = daily ? (x.pain || 0) >= 4 : (x.severity || 0) >= 40
                        return (
                          <ListRow key={x.id} tileText={daily ? "DEN" : "TÝD"} tone={daily ? "info" : "self"}
                            title={daily ? "Denní check-in" : x.adhoc ? "Týdenní check-in · mimořádný" : "Týdenní check-in"}
                            meta={<>{fmtD(x.at)}{daily
                              ? `${x.pain != null ? ` · bolest ${x.pain}/10` : ""}${x.mood != null ? ` · nálada ${x.mood}/4` : ""}${x.fatigue != null ? ` · únava ${x.fatigue}` : ""}`
                              : ` · OSTRC ${x.severity ?? 0}/100 · ${x.status === "active" ? "aktivní" : x.status === "resolved" ? "odezněl" : "bez potíží"}`}</>}
                            extra={x.regions.length > 0 ? <span className="mt-1.5 block"><Chip tone={hurt ? "alert" : "muted"}>{x.regions.slice(0, 2).join(", ")}{x.regions.length > 2 ? "…" : ""}</Chip></span> : undefined} />
                        )
                      })}
                    </div>
                    <p className="mt-2 text-[11px] leading-4 text-fg-3">Denní pocit a bolest a týdenní kontrola (OSTRC), mimo konkrétní běh. Přidáte je tlačítkem Check-in.</p>
                  </div>
                )}
              </div>
            )}
    </>
  )

  return (
    <>
      <Head
        kicker="Deník běhů"
        title={unrated.length ? `${unrated.length} ${plural(unrated.length, "běh čeká", "běhy čekají", "běhů čeká")} na zápis` : acts.length ? "Deník máte kompletní" : "Zatím žádný běh"}
      />
      {/* UX audit F19 — an empty diary said "complete"; say where the runs come from */}
      {!acts.length && <FirstSteps className="-mt-2 mb-4" />}
      {rate && <RateSheet act={rate.act} initial={rate.initial} rid={rid} onClose={() => setRate(null)} onDone={() => { setRate(null); refresh() }} />}
      {crossOpen && <CrossSheet rid={rid} onClose={() => setCrossOpen(false)} onDone={() => { setCrossOpen(false); refresh() }} />}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_.8fr]">
        <div className="grid content-start gap-4">
          {/* railway#135/#136 — one box: runs waiting for a note, the latest notes as a detail under
              them, and the other sports of the last 14 days */}
          <Card>
            <Label>Čeká na zápis</Label>
            {unrated.length ? (
              <div className="mt-2 divide-y divide-white/[.07]">
                {unrated.map((x) => (
                  <ListRow key={x.id} onClick={() => setRate({ act: x })} icon={actIcon(x)} tone="info"
                    title={actTitle(x)}
                    meta={isCross(x) ? `${fmtD(x.started_at)} · jiný sport${x.avg_hr ? ` · ${Math.round(x.avg_hr)} tep/min` : ""}` : `${fmtD(x.started_at)} · ${surf(x.surface)} · ${paceStr(x.pace_s_km)}/km · ${cz(x.descent_m)} m klesání`}
                    trailing={<span className="btn btn-primary btn-sm shrink-0">Zapsat</span>} />
                ))}
              </div>
            ) : (
              <div className="mt-3"><Empty>{acts.length ? "Nic nečeká. Další zápis se objeví po příštím běhu." : "Zatím žádný běh. Po synchronizaci hodinek se tu nové běhy objeví k zapsání."}</Empty></div>
            )}
            {sorted.length > 0 && (
              <>
                <button type="button" onClick={() => setLatestOpen((v) => !v)} aria-expanded={latestOpen} data-testid="latest-toggle"
                  className="nest mt-4 flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left transition hover:border-white/20">
                  <span className="t-label">Poslední zápisy</span>
                  <span className="flex items-center gap-2 text-[12px] text-fg-3">{Math.min(10, sorted.length)}<ChevronDown className={`size-4 transition ${latestOpen ? "rotate-180 text-accent" : ""}`} aria-hidden /></span>
                </button>
                {latestOpen && (
                  <div className="mt-1 origin-top animate-[careReveal_.28s_ease-out] divide-y divide-white/[.07]" data-testid="latest-list">
                    {/* feedback #176/#177 — every sport in one list, read only (a rating is given once) */}
                    {sorted.slice(0, 10).map((f) => {
                      const act = actById.get(f.activity_id)
                      const hurt = f.pain_during >= 4
                      const cross = act && isCross(act)
                      return (
                        <div key={f.id} className="flex items-center gap-1">
                          <ListRow icon={actIcon(act)} tone={hurt ? "alert" : "ok"}
                            title={act ? actTitle(act) : "Běh"}
                            meta={cross
                              ? `${fmtD(f.submitted_at)}${f.rpe != null ? ` · náročnost ${f.rpe}/10` : ""}${act.strength_focus ? ` · ${(FOCUS_OPTS.find((o) => o[0] === act.strength_focus) || [0, ""])[1]}` : ""}${act.provider === "manual" ? " · zapsáno ručně" : ""}`
                              : <>{fmtD(f.submitted_at)}{act?.surface ? ` · ${surf(act.surface)}` : ""} · pocit {FEEL_LABEL[f.feeling] || "—"} · nohy {f.legs}/5{f.pain_during > 0 ? ` · bolest ${f.pain_during}/10` : ""}</>}
                            extra={f.pain_site ? <span className="mt-1.5 block sm:hidden"><Chip tone="alert">{f.pain_site}</Chip></span> : undefined}
                            trailing={f.pain_site ? <span className="hidden shrink-0 sm:block"><Chip tone="alert">{f.pain_site}</Chip></span> : undefined} />
                          {cross && act.provider === "manual" ? (
                            <button type="button" onClick={() => { api.deleteActivity(rid, act.id).then(() => { toastX({ title: "Trénink smazán" }); refresh() }).catch(() => {}) }}
                              className="shrink-0 rounded-full px-2 py-1 text-[12px] font-bold text-fg-3 hover:bg-alert/10 hover:text-alert">Smazat</button>
                          ) : act && !cross ? (
                            <Link to={`/app/post/${act.id}`} aria-label="Detail běhu" title="Detail běhu"
                              className="grid size-9 shrink-0 place-items-center rounded-full text-fg-3 hover:bg-info/10 hover:text-info">
                              <ActivityIcon className="size-4" aria-hidden />
                            </Link>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
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
                <div data-tour="journal-summary">
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
                </div>
                {ciBlock}
                {Object.keys(ov.painMap).length > 0 && (
                  <div className="mt-4 border-t border-white/[.08] pt-4">
                    <Label>Kde to nejčastěji bolí</Label>
                    <p className="mt-1 text-[12px] leading-5 text-fg-3">Podle zápisů za posledních 30 dní — čím výraznější místo, tím častěji se v zápisech objevuje jako bolestivé.</p>
                    <div className="mt-3"><PainHeatmap counts={ov.painSided} /></div>
                    <div className="mt-4 space-y-1.5" data-tour="journal-sites">
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
              <>
                <div className="mt-3"><Empty>Zatím málo zápisů na to, aby z nich šel číst vzorec. Užitečné to začne být zhruba od čtvrtého.</Empty></div>
                {ciBlock}
              </>
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
  const painSided: Record<string, number> = {}   // keyed like the heatmap hotspots (region + side)
  rows.filter((f) => f.submitted_at >= cut30).forEach((f) => {
    ((f.pain_points || []) as any[]).forEach((p) => {
      if (!p?.region) return
      painMap[p.region] = (painMap[p.region] || 0) + 1
      painSided[painKey(p)] = (painSided[painKey(p)] || 0) + 1
    })
  })
  const topSites = Object.entries(painMap).sort((a, b) => b[1] - a[1])
  const topSite = topSites[0]

  const insights: { text: string; tone: "ok" | "watch" | "alert" }[] = []
  if (niggleCount >= 3) insights.push({ text: `Bolest se v zápisech objevila ${niggleCount}× — na náhodu už je toho dost. Stojí za to sledovat, u jakého typu běhu se vrací.`, tone: "alert" })
  else if (niggleCount > 0) insights.push({ text: `Bolest se objevila ${niggleCount}×, zatím ojediněle. Držte oči na tom, jestli se neopakuje.`, tone: "watch" })
  else insights.push({ text: "Žádnou bolest jste v zápisech neměl — pokračujte stejně.", tone: "ok" })
  if (topSite && topSite[1] >= 2) insights.push({ text: `Nejčastěji se ozývá ${topSite[0]} (${topSite[1]}×). Opakující se místo bereme vážněji než jednorázové.`, tone: "watch" })
  if (feelingTrend <= -0.6) insights.push({ text: "Pocit z běhů poslední týdny klesá. Bývá to první signál únavy dřív, než to ukážou čísla — zvažte lehčí týden.", tone: "watch" })
  else if (feelingTrend >= 0.6) insights.push({ text: "Pocit z běhů roste, forma jde nahoru.", tone: "ok" })
  if (mean(legs) <= 2.4 && legs.length >= 4) insights.push({ text: "Nohy hodnotíte často jako těžké. Zkuste přidat regenerační den nebo zkrátit dlouhý běh.", tone: "watch" })

  return { n: rows.length, n21, feelingMean, feelingTrend, legsMean: mean(legs), niggleCount, painMax, topSite, topSites, painMap, painSided, insights }
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
  const cross = isCross(act)
  const [focus, setFocus] = useState<string>(act.strength_focus || "lower")
  const [stype, setStype] = useState<string>(act.strength_type || "heavy")

  const submit = () =>
    run(async () => {
      const pts = points.map((p) => ({ region: p.region, side: p.side || null, severity: pain, type: p.kind }))
      const site = points.length ? points.map((p) => p.region).join(", ") : null
      await api.rateActivity(rid, act.id, {
        feeling, legs, stiffness_pre: stiff, rpe, pain_during: pain, pain_site: site,
        pain_points: pts, niggle: pain >= 2, note: note || null,
        ...(act.sport === "strength" ? { strength_focus: focus, strength_type: stype } : {}),
      })
      toast({ title: edit ? "Zápis upraven" : "Zápis uložen", msg: `${act.title}${act.distance_km ? ` · ${cz(act.distance_km)} km` : ""}` })
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
      <h2 className="font-serif text-2xl leading-tight">{edit ? "Upravit zápis" : cross ? actTitle(act) : `${act.title}${act.distance_km ? ` · ${cz(act.distance_km)} km` : ""}`}</h2>
      <p className="mt-1 text-[13px] text-fg-2">{fmtD(act.started_at)}{act.pace_s_km ? ` · ${paceStr(act.pace_s_km)}/km` : ""}{act.surface ? ` · ${surf(act.surface)}` : ""}{act.descent_m ? ` · ${cz(act.descent_m)} m sklesáno` : ""}</p>
      {act.auto_excluded === "treadmill" && act.excluded && (
        <p className="mt-3 rounded-[12px] border border-watch/30 bg-watch/[.07] p-3 text-[12px] leading-5 text-fg-soft" data-testid="rate-auto-excluded">
          {AUTO_TREADMILL_TEXT} <Link to={`/app/mechanics#beh-${act.id}`} onClick={onClose} className="font-bold text-accent">Zobrazit v historii běhů →</Link>
        </p>
      )}
      <div className="mt-4 grid gap-x-6 gap-y-4 md:grid-cols-2">
        <div>
          {cross ? (
            <Field label="Náročnost celého tréninku" hint="0 klid · 10 maximum"><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>
          ) : <Field label="Jak ztuhlé byly nohy PŘED během" hint="1 uvolněné · 5 ztuhlé"><Slider name="stiff" min={1} max={5} value={stiff} onChange={setStiff} /></Field>}
          {act.sport === "strength" && (
            <>
              <Field label="Co jste posilovali"><Segmented ariaLabel="Zaměření" options={FOCUS_OPTS as any} value={focus} onChange={setFocus as any} /></Field>
              <Field label="Typ tréninku"><Segmented ariaLabel="Typ posilování" size="sm" options={STYPE_OPTS as any} value={stype} onChange={setStype as any} /></Field>
            </>
          )}
          <Field label="Jak vám bylo"><Slider name="feeling" min={1} max={5} value={feeling} onChange={setFeeling} labels={FEEL_LABEL} /></Field>
          <Field label="Nohy" hint="1 těžké · 5 svěží"><Slider name="legs" min={1} max={5} value={legs} onChange={setLegs} /></Field>
          {!cross && <Field label="Vnímaná námaha (RPE)" hint={`hodinky ${act.rpe || "—"}/10`}><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>}
          <Field label={cross ? "Bolest během tréninku" : "Bolest během běhu"} hint="0 žádná"><Slider name="pain" min={0} max={10} value={pain} onChange={setPain} tone="pain" /></Field>
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
type Metric = { label: string; unit: string; dec: number; value: number; baseline: number; z: number; delta: string; hot: boolean; position: number; weeks: number[]; dates: string[]; series: number[]; seriesDates: string[]; terrain?: boolean; approx?: boolean; refSd?: number | null; lowRes?: boolean }

// Plan phase 3 — a word for where a metric sits against the runner's own norm,
// derived from the continuous deviation for display only. Defaults follow the
// example bands in Thornton et al. (2019): |z| 1.5–2 = on the edge, ≥ 2 = outside.
const MECH_BAD_DIR: Record<string, number> = { "Vertikální poměr": 1, "Kontakt se zemí": 1, "Kadence": -1, "Vertikální oscilace": 1 }
// UX audit F09 — the word follows the engine's signal for the metric as well: a metric that
// is a signal on Dnes is never "v normě" here, and one without a signal is never "mimo normu"
const MECH_SIG_ID: Record<string, string> = { "Vertikální poměr": "tavr", "Kontakt se zemí": "gct", "Symetrie kontaktu": "bal", "Kadence": "cad", "Vertikální oscilace": "vosc" }
export function normStatus(m: Pick<Metric, "label" | "z">, sigIds?: Set<string>): { word: string; tone: "ok" | "watch" | "alert" } {
  const dir = MECH_BAD_DIR[m.label]
  const zb = m.label === "Symetrie kontaktu" ? Math.abs(m.z) / 0.8 : dir ? dir * m.z : Math.abs(m.z)
  const own = zb >= 2 ? 2 : zb >= 1.5 ? 1 : 0
  const id = MECH_SIG_ID[m.label]
  const lvl = !sigIds || !id ? own : sigIds.has(id) ? Math.max(own, 1) : Math.min(own, 1)
  return lvl === 2 ? { word: "mimo normu", tone: "alert" } : lvl === 1 ? { word: "na hraně", tone: "watch" } : { word: "v normě", tone: "ok" }
}

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
export function usualRange(m: Metric) {
  // plan phase 3: the individual reference SD from the backend when population priors exist
  const fallback = Math.abs(m.baseline) * 0.03 || 1
  let isd = m.refSd ? m.refSd : Math.abs(m.z) > 0.15 ? Math.abs(m.value - m.baseline) / Math.abs(m.z) : fallback
  // The SD is backed out of (value − baseline) / z. When the two means round to the
  // same number (1,07 → 1,07) while z ≠ 0, that gives 0 — a zero-width range, and the
  // bar's scale divides by zero (bug report 2026-10-02: no band, the dot at the far left).
  // Keep the range at least 1 % of the baseline wide.
  if (!Number.isFinite(isd) || isd < Math.abs(m.baseline) * 0.01) isd = fallback
  return { lo: m.baseline - isd, hi: m.baseline + isd, isd }
}

// Feedback #164 — a cadence below 160 steps/min (the app's working threshold) gets a
// warning with the research behind it; runs below it are marked in the run history.
export const LOW_CADENCE = 160
export const LOW_CADENCE_TEXT =
  "Kadence pod 160 kroků za minutu. Nižší kadence při stejném tempu znamená delší krok a větší zatížení kolene a kyčle " +
  "v každém kroku: zvýšení kadence o 5–10 % ho v laboratoři snížilo (Heiderscheit et al., 2011). U středoškolských běžců " +
  "s kadencí pod 166 kroků za minutu byla častější zranění holeně (Luedke et al., 2016). Že nízká kadence sama zranění " +
  "předpovídá, ale zatím spolehlivě doloženo není, a hranice 160 je pracovní práh aplikace. Kadence klesá i s pomalejším " +
  "tempem. Pokud ji chcete zvýšit, přidávejte nejvýš 5–10 % a ideálně to proberte s fyzioterapeutem."
export function LowCadenceAlert({ className = "" }: { className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span className={className} onClick={(e) => e.stopPropagation()}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="Nízká kadence — podrobnosti" data-testid="low-cadence"
        className="inline-grid size-6 place-items-center rounded-full bg-watch/15 text-watch"><TriangleAlert className="size-3.5" aria-hidden /></button>
      {open && <span className="mt-2 block w-full basis-full rounded-[12px] border border-watch/30 bg-watch/[.07] p-3 text-[12px] leading-5 text-fg-soft">{LOW_CADENCE_TEXT}</span>}
    </span>
  )
}

function MechMetricCard({ m, open, onSelect, sigIds }: { m: Metric; open: boolean; onSelect: () => void; sigIds?: Set<string> }) {
  const { label, unit, dec, value, baseline, delta, approx } = m
  const st = normStatus(m, sigIds)
  const hot = st.tone !== "ok"
  // Numeric axis for the interval bar, so the bar shows real numbers, not just a dot.
  const { lo: bLo, hi: bHi, isd } = usualRange(m)
  const dLo = Math.min(bLo, value) - isd * 0.8, dHi = Math.max(bHi, value) + isd * 0.8
  const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 4, 96)
  const showBar = open || Math.abs(m.z) >= 1
  const col = st.tone === "alert" ? C.alert : st.tone === "watch" ? C.watch : C.ok
  return (
    <div onClick={onSelect} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect() } }}
      role="button" tabIndex={0} aria-expanded={open} className="group w-full cursor-pointer p-4 text-left">
      <div className="flex items-center gap-3">
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <span className="text-[14px] font-bold text-fg">{label}</span>
          <span data-norm={st.word} className="rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold" style={{ color: col, background: `${col}1f` }}>{st.word}</span>
          {MECH_INFO_BY_LABEL[label] && <InfoDot text={MECH_INFO_BY_LABEL[label]} label={label} />}
          {label === "Kadence" && value < LOW_CADENCE && <LowCadenceAlert className="contents" />}
          {m.lowRes && <span title="Hodinky tuto metriku měří s větším šumem, než je nejmenší smysluplná změna, proto se do skóre počítá polovinou." className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-fg-2">nízká přesnost</span>}
          {approx && <span title="Málo dat v jednotlivých profilech terénu — hrubý odhad z průměru běhů napříč terénem, ne terénně očištěná odchylka enginu." className="rounded-full bg-white/[.06] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-fg-2">odhad</span>}
        </span>
        <strong className="t-num shrink-0 whitespace-nowrap text-[20px] leading-none text-fg">
          {mfmt(dec, value)} <span className="text-[13px] font-semibold tracking-normal text-fg-3">{unit}</span>
        </strong>
        <span className={`shrink-0 whitespace-nowrap rounded-full px-2 py-1 text-[11px] font-bold ${st.tone === "alert" ? "bg-alert/15 text-alert-soft" : st.tone === "watch" ? "bg-watch/15 text-watch" : "bg-ok/12 text-ok"}`}
          title={`${st.word} · ${delta}`}>{delta}</span>
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
            <span className="absolute -top-6 -translate-x-1/2 whitespace-nowrap tabular-nums text-[12px] font-extrabold" style={{ left: `${P(value)}%`, color: st.tone === "alert" ? C.alertSoft : st.tone === "watch" ? C.watch : C.ok }}>{mfmt(dec, value)}</span>
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
// line up with the backend's terrain-aware baselines. v0.9.0: the pace classes are
// the runner's own tertiles when the engine has them (confidence.paceCuts), so a
// runner whose every run is "slow" by the fixed 4:30 / 5:30 cuts still gets three.
const PACE_CUTS_FIXED: [number, number] = [270, 330]
function bucketKey(a: any, cuts: [number, number] = PACE_CUTS_FIXED): string {
  const km = Math.max(a.distance_km || 0, 1)
  const asc = (a.ascent_m || 0) / km, desc = (a.descent_m || 0) / km
  const g = desc - asc > 12 ? "down" : asc - desc > 12 ? "up" : asc + desc >= 30 ? "rolling" : "flat"
  const p = ((a.duration_min || 0) / km) * 60
  const pb = p < cuts[0] ? "fast" : p < cuts[1] ? "mod" : "easy"
  return `${a.surface}|${g}|${pb}`
}
const bucketParts = (b: string) => { const [s, g, p] = b.split("|"); return { surf: _SURF[s] || s, grade: _GRADE[g] || g, pace: _PACE[p] || p } }

type Cell = { now: number | null; avg6: number; z: number | null; base: number | null } | null
const TERRAIN_DAYS = 182   // the terrain comparison looks 6 months back, so every profile has runs to show
// Per terrain profile × per metric: recent mean and its drift-z against the
// same profile's baseline — same windows/logic as engine._drift_z_core.
function terrainCompare(acts: any[], cuts?: [number, number]) {
  const since = dayAgo(TERRAIN_DAYS), rec = dayAgo(28)
  const byB: Record<string, any[]> = {}
  for (const a of acts) {
    if (!a.started_at || a.started_at <= since || (a.sport && a.sport !== "running")) continue
    ;(byB[bucketKey(a, cuts)] ||= []).push(a)
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
  const { boot } = useApp()
  const pc = boot?.assessment?.confidence?.paceCuts
  const cuts: [number, number] | undefined = Array.isArray(pc) && pc.length === 2 ? [pc[0], pc[1]] : undefined
  const { profiles, rows } = useMemo(() => terrainCompare(acts, cuts), [acts, cuts?.[0], cuts?.[1]])
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
  const temp = w.precision === "hour" ? `${cz(w.tempC)} °C` : `${cz(w.tMin)}–${cz(w.tMax)} °C`
  const extra = [w.windKmh != null && `${cz(w.windKmh)} km/h`, w.precipMm > 0 && `${cz1(w.precipMm)} mm`].filter(Boolean)
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
            {row("Stoupání", t.ascentM != null && `${cz(t.ascentM)} m${t.ascPerKm != null ? ` · ${cz1(t.ascPerKm)} m/km` : ""}`)}
            {row("Klesání", t.descentM != null && `${cz(t.descentM)} m${t.descPerKm != null ? ` · ${cz1(t.descPerKm)} m/km` : ""}`)}
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
              {row("Teplota", w.precision === "hour" ? `${cz(w.tempC)} °C · pocitově ${cz(w.feelsC)} °C` : `${cz(w.tMin)}–${cz(w.tMax)} °C · pocitově až ${cz(w.feelsC)} °C`)}
              {row("Vlhkost", w.humidity != null && `${w.humidity} %`)}
              {row(w.precision === "hour" ? "Vítr" : "Vítr (max.)", w.windKmh != null && `${cz(w.windKmh)} km/h`)}
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

export const AUTO_TREADMILL_TEXT =
  "Běh na pásu se automaticky nepočítá do mechaniky, protože jeho metriky výrazně vybočily z vaší normy z běhů venku " +
  "(pás mívá jinou kalibraci rychlosti, bez větru a s jiným odrazem)."
function RunHistoryReal({ acts }: { acts: any[] }) {
  const { me, refresh } = useApp()
  const rid = me?.runner_id
  // feedback #165: the diary links to one run here (#beh-<id>) — open the list on it
  const wantRun = window.location.hash.startsWith("#beh-") ? Number(window.location.hash.slice(5)) : null
  const [open, setOpen] = useState(!!wantRun)
  const [run, setRun] = useState<number | null>(wantRun)
  useEffect(() => {
    if (!wantRun) return
    setTimeout(() => document.getElementById(`beh-${wantRun}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 700)
  }, [wantRun])
  const [ctx, setCtx] = useState<any[] | null | false>(null) // null = not loaded, false = failed
  useEffect(() => {
    if (!open || !rid || ctx !== null) return
    let alive = true
    api.runHistory(rid, 20).then((d) => alive && setCtx(Array.isArray(d) ? d : false)).catch(() => alive && setCtx(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rid])
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
            const tl = terrainLine(x.terrain)
            const wl = weatherLine(x.weather)
            return (
              <div key={x.id} id={`beh-${x.id}`} className={`scroll-mt-24 overflow-hidden rounded-[18px] border transition ${isOpen ? "border-info/40 bg-panel-2" : "border-white/[.08] bg-white/[.03] hover:border-white/15"} ${x.excluded ? "opacity-60" : ""}`}>
                <button onClick={() => setRun(isOpen ? null : x.id)} aria-expanded={isOpen} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left">
                  <span className="grid size-[34px] place-items-center rounded-[10px] bg-info/15 text-info">{x.surface === "trail" ? <Mountain className="size-4" aria-hidden /> : <Footprints className="size-4" aria-hidden />}</span>
                  <span className="min-w-0">
                    <b className="text-sm font-bold">{x.title}</b>
                    {x.excluded && <span title={x.auto_excluded === "treadmill" ? AUTO_TREADMILL_TEXT : undefined} className={`ml-2 rounded-full px-2 py-0.5 align-middle text-[11px] font-bold uppercase tracking-[.08em] ${x.auto_excluded ? "bg-watch/15 text-watch" : "bg-white/[.08] text-fg-2"}`}>{x.auto_excluded === "treadmill" ? "pás · automaticky bez mechaniky" : (x.excluded_scope || "all") === "all" ? "vyřazeno" : x.excluded_scope === "mech" ? "bez mechaniky" : "bez zátěže"}</span>}
                    {x.cadence_spm != null && x.cadence_spm < LOW_CADENCE && <span title={LOW_CADENCE_TEXT} data-testid="run-low-cadence" className="ml-2 rounded-full bg-watch/15 px-2 py-0.5 align-middle text-[11px] font-bold uppercase tracking-[.08em] text-watch">kadence {Math.round(x.cadence_spm)}</span>}
                    {x.postStrength && <span title="Do 48 hodin po těžkém posilování nohou se technika běhu mění (Doma et al., 2017), proto se tento běh do driftu mechaniky počítá polovinou." className="ml-2 rounded-full bg-self/15 px-2 py-0.5 align-middle text-[11px] font-bold uppercase tracking-[.08em] text-self">po posilovně</span>}
                    <span className="block text-[12px] text-fg-3">{fmtD(x.started_at)}{x.start_time ? ` ${x.start_time}` : ""} · {surf(x.surface)} · {cz(x.distance_km)} km · {paceStr(x.pace_s_km)}/km · {x.avg_hr} tep</span>
                    {(tl || wl) && (
                      <span className="mt-1.5 flex flex-wrap gap-1.5">
                        {tl && <span className="inline-flex items-center gap-1 rounded-full bg-info/12 px-2 py-0.5 text-[11px] font-semibold text-info"><Mountain className="size-3" aria-hidden />{tl}</span>}
                        {wl && <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${x.weather?.hot && x.weather.precision === "hour" ? "bg-watch/12 text-watch" : "bg-self/12 text-self"}`}><CloudSun className="size-3" aria-hidden />{wl}</span>}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-2 whitespace-nowrap tabular-nums text-[12px] text-fg-2">VR {cz(x.vert_ratio_pct)} <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180 text-info" : ""}`} aria-hidden /></span>
                </button>
                {isOpen && rid && (
                  <RunFlip initial="move"
                    move={<MovementRunPanel rid={rid} x={x} hasCtx={!!ctx} onExcluded={(ex, scope) => {
                      setCtx((c) => (c ? c.map((r: any) => (r.id === x.id ? { ...r, excluded: ex, excluded_scope: scope } : r)) : c))
                      refresh()
                    }} />}
                    load={<LoadRunPanelById rid={rid} aid={x.id} />} />
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}

// Feedback #147 — one run, two faces: its movement detail (Pohyb) and its load detail
// (Zátěž). Swipe right → Zátěž, swipe left → Pohyb, or tap the switch; the card flips.
function RunFlip({ move, load, initial }: { move: ReactNode; load: ReactNode; initial: "move" | "load" }) {
  const [face, setFace] = useState<"move" | "load">(initial)
  const [anim, setAnim] = useState(0)
  const start = useRef<{ x: number; y: number } | null>(null)
  const go = (f: "move" | "load") => { if (f !== face) { setFace(f); setAnim((n) => n + 1) } }
  return (
    <div className="border-t border-white/[.07]" data-testid="run-flip"
      onTouchStart={(e) => { const t = e.touches[0]; start.current = { x: t.clientX, y: t.clientY } }}
      onTouchEnd={(e) => {
        const s0 = start.current; start.current = null
        if (!s0) return
        const t = e.changedTouches[0], dx = t.clientX - s0.x, dy = t.clientY - s0.y
        if (Math.abs(dx) > 60 && Math.abs(dx) > 1.6 * Math.abs(dy)) go(dx > 0 ? "load" : "move")
      }}>
      <div className="flex items-center justify-between gap-2 px-4 pt-3">
        <div className="inline-flex rounded-full bg-white/[.06] p-0.5 text-[11px] font-bold" role="tablist">
          {(["move", "load"] as const).map((f) => (
            <button key={f} role="tab" aria-selected={face === f} onClick={() => go(f)}
              className={`rounded-full px-3 py-1 transition ${face === f ? (f === "move" ? "bg-info text-ink" : "bg-load text-ink") : "text-fg-2"}`}>
              {f === "move" ? "Mechanika" : "Zátěž"}
            </button>
          ))}
        </div>
        <span className="text-[10.5px] text-fg-3">{face === "move" ? "swipe doprava → zátěž" : "← swipe doleva pohyb"}</span>
      </div>
      <div key={anim} className={anim ? "animate-[runFlip_.35s_ease-out]" : ""} style={{ transformOrigin: "center", backfaceVisibility: "hidden" }}>
        {face === "move" ? move : load}
      </div>
    </div>
  )
}

// cached per runner for a minute, so flipping back and forth doesn't refetch
const _flipCache = new Map<string, { at: number; p: Promise<any> }>()
function cached(key: string, f: () => Promise<any>) {
  const hit = _flipCache.get(key)
  if (hit && Date.now() - hit.at < 60_000) return hit.p
  const p = f().catch(() => null)
  _flipCache.set(key, { at: Date.now(), p })
  return p
}

function MovementRunPanel({ rid, x, hasCtx, onExcluded }: { rid: string; x: any; hasCtx: boolean; onExcluded?: (ex: boolean, scope?: string | null) => void }) {
  const [d, setD] = useState<any | null | false>(null)
  useEffect(() => {
    let alive = true
    setD(null)
    api.runCompare(rid, x.id).then((r) => alive && setD(r || false)).catch(() => alive && setD(false))
    return () => { alive = false }
  }, [rid, x.id])
  return (
    <>
      {hasCtx && <RunContext x={x} />}
      {d && d.metrics ? (
        <MonthCompare data={d} />
      ) : d === false ? (
        <dl className="grid grid-cols-3 gap-2 border-t border-white/[.07] px-4 py-3 text-[11px] md:grid-cols-6">
          {[["Kadence", x.cadence_spm && `${x.cadence_spm} spm`], ["Kontakt", x.gct_ms && `${x.gct_ms} ms`], ["Krok", x.stride_len_m && `${cz(x.stride_len_m)} m`], ["Osc.", x.vert_osc_cm && `${cz(x.vert_osc_cm)} cm`], ["Balance", x.gct_balance_l ? `${x.gct_balance_l} %` : "—"], ["Klesání", x.descent_m != null && `${x.descent_m} m`]].map(([k, v]) => (
            <div key={k as string}><dt className="uppercase tracking-[.1em] text-fg-3">{k}</dt><dd className="mt-0.5 tabular-nums text-[11px] text-fg">{v || "—"}</dd></div>
          ))}
        </dl>
      ) : (
        <p className="border-t border-white/[.07] px-4 py-3 text-[12px] text-fg-3">Načítám srovnání s během před měsícem…</p>
      )}
      {/* feedback #178 — the segments under the comparison with a run a month back */}
      {!x.excluded && <SegmentTimeline rid={rid} aid={x.id} />}
      {x.auto_excluded === "treadmill" && x.excluded && (
        <p className="mx-4 mt-3 rounded-[12px] border border-watch/30 bg-watch/[.07] p-3 text-[12px] leading-5 text-fg-soft" data-testid="auto-excluded-note">
          {AUTO_TREADMILL_TEXT} Pokud je běh v pořádku, vraťte ho níže tlačítkem.
        </p>
      )}
      {hasCtx && onExcluded && <ExcludeRun rid={rid} x={x} onDone={onExcluded} />}
    </>
  )
}

// the movement face for a run opened from Zátěž → historie aktivit
function MovementRunPanelById({ rid, aid }: { rid: string; aid: any }) {
  const { boot } = useApp()
  const [rows, setRows] = useState<any[] | null | false>(null)
  useEffect(() => {
    let alive = true
    cached(`rh:${rid}`, () => api.runHistory(rid, 40)).then((d) => alive && setRows(Array.isArray(d) ? d : false))
    return () => { alive = false }
  }, [rid])
  if (rows === null) return <p className="px-4 py-3 text-[12px] text-fg-3">Načítám pohyb běhu…</p>
  const x = (rows || []).find((r: any) => r.id === aid) || (boot?.activities || []).find((r: any) => r.id === aid)
  if (!x) return <p className="px-4 py-3 text-[12px] text-fg-3">Pro tento běh nejsou data o pohybu.</p>
  return <MovementRunPanel rid={rid} x={x} hasCtx={!!rows && rows.some((r: any) => r.id === aid)} />
}

// the load face for a run opened from Pohyb → historie běhů
function LoadRunPanelById({ rid, aid }: { rid: string; aid: any }) {
  const [data, setData] = useState<any | null | false>(null)
  useEffect(() => {
    let alive = true
    cached(`lh:${rid}`, () => api.loadHistory(rid)).then((d) => alive && setData(d || false))
    return () => { alive = false }
  }, [rid])
  if (data === null) return <p className="px-4 py-3 text-[12px] text-fg-3">Počítám zátěž běhu…</p>
  const x = data && data.items ? data.items.find((i: any) => i.id === aid) : null
  if (!x) return <p className="px-4 py-3 text-[12px] text-fg-3">Zátěž je k dispozici pro aktivity posledních {data?.days || 28} dní v kapacitním modelu.</p>
  const scale: number | null = data.impactScale ?? null
  const imp = (pts: number) => (scale != null ? fmtImpact(toImpact(pts, scale)) : pts >= 0.5 ? `+${mfmt(1, pts)} b` : "0 b")
  return <LoadRunPanel x={x} imp={imp} todayIso={new Date().toLocaleDateString("sv-SE")} />
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
          ? <b className="text-alert-soft">{`${run.sigCount} ${run.sigCount === 1 ? "významná odchylka" : run.sigCount < 5 ? "významné odchylky" : "významných odchylek"} v ${sigSegs} ${sigSegs === 1 ? "úseku" : "úsecích"}`}</b>
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
              {i === 0 ? "0" : `${cz(Math.round((t / 60) * 10) / 10)} min`}
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

// The mechanics metric cards (Pohyb) — also summarised on Dnes (feedback #156).
export function buildMechMetrics(a: any, acts: any[]): Metric[] {
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
    const res = (a.mechRes || {})[({ vert_ratio_pct: "tavr", gct_ms: "gct", cadence_spm: "cad", vert_osc_cm: "vosc" } as Record<string, string>)[field]]
    return { ...eng(series, field, label, unit, dec, rec, base, z, pctStr(rec, base), Math.abs(z) >= 1, clamp(50 + z * 18, 8, 92), terrain), refSd: o.refSd ?? null, lowRes: !!res && res.wf < 1 }
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
  const devKey = (m: Metric) => (Number.isFinite(m.z) ? Math.abs(m.z) : 0) / (m.label === "Symetrie kontaktu" ? 0.8 : 1)
  metrics.sort((x, y) => devKey(y) - devKey(x))
  return metrics
}

// feedback #156 — the metrics behind the mechanics score, compact: each with its
// position against the runner's usual range
export function MechMini({ a, acts }: { a: any; acts: any[] }) {
  const ms = buildMechMetrics(a, (acts || []).filter((x: any) => !x.excluded || x.excluded_scope === "load"))
  const sigIds = new Set<string>(((a?.signals || []) as any[]).filter((s) => MECH_IDS.has(s.id) && (s.pts || 0) > 0).map((s) => s.id))
  if (!ms.length) return null
  return (
    <div className="mt-4 border-t border-white/10 pt-4" data-testid="mech-mini">
      <p className="t-label !text-fg-3">Metriky běhu · proti vaší normě</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {ms.map((m) => {
          const st = normStatus(m, sigIds)
          const col = st.tone === "alert" ? C.alert : st.tone === "watch" ? C.watch : C.ok
          const { lo, hi, isd } = usualRange(m)
          const dLo = Math.min(lo, m.value) - isd * 0.8, dHi = Math.max(hi, m.value) + isd * 0.8
          const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 4, 96)
          return (
            <div key={m.label}>
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="flex items-center gap-1.5 font-semibold text-fg-soft">{m.label}{m.label === "Kadence" && m.value < LOW_CADENCE && <LowCadenceAlert />}</span>
                <span className="tabular-nums text-fg-2"><b className="text-fg">{mfmt(m.dec, m.value)}</b> {m.unit} · <span style={{ color: col }}>{st.word}</span></span>
              </div>
              <div className="relative mt-1.5 h-1.5 rounded-full bg-white/[.06]">
                <i className="absolute top-0 h-full rounded-full" style={{ left: `${P(lo)}%`, width: `${P(hi) - P(lo)}%`, background: `${C.ok}52` }} />
                <i className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${P(m.value)}%`, background: col, boxShadow: `0 0 0 2px ${C.bg}` }} />
              </div>
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-[11px] text-fg-3">zelený pás = vaše obvyklé rozmezí, tečka = poslední běhy</p>
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
  const [openMetric, setOpenMetric] = useState("Vertikální oscilace")   // feedback #185 — oscillation opens first
  const [terr, setTerr] = useState(false)
  const mechHist = useQuadHistory(rid)   // prefetched by the store (history.ts)
  const stage = useDataStage()
  if (!a) return <LoadGate />
  // UX audit F01/F19 — before the first run: what this tab will show, in plain words
  if (stage === "none")
    return (
      <NoData kicker="Mechanika · technika běhu" title="Techniku uvidíte po prvních bězích">
        Hodinky při každém běhu měří kontakt se zemí, kadenci, odraz a vyváženost kroku. Došlap je porovnává s vašimi vlastními běhy ve stejném terénu a tempu a upozorní, když se technika začne měnit, často dřív, než únavu ucítíte.
      </NoData>
    )
  if ((a.confidence?.value ?? 0) < 0.6)
    return (
      <>
        <Head kicker="Mechanika · technika běhu" title="Techniku zatím poznáváme" />
        <AlertBanner tone="info" icon={Gauge} title={`Připraveno ${Math.round((a.confidence?.value ?? 0) * 100)} %`}>
          {a.confidence?.deviceChanged ? a.confidence.note : <>Techniku porovnáváme jen s vašimi vlastními běhy ve srovnatelném terénu a tempu. Zatím je jich {a.confidence?.sessions ?? 0} z posledních 4 týdnů a historie má {a.confidence?.days ?? 0} dní. Hodnotit začneme od 60 %, při pravidelném běhání obvykle po 6–8 týdnech.</>}
          <span className="relative mt-2.5 block h-2 rounded-full bg-white/[.08]" aria-hidden>
            <i className="absolute inset-y-0 left-0 rounded-full bg-info" style={{ width: `${clamp((a.confidence?.value ?? 0) * 100, 2, 100)}%` }} />
            <i className="absolute -inset-y-1 left-[60%] w-0.5 bg-fg" title="60 %" />
          </span>
        </AlertBanner>
        <Card className="mt-4"><Label>Co pomůže nejrychleji</Label><p className="mt-2 text-sm text-fg-2">Opakovat podobné běhy: stejný povrch, podobné tempo. Běhy srovnáváme po skupinách podle povrchu, sklonu a tempa.</p></Card>
      </>
    )

  const metrics = buildMechMetrics(a, acts)

  // State label follows the quadrant (post-hysteresis), so Pohyb matches the
  // kvadrant exactly — not a separate ≥25 / tavr-z cutoff that could disagree.
  const drift = a.quadrant === "silent" || a.quadrant === "critical"
  const headline = drift ? "Mechanika se mění" : a.mech >= 12 ? "Jemný drift proti normě" : "Mechanika drží na normě"
  const mechSig = ((a.signals || []) as any[]).filter((s) => MECH_IDS.has(s.id))
  const mechSigIds = new Set<string>(mechSig.filter((s) => (s.pts || 0) > 0).map((s) => s.id))

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
            <Label>Signál mechaniky</Label>
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
                    <FactorBar key={s.id} label={s.name} value={s.val} pts={s.pts} impact={s.impact} tone="info" pct={(s.pts / Math.max(1, ...mechSig.map((x) => x.pts || 0))) * 100} />
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="nest p-4 md:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Mechanická stabilita — trend</Label>
              <span className="text-[12px] text-fg-3">skóre mechaniky 0–100</span>
            </div>
            <div className="mt-2 flex items-end gap-2">
              <b className="t-num text-[40px] leading-none" style={{ color: drift ? C.alert : C.fg }}>{a.mech}</b>
              <small className="pb-1 text-[13px] text-fg-2">/ 100 · {drift ? "drift" : "stabilní"}</small>
            </div>
            {mechHist === null ? (
              <p className="mt-3 text-sm text-fg-3">Počítám trend v čase…</p>
            ) : mechHist.length > 1 ? (
              <AxisLineChart points={mechPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh" color={drift ? C.alert : C.ok} height={150} zone />
            ) : (
              <p className="mt-3 text-sm text-fg-3">Na trend v čase je zatím málo historie.</p>
            )}
            <p className="mt-1 text-[11px] text-fg-3">skóre mechaniky po dnech · nad prahem 25 = technika mimo vaši normu</p>
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
                <MechMetricCard m={m} open={isOpen} onSelect={() => setOpenMetric(isOpen ? "" : m.label)} sigIds={mechSigIds} />
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
// 7:28 load ratio bands: <0,8 nízká · 0,8–1,3 v normě · 1,3–1,5 zvýšená · >1,5 vysoká
// (railway#137: the ratio bar itself is gone, the load trend chart shows the same over time).
const ratioTone = (r: number): Tone => (r < 0.8 ? "muted" : r <= 1.3 ? "ok" : r <= 1.5 ? "watch" : "alert")
// Weekly bar colour: each week against the mean of the four weeks before it (same bands
// as the 7:28 ratio). Below ×0,8 is its own colour (railway#82), grey = too little history.
export function weekTones(w: number[]): Tone[] {
  return w.map((v, i) => {
    const prev = w.slice(Math.max(0, i - 4), i).filter((x) => x > 0)
    if (prev.length < 2) return "muted"
    const t = ratioTone(v / mean(prev))
    return t === "ok" ? "info" : t === "muted" ? "self" : t
  })
}
export function WeekToneLegend() {
  const items: [string, string][] = [[C.self, "pod obvyklým (< ×0,8)"], [C.info, "v normě"], [C.watch, "mírně nad (> ×1,3)"], [C.alert, "výrazně nad (> ×1,5)"]]
  return (
    <div className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 text-[11px] text-fg-3">
      {items.map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><i className="size-2 rounded-sm" style={{ background: c }} />{l}</span>)}
      <span className="w-full">týden proti průměru 4 předchozích</span>
    </div>
  )
}
// OPT-7 · the 13 descent bins (2,5 % steps) grouped into 4 slope bands; ≥ 10 % matches the "steep" total.
const SLOPE_BANDS: [string, number, number, Tone][] = [["0–5 %", 0, 2, "muted"], ["5–10 %", 2, 4, "info"], ["10–20 %", 4, 8, "watch"], ["20 % +", 8, 13, "alert"]]
function DescentBySlope({ g, up = false }: { g: any; up?: boolean }) {
  const [detail, setDetail] = useState(false)
  const b: number[] = g.buckets || []
  const bands = SLOPE_BANDS.map(([l, a, z, t]) => ({ l, t, v: b.slice(a, z).reduce((s: number, x: number) => s + (x || 0), 0) }))
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>{up ? "Stoupání za 7 dní podle sklonu" : "Klesání za 7 dní podle sklonu"}</Label>
        <Segmented size="sm" ariaLabel="Rozlišení sklonu" options={[["bands", "4 pásma"], ["bins", "po 2,5 %"]] as const} value={detail ? "bins" : "bands"} onChange={(k) => setDetail(k === "bins")} />
      </div>
      {detail
        ? <Bars vals={b} unit="m" labels={g.labels} axisLabels={(g.labels || []).map((l: string) => (l.includes("–") ? l.split("–")[0] : l))}
            tones={b.map((_, i) => SLOPE_BANDS.find(([, a, z]) => i >= a && i < z)?.[3] || "muted")} />
        : <Bars vals={bands.map((x) => x.v)} unit="m" labels={bands.map((x) => x.l)} tones={bands.map((x) => x.t)} />}
      <p className="mt-2 text-[12px] text-fg-3">{(g.total7 || 0) > 0 ? `${cz(g.total7)} m celkem · ${cz(g.steep7)} m na sklonu ≥10 %.` : `Za posledních 7 dní žádné ${up ? "stoupání" : "klesání"} z běhů s výškovým profilem. Rozdělení se doplní po běhu do kopce.`}</p>
    </div>
  )
}

export function Load() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const a = boot?.assessment
  const L = a?.loadDetail
  const rcv = a?.rcv
  const hist = useQuadHistory(rid)   // prefetched by the store (history.ts)
  const stage = useDataStage()
  // UX audit F01 — before the first run "Zátěž drží v normě" was a verdict without data
  if (stage === "none")
    return (
      <NoData kicker="Zátěž" title="Zátěž uvidíte po prvních bězích">
        Po prvních bězích tu uvidíte, kolik jste naběhali a kolik toho tělo ještě unese: kilometry, intenzitu, stoupání a klesání proti tomu, co jste v posledních týdnech zvládli. Prudký nárůst, který tělo nestihne vstřebat, tu poznáte hned.
      </NoData>
    )
  if (!L) return <LoadGate />

  // State follows the quadrant (post-hysteresis) so Zátěž matches it exactly.
  const loadHot = a.quadrant === "overreaching" || a.quadrant === "critical"
  // UX audit F09 — the headline follows the strongest thing on the page: a channel at its weekly
  // ceiling is said here too (it read "v normě" above a red "strop vyčerpán")
  const CH_WORD: Record<string, string> = { volume: "objem", intensity: "intenzita", descent: "klesání", ascent: "stoupání", systemic: "celková zátěž", speed: "rychlost" }
  const full = Object.entries((a.capacity?.channels || {}) as Record<string, any>)
    .filter(([k, c]) => CH_WORD[k] && c?.known && c.week && (c.week.absorbedMax != null ? (c.week.absorbedLeft ?? 0) : (c.week.left ?? 0)) <= 0.005)
    .map(([k]) => CH_WORD[k])
  const atCeiling = !loadHot && (a.load ?? 0) < 12 && full.length > 0
  const rising = !loadHot && (a.load ?? 0) >= 12
  const loadHeadline = loadHot ? "Zátěž je zvýšená" : (a.load ?? 0) >= 12 ? "Zátěž roste" : atCeiling ? "Týden je naplněný" : "Zátěž drží v normě"
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
          <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] font-bold ${loadHot ? "bg-alert/12 text-alert-soft" : atCeiling || rising ? "bg-watch/12 text-watch" : "bg-ok/12 text-ok"}`}>
            <i className={`size-2 rounded-full ${loadHot ? "bg-alert" : atCeiling || rising ? "bg-watch" : "bg-ok"}`} />
            {loadHot ? "nad obvyklou úrovní" : atCeiling ? "na týdenním stropu" : rising ? "mírně nad obvyklou úrovní" : "v obvyklém rozsahu"}
          </div>
        </div>
        {atCeiling && (
          <p className="mt-2 max-w-xl text-[13px] leading-5 text-fg-2" data-testid="load-full">
            Zátěž je pro vás obvyklá, ale {full.join(", ")} {full.length > 1 ? "jsou" : "je"} na týdenním stropu. Do dalšího náročného tréninku nechte pár dní lehčích, ať tělo zátěž vstřebá.
          </p>
        )}
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
          <p className="mt-1 text-[11px] text-fg-3">skóre zátěže po dnech · po běhu se vstřebává noc po noci · nad prahem 25 = zvýšená</p>
        </div>
        <div className="mt-5">
          <div>
            <p className="t-label !text-fg-3">Co tvoří skóre zátěže</p>
            {loadSig.length > 0 ? (
              <div className="mt-3 space-y-3">
                {loadSig.map((s) => (
                  <FactorBar key={s.id} label={s.name} value={s.val} pts={s.pts} impact={s.impact} tone="load" pct={(s.pts / Math.max(1, ...loadSig.map((x) => x.pts || 0))) * 100} />
                ))}
              </div>
            ) : <p className="mt-2 text-[13px] text-fg-2">Nic nad vaší obvyklou úrovní — skóre je 0.</p>}
          </div>
        </div>
      </section>

      {a.capacity && (
        <CapacityPanel cap={a.capacity} scale={a.impactScale?.load} extra={{
          // railway#58/#59 — weekly and daily run volume feed the Objem channel
          volume: (
            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <Label>Týdenní objem běhu (Po–Ne), 12 týdnů</Label>
                <Bars vals={L.weekly || []} tones={weekTones(L.weekly || [])} />
                <p className="mt-2 text-[12px] text-fg-3">Tento týden (Po–Ne) <b className="text-fg">{cz(L.weekKm)} km</b> · posledních 7 dní <b className="text-fg">{cz(L.runKm7)} km</b></p>
                <WeekToneLegend />
              </div>
              <div>
                <Label>Denní objem běhu, 28 dní</Label>
                <Bars vals={L.daily || []} tones={(L.daily || []).map((_: number, i: number, arr: number[]) => (i >= arr.length - 7 ? (L.valid && L.ratio != null ? (ratioTone(L.ratio) === "ok" ? "info" : ratioTone(L.ratio)) : "info") : "muted"))} />
                <p className="mt-2 text-[11px] text-fg-3">barevně posledních 7 dní podle poměru 7 : 28</p>
              </div>
            </div>
          ),
          // railway#61 — descent by slope belongs to the Klesání channel
          ...(a?.gradientDescent?.buckets?.some((v: number) => v > 0) ? { descent: <DescentBySlope g={a.gradientDescent} /> } : {}),
          // feedback #160 — the same view for ascent
          // feedback #180 — always shown for ascent; without hilly runs it says why it's empty
          ascent: <DescentBySlope g={a?.gradientAscent || { buckets: [], labels: [], total7: 0, steep7: 0 }} up />,
        }} />
      )}
      {a.capacity && <LoadHistory rid={rid} />}
    </>
  )
}

const readinessWord = (p: number) => (p >= 70 ? "dobrá" : p >= 40 ? "snížená" : "nízká")
// railway#137/#138 — readiness over time; HRV, resting HR and sleep open under it.
// railway#142 — lives on Trénink, above today's capacity.
export function ReadinessTrend({ a, hist, below }: { a: any; hist: any[] | null; below?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const r = a?.readiness ?? a?.capacity?.readiness
  const rcv = a?.rcv
  // railway#194 — the morning's readiness (after the night, before today's training and the
  // day outside it lowered it), day by day; how the day lowers it is in Dnešní den below
  // UX audit F02 — no night from the watch this morning → no number (it used to read 100 %)
  const pct = r && r.known !== false ? (r.morningScore ?? readinessPct(r)) : null
  const col = pct != null ? readinessCol(pct) : C.fg3
  const asOf = (a?.computed_at || "").slice(0, 10)
  // feedback #157: the last two months only
  const since = new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10)
  // days without a night stay empty (a gap in the line); the line starts at the first known night
  const mornings = (hist || []).map((h) => ({ t: h.date as string, v: (h.readinessMorning ?? h.readiness ?? null) as number | null })).filter((h) => h.t >= since)
  const first = mornings.findIndex((h) => h.v != null)
  const pts = first < 0 ? [] : mornings.slice(first)
  if (pts.length) pts[pts.length - 1] = { t: asOf || pts[pts.length - 1].t, v: pct }
  if (pct == null && !rcv) return <p className="nest px-3.5 py-3 text-[12px] text-fg-3">Chybí souvislá data z hodinek za posledních 35 dní (HRV, klidový tep, spánek).</p>
  return (
    <div className="nest p-3.5" data-testid="readiness-trend">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><span className="t-label !text-fg-3">Ranní připravenost — trend</span><InfoDot text={MI.readiness} label="Připravenost" /></span>
        <span className="text-[11px] text-fg-3">60 dní · 0–100 %</span>
      </div>
      {pct != null && (
        <div className="mt-1.5 flex items-end gap-2">
          <b className="t-num text-[30px] leading-none" style={{ color: col }}>{pct}<small className="text-[14px] font-semibold"> %</small></b>
          <small className="pb-0.5 text-[12px] text-fg-2">dnes ráno · {readinessWord(pct)}</small>
        </div>
      )}
      {hist === null ? <p className="mt-2 text-[12px] text-fg-3">Počítám trend v čase…</p>
        : pts.filter((p) => p.v != null).length > 1 ? <AxisLineChart points={pts} yMin={0} yMax={100} unit=" %" color={col === C.fg3 ? C.info : col} height={96} />
        : <p className="mt-2 text-[12px] text-fg-3">Na trend připravenosti je zatím málo historie.</p>}
      {/* feedback #208 — today's readiness through the day, under the chart and outside its detail */}
      {below}
      {rcv && (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="readiness-detail-toggle"
          className="mt-2 flex w-full items-center justify-between gap-2 border-t border-white/[.07] pt-2.5 text-left text-[12px] font-semibold text-fg-2 transition hover:text-fg">
          <span>Z čeho vychází: HRV, klidový tep, spánek</span>
          <ChevronDown className={`size-4 shrink-0 transition ${open ? "rotate-180 text-accent" : "text-fg-3"}`} aria-hidden />
        </button>
      )}
      {rcv && open && <div className="mt-3 origin-top animate-[careReveal_.28s_ease-out]" data-testid="readiness-detail"><RecoveryDetail rcv={rcv} sleepEff={a.sleepEff} /></div>}
    </div>
  )
}

// railway#138 — the nights behind readiness, each over the last two months against the
// runner's usual range (28-day baseline ± 1 SD); sleep quality opens under the sleep chart.
function RecoveryDetail({ rcv, sleepEff }: { rcv: any; sleepEff: any }) {
  const [sleepOpen, setSleepOpen] = useState(false)
  const hist = (rcv.history || []) as any[]
  const rows: { k: "hrv" | "rhr" | "sleep"; label: string; info: string; unit: string; dec: number; bad: boolean; col: string }[] = [
    { k: "hrv", label: "HRV", info: MI.hrv, unit: "ms", dec: 0, bad: rcv.hrv.z <= -1, col: C.info },
    { k: "rhr", label: "Klidový tep", info: MI.rhr, unit: "tepů/min", dec: 0, bad: rcv.rhr.z >= 1.2, col: C.info },
    { k: "sleep", label: "Spánek", info: MI.sleep, unit: "h", dec: 1, bad: rcv.sleep.debt >= 4, col: C.info },
  ]
  return (
    <div className="grid gap-4">
      {rows.map((m) => {
        const c = rcv[m.k] || {}
        const pts = hist.filter((h) => h[m.k] != null).map((h) => ({ t: h.d as string, v: h[m.k] as number }))
        const band = c.base != null && c.sd ? { lo: c.base - c.sd, hi: c.base + c.sd, mid: c.base, label: "vaše obvyklé rozmezí" } : undefined
        return (
          <div key={m.k} data-testid="recovery-metric">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <span className="flex items-center gap-1"><span className="t-label !text-fg-3">{m.label}</span><InfoDot text={m.info} label={m.label} /></span>
              <span className="tabular-nums text-[12px] text-fg-3">
                <b className="text-[14px]" style={{ color: m.bad ? C.alert : C.fg }}>{cz(c.now)} {m.unit}</b> 7 nocí · obvykle {cz(c.base)}
                {m.k === "sleep" ? (c.debt > 0 ? ` · dluh ${cz(c.debt)} h/týd` : "") : ` · ${pctStr(c.now, c.base)}`}
              </span>
            </div>
            {pts.length > 1
              ? <AxisLineChart points={pts} dec={m.dec} unit={` ${m.unit}`} color={m.bad ? C.alert : m.col} height={96} band={band} />
              : <div className="mt-2"><Sparkline vals={c.series || []} color={m.bad ? C.alert : C.ok} /></div>}
            {m.k === "sleep" && sleepEff && (
              <>
                <button type="button" onClick={() => setSleepOpen((v) => !v)} aria-expanded={sleepOpen}
                  className="mt-1 flex w-full items-center justify-between gap-1 text-left text-[12px] font-semibold text-fg-2 transition hover:text-fg">
                  <span>Kvalita spánku</span>
                  <ChevronDown className={`size-3.5 transition ${sleepOpen ? "rotate-180 text-accent" : "text-fg-3"}`} aria-hidden />
                </button>
                {sleepOpen && <div className="nest mt-2 origin-top animate-[careReveal_.28s_ease-out] p-3.5"><SleepQuality s={sleepEff} /></div>}
              </>
            )}
          </div>
        )
      })}
      <p className="text-[11px] leading-4 text-fg-3">Po nocích za 2 měsíce, pás je vaše obvyklé rozmezí za 4 týdny. Připravenost z nich skládá hodnotu dne spolu s check-inem a dnešním tréninkem.</p>
    </div>
  )
}

// Feedback railway#33 — sleep quality, not only length: efficiency (asleep / in bed)
// and the deep + REM share of the staged night against the runner's 8-week normal.
// v0.11.0: only the efficiency (3 nights) feeds readiness; the stages are shown.
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
          <p className="t-num text-[30px]" style={{ color: restLow ? C.watch : undefined }}>{pct(s.restNow)}</p>
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
        {effLow ? "Víc bdění než obvykle — připravenost to sníží mírně, víc jen když to potvrdí HRV nebo klidový tep. " : ""}
        Fáze spánku jsou jen pro informaci, do připravenosti se nepočítají.
      </p>
      {(s.history || []).length >= 7 && <SleepHistory h={s.history} />}
    </div>
  )
}

// railway#114 — two months of nights: total sleep in hours, deep and REM sleep in minutes
// (two panels, never two y-scales on one). Thin lines are single nights, the solid ones
// their 7-night mean; hover or touch shows the night.
const roll7 = (vals: (number | null)[]) => vals.map((_, i) => {
  const w = vals.slice(Math.max(0, i - 6), i + 1).filter((v) => v != null) as number[]
  return w.length >= 3 ? w.reduce((a, b) => a + b, 0) / w.length : null
})
function SleepHistory({ h }: { h: any[] }) {
  const [act, setAct] = useState<number | null>(null)
  const n = h.length
  const W = 320, L = 26, R = 40, PH = 58, GAP = 22, T = 6
  const X = (i: number) => L + (i / Math.max(1, n - 1)) * (W - L - R)
  const total = h.map((x) => x.sleep ?? null) as (number | null)[]
  const deep = h.map((x) => x.deep ?? null) as (number | null)[]
  const rem = h.map((x) => x.rem ?? null) as (number | null)[]
  const tR = roll7(total), dR = roll7(deep), rR = roll7(rem)
  const hasStages = deep.some((v) => v != null) || rem.some((v) => v != null)
  const rng = (arrs: (number | null)[][], pad: number) => {
    const v = arrs.flat().filter((x) => x != null) as number[]
    const lo = Math.max(0, Math.floor(Math.min(...v) - pad)), hi = Math.ceil(Math.max(...v) + pad)
    return [lo, hi === lo ? lo + 1 : hi] as const
  }
  const [t0, t1] = rng([total], 0.5)
  const [s0, s1] = hasStages ? rng([deep, rem], 10) : [0, 1]
  const y1 = (v: number) => T + PH - ((v - t0) / (t1 - t0)) * PH
  const y2 = (v: number) => T + PH + GAP + PH - ((v - s0) / (s1 - s0)) * PH
  const path = (vals: (number | null)[], y: (v: number) => number) => {
    let d = "", pen = false
    vals.forEach((v, i) => { if (v == null) { pen = false; return } d += `${pen ? "L" : "M"}${X(i).toFixed(1)} ${y(v).toFixed(1)}`; pen = true })
    return d
  }
  const last = (vals: (number | null)[]) => { for (let i = vals.length - 1; i >= 0; i--) if (vals[i] != null) return [i, vals[i] as number] as const; return null }
  const Hh = T + PH * 2 + GAP + 16
  const fmtDay = (d: string) => { const [, m, dd] = d.split("-"); return `${+dd}. ${+m}.` }
  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * (W - L - R)
    setAct(Math.max(0, Math.min(n - 1, Math.round((px / (W - L - R)) * (n - 1)))))
  }
  const endLabel = (vals: (number | null)[], y: (v: number) => number, txt: (v: number) => string, dy = 0) => {
    const l = last(vals)
    return l && <text x={W - R + 4} y={y(l[1]) + 3 + dy} fontSize="8.5" fill={C.fg2} className="tabular-nums">{txt(l[1])}</text>
  }
  const a = act != null ? h[act] : null
  return (
    <div className="mt-4 border-t border-white/[.07] pt-3" data-testid="sleep-history">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label !text-fg-3">Spánek za 2 měsíce</p>
        <span className="flex items-center gap-3 text-[11px] text-fg-2">
          <span className="flex items-center gap-1"><i className="h-0.5 w-3 rounded-full" style={{ background: C.self }} />celkem</span>
          {hasStages && <span className="flex items-center gap-1"><i className="h-0.5 w-3 rounded-full" style={{ background: C.info }} />hluboký</span>}
          {hasStages && <span className="flex items-center gap-1"><i className="h-0.5 w-3 rounded-full" style={{ background: C.accent }} />REM</span>}
        </span>
      </div>
      <div className="relative mt-1.5">
        <svg viewBox={`0 0 ${W} ${Hh}`} className="block w-full" role="img" aria-label="Vývoj celkového, hlubokého a REM spánku za posledních 60 dní">
          {/* panel 1 · total sleep (h) */}
          <text x={2} y={T + 7} fontSize="8" fill={C.fg3}>{t1} h</text>
          <text x={2} y={T + PH} fontSize="8" fill={C.fg3}>{t0} h</text>
          <line x1={L} x2={W - R} y1={T + PH} y2={T + PH} stroke="rgb(255 255 255 / .08)" />
          <path d={path(total, y1)} fill="none" stroke={C.self} strokeOpacity=".35" strokeWidth="1" />
          <path d={path(tR, y1)} fill="none" stroke={C.self} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {endLabel(tR, y1, (v) => `${cz(Math.round(v * 10) / 10)} h`)}
          {hasStages && (
            <>
              {/* panel 2 · deep and REM (min) */}
              <text x={2} y={T + PH + GAP + 7} fontSize="8" fill={C.fg3}>{s1}</text>
              <text x={2} y={T + PH * 2 + GAP} fontSize="8" fill={C.fg3}>{s0} min</text>
              <line x1={L} x2={W - R} y1={T + PH * 2 + GAP} y2={T + PH * 2 + GAP} stroke="rgb(255 255 255 / .08)" />
              <path d={path(deep, y2)} fill="none" stroke={C.info} strokeOpacity=".3" strokeWidth="1" />
              <path d={path(rem, y2)} fill="none" stroke={C.accent} strokeOpacity=".3" strokeWidth="1" />
              <path d={path(dR, y2)} fill="none" stroke={C.info} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              <path d={path(rR, y2)} fill="none" stroke={C.accent} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {(() => {
                const ld = last(dR), lr = last(rR)
                const clash = ld && lr && Math.abs(y2(ld[1]) - y2(lr[1])) < 9
                const up = ld && lr && ld[1] > lr[1]
                return <>
                  {endLabel(dR, y2, (v) => `hl. ${Math.round(v)}`, clash ? (up ? -4 : 4) : 0)}
                  {endLabel(rR, y2, (v) => `REM ${Math.round(v)}`, clash ? (up ? 4 : -4) : 0)}
                </>
              })()}
            </>
          )}
          {/* x axis */}
          {[0, Math.floor((n - 1) / 2), n - 1].map((i, k) => (
            <text key={k} x={X(i)} y={Hh - 3} fontSize="8" fill={C.fg3} textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"}>{fmtDay(h[i].d)}</text>
          ))}
          {act != null && <line x1={X(act)} x2={X(act)} y1={T} y2={T + PH * 2 + GAP} stroke={C.fg} strokeOpacity=".35" />}
          <rect x={L} y={0} width={W - L - R} height={Hh - 12} fill="transparent" style={{ touchAction: "pan-y" }}
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setAct(null)} />
        </svg>
        {a && (
          <div className="pointer-events-none absolute top-0 -translate-x-1/2 whitespace-nowrap rounded-[10px] border border-white/14 bg-raised px-2 py-1 text-[11px] font-semibold tabular-nums text-fg shadow-lg"
            style={{ left: `${(X(act!) / W) * 100}%` }}>
            {fmtDay(a.d)} · {a.sleep != null ? `${cz(a.sleep)} h` : "—"}{a.deep != null ? ` · hluboký ${a.deep} min` : ""}{a.rem != null ? ` · REM ${a.rem} min` : ""}
          </div>
        )}
      </div>
      <p className="mt-1 text-[11px] text-fg-3">tenká čára jednotlivé noci · plná průměr 7 nocí</p>
    </div>
  )
}

const SPORT_ICON: Record<string, LucideIcon> = { cycling: Bike, swimming: Waves, strength: Dumbbell, rowing: Ship, elliptical: Orbit, hiking: Mountain, walking: Footprints, other: ActivityIcon }


// railway#55 — share of run vs other sport as a pie
// Zátěž → Historie aktivit: each run or other sport of the last 28 days against the
// capacity of its day, only in the channels it actually loads (a run: objem,
// intenzita, klesání, stoupání, celková zátěž; another sport: celková zátěž; strength
// also silová zátěž). railway#110 — drawn rather than written: the activity against
// the per-run ceiling (overflow in red), the 7-day window against the weekly ceiling,
// readiness around it and the room left at the same pace. railway#111 — its effect as
// percentage points of the overall Skóre.
const BAND_TONE: Record<string, Tone> = { "v kapacitě": "ok", "mírně nad": "watch", nad: "alert", "výrazně nad": "alert" }
const dur = (m?: number | null) => (m == null ? null : m >= 60 ? `${Math.floor(m / 60)} h ${String(Math.round(m % 60)).padStart(2, "0")} min` : `${Math.round(m)} min`)
const nfmt = (v: number | null | undefined) => (v == null ? "—" : (Math.round(v * 10) / 10).toLocaleString("cs-CZ"))
const unitShort = (u: string) => (u === "min v Z4+" ? "min" : u)

// one activity against the per-run ceiling: fill to the ceiling, the overflow in red past it
function OverBar({ value, ceiling, tone }: { value: number; ceiling: number | null; tone: Tone }) {
  if (ceiling == null || ceiling <= 0) return <div className="h-2 rounded-full bg-white/[.08]" />
  const scale = Math.max(value, ceiling) * 1.06
  const inside = Math.min(value, ceiling)
  return (
    <div className="relative h-2 rounded-full bg-white/[.08]">
      <i className="absolute inset-y-0 left-0 rounded-l-full" style={{ width: `${(inside / scale) * 100}%`, background: value > ceiling ? C.fg3 : toneCol(tone), borderRadius: value > ceiling ? undefined : 9999 }} />
      {value > ceiling && <i className="absolute inset-y-0 rounded-r-full" style={{ left: `${(ceiling / scale) * 100}%`, width: `${((value - ceiling) / scale) * 100}%`, background: `repeating-linear-gradient(135deg, ${C.alert}, ${C.alert} 3px, ${C.alert}bb 3px, ${C.alert}bb 6px)` }} />}
      <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${(ceiling / scale) * 100}% - 1px)` }} />
    </div>
  )
}
// the 7-day window ending that day: the other sessions (grey) + this one, against the weekly ceiling
function WeekBar({ before, value, ceiling, tone }: { before: number; value: number; ceiling: number | null; tone: Tone }) {
  const tot = before + value
  if (ceiling == null || ceiling <= 0) return <div className="h-1.5 rounded-full bg-white/[.08]" />
  const scale = Math.max(tot, ceiling) * 1.06
  return (
    <div className="relative h-1.5 rounded-full bg-white/[.08]">
      <i className="absolute inset-y-0 left-0 rounded-l-full bg-white/25" style={{ width: `${(before / scale) * 100}%` }} />
      <i className="absolute inset-y-0" style={{ left: `${(before / scale) * 100}%`, width: `${(value / scale) * 100}%`, background: tot > ceiling ? C.alert : toneCol(tone) }} />
      <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${(ceiling / scale) * 100}% - 1px)` }} />
    </div>
  )
}

function ReadinessStrip({ r, today }: { r: any; today: boolean }) {
  const pill = (label: string, v: number | null | undefined, sub?: string) => (
    <span className="min-w-0 flex-1 rounded-[10px] bg-white/[.05] px-2 py-1.5 text-center">
      <span className="block text-[10px] font-bold uppercase tracking-[.08em] text-fg-3">{label}</span>
      <b className="t-num block text-[16px] leading-tight" style={{ color: v == null ? C.fg3 : goodCol(v) }}>{v == null ? "—" : `${v} %`}</b>
      {sub && <span className="block text-[10px] leading-3 text-fg-3">{sub}</span>}
    </span>
  )
  return (
    <div>
      <p className="t-label !text-fg-3">Připravenost{r.band ? <span className="ml-1.5 normal-case tracking-normal text-fg-2">· trénink {r.band}</span> : null}</p>
      <div className="mt-1.5 flex items-center gap-1.5">
        {pill("ráno", r.before)}
        <ChevronRight className="size-3.5 shrink-0 text-fg-4" aria-hidden />
        {pill("po tréninku", r.after, "odhad")}
        <ChevronRight className="size-3.5 shrink-0 text-fg-4" aria-hidden />
        {pill("další ráno", r.next, r.next == null ? (today ? "doplní hodinky" : "bez dat") : "naměřeno")}
      </div>
    </div>
  )
}

function LoadHistory({ rid }: { rid: string }) {
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState<number | null>(null)
  const [more, setMore] = useState(false)
  const [data, setData] = useState<any | null | false>(null) // null = not loaded, false = failed
  useEffect(() => {
    if (!open || data !== null) return
    let alive = true
    api.loadHistory(rid).then((d) => alive && setData(d || false)).catch(() => alive && setData(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rid])
  const items: any[] = data && data.items ? data.items : []
  const shown = more ? items : items.slice(0, 12)
  const scale: number | null = data ? data.impactScale ?? null : null
  const imp = (pts: number) => (scale != null ? fmtImpact(toImpact(pts, scale)) : pts >= 0.5 ? `+${mfmt(1, pts)} b` : "0 b")
  const todayIso = new Date().toLocaleDateString("sv-SE")
  return (
    <section className="mt-4" data-testid="load-history">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="card flex w-full items-center gap-4 px-4 py-4 text-left text-fg transition hover:border-load/45 md:px-5">
        <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-load/15 text-load"><History className="size-4" aria-hidden /></span>
        <span className="min-w-0 flex-1"><span className="t-label">Historie běhů a jiných aktivit</span><span className="mt-1 block font-serif text-[19px] leading-snug">Vliv každé aktivity na složky kapacity · rozklikni detail</span></span>
        <ChevronDown className={`size-5 shrink-0 text-load transition ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {data === null && <p className="px-1 text-[12px] text-fg-3">Počítám zátěž jednotlivých aktivit…</p>}
          {data === false && <p className="px-1 text-[12px] text-fg-3">Historii zátěže se nepodařilo načíst. Zkuste to prosím později.</p>}
          {data && !data.available && <p className="px-1 text-[12px] text-fg-3">Rozpad zátěže podle kapacity je k dispozici v kapacitním modelu hodnocení.</p>}
          {data && data.available && !items.length && <p className="px-1 text-[12px] text-fg-3">Za posledních {data.days} dní tu zatím není žádná aktivita.</p>}
          {shown.map((x) => {
            const isOpen = sel === x.id
            const Icon = x.run ? Footprints : SPORT_ICON[x.sport] || ActivityIcon
            const pk = x.peak
            const over = (x.over || []) as any[]
            const pkTone: Tone = over.length ? "alert" : (x.weekOver || []).length ? "watch" : pk ? BAND_TONE[pk.band] || "muted" : "muted"
            const meta = [fmtD(x.date), x.sportLabel, x.km ? `${mfmt(1, x.km)} km` : null, dur(x.durationMin), x.avgHr ? `⌀ ${x.avgHr} tep` : null].filter(Boolean).join(" · ")
            return (
              <div key={x.id} className={`overflow-hidden rounded-[18px] border transition ${isOpen ? "border-load/40 bg-panel-2" : "border-white/[.08] bg-white/[.03] hover:border-white/15"}`}>
                <button onClick={() => setSel(isOpen ? null : x.id)} aria-expanded={isOpen} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left">
                  <span className={`grid size-[34px] place-items-center rounded-[10px] ${x.run ? "bg-load/15 text-load" : "bg-info/15 text-info"}`}><Icon className="size-4" aria-hidden /></span>
                  <span className="min-w-0">
                    <b className="text-sm font-bold">{x.title || x.sportLabel}</b>
                    <span className="block text-[12px] text-fg-3">{meta}</span>
                    {pk && (
                      <span className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: `${toneCol(pkTone)}1f`, color: toneCol(pkTone) }}>
                        {over.length ? `nad stropem: ${over.map((o) => o.label.toLowerCase()).join(", ")}`
                          : (x.weekOver || []).length ? `týden nad stropem: ${x.weekOver.map((o: any) => o.label.toLowerCase()).join(", ")}`
                          : `nejvíc ${pk.label.toLowerCase()} ×${mfmt(2, pk.ratio)} · ${pk.band}`}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-2 whitespace-nowrap text-right tabular-nums text-[12px]">
                    <span>
                      <b className="block text-sm" style={{ color: x.scorePts > 0 ? C.watch : C.fg3 }}>{imp(x.scorePts)}</b>
                      <span className="block text-[11px] text-fg-3">Skóre dnes</span>
                    </span>
                    <ChevronDown className={`size-4 text-fg-3 transition ${isOpen ? "rotate-180 text-load" : ""}`} aria-hidden />
                  </span>
                </button>
                {isOpen && (x.run
                  ? <RunFlip initial="load" load={<LoadRunPanel x={x} imp={imp} todayIso={todayIso} />} move={<MovementRunPanelById rid={rid} aid={x.id} />} />
                  : <div className="border-t border-white/[.07]"><LoadRunPanel x={x} imp={imp} todayIso={todayIso} /></div>)}
              </div>
            )
          })}
          {items.length > 12 && (
            <button type="button" onClick={() => setMore((v) => !v)} className="w-full rounded-[14px] border border-white/[.08] px-4 py-2.5 text-[12px] font-semibold text-fg-2 transition hover:border-white/20 hover:text-fg">
              {more ? "Zobrazit méně" : `Zobrazit dalších ${items.length - 12}`}
            </button>
          )}
        </div>
      )}
    </section>
  )
}

function LoadRunPanel({ x, imp, todayIso }: { x: any; imp: (pts: number) => string; todayIso: string }) {
  const over = (x.over || []) as any[]
  return (
    <div className="space-y-4 px-4 py-3.5" data-testid="load-history-detail">
    {x.readiness && <ReadinessStrip r={x.readiness} today={x.date === todayIso} />}
    {over.length > 0 ? (
      <p className="rounded-[12px] bg-alert/10 px-3 py-2 text-[13px] font-semibold text-alert-soft" data-testid="lh-over">
        Strop jedné aktivity překročen: {over.map((o) => `${o.label.toLowerCase()} o ${nfmt(o.over)} ${unitShort(o.unit)}`).join(", ")}
      </p>
    ) : (x.weekOver || []).length > 0 ? (
      <p className="rounded-[12px] bg-watch/10 px-3 py-2 text-[13px] font-semibold text-watch" data-testid="lh-week-over">
        S touto aktivitou 7 dní nad týdenním stropem: {x.weekOver.map((o: any) => `${o.label.toLowerCase()} o ${nfmt(o.over)} ${unitShort(o.unit)}`).join(", ")}
      </p>
    ) : x.extra ? (
      <p className="rounded-[12px] bg-ok/10 px-3 py-2 text-[13px] font-semibold text-ok" data-testid="lh-extra">
        {x.extra.min > 0
          ? `Ve stejném tempu ještě ~${dur(x.extra.min)}${x.extra.km ? ` (≈ ${mfmt(1, x.extra.km)} km)` : ""}, než narazíte na ${x.extra.by === "week" ? "týdenní strop" : "strop"}: ${x.extra.label.toLowerCase()}`
          : `Hraniční: ${x.extra.label.toLowerCase()} už je na ${x.extra.by === "week" ? "týdenním stropu" : "stropu jedné aktivity"}`}
      </p>
    ) : null}
    {x.channels.map((c: any) => {
      const tone: Tone = c.band ? BAND_TONE[c.band] || "muted" : "muted"
      const u = unitShort(c.unit)
      const room = c.ceiling != null ? c.ceiling - c.value : null
      return (
        <div key={c.ch}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <b className="text-[13px] font-bold text-fg">{c.label}</b>
              <b className="tabular-nums text-[13px] text-fg-2">{nfmt(c.value)} {u}</b>
            </span>
            <span className="flex shrink-0 items-center gap-1.5 tabular-nums text-[12px]">
              {c.ratio != null && <span className="rounded-full px-1.5 py-px font-bold" style={{ background: `${toneCol(tone)}1f`, color: toneCol(tone) }}>×{mfmt(2, c.ratio)}</span>}
              {c.scorePts > 0 && <b style={{ color: C.watch }} title={c.driver === "week" ? `${Math.round(c.share * 100)} % nevstřebané zátěže za 7 dní` : c.driver === "latent" ? "doznívající skok" : "určuje dnešní skóre kanálu"}>{imp(c.scorePts)}</b>}
            </span>
          </div>
          {c.cap != null ? (
            <>
              <div className="mt-1.5"><OverBar value={c.value} ceiling={c.ceiling} tone={tone} /></div>
              <div className="mt-1 flex justify-between gap-2 text-[11px] tabular-nums text-fg-3">
                <span>strop {nfmt(c.ceiling)} {u}{c.readinessScore < 97 ? ` (připravenost ${c.readinessScore} %)` : ""}</span>
                {room != null && (room < 0
                  ? <b style={{ color: C.alert }}>+{nfmt(-room)} {u} nad</b>
                  : <span>rezerva {nfmt(room)} {u}</span>)}
              </div>
            </>
          ) : <p className="mt-1 text-[11px] text-fg-3">kapacita ten den ještě neznámá (potřebuje 3 aktivity za 30 dní)</p>}
          {c.weekCeiling != null && (
            <>
              <div className="mt-2"><WeekBar before={c.weekBefore || 0} value={c.value} ceiling={c.weekCeiling} tone={tone} /></div>
              <div className="mt-1 flex justify-between gap-2 text-[11px] tabular-nums text-fg-3">
                {/* feedback #179 — say what the three numbers are */}
                <span>{`7 dní do tohoto dne: ostatní aktivity ${nfmt(c.weekBefore)} + tato ${nfmt(c.value)} ${u}, týdenní strop ${nfmt(c.weekCeiling)} ${u}`}</span>
                <span>{c.left > 0.005 ? `nevstřebáno ${Math.round(c.left * 100)} %` : "vstřebáno"}</span>
              </div>
            </>
          )}
        </div>
      )
    })}
    <p className="border-t border-white/[.07] pt-2.5 text-[11px] leading-4 text-fg-3">
      Bílá čárka = strop (kapacita + rezerva, podle připravenosti). Šedě ostatní aktivity 7 dní do tohoto dne.
      {x.run ? "" : x.sport === "strength" ? " Posilování ovlivňuje celkovou a silovou zátěž." : " Jiný sport ovlivňuje jen celkovou zátěž."}
    </p>
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
  // railway#116 — without a physio's program the ready-made and own programs take its place
  // UX audit F12 — "Zatím vám nikdo program neposlal" sat above the runner's own running
  // programmes; the physio line shows only when a physio is in the picture
  const hasPhysio = Object.keys(boot?.physios || {}).length > 0
  if (!p)
    return (
      <>
        <Head kicker="Program" title="Vaše programy"
          sub={hasPhysio ? "Cviky a posilování pro běžce. Program od fyzioterapeuta se objeví tady, až vám ho pošle." : "Cviky a posilování pro běžce. Program spustíte jedním klepnutím a po cvičení ho odškrtnete."} />
        <SelfPrograms />
      </>
    )
  const ex = (p.exercises || []) as any[]
  const adh = ex.length ? Math.round((ex.reduce((s, e) => s + (e.done_count || 0) / (e.target_count || 12), 0) / ex.length) * 100) : 0
  return (
    <>
      <Head kicker={`${PHASE[p.phase] || p.phase} · ${p.weeks} týdny`} title={p.name} sub={`Vede ${boot?.physios?.[p.physio_id]?.name || "—"}. Odesláno ${fmtD(p.sent_at || p.started_on)}`} />
      <div className="grid gap-4 lg:grid-cols-[1.5fr_.8fr]">
        <Card data-tour="care-programs">
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
      <SelfPrograms />
    </>
  )
}

// (Removed the unreachable `Messages` chat tab: the "messages" route renders
// <Care/>, whose PhysioChat is the live physio conversation. The old standalone
// Messages component had no import or route and only risked drifting out of sync.)
