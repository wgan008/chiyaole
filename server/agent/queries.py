"""Hand-written parameterised SQL — one function per intent.

★ Every statement here was written by a person and is reviewable as a unit. Nothing in this
file is generated, templated from user input, or string-formatted with a value. `patient_id`
is always a bound parameter, on every path, without exception.

## Prohibited

- ❌ No f-strings, no `%`, no `.format()`, no concatenation inside a SQL string. Ever.
- ❌ No query without a `patient_id = :patient_id` predicate. One elder's data must not be
     reachable from another's session even by accident.
- ❌ No `SELECT *`. Columns are listed so a schema change breaks loudly instead of leaking
     a new column into a spoken answer.
- ❌ No interpretation. These return numbers and dates. `phrase` reads them out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from .types import QueryResult, Slots

# ★ "Today" means China's calendar day, not UTC's — the server process runs in UTC (see
# app/api/caregiver.py's own CHINA_TZ note), so for roughly 8 hours of every day (China's
# 00:00-07:59) the UTC date is still "yesterday". Confirmed live as a real bug (dose times
# stored 8 hours off); this function had the same class of mistake for "did I take my
# meds today", just not yet caught live.
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# --------------------------------------------------------------------------- statements

_LATEST_METRIC = text("""
    SELECT li.value, li.unit, li.ref_low, li.ref_high, li.flag, lr.report_date
      FROM lab_items li
      JOIN lab_reports lr ON lr.id = li.report_id
     WHERE lr.patient_id = :patient_id
       AND li.code       = :code
       AND lr.confirmed_at IS NOT NULL
     ORDER BY lr.report_date DESC
     LIMIT 1
""")

_COMPARE_METRIC = text("""
    SELECT li.value, li.unit, li.ref_low, li.ref_high, li.flag, lr.report_date
      FROM lab_items li
      JOIN lab_reports lr ON lr.id = li.report_id
     WHERE lr.patient_id = :patient_id
       AND li.code       = :code
       AND lr.confirmed_at IS NOT NULL
     ORDER BY lr.report_date DESC
     LIMIT 2
""")

_ABNORMAL = text("""
    SELECT li.raw_name, li.code, li.value, li.unit, li.flag, lr.report_date
      FROM lab_items li
      JOIN lab_reports lr ON lr.id = li.report_id
     WHERE lr.patient_id = :patient_id
       AND lr.confirmed_at IS NOT NULL
       AND li.flag IN ('H', 'L')
       AND lr.report_date = (
             SELECT MAX(lr2.report_date) FROM lab_reports lr2
              WHERE lr2.patient_id = :patient_id AND lr2.confirmed_at IS NOT NULL
           )
     ORDER BY li.flag, li.raw_name
""")

_LAST_REPORT = text("""
    SELECT lr.report_date, lr.report_type, lr.hospital
      FROM lab_reports lr
     WHERE lr.patient_id = :patient_id
       AND lr.confirmed_at IS NOT NULL
     ORDER BY lr.report_date DESC
     LIMIT 1
""")

# ★ Note what this counts: confirmation EVENTS, not pills. It answers "did you press the
# button", which is the only thing we actually know.
_MED_TAKEN_TODAY = text("""
    SELECT d.scheduled_at,
           m.generic_name,
           ce.action,
           ce.tapped_at
      FROM doses d
      JOIN medications m ON m.id = d.medication_id
      LEFT JOIN confirmation_events ce ON ce.dose_id = d.id
     WHERE d.patient_id  = :patient_id
       AND d.scheduled_at >= :day_start
       AND d.scheduled_at <  :day_end
     ORDER BY d.scheduled_at
""")


# --------------------------------------------------------------------------- runners


def _row_to_china_tz(row: dict[str, Any]) -> dict[str, Any]:
    """★ Every timestamp column comes back from psycopg as a UTC-instant, timezone-aware
    datetime (correct — that's what's actually stored). Converted to China wall-clock time
    right here, once, for every row/column, rather than leaving it to `qa.phrase` (or the
    LLM it calls) to somehow know to do that — confirmed live: a caregiver's 18:55 dose
    got read back to the elder as "10:55", the raw UTC hour, because nothing ever
    converted it before the value reached the phrasing step."""
    return {
        k: v.astimezone(CHINA_TZ) if isinstance(v, datetime) and v.tzinfo is not None else v
        for k, v in row.items()
    }


def _rows(session: Session, stmt: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [_row_to_china_tz(dict(r)) for r in session.execute(stmt, params).mappings().all()]


def metric_latest(session: Session, patient_id: str, slots: Slots) -> QueryResult:
    rows = _rows(session, _LATEST_METRIC, {"patient_id": patient_id, "code": slots.metric_code})
    return QueryResult(intent="metric_latest", rows=rows, empty=not rows)


def metric_compare(session: Session, patient_id: str, slots: Slots) -> QueryResult:
    rows = _rows(session, _COMPARE_METRIC, {"patient_id": patient_id, "code": slots.metric_code})
    # ★ One data point is not a comparison. Report it as empty rather than as "unchanged".
    return QueryResult(intent="metric_compare", rows=rows, empty=len(rows) < 2)


def abnormal_list(session: Session, patient_id: str, slots: Slots) -> QueryResult:
    rows = _rows(session, _ABNORMAL, {"patient_id": patient_id})
    return QueryResult(intent="abnormal_list", rows=rows, empty=not rows)


def last_report(session: Session, patient_id: str, slots: Slots) -> QueryResult:
    rows = _rows(session, _LAST_REPORT, {"patient_id": patient_id})
    return QueryResult(intent="last_report", rows=rows, empty=not rows)


def med_taken_today(session: Session, patient_id: str, slots: Slots) -> QueryResult:
    from datetime import datetime, time

    today = datetime.now(CHINA_TZ).date()
    rows = _rows(
        session,
        _MED_TAKEN_TODAY,
        {
            "patient_id": patient_id,
            "day_start": datetime.combine(today, time.min, tzinfo=CHINA_TZ),
            "day_end": datetime.combine(today, time.max, tzinfo=CHINA_TZ),
        },
    )
    return QueryResult(intent="med_taken_today", rows=rows, empty=not rows)


_DISPATCH = {
    "metric_latest": metric_latest,
    "metric_compare": metric_compare,
    "abnormal_list": abnormal_list,
    "last_report": last_report,
    "med_taken_today": med_taken_today,
}


def run(intent: str, slots: Slots, patient_id: str, *, session: Session) -> QueryResult:
    """Dispatch to the one hand-written function for this intent.

    An unknown intent raises: it means the enum and this table drifted apart, which is a
    bug that must fail loudly rather than degrade into a default query.
    """
    fn = _DISPATCH.get(intent)
    if fn is None:
        raise KeyError(f"no query implemented for intent {intent!r}")
    return fn(session, patient_id, slots)
