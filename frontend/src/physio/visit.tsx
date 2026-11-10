// The visit, full page (physio brief 2026-11-09 W8, W9). Příprava works with or without a language model;
// the note editor saves itself every 5 seconds after a change, warns before leaving with unsaved text, offers
// templates and "Zkopírovat z minula" (text only, never the OSTRC), records only with the client's consent,
// and after approval leads to the programme, the next visit and the return to running.
import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
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
      {bid && <Link to={`/physio/client/${rid}/navsteva/${bid}`} className="btn btn-primary mt-4">Otevřít záznam z návštěvy</Link>}
    </>
  )
}

// ---------------------------------------------------------------- W9 the note editor
export function VisitEditor({ rid, bid }: { rid: string; bid: number }) {
  const toast = useToast()
  const nav = useNavigate()
  const [c, setC] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [send, setSend] = useState(true)
  const [caps, setCaps] = useState<any>({})
  const [consent, setConsent] = useState(false)
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const [templates, setTemplates] = useState<any[]>([])
  const [marks, setMarks] = useState<string[]>([])
  const cRef = useRef<any>(null)
  cRef.current = c
  const pre = useLoad<any>(() => api.previsit(rid, bid), [rid, bid])
  useEffect(() => {
    api.conclusionOpen(bid).then(setC).catch((e: any) => setErr(e?.message || "Záznam nelze otevřít"))
    api.physioMe().then((m: any) => setCaps(m.capabilities || {})).catch(() => null)
    api.noteTemplates().then((x: any) => setTemplates(x.items || [])).catch(() => null)
  }, [bid])
  const body = (x: any) => Object.fromEntries(FIELDS.map((k) => [k, x[k] === "" ? null : x[k] ?? null]))
  const save = useCallback(async () => {
    const x = cRef.current
    if (!x || x.status === "approved") return null
    const out = x.id ? await api.conclusionEdit(x.id, body(x)) : await api.conclusionDraft(bid, body(x))
    setC((cur: any) => ({ ...cur, id: out.id, status: out.status }))
    setDirty(false)
    setSavedAt(new Date().toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" }))
    return out
  }, [bid])
  // W9.3: autosave 5 s after the last change
  useEffect(() => {
    if (!dirty) return
    const t = setTimeout(() => { save().catch((e: any) => toast({ title: e?.message || "Automatické uložení selhalo" })) }, 5000)
    return () => clearTimeout(t)
  }, [dirty, c, save, toast])
  // W9.4: warn before leaving with unsaved text
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = "" } }
    window.addEventListener("beforeunload", h)
    return () => window.removeEventListener("beforeunload", h)
  }, [dirty])
  if (!c) return <><Back rid={rid} /><Loading err={err} /></>
  const done = c.status === "approved"
  const set = (k: string, v: any) => { setC((x: any) => ({ ...x, [k]: v })); setDirty(true) }
  const applyFields = (f: any) => { setC((x: any) => ({ ...x, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v != null)) })); setDirty(true) }
  const copyLast = async () => {
    const x = await api.lastNote(rid)
    if (!x.fields) { toast({ title: "Předchozí schválený záznam není" }); return }
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
      const saved = await save()
      const x = await api.conclusionApprove((saved || c).id, send)
      setC(x)
      toast({ title: x.shared_at ? "Záznam je schválený, shrnutí odešlo klientovi" : "Záznam je schválený" })
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const followUp = async () => {
    const at = new Date(Date.now() + 14 * 86400000)
    at.setHours(new Date(c.slot_at || Date.now()).getHours(), new Date(c.slot_at || Date.now()).getMinutes(), 0, 0)
    try {
      const r = await api.visitAdd({ runner_id: rid, starts_at: at.toISOString(), kind: "follow_up" })
      toast({ title: r.created.length ? `Kontrola naplánována na ${fmtDT(at.toISOString())}` : "Termín za 2 týdny koliduje — vyberte jiný v Kalendáři" })
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const upload = async (blob: Blob, name: string) => {
    try {
      const saved = c.id ? c : await save()
      const r = await api.conclusionAudio(saved.id, blob, name)
      if (r.conclusion) setC(r.conclusion)
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
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Back rid={rid} />
        <span className="text-[12px] text-fg-3" aria-live="polite" data-testid="autosave">{done ? `Schváleno ${fmtDT(c.approved_at)}` : dirty ? "Neuložené změny…" : savedAt ? `Uloženo ${savedAt}` : ""}</span>
      </div>
      <h1 className="mt-2 font-serif text-[30px]">{`Záznam z návštěvy ${c.slot_at ? fmtDT(c.slot_at) : ""}`}</h1>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <div className="grid content-start gap-4">
          <Card>
            <h2 className="font-serif text-xl">Před návštěvou</h2>
            {!pre.d ? <Loading err={pre.err} /> : (
              <div className="mt-2 grid gap-1 text-[13px]">
                {pre.d.reason && <p><b>{"Důvod: "}</b>{pre.d.reason}</p>}
                <p>{`Od ${fmtD(pre.d.since.from)}: ${pre.d.since.runs} běhů, bolest ve ${pre.d.since.pain_days} dnech${pre.d.since.pain_max != null ? `, max ${pre.d.since.pain_max}/10` : ""}`}</p>
                {pre.d.plan_vs_reality && <p>{`Program splněn na ${pre.d.plan_vs_reality.adherence?.pct ?? "—"} %`}</p>}
                {pre.d.last_record?.plan && <p className="text-fg-2"><b>{"Minule: "}</b>{pre.d.last_record.plan}</p>}
                {pre.d.since.sites.length > 0 && <p className="text-fg-2">{`Hlášená místa: ${pre.d.since.sites.join(", ")}`}</p>}
              </div>
            )}
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
        <Card>
          {!done && (
            <div className="flex flex-wrap items-center gap-2">
              <select className="rounded-lg border border-white/15 bg-panel px-2 py-1.5 text-[13px]" defaultValue="" aria-label="Šablona"
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
                <textarea rows={k === "objective" || k === "subjective" ? 4 : 2} disabled={done} value={c[k] || ""} onChange={(e) => set(k, e.target.value)} className={inp} />
              </label>
            ))}
            {!done && <DiagnosisPicker value={c} onPick={(x) => { set("diagnosis_code", x.code); set("diagnosis_label", x.label) }} />}
            {c.diagnosis_label && <p className="-mt-1 text-[13px]">{`Diagnóza: ${c.diagnosis_code ? `${c.diagnosis_code} ` : ""}${c.diagnosis_label}`}</p>}
            <div className="rounded-lg border border-white/[.1] p-3">
              <p className="text-[13px] font-bold">Výsledek návštěvy (OSTRC)</p>
              <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label="Výsledek návštěvy">
                {([[null, "Nevyplňovat"], ["injury", "Zranění"], ["no_injury", "Potvrdit: bez zranění"]] as [string | null, string][]).map(([k, t]) => (
                  <button key={t} type="button" role="radio" aria-checked={(c.outcome_kind ?? null) === k} disabled={done} onClick={() => set("outcome_kind", k)}
                    className={`rounded-full border px-3 py-1.5 text-[13px] ${(c.outcome_kind ?? null) === k ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{t}</button>
                ))}
              </div>
              {injury && (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
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
                  <p className="text-[13px] sm:col-span-2">{sev == null ? "Závažnost se spočítá, až budou vyplněné všechny čtyři otázky." : `Závažnost ${sev}/100`}</p>
                </div>
              )}
            </div>
            <label className="text-[13px] font-bold text-fg-2">Shrnutí pro klienta
              <textarea rows={4} disabled={done} value={c.summary || ""} onChange={(e) => set("summary", e.target.value)} className={inp} placeholder="Co jste zjistili, co dělat do příští návštěvy." /></label>
            <p className="-mt-1 text-[12px] text-fg-3">Klinický nález se klientovi automaticky neodesílá. Klient má právo nahlížet do dokumentace.</p>
          </div>
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
              <Button variant="outline" icon={Dumbbell} onClick={() => nav(`/physio/client/${rid}?tab=plan`)}>Upravit program</Button>
              <Button variant="outline" icon={CalendarPlus} onClick={followUp}>Naplánovat kontrolu</Button>
              <Button variant="outline" icon={Footprints} onClick={() => nav(`/physio/client/${rid}?tab=plan#rtr`)}>Začít návrat k běhu</Button>
            </div>
          )}
          <p className="mt-2 text-[12px] text-fg-3">{KIND[c.kind] || ""}</p>
        </Card>
      </div>
    </>
  )
}
