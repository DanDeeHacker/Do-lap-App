"""ORM tables. Mirrors the shape of the in-memory `DB` object from core.js's
build(), plus auth tables (users, sessions, care_assignments, settings) that
the prototype never had.

Domain-identity tables (clinics/physios/employers/partners/runners) keep the
string ids the prototype already uses (e.g. 'run-0001') so seed data and any
existing exports/links stay stable. Everything else uses an autoincrement
integer id, matching how the prototype numbered activities/messages/etc.

Timestamps are stored as ISO-8601 strings (not native datetime columns) to
match the JS side, which always produces/consumes `new Date().toISOString()`
or plain 'YYYY-MM-DD' date strings.
"""
from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


class Clinic(Base):
    __tablename__ = "clinics"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    city = Column(String)


class Physio(Base):
    __tablename__ = "physios"
    id = Column(String, primary_key=True)
    clinic_id = Column(String, ForeignKey("clinics.id"))
    name = Column(String, nullable=False)
    credential = Column(String)
    rating = Column(Float)
    bio = Column(String)               # short description shown when a runner picks a physio
    years_exp = Column(Integer)
    specialties = Column(JSON, default=list)
    price_czk = Column(Integer)        # indicative price per session


class Employer(Base):
    __tablename__ = "employers"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    city = Column(String)
    seats = Column(Integer)
    plan = Column(String)
    contract_value_czk = Column(Integer)


class Partner(Base):
    __tablename__ = "partners"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String)
    city = Column(String)
    referral_code = Column(String)
    commission_pct = Column(Float)


class Runner(Base):
    __tablename__ = "runners"
    id = Column(String, primary_key=True)
    bib = Column(String)
    name = Column(String, nullable=False)
    birth_year = Column(Integer)
    sex = Column(String)
    city = Column(String)
    goal_race = Column(String)
    goal_date = Column(String)
    employer_id = Column(String, ForeignKey("employers.id"), index=True)
    partner_id = Column(String, ForeignKey("partners.id"), index=True)
    prior_injury = Column(String)
    prior_injury_months_ago = Column(Integer)
    prior_injury_date = Column(String)   # ISO date; months are derived from it (plan A5)
    prior_injury_side = Column(String)   # left | right | both
    hr_max = Column(Integer)             # plan C2: measured max HR (test / race); None → estimated
    device = Column(String)
    # Consent gate: a runner is invisible to physios (triage queue / candidate
    # list) until they explicitly opt into the physiotherapy service.
    physio_interest = Column(Boolean, default=False)
    physio_interest_at = Column(String)
    # Which mechanics engine scores this runner: "v1" standard (averaged) or
    # "v2" sensitive (per-run, robust noise scale) or "v3" capacity (v2 mechanics +
    # load scored against the runner's own capacity). Toggled in the app.
    engine_mode = Column(String, default="v1")
    # AI summaries & training commentary (metrics/coach_texts.py): off until the runner
    # opts in, because derived health data goes to an externally hosted model.
    coach_consent = Column(Boolean, default=False)
    coach_consent_at = Column(String)
    # Trénink: the runner's own pick of this week's place in the 4-week cycle —
    # {"week": Monday ISO, "pos": 1–4}; only applies to that calendar week.
    cycle_override = Column(JSON)


class Integration(Base):
    __tablename__ = "integrations"
    id = Column(String, primary_key=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    provider = Column(String)
    status = Column(String, default="disconnected")
    last_sync_at = Column(String)
    fields = Column(JSON, default=list)
    coverage_json = Column(JSON)


class IngestToken(Base):
    """A long-lived bearer token that lets a phone push HealthKit data to the
    runner's own history without a browser session — the closest thing to a
    Garmin-style "connect" that Apple Health allows (Apple has no cloud API, so
    the device auto-POSTs instead, e.g. via the Health Auto Export app or an
    Apple Shortcut). Scoped to one runner; revocable by rotating it."""
    __tablename__ = "ingest_tokens"
    token = Column(String, primary_key=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    provider = Column(String, default="apple")
    created_at = Column(String, nullable=False)
    last_used_at = Column(String)


class ActivityStream(Base):
    """Result of Stage S1 (Phase 4) for one activity: the compact elevation
    profile derived from the 1 Hz Garmin stream (feeds Phase 3 terrain load and,
    later, DMR 5G / ZABAGED sampling) plus quality stats. One row per activity;
    the raw per-second records are re-fetched on demand by the segmentation phase
    rather than stored, to keep the DB small."""
    __tablename__ = "activity_streams"
    activity_id = Column(Integer, ForeignKey("activities.id"), primary_key=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    external_id = Column(String, index=True)
    elevation_profile = Column(JSON)
    quality_json = Column(JSON)
    segments_json = Column(JSON)   # Phase 5 — S3 segment features for within-run scoring
    surface_json = Column(JSON)    # Phase 3b — OSM/ZABAGED surface classification of the track
    gps = Column(Boolean, default=False)
    created_at = Column(String, nullable=False)


class GarminSession(Base):
    """Persisted Garmin Connect *session tokens* (the di_token / di_refresh_token
    / di_client_id blob from garminconnect's dumps()) — deliberately NOT the
    account password, which is never stored anywhere. Lets a runner opt in to a
    daily pre-07:00 auto-sync and a one-tap "Synchronizovat" on the Dnes page
    without re-entering credentials. The blob is encrypted at rest when
    DOSSLAP_SECRET (+ the cryptography lib) is present; `encrypted` records which.

    Revocable: disconnecting deletes the row (forgetting the tokens), and the
    refresh token can additionally be revoked from the Garmin account. One row
    per runner."""
    __tablename__ = "garmin_sessions"
    runner_id = Column(String, ForeignKey("runners.id"), primary_key=True)
    token_blob = Column(String, nullable=False)   # possibly-encrypted dumps() JSON — tokens only, no password
    encrypted = Column(Boolean, default=False)
    auto_sync = Column(Boolean, default=True)
    created_at = Column(String, nullable=False)
    last_sync_at = Column(String)
    last_error = Column(String)


class DeviceHistory(Base):
    """Logged whenever a runner's watch model changes — on the demo seed's
    initial assignment and on every Garmin sync where the imported device
    differs from what's on file. Vertical-oscillation-derived values aren't
    comparable across devices, so the engine's confidence() checks this to
    flag a baseline that spans a device change."""
    __tablename__ = "device_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    device = Column(String, nullable=False)
    source = Column(String)  # 'registration' | 'garmin_sync' | 'manual'
    recorded_at = Column(String, nullable=False)


class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    provider = Column(String)
    external_id = Column(String)
    started_at = Column(String, index=True, nullable=False)
    title = Column(String)
    # "running" (default / NULL) or a cross-training sport: cycling, swimming,
    # strength, rowing, elliptical, hiking, other. Only running feeds the
    # mechanics engine; every sport feeds systemic load as running-equivalent km.
    sport = Column(String, default="running")
    distance_km = Column(Float)
    duration_min = Column(Float)
    pace_s_km = Column(Float)
    avg_hr = Column(Float)
    surface = Column(String)
    ascent_m = Column(Float)
    descent_m = Column(Float)
    temp_c = Column(Float)
    cadence_spm = Column(Float)
    stride_len_m = Column(Float)
    vert_osc_cm = Column(Float)
    vert_ratio_pct = Column(Float)
    gct_ms = Column(Float)
    gct_balance_l = Column(Float)
    vr_thirds = Column(JSON)
    hr_thirds = Column(JSON)
    pace_thirds = Column(JSON)
    # [{distance_m, altitude_m}, ...], downsampled from FIT record streams (or
    # synthesized for demo data) — real per-segment gradient, not just a
    # single average-gradient-per-run proxy. See metrics/engine.py's
    # descent_by_gradient().
    elevation_profile = Column(JSON)
    rpe = Column(Integer)
    feel_garmin = Column(Integer)
    training_load = Column(Float)
    vo2max = Column(Float)
    # Run context (Pohyb → Historie běhů). started_at stays date-only (the engine
    # compares dates as strings), so the local start time lives separately.
    # Coordinates are stored rounded to 0.01° (~1 km) — enough for weather and
    # terrain lookups without keeping a precise home location.
    start_time = Column(String)      # local "HH:MM", Europe/Prague
    start_lat = Column(Float)
    start_lon = Column(Float)
    weather_json = Column(JSON)      # metrics/weather.py summary, fetched once per run
    # the runner took it out of every calculation (feedback railway#36) — kept, not
    # deleted, so a Garmin re-sync doesn't bring it back and it can be restored
    excluded = Column(Boolean, default=False)
    excluded_at = Column(String)


class ActivityFeedback(Base):
    __tablename__ = "activity_feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), index=True, nullable=False)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    submitted_at = Column(String, nullable=False)
    feeling = Column(Integer)
    legs = Column(Integer)
    stiffness_pre = Column(Integer)  # 1 (uvolněné) - 5 (velmi ztuhlé), self-reported retrospectively at rating time
    pain_during = Column(Integer)
    pain_site = Column(String)
    niggle = Column(Boolean, default=False)
    rpe = Column(Integer)
    note = Column(String)
    pain_points = Column(JSON, default=list)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    date = Column(String, index=True, nullable=False)
    sleep_h = Column(Float)
    sleep_efficiency = Column(Float)  # v0.5 — TST / (TST + awake), 0-1
    deep_min = Column(Float)          # sleep stages from the watch (minutes) — the quality of sleep,
    rem_min = Column(Float)           # not only its length, feeds readiness (feedback railway#33)
    light_min = Column(Float)
    awake_min = Column(Float)
    hrv_ms = Column(Float)
    resting_hr = Column(Float)
    body_battery = Column(Float)
    stress_avg = Column(Float)
    steps = Column(Integer)
    source = Column(String, default="garmin")
    original_sleep_h = Column(Float)
    edited_at = Column(String)
    edit_note = Column(String)
    __table_args__ = (UniqueConstraint("runner_id", "date", name="uq_daily_runner_date"),)


class Checkin(Base):
    __tablename__ = "checkins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    submitted_at = Column(String, nullable=False)
    pain_score = Column(Integer)
    pain_site = Column(String)  # primary site (first picked) — kept for existing consumers
    pain_points = Column(JSON, default=list)  # all picked sites: [{region, side, kind}]
    soreness = Column(Integer)
    stress = Column(Integer)
    mood = Column(Integer)  # 0-4 subjective mood — NOT scored; kept to check mood↔risk correlation
    # function, not just a number (OSTRC logic, prevention plan A1): pain that limits
    # ordinary movement, a run shortened / changed because of pain, limping
    limits_movement = Column(Boolean)
    run_modified = Column(Boolean)
    limping = Column(Boolean)
    notes = Column(String)


class InjuryReport(Base):
    """v0.6 — outcome capture: the injury *label* the engine will eventually
    be calibrated against (README's largest open item — thresholds are
    auditable but unvalidated cut-points until they're checked against real
    outcomes). Scored with the OSTRC-H overuse questionnaire: four items,
    each 0/8/17/25, summed to a 0-100 severity.

    Sources, in ascending authority: 'self_weekly'/'self_adhoc' (runner-
    reported, evidence grade B) and 'physio_conclusion' (written from a
    confirmed post-visit conclusion, grade A — the main lever). A 'none'-
    status row (all-zero answers, i.e. "no problem this week") is the
    negative datapoint validation needs, not noise, so it's stored too.
    """
    __tablename__ = "injury_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    submitted_at = Column(String, nullable=False)
    source = Column(String, nullable=False)  # self_weekly | self_adhoc | physio_conclusion
    status = Column(String, default="active")  # active | resolved | none
    q_participation = Column(Integer, default=0)  # OSTRC-H items, each 0 / 8 / 17 / 25
    q_volume = Column(Integer, default=0)
    q_performance = Column(Integer, default=0)
    q_pain = Column(Integer, default=0)
    severity = Column(Integer, default=0)  # 0-100, sum of the four items
    body_region = Column(String)  # primary site (first picked) — kept for existing consumers
    body_side = Column(String)  # 'L' | 'P' | None
    pain_points = Column(JSON, default=list)  # all picked sites: [{region, side, kind}]
    note = Column(String)
    physio_id = Column(String, ForeignKey("physios.id"))  # set when source=physio_conclusion
    confirmed = Column(Boolean, default=False)  # physio-confirmed → evidence grade A
    resolved_at = Column(String)


class Assessment(Base):
    __tablename__ = "assessments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), unique=True, index=True, nullable=False)
    computed_at = Column(String)
    engine_version = Column(String)
    mech = Column(Integer)
    load = Column(Integer)
    symp = Column(Integer)
    overall = Column(Integer)
    tier = Column(String)
    quadrant = Column(String)
    confidence_json = Column(JSON)
    signals_json = Column(JSON)
    detail_json = Column(JSON)


class EngineHistoryCache(Base):
    """Cached output of the expensive engine history replay — one row per
    (runner, kind). Valid while it matches the runner's engine version and was
    computed for the current day; invalidated wholesale in
    engine.recompute_assessment whenever the runner's data changes, and rebuilt
    lazily on the next read. Turns a per-page-view O(days × full-assess) replay
    into an O(1) lookup."""
    __tablename__ = "engine_history_cache"
    runner_id = Column(String, ForeignKey("runners.id"), primary_key=True)
    kind = Column(String, primary_key=True)  # "quadrant" | "mech"
    engine_version = Column(String)
    computed_for = Column(String)  # YYYY-MM-DD the replay's pinned "today" was
    payload_json = Column(JSON)
    updated_at = Column(String)


class Triage(Base):
    __tablename__ = "triage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    decision = Column(String)
    headline = Column(String)
    status = Column(String, default="open")
    claimed_by = Column(String, ForeignKey("physios.id"))
    created_at = Column(String)


class CareAssignment(Base):
    """Created when a physio claims a triage case. The actual enforcement row
    behind "a physio may only read/write patients they've claimed"."""
    __tablename__ = "care_assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    status = Column(String, default="active")
    created_at = Column(String)


class AccessLog(Base):
    """v0.6 — GDPR transparency: who touched a runner's (health) record. Only
    *other people's* access is logged — a physio reading or writing a patient
    they've claimed — never the runner's own requests. Rows are deduped per
    (runner, physio, day, action) with a running count, so the data subject
    sees a clean "Fyzio X · 14. 8. · 5× čtení" list instead of one row per
    HTTP call. Populated by the audit middleware in main.py."""
    __tablename__ = "access_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    actor_role = Column(String, default="physio")
    action = Column(String, nullable=False)  # read | write
    date = Column(String, nullable=False)    # YYYY-MM-DD dedup bucket
    resource = Column(String)                # last path segment touched
    access_count = Column(Integer, default=1)
    first_at = Column(String)
    last_at = Column(String)
    __table_args__ = (UniqueConstraint("runner_id", "physio_id", "date", "action", name="uq_access_daily"),)


class PhysioSlot(Base):
    """A concrete availability slot a physio offers (den + čas). The runner
    browses open slots filtered by their own preferred days/parts-of-day and
    requests one; on the physio's confirmation it flips to 'booked'."""
    __tablename__ = "physio_slots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    slot_at = Column(String, index=True, nullable=False)  # ISO datetime
    duration_min = Column(Integer, default=45)
    status = Column(String, default="open")  # open | held | booked
    created_at = Column(String)


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True)
    slot_id = Column(Integer, ForeignKey("physio_slots.id"))
    slot_at = Column(String)
    kind = Column(String)
    # requested (runner asked, awaiting physio) | confirmed | declined | cancelled | confirmed-direct(legacy default)
    status = Column(String, default="confirmed")
    price_czk = Column(Integer)
    payer = Column(String)
    requested_at = Column(String)
    prep_info = Column(String)      # day-before info, managed by the physio/clinic
    reminded = Column(Boolean, default=False)
    created_at = Column(String)


class Conclusion(Base):
    """v0.6 — the post-visit conclusion tied to a booked appointment. Written
    by the physio right after the session: audio is uploaded, transcribed by
    ASR (audio then discarded — only the transcript is kept), an LLM drafts a
    narrative, the physio edits it, and *nothing is shared with the runner
    until the physio approves it* (status draft → approved). On approval, if
    the physio filled the structured OSTRC outcome, an authoritative grade-A
    InjuryReport is written (source='physio_conclusion', confirmed=True) —
    the main calibration lever for the whole engine.
    """
    __tablename__ = "conclusions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=False)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    status = Column(String, default="draft")  # draft | approved
    created_at = Column(String)
    approved_at = Column(String)
    transcript = Column(String)
    transcript_source = Column(String)  # asr | manual | None
    summary = Column(String)   # free-text conclusion / recommendation (LLM draft, physio-edited)
    finding = Column(String)   # short clinical finding / diagnosis line
    # structured OSTRC-H outcome, only when has_outcome — mirrors InjuryReport
    has_outcome = Column(Boolean, default=False)
    out_participation = Column(Integer, default=0)
    out_volume = Column(Integer, default=0)
    out_performance = Column(Integer, default=0)
    out_pain = Column(Integer, default=0)
    out_severity = Column(Integer, default=0)
    out_region = Column(String)
    out_side = Column(String)
    injury_report_id = Column(Integer, ForeignKey("injury_reports.id"))  # set on approval


class ReturnToRun(Base):
    """v0.6 — a progressive walk/run ladder the physio prescribes to a runner
    recovering from injury, closing the loop after a conclusion. The runner
    logs each session with pain; the plan advances a level only after
    `sessions_per_level` sessions completed at or below `pain_threshold`, and
    a high-pain session is a logged setback that never advances the ladder.
    `levels_json` is the ordered ladder [{level,label,run_s,walk_s,reps,...}].
    """
    __tablename__ = "return_to_run"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    conclusion_id = Column(Integer, ForeignKey("conclusions.id"))
    created_at = Column(String)
    started_on = Column(String)
    status = Column(String, default="active")  # active | completed | paused
    current_level = Column(Integer, default=1)
    pain_threshold = Column(Integer, default=3)
    sessions_per_level = Column(Integer, default=3)
    levels_json = Column(JSON, default=list)
    note = Column(String)


class RtrSession(Base):
    __tablename__ = "rtr_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("return_to_run.id"), index=True, nullable=False)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    level = Column(Integer, nullable=False)
    logged_at = Column(String)
    pain = Column(Integer, default=0)
    rpe = Column(Integer)
    completed = Column(Boolean, default=True)
    counted = Column(Boolean, default=False)  # completed AND pain <= threshold → advances the ladder
    note = Column(String)


class Program(Base):
    __tablename__ = "programs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True, nullable=False)
    name = Column(String)
    phase = Column(String)
    weeks = Column(Integer)
    started_on = Column(String)
    active = Column(Boolean, default=True)
    status = Column(String, default="draft")
    sent_at = Column(String)


class Exercise(Base):
    __tablename__ = "exercises"
    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(Integer, ForeignKey("programs.id"), index=True, nullable=False)
    name = Column(String)
    dose = Column(String)
    per_week = Column(Integer)
    cue = Column(String)
    done_count = Column(Integer, default=0)
    target_count = Column(Integer, default=12)


class ProgramRevision(Base):
    __tablename__ = "program_revisions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(Integer, ForeignKey("programs.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"))
    at = Column(String)
    note = Column(String)
    changes = Column(JSON, default=list)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    physio_id = Column(String, ForeignKey("physios.id"), index=True)
    sender = Column(String)
    body = Column(String)
    created_at = Column(String)


class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    partner_id = Column(String, ForeignKey("partners.id"), index=True, nullable=False)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    created_at = Column(String)
    status = Column(String)
    value_czk = Column(Integer)


# ---------------------------------------------------------------- auth
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # runner | physio | employer | partner
    runner_id = Column(String, ForeignKey("runners.id"))
    physio_id = Column(String, ForeignKey("physios.id"))
    employer_id = Column(String, ForeignKey("employers.id"))
    partner_id = Column(String, ForeignKey("partners.id"))
    provider = Column(String, default="password")
    created_at = Column(String)


class UserSession(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)  # random opaque token
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    expires_at = Column(String, nullable=False)
    created_at = Column(String)


class Settings(Base):
    __tablename__ = "settings"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    share_with_physio = Column(Boolean, default=True)
    share_bodymap = Column(Boolean, default=True)
    employer_aggregate = Column(Boolean, default=True)
    notify_drift = Column(Boolean, default=True)
    notify_checkin = Column(Boolean, default=True)


class Annotation(Base):
    """A feedback note pinned to a spot in the app's UI (annotation mode in the top
    bar). Anchored by route + CSS path + the element's visible text, so it can be
    re-pinned on screen and found in the code. scripts/feedback_sync.py mirrors
    these (Railway + local) for Claude Code, which implements them and marks them
    resolved."""
    __tablename__ = "annotations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    route = Column(String, nullable=False)          # e.g. /app/mechanics
    selector = Column(Text)                         # CSS path to the element
    anchor_text = Column(String)                    # the element's visible text, trimmed
    context_json = Column(JSON)                     # heading, click offset, page position, viewport, bundle
    note = Column(Text, nullable=False)
    kind = Column(String, default="idea")           # bug | idea | copy | other
    status = Column(String, default="open")         # open | done | wontfix
    resolution = Column(Text)                       # what was done about it (commit), from the sync script
    created_at = Column(String)
    updated_at = Column(String)
    resolved_at = Column(String)


class Race(Base):
    """Plan B4 — the runner's race calendar. Priority A = the goal race (taper
    before it), B = a race run hard but without a taper, C = a race run as
    training. The profile's goal_race / goal_date still work: the engine reads
    them as an A race when the calendar has nothing on that day."""
    __tablename__ = "races"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    date = Column(String, nullable=False)           # YYYY-MM-DD
    name = Column(String)
    distance_km = Column(Float)
    priority = Column(String, default="B")          # A | B | C
    created_at = Column(String)


class CoachText(Base):
    """One generated AI text — daily summary, daily training commentary or weekly
    summary (metrics/coach_texts.py). Every generation is kept with the exact facts
    it was written from, the prompt version and the validator's verdict, so prompt
    changes can be evaluated against real cases later. `text` is what the runner
    sees: the model's text when it passed validation, else the deterministic one."""
    __tablename__ = "coach_texts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runner_id = Column(String, ForeignKey("runners.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)          # daily_summary | daily_commentary | weekly_summary
    period = Column(String, nullable=False)        # the day, or the week's Monday
    facts_json = Column(JSON)
    facts_hash = Column(String)
    prompt_version = Column(String)
    model = Column(String)
    llm_text = Column(Text)                        # the model's raw output, kept even when rejected
    text = Column(Text, nullable=False)            # what is shown
    source = Column(String)                        # llm | fallback
    issues_json = Column(JSON)                     # validator findings / why the fallback was used
    cards_json = Column(JSON)                      # literature cards used (phase 2)
    latency_ms = Column(Integer)
    created_at = Column(String)
