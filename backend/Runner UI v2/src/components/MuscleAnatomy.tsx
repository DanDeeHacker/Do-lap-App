import { useState } from "react"

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

export default function MuscleAnatomy() {
  const [view, setView] = useState<"back" | "front">("front")
  const [active, setActive] = useState<Record<"back" | "front", string | null>>(
    { back: null, front: null },
  )

  const list = hotspots[view]
  const activeId = active[view]
  const activePoint = activeId != null ? list.find((h) => h.id === activeId) : null

  // Clip a bilateral overlay image to just the selected half so one side lights up.
  const activeClip =
    activePoint && activePoint.side !== "center"
      ? activePoint.left < CX
        ? "inset(0 50% 0 0)"
        : "inset(0 0 0 50%)"
      : undefined

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
                ? "bg-[#6ce6d3] text-[#0c1f1c]"
                : "border border-white/10 text-[#a9c2b9] hover:border-[#6ce6d3]/40"
            }`}
          >
            {v === "front" ? "Zepředu" : "Zezadu"}
          </button>
        ))}
      </div>

      <div
        className="relative w-full overflow-hidden rounded-[24px] border border-white/10 bg-gradient-to-b from-[#12312c] to-[#0c211e]"
        style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}` }}
      >
        <img
          src={bases[view]}
          alt={`Svalová mapa – ${view === "front" ? "přední" : "zadní"} pohled`}
          className="absolute inset-0 h-full w-full object-cover"
        />

        {Object.entries(overlays[view]).map(([id, src]) => {
          const isActive =
            activePoint?.kind === "muscle" && activePoint.overlay === id
          return (
            <img
              key={id}
              src={src}
              alt=""
              aria-hidden
              className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${
                isActive ? "opacity-100" : "opacity-0"
              }`}
              style={{ clipPath: isActive ? activeClip : undefined }}
            />
          )
        })}

        {/* Red area highlight for tendon / foot points (no overlay image) */}
        {activePoint?.kind === "tendon" && (
          <span
            aria-hidden
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{
              top: `${(activePoint.top / CANVAS_H) * 100}%`,
              left: `${(activePoint.left / CANVAS_W) * 100}%`,
              width: `${((activePoint.w ?? 46) / CANVAS_W) * 100}%`,
              height: `${((activePoint.h ?? 60) / CANVAS_H) * 100}%`,
              background:
                "radial-gradient(closest-side, rgb(231 122 89 / .7), rgb(231 122 89 / .32) 55%, rgb(231 122 89 / 0))",
              mixBlendMode: "screen",
              zIndex: 5,
            }}
          />
        )}

        {list.map((h) => {
          const selected = activeId === h.id
          const isTendon = h.kind === "tendon"
          const base = isTendon ? "#f6b26b" : "#6ce6d3"
          return (
            <button
              key={h.id}
              title={h.title}
              aria-label={h.title}
              aria-pressed={selected}
              onClick={() =>
                setActive((prev) => ({
                  ...prev,
                  [view]: prev[view] === h.id ? null : h.id,
                }))
              }
              className={`atlas-hotspot absolute -translate-x-1/2 -translate-y-1/2 border-2 border-white transition ${
                isTendon
                  ? "size-3 rotate-45 rounded-[2px]"
                  : "size-3.5 rounded-full"
              }`}
              style={{
                top: `${(h.top / CANVAS_H) * 100}%`,
                left: `${(h.left / CANVAS_W) * 100}%`,
                backgroundColor: selected ? "#e77a59" : base,
                boxShadow: selected ? "0 0 0 6px rgb(228 125 81 / .25)" : undefined,
                zIndex: selected ? 20 : 10,
              }}
            />
          )
        })}
      </div>

      <div className="mt-4 flex items-center justify-center gap-4 text-[10px] text-[#8ba59d]">
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-full bg-[#6ce6d3]" />
          Svaly · {muscleCount}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rotate-45 rounded-[2px] bg-[#f6b26b]" />
          Šlachy a chodidla · {tendonCount}
        </span>
      </div>

      <p className="mt-2 text-center text-xs text-[#a9c2b9]">
        {activePoint ? (
          <>
            {activePoint.kind === "muscle"
              ? "Sval: "
              : activePoint.id.includes("foot")
                ? "Oblast chodidla: "
                : "Šlacha / úpon: "}
            <b className="text-[#f1f8f1]">{activePoint.title}</b>
          </>
        ) : (
          "Klepněte na bod – vyberte stranu (L/P), sval, šlachu nebo chodidlo"
        )}
      </p>
    </div>
  )
}
