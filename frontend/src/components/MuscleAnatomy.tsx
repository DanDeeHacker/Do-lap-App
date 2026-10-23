import { useEffect, useState } from "react"
import { C } from "@/tokens"

export type BodyPoint = { region: string; side: string; kind: string }

// Faithful React port of the imported "Male Muscle Anatomy" design
// (imports/index-1.html + script.js + style.css). The imports/ folder is
// read-only, so the interactive behaviour lives here and the styling is ported
// into the dark Motion Atlas theme.
//
// The import ships one overlay image per muscle group, drawn bilaterally on a
// centered full-body figure. To let the user pick a *side*, every limb point is
// mirrored across the centerline and — for muscles — the overlay image is
// clipped to the selected half so only that side lights up red. Tendons / feet
// have no overlay image, so they highlight with a drawn red area instead.

type Kind = "muscle" | "tendon"
type SideLabel = "L" | "P" | "center"

type Def = {
  key: string
  overlay?: string
  top: number
  left: number // for paired defs this is the image-LEFT-side x
  r?: [number, number] // paired: [top, left] of the image-RIGHT point (the drawings aren't mirror-exact)
  title: string
  kind: Kind
  layout: "pair" | "center"
  w?: number
  h?: number
}

type Hotspot = {
  id: string
  overlay?: string
  top: number
  left: number
  title: string
  kind: Kind
  side: SideLabel
  w?: number
  h?: number
}

// Original design canvas from the import (419 × 1024).
const CANVAS_W = 419
const CANVAS_H = 1024

// The figures' midlines (canvas px): the front drawing sits a little right of centre.
const AX = { front: 217, back: 204 } as const

const mirror = (view: "front" | "back", x: number) => Math.round(2 * AX[view] - x)

// Anatomical side for a point, accounting for the mirrored back view.
// Front view: image-left half = figure's RIGHT side; back view: image-left = LEFT.
function anatSide(view: "front" | "back", x: number): "L" | "P" {
  const imageLeft = x < AX[view]
  if (view === "front") return imageLeft ? "P" : "L"
  return imageLeft ? "L" : "P"
}

function build(view: "front" | "back", defs: Def[]): Hotspot[] {
  const out: Hotspot[] = []
  for (const d of defs) {
    if (d.layout === "center") {
      out.push({
        id: d.key,
        overlay: d.overlay,
        top: d.top,
        left: d.left,
        title: d.title,
        kind: d.kind,
        side: "center",
        w: d.w,
        h: d.h,
      })
    } else {
      const pts: [number, number][] = [[d.top, d.left], d.r ?? [d.top, mirror(view, d.left)]]
      for (const [top, x] of pts) {
        const s = anatSide(view, x)
        out.push({
          id: `${d.key}-${s}`,
          overlay: d.overlay,
          top,
          left: x,
          title: `${d.title} (${s})`,
          kind: d.kind,
          side: s,
          w: d.w,
          h: d.h,
        })
      }
    }
  }
  return out
}

const frontDefs: Def[] = [
  // Muscles — paired
  { key: "front-chest", overlay: "front-chest", top: 240, left: 168, title: "Prsní sval", kind: "muscle", layout: "pair", r: [234, 271] },
  { key: "front-biceps", overlay: "front-biceps", top: 312, left: 98, title: "Biceps", kind: "muscle", layout: "pair", r: [302, 337] },
  { key: "front-quads", overlay: "front-quads", top: 627, left: 158, title: "Kvadriceps", kind: "muscle", layout: "pair", r: [629, 277] },
  { key: "front-delts", overlay: "front-delts", top: 227, left: 101, title: "Přední delt", kind: "muscle", layout: "pair", r: [220, 329] },
  { key: "front-forearms", overlay: "front-forearms", top: 392, left: 75, title: "Předloktí", kind: "muscle", layout: "pair", r: [388, 359] },
  { key: "triceps", overlay: "triceps", top: 272, left: 68, title: "Triceps", kind: "muscle", layout: "pair", r: [284, 370] },
  { key: "front-obliques", overlay: "front-obliques", top: 412, left: 153, title: "Šikmé břišní", kind: "muscle", layout: "pair", r: [411, 281] },
  { key: "front-calves", overlay: "front-calves", top: 812, left: 198, title: "Lýtko", kind: "muscle", layout: "pair", r: [800, 243] },
  { key: "side-delt", overlay: "side-delt", top: 218, left: 76, title: "Boční delt", kind: "muscle", layout: "pair", r: [216, 358] },
  { key: "front-adductors", overlay: "front-adductors", top: 536, left: 197, title: "Adduktor", kind: "muscle", layout: "pair", r: [535, 236] },
  { key: "front-hips", overlay: "front-hips", top: 470, left: 144, title: "Ohýbač kyčle", kind: "muscle", layout: "pair", r: [471, 291] },
  { key: "front-traps", overlay: "front-traps", top: 168, left: 168, title: "Horní trapézy", kind: "muscle", layout: "pair", r: [168, 267] },
  // Muscles — central
  { key: "upper-abs", overlay: "upper-abs", top: 318, left: 217, title: "Horní břišní", kind: "muscle", layout: "center" },
  { key: "lower-abs", overlay: "lower-abs", top: 440, left: 217, title: "Dolní břišní", kind: "muscle", layout: "center" },
  // Tendons / úpony — paired
  { key: "f-patellar", top: 757, left: 170, title: "Patelární šlacha", kind: "tendon", layout: "pair", r: [757, 264] },
  { key: "f-quadtendon", top: 708, left: 168, title: "Kvadricepsová šlacha", kind: "tendon", layout: "pair", r: [708, 264] },
  { key: "f-shin", top: 830, left: 166, title: "Tibialis anterior (holeň)", kind: "tendon", layout: "pair", r: [830, 268] },
  { key: "f-groin", top: 497, left: 199, title: "Tříslo / úpon adduktorů", kind: "tendon", layout: "pair", r: [497, 235] },
  { key: "f-hipflexor", top: 455, left: 168, title: "Úpon ohýbačů kyčle", kind: "tendon", layout: "pair", r: [455, 266] },
  { key: "f-elbow", top: 350, left: 92, title: "Šlacha bicepsu (loket)", kind: "tendon", layout: "pair", r: [350, 340] },
  { key: "f-wrist", top: 476, left: 58, title: "Šlachy zápěstí", kind: "tendon", layout: "pair", r: [476, 374] },
  { key: "f-ankle", top: 922, left: 178, title: "Přední hlezenní vazy", kind: "tendon", layout: "pair", r: [922, 258] },
  // Feet — paired
  { key: "f-foot", top: 958, left: 185, title: "Chodidlo – nárt", kind: "tendon", layout: "pair", r: [958, 262], w: 55, h: 45 },
  { key: "f-toes", top: 990, left: 178, title: "Prsty / metatarzy", kind: "tendon", layout: "pair", r: [990, 272], w: 45, h: 32 },
]

const backDefs: Def[] = [
  // Muscles — paired
  { key: "back-lats", overlay: "back-lats", top: 336, left: 157, title: "Zádové svaly (lats)", kind: "muscle", layout: "pair", r: [336, 253] },
  { key: "back-img3", overlay: "back-img3", top: 503, left: 165, title: "Hýždě (gluteus)", kind: "muscle", layout: "pair", r: [493, 245] },
  { key: "back-img4", overlay: "back-img4", top: 654, left: 145, title: "Hamstring", kind: "muscle", layout: "pair", r: [642, 249] },
  { key: "back-img5", overlay: "back-img5", top: 807, left: 133, title: "Lýtko (gastrocnemius)", kind: "muscle", layout: "pair", r: [798, 266] },
  { key: "back-img6", overlay: "back-img6", top: 409, left: 138, title: "Šikmé břišní", kind: "muscle", layout: "pair", r: [412, 277] },
  { key: "back-img7", overlay: "back-img7", top: 209, left: 79, title: "Zadní delt", kind: "muscle", layout: "pair", r: [209, 329] },
  { key: "back-img8", overlay: "back-img8", top: 406, left: 59, title: "Předloktí", kind: "muscle", layout: "pair", r: [402, 362] },
  { key: "back-img9", overlay: "back-img9", top: 284, left: 57, title: "Triceps – laterální hlava", kind: "muscle", layout: "pair", r: [291, 352] },
  { key: "back-img10", overlay: "back-img10", top: 274, left: 86, title: "Triceps – dlouhá hlava", kind: "muscle", layout: "pair", r: [262, 324] },
  { key: "back-img11", overlay: "back-img11", top: 347, left: 85, title: "Triceps – mediální hlava", kind: "muscle", layout: "pair", r: [345, 325] },
  { key: "back-img14", overlay: "back-img14", top: 181, left: 90, title: "Boční delt", kind: "muscle", layout: "pair", r: [180, 322] },
  { key: "back-img15", overlay: "back-img15", top: 215, left: 108, title: "Teres minor", kind: "muscle", layout: "pair", r: [212, 298] },
  { key: "back-img16", overlay: "back-img16", top: 263, left: 114, title: "Teres major", kind: "muscle", layout: "pair", r: [264, 291] },
  { key: "back-img12", top: 228, left: 180, title: "Rhomboidy", kind: "muscle", layout: "pair", r: [228, 230] },
  // Muscles — central
  { key: "back-traps", overlay: "back-traps", top: 182, left: 204, title: "Trapézy", kind: "muscle", layout: "center" },
  { key: "back-img13", overlay: "back-img13", top: 407, left: 204, title: "Vzpřimovače páteře", kind: "muscle", layout: "center" },
  // Tendons / úpony — paired
  { key: "b-achilles", top: 905, left: 157, title: "Achillova šlacha", kind: "tendon", layout: "pair", r: [905, 234] },
  { key: "b-haminsert", top: 548, left: 172, title: "Úpon hamstringů (sedací hrbol)", kind: "tendon", layout: "pair", r: [548, 236] },
  { key: "b-itb", top: 625, left: 110, title: "Iliotibiální trakt (IT band)", kind: "tendon", layout: "pair", r: [625, 300] },
  { key: "b-knee", top: 712, left: 156, title: "Zákolenní šlachy", kind: "tendon", layout: "pair", r: [712, 243] },
  { key: "b-cuff", top: 230, left: 135, title: "Rotátorová manžeta", kind: "tendon", layout: "pair", r: [230, 276] },
  { key: "b-plantar", top: 992, left: 161, title: "Úpon plantární fascie (pata)", kind: "tendon", layout: "pair", r: [992, 230], w: 50, h: 40 },
  // Tendons — central
  { key: "b-si", top: 468, left: 204, title: "SI kloub / bederní úpony", kind: "tendon", layout: "center" },
  // Feet — paired
  { key: "b-foot", top: 966, left: 160, title: "Chodidlo – pata", kind: "tendon", layout: "pair", r: [966, 230], w: 60, h: 45 },
]

const overlays = {
  back: {
    "back-traps": "https://i.ibb.co/8DyCJrcr/Male-Back-traps.png",
    "back-lats": "https://i.ibb.co/jPdSSWqh/Male-Back-Lats.png",
    "back-img3": "https://i.ibb.co/LzfzzTbz/Male-Back-Glutes.png",
    "back-img4": "https://i.ibb.co/5p2h7Bm/Male-Back-Hamstrings.png",
    "back-img5": "https://i.ibb.co/KcWKM3f4/Male-Back-Calves.png",
    "back-img6": "https://i.ibb.co/Wp6XfJK2/Male-Back-Obliques.png",
    "back-img7": "https://i.ibb.co/Mxvn551d/Male-Back-Rear-Delt.png",
    "back-img8": "https://i.ibb.co/NdVwL8CX/Male-Back-Forearms-Full.png",
    "back-img9": "https://i.ibb.co/RG3JXNRZ/Male-Back-Triceps-Lateral.png",
    "back-img10": "https://i.ibb.co/Lz2NRvST/Male-Back-Triceps-Long.png",
    "back-img11": "https://i.ibb.co/RTG0kqvG/Male-Back-Triceps-Medial.png",
    "back-img12": "https://i.ibb.co/PGMZPjx0/Male-Back-Rhomboid-Majorr.png",
    "back-img13": "https://i.ibb.co/0yT8sRxh/Male-Back-Spinal-Eractors.png",
    "back-img14": "https://i.ibb.co/gsbXFcW/Male-Back-Side-Delt.png",
    "back-img15": "https://i.ibb.co/WvKFvy80/Male-Back-Teres-Minor.png",
    "back-img16": "https://i.ibb.co/L3rYNWN/Male-Back-Teres-Major.png",
  } as Record<string, string>,
  front: {
    "front-chest": "https://i.ibb.co/chBnXGWn/Muscle-M-FRONT-Pecs.png",
    "lower-abs": "https://i.ibb.co/Qxf0Lgy/Muscle-M-FRONT-abs-lower.png",
    "upper-abs": "https://i.ibb.co/prKvkp4f/Muscle-M-FRONT-abs-upper.png",
    "front-biceps": "https://i.ibb.co/d4F3JXD4/Muscle-M-FRONT-Biceps.png",
    "front-quads": "https://i.ibb.co/DscS1D1/Muscle-M-FRONT-QUADS.png.png",
    "front-delts":
      "https://i.ibb.co/Hf0Z3yfH/Muscle-M-FRONT-Front-Delt-Upper-Pecs.png",
    "front-forearms": "https://i.ibb.co/5XFZG9w3/Muscle-M-FRONT-forearms.png",
    triceps: "https://i.ibb.co/cXQ1hSq7/Muscle-M-FRONT-Triceps.png",
    "front-traps": "https://i.ibb.co/cc3CGkDN/Muscle-M-FRONT-Traps.png",
    "front-obliques": "https://i.ibb.co/zTpDSpCJ/Muscle-M-FRONT-abs-obliques.png",
    "front-calves": "https://i.ibb.co/WNGSyzFn/Muscle-M-FRONT-calves.png",
    "side-delt": "https://i.ibb.co/Pv1GYQXj/Muscle-M-FRONT-Side-Delt.png",
    "front-adductors": "https://i.ibb.co/jPxvxWM3/Muscle-M-FRONT-abductors.png",
    "front-hips": "https://i.ibb.co/j9gFhpsH/Muscle-M-FRONT-Hip-Flexors.png",
  } as Record<string, string>,
}

const bases = {
  back: "https://i.ibb.co/tTvq0CLn/Male-Back.png",
  front: "https://i.ibb.co/7dgWTHCN/Muscle-M-FRONT.png",
}

const hotspots = {
  front: build("front", frontDefs),
  back: build("back", backDefs),
}

const byId = (() => {
  const m = new Map<string, Hotspot & { view: "front" | "back" }>()
  ;(["front", "back"] as const).forEach((v) => hotspots[v].forEach((h) => m.set(h.id, { ...h, view: v })))
  return m
})()
const toBP = (h: Hotspot): BodyPoint => ({ region: h.title, side: h.side === "center" ? "" : h.side, kind: h.kind })
// Clip a bilateral overlay to the picked half, split at the figure's midline.
const clipFor = (h: Hotspot, view: "front" | "back") => {
  if (h.side === "center") return undefined
  const pct = (AX[view] / CANVAS_W) * 100
  return h.left < AX[view] ? `inset(0 ${100 - pct}% 0 0)` : `inset(0 0 0 ${pct}%)`
}

// Read-only body silhouette that highlights how often each region was marked
// painful (counts keyed by region title). Intensity ∝ frequency. Front/back
// auto-toggles to whichever side carries data.
// Key for a stored pain point on the heatmap: paired regions carry their side in the
// hotspot title ("Achillova šlacha (P)"), stored points keep region and side apart.
export const painKey = (p: { region?: string; side?: string | null }) => {
  const r = p.region || ""
  // body-map points already carry it ("Achillova šlacha (P)"), seeded/imported ones don't
  if (/ \((L|P)\)$/.test(r)) return r
  return p.side === "L" || p.side === "P" ? `${r} (${p.side})` : r
}

export function PainHeatmap({ counts }: { counts: Record<string, number> }) {
  // exact (sided) match first; a side-less count lights both sides only when no sided count exists
  const baseOf = (t: string) => t.replace(/ \((L|P)\)$/, "")
  const val = (h: Hotspot): number | undefined => {
    if (counts[h.title] != null) return counts[h.title]
    const b = baseOf(h.title)
    return b !== h.title && counts[`${b} (L)`] == null && counts[`${b} (P)`] == null ? counts[b] : undefined
  }
  const withData = (v: "front" | "back") => hotspots[v].filter((h) => val(h))
  const hasFront = withData("front").length > 0
  // railway#89 — open on the side with the most marked pain
  const load = (v: "front" | "back") => withData(v).reduce((t, h) => t + (val(h) || 0), 0)
  const [view, setView] = useState<"front" | "back">(load("back") > load("front") ? "back" : "front")
  const pts = withData(view)
  const max = Math.max(1, ...Object.values(counts))
  return (
    <div className="mx-auto w-full max-w-[300px]">
      {hasFront && withData("back").length > 0 && (
        <div className="mb-3 flex items-center justify-center gap-2">
          {(["front", "back"] as const).map((v) => (
            <button key={v} onClick={() => setView(v)} className={`rounded-full px-3 py-1 text-[11px] font-bold transition ${view === v ? "bg-alert text-ink" : "border border-white/10 text-fg-2 hover:border-alert/40"}`}>{v === "front" ? "Zepředu" : "Zezadu"}</button>
          ))}
        </div>
      )}
      <div className="relative w-full overflow-hidden rounded-[22px] border border-white/10 bg-panel" style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}` }}>
        <img src={bases[view]} alt="Silueta těla" className="absolute inset-0 h-full w-full object-cover opacity-20 grayscale" />
        <div className="absolute inset-0 bg-panel/50" />
        {pts.map((h) => {
          const t = (val(h) || 0) / max
          return (
            <span
              key={h.id}
              aria-hidden
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                top: `${(h.top / CANVAS_H) * 100}%`,
                left: `${(h.left / CANVAS_W) * 100}%`,
                width: `${9 + t * 13}%`,
                aspectRatio: "1",
                background: `radial-gradient(closest-side, rgb(231 122 89 / ${0.4 + t * 0.5}), rgb(231 122 89 / ${0.16 + t * 0.24}) 55%, rgb(231 122 89 / 0))`,
                mixBlendMode: "screen",
              }}
            />
          )
        })}
        {pts.map((h) => (
          <span
            key={`${h.id}-n`}
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 text-[11px] font-bold text-white"
            style={{ top: `${(h.top / CANVAS_H) * 100}%`, left: `${(h.left / CANVAS_W) * 100}%`, textShadow: "0 1px 2px rgb(0 0 0 / .85)" }}
          >
            {val(h)}×
          </span>
        ))}
      </div>
    </div>
  )
}

export default function MuscleAnatomy({
  onChange,
  onSelect,
  multi = false,
  initialRegions = [],
}: {
  onChange?: (p: BodyPoint | null) => void
  onSelect?: (points: BodyPoint[]) => void
  multi?: boolean
  initialRegions?: string[]
} = {}) {
  // Seed the selection from region titles (used when editing an existing entry).
  const seed = (() => {
    const ids: string[] = []
    for (const r of initialRegions) for (const [id, h] of byId) if (h.title === r) { ids.push(id); break }
    return ids
  })()
  const [view, setView] = useState<"back" | "front">(() => (seed[0] ? byId.get(seed[0])!.view : "front"))
  const [selected, setSelected] = useState<Set<string>>(() => new Set(seed))

  const list = hotspots[view]
  const selectedHere = list.filter((h) => selected.has(h.id))

  useEffect(() => {
    const pts = [...selected].map((id) => byId.get(id)).filter(Boolean).map((h) => toBP(h as Hotspot))
    if (multi) onSelect?.(pts)
    else onChange?.(pts[0] || null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(multi ? prev : [])
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const muscleCount = list.filter((h) => h.kind === "muscle").length
  const tendonCount = list.filter((h) => h.kind === "tendon").length

  return (
    <div className="mx-auto w-full max-w-[340px]">
      <div className="mb-4 flex items-center justify-center gap-2">
        {(["front", "back"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`rounded-full px-4 py-1.5 text-[11px] font-bold tracking-wide transition ${
              view === v
                ? "bg-info text-ink"
                : "border border-white/10 text-fg-2 hover:border-info/40"
            }`}
          >
            {v === "front" ? "Zepředu" : "Zezadu"}
          </button>
        ))}
      </div>

      <div
        className="relative w-full overflow-hidden rounded-[24px] border border-white/10 bg-gradient-to-b from-panel-2 to-panel"
        // the front art is 80 % opaque: on the dark card a stacked muscle overlay turned its half
        // visibly lighter, on white (as the opaque back art) the halves match
        style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}`, ...(view === "front" ? { background: "#fff" } : {}) }}
      >
        <img
          src={bases[view]}
          alt={`Svalová mapa – ${view === "front" ? "přední" : "zadní"} pohled`}
          className="absolute inset-0 h-full w-full object-cover"
        />

        {/* One overlay layer per selected muscle, clipped to its side, so
            several picks (incl. both L and R) light up at once. */}
        {selectedHere
          .filter((h) => h.kind === "muscle" && h.overlay && overlays[view][h.overlay])
          .map((h) => (
            <img
              key={h.id}
              src={overlays[view][h.overlay!]}
              alt=""
              aria-hidden
              className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-100 transition-opacity duration-300"
              style={{ clipPath: clipFor(h, view) }}
            />
          ))}

        {/* Red area highlight for each selected point without an overlay image (tendons, feet, rhomboids) */}
        {selectedHere
          .filter((h) => !(h.overlay && overlays[view][h.overlay]))
          .map((h) => (
            <span
              key={h.id}
              aria-hidden
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                top: `${(h.top / CANVAS_H) * 100}%`,
                left: `${(h.left / CANVAS_W) * 100}%`,
                width: `${((h.w ?? 46) / CANVAS_W) * 100}%`,
                height: `${((h.h ?? 60) / CANVAS_H) * 100}%`,
                background:
                  "radial-gradient(closest-side, rgb(231 122 89 / .7), rgb(231 122 89 / .32) 55%, rgb(231 122 89 / 0))",
                mixBlendMode: "screen",
                zIndex: 5,
              }}
            />
          ))}

        {list.map((h) => {
          const isSel = selected.has(h.id)
          const isTendon = h.kind === "tendon"
          const base = isTendon ? "#f6b26b" : C.info
          return (
            <button
              key={h.id}
              title={h.title}
              aria-label={h.title}
              aria-pressed={isSel}
              onClick={() => toggle(h.id)}
              className={`atlas-hotspot absolute -translate-x-1/2 -translate-y-1/2 border-2 border-white transition ${
                isTendon
                  ? "size-3 rotate-45 rounded-[2px]"
                  : "size-3.5 rounded-full"
              }`}
              style={{
                top: `${(h.top / CANVAS_H) * 100}%`,
                left: `${(h.left / CANVAS_W) * 100}%`,
                backgroundColor: isSel ? C.alert : base,
                boxShadow: isSel ? "0 0 0 6px rgb(228 125 81 / .25)" : undefined,
                zIndex: isSel ? 20 : 10,
              }}
            />
          )
        })}
      </div>

      <div className="mt-4 flex items-center justify-center gap-4 text-[11px] text-fg-2">
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-full bg-info" />
          Svaly · {muscleCount}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rotate-45 rounded-[2px] bg-watch" />
          Šlachy a chodidla · {tendonCount}
        </span>
      </div>

      {multi ? (
        selected.size ? (
          <div className="mt-3">
            <p className="text-center text-[11px] text-fg-2">Vybraná místa · {selected.size}{selected.size > selectedHere.length ? " (i v druhém pohledu)" : ""}</p>
            <div className="mt-2 flex flex-wrap justify-center gap-1.5">
              {[...selected].map((id) => {
                const h = byId.get(id)!
                return (
                  <button key={id} onClick={() => toggle(id)} className="inline-flex items-center gap-1 rounded-full bg-alert/15 px-2.5 py-1 text-[11px] font-semibold text-alert-soft">
                    {h.title} <span className="text-alert-soft/60">×</span>
                  </button>
                )
              })}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-center text-xs text-fg-2">Klepněte na místa, která bolí – můžete jich vybrat víc (i zepředu i zezadu).</p>
        )
      ) : (
        <p className="mt-2 text-center text-xs text-fg-2">
          {selectedHere[0] ? (
            <>
              {selectedHere[0].kind === "muscle" ? "Sval: " : selectedHere[0].id.includes("foot") ? "Oblast chodidla: " : "Šlacha / úpon: "}
              <b className="text-fg">{selectedHere[0].title}</b>
            </>
          ) : (
            "Klepněte na bod – vyberte stranu (L/P), sval, šlachu nebo chodidlo"
          )}
        </p>
      )}
    </div>
  )
}

// Feedback #159 — how full each body region's capacity is from the last 7 days of
// running (fills keyed by the region's base title, 1 = at the ceiling). Both legs
// carry the same value; the number sits on one side only. Regions with recent pain
// get a ring. The fills come from capacity.tsx (bodyLoad), a working model.
export function BodyLoadMap({ fills, pain = new Set<string>() }: { fills: Record<string, number>; pain?: Set<string> }) {
  const baseOf = (t: string) => t.replace(/ \((L|P)\)$/, "")
  const has = (v: "front" | "back") => hotspots[v].some((h) => fills[baseOf(h.title)] != null)
  const sum = (v: "front" | "back") => hotspots[v].reduce((t, h) => t + (fills[baseOf(h.title)] || 0), 0)
  const [view, setView] = useState<"front" | "back">(sum("back") >= sum("front") ? "back" : "front")
  const pts = hotspots[view].filter((h) => fills[baseOf(h.title)] != null)
  const col = (f: number) => (f >= 1 ? C.alert : f >= 0.7 ? C.watch : C.ok)
  return (
    <div className="mx-auto w-full max-w-[280px]" data-testid="body-load-map">
      {has("front") && has("back") && (
        <div className="mb-3 flex items-center justify-center gap-2">
          {(["front", "back"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setView(v)} className={`rounded-full px-3 py-1 text-[11px] font-bold transition ${view === v ? "bg-accent text-ink" : "border border-white/10 text-fg-2 hover:border-accent/40"}`}>{v === "front" ? "Zepředu" : "Zezadu"}</button>
          ))}
        </div>
      )}
      <div className="relative w-full overflow-hidden rounded-[22px] border border-white/10 bg-panel" style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}` }}>
        <img src={bases[view]} alt="Silueta těla" className="absolute inset-0 h-full w-full object-cover opacity-20 grayscale" />
        <div className="absolute inset-0 bg-panel/50" />
        {pts.map((h) => {
          const b = baseOf(h.title)
          const f = fills[b] || 0
          const c = col(f)
          return (
            <span key={h.id} aria-hidden className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                top: `${(h.top / CANVAS_H) * 100}%`, left: `${(h.left / CANVAS_W) * 100}%`, width: `${10 + Math.min(f, 1.3) * 10}%`, aspectRatio: "1",
                background: `radial-gradient(closest-side, ${c}cc, ${c}55 55%, ${c}00)`,
                boxShadow: pain.has(b) ? `0 0 0 2px ${C.alert}` : undefined,
              }} />
          )
        })}
        {pts.filter((h) => h.side !== "P").map((h) => (
          <span key={`${h.id}-n`} className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 tabular-nums text-[10.5px] font-bold text-white"
            style={{ top: `${(h.top / CANVAS_H) * 100}%`, left: `${(h.left / CANVAS_W) * 100}%`, textShadow: "0 1px 2px rgb(0 0 0 / .9)" }}>
            {Math.round((fills[baseOf(h.title)] || 0) * 100)} %
          </span>
        ))}
      </div>
    </div>
  )
}
