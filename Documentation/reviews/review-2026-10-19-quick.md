# Došlap review — 2026-10-19 (quick screen)

Commit / working tree: `416ba77` (Mechanics judged as of the last run, not today — v0.12.16), `main` = `origin/main`, working tree clean, nothing uncommitted. `ENGINE_VERSION` v0.12.16, `HISTORY_VERSION` h11.

Baseline: tests **687 passed / 2 skipped / 0 failed**, 209 s on Python 3.11 · `tsc --noEmit` OK · `vite build` OK (only the existing >500 kB chunk warning) · `python -m compileall` OK.

How this review was run: against a throwaway SQLite DB (`/tmp/review.db` for the app run, separate temp DBs for the test suite and the simulation), port 8765. Nobody contacted the deployed app, Garmin, Apple or any LLM (all keys unset). Scratch scripts, the simulation and the four screenshots are in `/tmp/pw-check/` and `/tmp/claude-0/.../scratchpad/` of the review container and are not committed.

## Summary

Since the 2026-10-16 full review (`7212123`), exactly **one commit** landed: v0.12.16, "Mechanics judged as of the last run, not today." It changes a real engine behaviour — every mechanics window (baseline 29–84 days, recent 28 days, confidence, pace classes, equipment-step detection) now counts back from the day of the runner's last run instead of from today, so a morning without a run no longer moves the mechanics score (previously the same last run read as drift 18 → 22 → 26 over three days without running). As a drive-by, it also **fixes 2026-10-16's F7** (the backend suite's one failing test, a colliding test e-mail) — the suite is green again.

This review traced the new code path end to end: single entry point (`assess()` → `mech_anchor()` → `mech_scope()`/`_assess()`, no bypass), the engine's own `today_pinned`/`today_date()` helpers throughout (no wall-clock calls), dates compared on `[:10]`/ISO date parts, and the change applies uniformly regardless of engine mode. A synthetic sweep (N=150, v1/v2, below) reproduces the fix directly: 200/200 no-run-day re-assessments of 40 runners came back byte-identical on the mechanics axis. The per-metric statistical core (`_drift_z_core`) is untouched by this commit and the existing calibration tests (`test_drift_validity.py`, `test_mech_anchor.py`) pass. A v3 demo runner driven in the browser at 400 px (Dnes, Trénink, Zátěž, Mechanika) showed no console errors, no overflow, and the quadrant/Zátěž-score/mechanics-drift numbers agreed across all four pages.

**No new S1/S2/S3 found this run.** The three known S1s and the other carried S2/S3 items from 2026-10-16 were **not re-verified** — this commit does not touch auth, imports or the AI-brief code paths they live in, so they are assumed unchanged; see Coverage gaps.

## Findings (most severe first)

No new findings this run.

## Fixed / closed since last review
- **2026-10-16 F7** (backend suite red: `test_week_past.py` reused `wp1@test.cz`, colliding with `test_daily_report.py`): **fixed**, in the same commit as the engine change (`tests/test_week_past.py:11` now uses `wpast1@test.cz`, exactly the suggested fix). Suite is green: 687 passed / 2 skipped / 0 failed.

## Product/engineering observations (not findings)
- The `conf["asOf"]` date the engine now computes (the last-run day the mechanics axis is judged as of) is not shown anywhere in the UI (checked Dnes, Trénink, Mechanika at 400 px). Not a defect — nothing in the playbook requires it — but worth a line on Mechanika ("k běhu z 16. 10.") so a runner understands why the score didn't move on an off day. S4, quick win if picked up.
- Quick null simulation (N=150: 75 v1 + 75 v3 synthetic runners, no real drift, 4 runs/week with a 0–3-day gap to today) gave mechFlag ("mechanika přetrvává") 0.0 % v1 / 6.7 % v2 against the ≈5 % target (fail > 8 %). At N=75 that is 5 flagged runners — within sampling noise of a true 5 % rate (binomial 95% CI ≈ 2–15 %) and not a confirmed deviation; the 2026-10-16 full review's own N=1500–2000 run already found 3.1–4.5 %. Not logged as a finding; flag for the next full review to re-run at higher N since it touches the window this commit changed.

## Calibration table vs previous review (phase D, row 1 only — quick screen)

| Check | Target / fail | This screen (N=75×2, 1 seed) | 2026-10-16 full (N=1500–2000×3 seeds) |
|---|---|---|---|
| Any mechanics signal shown, no change | — (informational; per-metric target ≈3.5–5 %) | v1 21.3 %, v2 20.0 % (union of 7 correlated metrics) | 10–17 % (noted as a product question: "per metric" wording) |
| "Mechanika přetrvává" flag, no change | ≈5 % / >8 % | v1 0.0 %, v2 6.7 % (N=75, noisy) | 3.1–4.5 % |
| No-run-day mechanics stability (new this commit) | identical | **200/200 identical** (40 runners × 5 no-run days) | not applicable before v0.12.16 |

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 1 commit since `7212123` (2026-10-16 full review) |
| A2 environment | PASS | Python 3.11, venv rebuilt clean; Node (npm ci clean) |
| A3 backend tests | PASS | 687/2/0, 209 s — F7 fixed in this commit |
| A4 frontend | PASS | `tsc` OK, `vite build` OK (pre-existing chunk-size warning only) |
| A5 compileall | PASS | `app` + top-level `*.py` |
| Discovery (role touched by diff) | PASS | Only "Engine core / axes" (`def assess(`) touched; still at `backend/app/metrics/engine.py`, no drift |
| C1 mode plumbing | PASS | Single entry point (`assess()`); no direct `_emode()==` added; anchor applies to v1/v2/v3 alike |
| C2 time | PASS | New code uses `today_pinned`/`today_date()` only; no `datetime.now()`/`date.today()`/`time.time()` added; dates compared on `[:10]`/ISO date part |
| F1/F2 (new routes) | N/A | No new routers or endpoints in this diff |
| G1 (new columns vs migrations) | N/A | No model/schema changes in this diff |
| C3 replay parity / C9 sandbox parity | PASS | Covered by the full suite (sandbox- and replay-parity tests green); anchor is recomputed per call under `today_pinned`, so replay and live share the same path |
| Guidance override tests | PASS | Suite green; live browser check: pain 8/10 + referral → "Dnes neběhat" on Dnes and Trénink, consistently |
| Null simulation (phase D row 1) | PASS (noisy) | See calibration table; no-run-day stability 200/200 |
| H1/H2/H3 browser, v3 demo runner, 400 px | PASS | Dnes, Trénink, Zátěž, Mechanika: 0 px overflow, 0 console errors; quadrant (Kritická) / Zátěž 66 / mechanics drift agree across pages |
| Regression watchlist items touched by the diff | PASS | None of the section 6 items are in the touched code path (statistical core, σ/flag logic, segment code, stream pipeline all unchanged) |

## Coverage gaps
- **The three carried S1s** (physio self-registration/claim, re-import wiping data, AI-brief consent bypass) and the carried S2/S3 list from 2026-10-16 were **not re-checked** — out of scope for a 1-commit diff that touches none of their code paths. Confidence they are unchanged: HIGH (diff stat confirms only `engine.py`, two test files and docs changed).
- **Demo-runner seeding** (kritickepretizeni stored as v1 with no `running_since`/`weight_kg` on a fresh DB — 2026-10-16 S3) was independently reconfirmed live in the browser (profile gate appeared, engine_mode was "v1"); same known item, not re-logged. The browser check above was run after setting `running_since`/`weight_kg`/`mode=v3` through the API against the throwaway review DB only (Appendix A pattern), not the seed data itself.
- **Docker image build**: not run (no Docker daemon in this container).
- **Real LLM / Garmin / Apple**: keys unset, as required; not exercised.
- Full-suite reruns to confirm F7 is not a flake: ran the full suite once (green) plus the two colliding files in isolation (green); did not force the previous collision order to prove it's fixed by code rather than luck — the e-mail change (`wp1@test.cz` → `wpast1@test.cz`) makes a collision structurally impossible, so this is treated as CONFIRMED by code, not re-reproduced.

## Structural drift
None. No new routers, models, modules or roles in this diff; the one touched discovery-map role (engine core) is still at its documented location.
