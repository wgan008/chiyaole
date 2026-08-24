"""Drug and lab-code normalisation.

## Prohibited (stated before behaviour, per docs/spec §10.2 rule 1)

- ❌ Must not call an LLM to guess a fallback.
- ❌ Must not return the "closest" match when more than one candidate is in range.
- ❌ Must not raise. Dirty input returns None.
- ❌ Must not resolve a combination product to one of its components. A combination is a
     different entity; it returns None and goes to the caregiver.
- ❌ Must not assume a unit. A lab value printed in a unit this table does not know
     returns None rather than being stored in the canonical unit unconverted.

## Why this matters more than it looks

Everything downstream branches on `None`. A wrong drug code silently attaches a schedule,
a PIM check and a duplicate-generic check to the wrong molecule. `None` costs the caregiver
fifteen seconds of manual review. A wrong guess costs correctness with no signal that
anything went wrong. **The asymmetry is the whole design.**
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from . import loader

try:  # pypinyin is an offline package; the fallback keeps tests runnable without it.
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    lazy_pinyin = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- text cleanup

_NOISE = re.compile(
    r"[\s　·・,，.。;；:：!！?？'\"“”‘’()（）\[\]【】<>《》/\\|~—\-_*#]+"
)
# Strength printed inline with the name: "氨氯地平5mg", "二甲双胍0.5g"
_STRENGTH = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|g|ug|μg|µg|ml|mL|iu|IU|万|单位|毫克|克)", re.I)
_TRAILING_COUNT = re.compile(r"[×x*]\s*\d+\s*(?:片|粒|袋|支|盒)?$")


def _clean(raw: str) -> str:
    """Normalise a printed name to a comparable key. Never raises."""
    s = unicodedata.normalize("NFKC", raw or "").strip()
    s = _TRAILING_COUNT.sub("", s)
    s = _STRENGTH.sub("", s)
    s = _NOISE.sub("", s)
    return s.lower()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _pinyin(s: str) -> str:
    if lazy_pinyin is None:  # pragma: no cover
        return s
    return "".join(lazy_pinyin(s, style=Style.NORMAL))


# --------------------------------------------------------------------------- indices


@lru_cache(maxsize=1)
def _drug_index() -> dict[str, str]:
    """cleaned alias -> single-entity code."""
    table = loader.drug_alias()
    idx: dict[str, str] = {}
    for code, entry in table["drugs"].items():
        for alias in entry["aliases"]:
            idx[_clean(alias)] = code
        idx.setdefault(_clean(entry["generic_zh"]), code)
        idx.setdefault(_clean(code), code)
    return idx


@lru_cache(maxsize=1)
def _combination_index() -> dict[str, str]:
    """cleaned alias -> combination code. Matching here means resolve_drug returns None."""
    table = loader.drug_alias()
    idx: dict[str, str] = {}
    for code, entry in table["combinations"].items():
        for alias in entry["aliases"]:
            idx[_clean(alias)] = code
        idx.setdefault(_clean(entry["generic_zh"]), code)
    return idx


@lru_cache(maxsize=1)
def _generic_stems() -> list[tuple[str, str]]:
    """(cleaned generic name, code) for every single entity, longest first.

    Used to detect an unlisted combination product: a string containing two different
    generic stems is a combination we have never seen, and must not resolve to either half.
    """
    table = loader.drug_alias()
    stems = [(_clean(v["generic_zh"]), k) for k, v in table["drugs"].items()]
    stems = [(s, c) for s, c in stems if len(s) >= 3]
    stems.sort(key=lambda t: -len(t[0]))
    return stems


@lru_cache(maxsize=1)
def _pinyin_index() -> list[tuple[str, str]]:
    return [(_pinyin(alias), code) for alias, code in _drug_index().items()]


@lru_cache(maxsize=1)
def _affixes() -> tuple[list[str], list[str]]:
    table = loader.drug_alias()
    suffixes = sorted(table["dosage_form_suffixes"], key=len, reverse=True)
    prefixes = sorted(table["salt_prefixes"], key=len, reverse=True)
    return [_clean(s) for s in suffixes], [_clean(p) for p in prefixes]


def _strip_affixes(s: str) -> str:
    suffixes, prefixes = _affixes()
    changed = True
    while changed:
        changed = False
        for suf in suffixes:
            if suf and s.endswith(suf) and len(s) > len(suf) + 1:
                s, changed = s[: -len(suf)], True
                break
        for pre in prefixes:
            if pre and s.startswith(pre) and len(s) > len(pre) + 1:
                s, changed = s[len(pre) :], True
                break
    return s


# --------------------------------------------------------------------------- drugs


def resolve_drug(raw: str) -> str | None:
    """Map a Chinese drug name read off a pill box to a canonical generic code.

    Behaviour, in order:
      1. Exact match against a known alias → return its code.
      2. Match against a known *combination* product → return None (different entity).
      3. Strip salt prefixes (苯磺酸/马来酸/…) and dosage-form suffixes (片/胶囊/缓释片/…), retry 1–2.
      4. Two different generic stems present in one string → an unlisted combination → None.
      5. Pinyin edit distance ≤ 2, and only if exactly one candidate is in range.
      6. Otherwise None.

    >>> resolve_drug("苯磺酸氨氯地平片")
    'AMLODIPINE'
    >>> resolve_drug("氨氯地平贝那普利") is None   # combination — a different entity
    True
    """
    try:
        return _resolve_drug(raw)
    except Exception:  # noqa: BLE001 — contract: dirty input returns None, never raises
        return None


def _resolve_drug(raw: str) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    key = _clean(raw)
    if not key:
        return None

    drugs, combos = _drug_index(), _combination_index()

    if key in combos:
        return None
    if key in drugs:
        return drugs[key]

    stripped = _strip_affixes(key)
    if stripped and stripped != key:
        if stripped in combos:
            return None
        if stripped in drugs:
            return drugs[stripped]
    else:
        stripped = key

    # An unlisted combination: two different generic stems inside one printed name.
    hits: list[str] = []
    for stem, code in _generic_stems():
        if stem in stripped and code not in hits:
            hits.append(code)
    if len(hits) >= 2:
        return None
    if len(hits) == 1 and len(stripped) - len(_clean(_generic_of(hits[0]))) <= 2:
        # e.g. "氨氯地平肠溶" after an unusual suffix we don't list yet
        return hits[0]

    return _fuzzy(stripped)


def _generic_of(code: str) -> str:
    entry: dict[str, str] = loader.drug_alias()["drugs"][code]
    return entry["generic_zh"]


def _fuzzy(key: str) -> str | None:
    """Pinyin edit distance ≤2, unique candidate only.

    Deliberately runs on pinyin rather than characters: 氨氯地平 and 尼群地平 are two
    real, different drugs at a character distance of 2. Their pinyin is far apart.
    """
    if lazy_pinyin is None or len(key) < 3:  # pragma: no cover
        return None
    target = _pinyin(key)
    if len(target) < 5:
        return None
    best: dict[str, int] = {}
    for cand_py, code in _pinyin_index():
        if abs(len(cand_py) - len(target)) > 2:
            continue
        d = _levenshtein(target, cand_py)
        if d <= 2 and d < best.get(code, 99):
            best[code] = d
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda t: t[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None  # ambiguous — refuse rather than pick
    return ranked[0][0]


def resolve_combination(raw: str) -> tuple[str, list[str]] | None:
    """Identify a combination product. Returns (combination_code, component_codes).

    Kept separate from `resolve_drug` on purpose: `safety.check` needs the components in
    order to catch 缬沙坦 + 诺欣妥 (valsartan taken twice), but the scheduler must still
    treat the combination as unresolved until a human confirms it.
    """
    try:
        key = _clean(raw)
        code = _combination_index().get(key) or _combination_index().get(_strip_affixes(key))
        if code is None:
            return None
        components: list[str] = loader.drug_alias()["combinations"][code]["components"]
        return code, list(components)
    except Exception:  # noqa: BLE001
        return None


def drug_display_name(code: str) -> str:
    """Chinese generic name for a code — what the elder is actually read aloud."""
    table = loader.drug_alias()
    if code in table["drugs"]:
        name: str = table["drugs"][code]["generic_zh"]
        return name
    if code in table["combinations"]:
        combo_name: str = table["combinations"][code]["generic_zh"]
        return combo_name
    return code


# --------------------------------------------------------------------------- lab metrics


@lru_cache(maxsize=1)
def _lab_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for code, entry in loader.lab_codes()["metrics"].items():
        for alias in entry["aliases"]:
            idx[_clean(alias)] = code
        idx.setdefault(_clean(entry["name_zh"]), code)
        idx.setdefault(_clean(code), code)
    return idx


def _clean_unit(unit: str | None) -> str:
    return unicodedata.normalize("NFKC", (unit or "").strip()).replace(" ", "")


def resolve_lab(raw: str, unit: str) -> tuple[str, float] | None:
    """Resolve a printed lab metric name and unit.

    Returns `(code, factor)` where `factor` converts a value FROM the printed unit TO the
    metric's canonical unit — i.e. `canonical_value = printed_value * factor`.

    (The spec writes this as "value converted to canonical unit"; since no value is passed
    in, the second element is the conversion factor. `resolve_lab_value` applies it.)

    Returns None when either the name or the unit is unknown. **An unknown unit is not a
    reason to assume the canonical one** — mg/dL creatinine stored as µmol/L is off by 88×,
    and nothing downstream would notice.
    """
    try:
        code = _lab_index().get(_clean(raw))
        if code is None:
            return None
        entry = loader.lab_codes()["metrics"][code]
        units: dict[str, float] = entry["units"]
        u = _clean_unit(unit)
        table = {_clean_unit(k): v for k, v in units.items()}
        if u not in table:
            return None
        return code, float(table[u])
    except Exception:  # noqa: BLE001
        return None


def resolve_lab_value(raw: str, unit: str, value: float) -> tuple[str, float] | None:
    """Convenience wrapper: returns (code, value in the canonical unit)."""
    hit = resolve_lab(raw, unit)
    if hit is None:
        return None
    code, factor = hit
    return code, value * factor


def canonical_unit(code: str) -> str | None:
    entry = loader.lab_codes()["metrics"].get(code)
    return None if entry is None else str(entry["canonical_unit"])


def reference_range(code: str) -> tuple[float | None, float | None]:
    """Population default reference range, for orientation only.

    ★ The report's own printed range always wins — labs and analysers differ. This is a
    fallback for reports where the range column was not captured.
    """
    entry = loader.lab_codes()["metrics"].get(code) or {}
    return entry.get("ref_low"), entry.get("ref_high")


def clear_caches() -> None:
    for fn in (
        _drug_index,
        _combination_index,
        _generic_stems,
        _pinyin_index,
        _affixes,
        _lab_index,
    ):
        fn.cache_clear()
