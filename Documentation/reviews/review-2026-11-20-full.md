# Došlap review — 2026-11-20 (full review)

**Fix before the next release:**
- **The calendar feed ignores the physio's "Dnes bez běhu" and every other care directive (R1, S2, CONFIRMED).** In the app, Dnes and Trénink correctly switch to volno. The runner's subscribed phone calendar still shows "🏃 Lehký běh 5–6,4 km" for the same day.
- **Clinical records are open to colleagues and reception who never treated the client (R2/R3, S2, CONFIRMED).** This confirms and widens the 2026-11-16 PLAUSIBLE item.
  - A reception-role member reads the full SOAP note and writes a legal correction through `POST /api/clinical-records/{id}/corrections` and `/addenda`.
  - Any clinical colleague at the same clinic reads and exports a client's documentation (name, birth date, address, notes) without a care assignment.
- **Message attachments live on the container's own disk (R4, S2, LIKELY).** With the recommended Railway setup (Postgres, no volume), every deploy wipes them. The download then returns 404.

Commit / working tree: `5581de8` (Merge pull request #25 … claude/physio-round2). `main` = `origin/main`. The working tree was clean and nothing was uncommitted. `ENGINE_VERSION` v0.12.23 and `HISTORY_VERSION` h11. HEAD has not changed since the 2026-11-16 quick screen.

Baseline: tests **963 passed / 2 skipped / 0 failed**, 272 s on Python 3.11.18, in a fresh venv. Two review agents and their servers ran on the same machine at the same time, which inflates the time. (2026-11-06 full: 772/2/0, 172 s; +191 tests.) `tsc --noEmit` OK · `vite build` OK (only the known > 500 kB chunk warning) · `compileall app *.py` OK · Node 22.23.5.

How this review was run:
- **One reviewer plus two parallel sub-agents:** phase F security probes and phase H browser.
- **Each used its own throwaway SQLite DB:** `/tmp/rv`, `/tmp/rvsec` and `/tmp/rvui`.
- **Tools:** in-process engine scripts (`/tmp/rv/parity.py`, `null.py`, `limitfeed.py`), local uvicorn and the preinstalled headless Chromium (58 page loads).
- **Nothing external was contacted:** no deployed app, GitHub, Railway, Garmin, Apple or LLM. `NVIDIA_API_KEY` and the ASR keys were unset.
- **`main` was not touched.**

## Summary

**What changed since the last full review** (2026-11-06, `9e89d83`):
- 37 non-merge commits: 141 files, +37 456 / −13 352.
- The three-day engine burst covered by the 2026-11-09 quick screen:
  - day-pin safety v0.12.20, which **closed S1 N2 and S2 N3**;
  - resting HR v0.12.21;
  - VO2max v0.12.22.
- The version-collision fix (v0.12.23).
- **The whole physio clinical-practice app** (physio brief phases 0–4 plus round 2, F1–F19):
  - 3 new routers (`business`, `records`, `work`) and 35 new tables;
  - 81 new columns on existing tables;
  - 9 new physio views.
- Mechanics and scoring code is unchanged (`engine.py` +1/−1, the version line only).

**What is healthy:**
- **Engine:** live vs history replay is 36/36 (12 demo runners × v1/v2/v3), and sandbox vs live is 36/36 on load and mechanics. The worst 183-day replay took 1.7 s. The null rates are within target.
- **Migrations:** a database created by the 2026-11-06 code upgrades with **no missing column** on the current code, and a second boot is clean.
- **CSRF:** every new mutating route has it.
- **Physio access:** an unverified physio and an unclaimed runner both get 403 on every `/api/runners/*` route.
- **Access log:** colleague reads land in the runner's access log.
- **Browser:** 0 px overflow on all 58 loads, Czech copy is clean, and the H6 error and empty states work.

**What went wrong:**
- **Access:** the clinic-level documentation branch is broader than "care assignment only" (R2, R3).
- **Calendar:** the calendar feed is a second guidance surface that skips the care layer (R1).
- **Attachments:** attachments are not persistent (R4).
- **Carried and still open:** the XFF throttle bypass and the malformed-upload 500s, both re-confirmed today.

Counts, new this run: **S1 0 · S2 4 · S3 4 · S4 5**.
- Closed since 2026-11-06, all verified: S1 1 (N2), S2 2 (N3, 11-09 S2-1 ENGINE_VERSION).
- Carried open items are listed separately.

## Findings (most severe first)

### R1 The calendar feed (ICS) ignores the physio's clinical limits, the return-to-run plan and the other care directives
Severity: S2 (borderline S1) · Confidence: CONFIRMED · Area: C8 / H3 (live vs another surface)

Location:
- `backend/app/routers/calendar.py:174-185` (`feed` builds the plan from `E.get_or_refresh_assessment` and `DR._week_plan`);
- compare `backend/app/care_view.py:395-445` (`present` → `resolve_care_directive`, `apply_clinical_limits`), which only the in-app routes call (`routers/runners.py:89,117,152…`).

What happens: the round-2 care layer (W12 limits "Dnes bez běhu", "max. X km na běh/týdně", "bez intervalů"; `rtr` and `rtr_paused`; injury) is applied at presentation time, on the API response. The ICS feed reads the raw engine week plan, so none of it reaches the calendar.

Failure scenario: a physio sets "Dnes bez běhu" for run-0001 (v3).
- Dnes and Trénink show `careDirective.source = clinical_limit`, `type = volno`.
- The runner's subscribed calendar still lists **"🏃 Lehký běh 5–6,4 km"** today and two "Lehký běh 10,1–12,6 km" days later in the week.
- A runner who plans from the phone calendar runs against the physio's instruction. The feed's footer ("aktuální verze je v aplikaci") is the only mitigation.

Evidence: `/tmp/rv/limitfeed.py`, run on a throwaway DB:
- BEFORE: Dnes `engine / lehký`; ICS today `Lehký běh 5–6,4 km`.
- `POST /api/physios/me/clients/run-0001/limits {"kind":"no_running"}` → 200.
- AFTER: Dnes `clinical_limit / volno`; **ICS today still `Lehký běh 5–6,4 km`**, with all 6 events unchanged.

Suggested fix: build the feed's today and week items through the same care layer.
- Call `CV.present(db, rid, a)` and drop or replace run items while `careDirective.running_allowed` is False.
- Cap future days by active `max_km_*` limits and their `ends_on`.
- A `no_running` limit with an end date should blank the run items through that date.

Test to add: `test_calendar_feed_respects_clinical_limit`. With a `no_running` limit, today's VEVENTs contain no run; with `max_km_session=3`, no run item exceeds 3 km.

Health-risk direction: **false reassurance.**

### R2 Reception staff can read and amend clinical records through the corrections and addenda routes
Severity: S2 · Confidence: CONFIRMED · Area: F2

Location: `backend/app/routers/records.py:386-390` (`_own_record` checks only `rec.clinic_id == p.clinic_id`), used by `correct` (`:393`) and `addendum` (`:435`).

What happens: these two routes never call `work.can(db, p.id, "clinical")`. That check is W1 in `docs/physio-brief-map.md:92` ("reception never reads clinical records"). `doc_access` (`records.py:35-49`) enforces it on every other documentation route.

Failure scenario: a reception-role member of cli-0001 who has a record's UUID can:
- POST an addendum, which returns 200 with the full SOAP content (`current`, `original`, `addenda`);
- POST a correction, which writes a new version of the legal record.

Reception gets 403 on `/clients/run-0001/documentation`, `card` and `export`, so the scoping is inconsistent. The UUID is the only barrier, and it is unknown whether reception can see record ids elsewhere (bookings, calendar).

Evidence: phase-F sub-agent, throwaway DB `/tmp/rvsec/review.db`:
- a reception member was inserted for cli-0001;
- a visit note was approved as Havlíčková;
- reception `POST …/addenda` → 200 with content, `POST …/corrections` → 200.

Suggested fix: in `_own_record`, require `W.can(db, p.id, "clinical")` and the same care rule as `doc_access`: live care, or the record's author, or a past assignment.

Test to add: `test_reception_cannot_correct_or_append_records` (403 on both).

Health-risk direction: none (privacy and record integrity).

### R3 Any clinical colleague at the clinic can read and export a client's documentation without a care assignment
Severity: S2 · Confidence: CONFIRMED · Area: F2. This upgrades 2026-11-16 F2 from PLAUSIBLE, and is also a product question.

Location: `backend/app/routers/records.py:44-47`. This is the "documentation only" branch: any `ClinicalRecord` for the clinic's `PatientRecord` grants read access.

What happens: the branch was written for R13, where the provider keeps the legally required records after a client withdraws consent. As written, it also opens the client's card, documentation, episodes and export to **every** clinical member of the clinic, including people who never treated the client.

This contradicts:
- CLAUDE.md: "Client data opens only with a care assignment";
- rulebook §3: "Physios see only runners … whom they have claimed".

Failure scenario: a newly added, verified physio at cli-0001 with no assignment gets 200 on these routes for run-0001:
- `/clients/run-0001/card` (name, birth date, address);
- `/documentation`;
- `/episodes`;
- `/documentation/export`.

The same physio's corrections and addenda through R2's routes are also accepted. `/previsit` and `/api/runners/run-0001/*` correctly return 403. Every read is logged in the runner's access log, which mitigates the risk.

Evidence: phase-F sub-agent live probe (above); code read confirms.

Suggested fix: limit the documentation-only branch to physios who had a care assignment with, or authored a record for, this patient. Alternatively, if clinic-wide access is intended (the clinic as data controller, continuity of care), record it as an owner product decision and amend CLAUDE.md.

Test to add: `test_clinic_colleague_without_assignment_gets_403_on_documentation`, or a test pinning the decision.

Health-risk direction: none (privacy).

### R4 Message attachments are stored on the container's disk by default and are lost on every deploy
Severity: S2 · Confidence: LIKELY (code path + documented deployment; not reproduced on Railway) · Area: G3 / data loss

Location:
- `backend/app/routers/work.py:1001-1002`: `UPLOAD_DIR = DOSSLAP_UPLOAD_DIR or <backend>/uploads`;
- `:1056-1058` writes the file there;
- `:1080-1081` returns 404 when the file is missing.

Related gaps:
- `DEPLOY.md` does not mention `DOSSLAP_UPLOAD_DIR`;
- it recommends Postgres "no volume needed";
- CLAUDE.md "Deploy Configuration" says Postgres via `DATABASE_URL`;
- `backend/uploads/` is not in `.gitignore` (`git check-ignore` matches nothing).

What happens: with Postgres and no volume, the attachment file lives in the ephemeral container, while the `messages` row survives. Auto-deploy on every push to `main` therefore orphans every photo or video a runner or physio sent. The message keeps its paperclip, and the download returns 404.

Failure scenario: a runner sends the physio a photo of a swollen Achilles. The next merge to `main` redeploys. The physio opens the chat and the attachment is gone.

Evidence: code path above. `DEPLOY.md:17,29` recommend the no-volume setup. There is no startup warning for uploads, unlike the DB (`db_persistent`).

Suggested fix:
- store attachments in the database (they are capped at 8/50 MB) or in object storage;
- or default `UPLOAD_DIR` to `/data/uploads` when a volume is detected, and report `uploads_persistent` in `/api/health` next to `db_persistent`;
- document `DOSSLAP_UPLOAD_DIR`;
- add `backend/uploads/` to `.gitignore`, because local test uploads must never be committed.

Test to add: `test_health_reports_upload_persistence`. When `DATABASE_URL` is set and `/data` is missing, health reports the upload store as not persistent.

Health-risk direction: none (data loss of clinical communication).

### R5 The runner's full name is sent to the external LLM
Severity: S3 · Confidence: CONFIRMED (code) · Area: F5

Location: `backend/app/metrics/ai_brief.py:367` (`"runner": r.name`), used in the prompts at `:533` (brief narrative), the chat facts and `draft_conclusion` (`"Pacient: {facts['runner']}"`).

What happens: since physio brief P0.1 (2026-11) the brief gates the LLM on `coach_consent` (good, P0.1). The prompt still begins "Pacient: <full name>". The model does not need the name to write the paragraph, and rulebook F5 asks for the minimum data. This is pre-existing: the lines were already there at `9e89d83`. No earlier report had flagged it.

Failure scenario: with `NVIDIA_API_KEY` set and a consenting runner, every brief, chat turn and conclusion draft sends identity plus health data to the third-party model.

Suggested fix: send "Pacient" or a per-request pseudonym, and substitute the name back in the UI if needed.

Test to add: with a stub `llm.chat_ex`, assert the runner's name is not in any message content.

Health-risk direction: none (privacy).

### R6 The physio AI brief's rule-based text uses dot decimals, "z +2.34" and "baseline"
Severity: S3 · Confidence: CONFIRMED (browser) · Area: H4 / H5 (watchlist: Czech number formatting in generated text)

Location: `backend/app/metrics/ai_brief.py:241-249` (from `06c551b`, 2026-10-13; newly prominent on the physio client overview).

What happens: the physio overview for run-0001 shows:
- "(poměr ×0.43)";
- "Vertikální poměr 7.49 % → 7.64 % …, z +2.34 [B]";
- "Symetrie kontaktu 50.23 % → 50.16 %";
- "baseline" in the recovery line.

Raw floats appear with dot decimals and two places, and the "z" reads as the Czech preposition.

Suggested fix: use the backend Czech number formatter (comma, 1 decimal place). Write "z-skóre +2,3" or "o 2,3 SD", and say "norma" instead of "baseline".

Test to add: the brief for a seeded runner matches no `\d\.\d` and no "baseline".

Health-risk direction: none.

### R7 Uploads are read whole into memory before the size check
Severity: S3 · Confidence: LIKELY · Area: F6

Location: `backend/app/routers/work.py:1053` (`await file.read()` then the 8/50 MB check); `routers/conclusions.py` audio upload (`~:206`, only when ASR is configured).

Failure scenario: an authenticated user posts a multi-GB body. The worker buffers it all before rejecting it, which risks memory exhaustion of the single container.

Suggested fix: read in chunks up to `MAX + 1` and reject early. Also check `Content-Length` when present.

Health-risk direction: none.

### R8 The not-a-medical-device note is missing on Dnes, Zátěž and Mechanika
Severity: S3 · Confidence: CONFIRMED (browser text at 400 px) · Area: I1. This may duplicate carried 10-23 F15–F17; merge if so.

Location: the note is rendered on Trénink (`frontend/src/training.tsx:1516`), physio Praxe and `/tisk`. It is absent from the Dnes, Zátěž and Mechanika text (0 matches).

What happens: rulebook I1 says "every guidance and risk view carries the not-a-medical-device note". Dnes shows today's guidance headline and the quadrant, and Zátěž shows the load verdict, both without it.

Suggested fix: add the shared footer component to Dnes, Zátěž and Mechanika.

Health-risk direction: none (regulatory wording).

## Carried — re-verified today

| ID | Item | Status today |
|---|---|---|
| old F13 (S2) | Login throttle bypass via `X-Forwarded-For` | **STILL OPEN, CONFIRMED.** 14 wrong passwords, each from a new XFF, all returned 401 and never 429. The correct password then returned 200. From one IP the throttle answers 429 after 8 tries. |
| old F11/F12 (S2) | Malformed Garmin/Apple import returns 500 | **STILL OPEN, CONFIRMED.** Corrupt zip and `{"a":1}` give 500 on all 4 combinations. |
| 10-23 F7 (S2) | Pace confound (slower easy runs read as mechanics drift) | **STILL OPEN, re-measured.** Core recipe, v2, +25 s/km with metrics independent of pace: the flag fires in **11.7 %** of runners (baseline pace 335–385 s/km) and **20.7 %** (340–370 s/km), above the 10 % fail line. The noisy own-pace slope extrapolates outside the baseline's speed range. Mechanics code is unchanged since 10-23. 2026-11-06 reported 2.3 % on a differently built harness; this run's generator gives every metric a fixed noise and no pace coupling. |
| 11-16 F1 (S3) | `tests/test_drift_validity.py` fails standalone (`no such table: activities`) | **STILL OPEN, CONFIRMED** (4 failed standalone, all pass in the full run). |
| 11-06 S3-1 | "Moje čísla" cards: "asi 0 pater", truncated labels | **STILL OPEN (code).** `shell.tsx:181` has no `floors ≥ 1` guard. The cards are not in the default layout, so they did not render. |
| 11-06 S3-2 | `lastActivity` / `recentActivities` same-day tie-break | **STILL OPEN (code).** `runstats.ts:53` uses `localeCompare` on date-only `started_at`. |
| 11-06 S3-3 | Model name in commit trailers | No new commits since 2026-11-16; one offender (`0cad381`) remains in history. |
| carried S3 | `/data` 403 console error for non-owners | **STILL OPEN, CONFIRMED** (6/6 loads, including a new runner). |
| carried S3 | Tap targets under 20 px | **STILL OPEN.** 17–19 px on Dnes ("Zobrazit (2)", "Další"), Trénink ("tabulka"), physio home and the client view. |
| carried S3 | DEPLOY.md lists few of the env vars | **WORSE: 65 of 72 missing** (was 54/61). The new missing ones include `FIELD_ENCRYPTION_KEY`, `FIELD_ENCRYPTION_KEY_PREVIOUS`, `BACKUP_ENCRYPTION_KEY`, `DOSSLAP_UPLOAD_DIR`, `DOSSLAP_TISSUE_HYPOTHESES` and `DOSSLAP_SEAT_PRICE_CZK`. |
| carried | C14 / I3 engine docs stop at v0.12.16 | **STILL OPEN.** The PDFs were last changed 2026-10-19, and the code is at v0.12.23. |
| carried | D1 CLAUDE.md "on a password account, the password" | Not re-checked (CLAUDE.md and the merge code are unchanged). |
| others | old F4–F8, F10, F14–F18, 10-23 F4–F6, 10-16 F4/F5, N7 | Not individually re-run. Their code is untouched by this diff (no ingestion or mechanics change). |

**Closed since 2026-11-06:**
- N2 day pins overriding safety stops (S1) and N3 the long-run pin crash (S2): fixed in `e149454`, verified 2026-11-09, and `test_pin_safety.py` is green today.
- 11-09 S2-1 `ENGINE_VERSION` collision: fixed in `0cad381`, version tests green.

## Product questions (not defects)
- **Clinic-wide record access (R3).** Is the clinic the data controller, with any clinician allowed to read and amend? Or is access per care relationship? The answer decides R3's fix, and CLAUDE.md should say which.
- **The physio queue shows "vysoké riziko" with no object** (`physio/common.tsx:29`, `queue.tsx:68-70`). It uses the runner app's tier words, but on its own it reads close to "injury risk". Consider "vysoká zátěž" or "priorita: vysoká".
- **New sign-ups start on v3** (`routers/auth.py:26`, `NEW_RUNNER_ENGINE = "v3"`), while rulebook §2 says v1 is the default. Confirm this, and update the playbook.
- **Carried:** self sign-off on `safety` PRs (four-eyes check); "Čas tréninku týdne" counting walks.

## Improvement proposals (S4)

**Quick wins** (< 1 h):
1. **One care-access helper for physio routes.** Example: `care_access(db, physio, rid, need="read|write")`, used by `doc_access`, `_own_record` and `_own_episode`. This fixes R2 now and makes R3 a one-line decision. Cost: small. Validate with the two tests named above.
2. **Pseudonymise LLM prompts (R5).** Replace the name with "Pacient". It is a one-line change plus a stub test.
3. **`.gitignore` `backend/uploads/` and document `DOSSLAP_UPLOAD_DIR`** (part of R4).
4. **Make `test_drift_validity.py` order-independent.** Use an autouse session fixture that creates the schema (carried 11-16 F1).

**Larger work:**
5. **Every runner-facing guidance surface goes through `care_view.present`.** This covers the ICS feed (R1), the morning report and any future push or email. A contract test should assert that the live Dnes `type` and today's calendar run item agree for every directive source (engine, clinical_limit, rtr, rtr_paused, injury, safety). Benefit: one rule for "what the runner is told today". Risk: low (presentation only, no engine bump). Validate with `test_calendar_feed_respects_clinical_limit` plus a parametrized directive test.
6. **Persistent attachment storage (R4):** DB blob or object storage, plus an `uploads_persistent` health flag.
7. **Carried:** XFF trusted only from Railway's proxy hop; 400 for malformed imports; recalibrate the pace slope (shrink it toward the population prior when the baseline speed range is narrow).

## Calibration table vs previous review (phase D)
This run used the Appendix B **core recipe**: `_drift_z_core` / `_mech_flags`, N = 300, seed 42, 90 days at about 4 runs a week, metrics independent of pace, engine day pinned to 2026-11-20 (`/tmp/rv/null.py`).

| Check | Target / fail | This review (core) | 2026-11-09 quick (core) | 2026-11-06 full (core) |
|---|---|---|---|---|
| Shown per metric (risk-direction z ≥ 0.6), no change, v1 | ≈ 3.5 % | VR 2.0, vosc 4.0, cad 0.0, GCT 3.0 | 2.3 (pooled) | VR 2.0, vosc 5.3, cad 1.3, GCT 2.7 |
| …v2 | ≈ 5 % / > 8 % | VR 2.7, vosc 4.7, cad 0.7, GCT 5.0 — PASS | 5.3 | 4.0 / 5.0 / 4.3 / 3.0 |
| "Mechanika přetrvává" flag, no change (v2) | ≈ 5 % / > 8 % | **4.3 — PASS** | 1.7 | 4.0 |
| Flag at 1 SD improvement (v2) | 0 % / > 1 % | **0.0 — PASS** (VR shown 0.3 %) | — | 0.0 |
| Easy runs +25 s/km, v2 flag | ≤ 5 % / > 10 % | **11.7 (wide pace) / 20.7 (narrow) — FAIL**, carried 10-23 F7 | — | 2.3 (other harness) |
| Detection +1 SD over 14 d (v2), flag | ≈ 67 % / < 55 % | flag 74.7–75.3 PASS; per-metric z: VR 58, vosc 58–59, GCT 61–63, **cad 28–29** | — | flag 81; cad 57 |
| Segment session drift SD | 0.8–1.25 | NOT RUN | — | NOT RUN |
| Segment significance FPR | ≈ 5 % / > 7.5 % | NOT RUN | — | NOT RUN |
| Demo accounts today (v3) | Tichý silent; Kritické critical | Kritické: load 66, overreaching, alert, "Dnes neběhat — objednejte se k fyzioterapeutovi" (browser). Tichý not tabulated. | Kritické as today | as today |
| Stable demos, 90-day v3 replay | ≤ ~30 % of days | NOT RUN (183-day replays ran for timing only) | — | NOT RUN |
| Physio override in guidance | only pain > 5 + referral | `test_pin_safety.py` and the guidance tests are green. A new non-pain trigger exists: the physio's own W12 "Dnes bez běhu" limit and `rtr_paused`. This is a physio decision, not the engine, so it is consistent with §2 but worth adding to the playbook. | PASS | PASS |

Shift explanation:
- No mechanics or scoring code changed since 2026-10-23.
- The cadence detection z-rate (28 % vs 57 % on 11-06) and the pace-probe rate differ from 11-06 because this harness was rebuilt. Cadence noise is 1.5 spm here, and stride is derived from cadence, so pace adjustment absorbs part of the shift.
- They are harness differences, not regressions. The combined flag detection (75 %) is in target.

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 37 non-merge commits since `9e89d83`; 0 since the 11-16 quick screen |
| A2 environment | PASS | fresh `.venv` (Python 3.11.18), `npm ci`, Node 22.23.5, preinstalled Chromium |
| A3 backend tests | PASS | 963 / 2 / 0, 272 s (+191 tests; the 1.6× time rise is explained by the new tests plus concurrent load) |
| A4 frontend | PASS | tsc OK, build OK (chunk warning) |
| A5 compileall | PASS | `app` + top-level scripts |
| B1 discovery | PASS with drift | all §4 roles found at their hinted files; new roles listed under Structural drift |
| B2 inventory | PASS | 30 router modules (3 new); 35 new tables; 81 new columns on old tables; new physio routes `/physio/*` and `/tisk` |
| B3 disappeared roles | PASS | none disappeared; the physio app superseded `physio.html` |
| C1 mode plumbing | PASS | 4 `_emode() ==` sites, unchanged; no new mode |
| C2 time | PASS | metrics wall-clock calls are the today helpers, `reference._real_today` (documented: priors are wall-clock by design), the weather stamp, coach-text retention and the `ai_brief` cache TTL (not scoring) |
| C3 replay parity | PASS | 36/36 (12 runners × 3 modes); the stream case is NOT RUN (the demos have no streams) |
| C4 caches | PASS / carried | history cache unchanged (h11); the new `ai_brief._CACHE` is keyed on assessment `computed_at` plus the last approved conclusion and checked after consent (OK) |
| C5 direction/units | PASS core / FAIL carried | improvement flag 0 %; pace confound carried |
| C6 rounded values | carried | not re-run; scoring code unchanged |
| C7 capacity invariants | PASS (diff) | `capacity.py` change is display-only (`dayRhr`) |
| C8 guidance invariants | PASS in-app / **FAIL (R1)** | the N2 pin blocks hold (`test_pin_safety`); W12 limits applied in-app; the calendar feed bypasses them |
| C9 sandbox parity | PASS | 36/36 load + mech (seeded with the runner, as the router does) |
| C10 statistics | NOT RUN | code unchanged |
| C11 stream pipeline | NOT RUN | code unchanged |
| C12 robustness | PASS (diff) | N3 crash fixed; a new runner with no data renders clean empty states |
| C13 performance | PASS | worst 183-day replay 1.7 s |
| C14 docs = code | FAIL carried | engine docs at v0.12.16; physio-brief map says `work.apply_limits`, but the function is `care_view.apply_clinical_limits` (minor doc drift) |
| D calibration | PASS core / FAIL carried | see the table |
| E1–E4 | NOT RUN | ingestion code unchanged |
| E5 Apple webhook | PASS | 401 with no or wrong token; invalid JSON → 400 |
| E6 cross-training | PASS (code) | unchanged |
| F1 CSRF | PASS | all new mutating routes have `verify_csrf`; exemptions are documented or have their own guard (feedback token, ingest token, `same_origin`); logout known/accepted |
| F2 access control | **FAIL** | R2, R3; otherwise 403 for unclaimed runners and runner→runner IDOR on all probed routes; `require_verified_physio` enforced |
| F3 sessions | FAIL carried | HttpOnly, SameSite=Lax, Secure by config; XFF bypass re-confirmed |
| F4 export/secrets | PASS | the documentation export has no password, token or hash strings |
| F5 external LLM | PASS consent gate / S3 R5 | consent gate added to brief, chat and conclusion draft; the name is still sent |
| F6 uploads | FAIL carried + S3 R7 | malformed imports → 500; the attachment allowlist, uuid name and realpath check are good |
| F7 access log | PASS | colleague card, documentation and export reads are logged and visible to the runner |
| G1 migrations | PASS (SQLite) | upgrade from the 2026-11-06 schema: 0 missing columns; Postgres NOT RUN |
| G2 seeding | PASS | second boot on a seeded and upgraded DB is clean; the demo accounts log in |
| G3 deploy | PARTIAL | `/api/health` 200; Docker NOT RUN; DEPLOY.md 65/72 missing; R4 |
| H1 tabs/overflow | PASS* | 58 loads, 0 px overflow; only the carried `/data` 403 |
| H2 Trénink nav | PASS | v3 only; the v1 direct URL shows a stub |
| H3 consistency | PASS in-app / FAIL R1 | v3 Dnes 66 = Zátěž 66 = API |
| H4 numbers | FAIL (S3 R6) | the runner app is clean; the physio brief has dot decimals |
| H5 Czech copy | PASS (minor R6) | no English leftovers except "baseline" |
| H6 empty/error | PASS (runner) | onboarding empty states and the "Server je chvíli nedostupný … Zkusit znovu" error state; physio empty states NOT RUN |
| H7 tap/contrast | FAIL carried | 17–19 px links; dark contrast NOT RUN |
| I1 no diagnosis | PARTIAL | no app diagnosis claims in the new physio copy; MDR note missing on Dnes/Zátěž/Mechanika (R8); tissue hypotheses are off by default (`DOSSLAP_TISSUE_HYPOTHESES`, D10), which is good |
| I2 evidence | PASS (new) | the one new citation (Daniels & Gilbert running equations, `vo2.py`): the coefficients match the published equations (VO2 = −4.60 + 0.182258v + 0.000104v²; %max = 0.8 + 0.1894393e^(−0.012778t) + 0.2989558e^(−0.1932605t)); checked against known values, not re-fetched online. Carried 8 reference items not re-audited. |
| I3 docs current | FAIL carried | v0.12.17–23, day pins and the physio app are undocumented in the engine PDF |
| Watchlist | PASS (re-run) / FAIL carried | replay parity and sandbox parity for every mode PASS; one-sided flags PASS; Czech formatting in generated text FAIL (R6); pace confound carried |

## Coverage gaps
- **Postgres:** the migrations and the 81 new column `add()` calls were verified on SQLite only.
- **Docker build:** no daemon.
- **Physio app, not covered:**
  - empty states, dark-theme contrast and the English locale;
  - the business and invoicing flows (`business.py`): invoices, packages, subscriptions and payments were not exercised end to end;
  - correctness of the round-2 F1–F19 fixes beyond their own tests.
- **Second clinic:** R2 and R3 were probed with members inserted straight into the throwaway DB, because invites need e-mail. Cross-clinic probes were not run (there is no login for phy-0002).
- **Phase D, not run:** segment checks, the 90-day demo replay table and the stream-runner parity case.
- **E1–E4 ingestion:** not re-run (code unchanged).
- **Team Console UI:** not driven (no owner account on the demo DB).
- **i18n `merge.py`:** not run, because extraction writes into the repository and this review is read-only.
- **References:** the one new citation was checked from known formulas; the web was not used.
- **Nothing real external** was contacted.

## Structural drift (playbook updates proposed)
- **New role "Physio care layer"** (what the runner is told after the physio's input):
  - discovery: `resolve_care_directive` · `apply_clinical_limits` · `def present(`;
  - hint: `backend/app/care_view.py`;
  - add a C8 item: "every runner-facing guidance surface (Dnes, Trénink, calendar feed, morning report) passes through it".
- **New role "Clinical records / practice":**
  - discovery: `doc_access` · `_own_record` · `_own_episode` · `has_care_assignment` · `def can(`;
  - hint: `app/records.py`, `app/work.py`, `routers/{records,work,business}.py`;
  - add to F2: "reception never reads clinical records (W1); per-patient access needs a care relationship unless an owner decision says otherwise".
- **Message attachments:** discovery `UPLOAD_DIR`, hint `routers/work.py`. Add to F6 and G3.
- **Ops scripts** `app/scripts/*` (backup, restore, key rotation, backfills, demo reset): add to G3. Today they are dry-run by default or production-guarded.
- **§2 product decisions:** new sign-ups start on v3 (`NEW_RUNNER_ENGINE`); a physio's W12 limit and `rtr_paused` stop running, in addition to the pain > 5 + referral override.
- **Frontend views:** add `frontend/src/physio/*.tsx` (queue, calendar, clients, plan, docs, business, messages, practice, today, visit, timeline), `recents.tsx` and `caretasks.tsx`.
- **Doc drift:** `docs/physio-brief-map.md:103` names `work.apply_limits`; the function is `care_view.apply_clinical_limits`.
