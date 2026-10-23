# Došlap review — 2026-10-23 (full review)

**Fix before the next release:**
- **The three S1s are unchanged since 2026-10-05.** All three were re-verified live at HEAD:
  1. Anyone can register as a physio and take over a runner's care and data.
  2. Re-importing a Garmin or Apple file deletes the runner's own ratings and manual sessions.
  3. The report "AI notes" send health data to the LLM without the AI consent.
- **New this week (S2):** v0.12.17 ("mechanics less sensitive") made mechanics drift too hard to detect.
  - A real +1 SD change over 14 days is now shown in only 42–45 % of runners. The target is ≈ 67 % and the fail line is 55 %.
  - A cadence change is shown in only 8–9 %.
  - Neither demo account shows its scenario any more: tichydrift is no longer "Tichý drift" and kritickepretizeni is no longer "Kritická".
- **The pace-confound false alarm (2026-10-16 F6) is much worse than last reported.** Easy runs at +25 s/km raise "mechanika přetrvává" for about 40 % of runners. The cause: the runner's pace classes leave the pace correction switched off for 93 % of them.

Commit / working tree: `1d0f421` (Mechanics chip names its metric; step length out of the flags — v0.12.19), `main` = `origin/main`, working tree clean, nothing uncommitted. `ENGINE_VERSION` v0.12.19, `HISTORY_VERSION` h11.

Baseline: tests **691 passed / 2 skipped / 0 failed**, 269 s on Python 3.11.17 (4 sub-reviewers were running in parallel) · `tsc --noEmit` OK · `vite build` OK (only the existing > 500 kB chunk warning) · `python -m compileall` OK. Node 22.22.0.

How this review was run:
- **Lead reviewer:** phases A–C (code, live/replay/sandbox parity on the demo data).
- **Four parallel sub-reviewers:** D (calibration), E+F+G, H (headless Chromium), I+C14. Each used its own throwaway SQLite DB and port; Postgres 16 was used for the G1 migration only.
- **Nothing external was contacted:** not the deployed app, Garmin, Apple, or any LLM (all keys unset). Web access was used only to verify references.
- **Nothing in the repo was changed.** Scratch scripts, outputs and screenshots are in the review container's `/tmp/rv-lead`, `/tmp/rv-d`, `/tmp/rv-efg`, `/tmp/rv-h` and `/tmp/rv-i`, and are not committed.

## Summary

**What changed.** Since the 2026-10-16 full review (`7212123`), 5 commits landed: 29 files, +620 / −298.
- v0.12.16: mechanics are judged as of the last run (the 2026-10-19 quick screen covered this).
- Feedback #217–#221: 24 h engagement, the quadrant grid removed from Dnes, diary metrics on Deník.
- **v0.12.17, a scoring change for mechanics in all three engines:**
  - each session's drift index is winsorised at ±2.5;
  - the point dead zone is 0.4;
  - the show threshold is 0.5;
  - a new "worthwhile factor" multiplies each metric by `clamp(shift / SWC − 0.5, 0, 1)`, where SWC = 0.2 × the between-runner SD taken from Garmin's gauge ranges.
- v0.12.18 / v0.12.19: the "mechanika přetrvává" flag follows that verdict, step length was removed from the flags, and the chip names its metrics.

**What is healthy:**
- Live vs 6-month history: 12 demo runners × v1/v2/v3, 36/36 identical on mech, load, symptoms and quadrant.
- Sandbox vs live: 36/36 identical.
- The history cache key includes the engine version.
- No new wall-clock or `_emode()==` uses.
- Live assessment takes ≤ 0.13 s, and a v3 history ≤ 2.7 s.
- Null false-signal rates and the flag-on-improvement check are now well under target.
- The new `usage_days.hour` migration works on SQLite and Postgres 16.
- No new CSRF or IDOR gaps (114 mutating routes and 48 runner-scoped GET routes probed).

**What went wrong.** The sensitivity cut overshot.
- With the "−0.5 SWC" offset, a 1-SD change only becomes a signal for runners whose own run-to-run noise is at least one SWC. Steady, low-noise runners and cadence are almost never flagged (F4).
- The demos lose their states (F5).
- Dnes, the rail, the Mechanika cards and the weekly text now disagree about whether technique is "mimo normu" (F6).
- The pace-confound false alarm turned out to be a pace-class bug, not a σ issue (F7).
- **No carried S1/S2 was fixed this period.**

Counts (open items at HEAD, carried included): **S1 3 · S2 20 · S3 70 · S4 8.** New this run: S2 3 (F4, F5, F6), S3 18. F7 is carried, re-diagnosed and re-measured.

## Findings (most severe first)

### S1 — carried, all re-verified live at HEAD

### F1 Anyone can register as a physio and claim any runner (2026-10-05 F1) — STILL OPEN
Severity: S1 · Confidence: CONFIRMED · Area: F2
Location: `backend/app/routers/auth.py:85`, `backend/app/routers/triage.py:71-93` (`claim`).
Evidence:
- Register with `"role":"physio"` → 200.
- The fresh phy-0005 gets 403 on run-0015's bootstrap.
- `PATCH /api/triage/16/claim` on a closed, self-managed case without consent → 200, and the bootstrap is then 200.
- Claiming triage 1, which phy-0001 had claimed → 200, `claimed_by` is overwritten, and adela's bootstrap is 200.
Suggested fix / test: as in 2026-10-05 (`test_claim_requires_consent_open_unclaimed_unrevoked`).
Health-risk direction: privacy breach; unsafe plans from an unverified "physio".

### F2 Re-importing a Garmin/Apple file wipes the runner's own data (2026-10-05 F2) — STILL OPEN
Severity: S1 · Confidence: CONFIRMED · Area: E1
Location: `backend/app/routers/integrations.py:119-121` (`_apply_seed`, unchanged).
Evidence: live on run-0017. Before re-import: 4 activities (1 manual) and 3 feedback rows. After: 3 activities, 0 manual, 0 feedback. The Postgres FK 500 from earlier reviews was not re-run this time; the code is unchanged.
Suggested fix: merge by `external_id`; never delete manual activities, ratings, exclusions or streams.
Health-risk direction: false reassurance (the pain history is lost).

### F3 Report "AI notes" bypass the AI consent (2026-10-05 F3) — STILL OPEN
Severity: S1 · Confidence: CONFIRMED (with a mocked LLM; previously LIKELY) · Area: F5
Location: `backend/app/routers/runners.py:1261-1272`, `backend/app/metrics/report_ai.py:118`.
Evidence: `POST /api/runners/run-0017/report/ai` with `coach_consent=False`, `llm.assistant_available` mocked to True and `chat_messages` mocked. The LLM was called once with the runner's report facts (readiness, sleep, …).
Suggested fix: send rules-only text unless `coach_consent` is set. Add a test that a mocked LLM is never called with consent off.
Health-risk direction: none (privacy / consent).

### S2 — new

### F4 v0.12.17's worthwhile gate pushes detection of real mechanics drift below the fail line; cadence is almost undetectable
Severity: S2 · Confidence: CONFIRMED · Area: D calibration / C5
Location:
- `backend/app/metrics/engine.py:3539-3551` (worthwhile factor, `MECH_SHOW`, `MECH_STAT_DEAD`);
- `engine.py:885-891` (`MECH_SWC_DEFAULT`);
- the cadence σ floor `abs(c) * 0.012` in `_drift_v2` (`engine.py:~1146`).

What happens:
- **The drift core still catches the change.** A +1 SD shift over the last 14 days gives z ≥ 0.6 in 66–69 % of runners, unchanged.
- **The new gate then removes most of these signals.** A metric is shown only when z × worth ≥ 0.5, and worth = shift/SWC − 0.5. So a 1-SD change only shows when the runner's own per-run SD is at least about one SWC.
- **The SWC is large relative to typical within-runner noise.** It is 0.2 × the *between*-runner SD from Garmin's gauges. SWC / within-runner SD at mid noise: vertical ratio 0.75, vertical oscillation 1.03, GCT 1.0, cadence 1.4. At low noise the ratios are 1.1–2.1.
- **The result is backwards: the gate rewards noisy runners and silences consistent ones.**

Failure scenario: a consistent runner whose cadence drops 1.5 spm and whose GCT rises 5 ms over two weeks, at the same pace. Both changes are real and beyond their noise; none are shown.

Evidence: synthetic runners end-to-end through `assess_data()`, 4 runs/week over 90 days, N = 1000 × 3 seeds.

| Case | Shown | Target |
|---|---|---|
| +1 SD over 14 d, Appendix-B recipe | 41.7–44.5 % (drift core 66–69 %) | ≈ 67 %, fail < 55 % |
| Mid noise: vertical ratio / vert. oscillation / GCT / cadence | 44–45 % / 26–28 % / 33–35 % / **7.7–9.0 %** | |
| Low-noise runner (SD 0.15), +1 SD over 14 d | 4.5–6.4 % | |
| Low-noise runner (SD 0.15), +1 SD over 28 d | 11–13 % | |
| +2 SD over 14 d | 69–71 % | |

Scripts: `/tmp/rv-d/calib.py`, `/tmp/rv-d/legacy.py`, output in `out_det.jsonl`.

Disproof attempted:
- This is a documented owner decision (owner feedback 2026-10-22, constants comment at `engine.py:873-881`). It is also reported as a product question below.
- `tests/test_mech_sensitivity.py` covers only a 0.1 cm and a 1.0 cm shift. No test pins detection.
- Two detection tests were loosened in the same commit: `test_engine_toggle.py` (z > 1.5 → z > 1.0) and `test_regression.py` (segment z > 1.0 → ≥ 0.5).

Suggested fix (changes scores, so it needs an engine bump and a calibration run). Either:
- use `worth = clamp(shift / SWC, 0, 1)` (no −0.5 offset), or
- cap the SWC at about 1 × the runner's own typical error.

Also remove or relax the cadence relative σ floor.
Test to add: `test_detection_plus_1sd_14d` — shown ≥ 55 % at N ≥ 1000 for the vertical-ratio recipe, and ≥ 40 % for cadence at mid noise.
Health-risk direction: **false reassurance** (worst for steady, low-noise runners and for cadence).

### F5 Both demo drift accounts lost their scenarios (Phase D row "Demo accounts today")
Severity: S2 · Confidence: CONFIRMED · Area: D / G2
Location: `engine.py:3539-3551` (v0.12.17) against the seeded demo series in `backend/app/seed.py`.

What happens:

| Account (v3) | Before (v0.12.16) | Now (HEAD) |
|---|---|---|
| tichydrift (run-0011) | Tichý drift, mech 33 | Stabilní, mech 21 |
| kritickepretizeni (run-0012) | Kritická, mech 29 | Přetížení, mech 22 |

- **tichydrift:** GCT +5.4 ms at z 1.18 (beyond the control limit) gets worth 0.48 and scores 2 points instead of 13.
- **kritickepretizeni:** the 0.4 dead zone and the ±2.5 cap take GCT from 25 to 19 points.
- **The 90-day v3 replay is the same:** neither account is ever silent or critical.
- **Both keep `mechFlag = True` ("kontakt se zemí")** while the quadrant says stable or overreaching. The flag still restricts v3 guidance (`guidance.py:579`: no quality, halved descent and Z4), but the quadrant does not reflect it.

Evidence:
- the lead's script `/tmp/rv-lead/demo.py` (per-metric z, worth and norm above);
- the sub-reviewer's A/B on fresh databases (`/tmp/rv-d/demo2.py`);
- 2026-10-16 table: "silent (mech 37); critical (load 66, symptoms 81)".

Suggested fix: decide F4 first. If the gate stays, strengthen the seeded drift so the demos show their states again. Add `test_demo_quadrants` (tichydrift v3 = silent, kritickepretizeni v3 = critical).
Health-risk direction: none directly (demo). It is the most visible symptom of F4.

### F6 Dnes, the rail, the Mechanika cards and the weekly text contradict each other about technique
Severity: S2 · Confidence: CONFIRMED · Area: H3 / I1
Location:
- `frontend/src/App.tsx` (QuadrantHead `techNote` and chip, v0.12.19);
- `frontend/src/shell.tsx:156` (rail);
- `frontend/src/tabs.tsx:1560` and `normStatus`;
- `backend/app/metrics/coach_texts.py:155-157` with `coach_facts.py:291`.

What happens: the flag counts every metric with `norm ≥ 1` ("na hraně"), but the card says "mimo normu" only at `norm = 2`.

tichydrift (v2, Stabilní) shows all of these at once:
- **Dnes:** "⚑ kontakt se zemí mimo normu" and "V technice se drží mimo normu: kontakt se zemí".
- **Rail, same screen:** "MECHANIKA 21/100 drží na normě".
- **Mechanika card:** "Kontakt se zemí – na hraně".
- **Mechanika page headline:** "v rámci obvyklého středu".
- **Weekly coach text** (new in 4c17c7d): "Zátěž i mechanika sedí na vlastní normě." It is appended to every Stabilní week, and `stateNow` carries no flag. This is the same contradiction v0.12.19 removed from Dnes.

kritickepretizeni (v3, Přetížení) is similar: the chip says "mimo normu" but the state text says "Technika zatím drží."

Evidence: `/tmp/rv-h/shots/tichy-v2_400__app_today.png`, `mechcard_run-0011_400.png`, `text/krit-v3_1360__app_today.txt`. The weekly-text gap is from the code.

Suggested fix:
- Drive every wording from the same verdict: the chip wording follows the strongest metric's norm ("na hraně" vs "mimo normu"), and the rail does not say "drží na normě" while a flag is on.
- Pass `mechFlag` / `mechFlagMetrics` into `stateNow` and reuse the Dnes sentence.

Test to add: a frontend snapshot test for a stable runner with a norm-1 flag, plus `fallback_weekly_summary` with a flag must not contain "sedí na vlastní normě".
Health-risk direction: false reassurance (one surface says technique is fine while the flag restricts training).

### S2 — carried, re-measured and re-diagnosed

### F7 Pace confound: the runner's pace classes switch the pace correction off — slower easy runs flag in ~40 % (2026-10-16 F6) — STILL OPEN, worse than reported
Severity: S2 · Confidence: CONFIRMED · Area: D / C5
Location:
- `engine.py:411-430` (`bucket()` includes the pace class from `pace_cuts`);
- `engine.py:440-452` (`pace_cuts`, the runner's own tertiles);
- `engine.py:947-978` (`_pace_slope`: estimated within buckets, then requires a 10–90 % speed spread ≥ `_PACE_MIN_SPREAD` 0.15 m/s).

What happens: within one pace tertile, the speed spread is usually below 0.15 m/s. The slope therefore comes back 0, and pace adjustment runs for only about 7 % of runners end-to-end. With the fixed pace cuts (as the 2026-10-16 core-level harness used), it runs for 100 % of runners.

Evidence (`/tmp/rv-d/pacecheck.py`, `ab.py`, `out_pace.jsonl`):

| Version, v2 end-to-end | Flag | Silent quadrant |
|---|---|---|
| v0.12.15 / v0.12.16 | 52–56 % | 20–22 % |
| HEAD | 39–43 % | 1.6–1.8 % |

- At HEAD, the shown rates are vertical ratio 26–27 %, GCT 17–18 %, cadence 13 %. v1: some metric shown in 73 %.
- The same histories through the core: with pace tertiles, adjustment active 7 % and z ≥ 0.6 in 40 %; with fixed cuts, adjustment 100 % and z ≥ 0.6 in 15 %.
- So v0.12.17 lowered the silent-quadrant rate but not the flag, and **2026-10-16's 10.5–12.1 % understated the problem**.

Failure scenario: a v3 runner jogging 25 s/km slower for three weeks (heat, fatigue) gets "mechanika přetrvává" about 40 % of the time. Guidance then blocks quality, halves descent and halves Z4 (`guidance.py:579, 892, 1018, 1067, 1374`).

Suggested fix: estimate the pace slope across pace classes (centre by surface and grade only), or drop pace from the bucket key once a slope is known. **Changes scores: engine bump plus a calibration run.**
Test: extend `test_slower_easy_runs_are_not_mechanical_drift` to go through `assess_data` with pace tertiles active and `gct_ms`; flag ≤ 5 % at N ≥ 1000.
Health-risk direction: false alarm.

### S2 — carried from 2026-10-16 / 2026-10-05

| ID | Item | Status at HEAD | Evidence this run |
|---|---|---|---|
| 10-16 F4 | Coach plan ignores an active physio referral; stop hidden on Trénink | STILL OPEN | code: `coach_plan.py` unchanged since 7212123 |
| 10-16 F5 | Dedupe deletes the second copy's pain rating | STILL OPEN, CONFIRMED | ratings pain 0 and pain 6 (Achilles) → only pain 0 left |
| old F4 | v3 loses the terrain-weighted spike (`engine.py:1548` `_v2 = _emode() == "v2"`) | STILL OPEN | code |
| old F5 | History digest misses `Shoe` / `ReturnToRun` | STILL OPEN | code (`history.load_inputs` unchanged) |
| old F6 | After an engine switch, live hysteresis uses the other engine's stored quadrant | STILL OPEN | code |
| old F7 | Critical-speed cache keyed on `(day, ids)` | STILL OPEN | code |
| old F8 | Dnes "Stabilní · Skóre 100" on bootstrap failure | STILL OPEN | `/tmp/rv-h/shots/neterr_app_today_400.png` (critical v3 runner shown as "Stabilní · SKÓRE 100 · nízké riziko") |
| old F10 | One transient Garmin error disables auto-sync for everyone | STILL OPEN | `garmin_live.py:458-459` → `integrations.py:722-725` |
| old F11/F12 | Uploads unbounded; malformed files → 500 | STILL OPEN, CONFIRMED | 6 malformed uploads → 500; zip traversal is safe (400) |
| old F13 | Login throttle bypass via X-Forwarded-For | STILL OPEN, CONFIRMED | 10 wrong passwords with rotating XFF → 10 × 401, no 429 |
| old F14 | Physio reads outside `/api/runners/` not access-logged | STILL OPEN, CONFIRMED | `POST /api/ai/brief`, `GET /api/engine/inputs/{rid}` and the triage claim leave no log row |
| old F15 | Upper-abdominal pain → lower-abdomen programme | STILL OPEN | `programs_library.py:475` |
| old F16 | Pain programmes framed as treatment | STILL OPEN | `programs_library.py:446` "úspěšné léčby", `:409/:474` |
| old F17 | Not-a-medical-device note missing from most views | STILL OPEN | only `training.tsx:1489`, `landing.tsx:1081`, `coachview.tsx` |
| old F18 | "6 týdnů (Fuller 2017)" shoe transition | STILL OPEN | `profile.tsx:495` |

### S3 — new this run

Engine
- **Segment-scored metrics are gated by the per-run means.**
  - `_mech_inputs` replaces a metric's z/state with the segment result, but the worthwhile factor still uses the per-run `baseMean`/`recMean` (`engine.py:3399-3407`, `3544-3547`). A change confined to one gradient band (e.g. downhill GCT) that does not move the whole-run mean is zeroed, so the finer segment scoring loses most of its purpose.
  - LIKELY (code path; the end-to-end generator had no streams). False reassurance. Also a product question.
- **Rounded display means feed the score.**
  - `baseMean`/`recMean` are `r2()`-rounded (`engine.py:1130-1131, 1184-1185`) and then used for `shift / SWC` (`:3544-3547`). For vertical ratio (SWC 0.24) the rounding moves worth by up to 0.04, i.e. up to about 1.4 points at z 2.
  - The stored `worth` is rounded again before the sandbox is seeded from it (`sensitivity.py:530`). Example: z 1.8, worth 0.6349 vs 0.63 → 13 vs 12 points.
  - This is the watchlist pattern "rounded ratio used for points". CONFIRMED by code (sandbox parity held on the 36 demo cases).
- **The v0.12.17 gate also changes v1.** The block is not gated on `_sensitive()`; v1 shown rates fall from ≈ 3.5 % to 0.1–1.3 %. The ENGINE_VERSION note does not say v1 changed. CONFIRMED. Ask the owner.
- **Segment session drift is under-scaled when within-run noise dominates.** DI SD is 0.76 (range 0.57–0.86) for a 0.5 / 12 variance split. PLAUSIBLE. Mild false reassurance (`/tmp/rv-d/seg.py`).
- **Tests loosened alongside the sensitivity cut** (`test_engine_toggle.py:61`, `test_regression.py:77`). No replacement test pins detection power (see F4). CONFIRMED.

Frontend / copy
- **The Mechanika band "norma ± podstatná změna" (baseline ± 1 SWC, `tabs.tsx:649-652`) does not match the score.**
  - Worth starts at 0.5 SWC and the band is symmetric, while worth counts only the risk direction.
  - tichydrift GCT: the trend ends at 259 ms, inside the band 251–262 ms, while the engine has norm 1 and the flag on. The card value (262, recMean) differs from the chart's end (259).
  - CONFIRMED.
- **The morning report shows "Připravenost —" for v1/v2 runners while Dnes shows 100 %.** `daily_report.py:174` reads only `capacity.readiness` (v3 only). CONFIRMED.
- **The rule-based morning-report text is labelled "Hodnocení AI".** With no LLM, `report/ai` stores `ReportNote.notes = {}`. `cached()` then returns `{}` (not None), so `aiPending` becomes False and `report.tsx:1655` marks the text as AI (`runners.py:1218-1219`). CONFIRMED (DB rows + screenshot). Labelling (F5/I1).
- **Deník check-in denominator is one day short west of UTC.** `tabs.tsx:~213`: `Date.parse(today) + 864e5` is UTC midnight. Los Angeles shows "1/3" on a Thursday (should be 1/4); on a Monday "x/0" is possible. CONFIRMED; Prague is correct.
- **The new Deník run-totals line reuses `hm()`.** It prints "13:29" with no unit and can print "1:60" (`tabs.tsx:403/453`). CONFIRMED; joins the known x:60 family.
- **Guidance copy has an English leftover:** "…a zároveň engine doporučuje fyzioterapeuta" (`guidance.py:1191`, seen on Trénink). CONFIRMED.
- **/admin:**
  - a runner with 0 activities is listed as "Stabilní";
  - in 24 h mode the rows still say "2 aktivních dní" and "0 min na návštěvu".
  - CONFIRMED.

Ingestion / ops
- **The 24 h engagement window mixes time zones.** `now` is Prague time (`admin.py:89-93`) but the row hour is the client's local hour. Clients east of Prague have hours "in the future" dropped, and pre-update rows from today count as 12:00, so they stay hidden until noon. CONFIRMED (owner analytics only).
- **Apple push: a wrongly shaped JSON payload → 500.** `{"data":"x"}` or `{"data":{"metrics":"x"}}` raise AttributeError at `apple_health_ingest.py:136/145`. Nothing is stored. CONFIRMED.

Evidence / docs (phase I, C14)
- **The engine documentation stops at v0.12.16.**
  - It still says "Výchozí mrtvá zóna je 0,2 SD" (`Documentation/engine/Engine_Doslap_dokumentace.html:139` and the PDF built from it).
  - Nothing documents ±2.5 winsorising, `MECH_STAT_DEAD` 0.4, `MECH_SHOW` 0.5, the worthwhile ramp, `MECH_SWC_DEFAULT`, the norm verdict, or the flag rules.
  - The header still says v0.12.0, dated 4. 10. 2026.
  - CONFIRMED.
- **`SIG_DOC` and `METRIC_INFO` do not describe the new verdict.**
  - `sig_doc.py:14-80`: cadence and vertical oscillation still say "signál při z ≤ −1 / z ≥ 1"; vertical ratio "clear" says "±1 SD po tři tréninky".
  - `metricinfo.ts` never explains "na hraně / mimo normu" or the SWC.
  - CONFIRMED.
- **The SWC rationale is overstated, and the cadence gauge is wrong.**
  - Thornton et al. 2019 (IJSPP 14(6):698-705, PMID 30676144) is about team-sport monitoring. The "0.2 × between-subject SD" default comes from Hopkins 2004, and the full text of Thornton could not be retrieved to confirm the wording.
  - Garmin's gauges are percentiles (5th / 95th), as the code says. Vertical ratio, vertical oscillation and GCT match the chest-strap ranges; the Running Dynamics Pod has wider ones.
  - **Garmin's cadence gauge is 153–183 spm, not 151–185.** So the SD is ≈ 9.1 and the SWC ≈ 1.8, not 2.1.
  - A between-runner SD pooled over all paces is a convention for a within-runner, pace-adjusted change, not evidence for it.
  - CONFIRMED (the cadence number) / LIKELY (the rest).
- **Daanen et al. is Sports Med 2018;48:409-430 (PMID 29129022), not 2017** (`goal_plan.py:992`, `summaries.json` `daanen-et-al-2017`). The ~2.5 %/day claim is correct. CONFIRMED.

### S3 — carried, re-checked and still open
- **From 2026-10-16:**
  - the x:60 duration and pace helpers: `rundetail.tsx:20-23`, `runprofile.tsx:119`, `training.tsx:546`, `report.tsx:25-27`, `tabs.tsx:403` and `:2075`; plus a probable new instance at `coachview.tsx:301`;
  - Trénink stays on "Načítám…" forever when bootstrap fails, and Trénink drops out of the nav;
  - tap targets of 17–18 px (Dnes "Zobrazit (2)", Trénink "tabulka", "připravenost teď"; a 13×16 checkbox on Data);
  - demo accounts seeded as v1 without `running_since`, so every demo login hits the profile gate;
  - the coach-link token, and the Apple `?token=`, appear in access logs;
  - CSRF is accepted with no Origin header;
  - the export lacks planned_sessions, goals, shoes, coach_links, access_log and usage_days;
  - there is no account-deletion route;
  - plan import with `week=9999-12-31` → 500;
  - DEPLOY.md misses about 36 environment variables (DOSSLAP_OWNER_EMAILS, the LLM / ASR / VISION keys, DOSSLAP_BACKUPS, DOSSLAP_PRECOMPUTE, …);
  - the "1,6×" figure attributed to Nielsen 2014 instead of Frandsen 2025;
  - wrong citation years: Heikura (2017 → 2018), Kraus (2018 → 2019), Doherty;
  - the 45-min Z4+ cap is undocumented;
  - `METRIC_INFO.capacity` omits the v0.12.6–v0.12.10 rules.
- **From 2026-10-05:** S3-3, S3-5, S3-6, S3-7, S3-8, S3-10, S3-12, S3-13, S3-14, S3-15, S3-17, S3-18–S3-25, S3-27, S3-29 (now seen as a 403 console error from `/api/engine/outcomes` on /data for every non-owner).
- **Not re-checked this run:** the other 10-16 S3s outside the touched areas. They are assumed open because their code is unchanged.

## Fixed / closed since last review
- **2026-10-16 F7** (suite red, colliding test e-mail): fixed in 416ba77; the suite is green at 691/2/0.
- **van Poppel year:** 2021 is now used everywhere. Closed.
- **2026-10-16 calibration S3 "v1 GCT false-signal 7.8–9.2 %":** end-to-end it is now 1.2–1.3 %. The v0.12.17 gate masks it, but the drift core still gives 8.5–10.3 %, so the 14-day window issue is not gone. Treat it as superseded by F4/F7.

## Product questions (not defects)
- **v0.12.17's purpose was to stop every metric reading "na hraně".** Is "≥ 55 % detection of a +1 SD / 14-day change" still the target, or should the playbook's Phase D target change? Today the two conflict (F4).
- **Should segment-scored metrics be judged by the segment shift rather than the whole-run mean?** (segment S3)
- **Should v1 get the v0.12.17 gate?**
- **The quadrant grid was removed from Dnes (4c17c7d)**, while playbook §2 still says "the quadrant is the first element on Dnes". Please confirm the new decision so the playbook can be updated.
- **Carried:** climb-channel memory after long breaks; the risk path during an energy hold, after a bone stress injury, or in the first year of running; seeding the demos as v3 with `running_since`; playbook §2/C8 out of date.

## Improvement proposals (S4)
**Quick wins** (< 1 h, no score change):
1. **One verdict for every surface (F6).** The chip, rail, techNote and weekly text read `mechFlag` / norm. Validation: a stable + norm-1 snapshot and a coach-text unit test.
2. **Mechanika band at baseline + 0.5 … 1.5 SWC, in the risk direction only, labelled as the gate.** Validation: the band contains the end of the trend exactly when the norm is 0.
3. **Fix `daily_report.py:174` readiness for v1/v2, and the "Hodnocení AI" label** (treat `{}` as "no AI"). Validation: a v1 report shows readiness and no "AI" label with keys off.
4. **One shared `fmtDur` helper that rounds before splitting.** It replaces `hm`, `dur` and the 6 other copies, and the diary line gets a unit. Validation: a unit test at 119.6 min and 179.6 s.
5. **Correct the cadence SWC (1.8), cite Hopkins 2004, update the engine documentation, `SIG_DOC` and `METRIC_INFO` for v0.12.16–19, and fix the Daanen year.**

**Larger work:**
6. **Recalibrate the worthwhile gate (F4) and the pace slope across pace classes (F7)** in one engine bump. Validation: the Phase D harness in `/tmp/rv-d/calib.py` plus pinned tests for detection ≥ 55 % and pace flag ≤ 5 %.
7. **Make the three S1s release blockers:** a verified physio claim, merge-only imports, and a consent gate for report AI.
8. **Add a demo-quadrant test**, so a scoring change that silently breaks the demos fails CI (F5).

## Calibration table vs previous review (phase D)

| Check | Target / fail | This review (HEAD, end-to-end through `assess_data`, N 1000–2000 × 3 seeds) | 2026-10-19 quick | 2026-10-16 full |
|---|---|---|---|---|
| Shown per metric, no change, v1 | ≈ 3.5 % | VR 0.8–1.3, vosc 0.1, cad 0–0.1, GCT 1.2–1.3 (core: 4.5–5.7 / 4.2–4.7 / 0.7–1.4 / 8.5–10.3) | — | VR 3.0–4.4, vosc 3.5–4.6, cad 0.2–0.6, GCT 7.8–9.2 |
| …v2 (= v3), mid noise | ≈ 5 % / > 8 % | VR 1.8–1.9, vosc 0.1–0.6, cad 0–0.1, GCT 0.5–0.9; high noise VR 4.5–5.3 | — | 3.4–6.2 |
| "Mechanika přetrvává" flag, no change | ≈ 5 % / > 8 % | 2.0–2.6 (low noise 0.6–0.9, high 4.2–5.1) | v2 6.7 (N 75) | 3.1–4.5 |
| Flag at 1 SD improvement | 0 % / > 1 % | 0.0 | — | 0.0–0.1 |
| Easy runs +25 s/km, form unchanged | ≤ 5 % / > 10 % | **flag 39–43 %**; silent quadrant 1.6–1.8 % (v0.12.16 end-to-end: flag 52–56 %, silent 20–22 %) | — | flag 10.5–12.1 % (core with fixed cuts) |
| Detection +1 SD over 14 d (v2) | ≈ 67 % / < 55 % | **shown 41.7–44.5 %** (core 66–69 %); cadence 7.7–9.0 % | — | 63.3–65.9 % |
| Segment session drift SD | 0.8–1.25 | 0.95–1.02 (4 splits); 0.76 for a within-dominated split | — | 0.90–1.17 |
| Segment significance FPR, 5-segment baseline | ≈ 5 % / > 7.5 % | 4.7–5.3 % | — | 4.4–5.2 % |
| Demo accounts today (v3) | Tichý silent, Kritické critical | **stable (mech 21); overreaching (mech 22, load 66)** | critical | silent (37); critical |
| Stable demo runners, 90-day v3 replay, Zátěž ≥ 25 | ≤ ~30 % of days | 0–29 % (Kritické 30 %) | — | 0–29 % (Kritické 30 %) |
| Physio override in guidance | only pain > 5 + referral | unchanged (`guidance.py` untouched since 7212123; code check) | live OK | OK |

Shift explanations:
- **Rows 1–3 and 6:** v0.12.17 (±2.5 cap, dead zone 0.4, show 0.5, worthwhile factor). The drift core numbers are unchanged.
- **Row 5:** this review's harness runs end-to-end with the runner's own pace tertiles; 2026-10-16 measured the core with fixed cuts. A/B on v0.12.15 / v0.12.16 / HEAD with the same generator is in F7.
- **Row 9:** v0.12.17 (A/B in F5).

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 5 commits since `7212123` |
| A2 environment | PASS | Python 3.11.17 venv, Node 22.22.0; Postgres 16 binaries present |
| A3 backend tests | PASS | 691/2/0, 269 s (+3 tests since 10-19; the time includes parallel load) |
| A4 frontend | PASS | tsc OK, build OK (chunk warning) |
| A5 compileall | PASS | `app` and top-level scripts |
| B1 discovery | PASS | every role at its hinted location; new `mech_anchor`, `MECH_SWC_DEFAULT` in `engine.py` |
| B2 inventory | PASS | 195 router endpoints in 23 modules (+3 in main), 56 models; no new routes; 1 new column `usage_days.hour` |
| B3 disappeared roles | PASS | Dnes quadrant grid removed (product change, see drift) |
| C1 mode plumbing | FAIL (carried) | old F4, S3-3; no new `_emode()` comparisons; the gate applies to v1 too (S3) |
| C2 time | PASS | no new wall clock in metrics; `admin.py` uses `datetime.now(LOCAL_TZ)` (router, S3 timezone note) |
| C3 replay parity | PASS on demo / FAIL carried | 36/36 live = history (12 runners × 3 modes); old F5/F6 carried |
| C4 caches | PASS (new) / FAIL carried | history key = engine version + HISTORY_VERSION + code fingerprint + priors; old F7 carried |
| C5 direction/units | FAIL | F7 (pace slope off under pace tertiles) |
| C6 rounded values | FAIL (minor) | rounded `baseMean`/`recMean` → worth; rounded worth seeds the sandbox |
| C7 capacity invariants | PASS | `capacity.py` unchanged |
| C8 guidance invariants | FAIL (carried) | 10-16 F4 coach mode; `guidance.py` unchanged |
| C9 sandbox parity | PASS | 36/36 (v1/v2/v3 × 12); note the suite tests only stored modes, all v1 on a fresh DB |
| C10 statistics | PASS (S3) | segment worth gate; segment DI 0.76 edge |
| C11 stream pipeline | PASS | SEG_VERSION unchanged; no stream code in the diff |
| C12 robustness | PASS | `mech_anchor` returns None for no runs / > 28 days; degenerate cases in the suite |
| C13 performance | PASS | live ≤ 0.13 s; demo 84-day v3 history ≤ 2.7 s; 183-day synthetic with streams NOT RUN |
| C14 docs = code | FAIL | docs stop at v0.12.16; `SIG_DOC` thresholds stale |
| D calibration | FAIL (3 rows) | F4, F5, F7 |
| E1 idempotence | FAIL | F2 (S1), 10-16 F5; Apple re-push and Garmin re-import add no duplicates |
| E2 rate limits | PASS (code) | |
| E3 tokens | PASS / FAIL carried | Fernet OK; old F10 |
| E4 auto-sync | PARTIAL | isolation OK; old F10; naive `datetime.now()` in `main.py:175` |
| E5 Apple webhook | FAIL (minor) | token required; malformed JSON → 500 |
| E6 cross-training | PASS (code) | |
| F1 CSRF | PASS | 114 mutating routes; exemptions as documented plus `/api/trener/*` (own same-origin), bearer-token annotations resolve / assistant ops, client-errors |
| F2 access control | FAIL | F1 (S1); 48 GET routes × 2 foreign actors otherwise 403 |
| F3 sessions | FAIL | old F13 |
| F4 export/secrets | PASS (note) | the root `.gitignore` does not cover a repo-root `.env` (`backend/.env` is covered) |
| F5 external LLM | FAIL | F3 (S1); "Hodnocení AI" on rule text |
| F6 uploads | FAIL | old F11/F12 |
| F7 access log | FAIL | old F14 (+ `/api/engine/inputs`) |
| G1 migrations | PASS | 7212123 DB → HEAD on SQLite and Postgres 16 |
| G2 seeding | PASS | idempotent; demo engine mode / profile gate S3 |
| G3 deploy | PARTIAL | `/api/health` OK; Docker build NOT RUN; DEPLOY.md env vars S3 |
| H1 tabs/overflow | PASS | 0 px overflow at 1360/400; /data 403 console error for non-owners (S3-29) |
| H2 Trénink nav | PASS | live engine switch updates nav |
| H3 consistency | FAIL | F6; numbers (ring, rail, trend last points, 6-month history) all agree |
| H4 numbers | FAIL (S3) | x:60 family; diary line |
| H5 Czech copy | PASS (S3) | "engine doporučuje" |
| H6 empty/error | FAIL | old F8, endless "Načítám…"; empty states OK |
| H7 tap/contrast | FAIL (minor) | 17–18 px targets; contrast ≥ 4.9:1 |
| I1 no diagnosis / disclaimer | FAIL (carried) | F15–F17; new copy clean |
| I2 evidence | FAIL | cadence gauge, Thornton/Hopkins, Daanen; 11 references newly verified OK |
| I3 docs current | FAIL | v0.12.17–19 undocumented |
| Watchlist | FAIL (2) | "rounded ratio used for points" pattern (C6); pace confound (F7). Others PASS: replay parity, one-sided flags (improvement 0 %), decimated streams / QC unchanged, unseen surface not scored, sandbox parity, tests don't switch seeded runners' engines (the browser sub-reviewer switched modes only in its own throwaway DB), "5:60" family still open |

References newly verified this run (OK): Marqueste 2008, Nosaka 2001, Tyler 2016, Miall 2018, Costa 2017, Knechtle 2011, Vesterinen 2016, Düking 2021, Hoffman & Krishnan 2014, Tanda 2011, Jaén-Carrillo 2024. Wrong: Daanen (year), Garmin cadence gauge. Partly verified: Thornton 2019.

## Coverage gaps
- **Docker image build:** no daemon.
- **Postgres FK 500 for F2:** not re-run; Postgres was used for G1 only.
- **Real LLM / ASR / vision, and Garmin live sync:** keys off and no accounts, so these were checked from code.
- **Phase D, not covered end-to-end:**
  - segment streams (so the segment worth gate is code-path only);
  - pooled priors, i.e. an SWC from data rather than Garmin's gauges;
  - weather adjustment;
  - separate v3 null and detection cells (mechanics are shared with v2).
- **Physio override:** checked from code only. `guidance.py` is unchanged, and the 10-19 quick screen confirmed it live.
- **C13:** the 183-day synthetic runner with streams was not re-timed.
- **Browser not covered:**
  - English UI, light theme, a real device;
  - run detail (`/app/post/:aid`);
  - the evening report (the test ran inside the morning window);
  - the network-error test, run on the v3 runner only;
  - `POST report/ai` called from the browser (the sandbox denied it; F3 was proved with TestClient instead).
- **References:**
  - Thornton 2019 full text: blocked (403 / 503);
  - Fuller 2017, Frandsen 2025, Sanchez-Alvarado 2024, Hecksteden 2017: not re-fetched;
  - `engine prevention plan.pdf` and the DOSLAP_* docs: not reviewed.
- **Carried S3s outside the touched areas:** not individually re-run; their code is unchanged.
- **10-16 F4 (coach mode + physio):** status by code only; `coach_plan.py` is unchanged.

## Structural drift (playbook updates proposed)
- **Dnes no longer has a quadrant grid (4c17c7d).** The quadrant lives in the QuadrantHead state chip with its sentence, and in "Vývoj stavu · 6 měsíců" opened from the Skóre ring (`data-testid="score-history"`). Update §2 "Dnes layout" and H3.
- **Mechanics verdict:** `var["norm"]` (0/1/2), `swc` and `worth` per metric; `mechFlagMetrics` in the assessment; `mech_anchor` / `conf.asOf`. Phase D recipes should measure "shown" end-to-end as `norm ≥ 1`, not z ≥ 0.6 from `_drift_z_core`. The Appendix B recipe no longer reflects what the runner sees.
- **Pace classes:** Appendix B's pace-confound probe must run with the runner's own `pace_cuts` active (through `assess_data` / `mech_scope`); the core alone uses fixed cuts.
- **F1 exemption list:** add `/api/trener/{token}` (own same-origin check), bearer-token `annotations/{aid}/resolve` and `assistant/ops/shoe-check`, and `client-errors` (own same-origin, logging only).
- **Discovery:** `def simulate(` matches 4 files (`coach_plan.py`, `readiness_compare.py`, `sensitivity.py`, `routers/simulate.py`); search `def inputs_from_assessment` for the sandbox instead.
- **Phase D row "Demo accounts today":** add a CI test so a scoring change cannot silently break it.
- **C9:** the suite's sandbox-parity test runs only each runner's stored mode (all v1 on a fresh DB). Add v2/v3.
