// The app's language: Czech (the source) or British English (translation request
// 2026-10-02). Chosen on the sign-up page, stored with the account and kept in the
// browser too, so the sign-up page itself and the shared demo follow it.
import { useEffect, useState } from "react"

export type Lang = "cs" | "en"
const KEY = "dl-lang"
const listeners = new Set<(l: Lang) => void>()

function read(): Lang {
  try {
    const v = localStorage.getItem(KEY)
    if (v === "en" || v === "cs") return v
  } catch { /* storage blocked */ }
  return "cs"
}

let current: Lang = read()

export const getLang = (): Lang => current

export function setLang(l: Lang) {
  if (l === current) return
  current = l
  try { localStorage.setItem(KEY, l) } catch { /* storage blocked */ }
  document.documentElement.lang = l === "en" ? "en-GB" : "cs"
  listeners.forEach((f) => f(l))
}

/** The account's stored choice wins over the browser's once the user is known. */
export function adoptAccountLang(l?: string | null) {
  if (l === "en" || l === "cs") setLang(l)
}

export function useLang(): Lang {
  const [l, setL] = useState<Lang>(current)
  useEffect(() => {
    listeners.add(setL)
    return () => { listeners.delete(setL) }
  }, [])
  return l
}

export function onLangChange(f: (l: Lang) => void) {
  listeners.add(f)
  return () => { listeners.delete(f) }
}
