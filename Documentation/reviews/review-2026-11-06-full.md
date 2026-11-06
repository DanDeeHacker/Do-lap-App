# Došlap review — 2026-11-06 (full review)

**Fix before the next release:**
- **The one open S1 is still the day pin (N2 from 2026-10-30).** It is untouched since it was reported a week ago and is re-confirmed today. A runner who reports a whole-body illness gets "volno" from the app. If they had pinned "lehký 18 km" for today, the pin still applies and shows 6.3–18 km. At pain 6/10 a pinned "regenerace" grows to 15 km. `guidance.py` has had no change since 2026-10-30.
- **The S2 crash that goes with it (N3) is also re-confirmed.** Pinning "dlouhý" for today still makes every recompute fail with a TypeError for a runner with no usual long-run day.
- **Nothing new reaches S1 or S2 this week.** The three merged PRs (Team Console multi-role, the running-statistics cards, the readiness wording) are clean apart from three minor items.

Commit / working tree: `9e89d83` (Team Console: several roles per person … (#13)). `main` = `origin/main`; the working tree was clean and nothing was uncommitted. `ENGINE_VERSION` v0.12.19 and `HISTORY_VERSION` h11, both unchanged.

Baseline: tests **772 passed / 2 skipped / 0 failed**, 172 s on Python 3.11, in a fresh venv (2026-11-02: 762/2/0, 258 s; +10 tests) · `tsc --noEmit` OK · `vite build` OK (only the known > 500 kB chunk warning) · `python -m compileall -q app *.py` OK · Node 22.23.4.

How this review was run:
- **One reviewer did all phases.** The runs were in-process engine scripts and a local uvicorn on a throwaway SQLite DB (`/tmp/review.db`, copied to `/tmp/rv/*.db` for each probe), plus headless Chromium (preinstalled Playwright).
- **Nothing external was contacted:** no deployed app, GitHub API, Railway, Garmin, Apple or LLM. `NVIDIA_API_KEY` and the ASR keys were unset.
- **Scratch files** are in `/tmp/rv` in the review container: `scripts/pins.py`, `parity.py`, `null.py`, `browse.js` and `shots/`.
- **`main` was not touched.**

## Summary

**What changed.** Since the 2026-10-30 full review (`6f4bdb9`), 4 commits landed: 47 files, +1 649 / −213, mostly i18n data.
- `32834fc` fixed 6 of the 7 items on the last release list. It was covered by the 2026-11-02 quick screen: N1, F1, F2, F3, N4, N5 and N6 are fixed.
- `d4ef5ca` changed the readiness wording at 100 %.
- `62f47a7` added four new "Moje čísla" cards: Čas tréninku týdne, Čas běhu týdne, Převýšení týdne and Poslední aktivita.
- `9e89d83` lets one person hold several team roles, adds member editing and lets an owner correct the e-mail of a pending invitation.
- **No engine, metrics or ingestion code changed.**

**What is healthy:**
- Live vs history: **39/39** identical (13 demo runners × v1/v2/v3: overall, quadrant, load, mech, symp).
- Sandbox vs live: **39/39** on the load and mechanics axes.
- Live recompute: 0.01–0.08 s warm. The worst 183-day replay took 4.7 s (limit 20 s).
- The null false-signal rates are within target on the Appendix B core recipe.
- Browser: 24 page loads at 1360/400 px (v1 adela, v3 kritickepretizeni), all with 0 px overflow. The only console error is the known 403 on `/data`.
- The new team endpoints refuse non-team users and cross-origin or no-Origin writes (403).
- The new `extra_roles` column has an additive migration.
- The i18n dictionary is in sync, and every new Czech string has an English entry.

**What went wrong:**
- **N2 and N3 are still unfixed and have no tests.** One week ago they topped the release list.
- **The new cards are cramped at phone width.** Labels and subtitles are cut off, and Převýšení shows "asi 0 pater" for 1 m of climb.
- **"Poslední aktivita" can name the wrong activity on a two-activity day.** Garmin Live stores dates without a time.
- **One commit trailer names a model again**, which CLAUDE.md forbids.

Counts (open items at HEAD, carried included): **S1 1 · S2 22 · S3 87 · S4 17.**
- New this run: S1 0, S2 0, S3 3, S4 2.
- Closed since 2026-10-30: S1 4 (N1, F1, F2, F3), S2 3 (N4, N5, N6) and S3 1 (`compare_digest`), all verified on 2026-11-02 and by tests that are green today.

## Findings (most severe first)

### S1 — carried, re-verified at HEAD

### N2 (2026-10-30) Day pins override the illness, pain > 5 and low-readiness stops and size runs up to the safety ceiling — STILL OPEN
Severity: S1 · Confidence: CONFIRMED (re-run today) · Area: C8 / D (guidance)

Location: `backend/app/metrics/guidance.py:1409-1427`.
- The pin branch checks only `pt["allowed"]` and the physio override.
- It then sizes the run with `hi = min(want, km["max"])`.
- The illness handling at `:1243-1245` blocks only dlouhý, kvalitní and posilování.

What happens: the code is the same as on 2026-10-30. Re-run on demo Pavel Urban (run-0006, v3, engine day 2026-11-06) with `/tmp/rv/scripts/pins.py`:

| Morning state | App's own pick | With a pin |
|---|---|---|
| Check-in `ill` + `ill_systemic` (screening `{'systemic': True}`) | **volno** (0 km) | pin "lehký 18 km" → **lehký 6.3–18.0 km, `applied: True`** |
| Pain 6/10 (knee), no referral | kolo | pin "regenerace 15 km" → **regenerace 3.7–15.0 km** (the type's own `hi` is 5.6) |
| Pain 6/10 | kolo | pin "lehký" → refused, `applied: False` (PASS) |

Failure scenario: a runner pins Friday as "lehký 18 km" on Monday. On Friday they report a fever with symptoms below the neck. Dnes, Trénink and the calendar feed still show an 18 km run.

Evidence: the script output above. No test covers the pin together with illness, pain or readiness: `grep -rn "pin" backend/tests | grep -i "ill\|pain"` returns nothing.

Suggested fix (unchanged):
- encode the no-run and reduced defaults as `block()` (illness → regenerace and lehký blocked; gscore < `READY_EASY_ONLY` → lehký blocked);
- cap the pinned km at the unpinned `types[t].km.hi`, not at `max`, and give the slider the same top;
- bump `ENGINE_VERSION`, label the PR `safety` and get clinical sign-off.

Test to add: `test_pin_respects_illness_pain_readiness`.

Health-risk direction: **false reassurance.**

### S2 — carried, re-verified at HEAD

### N3 (2026-10-30) Pinning "dlouhý" for today makes every recompute fail — STILL OPEN
Severity: S2 · Confidence: CONFIRMED (re-run today) · Area: C12

Location: `backend/app/metrics/guidance.py:1637` (`WD_IN[pat['longDay']]` when `longDay` is None).

Evidence: `pins.py` on run-0006 gives `TypeError: tuple indices must be integers or slices, not NoneType`, raised from `engine.py:4401 recompute_assessment → guidance.py:1637`.

Fix: `if typ == "dlouhý" and pat["longDay"] is not None:`.

Test: `test_long_run_pin_without_usual_long_day`.

Health-risk direction: none (availability: Dnes and Trénink stop updating).

### Old F13 Login throttle bypass via X-Forwarded-For — STILL OPEN, CONFIRMED today
Evidence: 14 wrong passwords, each from a new `X-Forwarded-For`, all returned 401 and never 429. The correct password then returned 200. From one IP, the throttle answers 429 after 8 tries.

### Old F11/F12 Malformed uploads return 500 — STILL OPEN, CONFIRMED today
Evidence: `POST /api/integrations/{garmin,apple}/import` with a corrupt `.zip` or with `{"a":1}` returns **500** on all four combinations. The upload is still read unbounded (`integrations.py:208`).

The other S2s carried from 2026-10-30 were not re-run. Their code is unchanged by this diff (no metrics, ingestion or physio-router change). They are:
- old F4–F8 and F10;
- 10-23 F4–F7 (the detection gate, the demo scenarios, technique wording and the pace confound);
- 10-16 F4 and F5;
- old F14–F18;
- N7 (third-party body-map images).

### S3 — new this run

### S3-1 The new "Moje čísla" running-statistics cards overflow at phone width and say "asi 0 pater"
Severity: S3 · Confidence: CONFIRMED · Area: H4 / H5

Location: `frontend/src/shell.tsx:172-189` (the `ttime`, `rtime`, `elev` and `last` cards) and `frontend/src/runstats.ts`.

What happens: at 400 px (`/tmp/rv/shots/v1_400__app_today.png`, `v3_400__app_today.png`):
- **Cut-off text:**
  - the label "Čas tréninku týdne" shows as "ČAS TRÉNINKU TÝ…";
  - the Převýšení subtitle shows as "1 m dolů · asi 0 pater (3 m = …";
  - the Poslední aktivita subtitle shows as "35 min · 4:42/km · 162 tep/mi…".
- **"asi 0 pater"** shows whenever the climb is under 1.5 m (adela: 1 m up).
- **"Převýšení týdne" counts running only** (`runstats.ts:18`), while the card next to it, "Čas tréninku týdne", counts all sports including walks and hikes. Neither card says so. Only the Čas běhu subtitle says "jen běh".

Failure scenario: a runner reads a truncated card, or "0 pater", and cannot tell what the number covers.

Suggested fix:
- shorten the labels ("Trénink za týden", "Běh za týden");
- let the subtitle wrap to two lines or drop the floors part below 1 floor;
- put "z běhu" in the elevation subtitle.

Test to add: extend `test_run_stats_cards.py` so that `floors` is reported only when it is ≥ 1.

Health-risk direction: none.

### S3-2 "Poslední aktivita" can show the earlier of two activities on the same day
Severity: S3 · Confidence: LIKELY (code path) · Area: H3 / E

Location:
- `frontend/src/runstats.ts:24-31` (`lastActivity` compares `started_at` strings and keeps the first of equal ones);
- `backend/garmin_live.py:117,131` (`started_at` = `startTimeLocal[:10]`, so a date with no time);
- `routers/runners.py` bootstrap orders by `started_at desc` with no tie-breaker.

What happens: Garmin Live stores only the date. A morning run and an evening ride on the same day therefore tie, and the card shows whichever row the database returns first. That is usually the one inserted first, i.e. the morning run. Manual entries are also date-only (`runners.py:917`).

Suggested fix: break ties by `id` (newest insert), or keep the activity's start time when Garmin gives it.

Test to add: two activities with the same date string; `lastActivity` returns the later-inserted one.

Health-risk direction: none.

### S3-3 Process: a commit trailer names a model again
Severity: S3 · Confidence: CONFIRMED · Area: process

Location: `62f47a7` (and its squashed sub-commits). The trailer is `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

What happens: CLAUDE.md says "Never put model names or identifiers in commits, PRs, code or docs". The same issue was reported for aa5dd97 on 2026-10-30. The other two commits this week use a neutral `Co-authored-by: Claude`.

Suggested fix: have the AI-team session's commit template drop the model name, and add a CI grep on PR commit messages.

Health-risk direction: none.

### S3 — carried, re-confirmed today
- **D1 (2026-11-02): CLAUDE.md still says "on a password account, the password"** (`CLAUDE.md:99`). The code requires the password on every account.
- **DEPLOY.md is still missing 54 of the 61 environment variables the code reads.** These include all the Team Console and persona variables.
- **Morning report: "Připravenost —" for v1 while the Dnes card shows "100 % Plná"** (adela, `v1_400__app_today.png`). The rule-based text is still labelled "Hodnocení AI".
- **Every non-owner gets a 403 console error from `/api/engine/outcomes` on `/data`** (4/4 loads today).
- All other carried S3s are in code this diff did not touch and were not individually re-run.

## Fixed / closed since last full review (verified 2026-11-02, tests green today)
- N1 invitations bound to an account (S1)
- F1 physio verification and claim rules (S1)
- F2 re-import merges instead of deleting (S1)
- F3 AI notes gated on consent (S1)
- N4 Inbox → GitHub sends no screen text (S2)
- N5 clinical sign-off tied to the head SHA, plus path-based gating (S2)
- N6 the physio "Skóre" direction (S2)
- `compare_digest` on bytes (S3)

## Product questions (not defects)
- **Self sign-off (issue #8, option b).** One person can now be owner and clinical guarantor, approve an `engine` or `safety` PR, and merge it. The review sheet and the audit log mark this (`routers/team.py:410-414, 477`). It works as designed, but it removes the four-eyes check that the clinical gate was built for, whenever that one person holds both roles. Should a second owner or an external clinical reviewer be required for `safety`?
- **"Čas tréninku týdne" counts walks and hikes.** The engine's day guidance leaves walking out (`guidance.py`, `sport != "walking"`). Is a walk "training" on this card?
- **Carried:** whether day pins may ever override a reduced or rest default (this review assumes not, per §2); the `share_with_physio` scope; whether v1/v2 runners should see the week-plan and calendar features; the 55 % detection target vs v0.12.17's worthwhile gate.

## Improvement proposals (S4)

**Quick wins** (< 1 h):
1. **Fix N3 now.** It is a one-line guard plus its test, and it does not depend on the N2 engine bump.
2. **Make the card copy fit (S3-1)** and break the `lastActivity` tie by id (S3-2).
3. **(new) A CI check that rejects model names in commit trailers (S3-3).** Example: `git log --format=%B origin/main..HEAD | grep -iE "(opus|sonnet|haiku|fable) [0-9]"` fails the job.
4. **Carried:** trust `X-Forwarded-For` only from Railway's proxy hop (old F13); catch `BadZipFile`, `KeyError` and `TypeError` in the import routes and return 400 (old F11/F12).

**Larger work:**
- **(new) A "release blockers" label on review findings.** N2 has now stayed open across two review cycles while three feature PRs merged. Example: the Team Console Práce view could refuse the merge button while an S1 `safety` issue is open, or at least show it.
- **N2 fix with an `ENGINE_VERSION` bump and clinical sign-off** (carried).
- **Recalibrate the worthwhile gate and the pace slope across pace classes** (carried).

## Calibration table vs previous review (phase D)
This run used the Appendix B **core recipe**: synthetic runners → `_drift_z_core` / `_mech_flags`, N = 300, seed 42, 90 days at about 4 runs a week, metrics not coupled to pace (`/tmp/rv/scripts/null.py`). The 2026-10-30 figures are **end-to-end** through `assess_data` with pace tertiles, so the two are not directly comparable. The scoring code is unchanged since 2026-10-23, so the end-to-end FAIL rows below are carried, not re-measured.

| Check | Target / fail | This review (core recipe) | 2026-10-30 full (end-to-end) |
|---|---|---|---|
| Shown per metric (z ≥ 0.6), no change, v1 | ≈ 3.5 % | VR 2.0, vosc 5.3, cad 1.3, GCT 2.7 | VR 0.1–0.4, vosc 0–0.2, cad 0–0.2, GCT 0.9–1.5 |
| …v2 | ≈ 5 % / > 8 % | VR 4.0, vosc 5.0, cad 4.3, GCT 3.0 — PASS | VR 1.0–1.5, vosc 0–0.4, cad 0–0.1, GCT 0.6–0.9 |
| "Mechanika přetrvává" flag, no change (v2) | ≈ 5 % / > 8 % | 4.0 — PASS | 1.9–2.4 |
| Flag at 1 SD improvement | 0 % / > 1 % | 0.0 (and 0 % shown) — PASS | 0.0 |
| Easy runs +25 s/km, v2 flag | ≤ 5 % / > 10 % | 2.3 (metrics not pace-coupled in this harness, so it does not test the confound) | **32.2–34.1 FAIL**, carried |
| Detection +1 SD over 14 d (v2) | ≈ 67 % / < 55 % | core z: VR 59, vosc 56, cad 57, GCT 61; flag 81 | **end-to-end 22–38 FAIL** (worthwhile gate), carried |
| Segment session drift SD | 0.8–1.25 | NOT RUN | 0.94–0.98 |
| Segment significance FPR | ≈ 5 % / > 7.5 % | NOT RUN | 4.68 / 4.79 |
| Demo accounts today (v3) | Tichý silent; Kritické critical | Kritické: readiness 20 %, "neběhat — objednejte se k fyzioterapeutovi"; quadrant not tabulated | FAIL (carried 10-23 F5) |
| Stable demos, 90-day v3 replay | ≤ ~30 % of days | NOT RUN (code unchanged) | 0–29 % |
| Physio override in guidance | only pain > 5 + referral | Pain 6 without referral → kolo or regenerace, no physio push — PASS. The pin bypass of the softer stops is N2 | PASS |

Shift explanation: the engine is unchanged. The core-recipe numbers are higher than the end-to-end ones because the core recipe has no worthwhile gate and no norm-level step. That is expected and shows no regression.

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 4 commits since `6f4bdb9`; 3 since the 11-02 quick screen |
| A2 environment | PASS | fresh `.venv` (Python 3.11), `npm ci`, Node 22.23.4, preinstalled Chromium |
| A3 backend tests | PASS | 772 / 2 / 0, 172 s |
| A4 frontend | PASS | tsc OK, build OK (chunk warning) |
| A5 compileall | PASS | `app` + top-level scripts |
| B1 discovery | PASS | every role at its 2026-10-30 location; new code in `runstats.ts` (frontend helper) |
| B2 inventory | PASS | no new endpoints; new column `team_members.extra_roles`; new rail/today card ids `ttime`, `rtime`, `elev`, `last` (cap 16) |
| B3 disappeared roles | PASS | none; `role_of` → `roles_of` (permissions now a union) |
| C1 mode plumbing | PASS (no change) / FAIL carried | no new modes; 4 `_emode() ==` sites, unchanged |
| C2 time | PASS | metrics wall-clock calls unchanged (today helpers, weather stamp, coach-text retention); `runstats.ts` uses the browser date (display only) |
| C3 replay parity | PASS | 39/39 (13 runners × 3 modes); the stream-runner case is NOT RUN (the demos have no streams) |
| C4 caches | PASS / FAIL carried | unchanged; old F7 carried |
| C5 direction/units | PASS core / FAIL carried | the improvement probe gives 0 %; the pace confound is carried |
| C6 rounded values | FAIL carried (minor) | unchanged |
| C7 capacity invariants | PASS | `capacity.py` unchanged |
| C8 guidance invariants | **FAIL** | N2 re-confirmed (illness → pinned lehký 18 km; pain 6 → regenerace 15 km); physio override PASS |
| C9 sandbox parity | PASS | 39/39 load + mech |
| C10 statistics | NOT RUN | code unchanged; 10-30 figures stand |
| C11 stream pipeline | NOT RUN | no stream code changed |
| C12 robustness | **FAIL** | N3 re-confirmed |
| C13 performance | PASS | warm recompute ≤ 0.08 s (profile: `assess_capacity` 0.10 s of 0.20 s cold); 183-day replay ≤ 4.7 s |
| C14 docs = code | FAIL carried | engine docs stop at v0.12.16; CLAUDE.md D1 |
| D calibration | PASS core / FAIL carried end-to-end | see the table |
| E1 idempotence | PASS (per 11-02) | re-import merges (F2 fixed); not re-run today |
| E2 rate limits | NOT RUN | code unchanged |
| E3 tokens | PARTIAL carried | old F10 |
| E4 auto-sync | PARTIAL carried | old F10 |
| E5 Apple webhook | FAIL carried (minor) | not re-run |
| E6 cross-training | PASS (code) | unchanged |
| F1 CSRF | PASS | all team.py mutating routes carry `verify_csrf`; no-Origin and foreign-Origin PATCH → 403 |
| F2 access control | PASS (diff) | a non-team runner gets 403 on `/api/team/me`, `members` GET/POST/PATCH; `roles_of` binds to `user_id`; a self owner-removal guard exists (tested) |
| F3 sessions | FAIL carried | XFF throttle bypass re-confirmed |
| F4 export/secrets | PASS (code) | no change |
| F5 external LLM | PASS (F3 fixed) / S3 carried | "Hodnocení AI" label on rule text |
| F6 uploads / privacy | FAIL carried | malformed uploads → 500 re-confirmed; N7 carried |
| F7 access log | PARTIAL carried | the client-list S3 is carried |
| G1 migrations | PASS (SQLite) | `extra_roles JSON` via `add()`; NULL handled in `member_roles`; Postgres NOT RUN |
| G2 seeding | PASS | a fresh DB seeds the demo accounts; the second boot was not re-run |
| G3 deploy | PARTIAL | `/api/health` OK (`db_persistent: true`); Docker NOT RUN; DEPLOY.md 54/61 missing |
| H1 tabs/overflow | PASS* | 24 loads, 0 px overflow; carried `/data` 403 console error |
| H2 Trénink nav | PASS (carried) | not re-clicked; v1 `/app/training` renders without error |
| H3 consistency | FAIL carried | morning report "Připravenost —" vs Dnes "100 %" (v1); S3-2 |
| H4 numbers | FAIL (minor) | S3-1 "asi 0 pater"; decimal commas, m:ss paces ("4:42/km", "5:47/km") and "1 h 35 min" are correct |
| H5 Czech copy | FAIL (minor) | S3-1 truncation; the new strings are good Czech; "Plná — nic ji dnes nesnižuje." is fine |
| H6 empty/error | NOT RUN | carried old F8 |
| H7 tap/contrast | NOT RUN | carried 16 px items |
| I1 no diagnosis | PASS (diff) / FAIL carried | the new copy makes no claims; F15–F17 carried |
| I2 evidence | NOT RUN | no new citations; the 8 carried reference items stay open |
| I3 docs current | FAIL carried | v0.12.17–19 and day pins undocumented |
| Watchlist | PASS (re-run items) / FAIL carried | replay parity and sandbox parity for every mode PASS; one-sided flags (improvement 0 %) PASS; seeded runners not mutated by tests (the suite is green with its own runners); pace confound and rounded ratio carried |

## Coverage gaps
- **Docker build:** no daemon.
- **Postgres migration** of `extra_roles`: not run (SQLite only).
- **Phase D end-to-end harness** (worthwhile gate, pace-coupled metrics, the runner's own pace tertiles): not re-built. Only the Appendix B core recipe was run, so the carried FAIL rows (detection, pace confound) are code-unchanged carries, not new measurements.
- **Not run:** segment checks (session drift SD, significance FPR), the 90-day demo replay table, and C13 with streams (the demos have none).
- **Browser:** the Team Console UI (multi-role checkboxes, member edit, share button, the self-sign-off banner) was checked by code and the new tests only. A browser run would need a `DOSSLAP_OWNER_EMAILS` account.
- **Browser, also not covered:** the physio app, empty and error states, tap targets and the English locale.
- **Carried S2/S3 items in untouched code** were not individually re-run. Re-confirmed today: N2, N3, the XFF bypass, upload 500s, D1, DEPLOY.md, the `/data` 403 and the morning-report "—".
- **References (phase I):** not re-audited, since there are no new citations.
- **Nothing real external** was contacted (no GitHub, Railway, Garmin, Apple or LLM).

## Structural drift (playbook updates proposed)
- **Team Console:** `role_of` is now a display helper. Permission checks use `roles_of` / `T.can(roles, …)`, so the discovery search should be `def roles_of` · `member_roles` · `extra_roles`.
- **New frontend helper `frontend/src/runstats.ts`** (week totals and the last activity, display only). Add it to the "Frontend views" row with discovery `weekStats` · `lastActivity`.
- **Carried from 2026-10-30 (not yet in the playbook):**
  - the Team Console, physio app, personas, day pins and calendar feed roles;
  - `sim_clock` as a legal clock source;
  - the C8 rule "a pin never overrides a no-run or reduced default";
  - the F1 exemption list additions;
  - measuring "shown" end-to-end as `norm ≥ 1`.
