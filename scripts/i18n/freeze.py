"""Turns batch files keyed by index (or aligned lists) into {Czech text: English}
so they survive re-extraction (the source order changes as the code changes).
Run right after writing a batch: python3 freeze.py"""
import glob
import json
import os
import re

HERE = os.path.dirname(__file__)
for f in sorted(glob.glob(os.path.join(HERE, "en", "*.json"))):
    m = re.search(r"(frontend|backend)_(\d+)\.json$", f)
    if not m:
        continue
    src, start = m.group(1), int(m.group(2))
    arr = json.load(open(os.path.join(HERE, f"src_{src}.json"), encoding="utf-8"))
    tr = json.load(open(f, encoding="utf-8"))
    if isinstance(tr, list):
        pairs = [(start + k, v) for k, v in enumerate(tr)]
    elif all(re.fullmatch(r"\d+", k) for k in tr):
        pairs = [(int(k), v) for k, v in tr.items()]
    else:
        continue                                      # already frozen
    out = {arr[i]["t"]: v for i, v in pairs}
    nf = os.path.join(HERE, "en", f"{src}-{start:04d}.json")
    json.dump(out, open(nf, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.remove(f)
    print(os.path.basename(f), "→", os.path.basename(nf), len(out))
