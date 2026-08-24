"""Elder-device routes (spec §6.2): register, schedule, events, config, doctor-view, and a
scaled-down voice Q&A (POST /api/asr, POST /api/qa).

★ Voice Q&A was originally built with a full escalation/caregiver-reply loop (wireframe
C3→C4), then removed entirely, then reinstated WITHOUT that loop: a refused question gets a
spoken decline telling the elder to ask their caregiver themselves (agent/qa.py's
`_refused`), not a promise that this app will relay it. The wireframe doc itself argues
C3→C4 (the reply loop), not C2 (plain Q&A), is the actually valuable part — "C2 只是功能"
(C2 is just a feature) — so this is a deliberately smaller, lower-value slice of the
original design, kept intentionally simple because the full loop still runs into the same
platform constraints as before: no push channel to the elder device at all, no push channel
to the caregiver beyond a text-only PushPlus link. agent/escalation.py stays dormant.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent import loader, qa
from agent.llm import LLMUnavailable, transcribe

from ..db import get_session
from ..deps import device_patient
from ..models import Asset, Caregiver, ConfirmationEvent, Dose, Medication, Patient
from ..schemas import (
    AsrOut,
    DevicePairRequest,
    DeviceRegisterOut,
    DeviceRegisterRequest,
    DoctorViewMedication,
    DoctorViewOut,
    DoseView,
    EventsOut,
    EventsRequest,
    QaOut,
    QaRequest,
    ScheduleItem,
    ScheduleOut,
)
from ..services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["device"])


@router.post("/device/register")
def register_device(
    body: DeviceRegisterRequest, session: Session = Depends(get_session)
) -> DeviceRegisterOut:
    patient = session.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="unknown patient_id")
    # ★ POC simplification, already documented in deps.py device_patient: the device
    # token IS the patient id. Fine for a POC with one device per patient; revisit before
    # any real rollout (deps.py has the same TODO).
    return DeviceRegisterOut(device_token=patient.id, display_name=patient.display_name)


@router.post("/device/pair")
def pair_device(
    body: DevicePairRequest, session: Session = Depends(get_session)
) -> DeviceRegisterOut:
    """The formal counterpart to register_device — what a real elder-phone install calls,
    authenticated by possessing the short-lived code from setup.html rather than already
    knowing the patient_id (a caregiver never actually hands that UUID to anyone; the
    pairing code is deliberately short-lived and single-use instead of a permanent secret).
    ★ Same 'never guess' spirit as normalize.py: an expired or unrecognised code refuses
    outright — it never falls back to matching on anything looser than an exact code."""
    code = body.code.strip().replace(" ", "")
    patient = session.scalar(select(Patient).where(Patient.pairing_code == code))
    if (
        patient is None
        or patient.pairing_code_expires_at is None
        or patient.pairing_code_expires_at < datetime.now(patient.pairing_code_expires_at.tzinfo)
    ):
        raise HTTPException(status_code=404, detail="配对码无效或已过期")

    patient.pairing_code = None
    patient.pairing_code_expires_at = None
    session.flush()
    return DeviceRegisterOut(device_token=patient.id, display_name=patient.display_name)


@router.get("/schedule")
def get_schedule(
    since: datetime,
    patient: Patient = Depends(device_patient),
    session: Session = Depends(get_session),
) -> ScheduleOut:
    rows = session.execute(
        select(Dose, Medication, Asset)
        .join(Medication, Dose.medication_id == Medication.id)
        .outerjoin(Asset, Medication.photo_asset_id == Asset.id)
        .where(Dose.patient_id == patient.id, Dose.scheduled_at >= since)
        .order_by(Dose.scheduled_at)
    ).all()

    items = [
        ScheduleItem(
            dose_id=dose.id,
            medication_id=med.id,
            scheduled_at=dose.scheduled_at,
            generic_name=med.generic_name,
            dose_per_take=float(med.dose_per_take),
            timing_note=med.timing_note,
            # ★ Pre-cached URL, not the file itself — AlarmActivity downloads and caches
            # this at sync time (spec §3.4-③: no network calls once the alarm fires).
            photo_url=storage.url_for(asset.oss_key) if asset is not None else None,
        )
        for dose, med, asset in rows
    ]
    return ScheduleOut(items=items, generated_at=datetime.now())


@router.post("/events")
def post_events(
    body: EventsRequest,
    patient: Patient = Depends(device_patient),
    session: Session = Depends(get_session),
) -> EventsOut:
    accepted = 0
    duplicates = 0
    state_by_action = {"taken": "confirmed", "snooze": "snoozed", "skip": "skipped"}

    for event in body.events:
        # ★ Confirmed live: a stray non-UUID dose_id (from an on-device debug/test seed —
        # see android HomeActivity.seedTestDose) reached session.get(Dose, ...) and raised
        # an unhandled psycopg InvalidTextRepresentation, 500ing the WHOLE batch — every
        # other, legitimate event in the same sync got wedged behind it forever. One
        # malformed event must never be able to do that; skip it and keep going.
        if not _is_uuid(event.id) or not _is_uuid(event.dose_id):
            logger.warning("dropping event with non-UUID id/dose_id: %r", event)
            continue

        existing = session.get(ConfirmationEvent, event.id)
        if existing is not None:
            duplicates += 1
            continue

        dose = session.get(Dose, event.dose_id)
        if dose is None or dose.patient_id != patient.id:
            logger.warning("dropping event for unknown/foreign dose_id=%s", event.dose_id)
            continue

        session.add(
            ConfirmationEvent(
                id=event.id,
                dose_id=event.dose_id,
                patient_id=patient.id,
                action=event.action,
                skip_reason=event.skip_reason,
                alarm_fired_at=event.alarm_fired_at,
                tapped_at=event.tapped_at,
                latency_ms=event.latency_ms,
                dwell_ms=event.dwell_ms,
                ring_index=event.ring_index,
                source=event.source,
                synced_at=datetime.now(),
            )
        )
        dose.state = state_by_action[event.action]
        accepted += 1

    session.flush()
    return EventsOut(accepted=accepted, duplicates=duplicates)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@router.get("/config")
def get_config() -> JSONResponse:
    # ★ Returned verbatim, not filtered to a device-relevant subset — Android's
    # RemoteConfigStore already parses with unknown-keys-ignored, so the superset costs
    # nothing and keeps this endpoint a one-liner (net/ApiService.kt's own comment on
    # `config()` documents this contract: "the device side are a deliberate subset").
    return JSONResponse(loader.remote_config())


@router.post("/asr")
def transcribe_audio(
    file: UploadFile = File(...),
    patient: Patient = Depends(device_patient),
    session: Session = Depends(get_session),
) -> AsrOut:
    content = file.file.read()
    oss_key, sha256 = storage.save(patient.id, "audio", file.filename or "clip.m4a", content)
    asset = Asset(patient_id=patient.id, kind="audio", oss_key=oss_key, sha256=sha256)
    session.add(asset)
    session.flush()

    # ★ Biased with this patient's own drug names (agent/llm.transcribe's docstring) — an
    # elder saying 「络活喜」 in a regional accent is transcribed reliably only when the
    # decoder already knows the word is likely.
    meds = _active_medications(session, patient.id)
    bias_terms = sorted({name for m in meds for name in (m.generic_name, m.brand_name) if name})

    try:
        text, confidence = transcribe(
            f"file://{storage.local_path(asset.oss_key)}", bias_terms=bias_terms or None
        )
    except LLMUnavailable as exc:
        raise HTTPException(
            status_code=502, detail=f"couldn't hear that, try again: {exc}"
        ) from exc
    return AsrOut(text=text, confidence=confidence)


@router.post("/qa")
def ask_question(
    body: QaRequest,
    patient: Patient = Depends(device_patient),
    session: Session = Depends(get_session),
) -> QaOut:
    caregiver = session.scalar(select(Caregiver).where(Caregiver.patient_id == patient.id))
    # ★ agent/qa.answer defaults caregiver_name to "小芳" — that default must never reach a
    # real patient; every refusal sentence names whoever is actually looking after them.
    caregiver_name = caregiver.called_by if caregiver is not None else "家人"

    result = qa.answer(body.text, patient.id, session=session, caregiver_name=caregiver_name)
    return QaOut(spoken=result.spoken, intent=result.intent, refused=result.refused)


@router.get("/doctor-view/{patient_id}")
def doctor_view(
    patient_id: str,
    patient: Patient = Depends(device_patient),
    session: Session = Depends(get_session),
) -> DoctorViewOut:
    if patient_id != patient.id:
        raise HTTPException(status_code=403, detail="token does not match requested patient")

    meds = _active_medications(session, patient.id)
    day_start, day_end = _today_range()
    doses = session.execute(
        select(Dose, Medication)
        .join(Medication, Dose.medication_id == Medication.id)
        .where(
            Dose.patient_id == patient.id,
            Dose.scheduled_at >= day_start,
            Dose.scheduled_at < day_end,
        )
        .order_by(Dose.scheduled_at)
    ).all()

    return DoctorViewOut(
        patient_id=patient.id,
        display_name=patient.display_name,
        medications=[
            DoctorViewMedication(
                generic_name=m.generic_name,
                strength_value=float(m.strength_value) if m.strength_value is not None else None,
                strength_unit=m.strength_unit,
                dose_per_take=float(m.dose_per_take),
                times_per_day=m.times_per_day,
                timing_note=m.timing_note,
            )
            for m in meds
        ],
        today=[_dose_view(dose, med) for dose, med in doses],
    )


def _active_medications(session: Session, patient_id: str) -> list[Medication]:
    stmt = select(Medication).where(
        Medication.patient_id == patient_id, Medication.status == "active"
    )
    return list(session.scalars(stmt))


def _today_range() -> tuple[datetime, datetime]:
    today = datetime.now().date()
    return datetime.combine(today, time.min), datetime.combine(today, time.max)


def _dose_view(dose: Dose, med: Medication) -> DoseView:
    state = dose.state
    if state == "pending" and dose.scheduled_at < datetime.now(dose.scheduled_at.tzinfo):
        state = "missed"
    return DoseView(
        dose_id=dose.id,
        scheduled_at=dose.scheduled_at,
        medication=med.generic_name,
        state=state,  # type: ignore[arg-type]
    )
