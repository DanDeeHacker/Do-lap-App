// Auth + bootstrap store. Loads the signed-in user once, then the runner's
// full bootstrap bundle (same shape core.js's refreshDB used). Components read
// live data via useApp(); refresh() re-pulls after a mutation.
//
// Tour mode (getting-started tutorial): startTour() swaps in the synthetic demo
// runner's data, with the demo runner renamed to the signed-in user, so every tab
// renders a realistic, personalised interface. `me.runner_id` then points at the
// demo runner (reads are allowed server-side, writes are not); `realMe` keeps the
// actual account.
//
// Guest mode (public demo, "Vyzkoušej hned!" on /auth): a read-only guest session
// whose `me.demo_rid` is the same tutorial runner. The store treats a guest as
// permanently touring; leaving the demo is a logout.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { api, ApiError, type Me } from "@/api"
import { clearQuadHistory, loadQuadHistory } from "@/history"

type Tour = { rid: string; boot: any }

type AppState = {
  me: Me | null
  realMe: Me | null
  boot: any | null
  loading: boolean
  error: string | null
  touring: boolean
  reloadMe: () => Promise<Me | null>
  refresh: () => Promise<void>
  logout: () => Promise<void>
  startTour: () => Promise<boolean>
  endTour: () => void
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [boot, setBoot] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tour, setTour] = useState<Tour | null>(null)

  const reloadMe = useCallback(async () => {
    try {
      const u = await api.authMe()
      setMe(u)
      return u
    } catch {
      setMe(null)
      return null
    }
  }, [])

  // the tour renames the demo runner to the signed-in user; a guest keeps "Ukázkový běžec"
  const personalise = useCallback((b: any) => (b && !me?.guest ? { ...b, runner: { ...(b.runner || {}), name: me?.name || b.runner?.name } } : b), [me?.name, me?.guest])

  const refresh = useCallback(async () => {
    if (tour) {
      try { setTour({ ...tour, boot: personalise(await api.bootstrap(tour.rid)) }) } catch { /* keep the old copy */ }
      return
    }
    const rid = me?.runner_id
    if (!rid) return
    // Clear any prior error up front so a retry (or a later refresh) shows the
    // loading state again instead of the stale error while the request is in flight.
    setError(null)
    try {
      setBoot(await api.bootstrap(rid))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Nepodařilo se načíst data")
    }
  }, [me?.runner_id, tour, personalise])

  const startTour = useCallback(async () => {
    const rid = me?.runner_id
    if (!rid) return false
    try {
      const d = await api.tutorialDemo(rid)
      const b = await api.bootstrap(d.runner_id)
      setTour({ rid: d.runner_id, boot: personalise(b) })
      return true
    } catch {
      return false
    }
  }, [me?.runner_id, personalise])
  const endTour = useCallback(() => { if (!me?.guest) setTour(null) }, [me?.guest])

  // guest: the demo runner is the only data there is, load it right away
  useEffect(() => {
    const rid = me?.guest ? me.demo_rid : undefined
    if (!rid) return
    setTour({ rid, boot: null })
    api.bootstrap(rid).then((b) => setTour({ rid, boot: b })).catch(() => setError("Ukázku se nepodařilo načíst"))
  }, [me?.guest, me?.demo_rid])

  const logout = useCallback(async () => {
    try {
      await api.authLogout()
    } catch {
      /* ignore */
    }
    setTour(null)
    setMe(null)
    setBoot(null)
    setError(null)
    clearQuadHistory()
  }, [])

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      await reloadMe()
      setLoading(false)
    })()
  }, [reloadMe])

  useEffect(() => {
    if (me?.runner_id) refresh()
  }, [me?.runner_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const shownMe = useMemo(() => (tour && me ? { ...me, runner_id: tour.rid } : me?.guest && me.demo_rid ? { ...me, runner_id: me.demo_rid } : me), [tour, me])
  const shownBoot = tour ? tour.boot : boot

  // Prefetch the daily history behind the trend charts as soon as the bootstrap
  // lands, and revalidate it whenever the assessment is recomputed (a sync, a
  // check-in, a new day), so the charts never wait when they open. The server
  // has usually precomputed it already, so this is a plain cache read.
  const histRid = shownMe?.runner_id
  const histVer = shownBoot?.assessment?.computed_at as string | undefined
  useEffect(() => {
    if (histRid && histVer) loadQuadHistory(histRid, histVer)
  }, [histRid, histVer])

  return (
    <Ctx.Provider value={{ me: shownMe, realMe: me, boot: shownBoot, loading, error, touring: !!tour || !!me?.guest, reloadMe, refresh, logout, startTour, endTour }}>
      {children}
    </Ctx.Provider>
  )
}

export function useApp() {
  const c = useContext(Ctx)
  if (!c) throw new Error("useApp mimo AppProvider")
  return c
}
