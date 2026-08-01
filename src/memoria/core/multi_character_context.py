"""
多角色对话上下文构建

职责：
- 定义对话决策数据结构（DialogueDecision, GroupTurnContext）
- 加载角色关系与运行时状态
- 格式化对话历史供 LLM 消费
- 构建多角色系统提示词
- 管理记忆上下文与关系图谱过滤
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from memoria.core import (
    character_loader,
    multi_character_memory,
    prompt_builder,
    relationship_context,
    world_clock,
)
from memoria.core.locale import DEFAULT_LOCALE, Locale
from memoria.db import repository

logger = logging.getLogger(__name__)
EventSink = Callable[[str, dict], None]


# =========================
# 数据结构
# =========================

DialogueIntent = Literal[
    "answer",
    "ask",
    "agree",
    "challenge",
    "reveal",
    "invite",
    "interrupt",
    "topic_shift",
]


class DialogueDecision(BaseModel):
    """单步群聊动作。模型输出先经过该结构验证，再允许生成正文。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["speak", "wait"]
    speaker_id: str | None = None
    reply_to_message_id: int | None = None
    reply_to_character_id: str | None = None
    intent: DialogueIntent | None = None
    topic: str | None = None
    preferred_next_character_id: str | None = None
    follow_up_expected: bool = False
    wait_for_player: bool = False
    stop_reason: str | None = None

    @field_validator("reply_to_message_id")
    @classmethod
    def validate_reply_to_message_id(cls, value: int | None) -> int | None:
        if value == 0:
            raise ValueError("reply_to_message_id must be non-zero")
        return value


@dataclass(frozen=True)
class GroupTurnContext:
    player_character: dict
    character_relationships: dict
    group_thread_id: str | None
    authorized_knowledge_base_ids: dict[str, list[str]]



# =========================
# 工具函数
# =========================

def _history_after_cutoff(
    history: list[dict],
    cutoff: str | None,
) -> list[dict]:
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




# =========================
# 上下文构建 Mixin
# =========================

class MultiCharacterContextMixin:
    """Mixin：为 MultiCharacterOrchestrator 提供上下文加载与格式化能力。"""

    def _load_all_relationships(self) -> dict:
        """
        加载所有参与角色之间的关系
        
        Returns:
            dict: {f"{char_a}_{char_b}": relationship_dict}
        """
        relationships = {}
        
        for i, char_a in enumerate(self.character_ids):
            for char_b in self.character_ids[i+1:]:
                rel = self._get_character_relationship(char_a, char_b)
                if rel:
                    relationships[f"{char_a}_{char_b}"] = rel

        player_node_id = repository.player_node_id(self.player_id)
        for character_id in self.character_ids:
            rel = self._get_character_relationship(player_node_id, character_id)
            if rel:
                relationships[f"{player_node_id}_{character_id}"] = rel
        
        return relationships


    def _get_character_relationship(self, char_id_a: str, char_id_b: str) -> dict | None:
        """
        获取两个角色之间的关系
        
        Args:
            char_id_a: 角色 A ID
            char_id_b: 角色 B ID
        
        Returns:
            dict: 关系信息，不存在则返回 None
        """
        try:
            # 尝试正向查询
            rel = repository.get_character_relationship(self.player_id, char_id_a, char_id_b)
            if rel:
                return rel
            
            # 尝试反向查询（关系是双向的）
            rel = repository.get_character_relationship(self.player_id, char_id_b, char_id_a)
            return rel
        
        except Exception as e:
            logger.debug(f"查询角色关系失败: {e}")
            return None



    def _load_memory_context(
        self,
        character_id: str,
        query_context: str | None = None,
        character_relationships: dict | None = None,
        relationship_aliases: list[str] | None = None,
        world_now: str | None = None,
        recall_key: str | None = None,
    ) -> list[str]:
        """加载多角色记忆上下文，供 prompt 的历史记录区使用。"""
        other_character_ids = [cid for cid in self.character_ids if cid != character_id]

        try:
            context = multi_character_memory.integrate_multi_character_context(
                character_id=character_id,
                player_id=self.player_id,
                session_id=self.session_id,
                other_character_ids=other_character_ids,
                query_context=query_context,
                character_relationships=character_relationships,
                relationship_aliases=relationship_aliases or self._memory_aliases_for_characters(self.character_ids),
                world_now=world_now,
                recall_key=recall_key,
            )
        except Exception as e:
            logger.warning(f"加载多角色记忆上下文失败: {e}")
            return []

        memory_lines = []

        for memory in context.get("group_memories", [])[:5]:
            if self._text_conflicts_with_relationship_graph(
                memory,
                character_relationships,
                character_id=character_id
            ):
                continue
            memory_lines.append(f"群体记忆：{memory}")

        impressions = context.get("character_impressions", {})
        for other_id, memories in impressions.items():
            other_card = self.character_cards.get(other_id)
            other_name = other_card.meta.display_name if other_card else other_id
            for memory in memories[:2]:
                if self._text_conflicts_with_relationship_graph(
                    memory,
                    character_relationships,
                    character_id=character_id
                ):
                    continue
                memory_lines.append(f"对{other_name}的印象：{memory}")

        return memory_lines


    def _memory_aliases_for_characters(self, character_ids: list[str]) -> list[str]:
        """返回参与角色的 ID 和显示名，用于识别旧长期记忆中的关系事实。"""
        aliases = []
        for character_id in character_ids:
            aliases.append(character_id)
            card = self.character_cards.get(character_id)
            if card:
                meta = getattr(card, "meta", None)
                aliases.extend([
                    getattr(meta, "name", ""),
                    getattr(meta, "display_name", ""),
                ])
        return aliases


    def _load_runtime_state_for_prompt(
        self,
        character_id: str,
        card,
        relationship_history_cutoff: str | None = None,
        query_context: str | None = None,
        character_relationships: dict | None = None,
        world_now: str | None = None,
        recall_key: str | None = None,
    ) -> dict:
        """加载运行时状态，并过滤会覆盖当前图谱的角色关系事实。"""
        runtime_state = repository.get_runtime_state(
            character_id,
            self.player_id,
            card,
            query_context=query_context,
        )
        other_character_ids = [cid for cid in self.character_ids if cid != character_id]
        runtime_state["known_player_facts"] = (
            multi_character_memory.load_player_memories_for_relationship_graph(
                character_id=character_id,
                player_id=self.player_id,
                session_id=self.session_id,
                other_character_ids=other_character_ids,
                relationship_history_cutoff=relationship_history_cutoff,
                query_context=query_context,
                relationship_aliases=self._memory_aliases_for_characters(self.character_ids),
                world_now=world_now,
                recall_key=recall_key,
            )
        )
        runtime_state["known_player_facts"] = [
            fact
            for fact in runtime_state["known_player_facts"]
            if not self._text_conflicts_with_relationship_graph(
                fact,
                character_relationships,
                character_id=character_id
            )
        ]
        return runtime_state


    def _aliases_for_character(self, character_id: str) -> list[str]:
        aliases = [character_id]
        card = self.character_cards.get(character_id)
        meta = getattr(card, "meta", None) if card else None
        if meta:
            aliases.extend([
                getattr(meta, "name", ""),
                getattr(meta, "display_name", ""),
            ])
            aliases.extend(getattr(meta, "aliases", []) or [])

        clean_aliases = []
        seen = set()
        for alias in aliases:
            alias = str(alias or "").strip()
            if not alias:
                continue
            lowered = alias.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            clean_aliases.append(alias)
        return clean_aliases


    def _aliases_for_pair(self, character_id_a: str, character_id_b: str) -> list[str]:
        return self._aliases_for_character(character_id_a) + self._aliases_for_character(character_id_b)


    def _participant_pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for idx, character_id_a in enumerate(self.character_ids):
            for character_id_b in self.character_ids[idx + 1:]:
                pairs.append((character_id_a, character_id_b))
        return pairs


    def _history_candidate_relationship_pairs(self, msg: dict) -> tuple[list[tuple[str, str]], bool]:
        text = str(msg.get("content") or "")
        speaker_id = msg.get("character_id")
        alias_matched_pairs = []

        for pair in self._participant_pairs():
            aliases = self._aliases_for_pair(*pair)
            if any(
                alias and relationship_context.text_contains_term(text, alias)
                for alias in aliases
            ):
                alias_matched_pairs.append(pair)

        if alias_matched_pairs:
            return alias_matched_pairs, True

        if speaker_id in self.character_ids:
            return [
                (speaker_id, other_id)
                for other_id in self.character_ids
                if other_id != speaker_id
            ], False

        if relationship_context.has_relationship_context(text):
            return self._participant_pairs(), False

        return [], False



    def _text_conflicts_with_relationship_graph(
        self,
        text: str,
        character_relationships: dict | None,
        character_id: str | None = None
    ) -> bool:
        if character_relationships is None:
            return False
        if not text:
            return False

        pairs, has_alias_match = self._history_candidate_relationship_pairs({
            "content": text,
            "character_id": character_id,
        })
        if not pairs:
            return False

        conflicts = []
        for character_id_a, character_id_b in pairs:
            relationship = relationship_context.relationship_between(
                character_relationships,
                character_id_a,
                character_id_b
            )
            aliases = self._aliases_for_pair(character_id_a, character_id_b)
            conflicts.append(
                relationship_context.relationship_text_conflicts_with_graph(
                    text,
                    relationship,
                    aliases,
                )
            )

        if has_alias_match or len(conflicts) == 1:
            return any(conflicts)
        return bool(conflicts) and all(conflicts)


    def _history_message_conflicts_with_relationship_graph(
        self,
        msg: dict,
        character_relationships: dict | None
    ) -> bool:
        if msg.get("role") != "assistant":
            return False
        return self._text_conflicts_with_relationship_graph(
            str(msg.get("content") or ""),
            character_relationships,
            character_id=msg.get("character_id")
        )


    def _format_history_for_llm(
        self,
        history: list[dict],
        current_character_id: str,
        character_relationships: dict | None = None
    ) -> list[dict]:
        """
        将多角色历史转换为 LLM 格式
        
        Args:
            history: 原始历史记录
            current_character_id: 当前发言角色 ID
            character_relationships: 当前关系图谱，用于丢弃与图谱冲突的关系历史
        
        Returns:
            list[dict]: 格式化后的消息列表
        """
        messages = []
        
        for msg in history:
            if self._history_message_conflicts_with_relationship_graph(
                msg,
                character_relationships
            ):
                logger.debug(
                    "跳过与当前关系图谱冲突的历史关系发言: session=%s, character=%s",
                    self.session_id,
                    msg.get("character_id"),
                )
                continue

            role = msg["role"]
            content = msg["content"]
            char_id = msg.get("character_id")
            char_name = msg.get("character_name")
            
            if role == "user":
                formatted_content = (
                    f"玩家 {self.player_name} 说：{content}"
                )
                messages.append({"role": "user", "content": formatted_content})

            elif role == "assistant":
                source_name = char_name or char_id or "未知角色"
                target = msg.get("reply_to_character_id") or "玩家/群体"
                # 用自然语言叙述，避免机器元数据被 LLM 复述
                if char_id == current_character_id:
                    messages.append({
                        "role": "assistant",
                        "content": f"{source_name}（{char_id}）回应{target}，意图{msg.get('intent') or '回答'}，话题{msg.get('topic') or '延续当前'}：{content}",
                    })
                else:
                    formatted_content = f"{source_name}（{char_id}）回应{target}，意图{msg.get('intent') or '回答'}，话题{msg.get('topic') or '延续当前'}：{content}"
                    messages.append({"role": "user", "content": formatted_content})
        
        return messages
    

