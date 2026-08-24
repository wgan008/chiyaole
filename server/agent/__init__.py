"""ChiYaoLe reasoning modules.

Each module is one pure function, one contract, one test set — the atomic unit of
spec-driven work (docs/spec/04-agent-modules.md).

The design rule that governs all of them:

    When a value cannot be resolved, return None / Ambiguous / Refuse.
    NEVER return the closest match.

The caller branches on that into "refuse" or "flag for the caregiver". Guessing here
silently produces a confidently wrong answer about someone's medication, which is the
one failure mode this product exists to prevent.
"""

from __future__ import annotations
