"""
多角色对话轮次执行

职责：
- 执行对话脉冲（run_dialogue_pulse）
- 生成单角色回复（含流式与安全处理）
- 对话决策：谁发言、什么意图、回复哪条消息
- 群聊讨论编排：多人连续发言
"""

from __future__ import annotations

import json
import logging
import random
from typing import Callable

from memoria.core import (
    llm_client,
    multi_character_memory,
    performance,
    world_clock,
)
from memoria.core.locale import DEFAULT_LOCALE
from memoria.core.output_safety import DialogueSafetyStream, safety_check
from memoria.db import repository

from memoria.core.knowledge_retriever import retrieve_knowledge  # noqa: F401
from memoria.core.multi_character_context import (
    DialogueDecision,
    GroupTurnContext,
    _build_multi_character_system_prompt,  # noqa: F401
    _clip,
    _clock_snapshot_for_player,  # noqa: F401
    _history_after_cutoff,
    _safe_float,
)
from memoria.core.relationship_delta_policy import resolve_relationship_delta

logger = logging.getLogger(__name__)
EventSink = Callable[[str, dict], None]


def _orchestrator_module():
    """延迟获取编排器模块，确保测试对编排器模块辅助函数的 monkeypatch 依然生效。"""
    from memoria.core import multi_character_orchestrator as _module
    return _module


# =========================
# 轮次执行 Mixin
# =========================

class MultiCharacterTurnMixin:
    """Mixin：为 MultiCharacterOrchestrator 提供轮次执行与对话决策能力。"""

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
        clock_snapshot = clock_snapshot or _orchestrator_module()._clock_snapshot_for_player(
            self.player_id
        )
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
            previous_same_speaker = next(
                (
                    prior
                    for prior in reversed(responses)
                    if prior.get("character_id") == decision.speaker_id
                ),
                None,
            )
            state_overrides = None
            if previous_same_speaker is not None:
                state_overrides = {
                    "affection_level": previous_same_speaker.get("current_affinity"),
                    "trust_level": previous_same_speaker.get("current_trust"),
                    "current_mood": previous_same_speaker.get("current_mood"),
                }
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
                state_overrides=state_overrides,
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
                runtime_state = None
                if all(
                    key in result
                    for key in (
                        "character_id",
                        "current_affinity",
                        "current_trust",
                        "current_mood",
                    )
                ):
                    runtime_state = {
                        "player_id": self.player_id,
                        "affection_level": result["current_affinity"],
                        "trust_level": result["current_trust"],
                        "current_mood": result["current_mood"],
                    }
                if (
                    result.get("message_id") is None
                    and result.get("character_id")
                    and result.get("character_name")
                ):
                    # 消息与状态在同一事务内落库，避免部分持久化
                    self._persist_generated_response(
                        result, clock_snapshot, runtime_state=runtime_state
                    )
                elif runtime_state:
                    repository.save_runtime_state(
                        result["character_id"],
                        self.player_id,
                        runtime_state["affection_level"],
                        runtime_state["trust_level"],
                        runtime_state["current_mood"],
                    )
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
                result["stream_id"] = stream_id
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
                        "message_id": response.get("message_id"),
                        "role": "assistant",
                        "content": response.get("dialogue", ""),
                        "character_id": response.get("character_id"),
                        "character_name": response.get("character_name"),
                        "world_created_at": response.get("world_created_at"),
                    }
                    for response in responses
                ],
                character_ids=self.character_ids,
                player_id=self.player_id,
                pulse_id=request_id,
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
        state_overrides: dict | None = None,
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
        clock_snapshot = clock_snapshot or world_clock.get_clock_snapshot(self.player_id)
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
            character_relationships=character_relationships,
            world_now=clock_snapshot.world_now.isoformat(),
            recall_key=stream_id or f"turn:{self.session_id}",
        )
        if state_overrides:
            # 同一脉冲内该角色已发言过：以内存中的最新状态为基线，
            # 避免第二次发言覆盖第一次的状态增量。
            runtime_state.update(state_overrides)
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
        knowledge = _orchestrator_module().retrieve_knowledge(
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
        system_prompt = _orchestrator_module()._build_multi_character_system_prompt(
            locale=getattr(self, "locale", DEFAULT_LOCALE),
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            player_character=turn_context.player_character,
            other_characters=other_characters,
            character_relationships=character_relationships,
            past_summaries=self._load_memory_context(
                character_id,
                character_relationships=character_relationships,
                world_now=clock_snapshot.world_now.isoformat(),
                recall_key=stream_id or f"turn:{self.session_id}",
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
        affinity_delta = resolve_relationship_delta(
            result.get("affinity_delta", 0),
            f"{dialogue}\n{player_message}",
            action,
            runtime_state.get("affection_level", 0),
            "affinity",
        )
        new_affinity = _clip(
            runtime_state.get("affection_level", 0) + affinity_delta,
            -100,
            100
        )
        
        trust_delta = resolve_relationship_delta(
            result.get("trust_delta", 0),
            f"{dialogue}\n{player_message}",
            action,
            runtime_state.get("trust_level", 0),
            "trust",
        )
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
            high_participation = (
                self._conversation_pressure_for_group(
                    latest_text,
                    turn_context,
                )
                >= 1.4
                and len(previous_responses) < self._decide_group_response_count(
                    latest_text,
                    max_responses=max(len(previous_responses) + 1, 2),
                    turn_context=turn_context,
                )
            )
            if (
                not mentioned
                and not any(cue in latest_text for cue in continuation_cues)
                and not high_participation
            ):
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

        short_ack = text in {"好", "好的", "嗯", "哦", "行", "可以", "知道了", "明白", "没事"}
        conversation_pressure = 0.0

        if short_ack:
            weights = [(1, 0.9), (2, 0.1)]
        else:
            conversation_pressure = self._conversation_pressure_for_group(
                text,
                turn_context,
            )

            if conversation_pressure >= 2.6:
                weights = [(1, 0.12), (2, 0.42), (3, 0.34), (4, 0.12)]
            elif conversation_pressure >= 1.4:
                weights = [(1, 0.35), (2, 0.45), (3, 0.17), (4, 0.03)]
            elif conversation_pressure >= 0.8:
                weights = [(1, 0.58), (2, 0.33), (3, 0.09)]
            else:
                weights = [(1, 0.78), (2, 0.18), (3, 0.04)]

        available = [(count, weight) for count, weight in weights if count <= cap]
        if not short_ack and conversation_pressure >= 1.4 and cap >= 2:
            available = [(count, weight) for count, weight in available if count >= 2]
            if not available:
                available = [(2, 1.0)]
        total = sum(weight for _, weight in available)
        pick = random.uniform(0, total)
        upto = 0.0
        for count, weight in available:
            upto += weight
            if pick <= upto:
                return count
        return available[-1][0]

    def _conversation_pressure_for_group(
        self,
        text: str,
        turn_context: GroupTurnContext | None = None,
    ) -> float:
        """估算本轮是否需要多人接话。"""
        broad_cues = (
            "大家", "你们", "各位", "都", "一起", "商量", "讨论", "投票", "选择",
            "怎么办", "怎么看", "意见", "想法", "谁", "有没有", "要不要", "为什么",
        )
        high_stakes_cues = (
            "危险", "紧急", "马上", "立刻", "救", "逃", "战斗", "计划", "决定",
            "分工", "调查", "线索", "真相", "冲突", "怀疑", "背叛", "秘密",
        )
        pressure = 0.0
        if any(cue in text for cue in broad_cues):
            pressure += 1.6
        if any(mark in text for mark in ("?", "？", "吗", "呢")):
            pressure += 0.8
        if any(cue in text for cue in high_stakes_cues):
            pressure += 0.9
        if len(text) >= 36:
            pressure += 0.5
        if len(text) >= 80:
            pressure += 0.5
        relation_pressure = self._relationship_pressure_for_group(turn_context)
        if relation_pressure >= 70:
            pressure += 0.8
        elif relation_pressure >= 40:
            pressure += 0.35
        return pressure


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
    
