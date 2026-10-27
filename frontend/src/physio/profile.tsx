// Profil fyzioterapeuta: the card runners choose from in their Care tab, and the clinic whose city
// sets the region of the case queue (owner request 2026-10-27).
import { useEffect, useState } from "react"
import { api } from "@/api"
import { Button, Card, Field, useToast } from "@/ui"
import { Loading } from "@/physio/common"

export function ProfilePage({ onSaved }: { onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.physioMe().then((p: any) => setF({ ...p, specialtiesText: (p.specialties || []).join(", "), clinic_name: p.clinic?.name || "", clinic_city: p.clinic?.city || "" }))
      .catch((e: any) => setErr(e?.message || "Nepodařilo se načíst"))
  }, [])
  if (!f) return <Loading err={err} />
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const save = async () => {
    setBusy(true)
    try {
      const p = await api.physioUpdate({
        name: f.name, credential: f.credential || "", bio: f.bio || "", years_exp: f.years_exp === "" || f.years_exp == null ? undefined : Number(f.years_exp),
        price_czk: f.price_czk === "" || f.price_czk == null ? undefined : Number(f.price_czk),
        specialties: String(f.specialtiesText || "").split(",").map((s) => s.trim()).filter(Boolean),
        clinic_name: f.clinic_name || undefined, clinic_city: f.clinic_city || undefined,
      })
      setF({ ...f, ...p })
      toast({ title: "Profil uložen" })
      onSaved()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  const inp = "w-full rounded-xl border border-white/10 bg-panel px-3 py-2.5 text-[14px]"
  return (
    <>
      <p className="t-label">Profil</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Váš profil a praxe</h1>
      <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">
        Tak vás uvidí běžci, když si v záložce Péče vybírají fyzioterapeuta. Podle města praxe se řadí fronta případů.
      </p>
      <Card className="mt-5 max-w-[760px]">
        <div className="grid gap-4 sm:grid-cols-2" data-testid="physio-profile">
          <Field label="Jméno"><input className={inp} value={f.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Titul a odbornost" hint="např. Mgr., fyzioterapeut"><input className={inp} value={f.credential || ""} onChange={(e) => set("credential", e.target.value)} /></Field>
          <Field label="Název praxe"><input className={inp} value={f.clinic_name} onChange={(e) => set("clinic_name", e.target.value)} /></Field>
          <Field label="Město praxe" hint="určuje region fronty případů"><input className={inp} value={f.clinic_city} onChange={(e) => set("clinic_city", e.target.value)} placeholder="např. Praha 7" /></Field>
          <Field label="Let praxe"><input className={inp} inputMode="numeric" value={f.years_exp ?? ""} onChange={(e) => set("years_exp", e.target.value.replace(/\D/g, ""))} /></Field>
          <Field label="Orientační cena za návštěvu (Kč)"><input className={inp} inputMode="numeric" value={f.price_czk ?? ""} onChange={(e) => set("price_czk", e.target.value.replace(/\D/g, ""))} /></Field>
          <div className="sm:col-span-2"><Field label="Zaměření" hint="oddělte čárkou, např. Achillova šlacha, koleno, návrat po zranění">
            <input className={inp} value={f.specialtiesText} onChange={(e) => set("specialtiesText", e.target.value)} /></Field></div>
          <div className="sm:col-span-2"><Field label="Krátce o vás">
            <textarea className={inp} rows={4} maxLength={800} value={f.bio || ""} onChange={(e) => set("bio", e.target.value)} /></Field></div>
        </div>
        <p className="mt-3 text-[12px] text-fg-3">{`Přihlášení: ${f.email}`}</p>
        <Button className="mt-4" busy={busy} onClick={save}>Uložit profil</Button>
      </Card>
    </>
  )
}
