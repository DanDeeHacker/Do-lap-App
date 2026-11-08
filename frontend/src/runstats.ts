// feedback #225 (note: basic running statistics in Moje čísla) — this week's totals and the last
// activity, from the activities the app already holds; nothing is computed by the engine.
// A week is Monday to Sunday, as in Kilometry týdně; manually excluded activities do not count.
const iso = (d: Date) => d.toLocaleDateString("sv-SE")
const monday = (s: string) => { const d = new Date(s.slice(0, 10) + "T12:00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d) }
/** one floor of stairs is taken as 3 m of climb */
export const FLOOR_M = 3

export type WeekStats = { allMin: number; runMin: number; ascent: number; descent: number; floors: number }

export function weekStats(acts: any[], today = iso(new Date())): WeekStats {
  const from = monday(today)
  let allMin = 0, runMin = 0, ascent = 0, descent = 0
  for (const x of acts || []) {
    if (x.excluded || !x.started_at || String(x.started_at).slice(0, 10) < from) continue
    const min = x.duration_min || 0
    allMin += min
    if (!x.sport || x.sport === "running") { runMin += min; ascent += x.ascent_m || 0; descent += x.descent_m || 0 }
  }
  return { allMin, runMin, ascent: Math.round(ascent), descent: Math.round(descent), floors: Math.round(ascent / FLOOR_M) }
}

/** the newest activity (any sport) that is not excluded */
export function lastActivity(acts: any[]): any | null {
  let best: any = null
  for (const x of acts || []) {
    if (x.excluded || !x.started_at) continue
    if (!best || String(x.started_at) > String(best.started_at)) best = x
  }
  return best
}

/** 95 → "1 h 35 min", 42 → "42 min" */
export function hm(min: number): string {
  const m = Math.round(min)
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`
}

/** seconds per km → "5:07" */
export function paceStr(s: number | null | undefined): string | null {
  if (!s || s <= 0) return null
  const t = Math.round(s)
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`
}

// feedback #231 — the list behind the running-statistics cards: the newest activities that count
// (not excluded), newest first, with the basics the cards already show
const SPORT_CS: Record<string, string> = { running: "běh", cycling: "kolo", swimming: "plavání", strength: "síla", walking: "chůze" }
export const sportCs = (sport: string | null | undefined) => SPORT_CS[sport || "running"] || "jiný sport"

export function recentActivities(acts: any[], n = 7): any[] {
  return (acts || []).filter((x) => !x.excluded && x.started_at)
    .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at))).slice(0, n)
}

// feedback #228-#230 — the same totals per week for the trend in the number's sheet: Monday to
// Sunday, the last `weeks` weeks (the running one last), excluded activities left out, the rules of weekStats
export type WeekKind = "all" | "run" | "ascent"
export function weeklyTotals(acts: any[], weeks: number, kind: WeekKind, today = iso(new Date())): { t: string; v: number }[] {
  const wk = new Map<string, number>()
  for (const x of acts || []) {
    if (x.excluded || !x.started_at) continue
    const run = !x.sport || x.sport === "running"
    if (kind !== "all" && !run) continue
    const m = monday(String(x.started_at))
    wk.set(m, (wk.get(m) || 0) + (kind === "ascent" ? x.ascent_m || 0 : x.duration_min || 0))
  }
  const out: { t: string; v: number }[] = []
  const d = new Date(monday(today) + "T12:00:00")
  for (let k = weeks - 1; k >= 0; k--) { const m = new Date(d); m.setDate(d.getDate() - 7 * k); const t = iso(m); out.push({ t, v: Math.round(wk.get(t) || 0) }) }
  return out
}
