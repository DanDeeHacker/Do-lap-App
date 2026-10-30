// The physio app's shared pieces (owner request 2026-10-27, report v6 Section 6.2.8).
import { useCallback, useEffect, useState, type ReactNode } from "react"
import { Chip } from "@/ui"
import { QUAD } from "@/lib"

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [d, setD] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const reload = useCallback(() => {
    setErr(null)
    fn().then(setD).catch((e: any) => setErr(e?.message || "Nepodařilo se načíst"))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  return { d, err, reload, setD }
}

export function Loading({ err }: { err: string | null }) {
  return err ? <p className="mt-4 text-sm text-alert">{err}</p> : <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám…</p>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="mt-4 rounded-xl bg-white/[.03] px-4 py-6 text-center text-[13px] text-fg-3">{children}</p>
}

// the engine's risk tier: ok / watch / alert (report: low / medium / high risk)
export const RISK: Record<string, [string, "ok" | "watch" | "alert"]> = {
  ok: ["nízké riziko", "ok"], watch: ["střední riziko", "watch"], alert: ["vysoké riziko", "alert"],
}

export function RiskChip({ tier }: { tier?: string | null }) {
  const r = RISK[tier || ""]
  return r ? <Chip tone={r[1]}>{r[0]}</Chip> : <Chip>bez hodnocení</Chip>
}

export function QuadChip({ q }: { q?: string | null }) {
  return q && QUAD[q] ? <Chip tone="info">{QUAD[q].t}</Chip> : null
}

export const KIND: Record<string, string> = {
  assessment: "Vstupní vyšetření", follow_up: "Kontrola", gait_analysis: "Analýza běhu", video_call: "Videohovor",
}

// the brief's items use <b> and <br> (metrics/ai_brief.py): a <br> becomes a line break (render
// with whitespace-pre-line), the rest of the markup is dropped
export const stripTags = (s: string) => (s || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "")

// review 2026-10-30 N6: the runner's ring shows 100 − overall (railway#99: high = fine); the physio
// app shows the same number, so "Skóre 100" never means a high-risk client
export const shownScore = (overall?: number | null) => (overall == null ? null : 100 - Math.min(100, Math.max(0, overall)))

export function Score({ v, label }: { v?: number | null; label: string }) {
  return (
    <div className="rounded-xl bg-white/[.04] px-3 py-2">
      <p className="text-[11px] text-fg-3">{label}</p>
      <p className="text-[20px] font-bold tabular-nums text-fg">{v == null ? "—" : Math.round(v)}</p>
    </div>
  )
}
