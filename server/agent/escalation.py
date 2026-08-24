"""Escalation: triage → outbox state machine → delivery to the caregiver's WeChat.

## Prohibited

- ❌ **The system must never claim a delivery that has not happened.** Before the push is
     confirmed the elder hears "我这就去问小芳" (future tense). Only `DELIVERED` may say
     "已经". This is asserted in tests, not left to reviewer discipline — see
     `PRE_DELIVERY_STATES` and `test_escalation.py`.
- ❌ `utterance_raw` is never rewritten, summarised, cleaned up or translated. The daughter
     needs to hear that her mother hesitated, and how she said it.
- ❌ The outbox must survive a restart. State lives in PostgreSQL, never in memory.
- ❌ Never drop an escalation because delivery failed. It retries for up to 7 days and then
     surfaces as FAILED with a full-screen dial button — a human path, not a silent drop.

## Why the wording rule is a state machine and not a style guide

An elder who is told "I've asked your daughter" and then waits four hours for an answer
that was never sent learns that the device lies. That is unrecoverable — every later
reassurance is worth nothing. So the phrasing is derived from the state, mechanically,
and there is no code path that can produce the past tense before delivery is confirmed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import loader
from .types import Escalation, EscalationKind, EscalationState, Refuse

# States in which delivery has NOT been confirmed. Nothing said to the elder in these
# states may claim that the message arrived.
PRE_DELIVERY_STATES: frozenset[EscalationState] = frozenset(
    {EscalationState.OPEN, EscalationState.SENT, EscalationState.FAILED}
)

# Markers that assert a completed delivery. Forbidden in any pre-delivery message.
PAST_DELIVERY_MARKERS: tuple[str, ...] = ("已经", "已", "告诉了", "带到了", "转告了", "发过去了")

_ALLOWED: dict[EscalationState, set[EscalationState]] = {
    EscalationState.OPEN: {EscalationState.SENT, EscalationState.FAILED,
                           EscalationState.CLOSED},
    EscalationState.SENT: {EscalationState.DELIVERED, EscalationState.FAILED,
                           EscalationState.OPEN},
    EscalationState.DELIVERED: {EscalationState.ANSWERED, EscalationState.CLOSED},
    EscalationState.ANSWERED: {EscalationState.RELAYED, EscalationState.CLOSED},
    EscalationState.RELAYED: {EscalationState.CLOSED},
    EscalationState.FAILED: {EscalationState.OPEN, EscalationState.CLOSED},
    EscalationState.CLOSED: set(),
}


class IllegalTransition(ValueError):
    """Raised on an undefined state transition. A bug, not a runtime condition."""


# --------------------------------------------------------------------------- triage


def triage(
    *,
    refusal: Refuse | None = None,
    kind: str | None = None,
    missed_doses: int = 0,
) -> tuple[EscalationKind, int]:
    """Decide what this is and how urgent it is.

    Urgency 1 is highest. Values come from remote_config.json so they can be retuned
    without shipping an APK.
    """
    cfg = loader.remote_config()["escalation"]
    urgency_by_kind: dict[str, int] = cfg["urgency_by_kind"]

    if refusal is not None and refusal.escalate_kind:
        resolved = EscalationKind(refusal.escalate_kind)
        # The guard's own urgency wins when it is more urgent than the default: a red-flag
        # symptom is a 1 regardless of what the generic SYMPTOM default happens to be.
        default = urgency_by_kind.get(resolved.value, 3)
        return resolved, min(refusal.urgency or default, default)

    if kind is not None:
        resolved = EscalationKind(kind)
        return resolved, urgency_by_kind.get(resolved.value, 3)

    if missed_doses >= cfg["missed_dose_threshold"]:
        return EscalationKind.MISSED_DOSE, urgency_by_kind["MISSED_DOSE"]

    raise ValueError("triage() needs a refusal, a kind, or a missed-dose count")


# --------------------------------------------------------------------------- wording


def elder_message(state: EscalationState | str, caregiver: str = "小芳") -> str:
    """The ONLY phrasing the elder may hear for a given state.

    ★ Derived from state mechanically. There is deliberately no code path that lets a
    caller supply its own string here.
    """
    st = EscalationState(state)
    template: str = loader.remote_config()["copy"]["escalation_state_messages"][st.value]
    message = template.format(caregiver=caregiver)

    # Belt and braces: the assertion also runs in production, not only in tests.
    if st in PRE_DELIVERY_STATES:
        for marker in PAST_DELIVERY_MARKERS:
            if marker in message:
                raise AssertionError(
                    f"remote_config copy for state {st.value} contains the completed-delivery "
                    f"marker {marker!r}: {message!r}. The system must not claim a delivery "
                    f"that has not happened."
                )
    return message


# --------------------------------------------------------------------------- outbox


def next_retry_at(attempts: int, *, now: datetime | None = None) -> datetime | None:
    """Exponential backoff from remote_config. None once the 7-day budget is spent."""
    cfg = loader.remote_config()["escalation"]
    backoff: list[int] = cfg["retry_backoff_seconds"]
    now = now or datetime.now(timezone.utc)
    if attempts >= len(backoff):
        elapsed = timedelta(seconds=sum(backoff))
        if elapsed >= timedelta(days=cfg["max_retry_days"]):
            return None
        return now + timedelta(seconds=backoff[-1])
    return now + timedelta(seconds=backoff[attempts])


def transition(
    esc: Escalation,
    to: EscalationState,
    *,
    now: datetime | None = None,
) -> Escalation:
    """Move an escalation to a new state, or raise.

    Returns a NEW object — the outbox rows are written by the caller inside a transaction,
    so this stays a pure function and is trivially testable.
    """
    now = now or datetime.now(timezone.utc)
    if to not in _ALLOWED[esc.state]:
        raise IllegalTransition(f"{esc.state.value} -> {to.value} is not a defined transition")

    updated = esc.model_copy(deep=True)
    updated.state = to

    if to is EscalationState.SENT:
        updated.attempts = esc.attempts + 1
        updated.next_retry_at = next_retry_at(updated.attempts, now=now)
    elif to is EscalationState.DELIVERED:
        updated.delivered_at = now
        updated.next_retry_at = None
    elif to is EscalationState.FAILED:
        updated.next_retry_at = next_retry_at(esc.attempts, now=now)
    elif to is EscalationState.CLOSED:
        updated.next_retry_at = None

    return updated


def is_exhausted(esc: Escalation, *, now: datetime | None = None) -> bool:
    """True once the retry budget is spent and the caregiver must be reached another way."""
    cfg = loader.remote_config()["escalation"]
    now = now or datetime.now(timezone.utc)
    if esc.created_at is None:
        return False
    created = esc.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created) > timedelta(days=cfg["max_retry_days"])
