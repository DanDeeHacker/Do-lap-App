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

## Phase 1 — record foundations

| Item | Code | Tests |
|---|---|---|
| R1 provider identity | `models.Clinic` legal fields, `Physio.title/qualification/hcp_identifier`; `routers/records.py` `/api/physios/me/practice`; UI `physio/practice.tsx`; approval 409 until complete | `test_records_ledger.py` |
| R2 patient card | `models.PatientRecord` (AES-GCM `*_enc`, `FIELD_ENCRYPTION_KEY`), `records.card_*`; `/api/physios/me/clients/{rid}/card`; UI Karta klienta in `physio/docs.tsx`; approval 409 without name, birth date, sex, address | `test_records_ledger.py`, `test_retention.py` |
| R3 episodes | `models.CareEpisode`, `episode_id` on bookings/programs/rtr/conclusions/injuries, `records.episode_for` (draft, programme, plan, confirmed booking, approval); `/api/episodes/{id}` edit + close → discharge record; MKN-10 table + `app/scripts/import_mkn10.py` (official ÚZIS file only) | `test_records_ledger.py` |
| R4 SOAP | `Conclusion.subjective/objective/assessment/plan/services_provided/diagnosis_*`; fields in `physio/conclusion.tsx` | |
| R5 ledger | `models.ClinicalRecord`, triggers in `main._ledger_guard` (SQLite and Postgres), `records.write_record` (canonical JSON, sha256, per-clinic chain), approval in one transaction, `app/scripts/verify_records.py`, `app/scripts/backfill_records.py` (legacy, idempotent) | `test_records_ledger.py` |
| R6 corrections | `/api/clinical-records/{id}/corrections` and `/addenda`; versions in the documentation view; corrected summary reaches the client | `test_records_corrections.py` |
| R7 activity log | `models.RecordEvent` (append-only), `app/audit.py` registry + `main.audit_access` middleware, explicit events in handlers; runner "Zobrazit detail", physio "Historie přístupů" | `test_audit_coverage.py` |
| R8 authorisation | approval records author and time; `records.sign_by` (end of the visit's local day), late approval flagged in the event; `/api/physios/me/unsigned` | |
| R9 printout | print route `/physio/client/:rid/tisk` (`docs.PrintPage`), print / handover / export events, `SigningProvider` null default | |
| R10 recording consent | required tick → `/api/bookings/{bid}/recording-consent`; audio refused without it | `test_records_ledger.py` |
| R11 retention | `records.retain_until_for`, card-level `retain_until`, `/api/physios/me/retention-due`, `/api/physios/me/destructions` → `record_destructions` (append-only, 40 years); delete trigger allows only past retention with a logged destruction; runner account deletion keeps cards and records | `test_retention.py` |
| R12 backups | `app/scripts/backup_db.py` (AES-GCM, `BACKUP_ENCRYPTION_KEY`), `app/scripts/restore_test.py` | `test_backup_restore.py` |
| R13 withdrawal | `booking.decline_physio` ends programmes and plans, logs consent; documentation stays (`records.doc_access`); runner sees what stays before confirming | `test_consent_withdrawal.py` |

**Not doable in code (owner / lawyer):** R12 EU storage separate from the database, the written retention
policy and the yearly object-locked copy; the production database decision (SQLite volume vs managed
Postgres in the EU). Provider documents from Appendix C. The MKN-10 file must be downloaded from ÚZIS by a
person and imported with the script; the running-injury shortlist needs a physio's review.

## Phase 2 — the working day

| Item | Code | Tests |
|---|---|---|
| W1 practice and roles | `models.ClinicMember`, `models.Subscription`; `work.ensure_clinic/role_of/can` (owner, admin, physio, reception); reception refused in `deps.has_care_assignment` and `records.doc_access`; `/api/physios/me/clinic`, members, `/clients/{rid}/transfer`, `PATCH /api/bookings/{bid}/payer` (default `client`); UI Praxe → Tým praxe, client card → Další | `test_working_day.py` |
| W2 invites | `models.ClientInvite` (sha256 token, 14 days, single use); `/api/physios/me/invites`, public `/api/invites/{token}`, accept starts care without the queue; client without the app (`/clients/no-app`); UI Klienti → Pozvat klienta / Klient bez aplikace, page `/pozvani/:token` | `test_working_day.py` |
| W3 Dnes | `/api/physios/me/today` (visits, requests, alerts from `work.refresh_alerts`, unsigned records, unread messages); `PATCH /api/alerts/{id}`; UI `physio/today.tsx` | `test_working_day.py` |
| W4 requests and capacity | reason, duration and red flags stored with the interest (`booking.set_interest`); `work`/`routers/work.capacity_full`; full physios get no new matches | `test_working_day.py` |
| W5 calendar | `AvailabilityRule`, `TimeOff`, `Service`; `work.free_times` in Europe/Prague (DST-safe); `/api/physios/{pid}/calendar`, `/me/visits` (weekly series, conflicts per date), private ICS feed; computed free times bookable; UI `physio/schedule.tsx` (week, add visit, working hours with preview, time off, services, ICS) | `test_working_day.py`, `test_booking.py` |
| W6 client page | five tabs (Přehled, Časová osa, Plán, Dokumentace, Zprávy, old `?tab=` redirect), sticky header from `physios._header` (diagnosis, phase, next visit, data freshness, limits), editable anamnesis, pain by place, weekly adherence | |
| W7 timeline | `/api/physios/me/clients/{rid}/timeline`; `physio/timeline.tsx` small multiples on one date axis, gaps not interpolated, table view | `test_working_day.py` (access) |
| W8 preparation | `/clients/{rid}/previsit`; `physio/visit.tsx` `PrevisitPage` | |
| W9 visit note | note templates, last note, 5 s autosave, body-map chips; `physio/visit.tsx` `VisitEditor` | |
| W10 programme builder | phases, structured dose, order, custom exercises, templates; edits are drafts, publish asks for the reason the client sees (`ProgramVersion`); runner logs pain and difficulty (`ExerciseLog`); UI `physio/plan.tsx`, runner `tabs.ExDone` | `test_program_integrity.py` |
| W11 return to running v2 | readiness gate, templates (general, Achilles, bone stress with a warning), session counts only after the next-morning answer (36 h window), controls; UI `physio/plan.tsx`, runner `care.MorningPrompt` | `test_rtr.py` |
| W12 limits | `ClinicalLimit`; `work.apply_limits` at the presentation layer (engine output unchanged, no version bump); Trénink shows who set it and why | `test_working_day.py` |
| W13 messages | inbox, handled, attachments (images ≤ 8 MB, video ≤ 50 MB, access-checked download), quick replies | |
| W14 profile and practice | capacity, response time, cancellation policy, notification settings; rating shown from 5 reviews | |
| W15 notifications | `work.Notifier` (in-app; e-mail and SMS only logged until a provider is chosen), bodies without health details; reminders once | `test_working_day.py` |
| W16 runner booking | confirmation step with service, reason, questions and the cancellation policy; intake questionnaire; visit summaries in Péče | `test_working_day.py` |
| W17 light theme | `[data-surface="physio"]` tokens in `index.css` | |

**Left for later:** a QR code for the invite (needs a library; the link can be copied or sent); e-mail and
SMS delivery (provider and contract); video in the exercise library (content).

## Phase 3 — paid product

| Item | Code | Tests |
|---|---|---|
| B1 payments and receipts | `business.PaymentProvider` with `MockProvider` only (no money moves; every screen says so); per-service deposit or full price opened at the booking request; `Invoice` numbered per clinic and year (`YYYY-NNNN`, unique index, cancelled numbers never reused), issued when a visit is marked held; packages (`Package`, `PackageUse`) pay a visit with a zero receipt; CSV for the accountant; revenue per period, per payer, outstanding. **No VAT lines** — the brief says an accountant confirms first. UI Praxe → Doklady a tržby, client Dokumentace → Balíčky, runner Péče → Čeká na vás | `test_business.py` |
| B2 seats | `business.subscription_state` (trial → active while paid → past due for 14 days → read-only); `main.read_only_practice` returns 402 on writes except sign-in, paying and the documentation (corrections, print, export); owner pays a month (mock). UI Praxe → Předplatné | `test_business.py` |
| B3 referral fee | **not built** — waits for counsel, as the brief says | |
| B4 waitlist | `Waitlist`; runner joins from Najít termín with the chosen days and parts of day; Kalendář → Pořadník lists fitting free times; an offer holds a time for 2 hours, one person at a time; a cancellation notifies the physio how many wait | `test_business.py` |
| B5 PROMs | schedule and answers (`PromSchedule`, `PromResponse`), chart in Plán → Dotazníky, runner form in Péče. Only Došlap's own short check, labelled **not validated**; VISA-A and others wait for a licence and the validated Czech version | `test_business.py` |
| B6 clinic report | occupancy, visits, no-shows, new against returning, revenue — counts and sums only; owner and admin | `test_business.py` |

## Phase 4 — moat

| Item | Code | Tests |
|---|---|---|
| M1 outcome dataset | labels from the episode the physio closes (diagnosis code, side, onset, outcome, return date) plus the runner's 3-month answer (`OutcomeFollowup`, Péče → Čeká na vás); pseudonymised export `/api/team/outcomes/export` for owners only, refused until `DOSSLAP_OUTCOME_EXPORT_BASIS` and `DOSSLAP_PSEUDO_KEY` are set; only coded diagnoses with an outcome. Complements `app/outcomes.py` (engine snapshots against self-reported events) | `test_business.py` |
| M2 recall | `moat.recall_list`: discharged, still sharing data (active consent), not back in care, with high risk or pain ≥ 3 since discharge; Dnes → Bývalí klienti s novým signálem | `test_business.py` |
| M3 video review | `VideoNote` — the physio's notes at moments of a client's video in Zprávy (reuses W13 storage); click jumps the video | `test_business.py` |
| M4 test battery | `ClinicTest`, five tests, limb symmetry index; Plán → Testy v ordinaci; the latest values are offered in W11's readiness gate | `test_business.py` |
| M5 interoperability | **not built** — the official record identifier and export format apply later; the R9 export stays the hand-over format | |

**Owner decisions before this goes live:** a payment provider and contract; VAT treatment from an accountant;
the seat price (`DOSSLAP_SEAT_PRICE_CZK`, default 690) and trial length; the legal basis for the outcome
export; licences for validated questionnaires; counsel's view on B3. The consent text should mention recall
(M2) before it is switched on for real clients.

## Round 2 (`DOSLAP_PHYSIO_BRIEF_ROUND2.md`, 10. 11. 2026)

### Phase A — data safety and one consistent answer

| Item | Code | Tests |
|---|---|---|
| F1 note editor | `frontend/src/physio/visit.tsx` (`VisitEditor` at `/physio/client/:id/visit/:bookingId`, `/navsteva/` still opens it; changed-field autosave 2 s / at most 5 s, backoff retry, `doslap:note:{bookingId}` local copy with Obnovit / Zahodit, `useBlocker` dialog, OSTRC full width), `physio/docs.tsx` `DiagnosisPicker` (Escape and outside click close only the list), `routers/conclusions.py` (`autosaved_at` on every save, `service_id` for the follow-up), `routers/work.py` `last_note` (same episode). The modal `physio/conclusion.tsx` is gone | `tests/test_note_editor_round2.py`; browser `scripts/e2e/note_editor.mjs` (+ `seed_past_visit.py`) — the five Done-when lines, 6/6 locally |
| F2 older notes into the record | `app/scripts/backfill_round2.py` (guard `migrations_applied`, `--dry-run`, cards `incomplete = 1`, one episode per pair, legacy rows through `records.write_record` with `authorised_at` and `flags`), `backfill_records.py` delegates; Dokumentace chips in `physio/docs.tsx`; Příprava section 4 `routers/work.py` `_last_record`; calendar hides Proběhla for an approved note | `tests/test_backfill_round2.py` |
| F3 one running answer | `app/care_view.py` (`rest_gap_headline`, `next_allowed_at`, `_block_running` removes running options, `apply_clinical_limits`, `guidance_physio`), `app/work.py` `limit_text`; UI `training.tsx` (Jiné možnosti, Dnešní kapacita, Plán týdne), `outlook.tsx` (Týden od pondělí), `App.tsx` (Dnes verdict), `care.tsx` (Zranění), `physio/client.tsx` (Klient dnes vidí) | `tests/test_care_directive.py` |
| F4 one pain source | `care_view.pain_events` / `pain_summary` / `last_pain`; `routers/physios.py` `_header`, `routers/work.py` `timeline` (gaps) and `previsit`; `work.alert_title`; `physio/timeline.tsx` shaded `bez dat` | `tests/test_pain_events.py` |
| F5 return to run | `routers/rtr.py` (`too_soon` whatever the pain, `pain_only`, `next_allowed_at`, morning from 06:00, `rtr_paused` notification), `work.morning_from`, `care.tsx` (Nahlásit bolest, slider captions `lib.painWord`), `physio/practice.tsx` toggle | `tests/test_rtr.py` |
| F6 programme versions | `routers/programs.py` (`total_weeks`, `published_at`, `ends_on`, `target_of`, `runner_history`, version max + 1, no-op PATCH, `/ noha` side) | `tests/test_program_integrity.py` |
| F7 one adherence | `work.program_adherence` used by Klienti, Dnes alert, Přehled, Plán, Příprava, runner Péče | `tests/test_adherence_round2.py` |
| F8 demo reset | `app/scripts/reset_demo.py` (round-2 data, rest-gap sessions, approved-before-visit notes, gender, `--recreate` demo-only), `seed.py` (client-facing reason, physio gender, valid IČO); a confirmed injury no longer writes `runner.prior_injury*` (`routers/conclusions.py`, history on close in `routers/physios.py`) | `tests/test_reset_demo.py` |

### Phase B — record polish

| Item | Code | Tests |
|---|---|---|
| F9 configuration | no variable names in the physio UI; `docs/field-encryption.md`; `records.py` previous key; `app/scripts/rotate_field_key.py`; MKN-10 bundled from ÚZIS 1. 1. 2026 (`app/data/mkn10-20260101.csv.gz`, `app/scripts/import_mkn10.py`, imported on start when empty), search by code prefix and folded text (`routers/records.py`) | `tests/test_round2_config.py` |
| F10 validation | `records.ico_valid`, `provider_name`, `missing_grouped`; `routers/physios.py` name 2–120; approval 409 `{detail, missing}`; `physio/practice.tsx`, `lib.icoValid` | `tests/test_round2_config.py`, `test_records_ledger.py` |
| F11 dates and labels | `lib.fmtDY` / `fmtDTY` in `physio/docs.tsx` and `datapage.tsx`; OSTRC `Outcome`; correction line; `doslap-record-export/1`; handover row from `detail_json`; verbs by gender (`work.verb`) | `tests/test_access_history_round2.py`, `test_access_history_labels.py` |
| F12 access history | `routers/records.py` `runner_access_events` (50 per page, cursor, `since`), `access_summary` from `record_events`; `routers/runners.py` `_access_log`; `datapage.tsx` `AccessDetail` | `tests/test_access_history_round2.py` |

### Phase C — working day

| Item | Code | Tests |
|---|---|---|
| F13 requests | `routers/booking.py` (`service_kind`, `lowest_price`, `request_detail`, per-service free times, bell title, `needs_intake`), `routers/records.py` card prefill from the intake, `physio/common.tsx` `RequestItem` (Kalendář and Dnes), `care.tsx` (service first, `od` price, intake identity) | `tests/test_booking_requests_round2.py` |
| F14 calendar grid | `physio/schedule.tsx` `WeekView` (week / day, 30-minute rows, status colours, cell menu, drag to move), `AddVisit` reset; `physio/calendar.tsx` (`Menu`, any-time move, `bez aktuálních dat`); `work.within_hours`; reschedule returns `outside_hours` | `tests/test_calendar_round2.py` |
| F15 Profil and gender | `physio/profile.tsx` (photo, title read-only, specialties, services, verification, preview, gender, title prompt), `physios.grammatical_gender`, `work.by_gender` in programme, limit and claim messages | `tests/test_profile_gender_round2.py` |
| F16 Příprava | `physio/visit.tsx` `PrevisitPage` / `PrevisitSections`, `routers/work.py` `previsit` (`runner_name`, `visit`, `running`, `rtr`) | `tests/test_pain_events.py` |
| F17 counts and header | `routers/triage.py` `queue_rows` (Fronta and Dnes), `routers/physios.py` `next_visit`, phase labels in `physio/client.tsx` | `tests/test_counts_round2.py` |
| F18 small fixes | client tabs scroll, invite `Pozvánka zrušena`, `/physio/clients/:id` redirect (`physio/app.tsx`), landing page physio text and `/auth?role=physio`, test unit once, Schůzka status once | (UI) |

### Phase D — F19 results (checked 10. 11. 2026 in the code and the test suite; nothing here touched production)

1. **Transcription.** `capabilities.asr` is `bool(ASR_API_KEY and ASR_BASE_URL)` (`app/llm.py`). `ASR_API_KEY` falls back to the model key, so production shows "Přepis zatím není zapnutý" because `ASR_BASE_URL` is not set. To switch it on, an owner sets `ASR_BASE_URL` (an OpenAI-compatible `/audio/transcriptions` endpoint) in Railway. No code change.
2. **The AI observation.** The pre-visit summary uses `llm.chat_ex` (5 s to connect, 25 s in total, one retry on a 5xx, up to 700 tokens) and a larger prompt (all facts of the client), while the runner chat uses `chat_messages` with 30 s (`LLM_TIMEOUT_S`) and up to 600 tokens. So the summary has the shorter timeout and the larger prompt; a slow answer falls back to the data-only view as designed. Changed nothing (AI code is out of scope this round). If it recurs, raising `chat_ex`'s 25 s to 30 s is the one-line option.
3. **R5 on production.** Not run here (no production access in AI sessions). Command for an owner: `railway run python -m app.scripts.verify_records` (exit 0 = intact). The UPDATE/DELETE triggers are created on every start by `main._ledger_guard` for both SQLite and Postgres; locally `verify_records` passes and `--recreate` reseeds keep it passing.
4. **R6.6.** Covered by `tests/test_records_corrections.py::test_two_corrections_and_the_original`: after a correction of `summary` the client receives the corrected text with `corrected_at` (Péče → Návštěvy shows "opraveno …"). Passes.
5. **R8.4 and W15.6.** `work.unsigned_reminders` sends at 17:00 and 21:00 local, once each (new frozen-clock test `tests/test_f19_checks.py`; it found that a second call in the same session did not see the first — fixed with a flush). The 24-hour visit reminder sets `reminded` once (`tests/test_working_day.py::test_reminder_goes_out_once`). Both pass.
6. **R13 consent withdrawal.** `tests/test_consent_withdrawal.py` runs the 403/200 matrix on a throwaway runner: after Odvolat only the documentation stays readable. Passes; nothing destructive was run on real accounts.
7. **R11 and R12.** `tests/test_retention.py` (retention from 1 January after the last service) and `tests/test_backup_restore.py` (backup, restore test, `verify_records`) pass. Daily production backups and a restore on a production copy are an owner's step on Railway.
8. **W12 runner side.** After F3 the runner's Trénink reads the same `care_view.present` payload: the weekly target becomes `min(engine, max_km_week)` and every offered run fits what is left (`tests/test_care_directive.py::test_weekly_limit_below_the_engine_target_changes_the_numbers`).
9. **Rating.** `booking._physio_public` returns `rating = None` below `RATING_MIN = 5` reviews, so the card shows `⭐ —`; the seeded 4.9 is never sent for a physio without reviews (`tests/test_f19_checks.py`). The Profil preview uses the same threshold.

**Owner steps after merge:** set `FIELD_ENCRYPTION_KEY` (docs/field-encryption.md); run `python -m app.scripts.backfill_round2 --dry-run`, then without `--dry-run` on production; optionally `ASR_BASE_URL`; on staging `ALLOW_DEMO_RESET=1 python -m app.scripts.reset_demo --recreate --apply`.
