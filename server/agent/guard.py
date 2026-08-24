"""The refusal guardrail.

★ **This runs BEFORE the classifier and BEFORE any phrasing.** The ordering is the point:
a guard bolted on after an answer has been generated is a guard that has already lost.
See docs/spec §7.5 and §10.3 — the guard is written before `qa.py` exists, deliberately.

## Prohibited

- ❌ Must never let a request about **changing a dose, stopping a medication, or a symptom**
     reach the answering path. Not "answer carefully" — not answered at all.
- ❌ Must never depend on an LLM for the refusal decision. A model that is right 99% of the
     time is wrong once every hundred questions, and the wrong one is a medical-advice leak.
     The model may only *add* refusals on top of this deterministic layer, never remove one.
- ❌ Must never rewrite the elder's words before escalating. `utterance_raw` is verbatim:
     the adult child needs to hear what was actually said, including the hesitation.

## The asymmetry that governs the thresholds

Intent classification may miss 5% (spec §8.4). Refusal may not miss a single case.
The first is a UX problem; the second is a safety incident. So this layer is intentionally
over-eager: a false refusal costs one escalation to the daughter, who can answer it in ten
seconds. A false pass costs the thing this product exists to prevent.
"""

from __future__ import annotations

import re

from .types import Refuse

# --------------------------------------------------------------------- refusal patterns
#
# Written as co-occurrence rules rather than one large regex, because real speech puts
# filler between the body part and the sensation: 「胸口有点闷」「头有点晕」「肚子这两天有点疼」.
# A pattern that only matches 「胸闷」 passes all three of those straight through to the
# answering path. That is precisely the miss this layer may not have.

_WINDOW = 6  # chars of filler tolerated between a body part and a sensation

# Red flags — urgency 1. These interrupt everything and page the caregiver immediately.
_RED_FLAG = [
    r"喘不(?:上|过)来?气", r"呼吸(?:困难|费劲)", r"上不来气",
    r"心慌", r"心悸", r"心跳(?:得)?(?:快|乱|厉害)",
    r"晕(?:倒|厥)", r"摔(?:倒|跤|了|着)", r"跌倒", r"站不(?:稳|起来?)", r"起不来",
    r"说不(?:出|了)话", r"嘴歪", r"半边(?:身子|脸)?(?:麻|没劲|不好使|动不了)",
    r"吐血", r"便血", r"黑便", r"大出血", r"血止不住",
    r"抽搐", r"意识不清", r"叫不醒",
]

# Chest and heart sensations are red flags even when phrased mildly.
_RED_BODY = r"胸(?:口|部|前)?|心口|心窝"
_RED_FEEL = r"闷|疼|痛|难受|发紧|发闷|压得慌|堵"

# Everything else symptomatic — urgency 2.
_SYMPTOM_STANDALONE = [
    r"不舒服", r"难受", r"恶心", r"想吐", r"呕吐",
    r"拉肚子", r"腹泻", r"便秘", r"浮肿", r"水肿",
    r"发(?:烧|热)", r"睡不着", r"失眠", r"没(?:有)?(?:力气|劲|胃口)", r"吃不下",
    r"手抖", r"发抖", r"出虚汗", r"盗汗", r"耳鸣",
    r"看不清", r"眼花", r"血压(?:高|低)得?厉害", r"血糖(?:高|低)得?厉害", r"低血糖",
]
_BODY = (
    r"头|肚子|腹部|肚|后背|背|腰|腿|脚|胳膊|手|嗓子|喉咙|眼睛|耳朵|"
    r"关节|膝盖|身上|浑身|全身|脖子|肩膀"
)
_FEEL = r"疼|痛|难受|晕|胀|麻|酸|痒|不舒服|没劲|没力气|发沉|发木|肿"

# Medication changes — urgency 2. Never answered, always escalated.
_MED_CHANGE_PHRASES = [
    r"停(?:药|了|一下|掉|几天|一?[片粒颗袋])",
    r"(?:能不能|可不可以|要不要|该不该|可以)?不吃(?:了|药|这个)",
    r"(?:加|减|多吃|少吃|多来|少来)(?:一?[片粒颗袋]|药|量|点)",
    r"(?:加|减)(?:大|到|半|量|倍)", r"翻倍", r"加倍", r"减半",
    r"吃(?:两|三|2|3|半)\s*[片粒颗袋]",
    r"(?:换|改)(?:个|成|一)?(?:药|别的)",
    r"剂量.{0,4}(?:改|调|加|减|变)", r"(?:改|调|加|减).{0,4}剂量",
    r"要不要(?:接着|继续)?吃", r"还(?:要|用)(?:不)?(?:要|用)?(?:接着|继续)?吃",
    r"能不能少吃", r"能不能多吃", r"漏(?:吃|了).{0,4}(?:要不要|补|怎么办)",
]

# Requests for a diagnosis or a severity judgement — refused, escalated as SYMPTOM.
_DIAGNOSIS = [
    r"(?:我)?(?:这是|得了|是不是得了|会不会是)(?:什么病|癌|肿瘤|中风|脑梗|心梗)",
    r"什么病", r"严不严重", r"要不要紧", r"严重(?:吗|不严重)",
    r"要不要去医院", r"用不用看医生", r"要不要看医生", r"该看什么科",
    r"会不会(?:死|瘫|中风|出事)", r"能治好吗", r"能不能治",
    r"(?:这个|那个)?(?:数值|指标|结果).{0,6}(?:严重|危险|要紧|正常吗|好不好|说明什么)",
    r"说明(?:什么|啥)", r"意味着什么", r"为什么会(?:这样|这么高|这么低)",
]

# Supply — refused as out of scope, escalated so the child can act. Urgency 3.
_STOCK = [
    r"药(?:快)?(?:没|吃完|用完)了", r"药盒空了", r"没药了",
    r"该去(?:开|拿|买|取)药", r"去医院(?:开|拿|取)药", r"药不够了",
]


def _any(patterns: list[str], s: str) -> bool:
    return any(re.search(p, s) for p in patterns)


def _cooccur(body: str, feel: str, s: str) -> bool:
    """True if a body part is followed by a sensation within _WINDOW chars of filler."""
    return re.search(rf"(?:{body}).{{0,{_WINDOW}}}?(?:{feel})", s) is not None


def check(text: str) -> Refuse | None:
    """Return a `Refuse` if this utterance must not be answered, else None.

    ★ The caller MUST call this before `intents.classify` and before any phrasing.
    `qa.answer` enforces the ordering; nothing else should be calling the classifier.

    Evaluated in urgency order — a sentence containing both a symptom and a dose question
    is triaged as the symptom.

    >>> check("我这个药能不能加一片").escalate_kind
    'MED_CHANGE'
    >>> check("我今天胸口有点闷").urgency
    1
    >>> check("肌酐是多少来着") is None
    True
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None

    def refuse(reason: str, kind: str, urgency: int) -> Refuse:
        return Refuse(
            reason=reason,  # type: ignore[arg-type]
            detail=s,  # ★ verbatim, never rewritten
            escalate_kind=kind,
            urgency=urgency,
        )

    if _any(_RED_FLAG, s) or _cooccur(_RED_BODY, _RED_FEEL, s):
        return refuse("SYMPTOM", "SYMPTOM", 1)

    if _any(_SYMPTOM_STANDALONE, s) or _cooccur(_BODY, _FEEL, s):
        return refuse("SYMPTOM", "SYMPTOM", 2)

    if _any(_MED_CHANGE_PHRASES, s):
        return refuse("MED_CHANGE", "MED_CHANGE", 2)

    if _any(_DIAGNOSIS, s):
        return refuse("OUT_OF_SCOPE", "SYMPTOM", 2)

    if _any(_STOCK, s):
        return refuse("OUT_OF_SCOPE", "OUT_OF_STOCK", 3)

    return None


def is_out_of_scope(text: str) -> bool:
    """Convenience predicate used by the eval harness."""
    return check(text) is not None
