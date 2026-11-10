// Phases 3 and 4 of the physio brief (2026-11-09) on the physio's side: receipts and revenue, seats, the clinic
// report (B1, B2, B6), the waitlist (B4), questionnaires (B5), recall (M2), clinic tests (M4) and packages.
// Payments go through a mock provider: no money moves, and every screen says so.
import { useState } from "react"
import { useNavigate } from "react-router"
import { Download } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { Empty, Loading, useLoad } from "@/physio/common"

const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
const czk = (n?: number | null) => (n == null ? "—" : `${n.toLocaleString("cs-CZ")} Kč`)
const PAYER: Record<string, string> = { client: "klient", employer: "zaměstnavatel", insurer: "pojišťovna", other: "jiný" }
const INV: Record<string, string> = { issued: "nezaplaceno", paid: "zaplaceno", cancelled: "zrušeno" }
const monthStart = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).toLocaleDateString("sv-SE") }

// ---------------------------------------------------------------- B1 receipts and revenue
export function Money() {
  const toast = useToast()
  const [from, setFrom] = useState(monthStart())
  const [to, setTo] = useState(new Date().toLocaleDateString("sv-SE"))
  const inv = useLoad<any>(() => api.invoices(from, to), [from, to])
  const rev = useLoad<any>(() => api.revenue(from, to), [from, to])
  const set = async (id: number, st: "paid" | "cancelled") => {
    if (st === "cancelled" && !window.confirm("Zrušit doklad? Číslo zůstane obsazené.")) return
    try { await api.invoiceStatus(id, st); inv.reload(); rev.reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <Card>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 className="font-serif text-xl">Doklady a tržby</h2>
        <span className="flex flex-wrap items-end gap-2">
          <label className="text-[12px] font-bold text-fg-2">Od<input type="date" className={inp} value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="text-[12px] font-bold text-fg-2">Do<input type="date" className={inp} value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <a className="btn btn-outline btn-sm" href={`/api/physios/me/invoices.csv?start=${from}&end=${to}`}><Download className="size-4" aria-hidden />CSV pro účetní</a>
        </span>
      </div>
      {rev.d && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="revenue">
          {[["Vystaveno", rev.d.invoiced_czk], ["Zaplaceno", rev.d.paid_czk], ["Nezaplaceno", rev.d.outstanding_czk], ["Dokladů", rev.d.receipts]].map(([l, v]) => (
            <div key={l as string} className="rounded-lg bg-white/[.04] px-3 py-2"><p className="text-[11.5px] text-fg-3">{l}</p>
              <b className="text-[17px] tabular-nums">{l === "Dokladů" ? v : czk(v as number)}</b></div>
          ))}
        </div>
      )}
      {rev.d && Object.keys(rev.d.by_payer || {}).length > 0 && (
        <p className="mt-2 text-[12px] text-fg-2">{"Podle plátce: "}{Object.entries(rev.d.by_payer).map(([k, v], n) => <span key={k}>{n ? " · " : ""}<span>{PAYER[k] || k}</span>{` ${czk(v as number)}`}</span>)}</p>
      )}
      {!inv.d ? <Loading err={inv.err} /> : inv.d.items.length === 0 ? <Empty>V tomto období žádné doklady. Doklad vznikne, když návštěvu označíte jako proběhlou.</Empty> : (
        <table className="mt-3 w-full text-[12.5px]" data-testid="invoices">
          <thead className="text-left text-fg-3"><tr><th className="py-1">Číslo</th><th>Datum</th><th>Klient</th><th>Plátce</th><th className="text-right">Částka</th><th className="pl-3">Stav</th><th /></tr></thead>
          <tbody>
            {inv.d.items.map((i: any) => (
              <tr key={i.id} className="border-t border-white/[.07]">
                <td className="py-1.5 tabular-nums">{i.number}</td><td>{fmtD(i.issued_at)}</td><td>{i.client}</td><td>{PAYER[i.payer] || i.payer}</td>
                <td className="text-right tabular-nums">{czk(i.amount_czk)}</td>
                <td className="pl-3"><Chip tone={i.status === "paid" ? "ok" : i.status === "cancelled" ? "muted" : "watch"}>{INV[i.status] || i.status}</Chip></td>
                <td className="text-right">{i.status === "issued" && <>
                  <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => set(i.id, "paid")}>Zaplaceno</button>{" "}
                  <button type="button" className="text-[12px] font-bold text-fg-3 hover:text-alert" onClick={() => set(i.id, "cancelled")}>Zrušit</button></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[11.5px] text-fg-3">DPH není nastavené — potvrďte ho s účetní. Platby klientů jsou zatím zkušební, žádné peníze se nepřevádějí.</p>
    </Card>
  )
}

// ---------------------------------------------------------------- B2 seats
const SUB: Record<string, string> = { trial: "zkušební období", active: "zaplaceno", past_due: "po splatnosti", read_only: "jen pro čtení", cancelled: "zrušeno" }

export function Subscription() {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.subscription(), [])
  if (!d) return null
  const until = d.paid_until || d.trial_ends_at
  return (
    <Card>
      <div className="flex items-center justify-between gap-2"><h2 className="font-serif text-xl">Předplatné</h2>
        <Chip tone={d.status === "active" || d.status === "trial" ? "ok" : "alert"}>{SUB[d.status] || d.status}</Chip></div>
      <p className="mt-2 text-[13px] text-fg-2">{`${d.seats} × ${d.price_czk_per_seat} Kč = ${d.seats * d.price_czk_per_seat} Kč měsíčně`}
        {until ? ` · platí do ${new Date(until).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" })}` : ""}</p>
      {d.read_only && <p className="mt-2 rounded-lg ph-risk-high px-3 py-2 text-[12.5px]">Praxe je jen pro čtení. Dokumentace zůstává dostupná, tisk i export fungují.</p>}
      {d.can_pay ? (
        <Button className="mt-3" size="sm" onClick={async () => {
          try { const p = await api.subscriptionPay(); await api.mockPay(p.id); toast({ title: "Zaplaceno (zkušební platba)" }); reload() }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Zaplatit měsíc (zkušební platba)</Button>
      ) : <p className="mt-2 text-[12px] text-fg-3">Platí vlastník praxe.</p>}
      <p className="mt-2 text-[11.5px] text-fg-3">Recepce se do míst nepočítá. Po skončení zkušebního období a 14 dnech po splatnosti přejde praxe do režimu jen pro čtení.</p>
    </Card>
  )
}

// ---------------------------------------------------------------- B6 clinic report
export function ClinicReport() {
  const { d, err } = useLoad<any>(() => api.clinicReport(), [])
  if (err) return null
  return (
    <Card>
      <h2 className="font-serif text-xl">Přehled praxe za měsíc</h2>
      {!d ? <Loading err={null} /> : (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="clinic-report">
          {[["Obsazenost", d.occupancy_pct == null ? "—" : `${d.occupancy_pct} %`], ["Návštěvy", d.visits],
            ["Nedostavili se", d.no_show_rate == null ? "—" : `${d.no_shows} (${d.no_show_rate} %)`],
            ["Noví klienti", d.new_clients], ["Vracející se", d.returning_clients], ["Tržby", czk(d.revenue?.invoiced_czk)]].map(([l, v]) => (
            <div key={l as string} className="rounded-lg bg-white/[.04] px-3 py-2"><p className="text-[11.5px] text-fg-3">{l}</p><b className="text-[17px] tabular-nums">{v as any}</b></div>
          ))}
        </div>
      )}
      <p className="mt-2 text-[11.5px] text-fg-3">Jen počty a součty, bez klinických údajů.</p>
    </Card>
  )
}

// ---------------------------------------------------------------- B4 waitlist
export function Waitlist() {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.physioWaitlist(), [])
  if (!d) return null
  return (
    <Card>
      <h2 className="font-serif text-xl">Pořadník</h2>
      <p className="mt-1 text-[12px] text-fg-3">Klienti, kteří čekají na uvolněný termín. Nabídka platí 2 hodiny a dostane ji vždy jen jeden.</p>
      {d.items.length === 0 ? <Empty>Nikdo nečeká.</Empty> : (
        <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="waitlist">
          {d.items.map((w: any) => (
            <li key={w.id} className="grid gap-1 py-2">
              <span className="flex flex-wrap items-center gap-2"><b>{w.name}</b><span className="text-[12px] text-fg-3">{`čeká od ${fmtD(w.created_at)}`}</span>
                {w.status === "offered" && <Chip tone="info">{`nabídnuto ${fmtDT(w.offered_slot_at)}`}</Chip>}</span>
              {w.note && <span className="text-[12px] text-fg-2">{w.note}</span>}
              {w.status === "waiting" && (w.fits.length ? (
                <span className="flex flex-wrap gap-1.5">{w.fits.map((t: string) => (
                  <button key={t} type="button" className="rounded-full border border-accent/40 px-2.5 py-0.5 text-[12px] font-bold text-accent hover:bg-accent/10"
                    onClick={async () => { try { await api.waitlistOffer(w.id, t); toast({ title: "Nabídnuto, klient má 2 hodiny" }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) } }}>
                    {`Nabídnout ${fmtDT(t)}`}</button>))}</span>
              ) : <span className="text-[12px] text-fg-3">V příštích 14 dnech žádný vhodný volný čas.</span>)}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- M2 recall
export function Recall() {
  const nav = useNavigate()
  const { d } = useLoad<any>(() => api.recall(), [])
  if (!d || d.items.length === 0) return null
  return (
    <Card>
      <h2 className="font-serif text-xl">Bývalí klienti s novým signálem</h2>
      <p className="mt-1 text-[12px] text-fg-3">Propuštění klienti, kteří vám dál sdílí data a mají vysoké riziko nebo novou bolest.</p>
      <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="recall">
        {d.items.map((x: any) => (
          <li key={x.runner_id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1"><b>{x.name}</b><span className="block text-[12px] text-fg-3">{`propuštěn(a) ${fmtD(x.discharged_on)}${x.diagnosis ? ` · ${x.diagnosis}` : ""}${x.pain_checkins ? ` · bolest 3+ ve ${x.pain_checkins} check-inech` : ""}`}</span></span>
            {x.tier === "alert" && <Chip tone="alert">vysoké riziko</Chip>}
            <Button size="sm" variant="outline" onClick={() => nav(`/physio/client/${x.runner_id}?tab=chat`)}>Napsat</Button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---------------------------------------------------------------- B1.4 packages (client documentation tab)
export function Packages({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.packages(rid), [rid])
  const [f, setF] = useState({ name: "", visits_total: 5, price_czk: 4500, paid: true })
  return (
    <Card>
      <h2 className="font-serif text-xl">Balíčky návštěv</h2>
      {(d?.items || []).length > 0 && (
        <ul className="mt-2 grid gap-1 text-[13px]">{d.items.map((p: any) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2"><b>{p.name}</b><span className="text-fg-2">{`zbývá ${p.visits_total - p.visits_used} z ${p.visits_total} · ${czk(p.price_czk)}`}</span>
            <Chip tone={p.status === "open" ? "ok" : "muted"}>{p.status === "open" ? "aktivní" : "vyčerpáno"}</Chip></li>))}</ul>
      )}
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
        <label className="text-[12px] font-bold text-fg-2">Název<input className={inp} value={f.name} placeholder="např. 5 kontrol" onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="w-20 text-[12px] font-bold text-fg-2">Návštěv<input type="number" min={2} max={50} className={inp} value={f.visits_total} onChange={(e) => setF({ ...f, visits_total: Number(e.target.value) })} /></label>
        <label className="w-24 text-[12px] font-bold text-fg-2">Cena Kč<input type="number" min={0} className={inp} value={f.price_czk} onChange={(e) => setF({ ...f, price_czk: Number(e.target.value) })} /></label>
        <Button size="sm" className="self-end" disabled={!f.name.trim()} onClick={async () => { try { await api.packageAdd(rid, f); toast({ title: "Balíček přidán" }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) } }}>Přidat</Button>
      </div>
      <p className="mt-1 text-[11.5px] text-fg-3">Každá proběhlá návštěva u vás odečte jednu; doklad k ní bude na 0 Kč s odkazem na balíček.</p>
    </Card>
  )
}

// ---------------------------------------------------------------- B5 questionnaires (client plan tab)
export function Proms({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.clientProms(rid), [rid])
  const cat = useLoad<any>(() => api.promInstruments(), [])
  const [every, setEvery] = useState(14)
  const ins = cat.d?.items?.[0]
  const resp: any[] = d?.responses || []
  return (
    <Card>
      <h2 className="font-serif text-xl">Dotazníky</h2>
      <p className="mt-1 text-[12px] text-fg-3">{cat.d?.note}</p>
      {(d?.schedules || []).map((s: any) => (
        <p key={s.id} className="mt-2 flex flex-wrap items-center gap-2 text-[13px]"><b>{cat.d?.items?.find((i: any) => i.key === s.instrument)?.name || s.instrument}</b>
          <span className="text-fg-2">{`každých ${s.every_days} dní · další ${fmtD(s.next_due)}`}</span>
          <button type="button" className="text-[12px] font-bold text-fg-3 hover:text-alert" onClick={async () => { await api.promStop(s.id); reload() }}>Ukončit</button></p>
      ))}
      {ins && !(d?.schedules || []).length && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="text-[12px] font-bold text-fg-2">Interval<select className={inp} value={every} onChange={(e) => setEvery(Number(e.target.value))}>
            {[7, 14, 28].map((n) => <option key={n} value={n}>{`každých ${n} dní`}</option>)}</select></label>
          <Button size="sm" onClick={async () => { try { await api.promAdd(rid, ins.key, every); toast({ title: "Dotazník naplánován" }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) } }}>{`Posílat: ${ins.name}`}</Button>
        </div>
      )}
      {resp.length > 0 && (
        <div className="mt-3">
          <p className="text-[12px] text-fg-3">Skóre 0–100, vyšší = lépe</p>
          <div className="mt-1 flex items-end gap-1.5" role="img" aria-label="Skóre dotazníku v čase">
            {resp.slice(-12).map((r: any) => (
              <div key={r.id} className="flex flex-1 flex-col items-center gap-1" title={`${fmtD(r.answered_at)}: ${r.score}`}>
                <span className="text-[10.5px] tabular-nums text-fg-2">{r.score}</span>
                <span className="w-full max-w-8 rounded-t-[4px] bg-[#2F5F7A]" style={{ height: `${Math.max(3, r.score * 0.6)}px` }} />
                <span className="text-[10px] text-fg-3">{fmtD(r.answered_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- M4 clinic tests (client plan tab)
export function ClinicTests({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.clinicTests(rid), [rid])
  const cat = useLoad<any>(() => api.clinicTestCatalog(), [])
  const [f, setF] = useState<any>({ test: "heel_raise_sl", left: "", right: "", involved: "" })
  const items: any[] = d?.items || []
  return (
    <Card>
      <h2 className="font-serif text-xl">Testy v ordinaci</h2>
      <p className="mt-1 text-[12px] text-fg-3">Index symetrie (LSI) = postižená strana / zdravá × 100. Poslední hodnoty se nabídnou u připravenosti k návratu k běhu.</p>
      {items.length > 0 && (
        <table className="mt-2 w-full text-[12.5px]" data-testid="clinic-tests">
          <thead className="text-left text-fg-3"><tr><th className="py-1">Datum</th><th>Test</th><th>L</th><th>P</th><th>LSI</th></tr></thead>
          <tbody>{[...items].reverse().map((t: any) => (
            <tr key={t.id} className="border-t border-white/[.07]"><td className="py-1">{fmtD(t.tested_on)}</td><td>{t.name}</td>
              <td className="tabular-nums">{t.left ?? "—"}</td><td className="tabular-nums">{t.right ?? "—"}</td>
              <td className="tabular-nums">{t.lsi == null ? "—" : <Chip tone={t.lsi >= 90 ? "ok" : t.lsi >= 80 ? "watch" : "alert"}>{`${t.lsi} %`}</Chip>}</td></tr>))}</tbody>
        </table>
      )}
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto_auto]">
        <label className="text-[12px] font-bold text-fg-2">Test<select className={inp} value={f.test} onChange={(e) => setF({ ...f, test: e.target.value })}>
          {(cat.d?.items || []).map((t: any) => <option key={t.key} value={t.key}>{`${t.name_cs} (${t.unit})`}</option>)}</select></label>
        <label className="w-20 text-[12px] font-bold text-fg-2">Levá<input type="number" min={0} className={inp} value={f.left} onChange={(e) => setF({ ...f, left: e.target.value })} /></label>
        <label className="w-20 text-[12px] font-bold text-fg-2">Pravá<input type="number" min={0} className={inp} value={f.right} onChange={(e) => setF({ ...f, right: e.target.value })} /></label>
        <label className="text-[12px] font-bold text-fg-2">Postižená<select className={inp} value={f.involved} onChange={(e) => setF({ ...f, involved: e.target.value })}>
          <option value="">—</option><option value="L">levá</option><option value="R">pravá</option></select></label>
        <Button size="sm" className="self-end" disabled={f.left === "" && f.right === ""} onClick={async () => {
          try {
            await api.clinicTestAdd(rid, { test: f.test, left: f.left === "" ? null : Number(f.left), right: f.right === "" ? null : Number(f.right), involved: f.involved || null })
            setF({ ...f, left: "", right: "" }); reload()
          } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Zapsat</Button>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- M3 video notes (chat)
export function VideoNotes({ m, physio, videoId }: { m: any; physio: boolean; videoId: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any>(() => api.videoNotes(m.id), [m.id])
  const [text, setText] = useState("")
  const seek = (t: number) => { const v = document.getElementById(videoId) as HTMLVideoElement | null; if (v) { v.currentTime = t; void v.play() } }
  const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`
  return (
    <div className="mt-1 grid gap-1 text-[12px]">
      {(d?.items || []).map((n: any) => (
        <button key={n.id} type="button" onClick={() => seek(n.t_seconds)} className="text-left hover:underline"><b className="tabular-nums">{mmss(n.t_seconds)}</b>{` ${n.text}`}</button>
      ))}
      {physio && (
        <form className="flex gap-1" onSubmit={async (e) => {
          e.preventDefault()
          const v = document.getElementById(videoId) as HTMLVideoElement | null
          try { await api.videoNoteAdd(m.id, v?.currentTime || 0, text); setText(""); reload() } catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
        }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Poznámka k aktuálnímu času videa" aria-label="Poznámka k videu"
            className="min-w-0 flex-1 rounded-md border border-white/15 bg-panel px-2 py-1" />
          <Button size="sm" type="submit" disabled={!text.trim()}>Přidat</Button>
        </form>
      )}
    </div>
  )
}
