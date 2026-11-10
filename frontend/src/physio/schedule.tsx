// Kalendář, the planning half (physio brief 2026-11-09 W5): the week at a glance, working hours that
// generate the free times runners book (previewed before saving), services, time off, a visit or a weekly
// series added by the physio (conflicts reported per date, never booked over) and the private calendar feed.
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"
import { CalendarPlus, ChevronLeft, ChevronRight, Link2, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, useToast } from "@/ui"
import { fmtD, fmtDT, plural } from "@/lib"
import { Empty, Loading, useLoad } from "@/physio/common"

const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
const iso = (d: Date) => d.toLocaleDateString("sv-SE")
const hm = (s: string) => new Date(s).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })
const monday = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(12, 0, 0, 0); return x }

// round 2 F14 (W5.6): a time grid — week by default, a day on demand, 30-minute rows, colours by status (never by
// risk), a click on an empty time adds a visit, an opening or a block, and a drag moves a visit after a confirmation
// that tells the client
const START_H = 7, END_H = 20, ROW = 22
const ROWS = (END_H - START_H) * 2
const STATUS_STYLE: Record<string, string> = {
  requested: "border border-dashed border-accent/70 bg-accent/[.06] text-fg",
  confirmed: "bg-accent/20 text-fg",
  completed: "bg-white/[.10] text-fg-2",
  no_show: "bg-white/[.05] text-fg-3 line-through",
}
const STATUS_CS: Record<string, string> = { requested: "žádost", confirmed: "potvrzeno", completed: "proběhla", no_show: "nedostavil(a) se" }
const mins = (s: string) => { const d = new Date(s); return d.getHours() * 60 + d.getMinutes() }
const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`
export const freeLabel = (n: number) => (n === 0 ? "plno" : `${n} ${plural(n, "volný", "volné", "volných")}`)

export function WeekView({ pid, version }: { pid: string; version: number }) {
  const nav = useNavigate()
  const toast = useToast()
  const [mode, setMode] = useState<"week" | "day">("week")
  const [start, setStart] = useState(() => monday(new Date()))
  const [dayIdx, setDayIdx] = useState(() => (new Date().getDay() + 6) % 7)
  const [ver, setVer] = useState(0)
  const [cell, setCell] = useState<{ day: string; m: number; x: number; y: number } | null>(null)
  const [drag, setDrag] = useState<any>(null)
  const end = useMemo(() => { const e = new Date(start); e.setDate(e.getDate() + 6); return e }, [start])
  const { d, err } = useLoad<any>(() => api.physioCalendar(pid, iso(start), iso(end)), [pid, start, version, ver])
  const shift = (n: number) => { const x = new Date(start); x.setDate(x.getDate() + 7 * n); setStart(x) }
  const all = Array.from({ length: 7 }, (_, i) => { const x = new Date(start); x.setDate(x.getDate() + i); return iso(x) })
  const days = mode === "week" ? all : [all[dayIdx]]
  const day = (s: string) => new Date(s).toLocaleDateString("sv-SE")
  const at = (dd: string, m: number) => new Date(`${dd}T${hhmm(m)}:00`)
  const refresh = () => setVer((v) => v + 1)
  const add = async (kind: "visit" | "slot" | "block") => {
    if (!cell) return
    const when = at(cell.day, cell.m)
    setCell(null)
    if (kind === "visit") { window.dispatchEvent(new CustomEvent("doslap:add-visit", { detail: { date: cell.day, time: hhmm(cell.m) } })); return }
    try {
      if (kind === "slot") await api.slotAdd(pid, when.toISOString(), 30)
      else await api.timeOffAdd({ starts_at: when.toISOString(), ends_at: new Date(when.getTime() + 30 * 60000).toISOString(), reason: "" })
      toast({ title: kind === "slot" ? "Volný termín přidán" : "Čas zablokován" }); refresh()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const drop = async (dd: string, m: number) => {
    const b = drag
    setDrag(null)
    if (!b) return
    const when = at(dd, m)
    if (!window.confirm(`Přesunout návštěvu ${b.name} na ${fmtDT(when.toISOString())}? Klient dostane zprávu.`)) return
    try {
      const r = await api.bookingReschedule(b.id, { starts_at: when.toISOString() })
      toast({ title: r.outside_hours ? "Přesunuto mimo pracovní dobu — klient dostal zprávu" : "Návštěva přesunuta — klient dostal zprávu" })
      refresh()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const now = new Date()
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-xl">{mode === "week" ? `Týden ${fmtD(iso(start))} – ${fmtD(iso(end))}` : `${WD[dayIdx]} ${fmtD(all[dayIdx])}`}</h2>
        <span className="flex flex-wrap items-center gap-1">
          <Segmented size="sm" ariaLabel="Zobrazení" value={mode} onChange={setMode} options={[["week", "Týden"], ["day", "Den"]] as const} />
          <Button size="sm" variant="outline" icon={ChevronLeft} onClick={() => (mode === "day" && dayIdx > 0 ? setDayIdx(dayIdx - 1) : (shift(-1), mode === "day" && setDayIdx(6)))} aria-label="Předchozí">{""}</Button>
          <Button size="sm" variant="outline" onClick={() => { setStart(monday(new Date())); setDayIdx((new Date().getDay() + 6) % 7) }}>Dnes</Button>
          <Button size="sm" variant="outline" icon={ChevronRight} onClick={() => (mode === "day" && dayIdx < 6 ? setDayIdx(dayIdx + 1) : (shift(1), mode === "day" && setDayIdx(0)))} aria-label="Další">{""}</Button>
        </span>
      </div>
      <p className="mt-1 flex flex-wrap gap-3 text-[11.5px] text-fg-3" aria-label="Legenda">
        {Object.entries(STATUS_CS).map(([k, l]) => <span key={k} className="inline-flex items-center gap-1"><i className={`inline-block h-3 w-4 rounded-sm ${STATUS_STYLE[k]}`} />{l}</span>)}
        <span className="inline-flex items-center gap-1"><i className="inline-block h-3 w-4 rounded-sm bg-white/[.04]" />pracovní doba</span>
      </p>
      {!d ? <Loading err={err} /> : (
        <div className="mt-3 overflow-x-auto" data-testid="week">
          <div className="grid min-w-[640px]" style={{ gridTemplateColumns: `44px repeat(${days.length}, minmax(0, 1fr))` }}>
            <div />
            {days.map((dd) => {
              const i = all.indexOf(dd)
              const free = d.free.filter((f: any) => day(f.start) === dd).length
              const rules = d.rules.filter((r: any) => r.weekday === i)
              return (
                <button key={dd} type="button" onClick={() => { setDayIdx(i); setMode("day") }}
                  className={`border-b px-1 pb-1 text-left text-[11.5px] ${dd === iso(now) ? "border-accent text-accent" : "border-white/[.1] text-fg-2"}`}>
                  <b className="uppercase tracking-[.05em]">{`${WD[i]} ${fmtD(dd)}`}</b>
                  <span className="block text-fg-3" data-testid="day-free">{dd < iso(now) ? "\u00a0" : rules.length || free ? freeLabel(free) : "nepracuji"}</span>
                </button>
              )
            })}
            <div className="relative" style={{ height: ROWS * ROW }}>
              {Array.from({ length: END_H - START_H }, (_, h) => <span key={h} className="absolute right-1 text-[10.5px] tabular-nums text-fg-3" style={{ top: h * 2 * ROW - 6 }}>{`${START_H + h}:00`}</span>)}
            </div>
            {days.map((dd) => {
              const i = all.indexOf(dd)
              const rules = d.rules.filter((r: any) => r.weekday === i)
              const offs = d.time_off.filter((t: any) => day(t.starts_at) <= dd && dd <= day(t.ends_at))
              const bs = d.bookings.filter((b: any) => day(b.slot_at) === dd && b.status !== "cancelled")
                .sort((x: any, y: any) => x.slot_at.localeCompare(y.slot_at))
              // overlapping visits sit side by side: each takes the first free lane
              const lanes: number[] = [], lane: Record<number, number> = {}
              for (const b of bs) {
                const a0 = mins(b.slot_at), a1 = a0 + (b.duration_min || 45)
                let k = lanes.findIndex((endM) => endM <= a0)
                if (k < 0) { k = lanes.length; lanes.push(a1) } else lanes[k] = a1
                lane[b.id] = k
              }
              const nl = Math.max(1, lanes.length)
              return (
                <div key={dd} className="relative border-l border-white/[.08]" style={{ height: ROWS * ROW }} data-testid="day-column">
                  {rules.map((r: any, k: number) => {
                    const a = Number(r.start.slice(0, 2)) * 60 + Number(r.start.slice(3, 5)), b = Number(r.end.slice(0, 2)) * 60 + Number(r.end.slice(3, 5))
                    return <div key={k} className="absolute inset-x-0 bg-white/[.04]" style={{ top: ((a - START_H * 60) / 30) * ROW, height: ((b - a) / 30) * ROW }} />
                  })}
                  {offs.map((t: any) => {
                    const a = day(t.starts_at) < dd ? START_H * 60 : mins(t.starts_at), b = day(t.ends_at) > dd ? END_H * 60 : mins(t.ends_at)
                    return <div key={t.id} className="absolute inset-x-0 bg-[repeating-linear-gradient(135deg,rgb(128_128_128/.18)_0_4px,transparent_4px_8px)]" title="blokováno"
                      style={{ top: ((Math.max(a, START_H * 60) - START_H * 60) / 30) * ROW, height: ((Math.min(b, END_H * 60) - Math.max(a, START_H * 60)) / 30) * ROW }} />
                  })}
                  {Array.from({ length: ROWS }, (_, r) => {
                    const m = START_H * 60 + r * 30
                    return <button key={r} type="button" aria-label={`${dd} ${hhmm(m)}`} data-testid="grid-cell"
                      className={`absolute inset-x-0 border-t ${r % 2 ? "border-white/[.03]" : "border-white/[.07]"} hover:bg-accent/[.06]`}
                      style={{ top: r * ROW, height: ROW }}
                      onClick={(e) => setCell({ day: dd, m, x: e.clientX, y: e.clientY })}
                      onDragOver={(e) => drag && e.preventDefault()} onDrop={() => drop(dd, m)} />
                  })}
                  {bs.map((b: any) => {
                    const top = ((mins(b.slot_at) - START_H * 60) / 30) * ROW
                    const movable = ["requested", "confirmed"].includes(b.status) && new Date(b.slot_at) > now
                    return (
                      <button key={b.id} type="button" draggable={movable} onDragStart={() => setDrag(b)} onDragEnd={() => setDrag(null)}
                        onClick={() => nav(`/physio/client/${b.runner_id}`)} data-testid="grid-visit"
                        className={`absolute overflow-hidden rounded-md px-1.5 py-0.5 text-left text-[11.5px] leading-tight ${STATUS_STYLE[b.status] || STATUS_STYLE.confirmed} ${movable ? "cursor-grab" : ""}`}
                        style={{ top: Math.max(0, top), height: Math.max(ROW - 2, ((b.duration_min || 45) / 30) * ROW - 2),
                          left: `calc(${(lane[b.id] / nl) * 100}% + 2px)`, width: `calc(${100 / nl}% - 4px)` }}
                        title={`${b.name} · ${STATUS_CS[b.status] || b.status}`}>
                        <b className="tabular-nums">{new Date(b.slot_at).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}</b>{` ${b.name}`}
                        <span className="block truncate opacity-80">{b.service || STATUS_CS[b.status]}</span>
                      </button>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {cell && (
        <CellMenu cell={cell} onClose={() => setCell(null)} onPick={add} />
      )}
    </Card>
  )
}

function CellMenu({ cell, onClose, onPick }: { cell: { day: string; m: number; x: number; y: number }; onClose: () => void; onPick: (k: "visit" | "slot" | "block") => void }) {
  const box = useMemo(() => ({ current: null as HTMLDivElement | null }), [])
  useEffect(() => {
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) onClose() }
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose() } }
    const t = setTimeout(() => document.addEventListener("mousedown", down), 0)
    window.addEventListener("keydown", key, true)
    return () => { clearTimeout(t); document.removeEventListener("mousedown", down); window.removeEventListener("keydown", key, true) }
  }, [box, onClose])
  return (
    <div ref={(el) => { box.current = el }} role="menu" data-testid="cell-menu" className="fixed z-50 grid w-48 rounded-xl border border-white/10 bg-panel p-1 text-[13px] shadow-lg"
      style={{ left: Math.min(cell.x, window.innerWidth - 200), top: Math.min(cell.y, window.innerHeight - 140) }}>
      <p className="px-3 py-1 text-[11.5px] text-fg-3">{`${fmtD(cell.day)} ${hhmm(cell.m)}`}</p>
      <button type="button" role="menuitem" className="rounded-lg px-3 py-2 text-left hover:bg-white/[.06]" onClick={() => onPick("visit")}>Přidat návštěvu</button>
      <button type="button" role="menuitem" className="rounded-lg px-3 py-2 text-left hover:bg-white/[.06]" onClick={() => onPick("slot")}>Přidat volný termín</button>
      <button type="button" role="menuitem" className="rounded-lg px-3 py-2 text-left hover:bg-white/[.06]" onClick={() => onPick("block")}>Blokovat čas</button>
    </div>
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
  // round 2 F14: a click on an empty time in the grid fills the day and time
  useEffect(() => {
    const h = (e: Event) => {
      const x = (e as CustomEvent).detail
      setF((cur: any) => ({ ...cur, date: x.date, time: x.time }))
      document.getElementById("add-visit")?.scrollIntoView({ behavior: "smooth" })
    }
    window.addEventListener("doslap:add-visit", h)
    return () => window.removeEventListener("doslap:add-visit", h)
  }, [])
  const submit = async () => {
    try {
      const r = await api.visitAdd({ runner_id: f.runner_id, starts_at: new Date(`${f.date}T${f.time}:00`).toISOString(),
        service_id: f.service_id ? Number(f.service_id) : null, weeks: Number(f.weeks), reason: f.reason || null })
      setRes(r)
      toast({ title: r.created.length ? `Naplánováno: ${r.created.length}` : "Nic se nenaplánovalo" })
      // round 2 F14.2: ready for the next one — client, date and reason cleared, the service kept
      if (r.created.length) setF((cur: any) => ({ ...cur, runner_id: "", date: "", reason: "" }))
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
