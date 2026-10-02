// British English for everything the app shows (translation request 2026-10-02).
//
// The app is written in Czech, and much of its text comes from the engine on the
// server (signals, guidance, reasons). Instead of threading a translation function
// through every component and every engine string, the rendered page is translated:
// each text node and the visible attributes (title, aria-label, placeholder, alt)
// are looked up in a fixed dictionary built from the source code (scripts/i18n).
// Internal values (session types, channel keys…) stay Czech, so nothing that
// compares them can break.
//
// Lookup order for a text: exact → with its numbers as placeholders → templates
// (strings built from variables, e.g. f"Bolest {site} ({pain}/10)") whose captured
// parts are translated in turn → its " · "-separated parts → its sentences. Numbers
// get a decimal point, Czech dates become British ones. A text the dictionary doesn't
// know stays as it is.
//
// Free text the runner or physiotherapist wrote (notes, messages) is never touched:
// it sits under translate="no" or data-no-i18n.
type Dict = { x: Record<string, string>; t: [string, string][] }

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE", "NOSCRIPT"])
const ATTRS = ["title", "aria-label", "placeholder", "alt"]
const CZ = /[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/
const LETTER = /[A-Za-zÀ-ž]/
const NUM = /[-−+]?\d+(?:[   ]\d{3})*(?:,\d+)?/g

let dict: Dict | null = null
let exact = new Map<string, string>()
let numTpl = new Map<string, string>()          // "Kapacita {} km" → "Capacity {0} km"
let rxTpl: { rx: RegExp; en: string; n: number; key: string }[] = []
let byWord = new Map<string, number[]>()        // a template's anchor word → its indices
const cache = new Map<string, string>()
const misses = new Set<string>()

const norm = (s: string) => s.replace(/[  ]/g, " ").replace(/\s+/g, " ").trim()
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

// ---------------------------------------------------------------- numbers and dates
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
const CZ_MONTH_GEN: Record<string, number> = {
  ledna: 0, února: 1, března: 2, dubna: 3, května: 4, června: 5, července: 6, srpna: 7, září: 8, října: 9, listopadu: 10, prosince: 11,
  leden: 0, únor: 1, březen: 2, duben: 3, květen: 4, červen: 5, červenec: 6, srpen: 7, říjen: 8, listopad: 9, prosinec: 11,
}
const CZ_DAYS: Record<string, string> = {
  pondělí: "Monday", úterý: "Tuesday", středa: "Wednesday", středu: "Wednesday", čtvrtek: "Thursday", pátek: "Friday",
  sobota: "Saturday", sobotu: "Saturday", neděle: "Sunday", neděli: "Sunday",
  po: "Mon", út: "Tue", st: "Wed", čt: "Thu", pá: "Fri", so: "Sat", ne: "Sun",
}

function numbersEn(s: string): string {
  return s
    // 2. 10. 2026 / 2. 10. → 2 Oct 2026 / 2 Oct
    .replace(/\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?(?!\d)/g, (m, d, mo, y) => {
      const k = +mo - 1
      if (k < 0 || k > 11 || +d < 1 || +d > 31) return m
      return `${+d} ${MONTHS[k]}${y ? ` ${y}` : ""}`
    })
    // 2. října 2026 → 2 October 2026
    .replace(/\b(\d{1,2})\.\s(ledna|února|března|dubna|května|června|července|srpna|září|října|listopadu|prosince)(\s\d{4})?/g,
      (_m, d, mo, y) => `${+d} ${MONTHS_LONG[CZ_MONTH_GEN[mo]]}${y || ""}`)
    // 7,4 → 7.4 ; 1 234 → 1,234
    .replace(/(\d)[   ](\d{3})(?!\d)/g, "$1,$2")
    .replace(/(\d),(\d)/g, "$1.$2")
}

function weekdaysEn(s: string): string {
  return s.replace(/(^|[^a-zà-ž])(pondělí|úterý|středa|středu|čtvrtek|pátek|sobota|sobotu|neděle|neděli)(?![a-zà-ž])/gi,
    (_m, pre, w) => pre + CZ_DAYS[w.toLowerCase()])
}

// ---------------------------------------------------------------- dictionary
export function loadDict(d: Dict) {
  dict = d
  exact = new Map()
  numTpl = new Map()
  rxTpl = []
  byWord = new Map()
  cache.clear()
  for (const [cs, en] of Object.entries(d.x)) exact.set(norm(cs), en)
  for (const [cs0, en] of d.t) {
    const cs = norm(cs0)
    if (!cs.includes("{}")) { exact.set(cs, en); continue }
    numTpl.set(cs, en)
    const parts = cs.split("{}")
    const lits = parts.map((p) => p.trim()).filter((p) => LETTER.test(p))
    if (!lits.length) continue                 // only placeholders: too greedy to match freely
    const rx = new RegExp("^" + parts.map(esc).join("(.+?)") + "$")
    const i = rxTpl.length
    rxTpl.push({ rx, en, n: parts.length - 1, key: cs })
    // index by the longest word of the literal parts
    const words = lits.join(" ").split(/[^A-Za-zÀ-ž]+/).filter((w) => w.length >= 3).map((w) => w.toLowerCase())
    const anchor = words.sort((a, b) => b.length - a.length)[0]
    if (anchor) {
      const arr = byWord.get(anchor) || []
      arr.push(i)
      byWord.set(anchor, arr)
    }
  }
}

const fill = (en: string, vals: string[]) => en.replace(/\{(\d+)\}/g, (_m, k) => vals[+k] ?? "")

function viaNumbers(s: string): string | null {
  const vals: string[] = []
  const key = s.replace(NUM, (m) => { vals.push(m); return "{}" })
  if (!vals.length) return null
  const en = numTpl.get(key)
  return en ? fill(en, vals.map(numbersEn)) : null
}

function viaTemplates(s: string, depth: number): string | null {
  const words = s.toLowerCase().split(/[^a-zà-ž]+/).filter((w) => w.length >= 3)
  const seen = new Set<number>()
  for (const w of words) {
    for (const i of byWord.get(w) || []) {
      if (seen.has(i)) continue
      seen.add(i)
      const t = rxTpl[i]
      const m = s.match(t.rx)
      if (!m) continue
      const vals = m.slice(1).map((v) => translate(v, depth + 1))
      return fill(t.en, vals)
    }
  }
  return null
}

function translateCore(s: string, depth: number): string | null {
  const hit = exact.get(s)
  if (hit != null) return hit
  const n = viaNumbers(s)
  if (n != null) return n
  if (depth < 3) {
    const t = viaTemplates(s, depth)
    if (t != null) return t
    // a list joined with " · " or ", " (labels, chips), then whole sentences
    for (const sep of [" · ", " – ", " — ", ": "]) {
      if (s.includes(sep)) {
        const parts = s.split(sep)
        const tr = parts.map((p) => translateCore(p.trim(), depth + 1))
        if (tr.some((x) => x != null)) return parts.map((p, k) => tr[k] ?? numbersEn(p.trim())).join(sep)
      }
    }
    const sents = s.split(/(?<=[.!?])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])/)
    if (sents.length > 1) {
      const tr = sents.map((p) => translateCore(p, depth + 1))
      if (tr.some((x) => x != null)) return sents.map((p, k) => tr[k] ?? p).join(" ")
    }
  }
  return null
}

/** British English for one text, or the text unchanged when the dictionary lacks it. */
export function translate(raw: string, depth = 0): string {
  if (!dict || !raw || !LETTER.test(raw)) return dict && raw && /\d,\d|\d\.\s?\d{1,2}\./.test(raw) ? numbersEn(raw) : raw
  const lead = raw.match(/^\s*/)![0]
  const trail = raw.match(/\s*$/)![0]
  const s = norm(raw)
  let out = cache.get(s)
  if (out === undefined) {
    const t = translateCore(s, depth)
    out = t != null ? t : numbersEn(weekdaysEn(s))
    if (t == null && CZ.test(s)) misses.add(s)
    cache.set(s, out)
  }
  return lead + out + trail
}

// ---------------------------------------------------------------- the page
const orig = new WeakMap<Node, string>()       // text node → its Czech text
const shown = new WeakMap<Node, string>()      // text node → what we wrote into it
const origAttr = new WeakMap<Element, Record<string, string>>()
let observer: MutationObserver | null = null
let pending = new Set<Node>()
let scheduled = false

const skipped = (el: Element | null) => !!el && (SKIP_TAGS.has(el.tagName) || !!el.closest("[translate='no'], [data-no-i18n]"))

function doText(n: Node) {
  const v = n.nodeValue || ""
  if (shown.get(n) === v) return              // our own write
  if (!LETTER.test(v) && !/\d/.test(v)) return
  if (skipped(n.parentElement)) return
  orig.set(n, v)
  const en = translate(v)
  if (en !== v) {
    shown.set(n, en)
    n.nodeValue = en
  }
}

function doAttrs(el: Element) {
  if (skipped(el) && !el.matches("input, textarea")) return
  for (const a of ATTRS) {
    const v = el.getAttribute(a)
    if (!v || !LETTER.test(v)) continue
    const rec = origAttr.get(el) || {}
    if (rec[`>${a}`] === v) continue
    const en = translate(v)
    rec[a] = v
    rec[`>${a}`] = en
    origAttr.set(el, rec)
    if (en !== v) el.setAttribute(a, en)
  }
}

function walk(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) { doText(root); return }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  const el = root as Element
  if (skipped(el)) return
  doAttrs(el)
  const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => {
      if (n.nodeType !== Node.ELEMENT_NODE || !skipped(n as Element)) return NodeFilter.FILTER_ACCEPT
      // a text field's placeholder is the app's text even though its value is not
      if ((n as Element).matches("input, textarea")) doAttrs(n as Element)
      return NodeFilter.FILTER_REJECT
    },
  })
  let n: Node | null = tw.nextNode()
  while (n) {
    if (n.nodeType === Node.TEXT_NODE) doText(n)
    else doAttrs(n as Element)
    n = tw.nextNode()
  }
}

function flush() {
  scheduled = false
  const nodes = pending
  pending = new Set()
  nodes.forEach((n) => n.isConnected && walk(n))
}

export function startTranslating(d: Dict) {
  loadDict(d)
  walk(document.body)
  document.title = translate(document.title)
  observer?.disconnect()
  observer = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "characterData") pending.add(m.target)
      else if (m.type === "attributes") pending.add(m.target)
      else m.addedNodes.forEach((n) => pending.add(n))
    }
    if (!scheduled) {
      scheduled = true
      // translate before the browser paints, so Czech never flashes
      queueMicrotask(flush)
    }
  })
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS })
}

export function stopTranslating() {
  observer?.disconnect()
  observer = null
}

/** Texts the dictionary didn't know (for the dictionary's next update). */
export function missing(): string[] {
  return [...misses]
}
if (typeof window !== "undefined") (window as any).__dlI18nMissing = missing
