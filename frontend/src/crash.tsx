// Crash safety net (2026-10-09). A render error inside a tab used to leave the runner
// with a broken page and nothing in the server logs ("Trénink se nenačítá"). Now:
//  • TabBoundary catches errors inside the page content, keeps the shell (header,
//    navigation) usable and offers to load the part again;
//  • RouteError is the router's last resort for anything outside the content;
//  • every caught error (and uncaught window errors / promise rejections from our own
//    code) is posted to /api/client-errors, which writes one line to the deploy log.
// Only technical details are sent: message, stack, page path, area and the bundle name.
import { Component, type ErrorInfo, type ReactNode } from "react"
import { useRouteError } from "react-router"
import { runningBundle } from "@/updateCheck"

const MAX_REPORTS = 10
const sent = new Set<string>()

export function reportCrash(err: unknown, where: string) {
  try {
    const e = err instanceof Error ? err : new Error(typeof err === "string" ? err : JSON.stringify(err ?? "unknown"))
    const key = `${where}|${location.pathname}|${e.message}`
    if (sent.has(key) || sent.size >= MAX_REPORTS) return
    sent.add(key)
    void fetch("/api/client-errors", {
      method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: (e.message || String(e)).slice(0, 500), stack: (e.stack || "").slice(0, 4000),
        path: location.pathname.slice(0, 300), where, build: (runningBundle() || "dev").slice(0, 60),
        ua: navigator.userAgent.slice(0, 300),
      }),
    }).catch(() => {})
  } catch { /* reporting must never throw */ }
}

let installed = false
/** Uncaught errors and promise rejections from the app's own code (not extensions). */
export function installCrashReporting() {
  if (installed) return
  installed = true
  window.addEventListener("error", (ev) => {
    if (!ev.error || (ev.filename && !ev.filename.startsWith(location.origin))) return
    if (/ResizeObserver loop/.test(ev.message)) return
    reportCrash(ev.error, "window")
  })
  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason
    // failed API calls are already shown to the runner by the screens that made them
    if (r && typeof r === "object" && "status" in r) return
    reportCrash(r, "promise")
  })
}

function Fallback({ title, detail, onRetry }: { title: string; detail?: string; onRetry: () => void }) {
  return (
    <div className="card mx-auto mt-6 max-w-lg p-6 text-center" role="alert" data-testid="crash-fallback">
      <p className="font-serif text-2xl">{title}</p>
      <p className="mt-2 text-sm leading-6 text-fg-2">
        Něco se pokazilo při zobrazení. Chyba se nám automaticky odeslala, ostatní části aplikace fungují dál.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <button type="button" className="btn btn-primary btn-sm" onClick={onRetry}>Načíst znovu</button>
        <a href="/app/today" className="btn btn-secondary btn-sm">Na Dnes</a>
      </div>
      {detail && <p className="mt-4 break-words font-mono text-[11px] text-fg-3" translate="no">{detail}</p>}
    </div>
  )
}

/** Error boundary around the page content; keyed by the path, so moving to another
 *  tab starts clean. */
export class TabBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) { return { err } }
  componentDidCatch(err: Error, info: ErrorInfo) {
    reportCrash(Object.assign(err, { stack: `${err.stack || ""}\n${info.componentStack || ""}` }), "tab")
  }
  render() {
    if (this.state.err)
      return <Fallback title="Tuhle část se nepodařilo zobrazit" detail={this.state.err.message}
        onRetry={() => this.setState({ err: null })} />
    return this.props.children
  }
}

/** The router's errorElement: anything that breaks outside the page content. */
export function RouteError() {
  const err = useRouteError()
  reportCrash(err, "route")
  const msg = err instanceof Error ? err.message : undefined
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-5 text-fg">
      <Fallback title="Aplikaci se nepodařilo zobrazit" detail={msg} onRetry={() => location.reload()} />
    </div>
  )
}
