"""Intent classification and slot resolution.

★ **This is deliberately NOT text-to-SQL.** The model picks one of six enum values and
fills named slots. It never writes a query, never names a table, never chooses which rows
come back. A model that can emit SQL against a patient's record can, on a bad day, emit
the wrong patient's record or a query nobody reviewed. Six enums and a whitelist cannot.

## Prohibited

- ❌ Must not accept an intent outside `INTENTS`. Anything else becomes OUT_OF_SCOPE.
- ❌ Must not resolve a metric name by similarity. `resolve_slots` uses the same whitelist
     as `normalize.resolve_lab`; a miss returns `Refuse(UNRESOLVED_ENTITY)`.
     ★ 「我那个尿酸」 with no uric-acid result on file must refuse — never substitute
     a nearby metric.
- ❌ Must not run before `guard.check`. See `qa.answer` for the enforced ordering.
- ❌ Must not fall back to a default intent when the model is unavailable. No model,
     no answer: refuse and escalate.
"""

from __future__ import annotations

from .llm import LLMUnavailable, complete_json
from .normalize import _clean, _lab_index  # whitelist lookup, shared with normalize
from .types import INTENTS, IntentPayload, Refuse, Slots

_SYSTEM = """\
你是一个意图分类器。输入是一位中国老人对自己健康数据的口语提问。
你只能输出 JSON，只能从下面 6 个意图里选一个：

  metric_latest    问某个指标最近一次的值        例：「肌酐是多少来着」
  metric_compare   问某个指标和上次比            例：「血糖比上回高了没」
  abnormal_list    问哪些指标不正常              例：「有哪些不正常的」
  last_report      问最近一次化验是什么时候/哪家  例：「上回化验是啥时候」
  med_taken_today  问今天吃药了没                例：「我今天吃药了没」
  OUT_OF_SCOPE     其他一切

★ 只要涉及【改剂量、停药、加药】或【身体不舒服的症状】，一律 OUT_OF_SCOPE。
★ 不确定就选 OUT_OF_SCOPE。宁可多拒绝，不可答错。

输出格式：
{"intent":"...","slots":{"metric":"原话里提到的指标名，没有就空字符串","period":"","n":""},
 "confidence":0-1}
只输出 JSON。"""


def classify(text: str) -> IntentPayload:
    """Classify one utterance. Never raises; an unavailable model yields OUT_OF_SCOPE.

    ★ Failure biases toward refusal, not toward answering. That direction is the whole
    reason this function does not raise.
    """
    if not text or not text.strip():
        return IntentPayload(intent="OUT_OF_SCOPE", confidence=1.0)
    try:
        data = complete_json(text.strip(), system=_SYSTEM)
    except LLMUnavailable:
        return IntentPayload(intent="OUT_OF_SCOPE", confidence=0.0)

    intent = str(data.get("intent") or "")
    if intent not in INTENTS:
        intent = "OUT_OF_SCOPE"
    slots = data.get("slots") or {}
    raw_slots = {str(k): str(v) for k, v in slots.items() if v not in (None, "")}
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return IntentPayload(intent=intent, raw_slots=raw_slots, confidence=confidence)  # type: ignore[arg-type]


def resolve_slots(payload: IntentPayload) -> Slots | Refuse:
    """Whitelist lookup. An unresolved entity refuses — it never falls back to a neighbour.

    >>> resolve_slots(IntentPayload(intent="metric_latest", raw_slots={"metric": "肌酐"}))
    Slots(metric_code='CREA', period=None, n=None)
    """
    if payload.intent == "OUT_OF_SCOPE":
        return Refuse(reason="OUT_OF_SCOPE", detail="classifier returned OUT_OF_SCOPE")

    slots = Slots()

    if payload.intent in ("metric_latest", "metric_compare"):
        raw = payload.raw_slots.get("metric", "")
        code = _lab_index().get(_clean(raw)) if raw else None
        if code is None:
            # ★ 「我那个尿酸」 with nothing on file lands here. Refuse; do not offer 血糖.
            return Refuse(
                reason="UNRESOLVED_ENTITY",
                detail=raw,
                escalate_kind="UNRESOLVED_ENTITY",
                urgency=4,
            )
        slots.metric_code = code

    period = payload.raw_slots.get("period")
    if period:
        slots.period = period

    n_raw = payload.raw_slots.get("n")
    if n_raw:
        try:
            slots.n = int(n_raw)
        except ValueError:
            slots.n = None

    return slots
