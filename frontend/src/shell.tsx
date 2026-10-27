// App shell pieces (redesign v2 §3 + OPT-5): nav icons, desktop sidebar and the
// customisable desktop stat rail. Behaviour of the existing shell (Topbar,
// AtlasNav, Check-in) lives in App.tsx; this file only adds the desktop layout.
import { useEffect, useMemo, useState, useSyncExternalStore } from "react"
import { Link, useLocation, useNavigate } from "react-router"
import {
  Activity, ChevronDown, ChevronUp, Database, Flag, Footprints, Gauge, HeartHandshake, HeartPulse, House, Moon, NotebookPen, Pencil, SlidersHorizontal, Target, TrendingUp, Users, Zap,
  type LucideIcon,
} from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { QUAD } from "@/lib"
import { C, goodCol } from "@/tokens"
import { Label, MiniTrend, Sheet, Switch } from "@/ui"
import { METRIC_IDS, MetricSheet, useTileTrends, type MetricId } from "@/metricsheet"
import { readinessCol, readinessPct } from "@/capacity"
import { dataStage } from "@/firstday"

export const NAV_ICON: Record<string, LucideIcon> = {
  today: House, training: Target, post: NotebookPen, mechanics: Footprints, load: Activity, messages: HeartHandshake,
}

// Brand mark "Kontakt" (brand book 2026-10-05): the open ring is the runner's own norm
// (the app's rings), the dot in its gap the moment the foot lands (došlap), the line
// the ground. Below ~28 px the compact form drops the ground line and thickens the ring.
export function Mark({ size = 36 }: { size?: number }) {
  const inner = size * 0.78
  const compact = inner < 28
  return (
    <span className="grid shrink-0 place-items-center rounded-xl bg-ink" style={{ width: size, height: size }}>
      <svg viewBox="0 0 64 64" style={{ width: inner, height: inner }} aria-hidden="true">
        {compact ? (
          <g transform="translate(0 3)">
            <path d="M21.53 42.4 A17 17 0 1 1 42.47 42.4" fill="none" stroke={C.accent} strokeWidth="7" strokeLinecap="round" />
            <circle cx="32" cy="46.5" r="4.6" fill={C.accent} />
          </g>
        ) : (
          <>
            <path d="M21.53 42.4 A17 17 0 1 1 42.47 42.4" fill="none" stroke={C.accent} strokeWidth="6" strokeLinecap="round" />
            <circle cx="32" cy="46" r="4" fill={C.accent} />
            <path d="M22 54 H42" stroke={C.fg3} strokeWidth="3" strokeLinecap="round" />
          </>
        )}
      </svg>
    </span>
  )
}

// The wordmark: "došlap" in lower case, the háček over "š" in the accent colour (the
// only coloured part, drawn with the ring's stroke).
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`whitespace-nowrap font-extrabold tracking-[-.04em] ${className}`}>
      <span className="sr-only">Došlap</span>
      <span aria-hidden="true">
        do<span className="relative inline-block leading-none">s<svg viewBox="0 0 36 22" className="absolute bottom-[.68em] left-1/2 h-[.2em] w-[.34em] -translate-x-1/2 overflow-visible">
          <path d="M5 5 L18 17 L31 5" fill="none" stroke={C.accent} strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg></span>lap
      </span>
    </span>
  )
}

/* ---------------- Desktop sidebar (lg+) ---------------- */
export function Sidebar({ items }: { items: [string, string][] }) {
  const { pathname } = useLocation()
  const { realMe, viewing } = useApp()
  const link = (to: string, label: string, Icon: LucideIcon, key: string) => {
    const on = pathname === to || pathname.startsWith(to + "/")
    return (
      <Link key={key} to={to} aria-current={on ? "page" : undefined} onClick={() => { if (on) window.scrollTo({ top: 0, behavior: "smooth" }) }}
        className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-bold transition ${on ? "bg-accent/12 text-accent" : "text-fg-2 hover:bg-white/[.05] hover:text-fg"}`}>
        <Icon className="size-[18px] shrink-0" aria-hidden />
        {label}
      </Link>
    )
  }
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[220px] flex-col border-r border-white/[.07] bg-bg/95 px-3 pb-6 pt-5 backdrop-blur lg:flex" aria-label="Hlavní navigace">
      <Link to="/app/today" className="mb-6 flex items-center gap-2.5 px-2 text-lg font-extrabold tracking-[-.04em]">
        <Mark size={34} />
        <Wordmark />
      </Link>
      <nav className="grid gap-1">{items.map(([id, label]) => link(`/app/${id}`, label, NAV_ICON[id] || House, id))}</nav>
      <div className="mt-6 border-t border-white/[.07] pt-4">
        <p className="t-label mb-2 px-3 !text-fg-3">Nastavení</p>
        <nav className="grid gap-1">
          {!viewing && link("/data", "Data a připojení", Database, "data")}
          {!viewing && link("/engine", "Citlivostní analýza", SlidersHorizontal, "engine")}
          {(realMe?.owner || realMe?.team) && link("/admin", "Správa a tým", Users, "admin")}
        </nav>
      </div>
    </aside>
  )
}

/* ---------------- Number cards: the desktop rail (xl+) and Moje čísla on Dnes (phone) ---------------- */
type RailCard = { id: string; label: string; to: string; Icon: LucideIcon; render: () => { value: string; unit?: string; sub?: string; col?: string; pct?: number } | null }
const DEFAULT_RAIL = ["readiness", "week", "load", "mech"]
// v0.12.13 — on a phone the Dnes card already shows the three rings, so the cards under it
// default to the numbers it does not show
const DEFAULT_TODAY = ["week", "hrv", "rhr", "sleep"]
// v0.9.0 — the single-night "Regenerace" card is gone; a saved choice of it shows Připravenost
const RAIL_RENAMED: Record<string, string> = { recovery: "readiness" }
const migrateRail = (ids: string[]) => [...new Set(ids.map((x) => RAIL_RENAMED[x] ?? x))]
const fmt1 = (v: number | null | undefined) => (v == null ? "—" : String(Math.round(v * 10) / 10).replace(".", ","))

// One copy of the saved choices for both places (on a wide screen both are on the page).
type Where = "rail" | "today"
type Choice = { uid: string; rail: string[]; today: string[] | null }
let choice: Choice | null = null
let choiceFor = ""
const choiceSubs = new Set<() => void>()
const choiceEmit = () => choiceSubs.forEach((f) => f())
const choiceSub = (f: () => void) => { choiceSubs.add(f); return () => { choiceSubs.delete(f) } }
function loadChoice(uid: string) {
  if (!uid || choiceFor === uid) return
  choiceFor = uid
  choice = null
  api.getSettings().then((st: any) => {
    choice = {
      uid,
      rail: Array.isArray(st?.rail_cards) && st.rail_cards.length ? migrateRail(st.rail_cards) : DEFAULT_RAIL,
      // null = never chosen (the default); [] = the runner hid them all
      today: Array.isArray(st?.today_cards) ? migrateRail(st.today_cards) : null,
    }
  }).catch(() => { choice = { uid, rail: DEFAULT_RAIL, today: null } }).finally(choiceEmit)
}
/** [the chosen ids (null while loading), save, whether it is the untouched default] */
function useCardChoice(where: Where): [string[] | null, (next: string[]) => void, boolean] {
  const { me } = useApp()
  const uid = String(me?.id ?? "")
  useEffect(() => loadChoice(uid), [uid])
  const c = useSyncExternalStore(choiceSub, () => choice)
  const save = (next: string[]) => {
    choice = { ...(choice || { uid, rail: DEFAULT_RAIL, today: null }), [where]: next }
    choiceEmit()
    api.patchSettings(where === "rail" ? { rail_cards: next } : { today_cards: next }).catch(() => {})
  }
  if (!c || c.uid !== uid) return [null, save, false]
  const v = c[where]
  return [v ?? (where === "rail" ? DEFAULT_RAIL : DEFAULT_TODAY), save, v == null]
}

function useRailCards(): RailCard[] {
  const { boot } = useApp()
  const a = boot?.assessment
  const rcv = a?.rcv
  const L = a?.loadDetail
  const tierCol = (v: number) => (v >= 25 ? C.alert : v >= 12 ? C.watch : C.ok)
  // UX audit F01 — no run or night yet: no "0 /100 pod prahem" cards
  const none = dataStage(boot) === "none"
  return useMemo(() => none ? [] : [
    { id: "week", label: "Tento týden", to: "/app/load", Icon: TrendingUp, render: () => L?.weekKm == null ? null : ({ value: fmt1(L.weekKm), unit: "km", sub: `posledních 7 dní ${fmt1(L.runKm7)} km` }) },
    { id: "load", label: "Zátěž", to: "/app/load", Icon: Zap, render: () => a?.load == null ? null : ({ value: String(a.load), unit: "/100", sub: a.load >= 25 ? "nad prahem 25" : "pod prahem 25", col: a.load >= 25 ? C.alert : C.load, pct: a.load }) },
    { id: "mech", label: "Mechanika", to: "/app/mechanics", Icon: Footprints, render: () => a?.mech == null ? null : ({ value: String(a.mech), unit: "/100", sub: a.mech >= 25 ? "drift nad prahem" : "drží na normě", col: tierCol(a.mech), pct: a.mech }) },
    { id: "hrv", label: "HRV", to: "/app/load", Icon: HeartPulse, render: () => rcv?.hrv?.now == null ? null : ({ value: fmt1(rcv.hrv.now), unit: "ms", sub: `obvykle ${fmt1(rcv.hrv.base)} ms`, col: (rcv.hrv.z ?? 0) <= -1 ? C.alert : (rcv.hrv.z ?? 0) < -0.3 ? C.watch : C.ok }) },
    { id: "rhr", label: "Klidový tep", to: "/app/load", Icon: Activity, render: () => rcv?.rhr?.now == null ? null : ({ value: fmt1(rcv.rhr.now), unit: "tep/min", sub: `obvykle ${fmt1(rcv.rhr.base)}`, col: (rcv.rhr.z ?? 0) >= 1.2 ? C.alert : (rcv.rhr.z ?? 0) > 0.5 ? C.watch : C.ok }) },
    { id: "sleep", label: "Spánek", to: "/app/load", Icon: Moon, render: () => rcv?.sleep?.now == null ? null : ({ value: fmt1(rcv.sleep.now), unit: "h", sub: `obvykle ${fmt1(rcv.sleep.base)} h`, col: (rcv.sleep.debt || 0) >= 4 ? C.alert : (rcv.sleep.debt || 0) >= 1 ? C.watch : C.ok }) },
    { id: "readiness", label: "Připravenost", to: "/app/today", Icon: Gauge, render: () => { const rd = a?.readiness ?? a?.capacity?.readiness; if (!rd || rd.known === false) return null; const p = readinessPct(rd); return { value: String(p), unit: "%", sub: rd.label || "dnešní stropy kapacity", col: readinessCol(p), pct: p } } },
    { id: "race", label: "Další závod", to: "/app/training", Icon: Flag, render: () => !a?.races?.next ? null : ({ value: a.races.next.daysTo === 0 ? "dnes" : `za ${a.races.next.daysTo} d`, sub: `${a.races.next.name || (a.races.next.priority === "A" ? "Cílový závod" : "Závod")} · ${a.races.next.date?.slice(8, 10).replace(/^0/, "")}. ${a.races.next.date?.slice(5, 7).replace(/^0/, "")}.` }) },
  ], [a, rcv, L, none])
}

/** Show / hide the cards and put them in order (arrows: a list of at most eight needs no drag). */
function CardEditor({ cards, chosen, onChange, hint }: { cards: RailCard[]; chosen: string[]; onChange: (next: string[]) => void; hint: string }) {
  const ids = chosen.filter((id) => cards.some((c) => c.id === id))
  const on = ids.map((id) => cards.find((c) => c.id === id)!)
  const off = cards.filter((c) => !ids.includes(c.id))
  const move = (i: number, d: number) => {
    const n = [...ids]
    ;[n[i], n[i + d]] = [n[i + d], n[i]]
    onChange(n)
  }
  const arrow = "grid size-7 place-items-center rounded-full text-fg-2 hover:bg-white/[.08] hover:text-fg disabled:opacity-25 disabled:hover:bg-transparent"
  return (
    <div className="grid gap-1" data-testid="card-editor">
      <p className="mb-1 text-[11.5px] leading-[1.45] text-fg-3">{hint}</p>
      {on.map((c, i) => (
        <div key={c.id} className="flex items-center gap-1.5 text-[13px] text-fg-soft">
          <span className="flex min-w-0 flex-1 items-center gap-2"><c.Icon className="size-4 shrink-0 text-fg-3" aria-hidden /><span className="truncate">{c.label}</span></span>
          <button type="button" className={arrow} disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Posunout výš: ${c.label}`}><ChevronUp className="size-4" aria-hidden /></button>
          <button type="button" className={arrow} disabled={i === on.length - 1} onClick={() => move(i, 1)} aria-label={`Posunout níž: ${c.label}`}><ChevronDown className="size-4" aria-hidden /></button>
          <span className="ml-1"><Switch checked onChange={() => onChange(ids.filter((x) => x !== c.id))} label={c.label} /></span>
        </div>
      ))}
      {off.length > 0 && on.length > 0 && <span className="my-1 border-t border-white/[.07]" />}
      {off.map((c) => (
        <div key={c.id} className="flex items-center gap-1.5 text-[13px] text-fg-3">
          <span className="flex min-w-0 flex-1 items-center gap-2"><c.Icon className="size-4 shrink-0" aria-hidden /><span className="truncate">{c.label}</span></span>
          <span className="ml-1"><Switch checked={false} onChange={() => onChange([...ids, c.id])} label={c.label} /></span>
        </div>
      ))}
    </div>
  )
}

const isMetric = (id: string): id is MetricId => (METRIC_IDS as readonly string[]).includes(id)

export function StatRail() {
  const { boot } = useApp()
  const nav = useNavigate()
  const cards = useRailCards()
  const [chosen, save] = useCardChoice("rail")
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState<MetricId | null>(null)
  const a = boot?.assessment
  const q = a?.quadrant ? QUAD[a.quadrant] : null
  const qCol = a?.quadrant === "critical" ? C.alert : a?.quadrant === "overreaching" ? C.watch : a?.quadrant === "silent" ? C.self : C.ok
  const list = (chosen || DEFAULT_RAIL).map((id) => cards.find((c) => c.id === id)).filter(Boolean) as RailCard[]
  const trends = useTileTrends(list.map((c) => c.id))
  return (
    <aside className="sticky top-[88px] hidden max-h-[calc(100dvh-104px)] self-start overflow-y-auto pb-6 xl:block" aria-label="Přehled">
      <div className="mb-3 flex items-center justify-between gap-2">
        {q ? (
          <span className="flex min-w-0 items-center gap-2 text-[12px] font-bold" style={{ color: qCol }}>
            <i className="size-2 shrink-0 rounded-full" style={{ background: qCol }} />
            <span className="truncate">{q.t}</span>
          </span>
        ) : <span className="t-label">Přehled</span>}
        <button type="button" onClick={() => setEditing((v) => !v)} aria-expanded={editing}
          className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-bold text-accent hover:bg-accent/10">
          <Pencil className="size-3.5" aria-hidden />{editing ? "Hotovo" : "Upravit"}
        </button>
      </div>
      {editing && (
        <div className="nest mb-3 p-3">
          <CardEditor cards={cards} chosen={chosen || DEFAULT_RAIL} onChange={save}
            hint="Vyberte karty, které chcete mít vpravo, a šipkami je seřaďte. Uloží se k vašemu účtu." />
        </div>
      )}
      <div className="grid gap-3">
        {list.map((c) => {
          const v = c.render()
          return (
            <button key={c.id} type="button" onClick={() => (isMetric(c.id) ? setOpen(c.id) : nav(c.to))} data-testid={`rail-${c.id}`}
              className="card group/rc p-3.5 text-left transition hover:-translate-y-0.5 hover:border-info/45 hover:shadow-[0_14px_34px_rgb(0_0_0_/_0.35)]">
              <span className="flex items-center justify-between gap-2">
                <span className="t-label">{c.label}</span>
                <c.Icon className="size-4 text-fg-3 transition group-hover/rc:text-fg-2" aria-hidden />
              </span>
              {v ? (
                <>
                  <span className="mt-2 flex items-end justify-between gap-3">
                    <span className="t-num block whitespace-nowrap text-[28px] leading-none" style={{ color: v.col || C.fg }}>
                      {v.value}{v.unit && <small className="ml-1 text-[13px] font-semibold tracking-normal text-fg-3">{v.unit}</small>}
                    </span>
                    <MiniTrend vals={trends[c.id]} className="mb-0.5 w-[92px] shrink-0" />
                  </span>
                  {v.pct != null && <span className="mt-2.5 block h-1.5 rounded-full bg-white/[.08]"><i className="block h-full rounded-full" style={{ width: `${Math.max(3, Math.min(100, v.pct))}%`, background: v.col || C.info }} /></span>}
                  {v.sub && <span className="mt-2 block truncate text-[12px] text-fg-2">{v.sub}</span>}
                </>
              ) : <span className="mt-2 block text-[12px] text-fg-3">Zatím bez dat</span>}
            </button>
          )
        })}
        {!list.length && <p className="text-[12px] text-fg-3">Žádné karty — přidejte je přes Upravit.</p>}
      </div>
      {open && <MetricSheet id={open} onClose={() => setOpen(null)} />}
    </aside>
  )
}

/** v0.12.13 — Moje čísla: the runner's chosen numbers under the Dnes card on a phone or tablet
 *  (the wide screen has the rail). Small tiles; a tap opens the number's trend. */
export function TodayNumbers() {
  const nav = useNavigate()
  const cards = useRailCards()
  const [chosen, save, isDefault] = useCardChoice("today")
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState<MetricId | null>(null)
  // the untouched default shows only the numbers this runner has (no "Zatím bez dat" tiles
  // for a runner without nights from a watch); a saved choice shows what was chosen
  const list = ((chosen || []).map((id) => cards.find((c) => c.id === id)).filter(Boolean) as RailCard[])
    .filter((c) => !isDefault || c.render() != null)
  const trends = useTileTrends(list.map((c) => c.id))
  if (!cards.length || chosen === null) return null
  return (
    <section className="mt-5 xl:hidden" aria-label="Moje čísla" data-testid="today-numbers">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="t-label">Moje čísla</span>
        <button type="button" onClick={() => setEditing(true)}
          className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-bold text-accent hover:bg-accent/10">
          <Pencil className="size-3.5" aria-hidden />Upravit
        </button>
      </div>
      {list.length ? (
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          {list.map((c) => {
            const v = c.render()
            return (
              <button key={c.id} type="button" onClick={() => (isMetric(c.id) ? setOpen(c.id) : nav(c.to))} data-testid={`num-${c.id}`}
                className="card min-w-0 p-3 text-left transition active:scale-[.98] hover:border-info/45">
                <span className="flex items-center justify-between gap-2">
                  <span className="t-label truncate">{c.label}</span>
                  <c.Icon className="size-3.5 shrink-0 text-fg-3" aria-hidden />
                </span>
                {v ? (
                  <>
                    <span className="t-num mt-1.5 block whitespace-nowrap text-[22px] leading-none" style={{ color: v.col || C.fg }}>
                      {v.value}{v.unit && <small className="ml-1 text-[11px] font-semibold tracking-normal text-fg-3">{v.unit}</small>}
                    </span>
                    <MiniTrend vals={trends[c.id]} className="mt-2" />
                    {v.sub && <span className="mt-1.5 block truncate text-[11px] text-fg-3">{v.sub}</span>}
                  </>
                ) : <span className="mt-1.5 block text-[11px] text-fg-3">Zatím bez dat</span>}
              </button>
            )
          })}
        </div>
      ) : <p className="text-[12px] text-fg-3">Žádná čísla — přidejte je přes Upravit.</p>}
      <Sheet open={editing} onClose={() => setEditing(false)}>
        <Label>Moje čísla</Label>
        <div className="mt-3">
          <CardEditor cards={cards} chosen={list.map((c) => c.id)} onChange={save}
            hint="Vyberte čísla pod kartou Dnes a šipkami je seřaďte. Klepnutím na číslo uvidíte jeho vývoj." />
        </div>
      </Sheet>
      {open && <MetricSheet id={open} onClose={() => setOpen(null)} />}
    </section>
  )
}
