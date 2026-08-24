"""Thin DashScope wrapper — the ONLY place in the codebase that talks to a model.

Isolated on purpose: every test in `tests/` runs offline because it stubs this module.
Anything that needs a network call to be exercised belongs in `evals/`, behind --eval.

Model tiers (docs/spec §2): the LLM only classifies intent and phrases an already-computed
answer. It never selects data, never does arithmetic on a lab value, and never decides
whether something is safe. `qwen-plus` is therefore sufficient — a frontier model would not
change a single output that matters here.
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_TEXT_MODEL = "qwen-plus"
DEFAULT_VISION_MODEL = "qwen-vl-ocr"
DEFAULT_ASR_MODEL = "qwen3-asr-flash"


class LLMUnavailable(RuntimeError):
    """No API key, or the call failed.

    ★ Callers must treat this as "refuse and escalate", never as "answer without the model".
    """


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise LLMUnavailable("DASHSCOPE_API_KEY is not set")
    return key


def complete_json(
    prompt: str,
    *,
    system: str = "",
    model: str = DEFAULT_TEXT_MODEL,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Constrained JSON completion. Raises LLMUnavailable rather than returning a guess."""
    try:
        import dashscope  # imported lazily so the package is optional in dev
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("dashscope is not installed") from exc

    dashscope.api_key = _api_key()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    try:
        resp = dashscope.Generation.call(
            model=model,
            messages=messages,
            result_format="message",
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        text = resp.output.choices[0].message.content  # type: ignore[union-attr]
        parsed: dict[str, Any] = json.loads(text)
        return parsed
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"{model} call failed: {exc}") from exc


def complete_text(
    prompt: str,
    *,
    system: str = "",
    model: str = DEFAULT_TEXT_MODEL,
    temperature: float = 0.2,
) -> str:
    try:
        import dashscope
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("dashscope is not installed") from exc

    dashscope.api_key = _api_key()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    try:
        resp = dashscope.Generation.call(
            model=model, messages=messages, result_format="message", temperature=temperature
        )
        return str(resp.output.choices[0].message.content)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"{model} call failed: {exc}") from exc


def ocr(image_urls: list[str], prompt: str, *, model: str = DEFAULT_VISION_MODEL) -> str:
    try:
        import dashscope
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("dashscope is not installed") from exc

    dashscope.api_key = _api_key()
    content: list[dict[str, Any]] = [{"image": u} for u in image_urls]
    content.append({"text": prompt})
    try:
        resp = dashscope.MultiModalConversation.call(
            model=model,
            messages=[{"role": "user", "content": content}],
            # ★ This call was never pinned to a fixed temperature, i.e. every property of
            # its output — box count judgment included — has always had sampling noise on
            # top of it. Confirmed live: the exact same photo, same prompt, produced a
            # correct single-box read on one call and an incorrect two-box read (treating
            # a box's brand name and generic name as separate boxes) on another. temperature=0
            # doesn't guarantee determinism (Alibaba's own docs note float non-associativity
            # can still cause drift) but removes the deliberate randomness this call never
            # needed — nothing here benefits from creative variation between calls.
            temperature=0,
        )
        # ★ Deliberately NOT response_format={"type": "json_object"}. Tried it (2026-08):
        # it guarantees syntactically valid JSON but not schema conformance, and in
        # practice it made the model consistently nest a full structured record inside
        # products_seen[0] instead of the plain description string agent/vision.py's
        # multi-box guard depends on — regardless of actual box count. That destabilised
        # the safety-critical guard for a marginal win (no more markdown-fence wrapping),
        # which _loads() below already strips anyway. If re-attempting this, re-verify
        # against a real multi-box photo, not just a clean single-box one.
        parts = resp.output.choices[0].message.content  # type: ignore[union-attr]
        if isinstance(parts, list):
            return "".join(p.get("text", "") for p in parts)
        return str(parts)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"{model} call failed: {exc}") from exc


def transcribe(audio_url: str, *, bias_terms: list[str] | None = None,
               model: str = DEFAULT_ASR_MODEL) -> tuple[str, float]:
    """ASR, biased with THIS patient's own drug names.

    Biasing matters more than model choice here: an elder saying 「络活喜」 in a regional
    accent is transcribed reliably only when the decoder already knows that word is likely.
    """
    try:
        import dashscope
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("dashscope is not installed") from exc

    dashscope.api_key = _api_key()
    try:
        kwargs: dict[str, Any] = {}
        if bias_terms:
            kwargs["vocabulary"] = bias_terms
        resp = dashscope.MultiModalConversation.call(
            model=model,
            messages=[{"role": "user", "content": [{"audio": audio_url}]}],
            **kwargs,
        )
        parts = resp.output.choices[0].message.content  # type: ignore[union-attr]
        text = "".join(p.get("text", "") for p in parts) if isinstance(parts, list) else str(parts)
        return text, 1.0
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"{model} call failed: {exc}") from exc
