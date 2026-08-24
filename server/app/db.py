"""Engine and session lifecycle."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_engine = create_engine(settings().database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def engine():  # type: ignore[no-untyped-def]
    return _engine
