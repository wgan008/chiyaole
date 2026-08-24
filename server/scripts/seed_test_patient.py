"""Seeds one Patient + Caregiver directly in the DB for local testing.

There is no public signup route (spec: patients/caregivers are provisioned by hand during
the POC's white-glove onboarding, not self-serve) — this stands in for that step.

Usage: .venv/bin/python scripts/seed_test_patient.py
Prints the caregiver access_token and patient_id to use against the running server.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.models import Caregiver, Patient  # noqa: E402


def main() -> int:
    session = SessionLocal()
    try:
        patient = Patient(display_name="测试阿姨")
        session.add(patient)
        session.flush()

        caregiver = Caregiver(
            patient_id=patient.id,
            called_by="小明",
            relation="son",
            phone="13800000000",
            access_token=secrets.token_urlsafe(24),
        )
        session.add(caregiver)
        session.commit()

        print(f"patient_id={patient.id}")
        print(f"access_token={caregiver.access_token}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
