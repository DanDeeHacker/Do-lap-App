// Kalendář (report v6 Section 6.2.7): appointments, booking requests and free slots. A confirmed
// booking lands in both calendars and both sides get a reminder with the preparation the day
// before (booking.due_reminders); after the visit the physio writes the conclusion here.
import { useState } from "react"
import { useNavigate } from "react-router"
import { CalendarPlus, Check, FileText, MoreHorizontal, Trash2, X } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { Empty, KIND, Loading, shownScore, useLoad } from "@/physio/common"
import { ConclusionSheet } from "@/physio/conclusion"
import { AddVisit, IcsLink, Services, WeekView, WorkingHours } from "@/physio/schedule"

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
  const [ver, setVer] = useState(0)
  const [allSlots, setAllSlots] = useState(false)
  const free = useLoad<any>(() => api.availability().then((x: any) => x.preview || []), [ver])
  const refresh = () => { setVer((v) => v + 1); reload() }
  const act = async (k: string, fn: () => Promise<any>, msg: string) => {
    setBusy(k)
    try { await fn(); toast({ title: msg }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  if (!d) return <Loading err={err} />
  const nowMs = Date.now()
  const t = (b: any) => new Date(b.slot_at).getTime()
  const remind = new Set((d.reminders || []).map((r: any) => r.booking_id ?? r.id))
  const confirmed = (d.bookings || []).filter((b: any) => b.status === "confirmed")
  // physio brief 2026-11-09 P0.6: a visit is past once it started; completed and no-show stay listed
  const upcoming = confirmed.filter((b: any) => t(b) > nowMs)
  const past = (d.bookings || []).filter((b: any) => ["confirmed", "completed", "no_show"].includes(b.status) && t(b) <= nowMs)
    .sort((a: any, b: any) => t(b) - t(a)).slice(0, 12)
  const openSlots = (d.slots || []).filter((s: any) => s.status === "open")
  // P0.6.10: a request that clashes with a confirmed visit says so
  const clash = (r: any) => {
    const a0 = t(r), a1 = a0 + (r.duration_min || 45) * 60000
    const x = confirmed.find((b: any) => b.id !== r.id && t(b) < a1 && a0 < t(b) + (b.duration_min || 45) * 60000)
    return x ? `Koliduje s návštěvou ${x.runner?.name || "klienta"} v ${new Date(x.slot_at).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}` : null
  }
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
      <div className="mt-5"><WeekView pid={pid} version={ver} /></div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
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
                      {clash(b) && <span className="block text-[12px] font-bold text-alert" data-testid="request-clash">{clash(b)}</span>}
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
                        onConclusion={() => setConcl(b)} onSaved={refresh} openSlots={openSlots} freeTimes={free.d || []} />)}
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
                    {b.status === "no_show" ? <Chip>nedostavil(a) se</Chip> : <RecordChip c={b.conclusion} />}
                    {b.status === "confirmed" && <>
                      <Button size="sm" variant="outline" busy={busy === `p${b.id}`} onClick={() => act(`p${b.id}`, () => api.bookingComplete(b.id), "Návštěva označena jako proběhlá")}>Proběhla</Button>
                      <Button size="sm" variant="outline" busy={busy === `n${b.id}`} onClick={() => act(`n${b.id}`, () => api.bookingNoShow(b.id), "Zaznamenáno: nedostavil(a) se")}>Nedostavil(a) se</Button>
                    </>}
                    {b.status !== "no_show" && <Button size="sm" variant="outline" icon={FileText} onClick={() => setConcl(b)}>Záznam</Button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="grid content-start gap-4">
          <AddVisit onDone={refresh} />
          <WorkingHours onDone={refresh} />
          <Services />
          <IcsLink />
          <Card>
            <h2 className="font-serif text-xl">Jednorázové volné termíny</h2>
            <p className="mt-1 text-[12px] text-fg-2">Běžci si z nich vybírají v záložce Péče; termín platí až po vašem potvrzení.</p>
            <div className="mt-3 grid grid-cols-[1fr_auto_auto] gap-2">
              <input type="date" value={date} min={new Date().toLocaleDateString("sv-SE")} onChange={(e) => setDate(e.target.value)} aria-label="Den"
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
                {(allSlots ? d.slots : d.slots.slice(0, 8)).map((s: any) => (
                  <li key={s.id} className="flex items-center gap-2 py-2">
                    <span className="flex-1 text-fg">{fmtDT(s.slot_at)}<span className="text-fg-3">{` · ${s.duration_min} min`}</span></span>
                    {s.status !== "open" ? <Chip tone="info">{s.status === "booked" ? "obsazeno" : "rezervováno"}</Chip>
                      : <button type="button" aria-label="Smazat termín" className="text-fg-3 hover:text-alert"
                          onClick={() => act(`s${s.id}`, () => api.slotRemove(s.id), "Termín smazán")}><Trash2 className="size-4" aria-hidden /></button>}
                  </li>
                ))}
              </ul>
            )}
            {!allSlots && (d.slots || []).length > 8 && <button type="button" className="mt-2 text-[12px] font-bold text-accent hover:underline" onClick={() => setAllSlots(true)}>{`Zobrazit všech ${d.slots.length}`}</button>}
          </Card>
        </div>
      </div>
      <ConclusionSheet booking={concl} onClose={() => setConcl(null)} onDone={() => { setConcl(null); reload() }} />
    </>
  )
}

// physio brief 2026-11-09 P0.5: an empty draft (left by merely opening the sheet before the fix)
// is not "rozepsaný"; an approved record says whether the summary went to the client.
function RecordChip({ c }: { c: any }) {
  if (c?.status === "approved") return c.shared_at ? <Chip tone="ok">shrnutí odesláno</Chip> : <Chip tone="watch">schváleno · shrnutí neodesláno</Chip>
  if (c && [c.summary, c.finding, c.transcript].some((t: any) => (t || "").trim())) return <Chip tone="watch">rozepsaný záznam</Chip>
  return <Chip tone="alert">bez záznamu</Chip>
}

function Visit({ b, reminder, onOpen, onConclusion, onSaved, openSlots, freeTimes }: { b: any; reminder: boolean; onOpen: () => void; onConclusion: () => void; onSaved: () => void; openSlots: any[]; freeTimes: any[] }) {
  const toast = useToast()
  const [menu, setMenu] = useState<"" | "move" | "cancel">("")
  const [to, setTo] = useState<string>("")
  const [why, setWhy] = useState("")
  const run = async (fn: () => Promise<any>, msg: string) => {
    try { await fn(); toast({ title: msg }); setMenu(""); onSaved() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
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
        {a.overall != null && <span className="text-fg-3">{`· skóre ${Math.round(shownScore(a.overall)!)}`}</span>}
        <span className="flex-1" />
        {new Date(b.slot_at).getTime() <= Date.now() &&
          <Button size="sm" variant="outline" icon={FileText} onClick={onConclusion}>Záznam</Button>}
        <details className="relative" data-testid="visit-menu">
          <summary aria-label="Další akce" className="cursor-pointer list-none rounded-lg px-2 py-1 text-fg-2 hover:bg-white/[.06]"><MoreHorizontal className="size-4" aria-hidden /></summary>
          <div className="absolute right-0 z-20 mt-1 grid w-40 rounded-xl border border-white/10 bg-panel p-1 text-[13px] shadow-lg">
            <button type="button" className="rounded-lg px-3 py-2 text-left hover:bg-white/[.06]" onClick={() => setMenu("move")}>Přesunout</button>
            <button type="button" className="rounded-lg px-3 py-2 text-left text-alert hover:bg-white/[.06]" onClick={() => setMenu("cancel")}>Zrušit</button>
          </div>
        </details>
      </div>
      {/* physio brief W5.6: move to an open slot or a computed free time, with a confirmation that says what the client gets */}
      {menu === "move" && (
        <div className="mt-2 flex flex-wrap gap-2">
          <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Nový termín" className="min-w-0 flex-1 rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]">
            <option value="">{openSlots.length || freeTimes.length ? "— vyberte volný čas —" : "Žádný volný čas — upravte pracovní dobu"}</option>
            {openSlots.map((s: any) => <option key={`s${s.id}`} value={`s:${s.id}`}>{fmtDT(s.slot_at)}</option>)}
            {freeTimes.filter((f: any) => !f.slot_id).slice(0, 40).map((f: any) => <option key={f.start} value={`t:${f.start}`}>{fmtDT(f.start)}</option>)}
          </select>
          <Button size="sm" disabled={!to} onClick={() => {
            const [k, v] = [to.slice(0, 1), to.slice(2)]
            if (!window.confirm(`Přesunout návštěvu na ${fmtDT(k === "s" ? openSlots.find((s: any) => String(s.id) === v)?.slot_at : v)}? Klient dostane zprávu.`)) return
            void run(() => api.bookingReschedule(b.id, k === "s" ? { slot_id: Number(v) } : { starts_at: v }), "Návštěva přesunuta — klient dostal zprávu")
          }}>Přesunout</Button>
          <Button size="sm" variant="outline" onClick={() => setMenu("")}>Zpět</Button>
        </div>
      )}
      {menu === "cancel" && (
        <div className="mt-2 grid gap-2">
          <input value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Důvod zrušení (klient ho uvidí)" aria-label="Důvod zrušení"
            className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
          <div className="flex gap-2">
            <Button size="sm" variant="danger" disabled={!why.trim()} onClick={() => run(() => api.bookingCancelPhysio(b.id, why), "Návštěva zrušena — klient dostal zprávu")}>Zrušit návštěvu</Button>
            <Button size="sm" variant="outline" onClick={() => setMenu("")}>Zpět</Button>
          </div>
        </div>
      )}
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
