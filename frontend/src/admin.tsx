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
      <GoalKpis />
    </>
  )
}

// plan k cíli 2.0 #20 — how the goal planner does against its targets (backend goal_backtest.py)
function Kpi({ label, value, target, ok }: { label: string; value: string; target: string; ok: boolean | null }) {
  return (
    <div className="rounded-xl bg-white/[.04] px-3 py-2">
      <p className="text-[11px] text-fg-3">{label}</p>
      <p className="text-[18px] font-bold tabular-nums" style={{ color: ok == null ? C.fg3 : ok ? C.ok : C.watch }}>{value}</p>
      <p className="text-[10.5px] text-fg-3">{`cíl ${target}`}</p>
    </div>
  )
}

function GoalKpis() {
  const [d, setD] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let alive = true
    api.adminGoalKpis().then((x: any) => alive && setD(x)).catch(() => {})
    return () => { alive = false }
  }, [])
  if (!d) return null
  const o = d.outcomes || {}, p = d.projection
  const pct = (v: number | null | undefined) => (v == null ? "—" : `${String(v).replace(".", ",")} %`)
  const replay = async () => { setBusy(true); try { setD(await api.adminGoalKpis(true)) } finally { setBusy(false) } }
  return (
    <Card className="mt-5" data-testid="goal-kpis">
      <Label>Plán k cíli · přesnost</Label>
      <p className="mt-1 text-[12px] text-fg-2">{`Výsledky ${o.goals ?? 0} cílů. Rezervy a prahy se mění jen podle těchto dat.`}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Kpi label="Na startu bez zranění" value={pct(o.startNoInjury)} target="≥ 90 %" ok={o.startNoInjury == null ? null : o.startNoInjury >= 90} />
        <Kpi label="Doběhne ze startujících" value={pct(o.finishOfStarters)} target="≥ 93 %" ok={o.finishOfStarters == null ? null : o.finishOfStarters >= 93} />
        <Kpi label="Chyba odhadu času" value={o.timeErrPct == null ? "—" : `± ${pct(o.timeErrPct)}`} target="± 3 %" ok={o.timeErrPct == null ? null : o.timeErrPct <= 3} />
        <Kpi label="Plnění plánu" value={pct(o.kmPct)} target="80–115 %" ok={o.kmPct == null ? null : o.kmPct >= 80 && o.kmPct <= 115} />
      </div>
      <p className="mt-3 t-label !text-fg-3">Kalibrace šance</p>
      <div className="mt-1 grid gap-1">
        {(o.calibration || []).map((b: any) => (
          <div key={b.from} className="grid grid-cols-[90px_1fr_70px] items-center gap-2 text-[12px]">
            <span className="text-fg-3">{`šance ${b.from}–${b.to} %`}</span>
            <span className="relative h-2 rounded-full bg-white/[.07]">
              {b.ready != null && <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${b.ready}%`, background: C.info }} />}
              <i className="absolute -inset-y-0.5 w-[2px] rounded" style={{ left: `${(b.from + b.to) / 2}%`, background: C.fg }} />
            </span>
            <span className="text-right tabular-nums text-fg-2">{`${pct(b.ready)} (${b.n})`}</span>
          </div>
        ))}
      </div>
      <p className="mt-1 text-[10.5px] text-fg-3">Pruh = kolik běžců dorazilo na start bez zranění, čárka = střed slíbené šance.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn btn-secondary btn-sm" disabled={busy} onClick={replay}>{busy ? "Přehrávám…" : "Přehrát projekce 8 týdnů zpět"}</button>
        {p && <span className="text-[12px] text-fg-2">{`${p.followed} z ${p.runners} běžců plán plnilo · medián chyby ${p.medianErrPct == null ? "—" : `${String(p.medianErrPct).replace(".", ",")} %`} (absolutně ${p.medianAbsErrPct == null ? "—" : `${String(p.medianAbsErrPct).replace(".", ",")} %`})`}</span>}
      </div>
    </Card>
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
