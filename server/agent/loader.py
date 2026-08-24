"""Reference-data loading.

All four JSON tables in `data/` are loaded once, at first use, and cached. They are read-only
at runtime; editing them requires a redeploy (except remote_config.json, which the elder device
re-fetches daily — see §remote_config).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    """Locate the repository's `data/` directory.

    Overridable with CHIYAOLE_DATA_DIR so tests and the Docker image can point elsewhere.
    """
    env = os.environ.get("CHIYAOLE_DATA_DIR")
    if env:
        return Path(env)
    # server/agent/loader.py -> server/agent -> server -> repo root
    return Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict[str, Any]:
    path = data_dir() / name
    if not path.exists():
        raise FileNotFoundError(
            f"Reference table {name} not found at {path}. "
            "Set CHIYAOLE_DATA_DIR if the data/ directory lives elsewhere."
        )
    with path.open(encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
    return result


def drug_alias() -> dict[str, Any]:
    return _load("drug_alias.json")


def lab_codes() -> dict[str, Any]:
    return _load("lab_codes.json")


def pim_list() -> dict[str, Any]:
    return _load("pim_cn_2017.json")


def interactions() -> dict[str, Any]:
    return _load("interactions.json")


def remote_config() -> dict[str, Any]:
    return _load("remote_config.json")


def clear_cache() -> None:
    """Drop cached tables. Tests use this after monkeypatching CHIYAOLE_DATA_DIR."""
    _load.cache_clear()
