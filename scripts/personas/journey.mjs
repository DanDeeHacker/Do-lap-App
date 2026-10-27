// Simulated runners in a real browser (owner request 2026-10-27, personas stages 1 and 2).
//
// Steps the personas on staging through simulated days (backend app/personas) and, on the days a
// persona would open the app, signs a browser in as that persona and visits the moments of the
// day: the morning (Dnes, the check-in, Trénink) and the evening (the run's detail, a tab the
// persona likes). On every page it checks for crashes, server errors, slow loads and Czech text
// in the English version, files what breaks as notes (POST /api/personas/findings), and writes a
// journal of screens (text + screenshot) for the AI review (scripts/personas/REVIEW.md).
//
//   DOSSLAP_PERSONA_TOKEN=… node scripts/personas/journey.mjs --base https://<staging> --days 7
//   node scripts/personas/journey.mjs file findings.json --base https://<staging>   (AI review notes)
//
// Options: --persona tereza (default all), --days N (simulated days per persona), --out DIR,
// --lang cs|en|mix (mix: mornings in Czech, evenings in English), --no-ui (simulation only).
// Playwright comes from the environment (NODE_PATH, or the project's node_modules).
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const args = process.argv.slice(2)
const flag = (k, d) => { const i = args.indexOf(`--${k}`); return i >= 0 ? args[i + 1] : d }
const has = (k) => args.includes(`--${k}`)
const BASE = (flag("base", process.env.DOSSLAP_STAGING_URL || "http://127.0.0.1:8766")).replace(/\/$/, "")
const TOKEN = process.env.DOSSLAP_PERSONA_TOKEN || ""
const OUT = flag("out", path.resolve("persona-journal"))
const DAYS = Number(flag("days", "7"))
const LANG = flag("lang", "mix")
const H = { "X-Persona-Token": TOKEN, "Content-Type": "application/json" }

// Czech that may legitimately stay in the English version: names and the persona's own data
// (activity titles from the watch, the race's name) — everything else with Czech letters is a leak
const ALLOW = [/Došlap/i, /dosslap/i, /\(persona\)/, /Tereza|Martin|Jana|Eva|Pavel/, /Praha|Pražský podzimní maraton/,
  /Lehký běh|Rozklusání|Dlouhý běh|Tempový běh|Intervaly|Lesní běh|Dlouhý běh v kopcích|Kolo|Plavání|Posilování/,
  /Achillova šlacha/]
const CZ = /[ěščřžůťďňĚŠČŘŽŮŤĎŇ]/

async function api(method, url, body) {
  const r = await fetch(BASE + url, { method, headers: H, body: body ? JSON.stringify(body) : undefined })
  const text = await r.text()
  let data = null
  try { data = JSON.parse(text) } catch { data = text }
  if (!r.ok) throw new Error(`${method} ${url} → ${r.status}: ${typeof data === "string" ? data.slice(0, 200) : JSON.stringify(data).slice(0, 200)}`)
  return data
}

function rng(seed) {           // small deterministic generator, so a rerun visits the same days
  let s = 0
  for (const c of seed) s = (s * 31 + c.charCodeAt(0)) >>> 0
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296 }
}

function wantsVisit(p, run, day, r) {
  const ev = (p.events || []).some((e) => day.day >= e.from - 1 && day.day <= e.to + 1)
  const monday = new Date(run.simDate + "T12:00:00").getDay() === 1
  return ev || monday || r() < (run.behaviour?.open ?? 0.7) * 0.35
}

async function fileFindings(persona, simDate, items, source = "synthetic") {
  if (!items.length) return null
  const res = await api("POST", "/api/personas/findings", { persona, simDate, source, items: items.slice(0, 10) })
  console.log(`  ${persona} ${simDate}: ${items.length} nálezů →`, JSON.stringify(res))
  return res
}

async function visit(page, ctx, route, label) {
  const errors = [], server = []
  const onErr = (e) => errors.push(String(e).slice(0, 300))
  const onResp = (r) => { if (r.url().includes("/api/") && r.status() >= 500) server.push(`${r.status()} ${new URL(r.url()).pathname}`) }
  page.on("pageerror", onErr)
  page.on("response", onResp)
  const t0 = Date.now()
  try {
    await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 30000 })
  } catch (e) { errors.push(`navigace: ${String(e).slice(0, 200)}`) }
  await page.waitForTimeout(1200)
  const ms = Date.now() - t0
  fs.mkdirSync(path.join(OUT, ctx.persona), { recursive: true })
  // a sheet the app opens by itself (the morning report, a question about a data gap) is part of
  // what the runner sees first: keep it, then close it like a runner would
  let overlay = null
  const dlg = page.locator('[role="dialog"]').first()
  if (await dlg.isVisible().catch(() => false)) {
    const oshot = path.join(OUT, ctx.persona, `${ctx.simDate}-${ctx.moment}-${label}-okno.png`)
    await page.screenshot({ path: oshot }).catch(() => {})
    overlay = { text: (await dlg.innerText().catch(() => "")).slice(0, 4000), screenshot: path.relative(OUT, oshot) }
    await page.keyboard.press("Escape")
    await page.waitForTimeout(700)
  }
  const text = ((overlay?.text ? overlay.text + "\n" : "") + (await page.locator("main").innerText().catch(() => ""))).slice(0, 9000)
  const shot = path.join(OUT, ctx.persona, `${ctx.simDate}-${ctx.moment}-${label}.png`)
  await page.screenshot({ path: shot }).catch(() => {})
  page.off("pageerror", onErr)
  page.off("response", onResp)
  const findings = []
  for (const e of errors) findings.push({ check: "ui-crash", route, key: e.slice(0, 120), type: "bug",
    title: `Obrazovka ${label} spadla v prohlížeči`, detail: `${ctx.who}: ${e}` })
  for (const s of [...new Set(server)]) findings.push({ check: "ui-server-error", route, key: s, type: "bug",
    title: `Server vrátil chybu na obrazovce ${label}`, detail: `${ctx.who}: ${s}` })
  if (ms > 10000) findings.push({ check: "ui-slow", route, key: label, type: "bug",
    title: `Obrazovka ${label} se načítala přes 10 s`, detail: `${ctx.who}: ${Math.round(ms / 100) / 10} s` })
  if (ctx.lang === "en") {
    const leaks = text.split("\n").map((l) => l.trim()).filter((l) => l && CZ.test(l) && !ALLOW.some((a) => a.test(l)))
    // the key without numbers, so "−4" one day and "−25" the next stay one note
    const norm = (l) => l.replace(/[−+\-]?\d+([.,]\d+)?\s*%?/g, "#").slice(0, 60)
    if (leaks.length) findings.push({ check: "ui-czech-in-english", route, key: `${label}:${norm(leaks[0])}`, type: "copy",
      title: `Česky v anglické verzi: ${label}`, detail: `${ctx.who}:\n${leaks.slice(0, 6).map((l) => `• ${l.slice(0, 140)}`).join("\n")}` })
  }
  return { route, label, ms, text, overlay: overlay?.screenshot || null, screenshot: path.relative(OUT, shot), findings }
}

async function moment(page, ctx, routes) {
  await page.clock.setSystemTime(new Date(ctx.clock))
  await page.request.put(BASE + "/api/auth/lang", { data: { lang: ctx.lang } }).catch(() => {})
  await page.evaluate((l) => { try { localStorage.setItem("dl-lang", l) } catch {} }, ctx.lang).catch(() => {})
  const screens = []
  for (const [route, label, after] of routes) {
    const s = await visit(page, ctx, route, label)
    if (after) await after(page).catch(() => {})
    screens.push(s)
  }
  return screens
}

async function openCheckin(page) {
  const b = page.getByRole("button", { name: /check-in/i }).first()
  if (await b.count()) {
    await b.click()
    await page.waitForTimeout(800)
    await page.keyboard.press("Escape")
  }
}

async function main() {
  if (!TOKEN) throw new Error("Chybí DOSSLAP_PERSONA_TOKEN")
  if (args[0] === "file") {                       // stage 2: notes from the AI review
    const data = JSON.parse(fs.readFileSync(args[1], "utf8"))
    for (const block of Array.isArray(data) ? data : [data]) await fileFindings(block.persona, block.simDate, block.items || [], "synthetic-ai")
    return
  }
  fs.mkdirSync(OUT, { recursive: true })
  const overview = await api("GET", "/api/personas")
  const keys = flag("persona") ? [flag("persona")] : overview.personas.map((p) => p.key)
  let chromium = null
  if (!has("no-ui")) ({ chromium } = require("playwright"))
  const browser = chromium ? await chromium.launch() : null
  const journal = []
  for (const key of keys) {
    const p = overview.personas.find((x) => x.key === key)
    let run = p.run || (await api("POST", `/api/personas/${key}/reset`, { seed: 1 }))
    const r = rng(`${key}-${run.simDate}`)
    let ctxBrowser = null, page = null
    for (let i = 0; i < DAYS; i++) {
      const dayNo = run.day + (run.phase === "evening" ? 1 : 0)
      if (!browser || !wantsVisit(p, run, { day: dayNo }, r)) {
        run = await api("POST", `/api/personas/${key}/advance`, { days: 1, to: "evening" })
        continue
      }
      if (!page) {
        ctxBrowser = await browser.newContext({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 2, isMobile: true,
          hasTouch: true, locale: "cs-CZ", timezoneId: "Europe/Prague" })
        page = await ctxBrowser.newPage()
        await page.clock.install({ time: new Date() })
        await page.goto(BASE + "/auth")
        const res = await page.request.post(BASE + `/api/personas/${key}/session`, { headers: { "X-Persona-Token": TOKEN } })
        if (!res.ok()) throw new Error(`přihlášení personou ${key}: ${res.status()}`)
      }
      // morning: the night arrived, before the run
      run = await api("POST", `/api/personas/${key}/advance`, { days: 1, to: "morning" })
      const who = `Persona ${p.name} (${p.label}), simulovaný den ${run.day} (${run.simDate})`
      const mlang = LANG === "mix" ? "cs" : LANG
      const mctx = { persona: key, simDate: run.simDate, moment: "rano", clock: `${run.simDate}T07:35:00+02:00`, lang: mlang, who }
      const morning = await moment(page, mctx, [["/app/today", "Dnes", openCheckin], ["/app/training", "Trénink"]])
      // evening: the run is done (or not)
      run = await api("POST", `/api/personas/${key}/advance`, { days: 1, to: "evening" })
      const acts = await page.request.get(BASE + `/api/runners/${run.runnerId}/activities`).then((x) => x.json()).catch(() => [])
      const last = (Array.isArray(acts) ? acts : acts.items || []).find((a) => (a.started_at || "").startsWith(run.simDate))
      const tabs = Object.keys(run.behaviour?.tabs || { load: 1, post: 1 }).filter((t) => ["load", "post", "mechanics", "care", "today", "training"].includes(t))
      const extra = tabs.find((t) => !["today", "training"].includes(t)) || "load"
      const eroutes = [[`/app/${extra}`, extra]]
      if (last) eroutes.unshift([`/app/post/${last.id}`, "Detail běhu"])
      const elang = LANG === "mix" ? "en" : LANG
      const ectx = { ...mctx, moment: "vecer", clock: `${run.simDate}T20:20:00+02:00`, lang: elang }
      const evening = await moment(page, ectx, eroutes)
      const screens = [...morning, ...evening]
      const day = (await api("GET", `/api/personas/${key}/days?limit=1`)).days[0] || {}
      await fileFindings(key, run.simDate, screens.flatMap((s) => s.findings))
      journal.push({ persona: key, name: p.name, label: p.label, simDate: run.simDate, day: run.day,
        events: day.events || [], checkin: day.checkin, app: day.morning, did: day.did, appFindings: day.findings,
        screens: screens.map(({ findings, ...s }) => ({ ...s, findings: findings.map((f) => f.title) })) })
      fs.writeFileSync(path.join(OUT, "journal.json"), JSON.stringify(journal, null, 1))
    }
    if (ctxBrowser) await ctxBrowser.close()
    console.log(`${key}: den ${run.day} (${run.simDate}), nálezy celkem ${run.stats?.findings ?? 0}`)
  }
  if (browser) await browser.close()
  fs.writeFileSync(path.join(OUT, "journal.json"), JSON.stringify(journal, null, 1))
  console.log(`deník: ${path.join(OUT, "journal.json")} (${journal.length} navštívených dní)`)
}

main().catch((e) => { console.error(e); process.exit(1) })
