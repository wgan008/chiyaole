"""Fixtures for the browser-driven golden-path E2E suite.

Unlike server/tests/conftest.py (an in-process ASGI TestClient — no real socket), Playwright
drives a real Chromium process that must reach the app over an actual HTTP port, so this
spins up `uvicorn` in a background thread of the SAME test process, serving the SAME `app`
object with `app.dependency_overrides[get_session]` pointed at an in-memory SQLite engine —
identical pattern to tests/conftest.py's `session`/`client` fixtures, just over a real socket
instead of ASGI-in-process, so a Playwright browser page and this fixture's own `httpx` calls
(simulating the Android device's API traffic) see the same committed data.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base


class _NoSignalServer(uvicorn.Server):
    """uvicorn installs SIGINT/SIGTERM handlers by default, which only works on the main
    thread — this test process's main thread is pytest's. Standard workaround for running
    uvicorn programmatically inside a test."""

    def install_signal_handlers(self) -> None:
        pass


@pytest.fixture()
def live_server() -> Iterator[tuple[str, sessionmaker]]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_session() -> Iterator[object]:
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = _NoSignalServer(config=config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start within 10s")
        time.sleep(0.02)

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield base_url, session_factory
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        app.dependency_overrides.pop(get_session, None)
