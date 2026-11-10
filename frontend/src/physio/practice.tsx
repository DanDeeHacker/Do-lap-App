// Praxe (physio brief 2026-11-09 R1 / W14): the provider's legal identity and the physio's qualification —
// required before the first record, copied into every record.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { Loading } from "@/physio/common"

const CLINIC: [string, string][] = [
  ["legal_name", "Název poskytovatele"], ["legal_form", "Právní forma"], ["ico", "IČO"],
  ["registered_street", "Sídlo — ulice"], ["registered_city", "Sídlo — obec"], ["registered_postal_code", "Sídlo — PSČ"],
  ["care_site_street", "Místo poskytování — ulice"], ["care_site_city", "Místo poskytování — obec"], ["care_site_postal_code", "Místo poskytování — PSČ"],
]
const PERSON: [string, string][] = [["title", "Titul"], ["qualification", "Odborná způsobilost"], ["hcp_identifier", "Identifikátor zdravotnického pracovníka"]]

export function PracticePage() {
  const toast = useToast()
  const [d, setD] = useState<any>(null)
  const [f, setF] = useState<any>({})
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.practice().then((x: any) => { setD(x); setF({ ...x.clinic, ...x.physio }) }).catch((e: any) => setErr(e?.message || "Nepodařilo se")) }, [])
  if (!d) return <Loading err={err} />
  const save = async (confirm: boolean) => {
    const body: any = { confirm }
    for (const [k] of [...CLINIC, ...PERSON]) body[k] = f[k] ?? null
    try { const x = await api.practiceSave(body); setD(x); toast({ title: confirm ? "Údaje poskytovatele potvrzené" : "Uloženo" }) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const inp = "mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2.5 text-[14px] font-normal"
  return (
    <>
      <p className="t-label">Praxe</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Údaje poskytovatele</h1>
      <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">
        Tyto údaje se otisknou do každého záznamu z návštěvy a do tisku dokumentace. Bez nich nejde první záznam schválit.
      </p>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-serif text-xl">Poskytovatel</h2>
            {d.missing.length === 0 ? <Chip tone="ok">{d.clinic.confirmed_at ? `potvrzeno ${fmtDT(d.clinic.confirmed_at)}` : "kompletní"}</Chip> : <Chip tone="watch">neúplné</Chip>}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {CLINIC.map(([k, label]) => (
              <label key={k} className="text-[12px] font-bold text-fg-2">{label}
                <input className={inp} value={f[k] || ""} inputMode={k === "ico" ? "numeric" : undefined} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
            ))}
          </div>
        </Card>
        <Card>
          <h2 className="font-serif text-xl">Vy jako autor záznamů</h2>
          <div className="mt-3 grid gap-2">
            {PERSON.map(([k, label]) => (
              <label key={k} className="text-[12px] font-bold text-fg-2">{label}
                <input className={inp} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
            ))}
            {d.physio.credential && <p className="text-[12px] text-fg-3">{`V profilu máte specializaci „${d.physio.credential}“. Do odborné způsobilosti ji nepřenášíme automaticky.`}</p>}
          </div>
        </Card>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => save(false)}>Uložit</Button>
        <Button onClick={() => save(true)} data-testid="practice-confirm">Uložit a potvrdit</Button>
      </div>
    </>
  )
}
