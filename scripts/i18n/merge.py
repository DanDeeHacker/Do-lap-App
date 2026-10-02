"""Builds frontend/src/i18n/en.json from the translations in en/*.json
({Czech text: British English}; an empty value means "not text"). Templates keep
their placeholders: {} in Czech ↔ {0}, {1}… in English. Reports which source
texts (src_*.json) still lack a translation."""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(__file__)
tr = {}
for f in sorted(glob.glob(os.path.join(HERE, "en", "*.json"))):
    tr.update(json.load(open(f, encoding="utf-8")))
x, t, problems = {}, [], []
for cs, en in tr.items():
    if not en:
        continue
    n = cs.count("{}")
    have = sorted(set(int(m) for m in re.findall(r"\{(\d+)\}", en)))
    if (n and have != list(range(n))) or (not n and have):
        problems.append(f"placeholders: {cs!r} → {en!r}")
        continue
    (t.append([cs, en]) if n else x.__setitem__(cs, en))
for src in ("frontend", "backend"):
    arr = json.load(open(os.path.join(HERE, f"src_{src}.json"), encoding="utf-8"))
    todo = [a["t"] for a in arr if a["t"] not in tr]
    print(f"{src}: {len(arr) - len(todo)}/{len(arr)} translated or skipped, {len(todo)} to go")
out = os.path.join(HERE, "../../frontend/src/i18n/en.json")
json.dump({"x": x, "t": t}, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(x), "exact,", len(t), "templates →", os.path.relpath(out, HERE))
if problems:
    print("\n".join(problems[:40]))
    sys.exit(1)
