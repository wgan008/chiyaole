"""Shared test fixtures: an in-memory SQLite database standing in for the real Postgres
(the schema is written to support this — see app/models/base.py's GUID type and
Escalation.context_json's `.with_variant(Text, "sqlite")`), plus a FastAPI TestClient wired
to it via a dependency override, so route-level tests never touch a real database or the
live DashScope API."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base, Caregiver, Patient


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = local_session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    def _get_session_override() -> Iterator[Session]:
        # ★ Deliberately does NOT close/commit-then-rollback the shared `session` fixture —
        # one transaction spans the whole test so assertions can read back what a route
        # just wrote, same as app.db.get_session's own commit-on-success contract.
        yield session
        session.commit()

    app.dependency_overrides[get_session] = _get_session_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def patient(session: Session) -> Patient:
    p = Patient(display_name="王阿姨")
    session.add(p)
    session.flush()
    return p


@pytest.fixture()
def caregiver(session: Session, patient: Patient) -> Caregiver:
    c = Caregiver(
        patient_id=patient.id,
        called_by="小芳",
        relation="daughter",
        phone="13800000000",
        access_token="test-token",
    )
    session.add(c)
    session.flush()
    return c
