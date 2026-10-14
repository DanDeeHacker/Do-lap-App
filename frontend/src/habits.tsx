// Owner decision 2026-10-14 — engagement that rewards habits, never volume (metrics/habits.py):
// the weeks kept inside the limits with the strength programme done (a pause for illness, pain or a
// week off neither counts nor breaks the run), and milestones for habits — earned once and kept.
// Trénink → Tento týden → Návyky (one row, the rest in a sheet); a newly earned milestone is
// announced once on Dnes.
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { CalendarCheck, ChevronRight, Dumbbell, Footprints, HeartPulse, Moon, NotebookPen, Repeat, Trophy, X, type LucideIcon } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { InfoDot, Label, Sheet } from "@/ui"
import { fmtD, plural } from "@/lib"
import { C } from "@/tokens"

const ICON: Record<string, LucideIcon> = {
  calendar: CalendarCheck, trophy: Trophy, dumbbell: Dumbbell, notebook: NotebookPen, moon: Moon, footprints: Footprints, repeat: Repeat, heart: HeartPulse,
}
const ST: Record<string, { col: string; label: string }> = {
  kept: { col: C.ok, label: "v pásmu" },
  missed: { col: C.watch, label: "mimo pásmo" },
  paused: { col: "rgba(255,255,255,.16)", label: "pauza" },
  now: { col: "transparent", label: "tento týden" },
}
const RULES = "Týden se počítá, když jste trénovali, zátěž ani jeden den nepřekročila práh 25 a posilování z programu Runner's must-have proběhlo, jak program chce (2× týdně, v lehčích týdnech 1×). Nemoc, bolest nebo týden bez tréninku řadu nepřeruší, jen se nepočítá: nikdo nemá trénovat nemocný nebo přes bolest, aby si řadu udržel. Kilometry ani tempo se tu nepočítají."

let cache: { key: string; data: any } | null = null
export function useHabits(): any | null {
  const { me, boot } = useApp()
  const rid = me?.runner_id || ""
  const key = `${rid}|${boot?.assessment?.computed_at || ""}`
  const [d, setD] = useState<any | null>(cache?.key === key ? cache.data : null)
  useEffect(() => {
    if (!rid) return
    if (cache?.key === key) { setD(cache.data); return }
    let alive = true
    api.habits(rid).then((x: any) => { cache = { key, data: x }; if (alive) setD(x) }).catch(() => {})
    return () => { alive = false }
  }, [rid, key])
  return d
}

const range = (w: any) => `${fmtD(w.start)} – ${fmtD(w.end)}`

function Badge({ m, size = 34 }: { m: any; size?: number }) {
  const Icon = ICON[m.icon] || Trophy
  const on = !!m.earned
  return (
    <span className="grid shrink-0 place-items-center rounded-full" title={m.title}
      style={{ width: size, height: size, background: on ? `${C.accent}22` : "rgba(255,255,255,.05)", color: on ? C.accent : C.fg3, boxShadow: on ? `inset 0 0 0 1.5px ${C.accent}66` : undefined }}>
      <Icon className="size-[45%]" aria-hidden />
    </span>
  )
}

function MilestoneList({ ms }: { ms: any[] }) {
  const earned = ms.filter((m) => m.earned), left = ms.filter((m) => !m.earned)
  return (
    <ul className="mt-2 grid gap-3">
      {[...earned, ...left].map((m) => (
        <li key={m.id} className="flex gap-3" data-testid={`milestone-${m.id}`}>
          <Badge m={m} size={40} />
          <span className="min-w-0 flex-1">
            <b className={`block text-[14px] font-bold ${m.earned ? "text-fg" : "text-fg-2"}`}>{m.title}</b>
            <span className="mt-0.5 block text-[12px] leading-[17px] text-fg-3">{m.text}</span>
            {m.earned ? <span className="mt-1 block text-[11.5px] font-semibold text-accent">{`Získáno ${fmtD(m.earned)}`}</span>
              : m.need > 1 && (
                <span className="mt-1.5 flex items-center gap-2">
                  <span className="relative block h-1.5 flex-1 rounded-full bg-white/[.08]"><i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, (m.have / m.need) * 100)}%`, background: C.info }} /></span>
                  <span className="shrink-0 text-[11px] tabular-nums text-fg-3">{`${m.have} z ${m.need}`}</span>
                </span>
              )}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Everything about the habits in one sheet: the run of weeks, the last 12 weeks, the milestones. */
function HabitsSheet({ h, open, onClose }: { h: any; open: boolean; onClose: () => void }) {
  const [sel, setSel] = useState<number | null>(null)
  const ws: any[] = (h.weeks || []).slice(-12)
  const ms: any[] = h.milestones || []
  const w = sel != null ? ws[sel] : null
  return (
    <Sheet open={open} onClose={onClose}>
      <div data-testid="habits-sheet">
        <span className="flex items-center gap-1.5"><Label>Návyky</Label><InfoDot label="Týdny v bezpečném pásmu" text={RULES} /></span>
        <p className="mt-2 flex flex-wrap items-baseline gap-x-2">
          <b className="t-num text-[30px] leading-none text-fg" data-testid="habits-chain">{h.chain}</b>
          <span className="text-[13px] text-fg-2">{`${plural(h.chain, "týden", "týdny", "týdnů")} v řadě v bezpečném pásmu`}</span>
          {h.best > h.chain && <span className="text-[12px] text-fg-3">{`· nejdelší řada ${h.best}`}</span>}
        </p>
        <div className="mt-3 grid gap-1" style={{ gridTemplateColumns: `repeat(${ws.length}, minmax(0, 1fr))` }} role="list" aria-label="Posledních 12 týdnů">
          {ws.map((x, i) => {
            const s = ST[x.status] || ST.paused
            return (
              <button key={x.start} type="button" role="listitem" onClick={() => setSel(sel === i ? null : i)} aria-label={`${range(x)}: ${s.label}`} title={`${range(x)}: ${s.label}`}
                data-testid={`habit-week-${x.status}`}
                className={`h-7 rounded-[6px] transition ${sel === i ? "ring-2 ring-fg/60" : ""}`}
                style={{ background: s.col, boxShadow: x.status === "now" ? `inset 0 0 0 1.5px ${C.fg3}` : undefined,
                  backgroundImage: x.status === "paused" ? "repeating-linear-gradient(135deg, rgba(255,255,255,.10) 0 2px, transparent 2px 5px)" : undefined }} />
            )
          })}
        </div>
        <p className="mt-1.5 min-h-[18px] text-[11.5px] text-fg-3" aria-live="polite">
          {w ? <>{`${range(w)} · `}<b className="text-fg-2">{(ST[w.status] || ST.paused).label}</b>{w.why ? ` (${w.why})` : ""}{w.strength && w.status !== "missed" ? ` · posilování ${w.strength[0]} z ${w.strength[1]}` : ""}</>
            : <span className="flex flex-wrap gap-x-3">{(["kept", "paused", "missed"] as const).map((k) => <span key={k} className="inline-flex items-center gap-1"><i className="inline-block size-2 rounded-[3px]" style={{ background: ST[k].col }} />{ST[k].label}</span>)}</span>}
        </p>
        {ms.length > 0 && (
          <div className="mt-4 border-t border-white/[.07] pt-3">
            <Label>{`Milníky ${ms.filter((m) => m.earned).length} z ${ms.length}`}</Label>
            <p className="mt-1 text-[12px] leading-[17px] text-fg-3">Za návyky, které chrání před zraněním. Získaný milník už vám zůstane.</p>
            <MilestoneList ms={ms} />
          </div>
        )}
      </div>
    </Sheet>
  )
}

/** Trénink → Tento týden: one quiet row (the run of weeks, the milestones); the rest in a sheet.
 *  #navyky (the Dnes milestone notice) opens it. */
export function HabitsRow() {
  const { touring } = useApp()
  const h = useHabits()
  const [open, setOpen] = useState(() => window.location.hash === "#navyky")
  if (touring || !h || !h.weeks?.length) return null
  const ms: any[] = h.milestones || []
  const close = () => {
    setOpen(false)
    if (window.location.hash === "#navyky") history.replaceState(null, "", window.location.pathname)
  }
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} data-testid="habits-row"
        className="mt-1 flex w-full items-center justify-between gap-2 border-t border-white/[.07] py-3 text-left text-[13px] font-bold text-fg-soft hover:text-fg">
        <span>Návyky</span>
        <span className="flex min-w-0 items-center gap-1.5 text-[12px] font-semibold text-fg-2">
          <span className="truncate">{`${h.chain} ${plural(h.chain, "týden", "týdny", "týdnů")} v pásmu`}{ms.length ? ` · milníky ${ms.filter((m) => m.earned).length}/${ms.length}` : ""}</span>
          <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
        </span>
      </button>
      <HabitsSheet h={h} open={open} onClose={close} />
    </>
  )
}

/** On Dnes: a milestone earned in the last two weeks, once (settings.badges_seen). */
export function NewMilestone() {
  const { viewing, touring } = useApp()
  const h = useHabits()
  const [seen, setSeen] = useState<string[] | null>(null)
  useEffect(() => {
    let alive = true
    api.getSettings().then((s: any) => alive && setSeen(Array.isArray(s?.badges_seen) ? s.badges_seen : [])).catch(() => {})
    return () => { alive = false }
  }, [])
  if (viewing || touring || !h || seen === null) return null
  const fresh = (h.milestones || []).filter((m: any) => m.recent && !seen.includes(m.id))
  if (!fresh.length) return null
  const m = fresh[0]
  const dismiss = () => {
    const next = [...seen, ...fresh.map((x: any) => x.id)]
    setSeen(next)
    api.patchSettings({ badges_seen: next }).catch(() => {})
  }
  return (
    <section className="card mt-4 flex items-center gap-3 p-3.5" data-testid="new-milestone">
      <Badge m={m} size={40} />
      <span className="min-w-0 flex-1">
        <span className="t-label block !text-accent">Nový milník</span>
        <b className="block truncate text-[14px] text-fg">{m.title}</b>
        <Link to="/app/training#navyky" onClick={dismiss} className="text-[12px] font-bold text-accent">{fresh.length > 1 ? `Zobrazit (${fresh.length})` : "Zobrazit"}</Link>
      </span>
      <button type="button" onClick={dismiss} aria-label="Zavřít" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-white/[.06] hover:text-fg"><X className="size-4" aria-hidden /></button>
    </section>
  )
}
