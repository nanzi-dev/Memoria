"""
多角色对话记忆与持久化操作

职责：
- 应用群聊事件结果（状态变更、事件触发）
- 持久化生成的对话消息
- 构建玩家检查点记忆的后台任务
"""

from __future__ import annotations

import logging

from memoria.core import (
    event_runtime,
    multi_character_memory,
    performance,
)
from memoria.core.config import configs
from memoria.core.memory_extractor import is_memory_worthy_candidate
from memoria.db import repository

from memoria.core.multi_character_context import GroupTurnContext

logger = logging.getLogger(__name__)


def _orchestrator_module():
    """延迟获取编排器模块，确保测试对编排器模块辅助函数的 monkeypatch 依然生效。"""
    from memoria.core import multi_character_orchestrator as _module
    return _module


# =========================
# 记忆与持久化 Mixin
# =========================

class MultiCharacterMemoryOpsMixin:
    """Mixin：为 MultiCharacterOrchestrator 提供事件处理与持久化能力。"""

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
        state_fields = {
            "character_id",
            "current_affinity",
            "current_trust",
            "current_mood",
        }
        responding_character_ids = {
            response["character_id"]
            for response in responses
            if response.get("character_id")
        }
        has_event_context = bool(getattr(self, "player_id", None)) and (
            not responses
            or all(state_fields <= response.keys() for response in responses)
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
            event_context_cache: dict = {}
            for character_id, response, response_index in ordered_context_inputs:
                if response is not None and (
                    required_response_fields <= response.keys()
                ):
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
                    # 响应未携带完整状态字段（或为未发言角色）时，
                    # 从已存储的运行时状态读取，让事件上下文仍然能为该角色构建。
                    runtime_state = repository.get_runtime_state(
                        character_id,
                        self.player_id,
                        getattr(self, "character_cards", {}).get(character_id),
                    )
                    if response is not None:
                        stored_affinity = float(
                            response.get(
                                "_previous_affinity",
                                runtime_state.get("affection_level", 0),
                            )
                            or 0
                        )
                        stored_trust = float(
                            response.get(
                                "_previous_trust",
                                runtime_state.get("trust_level", 0),
                            )
                            or 0
                        )
                    else:
                        stored_affinity = float(
                            runtime_state.get("affection_level", 0) or 0
                        )
                        stored_trust = float(
                            runtime_state.get("trust_level", 0) or 0
                        )
                    current_affinity = float(
                        response.get("current_affinity", stored_affinity)
                        if response is not None
                        else stored_affinity
                    )
                    current_trust = float(
                        response.get("current_trust", stored_trust)
                        if response is not None
                        else stored_trust
                    )
                    current_mood = (
                        response.get(
                            "current_mood",
                            runtime_state.get("current_mood", "neutral"),
                        )
                        if response is not None
                        else runtime_state.get("current_mood", "neutral")
                    )
                    previous_affinity = stored_affinity
                    previous_trust = stored_trust
                    affinity_delta = (
                        response.get(
                            "affinity_delta",
                            current_affinity - stored_affinity,
                        )
                        if response is not None
                        else 0
                    )
                    trust_delta = (
                        response.get(
                            "trust_delta",
                            current_trust - stored_trust,
                        )
                        if response is not None
                        else 0
                    )
                    npc_response = response.get("dialogue") if response is not None else None
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
                    shared_cache=event_context_cache,
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
                affinity_delta_before = response.get(
                    "affinity_delta",
                    response["current_affinity"]
                    - float(context.previous_affinity or 0),
                )
                response["affinity_delta"] = round(
                    affinity_delta_before
                    + (
                        response["current_affinity"]
                        - float(context.current_affinity or 0)
                    ),
                    6,
                )
                trust_delta_before = response.get(
                    "trust_delta",
                    response["current_trust"]
                    - float(context.previous_trust or 0),
                )
                response["trust_delta"] = round(
                    trust_delta_before
                    + (
                        response["current_trust"]
                        - float(context.current_trust or 0)
                    ),
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
                runtime_states = []
            runtime_states = list(runtime_states)
            for index, response in enumerate(responses):
                context = contexts_by_response_index.get(index)
                if context is not None:
                    previous_affinity = float(context.previous_affinity or 0)
                    previous_trust = float(context.previous_trust or 0)
                elif all(
                    key in response
                    for key in (
                        "character_id",
                        "current_affinity",
                        "current_trust",
                        "current_mood",
                    )
                ):
                    # 未携带上下文基线（如事件系统关闭或字段缺失）时，
                    # 回退到已存储的运行时状态，保证 delta 与状态增量仍然落库。
                    stored = repository.get_runtime_state(
                        response["character_id"],
                        self.player_id,
                        getattr(self, "character_cards", {}).get(
                            response["character_id"]
                        ),
                    )
                    previous_affinity = float(
                        response.get(
                            "_previous_affinity",
                            stored.get("affection_level"),
                        )
                        or 0
                    )
                    previous_trust = float(
                        response.get("_previous_trust", stored.get("trust_level"))
                        or 0
                    )
                else:
                    # 响应缺少状态字段（如测试替身），不补算 delta
                    continue
                response["affinity_delta"] = round(
                    response["current_affinity"] - previous_affinity,
                    6,
                )
                response["trust_delta"] = round(
                    response["current_trust"] - previous_trust,
                    6,
                )
                if not any(
                    state.get("character_id") == response["character_id"]
                    for state in runtime_states
                ):
                    runtime_states.append({
                        "character_id": response["character_id"],
                        "affection_level": response["current_affinity"],
                        "trust_level": response["current_trust"],
                        "current_mood": response["current_mood"],
                        "insert_only": True,
                    })
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


    def _persist_generated_response(
        self, response: dict, clock_snapshot, runtime_state: dict | None = None
    ) -> int:
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
                if runtime_state:
                    repository.save_runtime_state(
                        response["character_id"],
                        self.player_id,
                        runtime_state["affection_level"],
                        runtime_state["trust_level"],
                        runtime_state["current_mood"],
                    )
                return int(message_id)

        message_id = repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            runtime_state=runtime_state,
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
        world_occurred_at = next(
            (
                str(message.get("world_created_at"))
                for message in reversed(messages)
                if message.get("world_created_at")
            ),
            None,
        ) or _orchestrator_module()._clock_snapshot_for_player(
            self.player_id
        ).world_now.isoformat()
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
                "witness_character_ids": list(self.character_ids),
                "evidence_id": (
                    f"group-checkpoint:{self.session_id}:{checkpoint_turn}"
                ),
                "world_occurred_at": world_occurred_at,
            },
        }]


