// Auth + bootstrap store. Loads the signed-in user once, then the runner's
// full bootstrap bundle (same shape core.js's refreshDB used). Components read
// live data via useApp(); refresh() re-pulls after a mutation.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { api, ApiError, type Me } from "@/api"

type AppState = {
  me: Me | null
  boot: any | null
  loading: boolean
  error: string | null
  reloadMe: () => Promise<Me | null>
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [boot, setBoot] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  const refresh = useCallback(async () => {
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
  }, [me?.runner_id])

  const logout = useCallback(async () => {
    try {
      await api.authLogout()
    } catch {
      /* ignore */
    }
    setMe(null)
    setBoot(null)
    setError(null)
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
  }, [me?.runner_id, refresh])

  return (
    <Ctx.Provider value={{ me, boot, loading, error, reloadMe, refresh, logout }}>{children}</Ctx.Provider>
  )
}

export function useApp() {
  const c = useContext(Ctx)
  if (!c) throw new Error("useApp mimo AppProvider")
  return c
}
