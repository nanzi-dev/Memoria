"""
对话质量评分。

默认使用本地启发式，避免评分 API 在测试或离线环境里依赖外部 LLM。
调用方可显式启用 use_llm，让轻量模型给出更细的自然语言评估。
"""

from __future__ import annotations

import json
from statistics import mean

from memoria.core import character_loader, llm_client
from memoria.core.llm_client import _extract_json


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _assistant_messages(messages: list[dict]) -> list[str]:
    return [
        str(m.get("content", "")).strip()
        for m in messages
        if m.get("role") == "assistant" and str(m.get("content", "")).strip()
    ]


def _heuristic_score(
    messages: list[dict],
    character_id: str | None = None,
    owner_user_id: str | None = None,
) -> dict:
    assistant_texts = _assistant_messages(messages)
    all_text = "\n".join(assistant_texts)
    reasons: list[str] = []

    if not assistant_texts:
        return {
            "character_consistency": 0,
            "interestingness": 0,
            "overall": 0,
            "method": "heuristic",
            "reasons": ["没有可评分的 assistant 消息"],
        }

    risk_markers = ("我是AI", "我是 AI", "语言模型", "系统提示词", "无法扮演", "作为一个AI")
    risk_hits = sum(1 for marker in risk_markers if marker in all_text)
    consistency = 85 - risk_hits * 25
    if risk_hits:
        reasons.append("检测到可能破坏角色沉浸感的表述")

    if character_id:
        try:
            card = character_loader.load_character_card(character_id, owner_user_id)
            names = {card.meta.name, card.meta.display_name, character_id}
            if any(name and name in all_text for name in names):
                consistency += 5
        except Exception:
            reasons.append("角色卡不可用，未纳入角色关键词校验")

    lengths = [len(text) for text in assistant_texts]
    avg_len = mean(lengths)
    varied_length = len(set(lengths)) > 1
    action_markers = all((
        "[" in all_text or "【" in all_text,
        "]" in all_text or "】" in all_text,
    ))
    question_count = all_text.count("?") + all_text.count("？")

    interestingness = 55
    if 20 <= avg_len <= 220:
        interestingness += 15
    if varied_length:
        interestingness += 10
    if action_markers:
        interestingness += 10
    if question_count:
        interestingness += min(10, question_count * 3)
    if len(assistant_texts) >= 3:
        interestingness += 5

    if not reasons:
        reasons.append("未发现明显角色破坏信号，回复长度和互动性处于可用范围")

    consistency = _clamp_score(consistency)
    interestingness = _clamp_score(interestingness)
    return {
        "character_consistency": consistency,
        "interestingness": interestingness,
        "overall": _clamp_score(consistency * 0.6 + interestingness * 0.4),
        "method": "heuristic",
        "reasons": reasons,
    }


def _llm_score(messages: list[dict], character_id: str | None, fallback: dict) -> dict:
    prompt = f"""
请评估以下角色扮演对话质量，只输出 JSON。

评分范围 0-100：
- character_consistency: 是否保持角色一致性、没有暴露 AI/系统身份
- interestingness: 是否有趣、有互动推进、有画面感
- overall: 综合评分
- reasons: 2-4 条简短中文理由

character_id: {character_id or "unknown"}
messages:
{json.dumps(messages, ensure_ascii=False)}
    """.strip()

    raw = llm_client.call_light_task(prompt)
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return fallback

    return {
        "character_consistency": _clamp_score(parsed.get("character_consistency", fallback["character_consistency"])),
        "interestingness": _clamp_score(parsed.get("interestingness", fallback["interestingness"])),
        "overall": _clamp_score(parsed.get("overall", fallback["overall"])),
        "method": "llm",
        "reasons": parsed.get("reasons") or fallback["reasons"],
    }


def score_dialogue(
    messages: list[dict],
    character_id: str | None = None,
    owner_user_id: str | None = None,
    use_llm: bool = False,
) -> dict:
    fallback = _heuristic_score(messages, character_id, owner_user_id)
    if not use_llm:
        return fallback
    try:
        return _llm_score(messages, character_id, fallback)
    except Exception:
        return fallback
