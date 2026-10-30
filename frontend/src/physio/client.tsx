// Klienti and the client overview (report v6 Section 6.2.8, Figures A9–A10): everyone in the
// physio's care, and for one client the history, the symptom record and the data trends with an
// AI-enhanced summary (the figures come from the engine first, a language model only turns them
// into text — metrics/ai_brief.py), the programme between visits, the return-to-running plan, the
// visits with their conclusions and the chat.
import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { AlertTriangle, ArrowLeft, Bot, FileText, MessageCircle, Pause, Play, Plus, Printer, Search, Send, Sparkles, Trash2 } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { C } from "@/tokens"
import { Empty, KIND, Loading, QuadChip, RiskChip, Score, shownScore, stripTags, useLoad } from "@/physio/common"
import { ConclusionSheet } from "@/physio/conclusion"

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
                    <RiskChip tier={c.a?.tier} />
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
  const { d, err, reload } = useLoad<any>(() => api.physioClient(rid), [rid])
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
              r.running_since ? `běhá od ${fmtD(r.running_since)}` : null, r.device].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className="flex flex-wrap items-center gap-2"><RiskChip tier={d.a.tier} /><QuadChip q={d.a.quadrant} /></span>
      </div>
      {!d.share && <p className="mt-3 flex items-center gap-2 rounded-xl bg-watch/10 px-3 py-2 text-[12.5px] text-watch-soft">
        <AlertTriangle className="size-4" aria-hidden />Klient vypnul sdílení dat z hodinek — vidíte jen hodnocení, check-iny a zprávy.</p>}
      <Segmented className="mt-4" value={tab} onChange={(k) => setSp({ tab: k }, { replace: true })} ariaLabel="Části přehledu klienta"
        options={[["overview", "Přehled"], ["ai", "AI shrnutí"], ["program", "Program"], ["rtr", "Návrat k běhu"], ["visits", "Návštěvy"], ["chat", "Zprávy"]] as const} />
      <div className="mt-4" data-testid={`client-tab-${tab}`}>
        {tab === "overview" && <Overview d={d} />}
        {tab === "ai" && <AiTab rid={rid} />}
        {tab === "program" && <ProgramTab rid={rid} />}
        {tab === "rtr" && <RtrTab rid={rid} plan={d.rtr} onChange={reload} />}
        {tab === "visits" && <VisitsTab rid={rid} d={d} onChange={reload} pid={pid} />}
        {tab === "chat" && <ChatTab rid={rid} />}
      </div>
    </>
  )
}

function Back() {
  return <Link to="/physio/clients" className="inline-flex items-center gap-1 text-[12.5px] font-bold text-fg-2 hover:text-fg"><ArrowLeft className="size-4" aria-hidden />Klienti</Link>
}

function Overview({ d }: { d: any }) {
  const a = d.a
  const maxKm = Math.max(1, ...d.weeks.map((w: any) => w.km))
  const painDays = d.checkins.filter((c: any) => (c.pain || 0) > 0)
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h2 className="font-serif text-xl">Dnešní stav</h2>
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
          <Score v={shownScore(a.overall)} label="Skóre" /><Score v={a.readiness} label="Připravenost" /><Score v={a.symp} label="Příznaky" />
          <Score v={a.load} label="Zátěž" /><Score v={a.mech} label="Mechanika" />
        </div>
        {a.guidance?.typeLabel && <p className="mt-3 text-[13px] text-fg-2">{"Aplikace dnes doporučuje: "}<b className="text-fg">{a.guidance.typeLabel}</b></p>}
        {(a.guidance?.reasons || []).slice(0, 3).map((x: string, i: number) => <p key={i} className="mt-1 text-[12px] leading-[17px] text-fg-3">{`• ${stripTags(x)}`}</p>)}
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
                {i.severity ? ` · závažnost ${i.severity}` : ""}{" "}{i.confirmed ? <Chip tone="ok">potvrzeno fyzioterapeutem</Chip> : <Chip>hlášení běžce</Chip>}</li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

const INTENTS: [string, string][] = [["summary", "Posledních 28 dní"], ["change", "Co se změnilo"], ["where", "Kde může být problém"], ["program", "Co upravit v programu"], ["missing", "Jaká data chybí"]]

function AiTab({ rid }: { rid: string }) {
  const toast = useToast()
  const [intent, setIntent] = useState("summary")
  const [b, setB] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<{ role: string; content: string }[]>([])
  const [q, setQ] = useState("")
  useEffect(() => {
    setB(null)
    api.aiBrief(rid, intent).then(setB).catch((e: any) => setB({ error: e?.message || "Nepodařilo se" }))
  }, [rid, intent])
  const ask = async () => {
    if (!q.trim()) return
    const h = [...hist, { role: "user", content: q.trim() }]
    setHist(h); setQ(""); setBusy(true)
    try { const r = await api.aiChat(rid, h[h.length - 1].content, hist); setHist([...h, { role: "assistant", content: r.reply }]) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }); setHist(hist) }
    finally { setBusy(false) }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden /><h2 className="font-serif text-xl">AI shrnutí před návštěvou</h2>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {INTENTS.map(([k, l]) => (
            <button key={k} type="button" aria-pressed={intent === k} onClick={() => setIntent(k)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-bold ${intent === k ? "bg-fg text-ink" : "bg-white/[.06] text-fg-2 hover:text-fg"}`}>{l}</button>
          ))}
        </div>
        {!b ? <p className="mt-4 animate-pulse text-sm text-fg-2">Počítám z dat…</p> : b.error ? <p className="mt-4 text-sm text-alert">{b.error}</p> : (
          <div className="mt-4 grid gap-3" data-testid="ai-brief">
            {b.sections.map((s: any, i: number) => (
              <section key={i}>
                <h3 className="text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">{s.h}</h3>
                <ul className="mt-1 grid gap-1.5 text-[13px] leading-[19px] text-fg-soft">{s.items.map((it: string, k: number) => <li key={k} className="whitespace-pre-line">{stripTags(it)}</li>)}</ul>
              </section>
            ))}
            <p className="rounded-lg bg-white/[.04] px-3 py-2 text-[11.5px] text-fg-3">{b.caveat}{b.llm ? " Text upravil jazykový model, čísla jsou z enginu." : ""}</p>
          </div>
        )}
      </Card>
      <Card>
        <h2 className="flex items-center gap-2 font-serif text-xl"><Bot className="size-5 text-fg-2" aria-hidden />Zeptejte se na data klienta</h2>
        <div className="mt-3 grid max-h-[420px] gap-2 overflow-y-auto">
          {hist.length === 0 && <p className="text-[12px] text-fg-3">Např. „Jak se měnila zátěž poslední dva týdny?“ Odpovědi vycházejí z dat a nenahrazují vyšetření.</p>}
          {hist.map((m, i) => (
            <p key={i} className={`whitespace-pre-line rounded-xl px-3 py-2 text-[13px] leading-[18px] ${m.role === "user" ? "ml-8 bg-accent/12 text-fg" : "mr-4 bg-white/[.05] text-fg-soft"}`}>{m.content}</p>
          ))}
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask() }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Otázka" maxLength={1000}
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" placeholder="Otázka k datům klienta" />
          <Button size="sm" icon={Send} busy={busy} type="submit">Zeptat se</Button>
        </form>
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
            <p className="text-[12px] text-fg-3">{p.status === "sent" ? `poslán ${fmtD(p.sent_at)}` : "koncept — klient ho zatím nevidí"}</p>
          </div>
          <Button size="sm" variant="outline" icon={Plus} onClick={() => setLib(true)}>Přidat cvik</Button>
        </div>
        {ex.length === 0 ? <Empty>Program je prázdný.</Empty> : (
          <ul className="mt-3 grid gap-2" data-testid="program-exercises">
            {ex.map((e: any) => <ExerciseRow key={e.id} e={e} onChange={reload} />)}
          </ul>
        )}
        <div className="mt-4 grid gap-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Zpráva pro klienta k programu (nepovinné)" aria-label="Zpráva k programu"
            className="rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" />
          <Button icon={Send} busy={busy === "send"} disabled={!ex.length} onClick={() => act("send", () => api.programSend(p.id, note || undefined), "Program je u klienta")}>
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
      <Library open={lib} onClose={() => setLib(false)} onPick={async (x) => {
        await act(`add${x.id}`, () => api.exerciseAdd(p.id, { name: x.name, dose: x.dose, per_week: x.per_week, cue: x.cue }), `Přidáno: ${x.name}`)
      }} />
    </div>
  )
}

function ExerciseRow({ e, onChange }: { e: any; onChange: () => void }) {
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
          <input value={why} onChange={(x) => setWhy(x.target.value)} aria-label="Důvod změny" placeholder="Důvod změny (klient ho uvidí)" className={`${inp} sm:col-span-2`} />
          <Button size="sm" onClick={save}>Uložit</Button>
        </div>
      )}
    </li>
  )
}

function Library({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (x: any) => Promise<void> }) {
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
              <Button size="sm" variant="outline" icon={Plus} onClick={() => onPick(x)}>Přidat</Button>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  )
}

function RtrTab({ rid, plan, onChange }: { rid: string; plan: any; onChange: () => void }) {
  const toast = useToast()
  const [pain, setPain] = useState(3)
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
        <Button className="mt-3" icon={Play} busy={busy} onClick={create} data-testid="rtr-create">Začít návrat k běhu</Button>
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
            <li key={s.id} className="text-fg-2">{fmtDT(s.logged_at)}{` · úroveň ${s.level} · bolest ${s.pain}/10`}
              {" "}{s.counted ? <Chip tone="ok">započteno</Chip> : <Chip tone="watch">nezapočteno</Chip>}{s.note ? ` — ${s.note}` : ""}</li>
          ))}
        </ul>
      )}
      {plan.status === "paused" && <p className="mt-2 text-[12px] text-watch">Plán je pozastavený.</p>}
    </Card>
  )
}

function VisitsTab({ rid, d, onChange }: { rid: string; d: any; onChange: () => void; pid: string }) {
  const [concl, setConcl] = useState<any>(null)
  const [doc, setDoc] = useState<any>(null)
  const openDoc = async () => setDoc(await api.physioDocumentation(rid))
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-xl">Návštěvy a závěry</h2>
        <Button size="sm" variant="outline" icon={Printer} onClick={openDoc}>Dokumentace</Button>
      </div>
      {d.bookings.length === 0 ? <Empty>S tímto klientem zatím nemáte termín.</Empty> : (
        <ul className="mt-2 divide-y divide-white/[.07] text-[13px]" data-testid="visits">
          {d.bookings.map((b: any) => (
            <li key={b.id} className="flex flex-wrap items-center gap-2 py-2.5">
              <span className="min-w-0 flex-1"><b className="text-fg">{fmtDT(b.at)}</b><span className="block text-[12px] text-fg-3">{KIND[b.kind] || b.kind}{` · ${b.status === "confirmed" ? "potvrzeno" : b.status === "requested" ? "čeká na potvrzení" : b.status}`}</span></span>
              {b.conclusion?.status === "approved" ? <Chip tone="ok">závěr sdílen</Chip> : b.conclusion ? <Chip tone="watch">rozepsaný závěr</Chip> : null}
              {b.status === "confirmed" && <Button size="sm" variant="outline" icon={FileText} onClick={() => setConcl({ id: b.id, slot_at: b.at, kind: b.kind, runner: d.runner })}>Závěr</Button>}
            </li>
          ))}
        </ul>
      )}
      <ConclusionSheet booking={concl} onClose={() => setConcl(null)} onDone={() => { setConcl(null); onChange() }} />
      <Sheet open={!!doc} onClose={() => setDoc(null)}
        footer={<Button className="w-full" icon={Printer} onClick={() => window.print()}>Vytisknout</Button>}>
        {doc && (
          <div className="print-area" data-testid="documentation">
            <h2 className="font-serif text-2xl">Dokumentace klienta</h2>
            <p className="mt-1 text-[12.5px] text-fg-2">{doc.runner.name}{doc.runner.birth_year ? ` · nar. ${doc.runner.birth_year}` : ""}</p>
            <p className="text-[12.5px] text-fg-2">{doc.physio.name}{doc.physio.credential ? `, ${doc.physio.credential}` : ""}{doc.physio.clinic ? ` · ${doc.physio.clinic.name}, ${doc.physio.clinic.city || ""}` : ""}</p>
            {doc.visits.length === 0 ? <Empty>Zatím žádný schválený závěr.</Empty> : doc.visits.map((v: any, i: number) => (
              <section key={i} className="mt-4 border-t border-white/[.08] pt-3 text-[13px]">
                <p className="font-bold text-fg">{fmtDT(v.at)}{v.kind ? ` · ${KIND[v.kind] || v.kind}` : ""}</p>
                {v.finding && <p className="mt-1 text-fg-2"><b className="text-fg">{"Nález: "}</b>{v.finding}</p>}
                <p className="mt-1 whitespace-pre-line text-fg-soft">{v.summary}</p>
                {v.outcome && <p className="mt-1 text-[12px] text-fg-3">{`OSTRC: účast ${v.outcome.participation}, objem ${v.outcome.volume}, výkon ${v.outcome.performance}, bolest ${v.outcome.pain} — závažnost ${v.outcome.severity}/100`}{v.outcome.region ? ` · ${v.outcome.region} ${v.outcome.side || ""}` : ""}</p>}
              </section>
            ))}
            <p className="mt-4 text-[11px] text-fg-3">{`Vytvořeno ${fmtDT(doc.generated_at)} v aplikaci Došlap.`}</p>
          </div>
        )}
      </Sheet>
    </Card>
  )
}

function ChatTab({ rid }: { rid: string }) {
  const toast = useToast()
  const { d, reload } = useLoad<any[]>(() => api.messages(rid), [rid])
  const [body, setBody] = useState("")
  const [busy, setBusy] = useState(false)
  const msgs = useMemo(() => d || [], [d])
  const send = async () => {
    if (!body.trim()) return
    setBusy(true)
    try { await api.send(rid, "physio", body.trim()); setBody(""); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
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
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <input value={body} onChange={(e) => setBody(e.target.value)} aria-label="Zpráva" className="min-w-0 flex-1 rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px]" placeholder="Napište klientovi" />
        <Button size="sm" icon={Send} busy={busy} type="submit">Odeslat</Button>
      </form>
    </Card>
  )
}
