import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { AlertBanner, Button, Card, Chip, Field, Label, ListRow, Segmented, Sheet, Slider, useAsync, useToast } from "@/ui"
import { CalendarDays, CalendarClock, Send, Star, UserRound } from "lucide-react"
import { fmtSlot, fmtDT, initials, czk } from "@/lib"
import { Head, Program } from "@/tabs"
import MuscleAnatomy, { type BodyPoint } from "@/components/MuscleAnatomy"

const OSTRC: [string, string, [number, string][]][] = [
  ["q_participation", "Účast na tréninku/závodech", [[0, "Plná bez obtíží"], [8, "Plná s obtížemi"], [17, "Omezená"], [25, "Nemohl/a jsem"]]],
  ["q_volume", "Objem tréninku", [[0, "Bez omezení"], [8, "Mírné"], [17, "Střední"], [25, "Velké/úplné"]]],
  ["q_performance", "Vliv na výkon", [[0, "Bez vlivu"], [8, "Mírný"], [17, "Střední"], [25, "Velký"]]],
  ["q_pain", "Bolest", [[0, "Žádná"], [8, "Mírná"], [17, "Střední"], [25, "Silná"]]],
]
const REGIONS = [["achilles", "Achillova šlacha"], ["calf", "Lýtko"], ["shin", "Holeň"], ["knee", "Koleno"], ["hamstring", "Hamstring"], ["quad", "Kvadriceps"], ["hip", "Kyčel"], ["glute", "Hýždě"], ["foot", "Chodidlo"], ["plantar", "Plantární fascie"], ["ankle", "Kotník"], ["itb", "IT pás"], ["groin", "Tříslo"], ["lowback", "Bederní páteř"]]
const DOW = [["0", "Po"], ["1", "Út"], ["2", "St"], ["3", "Čt"], ["4", "Pá"]]
const DAYPART = [["morning", "Ráno"], ["afternoon", "Odpoledne"], ["evening", "Večer"]]

// Péče = a hub with sub-tabs. Fyzioterapeut (chat + booking), Program (moved
// in from its own top tab), and Zdraví (OSTRC report / return-to-run / závěr).
export function Care() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const rtr = boot?.rtr
  const [sub, setSub] = useState<"physio" | "program" | "health">("physio")
  const [findOpen, setFindOpen] = useState(false)
  const [injOpen, setInjOpen] = useState(false)
  const [rtrOpen, setRtrOpen] = useState(false)

  const subtabs: [typeof sub, string][] = [["physio", "Fyzioterapeut"], ["program", "Program"], ["health", "Zdraví"]]

  return (
    <>
      {findOpen && <FindSlotSheet onClose={() => setFindOpen(false)} onDone={() => { setFindOpen(false); refresh() }} />}
      {injOpen && <InjurySheet rid={rid} onClose={() => setInjOpen(false)} onDone={() => { setInjOpen(false); refresh() }} />}
      {rtrOpen && rtr && <RtrSheet plan={rtr} onClose={() => setRtrOpen(false)} onDone={() => { setRtrOpen(false); refresh() }} />}

      <div className="mb-6">
        <Label>Péče</Label>
        <Segmented className="mt-3" ariaLabel="Péče" options={subtabs} value={sub} onChange={setSub} />
      </div>

      {sub === "physio" && <PhysioSection onFind={() => setFindOpen(true)} />}
      {sub === "program" && <Program />}
      {sub === "health" && <HealthSection onReport={() => setInjOpen(true)} onRtr={() => setRtrOpen(true)} />}
    </>
  )
}

// Backwards-compatible alias (older imports referenced RunnerCare).
export const RunnerCare = Care

function PhysioSection({ onFind }: { onFind: () => void }) {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const r = boot?.runner
  const toast = useToast()
  const reminders = (boot?.reminders || []) as any[]
  const bookings = (boot?.bookings || []).filter((b: any) => b.status === "requested" || b.status === "confirmed")
  const carePids = new Set<string>([...(boot?.bookings || []).filter((b: any) => b.status === "confirmed").map((b: any) => b.physio_id), ...(boot?.program ? [boot.program.physio_id] : [])].filter(Boolean))
  const pn = (pid: string) => boot?.physios?.[pid]?.name || "fyzioterapeut"

  return (
    <>
      <Head kicker="Fyzioterapeut" title={r?.physio_interest ? "Domluvte se a napište si" : "Spojte se s fyzioterapeutem"} sub="Napište přímo tomu, kdo vede vaši péči, a naplánujte si schůzku ve chvíli, kdy potřebujete." />
      <div className="grid gap-4 lg:grid-cols-[1.25fr_.75fr]">
        <PhysioChat />
        <Card className="self-start">
          <Label>Schůzka</Label>
          {reminders.map((rm) => (
            <AlertBanner key={rm.booking_id} tone="alert" icon={CalendarClock} className="mt-3"
              title={<>Zítra máte termín · {fmtSlot(rm.slot_at)}{rm.physio_name ? ` · ${rm.physio_name}` : ""}</>}>
              {rm.prep_info || undefined}
            </AlertBanner>
          ))}
          {!r?.physio_interest ? (
            <>
              <p className="mt-2 text-sm text-fg-2">Chcete probrat svá data s fyzioterapeutem? Nejdřív potvrďte zájem — teprve pak vás uvidí a nabídne termíny.</p>
              <Button className="mt-4 w-full" onClick={async () => { await api.setInterest(rid, true); toast({ title: "Zájem potvrzen" }); refresh() }}>Mám zájem o fyzioterapii</Button>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm text-fg-2"><span className="font-bold text-ok">Zájem potvrzen ✓</span> <button onClick={async () => { await api.setInterest(rid, false); refresh() }} className="ml-1 text-[12px] font-bold text-fg-3 underline underline-offset-2 hover:text-fg-2">zrušit</button></p>
              <Button className="mt-3 w-full" icon={CalendarDays} onClick={onFind}>Naplánovat schůzku</Button>
              {bookings.length > 0 && (
                <div className="mt-2 divide-y divide-white/[.07]">{bookings.map((b: any) => (
                  <ListRow key={b.id} icon={CalendarDays} tone={b.status === "confirmed" ? "ok" : "watch"} title={pn(b.physio_id)}
                    meta={`${fmtSlot(b.slot_at)} · ${b.status === "requested" ? "čeká na potvrzení" : "potvrzeno"}`}
                    trailing={<>
                      <Chip tone={b.status === "confirmed" ? "ok" : "watch"}>{b.status === "requested" ? "čeká" : "potvrzeno"}</Chip>
                      <button onClick={async () => { await api.cancelBooking(rid, b.id); refresh() }} className="shrink-0 text-[12px] font-bold text-fg-3 hover:text-alert">Zrušit</button>
                    </>} />
                ))}</div>
              )}
              {carePids.size > 0 && (
                <div className="mt-3 border-t border-white/[.08] pt-3">
                  <Label>Spolupráce</Label>
                  {[...carePids].map((pid) => (
                    <ListRow key={pid} icon={UserRound} tone="accent" title={pn(pid)}
                      trailing={<Button size="sm" variant="outline" onClick={async () => { await api.declinePhysio(rid, pid); toast({ title: "Spolupráce odvolána" }); refresh() }}>Odvolat</Button>} />
                  ))}
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  )
}

function PhysioChat() {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const ms = (boot?.messages || []) as any[]
  const p = boot?.program
  const physioName = p ? boot?.physios?.[p.physio_id]?.name : null
  // FIX-7: the chat opens once a physio has taken the case (a program from them,
  // or a message they've already sent) — same condition the header states.
  const open = !!physioName || ms.some((m) => m.sender === "physio")
  const [body, setBody] = useState("")
  const send = async () => { const b = body.trim(); if (!b || !open) return; setBody(""); await api.send(rid, "runner", b); refresh() }
  return (
    <Card className="flex flex-col">
      <div className="flex items-center gap-3 border-b border-white/[.08] pb-4">
        <span className={`grid size-10 place-items-center rounded-full text-xs font-extrabold ${physioName ? "bg-accent text-ink" : "bg-white/[.07] text-fg-3"}`}>{physioName ? initials(physioName) : <UserRound className="size-4" aria-hidden />}</span>
        <div><b className="text-sm font-bold text-fg">{physioName || "Zatím bez fyzioterapeuta"}</b><p className="text-[12px] text-fg-3">{physioName ? "vede vaši péči" : "chat se otevře po převzetí případu"}</p></div>
      </div>
      <div className="mt-4 flex max-h-[52vh] min-h-[180px] flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {ms.length ? ms.map((m) => (
          <div key={m.id} className={`max-w-[85%] rounded-[18px] px-3.5 py-2 text-sm leading-5 ${m.sender === "runner" ? "ml-auto rounded-tr-[6px] bg-accent text-ink" : m.sender === "system" ? "mx-auto rounded-[12px] bg-white/[.05] text-center text-[12px] text-fg-2" : "rounded-tl-[6px] bg-info-bg text-fg"}`}>
            {m.body}<span className="mt-1 block text-[11px] opacity-60">{fmtDT(m.created_at)}</span>
          </div>
        )) : <p className="m-auto text-sm text-fg-3">{open ? "Zatím žádné zprávy. Napište první." : "Zatím žádné zprávy."}</p>}
      </div>
      <div className="mt-4 flex gap-2">
        <input value={body} onChange={(e) => setBody(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} disabled={!open} aria-label="Zpráva"
          placeholder={open ? "Napsat zprávu…" : "Chat se otevře po převzetí případu"} className="min-w-0 flex-1 rounded-xl border px-3 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-60" />
        <Button icon={Send} onClick={send} disabled={!open || !body.trim()}>Odeslat</Button>
      </div>
    </Card>
  )
}

function HealthSection({ onReport, onRtr }: { onReport: () => void; onRtr: () => void }) {
  const { me, boot, refresh } = useApp()
  const rid = me!.runner_id!
  const a = boot?.assessment
  const rtr = boot?.rtr
  const conclusion = (boot?.conclusions || [])[0]
  const injActive = a?.injury?.active

  return (
    <>
      <Head kicker="Zdraví" title="Obtíže a návrat k běhu" sub="Nahlášené obtíže kalibrují odhad rizika i práci vašeho fyzioterapeuta. Tady je nahlásíte a sledujete návrat zpět." />
      <div className="grid gap-4 lg:grid-cols-2">
        {injActive ? (
          <Card>
            <Label>Nahlášené zranění</Label>
            <AlertBanner tone="alert" className="mt-2" title={<>{injActive.site} · OSTRC {injActive.severity}/100</>}
              action={<Button size="sm" variant="outline" onClick={async () => { await api.reportInjury(rid, { resolve: true }); refresh() }}>Označit jako zahojené</Button>}>
              Pak následují 3 týdny postupného návratu (50 → 75 → 90 % týdne před zraněním), první 2 týdny bez intenzity.
            </AlertBanner>
            <button onClick={onReport} className="mt-3 text-[12px] font-bold text-fg-3 underline underline-offset-2 hover:text-fg-2">Nahlásit další obtíže</button>
          </Card>
        ) : (
          <Card>
            <Label>Nahlásit obtíže</Label>
            <p className="mt-2 text-sm text-fg-2">Něco vás začalo bolet? Nahlaste to — pomůže to kalibrovat riziko i vašemu fyzioterapeutovi.</p>
            <Button variant="danger" className="mt-3" onClick={onReport}>Nahlásit obtíže</Button>
          </Card>
        )}

        {rtr && (
          <Card>
            <div className="flex items-center justify-between"><Label>Návrat k běhu</Label><Chip tone="accent">úroveň {rtr.current_level}/{rtr.level_count}</Chip></div>
            <p className="mt-2 font-serif text-lg">{rtr.current?.label}</p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(((rtr.current_level - 1 + (rtr.cleared_at_current || 0) / (rtr.sessions_per_level || 1)) / (rtr.level_count || 1)) * 100)}%` }} /></div>
            <p className="mt-2 text-[12px] text-fg-3">Splněno {rtr.cleared_at_current}/{rtr.sessions_per_level} sezení · bolest do {rtr.pain_threshold}/10 posune dál.</p>
            <Button variant="outline" className="mt-3 w-full" onClick={onRtr}>Zaznamenat sezení</Button>
          </Card>
        )}

        {conclusion && (
          <Card className="lg:col-span-2">
            <Label>Závěr z prohlídky</Label>
            {conclusion.finding && <p className="mt-2 font-serif text-lg">{conclusion.finding}</p>}
            <p className="mt-1 whitespace-pre-wrap text-sm text-fg-2">{conclusion.summary}</p>
          </Card>
        )}
      </div>
    </>
  )
}

// Small corner control for the recovery card: the weekly health check-in.
// Disappears once done this week (injury_prompt_due flips false after refresh).
export function WeeklyCheckButton() {
  const { me, boot, refresh } = useApp()
  const rid = me?.runner_id
  const [open, setOpen] = useState(false)
  const toast = useToast()
  if (!rid || !boot?.injury_prompt_due) return null
  return (
    <>
      {open && <InjurySheet rid={rid} onClose={() => setOpen(false)} onDone={() => { setOpen(false); refresh() }} />}
      <div className="flex items-center gap-1.5">
        <span className="hidden text-[11px] text-fg-3 sm:inline">týdenní check-in:</span>
        <button onClick={async () => { await api.reportInjury(rid, { kind: "weekly" }); toast({ title: "Díky — zaznamenáno" }); refresh() }} className="rounded-full bg-accent px-2.5 py-1 text-[11px] font-bold text-ink hover:brightness-105">Bez obtíží</button>
        <button onClick={() => setOpen(true)} className="rounded-full border border-alert/50 px-2.5 py-1 text-[11px] font-bold text-alert-soft hover:bg-alert/10">Obtíže</button>
      </div>
    </>
  )
}

function FindSlotSheet({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [dow, setDow] = useState<Set<string>>(new Set())
  const [part, setPart] = useState<Set<string>>(new Set())
  const [opts, setOpts] = useState<any[] | null>(null)
  const { busy, run } = useAsync()
  const toast = useToast()
  const load = (d = dow, p = part) => run(async () => setOpts(await api.bookingOptions([...d].join(","), [...p].join(","))))
  const toggle = (s: Set<string>, set: (x: Set<string>) => void, k: string) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); set(n); return n }
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">Najít termín</h2>
      <p className="mt-1 text-[13px] leading-5 text-fg-2">Vyberte, kdy se vám hodí. Termín potvrdí fyzio, pak vám přijde do kalendáře a den předem připomenutí.</p>
      <div className="mt-4"><Label>Dny</Label><div className="mt-2 flex flex-wrap gap-2">{DOW.map(([k, l]) => <button key={k} onClick={() => load(toggle(dow, setDow, k), part)} aria-pressed={dow.has(k)} className={`rounded-full px-3.5 py-1.5 text-[12px] font-bold ${dow.has(k) ? "bg-accent text-ink" : "border border-white/15 text-fg-2 hover:border-white/30"}`}>{l}</button>)}</div></div>
      <div className="mt-3"><Label>Část dne</Label><div className="mt-2 flex flex-wrap gap-2">{DAYPART.map(([k, l]) => <button key={k} onClick={() => load(dow, toggle(part, setPart, k))} aria-pressed={part.has(k)} className={`rounded-full px-3.5 py-1.5 text-[12px] font-bold ${part.has(k) ? "bg-accent text-ink" : "border border-white/15 text-fg-2 hover:border-white/30"}`}>{l}</button>)}</div></div>
      <div className="mt-5 space-y-3">
        {busy && <p className="text-sm text-fg-3">Načítám…</p>}
        {opts && opts.length === 0 && <p className="text-sm text-fg-3">Žádné volné termíny pro tenhle filtr.</p>}
        {opts?.map((pp) => (
          <div key={pp.id} className="nest p-4">
            <div className="flex items-start gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent/15 text-xs font-extrabold text-accent">{initials(pp.name)}</span>
              <div className="min-w-0 flex-1"><b className="font-bold">{pp.name}</b><p className="text-[12px] text-fg-3">{pp.clinic?.name || ""}{pp.clinic?.city ? ` · ${pp.clinic.city}` : ""} · {pp.years_exp || "—"} let · <Star className="inline size-3 -translate-y-px fill-watch text-watch" aria-hidden /> {pp.rating || "—"}</p></div>
              {pp.price_czk ? <Chip tone="accent">{czk(pp.price_czk)}</Chip> : null}
            </div>
            {pp.bio && <p className="mt-2 text-[13px] leading-5 text-fg-2">{pp.bio}</p>}
            <div className="mt-3 flex flex-wrap gap-2">{pp.slots.map((s: any) => (
              <button key={s.id} onClick={() => run(async () => { await api.requestSlot(s.id); toast({ title: "Požádáno — čeká na potvrzení" }); onDone() })} className="rounded-full border border-accent/35 px-3 py-1.5 text-[12px] font-bold text-accent hover:bg-accent/10">{fmtSlot(s.slot_at)}</button>
            ))}</div>
          </div>
        ))}
      </div>
    </Sheet>
  )
}

export function InjurySheet({ rid, onClose, onDone, initialRegions = [], initialQ, intro }: {
  rid: string; onClose: () => void; onDone: () => void; initialRegions?: string[]; initialQ?: Record<string, number>; intro?: string
}) {
  const [q, setQ] = useState<Record<string, number>>({ q_participation: 0, q_volume: 0, q_performance: 0, q_pain: 0, ...initialQ })
  const [points, setPoints] = useState<BodyPoint[]>([])
  const { busy, err, run } = useAsync()
  const toast = useToast()
  return (
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">Nahlásit obtíže (OSTRC)</h2>
      {intro && <p className="mt-1 text-[13px] leading-5 text-fg-2">{intro}</p>}
      <p className="mt-1 text-[11px] leading-4 text-fg-3">Obtíže s dopadem na trénink se zapíšou do historie zranění v profilu (datum a strana). Po označení „zahojené" vás aplikace vrátí k běhu postupně: 50 → 75 → 90 % běžného týdne, první 2 týdny bez intenzity.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="grid gap-3">
          {OSTRC.map(([name, label, opts]) => (
            <Field key={name} label={label}><select value={q[name]} onChange={(e) => setQ({ ...q, [name]: Number(e.target.value) })} className="w-full rounded-xl border px-3 py-2 text-sm">{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></Field>
          ))}
        </div>
        <div>
          <Label>Kde to bolí</Label>
          <p className="mt-1 text-[12px] leading-5 text-fg-3">Klepněte na všechna místa, která bolí — silueta rozliší levou a pravou stranu.</p>
          <div className="mt-3"><MuscleAnatomy multi onSelect={setPoints} initialRegions={initialRegions} /></div>
        </div>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
      <button disabled={busy} onClick={() => run(async () => {
        const pts = points.map((p) => ({ region: p.region, side: p.side || null, type: p.kind }))
        await api.reportInjury(rid, { kind: "adhoc", ...q, pain_points: pts })
        toast({ title: "Nahlášeno" }); onDone()
      })} className="btn btn-primary mt-5 w-full py-3 text-sm">Nahlásit</button>
    </Sheet>
  )
}

function RtrSheet({ plan, onClose, onDone }: { plan: any; onClose: () => void; onDone: () => void }) {
  const [pain, setPain] = useState(0)
  const [rpe, setRpe] = useState(4)
  const [completed, setCompleted] = useState(true)
  const { busy, err, run } = useAsync()
  const toast = useToast()
  return (
    <Sheet open onClose={onClose}>
      <h2 className="font-serif text-2xl">Sezení návratu k běhu</h2>
      <p className="mt-1 text-[13px] text-fg-2">Úroveň {plan.current_level}: <b>{plan.current?.label}</b>. Bolest do {plan.pain_threshold}/10 vás posune dál.</p>
      <Field label="Dokončil/a jsem sezení"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={completed} onChange={(e) => setCompleted(e.target.checked)} className="accent-accent" /> odškrtněte, pokud jste musel/a přerušit</label></Field>
      <Field label="Bolest během sezení" hint="0 žádná"><Slider name="pain" min={0} max={10} value={pain} onChange={setPain} tone="pain" /></Field>
      <Field label="Vnímaná námaha (RPE)"><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
      <button disabled={busy} onClick={() => run(async () => { const p = await api.logRtrSession(plan.id, { pain, rpe, completed }); toast({ title: p.status === "completed" ? "Návrat k běhu dokončen! 🎉" : `Úroveň ${p.current_level}/${p.level_count}` }); onDone() })} className="btn btn-primary mt-5 w-full py-3 text-sm">Uložit sezení</button>
    </Sheet>
  )
}
