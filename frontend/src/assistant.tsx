// Physio AI Assistant (backend app/assistant/): the chat sheet, "Proč?" entry
// points, the evidence card sheet, AI summaries on the tabs and the knowledge
// admin card. Every answer comes from the runner's engine data plus the reviewed
// literature, and the backend validates it before it arrives here.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useNavigate } from "react-router"
import { BookOpen, ExternalLink, FileUp, Send, Sparkles, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Card, Label, Sheet, useToast } from "@/ui"

type Ref = { cite?: string; apa?: string; doi?: string | null }
type Source = { n: number; kind: string; id: string; title?: string; claim?: string; limits?: string; strength?: string; status?: string; cite?: string; section?: string; refs?: Ref[]; app?: string }
type Msg = { id: number; threadId?: string; role: "user" | "assistant"; text: string; sources?: Source[]; links?: string[]; source?: string; createdAt?: string; feedback?: number | null; pending?: boolean }
type Status = { name: string; access: { enabled: boolean; reason: string | null; needsConsent: boolean }; limit: number; used: number; visibleDays: number; disclaimer: string; llm: boolean; admin: boolean; suggestions?: string[]; history?: Msg[] }
type Ctx = { kind: string; id?: string | number }

const LINK_PATH: Record<string, string> = { Dnes: "/app/today", "Trénink": "/app/training", "Deník": "/app/post", Pohyb: "/app/mechanics", "Zátěž": "/app/load", "Péče": "/app/messages", Data: "/data" }
const STRENGTH_TONE: Record<string, string> = { "silné": "text-ok", "střední": "text-watch", "slabé": "text-fg-2" }
const STEPS = ["Čtu vaše data…", "Hledám v odborných zdrojích…", "Píšu odpověď…", "Kontroluji odpověď…"]

type AssistantApi = { available: boolean; status: Status | null; open: (question?: string, context?: Ctx) => void; coachTexts: any }
export const ASSISTANT_REFRESH_EVENT = "doslap:assistant-refresh"
const AssistantCtx = createContext<AssistantApi>({ available: false, status: null, open: () => {}, coachTexts: null })
export const useAssistant = () => useContext(AssistantCtx)

export function AssistantProvider({ children }: { children: ReactNode }) {
  const { me, touring } = useApp()
  // Tour mode shows the shared demo runner, whose chat would be shared too, so the
  // assistant stays hidden until the tour ends.
  const rid = touring ? undefined : (me?.runner_id as string | undefined)
  const [status, setStatus] = useState<Status | null>(null)
  const [coachTexts, setCoachTexts] = useState<any>(null)
  const [openState, setOpenState] = useState<{ q?: string; ctx?: Ctx; n: number } | null>(null)
  const load = useCallback(() => {
    if (!rid) return Promise.resolve()
    return api.assistant(rid).then(setStatus).catch(() => setStatus(null))
  }, [rid])
  const [rev, setRev] = useState(0)
  useEffect(() => {
    const again = () => setRev((n) => n + 1)
    window.addEventListener(ASSISTANT_REFRESH_EVENT, again)
    return () => window.removeEventListener(ASSISTANT_REFRESH_EVENT, again)
  }, [])
  useEffect(() => { if (rid) load(); else setStatus(null) }, [rid, load, rev])
  useEffect(() => {
    if (!rid) { setCoachTexts(null); return }
    let alive = true
    let timer = 0
    const get = (retry: boolean) => api.coach(rid).then((d: any) => {
      if (!alive) return
      setCoachTexts(d?.consent ? d.texts || null : null)
      // stale texts are regenerated in the background, look once more a bit later
      if (retry && d?.pending?.length) timer = window.setTimeout(() => get(false), 8000)
    }).catch(() => alive && setCoachTexts(null))
    get(true)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [rid, rev])
  const available = !!status && (status.access.enabled || status.access.reason === "consent")
  const open = useCallback((q?: string, ctx?: Ctx) => setOpenState((s) => ({ q, ctx, n: (s?.n || 0) + 1 })), [])
  const value = useMemo(() => ({ available, status, open, coachTexts }), [available, status, open, coachTexts])
  return (
    <AssistantCtx.Provider value={value}>
      {children}
      {openState && status && rid && (
        <AssistantSheet key={openState.n} rid={rid} status={status} initialQ={openState.q} initialCtx={openState.ctx}
          onClose={() => { setOpenState(null); load() }} />
      )}
    </AssistantCtx.Provider>
  )
}

export function AssistantHeaderButton() {
  const { available, open } = useAssistant()
  if (!available) return null
  return (
    <button onClick={() => open()} data-testid="assistant-open" aria-label="Otevřít Physio AI Assistant"
      className="grid size-9 place-items-center rounded-full border border-white/12 bg-white/[.04] text-accent hover:border-accent/50 hover:bg-accent/10">
      <Sparkles className="size-[18px]" aria-hidden />
    </button>
  )
}

// A small "Proč?" button next to anything the assistant can explain.
export function WhyButton({ question, context, label = "Proč?", className = "" }: { question: string; context?: Ctx; label?: string; className?: string }) {
  const { available, open } = useAssistant()
  if (!available) return null
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); open(question, context) }} data-testid="why-button"
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border border-accent/35 bg-accent/[.08] px-2.5 py-1 text-[11px] font-bold text-accent hover:bg-accent/15 ${className}`}>
      <Sparkles className="size-3" aria-hidden />{label}
    </button>
  )
}

function AnswerText({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const paras = text.split(/\n+/).filter((p) => p.trim())
  return (
    <div className="space-y-2">
      {paras.map((p, i) => {
        const m = p.match(/^(Ve vašich datech:|Co říká výzkum:|Co s tím:)\s*/)
        const body = m ? p.slice(m[0].length) : p
        const parts = body.split(/(\[\d{1,2}\])/g)
        return (
          <p key={i} className="text-[14px] leading-6 text-fg">
            {m && <b className="text-fg">{m[1]} </b>}
            {parts.map((x, j) => {
              const c = x.match(/^\[(\d{1,2})\]$/)
              return c ? (
                <button key={j} onClick={() => onCite(Number(c[1]))} aria-label={`Zdroj ${c[1]}`}
                  className="mx-0.5 inline-grid h-[18px] min-w-[18px] -translate-y-px place-items-center rounded-md bg-accent/15 px-1 align-middle text-[10px] font-extrabold text-accent hover:bg-accent/25">{c[1]}</button>
              ) : <span key={j}>{x}</span>
            })}
          </p>
        )
      })}
    </div>
  )
}

function SourceSheet({ src, onClose }: { src: Source; onClose: () => void }) {
  return (
    <Sheet open onClose={onClose} layer="z-[96]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="t-label">{src.kind === "card" ? "Důkazní karta" : src.kind === "summary" ? "Shrnutí studie" : "Pasáž článku"} · zdroj {src.n}</p>
          <h3 className="mt-1 font-serif text-[22px] leading-tight">{src.title || src.cite}</h3>
        </div>
        <button onClick={onClose} aria-label="Zavřít" className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 text-fg-2 hover:text-fg"><X className="size-4" aria-hidden /></button>
      </div>
      {src.claim && <p className="mt-3 text-[14px] leading-6 text-fg">{src.claim}</p>}
      {src.limits && <p className="mt-3 rounded-[12px] border border-white/10 bg-white/[.03] p-3 text-[12px] leading-5 text-fg-2"><b className="text-fg-soft">Omezení: </b>{src.limits}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
        {src.strength && <span className={`rounded-full border border-white/12 px-2.5 py-1 font-bold ${STRENGTH_TONE[src.strength] || "text-fg-2"}`}>Síla důkazů: {src.strength}</span>}
        {src.status && src.status !== "approved" && <span className="rounded-full border border-watch/40 px-2.5 py-1 font-bold text-watch">Koncept, čeká na odborné schválení</span>}
        {src.section && <span className="rounded-full border border-white/12 px-2.5 py-1 text-fg-2">část: {src.section}</span>}
      </div>
      <div className="mt-4 space-y-2 border-t border-white/[.08] pt-3">
        <p className="t-label !text-fg-3">Literatura</p>
        {(src.refs || []).map((r, i) => (
          <p key={i} className="text-[12px] leading-5 text-fg-2">
            {(r.apa || r.cite || "").replace(/\s*https?:\/\/doi\.org\/\S+\s*$/, "")}
            {r.doi && <a href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center gap-0.5 break-all font-bold text-accent hover:underline">https://doi.org/{r.doi}<ExternalLink className="size-3 shrink-0" aria-hidden /></a>}
          </p>
        ))}
      </div>
    </Sheet>
  )
}

function AssistantSheet({ rid, status, initialQ, initialCtx, onClose }: { rid: string; status: Status; initialQ?: string; initialCtx?: Ctx; onClose: () => void }) {
  const nav = useNavigate()
  const toast = useToast()
  const [msgs, setMsgs] = useState<Msg[]>(status.history || [])
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(0)
  const [thread, setThread] = useState<string | undefined>(() => {
    const last = (status.history || []).slice(-1)[0]
    return last?.threadId
  })
  const [src, setSrc] = useState<Source | null>(null)
  const [used, setUsed] = useState(status.used)
  const endRef = useRef<HTMLDivElement>(null)
  const sentInitial = useRef(false)
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }) }, [msgs.length, busy])
  useEffect(() => {
    if (!busy) return
    setStep(0)
    const t = [1500, 4500, 14000].map((ms, i) => window.setTimeout(() => setStep(i + 1), ms))
    return () => t.forEach(window.clearTimeout)
  }, [busy])
  const ask = async (q: string, ctx?: Ctx) => {
    const question = q.trim()
    if (!question || busy) return
    setInput("")
    setMsgs((m) => [...m, { id: -Date.now(), role: "user", text: question }])
    setBusy(true)
    try {
      const out: any = await api.assistantAsk(rid, { question, context: ctx || null, thread_id: thread })
      setThread(out.threadId)
      setUsed((u) => u + 1)
      setMsgs((m) => [...m, out])
    } catch (e: any) {
      setMsgs((m) => [...m, { id: -Date.now() - 1, role: "assistant", text: e?.message || "Odpověď se nepodařilo načíst, zkuste to prosím znovu.", source: "error" }])
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => {
    if (initialQ && !sentInitial.current && status.access.enabled) {
      sentInitial.current = true
      ask(initialQ, initialCtx)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const feedback = async (m: Msg, value: number) => {
    try {
      await api.assistantFeedback(rid, m.id, value)
      setMsgs((all) => all.map((x) => (x.id === m.id ? { ...x, feedback: value } : x)))
      toast({ title: value > 0 ? "Díky za zpětnou vazbu" : "Díky, odpověď projdeme" })
    } catch { /* feedback is best effort */ }
  }
  const forget = async () => {
    if (!confirm("Smazat celou historii konverzací s asistentem?")) return
    await api.assistantForget(rid)
    setMsgs([])
    setThread(undefined)
    toast({ title: "Historie smazána" })
  }
  const sourceOf = (m: Msg, n: number) => (m.sources || []).find((s) => s.n === n)
  const noAccess = !status.access.enabled
  return (
    <Sheet open onClose={onClose} layer="z-[95]"
      footer={noAccess ? undefined : (
        <form onSubmit={(e) => { e.preventDefault(); ask(input) }} className="flex items-end gap-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} maxLength={800} aria-label="Otázka pro asistenta"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input) } }}
            placeholder="Zeptejte se na trénink, data, aplikaci…"
            className="max-h-32 min-h-11 flex-1 resize-none rounded-[14px] border border-white/12 bg-white/[.04] px-3 py-2.5 text-[14px] text-fg" />
          <button type="submit" disabled={busy || !input.trim() || used >= status.limit} aria-label="Odeslat"
            className="btn btn-primary grid size-11 place-items-center !p-0"><Send className="size-4" aria-hidden /></button>
        </form>
      )}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="t-label flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" aria-hidden />AI asistent · beta</p>
          <h2 className="mt-1 font-serif text-[24px] leading-tight">{status.name}</h2>
        </div>
        <div className="flex shrink-0 gap-2">
          {msgs.length > 0 && <button onClick={forget} aria-label="Smazat historii" className="grid size-9 place-items-center rounded-full border border-white/15 text-fg-2 hover:text-fg"><Trash2 className="size-4" aria-hidden /></button>}
          <button onClick={onClose} aria-label="Zavřít asistenta" className="grid size-9 place-items-center rounded-full border border-white/15 text-fg-2 hover:text-fg"><X className="size-4" aria-hidden /></button>
        </div>
      </div>
      <p className="mt-2 text-[11px] leading-5 text-fg-3">{status.disclaimer} Konverzace vidíte {status.visibleDays} dní.</p>
      {noAccess ? (
        <div className="nest mt-4 p-4">
          <p className="text-[14px] leading-6 text-fg">Asistent pracuje s vašimi daty, proto potřebuje souhlas se zpracováním AI.</p>
          <button onClick={() => { onClose(); nav("/data") }} className="btn btn-primary mt-3 text-sm">Zapnout v Data a připojení</button>
        </div>
      ) : (
        <div className="mt-4 space-y-4 pb-2" data-testid="assistant-thread">
          {msgs.length === 0 && !busy && (
            <div className="nest p-4">
              <p className="text-[13px] leading-5 text-fg-2">Ptejte se na své data, dnešní trénink, plánování, zátěž, bolest nebo na to, kde co v aplikaci najdete.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(status.suggestions || []).map((s) => (
                  <button key={s} onClick={() => ask(s)} className="rounded-full border border-white/15 px-3 py-1.5 text-left text-[12px] font-semibold text-fg-soft hover:border-accent/50">{s}</button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end"><p className="max-w-[85%] rounded-[16px] rounded-br-md bg-accent/15 px-3.5 py-2.5 text-[14px] leading-6 text-fg">{m.text}</p></div>
          ) : (
            <div key={m.id} className="max-w-[95%]">
              <div className="rounded-[16px] rounded-bl-md border border-white/10 bg-white/[.03] px-3.5 py-3">
                <AnswerText text={m.text} onCite={(n) => { const s = sourceOf(m, n); if (s) setSrc(s) }} />
                {(m.links?.length || 0) > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {m.links!.map((l) => LINK_PATH[l] && (
                      <button key={l} onClick={() => { onClose(); nav(LINK_PATH[l]) }} className="rounded-full bg-white/[.07] px-2.5 py-1 text-[11px] font-bold text-fg-soft hover:bg-white/[.12]">Otevřít {l}</button>
                    ))}
                  </div>
                )}
                {(m.sources?.length || 0) > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5 border-t border-white/[.07] pt-2">
                    {m.sources!.map((s) => (
                      <button key={s.n} onClick={() => setSrc(s)} className="inline-flex max-w-full items-center gap-1 rounded-full border border-white/12 px-2 py-0.5 text-[11px] text-fg-2 hover:border-accent/40">
                        <BookOpen className="size-3 shrink-0" aria-hidden /><span className="truncate">[{s.n}] {s.kind === "card" ? s.title : s.cite}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {m.id > 0 && m.source !== "gate" && (
                <div className="mt-1 flex items-center gap-1 pl-1 text-fg-3">
                  <span className="mr-1 text-[10px]">{m.source === "llm" ? "AI" : m.source === "fallback" ? "stručná odpověď aplikace" : ""}</span>
                  <button onClick={() => feedback(m, 1)} aria-label="Užitečná odpověď" aria-pressed={m.feedback === 1} className={`grid size-7 place-items-center rounded-full hover:text-fg ${m.feedback === 1 ? "text-ok" : ""}`}><ThumbsUp className="size-3.5" aria-hidden /></button>
                  <button onClick={() => feedback(m, -1)} aria-label="Neužitečná nebo chybná odpověď" aria-pressed={m.feedback === -1} className={`grid size-7 place-items-center rounded-full hover:text-fg ${m.feedback === -1 ? "text-alert" : ""}`}><ThumbsDown className="size-3.5" aria-hidden /></button>
                </div>
              )}
            </div>
          ))}
          {busy && <p className="animate-pulse text-[12px] text-fg-2" role="status">{STEPS[step]}</p>}
          {used >= status.limit && <p className="text-[11px] text-watch">Dnešní limit {status.limit} otázek je vyčerpaný.</p>}
          <div ref={endRef} />
        </div>
      )}
      {src && <SourceSheet src={src} onClose={() => setSrc(null)} />}
    </Sheet>
  )
}

// The Phase 1 AI texts, placed on the tabs (daily summary on Dnes, the training
// commentary on Trénink, the weekly summary in Deník, the last run in run detail).
export function CoachTextCard({ kind, title, question, className = "" }: { kind: string; title: string; question: string; className?: string }) {
  const { coachTexts } = useAssistant()
  const t = coachTexts?.[kind]
  if (!t?.text) return null
  return (
    <Card className={className}>
      <div className="flex items-center justify-between gap-3">
        <Label><span className="inline-flex items-center gap-1.5"><Sparkles className="size-3.5 text-accent" aria-hidden />{title}</span></Label>
        <WhyButton question={question} context={{ kind: "summary", id: kind }} label="Zeptat se" />
      </div>
      <p className="mt-2 whitespace-pre-line text-[14px] leading-6 text-fg">{t.text}</p>
      <p className="mt-2 text-[11px] text-fg-3">{t.source === "llm" ? "Napsala AI z vašich dat, text prošel kontrolou." : "Sestaveno aplikací z vašich dat."}</p>
    </Card>
  )
}

// Knowledge base admin (accounts in DOSSLAP_ADMIN_EMAILS): upload full texts, review cards.
export function KnowledgeAdminCard() {
  const { status } = useAssistant()
  const toast = useToast()
  const [kb, setKb] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.knowledgeAdmin().then(setKb).catch(() => setKb(null))
  useEffect(() => { if (status?.admin) load() }, [status?.admin])
  if (!status?.admin || !kb) return null
  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    let ok = 0
    for (const f of Array.from(files)) {
      const fd = new FormData()
      fd.append("file", f)
      try { await api.knowledgeUpload(fd); ok++ } catch (e: any) { toast({ title: `${f.name}: ${e?.message || "nahrání selhalo"}` }) }
    }
    setBusy(false)
    toast({ title: `Nahráno ${ok} z ${files.length}` })
    load()
  }
  const review = async (id: string, st: string) => { await api.knowledgeCard(id, st); load() }
  return (
    <Card className="mt-4">
      <Label>Znalostní báze asistenta · správa</Label>
      <p className="mt-2 text-[12px] text-fg-2">
        Pasáže: {Object.entries(kb.chunks || {}).map(([k, v]) => `${k} ${v}`).join(", ")} · embedding {kb.embedModel ? `${kb.embedded} (${kb.embedModel})` : "vypnutý, hledá se podle slov"}
      </p>
      <label className={`btn btn-outline mt-3 inline-flex cursor-pointer items-center gap-2 text-sm ${busy ? "opacity-60" : ""}`}>
        <FileUp className="size-4" aria-hidden />{busy ? "Nahrávám…" : "Nahrát PDF článků"}
        <input type="file" accept="application/pdf" multiple className="hidden" disabled={busy} onChange={(e) => upload(e.target.files)} />
      </label>
      {kb.docs?.length > 0 && (
        <ul className="mt-3 space-y-1 text-[12px] text-fg-2">
          {kb.docs.map((d: any) => (
            <li key={d.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{d.cite} · {d.chunks} pasáží{d.summary ? "" : " · bez shrnutí"}</span>
              <button onClick={async () => { await api.knowledgeDelete(d.id); load() }} className="text-fg-3 hover:text-alert" aria-label={`Smazat ${d.cite}`}><Trash2 className="size-3.5" aria-hidden /></button>
            </li>
          ))}
        </ul>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer text-[12px] font-bold text-fg-soft">Důkazní karty ({kb.cards.filter((c: any) => c.status === "approved").length} z {kb.cards.length} schváleno)</summary>
        <ul className="mt-2 space-y-1.5">
          {kb.cards.map((c: any) => (
            <li key={c.id} className="flex items-center justify-between gap-2 text-[12px]">
              <span className="truncate text-fg-2">{c.cat} · {c.title}</span>
              <select value={c.status} onChange={(e) => review(c.id, e.target.value)} aria-label={`Stav karty ${c.title}`} className="rounded-md border border-white/12 bg-raised px-1.5 py-0.5 text-[11px] text-fg">
                <option value="draft">koncept</option><option value="approved">schváleno</option><option value="rejected">zamítnuto</option>
              </select>
            </li>
          ))}
        </ul>
      </details>
    </Card>
  )
}

