"""Tests for the Phase 2 additions: the caregiver web app's page routes/static assets, and
GET /api/regimen/draft (the re-fetch route the /confirm page needs on a fresh load)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, Caregiver, Medication, Patient


def test_regimen_draft_returns_current_state(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    session.add(
        Medication(
            patient_id=patient.id,
            generic_name="氨氯地平",
            dose_per_take=1.0,
            times_per_day=1,
            status="draft",
        )
    )
    session.flush()

    resp = client.get(f"/api/regimen/draft?t={caregiver.access_token}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["generic_name"] == "氨氯地平"


def test_regimen_draft_includes_photo_url(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    asset = Asset(patient_id=patient.id, kind="medbox", oss_key="p/medbox/abc.jpg", sha256="x")
    session.add(asset)
    session.flush()
    session.add(
        Medication(
            patient_id=patient.id,
            generic_name="氨氯地平",
            dose_per_take=1.0,
            times_per_day=1,
            status="draft",
            photo_asset_id=asset.id,
        )
    )
    session.flush()

    resp = client.get(f"/api/regimen/draft?t={caregiver.access_token}")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["photo_url"] is not None
    assert "abc.jpg" in item["photo_url"]


def test_delete_draft_medication_removes_it(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = Medication(
        patient_id=patient.id,
        generic_name="阿莫西林胶囊",
        dose_per_take=1.0,
        times_per_day=1,
        status="draft",
    )
    session.add(med)
    session.flush()
    med_id = med.id

    resp = client.delete(f"/api/medication/{med_id}?t={caregiver.access_token}")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_delete_active_medication_is_rejected(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    from datetime import datetime

    med = Medication(
        patient_id=patient.id,
        generic_name="阿莫西林胶囊",
        dose_per_take=1.0,
        times_per_day=1,
        status="active",
        confirmed_at=datetime.now(),
    )
    session.add(med)
    session.flush()

    resp = client.delete(f"/api/medication/{med.id}?t={caregiver.access_token}")
    assert resp.status_code == 409


def test_web_pages_render(client: TestClient, patient: Patient) -> None:
    for page in ("upload", "confirm", "lab", "dashboard", "setup", "elders"):
        resp = client.get(f"/web/{patient.id}/{page}", params={"t": "tok"})
        assert resp.status_code == 200, page
        assert "text/html" in resp.headers["content-type"]


def test_start_page_renders_with_no_patient_id(client: TestClient) -> None:
    resp = client.get("/web/start")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_web_static_assets_served(client: TestClient) -> None:
    assert client.get("/web-static/app.js").status_code == 200
    assert client.get("/web-static/style.css").status_code == 200
