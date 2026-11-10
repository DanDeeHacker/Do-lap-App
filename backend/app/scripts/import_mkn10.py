"""Import the MKN-10 (ICD-10, Czech) code list from the official ÚZIS file (physio brief R3.3). Codes are
never typed by hand. Download the classification from ÚZIS (https://mkn10.uzis.cz/ → export / CSV), then:

    python -m app.scripts.import_mkn10 path/to/mkn10.csv [--code-col KOD --label-col NAZEV] [--shortlist codes.txt]

The CSV is read as UTF-8 (or cp1250 when that fails), semicolon or comma separated. The running shortlist is
applied only from a file a physio reviewed. Re-running updates labels and adds new codes.
"""
from __future__ import annotations

import argparse
import csv
import io

from .. import models
from ..db import SessionLocal


def _read(path: str) -> list[dict]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1250"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--code-col", default=None)
    ap.add_argument("--label-col", default=None)
    ap.add_argument("--shortlist", default=None, help="a reviewed list of codes, one per line")
    a = ap.parse_args(argv)
    rows = _read(a.csv)
    if not rows:
        print("Soubor je prázdný.")
        return 2
    cols = list(rows[0].keys())
    code_col = a.code_col or next((c for c in cols if c.strip().upper() in ("KOD", "KÓD", "CODE")), cols[0])
    label_col = a.label_col or next((c for c in cols if c.strip().upper() in ("NAZEV", "NÁZEV", "NAZ", "LABEL")), cols[1])
    short = set()
    if a.shortlist:
        short = {x.strip() for x in open(a.shortlist, encoding="utf-8") if x.strip()}
    db = SessionLocal()
    n = 0
    try:
        for r in rows:
            code, label = (r.get(code_col) or "").strip(), (r.get(label_col) or "").strip()
            if not code or not label:
                continue
            row = db.get(models.DiagnosisCode, code) or models.DiagnosisCode(code=code)
            row.label, row.running_shortlist = label, code in short
            db.merge(row)
            n += 1
        db.commit()
    finally:
        db.close()
    print(f"Importováno {n} kódů MKN-10.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
