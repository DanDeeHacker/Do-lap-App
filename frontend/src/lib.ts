// Formatting + small helpers, ported from core.js.

export const r1 = (n: number | null | undefined) => (n == null ? null : Math.round(n * 10) / 10)
export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

// Czech decimal comma for a number (or numeric text) exactly as the API rounded it:
// 56.3 → "56,3", -0.5 → "−0,5"; null → dash
export const cz = (v: number | string | null | undefined, dash = "—") =>
  v == null || v === "" ? dash : String(v).replace(/(\d)\.(\d)/g, "$1,$2").replace(/(^|[^\w\d.,])-(?=\d)/g, "$1−")

// Feedback railway#111 — a signal's effect as the percentage points it takes off the
// overall Skóre (shown as 100 − risk): whole points from 1 up, one decimal below 1.
export const impactNum = (v: number | null | undefined) => {
  const x = Math.abs(v || 0)
  if (x === 0) return "0"
  if (x < 0.05) return "<0,1"
  return x < 1 ? x.toFixed(1).replace(".", ",") : String(Math.round(x))
}
// UX audit F10 — written as "bodů" (points off the Skóre): "p. b." also meant a measured
// change (contact balance) in the same row
const bodu = (n: string) => (/[,<]/.test(n) ? "bodu" : n === "1" ? "bod" : n === "2" || n === "3" || n === "4" ? "body" : "bodů")
export const fmtImpact = (v: number | null | undefined, unit?: string) => {
  const n = impactNum(v)
  const u = unit ?? ` ${bodu(n)}`
  return n === "0" ? `0${u}` : `−${n}${u}`
}
// axis points → Skóre percentage points with the assessment's per-axis scale
export const toImpact = (pts: number | null | undefined, scale: number | null | undefined) => (pts || 0) * (scale ?? 0)

export const initials = (name?: string) =>
  (name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("") || "?"

export const fmtD = (iso?: string) => {
  if (!iso) return "—"
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso)
  return d.toLocaleDateString("cs-CZ", { day: "numeric", month: "short" })
}
export const fmtDLong = (iso?: string) => {
  if (!iso) return "—"
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso)
  return d.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
}
export const fmtDT = (iso?: string) => {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
}
export const fmtSlot = (iso?: string) => {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("cs-CZ", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
}

export const czk = (n?: number | null) => (n == null ? "—" : new Intl.NumberFormat("cs-CZ").format(n) + " Kč")

export const paceStr = (sPerKm?: number | null) => {
  // Only null/undefined/NaN is "missing" — a genuine 0 should read "0:00", not "—".
  if (sPerKm == null || !Number.isFinite(sPerKm)) return "—"
  const t = Math.round(sPerKm) // round the total first — 359.6 s is 6:00, not "5:60"
  const m = Math.floor(t / 60)
  const s = t % 60
  return `${m}:${String(s).padStart(2, "0")}`
}

export const sgn = (n?: number | null) => (n == null ? "—" : n > 0 ? `+${cz(n)}` : cz(n))

// UX audit F07 — each state says in plain words what it means for the runner
export const QUAD: Record<string, { t: string; d: string }> = {
  stable: { t: "Stabilní", d: "Zátěž i technika běhu sedí na vaší normě." },
  overreaching: { t: "Přetížení", d: "Zátěž vyskočila nad to, co jste v posledních týdnech zvládali. Technika zatím drží." },
  silent: { t: "Tichý drift", d: "Technika běhu se mění, i když to možná necítíte. Bývá to znak únavy, ne předpověď zranění." },
  critical: { t: "Kritická kombinace", d: "Zátěž je nad normou a zároveň se mění technika běhu." },
}
export const TIER: Record<string, string> = { ok: "Nízké riziko", watch: "Sledovat", alert: "Vysoké riziko" }
export const FEEL_LABEL = ["", "špatný", "slabší", "normální", "dobrý", "výborný"]
export const PHASE: Record<string, string> = { offload: "odlehčení", rebuild: "budování", return: "návrat k běhu", prevent: "prevence" }

// Runner-only build: everyone lands on the runner dashboard; non-runner
// accounts are gated in Layout with a "runner-only" notice.
export const roleHome = (_role: string) => "/app/today"

// Czech plural: 1 → one, 2–4 → few, 0 / 5+ → many ("1 běh", "3 běhy", "5 běhů").
export const plural = (n: number, one: string, few: string, many: string) => {
  const a = Math.abs(n)
  return a === 1 ? one : a >= 2 && a <= 4 ? few : many
}

// UX audit F09 — the reasons behind today's plan, the one that decides the day first: on a
// day off the reason for the day off leads (a "nanejvýš krátký volný běh" from an earlier
// rule read as a contradiction above "dnes volno"); the rest are shown folded.
export function leadReasons(type: string | null | undefined, reasons: string[]): [string | null, string[]] {
  if (!reasons.length) return [null, []]
  const off = type === "volno" ? reasons.findIndex((r) => /volno|odpočinek|neběhat|bez běhu/i.test(r)) : -1
  const i = off >= 0 ? off : 0
  return [reasons[i], reasons.filter((_, k) => k !== i)]
}
