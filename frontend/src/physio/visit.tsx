// The visit, full page (physio brief 2026-11-09 W8, W9; round 2 F1). Příprava works with or without a language
// model. The note editor never loses text (round 2 F1): it saves changed fields 2 s after the last keystroke and
// at least every 5 s while typing, retries with backoff, keeps a copy on this device until the server has it,
// asks before leaving with unsaved text, offers templates and "Zkopírovat z minula" (text only, never the OSTRC),
// records only with the client's consent, and after approval leads to the programme, the next visit and the
// return to running.
import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useBlocker, useNavigate } from "react-router"
import { ArrowLeft, CalendarPlus, Copy, Dumbbell, Footprints, Mic, Save, Square } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { Empty, KIND, Loading, REGIONS, useLoad } from "@/physio/common"
import { DiagnosisPicker } from "@/physio/docs"

const SOAP: [string, string][] = [
  ["subjective", "Subjektivně (co uvádí klient)"], ["objective", "Objektivně (cílený nález)"],
  ["assessment", "Pracovní závěr / diagnóza"], ["plan", "Doporučený další postup"], ["services_provided", "Provedené výkony"],
]
const OSTRC: [string, string, [number, string][]][] = [
  ["out_participation", "Účast na tréninku a závodech", [[0, "plná, bez problému"], [8, "plná, ale s obtížemi"], [17, "omezená"], [25, "nemůže trénovat"]]],
  ["out_volume", "Omezení objemu tréninku", [[0, "žádné"], [8, "mírné"], [17, "střední"], [25, "výrazné"]]],
  ["out_performance", "Vliv na výkon", [[0, "žádný"], [8, "mírný"], [17, "střední"], [25, "výrazný"]]],
  ["out_pain", "Bolest", [[0, "žádná"], [8, "mírná"], [17, "střední"], [25, "silná"]]],
]
const FIELDS = ["subjective", "objective", "assessment", "plan", "services_provided", "diagnosis_code", "diagnosis_label",
  "transcript", "summary", "finding", "outcome_kind", "out_participation", "out_volume", "out_performance", "out_pain", "out_region", "out_side"]
const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-3 py-2 text-[14px] font-normal text-fg"

function Back({ rid }: { rid: string }) {
  return <Link to={`/physio/client/${rid}`} className="inline-flex items-center gap-1 text-[13px] font-bold text-fg-2 hover:text-fg"><ArrowLeft className="size-4" aria-hidden />Klient</Link>
}

// ---------------------------------------------------------------- W8 Příprava
export function PrevisitPage({ rid, bid }: { rid: string; bid?: number }) {
  const { d, err } = useLoad<any>(() => api.previsit(rid, bid), [rid, bid])
  if (!d) return <><Back rid={rid} /><Loading err={err} /></>
  return (
    <>
      <Back rid={rid} />
      <h1 className="mt-2 font-serif text-[30px]">Příprava na návštěvu</h1>
      <div className="mt-4 grid gap-4 lg:grid-cols-2" data-testid="previsit">
        <Card>
          <h2 className="font-serif text-xl">1. Důvod návštěvy a otázky klienta</h2>
          <p className="mt-2 text-[14px]">{d.reason || <span className="text-fg-3">Klient důvod neuvedl.</span>}</p>
          {d.questions && <p className="mt-1 text-[14px] text-fg-2">{"Chce probrat: "}{d.questions}</p>}
          {d.intake && <p className="mt-1 text-[13px] text-fg-3">{`Vstupní dotazník: ${Object.keys(d.intake).filter((k) => k !== "consent").join(", ")}`}</p>}
        </Card>
        <Card>
          <h2 className="font-serif text-xl">2. Od poslední návštěvy</h2>
          <p className="mt-2 text-[14px]">{`Od ${fmtD(d.since.from)}: ${d.since.runs} běhů, ${String(d.since.km).replace(".", ",")} km.`}</p>
          <p className="text-[14px]">{d.since.pain_days ? `Bolest ve ${d.since.pain_days} dnech, nejvýš ${d.since.pain_max}/10${d.since.sites.length ? ` (${d.since.sites.join(", ")})` : ""}.` : "Žádná hlášená bolest."}</p>
          {d.care_directive?.headline_cs && <p className="mt-1 text-[13px] text-fg-2">{"Klient dnes vidí: "}<b>{d.care_directive.headline_cs}</b></p>}
        </Card>
        <Card>
          <h2 className="font-serif text-xl">3. Plán a skutečnost</h2>
          {!d.plan_vs_reality ? <Empty>Bez programu.</Empty> : (
            <>
              <p className="mt-2 text-[14px]">{`${d.plan_vs_reality.program}: splněno ${d.plan_vs_reality.adherence?.pct ?? "—"} %`}</p>
              <table className="mt-2 w-full text-[13px]"><tbody>
                {d.plan_vs_reality.exercises.map((e: any, i: number) => (
                  <tr key={i} className="border-t border-white/[.07]"><td className="py-1.5">{e.name}</td><td className="text-right tabular-nums">{`${e.done}/${e.target}`}</td></tr>
                ))}
              </tbody></table>
            </>
          )}
          {d.limits.length > 0 && <p className="mt-2 text-[13px] text-fg-2">{`Omezení: ${d.limits.join(" · ")}`}</p>}
        </Card>
        <Card>
          <h2 className="font-serif text-xl">4. Poslední záznam a plán</h2>
          {!d.last_record ? <Empty>Zatím žádný schválený záznam.</Empty> : (
            <div className="mt-2 grid gap-1 text-[14px]">
              <p className="text-[12px] text-fg-3">{fmtDT(d.last_record.at)}</p>
              {d.last_record.assessment && <p><b>{"Závěr: "}</b>{d.last_record.assessment}</p>}
              {d.last_record.plan && <p><b>{"Plán: "}</b>{d.last_record.plan}</p>}
            </div>
          )}
        </Card>
        <Card>
          <h2 className="font-serif text-xl">5. Chybějící data</h2>
          {d.missing.length === 0 ? <p className="mt-2 text-[14px] text-fg-2">Data jsou kompletní.</p> : <ul className="mt-2 list-disc pl-5 text-[14px]">{d.missing.map((m: string) => <li key={m}>{m}</li>)}</ul>}
        </Card>
        {d.hypotheses && (
          <Card><h2 className="font-serif text-xl">6. {d.hypotheses.label}</h2><Empty>Žádná hypotéza.</Empty></Card>
        )}
      </div>
      {bid && <Link to={`/physio/client/${rid}/visit/${bid}`} className="btn btn-primary mt-4">Otevřít záznam z návštěvy</Link>}
    </>
  )
}


// ---------------------------------------------------------------- W9 / F1 the note editor
export const visitPath = (rid: string, bid: number | string) => `/physio/client/${encodeURIComponent(rid)}/visit/${bid}`
const localKey = (bid: number) => `doslap:note:${bid}`
type Local = { at: string; fields: Record<string, any> }
function readLocal(bid: number): Local | null {
  try { const raw = localStorage.getItem(localKey(bid)); return raw ? JSON.parse(raw) : null } catch { return null }
}
function writeLocal(bid: number, fields: Record<string, any>) {
  try { localStorage.setItem(localKey(bid), JSON.stringify({ at: new Date().toISOString(), fields })) } catch { /* private window or full storage */ }
}
function dropLocal(bid: number) {
  try { localStorage.removeItem(localKey(bid)) } catch { /* ignore */ }
}
const norm = (v: any) => (v === "" || v === undefined ? null : v)
const pick = (x: any) => Object.fromEntries(FIELDS.map((k) => [k, norm(x?.[k])]))
const hhmm = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" }) : "")
const BACKOFF = [2000, 4000, 8000, 16000, 30000]

export function VisitEditor({ rid, bid }: { rid: string; bid: number }) {
  const toast = useToast()
  const nav = useNavigate()
  const [c, setC] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const saved = useRef<Record<string, any>>({})        // the field values the server has
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [restore, setRestore] = useState<Local | null>(null)
  const [tries, setTries] = useState(0)
  const first = useRef<number | null>(null)            // first unsaved change, for the 5 s ceiling
  const last = useRef<number>(0)                       // last change, for the 2 s debounce
  const [tick, setTick] = useState(0)
  const [send, setSend] = useState(true)
  const [caps, setCaps] = useState<any>({})
  const [consent, setConsent] = useState(false)
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const [templates, setTemplates] = useState<any[]>([])
  const [marks, setMarks] = useState<string[]>([])
  const [gate, setGate] = useState<any>(null)
  const cRef = useRef<any>(null)
  cRef.current = c
  const pre = useLoad<any>(() => api.previsit(rid, bid), [rid, bid])
  useEffect(() => {
    api.conclusionOpen(bid).then((x: any) => {
      saved.current = x.id ? pick(x) : pick({})
      setSavedAt(x.autosaved_at || null)
      setC(x)
      // F1.4: a copy on this device that is newer than the server's last save
      const loc = readLocal(bid)
      if (loc && x.status !== "approved") {
        const serverAt = new Date(x.autosaved_at || x.created_at || 0).getTime()
        const differs = Object.entries(loc.fields).some(([k, v]) => norm(v) !== norm(x[k]))
        if (new Date(loc.at).getTime() > serverAt && differs) setRestore(loc); else dropLocal(bid)
      }
    }).catch((e: any) => setErr(e?.message || "Záznam nelze otevřít"))
    api.physioMe().then((m: any) => setCaps(m.capabilities || {})).catch(() => null)
    api.noteTemplates().then((x: any) => setTemplates(x.items || [])).catch(() => null)
  }, [bid])
  const changed = (x: any) => Object.fromEntries(FIELDS.filter((k) => norm(x?.[k]) !== saved.current[k]).map((k) => [k, norm(x[k])]))
  const pending = !!c && c.status !== "approved" && Object.keys(changed(c)).length > 0
  const busy = useRef(false)
  const save = useCallback(async () => {
    const x = cRef.current
    if (!x || x.status === "approved" || busy.current) return null
    const diff = changed(x)
    if (x.id && Object.keys(diff).length === 0) return x
    busy.current = true
    setState("saving")
    try {
      // F1.3: changed fields only; the server stamps autosaved_at
      const out = x.id ? await api.conclusionEdit(x.id, diff) : await api.conclusionDraft(bid, diff)
      saved.current = { ...saved.current, ...diff }
      setC((cur: any) => ({ ...cur, id: out.id, status: out.status, autosaved_at: out.autosaved_at }))
      setSavedAt(out.autosaved_at || new Date().toISOString())
      setState("saved")
      setTries(0)
      first.current = null
      if (Object.keys(changed(cRef.current)).length === 0) dropLocal(bid)
      return out
    } catch (e) {
      setState("error")
      setTries((t) => t + 1)
      throw e
    } finally { busy.current = false; setTick((t) => t + 1) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bid])
  // F1.3: 2 s after the last change, and never more than 5 s after the first unsaved one
  useEffect(() => {
    if (!pending || state === "error" || busy.current) return
    const now = Date.now()
    const due = Math.min(last.current + 2000, (first.current ?? now) + 5000)
    const t = setTimeout(() => { save().catch(() => null) }, Math.max(0, due - now))
    return () => clearTimeout(t)
  }, [c, pending, state, tick, save])
  // retry with backoff while the server cannot be reached
  useEffect(() => {
    if (state !== "error") return
    const t = setTimeout(() => { save().catch(() => null) }, BACKOFF[Math.min(tries - 1, BACKOFF.length - 1)] || 2000)
    return () => clearTimeout(t)
  }, [state, tries, save])
  // F1.5: the browser asks before closing the tab with unsaved text…
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (pending) { e.preventDefault(); e.returnValue = "" } }
    window.addEventListener("beforeunload", h)
    return () => window.removeEventListener("beforeunload", h)
  }, [pending])
  // …and the app asks before any in-app navigation
  const blocker = useBlocker(({ currentLocation, nextLocation }) => pending && currentLocation.pathname !== nextLocation.pathname)
  if (!c) return <><Back rid={rid} /><Loading err={err} /></>
  const done = c.status === "approved"
  const touch = () => { const now = Date.now(); last.current = now; if (first.current == null) first.current = now }
  const update = (patch: Record<string, any>) => {
    touch()
    setC((x: any) => {
      const next = { ...x, ...patch }
      writeLocal(bid, pick(next))       // F1.4: every change also lands on this device
      return next
    })
  }
  const set = (k: string, v: any) => update({ [k]: v })
  const applyFields = (f: any) => update(Object.fromEntries(Object.entries(f).filter(([, v]) => v != null)))
  const copyLast = async () => {
    const x = await api.lastNote(rid, bid)
    if (!x.fields) { toast({ title: "V této epizodě péče zatím není schválený záznam" }); return }
    applyFields(x.fields)
    toast({ title: `Zkopírováno ze záznamu ${fmtD(x.at)} — bez OSTRC` })
  }
  const injury = c.outcome_kind === "injury"
  const complete = injury && OSTRC.every(([k]) => c[k] != null && c[k] !== "")
  const sev = complete ? OSTRC.reduce((s, [k]) => s + Number(c[k]), 0) : null
  const started = !c.slot_at || new Date(c.slot_at).getTime() <= Date.now()
  const canApprove = started && ["summary", "finding", ...SOAP.map(([k]) => k)].some((k) => (c[k] || "").trim()) &&
    (!send || (c.summary || "").trim()) && (!injury || (complete && c.out_region && c.out_side))
  const approve = async () => {
    try {
      const out = await save()
      const x = await api.conclusionApprove((out || cRef.current).id, send)
      saved.current = pick(x)
      dropLocal(bid)
      setC(x)
      setGate(null)
      toast({ title: x.shared_at ? "Záznam je schválený, shrnutí odešlo klientovi" : "Záznam je schválený" })
    } catch (e: any) {
      if (e?.data?.missing) setGate(e.data)
      toast({ title: e?.message || "Nepodařilo se" })
    }
  }
  // F1.8: the same client, the same service, +14 days, the same time
  const followUp = async () => {
    const base = new Date(c.slot_at || Date.now())
    const at = new Date(base.getTime() + 14 * 86400000)
    try {
      const r = await api.visitAdd({ runner_id: rid, starts_at: at.toISOString(), kind: c.kind || "follow_up", service_id: c.service_id ?? undefined })
      toast({ title: r.created.length ? `Kontrola naplánována na ${fmtDT(at.toISOString())}` : "Termín za 2 týdny koliduje — vyberte jiný v Kalendáři" })
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const upload = async (blob: Blob, name: string) => {
    try {
      const out = c.id ? c : await save()
      const r = await api.conclusionAudio(out.id, blob, name)
      if (r.conclusion) { saved.current = pick(r.conclusion); setC(r.conclusion) }
      toast({ title: r.note || "Přepis hotový — zkontrolujte ho" })
    } catch (e: any) { toast({ title: e?.message || "Nahrání selhalo" }) }
  }
  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const r = new MediaRecorder(stream)
      chunks.current = []
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
      r.onstop = () => { stream.getTracks().forEach((t) => t.stop()); void upload(new Blob(chunks.current, { type: r.mimeType || "audio/webm" }), "navsteva.webm") }
      r.start()
      setRec(r)
    } catch { toast({ title: "Mikrofon není dostupný" }) }
  }
  const status = done ? `Schváleno ${fmtDT(c.approved_at)}`
    : state === "error" ? "Neuloženo — zkouším znovu"
    : state === "saving" ? "Ukládám…"
    : pending ? "Neuložené změny…"
    : savedAt ? `Uloženo ${hhmm(savedAt)}` : ""
  return (
    <>
      <div className="sticky top-12 z-20 -mx-4 flex flex-wrap items-center justify-between gap-2 border-b border-white/[.08] bg-bg/95 px-4 py-2 backdrop-blur lg:-mx-8 lg:px-8">
        <Back rid={rid} />
        <span className={`text-[12.5px] ${state === "error" ? "font-bold text-alert" : "text-fg-3"}`} aria-live="polite" data-testid="autosave">
          {status}
          {state === "error" && <button type="button" className="ml-2 font-bold text-accent underline" onClick={() => { save().catch(() => null) }}>Uložit teď</button>}
        </span>
      </div>
      <h1 className="mt-3 font-serif text-[30px]">{`Záznam z návštěvy ${c.slot_at ? fmtDT(c.slot_at) : ""}`}</h1>
      {pre.d?.runner_name && <p className="text-[14px] text-fg-2">{pre.d.runner_name}{c.kind ? ` · ${KIND[c.kind] || c.kind}` : ""}</p>}
      {restore && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-watch/10 px-4 py-3 text-[13.5px]" role="alert" data-testid="restore">
          <span className="flex-1">{`Na tomto zařízení je neuložený text z ${fmtDT(restore.at)}.`}</span>
          <Button size="sm" onClick={() => { applyFields(restore.fields); setRestore(null) }}>Obnovit</Button>
          <Button size="sm" variant="outline" onClick={() => { dropLocal(bid); setRestore(null) }}>Zahodit</Button>
        </div>
      )}
      <div className="mt-4 grid gap-4 min-[1200px]:grid-cols-[1fr_1.4fr]">
        {/* F1.2: two columns from 1200 px; below that the note comes first */}
        <div className="order-4 grid content-start gap-4 min-[1200px]:order-none">
          <Card>
            <h2 className="font-serif text-xl">Před návštěvou</h2>
            {!pre.d ? <Loading err={pre.err} /> : <PrevisitBrief d={pre.d} />}
          </Card>
          <Card>
            <h2 className="font-serif text-xl">Nález na mapě těla</h2>
            <p className="mt-1 text-[12px] text-fg-3">Vyberte místa; připíšou se do objektivního nálezu.</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {REGIONS.filter(([k]) => k !== "other").flatMap(([k, t]) => (["L", "P"] as const).map((side) => {
                const label = `${t} ${side === "L" ? "vlevo" : "vpravo"}`
                const onx = marks.includes(label)
                return <button key={`${k}${side}`} type="button" disabled={done} onClick={() => {
                  const next = onx ? marks.filter((m) => m !== label) : [...marks, label]
                  setMarks(next)
                  if (!onx) set("objective", `${(c.objective || "").trim()}${(c.objective || "").trim() ? "\n" : ""}Nález: ${label}`)
                }} className={`rounded-full border px-2.5 py-1 text-[12px] ${onx ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{label}</button>
              }))}
            </div>
          </Card>
          {caps.asr && !done && (
            <Card>
              <h2 className="font-serif text-xl">Nahrávka</h2>
              <label className="mt-2 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={consent} onChange={async (e) => {
                if (!e.target.checked) return setConsent(false)
                try { await api.recordingConsent(bid); setConsent(true) } catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
              }} />Klient s nahráváním souhlasil.</label>
              <div className="mt-2 flex gap-2">
                {rec ? <Button size="sm" variant="danger" icon={Square} onClick={() => { rec.stop(); setRec(null) }}>Ukončit nahrávání</Button>
                  : <Button size="sm" icon={Mic} disabled={!consent} onClick={startRec}>Nahrát návštěvu</Button>}
              </div>
            </Card>
          )}
        </div>
        <Card className="order-1 min-[1200px]:order-none">
          {!done && (
            <div className="flex flex-wrap items-center gap-2">
              <select className="rounded-lg border border-white/15 bg-panel px-2 py-1.5 text-[13px]" value="" aria-label="Šablona"
                onChange={(e) => { const t = templates[Number(e.target.value)]; if (t) applyFields(t.fields) }}>
                <option value="">Šablona…</option>
                {templates.map((t, i) => <option key={i} value={i}>{t.name}</option>)}
              </select>
              <Button size="sm" variant="outline" icon={Copy} onClick={copyLast}>Zkopírovat z minula</Button>
              <Button size="sm" variant="outline" icon={Save} onClick={async () => {
                const name = window.prompt("Název šablony")
                if (!name) return
                try { await api.noteTemplateAdd({ name, fields: Object.fromEntries(SOAP.map(([k]) => [k, c[k] || ""])) }); toast({ title: "Šablona uložena" }) }
                catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
              }}>Uložit jako šablonu</Button>
            </div>
          )}
          <div className="mt-3 grid gap-3" data-testid="visit-editor">
            {SOAP.map(([k, label]) => (
              <label key={k} className="text-[13px] font-bold text-fg-2">{label}
                <textarea rows={k === "objective" || k === "subjective" ? 5 : 3} disabled={done} value={c[k] || ""} onChange={(e) => set(k, e.target.value)} className={inp} data-field={k} />
              </label>
            ))}
            {!done && <DiagnosisPicker value={c} onPick={(x) => update({ diagnosis_code: x.code, diagnosis_label: x.label })} />}
            {c.diagnosis_label && <p className="-mt-1 text-[13px]">{"Diagnóza: "}{c.diagnosis_code ? `${c.diagnosis_code} ` : ""}{c.diagnosis_label}</p>}
          </div>
        </Card>
        {/* F1.7: OSTRC gets the full width, so no select is cut */}
        <Card className="order-2 min-[1200px]:order-none min-[1200px]:col-span-2">
          <h2 className="font-serif text-xl">Výsledek návštěvy (OSTRC)</h2>
          <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label="Výsledek návštěvy">
            {([[null, "Nevyplňovat"], ["injury", "Zranění"], ["no_injury", "Potvrdit: bez zranění"]] as [string | null, string][]).map(([k, t]) => (
              <button key={t} type="button" role="radio" aria-checked={(c.outcome_kind ?? null) === k} disabled={done}
                // P0.5.4: choosing Zranění never prefills the answers; every select starts at "— vyberte —"
                onClick={() => update({ outcome_kind: k, ...(k === "injury" && c.outcome_kind !== "injury" ? { out_participation: null, out_volume: null, out_performance: null, out_pain: null } : {}) })}
                className={`rounded-full border px-3 py-1.5 text-[13px] ${(c.outcome_kind ?? null) === k ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{t}</button>
            ))}
          </div>
          {injury && (
            <div className="mt-3 grid gap-3 md:grid-cols-2" data-testid="ostrc">
              {OSTRC.map(([k, label, opts]) => (
                <label key={k} className="text-[12.5px] font-bold text-fg-2">{label}
                  <select disabled={done} value={c[k] ?? ""} onChange={(e) => set(k, e.target.value === "" ? null : Number(e.target.value))} className={inp}>
                    <option value="">— vyberte —</option>{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
              ))}
              <label className="text-[12.5px] font-bold text-fg-2">Oblast
                <select disabled={done} value={c.out_region || ""} onChange={(e) => set("out_region", e.target.value || null)} className={inp}>
                  <option value="">— vyberte —</option>{REGIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
              <label className="text-[12.5px] font-bold text-fg-2">Strana
                <select disabled={done} value={c.out_side || ""} onChange={(e) => set("out_side", e.target.value || null)} className={inp}>
                  <option value="">— vyberte —</option><option value="L">levá</option><option value="P">pravá</option><option value="both">obě</option></select></label>
              <p className="text-[13px] md:col-span-2">{sev == null ? "Závažnost se spočítá, až budou vyplněné všechny čtyři otázky." : `Závažnost ${sev}/100`}</p>
            </div>
          )}
        </Card>
        <Card className="order-3 min-[1200px]:order-none min-[1200px]:col-span-2">
          <label className="text-[13px] font-bold text-fg-2">Shrnutí pro klienta
            <textarea rows={4} disabled={done} value={c.summary || ""} onChange={(e) => set("summary", e.target.value)} className={inp} placeholder="Co jste zjistili, co dělat do příští návštěvy." /></label>
          <p className="mt-1 text-[12px] text-fg-3">Klinický nález se klientovi automaticky neodesílá. Klient má právo nahlížet do dokumentace.</p>
          {gate?.missing && (
            <p className="mt-2 rounded-xl bg-watch/10 px-3 py-2 text-[13px]" data-testid="gate">
              {gate.detail}{" "}
              <Link className="font-bold text-accent underline" to={`/physio/client/${encodeURIComponent(rid)}?tab=docs#karta`}>Otevřít kartu</Link>
            </p>
          )}
          {!done ? (
            <div className="mt-4 grid gap-2 border-t border-white/[.08] pt-3">
              <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} />Poslat shrnutí klientovi</label>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => save().then(() => toast({ title: "Uloženo" })).catch((e: any) => toast({ title: e?.message || "Nepodařilo se" }))}>Uložit koncept</Button>
                <Button disabled={!canApprove} onClick={approve} data-testid="visit-approve">Schválit záznam</Button>
              </div>
              {!started && <p className="text-[12px] text-fg-3">Záznam lze schválit až po začátku návštěvy.</p>}
            </div>
          ) : (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-white/[.08] pt-3" data-testid="after-approve">
              <Chip tone="ok">{c.shared_at ? "Shrnutí odesláno" : "Shrnutí neodesláno"}</Chip>
              <Button variant="outline" icon={Dumbbell} onClick={() => nav(`/physio/client/${encodeURIComponent(rid)}?tab=plan`)}>Upravit program</Button>
              <Button variant="outline" icon={CalendarPlus} onClick={followUp}>Naplánovat kontrolu</Button>
              <Button variant="outline" icon={Footprints} onClick={() => nav(`/physio/client/${encodeURIComponent(rid)}?tab=plan#rtr`)}>Začít návrat k běhu</Button>
            </div>
          )}
        </Card>
      </div>
      {blocker.state === "blocked" && <LeaveDialog onStay={() => blocker.reset()} onLeave={() => blocker.proceed()} />}
    </>
  )
}

// F1.5: an in-app dialog, never window.confirm; Escape means "stay"
function LeaveDialog({ onStay, onLeave }: { onStay: () => void; onLeave: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onStay() } }
    window.addEventListener("keydown", k, true)
    return () => window.removeEventListener("keydown", k, true)
  }, [onStay])
  return (
    <div className="fixed inset-0 z-[90] grid place-items-center bg-black/40 p-4" role="alertdialog" aria-modal="true" aria-labelledby="leave-t" data-testid="leave-dialog">
      <div className="w-full max-w-sm rounded-2xl bg-panel p-5 shadow-xl">
        <p id="leave-t" className="text-[15px] font-bold">Máte neuložené změny. Odejít bez uložení?</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button autoFocus variant="outline" onClick={onStay}>Zůstat</Button>
          <Button variant="danger" onClick={onLeave}>Odejít</Button>
        </div>
      </div>
    </div>
  )
}

// the compact Příprava beside the note (F1.2; the same data as the Příprava page)
function PrevisitBrief({ d }: { d: any }) {
  return (
    <div className="mt-2 grid gap-1.5 text-[13px]">
      {d.reason && <p><b>{"Důvod: "}</b>{d.reason}</p>}
      {d.questions && <p><b>{"Chce probrat: "}</b>{d.questions}</p>}
      <p>{`Od ${fmtD(d.since.from)}: ${d.since.runs} běhů, ${String(d.since.km).replace(".", ",")} km`}</p>
      <p>{d.since.pain_text || (d.since.pain_days ? `Bolest hlášena ${d.since.pain_days}×, nejvýš ${d.since.pain_max}/10` : "Žádná hlášená bolest.")}</p>
      {d.plan_vs_reality && <p>{d.plan_vs_reality.adherence?.text || `Program splněn na ${d.plan_vs_reality.adherence?.pct ?? "—"} %`}</p>}
      {d.limits.length > 0 && <p className="text-fg-2">{`Omezení: ${d.limits.join(" · ")}`}</p>}
      <div className="mt-2 border-t border-white/[.08] pt-2">
        <p className="text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Poslední schválený záznam</p>
        {!d.last_record ? <p className="text-fg-3">Zatím žádný.</p> : <>
          <p className="text-[12px] text-fg-3">{fmtDT(d.last_record.at)}</p>
          {d.last_record.assessment && <p><b>{"Závěr: "}</b>{d.last_record.assessment}</p>}
          {d.last_record.plan && <p><b>{"Plán: "}</b>{d.last_record.plan}</p>}
        </>}
      </div>
    </div>
  )
}
