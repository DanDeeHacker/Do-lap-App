// Renders AI_agent_review_guidelines.html to "Documentation/AI agent review guidelines.pdf"
// with Chromium (Playwright): `node Documentation/review/build_pdf.cjs` (NODE_PATH = global modules
// when Playwright isn't a local dependency). The scheduled review routines read that PDF by name.
const path = require("path")
const fs = require("fs")
const { chromium } = require("playwright")
;(async () => {
  const src = path.join(__dirname, "AI_agent_review_guidelines.html")
  const title = (fs.readFileSync(src, "utf8").match(/<title>([^<]+)<\/title>/) || [])[1] || "AI agent review guidelines"
  const out = path.join(__dirname, "..", "AI agent review guidelines.pdf")
  const exe = process.env.CHROMIUM_PATH || ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => fs.existsSync(p))
  const browser = await chromium.launch(exe ? { executablePath: exe } : {})
  const page = await browser.newPage()
  await page.goto("file://" + src, { waitUntil: "load" })
  const small = 'font-family: "Liberation Sans", Arial, sans-serif; font-size: 6pt; color: #6b6b66; width: 100%;'
  await page.pdf({
    path: out, format: "A4", printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: "<div></div>",
    footerTemplate: `<div style='${small} display: flex; justify-content: space-between; padding: 0 42pt;'><span>${title}</span><span><span class="pageNumber"></span></span></div>`,
  })
  await browser.close()
  console.log(out)
})()
