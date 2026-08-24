"""Orchestration for POST /api/qa.

★ The ordering in `answer()` is the safety property of this whole module:

    guard.check  →  intents.classify  →  resolve_slots  →  queries.run  →  phrase

`guard` runs FIRST, deterministically, before the model sees anything. `phrase` runs LAST
and is handed a finished result — it is a sentence generator, not a decision maker.
It never sees the elder's original question, so it cannot be talked into answering it.

## Prohibited

- ❌ `phrase` must never receive the raw utterance. Only the query result.
- ❌ No path may reach `phrase` without passing `guard`. There is exactly one entry point.
- ❌ An empty result is spoken as "I don't have that", never as a zero, never as a guess.
- ❌ A model failure refuses and escalates. It never degrades into answering from memory.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import guard, intents, queries
from .llm import LLMUnavailable, complete_text
from .normalize import canonical_unit
from .types import QaResult, QueryResult, Refuse, Slots

_PHRASE_SYSTEM = """\
你在把一条已经查好的健康数据，念给一位七八十岁的中国老人听。

规则：
- 一到两句话，口语，像家里人说话。
- 不解释这个数字意味着什么，不判断严重不严重，不给任何建议。
- 只念事实：什么时候、是多少、和上次比高了还是低了。
- 不用医学术语。不用"根据您的检验报告显示"这种书面语。
- 只输出要念的那句话，不要引号，不要解释。
"""


def answer(
    text: str,
    patient_id: str,
    *,
    session: Session,
    caregiver_name: str = "小芳",
) -> QaResult:
    """The single entry point. Nothing else may call `phrase`."""
    # 1 ── guard, first and deterministic
    refusal = guard.check(text)
    if refusal is not None:
        return _refused(refusal, caregiver_name)

    # 2 ── classify
    payload = intents.classify(text)

    # 3 ── resolve slots against the whitelist
    resolved = intents.resolve_slots(payload)
    if isinstance(resolved, Refuse):
        return _refused(resolved, caregiver_name)
    slots: Slots = resolved

    # 4 ── hand-written SQL
    try:
        result = queries.run(payload.intent, slots, patient_id, session=session)
    except KeyError:
        return _refused(Refuse(reason="OUT_OF_SCOPE", detail=payload.intent), caregiver_name)

    if result.empty:
        return QaResult(spoken=_no_data(payload.intent), intent=payload.intent)

    # 5 ── phrase, last, and blind to the original question
    return QaResult(spoken=phrase(result), intent=payload.intent)


def _refused(refusal: Refuse, caregiver: str) -> QaResult:
    from . import loader

    copy = loader.remote_config()["copy"]
    key = {
        "MED_CHANGE": "refusal_med_change",
        "SYMPTOM": "refusal_symptom",
        "UNRESOLVED_ENTITY": "unresolved_entity",
    }.get(refusal.escalate_kind or refusal.reason, "refusal_generic")
    return QaResult(
        spoken=copy[key].format(caregiver=caregiver),
        intent="OUT_OF_SCOPE",
        refused=True,
        escalation_kind=refusal.escalate_kind,
        urgency=refusal.urgency,
    )


def _no_data(intent: str) -> str:
    return {
        "metric_latest": "这个我这儿没有记录，我帮你问问",
        "metric_compare": "只有一次的数，比不了，我帮你问问",
        "abnormal_list": "最近这次化验单上，没有标出不正常的",
        "last_report": "我这儿还没有化验单",
        "med_taken_today": "今天还没有安排要吃的药",
    }.get(intent, "这个我这儿没有")


def phrase(result: QueryResult) -> str:
    """Turn a finished query result into one spoken sentence.

    ★ Receives only the result. It cannot see what was asked, so it cannot be steered into
    answering something the guard already refused.

    A deterministic sentence is built first and used as the fallback, so an unavailable
    model degrades to a plain but correct sentence rather than to silence.
    """
    baseline = _deterministic(result)
    try:
        spoken = complete_text(_facts(result), system=_PHRASE_SYSTEM).strip()
    except LLMUnavailable:
        return baseline
    return spoken or baseline


def _facts(result: QueryResult) -> str:
    lines = [f"意图：{result.intent}"]
    for i, row in enumerate(result.rows[:10]):
        parts = [f"{k}={v}" for k, v in row.items() if v is not None]
        lines.append(f"第{i + 1}条：" + "，".join(parts))
    return "\n".join(lines)


def _deterministic(result: QueryResult) -> str:
    """Plain-language fallback. Facts only — no judgement, in any branch."""
    rows: list[dict[str, Any]] = result.rows

    if result.intent == "metric_latest":
        r = rows[0]
        unit = r.get("unit") or ""
        return f"{_date(r.get('report_date'))}那次，是{_fmt(r.get('value'))}{unit}"

    if result.intent == "metric_compare":
        new, old = rows[0], rows[1]
        unit = new.get("unit") or canonical_unit(str(new.get("code") or "")) or ""
        nv, ov = _f(new.get("value")), _f(old.get("value"))
        if nv is None or ov is None:
            return "这两次的数我这儿对不上，我帮你问问"
        direction = "高了" if nv > ov else ("低了" if nv < ov else "一样")
        if direction == "一样":
            return f"和上回一样，都是{_fmt(nv)}{unit}"
        return (
            f"上回{_date(old.get('report_date'))}是{_fmt(ov)}{unit}，"
            f"这回{_date(new.get('report_date'))}是{_fmt(nv)}{unit}，{direction}"
        )

    if result.intent == "abnormal_list":
        names = "、".join(str(r.get("raw_name")) for r in rows[:5])
        return f"最近这次化验单上标出来的有：{names}"

    if result.intent == "last_report":
        r = rows[0]
        where = r.get("hospital") or ""
        what = r.get("report_type") or "化验"
        return f"最近一次是{_date(r.get('report_date'))}，在{where}做的{what}".replace("在做的", "做的")

    if result.intent == "med_taken_today":
        taken = [r for r in rows if r.get("action") == "taken"]
        pending = [r for r in rows if not r.get("action")]
        if not pending:
            return f"今天{len(rows)}次药都按过了"
        return f"今天一共{len(rows)}次，按过{len(taken)}次，还有{len(pending)}次没按"

    return "我这儿有记录，但我说不好，我帮你问问"


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: Any) -> str:
    f = _f(v)
    if f is None:
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _date(v: Any) -> str:
    s = str(v or "")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{int(s[5:7])}月{int(s[8:10])}号"
    return s
