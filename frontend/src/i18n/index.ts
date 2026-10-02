// Starts the British English translation of the page when that language is chosen
// (see translator.ts). The dictionary (≈ a few hundred kB) loads only for English.
import { getLang, onLangChange } from "@/i18n/lang"
import { startTranslating, stopTranslating } from "@/i18n/translator"

let loaded: Promise<void> | null = null

function loadEn(): Promise<void> {
  if (!loaded) loaded = import("./en.json").then((m: any) => startTranslating(m.default || m))
  return loaded
}

/** Called before the first render: English pages render already translated. */
export async function bootI18n(): Promise<void> {
  document.documentElement.lang = getLang() === "en" ? "en-GB" : "cs"
  onLangChange((l) => {
    if (l === "en") void loadEn()
    else { stopTranslating(); location.reload() }   // the Czech originals come back cleanly with a reload
  })
  if (getLang() === "en") {
    try { await loadEn() } catch { /* the app stays Czech rather than not starting */ }
  }
}
