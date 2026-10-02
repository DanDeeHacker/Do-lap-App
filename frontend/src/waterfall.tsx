// A compact horizontal waterfall (feedback #146, #149): a starting total, the steps that
// raise (green) or lower (red) it, and the resulting total — one row each, so it reads
// on a phone. Steps float from the running total; totals start at the axis.
import type { ReactNode } from "react"
import { C } from "@/tokens"

export type WStep = {
  key: string
  label: ReactNode
  sub?: ReactNode
  delta?: number          // a step (signed)
  total?: number          // a total bar (absolute)
  color?: string          // overrides the default colour
  value?: ReactNode       // overrides the printed value
}

export function Waterfall({ steps, lo = 0, hi, unit = "", dec = 0, testid }: {
  steps: WStep[]; lo?: number; hi?: number; unit?: string; dec?: number; testid?: string
}) {
  let run = 0
  const rows = steps.map((s) => {
    if (s.total != null) {
      run = s.total
      return { s, a: lo, b: s.total }
    }
    const a = run
    run += s.delta || 0
    return { s, a, b: run }
  })
  const top = hi ?? Math.max(...rows.map((r) => Math.max(r.a, r.b)), lo + 1)
  const span = Math.max(top - lo, 1e-9)
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / span) * 100))}%`
  const fmt = (v: number) => (Math.round(v * 10 ** dec) / 10 ** dec).toLocaleString("cs-CZ")
  return (
    <ul className="mt-2 space-y-1.5" data-testid={testid}>
      {rows.map(({ s, a, b }) => {
        const isTotal = s.total != null
        const d = s.delta || 0
        const col = s.color || (isTotal ? C.fg2 : d > 0 ? C.ok : d < 0 ? C.alert : C.fg3)
        const x0 = Math.min(a, b), x1 = Math.max(a, b)
        const val = s.value ?? (isTotal ? `${fmt(s.total!)}${unit}` : d === 0 ? `0${unit}` : `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}${unit}`)
        return (
          <li key={s.key} className="flex items-center gap-2.5">
            <span className="w-[40%] min-w-0 shrink-0">
              <span className={`block truncate text-[12px] ${isTotal ? "font-extrabold text-fg" : "font-bold text-fg-soft"}`}>{s.label}</span>
              {s.sub && <span className="block truncate text-[10.5px] leading-[14px] text-fg-3">{s.sub}</span>}
            </span>
            <span className="relative h-3.5 flex-1 rounded-[4px] bg-white/[.05]">
              {!isTotal && <i className="absolute inset-y-0 w-px bg-white/25" style={{ left: pos(a) }} />}
              <i className="absolute inset-y-0 rounded-[3px]"
                style={{ left: pos(x0), width: `max(3px, calc(${pos(x1)} - ${pos(x0)}))`, background: col, opacity: isTotal ? 0.9 : 1 }} />
            </span>
            <span className="w-14 shrink-0 text-right text-[12px] font-bold tabular-nums" style={{ color: isTotal ? C.fg : col }}>{val}</span>
          </li>
        )
      })}
    </ul>
  )
}
