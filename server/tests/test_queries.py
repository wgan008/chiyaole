"""Unit tests for agent/queries.py's row post-processing — separate from the end-to-end
POST /api/qa tests in test_voice_qa.py because this specific bug (see _row_to_china_tz's
own docstring) can't be reproduced through the HTTP layer under SQLite, this suite's test
backend: SQLite never returns a timezone-aware datetime in the first place, so there's
nothing for the conversion to act on. This tests the pure conversion function directly
against a synthetic UTC-aware value instead."""

from __future__ import annotations

from datetime import UTC, datetime

from agent.queries import _row_to_china_tz


def test_row_to_china_tz_converts_utc_datetime_to_beijing_wall_clock() -> None:
    """★ Regression test for a real bug hit live: a dose scheduled for 18:55 Beijing time
    (stored correctly as 10:55 UTC, per app/api/caregiver.py's own CHINA_TZ fix) was read
    back to the elder as "10:55" — the raw UTC hour — because nothing converted it before
    it reached qa.py's phrase() / the LLM prompt built from these rows."""
    row = {
        "scheduled_at": datetime(2026, 8, 26, 10, 55, tzinfo=UTC),
        "generic_name": "阿司匹林",
    }

    converted = _row_to_china_tz(row)

    assert converted["scheduled_at"].hour == 18
    assert converted["scheduled_at"].minute == 55
    assert str(converted["scheduled_at"].tzinfo) == "Asia/Shanghai"
    # Non-datetime values pass through untouched.
    assert converted["generic_name"] == "阿司匹林"


def test_row_to_china_tz_leaves_naive_and_non_datetime_values_alone() -> None:
    """Naive datetimes (shouldn't occur against real Postgres, but SQLite in tests
    produces them) and plain values must not be touched or raise."""
    row = {"scheduled_at": datetime(2026, 8, 26, 18, 55), "code": None, "count": 3}

    converted = _row_to_china_tz(row)

    assert converted["scheduled_at"] == datetime(2026, 8, 26, 18, 55)
    assert converted["scheduled_at"].tzinfo is None
    assert converted["code"] is None
    assert converted["count"] == 3
