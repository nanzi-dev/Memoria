"""
对话编排核心逻辑

用途：
1. 调用 LLM 生成 NPC 对话
2. 维护 runtime_state
3. 写入短期 + 长期记忆
4. 防止模型输出破坏沉浸感内容
"""

from email import message
from email.policy import default
import re
import uuid
from venv import logger

from app.core import character_loader, llm_client, prompt_builder
from app.db import repository


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
    
    card =character_loader.load_character_card(character_id)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    
    session_id = str(uuid.uuid4())
    repository.create_session(session_id, character_id, player_id, player_name)
    
    system_prompt = prompt_builder.build_system_prompt(card, runtime_state, player_name)
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
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    
    # =========================
    # 短期记忆
    # =========================
    history = repository.get_short_term_history(
        session_id,
        limit_turns = 8
    )
    
    system_prompt = prompt_builder.build_system_prompt(
        card, runtime_state, player_name
    )
    
    message = history + [
        {"role": "user", "content": player_message}
    ]
    
    result = llm_client.call_role_turn(
        system_prompt = system_prompt,
        history = history,
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
        runtime_state.get("trust_level", 0),
        mood_after,
    )
    
    repository.append_short_term_message(session, "user", player_message)
    repository.append_short_term_message(session, "assistant", dialogue)
    
    # =========================
    # 长期记忆写入
    # =========================
    memory_fact = result.get("memory_worth_keeping")
    
    if memory_fact and str(memory_fact).strip.lower() not in ("none", "null", ""):
        repository.save_long_term_fact(
            character_id,
            player_id,
            str(memory_fact).strip()
        )
        
    # =========================
    # 返回结果
    # =========================
    return{
        "dialogue": dialogue,
        "action": action,
        "affinity_delta": affinity_delta,
        "current_affinity": new_affinity,
        "current_mood": mood_after,
        "triggered_events": [],
    }