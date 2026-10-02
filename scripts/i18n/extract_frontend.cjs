// Collects every user-visible Czech text of the frontend (JSX text, string and
// template literals) for the British English dictionary. Template literals become
// templates with {} for each ${…}. Output: scripts/i18n/src_frontend.json
const ts = require("../../frontend/node_modules/typescript")
const fs = require("fs")
const path = require("path")
const SRC = path.join(__dirname, "../../frontend/src")
const out = new Map()
const LETTER = /[A-Za-zÀ-ž]/
const CZ = /[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/
// Tailwind classes, ids, paths, css: not text
const CODE = /^[a-z0-9:[\]/.%_#!&>()=,'" -]+$/
const looksText = (s) => {
  const t = s.replace(/\s+/g, " ").trim()
  if (!t || !LETTER.test(t)) return false
  if (CZ.test(t)) return true
  if (/^(\/|https?:|#|\.\/|@)/.test(t)) return false
  if (/^[a-z][A-Za-z0-9]*$/.test(t) && !/^[a-z]+$/.test(t)) return false // camelCase ids
  if (/[a-z]-[a-z0-9]/.test(t) && !/\s[a-z]+\s/.test(" " + t + " ")) return false
  if (CODE.test(t) && /(^|\s)(bg|text|px|py|mt|mb|ml|mr|flex|grid|rounded|border|w|h|size|gap|p|m)-/.test(t)) return false
  return /^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/.test(t) || /\s/.test(t) || CZ.test(t)
}
const add = (s, file, kind) => {
  const t = s.replace(/\s+/g, " ").trim()
  if (!looksText(t)) return
  if (!out.has(t)) out.set(t, { files: new Set(), kind })
  out.get(t).files.add(path.basename(file))
}
for (const dir of [SRC, path.join(SRC, "components")]) {
  for (const f of fs.readdirSync(dir)) {
    if (!/\.(tsx?|ts)$/.test(f) || f.endsWith(".d.ts")) continue
    const file = path.join(dir, f)
    const sf = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const visit = (n) => {
      if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) return
      if (ts.isJsxText(n)) add(n.text, file, "jsx")
      else if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
        const p = n.parent
        // skip property keys, className, data-*, comparisons inside import paths
        if (p && ts.isJsxAttribute(p) && /^(className|data-|key|to|href|role|type|style|id|htmlFor|inputMode|autoComplete)/.test(p.name.getText())) return
        if (p && ts.isPropertyAssignment(p) && p.name === n) return
        add(n.text, file, "str")
      } else if (ts.isTemplateExpression(n)) {
        let s = n.head.text
        for (const sp of n.templateSpans) s += "{}" + sp.literal.text
        add(s, file, "tpl")
      }
      ts.forEachChild(n, visit)
    }
    visit(sf)
  }
}
const arr = [...out.entries()].map(([t, v]) => ({ t, files: [...v.files].sort(), kind: v.kind }))
arr.sort((a, b) => a.files[0].localeCompare(b.files[0]) || a.t.localeCompare(b.t))
fs.writeFileSync(path.join(__dirname, "src_frontend.json"), JSON.stringify(arr, null, 1))
console.log(arr.length, "strings")
