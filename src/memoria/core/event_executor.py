"""事件效果规划与原子执行。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from memoria.core.event_schema import (
    EffectExecutionDetail,
    EffectType,
    EventContext,
    EventDefinition,
    EventEffect,
    EventNotification,
    EventTriggerResult,
)
from memoria.db import repository

logger = logging.getLogger(__name__)


class EventExecutor:
    """先规划全部效果，再由 repository 在单一事务中提交。"""

    def plan_event(
        self,
        event: EventDefinition,
        context: EventContext,
        *,
        execution_id: str | None = None,
        execution_key: str | None = None,
    ) -> tuple[EventTriggerResult, dict[str, Any]]:
        started = time.perf_counter()
        result = EventTriggerResult(
            execution_id=execution_id or uuid.uuid4().hex,
            execution_key=execution_key or context.execution_key,
            event_id=event.event_id,
            event_name=event.event_name,
            character_id=context.character_id,
            triggered=True,
            status="succeeded",
        )
        operations: dict[str, Any] = {
            "memories": [],
            "unlock_keys": [],
            "inbox_items": [],
            "proactive_messages": [],
        }

        for index, effect in enumerate(event.effects):
            detail = EffectExecutionDetail(
                index=index,
                effect_type=effect.effect_type.value,
                status="succeeded",
            )
            try:
                detail.message, detail.data = self._plan_single_effect(
                    event,
                    effect,
                    context,
                    result,
                    operations,
                )
                result.effects.append(detail)
                result.effects_applied.append(
                    f"{effect.effect_type.value}: {detail.message or '已应用'}"
                )
            except Exception as exc:
                logger.error(
                    "事件效果规划失败: event=%s effect=%s",
                    event.event_id,
                    effect.effect_type.value,
                    exc_info=True,
                )
                detail.status = "failed"
                detail.error = str(exc)
                result.effects.append(detail)
                for previous in result.effects[:-1]:
                    if previous.status == "succeeded":
                        previous.status = "skipped"
                        previous.message = "事件原子执行失败，已回滚"
                result.status = "failed"
                result.triggered = False
                result.error = str(exc)
                result.effects_applied = []
                result.notification = None
                result.notifications = []
                result.dialogue_override = None
                result.dialogue_overrides = []
                result.state_changes = {}
                result.chained_events = []
                result.proactive_dialogues = []
                operations = {
                    "memories": [],
                    "unlock_keys": [],
                    "inbox_items": [],
                    "proactive_messages": [],
                }
                break

        result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        return result, operations

    def execute_event(
        self,
        event: EventDefinition,
        context: EventContext,
    ) -> EventTriggerResult:
        """兼容入口：单事件仍使用原子批次提交。"""
        execution_key = context.execution_key or (
            f"direct:{context.session_id}:{event.event_id}:{uuid.uuid4().hex}"
        )
        result, operations = self.plan_event(
            event,
            context,
            execution_key=execution_key,
        )
        execution = self.build_execution_record(event, context, result, operations)
        commit = repository.commit_event_execution_batch(
            player_id=context.player_id,
            execution_key=execution_key,
            trigger_source=context.trigger_source,
            results_data=json.dumps([result.model_dump(mode="json")], ensure_ascii=False),
            executions=[execution],
        )
        if commit["deduplicated"]:
            stored = json.loads(commit["batch"]["results_data"])
            restored = EventTriggerResult.model_validate(stored[0])
            restored.status = "skipped"
            restored.deduplicated = True
            return restored
        self._sync_vector_memories(commit.get("inserted_memories") or [])
        return result

    def build_execution_record(
        self,
        event: EventDefinition,
        context: EventContext,
        result: EventTriggerResult,
        operations: dict[str, Any],
        *,
        context_state: dict[str, Any] | None = None,
        trigger_claim_token: str | None = None,
        trigger_character_scope: str | None = None,
    ) -> dict[str, Any]:
        return {
            "execution_id": result.execution_id,
            "event_id": event.event_id,
            "character_id": context.character_id,
            "session_id": context.session_id,
            "status": result.status,
            "effects_data": json.dumps(
                [effect.model_dump(mode="json") for effect in result.effects],
                ensure_ascii=False,
            ),
            "result_data": result.model_dump_json(),
            "error": result.error,
            "duration_ms": result.duration_ms,
            "context_snapshot": context.model_dump_json(),
            "effects_applied": json.dumps(result.effects_applied, ensure_ascii=False),
            "context_state": context_state,
            "trigger_claim_token": trigger_claim_token,
            "trigger_character_scope": trigger_character_scope,
            **operations,
        }

    def _plan_single_effect(
        self,
        event: EventDefinition,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult,
        operations: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        effect_type = effect.effect_type

        if effect_type == EffectType.MODIFY_STATE:
            if not effect.state_changes:
                raise ValueError("修改状态效果缺少 state_changes")
            allowed = {"affection_level", "trust_level", "current_mood"}
            unknown = set(effect.state_changes) - allowed
            if unknown:
                raise ValueError(f"不支持的状态字段: {', '.join(sorted(unknown))}")
            result.state_changes.update(effect.state_changes)
            return "状态已规划", dict(effect.state_changes)

        if effect_type == EffectType.UNLOCK_CONTENT:
            keys = [str(key).strip() for key in effect.unlock_keys or [] if str(key).strip()]
            if not keys:
                raise ValueError("解锁内容效果缺少 unlock_keys")
            operations["unlock_keys"].extend(keys)
            unlocked = result.state_changes.setdefault("unlocked_content", [])
            unlocked.extend(key for key in keys if key not in unlocked)
            return "内容已规划解锁", {"unlock_keys": keys}

        if effect_type == EffectType.TRIGGER_DIALOGUE:
            text = str(effect.dialogue_text or "").strip()
            if not text:
                raise ValueError("触发对话效果缺少 dialogue_text")
            result.dialogue_overrides.append(text)
            if result.dialogue_override is None:
                result.dialogue_override = text
            return "对白已加入合并队列", {"dialogue": text}

        if effect_type == EffectType.ADD_MEMORY:
            text = str(effect.memory_text or "").strip()
            if not text:
                raise ValueError("添加记忆效果缺少 memory_text")
            operations["memories"].append({
                "character_id": context.character_id,
                "player_id": context.player_id,
                "fact_text": text,
                "importance": effect.memory_importance or 5,
            })
            return "记忆已加入原子提交", {"memory_text": text}

        if effect_type == EffectType.CHANGE_MOOD:
            mood = str(effect.target_mood or "").strip()
            if not mood:
                raise ValueError("改变情绪效果缺少 target_mood")
            result.state_changes["current_mood"] = mood
            return "情绪已规划", {"current_mood": mood}

        if effect_type == EffectType.NOTIFY_PLAYER:
            message = str(effect.notification_message or "").strip()
            if not message:
                raise ValueError("通知效果缺少 notification_message")
            notification = EventNotification(
                event_id=event.event_id,
                message=message,
                notification_type=effect.notification_type or "info",
                title=event.event_name,
            )
            result.notifications.append(notification)
            result.notification = message
            operations["inbox_items"].append({
                "title": event.event_name,
                "content": message,
                "session_id": (
                    None if context.session_id.startswith("schedule:") else context.session_id
                ),
                "payload": notification.model_dump_json(),
                "world_created_at": context.world_time,
            })
            return "通知已加入原子提交", notification.model_dump(mode="json")

        if effect_type == EffectType.MODIFY_RELATIONSHIP:
            raise ValueError("modify_relationship 尚未开放，请先完善关系事务语义")

        if effect_type in {EffectType.GRANT_ITEM, EffectType.START_QUEST}:
            raise ValueError(f"{effect_type.value} 尚未实现，不能执行")

        if effect_type == EffectType.TRIGGER_EVENT:
            event_id = str(effect.next_event_id or "").strip()
            if not event_id:
                raise ValueError("事件链效果缺少 next_event_id")
            result.chained_events.append(event_id)
            return "后续事件已加入执行链", {"next_event_id": event_id}

        if effect_type == EffectType.BRANCH_EVENT:
            event_id = self._select_branch_event(effect, context)
            if not event_id:
                return "没有分支条件命中", {}
            result.chained_events.append(event_id)
            return "分支事件已加入执行链", {"next_event_id": event_id}

        if effect_type == EffectType.NPC_PROACTIVE_DIALOGUE:
            proactive = self._plan_npc_proactive_dialogue(effect, context)
            result.proactive_dialogues.append(proactive)
            operations["proactive_messages"].append({
                "session_id": proactive["session_id"],
                "content": proactive["dialogue"],
                "character_id": proactive["character_id"],
                "character_name": proactive.get("character_name"),
                "knowledge_sources": proactive.get("knowledge_sources") or [],
                "world_created_at": context.world_time,
            })
            return "NPC 主动对白已生成，等待原子提交", proactive

        if effect_type == EffectType.UPDATE_EVENT_PROGRESS:
            progress_update: dict[str, Any] = {}
            if effect.progress is not None:
                progress_update["progress"] = max(0.0, min(1.0, float(effect.progress)))
            if effect.progress_delta is not None:
                progress_update["progress_delta"] = float(effect.progress_delta)
            if effect.event_status is not None:
                if effect.event_status not in {"pending", "active", "completed", "failed"}:
                    raise ValueError("无效的事件进度状态")
                progress_update["status"] = effect.event_status
            if not progress_update:
                raise ValueError("更新事件进度效果缺少 progress/progress_delta/event_status")
            result.state_changes["event_progress"] = progress_update
            return "事件进度已规划", progress_update

        raise ValueError(f"不支持的效果类型: {effect_type.value}")

    def _select_branch_event(self, effect: EventEffect, context: EventContext) -> str | None:
        if not effect.branch_conditions:
            raise ValueError("分支事件缺少 branch_conditions")
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import TriggerCondition

        detector = EventDetector()
        for branch in effect.branch_conditions:
            event_id = branch.get("event_id")
            condition_data = branch.get("condition")
            if not event_id or not condition_data:
                continue
            condition = TriggerCondition.model_validate(condition_data)
            if detector._check_trigger_condition(condition, context):
                return str(event_id)
        return str(effect.next_event_id).strip() if effect.next_event_id else None

    def _branch_next_event(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult,
    ) -> None:
        """兼容旧测试与内部调用的分支选择入口。"""
        event_id = self._select_branch_event(effect, context)
        if event_id:
            result.chained_events.append(event_id)

    def _plan_npc_proactive_dialogue(
        self,
        effect: EventEffect,
        context: EventContext,
    ) -> dict[str, Any]:
        target_session_id = (
            effect.target_session_id
            or context.active_multi_session_id
            or context.session_id
        )
        session = repository.get_session(target_session_id) if target_session_id else None
        if not session or not session.get("is_multi_character") or session.get("status") == "ended":
            raise ValueError("NPC 主动对白目标不是可用群聊")

        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

        orchestrator = MultiCharacterOrchestrator(target_session_id)
        dialogue = orchestrator.trigger_character_interaction(
            trigger_character_id=effect.proactive_character_id,
            prompt=effect.proactive_prompt,
            persist=False,
        )
        return {"session_id": target_session_id, **dialogue}

    @staticmethod
    def _sync_vector_memories(memories: list[dict[str, Any]]) -> None:
        if not memories:
            return
        try:
            from memoria.core.vector_memory import get_vector_store

            vector_store = get_vector_store()
            for memory in memories:
                vector_store.add_memory(**memory)
        except Exception as exc:  # 数据库提交成功后，向量索引允许异步恢复。
            logger.warning("事件记忆向量同步失败: %s", exc)


_executor_instance: EventExecutor | None = None


def get_event_executor() -> EventExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = EventExecutor()
    return _executor_instance
