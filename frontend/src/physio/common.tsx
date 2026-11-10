// The physio app's shared pieces (owner request 2026-10-27, report v6 Section 6.2.8).
import { useCallback, useEffect, useState, type ReactNode } from "react"
import { Button, Chip, useToast } from "@/ui"
import { api } from "@/api"
import { QUAD, fmtDT } from "@/lib"

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

// physio brief 2026-11-09 P0.3: stale or missing data is not low risk
export const noData = (a: any) => ["stale", "none"].includes(a?.freshness?.status)

export function RiskChip({ tier, a }: { tier?: string | null; a?: any }) {
  if (a && noData(a)) return <Chip>bez aktuálních dat</Chip>
  const r = RISK[tier || ""]
  return r ? <Chip tone={r[1]}>{r[0]}</Chip> : <Chip>bez hodnocení</Chip>
}

// P0.4: the label that cannot contradict the rest (injury, return to running, no data, then the quadrant)
export function QuadChip({ q, a }: { q?: string | null; a?: any }) {
  const st = a?.display_state
  if (st === "injury") return <Chip tone="alert">Zranění v péči</Chip>
  if (st === "rtr") return <Chip tone="watch">Návrat k běhu</Chip>
  if (st === "unknown") return null
  const k = st || q
  return k && QUAD[k] ? <Chip tone="info">{QUAD[k].t}</Chip> : null
}

// P0.3: the latest pain wherever it was reported, with its age
export function PainAgo({ p }: { p?: any }) {
  if (!p || p.score == null) return <>—</>
  const days = Math.max(0, Math.round((Date.now() - new Date(p.at).getTime()) / 86400000))
  const ago = days === 0 ? "dnes" : days === 1 ? "včera" : `před ${days} dny`
  return <span className={p.score >= 4 && days <= 3 ? "font-bold text-watch" : ""}>{`${p.score}/10 · ${ago}`}</span>
}

export const KIND: Record<string, string> = {
  assessment: "Vstupní vyšetření", follow_up: "Kontrola", gait_analysis: "Analýza běhu", video_call: "Videohovor",
  exam: "Vyšetření",   // physio brief 2026-11-09 P0.11: every kind has a label
}

// the brief's items use <b> and <br> (metrics/ai_brief.py): a <br> becomes a line break (render
// with whitespace-pre-line), the rest of the markup is dropped
export const stripTags = (s: string) => (s || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "")

// review 2026-10-30 N6: the runner's ring shows 100 − overall (railway#99: high = fine); the physio
// app shows the same number, so "Skóre 100" never means a high-risk client
export const shownScore = (overall?: number | null) => (overall == null ? null : 100 - Math.min(100, Math.max(0, overall)))

export function Score({ v, label, hint }: { v?: number | null; label: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-white/[.04] px-3 py-2" title={hint}>
      <p className="text-[11px] text-fg-3">{label}</p>
      <p className="text-[20px] font-bold tabular-nums text-fg">{v == null ? "—" : Math.round(v)}</p>
      <p className="text-[10.5px] text-fg-3">{v == null ? "bez dat" : hint}</p>
    </div>
  )
}

// One vocabulary of body regions, the same as backend/app/regions.py (physio brief 2026-11-09 P0.5).
export const REGIONS: [string, string][] = [
  ["achilles", "Achillova šlacha"], ["calf", "Lýtko"], ["plantar", "Plantární fascie (pata)"],
  ["knee_anterior", "Koleno vpředu"], ["itband", "IT pás a vnější strana kolena"], ["shin", "Holeň"],
  ["hamstring", "Zadní strana stehna"], ["hip", "Kyčel a hýždě"], ["groin", "Tříslo (adduktory)"],
  ["lower_abdomen", "Dolní břicho"], ["other", "Jiné (upřesněte)"],
]

// round 2 F13.1: a booking request the physio can decide on without opening anything else — the same card in
// Kalendář → Žádosti and in Dnes
export function RequestItem({ b, onDone }: { b: any; onDone: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const x = b.detail || {}
  const act = async (k: string, fn: () => Promise<any>, ok: string) => {
    setBusy(k)
    try { await fn(); toast({ title: ok }); onDone() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) } finally { setBusy(null) }
  }
  return (
    <li className="grid gap-1 py-3 text-[13px]" data-testid="request">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-fg">{b.runner?.name || b.name}</b>
        {x.first_visit && <Chip tone="info">první návštěva</Chip>}
        <span className="text-fg-2">{fmtDT(b.slot_at)}</span>
      </div>
      <p className="text-[12.5px] text-fg-2">
        {x.service ? `${x.service.name} · ${x.service.duration_minutes} min` : (KIND[b.kind] || b.kind)}
        {x.price_czk != null ? ` · ${String(x.price_czk).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} Kč` : ""}
        {x.payer_cs ? ` · ${x.payer_cs}` : ""}
      </p>
      {x.reason && <p className="text-[12.5px]"><span className="text-fg-3">{"S čím přichází: "}</span>{x.reason}</p>}
      {x.questions && <p className="text-[12.5px]"><span className="text-fg-3">{"Chce probrat: "}</span>{x.questions}</p>}
      {x.conflict && <p className="text-[12px] font-bold text-alert" data-testid="request-clash">{x.conflict}</p>}
      <div className="mt-1 flex gap-2">
        <Button size="sm" busy={busy === "c"} onClick={() => act("c", () => api.bookingConfirm(b.id), "Termín potvrzen — klient dostal zprávu")}>Potvrdit</Button>
        <Button size="sm" variant="outline" busy={busy === "d"} onClick={() => act("d", () => api.bookingDecline(b.id), "Termín odmítnut")}>Odmítnout</Button>
      </div>
    </li>
  )
}
