"""Safety filtering for complete and incrementally streamed dialogue."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

RISK_PATTERNS = [
    r"我是.{0,3}(AI|ai|人工智能|语言模型|机器人)",
    r"作为.{0,3}(AI|ai|人工智能|语言模型)",
    r"我(不能|无法)扮演",
    r"我没有(真正的|真实的)情感",
    r"系统提示词",
    r"作为一个语言模型",
]
_RISK_RE = re.compile("|".join(RISK_PATTERNS))

FALLBACK_LINE = "[皱眉]这话问得奇怪，不讲不讲。"

_EXACT_RISK_TEXTS = (
    "我不能扮演",
    "我无法扮演",
    "我没有真正的情感",
    "我没有真实的情感",
    "系统提示词",
    "作为一个语言模型",
)
_WILDCARD_RISK_TEXTS = (
    ("我是", ("AI", "ai", "人工智能", "语言模型", "机器人")),
    ("作为", ("AI", "ai", "人工智能", "语言模型")),
)
_MAX_RISK_TEXT_LENGTH = 9


def _could_be_risk_prefix(text: str) -> bool:
    if any(risk_text.startswith(text) for risk_text in _EXACT_RISK_TEXTS):
        return True
    for prefix, targets in _WILDCARD_RISK_TEXTS:
        if prefix.startswith(text):
            return True
        if not text.startswith(prefix):
            continue
        remainder = text[len(prefix):]
        for wildcard_length in range(4):
            if len(remainder) <= wildcard_length:
                return True
            target_prefix = remainder[wildcard_length:]
            if any(target.startswith(target_prefix) for target in targets):
                return True
    return False


def _ambiguous_suffix_length(text: str) -> int:
    max_length = min(len(text), _MAX_RISK_TEXT_LENGTH - 1)
    for length in range(max_length, 0, -1):
        if _could_be_risk_prefix(text[-length:]):
            return length
    return 0


def safety_check(dialogue: str, fallback: str = FALLBACK_LINE) -> str:
    """Replace empty or immersion-breaking model output."""
    if not dialogue:
        return fallback
    if _RISK_RE.search(dialogue):
        logger.warning("检测到高风险输出，已替换: %s", dialogue[:200])
        return fallback
    return dialogue


class DialogueSafetyStream:
    """Emit safe prefixes while retaining enough text to detect split risks."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._text = ""
        self._emitted_length = 0
        self._blocked = False

    def feed(self, delta: str) -> None:
        if self._blocked or not delta:
            return
        self._text += delta
        if _RISK_RE.search(self._text):
            self._blocked = True
            return
        emit_end = len(self._text) - _ambiguous_suffix_length(self._text)
        if emit_end <= self._emitted_length:
            return
        self._emit(self._text[self._emitted_length:emit_end])
        self._emitted_length = emit_end

    def finish(self, final_dialogue: str) -> str:
        """Flush safe remaining text and return the filtered final dialogue."""
        safe_dialogue = safety_check(final_dialogue)
        if self._blocked or safe_dialogue != final_dialogue:
            return safe_dialogue
        if final_dialogue.startswith(self._text):
            remaining = final_dialogue[self._emitted_length:]
            if remaining:
                self._emit(remaining)
            self._emitted_length = len(final_dialogue)
        return safe_dialogue
