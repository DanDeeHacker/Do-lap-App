// Závěr z návštěvy (report v6 Section 6.2.8, Figure A11). The physio records the session or
// uploads the recording; the server transcribes it, drafts the conclusion and drops the audio
// (conclusions.upload_audio). The physio edits and approves — only then the client reads it in the
// chat. A filled structured assessment (OSTRC) makes it a confirmed injury record, the most
// reliable data point the engine is calibrated with.
import { useEffect, useRef, useState } from "react"
import { Mic, Square, Upload } from "lucide-react"
import { api } from "@/api"
import { Button, Chip, Sheet, Switch, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { KIND } from "@/physio/common"

const OSTRC: [string, string, [number, string][]][] = [
  ["out_participation", "Účast na tréninku a závodech", [[0, "plná, bez problému"], [8, "plná, ale s obtížemi"], [17, "omezená"], [25, "nemůže trénovat"]]],
  ["out_volume", "Omezení objemu tréninku", [[0, "žádné"], [8, "mírné"], [17, "střední"], [25, "výrazné"]]],
  ["out_performance", "Vliv na výkon", [[0, "žádný"], [8, "mírný"], [17, "střední"], [25, "výrazný"]]],
  ["out_pain", "Bolest", [[0, "žádná"], [8, "mírná"], [17, "střední"], [25, "silná"]]],
]

export function ConclusionSheet({ booking, onClose, onDone }: { booking: any; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [c, setC] = useState<any>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const file = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    setC(null)
    if (!booking) return
    api.conclusionOpen(booking.id).then(setC).catch((e: any) => { toast({ title: e?.message || "Závěr nelze otevřít" }); onClose() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booking?.id])
  const set = (k: string, v: any) => setC((x: any) => ({ ...x, [k]: v }))
  const done = c?.status === "approved"
  const patch = () => api.conclusionEdit(c.id, {
    transcript: c.transcript ?? "", summary: c.summary ?? "", finding: c.finding ?? "", has_outcome: !!c.has_outcome,
    ...(c.has_outcome ? Object.fromEntries(OSTRC.map(([k]) => [k, c[k] ?? 0])) : {}),
    out_region: c.out_region ?? "", out_side: c.out_side ?? "",
  })
  const upload = async (blob: Blob, name: string) => {
    setBusy("audio")
    try {
      const r = await api.conclusionAudio(c.id, blob, name)
      setC(r.conclusion)
      toast({ title: r.note || (r.llm_draft ? "Přepis hotový, návrh závěru je doplněný — zkontrolujte ho" : "Přepis hotový") })
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
      let x = await patch()
      if (approve) x = await api.conclusionApprove(c.id)
      setC(x)
      toast({ title: approve ? "Závěr je sdílený s klientem" : "Uloženo jako koncept" })
      if (approve) onDone()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  const sev = OSTRC.reduce((s, [k]) => s + (Number(c?.[k]) || 0), 0)
  const inp = "mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] font-normal text-fg"
  return (
    <Sheet open={!!booking} onClose={onClose}
      footer={c && !done ? (
        <div className="grid grid-cols-2 gap-2">
          <Button variant="outline" busy={busy === "save"} onClick={() => save(false)}>Uložit koncept</Button>
          <Button busy={busy === "approve"} disabled={!(c.summary || "").trim()} onClick={() => save(true)} data-testid="conclusion-approve">Schválit a sdílet</Button>
        </div>
      ) : undefined}>
      <h2 className="font-serif text-2xl">Závěr z návštěvy</h2>
      {booking && <p className="mt-1 text-[12.5px] text-fg-2">{booking.runner?.name}{" · "}{fmtDT(booking.slot_at)}{" · "}{KIND[booking.kind] || booking.kind}</p>}
      {!c ? <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám…</p> : (
        <div className="mt-4 grid gap-4" data-testid="conclusion">
          {done && <Chip tone="ok">{`Schváleno ${fmtDT(c.approved_at)} — klient ho vidí`}</Chip>}
          {!done && (
            <div className="rounded-xl bg-white/[.04] p-3">
              <p className="text-[12px] font-bold text-fg-2">Záznam návštěvy</p>
              <p className="mt-1 text-[11.5px] leading-[16px] text-fg-3">
                Nahrávka se jen přepíše do textu a hned se smaže; uloží se přepis. Klient o nahrávání musí vědět.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {rec ? <Button size="sm" variant="danger" icon={Square} onClick={stopRec}>Ukončit nahrávání</Button>
                  : <Button size="sm" icon={Mic} busy={busy === "audio"} onClick={startRec}>Nahrát návštěvu</Button>}
                <Button size="sm" variant="outline" icon={Upload} disabled={!!rec || busy === "audio"} onClick={() => file.current?.click()}>Nahrát soubor</Button>
                <input ref={file} type="file" accept="audio/*" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], e.target.files[0].name)} />
              </div>
            </div>
          )}
          <label className="text-[12px] font-bold text-fg-2">Přepis návštěvy
            <textarea rows={4} disabled={done} value={c.transcript || ""} onChange={(e) => set("transcript", e.target.value)} className={inp}
              placeholder="Doplní se z nahrávky, nebo ho napište." />
          </label>
          <label className="text-[12px] font-bold text-fg-2">Shrnutí pro klienta
            <textarea rows={5} disabled={done} value={c.summary || ""} onChange={(e) => set("summary", e.target.value)} className={inp}
              placeholder="Co jste zjistili, co dělat do příští návštěvy." data-testid="conclusion-summary" />
          </label>
          <label className="text-[12px] font-bold text-fg-2">Klinický nález
            <textarea rows={3} disabled={done} value={c.finding || ""} onChange={(e) => set("finding", e.target.value)} className={inp} />
          </label>
          <div className="rounded-xl border border-white/[.08] p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[13px] font-bold text-fg">Strukturované hodnocení (OSTRC)</p>
                <p className="mt-0.5 text-[11.5px] leading-[16px] text-fg-3">
                  Vyplněné hodnocení udělá ze závěru potvrzený záznam o zranění (nebo potvrzení, že žádné není) — podle něj se
                  kalibruje engine.
                </p>
              </div>
              <Switch checked={!!c.has_outcome} disabled={done} onChange={(v) => set("has_outcome", v)} label="Vyplnit strukturované hodnocení" />
            </div>
            {c.has_outcome && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {OSTRC.map(([k, label, opts]) => (
                  <label key={k} className="text-[12px] font-bold text-fg-2">{label}
                    <select disabled={done} value={c[k] ?? 0} onChange={(e) => set(k, Number(e.target.value))} className={inp}>
                      {opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                    </select>
                  </label>
                ))}
                <label className="text-[12px] font-bold text-fg-2">Oblast
                  <input disabled={done} value={c.out_region || ""} onChange={(e) => set("out_region", e.target.value)} className={inp} placeholder="např. Achillova šlacha" />
                </label>
                <label className="text-[12px] font-bold text-fg-2">Strana
                  <select disabled={done} value={c.out_side || ""} onChange={(e) => set("out_side", e.target.value)} className={inp}>
                    <option value="">—</option><option value="L">levá</option><option value="P">pravá</option><option value="both">obě</option>
                  </select>
                </label>
                <p className="text-[12px] text-fg-2 sm:col-span-2">{`Závažnost ${sev}/100`}{sev === 0 ? " — potvrzení, že zranění není" : ""}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </Sheet>
  )
}
