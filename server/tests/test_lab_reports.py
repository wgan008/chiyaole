"""Tests for lab report capture/confirm (wireframe D1f/D6): POST /api/parse/lab,
GET /api/lab/reports, POST /api/lab/{id}/confirm, DELETE /api/lab/{id}."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent import vision
from app.models import Asset, Caregiver, LabItem, LabReport, Patient


def _seed_asset(session: Session, patient: Patient) -> Asset:
    asset = Asset(patient_id=patient.id, kind="lab", oss_key="p/lab/report.jpg", sha256="x")
    session.add(asset)
    session.flush()
    return asset


def test_parse_lab_creates_draft_report_with_items(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver, monkeypatch
) -> None:
    asset = _seed_asset(session, patient)
    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "report_date": "2026-08-01",
                "report_type": "生化全套",
                "hospital": "XX市第一人民医院",
                "items": [
                    {
                        "raw_name": "空腹血糖", "value": 6.1, "unit": "mmol/L",
                        "ref_low": 3.9, "ref_high": 6.1, "flag": "N",
                    },
                    {
                        "raw_name": "某未知项目", "value": 1.0, "unit": "x",
                        "ref_low": None, "ref_high": None, "flag": None,
                    },
                ],
                "confidence": {"overall": 0.9},
            }
        ),
    )

    resp = client.post(
        f"/api/parse/lab?t={caregiver.access_token}",
        json={"asset_ids": [asset.id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["reports"]) == 1
    report = body["reports"][0]
    assert report["confirmed"] is False
    assert report["report_date"] == "2026-08-01"
    assert report["hospital"] == "XX市第一人民医院"
    assert len(report["items"]) == 2
    resolved = next(i for i in report["items"] if i["raw_name"] == "空腹血糖")
    assert resolved["code"] == "GLU"
    unresolved = next(i for i in report["items"] if i["raw_name"] == "某未知项目")
    assert unresolved["code"] is None


def test_confirm_lab_report_sets_confirmed_and_enables_compare(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    old_report = LabReport(
        patient_id=patient.id, report_date=datetime(2026, 5, 12).date(),
        report_type=None, hospital=None, asset_ids="[]",
        confirmed_at=datetime.now(),
    )
    session.add(old_report)
    session.flush()
    session.add(
        LabItem(report_id=old_report.id, raw_name="血肌酐", code="CREA", value=96, unit="umol/L")
    )

    new_report = LabReport(
        patient_id=patient.id, report_date=datetime(2026, 8, 1).date(),
        report_type=None, hospital=None, asset_ids="[]",
    )
    session.add(new_report)
    session.flush()
    item = LabItem(
        report_id=new_report.id, raw_name="血肌酐", code="CREA", value=118, unit="umol/L"
    )
    session.add(item)
    session.flush()

    # Before confirming, the draft report shouldn't compare against anything yet — the
    # query filters on the OLD report already being confirmed, not the new one.
    resp = client.get(f"/api/lab/reports?t={caregiver.access_token}")
    draft = next(r for r in resp.json()["reports"] if r["report_id"] == new_report.id)
    assert draft["items"][0]["previous_value"] == 96.0

    resp = client.post(
        f"/api/lab/{new_report.id}/confirm?t={caregiver.access_token}",
        json={"confirmed": True, "items": []},
    )
    assert resp.status_code == 200
    confirmed = next(r for r in resp.json()["reports"] if r["report_id"] == new_report.id)
    assert confirmed["confirmed"] is True
    assert confirmed["items"][0]["value"] == 118.0
    assert confirmed["items"][0]["previous_value"] == 96.0


def test_confirm_lab_report_applies_item_edits(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    report = LabReport(
        patient_id=patient.id, report_date=datetime(2026, 8, 1).date(),
        report_type=None, hospital=None, asset_ids="[]",
    )
    session.add(report)
    session.flush()
    item = LabItem(report_id=report.id, raw_name="血肌酐", code="CREA", value=118, unit="umol/L")
    session.add(item)
    session.flush()
    item_id = item.id

    resp = client.post(
        f"/api/lab/{report.id}/confirm?t={caregiver.access_token}",
        json={"confirmed": True, "items": [{"item_id": item_id, "value": 120.5}]},
    )
    assert resp.status_code == 200
    out = next(r for r in resp.json()["reports"] if r["report_id"] == report.id)
    assert out["items"][0]["value"] == 120.5


def test_delete_draft_lab_report_removes_it(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    report = LabReport(
        patient_id=patient.id, report_date=datetime(2026, 8, 1).date(),
        report_type=None, hospital=None, asset_ids="[]",
    )
    session.add(report)
    session.flush()
    session.add(
        LabItem(report_id=report.id, raw_name="血肌酐", code="CREA", value=118, unit="umol/L")
    )
    session.flush()

    resp = client.delete(f"/api/lab/{report.id}?t={caregiver.access_token}")
    assert resp.status_code == 200
    assert resp.json()["reports"] == []


def test_delete_confirmed_lab_report_is_rejected(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    report = LabReport(
        patient_id=patient.id, report_date=datetime(2026, 8, 1).date(),
        report_type=None, hospital=None, asset_ids="[]",
        confirmed_at=datetime.now(),
    )
    session.add(report)
    session.flush()

    resp = client.delete(f"/api/lab/{report.id}?t={caregiver.access_token}")
    assert resp.status_code == 409
