# Došlap review — 2026-11-09 (quick screen)

Commit / working tree: `4dd668d` (merge of PR #5, "Merge pull request #5 from DanDeeHacker/claude/review-2026-10-30-safety"). `main` = `origin/main`; working tree clean, nothing uncommitted. `ENGINE_VERSION` **v0.12.21** — see Findings, this is itself the top finding this run. `HISTORY_VERSION` h11, unchanged.

Baseline: tests **793 passed / 2 skipped / 1 FAILED**, 193 s on Python 3.11, fresh venv (2026-11-06: 772/2/0, 172 s; +21 tests, +1 failure) · `tsc --noEmit` OK · `vite build` OK (only the known > 500 kB chunk warning) · `python -m compileall -q app *.py` OK. Node 22.x, npm `ci` clean.

How this review was run:
- In-process engine scripts and a local uvicorn on a throwaway SQLite DB (`/tmp/review.db`), plus headless Chromium (pre-installed, not Playwright's own download).
- Nothing external was contacted: no deployed app, GitHub API, Railway, Garmin, Apple or LLM. `NVIDIA_API_KEY` and ASR keys were unset.
- Scratch files are in `/tmp/rv` in the review container: `scripts/parity.py`, `pins.py`, `null.py`, `browse.js`, `browse2.js` and `shots/`.
- `main` was not touched; nothing was committed there.

## Summary

**What changed.** Since the 2026-11-06 full review (`9e89d83`), 7 non-merge commits landed on three branches that were merged into `main` back-to-back: the N2/N3 day-pin safety fix (`e149454`, engine v0.12.20), the resting-heart-rate-of-the-day display (`01b1e37`/`e2aa6ee`, engine v0.12.21), and the app's own VO2max estimate (`8e28557`, engine v0.12.22), plus the "tap a running-statistics card to see recent activities" feature (`9690b56`).

**The good news: the one open S1 is fixed.** N2 (day pins overriding illness/pain/low-readiness safety stops) and N3 (pinning "dlouhý" with no usual long-run day crashing every recompute) — both carried across the 2026-10-30, 2026-11-02 and 2026-11-06 reviews — are fixed in `e149454` and verified live today on demo Pavel Urban (`run-0006`, v3):

| Morning state | App's own pick | With a pin |
|---|---|---|
| Illness, systemic | volno | pin "lehký 18 km" → **refused** (`applied: False`); lehký's own ceiling now `pinMax: 8.2` instead of `max: 18.0` |
| Pain 6/10, no referral | voda (cross-training) | pin "regenerace 15 km" → **refused** (`applied: False`) |
| Pain 6/10 | voda | pin "lehký" → refused (unchanged, still PASS) |
| No usual long-run day, pin "dlouhý 14 km" | — | **no crash**, pin applied, type = dlouhý |

`backend/tests/test_pin_safety.py` (12 new parametrized cases) passes, and replay/sandbox parity hold (36/36 = 12 demo runners × v1/v2/v3).

**The bad news: `main`'s own test suite is red**, and the cause is the same pattern that hid N2/N3 for two weeks — three AI-team branches edited `ENGINE_VERSION` independently and a merge silently dropped two of the three bumps. See S2-1 below.

**Other new items:** the recurring commit-trailer process defect (CLAUDE.md: "never put model names … in commits") is worse this run, not fixed (carried S3-3, see below).

Counts (new findings this run only; carried items are listed separately and not re-counted): **S1 0 · S2 1 · S3 0 (carried item re-confirmed, not new) · S4 0.**
Closed since 2026-11-06, verified today: **S1 1 (N2), S2 1 (N3).**

## Findings (most severe first)

### S2 — new this run

#### S2-1 `ENGINE_VERSION` on `main` doesn't match the code that shipped, and a test that checks this is failing
Severity: S2 · Confidence: CONFIRMED (reproduced: `pytest` fails) · Area: C14 (docs/constants = code), process

Location: `backend/app/metrics/engine.py:38` (`ENGINE_VERSION = "v0.12.21"`); `backend/tests/test_vo2_estimate.py:58` (`test_the_engine_version_names_the_change`, asserts `== "v0.12.22"`); `backend/app/metrics/vo2.py` docstring (self-describes as "v0.12.22").

What happens: three AI-team branches each bumped `ENGINE_VERSION` from the same base (`v0.12.19`) independently — `e149454` (day-pin safety) → `v0.12.20`, `01b1e37` (resting HR) → `v0.12.21`, `8e28557` (VO2max) → `v0.12.22`, each with its own changelog sentence prepended to the constant's comment. The three branches were merged into `main` one after another (`b3dfcb1`, then the resting-HR branch, then the VO2max branch); the merges did not reconcile the three edits to the same line, and the version that survived on `main` is `v0.12.21` (resting HR only). Both the day-pin safety fix's `v0.12.20` entry and the VO2max estimate's `v0.12.22` entry are gone from the changelog comment, even though **the code for both features is present and working** (verified above for N2/N3; VO2max's own tests — equation values, highest-of-four selection, trend integration — all pass). Only the one test written specifically to catch a dropped version bump (`test_the_engine_version_names_the_change`) fails, because it's the only check that names an exact value rather than "changed from the base".

Failure scenario: `main`'s test suite is red right now (`1 failed, 793 passed`). CLAUDE.md's own gate — "CI must be green" (workflow step 4) and "bump it when the engine's output changes and say what changed in the commit" (Conventions) — is violated on `main` itself, not just on a branch. Any new PR branched from current `main` inherits this failing test, so its CI will show red through no fault of the new change, until someone either bumps `ENGINE_VERSION` to `v0.12.22` (and folds the day-pin and VO2max changelog lines back in) or edits the test. The Team Console merge button requires "CI green on the exact head SHA" — this does not block a merge on its own (the check is per-PR, not per-`main`), but it means every open or future PR now carries a failure that has nothing to do with its own diff, which is exactly the kind of noise that gets a real regression ignored or a red check "fixed" by weakening the test (forbidden by rule 6).

Evidence: `pytest -q` output: `FAILED tests/test_vo2_estimate.py::test_the_engine_version_names_the_change` — `AssertionError: - v0.12.22 / + v0.12.21`. `git show <commit>:backend/app/metrics/engine.py | grep ENGINE_VERSION` across the 7 commits confirms the sequence v0.12.20 → v0.12.20 (merges) → v0.12.21 → v0.12.22 → v0.12.21 (final, after the last merge) — i.e. `8e28557`'s own bump to `v0.12.22` was overwritten by a later merge of the resting-HR branch.

Suggested fix: bump `ENGINE_VERSION` to `v0.12.22` (or higher) on `main` now, with a changelog comment that mentions all three changes (v0.12.20 day-pin safety, v0.12.21 resting HR, v0.12.22 VO2max) so the history string stays a true record; consider a cheap CI guard that fails when a PR's `ENGINE_VERSION` isn't strictly newer than `main`'s, specifically to catch this merge-order problem before it reaches `main` again.

Test to add: a CI step, not a unit test — `git diff origin/main...HEAD -- backend/app/metrics/engine.py` must show `ENGINE_VERSION` changed whenever other files under `backend/app/metrics/` changed and the diff isn't display-only (hard to automate precisely; at minimum, re-run the full suite after every merge into `main`, not only per-branch).

Health-risk direction: none (no runner-facing output is wrong — both shipped features work; this is a version-bookkeeping and CI-hygiene defect).

## Carried — confirmed still open or worse (not newly introduced by this diff's substance)

| ID | Item | Status |
|---|---|---|
| S3-3 (2026-11-06) | Commit trailer names a model (`Co-Authored-By: Claude Sonnet 5.5` / `Claude Opus 5.5`), which CLAUDE.md forbids | **WORSE** — 6 of the 7 non-merge commits since 2026-11-06 carry a model name in the trailer (`e2aa6ee`, `8e28557`, `01b1e37`, `2a27022`, `95283a5`, `e149454`); only `9690b56` uses the neutral `Co-authored-by: Claude` |
| S3-2 (2026-11-06) | `lastActivity` in `runstats.ts` ties same-day activities by database row order, not by time | Code unchanged by this diff (`frontend/src/runstats.ts:24-31` still compares `started_at` with plain `>`); the new `recentActivities`/`RunStatSheet` feature (feedback #231) surfaces more of the activity list to the runner but doesn't change the tie-break |
| N7, old F11–F18, D1, DEPLOY.md gaps, pace confound, etc. (2026-10-23 through 2026-11-06) | Not touched by this diff's files; out of this quick screen's scope | Not re-run — see Coverage gaps |

## Check results (section 10, quick screen)

| # | Check | Result | Note |
|---|---|---|---|
| 1 | Phase A baseline | **FAIL** | tests 793/2/**1 failed** (S2-1); tsc OK; build OK (chunk-size warning only); compileall OK; diff since `9e89d83` is 7 non-merge commits (+ merges), 26 files, +539/−23 |
| 2 | Discovery for touched roles | PASS | all touched code is in files already on the section-4 map (`guidance.py`, `capacity.py`, `engine.py`, `fitness.py`, `week_plan.py` under "Engine core/axes" and "Capacity"; `runstats.ts`, `shell.tsx` under "Frontend views" per the 2026-11-06 structural-drift note); new file `app/metrics/vo2.py` and `frontend/src/recents.tsx` — propose adding both to the discovery map (see Structural drift) |
| 3 | C1 mode plumbing | PASS (no change) | `_emode() ==` count still 4, same sites as 2026-11-06; no new engine mode |
| 3 | C2 wall clock | PASS | `grep -rn 'datetime\.now\|date\.today\|time\.time'` over every touched metrics file returns nothing |
| 3 | F1 CSRF / F2 access, new routes | N/A | no new or changed backend routes in this diff (`git diff --stat -- backend/app/routers` is empty) |
| 4 | New model columns vs migrations | N/A | no changes to `backend/app/models.py` |
| 5 | C3/C9 replay & sandbox parity | PASS | 36/36 (12 demo runners × v1/v2/v3): live `overall`/`quadrant`/`mech`/`symp`/`load` match `history.engine_replay` for today |
| 5 | Guidance override tests | PASS | `test_pin_safety.py` (new, 12 cases) passes; live re-run above confirms N2/N3 fixed; physio override (pain > 5 + referral, no pin bypass) unaffected and correct |
| 6 | Null simulation (Appendix B core recipe, N=300, 90 days) | PASS | v1 shown 2.3 % (target ≈3.5 %), v2 shown 5.3 % (target ≈5 %, fail >8 %), v2 "mechanika přetrvává" flag 1.7 % (target ≈5 %, fail >8 %) — all within target; expected, since no mechanics/scoring code is in this diff |
| 7 | Browser, one v3 demo runner at 400 px | PASS | `kritickepretizeni@demo.cz`, Dnes/Trénink/Zátěž: 0 px overflow on every tab, 0 console errors; the demo correctly shows "Dnes neběhat — objednejte se k fyzioterapeutovi" (pain 8/10 + referral, readiness 20 %) |
| 8 | Regression watchlist items touched by the diff | PASS | "Sandbox diverged from the engine when a mode was added" — N/A, no new mode; "History replay omitted a table" — re-checked by the replay-parity run above (36/36); "Pace confound" / "Noise scale" / "Rounded ratio" — not touched by this diff |

## Coverage gaps
- **Postgres migration**: not applicable this run (no model changes), not re-verified either way.
- **Docker build**: no daemon available.
- **1360 px width, other demo accounts, physio app, Team Console UI, English locale, empty/error states, tap targets**: not covered — quick screen only calls for the one 400 px v3 check.
- **"Kondice a únava" sub-tab (where the new VO2max line shows) was not screenshotted**: this demo account (`kritickepretizeni`) has an incomplete profile and a "Doplňte prosím profil" modal blocks UI navigation past the morning report before that sub-tab can be reached headlessly in the time available; VO2max correctness was instead confirmed by its own passing unit/integration tests (`test_vo2_estimate.py`, all but the version-name test).
- **All S2/S3/S4 items carried from 2026-11-06 in files this diff didn't touch** (XFF login-throttle bypass, malformed-upload 500s, DEPLOY.md's 54 missing variables, CLAUDE.md's D1 password wording, the `/data` 403 console error, the morning-report "Připravenost —" vs Dnes 100 % disagreement, reference audit, etc.) were not individually re-run this cycle — see the 2026-11-06 full review for their status.
- **Nothing real external** was contacted (no GitHub, Railway, Garmin, Apple or LLM).

## Structural drift (playbook updates proposed)
- **New engine module `backend/app/metrics/vo2.py`** (VO2max estimate from the best-effort curve, called from `fitness.trend`). Add to the discovery map under "Engine core/axes" or a new "Fitness/VO2max" row: discovery `def estimate(` · `vo2_cost` · `share_held`.
- **New frontend file `frontend/src/recents.tsx`** (`RunStatSheet` — the sheet behind the four "Moje čísla" running-statistics cards). Add to "Frontend views": discovery `RunStatSheet` · `recentActivities`.
- **Capacity readiness inputs gained a `dayRhr` channel** (`capacity.py: readiness_inputs`) parallel to the existing `hrv`/`rhr`/`sleep` — worth noting in the C7/C8 "Guidance invariants" discovery note if a future check iterates readiness input keys.
