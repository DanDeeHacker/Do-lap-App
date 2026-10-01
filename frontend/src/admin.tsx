// Admin view for the app's owners (backend routers/admin.py): every registered runner,
// and "Zobrazit jako" — the whole app (all tabs but Profil and Data a připojení) with
// that runner's data, read-only. The server lets an owner read any runner but write
// only their own, and logs each view in the runner's "Kdo přistupoval k vašim datům".
import { useEffect, useMemo, useState } from "react"
import { Navigate, useNavigate } from "react-router"
import { Eye, Search, ShieldCheck, Users, X } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, Chip, Label } from "@/ui"
import { fmtD, QUAD } from "@/lib"
import { C } from "@/tokens"

type AdminRunner = {
  runnerId: string; name: string; email: string; joined?: string; demo: boolean; self: boolean
  engineMode?: string; activities: number; lastActivity?: string; lastCheckin?: string
  quadrant?: string; tier?: string; overall?: number
}
const TIER_TONE: Record<string, "ok" | "watch" | "alert"> = { ok: "ok", watch: "watch", alert: "alert" }

function useAdminRunners(enabled: boolean) {
  const [items, setItems] = useState<AdminRunner[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    api.adminRunners().then((d: any) => alive && setItems(d.items || [])).catch((e: any) => alive && setErr(e?.message || "Seznam se nepodařilo načíst"))
    return () => { alive = false }
  }, [enabled])
  return { items, err }
}

export function AdminPage() {
  const { realMe, viewing, startViewAs, endViewAs } = useApp()
  const nav = useNavigate()
  const owner = !!realMe?.owner
  const { items, err } = useAdminRunners(owner)
  const [q, setQ] = useState("")
  const [showDemo, setShowDemo] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const list = useMemo(() => {
    const t = q.trim().toLowerCase()
    return (items || []).filter((x) => (showDemo || !x.demo || x.self) && (!t || `${x.name} ${x.email}`.toLowerCase().includes(t)))
  }, [items, q, showDemo])
  if (!owner) return <Navigate to="/app/today" replace />
  const open = async (x: AdminRunner) => {
    if (x.self) { endViewAs(); nav("/app/today"); return }
    setBusy(x.runnerId)
    const ok = await startViewAs(x.runnerId, x.name)
    setBusy(null)
    if (ok) nav("/app/today")
  }
  const demoCount = (items || []).filter((x) => x.demo).length
  return (
    <>
      <div>
        <Label>Správa uživatelů</Label>
        <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Registrovaní běžci</h1>
        <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">
          Zobrazit jako otevře celou aplikaci s daty vybraného běžce, kromě Profilu a Dat a připojení. Je to jen pro čtení
          a běžec uvidí každé zobrazení v přehledu Kdo přistupoval k vašim datům.
        </p>
      </div>
      {viewing && (
        <Card className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <span className="text-[13px] text-fg-2">Právě zobrazujete jako <b className="text-fg">{viewing.name}</b></span>
          <button onClick={() => { endViewAs(); nav("/app/today") }} className="btn btn-secondary btn-sm">Ukončit zobrazení</button>
        </Card>
      )}
      <Card className="mt-5">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-[14px] border border-white/12 bg-white/[.04] px-3">
            <Search className="size-4 shrink-0 text-fg-3" aria-hidden />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hledat jméno nebo e-mail" aria-label="Hledat běžce"
              className="h-11 w-full bg-transparent text-[14px] text-fg outline-none" />
          </label>
          {demoCount > 0 && (
            <label className="flex items-center gap-2 text-[12px] font-semibold text-fg-2">
              <input type="checkbox" checked={showDemo} onChange={(e) => setShowDemo(e.target.checked)} /> ukázkové účty ({demoCount})
            </label>
          )}
        </div>
        {err ? <p className="mt-4 text-sm text-alert">{err}</p>
          : items === null ? <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám uživatele…</p>
          : list.length === 0 ? <p className="mt-4 text-sm text-fg-2">Nikdo neodpovídá hledání.</p>
          : (
            <ul className="mt-3 divide-y divide-white/[.07]" data-testid="admin-runners">
              {list.map((x) => {
                const q = x.quadrant ? QUAD[x.quadrant] : null
                const active = viewing?.rid === x.runnerId
                return (
                  <li key={x.runnerId} className="flex flex-wrap items-center gap-3 py-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-white/[.07] text-[12px] font-extrabold text-fg-2">
                      {(x.name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
                    </span>
                    <span className="min-w-0 flex-1">
                      <b className="flex flex-wrap items-center gap-2 text-[14px] text-fg">{x.name}{x.self && <Chip tone="info">vy</Chip>}{x.demo && <Chip>ukázka</Chip>}</b>
                      <span className="block truncate text-[12px] text-fg-3">{x.email}</span>
                      <span className="mt-0.5 block text-[11px] text-fg-3">
                        registrace {fmtD(x.joined) || "—"} · {x.activities} aktivit · poslední {x.lastActivity ? fmtD(x.lastActivity) : "—"}
                        {x.lastCheckin ? ` · check-in ${fmtD(x.lastCheckin)}` : ""}
                      </span>
                    </span>
                    {q && <Chip tone={TIER_TONE[x.tier || ""] || "muted"}>{q.t}</Chip>}
                    <button onClick={() => open(x)} disabled={busy === x.runnerId} data-testid="admin-view"
                      className={`btn btn-sm gap-1.5 ${active ? "btn-secondary" : "btn-primary"}`}>
                      <Eye className="size-4" aria-hidden />{busy === x.runnerId ? "Načítám…" : active ? "Zobrazeno" : x.self ? "Můj účet" : "Zobrazit jako"}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
      </Card>
    </>
  )
}

// The bar on top of every page while the owner looks at someone else's data: whose,
// that it is read-only, a quick switch to another runner and the way back.
export function ViewAsBanner() {
  const { realMe, viewing, startViewAs, endViewAs } = useApp()
  const nav = useNavigate()
  const { items } = useAdminRunners(!!viewing && !!realMe?.owner)
  const [switching, setSwitching] = useState(false)
  if (!viewing) return null
  const others = (items || []).filter((x) => !x.self)
  return (
    <div className="mb-5 flex flex-wrap items-center gap-2.5 rounded-[16px] border px-3.5 py-2.5 text-[13px]"
      style={{ borderColor: `${C.watch}66`, background: `${C.watch}14` }} data-testid="view-as-banner" role="status">
      <ShieldCheck className="size-4 shrink-0" style={{ color: C.watch }} aria-hidden />
      <span className="min-w-0 flex-1 text-fg">Zobrazujete jako <b>{viewing.name}</b><span className="text-fg-2"> · jen pro čtení</span></span>
      {others.length > 1 && (
        <select aria-label="Přepnout na jiného běžce" value={viewing.rid} disabled={switching}
          onChange={async (e) => {
            const x = others.find((o) => o.runnerId === e.target.value)
            if (!x) return
            setSwitching(true)
            await startViewAs(x.runnerId, x.name)
            setSwitching(false)
          }}
          className="h-9 max-w-[200px] rounded-full border border-white/15 bg-raised px-3 text-[12px] font-semibold text-fg">
          {others.map((x) => <option key={x.runnerId} value={x.runnerId}>{x.name}{x.demo ? " (ukázka)" : ""}</option>)}
        </select>
      )}
      <button onClick={() => nav("/admin")} className="inline-flex h-9 items-center gap-1.5 rounded-full border border-white/15 px-3 text-[12px] font-bold text-fg-soft hover:border-white/30">
        <Users className="size-4" aria-hidden />Uživatelé
      </button>
      <button onClick={() => { endViewAs(); nav("/app/today") }} aria-label="Ukončit zobrazení" data-testid="view-as-exit"
        className="inline-flex h-9 items-center gap-1.5 rounded-full bg-fg px-3 text-[12px] font-bold text-ink hover:opacity-90">
        <X className="size-4" aria-hidden />Ukončit
      </button>
    </div>
  )
}
