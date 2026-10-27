// Kalendář (report v6 Section 6.2.7): appointments, booking requests and free slots. A confirmed
// booking lands in both calendars and both sides get a reminder with the preparation the day
// before (booking.due_reminders); after the visit the physio writes the conclusion here.
import { useState } from "react"
import { useNavigate } from "react-router"
import { CalendarPlus, Check, FileText, Trash2, X } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { Empty, KIND, Loading, useLoad } from "@/physio/common"
import { ConclusionSheet } from "@/physio/conclusion"

const dayKey = (iso: string) => (iso || "").slice(0, 10)
const dayLabel = (iso: string) => new Date(iso).toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })

export function CalendarPage({ pid }: { pid: string }) {
  const toast = useToast()
  const nav = useNavigate()
  const { d, err, reload } = useLoad<any>(() => api.physioBootstrap(pid), [pid])
  const [date, setDate] = useState("")
  const [time, setTime] = useState("09:00")
  const [dur, setDur] = useState(45)
  const [busy, setBusy] = useState<string | null>(null)
  const [concl, setConcl] = useState<any>(null)
  const act = async (k: string, fn: () => Promise<any>, msg: string) => {
    setBusy(k)
    try { await fn(); toast({ title: msg }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  if (!d) return <Loading err={err} />
  const now = new Date().toISOString()
  const remind = new Set((d.reminders || []).map((r: any) => r.booking_id ?? r.id))
  const confirmed = (d.bookings || []).filter((b: any) => b.status === "confirmed")
  const upcoming = confirmed.filter((b: any) => (b.slot_at || "") >= now.slice(0, 10))
  const past = confirmed.filter((b: any) => (b.slot_at || "") < now.slice(0, 10)).reverse().slice(0, 12)
  const byDay: Record<string, any[]> = {}
  for (const b of upcoming) (byDay[dayKey(b.slot_at)] ||= []).push(b)
  const addSlot = () => {
    if (!date) { toast({ title: "Vyberte den" }); return }
    const at = new Date(`${date}T${time}:00`).toISOString()
    void act("slot", () => api.slotAdd(pid, at, dur), "Volný termín přidán")
  }
  return (
    <>
      <p className="t-label">Kalendář</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Termíny a žádosti</h1>
      <div className="mt-5 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="grid content-start gap-4">
          <Card>
            <h2 className="font-serif text-xl">Žádosti o termín</h2>
            {(d.requests || []).length === 0 ? <Empty>Žádné nové žádosti.</Empty> : (
              <ul className="mt-2 divide-y divide-white/[.07]" data-testid="requests">
                {d.requests.map((b: any) => (
                  <li key={b.id} className="flex flex-wrap items-center gap-2 py-2.5 text-[13px]">
                    <span className="min-w-0 flex-1">
                      <b className="text-fg">{b.runner?.name}</b>
                      <span className="block text-[12px] text-fg-3">{fmtDT(b.slot_at)}{" · "}{KIND[b.kind] || b.kind}</span>
                    </span>
                    <Button size="sm" icon={Check} busy={busy === `c${b.id}`} onClick={() => act(`c${b.id}`, () => api.bookingConfirm(b.id), "Termín potvrzen — klient dostal zprávu")}>Potvrdit</Button>
                    <Button size="sm" variant="outline" icon={X} busy={busy === `d${b.id}`} onClick={() => act(`d${b.id}`, () => api.bookingDecline(b.id), "Termín odmítnut")}>Odmítnout</Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <h2 className="font-serif text-xl">Nadcházející návštěvy</h2>
            {Object.keys(byDay).length === 0 ? <Empty>Zatím žádné potvrzené termíny.</Empty> : (
              <div className="mt-2 grid gap-4" data-testid="upcoming">
                {Object.entries(byDay).map(([day, bs]) => (
                  <section key={day}>
                    <h3 className="text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">{dayLabel(day)}</h3>
                    <ul className="mt-1.5 grid gap-2">
                      {bs.map((b: any) => <Visit key={b.id} b={b} reminder={remind.has(b.id)} onOpen={() => nav(`/physio/client/${b.runner_id}`)}
                        onConclusion={() => setConcl(b)} onSaved={reload} />)}
                    </ul>
                  </section>
                ))}
              </div>
            )}
          </Card>
          <Card>
            <h2 className="font-serif text-xl">Proběhlé návštěvy</h2>
            {past.length === 0 ? <Empty>Zatím žádné.</Empty> : (
              <ul className="mt-2 divide-y divide-white/[.07] text-[13px]">
                {past.map((b: any) => (
                  <li key={b.id} className="flex flex-wrap items-center gap-2 py-2.5">
                    <span className="min-w-0 flex-1"><b className="text-fg">{b.runner?.name}</b>
                      <span className="block text-[12px] text-fg-3">{fmtDT(b.slot_at)}{" · "}{KIND[b.kind] || b.kind}</span></span>
                    {b.conclusion?.status === "approved" ? <Chip tone="ok">závěr sdílen</Chip>
                      : b.conclusion ? <Chip tone="watch">rozepsaný závěr</Chip> : <Chip tone="alert">bez závěru</Chip>}
                    <Button size="sm" variant="outline" icon={FileText} onClick={() => setConcl(b)}>Závěr</Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="grid content-start gap-4">
          <Card>
            <h2 className="font-serif text-xl">Volné termíny</h2>
            <p className="mt-1 text-[12px] text-fg-2">Běžci si z nich vybírají v záložce Péče; termín platí až po vašem potvrzení.</p>
            <div className="mt-3 grid grid-cols-[1fr_auto_auto] gap-2">
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Den"
                className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
              <input type="time" value={time} step={900} onChange={(e) => setTime(e.target.value)} aria-label="Čas"
                className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
              <select value={dur} onChange={(e) => setDur(Number(e.target.value))} aria-label="Délka"
                className="rounded-xl border border-white/10 bg-panel px-2 py-2 text-[13px]">
                {[30, 45, 60, 90].map((m) => <option key={m} value={m}>{`${m} min`}</option>)}
              </select>
            </div>
            <Button className="mt-2 w-full" icon={CalendarPlus} busy={busy === "slot"} onClick={addSlot} data-testid="slot-add">Přidat termín</Button>
            {(d.slots || []).length === 0 ? <Empty>Žádné volné termíny.</Empty> : (
              <ul className="mt-3 divide-y divide-white/[.07] text-[13px]" data-testid="slots">
                {d.slots.map((s: any) => (
                  <li key={s.id} className="flex items-center gap-2 py-2">
                    <span className="flex-1 text-fg">{fmtDT(s.slot_at)}<span className="text-fg-3">{` · ${s.duration_min} min`}</span></span>
                    {s.status !== "open" ? <Chip tone="info">{s.status === "booked" ? "obsazeno" : "rezervováno"}</Chip>
                      : <button type="button" aria-label="Smazat termín" className="text-fg-3 hover:text-alert"
                          onClick={() => act(`s${s.id}`, () => api.slotRemove(s.id), "Termín smazán")}><Trash2 className="size-4" aria-hidden /></button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
      <ConclusionSheet booking={concl} onClose={() => setConcl(null)} onDone={() => { setConcl(null); reload() }} />
    </>
  )
}

function Visit({ b, reminder, onOpen, onConclusion, onSaved }: { b: any; reminder: boolean; onOpen: () => void; onConclusion: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [prep, setPrep] = useState<string>(b.prep_info || "")
  const [edit, setEdit] = useState(false)
  const save = async () => {
    try { await api.bookingPrep(b.id, prep); toast({ title: "Pokyny uloženy — klient je uvidí v připomínce" }); setEdit(false); onSaved() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const a = b.assessment || {}
  return (
    <li className="rounded-xl border border-white/[.07] bg-white/[.03] p-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <b className="tabular-nums text-fg">{new Date(b.slot_at).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}</b>
        <button type="button" onClick={onOpen} className="font-bold text-accent hover:underline">{b.runner?.name}</button>
        <span className="text-fg-3">{KIND[b.kind] || b.kind}</span>
        {reminder && <Chip tone="watch">do 24 h · klient vidí připomínku</Chip>}
        {a.overall != null && <span className="text-fg-3">{`· skóre ${Math.round(a.overall)}`}</span>}
        <span className="flex-1" />
        <Button size="sm" variant="outline" icon={FileText} onClick={onConclusion}>Závěr</Button>
      </div>
      {edit ? (
        <div className="mt-2 grid gap-2">
          <textarea value={prep} onChange={(e) => setPrep(e.target.value)} rows={2} aria-label="Pokyny k přípravě"
            placeholder="Co si vzít s sebou, kudy do ordinace…" className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
          <div className="flex gap-2"><Button size="sm" onClick={save}>Uložit</Button><Button size="sm" variant="outline" onClick={() => setEdit(false)}>Zrušit</Button></div>
        </div>
      ) : (
        <p className="mt-1.5 text-[12px] text-fg-2">
          {b.prep_info ? <>{"Pokyny: "}{b.prep_info}</> : <span className="text-fg-3">Bez pokynů k přípravě.</span>}{" "}
          <button type="button" className="font-bold text-accent hover:underline" onClick={() => setEdit(true)}>Upravit</button>
        </p>
      )}
    </li>
  )
}
