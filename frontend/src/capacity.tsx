// Engine v3 ("Kapacitní") views of the per-runner capacity model: the full panel
// on the Zátěž tab and a compact weekly strip on Dnes (below the quadrant, which
// stays the first thing on the page).
import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { InfoDot, Label } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { fmtD, fmtImpact, toImpact } from "@/lib"
import { C, goodCol } from "@/tokens"
import { Waterfall, type WStep } from "@/waterfall"
import { BodyLoadMap } from "@/components/MuscleAnatomy"
import { useApp } from "@/store"

const CH_ORDER = ["volume", "intensity", "descent", "ascent", "systemic", "strength"] as const
const RUN_CH = ["volume", "intensity", "descent", "ascent"] as const
const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("cs-CZ"))
const TONE = { ok: C.ok, watch: C.watch, alert: C.alert, muted: C.fg3 }
const toneOf = (ratio: number | null | undefined, margin: number) =>
  ratio == null ? "muted" : ratio <= 1 + margin ? "ok" : ratio <= 1.3 ? "watch" : "alert"
const PART_LABEL: Record<string, string> = { hrv: "HRV pod normou", rhr: "klidový tep nad normou", sleep: "kratší spánek než obvykle", sleepQuality: "víc bdění v noci", soreness: "svalová bolest", fatigue: "únava", stress: "stres mimo trénink", session: "dnešní trénink", dayStress: "zvýšený tep v klidu včera", dayLoad: "pohyb mimo trénink dnes", dayStressNow: "zvýšený tep v klidu dnes" }

export const readinessPct = (r: any) => (r?.score ?? Math.round((r?.today ?? 1) * 100)) as number
// railway#108 — green above 70 %, red below 40 %, as on the Dnes rings
export const readinessCol = (pct: number) => goodCol(pct)

// v0.10.4 — today's drop: the session(s) and the day outside training so far
export function dayBits(a: any): string[] {
  return [a?.nt && `pohyb mimo trénink +${a.nt.excess} j.z. nad obvyklý den`, a?.stress && `${a.stress.min} min zvýšeného tepu v klidu`].filter(Boolean) as string[]
}
export function afterLine(r: any): string {
  const a = r?.afterSession
  if (!a?.drop) return ""
  const bits: string[] = []
  if (a.sessionDrop) bits.push(a.today ? `po dnešním tréninku −${a.sessionDrop} · ${a.today.band}` : `včerejší náročný trénink ještě doznívá −${a.sessionDrop}`)
  if (a.dayDrop) bits.push(`den mimo trénink −${a.dayDrop} (${dayBits(a).join(", ")})`)
  const t = bits.join("; ")
  return `${t.charAt(0).toUpperCase()}${t.slice(1)} · ráno ${r.morningScore} % · zítra ji upřesní noční data`
}

export function Readiness({ r }: { r: any }) {
  const pct = readinessPct(r)
  const parts = Object.entries(r?.parts || {}).filter(([, v]) => (v as number) > 0.05) as [string, number][]
  const col = readinessCol(pct)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-full px-2.5 py-1 text-[12px] font-bold" style={{ background: `${col}1f`, color: col }}>Připravenost dnes {pct} %</span>
      {r?.afterSession?.drop ? (
        <span className="basis-full text-[11px] text-fg-2" data-testid="readiness-after">
          {afterLine(r)}
        </span>
      ) : null}
      {parts.length ? parts.map(([k, v]) => (
        <span key={k} className="rounded-full bg-white/[.06] px-2.5 py-1 text-[11px] font-semibold text-fg-2" style={{ opacity: 0.6 + 0.4 * v }}>{PART_LABEL[k] || k}</span>
      )) : <span className="text-[11px] text-fg-3">bez snížení</span>}
      <InfoDot text={MI.readiness} label="Připravenost" />
    </div>
  )
}

// Feedback railway#107 — what lowers readiness today and what keeps it up, each signal
// with its reading against the runner's usual value and the points it costs, plus the
// change since yesterday morning. Points follow the engine: 100 − 80 × combined
// deficit, the strongest signal fully, the 2nd half, the 3rd a quarter.
const SLEEP_Q = ["velmi špatně", "špatně", "průměrně", "dobře", "výborně"]
const FACTOR_LABEL: Record<string, string> = { hrv: "HRV", rhr: "Klidový tep", sleep: "Délka spánku", sleepQuality: "Kvalita spánku", soreness: "Svalová bolest", fatigue: "Únava", stress: "Stres mimo trénink", dayStress: "Zvýšený tep v klidu včera", session: "Dnešní trénink", day: "Den mimo trénink" }
const pctS = (v: number | null | undefined) => (v == null ? null : `${Math.round(v * 100)} %`)
const vs = (parts: (string | null | false)[]) => parts.filter(Boolean).join(" · ")
const pts1 = (v: number) => (Math.round(v * 10) / 10).toLocaleString("cs-CZ")

function factorReading(k: string, r: any): string | null {
  const i = r?.inputs || {}
  const n = i.night || {}, w = i.week || {}, b = i.base || {}, c = i.checkin
  if (k === "hrv") return n.hrv == null && w.hrv == null ? null : vs([n.hrv != null && `noc ${n.hrv} ms`, w.hrv != null && `7 nocí ${w.hrv} ms`, b.hrv != null && `obvykle ${b.hrv} ms`])
  if (k === "rhr") return n.rhr == null && w.rhr == null ? null : vs([n.rhr != null && `noc ${n.rhr}`, w.rhr != null && `7 nocí ${w.rhr}`, b.rhr != null && `obvykle ${b.rhr} tepů/min`])
  if (k === "sleep") return vs([n.sleep != null && `poslední noc ${num(n.sleep)} h`, w.sleep != null && `3 noci ${num(w.sleep)} h`, b.sleep != null && `obvykle ${num(b.sleep)} h`]) || null
  // v0.11.0 — quality = efficiency over 3 nights; the deep + REM share is shown, not scored
  if (k === "sleepQuality") {
    if (b.eff == null) return null                       // no norm yet: nothing to judge against
    const q = c?.sleepQuality
    return vs([w.eff != null ? `efektivita 3 noci ${pctS(w.eff)}` : n.eff != null && `efektivita ${pctS(n.eff)}`, b.eff != null && `obvykle ${pctS(b.eff)}`,
      n.rest != null && `hluboký + REM ${pctS(n.rest)}${b.rest != null ? ` (obvykle ${pctS(b.rest)})` : ""}, jen pro informaci`,
      q != null && SLEEP_Q[q] && `vaše hodnocení: ${SLEEP_Q[q]}`]) || null
  }
  if (k === "soreness") return c?.soreness == null ? null : `v check-inu ${c.soreness}/10 · snižuje od 6/10`
  if (k === "fatigue") return c?.fatigue == null ? null : `v check-inu ${c.fatigue}/10 · snižuje od 6/10`
  if (k === "stress") return c?.stress == null ? null : `v check-inu ${c.stress}/10 · snižuje od 6/10, počítá se 0,6×`
  if (k === "dayStress") { const ds = r?.inputs?.dayStress; return ds ? `včera ${ds.yesterday} min${ds.usual != null ? ` · obvykle ${ds.usual} min` : ""} · z celodenního tepu, počítá se 0,6×` : null }
  if (k === "session") {
    const a = r?.afterSession
    if (!a) return null
    const t = a.today
    return vs([t && `${(t.sessions || []).map((s: any) => s.title).filter(Boolean).join(", ") || "trénink"} · ${t.band}`, a.carry && `doznívá včerejší náročný trénink`, "zítra ji upřesní noční data"])
  }
  return null
}

export function ReadinessFactors({ r }: { r: any }) {
  if (!r?.inputs) return null
  const eff: Record<string, number> = r.effects || {}
  const keys = ["hrv", "rhr", "sleep", "sleepQuality", "dayStress", "soreness", "fatigue", "stress", "session"]
  const part: Record<string, number> = r.parts || {}
  // every signal off its norm is listed, also one that adds nothing because stronger
  // signals already cover it (only the three strongest count)
  const lower = keys.filter((k) => (part[k] || 0) > 0).sort((a, b) => (eff[b] || 0) - (eff[a] || 0) || part[b] - part[a])
  // a signal counts only with today's reading: without last night's data the engine
  // doesn't judge HRV / resting HR / sleep, so they are listed apart, not as "in norm"
  const n = r.inputs.night || {}, ci = r.inputs.checkin
  const today = (k: string) => (k === "hrv" ? n.hrv != null : k === "rhr" ? n.rhr != null : k === "sleep" ? n.sleep != null : k === "sleepQuality" ? n.eff != null : k === "dayStress" ? r.inputs?.dayStress != null : ci?.[k] != null)
  const fine = keys.filter((k) => k !== "session" && !lower.includes(k) && today(k) && factorReading(k, r))
  const stale = ["hrv", "rhr", "sleep", "sleepQuality"].filter((k) => !lower.includes(k) && !today(k) && factorReading(k, r))
  const habit = r.inputs.sleepHabit
  const noCheckin = !ci
  const y = r.yesterday
  const delta = y?.known ? (r.morningScore ?? r.score) - y.score : null
  const sess = r.afterSession?.sessionDrop || 0
  const dayD = r.afterSession?.dayDrop || 0
  // feedback #146 — a waterfall: from yesterday morning (or from full readiness when
  // yesterday is unknown) each signal's change raises (green) or lowers (red) the score
  const mEff: Record<string, number> = r.morningEffects || eff
  const morning: number = r.morningScore ?? r.score
  const covered = lower.filter((k) => (eff[k] || 0) < 0.5)
  const wf = (() => {
    const steps: WStep[] = []
    let cum: number
    if (y?.known) {
      const yEff: Record<string, number> = y.effects || {}
      cum = y.score
      steps.push({ key: "y", label: "Včera ráno", total: y.score })
      keys.filter((k) => k !== "session")
        .map((k) => [k, (yEff[k] || 0) - (mEff[k] || 0)] as [string, number])
        .filter(([, d]) => Math.abs(d) >= 0.5)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .forEach(([k, d]) => {
          cum += d
          steps.push({ key: k, label: FACTOR_LABEL[k], sub: d > 0 ? "blíž normě" : factorReading(k, r) || "dál od normy", delta: d })
        })
    } else {
      cum = 100
      steps.push({ key: "full", label: "Plná připravenost", total: 100 })
      keys.filter((k) => k !== "session" && (mEff[k] || 0) >= 0.5)
        .sort((a, b) => (mEff[b] || 0) - (mEff[a] || 0))
        .forEach((k) => {
          cum -= mEff[k]
          steps.push({ key: k, label: FACTOR_LABEL[k], sub: factorReading(k, r) || undefined, delta: -mEff[k] })
        })
    }
    if (Math.abs(morning - cum) >= 1) steps.push({ key: "round", label: "Souhrn signálů", sub: "překryv a zaokrouhlení", delta: morning - cum, color: C.fg3 })
    if (sess >= 0.5 || dayD >= 0.5) steps.push({ key: "m", label: "Dnes ráno", total: morning })
    if (sess >= 0.5) steps.push({ key: "session", label: FACTOR_LABEL.session, sub: factorReading("session", r) || undefined, delta: -sess })
    if (dayD >= 0.5) steps.push({ key: "day", label: FACTOR_LABEL.day, sub: `${dayBits(r.afterSession).join(" · ")} · zítra ji upřesní noční data`, delta: -dayD })
    const now: number = r.score ?? morning
    steps.push({ key: "now", label: sess >= 0.5 || dayD >= 0.5 ? "Teď" : "Dnes", total: now, color: readinessCol(now) })
    let run = 0, min = 100
    for (const st of steps) { run = st.total ?? run + (st.delta || 0); min = Math.min(min, run) }
    return { steps, lo: Math.max(0, Math.floor((min - 10) / 10) * 10) }
  })()
  return (
    <div className="nest mt-3 p-3.5" data-testid="readiness-factors">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Co připravenost ovlivňuje</Label>
        {delta != null && (
          <span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${delta > 0 ? C.ok : delta < 0 ? C.alert : C.fg3}1f`, color: delta > 0 ? C.ok : delta < 0 ? C.alert : C.fg2 }}>
            {delta > 0 ? "▲" : delta < 0 ? "▼" : "▬"} ráno {delta > 0 ? `+${delta}` : delta < 0 ? `−${-delta}` : "beze změny"} oproti včerejšímu ránu ({y.score} %)
          </span>
        )}
      </div>
      {!r.known && !lower.length && (
        <p className="mt-2 text-[12px] leading-5 text-fg-2">Dnes zatím chybí noční data z hodinek{noCheckin ? " i check-in" : ""}, proto připravenost nic nesnižuje. Po synchronizaci se přepočítá.</p>
      )}
      {(r.known || lower.length > 0) && <Waterfall steps={wf.steps} lo={wf.lo} hi={100} unit=" %" testid="readiness-waterfall" wrapSub />}
      {(fine.length > 0 || covered.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {fine.map((k) => (
            <span key={k} className="rounded-full px-2.5 py-1 text-[11px] font-semibold" style={{ background: `${C.ok}1f`, color: C.ok }} title={factorReading(k, r) || ""}>
              {FACTOR_LABEL[k]} v normě
            </span>
          ))}
          {covered.map((k) => (
            <span key={k} className="rounded-full bg-white/[.06] px-2.5 py-1 text-[11px] font-semibold text-fg-3" title={factorReading(k, r) || ""}>
              {FACTOR_LABEL[k]} mimo normu, překryto silnějšími
            </span>
          ))}
        </div>
      )}
      {stale.length > 0 && (
        <p className="mt-2 text-[11px] leading-4 text-fg-3">Bez dnešní noci, nezapočítává se: {stale.map((k) => FACTOR_LABEL[k]).join(", ")}.</p>
      )}
      {noCheckin && <p className="mt-1 text-[11px] leading-4 text-fg-3">Dnešní check-in zatím chybí, svalová bolest, únava a stres se proto nezapočítávají.</p>}
      {/* v0.11.0 — a habitually short sleep is a note beside readiness, not a daily deduction */}
      {habit && (
        <p className="mt-2 rounded-[10px] bg-white/[.05] px-2.5 py-2 text-[11.5px] leading-[17px] text-fg-2" data-testid="sleep-habit">
          {habit.severe
            ? `Dlouhodobě spíte v průměru ${num(habit.avg)} h (${habit.under} z ${habit.n} nocí pod 7 h). Noci pod 6 h snižují připravenost, i když jsou pro vás běžné. Pro zdraví a regeneraci se dospělým doporučuje aspoň 7 hodin.`
            : `Dlouhodobě spíte v průměru ${num(habit.avg)} h (${habit.under} z ${habit.n} nocí pod 7 h). Do připravenosti se to nepočítá, ta sleduje odchylky od vaší normy. Pro zdraví a regeneraci se dospělým doporučuje aspoň 7 hodin.`}
        </p>
      )}
      <p className="mt-3 border-t border-white/[.07] pt-2.5 text-[11px] leading-4 text-fg-3">
        Zelená zvyšuje, červená snižuje. Nejsilnější signál se počítá celý, druhý z poloviny a třetí ze čtvrtiny, protože se signály často překrývají. Obvyklá hodnota je průměr vašich nocí 8–56 dní zpět a běžné kolísání do ±0,5 SD nic nestojí. Kvalita spánku (efektivita za 3 noci) stojí nejvýš 20 bodů a bez potvrzení od HRV nebo tepu 10; fáze spánku z hodinek se nepočítají.
      </p>
    </div>
  )
}

// now vs ceiling on one bar; the ceiling marker sits where the bar would hit it
function HeadroomBar({ now, ceiling, tone, target }: { now: number | null; ceiling: number | null; tone: string; target?: number | null }) {
  if (now == null || ceiling == null || ceiling <= 0) return <div className="h-2 rounded-full bg-white/[.08]" />
  const scale = Math.max(now, ceiling, target || 0) * 1.08
  const col = (TONE as any)[tone] || TONE.ok
  return (
    <div className="relative h-2 rounded-full bg-white/[.08]">
      <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(now / scale) * 100}%`, background: col }} />
      <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${(ceiling / scale) * 100}% - 1px)` }} title="strop" />
      {target != null && <i className="absolute -inset-y-1 w-0.5 rounded-full" style={{ left: `calc(${(target / scale) * 100}% - 1px)`, background: C.watch }} title="cíl týdne v cyklu" />}
    </div>
  )
}

const CH_NOTE: Record<string, string> = {
  strength: "Posilování: náročnost po tréninku (0–10) × minuty, cvičení nohou a celého těla plně, horní polovina těla z menší části. Hlídá prudké skoky, třeba první plyometrii po pauze. Těžké posilování nohou navíc na 24–48 hodin sníží v Tréninku strop minut v Z4+.",
}

// Feedback railway#53 — each channel box shows its headline (capacity vs 7 days) and
// keeps the rest behind a detail arrow. railway#56–#61: the charts that feed a channel
// (volume bars, HR zones and relative effort, cross-training, descent by slope) live in
// that channel's detail rather than as separate cards further down the page.
function ChannelRow({ id, c, margins, extra, open, onToggle, scale, sub, target }: { id: string; c: any; margins: any; extra?: ReactNode; open: boolean; onToggle: () => void; scale?: number; sub?: any; target?: { budget: number; done: number } | null }) {
  const wk = c.week
  const ses = c.session
  const wTone = toneOf(wk?.ratio, margins.week)
  const sTone = toneOf(ses?.ratio, margins.session)
  const why = !c.pts ? null : c.driver === "session" ? (id === "strength" ? "za jedno posilování nad kapacitou" : "za jeden běh nad kapacitou") : c.driver === "week" ? "za 7 dní nad kapacitou" : c.driver === "latent" ? "doznívající skok" : null
  const hasDetail = !!(extra || (c.known && (ses || c.latent || c.pendingJump || CH_NOTE[id])))
  return (
    <div className={`nest p-3.5 transition ${open ? "md:col-span-full !border-accent/60" : ""}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm font-bold text-fg">{c.label}</b>
        <span className="grid size-5 place-items-center rounded-full bg-white/[.07] text-[11px] font-extrabold text-fg-2">{c.grade}</span>
        <span className="ml-auto text-right tabular-nums text-[12px] font-bold" style={{ color: c.pts ? C.watch : C.fg3 }}>
          {/* railway#111 — percentage points off the overall Skóre, not load points (#150: incl. strength) */}
          <span title="o kolik procentních bodů snižuje celkové Skóre">{scale != null ? fmtImpact(toImpact((c.pts || 0) + (sub?.pts || 0), scale)) : c.pts ? `+${c.pts} b` : "0 b"}</span>
          {why && <span className="block font-sans text-[11px] font-normal text-fg-3">{why}</span>}
        </span>
      </div>
      {!c.known ? (
        <p className="mt-2 text-[11px] text-fg-3">Kapacitu teprve poznáváme — stačí pár běhů{id === "intensity" ? " s tepem" : ""}.</p>
      ) : wk && (
        <>
          <p className="mt-1.5 text-[12px] text-fg-2">
            Týdenní kapacita <b className="text-fg">{num(wk.cap)} {c.unit}</b>
            <span className="text-[11px] text-fg-3"> · strop {num(wk.ceiling)}{wk.ceiling < wk.cap ? " (snížený připraveností)" : " s rezervou"}</span>
          </p>
          <div className="mt-2">
            <div className="mb-1 flex justify-between text-[11px] text-fg-3">
              <span>posledních 7 dní <b className="text-fg">{num(wk.now)}</b> {c.unit}</span>
              <span>{wk.left > 0 ? `do stropu zbývá ${num(wk.left)}` : "strop vyčerpán"}</span>
            </div>
            <HeadroomBar now={wk.now} ceiling={wk.ceiling} tone={wTone} target={target && target.budget < wk.ceiling - 0.05 ? target.budget : null} />
          </div>
          {/* feedback #181 — the week's target from Trénink, when it is lower than the ceiling */}
          {target && target.budget < wk.ceiling - 0.05 && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-fg-3" data-testid="cycle-target">
              <i className="h-2.5 w-0.5 rounded-full" style={{ background: C.watch }} />
              {`cíl týdne v cyklu ${num(target.budget)} ${c.unit} · od pondělí ${num(target.done)}`}
            </p>
          )}
        </>
      )}
      {sub?.known && sub.week && (
        // feedback #150 — strength load lives in the all-sport card, as its own sub-channel
        <div className="mt-3 border-t border-white/[.07] pt-2.5" data-testid="strength-sub">
          <div className="mb-1 flex justify-between gap-2 text-[11px] text-fg-3">
            <span><b className="text-fg-soft">z toho posilování</b> · 7 dní <b className="text-fg">{num(sub.week.now)}</b> {sub.unit}</span>
            <span>{sub.week.left > 0 ? `do stropu ${num(sub.week.left)}` : "strop vyčerpán"}{sub.pts ? ` · ${scale != null ? fmtImpact(toImpact(sub.pts, scale)) : `+${sub.pts} b`}` : ""}</span>
          </div>
          <HeadroomBar now={sub.week.now} ceiling={sub.week.ceiling} tone={toneOf(sub.week.ratio, margins.week)} />
        </div>
      )}
      {hasDetail && (
        <button type="button" onClick={onToggle} aria-expanded={open}
          className="mt-3 flex w-full items-center justify-between gap-2 border-t border-white/[.07] pt-2.5 text-left text-[12px] font-semibold text-fg-2 transition hover:text-fg">
          <span>{open ? "Skrýt detail" : "Detail"}</span>
          <ChevronDown className={`size-4 transition ${open ? "rotate-180 text-accent" : "text-fg-3"}`} aria-hidden />
        </button>
      )}
      {open && hasDetail && (
        <div className="origin-top animate-[careReveal_.28s_ease-out] pt-2">
          {c.known && ses && id !== "systemic" && (
            <p className="text-[11px] text-fg-3">
              Nejnáročnější {id === "strength" ? "posilování" : "běh"} 7 dní ({fmtD(ses.date)}): <b style={{ color: (TONE as any)[sTone] }}>{num(ses.value)} {c.unit} · ×{num(ses.ratio)}</b> proti kapacitě {id === "strength" ? "jednoho posilování" : "jednoho běhu"} {num(ses.cap)}
              {(ses.readinessScore ?? 100) < 97 ? ` · připravenost ${ses.readinessScore} %` : ""}
            </p>
          )}
          {c.known && wk?.residual != null && id !== "systemic" && (
            <p className="mt-1 text-[11px] text-fg-3">
              Nevstřebáno <b className="text-fg">{num(wk.residual)} {c.unit}</b> (týdenní ekvivalent, klesá každou noc) {wk.capPeak != null ? <>proti vaší obvyklé týdenní špičce {num(wk.capPeak)} · ×{num(wk.ratio)}</> : <>proti kapacitě {num(wk.cap)}</>}
              {ses?.left != null && ses.left < 0.99 ? ` · z nejnáročnějšího běhu zbývá asi ${Math.round(ses.left * 100)} %` : ""}
            </p>
          )}
          {c.known && c.latent && <p className="mt-1 text-[11px] text-watch">Doznívá skok ×{num(c.latent.ratio)} z {fmtD(c.latent.date)}</p>}
          {c.known && c.pendingJump && <PendingJump j={c.pendingJump} unit={c.unit} />}
          {c.known && CH_NOTE[id] && <p className="mt-2 text-[11px] leading-4 text-fg-3">{CH_NOTE[id]}</p>}
          {extra && <div className="mt-4">{extra}</div>}
        </div>
      )}
    </div>
  )
}

// Feedback #149 — what each activity of the last 7 days added to the all-sport load,
// as a waterfall up to the 7-day total, with the weekly ceiling as the last bar.
const SPORT_CS: Record<string, string> = { running: "Běh", cycling: "Kolo", swimming: "Plavání", strength: "Posilování", rowing: "Veslování", elliptical: "Orbitrek", hiking: "Turistika", walking: "Chůze", other: "Jiný sport" }
const sportCol = (x: any) => (x.run ? C.accent : x.sport === "strength" ? C.self : C.info)

export function SystemicWaterfall({ c, target }: { c: any; target?: number | null }) {
  const list: any[] = c?.week7 || []
  const wk = c?.week
  if (!list.length) return <p className="text-[12px] text-fg-3">Za posledních 7 dní žádná aktivita se zátěží.</p>
  const tot = list.reduce((a, x) => a + (x.value || 0), 0)
  const steps: WStep[] = list.map((x) => ({
    key: String(x.id), label: x.title || SPORT_CS[x.sport] || "Aktivita", sub: `${fmtD(x.date)} · ${SPORT_CS[x.run ? "running" : x.sport] || "jiný sport"}`,
    delta: x.value || 0, color: sportCol(x), value: `+${num(x.value)}`,
  }))
  steps.push({ key: "sum", label: "7 dní celkem", total: tot, color: wk?.ceiling && tot > wk.ceiling ? C.alert : C.ok, value: num(Math.round(tot)) })
  if (wk?.ceiling) steps.push({ key: "ceil", label: "Týdenní strop", total: wk.ceiling, color: C.fg4, value: num(wk.ceiling) })
  // feedback #181 — the week's target in the training cycle, when Trénink sets a lower one
  if (target != null && (!wk?.ceiling || target < wk.ceiling - 0.5)) steps.push({ key: "target", label: "Cíl týdne v cyklu", sub: "z Tréninku, počítá se od pondělí", total: target, color: C.watch, value: num(Math.round(target)) })
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Co přidala každá aktivita (7 dní)</Label>
        <span className="flex gap-2.5 text-[10.5px] text-fg-3">
          <span className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: C.accent }} />běh</span>
          <span className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: C.info }} />jiný sport</span>
          <span className="flex items-center gap-1"><i className="size-2 rounded-full" style={{ background: C.self }} />posilování</span>
        </span>
      </div>
      <Waterfall steps={steps} hi={Math.max(tot, wk?.ceiling || 0, target || 0) * 1.04} testid="systemic-waterfall" />
      <p className="mt-2 text-[11px] text-fg-3">j.z. = tep × čas, u posilování a plavání náročnost × minuty</p>
    </div>
  )
}

// plan B1: a big jump isn't capacity until it's held for 14 days (and confirmed pain-free)
function PendingJump({ j, unit }: { j: any; unit: string }) {
  const held = j.countsFrom <= new Date().toISOString().slice(0, 10)
  return (
    <p className="mt-1 text-[11px] leading-4 text-fg-2">
      Skok {fmtD(j.date)} ({num(j.value)} {unit}{j.ratio ? ` · ×${num(j.ratio)}` : ""}){" "}
      {held ? "se do kapacity počítá jen napůl" : `se do kapacity nepočítá do ${fmtD(j.countsFrom)}`}
      {j.confirmed ? "." : " — ohodnoťte ten běh (bolest 0), ať se po té době započítá celý."}
    </p>
  )
}

function ZoneTime({ cap }: { cap: any }) {
  const zones: any[] = cap.zones || []
  const mins: Record<string, number> = Object.fromEntries((cap.zones7d?.minutes || []).map((z: any) => [z.z, z.min]))
  const max = Math.max(1, ...Object.values(mins))
  const total = Object.values(mins).reduce((a, b) => a + b, 0)
  return (
    <div>
      <span className="flex items-center gap-1.5"><Label>Tepové zóny · čas za 7 dní</Label>
        {!cap.hrMaxMeasured && <span className="rounded-full bg-white/[.06] px-1.5 py-0.5 text-[11px] font-bold text-fg-2" title="Maximální tep je odhad — změřený zadejte v profilu">odhad</span>}
        <InfoDot text={MI.hrZones} label="Tepové zóny" /></span>
      <div className="mt-2 grid grid-cols-5 gap-1 text-center">
        {zones.map((z: any) => {
          const hard = z.z === "Z4" || z.z === "Z5"
          const m = mins[z.z]
          return (
            <div key={z.z} className={`flex flex-col rounded-[12px] border px-1 py-2 ${hard ? "border-alert/25 bg-alert/10" : "border-white/[.06] bg-white/[.04]"}`}>
              <b className="block text-[11px] text-fg">{z.z}</b>
              <span className="tabular-nums text-[11px] text-fg-2">{z.lo}–{z.hi}</span>
              <div className="mx-auto mt-1.5 flex h-12 w-3 items-end overflow-hidden rounded-full bg-white/[.08]">
                <i className="block w-full rounded-full" style={{ height: `${((m || 0) / max) * 100}%`, background: hard ? C.alert : C.ok }} />
              </div>
              <span className="mt-1 tabular-nums text-[11px] font-bold text-fg">{m != null ? `${m} min` : "—"}</span>
            </div>
          )
        })}
      </div>
      <p className="mt-1.5 text-[11px] leading-4 text-fg-3">
        {cap.zones7d ? `${cap.zones7d.runs} ${cap.zones7d.runs === 1 ? "běh" : cap.zones7d.runs < 5 ? "běhy" : "běhů"}${cap.zones7d.cross ? ` + ${cap.zones7d.cross} kolo / plavání (podle jejich tepových zón)` : ""} · celkem ${total} min${cap.zones7d.exact ? "" : " · bez detailních dat odhad z průměrného tepu"}` : "Za posledních 7 dní žádný běh s tepem."}
        {" "}· max {cap.hrMaxMeasured ? `${cap.hrMax} (změřený)` : `≈ ${cap.hrMax} (odhad — změřený zadejte v profilu)`} · klid ≈ {cap.hrRest} tep/min · kanál intenzity = minuty v Z4+
      </p>
    </div>
  )
}

// Feedback #148 — relative effort on an interval scale: where each run sits against the
// runner's usual efforts of the last 8 weeks. Light green = well below, dark green =
// around the middle, orange = above the usual range, red = harder than any of them.
const EFFORT_GRAD = "linear-gradient(90deg, #b4f0cd 0%, #6fd9a3 18%, #2c9a6a 32%, #2c9a6a 58%, #f3a54b 72%, #f3a54b 80%, #f0795a 86%, #e2553a 100%)"
const EFFORT_BAND: Record<string, [string, string]> = {
  pod: ["pod obvyklým", "#6fd9a3"], "obvyklé": ["obvyklé", "#3fb784"], nad: ["nad obvyklým", "#f3a54b"], "výrazně nad": ["výrazně nad", C.alert],
}
// 0–85 % of the scale = the percentile among the last 8 weeks' runs, 85–100 % = beyond the hardest
const effortPos = (r: any): number | null => {
  if (r.pct == null) return null
  if (r.band === "výrazně nad") return 86 + Math.min(13, Math.max(1, ((r.overMax ?? 1.1) - 1) * 45))
  return Math.min(84, r.pct * 0.84)
}

function EffortScale({ pos, col }: { pos: number | null; col: string }) {
  return (
    <span className="relative block h-2.5 w-full rounded-full" style={{ background: EFFORT_GRAD, opacity: pos == null ? 0.25 : 1 }}>
      {pos != null && (
        <i className="absolute top-1/2 block size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink shadow" style={{ left: `${pos}%`, background: col }} />
      )}
    </span>
  )
}

function RelativeEffort({ re }: { re: any }) {
  const wk = re.week
  // the week has the usual range only: lo → 21 %, hi → 63 % of the scale (the middle quartiles)
  const wkPos = wk ? (wk.now <= wk.lo ? Math.max(2, (wk.now / Math.max(wk.lo, 1)) * 21)
    : wk.now <= wk.hi ? 21 + ((wk.now - wk.lo) / Math.max(wk.hi - wk.lo, 1)) * 42
      : Math.min(97, 63 + ((wk.now - wk.hi) / Math.max(wk.hi, 1)) * 60)) : null
  return (
    <div>
      <span className="flex items-center gap-1.5"><Label>Relativní úsilí posledních běhů</Label><InfoDot text={MI.relEffort} label="Relativní úsilí" /></span>
      {re.runs?.length ? (
        <>
          <div className="mt-2 flex justify-between text-[10px] text-fg-3"><span>lehčí</span><span>obvyklé úsilí</span><span>těžší</span></div>
          <div className="divide-y divide-white/[.06]" data-testid="effort-scale">
            {re.runs.map((r: any, i: number) => {
              const [bl, bc] = EFFORT_BAND[r.band] || ["málo historie", TONE.muted]
              return (
                <div key={i} className="py-2 text-[12px]">
                  <div className="flex items-baseline gap-2">
                    <span className="w-12 shrink-0 whitespace-nowrap tabular-nums text-[11px] text-fg-3">{fmtD(r.date)}</span>
                    <span className="min-w-0 flex-1 truncate text-fg">{r.title || "Běh"}{r.km ? ` · ${num(r.km)} km` : ""}</span>
                    <b className="shrink-0 whitespace-nowrap text-[11px]" style={{ color: bc }}>{bl}</b>
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="w-12 shrink-0 whitespace-nowrap text-right tabular-nums text-[10.5px] text-fg-3">{r.effort} j.z.</span>
                    <span className="flex-1"><EffortScale pos={effortPos(r)} col={bc} /></span>
                  </div>
                  {r.hrDelta != null && Math.abs(r.hrDelta) >= 5 && (
                    <p className="mt-1 pl-14 text-[10.5px]" style={{ color: r.hrDelta > 0 ? TONE.watch : TONE.ok }}>tep při tomto tempu {r.hrDelta > 0 ? "+" : ""}{r.hrDelta} oproti obvyklému</p>
                  )}
                </div>
              )
            })}
          </div>
        </>
      ) : <p className="mt-2 text-xs text-fg-3">Zatím málo běhů s tepem.</p>}
      {wk && (
        <div className="mt-2 border-t border-white/[.07] pt-2">
          <div className="flex items-baseline justify-between gap-2 text-[11px] text-fg-2">
            <span>Týden: <b className="text-fg">{wk.now} j.z.</b> · obvykle {wk.lo}–{wk.hi}</span>
            <b style={{ color: (EFFORT_BAND[wk.band] || [])[1] }}>{(EFFORT_BAND[wk.band] || [wk.band])[0]}</b>
          </div>
          <div className="mt-1.5"><EffortScale pos={wkPos} col={(EFFORT_BAND[wk.band] || [])[1] || C.fg3} /></div>
        </div>
      )}
    </div>
  )
}

// Feedback #159 — which body regions the last 7 days of running loaded and how full
// their capacity is. A region's fill is a weighted mix of the run channels' fill
// (last 7 days ÷ the 7-day ceiling). The weights are the app's working model from the
// Literature Summary: injuries that follow jumps in distance (patellofemoral pain, IT
// band, medial shin, lateral hip) vs. those attributed to pace (Achilles, calf, plantar
// fascia, tibial stress fracture, hamstrings, iliopsoas) (Nielsen et al., 2014); downhill
// braking at the knee and higher tibial shock, more hip work uphill (Vernillo et al.,
// 2017); the calf carries most of the support at all recreational paces, the hamstrings
// and hip flexors take over only near sprinting (Dorn et al., 2012).
export const BODY_REGIONS: { title: string; label: string; w: Partial<Record<(typeof RUN_CH)[number], number>> }[] = [
  { title: "Patelární šlacha", label: "Koleno", w: { volume: 0.5, descent: 0.5 } },
  { title: "Kvadriceps", label: "Přední strana stehna", w: { descent: 0.7, volume: 0.3 } },
  { title: "Tibialis anterior (holeň)", label: "Holeň", w: { volume: 0.5, intensity: 0.3, descent: 0.2 } },
  { title: "Iliotibiální trakt (IT band)", label: "IT pás", w: { volume: 0.7, descent: 0.3 } },
  { title: "Lýtko (gastrocnemius)", label: "Lýtko", w: { intensity: 0.45, ascent: 0.3, volume: 0.25 } },
  { title: "Achillova šlacha", label: "Achillova šlacha", w: { intensity: 0.45, ascent: 0.3, volume: 0.25 } },
  { title: "Úpon plantární fascie (pata)", label: "Plantární fascie", w: { intensity: 0.5, volume: 0.3, ascent: 0.2 } },
  { title: "Hamstring", label: "Zadní strana stehna", w: { intensity: 0.7, ascent: 0.3 } },
  { title: "Ohýbač kyčle", label: "Ohýbač kyčle", w: { intensity: 0.7, volume: 0.3 } },
  { title: "Hýždě (gluteus)", label: "Hýždě", w: { volume: 0.4, ascent: 0.4, intensity: 0.2 } },
]

export function bodyLoad(cap: any): Record<string, number> {
  const out: Record<string, number> = {}
  for (const r of BODY_REGIONS) {
    let num = 0, den = 0
    for (const [id, w] of Object.entries(r.w)) {
      const wk = cap?.channels?.[id]?.week
      if (wk?.now == null || !wk?.ceiling) continue
      num += (w as number) * (wk.now / wk.ceiling)
      den += w as number
    }
    if (den >= 0.5) out[r.title] = num / den
  }
  return out
}

function BodyLoad({ cap }: { cap: any }) {
  const { boot } = useApp()
  const fills = bodyLoad(cap)
  if (!Object.keys(fills).length) return null
  // regions marked painful in the last 14 days get a ring
  const since = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10)
  const pain = new Set<string>()
  for (const c of (boot?.checkins || []) as any[]) {
    if (String(c.submitted_at || "") < since || !(c.pain_score > 0)) continue
    for (const p of (c.pain_points || []) as any[]) pain.add(String(p.region || "").replace(/ \((L|P)\)$/, ""))
  }
  const rows = BODY_REGIONS.filter((r) => fills[r.title] != null).sort((x, y) => fills[y.title] - fills[x.title])
  const col = (f: number) => (f >= 1 ? C.alert : f >= 0.7 ? C.watch : C.ok)
  return (
    <div className="mt-5 border-t border-white/[.07] pt-4" data-testid="body-load">
      <p className="t-label !text-fg-3">Kde běh zatěžuje tělo · 7 dní</p>
      <div className="mt-3 grid items-start gap-5 sm:grid-cols-[220px_1fr]">
        <BodyLoadMap fills={fills} pain={pain} />
        <div className="space-y-2.5">
          {rows.map((r) => {
            const f = fills[r.title]
            return (
              <div key={r.title}>
                <div className="flex items-baseline justify-between gap-2 text-[12px]">
                  <span className="font-semibold text-fg-soft">{r.label}{pain.has(r.title) ? <span className="ml-1.5 text-[10.5px] font-bold text-alert-soft">bolest</span> : null}</span>
                  <span className="tabular-nums font-bold" style={{ color: col(f) }}>{Math.round(f * 100)} %</span>
                </div>
                <div className="relative mt-1 h-1.5 rounded-full bg-white/[.06]">
                  <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, (f / 1.2) * 100)}%`, background: col(f) }} />
                  <i className="absolute -top-0.5 h-2.5 w-px bg-fg-2" style={{ left: `${100 / 1.2}%` }} title="strop 7 dní" />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function CapacityPanel({ cap, extra = {}, scale }: { cap: any; extra?: Record<string, ReactNode>; scale?: number }) {
  const [open, setOpen] = useState("")
  const { boot } = useApp()
  const gch = boot?.assessment?.guidance?.week?.channels || {}
  const targets: Record<string, number | null> = Object.fromEntries(Object.entries(gch).map(([k, v]: any) => [k, v?.budget ?? null]))
  if (!cap) return null
  const re = cap.relativeEffort || {}
  // intensity = minutes in Z4+, so its detail carries the HR zones and relative effort (railway#56/#57)
  const extras: Record<string, ReactNode> = {
    ...extra,
    systemic: <><SystemicWaterfall c={cap.channels?.systemic} target={targets?.systemic} /><BodyLoad cap={cap} /></>,
    intensity: (
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <RelativeEffort re={re} />
        <ZoneTime cap={cap} />
      </div>
    ),
  }
  return (
    <section className="card mb-4 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="flex items-center gap-1.5"><Label>Týdenní kapacita</Label><InfoDot wide label="Kapacita" text={<>
            <span className="block">Posledních 7 dní proti tomu, co za týden prokazatelně zvládáte bez obtíží. Bílá čárka = strop (kapacita + 15 % rezerva, podle připravenosti v týdnu). Kolik z toho je v plánu na tento týden a na dnešek, ukazuje Trénink.</span>
            <span className="mt-2 block">{MI.capacity}</span>
          </>} /></span>
        </div>
        <Readiness r={cap.readiness} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 min-[1600px]:grid-cols-3">
        {CH_ORDER.map((id) => cap.channels?.[id] && id !== "strength" && (
          <ChannelRow key={id} id={id} c={cap.channels[id]} margins={cap.margins} extra={extras[id]} scale={scale}
            target={gch[id]?.budget != null ? { budget: gch[id].budget, done: gch[id].done ?? 0 } : null}
            sub={id === "systemic" ? cap.channels.strength : undefined}
            open={open === id} onToggle={() => setOpen(open === id ? "" : id)} />
        ))}
      </div>
      {cap.margins?.frailty > 1 && (
        <p className="mt-3 text-[11px] text-fg-3">Zranění v posledních 12 měsících zmenšuje rezervu nad kapacitou (na běh +{Math.round(cap.margins.session * 100)} %, na týden +{Math.round(cap.margins.week * 100)} %).</p>
      )}
    </section>
  )
}

// Feedback railway#83 — Dnes: today's room against the 7-day room, per run channel.
// One bar per channel on the 7-day scale: what the last 7 days used (solid), what
// today may still add (lime, = the Trénink "dnes max"), what is left of the 7-day
// ceiling after that (faint), and the ceiling itself (white tick).
export function CapacityMini({ cap, week, className = "mt-4 border-t border-white/10 pt-4" }: { cap: any; week?: any; className?: string }) {
  if (!cap?.channels) return null
  return (
    <div className={className}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><p className="t-label !text-fg-3">Kapacita · dnes vs. 7 dní</p><InfoDot text={MI.capacity} label="Kapacita" /></span>
        <span className="text-[11px] font-bold" style={{ color: readinessCol(readinessPct(cap.readiness)) }}>připravenost {readinessPct(cap.readiness)} %</span>
      </div>
      <div className="mt-3 grid gap-3.5 sm:grid-cols-2">
        {RUN_CH.map((id) => {
          const c = cap.channels[id]
          if (!c) return null
          const g = week?.[id]
          const wk = c.week
          const done = g?.done7 ?? wk?.now ?? null
          const ceil = g?.ceiling7 ?? wk?.ceiling ?? null
          const today = g?.todayMax ?? null
          if (done == null || ceil == null || ceil <= 0) {
            return (
              <div key={id}>
                <div className="mb-1 flex justify-between text-[11px]"><span className="text-fg">{c.label}</span><span className="text-fg-3">poznáváme</span></div>
                <div className="h-2.5 rounded-full bg-white/[.08]" />
              </div>
            )
          }
          const scale = Math.max(ceil, done + (today ?? 0)) * 1.06
          const W = (v: number) => `${Math.max(0, (v / scale) * 100)}%`
          const over = done > ceil
          const col = (TONE as any)[toneOf(ceil ? done / ceil : null, 0)] || TONE.ok
          const rest = Math.max(0, ceil - done - (today ?? 0))
          return (
            <div key={id}>
              <div className="mb-1.5 flex items-baseline justify-between gap-2 text-[11px]">
                <span className="text-[12px] font-semibold text-fg">{c.label}</span>
                <span className="tabular-nums">
                  {today != null
                    ? <><span className="text-fg-3">dnes až </span><b className="text-[13px] text-accent">{num(today)}</b> <span className="text-fg-3">{c.unit}</span></>
                    : <span className="text-fg-3">{over ? "strop vyčerpán" : `zbývá ${num(Math.max(0, ceil - done))} ${c.unit}`}</span>}
                </span>
              </div>
              <div className="relative flex h-2.5 overflow-hidden rounded-full bg-white/[.06]">
                <i className="block h-full" style={{ width: W(Math.min(done, scale)), background: over ? TONE.alert : col, opacity: 0.9 }} />
                {today != null && today > 0 && <i className="block h-full" style={{ width: W(today), background: C.accent, backgroundImage: "repeating-linear-gradient(135deg, rgb(0 0 0 / .18) 0 3px, transparent 3px 6px)" }} />}
                {rest > 0 && <i className="block h-full bg-white/[.14]" style={{ width: W(rest) }} />}
                <i className="absolute inset-y-0 w-0.5 bg-fg" style={{ left: `calc(${(ceil / scale) * 100}% - 1px)` }} title="strop 7 dní" />
              </div>
              <p className="mt-1 tabular-nums text-[11px] text-fg-3">7 dní {num(done)} / strop {num(ceil)} {c.unit}{g?.left7 != null ? ` · zbývá ${num(g.left7)}` : ""}</p>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-3">
        <span className="flex items-center gap-1.5"><i className="h-2 w-3 rounded-sm" style={{ background: TONE.ok }} />posledních 7 dní</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-3 rounded-sm" style={{ background: C.accent }} />dnes k dispozici</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-3 rounded-sm bg-white/[.14]" />zbytek do stropu</span>
        <span className="flex items-center gap-1.5"><i className="h-3 w-0.5 bg-fg" />strop 7 dní</span>
      </div>
    </div>
  )
}

export const CAP_SIGNAL_IDS = ["cap_volume", "cap_intensity", "cap_descent", "cap_ascent", "cap_systemic", "cap_strength"]
