"""Caregiver-facing routes (spec §6.1): session, asset upload, medbox parsing, confirmation,
lab report parsing/confirmation, today's three-state view, and contact setup. Weekly digest
is not built yet (not on the golden E2E path).

★ The escalation inbox + reply (spec §6.1's GET /api/escalations, POST /api/escalations/
{id}/reply) was built, wired end to end, and then deliberately removed: it duplicated
WeChat's own instant messaging and couldn't realistically replace it given the platform
constraints (no push channel to either party beyond a text-only PushPlus link). agent/
escalation.py is left in place, dormant, in case a future channel makes it worth reviving."""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from agent import normalize, safety, schedule
from agent.llm import LLMUnavailable
from agent.types import Ambiguous, DailyRoutine
from agent.types import Medication as MedicationPy
from agent.vision import parse_lab, parse_medbox

from ..db import get_session
from ..deps import caregiver_from_token
from ..models import (
    Asset,
    Caregiver,
    ConfirmationEvent,
    Dose,
    Escalation,
    LabItem,
    LabReport,
    Medication,
    Patient,
)
from ..schemas import (
    AccountPatientOut,
    AccountPatientsOut,
    AccountStartOut,
    AccountStartRequest,
    AddPatientRequest,
    AssetOut,
    ConfirmRequest,
    ContactRequest,
    DoseView,
    LabConfirmRequest,
    LabItemOut,
    LabReportOut,
    LabReportsOut,
    MedboxDraft,
    PairingCodeOut,
    ParseRequest,
    RegimenDraftOut,
    SafetyAlertOut,
    ScheduleUpdateRequest,
    SessionOut,
    TodayOut,
)
from ..services import storage

# ★ Every server process/container in this deployment runs in UTC (confirmed live: both
# app and postgres containers report `date` as UTC, and nothing in docker-compose.yml sets
# TZ) — a bare `datetime.now()` is UTC wall-clock time, not China's. Confirmed live a
# second time: a caregiver picking "18:08" in the confirm wizard, meaning 18:08 Beijing
# time, got stored as `18:08+00` (UTC) and rendered back as 02:08 the next day in China —
# every dose time and every "what day is today" boundary in this file must use this
# explicitly, never a naive datetime.now()/date.today().
CHINA_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter(prefix="/api", tags=["caregiver"])


@router.post("/session")
def create_session(caregiver: Caregiver = Depends(caregiver_from_token)) -> SessionOut:
    return SessionOut(access_token=caregiver.access_token, patient_id=caregiver.patient_id)


@router.post("/assets")
def upload_asset(
    kind: str = Form(...),
    file: UploadFile = File(...),
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> AssetOut:
    content = file.file.read()
    oss_key, sha256 = storage.save(caregiver.patient_id, kind, file.filename or "upload", content)

    asset = Asset(
        patient_id=caregiver.patient_id,
        kind=kind,
        oss_key=oss_key,
        sha256=sha256,
    )
    session.add(asset)
    session.flush()
    return AssetOut(asset_id=asset.id)


def _parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid time: {value!r}, expected HH:MM") from exc


def _generate_doses(
    med: Medication, patient_id: str, times: list[time], session: Session, *, days: int = 7
) -> int:
    created = 0
    now = datetime.now(CHINA_TZ)
    start = now.date()
    for offset in range(days):
        day = start + timedelta(days=offset)
        for t in times:
            when = datetime.combine(day, t, tzinfo=CHINA_TZ)
            if when <= now:
                # Never invent a dose in the past — today's slots earlier than "right now"
                # (e.g. the caregiver edits the schedule mid-afternoon) simply start
                # tomorrow instead of showing up as instantly overdue.
                continue
            exists = session.scalar(
                select(Dose).where(Dose.medication_id == med.id, Dose.scheduled_at == when)
            )
            if exists is not None:
                continue
            session.add(Dose(medication_id=med.id, patient_id=patient_id, scheduled_at=when))
            created += 1
    session.flush()
    return created


def _to_medbox_draft(med: Medication, photo_url: str | None) -> MedboxDraft:
    missing = [
        f for f in ("generic_name", "strength_value", "usage_raw")
        if getattr(med, f) in (None, "")
    ]
    derived_times = None
    if med.status == "draft":
        preview = schedule.synthesize(_to_pydantic(med), DailyRoutine())
        if not isinstance(preview, Ambiguous):
            derived_times = sorted({t.strftime("%H:%M") for t in preview})
    return MedboxDraft(
        medication_id=med.id,
        generic_name=med.generic_name,
        generic_code=med.generic_code,
        brand_name=med.brand_name,
        strength_value=med.strength_value,
        strength_unit=med.strength_unit,
        usage_raw=med.usage_raw,
        status=med.status,
        photo_url=photo_url,
        missing=missing,
        derived_times=derived_times,
        explicit_times=json.loads(med.explicit_times) if med.explicit_times else None,
    )


def _regimen_state(patient_id: str, session: Session) -> RegimenDraftOut:
    """Recomputed on every parse/confirm — safety.check runs across the WHOLE regimen
    (spec: duplicate-generic screening needs every box in the household, not just the one
    just added)."""
    rows = session.execute(
        select(Medication, Asset)
        .outerjoin(Asset, Medication.photo_asset_id == Asset.id)
        .where(Medication.patient_id == patient_id)
    ).all()
    meds = [m for m, _ in rows]
    py_meds = [_to_pydantic(m) for m in meds]
    alerts = safety.check(py_meds)
    return RegimenDraftOut(
        items=[
            _to_medbox_draft(m, storage.url_for(asset.oss_key) if asset is not None else None)
            for m, asset in rows
        ],
        alerts=[
            SafetyAlertOut(
                kind=a.kind.value, codes=a.codes, message=a.message,
                ask_doctor=a.ask_doctor, level=a.level,
            )
            for a in alerts
        ],
        blocked=safety.blocks_activation(alerts),
    )


def _to_pydantic(med: Medication) -> MedicationPy:
    return MedicationPy(
        id=med.id,
        generic_code=med.generic_code,
        generic_name=med.generic_name,
        brand_name=med.brand_name,
        strength_value=float(med.strength_value) if med.strength_value is not None else None,
        strength_unit=med.strength_unit,
        dose_per_take=float(med.dose_per_take),
        times_per_day=med.times_per_day,
        usage_raw=med.usage_raw,
        timing_note=med.timing_note,
        status=med.status,  # type: ignore[arg-type]
        confirmed_at=med.confirmed_at,
    )


@router.get("/regimen/draft")
def regimen_draft(
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> RegimenDraftOut:
    """Re-fetches the current draft state (the web app's /confirm page needs this on a
    fresh page load — parse/medbox and regimen/confirm only return it inline as a
    side-effect of a write)."""
    return _regimen_state(caregiver.patient_id, session)


@router.post("/parse/medbox")
def parse_medbox_route(
    body: ParseRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> RegimenDraftOut:
    assets = list(
        session.scalars(
            select(Asset).where(
                Asset.id.in_(body.asset_ids), Asset.patient_id == caregiver.patient_id
            )
        )
    )
    if len(assets) != len(body.asset_ids):
        raise HTTPException(
            status_code=404, detail="one or more asset_ids not found for this patient"
        )

    # ★ Local-disk mode: file:// paths, not storage.url_for() — the vision call runs ON
    # this machine and can resolve/upload local files itself (confirmed live,
    # scripts/test_vision.py); a storage.url_for() http://localhost URL would not be
    # reachable from DashScope's side. Real OSS: url_for() IS a real, DashScope-reachable
    # signed URL, so no local file:// trick is needed at all.
    if storage.is_local():
        image_urls = [f"file://{storage.local_path(a.oss_key)}" for a in assets]
    else:
        image_urls = [storage.url_for(a.oss_key) for a in assets]

    try:
        parsed = parse_medbox(image_urls)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"couldn't read it, try again: {exc}") from exc

    generic_code = normalize.resolve_drug(parsed.generic_name or parsed.brand_name or "")
    times_per_day = schedule._frequency_from_text(parsed.usage_raw or "") or 1

    med = Medication(
        patient_id=caregiver.patient_id,
        generic_code=generic_code,
        # ★ NOT NULL in the DB; vision can legitimately fail to read it. "(未识别)" is a
        # placeholder that keeps the row insertable — the caregiver corrects it via
        # ConfirmRequest.fields before confirming, same as any other low-confidence field.
        generic_name=parsed.generic_name or parsed.brand_name or "(未识别)",
        brand_name=parsed.brand_name,
        strength_value=parsed.strength_value,
        strength_unit=parsed.strength_unit,
        dose_per_take=1.0,  # placeholder pending caregiver confirmation
        times_per_day=times_per_day,  # best-effort from usage_raw; caregiver can override
        usage_raw=parsed.usage_raw,
        photo_asset_id=assets[0].id,
        status="draft",
    )
    session.add(med)
    session.flush()

    return _regimen_state(caregiver.patient_id, session)



@router.post("/regimen/confirm")
def confirm_medication(
    body: ConfirmRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    med = session.get(Medication, body.medication_id)
    if med is None or med.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="medication not found")

    _EDITABLE = {
        "generic_name", "brand_name", "strength_value", "strength_unit",
        "dose_per_take", "times_per_day", "usage_raw", "timing_note",
    }
    for key, value in body.fields.items():
        if key in _EDITABLE:
            setattr(med, key, value)
    session.flush()

    regimen = _regimen_state(caregiver.patient_id, session)
    if regimen.blocked:
        # ★ Red line #2: never auto-activate. The alert stays visible; nothing here
        # changes `status` or `confirmed_at`.
        return {"status": "blocked", "alerts": [a.model_dump() for a in regimen.alerts]}

    med.status = "active"
    med.confirmed_by = caregiver.id
    med.confirmed_at = datetime.now(CHINA_TZ)

    if body.times:
        # ★ The caregiver typing "8am and 8pm" into the wizard is a stated fact, not a
        # guess — it takes priority over (and no longer needs) deriving times from
        # usage_raw text, and works even when that text is genuinely unparseable.
        try:
            parsed_times = [_parse_hhmm(t) for t in body.times]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        med.explicit_times = json.dumps(body.times)
        session.flush()
        created = _generate_doses(med, caregiver.patient_id, parsed_times, session)
        return {"status": "active", "schedule": "ok", "doses_created": created}

    session.flush()

    # Legacy fallback for any caller that doesn't go through the wizard's time picker.
    routine = DailyRoutine()
    result = schedule.synthesize_days(_to_pydantic(med), routine)

    if isinstance(result, Ambiguous):
        return {
            "status": "active",
            "schedule": "ambiguous",
            "ambiguous_reason": result.reason,
            "doses_created": 0,
        }

    created = 0
    for when in result:
        exists = session.scalar(
            select(Dose).where(Dose.medication_id == med.id, Dose.scheduled_at == when)
        )
        if exists is not None:
            continue
        session.add(Dose(medication_id=med.id, patient_id=caregiver.patient_id, scheduled_at=when))
        created += 1
    session.flush()

    return {"status": "active", "schedule": "ok", "doses_created": created}


@router.post("/medication/{medication_id}/schedule")
def update_medication_schedule(
    medication_id: str,
    body: ScheduleUpdateRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> RegimenDraftOut:
    """Lets the caregiver change an already-active medication's alarm times later — the
    counterpart to setting them the first time in the confirm wizard. Mirrors
    stop_active_medication's pattern, but keyed on `state`, not `scheduled_at`: any
    still-`pending` dose reflects the OLD schedule and gets dropped, even if its time
    already passed today (nothing was actually recorded for it — a caregiver editing at
    3pm means the 9am slot the elder never acted on shouldn't linger as a second, stale
    entry alongside the new one). A `confirmed`/`snoozed`/`skipped`/`missed` dose is real
    history and is never touched, past or future."""
    med = session.get(Medication, medication_id)
    if med is None or med.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="medication not found")
    if med.status != "active":
        raise HTTPException(
            status_code=409, detail="only an active medication has a schedule to edit"
        )
    if not body.times:
        raise HTTPException(status_code=400, detail="at least one time is required")

    try:
        parsed_times = [_parse_hhmm(t) for t in body.times]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.execute(
        delete(Dose).where(Dose.medication_id == med.id, Dose.state == "pending")
    )
    med.explicit_times = json.dumps(body.times)
    session.flush()
    _generate_doses(med, caregiver.patient_id, parsed_times, session)
    return _regimen_state(caregiver.patient_id, session)


@router.delete("/medication/{medication_id}")
def delete_draft_medication(
    medication_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> RegimenDraftOut:
    """Discards a mistaken/duplicate draft entry from the confirm screen — e.g. the same
    box photographed and parsed twice. ★ Scoped to `status == 'draft'` only: an already-
    confirmed medication has real Dose/ConfirmationEvent history hanging off it (no FK
    cascade is configured on purpose, matching the "assets/history are never destroyed"
    rule elsewhere in this schema) — undoing an active medication is a bigger, different
    operation than discarding a draft and isn't handled here."""
    med = session.get(Medication, medication_id)
    if med is None or med.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="medication not found")
    if med.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="only a draft (unconfirmed) medication can be deleted this way",
        )

    session.delete(med)
    session.flush()
    return _regimen_state(caregiver.patient_id, session)


@router.post("/medication/{medication_id}/stop")
def stop_active_medication(
    medication_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> RegimenDraftOut:
    """The counterpart to delete for an already-confirmed medication: a hard delete would
    destroy real Dose/ConfirmationEvent history, which this schema never does (assets are
    kept forever for the same reason). Stopping instead — MedStatus already had a `stopped`
    value that nothing wired up — preserves everything already recorded and only removes
    still-`pending` doses (never a `confirmed`/`snoozed`/`skipped`/`missed` one, whatever
    its time) so the alarm stops ringing for a medication that's been stopped — including
    today's own dose if the elder hasn't acted on it yet, not just future days'."""
    med = session.get(Medication, medication_id)
    if med is None or med.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="medication not found")
    if med.status != "active":
        raise HTTPException(status_code=409, detail="only an active medication can be stopped")

    med.status = "stopped"
    session.execute(
        delete(Dose).where(Dose.medication_id == med.id, Dose.state == "pending")
    )
    session.flush()
    return _regimen_state(caregiver.patient_id, session)


# --------------------------------------------------------------------------- lab reports


def _parse_report_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    # ★ Placeholder, same spirit as Medication's "(未识别)" generic_name — report_date is
    # NOT NULL so a row must be insertable even when the date couldn't be read; the
    # caregiver corrects it via LabConfirmRequest.report_date before confirming, same as
    # any other low-confidence field.
    return datetime.now(CHINA_TZ).date()


def _to_lab_report_out(report: LabReport, session: Session) -> LabReportOut:
    items = list(session.scalars(select(LabItem).where(LabItem.report_id == report.id)))
    asset_ids = json.loads(report.asset_ids) if report.asset_ids else []
    assets_by_id = (
        {a.id: a for a in session.scalars(select(Asset).where(Asset.id.in_(asset_ids)))}
        if asset_ids
        else {}
    )
    photo_urls = [
        storage.url_for(assets_by_id[aid].oss_key) for aid in asset_ids if aid in assets_by_id
    ]

    item_outs = []
    for item in items:
        previous_value = None
        if item.code:
            prev = session.scalar(
                select(LabItem.value)
                .join(LabReport, LabItem.report_id == LabReport.id)
                .where(
                    LabReport.patient_id == report.patient_id,
                    LabReport.confirmed_at.is_not(None),
                    LabReport.report_date < report.report_date,
                    LabItem.code == item.code,
                )
                .order_by(LabReport.report_date.desc())
                .limit(1)
            )
            previous_value = float(prev) if prev is not None else None
        item_outs.append(
            LabItemOut(
                item_id=item.id,
                raw_name=item.raw_name,
                code=item.code,
                value=float(item.value) if item.value is not None else None,
                unit=item.unit,
                ref_low=float(item.ref_low) if item.ref_low is not None else None,
                ref_high=float(item.ref_high) if item.ref_high is not None else None,
                flag=item.flag,  # type: ignore[arg-type]
                previous_value=previous_value,
            )
        )

    return LabReportOut(
        report_id=report.id,
        report_date=report.report_date,
        report_type=report.report_type,
        hospital=report.hospital,
        confirmed=report.confirmed_at is not None,
        photo_urls=photo_urls,
        items=item_outs,
    )


def _lab_state(patient_id: str, session: Session) -> LabReportsOut:
    reports = session.scalars(
        select(LabReport)
        .where(LabReport.patient_id == patient_id)
        .order_by(LabReport.report_date.desc())
    ).all()
    return LabReportsOut(reports=[_to_lab_report_out(r, session) for r in reports])


@router.post("/parse/lab")
def parse_lab_route(
    body: ParseRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> LabReportsOut:
    assets = list(
        session.scalars(
            select(Asset).where(
                Asset.id.in_(body.asset_ids), Asset.patient_id == caregiver.patient_id
            )
        )
    )
    if len(assets) != len(body.asset_ids):
        raise HTTPException(
            status_code=404, detail="one or more asset_ids not found for this patient"
        )

    # See parse_medbox_route's own comment on this same branch.
    if storage.is_local():
        image_urls = [f"file://{storage.local_path(a.oss_key)}" for a in assets]
    else:
        image_urls = [storage.url_for(a.oss_key) for a in assets]
    try:
        parsed = parse_lab(image_urls)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"couldn't read it, try again: {exc}") from exc

    report = LabReport(
        patient_id=caregiver.patient_id,
        report_date=_parse_report_date(parsed.report_date),
        report_type=parsed.report_type,
        hospital=parsed.hospital,
        asset_ids=json.dumps(body.asset_ids),
    )
    session.add(report)
    session.flush()
    for item in parsed.items:
        session.add(
            LabItem(
                report_id=report.id,
                raw_name=item.raw_name,
                code=item.code,
                value=item.value,
                unit=item.unit,
                ref_low=item.ref_low,
                ref_high=item.ref_high,
                flag=item.flag,
            )
        )
    session.flush()
    return _lab_state(caregiver.patient_id, session)


@router.get("/lab/reports")
def lab_reports_route(
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> LabReportsOut:
    return _lab_state(caregiver.patient_id, session)


@router.post("/lab/{report_id}/confirm")
def confirm_lab_report(
    report_id: str,
    body: LabConfirmRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> LabReportsOut:
    report = session.get(LabReport, report_id)
    if report is None or report.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="lab report not found")

    if body.report_date is not None:
        report.report_date = body.report_date
    if body.report_type is not None:
        report.report_type = body.report_type
    if body.hospital is not None:
        report.hospital = body.hospital

    items_by_id = {
        item.id: item
        for item in session.scalars(select(LabItem).where(LabItem.report_id == report.id))
    }
    for edit in body.items:
        item = items_by_id.get(edit.item_id)
        if item is None:
            continue
        if edit.raw_name is not None:
            item.raw_name = edit.raw_name
        if edit.value is not None:
            item.value = edit.value
        if edit.unit is not None:
            item.unit = edit.unit
        if edit.ref_low is not None:
            item.ref_low = edit.ref_low
        if edit.ref_high is not None:
            item.ref_high = edit.ref_high
        if edit.flag is not None:
            item.flag = edit.flag

    report.confirmed_at = datetime.now(CHINA_TZ)
    session.flush()
    return _lab_state(caregiver.patient_id, session)


@router.delete("/lab/{report_id}")
def delete_lab_report(
    report_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> LabReportsOut:
    """Mirrors delete_draft_medication: only an unconfirmed report can be discarded this
    way — a confirmed one may already be quoted back to the elder via voice Q&A
    (agent/queries.py's `_LATEST_METRIC` etc. filter on `confirmed_at IS NOT NULL`)."""
    report = session.get(LabReport, report_id)
    if report is None or report.patient_id != caregiver.patient_id:
        raise HTTPException(status_code=404, detail="lab report not found")
    if report.confirmed_at is not None:
        raise HTTPException(
            status_code=409, detail="only an unconfirmed report can be deleted this way"
        )

    session.execute(delete(LabItem).where(LabItem.report_id == report.id))
    session.delete(report)
    session.flush()
    return _lab_state(caregiver.patient_id, session)


@router.get("/patient/{patient_id}/today")
def today(
    patient_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> TodayOut:
    if patient_id != caregiver.patient_id:
        raise HTTPException(status_code=403, detail="token does not match requested patient")

    now = datetime.now(CHINA_TZ)
    day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=CHINA_TZ)
    day_end = datetime.combine(now.date(), datetime.max.time(), tzinfo=CHINA_TZ)
    rows = session.execute(
        select(Dose, Medication)
        .join(Medication, Dose.medication_id == Medication.id)
        .where(
            Dose.patient_id == patient_id,
            Dose.scheduled_at >= day_start,
            Dose.scheduled_at < day_end,
        )
        .order_by(Dose.scheduled_at)
    ).all()

    confirmed: list[DoseView] = []
    pending: list[DoseView] = []
    unknown: list[DoseView] = []
    for dose, med in rows:
        scheduled_at = dose.scheduled_at
        # ★ Matches device.py's _dose_view: datetime.now(tzinfo) degrades to a plain naive
        # now() when the DB gives back a naive datetime (SQLite in tests), and to an aware
        # comparison against Postgres's real TIMESTAMPTZ otherwise.
        overdue = scheduled_at < datetime.now(scheduled_at.tzinfo)
        # ★ Three real buckets, never two (schemas.TodayOut docstring): a past-due dose
        # nobody confirmed is 'unknown', not silently folded into 'pending'.
        if dose.state == "confirmed":
            bucket, state = confirmed, "confirmed"
        elif dose.state == "pending" and overdue:
            bucket, state = unknown, "missed"
        else:
            bucket, state = pending, dose.state
        bucket.append(
            DoseView(
                dose_id=dose.id,
                scheduled_at=dose.scheduled_at,
                medication=med.generic_name,
                state=state,  # type: ignore[arg-type]
            )
        )

    return TodayOut(
        patient_id=patient_id,
        date=now.date(),
        confirmed=confirmed,
        pending=pending,
        unknown=unknown,
    )


@router.post("/patient/{patient_id}/pairing-code")
def create_pairing_code(
    patient_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> PairingCodeOut:
    """Generates (or replaces) the code setup.html shows the caregiver to read aloud while
    installing the elder's APK — the formal, per-elder pairing flow that replaces
    HomeActivity's old "connect test server" debug button, which only ever worked against
    a hardcoded test patient over an emulator-only address. ★ Requesting a new code
    immediately invalidates whatever code was showing before: only one is ever live per
    patient, so a code left visible in an old screenshot or WeChat message stops working
    the moment a fresh one is generated."""
    if patient_id != caregiver.patient_id:
        raise HTTPException(status_code=403, detail="token does not match requested patient")
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")

    for _ in range(10):
        code = f"{secrets.randbelow(1_000_000):06d}"
        collision = session.scalar(select(Patient).where(Patient.pairing_code == code))
        if collision is None:
            break
    else:
        raise HTTPException(status_code=503, detail="couldn't generate a unique code, try again")

    patient.pairing_code = code
    patient.pairing_code_expires_at = datetime.now(CHINA_TZ) + timedelta(minutes=15)
    session.flush()
    return PairingCodeOut(code=code, expires_at=patient.pairing_code_expires_at)


@router.post("/setup/contact")
def setup_contact(
    body: ContactRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    caregiver.called_by = body.called_by
    caregiver.relation = body.relation
    caregiver.phone = body.phone
    patient = session.get(Patient, caregiver.patient_id)
    if patient is not None:
        patient.display_name = body.display_name
    session.flush()
    return {"status": "ok"}


# --------------------------------------------------------------------------- account


@router.post("/account/start")
def account_start(
    body: AccountStartRequest, session: Session = Depends(get_session)
) -> AccountStartOut:
    """The one self-serve entry point this POC has — everything else is still white-glove
    onboarding (see scripts/seed_test_patient.py's own docstring). A caregiver with no
    existing link creates their first elder profile here; every elder after the first goes
    through POST /api/account/patients instead, authenticated by the link they already
    have — there is no separate account signup step."""
    patient = Patient(display_name=body.display_name)
    session.add(patient)
    session.flush()
    caregiver = Caregiver(
        patient_id=patient.id,
        called_by=body.called_by,
        relation=body.relation,
        phone=body.phone,
        access_token=secrets.token_urlsafe(24),
    )
    session.add(caregiver)
    session.flush()
    return AccountStartOut(patient_id=patient.id, access_token=caregiver.access_token)


@router.post("/account/patients")
def add_patient(
    body: AddPatientRequest,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> AccountStartOut:
    """Adds another elder under the SAME caregiver. ★ Identified by phone number — the same
    field every caregiver already gives in 联系方式 (setup.html) — not a new account/login
    system; GET /api/account/patients below does the matching lookup. POC-scale
    simplification, same spirit as Caregiver's own "exactly one per patient" docstring: two
    different real people who happen to share a phone number would incorrectly see each
    other's elders. Acceptable at this scale; a real account system is future work."""
    patient = Patient(display_name=body.display_name)
    session.add(patient)
    session.flush()
    new_caregiver = Caregiver(
        patient_id=patient.id,
        called_by=caregiver.called_by,
        relation=caregiver.relation,
        phone=caregiver.phone,
        access_token=secrets.token_urlsafe(24),
    )
    session.add(new_caregiver)
    session.flush()
    return AccountStartOut(patient_id=patient.id, access_token=new_caregiver.access_token)


@router.get("/account/patients")
def list_patients(
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> AccountPatientsOut:
    rows = session.execute(
        select(Caregiver, Patient)
        .join(Patient, Caregiver.patient_id == Patient.id)
        .where(Caregiver.phone == caregiver.phone)
        .order_by(Patient.created_at)
    ).all()
    return AccountPatientsOut(
        patients=[
            AccountPatientOut(
                patient_id=p.id,
                display_name=p.display_name,
                access_token=c.access_token,
                is_current=c.id == caregiver.id,
            )
            for c, p in rows
        ]
    )


@router.delete("/account/patients/{patient_id}")
def delete_patient(
    patient_id: str,
    caregiver: Caregiver = Depends(caregiver_from_token),
    session: Session = Depends(get_session),
) -> AccountPatientsOut:
    """Removes an elder profile from this caregiver's list (elders.html's delete button) —
    e.g. a duplicate or mistakenly-added entry. ★ Scoped by phone, like list_patients: any
    of the caregiver's own elder tokens may delete any of their elders, not just its own.
    Unlike delete_draft_medication/delete_lab_report, this is not restricted to
    unconfirmed/draft data — removing the elder itself is a deliberate, whole-profile
    action, not an edit to history, so it cascades through everything scoped to
    patient_id. Refuses to remove the last remaining elder: a caregiver's phone is always
    tied to at least one profile, and there is no "start over" flow — POST
    /api/account/patients only ever adds another elder alongside an existing one."""
    target = session.scalar(
        select(Caregiver).where(
            Caregiver.patient_id == patient_id, Caregiver.phone == caregiver.phone
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="elder not found")

    remaining = session.scalar(
        select(func.count()).select_from(Caregiver).where(Caregiver.phone == caregiver.phone)
    )
    if remaining is not None and remaining <= 1:
        raise HTTPException(status_code=409, detail="不能删除最后一位老人")

    session.execute(
        delete(LabItem).where(
            LabItem.report_id.in_(select(LabReport.id).where(LabReport.patient_id == patient_id))
        )
    )
    session.execute(delete(LabReport).where(LabReport.patient_id == patient_id))
    session.execute(delete(ConfirmationEvent).where(ConfirmationEvent.patient_id == patient_id))
    session.execute(delete(Dose).where(Dose.patient_id == patient_id))
    session.execute(delete(Medication).where(Medication.patient_id == patient_id))
    session.execute(delete(Escalation).where(Escalation.patient_id == patient_id))
    session.execute(delete(Asset).where(Asset.patient_id == patient_id))
    session.execute(delete(Caregiver).where(Caregiver.patient_id == patient_id))
    patient = session.get(Patient, patient_id)
    if patient is not None:
        session.delete(patient)
    session.flush()

    rows = session.execute(
        select(Caregiver, Patient)
        .join(Patient, Caregiver.patient_id == Patient.id)
        .where(Caregiver.phone == caregiver.phone)
        .order_by(Patient.created_at)
    ).all()
    return AccountPatientsOut(
        patients=[
            AccountPatientOut(
                patient_id=p.id,
                display_name=p.display_name,
                access_token=c.access_token,
                is_current=c.id == caregiver.id,
            )
            for c, p in rows
        ]
    )
