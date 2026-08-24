"""Route-level tests for the Phase 0 additions that remain: config, today's three-state
view, and setup/contact. (POST /api/qa and the escalation reply/relayed round trip were
built, wired end to end, and then deliberately removed — see app/api/device.py and
app/api/caregiver.py's module docstrings for why.)"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Caregiver, Dose, Medication, Patient


def test_config_returns_remote_config(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "alarm" in body
    assert "copy" in body


def test_today_three_state_bucketing(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = Medication(
        patient_id=patient.id,
        generic_name="氨氯地平",
        dose_per_take=1.0,
        times_per_day=1,
        status="active",
        confirmed_at=datetime.now(),
    )
    session.add(med)
    session.flush()

    now = datetime.now()

    def dose(offset_hours: int, state: str) -> Dose:
        return Dose(
            medication_id=med.id,
            patient_id=patient.id,
            scheduled_at=now + timedelta(hours=offset_hours),
            state=state,
        )

    session.add_all(
        [
            dose(-2, "confirmed"),
            dose(-1, "pending"),  # past-due, never confirmed -> "unknown"
            dose(2, "pending"),  # future, not due yet -> "pending"
        ]
    )
    session.flush()

    resp = client.get(f"/api/patient/{patient.id}/today?t={caregiver.access_token}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["confirmed"]) == 1
    assert len(body["unknown"]) == 1  # past-due, never confirmed
    assert len(body["pending"]) == 1  # future, not due yet


def test_setup_contact_updates_caregiver(client: TestClient, caregiver: Caregiver) -> None:
    resp = client.post(
        f"/api/setup/contact?t={caregiver.access_token}",
        json={
            "display_name": "王阿姨",
            "called_by": "小明",
            "relation": "son",
            "phone": "13900001111",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
