"""Tests for the multi-parent flow: one caregiver registering/managing several elders.
POST /api/account/start (first elder, no existing link), POST /api/account/patients
(another elder under the same caregiver, identified by phone), GET /api/account/patients
(the "我的老人" list)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Caregiver, Patient


def test_account_start_creates_first_patient_and_caregiver(
    client: TestClient, session: Session
) -> None:
    resp = client.post(
        "/api/account/start",
        json={
            "display_name": "王阿姨", "called_by": "小芳",
            "relation": "daughter", "phone": "13900000000",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"]
    assert body["access_token"]

    patient = session.get(Patient, body["patient_id"])
    assert patient is not None
    assert patient.display_name == "王阿姨"


def test_add_patient_creates_sibling_under_same_phone(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    resp = client.post(
        f"/api/account/patients?t={caregiver.access_token}",
        json={"display_name": "李叔叔"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] != patient.id
    new_token = body["access_token"]
    assert new_token != caregiver.access_token

    # The new link works on its own, independently of the original.
    resp2 = client.get(f"/api/regimen/draft?t={new_token}")
    assert resp2.status_code == 200


def test_list_patients_returns_all_elders_sharing_phone(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    client.post(
        f"/api/account/patients?t={caregiver.access_token}", json={"display_name": "李叔叔"}
    )

    # sanity: original link still works
    resp = client.get(f"/api/lab/reports?t={caregiver.access_token}")
    assert resp.status_code == 200

    resp = client.get(f"/api/account/patients?t={caregiver.access_token}")
    assert resp.status_code == 200
    names = {p["display_name"] for p in resp.json()["patients"]}
    assert names == {"王阿姨", "李叔叔"}
    current = [p for p in resp.json()["patients"] if p["is_current"]]
    assert len(current) == 1
    assert current[0]["patient_id"] == patient.id


def test_list_patients_does_not_leak_a_different_phone_number(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    other_patient = Patient(display_name="陌生老人")
    session.add(other_patient)
    session.flush()
    session.add(
        Caregiver(
            patient_id=other_patient.id, called_by="陌生人", relation="son",
            phone="19999999999", access_token="other-token",
        )
    )
    session.flush()

    resp = client.get(f"/api/account/patients?t={caregiver.access_token}")
    names = {p["display_name"] for p in resp.json()["patients"]}
    assert "陌生老人" not in names


def test_delete_patient_removes_a_sibling_elder(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    add_resp = client.post(
        f"/api/account/patients?t={caregiver.access_token}", json={"display_name": "李叔叔"}
    )
    sibling_id = add_resp.json()["patient_id"]

    resp = client.delete(f"/api/account/patients/{sibling_id}?t={caregiver.access_token}")
    assert resp.status_code == 200
    names = {p["display_name"] for p in resp.json()["patients"]}
    assert names == {"王阿姨"}
    assert session.get(Patient, sibling_id) is None


def test_delete_patient_refuses_to_remove_the_last_elder(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    resp = client.delete(f"/api/account/patients/{patient.id}?t={caregiver.access_token}")
    assert resp.status_code == 409
    assert session.get(Patient, patient.id) is not None


def test_delete_patient_rejects_a_different_phone_number(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    other_patient = Patient(display_name="陌生老人")
    session.add(other_patient)
    session.flush()
    session.add(
        Caregiver(
            patient_id=other_patient.id, called_by="陌生人", relation="son",
            phone="19999999999", access_token="other-token",
        )
    )
    session.flush()

    resp = client.delete(f"/api/account/patients/{other_patient.id}?t={caregiver.access_token}")
    assert resp.status_code == 404
    assert session.get(Patient, other_patient.id) is not None
