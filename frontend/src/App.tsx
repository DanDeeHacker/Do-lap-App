import { useEffect, useRef, useState } from "react"
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
import MuscleAnatomy, { type BodyPoint } from "@/components/MuscleAnatomy"
import { api, ApiError } from "@/api"
import { AppProvider, useApp } from "@/store"
import { clamp, initials, QUAD, roleHome } from "@/lib"
import { Field, InfoDot, Sheet, ToastHost, useAsync, useToast } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { Load as LoadTab, Mechanics, Post } from "@/tabs"
import { Care, WeeklyCheckButton } from "@/care"
import { DataView } from "@/datapage"
import { EngineLab } from "@/enginelab"
import { CapacityMini } from "@/capacity"
import { Training } from "@/training"
import { startUpdateWatcher } from "@/updateCheck"
import { AnnotateProvider, AnnotateToggle, AnnotationLayer } from "@/annotate"

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

function Mark() {
  return (
    <span className="grid size-9 place-items-center rounded-xl bg-[#071313]">
      <svg viewBox="0 0 64 64" className="size-7" aria-hidden="true">
        <circle cx="32" cy="32" r="28" fill="none" stroke="#c7ff54" strokeWidth="2" strokeOpacity=".5" />
        <path d="M12 44 C12 34 19 13 37 13 C49 13 56 23 56 34 C56 46 45 54 34 54 C24 54 14 52 12 44 Z" fill="#c7ff54" />
        <path d="M27 42 C27 36 31 23 41 23 C48 23 52 29 52 35 C52 42 45 47 38 47 C31 47 28 46 27 42 Z" fill="#071313" />
      </svg>
    </span>
  )
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
    <header className="fixed inset-x-0 top-0 z-40 border-b border-[#dfe2da]/80 bg-[#f9f7f1]/95 pt-[env(safe-area-inset-top)] backdrop-blur">
      <div className="mx-auto flex h-[68px] max-w-[1180px] items-center justify-between gap-4 px-5">
        <Link to="/app/today" className="flex shrink-0 items-center gap-2.5 text-lg font-bold tracking-[-.04em]">
          <Mark />
          <span className="hidden sm:inline">došlap</span>
        </Link>
        <nav className="hidden flex-1 items-center justify-center gap-1 md:flex">
          {navItems.map(([id, label]) => {
            const to = `/app/${id}`
            const active = pathname === to
            return (
              <Link
                key={id}
                to={to}
                className={`rounded-full px-3.5 py-1.5 text-[13px] font-bold transition ${
                  active ? "bg-[#c7ff54] text-[#071313]" : "text-[#58716b] hover:text-[#c7ff54]"
                }`}
              >
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="relative flex shrink-0 items-center gap-2">
          <AnnotateToggle />
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="grid size-9 place-items-center rounded-full bg-[#dcece7] text-[10px] font-bold text-black"
            aria-expanded={profileOpen}
            aria-label="Otevřít profil"
          >
            {ini}
          </button>
          {profileOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setProfileOpen(false)} />
              <div className="absolute right-0 top-12 z-20 w-72 origin-top animate-[careReveal_.28s_ease-out] rounded-2xl border border-white/10 bg-[#102724] p-4 text-[#f1f8f1] shadow-2xl">
                <div className="flex items-center gap-3">
                  <span className="grid size-10 place-items-center rounded-full bg-[#c7ff54] text-xs font-bold text-[#071313]">{ini}</span>
                  <div>
                    <b>{me?.name}</b>
                    <p className="text-[10px] text-[#91b7a9]">běžecký profil</p>
                  </div>
                </div>
                <div className="mt-4 border-t border-white/10 pt-3 text-xs text-[#a9c2b9]">
                  <p>{boot?.integration?.status === "connected" ? "Zdroj dat připojen" : "Data zatím nepřipojena"}</p>
                  {runner?.goal_race && <p className="mt-1">Cíl: {runner.goal_race}</p>}
                </div>
                <div className="mt-3 grid gap-1.5">
                  <button onClick={() => { setProfileOpen(false); setEditOpen(true) }} className="rounded-xl bg-white/[.05] px-3 py-2 text-left text-xs font-bold hover:bg-white/[.09]">Upravit profil</button>
                  <Link to="/data" onClick={() => setProfileOpen(false)} className="rounded-xl bg-white/[.05] px-3 py-2 text-left text-xs font-bold hover:bg-white/[.09]">Data a připojení</Link>
                  <Link to="/engine" onClick={() => setProfileOpen(false)} className="rounded-xl bg-white/[.05] px-3 py-2 text-left text-xs font-bold hover:bg-white/[.09]">Citlivostní analýza</Link>
                </div>
                <button
                  onClick={async () => { setProfileOpen(false); await logout(); nav("/auth") }}
                  className="mt-3 block w-full rounded-full bg-[#c7ff54] px-3 py-2 text-center text-xs font-bold text-[#071313]"
                >
                  Odhlásit se
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
        prior_injury: r.prior_injury ?? "", prior_injury_months_ago: r.prior_injury_months_ago ?? "",
      })
  }, [open, r])
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }))
  const save = () =>
    run(async () => {
      await api.updateProfile(me!.runner_id!, {
        ...f,
        birth_year: f.birth_year ? Number(f.birth_year) : null,
        prior_injury_months_ago: f.prior_injury_months_ago !== "" ? Number(f.prior_injury_months_ago) : null,
        goal_date: f.goal_date || null,
        prior_injury: f.prior_injury || null,
      })
      await refresh()
      onClose()
    })
  const inp = "w-full rounded-xl border px-3 py-2.5 text-sm"
  return (
    <Sheet open={open} onClose={onClose}>
      <h2 className="font-serif text-2xl">Upravit profil</h2>
      <p className="mt-1 text-xs text-[#a9c2b9]">Údaje, které používá engine (dřívější zranění, cílový závod) a fyzioterapeut (věk, pohlaví, město).</p>
      <div className="grid gap-1 md:grid-cols-2">
        <Field label="Rok narození"><input className={inp} inputMode="numeric" value={f.birth_year ?? ""} onChange={(e) => set("birth_year", e.target.value)} /></Field>
        <Field label="Pohlaví"><select className={inp} value={f.sex ?? ""} onChange={(e) => set("sex", e.target.value)}><option value="">—</option><option value="f">žena</option><option value="m">muž</option></select></Field>
        <Field label="Město"><input className={inp} value={f.city ?? ""} onChange={(e) => set("city", e.target.value)} /></Field>
        <Field label="Hodinky / zařízení"><input className={inp} value={f.device ?? ""} onChange={(e) => set("device", e.target.value)} /></Field>
        <Field label="Cílový závod"><input className={inp} value={f.goal_race ?? ""} onChange={(e) => set("goal_race", e.target.value)} placeholder="např. Pražský půlmaraton" /></Field>
        <Field label="Datum závodu"><input type="date" className={inp} value={f.goal_date ?? ""} onChange={(e) => set("goal_date", e.target.value)} /></Field>
        <Field label="Dřívější zranění"><input className={inp} value={f.prior_injury ?? ""} onChange={(e) => set("prior_injury", e.target.value)} placeholder="např. Achillova šlacha" /></Field>
        <Field label="Před kolika měsíci"><input className={inp} inputMode="numeric" value={f.prior_injury_months_ago ?? ""} onChange={(e) => set("prior_injury_months_ago", e.target.value)} /></Field>
      </div>
      {err && <p className="mt-3 text-xs font-bold text-[#e77a59]">{err}</p>}
      <div className="mt-5 flex gap-2">
        <button onClick={save} disabled={busy} className="flex-1 rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-60">{busy ? "Ukládám…" : "Uložit profil"}</button>
        <button onClick={onClose} className="rounded-full border border-white/15 px-5 py-3 text-sm font-bold text-[#a9c2b9]">Zavřít</button>
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
function Layout() {
  const { me, loading } = useApp()
  // New deployments: reload when the app returns to the foreground, or offer a
  // reload if one lands while it's in use (home-screen apps never reload alone).
  const [updateReady, setUpdateReady] = useState(false)
  useEffect(() => startUpdateWatcher(() => setUpdateReady(true)), [])
  if (loading)
    return (
      <div className="motion-shell grid min-h-screen place-items-center bg-[#e7e9e1] text-[#a9c2b9]">
        <span className="font-mono text-xs uppercase tracking-[.2em]">načítám…</span>
      </div>
    )
  if (!me) return <Navigate to="/auth" replace />
  if (me.role !== "runner") return <RunnerOnlyNotice />
  return (
    <AnnotateProvider>
      <div className="motion-shell min-h-screen bg-[#e7e9e1] text-[#193431]">
        <Topbar />
        <main className="mx-auto min-h-screen max-w-[1180px] bg-[#f9f7f1] px-5 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-[calc(6rem+env(safe-area-inset-top))] md:rounded-b-[28px] md:px-9 md:pb-24 md:pt-24">
          <Outlet />
        </main>
        <AtlasBubble />
        <AtlasNav />
        {updateReady && (
          <div className="fixed inset-x-0 top-[calc(76px+env(safe-area-inset-top))] z-50 flex justify-center px-4">
            <div className="flex items-center gap-3 rounded-full border border-[#c7ff54]/40 bg-[#0c201d] py-2 pl-4 pr-2 text-xs text-[#f1f8f1] shadow-lg">
              <span>Je dostupná nová verze aplikace.</span>
              <button onClick={() => location.reload()} className="rounded-full bg-[#c7ff54] px-3 py-1.5 font-bold text-[#071313]">Aktualizovat</button>
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
    <div className="motion-shell grid min-h-screen place-items-center bg-[#e7e9e1] p-6 text-[#193431]">
      <div className="max-w-md rounded-[28px] bg-[#f9f7f1] p-8 text-center">
        <div className="mx-auto flex w-fit items-center gap-2 font-bold"><Mark /> došlap</div>
        <h1 className="mt-6 font-serif text-3xl">Zatím jen pro běžce</h1>
        <p className="mt-3 text-sm leading-6 text-[#64736e]">
          Účet <b>{me?.email}</b> má roli „{me?.role}". Rozhraní pro fyzioterapeuty a partnery se teprve připravuje —
          přihlaste se prosím běžeckým účtem.
        </p>
        <button onClick={logout} className="mt-6 rounded-full bg-[#c7ff54] px-5 py-2.5 text-sm font-bold text-[#071313]">Odhlásit se</button>
      </div>
    </div>
  )
}
function Label({ children }: { children: string }) {
  return (
    <p className="font-mono text-[10px] font-medium uppercase tracking-[.16em] text-[#a8c7bd]">
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
      className={`group rounded-[24px] border border-[#dfe2da] bg-white p-5 transition duration-200 hover:-translate-y-0.5 hover:border-[#235e59]/45 hover:shadow-[0_14px_34px_rgb(15_40_36_/_0.12)] ${className}`}
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
    <Card className={warm ? "border-0 bg-[#235e59] text-[#f8f7f1]" : ""}>
      <Label>{label}</Label>
      <p
        className={`mt-4 font-serif text-4xl tracking-[-.07em] ${
          warm ? "text-white" : ""
        }`}
      >
        {value}
      </p>
      <p
        className={`mt-2 text-xs ${warm ? "text-[#c9dfd8]" : "text-[#6b7b76]"}`}
      >
        {caption}
      </p>
    </Card>
  )
}
function NumberedChart({ vals }: { vals?: number[] }) {
  const [act, setAct] = useState<number | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  // No invented bars: until real weekly km arrive (boot loading / no loadDetail),
  // show an honest empty state instead of a hardcoded fake series.
  const volume = (vals || []).map((v) => Math.round(v))
  const n = volume.length
  if (!n)
    return (
      <div className="mt-7 grid h-32 place-items-center rounded-xl border border-dashed border-[#dae2dd] text-xs text-[#71837b]">
        Zatím není dost dat pro týdenní přehled.
      </div>
    )
  const mx = Math.max(...volume, 1)
  const lab = (i: number) => (i === n - 1 ? "tento týden" : `−${n - 1 - i} t`)
  const pick = (clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setAct(Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left) / r.width) * n))))
  }
  return (
    <div
      ref={wrapRef}
      className="relative mt-7 flex h-32 select-none items-end gap-1.5 border-b border-[#dae2dd] pb-1"
      style={{ touchAction: "pan-y" }}
      onPointerMove={(e) => pick(e.clientX)}
      onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId); pick(e.clientX) }}
      onPointerUp={() => setAct(null)}
      onPointerCancel={() => setAct(null)}
      onPointerLeave={() => setAct(null)}
    >
      {volume.map((km, i) => {
        const on = act === i
        return (
          <div key={i} className="relative flex h-full flex-1 items-end">
            {on && (
              <div className="pointer-events-none absolute -top-6 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/12 bg-[#0c201d] px-1.5 py-0.5 font-mono text-[10px] text-[#f1f8f1] shadow-lg">
                {lab(i)}: {km} km
              </div>
            )}
            <span className="absolute left-1/2 top-0 -translate-x-1/2 text-[9px] font-bold text-[#9bb3aa]">{km}</span>
            <i
              style={{ height: `${Math.max(3, (km / mx) * 88)}%` }}
              className={`block min-h-1 w-full self-end rounded-t-sm ${on ? "bg-[#c7ff54]" : i === n - 1 ? "bg-[#cf6542]" : "bg-[#b5d3ca]"}`}
            />
          </div>
        )
      })}
    </div>
  )
}
function RecoveryRanges({ rows }: { rows?: any[] }) {
  const col = (t: string) => (t === "ok" ? "#6ce6d3" : t === "watch" ? "#f6d69a" : t === "alert" ? "#e77a59" : "#9bb3aa")
  const word = (t: string) => (t === "ok" ? "v normě" : t === "watch" ? "sledovat" : t === "alert" ? "pod normou" : "—")
  const fmt = (n: number) => (Number.isInteger(n) ? `${n}` : `${Math.round(n * 10) / 10}`.replace(".", ","))
  if (!rows || !rows.length) return <p className="mt-4 text-sm text-[#71837b]">Chybí souvislá data z hodinek za posledních 35 dní.</p>
  return (
    <div className="mt-4 space-y-6">
      {rows.map((r: any) => {
        const sd = (r.hi - r.lo) / 2 || 1
        const dLo = Math.min(r.lo, r.valNum) - sd * 0.8
        const dHi = Math.max(r.hi, r.valNum) + sd * 0.8
        const P = (x: number) => clamp(((x - dLo) / (dHi - dLo)) * 100, 3, 97)
        const bandL = P(r.lo), bandR = P(r.hi), mk = P(r.valNum), c = col(r.tone)
        return (
          <div key={r.label}>
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-[#a9c2b9]"><span className="mr-1.5 text-[#6ce6d3]">{r.icon}</span>{r.label}</span>
              <span className="font-bold" style={{ color: c }}>{word(r.tone)}</span>
            </div>
            <div className="relative mt-5 h-2 rounded-full bg-white/[.06]">
              {/* usual range (baseline ± 1 SD) */}
              <i className="absolute top-0 h-full rounded-full bg-white/[.1]" style={{ left: `${bandL}%`, width: `${bandR - bandL}%` }} />
              {/* baseline center tick */}
              <i className="absolute top-[-2px] h-3 w-px bg-[#91b7a9]/70" style={{ left: `${P(r.baseNum)}%` }} />
              {/* current-value marker + its number */}
              <b className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${mk}%`, backgroundColor: c, boxShadow: `0 0 0 5px ${c}2e` }} />
              <span className="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-[11px] font-bold" style={{ left: `${mk}%`, color: c }}>{fmt(r.valNum)}{r.unit ? ` ${r.unit}` : ""}</span>
            </div>
            {/* numeric axis: usual-range bounds under the band edges */}
            <div className="relative mt-1.5 h-3 text-[9px] text-[#71837b]">
              <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${bandL}%` }}>{fmt(r.lo)}</span>
              <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${bandR}%` }}>{fmt(r.hi)}</span>
            </div>
            <p className="text-[9px] text-[#71837b]">obvyklé rozmezí {fmt(r.lo)}–{fmt(r.hi)}{r.unit ? ` ${r.unit}` : ""} · obvykle {fmt(r.baseNum)}</p>
          </div>
        )
      })}
    </div>
  )
}
const QCOL: Record<string, string> = { stable: "#6ce6d3", overreaching: "#f6d69a", silent: "#7fb0d6", critical: "#e77a59" }
function Quadrant({ quadrant = "stable", history, live, onSync, syncing, syncMsg, canSync }: { quadrant?: string; history?: any[] | null; live?: any; onSync?: () => void; syncing?: boolean; syncMsg?: string | null; canSync?: boolean }) {
  // 2×2: mechanika (sloupce) × zátěž (řádky). Aktivní buňka = reálný kvadrant.
  const cells: [string, string][] = [
    ["stable", "Stabilní"],
    ["silent", "Tichý drift"],
    ["overreaching", "Přetížení"],
    ["critical", "Kritická"],
  ]
  const q = QUAD[quadrant] || QUAD.stable
  const col = QCOL[quadrant] || "#6ce6d3"
  const [open, setOpen] = useState(false)
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="size-3 shrink-0 rounded-[4px]" style={{ background: col, boxShadow: `0 0 0 4px ${col}22` }} />
          <div className="min-w-0">
            <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Kvadrant stavu</p>
            <h3 className="truncate font-serif text-lg leading-tight text-[#f1f8f1]">{q.t}</h3>
            {(live?.engineMode === "v2" || live?.engineMode === "v3") && (live?.mechFlag || live?.mechWatch) && (
              <span
                className="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold"
                style={live?.mechFlag ? { background: "#e77a5920", color: "#ffc1ab" } : { background: "#ffffff12", color: "#a9c2b9" }}
                title={live?.mechFlag ? "Citlivý engine: mechanika se v rizikovém směru drží mimo vaši normu napříč běhy, nebo se to ukazuje ve dvou nezávislých skupinách metrik" : "Citlivý engine: jedna skupina metrik mechaniky se výrazně odchýlila — zatím jen sledujeme"}
              >
                {live?.mechFlag ? "⚑ mechanika přetrvává" : "◔ sledovat mechaniku"}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onSync && (
            <button
              onClick={onSync}
              disabled={syncing || !canSync}
              title={canSync ? "Stáhnout nová data z Garminu" : "Nejdřív připojte Garmin pro automatickou synchronizaci na stránce Data"}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-[#c7ff54]/40 bg-[#c7ff54]/10 px-3 py-1.5 font-mono text-[10px] font-bold text-[#c7ff54] transition enabled:hover:border-[#c7ff54] enabled:hover:bg-[#c7ff54]/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className={syncing ? "inline-block animate-spin" : ""}>⟳</span>
              {syncing ? "Synchronizuji…" : "Synchronizovat"}
            </button>
          )}
          <button onClick={() => setOpen(true)} className="whitespace-nowrap rounded-full border border-white/12 px-3 py-1.5 font-mono text-[10px] font-bold text-[#6ce6d3] transition hover:border-[#6ce6d3]/50 hover:text-[#c7ff54]">historie 6 měsíců ⤢</button>
        </div>
      </div>
      {syncMsg && <p className="mt-2 text-[11px] font-medium text-[#a9c2b9]">{syncMsg}</p>}
      <p className="mt-2 max-w-md text-xs leading-5 text-[#a9c2b9]">{q.d}</p>
      <button type="button" onClick={() => setOpen(true)} className="mt-4 grid w-full grid-cols-2 gap-2 text-left" title="Zobrazit vývoj stavu za 6 měsíců">
        {cells.map(([key, label]) => {
          const active = key === quadrant
          const c = QCOL[key]
          return (
            <span
              key={key}
              className="relative overflow-hidden rounded-xl border p-3.5 transition"
              style={{ borderColor: active ? c : "rgba(255,255,255,.08)", background: active ? `${c}20` : "rgba(255,255,255,.03)" }}
            >
              <span className="flex items-center gap-2">
                <i className={`size-2 rounded-full ${active ? "atlas-point" : ""}`} style={{ background: active ? c : `${c}55` }} />
                <b className="text-[13px]" style={{ color: active ? "#f1f8f1" : "#8ba59d" }}>{label}</b>
              </span>
              {active && <small className="mt-1.5 block text-[10px] font-bold uppercase tracking-wide" style={{ color: c }}>vy jste zde</small>}
            </span>
          )
        })}
      </button>
      <div className="mt-2 flex justify-between font-mono text-[8px] uppercase tracking-[.16em] text-[#5f7268]">
        <span>← vodorovně: mechanika</span>
        <span>svisle: zátěž ↑</span>
      </div>
      {open && <QuadrantHistory history={history} live={live} onClose={() => setOpen(false)} />}
    </div>
  )
}

// Large pop-out: daily state over the last ~6 months — bar height = overall
// risk, color = quadrant. Hover a bar to see that day's date and the signals
// that were influencing the state.
function QuadrantHistory({ history, live, onClose }: { history?: any[] | null; live?: any; onClose: () => void }) {
  const raw = history || []
  // Pin the final ("dnes") bar to the live assessment so the last day always
  // equals the STAV / big numbers, even if this history fetch is a day stale.
  const data =
    raw.length && live
      ? [
          ...raw.slice(0, -1),
          {
            ...raw[raw.length - 1],
            date: (live.computed_at || "").slice(0, 10) || raw[raw.length - 1].date,
            quadrant: live.quadrant ?? raw[raw.length - 1].quadrant,
            overall: live.overall ?? raw[raw.length - 1].overall,
            mech: live.mech ?? raw[raw.length - 1].mech,
            load: live.load ?? raw[raw.length - 1].load,
            symp: live.symp ?? raw[raw.length - 1].symp,
            signals: (live.signals || []).slice(0, 5),
          },
        ]
      : raw
  const [sel, setSel] = useState<number | null>(null)
  const i = sel != null && sel < data.length ? sel : data.length - 1
  const cur = data[i]
  const maxOv = Math.max(20, ...data.map((d) => d.overall || 0))
  const fmtShort = (s: string) => new Date(s).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })
  const fmtLong = (s: string) => new Date(s).toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })
  const gcol = (g: string) => (g === "A" ? "#e77a59" : g === "B" ? "#f6d69a" : "#6ce6d3")
  const axis = (label: string, v: number, tone: string) => (
    <div>
      <div className="flex justify-between text-[10px] text-[#9bb3aa]"><span>{label}</span><b style={{ color: v >= 25 ? tone : "#f1f8f1" }}>{v}</b></div>
      <div className="mt-1 h-1.5 rounded-full bg-white/10"><i className="block h-full rounded-full" style={{ width: `${clamp(v, 0, 100)}%`, background: tone }} /></div>
    </div>
  )
  return createPortal(
    <>
      <div className="fixed inset-0 z-[80] bg-[#050d0c]/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 top-[calc(68px+env(safe-area-inset-top))] z-[90] flex flex-col overflow-hidden border-t border-white/12 bg-[#0c201d] pb-[env(safe-area-inset-bottom)] text-[#f1f8f1] shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-white/10 p-5">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#71837b]">Vývoj stavu · 6 měsíců</p>
            <h2 className="mt-1 font-serif text-2xl">Kvadrant a rizikové skóre po dnech</h2>
          </div>
          <button onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 text-lg">×</button>
        </div>

        {data.length < 2 ? (
          <p className="p-6 text-sm text-[#71837b]">{history == null ? "Počítám historii…" : "Zatím málo historie."}</p>
        ) : (
          <div className="mx-auto grid w-full max-w-[1180px] flex-1 gap-5 overflow-auto p-5 md:grid-cols-[1.5fr_1fr]">
            {/* chart */}
            <div className="flex flex-col">
              <div className="flex h-[46vh] min-h-[220px] items-end gap-px rounded-xl bg-[#071313] p-2">
                {data.map((d, idx) => {
                  const h = Math.max(6, ((d.overall || 0) / maxOv) * 100)
                  const on = idx === i
                  return (
                    <button
                      key={d.date}
                      onMouseEnter={() => setSel(idx)}
                      onFocus={() => setSel(idx)}
                      onClick={() => setSel(idx)}
                      title={`${fmtShort(d.date)} · ${(QUAD[d.quadrant] || QUAD.stable).t} · skóre ${d.overall}`}
                      className="flex h-full flex-1 items-end"
                    >
                      <i className="block w-full rounded-sm transition-opacity" style={{ height: `${h}%`, background: QCOL[d.quadrant] || "#3a4a45", opacity: on ? 1 : 0.72, outline: on ? "1px solid #f1f8f1" : "none" }} />
                    </button>
                  )
                })}
              </div>
              <div className="mt-1 flex justify-between font-mono text-[9px] text-[#71837b]">
                <span>{fmtShort(data[0].date)}</span>
                <span>výška = skóre 0–{maxOv}</span>
                <span>dnes</span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10px] text-[#9bb3aa]">
                {(["stable", "overreaching", "silent", "critical"] as const).map((k) => (
                  <span key={k} className="inline-flex items-center gap-1.5">
                    <i className="size-2.5 rounded-sm" style={{ background: QCOL[k] }} />
                    {(QUAD[k] || QUAD.stable).t}
                  </span>
                ))}
              </div>
              <p className="mt-3 text-[10px] leading-4 text-[#71837b]">Denní přehrání enginu z dat do daného dne (objektivní signály z hodinek — self-report se nepřehrává). Najeď na sloupec.</p>
            </div>

            {/* selected-day detail */}
            {cur && (
              <div className="rounded-2xl border border-white/10 bg-[#102724] p-4">
                <p className="font-mono text-[10px] uppercase tracking-[.14em] text-[#71837b]">{fmtLong(cur.date)}</p>
                <div className="mt-1 flex items-center gap-2">
                  <span className="size-3 rounded-sm" style={{ background: QCOL[cur.quadrant] }} />
                  <h3 className="font-serif text-xl">{(QUAD[cur.quadrant] || QUAD.stable).t}</h3>
                  <span className="ml-auto font-serif text-2xl">{cur.overall}<small className="text-xs text-[#71837b]">/100</small></span>
                </div>
                <p className="mt-1 text-[11px] leading-4 text-[#a9c2b9]">{(QUAD[cur.quadrant] || QUAD.stable).d}</p>
                <div className="mt-4 space-y-2">
                  {axis("Mechanika", cur.mech, "#6ce6d3")}
                  {axis("Zátěž", cur.load, "#f6d69a")}
                  {axis("Příznaky", cur.symp, "#e77a59")}
                </div>
                <p className="mt-4 font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Co ovlivňovalo stav</p>
                {cur.signals && cur.signals.length ? (
                  <div className="mt-2 space-y-1.5">
                    {cur.signals.map((s: any, k: number) => (
                      <div key={k} className="flex items-center gap-2 text-[12px]">
                        <span className="grid size-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" style={{ background: `${gcol(s.grade)}26`, color: gcol(s.grade) }}>{s.grade}</span>
                        <span className="flex-1 truncate text-[#e7efe9]">{s.name}</span>
                        <span className="font-mono text-[#9bb3aa]">+{s.pts}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-[#71837b]">Nic nad prahem — stav držel na normě.</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>,
    document.body,
  )
}
function TodayV2() {
  const { me, boot, refresh, error } = useApp()
  const a = boot?.assessment
  const L = a?.loadDetail
  const rcv = a?.rcv
  const rid = me?.runner_id
  const [quadHist, setQuadHist] = useState<any[] | null>(null)
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
  const deltaCol = deltaUp ? "#6ce6d3" : deltaDown ? "#e77a59" : "#9bb3aa"
  const gated = (a?.confidence?.value ?? 0) < 0.6
  const mech = a?.mech ?? 0
  const quad = a?.quadrant ? QUAD[a.quadrant] : null
  const tavr = a?.tavr
  const pos = (p: number) => clamp(p, 10, 90)
  const sleepTone = rcv ? ((rcv.sleep?.debt || 0) >= 4 ? "alert" : (rcv.sleep?.debt || 0) >= 1 ? "watch" : "ok") : "muted"
  const hrvTone = rcv ? ((rcv.hrv?.z ?? 0) <= -1 ? "alert" : (rcv.hrv?.z ?? 0) < -0.3 ? "watch" : "ok") : "muted"
  const rhrTone = rcv ? ((rcv.rhr?.z ?? 0) >= 1.2 ? "alert" : (rcv.rhr?.z ?? 0) > 0.5 ? "watch" : "ok") : "muted"
  const rstd = (arr: number[]) => { if (!arr || arr.length < 2) return 0; const m = arr.reduce((s, x) => s + x, 0) / arr.length; return Math.sqrt(arr.reduce((s, x) => s + (x - m) ** 2, 0) / (arr.length - 1)) }
  // Numeric usual range = baseline ± 1 SD, so the interval bar can carry a real
  // axis (band bounds + the current value at the marker) instead of a bare dot.
  const rrow = (label: string, icon: string, unit: string, o: any, tone: string) => {
    const series = (o?.series || []) as number[]
    const base = o?.base ?? 0, val = o?.now ?? 0
    const sd = rstd(series) || Math.max(Math.abs(base) * 0.06, 0.1)
    return { label, icon, unit, tone, valNum: val, baseNum: base, lo: base - sd, hi: base + sd }
  }
  const recoveryRows = rcv
    ? [rrow("Spánek", "☾", "h", rcv.sleep, sleepTone), rrow("HRV", "♡", "ms", rcv.hrv, hrvTone), rrow("Klidový tep", "⏱", "", rcv.rhr, rhrTone)]
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
  const toneChip = (t: string) => (t === "ok" ? "bg-[#17382f] text-[#6ce6d3]" : t === "watch" ? "bg-[#3c2922] text-[#f6d69a]" : t === "alert" ? "bg-[#3c2922] text-[#e77a59]" : "bg-white/[.06] text-[#9bb3aa]")
  const wkly = (L?.weekly || []) as number[]
  const typicalKm = wkly.length > 1 ? Math.round(wkly.slice(0, -1).reduce((s, x) => s + x, 0) / (wkly.length - 1)) : (L?.runKm7 ?? 0)
  const signals = (a?.signals || []) as any[]
  const tierWord = a?.tier === "alert" ? "vysoké riziko" : a?.tier === "watch" ? "sledovat" : "nízké riziko"
  const recur = a?.painRecurring as { site: string; days: number } | null | undefined
  const tierCol = a?.tier === "alert" ? "#e77a59" : a?.tier === "watch" ? "#f6d69a" : "#6ce6d3"
  const gradeCol = (g: string) => (g === "A" ? "#e77a59" : g === "B" ? "#f6d69a" : "#6ce6d3")
  const overall = a?.overall ?? 0
  const RING = 2 * Math.PI * 44

  return (
    <>
      <div className="flex items-end justify-between">
        <div>
          <Label>{today}</Label>
          <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
            {greet}, {firstName}.
          </h1>
        </div>
      </div>
      {error && !a && (
        <div className="mt-5 flex items-start gap-3 rounded-2xl border border-[#e77a59]/40 bg-[#3c2922] p-4 text-[#ffc1ab]">
          <span className="text-lg leading-none">⚠</span>
          <div className="flex-1">
            <p className="text-sm font-bold">Data se nepodařilo načíst</p>
            <p className="mt-0.5 text-xs leading-5">{error}</p>
          </div>
          <button onClick={() => refresh()} className="shrink-0 self-center rounded-full bg-[#c7ff54] px-3 py-1.5 text-xs font-bold text-[#071313]">Zkusit znovu</button>
        </div>
      )}
      {a?.painWarn && (
        <div className="mt-5 flex items-start gap-3 rounded-2xl border border-[#e77a59]/40 bg-[#3c2922] p-4 text-[#ffc1ab]">
          <span className="text-lg leading-none">⚠</span>
          <div>
            <p className="text-sm font-bold">{a.painWarn.backToBack ? "Neustupující bolest — zvažte situaci" : `Nahlásil jste bolest ${a.painWarn.score}/10`}</p>
            <p className="mt-0.5 text-xs leading-5">
              {a.painWarn.site && a.painWarn.site !== "—" ? `${a.painWarn.site} · ` : ""}
              {a.painWarn.backToBack
                ? "Stejné místo bolí opakovaně během pár dní — varovný signál přetížení. Zvažte odpočinek a konzultaci s fyzioterapeutem, než přidáte objem."
                : "Bolest nad 3/10 stojí za pozornost. Zvažte lehčí zátěž; pokud se vrátí na stejném místě, proberte to s fyzioterapeutem."}
            </p>
          </div>
        </div>
      )}
      <section className="mt-7 rounded-[24px] border border-white/10 bg-gradient-to-br from-[#0c201d] to-[#0a1a18] p-6 text-[#f1f8f1]">
        <Quadrant quadrant={a?.quadrant} history={quadHist} live={a} onSync={doSync} syncing={syncing} syncMsg={syncMsg} canSync={!!gStatus?.connected} />
        {/* „Stav" — co jde do kvadrantu — je teď součástí boxu s kvadrantem */}
        <div className="mt-6 border-t border-white/10 pt-5">
          <div className="flex items-center gap-4">
            <div className="relative grid size-16 shrink-0 place-items-center">
              <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90">
                <circle cx="50" cy="50" r="44" fill="none" stroke="rgb(255 255 255 / .1)" strokeWidth="9" />
                <circle cx="50" cy="50" r="44" fill="none" stroke={tierCol} strokeWidth="9" strokeLinecap="round" strokeDasharray={RING} strokeDashoffset={RING * (1 - clamp(overall, 0, 100) / 100)} />
              </svg>
              <b className="font-serif text-2xl text-[#f1f8f1]">{overall}</b>
            </div>
            <div>
              <span className="flex items-center gap-1.5"><p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Celkový stav</p><InfoDot text={MI.overall} label="Celkový stav" /></span>
              <h3 className="font-serif text-xl text-[#f1f8f1]">{recur && a?.tier !== "alert" ? "Odlehčit — opakovaná bolest" : quad?.t}</h3>
              <p className="mt-0.5 text-xs font-bold" style={{ color: tierCol }}>{tierWord}</p>
              {recur && (
                <p className="mt-1 text-[11px] leading-4 text-[#f6d69a]">
                  {recur.site} · {recur.days}× za 28 dní — i mírná bolest na stejném místě je vzorec přetížení. Kratší a volnější běhy, bez dlouhého běhu a intenzity.
                </p>
              )}
            </div>
          </div>
          <div className="mt-5">
            <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Co teď nejvíc ovlivňuje stav</p>
            {signals.length ? (
              <div className="mt-2.5 space-y-2.5">
                {signals.slice(0, 4).map((s) => {
                  const gc = gradeCol(s.grade)
                  const w = Math.max(10, (s.pts / (signals[0].pts || 1)) * 100)
                  return (
                    <div key={s.id}>
                      <div className="flex items-center gap-2">
                        <span className="grid size-5 shrink-0 place-items-center rounded-full text-[9px] font-bold" style={{ background: `${gc}26`, color: gc }}>{s.grade}</span>
                        <span className="flex-1 truncate text-[13px] text-[#f1f8f1]">{s.name}</span>
                        <span className="font-mono text-[11px] text-[#9bb3aa]">{s.val}</span>
                      </div>
                      <div className="ml-7 mt-1 h-1 rounded-full bg-white/10">
                        <i className="block h-full rounded-full" style={{ width: `${w}%`, background: gc }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="mt-2 text-sm text-[#a9c2b9]">Nic nad prahem — zátěž i mechanika sedí na vaší normě.</p>
            )}
            {gated && <p className="mt-2 text-[10px] text-[#71837b]">Mechanické signály jsou zatím umlčené — buduje se baseline ({Math.round((a?.confidence?.value ?? 0) * 100)} %).</p>}
          </div>
        </div>
      </section>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.45fr_.8fr]">
        <section className="rounded-[24px] border border-white/10 bg-[#0c201d] p-6 text-[#f1f8f1]">
          <span className="flex items-center gap-1.5"><Label>Regenerace přes noc</Label><InfoDot text={MI.recoveryScore} label="Regenerace přes noc" /></span>
          <div className="mt-3 flex items-end justify-between">
            <b className="text-4xl">
              {score ?? "—"}{" "}
              <small className="text-sm font-normal text-[#9bb3aa]">/ 100</small>
            </b>
            <div className="text-right">
              <span className="block text-sm text-[#c7ff54]">{scoreLabel}</span>
              {scoreDelta != null && (
                <span className="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold" style={{ background: `${deltaCol}1f`, color: deltaCol }}>
                  <span>{deltaUp ? "▲" : deltaDown ? "▼" : "▬"}</span>
                  <span>{scoreDelta > 0 ? `+${scoreDelta}` : scoreDelta < 0 ? scoreDelta : "beze změny"}</span>
                  <span className="font-normal opacity-70">{scoreDelta !== 0 ? "přes noc" : "oproti včera"}</span>
                </span>
              )}
            </div>
          </div>
          <div className="relative mt-4 h-7 overflow-hidden rounded-md border border-[#c7ff54]/35 bg-[#071313]">
            <i className="absolute inset-y-0 left-0 bg-[#c7ff54]/40" style={{ width: `${clamp(score ?? 0, 0, 100)}%` }} />
            {scorePrev != null && !!scoreDelta && (
              <i className="absolute inset-y-0" style={{ left: `${clamp(Math.min(score ?? 0, scorePrev), 0, 100)}%`, width: `${Math.abs((score ?? 0) - scorePrev)}%`, background: deltaCol, opacity: 0.85 }} />
            )}
            {scorePrev != null && (
              <i className="absolute inset-y-0 w-0.5 bg-[#f1f8f1]" style={{ left: `calc(${clamp(scorePrev, 0, 100)}% - 1px)` }} />
            )}
            <i className="absolute inset-y-0 left-1/4 w-px bg-[#071313]/50" />
            <i className="absolute inset-y-0 left-1/2 w-px bg-[#071313]/50" />
            <i className="absolute inset-y-0 left-3/4 w-px bg-[#071313]/50" />
          </div>
          <div className="mt-2 flex justify-between text-[9px] text-[#71837b]">
            <span>nízká</span>
            <span>vyvážená</span>
            <span>plná</span>
          </div>
          {scorePrev != null && (
            <p className="mt-2 text-[10px] text-[#71837b]">
              <span className="mr-1 inline-block h-2 w-0.5 translate-y-px bg-[#f1f8f1]" /> včera {scorePrev}
              {scoreDelta ? <> · <span style={{ color: deltaCol }}>{deltaUp ? "regenerace přes noc stoupla" : "regenerace přes noc klesla"} o {Math.abs(scoreDelta)}</span></> : " · přes noc beze změny"}
            </p>
          )}
          <div className="mt-5 grid gap-2 border-t border-white/10 pt-4 text-xs">
            {rcv && (
              <div className="flex items-center gap-3">
                <span className="grid size-6 place-items-center rounded-full bg-[#6ce6d3]/15 text-[#6ce6d3]">☾</span>
                <span>
                  <b>HRV {rcv.hrv?.now} ms</b>
                  <small className="ml-2 text-[#91b7a9]">baseline {rcv.hrv?.base} ms · spánek {rcv.sleep?.now} h</small>
                </span>
              </div>
            )}
            <div className="flex items-center gap-3">
              <span className="grid size-6 place-items-center rounded-full bg-[#c7ff54]/15 text-[#c7ff54]">↗</span>
              <span>
                <b>{a?.tier === "alert" || a?.painRecurring ? "Prioritou je odlehčení" : a?.tier === "watch" ? "Sledujte zátěž" : "Trénink sedí"}</b>
                <small className="ml-2 text-[#91b7a9]">{quad?.d}</small>
              </span>
            </div>
          </div>
        </section>
        <Card>
          <div className="flex items-center justify-between gap-2">
            <Label>Regenerace vs. norma</Label>
            <WeeklyCheckButton />
          </div>
          <RecoveryRanges rows={recoveryRows} />
        </Card>
      </div>
      <div className="mt-4">
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Label>Tréninková zátěž</Label>
              <h2 className="mt-1 font-serif text-2xl">{loadStatus.t}</h2>
            </div>
            <span className={`rounded-full px-3 py-1 text-[11px] font-bold ${toneChip(loadStatus.tone)}`}>tento týden</span>
          </div>
          <p className="mt-1 text-xs text-[#64736e]">{loadStatus.d}</p>
          <p className="mt-4 font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Kilometry po kalendářních týdnech (Po–Ne)</p>
          <NumberedChart vals={L?.weekly} />
          <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-[#64736e]">
            <span>Tento týden <small className="text-[#71837b]">(Po–Ne)</small> <b className="block text-base text-[#f1f8f1]">{L?.weekKm ?? "—"} km</b></span>
            <span>Posledních 7 dní <b className="block text-base text-[#f1f8f1]">{L?.runKm7 ?? "—"} km</b></span>
            <span className="text-right">Obvykle / týden <b className="block text-base text-[#f1f8f1]">{typicalKm} km</b></span>
          </div>
          {a?.capacity && <CapacityMini cap={a.capacity} />}
        </Card>
      </div>
    </>
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
    <div className="motion-shell min-h-screen bg-[#e7e9e1] p-5 md:grid md:grid-cols-2 md:gap-8 md:p-8">
      <aside className="hidden rounded-[30px] bg-[#235e59] p-10 text-white md:flex md:flex-col">
        <div className="flex items-center gap-2 font-bold">
          <Mark />
          došlap
        </div>
        <div className="my-auto">
          <Label>Bezpečný přístup</Label>
          <h1 className="mt-4 max-w-md font-serif text-5xl leading-[.95]">
            Změny ve vaší zátěži a mechanice vidíte včas.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-6 text-[#cbe1db]">
            Aplikace pro běžce — sledování zátěže, regenerace a běžecké
            mechaniky proti vaší vlastní baseline.
          </p>
        </div>
      </aside>
      <section className="mx-auto flex w-full max-w-md flex-col justify-center py-8">
        <span className="mb-10 flex items-center gap-2 font-bold md:hidden">
          <Mark />
          došlap
        </span>
        <Label>Přístup pro běžce</Label>
        <h1 className="mt-1 font-serif text-4xl tracking-[-.06em]">
          {mode === "login" ? "Přihlášení" : "Nová registrace"}
        </h1>
        <Card className="mt-5">
          <p className="font-serif text-xl">
            {mode === "login" ? "Přihlásit se" : "Registrovat se"}
          </p>
          {mode === "register" && (
            <input
              className="mt-5 w-full rounded-xl border border-[#d9dfda] px-3 py-3 text-sm"
              placeholder="Jméno"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
          <input
            className="mt-3 w-full rounded-xl border border-[#d9dfda] px-3 py-3 text-sm"
            placeholder="E-mail"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password"
            className="mt-3 w-full rounded-xl border border-[#d9dfda] px-3 py-3 text-sm"
            placeholder="Heslo"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          {mode === "register" && <p className="mt-2 text-[11px] text-[#8a988f]">Heslo alespoň 8 znaků.</p>}
          {err && <p className="mt-3 text-xs font-bold text-[#e47d51]">{err}</p>}
          <button
            onClick={submit}
            disabled={busy}
            className="mt-5 w-full rounded-full bg-[#235e59] py-3 text-sm font-bold text-white disabled:opacity-60"
          >
            {busy ? "Přihlašuji…" : mode === "login" ? "Přihlásit se" : "Vytvořit účet"}
          </button>
          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login")
              setErr(null)
            }}
            className="mt-3 w-full text-center text-xs font-bold text-[#58716b]"
          >
            {mode === "login" ? "Nemáte účet? Registrovat se" : "Už máte účet? Přihlásit se"}
          </button>
        </Card>
      </section>
    </div>
  )
}
function AtlasBubble() {
  const [open, setOpen] = useState(false)
  const [score, setScore] = useState<number | null>(null)
  const [pain, setPain] = useState(0)
  const [soreness, setSoreness] = useState(1)
  const [fatigue, setFatigue] = useState(2)
  const [note, setNote] = useState("")
  const [points, setPoints] = useState<BodyPoint[]>([])
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
      const pts = points.map((p) => ({ region: p.region, side: p.side || null, type: p.kind }))
      await api.checkin(rid, {
        pain_score: pain, soreness, stress: fatigue, mood: score, notes: note || null,
        pain_points: pts, pain_site: pts.length ? pts.map((p) => p.region).join(", ") : null,
      })
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
          className="fixed right-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-[55] flex items-center gap-2 rounded-full bg-[#c7ff54] py-3 pl-3 pr-4 text-sm font-bold text-[#071313] shadow-[0_12px_30px_rgba(0,0,0,.45)] md:bottom-7 md:right-7"
        >
          <span className="grid size-6 place-items-center rounded-full bg-[#071313]/10 text-base">♡</span>
          <span className="whitespace-nowrap">Check-in</span>
        </button>
      )}
      {open && (
        <div
          data-auto-reveal
          className="fixed inset-x-0 bottom-[calc(4.4rem+env(safe-area-inset-bottom))] z-[70] mx-auto max-h-[calc(100dvh-6rem)] max-w-[480px] overflow-y-auto rounded-t-[28px] border border-white/10 bg-[#102724] p-5 text-[#f1f8f1] shadow-2xl md:bottom-7 md:right-7 md:left-auto md:rounded-[28px]"
        >
          <div className="flex justify-between">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
                Denní check-in
              </p>
              <h2 className="mt-1 text-2xl">Jak se dnes cítí tělo?</h2>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="grid size-9 place-items-center rounded-full border border-white/15"
            >
              ×
            </button>
          </div>
          <p className="mt-5 font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
            Nálada
          </p>
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
                className={`flex aspect-square flex-col items-center justify-center rounded-2xl border text-xl ${
                  score === index
                    ? "border-[#c7ff54] bg-[#c7ff54]/15"
                    : "border-white/10 bg-[#071313]"
                }`}
              >
                {face}
                <span className="mt-1 text-[8px] text-[#91b7a9]">{label}</span>
              </button>
            ))}
          </div>
          <div className="mt-6 space-y-5 rounded-2xl bg-[#071313] p-4">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
                Tělesné pocity
              </p>
              <span className="text-[9px] text-[#71837b]">0 nic 10 silné</span>
            </div>
            {bodySignals.map(([label, value, setValue, low]) => (
              <div key={label}>
                <div className="mb-2 flex justify-between text-xs">
                  <span>{label}</span>
                  <b className="text-[#c7ff54]">{value}/10</b>
                </div>
                <input
                  aria-label={label}
                  type="range"
                  min="0"
                  max="10"
                  value={value}
                  onChange={(event) => setValue(Number(event.target.value))}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-[#29413b] accent-[#c7ff54]"
                />
                <div className="mt-1 flex justify-between text-[9px] text-[#71837b]">
                  <span>{low}</span>
                  <span>silné</span>
                </div>
              </div>
            ))}
          </div>
          {pain > 0 && (
            <div className="mt-5 rounded-2xl bg-[#071313] p-4">
              <div className="flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">Kde to bolí</p>
                <span className="text-[9px] text-[#71837b]">bolest {pain}/10</span>
              </div>
              <p className="mt-1 text-xs text-[#71837b]">Klepněte na místa, která bolí — můžete vybrat víc.</p>
              <div className="mt-3"><MuscleAnatomy multi onSelect={setPoints} /></div>
            </div>
          )}
          {pain > 3 && (
            <div className="mt-5 rounded-2xl border border-[#e77a59]/40 bg-[#3c2922] p-4 text-[#ffc1ab]">
              <p className="text-sm font-bold">⚠ Bolest {pain}/10 — zvažte situaci</p>
              <p className="mt-1 text-xs leading-5">Bolest nad 3/10 není jen diskomfort. Zvažte odpočinek nebo lehčí zátěž, a pokud se ozve i u dalšího běhu na stejném místě, raději to proberte s fyzioterapeutem, než přidáte objem.</p>
            </div>
          )}
          <label className="mt-5 block">
            <span className="font-mono text-[10px] uppercase tracking-[.16em] text-[#91b7a9]">
              Poznámka
            </span>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Co by měl váš fyzioterapeut vědět?"
              className="mt-2 min-h-20 w-full rounded-xl border border-white/10 bg-[#071313] p-3 text-sm text-[#f1f8f1] placeholder:text-[#71837b]"
            />
          </label>
          <div className="mt-5 grid grid-cols-3 gap-2 rounded-2xl bg-[#071313] p-3 text-center">
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">{rcv?.score ?? "—"}<small className="text-[10px] font-normal text-[#71837b]">/100</small></b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">regenerace</span>
              <span className="mt-1 block text-[8px]" style={{ color: (rcv?.scoreDelta ?? 0) > 0 ? "#6ce6d3" : (rcv?.scoreDelta ?? 0) < 0 ? "#e77a59" : "#71837b" }}>
                {rcv?.scoreDelta == null ? (rcv?.scoreLabel || "—") : rcv.scoreDelta === 0 ? "beze změny" : `${rcv.scoreDelta > 0 ? "+" : ""}${rcv.scoreDelta} přes noc`}
              </span>
            </div>
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">{rcv?.sleep?.now ?? "—"}<small className="text-[10px] font-normal text-[#71837b]"> h</small></b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">spánek</span>
              <span className="mt-1 block text-[8px] text-[#71837b]">obvykle {rcv?.sleep?.base ?? "—"} h</span>
            </div>
            <div className="rounded-xl bg-white/[.035] px-2 py-2.5">
              <b className="block font-serif text-lg text-[#f1f8f1]">{L?.valid ? `×${L.ratio}` : "—"}</b>
              <span className="mt-1 block font-sans text-[9px] text-[#91b7a9]">poměr zátěže</span>
              <span className="mt-1 block text-[8px] text-[#71837b]">{L?.valid ? "7:28 dní · vč. sportu" : "zatím málo dat"}</span>
            </div>
          </div>
          <button
            onClick={save}
            disabled={busy}
            className="mt-5 w-full rounded-full bg-[#c7ff54] py-3 text-sm font-bold text-[#071313] disabled:opacity-40"
          >
            {busy ? "Ukládám…" : "Uložit check-in"}
          </button>
        </div>
      )}
    </>
  )
}
const NAV_ICON: Record<string, string> = { today: "⌂", training: "◎", post: "▤", mechanics: "◌", load: "⌁", messages: "◔" }
function AtlasNav() {
  const { pathname } = useLocation()
  const navItems = useRunnerNav()
  // Single source of truth = runnerNav, so the mobile bar can never drift from
  // the desktop tabs again (previously missing "Deník" and in wrong order).
  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 flex border-t border-white/10 bg-[#071313]/95 px-2 pb-[max(.8rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:hidden">
      {navItems.map(([id, label]) => {
        const to = `/app/${id}`
        return (
          <Link
            key={id}
            to={to}
            className={`flex flex-1 flex-col items-center gap-1 text-[10px] ${
              pathname === to ? "text-[#c7ff54]" : "text-[#80968e]"
            }`}
          >
            <span className="text-lg">{NAV_ICON[id] || "•"}</span>
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
const router = createBrowserRouter([
  { path: "/", Component: () => <Navigate to="/app/today" replace /> },
  { path: "/auth", Component: Auth },
  {
    Component: Layout,
    children: [
      { path: "/app/:tab", Component: RunnerPage },
      { path: "/data", Component: DataPage },
      { path: "/engine", Component: EngineLab },
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
