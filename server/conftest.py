"""Pytest configuration shared by tests/ and evals/.

The --eval flag gates every test that calls a live model API. Without it those tests are
skipped, so `pytest tests/` stays free, offline and fast on every commit.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--eval",
        action="store_true",
        default=False,
        help="run evals that call the live DashScope API (costs money, needs a key)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--eval"):
        return
    skip = pytest.mark.skip(reason="needs --eval (calls a live model API)")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)
