# Došlap review — 2026-10-05 (full review)

**Fix before the next release: 3 × S1.** (1) Anyone can self-register as a physio and take over any runner's health data. (2) Re-importing a Garmin/Apple file deletes the runner's own pain ratings, manual sessions and exclusions. (3) The report "AI notes" send runner health data to the external LLM without the AI consent.

Commit / working tree: `7b9bd43` (Monday morning report: the week's plan — runs, strength and rides by day, at the edge of capacity), detached checkout of `origin/main`; working tree clean, nothing uncommitted.

Baseline: tests 526 passed / 2 skipped / 0 failed, 167 s (Python 3.13 venv) · `tsc --noEmit` OK · `vite build` OK (chunk-size warning only) · `python -m compileall` OK. Postgres 16 was also exercised locally for migrations and imports (phase E/G).

How this review was run: phases A–D by the lead reviewer; E+G, F, H and I+C14 by four parallel sub-reviewers on separate throwaway databases and ports, never touching the deployed app, Garmin, Apple or any LLM (all keys unset). Every S1 and every S2 below was either reproduced or re-read in code by the lead reviewer before inclusion. Scratch scripts and screenshots live in `/tmp` of the review container (not committed).

## Summary

This is the first full review (only quick screens have run since the playbook was written on 25 Sep), and it lands on top of a very large, fast-moving week: v0.10–v0.12 engine releases, Apple Health sleep stages, shoes, critical speed, illness and menstrual-cycle signals, strength programmes, morning/evening/weekly reports, an English UI and an owner admin view. The engine core holds up well — calibration is on target (null false-signal rates 3.5 % v1 / ≈5 % v2–v3, improvement flags 0 %, detection 70 %), sandbox parity is exact for all 12 demo runners in all three engines, live assessment is fast, and the physio-override product rule fires exactly as specified. The risk has moved to the edges that grew this week: **access control for the physio role, data-destroying import paths, and consent for the new AI features (all S1)**, plus a cluster of **live-vs-history and cache-staleness bugs** in the new v0.12 inputs (shoes, critical speed) and the engine switch, **ingestion robustness** (Garmin outages, lost HRV, unbounded uploads), and **regulatory/evidence hygiene** around the new pain self-management programmes (S2).

Counts: **S1 3 · S2 15 · S3 32 · S4 8.** One previously reported item (the v3 terrain-spike gate, quick screen this morning) is re-listed here as F4 so this report stands alone.

## Findings (most severe first)

### F1 Anyone can register as a physio and claim any runner — including runners who never opted in or who revoked that physio
Severity: S1 · Confidence: CONFIRMED · Area: F2 access control
Location: `backend/app/routers/triage.py:70-92` (`claim`), `backend/app/routers/auth.py:83` (`role = body.role if body.role in ROLES`)
What happens: `POST /api/auth/register` accepts `"role": "physio"` from the request body, and `PATCH /api/triage/{tid}/claim` checks only `require_role("physio")`. It never checks the runner's `physio_interest` consent (enforced only when listing the queue), the case status (closed / self-managed cases can be claimed), an existing claim by another physio (it is silently taken over), or a revoked care assignment (it is re-activated). Triage ids are sequential and every runner has one.
Failure scenario: a stranger registers via the API, iterates `claim` over ids 1…N and gets an active care assignment for every runner, then reads their check-ins, pain, injuries, daily metrics and messages, and can push RTR plans and exercise programmes (`rtr.py:80`, `programs.py:30` require only the care assignment).
Evidence: lead reproduction — fresh physio `phy-0005`; `GET /api/runners/run-0002/bootstrap` → 403; `PATCH /api/triage/2/claim` (status `closed`, `physio_interest=False`) → 200; bootstrap → 200, 166 kB of health data. Sub-review also showed takeover of a case claimed by the seeded physio and re-claim after the runner's `…/physios/{pid}/decline`.
Suggested fix: in `claim()` require `runner.physio_interest`, `status == "open"`, `claimed_by is None`, and no revoked assignment for this physio; stop accepting `role` from public registration (create physio accounts by invitation/verification only). Test to add: `test_claim_requires_consent_open_unclaimed_unrevoked` — four 403 cases plus a 403 for `role: "physio"` on public register.
Health-risk direction: privacy breach; unsafe training via plans pushed by an unverified "physio".

### F2 Re-importing a Garmin or Apple file wipes the runner's own data (and 500s on Postgres)
Severity: S1 · Confidence: CONFIRMED · Area: E1 ingestion
Location: `backend/app/routers/integrations.py:91-93` (`_apply_seed`); UI gives no warning (`frontend/src/datapage.tsx:40`)
What happens: a file import first deletes **all** of the runner's `Activity`, `DailyMetric` and `ActivityFeedback` rows, then inserts the file's content. That destroys manually logged sessions, run ratings with pain points, exclusions, hand-edited days — and an Apple upload erases all Garmin history. On Postgres the same delete violates the `activity_feedback` / `activity_streams` foreign keys, so the re-import fails with 500 (SQLite does not enforce FKs, which is why tests pass).
Failure scenario: a runner rates yesterday's run "pain 7/10, knee", logs a gym session, then re-uploads a fresh Garmin export to backfill — the pain rating and gym session are silently gone, so the knee-pain signal and its physio routing disappear.
Evidence: sub-review `fb.py`: user pain/gym feedback 2 → 0, manual/excluded activities 2 → 0 after one re-import; `drive.py` on Postgres 16: first import 200, second 500 `ForeignKeyViolation … activity_feedback_activity_id_fkey` / `activity_streams_activity_id_fkey`. Lead re-read the three unconditional `.delete()` calls.
Suggested fix: make file imports merge by `external_id` like the live sync (`_merge_seed`), never delete manual activities, user feedback, exclusions or edited days; delete dependents first or use `ondelete="CASCADE"` if a replace is ever kept. Test to add: rate + manual log + exclude → re-import → all preserved; run the import test with `PRAGMA foreign_keys=ON`.
Health-risk direction: false reassurance (pain history lost).

### F3 Report "AI notes" send runner health data to the external LLM without the AI consent
Severity: S1 · Confidence: LIKELY (code path clear; no external call possible with keys off) · Area: F5 external LLM
Location: `backend/app/routers/runners.py:1103-1114` (`POST /{rid}/report/ai`), `backend/app/metrics/report_ai.py:110`; called automatically when a report opens (`frontend/src/report.tsx:978`)
What happens: the endpoint checks only read access; `report_ai.generate` posts sleep stages, HRV, resting HR, load and training to `ASSISTANT_BASE_URL` whenever a key is configured, without the `coach_consent` gate that the AI coach (`coach_texts.py:242`) and assistant (`assistant/service.py:96`) both enforce. A claimed physio or the owner opening the report triggers it on someone else's data.
Failure scenario: a runner who declined the AI consent opens the morning report; their night's health data leaves the app to the hosted model.
Evidence: as owner, `POST /api/runners/run-0014/report/ai` → 200 while `PUT …/coach/consent` → 403 (owner is read-only); code read of `report_ai.generate` shows no consent check.
Suggested fix: return the rule-based text (`source: "rules"`) unless `runner.coach_consent` is true, and only when the runner themself requests it. Test to add: consent off + mocked `llm.chat_messages` → mock never called.
Health-risk direction: none (privacy/consent).

### F4 v3 (Kapacitní) loses the terrain-weighted load-spike signal that v2 has
Severity: S2 · Confidence: CONFIRMED · Area: C1 mode plumbing
Location: `backend/app/metrics/engine.py:1434` (`_v2 = _emode() == "v2"`) vs the shared `_sensitive()` helper (`engine.py:349-352`) used by every other sensitive-mechanics branch
What happens: grade-adjusted km (Minetti cost, steep descent weighted up) feeds the session-spike detector only in exact mode v2, although v3 is "v2 mechanics + capacity". Identical data: v2 `sessionSpike 1.48 (terén)`, v3 `1.0 (vzdálenost+intenzita)`. Only a v2 test exists (`tests/test_terrain.py`).
Suggested fix: `_v2 = _sensitive()`; add a v3 copy of `test_v2_terrain_spike_only_compares_runs_with_profiles`.
Health-risk direction: false reassurance.

### F5 History cache ignores shoes and return-to-run plans — history ≠ live after adding a shoe
Severity: S2 · Confidence: CONFIRMED · Area: C3/C4 replay parity and caches
Location: `backend/app/history.py:89-105` (`load_inputs` streams), `:136-150` (`input_digests`); live reads them in `metrics/data.py:130-131`
What happens: v0.12.0 made `Shoe` (6-week transition narrows v3 running margins) and `ReturnToRun` engine inputs, and `as_of` filters them by date, but neither is in the per-day or global digest. Adding/editing a shoe calls `recompute_assessment` → `mark_dirty`, yet `refresh_quadrant_history` finds no changed day and replays nothing, so every cached day — including today's point — keeps the pre-shoe values.
Evidence: run-0009 in v3 after adding a minimal shoe first used 5 days ago: live load 2 → 3 (`cap_ascent` 2 → 3), history last point stays 2, `replayed=0 kept=84`. Seed data moves only 1 point; a runner near the 25 threshold would flip quadrant on Dnes but not in the history.
Suggested fix: add `shoes` and `rtr_plans` rows (keyed by `first_used`/`created_at`) to `streams` in `load_inputs`, or into the global digest. Test to add: add a shoe → `refresh_quadrant_history` replays from `first_used` and the last row equals live.
Health-risk direction: both (history disagrees with today's state).

### F6 After an engine switch, live hysteresis is seeded from the other engine's stored quadrant
Severity: S2 · Confidence: CONFIRMED (today) / LIKELY (persistence) · Area: C3 replay parity
Location: `backend/app/metrics/data.py:115` (`prev_quadrant` = stored `Assessment.quadrant`), `backend/app/routers/runners.py:74-87` (`set_engine` recomputes without resetting it)
What happens: the live quadrant uses the stored assessment's quadrant as "yesterday" for the 25/18 hysteresis; after a switch that row is from the previous engine. The history chain uses its own replayed yesterday. While mechanics sit in the 18–25 band, the two never reconcile.
Evidence: run-0008 switched v1 → v2 and v1 → v3 (same steps as the endpoint): live `critical` vs history last `overreaching` with identical axes (mech 20, load 100/76, overall 87/85); all other runner × engine pairs matched.
Suggested fix: on engine switch (and whenever the stored row's `engine_version` mode differs), take `prev_quadrant` from the refreshed history's previous day for the current engine. Test to add: switch engines for a runner with mech in the band → live quadrant equals history's last point.
Health-risk direction: both (here false alarm "Kritická"; reverse case is false reassurance).

### F7 Critical-speed cache ignores segments — CS is frozen before the run's streams arrive
Severity: S2 · Confidence: CONFIRMED · Area: C4 caches
Location: `backend/app/metrics/speed.py:136` (`key = (day, tuple(s["id"] for s in pool))`); sync order `routers/integrations.py:415` (recompute) → background `fetch_new_details_bg` → `:882` (recompute)
What happens: every sync recomputes right after importing a run, before its detail streams exist, and caches CS for that day/id set; the second recompute after the streams arrive hits the stale entry. Live heals at midnight (new key), but a stream backfill of older runs makes the incremental history replay read stale CS from the in-process cache and **persist** it into `EngineHistoryCache`.
Evidence: `/tmp/review_c/cs.py`: CS before streams `None`; fresh process with streams `{cs: 4.5, dPrime: 72}`; same process after streams arrive `None`. Affects the Rychlost channel, minutes above CS in Intenzita and the "≥ 20 min threshold work = hard day" rule. Related, plausible: `capacity._ecc_factor` is keyed `(activity id, len(profile))`, so a `/garmin/terrain` re-fetch with the same point count stays stale.
Suggested fix: include per-run segment presence/count and stream `created_at` in the CS and ECC keys (as `_seg_cached` already does). Test to add: CS computed without segments, then with → values differ.
Health-risk direction: false reassurance (hard intervals under-counted on the day they happen).

### F8 Dnes shows "Stabilní · Skóre 100 · nízké riziko" when loading the assessment fails
Severity: S2 · Confidence: CONFIRMED · Area: H6 error states
Location: `frontend/src/App.tsx:520`, `:565` (`quadrant = "stable"` defaults), `:1197` (`overall: a?.overall ?? 0`), tier words `:902-905`
What happens: if `/bootstrap` fails while auth works, the red "Data se nepodařilo načíst" banner is followed by a green Stabilní quadrant, Skóre 100, "Trénink sedí, nízké riziko", "Nic nad prahem", and the Trénink tab disappears. A brand-new runner with no data likewise sees "nízké riziko · Připravenost 100 % · sedí na vaší normě".
Evidence: sub-review screenshots `bootstrap500_today.png`, `neterr2__app_today.png` (kritickepretizeni, live state critical / overall 84), `fresh_400__app_today.png`; lead re-read the defaults.
Suggested fix: when the assessment is missing render a neutral "—" state (no quadrant, score or tier words); "zatím bez dat" for runners without data. Test: Playwright route-abort test asserting no "Stabilní" when bootstrap fails.
Health-risk direction: false reassurance.

### F9 Evening report's "Zítra" and "Zbytek týdne" ignore the stop/physio guidance and contradict the weekly plan
Severity: S2 · Confidence: CONFIRMED · Area: H3 consistency / C8 guidance
Location: `backend/app/metrics/daily_report.py:241-276` (`_rest_of_week`), `:445-448`; rendered `frontend/src/report.tsx:810, 844`
What happens: `_rest_of_week` spreads the remaining weekly km over the runner's usual pattern without consulting `week_plan`, pain, the override or the referral. For the same Monday the morning Plán týdne says "Dnes neběhat… plán běhu je pozastavený" (Tuesday volno) while the evening card says "Zítra podle plánu týdne: kvalitní ≈ 3,9 km" and lists five "kvalitní" days.
Evidence: sub-review text dumps `report_v3_evening_3_report-card-tomorrow.txt`, `…_4_report-card-week.txt`, `report_v3_morning_5_report-card-weekPlan.txt` (kritickepretizeni, pain 8/10, physio within 48 h, readiness 20 %); lead re-read `_rest_of_week`.
Suggested fix: derive the evening rest-of-week from `week_plan` (or apply its pause/override); never label a day "kvalitní" while a stop or referral is active.
Health-risk direction: false reassurance / over-loading.

### F10 One transient Garmin error turns off auto-sync for every runner
Severity: S2 · Confidence: CONFIRMED · Area: E3/E4
Location: `backend/garmin_live.py:458-459` (`except Exception: raise AuthError`), `backend/app/routers/integrations.py:612-617`
What happens: a network error or 5xx while resuming a session is mapped to "login expired"; auto-sync is set to False with the "vypršelo" message, so one Garmin outage at 06:30 disables auto-sync for everyone until each runner re-enters their password.
Evidence: `e3.py` (resume raises `ConnectionError`): 3/3 runners `auto_sync=False`.
Suggested fix: only authentication errors (401/403, `GarminConnectAuthenticationError`) become `AuthError`; others are retryable and recorded in `last_error`. Health-risk direction: false reassurance (stale data).

### F11 A failed HRV / resting-HR range call loses those values permanently
Severity: S2 · Confidence: CONFIRMED (mechanism) · Area: E2
Location: `backend/garmin_live.py:329-337` (`_safe`), `backend/app/routers/integrations.py:291-301, 382-391`
What happens: when the range call fails (e.g. 429 on the first 180-day connect) days are stored without HRV; later syncs skip existing dates except today/yesterday and `daily_fill` fills only sleep stages and breathing rate, so the readiness baseline has no HRV for months.
Evidence: `e5.py`: 60 rows, 0 HRV; after a healthy re-sync still only 2 HRV values.
Suggested fix: flag/abort the day write when a range call fails, or let the fill pass back-fill any empty field. Health-risk direction: false reassurance.

### F12 Uploads are unbounded: zip bomb extraction, unlimited request size, malformed files → 500
Severity: S2 · Confidence: CONFIRMED · Area: F6
Location: `backend/app/routers/integrations.py:147, 191` (`await file.read()`), `backend/garmin_ingest.py:274-275, 365-366` (`extractall`), `backend/app/routers/conclusions.py:75`
Evidence: a 498 kB zip expanded to 484 MB on disk before the 400; a 150 MB JSON was read into memory; a 60 MB audio upload accepted; bad zip / bad XML → 500 (`BadZipFile`, `ParseError`) and an empty `/tmp/garmin_*` left behind. Path traversal is safe.
Suggested fix: request size limits (e.g. 200 MB exports, 25 MB audio); sum `ZipInfo.file_size` before extracting or extract only needed members; map parse errors to 400. Health-risk direction: none (availability — a disk-filling upload takes the app down).

### F13 Login throttle bypassable with a forged X-Forwarded-For
Severity: S2 · Confidence: CONFIRMED locally / LIKELY in production · Area: F3
Location: `Dockerfile:33` (`--forwarded-allow-ips='*'`), `backend/app/security.py:139`
What happens: uvicorn trusts the client-supplied leftmost `X-Forwarded-For`; the throttle keys on email + IP, so rotating the header gives unlimited password guesses (the guest per-IP limit too).
Evidence: 8 wrong passwords → 429; the same request with `X-Forwarded-For: 1.2.3.4` → 401 (accepted for checking).
Suggested fix: trust only the platform proxy range (or use the rightmost hop) and add a per-email limit independent of IP.

### F14 Several physio reads of runner data are not written to the runner's access log
Severity: S2 · Confidence: CONFIRMED · Area: F7 GDPR
Location: `backend/app/main.py:385-412` (logs only `/api/runners/{rid}/…` paths)
Evidence: physio `POST /api/ai/brief {"runner_id":"run-0013"}` → 200 with a full health summary; run-0013's access log unchanged. Also unlogged: `/api/ai/chat`, `/api/rtr/{pid}`, `/api/conclusions/{cid}`, `/api/physios/{pid}/bootstrap`, `/api/simulate/inputs/{rid}`.
Suggested fix: record inside `ensure_runner_read_access` (or each handler) for non-self access.

### F15 Pain programmes are matched by substring — upper-abdominal pain gets the lower-abdomen tendinopathy programme
Severity: S2 · Confidence: CONFIRMED · Area: I1
Location: `backend/app/programs_library.py:475` (`"match": ["břiš", "abdom"]`), matched at `:571` (`any(m in r for m in p["match"])`); body-map region "Horní břišní" (`frontend/src/components/MuscleAnatomy.tsx:108`)
What happens: marking upper-abdominal pain recommends "Dolní břicho (úpon břišních svalů)"; its referral note screens only pubic pain, cough pain and a groin bulge — not pain unrelated to movement, fever or nausea (visceral causes). The library is flagged `reviewed: False`.
Suggested fix: match "dolní břiš" only; add the not-movement-related / fever / nausea → doctor/physio clause; physio sign-off before auto-recommending. Health-risk direction: false reassurance (non-musculoskeletal cause self-managed).

### F16 Pain self-management programmes are framed as treatment of a diagnosis (MDR grey zone)
Severity: S2 · Confidence: LIKELY · Area: I1 regulatory
Location: `backend/app/programs_library.py:411-482`, `backend/app/routers/self_programs.py:160`, `frontend/src/selfprograms.tsx:404`
What happens: programmes are "recommended by the pain you marked", link to Physiopedia diagnosis pages (Achilles_Tendinopathy, Plantar_Fasciitis, Medial_Tibial_Stress_Syndrome) and cite treatment RCTs ("úspěšné léčby", `:446`). Symptom → therapy mapping invites self-diagnosis and moves toward MDR Rule 11; the app's own evidence card (cards.json:671) says the Silbernagel pain rule applies "to diagnosed tendinopathy under a physio".
Suggested fix: present them as general strengthening options, gate auto-recommendation behind physio review, drop diagnosis links. Health-risk direction: false reassurance.

### F17 The not-a-medical-device note is missing from most guidance and risk views
Severity: S2 · Confidence: CONFIRMED · Area: I1 regulatory
Location: present only at `frontend/src/training.tsx:995` and `landing.tsx:580`; absent on Skóre/Příznaky, Zátěž, the body map, the illness card (`App.tsx:1831`) and the morning/evening reports (`report.tsx`). `backend/tests/test_wording.py` scans Czech sources only, not the English JSON.
Suggested fix: one shared footer component on every risk/guidance view; extend the wording test to `frontend/src/i18n/en.json` and `scripts/i18n/en/*`.

### F18 Shoe transition shown as "6 weeks (Fuller et al., 2017)" — the trial used 26 weeks and still saw excess injury
Severity: S2 · Confidence: LIKELY · Area: I2 evidence
Location: `frontend/src/profile.tsx:471`; `backend/app/metrics/runner_factors.py` (`TRANSITION_DAYS = 42`)
What happens: margins return to normal on day 42 and the UI attributes the 6 weeks to Fuller 2017 (PMID 28129518: 26-week graded transition, more pain/injury); Ryan 2014 (PMID 24357642) reports excess injuries throughout 12 weeks; "≥ 4 mm lower drop" is not what the trials tested. The engine doc (p. 31) calls 6 weeks a working assumption, the UI does not.
Suggested fix: label 6 weeks as the app's assumption, or extend to ≥ 12 weeks. Health-risk direction: false reassurance.

## S3 findings (compact)

Engine / calibration
- S3-1 Pace confound above target: easy runs +25 s/km with unchanged form raise the v2/v3 "mechanika přetrvává" flag to 7.7 % (matched baseline 1.8 %; target ≤ 5 %, fail > 10 %; N = 1000). v1 0 %. CONFIRMED. False alarm.
- S3-2 183-day history replay for a 6-month runner with streams: v1 2.2 s, v2 13.2 s, **v3 21.0 s** (target ≤ 20 s). Live assessment 0.05–0.13 s (target ≤ 0.3 s). CONFIRMED.
- S3-3 `POST /runners/{rid}/engine` silently maps an unknown mode to v1 instead of 422 (`runners.py:83`).
- S3-4 Sandbox capacity values use a period decimal (`metrics/sensitivity.py:283`, `f"×{round(…, 2)}"`) — same pattern as the fixed 2026-09-28 F1.

Security / privacy (F-phase)
- S3-5 CSRF accepts requests with no Origin and checks no Referer (`deps.py` `verify_csrf`); SameSite=Lax is the real defence.
- S3-6 Session tokens stored raw as the primary key (`security.py:47-75`), 400-day sliding lifetime, no "sign out everywhere"; DB backups therefore carry live tokens.
- S3-7 The shared guest account can change its settings and language (`deps.py:58` exempts all `/api/auth/`).
- S3-8 Apple push `?token=` is written to the access log in plain text (`integrations.py:270`).
- S3-9 `.dockerignore` misses `backend/.env`, `backend/.venv`, `backend/prod_copy.db`; root `.gitignore` has no `.env` (only `backend/.gitignore`). Nothing secret is tracked in git; affects local image builds only.

Ingestion / deploy (E/G)
- S3-10 Failed refresh of a stale ride/swim stream wipes its HR histogram (`integrations.py:807-822`); running streams keep theirs.
- S3-11 Missing/rotated `DOSSLAP_SECRET` or a failed download in auto-sync leaves no `last_error` (`integrations.py:610, 627-641`).
- S3-12 Rate-limit detection by substring (`"rate" in msg`, `"too many"`) stalls the backfill on unrelated errors (`garmin_live.py:434`).
- S3-13 Auto-sync time uses naive local time; the Dockerfile does not set `TZ` (DEPLOY.md asks for it); fires 07:30 on the spring DST change (`main.py:142-150`). Precompute already uses `LOCAL_TZ`.
- S3-14 `/api/health` `db_persistent` is a path heuristic — any SQLite path outside backend/ reports true (`db.py:73-79`).
- S3-15 DEPLOY.md misses ~30 environment variables (LLM/ASSISTANT/EMBED/ASR/VISION keys and models, `DOSSLAP_OWNER_EMAILS`, `DOSSLAP_ADMIN_EMAILS`, `DOSSLAP_FEEDBACK_TOKEN`, `DOSSLAP_PRECOMPUTE`, `DOSSLAP_WEATHER`, `OPEN_METEO_API_KEY`, `DOSSLAP_BACKUPS`, …).
- S3-16 Apple push payloads sum sleep and steps across sources (watch 7.6 h + phone 8.1 h → 15.7 h) — the 93b592a dedup fixed only the file path (`apple_health_ingest.py:156-170`). PLAUSIBLE.
- S3-17 Apple push with `{"data": "x"}` → 500 (AttributeError) instead of 400.

Evidence / docs (I, C14)
- S3-18 Neal 2024 (PMID 38181563, 12-week feasibility study, n = 86) described as "on the same data" as RUNSAFE and as "predicting" injury (`sig_doc.py:129`, cap_intensity, doc p. 8, English JSON).
- S3-19 Complaint/niggle figures (6.9 %, 39.6 %) attributed to Frandsen 2025 BJSM but come from a different Frandsen paper (JOSPT Open); that paper argues against grade A for "niggle"; `sig_doc.py:295` says pain is "the only grade-A signal" while four others are A.
- S3-20 "2025 meta-analysis of 46 studies" on ACWR not found (`sig_doc.py:4, 195-202`); `ewma_mild` graded B under a C parent.
- S3-21 Nielsen 2014 (PMID 25155475; novices, HR 1.59, p = 0.07) presented as "clearly risky" (`capacity.py:97`, `guidance.py:104`, `onboarding.tsx:261`).
- S3-22 Readiness labels disagree between the trend (70/40, `tabs.tsx:1684`) and the ring/engine/doc (85/65/45).
- S3-23 Signal-doc constants out of date: ACWR mild band 1.30 vs code 1.40 and detraining 0.70 vs 0.80 (`sig_doc.py:183, 187`); bone pain "≥ 3/10" vs 2/10 for women (`engine.py:2478`); injury history "12 months" vs 24 (`engine.py:2110`); capacity info text omits novice/shoe/under-conditioning factors; week-plan docstring 55 % vs code 60.5 % (`guidance.py:119`).
- S3-24 Engine documentation v0.12.0 predates the week plan (7b9bd43) and ride/swim HR hard minutes (8f86ab9); the 45-min Z4+ per-session cap (`guidance.py:98`) is in neither doc nor UI.

Frontend / UX (H)
- S3-25 "Citlivostní analýza" sidebar link shown to non-owners, bounces to Dnes (`shell.tsx:58` vs `App.tsx:262`).
- S3-26 Trénink hint for v1 runners points to an owner-only control and says "Data a propojení" instead of "Data a připojení" (`training.tsx:867`).
- S3-27 Czech copy: informal "ty" in a "vy" UI (`tabs.tsx:886, 2006`, `datapage.tsx:260`); masculine-only "abych zítra byl odpočatý" (`daily_report.py:518`); "baseline" (`tabs.tsx:1427`, `App.tsx:1232`); "session A/B"; "4 řad" (`profile.tsx:373`); Czech left in English mode from `guidance.py:926`.
- S3-28 Number/wording nits: "20–20 min" (`report.tsx:540, 556`); "261 j.z.." (`daily_report.py:643`); "Mechanika 25 je nad prahem 25" (`daily_report.py:404-406`); units dropped on the second figure (`capacity.tsx:269`); "strop vyčerpán" next to "do stropu 196" (`capacity.tsx:287`).
- S3-29 Non-owners get a 403 console error on every /data visit (`datapage.tsx:406`, `/api/engine/outcomes`).
- S3-30 Péče shows "Zatím vám nikdo program neposlal" when `/self-programs` fails — no error or retry. LIKELY.

Process (carried from this morning)
- S3-31 `main`'s history was rewritten after 2026-09-28; the previous baseline `40eebca` is unreachable.
- S3-32 No `.python-version`/`runtime.txt`; Python ≥ 3.12 required outside Docker.

## Fixed since last review
- 2026-09-28 F1 (capacity ratios with a period decimal) and F2 (stale "later phase" AI copy) — fixed (confirmed this morning).
- Physio-override contract holds in v3 guidance: fires only for pain 7–8 with a referral; pain 5 does not trigger it.

## Product questions (not defects — please confirm and update the playbook)
- New runners now default to **v3** (`auth.py:26 NEW_RUNNER_ENGINE = "v3"`); playbook §2 says v1 Standardní is the default.
- The engine picker on the Data page is **owner-only** (`datapage.tsx:225`); playbook §2 says engines are switchable per runner on the Data page.
- Quality sessions need readiness **≥ 65 %** (`guidance.py:93 READY_QUALITY`, documented in the engine doc); playbook C8 says ≥ 85 %.
- Seeded demo accounts have no `running_since`, so every demo login hits the v0.12 profile gate (intended for older accounts per `runners.py:43-47`); consider seeding it so demos open on Dnes.
- The Monday plan frames the week "at the edge of capacity" — check it against the "guardrail, not a coach" decision.

## Improvement proposals (S4)
Quick wins (< 1 h, low risk, no score change):
1. **One shared `NotMedicalDevice` footer** on all risk/guidance views (fixes F17) — validation: extend `test_wording.py` to assert presence per view.
2. **SQLite FK enforcement in tests** (`PRAGMA foreign_keys=ON` in conftest) — would have caught F2's Postgres 500 and future FK bugs; validation: run suite.
3. **Neutral loading/error state on Dnes** (F8) — remove the `"stable"` defaults.
4. **Seed `running_since` on demo runners** — demo logins land on Dnes.

Larger work:
5. **Merge-only file imports** (F2) — preserves runner-entered data; validate with a re-import regression test on SQLite (FK on) and Postgres.
6. **Physio onboarding with verification + consent-checked claim** (F1) — adds an invite/verify step; validate with IDOR tests for each object type.
7. **Single source of truth for "engine inputs"**: one list of tables the engine reads, used by `load_runner_data`, `as_of`, the history digest and the Excel replay — prevents F5-type parity bugs; validate with a parity test that mutates each input table and asserts history = live. Bumps `HISTORY_VERSION`, no score change.
8. **Cache-key audit for metrics caches** (F7, ECC): key on data fingerprints, not ids; validate with "mutate then recompute" tests; no score change except fixing stale values.

Anything changing scores (F4 terrain gate, shoe window F18) needs an engine version bump and a calibration run (phase D recipes).

## Check results

| Check | Result | Note |
|---|---|---|
| A1–A5 baseline | PASS | 526/2/0, tsc, build, compileall |
| B1 discovery | PASS | drift below |
| B2 inventory | PASS | 154 endpoints / 20 routers, 48 models, 8 runner routes |
| C1 mode plumbing | FAIL | F4; S3-3 |
| C2 time | PASS | only `reference._real_today` (documented, weekly-frozen priors) |
| C3 replay parity | FAIL | F5, F6; v1/v2/v3 otherwise equal for all 12 demo runners |
| C4 caches | FAIL | F7 (+ ECC key plausible) |
| C5 direction/units | PASS | improvement −1 SD → 0 % flags |
| C6 rounded values | PASS | |
| C7 capacity invariants | PASS | 72 h/≥3 pain exclusion, floor 0.70, MIN_PRIOR 3, no v3 frailty multiply |
| C8 guidance invariants | PASS | 48 type checks: km ≤ min(ceiling, week left), no quality with pain ≥ 3 or Zátěž ≥ 25, Z4+ ≤ 45 min; readiness gate 65 % (product question) |
| C9 sandbox parity | PASS | all runners × v1/v2/v3 axes equal |
| C10 statistics | PASS | Student t, df n−k / n−1, BH-FDR on unrounded p, domain check |
| C11 stream pipeline | PASS | by tests (decimation, QC acceptance, SEG_VERSION backfill) |
| C12 robustness | PASS | one run, no HR, identical, zero/negative duration, HRmax ≤ rest, NaN — no crash |
| C13 performance | PARTIAL | S3-2 |
| C14 docs = code | FAIL | 6 of 18 constants (S3-22, S3-23) |
| D calibration | PASS (1 off-target) | table below |
| E1 idempotence | FAIL | F2 (otherwise no duplicates on repeated imports/syncs/webhooks) |
| E2 rate limits/failures | FAIL | F11, S3-10, S3-12 |
| E3 tokens | FAIL | encryption OK; F10, S3-11 |
| E4 auto-sync | PARTIAL | isolation OK; S3-13 |
| E5 Apple webhook | PASS | token required; S3-17 |
| E6 cross-training | PASS | rides/swims reach Intenzita only |
| F1 CSRF | PASS | only documented exemptions; S3-5 |
| F2 access control | FAIL | F1 (runner↔runner, owner, guest all OK) |
| F3 sessions | PARTIAL | HttpOnly, SameSite=Lax, Secure via `DOSSLAP_HTTPS`, argon2id; F13, S3-6 |
| F4 export/secrets | PASS | S3-9 |
| F5 external LLM | FAIL | F3 (coach, assistant, physio brief, shoe photo gated correctly; EXIF stripped client-side, 4 MB cap) |
| F6 uploads | FAIL | F12 |
| F7 access log | PARTIAL | F14 |
| G1 migrations | PASS | 18 later-added columns all migrated; verified on SQLite and Postgres 16 |
| G2 seeding | PASS | idempotent on both DBs; edits preserved |
| G3 deploy | PARTIAL | image build NOT RUN (no docker); S3-14, S3-15 |
| H1 tabs/overflow | PASS | v1, v3, fresh × 400 & 1360 px, 0 overflow |
| H2 Trénink nav | PASS | |
| H3 consistency | FAIL | F9 (Dnes/Zátěž/Pohyb/charts otherwise equal live) |
| H4 numbers | PASS | S3-28 nits |
| H5 Czech copy | FAIL | S3-27 |
| H6 empty/error | FAIL | F8, S3-30 |
| H7 tap/contrast | PASS | |
| I1 no diagnosis / disclaimer | FAIL | F15, F16, F17 |
| I2 evidence | FAIL | 30 citations checked; F18, S3-18–S3-21 |
| I3 docs current | PARTIAL | S3-24 |

## Calibration table vs previous review (phase D)

| Check | Target | This review | 2026-09-28 / today's quick |
|---|---|---|---|
| Per-metric shown signal, no change, v1 | ≈ 3.5 % | 3.5 % (N 1000) | 3.7 % |
| …v2 | ≈ 5 % | 3.1 / 4.7 / 5.8 % (3 seeds, N 1000); 5.6 % test generator | 5.0 % |
| …v3 | ≈ 5 % | same as v2 (shared mechanics) | 5.0 % |
| "Mechanika přetrvává" flag, no change (v2/v3) | ≈ 5 % | 3.9 / 6.0 / 5.2 % | not run |
| Flag when metrics improve by 1 SD | 0 % | 0.0 % | not run |
| Easy runs +25 s/km, form unchanged (flag) | ≤ 5 % | v1 0.0 %, v2/v3 **7.7 %** (baseline 1.8 %) | not run |
| Detection +1 SD last 14 days (v2) | ≈ 67 % | 70.3 % | not run |
| Segment drift SD, no change | 0.8–1.25 | NOT RUN (tests) | not run |
| Segment significance FPR, 5-segment baseline | ≈ 5 % | NOT RUN (tests) | not run |
| Demo accounts today (v3) | Tichý silent, Kritické critical | silent, critical | — |
| Stable demo runners, 90-day replay (v3), Zátěž ≥ 25 | ≤ ~30 % of days | 0–29 % (Kritické 31 %, not "stable") | — |
| Physio override in guidance | only pain > 5 + referral | pain 7, 8 + referral only | — |

## Coverage gaps
- Docker image build (no daemon); the `?fit=true` FIT import path; Garmin MFA flow; real LLM/vision/ASR output (keys off — what leaves the app was inferred from code).
- Phase D segment rows (drift SD, significance FPR) relied on `tests/test_segmentation.py` rather than fresh probes.
- Browser: v2 engine, physio/employer/partner roles and "Zobrazit jako" UI, check-in and injury flows, light theme, real touch devices; morning/evening windows only at two simulated times.
- Evidence: ~20 programme references (Rathleff, Hölmich, Harøy …) plausibility-checked only; the full JOSPT Open text was not accessible (403); the Literature Summary .docx is not in the repo.
- Whether the illness signal false-alarms in the luteal phase (not cycle-adjusted) — not tested.
- Columns that predate the 2026-09-29 history root could not be traced (history rewrite).

## Structural drift (playbook updates proposed)
- History replay: `backend/app/history.py` (`load_inputs`/`engine_replay`, snapshot `RunnerData.as_of`, `HISTORY_VERSION = "h10"`); the Excel backtest replay `reports.py::_replay_both` still copies tables into in-memory SQLite and runs v1/v2 only. Engine input loader: `backend/app/metrics/data.py::load_runner_data` — make it the C3 starting point.
- External LLM: `backend/app/llm.py` (not `metrics/llm.py`); call sites now `ai_brief.py`, `coach_texts.py`, `report_ai.py`, `app/assistant/service.py`, `shoes.py` (vision). F5 should read "physio brief + consent-gated runner AI features".
- `fetch_details` is in `backend/garmin_live.py:424`.
- New engine modules: `speed.py` (critical speed), `illness.py`, `cycle.py`, `runner_factors.py`, `dayload.py`, `week_plan.py`, `daily_report.py`, `report_ai.py`.
- New routers: `admin.py` (owner "Zobrazit jako", read-only), `assistant.py`, `self_programs.py`, `shoes.py`; operator-token routes (`require_feedback_token`) now in annotations and assistant — add to F1 exemptions.
- 48 models; new tables this period include `Shoe`, `SelfProgram`, `UserSession`, `KnowledgeDoc/Chunk`, `CardReview`, `AssistantMessage`, `Translation`, `ReportNote`, `AdminAccessLog`.
- Rulebook §2/C8 values out of date: default engine (v3), engine picker owner-only, quality readiness gate 65 %.
- `ensure_demo_accounts` (`seed.py:280`) runs on every boot.
