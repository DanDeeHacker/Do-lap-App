// v0.12.14 — the run's route as a small outline in the run lists (Deník, Mechanika, Zátěž), the way
// Strava-like feeds (Endurain) let a run be recognised by its shape. The server sends only the
// shape (0–100, no coordinates) and only to the runner themself; runs without a stored route
// keep their icon.
import { useEffect, useState } from "react"
import { api } from "@/api"
import { useApp } from "@/store"

type Thumbs = Record<string, number[]>
let cache: { key: string; thumbs: Thumbs } | null = null
let inflight: { key: string; p: Promise<Thumbs> } | null = null

function load(rid: string, key: string): Promise<Thumbs> {
  if (cache?.key === key) return Promise.resolve(cache.thumbs)
  if (inflight?.key === key) return inflight.p
  const p = api.routeThumbs(rid).then((d: any) => {
    const thumbs: Thumbs = d?.thumbs || {}
    cache = { key, thumbs }
    return thumbs
  }).catch(() => ({} as Thumbs)).finally(() => { if (inflight?.key === key) inflight = null })
  inflight = { key, p }
  return p
}

/** {activity id: outline} for the signed-in runner's own runs (one request per assessment). */
export function useRouteThumbs(): Thumbs {
  const { me, boot } = useApp()
  const rid = me?.runner_id || ""
  const key = `${rid}|${boot?.assessment?.computed_at || ""}|${(boot?.activities || []).length}`
  const [t, setT] = useState<Thumbs>(cache?.key === key ? cache.thumbs : {})
  useEffect(() => {
    if (!rid) return
    let alive = true
    load(rid, key).then((x) => alive && setT(x))
    return () => { alive = false }
  }, [rid, key])
  return t
}

/** The outline in the list's icon tile; it takes the tile's colour (currentColor). */
export function RouteSvg({ pts, size = 24 }: { pts: number[]; size?: number }) {
  let d = ""
  for (let i = 0; i + 1 < pts.length; i += 2) d += `${i ? "L" : "M"}${pts[i]} ${pts[i + 1]}`
  return (
    <svg viewBox="-8 -8 116 116" width={size} height={size} aria-hidden="true" data-testid="route-thumb">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
