// v0.12.13 — the run's route (Deník → run detail). Loaded lazily with Leaflet, only for the runner
// themself (the server sends the route to no one else). OpenStreetMap tiles, darkened to the app's
// theme; the card shows a still preview (a map that pans under the thumb would trap the page
// scroll on a phone) and a tap opens it full-size to move and zoom.
import { useEffect, useRef } from "react"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import { C } from "@/tokens"

const TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
const ATTR = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'

export default function RouteMap({ route, interactive = false, height = 220 }: { route: [number, number][]; interactive?: boolean; height?: number | string }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!el.current || route.length < 2) return
    const map = L.map(el.current, {
      zoomControl: interactive, attributionControl: true, dragging: interactive, touchZoom: interactive,
      doubleClickZoom: interactive, scrollWheelZoom: interactive, boxZoom: false, keyboard: interactive,
    })
    L.tileLayer(TILES, { maxZoom: 18, attribution: ATTR, className: "route-tiles" }).addTo(map)
    const line = L.polyline(route, { color: C.ink, weight: 7, opacity: 0.55, interactive: false }).addTo(map)
    L.polyline(route, { color: C.accent, weight: 3.5, opacity: 1, interactive: false }).addTo(map)
    L.circleMarker(route[0], { radius: 6, color: C.ink, weight: 2, fillColor: C.ok, fillOpacity: 1, interactive: false }).addTo(map)
    L.circleMarker(route[route.length - 1], { radius: 6, color: C.ink, weight: 2, fillColor: C.fg, fillOpacity: 1, interactive: false }).addTo(map)
    map.fitBounds(line.getBounds(), { padding: [18, 18] })
    return () => { map.remove() }
  }, [route, interactive])
  return <div ref={el} className="route-map w-full overflow-hidden rounded-[14px]" style={{ height }} />
}
