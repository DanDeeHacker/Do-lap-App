// Physio brief round 2 F1 — the note editor loses nothing. Five browser checks against a local server on the
// seeded demo database (never production):
//   1. type, wait 6 s, close the tab → reopening shows the text from the server
//   2. block the network, type, reload → "Obnovit" restores the text
//   3. with the MKN-10 list open, Escape closes only the list
//   4. navigating away with unsaved text asks first (in-app dialog)
//   5. after approval the record appears in Dokumentace without a reload
// Run:  cd backend && DOSSLAP_DB_PATH=/tmp/e2e.db DOSSLAP_AUTOSYNC=0 python3 -m uvicorn app.main:app --port 8767
//       DOSSLAP_DB_PATH=/tmp/e2e.db E2E_URL=http://localhost:8767 node scripts/e2e/note_editor.mjs
import { execFileSync } from "node:child_process"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"

// the same way the persona journeys load it: the browser that comes with the environment
const { chromium } = createRequire(import.meta.url)("playwright")

const URL = process.env.E2E_URL || "http://localhost:8767"
const HERE = dirname(fileURLToPath(import.meta.url))
const RID = "run-0001"
const seed = () => Number(execFileSync("python3", [join(HERE, "seed_past_visit.py"), RID], { env: process.env }).toString().trim())
const results = []
const seen = (loc, timeout = 8000) => loc.waitFor({ timeout }).then(() => true, () => false)
const check = (name, ok, extra = "") => { results.push([name, ok]); console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? ` — ${extra}` : ""}`) }

const browser = await chromium.launch()
const ctx = await browser.newContext({ baseURL: URL, viewport: { width: 1280, height: 900 } })
const login = await ctx.request.post("/api/auth/session", { data: { email: "havlickova@fyzioholesovice.cz", password: "demo1234" }, headers: { Origin: URL } })
if (!login.ok()) throw new Error(`login ${login.status()}`)
const field = (page, k) => page.locator(`textarea[data-field="${k}"]`)
const open = async (page, bid) => { await page.goto(`/physio/client/${RID}/visit/${bid}`); await field(page, "objective").waitFor() }

// 1 ------------------------------------------------------------------------------------------------------------
{
  const bid = seed()
  let page = await ctx.newPage()
  await open(page, bid)
  await field(page, "objective").click()
  await page.keyboard.type("Citlivost úponu Achillovy šlachy vpravo.", { delay: 40 })
  await page.waitForTimeout(6000)
  await page.close({ runBeforeUnload: false })
  page = await ctx.newPage()
  await page.goto("/physio")
  await page.evaluate((b) => localStorage.removeItem(`doslap:note:${b}`), bid)   // only the server can answer now
  await open(page, bid)
  const v = await field(page, "objective").inputValue()
  check("1 autosave survives closing the tab", v === "Citlivost úponu Achillovy šlachy vpravo.", JSON.stringify(v))
  await page.close()
}

// 2 ------------------------------------------------------------------------------------------------------------
{
  const bid = seed()
  const page = await ctx.newPage()
  page.on("dialog", (d) => d.accept())
  await open(page, bid)
  const block = (r) => r.abort("internetdisconnected")
  await page.route("**/api/conclusions/**", block)
  await page.route("**/conclusion/draft", block)
  await field(page, "plan").click()
  await page.keyboard.type("Výpony 3 × 15 denně.", { delay: 30 })
  await page.getByText("Neuloženo — zkouším znovu").waitFor({ timeout: 8000 })
  await page.reload()
  await page.getByTestId("restore").waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "Obnovit" }).click()
  const v = await field(page, "plan").inputValue()
  await page.unroute("**/api/conclusions/**")
  await page.unroute("**/conclusion/draft")
  await page.getByText(/^Uloženo \d/).waitFor({ timeout: 10000 })
  check("2 offline text is restored with Obnovit and then saved", v === "Výpony 3 × 15 denně.", JSON.stringify(v))
  await page.close()
}

// 3 + 4 + 5 ---------------------------------------------------------------------------------------------------
{
  const bid = seed()
  const page = await ctx.newPage()
  await open(page, bid)
  const dg = page.getByRole("combobox", { name: "Diagnóza" })
  await dg.fill("tendinopatie")
  await page.getByTestId("diagnosis-list").waitFor()
  await page.keyboard.press("Escape")
  const listGone = await page.getByTestId("diagnosis-list").count() === 0
  const stillHere = page.url().includes(`/visit/${bid}`) && await field(page, "objective").isVisible()
  check("3 Escape closes only the MKN-10 list", listGone && stillHere)
  // outside click closes it too
  await dg.fill("achil")
  await page.getByTestId("diagnosis-list").waitFor()
  await page.locator("h1").click()
  check("3b an outside click closes the list", await page.getByTestId("diagnosis-list").count() === 0)

  await field(page, "assessment").fill("Přetížení Achillovy šlachy vpravo.")
  await page.getByRole("link", { name: "Klient", exact: true }).click()
  const asked = await seen(page.getByTestId("leave-dialog"), 1500)
  await page.getByRole("button", { name: "Zůstat" }).click().catch(() => null)
  check("4 leaving with unsaved text asks first", asked && page.url().includes(`/visit/${bid}`))

  // the identity on the card must be complete before approval (R2); demo data only
  await ctx.request.put(`/api/physios/me/clients/${RID}/card`, { headers: { Origin: URL }, data: {
    first_name: "Adéla", last_name: "Kučerová", birth_date: "1996-04-12", sex_at_birth: "f",
    permanent_street: "Ukázková 1", permanent_city: "Praha", permanent_postal_code: "17000" } })
  await page.getByRole("textbox", { name: "Shrnutí pro klienta" }).fill("Šlachu šetřete, výpony denně.")
  await page.getByTestId("visit-approve").click()
  const approved = await seen(page.getByTestId("after-approve"), 10000)
  if (!approved) await page.screenshot({ path: "/tmp/note-editor-approve.png" })
  await page.getByRole("link", { name: "Klient", exact: true }).click()          // in-app navigation, no reload
  await page.getByRole("button", { name: "Dokumentace", exact: true }).click()
  const rec = page.getByTestId("record").filter({ hasText: "Přetížení Achillovy šlachy vpravo." })
  const shown = await seen(rec.first())
  check("5 the approved record appears in Dokumentace", approved && shown)
  await page.close()
}

await browser.close()
const failed = results.filter(([, ok]) => !ok)
console.log(`${results.length - failed.length}/${results.length} passed`)
process.exit(failed.length ? 1 : 0)
