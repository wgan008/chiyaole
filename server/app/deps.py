"""Shared dependencies: auth for the two very different callers.

The caregiver authenticates with a random token embedded in the URL they got over WeChat.
The elder's device authenticates with a token issued at registration. Neither party ever
types a password — the elder cannot, and the adult child would not.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Caregiver, Patient


def caregiver_from_token(
    token: str = Query(..., alias="t", description="access_token from the caregiver URL"),
    session: Session = Depends(get_session),
) -> Caregiver:
    caregiver = session.scalar(select(Caregiver).where(Caregiver.access_token == token))
    if caregiver is None:
        raise HTTPException(status_code=401, detail="invalid access token")
    return caregiver


def device_patient(
    x_device_token: str = Header(..., alias="X-Device-Token"),
    session: Session = Depends(get_session),
) -> Patient:
    # POC: the device token is the patient id, signed by possession of the enrolment link.
    # TODO before any real rollout: issue a separate opaque token and store its hash.
    patient = session.get(Patient, x_device_token)
    if patient is None:
        raise HTTPException(status_code=401, detail="unknown device")
    return patient
