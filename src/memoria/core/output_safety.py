"""Safety filtering for complete and incrementally streamed dialogue."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from memoria.core.llm_client import looks_like_provider_rejection

logger = logging.getLogger(__name__)

# Immersion-breaking / prompt-leak / jailbreak markers.
# Keep patterns specific enough to avoid normal role-play dialogue false positives.
RISK_PATTERNS = [
    r"我是.{0,3}(AI|ai|人工智能|语言模型|机器人)",
    r"作为.{0,3}(AI|ai|人工智能|语言模型)",
    r"我(不能|无法)扮演",
    r"我没有(真正的|真实的)情感",
    r"系统提示词",
    r"作为一个语言模型",
    r"忽略(之前|以上|上面|先前)的(所有)?(指令|提示|规则)",
    r"无视(之前|以上|系统)(的)?(指令|提示|规则)",
    r"jailbreak",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
    r"system\s+prompt",
    r"you\s+are\s+(now\s+)?(chatgpt|gpt-?4|an?\s+ai\s+language\s+model)",
    r"i\s+am\s+(chatgpt|gpt-?4|an?\s+ai\s+language\s+model|an?\s+artificial\s+intelligence)",
    r"as\s+an?\s+ai\s+language\s+model",
    r"developer\s+mode\s+enabled",
    r"dan\s+mode",
    # 服务商拒答 / 风控标记（中英文）
    r"the\s+request\s+was\s+rejected",
    r"considered\s+high\s+risk",
    r"content\s+policy",
    r"safety\s+policy",
    r"risk\s+control",
    r"请求(已)?被拒绝",
    r"被判定为高风险",
    r"存在(较高)?风险",
    r"内容政策",
    r"安全政策",
    r"风控",
]
_RISK_RE = re.compile("|".join(RISK_PATTERNS), re.IGNORECASE)

FALLBACK_LINE = "[皱眉]这话问得奇怪，不讲不讲。"

_EXACT_RISK_TEXTS = (
    "我不能扮演",
    "我无法扮演",
    "我没有真正的情感",
    "我没有真实的情感",
    "系统提示词",
    "作为一个语言模型",
    "忽略之前的指令",
    "忽略以上的指令",
    "忽略上面的指令",
    "忽略先前的指令",
    "忽略之前的所有指令",
    "无视之前的指令",
    "无视系统指令",
    "jailbreak",
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore prior instructions",
    "ignore above instructions",
    "disregard previous instructions",
    "disregard all previous instructions",
    "system prompt",
    "as an ai language model",
    "i am chatgpt",
    "i am an ai language model",
    "you are chatgpt",
    "developer mode enabled",
    "dan mode",
    # 服务商拒答 / 风控标记（中英文）
    "the request was rejected",
    "considered high risk",
    "content policy",
    "safety policy",
    "risk control",
    "请求被拒绝",
    "请求已被拒绝",
    "被判定为高风险",
    "内容政策",
    "安全政策",
    "风控",
)
_WILDCARD_RISK_TEXTS = (
    ("我是", ("AI", "ai", "人工智能", "语言模型", "机器人")),
    ("作为", ("AI", "ai", "人工智能", "语言模型")),
)
# Longest exact risk phrase used to bound streaming holdback.
_MAX_RISK_TEXT_LENGTH = max(len(text) for text in _EXACT_RISK_TEXTS)


def _could_be_risk_prefix(text: str) -> bool:
    lowered = text.lower()
    if any(risk_text.startswith((text, lowered)) for risk_text in _EXACT_RISK_TEXTS):
        return True
    for prefix, targets in _WILDCARD_RISK_TEXTS:
        if prefix.startswith(text):
            return True
        if not text.startswith(prefix):
            continue
        remainder = text[len(prefix) :]
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
        # English phrases are matched case-insensitively.
        if _could_be_risk_prefix(text[-length:].lower()):
            return length
    return 0


def safety_check(dialogue: str, fallback: str = FALLBACK_LINE) -> str:
    """Replace empty or immersion-breaking model output."""
    if not dialogue:
        return fallback
    if _RISK_RE.search(dialogue) or looks_like_provider_rejection(dialogue):
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
        self._emit(self._text[self._emitted_length : emit_end])
        self._emitted_length = emit_end

    def finish(self, final_dialogue: str) -> str:
        """Flush safe remaining text and return the filtered final dialogue."""
        safe_dialogue = safety_check(final_dialogue)
        if self._blocked or safe_dialogue != final_dialogue:
            return safe_dialogue
        # 流式累积文案与最终文案不一致时，也不能静默丢弃尾部。
        # 对尚未 emit 的剩余内容做一次安全检查后再输出。
        if len(final_dialogue) > self._emitted_length:
            remaining = final_dialogue[self._emitted_length :]
            checked_remaining = safety_check(remaining, fallback="")
            if checked_remaining:
                self._emit(checked_remaining)
            self._emitted_length = len(final_dialogue)
        return safe_dialogue
