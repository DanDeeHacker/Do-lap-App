"""Re-encrypt the encrypted patient-card fields with a new key (round 2 F9.1, docs/field-encryption.md).

    FIELD_ENCRYPTION_KEY=<new> FIELD_ENCRYPTION_KEY_PREVIOUS=<old> python -m app.scripts.rotate_field_key [--apply]

Every value is read with whichever key opens it and written again with the new key. Without --apply it only
counts. A value neither key opens is reported and left as it is. It prints no values.
"""
from __future__ import annotations

import argparse
import sys

from .. import models
from .. import records as R
from ..db import SessionLocal

FIELDS = ("rodne_cislo_enc", "insurance_no_enc", "id_doc_no_enc")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if not R.crypto_on():
        print("Nový klíč není nastavený.", file=sys.stderr)
        return 2
    db = SessionLocal()
    n, bad = 0, 0
    try:
        for card in db.query(models.PatientRecord).all():
            for f in FIELDS:
                blob = getattr(card, f)
                if not blob:
                    continue
                plain = R.decrypt(blob)
                if plain is None:
                    bad += 1
                    print(f"karta {card.id}: pole {f} nejde otevřít žádným klíčem", file=sys.stderr)
                    continue
                setattr(card, f, R.encrypt(plain))
                n += 1
        if a.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    print(f"{n} hodnot {'přešifrováno' if a.apply else 'by se přešifrovalo (přidejte --apply)'}; {bad} nejde otevřít.")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
