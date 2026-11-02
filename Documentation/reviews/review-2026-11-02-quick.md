# Došlap review — 2026-11-02 (quick screen)

Commit / working tree: `32834fc` ("Access and privacy fixes from the 2026-10-30 review (#6)"), `main` = `origin/main`, working tree clean, nothing uncommitted. `ENGINE_VERSION` v0.12.19 (unchanged). No engine/metrics code in this diff.

Baseline: tests **762 passed / 2 skipped / 0 failed**, 258 s on Python 3.11.17 (baseline 2026-10-30: 752/2/0, 236 s — the 9 % jump is explained by +10 tests and a Playwright browser check competing for CPU in the same container, not by this diff) · `tsc --noEmit` OK · `vite build` OK (only the known > 500 kB chunk warning) · `python -m compileall` OK. Node 22.23.4.

## Summary

Since the 2026-10-30 full review, one commit landed: a targeted fix for 6 of the 7 items on that review's "fix before the next release" list. **It is solid work** — every claim in the commit message is backed by a new, targeted test, and the full suite is green.

**Fixed, confirmed (code + passing test):**
- **N1 (S1):** Team Console roles now bind to the account (`user_id`) that opens a single-use, 7-day invitation link, not to whoever registers the e-mail first; `register()` ignores a client-supplied `provider`; merge always re-checks the password.
- **F1 (S1, carried since 2026-10-05):** a physio account reads no runner data until an owner verifies it in Tým; claiming a case is refused once taken, closed, or without the runner's consent, or after the runner has revoked the relationship.
- **F2 (S1, carried):** a Garmin/Apple re-import now merges (matches by provider+external id, else start+sport) instead of deleting every activity, day and rating first; the runner's own rating is never overwritten.
- **F3 (S1, carried):** the report's "AI notes" now gate on the runner's AI consent (`assistant.access(...)["enabled"]`), same rule as the assistant chat; demo data needs none.
- **N4 (S2):** "Send to AI team" now sends only the route *pattern* (ids replaced with `:id`) plus the owner-edited text — the clicked element's text and section heading (which could carry a client's name or pain, e.g. "Adéla Nováková · bolest 6/10") are dropped.
- **N5 (S2):** the clinical sign-off comment now names the exact head SHA it approved; a push after sign-off removes `clinical-approved` (webhook `synchronize`); `merge_blockers` and the rewritten `clinical-gate.yml` both re-check the live head against the approved SHA, and the workflow now requires the `engine`/`safety` label whenever the diff touches `backend/app/metrics/**` or the exercise libraries, regardless of what the author labelled it.
- **N6 (S2):** the physio app now shows `100 − overall` (via a shared `shownScore` helper), matching the runner's own ring, so a high-risk client no longer reads "Skóre 100".
- **Minor:** `compare_digest` now runs on bytes for the GitHub webhook and persona-token headers (a non-ASCII header was a 500).

**Not fixed — still open, unchanged by this diff:**
- **N2 (S1, from 2026-10-30) — day pins still override the illness, pain > 5 and low-readiness safety stops and still size a pinned run up to the safety ceiling.** `backend/app/metrics/guidance.py` has no changes in this diff. This was the *other* S1 on the "fix before next release" list and remains exactly as the 2026-10-30 report described it.
- **N3 (S2, from 2026-10-30) — pinning "dlouhý" for a runner with no usual long-run day still crashes every later recompute** (`guidance.py:1637`, same unguarded `WD_IN[pat['longDay']]`). Untouched.

Neither was in this commit's scope, so this is not a regression — but it means **the single most dangerous finding from the last review (a runner's own schedule choice silently overriding a fever/pain/low-readiness rest day) is still live in production.** Recommend this be the first item in the next sprint, ahead of further Team Console polish.

**New this run:** one minor doc-drift item (below). No new S1/S2/S3 code defects found in the diff.

Counts for this run (new findings only; carried items are listed separately below and are not re-counted): **S1 0 · S2 0 · S3 1 · S4 0.**

## Findings (most severe first)

### S3 — new

#### D1 CLAUDE.md's merge description no longer matches the code: it still says the password is only for "a password account"
Severity: S3 · Confidence: CONFIRMED · Area: C14 (docs = code)

Location: `CLAUDE.md` (Team Console section, "the owner types `MERGE #<n>` and, on a password account, the password") vs `backend/app/routers/team.py` `pr_merge` (`if not verify_password(body.password or "", c.user.password_hash): raise _merge_refused(...)`, no longer gated by `c.user.provider`) and `pr_review`'s `"needsPassword": True` (unconditional, was `(c.user.provider or "password") == "password"`).

What happens: the N1 fix made every account's merge confirmation require the password (closing the hole where a client-supplied `provider="google"` skipped the check), but the CLAUDE.md prose describing the merge flow wasn't updated to match — it still implies the password step is conditional on account type.

Failure scenario: none for a runner or the app's behaviour (the code is correct and stricter than before); a reader of CLAUDE.md would believe some accounts can merge without typing a password, which is no longer true.

Suggested fix: change "on a password account, the password" to "the password" in CLAUDE.md's Team Console paragraph.

Health-risk direction: none (documentation accuracy only).

## Carried — confirmed still open (not touched by this diff)

| ID | Item | Status |
|---|---|---|
| N2 (S1, 2026-10-30) | Day pins override illness / pain > 5 / low-readiness safety stops and size to the safety ceiling | STILL OPEN — `guidance.py` not in this diff |
| N3 (S2, 2026-10-30) | Pinning "dlouhý" with no usual long-run day crashes every later recompute | STILL OPEN — same file, same line (`guidance.py:1637`) |

All other S2/S3/S4 items carried from 2026-10-30 (pace confound, demo-account drift, Dnes/rail/card technique disagreement, 16 px tap targets, body-map third-party image host, etc.) are outside this diff's touched files and were not re-run this cycle — see Coverage gaps.

## Check results

| Check | Result | Note |
|---|---|---|
| Phase A baseline | PASS | tests 762/2/0 (258 s), tsc OK, build OK, compileall OK; diff since 6f4bdb9 is one commit, 35 files, +997/−150 |
| Discovery for touched roles | PASS | Team Console (`team.py`/`routers/team.py`), physio verification (`deps.py`, `routers/physios.py`, `routers/triage.py`, `routers/booking.py`), re-import (`routers/integrations.py`) all at their section-4 hints; no role moved |
| C1 mode plumbing | N/A | no engine-mode code touched |
| C2 wall clock | N/A | no engine/metrics code touched; wall-clock calls in the diff are all in routers (fine) |
| F1 CSRF, new mutating routes | PASS | all 3 new POST routes (`/members/{mid}/invite`, `/invite/accept`, `/physios/{pid}/verify`) carry `verify_csrf` |
| F2 access control, new routes | PASS | `/api/team/physios*` require `team.manage` (owner-only by `PERMS`); manually probed as a signed-in non-owner runner (adela) → 403 on both read and write; `ensure_runner_read_access` → `has_care_assignment` → `physio_verified` chain confirmed to gate `ai.py`, `conclusions.py`, `programs.py`, `rtr.py` transitively (an unverified physio can hold no `CareAssignment` since `claim()` itself requires `require_verified_physio`) |
| G1 new columns vs migration | PASS | `physios.verified_at/verified_by`, `work_items.clinical_sha`, `team_members.invite_hash/invite_expires_at/user_id` all added via the additive `add()` helper in `main.py`, with a correct backfill (physios defaulted verified; `team_members.user_id` backfilled only where the matching account predates the invite row); seed physios set `verified_at` so demo logins keep working |
| C3/C9 replay & sandbox parity | NOT RUN | not needed — no engine/metrics code changed (confirmed by diff), figures from 2026-10-30 stand |
| Guidance override tests | PARTIAL | the physio-override guidance test from 2026-10-30 (pain > 5 + referral) is unaffected by this diff; the day-pin tests this commit should have added (`test_pin_respects_illness_pain_readiness`, `test_long_run_pin_without_usual_long_day`, both suggested in the 2026-10-30 report) are **not present** — N2/N3 remain unfixed and untested |
| Null simulation (false-signal rate) | NOT RUN | scoring code unchanged since 2026-10-30; last calibration table stands (coverage gap) |
| Browser, v3 demo at 400 px | PASS | `kritickepretizeni@demo.cz` (v3), 5 tabs (today/training/load/mechanics/messages): 0 px overflow on every tab, 0 console errors |
| Regression watchlist | N/A | none of the watchlist items' code paths are touched by this diff |

## Coverage gaps
- **No engine/metrics calibration run** (null simulation, replay/sandbox parity): justified by an empty diff in `backend/app/metrics/` and `engine.py` — not a judgement call I'd make if those files had changed.
- **Browser check** covered only the prescribed one v3 demo runner at 400 px; did not re-screenshot the new invite page, Team Console → Tým (invite / physio-verify UI) or the physio queue's new Skóre direction in a live browser — those were verified by reading the code and by the new passing unit/integration tests, not independently eyeballed.
- **1360 px width** not checked (quick screen only calls for 400 px).
- **Postgres migration** not re-run for the new columns this cycle (only SQLite, via the throwaway review server); the full review on 2026-10-30 confirmed the `add()` migration helper works on both, and this diff uses the same helper.
- **Docker image build** not attempted (no daemon).
- **Nothing real external** contacted: no GitHub, Railway, Garmin, Apple or LLM calls (all keys unset).
- **All carried S2/S3/S4 items from 2026-10-30 outside this diff's files** were not individually re-run this cycle (by design — see rulebook §0 and the quick-screen scope in §10).

## Structural drift
None. No role's location changed; the new `/pozvanka/:token` route and `/api/team/invite/*`, `/api/team/physios*` endpoints fit cleanly under the existing Team Console discovery entry (`backend/app/team.py` + `routers/team.py`).
