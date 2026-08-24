from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import GUID, Base, new_uuid


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    """How TTS addresses them — 「王阿姨」. Not a legal name; what they answer to."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    pairing_code: Mapped[str | None] = mapped_column(Text, unique=True)
    """6-digit code the caregiver reads to the adult child installing the elder's APK
    (setup.html) — the formal replacement for the old debug-only 'connect test server'
    shortcut. ★ Single-use and short-lived: POST /api/device/pair clears it the moment it's
    consumed, and it stops working after `pairing_code_expires_at`. NULL when no pairing is
    currently in flight, same "unresolved is a real, expected state" spirit as everywhere
    else in this schema — never a stale code left lying around that still works."""
    pairing_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    caregivers: Mapped[list[Caregiver]] = relationship(back_populates="patient")
    medications: Mapped[list[Medication]] = relationship(back_populates="patient")


class Caregiver(Base):
    """The adult child. Exactly one per patient at POC scale."""

    __tablename__ = "caregivers"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    called_by: Mapped[str] = mapped_column(Text, nullable=False)
    """What the elder actually calls them — 「小芳」. Used verbatim in every spoken line."""
    relation: Mapped[str] = mapped_column(Text, nullable=False)  # daughter|son|spouse|other
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    """Dialled by ACTION_DIAL from the elder's phone when delivery fails. The human fallback."""
    push_token: Mapped[str | None] = mapped_column(Text)
    access_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    patient: Mapped[Patient] = relationship(back_populates="caregivers")


class Asset(Base):
    """Raw evidence — kept forever, the single arbiter of truth.

    ★ Stored BEFORE parsing, always. Without the original image there is no way to
    adjudicate a parsing error, and no way to re-run history after a model upgrade.
    """

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # medbox|lab_report|discharge|audio
    oss_key: Mapped[str] = mapped_column(Text, nullable=False)
    masked_oss_key: Mapped[str | None] = mapped_column(Text)
    """Redacted copy — name and ID number masked. Only this one is ever served."""
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Medication(Base):
    """One row = one box."""

    __tablename__ = "medications"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    generic_code: Mapped[str | None] = mapped_column(Text)
    """normalize.resolve_drug output. NULL = unresolved — never a best guess."""
    generic_name: Mapped[str] = mapped_column(Text, nullable=False)
    brand_name: Mapped[str | None] = mapped_column(Text)
    strength_value: Mapped[float | None] = mapped_column(Numeric)
    """★ High-risk field: left UNCHECKED by default in the caregiver's review UI, so
    confirming it is a deliberate act rather than an accepted default."""
    strength_unit: Mapped[str | None] = mapped_column(Text)
    dose_per_take: Mapped[float] = mapped_column(Numeric, nullable=False)
    times_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    timing_note: Mapped[str | None] = mapped_column(Text)
    """Verbatim from the box — 「饭前服用」. Transcription, never interpretation."""
    usage_raw: Mapped[str | None] = mapped_column(Text)
    explicit_times: Mapped[str | None] = mapped_column(Text)
    """JSON array of "HH:MM" strings the caregiver set directly in the confirm wizard, e.g.
    '["07:30","19:30"]'. Takes priority over deriving times from usage_raw + DailyRoutine —
    the caregiver stating "8am and 8pm" is a fact, not a guess, same status as any other
    confirmed field. NULL means the schedule is still purely text-derived."""
    photo_asset_id: Mapped[str | None] = mapped_column(GUID, ForeignKey("assets.id"))
    confirmed_by: Mapped[str | None] = mapped_column(GUID, ForeignKey("caregivers.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """★ NULL = not in effect."""
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")

    patient: Mapped[Patient] = relationship(back_populates="medications")
    doses: Mapped[list[Dose]] = relationship(back_populates="medication")

    __table_args__ = (
        # ★ Safety rule #1, enforced by the database: an unconfirmed medication cannot
        # become active even if application code has a bug.
        CheckConstraint(
            "status <> 'active' OR confirmed_at IS NOT NULL",
            name="active_requires_confirm",
        ),
    )


class Dose(Base):
    """One row per dose occurrence, generated 7 days ahead."""

    __tablename__ = "doses"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    medication_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("medications.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    # pending|confirmed|snoozed|skipped|missed

    medication: Mapped[Medication] = relationship(back_populates="doses")

    __table_args__ = (
        UniqueConstraint("medication_id", "scheduled_at", name="uq_dose_med_time"),
        Index("ix_doses_patient_time", "patient_id", "scheduled_at"),
    )


class ConfirmationEvent(Base):
    """★ Core table. Note the name: NOT medication_taken.

    We record that a large button was pressed at a time. Everything downstream — the
    caregiver's dashboard, the weekly digest, the escalations — is built on that single
    honest fact. `confidence` is computed server-side from latency and dwell, and is
    allowed to be 'unknown'.
    """

    __tablename__ = "confirmation_events"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    """★ Client-generated. POST /api/events deduplicates on it, because the device
    retries offline for up to 7 days."""
    dose_id: Mapped[str] = mapped_column(GUID, ForeignKey("doses.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # taken|snooze|skip
    skip_reason: Mapped[str | None] = mapped_column(Text)
    # away|out_of_stock|unwell|doctor_stopped|unspecified
    alarm_fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tapped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    dwell_ms: Mapped[int | None] = mapped_column(Integer)
    ring_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # alarm|notification|todo_card
    confidence: Mapped[str | None] = mapped_column(Text)  # high|low|unknown
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_events_patient_tapped", "patient_id", "tapped_at"),
    )


class LabReport(Base):
    __tablename__ = "lab_reports"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str | None] = mapped_column(Text)
    hospital: Mapped[str | None] = mapped_column(Text)
    asset_ids: Mapped[str] = mapped_column(Text, nullable=False)
    """JSON-encoded list[str] (photo pages, multi-page reports are common — spec D1f). Plain
    Text, not `ARRAY(String)`: confirmed live that a Postgres ARRAY column silently rejects a
    Python list under the SQLite dev backend this repo also supports (`sqlite3.
    ProgrammingError: type 'list' is not supported`) — same fix as Medication.explicit_times,
    application code encodes/decodes explicitly instead of relying on a dialect variant."""
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[LabItem]] = relationship(back_populates="report")


class LabItem(Base):
    __tablename__ = "lab_items"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    report_id: Mapped[str] = mapped_column(GUID, ForeignKey("lab_reports.id"), nullable=False)
    raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    """Verbatim from the printout. The arbiter when normalisation is later found wrong."""
    code: Mapped[str | None] = mapped_column(Text)
    """★ NULL = unresolved, NEVER guessed."""
    value: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(Text)
    ref_low: Mapped[float | None] = mapped_column(Numeric)
    ref_high: Mapped[float | None] = mapped_column(Numeric)
    flag: Mapped[str | None] = mapped_column(String(1))  # H|L|N

    report: Mapped[LabReport] = relationship(back_populates="items")

    __table_args__ = (Index("ix_lab_items_report_code", "report_id", "code"),)


class Escalation(Base):
    """Outbox. Must survive restarts — which is why state lives here and not in memory."""

    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(GUID, ForeignKey("patients.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 highest … 5 lowest
    utterance_raw: Mapped[str | None] = mapped_column(Text)
    """★ Verbatim. NEVER rewritten, summarised or cleaned up."""
    audio_asset_id: Mapped[str | None] = mapped_column(GUID, ForeignKey("assets.id"))
    context_json: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(Text, "sqlite")
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="OPEN")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_text: Mapped[str | None] = mapped_column(Text)
    reply_audio_id: Mapped[str | None] = mapped_column(GUID, ForeignKey("assets.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    relayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_escalations_state_retry", "state", "next_retry_at"),)
