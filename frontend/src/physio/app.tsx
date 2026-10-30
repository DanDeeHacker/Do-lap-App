// The physiotherapist application (owner request 2026-10-27, report v6 Section 6.1: "the physio
// application follows the progression of a client's case"): the case queue opens first, then the
// calendar, the clients with their overview, programme, return to running, conclusions and chat,
// and the physio's own profile. Same platform and data as the runner app, another level of detail.
import { useEffect, useState } from "react"
import { Link, Navigate, useLocation } from "react-router"
import { CalendarDays, Inbox, LogOut, Settings, Users, UserRound, type LucideIcon } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Mark, Wordmark } from "@/shell"
import { AdminPage } from "@/admin"
import { QueuePage } from "@/physio/queue"
import { CalendarPage } from "@/physio/calendar"
import { ClientPage, ClientsPage } from "@/physio/client"
import { ProfilePage } from "@/physio/profile"

const NAV: [string, string, LucideIcon][] = [
  ["/physio", "Fronta případů", Inbox], ["/physio/calendar", "Kalendář", CalendarDays],
  ["/physio/clients", "Klienti", Users], ["/physio/profile", "Profil", UserRound],
]

export function PhysioApp() {
  const { me, logout } = useApp()
  const { pathname } = useLocation()
  const [prof, setProf] = useState<any>(null)
  const loadProf = () => api.physioMe().then(setProf).catch(() => setProf(null))
  useEffect(() => { void loadProf() }, [])
  const pid = me?.physio_id || ""
  if (!pathname.startsWith("/physio") && !(pathname === "/admin" && me?.team)) return <Navigate to="/physio" replace />
  const on = (to: string) => (to === "/physio" ? pathname === "/physio" : pathname === to || pathname.startsWith(to + "/") || (to === "/physio/clients" && pathname.startsWith("/physio/client/")))
  const nav = [...NAV, ...(me?.team ? [["/admin", "Správa a tým", Settings] as [string, string, LucideIcon]] : [])]
  let page = <QueuePage pid={pid} />
  if (pathname.startsWith("/physio/calendar")) page = <CalendarPage pid={pid} />
  else if (pathname.startsWith("/physio/client/")) page = <ClientPage pid={pid} rid={decodeURIComponent(pathname.slice("/physio/client/".length).split("/")[0])} />
  else if (pathname.startsWith("/physio/clients")) page = <ClientsPage />
  else if (pathname.startsWith("/physio/profile")) page = <ProfilePage onSaved={loadProf} />
  else if (pathname === "/admin") page = <AdminPage />
  return (
    <div className="motion-shell min-h-screen bg-bg text-fg" data-testid="physio-app">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[220px] flex-col border-r border-white/[.07] bg-bg/95 px-3 pb-6 pt-5 backdrop-blur lg:flex" aria-label="Navigace fyzioterapeuta">
        <Link to="/physio" className="mb-1 flex items-center gap-2.5 px-2 text-lg font-extrabold tracking-[-.04em]"><Mark size={34} /><Wordmark /></Link>
        <p className="mb-5 px-2 text-[11px] font-bold uppercase tracking-[.08em] text-fg-3">pro fyzioterapeuty</p>
        <nav className="grid gap-1">
          {nav.map(([to, label, Icon]) => (
            <Link key={to} to={to} aria-current={on(to) ? "page" : undefined}
              className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-bold transition ${on(to) ? "bg-accent/12 text-accent" : "text-fg-2 hover:bg-white/[.05] hover:text-fg"}`}>
              <Icon className="size-[18px] shrink-0" aria-hidden />{label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto border-t border-white/[.07] px-2 pt-4 text-[12px] text-fg-3">
          <p className="truncate font-bold text-fg-2">{prof?.name || me?.name}</p>
          <p className="truncate">{prof?.clinic ? `${prof.clinic.name}${prof.clinic.city ? `, ${prof.clinic.city}` : ""}` : me?.email}</p>
          <button type="button" onClick={logout} className="mt-2 inline-flex items-center gap-1.5 font-bold text-fg-2 hover:text-fg"><LogOut className="size-3.5" aria-hidden />Odhlásit se</button>
        </div>
      </aside>
      <header className="flex items-center justify-between gap-3 border-b border-white/[.07] px-5 py-3 lg:hidden">
        <Link to="/physio" className="flex items-center gap-2 text-lg"><Mark size={28} /><Wordmark /></Link>
        <button type="button" onClick={logout} className="btn btn-secondary btn-sm">Odhlásit se</button>
      </header>
      <div className="lg:pl-[220px]">
        <main className="mx-auto max-w-[1180px] px-5 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-6 md:px-9 lg:pb-16 lg:pt-10">
          {prof && !prof.verified && (
            <div className="mb-5 rounded-2xl border border-info/30 bg-info/10 px-4 py-3 text-[13px] text-fg-2" data-testid="physio-unverified" role="status">
              <b className="text-fg">Účet čeká na ověření</b>
              {" — tým Došlapu ověří, kdo jste a vaši odbornou způsobilost. Do té doby nevidíte frontu případů ani klienty; profil a volné termíny si můžete připravit."}
            </div>
          )}
          {prof && !prof.complete && !pathname.startsWith("/physio/profile") && (
            <Link to="/physio/profile" className="mb-5 block rounded-2xl border border-watch/30 bg-watch/10 px-4 py-3 text-[13px] text-watch-soft hover:bg-watch/15" data-testid="physio-setup">
              <b className="text-fg">Doplňte profil a praxi</b>{" — podle města praxe se vám řadí fronta případů a běžci vás najdou v záložce Péče."}
            </Link>
          )}
          {page}
        </main>
      </div>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-white/[.08] bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Navigace fyzioterapeuta">
        {NAV.map(([to, label, Icon]) => (
          <Link key={to} to={to} aria-current={on(to) ? "page" : undefined}
            className={`flex min-h-[56px] flex-col items-center justify-center gap-1 text-[11px] font-bold ${on(to) ? "text-accent" : "text-fg-3"}`}>
            <Icon className="size-5" aria-hidden />{label}
          </Link>
        ))}
      </nav>
    </div>
  )
}
