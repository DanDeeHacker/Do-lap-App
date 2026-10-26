// Plán týdne → Změnit (owner request 2026-10-26): the runner changes a day's session. Every type
// carries the app's verdict for that day (backend week_plan.options: the same rules and ceilings
// as the plan itself) — ✓ fits, ↻ fits smaller or moves another day, ✕ can't, with the reason and
// alternatives. A change the rules don't allow can't be forced. Saving re-lays the rest of the week.
import { useEffect, useRef, useState } from "react"
import { api, type DayPin } from "@/api"
import { useApp } from "@/store"
import { Button, Chip, Sheet, useToast } from "@/ui"
import { C } from "@/tokens"
import { Ban, Check, RefreshCw, RotateCcw } from "lucide-react"

const TYPE_COL: Record<string, string> = {
  "lehký": C.info, "dlouhý": C.load, "kvalitní": C.alert, regenerace: C.ok, kolo: C.watch, voda: C.watch,
  "posilování": C.self, volno: C.fg4,
}
const STATUS: Record<string, [string, "ok" | "watch" | "alert"]> = { ok: ["jde", "ok"], mod: ["s úpravou", "watch"], no: ["nejde", "alert"] }
const WD_IN: Record<string, string> = { po: "v pondělí", "út": "v úterý", st: "ve středu", "čt": "ve čtvrtek", "pá": "v pátek", so: "v sobotu", ne: "v neděli" }
const WD_NUM: Record<string, number> = { po: 0, "út": 1, st: 2, "čt": 3, "pá": 4, so: 5, ne: 6 }
const WD_GEN: Record<string, string> = { po: "pondělí", "út": "úterý", st: "středy", "čt": "čtvrtku", "pá": "pátku", so: "soboty", ne: "neděle" }
const num = (v: number) => (Math.round(v * 10) / 10).toLocaleString("cs-CZ")
const dm = (iso: string) => { const [, m, d] = iso.split("-"); return `${+d}. ${+m}.` }

type Pick = { type: string; moveTo?: string } | null

export function DayEditSheet({ rid, day, onClose, onPlan }: { rid: string; day: any; onClose: () => void; onPlan: (p: any) => void }) {
  const { boot, refresh } = useApp()
  const toast = useToast()
  const [opts, setOpts] = useState<any>(undefined)
  const [pick, setPick] = useState<Pick>(null)
  const [size, setSize] = useState<number | null>(null)
  const [pv, setPv] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  useEffect(() => {
    let alive = true
    api.weekPlanOptions(rid, day.date).then((o: any) => alive && setOpts(o)).catch(() => alive && setOpts(null))
    return () => { alive = false }
  }, [rid, day.date])
  const types: any[] = opts?.types || []
  const sel = pick && !pick.moveTo ? types.find((t) => t.type === pick.type) : null
  const move = pick?.moveTo ? (opts?.moves || []).find((m: any) => m.date === pick.moveTo) : null
  const body = (): DayPin | null => {
    if (!pick) return null
    const r = sel?.range
    return {
      date: day.date, type: pick.type, move_to: pick.moveTo || null,
      km: r && r.unit === "km" && size != null ? size : null, min: r && r.unit === "min" && size != null ? size : null,
    }
  }
  // the preview follows the slider (debounced), the type's own verdict shows meanwhile
  useEffect(() => {
    const b = body()
    if (!b) { setPv(null); return }
    const k = ++seq.current
    const t = setTimeout(() => {
      api.weekPlanPreview(rid, b).then((p: any) => { if (k === seq.current) setPv(p) }).catch(() => {})
    }, size != null ? 250 : 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pick?.type, pick?.moveTo, size])
  const choose = (p: Pick) => {
    setPv(null)
    setPick(p)
    const t = p && !p.moveTo ? types.find((x) => x.type === p.type) : null
    setSize(t?.range ? t.range.value : null)
  }
  const save = async () => {
    const b = body()
    if (!b) return
    setBusy(true)
    try {
      const r: any = await api.weekPlanPin(rid, b)
      onPlan(r.plan)
      toast({ title: "Plán týdne je přepočítaný" })
      refresh()
      onClose()
    } catch (e: any) {
      toast({ title: e?.message || "Změnu se nepodařilo uložit" })
    } finally { setBusy(false) }
  }
  const undo = async () => {
    setBusy(true)
    try {
      const r: any = await api.weekPlanUnpin(rid, day.date)
      onPlan(r.plan)
      toast({ title: "Den je zpět podle návrhu aplikace" })
      refresh()
      onClose()
    } finally { setBusy(false) }
  }
  // "v úterý nemůžu nikdy" → the runner's usual days without this weekday (Cíl → Můj týden)
  const never = async () => {
    setBusy(true)
    try {
      const g = boot?.assessment?.guidance
      const cur: any = (await api.goalPrefs(rid))?.prefs || {}
      const wd = WD_NUM[day.wd]
      const base: number[] = cur.days?.length ? cur.days : g?.pattern?.runDays || []
      const days = base.filter((d: number) => d !== wd)
      if (days.length < 2) { toast({ title: "Běhací dny musí být aspoň dva — upravte je v Cíl → Můj týden" }); return }
      await api.setGoalPrefs(rid, {
        days, long_day: cur.longDay === wd ? null : cur.longDay ?? null, day_min: cur.dayMin ?? null,
        long_min: cur.longMin ?? null, vacations: cur.vacations || [],
      })
      toast({ title: `Běhací dny bez ${WD_GEN[day.wd]} — plán se přepočítal` })
      refresh()
      const w: any = await api.weekPlan(rid)
      onPlan(w?.plan ?? null)
      onClose()
    } catch (e: any) {
      toast({ title: e?.message || "Běhací dny se nepodařilo uložit" })
    } finally { setBusy(false) }
  }
  const status = pv?.status ?? (move ? move.status : sel?.status)
  const why = pv?.why ?? (move ? move.why : sel?.why)
  const chg: any[] = pv?.changes ?? (move ? move.changes : sel?.changes) ?? []
  return (
    <Sheet open onClose={onClose} footer={pick ? (
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => choose(null)} className="px-5">Zpět</Button>
        <Button className="flex-1" busy={busy} disabled={status === "no" || busy} onClick={save} data-testid="day-edit-save">
          {status === "no" ? "Tohle plán nedovolí" : "Potvrdit a přepočítat týden"}
        </Button>
      </div>
    ) : undefined}>
      <div data-testid="day-edit">
        <p className="t-label">Změnit trénink</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">{`${day.wdLong.replace(/^./, (c: string) => c.toUpperCase())} ${dm(day.date)}`}</h2>
        {opts?.current && <p className="mt-1 text-[13px] text-fg-2">{`Teď v plánu: ${opts.current}`}</p>}
        {opts === undefined && <p className="mt-4 animate-pulse text-[13px] text-fg-3">Počítám, co se na tento den vejde…</p>}
        {opts === null && <p className="mt-4 text-[13px] text-fg-3">Možnosti se nepodařilo načíst.</p>}
        {opts && !opts.editable && <p className="nest mt-4 px-3.5 py-3 text-[13px] text-fg-soft">{opts.why}</p>}
        {opts?.editable && !pick && (
          <>
            {opts.pinned && (
              <button type="button" onClick={undo} disabled={busy} className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] font-bold text-accent hover:underline" data-testid="day-edit-undo">
                <RotateCcw className="size-3.5" aria-hidden />Vrátit návrh aplikace
              </button>
            )}
            <ul className="mt-4 divide-y divide-white/[.06]" data-testid="day-edit-types">
              {types.map((t) => {
                const [lbl, tone] = STATUS[t.status]
                const cur = t.type === opts.currentType
                return (
                  <li key={t.type} className="py-2.5" data-testid={`day-type-${t.type}`}>
                    <button type="button" disabled={t.status === "no"} onClick={() => choose({ type: t.type })}
                      className="flex w-full items-start gap-3 text-left disabled:cursor-default">
                      <i className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{ background: TYPE_COL[t.type], opacity: t.status === "no" ? 0.4 : 1 }} />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <b className={`text-[14px] ${t.status === "no" ? "text-fg-3" : "text-fg"}`}>{t.label}</b>
                          {cur && <Chip>teď</Chip>}
                          <Chip tone={tone}>{t.status === "ok" ? <Check className="size-3" aria-hidden /> : t.status === "mod" ? <RefreshCw className="size-3" aria-hidden /> : <Ban className="size-3" aria-hidden />}{lbl}</Chip>
                        </span>
                        {t.text && t.status !== "no" && <span className="mt-0.5 block text-[12.5px] tabular-nums text-fg-2">{t.text}</span>}
                        {t.why && <span className={`mt-0.5 block text-[12px] leading-[17px] ${t.status === "no" ? "text-fg-3" : "text-watch"}`}>{t.why}</span>}
                      </span>
                    </button>
                    {t.status === "no" && t.alts?.length > 0 && (
                      <span className="ml-5 mt-1.5 flex flex-wrap gap-1.5">
                        {t.alts.map((x: any, k: number) => (
                          <button key={k} type="button" data-testid="day-alt"
                            onClick={() => (x.kind === "type" ? choose({ type: x.type }) : choose({ type: x.type, moveTo: x.date }))}
                            className="rounded-full border border-accent/35 px-2.5 py-1 text-[11.5px] font-bold text-accent hover:bg-accent/10">
                            {x.kind === "type" ? <>{"Místo toho: "}{x.label}</> : <>{`${x.label} `}{WD_IN[x.wd] || x.wd}</>}
                          </button>
                        ))}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
            {opts.moves?.length > 0 && (
              <div className="mt-4">
                <p className="t-label">{`Přesunout „${opts.current}" na jiný den`}</p>
                <div className="mt-2 flex flex-wrap gap-1.5" data-testid="day-moves">
                  {opts.moves.map((m: any) => (
                    <button key={m.date} type="button" disabled={m.status === "no"} title={m.why || undefined}
                      onClick={() => choose({ type: opts.currentType, moveTo: m.date })}
                      className={`rounded-full px-3 py-1.5 text-[12px] font-bold ${m.status === "no" ? "bg-white/[.04] text-fg-4 line-through" : "border border-white/12 text-fg hover:border-accent/50"}`}>
                      {`${m.wd} ${dm(m.date)}`}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!opts.today && (
              <button type="button" onClick={never} disabled={busy} className="mt-5 text-[12.5px] font-bold text-fg-2 underline-offset-2 hover:text-fg hover:underline" data-testid="day-never">
                {`Nikdy nemůžu běhat ${WD_IN[day.wd] || day.wd} → upravit běhací dny`}
              </button>
            )}
          </>
        )}
        {opts?.editable && pick && (
          <div className="mt-4" data-testid="day-edit-preview">
            <p className="text-[15px] font-bold text-fg">
              {move ? <>{opts.current}{": "}{dm(day.date)}{" → "}{move.wdLong}{" "}{dm(move.date)}</> : sel?.label}
            </p>
            {sel?.range && size != null && (
              <div className="mt-3">
                <div className="flex items-baseline justify-between text-[12.5px]">
                  <span className="text-fg-2">{sel.range.unit === "km" ? "Vzdálenost" : "Délka"}</span>
                  <b className="tabular-nums text-fg">{`${num(size)} ${sel.range.unit}`}</b>
                </div>
                <input type="range" className="range mt-2 w-full" min={sel.range.lo} max={sel.range.hi} step={sel.range.step}
                  value={size} onChange={(e) => setSize(+e.target.value)} aria-label="Velikost tréninku" data-testid="day-size" />
                <div className="mt-1 flex justify-between text-[11px] tabular-nums text-fg-3">
                  <span>{`${num(sel.range.lo)} ${sel.range.unit}`}</span><span>{`nejvýš ${num(sel.range.hi)} ${sel.range.unit} pod stropy`}</span>
                </div>
              </div>
            )}
            {pv?.text && <p className="mt-3 text-[13px] text-fg-soft">{`Nový plán dne: ${pv.text}`}</p>}
            {why && <p className={`mt-2 text-[12.5px] leading-[18px] ${status === "no" ? "text-alert-soft" : "text-watch"}`}>{why}</p>}
            <div className="nest mt-3 px-3.5 py-3">
              <p className="t-label">Co se tím změní ve zbytku týdne</p>
              {chg.length ? (
                <ul className="mt-2 space-y-1 text-[12.5px] leading-[18px] text-fg-soft" data-testid="day-changes">
                  {chg.map((c: any) => <li key={c.date} className="flex gap-2"><span className="text-accent">›</span><span>{c.text}</span></li>)}
                </ul>
              ) : <p className="mt-1.5 text-[12.5px] text-fg-3">Nic dalšího — ostatní dny zůstanou, jak jsou.</p>}
            </div>
          </div>
        )}
      </div>
    </Sheet>
  )
}
