# Physio brief 2026-11-09 — code map and Phase 0 status

Step 0 of the brief: where each item lives in this codebase, what Phase 0 changed, and where the code
differs from what the brief assumed. Phases 1–4 are not started (Phase 1 needs the lawyer's answers in
Appendix C, Phase 3 needs payments).

## Stack (verified)

- Backend: FastAPI + SQLAlchemy, `backend/app`. Routers in `app/routers/`, models in `app/models.py`,
  additive migrations in `main._migrate` (`add(table, column, ddl, backfill)`), no Alembic.
- Frontend: React + TypeScript + Vite, `frontend/src`. Physio app in `frontend/src/physio/`, runner app in
  `App.tsx`, `care.tsx`, `tabs.tsx`, `training.tsx`, `selfprograms.tsx`.
- i18n: Czech in the code, English in `scripts/i18n/en/*.json` (Phase 0 strings: `frontend-9052.json`).
- The brief's "services area" does not exist; shared logic sits in `app/` modules.

## Phase 0 — where each item landed

| Item | Code | Tests |
|---|---|---|
| P0.1 honest AI | `llm.chat_ex` (one retry on 5xx, 25 s timeout, reason), `metrics/ai_brief.py` (`capabilities`, `consent_ok`, 1 h cache, `source`/`reason`), `physio/client.tsx` AiTab | `test_ai_fallback.py` |
| P0.2 care directive | Dnes verdict follows the directive also for v1 runners without Trénink guidance (`App.tsx` todayDay.directive); `app/care_view.py` (`resolve_care_directive`, `present`), applied in `routers/runners.py` (bootstrap, assessment, week plan, every assessment response), `routers/physios.py`, `routers/triage.py`; UI: `App.tsx` RecommendationStrip, `care.tsx`, `selfprograms.tsx`, physio Přehled "Klient dnes vidí" | `test_care_directive.py` |
| P0.3 freshness | `care_view.data_freshness` / `freshness_for` / `last_pain`; physio `_a_summary` no longer shows an unknown readiness as 100; Dnes no longer shows a missing Skóre as 100 (`App.tsx` StateOverview, the coercion the brief asked to find); engine wording fix in `metrics/guidance.py` (v0.12.23) | `test_care_directive.py` |
| P0.4 display state | `care_view.display_state`; `lib.ts` QUAD gains injury / rtr / unknown; physio `QuadChip` | `test_care_directive.py` |
| P0.5 visit record | `routers/conclusions.py`, `app/regions.py`, `physio/conclusion.tsx`, `physio/calendar.tsx`, `care.tsx`; physio close-injury endpoint in `routers/physios.py` | `test_conclusions_integrity.py`, `test_conclusions.py` |
| P0.6 booking safety | `routers/booking.py` (`overlaps`, `booking_conflict`, cancel / reschedule / complete / no-show), `main._booking_guard` (unique index), `physio/calendar.tsx` | `test_booking_safety.py` |
| P0.7 return to run | `routers/rtr.py`, `care_view.MIN_HOURS_BETWEEN_SESSIONS`, `care.tsx` RtrSheet, physio RtrTab | `test_rtr.py` |
| P0.8 programmes | `routers/programs.py` (`program_out`, `exercises_of`, `ends_on`, validation), `physio/client.tsx` ProgramTab/Library, `tabs.tsx` | `test_program_integrity.py` |
| P0.9 queue privacy | `routers/triage.py` (`_anonymous`, `release`, `pass`), `models.TriagePass`, `physio/queue.tsx`, client page "Vrátit do fronty" | `test_queue_privacy.py`, `test_triage_scope.py` |
| P0.10 security | `main.py` docs off when `RAILWAY_ENVIRONMENT_NAME=production`; message `audience` + read markers; sender from the session (it already was — the field is now ignored and optional); `crash.NotFound` | `test_messages_audience.py` |
| P0.11 bug sweep | toasts `z-[300]` (`ui.tsx`), date-only values without a time (`lib.fmtDT`), `exam` label, chat textarea that keeps text typed while sending, "nová zpráva" = unread, RTR over-limit in attention, back link with history, typo `inserční` | covered by the tests above |
| P0.12 seed + reset | `seed.py` (running_since, feminine forms for Tereza, real message times, no action on vertical-ratio drift), `tutorial_demo.py` (`shared_at`), `app/scripts/reset_demo.py` | `test_reset_demo.py` |

## Deviations and open points

- **D8 at the presentation layer.** The care directive, freshness and display state are computed on
  read (`care_view.present`) and never written to the stored assessment. History replays and the engine
  see the raw result.
- **P0.2 row 2 (clinical limit).** Waits for W12; the slot is marked in `resolve_care_directive`.
- **P0.3 "Tomáš" scenario.** Freshness counts check-ins and syncs as data, as the brief's function does,
  so a runner with fresh check-ins and no runs is "fresh". The brief's Tomáš case (0 km in 4 weeks) is
  therefore only covered if he also had no check-ins; worth a decision.
- **P0.5.9 (stop writing `prior_injury*`).** Not done: it changes the engine's input and needs the
  clinical guarantor's sign-off. The demo reset restores Adéla's prior injury instead.
- **Engine version.** v0.12.23 is wording only (the weekly-goal sentence); no scoring change.
- **P0.6 runner-side direct booking** (`POST /api/runners/{rid}/bookings`, used by older flows) does not
  run the overlap check yet; the unique index still blocks a second visit at the same start.
- **P0.10 docs switch** is read at import time from `RAILWAY_ENVIRONMENT_NAME`; the brief's
  `settings.ENV` does not exist here.
- **P0.11 not done:** `guidance_physio` third-person texts, one definition of descent (×2,15 vs ×3,5),
  merged pain history in Příznaky, mobile tab scroll-into-view, shared Czech number formatter. They need
  more than a sweep and are left for Phase 2 (W6/W7).
- **P0.12 item 3 (production test data).** The IDs in the brief refer to the production database. They
  are not hard-coded; the owner runs `ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo --extra …`
  (dry run first, `--apply` second). The script refuses any row of a non-demo account.
- **N7 body-map images** (earlier review): the image host was unreachable from the build environment.
- **Exercise library text** (`content.py`, the `inserční` typo) is an exercise library file:
  `clinical-gate` will ask for the `safety` label on the PR.

## Labels a PR from this branch needs

`engine` (guidance wording, version bump) and `safety` (what runners are told: care directive, return to
run pause, stale-data rule, programme texts) → clinical guarantor's sign-off. `security` (queue
privacy, message audience, API docs) → a `/cso` report.
