# Došlap review — 2026-10-12 (quick screen)

Commit / working tree: `f4466c4` (EN: translate the week chart's table toggle and the quality session terrain), working tree clean, no uncommitted files.

Baseline: tests 570 passed / 2 skipped, 237.9 s (Python 3.11 venv) · `tsc --noEmit` OK · `vite build` OK (pre-existing >500 kB chunk-size warning only, not an error) · `python -m compileall` OK.

## Summary

Screened the 14 commits since the last report (the 2026-10-05 full review at `7b9bd43`): a morning tendon-pain-monitor feature (`tendon.py`, v0.12.1), evening day-tags for sleep confounders (`day_tags.py`, display-only), bedtime mobility suggestions, a strength/durability rewrite, the week-planner-driven evening report, and a large i18n/English-UI pass. Backend tests grew 526 → 570 (all green), type-check and build are clean.

**No new S1/S2 defect found in this diff.** The two new engine-relevant inputs were checked for the exact parity pattern the last full review flagged for shoes/RTR (F5): the new `TendonCheck` table *is* correctly wired into `history.py`'s replay digest (the `"tnd"` stream, `history.py:98`), so a tendon test changes history the same day it changes the live assessment — unlike shoes/RTR, which are still *not* in the digest (F5 remains open, see below). `DayTag` is correctly listed in `history.NON_SCORING` since the engine doesn't read it (matches the router's own comment). Mode plumbing, wall-clock calls, CSRF and access control on the two new routes (`/runners/{rid}/tendon-checks`, `/runners/{rid}/day-tags`) are all correct. No new model columns were added (only two new tables, handled by `create_all()`), so G1 is not applicable this round.

**Three S1 defects from the 2026-10-05 full review remain open and unaddressed by this diff** — worth flagging again since they are release blockers, not routine findings: (1) anyone can self-register as a physio and claim/take over any runner's care (`triage.py` — zero lines changed since the full review); (2) re-importing a Garmin/Apple file still unconditionally deletes the runner's own activities, daily metrics and feedback before re-inserting (`integrations.py:_apply_seed` — untouched; the one nearby change, `delete_activity`, is for the unrelated single-activity delete flow from `48881df`); (3) the AI report notes endpoint still has no `coach_consent` check before (would-be) calling the external LLM (`report_ai.py` — no `coach_consent` reference anywhere in the file or its caller). One good sign: **F9 (evening report's "Zítra"/"Zbytek týdne" contradicting the week plan) is now fixed** — `_rest_of_week` was rewritten to read directly from the week planner (commit `a41bb2b`), with new tests (`test_rest_of_week_is_the_week_plan`, `test_every_evening_card_names_the_same_plan`).

One new S3: the fresh null-signal probe (phase D row 1, N=300) shows `vert_ratio_pct` running noticeably hotter than `cadence_spm` for v2/v3 (11.0% vs 1.7% shown-signal rate) — combined they're within the ~5%/fail->8% target band, but the per-field split hasn't been reported before and is worth the Friday full review's attention. The code computing this (`_drift_z_core`, `mech_priors`) is untouched by this week's diff, so this is not a regression from these 14 commits — a pre-existing characteristic this screen happened to measure for the first time at this granularity.

Browser check (v3 demo runner, 400 px): Dnes, Trénink and Zátěž all render with 0 px overflow and no console errors; the Dnes quadrant ("Kritická") and the Zátěž headline ("Zátěž 70 je nad prahem 25") agree; numbers use the Czech decimal comma throughout; the Dnes "Hodnocení AI" card shows the rule-based fallback text (LLM keys were left unset per the rules of engagement, so this run can't confirm or refute F3's consent gate against a real call — code read already shows no consent check, as above).

## Findings (most severe first)

### F1 `vert_ratio_pct` shows a much higher null-detection rate than `cadence_spm` for v2/v3 — worth a dedicated calibration pass
Severity: S3 · Confidence: PLAUSIBLE (fresh probe, not reproduced against the project's official calibration harness) · Area: Phase D calibration
Location: `backend/app/metrics/engine.py` (`_drift_z_core`, `mech_priors`) — code unchanged since the last full review
What happens: a quick per-field null-signal probe (appendix B recipe, N=300 synthetic 90-day null histories per mode, same generator as `tests/synth.py`/`tests/test_drift_validity.py`, threshold `|z| ≥ 0.6`) shows, for identical "no real change" synthetic runners: `cadence_spm` shown 0.3% (v1) / 1.7% (v2, v3); `vert_ratio_pct` shown 4.3% (v1) / **11.0%** (v2, v3). The combined two-field average (2.3% v1, 6.3% v2/v3) sits inside the documented target band (≈3.5%/≈5%, fail only above 10%/8%), but `vert_ratio_pct` alone for v2/v3 is above the v2 fail threshold (>8%) if judged on its own.
Failure scenario: a v2/v3 runner whose only drifting signal is vertical ratio is more likely than other metrics to get a "mechanika se mění" flag on pure noise — a false alarm, not a missed real drift.
Evidence: `/tmp/claude-0/.../scratchpad/null_probe.py` (not committed), run against this commit: `v1 cadence_spm: 1/300=0.3%`, `v1 vert_ratio_pct: 13/300=4.3%`, `v2/v3 cadence_spm: 5/300=1.7%`, `v2/v3 vert_ratio_pct: 33/300=11.0%`.
Suggested fix: no code change proposed from this screen alone — the full review should re-run phase D broken out per field (not just combined/averaged as the last two reports did) across more seeds to confirm this is real and not this screen's own generator artifact, then decide whether `vert_ratio_pct`'s prior/noise-scale needs recalibrating.
Health-risk direction: false alarm (alarm fatigue / needless flags on vertical-ratio-only noise).

## Fixed since last review
- **F9** (2026-10-05 full review: evening report's "Zítra"/"Zbytek týdne" ignored the week plan and could contradict a stop/physio override) — fixed in `a41bb2b`: `daily_report._rest_of_week` now reads directly from the same week planner the Monday sheet uses, including `plan.get("override")`. New tests `test_rest_of_week_is_the_week_plan` and `test_every_evening_card_names_the_same_plan` pass.

## Still open (carried from the 2026-10-05 full review, not re-verified in depth this screen)
- **F1** (S1) — physio self-registration + unguarded `claim()` lets any new physio account take over any runner's care. `backend/app/routers/triage.py` has zero diff since the full review.
- **F2** (S1) — Garmin/Apple file re-import still deletes the runner's own activities/daily-metrics/feedback before inserting the file. `backend/app/routers/integrations.py:_apply_seed` unconditional `.delete()` calls are unchanged.
- **F3** (S1) — the AI report-notes endpoint (`report_ai.py`) still has no `coach_consent` gate before it would call the external LLM.
- **F5** (S2) — `Shoe` and `ReturnToRun` rows are still not in `history.py`'s input digest, so history can disagree with a live assessment after a shoe is added/edited. (By contrast, this screen confirms the new `TendonCheck` input *was* wired in correctly — see Summary.)
- Everything else listed as open S2/S3 in the 2026-10-05 full review was out of this quick screen's scope and was not re-checked.

## Improvement proposals (S4)
None new this screen.

## Calibration table vs previous review (phase D)

| Check | Target | This screen (N=300, seeds 0–299) | 2026-10-05 full |
|---|---|---|---|
| Per-metric shown signal, v1, no real change | ≈3.5 % | 2.3 % combined (cadence 0.3 %, vert_ratio 4.3 %) | 3.5 % |
| …v2/v3 | ≈5 % | 6.3 % combined (cadence 1.7 %, vert_ratio **11.0 %** — see F1) | 3.1–5.8 % (3 seeds) |

Only the per-metric drift-signal row was re-probed this screen (per section 10 item 6); the other phase D rows (flag rate on real improvement, +1 SD detection, pace-confound flag rate, segment drift/significance) were not re-run and rely on the green test suite, same caveat as previous quick screens.

## Coverage gaps
- Phase D: only `cadence_spm` and `vert_ratio_pct` were probed (2 of the scored mechanics fields); the other mechanics metrics (GCT, GCT balance, stride length, etc.) were not re-probed this screen.
- F1/F2/F3/F5 (carried over) were confirmed **still open by code read** (diff absence / grep for the missing guard), not re-reproduced live this screen — the full review already reproduced each with evidence.
- Browser check: only the v3 demo runner (`kritickepretizeni@demo.cz`), only 400 px, only three tabs (Dnes/Trénink/Zátěž) — Deník/Pohyb/Péče, 1360 px, other roles and a v1/v2 runner were not driven.
- Citations for the new tendon-test feature (Silbernagel 2007, reused; Malliaras 2015, new) were read in the code's own docstrings but not independently verified against the source papers this screen (phase I, full-review scope).
- Did not probe the new `day-tags`/`tendon-checks` endpoints for IDOR beyond the code read of `ensure_runner_self`/`ensure_runner_read_access` shown in Summary.

## Check results (quick screen, section 10)

| # | Check | Result | Note |
|---|---|---|---|
| 1 | Phase A baseline (tests, type-check, build) + diff since last report | PASS | 570/2/0, 237.9 s; tsc OK; build OK; compileall OK; 14 commits since `7b9bd43` |
| 2 | Discovery searches for roles touched by the diff | PASS | tendon.py, day_tags.py, mobility.py, self_programs.py/runners.py routes, models.py — all located, no drift beyond what's noted below |
| 3 | Mode plumbing / wall-clock (C1, C2); CSRF + access-check for new routes (F1, F2) | PASS | no `_emode() ==` or wall-clock calls in touched files; new routes CSRF- and access-controlled correctly |
| 4 | New model columns vs startup migrations (G1) | N/A | only 2 new tables (`TendonCheck`, `DayTag`), no new columns on existing tables — no migration needed |
| 5 | Replay parity (C3) and sandbox parity (C9); guidance override tests | PASS | `TendonCheck` correctly in `history.py`'s digest (`"tnd"` stream); `DayTag` correctly in `NON_SCORING`; full suite (incl. C9/override tests) green |
| 6 | Quick null simulation (N≈300) for per-metric false-signal rate | PASS (combined), see F1 | v1 2.3 %, v2/v3 6.3 % combined — within target band; `vert_ratio_pct` alone elevated for v2/v3, flagged as S3 F1 above |
| 7 | One v3 demo runner in browser at 400 px: Dnes, Trénink, Zátěž | PASS | 0 px overflow, 0 console errors on all three tabs; quadrant/headline consistent; Czech decimal comma throughout |
| 8 | Regression watchlist items touched by the diff | PASS | none of the 16 watchlist items intersect this diff's touched code (checked capacity.py rounding, test isolation, sensitivity.py — untouched) |

## Structural drift
- New tables since the last report: `TendonCheck` (`backend/app/models.py`), `DayTag` — both new tables, not new columns, so `create_all()` covers them with no migration needed.
- New metrics modules: `tendon.py` (morning tendon-pain-monitor test, feeds `engine.pain_monitor`), `day_tags.py` (evening confounders, display-only, in `history.NON_SCORING`), `mobility.py` + `mobility_library.py` (evening bedtime-mobility suggestions, display-only, not an engine input), `coach_validate.py`.
- New runner-facing routes in `backend/app/routers/runners.py`: `GET/POST /{rid}/tendon-checks`, `GET/PUT /{rid}/day-tags` — both correctly access-controlled (`ensure_runner_read_access` / `ensure_runner_self`) and CSRF-covered on the mutating verbs.
- `HISTORY_VERSION` moved `h10` → `h11` (expected, new scoring input added).
- `ENGINE_VERSION` moved `v0.12.0` → `v0.12.4`.
