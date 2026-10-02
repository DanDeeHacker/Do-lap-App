// Feedback railway#116 — exercise programs a runner starts on their own: ready-made ones
// for common running problems (recommended by the pain they marked in the last 4 weeks),
// core and running-drill programs, and an own session picked from the exercise library.
// Content and sources live in backend/app/programs_library.py. Every exercise opens a
// detail with an own illustration, numbered steps and the common faults; Physiopedia is
// only linked for further reading (its licence is non-commercial).
import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, Chip, Label, Sheet, useToast } from "@/ui"
import { BookOpen, Check, ChevronDown, ChevronRight, Dumbbell, ExternalLink, Info, Pause, Play, Plus, RotateCcw, Sparkles, Timer } from "lucide-react"
import { fmtD, plural } from "@/lib"
import { ExerciseFigure, ExerciseThumb, hasFigure } from "@/exfigure"

type Ex = { name: string; area: string; how: string; dose: string; perWeek: number; steps?: string[]; mistakes?: string[]; caution?: string; links?: { url: string; topic: string }[] }
type Prog = { key: string; group?: string; physio?: string; name: string; weeks: number; summary: string; exercises: string[]; evidence: string; refs: string[]; assumption: string | null }

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
        <p className="t-label !text-fg-3">Program · {prog.weeks} týdnů</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">{prog.name}</h2>
        <p className="mt-1 text-[13px] leading-5 text-fg-2">{prog.summary}</p>
        <ul className="mt-4 grid gap-2">
          {prog.exercises.map((id) => {
            const e: Ex = lib.exercises[id]
            return (
              <li key={id}>
                <button type="button" onClick={() => onOpenEx(id)} data-testid="program-ex"
                  className="nest flex w-full items-center gap-3 px-3 py-2.5 text-left transition hover:bg-white/[.05]">
                  <Thumb id={id} />
                  <span className="min-w-0 flex-1">
                    <b className="block text-[14px] font-bold text-fg">{e.name}</b>
                    <span className="block tabular-nums text-[12px] text-fg-2">{e.dose} · {e.perWeek}× týdně</span>
                    <span className="mt-0.5 block text-[12px] leading-5 text-fg-3">{e.how}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-fg-3" aria-hidden />
                </button>
              </li>
            )
          })}
        </ul>
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
        <Button className="mt-4 w-full" disabled={busy} onClick={onStart} data-testid="program-start">Začít program</Button>
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

export function SelfPrograms() {
  const { me } = useApp()
  const rid = me!.runner_id!
  const toast = useToast()
  const [d, setD] = useState<any | null>(null)
  const [open, setOpen] = useState<Prog | null>(null)
  const [build, setBuild] = useState(false)
  const [exId, setExId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.selfPrograms(rid).then(setD).catch(() => setD(false))
  useEffect(() => { load() }, [rid]) // eslint-disable-line react-hooks/exhaustive-deps
  if (d === null) return <p className="mt-4 text-sm text-fg-3">Načítám programy…</p>
  if (d === false) return null
  const lib = d.library
  const progs: Prog[] = lib.programs
  const rec = (d.recommended || []) as string[]
  const regions = (d.regions || []) as string[]
  const act = d.active
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
      {act && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <Label>Váš program</Label>
              <h3 className="mt-1 font-serif text-[22px] leading-tight">{act.name}</h3>
              <p className="text-[12px] text-fg-3">od {fmtD(act.startedOn)}{act.weeks ? ` · ${act.weeks} týdnů` : ""}</p>
            </div>
            <Button size="sm" variant="outline" onClick={async () => { await api.endSelfProgram(rid, act.id); load() }}>Ukončit</Button>
          </div>
          <div className="mt-2 divide-y divide-white/[.07]">
            {act.exercises.map((e: any) => (
              <ExerciseModule key={e.id} e={{ ...lib.exercises[e.id], ...e }} progId={act.id} onOpen={() => setExId(e.id)}
                onToggle={async (done) => {
                  try { setD({ ...d, active: await api.logSelfProgram(rid, act.id, e.id, done) }) }
                  catch (err: any) { toast({ title: err?.message || "Nepodařilo se zapsat" }) }
                }} />
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-4 text-fg-3">{lib.painRule}</p>
        </Card>
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
