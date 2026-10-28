// Team Console (owner request 2026-10-27): Admin → Tým, Inbox, Práce, Schválení, Vydání, Pilot.
// The founders run the AI engineering team (gstack sprints on GitHub) from the app; the backend
// (routers/team.py) checks every permission, the tabs only follow the role it reports. The app
// never deploys: it writes issues, labels and comments, reads what runs, and (issue #3) lets an
// owner review a pull request and merge it, after the server re-checked every gate.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router"
import { Bot, CheckCircle2, Download, ExternalLink, GitPullRequest, Play, RefreshCw, RotateCcw, Send, ShieldCheck, TriangleAlert, Upload } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Segmented, Sheet, useToast } from "@/ui"
import { fmtD, fmtDT } from "@/lib"
import { C } from "@/tokens"

type TeamMe = { role: string; perms: string[]; email: string; config: { github: boolean; mergeToken?: boolean; githubRepo: string; webhook: boolean; railway: boolean; staging: string | null; personas?: boolean; personaToken?: boolean } }

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
    // simulated runners — staging only (DOSSLAP_PERSONAS), owners and engineers
    ["personas", "Persony", !!me?.config.personas && ["owner", "engineer"].includes(me?.role || "")],
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
        {me && tab === "personas" && <PersonasTab />}
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
  const [source, setSource] = useState<"all" | "people" | "synthetic">("all")
  const { d, err, reload } = useLoad<any>(() => api.teamInbox(status, source), [status, source])
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
        <div className="flex flex-wrap gap-2">
          <Segmented size="sm" value={source} onChange={setSource} ariaLabel="Odkud poznámky jsou"
            options={[["all", "Vše"], ["people", "Od lidí"], ["synthetic", "Od person"]] as const} />
          <Segmented size="sm" value={status} onChange={setStatus} ariaLabel="Stav poznámek"
            options={[["open", "Otevřené"], ["done", "Vyřešené"], ["wontfix", "Nebude"]] as const} />
        </div>
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
                {n.synthetic ? (
                  <span className="inline-flex items-center gap-1">
                    <Chip tone="load"><Bot className="size-3" aria-hidden />{`persona ${n.synthetic.persona || ""}`}</Chip>
                    {n.source === "synthetic-ai" && <Chip>AI kontrola</Chip>}
                    {(n.synthetic.repeats || 1) > 1 && <Chip>{`${n.synthetic.repeats}× (naposledy ${n.synthetic.lastSeen || "—"})`}</Chip>}
                    {n.synthetic.verifiedAt && <Chip tone="ok">{`po opravě ověřeno ${fmtD(n.synthetic.verifiedAt)}`}</Chip>}
                  </span>
                ) : (
                  <span>· {n.author.isOwner ? "vlastník" : n.author.role === "physio" ? "fyzioterapeut" : "běžec"}{n.author.name ? ` (${n.author.name})` : ""}</span>
                )}
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
                {items.filter((w) => w.stage === s).slice(0, 12).map((w) => <WorkCard key={`${w.kind}${w.number}`} w={w} me={me} onChanged={reload} />)}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Card>
  )
}

function WorkCard({ w, me, onChanged }: { w: any; me: TeamMe; onChanged: () => void }) {
  const toast = useToast()
  const [review, setReview] = useState(false)
  const [busy, setBusy] = useState(false)
  const owner = me.perms.includes("pr.merge")
  const open = w.kind === "pr" && w.state === "open"
  const go = async () => {
    setBusy(true)
    try { await api.teamPlanGo(w.number); toast({ title: "Go odesláno — AI tým plán převezme" }); onChanged() }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
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
      {open && <Button size="sm" variant="outline" className="mt-2" icon={GitPullRequest} onClick={() => setReview(true)} data-testid={`review-${w.number}`}>{owner ? "Zkontrolovat a sloučit" : "Zkontrolovat"}</Button>}
      {w.kind === "issue" && w.stage === "needs_owner" && owner && <Button size="sm" className="mt-2" busy={busy} onClick={go} data-testid={`go-${w.number}`}>Schválit plán (go)</Button>}
      {review && <ReviewSheet number={w.number} onClose={() => setReview(false)} onMerged={onChanged} />}
    </li>
  )
}

/** Issue #3 — review a pull request and, as an owner, merge it. Everything shown is read from
 *  GitHub just now; the server checks the gates again when Merge is pressed. */
function ReviewSheet({ number, onClose, onMerged }: { number: number; onClose: () => void; onMerged: () => void }) {
  const toast = useToast()
  const [cso, setCso] = useState(false)
  const { d, err, reload } = useLoad<any>(() => api.teamPr(number, cso), [cso])
  const [confirm, setConfirm] = useState("")
  const [password, setPassword] = useState("")
  const [remark, setRemark] = useState("")
  const [busy, setBusy] = useState<string | null>(null)
  const want = `MERGE #${number}`
  const act = async (what: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(what)
    try { await fn(); toast({ title: ok }); return true }
    catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }); reload(); return false }
    finally { setBusy(null) }
  }
  const merge = async () => {
    if (await act("merge", () => api.teamMerge(number, { sha: d.sha, confirm, password, cso }), "Sloučeno — nasazení do produkce začne samo")) { onMerged(); onClose() }
  }
  const blocked = !d || d.blockers.length > 0
  const ready = d?.canMerge && d?.mergeToken && !blocked && confirm.trim() === want && (!d.needsPassword || password.length > 0)
  return (
    <Sheet open onClose={onClose}>
      <div data-testid="review-sheet">
        {!d ? <Loading err={err} /> : (
          <>
            <p className="flex flex-wrap items-center gap-2 text-[11.5px] text-fg-3">
              <Ext href={d.url}>{`PR #${d.number}`}</Ext><span translate="no">{d.author}</span>
              {d.labels.map((l: string) => <Chip key={l} tone={["engine", "safety", "security"].includes(l) ? "watch" : "muted"}><span translate="no">{l}</span></Chip>)}
            </p>
            <h3 className="mt-1 font-serif text-lg leading-[22px]">{d.title}</h3>
            <div className="mt-3 rounded-lg bg-white/[.04] px-3 py-2">
              <p className="text-[11px] font-bold uppercase tracking-[.06em] text-fg-3">Změna pro běžce</p>
              <p className="mt-1 whitespace-pre-line text-[13px] leading-[18px] text-fg-soft">{d.summary || "PR změnu pro běžce nepopsal."}</p>
            </div>
            <p className="mt-3 flex flex-wrap items-center gap-2 text-[12px] text-fg-2">
              {d.checks && CHECKS[d.checks] ? <Chip tone={CHECKS[d.checks][1]}>{CHECKS[d.checks][0]}</Chip> : <Chip tone="watch">CI neznámé</Chip>}
              <span>{`${d.files ?? "?"} souborů · +${d.additions ?? 0} −${d.deletions ?? 0}`}</span>
              <Ext href={d.diffUrl}>Změny na GitHubu</Ext>
            </p>
            {d.checkItems.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[12px] text-fg-2" data-testid="review-checks">
                {d.checkItems.map((c: any, i: number) => <li key={i}><span translate="no">{c.name}</span>{` — ${c.conclusion ?? "běží"}`}</li>)}
              </ul>
            )}
            {d.labels.includes("security") && (
              <label className="mt-3 flex items-start gap-2 text-[12.5px] text-fg-soft">
                <input type="checkbox" checked={cso} onChange={(e) => setCso(e.target.checked)} className="mt-0.5" />
                <span>V PR je odkaz na zprávu /cso (štítek security).</span>
              </label>
            )}
            {d.blockers.length > 0 ? (
              <ul className="mt-3 space-y-1 rounded-lg border border-white/[.08] px-3 py-2 text-[12.5px] text-watch" data-testid="review-blockers">
                {d.blockers.map((b: string) => <li key={b}>{b}</li>)}
              </ul>
            ) : <p className="mt-3 text-[12.5px] text-ok">Všechny podmínky pro sloučení jsou splněné.</p>}
            {d.canMerge && (
              <>
                <textarea value={remark} onChange={(e) => setRemark(e.target.value)} rows={2} placeholder="Připomínka pro AI tým (přidá se do PR jako komentář)" aria-label="Připomínka"
                  className="mt-3 w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] text-fg" />
                <Button size="sm" variant="outline" className="mt-2" busy={busy === "remark"} disabled={!remark.trim()}
                  onClick={async () => { if (await act("remark", () => api.teamPrComment(number, remark.trim()), "Připomínka je v PR")) setRemark("") }}>Poslat připomínku</Button>
                <div className="mt-4 border-t border-white/[.07] pt-3">
                  {!d.mergeToken ? <Missing>Sloučení z aplikace není zapnuté — nastavte DOSSLAP_GITHUB_MERGE_TOKEN v proměnných Railway. Do té doby sloučte na GitHubu.</Missing> : (
                    <div className="grid gap-2">
                      <p className="text-[12px] text-fg-2">{`Sloučením se změna nasadí do produkce. Pro potvrzení napište `}<b translate="no">{want}</b>{d.needsPassword ? " a své heslo." : "."}</p>
                      <input value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="Potvrzení" placeholder={want} autoComplete="off"
                        className="w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] text-fg" data-testid="merge-confirm" />
                      {d.needsPassword && <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Heslo" placeholder="Heslo" autoComplete="current-password"
                        className="w-full rounded-xl border border-white/10 bg-panel px-3 py-2 text-[13px] text-fg" data-testid="merge-password" />}
                      <Button busy={busy === "merge"} disabled={!ready} onClick={merge} data-testid="merge">Sloučit do main</Button>
                    </div>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Sheet>
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
    <>
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
    <BehaviourExport />
    </>
  )
}

/* ---------------------------------------------------------------- Pilot → profile for the personas */
// personas stage 3: an anonymous profile of how the consenting pilot runners use the app
// (groups of 5+, behaviour only), downloaded here and imported on staging → Persony
function BehaviourExport() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const get = async () => {
    setBusy(true)
    try {
      const prof = await api.teamBehaviourProfile()
      const groups = Object.keys(prof.groups || {})
      if (!groups.length) { toast({ title: `Zatím málo souhlasů (${prof.consenting}) — skupina potřebuje aspoň ${prof.kMin} lidí` }); return }
      const url = URL.createObjectURL(new Blob([JSON.stringify(prof, null, 1)], { type: "application/json" }))
      const a = document.createElement("a")
      a.href = url
      a.download = `doslap-profil-chovani-${(prof.generatedAt || "").slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  return (
    <Card className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-[640px]">
          <h2 className="font-serif text-xl">Profil chování pro persony</h2>
          <p className="mt-1 text-[12px] leading-[17px] text-fg-2">
            Jak aplikaci používají běžci, kteří s tím v Profilu souhlasili: kdy ji otevírají, které části a jak dlouho, jak často
            vyplní check-in a ohodnotí běh. Jen skupiny aspoň 5 lidí, žádná zdravotní data. Soubor nahrajte na stagingu v záložce Persony.
          </p>
        </div>
        <Button size="sm" variant="outline" icon={Download} busy={busy} onClick={get} data-testid="behaviour-export">Stáhnout profil chování</Button>
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------- Persony (staging) */
const PHASE: Record<string, string> = { night: "před 1. dnem", morning: "ráno", evening: "večer" }

function PersonasTab() {
  const toast = useToast()
  const { d, err, reload } = useLoad<any>(() => api.personas())
  const [sel, setSel] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const file = useRef<HTMLInputElement | null>(null)
  const running = !!d?.personas?.some((p: any) => p.run?.status === "running")
  useEffect(() => {
    if (!running) return
    const t = setInterval(reload, 4000)
    return () => clearInterval(t)
  }, [running, reload])
  const act = async (k: string, fn: () => Promise<any>, msg: string) => {
    setBusy(k)
    try { await fn(); toast({ title: msg }); reload() } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(null) }
  }
  const upload = async (f: File) => {
    try { const data = JSON.parse(await f.text()); await act("cal", () => api.personaCalibrationPut(data), "Profil chování nahraný — persony ho používají") }
    catch { toast({ title: "Soubor není platné JSON" }) }
  }
  if (!d) return <Card><Loading err={err} /></Card>
  return (
    <div className="grid gap-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="max-w-[680px]">
            <h2 className="font-serif text-xl">Simulovaní běžci</h2>
            <p className="mt-1 text-[12px] leading-[17px] text-fg-2">
              {`Pět person žije na vlastních hodinách a prochází ${d.simDays} dní tréninku podle plánu aplikace. Po každém půldni se kontroluje, jestli `}
              {"si obrazovky neodporují a jestli aplikace dodržuje vlastní pravidla; co nesedí, přijde do Inboxu jako poznámka od persony. "}
              {d.reportsTo ? "Poznámky jdou do produkčního Inboxu." : "Poznámky zůstávají v Inboxu tohoto prostředí."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={Play} busy={busy === "all"} disabled={running} onClick={() => act("all", () => api.personaAdvanceAll(7), "Všechny persony běží o týden dál")} data-testid="personas-week">Všichni o týden dál</Button>
            <Button size="sm" variant="outline" icon={Upload} busy={busy === "cal"} onClick={() => file.current?.click()}>Nahrát profil chování</Button>
            <input ref={file} type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </div>
        </div>
        {d.calibration
          ? <p className="mt-2 text-[12px] text-fg-3">{`Chování podle profilu z ${fmtD(d.calibration.generatedAt)}: `}{Object.entries(d.calibration.groups || {}).map(([g, n]) => `${g} ${n}`).join(", ")}</p>
          : <Missing>Persony se chovají podle vlastních zvyků — profil chování z pilotu zatím není nahraný (Pilot → Stáhnout profil chování v produkci).</Missing>}
        <ul className="mt-3 divide-y divide-white/[.07]" data-testid="personas">
          {d.personas.map((p: any) => {
            const r = p.run
            const checks = Object.entries(r?.stats?.checks || {})
            return (
              <li key={p.key} className="py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1">
                    <b className="text-[14px] text-fg">{p.name}</b>
                    <span className="block text-[12px] text-fg-3">{p.label}</span>
                  </span>
                  {r ? (
                    <>
                      <Chip tone={r.status === "error" ? "alert" : r.status === "running" ? "watch" : "muted"}>
                        {r.status === "running" ? "běží…" : r.status === "error" ? "chyba" : `den ${r.day} · ${PHASE[r.phase] || r.phase}`}
                      </Chip>
                      <span className="text-[12px] text-fg-3">{fmtD(r.simDate)}</span>
                      <Chip tone={(r.stats?.findings || 0) ? "watch" : "ok"}>{`${r.stats?.findings || 0} nálezů`}</Chip>
                      {r.behaviour?.calibrated && <Chip tone="info">kalibrováno</Chip>}
                    </>
                  ) : <Chip>zatím nezačala</Chip>}
                  <span className="flex gap-1.5">
                    <Button size="sm" variant="outline" busy={busy === `d${p.key}`} disabled={running}
                      onClick={() => act(`d${p.key}`, () => api.personaAdvance(p.key, 1), `${p.name}: další den`)}>+1 den</Button>
                    <Button size="sm" variant="outline" busy={busy === `w${p.key}`} disabled={running}
                      onClick={() => act(`w${p.key}`, () => api.personaAdvance(p.key, 7), `${p.name}: týden běží`)}>+7 dní</Button>
                    <button type="button" disabled={running || busy !== null} aria-label={`Začít znovu: ${p.name}`} className="btn btn-outline btn-sm"
                      onClick={() => act(`r${p.key}`, () => api.personaReset(p.key), `${p.name} začíná znovu`)}><RotateCcw className="size-3.5" aria-hidden /></button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSel(sel === p.key ? null : p.key)}>Deník</button>
                  </span>
                </div>
                {r?.error && <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-alert/[.07] p-2 text-[11px] text-alert-soft" translate="no">{r.error}</pre>}
                {checks.length > 0 && <p className="mt-1.5 text-[11.5px] text-fg-3" translate="no">{checks.map(([k, v]) => `${k} ${v}×`).join(" · ")}</p>}
                {sel === p.key && <PersonaJournal k={p.key} />}
              </li>
            )
          })}
        </ul>
      </Card>
    </div>
  )
}

function PersonaJournal({ k }: { k: string }) {
  const { d, err } = useLoad<any>(() => api.personaDays(k, 21), [k])
  if (!d) return <Loading err={err} />
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[640px] text-[12px]">
        <thead className="text-left text-fg-3">
          <tr><th className="py-1 pr-3 font-semibold">Den</th><th className="py-1 pr-3 font-semibold">Události</th><th className="py-1 pr-3 font-semibold">Aplikace ráno</th>
            <th className="py-1 pr-3 font-semibold">Persona udělala</th><th className="py-1 pr-3 font-semibold">Nálezy</th></tr>
        </thead>
        <tbody>
          {d.days.map((x: any) => (
            <tr key={x.date} className="border-t border-white/[.06] align-top">
              <td className="py-1.5 pr-3 text-fg-2">{`${x.day ?? ""}. · ${fmtD(x.date)}`}</td>
              <td className="py-1.5 pr-3 text-fg-2">{(x.events || []).join(", ") || "—"}{x.checkin ? " · check-in" : ""}</td>
              <td className="py-1.5 pr-3 text-fg">
                {x.morning?.typeLabel || "—"}
                {x.morning?.readiness != null && <span className="text-fg-3">{` · připravenost ${x.morning.readiness}`}</span>}
                {(x.morning?.planToday || []).filter((i: any) => i.kind === "run").map((i: any) => <span key={i.type} className="block text-fg-3">{`plán: ${i.label} ${i.km?.lo ?? ""}–${i.km?.hi ?? ""} km`}</span>)}
              </td>
              <td className="py-1.5 pr-3 text-fg">{(x.did || []).map((a: any) => `${a.kind} ${a.amount}${a.followed ? "" : " (mimo plán)"}`).join(", ") || "odpočinek"}</td>
              <td className="py-1.5 pr-3">{(x.findings || []).length ? <span className="text-watch">{x.findings.join(" · ")}</span> : <span className="text-fg-3">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
