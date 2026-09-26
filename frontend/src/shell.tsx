// App shell pieces (redesign v2 §3 + OPT-5): nav icons, desktop sidebar and the
// customisable desktop stat rail. Behaviour of the existing shell (Topbar,
// AtlasNav, Check-in) lives in App.tsx; this file only adds the desktop layout.
import { useEffect, useMemo, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router"
import {
  Activity, Database, Flag, Footprints, Gauge, HeartHandshake, HeartPulse, House, Moon, NotebookPen, Pencil, SlidersHorizontal, Target, TrendingUp, Zap,
  type LucideIcon,
} from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { QUAD } from "@/lib"
import { C } from "@/tokens"
import { Switch } from "@/ui"
import { readinessCol, readinessPct } from "@/capacity"

export const NAV_ICON: Record<string, LucideIcon> = {
  today: House, training: Target, post: NotebookPen, mechanics: Footprints, load: Activity, messages: HeartHandshake,
}

export function Mark({ size = 36 }: { size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-xl bg-ink" style={{ width: size, height: size }}>
      <svg viewBox="0 0 64 64" style={{ width: size * 0.78, height: size * 0.78 }} aria-hidden="true">
        <circle cx="32" cy="32" r="28" fill="none" stroke={C.accent} strokeWidth="2" strokeOpacity=".5" />
        <path d="M12 44 C12 34 19 13 37 13 C49 13 56 23 56 34 C56 46 45 54 34 54 C24 54 14 52 12 44 Z" fill={C.accent} />
        <path d="M27 42 C27 36 31 23 41 23 C48 23 52 29 52 35 C52 42 45 47 38 47 C31 47 28 46 27 42 Z" fill={C.ink} />
      </svg>
    </span>
  )
}

/* ---------------- Desktop sidebar (lg+) ---------------- */
export function Sidebar({ items }: { items: [string, string][] }) {
  const { pathname } = useLocation()
  const link = (to: string, label: string, Icon: LucideIcon, key: string) => {
    const on = pathname === to
    return (
      <Link key={key} to={to} aria-current={on ? "page" : undefined}
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
        došlap
      </Link>
      <nav className="grid gap-1">{items.map(([id, label]) => link(`/app/${id}`, label, NAV_ICON[id] || House, id))}</nav>
      <div className="mt-6 border-t border-white/[.07] pt-4">
        <p className="t-label mb-2 px-3 !text-fg-3">Nastavení</p>
        <nav className="grid gap-1">
          {link("/data", "Data a připojení", Database, "data")}
          {link("/engine", "Citlivostní analýza", SlidersHorizontal, "engine")}
        </nav>
      </div>
    </aside>
  )
}

/* ---------------- Desktop stat rail (xl+) ---------------- */
type RailCard = { id: string; label: string; to: string; Icon: LucideIcon; render: () => { value: string; unit?: string; sub?: string; col?: string; pct?: number } | null }
const DEFAULT_RAIL = ["recovery", "week", "load", "mech"]
const fmt1 = (v: number | null | undefined) => (v == null ? "—" : String(Math.round(v * 10) / 10).replace(".", ","))

function useRailCards(): RailCard[] {
  const { boot } = useApp()
  const a = boot?.assessment
  const rcv = a?.rcv
  const L = a?.loadDetail
  const tierCol = (v: number) => (v >= 25 ? C.alert : v >= 12 ? C.watch : C.ok)
  return useMemo(() => [
    { id: "recovery", label: "Regenerace přes noc", to: "/app/today", Icon: HeartPulse, render: () => rcv?.score == null ? null : ({ value: String(rcv.score), unit: "/100", sub: rcv.scoreLabel, col: rcv.score >= 67 ? C.ok : rcv.score >= 34 ? C.watch : C.alert, pct: rcv.score }) },
    { id: "week", label: "Tento týden", to: "/app/load", Icon: TrendingUp, render: () => L?.weekKm == null ? null : ({ value: fmt1(L.weekKm), unit: "km", sub: `posledních 7 dní ${fmt1(L.runKm7)} km` }) },
    { id: "load", label: "Zátěž", to: "/app/load", Icon: Zap, render: () => a?.load == null ? null : ({ value: String(a.load), unit: "/100", sub: a.load >= 25 ? "nad prahem 25" : "pod prahem 25", col: a.load >= 25 ? C.alert : C.load, pct: a.load }) },
    { id: "mech", label: "Mechanika", to: "/app/mechanics", Icon: Footprints, render: () => a?.mech == null ? null : ({ value: String(a.mech), unit: "/100", sub: a.mech >= 25 ? "drift nad prahem" : "drží na normě", col: tierCol(a.mech), pct: a.mech }) },
    { id: "hrv", label: "HRV", to: "/app/load", Icon: HeartPulse, render: () => rcv?.hrv?.now == null ? null : ({ value: fmt1(rcv.hrv.now), unit: "ms", sub: `obvykle ${fmt1(rcv.hrv.base)} ms`, col: (rcv.hrv.z ?? 0) <= -1 ? C.alert : (rcv.hrv.z ?? 0) < -0.3 ? C.watch : C.ok }) },
    { id: "rhr", label: "Klidový tep", to: "/app/load", Icon: Activity, render: () => rcv?.rhr?.now == null ? null : ({ value: fmt1(rcv.rhr.now), unit: "tep/min", sub: `obvykle ${fmt1(rcv.rhr.base)}`, col: (rcv.rhr.z ?? 0) >= 1.2 ? C.alert : (rcv.rhr.z ?? 0) > 0.5 ? C.watch : C.ok }) },
    { id: "sleep", label: "Spánek", to: "/app/load", Icon: Moon, render: () => rcv?.sleep?.now == null ? null : ({ value: fmt1(rcv.sleep.now), unit: "h", sub: `obvykle ${fmt1(rcv.sleep.base)} h`, col: (rcv.sleep.debt || 0) >= 4 ? C.alert : (rcv.sleep.debt || 0) >= 1 ? C.watch : C.ok }) },
    { id: "readiness", label: "Připravenost", to: "/app/training", Icon: Gauge, render: () => !a?.capacity?.readiness ? null : (() => { const p = readinessPct(a.capacity.readiness); return { value: String(p), unit: "%", sub: "dnešní stropy kapacity", col: readinessCol(p), pct: p } })() },
    { id: "race", label: "Další závod", to: "/app/training", Icon: Flag, render: () => !a?.races?.next ? null : ({ value: a.races.next.daysTo === 0 ? "dnes" : `za ${a.races.next.daysTo} d`, sub: `${a.races.next.name || (a.races.next.priority === "A" ? "Cílový závod" : "Závod")} · ${a.races.next.date?.slice(8, 10).replace(/^0/, "")}. ${a.races.next.date?.slice(5, 7).replace(/^0/, "")}.` }) },
  ], [a, rcv, L])
}

export function StatRail() {
  const { boot } = useApp()
  const nav = useNavigate()
  const cards = useRailCards()
  const [chosen, setChosen] = useState<string[] | null>(null)
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    let alive = true
    api.getSettings().then((s: any) => alive && setChosen(Array.isArray(s?.rail_cards) && s.rail_cards.length ? s.rail_cards : DEFAULT_RAIL)).catch(() => alive && setChosen(DEFAULT_RAIL))
    return () => { alive = false }
  }, [])
  const save = (next: string[]) => {
    setChosen(next)
    api.patchSettings({ rail_cards: next }).catch(() => {})
  }
  const toggle = (id: string, on: boolean) => {
    const cur = chosen || DEFAULT_RAIL
    save(on ? [...cur.filter((x) => x !== id), id] : cur.filter((x) => x !== id))
  }
  const a = boot?.assessment
  const q = a?.quadrant ? QUAD[a.quadrant] : null
  const qCol = a?.quadrant === "critical" ? C.alert : a?.quadrant === "overreaching" ? C.watch : a?.quadrant === "silent" ? C.self : C.ok
  const list = (chosen || DEFAULT_RAIL).map((id) => cards.find((c) => c.id === id)).filter(Boolean) as RailCard[]
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
        <div className="nest mb-3 grid gap-2 p-3">
          <p className="text-[11px] text-fg-3">Vyberte karty, které chcete mít vpravo. Uloží se k vašemu účtu.</p>
          {cards.map((c) => (
            <label key={c.id} className="flex items-center justify-between gap-2 text-[13px] text-fg-soft">
              <span className="flex items-center gap-2"><c.Icon className="size-4 text-fg-3" aria-hidden />{c.label}</span>
              <Switch checked={(chosen || DEFAULT_RAIL).includes(c.id)} onChange={(v) => toggle(c.id, v)} label={c.label} />
            </label>
          ))}
        </div>
      )}
      <div className="grid gap-3">
        {list.map((c) => {
          const v = c.render()
          return (
            <button key={c.id} type="button" onClick={() => nav(c.to)}
              className="card group/rc p-3.5 text-left transition hover:-translate-y-0.5 hover:border-info/45 hover:shadow-[0_14px_34px_rgb(0_0_0_/_0.35)]">
              <span className="flex items-center justify-between gap-2">
                <span className="t-label">{c.label}</span>
                <c.Icon className="size-4 text-fg-3 transition group-hover/rc:text-fg-2" aria-hidden />
              </span>
              {v ? (
                <>
                  <span className="t-num mt-2 block text-[28px] leading-none" style={{ color: v.col || C.fg }}>
                    {v.value}{v.unit && <small className="ml-1 text-[13px] font-semibold tracking-normal text-fg-3">{v.unit}</small>}
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
    </aside>
  )
}
