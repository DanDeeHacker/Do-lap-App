// Annotation mode — the in-app feedback loop. A toggle in the top bar turns it
// on; then a click anywhere in the app no longer acts on the app but opens a
// note pinned to that element. Notes are stored server-side (/api/annotations)
// and anchored by route + CSS path + the element's text, so they re-pin on
// screen and can be found in the code. backend/feedback_sync.py mirrors them
// for Claude Code, which implements them and marks them resolved.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { useLocation } from "react-router"
import { api } from "@/api"
import { useApp } from "@/store"
import { runningBundle } from "@/updateCheck"

export type Note = {
  id: number
  route: string
  selector: string | null
  anchorText: string | null
  context: Record<string, any>
  note: string
  kind: string
  status: "open" | "done" | "wontfix"
  resolution: string | null
  createdAt: string
  author: { name: string | null; role: string | null; isOwner: boolean }
  own?: boolean
}
type Draft = { el: Element; fx: number; fy: number; body: any }

const KINDS: [string, string][] = [["bug", "Chyba"], ["idea", "Návrh"], ["copy", "Text"], ["other", "Jiné"]]
const KIND_LABEL = Object.fromEntries(KINDS)
const STATUS_LABEL: Record<string, string> = { open: "otevřená", done: "vyřešená", wontfix: "nebude se řešit" }
const UI = "data-annot-ui" // our own overlay: never annotated, never blocked

type Ctx = {
  on: boolean
  setOn: (v: boolean) => void
  notes: Note[]
  setNotes: (f: (n: Note[]) => Note[]) => void
  owner: boolean
}
const AnnotateCtx = createContext<Ctx | null>(null)
export const useAnnotate = () => useContext(AnnotateCtx)!

export function AnnotateProvider({ children }: { children: ReactNode }) {
  const [on, setOn] = useState(false)
  const [notes, setNotesState] = useState<Note[]>([])
  const [owner, setOwner] = useState(false)
  useEffect(() => {
    api.annotations().then((d) => { setNotesState(d?.items || []); setOwner(!!d?.owner) }).catch(() => {})
  }, [])
  const setNotes = useCallback((f: (n: Note[]) => Note[]) => setNotesState(f), [])
  return <AnnotateCtx.Provider value={{ on, setOn, notes, setNotes, owner }}>{children}</AnnotateCtx.Provider>
}

export function AnnotateToggle() {
  const { on, setOn, notes } = useAnnotate()
  const { pathname } = useLocation()
  const here = notes.filter((n) => n.route === pathname && n.status === "open").length
  return (
    <button
      {...{ [UI]: "" }}
      onClick={() => setOn(!on)}
      aria-pressed={on}
      aria-label={on ? "Ukončit režim poznámek" : "Režim poznámek"}
      title={on ? "Ukončit režim poznámek (Esc)" : "Režim poznámek — klikněte kamkoli v aplikaci a nechte poznámku"}
      className={`relative grid size-9 place-items-center rounded-full transition ${on ? "bg-[#c7ff54] text-[#071313] ring-2 ring-[#071313]/15" : "bg-[#dcece7] text-[#193431] hover:bg-[#c7ff54]/70"}`}
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z" />
        <path d="M9 9.5h6M12 6.5v6" />
      </svg>
      {here > 0 && (
        <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-[#e77a59] px-1 text-[9px] font-bold leading-none text-white">{here}</span>
      )}
    </button>
  )
}

// ---- anchoring ---------------------------------------------------------------
const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
const squash = (s: string | null | undefined) => (s || "").replace(/\s+/g, " ").trim()

/** The element a click means: the whole button / link / chart, not the icon or
 * the word inside it. */
function pickTarget(el: Element): Element {
  return el.closest("button, a, input, select, textarea, label, [role=button], svg, img, table") || el
}

function cssPath(el: Element): string {
  const parts: string[] = []
  let cur: Element | null = el
  while (cur && cur !== document.body && parts.length < 16) {
    if (cur.id) {
      parts.unshift(`#${CSS.escape(cur.id)}`)
      return parts.join(" > ")
    }
    const parent: Element | null = cur.parentElement
    const name = cur.localName
    const same = parent ? Array.from(parent.children).filter((c) => c.localName === name) : []
    parts.unshift(same.length > 1 ? `${name}:nth-of-type(${same.indexOf(cur) + 1})` : name)
    cur = parent
  }
  return ["body", ...parts].join(" > ")
}

function textOf(el: Element): string {
  const h = el as HTMLElement & { placeholder?: string }
  return squash(h.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || h.placeholder || el.textContent).slice(0, 160)
}

/** The nearest section title above the element — tells Claude which card it is. */
function headingOf(el: Element): string | undefined {
  let a: Element | null = el.parentElement
  for (let i = 0; a && i < 10; a = a.parentElement, i++) {
    for (const h of Array.from(a.querySelectorAll("h1, h2, h3, h4, .font-serif, [class*='uppercase']"))) {
      if (h === el || el.contains(h) || h.contains(el)) continue // the clicked thing itself isn't its section
      const t = squash(h.textContent)
      if (t) return t.slice(0, 120)
    }
  }
  return undefined
}

/** Where a stored note sits on screen now: on its element when the element is
 * still there (and still says the same thing), else where it was clicked. */
function pinPoint(n: Note): { x: number; y: number; moved: boolean } | null {
  let el: Element | null = null
  try {
    el = n.selector ? document.querySelector(n.selector) : null
  } catch {
    el = null
  }
  const want = squash(n.anchorText).slice(0, 24)
  if (el && (!want || textOf(el).startsWith(want))) {
    const r = el.getBoundingClientRect()
    if (r.width || r.height) return { x: r.left + (n.context.fx ?? 0.5) * r.width, y: r.top + (n.context.fy ?? 0.5) * r.height, moved: false }
  }
  if (n.context.pageX != null) return { x: n.context.pageX - scrollX, y: n.context.pageY - scrollY, moved: true }
  return null
}

function popoverStyle(x: number, y: number, h = 250): React.CSSProperties {
  if (innerWidth < 640) return {} // phone: bottom sheet via classes
  const w = 320
  const left = Math.max(8, Math.min(x + 14, innerWidth - w - 8))
  const top = y + 14 + h > innerHeight - 8 ? Math.max(84, y - h - 14) : y + 14
  return { left, top, width: w }
}
const popoverCls =
  "fixed z-[80] rounded-2xl border border-white/10 bg-[#102724] p-3 text-[#f1f8f1] shadow-[0_18px_50px_rgb(0_0_0_/_0.45)] max-sm:inset-x-2 max-sm:bottom-[calc(76px+env(safe-area-inset-bottom))]"

// ---- the overlay ----------------------------------------------------------------
export function AnnotationLayer() {
  const { on, setOn, notes, setNotes, owner } = useAnnotate()
  const { pathname } = useLocation()
  const { boot } = useApp()
  const [hover, setHover] = useState<DOMRect | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [showDone, setShowDone] = useState(false)
  const [, setTick] = useState(0)
  const engine = boot?.assessment?.engineMode || boot?.runner?.engine_mode

  // While on: clicks annotate instead of acting on the app.
  useEffect(() => {
    if (!on) return
    const ours = (t: EventTarget | null) => t instanceof Element && !!t.closest(`[${UI}]`)
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return
      const t = e.target
      setHover(t instanceof Element && !ours(t) ? pickTarget(t).getBoundingClientRect() : null)
    }
    const swallow = (e: Event) => {
      if (ours(e.target)) return
      e.stopPropagation()
      if (e.type === "mousedown") e.preventDefault() // no focus / text selection
    }
    const click = (e: MouseEvent) => {
      if (ours(e.target) || !(e.target instanceof Element)) return
      e.preventDefault()
      e.stopPropagation()
      e.stopImmediatePropagation()
      const el = pickTarget(e.target)
      const r = el.getBoundingClientRect()
      const fx = clamp01(r.width ? (e.clientX - r.left) / r.width : 0.5)
      const fy = clamp01(r.height ? (e.clientY - r.top) / r.height : 0.5)
      setOpenId(null)
      // phone: the note sheet covers the bottom of the screen — keep the element in view
      if (innerWidth < 640) requestAnimationFrame(() => el.scrollIntoView({ block: "center", behavior: "smooth" }))
      setDraft({
        el, fx, fy,
        body: {
          route: location.pathname, selector: cssPath(el), anchorText: textOf(el),
          context: {
            heading: headingOf(el), tag: el.localName, fx: Math.round(fx * 1000) / 1000, fy: Math.round(fy * 1000) / 1000,
            pageX: Math.round(e.clientX + scrollX), pageY: Math.round(e.clientY + scrollY), vw: innerWidth, vh: innerHeight,
            device: innerWidth < 640 ? "phone" : innerWidth < 1024 ? "tablet" : "desktop",
            bundle: runningBundle() || "dev", engine,
          },
        },
      })
    }
    window.addEventListener("pointermove", move, true)
    window.addEventListener("pointerdown", swallow, true)
    window.addEventListener("mousedown", swallow, true)
    window.addEventListener("click", click, true)
    return () => {
      window.removeEventListener("pointermove", move, true)
      window.removeEventListener("pointerdown", swallow, true)
      window.removeEventListener("mousedown", swallow, true)
      window.removeEventListener("click", click, true)
      setHover(null)
      setDraft(null)
      setOpenId(null)
    }
  }, [on, engine])

  // Esc: close what's open, else leave the mode.
  useEffect(() => {
    if (!on) return
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      if (draft) setDraft(null)
      else if (openId != null) setOpenId(null)
      else setOn(false)
    }
    window.addEventListener("keydown", key)
    return () => window.removeEventListener("keydown", key)
  }, [on, draft, openId, setOn])

  // Pins follow their elements through scrolling, resizing and late-loading content.
  useEffect(() => {
    if (!on) return
    let raf = 0
    const bump = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setTick((t) => t + 1))
    }
    window.addEventListener("scroll", bump, { capture: true, passive: true })
    window.addEventListener("resize", bump)
    const iv = window.setInterval(bump, 700)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener("scroll", bump, true)
      window.removeEventListener("resize", bump)
      window.clearInterval(iv)
    }
  }, [on])

  useEffect(() => { setDraft(null); setOpenId(null) }, [pathname])

  if (!on) return null
  const here = notes.filter((n) => n.route === pathname).sort((a, b) => a.id - b.id)
  const numbered = here.map((n, i) => ({ n, num: i + 1 }))
  const shown = numbered.filter(({ n }) => showDone || n.status === "open")
  const openNote = here.find((n) => n.id === openId) || null
  const draftRect = draft && draft.el.isConnected ? draft.el.getBoundingClientRect() : null
  const draftPt = draftRect ? { x: draftRect.left + draft!.fx * draftRect.width, y: draftRect.top + draft!.fy * draftRect.height } : null
  const openPt = openNote ? pinPoint(openNote) : null

  return (
    <>
      <div {...{ [UI]: "" }} className="fixed inset-x-0 top-[calc(76px+env(safe-area-inset-top))] z-[75] flex justify-center px-3">
        <div className="flex max-w-full items-center gap-2 rounded-full border border-[#c7ff54]/40 bg-[#0c201d] py-1.5 pl-3.5 pr-1.5 text-[11px] text-[#f1f8f1] shadow-lg">
          <span className="size-2 shrink-0 animate-pulse rounded-full bg-[#c7ff54]" />
          <span className="min-w-0 truncate"><b>Režim poznámek</b><span className="hidden sm:inline"> — klikněte na libovolné místo a napište, co změnit</span></span>
          <label className="flex shrink-0 cursor-pointer items-center gap-1 text-[10px] text-[#a9c2b9]">
            <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} className="accent-[#c7ff54]" />vyřešené
          </label>
          <button onClick={() => setOn(false)} className="shrink-0 rounded-full bg-[#c7ff54] px-3 py-1 font-bold text-[#071313]">Hotovo</button>
        </div>
      </div>

      {hover && !draft && (
        <div className="pointer-events-none fixed z-[70] rounded-lg border-2 border-[#c7ff54] bg-[#c7ff54]/[.06] transition-all duration-75"
          style={{ left: hover.left - 3, top: hover.top - 3, width: hover.width + 6, height: hover.height + 6 }} />
      )}
      {draftRect && (
        <div className="pointer-events-none fixed z-[70] rounded-lg border-2 border-dashed border-[#c7ff54]"
          style={{ left: draftRect.left - 3, top: draftRect.top - 3, width: draftRect.width + 6, height: draftRect.height + 6 }} />
      )}

      {shown.map(({ n, num }) => {
        const p = pinPoint(n)
        if (!p || p.y < 60 || p.y > innerHeight + 20) return null
        const col = n.status === "open" ? (n.own === false ? "bg-[#f6d69a] text-[#3a2a12]" : "bg-[#c7ff54] text-[#071313]") : "bg-[#5f7268] text-white"
        return (
          <button
            key={n.id}
            {...{ [UI]: "" }}
            onClick={() => { setDraft(null); setOpenId(openId === n.id ? null : n.id) }}
            title={n.note}
            aria-label={`Poznámka ${num}`}
            className={`fixed z-[72] grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full rounded-bl-none text-[11px] font-extrabold shadow-[0_4px_14px_rgb(0_0_0_/_0.35)] ring-2 ring-[#071313]/70 ${col} ${p.moved ? "outline-dashed outline-2 outline-offset-2 outline-[#c7ff54]/60" : ""} ${openId === n.id ? "scale-110" : ""}`}
            style={{ left: p.x, top: p.y }}
          >
            {n.status === "done" ? "✓" : num}
          </button>
        )
      })}

      {draft && draftPt && (
        <DraftCard
          at={draftPt}
          anchor={draft.body.anchorText || `<${draft.body.context.tag}>`}
          onCancel={() => setDraft(null)}
          onSave={async (note, kind) => {
            const created = await api.createAnnotation({ ...draft.body, note, kind })
            setNotes((ns) => [created, ...ns])
            setDraft(null)
          }}
        />
      )}
      {openNote && (
        <NoteCard
          note={openNote}
          num={numbered.find((x) => x.n.id === openNote.id)!.num}
          at={openPt}
          showAuthor={owner && openNote.own === false}
          onClose={() => setOpenId(null)}
          onChange={(u) => setNotes((ns) => ns.map((x) => (x.id === u.id ? u : x)))}
          onDelete={() => { setNotes((ns) => ns.filter((x) => x.id !== openNote.id)); setOpenId(null) }}
        />
      )}
    </>
  )
}

function KindPicker({ kind, setKind }: { kind: string; setKind: (k: string) => void }) {
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Typ poznámky">
      {KINDS.map(([k, label]) => (
        <button key={k} role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
          className={`rounded-full px-2.5 py-1 text-[10px] font-bold transition ${kind === k ? "bg-[#c7ff54] text-[#071313]" : "bg-white/[.06] text-[#a9c2b9] hover:bg-white/[.1]"}`}>
          {label}
        </button>
      ))}
    </div>
  )
}

function DraftCard({ at, anchor, onCancel, onSave }: {
  at: { x: number; y: number }; anchor: string; onCancel: () => void; onSave: (note: string, kind: string) => Promise<void>
}) {
  const [text, setText] = useState("")
  const [kind, setKind] = useState("idea")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const ta = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { ta.current?.focus() }, [])
  const save = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    setErr(null)
    try {
      await onSave(text.trim(), kind)
    } catch (e: any) {
      setErr(e?.message || "Poznámku se nepodařilo uložit.")
      setBusy(false)
    }
  }
  return (
    <>
      <span {...{ [UI]: "" }} className="pointer-events-none fixed z-[72] size-3 -translate-x-1/2 -translate-y-1/2 animate-ping rounded-full bg-[#c7ff54]" style={{ left: at.x, top: at.y }} />
      <div {...{ [UI]: "" }} className={popoverCls} style={popoverStyle(at.x, at.y)} role="dialog" aria-label="Nová poznámka">
        <p className="font-mono text-[9px] uppercase tracking-[.16em] text-[#91b7a9]">Nová poznámka</p>
        <p className="mt-1 truncate text-[11px] text-[#a9c2b9]" title={anchor}>k prvku „{anchor}“</p>
        <div className="mt-2"><KindPicker kind={kind} setKind={setKind} /></div>
        <textarea
          ref={ta}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void save() }}
          maxLength={4000}
          rows={4}
          placeholder="Co tu změnit, co nefunguje, co chybí…"
          className="mt-2 w-full resize-y rounded-xl border border-white/10 bg-black/25 p-2.5 text-[13px] leading-5 text-[#f1f8f1] placeholder:text-[#5f7268] focus:border-[#c7ff54]/60 focus:outline-none"
        />
        {err && <p className="mt-1 text-[11px] text-[#f6b89f]">{err}</p>}
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="hidden text-[9px] text-[#5f7268] sm:inline">⌘/Ctrl + Enter uloží</span>
          <span className="ml-auto flex gap-2">
            <button onClick={onCancel} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#a9c2b9]">Zrušit</button>
            <button onClick={() => void save()} disabled={!text.trim() || busy} className="rounded-full bg-[#c7ff54] px-3.5 py-1.5 text-[11px] font-bold text-[#071313] disabled:opacity-40">{busy ? "Ukládám…" : "Uložit"}</button>
          </span>
        </div>
      </div>
    </>
  )
}

function NoteCard({ note, num, at, showAuthor, onClose, onChange, onDelete }: {
  note: Note; num: number; at: { x: number; y: number } | null; showAuthor: boolean
  onClose: () => void; onChange: (n: Note) => void; onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(note.note)
  const [kind, setKind] = useState(note.kind)
  const [confirmDel, setConfirmDel] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setEditing(false); setText(note.note); setKind(note.kind); setConfirmDel(false) }, [note.id, note.note, note.kind])
  const patch = async (body: any) => {
    setErr(null)
    try {
      onChange(await api.updateAnnotation(note.id, body))
      setEditing(false)
    } catch (e: any) {
      setErr(e?.message || "Změnu se nepodařilo uložit.")
    }
  }
  const del = async () => {
    try {
      await api.deleteAnnotation(note.id)
      onDelete()
    } catch (e: any) {
      setErr(e?.message || "Poznámku se nepodařilo smazat.")
    }
  }
  const when = new Date(note.createdAt).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })
  return (
    <div {...{ [UI]: "" }} className={popoverCls} style={at ? popoverStyle(at.x, at.y, 220) : { left: 16, top: 96, width: 320 }} role="dialog" aria-label={`Poznámka ${num}`}>
      <div className="flex items-center gap-2">
        <span className="grid size-6 place-items-center rounded-full bg-[#c7ff54] text-[11px] font-extrabold text-[#071313]">{num}</span>
        <span className="rounded-full bg-white/[.06] px-2 py-0.5 text-[10px] font-bold text-[#c9dcd4]">{KIND_LABEL[note.kind] || note.kind}</span>
        <span className={`text-[10px] ${note.status === "open" ? "text-[#c7ff54]" : "text-[#91b7a9]"}`}>{STATUS_LABEL[note.status]}</span>
        <button onClick={onClose} aria-label="Zavřít" className="ml-auto grid size-6 place-items-center rounded-full text-[#91b7a9] hover:bg-white/[.06]">×</button>
      </div>
      {editing ? (
        <>
          <div className="mt-2"><KindPicker kind={kind} setKind={setKind} /></div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} rows={4} autoFocus
            className="mt-2 w-full resize-y rounded-xl border border-white/10 bg-black/25 p-2.5 text-[13px] leading-5 text-[#f1f8f1] focus:border-[#c7ff54]/60 focus:outline-none" />
        </>
      ) : (
        <p className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap text-[13px] leading-5">{note.note}</p>
      )}
      {note.resolution && <p className="mt-2 rounded-lg bg-black/25 px-2 py-1.5 text-[11px] leading-4 text-[#9bd8c6]">Vyřešeno: {note.resolution}</p>}
      <p className="mt-2 text-[10px] text-[#71837b]">{when}{showAuthor ? ` · ${note.author.name || "?"} (${note.author.role || "?"})` : ""}{note.anchorText ? ` · „${note.anchorText.slice(0, 40)}${note.anchorText.length > 40 ? "…" : ""}“` : ""}</p>
      {err && <p className="mt-1 text-[11px] text-[#f6b89f]">{err}</p>}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {editing ? (
          <>
            <button onClick={() => void patch({ note: text.trim(), kind })} disabled={!text.trim()} className="rounded-full bg-[#c7ff54] px-3 py-1.5 text-[11px] font-bold text-[#071313] disabled:opacity-40">Uložit</button>
            <button onClick={() => { setEditing(false); setText(note.note); setKind(note.kind) }} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#a9c2b9]">Zrušit</button>
          </>
        ) : confirmDel ? (
          <>
            <span className="text-[11px] text-[#f6b89f]">Opravdu smazat?</span>
            <button onClick={() => void del()} className="rounded-full bg-[#e77a59] px-3 py-1.5 text-[11px] font-bold text-white">Smazat</button>
            <button onClick={() => setConfirmDel(false)} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#a9c2b9]">Ne</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#c9dcd4]">Upravit</button>
            <button onClick={() => void patch({ status: note.status === "open" ? "done" : "open" })} className="rounded-full bg-white/[.06] px-3 py-1.5 text-[11px] font-bold text-[#c9dcd4]">
              {note.status === "open" ? "Označit vyřešené" : "Znovu otevřít"}
            </button>
            <button onClick={() => setConfirmDel(true)} className="ml-auto rounded-full px-2.5 py-1.5 text-[11px] font-bold text-[#e77a59] hover:bg-[#e77a59]/10">Smazat</button>
          </>
        )}
      </div>
    </div>
  )
}
