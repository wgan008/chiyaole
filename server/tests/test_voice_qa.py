"""Tests for the reinstated (escalation-free) voice Q&A routes: POST /api/asr and
POST /api/qa. See app/api/device.py's module docstring for why the escalation/reply loop
(wireframe C3->C4) is deliberately not part of this pass."""

from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent import intents, qa
from agent.llm import LLMUnavailable
from app.models import Caregiver, LabItem, LabReport, Patient


def test_asr_transcribes_uploaded_audio(
    client: TestClient, patient: Patient, monkeypatch
) -> None:
    monkeypatch.setattr("app.api.device.transcribe", lambda *a, **k: ("我今天吃药了没", 0.92))

    resp = client.post(
        "/api/asr",
        headers={"X-Device-Token": patient.id},
        files={"file": ("clip.m4a", b"fake-audio-bytes", "audio/mp4")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "我今天吃药了没"
    assert body["confidence"] == 0.92


def test_asr_reports_502_when_llm_unavailable(
    client: TestClient, patient: Patient, monkeypatch
) -> None:
    def _boom(*a: object, **k: object) -> tuple[str, float]:
        raise LLMUnavailable("no api key")

    monkeypatch.setattr("app.api.device.transcribe", _boom)

    resp = client.post(
        "/api/asr",
        headers={"X-Device-Token": patient.id},
        files={"file": ("clip.m4a", b"fake-audio-bytes", "audio/mp4")},
    )
    assert resp.status_code == 502


def test_qa_refuses_med_change_and_names_real_caregiver(
    client: TestClient, patient: Patient, caregiver: Caregiver
) -> None:
    """MED_CHANGE is caught by agent/guard.py deterministically — no LLM involved, so this
    is safe to run with no mocking at all. The refusal sentence must name the actual
    caregiver (caregiver.called_by), never agent/qa.py's "小芳" default."""
    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "这个药能不能少吃一片"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is True
    assert caregiver.called_by in body["spoken"]
    assert "小芳" not in body["spoken"] or caregiver.called_by == "小芳"
    # ★ No promise of automatic delivery — the escalation loop isn't wired up this pass.
    assert "已经" not in body["spoken"]


def test_qa_answers_a_classified_intent(
    client: TestClient, patient: Patient, monkeypatch
) -> None:
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {"intent": "med_taken_today", "slots": {}, "confidence": 0.9},
    )
    # Let phrase() fall back to its deterministic sentence rather than depending on a real
    # model call in tests (same pattern the golden-path E2E test uses for vision.ocr).
    def _no_llm(*a: object, **k: object) -> str:
        raise LLMUnavailable("no key")

    monkeypatch.setattr(qa, "complete_text", _no_llm)

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "我今天吃药了没"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "med_taken_today"
    assert body["refused"] is False
    assert body["spoken"]


# --------------------------------------------------------------------------- lab reports
# ★ Confirms 问一问 (POST /api/qa) can actually read back a confirmed lab report, not just
# that queries.py has the SQL for it — nothing exercised these intents end to end before.


def _seed_confirmed_report(
    session: Session, patient: Patient, *, report_date: date, glucose: float
) -> None:
    report = LabReport(
        patient_id=patient.id,
        report_date=report_date,
        report_type="生化全套",
        hospital="XX市第一人民医院",
        asset_ids="[]",
        confirmed_at=datetime.now(),
    )
    session.add(report)
    session.flush()
    session.add(
        LabItem(
            report_id=report.id, raw_name="空腹血糖", code="GLU",
            value=glucose, unit="mmol/L", ref_low=3.9, ref_high=6.1,
            flag="H" if glucose > 6.1 else "N",
        )
    )
    session.flush()


def _no_llm(*a: object, **k: object) -> str:
    raise LLMUnavailable("no key")


def test_qa_metric_latest_reads_a_confirmed_lab_report(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    _seed_confirmed_report(session, patient, report_date=date(2026, 8, 1), glucose=6.8)
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {
            "intent": "metric_latest", "slots": {"metric": "血糖"}, "confidence": 0.9
        },
    )
    monkeypatch.setattr(qa, "complete_text", _no_llm)

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "我血糖是多少"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "metric_latest"
    assert body["refused"] is False
    assert "6.8" in body["spoken"]


def test_qa_metric_compare_reads_two_confirmed_reports(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    _seed_confirmed_report(session, patient, report_date=date(2026, 6, 1), glucose=5.5)
    _seed_confirmed_report(session, patient, report_date=date(2026, 8, 1), glucose=6.8)
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {
            "intent": "metric_compare", "slots": {"metric": "血糖"}, "confidence": 0.9
        },
    )
    monkeypatch.setattr(qa, "complete_text", _no_llm)

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "血糖比上次高了没"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert "高了" in body["spoken"]


def test_qa_abnormal_list_reads_flagged_items_from_latest_report(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    _seed_confirmed_report(session, patient, report_date=date(2026, 8, 1), glucose=7.2)
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {"intent": "abnormal_list", "slots": {}, "confidence": 0.9},
    )
    monkeypatch.setattr(qa, "complete_text", _no_llm)

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "有哪些不正常的"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert "血糖" in body["spoken"]


def test_qa_last_report_reads_date_and_hospital(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    _seed_confirmed_report(session, patient, report_date=date(2026, 8, 1), glucose=5.9)
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {"intent": "last_report", "slots": {}, "confidence": 0.9},
    )
    monkeypatch.setattr(qa, "complete_text", _no_llm)

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "上回化验是啥时候"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert "XX市第一人民医院" in body["spoken"]


def test_qa_metric_latest_ignores_an_unconfirmed_report(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    """Mirrors delete_lab_report's own docstring: an unconfirmed report may not be quoted
    back to the elder — the caregiver hasn't reviewed it yet."""
    report = LabReport(
        patient_id=patient.id, report_date=date(2026, 8, 1), report_type="生化全套",
        hospital="XX市第一人民医院", asset_ids="[]", confirmed_at=None,
    )
    session.add(report)
    session.flush()
    session.add(
        LabItem(report_id=report.id, raw_name="空腹血糖", code="GLU", value=6.8, unit="mmol/L")
    )
    session.flush()
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {
            "intent": "metric_latest", "slots": {"metric": "血糖"}, "confidence": 0.9
        },
    )

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "我血糖是多少"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert "没有记录" in body["spoken"]


def test_qa_refuses_an_unresolved_metric_rather_than_substituting(
    client: TestClient, session: Session, patient: Patient, monkeypatch
) -> None:
    """agent/intents.py's own prohibited list: an off-whitelist metric name must refuse,
    never answer with a different metric that happens to be on record (here, 血糖)."""
    _seed_confirmed_report(session, patient, report_date=date(2026, 8, 1), glucose=5.9)
    monkeypatch.setattr(
        intents, "complete_json",
        lambda *a, **k: {
            "intent": "metric_latest", "slots": {"metric": "血脂粘稠度"}, "confidence": 0.9
        },
    )

    resp = client.post(
        "/api/qa",
        headers={"X-Device-Token": patient.id},
        json={"text": "我那个血脂粘稠度是多少"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is True
