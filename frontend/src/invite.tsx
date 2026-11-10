// Pozvánka do týmu (review 2026-10-30 N1): a Team Console role belongs to the account that opens
// the single-use link the owner passed on, signed in with the invited e-mail — not to whoever
// registers that e-mail first.
import { useEffect, useState } from "react"
import { Link, useParams } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { Mark, Wordmark } from "@/shell"

const ROLE: Record<string, string> = { owner: "vlastník", engineer: "inženýr", clinical: "klinický garant", support: "podpora", auditor: "auditor" }

export function InvitePage() {
  const { token = "" } = useParams()
  const { me, loading } = useApp()
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const accept = async () => {
    setBusy(true)
    setErr(null)
    try { setDone((await api.teamInviteAccept(token)).role) } catch (e: any) { setErr(e?.message || "Nepodařilo se") }
    finally { setBusy(false) }
  }
  return (
    <div className="motion-shell grid min-h-screen place-items-center bg-bg p-6 text-fg" data-testid="invite-page">
      <div className="card w-full max-w-md p-8">
        <div className="flex items-center gap-2 text-lg"><Mark /> <Wordmark /></div>
        <h1 className="mt-6 font-serif text-3xl">Pozvánka do týmu</h1>
        {loading ? <p className="mt-3 text-sm text-fg-2">Načítám…</p> : done ? (
          <>
            <p className="mt-3 text-sm leading-6 text-fg-2">Jste v týmu Došlapu jako <b className="text-fg">{ROLE[done] || done}</b>.</p>
            <a href="/admin" className="btn btn-primary mt-6">Otevřít Team Console</a>
          </>
        ) : !me ? (
          <>
            <p className="mt-3 text-sm leading-6 text-fg-2">
              Přihlaste se (nebo si založte účet) s e-mailem, na který pozvánka přišla, a pak tento odkaz otevřete znovu.
              Odkaz platí 7 dní a jen jednou.
            </p>
            <Link to="/auth" className="btn btn-primary mt-6">Přihlásit se</Link>
          </>
        ) : (
          <>
            <p className="mt-3 text-sm leading-6 text-fg-2">
              Pozvánku přijmete účtem <b className="text-fg">{me.email}</b>. Musí to být e-mail, na který byla poslaná.
            </p>
            {err && <p className="mt-3 text-sm text-alert" role="alert">{err}</p>}
            <button type="button" onClick={accept} disabled={busy} className="btn btn-primary mt-6" data-testid="invite-accept">Přijmout pozvánku</button>
          </>
        )}
      </div>
    </div>
  )
}

// Pozvánka od fyzioterapeuta (physio brief 2026-11-09 W2): a client the physio invited joins their care
// directly, without the queue. The page shows only who invites; accepting is the client's consent to share.
export function ClientInvitePage() {
  const { token = "" } = useParams()
  const { me, loading } = useApp()
  const [info, setInfo] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.inviteInfo(token).then(setInfo).catch((e: any) => setErr(e?.message || "Pozvánka neplatí")) }, [token])
  const accept = async () => {
    setBusy(true)
    setErr(null)
    try { await api.inviteAccept(token); setDone(true) } catch (e: any) { setErr(e?.message || "Nepodařilo se") }
    finally { setBusy(false) }
  }
  return (
    <div className="motion-shell grid min-h-screen place-items-center bg-bg p-6 text-fg" data-testid="client-invite-page">
      <div className="card w-full max-w-md p-8">
        <div className="flex items-center gap-2 text-lg"><Mark /> <Wordmark /></div>
        <h1 className="mt-6 font-serif text-3xl">Pozvánka od fyzioterapeuta</h1>
        {loading || (!info && !err) ? <p className="mt-3 text-sm text-fg-2">Načítám…</p> : !info ? (
          <p className="mt-3 text-sm leading-6 text-alert" role="alert">{err}</p>
        ) : done ? (
          <>
            <p className="mt-3 text-sm leading-6 text-fg-2">{`Jste v péči: ${info.physio}. Fyzioterapeut teď vidí vaše běhy, zátěž, spánek a HRV, deník a hlášené bolesti. Sdílení můžete kdykoli ukončit v Péči.`}</p>
            <a href="/app/care" className="btn btn-primary mt-6">Otevřít Péči</a>
          </>
        ) : (
          <>
            <p className="mt-3 text-sm leading-6 text-fg-2"><b className="text-fg">{info.physio}</b>{info.clinic ? ` (${info.clinic})` : ""}{" vás zve do péče v Došlapu."}</p>
            {info.message && <p className="mt-3 rounded-xl bg-white/[.05] px-3 py-2 text-sm leading-6">{`„${info.message}“`}</p>}
            <p className="mt-3 text-[13px] leading-5 text-fg-2">Po přijetí uvidí vaše běhy, zátěž, spánek a HRV, deník a hlášené bolesti. Došlap sleduje zátěž a pomáhá fyzioterapeutovi; nestanovuje diagnózu.</p>
            {!me ? (
              <>
                <p className="mt-3 text-sm text-fg-2">Přihlaste se nebo si založte účet a pak tento odkaz otevřete znovu. Odkaz platí jen jednou.</p>
                <Link to="/auth" className="btn btn-primary mt-6">Přihlásit se</Link>
              </>
            ) : me.role !== "runner" ? (
              <p className="mt-3 text-sm text-alert">Pozvánku přijímá účet běžce.</p>
            ) : (
              <>
                {err && <p className="mt-3 text-sm text-alert" role="alert">{err}</p>}
                <button type="button" onClick={accept} disabled={busy} className="btn btn-primary mt-6" data-testid="client-invite-accept">Přijmout a sdílet data</button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
