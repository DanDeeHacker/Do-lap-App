// Dev-only living styleguide for the shared components (route /ui, only in `vite dev`).
// Not part of the production bundle.
import { useState } from "react"
import { RefreshCw, TrendingUp, Zap, Flag, Bandage } from "lucide-react"
import { AlertBanner, AxisLineChart, Bars, Button, Card, Chip, Empty, FactorBar, InfoDot, Label, Ring, Segmented, Sheet, Slider, Sparkline, Switch, useToast } from "@/ui"
import { C } from "@/tokens"
import { FileText } from "lucide-react"

export default function Gallery() {
  const [seg, setSeg] = useState<"all" | "terr">("all")
  const [sw, setSw] = useState(true)
  const [open, setOpen] = useState<number>(1)
  const [pain, setPain] = useState(6)
  const [legs, setLegs] = useState(2)
  const [sheet, setSheet] = useState(false)
  const toast = useToast()
  const weekly = [61.9, 42.4, 66.2, 68.4, 42.7, 63.5, 57.5, 60.4, 65.1, 80.3, 68.9, 149.5]
  const pts = [0, 1, 35, 27, 31, 5, 10, 18, 6, 3, 15, 50, 74].map((v, i) => ({ t: `2026-${String(7 + Math.floor(i / 4)).padStart(2, "0")}-${String(1 + (i % 4) * 7).padStart(2, "0")}`, v }))
  return (
    <div className="motion-shell min-h-screen p-5 text-fg md:p-10">
      <div className="mx-auto grid max-w-5xl gap-4">
        <div><Label>Došlap · shared components</Label><h1 className="mt-1 font-serif text-4xl tracking-[-.04em]">Komponenty a stavy</h1></div>
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <Label>Buttons</Label>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button>Primary</Button><Button variant="secondary">Secondary</Button><Button variant="outline">Outline</Button>
              <Button variant="danger">Nahlásit zranění</Button><Button disabled>Disabled</Button><Button busy>Ukládám…</Button>
              <Button size="sm" variant="outline" icon={RefreshCw}>Synchronizovat</Button><Button size="sm" onClick={() => toast({ title: "Check-in uložen" })}>Toast</Button>
            </div>
          </Card>
          <Card>
            <Label>Chips · segmented · switch</Label>
            <div className="mt-3 flex flex-wrap gap-2">
              <Chip tone="ok">v normě</Chip><Chip tone="watch">sledovat</Chip><Chip tone="alert">Achillovka (P)</Chip><Chip tone="load">zátěž 100</Chip>
              <Chip tone="info">silnice</Chip><Chip tone="self">TÝD</Chip><Chip>odhad</Chip><Chip tone="accent">A · cílový</Chip>
            </div>
            <div className="mt-3"><Segmented options={[["all", "Všechen terén"], ["terr", "Podle profilu terénu"]] as const} value={seg} onChange={setSeg} /></div>
            <div className="mt-3 flex items-center gap-3"><Switch checked={sw} onChange={setSw} label="AI shrnutí" /><Switch checked={!sw} onChange={(v) => setSw(!v)} label="Kulhám" tone="alert" /><span className="text-xs text-fg-2">Switch</span></div>
          </Card>
          <Card>
            <Label>Alert banners</Label>
            <div className="mt-3 grid gap-2">
              <AlertBanner tone="stop" title="Bolest omezuje pohyb — dnes neběhat">Hýbejte se jen tak, aby to nebolelo, a nechte to posoudit fyzioterapeutem do 48 hodin.</AlertBanner>
              <AlertBanner tone="alert" title="Nahlásil jste bolest 8/10" collapsible open={open === 1} onToggle={() => setOpen(open === 1 ? 0 : 1)}>Achillova šlacha (P) · Bolest nad 3/10 stojí za pozornost.</AlertBanner>
              <AlertBanner tone="watch" icon={Zap} title="Akutní přetížení po běhu" collapsible open={open === 2} onToggle={() => setOpen(open === 2 ? 0 : 2)}>Den dva bez běhu, pak jen volně a krátce.</AlertBanner>
              <AlertBanner tone="watch" icon={TrendingUp} title="Bolest týden od týdne roste" collapsible open={open === 3} onToggle={() => setOpen(open === 3 ? 0 : 3)}>Průměr za 7 dní 3,8/10, týden předtím 1,7/10.</AlertBanner>
              <AlertBanner tone="info" icon={Flag} title="Zotavení po závodním úsilí · den 2 z 4" />
              <AlertBanner tone="info" icon={Bandage} title="Je to zranění?" action={<Button size="sm" variant="danger">Nahlásit zranění</Button>}>Bolest týden od týdne roste.</AlertBanner>
            </div>
          </Card>
          <Card>
            <span className="flex items-center gap-1.5"><Label>Factor bars · InfoDot</Label><InfoDot label="Celkový stav" text="Celkové skóre stavu (0–100) složené z mechaniky, zátěže a příznaků." /></span>
            <div className="mt-3 grid gap-3">
              <FactorBar grade="A" tone="alert" label="Bolest při běhu" value="8/10" pct={100} />
              <FactorBar grade="B" tone="watch" label="Objem nad kapacitou" value="×6,87" pct={86} />
              <FactorBar label="Skok v jednom běhu" value="×2,6" pts={24} pct={100} tone="alert" />
              <FactorBar label="Zvýšený klidový tep" value="57,7" pts={18} pct={75} tone="watch" />
            </div>
            <div className="mt-4 flex items-center gap-4"><Ring value={93} /><Ring value={33} /></div>
          </Card>
          <Card>
            <Label>Charts (scrub = hover / drag)</Label>
            <AxisLineChart points={pts} yMin={0} yMax={100} threshold={25} thresholdLabel="práh" color={C.load} height={140} />
            <Bars vals={weekly} />
            <div className="mt-4"><Sparkline vals={[42, 36, 38, 39, 39, 36, 37]} color={C.alert} /></div>
          </Card>
          <Card>
            <Label>Slider · empty · sheet</Label>
            <div className="mt-3 grid gap-3">
              <Slider name="pain" min={0} max={10} value={pain} onChange={setPain} tone="pain" />
              <Slider name="legs" min={1} max={5} value={legs} onChange={setLegs} />
              <Empty icon={FileText}>Zatím žádné zápisy.</Empty>
              <Button variant="outline" onClick={() => setSheet(true)}>Otevřít sheet</Button>
            </div>
          </Card>
        </div>
      </div>
      <Sheet open={sheet} onClose={() => setSheet(false)} footer={<div className="flex gap-2"><Button className="flex-1">Uložit změny</Button><Button variant="outline" onClick={() => setSheet(false)}>Zrušit</Button></div>}>
        <h2 className="font-serif text-2xl">Upravit zápis</h2>
        <p className="mt-1 text-xs text-fg-2">26. 9. · 5:47/km · silnice · 47 m sklesáno</p>
        <div className="mt-4"><Slider name="x" min={1} max={5} value={legs} onChange={setLegs} /></div>
      </Sheet>
    </div>
  )
}
