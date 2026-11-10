// Dokumentace (physio brief 2026-11-09, Phase 1): the client card (R2), care episodes (R3), the approved
// records from the ledger with corrections and addenda (R5/R6), printout, handover and export (R9) and the
// access history (R7). After a withdrawal of consent only this tab stays (R13).
import { useState } from "react"
import { Download, FilePlus2, Pencil, Printer, Send } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { Empty, KIND, Loading, REGIONS, useLoad } from "@/physio/common"

const SOAP: [string, string][] = [
  ["subjective", "Subjektivně (co uvádí klient)"], ["objective", "Objektivně (cílený nález)"],
  ["assessment", "Pracovní závěr / diagnóza"], ["plan", "Doporučený další postup"], ["services_provided", "Provedené výkony"],
]
const OUTCOME: Record<string, string> = {
  returned_full: "návrat k plnému běhu", returned_reduced: "návrat s omezením", referred: "předán jinam", stopped: "péče ukončena",
}
const inp = "mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] font-normal text-fg"

export function DocsTab({ rid }: { rid: string }) {
  const { d, err, reload } = useLoad<any>(() => api.physioDocumentation(rid), [rid])
  const [card, setCard] = useState(false)
  const [handover, setHandover] = useState(false)
  const toast = useToast()
  if (!d) return <Card><Loading err={err} /></Card>
  const exportJson = async () => {
    try {
      const x = await api.docExport(rid)
      const url = URL.createObjectURL(new Blob([JSON.stringify(x, null, 2)], { type: "application/json" }))
      const a = document.createElement("a")
      a.href = url
      a.download = `dokumentace-${rid}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <div className="grid gap-4" data-testid="docs">
      {d.banner && <p className="rounded-xl bg-watch/10 px-3 py-2 text-[13px] text-watch-soft" data-testid="docs-banner">{d.banner}</p>}
      {d.provider_missing?.length > 0 && (
        <p className="rounded-xl bg-watch/10 px-3 py-2 text-[13px] text-watch-soft">Před prvním záznamem doplňte údaje poskytovatele v <a className="font-bold underline" href="/physio/practice">Praxi</a>.</p>
      )}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-serif text-xl">Karta klienta</h2>
          <Button size="sm" variant="outline" icon={Pencil} onClick={() => setCard(true)} data-testid="card-open">{d.patient ? "Upravit" : "Založit kartu"}</Button>
        </div>
        {d.patient ? (
          <p className="mt-2 text-[13px] text-fg-2">
            <b className="text-fg">{`${d.patient.first_name} ${d.patient.last_name}`}</b>
            {d.patient.birth_date ? ` · nar. ${fmtD(d.patient.birth_date)}` : ""}
            {d.patient.sex_at_birth ? ` · ${d.patient.sex_at_birth === "f" ? "žena" : "muž"}` : ""}
            {d.patient.permanent_address?.city ? ` · ${[d.patient.permanent_address.street, d.patient.permanent_address.postal_code, d.patient.permanent_address.city].filter(Boolean).join(", ")}` : ""}
            <span className="block text-[11.5px] text-fg-3">{`Identifikátor ${d.patient.identifier}`}</span>
          </p>
        ) : <Empty>Karta zatím není založená. Bez ní nejde schválit záznam z návštěvy.</Empty>}
        {d.patient_missing?.length > 0 && d.patient && <p className="mt-2 text-[12px] text-watch">Chybí údaje potřebné ke schválení záznamu.</p>}
      </Card>
      <Episodes rid={rid} />
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-serif text-xl">Záznamy z návštěv</h2>
          <span className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" icon={Printer} onClick={() => window.open(`/physio/client/${encodeURIComponent(rid)}/tisk`, "_blank")}>Vytisknout</Button>
            <Button size="sm" variant="outline" icon={Send} onClick={() => setHandover(true)}>Předat dokumentaci</Button>
            <Button size="sm" variant="outline" icon={Download} onClick={exportJson}>Export</Button>
          </span>
        </div>
        {d.records.length === 0 ? <Empty>Zatím žádný schválený záznam.</Empty> : (
          <div className="mt-2 grid gap-3">
            {[...d.records].reverse().map((r: any) => <RecordView key={r.id} r={r} onChange={reload} />)}
          </div>
        )}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Historie přístupů</h2>
        <p className="mt-1 text-[12px] text-fg-3">Kdy, kdo a v jakém rozsahu s dokumentací a daty klienta pracoval (vyhl. 444/2024 § 3/1 t).</p>
        {d.access.length === 0 ? <Empty>Zatím žádný záznam.</Empty> : (
          <ul className="mt-2 grid gap-1 text-[12.5px]" data-testid="access-history">
            {d.access.map((e: any, i: number) => <li key={i} className="text-fg-2"><span className="tabular-nums text-fg-3">{fmtDT(e.at)}</span>{` · ${e.who} ${e.text}`}</li>)}
          </ul>
        )}
      </Card>
      {card && <CardSheet rid={rid} onClose={() => setCard(false)} onSaved={() => { setCard(false); reload() }} />}
      {handover && <HandoverSheet rid={rid} onClose={() => setHandover(false)} />}
    </div>
  )
}

function RecordView({ r, onChange }: { r: any; onChange: () => void }) {
  const toast = useToast()
  const [mode, setMode] = useState<"" | "fix" | "add">("")
  const [orig, setOrig] = useState(false)
  const [f, setF] = useState<any>({})
  const [why, setWhy] = useState("")
  const [asked, setAsked] = useState(false)
  const [text, setText] = useState("")
  const c = r.current || {}
  const shown = orig ? r.original : c
  const save = async () => {
    try {
      if (mode === "fix") await api.recordCorrect(r.id, { changes: f, reason: why, at_patient_request: asked })
      else await api.recordAddendum(r.id, text)
      toast({ title: mode === "fix" ? "Oprava zapsaná jako nový záznam" : "Doplněk zapsán" })
      setMode(""); setF({}); setWhy(""); setText(""); onChange()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <section className="rounded-xl border border-white/[.08] p-3 text-[13px]" data-testid="record">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-fg">{fmtDT(r.encounter_at)}</b>
        <span className="text-fg-3">{r.kind === "discharge" ? "Ukončení péče" : KIND[c.visit_kind] || "Návštěva"}</span>
        {r.corrections.length > 0 && <Chip tone="watch">{`Opraveno ${fmtD(r.corrections.at(-1).at)}, ${r.corrections.at(-1).by}`}</Chip>}
        <span className="flex-1" />
        {r.kind !== "discharge" && <>
          <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => setMode(mode === "fix" ? "" : "fix")}>Opravit záznam</button>
          <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => setMode(mode === "add" ? "" : "add")}>Doplnit záznam</button>
        </>}
      </div>
      {r.kind === "discharge" ? (
        <p className="mt-1 text-fg-2">{OUTCOME[c.episode?.discharge_outcome] || c.episode?.discharge_outcome}{c.episode?.closing_note ? ` — ${c.episode.closing_note}` : ""}</p>
      ) : (
        <dl className="mt-2 grid gap-1.5">
          {SOAP.map(([k, label]) => shown?.[k] ? <div key={k}><dt className="text-[11.5px] font-bold text-fg-3">{label}</dt><dd className="whitespace-pre-line text-fg-soft">{shown[k]}</dd></div> : null)}
          {shown?.diagnosis_label && <div><dt className="text-[11.5px] font-bold text-fg-3">Diagnóza</dt><dd className="text-fg-soft">{`${shown.diagnosis_code ? `${shown.diagnosis_code} ` : ""}${shown.diagnosis_label}`}</dd></div>}
          {shown?.finding && <div><dt className="text-[11.5px] font-bold text-fg-3">Klinický nález</dt><dd className="whitespace-pre-line text-fg-soft">{shown.finding}</dd></div>}
          {shown?.outcome && <div><dt className="text-[11.5px] font-bold text-fg-3">Výsledek (OSTRC)</dt><dd className="text-fg-soft">
            <Outcome o={shown.outcome} />{/* separate text nodes so each answer is translated */}</dd></div>}
          {shown?.summary && <div><dt className="text-[11.5px] font-bold text-fg-3">Shrnutí pro klienta</dt><dd className="whitespace-pre-line text-fg-soft">{shown.summary}</dd></div>}
          {shown?.note_patient_request && <p className="text-[12px] text-fg-3">{shown.note_patient_request}</p>}
        </dl>
      )}
      {r.addenda.map((a: any) => <p key={a.id} className="mt-2 rounded-lg bg-white/[.03] px-3 py-2 text-fg-2"><b className="text-fg">{`Doplněk ${fmtDT(a.at)}, ${a.by}: `}</b>{a.text}</p>)}
      <p className="mt-2 text-[11.5px] text-fg-3">{`Záznam ${r.id} · ${r.author}${r.author_identifier ? ` (${r.author_identifier})` : ""} · schváleno ${fmtDT(r.authorised_at)}`}
        {r.original && <> · <button type="button" className="font-bold underline" onClick={() => setOrig(!orig)}>{orig ? "Zobrazit aktuální znění" : "Zobrazit původní znění"}</button></>}</p>
      {mode === "fix" && (
        <div className="mt-3 grid gap-2 rounded-xl bg-white/[.03] p-3">
          {[...SOAP, ["summary", "Shrnutí pro klienta"] as [string, string]].map(([k, label]) => (
            <label key={k} className="text-[12px] font-bold text-fg-2">{label}
              <textarea rows={2} className={inp} defaultValue={c[k] || ""} onChange={(e) => setF((x: any) => ({ ...x, [k]: e.target.value }))} />
            </label>
          ))}
          <label className="text-[12px] font-bold text-fg-2">Důvod opravy<input className={inp} value={why} onChange={(e) => setWhy(e.target.value)} /></label>
          <label className="flex items-center gap-2 text-[12.5px] text-fg-2"><input type="checkbox" checked={asked} onChange={(e) => setAsked(e.target.checked)} />Na žádost klienta</label>
          <Button size="sm" disabled={!why.trim() || !Object.keys(f).length} onClick={save}>Uložit opravu</Button>
          <p className="text-[11.5px] text-fg-3">Původní znění zůstane čitelné, oprava se uloží jako nový záznam.</p>
        </div>
      )}
      {mode === "add" && (
        <div className="mt-3 grid gap-2 rounded-xl bg-white/[.03] p-3">
          <textarea rows={3} className={inp} value={text} onChange={(e) => setText(e.target.value)} placeholder="Doplněk k záznamu" />
          <Button size="sm" icon={FilePlus2} disabled={!text.trim()} onClick={save}>Uložit doplněk</Button>
        </div>
      )}
    </section>
  )
}

function Episodes({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.episodes(rid), [rid])
  const [closing, setClosing] = useState<any>(null)
  const [out, setOut] = useState({ outcome: "returned_full", return_to_run_date: "", note: "" })
  const items = d?.items || []
  const edit = async (ep: any, patch: any) => {
    try { await api.episodeEdit(ep.id, patch); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const close = async () => {
    try { await api.episodeClose(closing.id, { ...out, return_to_run_date: out.return_to_run_date || null }); toast({ title: "Péče ukončena, záznam o ukončení zapsán" }); setClosing(null); reload() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <Card>
      <h2 className="font-serif text-xl">Epizody péče</h2>
      {items.length === 0 ? <Empty>Epizoda vznikne s první návštěvou, programem nebo plánem.</Empty> : (
        <ul className="mt-2 grid gap-2 text-[13px]">
          {items.map((ep: any) => (
            <li key={ep.id} className="rounded-xl border border-white/[.07] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <b className="text-fg">{"Od "}{fmtD(ep.opened_at)}</b>
                {ep.status === "open" ? <Chip tone="info">probíhá</Chip> : <Chip>{`ukončeno ${fmtD(ep.closed_at)} · ${OUTCOME[ep.discharge_outcome] || ""}`}</Chip>}
                <span className="flex-1" />
                {ep.status === "open" && <Button size="sm" variant="outline" onClick={() => setClosing(ep)}>Ukončit péči</Button>}
              </div>
              {ep.status === "open" ? (
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <select className={inp} value={ep.region || ""} onChange={(e) => edit(ep, { region: e.target.value || null })} aria-label="Oblast">
                    <option value="">— oblast —</option>{REGIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                  <select className={inp} value={ep.side || ""} onChange={(e) => edit(ep, { side: e.target.value || null })} aria-label="Strana">
                    <option value="">— strana —</option><option value="L">levá</option><option value="P">pravá</option><option value="both">obě</option>
                  </select>
                  <input type="date" className={inp} defaultValue={ep.onset_date || ""} onBlur={(e) => edit(ep, { onset_date: e.target.value || null })} aria-label="Začátek obtíží" />
                  <DiagnosisPicker value={ep} onPick={(x) => edit(ep, { diagnosis_code: x.code, diagnosis_label: x.label })} />
                </div>
              ) : ep.diagnosis_label && <p className="mt-1 text-fg-2">{`${ep.diagnosis_code || ""} ${ep.diagnosis_label}`}</p>}
            </li>
          ))}
        </ul>
      )}
      <Sheet open={!!closing} onClose={() => setClosing(null)}>
        <h2 className="font-serif text-2xl">Ukončit péči</h2>
        <label className="mt-3 block text-[12px] font-bold text-fg-2">Výsledek
          <select className={inp} value={out.outcome} onChange={(e) => setOut({ ...out, outcome: e.target.value })}>
            {Object.entries(OUTCOME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <label className="mt-2 block text-[12px] font-bold text-fg-2">Datum návratu k běhu
          <input type="date" className={inp} value={out.return_to_run_date} onChange={(e) => setOut({ ...out, return_to_run_date: e.target.value })} /></label>
        <label className="mt-2 block text-[12px] font-bold text-fg-2">Závěrečná poznámka
          <textarea rows={3} className={inp} value={out.note} onChange={(e) => setOut({ ...out, note: e.target.value })} /></label>
        <Button className="mt-3 w-full" onClick={close}>Ukončit a zapsat záznam</Button>
        <p className="mt-2 text-[11.5px] text-fg-3">Za 3 měsíce se aplikace klienta zeptá, jak se mu daří.</p>
      </Sheet>
    </Card>
  )
}

export function DiagnosisPicker({ value, onPick }: { value: any; onPick: (x: { code: string | null; label: string }) => void }) {
  const [q, setQ] = useState("")
  const [res, setRes] = useState<any>(null)
  const search = async (v: string) => { setQ(v); if (v.trim().length >= 2) setRes(await api.diagnoses(v).catch(() => null)) }
  return (
    <div className="relative sm:col-span-3">
      <input className={inp} value={q} onChange={(e) => search(e.target.value)} aria-label="Diagnóza"
        placeholder={value?.diagnosis_label ? `${value.diagnosis_code || ""} ${value.diagnosis_label}` : "Diagnóza (MKN-10)"} />
      {res && q.trim().length >= 2 && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-xl border border-white/10 bg-panel p-1 text-[12.5px] shadow-lg">
          {res.items.map((x: any) => (
            <button key={x.code} type="button" className="block w-full rounded-lg px-3 py-1.5 text-left hover:bg-white/[.06]" onClick={() => { onPick(x); setQ(""); setRes(null) }}>{`${x.code} ${x.label}`}</button>
          ))}
          {!res.imported && <p className="px-3 py-1.5 text-fg-3">Číselník MKN-10 zatím není importovaný.</p>}
          <button type="button" className="block w-full rounded-lg px-3 py-1.5 text-left text-fg-2 hover:bg-white/[.06]" onClick={() => { onPick({ code: null, label: q.trim() }); setQ(""); setRes(null) }}>{`Použít text „${q.trim()}“ bez kódu`}</button>
        </div>
      )}
    </div>
  )
}

function CardSheet({ rid, onClose, onSaved }: { rid: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const { d } = useLoad<any>(() => api.patientCard(rid), [rid])
  const [f, setF] = useState<any>(null)
  if (d && !f) setF(d.id ? { ...d } : { ...(d.prefill || {}) })
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const save = async () => {
    const body: any = {}
    for (const k of ["first_name", "last_name", "birth_date", "sex_at_birth", "permanent_street", "permanent_city", "permanent_postal_code",
      "phone", "email", "insurer_code", "gp_name", "gp_contact", "anamnesis"]) if (f[k] !== undefined) body[k] = f[k] || null
    if (d?.crypto) for (const k of ["rodne_cislo", "insurance_no"]) if (f[k] !== undefined && f[k] !== d[k]) body[k] = f[k] || null
    try { await api.patientCardSave(rid, body); toast({ title: "Karta klienta uložena" }); onSaved() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const field = (k: string, label: string, type = "text") => (
    <label className="text-[12px] font-bold text-fg-2">{label}<input type={type} className={inp} value={f?.[k] || ""} onChange={(e) => set(k, e.target.value)} /></label>
  )
  return (
    <Sheet open onClose={onClose} footer={f ? <Button className="w-full" onClick={save} data-testid="card-save">Uložit kartu</Button> : undefined}>
      <h2 className="font-serif text-2xl">Karta klienta</h2>
      <p className="mt-1 text-[12px] text-fg-3">Patří poskytovateli a zůstává i po smazání účtu v aplikaci. Údaje z profilu klienta jsou předvyplněné, potvrďte je.</p>
      {!f ? <Loading err={null} /> : (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {d?.profile_changed?.length > 0 && (
            <p className="rounded-xl bg-watch/10 px-3 py-2 text-[12.5px] text-watch-soft sm:col-span-2">
              {"Klient změnil údaje v aplikaci. "}
              <button type="button" className="font-bold underline" onClick={() => setF({ ...f, ...(d.prefill || {}) })}>Převzít změny</button>
            </p>
          )}
          {field("first_name", "Jméno")}{field("last_name", "Příjmení")}
          {field("birth_date", `Datum narození${f.birth_year_hint ? ` (v aplikaci rok ${f.birth_year_hint})` : ""}`, "date")}
          <label className="text-[12px] font-bold text-fg-2">Pohlaví při narození
            <select className={inp} value={f.sex_at_birth || ""} onChange={(e) => set("sex_at_birth", e.target.value)}>
              <option value="">—</option><option value="f">žena</option><option value="m">muž</option></select></label>
          {field("permanent_street", "Ulice a číslo (trvalý pobyt)")}{field("permanent_city", "Obec")}
          {field("permanent_postal_code", "PSČ")}{field("phone", "Telefon", "tel")}{field("email", "E-mail", "email")}
          {field("insurer_code", "Kód pojišťovny")}{field("gp_name", "Praktický lékař")}{field("gp_contact", "Kontakt na lékaře")}
          {d?.crypto ? <>{field("rodne_cislo", "Rodné číslo (šifrováno)")}{field("insurance_no", "Číslo pojištěnce (šifrováno)")}</>
            : <p className="text-[11.5px] text-fg-3 sm:col-span-2">Rodné číslo a číslo pojištěnce lze uložit, až bude nastavené šifrování (FIELD_ENCRYPTION_KEY).</p>}
          <label className="text-[12px] font-bold text-fg-2 sm:col-span-2">Anamnéza a červené vlajky
            <textarea rows={4} className={inp} value={f.anamnesis || ""} onChange={(e) => set("anamnesis", e.target.value)} /></label>
        </div>
      )}
    </Sheet>
  )
}

function HandoverSheet({ rid, onClose }: { rid: string; onClose: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ recipient: "", purpose: "", scope: "" })
  const ok = f.recipient.trim() && f.purpose.trim() && f.scope.trim()
  const save = async () => {
    try { await api.docHandover(rid, f); toast({ title: "Předání zapsáno do historie přístupů" }); onClose() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">Předat dokumentaci</h2>
      <p className="mt-1 text-[12px] text-fg-3">Zapíše se, komu, proč a v jakém rozsahu jste dokumentaci předali (§ 4/1 i). Elektronické odeslání vyžaduje elektronickou pečeť nebo podpis a zatím není zapnuté.</p>
      {[["recipient", "Příjemce"], ["purpose", "Účel"], ["scope", "Rozsah"]].map(([k, label]) => (
        <label key={k} className="mt-2 block text-[12px] font-bold text-fg-2">{label}
          <input className={inp} value={(f as any)[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
      ))}
      <Button className="mt-3 w-full" disabled={!ok} onClick={save}>Zapsat předání</Button>
    </Sheet>
  )
}

// R9: the printout — black on white, A4, header with provider and patient, every entry with its record ID,
// S/O/A/P, author and authorisation, correction notes and a signature line. Printing is logged.
export function PrintPage({ rid }: { rid: string }) {
  const { d, err } = useLoad<any>(async () => { const x = await api.physioDocumentation(rid); await api.docPrint(rid).catch(() => null); return x }, [rid])
  if (!d) return <Loading err={err} />
  const pv = d.provider || {}
  const pt = d.patient
  return (
    <div className="doc-print" data-testid="print">
      <style>{`.doc-print{background:#fff;color:#000;font:12px/1.45 Manrope,system-ui,sans-serif;padding:16px;max-width:190mm;margin:0 auto}
        .doc-print h1{font-size:18px;margin:0 0 4px}.doc-print h2{font-size:13px;margin:14px 0 4px}
        .doc-print .head{border-bottom:1px solid #000;padding-bottom:8px;margin-bottom:8px}
        .doc-print section{break-inside:avoid;border-top:1px solid #999;padding-top:6px;margin-top:10px}
        .doc-print dt{font-weight:700}.doc-print dd{margin:0 0 4px;white-space:pre-line}
        .doc-print .sig{margin-top:18px;border-top:1px solid #000;width:60mm;padding-top:2px;font-size:10px}
        .doc-print .no-print{margin-bottom:12px}
        @media print{@page{size:A4;margin:14mm}.doc-print .no-print{display:none}body{background:#fff}}`}</style>
      <div className="no-print"><button type="button" onClick={() => window.print()} style={{ border: "1px solid #000", padding: "6px 12px", borderRadius: 8 }}>Vytisknout</button></div>
      <div className="head">
        <h1>Zdravotnická dokumentace — fyzioterapie</h1>
        <div>{`${pv.legal_name || pv.name || ""}${pv.legal_form ? `, ${pv.legal_form}` : ""} · IČO ${pv.ico || "—"} · ${[pv.care_site_street, pv.care_site_postal_code, pv.care_site_city].filter(Boolean).join(", ")}`}</div>
        {pt ? <div>{`Pacient: ${pt.first_name} ${pt.last_name} · nar. ${pt.birth_date ? fmtD(pt.birth_date) : "—"} · ${pt.sex_at_birth === "f" ? "žena" : pt.sex_at_birth === "m" ? "muž" : "—"} · ${[pt.permanent_address?.street, pt.permanent_address?.postal_code, pt.permanent_address?.city].filter(Boolean).join(", ")} · identifikátor ${pt.identifier}`}</div> : <div>Karta pacienta není založená.</div>}
      </div>
      {d.records.map((r: any) => {
        const c = r.current || {}
        return (
          <section key={r.id}>
            <h2>{`${fmtDT(r.encounter_at)} · ${r.kind === "discharge" ? "Ukončení péče" : KIND[c.visit_kind] || "Návštěva"} · záznam ${r.id}`}</h2>
            <dl>
              {SOAP.map(([k, label]) => c[k] ? <div key={k}><dt>{label}</dt><dd>{c[k]}</dd></div> : null)}
              {c.diagnosis_label && <div><dt>Diagnóza</dt><dd>{`${c.diagnosis_code || ""} ${c.diagnosis_label}`}</dd></div>}
              {c.finding && <div><dt>Klinický nález</dt><dd>{c.finding}</dd></div>}
              {c.outcome && <div><dt>Výsledek (OSTRC)</dt><dd><Outcome o={c.outcome} /></dd></div>}
              {r.kind === "discharge" && <div><dt>Výsledek péče</dt><dd>{`${OUTCOME[c.episode?.discharge_outcome] || ""}${c.episode?.closing_note ? ` — ${c.episode.closing_note}` : ""}`}</dd></div>}
            </dl>
            {r.corrections.map((k: any) => <div key={k.id}>{`Opraveno ${fmtDT(k.at)}, ${k.by}: ${k.reason}${k.at_patient_request ? " (na žádost pacienta)" : ""}. Původní znění: záznam ${r.id}.`}</div>)}
            {r.addenda.map((a: any) => <div key={a.id}>{`Doplněk ${fmtDT(a.at)}, ${a.by}: ${a.text}`}</div>)}
            <div>{`Zapsal(a): ${r.author}${r.author_identifier ? ` (${r.author_identifier})` : ""} · autorizováno ${fmtDT(r.authorised_at)}`}</div>
            <div className="sig">podpis</div>
          </section>
        )
      })}
      <p style={{ marginTop: 16, fontSize: 10 }}>{`Vytištěno ${fmtDT(d.generated_at)} z aplikace Došlap.`}</p>
    </div>
  )
}

// the OSTRC outcome: region, side in words, severity and each answer as its own text, so the English view
// translates them (one joined string stayed Czech)
const SIDE_CS: Record<string, string> = { L: "vlevo", P: "vpravo", R: "vpravo", both: "oboustranně" }
function Outcome({ o }: { o: any }) {
  if (o.kind === "no_injury") return <>bez zranění</>
  return (
    <>
      <span>{o.region_label || ""}</span>{o.side ? <>{", "}<span>{SIDE_CS[o.side] || o.side}</span></> : null}
      {" · "}<span>{`závažnost ${o.severity}/100`}</span>
      {Object.entries(o.answers || {}).map(([q, a]) => <span key={q}>{" · "}<span>{q}</span>{": "}<span>{String(a)}</span></span>)}
    </>
  )
}
