// Exercise illustrations: an own stick figure per exercise (no third-party images; the
// Physiopedia pages the exercise detail links to are CC BY-NC-SA and their images are
// often third-party). Side-view exercises are posed by joint angles and drawn by forward
// kinematics, so the limbs keep their length while the figure moves between key frames;
// a few front-view exercises (lying on the side, pelvis drop) give their points directly.
import { useEffect, useMemo, useRef, useState } from "react"
import { Pause, Play } from "lucide-react"

type V = [number, number]
type Arm = [number, number]          // upper arm (absolute), elbow flexion
type Leg = [number, number, number]  // thigh (absolute), knee flexion, ankle plantar flexion
// Absolute angles: 0 = down, 90 = forward (right, the figure faces right), 180 = up.
type Pose = { t: number; h?: number; a: Arm; b: Arm; l: Leg; r: Leg; lift?: number; ms?: number; hold?: number }
type PtsPose = { p: Record<string, V>; ms?: number; hold?: number }
type Prop = { k: "wall" | "step" | "box" | "towel" | "weight" | "bar" | "rect" | "arrow" | "ball" | "line"; j?: string; j2?: string; dx?: number; dy?: number; x0?: number; x1?: number; y?: number; live?: boolean }
type Spec = {
  f?: Pose[]; pts?: PtsPose[]; lines?: [string[], 0 | 1][]
  pin?: string; mode?: "ground" | "hold"; ground?: number; props?: Prop[]; ease?: "sine" | "lin"; thumb?: number
  floor?: boolean     // false: a view from above (lying on the floor), no floor line
}

const W = 120, H = 92, FLOOR = 86
const TR = 24, HD = 7, HR = 5.2, UA = 12, FA = 11, TH = 17, SH = 17, FT = 6, HL = 1.5
const rad = (d: number) => (d * Math.PI) / 180
const dir = (a: number, len: number): V => [Math.sin(rad(a)) * len, Math.cos(rad(a)) * len]
const add = (p: V, q: V): V => [p[0] + q[0], p[1] + q[1]]
const sub = (p: V, q: V): V => [p[0] - q[0], p[1] - q[1]]

function fk(p: Pose): Record<string, V> {
  const hip: V = [0, 0]
  const neck = dir(p.t, TR)
  const head = add(neck, dir(p.t + (p.h || 0), HD))
  const arm = (x: Arm, s: string) => {
    const el = add(neck, dir(x[0], UA))
    return { ["elbow" + s]: el, ["hand" + s]: add(el, dir(x[0] + x[1], FA)) }
  }
  const leg = (x: Leg, s: string) => {
    const kn = dir(x[0], TH)
    const shin = x[0] - x[1]
    const an = add(kn, dir(shin, SH))
    const foot = shin + 90 - x[2]
    return { ["knee" + s]: kn, ["ankle" + s]: an, ["toe" + s]: add(an, dir(foot, FT)), ["heel" + s]: sub(an, dir(foot, HL)) }
  }
  return { hip, neck, head, ...arm(p.a, "N"), ...arm(p.b, "F"), ...leg(p.l, "N"), ...leg(p.r, "F") }
}

const lerp = (a: number, b: number, u: number) => a + (b - a) * u
function mixPose(x: Pose, y: Pose, u: number): Pose {
  const m = (p: number[], q: number[]) => p.map((v, i) => lerp(v, q[i], u))
  return { t: lerp(x.t, y.t, u), h: lerp(x.h || 0, y.h || 0, u), a: m(x.a, y.a) as Arm, b: m(x.b, y.b) as Arm,
    l: m(x.l, y.l) as Leg, r: m(x.r, y.r) as Leg, lift: lerp(x.lift || 0, y.lift || 0, u) }
}
function mixPts(x: PtsPose, y: PtsPose, u: number): PtsPose {
  const p: Record<string, V> = {}
  for (const k of Object.keys(x.p)) { const q = y.p[k] || x.p[k]; p[k] = [lerp(x.p[k][0], q[0], u), lerp(x.p[k][1], q[1], u)] }
  return { p }
}
const lowest = (j: Record<string, V>) => Math.max(...Object.entries(j).map(([k, v]) => v[1] + (k === "head" ? HR : 0)))
const shift = (j: Record<string, V>, d: V) => Object.fromEntries(Object.entries(j).map(([k, v]) => [k, add(v, d)])) as Record<string, V>

// ---- poses --------------------------------------------------------------------------
const ARMS_WALL = { a: [70, 20] as Arm, b: [-4, 10] as Arm }
const up = (l: Leg, r: Leg, x: Partial<Pose> = {}): Pose => ({ t: 180, ...ARMS_WALL, l, r, ...x })
const mirror = (p: Pose): Pose => ({ ...p, a: p.b, b: p.a, l: p.r, r: p.l })
const DRILL: Partial<Spec> = { pin: "hip", ease: "lin", props: [{ k: "arrow" }] }
const run = (p: Pose[]): Pose[] => [...p, ...p.map(mirror)]

// Side-lying and front-view figures: absolute points.
const SIDE_LYING = { head: [17, 75], neck: [25, 78], hip: [51, 78], elbowF: [22, 84.5], handF: [15, 81], elbowN: [37, 74], handN: [49, 76] } as Record<string, V>
const LYING_LINES: [string[], 0 | 1][] = [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF", "toeF"], 1], [["neck", "hip"], 0], [["hip", "kneeN", "ankleN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]]

// railway#203 — front views (seated / standing) and views from above (lying on the floor)
const SEATED_FRONT = { head: [60, 47], neck: [60, 54], mid: [60, 78], shN: [55, 56], shF: [65, 56], elbowN: [49, 66], handN: [46, 79],
  elbowF: [71, 66], handF: [74, 79], hipN: [55.5, 80], hipF: [64.5, 80] } as Record<string, V>
const SEATED_LINES: [string[], 0 | 1][] = [[["shF", "elbowF", "handF"], 1], [["hipF", "kneeF", "ankleF", "toeF"], 1], [["neck", "mid"], 0], [["shN", "shF"], 0],
  [["hipN", "hipF"], 0], [["hipN", "kneeN", "ankleN", "toeN"], 0], [["shN", "elbowN", "handN"], 0]]
const STAND_FRONT = { head: [60, 20], neck: [60, 27], mid: [60, 51], shN: [54, 29], shF: [66, 29], hipN: [55, 51], hipF: [65, 51], kneeN: [55, 68], kneeF: [65, 68],
  ankleN: [55, 85], ankleF: [65, 85], toeN: [52, 86], toeF: [68, 86] } as Record<string, V>
const FRONT_LINES: [string[], 0 | 1][] = [[["shF", "elbowF", "handF"], 1], [["hipF", "kneeF", "ankleF", "toeF"], 1], [["neck", "mid"], 0], [["shN", "shF"], 0],
  [["hipN", "hipF"], 0], [["hipN", "kneeN", "ankleN", "toeN"], 0], [["shN", "elbowN", "handN"], 0]]
const SUPINE_TOP = { head: [18, 64], neck: [26, 64], hip: [52, 64], elbowN: [33, 53], handN: [39, 44], elbowF: [33, 75], handF: [39, 84],
  kneeF: [69, 66], ankleF: [86, 67], toeF: [89, 67] } as Record<string, V>
const SUPINE_TOP_HOOK = { ...SUPINE_TOP, ankleN: [75, 62], toeN: [78.5, 62], ankleF: [75, 66], toeF: [78.5, 66] } as Record<string, V>
const TOP_LINES: [string[], 0 | 1][] = [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF", "toeF"], 1], [["neck", "hip"], 0],
  [["hip", "kneeN", "ankleN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]]
const SIDE_TOP = { head: [20, 60], neck: [28, 62], hip: [54, 62], elbowF: [30, 72], handF: [30, 82], kneeF: [63, 77], ankleF: [78, 78], toeF: [82, 78],
  kneeN: [61, 75], ankleN: [76, 76], toeN: [80, 76] } as Record<string, V>
const QUAD_PTS = { neck: [38, 64], elbowN: [38, 75], handN: [38, 86], elbowF: [40, 75], handF: [40, 86], hip: [68, 69], kneeN: [68, 86], ankleN: [85, 86],
  kneeF: [70, 86], ankleF: [87, 86] } as Record<string, V>

const SPECS: Record<string, Spec> = {
  heel_raise_2: { f: [up([0, 0, 0], [0, 0, 0], { ms: 1400, hold: 300 }), up([0, 0, 40], [0, 0, 40], { ms: 900, hold: 500 })], props: [{ k: "wall", j: "handN", dx: 1.2 }] },
  heel_raise_1: { f: [up([0, 0, 0], [15, 85, 30], { ms: 1400, hold: 300 }), up([0, 0, 40], [15, 85, 30], { ms: 900, hold: 500 })], props: [{ k: "wall", j: "handN", dx: 1.2 }] },
  towel_raise: { f: [up([0, 0, 0], [15, 85, 30], { ms: 1500, hold: 300 }), up([0, 0, 40], [15, 85, 30], { ms: 1300, hold: 800 })], props: [{ k: "wall", j: "handN", dx: 1.2 }, { k: "towel", j: "toeN" }] },
  ecc_straight: { mode: "hold", ground: FLOOR - 10, f: [up([0, 0, 35], [0, 0, 35], { ms: 900, hold: 300 }), up([0, 0, -22], [20, 75, 20], { ms: 1600, hold: 300 })],
    props: [{ k: "step", j: "toeN", x0: -3.5, x1: 17 }, { k: "wall", j: "handN", dx: 1.2 }] },
  ecc_bent: { mode: "hold", ground: FLOOR - 10, f: [up([20, 40, 30], [20, 40, 30], { ms: 900, hold: 300 }), up([20, 40, -40], [25, 80, 20], { ms: 1600, hold: 300 })],
    props: [{ k: "step", j: "toeN", x0: -3.5, x1: 17 }, { k: "wall", j: "handN", dx: 1.2 }] },
  seated_calf: { mode: "hold", pin: "hip", f: [{ t: 180, a: [15, 45], b: [15, 45], l: [90, 90, 0], r: [90, 90, 0], ms: 1300, hold: 300 },
    { t: 180, a: [15, 45], b: [15, 45], l: [104, 96, 53], r: [104, 96, 53], ms: 900, hold: 500 }],
    props: [{ k: "box", j: "hip", x0: -12, x1: 5, dy: 2 }, { k: "weight", j: "kneeN", dx: -4, dy: -3.5, live: true }] },
  hops: { pin: "hip", f: [{ t: 178, a: [10, 20], b: [-10, 20], l: [12, 25, 5], r: [12, 25, 5], ms: 260 }, { t: 180, a: [5, 15], b: [-5, 15], l: [3, 6, 35], r: [3, 6, 35], lift: 6, ms: 260 }] },
  side_abd: { pts: [
    { p: { ...SIDE_LYING, kneeF: [68, 80], ankleF: [84, 83], toeF: [88, 81], kneeN: [68, 76], ankleN: [85, 79], toeN: [89, 77] }, ms: 1200, hold: 300 },
    { p: { ...SIDE_LYING, kneeF: [68, 80], ankleF: [84, 83], toeF: [88, 81], kneeN: [66, 70], ankleN: [81, 62], toeN: [85, 60.5] }, ms: 900, hold: 500 }], lines: LYING_LINES },
  clamshell: { pts: [
    { p: { ...SIDE_LYING, kneeF: [63, 81], ankleF: [75, 83], toeF: [79, 81.5], kneeN: [63, 77], ankleN: [76, 80], toeN: [80, 78.5] }, ms: 1100, hold: 300 },
    { p: { ...SIDE_LYING, kneeF: [63, 81], ankleF: [75, 83], toeF: [79, 81.5], kneeN: [60, 66], ankleN: [76, 80], toeN: [80, 78.5] }, ms: 900, hold: 500 }], lines: LYING_LINES },
  bridge: { f: [{ t: -90, a: [97, 0], b: [97, 0], l: [125, 95, 30], r: [125, 95, 30], ms: 1300, hold: 300 },
    { t: -70, h: -20, a: [100, 0], b: [100, 0], l: [100, 81, 19], r: [100, 81, 19], ms: 900, hold: 700 }] },
  bridge_iso: { f: [{ t: -90, a: [97, 0], b: [97, 0], l: [110, 59, -9], r: [110, 59, -9], ms: 1200, hold: 300 },
    { t: -75, h: -15, a: [100, 0], b: [100, 0], l: [100, 66, -26], r: [100, 66, -26], ms: 1000, hold: 1600 }] },
  wall_squat: { f: [{ t: 180, a: [2, 5], b: [-2, 5], l: [29, 0, 29], r: [29, 0, 29], ms: 1000, hold: 300 },
    { t: 180, a: [2, 5], b: [-2, 5], l: [82, 82, 0], r: [82, 82, 0], ms: 1200, hold: 1200 }], props: [{ k: "wall", j: "hip", dx: -3.5 }] },
  step_up: { mode: "hold", f: [{ t: 175, a: [-20, 30], b: [20, 30], l: [60, 90, -30], r: [0, 0, 0], ms: 1100, hold: 300 },
    { t: 180, a: [10, 20], b: [-10, 20], l: [0, 0, 0], r: [10, 45, 25], ms: 1000, hold: 400 }], props: [{ k: "step", j: "toeN", x0: -11, x1: 6 }] },
  knee_ext: { mode: "hold", pin: "hip", f: [{ t: 180, a: [15, 45], b: [15, 45], l: [90, 90, 0], r: [90, 90, 0], ms: 1300, hold: 300 },
    { t: 180, a: [15, 45], b: [15, 45], l: [92, 6, -5], r: [90, 90, 0], ms: 900, hold: 500 }],
    props: [{ k: "box", j: "hip", x0: -12, x1: 5, dy: 2 }, { k: "weight", j: "ankleN", dx: -1, dy: -1.5, live: true }] },
  pelvic_drop: { pts: [
    { p: { head: [60, 13], neck: [60, 20], mid: [60, 44], shN: [54, 22], shF: [66, 22], elbowN: [51, 33], elbowF: [69, 33], handN: [50, 43], handF: [70, 43],
      hipN: [55, 44], hipF: [65, 44], kneeN: [55, 61], kneeF: [65, 61], ankleN: [55, 78], ankleF: [65, 78], toeN: [51, 79], toeF: [69, 79] }, ms: 1000, hold: 300 },
    { p: { head: [60, 13], neck: [60, 20], mid: [60, 46], shN: [54, 22], shF: [66, 22], elbowN: [51, 33], elbowF: [69, 33], handN: [50, 43], handF: [70, 43],
      hipN: [55, 44], hipF: [65, 48], kneeN: [55, 61], kneeF: [65.4, 65], ankleN: [55, 78], ankleF: [65.8, 82], toeN: [51, 79], toeF: [69.8, 83] }, ms: 1000, hold: 300 }],
    lines: [[["neck", "shF", "elbowF", "handF"], 1], [["hipF", "kneeF", "ankleF", "toeF"], 1], [["neck", "mid"], 0], [["hipN", "hipF"], 0],
      [["hipN", "kneeN", "ankleN", "toeN"], 0], [["neck", "shN", "elbowN", "handN"], 0]], props: [{ k: "rect", x0: 22, x1: 60, y: 78 }] },
  sl_squat: { f: [{ t: 178, a: [60, 20], b: [60, 20], l: [2, 4, -2], r: [25, 45, 15], ms: 1100, hold: 300 },
    { t: 158, a: [75, 10], b: [75, 10], l: [40, 65, -25], r: [45, 40, 5], ms: 1400, hold: 300 }] },
  toe_raise: { pin: "ankleN", f: [{ t: 192, a: [-8, 5], b: [-8, 5], l: [12, 0, 12], r: [12, 0, 12], ms: 700, hold: 200 },
    { t: 192, a: [-8, 5], b: [-8, 5], l: [12, 0, -25], r: [12, 0, -25], ms: 600, hold: 300 }], props: [{ k: "wall", j: "neck", dx: -3 }] },
  balance: { f: [{ t: 180, a: [35, 10], b: [-30, 10], l: [4, 10, 6], r: [25, 80, 20], ms: 1500 }, { t: 176, a: [45, 10], b: [-20, 10], l: [5, 12, 7], r: [28, 85, 22], ms: 1500 }] },
  nordic: { mode: "hold", pin: "kneeN", f: [{ t: 180, a: [35, 110], b: [35, 110], l: [0, 90, 90], r: [0, 90, 90], ms: 900, hold: 400 },
    { t: 128, a: [40, 20], b: [40, 20], l: [-52, 38, 90], r: [-52, 38, 90], ms: 2200, hold: 200 }], props: [{ k: "bar", j: "ankleN", dy: -3.2 }] },
  sl_rdl: { f: [{ t: 180, a: [3, 5], b: [-3, 5], l: [3, 10, -7], r: [3, 10, -7], ms: 1100, hold: 300 },
    { t: 98, a: [2, 0], b: [2, 0], l: [12, 22, -10], r: [-82, 4, 4], ms: 1400, hold: 400 }] },
  plank: { mode: "hold", pin: "elbowN", f: [{ t: 100, h: -5, a: [0, 90], b: [0, 90], l: [-62.7, 42.3, 90], r: [-62.7, 42.3, 90], ms: 900, hold: 300 },
    { t: 95, h: -5, a: [0, 90], b: [0, 90], l: [-85, 0, -5], r: [-85, 0, -5], ms: 800, hold: 2000 }] },
  // feedback #163 — figures for the groin and lower-abdomen programmes
  add_squeeze: { mode: "hold", f: [{ t: -90, a: [97, 0], b: [97, 0], l: [125, 95, 30], r: [125, 95, 30], ms: 900, hold: 300 },
    { t: -90, h: 0, a: [97, 0], b: [97, 0], l: [127, 98, 30], r: [127, 98, 30], ms: 500, hold: 2000 }],
    props: [{ k: "weight", j: "kneeN", dx: 0, dy: 0, live: true }] },
  curl_up: { mode: "hold", pin: "hip", f: [{ t: -90, a: [97, 0], b: [97, 0], l: [125, 95, 30], r: [90, 0, -20], ms: 900, hold: 300 },
    { t: -103, h: -10, a: [95, 0], b: [95, 0], l: [125, 95, 30], r: [90, 0, -20], ms: 900, hold: 1500 }] },
  pelvic_tilt: { f: [{ t: -90, a: [97, 0], b: [97, 0], l: [125, 95, 30], r: [125, 95, 30], ms: 1000, hold: 300 },
    { t: -84, a: [97, 0], b: [97, 0], l: [170, 105, 20], r: [170, 105, 20], ms: 1100, hold: 900 }] },
  side_adduction: { pts: [
    { p: { ...SIDE_LYING, kneeF: [68, 81], ankleF: [85, 83], toeF: [89, 81], kneeN: [62, 68], ankleN: [66, 84], toeN: [70, 84] }, ms: 1200, hold: 300 },
    { p: { ...SIDE_LYING, kneeF: [68, 77], ankleF: [85, 73], toeF: [89, 71], kneeN: [62, 68], ankleN: [66, 84], toeN: [70, 84] }, ms: 900, hold: 600 }], lines: LYING_LINES },
  copenhagen: { pts: [
    { p: { head: [23, 70], neck: [30, 72], elbowN: [30, 85], handN: [37, 85.5], elbowF: [41, 75], handF: [51.5, 80], hip: [52, 82],
      kneeN: [69, 76], ankleN: [86, 71], toeN: [89, 69], kneeF: [68, 83], ankleF: [85, 85], toeF: [89, 84] }, ms: 1000, hold: 300 },
    { p: { head: [23.1, 70.8], neck: [30, 72], elbowN: [30, 85], handN: [37, 85.5], elbowF: [41.5, 71], handF: [52.5, 74.5], hip: [53.6, 74.5],
      kneeN: [70, 72.5], ankleN: [86, 71], toeN: [89, 69], kneeF: [70, 75], ankleF: [86, 74.5], toeF: [89.5, 73] }, ms: 1100, hold: 900 }],
    lines: [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF", "toeF"], 1], [["neck", "hip", "kneeN", "ankleN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]],
    props: [{ k: "rect", x0: 80, x1: 104, y: 72 }] },
  side_plank: { pts: [
    { p: { head: [23, 70], neck: [30, 72], elbowN: [30, 85], handN: [37, 85.5], elbowF: [41, 75], handF: [51.5, 80], hip: [52, 82.5], knee: [69.5, 83.2], ankle: [87, 84], toe: [89, 82] }, ms: 900, hold: 300 },
    { p: { head: [23.1, 70.8], neck: [30, 72], elbowN: [30, 85], handN: [37, 85.5], elbowF: [41.5, 71], handF: [52.5, 74.5], hip: [53.6, 76.1], knee: [70.3, 79.1], ankle: [87, 82], toe: [89, 80] }, ms: 900, hold: 1800 }],
    lines: [[["neck", "elbowF", "handF"], 1], [["neck", "hip", "knee", "ankle", "toe"], 0], [["neck", "elbowN", "handN"], 0]] },
  dead_bug: { pin: "hip", f: [{ t: -90, a: [180, 0], b: [180, 0], l: [180, 90, 0], r: [180, 90, 0], ms: 900, hold: 300 },
    { t: -90, a: [265, 0], b: [180, 0], l: [180, 90, 0], r: [97, 0, 40], ms: 1300, hold: 400 }] },
  bird_dog: { pin: "hip", f: [{ t: 100, a: [22, 0], b: [22, 0], l: [0, 90, 90], r: [0, 90, 90], ms: 1000, hold: 300 },
    { t: 100, a: [92, 0], b: [22, 0], l: [0, 90, 90], r: [-92, 0, 90], ms: 1100, hold: 900 }] },
  skipink: { ...DRILL, f: run([{ t: 176, l: [30, 55, 5], r: [-2, 6, 28], a: [-30, 80], b: [30, 80], lift: 0.5, ms: 170 }]) },
  a_skip: { ...DRILL, f: run([{ t: 178, l: [90, 90, -5], r: [-3, 4, 30], a: [-45, 75], b: [55, 85], lift: 3, ms: 230 },
    { t: 178, l: [20, 25, 20], r: [-5, 10, 25], a: [-10, 70], b: [15, 75], ms: 200 }]) },
  b_skip: { ...DRILL, f: run([{ t: 178, l: [90, 90, -5], r: [-3, 4, 30], a: [-45, 75], b: [55, 85], lift: 2.5, ms: 220 },
    { t: 178, l: [75, 8, 15], r: [-5, 6, 30], a: [-40, 75], b: [50, 85], lift: 2.5, ms: 200 },
    { t: 178, l: [5, 8, 25], r: [-10, 20, 25], a: [-10, 70], b: [15, 75], ms: 220 }]) },
  heel_flicks: { ...DRILL, f: run([{ t: 178, l: [0, 125, 30], r: [-3, 8, 28], a: [-30, 80], b: [30, 80], lift: 1.5, ms: 200 }]) },
  straight_leg: { ...DRILL, f: run([{ t: 180, l: [45, 0, -15], r: [-12, 0, 25], a: [-40, 70], b: [45, 80], lift: 1, ms: 260 }]) },
  bounding: { ...DRILL, f: run([{ t: 172, l: [75, 85, 0], r: [-35, 25, 45], a: [-55, 50], b: [85, 70], lift: 9, ms: 300 },
    { t: 174, l: [10, 20, 15], r: [15, 100, 20], a: [-10, 60], b: [20, 60], ms: 250 }]) },
  strides: { ...DRILL, f: run([{ t: 170, l: [18, 18, 5], r: [-10, 95, 25], a: [-35, 85], b: [30, 85], ms: 170 },
    { t: 170, l: [-30, 35, 40], r: [50, 85, 5], a: [35, 85], b: [-40, 85], lift: 3.5, ms: 170 }]) },
  // Runner's must-have: two-leg hip hinge with a weight in the hands
  rdl: { f: [{ t: 180, a: [3, 5], b: [-3, 5], l: [3, 10, -7], r: [3, 10, -7], ms: 1100, hold: 300 },
    { t: 104, a: [2, 0], b: [2, 0], l: [15, 20, -5], r: [15, 20, -5], ms: 1400, hold: 400 }] },
  // feedback railway#203 — the rest of the Runner's must-have
  monster_walk: { ...DRILL, ease: "sine", f: run([{ t: 166, a: [45, 45], b: [35, 45], l: [36, 48, 10], r: [-6, 36, 28], ms: 650 }]) },
  bulgarian_ss: { mode: "hold", pin: "toeN", f: [
    { t: 176, a: [4, 8], b: [-4, 8], l: [33, 24, 9], r: [-44, 27, 113], ms: 1300, hold: 300 },
    { t: 168, a: [10, 8], b: [2, 8], l: [85, 75, 10], r: [-24, 105, 56], ms: 1400, hold: 300 }],
    props: [{ k: "box", j: "toeF", x0: -8, x1: 3, dy: 0.6 }] },
  pallof: { f: [{ t: 180, a: [-8, 128], b: [-8, 128], l: [10, 18, 8], r: [10, 18, 8], ms: 900, hold: 300 },
    { t: 180, a: [88, 0], b: [88, 0], l: [10, 18, 8], r: [10, 18, 8], ms: 800, hold: 1200 }] },
  sl_hops: { pin: "hip", f: [{ t: 178, a: [10, 20], b: [-10, 20], l: [12, 25, 5], r: [35, 85, 20], ms: 260 },
    { t: 180, a: [5, 15], b: [-5, 15], l: [3, 6, 35], r: [35, 85, 20], lift: 6, ms: 260 }] },
  step_down: { mode: "hold", ground: FLOOR - 10, pin: "toeN", f: [
    { t: 180, a: [55, 25], b: [55, 25], l: [6, 7, -1], r: [28, 24, 20], ms: 1200, hold: 300 },
    { t: 166, a: [72, 12], b: [72, 12], l: [48, 71, -23], r: [29, 0, 49], ms: 1600, hold: 300 }],
    props: [{ k: "step", j: "toeN", x0: -17, x1: 1 }] },
  // owner request 2026-10-05 — bedtime mobility
  mob_calf_wall: { mode: "hold", pin: "toeN", f: [
    { t: 165, a: [100, 25], b: [100, 25], l: [-18, 0, -18], r: [32, 30, 2], ms: 1500, hold: 300 },
    { t: 150, a: [104, 30], b: [104, 30], l: [-28, 0, -28], r: [39, 48, -9], ms: 1500, hold: 2200 }],
    props: [{ k: "wall", j: "handN", dx: 1.2 }] },
  mob_soleus_wall: { mode: "hold", pin: "toeN", f: [
    { t: 172, a: [98, 30], b: [98, 30], l: [15, 52, -37], r: [40, 43, -3], ms: 1500, hold: 300 },
    { t: 166, a: [100, 35], b: [100, 35], l: [17, 72, -55], r: [53, 75, -22], ms: 1500, hold: 2200 }],
    props: [{ k: "wall", j: "handN", dx: 1.2 }] },
  mob_knee_wall: { mode: "hold", pin: "toeN", f: [
    { t: 176, a: [92, 35], b: [92, 35], l: [24, 24, 0], r: [-24, 0, -9], ms: 1000, hold: 200 },
    { t: 172, a: [96, 45], b: [96, 45], l: [42, 67, -26], r: [-8, 51, -31], ms: 1000, hold: 300 }],
    props: [{ k: "wall", j: "toeN", dx: 9 }] },
  mob_foot_ball: { mode: "hold", pin: "hip", f: [
    { t: 180, a: [15, 45], b: [15, 45], l: [103, 88, 15], r: [90, 90, 0], ms: 1200 },
    { t: 180, a: [15, 45], b: [15, 45], l: [103, 118, -15], r: [90, 90, 0], ms: 1200 }],
    props: [{ k: "box", j: "hip", x0: -12, x1: 5, dy: 2 }, { k: "ball", j: "ankleN", dx: 2, dy: 2.2, live: true }] },
  mob_toes: { mode: "hold", pin: "toeN", f: [
    { t: 180, a: [30, 40], b: [30, 40], l: [0, 110, -20], r: [0, 110, -20], ms: 1500, hold: 300 },
    { t: 188, a: [55, 40], b: [55, 40], l: [70, 180, -20], r: [70, 180, -20], ms: 1500, hold: 1500 }] },
  mob_hamstring_strap: { mode: "hold", pin: "hip", f: [
    { t: -90, a: [119, 0], b: [119, 0], l: [140, 8, -20], r: [90, 0, 0], ms: 1500, hold: 300 },
    { t: -90, a: [135, 0], b: [135, 0], l: [166, 8, -20], r: [90, 0, 0], ms: 1500, hold: 2000 }],
    props: [{ k: "line", j: "handN", j2: "toeN", live: true }] },
  mob_hip_flexor: { mode: "hold", pin: "kneeN", f: [
    { t: 180, a: [25, 70], b: [25, 70], l: [5, 95, 90], r: [82, 51, 31], ms: 1500, hold: 300 },
    { t: 183, a: [25, 70], b: [25, 70], l: [-17.5, 72.5, 90], r: [93, 86, 7], ms: 1500, hold: 2000 }] },
  mob_quad_side: { mode: "hold", pin: "hip", f: [
    { t: -90, h: 0, a: [100, 0], b: [80, 0], l: [90, -110, 0], r: [90, 0, 0], ms: 1500, hold: 300 },
    { t: -90, h: 0, a: [112, 0], b: [80, 0], l: [92, -155, 0], r: [90, 0, 0], ms: 1500, hold: 2000 }] },
  mob_figure4: { pts: [
    { p: { head: [16, 80], neck: [23, 82], hip: [47, 82], elbowN: [36, 72], handN: [51, 70], kneeF: [56, 67], ankleF: [71, 73], toeF: [74, 68],
      kneeN: [63, 79], ankleN: [57, 68], toeN: [55, 63] }, ms: 1300, hold: 300 },
    { p: { head: [16, 80], neck: [23, 82], hip: [47, 82], elbowN: [34, 70], handN: [47, 66], kneeF: [51, 63], ankleF: [66, 66], toeF: [69, 61],
      kneeN: [59, 76], ankleN: [52, 64], toeN: [50, 59] }, ms: 1300, hold: 2000 }],
    lines: [[["hip", "kneeF", "ankleF", "toeF"], 1], [["neck", "hip"], 0], [["hip", "kneeN", "ankleN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]] },
  mob_9090: { pts: [
    { p: { ...SEATED_FRONT, kneeN: [48, 66], ankleN: [43, 84], toeN: [40, 85], kneeF: [72, 66], ankleF: [77, 84], toeF: [80, 85] }, ms: 900, hold: 200 },
    { p: { ...SEATED_FRONT, kneeN: [38, 78], ankleN: [47, 84], toeN: [45, 85], kneeF: [56, 74], ankleF: [74, 84], toeF: [77, 85] }, ms: 1100, hold: 500 },
    { p: { ...SEATED_FRONT, kneeN: [48, 66], ankleN: [43, 84], toeN: [40, 85], kneeF: [72, 66], ankleF: [77, 84], toeF: [80, 85] }, ms: 1100, hold: 200 },
    { p: { ...SEATED_FRONT, kneeN: [64, 74], ankleN: [46, 84], toeN: [43, 85], kneeF: [82, 78], ankleF: [73, 84], toeF: [75, 85] }, ms: 1100, hold: 500 }],
    lines: SEATED_LINES },
  mob_butterfly: { pts: [
    { p: { ...SEATED_FRONT, elbowN: [51, 71], handN: [56, 81], elbowF: [69, 71], handF: [64, 81], kneeN: [41, 77], ankleN: [57, 83], toeN: [59, 85], kneeF: [79, 77], ankleF: [63, 83], toeF: [61, 85] }, ms: 1300, hold: 300 },
    { p: { ...SEATED_FRONT, head: [60, 54], neck: [60, 61], shN: [55, 63], shF: [65, 63], elbowN: [51, 73], handN: [56, 81], elbowF: [69, 73], handF: [64, 81],
      kneeN: [39, 80], ankleN: [57, 83], toeN: [59, 85], kneeF: [81, 80], ankleF: [63, 83], toeF: [61, 85] }, ms: 1500, hold: 1800 }],
    lines: SEATED_LINES },
  mob_it_cross: { pts: [
    { p: { ...SUPINE_TOP, kneeN: [69, 62], ankleN: [86, 61], toeN: [89, 61] }, ms: 1300, hold: 300 },
    { p: { ...SUPINE_TOP, kneeN: [66, 72], ankleN: [78, 82], toeN: [81, 83.5], hip: [52, 65] }, ms: 1500, hold: 2000 }],
    lines: TOP_LINES, floor: false },
  mob_lumbar_rot: { pts: [
    { p: { ...SUPINE_TOP_HOOK, kneeN: [63, 62.5], kneeF: [63, 65.5] }, ms: 900, hold: 100 },
    { p: { ...SUPINE_TOP_HOOK, kneeN: [61, 51], kneeF: [64, 54] }, ms: 1100, hold: 400 },
    { p: { ...SUPINE_TOP_HOOK, kneeN: [63, 62.5], kneeF: [63, 65.5] }, ms: 1100, hold: 100 },
    { p: { ...SUPINE_TOP_HOOK, kneeN: [64, 75], kneeF: [61, 78] }, ms: 1100, hold: 400 }],
    lines: TOP_LINES, floor: false },
  mob_knees_chest: { mode: "hold", pin: "hip", f: [
    { t: -90, a: [117, 0], b: [117, 0], l: [160, 125, 20], r: [160, 125, 20], ms: 1500, hold: 200 },
    { t: -92, a: [123, 0], b: [123, 0], l: [175, 130, 20], r: [175, 130, 20], ms: 1500, hold: 900 }] },
  mob_child: { mode: "hold", pin: "kneeN", f: [
    { t: 100, a: [22, 0], b: [22, 0], l: [0, 90, 90], r: [0, 90, 90], ms: 1500, hold: 300 },
    { t: 80, h: 20, a: [82, 0], b: [82, 0], l: [62, 152, 90], r: [62, 152, 90], ms: 1800, hold: 2400 }] },
  mob_cat_cow: { pts: [
    { p: { ...QUAD_PTS, mid: [53, 71], head: [32, 59] }, ms: 1500, hold: 300 },
    { p: { ...QUAD_PTS, mid: [53, 57], head: [35, 70.5] }, ms: 1500, hold: 300 }],
    lines: [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF"], 1], [["neck", "mid", "hip"], 0], [["hip", "kneeN", "ankleN"], 0], [["neck", "elbowN", "handN"], 0]] },
  mob_open_book: { pts: [
    { p: { ...SIDE_TOP, elbowN: [32, 71], handN: [33, 81] }, ms: 1200, hold: 200 },
    { p: { ...SIDE_TOP, elbowN: [31, 60], handN: [32, 57], head: [20.5, 59] }, ms: 1100, hold: 100 },
    { p: { ...SIDE_TOP, elbowN: [30, 52], handN: [30, 42], head: [21, 57] }, ms: 1100, hold: 900 },
    { p: { ...SIDE_TOP, elbowN: [31, 60], handN: [32, 57], head: [20.5, 59] }, ms: 1100, hold: 100 }],
    lines: [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF", "toeF"], 1], [["neck", "hip"], 0], [["hip", "kneeN", "ankleN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]], floor: false },
  mob_thread_needle: { mode: "hold", pin: "kneeN", f: [
    { t: 100, a: [22, 0], b: [22, 0], l: [0, 90, 90], r: [0, 90, 90], ms: 1200, hold: 200 },
    { t: 86, h: 15, a: [-62, 0], b: [32, 25], l: [0, 90, 90], r: [0, 90, 90], ms: 1400, hold: 1200 },
    { t: 100, a: [22, 0], b: [22, 0], l: [0, 90, 90], r: [0, 90, 90], ms: 1200, hold: 200 },
    { t: 102, h: -10, a: [180, 0], b: [22, 0], l: [0, 90, 90], r: [0, 90, 90], ms: 1300, hold: 900 }] },
  mob_doorway_chest: { pin: "handN", f: [
    { t: 180, a: [-70, -110], b: [5, 10], l: [0, 0, 0], r: [0, 0, 0], ms: 1400, hold: 300 },
    { t: 173, a: [-100, -80], b: [5, 10], l: [20, 6, 14], r: [-12, 8, -4], ms: 1500, hold: 2000 }],
    props: [{ k: "wall", j: "handN", dx: -1.6 }] },
  mob_cross_body: { pts: [
    { p: { ...STAND_FRONT, elbowN: [51, 40], handN: [50, 50], elbowF: [69, 40], handF: [70, 50] }, ms: 1200, hold: 300 },
    { p: { ...STAND_FRONT, elbowN: [64, 31], handN: [75, 30], elbowF: [72, 39], handF: [65, 32] }, ms: 1300, hold: 2000 }],
    lines: FRONT_LINES },
  mob_neck_side: { pts: [
    { p: { ...STAND_FRONT, elbowN: [51, 40], handN: [50, 50], elbowF: [69, 40], handF: [70, 50] }, ms: 1200, hold: 300 },
    { p: { ...STAND_FRONT, head: [55.5, 21.6], shF: [66, 30.5], elbowN: [51, 40], handN: [50, 50], elbowF: [69, 41], handF: [70, 51] }, ms: 1300, hold: 1600 },
    { p: { ...STAND_FRONT, elbowN: [51, 40], handN: [50, 50], elbowF: [69, 40], handF: [70, 50] }, ms: 1200, hold: 300 },
    { p: { ...STAND_FRONT, head: [64.5, 21.6], shN: [54, 30.5], elbowN: [51, 41], handN: [50, 51], elbowF: [69, 40], handF: [70, 50] }, ms: 1300, hold: 1600 }],
    lines: FRONT_LINES },
  mob_chin_tuck: { mode: "hold", pin: "hip", f: [
    { t: 180, h: -16, a: [15, 45], b: [15, 45], l: [90, 90, 0], r: [90, 90, 0], ms: 900, hold: 300 },
    { t: 182, h: 8, a: [15, 45], b: [15, 45], l: [90, 90, 0], r: [90, 90, 0], ms: 900, hold: 1500 }],
    props: [{ k: "box", j: "hip", x0: -12, x1: 5, dy: 2 }] },
  mob_legs_wall: { mode: "hold", pin: "hip", f: [
    { t: -90, a: [80, 0], b: [80, 0], l: [178, 0, 90], r: [178, 0, 90], ms: 4000 },
    { t: -91, a: [80, 0], b: [80, 0], l: [176, 6, 90], r: [176, 6, 90], ms: 4000 }],
    props: [{ k: "wall", j: "ankleN", dx: 3.2 }] },
  mob_breathing: { mode: "hold", pin: "hip", f: [
    { t: -90, a: [148, -96], b: [97, 0], l: [125, 95, 30], r: [125, 95, 30], ms: 6000 },
    { t: -93, a: [152, -94], b: [97, 0], l: [125, 95, 30], r: [125, 95, 30], ms: 4000 }] },
}
// the same movement as an existing figure (the dose / variant differs, not the motion)
SPECS.pogo_hops = SPECS.hops
SPECS.sl_calf_slow = SPECS.heel_raise_1
SPECS.copenhagen_hold = SPECS.copenhagen
SPECS.side_plank_abd = SPECS.side_plank
SPECS.mob_child_side = SPECS.mob_child

export const hasFigure = (id: string) => id in SPECS

// ---- layout -------------------------------------------------------------------------
type Box = { x0: number; x1: number; y0: number; y1: number }
/** Union box of the key frames (head included), down to the floor. */
function bbox(frames: Record<string, V>[], spec: Spec): Box {
  const pts = frames.flatMap((j) => Object.entries(j).flatMap(([k, v]) => k === "head" ? [[v[0] - HR, v[1] - HR], [v[0] + HR, v[1] + HR]] as V[] : [v]))
  const xs = pts.map((v) => v[0]), ys = pts.map((v) => v[1])
  const arrow = (spec.props || []).some((p) => p.k === "arrow")
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: FLOOR + (arrow ? 7 : 3) }
}
/** Lying exercises fill the frame: "y" crops the empty space above the figure (the
 *  detail keeps one horizontal scale for all exercises), "xy" crops both ways (thumbs). */
function viewBoxOf(b: Box, crop: "y" | "xy") {
  if (crop === "y") {
    const top = Math.max(0, Math.min(b.y0 - 9, b.y1 - 44))
    return `0 ${top.toFixed(1)} ${W} ${(b.y1 - top).toFixed(1)}`
  }
  const pad = 4
  const x0 = Math.max(0, b.x0 - pad), x1 = Math.min(W, b.x1 + pad)
  const top = Math.max(0, b.y0 - pad)
  return `${x0.toFixed(1)} ${top.toFixed(1)} ${(x1 - x0).toFixed(1)} ${(b.y1 - top).toFixed(1)}`
}
type Frame = { j: Record<string, V> }
function build(spec: Spec) {
  const ground = spec.ground ?? FLOOR
  const pin = spec.pin || "toeN"
  if (spec.pts) {
    const all = spec.pts.flatMap((f) => Object.values(f.p))
    const xs = all.map((v) => v[0])
    const dx = W / 2 - (Math.min(...xs) + Math.max(...xs)) / 2
    const place = (u: PtsPose) => shift(u.p, [dx, 0])
    return { place, ref: shift(spec.pts[0].p, [dx, 0]), box: bbox(spec.pts.map(place), spec) }
  }
  const f = spec.f!
  const raw0 = fk(f[0])
  const d0: V = [-raw0[pin][0], ground - lowest(raw0) - (f[0].lift || 0)]
  const ref0 = shift(raw0, d0)
  const placeRaw = (p: Pose) => {
    const j = fk(p)
    if (spec.mode === "hold") return shift(j, sub(ref0[pin], j[pin]))
    return shift(j, [-j[pin][0], ground - lowest(j) - (p.lift || 0)])
  }
  // centre the union of the key frames horizontally
  const xs = f.flatMap((p) => Object.values(placeRaw(p)).map((v) => v[0]))
  const cx = W / 2 - (Math.min(...xs) + Math.max(...xs)) / 2
  const place = (p: Pose) => shift(placeRaw(p), [cx, 0])
  return { place, ref: shift(ref0, [cx, 0]), box: bbox(f.map(place), spec) }
}

const ease = (u: number, kind?: string) => (kind === "lin" ? u : 0.5 - Math.cos(Math.PI * u) / 2)
function poseAt(spec: Spec, ms: number): Pose | PtsPose {
  const frames = (spec.f || spec.pts)! as (Pose | PtsPose)[]
  const n = frames.length
  const total = frames.reduce((s, x) => s + (x.ms || 600) + (x.hold || 0), 0)
  let t = ms % total
  for (let k = 0; k < n; k++) {
    const to = frames[(k + 1) % n]
    const mv = to.ms || 600
    if (t < mv) {
      const u = ease(t / mv, spec.ease)
      return spec.f ? mixPose(frames[k] as Pose, to as Pose, u) : mixPts(frames[k] as PtsPose, to as PtsPose, u)
    }
    t -= mv
    if (t < (to.hold || 0)) return to
    t -= to.hold || 0
  }
  return frames[0]
}

const path = (j: Record<string, V>, names: string[]) => names.filter((n) => j[n]).map((n, i) => `${i ? "L" : "M"}${j[n][0].toFixed(2)} ${j[n][1].toFixed(2)}`).join(" ")
const SIDE_LINES: [string[], 0 | 1][] = [[["neck", "elbowF", "handF"], 1], [["hip", "kneeF", "ankleF"], 1], [["heelF", "toeF"], 1],
  [["hip", "neck"], 0], [["hip", "kneeN", "ankleN"], 0], [["heelN", "toeN"], 0], [["neck", "elbowN", "handN"], 0]]

function Props({ props, ref0, j, live }: { props: Prop[]; ref0: Record<string, V>; j: Record<string, V>; live: boolean }) {
  return <>{props.filter((p) => !!p.live === live).map((p, i) => {
    const at = p.j ? (live ? j : ref0)[p.j] : undefined
    const x = (at?.[0] ?? 0) + (p.dx || 0), y = (at?.[1] ?? 0) + (p.dy || 0)
    switch (p.k) {
      case "wall": return <line key={i} x1={x} y1={FLOOR} x2={x} y2={10} strokeWidth={2.2} stroke="currentColor" opacity={0.45} />
      case "step": return <rect key={i} x={x + (p.x0 || 0) - (p.dx || 0)} y={y + 0.8} width={(p.x1 || 0) - (p.x0 || 0)} height={Math.max(0, FLOOR - y - 0.8)} rx={1} fill="currentColor" fillOpacity={0.1} stroke="currentColor" strokeOpacity={0.45} strokeWidth={1.2} />
      case "rect": return <rect key={i} x={p.x0} y={p.y! + 0.8} width={(p.x1 || 0) - (p.x0 || 0)} height={FLOOR - p.y! - 0.8} rx={1} fill="currentColor" fillOpacity={0.1} stroke="currentColor" strokeOpacity={0.45} strokeWidth={1.2} />
      case "box": return <rect key={i} x={x + (p.x0 || 0) - (p.dx || 0)} y={y} width={(p.x1 || 0) - (p.x0 || 0)} height={Math.max(0, FLOOR - y)} rx={1.5} fill="currentColor" fillOpacity={0.1} stroke="currentColor" strokeOpacity={0.45} strokeWidth={1.2} />
      case "towel": return <ellipse key={i} cx={x - 0.5} cy={FLOOR - 1.6} rx={2.6} ry={1.6} fill="currentColor" fillOpacity={0.35} />
      case "weight": return <rect key={i} x={x - 3} y={y - 2.2} width={6} height={4.4} rx={1.2} fill="currentColor" fillOpacity={0.55} />
      case "bar": return <line key={i} x1={x - 3.5} y1={y} x2={x + 3.5} y2={y} strokeWidth={2.4} stroke="currentColor" opacity={0.6} strokeLinecap="round" />
      case "ball": return <circle key={i} cx={x} cy={y} r={1.9} fill="currentColor" fillOpacity={0.55} />
      case "line": { const b = p.j2 ? (live ? j : ref0)[p.j2] : undefined
        return b ? <line key={i} x1={x} y1={y} x2={b[0]} y2={b[1]} strokeWidth={1.2} stroke="currentColor" opacity={0.7} strokeDasharray="2 1.4" /> : null }
      case "arrow": return <g key={i} opacity={0.5} stroke="currentColor" strokeWidth={1.2} fill="none" strokeLinecap="round"><path d={`M${W - 32} ${FLOOR + 3.5}H${W - 12}`} /><path d={`M${W - 15.5} ${FLOOR + 1.2}L${W - 12} ${FLOOR + 3.5}L${W - 15.5} ${FLOOR + 5.8}`} /></g>
      default: return null
    }
  })}</>
}

function Figure({ spec, pose, layout, className, crop = "y" }: { spec: Spec; pose: Pose | PtsPose; layout: ReturnType<typeof build>; className?: string; crop?: "y" | "xy" }) {
  const j = layout.place(pose as any)
  const lines = spec.lines || SIDE_LINES
  const props = spec.props || []
  return (
    <svg viewBox={viewBoxOf(layout.box, crop)} className={className} role="img" aria-hidden="true">
      <g className="text-fg-3">
        {spec.floor !== false && <line x1={4} y1={FLOOR} x2={W - 4} y2={FLOOR} stroke="currentColor" strokeWidth={1} opacity={0.5} />}
        <Props props={props} ref0={layout.ref} j={j} live={false} />
      </g>
      <g className="text-accent" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
        {lines.filter(([, w]) => w === 1).map(([n], i) => <path key={"f" + i} d={path(j, n)} strokeWidth={2.8} opacity={0.4} />)}
        {lines.filter(([, w]) => w === 0).map(([n], i) => <path key={"n" + i} d={path(j, n)} strokeWidth={3.4} />)}
        <circle cx={j.head[0]} cy={j.head[1]} r={HR} strokeWidth={2.6} fill="currentColor" fillOpacity={0.18} />
      </g>
      <g className="text-fg-2"><Props props={props} ref0={layout.ref} j={j} live /></g>
    </svg>
  )
}

/** Small static figure for lists. */
export function ExerciseThumb({ id, className = "size-10" }: { id: string; className?: string }) {
  const spec = SPECS[id]
  const layout = useMemo(() => (spec ? build(spec) : null), [spec])
  if (!spec || !layout) return null
  const frames = (spec.f || spec.pts)! as (Pose | PtsPose)[]
  return <Figure spec={spec} pose={frames[Math.min(spec.thumb ?? 1, frames.length - 1)]} layout={layout} className={className} crop="xy" />
}

/** Animated figure for the exercise detail; pauses on request or with reduced motion. */
export function ExerciseFigure({ id, className = "w-full" }: { id: string; className?: string }) {
  const spec = SPECS[id]
  const layout = useMemo(() => (spec ? build(spec) : null), [spec])
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  const [playing, setPlaying] = useState(!reduced)
  const [ms, setMs] = useState(0)
  const t0 = useRef<number | null>(null)
  const base = useRef(0)
  useEffect(() => {
    if (!playing || !spec) return
    let raf = 0
    t0.current = null
    const tick = (now: number) => {
      if (t0.current == null) t0.current = now - base.current
      const t = now - t0.current
      base.current = t
      setMs(t)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, spec])
  if (!spec || !layout) return null
  return (
    <div className="relative">
      <Figure spec={spec} pose={poseAt(spec, ms)} layout={layout} className={className} />
      <button type="button" onClick={() => setPlaying((v) => !v)} aria-label={playing ? "Zastavit animaci" : "Přehrát animaci"} data-testid="figure-toggle"
        className="absolute right-2 top-2 grid size-8 place-items-center rounded-full bg-white/[.06] text-fg-2 transition hover:bg-white/[.12] hover:text-fg">
        {playing ? <Pause className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
      </button>
    </div>
  )
}

/** Static figure at a given time of the loop (used by the exercise-figure check script). */
export function ExerciseFrame({ id, ms, className = "w-full" }: { id: string; ms: number; className?: string }) {
  const spec = SPECS[id]
  const layout = useMemo(() => (spec ? build(spec) : null), [spec])
  if (!spec || !layout) return null
  return <Figure spec={spec} pose={poseAt(spec, ms)} layout={layout} className={className} />
}
export const figureIds = () => Object.keys(SPECS)
/** When each key frame is fully reached in the loop (the figure check renders them). */
export const figureKeyTimes = (id: string) => {
  const fr = ((SPECS[id]?.f || SPECS[id]?.pts || []) as { ms?: number; hold?: number }[])
  const out = [0]
  let t = 0
  for (let k = 1; k < fr.length; k++) { t += fr[k].ms || 600; out.push(t); t += fr[k].hold || 0 }
  return out
}
export const figureLoopMs = (id: string) => ((SPECS[id]?.f || SPECS[id]?.pts || []) as { ms?: number; hold?: number }[]).reduce((s, x) => s + (x.ms || 600) + (x.hold || 0), 0)
