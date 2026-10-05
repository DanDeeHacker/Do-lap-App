# Došlap review — 2026-10-05 (quick screen)

Commit / working tree: `7b9bd43` (Monday morning report: the week's plan — runs, strength and rides by day, at the edge of capacity), working tree clean, no uncommitted files.

Baseline: tests 526 passed / 2 skipped, 167.3 s (Python 3.13 venv, as before — `.python-version`/`runtime.txt` still absent) · type-check OK · production build OK (one pre-existing >500 kB chunk-size warning, not an error) · `python -m compileall` OK.

## Summary

**The diff since the last report could not be computed by commit hash** (see Structural drift) — `main`'s history was rewritten after 2026-09-28, and the last report's baseline commit (`40eebca`) no longer exists anywhere in this repository. Falling back to the current commit log: ~90 commits are reachable from `HEAD`, the most recent ~20 alone (2026-10-03 → 2026-10-04) touch 96 files (+16.5k/−4.1k). This was an unusually large week even by this project's pace: a v0.12.0 engine release (profile gate, critical-speed "Rychlost" signal, cycle-aware readiness, illness signal), Apple Health sleep-stage/night-HRV ingestion, LLM-based shoe recognition (Llama 3.2 Vision), persistent sliding sessions, a new strength/durability program module, a Monday morning report, and a repo-wide i18n extraction pipeline. Backend tests grew from 321 to 526 (all green); frontend type-check and build are clean.

Given the diff could not be scoped precisely, I leaned on direct, mode-by-mode probing rather than a line-by-line diff read: a fresh v1/v2/v3 null-signal calibration run, a live CSRF/access-control sweep of every mutating route (including all routes added since the last report), a model-column-vs-migration check, and a v3-demo-runner browser pass (Dnes/Trénink/Zátěž at 400 px). That turned up one confirmed **S2**: the v3 (Kapacitní) engine silently drops the terrain-weighted (grade-adjusted) load-spike detection that v2 has, because one gate in `engine.py` was never switched over to the shared v2+v3 helper when v3 was built. This is a real regression risk (false reassurance on hilly/downhill training) and, combined with the size and unreviewable-diff nature of this week's change, **a full review is overdue** — the last report already flagged this at half this diff's size and recommended prioritising it over waiting for the next scheduled Friday.

Both carried-over S3 items from the last report are now fixed (see "Fixed since last review"). One new process-level S3 (history rewrite) is recorded below; it is not a product defect but affects every future review's ability to scope its diff.

## Findings (most severe first)

### F1 v3 (Kapacitní) silently loses the grade-adjusted load-spike signal that v2 has
Severity: S2 · Confidence: CONFIRMED · Area: Phase C (engine correctness), C1 mode plumbing
Location: `backend/app/metrics/engine.py:1434` (`_v2 = _emode() == "v2"`), contrasted with the shared `_sensitive()` helper at `engine.py:349-352` (`return _emode() in ("v2", "v3")`) which every other sensitive-mechanics gate in the same file uses (`engine.py:938`, `:3196`, `:3221`, `:3903`).
What happens: The terrain-load-weighted km per run (Minetti grade cost, added "so a hilly run's true demand feeds the spike, not just its raw distance" — the function's own comment, `engine.py:1431-1433`) is gated by `_v2`, which is `True` only in exact mode `"v2"`. Per the product-decision table, v3 ("Kapacitní") is documented as "v2 mechanics + capacity-based Zátěž axis + Trénink tab" — it is supposed to inherit v2's per-run mechanics, including this one. Because the gate was never switched to `_sensitive()`, a v3 runner's session-spike detector only ever looks at raw distance and effort (TRIMP), never the grade-adjusted km, even on a run with a full elevation profile.
Failure scenario: A v3 runner does a short, steep downhill run (the single most eccentric/impact-heavy kind of session, per the surrounding code's own citation of Gottschall & Kram 2005) after a run of ordinary flat long runs. A v2 runner with the identical activity history gets a load-spike warning driven by terrain; the v3 runner — on the exact same numbers — gets none.
Evidence: Reproduced directly against the live engine (no test file added to the repo; script run from `/tmp`, not committed): registered a runner, gave it three flat 10-20 km runs plus one 2 km steep-downhill run (profile: −15% grade throughout, same shape as `tests/test_terrain.py`'s existing v2 fixture), then called `E.load()` pinned to each mode on identical data —
  `v3 sessionSpike: 1.0  basis: vzdálenost+intenzita`
  `v2 sessionSpike (same data): 1.48  basis: terén`
  `tests/test_terrain.py` only exercises this path with `E.engine_pinned("v2")` (`test_v2_terrain_spike_only_compares_runs_with_profiles`); there is no v3 equivalent, which is how this went unnoticed through the full test suite.
Suggested fix: change `engine.py:1434` to `_v2 = _sensitive()` (keeping the variable's existing name is fine; it already means "the terrain-aware branch" elsewhere in spirit) so v3 inherits the same grade-adjusted spike math v2 has. Test to add: a v3-mode copy of `test_v2_terrain_spike_only_compares_runs_with_profiles` in `tests/test_terrain.py`, asserting `sessionSpikeBasis` contains "terén" for a v3-pinned runner with the same steep-downhill fixture.
Health-risk direction: false reassurance — a v3 runner's load-spike warning under-reacts to grade-driven load that v2 (and, per the product decision, v3 is supposed to inherit) correctly flags.

### F2 (process) `main`'s git history was rewritten since the last review; the last report's baseline commit no longer exists
Severity: S3 · Confidence: CONFIRMED · Area: review process / tooling, not app behaviour
Location: repository history (no single file)
What happens: The 2026-09-28 quick-screen report cites `40eebca` as "commit / working tree" to diff against. In this checkout, `git fetch origin 40eebca` fails ("couldn't find remote ref 40eebca"); `git merge-base 40eebca HEAD` returns no common ancestor at all (not even the repo's root commit); and no local or remote ref contains it. `HEAD`'s own root commit (`379e3e0`) is dated 2026-09-29 — one day after the last review — consistent with a full history rewrite (squash/rebase/force-push) of `main` around that date, not merely new commits on top of the old history.
Failure scenario: Any reviewer (human or AI) following the playbook's "git log since the date of the last report" or "screen the diff since that date" instructions literally gets a hard failure on the cited commit, with no clean way to recover the actual diff — exactly what happened this run (worked around by falling back to the current full commit log and live behavioural probes instead of a diff read).
Evidence: `git fetch origin 40eebca` → `fatal: couldn't find remote ref 40eebca`; `git merge-base 40eebca HEAD` → empty, exit 1; `git branch -a --contains 40eebca` / `git tag --contains 40eebca` → empty; `git rev-list --max-parents=0 HEAD` → single root `379e3e094cc9...` dated 2026-09-29.
Suggested fix: avoid rewriting the history of the branch reviews are run against (or, if a squash/rebase is genuinely needed, do it with the review workflow in mind — e.g. tag each report's baseline commit, `review-2026-09-28`, so a tag-preserving rewrite keeps it resolvable). Playbook update proposed below: when the cited baseline is unreachable, fall back to the "first run" procedure (screen recent commits + full baseline) rather than erroring, which is what this screen did.
Health-risk direction: none (process/tooling risk only).

## Fixed since last review
- The 2026-09-28 F1 (new v3 capacity signals — `cap_volume`, `cap_intensity`, `cap_descent`, `cap_ascent`, `cap_systemic` — rendering their ratio with a bare period instead of the Czech decimal comma) is fixed: a live v3 browser check of `kritickepretizeni@demo.cz`'s Zátěž tab this screen shows "Objem nad kapacitou ×3,44", "Prodloužený kontakt se zemí +3,6 %" etc., all correctly comma-formatted, consistent with the rest of the page.
- The 2026-09-28 F2 (Data-page copy claiming AI coach texts "will appear on Dnes/Trénink in a later phase") no longer reproduces: that exact string is gone from `datapage.tsx`, and the AI-coach/assistant surface has since been substantially reworked into the new per-tab assistant feature (`routers/assistant.py`, "Assistant per tab" per the commit log) — the stale "later phase" promise it was about doesn't appear to still exist anywhere I checked.

## Improvement proposals (S4)
None beyond the fixes already described above.

## Calibration table vs previous review (phase D)

Fresh probe this screen (appendix B recipe, N=300 null histories per mode, seed 11 — same seed/N as the last review for a direct comparison):

| Check | Target | This screen | 2026-09-28 |
|---|---|---|---|
| Per-metric shown signal, v1, no real change | ≈3.5 % | 3.7 % | 3.7 % |
| Per-metric shown signal, v2, no real change | ≈5 % | 5.0 % | 5.0 % |
| Per-metric shown signal, v3, no real change | ≈5 % | 5.0 % | 5.0 % |

No drift — identical to the last review's numbers (same seed), despite the large intervening diff. This probe only exercises `_drift_z_core` directly and would not have caught F1 above (a session-spike/terrain issue, not a per-metric drift-signal one); it's recorded here as a clean result on its own narrow scope, not as evidence against F1.

## Coverage gaps
- **The diff since the last report could not be scoped by commit hash** (see F2) — this screen substituted a full-suite run, live mode-by-mode probes, and a CSRF/access-control/migration sweep of the current codebase for what would normally be a targeted read of the actual diff. A full review should re-run phases B through J in full against the current `HEAD` rather than relying on this substitution.
- Still open from 2026-09-25/-28: no `.python-version`/`runtime.txt` pinning Python ≥3.12 at the repo root — this screen's environment setup again had to explicitly select `python3.13`.
- Per section 10's own scope, not run this screen: IDOR probes beyond a code read (F2 full), upload/zip handling (F6), GDPR access-log visibility (F7), container build end-to-end (G3), citation/evidence audit (I2 — notably, the new v0.12.0 engine documentation and several new in-code citations, e.g. Gottschall & Kram 2005, Gregor et al. 1987, were read but not independently verified against the source literature), and the fuller Czech-copy/empty-state sweep (H5-H7) beyond the three tabs driven.
- Only three tabs (Dnes, Trénink, Zátěž) were driven in the browser, at 400 px only, on one v3 demo runner (`kritickepretizeni@demo.cz`, engine switched to v3 via the API as appendix A describes); 1360 px and the remaining tabs (Deník, Pohyb, Péče) plus the large new surfaces from this week (shoe recognition/catalog UI, the strength/durability program, the Monday morning report, Apple Health sleep views) are full-review scope and were not driven at all.
- A native `<input type="date">` on the new profile-gate form rendered as "mm/dd/yyyy" during the browser check; verified this is a Chromium browser-locale artifact of the headless launch (no `locale: 'cs-CZ'` context option was set) rather than an app bug — `frontend/index.html` does set `<html lang="cs">`, and native date-input formatting follows the browser's own locale, not page content. Not listed as a finding; flagged here only as a limitation of this screen's own browser setup, in case a future screen wants to confirm with the context locale set.
- The null-signal probe (phase D row 1) was re-run; the other phase D rows (the "mechanika přetrvává" flag rate, the +1 SD detection rate, the easy-pace-slower-25-s/km confound, segment significance false-positive rate) were not re-run this screen and are relying on the existing green test suite (`test_drift_validity.py`, `test_calibration.py`, `test_capacity.py`) rather than a fresh probe — same caveat the last two reviews carried.
- The shoe-recognition LLM call (`routers/shoes.py` → `routers/assistant.py:182 /api/assistant/ops/shoe-check`, `app/llm.py::vision`) was read but not exercised live (`NVIDIA_API_KEY` was left unset per the rules of engagement, so `llm.available()` returns false and the feature no-ops); confirmed it has a timeout (`VISION_TIMEOUT`, default 45 s, capped at 120 s) and a graceful `{"ok": false}` fallback, consistent with F5's requirements, but the actual model output/prompt-injection surface of a real vision call was not reviewed.

## Structural drift
- `main`'s git history was rewritten since the 2026-09-28 review; see F2. The discovery map and regression watchlist are unaffected (still resolve correctly by role-based search), but any future "diff since the last report" step needs a fallback for an unreachable baseline commit.
- `HISTORY_VERSION` (the history-cache key, `backend/app/history.py`) has moved from `h7` (2026-09-28) to `h10` — consistent with ordinary cache-invalidating changes to the replay path, not a parity concern by itself; noted for the discovery map.
- Two new routers since the last report, `backend/app/routers/admin.py` (owner-only read-only "Zobrazit jako" view, `require_owner` dependency) and `backend/app/routers/self_programs.py` (the new strength/durability programs, `ensure_runner_self`/`ensure_runner_read_access` on every route) — both correctly access-controlled and CSRF-covered on every mutating route; adding to the discovery map's router list.
- A new table, `Shoe` (`backend/app/models.py`), and the already-noted `SelfProgram` table are both new tables (handled by `create_all()`, no migration needed) rather than new columns on existing tables — no `G1` gap.
- `backend/app/routers/assistant.py:182` (`/api/assistant/ops/shoe-check`) is a new bearer-token-gated operator route (`require_feedback_token`, same shape as the already-documented `annotations.py` `/export`/`/resolve` exemptions) — proposing the playbook's F1 known-exemptions list add this alongside the sandbox, Apple-webhook, and annotations entries, since the operator-token pattern is now used in three separate routers.
