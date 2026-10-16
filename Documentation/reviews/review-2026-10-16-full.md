# Došlap review — 2026-10-16 (full review)

**Fix before the next release: still 3 × S1, all carried from 2026-10-05 and still untouched.** (1) Anyone can self-register as a physio and take over any runner's care and data. (2) Re-importing a Garmin or Apple file deletes the runner's own ratings and manual sessions, and returns 500 on Postgres. (3) The report "AI notes" send health data to the external LLM without the AI consent. **New this week (S2):** coach plan mode marks tomorrow's long run "Sedí s úpravou" during an active physio referral and hides the stop on Trénink. **The backend suite is red** (1 failing test; see F7).

Commit / working tree: `7212123` (Feedback #215, #216: previous weeks on Trénink, heart-rate values in the profile), `main` = `origin/main`, working tree clean, nothing uncommitted. `ENGINE_VERSION` v0.12.15, `HISTORY_VERSION` h11.

Baseline: tests **685 passed / 2 skipped / 1 failed**, 265 s on Python 3.11 (a rerun failed the same way, so it is not a flake) · `tsc --noEmit` OK · `vite build` OK (only the existing >500 kB chunk warning) · `python -m compileall` OK. Postgres 16 was installed locally for the migration and import checks.

How this review was run: the lead reviewer did phases A and B, verified the failing test and re-read the code behind every new S2. Six parallel sub-reviewers covered C, D, E+G, F, H and I+C14, each on its own throwaway SQLite DB and port. Nobody contacted the deployed app, Garmin, Apple, any calendar provider or any LLM (all keys unset). Web access was used only to verify references. Scratch scripts and the 106 screenshots are in `/tmp/rv/` of the review container and are not committed.

## Summary

Since the 2026-10-12 quick screen (`f4466c4`), 40 commits landed (≈30 k lines; 154 → 194 endpoints, 48 → 56 models since the last full review). The main additions:
- the goal planner "Plán k cíli 2.0", including a consent-gated risk path;
- coach plan mode with text/photo import, an ICS calendar feed and an anonymous coach link;
- usage analytics;
- Návyky, Kondice a únava, run detail with route and best-pace curve;
- shoes per run;
- activity de-duplication with tombstones;
- capacity memory changes v0.12.6–v0.12.10.

**The engine core is healthy:**
- v2/v3 calibration is on target per metric (4–6 %).
- Sandbox parity is exact for all 12 demo runners × v1/v2/v3.
- The physio override fires only for pain > 5 with a referral.
- Guidance km never exceeds min(ceiling, week room).
- No new wall-clock or mode-comparison bugs, no crash on degenerate runners.
- Live assessment ≤ 0.24 s; v3 183-day replay 12.9 s (S3-2 effectively fixed).
- Migrations from the previous commit work on SQLite and Postgres.
- The SSRF guard on the calendar feed is solid; only DNS rebinding and a missing total deadline remain (S3).

**The risk sits in the new layers built on top of the engine:**
- coach mode does not carry the physio stop forward (S2);
- de-duplication can delete a second pain rating (S2);
- the pace-confound false alarm is above its fail line once GCT is included (S2, an upgrade of S3-1).

**None of the three S1s or the open S2s from 2026-10-05 were fixed this period.** F9 was fixed on 10-12, F8 is partly fixed, and the quick screen's vert-ratio F1 is refuted (two-sided counting).

Counts (open items at HEAD, carried included): **S1 3 · S2 17 · S3 53 · S4 12.** New this run: S2 3, S3 32.

## Findings (most severe first)

### S1: carried, all re-verified at HEAD

### F1 Anyone can register as a physio and claim any runner (2026-10-05 F1) — STILL OPEN
Severity: S1 · Confidence: CONFIRMED · Area: F2 access control
Location: `backend/app/routers/auth.py:85` (`role = body.role if body.role in ROLES`), `backend/app/routers/triage.py:71-93` (`claim`)
What happens: public registration still accepts `"role":"physio"`. `claim` still checks neither consent, case status, an existing claimant nor a revoked assignment.
Failure scenario / Evidence:
- Live re-run: fresh physio `phy-0006` got 403 on run-0014's bootstrap.
- `PATCH /api/triage/14/claim` then returned 200, although the case was closed and `physio_interest=0`.
- After the claim, every call returned 200: bootstrap (32 kB), goal, plan, habits, fitness-trend, activities, daily, report.
- The same physio also took over triage 1, which phy-0001 had claimed (200).
- This week's new goal, plan and habits data is exposed through the same path.

Suggested fix: as in 2026-10-05 (claim requires consent + open + unclaimed + not revoked; no `role` on public registration). Test to add: `test_claim_requires_consent_open_unclaimed_unrevoked`.
Health-risk direction: privacy breach; unsafe training via plans pushed by an unverified "physio".

### F2 Re-importing a Garmin/Apple file wipes the runner's own data, 500 on Postgres (2026-10-05 F2) — STILL OPEN
Severity: S1 · Confidence: CONFIRMED · Area: E1
Location: `backend/app/routers/integrations.py:119-123` (`_apply_seed`, now inside the per-runner lock but otherwise unchanged)
Evidence: test client, run rated pain 7 plus a manual strength session, then re-import: feedback 2 → 0, manual activities 1 → 0. On Postgres 16 the second import fails with `ForeignKeyViolation activity_feedback_activity_id_fkey` and returns 500.
Suggested fix: merge by `external_id` like `_merge_seed`; never delete manual activities, ratings, exclusions or streams. Test: rate + manual + exclude → re-import → all preserved, with `PRAGMA foreign_keys=ON`.
Health-risk direction: false reassurance (the pain history is lost).

### F3 Report "AI notes" bypass the AI consent (2026-10-05 F3) — STILL OPEN
Severity: S1 · Confidence: LIKELY (keys off, so no external call is possible) · Area: F5
Location: `backend/app/routers/runners.py:1261-1272` (only `ensure_runner_read_access`), `backend/app/metrics/report_ai.py:118` (no `coach_consent` check)
Suggested fix / test: as in 2026-10-05 (rules text unless `coach_consent` is set and the runner themself asked; test that a mocked LLM is never called with consent off).
Health-risk direction: none (privacy/consent).

### S2: new

### F4 Coach plan mode: future sessions ignore an active physio referral, and the stop is hidden on Trénink
Severity: S2 · Confidence: CONFIRMED · Area: C8 / H3 (coach mode)
Location:
- `backend/app/metrics/coach_plan.py:60`: `NO_PERSIST = ("injury", "function", "bone_stress", "red_flag")` has no `"physio"`.
- `coach_plan.py:397-400`: only those kinds turn future days into "no".
- `frontend/src/training.tsx:1439-1450`: in coach mode the override banner (`TodayHero`) is only inside the collapsed "Alternativa Došlapu".

What happens: kritickepretizeni (v3) has pain 8/10 and "Dnes neběhat — objednejte se k fyzioterapeutovi (do 48 hodin)". With coach mode on:
- Tomorrow's coach-planned 24 km long run gets verdict `mod`, "Sedí s úpravou · předběžně · dnes se nevejde", with an empty `why` and a fit of 0 km. Sunday's 8 km run is the same.
- Meanwhile Výhled na zítra says "Zítra bez běhu" and the normal week plan says the plan is paused.
- The coach-mode Trénink page contains no "fyzio" and no "neběhat" text.

Failure scenario: a runner who trains with a coach sees tomorrow's long run as "fits with modification" two days into a 48-hour physio referral, with no mention of the pain on that page. Dnes does still show the stop, which is why this is S2 and not S1.
Evidence:
- `GET /plan` → `eval.days[1] = {"date":"2026-10-17","verdict":"mod","s":[{"k":"long","km":24,"v":"mod","why":[],"fit":{"km":0,"fits":false}}]}`
- screenshots `coach_training_q_400.png` / `.txt`
- the lead re-read `NO_PERSIST` and the persist branch.

Suggested fix:
- Add the physio override to the persisting kinds for the referral window, or while today's pain is above 5.
- Render the override banner above the coach section.
- Show a "mod" with a 0 km fit as "raději ne".

Test to add: `test_coach_plan_physio_override_blocks_tomorrow` (override physio + long run at n=1 → verdict "no"), plus a frontend check that the coach-mode Trénink contains the override title.
Health-risk direction: false reassurance.

### F5 Activity de-duplication deletes the second copy's rating, including a pain rating
Severity: S2 · Confidence: CONFIRMED · Area: E1
Location: `backend/app/metrics/engine.py:776-827` (`dedupe_activities`); the rating moves only `if keep.id not in rated`, then `delete_activity(db, x)`.
What happens: when both copies of a duplicated run were rated, the lowest-id rated copy is kept and the other copy's feedback is deleted with it. This runs on every boot (`main._dedupe_activities`) and on sync.
Failure scenario: before v0.12.11 a runner saw the run twice. They rated copy A "RPE 4, no pain" and copy B "pain 7, knee, niggle". After the next deploy only A remains, and the knee-pain signal and its physio routing disappear.
Evidence: probe `test_a1`: feedback (RPE, pain) before (4,0) and (6,7); after only (4,0). The lead re-read the merge branch.
Suggested fix: merge ratings (max pain, union of pain points, niggle = OR), or keep the copy with the highest pain. Test to add: a duplicated pair with pain 7 on the higher id still has pain 7 after the dedupe.
Health-risk direction: false reassurance.

### F6 Pace confound: "mechanika přetrvává" flag on 10.5–12.1 % of slower easy weeks (fail > 10 %); upgrades 2026-10-05 S3-1
Severity: S2 · Confidence: CONFIRMED · Area: D calibration
Location: `backend/app/metrics/engine.py:925-961` (`_pace_slope`), `:1036-1049` (linear speed adjustment), `:3255` (`_mech_flags`), consumed at `guidance.py:579`
What happens: the slope's estimation error, multiplied by the speed offset, is not in σ, so slower easy runs read as mechanical drift. The 2026-10-05 figure of 7.7 % came from a generator without GCT (`tests/test_drift_validity.py` has no `gct_ms`). With GCT included, the rate crosses the fail line. The drift code is unchanged since 7b9bd43, so this is not a regression; it was understated before.
Failure scenario: a v3 runner who jogs 25 s/km slower for 3 weeks (heat, fatigue) gets the flag about 11 % of the time. Guidance then blocks quality, halves descent room and halves Z4 minutes (`guidance.py:892, 1018, 1067, 1374`).
Evidence: realistic generator, 4 runs/week, 3 seeds × 1500:
- flag 10.5 / 12.1 / 11.4 %, against a null of 3.1–4.5 %;
- t4 noise 9.7–10.9 %;
- without GCT 6.7–7.6 %.
The silent-quadrant rate is fine (1.3–2.2 %).
Suggested fix: add slope standard error × speed offset to σ, or shrink a non-significant slope toward 0, or adjust on the s/km scale for pace-linear metrics. **Changes scores: needs an engine version bump and a calibration run.** Test to add: extend `test_slower_easy_runs_are_not_mechanical_drift` with `gct_ms`; flag rate ≤ 5 % at N ≥ 1000.
Health-risk direction: false alarm.

### S2: carried from 2026-10-05, re-checked this run

| ID | Item | Status at HEAD | Evidence this run |
|---|---|---|---|
| old F4 | v3 loses the terrain-weighted spike (`engine.py:1526` `_v2 = _emode() == "v2"`) | STILL OPEN | code |
| old F5 | History digest misses `Shoe` (now also `is_default`/`garmin_uuid`, which since v0.12.13 decide each run's shoe) and `ReturnToRun` | STILL OPEN, CONFIRMED | v3 runner + default shoe: live load 11→12, 12→13, 15→16; history `replayed 0` |
| old F6 | After an engine switch, live hysteresis uses the other engine's stored quadrant | STILL OPEN, CONFIRMED | run-0008: live `critical` vs history `overreaching`, same axes (v2 and v3) |
| old F7 | Critical-speed cache keyed on `(day, ids)` only (`speed.py:171`); the new `best_curve` shares it | STILL OPEN, CONFIRMED | CS None → None after streams → 3.156 after cache clear |
| old F8 | Dnes "Stabilní · Skóre 100 · nízké riziko" on bootstrap failure | PARTLY FIXED | new-runner Dnes is now neutral; still "Stabilní…" on bootstrap failure (`App.tsx:537, 590`) and in the desktop rail for a runner with no data (`shell.tsx:209-217`); `net_boot_400_app_today.png`, `h6_fresh_1360_app_today.png` |
| old F10 | One transient Garmin error disables auto-sync for everyone (`garmin_live.py:458-459`) | STILL OPEN | code unchanged |
| old F11 | A failed HRV/resting-HR range call loses the values | STILL OPEN | code unchanged |
| old F12 | Uploads unbounded; bad zip/XML → 500 | STILL OPEN, CONFIRMED | BadZipFile/ParseError → 500 |
| old F13 | Login throttle bypass via X-Forwarded-For | STILL OPEN, CONFIRMED | 8 × wrong → 429; new XFF → 401, then 200 |
| old F14 | Physio reads outside `/api/runners/` not access-logged | STILL OPEN, CONFIRMED | physio `POST /api/ai/brief` → 200, no log row |
| old F15 | Upper-abdominal pain matched to the lower-abdomen programme | STILL OPEN | `programs_library.py:475` |
| old F16 | Pain programmes framed as treatment of a diagnosis | STILL OPEN | Physiopedia links `:409, :474`, "úspěšné léčby" `:446` |
| old F17 | Not-a-medical-device note missing from most views | STILL OPEN | only `training.tsx:1489`, `landing.tsx:1081`, `coachview.tsx:53`; none on the new goal sheets, Kondice, reports, Skóre/Zátěž |
| old F18 | Shoe transition "6 weeks (Fuller 2017)" | STILL OPEN | `profile.tsx:495` |

(The old F9, evening report contradicting the week plan, was fixed on 2026-10-12.)

### S3: new this run

Tests / process
- **F7 Backend suite is red: `test_week_past.py::test_past_weeks` reuses the email `wp1@test.cz`, which `test_daily_report.py:238` also registers in the session-scoped test DB.**
  - Registration then returns no `runner_id`, giving `KeyError: 'runner_id'` (`tests/test_guidance.py:14`).
  - It passes in isolation and fails in every full run (2/2).
  - Introduced in the HEAD commit 7212123.
  - CONFIRMED. Fix: use a unique email (e.g. `wpast1@test.cz`).
- New test `tests/test_run_track.py:83-107` overwrites the `ActivityStream` of the shared demo runner Adéla and does not clean up (watchlist: tests mutating seeded accounts). CONFIRMED (code).

Engine / guidance
- Coach-plan sessions of kind "race" skip the room and ceiling check: a 42.2 km "Závod" against an 11 km per-run ceiling gets "ok" with empty `over` (`coach_plan.py:~424`). Pain rules still apply. CONFIRMED. False reassurance.
- After a long break the climb channels keep about 100 % (35 d), 91 % (45 d) and 63 % (60 d) of their weekly descent capacity, while volume is at its floor and per-run ceilings are gone (`capacity.py:610-620`, `CLIMB_HOLD 42`, no `RETURN_ACWR` limit for the climb channels in `_former`). This was an owner decision (v0.12.10), but the repeated-bout evidence covers muscle damage, not tendon or bone detraining. CONFIRMED. Product question too.
- The risk path is offered and kept during an energy hold (amenorrhoea 90+ days), after a stress fracture and in the first year of running. It widens the per-run maximum to +15 % on bone-loading channels (`goal_plan.py:1131`, `routers/goals.py:387-393`, `goal_plan.py:1535`). LIKELY. False reassurance.
- Goal `created_at` / `risk_consent_at` are stamped in UTC (`routers/goals.py:56`), but `goal_track.py:102, 124, 165, 244` compares `[:10]` with the engine's local date. A goal saved Monday 00:30 Prague starts tracking a week early. LIKELY.
- The rounded personal-tolerance factor (`capacity.py:578-579`, `round(f, 2)`) multiplies the margins (`:1914-1916`). This is the "rounded ratio used for points" watchlist pattern; the effect is ≤ 0.5 % of the margin. CONFIRMED.
- Opening a run's detail (GET) can store segments, elevation profile and start time through `fetch_run_track` → `_store_run_stream`, without `recompute_assessment` or `mark_dirty` (`runners.py:626-629`, `integrations.py:906-923`). Live and history stay stale until the next sync. LIKELY.
- Goal planner headline "Stihnete to bezpečně · > 95 % · Na cestě", and a 61 km week with a 22 km long run, shown directly under the "Dnes neběhat" physio stop. The limiting note is collapsed (`goal_plan.py:358, 1216-1218`). The date range prints "18. 10. 2026 a 18. 10. 2026". CONFIRMED (`goal_krit_400_*.txt`). False reassurance (mild).
- The coach-plan weekly review says "Plán držíte, bezpečné limity ne. Pokud se cítíte dobře, je to v pořádku" (`coach_plan.py:719`). LIKELY. False reassurance.

Calibration (phase D)
- v1 GCT false-signal rate 7.8–9.2 % (target ≈ 3.5 %). Cause: `gct_drift` uses a 14-day recent window with v1's single-run SD z (`engine.py:1191, 1084-1090`); with 28 days it is 3.8 %. CONFIRMED. False alarm.
- The GCT-balance signal uses absolute 0.4/0.8 pp cut-offs (`engine.py:1325-1342, ~3436`). False signal 4.7 % at per-run SD 1 pp, 17.9 % at 1.5 pp, 31.7 % at 2 pp. Demo runners have 0.12–0.55. Mechanism CONFIRMED, realism PLAUSIBLE.
- Segment significance has no minimum number of baseline sessions and ignores between-session variance (`engine.py:3068-3112`). With 1–2 baseline runs it gives 11–31 % of unchanged runs a "significant" segment (display only). The documented 5 × 1 case is nominal (4.4–5.2 %). CONFIRMED.
- On a freshly seeded DB every demo runner, including the "v3 critical" kritickepretizeni, is stored as v1: the model default is "v1", the v3 migration runs only when the column is added, and `seed.py` sets no mode (`models.py:88`, `main.py:78-80`). New deploys show no Trénink for the demos. CONFIRMED.

Ingestion / ops
- Dedupe also drops the dropped copy's `shoe_id`, `gear_uuid`, `mech_keep` and `weather_json`, and can keep a failed stream placeholder over a good stream (`engine.py:812-814`). CONFIRMED.
- Gear and route fetches turn any non-rate-limit error into a permanent "checked, nothing" mark (`gear_uuid=""`, `track_json={"v":1}`; `integrations.py:654-658, 931-932, 963-966`). CONFIRMED.
- The calendar-feed sync shares the auto-sync try block and runs after the AI texts (`main.py:192-203`), so an AI-text error skips every feed. `feed_stale` compares a Prague stamp with naive `datetime.now()`, which is UTC in the container: a feed counts as stale after 5 h instead of 3 h. LIKELY.

Security / privacy (phase F)
- Calendar feed DNS-rebinding TOCTOU: the host is validated with `getaddrinfo`, then httpx resolves again (`plan_import.py:339-392`). Impact is a blind internal :443 probe (https, port 443 and TLS verification still apply). CONFIRMED (simulated resolver).
- No total deadline on the feed fetch: the 8 s timeout is per read. A drip server held a worker for 40 s for 42 bytes. The nightly `sync_all_feeds` is sequential and `set_feed` is synchronous (`plan_import.py:331, 374`, `plan.py:162-178, 490`). CONFIRMED.
- Coach-link bearer tokens appear in plain text in access logs and in client-error paths (`/api/trener/{token}`, `plan.py:627-696`). The token grants 6 weeks of health data plus plan write access for 6 months. CONFIRMED.
- Usage analytics (`UsageDay`, per-tab seconds by name and e-mail for the owner) are undisclosed and not in the export. The export also lacks PlannedSession, Goal, Shoe, CoachLink/CoachAccessLog and AccessLog (`reports.py:207-214`), and there is no account-deletion route. CONFIRMED.
- Pasted plan text goes to the hosted LLM without prior notice, unlike the photo path (`plan_import.py:224-229`, `coach.tsx:567`). LIKELY.
- `POST /plan/import` with `week=9999-12-31` and `copy-week` with year 9999 → 500 (`plan.py:375, 405-407`). CONFIRMED.

Frontend (phase H)
- Duration/split formatters can print **"1:60 h"** and "2:60": they floor the minutes but round the remainder (`rundetail.tsx:20-23`, `runprofile.tsx:119`; the same pattern in `training.tsx:546`, `report.tsx:26-27`, `tabs.tsx:403, 2035`). Seen live on a 119.6-minute run. This is a variant of the watchlist "5:60" defect. CONFIRMED.
- Trénink and run detail stay on "Načítám…" forever when bootstrap fails; a `/goal` error shows "Nastavit cíl" as if no goal existed (`goal.tsx:1391`). CONFIRMED.
- Number consistency and units:
  - resting HR "57,7 tep/min" vs "obvykle 53" with no unit;
  - the HRV sheet shows 39 vs tile 38,9 vs chart 37 ms;
  - the best-pace axis repeats "4:40" and has no /km;
  - run-detail climb ↑52 m vs the per-km table 31 m;
  - mixed minus signs ("−107 %" vs "-106 %");
  - "16. 10.." has a double period.
  CONFIRMED.
- The coach view `/trener/:token` logs a 401 console error from `/api/auth/me`. CONFIRMED.
- Phone tap targets of 16–18 px on the new toggles (`capacity.tsx`, `goal.tsx`, `fitness.tsx`, `training.tsx`); fg-3 on a raised sheet is 4.42:1. CONFIRMED.

Evidence / docs (phase I, C14)
- The risk-path consent card's "zhruba 1,6×" is Frandsen 2025 (BJSM, HRR 1.64), but its Sources show Nielsen 2014 (novices, HR 1.59, p = 0.07). Frandsen 2025 is missing from `summaries.json` (`goal.tsx:810-814`, `goal_plan.py:127`). CONFIRMED.
- Citation years and attributions in the new knowledge entries:
  - Heikura is 2018, not 2017;
  - Kraus is BJSM 2019, not 2018, and is cited for nutrition advice it does not support;
  - Doherty is JSAMS 2020;
  - van Poppel is cited as 2020 vs 2021;
  - most new entries have `doi: null`.
  CONFIRMED.
- The engine documentation header still says v0.12.0, the summary says v0.11.0, v0.12.15 is missing, and the 45-minute Z4+ per-session cap (`guidance.py:110`) is undocumented. CONFIRMED.
- `METRIC_INFO.capacity` (`metricinfo.ts:45`) and the `capacity.py:22` / `goal_plan.py:43-47` docstrings omit the v0.12.6–v0.12.10 capacity rules (former level, recovery week, personal tolerance, climb memory). CONFIRMED.

### S3: carried, re-checked and still open
S3-3 (unknown engine mode → v1), S3-5 (CSRF with no Origin), S3-6 (raw session tokens, 400 days), S3-7 (guest settings), S3-8 (Apple `?token=` in the log), S3-10, S3-12 (the "rate" substring match, now copied into the gear/track code), S3-13 (naive local time, no TZ), S3-14, S3-15 (DEPLOY.md misses 41 env vars, none new), S3-17 (Apple payloads → 500), S3-18, S3-19, S3-20, S3-21 (partly softened in onboarding; `capacity.py:98`, `guidance.py:116` unchanged), S3-22, S3-23, S3-24 (partly: ride/swim and the week plan are now documented), S3-25 (Citlivostní analýza link for non-owners), S3-27 (informal "ty"/"rozklikni"), S3-29 (403 on /data for non-owners). That is 21 items.

## Fixed / closed since last review
- **S3-2** (v3 183-day replay 21.0 s): now 12.9 s (v1 1.7 s, v2 4.8 s) on a synthetic 6-month runner with streams. Effectively fixed (not the same runner).
- **2026-10-12 quick F1** (`vert_ratio_pct` 11 % for v2/v3): **refuted, please close.** That probe counted |z| ≥ 0.6 in both directions. The engine shows a signal only in the bad direction, and that rate is 4.2–5.8 % (3 seeds × 2000).
- **F8**: partly fixed (a new runner's Dnes card is neutral; see the table).
- **S3-1**: superseded by F6 (upgraded to S2).

## Product questions (not defects)
- Climb-channel memory after long breaks (v0.12.10): should the hold end, or be limited to the volume channel's return ratio, once there are fewer than 3 runs in 30 days?
- Should the risk path be blocked during an energy hold, after a past bone stress injury, and in the first year of running?
- Should kritickepretizeni and tichydrift be seeded as v3 with `running_since`? The playbook appendix treats them as v3 demos; on a fresh DB they are v1 and hit the profile gate.
- Playbook §2/C8 is still out of date (carried): new runners default to v3, the engine picker is owner-only, and the quality readiness gate is 65 %.
- "≈ 5 % false signal" is per metric. On 10–15 % (v2) or 13–17 % (v1) of no-change days at least one mechanics signal is listed. Consider wording the product statement per metric.

## Improvement proposals (S4)
Quick wins (< 1 h, no score change):
1. Fix the colliding test email (F7) and make test emails unique per file (e.g. prefix with the module name). Validation: full suite green.
2. Add `"physio"` to coach-plan `NO_PERSIST` for the referral window, and render the override banner above coach mode (F4). Validation: the new test in F4.
3. Merge ratings in `dedupe_activities` and fill `shoe_id`/`gear_uuid`/`mech_keep`/`weather_json` from the dropped copy (F5). Validation: dedupe probes as tests.
4. Round the total before splitting h:mm / m:ss in every formatter, using one shared helper like `lib.paceStr`. Validation: unit test at 119.6 min / 179.6 s.
5. Redact `/trener/*` and `?token=` in access logs, and hash coach, Apple and session tokens at rest.
6. Put the feed sync in its own try block before the AI texts, use `datetime.now(E.LOCAL_TZ)` in `feed_stale`, and add a 15 s total deadline to the feed fetch.
7. Seed the demo runners' `engine_mode` and `running_since`.

Larger work:
8. Merge-only file imports (F2), validated on SQLite with FK on and on Postgres.
9. Verified physio onboarding plus a consent-checked claim (F1).
10. One "engine inputs" registry used by `load_runner_data`, `as_of`, the history digest and the Excel replay (closes the old F5 class). Bumps `HISTORY_VERSION`.
11. Pace-confound σ fix (F6) and a v1 GCT window fix. **Both change scores: engine bump plus a calibration run.** Add `gct_ms` to `tests/test_drift_validity.py`.
12. An audit hook inside `ensure_runner_read_access` (closes the old F14), and add the new per-runner tables plus UsageDay to the export.

## Calibration table vs previous review (phase D)

| Check | Target / fail | This review (HEAD, N 1500–2000 × 3 seeds) | 2026-10-12 quick | 2026-10-05 full |
|---|---|---|---|---|
| Shown signal per metric, no change, v1 | ≈ 3.5 % | vert ratio 3.0–4.4, vert osc 3.5–4.6, cadence 0.2–0.6, **GCT 7.8–9.2 %** | 2.3 % (2 fields) | 3.5 % |
| …v2 (= v3) | ≈ 5 % / > 8 % | vert ratio 4.2–5.8, vert osc 4.2–6.2, GCT 3.4–4.5, cadence 0.5–1.1, balance 0–0.1; mean ≈ 3.7 % | 6.3 % (two-sided, refuted) | 3.1–5.8 % |
| "Mechanika přetrvává" flag, no change | ≈ 5 % / > 8 % | 3.1–4.5 % (realistic), 5.8–6.7 % (simple) | — | 3.9 / 6.0 / 5.2 % |
| Flag at 1 SD improvement | 0 % / > 1 % | 0.0–0.1 % | — | 0.0 % |
| Easy runs +25 s/km, form unchanged | ≤ 5 % / > 10 % | silent quadrant v1 1.3–1.5 %, v2/v3 1.3–2.2 %; **flag v2/v3 10.5–12.1 %** (null 3.1–4.5 %) | — | flag 7.7 % (without GCT) |
| Detection +1 SD over 14 d (v2) | ≈ 67 % / < 55 % | 63.3–65.9 % (4 runs/week); 67.4 % (test generator) | — | 70.3 % |
| Segment session drift SD, no change | 0.8–1.25 | 0.90–1.17 (regression), 0.96–1.03 (bucket) | — | NOT RUN |
| Segment significance FPR, 5-segment baseline | ≈ 5 % / > 7.5 % | 4.4–5.2 % raw, 0.2–0.9 % after FDR (but see the segment S3 on 1–2-session baselines) | — | NOT RUN |
| Demo accounts today (v3) | Tichý silent, Kritické critical | silent (mech 37); critical (load 66, symptoms 81) | critical | silent, critical |
| Stable demo runners, 90-day v3 replay, Zátěž ≥ 25 | ≤ ~30 % of days | 0–29 % (Kritické 30 %, not stable); v1 for comparison 7–39 % | — | 0–29 % (Kritické 31 %) |
| Physio override in guidance | only pain > 5 + referral | pain 6–8 + referral only; pain 6–8 without a referral → no running, no override | — | pain 7, 8 + referral |

Shift explanations: the mechanics and segment code is unchanged since 7b9bd43, so the differences in rows 1–7 come from the harness (GCT now included, 4 runs/week). In row 9, Kritické 34 → 30 % and max load 70 → 66 come from v0.12.6 (former level, b4a9e46). run-0006's mean 12.9 → 10.6 and run-0007's 10.3 → 8.7 come from v0.12.10 (climb hold, ebdcc7d). Reverting those changes reproduces f4466c4 exactly. v0.12.7 and v0.12.8 are inactive on the demo data.

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 40 commits since `f4466c4` (2026-10-12 quick), 59 since `7b9bd43` (last full) |
| A2 environment | PASS | Python 3.11.17 venv, Node 22.22.0; Postgres 16 installed for E/G |
| A3 backend tests | **FAIL** | 685/2/1, 265 s (526 → 688 tests since the last full; time ×1.6 with ×1.3 tests, while 6 sub-reviewers were also running); F7 |
| A4 frontend | PASS | tsc OK, build OK (chunk warning) |
| A5 compileall | PASS | |
| B1 discovery | PASS | every role located; drift below |
| B2 inventory | PASS | 194 endpoints / 23 routers, 56 models |
| B3 disappeared roles | PASS | none disappeared; new roles listed under drift |
| C1 mode plumbing | FAIL | old F4, S3-3 carried; new modules have no mode comparisons |
| C2 time | PASS (S3) | goal UTC stamps |
| C3 replay parity | FAIL | old F5, F6 carried; new PlannedSession/Goal are read only by guidance (NON_SCORING) |
| C4 caches | FAIL | old F7 carried; new zonecheck cache is display-only |
| C5 direction/units | PASS | |
| C6 rounded values | FAIL (minor) | personal tolerance `round(f, 2)` |
| C7 capacity invariants | PASS (concern) | climb hold after breaks |
| C8 guidance invariants | FAIL | F4 (coach mode + physio), coach "race" unchecked; core guidance PASS |
| C9 sandbox parity | PASS | 12 runners × v1/v2/v3 exact |
| C10 statistics | PASS | code unchanged; segment baseline-session S3 |
| C11 stream pipeline | PASS (S3) | SEG_VERSION 2 unchanged; GET run detail stores inputs without recompute |
| C12 robustness | PASS | 8 degenerate runners × 3 modes × 13 endpoints, no crash or NaN |
| C13 performance | PASS | live ≤ 0.24 s; v3 replay 12.9 s; goal preview ≤ 0.74 s |
| C14 docs = code | FAIL | 17/22 constants match; capacity info text, S3-22/23 |
| D calibration | FAIL (1 row) | F6; others on target |
| E1 idempotence | FAIL | F2 (S1), F5; tombstones and lock PASS |
| E2 rate limits/failures | FAIL | old F11, S3-10, S3-12; gear/track marks |
| E3 tokens | FAIL | encryption OK; old F10 |
| E4 auto-sync | PARTIAL | isolation OK; feed sync placement, S3-13 |
| E5 Apple webhook | PASS | token required; S3-17 |
| E6 cross-training | PASS | |
| F1 CSRF | PASS | all 195 routes introspected; only documented exemptions (+ `/api/trener/{token}` with its own same-origin check) |
| F2 access control | FAIL | F1 (S1); 4 actors × 130 routes otherwise 0 leaks; admin owner-only |
| F3 sessions | FAIL | old F13 |
| F4 export/secrets | PASS (S3) | `plan_feed_url` private; coach token in logs |
| F5 external LLM | FAIL | F3 (S1); plan import has timeouts and a fallback |
| F6 uploads | FAIL | old F12; plan import bounded |
| F7 access log / GDPR | FAIL | old F14; usage analytics undisclosed |
| G1 migrations | PASS | old DB → HEAD on SQLite and Postgres 16 |
| G2 seeding | PASS | idempotent; demo engine mode is a separate S3 |
| G3 deploy | PARTIAL | image build NOT RUN (no Docker daemon); S3-14/15 |
| H1 tabs/overflow | PASS (S3) | 0 px overflow everywhere; S3-29 403; coach-view 401 |
| H2 Trénink nav | PASS | |
| H3 consistency | FAIL | F4; goal headline during the stop |
| H4 numbers | FAIL | "1:60 h" and unit/consistency nits |
| H5 Czech copy | PASS (known S3-27) | no English leftovers in the new screens |
| H6 empty/error | FAIL | old F8 partial; endless "Načítám…" |
| H7 tap/contrast | FAIL (minor) | 16–18 px toggles |
| I1 no diagnosis / disclaimer | FAIL | old F15–F17; risk-path gating, coach "v pořádku" |
| I2 evidence | FAIL | 17 references verified, key new numbers correct; Frandsen/Nielsen mix-up, years; old F18, S3-18–21 |
| I3 docs current | PARTIAL | v0.12.6–14 documented; header and Z4 cap stale |

## Coverage gaps
- **Docker image build**: no daemon. **Real LLM, vision and ASR output**: keys off, so what leaves the app was judged from code. **Plan import and ICS parsing against real provider feeds**: no external network.
- **Demo data has no activity streams**, so the following were checked by code only:
  - route map and pace/HR strips;
  - track/route IDOR;
  - the run-detail stream-storing path (C11 S3).
  The 183-day performance figure is from a synthetic runner.
- **Browser not covered**: English mode, physio/employer/partner roles, the calendar-feed and plan-import UI, and the Co je nového sheet (code-read only, the menu click failed).
- **Phase D**:
  - no real-device noise data for the balance and segment findings;
  - population priors tested only for vert ratio;
  - pace confound tested only in the easy bucket;
  - no v2 replay for row 9.
- **Evidence**: 13 newer references were not verified on the web (Marqueste 2008, Nosaka 2001, Tyler 2016, Daanen 2017, Costa 2017, Miall 2018, Hoffman & Krishnan 2014, Jaén-Carrillo 2024, Knechtle 2011, Tanda 2011, Vesterinen 2016, Düking 2021, the TID papers). Toresdahl 2021, Doherty, Coyle 1984 and Taddei 2020 were only partly verified.
- **Not re-checked this run**: S3-4, S3-9, S3-11, S3-16, S3-26, S3-28, S3-30, S3-31, S3-32 (outside the touched areas).
- **Old F10** was confirmed by unchanged code, not reproduced again.
- **Side note from F**: a fresh runner gained 4 triage rows after one manual activity plus a recompute. Not investigated; worth a look.

## Structural drift (playbook updates proposed)
- **New engine-adjacent modules**: `metrics/goal_plan.py` (its `SRC` map is a second citation registry next to `sig_doc.py`), `goal_track.py`, `goal_sessions.py`, `goal_backtest.py`, `coach_plan.py` (note: it has its own `def simulate(`, which collides with the sandbox discovery search), `fitness.py`, `habits.py`, `run_track.py`, `zonecheck.py`, `energy.py`, `gaps.py`; plus `app/plan_import.py` (outbound feed fetcher, LLM caller). These are not in `history.NON_SCORING`, so editing them invalidates all cached history (safe, but costs performance).
- **New routers**: `goals.py` (13), `plan.py` (18, including the anonymous coach link `/api/trener/{token}`, a third actor type outside the `/api/runners` audit middleware, with its own `CoachAccessLog`), `usage.py` (first-party analytics, `UsageDay`). Add `/api/trener/{token}` (own same-origin check) to the F1 exemption list, and the coach link to the F2/F7 actors.
- **`RunnerData`** gained `planned` and `goals` (guidance-only; `as_of` does not filter them). `recompute_assessment` now writes `Goal` rows.
- **Ingestion**: de-duplication `engine.dedupe_activities` runs on boot (`main._dedupe_activities`) and on sync; `DeletedActivity` tombstones; per-runner `threading.RLock` in `integrations.py:100-115`, which assumes a single process.
- **Run detail**: `integrations.fetch_tracks` / `fetch_run_track` (`route_json` / `track_json`).
- **Capacity helpers**: `_former`, `_chronic`, `weekly_capacity_vals` (shared with the goal planner), `personal_tolerance`, `weak_night`.
- **Other**:
  - `serializers.PRIVATE` now holds field-level secrets, so new secret columns must be added there.
  - The assistant prompt is v5, but the `service.py` docstring says v3.
  - The `summaries.json` "category" field is now a topic letter, not an evidence grade.
- **Proposed addition to playbook §6** (regression watchlist): "test emails collide across files in the session DB → re-check with the full suite".
