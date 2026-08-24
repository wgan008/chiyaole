from __future__ import annotations

import uuid

from sqlalchemy import String, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class GUID(TypeDecorator[str]):
    """UUID on PostgreSQL, CHAR(36) elsewhere.

    Exists so the unit tests can run the real schema on in-memory SQLite. Production is
    always PostgreSQL 16 (docs/spec §2).
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        return None if value is None else str(value)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        return None if value is None else str(value)


def new_uuid() -> str:
    return str(uuid.uuid4())
