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
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Team />
        <Settings />
      </div>
    </>
  )
}

const ROLE_CS: Record<string, string> = { owner: "vlastník", admin: "správce", physio: "fyzioterapeut", reception: "recepce" }
const SUB_CS: Record<string, string> = { trial: "zkušební období", active: "aktivní", past_due: "po splatnosti", read_only: "jen pro čtení", cancelled: "zrušeno" }

// W1 roles and members, B2 seats (shown to owner and admin only — the server leaves it out for others)
function Team() {
  const toast = useToast()
  const [d, setD] = useState<any>(null)
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("physio")
  const load = () => api.clinic().then(setD).catch(() => setD({ members: [] }))
  useEffect(() => { void load() }, [])
  if (!d) return <Card><Loading err={null} /></Card>
  const manage = ["owner", "admin"].includes(d.role)
  const sub = d.subscription
  return (
    <Card>
      <h2 className="font-serif text-xl">Tým praxe</h2>
      <p className="mt-1 text-[12px] text-fg-3">{d.is_solo ? "Samostatná praxe. Kolegu přidáte e-mailem jeho účtu v Došlapu." : `${d.name} · vaše role: ${ROLE_CS[d.role] || d.role}`}</p>
      <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="members">
        {d.members.map((m: any) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2 py-2">
            <b className="min-w-0 flex-1">{m.name}{!m.active && <span className="ml-1 font-normal text-fg-3">(neaktivní)</span>}</b>
            {manage ? (
              <select className="rounded-lg border border-white/15 bg-panel px-2 py-1 text-[12.5px]" value={m.role} aria-label={`Role ${m.name}`}
                onChange={async (e) => { try { await api.clinicMemberEdit(m.id, { role: e.target.value }); void load() } catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) } }}>
                {Object.entries(ROLE_CS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            ) : <Chip>{ROLE_CS[m.role] || m.role}</Chip>}
            {manage && m.role !== "owner" && <button type="button" className="text-[12px] font-bold text-accent hover:underline"
              onClick={async () => { await api.clinicMemberEdit(m.id, { role: m.role, active: !m.active }); void load() }}>{m.active ? "Deaktivovat" : "Aktivovat"}</button>}
          </li>
        ))}
      </ul>
      {manage && (
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
          <input className="rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px]" placeholder="E-mail kolegy" aria-label="E-mail kolegy" value={email} onChange={(e) => setEmail(e.target.value)} />
          <select className="rounded-lg border border-white/15 bg-panel px-2 py-1.5 text-[13px]" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
            <option value="physio">fyzioterapeut</option><option value="admin">správce</option><option value="reception">recepce</option></select>
          <Button size="sm" disabled={!email.includes("@")} onClick={async () => {
            try { await api.clinicMemberAdd(email, role); setEmail(""); toast({ title: "Člen přidán" }); void load() } catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
          }}>Přidat</Button>
        </div>
      )}
      <p className="mt-2 text-[11.5px] text-fg-3">Recepce vidí kalendář a platby, ne klinická data.</p>
      {sub && (
        <div className="mt-4 rounded-lg bg-white/[.04] p-3 text-[13px]" data-testid="subscription">
          <b>{`Předplatné: ${SUB_CS[sub.status] || sub.status}`}</b>
          <p className="mt-1 text-fg-2">{`${sub.seats} ${sub.seats === 1 ? "místo" : sub.seats < 5 ? "místa" : "míst"} × ${sub.price_czk_per_seat} Kč = ${sub.monthly_czk} Kč měsíčně`}
            {sub.status === "trial" && sub.trial_ends_at ? ` · zkušební období do ${new Date(sub.trial_ends_at).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" })}` : ""}</p>
          <p className="mt-1 text-[11.5px] text-fg-3">Recepce se do míst nepočítá. Platby zatím nejsou zapnuté.</p>
        </div>
      )}
    </Card>
  )
}

const EVENTS: [string, string][] = [
  ["booking_requested", "Nová žádost o termín"], ["booking_cancelled", "Klient zrušil termín"], ["booking_moved", "Přesunutý termín"],
  ["note_unsigned", "Nepodepsaný záznam večer"], ["invite_accepted", "Klient přijal pozvánku"],
]

// W4 capacity, W13 response time + quick replies, W14 cancellation policy, W15 notifications
function Settings() {
  const toast = useToast()
  const [f, setF] = useState<any>(null)
  useEffect(() => { api.physioMe().then((m: any) => setF({ ...m, quick: (m.quick_replies || []).join("\n") })).catch(() => setF({})) }, [])
  if (!f) return <Card><Loading err={null} /></Card>
  const ns = f.notify_settings || {}
  const save = async () => {
    try {
      await api.physioSettings({
        accepting_new_clients: f.accepting_new_clients, max_new_per_week: f.max_new_per_week === "" || f.max_new_per_week == null ? null : Number(f.max_new_per_week),
        response_time_text: f.response_time_text || null, cancellation_policy: f.cancellation_policy || null, notify_settings: ns,
        quick_replies: String(f.quick || "").split("\n").map((x: string) => x.trim()).filter(Boolean).slice(0, 12),
      })
      toast({ title: "Nastavení uloženo" })
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
  return (
    <Card>
      <h2 className="font-serif text-xl">Kapacita a komunikace</h2>
      <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={f.accepting_new_clients !== false} onChange={(e) => setF({ ...f, accepting_new_clients: e.target.checked })} />Přijímám nové klienty</label>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="text-[12px] font-bold text-fg-2">Nových klientů za týden (max.)<input type="number" min={0} max={50} className={inp} value={f.max_new_per_week ?? ""} onChange={(e) => setF({ ...f, max_new_per_week: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Obvykle odpovídám<input className={inp} value={f.response_time_text || ""} onChange={(e) => setF({ ...f, response_time_text: e.target.value })} placeholder="např. do 24 hodin v pracovní dny" /></label>
      </div>
      <label className="mt-2 block text-[12px] font-bold text-fg-2">Storno podmínky (klient je uvidí při rezervaci)<textarea rows={2} className={inp} value={f.cancellation_policy || ""} onChange={(e) => setF({ ...f, cancellation_policy: e.target.value })} /></label>
      <label className="mt-2 block text-[12px] font-bold text-fg-2">Rychlé odpovědi (jedna na řádek)<textarea rows={3} className={inp} value={f.quick} onChange={(e) => setF({ ...f, quick: e.target.value })} /></label>
      <h3 className="mt-3 font-bold">Upozornění</h3>
      <div className="mt-1 grid gap-1 text-[13px]">
        {EVENTS.map(([k, l]) => (
          <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={!ns[`off:${k}`]}
            onChange={(e) => setF({ ...f, notify_settings: { ...ns, [`off:${k}`]: !e.target.checked } })} />{l}</label>
        ))}
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!ns.email} onChange={(e) => setF({ ...f, notify_settings: { ...ns, email: e.target.checked } })} />Také e-mailem (bez zdravotních údajů)</label>
      </div>
      <p className="mt-1 text-[11.5px] text-fg-3">E-mail a SMS zatím nejsou napojené; upozornění chodí v aplikaci.</p>
      <Button className="mt-3" size="sm" onClick={save}>Uložit nastavení</Button>
    </Card>
  )
}
