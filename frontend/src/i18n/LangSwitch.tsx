// Čeština / English (British) — on the sign-up page and in the profile menu.
import { api } from "@/api"
import { setLang, useLang, type Lang } from "@/i18n/lang"

export function LangSwitch({ account = false, className = "" }: { account?: boolean; className?: string }) {
  const lang = useLang()
  const pick = async (l: Lang) => {
    if (l === lang) return
    if (account) {
      try { await api.setLang(l) } catch { /* the browser keeps the choice anyway */ }
    }
    setLang(l)
  }
  return (
    <div translate="no" data-no-i18n className={`inline-flex rounded-full bg-white/[.06] p-0.5 text-[12px] font-bold ${className}`}
      role="radiogroup" aria-label="Jazyk / Language" data-testid="lang-switch">
      {([["cs", "Čeština"], ["en", "English"]] as const).map(([l, label]) => (
        <button key={l} type="button" role="radio" aria-checked={lang === l} onClick={() => void pick(l)}
          data-testid={`lang-${l}`}
          className={`rounded-full px-3 py-1 transition ${lang === l ? "bg-accent text-ink" : "text-fg-2 hover:text-fg"}`}>
          {label}
        </button>
      ))}
    </div>
  )
}
