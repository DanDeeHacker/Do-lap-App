// v0.12.0 — the runner's profile: the gate asked before the getting-started checklist
// (and of every account that misses a required item), the full profile sheet, the
// shoe list (a photo recognised by the AI assistant, the first use by date or by a
// run) and, for women who want it, the menstrual cycle that refines readiness.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { Camera, Check, Footprints, Plus, Trash2 } from "lucide-react"
import { api } from "@/api"
import { useApp } from "@/store"
import { Field, Sheet, useAsync, useToast } from "@/ui"
import { fmtD } from "@/lib"
import { C } from "@/tokens"

const todayIso = () => new Date().toLocaleDateString("sv-SE")
const monthsAgo = (m: number) => { const d = new Date(); d.setMonth(d.getMonth() - m); return d.toLocaleDateString("sv-SE") }
const monthsSince = (iso: string) => (Date.now() - Date.parse(iso)) / (30.44 * 86400000)

export const EXPERIENCE = [
  { id: "new", label: "Začínám", sub: "méně než 3 měsíce", months: 1 },
  { id: "m6", label: "3–6 měsíců", sub: "", months: 4 },
  { id: "m12", label: "6–12 měsíců", sub: "", months: 9 },
  { id: "y3", label: "1–3 roky", sub: "", months: 24 },
  { id: "more", label: "Víc než 3 roky", sub: "", months: 60 },
] as const
export function expId(since?: string | null) {
  if (!since) return ""
  const m = monthsSince(since)
  return m < 3 ? "new" : m < 6 ? "m6" : m < 12 ? "m12" : m < 36 ? "y3" : "more"
}
function sinceFor(id: string, current?: string | null) {
  if (current && expId(current) === id) return current          // keep the stored date while the answer holds
  const o = EXPERIENCE.find((e) => e.id === id)
  return o ? monthsAgo(o.months) : null
}

const inp = "w-full rounded-xl border px-3 py-2.5 text-sm"
function Choice({ on, onClick, children, testid }: { on: boolean; onClick: () => void; children: ReactNode; testid?: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} data-testid={testid}
      className={`rounded-[12px] border px-3 py-2.5 text-left text-[13px] font-semibold leading-tight transition ${on ? "border-accent bg-accent/15 text-fg" : "border-white/[.1] bg-white/[.03] text-fg-2 hover:border-white/25"}`}>
      {children}
    </button>
  )
}
function Toggle({ on, label, onClick, testid }: { on: boolean; label: string; onClick: () => void; testid?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={onClick} data-testid={testid}
      className={`flex w-full items-center justify-between gap-3 rounded-[12px] border px-3 py-2.5 text-left text-[13px] transition ${on ? "border-accent/60 bg-accent/10 text-fg" : "border-white/10 text-fg-soft hover:border-white/20"}`}>
      <span>{label}</span>
      <span className={`relative h-6 w-10 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-white/15"}`}><i className={`absolute top-[3px] size-[18px] rounded-full transition-all ${on ? "left-[19px] bg-ink" : "left-[3px] bg-fg-2"}`} /></span>
    </button>
  )
}

// ---------------------------------------------------------------- the menstrual cycle
type Cycle = { track: boolean; hormonal: boolean; length: number; last: string }
function cycleFrom(mj: any): Cycle {
  const starts: string[] = mj?.starts || []
  return { track: !!mj?.track, hormonal: !!mj?.hormonal, length: mj?.length || 28, last: starts.length ? starts[starts.length - 1] : "" }
}
function cyclePatch(c: Cycle, mj: any) {
  const starts: string[] = [...(mj?.starts || [])]
  if (c.last && !starts.includes(c.last)) starts.push(c.last)
  return { track: c.track, hormonal: c.hormonal, length: Number(c.length) || 28, starts: starts.sort() }
}
function CycleFields({ c, set }: { c: Cycle; set: (c: Cycle) => void }) {
  return (
    <div className="mt-4" data-testid="cycle-fields">
      <Toggle on={c.track} onClick={() => set({ ...c, track: !c.track })} testid="cycle-toggle"
        label="Zpřesnit připravenost podle menstruačního cyklu (nepovinné)" />
      {c.track && (
        <div className="mt-2 rounded-[14px] bg-white/[.03] px-3 pb-3">
          <div className="grid gap-x-3 sm:grid-cols-2">
            <Field label="První den poslední menstruace"><input type="date" className={inp} max={todayIso()} value={c.last} onChange={(e) => set({ ...c, last: e.target.value })} /></Field>
            <Field label="Obvyklá délka cyklu (dny)"><input className={inp} inputMode="numeric" value={c.length} onChange={(e) => set({ ...c, length: Number(e.target.value.replace(/\D/g, "")) || 0 })} /></Field>
          </div>
          <div className="mt-3"><Toggle on={c.hormonal} onClick={() => set({ ...c, hormonal: !c.hormonal })} label="Užívám hormonální antikoncepci" /></div>
          <p className="mt-2 text-[11.5px] leading-[17px] text-fg-3">
            {c.hormonal
              ? "S hormonální antikoncepcí se cyklus na tepu a HRV projevuje málo, připravenost proto zůstává bez úprav."
              : "V druhé polovině cyklu bývá HRV nižší a klidový tep o pár úderů vyšší. Engine je pak porovná s vaší normou ze stejné fáze, aby to nevypadalo jako horší zotavení. Začátek další menstruace zapíšete v denním check-inu."}
          </p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- the profile gate
export function ProfileGate({ missing, onDone }: { missing: string[]; onDone: () => void }) {
  const { me, boot, refresh, logout } = useApp()
  const r = boot?.runner
  const [f, setF] = useState<Record<string, any>>({})
  const [injured, setInjured] = useState<"" | "yes" | "no">("")
  const [cyc, setCyc] = useState<Cycle>(cycleFrom(null))
  const { busy, err, run } = useAsync()
  useEffect(() => {
    if (!r) return
    setF({ birth_year: r.birth_year ?? "", sex: r.sex ?? "", exp: expId(r.running_since), weight_kg: r.weight_kg ?? "",
      prior_injury: r.prior_injury ?? "", prior_injury_date: (r.prior_injury_date ?? "").slice(0, 10), prior_injury_side: r.prior_injury_side ?? "",
      goal_race: r.goal_race ?? "", goal_date: (r.goal_date ?? "").slice(0, 10) })
    setInjured(r.prior_injury ? "yes" : "")
    setCyc(cycleFrom(r.menstrual_json))
  }, [r?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }))
  const year = Number(f.birth_year)
  const ok = f.sex && f.exp && year >= 1920 && year <= new Date().getFullYear() - 8
  const save = () => run(async () => {
    await api.updateProfile(me!.runner_id!, {
      birth_year: year, sex: f.sex, running_since: sinceFor(f.exp, r?.running_since),
      weight_kg: f.weight_kg ? f.weight_kg : null,
      ...(injured === "yes" ? { prior_injury: f.prior_injury || "běžecké zranění", prior_injury_date: f.prior_injury_date || null, prior_injury_side: f.prior_injury_side || null }
        : injured === "no" ? { prior_injury: null, prior_injury_date: null, prior_injury_side: null } : {}),
      ...(f.goal_race ? { goal_race: f.goal_race, goal_date: f.goal_date || null } : {}),
      ...(f.sex === "f" ? { menstrual_json: cyclePatch(cyc, r?.menstrual_json) } : {}),
    })
    await refresh()
    onDone()
  })
  const first = !r?.birth_year && !r?.sex
  return createPortal(
    <div className="fixed inset-0 z-[96] overflow-y-auto overscroll-contain bg-black/60 backdrop-blur-[2px]">
      <div className="flex min-h-full items-center justify-center p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
      <section role="dialog" aria-modal="true" aria-label="Váš profil" data-testid="profile-gate"
        className="my-4 w-full max-w-[520px] animate-[careReveal_.28s_ease-out] rounded-[24px] border border-white/10 bg-raised p-5 text-fg shadow-[0_24px_70px_rgb(0_0_0_/_0.55)]">
        <h2 className="text-[20px] font-extrabold tracking-[-.02em]">{first ? "Než začneme" : "Doplňte prosím profil"}</h2>
        <p className="mt-1 text-[13.5px] leading-5 text-fg-2">
          {first ? "Pár údajů, ze kterých engine od prvního dne nastaví bezpečné rezervy. Kdykoli je změníte v profilu."
            : `Engine nově potřebuje ${missing.includes("running_since") && missing.length === 1 ? "vědět, jak dlouho běháte" : "pár údajů navíc"}. Zabere to půl minuty.`}
        </p>
        <p className="mt-4 text-[13px] font-bold text-fg-soft">Pohlaví</p>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Choice on={f.sex === "f"} onClick={() => set("sex", "f")} testid="gate-sex-f">Žena</Choice>
          <Choice on={f.sex === "m"} onClick={() => set("sex", "m")} testid="gate-sex-m">Muž</Choice>
        </div>
        <div className="grid gap-x-3 sm:grid-cols-2">
          <Field label="Rok narození"><input className={inp} inputMode="numeric" value={f.birth_year ?? ""} placeholder="např. 1990" data-testid="gate-year" onChange={(e) => set("birth_year", e.target.value.replace(/\D/g, "").slice(0, 4))} /></Field>
          <Field label="Hmotnost (kg)" hint="nepovinné"><input className={inp} inputMode="decimal" value={f.weight_kg ?? ""} placeholder="např. 72" onChange={(e) => set("weight_kg", e.target.value.replace(/[^\d.,]/g, ""))} /></Field>
        </div>
        <p className="mt-4 text-[13px] font-bold text-fg-soft">Jak dlouho běháte pravidelně?</p>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {EXPERIENCE.map((o) => (
            <Choice key={o.id} on={f.exp === o.id} onClick={() => set("exp", o.id)} testid={`gate-exp-${o.id}`}>
              {o.label}{o.sub && <span className="block text-[11px] font-normal text-fg-3">{o.sub}</span>}
            </Choice>
          ))}
        </div>
        <p className="mt-1.5 text-[11.5px] leading-[17px] text-fg-3">V prvním roce pravidelného běhání se běžci zraňují zhruba dvakrát častěji, proto jim engine nechává menší rezervy nad zvládnutou zátěží.</p>
        <p className="mt-4 text-[13px] font-bold text-fg-soft">Běžecké zranění za posledních 12 měsíců?</p>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Choice on={injured === "no"} onClick={() => setInjured("no")} testid="gate-injury-no">Ne</Choice>
          <Choice on={injured === "yes"} onClick={() => setInjured("yes")} testid="gate-injury-yes">Ano</Choice>
        </div>
        {injured === "yes" && (
          <div className="grid gap-x-3 sm:grid-cols-3">
            <Field label="Co"><input className={inp} value={f.prior_injury ?? ""} placeholder="např. Achillova šlacha" onChange={(e) => set("prior_injury", e.target.value)} /></Field>
            <Field label="Kdy"><input type="date" className={inp} max={todayIso()} value={f.prior_injury_date ?? ""} onChange={(e) => set("prior_injury_date", e.target.value)} /></Field>
            <Field label="Strana"><select className={inp} value={f.prior_injury_side ?? ""} onChange={(e) => set("prior_injury_side", e.target.value)}><option value="">—</option><option value="left">levá</option><option value="right">pravá</option><option value="both">obě</option></select></Field>
          </div>
        )}
        <div className="grid gap-x-3 sm:grid-cols-2">
          <Field label="Cílový závod" hint="nepovinné"><input className={inp} value={f.goal_race ?? ""} placeholder="např. Pražský půlmaraton" onChange={(e) => set("goal_race", e.target.value)} /></Field>
          <Field label="Datum závodu"><input type="date" className={inp} value={f.goal_date ?? ""} onChange={(e) => set("goal_date", e.target.value)} /></Field>
        </div>
        {f.sex === "f" && <CycleFields c={cyc} set={setCyc} />}
        {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
        <button onClick={save} disabled={!ok || busy} data-testid="gate-save" className="btn btn-primary mt-5 w-full py-3 text-sm disabled:opacity-50">
          {busy ? "Ukládám…" : "Uložit a pokračovat"}
        </button>
        {!ok && <p className="mt-2 text-center text-[11.5px] text-fg-3">Povinné: pohlaví, rok narození a jak dlouho běháte.</p>}
        <p className="mt-3 text-center text-[11.5px] text-fg-3">Obuv přidáte později v profilu. <button type="button" onClick={() => logout()} className="underline hover:text-fg">Odhlásit se</button></p>
      </section>
      </div>
    </div>,
    document.body,
  )
}

// ---------------------------------------------------------------- the full profile sheet
export function ProfileSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me, boot, refresh } = useApp()
  const r = boot?.runner
  const [f, setF] = useState<Record<string, any>>({})
  const [cyc, setCyc] = useState<Cycle>(cycleFrom(null))
  const { busy, err, run } = useAsync()
  useEffect(() => {
    if (open && r) {
      setF({
        birth_year: r.birth_year ?? "", sex: r.sex ?? "", city: r.city ?? "", device: r.device ?? "",
        goal_race: r.goal_race ?? "", goal_date: (r.goal_date ?? "").slice(0, 10),
        prior_injury: r.prior_injury ?? "", prior_injury_date: (r.prior_injury_date ?? "").slice(0, 10),
        prior_injury_side: r.prior_injury_side ?? "", hr_max: r.hr_max ?? "", threshold_hr: r.threshold_hr ?? "",
        exp: expId(r.running_since), weight_kg: r.weight_kg ?? "",
      })
      setCyc(cycleFrom(r.menstrual_json))
    }
  }, [open, r])
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }))
  const save = () =>
    run(async () => {
      const { exp, ...rest } = f
      await api.updateProfile(me!.runner_id!, {
        ...rest,
        birth_year: f.birth_year ? Number(f.birth_year) : null,
        goal_date: f.goal_date || null,
        prior_injury: f.prior_injury || null,
        prior_injury_date: f.prior_injury_date || null,
        prior_injury_side: f.prior_injury_side || null,
        hr_max: f.hr_max ? Number(f.hr_max) : null,
        threshold_hr: f.threshold_hr ? Number(f.threshold_hr) : null,
        running_since: exp ? sinceFor(exp, r?.running_since) : r?.running_since ?? null,
        weight_kg: f.weight_kg ? f.weight_kg : null,
        ...(f.sex === "f" ? { menstrual_json: cyclePatch(cyc, r?.menstrual_json) } : {}),
      })
      await refresh()
      onClose()
    })
  return (
    <Sheet open={open} onClose={onClose}>
      <h2 className="font-serif text-2xl">Upravit profil</h2>
      <p className="mt-1 text-xs text-fg-2">Údaje, které používá engine (zkušenost, dřívější zranění, obuv, cílový závod) a fyzioterapeut (věk, pohlaví, město).</p>
      <div className="grid gap-1 md:grid-cols-2">
        <Field label="Rok narození"><input className={inp} inputMode="numeric" value={f.birth_year ?? ""} onChange={(e) => set("birth_year", e.target.value)} /></Field>
        <Field label="Pohlaví"><select className={inp} value={f.sex ?? ""} onChange={(e) => set("sex", e.target.value)}><option value="">—</option><option value="f">žena</option><option value="m">muž</option></select></Field>
        <Field label="Jak dlouho běháte pravidelně"><select className={inp} value={f.exp ?? ""} data-testid="profile-exp" onChange={(e) => set("exp", e.target.value)}><option value="">—</option>{EXPERIENCE.map((o) => <option key={o.id} value={o.id}>{o.label}{o.sub ? ` (${o.sub})` : ""}</option>)}</select></Field>
        <Field label="Hmotnost (kg)"><input className={inp} inputMode="decimal" value={f.weight_kg ?? ""} onChange={(e) => set("weight_kg", e.target.value.replace(/[^\d.,]/g, ""))} /></Field>
        <Field label="Město"><input className={inp} value={f.city ?? ""} onChange={(e) => set("city", e.target.value)} /></Field>
        <Field label="Hodinky / zařízení"><input className={inp} value={f.device ?? ""} onChange={(e) => set("device", e.target.value)} /></Field>
        <Field label="Cílový závod"><input className={inp} value={f.goal_race ?? ""} onChange={(e) => set("goal_race", e.target.value)} placeholder="např. Pražský půlmaraton" /></Field>
        <Field label="Datum závodu" hint="další závody přidáte v Tréninku → Závody"><input type="date" className={inp} value={f.goal_date ?? ""} onChange={(e) => set("goal_date", e.target.value)} /></Field>
        <Field label="Dřívější zranění"><input className={inp} value={f.prior_injury ?? ""} onChange={(e) => set("prior_injury", e.target.value)} placeholder="např. Achillova šlacha" /></Field>
        <Field label="Kdy se zranění stalo" hint={f.prior_injury && !f.prior_injury_date ? "bez data ho engine počítá jako nedávné" : undefined}><input type="date" className={inp} value={f.prior_injury_date ?? ""} max={todayIso()} onChange={(e) => set("prior_injury_date", e.target.value)} /></Field>
        <Field label="Maximální tep (změřený)" hint={f.hr_max ? "tepové zóny se počítají z něj" : "z testu nebo závodu do vrchu; bez něj zóny odhadujeme"}><input className={inp} inputMode="numeric" value={f.hr_max ?? ""} placeholder="např. 192" onChange={(e) => set("hr_max", e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="Tep na prahu (LTHR)" hint={f.threshold_hr ? "zóny a tvrdé minuty se počítají z prahu" : "z laktátového nebo terénního testu (průměr posledních 20 min 30min testu); nepovinné"}><input className={inp} inputMode="numeric" value={f.threshold_hr ?? ""} placeholder="např. 172" onChange={(e) => set("threshold_hr", e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="Strana"><select className={inp} value={f.prior_injury_side ?? ""} onChange={(e) => set("prior_injury_side", e.target.value)}><option value="">—</option><option value="left">levá</option><option value="right">pravá</option><option value="both">obě</option></select></Field>
      </div>
      {f.sex === "f" && <CycleFields c={cyc} set={setCyc} />}
      {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
      <div className="mt-5 flex gap-2">
        <button onClick={save} disabled={busy} className="btn btn-primary flex-1 py-3 text-sm">{busy ? "Ukládám…" : "Uložit profil"}</button>
        <button onClick={onClose} className="btn btn-outline px-5 py-3 text-sm">Zavřít</button>
      </div>
      {open && me?.runner_id && <Shoes rid={me.runner_id} />}
    </Sheet>
  )
}

// ---------------------------------------------------------------- shoes
const CATEGORY: [string, string][] = [["daily", "každodenní"], ["cushioned", "s vysokým tlumením"], ["stability", "stabilní"],
  ["racing", "závodní"], ["minimal", "minimalistická"], ["trail", "trailová"], ["track", "tretry / dráha"]]
type ShoeForm = { brand: string; model: string; category: string; drop_mm: string; carbon: boolean; mode: "date" | "run"; first_used: string; first_activity_id: string; source: string; confidence?: number | null }
const EMPTY: ShoeForm = { brand: "", model: "", category: "", drop_mm: "", carbon: false, mode: "date", first_used: todayIso(), first_activity_id: "", source: "manual" }

async function photoData(file: File, max = 1280): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url })
    const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight))
    const c = document.createElement("canvas")
    c.width = Math.round(img.naturalWidth * k)
    c.height = Math.round(img.naturalHeight * k)
    c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height)
    return c.toDataURL("image/jpeg", 0.85)
  } finally {
    URL.revokeObjectURL(url)
  }
}

// ---------------------------------------------------------------- shoe catalog (brands and model lines)
type CatModel = { name: string; category: string; carbon: boolean; drop: number | null }
type CatBrand = { name: string; models: CatModel[] }
let catalogCache: Promise<CatBrand[]> | null = null
function useShoeCatalog(): CatBrand[] {
  const [c, setC] = useState<CatBrand[]>([])
  useEffect(() => {
    if (!catalogCache) catalogCache = api.shoeCatalog().then((r: any) => r?.brands || []).catch(() => { catalogCache = null; return [] })
    catalogCache.then(setC)
  }, [])
  return c
}
const norm = (x: string) => x.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim()
/** the catalog line a typed model starts with (whole words, the longest wins) */
function lineOf(brand: CatBrand | undefined, model: string): CatModel | undefined {
  const m = norm(model)
  return brand?.models.filter((x) => m === norm(x.name) || m.startsWith(norm(x.name) + " ")).sort((a, b) => b.name.length - a.name.length)[0]
}

type Opt = { key: string; label: string; sub?: string; pick: () => void }
/** A text field with a list of suggestions under it; anything can still be typed. */
function Suggest({ value, onChange, options, placeholder, testid }: { value: string; onChange: (v: string) => void; options: Opt[]; placeholder?: string; testid?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <input className={inp} value={value} placeholder={placeholder} data-testid={testid} autoComplete="off"
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => { onChange(e.target.value); setOpen(true) }} />
      {open && options.length > 0 && (
        <ul role="listbox" data-testid={testid ? `${testid}-list` : undefined}
          className="absolute inset-x-0 top-full z-30 mt-1 max-h-60 overflow-y-auto rounded-xl border border-white/12 bg-raised py-1 shadow-[0_16px_40px_rgb(0_0_0_/_0.5)]">
          {options.slice(0, 80).map((o) => (
            <li key={o.key}>
              <button type="button" role="option" aria-selected={false} onMouseDown={(e) => e.preventDefault()} onClick={() => { o.pick(); setOpen(false) }}
                className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left text-[13px] text-fg hover:bg-white/[.06]">
                <span>{o.label}</span>{o.sub && <span className="shrink-0 text-[11px] text-fg-3">{o.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const RECOG_ERR: Record<string, string> = {
  unavailable: "Rozpoznávání fotek teď není dostupné. Zadejte botu ručně.",
  failed: "Fotku se nepodařilo rozpoznat. Zkuste jinou (bota z boku, čitelný nápis), nebo ji zadejte ručně.",
  no_shoe: "Na fotce jsme botu nenašli. Zkuste ji vyfotit z boku.",
  unknown: "Model se z fotky nepodařilo přečíst. Doplňte ho prosím ručně.",
}

export function Shoes({ rid }: { rid: string }) {
  const { boot, refresh } = useApp()
  const toast = useToast()
  const [data, setData] = useState<any>(null)
  const [form, setForm] = useState<ShoeForm | null>(null)
  const [recog, setRecog] = useState<"" | "busy" | string>("")
  const fileRef = useRef<HTMLInputElement | null>(null)
  const { busy, err, run, setErr } = useAsync()
  useEffect(() => { api.shoes(rid).then(setData).catch(() => {}) }, [rid])
  const runs = useMemo(() => ((boot?.activities || []) as any[])
    .filter((a) => (!a.sport || a.sport === "running") && !(a.excluded && a.excluded_scope !== "mech"))
    .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at))).slice(0, 80), [boot?.activities])
  const after = async (out: any) => { setData(out); await refresh() }
  const onPhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    setErr(null)
    setRecog("busy")
    setForm({ ...EMPTY, source: "photo" })
    try {
      const img = await photoData(file)
      const res: any = await api.recognizeShoe(rid, img)
      const s = res?.suggestion
      if (s) setForm((p) => ({ ...(p || EMPTY), brand: s.brand || "", model: s.model || "", category: s.category || "", drop_mm: s.drop_mm != null ? String(s.drop_mm) : "", carbon: !!s.carbon, source: "photo", confidence: s.confidence }))
      setRecog(res?.ok ? "" : res?.error || "failed")
    } catch (x: any) {
      setRecog(x?.message || "failed")
    }
  }
  const save = () => form && run(async () => {
    const body: any = { brand: form.brand, model: form.model, category: form.category || null, drop_mm: form.drop_mm === "" ? null : Number(form.drop_mm.replace(",", ".")),
      carbon: form.carbon, source: form.source }
    if (form.mode === "run" && form.first_activity_id) body.first_activity_id = Number(form.first_activity_id)
    else body.first_used = form.first_used
    await after(await api.addShoe(rid, body))
    setForm(null)
    setRecog("")
    toast({ title: "Bota uložena" })
  })
  const shoes: any[] = data?.shoes || []
  const set = (k: keyof ShoeForm, v: any) => setForm((p) => (p ? { ...p, [k]: v } : p))
  // brands and model lines (shoe_catalog.py): pick one, the version number is typed after it
  const catalog = useShoeCatalog()
  const catBrand = form ? catalog.find((b) => norm(b.name) === norm(form.brand)) : undefined
  const catLine = form ? lineOf(catBrand, form.model) : undefined
  const pickLine = (b: CatBrand, m: CatModel) => setForm((p) => p && ({
    ...p, brand: b.name, model: `${m.name} `, category: m.category, carbon: m.carbon,
    drop_mm: m.drop != null ? String(m.drop) : (p.brand === b.name && lineOf(b, p.model)?.name === m.name ? p.drop_mm : ""),
  }))
  const brandOpts: Opt[] = form ? catalog.filter((b) => !form.brand || norm(b.name).includes(norm(form.brand)))
    .filter((b) => norm(b.name) !== norm(form.brand))
    .map((b) => ({ key: b.name, label: b.name, sub: b.models.length ? `${b.models.length} řad` : undefined, pick: () => set("brand", b.name) })) : []
  const q = form ? norm(form.model) : ""
  const modelOpts: Opt[] = !form ? [] : (catBrand ? [catBrand] : catalog)
    .flatMap((b) => b.models.map((m) => ({ b, m })))
    .filter(({ b, m }) => !q || norm(m.name).includes(q) || norm(`${b.name} ${m.name}`).includes(q))
    .filter(({ m }) => !catLine || norm(m.name) !== norm(catLine.name))
    .map(({ b, m }) => ({ key: `${b.name}|${m.name}`, label: catBrand ? m.name : `${b.name} ${m.name}`,
      sub: CATEGORY.find(([k]) => k === m.category)?.[1], pick: () => pickLine(b, m) }))
  return (
    <section className="mt-7 border-t border-white/[.08] pt-5" data-testid="shoes">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-serif text-xl"><Footprints className="size-5 text-fg-2" aria-hidden />Obuv</h3>
        {!form && (
          <div className="flex gap-1.5">
            <button type="button" onClick={() => fileRef.current?.click()} data-testid="shoe-photo" className="btn btn-primary btn-sm gap-1.5"><Camera className="size-4" aria-hidden />Vyfotit botu</button>
            <button type="button" onClick={() => setForm({ ...EMPTY })} data-testid="shoe-manual" className="btn btn-outline btn-sm gap-1.5"><Plus className="size-4" aria-hidden />Ručně</button>
          </div>
        )}
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPhoto} data-testid="shoe-file" />
      </div>
      <p className="mt-1 text-[11.5px] leading-[17px] text-fg-3">Fotku bot rozpozná AI asistent a zapíše model jednotně. Fotka se neukládá. Vy doplníte, odkdy v botách běháte.</p>
      {data?.rotation && (
        <p className="mt-3 rounded-[10px] px-2.5 py-2 text-[12px] leading-[17px]" style={{ background: `${C.ok}14`, color: C.ok }} data-testid="shoe-rotation">
          Střídáte {data.rotation.n} páry bot. Běžci, kteří střídají víc párů, se zraňovali méně (Malisoux et al., 2015).
        </p>
      )}
      {form && (
        <div className="nest mt-3 p-3.5" data-testid="shoe-form">
          {recog === "busy" && <p className="text-[12.5px] text-fg-2" role="status">Rozpoznávám botu na fotce…</p>}
          {recog && recog !== "busy" && <p className="text-[12px] leading-[17px] text-watch">{RECOG_ERR[recog] || recog}</p>}
          {form.source === "photo" && recog === "" && form.brand && (
            <p className="text-[12px] leading-[17px] text-fg-2">Rozpoznáno z fotky{form.confidence != null ? ` (jistota ${Math.round(form.confidence * 100)} %)` : ""}. Zkontrolujte údaje.</p>
          )}
          <div className="grid gap-x-3 sm:grid-cols-2">
            <Field label="Značka"><Suggest value={form.brand} placeholder="vyberte nebo napište, např. HOKA" testid="shoe-brand" options={brandOpts} onChange={(v) => set("brand", v)} /></Field>
            <Field label="Model" hint={catLine && !/\d/.test(form.model) ? "doplňte číslo verze" : undefined}><Suggest value={form.model} placeholder={catBrand?.models[0] ? `např. ${catBrand.models[0].name} …` : "např. Clifton 10"} testid="shoe-model" options={modelOpts} onChange={(v) => set("model", v)} /></Field>
            <Field label="Typ"><select className={inp} value={form.category} onChange={(e) => set("category", e.target.value)}><option value="">—</option>{CATEGORY.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Drop (mm)" hint="rozdíl pata–špička"><input className={inp} inputMode="decimal" value={form.drop_mm} placeholder="např. 8" onChange={(e) => set("drop_mm", e.target.value.replace(/[^\d.,]/g, ""))} /></Field>
          </div>
          {catLine && catLine.drop == null && form.drop_mm === "" && (
            <p className="mt-2 text-[11.5px] leading-[17px] text-fg-3" data-testid="shoe-drop-hint">Drop se u řady {catLine.name} mezi verzemi mění. Najdete ho na krabici, na jazyku boty nebo na webu výrobce; bez něj engine pozná přechod jen podle typu boty.</p>
          )}
          <div className="mt-3"><Toggle on={form.carbon} onClick={() => set("carbon", !form.carbon)} label="Karbonová deska" /></div>
          <p className="mt-4 text-[13px] font-bold text-fg-soft">První použití</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Choice on={form.mode === "date"} onClick={() => set("mode", "date")}>Datum</Choice>
            <Choice on={form.mode === "run"} onClick={() => set("mode", "run")} testid="shoe-mode-run">Vybrat běh</Choice>
          </div>
          {form.mode === "date" ? (
            <Field label="Od kdy v nich běháte"><input type="date" className={inp} max={todayIso()} value={form.first_used} onChange={(e) => set("first_used", e.target.value)} /></Field>
          ) : (
            <Field label="První běh v nich" hint="už nahrané běhy"><select className={inp} value={form.first_activity_id} data-testid="shoe-run" onChange={(e) => set("first_activity_id", e.target.value)}>
              <option value="">—</option>
              {runs.map((a) => <option key={a.id} value={a.id}>{fmtD(String(a.started_at).slice(0, 10))} · {a.distance_km != null ? `${String(Math.round(a.distance_km * 10) / 10).replace(".", ",")} km` : ""} · {a.title || "Běh"}</option>)}
            </select></Field>
          )}
          {err && <p className="mt-3 text-xs font-bold text-alert">{err}</p>}
          <div className="mt-4 flex gap-2">
            <button onClick={save} disabled={busy || recog === "busy" || !form.brand || !form.model || (form.mode === "run" ? !form.first_activity_id : !form.first_used)}
              data-testid="shoe-save" className="btn btn-primary flex-1 py-2.5 text-sm disabled:opacity-50">{busy ? "Ukládám…" : "Uložit botu"}</button>
            <button onClick={() => { setForm(null); setRecog("") }} className="btn btn-outline px-4 py-2.5 text-sm">Zrušit</button>
          </div>
        </div>
      )}
      {shoes.length ? (
        <ul className="mt-3 grid gap-2" data-testid="shoe-list">
          {[...shoes].sort((a, b) => Number(!!a.retired_at) - Number(!!b.retired_at) || String(b.first_used).localeCompare(String(a.first_used))).map((s) => (
            <li key={s.id} className={`nest flex items-start gap-3 p-3 ${s.retired_at ? "opacity-60" : ""}`}>
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-white/[.06] text-fg-2"><Footprints className="size-4" aria-hidden /></span>
              <div className="min-w-0 flex-1">
                <b className="block text-[14px] text-fg">{s.brand} {s.model}</b>
                <span className="block text-[11.5px] leading-[17px] text-fg-3">
                  {[s.categoryLabel, s.drop_mm != null ? `drop ${String(s.drop_mm).replace(".", ",")} mm` : null, s.carbon ? "karbon" : null].filter(Boolean).join(" · ")}
                </span>
                <span className="block text-[11.5px] leading-[17px] text-fg-2">
                  {s.retired_at ? `vyřazeno ${fmtD(s.retired_at)}` : `od ${fmtD(s.first_used)}`}
                  {s.kmSince != null && !s.retired_at ? ` · ${data?.kmShared ? "nejvýš " : ""}${String(s.kmSince).replace(".", ",")} km` : ""}
                </span>
                {s.transition && (
                  <span className="mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ background: `${C.watch}1f`, color: C.watch }} data-testid="shoe-transition">
                    přechod do {fmtD(s.transition.until)}: užší rezervy na běh
                  </span>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button type="button" onClick={() => run(async () => after(await api.updateShoe(rid, s.id, { retired: !s.retired_at })))} className="rounded-full border border-white/12 px-2.5 py-1 text-[11px] font-bold text-fg-2 hover:text-fg" title={s.retired_at ? "Vrátit do používání" : "Vyřadit"}>
                  {s.retired_at ? <Check className="size-3.5" aria-label="Vrátit do používání" /> : "Vyřadit"}
                </button>
                <button type="button" onClick={() => { if (confirm(`Smazat ${s.brand} ${s.model}?`)) run(async () => after(await api.deleteShoe(rid, s.id))) }} className="grid size-7 place-items-center rounded-full border border-white/12 text-fg-3 hover:text-alert" aria-label="Smazat"><Trash2 className="size-3.5" aria-hidden /></button>
              </div>
            </li>
          ))}
        </ul>
      ) : !form ? <p className="mt-3 text-[12.5px] text-fg-2">Zatím žádná obuv. Přidejte boty, ve kterých běháte.</p> : null}
      {data?.transition && (
        <p className="mt-3 text-[11.5px] leading-[17px] text-fg-3">
          {data.transition.kind === "carbon"
            ? "Závodní bota s karbonovou deskou mění zatížení chodidla. Prvních 6 týdnů v ní běhejte hlavně kratší a rychlejší běhy."
            : "Nižší drop nebo minimalistická bota víc zatíží lýtka, Achillovy šlachy a chodidla. Prvních 6 týdnů je střídejte s dosavadní obuví a začněte kratšími běhy (Fuller et al., 2017)."}
        </p>
      )}
    </section>
  )
}
