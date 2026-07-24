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


# =========================
# 工具函数
# =========================

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
# 多角色对话编排器
# =========================

class MultiCharacterOrchestrator:
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
            repository.fail_dialogue_turn(
                self.session_id,
                request_id,
                lease_owner,
                str(exc),
            )
            raise


    def _apply_group_event_results(
        self,
        player_text: str,
        responses: list[dict],
        *,
        clock_snapshot,
        request_id: str,
        lease_owner: str,
        player_message: dict,
        turn_context: GroupTurnContext | None = None,
    ) -> list:
        required_response_fields = {
            "character_id",
            "current_affinity",
            "current_trust",
            "current_mood",
            "_previous_affinity",
            "_previous_trust",
        }
        responding_character_ids = {
            response["character_id"]
            for response in responses
            if response.get("character_id")
        }
        has_event_context = bool(getattr(self, "player_id", None)) and (
            not responses
            or all(
                required_response_fields <= response.keys()
                for response in responses
            )
        )
        contexts = []
        nonresponder_character_ids: set[str] = set()
        if has_event_context:
            relationships = (
                turn_context.character_relationships
                if turn_context is not None
                else self._load_all_relationships()
            )
            nonresponder_character_ids = {
                participant["character_id"]
                for participant in self.participants
                if participant["character_id"] not in responding_character_ids
            }
            ordered_context_inputs = [
                (response["character_id"], response, response_index)
                for response_index, response in enumerate(responses)
            ] + [
                (participant["character_id"], None, None)
                for participant in self.participants
                if participant["character_id"] not in responding_character_ids
            ]
            for character_id, response, response_index in ordered_context_inputs:
                if response is not None:
                    current_affinity = response["current_affinity"]
                    current_trust = response["current_trust"]
                    current_mood = response["current_mood"]
                    previous_affinity = response["_previous_affinity"]
                    previous_trust = response["_previous_trust"]
                    affinity_delta = response.get(
                        "affinity_delta",
                        current_affinity - previous_affinity,
                    )
                    trust_delta = response.get(
                        "trust_delta",
                        current_trust - previous_trust,
                    )
                    npc_response = response.get("dialogue")
                else:
                    runtime_state = repository.get_runtime_state(
                        character_id,
                        self.player_id,
                        self.character_cards.get(character_id),
                    )
                    current_affinity = runtime_state["affection_level"]
                    current_trust = runtime_state["trust_level"]
                    current_mood = runtime_state["current_mood"]
                    previous_affinity = current_affinity
                    previous_trust = current_trust
                    affinity_delta = 0
                    trust_delta = 0
                    npc_response = None
                contexts.append(event_runtime.build_event_context(
                    character_id=character_id,
                    player_id=self.player_id,
                    session_id=self.session_id,
                    current_affinity=current_affinity,
                    current_trust=current_trust,
                    current_mood=current_mood,
                    previous_affinity=previous_affinity,
                    previous_trust=previous_trust,
                    affinity_delta=affinity_delta,
                    trust_delta=trust_delta,
                    player_message=player_text,
                    npc_response=npc_response,
                    character_relationships=relationships,
                    world_time=clock_snapshot.world_now.isoformat(),
                    execution_key=f"multi:{self.session_id}:{request_id}",
                    trigger_source="multi_dialogue",
                    current_user_turn_persisted=False,
                    response_index=response_index,
                ))

        turn_holder: dict = {}

        def build_dialogue_turn(event_results: list) -> dict:
            if turn_holder:
                return turn_holder["turn"]
            contexts_by_response_index = {
                context.response_index: context
                for context in contexts
                if context.response_index is not None
            }
            response_counts_by_character = {
                character_id: sum(
                    response.get("character_id") == character_id
                    for response in responses
                )
                for character_id in responding_character_ids
            }
            for response_index, response in enumerate(responses):
                context = contexts_by_response_index.get(response_index)
                if context is None:
                    continue
                character_results = [
                    result
                    for result in event_results
                    if result.response_index == response_index
                    or (
                        result.response_index is None
                        and result.character_id == response["character_id"]
                        and response_counts_by_character[
                            response["character_id"]
                        ] == 1
                    )
                ]
                (
                    response["dialogue"],
                    response["current_affinity"],
                    response["current_trust"],
                    response["current_mood"],
                    response["triggered_events"],
                    response["event_notification"],
                ) = event_runtime.apply_event_results_to_dialogue_state(
                    character_results,
                    response["dialogue"],
                    response["current_affinity"],
                    response["current_trust"],
                    response["current_mood"],
                )
                response["affinity_delta"] = round(
                    response["current_affinity"] - float(context.previous_affinity or 0),
                    6,
                )
                response["trust_delta"] = round(
                    response["current_trust"] - float(context.previous_trust or 0),
                    6,
                )
                response["event_executions"] = [
                    result.model_dump(mode="json") for result in character_results
                ]
                response["event_notifications"] = (
                    event_runtime.collect_event_notifications(character_results)
                )

            if contexts:
                runtime_states = event_runtime._runtime_states_after_contexts(
                    contexts,
                    event_results,
                    insert_only_unchanged_character_ids=nonresponder_character_ids,
                    apply_state_changes_to_current_character_ids=(
                        nonresponder_character_ids
                    ),
                )
            else:
                runtime_states = [
                    {
                        "character_id": response["character_id"],
                        "affection_level": response["current_affinity"],
                        "trust_level": response["current_trust"],
                        "current_mood": response["current_mood"],
                    }
                    for response in responses
                    if all(
                        key in response
                        for key in (
                            "character_id",
                            "current_affinity",
                            "current_trust",
                            "current_mood",
                        )
                    )
                ]
            messages = [{
                **player_message,
                "temporary_id": player_message["message_id"],
            }]
            for index, response in enumerate(responses):
                response.pop("_previous_affinity", None)
                response.pop("_previous_trust", None)
                messages.append({
                    "role": "assistant",
                    "content": response.get("dialogue", ""),
                    "character_id": response.get("character_id"),
                    "character_name": response.get("character_name"),
                    "action": response.get("action"),
                    "affinity_delta": response.get("affinity_delta"),
                    "trust_delta": response.get("trust_delta"),
                    "current_affinity": response.get("current_affinity"),
                    "current_trust": response.get("current_trust"),
                    "current_mood": response.get("current_mood"),
                    "event_notification": response.get("event_notification"),
                    "world_created_at": response.get("world_created_at"),
                    "knowledge_sources": response.get("knowledge_sources") or [],
                    "reply_to_message_id": response.get("reply_to_message_id"),
                    "reply_to_character_id": response.get("reply_to_character_id"),
                    "intent": response.get("intent"),
                    "topic": response.get("topic"),
                    "trigger_source": response.get("trigger_source"),
                    "temporary_id": response.get("message_id"),
                    "response_index": index,
                    "response_field": "message_id",
                })
            group_state = {
                **getattr(self, "last_pulse_state", {}),
                "group_thread_id": (
                    (
                        turn_context.group_thread_id
                        if turn_context is not None
                        else repository.get_group_thread_id(self.session_id)
                    )
                    or self.session_id
                ),
            }
            turn = {
                "session_id": self.session_id,
                "request_id": request_id,
                "player_id": self.player_id,
                "lease_owner": lease_owner,
                "response": responses,
                "runtime_states": runtime_states,
                "messages": messages,
                "group_state": group_state,
                "background_jobs": self._build_player_checkpoint_background_jobs(
                    messages
                ),
            }
            turn_holder["turn"] = turn
            return turn

        event_results = []
        if contexts:
            event_results = event_runtime.detect_and_execute_event_contexts(
                contexts,
                dialogue_turn_factory=build_dialogue_turn,
            )
        if not turn_holder:
            turn = build_dialogue_turn(event_results)
            repository.commit_dialogue_turn(
                dialogue_turn=turn,
                runtime_states=turn["runtime_states"],
            )
        return event_results


    def _persist_generated_response(self, response: dict, clock_snapshot) -> int:
        world_created_at = (
            response.get("world_created_at")
            or clock_snapshot.world_now.isoformat()
        )
        message_id = response.get("message_id")
        persistence_fields = {
            "content": response["dialogue"],
            "character_id": response["character_id"],
            "character_name": response["character_name"],
            "world_created_at": world_created_at,
            "knowledge_sources": response.get("knowledge_sources") or [],
            "reply_to_message_id": response.get("reply_to_message_id"),
            "reply_to_character_id": response.get("reply_to_character_id"),
            "intent": response.get("intent"),
            "topic": response.get("topic"),
            "trigger_source": response.get("trigger_source"),
        }
        if message_id is not None:
            updated = repository.update_multi_character_message(
                int(message_id),
                self.session_id,
                **persistence_fields,
            )
            if updated:
                return int(message_id)

        message_id = repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            **persistence_fields,
        )
        response["message_id"] = message_id
        return message_id


    def _build_player_checkpoint_background_jobs(
        self,
        messages: list[dict],
    ) -> list[dict]:
        checkpoint_interval = configs.long_term_memory_interval_turns
        checkpoint_turn = (
            repository.get_session_user_turn_count(self.session_id) + 1
        )
        if checkpoint_turn % checkpoint_interval != 0 or not self.player_id:
            return []
        generated_scope = multi_character_memory.resolve_generated_fact_scope(
            self.session_id
        )
        if not generated_scope:
            return []
        scope_type, scope_id = generated_scope
        history_limit = max(12, checkpoint_interval * 4)
        history = repository.get_multi_character_thread_history(
            self.session_id,
            limit_messages=history_limit,
        )
        history.extend(
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in messages
        )
        history = history[-history_limit:]
        if not is_memory_worthy_candidate(
            history,
            max_messages=checkpoint_interval,
        ):
            performance.increment("llm.calls_avoided.memory_gate")
            return []
        return [{
            "job_type": "group_checkpoint_memory",
            "dedupe_key": (
                f"group_checkpoint_memory:{self.session_id}:{checkpoint_turn}"
            ),
            "payload": {
                "owner_user_id": self.player_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "session_id": self.session_id,
                "history": history,
            },
        }]

    def _decide_group_response_count(
        self,
        player_message: str,
        max_responses: int | None = None,
        turn_context: GroupTurnContext | None = None,
    ) -> int:
        """按群聊语境决定本轮实际接话人数。"""
        participant_count = len(self.participants)
        if participant_count <= 1:
            return participant_count

        requested_cap = max_responses or participant_count
        try:
            requested_cap = int(requested_cap)
        except Exception:
            requested_cap = participant_count
        cap = min(max(1, requested_cap), participant_count, 4)

        text = (player_message or "").strip()
        if not text:
            return 1

        mentioned_ids = self._find_mentioned_character_ids(text)
        mentioned = len(mentioned_ids)

        if mentioned == 1:
            return 1
        if mentioned >= 2:
            return min(cap, max(2, mentioned))

        broad_cues = (
            "大家", "你们", "各位", "都", "一起", "商量", "讨论", "投票", "选择",
            "怎么办", "怎么看", "意见", "想法", "谁", "有没有", "要不要", "为什么",
        )
        high_stakes_cues = (
            "危险", "紧急", "马上", "立刻", "救", "逃", "战斗", "计划", "决定",
            "分工", "调查", "线索", "真相", "冲突", "怀疑", "背叛", "秘密",
        )
        short_ack = text in {"好", "好的", "嗯", "哦", "行", "可以", "知道了", "明白", "没事"}
        is_question = any(mark in text for mark in ("?", "？", "吗", "呢"))

        if short_ack:
            weights = [(1, 0.9), (2, 0.1)]
        else:
            conversation_pressure = 0.0
            if any(cue in text for cue in broad_cues):
                conversation_pressure += 1.6
            if is_question:
                conversation_pressure += 0.8
            if any(cue in text for cue in high_stakes_cues):
                conversation_pressure += 0.9
            if len(text) >= 36:
                conversation_pressure += 0.5
            if len(text) >= 80:
                conversation_pressure += 0.5

            relation_pressure = self._relationship_pressure_for_group(turn_context)
            if relation_pressure >= 70:
                conversation_pressure += 0.8
            elif relation_pressure >= 40:
                conversation_pressure += 0.35

            if conversation_pressure >= 2.6:
                weights = [(1, 0.12), (2, 0.42), (3, 0.34), (4, 0.12)]
            elif conversation_pressure >= 1.4:
                weights = [(1, 0.35), (2, 0.45), (3, 0.17), (4, 0.03)]
            elif conversation_pressure >= 0.8:
                weights = [(1, 0.58), (2, 0.33), (3, 0.09)]
            else:
                weights = [(1, 0.78), (2, 0.18), (3, 0.04)]

        available = [(count, weight) for count, weight in weights if count <= cap]
        total = sum(weight for _, weight in available)
        pick = random.uniform(0, total)
        upto = 0.0
        for count, weight in available:
            upto += weight
            if pick <= upto:
                return count
        return available[-1][0]


    def _find_mentioned_character_ids(self, text: str) -> set[str]:
        """找出玩家消息中直接提到的角色。"""
        mentioned = set()
        for char_id, card in self.character_cards.items():
            meta = getattr(card, "meta", None)
            if not meta:
                continue
            names = [
                getattr(meta, "name", None),
                getattr(meta, "display_name", None),
            ]
            names.extend(getattr(meta, "aliases", []) or [])
            if any(name and str(name) in text for name in names):
                mentioned.add(char_id)
        return mentioned


    def _relationship_pressure_for_group(
        self,
        turn_context: GroupTurnContext | None = None,
    ) -> float:
        """估算当前群聊关系强度，越高越适合多人接话。"""
        relationships = (
            turn_context.character_relationships
            if turn_context is not None
            else self._load_all_relationships()
        )
        if not relationships:
            return 0.0
        values = []
        for rel in relationships.values():
            values.append(abs(_safe_float(rel.get("affinity", 0))))
        return sum(values) / len(values) if values else 0.0
    
    
    def _generate_group_discussion(
        self,
        player_message: str,
        max_responses: int = 3,
        *,
        clock_snapshot=None,
        trigger_message_id: int | None = None,
        staged_history: list[dict] | None = None,
        event_sink: EventSink | None = None,
        request_id: str | None = None,
        turn_context: GroupTurnContext | None = None,
    ) -> list[dict]:
        """兼容旧调用名，内部执行逐条重决策的对话脉冲。"""
        return self.run_dialogue_pulse(
            trigger_source="player",
            trigger_text=player_message,
            trigger_message_id=trigger_message_id,
            max_messages=max_responses,
            clock_snapshot=clock_snapshot,
            persist_state=False,
            persist_messages=False,
            staged_history=staged_history,
            event_sink=event_sink,
            request_id=request_id,
            turn_context=turn_context,
        )


    def run_dialogue_pulse(
        self,
        *,
        trigger_source: str,
        trigger_text: str | None = None,
        trigger_message_id: int | None = None,
        initial_speaker_id: str | None = None,
        max_messages: int = 3,
        clock_snapshot=None,
        persist_state: bool = True,
        persist_messages: bool = True,
        extract_memory: bool = False,
        staged_history: list[dict] | None = None,
        event_sink: EventSink | None = None,
        request_id: str | None = None,
        turn_context: GroupTurnContext | None = None,
    ) -> list[dict]:
        """每生成一条消息后重新决定下一动作。"""
        self._ensure_has_active_participants()
        clock_snapshot = clock_snapshot or _clock_snapshot_for_player(self.player_id)
        turn_context = turn_context or self._load_group_turn_context()
        max_messages = min(3, max(1, int(max_messages or 1)))
        responses: list[dict] = []
        decisions: list[DialogueDecision] = []
        staged_messages: list[dict] = []
        base_history = None
        if not persist_messages:
            base_history = repository.get_multi_character_thread_history(
                self.session_id,
                limit_messages=30,
            )

        for step in range(max_messages):
            stream_id = f"{request_id}:{step}" if request_id else None
            if persist_messages:
                history = repository.get_multi_character_thread_history(
                    self.session_id,
                    limit_messages=30,
                )
            else:
                history = [
                    *(base_history or []),
                    *(staged_history or []),
                    *staged_messages,
                ]
            if trigger_source == "player":
                decision = self._fallback_dialogue_decision(
                    history=history,
                    trigger_text=trigger_text or "",
                    trigger_message_id=trigger_message_id,
                    initial_speaker_id=initial_speaker_id if step == 0 else None,
                    previous_responses=responses,
                    turn_context=turn_context,
                    force_speak=True,
                )
                if step == max_messages - 1:
                    decision = decision.model_copy(update={"wait_for_player": True})
                performance.increment("llm.calls_avoided.group_dialogue_decision")
            else:
                decision = self._decide_dialogue_action(
                    history=history,
                    trigger_source=trigger_source,
                    trigger_text=trigger_text or "",
                    trigger_message_id=trigger_message_id,
                    initial_speaker_id=initial_speaker_id if step == 0 else None,
                    previous_responses=responses,
                    turn_context=turn_context,
                )
            decisions.append(decision)
            if decision.action == "wait":
                break

            target = next(
                (msg for msg in reversed(history) if msg.get("message_id") == decision.reply_to_message_id),
                history[-1] if history else None,
            )
            result = self._generate_character_response(
                decision.speaker_id,
                str((target or {}).get("content") or trigger_text or ""),
                decision=decision,
                trigger_source=trigger_source if step == 0 else "npc_follow_up",
                target_message=target,
                clock_snapshot=clock_snapshot,
                persist=False,
                history_override=history,
                event_sink=event_sink,
                stream_id=stream_id,
                turn_context=turn_context,
            )
            if self._is_redundant_dialogue_response(
                result,
                history=history,
                accepted_responses=responses,
            ):
                logger.warning(
                    "抑制重复群聊回复: session=%s, character=%s, reply_to=%s",
                    self.session_id,
                    result.get("character_id"),
                    result.get("reply_to_message_id"),
                )
                decisions.pop()
                decisions.append(DialogueDecision(
                    action="wait",
                    wait_for_player=True,
                    stop_reason="duplicate_response",
                ))
                break
            if persist_messages:
                if all(
                    key in result
                    for key in (
                        "character_id",
                        "current_affinity",
                        "current_trust",
                        "current_mood",
                    )
                ):
                    repository.save_runtime_state(
                        result["character_id"],
                        self.player_id,
                        result["current_affinity"],
                        result["current_trust"],
                        result["current_mood"],
                    )
                if (
                    result.get("message_id") is None
                    and result.get("character_id")
                    and result.get("character_name")
                ):
                    self._persist_generated_response(result, clock_snapshot)
            else:
                temporary_message_id = -(
                    len(staged_messages) + len(staged_history or []) + 1
                )
                result["message_id"] = temporary_message_id
                staged_messages.append({
                    "message_id": temporary_message_id,
                    "role": "assistant",
                    "content": result.get("dialogue", ""),
                    "character_id": result.get("character_id"),
                    "character_name": result.get("character_name"),
                    "world_created_at": result.get("world_created_at"),
                    "knowledge_sources": result.get("knowledge_sources") or [],
                    "reply_to_message_id": result.get("reply_to_message_id"),
                    "reply_to_character_id": result.get("reply_to_character_id"),
                    "intent": result.get("intent"),
                    "topic": result.get("topic"),
                    "trigger_source": result.get("trigger_source"),
                })
            if event_sink and stream_id:
                event_sink(
                    "character_completed",
                    {
                        "stream_id": stream_id,
                        "character_id": result.get("character_id"),
                        "response": result,
                    },
                )
            responses.append(result)
            self.last_speaker_id = decision.speaker_id
            if decision.wait_for_player:
                break

        pulse_state = self._build_pulse_state(decisions, responses, trigger_source)
        self.last_pulse_state = pulse_state
        if persist_state:
            repository.save_group_dialogue_state(
                turn_context.group_thread_id or self.session_id,
                self.player_id,
                **pulse_state,
            )
        if extract_memory and responses:
            multi_character_memory.process_dialogue_pulse_memories(
                session_id=self.session_id,
                recent_messages=[
                    {
                        "role": "assistant",
                        "content": response.get("dialogue", ""),
                        "character_id": response.get("character_id"),
                        "character_name": response.get("character_name"),
                    }
                    for response in responses
                ],
                character_ids=self.character_ids,
                player_id=self.player_id,
            )
        return responses


    @staticmethod
    def _is_redundant_dialogue_response(
        result: dict,
        *,
        history: list[dict],
        accepted_responses: list[dict],
    ) -> bool:
        dialogue = str(result.get("dialogue") or "").strip()
        speaker_id = result.get("character_id")
        if not dialogue or not speaker_id:
            return True

        candidates = [
            str(response.get("dialogue") or "")
            for response in accepted_responses
            if response.get("character_id") == speaker_id
        ]
        reply_to_message_id = result.get("reply_to_message_id")
        recent_message_ids = {
            message.get("message_id")
            for message in history[-4:]
        }
        candidates.extend(
            str(message.get("content") or "")
            for message in history
            if message.get("role") == "assistant"
            and message.get("character_id") == speaker_id
            and (
                message.get("message_id") in recent_message_ids
                or message.get("message_id") == reply_to_message_id
                or message.get("reply_to_message_id") == reply_to_message_id
            )
        )
        return any(
            repository.dialogue_texts_redundant(dialogue, candidate)
            for candidate in candidates
        )


    def _decide_dialogue_action(
        self,
        *,
        history: list[dict],
        trigger_source: str,
        trigger_text: str,
        trigger_message_id: int | None,
        initial_speaker_id: str | None,
        previous_responses: list[dict],
        turn_context: GroupTurnContext | None = None,
    ) -> DialogueDecision:
        prompt = self._build_dialogue_decision_prompt(
            history=history,
            trigger_source=trigger_source,
            trigger_text=trigger_text,
            initial_speaker_id=initial_speaker_id,
            turn_context=turn_context,
        )
        try:
            raw = llm_client.call_light_task(
                prompt,
                allow_reasoning_fallback=False,
                task_name="group_dialogue_decision",
                max_tokens=120,
                max_attempts=1,
            )
            decision = self._parse_dialogue_decision(raw)
            return self._validate_dialogue_decision(
                decision,
                history=history,
                trigger_message_id=trigger_message_id,
            )
        except Exception as exc:
            logger.warning("群聊动作决策失败，使用确定性降级: %s", exc)
            return self._fallback_dialogue_decision(
                history=history,
                trigger_text=trigger_text,
                trigger_message_id=trigger_message_id,
                initial_speaker_id=initial_speaker_id,
                previous_responses=previous_responses,
                turn_context=turn_context,
            )


    def _build_dialogue_decision_prompt(
        self,
        *,
        history: list[dict],
        trigger_source: str,
        trigger_text: str,
        initial_speaker_id: str | None,
        turn_context: GroupTurnContext | None = None,
    ) -> str:
        if turn_context is None:
            player_character = self._refresh_player_character()
            group_thread_id = repository.get_group_thread_id(self.session_id)
        else:
            player_character = turn_context.player_character
            group_thread_id = turn_context.group_thread_id
        participants = []
        for participant in self.participants:
            character_id = participant["character_id"]
            card = self.character_cards.get(character_id)
            if not card:
                continue
            goals = getattr(card, "goals_and_motivations", None)
            rules = getattr(card, "interaction_rules", None)
            background = getattr(card, "background", None)
            participants.append({
                "character_id": character_id,
                "name": card.meta.display_name or card.meta.name,
                "current_goals": list(getattr(goals, "current_goals", []) or []),
                "long_term_goals": list(getattr(goals, "long_term_goals", []) or []),
                "loved_topics": list(getattr(rules, "topics_he_or_she_loves_to_discuss", []) or []),
                "avoid_topics": list(getattr(rules, "topics_to_avoid_unless_trusted", []) or []),
                "anger_triggers": list(getattr(goals, "what_triggers_anger", []) or []),
                "joy_triggers": list(getattr(goals, "what_brings_joy", []) or []),
                "secrets": [
                    str(getattr(secret, "secret", "") or "")
                    for secret in list(getattr(background, "secrets", []) or [])[:3]
                ],
                "relationships": [
                    {
                        "target": getattr(relation, "target", ""),
                        "type": getattr(relation, "relationship_type", ""),
                        "description": getattr(relation, "description", ""),
                    }
                    for relation in list(getattr(background, "relationships", []) or [])[:5]
                ],
                "message_count": int(participant.get("message_count") or 0),
            })

        recent_history = [
            {
                "message_id": message.get("message_id"),
                "speaker_id": message.get("character_id") or "player",
                "speaker_name": message.get("character_name") or self.player_name,
                "content": str(message.get("content") or "")[:500],
                "reply_to_message_id": message.get("reply_to_message_id"),
                "intent": message.get("intent"),
                "topic": message.get("topic"),
            }
            for message in history[-12:]
        ]
        thread_state = repository.get_group_dialogue_state(
            group_thread_id or self.session_id
        ) or {}
        schema_example = {
            "action": "speak",
            "speaker_id": "character_id",
            "reply_to_message_id": 123,
            "reply_to_character_id": "character_id_or_null",
            "intent": "answer",
            "topic": "当前话题",
            "preferred_next_character_id": None,
            "follow_up_expected": False,
            "wait_for_player": False,
            "stop_reason": None,
        }
        return "\n".join([
            "你是多角色剧情群聊的单步动作决策器，只决定下一步，不生成对白。",
            "话题优先级：明确事件/未解决钩子 > 目标、秘密、关系冲突 > 最新问题或点名 > 情绪关系延伸 > 喜爱话题。",
            "普通闲聊不能连续开启无剧情价值的新话题。连续发言和发言次数只降低优先级，不得硬性排除角色。",
            "若最新发言明确等待某角色、追问、反驳或点名，允许同一角色再次发言。没有自然后续时 action=wait。",
            "后续发言必须承接最近一条有效消息推进内容；如果只能重复已有表达，必须选择 action=wait。",
            "回复必须指向历史中真实 message_id；面向玩家时 reply_to_character_id=null，面向 NPC 时填其 character_id。",
            f"触发来源: {trigger_source}",
            f"触发文本: {trigger_text[:800]}",
            f"首步指定发言者: {initial_speaker_id or '无'}",
            f"玩家角色卡: {json.dumps(player_character, ensure_ascii=False)}",
            f"线程状态: {json.dumps(thread_state, ensure_ascii=False)}",
            f"参与角色: {json.dumps(participants, ensure_ascii=False)}",
            f"最近历史: {json.dumps(recent_history, ensure_ascii=False)}",
            "intent 只能是 answer/ask/agree/challenge/reveal/invite/interrupt/topic_shift。",
            "只返回合法 JSON 对象，不使用 Markdown。wait 动作可将其余可选字段设为 null。",
            f"格式示例: {json.dumps(schema_example, ensure_ascii=False)}",
        ])


    @staticmethod
    def _parse_dialogue_decision(raw: str) -> DialogueDecision:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].startswith("```"):
                lines.pop()
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise
            payload = json.loads(text[start:end + 1])
        return DialogueDecision.model_validate(payload)


    def _validate_dialogue_decision(
        self,
        decision: DialogueDecision,
        *,
        history: list[dict],
        trigger_message_id: int | None,
    ) -> DialogueDecision:
        if decision.action == "wait":
            return decision.model_copy(update={"speaker_id": None})
        if decision.speaker_id not in self.character_ids:
            raise ValueError("决策发言者不在群聊中")

        valid_targets = {
            int(message["message_id"]): message
            for message in history
            if message.get("message_id") is not None
        }
        target_id = decision.reply_to_message_id or trigger_message_id
        if target_id not in valid_targets:
            if not history:
                raise ValueError("没有可回复的群聊消息")
            target_id = int(history[-1]["message_id"])
        target = valid_targets[target_id]
        target_character_id = target.get("character_id")
        if decision.reply_to_character_id not in {None, *self.character_ids}:
            raise ValueError("决策回复目标角色不在群聊中")
        return decision.model_copy(update={
            "reply_to_message_id": target_id,
            "reply_to_character_id": target_character_id,
            "intent": decision.intent or "answer",
            "topic": (decision.topic or str(target.get("topic") or "").strip() or None),
        })


    def _fallback_dialogue_decision(
        self,
        *,
        history: list[dict],
        trigger_text: str,
        trigger_message_id: int | None,
        initial_speaker_id: str | None,
        previous_responses: list[dict],
        turn_context: GroupTurnContext | None = None,
        force_speak: bool = False,
    ) -> DialogueDecision:
        latest = history[-1] if history else {}
        if previous_responses and not force_speak:
            latest_text = str(latest.get("content") or "")
            mentioned = self._find_mentioned_character_ids(latest_text)
            continuation_cues = ("?", "？", "但是", "不过", "为什么", "你呢", "怎么看", "反对", "不对")
            if not mentioned and not any(cue in latest_text for cue in continuation_cues):
                return DialogueDecision(action="wait", wait_for_player=True, stop_reason="no_natural_follow_up")

        target = latest
        if force_speak and trigger_message_id is not None:
            target = next(
                (
                    message
                    for message in reversed(history)
                    if message.get("message_id") == trigger_message_id
                ),
                latest,
            )
        context = {
            "player_message": (
                trigger_text
                if force_speak
                else str(latest.get("content") or trigger_text)
            ),
            "last_speaker_id": latest.get("character_id") or self.last_speaker_id,
            "character_relationships": (
                turn_context.character_relationships
                if turn_context is not None
                else self._load_all_relationships()
            ),
            "previous_responses": previous_responses,
            "history": history,
            "selection_seed": (
                f"{self.session_id}:{trigger_message_id or target.get('message_id') or ''}:"
                f"{len(previous_responses)}"
            ),
        }
        speaker_id = initial_speaker_id if initial_speaker_id in self.character_ids else None
        if not speaker_id:
            spoken_ids = {
                response.get("character_id")
                for response in previous_responses
                if response.get("character_id")
            }
            candidates = [
                participant
                for participant in self.participants
                if participant.get("character_id") not in spoken_ids
            ] or self.participants
            strategy = getattr(self, "speaking_strategy", None)
            if strategy is not None:
                speaker_id = strategy.select_speaker(
                    candidates,
                    self.character_cards,
                    context,
                )
            else:
                speaker_id = (
                    candidates[0].get("character_id")
                    if candidates
                    else None
                )
        target_id = target.get("message_id") or trigger_message_id
        return DialogueDecision(
            action="speak",
            speaker_id=speaker_id,
            reply_to_message_id=target_id,
            reply_to_character_id=target.get("character_id"),
            intent="answer" if target.get("role") == "user" else "agree",
            topic=str(target.get("topic") or trigger_text or "")[:120] or None,
        )


    def _build_pulse_state(
        self,
        decisions: list[DialogueDecision],
        responses: list[dict],
        trigger_source: str,
    ) -> dict:
        spoken = [decision for decision in decisions if decision.action == "speak"]
        final = decisions[-1] if decisions else DialogueDecision(action="wait", wait_for_player=True)
        hooks = []
        for decision, response in zip(spoken, responses):
            if decision.follow_up_expected:
                hooks.append({
                    "message_id": response.get("message_id"),
                    "character_id": decision.speaker_id,
                    "preferred_next_character_id": decision.preferred_next_character_id,
                    "topic": decision.topic,
                })
        last = spoken[-1] if spoken else None
        return {
            "current_topic": last.topic if last else None,
            "topic_source": trigger_source,
            "last_reply_to_message_id": last.reply_to_message_id if last else None,
            "last_reply_to_character_id": last.reply_to_character_id if last else None,
            "last_speaker_id": last.speaker_id if last else None,
            "waiting_for_player": bool(final.wait_for_player or final.action == "wait"),
            "unresolved_hooks": hooks,
        }
    
    
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


    def _load_memory_context(
        self,
        character_id: str,
        query_context: str | None = None,
        character_relationships: dict | None = None,
        relationship_aliases: list[str] | None = None
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
        character_relationships: dict | None = None
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
            
            # 计算权重：发言次数少的优先
            weight = 100.0 - message_count * 5
            
            # 最近没发言的优先
            if not last_spoke:
                weight += 50.0
            
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
            character_relationships=character_relationships
        )
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
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
        )
        
        # 生成开场白
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=[]
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
    
    
    def _generate_character_response(
        self,
        character_id: str,
        player_message: str,
        *,
        decision: DialogueDecision | None = None,
        trigger_source: str = "player",
        target_message: dict | None = None,
        clock_snapshot=None,
        persist: bool = True,
        history_override: list[dict] | None = None,
        event_sink: EventSink | None = None,
        stream_id: str | None = None,
        turn_context: GroupTurnContext | None = None,
    ) -> dict:
        """
        生成角色对玩家的回应
        
        Args:
            character_id: 发言角色 ID
            player_message: 玩家消息
        
        Returns:
            dict: 角色回应结果
        """
        turn_context = turn_context or self._load_group_turn_context()
        if character_id not in self.character_cards:
            raise ValueError(f"角色不可回复: {character_id}")
        card = self.character_cards[character_id]
        character_relationships = turn_context.character_relationships
        relationship_history_cutoff = multi_character_memory.get_relationship_history_cutoff(
            self.player_id,
            self.character_ids,
            character_relationships
        )
        runtime_state = self._load_runtime_state_for_prompt(
            character_id,
            card,
            relationship_history_cutoff=relationship_history_cutoff,
            character_relationships=character_relationships
        )
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
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
        history = history_override
        if history is None:
            history = repository.get_multi_character_thread_history(
                self.session_id,
                limit_messages=20,
                created_after=relationship_history_cutoff
            )
        else:
            history = _history_after_cutoff(
                history,
                relationship_history_cutoff,
            )
        knowledge = retrieve_knowledge(
            owner_user_id=self.player_id,
            character_id=character_id,
            group_thread_id=turn_context.group_thread_id,
            current_message=player_message,
            recent_history=history,
            preauthorized_knowledge_base_ids=(
                turn_context.authorized_knowledge_base_ids.get(character_id)
            ),
        )
        decision = decision or DialogueDecision(
            action="speak",
            speaker_id=character_id,
            reply_to_message_id=(target_message or {}).get("message_id"),
            reply_to_character_id=(target_message or {}).get("character_id"),
            intent="answer",
            topic=player_message[:120] or None,
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
        
        # 使用 prompt_builder 构建系统提示
        system_prompt = _build_multi_character_system_prompt(
            locale=getattr(self, "locale", DEFAULT_LOCALE),
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            player_character=turn_context.player_character,
            other_characters=other_characters,
            character_relationships=character_relationships,
            past_summaries=self._load_memory_context(
                character_id,
                character_relationships=character_relationships
            ),
            time_context=time_context,
            knowledge_context=knowledge.prompt_section,
            dialogue_target={
                "reply_to_message_id": decision.reply_to_message_id,
                "reply_to_character_id": decision.reply_to_character_id,
                "reply_to_name": (target_message or {}).get("character_name") or self.player_name,
                "message": str((target_message or {}).get("content") or player_message),
                "intent": decision.intent,
                "topic": decision.topic,
                "preferred_next_character_id": decision.preferred_next_character_id,
                "follow_up_expected": decision.follow_up_expected,
            },
        )
        
        # 转换为 LLM 格式
        messages = self._format_history_for_llm(
            history,
            character_id,
            character_relationships=character_relationships
        )
        messages.append({
            "role": "user",
            "content": (
                "[对话动作指令] "
                f"请以 {decision.intent or 'answer'} 意图回复消息 "
                f"#{decision.reply_to_message_id or 'latest'}，"
                f"目标身份为 {decision.reply_to_character_id or 'player'}，"
                f"当前话题为 {decision.topic or '延续当前话题'}。"
            ),
        })
        
        # 调用 LLM
        if event_sink and stream_id:
            event_sink(
                "character_started",
                {
                    "stream_id": stream_id,
                    "character_id": character_id,
                    "character_name": card.meta.display_name or card.meta.name,
                },
            )
        safety_stream = (
            DialogueSafetyStream(
                lambda delta: event_sink(
                    "dialogue_delta",
                    {"stream_id": stream_id, "delta": delta},
                )
            )
            if event_sink and stream_id
            else None
        )
        with performance.measure("multi_dialogue.character.generate"):
            result = llm_client.call_role_turn(
                system_prompt=system_prompt,
                history=messages,
                on_dialogue_delta=safety_stream.feed if safety_stream else None,
            )
        
        raw_dialogue = result.get("dialogue", "")
        dialogue = (
            safety_stream.finish(raw_dialogue)
            if safety_stream
            else safety_check(raw_dialogue)
        )
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 状态更新
        affinity_delta = _clip(_safe_float(result.get("affinity_delta", 0)), -10, 10)
        new_affinity = _clip(
            runtime_state.get("affection_level", 0) + affinity_delta,
            -100,
            100
        )
        
        trust_delta = _clip(_safe_float(result.get("trust_delta", 0)), -10, 10)
        new_trust = _clip(
            runtime_state.get("trust_level", 0) + trust_delta,
            0,
            100
        )
        
        mood_after = result.get("mood_after") or runtime_state.get("current_mood", "neutral")
        
        character_name = card.meta.display_name or card.meta.name
        response = {
            "character_id": character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action,
            "affinity_delta": affinity_delta,
            "trust_delta": trust_delta,
            "current_affinity": new_affinity,
            "current_trust": new_trust,
            "current_mood": mood_after,
            "world_created_at": clock_snapshot.world_now.isoformat(),
            "knowledge_sources": knowledge.sources,
            "_previous_affinity": runtime_state.get("affection_level", 0),
            "_previous_trust": runtime_state.get("trust_level", 0),
            "reply_to_message_id": decision.reply_to_message_id,
            "reply_to_character_id": decision.reply_to_character_id,
            "intent": decision.intent,
            "topic": decision.topic,
            "trigger_source": trigger_source,
        }
        if persist:
            repository.save_runtime_state(
                character_id,
                self.player_id,
                new_affinity,
                new_trust,
                mood_after,
            )
            self._persist_generated_response(response, clock_snapshot)
            response.pop("_previous_affinity", None)
            response.pop("_previous_trust", None)
        return response
    
    
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
            character_relationships=character_relationships
        )
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
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
                character_relationships=character_relationships
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
                    f"[消息 #{msg.get('message_id') or '?'} | 玩家 {self.player_name}]: {content}"
                )
                messages.append({"role": "user", "content": formatted_content})
            
            elif role == "assistant":
                source_name = char_name or char_id or "未知角色"
                target = msg.get("reply_to_character_id") or "玩家/群体"
                metadata = (
                    f"消息 #{msg.get('message_id') or '?'}，发言者 {source_name}({char_id or '?'})，"
                    f"回复消息 #{msg.get('reply_to_message_id') or '?'}，目标 {target}，"
                    f"意图 {msg.get('intent') or '未标注'}，话题 {msg.get('topic') or '未标注'}"
                )
                if char_id == current_character_id:
                    messages.append({
                        "role": "assistant",
                        "content": f"[{metadata}] {content}",
                    })
                else:
                    formatted_content = f"[{metadata}] {content}"
                    messages.append({"role": "user", "content": formatted_content})
        
        return messages
    
    
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
    
    # 生成开场白
    opening_result = orchestrator.start_conversation()
    
    return {
        "session_id": session_id,
        "opening": opening_result,
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
