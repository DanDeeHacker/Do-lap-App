# Došlap review — 2026-11-23 (quick screen)

Commit / working tree: `5581de8` (merge of PR #25, "Merge pull request #25 from DanDeeHacker/claude/physio-round2"). `main` = `origin/main`; working tree clean, nothing uncommitted.

**There is no diff to screen.** `main`'s HEAD (`5581de8`) is the exact same commit reviewed by both the 2026-11-20 full review and the 2026-11-16 quick screen — zero commits have landed since then. `ENGINE_VERSION` is still `v0.12.23`, `HISTORY_VERSION` is still `h11`, both exactly as last reported.

Baseline: tests **963 passed / 2 skipped / 0 failed**, 285.86 s on Python 3.11 (fresh venv) — identical pass/skip/fail counts to the 2026-11-20 full review (272 s) and the 2026-11-16 quick screen (321 s); this run's duration sits between the two, no 2× jump · `tsc --noEmit` OK, no errors · `vite build` OK (only the known > 500 kB chunk-size warning, unchanged) · `compileall app *.py` OK · Node 22.23.5.

## Summary

Nothing changed in the repository since the last full review four days ago, so this quick screen found **no new findings** (S1 0 · S2 0 · S3 0 · S4 0). The baseline is exactly as green as last time, and the one carried item this screen's checklist happens to touch — the `test_drift_validity.py` fixture-ordering fragility — is unchanged (still reproduces standalone). The real news is what is *not* fixed yet: the 2026-11-20 full review's three S2 findings (calendar feed ignoring physio "no run" directives; clinic-wide access to clinical records without a care assignment; message attachments lost on redeploy) remain open, since no commit has touched any of that code. This screen did not re-verify them (out of quick-screen scope, and nothing moved to re-check); treat them as still outstanding until a PR closes them. No action needed from this cycle beyond that reminder.

## Findings (most severe first)

None this cycle — no diff, no new behaviour to probe.

## Carried — not fixed, not re-verified this cycle (see the cited report for full evidence)

| ID | Item | Severity | Status |
|---|---|---|---|
| R1 (2026-11-20 full) | Calendar feed ignores the physio's "Dnes bez běhu" and other care directives | S2 | Open — code untouched since 2026-11-20 |
| R2/R3 (2026-11-20 full) | Clinical records readable/correctable by any colleague at the same clinic, not just the treating clinician (widens 2026-11-16's F2) | S2 | Open — code untouched since 2026-11-20 |
| R4 (2026-11-20 full) | Message attachments stored on local container disk, lost on redeploy without a volume | S2 | Open — code untouched since 2026-11-20 |
| S3-3 (2026-11-06, improved 2026-11-16) | Commit trailer naming a model, against CLAUDE.md | S3 | Not re-checked this cycle (no new commits to check) |
| S3-2 (2026-11-06) | `runstats.ts` same-day tie-break by plain string compare, not true row/time order | S3 | Not re-checked this cycle (file untouched) |
| F1 (2026-11-16, re-confirmed today) | `tests/test_drift_validity.py`'s four tests only pass because an earlier test in the same pytest run creates the schema via `TestClient`; run standalone they fail with "no such table: activities" | S3 | **Re-verified today, still open**: `pytest tests/test_drift_validity.py -q` → 4 failed, same as 2026-11-16. Not a CI risk (deterministic order), still fragile against `-k`, standalone runs while editing mechanics-drift code, or future `pytest-randomly`/`xdist` adoption. |

## Calibration table vs previous review (phase D)

Not re-run this cycle — no engine or guidance code changed since the calibration figures in the 2026-11-16 quick screen and 2026-11-20 full review, so there is nothing new to calibrate. The existing calibration test (`test_v2_false_signal_rate_is_calibrated` in `tests/test_drift_validity.py`) passed as part of the 963-test green run (it only fails in the standalone-ordering scenario above, which the full suite run does not hit).

## Check results (section 10, quick screen)

| # | Check | Result | Note |
|---|---|---|---|
| 1 | Phase A baseline (tests, type-check, build) and diff since last report | **PASS** | 963/2/0, 285.86 s; `tsc` OK; `vite build` OK; **diff since 2026-11-20 is empty — HEAD unchanged** |
| 2 | Discovery searches for any role touched by the diff | N/A | No diff |
| 3 | Mode plumbing / wall-clock (C1, C2); CSRF and access-check listing for new routes (F1, F2) | N/A | No diff, no new routes |
| 4 | New model columns vs startup migrations (G1) | N/A | No diff, no new columns |
| 5 | Replay parity and sandbox parity tests (C3, C9); guidance override tests | PASS | `test_engine_history.py` + `test_history_precompute.py` + `test_pin_safety.py` (20 tests) pass; engine/history/guidance code unchanged since last report so results are definitionally unchanged |
| 6 | Quick null simulation (v2 false-signal rate, phase D row 1) | PASS | `test_v2_false_signal_rate_is_calibrated` passed inside the full suite run; engine's `_drift_z_core`/`_mech_flags` are byte-for-byte unchanged since the figure was last measured (2026-11-16) |
| 7 | One v3 demo runner in the browser at 400 px: Dnes, Trénink, Zátěž | PASS | `kritickepretizeni@demo.cz`, switched to v3 via `POST /api/runners/{rid}/engine`: all three tabs render with 0 horizontal overflow (`scrollWidth − clientWidth`) and 0 console errors; Trénink correctly shows "Dnes neběhat — objednejte se k fyzioterapeutovi" for pain 8/10 + referral; Zátěž shows 66/100 "zvýšená", consistent with Dnes's overreaching headline (H3) |
| 8 | Regression watchlist items touched by the diff | N/A | No diff |

## Coverage gaps

- The three carried S2 items from the 2026-11-20 full review (R1, R2/R3, R4) were **not re-verified** this cycle — quick-screen scope and time budget don't cover phases E/F reproduction work, and nothing changed in the files involved, so there was nothing new to check. They stay open until a fix PR lands; the next full review should re-confirm their status regardless.
- No browser pass at 1360 px, and no other demo accounts (adela/v1, physio, employer/partner) — the quick screen only calls for the one 400 px v3 check.
- No Postgres or Docker build check (no Postgres instance or Docker daemon available in this environment) — unchanged limitation from every prior cycle.
- Nothing real external was contacted — no GitHub, Railway, Garmin, Apple or LLM calls; `NVIDIA_API_KEY` and ASR keys left unset throughout.

## Structural drift

None — no files moved or roles changed since the 2026-11-20 full review's structural-drift notes, which already cover the physio-app additions.
