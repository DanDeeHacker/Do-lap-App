// UX audit F07 — the words a new runner meets, in plain Czech, one tap from every "?"
// (InfoDot) and from the tab tours. Mounted once in the layout; opened by an event so
// the small ui.tsx helper does not depend on this file.
import { useEffect, useState } from "react"
import { Sheet } from "@/ui"
import { QUAD } from "@/lib"

export const GLOSSARY_EVENT = "doslap:glossary"
export const openGlossary = () => window.dispatchEvent(new Event(GLOSSARY_EVENT))

const TERMS: [string, string][] = [
  ["Vaše norma", "Jak to u vás obvykle vypadá, spočítané z vašich vlastních běhů a nocí za posledních 8–12 týdnů. Nikdy průměr ostatních."],
  ["Skóre dne", "Číslo 0–100, čím vyšší, tím lépe. Shrnuje zátěž, techniku běhu a příznaky proti vaší normě."],
  ["Signál", "Jedna věc, která se odchyluje od vaší normy, například prudký nárůst klesání. U každého je, kolik bodů ubírá ze skóre."],
  ["A, B, C u signálu", "Síla důkazů z výzkumu, že signál souvisí s přetížením: A silná, B střední, C slabší nebo nepřímá."],
  ["Připravenost", "Jak jste zotavení po noci: HRV, klidový tep a spánek proti vaší normě, 20–100 %. Po špatné noci aplikace sníží dnešní stropy."],
  ["HRV", "Variabilita tepu přes noc. Když je nižší než obvykle, bývá to znak únavy, stresu nebo začínající nemoci."],
  ["Příznaky", "Bolest, ztuhlost a únava, které zapíšete v check-inu nebo po běhu."],
  ["Zátěž", "Kolik trénujete proti tomu, co jste v posledních týdnech zvládli bez obtíží."],
  ["Mechanika", "Technika běhu z hodinek: kontakt se zemí, kadence, odraz a vyváženost kroku, vždy proti vaší normě ve stejném terénu a tempu."],
  ["Stav", `${QUAD.stable.t}: ${QUAD.stable.d} ${QUAD.overreaching.t}: ${QUAD.overreaching.d} ${QUAD.silent.t}: ${QUAD.silent.d} ${QUAD.critical.t}: ${QUAD.critical.d}`],
  ["Kapacita", "Kolik zátěže tělo prokazatelně snese za den a za týden. Roste s tím, co zvládáte bez obtíží."],
  ["Strop", "Kapacita plus bezpečná rezerva. Nad stropem roste riziko přetížení."],
  ["Nevstřebáno", "Zátěž posledních dní, kterou tělo ještě nevstřebalo. Starší dny se počítají jen zčásti, dnešek celý."],
  ["Body zátěže", "Tep × čas. U posilování a plavání náročnost × minuty. Díky tomu jdou běh, kolo i posilování sečíst."],
  ["Tvrdá práce (Z4+)", "Minuty s tepem nad 80 % tepové rezervy, tedy úseky, tempové běhy a závody."],
  ["Check-in", "Krátký denní dotazník na bolest, ztuhlost a únavu. Hodinky tohle neznají, proto je pro hodnocení důležitý."],
]

export function GlossarySheet() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const on = () => setOpen(true)
    window.addEventListener(GLOSSARY_EVENT, on)
    document.body.dataset.glossary = "1"          // InfoDot shows its link only where the sheet is mounted
    return () => { window.removeEventListener(GLOSSARY_EVENT, on); delete document.body.dataset.glossary }
  }, [])
  return (
    <Sheet open={open} onClose={() => setOpen(false)} layer="z-[140]">
      <div data-testid="glossary">
        <p className="t-label">Slovníček</p>
        <h2 className="mt-1 font-serif text-[24px] leading-tight text-fg">Pojmy v aplikaci</h2>
        <dl className="mt-4 divide-y divide-white/[.07]">
          {TERMS.map(([t, d]) => (
            <div key={t} className="py-2.5">
              <dt className="text-[14px] font-bold text-fg">{t}</dt>
              <dd className="mt-0.5 text-[13px] leading-5 text-fg-2">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Sheet>
  )
}
