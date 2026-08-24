"""Tests for the caregiver-set alarm times added to /api/regimen/confirm and the new
/api/medication/{id}/schedule edit route — the caregiver stating "8am and 8pm" directly,
rather than relying only on deriving times from usage_raw text (agent/schedule.py)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Caregiver, Dose, Medication, Patient


def _draft_med(session: Session, patient: Patient, **overrides: object) -> Medication:
    defaults: dict[str, object] = dict(
        patient_id=patient.id,
        generic_name="阿莫西林胶囊",
        dose_per_take=1.0,
        times_per_day=1,
        status="draft",
    )
    defaults.update(overrides)
    med = Medication(**defaults)  # type: ignore[arg-type]
    session.add(med)
    session.flush()
    return med


def test_confirm_with_explicit_times_creates_doses_at_those_times(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = _draft_med(session, patient, usage_raw="详见说明书")  # unparseable text on purpose

    resp = client.post(
        f"/api/regimen/confirm?t={caregiver.access_token}",
        json={
            "medication_id": med.id, "fields": {}, "confirmed": True,
            "times": ["07:30", "19:30"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["schedule"] == "ok"
    # 2 times/day * 7 days, minus whichever of today's two slots (if any) already passed —
    # a dose is never invented in the past.
    assert 12 <= body["doses_created"] <= 14

    doses = session.scalars(select(Dose).where(Dose.medication_id == med.id)).all()
    assert all(d.scheduled_at > datetime.now() for d in doses)
    times = sorted({d.scheduled_at.strftime("%H:%M") for d in doses})
    assert times == ["07:30", "19:30"]


def test_confirm_without_times_falls_back_to_text_derivation(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = _draft_med(session, patient, usage_raw="必要时服用")  # genuinely ambiguous (AS_NEEDED)

    resp = client.post(
        f"/api/regimen/confirm?t={caregiver.access_token}",
        json={"medication_id": med.id, "fields": {}, "confirmed": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["schedule"] == "ambiguous"
    assert body["doses_created"] == 0


def test_confirm_rejects_malformed_time(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = _draft_med(session, patient)

    resp = client.post(
        f"/api/regimen/confirm?t={caregiver.access_token}",
        json={"medication_id": med.id, "fields": {}, "confirmed": True, "times": ["not-a-time"]},
    )
    assert resp.status_code == 400


def test_update_schedule_replaces_pending_doses_including_past_ones(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    """A same-day edit must not leave today's un-acted-on dose behind as a stale duplicate
    alongside the new schedule — only real history (a state other than "pending") is
    protected, regardless of whether its time has already passed."""
    med = _draft_med(session, patient, status="active", confirmed_at=datetime.now())
    session.flush()
    answered = Dose(
        medication_id=med.id, patient_id=patient.id,
        scheduled_at=datetime.now() - timedelta(hours=1), state="confirmed",
    )
    stale_pending = Dose(
        medication_id=med.id, patient_id=patient.id,
        scheduled_at=datetime.now() - timedelta(minutes=30),
    )
    future = Dose(
        medication_id=med.id, patient_id=patient.id,
        scheduled_at=datetime.now() + timedelta(hours=1),
    )
    session.add_all([answered, stale_pending, future])
    session.flush()
    answered_id, stale_pending_id = answered.id, stale_pending.id

    resp = client.post(
        f"/api/medication/{med.id}/schedule?t={caregiver.access_token}",
        json={"times": ["08:00"]},
    )
    assert resp.status_code == 200

    doses = session.scalars(select(Dose).where(Dose.medication_id == med.id)).all()
    remaining_ids = {d.id for d in doses}
    assert answered_id in remaining_ids  # real history survives
    assert stale_pending_id not in remaining_ids  # untouched-but-overdue does not
    assert all(
        d.scheduled_at.strftime("%H:%M") == "08:00" for d in doses if d.id != answered_id
    )


def test_update_schedule_requires_active_medication(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = _draft_med(session, patient)  # still draft

    resp = client.post(
        f"/api/medication/{med.id}/schedule?t={caregiver.access_token}",
        json={"times": ["08:00"]},
    )
    assert resp.status_code == 409


def test_update_schedule_requires_at_least_one_time(
    client: TestClient, session: Session, patient: Patient, caregiver: Caregiver
) -> None:
    med = _draft_med(session, patient, status="active", confirmed_at=datetime.now())

    resp = client.post(
        f"/api/medication/{med.id}/schedule?t={caregiver.access_token}",
        json={"times": []},
    )
    assert resp.status_code == 400
