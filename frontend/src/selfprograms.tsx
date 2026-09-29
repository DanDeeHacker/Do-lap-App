// Feedback railway#116 — exercise programs a runner starts on their own: ready-made ones
// for common running problems (recommended by the pain they marked in the last 4 weeks)
// and an own session picked from the exercise library. Content and sources live in
// backend/app/programs_library.py.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Button, Card, Chip, Label, Sheet, useToast } from "@/ui"
import { BookOpen, Check, ChevronRight, Dumbbell, Plus, Sparkles } from "lucide-react"
import { fmtD, plural } from "@/lib"

type Ex = { name: string; area: string; how: string; dose: string; perWeek: number }
type Prog = { key: string; name: string; weeks: number; summary: string; exercises: string[]; evidence: string; refs: string[]; assumption: string | null }

function ProgramSheet({ prog, lib, onClose, onStart, busy }: { prog: Prog; lib: any; onClose: () => void; onStart: () => void; busy: boolean }) {
  const [refs, setRefs] = useState(false)
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
              <li key={id} className="nest px-3 py-2.5">
                <div className="flex items-baseline justify-between gap-2">
                  <b className="text-[14px] font-bold text-fg">{e.name}</b>
                  <span className="shrink-0 tabular-nums text-[12px] text-fg-2">{e.dose} · {e.perWeek}× týdně</span>
                </div>
                <p className="mt-1 text-[12px] leading-5 text-fg-3">{e.how}</p>
              </li>
            )
          })}
        </ul>
        <p className="mt-3 rounded-[12px] bg-watch/10 px-3 py-2 text-[12px] leading-5 text-watch">{lib.painRule}</p>
        <div className="mt-3 text-[12px] leading-5 text-fg-2">
          <p className="flex items-start gap-1.5"><BookOpen className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden />{prog.evidence}</p>
          {prog.assumption && <p className="mt-1 text-fg-3">{prog.assumption}</p>}
          <button onClick={() => setRefs((v) => !v)} className="mt-1.5 text-[11px] font-bold text-fg-3 underline underline-offset-2 hover:text-fg-2">{refs ? "Skrýt literaturu" : "Literatura"}</button>
          {refs && <ul className="mt-1 space-y-1 text-[11px] leading-4 text-fg-3">{prog.refs.map((r) => <li key={r}>{lib.references[r] || r}</li>)}</ul>}
        </div>
        <Button className="mt-4 w-full" disabled={busy} onClick={onStart} data-testid="program-start">Začít program</Button>
        <p className="mt-2 text-[11px] leading-4 text-fg-3">Program je pro mírné obtíže a nenahrazuje vyšetření. Bolest, která se zhoršuje, bolí v noci nebo omezuje chůzi, nechte posoudit fyzioterapeutem.</p>
      </div>
    </Sheet>
  )
}

function BuilderSheet({ lib, onClose, onStart, busy }: { lib: any; onClose: () => void; onStart: (name: string, ids: string[]) => void; busy: boolean }) {
  const [sel, setSel] = useState<string[]>([])
  const [name, setName] = useState("")
  const ids = Object.keys(lib.exercises) as string[]
  const areas = Array.from(new Set(ids.map((id) => lib.exercises[id].area as string)))
  return (
    <Sheet open onClose={onClose}
      footer={<Button className="w-full" disabled={busy || !sel.length} onClick={() => onStart(name, sel)} data-testid="builder-start">Začít vlastní trénink ({sel.length})</Button>}>
      <div data-testid="builder-sheet">
        <h2 className="font-serif text-[24px] leading-tight text-fg">Vlastní trénink</h2>
        <p className="mt-1 text-[13px] leading-5 text-fg-2">Vyberte cviky, které chcete dělat. Dávkování je výchozí a řídí se pravidlem bolesti.</p>
        <label className="mt-3 block text-[12px] font-semibold text-fg-2">Název<input className="mt-1 w-full rounded-xl border px-3 py-2.5 text-sm text-fg" placeholder="Vlastní trénink" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></label>
        {areas.map((area) => (
          <div key={area} className="mt-4">
            <p className="t-label !text-fg-3">{area}</p>
            <ul className="mt-1.5 grid gap-1.5">
              {ids.filter((id) => lib.exercises[id].area === area).map((id) => {
                const e: Ex = lib.exercises[id]
                const on = sel.includes(id)
                return (
                  <li key={id}>
                    <button type="button" onClick={() => setSel(on ? sel.filter((x) => x !== id) : sel.length < 12 ? [...sel, id] : sel)} aria-pressed={on}
                      className={`flex w-full items-start gap-3 rounded-[14px] border px-3 py-2.5 text-left transition ${on ? "border-accent/60 bg-accent/10" : "border-white/10 hover:border-white/20"}`}>
                      <span className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border ${on ? "border-accent bg-accent text-ink" : "border-white/25"}`}>{on && <Check className="size-3.5" aria-hidden />}</span>
                      <span className="min-w-0">
                        <b className="block text-[13px] font-bold text-fg">{e.name}</b>
                        <span className="block text-[11px] text-fg-3">{e.dose} · {e.perWeek}× týdně</span>
                      </span>
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
  const [busy, setBusy] = useState(false)
  const load = () => api.selfPrograms(rid).then(setD).catch(() => setD(false))
  useEffect(() => { load() }, [rid]) // eslint-disable-line react-hooks/exhaustive-deps
  if (d === null) return <p className="mt-4 text-sm text-fg-3">Načítám programy…</p>
  if (d === false) return null
  const lib = d.library
  const progs: Prog[] = lib.programs
  const rec = (d.recommended || []) as string[]
  const act = d.active
  const start = async (body: any) => {
    setBusy(true)
    try { await api.startSelfProgram(rid, body); setOpen(null); setBuild(false); toast({ title: "Program spuštěn" }); await load() }
    catch (e: any) { toast({ title: e?.message || "Program se nepodařilo spustit" }) } finally { setBusy(false) }
  }
  const toggle = async (ex: any) => {
    try { setD({ ...d, active: await api.logSelfProgram(rid, act.id, ex.id, !ex.doneToday) }) } catch (e: any) { toast({ title: e?.message || "Nepodařilo se zapsat" }) }
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
              <div key={e.id} className="flex items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <b className="text-sm font-bold">{e.name}</b>
                  <span className="block text-[12px] text-fg-3">{e.dose} · tento týden {e.doneWeek}/{e.perWeek}×</span>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.round((e.doneWeek / Math.max(1, e.perWeek)) * 100))}%` }} /></div>
                </div>
                <Button size="sm" variant={e.doneToday ? "secondary" : "outline"} onClick={() => toggle(e)} data-testid="self-ex-done">{e.doneToday ? "✓ dnes" : "Hotovo"}</Button>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-4 text-fg-3">{lib.painRule}</p>
        </Card>
      )}
      <Card>
        <div className="flex items-center justify-between gap-2">
          <Label><span className="inline-flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" aria-hidden />Doporučeno podle bolesti</span></Label>
          {d.regions?.length > 0 && <Chip>{d.regions.slice(0, 2).join(", ")}{d.regions.length > 2 ? "…" : ""}</Chip>}
        </div>
        {rec.length ? (
          <div className="mt-1 divide-y divide-white/[.07]">{rec.map((k) => progs.find((p) => p.key === k)).filter(Boolean).map((p) => row(p as Prog, true))}</div>
        ) : (
          <p className="mt-2 text-sm text-fg-2">Za poslední 4 týdny jste neoznačili bolest, ke které máme program. Níže jsou všechny programy.</p>
        )}
      </Card>
      <Card>
        <div className="flex items-center justify-between gap-2">
          <Label>Všechny programy</Label>
          <Button size="sm" variant="outline" icon={Plus} onClick={() => setBuild(true)} data-testid="builder-open">Vlastní trénink</Button>
        </div>
        <div className="mt-1 divide-y divide-white/[.07]">{progs.filter((p) => !rec.includes(p.key)).map((p) => row(p, false))}</div>
        <p className="mt-2 text-[11px] leading-4 text-fg-3">Programy vycházejí z publikovaných postupů, u každého je zdroj. Na odbornou revizi fyzioterapeutem Došlapu zatím čekají a nenahrazují vyšetření.</p>
      </Card>
      {open && <ProgramSheet prog={open} lib={lib} busy={busy} onClose={() => setOpen(null)} onStart={() => start({ template: open.key })} />}
      {build && <BuilderSheet lib={lib} busy={busy} onClose={() => setBuild(false)} onStart={(name, ids) => start({ name, exercises: ids })} />}
    </div>
  )
}
