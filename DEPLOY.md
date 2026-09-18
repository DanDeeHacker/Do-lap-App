# Deploying Došlap to Railway (for testing with friends)

The app ships as **one container**: FastAPI serves both the API (`/api/*`) and the
built React SPA from the same origin, so the session cookie and CSRF check work
with no CORS setup. A `Dockerfile` builds the frontend and runs the backend.

Result: one HTTPS URL your friends open on their phone (the UI is mobile-responsive;
they can "Add to Home Screen").

---

## What's already wired

- `Dockerfile` — builds `frontend/dist`, then runs `uvicorn app.main:app` serving the SPA + API.
- `main.py` — serves the SPA with client-route fallback (`/`, `/auth`, `/app/:tab`, `/data`).
- `DOSSLAP_HTTPS=1` is set in the image → secure cookies over HTTPS.
- `DOSSLAP_DB_PATH` — override so SQLite lives on a **persistent volume** (survives redeploys).
- Listens on Railway's injected `$PORT` automatically.

---

## Option A — Deploy from GitHub (easiest)

1. Push this repo to GitHub (a private repo is fine).
2. On <https://railway.app> → **New Project → Deploy from GitHub repo** → pick the repo.
   Railway auto-detects the `Dockerfile` and builds.
3. Add a **persistent volume** (so test data survives redeploys):
   - Project → your service → **Variables/Settings → Volumes → New Volume**
   - Mount path: `/data`
4. Add environment variables (service → **Variables**):
   - `DOSSLAP_DB_PATH` = `/data/dosslap.db`
   - (`DOSSLAP_HTTPS` is already `1` from the Dockerfile — no need to set it.)
5. Generate a public URL: service → **Settings → Networking → Generate Domain**.
6. Open the URL. First boot auto-creates tables and seeds demo data.

## Option B — Deploy with the Railway CLI

```bash
npm i -g @railway/cli          # or: brew install railway
railway login
cd /path/to/dosslap
railway init                   # create a new project
railway up                     # build & deploy the Dockerfile

# persistent SQLite
railway volume add --mount-path /data
railway variables --set DOSSLAP_DB_PATH=/data/dosslap.db

railway up                     # redeploy so the var/volume take effect
railway domain                 # print the public HTTPS URL
```

---

## Logging in

- New visitors land on the **sign-up** screen; they can switch to sign-in via the toggle.
- Sign-in is remembered while the browser stays open and is dropped when it's fully
  closed (session cookie), returning to sign-up on the next visit.
- **Demo account:** `adela@demo.cz` / `demo1234` (a runner with seeded data).

Demo data is seeded only on the first boot of an empty database; with the volume
attached it persists afterwards.

---

## Connecting a watch / phone (for real data)

- **Garmin — file:** upload the Garmin Connect export ZIP.
- **Garmin — login:** enter Garmin credentials; data is pulled server-side (used only
  for that download, never stored). Supports MFA.
- **Apple Health — auto-connect (no exports):** Apple has no cloud API, so the phone
  pushes data. In **Data → Apple Health** the app shows a webhook **URL + bearer token**;
  paste them into the **Health Auto Export** iOS app (Automations → REST API, JSON) or an
  Apple Shortcut. It then syncs HRV, resting HR, sleep, steps and runs automatically.
  A manual `export.zip` upload is available as a fallback.

---

## Test it locally first (optional)

```bash
cd /path/to/dosslap
docker build -t dosslap .
docker run --rm -p 8000:8000 -v "$PWD/_data:/data" \
  -e DOSSLAP_DB_PATH=/data/dosslap.db dosslap
# open http://localhost:8000
```

---

## Notes & caveats

- **SQLite** is fine for a friends test (single small container). It is not built
  for high concurrency — for a real pilot, move to Postgres later.
- **Cost:** Railway has trial credit, then ~$5/mo for a small always-on service + volume.
- **Garmin live-connect:** works, but never store anyone's Garmin password — the
  connect endpoint uses credentials transiently only. For a casual test, friends can
  just use the diary or file upload instead.
- **Redeploys:** with the volume, accounts/runs/diary survive. Without it, the DB
  resets (and reseeds demo data) on each restart/redeploy.
- **Custom domain / password gate:** optional; ask if you want a simple shared
  access password in front of it so it's not fully public.
```
