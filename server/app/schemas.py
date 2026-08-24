"""Request/response bodies. Conventions from docs/spec/03-api.md."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# --------------------------------------------------------------------------- caregiver


class SessionOut(BaseModel):
    access_token: str
    patient_id: str


class AssetOut(BaseModel):
    asset_id: str


class ParseRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1)


class MedboxDraft(BaseModel):
    medication_id: str
    generic_name: str | None
    generic_code: str | None
    brand_name: str | None
    strength_value: float | None
    strength_unit: str | None
    usage_raw: str | None
    status: str
    """draft | active | stopped — the web UI shows a different action per status: Confirm
    or Delete for a draft, Stop for an active one, nothing for an already-stopped one."""
    photo_url: str | None = None
    """★ The caregiver must be able to check the extracted fields — especially strength,
    which starts unchecked on purpose — against the actual photo, not just trust the OCR."""
    missing: list[str] = []
    confidence: dict[str, float] = {}
    low_confidence_fields: list[str] = []
    """★ Rendered UNCHECKED in the review UI. Confirming one must be a deliberate act."""
    derived_times: list[str] | None = None
    """"HH:MM" times agent/schedule.py can work out from usage_raw + the default daily
    routine right now, as a prefill suggestion — None when the text alone is ambiguous.
    Always overridable; the caregiver's own entry (explicit_times) is what actually gets
    scheduled once confirmed."""
    explicit_times: list[str] | None = None
    """"HH:MM" times the caregiver has already set directly (see Medication.explicit_times).
    Only present once confirmed at least one time this way."""


class SafetyAlertOut(BaseModel):
    kind: str
    codes: list[str]
    message: str
    ask_doctor: str
    level: str


class RegimenDraftOut(BaseModel):
    items: list[MedboxDraft]
    alerts: list[SafetyAlertOut]
    blocked: bool
    """★ True when any alert is present: no schedule is generated until a human confirms."""


class ConfirmRequest(BaseModel):
    medication_id: str
    fields: dict[str, object] = {}
    confirmed: Literal[True]
    """Literal True on purpose — `confirmed: false` is not a thing you can send."""
    times: list[str] = []
    """"HH:MM" alarm times the caregiver set in the confirm wizard. Required to actually
    schedule anything — empty falls back to deriving from usage_raw (legacy path, kept for
    the odd case a caller doesn't go through the wizard)."""


class ScheduleUpdateRequest(BaseModel):
    times: list[str]
    """"HH:MM" — replaces the medication's schedule from today onward. At least one
    required; use POST /api/medication/{id}/stop to turn reminders off entirely."""


class PairingCodeOut(BaseModel):
    code: str
    """6 digits, read aloud by the caregiver to whoever is setting up the elder's phone."""
    expires_at: datetime


class ContactRequest(BaseModel):
    display_name: str
    called_by: str
    relation: Literal["daughter", "son", "spouse", "other"]
    phone: str


class AccountStartRequest(BaseModel):
    display_name: str
    called_by: str
    relation: Literal["daughter", "son", "spouse", "other"]
    phone: str


class AccountStartOut(BaseModel):
    patient_id: str
    access_token: str


class AddPatientRequest(BaseModel):
    display_name: str


class AccountPatientOut(BaseModel):
    patient_id: str
    display_name: str
    access_token: str
    is_current: bool


class AccountPatientsOut(BaseModel):
    patients: list[AccountPatientOut]


class DoseView(BaseModel):
    dose_id: str
    scheduled_at: datetime
    medication: str
    state: Literal["pending", "confirmed", "snoozed", "skipped", "missed"]
    confidence: Literal["high", "low", "unknown"] | None = None


class TodayOut(BaseModel):
    """The caregiver's three-state view. ★ Never two states — 'unknown' is a real answer
    and hiding it would be the lie this product exists to avoid."""

    patient_id: str
    date: date
    confirmed: list[DoseView]
    pending: list[DoseView]
    unknown: list[DoseView]


class LabItemOut(BaseModel):
    item_id: str
    raw_name: str
    """Verbatim from the printout — never replaced with a standard name (wireframe D1f)."""
    code: str | None
    """★ NULL = unresolved, never guessed (agent/normalize.resolve_lab)."""
    value: float | None
    unit: str | None
    ref_low: float | None
    ref_high: float | None
    flag: Literal["H", "L", "N"] | None
    previous_value: float | None = None
    """Same-code value from the most recent prior CONFIRMED report — the 对比 (compare)
    column, wireframe D6. None when there's no such report yet."""


class LabReportOut(BaseModel):
    report_id: str
    report_date: date
    report_type: str | None
    hospital: str | None
    confirmed: bool
    photo_urls: list[str]
    items: list[LabItemOut]


class LabReportsOut(BaseModel):
    reports: list[LabReportOut]


class LabItemEdit(BaseModel):
    item_id: str
    raw_name: str | None = None
    value: float | None = None
    unit: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    flag: Literal["H", "L", "N"] | None = None


class LabConfirmRequest(BaseModel):
    report_date: date | None = None
    report_type: str | None = None
    hospital: str | None = None
    items: list[LabItemEdit] = []
    confirmed: Literal[True]


# --------------------------------------------------------------------------- device


class DeviceRegisterRequest(BaseModel):
    patient_id: str
    device_info: dict[str, str] = {}


class DeviceRegisterOut(BaseModel):
    device_token: str
    display_name: str
    """How TTS addresses the elder — 「王阿姨」(Patient.display_name). Fetched once at
    registration and cached on-device so AlarmActivity.onCreate never needs a network call
    to know who to address (spec §3.4-③)."""


class DevicePairRequest(BaseModel):
    code: str
    """The 6-digit code shown on setup.html. Whitespace-insensitive on the server side —
    an elder-phone installer reading it back digit by digit may include a stray space."""


class ScheduleItem(BaseModel):
    dose_id: str
    medication_id: str
    scheduled_at: datetime
    generic_name: str
    dose_per_take: float
    timing_note: str | None
    photo_url: str | None
    """★ Pre-cached at enrolment. AlarmActivity.onCreate makes NO network calls."""


class ScheduleOut(BaseModel):
    items: list[ScheduleItem]
    generated_at: datetime


class EventIn(BaseModel):
    id: str
    """★ Client-generated UUID. The server deduplicates on it — the device retries offline."""
    dose_id: str
    action: Literal["taken", "snooze", "skip"]
    skip_reason: str | None = None
    alarm_fired_at: datetime
    tapped_at: datetime
    latency_ms: int
    dwell_ms: int | None = None
    ring_index: int = 1
    source: Literal["alarm", "notification", "todo_card"] = "alarm"


class EventsRequest(BaseModel):
    events: list[EventIn]


class AsrOut(BaseModel):
    text: str
    """★ Shown to the elder verbatim before the answer (wireframe C2) — lets them notice a
    mis-transcription rather than just get a confidently wrong answer."""
    confidence: float


class QaRequest(BaseModel):
    text: str


class QaOut(BaseModel):
    """No escalation_id: the escalation/caregiver-reply loop (wireframe C3→C4) is not
    wired up this pass — see agent/qa.py and agent/escalation.py's module docstrings. A
    refused question is answered with a spoken decline that tells the elder to ask their
    caregiver themselves (agent/qa.py's `_refused`), not with a promise this app will."""

    spoken: str
    intent: str
    refused: bool = False


class EventsOut(BaseModel):
    accepted: int
    duplicates: int


class DoctorViewMedication(BaseModel):
    generic_name: str
    strength_value: float | None
    strength_unit: str | None
    dose_per_take: float
    times_per_day: int
    timing_note: str | None
    """Verbatim from the box — never a fabricated instruction (product boundary #1)."""


class DoctorViewOut(BaseModel):
    """"Show the doctor": transcribe/enlarge only, never a recommendation (README red line)."""

    patient_id: str
    display_name: str
    medications: list[DoctorViewMedication]
    today: list[DoseView]
