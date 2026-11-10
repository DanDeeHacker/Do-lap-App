// Klienti and the client overview (report v6 Section 6.2.8, Figures A9–A10): everyone in the
// physio's care, and for one client the history, the symptom record and the data trends with an
// AI-enhanced summary (the figures come from the engine first, a language model only turns them
// into text — metrics/ai_brief.py), the programme between visits, the return-to-running plan, the
// visits with their conclusions and the chat.
import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { AlertTriangle, ArrowLeft, Bot, FileText, MessageCircle, Paperclip, Pause, Play, Plus, Printer, Search, Send, Sparkles, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { C } from "@/tokens"
import { Empty, KIND, Loading, PainAgo, QuadChip, REGIONS, RiskChip, Score, noData, shownScore, stripTags, useLoad } from "@/physio/common"
import { ConclusionSheet } from "@/physio/conclusion"
import { DocsTab } from "@/physio/docs"
import { AdherenceGrid, PlanTab } from "@/physio/plan"
import { Timeline } from "@/physio/timeline"
import { Packages, VideoNotes } from "@/physio/business"

const ATTN: Record<string, [string, "alert" | "watch" | "info"]> = {
  pain: ["bolest 4+/10", "alert"], alert: ["vysoké riziko", "alert"], setback: ["zhoršení v návratu", "watch"], message: ["nová zpráva", "info"],
}

export function ClientsPage() {
  const nav = useNavigate()
  const { d, err } = useLoad<any>(() => api.physioClients())
  const [q, setQ] = useState("")
  const list = (d?.items || []).filter((c: any) => !q.trim() || `${c.name} ${c.city || ""}`.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <>
      <p className="t-label">Klienti</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Ve vaší péči</h1>
      <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">Nahoře ti, kdo potřebují pozornost: hlášená bolest, vysoké riziko, zhoršení v návratu k běhu nebo nová zpráva.</p>
      <div className="mt-3 flex flex-wrap gap-2"><InviteClient /><NoAppClient /></div>
      <Card className="mt-5">
        <label className="flex items-center gap-2 rounded-[14px] border border-white/12 bg-white/[.04] px-3">
          <Search className="size-4 text-fg-3" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hledat klienta" aria-label="Hledat klienta" className="h-11 w-full bg-transparent text-[14px] outline-none" />
        </label>
        {!d ? <Loading err={err} /> : list.length === 0 ? <Empty>Zatím nemáte žádného klienta — převezměte případ z fronty nebo potvrďte žádost o termín.</Empty> : (
          <ul className="mt-3 divide-y divide-white/[.07]" data-testid="clients">
            {list.map((c: any) => (
              <li key={c.runnerId}>
                <button type="button" onClick={() => nav(`/physio/client/${c.runnerId}`)} className="flex w-full flex-wrap items-center gap-3 py-3 text-left hover:bg-white/[.02]">
                  <span className="grid size-10 shrink-0 place-items-center rounded-full bg-white/[.07] text-[12px] font-extrabold text-fg-2">
                    {(c.name || "?").split(" ").map((p: string) => p[0]).slice(0, 2).join("").toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <b className="flex flex-wrap items-center gap-1.5 text-[14px] text-fg">{c.name}
                      {c.attention.map((k: string) => <Chip key={k} tone={ATTN[k]?.[1] || "muted"}>{ATTN[k]?.[0] || k}</Chip>)}</b>
                    <span className="mt-0.5 block text-[12px] text-fg-3">
                      {c.next ? `další návštěva ${fmtDT(c.next.at)}` : "bez naplánované návštěvy"}
                      {c.program ? ` · program ${c.program.adherence ?? "—"} % splněno` : ""}
                      {c.rtr ? ` · návrat k běhu ${c.rtr.level}/${c.rtr.levels}` : ""}
                    </span>
                    {c.lastMessage && <span className="block truncate text-[12px] text-fg-3">{`${c.lastMessage.sender === "runner" ? "Klient" : c.lastMessage.sender === "physio" ? "Vy" : "Systém"}: ${c.lastMessage.body}`}</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    <RiskChip tier={c.a?.tier} a={c.a} />
                    <b className="w-9 text-right text-[18px] tabular-nums text-fg">{c.a?.overall == null ? "—" : Math.round(shownScore(c.a.overall)!)}</b>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}

// W2: invite by link (single use, 14 days); the link is shown once and can be copied or sent
function InviteClient() {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: "", email: "", message: "" })
  const [link, setLink] = useState<string | null>(null)
  const list = useLoad<any>(() => (open ? api.invites() : Promise.resolve({ items: [] })), [open, link])
  const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
  const ST: Record<string, string> = { open: "čeká", accepted: "přijato", revoked: "zrušeno", expired: "vypršelo" }
  return (
    <>
      <Button size="sm" icon={Plus} onClick={() => { setOpen(true); setLink(null) }}>Pozvat klienta</Button>
      <Sheet open={open} onClose={() => setOpen(false)}>
        <h2 className="font-serif text-2xl">Pozvat klienta</h2>
        <p className="mt-1 text-[12.5px] text-fg-2">Klient po přijetí odkazu přejde rovnou do vaší péče, bez fronty. Odkaz platí jednou.</p>
        {link ? (
          <div className="mt-3 grid gap-2" data-testid="invite-link">
            <input readOnly className={inp} value={link} onFocus={(e) => e.target.select()} aria-label="Odkaz pozvánky" />
            <span className="flex flex-wrap gap-2">
              <Button size="sm" onClick={async () => { try { await navigator.clipboard.writeText(link); toast({ title: "Odkaz zkopírován" }) } catch { toast({ title: "Zkopírujte odkaz ručně" }) } }}>Kopírovat</Button>
              {f.email && <a className="btn btn-outline btn-sm" href={`mailto:${encodeURIComponent(f.email)}?subject=${encodeURIComponent("Pozvánka do Došlapu")}&body=${encodeURIComponent(link)}`}>Poslat e-mailem</a>}
              <a className="btn btn-outline btn-sm" href={`sms:?&body=${encodeURIComponent(link)}`}>Poslat SMS</a>
            </span>
          </div>
        ) : (
          <div className="mt-3 grid gap-2">
            <label className="text-[12px] font-bold text-fg-2">Jméno (pro vás)<input className={inp} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="text-[12px] font-bold text-fg-2">E-mail (nepovinné)<input type="email" className={inp} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
            <label className="text-[12px] font-bold text-fg-2">Vzkaz (klient ho uvidí)<textarea rows={2} className={inp} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></label>
            <Button size="sm" onClick={async () => { try { setLink((await api.inviteCreate(f)).link) } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) } }}>Vytvořit odkaz</Button>
          </div>
        )}
        {(list.d?.items || []).length > 0 && (
          <ul className="mt-4 divide-y divide-white/[.07] text-[12.5px]">
            {list.d.items.slice(0, 10).map((i: any) => (
              <li key={i.id} className="flex items-center gap-2 py-1.5"><span className="flex-1">{i.name || i.email || "bez jména"}<span className="ml-1 text-fg-3">{fmtD(i.created_at)}</span></span>
                <Chip tone={i.status === "accepted" ? "ok" : "muted"}>{ST[i.status] || i.status}</Chip>
                {i.status === "open" && <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={async () => { await api.inviteRevoke(i.id); list.reload() }}>Zrušit</button>}</li>
            ))}
          </ul>
        )}
      </Sheet>
    </>
  )
}

// W2.7: a client who does not use the app — a patient card and documentation, no runner data
function NoAppClient() {
  const toast = useToast()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ first_name: "", last_name: "", birth_date: "", phone: "" })
  const inp = "mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px] font-normal"
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Klient bez aplikace</Button>
      <Sheet open={open} onClose={() => setOpen(false)}>
        <h2 className="font-serif text-2xl">Klient bez aplikace</h2>
        <p className="mt-1 text-[12.5px] text-fg-2">Vede se jen karta pacienta a dokumentace návštěv. Data z hodinek ani zprávy nejsou k dispozici.</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="text-[12px] font-bold text-fg-2">Jméno<input className={inp} value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} /></label>
          <label className="text-[12px] font-bold text-fg-2">Příjmení<input className={inp} value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} /></label>
          <label className="text-[12px] font-bold text-fg-2">Datum narození<input type="date" className={inp} value={f.birth_date} onChange={(e) => setF({ ...f, birth_date: e.target.value })} /></label>
          <label className="text-[12px] font-bold text-fg-2">Telefon<input className={inp} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
        </div>
        <Button className="mt-3" size="sm" disabled={!f.first_name.trim() || !f.last_name.trim()} onClick={async () => {
          try { const r = await api.clientNoApp({ ...f, birth_date: f.birth_date || null, phone: f.phone || null }); nav(`/physio/client/${r.runner_id}?tab=docs`) }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Založit kartu</Button>
      </Sheet>
    </>
  )
}

// physio brief 2026-11-09 W6.1: five tabs; the old addresses still open the right place
type Tab = "overview" | "timeline" | "plan" | "docs" | "chat"
const OLD_TAB: Record<string, Tab> = { ai: "overview", program: "plan", rtr: "plan", visits: "docs" }

export function ClientPage({ pid, rid }: { pid: string; rid: string }) {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const raw = sp.get("tab") || "overview"
  const tab = (OLD_TAB[raw] || raw) as Tab
  const toast = useToast()
  const { d, err, reload } = useLoad<any>(() => api.physioClient(rid), [rid])
  useEffect(() => {
    if (OLD_TAB[raw]) setSp({ tab: OLD_TAB[raw] }, { replace: true })
    if (raw === "rtr") setTimeout(() => document.getElementById("rtr")?.scrollIntoView(), 300)
  }, [raw, setSp])
  // physio brief R13: after a withdrawal only the documentation stays
  if (!d && err) return <><Back /><div className="mt-4"><DocsTab rid={rid} /></div></>
  if (!d) return <><Back /><Loading err={err} /></>
  const r = d.runner
  const ep = d.episode
  const fr = d.freshness
  return (
    <>
      <Back />
      {/* W6.2: sticky header — who, what, which phase, when next, how fresh the data are */}
      <div className="sticky top-0 z-10 -mx-4 mt-2 border-b border-white/[.08] bg-bg/95 px-4 py-2 backdrop-blur" data-testid="client-header">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="font-serif text-[26px] leading-tight tracking-[-.02em]">{r.name}
              <span className="ml-2 align-middle text-[12.5px] font-normal text-fg-2">
                {[r.age ? `${r.age} let` : null, r.sex === "f" ? "žena" : r.sex === "m" ? "muž" : null, r.city].filter(Boolean).join(" · ")}</span></h1>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-2">
              <span>{ep?.diagnosis ? `${ep.code ? `${ep.code} ` : ""}${ep.diagnosis}${ep.side ? ` (${ep.side === "L" ? "vlevo" : ep.side === "R" ? "vpravo" : "oboustranně"})` : ""}` : "bez diagnózy"}</span>
              {d.phase && <span>{`fáze: ${d.phase}`}</span>}
              <span>{d.next_visit ? `další návštěva ${fmtDT(d.next_visit.at)}` : "bez další návštěvy"}</span>
              <span className={fr?.status === "fresh" ? "" : "text-watch"}>{fr?.last_data_at ? `data ${fmtD(fr.last_data_at)}` : "bez dat z hodinek"}</span>
              {d.no_app && <Chip>bez aplikace</Chip>}
              {(d.limits || []).map((t: string) => <Chip key={t} tone="watch">{t}</Chip>)}
            </p>
          </div>
          <span className="flex flex-wrap items-center gap-2">
            <RiskChip tier={d.a.tier} a={d.a} /><QuadChip q={d.a.quadrant} a={d.a} />
            {d.next_visit && <Button size="sm" variant="outline" onClick={() => nav(`/physio/client/${rid}/priprava/${d.next_visit.id}`)}>Příprava</Button>}
            <Button size="sm" icon={Plus} onClick={() => nav(`/physio/calendar?client=${rid}`)}>Nová návštěva</Button>
            {!d.no_app && <Button size="sm" variant="outline" icon={MessageCircle} onClick={() => setSp({ tab: "chat" }, { replace: true })}>Napsat</Button>}
            <ClientMenu d={d} rid={rid} onChange={reload} />
          </span>
        </div>
        <Segmented className="mt-2" value={tab} onChange={(k) => setSp({ tab: k }, { replace: true })} ariaLabel="Části karty klienta"
          options={[["overview", "Přehled"], ["timeline", "Časová osa"], ["plan", "Plán"], ["docs", "Dokumentace"], ["chat", "Zprávy"]] as const} />
      </div>
      {!d.share && <p className="mt-3 flex items-center gap-2 rounded-xl bg-watch/10 px-3 py-2 text-[12.5px] text-watch-soft">
        <AlertTriangle className="size-4" aria-hidden />Klient vypnul sdílení dat z hodinek — vidíte jen hodnocení, check-iny a zprávy.</p>}
      <div className="mt-4" data-testid={`client-tab-${tab}`}>
        {tab === "overview" && <Overview d={d} rid={rid} onChange={reload} onClose={async (iid) => {
          if (!window.confirm("Uzavřít zranění? Klient dostane zprávu a engine přejde do návratu k běhu.")) return
          try { await api.physioCloseInjury(rid, iid); toast({ title: "Zranění uzavřeno" }); reload() }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }} />}
        {tab === "timeline" && <Timeline rid={rid} />}
        {tab === "plan" && <PlanTab rid={rid} d={d} onChange={reload} />}
        {tab === "docs" && <VisitsTab rid={rid} d={d} onChange={reload} pid={pid} />}
        {tab === "chat" && (d.no_app ? <Card><Empty>Klient aplikaci nepoužívá — zprávy nejsou k dispozici.</Empty></Card> : <ChatTab rid={rid} />)}
      </div>
    </>
  )
}

// W1.5 transfer to a colleague and the claim release, out of the way of the daily actions
function ClientMenu({ d, rid, onChange }: { d: any; rid: string; onChange: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [to, setTo] = useState("")
  if (!d.claim?.releasable && !(d.colleagues || []).length) return null
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Další</Button>
      <Sheet open={open} onClose={() => setOpen(false)}>
        <h2 className="font-serif text-2xl">Klient</h2>
        {(d.colleagues || []).length > 0 && (
          <div className="mt-3 grid gap-2">
            <label className="text-[12px] font-bold text-fg-2">Předat kolegovi z praxe
              <select className="mt-1 w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px]" value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">Vyberte…</option>{d.colleagues.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            <p className="text-[12px] text-fg-3">Dokumentace zůstává v praxi; nový fyzioterapeut ji uvidí a klient dostane zprávu.</p>
            <Button size="sm" disabled={!to} onClick={async () => {
              try { await api.clientTransfer(rid, to); toast({ title: "Klient předán" }); window.location.assign("/physio/clients") }
              catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
            }}>Předat</Button>
          </div>
        )}
        {d.claim?.releasable && (
          <Button className="mt-4" size="sm" variant="outline" onClick={async () => {
            if (!window.confirm("Vrátit případ do fronty? Klient dostane zprávu a jeho data se vám zavřou.")) return
            try { await api.triageRelease(d.claim.id); toast({ title: "Případ je zpět ve frontě" }); window.location.assign("/physio/queue") }
            catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }); onChange() }
          }}>Vrátit do fronty</Button>
        )}
      </Sheet>
    </>
  )
}
// physio brief 2026-11-09 P0.11: back goes where the physio came from (Kalendář, Fronta…), Klienti otherwise
function Back() {
  const nav = useNavigate()
  const hasHistory = typeof window !== "undefined" && (window.history.state?.idx ?? 0) > 0
  return hasHistory
    ? <button type="button" onClick={() => nav(-1)} className="inline-flex items-center gap-1 text-[12.5px] font-bold text-fg-2 hover:text-fg"><ArrowLeft className="size-4" aria-hidden />Zpět</button>
    : <Link to="/physio/clients" className="inline-flex items-center gap-1 text-[12.5px] font-bold text-fg-2 hover:text-fg"><ArrowLeft className="size-4" aria-hidden />Klienti</Link>
}

function Overview({ d, rid, onChange, onClose }: { d: any; rid: string; onChange: () => void; onClose?: (iid: number) => void }) {
  const a = d.a
  const maxKm = Math.max(1, ...d.weeks.map((w: any) => w.km))
  const painDays = d.checkins.filter((c: any) => (c.pain || 0) > 0)
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h2 className="font-serif text-xl">Dnešní stav</h2>
        {noData(a) && (
          <p className="mt-2 rounded-xl bg-white/[.05] px-3 py-2 text-[12.5px] leading-[17px] text-fg-2" data-testid="stale-banner">
            {a.freshness?.last_data_at
              ? `Data nejsou aktuální. Poslední záznam ${fmtD(a.freshness.last_data_at)} (před ${a.freshness.days_since} dny). Stav ani doporučení se nepočítají.`
              : "Klient zatím nemá žádná data. Stav ani doporučení se nepočítají."}
          </p>
        )}
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
          <Score v={shownScore(a.overall)} label="Skóre" hint="100 = bez obtíží" /><Score v={a.readiness} label="Připravenost" hint="100 = plná" />
          <Score v={a.symp} label="Příznaky" hint="0 = v normě" />
          <Score v={a.load} label="Zátěž" hint="0 = v normě" /><Score v={a.mech} label="Mechanika" hint="0 = v normě" />
        </div>
        <p className="mt-2 text-[12px] text-fg-3">{"Poslední bolest: "}<PainAgo p={a.lastPain} />{a.lastPain?.site ? ` · ${a.lastPain.site}` : ""}</p>
        {/* physio brief 2026-11-09 P0.2: exactly what the client's Dnes and Trénink say today */}
        {(a.careDirective?.headline_cs || a.guidance?.typeLabel) && (
          <p className="mt-3 text-[13px] text-fg-2" data-testid="client-sees">{"Klient dnes vidí: "}
            <b className="text-fg">{a.careDirective?.headline_cs || a.guidance?.typeLabel}</b></p>
        )}
        {a.careDirective?.source === "engine" && (a.guidance?.reasons || []).slice(0, 3).map((x: string, i: number) => <p key={i} className="mt-1 text-[12px] leading-[17px] text-fg-3">{`• ${stripTags(x)}`}</p>)}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Co nejvíc ovlivňuje skóre</h2>
        {a.signals.length === 0 ? <Empty>Žádný signál mimo normu.</Empty> : (
          <ul className="mt-2 divide-y divide-white/[.06] text-[13px]">
            {a.signals.map((s: any) => (
              <li key={s.id || s.name} className="flex items-start gap-2 py-2">
                <Chip>{s.grade}</Chip>
                <span className="min-w-0 flex-1"><b className="text-fg">{s.name}</b><span className="block text-[12px] text-fg-3">{s.val}{s.detail ? ` · ${stripTags(s.detail)}` : ""}</span></span>
                <span className="text-[12px] tabular-nums text-fg-2">{s.pts ? `−${Math.round(s.pts)}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {/* W6.5 body map from the check-ins' pain points; W6.6 programme adherence by week */}
      <Card>
        <h2 className="font-serif text-xl">Kde to bolí</h2>
        {(d.pain_map || []).length === 0 ? <Empty>Za posledních 6 týdnů bez hlášené bolesti.</Empty> : (
          <ul className="mt-2 grid gap-1.5 text-[13px]" data-testid="pain-map">
            {d.pain_map.slice(0, 6).map((x: any) => (
              <li key={x.region} className="flex items-center gap-2">
                <span className={`grid h-6 w-10 place-items-center rounded text-[12px] font-bold tabular-nums ${x.max >= 5 ? "ph-risk-high" : x.max >= 3 ? "ph-risk-med" : "ph-unknown"}`}>{`${x.max}/10`}</span>
                <b className="min-w-0 flex-1">{REGION_CS[x.region] || x.region}</b>
                <span className="text-[12px] text-fg-3">{`${x.count}× · naposledy ${fmtD(x.last)}`}</span>
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 font-bold">Plnění programu</h3>
        {d.adherence ? <AdherenceGrid adh={d.adherence} /> : <p className="mt-1 text-[12.5px] text-fg-3">Klient nemá od vás aktivní program.</p>}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Běžecký objem po týdnech</h2>
        {d.weeks.length === 0 ? <Empty>Data z hodinek klient nesdílí.</Empty> : (
          <div className="mt-4 flex h-32 items-end gap-1.5" role="img" aria-label="Kilometry za posledních 12 týdnů">
            {d.weeks.map((w: any) => (
              <div key={w.week} className="flex flex-1 flex-col items-center gap-1" title={`${fmtD(w.week)}: ${String(w.km).replace(".", ",")} km`}>
                <span className="text-[10px] tabular-nums text-fg-3">{w.km ? Math.round(w.km) : ""}</span>
                <span className="w-full rounded-t-[4px]" style={{ height: `${Math.max(2, (w.km / maxKm) * 96)}px`, background: C.info }} />
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-[11.5px] text-fg-3">{d.weeks.length ? `${fmtD(d.weeks[0].week)} – ${fmtD(d.weeks[d.weeks.length - 1].week)}, km za týden od pondělí` : ""}</p>
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Příznaky za 6 týdnů</h2>
        <p className="mt-1 text-[12px] text-fg-2">{`Check-in ${d.checkins.length}×, bolest hlášena ${painDays.length}×.`}</p>
        <div className="mt-3 flex flex-wrap gap-1" role="img" aria-label="Bolest v check-inech">
          {d.checkins.map((c: any, i: number) => {
            const p = c.pain || 0
            return <span key={i} title={`${fmtD(c.date)}: bolest ${p}/10${c.site ? ` (${c.site})` : ""}`} className="size-4 rounded-[3px]"
              style={{ background: p >= 5 ? C.alert : p >= 3 ? C.watch : p > 0 ? C.watchSoft : "rgba(255,255,255,.08)" }} />
          })}
        </div>
        <ul className="mt-3 grid gap-1 text-[12.5px]">
          {painDays.slice(-5).reverse().map((c: any, i: number) => (
            <li key={i} className="text-fg-2"><b className="text-fg">{`${c.pain}/10`}</b>{` ${c.site || ""} · ${fmtD(c.date)}`}
              {c.limits ? " · omezuje pohyb" : ""}{c.modified ? " · upravil běh" : ""}{c.note ? ` — „${c.note}“` : ""}</li>
          ))}
        </ul>
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Poslední aktivity</h2>
        {d.activities.length === 0 ? <Empty>Bez aktivit.</Empty> : (
          <ul className="mt-2 divide-y divide-white/[.06] text-[12.5px]">
            {d.activities.map((x: any) => (
              <li key={x.id} className="flex items-center gap-2 py-1.5">
                <span className="w-14 text-fg-3">{fmtD(x.date)}</span>
                <span className="min-w-0 flex-1 truncate text-fg">{x.title}</span>
                <span className="tabular-nums text-fg-2">{x.km ? `${String(Math.round(x.km * 10) / 10).replace(".", ",")} km` : x.min ? `${Math.round(x.min)} min` : ""}</span>
                {x.rpe != null && <span className="text-fg-3">{`RPE ${x.rpe}`}</span>}
                {x.pain ? <Chip tone="watch">{`bolest ${x.pain}`}</Chip> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Anamnéza a zranění</h2>
        <Anamnesis rid={rid} text={d.anamnesis} onChange={onChange} />
        <p className="mt-2 text-[12.5px] text-fg-2">
          {d.runner.prior_injury ? <>{"Dřívější zranění: "}<b className="text-fg">{d.runner.prior_injury}</b>{d.runner.prior_injury_date ? ` (${fmtD(d.runner.prior_injury_date)})` : ""}</> : "Dřívější zranění neuvedl."}
          {d.runner.goal_race ? <>{" · cíl: "}{d.runner.goal_race}{d.runner.goal_date ? ` ${fmtD(d.runner.goal_date)}` : ""}</> : null}
        </p>
        {d.injuries.length > 0 && (
          <ul className="mt-2 grid gap-1 text-[12.5px]">
            {d.injuries.map((i: any, k: number) => (
              <li key={k} className="text-fg-2">{fmtD(i.at)}{" · "}{i.status === "none" ? "bez obtíží" : `${i.region || "obtíže"} ${i.side || ""}`}
                {i.severity ? ` · závažnost ${i.severity}` : ""}{" "}{i.confirmed ? <Chip tone="ok">potvrzeno fyzioterapeutem</Chip> : <Chip>hlášení běžce</Chip>}
                {i.status === "resolved" && <>{" "}<Chip>uzavřeno</Chip></>}
                {i.status === "active" && i.confirmed && onClose && (
                  <button type="button" className="ml-2 text-[12px] font-bold text-accent hover:underline" onClick={() => onClose(i.id)}>Uzavřít zranění</button>
                )}</li>
            ))}
          </ul>
        )}
      </Card>
      <div className="lg:col-span-2"><AiTab rid={rid} /></div>
    </div>
  )
}

const REGION_CS: Record<string, string> = Object.fromEntries(REGIONS)

// W6.4: the anamnesis is the physio's own text on the patient card, editable in place
function Anamnesis({ rid, text, onChange }: { rid: string; text?: string | null; onChange: () => void }) {
  const toast = useToast()
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(text || "")
  if (!edit) {
    return (
      <div className="mt-2 text-[13px]">
        {text ? <p className="whitespace-pre-line text-fg">{text}</p> : <p className="text-fg-3">Anamnéza zatím není zapsaná.</p>}
        <button type="button" className="mt-1 text-[12px] font-bold text-accent hover:underline" onClick={() => { setV(text || ""); setEdit(true) }}>{text ? "Upravit anamnézu" : "Zapsat anamnézu"}</button>
      </div>
    )
  }
  return (
    <div className="mt-2 grid gap-2">
      <textarea value={v} onChange={(e) => setV(e.target.value)} rows={5} aria-label="Anamnéza"
        className="w-full rounded-lg border border-white/15 bg-panel px-2.5 py-1.5 text-[13px]" />
      <span className="flex gap-2">
        <Button size="sm" onClick={async () => {
          try { await api.patientCardSave(rid, { anamnesis: v }); toast({ title: "Anamnéza uložena" }); setEdit(false); onChange() }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }}>Uložit</Button>
        <Button size="sm" variant="outline" onClick={() => setEdit(false)}>Zrušit</Button>
      </span>
    </div>
  )
}

const INTENTS: [string, string][] = [["summary", "Posledních 28 dní"], ["change", "Co se změnilo"], ["where", "Kde může být problém"], ["program", "Co upravit v programu"], ["missing", "Jaká data chybí"]]

// physio brief 2026-11-09 P0.1: say where the text comes from, never show a stale answer, and offer the
// free-text question only when a language model is actually switched on
const AI_REASON: Record<string, string> = {
  not_configured: "Jazykový model není zapnutý. Přehled skládá aplikace přímo z dat.",
  no_consent: "Klient nedal souhlas s AI. Přehled je složený přímo z dat a nic se neodesílá mimo Došlap.",
  timeout: "Jazykový model neodpověděl včas. Zobrazuji přehled přímo z dat.",
  error: "Jazykový model selhal. Zobrazuji přehled přímo z dat.",
}

function AiTab({ rid }: { rid: string }) {
  const toast = useToast()
  const caps = useLoad<any>(() => api.physioMe().then((m: any) => m.capabilities || {}), [])
  const [intent, setIntent] = useState("summary")
  const [b, setB] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<{ role: string; content: string }[]>([])
  const [q, setQ] = useState("")
  const seq = useRef(0)
  useEffect(() => {
    const mine = ++seq.current                  // only the answer to the latest preset may land
    setB(null)
    api.aiBrief(rid, intent).then((r: any) => { if (seq.current === mine) setB(r) })
      .catch((e: any) => { if (seq.current === mine) setB({ error: e?.message || "Nepodařilo se" }) })
  }, [rid, intent])
  const intents = INTENTS.filter(([k]) => k !== "where" || caps.d?.hypotheses)
  const ask = async () => {
    const text = q.trim()
    if (!text) return
    const h = [...hist, { role: "user", content: text }]
    setHist(h); setBusy(true)
    setQ((cur) => (cur.trim() === text ? "" : cur))   // keep anything typed while sending
    try { const r = await api.aiChat(rid, text, hist); setHist([...h, { role: "assistant", content: r.reply }]) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }); setHist(hist); setQ(text) }
    finally { setBusy(false) }
  }
  const llmText = b?.source === "llm"
  return (
    <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden />
          <h2 className="font-serif text-xl" data-testid="ai-title">{llmText ? "AI shrnutí před návštěvou" : "Přehled z dat před návštěvou"}</h2>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {intents.map(([k, l]) => (
            <button key={k} type="button" aria-pressed={intent === k} onClick={() => setIntent(k)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-bold ${intent === k ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>{l}</button>
          ))}
        </div>
        {!b ? <p className="mt-4 animate-pulse text-sm text-fg-2">Počítám z dat…</p> : b.error ? <p className="mt-4 text-sm text-alert">{b.error}</p> : (
          <div className="mt-4 grid gap-3" data-testid="ai-brief">
            {b.reason && AI_REASON[b.reason] && <p className="rounded-lg border border-white/10 px-3 py-2 text-[12px] text-fg-2" data-testid="ai-reason">{AI_REASON[b.reason]}</p>}
            {b.sections.map((s: any, i: number) => (
              <section key={i}>
                <h3 className="text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">{s.h}</h3>
                <ul className="mt-1 grid gap-1.5 text-[13px] leading-[19px] text-fg-soft">{s.items.map((it: string, k: number) => <li key={k} className="whitespace-pre-line">{stripTags(it)}</li>)}</ul>
              </section>
            ))}
            <p className="rounded-lg bg-white/[.04] px-3 py-2 text-[11.5px] text-fg-3">{b.caveat}{llmText ? " Text upravil jazykový model, čísla jsou z enginu." : ""}</p>
          </div>
        )}
      </Card>
      <Card>
        <h2 className="flex items-center gap-2 font-serif text-xl"><Bot className="size-5 text-fg-2" aria-hidden />Zeptejte se na data klienta</h2>
        {!caps.d ? <Loading err={caps.err} /> : !caps.d.llm ? (
          <p className="mt-3 text-[13px] text-fg-2" data-testid="ai-chat-off">Dotazy vlastními slovy zatím nejsou zapnuté.</p>
        ) : (
          <>
            <div className="mt-3 grid max-h-[420px] gap-2 overflow-y-auto">
              {hist.length === 0 && <p className="text-[12px] text-fg-3">Např. „Jak se měnila zátěž poslední dva týdny?“ Odpovědi vycházejí z dat a nenahrazují vyšetření.</p>}
              {hist.map((m, i) => (
                <p key={i} className={`whitespace-pre-line rounded-xl px-3 py-2 text-[13px] leading-[18px] ${m.role === "user" ? "ml-8 bg-accent/12 text-fg" : "mr-4 bg-white/[.05] text-fg-soft"}`}>{m.content}</p>
              ))}
            </div>
            <form className="mt-3 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void ask() }}>
              <textarea value={q} onChange={(e) => setQ(e.target.value)} aria-label="Otázka" maxLength={1000} rows={2}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask() } }}
                className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" placeholder="Otázka k datům klienta" />
              <Button size="sm" icon={Send} busy={busy} type="submit">Zeptat se</Button>
            </form>
          </>
        )}
      </Card>
    </div>
  )
}

function VisitsTab({ rid, d, onChange }: { rid: string; d: any; onChange: () => void; pid: string }) {
  const [concl, setConcl] = useState<any>(null)
  const toast = useToast()
  return (
    <div className="grid gap-4">
      <Card>
        <h2 className="font-serif text-xl">Návštěvy</h2>
        {d.bookings.length === 0 ? <Empty>S tímto klientem zatím nemáte termín.</Empty> : (
          <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="visits">
            {d.bookings.map((b: any) => (
              <li key={b.id} className="flex flex-wrap items-center gap-2 py-2.5">
                <span className="min-w-0 flex-1"><b className="text-fg">{fmtDT(b.at)}</b><span className="block text-[12px] text-fg-3">{KIND[b.kind] || b.kind}{` · ${STATUS[b.status] || b.status}`}</span></span>
                {b.conclusion?.status === "approved" ? <Chip tone="ok">záznam schválen</Chip> : b.conclusion ? <Chip tone="watch">rozepsaný záznam</Chip> : null}
                {["confirmed", "completed"].includes(b.status) && new Date(b.at).getTime() <= Date.now() &&
                  <Button size="sm" variant="outline" icon={FileText} onClick={() => setConcl({ id: b.id, slot_at: b.at, kind: b.kind, runner: d.runner })}>Záznam</Button>}
                {["confirmed", "completed"].includes(b.status) && new Date(b.at).getTime() <= Date.now() &&
                  <Button size="sm" variant="outline" onClick={async () => {
                    try { const i = await api.invoiceIssue(b.id); toast({ title: `Doklad ${i.number}` }) } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
                  }}>Doklad</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Packages rid={rid} />
      <DocsTab rid={rid} />
      <ConclusionSheet booking={concl} onClose={() => setConcl(null)} onDone={() => { setConcl(null); onChange() }} />
    </div>
  )
}

const STATUS: Record<string, string> = { confirmed: "potvrzeno", requested: "čeká na potvrzení", completed: "proběhla", no_show: "nedostavil(a) se", cancelled: "zrušeno", declined: "odmítnuto" }

// W13: attachments (photo or short video, checked on the server) and the physio's quick replies
function ChatTab({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any[]>(() => api.messages(rid), [rid])
  const quick = useLoad<any>(() => api.physioMe().then((m: any) => m.quick_replies || []), [])
  const [body, setBody] = useState("")
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const msgs = useMemo(() => d || [], [d])
  const send = async () => {
    const sent = body
    if (!sent.trim() || busy) return
    setBusy(true)
    // physio brief 2026-11-09 P0.11: clear only what was sent — text typed while sending stays
    try { await api.send(rid, "physio", sent.trim()); setBody((cur) => (cur.startsWith(sent) ? cur.slice(sent.length) : cur)); reload() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  const attach = async (f?: File) => {
    if (!f) return
    setBusy(true)
    try { await api.messageAttach(rid, f, body.trim()); setBody(""); reload() }
    catch (e: any) { toast({ title: e?.message || "Soubor se nepodařilo odeslat" }) }
    finally { setBusy(false); if (file.current) file.current.value = "" }
  }
  const replies: string[] = (quick.d && quick.d.length ? quick.d : QUICK_DEFAULT)
  return (
    <Card>
      <h2 className="flex items-center gap-2 font-serif text-xl"><MessageCircle className="size-5 text-fg-2" aria-hidden />Zprávy s klientem</h2>
      <div className="mt-3 grid max-h-[520px] gap-2 overflow-y-auto" data-testid="chat">
        {msgs.length === 0 && <Empty>Zatím žádné zprávy.</Empty>}
        {msgs.map((m: any) => (
          <div key={m.id} className={`max-w-[85%] rounded-xl px-3 py-2 text-[13px] leading-[18px] ${m.sender === "physio" ? "ml-auto bg-accent/12 text-fg" : m.sender === "system" ? "mx-auto bg-white/[.03] text-[12px] text-fg-3" : "bg-white/[.05] text-fg-soft"}`}>
            {m.attachment_path && <Attachment m={m} />}
            {m.body && <p className="whitespace-pre-line">{m.body}</p>}
            <p className="mt-0.5 text-[10.5px] text-fg-3">{fmtDT(m.created_at)}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Rychlé odpovědi">
        {replies.map((t) => <button key={t} type="button" onClick={() => setBody((b) => (b ? `${b} ${t}` : t))}
          className="rounded-full border border-white/15 px-2.5 py-1 text-[12px] text-fg-2 hover:border-accent hover:text-accent">{t}</button>)}
      </div>
      <form className="mt-2 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} aria-label="Zpráva" rows={2}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send() } }}
          className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" placeholder="Napište klientovi (Shift+Enter = nový řádek)" />
        <input ref={file} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" className="hidden"
          onChange={(e) => void attach(e.target.files?.[0])} aria-label="Příloha" />
        <Button size="sm" variant="outline" icon={Paperclip} type="button" onClick={() => file.current?.click()} disabled={busy}>Příloha</Button>
        <Button size="sm" icon={Send} busy={busy} type="submit">Odeslat</Button>
      </form>
      <p className="mt-1 text-[11.5px] text-fg-3">Fotka do 8 MB, video do 50 MB. Příloha je jen pro vás a klienta.</p>
    </Card>
  )
}

const QUICK_DEFAULT = ["Děkuji, podívám se na to.", "Pokračujte podle plánu.", "Dnes prosím vynechte běh.", "Zavolám vám."]

export function Attachment({ m }: { m: any }) {
  const url = `/api/messages/${m.id}/attachment`
  if ((m.attachment_type || "").startsWith("image/")) return <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={m.attachment_name || "fotka"} className="mb-1 max-h-60 rounded-lg" /></a>
  // physio brief M3: a client's video gets the physio's notes at moments of it
  if ((m.attachment_type || "").startsWith("video/")) return <div className="mb-1"><video id={`v${m.id}`} src={url} controls className="max-h-60 rounded-lg" /><VideoNotes m={m} physio videoId={`v${m.id}`} /></div>
  return <a href={url} className="mb-1 block text-accent underline">{m.attachment_name || "příloha"}</a>
}
