"""Chains the real agent/ pipeline against real photos: vision -> normalize -> safety ->
(simulated caregiver confirmation) -> schedule. Not the HTTP API (server/app has no routes
yet) — this calls the same pure functions the API would call, directly.

Usage:
    DASHSCOPE_API_KEY=... .venv/bin/python scripts/test_pipeline.py \\
        "6014.JPG,6015.JPG" "6019.JPG,6020.JPG" "6023.JPG,6024.JPG"

Each argument is one medication: a comma-separated list of photo paths (front[,back]).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import normalize, safety, schedule  # noqa: E402
from agent.llm import LLMUnavailable  # noqa: E402
from agent.types import Ambiguous, DailyRoutine, MedStatus, Medication  # noqa: E402
from agent.vision import parse_medbox  # noqa: E402


def build_medication(photo_group: str) -> Medication:
    paths = [Path(p).resolve() for p in photo_group.split(",")]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)
    image_urls = [f"file://{p}" for p in paths]

    parsed = parse_medbox(image_urls)
    generic_code = normalize.resolve_drug(parsed.generic_name or parsed.brand_name or "")

    return Medication(
        generic_code=generic_code,
        generic_name=parsed.generic_name,
        brand_name=parsed.brand_name,
        strength_value=parsed.strength_value,
        strength_unit=parsed.strength_unit,
        usage_raw=parsed.usage_raw,
    ), parsed


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    print(f"=== Step 1: vision.parse_medbox + normalize.resolve_drug ({len(argv)} medication(s)) ===\n")
    meds: list[Medication] = []
    parses = []
    for i, group in enumerate(argv, 1):
        try:
            med, parsed = build_medication(group)
        except LLMUnavailable as exc:
            print(f"[{i}] ✗ vision call failed: {exc}")
            return 1
        meds.append(med)
        parses.append(parsed)
        resolved = f"-> {med.generic_code}" if med.generic_code else "-> UNRESOLVED (None, never guessed)"
        print(f"[{i}] {parsed.generic_name!r} / {parsed.strength_value}{parsed.strength_unit or '?'} {resolved}")
        if parsed.missing:
            print(f"    ⚠ missing: {parsed.missing}")

    print(f"\n=== Step 2: safety.check across the whole regimen ({len(meds)} medication(s)) ===\n")
    alerts = safety.check(meds)
    if not alerts:
        print("No alerts.")
    else:
        for a in alerts:
            print(f"⚠ {a.kind.value}: {a.message}")
            print(f"   ask_doctor: {a.ask_doctor}")
    blocked = safety.blocks_activation(alerts)
    print(f"\nblocks_activation = {blocked}")

    print("\n=== Step 3: simulated caregiver confirmation ===\n")
    if blocked:
        print("★ Blocked — per spec, none of these are auto-confirmed. A human resolves the")
        print("  alert first (docs/spec red line #2: AI parses, caregiver confirms, only then active).")
    else:
        for med, parsed in zip(meds, parses, strict=True):
            med.status = MedStatus.ACTIVE
            med.confirmed_at = datetime.now()
            print(f"✓ confirmed: {parsed.generic_name} (is_active={med.is_active})")

    print("\n=== Step 4: schedule.synthesize for each confirmed medication (today) ===\n")
    routine = DailyRoutine()
    for med, parsed in zip(meds, parses, strict=True):
        if not med.is_active:
            print(f"[{parsed.generic_name}] skipped — not confirmed active")
            continue
        result = schedule.synthesize(med, routine)
        if isinstance(result, Ambiguous):
            print(f"[{parsed.generic_name}] Ambiguous({result.reason}) — raw: {result.raw!r}")
        else:
            times = ", ".join(t.strftime("%H:%M") for t in result)
            print(f"[{parsed.generic_name}] {len(result)} dose(s) today: {times}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
