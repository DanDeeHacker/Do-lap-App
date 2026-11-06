// feedback #231 — "on tap, a list of the latest activities and their basic stats": the detail of the
// running-statistics cards (Moje čísla) and of Kilometry týdně. Only what the activities already hold.
import { Link } from "react-router"
import { ChevronRight } from "lucide-react"
import { useApp } from "@/store"
import { Label, Sheet } from "@/ui"
import { hm, paceStr, recentActivities, sportCs } from "@/runstats"

const when = (s: string) => new Date(String(s).slice(0, 10) + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })

export function RecentActivities({ onClose }: { onClose: () => void }) {
  const { boot } = useApp()
  const list = recentActivities(boot?.activities || [])
  if (!list.length) return null
  return (
    <div className="mt-4" data-testid="recent-activities">
      <Label>Poslední aktivity</Label>
      <ul className="mt-1.5 divide-y divide-white/[.07]">
        {list.map((x) => {
          const run = !x.sport || x.sport === "running"
          const bits = [x.distance_km ? `${x.distance_km.toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} km` : null, x.duration_min ? hm(x.duration_min) : null,
            run && paceStr(x.pace_s_km) ? `${paceStr(x.pace_s_km)}/km` : null, x.avg_hr ? `${Math.round(x.avg_hr)} tep/min` : null, x.rpe ? `RPE ${x.rpe}` : null].filter(Boolean)
          const body = (
            <>
              <span className="w-11 shrink-0 text-[12px] text-fg-3">{when(x.started_at)}</span>
              <span className="min-w-0 flex-1">
                <b className="block truncate text-[13px] font-bold text-fg">{x.title || sportCs(x.sport)}</b>
                <span className="block truncate text-[12px] text-fg-2">{bits.join(" · ")}</span>
              </span>
              {run && <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />}
            </>
          )
          return (
            <li key={x.id ?? x.started_at}>
              {run && x.id != null
                ? <Link to={`/app/post/${x.id}`} onClick={onClose} className="flex items-center gap-2.5 py-2 hover:bg-white/[.03]">{body}</Link>
                : <div className="flex items-center gap-2.5 py-2">{body}</div>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** The sheet of a running-statistics card: its number, then the latest activities. */
export function RunStatSheet({ label, value, unit, sub, onClose }: { label: string; value?: string; unit?: string; sub?: string; onClose: () => void }) {
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="runstat-sheet">
        <Label>{label}</Label>
        {value == null ? <b className="mt-1.5 block text-[15px] font-semibold text-fg-3">Zatím bez dat</b>
          : <b className="t-num mt-1.5 block text-[38px] leading-none text-fg">{value}{unit && <small className="ml-1 text-[14px] font-semibold text-fg-3">{unit}</small>}</b>}
        {sub && <p className="mt-1 text-[12.5px] text-fg-2">{sub}</p>}
        <RecentActivities onClose={onClose} />
        <Link to="/app/load" onClick={onClose} className="mt-3 inline-flex items-center gap-1 text-[13px] font-bold text-accent">{`Více na stránce Zátěž`}<ChevronRight className="size-4" aria-hidden /></Link>
      </div>
    </Sheet>
  )
}
