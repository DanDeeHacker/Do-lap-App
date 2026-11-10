# Field encryption key (physio brief R2.1, round 2 F9.1)

The patient card stores the birth number (rodné číslo), the insurance number and an identity-document number
encrypted with AES-GCM (`backend/app/records.py`). Without a key the app stores none of them and the card says
"Rodné číslo zatím nelze uložit." The key never appears in the UI, in logs or in this repository.

## Set it (owner, once per environment)

1. Generate 32 random bytes, base64url:
   `python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`
2. Railway → the service → Variables → `FIELD_ENCRYPTION_KEY` = that value. Production and staging get
   different keys. Redeploy.
3. Patient card → Upravit: the two encrypted inputs appear. `GET …/documentation/export` shows
   `has_rodne_cislo: true` once a value is saved.

## Back it up

- Keep the key in the owners' password manager (two owners), outside Railway, the moment it is created. A database
  backup without the key cannot be read; the key without the database is useless — store them apart.
- The daily database backup (R12) does not contain the key. A restore test (`python -m app.scripts.restore_test`)
  needs the key in its environment to read the encrypted fields.

## Rotate it (yearly, or at once when it may have leaked)

1. Generate a new key as above.
2. Set `FIELD_ENCRYPTION_KEY_PREVIOUS` = the old key and `FIELD_ENCRYPTION_KEY` = the new key; redeploy. The app
   now writes with the new key and reads with either.
3. Re-encrypt every stored value: `python -m app.scripts.rotate_field_key` (counts), then `--apply`. It prints no
   values and reports any value neither key opens.
4. When it reports 0 left to open, remove `FIELD_ENCRYPTION_KEY_PREVIOUS`, redeploy, and record the rotation date
   next to the key in the password manager. Keep the old key there for as long as backups made with it are kept.

## Status

Setting the Railway variable is an owner's step; the AI team holds no Railway token. Until it is set the card
hides the inputs.
