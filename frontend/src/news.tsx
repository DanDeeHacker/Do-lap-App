// v0.12.14 — Co je nového (NOOP's in-app "What's new"): what changed in the app, once per release,
// on Dnes for accounts that existed before it (a new account has nothing "new"), never over the
// morning or evening report; the whole list stays in the profile menu.
import { useEffect, useState } from "react"
import { CalendarDays, Footprints, LayoutGrid, Route, Sparkles, type LucideIcon } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { useReport } from "@/report"
import { Button, Label, Sheet } from "@/ui"

type Release = { id: string; date: string; items: [LucideIcon, string, string][] }
// newest first; the id is what the account remembers as seen
export const NEWS: Release[] = [
  {
    id: "2026-10-14", date: "2026-10-14", items: [
      [Route, "Detail běhu", "Trasa (vidíte ji jen vy), mezičasy a průběh tempa a tepu. Otevřete ho z Deníku i ze seznamů běhů na Mechanice a Zátěži, kde běh poznáte podle tvaru trasy."],
      [Footprints, "Boty u každého běhu", "Výchozí pár, spárování s botami z Garminu a kilometry pro každý pár zvlášť (profil → Boty)."],
      [LayoutGrid, "Moje čísla na Dnes", "Pod kartou Dnes si vyberte a seřaďte čísla. Každé ukazuje vývoj za poslední dny, klepnutím otevřete celý graf."],
      [CalendarDays, "Výhled na zítra a Deník", "Výhled začíná zítřejším dnem z plánu týdne a slabší noc bere z vašich nocí. Deník nahoře shrnuje týden a měsíc."],
    ],
  },
]

const fmtDate = (d: string) => new Date(d + "T12:00:00").toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" })

export function NewsSheet({ open, onClose, all = false }: { open: boolean; onClose: () => void; all?: boolean }) {
  const list = all ? NEWS : NEWS.slice(0, 1)
  return (
    <Sheet open={open} onClose={onClose} footer={<Button className="w-full" onClick={onClose}>Rozumím</Button>}>
      <div data-testid="news-sheet">
        <span className="flex items-center gap-2"><Sparkles className="size-4 text-accent" aria-hidden /><Label>Co je nového</Label></span>
        {list.map((r) => (
          <section key={r.id} className="mt-3">
            <p className="text-[12px] text-fg-3">{fmtDate(r.date)}</p>
            <ul className="mt-2 grid gap-3">
              {r.items.map(([Icon, title, text]) => (
                <li key={title} className="flex gap-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-[11px] bg-accent/12 text-accent"><Icon className="size-[18px]" aria-hidden /></span>
                  <span className="min-w-0">
                    <b className="block text-[14px] font-bold text-fg">{title}</b>
                    <span className="mt-0.5 block text-[12.5px] leading-5 text-fg-2">{text}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Sheet>
  )
}

/** On Dnes: the latest release, once, for an account older than it. */
export function NewsPrompt() {
  const { me, viewing, touring } = useApp()
  const { showing } = useReport()
  const [due, setDue] = useState(false)
  const [open, setOpen] = useState(false)
  const latest = NEWS[0]
  useEffect(() => {
    if (!me || me.guest || viewing || touring || me.role !== "runner" || !latest) return
    let alive = true
    api.getSettings().then((s: any) => {
      if (!alive || s?.news_seen === latest.id) return
      if (!s?.user_since || s.user_since >= latest.date) return       // a new account: nothing is "new"
      setDue(true)
    }).catch(() => {})
    return () => { alive = false }
  }, [me?.id, viewing, touring])
  useEffect(() => { if (due && !showing) { const t = setTimeout(() => setOpen(true), 600); return () => clearTimeout(t) } }, [due, showing])
  const close = () => {
    setOpen(false)
    setDue(false)
    api.patchSettings({ news_seen: latest.id }).catch(() => {})
  }
  return <NewsSheet open={open} onClose={close} />
}
