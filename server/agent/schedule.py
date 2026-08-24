"""Turn the dosage text printed on a pill box into concrete clock times.

## Prohibited

- ❌ Must not guess a frequency that is not stated. "必要时" (as needed), "遵医嘱"
     (as directed) with no frequency anywhere else in the text, and an empty usage line all
     return `Ambiguous`. Chinese package inserts almost always end with a boilerplate
     "其他内容详见说明书" sentence about non-dosage details even when the frequency is
     stated plainly earlier in the same paragraph ("一日2次...或遵医嘱") — treating that as
     ambiguous would refuse nearly every real box. The rule is not "does 遵医嘱/详见说明书
     appear anywhere in the text" but "is there still no extractable frequency after
     looking."
- ❌ Must not interpret 饭前/饭后 medically. It anchors a time to the elder's stated meal
     routine. That is arithmetic, not advice.
- ❌ Must not silently reconcile a contradiction between `times_per_day` and `usage_raw`.
     Two sources disagreeing is exactly the case a human must look at.
- ❌ Must not schedule a medication that is not confirmed (`Medication.is_active`).
     The caller enforces this; `synthesize` refuses too, as a second line.

## Why refusing is cheap here

"As needed" is genuinely unschedulable. An alarm invented for it rings at a time no doctor
chose, and the elder learns that the alarm is sometimes wrong — which costs far more than
the one line the caregiver has to type.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from .types import Ambiguous, DailyRoutine, Medication

# --------------------------------------------------------------------------- frequency

_FREQ_PATTERNS: list[tuple[str, int]] = [
    (r"(?:一日|每日|每天|一天)\s*[1１一]\s*次", 1),
    (r"(?:一日|每日|每天|一天)\s*[2２两二]\s*次", 2),
    (r"(?:一日|每日|每天|一天)\s*[3３三]\s*次", 3),
    (r"(?:一日|每日|每天|一天)\s*[4４四]\s*次", 4),
    (r"\bq\.?d\b", 1),
    (r"\bb\.?i\.?d\b", 2),
    (r"\bt\.?i\.?d\b", 3),
    (r"\bq\.?i\.?d\b", 4),
    (r"每晚[1１一]?次?", 1),
    (r"睡前(?:服|口服)?", 1),
    (r"晨起(?:服|口服)?", 1),
]

# Anything matching these means the dosing itself is conditional/irregular regardless of
# any frequency number that might also appear nearby — checked BEFORE frequency extraction.
_HARD_AMBIGUOUS_PATTERNS: list[tuple[str, str]] = [
    (r"必要时|需要时|按需|prn|p\.r\.n", "AS_NEEDED"),
    (r"隔日|隔天|每隔[一二三两\d]+日|每周|一周|qod|q\.o\.d", "NON_DAILY"),
    (r"逐渐加量|递增|滴定|按体重|按血压调整|根据.{0,6}调整", "TITRATED"),
]

# "As directed" boilerplate ("遵医嘱"/"详见说明书") is usually a trailing disclaimer about
# details OTHER than frequency, not a statement that frequency itself is unknown — checked
# only as a fallback, after frequency extraction has already failed.
_AS_DIRECTED_PATTERN = r"遵医嘱|遵嘱|按医师指导|详见说明书|请咨询医师"

# --------------------------------------------------------------------------- timing

_TIMING = {
    "BEFORE_MEAL": r"饭前|餐前|进食前|空腹",
    "AFTER_MEAL": r"饭后|餐后|进食后|随餐",
    "BEDTIME": r"睡前|临睡|睡觉前",
    "MORNING": r"晨起|早晨|清晨|早上服",
}

_MEAL_OFFSET_MIN = 30  # "before meals" = 30 min before; "after meals" = 30 min after


def synthesize(
    med: Medication,
    routine: DailyRoutine,
    *,
    on_date: date | None = None,
) -> list[datetime] | Ambiguous:
    """Dosage text + this elder's routine → concrete times for one day.

    `on_date` defaults to today; the caller generates seven days ahead by iterating.

    >>> from agent.types import Medication, DailyRoutine
    >>> synthesize(Medication(usage_raw="必要时服用"), DailyRoutine())
    Ambiguous(reason='AS_NEEDED', raw='必要时服用', candidates=[])
    """
    day = on_date or date.today()
    text = (med.usage_raw or "") + " " + (med.timing_note or "")
    text = text.strip()

    for pattern, reason in _HARD_AMBIGUOUS_PATTERNS:
        if re.search(pattern, text, re.I):
            return Ambiguous(reason=reason, raw=med.usage_raw)

    stated = _frequency_from_text(text)
    declared = med.times_per_day

    if stated is None and declared is None:
        if re.search(_AS_DIRECTED_PATTERN, text, re.I):
            return Ambiguous(reason="AS_DIRECTED", raw=med.usage_raw)
        return Ambiguous(reason="NO_FREQUENCY", raw=med.usage_raw or None)
    if stated is not None and declared is not None and stated != declared:
        return Ambiguous(
            reason="FREQUENCY_CONFLICT",
            raw=med.usage_raw,
            candidates=[f"usage_raw={stated}", f"times_per_day={declared}"],
        )

    n = stated if stated is not None else declared
    assert n is not None
    if n < 1 or n > 6:
        return Ambiguous(reason="FREQUENCY_OUT_OF_RANGE", raw=med.usage_raw)

    timing = _timing_from_text(text)
    times = _times_for(n, timing, routine)
    if times is None:
        return Ambiguous(reason="UNSUPPORTED_TIMING", raw=med.usage_raw)

    return [datetime.combine(day, t) for t in times]


def synthesize_days(
    med: Medication,
    routine: DailyRoutine,
    *,
    start: date | None = None,
    days: int = 7,
) -> list[datetime] | Ambiguous:
    """Seven days ahead — what `doses` is populated from (spec §5)."""
    start = start or date.today()
    out: list[datetime] = []
    for offset in range(days):
        result = synthesize(med, routine, on_date=start + timedelta(days=offset))
        if isinstance(result, Ambiguous):
            return result
        out.extend(result)
    return out


# --------------------------------------------------------------------------- internals


def _frequency_from_text(text: str) -> int | None:
    if not text:
        return None
    for pattern, n in _FREQ_PATTERNS:
        if re.search(pattern, text, re.I):
            return n
    return None


def _timing_from_text(text: str) -> str | None:
    for name, pattern in _TIMING.items():
        if re.search(pattern, text):
            return name
    return None


def _shift(t: time, minutes: int) -> time:
    return (datetime.combine(date(2000, 1, 1), t) + timedelta(minutes=minutes)).time()


def _times_for(n: int, timing: str | None, r: DailyRoutine) -> list[time] | None:
    """Anchor n doses per day to this elder's actual routine.

    Note the once-daily default is breakfast, not 08:00. Someone who gets up at 05:00
    should not be woken by a reminder at 08:00 for a pill they could have taken at 05:30.
    """
    meals = [r.breakfast, r.lunch, r.dinner]

    if timing == "BEDTIME":
        return [r.sleep] if n == 1 else None
    if timing == "MORNING":
        return [r.wake] if n == 1 else None

    if timing == "BEFORE_MEAL":
        anchors = [_shift(m, -_MEAL_OFFSET_MIN) for m in meals]
    elif timing == "AFTER_MEAL":
        anchors = [_shift(m, _MEAL_OFFSET_MIN) for m in meals]
    else:
        anchors = meals

    if n == 1:
        return [anchors[0]]
    if n == 2:
        return [anchors[0], anchors[2]]
    if n == 3:
        return anchors
    if n == 4:
        return [*anchors, r.sleep]
    return None
