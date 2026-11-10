// Klienti and the client overview (report v6 Section 6.2.8, Figures A9–A10): everyone in the
// physio's care, and for one client the history, the symptom record and the data trends with an
// AI-enhanced summary (the figures come from the engine first, a language model only turns them
// into text — metrics/ai_brief.py), the programme between visits, the return-to-running plan, the
// visits with their conclusions and the chat.
import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { AlertTriangle, ArrowLeft, Bot, FileText, MessageCircle, Pause, Play, Plus, Printer, Search, Send, Sparkles, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { C } from "@/tokens"
import { Empty, KIND, Loading, PainAgo, QuadChip, RiskChip, Score, noData, shownScore, stripTags, useLoad } from "@/physio/common"
import { ConclusionSheet } from "@/physio/conclusion"
import { DocsTab } from "@/physio/docs"

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

type Tab = "overview" | "ai" | "program" | "rtr" | "visits" | "chat"

export function ClientPage({ pid, rid }: { pid: string; rid: string }) {
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get("tab") as Tab) || "overview"
  const toast = useToast()
  const { d, err, reload } = useLoad<any>(() => api.physioClient(rid), [rid])
  // physio brief R13: after a withdrawal only the documentation stays
  if (!d && err) return <><Back /><div className="mt-4"><DocsTab rid={rid} /></div></>
  if (!d) return <><Back /><Loading err={err} /></>
  const r = d.runner
  return (
    <>
      <Back />
      <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="t-label">Klient</p>
          <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">{r.name}</h1>
          <p className="mt-1 text-[12.5px] text-fg-2">
            {[r.age ? `${r.age} let` : null, r.sex === "f" ? "žena" : r.sex === "m" ? "muž" : null, r.city,
              r.running_since ? `běhá od roku ${String(r.running_since).slice(0, 4)}` : null, r.device].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className="flex flex-wrap items-center gap-2"><RiskChip tier={d.a.tier} a={d.a} /><QuadChip q={d.a.quadrant} a={d.a} />
          {d.claim?.releasable && (
            <Button size="sm" variant="outline" onClick={async () => {
              if (!window.confirm("Vrátit případ do fronty? Klient dostane zprávu a jeho data se vám zavřou.")) return
              try { await api.triageRelease(d.claim.id); toast({ title: "Případ je zpět ve frontě" }); window.location.assign("/physio/queue") }
              catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
            }}>Vrátit do fronty</Button>
          )}</span>
      </div>
      {!d.share && <p className="mt-3 flex items-center gap-2 rounded-xl bg-watch/10 px-3 py-2 text-[12.5px] text-watch-soft">
        <AlertTriangle className="size-4" aria-hidden />Klient vypnul sdílení dat z hodinek — vidíte jen hodnocení, check-iny a zprávy.</p>}
      <Segmented className="mt-4" value={tab} onChange={(k) => setSp({ tab: k }, { replace: true })} ariaLabel="Části přehledu klienta"
        options={[["overview", "Přehled"], ["ai", "AI shrnutí"], ["program", "Program"], ["rtr", "Návrat k běhu"], ["visits", "Návštěvy"], ["chat", "Zprávy"]] as const} />
      <div className="mt-4" data-testid={`client-tab-${tab}`}>
        {tab === "overview" && <Overview d={d} onClose={async (iid) => {
          if (!window.confirm("Uzavřít zranění? Klient dostane zprávu a engine přejde do návratu k běhu.")) return
          try { await api.physioCloseInjury(rid, iid); toast({ title: "Zranění uzavřeno" }); reload() }
          catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
        }} />}
        {tab === "ai" && <AiTab rid={rid} />}
        {tab === "program" && <ProgramTab rid={rid} />}
        {tab === "rtr" && <RtrTab rid={rid} plan={d.rtr} a={d.a} onChange={reload} />}
        {tab === "visits" && <VisitsTab rid={rid} d={d} onChange={reload} pid={pid} />}
        {tab === "chat" && <ChatTab rid={rid} />}
      </div>
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

function Overview({ d, onClose }: { d: any; onClose?: (iid: number) => void }) {
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

function ProgramTab({ rid }: { rid: string }) {
  const toast = useToast()
  const { d: box, err, reload } = useLoad<any>(() => api.program(rid).then((x: any) => ({ p: x })), [rid])   // null = no programme yet
  const p = box?.p
  const [lib, setLib] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState("")
  const act = async (k: string, fn: () => Promise<any>, msg: string) => {
    setBusy(k)
    try { await fn(); toast({ title: msg }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  if (!box) return <Card><Loading err={err} /></Card>
  if (!p) {
    return (
      <Card>
        <h2 className="font-serif text-xl">Program</h2>
        <Empty>Klient zatím nemá program od vás.</Empty>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button icon={Plus} busy={busy === "draft"} onClick={() => act("draft", () => api.programDraft(rid), "Návrh programu je připravený — upravte ho a pošlete")}>Navrhnout preventivní program</Button>
        </div>
      </Card>
    )
  }
  const ex = p.exercises || []
  return (
    <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-serif text-xl">{p.name}</h2>
            <p className="text-[12px] text-fg-3">{p.status === "sent" ? `poslán ${fmtD(p.sent_at)}` : "koncept — klient ho zatím nevidí"}
              {p.ends_on ? (p.ended ? ` · program skončil ${fmtD(p.ends_on)}` : ` · končí ${fmtD(p.ends_on)}`) : ""}</p>
          </div>
          <Button size="sm" variant="outline" icon={Plus} onClick={() => setLib(true)}>Přidat cvik</Button>
        </div>
        {ex.length === 0 ? <Empty>Program je prázdný.</Empty> : (
          <ul className="mt-3 grid gap-2" data-testid="program-exercises">
            {ex.map((e: any) => <ExerciseRow key={e.id} e={e} sent={p.status === "sent"} onChange={reload} />)}
          </ul>
        )}
        <div className="mt-4 grid gap-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Zpráva pro klienta k programu (nepovinné)" aria-label="Zpráva k programu"
            className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
          {/* physio brief 2026-11-09 P0.8: the message box clears after a successful send */}
          <Button icon={Send} busy={busy === "send"} disabled={!ex.length} onClick={() => act("send", async () => { await api.programSend(p.id, note || undefined); setNote("") }, "Program je u klienta")}>
            {p.status === "sent" ? "Poslat aktualizaci" : "Poslat klientovi"}
          </Button>
        </div>
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Historie změn</h2>
        <p className="mt-1 text-[12px] text-fg-2">Klient vidí každou změnu i s důvodem.</p>
        {(p.revisions || []).length === 0 ? <Empty>Zatím beze změn.</Empty> : (
          <ul className="mt-2 grid gap-2 text-[12.5px]">
            {[...p.revisions].reverse().map((r: any) => (
              <li key={r.id} className="rounded-lg bg-white/[.03] px-3 py-2"><span className="text-fg-3">{fmtDT(r.at)}</span>
                <span className="block text-fg">{r.note}</span>
                {(r.changes || []).map((c: string, i: number) => <span key={i} className="block text-fg-2">{`• ${c}`}</span>)}</li>
            ))}
          </ul>
        )}
      </Card>
      <Library open={lib} onClose={() => setLib(false)} have={new Set(ex.map((e: any) => e.library_id).filter(Boolean))} onPick={async (x) => {
        await act(`add${x.id}`, () => api.exerciseAdd(p.id, { name: x.name, dose: x.dose, per_week: x.per_week, cue: x.cue, library_id: x.id }), `Přidáno: ${x.name}`)
      }} />
    </div>
  )
}

function ExerciseRow({ e, sent, onChange }: { e: any; sent: boolean; onChange: () => void }) {
  const toast = useToast()
  const [edit, setEdit] = useState(false)
  const [dose, setDose] = useState(e.dose || "")
  const [per, setPer] = useState<number>(e.per_week || 3)
  const [cue, setCue] = useState(e.cue || "")
  const [why, setWhy] = useState("")
  const save = async () => {
    try { await api.exerciseEdit(e.id, { dose, per_week: per, cue }, why || undefined); toast({ title: "Cvik upraven" }); setEdit(false); onChange() }
    catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
  }
  const remove = async () => {
    try { await api.exerciseRemove(e.id); toast({ title: `Odebráno: ${e.name}` }); onChange() } catch (x: any) { toast({ title: x?.message || "Nepodařilo se" }) }
  }
  const pct = e.target_count ? Math.round(100 * (e.done_count || 0) / e.target_count) : null
  const inp = "rounded-lg border border-white/10 bg-panel px-2 py-1.5 text-[12.5px]"
  return (
    <li className="rounded-xl border border-white/[.07] bg-white/[.03] p-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <b className="min-w-0 flex-1 text-fg">{e.name}</b>
        {pct != null && <Chip tone={pct >= 70 ? "ok" : pct >= 30 ? "watch" : "muted"}>{`${e.done_count || 0}/${e.target_count} splněno`}</Chip>}
        <button type="button" className="text-[12px] font-bold text-accent hover:underline" onClick={() => setEdit(!edit)}>{edit ? "Zavřít" : "Upravit"}</button>
        <button type="button" aria-label={`Odebrat ${e.name}`} className="text-fg-3 hover:text-alert" onClick={remove}><Trash2 className="size-4" aria-hidden /></button>
      </div>
      {!edit ? <p className="mt-1 text-[12px] text-fg-2">{`${e.dose} · ${e.per_week}× týdně`}{e.cue ? ` · ${e.cue}` : ""}</p> : (
        <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
          <input value={dose} onChange={(x) => setDose(x.target.value)} aria-label="Dávka" className={inp} />
          <select value={per} onChange={(x) => setPer(Number(x.target.value))} aria-label="Kolikrát týdně" className={inp}>
            {[1, 2, 3, 4, 5, 6, 7].map((n) => <option key={n} value={n}>{`${n}× týdně`}</option>)}
          </select>
          <input value={cue} onChange={(x) => setCue(x.target.value)} aria-label="Pokyn" placeholder="Pokyn k provedení" className={`${inp} sm:col-span-2`} />
          <input value={why} onChange={(x) => setWhy(x.target.value)} aria-label="Důvod změny" placeholder={sent ? "Důvod změny (povinný, klient ho uvidí)" : "Důvod změny (klient ho uvidí)"} className={`${inp} sm:col-span-2`} />
          <Button size="sm" disabled={!dose.trim() || (sent && !why.trim())} onClick={save}>Uložit</Button>
        </div>
      )}
    </li>
  )
}

function Library({ open, onClose, onPick, have }: { open: boolean; onClose: () => void; onPick: (x: any) => Promise<void>; have: Set<string> }) {
  const [q, setQ] = useState("")
  const [cat, setCat] = useState("")
  const [d, setD] = useState<any>(null)
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => api.exerciseLibrary(q, cat).then(setD).catch(() => setD({ exercises: [], categories: {} })), 200)
    return () => clearTimeout(t)
  }, [open, q, cat])
  return (
    <Sheet open={open} onClose={onClose}>
      <h2 className="font-serif text-2xl">Knihovna cviků</h2>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hledat cvik nebo potíž" aria-label="Hledat cvik"
          className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Oblast" className="rounded-xl border border-white/10 bg-panel px-2 py-2 text-[13px]">
          <option value="">všechny oblasti</option>
          {Object.entries(d?.categories || {}).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {!d ? <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám…</p> : (
        <ul className="mt-3 grid gap-2" data-testid="library">
          {d.exercises.slice(0, 60).map((x: any) => (
            <li key={x.id} className="flex items-start gap-2 rounded-xl bg-white/[.03] p-3 text-[13px]">
              <span className="min-w-0 flex-1"><b className="text-fg">{x.name}</b>
                <span className="block text-[12px] text-fg-2">{`${x.dose} · ${x.per_week}× týdně`}</span>
                <span className="block text-[11.5px] text-fg-3">{(x.treats || []).join(", ")}</span></span>
              {have.has(x.id) ? <Chip tone="ok">V programu</Chip>
                : <Button size="sm" variant="outline" icon={Plus} onClick={() => onPick(x)}>Přidat</Button>}
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  )
}

const COUNT_REASON: Record<string, string> = { pain_over_limit: "bolest nad hranicí", too_soon: "příliš brzy po minulém", not_completed: "nedokončeno" }

function RtrTab({ rid, plan, a, onChange }: { rid: string; plan: any; a: any; onChange: () => void }) {
  const toast = useToast()
  const [pain, setPain] = useState(3)
  const [ack, setAck] = useState(false)
  const [per, setPer] = useState(3)
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const create = async () => {
    setBusy(true)
    try { await api.rtrCreate({ runner_id: rid, pain_threshold: pain, sessions_per_level: per, note: note || undefined }); toast({ title: "Plán návratu je u klienta" }); onChange() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  const toggle = async () => {
    try { await api.rtrStatus(plan.id, plan.status === "paused" ? "active" : "paused"); onChange() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  if (!plan || plan.status === "completed") {
    return (
      <Card>
        <h2 className="font-serif text-xl">Návrat k běhu</h2>
        <p className="mt-1 max-w-[640px] text-[12.5px] leading-[18px] text-fg-2">
          {plan ? "Poslední plán je dokončený. " : ""}Plán dělí návrat do úrovní (od 1 min běhu / 2 min chůze po 25 min souvislého běhu).
          Úroveň je splněná až po zvoleném počtu sezení s bolestí nejvýš na vámi nastavené hranici; sezení nad ní plán zastaví a vám přijde zpráva.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="text-[12px] font-bold text-fg-2">Hranice bolesti
            <select value={pain} onChange={(e) => setPain(Number(e.target.value))} className="mt-1 w-full rounded-xl border border-white/10 bg-panel px-2 py-2 text-[13px] font-normal">
              {[2, 3, 4, 5].map((n) => <option key={n} value={n}>{`nejvýš ${n}/10`}</option>)}
            </select></label>
          <label className="text-[12px] font-bold text-fg-2">Sezení na úroveň
            <select value={per} onChange={(e) => setPer(Number(e.target.value))} className="mt-1 w-full rounded-xl border border-white/10 bg-panel px-2 py-2 text-[13px] font-normal">
              {[2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select></label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Poznámka pro klienta (nepovinné)" aria-label="Poznámka"
            className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] sm:col-span-2" />
        </div>
        {/* physio brief 2026-11-09 P0.7: starting with recent pain at the limit, or without current data, needs a tick */}
        {(() => {
          const lp = a?.lastPain
          const hot = lp && lp.score != null && lp.score >= pain && (Date.now() - new Date(lp.at).getTime()) < 7 * 86400000
          const stale = noData(a)
          if (!hot && !stale) return null
          return (
            <label className="mt-3 flex items-start gap-2 rounded-xl bg-watch/10 px-3 py-2 text-[12.5px] leading-[17px] text-watch" data-testid="rtr-warning">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
              <span>{hot ? `Poslední hlášená bolest je ${lp.score}/10, na zvolené hranici nebo nad ní. ` : ""}
                {stale ? "Klient nemá aktuální data. " : ""}Potvrzuji, že jsem stav klienta ověřil(a).</span>
            </label>
          )
        })()}
        <Button className="mt-3" icon={Play} busy={busy} disabled={(() => {
          const lp = a?.lastPain
          const hot = lp && lp.score != null && lp.score >= pain && (Date.now() - new Date(lp.at).getTime()) < 7 * 86400000
          return (hot || noData(a)) && !ack
        })()} onClick={create} data-testid="rtr-create">Začít návrat k běhu</Button>
      </Card>
    )
  }
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-serif text-xl">Návrat k běhu</h2>
          <p className="text-[12px] text-fg-3">{`od ${fmtD(plan.started_on)} · hranice bolesti ${plan.pain_threshold}/10 · ${plan.sessions_per_level} sezení na úroveň`}</p>
        </div>
        <Button size="sm" variant="outline" icon={plan.status === "paused" ? Play : Pause} onClick={toggle}>{plan.status === "paused" ? "Pokračovat" : "Pozastavit"}</Button>
      </div>
      <ol className="mt-3 grid gap-1.5" data-testid="rtr-levels">
        {(plan.levels_json || []).map((l: any) => {
          const cur = l.level === plan.current_level
          const done = l.level < plan.current_level || plan.status === "completed"
          return (
            <li key={l.level} className={`flex items-center gap-2 rounded-xl px-3 py-2 text-[13px] ${cur ? "bg-accent/10 text-fg" : "bg-white/[.03] text-fg-2"}`}>
              <b className="w-6 tabular-nums">{l.level}</b><span className="flex-1">{l.label}</span>
              {done ? <Chip tone="ok">splněno</Chip> : cur ? <Chip tone="info">{`${plan.cleared_at_current}/${plan.sessions_per_level}`}</Chip> : null}
            </li>
          )
        })}
      </ol>
      <h3 className="mt-4 text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">Sezení</h3>
      {(plan.sessions || []).length === 0 ? <Empty>Klient zatím žádné sezení nezaznamenal.</Empty> : (
        <ul className="mt-1 grid gap-1 text-[12.5px]">
          {[...plan.sessions].reverse().slice(0, 12).map((s: any) => (
            <li key={s.id} className="text-fg-2">{fmtDT(s.logged_at)}{` · úroveň ${s.level} · bolest ${s.pain}/10`}{s.rpe != null ? ` · RPE ${s.rpe}` : ""}
              {" "}{s.counted ? <Chip tone="ok">započteno</Chip> : <Chip tone="watch">{`nezapočteno${s.count_reason ? ` · ${COUNT_REASON[s.count_reason] || s.count_reason}` : ""}`}</Chip>}{s.note ? ` — ${s.note}` : ""}</li>
          ))}
        </ul>
      )}
      {plan.status === "paused" && <p className="mt-2 text-[12px] text-watch">{plan.paused_reason === "pain_over_limit" ? "Plán se pozastavil: klient hlásil bolest nad hranicí. Obnovíte ho tlačítkem Pokračovat." : "Plán je pozastavený."}</p>}
    </Card>
  )
}

function VisitsTab({ rid, d, onChange }: { rid: string; d: any; onChange: () => void; pid: string }) {
  const [concl, setConcl] = useState<any>(null)
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
              </li>
            ))}
          </ul>
        )}
      </Card>
      <DocsTab rid={rid} />
      <ConclusionSheet booking={concl} onClose={() => setConcl(null)} onDone={() => { setConcl(null); onChange() }} />
    </div>
  )
}

const STATUS: Record<string, string> = { confirmed: "potvrzeno", requested: "čeká na potvrzení", completed: "proběhla", no_show: "nedostavil(a) se", cancelled: "zrušeno", declined: "odmítnuto" }

function ChatTab({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any[]>(() => api.messages(rid), [rid])
  const [body, setBody] = useState("")
  const [busy, setBusy] = useState(false)
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
  return (
    <Card>
      <h2 className="flex items-center gap-2 font-serif text-xl"><MessageCircle className="size-5 text-fg-2" aria-hidden />Zprávy s klientem</h2>
      <div className="mt-3 grid max-h-[520px] gap-2 overflow-y-auto" data-testid="chat">
        {msgs.length === 0 && <Empty>Zatím žádné zprávy.</Empty>}
        {msgs.map((m: any) => (
          <div key={m.id} className={`max-w-[85%] rounded-xl px-3 py-2 text-[13px] leading-[18px] ${m.sender === "physio" ? "ml-auto bg-accent/12 text-fg" : m.sender === "system" ? "mx-auto bg-white/[.03] text-[12px] text-fg-3" : "bg-white/[.05] text-fg-soft"}`}>
            <p className="whitespace-pre-line">{m.body}</p>
            <p className="mt-0.5 text-[10.5px] text-fg-3">{fmtDT(m.created_at)}</p>
          </div>
        ))}
      </div>
      <form className="mt-3 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} aria-label="Zpráva" rows={2}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send() } }}
          className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" placeholder="Napište klientovi (Shift+Enter = nový řádek)" />
        <Button size="sm" icon={Send} busy={busy} type="submit">Odeslat</Button>
      </form>
    </Card>
  )
}
