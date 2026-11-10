// Profil fyzioterapeuta (round 2 F15, completes W14): the public card runners choose from — photo, the display
// name without the title (the title comes from Praxe), specialties from the region list plus free text, bio,
// services and prices from Kalendář → Služby, the usual reply time, the verification status and a live preview
// of the card. Also how texts about the physio read (grammatical gender) and the clinic whose city sets the
// region of the case queue (owner request 2026-10-27).
import { useEffect, useState } from "react"
import { Link } from "react-router"
import { Star } from "lucide-react"
import { api } from "@/api"
import { Button, Card, Chip, Field, useToast } from "@/ui"
import { czk, fmtDY, initials } from "@/lib"
import { Loading, REGIONS } from "@/physio/common"

const TITLES = /^(prof\.|doc\.|mgr\.|bc\.|mudr\.|phdr\.|paeddr\.|ing\.|ph\.d\.|dis\.)\s*/i

// the browser shrinks the photo to 256 px before it is sent (a data URL, a few tens of kB)
async function shrink(file: File): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url })
    const k = Math.min(1, 256 / Math.max(img.width, img.height))
    const c = document.createElement("canvas")
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k)
    c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height)
    return c.toDataURL("image/jpeg", 0.85)
  } finally { URL.revokeObjectURL(url) }
}

export function ProfilePage({ onSaved }: { onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [splitSeen, setSplitSeen] = useState(() => { try { return localStorage.getItem("doslap:title-split") === "1" } catch { return false } })
  useEffect(() => {
    api.physioMe().then((p: any) => {
      const regs = REGIONS.map(([, t]) => t)
      setF({ ...p, specRegions: (p.specialties || []).filter((x: string) => regs.includes(x)),
        specialtiesText: (p.specialties || []).filter((x: string) => !regs.includes(x)).join(", "),
        clinic_name: p.clinic?.name || "", clinic_city: p.clinic?.city || "", grammatical_gender: p.grammatical_gender || "" })
    }).catch((e: any) => setErr(e?.message || "Nepodařilo se načíst"))
  }, [])
  if (!f) return <Loading err={err} />
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const specialties = [...f.specRegions, ...String(f.specialtiesText || "").split(",").map((s: string) => s.trim()).filter(Boolean)]
  const save = async () => {
    setBusy(true)
    try {
      const p = await api.physioUpdate({
        name: f.name, bio: f.bio || "", years_exp: f.years_exp === "" || f.years_exp == null ? undefined : Number(f.years_exp),
        ...(f.services?.length ? {} : { price_czk: f.price_czk === "" || f.price_czk == null ? undefined : Number(f.price_czk) }),
        specialties, clinic_name: f.clinic_name || undefined, clinic_city: f.clinic_city || undefined,
        grammatical_gender: f.grammatical_gender, ...(f.photoChanged ? { photo: f.photo_url || "" } : {}),
      })
      setF({ ...f, ...p, photoChanged: false })
      toast({ title: "Profil uložen" })
      onSaved()
    } catch (e: any) { toast({ title: e?.message || "Nepodařilo se" }) }
    finally { setBusy(false) }
  }
  const inp = "w-full rounded-xl border border-white/10 bg-panel px-3 py-2.5 text-[14px]"
  const titleInName = TITLES.test(f.name || "")
  const lowest = (f.services || []).filter((s: any) => s.price_czk != null).map((s: any) => s.price_czk)
  return (
    <>
      <p className="t-label">Profil</p>
      <h1 className="mt-1 font-serif text-[30px] leading-tight tracking-[-.03em] md:text-4xl">Váš profil</h1>
      <p className="mt-2 max-w-[640px] text-[13px] leading-5 text-fg-2">
        Tak vás uvidí běžci, když si v záložce Péče vybírají fyzioterapeuta. Podle města praxe se řadí fronta případů.
      </p>
      {/* F15.3: never split automatically — ask once */}
      {titleInName && !splitSeen && (
        <p className="mt-4 flex max-w-[760px] flex-wrap items-center gap-2 rounded-xl bg-watch/10 px-4 py-3 text-[13px]" data-testid="title-split">
          <span className="flex-1">Ve jméně máte titul. Napište jméno bez titulu a titul doplňte v Praxi — na kartě se zobrazí obojí.</span>
          <Link to="/physio/practice" className="font-bold text-accent underline">Praxe</Link>
          <button type="button" className="font-bold text-fg-3 underline" onClick={() => { setSplitSeen(true); try { localStorage.setItem("doslap:title-split", "1") } catch { /* ignore */ } }}>Rozumím</button>
        </p>
      )}
      <div className="mt-5 grid max-w-[1100px] gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <div className="grid gap-4 sm:grid-cols-2" data-testid="physio-profile">
            <div className="flex items-center gap-3 sm:col-span-2">
              {f.photo_url ? <img src={f.photo_url} alt="" className="size-16 rounded-full object-cover" /> : <span className="grid size-16 place-items-center rounded-full bg-accent/15 font-extrabold text-accent">{initials(f.name || "")}</span>}
              <label className="btn btn-outline btn-sm cursor-pointer">Nahrát fotku
                <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={async (e) => {
                  const file = e.target.files?.[0]; if (!file) return
                  try { setF({ ...f, photo_url: await shrink(file), photoChanged: true }) } catch { toast({ title: "Fotku nejde načíst" }) }
                }} /></label>
              {f.photo_url && <button type="button" className="text-[12px] font-bold text-fg-3 underline" onClick={() => setF({ ...f, photo_url: null, photoChanged: true })}>Odebrat</button>}
            </div>
            <Field label="Jméno (bez titulu)"><input className={inp} value={f.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Titul" hint="upravíte v Praxi"><input className={inp} value={f.title || "—"} readOnly aria-readonly /></Field>
            <Field label="V textech o mně psát">
              <select className={inp} value={f.grammatical_gender} onChange={(e) => set("grammatical_gender", e.target.value)} data-testid="gender">
                <option value="">neutrálně</option><option value="f">udělala</option><option value="m">udělal</option></select></Field>
            <Field label="Let praxe"><input className={inp} inputMode="numeric" value={f.years_exp ?? ""} onChange={(e) => set("years_exp", e.target.value.replace(/\D/g, ""))} /></Field>
            <div className="sm:col-span-2"><Field label="Zaměření">
              <div className="flex flex-wrap gap-1.5">{REGIONS.filter(([k]) => k !== "other").map(([k, t]) => {
                const on = f.specRegions.includes(t)
                return <button key={k} type="button" aria-pressed={on} onClick={() => set("specRegions", on ? f.specRegions.filter((x: string) => x !== t) : [...f.specRegions, t])}
                  className={`rounded-full border px-2.5 py-1 text-[12px] ${on ? "border-accent bg-accent/12 text-accent" : "border-white/15 text-fg-2"}`}>{t}</button>
              })}</div>
              <input className={`${inp} mt-2`} value={f.specialtiesText} onChange={(e) => set("specialtiesText", e.target.value)} placeholder="další, oddělte čárkou (např. návrat po zranění)" /></Field></div>
            <div className="sm:col-span-2"><Field label="Krátce o vás">
              <textarea className={inp} rows={4} maxLength={800} value={f.bio || ""} onChange={(e) => set("bio", e.target.value)} /></Field></div>
            <Field label="Název praxe"><input className={inp} value={f.clinic_name} onChange={(e) => set("clinic_name", e.target.value)} /></Field>
            <Field label="Město praxe" hint="určuje region fronty případů"><input className={inp} value={f.clinic_city} onChange={(e) => set("clinic_city", e.target.value)} placeholder="např. Praha 7" /></Field>
            {!(f.services || []).length && <Field label="Orientační cena za návštěvu (Kč)" hint="jen dokud nemáte služby"><input className={inp} inputMode="numeric" value={f.price_czk ?? ""} onChange={(e) => set("price_czk", e.target.value.replace(/\D/g, ""))} /></Field>}
          </div>
          <div className="mt-4 border-t border-white/[.08] pt-3 text-[13px]">
            <p className="font-bold">Služby a ceny</p>
            {(f.services || []).length === 0 ? <p className="mt-1 text-fg-3">Zatím žádné.</p> : (
              <ul className="mt-1 grid gap-0.5 text-fg-2">{f.services.map((s: any) => <li key={s.id}>{`${s.name} · ${s.duration_minutes} min${s.price_czk != null ? ` · ${czk(s.price_czk)}` : ""}`}</li>)}</ul>)}
            <Link to="/physio/calendar#services" className="mt-1 inline-block text-[12px] font-bold text-accent hover:underline">Upravit v Kalendáři → Služby</Link>
            <p className="mt-2"><span className="text-fg-3">{"Obvykle odpovídám: "}</span>{f.response_time_text || "neuvedeno"}{" "}<Link to="/physio/practice" className="text-[12px] font-bold text-accent hover:underline">upravit</Link></p>
            <p className="mt-1" data-testid="verification">{f.verified_at ? <Chip tone="ok">{`Ověřeno ${fmtDY(f.verified_at)}`}</Chip> : <Chip tone="watch">Čeká na ověření</Chip>}</p>
          </div>
          <p className="mt-3 text-[12px] text-fg-3">{`Přihlášení: ${f.email}`}</p>
          <Button className="mt-4" busy={busy} onClick={save}>Uložit profil</Button>
        </Card>
        <div>
          <p className="t-label mb-2">Tak vás uvidí běžci</p>
          {/* F15.1: the live preview, built like the card in Péče → Najít termín */}
          <div className="nest p-4" data-testid="profile-preview">
            <div className="flex items-start gap-3">
              {f.photo_url ? <img src={f.photo_url} alt="" className="size-10 shrink-0 rounded-full object-cover" /> : <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent/15 text-xs font-extrabold text-accent">{initials(f.name || "")}</span>}
              <div className="min-w-0 flex-1"><b className="font-bold">{[f.title, f.name].filter(Boolean).join(" ")}</b>
                <p className="text-[12px] text-fg-3">{f.clinic_name || ""}{f.clinic_city ? ` · ${f.clinic_city}` : ""} · {f.years_exp || "—"} let · <Star className="inline size-3 -translate-y-px fill-watch text-watch" aria-hidden /> {f.rating_count >= 5 ? f.rating : "—"}</p></div>
              {lowest.length ? <Chip tone="accent">{`od ${czk(Math.min(...lowest))}`}</Chip> : f.price_czk ? <Chip tone="accent">{czk(Number(f.price_czk))}</Chip> : null}
            </div>
            {specialties.length > 0 && <p className="mt-2 flex flex-wrap gap-1">{specialties.map((x: string) => <Chip key={x}>{x}</Chip>)}</p>}
            {f.bio && <p className="mt-2 text-[13px] leading-5 text-fg-2">{f.bio}</p>}
            {f.response_time_text && <p className="mt-1 text-[12px] text-fg-3">{`Obvykle odpovídá ${f.response_time_text}`}</p>}
          </div>
        </div>
      </div>
    </>
  )
}
