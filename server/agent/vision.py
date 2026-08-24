"""Pill box and lab report → structured JSON.

## Prohibited

- ❌ **Confidently wrong is not permitted.** When `strength_value` is uncertain, the
     matching entry in `confidence` must be low. A wrong strength with confidence 0.95 is
     worse than no answer, because it is the one field nobody re-reads.
- ❌ Must not infer a field that is not visible. If the dosage side of the box was not
     photographed, `usage_raw` is None and "usage" goes in `missing` — which is what drives
     「请把药盒转到写用法的那面」 on the caregiver's screen.
- ❌ Must not interpret 用法. It is transcribed character for character. `schedule.synthesize`
     is the only thing allowed to turn it into times, and it refuses when it cannot.
- ❌ Must not normalise the drug name here. Raw text out; `normalize.resolve_drug` decides.

## Why this module assumes exactly one box per call, and does not try to detect otherwise

Tested against a real photo of three stacked boxes: the model filled every field
confidently — generic name from box 1, strength from box 2, manufacturer from box 3 — with
no missing fields and 0.95+ confidence throughout. A fabricated, internally-consistent
record wrong on every field, with nothing to make the caregiver double-check it.

An in-prompt guard (forcing the model to enumerate every box it saw, refusing when it
counted more than one) was built and tested against that photo — and against several
prompt rewrites, `temperature=0`, and `response_format=json_object` — and stayed unreliable
in both directions: it missed the real 3-box photo at least once, and it also flagged a
genuine single box as multiple, deterministically, because the model read the box's brand
name and generic name (two lines of text on one box) as two separate boxes. Counting
objects in a photo is a fundamentally harder visual-reasoning task than "read the text on
this one thing" — every failure was in the counting step; transcription itself was
reliable throughout.

★ The fix is upstream, not here: the caregiver capture flow requires one photo (or one
front+back pair) per medication — this was always the documented contract (see
`parse_medbox`'s docstring below) — and the enrollment UI must make that instruction
impossible to miss, not just state it once. This module trusts that contract rather than
re-deriving box count from pixels.

## Acceptance (docs/spec §7.1, §8.3)

On the 6 real boxes in `evals/boxes/`: `generic_name` and `usage_raw` must be 6/6 correct.
CI blocks on regression.
"""

from __future__ import annotations

import json
import re

from .llm import LLMUnavailable, ocr
from .types import LabItemParse, LabParse, MedboxParse

_MEDBOX_PROMPT = """\
你是药盒信息转录员。只做转录，不做任何解释、推断或补全。
这张（或这几张）图片里应该只有一盒药。

严格输出 JSON：
{
  "generic_name":   "通用名，药盒上原样的字，读不到写 null",
  "brand_name":     "商品名，读不到写 null",
  "strength_value": 规格数值，读不到写 null,
  "strength_unit":  "规格单位，读不到写 null",
  "usage_raw":      "用法用量那一行的原文，一字不改，读不到写 null",
  "manufacturer":   "生产企业，读不到写 null",
  "confidence": {"generic_name":0-1, "strength_value":0-1, "usage_raw":0-1}
}

硬性要求：
- 看不清就写 null 并把 confidence 打低。★ 绝对不许猜，不许写"可能是"。
- usage_raw 必须是原文，不许改写成"一天三次"这种规范说法。
- ★ strength_value / strength_unit 只表示"每片/每粒含多少剂量"，不包含盒子里装了多少片。
  规格常印成"每片剂量+单位×总片数+剂型"这样的格式，例如"100mg×20片"：
  strength_value 是 100（不是 20，20 是片数，不放进这两个字段）；
  strength_unit 是 "mg"（不是 "×20片"，"×20片" 是数量单位，不是剂量单位）。
  常见剂量单位只有 mg / g / ml / μg / IU 这几种，"片""粒""袋""×N片"都不是剂量单位。
- 只输出 JSON，不要任何解释文字。
"""

_LAB_PROMPT = """\
你是化验单/检查报告转录员。只做转录，不做任何解释或判断。

严格输出 JSON：
{
  "report_date": "YYYY-MM-DD，读不到写 null",
  "report_type": "报告名称，读不到写 null",
  "hospital":    "医院名称，读不到写 null",
  "items": [
    {"raw_name":"项目名原文","value":数值,"unit":"单位原文",
     "ref_low":参考范围下限或null,"ref_high":参考范围上限或null,"flag":"H/L/N 或 null"}
  ],
  "confidence": {"overall":0-1}
}

硬性要求：
- ★ 报告上出现的每一个数值都要单独列一条 item，不要只挑"看起来像标准化验单"的几行，
  也不要因为凑不出一个完整的"项目/结果/单位/参考范围"就跳过整行。
- ★ 报告如果分左右眼/双侧（OD/OS，右眼/左眼）、或者一个项目下有好几个数（比如"首次破裂
  时间"和"平均破裂时间"、"上睑"和"下睑"），每一个数字都要单独列一条 item，在 raw_name 里
  写清楚是哪一侧、哪一个子项目，例如"泪膜破裂时间(OD)首次破裂时间"、
  "泪膜破裂时间(OS)平均破裂时间"。不许把好几个数合并成一条，也不许只挑一个。
- value 必须是数字本身；括号里的英文缩写、量表代号（比如"(NIKBUT)"）不是数值，不能填进
  value —— 读不到真正的数字就把这条 value 写 null，宁可 null 也不能拿缩写充数。
- raw_name 必须是化验单上印的原字，不许换成标准名。
- ★ flag 必须是化验单上本来就印着的 H/L/N 标记，原样抄写；报告上没有印这种标记就写 null，
  不许自己根据数值判断高低。
- ★ 不许判断"这个高了要紧不要紧"。只转录数字。
- 只输出 JSON。
"""

_REQUIRED_FIELDS = ("generic_name", "strength_value", "usage_raw")


def parse_medbox(image_urls: list[str]) -> MedboxParse:
    """Read one pill box (usually 2 photos: front and the dosage side).

    Raises LLMUnavailable on a failed call. ★ Callers must surface that to the caregiver as
    "couldn't read it, try again" — never as an empty but successful-looking parse.
    """
    raw = ocr(image_urls, _MEDBOX_PROMPT)
    data = _loads(raw)

    strength_unit = _clean_strength_unit(data.get("strength_unit"))
    if strength_unit is None:
        # The unit is often glued onto strength_value itself (e.g. "0.3g") while the
        # separate strength_unit field gets unrelated label text instead (confirmed live:
        # "每粒装", the "each capsule contains" prefix — not a unit at all). Recover it from
        # the same string _num() already pulled the number out of, rather than trusting a
        # second field the model doesn't populate reliably.
        strength_unit = _unit_suffix(data.get("strength_value"))

    parse = MedboxParse(
        generic_name=data.get("generic_name"),
        brand_name=data.get("brand_name"),
        strength_value=_num(data.get("strength_value")),
        strength_unit=strength_unit,
        usage_raw=data.get("usage_raw"),
        manufacturer=data.get("manufacturer"),
        confidence=_confidence_dict(data.get("confidence")),
    )
    parse.missing = [f for f in _REQUIRED_FIELDS if getattr(parse, f) in (None, "")]
    # A field we could not read has confidence 0, never a default of 1.
    for field in parse.missing:
        parse.confidence[field] = 0.0
    return parse


def parse_lab(image_urls: list[str]) -> LabParse:
    """Read a lab report. Normalisation happens later, in `normalize.resolve_lab`."""
    from .normalize import resolve_lab_value

    raw = ocr(image_urls, _LAB_PROMPT)
    data = _loads(raw)

    items: list[LabItemParse] = []
    unresolved: list[str] = []
    for row in data.get("items") or []:
        name = str(row.get("raw_name") or "").strip()
        if not name:
            continue
        value, unit = _num(row.get("value")), row.get("unit")
        code = None
        if value is not None and unit:
            hit = resolve_lab_value(name, unit, value)
            if hit is not None:
                code, value = hit
        if code is None:
            unresolved.append(name)  # ★ recorded, never guessed at
        items.append(
            LabItemParse(
                raw_name=name,
                code=code,
                value=value,
                unit=unit,
                ref_low=_num(row.get("ref_low")),
                ref_high=_num(row.get("ref_high")),
                flag=row.get("flag") if row.get("flag") in ("H", "L", "N") else None,
            )
        )

    return LabParse(
        report_date=data.get("report_date"),
        report_type=data.get("report_type"),
        hospital=data.get("hospital"),
        items=items,
        unresolved=unresolved,
        confidence=_confidence_dict(data.get("confidence")),
    )


def _confidence_dict(v: object) -> dict[str, float]:
    """`response_format={"type": "json_object"}` guarantees valid JSON syntax, not schema
    conformance (confirmed live: one real response returned `"confidence": 0.99`, a bare
    float, where every prompt's schema asks for an object of per-field scores — an
    unguarded `.items()` on that crashes parse_medbox outright). Anything not shaped like
    a field->score mapping is treated as "no confidence info", never as an error."""
    if not isinstance(v, dict):
        return {}
    out: dict[str, float] = {}
    for k, val in v.items():
        try:
            out[k] = float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return out


def _loads(raw: str) -> dict[str, object]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"model did not return JSON: {raw[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailable(f"model returned {type(parsed).__name__}, expected an object")
    return parsed


_LEADING_NUMBER = re.compile(r"[-+]?\d+\.?\d*")


def _num(v: object) -> float | None:
    """Parses a number, tolerating a unit glued onto the string (e.g. "240mg" -> 240.0).
    ★ Code-side defense, not a substitute for prompt wording — the model does not always
    separate value and unit cleanly even when told to, so this must not be the only guard."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        match = _LEADING_NUMBER.match(v.strip())
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
    return None


# Real dosage units only — never a pack-count notation like "×7片". A box's specification
# line is commonly printed as "<dose><unit>×<count><form>" (e.g. "240mg×7片": 240 mg per
# tablet, 7 tablets in the box) and the model does not always split it cleanly on its own.
_KNOWN_STRENGTH_UNITS = {"mg", "g", "ml", "μg", "ug", "iu", "mcg"}


def _clean_strength_unit(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    candidate = v.strip()
    if candidate.lower() in _KNOWN_STRENGTH_UNITS:
        return candidate
    return None


def _unit_suffix(v: object) -> str | None:
    """Recovers a unit glued directly onto a value string (e.g. "0.3g" -> "g",
    "240 mg" -> "mg"). Only trusts a short trailing run of letters that is itself a known
    unit — never an arbitrary suffix, which would just move the "confidently wrong"
    problem from strength_unit into this function instead of fixing it."""
    if not isinstance(v, str):
        return None
    match = _LEADING_NUMBER.match(v.strip())
    if not match:
        return None
    remainder = v.strip()[match.end() :].strip()
    return _clean_strength_unit(remainder)
