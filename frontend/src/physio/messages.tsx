// Zprávy (physio brief 2026-11-09 W13): one inbox for all clients — unread filter, search, the last message,
// Vyřízeno; the thread opens the client's Zprávy with quick replies and attachments.
import { useState } from "react"
import { Link } from "react-router"
import { Search } from "lucide-react"
import { api } from "@/api"
import { Card, Chip } from "@/ui"
import { fmtDT } from "@/lib"
import { Empty, Loading, useLoad } from "@/physio/common"

export function MessagesPage() {
  const [q, setQ] = useState("")
  const [unread, setUnread] = useState(false)
  const { d, err, reload } = useLoad<any>(() => api.inbox(q, unread), [q, unread])
  return (
    <>
      <p className="t-label">Zprávy</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight">Zprávy od klientů</h1>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]">
          <Search className="size-4 text-fg-3" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hledat klienta" aria-label="Hledat klienta" className="min-w-0 flex-1 bg-transparent outline-none" />
        </label>
        <label className="flex items-center gap-2 text-[13px] text-fg-2"><input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} />Jen nepřečtené</label>
      </div>
      <Card className="mt-4">
        {!d ? <Loading err={err} /> : d.items.length === 0 ? <Empty>Žádné konverzace.</Empty> : (
          <ul className="divide-y divide-white/[.07]" data-testid="inbox">
            {d.items.map((c: any) => (
              <li key={c.runner_id} className="flex flex-wrap items-center gap-2 py-2.5 text-[13px]">
                <Link to={`/physio/client/${c.runner_id}?tab=chat`} className="min-w-0 flex-1">
                  <b className="text-fg">{c.name}</b>
                  <span className="block truncate text-fg-2">{c.last ? <>{c.last.sender === "runner" ? "" : c.last.sender === "physio" ? "Vy: " : "Systém: "}<span>{c.last.body}</span></> : "Zatím bez zpráv"}</span>
                </Link>
                {c.last && <span className="text-[12px] text-fg-3">{fmtDT(c.last.at)}</span>}
                {c.unread > 0 && <Chip tone="alert">{`${c.unread} nové`}</Chip>}
                {c.needs_reply && <button type="button" className="btn btn-outline btn-sm" onClick={async () => { await api.messagesHandled(c.runner_id); reload() }}>Vyřízeno</button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {d && <p className="mt-3 text-[12px] text-fg-3">{d.response_time_text ? <>{"Klientům se ukazuje: "}{`Obvykle odpovídá ${d.response_time_text}`}</> : "Dobu odpovědi a rychlé odpovědi nastavíte v Praxi."}{/* the runner card's own words; the text already starts with "do …" */}</p>}
    </>
  )
}
