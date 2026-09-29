// Design tokens for inline styles, SVG fills and hex-alpha concatenation
// (`${C.alert}1f`). Mirrors the @theme block in index.css — change both together.
export const C = {
  bg: "#061010",
  ink: "#071313",
  panel: "#0c201d",
  panel2: "#102724",
  raised: "#17302a",
  fg: "#eef6f2",
  fgSoft: "#cfe0d9",
  fg2: "#a9bfb7",
  fg3: "#7f958e",
  fg4: "#5f7268",
  accent: "#c7ff54",
  ok: "#4fd69c",
  info: "#6ce6d3",
  watch: "#f2c46d",
  alert: "#f0795a",
  load: "#8a95ff",
  self: "#7fb0d6",
  alertSoft: "#ffc1ab",
  watchSoft: "#f6e2b3",
} as const

export type Tone = "ok" | "watch" | "alert" | "muted" | "info" | "load"
export const toneColor = (t: Tone | string): string =>
  t === "ok" ? C.ok : t === "watch" ? C.watch : t === "alert" ? C.alert : t === "info" ? C.info : t === "load" ? C.load : C.fg3

// Feedback railway#108 — one colour rule for the Dnes rings (Skóre, Regenerace,
// Připravenost, Příznaky; Zátěž and Mechanika keep their own). A higher-is-better
// score is green above 70 and red below 40. Příznaky grows with symptoms, so the
// same bands are mirrored there: green below 30, red above 60.
export const RING_GREEN = 70
export const RING_RED = 40
export const goodCol = (v: number | null | undefined): string =>
  v == null ? C.fg3 : v > RING_GREEN ? C.ok : v >= RING_RED ? C.watch : C.alert
export const badCol = (v: number | null | undefined): string =>
  v == null ? C.fg3 : v < 100 - RING_GREEN ? C.ok : v <= 100 - RING_RED ? C.watch : C.alert
