// Dnes (physio brief 2026-11-09 W3): one screen that answers who do I see, who needs me and what is
// unfinished. Left: today's visits with preparation and the record; right: alerts, requests, unread
// messages and unsigned records.
import { Link } from "react-router"
import { AlertTriangle, Bell, CheckCircle2, Clock, FileText, MessageCircle, NotebookPen } from "lucide-react"
import { api } from "@/api"
import { Recall } from "@/physio/business"
import { Button, Card, Chip, useToast } from "@/ui"
import { fmtDT } from "@/lib"
import { Empty, KIND, Loading, RequestItem, useLoad } from "@/physio/common"

const SEV: Record<string, string> = { high: "ph-risk-high", medium: "ph-risk-med", low: "ph-unknown" }
const SEV_CS: Record<string, string> = { high: "vysoká", medium: "střední", low: "nízká" }
const time = (iso: string) => new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })

export function TodayPage() {
  const toast = useToast()
  const { d, err, reload } = useLoad<any>(() => api.today(), [])
  if (!d) return <Loading err={err} />
  const act = async (id: number, a: "snooze" | "resolve") => {
    try { await api.alertAction(id, a); toast({ title: a === "snooze" ? "Odloženo na 24 hodin" : "Označeno jako vyřešené" }); reload() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  const dateLabel = new Date().toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
  return (
    <>
      <p className="t-label">Dnes</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight">{dateLabel}</h1>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.3fr_1fr]" data-testid="today">
        <Card>
          <h2 className="flex items-center gap-2 font-serif text-xl"><Clock className="size-4" aria-hidden />Návštěvy dnes</h2>
          {d.visits.length === 0 ? <Empty>Dnes žádná návštěva.</Empty> : (
            <ol className="mt-2 divide-y divide-white/[.07]">
              {d.visits.map((v: any) => (
                <li key={v.id} className="flex flex-wrap items-center gap-2 py-2.5 text-[14px]" data-testid="today-visit">
                  <b className="w-12 tabular-nums">{time(v.slot_at)}</b>
                  <Link to={`/physio/client/${v.runner_id}`} className="min-w-0 flex-1 font-bold text-fg hover:underline">{v.name}
                    <span className="block text-[12px] font-normal text-fg-3">{v.service || KIND[v.kind] || v.kind}{v.reason ? ` · ${v.reason}` : ""}</span></Link>
                  {v.status === "no_show" ? <Chip>nedostavil(a) se</Chip> : v.record === "approved" ? <Chip tone="ok">záznam schválen</Chip>
                    : v.record ? <Chip tone="watch">rozepsaný záznam</Chip> : null}
                  {!v.prep && <Chip>bez pokynů k přípravě</Chip>}
                  <Link to={`/physio/client/${v.runner_id}/priprava/${v.id}`} className="btn btn-outline btn-sm">Příprava</Link>
                  <Link to={`/physio/client/${v.runner_id}/visit/${v.id}`} className="btn btn-outline btn-sm"><FileText className="size-3.5" aria-hidden />Záznam</Link>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <h2 className="flex items-center gap-2 font-serif text-xl"><Bell className="size-4" aria-hidden />Kdo mě potřebuje</h2>
            {d.alerts.length === 0 ? <Empty>Žádné upozornění.</Empty> : (
              <ul className="mt-2 grid gap-2" data-testid="alerts">
                {d.alerts.map((a: any) => (
                  <li key={a.id} className="rounded-lg border border-white/[.08] p-2.5 text-[13px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-bold ${SEV[a.severity]}`}>{SEV_CS[a.severity]}</span>
                      <b className="text-fg">{a.title}</b>
                      <span className="text-fg-2">{a.name}</span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {a.runner_id && <Link to={`/physio/client/${a.runner_id}`} className="btn btn-outline btn-sm">Otevřít</Link>}
                      <Button size="sm" variant="outline" onClick={() => act(a.id, "snooze")}>Odložit</Button>
                      <Button size="sm" variant="outline" icon={CheckCircle2} onClick={() => act(a.id, "resolve")}>Vyřešeno</Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <h2 className="flex items-center gap-2 font-serif text-xl"><NotebookPen className="size-4" aria-hidden />Nepodepsané záznamy</h2>
            {d.unsigned.length === 0 ? <Empty>Vše podepsané.</Empty> : (
              <ul className="mt-2 grid gap-1 text-[13px]" data-testid="unsigned">
                {d.unsigned.map((u: any) => (
                  <li key={u.booking_id} className="flex items-center gap-2">
                    <Link to={`/physio/client/${u.runner_id}/visit/${u.booking_id}`} className="min-w-0 flex-1 truncate font-bold text-fg hover:underline">{u.name}</Link>
                    <span className="text-fg-3">{fmtDT(u.slot_at)}</span>
                    {u.overdue && <AlertTriangle className="size-4 text-alert" aria-label="po termínu" />}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <h2 className="flex items-center gap-2 font-serif text-xl"><MessageCircle className="size-4" aria-hidden />Nepřečtené zprávy</h2>
            {d.unread.length === 0 ? <Empty>Nic nového.</Empty> : (
              <ul className="mt-2 grid gap-1.5 text-[13px]">
                {d.unread.slice(0, 6).map((m: any, i: number) => (
                  <li key={i}><Link to={`/physio/client/${m.runner_id}?tab=chat`} className="font-bold text-fg hover:underline">{m.name}</Link>
                    <span className="block truncate text-fg-2">{m.preview}</span></li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <h2 className="font-serif text-xl">Žádosti a nové případy</h2>
            <p className="mt-2 text-[13px] text-fg-2">
              {d.requests.length ? null : "Žádné žádosti o termín."}
              {" · "}
              <Link to="/physio/queue" className="font-bold text-accent hover:underline">{`Nové případy ve frontě: ${d.new_cases}`}</Link>
            </p>
            {d.requests.length > 0 && <ul className="mt-1 divide-y divide-white/[.07]">{d.requests.map((b: any) => <RequestItem key={b.id} b={b} onDone={reload} />)}</ul>}
          </Card>
          <Recall />
        </div>
      </div>
    </>
  )
}
