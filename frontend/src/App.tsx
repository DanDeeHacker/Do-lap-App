import { lazy, Suspense, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  createBrowserRouter,
  Link,
  Navigate,
  Outlet,
  RouterProvider,
  useLocation,
  useNavigate,
  useParams,
} from "react-router"
import MuscleAnatomy, { PainHeatmap, painKey, type BodyPoint } from "@/components/MuscleAnatomy"
import { api, ApiError } from "@/api"
import { AppProvider, useApp } from "@/store"
import { clamp, fmtD, initials, QUAD, roleHome } from "@/lib"
import { AlertBanner, AxisLineChart, Bars, Button, Chip, FactorBar, Field, InfoDot, Sheet, ToastHost, toneCol, useAsync, useToast } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { Load as LoadTab, LOAD_IDS, MECH_IDS, Mechanics, Post, weekTones, WeekToneLegend } from "@/tabs"
import { Care, InjurySheet, WeeklyCheckButton } from "@/care"
import { DataView } from "@/datapage"
import { EngineLab } from "@/enginelab"
import { EngineCompare } from "@/enginecompare"
import { CapacityMini, Readiness, readinessCol, readinessPct } from "@/capacity"
import { Training } from "@/training"
import { RunDetail } from "@/rundetail"
import { startUpdateWatcher } from "@/updateCheck"
import { AnnotateProvider, AnnotateToggle, AnnotationLayer } from "@/annotate"
import { C } from "@/tokens"
import { Bandage, ChevronDown, ChevronLeft, ChevronRight, Database, Flag, Heart, HeartPulse, LogOut, Maximize2, Moon, RefreshCw, SlidersHorizontal, Timer, TrendingUp, TriangleAlert, UserPen, X, Zap, type LucideIcon } from "lucide-react"
import { Mark, NAV_ICON, Sidebar, StatRail } from "@/shell"

// Only runners sign in here. Fyzioterapeuti dostanou vlastní rozhraní pro
// svou infrastrukturu; zaměstnavatelé a partneři se v této aplikaci nepřihlašují.

function useDynamicReveal() {
  useEffect(() => {
    let timer: number | undefined
    const revealLatest = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        const panels =
          document.querySelectorAll<HTMLElement>("[data-auto-reveal]")
        panels
          .item(panels.length - 1)
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" })
      }, 100)
    }
    // Only react when an actual reveal target is inserted — not on every DOM
    // mutation. A blanket observer fired on toasts, tooltip portals, chart hover
    // state and sheet toggles, hijacking the user's scroll and churning on hover.
    const isRevealTarget = (node: Node) =>
      node instanceof HTMLElement &&
      (node.matches("[data-auto-reveal]") || !!node.querySelector("[data-auto-reveal]"))
    const observer = new MutationObserver((records) => {
      for (const rec of records) {
        for (const node of rec.addedNodes) {
          if (isRevealTarget(node)) {
            revealLatest()
            return
          }
        }
      }
    })
    observer.observe(document.body, { childList: true, subtree: true })
    return () => {
      window.clearTimeout(timer)
      observer.disconnect()
    }
  }, [])
}

function Topbar() {
  const [profileOpen, setProfileOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const { me, boot, logout } = useApp()
  const nav = useNavigate()
  const { pathname } = useLocation()
  const runner = boot?.runner
  const ini = initials(me?.name)
  const navItems = useRunnerNav()
  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-white/[.07] bg-bg/[.92] pt-[env(safe-area-inset-top)] backdrop-blur-md lg:left-[220px]">
      <div className="mx-auto flex h-[68px] max-w-[1180px] items-center justify-between gap-4 px-5 lg:max-w-none lg:px-9">
        <Link to="/app/today" className="flex shrink-0 items-center gap-2.5 text-lg font-extrabold tracking-[-.04em] lg:hidden">
          <Mark />
          <span className="hidden sm:inline">došlap</span>
        </Link>
        <nav className="hidden flex-1 items-center justify-center gap-1 md:flex lg:hidden" aria-label="Hlavní navigace">
          {navItems.map(([id, label]) => {
            const to = `/app/${id}`
            const active = pathname === to || pathname.startsWith(to + "/")
            return (
              <Link
                key={id}
                to={to}
                aria-current={active ? "page" : undefined}
                className={`rounded-full px-3.5 py-1.5 text-[13px] font-bold transition ${
                  active ? "bg-accent text-ink" : "text-fg-2 hover:bg-white/[.06] hover:text-fg"
                }`}
              >
                {label}
              </Link>
            )
          })}
        </nav>
        <p className="hidden text-[15px] font-extrabold tracking-[-.02em] text-fg lg:block">{navItems.find(([id]) => pathname === `/app/${id}` || pathname.startsWith(`/app/${id}/`))?.[1] ?? (pathname === "/data" ? "Data a připojení" : pathname === "/engines" ? "Porovnání enginů" : pathname.startsWith("/engine") ? "Citlivostní analýza" : "")}</p>
        <div className="relative flex shrink-0 items-center gap-2">
          <AnnotateToggle />
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="grid size-9 place-items-center rounded-full bg-accent text-[11px] font-extrabold text-ink"
            aria-expanded={profileOpen}
            aria-label="Otevřít profil"
          >
            {ini}
          </button>
          {profileOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setProfileOpen(false)} />
              <div className="absolute right-0 top-12 z-20 w-72 origin-top animate-[careReveal_.28s_ease-out] rounded-[20px] border border-white/10 bg-raised p-4 text-fg shadow-[0_24px_60px_rgb(0_0_0_/_0.5)]">
                <div className="flex items-center gap-3">
                  <span className="grid size-10 place-items-center rounded-full bg-accent text-xs font-bold text-ink">{ini}</span>
                  <div>
                    <b>{me?.name}</b>
                    <p className="text-[11px] text-fg-2">běžecký profil</p>
                  </div>
                </div>
                <div className="mt-4 border-t border-white/10 pt-3 text-xs text-fg-2">
                  <p>{boot?.integration?.status === "connected" ? "Zdroj dat připojen" : "Data zatím nepřipojena"}</p>
                  {runner?.goal_race && <p className="mt-1">Cíl: {runner.goal_race}</p>}
                </div>
                <div className="mt-3 grid gap-1.5">
                  <button onClick={() => { setProfileOpen(false); setEditOpen(true) }} className="flex items-center gap-2.5 rounded-xl bg-white/[.05] px-3 py-2.5 text-left text-[13px] font-bold hover:bg-white/[.09]"><UserPen className="size-4 text-fg-2" aria-hidden />Upravit profil</button>
                  <Link to="/data" onClick={() => setProfileOpen(false)} className="flex items-center gap-2.5 rounded-xl bg-white/[.05] px-3 py-2.5 text-left text-[13px] font-bold hover:bg-white/[.09]"><Database className="size-4 text-fg-2" aria-hidden />Data a připojení</Link>
                  <Link to="/engine" onClick={() => setProfileOpen(false)} className="flex items-center gap-2.5 rounded-xl bg-white/[.05] px-3 py-2.5 text-left text-[13px] font-bold hover:bg-white/[.09]"><SlidersHorizontal className="size-4 text-fg-2" aria-hidden />Citlivostní analýza</Link>
                </div>
                <button
                  onClick={async () => { setProfileOpen(false); await logout(); nav("/auth") }}
                  className="btn btn-primary mt-3 w-full"
                >
                  <LogOut className="size-4" aria-hidden />Odhlásit se
                </button>
              </div>
            </>
          )}
        </div>
      </div>
      <ProfileSheet open={editOpen} onClose={() => setEditOpen(false)} />
    </header>
  )
}

function ProfileSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me, boot, refresh } = useApp()
  const r = boot?.runner
  const [f, setF] = useState<Record<string, any>>({})
  const { busy, err, run } = useAsync()
  useEffect(() => {
    if (open && r)
      setF({
        birth_year: r.birth_year ?? "", sex: r.sex ?? "", city: r.city ?? "", device: r.device ?? "",
        goal_race: r.goal_race ?? "", goal_date: (r.goal_date ?? "").slice(0, 10),
        prior_injury: r.prior_injury ?? "", prior_injury_date: (r.prior_injury_date ?? "").slice(0, 10),
        prior_injury_side: r.prior_injury_side ?? "", hr_max: r.hr_max ?? "",
      })
  }, [open, r])
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }))
  const save = () =>
    run(async () => {
      await api.updateProfile(me!.runner_id!, {
        ...f,
        birth_year: f.birth_year ? Number(f.birth_year) : null,
        goal_date: f.goal_date || null,
        prior_injury: f.prior_injury || null,
        prior_injury_date: f.prior_injury_date || null,
        prior_injury_side: f.prior_injury_side || null,
        hr_max: f.hr_max ? Number(f.hr_max) : null,
      })
      await refresh()
      onClose()
    })
  const inp = "w-full rounded-xl border px-3 py-2.5 text-sm"
  return (
    <Sheet open={open} onClose={onClose}>
      <h2 className="font-serif text-2xl">Upravit profil</h2>
      <p className="mt-1 text-xs text-fg-2">Údaje, které používá engine (dřívější zranění, cílový závod) a fyzioterapeut (věk, pohlaví, město).</p>
      <div className="grid gap-1 md:grid-cols-2">
        <Field label="Rok narození"><input className={inp} inputMode="numeric" value={f.birth_year ?? ""} onChange={(e) => set("birth_year", e.target.value)} /></Field>
        <Field label="Pohlaví"><select className={inp} value={f.sex ?? ""} onChange={(e) => set("sex", e.target.value)}><option value="">—</option><option value="f">žena</option><option value="m">muž</option></select></Field>
        <Field label="Město"><input className={inp} value={f.city ?? ""} onChange={(e) => set("city", e.target.value)} /></Field>
        <Field label="Hodinky / zařízení"><input className={inp} value={f.device ?? ""} onChange={(e) => set("device", e.target.value)} /></Field>
        <Field label="Cílový závod"><input className={inp} value={f.goal_race ?? ""} onChange={(e) => set("goal_race", e.target.value)} placeholder="např. Pražský půlmaraton" /></Field>
        <Field label="Datum závodu" hint="další závody přidáte v Tréninku → Závody"><input type="date" className={inp} value={f.goal_date ?? ""} onChange={(e) => set("goal_date", e.target.value)} /></Field>
        <Field label="Dřívější zranění"><input className={inp} value={f.prior_injury ?? ""} onChange={(e) => set("prior_injury", e.target.value)} placeholder="např. Achillova šlacha" /></Field>
        <Field label="Kdy se zranění stalo" hint={f.prior_injury && !f.prior_injury_date ? "bez data ho engine počítá jako nedávné" : undefined}><input type="date" className={inp} value={f.prior_injury_date ?? ""} max={new Date().toISOString().slice(0, 10)} onChange={(e) => set("prior_injury_date", e.target.value)} /></Field>
        <Field label="Maximální tep (změřený)" hint={f.hr_max ? "tepové zóny se počítají z něj" : "z testu nebo závodu do vrchu; bez něj zóny odhadujeme"}><input className={inp} inputMode="numeric" value={f.hr_max ?? ""} placeholder="např. 192" onChange={(e) => set("hr_max", e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="Strana"><select className={inp} value={f.prior_injury_side ?? ""} onChange={(e) => set("prior_injury_side", e.target.value)}><option value="">—</option><option value="left">levá</option><option value="right">pravá</option><option value="both">obě</option></select></Field>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
      <div className="mt-5 flex gap-2">
        <button onClick={save} disabled={busy} className="btn btn-primary flex-1 py-3 text-sm">{busy ? "Ukládám…" : "Uložit profil"}</button>
        <button onClick={onClose} className="btn btn-outline px-5 py-3 text-sm">Zavřít</button>
      </div>
    </Sheet>
  )
}
const runnerNav: [string, string][] = [
  ["today", "Dnes"],
  ["post", "Deník"],
  ["mechanics", "Pohyb"],
  ["load", "Zátěž"],
  ["messages", "Péče"],
]
// The Trénink tab exists only with the Kapacitní engine (v3), right after Dnes.
function useRunnerNav(): [string, string][] {
  const { boot } = useApp()
  const v3 = (boot?.assessment?.engineMode || boot?.runner?.engine_mode) === "v3"
  return v3 ? [runnerNav[0], ["training", "Trénink"], ...runnerNav.slice(1)] : runnerNav
}
// feedback railway#38 — sync Garmin automatically when the runner opens / logs in
// to the app (once per page load); the Synchronizovat button stays for manual use.
let autoSyncDone = false
function useAutoGarminSync(active: boolean) {
  const { refresh } = useApp()
  const toast = useToast()
  useEffect(() => {
    if (!active || autoSyncDone) return
    autoSyncDone = true
    ;(async () => {
      try {
        const st: any = await api.garminStatus()
        if (!st?.connected) return
        const r: any = await api.garminSync()
        const na = r?.added_activities ?? 0, nd = r?.added_daily ?? 0
        if (na || nd) { toast({ title: "Garmin synchronizován", msg: `Staženo: ${na} aktivit, ${nd} dní dat.` }); refresh() }
      } catch { /* silent: the manual button still shows errors */ }
    })()
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
}
function Layout() {
  const { me, loading } = useApp()
  useAutoGarminSync(!!me && me.role === "runner")
  // New deployments: reload when the app returns to the foreground, or offer a
  // reload if one lands while it's in use (home-screen apps never reload alone).
  const [updateReady, setUpdateReady] = useState(false)
  useEffect(() => startUpdateWatcher(() => setUpdateReady(true)), [])
  const navItems = useRunnerNav()
  const rail = useLocation().pathname.startsWith("/app/")
  if (loading)
    return (
      <div className="motion-shell grid min-h-screen place-items-center bg-bg text-fg-2" role="status">
        <span className="flex flex-col items-center gap-3"><Mark size={44} /><span className="t-label">načítám…</span></span>
      </div>
    )
  if (!me) return <Navigate to="/auth" replace />
  if (me.role !== "runner") return <RunnerOnlyNotice />
  return (
    <AnnotateProvider>
      <div className="motion-shell min-h-screen bg-bg text-fg">
        <Sidebar items={navItems} />
        <Topbar />
        {/* FIX-5: bottom padding = tab bar + Check-in button + 16 px, so the button never covers content. */}
        <div className="lg:pl-[220px]">
          <main className="mx-auto min-h-screen max-w-[1180px] bg-bg px-5 pb-[calc(9rem+env(safe-area-inset-bottom))] pt-[calc(6rem+env(safe-area-inset-top))] md:px-9 md:pb-28 md:pt-24">
            {rail ? (
              <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_280px] xl:gap-7">
                <div className="min-w-0"><Outlet /></div>
                <StatRail />
              </div>
            ) : <Outlet />}
          </main>
        </div>
        <AtlasBubble />
        <AtlasNav />
        {updateReady && (
          <div className="fixed inset-x-0 top-[calc(76px+env(safe-area-inset-top))] z-50 flex justify-center px-4 lg:left-[220px]" role="status">
            <div className="flex items-center gap-3 rounded-full border border-white/10 bg-raised py-2 pl-4 pr-2 text-[13px] text-fg shadow-[0_16px_40px_rgb(0_0_0_/_0.45)]">
              <span>Je dostupná nová verze aplikace.</span>
              <button onClick={() => location.reload()} className="btn btn-primary btn-sm">Aktualizovat</button>
            </div>
          </div>
        )}
        <AnnotationLayer />
      </div>
    </AnnotateProvider>
  )
}

// Runner-only build: physio / employer / partner accounts don't have a UI yet.
function RunnerOnlyNotice() {
  const { me, logout } = useApp()
  return (
    <div className="motion-shell grid min-h-screen place-items-center bg-bg p-6 text-fg">
      <div className="card max-w-md p-8 text-center">
        <div className="mx-auto flex w-fit items-center gap-2 font-bold"><Mark /> došlap</div>
        <h1 className="mt-6 font-serif text-3xl">Zatím jen pro běžce</h1>
        <p className="mt-3 text-sm leading-6 text-fg-2">
          Účet <b>{me?.email}</b> má roli „{me?.role}". Rozhraní pro fyzioterapeuty a partnery se teprve připravuje —
          přihlaste se prosím běžeckým účtem.
        </p>
        <button onClick={logout} className="btn btn-primary mt-6">Odhlásit se</button>
      </div>
    </div>
  )
}
function Label({ children }: { children: string }) {
  return (
    <p className="t-label">
      {children}
    </p>
  )
}
function Card({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`group card p-4 transition duration-200 md:p-5 hover:-translate-y-0.5 hover:border-info/45 hover:shadow-[0_14px_34px_rgb(0_0_0_/_0.35)] ${className}`}
    >
      {children}
    </section>
  )
}
function Metric({
  label,
  value,
  caption,
  warm = false,
}: {
  label: string
  value: string
  caption: string
  warm?: boolean
}) {
  return (
    <Card className={warm ? "border-0 bg-panel-2 text-fg" : ""}>
      <Label>{label}</Label>
      <p
        className={`mt-4 font-serif text-4xl tracking-[-.07em] ${
          warm ? "text-white" : ""
        }`}
      >
        {value}
      </p>
      <p
        className={`mt-2 text-xs ${warm ? "text-fg-soft" : "text-fg-2"}`}
      >
        {caption}
      </p>
    </Card>
  )
}
function RecoveryRanges({ rows }: { rows?: any[] }) {
  const col = (t: string) => (t === "ok" ? C.ok : t === "watch" ? C.watch : t === "alert" ? C.alert : C.fg2)
  // Plain status words; an alert above the usual level (resting HR) reads "nad normou".
  const word = (r: any) => (r.tone === "ok" ? "v normě" : r.tone === "watch" ? "sledovat" : r.tone === "alert" ? (r.valNum > r.baseNum ? "nad normou" : "pod normou") : "—")
  const fmt = (n: number) => (Number.isInteger(n) ? `${n}` : `${Math.round(n * 10) / 10}`.replace(".", ","))
  if (!rows || !rows.length) return <p className="mt-4 text-sm text-fg-3">Chybí souvislá data z hodinek za posledních 35 dní.</p>
  return (
    <div className="mt-4 space-y-6">
      {rows.map((r: any) => {
        const sd = (r.hi - r.lo) / 2 || 1
        const dLo = Math.min(r.lo, r.valNum) - sd * 0.8
        const dHi = Math.max(r.hi, r.valNum) + sd * 0.8
        const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 3, 97)
        const bandL = P(r.lo), bandR = P(r.hi), mk = P(r.valNum), c = col(r.tone)
        const Icon = r.icon as LucideIcon
        return (
          <div key={r.label}>
            <div className="flex items-baseline justify-between">
              <span className="flex items-center gap-2 text-sm text-fg-soft"><Icon className="size-4 text-info" aria-hidden />{r.label}</span>
              <span className="text-[13px] font-bold" style={{ color: c }}>{word(r)}</span>
            </div>
            <div className="relative mt-6 h-2 rounded-full bg-white/[.06]">
              {/* usual range (baseline ± 1 SD) */}
              <i className="absolute top-0 h-full rounded-full" style={{ left: `${bandL}%`, width: `${bandR - bandL}%`, background: `${C.ok}52` }} />
              {/* baseline center tick */}
              <i className="absolute top-[-3px] h-3.5 w-px bg-fg-2/80" style={{ left: `${P(r.baseNum)}%` }} />
              {/* current-value marker + its number */}
              <b className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${mk}%`, backgroundColor: c, boxShadow: `0 0 0 3px ${C.bg}, 0 0 0 6px ${c}40` }} />
              <span className="absolute -top-6 -translate-x-1/2 whitespace-nowrap tabular-nums text-[12px] font-extrabold" style={{ left: `${mk}%`, color: c }}>{fmt(r.valNum)}{r.unit ? ` ${r.unit}` : ""}</span>
            </div>
            {/* numeric axis: usual-range bounds under the band edges */}
            <div className="relative mt-1.5 h-3.5 tabular-nums text-[11px] text-fg-3">
              <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${bandL}%` }}>{fmt(r.lo)}</span>
              <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${bandR}%` }}>{fmt(r.hi)}</span>
            </div>
            <p className="text-[11px] text-fg-3">obvyklé rozmezí {fmt(r.lo)}–{fmt(r.hi)}{r.unit ? ` ${r.unit}` : ""} · obvykle {fmt(r.baseNum)}</p>
          </div>
        )
      })}
    </div>
  )
}
const QCOL: Record<string, string> = { stable: C.ok, overreaching: C.watch, silent: C.self, critical: C.alert }
const QCELLS: [string, string][] = [
  ["stable", "Stabilní"],
  ["silent", "Tichý drift"],
  ["overreaching", "Přetížení"],
  ["critical", "Kritická"],
]
// State card, top row: quadrant chip (the only place the quadrant name appears, FIX-4),
// the Garmin sync button and the 6-month history button.
function QuadrantHead({ quadrant = "stable", live, onSync, syncing, syncMsg, canSync, alertSlot }: { quadrant?: string; live?: any; onSync?: () => void; syncing?: boolean; syncMsg?: string | null; canSync?: boolean; alertSlot?: React.ReactNode }) {
  const q = QUAD[quadrant] || QUAD.stable
  const col = QCOL[quadrant] || C.ok
  return (
    <div>
      {/* railway#73 — the sync button always sits on the right, even on a phone */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="t-label !text-fg-3">Kvadrant stavu</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full py-1.5 pl-2.5 pr-3.5 font-serif text-[17px] leading-none" style={{ background: `${col}1f`, color: C.fg, boxShadow: `inset 0 0 0 1px ${col}55` }}>
              <i className="size-2.5 shrink-0 rounded-full" style={{ background: col, boxShadow: `0 0 0 3px ${col}33` }} />
              {q.t}
            </span>
            {alertSlot}
            {(live?.engineMode === "v2" || live?.engineMode === "v3") && (live?.mechFlag || live?.mechWatch) && (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold"
                style={live?.mechFlag ? { background: `${C.alert}20`, color: C.alertSoft } : { background: "rgb(255 255 255 / .07)", color: C.fg2 }}
                title={live?.mechFlag ? "Citlivý engine: mechanika se v rizikovém směru drží mimo vaši normu napříč běhy, nebo se to ukazuje ve dvou nezávislých skupinách metrik" : "Citlivý engine: jedna skupina metrik mechaniky se výrazně odchýlila — zatím jen sledujeme"}
              >
                {live?.mechFlag ? "⚑ mechanika přetrvává" : "◔ sledovat mechaniku"}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {onSync && (
            <button
              onClick={onSync}
              disabled={syncing || !canSync}
              title={canSync ? "Stáhnout nová data z Garminu" : "Nejdřív připojte Garmin pro automatickou synchronizaci na stránce Data"}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-accent/40 bg-accent/10 px-3 py-1.5 text-[12px] font-bold text-accent transition enabled:hover:border-accent enabled:hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw className={`size-3.5 ${syncing ? "animate-spin" : ""}`} aria-hidden />
              {syncing ? "Synchronizuji…" : "Synchronizovat"}
            </button>
          )}
        </div>
      </div>
      {syncMsg && <p className="mt-2 text-[12px] font-medium text-fg-2" role="status">{syncMsg}</p>}
      <p className="mt-2 max-w-xl text-[13px] leading-5 text-fg-2">{q.d}</p>
    </div>
  )
}
// Compact 2×2: mechanika (sloupce) × zátěž (řádky). Aktivní buňka = reálný kvadrant; tap opens history.
function QuadrantGrid({ quadrant = "stable", onHistory }: { quadrant?: string; onHistory?: () => void }) {
  const Wrap = onHistory ? "button" : "div"
  return (
    <div>
      {/* railway#72 — the 6-month history opens from the quadrant graphic itself */}
      <div className="mb-2.5 flex min-h-[30px] items-center justify-between gap-2">
        <p className="t-label !text-fg-3">Mechanika × zátěž</p>
        {onHistory && (
          <button type="button" onClick={onHistory} className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-white/14 px-3 py-1.5 text-[12px] font-bold text-info transition hover:border-info/50 hover:bg-info/[.07]">
            historie 6 měsíců <Maximize2 className="size-3.5" aria-hidden />
          </button>
        )}
      </div>
      <Wrap {...(onHistory ? { type: "button" as const, onClick: onHistory, title: "Zobrazit vývoj stavu za 6 měsíců" } : {})} className="grid w-full grid-cols-2 gap-2 text-left">
        {QCELLS.map(([key, label]) => {
          const active = key === quadrant
          const c = QCOL[key]
          return (
            <span
              key={key}
              aria-current={active ? "true" : undefined}
              className="relative overflow-hidden rounded-[14px] border px-3 py-3 transition"
              style={{ borderColor: active ? c : "rgb(255 255 255 / .08)", background: active ? `${c}24` : "rgb(255 255 255 / .03)", boxShadow: active ? `inset 0 0 0 1px ${c}` : undefined }}
            >
              <span className="flex items-center gap-2">
                <i className={`size-2 rounded-full ${active ? "atlas-point" : ""}`} style={{ background: active ? c : `${c}66` }} />
                <b className="text-[13px]" style={{ color: active ? C.fg : C.fg2 }}>{label}</b>
              </span>
            </span>
          )
        })}
      </Wrap>
      <div className="mt-2 flex justify-between text-[11px] font-bold uppercase tracking-[.12em] text-fg-3">
        <span>← vodorovně: mechanika</span>
        <span>svisle: zátěž ↑</span>
      </div>
    </div>
  )
}

// Large pop-out: daily state over the last ~6 months — bar height = overall
// risk, color = quadrant. Hover a bar to see that day's date and the signals
// that were influencing the state.
function QuadrantHistory({ history, today, onClose }: { history?: any[] | null; today: OverviewDay; onClose: () => void }) {
  const raw = (history || []) as OverviewDay[]
  // Pin the final ("dnes") day to the live overview so it always equals the Dnes card.
  const data: OverviewDay[] = raw.length ? [...raw.slice(0, -1), { ...raw[raw.length - 1], ...today, date: today.date || raw[raw.length - 1].date }] : raw
  const n = data.length
  const [sel, setSel] = useState<number | null>(null)
  const i = sel != null && sel < n ? sel : n - 1
  const cur = data[i]
  const maxOv = Math.max(20, ...data.map((d) => d.overall || 0))
  const fmtShort = (s?: string) => (s ? new Date(s).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" }) : "")
  const fmtLong = (s?: string) => (s ? new Date(s).toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" }) : "")
  const chartRef = useRef<HTMLDivElement>(null)
  // drag / tap anywhere on the strip to pick a day (bars are ~2 px wide on a phone)
  const pick = (clientX: number) => {
    const el = chartRef.current
    if (!el || !n) return
    const r = el.getBoundingClientRect()
    setSel(clamp(Math.floor(((clientX - r.left) / r.width) * n), 0, n - 1))
  }
  const step = (d: number) => setSel(clamp(i + d, 0, n - 1))
  const q = cur ? QUAD[cur.quadrant || "stable"] || QUAD.stable : null
  const qc = cur ? QCOL[cur.quadrant || "stable"] || C.ok : C.ok
  return createPortal(
    <>
      <div className="fixed inset-0 z-[80] bg-bg/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 top-[calc(56px+env(safe-area-inset-top))] z-[90] flex flex-col overflow-hidden rounded-t-[22px] border-t border-white/12 bg-raised pb-[env(safe-area-inset-bottom)] text-fg shadow-[0_-20px_60px_rgb(0_0_0_/_0.5)] md:top-[calc(68px+env(safe-area-inset-top))] lg:left-[220px]">
        <div className="flex items-start justify-between gap-3 border-b border-white/10 px-4 py-3.5 md:p-5">
          <div className="min-w-0">
            <p className="t-label !text-fg-3">Vývoj stavu · 6 měsíců</p>
            <h2 className="mt-0.5 font-serif text-[20px] leading-tight md:text-2xl">Kvadrant a rizikové skóre po dnech</h2>
          </div>
          <button onClick={onClose} aria-label="Zavřít" className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 text-fg-2 hover:text-fg"><X className="size-4" aria-hidden /></button>
        </div>

        {n < 2 ? (
          <p className="p-6 text-sm text-fg-3">{history == null ? "Počítám historii…" : "Zatím málo historie."}</p>
        ) : (
          <div className="flex-1 overflow-y-auto overscroll-contain">
            <div className="mx-auto w-full max-w-[1180px] px-4 pb-8 md:px-5">
              {/* strip + day picker stay pinned while the overview scrolls under them (phone) */}
              <div className="sticky top-0 z-10 -mx-4 bg-raised px-4 pb-3 pt-4 shadow-[0_10px_18px_-14px_rgb(0_0_0_/_.8)] md:-mx-5 md:px-5">
              {/* day strip: height = score, colour = quadrant */}
              <div
                ref={chartRef}
                role="slider" tabIndex={0} aria-label="Vybraný den" aria-valuemin={0} aria-valuemax={n - 1} aria-valuenow={i} aria-valuetext={fmtLong(cur?.date)}
                onKeyDown={(e) => { if (e.key === "ArrowLeft") { e.preventDefault(); step(-1) } if (e.key === "ArrowRight") { e.preventDefault(); step(1) } }}
                onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
                onPointerMove={(e) => { if (e.buttons || e.pointerType === "mouse") pick(e.clientX) }}
                className="relative flex h-[112px] cursor-crosshair select-none items-end rounded-[14px] bg-ink p-1.5 outline-none focus-visible:ring-2 focus-visible:ring-accent md:h-[170px] md:gap-px md:p-2"
                style={{ touchAction: "pan-y" }}
              >
                {data.map((d, idx) => (
                  <i key={d.date || idx} className="block flex-1 rounded-[1px]" style={{ height: `${Math.max(5, ((d.overall || 0) / maxOv) * 100)}%`, background: QCOL[d.quadrant || "stable"] || C.fg4, opacity: idx === i ? 1 : 0.62 }} />
                ))}
                <i className="pointer-events-none absolute inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-fg shadow-[0_0_0_2px_rgb(6_16_16_/_.6)]" style={{ left: `calc(${((i + 0.5) / n) * 100}% )` }} aria-hidden />
              </div>
              <div className="mt-1 flex justify-between tabular-nums text-[11px] text-fg-3">
                <span>{fmtShort(data[0].date)}</span>
                <span>výška = skóre · barva = kvadrant</span>
                <span>dnes</span>
              </div>

              {/* day picker for thumbs */}
              <div className="mt-3 flex items-center gap-2">
                <button type="button" onClick={() => step(-1)} disabled={i <= 0} aria-label="Předchozí den" className="grid size-10 shrink-0 place-items-center rounded-full border border-white/14 text-fg-2 transition enabled:hover:text-fg disabled:opacity-30"><ChevronLeft className="size-4" aria-hidden /></button>
                <div className="min-w-0 flex-1 text-center">
                  <p className="truncate text-[14px] font-bold text-fg first-letter:uppercase" data-day>{i === n - 1 ? "Dnes · " : ""}{fmtLong(cur?.date)}</p>
                  {q && (
                    <p className="mt-0.5 inline-flex flex-wrap items-center justify-center gap-x-1.5 text-[12px] font-semibold text-fg-2">
                      <i className="size-2 rounded-full" style={{ background: qc }} />{q.t}
                      {i !== n - 1 && <><span className="text-fg-4">·</span><button type="button" onClick={() => setSel(n - 1)} className="font-bold text-info hover:underline">zpět na dnešek</button></>}
                    </p>
                  )}
                </div>
                <button type="button" onClick={() => step(1)} disabled={i >= n - 1} aria-label="Další den" className="grid size-10 shrink-0 place-items-center rounded-full border border-white/14 text-fg-2 transition enabled:hover:text-fg disabled:opacity-30"><ChevronRight className="size-4" aria-hidden /></button>
              </div>
              </div>

              {/* railway#88 — the same overview as on Dnes, for the picked day */}
              {cur && (
                <div className="nest mt-4 p-4 md:p-6">
                  {q && <p className="mb-4 max-w-xl text-[13px] leading-5 text-fg-2">{q.d}</p>}
                  <StateOverview d={cur} />
                </div>
              )}
              <p className="mt-3 text-[11px] leading-4 text-fg-3">Denní přehrání enginu z dat do daného dne, včetně check-inů a hodnocení běhů. Tažením po pásu nebo šipkami vyberete den.</p>
            </div>
          </div>
        )}
      </div>
    </>,
    document.body,
  )
}
// Plan B3: pain that limits movement, keeps coming back, got worse overnight or
// hit right after a run → ask whether it's an injury, with the OSTRC report
// prefilled (sites, and "participation with problems" when movement is limited).
function InjuryPrompt({ a }: { a: any }) {
  const { me, refresh } = useApp()
  const [open, setOpen] = useState(false)
  const rid = me?.runner_id
  if (!rid || !a || a.injury?.active) return null
  const f = a.functionLimit, pm = a.painMonitor, ac = a.acuteOverload, rec = a.painRecurring
  if (!f && !pm && !ac && !rec) return null
  const split = (x?: string | null) => (x ? x.split(",").map((t) => t.trim()).filter(Boolean) : [])
  const regions = [...new Set([...split(f?.site), ...(ac?.sites || []), ...split(pm?.morningWorse?.site), ...split(rec?.site)])]
  const why = f ? "Bolest omezila pohyb nebo běh" : pm?.morningWorse ? "Bolest je ráno horší než při běhu" : pm?.trend ? "Bolest týden od týdne roste"
    : ac ? "Přetížení hned po běhu" : `Stejné místo bolí opakovaně (${rec.days}× za 28 dní)`
  const q: Record<string, number> = f?.severe ? { q_participation: 17, q_pain: 8 } : f?.runModified ? { q_participation: 8, q_volume: 8, q_pain: 8 } : { q_pain: 8 }
  return (
    <>
      {open && <InjurySheet rid={rid} initialRegions={regions} initialQ={q} intro={`${why} — upravte odpovědi podle skutečnosti.`}
        onClose={() => setOpen(false)} onDone={() => { setOpen(false); refresh() }} />}
      <AlertBanner tone="info" icon={Bandage} title="Je to zranění?"
        action={<Button size="sm" variant="danger" onClick={() => setOpen(true)}>Nahlásit zranění</Button>}>
        {why}. Když to omezuje trénink, nahlaste to — zapíše se to do historie zranění, přizpůsobí se plán a po zahojení vás aplikace vrátí k běhu postupně.
      </AlertBanner>
    </>
  )
}

// OPT-1 + feedback railway#42 · today's Trénink guidance as a strip inside the
// state card, above the overall score, linking to the Trénink tab (v3 only).
const kmFmt = (v: number) => v.toLocaleString("cs-CZ", { maximumFractionDigits: 1 })
function RecommendationStrip({ a }: { a: any }) {
  const g = a?.guidance
  if (a?.engineMode !== "v3" || !g) return null
  const t = g.types?.[g.type]
  if (!t) return null
  const ov = g.override
  const physio = ov && (ov.kind === "physio" || ov.kind === "function")
  const run = g.type !== "volno" && g.type !== "závod"
  const col = ov ? C.alert : C.accent
  const facts = run
    ? [t.km && t.km.hi ? `${t.km.lo === t.km.hi ? kmFmt(t.km.lo) : `${kmFmt(t.km.lo)}–${kmFmt(t.km.hi)}`} km` : null, t.hr ? `${t.hr[0]}–${t.hr[1]} tep/min` : null, t.durationMin ? `≈ ${t.durationMin[0]}–${t.durationMin[1]} min` : null].filter(Boolean).join(" · ")
    : t.notes?.[0]
  return (
    // railway#75 — only the verdict and the way to Trénink, on one short row
    <div className="nest mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 px-3.5 py-2.5" style={{ borderColor: `${col}55`, backgroundImage: `linear-gradient(120deg, ${col}17, transparent 60%)` }}
      aria-label={`Doporučení na dnes: ${t.label}${ov?.title ? ` — ${ov.title}` : facts ? ` — ${facts}` : ""}`} title={ov?.title || facts || undefined}>
      <p className="min-w-[7rem] flex-1 font-serif text-[20px] leading-tight" style={{ color: ov ? C.alertSoft : C.fg }}>
        {t.label}
        {g.provisional && <i className="ml-2 inline-block size-2 -translate-y-0.5 rounded-full bg-watch" title="předběžné · čeká na ranní data" />}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {physio && <Link to="/app/messages" className="btn btn-primary btn-sm">Objednat fyzioterapeuta</Link>}
        <Link to="/app/training" className="btn btn-outline btn-sm">Trénink <ChevronRight className="size-3.5" aria-hidden /></Link>
      </div>
    </div>
  )
}

// railway#76 — Regenerace, Příznaky, Zátěž and Mechanika as small rings around the score;
// the ones with a detail open a panel under the card.
function MiniRing({ label, value, col, onClick, open }: { label: string; value: number | null | undefined; col: string; onClick?: () => void; open?: boolean }) {
  const R = 2 * Math.PI * 42
  const body = (
    <>
      <span className="relative grid size-[58px] place-items-center">
        <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90" aria-hidden>
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="9" />
          {value != null && <circle cx="50" cy="50" r="42" fill="none" stroke={col} strokeWidth="9" strokeLinecap="round" strokeDasharray={R} strokeDashoffset={R * (1 - clamp(value, 0, 100) / 100)} />}
        </svg>
        <b className="t-num text-[18px] leading-none" style={{ color: value == null ? C.fg3 : C.fg }}>{value ?? "—"}</b>
      </span>
      <span className="mt-1 flex items-center justify-center gap-0.5 whitespace-nowrap text-[10px] font-bold uppercase tracking-[.08em] text-fg-2">
        {label}{onClick && <ChevronDown className={`size-3 transition ${open ? "rotate-180 text-accent" : "text-fg-3"}`} aria-hidden />}
      </span>
    </>
  )
  return onClick
    ? <button type="button" onClick={onClick} aria-expanded={!!open} className={`flex flex-col items-center rounded-[14px] p-1 transition hover:bg-white/[.05] ${open ? "bg-white/[.07] ring-1 ring-accent/50" : ""}`}>{body}</button>
    : <div className="flex flex-col items-center p-1">{body}</div>
}

// railway#88 — the Dnes overview (rings, readiness, verdict, quadrant, drivers) as one
// component, so the 6-month history shows any past day exactly like today.
type PanelKey = "mech" | "load" | "recovery" | "readiness" | "symp"
type OverviewDay = {
  date?: string; quadrant?: string; overall?: number; tier?: string
  mech?: number | null; load?: number | null; symp?: number | null; rcv?: number | null; readiness?: number | null
  painRecurring?: { site: string; days: number } | null; signals?: any[]
}
const axisCol = (v: number | null | undefined, hot: string) => (v == null ? C.fg3 : v >= 25 ? hot : v >= 12 ? C.watch : C.fg)
const gradeTone = (g: string) => (g === "A" ? "alert" : g === "B" ? "watch" : "ok") as "alert" | "watch" | "ok"
function StateOverview({ d, open = null, onToggle, panel, onHistory, note }: { d: OverviewDay; open?: PanelKey | null; onToggle?: (k: PanelKey) => void; panel?: React.ReactNode; onHistory?: () => void; note?: React.ReactNode }) {
  const overall = d.overall ?? 0
  const RING = 2 * Math.PI * 44
  const score = d.rcv ?? null
  const scoreCol = score == null ? C.fg3 : score >= 67 ? C.ok : score >= 34 ? C.watch : C.alert
  const tierCol = d.tier === "alert" ? C.alert : d.tier === "watch" ? C.watch : C.ok
  const tierWord = d.tier === "alert" ? "vysoké riziko" : d.tier === "watch" ? "sledovat" : "nízké riziko"
  const recur = d.painRecurring
  // FIX-4: the quadrant name lives in the chip; the verdict carries the priority
  const priority = d.tier === "alert" || recur ? "Prioritou je odlehčení" : d.tier === "watch" ? "Sledujte zátěž" : "Trénink sedí"
  const verdict = recur && d.tier !== "alert" ? "Odlehčit — opakovaná bolest" : priority
  const signals = d.signals || []
  const tg = (k: PanelKey) => (onToggle ? () => onToggle(k) : undefined)
  return (
    <div className="grid gap-6 md:grid-cols-2 md:gap-8">
      <div>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <div className="grid justify-items-center gap-2">
            <MiniRing label="Regenerace" value={score} col={scoreCol} onClick={tg("recovery")} open={open === "recovery"} />
            <MiniRing label="Příznaky" value={d.symp} col={axisCol(d.symp, C.alert)} onClick={tg("symp")} open={open === "symp"} />
          </div>
          <div className="relative grid size-[132px] place-items-center">
            <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90" aria-hidden>
              <circle cx="50" cy="50" r="44" fill="none" stroke="rgb(255 255 255 / .09)" strokeWidth="8" />
              <circle cx="50" cy="50" r="44" fill="none" stroke={tierCol} strokeWidth="8" strokeLinecap="round" strokeDasharray={RING} strokeDashoffset={RING * (1 - clamp(overall, 0, 100) / 100)} />
            </svg>
            <span className="text-center">
              <b className="t-num block text-[40px] leading-none text-fg">{overall}</b>
              <span className="mt-1 block text-[11px] font-bold uppercase tracking-[.1em] text-fg-2">Skóre</span>
            </span>
            <span className="absolute -right-1 top-1"><InfoDot text={MI.overall} label="Skóre" /></span>
          </div>
          <div className="grid justify-items-center gap-2">
            <MiniRing label="Zátěž" value={d.load} col={C.load} onClick={tg("load")} open={open === "load"} />
            <MiniRing label="Mechanika" value={d.mech} col={axisCol(d.mech, C.alert)} onClick={tg("mech")} open={open === "mech"} />
          </div>
        </div>
        {d.readiness != null && (
          <div className="mt-3 flex justify-center">
            <SideStat label="Připravenost" value={d.readiness} unit=" %" col={readinessCol(d.readiness)} align="center" onClick={tg("readiness")} open={open === "readiness"} />
          </div>
        )}
        <div className="mt-4 text-center">
          <h3 className="font-serif text-[21px] leading-tight text-fg">{verdict}</h3>
          <p className="mt-1 flex items-center justify-center gap-1.5 text-[13px] font-bold" style={{ color: tierCol }}>
            {tierWord}
            {/* railway#77 — the recurring-pain note opens from the ! next to the risk word */}
            {recur && <InfoDot variant="watch" label="Opakovaná bolest" text={`${recur.site} · ${recur.days}× za 28 dní — i mírná bolest na stejném místě je vzorec přetížení. Kratší a volnější běhy, bez dlouhého běhu a intenzity.`} />}
          </p>
        </div>
      </div>
      {panel}
      <div>
        <QuadrantGrid quadrant={d.quadrant} onHistory={onHistory} />
        <div className="mt-5">
          <p className="t-label !text-fg-3">Co {onToggle ? "teď nejvíc ovlivňuje" : "nejvíc ovlivňovalo"} stav</p>
          {signals.length ? <ImpactPyramid signals={signals} tone={gradeTone} />
            : <p className="mt-2 text-sm text-fg-2">Nic nad prahem — zátěž i mechanika {onToggle ? "sedí" : "seděly"} na vaší normě.</p>}
          {note}
        </div>
      </div>
    </div>
  )
}

// railway#84 — Příznaky: where it hurts (runs and daily check-ins, 30 days), the last
// daily check-in in short and what feeds the symptom score.
function SymptomPanel({ signals }: { signals: any[] }) {
  const { boot } = useApp()
  const since = (days: number) => new Date(Date.now() - days * 864e5).toISOString()
  const cut30 = since(30), cut7 = since(7)
  const fb = (boot?.activity_feedback || []) as any[]
  const cis = ((boot?.checkins || []) as any[]).slice().sort((x, y) => (y.submitted_at || "").localeCompare(x.submitted_at || ""))
  const counts: Record<string, number> = {}, sided: Record<string, number> = {}
  const add = (pts: any[]) => (pts || []).forEach((p: any) => {
    if (!p?.region) return
    counts[p.region] = (counts[p.region] || 0) + 1
    sided[painKey(p)] = (sided[painKey(p)] || 0) + 1
  })
  fb.filter((f) => (f.submitted_at || "") >= cut30).forEach((f) => add(f.pain_points))
  cis.filter((c) => (c.submitted_at || "") >= cut30).forEach((c) => add(c.pain_points))
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 4)
  const last = cis[0]
  const wk = cis.filter((c) => (c.submitted_at || "") >= cut7)
  const avg = (k: string) => { const v = wk.map((c) => c[k]).filter((x) => x != null) as number[]; return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null }
  const f1 = (v: number | null | undefined) => (v == null ? "—" : (Math.round(v * 10) / 10).toLocaleString("cs-CZ"))
  const sympSig = signals.filter((x) => !MECH_IDS.has(x.id) && !LOAD_IDS.has(x.id))
  const maxPts = Math.max(1, ...sympSig.map((x) => x.pts || 0))
  const cell = (label: string, v: number | null | undefined, max: number, warnAt: number) => (
    <div className="nest px-2 py-2.5 text-center">
      <p className="t-num text-[20px] leading-none" style={{ color: v != null && v >= warnAt ? C.alert : C.fg }}>{v == null ? "—" : v}<small className="text-[11px] font-semibold text-fg-3">/{max}</small></p>
      <p className="mt-1 text-[11px] text-fg-3">{label}</p>
    </div>
  )
  return (
    <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] md:gap-8">
      <div>
        <div className="flex items-center justify-between gap-2">
          <p className="t-label">Kde to bolí · 30 dní</p>
          <Link to="/app/post" className="inline-flex items-center gap-1 text-[12px] font-bold text-accent hover:underline">Deník<ChevronRight className="size-3.5" aria-hidden /></Link>
        </div>
        {top.length ? (
          <>
            <div className="mx-auto mt-3 max-w-[190px]"><PainHeatmap counts={sided} /></div>
            <div className="mt-3 space-y-1.5">
              {top.map(([region, n]) => (
                <div key={region} className="flex items-center gap-2 text-[12px]">
                  <span className="w-32 shrink-0 truncate text-fg-soft">{region}</span>
                  <div className="h-1.5 flex-1 rounded-full bg-white/[.08]"><i className="block h-full rounded-full bg-alert" style={{ width: `${Math.round((n / top[0][1]) * 100)}%` }} /></div>
                  <span className="tabular-nums text-fg-2">{n}×</span>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-fg-3">z hodnocení běhů i denních check-inů</p>
          </>
        ) : <p className="mt-2 text-[12px] text-fg-2">Za posledních 30 dní žádné označené bolestivé místo.</p>}
      </div>
      <div>
        <p className="t-label">Denní check-in</p>
        {last ? (
          <>
            <p className="mt-1 text-[12px] text-fg-3">poslední {fmtD(last.submitted_at)}{last.notes ? ` · „${String(last.notes).slice(0, 60)}${String(last.notes).length > 60 ? "…" : ""}“` : ""}</p>
            <div className="mt-2.5 grid grid-cols-4 gap-2">
              {cell("bolest", last.pain_score, 10, 4)}
              {cell("ztuhlost", last.soreness, 10, 6)}
              {cell("únava", last.stress, 10, 6)}
              {cell("nálada", last.mood, 4, 99)}
            </div>
            <p className="mt-2 text-[11px] text-fg-3">{wk.length ? `za 7 dní ${wk.length}× · ø bolest ${f1(avg("pain_score"))}/10 · ø únava ${f1(avg("stress"))}/10` : "za posledních 7 dní žádný check-in"}</p>
          </>
        ) : <p className="mt-2 text-[12px] text-fg-2">Zatím žádný denní check-in — přidáte ho tlačítkem Check-in.</p>}
        <p className="t-label mt-4 !text-fg-3">Co tvoří skóre příznaků</p>
        {sympSig.length ? (
          <div className="mt-2.5 space-y-2.5">
            {sympSig.map((x) => <FactorBar key={x.id} label={x.name} value={x.val} pts={x.pts} tone="alert" pct={((x.pts || 0) / maxPts) * 100} />)}
          </div>
        ) : <p className="mt-2 text-[12px] text-fg-2">Nic nad vaší obvyklou úrovní — skóre je 0.</p>}
      </div>
    </div>
  )
}

function SideStat({ label, value, col, align = "left", unit, onClick, open }: { label: string; value: number | null | undefined; col: string; align?: "left" | "right" | "center"; unit?: string; onClick?: () => void; open?: boolean }) {
  const body = (
    <>
      <span className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-[.1em] text-fg-2" style={{ justifyContent: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}>
        {label}{onClick && <ChevronDown className={`size-3.5 text-fg-3 transition ${open ? "rotate-180 text-accent" : ""}`} aria-hidden />}
      </span>
      <span className="t-num mt-0.5 block text-[24px] leading-none" style={{ color: value == null ? C.fg3 : col }}>{value ?? "—"}{value != null && unit && <small className="text-[13px] font-semibold text-fg-3">{unit}</small>}</span>
    </>
  )
  const cls = align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left"
  return onClick
    ? <button type="button" onClick={onClick} aria-expanded={!!open} className={`${cls} -m-1.5 rounded-[12px] p-1.5 transition hover:bg-white/[.05] ${open ? "bg-white/[.06]" : ""}`}>{body}</button>
    : <div className={cls}>{body}</div>
}

type AlertRow = { key: string; tone: "stop" | "alert" | "watch" | "info"; icon?: LucideIcon; title: React.ReactNode; body: React.ReactNode }
function TodayV2() {
  const { me, boot, refresh, error } = useApp()
  const a = boot?.assessment
  const L = a?.loadDetail
  const rcv = a?.rcv
  const rid = me?.runner_id
  const [quadHist, setQuadHist] = useState<any[] | null>(null)
  const [histOpen, setHistOpen] = useState(false)
  const [alertsOpen, setAlertsOpen] = useState(false)
  // feedback railway#69/#70 — tap Mechanika / Zátěž for its trend + what drives it
  // railway#79–#81 — Regenerace and Připravenost open their detail the same way
  const [statPanel, setStatPanel] = useState<PanelKey | null>(null)
  const togglePanel = (k: PanelKey) => setStatPanel(statPanel === k ? null : k)
  const [axisHist, setAxisHist] = useState<any[] | null>(null)
  useEffect(() => {
    if ((statPanel !== "mech" && statPanel !== "load") || !rid || axisHist !== null) return
    let alive = true
    api.mechHistory(rid).then((h) => alive && setAxisHist(Array.isArray(h) ? h : [])).catch(() => alive && setAxisHist([]))
    return () => { alive = false }
  }, [statPanel, rid, axisHist])
  useEffect(() => {
    if (!rid) return
    let alive = true
    api.quadrantHistory(rid).then((h) => alive && setQuadHist(h)).catch(() => alive && setQuadHist([]))
    return () => { alive = false }
  }, [rid])
  // Garmin one-tap sync (next to the quadrant). Enabled only when a stored
  // session token exists (runner opted into "remember" on the Data page).
  const [gStatus, setGStatus] = useState<any | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    api.garminStatus().then((s) => alive && setGStatus(s)).catch(() => alive && setGStatus(null))
    return () => { alive = false }
  }, [rid])
  const doSync = async () => {
    setSyncing(true); setSyncMsg(null)
    try {
      const r: any = await api.garminSync()
      const na = r?.added_activities ?? 0, nd = r?.added_daily ?? 0
      setSyncMsg(na || nd ? `Staženo: ${na} aktivit, ${nd} dní dat.` : "Máte aktuální data — nic nového.")
      if (r?.status) setGStatus(r.status)
      await refresh()
    } catch (e: any) {
      setSyncMsg(e?.message || "Synchronizace se nezdařila.")
      api.garminStatus().then(setGStatus).catch(() => {})
    } finally {
      setSyncing(false)
    }
  }
  const firstName = (me?.name || "").split(" ")[0] || "běžče"
  const today = new Date().toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
  const hour = new Date().getHours()
  const greet = hour < 10 ? "Dobré ráno" : hour < 18 ? "Dobrý den" : "Dobrý večer"

  const score = rcv?.score ?? null
  const scoreLabel = rcv?.scoreLabel ?? "chybí data z hodinek"
  const scorePrev = rcv?.scorePrev ?? null
  const scoreDelta = rcv?.scoreDelta ?? null
  const deltaUp = (scoreDelta ?? 0) > 0
  const deltaDown = (scoreDelta ?? 0) < 0
  const deltaCol = deltaUp ? C.ok : deltaDown ? C.alert : C.fg2
  const scoreCol = score == null ? C.fg3 : score >= 67 ? C.ok : score >= 34 ? C.watch : C.alert
  const gated = (a?.confidence?.value ?? 0) < 0.6
  const sleepTone = rcv ? ((rcv.sleep?.debt || 0) >= 4 ? "alert" : (rcv.sleep?.debt || 0) >= 1 ? "watch" : "ok") : "muted"
  const hrvTone = rcv ? ((rcv.hrv?.z ?? 0) <= -1 ? "alert" : (rcv.hrv?.z ?? 0) < -0.3 ? "watch" : "ok") : "muted"
  const rhrTone = rcv ? ((rcv.rhr?.z ?? 0) >= 1.2 ? "alert" : (rcv.rhr?.z ?? 0) > 0.5 ? "watch" : "ok") : "muted"
  const rstd = (arr: number[]) => { if (!arr || arr.length < 2) return 0; const m = arr.reduce((s, x) => s + x, 0) / arr.length; return Math.sqrt(arr.reduce((s, x) => s + (x - m) ** 2, 0) / (arr.length - 1)) }
  // Numeric usual range = baseline ± 1 SD, so the interval bar can carry a real
  // axis (band bounds + the current value at the marker) instead of a bare dot.
  const rrow = (label: string, icon: LucideIcon, unit: string, o: any, tone: string) => {
    const series = (o?.series || []) as number[]
    const base = o?.base ?? 0, val = o?.now ?? 0
    const sd = rstd(series) || Math.max(Math.abs(base) * 0.06, 0.1)
    return { label, icon, unit, tone, valNum: val, baseNum: base, lo: base - sd, hi: base + sd }
  }
  const recoveryRows = rcv
    ? [rrow("Spánek", Moon, "h", rcv.sleep, sleepTone), rrow("HRV", HeartPulse, "ms", rcv.hrv, hrvTone), rrow("Klidový tep", Timer, "", rcv.rhr, rhrTone)]
    : undefined
  // Keep this box in sync with the Zátěž tab + quadrant: the load *axis* is a
  // composite (descent spike, high-intensity, load creep, monotony…), not just
  // ACWR — so gate the headline off the same quadrant/axis the state uses,
  // otherwise this reads "V pohodě" while the tab and quadrant say "Přetížení".
  const loadHot = a?.quadrant === "overreaching" || a?.quadrant === "critical"
  const loadStatus = !L?.valid
    ? { t: "Sbírá se historie", tone: "muted", d: "Zátěž vyhodnotíme, až naběháte pár týdnů." }
    : loadHot
      ? { t: "Zvýšená", tone: "alert", d: "Zátěž a související signály jsou nad vaší obvyklou úrovní — zvažte odlehčení a hlídejte regeneraci." }
      : (a?.load ?? 0) >= 12
        ? { t: "Mírně zvýšená", tone: "watch", d: "O něco víc než obvykle. Hlídejte spánek a regeneraci." }
        : (L.ratio ?? 1) < 0.8
          ? { t: "Nižší než obvykle", tone: "muted", d: "Objem klesl pod vaši obvyklou úroveň." }
          : { t: "V pohodě", tone: "ok", d: "Zátěž sedí na vaší obvyklé úrovni." }
  const wkly = (L?.weekly || []) as number[]
  const typicalKm = wkly.length > 1 ? Math.round(wkly.slice(0, -1).reduce((s, x) => s + x, 0) / (wkly.length - 1)) : (L?.runKm7 ?? 0)
  const signals = (a?.signals || []) as any[]

  // Alert stack — same conditions and order as before; stop-level items are always open,
  // of the rest the first is open and the others collapse (one open at a time).
  const alerts: AlertRow[] = []
  if (a?.painWarn)
    alerts.push({
      key: "pain", tone: "alert",
      title: a.painWarn.backToBack ? "Neustupující bolest — zvažte situaci" : `Nahlásil jste bolest ${a.painWarn.score}/10`,
      body: <>{a.painWarn.site && a.painWarn.site !== "—" ? `${a.painWarn.site} · ` : ""}{a.painWarn.backToBack
        ? "Stejné místo bolí opakovaně během pár dní — varovný signál přetížení. Zvažte odpočinek a konzultaci s fyzioterapeutem, než přidáte objem."
        : "Bolest nad 3/10 stojí za pozornost. Zvažte lehčí zátěž; pokud se vrátí na stejném místě, proberte to s fyzioterapeutem."}</>,
    })
  if (a?.functionLimit?.severe)
    alerts.push({
      key: "function", tone: "stop", title: "Bolest omezuje pohyb — dnes neběhat",
      body: <>{a.functionLimit.site ? `${a.functionLimit.site} · ` : ""}Omezený pohyb nebo kulhání je úroveň zranění, i když je číslo bolesti nízké. Hýbejte se jen tak, aby to nebolelo, a nechte to posoudit fyzioterapeutem do 48 hodin.</>,
    })
  if (a?.acuteOverload && !a?.functionLimit?.severe)
    alerts.push({
      key: "acute", tone: "watch", icon: Zap, title: "Akutní přetížení po běhu",
      body: <>{a.acuteOverload.reasons.join(", ")}. {a.acuteOverload.daysSince <= 1 ? "Den dva bez běhu, pak jen volně a krátce." : "Zatím jen volně a krátce, bez intenzity a dlouhého běhu."} Pokud bolest do 3 dnů neustoupí, proberte ji s fyzioterapeutem.</>,
    })
  if (a?.painMonitor?.morningWorse && !a?.functionLimit?.severe)
    alerts.push({
      key: "morning", tone: "stop", title: "Bolest je ráno horší než při běhu — dnes neběhat",
      body: <>{a.painMonitor.morningWorse.site ? `${a.painMonitor.morningWorse.site} · ` : ""}ráno {a.painMonitor.morningWorse.morning}/10, při včerejším běhu {a.painMonitor.morningWorse.during}/10. Bolest má do rána odeznít — když je horší, byla zátěž moc. Další běh kratší a volnější; pokud se to zopakuje, k fyzioterapeutovi.</>,
    })
  if (a?.painMonitor?.trend)
    alerts.push({
      key: "trend", tone: "watch", icon: TrendingUp, title: "Bolest týden od týdne roste",
      body: <>Průměr za 7 dní {a.painMonitor.trend.now.toLocaleString("cs-CZ")}/10, týden předtím {a.painMonitor.trend.before.toLocaleString("cs-CZ")}/10. Bolest nemá z týdne na týden růst — odlehčujeme: bez intenzity a dlouhého běhu, dokud se neustálí.</>,
    })
  if (a?.races?.warnings?.length > 0)
    alerts.push({
      key: "race", tone: "watch", icon: Flag,
      title: a.races.warnings.some((w: any) => w.kind === "race_day") ? "Závod na hraně zotavení" : "Závod příliš blízko jinému úsilí",
      body: <>{a.races.warnings.map((w: any, i: number) => <span key={i} className="block">{w.text}</span>)}</>,
    })
  if (a?.raceRecovery)
    alerts.push({
      key: "raceRecovery", tone: "info", icon: Flag,
      title: `Zotavení po závodním úsilí · den ${a.raceRecovery.daysSince + 1} z ${a.raceRecovery.days}`,
      body: <>{a.raceRecovery.km} km ({fmtD(a.raceRecovery.date)}: {a.raceRecovery.why.join(", ")}). {a.raceRecovery.daysSince < a.raceRecovery.restDays ? "První dny odpočinek nebo velmi volný pohyb." : "Zatím bez intenzity a dlouhého běhu."}</>,
    })
  const injuryPromptShown = !!(rid && a && !a.injury?.active && (a.functionLimit || a.painMonitor || a.acuteOverload || a.painRecurring))
  const alertCount = alerts.length + (injuryPromptShown ? 1 : 0)
  const hasStop = alerts.some((x) => x.tone === "stop")
  const worstTone = alerts.some((x) => x.tone === "alert") ? "alert" : "watch"
  const readiness: number | null = a?.capacity?.readiness ? readinessPct(a.capacity.readiness) : a?.guidance ? (a.guidance.readinessScore ?? Math.round((a.guidance.readiness ?? 1) * 100)) : null
  const panelSig = statPanel === "mech" || statPanel === "load" ? signals.filter((s: any) => (statPanel === "mech" ? MECH_IDS : LOAD_IDS).has(s.id)) : []
  const axisPoints = (axisHist || []).map((h: any) => ({ t: h.date, v: statPanel === "mech" ? h.mech : h.load }))
  if (axisPoints.length && a) axisPoints[axisPoints.length - 1] = { t: (a.computed_at || "").slice(0, 10) || axisPoints[axisPoints.length - 1].t, v: (statPanel === "mech" ? a.mech : a.load) ?? axisPoints[axisPoints.length - 1].v }
  const todayDay: OverviewDay = {
    date: (a?.computed_at || "").slice(0, 10), quadrant: a?.quadrant, overall: a?.overall ?? 0, tier: a?.tier,
    mech: a ? a.mech : null, load: a ? a.load : null, symp: a ? a.symp : null, rcv: score, readiness,
    painRecurring: a?.painRecurring ?? null, signals,
  }
  const firstCollapsible = alerts.find((x) => x.tone !== "stop")?.key ?? null
  const [openAlert, setOpenAlert] = useState<string | null | undefined>(undefined)
  const openKey = openAlert === undefined ? firstCollapsible : openAlert

  return (
    <>
      <div className="flex items-end justify-between">
        <div>
          <Label>{today}</Label>
          <h1 className="mt-1 font-serif text-[30px] tracking-[-.03em] md:text-4xl">
            {greet}, {firstName}.
          </h1>
        </div>
      </div>
      {error && !a && (
        <AlertBanner tone="alert" className="mt-5" title="Data se nepodařilo načíst"
          action={<Button size="sm" onClick={() => refresh()}>Zkusit znovu</Button>}>
          {error}
        </AlertBanner>
      )}
      <section className="card mt-6 p-4 text-fg md:p-6">
        <QuadrantHead quadrant={a?.quadrant} live={a} onSync={doSync} syncing={syncing} syncMsg={syncMsg} canSync={!!gStatus?.connected}
          alertSlot={alertCount > 0 && (
            <button type="button" onClick={() => setAlertsOpen((v) => !v)} aria-expanded={alertsOpen} aria-label={`Upozornění (${alertCount})`} title="Upozornění"
              className={`relative inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[12px] font-extrabold transition ${hasStop ? "bg-alert text-ink motion-safe:animate-pulse" : worstTone === "alert" ? "bg-alert/15 text-alert-soft ring-1 ring-alert/40" : "bg-watch/15 text-watch ring-1 ring-watch/40"}`}>
              <TriangleAlert className="size-4" aria-hidden />{alertCount}
            </button>
          )} />
        {/* feedback railway#37 — every alert sits behind the ! icon in this box */}
        {alertsOpen && alertCount > 0 && (
          <div className="mt-4 grid origin-top animate-[careReveal_.28s_ease-out] gap-2.5">
            {alerts.map((x) => (
              <AlertBanner key={x.key} tone={x.tone} icon={x.icon} title={x.title} collapsible open={x.tone === "stop" || openKey === x.key}
                onToggle={() => setOpenAlert(openKey === x.key ? null : x.key)}>{x.body}</AlertBanner>
            ))}
            <InjuryPrompt a={a} />
          </div>
        )}
        <RecommendationStrip a={a} />
        {/* „Stav" — co jde do kvadrantu — je součástí boxu s kvadrantem */}
        <div className="mt-5 border-t border-white/[.08] pt-5">
          <StateOverview d={todayDay} open={statPanel} onToggle={togglePanel} onHistory={() => setHistOpen(true)}
            note={gated && <p className="mt-3 text-[11px] text-fg-3">Mechanické signály jsou zatím umlčené — buduje se baseline ({Math.round((a?.confidence?.value ?? 0) * 100)} %).</p>}
            panel={statPanel && (
            <div className="nest origin-top animate-[careReveal_.28s_ease-out] p-3.5 md:order-last md:col-span-2 md:p-5">
              {statPanel === "symp" && <SymptomPanel signals={signals} />}
              {(statPanel === "mech" || statPanel === "load") && (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <p className="t-label">{statPanel === "mech" ? "Mechanika — trend" : "Zátěž — trend"}</p>
                    <Link to={statPanel === "mech" ? "/app/mechanics" : "/app/load"} className="inline-flex items-center gap-1 text-[12px] font-bold text-accent hover:underline">{statPanel === "mech" ? "Pohyb" : "Zátěž"}<ChevronRight className="size-3.5" aria-hidden /></Link>
                  </div>
                  <div className="grid gap-x-8 md:grid-cols-[1.3fr_1fr]">
                    <div>
                      {axisHist === null ? <p className="mt-2 text-[12px] text-fg-3">Počítám trend v čase…</p>
                        : axisPoints.length > 1 ? <AxisLineChart points={axisPoints} yMin={0} yMax={100} threshold={25} thresholdLabel="práh" color={statPanel === "mech" ? (a?.mech >= 25 ? C.alert : C.ok) : C.load} height={130} zone />
                        : <p className="mt-2 text-[12px] text-fg-3">Na trend je zatím málo historie.</p>}
                    </div>
                    <div>
                      <p className="t-label mt-3 !text-fg-3">{statPanel === "mech" ? "Co tvoří skóre mechaniky" : "Co tvoří skóre zátěže"}</p>
                      {panelSig.length ? (
                        <div className="mt-2.5 space-y-2.5">
                          {panelSig.map((s: any) => <FactorBar key={s.id} label={s.name} value={s.val} pts={s.pts} tone={statPanel === "mech" ? "info" : "load"} pct={(s.pts / Math.max(1, ...panelSig.map((x: any) => x.pts || 0))) * 100} />)}
                        </div>
                      ) : <p className="mt-2 text-[12px] text-fg-2">Nic nad vaší obvyklou úrovní — skóre je 0.</p>}
                    </div>
                  </div>
                </>
              )}
              {statPanel === "recovery" && (
                <div className="grid gap-6 md:grid-cols-2 md:gap-8">
                  {/* railway#79 — Regenerace přes noc */}
                  <div>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="flex items-center gap-1.5"><p className="t-label">Regenerace přes noc</p><InfoDot text={MI.recoveryScore} label="Regenerace přes noc" /></span>
                      {scoreDelta != null && (
                        <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-bold" style={{ background: `${deltaCol}1f`, color: deltaCol }}>
                          <span>{deltaUp ? "▲" : deltaDown ? "▼" : "▬"}</span>
                          <span>{scoreDelta > 0 ? `+${scoreDelta}` : scoreDelta < 0 ? scoreDelta : "beze změny"}</span>
                          <span className="font-medium opacity-80">{scoreDelta !== 0 ? "přes noc" : "oproti včera"}</span>
                        </span>
                      )}
                    </div>
                    <div className="mt-2 flex items-end justify-between gap-3">
                      <b className="t-num text-[40px] leading-none" style={{ color: scoreCol }}>
                        {score ?? "—"}
                        <small className="ml-1 text-sm font-semibold tracking-normal text-fg-3">/ 100</small>
                      </b>
                      <span className="pb-1 text-right text-[14px] font-bold text-fg">{scoreLabel}</span>
                    </div>
                    <div className="relative mt-4 h-3 overflow-hidden rounded-full bg-white/[.07]">
                      <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${clamp(score ?? 0, 0, 100)}%`, background: `${scoreCol}88` }} />
                      {scorePrev != null && !!scoreDelta && (
                        <i className="absolute inset-y-0" style={{ left: `${clamp(Math.min(score ?? 0, scorePrev), 0, 100)}%`, width: `${Math.abs((score ?? 0) - scorePrev)}%`, background: deltaCol, opacity: 0.85 }} />
                      )}
                      {scorePrev != null && <i className="absolute inset-y-0 w-0.5 bg-fg" style={{ left: `calc(${clamp(scorePrev, 0, 100)}% - 1px)` }} />}
                      <i className="absolute inset-y-0 left-1/4 w-px bg-bg/60" />
                      <i className="absolute inset-y-0 left-1/2 w-px bg-bg/60" />
                      <i className="absolute inset-y-0 left-3/4 w-px bg-bg/60" />
                    </div>
                    <div className="mt-2 flex justify-between text-[11px] text-fg-3"><span>nízká</span><span>vyvážená</span><span>plná</span></div>
                    {scorePrev != null && (
                      <p className="mt-2 text-[12px] text-fg-3">
                        <span className="mr-1 inline-block h-2 w-0.5 translate-y-px bg-fg" /> včera {scorePrev}
                        {scoreDelta ? <> · <span style={{ color: deltaCol }}>{deltaUp ? "regenerace přes noc stoupla" : "regenerace přes noc klesla"} o {Math.abs(scoreDelta)}</span></> : " · přes noc beze změny"}
                      </p>
                    )}
                    {rcv && (
                      <div className="mt-4 flex items-center gap-3 border-t border-white/[.08] pt-3.5 text-[13px]">
                        <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-info/15 text-info"><Moon className="size-4" aria-hidden /></span>
                        <span><b>HRV {rcv.hrv?.now} ms</b><small className="ml-2 text-[12px] text-fg-2">baseline {rcv.hrv?.base} ms · spánek {rcv.sleep?.now} h</small></span>
                      </div>
                    )}
                  </div>
                  {/* railway#80 — Regenerace vs. norma */}
                  <div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="t-label">Regenerace vs. norma</p>
                      <WeeklyCheckButton />
                    </div>
                    <RecoveryRanges rows={recoveryRows} />
                  </div>
                </div>
              )}
              {statPanel === "readiness" && (
                <div>
                  {/* railway#81 — Připravenost opens the training load: why readiness is what it is, the weeks, today vs. the 7-day room */}
                  {a?.capacity?.readiness && <Readiness r={a.capacity.readiness} />}
                  <div className="mt-4 grid gap-6 md:grid-cols-2 md:gap-8">
                    <div>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="t-label">Tréninková zátěž</p>
                          <h2 className="mt-1 font-serif text-2xl">{loadStatus.t}</h2>
                        </div>
                        <Chip tone={loadStatus.tone as any}>tento týden</Chip>
                      </div>
                      <p className="mt-1 text-[13px] text-fg-2">{loadStatus.d}</p>
                      <p className="t-label mt-4 !text-fg-3">Kilometry po kalendářních týdnech (Po–Ne)</p>
                      {/* railway#82 — same colours as the weekly volume chart on Zátěž */}
                      {wkly.length ? <><Bars vals={wkly.map((v) => Math.round(v))} tones={weekTones(wkly)} /><WeekToneLegend /></>
                        : <p className="mt-3 text-[12px] text-fg-3">Zatím není dost dat pro týdenní přehled.</p>}
                      <div className="mt-3 grid grid-cols-3 gap-2 text-[12px] text-fg-2">
                        <span>Tento týden <small className="text-fg-3">(Po–Ne)</small> <b className="t-num block text-[18px] text-fg">{L?.weekKm ?? "—"} km</b></span>
                        <span>Posledních 7 dní <b className="t-num block text-[18px] text-fg">{L?.runKm7 ?? "—"} km</b></span>
                        <span className="text-right">Obvykle / týden <b className="t-num block text-[18px] text-fg">{typicalKm} km</b></span>
                      </div>
                    </div>
                    <div>
                      {a?.capacity ? <CapacityMini cap={a.capacity} week={a?.guidance?.week?.channels} className="border-t border-white/10 pt-4 md:border-t-0 md:pt-0" /> : <p className="text-[12px] text-fg-3">Kapacitu zatím poznáváme.</p>}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )} />
        </div>
        {histOpen && <QuadrantHistory history={quadHist} today={todayDay} onClose={() => setHistOpen(false)} />}
      </section>
    </>
  )
}

// railway#78 — what drives the state as an inverted pyramid: the biggest impact on top
// and widest, each lower row narrower.
function ImpactPyramid({ signals, tone }: { signals: any[]; tone: (g: string) => "alert" | "watch" | "ok" }) {
  const top = [...signals].sort((x, y) => (y.pts || 0) - (x.pts || 0)).slice(0, 4)
  const n = top.length
  const maxPts = Math.max(1, top[0]?.pts || 0)
  return (
    <div className="mt-3 flex flex-col items-center gap-1.5">
      {top.map((s, i) => {
        const col = toneCol(tone(s.grade))
        const w = n > 1 ? 100 - (i * 44) / (n - 1) : 100
        return (
          <div key={s.id} className="relative overflow-hidden rounded-[12px] border px-3 py-2 text-center" style={{ width: `${w}%`, borderColor: `${col}55`, background: `${col}14` }}
            title={`${s.name}${s.val ? ` · ${s.val}` : ""}${s.pts != null ? ` · ${s.pts} b` : ""}`}>
            <i className="absolute inset-y-0 left-0" style={{ width: `${((s.pts || 0) / maxPts) * 100}%`, background: `${col}1c` }} aria-hidden />
            <span className="relative flex items-center justify-center gap-1.5">
              {s.grade && <span className="grid size-[18px] shrink-0 place-items-center rounded-full text-[10px] font-extrabold" style={{ background: `${col}30`, color: col }}>{s.grade}</span>}
              <span className="min-w-0 text-balance text-[12.5px] font-semibold leading-4 text-fg">{s.name}</span>
            </span>
            {s.val && <span className="relative mt-0.5 block truncate tabular-nums text-[11px] text-fg-2">{s.val}</span>}
          </div>
        )
      })}
      <div className="mt-1 flex w-full justify-between text-[10px] font-bold uppercase tracking-[.1em] text-fg-3"><span>↑ největší vliv</span><span>nejmenší ↓</span></div>
    </div>
  )
}
function RunnerPage() {
  const { tab } = useParams()
  switch (tab) {
    case "post":
      return <Post />
    case "mechanics":
      return <Mechanics />
    case "load":
      return <LoadTab />
    case "training":
      return <Training />
    case "program":
      return <Navigate to="/app/messages" replace />
    case "messages":
      return <Care />
    default:
      return <TodayV2 />
  }
}
function DataPage() {
  return <DataView />
}
function Auth() {
  const nav = useNavigate()
  const { reloadMe } = useApp()
  const role = "runner" // runner-only sign-in
  // New visitors land on sign-up; they can switch to sign-in via the toggle.
  const [mode, setMode] = useState<"login" | "register">("register")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    setErr(null)
    if (!email.trim() || !password) {
      setErr("Vyplňte e-mail a heslo.")
      return
    }
    if (mode === "register" && password.length < 8) {
      setErr("Heslo musí mít alespoň 8 znaků.")
      return
    }
    setBusy(true)
    try {
      if (mode === "register") {
        await api.authRegister({ email, password, name: name || email, role })
      }
      await api.authSignIn(email, password, role)
      const me = await reloadMe()
      nav(roleHome(me?.role || role))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Přihlášení selhalo")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="motion-shell min-h-screen bg-bg p-5 md:grid md:grid-cols-2 md:gap-8 md:p-8">
      <aside className="card relative hidden overflow-hidden p-10 text-fg md:flex md:flex-col" style={{ backgroundImage: `radial-gradient(circle at 85% 12%, ${C.accent}1a, transparent 22rem), radial-gradient(circle at 10% 90%, ${C.info}14, transparent 20rem)` }}>
        <div className="flex items-center gap-2.5 text-lg font-extrabold tracking-[-.04em]">
          <Mark />
          došlap
        </div>
        <div className="my-auto">
          <Label>Bezpečný přístup</Label>
          <h1 className="mt-4 max-w-md font-serif text-5xl leading-[1.02] tracking-[-.02em]">
            Změny ve vaší zátěži a mechanice vidíte včas.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-6 text-fg-soft">
            Aplikace pro běžce — sledování zátěže, regenerace a běžecké
            mechaniky proti vaší vlastní baseline.
          </p>
        </div>
      </aside>
      <section className="mx-auto flex w-full max-w-md flex-col justify-center py-8">
        <span className="mb-10 flex items-center gap-2.5 text-lg font-extrabold tracking-[-.04em] md:hidden">
          <Mark />
          došlap
        </span>
        <Label>Přístup pro běžce</Label>
        <h1 className="mt-1 font-serif text-[34px] tracking-[-.03em] md:text-4xl">
          {mode === "login" ? "Přihlášení" : "Nová registrace"}
        </h1>
        <Card className="mt-5">
          <p className="font-serif text-xl">
            {mode === "login" ? "Přihlásit se" : "Registrovat se"}
          </p>
          {mode === "register" && (
            <input
              className="mt-5 w-full rounded-xl border px-3.5 py-3 text-sm"
              aria-label="Jméno"
              autoComplete="name"
              placeholder="Jméno"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
          <input
            className="mt-3 w-full rounded-xl border px-3.5 py-3 text-sm"
            aria-label="E-mail"
            type="email"
            autoComplete="email"
            placeholder="E-mail"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password"
            className="mt-3 w-full rounded-xl border px-3.5 py-3 text-sm"
            aria-label="Heslo"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            placeholder="Heslo"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          {mode === "register" && <p className="mt-2 text-[11px] text-fg-2">Heslo alespoň 8 znaků.</p>}
          {err && <p role="alert" className="mt-3 text-[13px] font-bold text-alert">{err}</p>}
          <button
            onClick={submit}
            disabled={busy}
            className="btn btn-primary mt-5 w-full py-3 text-sm"
          >
            {busy ? "Přihlašuji…" : mode === "login" ? "Přihlásit se" : "Vytvořit účet"}
          </button>
          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login")
              setErr(null)
            }}
            className="mt-3 w-full text-center text-[13px] font-bold text-fg-2 hover:text-accent"
          >
            {mode === "login" ? "Nemáte účet? Registrovat se" : "Už máte účet? Přihlásit se"}
          </button>
        </Card>
      </section>
    </div>
  )
}
const STEP_TITLE = ["Jak se dnes cítí tělo?", "Kde to bolí?", "Ještě něco?"]
const STEP_SHORT = ["Pocity", "Bolest", "Poznámka"]
function AtlasBubble() {
  const [open, setOpen] = useState(false)
  const [score, setScore] = useState<number | null>(null)
  const [pain, setPain] = useState(0)
  const [soreness, setSoreness] = useState(1)
  const [fatigue, setFatigue] = useState(2)
  const [note, setNote] = useState("")
  const [points, setPoints] = useState<BodyPoint[]>([])
  const [fn, setFn] = useState<{ limits_movement: boolean; run_modified: boolean; limping: boolean }>({ limits_movement: false, run_modified: false, limping: false })
  const [step, setStep] = useState(1)
  useEffect(() => { if (open) setStep(1) }, [open])
  // Step 2 (where it hurts) is only asked when there is pain; otherwise it's skipped.
  const next = () => setStep((st) => (st === 1 ? (pain > 0 ? 2 : 3) : 3))
  const back = () => setStep((st) => (st === 3 ? (pain > 0 ? 2 : 1) : 1))
  const { me, boot, refresh } = useApp()
  const rid = me?.runner_id
  const rcv = boot?.assessment?.rcv
  const L = boot?.assessment?.loadDetail
  const { busy, run } = useAsync()
  const toast = useToast()
  const bodySignals: [string, number, (value: number) => void, string][] = [
    ["Bolest", pain, setPain, "žádná"],
    ["Svalová ztuhlost", soreness, setSoreness, "lehká"],
    ["Únava", fatigue, setFatigue, "mírná"],
  ]
  const save = () =>
    run(async () => {
      if (!rid) return
      // as before: the body map only counts while pain > 0 (it was hidden at 0)
      const pts = (pain > 0 ? points : []).map((p) => ({ region: p.region, side: p.side || null, type: p.kind }))
      const hurts = pain > 0 || pts.length > 0
      await api.checkin(rid, {
        pain_score: pain, soreness, stress: fatigue, mood: score, notes: note || null,
        pain_points: pts, pain_site: pts.length ? pts.map((p) => p.region).join(", ") : null,
        ...(hurts ? fn : {}),
      })
      setFn({ limits_movement: false, run_modified: false, limping: false })
      toast({ title: "Check-in uložen" })
      refresh()
      setOpen(false)
    })
  return (
    <>
      {!open && (
        // Check-in FAB, parked in the bottom-right corner just above the mobile
        // nav. The earlier full-height side rail sat vertically centered over the
        // right edge and *covered* the right ~40px of every page's content (cards
        // and text looked cut off); a corner pill keeps it out of the content
        // column entirely.
        <button
          onClick={() => setOpen(true)}
          aria-label="Otevřít check-in"
          className="fixed right-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-[55] flex items-center gap-2 rounded-full bg-accent py-3 pl-3 pr-4 text-sm font-extrabold text-ink shadow-[0_12px_30px_rgb(0_0_0_/_0.45),0_0_0_1px_rgb(0_0_0_/_0.1)] hover:brightness-105 md:bottom-7 md:right-7"
        >
          <span className="grid size-6 place-items-center rounded-full bg-ink/10"><Heart className="size-4" strokeWidth={2.4} aria-hidden /></span>
          <span className="whitespace-nowrap">Check-in</span>
        </button>
      )}
      {open && (
        <div
          data-auto-reveal
          role="dialog"
          aria-label="Denní check-in"
          className="fixed inset-x-0 bottom-[calc(4.4rem+env(safe-area-inset-bottom))] z-[70] mx-auto flex max-h-[calc(100dvh-6rem)] max-w-[480px] flex-col overflow-hidden rounded-t-[28px] border border-white/10 bg-raised text-fg shadow-[0_24px_60px_rgb(0_0_0_/_0.5)] md:bottom-7 md:right-7 md:left-auto md:rounded-[26px]"
        >
          <div className="shrink-0 px-5 pt-5">
            <div className="flex justify-between gap-3">
              <div>
                <p className="t-label">Denní check-in · krok {step} ze 3</p>
                <h2 className="mt-1 font-serif text-[24px] leading-tight">{STEP_TITLE[step - 1]}</h2>
              </div>
              <button onClick={() => setOpen(false)} aria-label="Zavřít check-in" className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 text-fg-2 hover:text-fg">
                <X className="size-4" aria-hidden />
              </button>
            </div>
            {/* OPT-3: three steps — feelings → where it hurts → note (same payload as before) */}
            <div className="mt-3 grid grid-cols-3 gap-1.5" aria-hidden>
              {[1, 2, 3].map((n) => (
                <span key={n} className="grid gap-1">
                  <i className={`block h-1 rounded-full ${n <= step ? "bg-accent" : "bg-white/[.1]"} ${n === 2 && pain === 0 && step === 3 ? "opacity-40" : ""}`} />
                  <span className={`text-[11px] font-semibold ${n === step ? "text-fg" : "text-fg-3"}`}>{STEP_SHORT[n - 1]}{n === 2 && pain === 0 && step > 1 ? " · přeskočeno" : ""}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-2 pt-4" style={{ overscrollBehavior: "contain" }}>
            {/* step 1 — feelings */}
            <div className={step === 1 ? "" : "hidden"}>
              <p className="t-label">Nálada</p>
              <div className="mt-2 grid grid-cols-5 gap-2">
                {[
                  ["😣", "těžká"],
                  ["😕", "nejistá"],
                  ["😐", "neutrální"],
                  ["🙂", "dobrá"],
                  ["😄", "skvělá"],
                ].map(([face, label], index) => (
                  <button
                    onClick={() => setScore(index)}
                    key={face}
                    aria-label={`Nálada: ${label}`}
                    aria-pressed={score === index}
                    className={`flex aspect-square flex-col items-center justify-center rounded-[16px] border text-xl transition ${
                      score === index ? "border-accent bg-accent/15" : "border-white/[.08] bg-white/[.04] hover:border-white/20"
                    }`}
                  >
                    {face}
                    <span className="mt-1 text-[11px] text-fg-2">{label}</span>
                  </button>
                ))}
              </div>
              <div className="nest mt-5 space-y-5 p-4">
                <div className="flex items-center justify-between">
                  <p className="t-label">Tělesné pocity</p>
                  <span className="text-[11px] text-fg-3">0 nic 10 silné</span>
                </div>
                {bodySignals.map(([label, value, setValue, low]) => {
                  const isPain = label === "Bolest"
                  const col = isPain ? (value >= 4 ? C.alert : value >= 1 ? C.watch : C.ok) : C.accent
                  return (
                    <div key={label}>
                      <div className="mb-1 flex justify-between text-[13px]">
                        <span className="font-semibold">{label}</span>
                        <b className="tabular-nums" style={{ color: col }}>{value}/10</b>
                      </div>
                      <input
                        aria-label={label}
                        type="range"
                        min="0"
                        max="10"
                        value={value}
                        onChange={(event) => setValue(Number(event.target.value))}
                        className="range"
                        style={{ ["--fill" as any]: `${value * 10}%`, ["--fill-color" as any]: col }}
                      />
                      <div className="mt-0.5 flex justify-between text-[11px] text-fg-3">
                        <span>{low}</span>
                        <span>silné</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
            {/* step 2 — where it hurts (only asked when pain > 0) */}
            <div className={step === 2 ? "" : "hidden"}>
              <div className="nest p-4">
                <div className="flex items-center justify-between">
                  <p className="t-label">Kde to bolí</p>
                  <span className="text-[11px] text-fg-3">bolest {pain}/10</span>
                </div>
                <p className="mt-1 text-[12px] text-fg-3">Klepněte na místa, která bolí — můžete vybrat víc.</p>
                <div className="mt-3"><MuscleAnatomy multi onSelect={setPoints} /></div>
              </div>
              <div className="nest mt-4 p-4">
                <p className="t-label">Co bolest dělá</p>
                <p className="mt-1 text-[12px] text-fg-3">Důležitější než číslo — omezený pohyb je úroveň zranění i při nízké bolesti.</p>
                <div className="mt-3 space-y-2">
                  {([["limits_movement", "Omezuje mě v běžném pohybu nebo při chůzi"], ["limping", "Kulhám"], ["run_modified", "Kvůli bolesti jsem zkrátil(a) nebo upravil(a) běh"]] as const).map(([k, label]) => (
                    <button key={k} type="button" role="switch" aria-checked={fn[k]} onClick={() => setFn((p) => ({ ...p, [k]: !p[k] }))}
                      className={`flex w-full items-center justify-between gap-3 rounded-[12px] border px-3 py-2.5 text-left text-[13px] transition ${fn[k] ? "border-alert/60 bg-alert/12 text-alert-soft" : "border-white/10 text-fg-soft hover:border-white/20"}`}>
                      <span>{label}</span>
                      <span className={`relative h-6 w-10 shrink-0 rounded-full transition ${fn[k] ? "bg-alert" : "bg-white/15"}`}><i className={`absolute top-[3px] size-[18px] rounded-full transition-all ${fn[k] ? "left-[19px] bg-ink" : "left-[3px] bg-fg-2"}`} /></span>
                    </button>
                  ))}
                </div>
                {(fn.limits_movement || fn.limping) && (
                  <p className="mt-3 rounded-[12px] border border-alert/40 bg-alert/10 p-3 text-[12px] leading-5 text-alert-soft">Bolest, která omezuje pohyb, je signál zranění — dnes neběhejte a nechte to posoudit fyzioterapeutem (do 48 hodin).</p>
                )}
              </div>
              {pain > 3 && (
                <div className="mt-4 rounded-[16px] border border-alert/40 bg-alert/10 p-4 text-alert-soft">
                  <p className="flex items-center gap-2 text-sm font-bold"><TriangleAlert className="size-4" aria-hidden />Bolest {pain}/10 — zvažte situaci</p>
                  <p className="mt-1 text-[12px] leading-5">Bolest nad 3/10 není jen diskomfort. Zvažte odpočinek nebo lehčí zátěž, a pokud se ozve i u dalšího běhu na stejném místě, raději to proberte s fyzioterapeutem, než přidáte objem.</p>
                </div>
              )}
            </div>
            {/* step 3 — note + context */}
            <div className={step === 3 ? "" : "hidden"}>
              <label className="block">
                <span className="t-label">Poznámka</span>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Co by měl váš fyzioterapeut vědět?"
                  className="mt-2 min-h-24 w-full rounded-[12px] border p-3 text-sm text-fg"
                />
              </label>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="nest px-2 py-2.5">
                  <b className="t-num block text-[18px] text-fg">{rcv?.score ?? "—"}<small className="text-[11px] font-semibold text-fg-3">/100</small></b>
                  <span className="mt-1 block text-[11px] text-fg-2">regenerace</span>
                  <span className="mt-1 block text-[11px]" style={{ color: (rcv?.scoreDelta ?? 0) > 0 ? C.ok : (rcv?.scoreDelta ?? 0) < 0 ? C.alert : C.fg3 }}>
                    {rcv?.scoreDelta == null ? (rcv?.scoreLabel || "—") : rcv.scoreDelta === 0 ? "beze změny" : `${rcv.scoreDelta > 0 ? "+" : ""}${rcv.scoreDelta} přes noc`}
                  </span>
                </div>
                <div className="nest px-2 py-2.5">
                  <b className="t-num block text-[18px] text-fg">{rcv?.sleep?.now ?? "—"}<small className="text-[11px] font-semibold text-fg-3"> h</small></b>
                  <span className="mt-1 block text-[11px] text-fg-2">spánek</span>
                  <span className="mt-1 block text-[11px] text-fg-3">obvykle {rcv?.sleep?.base ?? "—"} h</span>
                </div>
                <div className="nest px-2 py-2.5">
                  <b className="t-num block text-[18px] text-fg">{L?.valid ? `×${L.ratio}` : "—"}</b>
                  <span className="mt-1 block text-[11px] text-fg-2">poměr zátěže</span>
                  <span className="mt-1 block text-[11px] text-fg-3">{L?.valid ? "7:28 dní · vč. sportu" : "zatím málo dat"}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 gap-2 border-t border-white/[.08] bg-raised px-5 py-3.5">
            {step > 1 && <button onClick={back} className="btn btn-outline px-5 py-3 text-sm"><ChevronLeft className="size-4" aria-hidden />Zpět</button>}
            {step < 3 ? (
              <button onClick={next} className="btn btn-primary flex-1 py-3 text-sm">Pokračovat<ChevronRight className="size-4" aria-hidden /></button>
            ) : (
              <button onClick={save} disabled={busy} className="btn btn-primary flex-1 py-3 text-sm">{busy ? "Ukládám…" : "Uložit check-in"}</button>
            )}
          </div>
        </div>
      )}
    </>
  )
}
function AtlasNav() {
  const { pathname } = useLocation()
  const navItems = useRunnerNav()
  // Single source of truth = runnerNav, so the mobile bar can never drift from
  // the desktop tabs again (previously missing "Deník" and in wrong order).
  return (
    <nav aria-label="Hlavní navigace" className="fixed inset-x-0 bottom-0 z-50 flex border-t border-white/[.08] bg-ink/95 px-1.5 pb-[max(.7rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur-md md:hidden">
      {navItems.map(([id, label]) => {
        const to = `/app/${id}`
        const on = pathname === to || pathname.startsWith(to + "/")
        const Icon = NAV_ICON[id]
        return (
          <Link
            key={id}
            to={to}
            aria-current={on ? "page" : undefined}
            className={`flex min-h-[48px] flex-1 flex-col items-center justify-center gap-1 text-[11px] font-bold ${on ? "text-accent" : "text-fg-3"}`}
          >
            <span className={`grid h-[26px] w-10 place-items-center rounded-full transition-colors ${on ? "bg-accent/[.14]" : ""}`}>
              {Icon ? <Icon className="size-[19px]" strokeWidth={on ? 2.4 : 2} aria-hidden /> : "•"}
            </span>
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
// Dev-only component gallery (/ui) — tree-shaken out of production builds.
const DevGallery = import.meta.env.DEV ? lazy(() => import("@/dev/Gallery")) : null
const router = createBrowserRouter([
  ...(DevGallery ? [{ path: "/ui", Component: () => <Suspense fallback={null}><DevGallery /></Suspense> }] : []),
  { path: "/", Component: () => <Navigate to="/app/today" replace /> },
  { path: "/auth", Component: Auth },
  {
    Component: Layout,
    children: [
      { path: "/app/:tab", Component: RunnerPage },
      { path: "/app/post/:aid", Component: RunDetail },
      { path: "/data", Component: DataPage },
      { path: "/engine", Component: EngineLab },
      { path: "/engines", Component: EngineCompare },
    ],
  },
])
export default function App() {
  useDynamicReveal()
  return (
    <AppProvider>
      <ToastHost>
        <RouterProvider router={router} />
      </ToastHost>
    </AppProvider>
  )
}
