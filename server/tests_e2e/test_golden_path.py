"""Browser-driven golden-path E2E test: photo upload -> parse -> caregiver confirms ->
schedule exists. This is the core of the canonical flow CLAUDE.md names as the product's
end-to-end loop — photo → parse → caregiver confirms → schedule → alarm.

(An earlier version of this test also covered a voice-question refusal creating an
escalation, the caregiver replying via the web app, and the device seeing the reply. That
whole loop — POST /api/asr, POST /api/qa, the escalations inbox — was built, wired end to
end, and then deliberately removed: see app/api/device.py and app/api/caregiver.py's module
docstrings for why.)

The web app side is driven through a real Chromium page (Playwright). The elder Android
device isn't available in this environment (no emulator/hardware here — see
docs/testing/manual_e2e.md for the physical-device procedure), so its half of the loop is
simulated with the exact same HTTP calls net/ApiService.kt makes: `X-Device-Token` header,
same routes, same request bodies.

agent/llm.py is stubbed (not a live DashScope call) for the vision step — deterministic and
free, matching evals/boxes/001_amoxicillin/truth.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from agent import vision
from app.models import Caregiver, Patient

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "evals" / "boxes" / "001_amoxicillin"
TRUTH = json.loads((FIXTURE_DIR / "truth.json").read_text())


@pytest.fixture()
def seeded(live_server, monkeypatch):  # type: ignore[no-untyped-def]
    base_url, session_factory = live_server

    db = session_factory()
    patient = Patient(display_name="王阿姨")
    db.add(patient)
    db.flush()
    caregiver = Caregiver(
        patient_id=patient.id,
        called_by="小芳",
        relation="daughter",
        phone="13800000000",
        access_token="e2e-test-token",
    )
    db.add(caregiver)
    db.commit()
    patient_id, token = patient.id, caregiver.access_token
    db.close()

    monkeypatch.setattr(
        vision,
        "ocr",
        lambda image_urls, prompt: json.dumps(
            {
                "generic_name": TRUTH["generic_name"],
                "strength_value": TRUTH["strength_value"],
                "strength_unit": TRUTH["strength_unit"],
                "usage_raw": TRUTH["usage_raw"],
                "confidence": {"generic_name": 0.99, "strength_value": 0.95, "usage_raw": 0.9},
            }
        ),
    )

    return base_url, patient_id, token


def test_golden_path(page: Page, seeded: tuple[str, str, str]) -> None:
    base_url, patient_id, token = seeded

    # ── 1. Caregiver photographs one box and identifies it (wireframe D1) ───────────
    page.goto(f"{base_url}/web/{patient_id}/upload?t={token}")
    # D1a: the entry screen offers 拍药盒/拍药袋标签/拍化验单 before the capture UI appears.
    page.click("#choiceBox")
    # The visible "拍下一盒" tile just opens this file input — Playwright targets the
    # (hidden) input directly, same as a real file picker would hand back a file.
    page.set_input_files("#fileInput", str(FIXTURE_DIR / "front.jpg"))
    page.click("#identifyBtn")
    expect(page.locator("#summary")).to_contain_text(TRUTH["generic_name"], timeout=15_000)
    page.click("#summary a.btn")

    # ── 2. Caregiver confirms it in the step wizard (wireframe D2) ──────────────────
    wizard = page.locator("#wizard")
    expect(wizard).to_be_visible(timeout=10_000)
    # ★ Field values live in <input value=...>, which Playwright's text-content matchers
    # don't read (that's the *attribute*, not rendered text content) — assert on the input.
    expect(wizard.locator(".f-generic_name")).to_have_value(TRUTH["generic_name"])
    # Every field checkbox must be explicitly checked — strength/dosage starts unchecked
    # on purpose (spec: never an accepted default) — before the confirm button enables.
    for checkbox in wizard.locator(".f-check").all():
        checkbox.check()
    confirm_btn = wizard.locator("#confirmStepBtn")
    expect(confirm_btn).to_be_enabled()
    confirm_btn.click()
    # The step disappears once confirmed (the next unconfirmed item would slide into its
    # place) — with only one medication in this test, the wizard now reports none left.
    expect(wizard).to_contain_text("没有待确认的药了", timeout=10_000)

    # ── 3. A schedule now exists — verified the way the Android app would see it ────
    device_headers = {"X-Device-Token": patient_id}
    schedule_resp = httpx.get(
        f"{base_url}/api/schedule",
        params={"since": "2020-01-01T00:00:00"},
        headers=device_headers,
    )
    assert schedule_resp.status_code == 200
    items = schedule_resp.json()["items"]
    assert items, "confirming a medication should have generated at least one dose"
    assert items[0]["generic_name"] == TRUTH["generic_name"]
