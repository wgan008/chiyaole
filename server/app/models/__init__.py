"""SQLAlchemy models — a 1:1 mapping of the DDL in docs/spec/02-data-model.md.

Two names in here carry the product's honesty and must not be "tidied up":

* `ConfirmationEvent`, not `MedicationTaken`. We know a button was pressed. We do not know
  a pill was swallowed.
* `Medication.confirmed_at IS NULL` means not in effect — enforced by a CHECK constraint in
  the database, not only in Python. A caregiver-unconfirmed medication cannot become active
  even if application code has a bug.
"""

from .base import Base
from .tables import (
    Asset,
    Caregiver,
    ConfirmationEvent,
    Dose,
    Escalation,
    LabItem,
    LabReport,
    Medication,
    Patient,
)

__all__ = [
    "Asset",
    "Base",
    "Caregiver",
    "ConfirmationEvent",
    "Dose",
    "Escalation",
    "LabItem",
    "LabReport",
    "Medication",
    "Patient",
]
