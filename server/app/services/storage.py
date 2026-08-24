"""Asset storage. ★ POC/local-testing stand-in for Alibaba Cloud OSS (spec §2's real
choice) — no OSS credentials are configured in this environment. Writes to local disk
under a content-addressed key and serves it back via /media/{oss_key} in app/main.py.

Swap this module for a real OSS-backed implementation before anything resembling
production; the call sites (app/api/*) only depend on save() returning (oss_key, sha256)
and url_for() turning a key into something fetchable, so the swap is contained here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import settings

STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / ".local_storage"


def save(patient_id: str, kind: str, filename: str, content: bytes) -> tuple[str, str]:
    """Returns (oss_key, sha256). ★ The original is written before any parsing happens —
    without it there is no way to arbitrate a parsing error later (models/tables.py Asset
    docstring)."""
    sha256 = hashlib.sha256(content).hexdigest()
    suffix = Path(filename).suffix or ".bin"
    oss_key = f"{patient_id}/{kind}/{sha256}{suffix}"

    path = STORAGE_ROOT / oss_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    return oss_key, sha256


def local_path(oss_key: str) -> Path:
    return STORAGE_ROOT / oss_key


def url_for(oss_key: str) -> str:
    """A URL the elder device / caregiver web can fetch the asset from. Local dev only —
    real OSS would return a signed bucket URL instead."""
    return f"{settings().base_url}/media/{oss_key}"
