# Došlap review — 2026-10-30 (full review)

**Fix before the next release:**
- **Two new S1s:**
  1. **Team Console invitations can be hijacked.** A Team Console invitation is bound to an e-mail address, not to an account. Whoever registers the invited address first becomes a team member, including the owner role. Owners can read every runner's data and invite more owners (N1).
  2. **A day pinned in Plán týdne overrides the morning's safety stops.** These stops are an illness with whole-body symptoms, pain above 5/10, and check-in readiness below 45 %. The pinned run is then sized up to the safety ceiling, e.g. 15.5 km of "regenerace" at pain 6/10 (N2).
- **A related S2:** pinning "dlouhý" for today makes every recompute for that runner fail (TypeError) until the pin is removed. This affects any runner without a usual long-run day (N3).
- **The three S1s carried since 2026-10-05 are still open:**
  - physio self-registration plus case takeover, which the new physio app now widens to a full client overview;
  - re-importing a file deletes the runner's own data;
  - the report "AI notes" run without the AI consent.

Commit / working tree: `6f4bdb9` (Merge PR #2 "Moje čísla: Čerstvost, Kondice, Únava"). `main` = `origin/main`; the working tree was clean and nothing was uncommitted. `ENGINE_VERSION` v0.12.19, unchanged; `HISTORY_VERSION` h11.

Baseline: tests **752 passed / 2 skipped / 0 failed**, 236 s on Python 3.11.17 (+61 tests since 2026-10-23) · `tsc --noEmit` OK · `vite build` OK (only the existing > 500 kB chunk warning) · `python -m compileall` OK. Node 22.22.0.

How this review was run:
- **Lead reviewer:** phases A–C.
- **Three parallel sub-reviewers:** E+F+G; H (headless Chromium); D+I+C14 together with the C8 day-pin invariants.
- **Data:**
  - each reviewer used its own throwaway SQLite DB and port;
  - Postgres 16 was used for G1 only;
  - nothing external was contacted: no deployed app, GitHub API, Railway, Garmin, Apple or LLM (all keys unset, outbound HTTP mocked);
  - web access was used only to verify references.
- **The repo on `main` was not touched.** Scratch files are in the review container under `/tmp/rv-lead`, `/tmp/rv-efg`, `/tmp/rv-h` and `/tmp/rv-d`.

## Summary

**What changed.** Since the 2026-10-23 full review (`1d0f421`), 15 commits landed: 86 files, +21 596 / −8 112, most of it i18n data. Code alone: 69 files, +8 015.
- **Large new surface:**
  - the Team Console (team roles, GitHub Inbox/Work/Approvals, merging a PR from the app);
  - the physiotherapist app (`/physio`);
  - simulated runners ("personas") for staging;
  - Plán týdne → Změnit (day pins) with a calendar feed (ICS);
  - the Moje čísla Čerstvost / Kondice / Únava cards;
  - a usage-consent setting;
  - CI, clinical-gate and Claude workflows.
- **The scoring did not change.** The only change in `engine.py` is a `sim_clock` contextvar.
- **Runner-facing guidance did change.** `guidance.py` now applies today's pin. That change went straight to `main` (aa5dd97) with no engine bump, no `engine`/`safety` label and no clinical sign-off.

**What is healthy:**
- Live vs 6-month history: 36/36 identical (12 demo runners × v1/v2/v3).
- Sandbox vs live: 36/36 identical.
- Live assessment ≤ 0.29 s; a 183-day v3 replay ≤ 2.1 s.
- The null false-signal rates are still under target.
- The new tables and columns migrate cleanly on SQLite and Postgres 16.
- All 9 new runner-scoped routes pass the IDOR probes.
- The merge endpoint does what CLAUDE.md promises: live re-read, SHA match, typed MERGE, password, and a lock after 5 refusals.
- The calendar token is strong and rotatable.
- The physio app refuses clients without a care assignment and logs reads from the overview.

**What went wrong:**
- **Access is tied to e-mail strings.** Team roles bind to an address (N1), and physio status is self-declared (carried S1).
- **Day pins trust only `allowed` and the safety ceiling `max`.** They skip the softer stops and the size reductions (N2), and one of them crashes (N3).
- **The Inbox → GitHub path leaks screen text.** It includes names and pain values (N4).
- **The clinical gate reads labels only, not the code that was signed off** (N5).
- **The physio "Skóre" means the opposite of the runner's "Skóre"** (N6).
- **No carried S1 or S2 was fixed.** The physio access log and the Apple-push 500 are partly fixed.

Counts (open items at HEAD, carried included): **S1 5 · S2 25 · S3 84 · S4 15.**
- New this run: S1 2 (N1, N2), S2 5 (N3–N7), S3 14, S4 7.

## Findings (most severe first)

### S1 — new

### N1 A Team Console invitation can be claimed by whoever registers the e-mail first, including the owner role
Severity: S1 · Confidence: CONFIRMED · Area: F2 / F3

Location:
- `backend/app/routers/team.py:84-101` (`add_member`: an e-mail only, no account required);
- `backend/app/team.py:44-51` (`role_of` matches `TeamMember.email`);
- `backend/app/deps.py:114-123` (`is_owner` includes team owners);
- `backend/app/routers/auth.py:86-130` (register: no e-mail verification, client-chosen `provider`).

What happens: the role follows the e-mail string of whoever is signed in.

Failure scenario:
1. An owner invites `cofounder@…` as owner (or `clinical@…` as clinical guarantor) before that person has an account.
2. Anyone who knows or guesses the address registers it.
3. They are now owner: every runner's data via "Zobrazit jako" / `ensure_runner_read_access`, Inbox, Pilot, "go" on `ai-plan` issues, and inviting more owners.
4. As clinical guarantor they could approve engine changes.

Merging still needs `DOSSLAP_GITHUB_MERGE_TOKEN`, the typed confirmation and a password, but the squatter set that password themselves. With `provider="google"` (accepted from the client at register), the merge password re-check is skipped (`team.py:336`).

Evidence (`/tmp/rv-efg/probe1.py`):
- `add owner (no account) 200`
- `squatter registers invited email 200 owner=True team=owner`
- `squatter reads adela runner 200`
- `squatter adds another owner 200`
- after deactivation: 403.

Suggested fix:
- bind a member to an existing `user_id`, or use a single-use invite token sent by e-mail;
- refuse team roles for addresses that have no verified account;
- ignore a client-supplied `provider` at register.

Test to add: `test_invited_email_registered_by_stranger_gets_no_role`. Invite an address, register it through `/api/auth/register`, then assert `role_of` is None and `/api/runners/{rid}` returns 403.

Health-risk direction: privacy breach (all runners' health data); unreviewed clinical approvals.

### N2 Day pins override the illness, pain > 5 and low-readiness stops and size runs up to the safety ceiling
Severity: S1 · Confidence: CONFIRMED · Area: C8 / D (guidance)

Location:
- `backend/app/metrics/guidance.py:1407-1427` (the pin branch checks only `types[t]["allowed"]` and the override, then `hi = min(want, km["max"])`);
- illness handling at `:1243-1245` (blocks only dlouhý / kvalitní / posilování; the "volno" default comes from the pick, not from a block);
- the pin is applied after `xt_pick` (`:1393-1405`);
- `backend/app/metrics/week_plan.py:981, 1017-1030, 1042` (the options slider tops out at `max`, and `_status` rates these pins "ok").

What happens: today's pin wins whenever the type is not explicitly blocked. The softer no-run and size rules are not encoded as blocks, so a pin silently overrides them, and its size runs to `max` (the per-run/weekly safety ceiling), not to the scaled recommendation.

| Morning state (demo runner Pavel Urban, v3) | App's own pick | With a pin |
|---|---|---|
| Illness reported, symptoms below the neck | volno ("Hlásíte nemoc — tento týden nejdřív odpočinek") | **lehký 6.3–20.7 km, 36–116 min** |
| Pain 6/10, no referral (§2: regeneration or cross-training) | voda (spares the painful site) | **regenerace 3.7–15.5 km, 97 min** |
| Pain 4/10 (shorter / easier day) | lehký 4.4–5.7 km | lehký up to **18.8 km** |
| Check-in readiness < 45 % ("pod 45 % jen regenerace nebo volno") | regenerace 2.9–4.3 km | **lehký** up to 20.7 km |

- The browser run saw the same behaviour: adela at pain 4/10 got a Regenerační slider of 4,5–13 km, while the type itself was 2,9–4,4 km.
- The physio override, an active injury, morning-worse tendon pain and other overrides are respected (PASS).
- Quality pins are refused correctly.
- Pins for future days stay inside the weekly budget.

Failure scenario: on Monday a runner pins Friday as "lehký 15 km". On Friday they check in with fever-type symptoms. Dnes, Trénink and their Google calendar still show the 15 km run.

Evidence: `/tmp/rv-d/pins.py` → `/tmp/rv-d/pins.out` (re-run by the lead), and `/tmp/rv-h/shots/pin_training_after_400.png`.

Suggested fix:
- encode every no-run / reduced default as `block()` (illness → regenerace + lehký blocked; pain > 5 → lehký blocked and running pins refused while `pain_rest` holds; gscore < `READY_EASY_ONLY` → lehký blocked), so `allowed` is the single source of truth;
- cap a pinned km at the unpinned `types[t].km.hi`, not `max`, and give the slider the same top;
- treat the change as an engine-output change: bump `ENGINE_VERSION`, label it `safety`, get clinical sign-off.

Test to add: `test_pin_respects_illness_pain_readiness`. For each of the four states, a pinned run gives `g["type"]` equal to the unpinned type (or `pin.applied is False`), and pinned km ≤ the unpinned `hi`.

Health-risk direction: **false reassurance** (unsafe training on an ill or painful day).

### S1 — carried, re-verified at HEAD

### F1 (2026-10-05) Anyone can register as a physio and claim any runner's case — STILL OPEN, wider now
Severity: S1 · Confidence: CONFIRMED · Area: F2

Location: `routers/auth.py:92` (role from the body), `routers/triage.py:71-96` (`claim`: no check of `claimed_by`, consent, or status), `routers/physios.py:242-302`.

Evidence (`/tmp/rv-efg/probe2.py`):
- A self-registered physio claims triage 1, which phy-0001 holds → 200.
- `GET /api/physios/me/clients/run-0001` → 200: name, age, sex, city, prior injury "Achillova šlacha", 42 days of check-ins with pain and site, injuries and RTR.
- Claiming a case for run-0008 (`physio_interest=False`) → 200, and that overview → 200.

Booking confirmation adds no new hole.

Suggested fix: verified or owner-approved physio accounts. `claim` refuses an already-claimed or closed case and a runner without consent.

Test: `test_claim_requires_consent_open_unclaimed_unrevoked`.

Health-risk direction: privacy breach; the real physio's care is taken over.

### F2 (2026-10-05) Re-importing a Garmin or Apple file wipes manual activities and ratings — STILL OPEN
Severity: S1 · Confidence: CONFIRMED earlier; the code is unchanged (`routers/integrations.py:119` `_apply_seed`, empty diff) · Area: E1

Not re-run this week. Fix as before: merge by `external_id`, never delete manual data.

Health-risk direction: false reassurance.

### F3 (2026-10-05) Report "AI notes" call the LLM without the AI consent — STILL OPEN
Severity: S1 · Confidence: CONFIRMED earlier; code unchanged (`routers/runners.py:1361` → `metrics/report_ai.py:118`, which gates only on `assistant_available()`) · Area: F5

Fix and test as before.

Health-risk direction: none (consent / privacy).

### S2 — new

### N3 Pinning "dlouhý" for today makes every recompute fail
Severity: S2 · Confidence: CONFIRMED · Area: C12 / C8

Location: `backend/app/metrics/guidance.py:1637` (`WD_IN[pat['longDay']]` when `longDay` is None); `engine.py` `recompute_assessment` has no guard around `build_guidance`.

What happens:
1. `options` and `preview` rate "dlouhý" today as "ok".
2. `PUT /week-plan/pins` commits the pin, then recomputes.
3. The recompute raises `TypeError: tuple indices must be integers or slices, not NoneType`, so the PUT returns 500.
4. Every later recompute for that runner fails until the pin is deleted or the week ends.

Affected: any runner without a usual long-run day, e.g. demo Pavel Urban.

Evidence: `/tmp/rv-d/crash.py` (re-run by the lead; traceback at `guidance.py:1637`).

Suggested fix: `if typ == "dlouhý" and pat["longDay"] is not None:`.

Test: `test_long_run_pin_without_usual_long_day` (recompute succeeds and the type is dlouhý).

Health-risk direction: none (availability). A runner's Dnes and Trénink stop updating.

### N4 "Send to AI team" copies raw screen text (names, pain values) into the GitHub issue
Severity: S2 · Confidence: CONFIRMED (mechanism) / LIKELY (real notes carry such text) · Area: F6 / F5

Location: `backend/app/team.py:370-391` (`issue_body` appends `a.route`, `a.anchor_text`, `context.heading`); `frontend/src/annotate.tsx:108-111` (the anchor is the clicked element's `innerText`, up to 160 characters).

What happens: the owner edits the note text, but the issue still carries the untouched screen context. A physio note on a client screen produced:

```
- Obrazovka: `/physio/clients/run-0001 — „Adéla Nováková · bolest 6/10 Achillova šlacha“ (sekce Adéla Nováková)`
```

The owner-edited text was "Edited neutral text". This breaks the CLAUDE.md hard rule ("never a name, e-mail or health data").

Evidence: `/tmp/rv-efg/probe3.py` (GitHub client faked).

Suggested fix: send only route patterns with ids replaced, plus the owner-edited text. Alternatively, put the anchor and heading into the editable preview so the owner sees and edits them.

Test: an annotation with a name in `anchor_text` gives an issue body that does not contain it.

Health-risk direction: privacy (health data to a third-party processor).

### N5 The clinical sign-off is not tied to the approved code, and the gate reads labels only
Severity: S2 · Confidence: CONFIRMED (server) / LIKELY (workflow) · Area: G3 / process

Location:
- `backend/app/team.py:618-640` (`merge_blockers` checks labels);
- `backend/app/routers/team.py:416-444` (`decide` records `head_sha` in the audit but never compares it);
- `.github/workflows/clinical-gate.yml` (label names only; no check of who labelled; the approval survives new pushes).

What happens: a WorkItem was approved at head `aaaa…`, and the live PR head was `bbbb…` with `engine` + `clinical-approved`. `merge_blockers` returned `[]` and `POST /api/team/pr/7/merge` returned `200 {merged: true}`.

Failure scenarios:
- thresholds are pushed after sign-off and the label still passes;
- anyone with label rights, including the AI team's GitHub access, adds `clinical-approved`;
- a PR that touches `backend/app/metrics/` without the `engine` label is never gated. aa5dd97 (N2) shows that engine-adjacent changes do reach `main` without the gate.

Suggested fix:
- store the approved head SHA and block when the live head differs;
- remove `clinical-approved` on `synchronize`;
- in the workflow, verify that the labeler is the Team Console identity;
- require `engine`/`safety` by path (`backend/app/metrics/**`, `programs_library.py`).

Test: approve at SHA A with live head B → a blocker exists.

Health-risk direction: unreviewed changes to what runners are told.

### N6 The physio app's "Skóre" has the opposite meaning from the runner's
Severity: S2 · Confidence: CONFIRMED · Area: H3

Location: `frontend/src/physio/client.tsx:118` (`<Score v={a.overall}>`), `physio/queue.tsx:70`, the physio calendar "· skóre N". The runner app shows `100 − overall` (`App.tsx:626, 892`, railway#99).

What happens: adela on a high-risk day (pain 7, limited movement) shows as "Skóre 100" in the physio queue, client overview and calendar, while her own ring is low. Low-risk clients show "skóre 18".

Evidence: `/tmp/rv-h/shots/physio_1360__physio_client_run_0001.txt` ("vysoké riziko … Skóre 100"), `physio_400__physio.png`.

Suggested fix: show `100 − overall` as the ring does, or rename the figure "Riziko".

Health-risk direction: false reassurance (a physio skimming the calendar reads 100 as good).

### N7 The body-map images come from a third-party host; picking a painful muscle tells it which one
Severity: S2 · Confidence: LIKELY (the base image fetch was seen in the browser; the per-muscle request is from code) · Area: F6 / I

Location: `frontend/src/components/MuscleAnatomy.tsx:163-201` (32 `https://i.ibb.co/…` URLs) and `:365-372` (one `<img>` overlay per selected muscle). Used in the check-in, Care, Capacity and the tabs.

What happens:
- Opening the check-in fetches `i.ibb.co/…/Muscle-M-FRONT.png`.
- Selecting a painful muscle requests e.g. `Male-Back-Hamstrings.png`. The image host then gets the runner's IP and which body part hurts.
- If the host deletes the images, the body map breaks.
- The page never reaches network-idle.

This code dates from fef43f6 (2026-10-12) and is not in any earlier report.

Suggested fix: bundle the PNGs in `frontend/public` (same-origin).

Test: a build check that no `https://` image URL is in `src/`.

Health-risk direction: privacy.

### S2 — carried, re-measured

| ID | Item | Status at HEAD | Evidence this run |
|---|---|---|---|
| 10-23 F4 | v0.12.17's worthwhile gate pushes detection of real drift below the fail line | STILL OPEN | +1 SD/14 d shown VR 34–38 %, vosc 22–24 %, cad 6 %, GCT 7–10 % (target ≈ 67 %, fail < 55 %). The new harness has pace-independent VR, so it is not directly comparable to 41.7–44.5 %. `engine.py:3567` |
| 10-23 F5 | Demo accounts lost their scenarios | STILL OPEN | tichydrift v3 stable (mech 21); kritickepretizeni overreaching (mech 22, load 100, symp 81) |
| 10-23 F6 | Dnes, the rail, the Mechanika cards and texts disagree about technique | STILL OPEN, wider | tichydrift: chip "mimo normu" vs rail "drží na normě" vs card "na hraně" vs headline "v rámci obvyklého středu". **New:** kritickepretizeni (v3) says "Technika zatím drží." under the "⚑ kontakt se zemí mimo normu" chip; the v0.12.19 `techNote` covers `stable` only (`App.tsx:559`, `shell.tsx:162`) |
| 10-23 F7 | Pace confound: slower easy runs flag | STILL OPEN | v2 flag 32–34 %; **v1 shows cadence and GCT in 48–50 %** (new row); pace correction active in 12.5–14.9 % (`engine.py:969-1003`, bucket key `:433`) |
| 10-16 F4 | Coach plan ignores an active physio referral | STILL OPEN | code |
| 10-16 F5 | Dedupe deletes the second copy's pain rating | STILL OPEN | code unchanged |
| old F4 | v3 loses the terrain-weighted spike (`engine.py:1570`) | STILL OPEN | code |
| old F5 | History digest misses `Shoe` / `ReturnToRun` | STILL OPEN | `history.load_inputs` unchanged |
| old F6 | Live hysteresis uses the other engine's stored quadrant after a switch | STILL OPEN | code |
| old F7 | Critical-speed cache keyed on `(day, ids)` | STILL OPEN | code |
| old F8 | Dnes "Stabilní · Skóre 100" on bootstrap failure | STILL OPEN (partly) | an error banner with "Zkusit znovu" now shows, but Stabilní / 100 / "nízké riziko" still render under it (`/tmp/rv-h/shots/neterr_400__app_today.png`) |
| old F10 | One transient Garmin error disables auto-sync | STILL OPEN | `garmin_live.py:456-459` → `integrations.py:722-724` |
| old F11/F12 | Uploads unbounded; malformed files → 500 | STILL OPEN, CONFIRMED | garbage zip, `{"a":1}` and `[1,2]` → 500 on Garmin and Apple import; `integrations.py:184` reads unbounded |
| old F13 | Login throttle bypass via X-Forwarded-For | STILL OPEN, CONFIRMED | 15 × 401 with rotating XFF, then 200 with the correct password |
| old F14 | Physio reads not access-logged | PARTLY FIXED | the new overview and documentation log; `/api/physios/me/clients` (N-S3), `/api/ai/brief` and `/api/engine/inputs` do not |
| old F15 | Upper-abdominal pain → lower-abdomen programme | STILL OPEN | `programs_library.py:475` |
| old F16 | Pain programmes framed as treatment | STILL OPEN | `programs_library.py:446` "úspěšné léčby" |
| old F17 | Not-a-medical-device note missing from most views | STILL OPEN | the physio queue and overview also lack it |
| old F18 | "6 týdnů (Fuller 2017)" shoe transition | STILL OPEN | `profile.tsx:499` |

### S3 — new this run
Security / privacy / process
- **The physio client list is not access-logged.** `physios.py:179-227` returns each client's last pain score and site, tier, the last message (120 characters) and programme adherence. Access-log rows before and after: 0 / 0. CONFIRMED.
- **`share_with_physio` is honoured only in part.** With it off, the physio overview hides weeks and activities but still shows check-ins, pain, injuries and RTR. The `/api/runners/{rid}/*` reads ignore it entirely (`physios.py:257-293`). LIKELY. Decide whether to retire or enforce it.
- **The calendar feed exports pain-site notes to Google or Apple.** Ride notes such as "tlak v čéšce nízký" come from `cross_for_sites` (`routers/calendar.py:132`, `week_plan.py:726/747`). The token is in the URL and stored unhashed. LIKELY.
- **A non-ASCII `X-Hub-Signature-256` / `X-Persona-Token` header → 500** (`team.py:118, 510`: `compare_digest` on str). These are unauthenticated endpoints. CONFIRMED.
- **DEPLOY.md misses 15 new environment variables.** They include DOSSLAP_GITHUB_TOKEN / _MERGE_TOKEN / _WEBHOOK_SECRET / _REPO, DOSSLAP_RAILWAY_TOKEN, DOSSLAP_STAGING_URL, DOSSLAP_PERSONAS / _PERSONA_TOKEN / _PERSONA_REPORT_URL and DOSSLAP_SYNTHETIC_DAILY_CAP. In total 54 of 61 variables are missing. CONFIRMED.
- **Process: the guidance change went straight to `main`.** aa5dd97 changed runner-facing guidance (day pins) with no PR, no `ENGINE_VERSION` bump and no clinical review, contrary to CLAUDE.md. Its commit trailer also names a model, which CLAUDE.md forbids. CONFIRMED.

Physio app / UI (H)
- **The physio app labels "nízké/střední/vysoké riziko" with no object and no boundary note** (`physio/common.tsx:28`, `queue.tsx:60-62`, `client.tsx:17/29`). CONFIRMED.
- **Physio formats are wrong:**
  - "běhá od 1. 3." has no year (`client.tsx:84`);
  - the AI-summary text uses decimal points and wrong plurals ("×0.43", "64.3 ms", "1 dní", "3 bodů"; `metrics/ai_brief.py`).

  CONFIRMED.
- **The physio calendar "Smazat termín" is 16 × 16 px and deletes with no confirmation** (`physio/calendar.tsx:120`). CONFIRMED.
- **The new Čerstvost / Kondice / Únava cards send v1/v2 runners to a hidden Trénink page.** "Více na stránce Trénink" leads to "Denní doporučení … není zapnuté" (`metricsheet.tsx:24-43`, `shell.tsx:167-169`). The same holds for the HRV / RHR / sleep / readiness sheets. The sheet's "42 %" lacks a "+", and negatives use a hyphen. CONFIRMED. The values match `/fitness-trend`.
- **The calendar subscription is offered to v1/v2 runners, but their feed has 0 events** (`profile.tsx`, `/tmp/rv-h/ics_tichydrift.txt`). The "Co je nového" items about Změnit are shown to everyone. CONFIRMED.
- **A pin cancelled by the morning data is never mentioned.** The override hides the day list, so "Vaše změna už nejde" (`report.tsx:657`) never renders (`training.tsx:1277/1298`). CONFIRMED.
- **The runner's own pin is labelled "doporučeno na dnešek" / "Dnes doporučeno"** (`training.tsx:1139`, `App.tsx:775`). The "Posilování 0 km + …" option text is also odd. CONFIRMED.
- **Double full stop** "z 29. 10.. Posuňte" (`App.tsx:1878`). CONFIRMED.

### S3 — carried, still open
- **The labelling and reporting items from 2026-10-23 are re-confirmed in the browser:**
  - rule-based report text is labelled "Hodnocení AI" (`report.tsx:1665`, `runners.py:1219`); the physio "AI shrnutí" title shows even when no model ran;
  - the morning report shows "Připravenost —" for v1/v2 while Dnes shows a value (`daily_report.py:174`);
  - every non-owner gets a 403 console error from `/api/engine/outcomes` on /data;
  - Trénink is stuck on "Načítám…" when bootstrap fails;
  - tap targets of 16–17 px (Trénink "tabulka", Vydání "Obnovit").
- **Apple push, partly fixed:** non-JSON, `[]` and `123` now return 400, but `{"data":5}` and `{"data":{"metrics":"x"}}` still return 500.
- **CSRF is accepted with no Origin header** (known / accepted).
- **The export lacks the settings / consent, usage and access-log data;** the new token tables are rightly excluded.
- **There is no account-deletion route.**
- **Engine documentation, `SIG_DOC` and the references:** the engine documentation stops at v0.12.16 (header v0.12.0, "mrtvá zóna 0,2 SD"), and `SIG_DOC` has no SWC / 0.4 / ±2.5. These references are still wrong:
  - the cadence gauge is 151–185 (should be 153–183, SWC ≈ 1.8);
  - Thornton is cited instead of Hopkins 2004;
  - Daanen 2017 should be 2018;
  - "1,6×" is attributed to Nielsen 2014 instead of Frandsen 2025;
  - Heikura and Kraus have the wrong years.
- **Every other S3 from 2026-10-23, 10-16 and 10-05** in code not touched by this diff. These were not individually re-run.

## Fixed / closed since last review
- **Physio access logging, partly:** the new physio overview and documentation reads write the runner's access log.
- **Apple push malformed body, partly:** non-JSON bodies now get 400.
- **Dnes on bootstrap failure, partly:** an error banner with "Zkusit znovu" now appears; the misleading state under it remains.
- **English-mode leak (10-26 F1):** not re-checked this run.

## Product questions (not defects)
- **Day pins:** should a runner's own choice ever override a reduced-size or rest default (illness, pain 3–5, pain > 5, low check-in readiness)? This review assumes not, per §2 "pain rules" (N2).
- **Should `share_with_physio` still exist?** It is enforced only in part.
- **Should v1/v2 runners see the week-plan / calendar features and the Trénink links,** or should they stay v3-only?
- **The physio AI brief's "Směry ke zvážení"** lists tissue hypotheses with palpation and confirmation tests. It carries the "ne diagnóza" caveat, but the clinical guarantor should review the wording against the MDR boundary.
- **Carried:** Phase D's 55 % detection target vs v0.12.17's purpose; segment-scored metrics judged by the per-run means; the v0.12.17 gate also applying to v1; the playbook's §2 "quadrant first on Dnes" now being outdated.

## Improvement proposals (S4)

**Quick wins** (< 1 h):
1. **Guard `longDay` (N3)** and add the four pin-state tests from N2. The N2 fix itself needs an engine bump.
2. **`compare_digest` on bytes** for the webhook and persona token headers.
3. **Bundle the body-map PNGs (N7)** and fix the physio "Skóre" direction (N6).
4. **Personas: fail closed.** Enable them only when `RAILWAY_ENVIRONMENT_NAME == "staging"`, not "≠ production" (`personas/sim.py:32-35`).
5. **Write persona and calibration admin actions and synthetic-note writes into `team_audit`.** A persona-token holder can create 6 notes a day on production and mark resolved ones "verified" without limit.
6. **Report disjoint groups in the behaviour profile.** Today "all" (n 6) and "novice" (n 5) let the single experienced runner be inferred.

**Larger work:**
- **Invite tokens bound to accounts (N1), plus physio verification and claim rules (carried F1).** Ship both together as the access model for the team and for physios.
- **Tie the clinical approval to a head SHA, add path-based `engine`/`safety` labels and check who applied a label (N5).**
- **Carried:** recalibrate the worthwhile gate and the pace slope across pace classes in one engine bump; add a demo-quadrant test; make the S1s release blockers.

## Calibration table vs previous review (phase D)
This run: end-to-end through `assess_data` with the runner's own pace tertiles, N 1000 × 2 seeds (`/tmp/rv-d/harness.py`). The scoring is unchanged since 2026-10-23.

| Check | Target / fail | This review | 2026-10-23 full |
|---|---|---|---|
| Shown per metric, no change, v1 | ≈ 3.5 % | VR 0.1–0.4, vosc 0–0.2, cad 0–0.2, GCT 0.9–1.5 | VR 0.8–1.3, vosc 0.1, cad 0–0.1, GCT 1.2–1.3 |
| …v2 | ≈ 5 % / > 8 % | VR 1.0–1.5, vosc 0–0.4, cad 0–0.1, GCT 0.6–0.9 | VR 1.8–1.9, vosc 0.1–0.6, cad 0–0.1, GCT 0.5–0.9 |
| "Mechanika přetrvává" flag, no change | ≈ 5 % / > 8 % | 1.9–2.4 | 2.0–2.6 |
| Flag at 1 SD improvement | 0 % / > 1 % | 0.0 | 0.0 |
| Easy runs +25 s/km, v2 flag | ≤ 5 % / > 10 % | **32.2–34.1** (FAIL) | 39–43 (FAIL) |
| Easy runs +25 s/km, v1 shown (new row) | ≤ 5 % / > 10 % | **cad 48–50, GCT 48–49** (FAIL) | — |
| Detection +1 SD over 14 d (v2) | ≈ 67 % / < 55 % | **VR 34–38, vosc 22–24, cad 6, GCT 7–10; mechFlag 54–56** (FAIL) | 41.7–44.5 (FAIL) |
| Segment session drift SD | 0.8–1.25 | 0.94–0.98; 0.79 for a within-dominated split | 0.95–1.02; 0.76 |
| Segment significance FPR, 5-segment | ≈ 5 % / > 7.5 % | 4.68 / 4.79 | 4.7–5.3 |
| Demo accounts today (v3) | Tichý silent; Kritické critical | stable (mech 21); overreaching (mech 22, load 100) (FAIL) | stable; overreaching (FAIL) |
| Stable demos, 90-day v3 replay, Zátěž ≥ 25 | ≤ ~30 % of days | 0–29 % (Kritické 30 %) | 0–29 % |
| Physio override in guidance | only pain > 5 + referral | PASS; pins cannot bypass it (but see N2 for the softer stops) | OK |

Shift explanation: the scoring code is unchanged. The differences come from a new harness (different pace/metric coupling: this run's VR is pace-independent, cadence and GCT pace-coupled). The FAIL rows are the same root causes as 2026-10-23.

Side note (PLAUSIBLE, not investigated): Marek Beneš (a "clean" demo) reads overreaching on 44 % of replay days, while Zátěž ≥ 25 holds on 29 %.

## Check results

| Check | Result | Note |
|---|---|---|
| A1 what changed | PASS | 15 commits since `1d0f421` |
| A2 environment | PASS | Python 3.11.17 venv, Node 22.22.0, Postgres 16 |
| A3 backend tests | PASS | 752/2/0, 236 s (+61 tests) |
| A4 frontend | PASS | tsc OK, build OK (chunk warning) |
| A5 compileall | PASS | `app` + top-level scripts |
| B1 discovery | PASS | every role at its hint; `fetch_details` is in `backend/garmin_live.py`; `def simulate(` now matches 5 files (+`week_plan.py`) |
| B2 inventory | PASS | 237 endpoints (194 before), 64 models (56 before); new routers `team`, `physios`, `calendar`, `personas`; new tables CalendarFeed, TeamMember, TeamAudit, WorkItem, PilotSnapshot, PersonaRun …; new annotations / settings columns |
| B3 disappeared roles | PASS | none; new roles: Team Console, physio app, personas, day pins (drift) |
| C1 mode plumbing | FAIL (carried) | no new modes or `_emode()==` comparisons; old F4 remains |
| C2 time | PASS | no new wall clock; `sim_clock` contextvar is staging-only and the thread-local pin still wins |
| C3 replay parity | PASS (demo) / FAIL carried | 36/36; no new table on the assessment path; old F5/F6 carried |
| C4 caches | PASS / FAIL carried | `guidance.py` is NON_SCORING; a pin save recomputes; old F7 |
| C5 direction/units | FAIL (carried) | pace confound |
| C6 rounded values | FAIL (carried, minor) | as on 2026-10-23 |
| C7 capacity invariants | PASS | `capacity.py` unchanged |
| C8 guidance invariants | **FAIL** | N2 (pins vs illness / pain / readiness / size), N3; physio override PASS; 10-16 F4 carried |
| C9 sandbox parity | PASS | 36/36 |
| C10 statistics | PASS (edge) | segment DI 0.79 for a within-dominated split |
| C11 stream pipeline | PASS | no stream code changed |
| C12 robustness | FAIL | N3 (None `longDay`) |
| C13 performance | PASS | live ≤ 0.29 s (under test load); 183-day v3 replay ≤ 2.1 s; with streams NOT RUN (the demos have none) |
| C14 docs = code | FAIL (carried) | docs stop at v0.12.16; no doc for pins |
| D calibration | FAIL (4 rows) | pace confound (v1 + v2), detection, demos |
| E1 idempotence | FAIL (carried) | F2 S1, code unchanged; 10-16 F5 |
| E2 rate limits | PASS (code) | unchanged |
| E3 tokens | PARTIAL | the calendar token is fine; old F10 carried |
| E4 auto-sync | PARTIAL | old F10 |
| E5 Apple webhook | FAIL (minor) | partly fixed; dict-shaped garbage → 500 |
| E6 cross-training | PASS (code) | unchanged |
| F1 CSRF | PASS | 137 mutating routes: 119 `verify_csrf`, 18 documented exemptions or token/HMAC/same-origin routes |
| F2 access control | **FAIL** | N1, carried F1; 9 new runner routes × 3 actors = 27 probes, all 401/403 |
| F3 sessions | FAIL (carried) | XFF throttle bypass; register accepts `provider` |
| F4 export/secrets | PASS | no tokens in the export; new token tables excluded |
| F5 external LLM | FAIL (carried) | F3 S1; "Hodnocení AI" on rule text |
| F6 uploads / privacy | FAIL | old F11/F12; N4, N7 |
| F7 access log | FAIL (improved) | the client list, `/api/ai/brief`, `/api/engine/inputs` |
| G1 migrations | PASS | DB from 1d0f421 → HEAD on SQLite and Postgres 16 (56 → 64 tables) |
| G2 seeding | PASS | idempotent on a second boot |
| G3 deploy | PARTIAL | `/api/health` OK; Docker NOT RUN; DEPLOY.md 54/61 variables missing |
| H1 tabs/overflow | PASS* | 0 px overflow everywhere at 1360/400, including /physio and Admin; carried 403 console error on /data |
| H2 Trénink nav | PASS | v3 only, next to Dnes; switching updates the nav |
| H3 consistency | FAIL | carried F6 (wider), N6 |
| H4 numbers | FAIL (minor) | physio formats; carried x:60 family not re-checked in the old files |
| H5 Czech copy | PASS (S3) | double full stop; every new card has an info text |
| H6 empty/error | FAIL (carried) | old F8 (partly fixed), Trénink "Načítám…"; new-runner empty states good |
| H7 tap/contrast | FAIL (minor) | 16 px physio delete and Vydání refresh |
| I1 no diagnosis / disclaimer | FAIL (carried + new S3) | physio "riziko" with no note; F15–F17 carried; no new diagnostic wording |
| I2 evidence | FAIL (carried) | no new citations; 8 carried reference items still open |
| I3 docs current | FAIL | v0.12.17–19 and day pins undocumented |
| Watchlist | FAIL (2, carried) | pace confound; rounded ratio for points. Others PASS: replay parity, one-sided flags, decimated streams / QC unchanged, unseen surface, sandbox parity, tests don't switch seeded runners |

## Coverage gaps
- **Docker image build:** no daemon.
- **Nothing real external:** no GitHub, Railway or Garmin calls. Label timing, branch protection and the workflow labeler were checked by code only.
- **Data paths not exercised:** E2 Garmin live and the F2 S1 re-import were not re-run (code unchanged).
- **Personas:** the persona simulation and its checks were not run, so there was no 12-week false-positive run.
- **ICS feed:** end-to-end content was not checked (the plan was empty on a fresh seed for v1/v2); the pain-site note is from code.
- **Browser, not covered:** clicking through the body map (the per-muscle ibb request is from code); run detail `/app/post/:aid`; `/engine` pages; the English locale; physio write actions (claim, conclusion, programme edit).
- **Phase D:** segment streams end-to-end; pooled priors; weather; pins on a novice runner and during race rest.
- **C13 with streams:** the demo runners have no stored streams.
- **References:** Thornton 2019 full text and Frandsen 2025 primary text (the "1,6×" figure was confirmed through secondary sources only).
- **Carried S3s outside the touched areas:** not individually re-run.

## Structural drift (playbook updates proposed)
- **New roles for §4:**
  - Team Console: `backend/app/team.py`, `routers/team.py`, `frontend/src/teamconsole.tsx`; discovery `def role_of` · `merge_blockers` · `TeamMember`.
  - Physio app: `routers/physios.py`, `frontend/src/physio/`; discovery `/api/physios/me` · `_log_read`.
  - Personas: `backend/app/personas/`; discovery `sim_clock` · `is_persona_rid`.
  - Day pins: `guidance.py` "dayPins", `week_plan.py` `options` / `preview`, `routers/runners.py` `week-plan/pins`.
  - Calendar feed: `routers/calendar.py`, `i18n_static.py`.
- **C2:** document `sim_clock` as the third legal clock source (staging only) next to `today_pinned`.
- **C8:** add "a runner's day pin never overrides a no-run or reduced default, and never sizes above the unpinned `hi`".
- **F2 / F7:** add the physio app's care-assignment rule, the Team Console role model (a role must bind to an account) and "Inbox → GitHub carries no screen text".
- **F1 exemption list:** add `/api/github/webhook` (HMAC), the persona report endpoint (token) and the personas `same_origin` routes.
- **Discovery:** `def simulate(` now also matches `week_plan.py`; `fetch_details` lives in `backend/garmin_live.py`.
- **Carried from 2026-10-23:** the Dnes quadrant grid is gone (update §2); measure "shown" end-to-end as `norm ≥ 1`; run the pace probe with the runner's own pace tertiles.
