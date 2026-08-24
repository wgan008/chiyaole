"""Tests for the elder-device pairing code flow: POST /api/patient/{id}/pairing-code
(caregiver side, setup.html) and POST /api/device/pair (device side) — the formal
replacement for HomeActivity's old hardcoded debug-only "connect test server" button."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Caregiver, Patient


def test_create_pairing_code_returns_a_six_digit_code(
    client: TestClient, patient: Patient, caregiver: Caregiver
) -> None:
    resp = client.post(f"/api/patient/{patient.id}/pairing-code?t={caregiver.access_token}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["code"]) == 6
    assert body["code"].isdigit()
    assert body["expires_at"]


def test_create_pairing_code_rejects_a_different_patient(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    other = Patient(display_name="陌生老人")
    session.add(other)
    session.flush()

    resp = client.post(f"/api/patient/{other.id}/pairing-code?t={caregiver.access_token}")
    assert resp.status_code == 403


def test_device_pair_succeeds_with_a_fresh_code(
    client: TestClient, patient: Patient, caregiver: Caregiver
) -> None:
    code = client.post(
        f"/api/patient/{patient.id}/pairing-code?t={caregiver.access_token}"
    ).json()["code"]

    resp = client.post("/api/device/pair", json={"code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["device_token"] == patient.id
    assert body["display_name"] == patient.display_name


def test_device_pair_code_is_single_use(
    client: TestClient, patient: Patient, caregiver: Caregiver
) -> None:
    code = client.post(
        f"/api/patient/{patient.id}/pairing-code?t={caregiver.access_token}"
    ).json()["code"]

    first = client.post("/api/device/pair", json={"code": code})
    assert first.status_code == 200

    second = client.post("/api/device/pair", json={"code": code})
    assert second.status_code == 404


def test_device_pair_rejects_an_expired_code(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    patient.pairing_code = "123456"
    patient.pairing_code_expires_at = datetime.now() - timedelta(minutes=1)
    session.flush()

    resp = client.post("/api/device/pair", json={"code": "123456"})
    assert resp.status_code == 404


def test_device_pair_rejects_an_unknown_code(client: TestClient) -> None:
    resp = client.post("/api/device/pair", json={"code": "000000"})
    assert resp.status_code == 404


def test_a_new_code_invalidates_the_old_one(
    client: TestClient, patient: Patient, caregiver: Caregiver
) -> None:
    old_code = client.post(
        f"/api/patient/{patient.id}/pairing-code?t={caregiver.access_token}"
    ).json()["code"]
    client.post(f"/api/patient/{patient.id}/pairing-code?t={caregiver.access_token}")

    resp = client.post("/api/device/pair", json={"code": old_code})
    assert resp.status_code == 404
