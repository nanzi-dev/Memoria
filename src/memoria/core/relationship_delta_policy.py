"""Deterministic fallbacks for relationship deltas returned by the LLM.

The LLM is still the primary source for relationship changes.  When it
returns zero or omits a delta, this module supplies a bounded deterministic
signal so ordinary warming conversations do not silently leave every
relationship unchanged.
"""

from __future__ import annotations

from typing import Any

from memoria.core.config import configs


_SHARED_POSITIVE_CUES = (
    "谢谢",
    "感谢",
    "开心",
    "高兴",
    "温暖",
    "关心",
    "在意",
    "一起",
    "陪伴",
    "陪你",
    "想你",
    "抱歉",
    "对不起",
    "珍惜",
)

_AFFINITY_POSITIVE_CUES = (
    "喜欢",
    "好感",
    "心动",
    "亲近",
    "靠近",
    "更亲",
    "投缘",
    "有缘",
    "温柔",
    "可爱",
    "有意思",
    "舍不得",
)

_TRUST_POSITIVE_CUES = (
    "相信",
    "信任",
    "信赖",
    "放心",
    "可靠",
    "靠谱",
    "真诚",
    "坦诚",
    "诚恳",
    "坦白",
    "交底",
    "托付",
    "依靠",
    "依赖",
    "安心",
    "秘密",
    "承诺",
)

_STRONG_POSITIVE_CUES = (
    "更喜欢",
    "好感",
    "心动",
    "信任你",
    "相信你",
    "最爱",
    "很重要",
    "依赖",
    "交底",
    "托付",
    "离不开",
)

_NEGATIVE_CUES = (
    "讨厌",
    "厌恶",
    "恶心",
    "滚",
    "滚开",
    "别烦",
    "不想理",
    "离我远点",
    "恨",
    "拒绝",
    "不用了",
    "不需要",
    "不同意",
    "不行",
    "没兴趣",
    "不想说",
    "少来",
    "烦",
    "失望",
    "背叛",
    "欺骗",
    "说谎",
)

_NEGATIVE_ACTIONS = (
    "disagree",
    "reject",
    "refuse",
    "leave",
    "angry",
    "ignore",
    "attack",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def _fallback_delta(
    text: str,
    action: str,
    relationship_kind: str,
) -> float:
    combined = f"{text} {action}".lower()
    if _contains_any(combined, _NEGATIVE_CUES) or _contains_any(
        action.lower(),
        _NEGATIVE_ACTIONS,
    ):
        return -1.0

    positive_cues = (
        _SHARED_POSITIVE_CUES
        + (
            _AFFINITY_POSITIVE_CUES
            if relationship_kind == "affinity"
            else _TRUST_POSITIVE_CUES
        )
    )
    if _contains_any(combined, _STRONG_POSITIVE_CUES):
        return 2.0
    if _contains_any(combined, positive_cues):
        return 1.0
    return 0.0


def resolve_relationship_delta(
    llm_delta: Any,
    text: str,
    action: str,
    current_value: float,
    relationship_kind: str,
    context: dict[str, Any] | None = None,
) -> float:
    """Resolve one affinity or trust delta with a deterministic fallback.

    Non-zero LLM values are preserved and clipped to the [-10, 10] range.
    Zero or missing values are only replaced when the fallback is enabled.
    """
    del current_value, context  # kept for call-site symmetry and future tuning

    parsed = max(-10.0, min(10.0, _safe_float(llm_delta)))
    if parsed != 0.0 or not configs.relationship_delta_enabled:
        return parsed

    relationship_kind = str(relationship_kind or "affinity").lower()
    if relationship_kind not in {"affinity", "trust"}:
        relationship_kind = "affinity"
    delta = _fallback_delta(str(text or ""), str(action or ""), relationship_kind)

    lower = max(-10.0, _safe_float(configs.relationship_delta_min, -10.0))
    upper = min(10.0, _safe_float(configs.relationship_delta_max, 10.0))
    if lower > upper:
        lower, upper = upper, lower
    return max(lower, min(upper, delta))
