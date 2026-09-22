import { Fragment, useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { AxisLineChart, Bars, Card, Chip, Field, InfoDot, Label, Metric, Ring, Sheet, Slider, Sparkline, useAsync, useToast } from "@/ui"
import { METRIC_INFO as MI, MECH_INFO_BY_LABEL } from "@/metricinfo"
import { clamp, czk, FEEL_LABEL, fmtD, fmtDT, fmtSlot, paceStr, PHASE, QUAD, sgn } from "@/lib"
import MuscleAnatomy, { PainHeatmap, type BodyPoint } from "@/components/MuscleAnatomy"

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
        sub="Hodinky změří, jak jste běželi. Neřeknou, jak vám bylo. Váš zápis pocitu a bolesti k danému běhu je to, co z dat samotných nevyčtete — a kdykoli ho můžete upravit."
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
                    <span className="flex-1">
                      <b className="text-sm">{x.title} · {x.distance_km} km</b>
                      <em className="block text-xs not-italic text-[#71837b]">{fmtD(x.started_at)} · {paceStr(x.pace_s_km)}/km · {x.descent_m} m klesání</em>
                    </span>
                    <span className="text-[#6ce6d3]">›</span>
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
                        <b className="text-sm">{act ? `${act.title} · ${act.distance_km} km` : "Běh"}</b>
                        <em className="mt-0.5 block truncate text-xs not-italic text-[#71837b]">
                          {fmtD(f.submitted_at)} · pocit {FEEL_LABEL[f.feeling] || "—"} · nohy {f.legs}/5
                          {f.pain_during > 0 ? ` · bolest ${f.pain_during}/10` : ""}
                        </em>
                      </span>
                      {f.pain_site && <Chip tone="alert">{f.pain_site}</Chip>}
                      <span className="text-[#71837b] transition group-hover:text-[#6ce6d3]">Upravit</span>
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
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">{edit ? "Upravit zápis" : `${act.title}${act.distance_km ? ` · ${act.distance_km} km` : ""}`}</h2>
      <p className="mt-1 text-xs text-[#a9c2b9]">{fmtD(act.started_at)}{act.pace_s_km ? ` · ${paceStr(act.pace_s_km)}/km` : ""}{act.surface ? ` · ${surf(act.surface)}` : ""}{act.descent_m ? ` · ${act.descent_m} m sklesáno` : ""}</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
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
        <div>
          <Label>Kde to bolelo</Label>
          <p className="mt-1 text-xs text-[#71837b]">Klepněte na všechna místa, která bolela — můžete vybrat víc, silueta rozliší levou a pravou stranu.</p>
          <div className="mt-3"><MuscleAnatomy multi onSelect={setPoints} initialRegions={initialRegions} /></div>
        </div>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
      <div className="mt-5 flex gap-2">
        <button onClick={submit} disabled={busy} className="flex-1 rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">{busy ? "Ukládám…" : edit ? "Uložit změny" : "Uložit zápis"}</button>
        <button onClick={onClose} className="rounded-full border border-white/15 px-5 py-3 text-sm font-bold text-[#a9c2b9]">Zrušit</button>
      </div>
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
type Metric = { label: string; unit: string; dec: number; value: number; baseline: number; z: number; delta: string; hot: boolean; position: number; weeks: number[]; dates: string[]; series: number[]; seriesDates: string[]; terrain?: boolean }

// dates of the last `n` runs that carry `field` (to label the per-run charts)
function fieldDates(acts: any[], field: string, n: number): string[] {
  return acts.filter((a) => a[field] != null).sort((a, b) => a.started_at.localeCompare(b.started_at)).slice(-n).map((a) => a.started_at)
}

// Build a metric card straight from activity fields (cadence, stride, oscillation)
// — recent mean vs a baseline window, last 8 runs as the mini chart.
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
  return { label, unit, dec, value, baseline, z, delta, hot: false, position: clamp(50 + z * 18, 8, 92), weeks, dates: dates.slice(-8), series: vals.slice(-26), seriesDates: dates.slice(-26), terrain: false }
}

function MechMetricCard({ m, onSelect }: { m: Metric; onSelect: () => void }) {
  const { label, unit, dec, value, baseline, z, delta, hot, weeks, dates } = m
  // Numeric axis for the interval bar: usual range = baseline ± 1 SD (SD backed
  // out from the z-score), so the bar shows real numbers, not just a dot.
  const isd = Math.abs(z) > 0.15 ? Math.abs(value - baseline) / Math.abs(z) : (Math.abs(baseline) * 0.03 || 1)
  const bLo = baseline - isd, bHi = baseline + isd
  const dLo = Math.min(bLo, value) - isd * 0.8, dHi = Math.max(bHi, value) + isd * 0.8
  const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 4, 96)
  const has = weeks.length > 0
  const mn = has ? Math.min(...weeks) : 0
  const mx = has ? Math.max(...weeks) : 1
  const pad = (mx - mn) * 0.35 || Math.abs(mx * 0.02) || 1
  const lo = mn - pad
  const hi = mx + pad
  const wkY = (v: number) => 72 - ((v - lo) / (hi - lo || 1)) * 54
  const x = (i: number) => 24 + (i / Math.max(1, weeks.length - 1)) * 184
  return (
    <div onClick={onSelect} role="button" tabIndex={0} className="group w-full cursor-pointer p-4 text-left">
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <Label>{label}</Label>
          {MECH_INFO_BY_LABEL[label] && <InfoDot text={MECH_INFO_BY_LABEL[label]} label={label} />}
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
        <p className="mt-1 text-[10px] text-[#9bb3aa]">obvyklé rozmezí {mfmt(dec, bLo)}–{mfmt(dec, bHi)} {unit} · střed {mfmt(dec, baseline)}</p>
      </div>
      {has && (
        <div className="mt-4 border-t border-white/5 pt-3">
          <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">
            Posledních {weeks.length} běhů{dates.length ? ` · ${fmtD(dates[0])} → ${fmtD(dates.at(-1)!)}` : ""}
          </p>
          <svg viewBox="0 0 220 100" className="mt-2 h-24 w-full overflow-visible" aria-label={`Trend metriky ${label} za posledních ${weeks.length} běhů`}>
            <line x1="20" y1="8" x2="20" y2="74" stroke="#6ce6d3" strokeOpacity=".25" />
            <line x1="20" y1="74" x2="212" y2="74" stroke="#6ce6d3" strokeOpacity=".25" />
            {[mx, mn].map((tick, ti) => (
              <text key={ti} x="16" y={wkY(tick) + 2.5} textAnchor="end" fill="#71837b" fontSize="6.5">{mfmt(dec, tick)}</text>
            ))}
            {weeks.map((v, i) => {
              const latest = i === weeks.length - 1
              const cx = x(i)
              const y = wkY(v)
              const xlabel = latest ? "nyní" : i === 0 && dates[0] ? fmtD(dates[0]) : ""
              return (
                <g key={i}>
                  <text x={cx} y={y - 4} textAnchor="middle" fill={latest ? "#ffc1ab" : "#9bb3aa"} fontSize="6" fontWeight={latest ? "bold" : "normal"}>{mfmt(dec, v)}</text>
                  <rect x={cx - 4.5} y={y} width={9} height={Math.max(74 - y, 1)} rx="2" fill={latest ? "#e77a59" : "#6ce6d3"} fillOpacity={latest ? 1 : 0.42} />
                  <text x={cx} y="88" textAnchor={i === 0 ? "start" : "middle"} fill={latest ? "#ffc1ab" : "#71837b"} fontSize="6.5">{xlabel}</text>
                </g>
              )
            })}
          </svg>
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

type Cell = { now: number; z: number | null } | null
// Per terrain profile × per metric: recent mean and its drift-z against the
// same profile's baseline — same windows/logic as engine._drift_z_core.
function terrainCompare(acts: any[]) {
  const lo = dayAgo(84), hi = dayAgo(29), rec = dayAgo(28)
  const byB: Record<string, any[]> = {}, recB: Record<string, any[]> = {}
  for (const a of acts) {
    const b = bucketKey(a)
    if (a.started_at <= hi && a.started_at > lo) (byB[b] ||= []).push(a)
    if (a.started_at > rec) (recB[b] ||= []).push(a)
  }
  const ranked = Object.keys(recB).sort((x, y) => recB[y].length - recB[x].length)
  const withBase = ranked.filter((b) => (byB[b]?.length || 0) >= 3)
  // Buckets that have a baseline (reliable z) come first, then the rest — so a
  // minority surface like trail can still surface for the diversity pass even
  // when it has no comparable baseline yet (its cells show the value, z "málo dat").
  const pool = [...withBase, ...ranked.filter((b) => !withBase.includes(b))]
  // Prefer surface diversity: take the strongest bucket of each distinct
  // surface first (so trail shows even when it's a minority of runs), then
  // fill the remaining slots with the next-highest buckets.
  const keys: string[] = []
  const seenSurf = new Set<string>()
  for (const b of pool) { const s = b.split("|")[0]; if (!seenSurf.has(s)) { keys.push(b); seenSurf.add(s) } if (keys.length === 3) break }
  for (const b of pool) { if (keys.length === 3) break; if (!keys.includes(b)) keys.push(b) }
  const profiles = keys.map((b) => ({ key: b, ...bucketParts(b), nNow: recB[b].length }))
  const rows = M_DEFS.map((m) => ({
    ...m,
    cells: keys.map((b): Cell => {
      const recv = recB[b].map((a) => a[m.field]).filter((v: any) => v != null) as number[]
      if (!recv.length) return null
      const bv = (byB[b] || []).map((a) => a[m.field]).filter((v: any) => v != null) as number[]
      const now = mean(recv)
      if (bv.length < 3) return { now, z: null }
      const s = Math.max(std(bv), Math.abs(mean(bv)) * 0.012) || 1
      return { now, z: (now - mean(bv)) / s }
    }),
  }))
  return { profiles, rows }
}

function TerrainMatrix({ acts }: { acts: any[] }) {
  const { profiles, rows } = useMemo(() => terrainCompare(acts), [acts])
  if (!profiles.length) return <Card><Empty>Zatím není dost běhů ve srovnatelných profilech terénu.</Empty></Card>
  const zTone = (z: number | null) => (z == null ? "#71837b" : Math.abs(z) >= 1 ? "#e77a59" : Math.abs(z) >= 0.5 ? "#f6d69a" : "#6ce6d3")
  const cols = `minmax(112px,1.2fr) repeat(${profiles.length}, minmax(0,1fr))`
  return (
    <Card>
      <Label>Podle profilu terénu</Label>
      <p className="mt-1 text-xs text-[#71837b]">Každý sloupec je jiný profil (povrch · sklon · tempo). Hodnota = průměr posledních 28 dní, odchylka (z) proti vaší baseline ve stejném profilu.</p>
      <div className="mt-4 grid items-stretch gap-y-1" style={{ gridTemplateColumns: cols }}>
        <div />
        {profiles.map((p) => (
          <div key={p.key} className="rounded-xl bg-[#102724] px-2 py-2 text-center">
            <p className="text-[13px] font-semibold text-[#f1f8f1]">{p.surf}</p>
            <p className="text-[10px] text-[#9bb3aa]">{p.grade} · {p.pace}</p>
            <p className="mt-0.5 font-mono text-[9px] text-[#71837b]">{p.nNow} běhů</p>
          </div>
        ))}
        {rows.map((r) => (
          <Fragment key={r.field}>
            <div className="col-span-full mt-1 h-px bg-white/5" />
            <div className="flex items-baseline gap-1 py-2.5 pr-2 text-[12px] text-[#a9c2b9]">{r.label}<span className="text-[10px] text-[#71837b]">{r.unit}</span></div>
            {r.cells.map((c, i) => (
              <div key={i} className="px-1 py-2.5 text-center">
                {c ? (
                  <>
                    <p className="font-serif text-lg leading-none text-[#f1f8f1]">{mfmt(r.dec, c.now)}</p>
                    <p className="mt-1 font-mono text-[10px]" style={{ color: zTone(c.z) }}>{c.z != null ? `${sgn(Math.round(c.z * 100) / 100)} z` : "málo dat"}</p>
                  </>
                ) : (
                  <p className="text-[#71837b]">—</p>
                )}
              </div>
            ))}
          </Fragment>
        ))}
      </div>
    </Card>
  )
}

function RunHistoryReal({ acts }: { acts: any[] }) {
  const { me } = useApp()
  const rid = me?.runner_id
  const [open, setOpen] = useState(false)
  const [run, setRun] = useState<number | null>(null)
  const [cmp, setCmp] = useState<Record<number, any>>({})
  useEffect(() => {
    if (run == null || !rid || cmp[run] !== undefined) return
    let alive = true
    setCmp((c) => ({ ...c, [run]: null })) // mark loading
    api.runCompare(rid, run).then((d) => alive && setCmp((c) => ({ ...c, [run]: d || false }))).catch(() => alive && setCmp((c) => ({ ...c, [run]: false })))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, rid])
  return (
    <>
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-4 flex w-full items-center justify-between gap-4 rounded-[24px] border border-white/10 bg-[#102724] px-5 py-4 text-left text-[#f1f8f1] transition hover:border-[#6ce6d3]/40">
        <span><span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">Historie běhů</span><span className="mt-1 block font-serif text-xl">Běhy s dynamikou — rozklikni pro srovnání s normou</span></span>
        <span className="text-[#6ce6d3]">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {acts.slice().sort((a, b) => (b.started_at || "").localeCompare(a.started_at || "")).slice(0, 20).map((x) => {
            const isOpen = run === x.id
            const d = cmp[x.id]
            return (
              <div key={x.id} className="overflow-hidden rounded-2xl border border-white/10 bg-[#0c201d]">
                <button onClick={() => setRun(isOpen ? null : x.id)} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left">
                  <span className="grid size-9 place-items-center rounded-xl bg-[#17382f] text-[10px] font-bold text-[#6ce6d3]">{surf(x.surface)}</span>
                  <span><b className="text-sm">{x.title}</b><em className="block text-xs not-italic text-[#71837b]">{fmtD(x.started_at)} · {x.distance_km} km · {paceStr(x.pace_s_km)}/km · {x.avg_hr} tep</em></span>
                  <span className="font-mono text-xs text-[#9bb3aa]">VR {x.vert_ratio_pct} · {isOpen ? "▴" : "▾"}</span>
                </button>
                {isOpen && (
                  d && d.metrics?.length ? (
                    <CompareTable data={d} />
                  ) : d === false ? (
                    <dl className="grid grid-cols-3 gap-2 border-t border-white/5 px-4 py-3 text-[10px] md:grid-cols-6">
                      {[["Kadence", x.cadence_spm && `${x.cadence_spm} spm`], ["Kontakt", x.gct_ms && `${x.gct_ms} ms`], ["Krok", x.stride_len_m && `${x.stride_len_m} m`], ["Osc.", x.vert_osc_cm && `${x.vert_osc_cm} cm`], ["Balance", x.gct_balance_l ? `${x.gct_balance_l} %` : "—"], ["Klesání", x.descent_m != null && `${x.descent_m} m`]].map(([k, v]) => (
                        <div key={k as string}><dt className="uppercase tracking-[.1em] text-[#71837b]">{k}</dt><dd className="mt-0.5 font-mono text-[11px] text-[#f1f8f1]">{v || "—"}</dd></div>
                      ))}
                    </dl>
                  ) : (
                    <p className="border-t border-white/5 px-4 py-3 text-xs text-[#71837b]">Načítám srovnání s normou…</p>
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
  if (!a) return <Empty>Načítám…</Empty>
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
  const metrics: Metric[] = []
  if (a.tavr) metrics.push(eng(a.tavr.series, "vert_ratio_pct", "Vertikální poměr", "%", 1, a.tavr.recMean, a.tavr.baseMean, a.tavr.z, `${sgn(a.tavr.z)} z`, a.tavr.z >= 1, clamp(50 + a.tavr.z * 18, 8, 92)))
  if (a.gct) metrics.push(eng(a.gct.series, "gct_ms", "Kontakt se zemí", "ms", 0, a.gct.recMean, a.gct.baseMean, a.gct.z, `${sgn(a.gct.z)} z`, a.gct.z >= 1, clamp(50 + a.gct.z * 18, 8, 92)))
  if (a.bal) metrics.push(eng(a.bal.series, "gct_balance_l", "Symetrie kontaktu", "%", 1, a.bal.now, a.bal.baseline, a.bal.excursion, `${sgn(a.bal.excursion)} p.b.`, a.bal.excursion >= 0.8, clamp(50 + a.bal.excursion * 22, 8, 92), false))
  // Prefer the backend's per-terrain drift-z (terrain-cleaned); fall back to a
  // plain recent-vs-baseline mean only when there isn't enough bucketed data.
  const engDrift = (d: any, field: string, label: string, unit: string, dec: number): Metric | null =>
    d
      ? eng(d.series, field, label, unit, dec, d.recMean, d.baseMean, d.z, `${sgn(d.z)} z`, Math.abs(d.z) >= 1, clamp(50 + d.z * 18, 8, 92))
      : metricFromActs(acts, field, label, unit, dec)
  for (const m of [
    engDrift(a.cadence, "cadence_spm", "Kadence", "spm", 0),
    engDrift(a.stride, "stride_len_m", "Délka kroku", "m", 2),
    engDrift(a.vosc, "vert_osc_cm", "Vertikální oscilace", "cm", 1),
    engDrift(a.duty, "duty_factor", "Poměr kontaktu", "", 2),
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
                        <AxisLineChart points={m.series.map((v, i) => ({ t: m.seriesDates[i] || m.seriesDates.at(-1) || "", v }))} dec={m.dec} unit={` ${m.unit}`} color={m.hot ? "#e77a59" : "#6ce6d3"} height={130} />
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

// One run vs. the runner's baseline as of that run's day and a month before —
// shows both how the run sits on the norm and how the norm itself has drifted.
// Embedded in each expanded row of the run-history table.
function CompareTable({ data }: { data: any }) {
  const eps = (dec: number) => (dec ? 1 / Math.pow(10, dec) : 1)
  const fmt = (m: any, x: number | null) =>
    x == null ? "—" : m.key === "pace_s_km" ? `${paceStr(x)}/km` : `${mfmt(m.dec, x)}${m.unit ? ` ${m.unit}` : ""}`
  return (
    <div className="border-t border-white/5 px-4 py-3">
      <p className="text-[10px] text-[#71837b]">Profil: <b className="text-[#9bb3aa]">{data.bucketLabel}</b> · srovnání s vaší normou k tomuto dni a měsíc předtím.</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left font-mono text-[10px] uppercase text-[#71837b]">
            <th className="py-1 pr-2">Metrika</th><th className="pr-2">Tento běh</th><th className="pr-2">Baseline (ten den)</th><th className="pr-2">Měsíc předtím</th><th>Posun normy</th>
          </tr></thead>
          <tbody>
            {data.metrics.map((m: any) => {
              const shift = m.baseNow != null && m.base1mo != null ? m.baseNow - m.base1mo : null
              const dev = m.baseNow != null ? m.value - m.baseNow : null
              return (
                <tr key={m.key} className="border-t border-white/5">
                  <td className="py-2 pr-2 text-[#a9c2b9]">{m.label}{!m.terrain && <span className="ml-0.5 text-[9px] text-[#71837b]" title="málo běhů v profilu → napříč terénem">*</span>}</td>
                  <td className="pr-2 font-mono"><b className="text-[#f1f8f1]">{fmt(m, m.value)}</b>{dev != null && Math.abs(dev) >= eps(m.dec) && <small className="ml-1 text-[10px] text-[#9bb3aa]">({dev > 0 ? "+" : "−"}{mfmt(m.dec, Math.abs(dev))})</small>}</td>
                  <td className="pr-2 font-mono text-[#a9c2b9]">{fmt(m, m.baseNow)}</td>
                  <td className="pr-2 font-mono text-[#71837b]">{fmt(m, m.base1mo)}</td>
                  <td>{shift != null && Math.abs(shift) >= eps(m.dec)
                    ? <span className="font-mono text-[11px] text-[#c9dcd4]">{shift > 0 ? "▲" : "▼"} {mfmt(m.dec, Math.abs(shift))}</span>
                    : <span className="text-[10px] text-[#71837b]">beze změny</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[9px] text-[#71837b]">V závorce = odchylka běhu od normy toho dne. „Posun normy" = jak se baseline změnila za měsíc. * málo běhů v přesném profilu → baseline napříč terénem.</p>
    </div>
  )
}

/* ============================ ZÁTĚŽ ============================ */
const LOAD_IDS = new Set([
  // v0.6 spine
  "session_spike", "spike_latent", "pace_spike", "load_capacity",
  // grade-C ACWR context + the rest of the load axis
  "ewma", "hi_load", "load_creep", "mono", "desc", "desc_steep", "aer", "hrv", "rhr", "hrvcv", "tsb", "taper",
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
  if (!L) return <Empty>Načítám…</Empty>

  // State follows the quadrant (post-hysteresis) so Zátěž matches it exactly.
  const loadHot = a.quadrant === "overreaching" || a.quadrant === "critical"
  const loadHeadline = loadHot ? "Zátěž je zvýšená" : (a.load ?? 0) >= 12 ? "Zátěž roste" : "Zátěž drží v normě"
  const loadDesc = loadHot
    ? "Akutní zátěž a související signály se zvedají nad vaši obvyklou úroveň — dobrý čas ubrat a hlídat regeneraci."
    : "Objem, intenzita, monotónnost i regenerace sedí na vaší obvyklé úrovni."
  const loadSig = ((a.signals || []) as any[]).filter((s) => LOAD_IDS.has(s.id))

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
            {L?.safeLongRunKm && (
              <div className="mt-4 flex items-center gap-2 rounded-xl bg-white/[.04] px-3 py-2.5">
                <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-[#17382f] text-[#6ce6d3]">⤢</span>
                <p className="text-[11px] leading-4 text-[#a9c2b9]">
                  Bezpečný nejdelší běh: <b className="text-[#f1f8f1]">≈ {L.safeLongRunKm} km</b>
                  <span className="block text-[10px] text-[#71837b]">≈ +10 % nad váš nejdelší běh 30 dní · nad +100 % prudce roste riziko</span>
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

/* ============================ ZPRÁVY ============================ */
export function Messages() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const ms = (boot?.messages || []) as any[]
  const p = boot?.program
  const physioName = p ? boot?.physios?.[p.physio_id]?.name : null
  const [body, setBody] = useState("")
  const send = async () => { const b = body.trim(); if (!b) return; setBody(""); await api.send(rid, "runner", b); refresh() }
  return (
    <>
      <Head kicker="Zprávy" title={physioName || "Zatím bez fyzioterapeuta"} sub={physioName ? "Píšete přímo tomu, kdo vede váš program." : "Zprávy se otevřou, jakmile váš případ někdo převezme."} />
      <Card className="max-w-2xl">
        <div className="flex max-h-[52vh] flex-col gap-2 overflow-y-auto pr-1">
          {ms.length ? ms.map((m) => (
            <div key={m.id} className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${m.sender === "runner" ? "ml-auto bg-[#c7ff54] text-[#071313]" : m.sender === "system" ? "mx-auto bg-white/5 text-[#a9c2b9]" : "bg-[#17382f] text-[#f1f8f1]"}`}>
              {m.body}<span className="mt-1 block text-[10px] opacity-60">{fmtDT(m.created_at)}</span>
            </div>
          )) : <Empty>Zatím žádné zprávy.</Empty>}
        </div>
        <div className="mt-4 flex gap-2">
          <input value={body} onChange={(e) => setBody(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Napsat zprávu…" className="flex-1 rounded-xl border px-3 py-2.5 text-sm" />
          <button onClick={send} className="rounded-full bg-[#c7ff54] px-5 text-sm font-bold text-[#071313]">Odeslat</button>
        </div>
      </Card>
    </>
  )
}
