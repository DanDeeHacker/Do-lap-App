// Fronta případů (report v6 Section 6.2.8, Figure A8): runners who became clients and gave their
// consent, by region and urgency. Summary tiles count the unclaimed and the low / medium / high-risk
// cases; the table shows each runner's score, quadrant, strongest signal, reported pain and the
// case's status. Claiming a case opens the runner's data to the physio (triage.claim).
import { useMemo, useState } from "react"
import { useNavigate } from "react-router"
import { Inbox, MapPin } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, useToast } from "@/ui"
import { fmtD } from "@/lib"
import { Empty, Loading, QuadChip, RiskChip, shownScore, useLoad } from "@/physio/common"

export function QueuePage({ pid }: { pid: string }) {
  const toast = useToast()
  const nav = useNavigate()
  const [scope, setScope] = useState<"clinic" | "all">("clinic")
  const [risk, setRisk] = useState<"all" | "alert" | "watch" | "ok" | "open">("all")
  const { d, err, reload } = useLoad<any[]>(() => api.triageQueue(scope), [scope])
  const [busy, setBusy] = useState<number | null>(null)
  const items = d || []
  const counts = useMemo(() => ({
    open: items.filter((t) => !t.claimed_by).length,
    ok: items.filter((t) => t.a?.tier === "ok").length,
    watch: items.filter((t) => t.a?.tier === "watch").length,
    alert: items.filter((t) => t.a?.tier === "alert").length,
  }), [items])
  const list = items.filter((t) => risk === "all" || (risk === "open" ? !t.claimed_by : t.a?.tier === risk))
  const claim = async (t: any) => {
    setBusy(t.id)
    try {
      await api.triageClaim(t.id)
      toast({ title: `${t.runner?.name || "Případ"} je ve vaší péči — data jsou otevřená` })
      nav(`/physio/client/${t.runner_id}`)
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }); reload() }
    finally { setBusy(null) }
  }
  const tile = (k: typeof risk, label: string, n: number, tone: string) => (
    <button type="button" onClick={() => setRisk(risk === k ? "all" : k)} aria-pressed={risk === k}
      className={`rounded-2xl border px-4 py-3 text-left transition ${risk === k ? "border-accent/60 bg-accent/[.08]" : "border-white/[.07] bg-white/[.03] hover:bg-white/[.06]"}`}>
      <p className="text-[12px] font-bold text-fg-2">{label}</p>
      <p className="mt-1 text-[26px] font-bold tabular-nums" style={{ color: tone }}>{n}</p>
    </button>
  )
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="t-label">Fronta případů</p>
          <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Kdo potřebuje péči</h1>
          <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">
            Běžci, kteří požádali o fyzioterapeuta a souhlasili se sdílením dat. Seřazeno podle naléhavosti; převzetím případu
            se vám otevře jeho přehled.
          </p>
        </div>
        <Segmented size="sm" value={scope} onChange={setScope} ariaLabel="Oblast"
          options={[["clinic", "Můj region"], ["all", "Všechny regiony"]] as const} />
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="queue-tiles">
        {tile("open", "Nepřevzaté", counts.open, "var(--color-fg)")}
        {tile("ok", "Nízké riziko", counts.ok, "var(--color-ok)")}
        {tile("watch", "Střední riziko", counts.watch, "var(--color-watch)")}
        {tile("alert", "Vysoké riziko", counts.alert, "var(--color-alert)")}
      </div>
      <Card className="mt-4">
        {!d ? <Loading err={err} /> : list.length === 0 ? <Empty>Ve frontě teď nikdo není.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-[13px]" data-testid="queue">
              <thead className="text-left text-[11.5px] text-fg-3">
                <tr>
                  <th className="py-2 pr-3 font-semibold">Běžec</th><th className="py-2 pr-3 font-semibold">Skóre</th>
                  <th className="py-2 pr-3 font-semibold">Stav</th><th className="py-2 pr-3 font-semibold">Nejsilnější signál</th>
                  <th className="py-2 pr-3 font-semibold">Bolest</th><th className="py-2 pr-3 font-semibold">Případ</th><th />
                </tr>
              </thead>
              <tbody>
                {list.map((t: any) => {
                  const sig = [...(t.a?.signals || [])].sort((x: any, y: any) => (y.pts || 0) - (x.pts || 0))[0]
                  const ps = t.a?.painState || {}
                  const mine = t.claimed_by === pid
                  return (
                    <tr key={t.id} className="border-t border-white/[.06] align-top">
                      <td className="py-2.5 pr-3">
                        <b className="block text-fg">{t.runner?.name || t.runner_id}</b>
                        <span className="flex items-center gap-1 text-[11.5px] text-fg-3"><MapPin className="size-3" aria-hidden />{t.runner?.city || "—"}
                          {!t.in_region && <span>{" · mimo region"}</span>}</span>
                      </td>
                      <td className="py-2.5 pr-3 text-[18px] font-bold tabular-nums text-fg">{t.a?.overall == null ? "—" : Math.round(shownScore(t.a.overall)!)}</td>
                      <td className="py-2.5 pr-3"><span className="flex flex-wrap gap-1"><RiskChip tier={t.a?.tier} /><QuadChip q={t.a?.quadrant} /></span></td>
                      <td className="py-2.5 pr-3 text-fg-2">{sig ? <>{sig.name}<span className="block text-[11.5px] text-fg-3">{sig.val}</span></> : "—"}</td>
                      <td className="py-2.5 pr-3 text-fg-2">
                        {ps.todayPain != null ? <span className="font-bold text-watch">{`${ps.todayPain}/10`}</span>
                          : ps.lastPainDay ? <span>{`naposledy ${fmtD(ps.lastPainDay)}`}</span> : "—"}
                        {ps.todaySites?.length ? <span className="block text-[11.5px] text-fg-3">{ps.todaySites.join(", ")}</span> : null}
                      </td>
                      <td className="py-2.5 pr-3">
                        {mine ? <Chip tone="ok">ve vaší péči</Chip> : t.claimed_by ? <Chip>převzal jiný</Chip> : <Chip tone="info">volný</Chip>}
                        {t.headline && <span className="mt-1 block max-w-[220px] text-[11.5px] text-fg-3">{t.headline}</span>}
                      </td>
                      <td className="py-2.5 text-right">
                        {mine ? <Button size="sm" variant="outline" onClick={() => nav(`/physio/client/${t.runner_id}`)}>Otevřít</Button>
                          : !t.claimed_by && <Button size="sm" icon={Inbox} busy={busy === t.id} onClick={() => claim(t)} data-testid="queue-claim">Převzít</Button>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
