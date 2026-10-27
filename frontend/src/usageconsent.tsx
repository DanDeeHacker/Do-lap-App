// Profil → Pomoc s vývojem (owner request 2026-10-27, personas stage 3): the runner may let the
// way they use the app count towards an anonymous summary the test personas copy. Behaviour only
// (when the app opens, which tabs and for how long, check-ins and rated runs), groups of 5 and
// more, nothing about health; off by default, switched off any time.
import { useEffect, useState } from "react"
import { FlaskConical } from "lucide-react"
import { api } from "@/api"
import { Switch, useToast } from "@/ui"

export function UsageConsent() {
  const toast = useToast()
  const [on, setOn] = useState<boolean | null>(null)
  useEffect(() => { api.getSettings().then((s: any) => setOn(!!s?.share_usage)).catch(() => setOn(null)) }, [])
  const change = async (v: boolean) => {
    const prev = on
    setOn(v)
    try {
      await api.patchSettings({ share_usage: v })
      toast({ title: v ? "Díky — váš způsob používání se započítá do souhrnu" : "Souhlas je odvolaný" })
    } catch (e: any) { setOn(prev); toast({ title: e?.message || "Nepovedlo se" }) }
  }
  if (on === null) return null
  return (
    <section className="mt-7 border-t border-white/[.08] pt-5" data-testid="usage-consent">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="flex items-center gap-2 font-serif text-xl"><FlaskConical className="size-5 text-fg-2" aria-hidden />Pomoc s vývojem</h3>
          <p className="mt-1 text-[12px] leading-[17px] text-fg-2">
            Aplikaci testují i simulovaní běžci. Smějí se při tom řídit tím, jak ji používáte vy: kdy ji otevíráte, které části
            a jak dlouho, jak často vyplníte check-in a ohodnotíte běh. Do souhrnu jdou jen skupiny aspoň 5 lidí, nikdy nic o
            vašem zdraví ani tréninku. Souhlas můžete kdykoli odvolat.
          </p>
        </div>
        <Switch checked={on} onChange={change} label="Započítat můj způsob používání do anonymního souhrnu" />
      </div>
    </section>
  )
}
