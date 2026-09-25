import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, Chip, Field, Label, Sheet, Slider, useAsync, useToast } from "@/ui"
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
        <div className="mt-3 inline-flex flex-wrap gap-2 rounded-full border border-white/10 bg-[#0c201d] p-1 text-xs font-semibold">
          {subtabs.map(([k, l]) => (
            <button key={k} onClick={() => setSub(k)} className={`rounded-full px-4 py-1.5 transition ${sub === k ? "bg-[#c7ff54] text-[#071313]" : "text-[#9bb3aa] hover:text-[#f1f8f1]"}`}>
              {l}
            </button>
          ))}
        </div>
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
            <div key={rm.booking_id} className="mt-3 rounded-xl bg-[#3c2922] p-3 text-sm text-[#ffc1ab]">
              <b>Zítra máte termín</b> · {fmtSlot(rm.slot_at)}{rm.physio_name ? ` · ${rm.physio_name}` : ""}
              {rm.prep_info && <p className="mt-1 text-xs">{rm.prep_info}</p>}
            </div>
          ))}
          {!r?.physio_interest ? (
            <>
              <p className="mt-2 text-sm text-[#64736e]">Chcete probrat svá data s fyzioterapeutem? Nejdřív potvrďte zájem — teprve pak vás uvidí a nabídne termíny.</p>
              <button onClick={async () => { await api.setInterest(rid, true); toast({ title: "Zájem potvrzen" }); refresh() }} className="mt-4 w-full rounded-full bg-[#c7ff54] py-2.5 text-sm font-bold text-[#071313]">Mám zájem o fyzioterapii</button>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm text-[#64736e]">Zájem potvrzen ✓ <button onClick={async () => { await api.setInterest(rid, false); refresh() }} className="ml-1 text-xs font-bold text-[#71837b] underline">zrušit</button></p>
              <button onClick={onFind} className="mt-3 w-full rounded-full bg-[#c7ff54] py-2.5 text-sm font-bold text-[#071313]">Naplánovat schůzku</button>
              {bookings.length > 0 && (
                <div className="mt-3 divide-y divide-white/10">{bookings.map((b: any) => (
                  <div key={b.id} className="flex items-center gap-2 py-2 text-sm">
                    <span className="flex-1"><b>{pn(b.physio_id)}</b><em className="block text-xs not-italic text-[#71837b]">{fmtSlot(b.slot_at)} · {b.status === "requested" ? "čeká na potvrzení" : "potvrzeno"}</em></span>
                    <Chip tone={b.status === "confirmed" ? "ok" : "watch"}>{b.status === "requested" ? "čeká" : "potvrzeno"}</Chip>
                    <button onClick={async () => { await api.cancelBooking(rid, b.id); refresh() }} className="text-xs font-bold text-[#71837b]">Zrušit</button>
                  </div>
                ))}</div>
              )}
              {carePids.size > 0 && (
                <div className="mt-3 border-t border-white/10 pt-3">
                  <Label>Spolupráce</Label>
                  {[...carePids].map((pid) => (
                    <div key={pid} className="mt-2 flex items-center gap-2 text-sm"><b className="flex-1">{pn(pid)}</b><button onClick={async () => { await api.declinePhysio(rid, pid); toast({ title: "Spolupráce odvolána" }); refresh() }} className="rounded-full border border-white/15 px-3 py-1 text-xs font-bold text-[#71837b]">Odvolat</button></div>
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
  const [body, setBody] = useState("")
  const send = async () => { const b = body.trim(); if (!b) return; setBody(""); await api.send(rid, "runner", b); refresh() }
  return (
    <Card className="flex flex-col">
      <div className="flex items-center gap-3 border-b border-white/10 pb-4">
        <span className="grid size-10 place-items-center rounded-full bg-[#c7ff54] text-xs font-bold text-[#071313]">{physioName ? initials(physioName) : "?"}</span>
        <div><b className="text-sm text-[#f1f8f1]">{physioName || "Zatím bez fyzioterapeuta"}</b><p className="text-xs text-[#71837b]">{physioName ? "vede vaši péči" : "chat se otevře po převzetí případu"}</p></div>
      </div>
      <div className="mt-4 flex max-h-[52vh] min-h-[180px] flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {ms.length ? ms.map((m) => (
          <div key={m.id} className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${m.sender === "runner" ? "ml-auto rounded-tr-sm bg-[#c7ff54] text-[#071313]" : m.sender === "system" ? "mx-auto bg-white/5 text-[#a9c2b9]" : "rounded-tl-sm bg-[#17382f] text-[#f1f8f1]"}`}>
            {m.body}<span className="mt-1 block text-[10px] opacity-60">{fmtDT(m.created_at)}</span>
          </div>
        )) : <p className="m-auto text-sm text-[#71837b]">Zatím žádné zprávy. Napište první.</p>}
      </div>
      <div className="mt-4 flex gap-2">
        <input value={body} onChange={(e) => setBody(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Napsat zprávu…" className="flex-1 rounded-xl border px-3 py-2.5 text-sm" />
        <button onClick={send} className="rounded-full bg-[#c7ff54] px-5 text-sm font-bold text-[#071313]">Odeslat</button>
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
            <div className="mt-2 rounded-xl bg-[#3c2922] p-3 text-sm text-[#ffc1ab]"><b>{injActive.site}</b> · OSTRC {injActive.severity}/100<br />
              <button onClick={async () => { await api.reportInjury(rid, { resolve: true }); refresh() }} className="mt-2 rounded-full border border-white/15 px-3 py-1 text-xs font-bold">Označit jako zahojené</button>
              <p className="mt-2 text-[11px] leading-4 text-[#ffc1ab]/80">Pak následují 3 týdny postupného návratu (50 → 75 → 90 % týdne před zraněním), první 2 týdny bez intenzity.</p></div>
            <button onClick={onReport} className="mt-3 text-xs font-bold text-[#71837b] underline">Nahlásit další obtíže</button>
          </Card>
        ) : (
          <Card>
            <Label>Nahlásit obtíže</Label>
            <p className="mt-2 text-sm text-[#64736e]">Něco vás začalo bolet? Nahlaste to — pomůže to kalibrovat riziko i vašemu fyzioterapeutovi.</p>
            <button onClick={onReport} className="mt-3 rounded-full bg-[#e77a59] px-4 py-2 text-xs font-bold text-[#071313]">Nahlásit obtíže</button>
          </Card>
        )}

        {rtr && (
          <Card>
            <div className="flex items-center justify-between"><Label>Návrat k běhu</Label><Chip>úroveň {rtr.current_level}/{rtr.level_count}</Chip></div>
            <p className="mt-2 font-serif text-lg">{rtr.current?.label}</p>
            <p className="text-xs text-[#71837b]">Splněno {rtr.cleared_at_current}/{rtr.sessions_per_level} sezení · bolest do {rtr.pain_threshold}/10 posune dál.</p>
            <button onClick={onRtr} className="mt-3 w-full rounded-full border border-white/15 py-2 text-sm font-bold text-[#c7ff54]">Zaznamenat sezení</button>
          </Card>
        )}

        {conclusion && (
          <Card className="lg:col-span-2">
            <Label>Závěr z prohlídky</Label>
            {conclusion.finding && <p className="mt-2 font-serif text-lg">{conclusion.finding}</p>}
            <p className="mt-1 whitespace-pre-wrap text-sm text-[#64736e]">{conclusion.summary}</p>
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
        <span className="hidden text-[10px] text-[#71837b] sm:inline">týdenní check-in:</span>
        <button onClick={async () => { await api.reportInjury(rid, { kind: "weekly" }); toast({ title: "Díky — zaznamenáno" }); refresh() }} className="rounded-full bg-[#c7ff54] px-2.5 py-1 text-[10px] font-bold text-[#071313]">Bez obtíží</button>
        <button onClick={() => setOpen(true)} className="rounded-full border border-[#e77a59]/50 px-2.5 py-1 text-[10px] font-bold text-[#ffc1ab]">Obtíže</button>
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
      <p className="mt-1 text-xs text-[#a9c2b9]">Vyberte, kdy se vám hodí. Termín potvrdí fyzio, pak vám přijde do kalendáře a den předem připomenutí.</p>
      <div className="mt-4"><Label>Dny</Label><div className="mt-2 flex flex-wrap gap-2">{DOW.map(([k, l]) => <button key={k} onClick={() => load(toggle(dow, setDow, k), part)} className={`rounded-full px-3 py-1.5 text-xs font-bold ${dow.has(k) ? "bg-[#c7ff54] text-[#071313]" : "border border-white/15 text-[#a9c2b9]"}`}>{l}</button>)}</div></div>
      <div className="mt-3"><Label>Část dne</Label><div className="mt-2 flex flex-wrap gap-2">{DAYPART.map(([k, l]) => <button key={k} onClick={() => load(dow, toggle(part, setPart, k))} className={`rounded-full px-3 py-1.5 text-xs font-bold ${part.has(k) ? "bg-[#c7ff54] text-[#071313]" : "border border-white/15 text-[#a9c2b9]"}`}>{l}</button>)}</div></div>
      <div className="mt-5 space-y-3">
        {busy && <p className="text-sm text-[#71837b]">Načítám…</p>}
        {opts && opts.length === 0 && <p className="text-sm text-[#71837b]">Žádné volné termíny pro tenhle filtr.</p>}
        {opts?.map((pp) => (
          <div key={pp.id} className="rounded-2xl border border-white/10 p-4">
            <div className="flex items-start justify-between"><div><b>{pp.name}</b><p className="text-xs text-[#71837b]">{pp.clinic?.name || ""}{pp.clinic?.city ? ` · ${pp.clinic.city}` : ""} · {pp.years_exp || "—"} let · ★ {pp.rating || "—"}</p></div>{pp.price_czk ? <Chip>{czk(pp.price_czk)}</Chip> : null}</div>
            {pp.bio && <p className="mt-2 text-xs text-[#64736e]">{pp.bio}</p>}
            <div className="mt-3 flex flex-wrap gap-2">{pp.slots.map((s: any) => (
              <button key={s.id} onClick={() => run(async () => { await api.requestSlot(s.id); toast({ title: "Požádáno — čeká na potvrzení" }); onDone() })} className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-bold text-[#c7ff54]">{fmtSlot(s.slot_at)}</button>
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
      {intro && <p className="mt-1 text-xs leading-5 text-[#a9c2b9]">{intro}</p>}
      <p className="mt-1 text-[11px] leading-4 text-[#71837b]">Obtíže s dopadem na trénink se zapíšou do historie zranění v profilu (datum a strana). Po označení „zahojené" vás aplikace vrátí k běhu postupně: 50 → 75 → 90 % běžného týdne, první 2 týdny bez intenzity.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="grid gap-3">
          {OSTRC.map(([name, label, opts]) => (
            <Field key={name} label={label}><select value={q[name]} onChange={(e) => setQ({ ...q, [name]: Number(e.target.value) })} className="w-full rounded-xl border px-3 py-2 text-sm">{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></Field>
          ))}
        </div>
        <div>
          <Label>Kde to bolí</Label>
          <p className="mt-1 text-xs text-[#71837b]">Klepněte na všechna místa, která bolí — silueta rozliší levou a pravou stranu.</p>
          <div className="mt-3"><MuscleAnatomy multi onSelect={setPoints} initialRegions={initialRegions} /></div>
        </div>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
      <button disabled={busy} onClick={() => run(async () => {
        const pts = points.map((p) => ({ region: p.region, side: p.side || null, type: p.kind }))
        await api.reportInjury(rid, { kind: "adhoc", ...q, pain_points: pts })
        toast({ title: "Nahlášeno" }); onDone()
      })} className="mt-5 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">Nahlásit</button>
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
      <p className="mt-1 text-xs text-[#a9c2b9]">Úroveň {plan.current_level}: <b>{plan.current?.label}</b>. Bolest do {plan.pain_threshold}/10 vás posune dál.</p>
      <Field label="Dokončil/a jsem sezení"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={completed} onChange={(e) => setCompleted(e.target.checked)} className="accent-[#c7ff54]" /> odškrtněte, pokud jste musel/a přerušit</label></Field>
      <Field label="Bolest během sezení" hint="0 žádná"><Slider name="pain" min={0} max={10} value={pain} onChange={setPain} /></Field>
      <Field label="Vnímaná námaha (RPE)"><Slider name="rpe" min={1} max={10} value={rpe} onChange={setRpe} /></Field>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
      <button disabled={busy} onClick={() => run(async () => { const p = await api.logRtrSession(plan.id, { pain, rpe, completed }); toast({ title: p.status === "completed" ? "Návrat k běhu dokončen! 🎉" : `Úroveň ${p.current_level}/${p.level_count}` }); onDone() })} className="mt-5 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">Uložit sezení</button>
    </Sheet>
  )
}
