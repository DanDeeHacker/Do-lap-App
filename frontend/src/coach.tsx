// Plán od trenéra (owner request 2026-10-12): the coach decides what is run, Došlap keeps
// to what the body takes. Every planned session gets a verdict — Sedí / Sedí s úpravou /
// Dnes raději ne — against today's safety limits and the engine's rules (backend
// metrics/coach_plan.py), with the smallest change that fits, a day with room, and a
// message for the coach. Visual first: bars of plan vs. today's safe maximum, chips for
// the changes, a week strip of verdict dots, the 2×2 of keeping to the plan and the limits.
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router"
import {
  Activity, ArrowRight, Bike, CalendarDays, Camera, Check, CircleCheck, CircleMinus, ClipboardPaste, Copy, Dumbbell,
  Flag, Footprints, Leaf, Link2, Mountain, Pencil, Plus, RefreshCw, Route, Send, ShieldCheck, SlidersHorizontal, Sofa,
  Trash2, TriangleAlert, Unplug, Users, Waves, Zap, type LucideIcon,
} from "lucide-react"
import { api } from "@/api"
import { Button, Chip, InfoDot, Label, Segmented, Sheet, Switch, useToast } from "@/ui"
import { C } from "@/tokens"
import { fmtD } from "@/lib"
import { getLang } from "@/i18n/lang"
import { translate } from "@/i18n/translator"
import { num } from "@/outlook"

export const PLAN_EVENT = "doslap:plan"
const ECC = 1.16
const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
const WD_LONG = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]

export const KIND: Record<string, { label: string; Icon: LucideIcon; run?: boolean; hard?: boolean }> = {
  easy: { label: "Lehký běh", Icon: Footprints, run: true },
  recovery: { label: "Regenerační běh", Icon: Leaf, run: true },
  long: { label: "Dlouhý běh", Icon: Route, run: true },
  quality: { label: "Intervaly / tempo", Icon: Zap, run: true, hard: true },
  hills: { label: "Kopce", Icon: Mountain, run: true, hard: true },
  race: { label: "Závod", Icon: Flag, run: true, hard: true },
  ride: { label: "Kolo", Icon: Bike },
  swim: { label: "Plavání", Icon: Waves },
  strength: { label: "Posilování", Icon: Dumbbell },
  other: { label: "Jiný trénink", Icon: Activity },
  rest: { label: "Volno", Icon: Sofa },
}
export const KIND_ORDER = ["easy", "recovery", "long", "quality", "hills", "race", "ride", "swim", "strength", "other", "rest"]

export const VERDICT: Record<string, { label: string; col: string; Icon: LucideIcon }> = {
  ok: { label: "Sedí", col: C.ok, Icon: CircleCheck },
  mod: { label: "Sedí s úpravou", col: C.watch, Icon: SlidersHorizontal },
  no: { label: "Dnes raději ne", col: C.alert, Icon: CircleMinus },
  rest: { label: "Volno", col: C.fg3, Icon: Sofa },
}
const STATUS: Record<string, { label: string; col: string }> = {
  done: { label: "splněno", col: C.ok }, more: { label: "víc než plán", col: C.watch }, partial: { label: "částečně", col: C.watch },
  missed: { label: "vynecháno", col: C.fg3 }, planned: { label: "v plánu", col: C.fg2 }, rest: { label: "volno", col: C.fg3 },
}
const CH: [string, string, string, number][] = [
  ["volume", "Objem", "km", 1], ["intensity", "Tvrdé minuty (Z4+)", "min", 0], ["descent", "Klesání", "m", 0],
  ["ascent", "Stoupání", "m", 0], ["systemic", "Celková zátěž", "b.", 0],
]
const BY: Record<string, string> = { "7d": "nevstřebaná zátěž", run: "strop jednoho běhu" }

const disp = (c: string, v: number | null | undefined) => (v == null ? null : c === "descent" ? v / ECC : v)
const dayName = (iso: string) => WD_LONG[(new Date(iso + "T12:00:00").getDay() + 6) % 7]
const dayShort = (iso: string) => WD[(new Date(iso + "T12:00:00").getDay() + 6) % 7]
const sizeOf = (s: any) => KIND[s.kind]?.run ? (s.km != null ? `${num(s.km)} km` : s.min ? `${num(s.min, 0)} min` : "") : s.min ? `${num(s.min, 0)} min` : ""

function copyText(text: string, toast: (t: { title: string; msg?: string }) => void) {
  const t = getLang() === "en" ? translate(text) : text
  navigator.clipboard?.writeText(t).then(() => toast({ title: "Zpráva zkopírována", msg: "Vložte ji trenérovi do chatu nebo e-mailu." }),
    () => toast({ title: "Zprávu se nepodařilo zkopírovat" }))
}

/* ------------------------------------------------------------------ state */
export function usePlan(rid?: string | null) {
  const [st, setSt] = useState<any | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const toast = useToast()
  const load = () => rid ? api.plan(rid).then((d) => { setSt(d); setErr(null) }).catch((e) => setErr(e?.message || "Plán se nepodařilo načíst")) : Promise.resolve()
  useEffect(() => {
    load()
    const on = () => load()
    window.addEventListener(PLAN_EVENT, on)
    return () => window.removeEventListener(PLAN_EVENT, on)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid])
  const act = async (fn: () => Promise<any>, ok?: string) => {
    try {
      const d = await fn()
      if (d && typeof d === "object" && "on" in d) setSt(d)
      window.dispatchEvent(new CustomEvent(PLAN_EVENT, { detail: "self" }))
      if (ok) toast({ title: ok })
      return d
    } catch (e: any) {
      toast({ title: e?.message || "Změna se nepodařila" })
      throw e
    }
  }
  return { st, err, load, act, setSt }
}

/* ------------------------------------------------------------------ small pieces */
export function VerdictBadge({ v, small = false, prelim = false }: { v?: string | null; small?: boolean; prelim?: boolean }) {
  const m = v ? VERDICT[v] : null
  if (!m) return null
  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-bold leading-none ${small ? "px-2 py-1 text-[10.5px]" : "px-2.5 py-1.5 text-[12px]"}`}
      style={{ background: `${m.col}1f`, color: m.col }} data-testid="verdict-badge">
      <m.Icon className={small ? "size-3" : "size-3.5"} aria-hidden />{m.label}{prelim && v !== "rest" ? <span className="font-semibold opacity-70">{" · předběžně"}</span> : null}
    </span>
  )
}

function KindTile({ kind, size = "md" }: { kind: string; size?: "sm" | "md" }) {
  const K = KIND[kind] || KIND.other
  return (
    <span className={`grid shrink-0 place-items-center rounded-[12px] bg-white/[.06] ${size === "sm" ? "size-8" : "size-10"}`}>
      <K.Icon className={`${size === "sm" ? "size-4" : "size-5"} ${K.hard ? "text-watch" : "text-accent"}`} aria-hidden />
    </span>
  )
}

// plan vs today's safe maximum, one bar per channel the session loads
function ChannelBars({ s }: { s: any }) {
  const rows = CH.filter(([c]) => (s.load?.[c] || 0) > 0 && s.room?.[c] && (s.room[c].day != null || (KIND[s.kind]?.run && s.room[c].run != null)))
  if (!rows.length) return null
  return (
    <div className="mt-3 grid gap-2.5" data-testid="coach-bars">
      {rows.map(([c, label, unit, d]) => {
        const r = s.room[c]
        const run = KIND[s.kind]?.run && c !== "systemic"
        const lims = [r.day, run ? r.run : null].filter((x: any) => x != null) as number[]
        const mx = disp(c, Math.min(...lims))!
        const by = r.day != null && (!run || r.run == null || r.day <= r.run) ? "7d" : "run"
        const v = disp(c, s.load[c])!
        const over = v > mx * 1.05 + (c === "volume" ? 0.3 : c === "intensity" ? 2 : 5)
        const scale = Math.max(v, mx, 0.1) * 1.08
        return (
          <div key={c}>
            <div className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="font-bold text-fg-soft">{label}</span>
              <span className="tabular-nums text-fg-3"><b className={over ? "text-watch" : "text-fg"}>{num(v, d)}</b>{" / max "}<span>{num(mx, d)}</span>{` ${unit}`}</span>
            </div>
            <div className="relative mt-1 h-2.5 rounded-full bg-white/[.07]">
              <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(Math.min(v, mx) / scale) * 100}%`, background: C.ok }} />
              {over && <i className="absolute inset-y-0 rounded-r-full" style={{ left: `${(mx / scale) * 100}%`, width: `${((v - mx) / scale) * 100}%`, background: `repeating-linear-gradient(135deg, ${C.watch} 0 3px, ${C.watch}55 3px 6px)` }} />}
              <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg/85" style={{ left: `calc(${(mx / scale) * 100}% - 1px)` }} title="dnešní bezpečné maximum" />
            </div>
            {over && <p className="mt-0.5 text-[11px] leading-4 text-fg-3">{`o ${num(v - mx, d)} ${unit} víc · omezuje ${BY[by]}`}</p>}
          </div>
        )
      })}
    </div>
  )
}

function changeChip(c: any): ReactNode {
  switch (c.k) {
    case "km": return <><span className="line-through opacity-60">{num(c.from)}</span><ArrowRight className="size-3" aria-hidden /><b>{num(c.to)}</b><span>km</span></>
    case "z4": return <><span>Z4+</span><span className="line-through opacity-60">{num(c.from, 0)}</span><ArrowRight className="size-3" aria-hidden /><b>{num(c.to, 0)}</b><span>min</span></>
    case "easy": return <span>bez tvrdé části</span>
    case "desc": return <><span>klesání do</span><b>{num(c.to, 0)}</b><span>m</span></>
    case "asc": return <><span>stoupání do</span><b>{num(c.to, 0)}</b><span>m</span></>
    case "min": return <><span className="line-through opacity-60">{num(c.from, 0)}</span><ArrowRight className="size-3" aria-hidden /><b>{num(c.to, 0)}</b><span>min</span></>
    case "flat": return <span>po rovině</span>
    default: return null
  }
}

export function FitChips({ s, compact = false }: { s: any; compact?: boolean }) {
  const ch: any[] = s.fit?.changes || []
  const fits = s.fit?.fits !== false
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="fit-chips">
      {fits && ch.map((c, i) => (
        <span key={i} className="inline-flex items-center gap-1 rounded-full bg-watch/15 px-2.5 py-1 text-[12px] font-semibold text-watch-soft tabular-nums">{changeChip(c)}</span>
      ))}
      {!fits && <span className="inline-flex items-center gap-1 rounded-full bg-alert/15 px-2.5 py-1 text-[12px] font-semibold text-alert-soft">dnes se nevejde</span>}
      {s.move && (
        <span className="inline-flex items-center gap-1 rounded-full border border-white/15 px-2.5 py-1 text-[12px] font-semibold text-fg-soft" data-testid="move-chip">
          <CalendarDays className="size-3.5" aria-hidden />
          {s.move.swap ? <><span>{fits && ch.length ? "nebo prohodit s:" : "prohodit s:"}</span><b>{dayName(s.move.date)}</b></> : <><span>{fits && ch.length ? "nebo přesunout na:" : "přesunout na:"}</span><b>{dayName(s.move.date)}</b></>}
        </span>
      )}
      {!compact && null}
    </div>
  )
}

/* ------------------------------------------------------------------ today */
export function CoachToday({ st, rid, onEdit, onAdd, onImport }: { st: any; rid: string; onEdit: (s: any, date: string) => void; onAdd: (date: string) => void; onImport: () => void }) {
  const toast = useToast()
  const ev = st.eval
  const day = ev?.days?.find((d: any) => d.today)
  const sess: any[] = (day?.sessions || [])
  const msg = ev?.message
  const weekHas = ev?.week?.has
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="coach-today">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>{st.name ? `Dnes v plánu · ${st.name}` : "Dnes v plánu od trenéra"}</Label>
          <InfoDot label="Plán od trenéra" text="Plán určuje trenér, Došlap hlídá, kolik dnes tělo unese: každý trénink porovná s dnešními bezpečnými limity (nevstřebaná zátěž, strop jednoho běhu, celková zátěž) a s pravidly pro bolest, nemoc, připravenost a odstup tvrdých tréninků. Nic neblokuje — ukáže, o kolik a proč se trénink nevejde, a nabídne upravenou verzi." /></span>
        <button type="button" onClick={() => onAdd(day?.date || st.date)} className="flex items-center gap-1 text-[12px] font-bold text-accent hover:underline" data-testid="coach-add-today"><Plus className="size-3.5" aria-hidden />Přidat</button>
      </div>
      {!sess.length && (
        <div className="nest mt-3 p-4 text-center" data-testid="coach-empty-today">
          <Sofa className="mx-auto size-6 text-fg-3" aria-hidden />
          <p className="mt-2 text-[14px] font-bold text-fg">{weekHas ? "Dnes nic v plánu" : "Na tento týden zatím není plán"}</p>
          <p className="mt-1 text-[12px] leading-5 text-fg-3">{weekHas ? "Den volna podle plánu. Pokud trenér něco poslal, přidejte to." : "Vložte plán od trenéra — text, fotku nebo kalendář. Do té doby platí jen bezpečnostní limity."}</p>
          {!weekHas && <Button size="sm" className="mt-3" icon={ClipboardPaste} onClick={onImport} data-testid="coach-import-cta">Vložit plán týdne</Button>}
        </div>
      )}
      {sess.map((s) => {
        const done = ["done", "more", "partial"].includes(s.status)
        const m = s.verdict ? VERDICT[s.verdict] : null
        return (
          <div key={s.id} className="mt-3" data-testid="coach-session">
            <div className="flex items-start gap-3">
              <KindTile kind={s.kind} />
              <div className="min-w-0 flex-1">
                <p className="text-[17px] font-bold leading-6 text-fg">{s.title && s.title !== s.label ? s.title : s.label}
                  <span className="font-semibold text-fg-3">{sizeOf(s) ? ` · ${sizeOf(s)}` : ""}</span></p>
                <p className="mt-0.5 flex flex-wrap gap-x-2 text-[12px] text-fg-3">
                  {s.intervals && <span className="text-fg-2">{s.intervals}</span>}
                  {s.z4 > 0 && <span>{`≈ ${num(s.z4, 0)} min v Z4+`}</span>}
                  {s.target && <span>{`cíl trenéra: ${s.target}`}</span>}
                </p>
              </div>
              <button type="button" onClick={() => onEdit(s, day.date)} aria-label="Upravit trénink" className="grid size-8 shrink-0 place-items-center rounded-full text-fg-3 hover:bg-white/[.06] hover:text-fg"><Pencil className="size-4" aria-hidden /></button>
            </div>
            {done ? (
              <div className="mt-3 flex items-center gap-2 rounded-[14px] bg-ok/10 px-3 py-2.5 text-[13px] text-fg-soft" data-testid="coach-done">
                <Check className="size-4 text-ok" aria-hidden /><b style={{ color: STATUS[s.status].col }}>{STATUS[s.status].label}</b>
                {s.act && <span className="tabular-nums text-fg-2">{s.act.km != null ? `${num(s.act.km)} km` : `${num(s.act.min, 0)} min`}{s.act.z4 ? ` · ${num(s.act.z4, 0)} min Z4+` : ""}</span>}
              </div>
            ) : m && (
              <div className="mt-3 rounded-[16px] border p-3.5" style={{ borderColor: `${m.col}55`, background: `${m.col}0f` }} data-testid="coach-verdict">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-[16px] font-bold" style={{ color: m.col }}><m.Icon className="size-5" aria-hidden />{m.label}</span>
                  {s.verdict === "ok" && <span className="text-[12px] text-fg-2">vejde se do dnešních limitů</span>}
                </div>
                {s.why?.length > 0 && (
                  <ul className="mt-2 grid gap-1 text-[12.5px] leading-5 text-fg-soft">{s.why.slice(0, 2).map((w: string, i: number) => <li key={i} className="flex gap-2"><i className="mt-2 size-1.5 shrink-0 rounded-full" style={{ background: m.col }} /><span>{w}</span></li>)}</ul>
                )}
                {s.verdict === "mod" && (s.fit || s.move) && <div className="mt-2.5"><FitChips s={s} /></div>}
                {s.verdict === "no" && s.alt && (
                  <div className="mt-2.5 flex items-center gap-2 rounded-[12px] bg-white/[.05] px-3 py-2 text-[12.5px]" data-testid="coach-alt">
                    <span className="text-fg-3">Místo toho:</span><b className="text-fg">{s.alt.label}</b>
                    {s.alt.km?.hi ? <span className="tabular-nums text-fg-2">{`${num(s.alt.km.lo)}–${num(s.alt.km.hi)} km`}</span> : s.alt.durationMin ? <span className="tabular-nums text-fg-2">{`${s.alt.durationMin[0]}–${s.alt.durationMin[1]} min`}</span> : null}
                  </div>
                )}
                <ChannelBars s={s} />
              </div>
            )}
          </div>
        )
      })}
      {msg && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" icon={Send} onClick={() => copyText(msg, toast)} data-testid="coach-message">Zpráva pro trenéra</Button>
          <span className="text-[11px] text-fg-3">rozhoduje trenér · Došlap nic neblokuje</span>
        </div>
      )}
      {rid && null}
    </section>
  )
}

/* ------------------------------------------------------------------ the week */
export function WeekStrip({ st, onPick, onImport, onCopy }: { st: any; onPick: (day: any) => void; onImport?: () => void; onCopy?: () => void }) {
  const [wk, setWk] = useState<"this" | "next">("this")
  const ev = st.eval
  if (!ev) return null
  const ws = ev.week?.start
  const all: any[] = ev.days || []
  const start = wk === "this" ? ws : addDays(ws, 7)
  const days = all.filter((d) => d.date >= start && d.date <= addDays(start, 6))
  const plan = ev.week?.plan || {}
  const over: string[] = ev.week?.overDays || []
  const lastWeekHas = all.some((d) => d.date < ws && d.sessions.length)
  const nextSum = sumWeek(days)
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="coach-week">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Plán týdne</Label>
        <Segmented size="sm" ariaLabel="Týden" value={wk} onChange={setWk} options={[["this", "tento týden"], ["next", "příští"]] as const} />
      </div>
      <p className="mt-2 text-[13px] text-fg-2 tabular-nums" data-testid="coach-week-sum">
        {wk === "this" ? (
          <><b className="text-fg">{num(plan.volume)}</b><span>{" km"}</span>{plan.intensity ? <><span>{" · "}</span><b className="text-fg">{num(plan.intensity, 0)}</b><span>{" min v Z4+"}</span></> : null}<span>{" v plánu"}</span></>
        ) : <><b className="text-fg">{num(nextSum.km)}</b><span>{" km v plánu"}</span></>}
      </p>
      <div className="mt-3 grid grid-cols-7 gap-1.5" role="list" aria-label="Dny týdne">
        {days.map((d) => {
          const ss: any[] = d.sessions || []
          const main = ss.find((x) => x.kind !== "rest") || ss[0]
          const v = d.verdict
          const st0 = main?.status
          const pastCol = st0 && STATUS[st0] ? STATUS[st0].col : C.fg4
          const col = d.past ? pastCol : v ? VERDICT[v].col : C.fg4
          const K = main ? KIND[main.kind] || KIND.other : null
          return (
            <button key={d.date} type="button" role="listitem" onClick={() => onPick(d)} data-testid="coach-day"
              className={`flex min-h-[92px] flex-col items-center gap-1 rounded-[14px] border px-0.5 pb-2 pt-1.5 text-center transition ${d.today ? "border-accent/70 bg-accent/[.07]" : "border-white/[.07] bg-white/[.025] hover:border-white/20"}`}>
              <span className={`text-[11px] font-bold ${d.today ? "text-accent" : "text-fg-3"}`}>{WD[d.wd]}</span>
              <span className="text-[10.5px] tabular-nums text-fg-4">{new Date(d.date + "T12:00:00").getDate()}.</span>
              {K ? <K.Icon className={`size-4 ${d.past && st0 === "missed" ? "text-fg-4" : "text-fg-2"}`} aria-hidden /> : <span className="size-4" />}
              <span className="text-[10.5px] font-semibold tabular-nums leading-3 text-fg-2">{main && main.kind !== "rest" ? (sizeOf(main).replace(" km", "") || "·") : ""}</span>
              <i className="mt-auto size-2.5 rounded-full" style={{ background: main && main.kind !== "rest" ? col : "transparent", boxShadow: main && main.kind !== "rest" ? "none" : `inset 0 0 0 1.5px ${C.fg4}` }}
                title={d.past ? (st0 ? STATUS[st0]?.label : "") : v ? VERDICT[v].label : ""} />
              {(d.extra?.length || 0) > 0 && <span className="text-[9.5px] font-bold leading-3 text-info">+{d.extra.length}</span>}
            </button>
          )
        })}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-3">
        {(["ok", "mod", "no"] as const).map((k) => <span key={k} className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: VERDICT[k].col }} />{VERDICT[k].label.toLowerCase()}</span>)}
        <span className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: C.fg3 }} />vynecháno</span>
      </div>
      {wk === "this" && over.length > 0 && (
        <div className="mt-3 flex items-start gap-2 rounded-[14px] border border-watch/30 bg-watch/[.07] px-3 py-2.5 text-[12.5px] leading-5 text-watch-soft" data-testid="coach-over-days">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span><span>{"Nevejde se do bezpečných limitů: "}</span><b>{over.map((x) => dayShort(x)).join(", ")}</b><span>{" — klepněte na den pro upravenou verzi."}</span></span>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {onImport && <Button size="sm" variant="outline" icon={ClipboardPaste} onClick={onImport} data-testid="coach-import">Vložit plán</Button>}
        {onCopy && lastWeekHas && !ev.week?.has && wk === "this" && <Button size="sm" variant="outline" icon={Copy} onClick={onCopy} data-testid="coach-copy">Zkopírovat minulý týden</Button>}
      </div>
    </section>
  )
}

function sumWeek(days: any[]) {
  let km = 0
  for (const d of days) for (const s of d.sessions || []) if (KIND[s.kind]?.run) km += s.km || 0
  return { km }
}
export function addDays(iso: string, n: number) {
  const d = new Date(iso + "T12:00:00")
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

/* ------------------------------------------------------------------ a day */
export function DaySheet({ day, st, onClose, onEdit, onAdd, onDelete, onPair }: {
  day: any; st: any; onClose: () => void; onEdit: (s: any) => void; onAdd: () => void; onDelete: (s: any) => void; onPair?: (s: any, aid: number | null) => void
}) {
  const acts: any[] = (st.acts || []).filter((a: any) => a.date === day.date)
  const title = new Date(day.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" })
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="coach-day-sheet">
        <p className="t-label !text-fg-3">{day.today ? "Dnes" : day.past ? "Proběhlo" : "V plánu"}</p>
        <h2 className="mt-1 font-serif text-[24px] capitalize leading-tight text-fg">{title}</h2>
        {!day.sessions.length && <p className="mt-3 text-sm text-fg-3">Na tento den nic v plánu.</p>}
        {day.sessions.map((s: any) => (
          <div key={s.id} className="nest mt-3 p-3.5" data-testid="coach-day-session">
            <div className="flex items-start gap-3">
              <KindTile kind={s.kind} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-bold text-fg">{s.title && s.title !== s.label ? s.title : s.label}<span className="font-semibold text-fg-3">{sizeOf(s) ? ` · ${sizeOf(s)}` : ""}</span></p>
                <p className="mt-0.5 text-[11.5px] text-fg-3">{[s.intervals, s.target && `cíl: ${s.target}`, s.source === "ics" ? "z kalendáře" : s.source === "coach" ? "od trenéra" : s.source === "text" || s.source === "photo" ? "z importu" : null].filter(Boolean).join(" · ")}</p>
              </div>
              <span className="flex gap-0.5">
                <button type="button" onClick={() => onEdit(s)} aria-label="Upravit" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-white/[.06] hover:text-fg"><Pencil className="size-4" aria-hidden /></button>
                <button type="button" onClick={() => onDelete(s)} aria-label="Smazat" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-alert/10 hover:text-alert"><Trash2 className="size-4" aria-hidden /></button>
              </span>
            </div>
            {s.kind !== "rest" && (day.past || (day.today && ["done", "partial", "more", "missed"].includes(s.status))) ? (
              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px]">
                <span className="rounded-full px-2 py-0.5 font-bold" style={{ background: `${STATUS[s.status]?.col || C.fg3}1f`, color: STATUS[s.status]?.col || C.fg3 }}>{STATUS[s.status]?.label || s.status}</span>
                {s.act && <span className="tabular-nums text-fg-2">{s.act.title || "aktivita"}{s.act.km != null ? ` · ${num(s.act.km)} km` : ""}</span>}
                {onPair && (
                  <select className="ml-auto rounded-lg border bg-transparent px-2 py-1 text-[12px]" aria-label="Spárovat s aktivitou" value={s.act?.id ?? (s.status === "missed" ? "0" : "")}
                    onChange={(e) => onPair(s, e.target.value === "" ? null : +e.target.value)} data-testid="coach-pair">
                    <option value="">automaticky</option>
                    <option value="0">neodběhnuto</option>
                    {acts.map((a) => <option key={a.id} value={a.id}>{`${a.title || "aktivita"}${a.km ? ` · ${num(a.km)} km` : ""}`}</option>)}
                  </select>
                )}
              </div>
            ) : s.verdict && s.verdict !== "rest" && (
              <div className="mt-2.5">
                <VerdictBadge v={s.verdict} small prelim={!day.today} />
                {s.why?.length > 0 && <p className="mt-1.5 text-[12px] leading-5 text-fg-2">{s.why[0]}</p>}
                {s.verdict === "mod" && <div className="mt-2"><FitChips s={s} /></div>}
                {s.over?.length > 0 && (
                  <p className="mt-1.5 text-[11.5px] leading-4 text-fg-3">{s.over.map((o: any) => `${CH.find((c) => c[0] === o.ch)?.[1]}: ${num(disp(o.ch, o.plan), o.ch === "volume" ? 1 : 0)} / max ${num(disp(o.ch, o.max), o.ch === "volume" ? 1 : 0)}`).join(" · ")}</p>
                )}
              </div>
            )}
          </div>
        ))}
        {day.extra?.length > 0 && (
          <div className="mt-3">
            <p className="t-label !text-fg-3">Navíc mimo plán</p>
            {day.extra.map((x: any) => <p key={x.id} className="mt-1 text-[13px] text-fg-2">{`${x.title || "aktivita"}${x.km ? ` · ${num(x.km)} km` : x.min ? ` · ${num(x.min, 0)} min` : ""}`}</p>)}
          </div>
        )}
        {!day.past && <Button size="sm" variant="outline" className="mt-4" icon={Plus} onClick={onAdd} data-testid="coach-day-add">Přidat trénink</Button>}
      </div>
    </Sheet>
  )
}

/* ------------------------------------------------------------------ the session form */
// the backend's coach_plan.hard_minutes, for the form's hint (the server computes the real value)
export function hardMinutes(text: string, easyPace = 360): number | null {
  const t = text.replace(/,/g, ".")
  let pace: number | null = null
  for (const m of t.matchAll(/(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])/g)) { const p = +m[1] * 60 + +m[2]; if (p >= 150 && p <= 540) { pace = p; break } }
  const hp = pace || easyPace * 0.82
  let total = 0, found = false
  for (const m of t.matchAll(/(\d{1,2})\s*[x×*]\s*\(?\s*(\d+(?:\.\d+)?)\s*(km|m\b|min|minut|s\b|sec|'|´|")?/gi)) {
    const n = +m[1], v = +m[2], u = (m[3] || "").toLowerCase()
    if (n < 1 || n > 40) continue
    const mins = u === "km" ? (v * hp) / 60 : u === "m" || (!u && v >= 100) ? (v / 1000) * hp / 60 : ["s", "sec", '"'].includes(u) ? v / 60 : v
    total += n * mins; found = true
  }
  if (!found) {
    const m = t.match(/(?:tempo|threshold|prah\w*|fartlek)\s*[:-]?\s*(\d+(?:\.\d+)?)\s*(min|minut|'|´|km)/i) || t.match(/(\d+(?:\.\d+)?)\s*(min|minut|'|´|km)\s*(?:v\s*)?(?:tempo|tempu|threshold|prah)/i)
    if (m) { total = m[2].toLowerCase() === "km" ? (+m[1] * hp) / 60 : +m[1]; found = true }
  }
  return found ? Math.round(total) : null
}
export function SessionForm({ initial, date, onSave, onCancel, busy, fixedDate = false }: { initial?: any; date: string; onSave: (s: any) => void; onCancel: () => void; busy?: boolean; fixedDate?: boolean }) {
  const [f, setF] = useState<any>(() => ({
    kind: initial?.kind || "easy", title: initial?.title || "", km: initial?.km ?? "", duration_min: initial?.duration_min ?? initial?.min ?? "",
    intervals: initial?.intervals || "", target: initial?.target || "", ascent_m: initial?.ascent_m ?? initial?.asc ?? "", descent_m: initial?.descent_m ?? initial?.desc ?? "",
    notes: initial?.notes || "", z4_min: initial?.z4_min ?? "",
  }))
  const [d, setD] = useState(date)
  const K = KIND[f.kind]
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const n = (v: any) => (v === "" || v == null ? null : +String(v).replace(",", "."))
  const save = () => onSave({
    date: d, kind: f.kind, title: f.title.trim() || null, km: K.run ? n(f.km) : null, duration_min: n(f.duration_min), z4_min: n(f.z4_min),
    intervals: K.run ? f.intervals.trim() || null : null, target: f.target.trim() || null, ascent_m: K.run ? n(f.ascent_m) : null,
    descent_m: K.run ? n(f.descent_m) : null, notes: f.notes.trim() || null,
  })
  const inp = "w-full rounded-xl border px-3 py-2.5 text-sm"
  return (
    <div data-testid="session-form">
      <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6" role="group" aria-label="Typ tréninku">
        {KIND_ORDER.map((k) => {
          const M = KIND[k]
          const on = f.kind === k
          return (
            <button key={k} type="button" aria-pressed={on} onClick={() => set("kind", k)}
              className={`flex flex-col items-center gap-1 rounded-[12px] border px-1 py-2 text-[10.5px] font-bold leading-tight transition ${on ? "border-accent bg-accent/[.1] text-fg" : "border-white/[.08] bg-white/[.03] text-fg-2 hover:border-white/20"}`}>
              <M.Icon className={`size-4 ${on ? "text-accent" : ""}`} aria-hidden />{M.label}
            </button>
          )
        })}
      </div>
      {!fixedDate && (
        <label className="mt-3 block text-[12px] font-bold text-fg-soft">Den
          <input type="date" value={d} onChange={(e) => setD(e.target.value)} className={`${inp} mt-1`} />
        </label>
      )}
      {f.kind !== "rest" && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {K.run && <label className="block text-[12px] font-bold text-fg-soft">Vzdálenost (km)<input inputMode="decimal" value={f.km} onChange={(e) => set("km", e.target.value)} className={`${inp} mt-1`} placeholder="10" data-testid="form-km" /></label>}
            <label className="block text-[12px] font-bold text-fg-soft">Délka (min)<input inputMode="numeric" value={f.duration_min} onChange={(e) => set("duration_min", e.target.value)} className={`${inp} mt-1`} placeholder={K.run ? "nebo minuty" : "60"} /></label>
          </div>
          {K.run && (
            <>
              <label className="mt-3 block text-[12px] font-bold text-fg-soft">Tvrdá část <span className="font-normal text-fg-3">úseky textem</span>
                <input value={f.intervals} onChange={(e) => set("intervals", e.target.value)} className={`${inp} mt-1`} placeholder="6× 1 km v 4:30 · tempo 20 min" data-testid="form-intervals" />
              </label>
              {f.intervals && hardMinutes(f.intervals) != null && !f.z4_min && <p className="mt-1 text-[11px] text-fg-3">{`≈ ${num(hardMinutes(f.intervals), 0)} min v Z4+ (dopočteno z úseků)`}</p>}
              <div className="mt-3 grid grid-cols-3 gap-2">
                <label className="block text-[12px] font-bold text-fg-soft">Z4+ (min)<input inputMode="numeric" value={f.z4_min} onChange={(e) => set("z4_min", e.target.value)} className={`${inp} mt-1`} placeholder="auto" /></label>
                <label className="block text-[12px] font-bold text-fg-soft">Stoupání (m)<input inputMode="numeric" value={f.ascent_m} onChange={(e) => set("ascent_m", e.target.value)} className={`${inp} mt-1`} placeholder="obvyklé" /></label>
                <label className="block text-[12px] font-bold text-fg-soft">Klesání (m)<input inputMode="numeric" value={f.descent_m} onChange={(e) => set("descent_m", e.target.value)} className={`${inp} mt-1`} placeholder="obvyklé" /></label>
              </div>
            </>
          )}
          <label className="mt-3 block text-[12px] font-bold text-fg-soft">Cíl trenéra <span className="font-normal text-fg-3">tempo nebo tep</span>
            <input value={f.target} onChange={(e) => set("target", e.target.value)} className={`${inp} mt-1`} placeholder="4:30/km · Z2 · tep do 150" />
          </label>
        </>
      )}
      <label className="mt-3 block text-[12px] font-bold text-fg-soft">Poznámka
        <input value={f.notes} onChange={(e) => set("notes", e.target.value)} className={`${inp} mt-1`} />
      </label>
      <div className="mt-4 flex gap-2">
        <Button variant="secondary" className="flex-1" onClick={onCancel}>Zrušit</Button>
        <Button className="flex-1" busy={busy} onClick={save} data-testid="form-save">Uložit</Button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ the import */
async function photoToDataUrl(file: File): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url })
    const s = Math.min(1, 1600 / Math.max(img.width, img.height))
    const cv = document.createElement("canvas")
    cv.width = Math.round(img.width * s); cv.height = Math.round(img.height * s)
    cv.getContext("2d")!.drawImage(img, 0, 0, cv.width, cv.height)
    return cv.toDataURL("image/jpeg", 0.85)
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function ImportSheet({ st, rid, onClose, act }: { st: any; rid: string; onClose: () => void; act: (fn: () => Promise<any>, ok?: string) => Promise<any> }) {
  const toast = useToast()
  const [mode, setMode] = useState<"text" | "photo">("text")
  const [week, setWeek] = useState<"this" | "next">(() => (new Date(st.date + "T12:00:00").getDay() % 6 === 0 ? "next" : "this"))
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any | null>(null)
  const [edit, setEdit] = useState<number | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const ws = week === "this" ? st.weekStart : addDays(st.weekStart, 7)
  const run = async (body: any) => {
    setBusy(true)
    try { setRes(await api.planImport(rid, { ...body, week: ws })) } catch (e: any) { toast({ title: e?.message || "Plán se nepodařilo načíst" }) } finally { setBusy(false) }
  }
  const onPhoto = async (f?: File) => {
    if (!f) return
    try { await run({ image: await photoToDataUrl(f) }) } catch { toast({ title: "Fotku se nepodařilo otevřít" }) }
  }
  const save = async () => {
    setBusy(true)
    try {
      await act(() => api.planConfirm(rid, res.sessions.map(({ unsure, seq, ext_uid, ...x }: any) => x), res.via), "Plán uložen")
      onClose()
    } finally { setBusy(false) }
  }
  const sess: any[] = res?.sessions || []
  const pv = res?.preview
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="import-sheet">
        <p className="t-label !text-fg-3">Plán od trenéra</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">Vložit plán</h2>
        {!res && (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Segmented size="sm" ariaLabel="Zdroj" value={mode} onChange={setMode} options={[["text", "text"], ["photo", "fotka"]] as const} />
              <Segmented size="sm" ariaLabel="Týden" value={week} onChange={setWeek} options={[["this", "tento týden"], ["next", "příští týden"]] as const} />
            </div>
            {mode === "text" ? (
              <>
                <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} data-testid="import-text"
                  placeholder={"Po: 10 km lehce\nÚt: 2 km rozklus, 6× 1 km v 4:30, 2 km výklus\nSt: volno\n…"}
                  className="mt-3 w-full rounded-xl border px-3 py-2.5 text-[13px] leading-5" />
                <p className="mt-1 text-[11px] text-fg-3">Zkopírujte zprávu z WhatsAppu, e-mailu nebo řádky z tabulky. Každý den na nový řádek (Po, Út … nebo datum).</p>
                <Button className="mt-3 w-full" busy={busy} icon={ClipboardPaste} onClick={() => run({ text })} disabled={!text.trim()} data-testid="import-read">Načíst plán</Button>
              </>
            ) : (
              <>
                <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => onPhoto(e.target.files?.[0])} />
                <button type="button" onClick={() => file.current?.click()} disabled={busy}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-[16px] border-2 border-dashed border-info/50 p-8 text-sm font-bold text-accent transition hover:border-accent hover:bg-accent/[.04]">
                  {busy ? <RefreshCw className="size-5 animate-spin" aria-hidden /> : <Camera className="size-5" aria-hidden />}{busy ? "Čtu fotku…" : "Vyfotit nebo vybrat obrázek plánu"}
                </button>
                <p className="mt-1 text-[11px] text-fg-3">Fotku přečte bezplatný model a hned ji zahodí — neukládáme ji. Výsledek vždy zkontrolujete.</p>
              </>
            )}
          </>
        )}
        {res && (
          <>
            <p className="mt-2 text-[12px] text-fg-3">{res.via === "llm" ? "Přečteno modelem a zkontrolováno aplikací." : res.via === "photo" ? "Přečteno z fotky." : "Přečteno aplikací."}{" Zkontrolujte, co je označené."}</p>
            <div className="mt-3 grid gap-2" data-testid="import-preview">
              {sess.map((s, i) => {
                const v = pv?.verdicts?.[String(i)]
                const unsure: string[] = s.unsure || []
                return edit === i ? (
                  <div key={i} className="nest p-3"><SessionForm initial={s} date={s.date} onCancel={() => setEdit(null)}
                    onSave={(x) => { setRes({ ...res, sessions: sess.map((y, j) => (j === i ? { ...x, unsure: [] } : y)) }); setEdit(null) }} /></div>
                ) : (
                  <button key={i} type="button" onClick={() => setEdit(i)} data-testid="import-row"
                    className={`flex items-center gap-3 rounded-[14px] border p-2.5 text-left transition hover:border-white/25 ${unsure.length ? "border-watch/50 bg-watch/[.05]" : "border-white/[.08] bg-white/[.03]"}`}>
                    <span className="w-9 shrink-0 text-center text-[11px] font-bold text-fg-3">{dayShort(s.date)}<span className="block text-[10px] font-semibold text-fg-4">{fmtD(s.date)}</span></span>
                    <KindTile kind={s.kind} size="sm" />
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-[13px] text-fg">{KIND[s.kind]?.label}{s.km ? ` · ${num(s.km)} km` : s.duration_min ? ` · ${num(s.duration_min, 0)} min` : ""}</b>
                      <span className="block truncate text-[11px] text-fg-3">{s.intervals || s.title}</span>
                      {unsure.length > 0 && <span className="mt-0.5 block text-[11px] font-bold text-watch">{`zkontrolujte: ${unsure.map((u) => ({ km: "vzdálenost", kind: "typ", min: "délku", z4: "tvrdou část", date: "den" } as any)[u] || u).join(", ")}`}</span>}
                    </span>
                    {v?.verdict && <i className="size-2.5 shrink-0 rounded-full" style={{ background: VERDICT[v.verdict]?.col || C.fg4 }} title={VERDICT[v.verdict]?.label} />}
                    <Pencil className="size-3.5 shrink-0 text-fg-4" aria-hidden />
                  </button>
                )
              })}
            </div>
            {pv?.overDays?.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-[14px] border border-watch/30 bg-watch/[.07] px-3 py-2.5 text-[12.5px] leading-5 text-watch-soft" data-testid="import-over">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span><span>{"Nad bezpečnými limity: "}</span><b>{pv.overDays.map((x: string) => dayShort(x)).join(", ")}</b><span>{". Plán uložíte i tak — u dne uvidíte upravenou verzi."}</span></span>
              </div>
            )}
            {pv?.message && <Button size="sm" variant="outline" className="mt-2" icon={Send} onClick={() => copyText(pv.message, toast)}>Zpráva pro trenéra</Button>}
            {pv?.replaced > 0 && <p className="mt-2 text-[11.5px] text-fg-3">{`Nahradí ${pv.replaced} dříve zadaných tréninků v těchto dnech.`}</p>}
            <div className="mt-4 flex gap-2">
              <Button variant="secondary" className="flex-1" onClick={() => setRes(null)}>Zpět</Button>
              <Button className="flex-1" busy={busy} onClick={save} disabled={!sess.length} data-testid="import-save">{`Uložit ${sess.length} tréninků`}</Button>
            </div>
          </>
        )}
      </div>
    </Sheet>
  )
}

/* ------------------------------------------------------------------ progress */
export function AdherenceCard({ list }: { list: any[] }) {
  const [i, setI] = useState<"0" | "1">(list.length > 1 ? "0" : "0")
  if (!list?.length) return null
  const a = list[+i] || list[0]
  const cells: [string, boolean, boolean, string][] = [
    ["both", true, true, "plán ✓ · limity ✓"], ["plan", true, false, "plán ✓ · limity ✗"],
    ["safe", false, true, "plán ✗ · limity ✓"], ["neither", false, false, "plán ✗ · limity ✗"],
  ]
  const tone = a.tone === "good" || a.tone === "praise" ? C.ok : a.tone === "ok" ? C.info : a.tone === "warn" ? C.alert : C.fg3
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="coach-adherence">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Plán a limity</Label>
          <InfoDot label="Plán a limity" text="Progres podle trenéra: plán se plní, bezpečné limity drží a týdenní kapacita roste bez skoků. Plán = kolik tréninků a kilometrů z plánu proběhlo. Limity = dny, kdy nevstřebaná zátěž zůstala pod týdenním stropem a žádný běh nepřekročil strop jednoho běhu." /></span>
        {list.length > 1 && <Segmented size="sm" ariaLabel="Týden" value={i} onChange={setI} options={[["0", "minulý týden"], ["1", "tento týden"]] as const} />}
      </div>
      <div className="mt-3 grid grid-cols-[auto_1fr_1fr] gap-1.5 text-[11px]" data-testid="coach-quad">
        <span />
        <span className="text-center font-bold text-fg-3">limity drží</span>
        <span className="text-center font-bold text-fg-3">limity přetažené</span>
        {[true, false].map((planOk) => (
          <Frag key={String(planOk)}>
            <span className="flex items-center pr-1 font-bold text-fg-3">{planOk ? "plán ✓" : "plán ✗"}</span>
            {[true, false].map((safeOk) => {
              const c = cells.find((x) => x[1] === planOk && x[2] === safeOk)!
              const on = a.quad === c[0]
              const col = c[0] === "both" ? C.ok : c[0] === "neither" ? C.alert : c[0] === "safe" ? C.info : C.watch
              return (
                <span key={c[0]} className="grid h-12 place-items-center rounded-[12px] border text-[11px] font-bold transition"
                  style={{ borderColor: on ? col : "rgba(255,255,255,.07)", background: on ? `${col}22` : "rgba(255,255,255,.02)", color: on ? col : C.fg4 }}>
                  {on ? <Check className="size-4" aria-hidden /> : "·"}
                </span>
              )
            })}
          </Frag>
        ))}
      </div>
      {a.msg && <p className="mt-3 rounded-[14px] px-3 py-2.5 text-[13px] leading-5" style={{ background: `${tone}14`, color: C.fgSoft, borderLeft: `3px solid ${tone}` }} data-testid="coach-adh-msg">{a.msg}</p>}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Plán" value={a.sessions?.[1] ? `${a.sessions[0]}/${a.sessions[1]}` : "—"} sub={a.km?.[1] ? `${num(a.km[0])} z ${num(a.km[1])} km` : "tréninků"} ok={a.planOk} />
        <Tile label="Bezpečné dny" value={a.safe?.[1] ? `${a.safe[0]}/${a.safe[1]}` : "—"} sub="v limitech" ok={a.safeOk} dots={a.safe} />
        <Tile label="Lehké opravdu lehce" value={a.easy?.[1] ? `${a.easy[0]}/${a.easy[1]}` : "—"} sub="≥ 80 % v Z1–Z2" ok={a.easy?.[1] ? a.easy[0] === a.easy[1] : null} />
        <Tile label="Tvrdé v cíli" value={a.hard?.[1] ? `${a.hard[0]}/${a.hard[1]}` : "—"} sub="Z4+ ± 20 %" ok={a.hard?.[1] ? a.hard[0] === a.hard[1] : null} />
      </div>
      {(a.readiness != null || a.painMax != null) && (
        <p className="mt-2 text-[11.5px] text-fg-3">{[a.readiness != null ? `průměrná připravenost ${a.readiness} %` : null, a.painMax != null ? `nejvyšší bolest ${a.painMax}/10` : "bez bolesti v deníku"].filter(Boolean).join(" · ")}</p>
      )}
    </section>
  )
}
function Frag({ children }: { children: ReactNode }) { return <>{children}</> }
function Tile({ label, value, sub, ok, dots }: { label: string; value: string; sub: string; ok: boolean | null; dots?: number[] }) {
  const col = ok == null ? C.fg2 : ok ? C.ok : C.watch
  return (
    <div className="rounded-[14px] border border-white/[.07] bg-white/[.025] p-2.5">
      <p className="text-[10.5px] font-bold uppercase tracking-[.06em] text-fg-3">{label}</p>
      <p className="mt-1 text-[20px] font-bold leading-6 tabular-nums" style={{ color: col }}>{value}</p>
      {dots && dots[1] ? (
        <span className="mt-1 flex gap-0.5">{Array.from({ length: dots[1] }, (_, k) => <i key={k} className="h-1.5 flex-1 rounded-full" style={{ background: k < dots[0] ? C.ok : C.watch }} />)}</span>
      ) : <p className="text-[11px] text-fg-3">{sub}</p>}
    </div>
  )
}

export function TrendCard({ trend }: { trend: any[] }) {
  const [ch, setCh] = useState<"volume" | "intensity">("volume")
  const [hv, setHv] = useState<number | null>(null)
  if (!trend?.length) return null
  const unit = ch === "volume" ? "km" : "min"
  const d = ch === "volume" ? 1 : 0
  const vals = trend.map((t) => ({ cap: t[ch] as number | null, done: t[ch + "Done"] as number | null, start: t.start as string }))
  const top = Math.max(...vals.map((v) => Math.max(v.cap || 0, v.done || 0)), 0.1) * 1.12
  const W = 100, H = 100
  const x = (i: number) => (i + 0.5) * (W / vals.length)
  const pts = vals.map((v, i) => (v.cap != null ? `${x(i)},${H - ((v.cap || 0) / top) * H}` : null)).filter(Boolean).join(" ")
  const first = vals.find((v) => v.cap != null)?.cap, last = [...vals].reverse().find((v) => v.cap != null)?.cap
  const h = hv != null ? vals[hv] : null
  return (
    <section className="card mt-4 p-4 md:p-6" data-testid="coach-trend">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><Label>Kapacita za 12 týdnů</Label>
          <InfoDot label="Kapacita" text="Týdenní kapacita = kolik prokazatelně zvládáte (průměr posledních týdnů, nebo nejlepší týden bez bolesti). Když držíte plán i limity, roste postupně. Sloupce = co jste v týdnu skutečně odběhli." /></span>
        <Segmented size="sm" ariaLabel="Kanál" value={ch} onChange={setCh} options={[["volume", "objem"], ["intensity", "Z4+"]] as const} />
      </div>
      {first != null && last != null && (
        <p className="mt-2 text-[13px] text-fg-2 tabular-nums">
          <span>{"kapacita "}</span><b className="text-fg">{num(first, d)}</b><ArrowRight className="mx-1 inline size-3.5" aria-hidden /><b className="text-fg">{num(last, d)}</b><span>{` ${unit} týdně`}</span>
        </p>
      )}
      <div className="relative mt-3 h-[140px]" onMouseLeave={() => setHv(null)}>
        <div className="absolute inset-0 flex items-end gap-1 border-b border-white/15">
          {vals.map((v, i) => (
            <button key={v.start} type="button" className="flex h-full flex-1 items-end" onMouseEnter={() => setHv(i)} onFocus={() => setHv(i)} onClick={() => setHv(hv === i ? null : i)}
              aria-label={`${fmtD(v.start)}: ${num(v.done, d)} ${unit}`}>
              <i className="block w-full rounded-t-[4px]" style={{ height: `${((v.done || 0) / top) * 100}%`, background: i === vals.length - 1 ? `${C.load}88` : C.load, opacity: hv == null || hv === i ? 1 : 0.55 }} />
            </button>
          ))}
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
          <polyline points={pts} fill="none" stroke={C.accent} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </svg>
        {h && (
          <div className="pointer-events-none absolute left-1/2 top-0 z-10 w-[190px] -translate-x-1/2 rounded-[12px] border border-white/10 bg-raised/95 p-2 text-[11.5px] shadow-xl">
            <p className="font-bold text-fg">{`týden od ${fmtD(h.start)}`}</p>
            <p className="mt-1 flex justify-between text-fg-2"><span>odběhnuto</span><b className="tabular-nums text-fg">{`${num(h.done, d)} ${unit}`}</b></p>
            <p className="flex justify-between text-fg-2"><span>kapacita</span><b className="tabular-nums text-fg">{`${num(h.cap, d)} ${unit}`}</b></p>
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 text-[11px] text-fg-3">
        <span className="flex items-center gap-1"><i className="size-2.5 rounded-[3px]" style={{ background: C.load }} />odběhnuto za týden</span>
        <span className="flex items-center gap-1"><i className="h-0.5 w-3 rounded-full" style={{ background: C.accent }} />týdenní kapacita</span>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ Trénink: everything of coach mode */
export function CoachSection({ rid, children }: { rid: string; children?: ReactNode }) {
  const { st, act } = usePlan(rid)
  const [day, setDay] = useState<any | null>(null)
  const [form, setForm] = useState<{ s?: any; date: string } | null>(null)
  const [imp, setImp] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!st?.on || !st.eval) return st?.on && !st?.eval ? <p className="mt-4 text-sm text-fg-3">Načítám plán…</p> : null
  const save = async (x: any) => {
    setBusy(true)
    try {
      await act(() => (form?.s?.id ? api.planEdit(rid, form.s.id, x) : api.planAdd(rid, x)), form?.s?.id ? "Trénink upraven" : "Trénink přidán")
      setForm(null); setDay(null)
    } finally { setBusy(false) }
  }
  const delSession = async (s: any) => { await act(() => api.planDelete(rid, s.id), "Trénink smazán"); setDay(null) }
  const pair = async (s: any, aid: number | null) => { await act(() => api.planPair(rid, s.id, aid), "Párování uloženo") }
  const copyLast = () => act(() => api.planCopyWeek(rid, addDays(st.weekStart, -7), st.weekStart), "Minulý týden zkopírován")
  const freshDay = day ? st.eval.days.find((d: any) => d.date === day.date) || day : null
  return (
    <>
      <CoachToday st={st} rid={rid} onEdit={(s, date) => setForm({ s: rowOf(s), date })} onAdd={(date) => setForm({ date })} onImport={() => setImp(true)} />
      <WeekStrip st={st} onPick={setDay} onImport={() => setImp(true)} onCopy={copyLast} />
      {children}
      {freshDay && !form && (
        <DaySheet day={freshDay} st={st} onClose={() => setDay(null)} onEdit={(s) => setForm({ s: rowOf(s), date: freshDay.date })}
          onAdd={() => setForm({ date: freshDay.date })} onDelete={delSession} onPair={pair} />
      )}
      {form && (
        <Sheet open onClose={() => setForm(null)}>
          <p className="t-label !text-fg-3">{form.s ? "Upravit trénink" : "Nový trénink"}</p>
          <div className="mt-3"><SessionForm initial={form.s} date={form.date} busy={busy} onCancel={() => setForm(null)} onSave={save} /></div>
        </Sheet>
      )}
      {imp && <ImportSheet st={st} rid={rid} act={act} onClose={() => setImp(false)} />}
    </>
  )
}
export function CoachProgress({ rid }: { rid: string }) {
  const { st } = usePlan(rid)
  if (!st?.on || !st.eval) return null
  return (
    <>
      <AdherenceCard list={st.adherence || []} />
      <TrendCard trend={st.trend || []} />
    </>
  )
}
// an evaluated session back into the form's fields
function rowOf(s: any) {
  return { id: s.id, kind: s.kind, title: s.title, km: s.km, duration_min: s.est?.includes("min") ? null : s.min, intervals: s.intervals, target: s.target,
    ascent_m: s.asc, descent_m: s.desc, notes: s.notes, z4_min: s.est?.some((e: string) => e.startsWith("z4")) ? null : s.z4 }
}

/* ------------------------------------------------------------------ Profil → Data: the switch and the sources */
const APPS: { key: string; name: string; steps: string[] }[] = [
  { key: "tp", name: "TrainingPeaks", steps: ["Na webu TrainingPeaks: Settings → Account → Calendar (Calendar Sync).", "Zkopírujte odkaz webcal:// a vložte ho sem.", "Jen pro účet Premium; TrainingPeaks posílá 5 dní zpět a 14 dní dopředu, změny se mohou projevit až do 24 hodin."] },
  { key: "fs", name: "Final Surge", steps: ["Ve Final Surge: Settings → Calendar Sync → Edit Sync → Turn On.", "Zkopírujte zobrazený Sync URL a vložte ho sem."] },
  { key: "icu", name: "Intervals.icu", steps: ["V Intervals.icu najděte v nastavení kalendáře odkaz pro export do kalendáře (iCal / webcal).", "Zkopírujte ho a vložte sem."] },
  { key: "runna", name: "Runna", steps: ["V Runně: Connected Apps & Devices → Calendar Syncing → Connect Calendar → Other.", "Zkopírujte odkaz kalendáře (iCalendar) a vložte ho sem."] },
  { key: "gcal", name: "Google Kalendář", steps: ["Pokud vám trenér plán sdílí v Google Kalendáři: Nastavení kalendáře → Integrovat kalendář.", "Zkopírujte „Tajnou adresu ve formátu iCal“ a vložte ji sem."] },
  { key: "ics", name: "Jiný (iCal)", steps: ["Jakýkoli kalendář s odkazem .ics nebo webcal://."] },
]

export function CoachModeCard({ rid }: { rid: string }) {
  const { st, act } = usePlan(rid)
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState<string | null>(null)
  const [app, setApp] = useState<string | null>(null)
  const [url, setUrl] = useState("")
  const [consent, setConsent] = useState(false)
  const [coachName, setCoachName] = useState("")
  const [explain, setExplain] = useState(false)
  if (!st) return null
  const on = !!st.on
  const toggle = async (v: boolean) => {
    setBusy(true)
    try { await act(() => api.planMode(rid, v, name ?? st.name), v ? "Režim trenéra zapnut" : "Režim trenéra vypnut") } finally { setBusy(false) }
  }
  const saveName = () => name != null && name !== (st.name || "") && act(() => api.planMode(rid, on, name), "Uloženo")
  const connect = async () => {
    setBusy(true)
    try { const d = await act(() => api.planFeed(rid, url)); setUrl(""); setApp(null); toast({ title: d?.feed?.status?.ok ? `Kalendář připojen · ${d.feed.status.n} tréninků` : d?.feed?.status?.error || "Kalendář se nepodařilo načíst" }) } finally { setBusy(false) }
  }
  const feed = st.feed || {}
  const fst = feed.status || {}
  const links: any[] = st.links || []
  const linkUrl = (p: string) => `${location.origin}${p}`
  const what: [LucideIcon, string, string][] = [
    [CalendarDays, "Plán určuje trenér", "Trénink ukáže váš plán a u každého tréninku verdikt: sedí, sedí s úpravou, nebo dnes raději ne."],
    [RefreshCw, "Vlastní cyklus aplikace se vypne", "Cíl týdne = součet plánu. Bez zadaného plánu platí jen bezpečnostní limity."],
    [ShieldCheck, "Bezpečnost zůstává", "Limity zátěže, bolest, nemoc i připravenost hlídáme dál. Nic se neblokuje — jen doporučení a zpráva pro trenéra."],
  ]
  return (
    <section className="card mt-4 p-4 md:p-5" data-testid="coach-mode-card">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-3">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-info/15 text-info"><Users className="size-4" aria-hidden /></span>
          <span><b className="block text-[15px] text-fg">Trénuju podle trenéra</b><span className="block text-[12px] text-fg-3">{on ? (st.name ? `plán od: ${st.name}` : "režim trenéra zapnutý") : "Došlap navrhuje vlastní trénink"}</span></span>
        </span>
        <Switch checked={on} onChange={toggle} label="Trénuju podle trenéra" disabled={busy} />
      </div>
      {(!on || explain) && (
        <div className="mt-3 grid gap-2" data-testid="coach-mode-explain">
          {what.map(([I, t, d]) => (
            <div key={t} className="flex items-start gap-3 rounded-[14px] bg-white/[.03] p-3">
              <I className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <span><b className="block text-[13px] text-fg">{t}</b><span className="block text-[12px] leading-5 text-fg-2">{d}</span></span>
            </div>
          ))}
          {!on && <p className="text-[11px] text-fg-3">Vypnutím se vrátí doporučení a cyklus aplikace; zadaný plán zůstane uložený.</p>}
        </div>
      )}
      {on && (
        <>
          <button type="button" onClick={() => setExplain((v) => !v)} className="mt-2 text-[12px] font-bold text-accent hover:underline">{explain ? "Skrýt, co režim dělá" : "Co režim dělá"}</button>
          <label className="mt-3 block text-[12px] font-bold text-fg-soft">Jméno trenéra <span className="font-normal text-fg-3">nepovinné</span>
            <input value={name ?? st.name ?? ""} onChange={(e) => setName(e.target.value)} onBlur={saveName} className="mt-1 w-full rounded-xl border px-3 py-2.5 text-sm" placeholder="např. Petr" />
          </label>

          <div className="mt-4 border-t border-white/[.08] pt-4">
            <p className="t-label">Odkud plán vezmeme</p>
            <div className="mt-2 grid grid-cols-3 gap-1.5">
              <div className="rounded-[14px] border border-white/[.08] bg-white/[.03] p-2.5"><Link2 className="size-4 text-accent" aria-hidden /><b className="mt-1 block text-[12.5px] leading-4 text-fg">Kalendář</b><span className="block text-[11px] leading-4 text-fg-3">sám každé ráno</span></div>
              <Link to="/app/training" className="rounded-[14px] border border-white/[.08] bg-white/[.03] p-2.5 transition hover:border-white/20"><ClipboardPaste className="size-4 text-accent" aria-hidden /><b className="mt-1 block text-[12.5px] leading-4 text-fg">Text, fotka</b><span className="block text-[11px] leading-4 text-fg-3">v Tréninku</span></Link>
              <Link to="/app/training" className="rounded-[14px] border border-white/[.08] bg-white/[.03] p-2.5 transition hover:border-white/20"><Pencil className="size-4 text-accent" aria-hidden /><b className="mt-1 block text-[12.5px] leading-4 text-fg">Ručně</b><span className="block text-[11px] leading-4 text-fg-3">v Tréninku po dnech</span></Link>
            </div>
            {feed.set ? (
              <div className="nest mt-3 p-3.5" data-testid="feed-status">
                <p className="flex flex-wrap items-center gap-2 text-[13px] text-fg"><Link2 className="size-4 text-accent" aria-hidden /><b>Kalendář připojen</b>
                  {fst.ok === false ? <Chip tone="alert">chyba</Chip> : fst.ok ? <Chip tone="ok">{`${fst.n ?? 0} tréninků`}</Chip> : null}</p>
                <p className="mt-1 truncate text-[11.5px] text-fg-3">{feed.url}</p>
                <p className="mt-1 text-[11.5px] text-fg-3">{fst.at ? `naposledy ${fmtD(fst.at)} ${String(fst.at).slice(11, 16)}` : "zatím nenačteno"}{" · obnovuje se samo každé ráno a při otevření"}</p>
                {fst.error && <p className="mt-1 text-[12px] text-alert">{fst.error}</p>}
                <div className="mt-2.5 flex flex-wrap gap-2">
                  <Button size="sm" icon={RefreshCw} onClick={() => act(() => api.planFeedSync(rid), "Plán z kalendáře obnoven")}>Načíst teď</Button>
                  <Button size="sm" variant="outline" icon={Unplug} onClick={() => act(() => api.planFeedDrop(rid), "Kalendář odpojen")}>Odpojit</Button>
                </div>
              </div>
            ) : (
              <>
                <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Aplikace trenéra">
                  {APPS.map((x) => (
                    <button key={x.key} type="button" aria-pressed={app === x.key} onClick={() => setApp(app === x.key ? null : x.key)} data-testid="feed-app"
                      className={`rounded-full border px-3 py-1.5 text-[12px] font-bold transition ${app === x.key ? "border-fg bg-fg text-ink" : "border-white/12 text-fg-2 hover:text-fg"}`}>{x.name}</button>
                  ))}
                </div>
                {app && (
                  <div className="nest mt-3 p-3.5" data-testid="feed-steps">
                    <ol className="grid gap-1.5 text-[12.5px] leading-5 text-fg-2">
                      {APPS.find((x) => x.key === app)!.steps.map((s, k) => <li key={k} className="flex gap-2"><b className="grid size-5 shrink-0 place-items-center rounded-full bg-white/[.08] text-[11px] text-fg">{k + 1}</b><span>{s}</span></li>)}
                    </ol>
                    <div className="mt-3 flex gap-2">
                      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="webcal://… nebo https://….ics" className="w-full rounded-xl border px-3 py-2.5 text-[12px]" data-testid="feed-url" />
                      <Button size="sm" busy={busy} onClick={connect} disabled={!url.trim()} className="shrink-0" data-testid="feed-connect">Připojit</Button>
                    </div>
                    <p className="mt-2 text-[11px] leading-4 text-fg-3">Odkaz je soukromý — uložíme ho jen u vás a nikomu ho neukazujeme. Z kalendáře bereme jen tréninky; den, který upraví trenér v přehledu, zůstane jeho.</p>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="mt-4 border-t border-white/[.08] pt-4" data-testid="coach-share">
            <p className="t-label">Přehled pro trenéra</p>
            <p className="mt-1.5 text-[12.5px] leading-5 text-fg-2">Odkaz, přes který trenér uvidí váš stav a může upravit plán na 6 měsíců dopředu — jeho úprava daného dne přepíše dosavadní plán.</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {["připravenost", "spánek", "HRV", "klidový tep", "bolest z deníku", "aktivity 14 dní", "plán a verdikty"].map((x) => <Chip key={x}>{x}</Chip>)}
            </div>
            {links.map((l) => (
              <div key={l.token} className="nest mt-3 p-3" data-testid="coach-link">
                <p className="flex flex-wrap items-center gap-2 text-[13px] text-fg"><b>{l.coachName ? `Trenér: ${l.coachName}` : "Odkaz pro trenéra"}</b>
                  <Chip tone={l.lastSeenAt ? "ok" : "muted"}>{l.lastSeenAt ? `otevřeno ${fmtD(l.lastSeenAt)}` : "zatím neotevřeno"}</Chip></p>
                <p className="mt-1 text-[11.5px] text-fg-3">{`platí do ${fmtD(l.expiresAt)} · každé otevření uvidíte v „Kdo přistupoval k vašim datům“`}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" icon={Copy} onClick={() => { navigator.clipboard?.writeText(linkUrl(l.path)); toast({ title: "Odkaz zkopírován" }) }}>Kopírovat odkaz</Button>
                  <Button size="sm" variant="outline" icon={CircleMinus} onClick={() => act(() => api.coachLinkRevoke(rid, l.token), "Odkaz zrušen — trenér už nic neuvidí")}>Zrušit odkaz</Button>
                </div>
              </div>
            ))}
            {!links.length && (
              <div className="mt-3">
                <input value={coachName} onChange={(e) => setCoachName(e.target.value)} placeholder="Jméno trenéra (nepovinné)" className="w-full rounded-xl border px-3 py-2.5 text-sm" />
                <label className="mt-2.5 flex cursor-pointer items-start gap-2.5 text-[12.5px] leading-5 text-fg-2">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 size-4 accent-accent" data-testid="coach-consent" />
                  <span>Souhlasím, že trenér s tímto odkazem uvidí moje zdravotní údaje (připravenost, spánek, HRV, klidový tep, bolest) a tréninky a může upravovat můj plán. Souhlas odvolám zrušením odkazu.</span>
                </label>
                <Button size="sm" className="mt-3" icon={Link2} disabled={!consent} onClick={() => act(() => api.coachLinkCreate(rid, coachName.trim() || null, consent), "Odkaz pro trenéra vytvořen")} data-testid="coach-link-create">Vytvořit odkaz</Button>
                <p className="mt-1.5 text-[11px] text-fg-3">Platí 6 měsíců, kdykoli ho zrušíte.</p>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
