// Plán od trenéra — the coach's overview (/trener/<token>, no account): the runner's
// state (readiness, sleep, HRV, resting HR, pain), the days and activities, the plan with
// Došlap's verdicts, and the plan itself, editable 6 months ahead. A day the coach saves
// replaces whatever was planned there before. Only with the runner's explicit consent;
// every open is logged and shown to the runner; the runner can revoke the link any time.
import { useEffect, useMemo, useState } from "react"
import { useParams } from "react-router"
import { CalendarDays, Copy, HeartPulse, Moon, Plus, Activity as ActIcon, ShieldCheck, Trash2, Pencil } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Label, Segmented, Sheet, Sparkline, useToast } from "@/ui"
import { C, goodCol } from "@/tokens"
import { fmtD } from "@/lib"
import { num } from "@/outlook"
import { AdherenceCard, FitChips, KIND, SessionForm, TrendCard, VERDICT, VerdictBadge, addDays } from "@/coach"

const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
const FIELDS = ["kind", "title", "km", "duration_min", "z4_min", "intervals", "target", "ascent_m", "descent_m", "notes"]

export function CoachPage() {
  const { token = "" } = useParams()
  const [d, setD] = useState<any | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<"overview" | "plan" | "health" | "acts">("overview")
  const load = () => api.coachView(token).then((x) => { setD(x); setErr(null) }).catch((e) => setErr(e?.message || "Přehled se nepodařilo načíst"))
  useEffect(() => { load() }, [token])
  if (err) return (
    <Shell><Card className="mt-8"><Label>Přehled pro trenéra</Label><p className="mt-2 text-sm text-fg-2">{err}</p></Card></Shell>
  )
  if (!d) return <Shell><p className="mt-10 text-sm text-fg-3">Načítám…</p></Shell>
  const t = d.today || {}
  return (
    <Shell>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>{d.coachName ? `Přehled pro trenéra · ${d.coachName}` : "Přehled pro trenéra"}</Label>
          <h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">{d.runner.name}</h1>
          <p className="mt-1 text-[12px] text-fg-3">{`${new Date(d.date + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })} · odkaz platí do ${fmtD(d.expiresAt)}`}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {t.readiness != null && <span className="rounded-full px-3 py-1.5 text-[12px] font-bold" style={{ background: `${goodCol(t.readiness)}1f`, color: goodCol(t.readiness) }}>{`připravenost ${t.readiness} %`}</span>}
          {t.pain ? <Chip tone={t.pain > 5 ? "alert" : "watch"}>{`bolest ${t.pain}/10`}</Chip> : <Chip tone="ok">bez bolesti</Chip>}
        </div>
      </div>
      {t.override && <p className="mt-3 rounded-[14px] border border-alert/40 bg-alert/10 px-3 py-2.5 text-[13px] text-alert-soft">{t.override}</p>}
      {!d.runner.coachMode && <p className="mt-3 text-[12px] text-fg-3">Běžec má teď režim trenéra vypnutý — plán vidí, ale aplikace ho nevyhodnocuje.</p>}
      <Segmented className="mt-5" ariaLabel="Části přehledu" value={tab} onChange={setTab}
        options={[["overview", "Přehled"], ["plan", "Plán"], ["health", "Zdraví"], ["acts", "Aktivity"]] as const} />
      {tab === "overview" && <Overview d={d} />}
      {tab === "plan" && <PlanEditor d={d} token={token} reload={load} />}
      {tab === "health" && <Health d={d} />}
      {tab === "acts" && <Acts d={d} />}
      <p className="mt-6 flex items-start gap-2 text-[11px] leading-5 text-fg-3"><ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>Běžec vám přístup dal výslovným souhlasem a může ho kdykoli zrušit; každé otevření a úprava se mu zobrazí. Došlap není zdravotnický prostředek — verdikty jsou ochranné mantinely z dat běžce, rozhodujete vy dva.</span></p>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-bg text-fg">
      <header className="border-b border-white/[.07] px-4 py-3"><div className="mx-auto flex max-w-3xl items-center justify-between"><b className="font-serif text-xl">Došlap</b><span className="text-[11px] text-fg-3">pro trenéry</span></div></header>
      <main className="mx-auto max-w-3xl px-4 pb-16">{children}</main>
    </div>
  )
}

/* ------------------------------------------------------------------ overview */
function Overview({ d }: { d: any }) {
  const days: any[] = (d.eval?.days || []).filter((x: any) => x.date >= addDays(d.date, -6))
  return (
    <>
      {days.length > 0 && (
        <Card className="mt-4">
          <Label>Posledních 7 dní a výhled</Label>
          <div className="mt-3 grid grid-cols-7 gap-1.5 sm:grid-cols-14" style={{ gridTemplateColumns: `repeat(${Math.min(days.length, 14)}, minmax(0, 1fr))` }}>
            {days.slice(0, 14).map((x: any) => {
              const s = x.sessions.find((y: any) => y.kind !== "rest") || x.sessions[0]
              const K = s ? KIND[s.kind] || KIND.other : null
              const col = x.past || (x.today && s && ["done", "partial", "more", "missed"].includes(s.status))
                ? (s?.status === "done" ? C.ok : s?.status === "missed" ? C.fg3 : s ? C.watch : C.fg4) : x.verdict ? VERDICT[x.verdict].col : C.fg4
              return (
                <div key={x.date} className={`flex min-h-[80px] flex-col items-center gap-1 rounded-[12px] border px-0.5 py-1.5 text-center ${x.today ? "border-accent/70 bg-accent/[.06]" : "border-white/[.07]"}`} title={s ? `${s.label}${s.status ? ` · ${s.status}` : ""}` : ""}>
                  <span className="text-[10.5px] font-bold text-fg-3">{WD[x.wd]}</span>
                  {K ? <K.Icon className="size-4 text-fg-2" aria-hidden /> : <span className="size-4" />}
                  <span className="text-[10px] tabular-nums text-fg-2">{s?.km ? num(s.km) : ""}</span>
                  <i className="mt-auto size-2.5 rounded-full" style={{ background: s ? col : "transparent" }} />
                </div>
              )
            })}
          </div>
          <p className="mt-2 text-[11px] text-fg-3">Minulé dny: zelená splněno, žlutá částečně nebo víc, šedá vynecháno. Dnešek a další dny: verdikt Došlapu.</p>
        </Card>
      )}
      <AdherenceCard list={d.adherence || []} />
      <WeeksAhead d={d} />
      <TrendCard trend={d.trend || []} />
    </>
  )
}

function WeeksAhead({ d }: { d: any }) {
  const weeks: any[] = (d.weeks || []).slice(0, 12)
  const ceil = d.limits?.volume?.capacity
  if (!weeks.length) return null
  const top = Math.max(...weeks.map((w) => w.km), ceil || 0, 1) * 1.12
  return (
    <Card className="mt-4">
      <Label>Plánované km na další týdny</Label>
      <p className="mt-1 text-[12px] text-fg-3">{ceil ? `Čárkovaně současná týdenní kapacita ${num(ceil)} km (co běžec prokazatelně zvládá). Týden nad ní je nárůst — den po dni ho hlídají verdikty.` : "Sloupce = naplánované kilometry v týdnu."}</p>
      <div className="relative mt-3 h-[120px]">
        {ceil ? <div className="pointer-events-none absolute inset-x-0 z-10 border-t-[1.5px] border-dashed" style={{ bottom: `${(ceil / top) * 100}%`, borderColor: C.fg2 }} /> : null}
        <div className="absolute inset-0 flex items-end gap-1 border-b border-white/15">
          {weeks.map((w) => (
            <div key={w.start} className="flex h-full flex-1 flex-col justify-end" title={`${fmtD(w.start)}: ${num(w.km)} km`}>
              <i className="block w-full rounded-t-[4px]" style={{ height: `${(w.km / top) * 100}%`, background: C.info }} />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-1 flex gap-1 text-[9.5px] tabular-nums text-fg-4">{weeks.map((w) => <span key={w.start} className="flex-1 text-center">{fmtD(w.start).replace(/\.\s?\d{4}$/, "")}</span>)}</div>
    </Card>
  )
}

/* ------------------------------------------------------------------ the plan, 6 months */
function PlanEditor({ d, token, reload }: { d: any; token: string; reload: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState<string | null>(null)
  const [weeksShown, setWeeksShown] = useState(8)
  const [copyFrom, setCopyFrom] = useState<string | null>(null)
  const [rep, setRep] = useState(1)
  const byDate = useMemo(() => {
    const m: Record<string, any[]> = {}
    for (const r of d.plan || []) (m[r.date] ||= []).push(r)
    return m
  }, [d.plan])
  const ev = useMemo(() => {
    const m: Record<string, any> = {}
    for (const x of d.eval?.days || []) m[x.date] = x
    return m
  }, [d.eval])
  const t0 = new Date(d.date + "T12:00:00")
  const ws = addDays(d.date, -((t0.getDay() + 6) % 7))
  const weeks = Array.from({ length: Math.min(27, weeksShown) }, (_, k) => addDays(ws, 7 * k))
  const doCopy = async () => {
    if (!copyFrom) return
    try {
      const r = await api.coachCopyWeek(token, copyFrom, addDays(copyFrom, 7), rep)
      toast({ title: `Zkopírováno ${r.copied} tréninků` }); setCopyFrom(null); reload()
    } catch (e: any) { toast({ title: e?.message || "Kopírování se nepovedlo" }) }
  }
  return (
    <>
      <Card className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label>Plán na 6 měsíců</Label>
          <span className="text-[11px] text-fg-3">klepněte na den · vaše úprava přepíše plán toho dne</span>
        </div>
        <div className="mt-3 grid gap-2">
          {weeks.map((w) => {
            let km = 0
            for (let k = 0; k < 7; k++) for (const r of byDate[addDays(w, k)] || []) if (KIND[r.kind]?.run) km += r.km || 0
            return (
              <div key={w} className="rounded-[14px] border border-white/[.07] p-2" data-testid="coach-plan-week">
                <div className="mb-1.5 flex items-center justify-between gap-2 px-1 text-[11.5px]">
                  <span className="font-bold text-fg-2">{`týden od ${fmtD(w)}`}</span>
                  <span className="flex items-center gap-2"><span className="tabular-nums text-fg-3">{km ? `${num(km)} km` : ""}</span>
                    <button type="button" onClick={() => setCopyFrom(w)} className="flex items-center gap-1 font-bold text-accent hover:underline" aria-label="Kopírovat týden"><Copy className="size-3" aria-hidden />kopírovat</button></span>
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {Array.from({ length: 7 }, (_, k) => {
                    const day = addDays(w, k)
                    const rows = byDate[day] || []
                    const s = rows.find((r) => r.kind !== "rest") || rows[0]
                    const K = s ? KIND[s.kind] || KIND.other : null
                    const v = ev[day]?.verdict
                    const past = day < d.date
                    return (
                      <button key={day} type="button" onClick={() => setOpen(day)} data-testid="coach-plan-day"
                        className={`flex min-h-[64px] flex-col items-center gap-0.5 rounded-[10px] px-0.5 py-1 text-center transition ${day === d.date ? "bg-accent/[.1] ring-1 ring-accent/60" : "bg-white/[.03] hover:bg-white/[.07]"} ${past ? "opacity-60" : ""}`}>
                        <span className="text-[10px] font-bold text-fg-3">{`${WD[k]} ${new Date(day + "T12:00:00").getDate()}.`}</span>
                        {K ? <K.Icon className="size-3.5 text-fg-2" aria-hidden /> : <Plus className="size-3 text-fg-4" aria-hidden />}
                        <span className="text-[10px] tabular-nums text-fg-2">{s?.km ? num(s.km) : s?.duration_min ? `${num(s.duration_min, 0)}′` : ""}</span>
                        {v && v !== "rest" && !past && <i className="size-1.5 rounded-full" style={{ background: VERDICT[v].col }} />}
                        {s?.source === "coach" && <i className="h-0.5 w-3 rounded-full bg-info" title="upraveno trenérem" />}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
        {weeksShown < 27 && <Button size="sm" variant="outline" className="mt-3" icon={CalendarDays} onClick={() => setWeeksShown((n) => Math.min(27, n + 8))}>Další týdny</Button>}
      </Card>
      {copyFrom && (
        <Sheet open onClose={() => setCopyFrom(null)}>
          <p className="t-label !text-fg-3">Kopírovat týden</p>
          <h2 className="mt-1 font-serif text-[22px]">{`Týden od ${fmtD(copyFrom)}`}</h2>
          <p className="mt-2 text-[13px] text-fg-2">Zkopíruje tréninky do následujících týdnů. Dny v cílových týdnech se přepíšou.</p>
          <div className="mt-3 flex items-center gap-2">
            <span className="text-[13px] text-fg-2">Do dalších</span>
            <select value={rep} onChange={(e) => setRep(+e.target.value)} className="rounded-lg border bg-transparent px-2 py-1.5 text-sm">
              {[1, 2, 3, 4, 6, 8, 12].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <span className="text-[13px] text-fg-2">týdnů</span>
          </div>
          <Button className="mt-4 w-full" onClick={doCopy}>Kopírovat</Button>
        </Sheet>
      )}
      {open && <DayEditor day={open} rows={byDate[open] || []} ev={ev[open]} token={token} onClose={() => setOpen(null)} onSaved={() => { setOpen(null); reload() }} />}
    </>
  )
}

function DayEditor({ day, rows, ev, token, onClose, onSaved }: { day: string; rows: any[]; ev: any; token: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [draft, setDraft] = useState<any[]>(() => rows.filter((r) => r.kind !== "rest").map((r) => ({ ...Object.fromEntries(FIELDS.map((f) => [f, r[f]])), _id: r.id })))
  const [edit, setEdit] = useState<number | "new" | null>(rows.length ? null : "new")
  const [busy, setBusy] = useState(false)
  const evOf = (i: number) => (draft[i]?._id != null ? ev?.sessions?.find((s: any) => s.id === draft[i]._id) : null)
  const save = async () => {
    setBusy(true)
    try {
      await api.coachDay(token, day, draft.filter((x) => x.kind !== "rest").map(({ _id, ...x }) => ({ ...x, date: day })))
      toast({ title: "Den uložen — běžec ho uvidí v Tréninku" }); onSaved()
    } catch (e: any) { toast({ title: e?.message || "Uložení se nepovedlo" }) } finally { setBusy(false) }
  }
  const clear = async () => {
    setBusy(true)
    try { await api.coachClearDay(token, day); toast({ title: "Den vyprázdněn" }); onSaved() } catch (e: any) { toast({ title: e?.message || "Nepovedlo se" }) } finally { setBusy(false) }
  }
  const title = new Date(day + "T12:00:00").toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" })
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="coach-day-editor">
        <p className="t-label !text-fg-3">Plán dne</p>
        <h2 className="mt-1 font-serif text-[24px] capitalize leading-tight">{title}</h2>
        {draft.map((x, i) => edit === i ? (
          <div key={i} className="nest mt-3 p-3"><SessionForm fixedDate initial={x} date={day} onCancel={() => setEdit(null)} onSave={(y) => { setDraft((dr) => dr.map((z, j) => (j === i ? Object.fromEntries(FIELDS.map((f) => [f, (y as any)[f]])) : z))); setEdit(null) }} /></div>
        ) : (
          <div key={i} className="nest mt-3 flex items-start gap-3 p-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-white/[.06]">{(() => { const K = KIND[x.kind] || KIND.other; return <K.Icon className="size-4 text-accent" aria-hidden /> })()}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-bold">{x.title || KIND[x.kind]?.label}{x.km ? ` · ${num(x.km)} km` : x.duration_min ? ` · ${num(x.duration_min, 0)} min` : ""}</p>
              <p className="text-[11.5px] text-fg-3">{[x.intervals, x.target].filter(Boolean).join(" · ")}</p>
              {evOf(i)?.verdict && (
                <div className="mt-1.5"><VerdictBadge v={evOf(i).verdict} small prelim={day !== ev?.date || !ev?.today} />
                  {evOf(i).verdict === "mod" && <div className="mt-1.5"><FitChips s={evOf(i)} /></div>}
                  {evOf(i).why?.[0] && <p className="mt-1 text-[11.5px] text-fg-2">{evOf(i).why[0]}</p>}</div>
              )}
            </div>
            <button type="button" onClick={() => setEdit(i)} aria-label="Upravit" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-white/[.06]"><Pencil className="size-4" aria-hidden /></button>
            <button type="button" onClick={() => setDraft((dr) => dr.filter((_, j) => j !== i))} aria-label="Odebrat" className="grid size-8 place-items-center rounded-full text-fg-3 hover:bg-alert/10 hover:text-alert"><Trash2 className="size-4" aria-hidden /></button>
          </div>
        ))}
        {edit === "new" ? (
          <div className="nest mt-3 p-3"><SessionForm fixedDate date={day} onCancel={() => setEdit(null)} onSave={(y) => { setDraft((dr) => [...dr, Object.fromEntries(FIELDS.map((f) => [f, (y as any)[f]]))]); setEdit(null) }} /></div>
        ) : draft.length < 4 && <Button size="sm" variant="outline" className="mt-3" icon={Plus} onClick={() => setEdit("new")}>Přidat trénink</Button>}
        <div className="mt-4 flex gap-2">
          {rows.length > 0 && <Button variant="secondary" onClick={clear} disabled={busy}>Vyprázdnit den</Button>}
          <Button className="flex-1" busy={busy} onClick={save} data-testid="coach-day-save">{draft.filter((x) => x.kind !== "rest").length ? "Uložit den" : "Uložit jako volno"}</Button>
        </div>
      </div>
    </Sheet>
  )
}

/* ------------------------------------------------------------------ health, activities */
function Health({ d }: { d: any }) {
  const h: any[] = d.health || []
  const rows: [string, string, any, string, (v: number) => string][] = [
    ["readiness", "Připravenost", HeartPulse, C.ok, (v) => `${Math.round(v)} %`],
    ["sleep", "Spánek", Moon, C.self, (v) => `${num(v)} h`],
    ["hrv", "HRV", ActIcon, C.info, (v) => `${Math.round(v)} ms`],
    ["rhr", "Klidový tep", HeartPulse, C.load, (v) => `${Math.round(v)} tepů/min`],
    ["pain", "Bolest (deník)", ActIcon, C.watch, (v) => `${v}/10`],
  ]
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      {rows.map(([k, label, I, col, fmt]) => {
        const vals = h.map((x) => x[k]).filter((v) => v != null) as number[]
        const last7 = h.slice(-7).map((x) => x[k]).filter((v) => v != null) as number[]
        const avg = (a: number[]) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : null)
        const a7 = avg(last7), a42 = avg(vals)
        return (
          <Card key={k}>
            <div className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><I className="size-4" style={{ color: col }} aria-hidden /><Label>{label}</Label></span>
              <span className="text-[11px] text-fg-3">42 dní</span></div>
            {vals.length >= 2 ? <div className="mt-2"><Sparkline vals={vals} color={col} /></div> : <p className="mt-3 text-[12px] text-fg-3">{k === "pain" ? "Bez bolesti v deníku." : "Málo dat."}</p>}
            {a7 != null && a42 != null && <p className="mt-1 text-[11.5px] text-fg-2">{`posledních 7 dní ${fmt(a7)} · průměr ${fmt(a42)}`}</p>}
          </Card>
        )
      })}
    </div>
  )
}

function Acts({ d }: { d: any }) {
  const a: any[] = d.activities || []
  const pace = (s?: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}/km` : "")
  return (
    <Card className="mt-4">
      <Label>Aktivity za 14 dní</Label>
      {!a.length && <p className="mt-2 text-sm text-fg-3">Žádné aktivity.</p>}
      <div className="mt-2 divide-y divide-white/[.07]">
        {a.map((x) => (
          <div key={x.id} className="flex items-center gap-3 py-2.5">
            <span className="w-14 shrink-0 text-[11.5px] tabular-nums text-fg-3">{fmtD(x.date)}</span>
            <span className="min-w-0 flex-1">
              <b className="block truncate text-[13px]">{x.title || x.sport}</b>
              <span className="block text-[11.5px] tabular-nums text-fg-3">{[x.km ? `${num(x.km)} km` : null, x.min ? `${x.min} min` : null, x.sport === "running" ? pace(x.pace) : null, x.hr ? `tep ${x.hr}` : null, x.ascent ? `+${x.ascent} m` : null, x.rpe ? `RPE ${x.rpe}` : null].filter(Boolean).join(" · ")}</span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}
