"""Import the MKN-10 (ICD-10, Czech) code list from the official ÚZIS file (physio brief R3.3, round 2 F9.3). Codes
are never typed by hand.

The repository carries the valid codes of the ÚZIS release of 1. 1. 2026 (`app/data/mkn10-20260101.csv.gz`:
code with the dot and the full Czech name, from `01_MKN10_5E_2026_utf8.csv` of
https://www.uzis.cz/res/f/008465/mkn-10-strukturovane-podklady-20260101.zip, rows without PlatnostDo). The app
imports it on start when the table is empty. For a newer release, download the "strukturované podklady" zip from
https://www.uzis.cz/mkn-10 and run

    python -m app.scripts.import_mkn10 path/to/01_MKN10_5E_<rok>_utf8.csv [--shortlist codes.txt]
    python -m app.scripts.import_mkn10 --bundled          # the file in the repository

The CSV is read as UTF-8 (or cp1250), semicolon or comma separated, optionally gzipped. ÚZIS columns
(KodSTeckou, NazevPlny, PlatnostDo) are recognised; rows with a PlatnostDo are skipped. The running shortlist is
applied only from a file a physio reviewed. Re-running updates labels and adds new codes.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import os

from .. import models
from ..db import SessionLocal

BUNDLED = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mkn10-20260101.csv.gz")


def fold(s: str) -> str:
    """Lowercase without diacritics, for search ('slacha' finds 'šlacha')."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def _read(path: str) -> list[dict]:
    raw = open(path, "rb").read()
    if path.endswith(".gz"):
        raw = gzip.decompress(raw)
    for enc in ("utf-8-sig", "cp1250"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def import_rows(db, rows: list[dict], code_col=None, label_col=None, short: set[str] | None = None) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    up = {c.strip().upper(): c for c in cols}
    code_col = code_col or next((up[k] for k in ("KODSTECKOU", "KOD", "KÓD", "CODE") if k in up), cols[0])
    label_col = label_col or next((up[k] for k in ("NAZEVPLNY", "NAZEV", "NÁZEV", "NAZ", "LABEL") if k in up), cols[1])
    until = up.get("PLATNOSTDO")
    short = short or set()
    have = {d.code: d for d in db.query(models.DiagnosisCode).all()}
    n = 0
    for r in rows:
        code, label = (r.get(code_col) or "").strip(), (r.get(label_col) or "").strip()
        if not code or not label or (until and (r.get(until) or "").strip()):
            continue
        row = have.get(code)
        if row is None:
            row = models.DiagnosisCode(code=code)
            db.add(row)
            have[code] = row
        row.label, row.search = label, fold(f"{code} {code.replace('.', '')} {label}")
        if short:
            row.running_shortlist = code in short
        n += 1
    db.commit()
    return n


def ensure_imported(db) -> int:
    """On start: an empty table gets the bundled release (round 2 F9.3)."""
    if db.query(models.DiagnosisCode.code).first() is not None or not os.path.exists(BUNDLED):
        return 0
    return import_rows(db, _read(BUNDLED))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--bundled", action="store_true")
    ap.add_argument("--code-col", default=None)
    ap.add_argument("--label-col", default=None)
    ap.add_argument("--shortlist", default=None, help="a reviewed list of codes, one per line")
    a = ap.parse_args(argv)
    path = BUNDLED if a.bundled or not a.csv else a.csv
    rows = _read(path)
    if not rows:
        print("Soubor je prázdný.")
        return 2
    short = set()
    if a.shortlist:
        short = {x.strip() for x in open(a.shortlist, encoding="utf-8") if x.strip()}
    db = SessionLocal()
    try:
        n = import_rows(db, rows, a.code_col, a.label_col, short)
    finally:
        db.close()
    print(f"Importováno {n} kódů MKN-10.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
