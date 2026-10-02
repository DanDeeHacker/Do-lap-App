"""Collects the user-visible Czech texts of the backend (engine signals, guidance,
programmes, demo data…) for the British English dictionary. f-strings become
templates with {} for each placeholder. The AI assistant (app/assistant, prompts,
knowledge base) is left out: its answers are translated by the model after
validation (app/translate.py). Output: scripts/i18n/src_backend.json"""
import ast
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "../../backend/app")
SKIP_DIRS = {"assistant", "prompts", "knowledge"}
SKIP_FILES = {"coach_validate.py", "translate.py", "llm.py", "evaluate.py", "reports.py"}  # reports: xlsx exports
CZ = re.compile(r"[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]")
REGEXISH = re.compile(r"\\[bdswW]|\(\?|\[\^|\w\*|\|\w+\|")
out = {}


def texty(s: str) -> bool:
    t = " ".join(s.split())
    if not t or not re.search(r"[A-Za-zÀ-ž]", t) or REGEXISH.search(s):
        return False
    if CZ.search(t):
        return True
    # plain labels without diacritics ("Objem", "Intenzita", "Kadence")
    return bool(re.fullmatch(r"[A-Z][a-zA-Z]{2,}( [a-zA-Z0-9]+){0,4}", t)) and not re.fullmatch(r"[A-Z][a-z]+[A-Z]\w*", t)


for root, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("__")]
    for f in files:
        if not f.endswith(".py") or f in SKIP_FILES:
            continue
        p = os.path.join(root, f)
        tree = ast.parse(open(p, encoding="utf-8").read())
        docs = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
                b = n.body[0]
                if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant):
                    docs.add(id(b.value))
        inner = set()       # the literal parts of an f-string belong to its template
        for n in ast.walk(tree):
            if isinstance(n, ast.JoinedStr):
                for v in n.values:
                    inner.add(id(v))
        for n in ast.walk(tree):
            s = None
            if isinstance(n, ast.JoinedStr):
                s = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and id(n) not in inner:
                s = n.value
            if s is not None and texty(s):
                t = " ".join(s.split())
                out.setdefault(t, set()).add(os.path.relpath(p, ROOT))

arr = sorted(({"t": t, "files": sorted(v)} for t, v in out.items()), key=lambda x: (x["files"][0], x["t"]))
json.dump(arr, open(os.path.join(os.path.dirname(__file__), "src_backend.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(arr), "strings", sum(len(x["t"]) for x in arr), "chars")
