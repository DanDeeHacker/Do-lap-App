// Profil → Kalendář (owner request 2026-10-26): the week's plan in the runner's own calendar.
// The backend serves it as an .ics feed behind a secret link (routers/calendar.py); Apple
// Calendar subscribes through webcal://, Google Calendar through its "add by URL" link. The
// calendar apps poll the feed themselves, so changes appear with their delay.
import { useEffect, useState } from "react"
import { CalendarPlus, Copy, RefreshCw } from "lucide-react"
import { api } from "@/api"
import { Button, useToast } from "@/ui"
import { fmtD } from "@/lib"

export function CalendarSync({ rid }: { rid: string }) {
  const toast = useToast()
  const [f, setF] = useState<any>(undefined)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.calendarFeed(rid).then(setF).catch(() => setF(null)) }, [rid])
  const act = async (fn: () => Promise<any>, msg: string) => {
    setBusy(true)
    try { setF(await fn()); toast({ title: msg }) }
    catch (e: any) { toast({ title: e?.message || "Nepovedlo se" }) }
    finally { setBusy(false) }
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(f.url); toast({ title: "Odkaz zkopírován" }) }
    catch { toast({ title: "Odkaz označte a zkopírujte ručně" }) }
  }
  return (
    <section className="mt-7 border-t border-white/[.08] pt-5" data-testid="calendar-sync">
      <h3 className="flex items-center gap-2 font-serif text-xl"><CalendarPlus className="size-5 text-fg-2" aria-hidden />Tréninky v kalendáři</h3>
      <p className="mt-1 text-[12px] leading-[17px] text-fg-2">
        Plán týdne se zobrazí ve vašem Apple nebo Google Kalendáři jako celodenní události s tepem, tempem a náplní tréninku. Když plán
        změníte nebo ho ráno upraví připravenost, kalendář se aktualizuje sám.
      </p>
      {f === undefined && <p className="mt-3 animate-pulse text-[12px] text-fg-3">Načítám…</p>}
      {f === null && <p className="mt-3 text-[12px] text-fg-3">Nastavení kalendáře se nepodařilo načíst.</p>}
      {f && !f.on && (
        <Button className="mt-3" icon={CalendarPlus} busy={busy} onClick={() => act(() => api.calendarFeedNew(rid), "Odkaz na kalendář je připravený")} data-testid="calendar-on">
          Zapnout odběr kalendáře
        </Button>
      )}
      {f?.on && (
        <div className="mt-3 grid gap-2" data-testid="calendar-links">
          <div className="grid gap-2 sm:grid-cols-2">
            <a href={f.webcal} className="btn btn-primary py-2.5 text-sm" data-testid="calendar-apple">Přidat do Apple Kalendáře</a>
            <a href={f.google} target="_blank" rel="noreferrer" className="btn btn-outline py-2.5 text-sm" data-testid="calendar-google">Přidat do Google Kalendáře</a>
          </div>
          <div className="flex gap-2">
            <input readOnly value={f.url} onFocus={(e) => e.currentTarget.select()} aria-label="Odkaz na kalendář" translate="no"
              className="min-w-0 flex-1 rounded-[12px] border border-white/10 bg-white/[.04] px-3 py-2 text-[11.5px] text-fg-2" />
            <button type="button" onClick={copy} className="btn btn-outline btn-sm shrink-0"><Copy className="size-3.5" aria-hidden />Kopírovat</button>
          </div>
          <details className="rounded-[12px] bg-white/[.04] px-3 py-2 text-[12px] leading-[17px] text-fg-soft">
            <summary className="cursor-pointer font-semibold text-fg-2">Jak na to</summary>
            <ul className="mt-1.5 space-y-1">
              <li><b className="text-fg">iPhone a Mac:</b> „Přidat do Apple Kalendáře" otevře Kalendář a nabídne odběr. Jak často se obnovuje, nastavíte v Kalendáři u odběru (doporučujeme každou hodinu).</li>
              <li><b className="text-fg">Google:</b> odkaz otevře Google Kalendář v prohlížeči a přidá ho. V telefonu se pak ukáže sám; Google odběry obnovuje po několika hodinách.</li>
              <li><b className="text-fg">Jiný kalendář</b> (Outlook…): zkopírujte odkaz a přidejte kalendář „z adresy URL".</li>
            </ul>
          </details>
          <p className="text-[11.5px] leading-[17px] text-fg-3">
            {"Odkaz je tajný — kdo ho má, vidí váš plán. "}
            {f.lastUsedAt ? `Kalendář si plán naposledy stáhl ${fmtD(f.lastUsedAt)}.` : "Zatím si ho žádný kalendář nestáhl."}
          </p>
          <div className="flex flex-wrap gap-3 text-[12px] font-bold">
            <button type="button" disabled={busy} className="inline-flex items-center gap-1 text-accent hover:underline" data-testid="calendar-rotate"
              onClick={() => act(() => api.calendarFeedNew(rid), "Nový odkaz je připravený — starý přestal fungovat")}>
              <RefreshCw className="size-3.5" aria-hidden />Vytvořit nový odkaz
            </button>
            <button type="button" disabled={busy} className="text-fg-3 hover:text-fg" data-testid="calendar-off"
              onClick={() => act(() => api.calendarFeedStop(rid), "Odběr kalendáře je vypnutý")}>Vypnout</button>
          </div>
        </div>
      )}
    </section>
  )
}
