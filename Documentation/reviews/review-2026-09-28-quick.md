# Došlap review — 2026-09-28 (quick screen)

Commit / working tree: `40eebca` (Engine v0.8.4: úpravy podle rešerše literatury), working tree clean, no uncommitted files.

Baseline: tests 321 passed / 2 skipped, 154.7 s · type-check OK · build OK · `python -m compileall` OK (Python 3.13 venv, per the Python-floor note from the last review).

## Summary

Since the last review (`4277a56`, 2026-09-25) the app grew substantially: 91 files, +16.3k/-2.5k lines across 30 commits — the v3 redesign follow-through, a new prevention/screening engine pass (v0.8.0–v0.8.4: thresholds plan, individual reference ranges, cross-training, an opt-in AI coach), run-context/weather, precomputed history, and in-app annotations tooling. Backend tests grew from 157 to 321 (all green), frontend type-check and production build are clean. Mode plumbing (C1), the v3 nav gate, CSRF coverage on new routes, new-column migrations (G1) and history-replay parity all check out, including a live-vs-history parity check I ran directly against the v3 demo runner (axes, quadrant and tier all matched). The physio pain-override in v3 guidance fired exactly on the documented condition (pain > 5 + referral) when exercised live. A fresh calibration probe (v1/v2/v3, N=300 null histories) landed within target (3.7 % / 5.0 % / 5.0 % against ≈3.5 %/≈5 %/≈5 %). One S3 finding carries over from the last review (still open, now narrowed to a specific code path); one previously-open S3 is now fixed; one new S3 cosmetic item. No S1 or S2 found. No "Full review recommended" trigger, but given the size of this diff a full review (phase D behavioural sweep beyond the quick probe, phases E–I) is worth prioritising soon rather than waiting for the next scheduled Friday if this Monday-to-Monday pace continues.

## Findings (most severe first)

### F1 (carried over, narrowed) Capacity-axis signal values still render with a period instead of the Czech decimal comma
Severity: S3 · Confidence: CONFIRMED · Area: Phase H (frontend/UX), regression watchlist ("Czech number formatting")
Location: `backend/app/metrics/capacity.py:881,888` (`val = f"×{s['ratio']}"`, `val = f"×{w['ratio']}"`); rendered verbatim by `frontend/src/ui.tsx:211` (`FactorBar`'s `{value}`)
What happens: The five new v3 capacity signals (`cap_volume`, `cap_intensity`, `cap_descent`, `cap_ascent`, `cap_systemic`) build their `val` string in Python with a bare f-string interpolation of a rounded float, so it always uses a `.` decimal point; `FactorBar` (and the Dnes/Zátěž signal cards that use it) render that string as-is with no `cs-CZ` reformatting. This is the same root cause flagged in the 2026-09-25 review, but the earlier examples (`tabs.tsx:1048-1052`, `App.tsx:759`) have since been cleaned up or no longer reproduce — the bug is now isolated to these two `capacity.py` lines. Neighbouring values in the same UI (e.g. the ACWR ratio "×1,68", weekly km "171,1 km") are correctly comma-formatted, so the inconsistency is visually obvious.
Failure scenario: Logging in as `kritickepretizeni@demo.cz` in v3 and opening Dnes or Zátěž shows "Objem nad kapacitou ×3.45", "Intenzita nad kapacitou ×4.66", "Celková zátěž nad kapacitou ×3.51" — all with a period — directly next to "Poměr zátěže (7:28 dní) ×1,68" which is correctly comma-formatted.
Evidence: Live browser screenshots (400 px, v3 demo runner, Dnes and Zátěž tabs) taken during this screen show the raw periods; `grep -n 'val = f"×{' backend/app/metrics/capacity.py` confirms the two call sites; `grep -n '{value}' frontend/src/ui.tsx` confirms no formatting is applied on render.
Suggested fix: Format the ratio with the same comma-swap the app already uses elsewhere (or keep `ratio` numeric in the payload and format it in the frontend via the existing `cs-CZ` helper) at `capacity.py:881` and `:888`. Test to add: a unit test asserting no `val` string produced by `capacity.assess_capacity`'s signal list contains a bare `.` followed by a digit.
Health-risk direction: none (cosmetic; the underlying ratios and point totals are correct).

### F2 (new) The Data-page engine picker still promises AI texts on Dnes/Trénink "in a later phase", but only the picker's own preview panel is unbuilt
Severity: S3 · Confidence: CONFIRMED · Area: Phase H (frontend/UX copy)
Location: `frontend/src/datapage.tsx:506`
What happens: `datapage.tsx:506` reads "Na záložkách Dnes a Trénink se texty objeví v další fázi; tady je zatím náhled" ("...the texts will appear on Dnes/Trénink in a later phase; this is a preview for now"). This is a different string from the one the 2026-09-25 review flagged (that one, about the Trénink tab itself, is now fixed — see below), but makes essentially the same kind of claim: it undersells what's already shipped. `frontend/src/App.tsx:695` already links out to Trénink from a guidance strip on Dnes, and the AI coach feature itself (`routers/coach.py`, `metrics/coach_texts.py`) is fully wired end-to-end (opt-in, background generation, `datapage.tsx:492` shows the text with a source label). Whether the daily/weekly AI text is meant to also surface as an inline strip on Dnes/Trénink (not just the Data-page preview) is a product decision I can't verify from the code alone — flagging this as a copy check rather than asserting the feature is incomplete.
Failure scenario: A runner who opts into the AI coach and reads this line may believe the feature is not yet active anywhere in the app, when the Data page directly above/below this line already shows their current AI-generated text.
Evidence: Code read of `datapage.tsx:472-506` (the AI-coach preview card, which shows real generated text on the same page as this "later phase" disclaimer) vs. `routers/coach.py` and `metrics/coach_texts.py` (feature fully implemented and reachable).
Suggested fix: Either confirm this is accurate (if Dnes/Trénink integration for the AI texts is genuinely still pending — in which case no fix is needed and this can be dropped in the next review) or update the copy to say where the text can be found today (the Data page card) instead of promising a future phase. Test to add: none (copy-only).
Health-risk direction: none.

## Fixed since last review
- The 2026-09-25 F2 ("Trénink tab arrives in a later phase" on the v3 engine description) is fixed: `datapage.tsx:141` now reads "...Odemkne záložku Trénink s denním doporučením" ("...unlocks the Trénink tab with daily guidance"), correctly matching the shipped feature.
- The 2026-09-25 F3 (engine module needing Python ≥3.12 for nested f-strings, no floor pinned outside Docker) is unchanged in the sense that `.python-version`/`runtime.txt` are still absent from the repo root — this review's own environment setup again needed an explicit `python3.13 -m venv` to avoid the same `SyntaxError`. Not re-listed as a new finding since it's already tracked; carrying it forward as still-open below rather than duplicating it as F-something.

## Improvement proposals (S4)
None beyond the fixes already described above.

## Calibration table vs previous review (phase D)
Fresh probe this screen (appendix B recipe, N=300 null histories per mode, seed 11):

| Check | Target | This screen | 2026-09-25 |
|---|---|---|---|
| Per-metric shown signal, v1, no real change | ≈3.5 % | 3.7 % | not run separately |
| Per-metric shown signal, v2, no real change | ≈5 % | 5.0 % | <8 % (existing test) |
| Per-metric shown signal, v3, no real change | ≈5 % | 5.0 % | not run |

All within target; no drift since the last review's v2 number.

## Coverage gaps
- Still open from 2026-09-25: no `.python-version`/`runtime.txt` pinning Python ≥3.12 at the repo root — this screen's environment setup again had to explicitly select `python3.13`.
- The full phase D behavioural sweep beyond the false-signal-rate row (the "mechanika přetrvává" flag rate, the improvement-flag null check, the silent-drift/pace-confound probes, segment significance) was not re-run this screen — relied on the passing `test_drift_validity.py`/`test_calibration.py`/`test_capacity.py` suite. Given the size of the v0.8.2–v0.8.4 diff (individual reference ranges, SWC dead zones, continuous point ramps), a full review should re-run these explicitly rather than trusting existing tests alone, since thresholds/scaling changed in ways that could shift calibration without breaking an existing assertion.
- IDOR probes (F2 in the rulebook's numbering), upload/zip handling (F6), GDPR access-log visibility (F7), container build end-to-end (G3), citation/evidence audit (I2), and the fuller Czech-copy/empty-state sweep (H5–H7) are full-review-only items per section 10 and were not run.
- Only three tabs (Dnes, Trénink, Zátěž) were driven in the browser, at 400 px only (per the quick-screen recipe); 1360 px and the remaining tabs are full-review scope.
- The Excel backtest replay (`reports.py::_replay_both`, the second "history replay" implementation named in the discovery map) does not copy the `Race` or `ReturnToRun` tables into its throwaway DB, unlike `history.py::engine_replay` which does. I traced this all the way through and confirmed it has **no observable effect**: both `races`/`returnToRun` are purely informational fields in `assess()`'s output (never feed `mech_score`/`load_score`/`symp_score`/`quadrant`/`tier`), and the Excel workbook never renders them. Recording as a coverage note rather than a finding, but flagging because it's exactly the shape of the regression-watchlist's "history replay omitted a table" item and is worth a comment in the code (or a parity test) so a future signal that *does* read the race calendar for scoring doesn't silently inherit the gap.
- The `annotations.py` `/export` and `/resolve` routes (new, bearer-token gated, disabled unless `DOSSLAP_FEEDBACK_TOKEN` is set to ≥24 chars) aren't in the rulebook's F1 exemption list yet — verified they're safe (token auth, not cookie-based, so CSRF doesn't apply, same shape as the documented Apple-webhook exemption) but proposing the playbook's known-exemptions list get this added (see Structural drift).
- The new opt-in "AI coach" feature (`routers/coach.py`, `metrics/coach_texts.py`, `metrics/llm.py`) calls the external LLM for the *runner's own* daily/weekly text, not only for the physio role as rulebook F5 currently states. Checked it directly: access control is `ensure_runner_self`/`ensure_runner_read_access` correctly, generation is gated behind explicit per-runner consent (`coach_consent`), calls have timeouts (60–120 s) with a non-LLM fallback, and the UI labels output as "AI" vs. "Sestaveno aplikací" depending on source. No bug found, but this is a new deviation from what F5 documents as the invariant — playbook update proposed below rather than a finding.

## Structural drift
- History replay's role split: the discovery-map hint (`routers/runners.py` → `_engine_replay`) has moved to a new dedicated module, `backend/app/history.py` (`load_inputs`/`engine_replay`, `HISTORY_VERSION = "h7"`, up from `h3` at the last review). `reports.py::_replay_both` (the Excel-backtest replay) is unchanged in location. Propose updating the discovery map's "History replay" row to point at `backend/app/history.py`.
- F1 (CSRF exemptions) in the rulebook should add the new `annotations.py` `/export` and `/resolve` routes (bearer-token gated via `require_feedback_token`, off by default) to the documented exemption list, alongside the sandbox and Apple-webhook entries.
- F5 (external LLM restricted to the physio role) is now broader in practice: a new, correctly-gated opt-in AI coach lets runners themselves receive LLM-generated text (`routers/coach.py`). Propose rewording F5 to "physio AI brief and the opt-in runner AI coach" and listing both call sites (`metrics/ai_brief.py`, `metrics/coach_texts.py`).
- Five new model tables since the last review (`Annotation`, `Race`, `CoachText`, `EngineDailySnapshot`, `EngineAlert`) — all correctly created via `create_all()` with no migration needed; noting for the discovery map's "Data model" section, which is otherwise unchanged (`backend/app/models.py`).
