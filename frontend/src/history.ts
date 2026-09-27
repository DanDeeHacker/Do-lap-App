// Shared, prefetched daily quadrant history: one copy per runner feeds the Dnes
// history sheet, the Mechanika / Zátěž detail sheets and the Pohyb / Zátěž trend
// charts. The store (store.tsx) loads it right after the bootstrap and again
// whenever the assessment is recomputed (its computed_at changes), so the data
// is usually in memory before any chart opens. The last copy is also kept in
// localStorage, so even a fresh app start draws the charts at once while the
// revalidation runs in the background (stale-while-revalidate).
import { useSyncExternalStore } from "react"
import { api } from "@/api"

type Entry = { v: string; rows: any[] }

const mem = new Map<string, Entry>()
const latest = new Map<string, number>() // rid → sequence number of the newest request
const inflight = new Map<string, { v: string; p: Promise<void> }>()
const subs = new Set<() => void>()
let seq = 0
const LS_PREFIX = "doslap.qh."

function read(rid: string): Entry | undefined {
  let e = mem.get(rid)
  if (!e) {
    try {
      const raw = localStorage.getItem(LS_PREFIX + rid)
      const j = raw ? JSON.parse(raw) : null
      if (j && typeof j.v === "string" && Array.isArray(j.rows)) {
        e = j as Entry
        mem.set(rid, e)
      }
    } catch {
      /* storage blocked or corrupt: just fetch */
    }
  }
  return e
}

function emit() {
  subs.forEach((f) => f())
}

/** Make sure the history for `rid` matches assessment version `v` (its computed_at). */
export function loadQuadHistory(rid: string, v: string): Promise<void> {
  const cur = read(rid)
  if (cur && cur.v === v) return Promise.resolve()
  const f = inflight.get(rid)
  if (f && f.v === v) return f.p
  const n = ++seq
  latest.set(rid, n)
  const p = api
    .quadrantHistory(rid)
    .then((rows) => {
      if (latest.get(rid) !== n || !Array.isArray(rows)) return // a newer request superseded this one
      const e = { v, rows }
      mem.set(rid, e)
      try {
        localStorage.setItem(LS_PREFIX + rid, JSON.stringify(e))
      } catch {
        /* quota or blocked storage: the in-memory copy still serves this session */
      }
      emit()
    })
    .catch(() => {
      // keep whatever we had; with nothing at all, stop the charts' loading state
      if (latest.get(rid) === n && !read(rid)) {
        mem.set(rid, { v: "", rows: [] })
        emit()
      }
    })
    .finally(() => {
      if (inflight.get(rid)?.p === p) inflight.delete(rid)
    })
  inflight.set(rid, { v, p })
  return p
}

function subscribe(f: () => void) {
  subs.add(f)
  return () => {
    subs.delete(f)
  }
}

/** The runner's daily history rows, or null while nothing has loaded yet. */
export function useQuadHistory(rid: string | null | undefined): any[] | null {
  return useSyncExternalStore(subscribe, () => (rid ? read(rid)?.rows ?? null : null))
}

/** Forget every cached history (logout on a shared device). */
export function clearQuadHistory() {
  mem.clear()
  latest.clear()
  inflight.clear()
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i)
      if (k && k.startsWith(LS_PREFIX)) localStorage.removeItem(k)
    }
  } catch {
    /* ignore */
  }
  emit()
}
