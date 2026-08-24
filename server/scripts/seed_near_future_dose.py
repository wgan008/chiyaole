"""Inserts one real Dose row, a few minutes from now, for an already-confirmed medication —
so the real photo -> parse -> confirm pipeline's output can be watched firing a real alarm
on the Android app, without re-deriving times through schedule.synthesize (already proven
correct in the full e2e run; this just needs a dose time close enough to "now" to watch).

Usage:
    .venv/bin/python scripts/seed_near_future_dose.py <medication_id> [minutes_from_now]
    .venv/bin/python scripts/seed_near_future_dose.py <medication_id> --at HH:MM
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.models import Dose, Medication  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    medication_id = argv[0]

    if len(argv) > 1 and argv[1] == "--at":
        hh, mm = (int(p) for p in argv[2].split(":"))
        when = datetime.now().astimezone().replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        minutes = int(argv[1]) if len(argv) > 1 else 3
        when = datetime.now().astimezone() + timedelta(minutes=minutes)

    session = SessionLocal()
    try:
        med = session.get(Medication, medication_id)
        if med is None:
            print(f"no such medication: {medication_id}")
            return 1
        if med.status != "active":
            print(f"medication is not active (status={med.status!r}) — confirm it first")
            return 1

        dose = Dose(medication_id=med.id, patient_id=med.patient_id, scheduled_at=when)
        session.add(dose)
        session.commit()

        print(f"{med.generic_name}: dose scheduled at {when.isoformat()} (dose_id={dose.id})")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
