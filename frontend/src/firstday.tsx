// UX audit F01/F04/F19 — what the app knows about the runner yet, and the first-day
// screens. Before the first run or night the tabs show no scores, risk words or plans
// (a new account used to read readiness 100 %, Skóre 100 and "nízké riziko"); in the
// first two weeks the plan is labelled a general start, because the norms and the
// capacity are still starting values.
import { Link } from "react-router"
import { Compass, PlugZap } from "lucide-react"
import { useApp } from "@/store"
import { useOnboarding } from "@/onboarding"

export type DataStage = "none" | "early" | "ok"

const EARLY_DAYS = 14

const hasNight = (m: any) => m.hrv_ms != null || m.resting_hr != null || m.sleep_h != null

export function dataStage(boot: any): DataStage {
  if (!boot) return "ok"
  const acts = ((boot.activities || []) as any[]).filter((a) => !a.excluded)
  const nights = ((boot.daily_metrics || []) as any[]).filter(hasNight)
  if (!acts.length && !nights.length) return "none"
  const first = [...acts.map((a) => String(a.started_at || "").slice(0, 10)), ...nights.map((m) => String(m.date || "").slice(0, 10))]
    .filter(Boolean).sort()[0]
  return first && Date.now() - Date.parse(first + "T00:00:00") < EARLY_DAYS * 864e5 ? "early" : "ok"
}

export function useDataStage(): DataStage {
  return dataStage(useApp().boot)
}

/** Whether a data source is set up: Garmin login or an imported file. */
export function useConnected(): boolean {
  const { boot } = useApp()
  return boot?.integration?.status === "connected" || dataStage(boot) !== "none"
}

/** The two ways forward on a first-day screen: connect a watch, or see how the app works. */
export function FirstSteps({ className = "mt-4" }: { className?: string }) {
  const { viewing, touring } = useApp()
  const ob = useOnboarding()
  if (viewing || touring) return null
  const tourLeft = !!ob.state && ob.state.active && !ob.state.completed && ob.state.steps.some((s) => s.id === "tutorial" && !s.done)
  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      <Link to="/data" className="btn btn-primary" data-testid="connect-watch"><PlugZap className="size-4" aria-hidden />Připojit hodinky</Link>
      {tourLeft && (
        <button type="button" onClick={ob.openCard} className="btn btn-outline"><Compass className="size-4" aria-hidden />Jak aplikace funguje</button>
      )}
    </div>
  )
}

/** A tab's empty state before the first data: what will appear here and the way to get it. */
export function NoData({ kicker, title, children }: { kicker: string; title: string; children: React.ReactNode }) {
  return (
    <section className="card p-5 md:p-6" data-testid="no-data">
      <p className="t-label">{kicker}</p>
      <h1 className="mt-1 font-serif text-[26px] leading-tight tracking-[-.02em] text-fg md:text-[30px]">{title}</h1>
      <p className="mt-2 max-w-xl text-[14px] leading-6 text-fg-2">{children}</p>
      <FirstSteps />
    </section>
  )
}

/** First two weeks: the plan and limits are a general start, not yet the runner's own. */
export function EarlyNote({ className = "" }: { className?: string }) {
  return (
    <p className={`nest px-3.5 py-2.5 text-[12.5px] leading-5 text-fg-2 ${className}`} data-testid="early-note">
      <b className="text-fg">Obecné doporučení pro začátek.</b> Vaši normu a kapacitu teprve poznáváme. Rozsahy jsou opatrný počáteční odhad a během 2–4 týdnů se zpřesní podle vašich běhů a nocí.
    </p>
  )
}
