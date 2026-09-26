"""Pydantic request bodies. Response payloads are returned as plain dicts
from route handlers (the assessment/AI-brief shapes are deeply nested and
already produced in dict form by metrics/engine.py and metrics/ai_brief.py —
re-typing them here would just be a second, drift-prone copy of the same
shape). `extra="ignore"` throughout so an evolving frontend payload doesn't
422 the whole request over one unexpected field.
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RegisterRequest(Lenient):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    role: str = "runner"
    provider: str = "password"


class LoginRequest(Lenient):
    email: EmailStr
    password: str
    expected_role: Optional[str] = None


class CheckinRequest(Lenient):
    pain_score: Optional[int] = None
    pain_site: Optional[str] = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)
    soreness: Optional[int] = None
    stress: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None
    limits_movement: Optional[bool] = None   # pain limits ordinary movement / walking
    run_modified: Optional[bool] = None      # a run was shortened or changed because of pain
    limping: Optional[bool] = None


class ExcludeActivityRequest(Lenient):
    excluded: bool = True


class RateActivityRequest(Lenient):
    feeling: Optional[int] = None
    legs: Optional[int] = None
    stiffness_pre: Optional[int] = None
    pain_during: Optional[int] = 0
    pain_site: Optional[str] = None
    niggle: Optional[bool] = False
    rpe: Optional[int] = None
    note: Optional[str] = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)


class EditDailyRequest(Lenient):
    patch: dict[str, Any]
    note: Optional[str] = None


class RunnerProfilePatch(Lenient):
    """Runner profile fields the runner may edit (engine + physio context)."""
    patch: dict[str, Any]


class InjuryReportRequest(Lenient):
    """One OSTRC-H overuse-questionnaire submission. `resolve=True` with all-
    zero answers is how a runner marks a previously reported problem as
    recovered. Each q_* is validated server-side against {0, 8, 17, 25}."""
    kind: str = "weekly"  # weekly | adhoc
    q_participation: int = 0
    q_volume: int = 0
    q_performance: int = 0
    q_pain: int = 0
    body_region: Optional[str] = None
    body_side: Optional[str] = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)
    note: Optional[str] = None
    resolve: bool = False


class BookRequest(Lenient):
    physio_id: str
    kind: str
    days_ahead: int = 2


class PhysioInterestRequest(Lenient):
    interested: bool = True


class GarminCredsRequest(Lenient):
    """The password is used only for this single Garmin Connect login and is
    never stored. When `remember` is true, the resulting OAuth *session tokens*
    (not the password) are persisted so the runner gets daily auto-sync and a
    one-tap sync without re-entering credentials."""
    email: str
    password: str
    remember: bool = False


class GarminMfaRequest(Lenient):
    mfa_token: str
    mfa_code: str
    remember: bool = False


class GarminAutoSyncRequest(Lenient):
    enabled: bool


class EngineModeRequest(Lenient):
    mode: str  # "v1" standard | "v2" sensitive | "v3" capacity


class RaceRequest(Lenient):
    date: str                           # YYYY-MM-DD
    name: Optional[str] = None
    distance_km: Optional[float] = None
    priority: str = "B"                 # A | B | C


class CycleWeekRequest(Lenient):
    pos: int | None = None  # 1–4 = this week's place in the 4-week cycle; None = automatic again


class SlotBookRequest(Lenient):
    slot_id: int
    kind: str = "assessment"
    note: Optional[str] = None


class AddSlotRequest(Lenient):
    slot_at: str
    duration_min: int = 45


class PrepInfoRequest(Lenient):
    prep_info: str


class SendMessageRequest(Lenient):
    sender: str
    body: str


class DraftProgramRequest(Lenient):
    runner_id: str
    site: Optional[str] = None


class EditExerciseRequest(Lenient):
    patch: dict[str, Any]
    note: Optional[str] = None


class AddExerciseRequest(Lenient):
    name: str
    dose: str
    per_week: int
    cue: Optional[str] = None


class SendProgramRequest(Lenient):
    note: Optional[str] = None


class AIBriefRequest(Lenient):
    runner_id: str
    intent: str = "summary"


class AiChatRequest(Lenient):
    runner_id: str
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict[str, Any]] = Field(default_factory=list)


class CreateRtrRequest(Lenient):
    """Physio starts a return-to-run ladder. Omit `levels` to use the default
    6-stage ladder. `conclusion_id` links it back to the visit it came from."""
    runner_id: str
    pain_threshold: int = 3
    sessions_per_level: int = 3
    note: Optional[str] = None
    conclusion_id: Optional[int] = None
    levels: Optional[list[dict[str, Any]]] = None


class LogRtrSessionRequest(Lenient):
    pain: int = 0
    rpe: Optional[int] = None
    completed: bool = True
    note: Optional[str] = None


class ConclusionPatch(Lenient):
    """Physio edits to a draft conclusion. OSTRC out_* values are validated
    against {0, 8, 17, 25} server-side when has_outcome is set."""
    transcript: Optional[str] = None
    summary: Optional[str] = None
    finding: Optional[str] = None
    has_outcome: Optional[bool] = None
    out_participation: Optional[int] = None
    out_volume: Optional[int] = None
    out_performance: Optional[int] = None
    out_pain: Optional[int] = None
    out_region: Optional[str] = None
    out_side: Optional[str] = None


class SettingsPatch(Lenient):
    share_with_physio: Optional[bool] = None
    share_bodymap: Optional[bool] = None
    employer_aggregate: Optional[bool] = None
    notify_drift: Optional[bool] = None
    notify_checkin: Optional[bool] = None
    rail_cards: Optional[list[str]] = None
