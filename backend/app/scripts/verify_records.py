"""Recompute every clinical record's hash and its clinic chain; report the first mismatch (physio brief R5.5).

    python -m app.scripts.verify_records             # exit 0 when intact, 1 on the first mismatch
"""
from __future__ import annotations

import sys

from .. import records as R
from ..db import SessionLocal


def main(argv=None) -> int:
    db = SessionLocal()
    try:
        res = R.verify(db)
    finally:
        db.close()
    if res["ok"]:
        print(f"OK: {res['checked']} záznamů, hashe i řetěz sedí.")
        return 0
    print(f"NESEDÍ: záznam {res['record_id']} ({res['problem']}), zkontrolováno {res['checked']}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
