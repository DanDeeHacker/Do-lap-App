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
const CX = CANVAS_W / 2

const mirror = (x: number) => Math.round(2 * CX - x)

// Anatomical side for a point, accounting for the mirrored back view.
// Front view: image-left half = figure's RIGHT side; back view: image-left = LEFT.
function anatSide(view: "front" | "back", x: number): "L" | "P" {
  const imageLeft = x < CX
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
      for (const x of [d.left, mirror(d.left)]) {
        const s = anatSide(view, x)
        out.push({
          id: `${d.key}-${s}`,
          overlay: d.overlay,
          top: d.top,
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
  { key: "front-chest", overlay: "front-chest", top: 250, left: 165, title: "Prsní sval", kind: "muscle", layout: "pair" },
  { key: "front-biceps", overlay: "front-biceps", top: 300, left: 100, title: "Biceps", kind: "muscle", layout: "pair" },
  { key: "front-quads", overlay: "front-quads", top: 630, left: 170, title: "Kvadriceps", kind: "muscle", layout: "pair" },
  { key: "front-delts", overlay: "front-delts", top: 230, left: 80, title: "Přední delt", kind: "muscle", layout: "pair" },
  { key: "front-forearms", overlay: "front-forearms", top: 400, left: 80, title: "Předloktí", kind: "muscle", layout: "pair" },
  { key: "triceps", overlay: "triceps", top: 290, left: 40, title: "Triceps", kind: "muscle", layout: "pair" },
  { key: "front-obliques", overlay: "front-obliques", top: 380, left: 140, title: "Šikmé břišní", kind: "muscle", layout: "pair" },
  { key: "front-calves", overlay: "front-calves", top: 800, left: 165, title: "Lýtko", kind: "muscle", layout: "pair" },
  { key: "side-delt", overlay: "side-delt", top: 220, left: 55, title: "Boční delt", kind: "muscle", layout: "pair" },
  { key: "front-adductors", overlay: "front-adductors", top: 540, left: 185, title: "Adduktor", kind: "muscle", layout: "pair" },
  { key: "front-hips", overlay: "front-hips", top: 460, left: 155, title: "Ohýbač kyčle", kind: "muscle", layout: "pair" },
  // Muscles — central
  { key: "upper-abs", overlay: "upper-abs", top: 300, left: 210, title: "Horní břišní", kind: "muscle", layout: "center" },
  { key: "lower-abs", overlay: "lower-abs", top: 450, left: 210, title: "Dolní břišní", kind: "muscle", layout: "center" },
  { key: "front-traps", overlay: "front-traps", top: 150, left: 210, title: "Horní trapézy", kind: "muscle", layout: "center" },
  // Tendons / úpony — paired
  { key: "f-patellar", top: 715, left: 172, title: "Patelární šlacha", kind: "tendon", layout: "pair" },
  { key: "f-quadtendon", top: 670, left: 172, title: "Kvadricepsová šlacha", kind: "tendon", layout: "pair" },
  { key: "f-shin", top: 830, left: 165, title: "Tibialis anterior (holeň)", kind: "tendon", layout: "pair" },
  { key: "f-groin", top: 505, left: 185, title: "Tříslo / úpon adduktorů", kind: "tendon", layout: "pair" },
  { key: "f-hipflexor", top: 480, left: 160, title: "Úpon ohýbačů kyčle", kind: "tendon", layout: "pair" },
  { key: "f-elbow", top: 375, left: 95, title: "Šlacha bicepsu (loket)", kind: "tendon", layout: "pair" },
  { key: "f-wrist", top: 475, left: 72, title: "Šlachy zápěstí", kind: "tendon", layout: "pair" },
  { key: "f-ankle", top: 895, left: 168, title: "Přední hlezenní vazy", kind: "tendon", layout: "pair" },
  // Feet — paired
  { key: "f-foot", top: 975, left: 168, title: "Chodidlo – nárt", kind: "tendon", layout: "pair", w: 55, h: 45 },
  { key: "f-toes", top: 1005, left: 166, title: "Prsty / metatarzy", kind: "tendon", layout: "pair", w: 45, h: 32 },
]

const backDefs: Def[] = [
  // Muscles — paired
  { key: "back-lats", overlay: "back-lats", top: 300, left: 150, title: "Zádové svaly (lats)", kind: "muscle", layout: "pair" },
  { key: "back-img3", overlay: "back-img3", top: 500, left: 175, title: "Hýždě (gluteus)", kind: "muscle", layout: "pair" },
  { key: "back-img4", overlay: "back-img4", top: 620, left: 170, title: "Hamstring", kind: "muscle", layout: "pair" },
  { key: "back-img5", overlay: "back-img5", top: 780, left: 170, title: "Lýtko (gastrocnemius)", kind: "muscle", layout: "pair" },
  { key: "back-img6", overlay: "back-img6", top: 380, left: 108, title: "Šikmé břišní", kind: "muscle", layout: "pair" },
  { key: "back-img7", overlay: "back-img7", top: 200, left: 104, title: "Zadní delt", kind: "muscle", layout: "pair" },
  { key: "back-img8", overlay: "back-img8", top: 400, left: 60, title: "Předloktí", kind: "muscle", layout: "pair" },
  { key: "back-img9", overlay: "back-img9", top: 280, left: 30, title: "Triceps – laterální hlava", kind: "muscle", layout: "pair" },
  { key: "back-img10", overlay: "back-img10", top: 240, left: 114, title: "Triceps – dlouhá hlava", kind: "muscle", layout: "pair" },
  { key: "back-img11", overlay: "back-img11", top: 350, left: 114, title: "Triceps – mediální hlava", kind: "muscle", layout: "pair" },
  { key: "back-img14", overlay: "back-img14", top: 200, left: 74, title: "Boční delt", kind: "muscle", layout: "pair" },
  { key: "back-img15", overlay: "back-img15", top: 210, left: 134, title: "Teres minor", kind: "muscle", layout: "pair" },
  { key: "back-img16", overlay: "back-img16", top: 255, left: 139, title: "Teres major", kind: "muscle", layout: "pair" },
  // Muscles — central
  { key: "back-traps", overlay: "back-traps", top: 100, left: 210, title: "Trapézy", kind: "muscle", layout: "center" },
  { key: "back-img12", overlay: "back-img12", top: 240, left: 210, title: "Rhomboidy", kind: "muscle", layout: "center" },
  { key: "back-img13", overlay: "back-img13", top: 400, left: 210, title: "Vzpřimovače páteře", kind: "muscle", layout: "center" },
  // Tendons / úpony — paired
  { key: "b-achilles", top: 905, left: 172, title: "Achillova šlacha", kind: "tendon", layout: "pair" },
  { key: "b-haminsert", top: 560, left: 172, title: "Úpon hamstringů (sedací hrbol)", kind: "tendon", layout: "pair" },
  { key: "b-itb", top: 560, left: 118, title: "Iliotibiální trakt (IT band)", kind: "tendon", layout: "pair" },
  { key: "b-knee", top: 700, left: 165, title: "Zákolenní šlachy", kind: "tendon", layout: "pair" },
  { key: "b-cuff", top: 220, left: 118, title: "Rotátorová manžeta", kind: "tendon", layout: "pair" },
  { key: "b-plantar", top: 965, left: 172, title: "Úpon plantární fascie (pata)", kind: "tendon", layout: "pair", w: 50, h: 40 },
  // Tendons — central
  { key: "b-si", top: 470, left: 210, title: "SI kloub / bederní úpony", kind: "tendon", layout: "center" },
  // Feet — paired
  { key: "b-foot", top: 1000, left: 170, title: "Chodidlo – pata", kind: "tendon", layout: "pair", w: 60, h: 45 },
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
const clipFor = (h: Hotspot) => (h.side !== "center" ? (h.left < CX ? "inset(0 50% 0 0)" : "inset(0 0 0 50%)") : undefined)

// Read-only body silhouette that highlights how often each region was marked
// painful (counts keyed by region title). Intensity ∝ frequency. Front/back
// auto-toggles to whichever side carries data.
export function PainHeatmap({ counts }: { counts: Record<string, number> }) {
  const withData = (v: "front" | "back") => hotspots[v].filter((h) => counts[h.title])
  const hasFront = withData("front").length > 0
  const [view, setView] = useState<"front" | "back">(hasFront ? "front" : "back")
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
          const t = counts[h.title] / max
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
            {counts[h.title]}×
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
        style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}` }}
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
              style={{ clipPath: clipFor(h) }}
            />
          ))}

        {/* Red area highlight for each selected tendon / foot point (no overlay image) */}
        {selectedHere
          .filter((h) => h.kind === "tendon")
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
