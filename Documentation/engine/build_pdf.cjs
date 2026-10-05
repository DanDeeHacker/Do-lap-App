// Renders Engine_Doslap_dokumentace.html to Documentation/Engine_Doslap_<version>_dokumentace.pdf
// with Chromium (Playwright): `node Documentation/engine/build_pdf.cjs` (NODE_PATH = global modules
// when Playwright isn't a local dependency). The version comes from the page <title>.
const path = require("path")
const fs = require("fs")
const { chromium } = require("playwright")
;(async () => {
  const src = path.join(__dirname, "Engine_Doslap_dokumentace.html")
  const title = (fs.readFileSync(src, "utf8").match(/<title>([^<]+)<\/title>/) || [])[1] || "Engine Došlap"
  const ver = (title.match(/v\d+\.\d+\.\d+/) || ["vX"])[0]
  const out = path.join(__dirname, "..", `Engine_Doslap_${ver}_dokumentace.pdf`)
  const exe = process.env.CHROMIUM_PATH || ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => fs.existsSync(p))
  const browser = await chromium.launch(exe ? { executablePath: exe } : {})
  const page = await browser.newPage()
  await page.goto("file://" + src, { waitUntil: "load" })
  const small = 'font-family: "Liberation Sans", Arial, sans-serif; font-size: 5.3pt; color: #45454a; width: 100%;'
  await page.pdf({
    path: out, format: "A4", printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: `<div style='${small} padding: 0 0 0 57pt;'>${title}</div>`,
    footerTemplate: `<div style='${small} text-align: right; padding: 0 56pt 0 0;'>Strana <span class="pageNumber"></span> z <span class="totalPages"></span></div>`,
  })
  await browser.close()
  console.log(out)
})()
