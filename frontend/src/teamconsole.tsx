// Team Console (owner request 2026-10-27): Admin → Tým, Inbox, Práce, Schválení, Vydání, Pilot.
// The founders run the AI engineering team (gstack sprints on GitHub) from the app; the backend
// (routers/team.py) checks every permission, the tabs only follow the role it reports. The app
// never merges or deploys: it writes issues, labels and comments, and reads what runs.
import { useCallback, useEffect, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router"
import { CheckCircle2, ExternalLink, GitPullRequest, RefreshCw, Send, ShieldCheck, TriangleAlert } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { C } from "@/tokens"

type TeamMe = { role: string; perms: string[]; email: string; config: { github: boolean; githubRepo: string; webhook: boolean; railway: boolean; staging: string | null } }

const ROLE: Record<string, string> = { owner: "vlastník", engineer: "inženýr", clinical: "klinický garant", support: "podpora", auditor: "auditor" }
const STAGE: Record<string, [string, "ok" | "watch" | "alert" | "muted" | "info" | "load" | "accent"]> = {
  planned: ["Naplánováno", "muted"], queued: ["Ve frontě AI", "info"], in_progress: ["Rozpracováno", "load"],
  needs_clinical: ["Čeká na klinika", "watch"], needs_owner: ["Plán čeká na vlastníka", "watch"], in_review: ["Ke kontrole", "info"], merged: ["Sloučeno", "ok"],
  deployed: ["V produkci", "accent"], closed: ["Zavřeno", "muted"],
}
const STAGE_ORDER = ["needs_owner", "needs_clinical", "in_review", "in_progress", "queued", "planned", "merged", "deployed", "closed"]
const CHECKS: Record<string, [string, "ok" | "watch" | "alert"]> = { success: ["CI zelené", "ok"], pending: ["CI běží", "watch"], failure: ["CI červené", "alert"] }
const TYPE: Record<string, string> = { bug: "chyba", feature: "funkce", engine: "engine", safety: "bezpečnost", copy: "text" }

function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [d, setD] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const reload = useCallback(() => {
    setErr(null)
    fn().then(setD).catch((e: any) => setErr(e?.message || "Nepodařilo se načíst"))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  return { d, err, reload, setD }
}

function Loading({ err }: { err: string | null }) {
  return err ? <p className="mt-4 text-sm text-alert">{err}</p> : <p className="mt-4 animate-pulse text-sm text-fg-2">Načítám…</p>
}

function Missing({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-2 rounded-xl bg-watch/10 px-3 py-2 text-[12px] leading-[17px] text-watch-soft">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /><span>{children}</span>
    </p>
  )
}

function Ext({ href, children }: { href?: string | null; children: ReactNode }) {
  if (!href) return <>{children}</>
  return <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{children}<ExternalLink className="size-3" aria-hidden /></a>
}

export function TeamConsole({ owner, runners }: { owner: boolean; runners: ReactNode }) {
  const [sp, setSp] = useSearchParams()
  const { d: me, err } = useLoad<TeamMe>(() => api.teamMe())
  const has = (p: string) => !!me?.perms.includes(p)
  const tabs = ([
    ["runners", "Běžci", owner],
    ["team", "Tým", has("team.manage") || has("audit.read")],
    ["inbox", "Inbox", has("inbox.read")],
    ["work", "Práce", has("work.read")],
    ["approvals", "Schválení", has("approvals.read")],
    ["releases", "Vydání", has("releases.read")],
    ["pilot", "Pilot", has("pilot.read")],
  ] as const).filter((t) => t[2]).map(([k, l]) => [k, l] as const)
  const want = sp.get("tab") || (owner ? "runners" : me?.role === "clinical" ? "approvals" : "inbox")
  const tab = tabs.some(([k]) => k === want) ? want : tabs[0]?.[0]
  if (!me && !owner) return <Loading err={err} />
  return (
    <>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Segmented options={tabs} value={tab as any} onChange={(k) => setSp({ tab: k }, { replace: true })} ariaLabel="Části správy" />
        {me && <Chip tone="info">{ROLE[me.role] || me.role}</Chip>}
      </div>
      <div className="mt-4" data-testid={`team-tab-${tab}`}>
        {tab === "runners" && runners}
        {me && tab === "team" && <TeamTab me={me} />}
        {me && tab === "inbox" && <InboxTab me={me} />}
        {me && tab === "work" && <WorkTab me={me} />}
        {me && tab === "approvals" && <ApprovalsTab />}
        {me && tab === "releases" && <ReleasesTab />}
        {me && tab === "pilot" && <PilotTab />}
      </div>
    </>
  )
}

/* ---------------------------------------------------------------- Tým */
function TeamTab({ me }: { me: TeamMe }) {
  const toast = useToast()
  const manage = me.perms.includes("team.manage")
  const { d, err, reload } = useLoad<any>(() => api.teamMembers())
  const audit = useLoad<any>(() => (me.perms.includes("audit.read") ? api.teamAudit() : Promise.resolve({ items: [] })))
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("engineer")
  const [busy, setBusy] = useState(false)
  const add = async () => {
    setBusy(true)
    try { await api.teamAddMember({ email, name: name || undefined, role }); setEmail(""); setName(""); reload(); audit.reload(); toast({ title: "Člen týmu přidán" }) }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  const patch = async (id: number, body: any) => {
    try { await api.teamPatchMember(id, body); reload(); audit.reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <Card>
        <h2 className="font-serif text-xl">Tým a role</h2>
        <p className="mt-1 text-[12px] leading-[17px] text-fg-2">
          Přístup se řídí e-mailem přihlášeného účtu. Klinický garant schvaluje změny enginu a bezpečnosti, podpora třídí Inbox,
          auditor jen čte. Vlastníky z proměnné DOSSLAP_OWNER_EMAILS tady změnit nelze.
        </p>
        {!d ? <Loading err={err} /> : (
          <ul className="mt-3 divide-y divide-white/[.07]" data-testid="team-members">
            {d.env.map((m: any) => (
              <li key={m.email} className="flex flex-wrap items-center gap-2 py-2.5 text-[13px]">
                <span className="min-w-0 flex-1 truncate text-fg">{m.email}</span>
                <Chip tone="info">{ROLE.owner}</Chip><Chip>Railway</Chip>
                {!m.hasAccount && <Chip tone="watch">bez účtu</Chip>}
              </li>
            ))}
            {d.items.map((m: any) => (
              <li key={m.id} className={`flex flex-wrap items-center gap-2 py-2.5 text-[13px] ${m.active ? "" : "opacity-50"}`}>
                <span className="min-w-0 flex-1">
                  <b className="block truncate text-fg">{m.name || m.email}</b>
                  {m.name && <span className="block truncate text-[11.5px] text-fg-3">{m.email}</span>}
                </span>
                {!m.hasAccount && <Chip tone="watch">bez účtu</Chip>}
                {manage ? (
                  <>
                    <select value={m.role} onChange={(e) => patch(m.id, { role: e.target.value })} aria-label="Role"
                      className="rounded-lg border border-white/10 bg-panel px-2 py-1 text-[12px]">
                      {d.roles.map((r: string) => <option key={r} value={r}>{ROLE[r] || r}</option>)}
                    </select>
                    <button type="button" onClick={() => patch(m.id, { active: !m.active })} className="text-[12px] font-bold text-fg-3 hover:text-fg">
                      {m.active ? "Odebrat" : "Vrátit"}
                    </button>
                  </>
                ) : <Chip>{ROLE[m.role] || m.role}</Chip>}
              </li>
            ))}
          </ul>
        )}
        {manage && (
          <div className="mt-4 grid gap-2 rounded-xl bg-white/[.04] p-3" data-testid="team-add">
            <p className="text-[12px] font-bold text-fg-2">Přidat člena</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="e-mail" aria-label="E-mail"
                className="rounded-lg border border-white/10 bg-panel px-3 py-2 text-[13px]" />
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="jméno (nepovinné)" aria-label="Jméno"
                className="rounded-lg border border-white/10 bg-panel px-3 py-2 text-[13px]" />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role"
                className="rounded-lg border border-white/10 bg-panel px-2 py-2 text-[13px]">
                {Object.keys(ROLE).map((r) => <option key={r} value={r}>{ROLE[r]}</option>)}
              </select>
              <Button busy={busy} disabled={!email.includes("@")} onClick={add}>Přidat</Button>
            </div>
            <p className="text-[11.5px] text-fg-3">Člověk se přihlásí vlastním účtem Došlapu s tímto e-mailem (nebo si ho založí).</p>
          </div>
        )}
      </Card>
      {me.perms.includes("audit.read") && (
        <Card>
          <h2 className="font-serif text-xl">Záznam změn</h2>
          <p className="mt-1 text-[12px] text-fg-2">Kdo co v Team Console udělal. Záznam nejde upravit.</p>
          {!audit.d ? <Loading err={audit.err} /> : audit.d.items.length === 0 ? <p className="mt-3 text-[12px] text-fg-3">Zatím nic.</p> : (
            <ul className="mt-3 max-h-[520px] space-y-2 overflow-y-auto text-[12px]" data-testid="team-audit">
              {audit.d.items.map((a: any) => (
                <li key={a.id} className="rounded-lg bg-white/[.03] px-2.5 py-1.5">
                  <span className="text-fg-3">{fmtDT(a.at)}</span>{" · "}<b className="text-fg">{a.actor}</b>{" · "}
                  <code translate="no" className="text-fg-2">{a.action}</code>
                  {a.target && <>{" · "}<span translate="no" className="text-fg-2">{a.target}</span></>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- Inbox */
function InboxTab({ me }: { me: TeamMe }) {
  const toast = useToast()
  const [status, setStatus] = useState<"open" | "done" | "wontfix">("open")
  const { d, err, reload } = useLoad<any>(() => api.teamInbox(status), [status])
  const [send, setSend] = useState<any>(null)
  const triage = me.perms.includes("inbox.triage")
  const owner = me.role === "owner"
  const patch = async (id: number, body: any) => {
    try { await api.teamTriage(id, body); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
  }
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl">Inbox zpětné vazby</h2>
          <p className="mt-1 max-w-[640px] text-[12px] leading-[17px] text-fg-2">
            Poznámky z aplikace. Roztřiďte je a pošlete AI týmu: vznikne issue na GitHubu se štítkem ai-ready a AI tým začne pracovat.
            Poznámka od uživatele jde k implementaci až po schválení vlastníkem.
          </p>
        </div>
        <Segmented size="sm" value={status} onChange={setStatus} ariaLabel="Stav poznámek"
          options={[["open", "Otevřené"], ["done", "Vyřešené"], ["wontfix", "Nebude"]] as const} />
      </div>
      {d && !d.github && <Missing>GitHub není připojený — posílání AI týmu potřebuje proměnnou DOSSLAP_GITHUB_TOKEN v Railway.</Missing>}
      {!d ? <Loading err={err} /> : d.items.length === 0 ? <p className="mt-4 text-[13px] text-fg-3">Žádné poznámky.</p> : (
        <ul className="mt-3 divide-y divide-white/[.07]" data-testid="team-inbox">
          {d.items.map((n: any) => (
            <li key={n.id} className="py-3">
              <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-fg-3">
                <span translate="no">{`#${n.id}`}</span>
                <span translate="no">{n.route}</span>
                {n.heading && <span>{`· ${n.heading}`}</span>}
                <span>{`· ${fmtD(n.createdAt)}`}</span>
                <span>· {n.author.isOwner ? "vlastník" : n.author.role === "physio" ? "fyzioterapeut" : "běžec"}{n.author.name ? ` (${n.author.name})` : ""}</span>
                {n.ready ? <Chip tone="ok">schváleno</Chip> : <Chip tone="watch">čeká na schválení</Chip>}
                {n.issueNumber && <Chip tone="info"><Ext href={n.issueUrl}>{`issue #${n.issueNumber}`}</Ext></Chip>}
              </div>
              <p className="mt-1.5 whitespace-pre-line text-[13.5px] leading-[19px] text-fg">{n.note}</p>
              {n.resolution && <p className="mt-1 text-[12px] text-ok">{n.resolution}</p>}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
                {triage ? (
                  <>
                    <select value={n.priority || ""} onChange={(e) => patch(n.id, { priority: e.target.value })} aria-label="Priorita"
                      className="rounded-lg border border-white/10 bg-panel px-2 py-1">
                      <option value="">priorita</option>{d.priorities.map((p: string) => <option key={p} value={p}>{p}</option>)}
                    </select>
                    <select value={n.type || ""} onChange={(e) => patch(n.id, { type: e.target.value })} aria-label="Typ"
                      className="rounded-lg border border-white/10 bg-panel px-2 py-1">
                      <option value="">typ</option>{d.types.map((t: string) => <option key={t} value={t}>{TYPE[t] || t}</option>)}
                    </select>
                    <select value={n.assignee || ""} onChange={(e) => patch(n.id, { assignee: e.target.value })} aria-label="Řeší"
                      className="max-w-[200px] rounded-lg border border-white/10 bg-panel px-2 py-1">
                      <option value="">řeší</option>{d.assignees.map((a: string) => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </>
                ) : (
                  <>{n.priority && <Chip>{n.priority}</Chip>}{n.type && <Chip>{TYPE[n.type] || n.type}</Chip>}</>
                )}
                {owner && !n.author.isOwner && (
                  <button type="button" className="font-bold text-accent hover:underline" onClick={() => patch(n.id, { approved: !n.approvedAt })}>
                    {n.approvedAt ? "Zrušit schválení" : "Schválit k implementaci"}
                  </button>
                )}
                {me.perms.includes("inbox.send") && !n.issueNumber && n.status === "open" && (n.ready || owner) && (
                  <button type="button" data-testid="inbox-send" onClick={() => setSend(n)}
                    className="btn btn-primary btn-sm gap-1.5"><Send className="size-3.5" aria-hidden />Poslat AI týmu</button>
                )}
                {triage && n.status === "open" && (
                  <>
                    <button type="button" className="text-fg-3 hover:text-fg" onClick={() => patch(n.id, { status: "done" })}>Vyřešeno</button>
                    <button type="button" className="text-fg-3 hover:text-fg" onClick={() => patch(n.id, { status: "wontfix" })}>Nebude</button>
                  </>
                )}
                {triage && n.status !== "open" && (
                  <button type="button" className="text-fg-3 hover:text-fg" onClick={() => patch(n.id, { status: "open" })}>Znovu otevřít</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <SendSheet note={send} onClose={() => setSend(null)} onSent={() => { setSend(null); reload() }} />
    </Card>
  )
}

function SendSheet({ note, onClose, onSent }: { note: any; onClose: () => void; onSent: () => void }) {
  const toast = useToast()
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (note) { setTitle(note.note.split("\n")[0].slice(0, 90)); setText(note.note) } }, [note])
  const go = async () => {
    setBusy(true)
    try { const r = await api.teamSend(note.id, { title, text }); toast({ title: `Issue #${r.issueNumber} je u AI týmu` }); onSent() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  return (
    <Sheet open={!!note} onClose={onClose}
      footer={<Button className="w-full" icon={Send} busy={busy} disabled={title.trim().length < 3 || !text.trim()} onClick={go} data-testid="inbox-send-confirm">Vytvořit issue</Button>}>
      <h2 className="font-serif text-2xl">Poslat AI týmu</h2>
      <p className="mt-2 flex items-start gap-2 rounded-xl bg-alert/10 px-3 py-2 text-[12px] leading-[17px] text-alert-soft">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>Issue opouští aplikaci. Odstraňte jména, e-maily a cokoli o zdraví konkrétního běžce — popište chybu nebo přání obecně.</span>
      </p>
      <label className="mt-4 block text-[12px] font-bold text-fg-2">Název
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={140}
          className="mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[14px] font-normal text-fg" />
      </label>
      <label className="mt-3 block text-[12px] font-bold text-fg-2">Text pro AI tým
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} maxLength={4000}
          className="mt-1 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] font-normal leading-[19px] text-fg" />
      </label>
      <p className="mt-2 text-[11.5px] leading-[16px] text-fg-3">
        Přidá se obrazovka, typ, priorita, build a štítky ai-ready a from-app (a engine nebo safety, které vyžadují klinické schválení).
      </p>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- Práce */
function WorkTab({ me }: { me: TeamMe }) {
  const toast = useToast()
  const { d, err, reload } = useLoad<any>(() => api.teamWork())
  const [busy, setBusy] = useState(false)
  const sync = async () => {
    setBusy(true)
    try { const r = await api.teamSync(); toast({ title: `Synchronizováno: ${r.issues} issues, ${r.prs} PR` }); reload() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  // an issue with its pull request shows once, as the pull request
  const items: any[] = (d?.items || []).filter((w: any) => !(w.kind === "issue" && w.pr))
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl">Práce AI týmu</h2>
          <p className="mt-1 text-[12px] text-fg-2">
            Issues a pull requesty z GitHubu.{d?.lastSync ? ` Poslední synchronizace: ${fmtDT(d.lastSync)}` : ""}
          </p>
        </div>
        {me.perms.includes("work.sync") && <Button size="sm" icon={RefreshCw} busy={busy} onClick={sync} data-testid="work-sync">Synchronizovat</Button>}
      </div>
      {d && !d.config.webhook && <Missing>Webhook z GitHubu není nastavený (DOSSLAP_GITHUB_WEBHOOK_SECRET) — práce se obnoví jen tlačítkem Synchronizovat.</Missing>}
      {!d ? <Loading err={err} /> : items.length === 0 ? <p className="mt-4 text-[13px] text-fg-3">Zatím žádná práce.</p> : (
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="team-work">
          {STAGE_ORDER.filter((s) => items.some((w) => w.stage === s)).map((s) => (
            <section key={s}>
              <h3 className="mb-2 flex items-center gap-2 text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">
                <Chip tone={STAGE[s][1]}>{STAGE[s][0]}</Chip><span className="tabular-nums">{items.filter((w) => w.stage === s).length}</span>
              </h3>
              <ul className="space-y-2">
                {items.filter((w) => w.stage === s).slice(0, 12).map((w) => <WorkCard key={`${w.kind}${w.number}`} w={w} />)}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Card>
  )
}

function WorkCard({ w }: { w: any }) {
  return (
    <li className="rounded-xl bg-white/[.04] px-3 py-2.5 text-[12.5px]">
      <p className="flex items-center gap-1.5 text-[11px] text-fg-3">
        {w.kind === "pr" ? <GitPullRequest className="size-3.5" aria-hidden /> : <CheckCircle2 className="size-3.5" aria-hidden />}
        <Ext href={w.url}>{`#${w.number}`}</Ext>
        {w.author && <span translate="no">{w.author}</span>}
        <span>{fmtD(w.updatedAt)}</span>
      </p>
      <p className="mt-1 font-semibold leading-[17px] text-fg">{w.title}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {w.checks && CHECKS[w.checks] && <Chip tone={CHECKS[w.checks][1]}>{CHECKS[w.checks][0]}</Chip>}
        {w.labels.filter((l: string) => !["ai-ready", "from-app", "ai-working", "ai-plan"].includes(l)).map((l: string) => <Chip key={l}><span translate="no">{l}</span></Chip>)}
      </div>
      {w.summary && <p className="mt-1.5 line-clamp-3 text-[12px] leading-[16px] text-fg-2">{w.summary}</p>}
    </li>
  )
}

/* ---------------------------------------------------------------- Schválení */
function ApprovalsTab() {
  const { d, err, reload } = useLoad<any>(() => api.teamApprovals())
  return (
    <Card>
      <h2 className="font-serif text-xl">Klinické schválení</h2>
      <p className="mt-1 max-w-[680px] text-[12px] leading-[17px] text-fg-2">
        Změny, které mění, co aplikace běžcům říká o zdraví (prahy enginu, varování, bezpečnostní screening, cvičební programy),
        nesou štítek engine nebo safety. Bez schválení klinického garanta je nejde sloučit.
      </p>
      {d && !d.github && <Missing>GitHub není připojený (DOSSLAP_GITHUB_TOKEN) — rozhodnutí se nedá zapsat do PR.</Missing>}
      {!d ? <Loading err={err} /> : (
        <>
          {d.pending.length === 0 ? <p className="mt-4 text-[13px] text-fg-3">Nic nečeká na schválení.</p> : (
            <ul className="mt-3 space-y-3" data-testid="approvals-pending">
              {d.pending.map((w: any) => <Approval key={w.number} w={w} canDecide={d.canDecide} onDone={reload} />)}
            </ul>
          )}
          {d.decided.length > 0 && (
            <>
              <h3 className="mt-6 text-[12px] font-extrabold uppercase tracking-[.06em] text-fg-3">Rozhodnuto</h3>
              <ul className="mt-2 divide-y divide-white/[.07] text-[12.5px]">
                {d.decided.map((w: any) => (
                  <li key={w.number} className="flex flex-wrap items-center gap-2 py-2">
                    <Ext href={w.url}>{`#${w.number}`}</Ext><span className="min-w-0 flex-1 text-fg">{w.title}</span>
                    <Chip tone={w.clinical === "approved" ? "ok" : "watch"}>{w.clinical === "approved" ? "schváleno" : "k úpravě"}</Chip>
                    <span className="text-fg-3">{w.clinicalBy}{` · ${fmtD(w.clinicalAt)}`}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Card>
  )
}

function Approval({ w, canDecide, onDone }: { w: any; canDecide: boolean; onDone: () => void }) {
  const toast = useToast()
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState<string | null>(null)
  const decide = async (decision: "approve" | "changes") => {
    setBusy(decision)
    try { await api.teamDecide(w.number, { decision, note }); toast({ title: decision === "approve" ? "Schváleno — štítek clinical-approved je v PR" : "Vráceno k úpravě" }); onDone() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  return (
    <li className="rounded-xl border border-white/[.08] bg-white/[.03] p-3">
      <p className="flex flex-wrap items-center gap-2 text-[11.5px] text-fg-3">
        <Ext href={w.url}>{`PR #${w.number}`}</Ext>
        {w.labels.filter((l: string) => ["engine", "safety"].includes(l)).map((l: string) => <Chip key={l} tone="watch"><span translate="no">{l}</span></Chip>)}
        {w.checks && CHECKS[w.checks] && <Chip tone={CHECKS[w.checks][1]}>{CHECKS[w.checks][0]}</Chip>}
        {w.clinical === "changes" && <Chip tone="alert">vráceno k úpravě</Chip>}
      </p>
      <p className="mt-1 text-[14px] font-semibold text-fg">{w.title}</p>
      <div className="mt-2 rounded-lg bg-white/[.04] px-3 py-2">
        <p className="text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Změna pro běžce</p>
        <p className="mt-1 whitespace-pre-line text-[13px] leading-[18px] text-fg-soft">{w.summary || "PR změnu pro běžce nepopsal — otevřete ho na GitHubu."}</p>
      </div>
      {canDecide && (
        <div className="mt-3 grid gap-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Poznámka (u vrácení povinná)" aria-label="Poznámka"
            className="w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] text-fg" />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" busy={busy === "approve"} onClick={() => decide("approve")} data-testid="approve">Schválit</Button>
            <Button size="sm" variant="outline" busy={busy === "changes"} disabled={!note.trim()} onClick={() => decide("changes")}>Vrátit k úpravě</Button>
          </div>
        </div>
      )}
    </li>
  )
}

/* ---------------------------------------------------------------- Vydání */
function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="flex items-baseline justify-between gap-3 py-1 text-[12.5px]"><span className="text-fg-3">{k}</span><span className="text-right text-fg">{children}</span></div>
}

function ReleasesTab() {
  const { d, err, reload } = useLoad<any>(() => api.teamReleases())
  if (!d) return <Card><Loading err={err} /></Card>
  const p = d.production
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="team-releases">
      <Card>
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-serif text-xl">Produkce</h2>
          <button type="button" onClick={reload} className="text-fg-3 hover:text-fg" aria-label="Obnovit"><RefreshCw className="size-4" aria-hidden /></button>
        </div>
        <div className="mt-2 divide-y divide-white/[.06]">
          <Row k="Commit"><code translate="no">{p.sha ? p.sha.slice(0, 7) : "—"}</code></Row>
          <Row k="Engine"><span translate="no">{p.engine}</span></Row>
          <Row k="Prostředí"><span translate="no">{p.environment || "lokálně"}</span></Row>
          <Row k="Spuštěno">{fmtDT(p.bootedAt)}</Row>
          <Row k="Databáze">{p.db ? "trvalá" : "dočasná"}</Row>
          <Row k="Ranní synchronizace hodinek">{d.autosync ? <>{fmtDT(d.autosync.at)}{" · "}{`${d.autosync.synced}/${d.autosync.total} OK`}{d.autosync.failed ? `, ${d.autosync.failed} selhalo` : ""}</> : "od spuštění neproběhla"}</Row>
        </div>
        {d.staging ? (
          <p className="mt-3 flex items-center gap-2 text-[12.5px]">
            <Chip tone={d.staging.ok ? "ok" : "alert"}>{d.staging.ok ? "staging běží" : "staging neodpovídá"}</Chip>
            <Ext href={d.staging.url}><span translate="no">{d.staging.engine || d.staging.url}</span></Ext>
          </p>
        ) : <Missing>Staging není nastavený (DOSSLAP_STAGING_URL).</Missing>}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Chyby v prohlížeči</h2>
        <p className="mt-1 text-[12px] text-fg-2">{`Za 24 hodin: ${d.clientErrors.last24h} · od spuštění: ${d.clientErrors.sinceBoot}`}</p>
        {d.clientErrors.recent.length === 0 ? <p className="mt-3 text-[12.5px] text-ok">Žádné pády obrazovky.</p> : (
          <ul className="mt-2 space-y-1.5 text-[12px]">
            {d.clientErrors.recent.map((e: any, i: number) => (
              <li key={i} className="rounded-lg bg-alert/[.07] px-2.5 py-1.5">
                <span className="text-fg-3">{fmtDT(e.at)}</span>{" · "}<span translate="no" className="text-fg-2">{e.path || "—"}</span>
                <span translate="no" className="block truncate text-alert-soft">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Nasazení na Railway</h2>
        {!d.deployments.configured ? <Missing>Pro historii nasazení přidejte DOSSLAP_RAILWAY_TOKEN (token jen pro čtení).</Missing>
          : d.deployments.error ? <Missing>{d.deployments.error}</Missing> : (
            <ul className="mt-2 divide-y divide-white/[.06] text-[12.5px]">
              {d.deployments.items.map((x: any) => (
                <li key={x.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <Chip tone={x.status === "SUCCESS" ? "ok" : ["FAILED", "CRASHED"].includes(x.status) ? "alert" : "watch"}><span translate="no">{x.status}</span></Chip>
                  <code translate="no" className="text-fg-2">{(x.sha || "").slice(0, 7)}</code>
                  <span translate="no" className="min-w-0 flex-1 truncate text-fg">{x.message}</span>
                  <span className="text-fg-3">{fmtDT(x.createdAt)}</span>
                </li>
              ))}
            </ul>
          )}
      </Card>
      <Card>
        <h2 className="font-serif text-xl">Sloučené změny</h2>
        {d.merged.length === 0 ? <p className="mt-2 text-[12.5px] text-fg-3">Zatím žádné sloučené PR (Práce → Synchronizovat).</p> : (
          <ul className="mt-2 divide-y divide-white/[.06] text-[12.5px]">
            {d.merged.map((w: any) => (
              <li key={w.number} className="flex flex-wrap items-center gap-2 py-1.5">
                <Ext href={w.url}>{`#${w.number}`}</Ext>
                <span className="min-w-0 flex-1 text-fg">{w.title}</span>
                <Chip tone={w.deployed ? "accent" : "muted"}>{w.deployed ? "v produkci" : "čeká na nasazení"}</Chip>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

/* ---------------------------------------------------------------- Pilot */
function PilotTab() {
  const { d, err } = useLoad<any>(() => api.teamPilot())
  if (!d) return <Card><Loading err={err} /></Card>
  const fmt = (g: any) => (g.value == null ? "—" : `${String(g.value).replace(".", ",")}${g.unit ? ` ${g.unit}` : ""}`)
  const tone = (s: string | null) => (s === "ok" ? "ok" : s === "alert" ? "alert" : s === "watch" ? "watch" : "muted") as "ok" | "alert" | "watch" | "muted"
  const word: Record<string, string> = { ok: "splněno", watch: "zatím ne", alert: "pozor", info: "měříme" }
  return (
    <Card>
      <h2 className="font-serif text-xl">Pilot a rozhodovací brány</h2>
      <p className="mt-1 max-w-[700px] text-[12px] leading-[17px] text-fg-2">
        {"Čísla, na kterých stojí rozhodnutí z business plánu: aktivace a používání, fyzioterapeuti a jejich odchod, kalibrační data. Bez demo účtů. "}
        {`Stav k ${fmtD(d.asOf)}; týdenní snímek se ukládá.`}
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="team-pilot">
        {d.gates.map((g: any) => {
          const pct = g.target && g.value != null && g.key !== "churn" ? Math.min(100, (100 * g.value) / g.target) : null
          return (
            <div key={g.key} className="rounded-xl bg-white/[.04] px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[12px] font-bold text-fg-2">{g.label}</p>
                {g.status && <Chip tone={tone(g.status)}>{word[g.status] || g.status}</Chip>}
              </div>
              <p className="mt-1 text-[24px] font-bold tabular-nums text-fg">{fmt(g)}</p>
              {pct != null && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[.08]" aria-hidden>
                  <i className="block h-full rounded-full" style={{ width: `${pct}%`, background: C.accent }} />
                </div>
              )}
              <p className="mt-1.5 text-[11.5px] text-fg-3">{`Cíl: ${g.targetText}`}{g.n != null ? ` · n = ${g.n}` : ""}</p>
              <p className="text-[11px] text-fg-3">{g.source}{g.proxy ? " · zástupný ukazatel" : ""}</p>
            </div>
          )
        })}
      </div>
      {d.history.length > 1 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[12px]">
            <thead className="text-left text-fg-3"><tr><th className="py-1 pr-3 font-semibold">Týden od</th>{d.gates.map((g: any) => <th key={g.key} className="py-1 pr-3 font-semibold">{g.label}</th>)}</tr></thead>
            <tbody>
              {d.history.slice(-8).reverse().map((h: any) => (
                <tr key={h.week} className="border-t border-white/[.06]">
                  <td className="py-1 pr-3 text-fg-2">{fmtD(h.week)}</td>
                  {d.gates.map((g: any) => <td key={g.key} className="py-1 pr-3 tabular-nums text-fg">{h[g.key] == null ? "—" : String(h[g.key]).replace(".", ",")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
