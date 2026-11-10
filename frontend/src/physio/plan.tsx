// Plán (physio brief 2026-11-09 W6/W10/W11/W12): the programme builder, the return to running and the
// training limits in one tab. A sent programme is edited as a draft and published with the reason the client
// sees; the return to running starts behind a readiness gate and counts a session only with the next-morning
// answer; a limit changes Trénink and tells the client why.
import { useEffect, useState } from "react"
import { ArrowDown, ArrowUp, Ban, LayoutTemplate, Pause, Play, Plus, RotateCcw, Send, SkipBack, Square, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT, plural } from "@/lib"
import { Empty, Loading, noData, useLoad } from "@/physio/common"
import { ClinicTests, Proms } from "@/physio/business"

const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal text-fg"

export function PlanTab({ rid, d, onChange }: { rid: string; d: any; onChange: () => void }) {
  return (
    <div className="grid gap-4">
      <ProgramBuilder rid={rid} />
      <div id="rtr"><RtrPlan rid={rid} plan={d.rtr} a={d.a} onChange={onChange} /></div>
      <Limits rid={rid} />
      <div className="grid gap-4 lg:grid-cols-2"><Proms rid={rid} /><ClinicTests rid={rid} /></div>
    </div>
  )
}

// ---------------------------------------------------------------- W10 programme builder
export function AdherenceGrid({ adh }: { adh: any }) {
  if (adh?.undated) return <p className="mt-2 text-[12px] text-fg-3">{`Klient odškrtl ${adh.undated}× cvičení bez data, plnění po týdnech zatím nejde spočítat.`}</p>
  if (!adh?.weeks?.length) return null
  return (
    <div className="mt-2" aria-label="Plnění po týdnech">
      <div className="flex gap-1">
        {adh.weeks.map((w: any) => (
          <div key={w.week} title={`${fmtD(w.week)}: ${w.done} z ${String(w.expected).replace(".", ",")}`}
            className={`grid h-7 min-w-9 flex-1 place-items-center rounded text-[11px] font-bold tabular-nums ${w.pct == null ? "ph-unknown" : w.pct >= 80 ? "ph-risk-low" : w.pct >= 50 ? "ph-risk-med" : "ph-risk-high"}`}>
            {w.pct == null ? "—" : `${w.pct} %`}
          </div>
        ))}
      </div>
      <p className="mt-1 text-[11.5px] text-fg-3">Uplynulé týdny celé, aktuální týden podle uplynulých dnů.</p>
    </div>
  )
}

function ProgramBuilder({ rid }: { rid: string }) {
  const toast = useToast()
  const { d: box, err, reload } = useLoad<any>(() => api.program(rid).then((x: any) => ({ p: x })), [rid])
  const [lib, setLib] = useState(false)
  const [note, setNote] = useState("")
  const [phase, setPhase] = useState({ name: "", weeks: 2 })
  const [tpls, setTpls] = useState<any[]>([])
  useEffect(() => { api.programTemplates().then((x: any) => setTpls(x.items || [])).catch(() => null) }, [])
  const act = async (fn: () => Promise<any>, msg: string) => {
    try { await fn(); toast({ title: msg }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  if (!box) return <Card><Loading err={err} /></Card>
  const p = box.p
  if (!p) {
    return (
      <Card>
        <h2 className="font-serif text-xl">Program</h2>
        <Empty>Klient zatím nemá program od vás.</Empty>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button icon={Plus} onClick={() => act(() => api.programDraft(rid), "Návrh programu je připravený")}>Navrhnout program</Button>
          {tpls.length > 0 && (
            <select className="rounded-lg border border-white/15 bg-panel px-2 py-1.5 text-[13px]" defaultValue="" aria-label="Použít šablonu"
              onChange={(e) => e.target.value && act(() => api.programFromTemplate(rid, Number(e.target.value)), "Program ze šablony je připravený")}>
              <option value="">Použít šablonu…</option>
              {tpls.map((t) => <option key={t.id} value={t.id}>{`${t.name} (${t.exercises} cviků)`}</option>)}
            </select>
          )}
        </div>
      </Card>
    )
  }
  const ex: any[] = p.exercises || []
  const phases: any[] = p.phases || []
  const move = (i: number, dir: -1 | 1) => {
    const ids = ex.map((e) => e.id)
    const j = i + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    void act(() => api.programOrder(p.id, ids), "Pořadí uloženo")
  }
  const groups: [any, any[]][] = phases.length
    ? [...phases.map((ph) => [ph, ex.filter((e) => e.phase_id === ph.id)] as [any, any[]]), [null, ex.filter((e) => !e.phase_id || !phases.some((ph) => ph.id === e.phase_id))]]
    : [[null, ex]]
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-serif text-xl">{p.name}</h2>
          <p className="text-[12px] text-fg-3">
            {p.status === "sent" ? `odesláno ${fmtD(p.sent_at)} · verze ${p.version || 1}` : "koncept — klient ho zatím nevidí"}
            {p.ends_on ? (p.ended ? ` · program skončil ${fmtD(p.ends_on)}` : ` · končí ${fmtD(p.ends_on)}`) : ""}
            {p.pending_changes ? ` · ${p.pending_changes} neodeslaných změn` : ""}
          </p>
        </div>
        <span className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" icon={Plus} onClick={() => setLib(true)}>Přidat cvik</Button>
          <Button size="sm" variant="outline" icon={LayoutTemplate} onClick={async () => {
            const name = window.prompt("Název šablony", p.name)
            if (name) await act(() => api.programSaveTemplate(p.id, name), "Uloženo jako šablona")
          }}>Uložit jako šablonu</Button>
        </span>
      </div>
      <AdherenceGrid adh={p.adherence} />
      <div className="mt-3 grid gap-3" data-testid="program-exercises">
        {groups.map(([ph, list], gi) => (list.length > 0 || ph) && (
          <section key={ph?.id ?? `none${gi}`}>
            {ph && (
              <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[.06em] text-fg-3">
                {`${ph.name} · ${ph.weeks} ${plural(ph.weeks, "týden", "týdny", "týdnů")}`}
                <button type="button" aria-label={`Odebrat fázi ${ph.name}`} onClick={() => act(() => api.programPhaseRemove(p.id, ph.id), "Fáze odebrána")} className="text-fg-3 hover:text-alert"><Trash2 className="size-3.5" aria-hidden /></button>
              </div>
            )}
            {list.length === 0 ? <p className="text-[12px] text-fg-3">Zatím bez cviků.</p> : (
              <ul className="mt-1 grid gap-1.5">
                {list.map((e) => {
                  const i = ex.findIndex((x) => x.id === e.id)
                  return <ExerciseRow key={e.id} e={e} phases={phases} onChange={reload}
                    onUp={i > 0 ? () => move(i, -1) : undefined} onDown={i < ex.length - 1 ? () => move(i, 1) : undefined} />
                })}
              </ul>
            )}
          </section>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-[12px] font-bold text-fg-2">Nová fáze<input className={inp} value={phase.name} onChange={(e) => setPhase({ ...phase, name: e.target.value })} placeholder="např. Odlehčení" /></label>
        <label className="w-24 text-[12px] font-bold text-fg-2">Týdnů<input type="number" min={1} max={26} className={inp} value={phase.weeks} onChange={(e) => setPhase({ ...phase, weeks: Number(e.target.value) })} /></label>
        <Button size="sm" variant="outline" disabled={!phase.name.trim()} onClick={() => act(async () => { await api.programPhaseAdd(p.id, phase.name, phase.weeks); setPhase({ name: "", weeks: 2 }) }, "Fáze přidána")}>Přidat fázi</Button>
      </div>
      <div className="mt-4 grid gap-2 border-t border-white/[.08] pt-3">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} aria-label="Zpráva k programu"
          placeholder={p.status === "sent" ? "Důvod změny (povinný, klient ho uvidí)" : "Zpráva pro klienta k programu (nepovinné)"} className={inp} />
        <Button icon={Send} disabled={!ex.length || (p.status === "sent" && (!p.pending_changes || !note.trim()))}
          onClick={() => act(async () => { await api.programSend(p.id, note || undefined); setNote("") }, "Program je u klienta")}>
          {p.status === "sent" ? "Odeslat klientovi novou verzi" : "Odeslat klientovi"}
        </Button>
      </div>
      {(p.revisions || []).filter((r: any) => r.note).length > 0 && (
        <details className="mt-3 text-[12.5px]">
          <summary className="cursor-pointer font-bold text-fg-2">Historie změn</summary>
          <ul className="mt-2 grid gap-1.5">
            {[...p.revisions].filter((r: any) => r.note).reverse().map((r: any) => (
              <li key={r.id}><span className="text-fg-3">{fmtDT(r.at)}</span>{` · ${r.note}`}
                {(r.changes || []).map((c: string, i: number) => <span key={i} className="block text-fg-2">{`• ${c}`}</span>)}</li>
            ))}
          </ul>
        </details>
      )}
      <Library open={lib} onClose={() => setLib(false)} have={new Set(ex.map((e) => e.library_id).filter(Boolean))}
        onPick={(x) => act(() => api.exerciseAdd(p.id, { name: x.name, dose: x.dose || undefined, per_week: x.per_week || 3, cue: x.cue, library_id: x.id, media_url: x.media_url }), `Přidáno: ${x.name}`)} />
    </Card>
  )
}

function ExerciseRow({ e, phases, onChange, onUp, onDown }: { e: any; phases: any[]; onChange: () => void; onUp?: () => void; onDown?: () => void }) {
  const toast = useToast()
  const [edit, setEdit] = useState(false)
  const [f, setF] = useState<any>({ ...e })
  const save = async () => {
    const patch: any = {}
    for (const k of ["sets", "reps", "duration_s", "load_text", "tempo", "side", "per_week", "cue", "pain_limit", "phase_id"]) {
      const v = f[k] === "" ? null : f[k]
      if (v !== e[k]) patch[k] = ["sets", "reps", "duration_s", "per_week", "pain_limit", "phase_id"].includes(k) && v != null ? Number(v) : v
    }
    try { await api.exerciseEdit(e.id, patch); toast({ title: "Uloženo jako neodeslaná změna" }); setEdit(false); onChange() }
    catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
  }
  return (
    <li className="rounded-lg border border-white/[.1] p-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex flex-col">
          <button type="button" aria-label="Posunout nahoru" disabled={!onUp} onClick={onUp} className="text-fg-3 hover:text-fg disabled:opacity-30"><ArrowUp className="size-3.5" aria-hidden /></button>
          <button type="button" aria-label="Posunout dolů" disabled={!onDown} onClick={onDown} className="text-fg-3 hover:text-fg disabled:opacity-30"><ArrowDown className="size-3.5" aria-hidden /></button>
        </span>
        <b className="min-w-0 flex-1">{e.name}<span className="block text-[12px] font-normal text-fg-2">{`${e.dose || "—"} · ${e.per_week}× týdně${e.pain_limit != null ? ` · bolest do ${e.pain_limit}/10` : ""}`}</span></b>
        <Chip>{`${e.done_count || 0}/${e.target_count}`}</Chip>
        <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => setEdit(!edit)}>{edit ? "Zavřít" : "Upravit"}</button>
        <button type="button" aria-label={`Odebrat ${e.name}`} className="text-fg-3 hover:text-alert" onClick={async () => { await api.exerciseRemove(e.id); onChange() }}><Trash2 className="size-4" aria-hidden /></button>
      </div>
      {edit && (
        <div className="mt-2 grid gap-2 sm:grid-cols-4">
          {[["sets", "Série"], ["reps", "Opakování"], ["duration_s", "Výdrž (s)"], ["per_week", "Krát týdně"]].map(([k, l]) => (
            <label key={k} className="text-[12px] font-bold text-fg-2">{l}<input type="number" min={0} className={inp} value={f[k] ?? ""} onChange={(x) => setF({ ...f, [k]: x.target.value })} /></label>
          ))}
          <label className="text-[12px] font-bold text-fg-2">Zátěž<input className={inp} value={f.load_text ?? ""} onChange={(x) => setF({ ...f, load_text: x.target.value })} placeholder="např. 10 kg" /></label>
          <label className="text-[12px] font-bold text-fg-2">Tempo<input className={inp} value={f.tempo ?? ""} onChange={(x) => setF({ ...f, tempo: x.target.value })} placeholder="3-1-3" /></label>
          <label className="text-[12px] font-bold text-fg-2">Strana<select className={inp} value={f.side ?? ""} onChange={(x) => setF({ ...f, side: x.target.value })}>
            <option value="">—</option><option value="L">levá</option><option value="P">pravá</option><option value="each">každá strana</option><option value="both">obě</option></select></label>
          <label className="text-[12px] font-bold text-fg-2">Hranice bolesti<input type="number" min={0} max={10} className={inp} value={f.pain_limit ?? ""} onChange={(x) => setF({ ...f, pain_limit: x.target.value })} /></label>
          {phases.length > 0 && <label className="text-[12px] font-bold text-fg-2">Fáze<select className={inp} value={f.phase_id ?? ""} onChange={(x) => setF({ ...f, phase_id: x.target.value })}>
            <option value="">—</option>{phases.map((ph) => <option key={ph.id} value={ph.id}>{ph.name}</option>)}</select></label>}
          <label className="text-[12px] font-bold text-fg-2 sm:col-span-4">Pokyn<input className={inp} value={f.cue ?? ""} onChange={(x) => setF({ ...f, cue: x.target.value })} /></label>
          <Button size="sm" onClick={save}>Uložit</Button>
        </div>
      )}
    </li>
  )
}

function Library({ open, onClose, onPick, have }: { open: boolean; onClose: () => void; onPick: (x: any) => Promise<void>; have: Set<string> }) {
  const [q, setQ] = useState("")
  const [cat, setCat] = useState("")
  const [level, setLevel] = useState("")
  const [d, setD] = useState<any>(null)
  const [added, setAdded] = useState<Set<string>>(new Set())
  const [own, setOwn] = useState({ name: "", description: "", media_url: "" })
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => api.exerciseLibrary(q, cat + (level ? `&level=${level}` : "")).then(setD).catch(() => setD({ exercises: [], categories: {} })), 200)
    return () => clearTimeout(t)
  }, [open, q, cat, level])
  return (
    <Sheet open={open} onClose={onClose}>
      <h2 className="font-serif text-2xl">Knihovna cviků</h2>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hledat cvik nebo potíž" aria-label="Hledat cvik" className={inp} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Oblast" className={inp}>
          <option value="">všechny oblasti</option>{Object.entries(d?.categories || {}).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Úroveň" className={inp}>
          <option value="">všechny úrovně</option>{(d?.levels || []).map((l: string) => <option key={l} value={l}>{l}</option>)}</select>
      </div>
      {!d ? <p className="mt-4 text-sm text-fg-2">Načítám…</p> : (
        <ul className="mt-3 grid gap-2" data-testid="library">
          {d.exercises.slice(0, 60).map((x: any) => (
            <li key={x.id} className="flex items-start gap-3 rounded-lg border border-white/[.08] p-2.5 text-[13px]">
              <span className="grid size-12 shrink-0 place-items-center rounded-md ph-unknown text-[10px]" aria-hidden>{x.thumbnail_url ? <img src={x.thumbnail_url} alt="" className="size-12 rounded-md object-cover" /> : "bez videa"}</span>
              <span className="min-w-0 flex-1"><b>{x.name}</b>
                <span className="block text-[12px] text-fg-2">{x.dose ? `${x.dose} · ${x.per_week}× týdně` : "vlastní cvik"}</span>
                <span className="block text-[11.5px] text-fg-3">{(x.treats || []).join(", ")}</span></span>
              {have.has(x.id) ? <Chip tone="ok">V programu</Chip> : added.has(x.id) ? <Chip tone="ok">Přidáno</Chip>
                : <Button size="sm" variant="outline" icon={Plus} onClick={async () => { await onPick(x); setAdded(new Set([...added, x.id])) }}>Přidat</Button>}
            </li>
          ))}
        </ul>
      )}
      <details className="mt-4 text-[13px]">
        <summary className="cursor-pointer font-bold">Vlastní cvik</summary>
        <div className="mt-2 grid gap-2">
          <input className={inp} placeholder="Název" value={own.name} onChange={(e) => setOwn({ ...own, name: e.target.value })} />
          <textarea className={inp} rows={2} placeholder="Popis" value={own.description} onChange={(e) => setOwn({ ...own, description: e.target.value })} />
          <input className={inp} placeholder="Odkaz na video (https://…)" value={own.media_url} onChange={(e) => setOwn({ ...own, media_url: e.target.value })} />
          <Button size="sm" disabled={!own.name.trim()} onClick={async () => { await api.customExerciseAdd({ ...own, media_url: own.media_url || null }); setOwn({ name: "", description: "", media_url: "" }); setQ(q + " "); setQ(q) }}>Uložit do knihovny</Button>
        </div>
      </details>
      <p className="mt-3 text-[11.5px] text-fg-3">Knihovna zatím nemá videa; vlastní cvik může mít odkaz na video.</p>
    </Sheet>
  )
}

// ---------------------------------------------------------------- W11 return to running v2
const READY: [string, string][] = [
  ["walk_30", "30 minut svižné chůze bez bolesti"], ["daily_pain_lt2", "Bolest v běžných činnostech pod 2/10"],
  ["no_night_pain", "Žádná noční bolest ani ranní otok"], ["no_limp", "Chůze bez kulhání"],
]
const COUNT_REASON: Record<string, string> = {
  pain_over_limit: "bolest nad hranicí", too_soon: "příliš brzy po minulém", not_completed: "nedokončeno",
  morning_over_limit: "ráno nad hranicí", morning_worse: "ráno hůř než při sezení", no_morning_data: "chybí ranní odpověď",
  repeat_level: "úroveň se opakuje", step_back: "krok zpět",
}

function RtrPlan({ rid, plan, a, onChange }: { rid: string; plan: any; a: any; onChange: () => void }) {
  const toast = useToast()
  const [tpl, setTpl] = useState<any>(null)
  const [choice, setChoice] = useState("default")
  const [levels, setLevels] = useState<any[]>([])
  const [pain, setPain] = useState(3)
  const [per, setPer] = useState(3)
  const [note, setNote] = useState("")
  const [items, setItems] = useState<Record<string, boolean>>({})
  const [tests, setTests] = useState("")
  const [ack, setAck] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)
  useEffect(() => { api.rtrTemplates().then((x: any) => { setTpl(x); setLevels(x.templates.default) }).catch(() => null) }, [])
  const [lastTests, setLastTests] = useState<string[]>([])
  useEffect(() => {
    api.clinicTests(rid).then((x: any) => setLastTests(Object.values(x.latest || {}).map((t: any) =>
      `${t.name} L ${t.left ?? "—"} / P ${t.right ?? "—"}${t.lsi != null ? `, LSI ${t.lsi} %` : ""} (${fmtD(t.tested_on)})`))).catch(() => null)
  }, [rid])
  const control = async (action: string, lv?: any[]) => {
    try { await api.rtrControl(plan.id, action, lv); toast({ title: "Plán upraven, klient dostal zprávu" }); onChange() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  if (!plan || ["completed", "ended"].includes(plan.status)) {
    const lp = a?.lastPain
    const hot = lp && lp.score != null && lp.score >= pain && Date.now() - new Date(lp.at).getTime() < 7 * 86400000
    const allReady = READY.every(([k]) => items[k] !== undefined)
    return (
      <Card>
        <h2 className="font-serif text-xl">Návrat k běhu</h2>
        {plan && <p className="mt-1 text-[12.5px] text-fg-3">{plan.status === "completed" ? "Poslední plán je splněný." : "Poslední plán byl ukončen."}</p>}
        <h3 className="mt-3 font-bold">Připravenost před startem</h3>
        <div className="mt-1 grid gap-1.5">
          {READY.map(([k, label]) => (
            <div key={k} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="min-w-0 flex-1">{label}</span>
              {[[true, "ano"], [false, "ne"]].map(([v, t]) => (
                <button key={String(v)} type="button" onClick={() => setItems({ ...items, [k]: v as boolean })}
                  className={`rounded-full border px-2.5 py-0.5 text-[12px] ${items[k] === v ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{t as string}</button>
              ))}
            </div>
          ))}
          <label className="text-[12px] font-bold text-fg-2">Testy síly a poskoků (vaše hodnoty)<input className={inp} value={tests} onChange={(e) => setTests(e.target.value)} placeholder="např. výpony na jedné noze L 25 / P 18" /></label>
          {/* physio brief M4: the clinic tests feed the readiness gate */}
          {lastTests.length > 0 && !tests && (
            <button type="button" className="justify-self-start text-[12px] font-bold text-accent hover:underline" onClick={() => setTests(lastTests.join("; "))}>
              {`Vložit poslední testy z ordinace (${lastTests.length})`}</button>
          )}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <label className="text-[12px] font-bold text-fg-2">Šablona<select className={inp} value={choice} onChange={(e) => { setChoice(e.target.value); setLevels(tpl?.templates[e.target.value] || []) }}>
            <option value="default">obecná</option><option value="achilles">Achillova šlacha</option><option value="bone">únavové přetížení kosti</option></select></label>
          <label className="text-[12px] font-bold text-fg-2">Hranice bolesti<select className={inp} value={pain} onChange={(e) => setPain(Number(e.target.value))}>
            {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{`nejvýš ${n}/10`}</option>)}</select></label>
          <label className="text-[12px] font-bold text-fg-2">Sezení na úroveň<select className={inp} value={per} onChange={(e) => setPer(Number(e.target.value))}>
            {[2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        </div>
        {choice === "bone" && <p className="mt-2 rounded-lg ph-risk-med px-3 py-2 text-[12.5px]">Únavové přetížení kosti: návrat vede fyzioterapeut s dalším uvolněním, případně se souhlasem lékaře.</p>}
        <ol className="mt-3 grid gap-1" aria-label="Náhled úrovní">
          {levels.map((l, i) => (
            <li key={i} className="flex items-center gap-2 text-[13px]"><b className="w-5 tabular-nums">{i + 1}</b>
              <input className="min-w-0 flex-1 rounded-md border border-white/15 bg-panel px-2 py-1 text-[13px]" value={l.label} onChange={(e) => setLevels(levels.map((x, k) => k === i ? { ...x, label: e.target.value } : x))} />
              <button type="button" aria-label="Odebrat úroveň" onClick={() => setLevels(levels.filter((_, k) => k !== i))} className="text-fg-3 hover:text-alert"><Trash2 className="size-3.5" aria-hidden /></button></li>
          ))}
        </ol>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Poznámka pro klienta (nepovinné)" aria-label="Poznámka" className={`${inp} mt-2`} />
        {(hot || noData(a)) && (
          <label className="mt-2 flex items-start gap-2 rounded-lg ph-risk-med px-3 py-2 text-[12.5px]" data-testid="rtr-warning">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
            <span>{hot ? `Poslední hlášená bolest je ${lp.score}/10, na hranici nebo nad ní. ` : ""}{noData(a) ? "Klient nemá aktuální data. " : ""}Potvrzuji, že jsem stav klienta ověřil(a).</span>
          </label>
        )}
        {warning && <p className="mt-2 text-[12.5px] text-watch">{warning}</p>}
        <Button className="mt-3" icon={Play} disabled={!allReady || !levels.length || ((hot || noData(a)) && !ack)} data-testid="rtr-create" onClick={async () => {
          try {
            const r = await api.rtrCreate({ runner_id: rid, pain_threshold: pain, sessions_per_level: per, note: note || undefined, template: choice,
              levels: levels.map((l, i) => ({ ...l, level: i + 1 })), readiness: { items, tests: tests ? [tests] : [] } })
            setWarning(r.warning || null)
            toast({ title: "Plán návratu je u klienta" }); onChange()
          } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Začít návrat k běhu</Button>
      </Card>
    )
  }
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-serif text-xl">Návrat k běhu</h2>
          <p className="text-[12px] text-fg-3">{`od ${fmtD(plan.started_on)} · hranice bolesti ${plan.pain_threshold}/10 · ${plan.sessions_per_level} sezení na úroveň`}</p>
        </div>
        <span className="flex flex-wrap gap-1.5">
          {plan.status === "paused"
            ? <Button size="sm" icon={Play} onClick={() => control("resume")}>Obnovit</Button>
            : <Button size="sm" variant="outline" icon={Pause} onClick={async () => { await api.rtrStatus(plan.id, "paused"); onChange() }}>Pozastavit</Button>}
          <Button size="sm" variant="outline" icon={RotateCcw} onClick={() => control("repeat_level")}>Opakovat úroveň</Button>
          <Button size="sm" variant="outline" icon={SkipBack} onClick={() => control("step_back")}>O úroveň zpět</Button>
          <Button size="sm" variant="outline" icon={Square} onClick={() => window.confirm("Ukončit plán návratu?") && control("end")}>Ukončit</Button>
        </span>
      </div>
      {plan.status === "paused" && <p className="mt-2 rounded-lg ph-risk-med px-3 py-2 text-[12.5px]">{plan.paused_reason === "pain_over_limit" ? "Plán se pozastavil: bolest nad hranicí (při sezení nebo ráno)." : "Plán je pozastavený."}</p>}
      <ol className="mt-3 grid gap-1" data-testid="rtr-levels">
        {(plan.levels_json || []).map((l: any) => {
          const cur = l.level === plan.current_level
          const done = l.level < plan.current_level
          return (
            <li key={l.level} className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-[13px] ${cur ? "bg-accent/12" : ""}`}>
              <b className="w-5 tabular-nums">{l.level}</b><span className="flex-1">{l.label}</span>
              {done ? <Chip tone="ok">splněno</Chip> : cur ? <Chip tone="info">{`${plan.cleared_at_current}/${plan.sessions_per_level}`}</Chip> : null}
            </li>
          )
        })}
      </ol>
      <h3 className="mt-3 text-[12px] font-bold uppercase tracking-[.06em] text-fg-3">Sezení</h3>
      {(plan.sessions || []).length === 0 ? <Empty>Klient zatím žádné sezení nezaznamenal.</Empty> : (
        <table className="mt-1 w-full text-[12.5px]">
          <thead className="text-left text-fg-3"><tr><th className="py-1 font-semibold">Kdy</th><th>Úr.</th><th>Bolest</th><th>Ráno</th><th>RPE</th><th>Hodinky</th><th>Stav</th></tr></thead>
          <tbody>
            {[...plan.sessions].reverse().slice(0, 14).map((s: any) => (
              <tr key={s.id} className="border-t border-white/[.07]">
                <td className="py-1.5">{fmtDT(s.logged_at)}</td><td className="tabular-nums">{s.level}</td><td className="tabular-nums">{`${s.pain}/10`}</td>
                <td className="tabular-nums">{s.next_morning_pain != null ? `${s.next_morning_pain}/10` : "—"}</td>
                <td className="tabular-nums">{s.rpe ?? "—"}</td><td>{s.matched_activity_id ? "běh spárován" : "—"}</td>
                <td>{s.counted ? <Chip tone="ok">započteno</Chip> : s.state === "pending" ? <Chip>čeká na ráno</Chip> : <Chip tone="watch">{COUNT_REASON[s.count_reason] || "nezapočteno"}</Chip>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- W12 training limits
const PRESETS: [string, number | null, string][] = [
  ["no_running", null, "Dnes bez běhu"], ["max_km_week", 20, "Max. 20 km týdně"], ["max_km_session", 5, "Max. 5 km na běh"],
  ["no_intervals", null, "Bez intervalů"], ["no_downhill", null, "Bez seběhů"],
]

function Limits({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.limits(rid), [rid])
  const [kind, setKind] = useState("max_km_week")
  const [value, setValue] = useState<string>("20")
  const [until, setUntil] = useState("")
  const [why, setWhy] = useState("")
  const items = (d?.items || []).filter((x: any) => x.active)
  const add = async () => {
    try {
      await api.limitAdd(rid, { kind, value: value === "" ? null : Number(value), ends_on: until || null, reason_cs: why })
      toast({ title: "Omezení platí, Trénink ho zobrazí s důvodem" }); setWhy(""); reload()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const needsValue = d?.kinds?.[kind]?.includes("{v}")
  return (
    <Card>
      <h2 className="flex items-center gap-2 font-serif text-xl"><Ban className="size-4" aria-hidden />Omezení tréninku</h2>
      <p className="mt-1 text-[12px] text-fg-3">Trénink klienta vezme nižší z hodnot: vaše omezení, nebo strop enginu. Výsledek enginu se nemění.</p>
      {items.length > 0 && (
        <ul className="mt-2 grid gap-1 text-[13px]">
          {items.map((x: any) => (
            <li key={x.id} className="flex flex-wrap items-center gap-2"><b>{x.text}</b><span className="text-fg-2">{`— ${x.reason_cs}`}</span>
              {x.ends_on && <span className="text-fg-3">{`do ${fmtD(x.ends_on)}`}</span>}
              <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={async () => { await api.limitEnd(x.id); reload() }}>Ukončit</button></li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {PRESETS.map(([k, v, t]) => <button key={t} type="button" onClick={() => { setKind(k); setValue(v == null ? "" : String(v)) }}
          className={`rounded-full border px-2.5 py-1 text-[12px] ${kind === k ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{t}</button>)}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[auto_auto_1fr_auto]">
        {needsValue && <label className="w-24 text-[12px] font-bold text-fg-2">Hodnota<input type="number" min={0} className={inp} value={value} onChange={(e) => setValue(e.target.value)} /></label>}
        <label className="text-[12px] font-bold text-fg-2">Do<input type="date" className={inp} value={until} onChange={(e) => setUntil(e.target.value)} /></label>
        <label className="text-[12px] font-bold text-fg-2">Důvod (klient ho uvidí)<input className={inp} value={why} onChange={(e) => setWhy(e.target.value)} /></label>
        <Button size="sm" className="self-end" disabled={!why.trim() || (needsValue && value === "")} onClick={add}>Nastavit</Button>
      </div>
    </Card>
  )
}
