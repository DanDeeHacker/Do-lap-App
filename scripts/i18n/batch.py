"""Prints the next texts still to translate (absolute indices into src_<src>.json),
skipping obvious code (CSS classes, colours, SVG paths, ids):
python3 batch.py frontend|backend COUNT"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(__file__)
src, count = sys.argv[1], int(sys.argv[2])
arr = json.load(open(os.path.join(HERE, f"src_{src}.json"), encoding="utf-8"))
done = {}
for f in glob.glob(os.path.join(HERE, "en", "*.json")):
    done.update(json.load(open(f, encoding="utf-8")))
TW = re.compile(r"(^|\s)(-?[a-z]+:)*-?(bg|text|px|py|pt|pb|pl|pr|mt|mb|ml|mr|mx|my|flex|grid|rounded|border|w|h|size|gap|p|m|z|inset|top|left|right|bottom|shadow|ring|transition|duration|opacity|translate|origin|animate|font|leading|tracking|items|justify|place|min|max|overflow|absolute|relative|fixed|block|inline|hidden|shrink|grow|cursor|outline|select|tabular|truncate|whitespace|divide|space|col|row|aspect|backdrop|object|sr|ease|delay|scale|rotate|fill|stroke)(-|$|\s)")
def noise(t):
    return (TW.search(t) and len(TW.findall(t)) >= 2) or re.match(r"^(rgb|linear-gradient|radial-gradient|repeating|calc|inset|M\d|transform|0 0 0)", t) \
        or re.fullmatch(r"[A-Z][a-z]+[A-Z]\w*|[A-Z]{2,}[a-z]*|[\w-]+/[\w./-]+", t)
n = 0
for i, a in enumerate(arr):
    if a["t"] in done or noise(a["t"]):
        continue
    print(f"{i}\t{a['t']}")
    n += 1
    if n >= count:
        break
