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
