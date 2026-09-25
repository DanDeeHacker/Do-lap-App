# Došlap review — 2026-09-25 (quick screen)

Commit / working tree: `4277a56` (Engine v3 (Kapacitní) + Trénink tab, v2 engine fixes, review playbook), working tree clean, no uncommitted files.

Baseline: tests 157 passed / 2 skipped / 0 failed, 42.1–42.7 s (two runs) · type-check OK · build OK · `python -m compileall` OK (see note under Coverage gaps about the Python version needed to get here).

## Summary

First run of this playbook — no `Documentation/reviews/` history and no `claude/reviews` branch exist yet, so this screen covers the last 20 commits (through `4277a56`, "Engine v3 (Kapacitní) + Trénink tab"), the largest of which adds the whole v3 capacity/guidance engine and the Trénink tab. Backend tests (157), frontend type-check and production build all pass cleanly. Mode plumbing (C1), wall-clock hygiene (C2), CSRF coverage (F1) and the v3 nav gate (H2) all check out — the shared `_sensitive()` helper is used correctly wherever mechanics logic must treat v2 and v3 alike, and the four remaining direct `_emode() == "v3"` comparisons are all in the (correctly) v3-specific load/capacity branch. The one past regression this diff touches directly — history replay omitting a table for v2/v3 (`ActivityStream`, i.e. stored segments) — was caught and fixed in this same commit (`_HISTORY_VERSION` bumped h2→h3, new `test_v2_history_replays_segment_streams`), so it is not open. No S1 or S2 issues found; three S3 cosmetic/portability issues below. No "Full review recommended" trigger.

## Findings (most severe first)

### F1 Signal and metric values render with the wrong decimal separator for Czech users
Severity: S3 · Confidence: CONFIRMED · Area: Phase H (frontend/UX), regression watchlist ("Czech number formatting")
Location: `backend/app/metrics/capacity.py:480,485`, `backend/app/metrics/engine.py` (e.g. lines 1907, 1937, 1973, 1994, 2005, 2010, 2017, 2037, 2042 — every `f"×{...}"` signal `val`); `frontend/src/tabs.tsx:1048-1052`, `frontend/src/App.tsx:759`
What happens: Several numeric values reach the runner with a `.` instead of the Czech `,` decimal separator, both in backend-built strings (`val`/`detail` on signal cards, e.g. `f"×{s['ratio']}"`) that the frontend renders verbatim (`{s.val}` in `tabs.tsx:833/1003`, `App.tsx:759`), and in frontend template literals that skip the app's own `cs-CZ` formatters (`` `×${L.ratio}` ``, `` `${L.gradeAdjKm7}` `` in `tabs.tsx:1048-1052`) even though the same files already have `mfmt`/`toLocaleString("cs-CZ")` helpers used elsewhere.
Failure scenario: Logging in as `kritickepretizeni@demo.cz`, switching to v3 and opening Dnes/Zátěž shows "Objem nad kapacitou ×3.4", "Prodloužený kontakt se zemí z +2.15", "Poměr 7:28 ×1.68", "Efektivní km 171.4" — all with a period, next to correctly-formatted neighbours like "486 %" and dates. Reads as a foreign/broken locale to a Czech runner.
Evidence: Screenshots taken during the quick screen's browser check (`/app/today`, `/app/load` at 400 px, v3 mode) show the raw periods; `grep -n 'f"×{' backend/app/metrics/*.py` and `grep -n '\.val\b' frontend/src/*.tsx` confirm the code path (verbatim string pass-through / raw template literal, no `cs-CZ` formatting).
Suggested fix: Either format these values in Python with the same comma-swap the frontend already does for other fields (or keep them numeric and let the frontend format them), and route the four `tabs.tsx:1048-1052`/`App.tsx:759` interpolations through the existing `mfmt`/`toLocaleString("cs-CZ")` helpers instead of raw template literals.  Test to add: a snapshot/unit test asserting no `s.val`/formatted metric string produced by the v2/v3 signal set contains a bare `.` followed by a digit.
Health-risk direction: none (cosmetic; the underlying numbers and decisions are correct).

### F2 Data-page engine description says the Trénink tab is a future phase, but it already ships in this build
Severity: S3 · Confidence: CONFIRMED · Area: Phase H (frontend/UX copy)
Location: `frontend/src/datapage.tsx:139`
What happens: The v3 "Kapacitní" engine description on the Data page reads "Citlivá mechanika + zátěž proti vaší vlastní kapacitě … Záložka Trénink s denním doporučením přibude v další fázi" ("… the Trénink tab with daily guidance will arrive in a later phase"), but `frontend/src/training.tsx` and the v3 nav gate (`App.tsx:211-215`) already ship a fully working Trénink tab with daily guidance in this very commit.
Failure scenario: A runner reading the engine picker on the Data page is told a feature isn't available yet, when switching to v3 (as confirmed live in this screen) immediately surfaces it.
Evidence: Code read of `datapage.tsx:139` vs. `training.tsx` and the live browser check (Trénink tab present, populated, in the nav bar right after Dnes for the v3 demo runner).
Suggested fix: Drop the "přibude v další fázi" clause from the v3 description now that the tab ships. Test to add: none needed (copy-only change); a snapshot test on the engine picker copy would catch future drift.
Health-risk direction: none (stale copy, not a scoring or referral issue).

### F3 The engine module requires Python ≥3.12 syntax but nothing outside the Docker image pins that version
Severity: S3 · Confidence: CONFIRMED · Area: Phase A (environment/portability)
Location: `backend/app/metrics/engine.py:2176`; `backend/requirements.txt` (no Python floor); no `.python-version`/`runtime.txt` in the repo
What happens: `f' (obvykle {round(seff['base'] * 100)} %)'` nests an f-string inside an f-string using the *same* quote character, which is a `SyntaxError` before Python 3.12 (PEP 701). `Dockerfile` pins `python:3.13-slim` for production, but the repo has no `.python-version`/`runtime.txt`/README note, so a contributor or CI job that does the obvious `python3 -m venv .venv` gets whatever `python3` resolves to locally.
Failure scenario: On this review container, plain `python3` resolved to 3.11.15, and `pip install -r requirements.txt && pytest` failed immediately with `SyntaxError: f-string: unmatched '['` while importing `app.main` — the whole app and every test are unrunnable until the venv is rebuilt with `python3.13`. Reproduced exactly as described (see Coverage gaps).
Evidence: `.venv` built with the container's default `python3` (3.11.15) reproduced the `SyntaxError` at `backend/app/metrics/engine.py:2176`; rebuilding with `python3.13` (available on this box) fixed it and the full suite then passed.
Suggested fix: Add a `.python-version` (or `runtime.txt`) pinning 3.13 at the repo root, and/or note the Python floor in a README/CONTRIBUTING note, so `python3 -m venv` doesn't silently pick an incompatible interpreter. Test to add: none needed; this is a repo-metadata fix, not a code fix.
Health-risk direction: none (production is unaffected — the Docker image already pins 3.13 — but local dev/CI on an older default Python breaks completely and silently).

## Improvement proposals (S4)
None beyond the fixes already described above (all three findings are cheap, low-risk, < 1 hour fixes rather than separate proposals).

## Calibration table vs previous review (phase D)
No previous review exists to compare against (first run). For the record, this screen's null-simulation check (existing `test_v2_false_signal_rate_is_calibrated`, N=500 synthetic null histories) passed at < 8% for v2's per-metric false-signal rate, matching the ≈5% target in section 2/phase D.

## Coverage gaps
- Full false-signal simulation across v1 and v3 (phase D rows beyond row 1) — not run separately; relied on the existing, passing `test_drift_validity.py`/`test_guidance.py` suite, which covers v2 explicitly and v3 via the shared `_sensitive()` mechanics core. A full review should run the appendix B recipe directly for v1 and v3 too.
- IDOR probes (F2), upload/zip handling (F6), GDPR access-log visibility (F7), container build end-to-end (G3), citation/evidence audit (I2), and the fuller Czech-copy and empty/error-state sweep (H5-H7) are full-review-only items per section 10 and were not run in this quick screen.
- Backend test suite duration was consistently ~42 s across two runs, vs. the ~20 s baseline recorded in the rulebook (dated the same day). Since the rulebook's baseline was set by the same commit and test count (157 passed/2 skipped) matches exactly, this reads as this container's CPU being slower rather than a regression — noted for the next review to compare against.
- The one console error seen during the browser check (`net::ERR_CERT_AUTHORITY_INVALID` for `fonts.googleapis.com`) is this sandbox's outbound TLS proxy blocking a Google Fonts request, not an app defect (confirmed by isolating the failing request) — excluded from the H1 pass/fail call.

## Structural drift
None. Every discovery-map hint in section 4 still points at the correct location (`app/metrics/engine.py`, `app/metrics/capacity.py`, `app/metrics/guidance.py`, `app/routers/runners.py`, `app/models.py`, `frontend/src/App.tsx`/`training.tsx`/`datapage.tsx` all matched on first search).
