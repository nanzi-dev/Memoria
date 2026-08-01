"""
多角色对话编排核心逻辑

功能：
1. 管理多角色发言顺序
2. 构建多角色上下文
3. 处理角色间互动
4. 协调记忆系统
5. 应用角色关系网络
"""

import json
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from memoria.core import (
    character_loader,
    event_runtime,
    llm_client,
    multi_character_memory,
    performance,
    prompt_builder,
    relationship_context,
    world_clock,
)
from memoria.core.config import configs
from memoria.core.event_schema import EventTriggerResult
from memoria.core.knowledge_retriever import retrieve_knowledge
from memoria.core.locale import DEFAULT_LOCALE, Locale
from memoria.core.memory_extractor import is_memory_worthy_candidate
from memoria.core.output_safety import DialogueSafetyStream, safety_check
from memoria.core.relationship_delta_policy import resolve_relationship_delta
from memoria.core.speaking_strategy import HybridStrategy
from memoria.db import repository

logger = logging.getLogger(__name__)
EventSink = Callable[[str, dict], None]


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


# -- 辅助函数已拆分至 multi_character_helpers，以下为向后兼容的导入 --
from memoria.core.multi_character_helpers import (  # noqa: E402
    _history_after_cutoff,
    _clip,
    _safe_float,
    _clock_snapshot_for_player,
    _load_character_card,
    _build_multi_character_system_prompt,
)
# -- 方法已拆分至以下 Mixin，编排器通过继承复用，避免重复维护 --
from memoria.core.multi_character_context import (  # noqa: E402
    DialogueDecision,
    GroupTurnContext,
    MultiCharacterContextMixin,
)
from memoria.core.multi_character_memory_ops import (  # noqa: E402
    MultiCharacterMemoryOpsMixin,
)
from memoria.core.multi_character_turn import (  # noqa: E402
    MultiCharacterTurnMixin,
)


class MultiCharacterOrchestrator(
    MultiCharacterTurnMixin,
    MultiCharacterContextMixin,
    MultiCharacterMemoryOpsMixin,
):
    """
    多角色对话编排器

    负责：
    - 决定哪个角色发言
    - 构建多角色上下文
    - 处理角色间关系
    - 管理发言轮次
    """
    
    def __init__(self, session_id: str):
        """
        初始化编排器
        
        Args:
            session_id: 会话 ID
        """
        self.session_id = session_id
        self.session = repository.get_session(session_id)
        
        if not self.session:
            raise ValueError(f"会话不存在: {session_id}")
        
        if not self.session.get("is_multi_character"):
            raise ValueError(f"会话 {session_id} 不是多角色会话")
        if self.session.get("status") == "ended":
            raise ValueError("会话已经结束")
        
        self.player_id = self.session["player_id"]
        self.player_name = self.session["player_name"]
        self.player_character = {}
        self._refresh_player_character()
        self.locale = self.session.get("locale") or DEFAULT_LOCALE
        
        # 加载参与者
        self.participants = repository.get_session_participants(session_id, only_active=True)
        self.character_ids = [p["character_id"] for p in self.participants]
        
        # 加载角色卡
        self.character_cards = {}
        for char_id in self.character_ids:
            try:
                card = _load_character_card(char_id, self.player_id, self.locale)
                self.character_cards[char_id] = card
            except Exception as e:
                logger.error(f"加载角色卡失败 {char_id}: {e}")
        
        # 初始化发言策略
        self.speaking_strategy = HybridStrategy()
        
        # 缓存最后发言者
        self.last_speaker_id = None
        self._checkpoint_memory_fact = None
        self._checkpoint_memory_ready = False
        
        logger.info(f"多角色编排器已初始化: session={session_id}, 参与角色={self.character_ids}")


    def _refresh_player_character(self) -> dict:
        fallback_name = getattr(self, "player_name", None) or "玩家"
        try:
            card = repository.get_or_create_user_character_card(self.player_id)
        except Exception as exc:
            logger.warning("加载玩家角色卡失败，继续使用会话名称: %s", exc)
            card = None
        player_character = dict(card or getattr(self, "player_character", {}) or {})
        player_character.setdefault("display_name", fallback_name)
        player_character.setdefault("node_id", repository.player_node_id(self.player_id))
        self.player_character = player_character
        self.player_name = player_character["display_name"]
        return player_character


    def _load_group_turn_context(self) -> GroupTurnContext:
        player_character = self._refresh_player_character()
        character_relationships = self._load_all_relationships()
        group_thread_id = repository.get_group_thread_id(self.session_id)
        authorized_knowledge_base_ids = {}
        for character_id in dict.fromkeys(self.character_ids):
            try:
                authorized_knowledge_base_ids[character_id] = (
                    repository.get_authorized_knowledge_base_ids(
                        self.player_id,
                        character_id=character_id,
                        group_thread_id=group_thread_id,
                    )
                )
            except Exception:
                logger.warning(
                    "预取角色知识库授权失败: session=%s, character=%s",
                    self.session_id,
                    character_id,
                    exc_info=True,
                )
                authorized_knowledge_base_ids[character_id] = []
        return GroupTurnContext(
            player_character=player_character,
            character_relationships=character_relationships,
            group_thread_id=group_thread_id,
            authorized_knowledge_base_ids=authorized_knowledge_base_ids,
        )


    def _ensure_has_active_participants(self) -> None:
        if not self.participants:
            raise ValueError("群聊中没有可回复的在线角色")
    
    
    def start_conversation(self) -> dict:
        """
        开始多角色对话
        
        Returns:
            dict: 包含开场白的响应
        """
        # 选择第一个角色发言（按加入顺序）
        self._ensure_has_active_participants()
        
        first_speaker = self.participants[0]
        character_id = first_speaker["character_id"]
        
        # 生成开场白
        clock_snapshot = _clock_snapshot_for_player(getattr(self, "player_id", None))
        result = self._generate_opening(character_id, clock_snapshot=clock_snapshot)
        
        return result
    
    
    def process_player_message(
        self,
        player_message: str,
        allow_multiple_responses: bool = False,
        max_responses: int | None = None,
        request_id: str | None = None,
        event_sink: EventSink | None = None,
    ) -> dict | list[dict]:
        """
        处理玩家消息，决定哪个角色回应
        
        Args:
            player_message: 玩家消息内容
            allow_multiple_responses: 是否允许多个角色连续回应（讨论模式）
            max_responses: 最多允许几个角色回应；实际人数会按群聊语境动态决定
        
        Returns:
            dict | list[dict]: 单个角色回应或多个角色回应列表
        """
        request_id = request_id or uuid.uuid4().hex
        claim = repository.claim_dialogue_turn(
            session_id=self.session_id,
            request_id=request_id,
            player_id=self.player_id,
            turn_kind="multi",
        )
        if claim["completed"]:
            return claim["response"]
        lease_owner = claim["lease_owner"]
        clock_snapshot = _clock_snapshot_for_player(getattr(self, "player_id", None))
        world_created_at = clock_snapshot.world_now.isoformat()
        player_message_id = -1
        staged_player_message = {
            "message_id": player_message_id,
            "role": "user",
            "content": player_message,
            "world_created_at": world_created_at,
            "trigger_source": "player",
        }

        try:
            self._ensure_has_active_participants()
            turn_context = self._load_group_turn_context()
            if not allow_multiple_responses:
                speaker_id = self._decide_next_speaker(
                    player_message,
                    turn_context=turn_context,
                )
                history = repository.get_multi_character_thread_history(
                    self.session_id,
                    limit_messages=30,
                )
                history = [*history, staged_player_message]
                result = self._generate_character_response(
                    speaker_id,
                    player_message,
                    decision=DialogueDecision(
                        action="speak",
                        speaker_id=speaker_id,
                        reply_to_message_id=player_message_id,
                        intent="answer",
                        topic=player_message[:120] or None,
                    ),
                    trigger_source="player",
                    target_message=staged_player_message,
                    clock_snapshot=clock_snapshot,
                    persist=False,
                    history_override=history,
                    event_sink=event_sink,
                    stream_id=f"{request_id}:0",
                    turn_context=turn_context,
                )
                result["message_id"] = -2
                result["stream_id"] = f"{request_id}:0"
                # 单响应路径不经过脉冲循环，_generate_character_response 以
                # persist=False 生成；立即把好感/信任/情绪增量写入状态表，
                # 避免后续事件系统无事件命中时（state_changes 为空）关系图静默失更。
                if all(
                    key in result
                    for key in (
                        "current_affinity",
                        "current_trust",
                        "current_mood",
                    )
                ):
                    repository.save_runtime_state(
                        speaker_id,
                        self.player_id,
                        result["current_affinity"],
                        result["current_trust"],
                        result["current_mood"],
                    )
                if event_sink:
                    event_sink(
                        "character_completed",
                        {
                            "stream_id": f"{request_id}:0",
                            "character_id": speaker_id,
                            "response": result,
                        },
                    )
                responses = [result]
                self.last_pulse_state = self._build_pulse_state(
                    [
                        DialogueDecision(
                            action="speak",
                            speaker_id=speaker_id,
                            reply_to_message_id=player_message_id,
                            intent="answer",
                            topic=player_message[:120] or None,
                            wait_for_player=True,
                        )
                    ],
                    responses,
                    "player",
                )
            else:
                response_count = min(
                    3,
                    self._decide_group_response_count(
                        player_message,
                        max_responses,
                        turn_context,
                    ),
                )
                responses = self._generate_group_discussion(
                    player_message,
                    response_count,
                    clock_snapshot=clock_snapshot,
                    trigger_message_id=player_message_id,
                    staged_history=[staged_player_message],
                    event_sink=event_sink,
                    request_id=request_id,
                    turn_context=turn_context,
                )

            self._apply_group_event_results(
                player_message,
                responses,
                clock_snapshot=clock_snapshot,
                request_id=request_id,
                lease_owner=lease_owner,
                player_message=staged_player_message,
                turn_context=turn_context,
            )
            committed_response = responses if allow_multiple_responses else responses[0]
            return committed_response
        except Exception as exc:
            # 清理失败不得顶替原始异常，详见 orchestrator.run_dialogue_turn 同处注释。
            try:
                repository.fail_dialogue_turn(
                    self.session_id,
                    request_id,
                    lease_owner,
                    str(exc),
                )
            except Exception:
                logger.exception(
                    "标记群聊轮次失败时出错，租约将等待过期: session=%s request_id=%s",
                    self.session_id,
                    request_id,
                )
            raise












    
    




    @staticmethod






    @staticmethod






    
    
    def trigger_character_interaction(
        self,
        trigger_character_id: str = None,
        prompt: str = None,
        *,
        persist: bool = True,
    ) -> dict:
        """
        触发角色间互动（角色主动发言）
        
        Args:
            trigger_character_id: 触发角色ID，如果为None则自动选择
        
        Returns:
            dict: 角色发言结果
        """
        if trigger_character_id is None:
            trigger_character_id = self._select_character_for_interaction()

        clock_snapshot = world_clock.get_clock_snapshot(self.player_id)
        responses = self.run_dialogue_pulse(
            trigger_source="goal",
            trigger_text=prompt or "主动延续当前剧情或未解决的话题",
            initial_speaker_id=trigger_character_id,
            max_messages=1,
            clock_snapshot=clock_snapshot,
            persist_state=persist,
            persist_messages=persist,
            extract_memory=persist,
        )
        if not responses:
            return {
                "character_id": trigger_character_id,
                "character_name": self.character_cards[trigger_character_id].meta.display_name,
                "dialogue": "",
                "action": "wait",
            }
        return responses[0]
    
    
    def _decide_next_speaker(
        self,
        player_message: str,
        *,
        turn_context: GroupTurnContext | None = None,
    ) -> str:
        """
        决定下一个发言的角色（使用策略系统）
        
        Args:
            player_message: 玩家消息
        
        Returns:
            str: 选中的角色 ID
        """
        # 构建上下文
        context = {
            "player_message": player_message,
            "last_speaker_id": self.last_speaker_id,
            "character_relationships": (
                turn_context.character_relationships
                if turn_context is not None
                else self._load_all_relationships()
            ),
        }
        
        # 使用策略选择
        selected_id = self.speaking_strategy.select_speaker(
            self.participants,
            self.character_cards,
            context
        )
        
        # 更新缓存
        self.last_speaker_id = selected_id
        
        return selected_id
    
    








    def _select_character_for_interaction(self) -> str:
        """
        选择一个角色发起互动（用于角色主动发言）
        
        Returns:
            str: 选中的角色 ID
        """
        # 简单策略：选择最久没发言的角色
        candidates = []
        
        for participant in self.participants:
            char_id = participant["character_id"]
            last_spoke = participant.get("last_spoke_at")
            message_count = participant.get("message_count", 0)
            
            # 计算权重：发言次数少的优先；钳制非负避免长会话后权重为负
            weight = max(0.0, 100.0 - message_count * 5)

            # 最近没发言的优先
            if not last_spoke:
                weight += 50.0

            # 保底权重，避免全员为 0 时随机退化
            weight = max(weight, 1.0)

            candidates.append((char_id, weight))
        
        if not candidates:
            raise ValueError("群聊中没有可回复的在线角色")
        
        # 加权随机选择
        total_weight = sum(w for _, w in candidates)
        rand = random.uniform(0, total_weight)
        
        cumulative = 0
        for char_id, weight in candidates:
            cumulative += weight
            if rand <= cumulative:
                return char_id
        
        return candidates[0][0]
    
    
    def _generate_opening(self, character_id: str, *, clock_snapshot=None) -> dict:
        """
        生成多角色对话开场白
        
        Args:
            character_id: 发言角色 ID
        
        Returns:
            dict: 开场白结果
        """
        self._refresh_player_character()
        card = self.character_cards[character_id]
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
        character_relationships = self._load_all_relationships()
        relationship_history_cutoff = multi_character_memory.get_relationship_history_cutoff(
            self.player_id,
            self.character_ids,
            character_relationships
        )
        runtime_state = self._load_runtime_state_for_prompt(
            character_id,
            card,
            relationship_history_cutoff=relationship_history_cutoff,
            character_relationships=character_relationships,
            world_now=clock_snapshot.world_now.isoformat(),
            recall_key=f"opening:{self.session_id}",
        )
        time_context = clock_snapshot.prompt_context(
            repository.get_last_character_interaction_world_at(
                self.player_id,
                character_id,
            ),
            locale=getattr(
                getattr(card, "speech_style", None),
                "language",
                "zh-CN",
            ),
        )
        # 准备其他角色信息
        other_characters = []
        for other_id in self.character_ids:
            if other_id != character_id:
                other_card = self.character_cards.get(other_id)
                if other_card:
                    other_characters.append({
                        "character_id": other_id,
                        "name": other_card.meta.name,
                        "display_name": other_card.meta.display_name,
                        "occupation": other_card.identity.occupation
                    })

        opening_memory_context = {}
        if configs.memory_curve_enabled:
            opening_memory_context["past_summaries"] = self._load_memory_context(
                character_id,
                character_relationships=character_relationships,
                world_now=clock_snapshot.world_now.isoformat(),
                recall_key=f"opening:{self.session_id}",
            )

        # 加载线程历史，让开场白基于既有关系（避免每次重新自我介绍）
        opening_history = repository.get_multi_character_thread_history(
            self.session_id,
            limit_messages=20,
            created_after=relationship_history_cutoff,
        )

        # 使用 prompt_builder 构建系统提示
        system_prompt = _build_multi_character_system_prompt(
            locale=getattr(self, "locale", DEFAULT_LOCALE),
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            player_character=self.player_character,
            other_characters=other_characters,
            character_relationships=character_relationships,
            is_opening=True,
            time_context=time_context,
            **opening_memory_context,
        )

        # 生成开场白（基于线程历史）
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=self._format_history_for_llm(
                opening_history,
                character_id,
                character_relationships=character_relationships,
            ),
        )
        
        dialogue = result.get("dialogue", "")
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 记录消息
        character_name = card.meta.display_name or card.meta.name
        message_id = repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            content=dialogue,
            character_id=character_id,
            character_name=character_name,
            world_created_at=clock_snapshot.world_now.isoformat(),
        )
        
        return {
            "message_id": message_id,
            "character_id": character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action,
            "current_affinity": runtime_state.get("affection_level", 0),
            "current_mood": runtime_state.get("current_mood", "neutral"),
            "world_created_at": clock_snapshot.world_now.isoformat(),
        }
    
    
    
    
    def _generate_character_interaction(
        self,
        trigger_character_id: str,
        prompt: str = None,
        *,
        clock_snapshot=None,
        persist: bool = True,
    ) -> dict:
        """
        生成角色间互动（角色主动发言）
        
        Args:
            trigger_character_id: 触发角色 ID
        
        Returns:
            dict: 角色互动结果
        """
        self._refresh_player_character()
        if trigger_character_id not in self.character_cards:
            raise ValueError(f"角色不可回复: {trigger_character_id}")
        card = self.character_cards[trigger_character_id]
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
        character_relationships = self._load_all_relationships()
        relationship_history_cutoff = multi_character_memory.get_relationship_history_cutoff(
            self.player_id,
            self.character_ids,
            character_relationships
        )
        runtime_state = self._load_runtime_state_for_prompt(
            trigger_character_id,
            card,
            relationship_history_cutoff=relationship_history_cutoff,
            character_relationships=character_relationships,
            world_now=clock_snapshot.world_now.isoformat(),
            recall_key=f"interaction:{self.session_id}:{clock_snapshot.world_now.isoformat()}",
        )
        time_context = clock_snapshot.prompt_context(
            repository.get_last_character_interaction_world_at(
                self.player_id,
                trigger_character_id,
            ),
            locale=getattr(
                getattr(card, "speech_style", None),
                "language",
                "zh-CN",
            ),
        )
        history = repository.get_multi_character_thread_history(
            self.session_id,
            limit_messages=20,
            created_after=relationship_history_cutoff
        )
        interaction_prompt = prompt or "（现在可以主动说些什么，或者对其他角色的发言做出反应）"
        knowledge = retrieve_knowledge(
            owner_user_id=self.player_id,
            character_id=trigger_character_id,
            group_thread_id=repository.get_group_thread_id(self.session_id),
            current_message=interaction_prompt,
            recent_history=history,
        )
        
        # 准备其他角色信息
        other_characters = []
        for other_id in self.character_ids:
            if other_id != trigger_character_id:
                other_card = self.character_cards.get(other_id)
                if other_card:
                    other_characters.append({
                        "character_id": other_id,
                        "name": other_card.meta.name,
                        "display_name": other_card.meta.display_name,
                        "occupation": other_card.identity.occupation
                    })
        
        # 使用 prompt_builder 构建系统提示
        system_prompt = _build_multi_character_system_prompt(
            locale=getattr(self, "locale", DEFAULT_LOCALE),
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            player_character=self.player_character,
            other_characters=other_characters,
            character_relationships=character_relationships,
            past_summaries=self._load_memory_context(
                trigger_character_id,
                character_relationships=character_relationships,
                world_now=clock_snapshot.world_now.isoformat(),
                recall_key=f"interaction:{self.session_id}:{clock_snapshot.world_now.isoformat()}",
            ),
            is_interaction=True,
            time_context=time_context,
            knowledge_context=knowledge.prompt_section,
        )
        
        messages = self._format_history_for_llm(
            history,
            trigger_character_id,
            character_relationships=character_relationships
        )
        
        # 添加互动提示
        messages.append({"role": "user", "content": interaction_prompt})
        
        # 调用 LLM
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=messages
        )
        
        dialogue = result.get("dialogue", "")
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 记录消息
        character_name = card.meta.display_name or card.meta.name
        message_id = None
        if persist:
            message_id = repository.append_multi_character_message(
                self.session_id,
                role="assistant",
                content=dialogue,
                character_id=trigger_character_id,
                character_name=character_name,
                world_created_at=clock_snapshot.world_now.isoformat(),
                knowledge_sources=knowledge.sources,
            )
        
        return {
            "character_id": trigger_character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action,
            "world_created_at": clock_snapshot.world_now.isoformat(),
            "knowledge_sources": knowledge.sources,
            "message_id": message_id,
        }
    
    












    
    


# =========================
# 便捷函数
# =========================

def start_multi_character_session(
    player_id: str,
    player_name: str,
    character_ids: list[str],
    group_name: str | None = None,
    group_thread_id: str | None = None,
    locale: Locale = DEFAULT_LOCALE,
    story_id: str | None = None,
) -> dict:
    """
    创建并启动多角色会话
    
    Args:
        player_id: 玩家 ID
        player_name: 玩家名称
        character_ids: 参与角色 ID 列表
    
    Returns:
        dict: 包含 session_id 和开场白的结果
    """
    try:
        player_character = repository.get_or_create_user_character_card(player_id)
    except Exception as exc:
        logger.warning("加载玩家角色卡失败，继续使用请求名称: %s", exc)
        player_character = None
    player_name = (player_character or {}).get("display_name") or player_name
    session_id = str(uuid.uuid4())
    
    # 创建会话
    success = repository.create_multi_character_session(
        session_id=session_id,
        player_id=player_id,
        player_name=player_name,
        character_ids=character_ids,
        group_name=group_name,
        group_thread_id=group_thread_id,
        locale=locale,
        story_id=story_id,
    )
    
    if not success:
        raise ValueError("创建多角色会话失败")

    # 初始化编排器
    orchestrator = MultiCharacterOrchestrator(session_id)

    return {
        "session_id": session_id,
        "opening": None,
        "group_name": group_name,
        "group_thread_id": repository.get_group_thread_id(session_id),
        "locale": locale,
    }


def process_multi_character_turn(
    session_id: str,
    player_message: str,
    discussion_mode: bool = True,
    max_responses: int | None = None,
    request_id: str | None = None,
    event_sink: EventSink | None = None,
    include_event_metadata: bool = False,
) -> dict | list[dict]:
    """
    处理多角色对话轮次
    
    Args:
        session_id: 会话 ID
        player_message: 玩家消息
        discussion_mode: 是否启用讨论模式（多角色连续发言）
        max_responses: 可选的人数上限；不传时按语境动态决定
        event_sink: 可选的流式事件回调
        include_event_metadata: 是否返回整轮事件元数据

    Returns:
        dict | list[dict]: 角色回应结果，或带整轮事件元数据的内部信封
    """
    with performance.measure("multi_dialogue.turn.total"):
        effective_request_id = request_id or uuid.uuid4().hex
        orchestrator = MultiCharacterOrchestrator(session_id)
        result = orchestrator.process_player_message(
            player_message,
            allow_multiple_responses=discussion_mode,
            max_responses=max_responses,
            request_id=effective_request_id,
            event_sink=event_sink,
        )
        if not include_event_metadata:
            return result

        batch = repository.get_event_execution_batch(
            orchestrator.player_id,
            f"multi:{session_id}:{effective_request_id}",
        )
        stored_results = json.loads(batch["results_data"]) if batch else []
        event_results = [
            EventTriggerResult.model_validate(item)
            for item in stored_results
        ]
        return {
            "turn_response": result,
            "event_executions": [
                event_result.model_dump(mode="json")
                for event_result in event_results
            ],
            "event_notifications": event_runtime.collect_event_notifications(
                event_results
            ),
        }