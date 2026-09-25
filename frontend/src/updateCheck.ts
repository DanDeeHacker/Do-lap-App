// New-deployment detection. The app shell (index.html) is served with no-cache
// and names a content-hashed bundle (/assets/index-<hash>.js). A running app —
// especially one added to the home screen, which stays in memory and has no
// reload button — keeps executing the bundle it started with, so after a deploy
// it silently misses every new feature. Comparing the bundle the fresh shell
// names with the one this page runs tells us a new version is live.

const BUNDLE_RE = /<script[^>]+src="(\/assets\/[^"]+\.js)"/

export function runningBundle(): string | null {
  const s = document.querySelector('script[type="module"][src*="/assets/"]') as HTMLScriptElement | null
  return s ? new URL(s.src, location.origin).pathname : null
}

export async function newVersionAvailable(): Promise<boolean> {
  const current = runningBundle()
  if (!current) return false // dev server (no hashed bundle) — nothing to compare
  try {
    const r = await fetch(`/?_v=${Date.now()}`, { cache: "no-store", credentials: "same-origin" })
    if (!r.ok) return false
    const m = (await r.text()).match(BUNDLE_RE)
    return !!m && m[1] !== current
  } catch {
    return false // offline / transient — try again later
  }
}

const CHECK_EVERY_MS = 5 * 60 * 1000

/** Reload silently when the app comes back to the foreground (the runner hasn't
 * started typing yet); while it's in use, only call `onAvailable` so the UI can
 * offer a reload instead of discarding what's on screen. */
export function startUpdateWatcher(onAvailable: () => void): () => void {
  const onVisible = async () => {
    if (document.visibilityState === "visible" && (await newVersionAvailable())) location.reload()
  }
  const onPageShow = (e: PageTransitionEvent) => { if (e.persisted) void onVisible() }
  document.addEventListener("visibilitychange", onVisible)
  window.addEventListener("pageshow", onPageShow)
  const timer = window.setInterval(async () => {
    if (document.visibilityState === "visible" && (await newVersionAvailable())) onAvailable()
  }, CHECK_EVERY_MS)
  return () => {
    document.removeEventListener("visibilitychange", onVisible)
    window.removeEventListener("pageshow", onPageShow)
    window.clearInterval(timer)
  }
}
