// Péče → Fyzioterapeut, the runner's open tasks (physio brief 2026-11-09 B1, B4, B5, M1): a deposit to pay
// (a test payment — no money moves), a time offered from the waitlist, a questionnaire from the physio and the
// three-month follow-up after discharge. Nothing shows when there is nothing to do.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { Button, Card, Field, Label, Slider, useAsync, useToast } from "@/ui"
import { fmtSlot } from "@/lib"

export function CareTasks({ rid, onChange }: { rid: string; onChange: () => void }) {
  const [d, setD] = useState<any>(null)
  const load = () => Promise.all([
    api.runnerPayments(rid).catch(() => ({ items: [] })), api.myWaitlist(rid).catch(() => ({ items: [] })),
    api.promsDue(rid).catch(() => ({ items: [] })), api.followups(rid).catch(() => ({ items: [] })),
  ]).then(([p, w, pr, f]) => setD({ pay: p.items.filter((x: any) => x.status === "pending" && x.kind !== "subscription"),
    wait: w.items, proms: pr.items, fu: f.items }))
  useEffect(() => { void load() }, [rid]) // eslint-disable-line react-hooks/exhaustive-deps
  const toast = useToast()
  const { busy, run } = useAsync()
  if (!d || (!d.pay.length && !d.wait.length && !d.proms.length && !d.fu.length)) return null
  const done = () => { void load(); onChange() }
  return (
    <Card data-testid="care-tasks">
      <Label>Čeká na vás</Label>
      <div className="mt-2 grid gap-3">
        {d.pay.map((p: any) => (
          <div key={p.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="min-w-0 flex-1">{`${p.kind === "deposit" ? "Záloha" : "Platba"} za návštěvu: ${p.amount_czk} Kč`}
              <span className="block text-[12px] text-fg-3">Zkušební platba — žádné peníze se nepřevádějí.</span></span>
            <Button size="sm" busy={busy} onClick={() => run(async () => { await api.mockPay(p.id); toast({ title: "Zaplaceno" }); done() })}>Zaplatit</Button>
          </div>
        ))}
        {d.wait.map((w: any) => (
          <div key={w.id} className="flex flex-wrap items-center gap-2 text-sm">
            {w.status === "offered" ? <>
              <span className="min-w-0 flex-1">{`Uvolněný termín: ${fmtSlot(w.offered_slot_at)} · ${w.physio}`}<span className="block text-[12px] text-fg-3">Nabídka platí 2 hodiny.</span></span>
              <Button size="sm" busy={busy} onClick={() => run(async () => { await api.waitlistAccept(w.id); toast({ title: "Požádáno — čeká na potvrzení" }); done() })}>Chci ho</Button>
            </> : <>
              <span className="min-w-0 flex-1">{`Pořadník: ${w.physio}`}<span className="block text-[12px] text-fg-3">Ozveme se, až se uvolní vhodný termín.</span></span>
              <button className="text-[12px] font-bold text-fg-3 hover:text-alert" onClick={() => run(async () => { await api.waitlistLeave(w.id); done() })}>Odhlásit</button>
            </>}
          </div>
        ))}
        {d.proms.map((p: any) => <PromForm key={p.schedule_id} p={p} onDone={done} />)}
        {d.fu.map((f: any) => <FollowupForm key={f.id} f={f} onDone={done} />)}
      </div>
    </Card>
  )
}

function PromForm({ p, onDone }: { p: any; onDone: () => void }) {
  const [a, setA] = useState<Record<string, number | null>>(Object.fromEntries(p.items.map((i: any) => [i.id, null])))
  const { busy, err, run } = useAsync()
  return (
    <div className="rounded-xl border border-white/10 p-3" data-testid="prom-form">
      <b className="text-sm">{p.name}</b>
      {p.items.map((i: any) => (
        <Field key={i.id} label={i.text_cs} hint={a[i.id] == null ? "posuňte jezdec" : undefined}>
          <Slider name={i.id} min={i.min} max={i.max} value={a[i.id] ?? i.min} onChange={(v: number) => setA({ ...a, [i.id]: v })} /></Field>
      ))}
      {err && <p className="mt-2 text-xs font-bold text-alert">{err}</p>}
      <button className="btn btn-primary mt-3 w-full text-sm" disabled={busy || Object.values(a).some((v) => v == null)}
        onClick={() => run(async () => { await api.promAnswer(p.schedule_id, a); onDone() })}>Odeslat fyzioterapeutovi</button>
    </div>
  )
}

function FollowupForm({ f, onDone }: { f: any; onDone: () => void }) {
  const [normal, setNormal] = useState<boolean | null>(null)
  const [rec, setRec] = useState<boolean | null>(null)
  const [pain, setPain] = useState<number | null>(null)
  const { busy, run } = useAsync()
  const yn = (v: boolean | null, set: (x: boolean) => void) => (
    <span className="flex gap-1.5">{[[true, "ano"], [false, "ne"]].map(([x, t]) => (
      <button key={String(x)} type="button" onClick={() => set(x as boolean)} aria-pressed={v === x}
        className={`rounded-full px-3 py-1 text-[12px] font-bold ${v === x ? "bg-accent text-ink" : "border border-white/15 text-fg-2"}`}>{t as string}</button>))}</span>
  )
  return (
    <div className="rounded-xl border border-white/10 p-3" data-testid="followup-form">
      <b className="text-sm">Tři měsíce po ukončení péče: jak to jde?</b>
      <div className="mt-2 grid gap-2 text-[13px]">
        <div className="flex flex-wrap items-center justify-between gap-2">Běháte jako dřív?{yn(normal, setNormal)}</div>
        <div className="flex flex-wrap items-center justify-between gap-2">Vrátily se stejné obtíže?{yn(rec, setRec)}</div>
      </div>
      <Field label="Bolest teď (0–10)" hint={pain == null ? "posuňte jezdec" : undefined}><Slider name="fupain" min={0} max={10} value={pain ?? 0} onChange={setPain} tone="pain" /></Field>
      <button className="btn btn-primary mt-3 w-full text-sm" disabled={busy || normal == null || rec == null || pain == null}
        onClick={() => run(async () => { await api.followupAnswer(f.id, { running_normally: normal, recurrence: rec, pain }); onDone() })}>Odeslat</button>
      <p className="mt-1 text-[11.5px] text-fg-3">Odpověď pomáhá zpřesnit, jak Došlap sleduje zátěž. Vašemu fyzioterapeutovi se ukáže v dokumentaci.</p>
    </div>
  )
}
