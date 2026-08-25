"""Asset storage — real Alibaba Cloud OSS when OSS_* credentials are configured
(config.py's "everything secret comes from the environment; nothing is defaulted to a
real value"), otherwise a local-disk stand-in so local dev never needs OSS credentials.

Swap-contained by design: every caller (app/api/*, agent/vision.py's OCR calls via
url_for()) only depends on save() returning (oss_key, sha256) and url_for()/is_local()
turning a key into something fetchable — nothing outside this module knows which backend
is actually in play.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import oss2

from ..config import settings

STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / ".local_storage"

# Regenerated fresh on every url_for() call, never stored — matches the bucket's private
# ACL (spec: never publicly expose a photo of a pill box or a lab report). Long enough to
# cover an immediate DashScope OCR fetch or a browser loading an <img>, short enough that
# a leaked/logged URL doesn't stay valid for long.
_SIGNED_URL_EXPIRES_SECONDS = 3600


def _oss_configured() -> bool:
    s = settings()
    return bool(s.oss_endpoint and s.oss_bucket and s.oss_access_key_id and s.oss_access_key_secret)


@lru_cache(maxsize=1)
def _bucket() -> oss2.Bucket:
    s = settings()
    auth = oss2.Auth(s.oss_access_key_id, s.oss_access_key_secret)
    endpoint = s.oss_endpoint if s.oss_endpoint.startswith("http") else f"https://{s.oss_endpoint}"
    return oss2.Bucket(auth, endpoint, s.oss_bucket)


def is_local() -> bool:
    """★ Callers that need a locally-resolvable path (agent/vision.py's OCR calls, via
    `file://` — DashScope's SDK reads a local file itself rather than fetching a URL, so
    this only works when the file is actually on this machine) must check this first and
    fall back to url_for() otherwise. A `storage.url_for()` result is always fetchable
    on its own — this is only about which path a *local* fetch needs."""
    return not _oss_configured()


def save(patient_id: str, kind: str, filename: str, content: bytes) -> tuple[str, str]:
    """Returns (oss_key, sha256). ★ The original is written before any parsing happens —
    without it there is no way to arbitrate a parsing error later (models/tables.py Asset
    docstring)."""
    sha256 = hashlib.sha256(content).hexdigest()
    suffix = Path(filename).suffix or ".bin"
    oss_key = f"{patient_id}/{kind}/{sha256}{suffix}"

    if _oss_configured():
        _bucket().put_object(oss_key, content)
    else:
        path = STORAGE_ROOT / oss_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    return oss_key, sha256


def local_path(oss_key: str) -> Path:
    """Local-disk mode only — see is_local()'s docstring for why a caller must check
    first rather than assuming this resolves to a real file."""
    return STORAGE_ROOT / oss_key


def url_for(oss_key: str) -> str:
    """A URL the elder device / caregiver web / DashScope's OCR call can all fetch the
    asset from. Real OSS: a freshly-signed, time-limited URL (see
    _SIGNED_URL_EXPIRES_SECONDS). Local dev: the app's own /media/{oss_key} route —
    reachable from the browser and the emulator, but NOT from DashScope's remote
    servers, which is why OCR call sites branch on is_local() instead of using this
    unconditionally."""
    if _oss_configured():
        # oss2 ships no type stubs, so this comes back as Any without the explicit str().
        return str(_bucket().sign_url("GET", oss_key, _SIGNED_URL_EXPIRES_SECONDS))
    return f"{settings().base_url}/media/{oss_key}"
