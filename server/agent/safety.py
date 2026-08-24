"""Safety screening: duplicate generics, potentially inappropriate medications, interactions.

## Prohibited

- ❌ An alert must never be shown to the elder. It is addressed to the adult child only.
- ❌ An alert must never recommend a change — not "stop this", not "lower the dose",
     not "this is dangerous". It phrases a question to put to the doctor. Crossing that
     line makes this a regulated medical device (docs/spec, red line #1).
- ❌ On any hit, do NOT generate a schedule. The regimen stays in `draft`.
- ❌ Must not raise on a regimen containing unresolved (None-coded) medications.

## Why "block" and not "warn"

A warning the caregiver can click past is a warning they will click past on the day it
matters. There are three or four medications in a POC regimen; blocking costs one tap of
deliberate confirmation and makes the confirmation mean something.
"""

from __future__ import annotations

from itertools import combinations as _pairs

from . import loader
from .normalize import drug_display_name, resolve_combination, resolve_drug
from .types import Medication, SafetyAlert, SafetyAlertKind

_SLOW_RELEASE_MARKERS = ("缓释", "控释", "肠溶缓释")


def _expand(med: Medication) -> tuple[list[str], str | None]:
    """Return (component codes, combination code) for one medication.

    A combination product contributes ALL of its components to duplicate screening. That is
    what catches 缬沙坦 + 诺欣妥 — valsartan twice, in two boxes that share no name.
    """
    raw = med.generic_name or med.brand_name or ""
    if med.generic_code:
        combos = loader.drug_alias()["combinations"]
        if med.generic_code in combos:
            return list(combos[med.generic_code]["components"]), med.generic_code
        return [med.generic_code], None

    combo = resolve_combination(raw)
    if combo is not None:
        combo_code, components = combo
        return components, combo_code

    code = resolve_drug(raw)
    return ([code] if code else []), None


def _class_of(code: str) -> str | None:
    entry = loader.drug_alias()["drugs"].get(code)
    return None if entry is None else str(entry.get("class") or "") or None


def check(meds: list[Medication]) -> list[SafetyAlert]:
    """Screen a whole regimen. Any returned alert blocks activation."""
    alerts: list[SafetyAlert] = []
    expanded: list[tuple[Medication, list[str], str | None]] = []
    for m in meds:
        codes, combo = _expand(m)
        expanded.append((m, codes, combo))

    alerts += _duplicate_generic(expanded)
    alerts += _pim(expanded)
    alerts += _interactions(expanded)
    return alerts


# --------------------------------------------------------------------------- duplicates


def _duplicate_generic(
    expanded: list[tuple[Medication, list[str], str | None]],
) -> list[SafetyAlert]:
    owners: dict[str, list[str]] = {}
    for med, codes, _combo in expanded:
        label = med.brand_name or med.generic_name or "(未识别)"
        for code in codes:
            owners.setdefault(code, []).append(label)

    out: list[SafetyAlert] = []
    for code, labels in owners.items():
        if len(labels) < 2:
            continue
        name = drug_display_name(code)
        unique_labels = list(dict.fromkeys(labels))
        if len(unique_labels) == 1:
            # Same label N times isn't a formatting glitch — it's N separate boxes that all
            # read out identically, most often because the same box got photographed and
            # confirmed more than once. Say the count explicitly instead of repeating the
            # name, which reads like a bug.
            message = (
                f"有 {len(labels)} 盒都叫「{unique_labels[0]}」，都含{name}，"
                f"可能是同一盒药拍重了，也可能是真的买了两份"
            )
        else:
            message = f"「{'」和「'.join(unique_labels)}」里都含{name}，可能重复用药"
        out.append(
            SafetyAlert(
                kind=SafetyAlertKind.DUPLICATE_GENERIC,
                codes=[code],
                message=message,
                ask_doctor=f"这些药都含{name}，是不是本来就该一起吃？请医生确认一次",
                level="high",
            )
        )
    return out


# --------------------------------------------------------------------------- PIM


def _pim(expanded: list[tuple[Medication, list[str], str | None]]) -> list[SafetyAlert]:
    entries = loader.pim_list()["entries"]
    by_code = {e["code"]: e for e in entries}
    out: list[SafetyAlert] = []
    seen: set[str] = set()

    for med, codes, combo in expanded:
        candidates = list(codes) + ([combo] if combo else [])
        text = " ".join(filter(None, [med.generic_name, med.brand_name, med.usage_raw]))
        for code in candidates:
            entry = by_code.get(code)
            if entry is None or code in seen:
                continue
            form = entry.get("conditional_on_form")
            if form == "immediate_release" and any(m in text for m in _SLOW_RELEASE_MARKERS):
                continue  # the slow-release form is not the PIM
            seen.add(code)
            out.append(
                SafetyAlert(
                    kind=SafetyAlertKind.PIM_HIT,
                    codes=[code],
                    message=f"{entry['name_zh']}：{entry['concern']}",
                    ask_doctor=entry.get("ask_doctor", ""),
                    level=entry.get("level", "high"),
                )
            )
    return out


# --------------------------------------------------------------------------- interactions


def _interactions(
    expanded: list[tuple[Medication, list[str], str | None]],
) -> list[SafetyAlert]:
    data = loader.interactions()
    present: dict[str, str] = {}
    for med, codes, _combo in expanded:
        for code in codes:
            present.setdefault(code, med.brand_name or med.generic_name or code)

    out: list[SafetyAlert] = []
    for pair in data["pairs"]:
        a, b = pair["codes"]
        if a in present and b in present:
            out.append(
                SafetyAlert(
                    kind=SafetyAlertKind.INTERACTION,
                    codes=[a, b],
                    message=f"{drug_display_name(a)} + {drug_display_name(b)}：{pair['concern']}",
                    ask_doctor=pair.get("ask_doctor", ""),
                    level=pair.get("level", "high"),
                )
            )

    # Class-level rules, e.g. two NSAIDs, ACEI + ARB.
    by_class: dict[str, list[str]] = {}
    for code in present:
        cls = _class_of(code)
        if cls:
            by_class.setdefault(cls, []).append(code)

    for rule in data["class_rules"]:
        c1, c2 = rule["classes"]
        if c1 == c2:
            members = by_class.get(c1, [])
            hits = list(_pairs(sorted(members), 2))
        else:
            hits = [(x, y) for x in by_class.get(c1, []) for y in by_class.get(c2, [])]
        for x, y in hits:
            out.append(
                SafetyAlert(
                    kind=SafetyAlertKind.INTERACTION,
                    codes=[x, y],
                    message=(
                        f"{drug_display_name(x)} + {drug_display_name(y)}：{rule['concern']}"
                    ),
                    ask_doctor=rule.get("ask_doctor", ""),
                    level=rule.get("level", "high"),
                )
            )

    # Deduplicate: a pair caught by both an explicit entry and a class rule appears once.
    unique: dict[frozenset[str], SafetyAlert] = {}
    for alert in out:
        unique.setdefault(frozenset(alert.codes), alert)
    return list(unique.values())


def blocks_activation(alerts: list[SafetyAlert]) -> bool:
    """Any alert at all blocks. Kept as a named function so the rule is greppable."""
    return bool(alerts)
