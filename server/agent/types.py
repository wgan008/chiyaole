"""Shared contracts.

Note two naming decisions that carry meaning:

* `ConfirmationEvent`, never `MedicationTaken`. We record that a button was pressed. We do
  not know that a pill was swallowed, and the type name must not claim that we do.
* `Ambiguous` and `Refuse` are return values, not exceptions. An unresolvable input is an
  expected, routine outcome in this system — not an error condition.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# `class X(str, Enum)` rather than 3.11's StrEnum: identical behaviour, and it keeps the
# agent modules importable on 3.10 so they can be run anywhere. The server itself targets
# 3.11 (docs/spec §2).

# --------------------------------------------------------------------------- medications


class MedStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    STOPPED = "stopped"


class Medication(BaseModel):
    """One pill box.

    `usage_raw` is transcription, never interpretation: whatever is printed on the box,
    character for character. `schedule.synthesize` is the only thing allowed to turn it
    into times, and it refuses when it cannot.
    """

    id: str | None = None
    generic_code: str | None = None
    generic_name: str | None = None
    brand_name: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    dose_per_take: float | None = None
    times_per_day: int | None = None
    usage_raw: str | None = None
    timing_note: str | None = None
    status: MedStatus = MedStatus.DRAFT
    confirmed_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Mirrors the DB constraint `active_requires_confirm` (spec §5)."""
        return self.status is MedStatus.ACTIVE and self.confirmed_at is not None


class DailyRoutine(BaseModel):
    """When this particular elder actually eats and sleeps.

    Defaults are a starting point the caregiver edits during setup. Anchoring doses to a
    real routine rather than to clock time is what makes "before meals" mean anything.
    """

    wake: time = time(6, 30)
    breakfast: time = time(7, 30)
    lunch: time = time(11, 30)
    dinner: time = time(17, 30)
    sleep: time = time(21, 30)


# --------------------------------------------------------------------------- refusals


class Ambiguous(BaseModel):
    """Returned instead of a guess. The caregiver resolves it by hand."""

    reason: str
    raw: str | None = None
    candidates: list[str] = Field(default_factory=list)


class Refuse(BaseModel):
    """Returned when a request must not be answered at all."""

    reason: Literal[
        "OUT_OF_SCOPE",
        "UNRESOLVED_ENTITY",
        "NO_DATA",
        "MED_CHANGE",
        "SYMPTOM",
    ]
    detail: str = ""
    escalate_kind: str | None = None
    urgency: int | None = None


# --------------------------------------------------------------------------- safety


class SafetyAlertKind(str, Enum):
    DUPLICATE_GENERIC = "DUPLICATE_GENERIC"
    PIM_HIT = "PIM_HIT"
    INTERACTION = "INTERACTION"


class SafetyAlert(BaseModel):
    """A blocking finding.

    ★ This never becomes advice and never reaches the elder. It blocks schedule generation
    and routes the item to the adult child, phrased as a question to put to the doctor.
    """

    kind: SafetyAlertKind
    codes: list[str]
    message: str
    ask_doctor: str = ""
    level: Literal["low", "high"] = "high"


# --------------------------------------------------------------------------- vision


class MedboxParse(BaseModel):
    generic_name: str | None = None
    brand_name: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    usage_raw: str | None = None
    manufacturer: str | None = None
    missing: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)


class LabItemParse(BaseModel):
    raw_name: str
    code: str | None = None
    value: float | None = None
    unit: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    flag: Literal["H", "L", "N"] | None = None


class LabParse(BaseModel):
    report_date: str | None = None
    report_type: str | None = None
    hospital: str | None = None
    items: list[LabItemParse] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- QA


Intent = Literal[
    "metric_latest",
    "metric_compare",
    "abnormal_list",
    "last_report",
    "med_taken_today",
    "OUT_OF_SCOPE",
]

INTENTS: tuple[str, ...] = (
    "metric_latest",
    "metric_compare",
    "abnormal_list",
    "last_report",
    "med_taken_today",
    "OUT_OF_SCOPE",
)


class IntentPayload(BaseModel):
    """Output of the classifier. `raw_slots` is unvalidated model output — resolve it
    through `resolve_slots` before it touches a query."""

    intent: Intent
    raw_slots: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0


class Slots(BaseModel):
    metric_code: str | None = None
    period: str | None = None
    n: int | None = None


class QueryResult(BaseModel):
    intent: str
    rows: list[dict[str, object]] = Field(default_factory=list)
    empty: bool = False


class QaResult(BaseModel):
    """What the device gets back from POST /api/qa."""

    spoken: str
    intent: str
    refused: bool = False
    escalation_kind: str | None = None
    urgency: int | None = None


# --------------------------------------------------------------------------- escalation


class EscalationKind(str, Enum):
    SYMPTOM = "SYMPTOM"
    MED_CHANGE = "MED_CHANGE"
    MISSED_DOSE = "MISSED_DOSE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    REGIMEN_STALE = "REGIMEN_STALE"
    UNRESOLVED_ENTITY = "UNRESOLVED_ENTITY"


class EscalationState(str, Enum):
    OPEN = "OPEN"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    ANSWERED = "ANSWERED"
    RELAYED = "RELAYED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class Escalation(BaseModel):
    id: str | None = None
    patient_id: str | None = None
    kind: EscalationKind
    urgency: int = 3
    utterance_raw: str | None = None  # ★ verbatim, never rewritten
    state: EscalationState = EscalationState.OPEN
    attempts: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None
