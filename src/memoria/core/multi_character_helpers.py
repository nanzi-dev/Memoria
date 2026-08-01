"""
多角色对话编排 — 辅助函数

从 multi_character_orchestrator.py 中提取的独立工具函数，
供编排器及其他模块复用。
"""

from __future__ import annotations

import logging

from memoria.core import (
    character_loader,
    prompt_builder,
    world_clock,
)
from memoria.core.locale import Locale

logger = logging.getLogger(__name__)


def _history_after_cutoff(
    history: list[dict],
    cutoff: str | None,
) -> list[dict]:
    """过滤 *cutoff* 之前的历史消息，返回 >= cutoff 的记录。"""
    if not cutoff:
        return history
    try:
        cutoff_at = world_clock.as_utc(cutoff)
    except (TypeError, ValueError):
        logger.warning("无效的关系历史截止时间: %r", cutoff)
        return history

    filtered = []
    for message in history:
        created_at = message.get("created_at")
        if not created_at:
            filtered.append(message)
            continue
        try:
            if world_clock.as_utc(created_at) >= cutoff_at:
                filtered.append(message)
        except (TypeError, ValueError):
            logger.warning(
                "忽略时间格式无效的群聊历史消息: message_id=%s",
                message.get("message_id"),
            )
    return filtered


def _clip(value: float, lo: float, hi: float) -> float:
    """数值裁剪"""
    return max(lo, min(hi, value))


def _safe_float(value, default: float = 0.0) -> float:
    """安全 float 转换"""
    try:
        return float(value)
    except Exception:
        return default


def _clock_snapshot_for_player(player_id: str | None):
    """为指定玩家获取时钟快照；无玩家时返回 UTC 快照。"""
    if player_id:
        return world_clock.get_clock_snapshot(player_id)
    now = world_clock.utc_now()
    return world_clock.WorldClockSnapshot(
        player_id="",
        timezone="UTC",
        time_scale=1,
        real_now=now,
        world_now=now,
    )


def _load_character_card(character_id: str, player_id: str, locale: Locale):
    """Load a localized card while tolerating legacy test doubles."""
    try:
        return character_loader.load_character_card(character_id, player_id, locale)
    except TypeError as exc:
        if "positional" not in str(exc) and "unexpected keyword argument" not in str(exc):
            raise
        return character_loader.load_character_card(character_id, player_id)


def _build_multi_character_system_prompt(*, locale: Locale, **kwargs) -> str:
    """Build a locale-aware prompt while tolerating legacy test doubles."""
    try:
        return prompt_builder.build_multi_character_system_prompt(
            locale=locale,
            **kwargs,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        legacy_kwargs = dict(kwargs)
        legacy_kwargs.pop("player_character", None)
        try:
            return prompt_builder.build_multi_character_system_prompt(
                locale=locale,
                **legacy_kwargs,
            )
        except TypeError as legacy_exc:
            if "unexpected keyword argument" not in str(legacy_exc):
                raise
            return prompt_builder.build_multi_character_system_prompt(**legacy_kwargs)
