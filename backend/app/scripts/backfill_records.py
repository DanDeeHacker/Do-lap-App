"""Superseded by `backfill_round2` (physio brief round 2 F2): one code path for legacy notes.

    python -m app.scripts.backfill_records            # dry run
    python -m app.scripts.backfill_records --apply
"""
from __future__ import annotations

import argparse

from . import backfill_round2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    return backfill_round2.main([] if a.apply else ["--dry-run"])


if __name__ == "__main__":
    raise SystemExit(main())
