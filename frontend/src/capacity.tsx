// Engine v3 ("Kapacitní") views of the per-runner capacity model: the full panel
// on the Zátěž tab and a compact weekly strip on Dnes (below the quadrant, which
// stays the first thing on the page).
import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { InfoDot, Label } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { fmtD } from "@/lib"
import { C, goodCol } from "@/tokens"

const CH_ORDER = ["volume", "intensity", "descent", "ascent", "systemic", "strength"] as const
const RUN_CH = ["volume", "intensity", "descent", "ascent"] as const
const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("cs-CZ"))
const TONE = { ok: C.ok, watch: C.watch, alert: C.alert, muted: C.fg3 }
const toneOf = (ratio: number | null | undefined, margin: number) =>
  ratio == null ? "muted" : ratio <= 1 + margin ? "ok" : ratio <= 1.3 ? "watch" : "alert"
const PART_LABEL: Record<string, string> = { hrv: "HRV pod normou", rhr: "klidový tep nad normou", sleep: "kratší nebo méně kvalitní spánek", soreness: "svalová bolest", fatigue: "únava", stress: "stres mimo trénink", session: "dnešní trénink" }
const BAND: Record<string, [string, string]> = {
  pod: ["pod obvyklým", TONE.muted], "obvyklé": ["obvyklé", TONE.ok], nad: ["nad obvyklým", TONE.watch], "výrazně nad": ["výrazně nad", TONE.alert],
}

export const readinessPct = (r: any) => (r?.score ?? Math.round((r?.today ?? 1) * 100)) as number
// railway#108 — green above 70 %, red below 40 %, as on the Dnes rings
export const readinessCol = (pct: number) => goodCol(pct)

export function Readiness({ r }: { r: any }) {
  const pct = readinessPct(r)
  const parts = Object.entries(r?.parts || {}).filter(([, v]) => (v as number) > 0.05) as [string, number][]
  const col = readinessCol(pct)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-full px-2.5 py-1 text-[12px] font-bold" style={{ background: `${col}1f`, color: col }}>Připravenost dnes {pct} %</span>
      {r?.afterSession?.drop ? (
        <span className="basis-full text-[11px] text-fg-2" data-testid="readiness-after">
          {r.afterSession.today ? `Po dnešním tréninku −${r.afterSession.drop} (ráno ${r.morningScore} %) · ${r.afterSession.today.band}` : `Včerejší náročný trénink ještě doznívá −${r.afterSession.drop}`} · zítra ji upřesní noční data
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
const FACTOR_LABEL: Record<string, string> = { hrv: "HRV", rhr: "Klidový tep", sleep: "Spánek", soreness: "Svalová bolest", fatigue: "Únava", stress: "Stres mimo trénink", session: "Dnešní trénink" }
const pctS = (v: number | null | undefined) => (v == null ? null : `${Math.round(v * 100)} %`)
const vs = (parts: (string | null | false)[]) => parts.filter(Boolean).join(" · ")
const pts1 = (v: number) => (Math.round(v * 10) / 10).toLocaleString("cs-CZ")

function factorReading(k: string, r: any): string | null {
  const i = r?.inputs || {}
  const n = i.night || {}, w = i.week || {}, b = i.base || {}, c = i.checkin
  if (k === "hrv") return n.hrv == null && w.hrv == null ? null : vs([n.hrv != null && `noc ${n.hrv} ms`, w.hrv != null && `7 nocí ${w.hrv} ms`, b.hrv != null && `obvykle ${b.hrv} ms`])
  if (k === "rhr") return n.rhr == null && w.rhr == null ? null : vs([n.rhr != null && `noc ${n.rhr}`, w.rhr != null && `7 nocí ${w.rhr}`, b.rhr != null && `obvykle ${b.rhr} tepů/min`])
  if (k === "sleep") {
    const q = c?.sleepQuality
    const line = vs([n.sleep != null && `poslední noc ${num(n.sleep)} h`, w.sleep != null && `3 noci ${num(w.sleep)} h`, b.sleep != null && `obvykle ${num(b.sleep)} h`,
      n.rest != null && `hluboký + REM ${pctS(n.rest)}${b.rest != null ? ` (obvykle ${pctS(b.rest)})` : ""}`, q != null && SLEEP_Q[q] && `vaše hodnocení: ${SLEEP_Q[q]}`])
    return line || null
  }
  if (k === "soreness") return c?.soreness == null ? null : `v check-inu ${c.soreness}/10 · snižuje od 6/10`
  if (k === "fatigue") return c?.fatigue == null ? null : `v check-inu ${c.fatigue}/10 · snižuje od 6/10`
  if (k === "stress") return c?.stress == null ? null : `v check-inu ${c.stress}/10 · snižuje od 6/10, počítá se 0,6×`
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
  const keys = ["hrv", "rhr", "sleep", "soreness", "fatigue", "stress", "session"]
  const part: Record<string, number> = r.parts || {}
  // every signal off its norm is listed, also one that adds nothing because stronger
  // signals already cover it (only the three strongest count)
  const lower = keys.filter((k) => (part[k] || 0) > 0).sort((a, b) => (eff[b] || 0) - (eff[a] || 0) || part[b] - part[a])
  // a signal counts only with today's reading: without last night's data the engine
  // doesn't judge HRV / resting HR / sleep, so they are listed apart, not as "in norm"
  const n = r.inputs.night || {}, ci = r.inputs.checkin
  const today = (k: string) => (k === "hrv" ? n.hrv != null : k === "rhr" ? n.rhr != null : k === "sleep" ? n.sleep != null || ci?.sleepQuality != null : ci?.[k] != null)
  const fine = keys.filter((k) => k !== "session" && !lower.includes(k) && today(k) && factorReading(k, r))
  const stale = ["hrv", "rhr", "sleep"].filter((k) => !lower.includes(k) && !today(k) && factorReading(k, r))
  const noCheckin = !ci
  const y = r.yesterday
  const delta = y?.known ? (r.morningScore ?? r.score) - y.score : null
  // day-over-day by each signal's own deviation (its points depend on the ranking with the
  // others, so a worse signal could otherwise read as "better" when a stronger one overtakes it)
  const yPart: Record<string, number> = y?.parts || {}
  const changes = y?.known
    ? keys.filter((k) => k !== "session").map((k) => [k, (part[k] || 0) - (yPart[k] || 0)] as [string, number]).filter(([, d]) => Math.abs(d) >= 0.05).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    : []
  const sess = r.afterSession?.drop || 0
  const row = (k: string, right: ReactNode, tone: string) => (
    <li key={k} className="flex items-start justify-between gap-3 py-2">
      <span className="min-w-0">
        <b className="text-[13px] font-bold text-fg">{FACTOR_LABEL[k]}</b>
        <span className="block text-[11px] leading-4 text-fg-3">{factorReading(k, r) || (k === "session" ? "" : "chybí data")}</span>
      </span>
      <span className="shrink-0 tabular-nums text-[13px] font-bold" style={{ color: tone }}>{right}</span>
    </li>
  )
  return (
    <div className="nest mt-3 p-3.5" data-testid="readiness-factors">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Co připravenost ovlivňuje</Label>
        {delta != null && (
          <span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${delta > 0 ? C.ok : delta < 0 ? C.alert : C.fg3}1f`, color: delta > 0 ? C.ok : delta < 0 ? C.alert : C.fg2 }}>
            {delta > 0 ? "▲" : delta < 0 ? "▼" : "▬"} ráno {delta > 0 ? `+${delta}` : delta < 0 ? delta : "beze změny"} oproti včerejšímu ránu ({y.score} %)
          </span>
        )}
      </div>
      {!r.known && !lower.length && (
        <p className="mt-2 text-[12px] leading-5 text-fg-2">Dnes zatím chybí noční data z hodinek{noCheckin ? " i check-in" : ""}, proto připravenost nic nesnižuje. Po synchronizaci se přepočítá.</p>
      )}
      {lower.length > 0 && (
        <>
          <p className="t-label mt-3 !text-fg-3">Snižuje ji</p>
          <ul className="divide-y divide-white/[.07]">
            {lower.map((k) => (eff[k] || 0) >= 0.5
              ? row(k, `−${pts1(eff[k])} b`, eff[k] >= 10 ? C.alert : C.watch)
              : row(k, <span className="block text-right">0 b<small className="block text-[10px] font-medium text-fg-3">překryto silnějšími</small></span>, C.fg3))}
          </ul>
        </>
      )}
      {fine.length > 0 && (
        <>
          <p className="t-label mt-3 !text-fg-3">Drží ji nahoře (v normě)</p>
          <ul className="divide-y divide-white/[.07]">
            {fine.map((k) => row(k, "0 b", C.ok))}
          </ul>
        </>
      )}
      {stale.length > 0 && (
        <>
          <p className="t-label mt-3 !text-fg-3">Bez dnešní noci (nezapočítává se)</p>
          <ul className="divide-y divide-white/[.07]">
            {stale.map((k) => row(k, "—", C.fg3))}
          </ul>
        </>
      )}
      {noCheckin && <p className="mt-2 text-[11px] leading-4 text-fg-3">Dnešní check-in zatím chybí, svalová bolest, únava a stres se proto nezapočítávají.</p>}
      {(changes.length > 0 || sess >= 0.5) && (
        <>
          <p className="t-label mt-3 !text-fg-3">Oproti včerejšímu ránu</p>
          <ul className="mt-1 space-y-1 text-[12px]">
            {changes.map(([k, d]) => (
              <li key={k} className="flex justify-between gap-2">
                <span className="text-fg-2">{FACTOR_LABEL[k]}</span>
                <b style={{ color: d < 0 ? C.ok : C.alert }}>{d < 0 ? "▲ blíž normě" : "▼ dál od normy"}</b>
              </li>
            ))}
            {sess >= 0.5 && (
              <li className="flex justify-between gap-2">
                <span className="text-fg-2">Dnešní trénink (od rána)</span>
                <b className="tabular-nums" style={{ color: C.alert }}>▼ −{sess} b</b>
              </li>
            )}
          </ul>
        </>
      )}
      <p className="mt-3 border-t border-white/[.07] pt-2.5 text-[11px] leading-4 text-fg-3">
        Připravenost = 100 − srážky. Nejsilnější signál se počítá celý, druhý z poloviny a třetí ze čtvrtiny, protože se signály často překrývají. Obvyklá hodnota je průměr vašich nocí 8–56 dní zpět a běžné kolísání do ±0,5 SD nic nestojí.
      </p>
    </div>
  )
}

// now vs ceiling on one bar; the ceiling marker sits where the bar would hit it
function HeadroomBar({ now, ceiling, tone }: { now: number | null; ceiling: number | null; tone: string }) {
  if (now == null || ceiling == null || ceiling <= 0) return <div className="h-2 rounded-full bg-white/[.08]" />
  const scale = Math.max(now, ceiling) * 1.08
  const col = (TONE as any)[tone] || TONE.ok
  return (
    <div className="relative h-2 rounded-full bg-white/[.08]">
      <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(now / scale) * 100}%`, background: col }} />
      <i className="absolute -inset-y-1 w-0.5 rounded-full bg-fg" style={{ left: `calc(${(ceiling / scale) * 100}% - 1px)` }} title="strop" />
    </div>
  )
}

const CH_NOTE: Record<string, string> = {
  strength: "Posilování: náročnost po tréninku (0–10) × minuty, cvičení nohou a celého těla plně, horní polovina těla z menší části. Hlídá prudké skoky, třeba první plyometrii po pauze. Těžké posilování nohou navíc na 24–48 hodin sníží v Tréninku strop minut v Z4+.",
  systemic: "Tep × čas ze všech aktivit (běh i jiné sporty) — objem a intenzita v jednom čísle. Co z ní zbývá, omezuje v Tréninku i dnešní kilometry a minuty v Z4+.",
}

// Feedback railway#53 — each channel box shows its headline (capacity vs 7 days) and
// keeps the rest behind a detail arrow. railway#56–#61: the charts that feed a channel
// (volume bars, HR zones and relative effort, cross-training, descent by slope) live in
// that channel's detail rather than as separate cards further down the page.
function ChannelRow({ id, c, margins, extra, open, onToggle }: { id: string; c: any; margins: any; extra?: ReactNode; open: boolean; onToggle: () => void }) {
  const wk = c.week
  const ses = c.session
  const wTone = toneOf(wk?.ratio, margins.week)
  const sTone = toneOf(ses?.ratio, margins.session)
  const why = !c.pts ? null : c.driver === "session" ? (id === "strength" ? "body za jedno posilování nad kapacitou" : "body za jeden běh nad kapacitou") : c.driver === "week" ? "body za 7 dní nad kapacitou" : c.driver === "latent" ? "body doznívajícího skoku" : null
  const hasDetail = !!(extra || (c.known && (ses || c.latent || c.pendingJump || CH_NOTE[id])))
  return (
    <div className={`nest p-3.5 transition ${open ? "md:col-span-full !border-accent/60" : ""}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm font-bold text-fg">{c.label}</b>
        <span className="grid size-5 place-items-center rounded-full bg-white/[.07] text-[11px] font-extrabold text-fg-2">{c.grade}</span>
        <span className="ml-auto text-right tabular-nums text-[12px] font-bold" style={{ color: c.pts ? C.watch : C.fg3 }}>
          {c.pts ? `+${c.pts} b` : "0 b"}
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
            <HeadroomBar now={wk.now} ceiling={wk.ceiling} tone={wTone} />
          </div>
        </>
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
          {c.known && ses && (
            <p className="text-[11px] text-fg-3">
              Nejnáročnější {id === "strength" ? "posilování" : "běh"} 7 dní ({fmtD(ses.date)}): <b style={{ color: (TONE as any)[sTone] }}>{num(ses.value)} {c.unit} · ×{num(ses.ratio)}</b> proti kapacitě {id === "strength" ? "jednoho posilování" : "jednoho běhu"} {num(ses.cap)}
              {(ses.readinessScore ?? 100) < 97 ? ` · připravenost ${ses.readinessScore} %` : ""}
            </p>
          )}
          {c.known && wk?.residual != null && (
            <p className="mt-1 text-[11px] text-fg-3">
              Nevstřebáno <b className="text-fg">{num(wk.residual)} {c.unit}</b> (týdenní ekvivalent, klesá každou noc) proti kapacitě {num(wk.cap)}
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
        {cap.zones7d ? `${cap.zones7d.runs} ${cap.zones7d.runs === 1 ? "běh" : cap.zones7d.runs < 5 ? "běhy" : "běhů"} · celkem ${total} min${cap.zones7d.exact ? "" : " · u běhů bez detailních dat odhad z průměrného tepu"}` : "Za posledních 7 dní žádný běh s tepem."}
        {" "}· max {cap.hrMaxMeasured ? `${cap.hrMax} (změřený)` : `≈ ${cap.hrMax} (odhad — změřený zadejte v profilu)`} · klid ≈ {cap.hrRest} tep/min · kanál intenzity = minuty v Z4+
      </p>
    </div>
  )
}

function RelativeEffort({ re }: { re: any }) {
  return (
    <div>
      <span className="flex items-center gap-1.5"><Label>Relativní úsilí posledních běhů</Label><InfoDot text={MI.relEffort} label="Relativní úsilí" /></span>
      {re.runs?.length ? (
        <div className="mt-2 divide-y divide-white/[.06]">
          {re.runs.map((r: any, i: number) => {
            const [bl, bc] = BAND[r.band] || ["málo historie", TONE.muted]
            return (
              <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[12px]">
                <span className="w-14 shrink-0 whitespace-nowrap tabular-nums text-[11px] text-fg-3">{fmtD(r.date)}</span>
                <span className="min-w-0 flex-1 truncate text-fg">{r.title || "Běh"}{r.km ? ` · ${num(r.km)} km` : ""}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="w-16 whitespace-nowrap text-right tabular-nums text-[11px] text-fg-2">{r.effort} j.z.</span>
                  <span className="min-w-[6.5rem] text-center"><span className="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ background: `${bc}1f`, color: bc }}>{bl}</span></span>
                  <span className="w-[5.5rem] whitespace-nowrap text-[11px]" style={{ color: (r.hrDelta ?? 0) > 0 ? TONE.watch : TONE.ok }}>
                    {r.hrDelta != null && Math.abs(r.hrDelta) >= 5 ? `tep při tempu ${r.hrDelta > 0 ? "+" : ""}${r.hrDelta}` : ""}
                  </span>
                </span>
              </div>
            )
          })}
        </div>
      ) : <p className="mt-2 text-xs text-fg-3">Zatím málo běhů s tepem.</p>}
      {re.week && (
        <p className="mt-2 text-[11px] text-fg-2">Týden: <b className="text-fg">{re.week.now} j.z.</b> · obvykle {re.week.lo}–{re.week.hi} · <b style={{ color: (BAND[re.week.band] || [])[1] }}>{(BAND[re.week.band] || [re.week.band])[0]}</b></p>
      )}
    </div>
  )
}

export function CapacityPanel({ cap, extra = {} }: { cap: any; extra?: Record<string, ReactNode> }) {
  const [open, setOpen] = useState("")
  if (!cap) return null
  const re = cap.relativeEffort || {}
  // intensity = minutes in Z4+, so its detail carries the HR zones and relative effort (railway#56/#57)
  const extras: Record<string, ReactNode> = {
    ...extra,
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
        {CH_ORDER.map((id) => cap.channels?.[id] && (id !== "strength" || cap.channels[id].known) && (
          <ChannelRow key={id} id={id} c={cap.channels[id]} margins={cap.margins} extra={extras[id]}
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
