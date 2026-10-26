# Došlap review — 2026-10-26 (quick screen)

Commit / working tree: `cf291b6` (Body map: pain points on the right muscles; English-mode leaks), `main` = `origin/main`, working tree clean, nothing uncommitted. `ENGINE_VERSION` v0.12.19, `HISTORY_VERSION` h11 (unchanged — this diff is frontend-only).

Baseline: tests **691 passed / 2 skipped / 0 failed**, 273.67 s on Python 3.11.17 · `tsc --noEmit` OK · `vite build` OK (only the existing >500 kB chunk warning) · `python -m compileall` OK. Node 22.22.0.

How this review was run: against a throwaway SQLite DB (`DOSSLAP_DB_PATH=/tmp/review.db` for the app run; separate temp DBs for the test suite and the calibration simulation), port 8765. Nobody contacted the deployed app, Garmin, Apple or any LLM (all keys unset). Scratch scripts, the simulation and the screenshots are in `/tmp/` and `/tmp/pw/` of the review container and are not committed.

## Summary

Since the 2026-10-23 full review (`1d0f421`), exactly **one commit** landed: cf291b6, "Body map: pain points on the right muscles; English-mode leaks." It is frontend-only (`git diff --stat` for `backend/` is empty):
- `MuscleAnatomy.tsx`: every hotspot re-placed from its muscle overlay or an anatomical landmark, with separate left/right points (`r:` field) since the drawings aren't mirror-exact, and per-view midlines (front 217 px, back 204 px) replacing a single shared centre for both mirroring and overlay clipping. Rhomboids switch from an overlay (which lit the wrong muscle, infraspinatus) to a drawn highlight. The front figure gets a white background so its 80%-opacity art doesn't look different from the fully-opaque back art.
- `translator.ts`: the per-template regex no longer always inserts a `(.+?)` between every literal part — it special-cases two placeholders with nothing between them, so a single captured value isn't split mid-word. Also unwraps a leading weather/status icon before matching the rest of the text.
- Two new dictionary entries ("Bolest {}/10 · {}", "Bolest {}/10") catch the string a sibling template's ambiguous capture swallows whole.
- `App.tsx`: the Dnes "V technice se drží mimo normu: X" sentence now translates each flagged metric name individually in English mode (previously joined the raw Czech names).

**What is healthy:** the 691-test suite, `tsc`, the production build and `compileall` are all unchanged from the 2026-10-23 baseline (no engine code touched, so no behavioural regression is possible on the scoring side). A quick N=300 null simulation (v2, no drift) landed at or below the 2026-10-23 full-review baseline on all four mechanics metrics (below). The body map renders cleanly at 400 px in both languages (front figure on white, hotspots inside the canvas, no console errors, no overflow), and the new per-view midline/clip-path logic is internally consistent (checked by reading the code, not just the screenshot).

**What needs attention:** this commit's own stated goal — fixing "English-mode leaks" — is not reached for every case. The translator's split-by-template approach still produces embedded, untranslated Czech text inside otherwise-English sentences whenever (a) a placeholder's own value needs further translation but the regex captures more than that one placeholder's text, or (b) a nested value simply has no dictionary entry. Two concrete, reproduced instances below (F1), one of them a live browser screenshot of the Dnes illness-watch banner. Neither is new in this commit — the underlying architecture predates it — but this is exactly the bug class the commit title claims to address, and the fix only covers the fully-adjacent `{}{}` case, not these.

Counts this run: **S1 0 · S2 0 · S3 1 · S4 1.**

## Findings (most severe first)

### F1 English mode: multi-placeholder templates leave Czech text embedded in otherwise-English sentences
Severity: S3 · Confidence: CONFIRMED · Area: Frontend / i18n (`frontend/src/i18n/translator.ts`, `en.json`)

What happens: `viaTemplates()` matches a Czech sentence against a template with 2+ `{}` placeholders using a hand-built regex, then recursively re-translates each captured group. Two distinct ways this produces visible Czech-in-English text:

**(a) Ambiguous capture boundary.** When two placeholders in a template are separated only by a generic literal (a single space, " · ", etc.) that also occurs inside the placeholder values themselves, the regex's lazy/lazy (or lazy/greedy) pairing can pick the wrong split point, so one placeholder's capture swallows text that belongs to its neighbour. The swallowed combination is then not found by any dictionary entry and stays in Czech.
  - Live example: the Dnes illness-watch banner, template `"{} {}. Bývá to první známka nemoci, ale i únavy, alkoholu nebo horka."` (`frontend/src/App.tsx:2015`, `illText()`). With input `"Dvě noci po sobě klidový tep 60 (obvykle 53). Bývá to první známka nemoci…"`, the regex splits it as group1=`"Dvě"`, group2=`"noci po sobě klidový tep 60 (obvykle 53)"` instead of group1=`"Dvě noci po sobě"`, group2=`"klidový tep 60 (obvykle 53)"`. The sub-phrase `"klidový tep 60 (obvykle 53)"` translates correctly **on its own** (to "resting heart rate 60 (usually 53)") — confirming the dictionary coverage is fine and the bug is purely in how the outer template captures it.
  - Screenshot: `/tmp/pw/shot_bodymap3` run, illness-watch banner, kritickepretizeni@demo.cz, English mode, 400 px — reads "**Dvě noci po sobě klidový tep 60 (obvykle 53)**. It is often the first sign of an illness, but also of fatigue, alcohol or heat."
  - Reproduced directly against `translator.ts` + `en.json` with Node/esbuild (see Evidence).

**(b) Missing nested dictionary entry.** `guidance.py:984` builds the recurring-pain "clears after" text as `f"{E.CLEAR_BONE_DAYS} dní bez bolesti"` (bone sites) or `f"{E.CLEAR_CHECKINS} check-iny bez bolesti"` (every other site — the common case, since `CLEAR_CHECKINS=2` is the non-bone default). The dictionary has a template for the bone form (`"{} dní bez bolesti"` → `"{0} days without pain"`) but none for the check-in form, so `"2 check-iny bez bolesti"` is never translated and leaks into the recurring-pain guidance sentence in English mode: *"Recurring pain (koleno, 3× in 28 days; lifted after: **2 check-iny bez bolesti**)…"*.

Failure scenario: an English-mode runner with 2 consecutive nights of raised resting HR, or with recurring pain at a non-bone site, sees a guidance/warning sentence that is mostly English with a Czech clause in the middle — confusing, and undermines trust that the English mode is complete, though it doesn't change any score or recommendation.

Evidence:
- `/tmp/translator_test/run4.cjs` (Node + esbuild bundle of `translator.ts` against the real `en.json`): confirms (a) — full sentence leaks "Dvě noci po sobě klidový tep 60 (obvykle 53)", while the same sub-phrase alone translates correctly.
- `/tmp/translator_test/run3.cjs`: confirms (b) — `"2 check-iny bez bolesti"` stays untranslated while `"5 dní bez bolesti"` (the sibling bone-site template) translates correctly to "5 days without pain".
- Live screenshot `/tmp/pw/shot_bodymap_real_400.png`'s preceding step (illness-watch banner, not included in that exact screenshot but reproduced in the same session — see `/tmp/claude-0/.../tasks/blv84now6.output` and the earlier `debug1.png`/`shot_en_today_400.png` sequence) and the signal-card title `"Pain při běhu · 8/10"` on Dnes (English mode) are further live instances of the same class (a different Czech fragment, "při běhu," left embedded after a partial translation).

Suggested fix: this is a drive-by observation, not something to ask the diff's author to re-scope. Two independent, low-risk options for a follow-up:
- Add the missing dictionary entry (`"{} check-iny bez bolesti"` → `"{0} check-in(s) without pain"`), which fixes (b) immediately with no code change.
- For (a), make multi-placeholder template regexes greedy-first for every group except the last (so each group prefers to end at the *next* occurrence of its following literal rather than growing past it), or require templates with 2+ placeholders to be re-verified by a round-trip test (render with a few representative values, translate, assert no Czech diacritics remain outside an untranslated proper-noun allowlist).

Test to add: an i18n contract test (Python or Node) that renders a representative sample of the backend's own templated strings (grep for `f"..."` / `.format()` in `guidance.py`, `App.tsx`'s `illText`, etc.) through `translate()` and asserts the result contains no Czech-only diacritic characters (ď, ě, ř, š, ť, ů, ž minus proper nouns) — this would have caught both (a) and (b) without needing to know the specific sentences in advance.

Health-risk direction: none (display/comprehension issue in English mode only; the underlying decision logic, score and Czech-mode text are unaffected).

## Product/engineering observations (not findings)
- `MuscleAnatomy.tsx`'s `backDefs` no longer gives `back-img12` ("Rhomboidy") an `overlay:` key (it now gets the drawn-highlight treatment instead, per the commit message), but the `overlays` map at the bottom of the file still carries a `"back-img12"` URL entry. It's simply unreferenced now — no behaviour change, nothing to fix, just noting it so a future cleanup pass knows it's dead.
- This review independently hit the same carried item the 2026-10-19 quick screen logged: every demo-account login (including v3 `kritickepretizeni@demo.cz`) hits the mandatory profile-completion gate because `running_since` is `NULL` on the seeded demo runners. Worked around the same way (set `running_since` directly on the throwaway review DB via the API/SQL, Appendix A pattern) — not re-logged as a new finding.

## Calibration table vs previous review (phase D, row 1 only — quick screen)

No engine code changed in this diff, so this is a sanity check, not a recalibration.

| Check | Target / fail | This screen (N=300, v2, 1 seed, end-to-end via `assess()`) | 2026-10-23 full (N=1000×3 seeds) |
|---|---|---|---|
| Shown per metric, no change — vertical ratio | ≈5 % / >8 % | 1.00 % | 1.8–1.9 % |
| …vertical oscillation | ≈5 % / >8 % | 0.00 % | 0.1–0.6 % |
| …cadence | ≈5 % / >8 % | 0.00 % | 0–0.1 % |
| …GCT | ≈5 % / >8 % | 0.67 % | 0.5–0.9 % |

All four at or below the prior full review's range; no regression, as expected for a diff that touches no engine code.

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 1 commit since `1d0f421`; frontend-only (`backend/` diff-stat empty) |
| A2 environment | PASS | Python 3.11.17 venv rebuilt clean; Node 22.22.0, `npm ci` clean |
| A3 backend tests | PASS | 691/2/0, 273.67 s — unchanged from 2026-10-23 baseline |
| A4 frontend | PASS | `tsc --noEmit` OK, `vite build` OK (pre-existing >500 kB chunk warning only) |
| A5 compileall | PASS | `app` + top-level `*.py` |
| Discovery (roles touched by diff) | PASS | Only "Frontend views" (`MuscleAnatomy.tsx`, `App.tsx`) and "Signal documentation"-adjacent (`translator.ts`, `en.json`) touched; both still at their hinted locations |
| C1 mode plumbing | N/A | No engine code in this diff; `_emode()==` count unchanged (4, all carried/pre-existing) |
| C2 time | N/A | No engine/metrics code in this diff |
| F1 CSRF / F2 access control (new routes) | N/A | No new routers or endpoints in this diff |
| G1 new columns vs migrations | N/A | No model/schema changes in this diff |
| C3 replay parity / C9 sandbox parity | PASS | Covered by the unchanged 691-test suite (no engine/data-shape change in this diff) |
| Guidance override tests | PASS | Suite green; not exercised live this run (diff doesn't touch guidance logic) |
| Null simulation (phase D row 1, N=300) | PASS | See calibration table — at/below the 2026-10-23 baseline on all 4 metrics |
| H1 tabs/overflow, v3 demo runner, 400 px | PASS | `/app/today`, `/app/training`, `/app/load`: 0 px overflow, 0 console errors — in Czech and in English mode |
| H2 Trénink nav | PASS | Trénink tab present for the v3 demo runner, next to Dnes, in both languages |
| Body map (H1/H3-adjacent, new this diff) | PASS | Front figure renders on white at 400 px (the opacity fix), all hotspots inside the 419×1024 canvas bounds (checked by parsing every `Def` in the diff), no console errors, no overflow, step 1→2 of the check-in flow works in English mode |
| Regression watchlist items touched by the diff | PASS (with note) | None of the section 6 items are a direct match; the "rounded ratio used for points" and pace-confound items are engine-only and untouched. F1 above is a new instance of the general "generated text not fully translated" class, which the watchlist doesn't yet list — see Structural drift |

## Coverage gaps
- **The three carried S1s** (physio self-registration/claim, re-import wiping data, AI-brief consent bypass) and the carried S2/S3 list from 2026-10-23 were **not re-checked** — out of scope for a 1-commit, frontend-only diff that touches none of their code paths. Confidence they are unchanged: HIGH (diff-stat confirms only the 5 files listed in Summary changed).
- **MuscleAnatomy coordinates**: verified programmatically (every `top`/`left`/`r` value is inside the 419×1024 canvas) and visually at one viewport (400 px, front view only) — the back view and tablet/desktop widths were not screenshotted this run.
- **English-mode coverage beyond F1**: not exhaustively swept; F1's examples were found by following the diff's own stated goal ("English-mode leaks") into adjacent guidance/banner text, not by a systematic scan of every templated string in the dictionary.
- **Docker image build**: not run (no Docker daemon in this container).
- **Real LLM / Garmin / Apple**: keys unset, as required; not exercised.
- Deník, Mechanika and Péče tabs: not driven in the browser this run (only Dnes, Trénink, Zátěž per the quick-screen recipe, plus the check-in modal/body map).

## Structural drift (playbook updates proposed)
- Consider adding a regression-watchlist line for "generated/templated text leaks Czech in English mode" (section 6) — this is now the second time (this run) the same architectural weakness in `translator.ts`'s multi-placeholder matching has been the direct cause of a visible defect, and the playbook's current watchlist has no entry pointing a future reviewer at `viaTemplates()`/`loadDict()`.
