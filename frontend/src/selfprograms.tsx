// Feedback railway#116 — exercise programs a runner starts on their own: ready-made ones
// for common running problems (recommended by the pain they marked in the last 4 weeks),
// core and running-drill programs, and an own session picked from the exercise library.
// Content and sources live in backend/app/programs_library.py. Every exercise opens a
// detail with an own illustration, numbered steps and the common faults; Physiopedia is
// only linked for further reading (its licence is non-commercial).
import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, Chip, Label, Sheet, useToast } from "@/ui"
import { BookOpen, Check, ChevronDown, ChevronRight, Dumbbell, ExternalLink, Info, Pause, Play, Plus, RotateCcw, Sparkles, Timer } from "lucide-react"
import { fmtD, plural } from "@/lib"
import { ExerciseFigure, ExerciseThumb, hasFigure } from "@/exfigure"

type Ex = { name: string; area: string; how: string; dose: string; perWeek: number; steps?: string[]; mistakes?: string[]; caution?: string; links?: { url: string; topic: string }[] }
type Phase = { key: string; name: string; goal?: string; from: number; to: number; rpe: string }
type Prog = { key: string; group?: string; physio?: string; name: string; weeks: number; summary: string; exercises: string[]; evidence: string; refs: string[]; assumption: string | null
  perWeek?: number; sessions?: Record<string, string[]>; sessionLabels?: Record<string, string>; sessionDoses?: Record<string, Record<string, string>>; phases?: Phase[] }

/** railway#133 — the most recent marked region, shortened for the chip. */
export function shortRegion(r: string) {
  // "Úpon plantární fascie (pata)" → "Pata", "Lýtko (gastrocnemius)" → "Lýtko": the shorter name wins
  const m = r.match(/^(.*?)\s*\((.+)\)\s*$/)
  let s = m ? (m[2].length < m[1].length ? m[2] : m[1]) : r
  s = s.split(" / ")[0].replace(/\s+[–-]\s+/g, ", ").trim()
  s = s.charAt(0).toUpperCase() + s.slice(1)
  return s.length > 18 ? s.slice(0, 17).trimEnd() + "…" : s
}

// Feedback #163 — each exercise of the running programme as its own module: tick the
// sets one by one (kept on this device for today), a hold timer where the dose has
// seconds, the moving figure inline; the last set logs the exercise as done.
const setsOf = (dose: string) => Math.min(10, Math.max(1, Number((dose.match(/(\d+)\s*×/) || [])[1]) || 1))
const holdOf = (dose: string) => Number((dose.match(/(\d+)\s*s\b/) || [])[1]) || 0
const todayKey = () => new Date().toLocaleDateString("sv-SE")
function loadSets(key: string): number {
  try { return Number(localStorage.getItem(key)) || 0 } catch { return 0 }
}
function saveSets(key: string, n: number) {
  try { if (n) localStorage.setItem(key, String(n)); else localStorage.removeItem(key) } catch { /* private mode */ }
}

function HoldTimer({ secs, onDone }: { secs: number; onDone: () => void }) {
  const [left, setLeft] = useState(secs)
  const [run, setRun] = useState(false)
  useEffect(() => {
    if (!run) return
    if (left <= 0) { setRun(false); onDone(); setLeft(secs); return }
    const t = setTimeout(() => setLeft((x) => x - 1), 1000)
    return () => clearTimeout(t)
  }, [run, left, secs, onDone])
  const pct = ((secs - left) / secs) * 100
  return (
    <div className="flex items-center gap-2.5">
      <button type="button" onClick={() => setRun((v) => !v)} aria-label={run ? "Pozastavit výdrž" : "Spustit výdrž"} data-testid="hold-timer"
        className="relative grid size-11 place-items-center rounded-full bg-accent/15 text-accent">
        <svg viewBox="0 0 36 36" className="absolute inset-0 size-11 -rotate-90" aria-hidden>
          <circle cx="18" cy="18" r="16" fill="none" stroke="currentColor" strokeOpacity=".2" strokeWidth="3" />
          <circle cx="18" cy="18" r="16" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray={`${pct} 100`} pathLength={100} strokeLinecap="round" />
        </svg>
        {run ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
      </button>
      <span className="tabular-nums text-[13px] font-bold text-fg">{left} s</span>
      {!run && left !== secs && <button type="button" onClick={() => setLeft(secs)} aria-label="Vynulovat" className="text-fg-3"><RotateCcw className="size-3.5" aria-hidden /></button>}
    </div>
  )
}

function ExerciseModule({ e, progId, onToggle, onOpen }: { e: any; progId: any; onToggle: (done: boolean) => Promise<void>; onOpen: () => void }) {
  const sets = setsOf(e.dose || "")
  const hold = holdOf(e.dose || "")
  const key = `dl-sets:${progId}:${e.id}:${todayKey()}`
  const [n, setN] = useState(() => (e.doneToday ? sets : Math.min(loadSets(key), sets)))
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (e.doneToday) setN(sets) }, [e.doneToday, sets])
  const tick = async (k: number) => {
    if (busy) return
    const next = k < n ? k : k + 1            // tapping a filled set steps back to it
    setN(next)
    saveSets(key, next)
    if (next >= sets && !e.doneToday) { setBusy(true); try { await onToggle(true) } finally { setBusy(false) } }
    else if (next < sets && e.doneToday) { setBusy(true); try { await onToggle(false) } finally { setBusy(false) } }
  }
  const done = n >= sets
  return (
    <div className={`py-3 transition ${done ? "opacity-90" : ""}`} data-testid="exercise-module">
      <div className="flex items-center gap-3">
        <button type="button" onClick={onOpen} data-testid="self-ex-open" aria-label={`Provedení: ${e.name}`} className="shrink-0"><Thumb id={e.id} /></button>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="min-w-0 flex-1 text-left">
          <b className="flex items-center gap-1.5 text-sm font-bold">{done && <Check className="size-4 text-accent" aria-hidden />}{e.name}</b>
          <span className="block text-[12px] text-fg-3">{e.dose} · tento týden {e.doneWeek}/{e.perWeek}×</span>
        </button>
        <ChevronDown className={`size-4 shrink-0 text-fg-3 transition ${open ? "rotate-180 text-accent" : ""}`} aria-hidden />
      </div>
      {/* the sets of today */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5" role="group" aria-label={`Série: ${e.name}`}>
        {Array.from({ length: sets }, (_, k) => (
          <button key={k} type="button" onClick={() => tick(k)} disabled={busy} data-testid="set-dot"
            aria-label={`${k + 1}. série${k < n ? " hotová" : ""}`}
            className={`grid h-8 min-w-8 place-items-center rounded-full px-2 text-[12px] font-bold transition active:scale-95 ${k < n ? "bg-accent text-ink" : "border border-white/15 text-fg-2 hover:border-accent/60"}`}>
            {k < n ? <Check className="size-3.5" strokeWidth={3} aria-hidden /> : k + 1}
          </button>
        ))}
        <span className="ml-1 text-[11px] text-fg-3">{done ? "hotovo dnes" : `${n}/${sets} sérií`}</span>
      </div>
      {/* this week, one dot per planned session */}
      <div className="mt-2 flex gap-1" aria-hidden>
        {Array.from({ length: Math.max(1, e.perWeek) }, (_, k) => <i key={k} className={`h-1.5 flex-1 rounded-full ${k < e.doneWeek ? "bg-accent" : "bg-white/[.08]"}`} />)}
      </div>
      {open && (
        <div className="mt-3 grid origin-top animate-[careReveal_.28s_ease-out] gap-3 rounded-[14px] bg-white/[.03] p-3 sm:grid-cols-[180px_1fr]">
          {hasFigure(e.id) ? <ExerciseFigure id={e.id} className="mx-auto block w-full max-w-[220px]" /> : null}
          <div className="grid content-start gap-2.5">
            {e.how && <p className="text-[13px] leading-5 text-fg-soft">{e.how}</p>}
            {hold > 0 && <HoldTimer secs={hold} onDone={() => { if (n < sets) tick(n) }} />}
            <button type="button" onClick={onOpen} className="justify-self-start text-[12px] font-bold text-accent">Celý postup a chyby →</button>
          </div>
        </div>
      )}
    </div>
  )
}

// Feedback #170 — once every exercise of the day is done, the session closes into a
// summary: the week at a glance, where the programme stands, and the next session.
const WD_SHORT = ["po", "út", "st", "čt", "pá", "so", "ne"]
// feedback #172 — the last session as a read-only record of what was done: every set
// ticked, the dose and (runner's must-have) how it felt; nothing can be changed here.
function LastSession({ act, lib, onBack }: { act: any; lib: any; onBack: () => void }) {
  const dur = act.durability
  const last = dur?.history?.length ? dur.history[dur.history.length - 1] : null
  const FEEL_LABEL: Record<string, string> = { easy: "lehké", ok: "akorát", hard: "těžké", pain: "něco bolelo" }
  return (
    <div className="mt-3 animate-[careReveal_.28s_ease-out]" data-testid="last-session">
      <button type="button" onClick={onBack} className="text-[12px] font-bold text-accent" data-testid="last-session-back">← Zpět</button>
      <b className="mt-2 block text-[15px] text-fg">Poslední trénink{last ? ` · ${fmtD(last.date)}` : ""}</b>
      {last && <p className="text-[12px] text-fg-3">{`${dur.sessionLabel} · na konci ${FEEL_LABEL[last.feel] || last.feel}`}</p>}
      <div className="mt-2 divide-y divide-white/[.06]">
        {act.exercises.map((e: any) => {
          const sets = setsOf(e.dose || "")
          return (
            <div key={e.id} className="flex items-center gap-3 py-2.5">
              <Thumb id={e.id} />
              <span className="min-w-0 flex-1">
                <b className="block text-[13px] font-bold">{lib.exercises[e.id]?.name || e.name}</b>
                <span className="text-[12px] text-fg-3">{e.dose}</span>
              </span>
              <span className="flex shrink-0 gap-1" aria-label={`${e.doneToday ? sets : 0} z ${sets} sérií`}>
                {Array.from({ length: sets }, (_, k) => (
                  <i key={k} className={`grid size-5 place-items-center rounded-full ${e.doneToday ? "bg-accent text-ink" : "border border-white/15"}`}>{e.doneToday && <Check className="size-3" strokeWidth={3} aria-hidden />}</i>
                ))}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SessionDone({ act, lib, onReopen, onRerate }: { act: any; lib: any; onReopen: () => void; onRerate?: () => void }) {
  const dur = act.durability
  const labels = (lib.programs as Prog[]).find((p) => p.key === act.template)?.sessionLabels || {}
  const [next, setNext] = useState(false)
  const today = new Date().toLocaleDateString("sv-SE")
  const days = (act.weekDays || []) as { date: string; done: number; full: boolean }[]
  const nx = act.next || {}
  const tomorrow = new Date(Date.now() + 864e5).toLocaleDateString("sv-SE")
  return (
    <div className="mt-3 animate-[careReveal_.28s_ease-out]" data-testid="session-done">
      <div className="flex items-center gap-3 rounded-[16px] bg-accent/[.1] p-3.5">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-ink"><Check className="size-5" strokeWidth={3} aria-hidden /></span>
        <div className="min-w-0">
          <b className="block text-[15px] text-fg">Trénink hotový</b>
          <span className="text-[12px] text-fg-2">
            {act.weeks ? `${act.weekNo}. týden z ${act.weeks}${act.weeksLeft != null ? ` · zbývá ${act.weeksLeft} ${plural(act.weeksLeft, "týden", "týdny", "týdnů")}` : ""}` : `${act.weekNo}. týden`}
            {act.sessionsTotal ? ` · celkem ${act.sessionsTotal} ${plural(act.sessionsTotal, "trénink", "tréninky", "tréninků")}` : ""}
          </span>
        </div>
      </div>
      {dur?.note && (
        <p className="mt-3 flex items-start gap-2 rounded-[12px] bg-white/[.04] px-3 py-2 text-[13px] leading-5 text-fg" data-testid="progress-note">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />{dur.note}
        </p>
      )}
      {act.weeks ? (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[.08]" aria-hidden>
          <i className="block h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.round((Math.min(act.weekNo, act.weeks) / act.weeks) * 100))}%` }} />
        </div>
      ) : null}
      <p className="t-label mt-4 !text-fg-3">Tento týden</p>
      <div className="mt-2 grid grid-cols-7 gap-1.5" data-testid="week-days">
        {days.map((d, i) => (
          <div key={d.date} className="text-center">
            <span className={`mx-auto grid size-8 place-items-center rounded-full text-[11px] font-bold ${d.full ? "bg-accent text-ink" : d.done ? "bg-accent/30 text-fg" : "bg-white/[.06] text-fg-3"} ${d.date === today ? "ring-2 ring-fg/60" : ""}`}>
              {d.full ? <Check className="size-3.5" strokeWidth={3} aria-hidden /> : d.done || ""}
            </span>
            <span className={`mt-1 block text-[10.5px] ${d.date === today ? "font-bold text-fg" : "text-fg-3"}`}>{WD_SHORT[i]}</span>
          </div>
        ))}
      </div>
      {!next ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setNext(true)} data-testid="next-session">Pokračovat na další trénink</Button>
          <Button size="sm" variant="outline" onClick={onReopen} data-testid="last-session-open">Poslední trénink</Button>
          {onRerate && <Button size="sm" variant="outline" onClick={onRerate} data-testid="rerate">Změnit hodnocení</Button>}
        </div>
      ) : (
        <div className="mt-4 rounded-[14px] border border-white/[.08] bg-white/[.03] p-3" data-testid="next-session-card">
          <b className="text-sm text-fg">Další trénink{nx.session && labels[nx.session] ? ` ${labels[nx.session]}` : ""} · {nx.date === tomorrow ? "zítra" : fmtD(nx.date)}</b>
          <div className="mt-2 divide-y divide-white/[.06]">
            {(nx.exercises || []).map((id: string) => (
              <div key={id} className="flex items-center gap-3 py-2">
                <Thumb id={id} />
                <span className="min-w-0"><b className="block text-[13px] font-bold">{lib.exercises[id]?.name}</b><span className="text-[12px] text-fg-3">{nx.doses?.[id] || lib.exercises[id]?.dose}</span></span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-fg-3">{dur ? "Která session to bude, se rozhodne v den tréninku podle ostatních aktivit. Dávky se mohou upravit podle vašeho hodnocení." : "Odškrtávat půjde v den tréninku — tělo potřebuje mezi tréninky čas."}</p>
        </div>
      )}
    </div>
  )
}

// Runner's must-have — how the end of the session felt sets the next dose
const FEELS = [
  { k: "easy", label: "Lehké", sub: "3 a víc opakování v záloze" },
  { k: "ok", label: "Akorát", sub: "1–2 opakování v záloze" },
  { k: "hard", label: "Těžké", sub: "na hraně, technika se rozpadala" },
  { k: "pain", label: "Něco bolelo", sub: "bolest při cviku nebo po něm" },
]
function FeelPrompt({ onPick, busy }: { onPick: (k: string) => void; busy: boolean }) {
  return (
    <div className="mt-3 rounded-[16px] border border-accent/30 bg-accent/[.06] p-3.5 animate-[careReveal_.28s_ease-out]" data-testid="feel-prompt">
      <b className="block text-[15px] text-fg">Jak jste se cítili na konci tréninku?</b>
      <p className="mt-0.5 text-[12px] leading-5 text-fg-2">Podle toho se příště přidá, nebo ubere. Trénink se započítá do týdenní zátěže.</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {FEELS.map((f) => (
          <button key={f.k} type="button" disabled={busy} onClick={() => onPick(f.k)} data-testid={`feel-${f.k}`}
            className={`rounded-[12px] border px-3 py-2.5 text-left transition active:scale-[.98] disabled:opacity-50 ${f.k === "pain" ? "border-watch/40 hover:bg-watch/10" : "border-white/12 hover:border-accent/60 hover:bg-accent/10"}`}>
            <b className={`block text-[14px] ${f.k === "pain" ? "text-watch" : "text-fg"}`}>{f.label}</b>
            <span className="block text-[11px] leading-4 text-fg-3">{f.sub}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function PhaseBar({ phases, week, weeks }: { phases: Phase[]; week: number; weeks: number }) {
  return (
    <div className="mt-3" data-testid="phase-bar">
      <div className="flex gap-1">
        {phases.map((ph) => {
          const on = week >= ph.from && week <= ph.to
          const fill = week > ph.to ? 1 : on ? (week - ph.from + 1) / (ph.to - ph.from + 1) : 0
          return (
            <div key={ph.key} className="min-w-0" style={{ flex: ph.to - ph.from + 1 }} title={`${ph.name} · ${ph.from}.–${ph.to}. týden`}>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-accent" style={{ width: `${fill * 100}%` }} /></div>
              <span className={`mt-1 block truncate text-[10px] ${on ? "font-bold text-fg" : "text-fg-3"}`}>{ph.name}</span>
            </div>
          )
        })}
      </div>
      <p className="sr-only">{`${week}. týden z ${weeks}`}</p>
    </div>
  )
}

function DurabilityHead({ d }: { d: any }) {
  return (
    <div className="mt-3" data-testid="durability-head">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip>{d.sessionLabel}</Chip>
        <Chip>{`${d.week}. týden z ${d.weeks}`}</Chip>
        <Chip>{`tento týden ${d.weekDone}/${d.perWeek}`}</Chip>
        {d.deload && <span className="rounded-full bg-info/15 px-2.5 py-1 text-[11px] font-bold text-info" data-testid="deload-chip">Odlehčovací týden</span>}
      </div>
      <PhaseBar phases={d.phases} week={d.week} weeks={d.weeks} />
      <p className="mt-2 text-[13px] leading-5 text-fg-soft"><b className="text-fg">{d.phase.name}</b> · <span>{d.phase.goal}</span> <span>{`Cílová náročnost ${d.phase.rpe} z 10, zhruba ${d.estMin} min.`}</span></p>
      {!d.doneToday && <p className="mt-1 text-[12px] leading-5 text-fg-2" data-testid="session-why">{d.why}</p>}
      {d.scaled && d.capacity && (
        <p className="mt-1 text-[11px] leading-4 text-watch">{`Série jsou upravené podle týdenní kapacity posilování: dva tréninky by daly ≈ ${d.capacity.weekly} sRPE·min, strop je ${d.capacity.ceiling}.`}</p>
      )}
    </div>
  )
}

function Thumb({ id }: { id: string }) {
  return hasFigure(id)
    ? <span className="grid size-11 shrink-0 place-items-center rounded-[10px] bg-white/[.04]"><ExerciseThumb id={id} className="size-10" /></span>
    : <span className="grid size-11 shrink-0 place-items-center rounded-[10px] bg-white/[.06] text-fg-2"><Dumbbell className="size-4" aria-hidden /></span>
}

export function ExerciseSheet({ id, ex, onClose }: { id: string; ex: Ex; onClose: () => void }) {
  return (
    <Sheet open onClose={onClose} layer="z-[90]">
      <div data-testid="exercise-sheet">
        <p className="t-label !text-fg-3">{ex.area}</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">{ex.name}</h2>
        <p className="mt-1 inline-flex items-center gap-1.5 text-[13px] tabular-nums text-fg-2"><Timer className="size-3.5 text-fg-3" aria-hidden />{ex.dose} · {ex.perWeek}× týdně</p>
        {hasFigure(id) && (
          <figure className="nest mt-3 overflow-hidden px-2 pb-1 pt-2" data-testid="exercise-figure">
            <ExerciseFigure id={id} className="mx-auto block max-h-[300px] w-full max-w-[360px]" />
            <figcaption className="px-1 pb-1 text-[11px] text-fg-3">Schematická ilustrace pohybu</figcaption>
          </figure>
        )}
        <p className="t-label mt-4 !text-fg-3">Provedení</p>
        <ol className="mt-2 grid gap-2" data-testid="exercise-steps">
          {(ex.steps?.length ? ex.steps : [ex.how]).map((s, i) => (
            <li key={i} className="flex gap-3 text-[14px] leading-5 text-fg">
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent/15 text-[12px] font-bold tabular-nums text-accent">{i + 1}</span>
              <span className="pt-0.5">{s}</span>
            </li>
          ))}
        </ol>
        {!!ex.mistakes?.length && (
          <>
            <p className="t-label mt-4 !text-fg-3">Na co si dát pozor</p>
            <ul className="mt-2 grid gap-1.5">
              {ex.mistakes.map((m) => <li key={m} className="flex gap-2 text-[13px] leading-5 text-fg-2"><span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-watch" aria-hidden />{m}</li>)}
            </ul>
          </>
        )}
        {ex.caution && <p className="mt-3 rounded-[12px] bg-watch/10 px-3 py-2 text-[12px] leading-5 text-watch">{ex.caution}</p>}
        {!!ex.links?.length && (
          <div className="mt-4 border-t border-white/[.07] pt-3">
            <p className="text-[12px] text-fg-3">K tématu více na Physiopedii (anglicky):</p>
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {ex.links.map((l) => (
                <li key={l.url}><a href={l.url} target="_blank" rel="noopener noreferrer" data-testid="physio-link"
                  className="inline-flex items-center gap-1 text-[13px] font-semibold text-info underline-offset-2 hover:underline">{l.topic}<ExternalLink className="size-3" aria-hidden /></a></li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-3 text-[11px] leading-4 text-fg-3">Text a ilustrace jsou vlastní. Cvik je pro mírné obtíže a nenahrazuje vyšetření.</p>
      </div>
    </Sheet>
  )
}

function ProgramSheet({ prog, lib, onClose, onStart, busy, onOpenEx }: { prog: Prog; lib: any; onClose: () => void; onStart: () => void; busy: boolean; onOpenEx: (id: string) => void }) {
  const [refs, setRefs] = useState(false)
  const perf = prog.group === "performance"
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="program-sheet">
        <p className="t-label !text-fg-3">Program · {prog.weeks} týdnů{prog.perWeek ? ` · ${prog.perWeek}× týdně` : ""}</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">{prog.name}</h2>
        <p className="mt-1 text-[13px] leading-5 text-fg-2">{prog.summary}</p>
        {/* feedback #173 — start above the exercises, not at the very bottom */}
        <Button className="mt-4 w-full" disabled={busy} onClick={onStart} data-testid="program-start">Začít program</Button>
        {prog.phases && (
          <div className="mt-4 grid gap-1.5" data-testid="program-phases">
            {prog.phases.map((ph) => (
              <div key={ph.key} className="grid grid-cols-[78px_1fr] gap-2 text-[12px] leading-5">
                <span className="tabular-nums text-fg-3">{`${ph.from}.–${ph.to}. týden`}</span>
                <span><b className="text-fg">{ph.name}</b> <span className="text-fg-3">{`· náročnost ${ph.rpe}`}</span><br /><span className="text-fg-2">{ph.goal}</span></span>
              </div>
            ))}
          </div>
        )}
        {(prog.sessions ? Object.entries(prog.sessions) : [["", prog.exercises] as [string, string[]]]).map(([sk, ids]) => (
        <div key={sk || "all"}>
        {sk && <p className="t-label mt-4 !text-fg-3">{`${prog.sessionLabels?.[sk] || sk} · začátek`}</p>}
        <ul className={`${sk ? "mt-2" : "mt-4"} grid gap-2`}>
          {ids.map((id) => {
            const e: Ex = lib.exercises[id]
            return (
              <li key={id}>
                <button type="button" onClick={() => onOpenEx(id)} data-testid="program-ex"
                  className="nest flex w-full items-center gap-3 px-3 py-2.5 text-left transition hover:bg-white/[.05]">
                  <Thumb id={id} />
                  <span className="min-w-0 flex-1">
                    <b className="block text-[14px] font-bold text-fg">{e.name}</b>
                    <span className="block tabular-nums text-[12px] text-fg-2">{sk ? prog.sessionDoses?.[sk]?.[id] || e.dose : `${e.dose} · ${e.perWeek}× týdně`}</span>
                    <span className="mt-0.5 block text-[12px] leading-5 text-fg-3">{e.how}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
                </button>
              </li>
            )
          })}
        </ul>
        </div>
        ))}
        {!perf && <p className="mt-3 rounded-[12px] bg-watch/10 px-3 py-2 text-[12px] leading-5 text-watch">{lib.painRule}</p>}
        <div className="mt-3 text-[12px] leading-5 text-fg-2">
          <p className="flex items-start gap-1.5"><BookOpen className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden />{prog.evidence}</p>
          {prog.assumption && <p className="mt-1 text-fg-3">{prog.assumption}</p>}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            <button onClick={() => setRefs((v) => !v)} className="text-[11px] font-bold text-fg-3 underline underline-offset-2 hover:text-fg-2">{refs ? "Skrýt literaturu" : "Literatura"}</button>
            {prog.physio && <a href={prog.physio} target="_blank" rel="noopener noreferrer" data-testid="program-physio"
              className="inline-flex items-center gap-1 text-[11px] font-bold text-info underline-offset-2 hover:underline">Více na Physiopedii<ExternalLink className="size-3" aria-hidden /></a>}
          </div>
          {refs && <ul className="mt-1 space-y-1 text-[11px] leading-4 text-fg-3">{prog.refs.map((r) => <li key={r}>{lib.references[r] || r}</li>)}</ul>}
        </div>
        <p className="mt-2 text-[11px] leading-4 text-fg-3">{perf
          ? "Program doplňuje běžecký trénink. Když cvik bolí, vynechte ho."
          : "Program je pro mírné obtíže a nenahrazuje vyšetření. Bolest, která se zhoršuje, bolí v noci nebo omezuje chůzi, nechte posoudit fyzioterapeutem."}</p>
      </div>
    </Sheet>
  )
}

function BuilderSheet({ lib, onClose, onStart, busy, onOpenEx }: { lib: any; onClose: () => void; onStart: (name: string, ids: string[]) => void; busy: boolean; onOpenEx: (id: string) => void }) {
  const [sel, setSel] = useState<string[]>([])
  const [name, setName] = useState("")
  const ids = Object.keys(lib.exercises) as string[]
  const areas = Array.from(new Set(ids.map((id) => lib.exercises[id].area as string)))
  return (
    <Sheet open onClose={onClose}
      footer={<Button className="w-full" disabled={busy || !sel.length} onClick={() => onStart(name, sel)} data-testid="builder-start">Začít vlastní trénink ({sel.length})</Button>}>
      <div data-testid="builder-sheet">
        <h2 className="font-serif text-[24px] leading-tight text-fg">Vlastní trénink</h2>
        <p className="mt-1 text-[13px] leading-5 text-fg-2">Vyberte cviky, které chcete dělat. Detail s provedením otevřete ikonou vpravo. Dávkování je výchozí a řídí se pravidlem bolesti.</p>
        <label className="mt-3 block text-[12px] font-semibold text-fg-2">Název<input className="mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg" placeholder="Vlastní trénink" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></label>
        {areas.map((area) => (
          <div key={area} className="mt-4">
            <p className="t-label !text-fg-3">{area}</p>
            <ul className="mt-1.5 grid gap-1.5">
              {ids.filter((id) => lib.exercises[id].area === area).map((id) => {
                const e: Ex = lib.exercises[id]
                const on = sel.includes(id)
                return (
                  <li key={id} className={`flex items-stretch overflow-hidden rounded-[14px] border transition ${on ? "border-accent/60 bg-accent/10" : "border-white/10 hover:border-white/20"}`}>
                    <button type="button" onClick={() => setSel(on ? sel.filter((x) => x !== id) : sel.length < 12 ? [...sel, id] : sel)} aria-pressed={on}
                      className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left">
                      <span className={`grid size-5 shrink-0 place-items-center rounded-md border ${on ? "border-accent bg-accent text-ink" : "border-white/25"}`}>{on && <Check className="size-3.5" aria-hidden />}</span>
                      <span className="min-w-0">
                        <b className="block text-[13px] font-bold text-fg">{e.name}</b>
                        <span className="block text-[11px] text-fg-3">{e.dose} · {e.perWeek}× týdně</span>
                      </span>
                    </button>
                    <button type="button" onClick={() => onOpenEx(id)} aria-label={`Provedení: ${e.name}`} data-testid="builder-ex-info"
                      className="flex shrink-0 items-center gap-1 border-l border-white/[.07] px-2 text-fg-3 transition hover:bg-white/[.05] hover:text-fg">
                      {hasFigure(id) ? <ExerciseThumb id={id} className="size-9" /> : <Info className="size-4" aria-hidden />}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>
    </Sheet>
  )
}

// feedback #186 — one running programme (several can run at once, swiped between)
function ActiveProgram({ act, lib, rid, onChange, onEnd, onOpenEx }: { act: any; lib: any; rid: string; onChange: (a: any) => void; onEnd: () => void; onOpenEx: (id: string) => void }) {
  const toast = useToast()
  const [reopen, setReopen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [force, setForce] = useState(false)
  const [rerate, setRerate] = useState(false)
  const setExId = onOpenEx
  const finish = async (feel: string) => {
    setBusy(true)
    try { onChange(await api.finishSelfProgram(rid, act.id, feel)); setRerate(false); setReopen(false); toast({ title: "Trénink zapsán do zátěže" }) }
    catch (e: any) { toast({ title: e?.message || "Hodnocení se nepodařilo uložit" }) } finally { setBusy(false) }
  }
  return (
    <Card className="h-full">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Label>Váš program</Label>
          <h3 className="mt-1 font-serif text-[22px] leading-tight">{act.name}</h3>
          <p className="text-[12px] text-fg-3">od {fmtD(act.startedOn)}{act.weeks ? ` · ${act.weeks} týdnů` : ""}</p>
        </div>
        <Button size="sm" variant="outline" onClick={onEnd}>Ukončit</Button>
      </div>
      {act.durability && <DurabilityHead d={act.durability} />}
      {(act.durability ? act.durability.doneToday && !rerate : act.exercises.length > 0 && act.exercises.every((e: any) => e.doneToday)) ? (
        reopen ? <LastSession act={act} lib={lib} onBack={() => setReopen(false)} />
          : <SessionDone act={act} lib={lib} onReopen={() => setReopen(true)} onRerate={act.durability ? () => setRerate(true) : undefined} />
      ) : act.durability && (rerate || (act.exercises.every((e: any) => e.doneToday) && !act.durability.doneToday)) ? (
        <FeelPrompt busy={busy} onPick={finish} />
      ) : act.durability?.blocked && !act.durability.doneToday && !force ? (
        <div className="mt-3 rounded-[14px] border border-white/[.08] bg-white/[.03] p-3" data-testid="durability-blocked">
          <p className="text-[13px] leading-5 text-fg">{act.durability.blocked}</p>
          <p className="t-label mt-3 !text-fg-3">Další session</p>
          <div className="mt-1 divide-y divide-white/[.06]">
            {act.exercises.map((e: any) => (
              <div key={e.id} className="flex items-center gap-3 py-2"><Thumb id={e.id} /><span className="min-w-0"><b className="block text-[13px] font-bold">{e.name}</b><span className="text-[12px] text-fg-3">{e.dose}</span></span></div>
            ))}
          </div>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setForce(true)} data-testid="durability-force">Přesto odcvičit dnes</Button>
        </div>
      ) : (
      <div className="mt-2 divide-y divide-white/[.07]">
        {act.exercises.map((e: any) => (
          <ExerciseModule key={e.id} e={{ ...lib.exercises[e.id], ...e }} progId={act.id} onOpen={() => setExId(e.id)}
            onToggle={async (done) => {
              try { onChange(await api.logSelfProgram(rid, act.id, e.id, done)) }
              catch (err: any) { toast({ title: err?.message || "Nepodařilo se zapsat" }) }
            }} />
        ))}
      </div>
      )}
      <p className="mt-2 text-[11px] leading-4 text-fg-3">{lib.painRule}</p>
    </Card>
  )
}

export function SelfPrograms() {
  const { me } = useApp()
  const rid = me!.runner_id!
  const toast = useToast()
  const [d, setD] = useState<any | null>(null)
  const [open, setOpen] = useState<Prog | null>(null)
  const [build, setBuild] = useState(false)
  const [exId, setExId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [slide, setSlide] = useState(0)
  const rail = useRef<HTMLDivElement>(null)
  const onRail = () => { const el = rail.current; if (el) setSlide(Math.round(el.scrollLeft / Math.max(1, el.clientWidth))) }
  const goSlide = (i: number) => { const el = rail.current; if (el) el.scrollTo({ left: i * el.clientWidth, behavior: "smooth" }) }
  const load = () => api.selfPrograms(rid).then(setD).catch(() => setD(false))
  useEffect(() => { load() }, [rid]) // eslint-disable-line react-hooks/exhaustive-deps
  // railway#196 — Trénink links here (?prog=durability): the running programme comes
  // into view, one not started yet opens its sheet
  const [params, setParams] = useSearchParams()
  const want = params.get("prog")
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!want || !d) return
    const acts: any[] = d.actives || (d.active ? [d.active] : [])
    const i = acts.findIndex((x: any) => x.template === want)
    if (i >= 0) {
      requestAnimationFrame(() => { goSlide(i); box.current?.scrollIntoView({ behavior: "smooth", block: "start" }) })
    } else {
      const p = (d.library?.programs || []).find((x: Prog) => x.key === want)
      if (p) setOpen(p)
    }
    const next = new URLSearchParams(params)
    next.delete("prog")
    setParams(next, { replace: true })
  }, [want, d]) // eslint-disable-line react-hooks/exhaustive-deps
  if (d === null) return <p className="mt-4 text-sm text-fg-3">Načítám programy…</p>
  if (d === false) return null
  const lib = d.library
  const progs: Prog[] = lib.programs
  const rec = (d.recommended || []) as string[]
  const regions = (d.regions || []) as string[]
  const actives: any[] = d.actives || (d.active ? [d.active] : [])
  const start = async (body: any) => {
    setBusy(true)
    try { await api.startSelfProgram(rid, body); setOpen(null); setBuild(false); toast({ title: "Program spuštěn" }); await load() }
    catch (e: any) { toast({ title: e?.message || "Program se nepodařilo spustit" }) } finally { setBusy(false) }
  }
  const row = (p: Prog, recommended: boolean) => (
    <button key={p.key} type="button" onClick={() => setOpen(p)} data-testid="program-row"
      className="flex w-full items-center gap-3 py-3 text-left">
      <span className={`grid size-[34px] shrink-0 place-items-center rounded-[10px] ${recommended ? "bg-accent/15 text-accent" : "bg-white/[.06] text-fg-2"}`}><Dumbbell className="size-4" aria-hidden /></span>
      <span className="min-w-0 flex-1">
        <b className="text-sm font-bold text-fg">{p.name}</b>
        <span className="block truncate text-[12px] text-fg-3">{p.weeks} týdnů · {p.exercises.length} {plural(p.exercises.length, "cvik", "cviky", "cviků")} · {p.summary}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
    </button>
  )
  const painProgs = progs.filter((p) => (p.group || "pain") === "pain" && !rec.includes(p.key))
  const perfProgs = progs.filter((p) => p.group === "performance")
  return (
    <div className="mt-4 grid gap-4" data-testid="self-programs">
      {actives.length > 0 && (
        <div ref={box} className="scroll-mt-24" data-testid="active-programs">
          {actives.length > 1 && (
            <div className="mb-2 flex items-center justify-between gap-2 px-1">
              <span className="t-label !text-fg-3">{`Běžící programy · ${slide + 1} / ${actives.length}`}</span>
              <span className="flex gap-1.5">
                {actives.map((a: any, i: number) => (
                  <button key={a.id} type="button" aria-label={a.name} onClick={() => goSlide(i)}
                    className={`h-2 rounded-full transition-all ${i === slide ? "w-5 bg-accent" : "w-2 bg-white/25"}`} />
                ))}
              </span>
            </div>
          )}
          <div ref={rail} onScroll={onRail} className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
            {actives.map((a: any) => (
              <div key={a.id} className="w-full shrink-0 snap-center">
                <ActiveProgram act={a} lib={lib} rid={rid} onOpenEx={setExId}
                  onChange={(n) => setD({ ...d, actives: actives.map((x: any) => (x.id === n.id ? n : x)), active: d.active?.id === n.id ? n : d.active })}
                  onEnd={async () => { await api.endSelfProgram(rid, a.id); load() }} />
              </div>
            ))}
          </div>
        </div>
      )}
      <Card>
        <div className="flex min-w-0 items-center justify-between gap-2">
          <Label><span className="inline-flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" aria-hidden />Doporučeno podle bolesti</span></Label>
          {regions.length > 0 && (
            <span className="flex min-w-0 max-w-[48%] justify-end" title={regions.join(", ")} data-testid="pain-region-chip">
              <Chip className="max-w-full"><span className="block min-w-0 truncate">{shortRegion(regions[0])}{regions.length > 1 ? ` +${regions.length - 1}` : ""}</span></Chip>
            </span>
          )}
        </div>
        {rec.length ? (
          <div className="mt-1 divide-y divide-white/[.07]">{rec.map((k) => progs.find((p) => p.key === k)).filter(Boolean).map((p) => row(p as Prog, true))}</div>
        ) : (
          <p className="mt-2 text-sm text-fg-2">Za poslední 4 týdny jste neoznačili bolest, ke které máme program. Níže jsou všechny programy.</p>
        )}
      </Card>
      <Card>
        <div className="flex items-center justify-between gap-2">
          <Label>Při potížích</Label>
          <Button size="sm" variant="outline" icon={Plus} onClick={() => setBuild(true)} data-testid="builder-open">Vlastní trénink</Button>
        </div>
        <div className="mt-1 divide-y divide-white/[.07]">{painProgs.map((p) => row(p, false))}</div>
        <p className="mt-2 text-[11px] leading-4 text-fg-3">Programy vycházejí z publikovaných postupů, u každého je zdroj. Na odbornou revizi fyzioterapeutem Došlapu zatím čekají a nenahrazují vyšetření.</p>
      </Card>
      {perfProgs.length > 0 && (
        <div data-testid="perf-programs"><Card>
          <Label>Síla a technika</Label>
          <div className="mt-1 divide-y divide-white/[.07]">{perfProgs.map((p) => row(p, false))}</div>
          <p className="mt-2 text-[11px] leading-4 text-fg-3">Doplněk k běhání. U každého programu je uvedeno, co je doložené a co vychází z trenérské praxe.</p>
        </Card></div>
      )}
      {open && <ProgramSheet prog={open} lib={lib} busy={busy} onClose={() => setOpen(null)} onStart={() => start({ template: open.key })} onOpenEx={setExId} />}
      {build && <BuilderSheet lib={lib} busy={busy} onClose={() => setBuild(false)} onStart={(name, ids) => start({ name, exercises: ids })} onOpenEx={setExId} />}
      {exId && lib.exercises[exId] && <ExerciseSheet id={exId} ex={lib.exercises[exId]} onClose={() => setExId(null)} />}
    </div>
  )
}
