// Kalendář, the planning half (physio brief 2026-11-09 W5): the week at a glance, working hours that
// generate the free times runners book (previewed before saving), services, time off, a visit or a weekly
// series added by the physio (conflicts reported per date, never booked over) and the private calendar feed.
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"
import { CalendarPlus, ChevronLeft, ChevronRight, Link2, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { Empty, Loading, useLoad } from "@/physio/common"

const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
const iso = (d: Date) => d.toLocaleDateString("sv-SE")
const hm = (s: string) => new Date(s).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })
const monday = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(12, 0, 0, 0); return x }

export function WeekView({ pid, version }: { pid: string; version: number }) {
  const nav = useNavigate()
  const [start, setStart] = useState(() => monday(new Date()))
  const end = useMemo(() => { const e = new Date(start); e.setDate(e.getDate() + 6); return e }, [start])
  const { d, err } = useLoad<any>(() => api.physioCalendar(pid, iso(start), iso(end)), [pid, start, version])
  const shift = (w: number) => { const x = new Date(start); x.setDate(x.getDate() + 7 * w); setStart(x) }
  const days = Array.from({ length: 7 }, (_, i) => { const x = new Date(start); x.setDate(x.getDate() + i); return iso(x) })
  const day = (s: string) => new Date(s).toLocaleDateString("sv-SE")
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-xl">{`Týden ${fmtD(iso(start))} – ${fmtD(iso(end))}`}</h2>
        <span className="flex gap-1">
          <Button size="sm" variant="outline" icon={ChevronLeft} onClick={() => shift(-1)} aria-label="Předchozí týden">{""}</Button>
          <Button size="sm" variant="outline" onClick={() => setStart(monday(new Date()))}>Dnes</Button>
          <Button size="sm" variant="outline" icon={ChevronRight} onClick={() => shift(1)} aria-label="Další týden">{""}</Button>
        </span>
      </div>
      {!d ? <Loading err={err} /> : (
        <div className="mt-3 grid gap-2 overflow-x-auto sm:grid-cols-7" data-testid="week">
          {days.map((dd, i) => {
            const bs = d.bookings.filter((b: any) => day(b.slot_at) === dd && !["cancelled"].includes(b.status)).sort((a: any, b: any) => a.slot_at.localeCompare(b.slot_at))
            const free = d.free.filter((f: any) => day(f.start) === dd).length
            const off = d.time_off.some((t: any) => day(t.starts_at) <= dd && dd <= day(t.ends_at))
            return (
              <section key={dd} className={`min-h-24 rounded-lg border p-2 ${dd === iso(new Date()) ? "border-accent" : "border-white/[.1]"}`}>
                <h3 className="text-[11.5px] font-bold uppercase tracking-[.05em] text-fg-3">{`${WD[i]} ${fmtD(dd)}`}</h3>
                {off && <Chip>volno</Chip>}
                <ul className="mt-1 grid gap-1">
                  {bs.map((b: any) => (
                    <li key={b.id}>
                      <button type="button" onClick={() => nav(`/physio/client/${b.runner_id}`)}
                        className={`w-full rounded-md px-1.5 py-1 text-left text-[12px] ${b.status === "requested" ? "ph-risk-med" : "bg-accent/12"}`}>
                        <b className="tabular-nums">{hm(b.slot_at)}</b>{` ${b.name}`}
                        <span className="block text-[11px] opacity-80">{b.service || (b.status === "requested" ? "žádost" : "návštěva")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                {free > 0 && <p className="mt-1 text-[11px] text-fg-3">{`${free} volných`}</p>}
              </section>
            )
          })}
        </div>
      )}
    </Card>
  )
}

export function AddVisit({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const [sp] = useSearchParams()
  const clients = useLoad<any>(() => api.physioClients(), [])
  const services = useLoad<any>(() => api.services(), [])
  const [f, setF] = useState<any>({ runner_id: sp.get("client") || "", date: "", time: "09:00", service_id: "", weeks: 1, reason: "" })
  const [res, setRes] = useState<any>(null)
  useEffect(() => { if (sp.get("client")) document.getElementById("add-visit")?.scrollIntoView({ behavior: "smooth" }) }, [sp])
  const submit = async () => {
    try {
      const r = await api.visitAdd({ runner_id: f.runner_id, starts_at: new Date(`${f.date}T${f.time}:00`).toISOString(),
        service_id: f.service_id ? Number(f.service_id) : null, weeks: Number(f.weeks), reason: f.reason || null })
      setRes(r)
      toast({ title: r.created.length ? `Naplánováno: ${r.created.length}` : "Nic se nenaplánovalo" })
      onDone()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <Card>
      <h2 id="add-visit" className="font-serif text-xl">Přidat návštěvu</h2>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="text-[12px] font-bold text-fg-2 sm:col-span-2">Klient<select className={inp} value={f.runner_id} onChange={(e) => setF({ ...f, runner_id: e.target.value })}>
          <option value="">Vyberte…</option>{(clients.d?.items || []).map((c: any) => <option key={c.runnerId} value={c.runnerId}>{c.name}</option>)}</select></label>
        <label className="text-[12px] font-bold text-fg-2">Den<input type="date" className={inp} value={f.date} min={iso(new Date())} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Čas<input type="time" step={900} className={inp} value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Služba<select className={inp} value={f.service_id} onChange={(e) => setF({ ...f, service_id: e.target.value })}>
          <option value="">Návštěva (45 min)</option>{(services.d?.items || []).filter((s: any) => s.active).map((s: any) => <option key={s.id} value={s.id}>{`${s.name_cs} (${s.duration_minutes} min)`}</option>)}</select></label>
        <label className="text-[12px] font-bold text-fg-2">Opakovat týdně<select className={inp} value={f.weeks} onChange={(e) => setF({ ...f, weeks: e.target.value })}>
          {[1, 2, 3, 4, 6, 8, 10, 12].map((n) => <option key={n} value={n}>{n === 1 ? "jen jednou" : `${n}×`}</option>)}</select></label>
        <label className="text-[12px] font-bold text-fg-2 sm:col-span-2">Důvod (nepovinné)<input className={inp} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></label>
      </div>
      <Button className="mt-3" icon={CalendarPlus} disabled={!f.runner_id || !f.date} onClick={submit} data-testid="visit-add">Naplánovat</Button>
      {res?.conflicts?.length > 0 && (
        <ul className="mt-2 grid gap-1 text-[12.5px] text-watch" data-testid="visit-conflicts">
          {res.conflicts.map((c: any) => <li key={c.at}>{`${fmtDT(c.at)}: ${c.why}`}</li>)}
        </ul>
      )}
    </Card>
  )
}

export function WorkingHours({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.availability(), [])
  const [rules, setRules] = useState<any[] | null>(null)
  useEffect(() => { if (d && rules == null) setRules(d.rules.map((r: any) => ({ weekday: r.weekday, start_local: r.start_local, end_local: r.end_local, slot_minutes: r.slot_minutes }))) }, [d, rules])
  if (!d || !rules) return <Card><Loading err={null} /></Card>
  const set = (i: number, k: string, v: any) => setRules(rules.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  // preview without saving: how many free times the edited rules give over the next 14 days
  const preview = (() => {
    let n = 0
    const t = new Date()
    for (let k = 0; k < 14; k++) {
      const x = new Date(t); x.setDate(t.getDate() + k)
      for (const r of rules) {
        if (r.weekday !== (x.getDay() + 6) % 7) continue
        const [h0, m0] = r.start_local.split(":").map(Number), [h1, m1] = r.end_local.split(":").map(Number)
        n += Math.max(0, Math.floor(((h1 * 60 + m1) - (h0 * 60 + m0)) / (Number(r.slot_minutes) || 45)))
      }
    }
    return n
  })()
  return (
    <Card>
      <h2 className="font-serif text-xl">Pracovní doba</h2>
      <p className="mt-1 text-[12px] text-fg-3">Z pracovní doby se počítají volné časy, ze kterých si klienti vybírají. Obsazené a volno se odečtou.</p>
      <ul className="mt-2 grid gap-1.5" data-testid="rules">
        {rules.map((r, i) => (
          <li key={i} className="flex flex-wrap items-center gap-1.5 text-[13px]">
            <select className="rounded-md border border-white/15 bg-panel px-1.5 py-1" value={r.weekday} onChange={(e) => set(i, "weekday", Number(e.target.value))} aria-label="Den">
              {WD.map((w, k) => <option key={k} value={k}>{w}</option>)}</select>
            <input type="time" step={900} className="rounded-md border border-white/15 bg-panel px-1.5 py-1" value={r.start_local} onChange={(e) => set(i, "start_local", e.target.value)} aria-label="Od" />
            <span>–</span>
            <input type="time" step={900} className="rounded-md border border-white/15 bg-panel px-1.5 py-1" value={r.end_local} onChange={(e) => set(i, "end_local", e.target.value)} aria-label="Do" />
            <select className="rounded-md border border-white/15 bg-panel px-1.5 py-1" value={r.slot_minutes} onChange={(e) => set(i, "slot_minutes", Number(e.target.value))} aria-label="Délka termínu">
              {[30, 45, 60, 90].map((m) => <option key={m} value={m}>{`${m} min`}</option>)}</select>
            <button type="button" aria-label="Odebrat" className="text-fg-3 hover:text-alert" onClick={() => setRules(rules.filter((_, j) => j !== i))}><Trash2 className="size-4" aria-hidden /></button>
          </li>
        ))}
      </ul>
      <button type="button" className="mt-2 text-[12px] font-bold text-accent hover:underline" onClick={() => setRules([...rules, { weekday: 0, start_local: "08:00", end_local: "12:00", slot_minutes: 45 }])}>Přidat blok</button>
      <p className="mt-2 text-[12.5px] text-fg-2" data-testid="rules-preview">{`Náhled: ${preview} termínů v příštích 14 dnech (před odečtením obsazených).`}</p>
      <Button className="mt-2" size="sm" onClick={async () => {
        try { await api.availabilitySave(rules); toast({ title: "Pracovní doba uložena" }); reload(); onDone() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
      }}>Uložit pracovní dobu</Button>
      <TimeOff items={d.time_off} onChange={() => { reload(); onDone() }} />
    </Card>
  )
}

function TimeOff({ items, onChange }: { items: any[]; onChange: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ from: "", to: "", reason: "" })
  return (
    <div className="mt-4 border-t border-white/[.08] pt-3">
      <h3 className="font-bold">Volno</h3>
      {items.length > 0 && <ul className="mt-1 grid gap-1 text-[12.5px]">{items.map((t: any) => (
        <li key={t.id} className="flex items-center gap-2">{`${fmtD(t.starts_at)} – ${fmtD(t.ends_at)}`}{t.reason ? ` · ${t.reason}` : ""}
          <button type="button" aria-label="Smazat volno" className="text-fg-3 hover:text-alert" onClick={async () => { await api.timeOffRemove(t.id); onChange() }}><Trash2 className="size-3.5" aria-hidden /></button></li>))}</ul>}
      <div className="mt-2 grid gap-2 sm:grid-cols-[auto_auto_1fr_auto]">
        <label className="text-[12px] font-bold text-fg-2">Od<input type="date" className={inp} value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Do<input type="date" className={inp} value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Důvod<input className={inp} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="dovolená, školení…" /></label>
        <Button size="sm" className="self-end" disabled={!f.from || !f.to} onClick={async () => {
          try {
            await api.timeOffAdd({ starts_at: new Date(`${f.from}T00:00:00`).toISOString(), ends_at: new Date(`${f.to}T23:59:00`).toISOString(), reason: f.reason, all_day: true })
            setF({ from: "", to: "", reason: "" }); onChange()
          } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Přidat</Button>
      </div>
    </div>
  )
}

export function Services() {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.services(), [])
  const [f, setF] = useState({ name_cs: "", duration_minutes: 45, price_czk: "" as any, buffer_minutes: 0 })
  return (
    <Card>
      <h2 className="font-serif text-xl">Služby</h2>
      {!d ? <Loading err={null} /> : d.items.length === 0 ? <Empty>Zatím žádné služby — klienti uvidí obecnou návštěvu.</Empty> : (
        <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="services">
          {d.items.map((s: any) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <b className="min-w-0 flex-1">{s.name_cs}</b>
              <span className="text-fg-2">{`${s.duration_minutes} min${s.price_czk != null ? ` · ${s.price_czk} Kč` : ""}${s.buffer_minutes ? ` · +${s.buffer_minutes} min pauza` : ""}`}</span>
              <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={async () => {
                await api.serviceEdit(s.id, { name_cs: s.name_cs, active: !s.active }); reload()
              }}>{s.active ? "Skrýt" : "Zobrazit"}</button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
        <label className="text-[12px] font-bold text-fg-2">Název<input className={inp} value={f.name_cs} onChange={(e) => setF({ ...f, name_cs: e.target.value })} /></label>
        <label className="w-20 text-[12px] font-bold text-fg-2">Minut<input type="number" min={10} max={240} className={inp} value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: Number(e.target.value) })} /></label>
        <label className="w-24 text-[12px] font-bold text-fg-2">Cena Kč<input type="number" min={0} className={inp} value={f.price_czk} onChange={(e) => setF({ ...f, price_czk: e.target.value })} /></label>
        <Button size="sm" className="self-end" disabled={!f.name_cs.trim()} onClick={async () => {
          try { await api.serviceAdd({ ...f, price_czk: f.price_czk === "" ? null : Number(f.price_czk) }); setF({ name_cs: "", duration_minutes: 45, price_czk: "", buffer_minutes: 0 }); reload() }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Přidat</Button>
      </div>
    </Card>
  )
}

export function IcsLink() {
  const toast = useToast()
  const [url, setUrl] = useState<string | null>(null)
  return (
    <Card>
      <h2 className="flex items-center gap-2 font-serif text-xl"><Link2 className="size-4" aria-hidden />Kalendář v telefonu</h2>
      <p className="mt-1 text-[12px] text-fg-3">Soukromý odkaz pro Google, Apple nebo Outlook kalendář. Obsahuje jen iniciály klienta a službu. Nový odkaz zruší ten starý.</p>
      {url ? <input readOnly className={inp} value={url} onFocus={(e) => e.target.select()} aria-label="Odkaz na kalendář" />
        : <Button className="mt-2" size="sm" variant="outline" onClick={async () => {
          try { const r = await api.physioIcs(); setUrl(r.url); toast({ title: "Odkaz je připravený" }) } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Vytvořit odkaz</Button>}
    </Card>
  )
}
