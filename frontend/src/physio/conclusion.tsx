// Záznam z návštěvy (report v6 Section 6.2.8, Figure A11; physio brief 2026-11-09 P0.5). Opening the
// sheet stores nothing — the first save creates the draft. The physio approves the record only after
// the visit; sending the summary to the client is a separate choice (D5) and the clinical finding is
// never sent (D6). The OSTRC outcome counts only when the physio chose it: an injury with all four
// answers, region and side, or an explicit "bez zranění".
import { useEffect, useRef, useState } from "react"
import { Mic, Square, Upload } from "lucide-react"
import { api } from "@/api"
import { Button, Chip, Sheet, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { KIND, REGIONS } from "@/physio/common"

const OSTRC: [string, string, [number, string][]][] = [
  ["out_participation", "Účast na tréninku a závodech", [[0, "plná, bez problému"], [8, "plná, ale s obtížemi"], [17, "omezená"], [25, "nemůže trénovat"]]],
  ["out_volume", "Omezení objemu tréninku", [[0, "žádné"], [8, "mírné"], [17, "střední"], [25, "výrazné"]]],
  ["out_performance", "Vliv na výkon", [[0, "žádný"], [8, "mírný"], [17, "střední"], [25, "výrazný"]]],
  ["out_pain", "Bolest", [[0, "žádná"], [8, "mírná"], [17, "střední"], [25, "silná"]]],
]
const FIELDS = ["transcript", "summary", "finding", "outcome_kind", "out_participation", "out_volume", "out_performance", "out_pain", "out_region", "out_side"]

export function ConclusionSheet({ booking, onClose, onDone }: { booking: any; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [c, setC] = useState<any>(null)
  const [asr, setAsr] = useState(false)
  const [send, setSend] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const file = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    setC(null)
    setSend(true)
    if (!booking) return
    api.conclusionOpen(booking.id).then(setC).catch((e: any) => { toast({ title: e?.message || "Záznam nelze otevřít" }); onClose() })
    api.physioMe().then((m: any) => setAsr(!!m.capabilities?.asr)).catch(() => setAsr(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booking?.id])
  const set = (k: string, v: any) => setC((x: any) => ({ ...x, [k]: v }))
  const done = c?.status === "approved"
  const started = !c?.slot_at || new Date(c.slot_at).getTime() <= Date.now()
  const body = () => Object.fromEntries(FIELDS.map((k) => [k, c[k] === "" ? null : c[k] ?? null]))
  // the first save creates the record; later ones edit it
  const store = async () => (c.id ? api.conclusionEdit(c.id, body()) : api.conclusionDraft(booking.id, body()))
  const upload = async (blob: Blob, name: string) => {
    setBusy("audio")
    try {
      const saved = c.id ? c : await store()
      const r = await api.conclusionAudio(saved.id, blob, name)
      setC(r.conclusion || saved)
      toast({ title: r.note || (r.llm_draft ? "Přepis hotový, návrh je doplněný — zkontrolujte ho" : "Přepis hotový") })
    } catch (e: any) { toast({ title: e?.message || "Nahrání selhalo" }) }
    finally { setBusy(null) }
  }
  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const r = new MediaRecorder(stream)
      chunks.current = []
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        void upload(new Blob(chunks.current, { type: r.mimeType || "audio/webm" }), "navsteva.webm")
      }
      r.start()
      setRec(r)
    } catch { toast({ title: "Mikrofon není dostupný — nahrajte soubor" }) }
  }
  const stopRec = () => { rec?.stop(); setRec(null) }
  const save = async (approve: boolean) => {
    setBusy(approve ? "approve" : "save")
    try {
      let x = await store()
      setC(x)
      if (approve) {
        x = await api.conclusionApprove(x.id, send)
        setC(x)
      }
      toast({ title: approve ? (x.shared_at ? "Záznam je schválený, shrnutí odešlo klientovi" : "Záznam je schválený") : "Uloženo jako koncept" })
      if (approve) onDone()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  const share = async () => {
    setBusy("share")
    try { setC(await api.conclusionShare(c.id)); toast({ title: "Shrnutí odešlo klientovi" }) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  const injury = c?.outcome_kind === "injury"
  const complete = injury && OSTRC.every(([k]) => c[k] != null && c[k] !== "")
  const sev = complete ? OSTRC.reduce((s, [k]) => s + Number(c[k]), 0) : null
  const hasText = !!((c?.summary || "").trim() || (c?.finding || "").trim())
  const canApprove = started && hasText && (!send || !!(c?.summary || "").trim()) &&
    (!injury || (complete && !!c.out_region && !!c.out_side))
  const inp = "mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] font-normal text-fg"
  return (
    <Sheet open={!!booking} onClose={onClose}
      footer={c && !done ? (
        <div className="grid gap-2">
          <label className="flex items-center gap-2 text-[12.5px] text-fg-2">
            <input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} data-testid="conclusion-send" />
            Poslat shrnutí klientovi
          </label>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" busy={busy === "save"} onClick={() => save(false)}>Uložit koncept</Button>
            <Button busy={busy === "approve"} disabled={!canApprove} onClick={() => save(true)} data-testid="conclusion-approve">Schválit záznam</Button>
          </div>
          {!started && <p className="text-[11.5px] text-fg-3">Záznam lze schválit až po začátku návštěvy.</p>}
        </div>
      ) : undefined}>
      <h2 className="font-serif text-2xl">Záznam z návštěvy</h2>
      {booking && <p className="mt-1 text-[12.5px] text-fg-2">{booking.runner?.name}{" · "}{fmtDT(booking.slot_at)}{" · "}{KIND[booking.kind] || booking.kind}</p>}
      {!c ? <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám…</p> : (
        <div className="mt-4 grid gap-4" data-testid="conclusion">
          {done && (
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="ok">{`Schváleno ${fmtDT(c.approved_at)}`}</Chip>
              {c.shared_at ? <Chip tone="ok">{`Shrnutí odesláno ${fmtDT(c.shared_at)}`}</Chip> : (
                <Button size="sm" variant="outline" busy={busy === "share"} disabled={!(c.summary || "").trim()} onClick={share}>Poslat shrnutí klientovi</Button>
              )}
            </div>
          )}
          {!done && (
            <div className="rounded-xl bg-white/[.04] p-3">
              <p className="text-[12px] font-bold text-fg-2">Nahrávka návštěvy</p>
              {asr ? (
                <p className="mt-1 text-[11.5px] leading-[16px] text-fg-3">
                  Nahrávka se jen přepíše do textu a hned se smaže; uloží se přepis. Klient o nahrávání musí vědět.
                </p>
              ) : <p className="mt-1 text-[11.5px] leading-[16px] text-fg-3" data-testid="asr-off">Přepis zatím není zapnutý. Záznam napište ručně.</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {rec ? <Button size="sm" variant="danger" icon={Square} onClick={stopRec}>Ukončit nahrávání</Button>
                  : <Button size="sm" icon={Mic} busy={busy === "audio"} disabled={!asr} onClick={startRec}>Nahrát návštěvu</Button>}
                <Button size="sm" variant="outline" icon={Upload} disabled={!asr || !!rec || busy === "audio"} onClick={() => file.current?.click()}>Nahrát soubor</Button>
                <input ref={file} type="file" accept="audio/*" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], e.target.files[0].name)} />
              </div>
            </div>
          )}
          {(asr || c.transcript) && (
            <label className="text-[12px] font-bold text-fg-2">Přepis návštěvy
              <textarea rows={4} disabled={done} value={c.transcript || ""} onChange={(e) => set("transcript", e.target.value)} className={inp}
                placeholder="Doplní se z nahrávky, nebo ho napište." />
            </label>
          )}
          <label className="text-[12px] font-bold text-fg-2">Shrnutí pro klienta
            <textarea rows={5} disabled={done} value={c.summary || ""} onChange={(e) => set("summary", e.target.value)} className={inp}
              placeholder="Co jste zjistili, co dělat do příští návštěvy." data-testid="conclusion-summary" />
          </label>
          <label className="text-[12px] font-bold text-fg-2">Klinický nález
            <textarea rows={3} disabled={done} value={c.finding || ""} onChange={(e) => set("finding", e.target.value)} className={inp} />
            <span className="mt-1 block text-[11.5px] font-normal leading-[16px] text-fg-3">
              Neodesílá se klientovi automaticky. Klient má právo nahlížet do dokumentace.
            </span>
          </label>
          <div className="rounded-xl border border-white/[.08] p-3">
            <p className="text-[13px] font-bold text-fg">Výsledek návštěvy (OSTRC)</p>
            <p className="mt-0.5 text-[11.5px] leading-[16px] text-fg-3">
              Potvrzené zranění nebo potvrzení, že žádné není, je nejspolehlivější údaj, podle kterého se kalibruje engine.
              Bez volby se nic nezapíše.
            </p>
            <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label="Výsledek návštěvy">
              {([[null, "Nevyplňovat"], ["injury", "Zranění"], ["no_injury", "Potvrdit: bez zranění"]] as [string | null, string][]).map(([k, t]) => (
                <button key={t} type="button" role="radio" aria-checked={(c.outcome_kind ?? null) === k} disabled={done}
                  onClick={() => set("outcome_kind", k)} data-testid={`outcome-${k ?? "none"}`}
                  className={`rounded-full border px-3 py-1.5 text-[12.5px] ${(c.outcome_kind ?? null) === k ? "border-accent bg-accent/15 text-fg" : "border-white/10 text-fg-2"}`}>{t}</button>
              ))}
            </div>
            {injury && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {OSTRC.map(([k, label, opts]) => (
                  <label key={k} className="text-[12px] font-bold text-fg-2">{label}
                    <select disabled={done} value={c[k] ?? ""} onChange={(e) => set(k, e.target.value === "" ? null : Number(e.target.value))} className={inp}>
                      <option value="">— vyberte —</option>
                      {opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                    </select>
                  </label>
                ))}
                <label className="text-[12px] font-bold text-fg-2">Oblast
                  <select disabled={done} value={c.out_region || ""} onChange={(e) => set("out_region", e.target.value || null)} className={inp}>
                    <option value="">— vyberte —</option>
                    {REGIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                </label>
                <label className="text-[12px] font-bold text-fg-2">Strana
                  <select disabled={done} value={c.out_side || ""} onChange={(e) => set("out_side", e.target.value || null)} className={inp}>
                    <option value="">— vyberte —</option><option value="L">levá</option><option value="P">pravá</option><option value="both">obě</option>
                  </select>
                </label>
                <p className="text-[12px] text-fg-2 sm:col-span-2">
                  {sev == null ? "Závažnost se spočítá, až budou vyplněné všechny čtyři otázky." : `Závažnost ${sev}/100`}
                </p>
              </div>
            )}
            {c.outcome_kind === "no_injury" && <p className="mt-2 text-[12px] text-fg-2">Zapíše se potvrzení, že klient zranění nemá.</p>}
          </div>
        </div>
      )}
    </Sheet>
  )
}
