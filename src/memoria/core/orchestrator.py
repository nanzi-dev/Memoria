"""
对话编排核心逻辑

用途：
1. 调用 LLM 生成 NPC 对话
2. 维护 runtime_state
3. 写入短期 + 长期记忆
4. 防止模型输出破坏沉浸感内容
5. 🆕 检测和执行事件
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from memoria.core import character_loader, llm_client, prompt_builder
from memoria.core.event_schema import EventContext, EventDefinition
from memoria.core.event_detector import get_event_detector
from memoria.core.event_executor import get_event_executor
from memoria.db import repository

logger = logging.getLogger(__name__)


# =========================
# 安全过滤
# =========================
RISK_PATTERNS = [
    r"我是.{0,3}(AI|ai|人工智能|语言模型|机器人)",
    r"作为.{0,3}(AI|ai|人工智能|语言模型)",
    r"我(不能|无法)扮演",
    r"我没有(真正的|真实的)情感",
    r"系统提示词",
    r"作为一个语言模型",
]

_RISK_RE = re.compile("|".join(RISK_PATTERNS)) if RISK_PATTERNS else None

FALLBACK_LINE = "[皱眉]这话问得奇怪，不讲不讲。"

def _safety_check(dialogue: str, fallback: str = FALLBACK_LINE) -> str:
    """
    输出安全检查：
    - 命中 AI/系统泄露 → 替换兜底话术
    """
    if not dialogue:
        return fallback
    
    if _RISK_RE and _RISK_RE.search(dialogue):
        logger.warning("检测到高风险输出，已替换: %s", dialogue[:200])
        return fallback
    
    return dialogue
    

# =========================
# 数值裁剪
# =========================
def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

def _safe_float(value, default: float = 0.0) -> float:
    """安全 float 转换（防 None / 字符串异常）"""
    try:
        return float(value)
    except Exception:
        return default
    

# =========================
# Session 创建
# =========================
def start_session(character_id: str, player_id: str, player_name: str) -> dict:
    """对应 /dialogue/session/start"""
    
    card = character_loader.load_character_card(character_id)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    
    session_id = str(uuid.uuid4())
    repository.create_session(session_id, character_id, player_id, player_name)
    
    # 获取历史会话摘要（最近3次）
    past_summaries_raw = repository.get_recent_summaries(character_id, player_id, limit=3)
    past_summaries = [s["summary_text"] for s in past_summaries_raw] if past_summaries_raw else []
    
    system_prompt = prompt_builder.build_system_prompt(
        card, runtime_state, player_name, past_summaries=past_summaries
    )
    opening_instruction = prompt_builder.build_opening_line_prompt(card, runtime_state, player_name)
    
    result = llm_client.call_role_turn(
        system_prompt = system_prompt + opening_instruction,
        history =  [],
    )
    
    dialogue = _safety_check(result.get("dialogue", ""))
    
    repository.append_short_term_message(session_id, "assistant", dialogue)
    
    return{
        "session_id": session_id,
        "opening_line": dialogue,
        "action": result.get("action", card.action_vocabulary.default_action),
        "current_affinity": runtime_state.get("affection_level", 0),
    }
    

# =========================
# 主对话流程
# =========================
def run_dialogue_turn(session_id: str, player_message: str) -> dict:
    """对应 /dialogue/turn"""
    
    session = repository.get_session(session_id)
    if not session:
        raise ValueError(f"会话不存在: {session_id}")
    
    character_id = session["character_id"]
    player_id = session["player_id"]
    player_name = session["player_name"]
    
    card = character_loader.load_character_card(character_id)
    
    # 使用玩家消息作为查询上下文，进行向量检索
    runtime_state = repository.get_runtime_state(
        character_id, 
        player_id, 
        card,
        query_context=player_message
    )
    
    # =========================
    # 短期记忆
    # =========================
    history = repository.get_short_term_history(
        session_id,
        limit_turns = 8
    )
    
    # 获取历史会话摘要（最近3次，用于上下文增强）
    past_summaries_raw = repository.get_recent_summaries(character_id, player_id, limit=3)
    past_summaries = [s["summary_text"] for s in past_summaries_raw] if past_summaries_raw else []
    
    system_prompt = prompt_builder.build_system_prompt(
        card, runtime_state, player_name, past_summaries=past_summaries
    )
    
    messages = history + [
        {"role": "user", "content": player_message}
    ]
    
    result = llm_client.call_role_turn(
        system_prompt = system_prompt,
        history = messages,
    )
    
    # =========================
    # fallback 监控
    # =========================
    if result.get("_fallback_mode"):
        logger.warning(
            "LLM JSON降级触发 (character_id=%s, session_id=%s)",
            character_id,
            session_id,
        )
        
    # =========================
    # dialogue 安全过滤
    # =========================
    dialogue = _safety_check(result.get("dialogue", ""))
    
    # =========================
    # action 校验（兼容新结构）
    # =========================
    action = result.get("action") or card.action_vocabulary.default_action
    
    valid_actions = (
        getattr(card.action_vocabulary, "greeting_actions", [])
        + getattr(card.action_vocabulary, "farewell_actions", [])
        + getattr(card.action_vocabulary, "agreement_actions", [])
        + getattr(card.action_vocabulary, "disagreement_actions", [])
        + getattr(card.action_vocabulary, "emotional_reactions", [])
    )
    
    if valid_actions and action not in valid_actions:
        action = card.action_vocabulary.default_action
        
    # =========================
    # affection_level 计算（裁剪）
    # =========================
    affinity_delta = _clip(_safe_float(result.get("affinity_delta", 0)), -10, 10)
    new_affinity = _clip(
        runtime_state.get("affection_level", 0) + affinity_delta,
        -100,
        100
    )
    
    # =========================
    # trust 处理
    # =========================
    trust_delta = _clip(_safe_float(result.get("trust_delta", 0)), -10, 10)
    new_trust = _clip(
        runtime_state.get("trust_level", 0) + trust_delta,
        0,
        100
    )
    
    # =========================
    # mood 处理（兼容 schema）
    # =========================
    mood_after = result.get("mood_after") or runtime_state.get("current_mood", "neutral")
    
    mood_values = getattr(card.runtime_state_schema.current_mood, "emotions", [])
    if mood_values and mood_after not in mood_values:
        mood_after = runtime_state.get("current_mood", "neutral")
        
    # =========================
    # 状态持久化
    # =========================
    repository.save_runtime_state(
        character_id,
        player_id,
        new_affinity,
        new_trust,
        mood_after,
    )
    
    repository.append_short_term_message(session_id, "user", player_message)
    repository.append_short_term_message(session_id, "assistant", dialogue)
    
    # =========================
    # 长期记忆写入
    # =========================
    memory_fact = result.get("memory_worth_keeping")
    
    if memory_fact and str(memory_fact).strip().lower() not in ("none", "null", ""):
        repository.save_long_term_fact(
            character_id,
            player_id,
            str(memory_fact).strip()
        )
    
    # =========================
    # 事件系统检测和执行
    # =========================
    triggered_events_info = []
    event_notification = None
    
    try:
        # 构建事件上下文
        session_created = datetime.fromisoformat(session["created_at"]) if session.get("created_at") else datetime.now(timezone.utc)
        session_duration = (datetime.now(timezone.utc) - session_created).total_seconds() / 60.0
        
        event_context = EventContext(
            character_id=character_id,
            player_id=player_id,
            session_id=session_id,
            current_affinity=new_affinity,
            current_trust=runtime_state.get("trust_level", 0),
            current_mood=mood_after,
            player_message=player_message,
            npc_response=dialogue,
            dialogue_count=len(history) // 2 + 1,
            total_dialogue_count=len(history) // 2 + 1,  # 简化实现，后续可扩展
            session_duration_minutes=session_duration,
            unlocked_content=[],
            character_relationships={}
        )
        
        # 加载事件定义
        event_defs_raw = repository.list_event_definitions(
            character_id=character_id,
            only_active=True
        )
        
        # 转换为 EventDefinition 对象
        event_definitions = []
        for event_raw in event_defs_raw:
            try:
                event_def = EventDefinition(
                    event_id=event_raw["event_id"],
                    event_name=event_raw["event_name"],
                    description=event_raw.get("description"),
                    character_id=event_raw.get("character_id"),
                    trigger_condition=json.loads(event_raw["trigger_config"]),
                    effects=json.loads(event_raw["effects_config"]),
                    priority=event_raw.get("priority", 0),
                    is_active=bool(event_raw.get("is_active", 1)),
                    created_at=event_raw.get("created_at"),
                    updated_at=event_raw.get("updated_at"),
                    trigger_count=event_raw.get("trigger_count", 0),
                    last_triggered_at=event_raw.get("last_triggered_at")
                )
                event_definitions.append(event_def)
            except Exception as e:
                logger.error(f"解析事件定义失败: {event_raw.get('event_id')}, 错误: {e}")
        
        # 检测事件
        detector = get_event_detector()
        triggered_events = detector.check_events(event_context, event_definitions)
        
        # 执行事件
        executor = get_event_executor()
        for event in triggered_events:
            try:
                event_result = executor.execute_event(event, event_context)
                
                # 应用事件效果到状态
                if event_result.state_changes:
                    # 应用好感度变化
                    if "affection_level" in event_result.state_changes:
                        new_affinity += event_result.state_changes["affection_level"]
                        new_affinity = _clip(new_affinity, -100, 100)
                    
                    # 应用信任度变化
                    if "trust_level" in event_result.state_changes:
                        trust_delta = event_result.state_changes["trust_level"]
                        new_trust = _clip(
                            runtime_state.get("trust_level", 0) + trust_delta,
                            0,
                            100
                        )
                        repository.save_runtime_state(
                            character_id,
                            player_id,
                            new_affinity,
                            new_trust,
                            mood_after
                        )
                    
                    # 应用情绪变化
                    if "current_mood" in event_result.state_changes:
                        mood_after = event_result.state_changes["current_mood"]
                
                # 对话覆盖（优先级最高的事件生效）
                if event_result.dialogue_override and not dialogue.startswith("[事件触发]"):
                    dialogue = f"[事件触发] {event_result.dialogue_override}"
                
                # 玩家通知
                if event_result.notification:
                    event_notification = event_result.notification
                
                # 记录触发信息
                triggered_events_info.append({
                    "event_id": event.event_id,
                    "event_name": event.event_name,
                    "effects": event_result.effects_applied
                })
                
                logger.info(f"事件已执行: {event.event_id} - {event.event_name}")
                
            except Exception as e:
                logger.error(f"执行事件失败: {event.event_id}, 错误: {e}")
        
        # 更新最终状态
        if triggered_events:
            repository.save_runtime_state(
                character_id,
                player_id,
                new_affinity,
                new_trust,
                mood_after
            )
    
    except Exception as e:
        logger.error(f"事件系统处理失败: {e}", exc_info=True)
        
    # =========================
    # 返回结果
    # =========================
    return {
        "dialogue": dialogue,
        "action": action,
        "affinity_delta": affinity_delta,
        "current_affinity": new_affinity,
        "current_mood": mood_after,
        "triggered_events": triggered_events_info,
        "event_notification": event_notification,
    }