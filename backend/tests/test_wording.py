"""Plan phase 3: user-facing texts stay training guidance, not medical claims.
The project's regulatory note (Regulace a cenotvorba Došlap) puts injury-risk
prediction and prevention claims in the MDR grey zone, so none of these phrasings
may appear in the app's texts (frontend source or backend strings)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORBIDDEN = [
    r"prevenc\w*\s+zraněn",
    r"predikc\w*\s+(rizika\s+)?zraněn",
    r"pravděpodobnost\w*\s+zraněn",
    r"\d+\s*%\s*riziko\s+zraněn",
    r"riziko\s+zranění\s*:?\s*\d+\s*%",
    r"včasn\w*\s+varování\s+před\s+zraněním",
    r"detek\w*\s+(tendinopati|zraněn)",
    r"\bdiagnostikuj\w*",
]
SKIP_DIRS = {"node_modules", "dist", "__pycache__", "tests"}


def _files():
    for base, exts in ((os.path.join(ROOT, "frontend", "src"), (".ts", ".tsx")), (os.path.join(ROOT, "backend", "app"), (".py",))):
        for d, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                if f.endswith(exts):
                    yield os.path.join(d, f)


def test_no_medical_claims_in_app_texts():
    hits = []
    for path in _files():
        if path.endswith("coach_validate.py"):   # the validator lists these patterns on purpose
            continue
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                code = line.strip()
                if code.startswith(("#", "//", "*")):
                    continue
                for pat in FORBIDDEN:
                    if re.search(pat, line, re.I):
                        hits.append(f"{os.path.relpath(path, ROOT)}:{n}: {code[:120]}")
    assert not hits, "medical claims in app texts:\n" + "\n".join(hits)
