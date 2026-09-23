// Formatting + small helpers, ported from core.js.

export const r1 = (n: number | null | undefined) => (n == null ? null : Math.round(n * 10) / 10)
export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

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
  const m = Math.floor(sPerKm / 60)
  const s = Math.round(sPerKm % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}

export const sgn = (n?: number | null) => (n == null ? "—" : n > 0 ? `+${n}` : String(n))

export const QUAD: Record<string, { t: string; d: string }> = {
  stable: { t: "Stabilní", d: "Zátěž i mechanika sedí na vlastní normě." },
  overreaching: { t: "Přetížení", d: "Zátěž vyskočila, ale technika zatím drží." },
  silent: { t: "Tichý drift", d: "Mechanika se odchyluje od vaší normy — signál únavy/přetížení, ne předpověď zranění." },
  critical: { t: "Kritická kombinace", d: "Zátěž i mechanika se hýbou naráz." },
}
export const TIER: Record<string, string> = { ok: "Nízké riziko", watch: "Sledovat", alert: "Vysoké riziko" }
export const FEEL_LABEL = ["", "špatný", "slabší", "normální", "dobrý", "výborný"]
export const PHASE: Record<string, string> = { offload: "odlehčení", rebuild: "budování", return: "návrat k běhu", prevent: "prevence" }

// Runner-only build: everyone lands on the runner dashboard; non-runner
// accounts are gated in Layout with a "runner-only" notice.
export const roleHome = (_role: string) => "/app/today"
