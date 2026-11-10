// The physiotherapist application (owner request 2026-10-27; physio brief 2026-11-09 W3/W17): Dnes opens
// first, then the queue, the calendar, the clients, the messages, the practice and the profile. A light,
// dense surface of its own ([data-surface="physio"]); Ctrl/Cmd+K finds a client from anywhere.
import { useEffect, useRef, useState } from "react"
import { Link, Navigate, useLocation, useNavigate } from "react-router"
import { Bell, Building2, CalendarDays, Inbox, LogOut, MessageCircle, Search, Settings, Sun, Users, UserRound, type LucideIcon } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Mark, Wordmark } from "@/shell"
import { AdminPage } from "@/admin"
import { QueuePage } from "@/physio/queue"
import { CalendarPage } from "@/physio/calendar"
import { ClientPage, ClientsPage } from "@/physio/client"
import { ProfilePage } from "@/physio/profile"
import { PracticePage } from "@/physio/practice"
import { PrintPage } from "@/physio/docs"
import { TodayPage } from "@/physio/today"
import { MessagesPage } from "@/physio/messages"
import { PrevisitPage, VisitEditor } from "@/physio/visit"

const NAV: [string, string, LucideIcon][] = [
  ["/physio", "Dnes", Sun], ["/physio/queue", "Fronta případů", Inbox], ["/physio/calendar", "Kalendář", CalendarDays],
  ["/physio/clients", "Klienti", Users], ["/physio/messages", "Zprávy", MessageCircle], ["/physio/practice", "Praxe", Building2],
  ["/physio/profile", "Profil", UserRound],
]
// W17.8: on a phone the four things a physio does away from the desk
const MOBILE = ["/physio", "/physio/clients", "/physio/messages", "/physio/calendar"]

export function PhysioApp() {
  const { me, logout } = useApp()
  const { pathname } = useLocation()
  const nav = useNavigate()
  const [prof, setProf] = useState<any>(null)
  const [search, setSearch] = useState(false)
  const [notes, setNotes] = useState<any[]>([])
  const [bell, setBell] = useState(false)
  const loadProf = () => api.physioMe().then(setProf).catch(() => setProf(null))
  useEffect(() => { void loadProf(); api.notifications().then((x: any) => setNotes(x.items || [])).catch(() => null) }, [pathname])
  // the physio surface applies to the whole document, so sheets and toasts in portals follow it
  useEffect(() => {
    const el = document.documentElement
    el.dataset.surface = "physio"
    if (prof?.dark_mode) el.dataset.theme = "dark"; else delete el.dataset.theme
    return () => { delete el.dataset.surface; delete el.dataset.theme }
  }, [prof?.dark_mode])
  // W17.7: Ctrl/Cmd+K search, only outside input fields
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearch(true) }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
  const pid = me?.physio_id || ""
  if (!pathname.startsWith("/physio") && !(pathname === "/admin" && me?.team)) return <Navigate to="/physio" replace />
  const on = (to: string) => (to === "/physio" ? pathname === "/physio" : pathname === to || pathname.startsWith(to + "/") || (to === "/physio/clients" && pathname.startsWith("/physio/client/")))
  const links = [...NAV, ...(me?.team ? [["/admin", "Správa a tým", Settings] as [string, string, LucideIcon]] : [])]
  // R9: the printout renders on its own, black on white, without the app shell
  const print = pathname.match(/^\/physio\/client\/([^/]+)\/tisk$/)
  if (print) return <PrintPage rid={decodeURIComponent(print[1])} />
  const visit = pathname.match(/^\/physio\/client\/([^/]+)\/navsteva\/(\d+)$/)
  const prep = pathname.match(/^\/physio\/client\/([^/]+)\/priprava\/(\d+)$/)
  let page = <TodayPage />
  if (visit) page = <VisitEditor rid={decodeURIComponent(visit[1])} bid={Number(visit[2])} />
  else if (prep) page = <PrevisitPage rid={decodeURIComponent(prep[1])} bid={Number(prep[2])} />
  else if (pathname.startsWith("/physio/queue")) page = <QueuePage pid={pid} />
  else if (pathname.startsWith("/physio/calendar")) page = <CalendarPage pid={pid} />
  else if (pathname.startsWith("/physio/client/")) page = <ClientPage pid={pid} rid={decodeURIComponent(pathname.slice("/physio/client/".length).split("/")[0])} />
  else if (pathname.startsWith("/physio/clients")) page = <ClientsPage />
  else if (pathname.startsWith("/physio/messages")) page = <MessagesPage />
  else if (pathname.startsWith("/physio/profile")) page = <ProfilePage onSaved={loadProf} />
  else if (pathname.startsWith("/physio/practice")) page = <PracticePage />
  else if (pathname === "/admin") page = <AdminPage />
  const unread = notes.filter((n) => !n.read).length
  return (
    <div className="min-h-screen bg-bg text-fg" data-testid="physio-app">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[208px] flex-col border-r border-white/[.08] bg-panel px-3 pb-5 pt-4 lg:flex" aria-label="Navigace fyzioterapeuta">
        <Link to="/physio" className="mb-1 flex items-center gap-2.5 px-2 text-lg font-extrabold tracking-[-.04em]"><Mark size={30} /><Wordmark /></Link>
        <p className="mb-4 px-2 text-[11px] font-bold uppercase tracking-[.08em] text-fg-3">pro fyzioterapeuty</p>
        <button type="button" onClick={() => setSearch(true)} className="mb-3 flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-2 text-[13px] text-fg-3 hover:text-fg">
          <Search className="size-4" aria-hidden />Hledat klienta<kbd className="ml-auto rounded border border-white/15 px-1 text-[11px]">Ctrl K</kbd>
        </button>
        <nav className="grid gap-0.5">
          {links.map(([to, label, Icon]) => (
            <Link key={to} to={to} aria-current={on(to) ? "page" : undefined}
              className={`flex h-10 items-center gap-3 rounded-lg px-3 text-[14px] font-bold transition ${on(to) ? "bg-accent/12 text-accent" : "text-fg-2 hover:bg-white/[.05] hover:text-fg"}`}>
              <Icon className="size-[18px] shrink-0" aria-hidden />{label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto border-t border-white/[.08] px-2 pt-4 text-[12px] text-fg-3">
          <p className="truncate font-bold text-fg-2">{prof?.name || me?.name}</p>
          <p className="truncate">{prof?.clinic ? `${prof.clinic.name}${prof.clinic.city ? `, ${prof.clinic.city}` : ""}` : me?.email}</p>
          <button type="button" onClick={logout} className="mt-2 inline-flex items-center gap-1.5 font-bold text-fg-2 hover:text-fg"><LogOut className="size-3.5" aria-hidden />Odhlásit se</button>
        </div>
      </aside>
      <div className="lg:pl-[208px]">
        <header className="sticky top-0 z-30 flex h-12 items-center justify-between gap-3 border-b border-white/[.08] bg-panel/95 px-4 py-2 backdrop-blur lg:px-8">
          <Link to="/physio" className="flex items-center gap-2 text-lg lg:invisible"><Mark size={26} /><Wordmark /></Link>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setSearch(true)} aria-label="Hledat klienta" className="grid size-9 place-items-center rounded-lg text-fg-2 hover:bg-white/[.06] lg:hidden"><Search className="size-5" aria-hidden /></button>
            <div className="relative">
              <button type="button" onClick={() => { setBell(!bell); if (unread) void api.notificationsRead() }} aria-label={`Upozornění${unread ? `, ${unread} nových` : ""}`}
                className="relative grid size-9 place-items-center rounded-lg text-fg-2 hover:bg-white/[.06]" data-testid="bell">
                <Bell className="size-5" aria-hidden />
                {unread > 0 && <span className="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-alert px-1 text-[10px] font-bold text-white">{unread}</span>}
              </button>
              {bell && (
                <div className="absolute right-0 z-50 mt-1 w-80 rounded-xl border border-white/10 bg-panel p-2 text-[13px] shadow-lg">
                  {notes.length === 0 ? <p className="p-2 text-fg-3">Žádná upozornění.</p> : notes.slice(0, 12).map((n) => (
                    <p key={n.id} className="rounded-lg px-2 py-1.5"><b className="text-fg">{n.title}</b><span className="block text-[11.5px] text-fg-3">{new Date(n.at).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}</span></p>
                  ))}
                </div>
              )}
            </div>
            <button type="button" onClick={logout} className="btn btn-secondary btn-sm lg:hidden">Odhlásit</button>
          </div>
        </header>
        <main className="mx-auto max-w-[1240px] px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-5 md:px-8 lg:pb-12">
          {prof && !prof.verified && (
            <div className="mb-4 rounded-xl border border-info/30 bg-info/10 px-4 py-3 text-[13px] text-fg-2" data-testid="physio-unverified" role="status">
              <b className="text-fg">Účet čeká na ověření</b>
              {" — tým Došlapu ověří, kdo jste a vaši odbornou způsobilost. Do té doby nevidíte frontu případů ani klienty; profil, praxi a pracovní dobu si můžete připravit."}
            </div>
          )}
          {prof && !prof.complete && !pathname.startsWith("/physio/profile") && (
            <Link to="/physio/profile" className="mb-4 block rounded-xl border border-watch/30 bg-watch/10 px-4 py-3 text-[13px] hover:bg-watch/15" data-testid="physio-setup">
              <b className="text-fg">Doplňte profil a praxi</b>{" — podle města praxe se vám řadí fronta případů a běžci vás najdou v záložce Péče."}
            </Link>
          )}
          {page}
        </main>
      </div>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-white/[.08] bg-panel pb-[env(safe-area-inset-bottom)] lg:hidden" aria-label="Navigace fyzioterapeuta">
        {NAV.filter(([to]) => MOBILE.includes(to)).map(([to, label, Icon]) => (
          <Link key={to} to={to} aria-current={on(to) ? "page" : undefined}
            className={`flex min-h-[56px] flex-col items-center justify-center gap-1 text-[11px] font-bold ${on(to) ? "text-accent" : "text-fg-3"}`}>
            <Icon className="size-5" aria-hidden />{label}
          </Link>
        ))}
      </nav>
      {search && <ClientSearch onClose={() => setSearch(false)} onPick={(rid) => { setSearch(false); nav(`/physio/client/${rid}`) }} />}
    </div>
  )
}

function ClientSearch({ onClose, onPick }: { onClose: () => void; onPick: (rid: string) => void }) {
  const [q, setQ] = useState("")
  const [items, setItems] = useState<any[]>([])
  const [i, setI] = useState(0)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.focus(); api.physioClients().then((x: any) => setItems(x.items || [])).catch(() => null) }, [])
  const hits = items.filter((c) => (c.name || "").toLowerCase().includes(q.toLowerCase())).slice(0, 8)
  return (
    <div className="fixed inset-0 z-[90] grid place-items-start justify-center bg-black/40 p-4 pt-[12vh]" onClick={onClose} role="dialog" aria-label="Hledat klienta">
      <div className="w-full max-w-md rounded-xl border border-white/10 bg-panel p-2 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <input ref={ref} value={q} onChange={(e) => { setQ(e.target.value); setI(0) }} placeholder="Jméno klienta" aria-label="Jméno klienta"
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose()
            if (e.key === "ArrowDown") { e.preventDefault(); setI(Math.min(hits.length - 1, i + 1)) }
            if (e.key === "ArrowUp") { e.preventDefault(); setI(Math.max(0, i - 1)) }
            if (e.key === "Enter" && hits[i]) onPick(hits[i].runnerId)
          }}
          className="w-full rounded-lg border border-white/10 bg-bg px-3 py-2.5 text-[14px] outline-none" data-testid="client-search" />
        <ul className="mt-1">
          {hits.map((c, k) => (
            <li key={c.runnerId}><button type="button" onClick={() => onPick(c.runnerId)}
              className={`w-full rounded-lg px-3 py-2 text-left text-[14px] ${k === i ? "bg-accent/12 text-accent" : "text-fg hover:bg-white/[.05]"}`}>{c.name}</button></li>
          ))}
          {hits.length === 0 && <li className="px-3 py-2 text-[13px] text-fg-3">Nic nenalezeno.</li>}
        </ul>
      </div>
    </div>
  )
}
