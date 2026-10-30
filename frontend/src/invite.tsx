// Pozvánka do týmu (review 2026-10-30 N1): a Team Console role belongs to the account that opens
// the single-use link the owner passed on, signed in with the invited e-mail — not to whoever
// registers that e-mail first.
import { useState } from "react"
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
