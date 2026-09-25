// Engine v3 ("Kapacitní") views of the per-runner capacity model: the full panel
// on the Zátěž tab and a compact weekly strip on Dnes (below the quadrant, which
// stays the first thing on the page).
import { InfoDot, Label } from "@/ui"
import { METRIC_INFO as MI } from "@/metricinfo"
import { fmtD } from "@/lib"

const CH_ORDER = ["volume", "intensity", "descent", "ascent", "systemic"] as const
const RUN_CH = ["volume", "intensity", "descent", "ascent"] as const
const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("cs-CZ"))
const TONE = { ok: "#6ce6d3", watch: "#f6d69a", alert: "#e77a59", muted: "#71837b" }
const toneOf = (ratio: number | null | undefined, margin: number) =>
  ratio == null ? "muted" : ratio <= 1 + margin ? "ok" : ratio <= 1.3 ? "watch" : "alert"
const PART_LABEL: Record<string, string> = { hrv: "HRV", rhr: "klidový tep", sleep: "spánek", soreness: "svalová bolest", fatigue: "únava" }
const BAND: Record<string, [string, string]> = {
  pod: ["pod obvyklým", TONE.muted], "obvyklé": ["obvyklé", TONE.ok], nad: ["nad obvyklým", TONE.watch], "výrazně nad": ["výrazně nad", TONE.alert],
}

function Readiness({ r }: { r: any }) {
  const pct = Math.round((r?.today ?? 1) * 100)
  const parts = Object.entries(r?.parts || {}).filter(([, v]) => (v as number) > 0.05) as [string, number][]
  const col = pct >= 95 ? TONE.ok : pct >= 85 ? TONE.watch : TONE.alert
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: `${col}1f`, color: col }}>Připravenost dnes {pct} %</span>
      {parts.length ? parts.map(([k, v]) => (
        <span key={k} className="rounded-full bg-white/[.06] px-2 py-0.5 text-[10px] text-[#a9c2b9]" style={{ opacity: 0.55 + 0.45 * v }}>{PART_LABEL[k] || k} ↓</span>
      )) : <span className="text-[10px] text-[#71837b]">bez snížení</span>}
      <InfoDot text={MI.readiness} label="Připravenost" />
    </div>
  )
}

// now vs ceiling on one bar; the ceiling marker sits where the bar would hit it
function HeadroomBar({ now, ceiling, tone }: { now: number | null; ceiling: number | null; tone: string }) {
  if (now == null || ceiling == null || ceiling <= 0) return <div className="h-2 rounded-full bg-white/10" />
  const scale = Math.max(now, ceiling) * 1.08
  const col = (TONE as any)[tone] || TONE.ok
  return (
    <div className="relative h-2 rounded-full bg-white/10">
      <i className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(now / scale) * 100}%`, background: col }} />
      <i className="absolute -inset-y-1 w-0.5 bg-[#f1f8f1]" style={{ left: `calc(${(ceiling / scale) * 100}% - 1px)` }} title="strop" />
    </div>
  )
}

function ChannelRow({ id, c, margins }: { id: string; c: any; margins: any }) {
  const wk = c.week
  const ses = c.session
  const wTone = toneOf(wk?.ratio, margins.week)
  const sTone = toneOf(ses?.ratio, margins.session)
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[.02] p-3.5">
      <div className="flex items-center gap-2">
        <b className="text-sm text-[#f1f8f1]">{c.label}</b>
        <span className="rounded-full bg-white/[.06] px-1.5 py-0.5 text-[9px] font-bold text-[#9bb3aa]">{c.grade}</span>
        <span className="ml-auto font-mono text-[11px]" style={{ color: c.pts ? "#f6d69a" : "#71837b" }}>{c.pts ? `+${c.pts} b` : "0 b"}</span>
      </div>
      {!c.known ? (
        <p className="mt-2 text-[11px] text-[#71837b]">Kapacitu teprve poznáváme — stačí pár běhů{id === "intensity" ? " s tepem" : ""}.</p>
      ) : (
        <>
          {c.ceilingToday != null && id !== "systemic" && (
            <p className="mt-1.5 text-[12px] text-[#a9c2b9]">
              Dnes max na jeden běh <b className="text-[#f1f8f1]">{num(c.ceilingToday)} {c.unit}</b>
              <span className="text-[10px] text-[#71837b]"> · prokázáno {num(c.capSession)} {c.unit}</span>
            </p>
          )}
          {wk && (
            <div className="mt-2">
              <div className="mb-1 flex justify-between text-[10px] text-[#71837b]">
                <span>7 dní <b className="text-[#e7efe9]">{num(wk.now)}</b> / strop {num(wk.ceiling)} {c.unit}</span>
                <span>{wk.left > 0 ? `zbývá ${num(wk.left)}` : "strop vyčerpán"}</span>
              </div>
              <HeadroomBar now={wk.now} ceiling={wk.ceiling} tone={wTone} />
            </div>
          )}
          {ses && (
            <p className="mt-2 text-[10px] text-[#71837b]">
              Nejnáročnější běh 7 dní ({fmtD(ses.date)}): <b style={{ color: (TONE as any)[sTone] }}>{num(ses.value)} {c.unit} · ×{num(ses.ratio)}</b> proti kapacitě {num(ses.cap)}
              {ses.readiness < 0.99 ? ` · připravenost ${Math.round(ses.readiness * 100)} %` : ""}
            </p>
          )}
          {c.latent && <p className="mt-1 text-[10px] text-[#f6d69a]">Doznívá skok ×{num(c.latent.ratio)} z {fmtD(c.latent.date)}</p>}
        </>
      )}
    </div>
  )
}

export function CapacityPanel({ cap }: { cap: any }) {
  if (!cap) return null
  const re = cap.relativeEffort || {}
  return (
    <section className="mb-4 rounded-[24px] border border-[#f6d69a]/20 bg-[#0c201d] p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="flex items-center gap-1.5"><Label>Kapacita a dnešní stropy</Label><InfoDot text={MI.capacity} label="Kapacita" /></span>
          <p className="mt-1 max-w-xl text-xs leading-5 text-[#a9c2b9]">Zátěž proti tomu, co jste prokazatelně zvládli bez obtíží. Bílá čárka = strop (kapacita + rezerva, snížená podle dnešní připravenosti).</p>
        </div>
        <Readiness r={cap.readiness} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {CH_ORDER.map((id) => cap.channels?.[id] && <ChannelRow key={id} id={id} c={cap.channels[id]} margins={cap.margins} />)}
      </div>
      {cap.margins?.frailty > 1 && (
        <p className="mt-3 text-[10px] text-[#71837b]">Zranění v posledních 12 měsících zmenšuje rezervu nad kapacitou (na běh +{Math.round(cap.margins.session * 100)} %, na týden +{Math.round(cap.margins.week * 100)} %).</p>
      )}
      <div className="mt-5 grid gap-4 border-t border-white/10 pt-4 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <span className="flex items-center gap-1.5"><Label>Relativní úsilí posledních běhů</Label><InfoDot text={MI.relEffort} label="Relativní úsilí" /></span>
          {re.runs?.length ? (
            <div className="mt-2 divide-y divide-white/10">
              {re.runs.map((r: any, i: number) => {
                const [bl, bc] = BAND[r.band] || ["málo historie", TONE.muted]
                return (
                  <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[12px]">
                    <span className="w-14 shrink-0 whitespace-nowrap font-mono text-[11px] text-[#71837b]">{fmtD(r.date)}</span>
                    <span className="min-w-0 flex-1 truncate text-[#e7efe9]">{r.title || "Běh"}{r.km ? ` · ${num(r.km)} km` : ""}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="w-16 whitespace-nowrap text-right font-mono text-[11px] text-[#9bb3aa]">{r.effort} j.z.</span>
                      <span className="w-[5.5rem] text-center"><span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${bc}1f`, color: bc }}>{bl}</span></span>
                      <span className="w-[5.5rem] whitespace-nowrap text-[10px]" style={{ color: (r.hrDelta ?? 0) > 0 ? TONE.watch : TONE.ok }}>
                        {r.hrDelta != null && Math.abs(r.hrDelta) >= 5 ? `tep při tempu ${r.hrDelta > 0 ? "+" : ""}${r.hrDelta}` : ""}
                      </span>
                    </span>
                  </div>
                )
              })}
            </div>
          ) : <p className="mt-2 text-xs text-[#71837b]">Zatím málo běhů s tepem.</p>}
          {re.week && (
            <p className="mt-2 text-[11px] text-[#a9c2b9]">Týden: <b className="text-[#f1f8f1]">{re.week.now} j.z.</b> · obvykle {re.week.lo}–{re.week.hi} · <b style={{ color: (BAND[re.week.band] || [])[1] }}>{(BAND[re.week.band] || [re.week.band])[0]}</b></p>
          )}
        </div>
        <div>
          <span className="flex items-center gap-1.5"><Label>Tepové zóny</Label><InfoDot text={MI.hrZones} label="Tepové zóny" /></span>
          <div className="mt-2 grid grid-cols-5 gap-1 text-center">
            {(cap.zones || []).map((z: any) => (
              <div key={z.z} className={`rounded-lg px-1 py-1.5 ${z.z === "Z4" || z.z === "Z5" ? "bg-[#e77a59]/15" : "bg-white/[.05]"}`}>
                <b className="block text-[11px] text-[#f1f8f1]">{z.z}</b>
                <span className="font-mono text-[10px] text-[#9bb3aa]">{z.lo}–{z.hi}</span>
              </div>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-[#71837b]">max ≈ {cap.hrMax} · klid ≈ {cap.hrRest} tep/min · kanál intenzity = minuty v Z4+</p>
        </div>
      </div>
    </section>
  )
}

// Compact weekly headroom for Dnes — placed under the quadrant / recovery.
export function CapacityMini({ cap }: { cap: any }) {
  if (!cap?.channels) return null
  return (
    <div className="mt-4 border-t border-white/10 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5"><p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#71837b]">Kapacita · posledních 7 dní vs. strop</p><InfoDot text={MI.capacity} label="Kapacita" /></span>
        <span className="text-[10px] text-[#a9c2b9]">připravenost {Math.round((cap.readiness?.today ?? 1) * 100)} %</span>
      </div>
      <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
        {RUN_CH.map((id) => {
          const c = cap.channels[id]
          if (!c) return null
          const wk = c.week
          return (
            <div key={id}>
              <div className="mb-1 flex justify-between text-[11px]">
                <span className="text-[#e7efe9]">{c.label}</span>
                <span className="font-mono text-[10px] text-[#9bb3aa]">{wk ? `${num(wk.now)} / ${num(wk.ceiling)} ${c.unit}` : "poznáváme"}</span>
              </div>
              <HeadroomBar now={wk?.now ?? null} ceiling={wk?.ceiling ?? null} tone={toneOf(wk?.ratio, cap.margins?.week ?? 0.15)} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

export const CAP_SIGNAL_IDS = ["cap_volume", "cap_intensity", "cap_descent", "cap_ascent", "cap_systemic"]
