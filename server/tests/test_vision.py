"""Offline unit tests for agent.vision — stubs agent.vision.ocr so no network call happens
(conftest's --eval gate is for the live-API evals; this file never needs it).

★ Box-counting / multi-product detection is deliberately not tested here — it was tried
as an in-prompt guard and removed (see agent/vision.py module docstring) because it stayed
unreliable in both directions under real testing. The fix lives upstream, in the caregiver
capture flow requiring one photo per medication."""

from __future__ import annotations

import json

from agent import vision


def test_single_product_parses_normally(monkeypatch):
    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "generic_name": "阿利沙坦酯片",
                "brand_name": "信立坦",
                "strength_value": 240,
                "strength_unit": "mg",
                "usage_raw": "每天一次240mg",
                "manufacturer": "深圳信立泰药业股份有限公司",
                "confidence": {"generic_name": 0.99, "strength_value": 0.95, "usage_raw": 0.99},
            }
        ),
    )

    result = vision.parse_medbox(["file:///fake/a.jpg"])

    assert result.generic_name == "阿利沙坦酯片"
    assert result.strength_value == 240.0
    assert result.missing == []


def test_strength_value_with_glued_unit_is_still_parsed(monkeypatch):
    """Regression test for the real failure on data/test_photos/5982.JPG: the model
    returned strength_value as the string "240mg" (unit glued to the number) and dumped
    the leftover pack-count notation "×7片" into strength_unit. float("240mg") raises, so
    this silently produced strength_value=None despite 240mg being printed clearly on the
    box. `_num` recovers the leading number; `_clean_strength_unit` discards a unit that
    isn't a real dosage unit rather than pass "×7片" through as if it were mg; `_unit_suffix`
    then recovers "mg" from the same glued strength_value string instead of giving up."""
    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "generic_name": "阿利沙坦酯片",
                "strength_value": "240mg",
                "strength_unit": "×7片",
                "usage_raw": "对大多数病人,通常起始和维持剂量为每天一次240mg",
                "confidence": {"generic_name": 0.99, "strength_value": 1.0, "usage_raw": 0.99},
            }
        ),
    )

    result = vision.parse_medbox(["file:///fake/a.jpg"])

    assert result.strength_value == 240.0
    assert result.strength_unit == "mg"  # recovered from strength_value, not from "×7片"
    assert "strength_value" not in result.missing


def test_bogus_unit_alone_never_leaks_through(monkeypatch):
    """When strength_value has no glued unit to recover from AND strength_unit is
    garbage, the result must be None — never fabricate a unit from nothing."""
    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "generic_name": "阿利沙坦酯片",
                "strength_value": 240,
                "strength_unit": "×7片",
                "usage_raw": "每天一次240mg",
            }
        ),
    )

    result = vision.parse_medbox(["file:///fake/a.jpg"])

    assert result.strength_value == 240.0
    assert result.strength_unit is None


def test_confidence_tolerates_malformed_shape(monkeypatch):
    """Regression test: response_format=json_object was tried and one real response came
    back with "confidence": 0.99 (a bare float) where every prompt's schema asks for an
    object of per-field scores. An unguarded `.items()` on that crashes parse_medbox
    outright. Malformed confidence must degrade to "no info", never an exception."""
    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "generic_name": "阿利沙坦酯片",
                "strength_value": 240,
                "usage_raw": "每天一次240mg",
                "confidence": 0.99,  # malformed: a bare float, not a field->score object
            }
        ),
    )

    result = vision.parse_medbox(["file:///fake/a.jpg"])

    assert result.generic_name == "阿利沙坦酯片"
    assert result.missing == []
    # The malformed top-level "confidence" contributes nothing (degrades to {}), and
    # every required field was present, so nothing gets force-zeroed either.
    assert result.confidence == {}
