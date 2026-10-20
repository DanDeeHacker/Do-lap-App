// Engagement for the owners' overview (Správa uživatelů → Zapojení; backend routers/usage.py):
// the seconds a tab is in the foreground and in use (2 minutes without any input stop the
// count), the tab's views, the app opens (a load or a return after 30 minutes away) and a few
// features' opens. Sent every minute and when the app goes to the background; never from the
// demo or while an owner views someone else's data. No content of what was viewed.
import { useEffect } from "react"
import { useLocation } from "react-router"
import { useApp } from "@/store"

const IDLE_MS = 2 * 60_000
const VISIT_GAP_MS = 30 * 60_000
const FLUSH_MS = 60_000
const LAST_KEY = "dl-usage-last"

type Buf = { tabs: Record<string, { s: number; v: number }>; opens: number }
let buf: Buf = { tabs: {}, opens: 0 }
let on = false
let tab: string | null = null
let since = 0                 // when the current stretch started counting (0 = not counting)
let lastAct = 0
let hiddenAt = 0
let timer = 0

const localDay = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function add(key: string, s: number, v: number) {
  const t = (buf.tabs[key] ||= { s: 0, v: 0 })
  t.s += s
  t.v += v
}

/** The pathname as a tab key: /app/training → training, /app/post/123 → post, /data → data. */
export function tabOf(pathname: string): string | null {
  const m = pathname.match(/^\/app\/([a-z]+)/)
  if (m) return m[1] === "messages" ? "care" : m[1]
  const r = pathname.match(/^\/(data|admin|engine)s?\b/)
  return r ? r[1] : null
}

function settle(now: number) {
  if (tab && since) {
    const end = Math.min(now, lastAct + IDLE_MS)
    if (end > since) add(tab, (end - since) / 1000, 0)
  }
  since = document.visibilityState === "visible" && on ? now : 0
}

function remember(now: number) {
  try { localStorage.setItem(LAST_KEY, String(now)) } catch { /* storage blocked */ }
}

function flush() {
  if (!on) return
  settle(Date.now())
  const body = buf
  if (!body.opens && !Object.keys(body.tabs).length) return
  buf = { tabs: {}, opens: 0 }
  const tabs = Object.fromEntries(Object.entries(body.tabs).map(([k, v]) => [k, { s: Math.round(v.s), v: v.v }]))
  fetch("/api/usage", { method: "POST", credentials: "same-origin", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ day: localDay(), hour: new Date().getHours(), opens: body.opens, tabs }) }).catch(() => { /* engagement is best-effort */ })
}

function activity() {
  const now = Date.now()
  if (now - lastAct > IDLE_MS) settle(now)        // back from idle: the idle gap doesn't count
  lastAct = now
  if (!since && document.visibilityState === "visible" && on) since = now
}

function visibility() {
  const now = Date.now()
  if (document.visibilityState === "hidden") {
    settle(now)
    since = 0
    hiddenAt = now
    remember(now)
    flush()
  } else {
    if (hiddenAt && now - hiddenAt > VISIT_GAP_MS) buf.opens += 1
    lastAct = now
    since = on ? now : 0
  }
}

function start() {
  if (on) return
  on = true
  const now = Date.now()
  let last = 0
  try { last = Number(localStorage.getItem(LAST_KEY)) || 0 } catch { /* storage blocked */ }
  if (now - last > VISIT_GAP_MS) buf.opens += 1     // a reload within a visit isn't a new open
  lastAct = now
  since = document.visibilityState === "visible" ? now : 0
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart", "scroll"]) window.addEventListener(ev, activity, { passive: true, capture: true })
  document.addEventListener("visibilitychange", visibility)
  window.addEventListener("pagehide", flush)
  timer = window.setInterval(() => { remember(Date.now()); flush() }, FLUSH_MS)
}

function stop() {
  if (!on) return
  flush()
  on = false
  since = 0
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart", "scroll"]) window.removeEventListener(ev, activity, { capture: true })
  document.removeEventListener("visibilitychange", visibility)
  window.removeEventListener("pagehide", flush)
  window.clearInterval(timer)
}

/** A feature opened (the goal planner, a report, the assistant …): counted, not timed. */
export function track(feature: string) {
  if (on) add(`f:${feature}`, 0, 1)
}

/** In the runner layout: tracks the signed-in runner, not the demo and not an owner's "view as". */
export function useUsageTracking() {
  const { me, viewing } = useApp()
  const { pathname } = useLocation()
  const active = !!me && me.role === "runner" && !me.guest && !viewing
  useEffect(() => {
    if (active) start()
    else stop()
  }, [active])
  useEffect(() => () => stop(), [])
  useEffect(() => {
    if (!on) return
    const now = Date.now()
    settle(now)
    tab = tabOf(pathname)
    if (tab) add(tab, 0, 1)
    since = document.visibilityState === "visible" ? now : 0
  }, [pathname, active])
}
