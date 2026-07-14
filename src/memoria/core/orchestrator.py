"""
对话编排核心逻辑

用途：
1. 调用 LLM 生成 NPC 对话
2. 维护 runtime_state
3. 写入短期 + 长期记忆
4. 防止模型输出破坏沉浸感内容
5. 检测和执行事件
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable

from memoria.core import (
    character_loader,
    llm_client,
    multi_character_memory,
    prompt_builder,
    world_clock,
)
from memoria.core.config import configs
from memoria.core import event_runtime, relationship_context
from memoria.core.knowledge_retriever import retrieve_knowledge
from memoria.core.memory_extractor import extract_player_memory
from memoria.db import repository

logger = logging.getLogger(__name__)
DebugSink = Callable[[str], None]


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


def _append_short_term_message(
    session_id: str,
    role: str,
    content: str,
    **state_snapshot,
) -> int:
    """写入短期消息；兼容只接受三参的测试替身。"""
    if not state_snapshot:
        return repository.append_short_term_message(session_id, role, content)

    try:
        return repository.append_short_term_message(
            session_id,
            role,
            content,
            **state_snapshot,
        )
    except TypeError as e:
        if "unexpected keyword argument" not in str(e):
            raise
        return repository.append_short_term_message(session_id, role, content)


def _build_system_prompt(
    card,
    runtime_state: dict,
    player_name: str,
    *,
    past_summaries: list[str],
    relationship_graph_lines: list[str],
    time_context: dict,
    knowledge_context: str = "",
) -> str:
    """Call the prompt builder while tolerating legacy test doubles."""
    try:
        return prompt_builder.build_system_prompt(
            card,
            runtime_state,
            player_name,
            past_summaries=past_summaries,
            relationship_graph_lines=relationship_graph_lines,
            time_context=time_context,
            knowledge_context=knowledge_context,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        try:
            return prompt_builder.build_system_prompt(
                card,
                runtime_state,
                player_name,
                past_summaries=past_summaries,
                relationship_graph_lines=relationship_graph_lines,
                time_context=time_context,
            )
        except TypeError as legacy_exc:
            if "unexpected keyword argument" not in str(legacy_exc):
                raise
            return prompt_builder.build_system_prompt(
                card,
                runtime_state,
                player_name,
                past_summaries=past_summaries,
                relationship_graph_lines=relationship_graph_lines,
            )
    

def _aliases_for_card(character_id: str, card) -> list[str]:
    aliases = [character_id]
    meta = getattr(card, "meta", None)
    if meta:
        aliases.extend([
            getattr(meta, "name", ""),
            getattr(meta, "display_name", ""),
        ])
        aliases.extend(getattr(meta, "aliases", []) or [])
    return relationship_context.normalize_aliases(aliases)


def _character_name_and_aliases(player_id: str, character_id: str) -> tuple[str, list[str]]:
    aliases = [character_id]
    name = character_id
    row = None
    try:
        row = repository.get_character_card_from_db(
            player_id,
            character_id,
            include_inactive=True,
        )
    except Exception as e:
        logger.debug("读取关联角色卡失败: %s", e)

    if row:
        name = row.get("display_name") or row.get("name") or character_id
        aliases.extend([row.get("name"), row.get("display_name")])
        try:
            card_data = json.loads(row.get("card_data") or "{}")
            meta = card_data.get("meta") or {}
            aliases.extend([
                meta.get("name"),
                meta.get("display_name"),
                *(meta.get("aliases") or []),
            ])
        except (TypeError, ValueError):
            pass

    return name, relationship_context.normalize_aliases(aliases)


def _other_character_id(character_id: str, memory: dict) -> str | None:
    char_a = memory.get("character_a_id")
    char_b = memory.get("character_b_id")
    if char_a == character_id:
        return char_b
    if char_b == character_id:
        return char_a
    return None


def _parse_group_memory_participants(raw_participants) -> list[str]:
    if not raw_participants:
        return []
    if isinstance(raw_participants, list):
        return [str(pid) for pid in raw_participants if pid]
    try:
        parsed = json.loads(raw_participants)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(pid) for pid in parsed if pid]


def _relationship_updated_at_for_pair(
    player_id: str,
    character_id_a: str,
    character_id_b: str,
    character_relationships: dict | None,
) -> str | None:
    relationship = relationship_context.relationship_between(
        character_relationships,
        character_id_a,
        character_id_b,
    )
    updated_at = relationship.get("updated_at") if relationship else None
    revision_updated_at = repository.get_character_relationship_updated_at(
        player_id,
        character_id_a,
        character_id_b,
    )
    return relationship_context.latest_timestamp(updated_at, revision_updated_at)


def _single_text_conflicts_with_relationship_graph(
    text: str,
    character_id: str,
    related_character_ids: list[str],
    character_relationships: dict | None,
    aliases_by_character: dict[str, list[str]],
) -> bool:
    if character_relationships is None or not text:
        return False

    for other_id in related_character_ids:
        relationship = relationship_context.relationship_between(
            character_relationships,
            character_id,
            other_id,
        )
        pair_aliases = relationship_context.normalize_aliases(
            [
                *aliases_by_character.get(character_id, [character_id]),
                *aliases_by_character.get(other_id, [other_id]),
            ]
        )
        if relationship_context.relationship_text_conflicts_with_graph(
            text,
            relationship,
            pair_aliases,
        ):
            return True
    return False


def _get_character_group_memories_for_player(
    character_id: str,
    player_id: str,
    limit: int = 20,
) -> list[dict]:
    try:
        return repository.get_character_group_memories(
            character_id=character_id,
            owner_user_id=player_id,
            limit=limit,
        )
    except TypeError:
        return repository.get_character_group_memories(character_id, limit=limit)


def _format_cross_mode_memories(
    character_id: str,
    player_id: str,
    shared_records: list[dict],
    group_records: list[dict],
    related_character_ids: list[str],
    character_names: dict[str, str],
    aliases_by_character: dict[str, list[str]],
    relationship_aliases: list[str],
    relationship_cutoff: str | None,
    character_relationships: dict,
) -> list[str]:
    memory_lines = []
    seen = set()

    for memory in shared_records:
        other_id = _other_character_id(character_id, memory)
        if not other_id:
            continue
        relationship = relationship_context.relationship_between(
            character_relationships,
            character_id,
            other_id,
        )
        pair_aliases = relationship_context.normalize_aliases(
            [
                *aliases_by_character.get(character_id, [character_id]),
                *aliases_by_character.get(other_id, [other_id]),
            ]
        )
        relationship_updated_at = _relationship_updated_at_for_pair(
            player_id,
            character_id,
            other_id,
            character_relationships,
        )
        filtered = relationship_context.filter_stale_relationship_memory_records(
            [memory],
            relationship_updated_at,
            participant_aliases=pair_aliases,
            text_key="memory_text",
            relationship_context=True,
            relationship=relationship,
        )
        if not filtered:
            continue
        text = str(memory.get("memory_text") or "").strip()
        if not text or _single_text_conflicts_with_relationship_graph(
            text,
            character_id,
            related_character_ids,
            character_relationships,
            aliases_by_character,
        ):
            continue
        line = f"共享记忆（与{character_names.get(other_id) or other_id}）：{text}"
        if line not in seen:
            memory_lines.append(line)
            seen.add(line)
        if len(memory_lines) >= 6:
            break

    group_records = relationship_context.filter_stale_relationship_memory_records(
        group_records,
        relationship_cutoff,
        participant_aliases=relationship_aliases,
        text_key="memory_text",
        relationship_context=True,
    )
    group_count = 0
    for memory in group_records:
        text = str(memory.get("memory_text") or "").strip()
        if not text or _single_text_conflicts_with_relationship_graph(
            text,
            character_id,
            related_character_ids,
            character_relationships,
            aliases_by_character,
        ):
            continue
        line = f"群体记忆：{text}"
        if line not in seen:
            memory_lines.append(line)
            seen.add(line)
            group_count += 1
        if group_count >= 5:
            break

    return memory_lines


def _build_single_character_memory_query_context(
    query_context: str | None,
    character_names: dict[str, str],
    relationship_graph_lines: list[str],
) -> str | None:
    parts = []
    if query_context:
        parts.append(str(query_context).strip())

    names = relationship_context.normalize_aliases([
        name
        for name in character_names.values()
        if name
    ])
    if names:
        parts.append("相关角色：" + "、".join(names))

    if relationship_graph_lines:
        parts.append("当前关系图谱：\n" + "\n".join(relationship_graph_lines))

    return "\n".join(part for part in parts if part) or None


def _load_single_character_prompt_context(
    character_id: str,
    player_id: str,
    card,
    query_context: str | None = None,
    fallback_known_player_facts=None,
) -> dict:
    relationship_records = repository.list_character_relationships(player_id, character_id)
    character_relationships = relationship_context.relationship_map_from_records(
        relationship_records
    )

    shared_records = repository.get_character_shared_memories(
        owner_user_id=player_id,
        character_id=character_id,
        limit=20,
    )
    group_records = _get_character_group_memories_for_player(
        character_id,
        player_id,
        limit=20,
    )

    related_character_ids = []
    seen_related = set()

    def add_related(other_id: str | None) -> None:
        if not other_id or other_id == character_id or other_id in seen_related:
            return
        seen_related.add(other_id)
        related_character_ids.append(other_id)

    for relationship in relationship_records:
        char_a = relationship.get("character_id_a")
        char_b = relationship.get("character_id_b")
        add_related(char_b if char_a == character_id else char_a)

    for memory in shared_records:
        add_related(_other_character_id(character_id, memory))

    for memory in group_records:
        for participant_id in _parse_group_memory_participants(memory.get("participants")):
            add_related(participant_id)

    current_name = getattr(getattr(card, "meta", None), "display_name", None)
    current_name = current_name or getattr(getattr(card, "meta", None), "name", None) or character_id
    character_names = {character_id: current_name}
    aliases_by_character = {character_id: _aliases_for_card(character_id, card)}

    for other_id in related_character_ids:
        name, aliases = _character_name_and_aliases(player_id, other_id)
        character_names[other_id] = name
        aliases_by_character[other_id] = aliases

    relationship_aliases = relationship_context.normalize_aliases(
        [
            alias
            for aliases in aliases_by_character.values()
            for alias in aliases
        ]
    )
    relationship_cutoff = None
    if related_character_ids:
        relationship_cutoff = multi_character_memory.get_relationship_history_cutoff(
            player_id,
            [character_id, *related_character_ids],
            character_relationships,
        )

    relationship_graph_lines = relationship_context.build_relationship_graph_lines_for_pairs(
        [(character_id, other_id) for other_id in related_character_ids],
        character_names,
        character_relationships,
    )
    memory_query_context = _build_single_character_memory_query_context(
        query_context,
        character_names,
        relationship_graph_lines,
    )

    try:
        fact_records = repository.get_long_term_fact_records(
            character_id=character_id,
            player_id=player_id,
            limit=20,
            query_context=memory_query_context,
        )
    except Exception as e:
        logger.warning("加载长期记忆记录失败，使用 runtime_state 默认记忆: %s", e)
        if isinstance(fallback_known_player_facts, dict):
            fallback_facts = [
                f"{key}:{value}" for key, value in fallback_known_player_facts.items()
            ]
        elif isinstance(fallback_known_player_facts, list):
            fallback_facts = fallback_known_player_facts
        elif fallback_known_player_facts:
            fallback_facts = [str(fallback_known_player_facts)]
        else:
            fallback_facts = []
        fact_records = [
            {"fact_text": str(fact), "created_at": None}
            for fact in fallback_facts
            if str(fact).strip()
        ]

    fact_records = relationship_context.filter_stale_relationship_memory_records(
        fact_records,
        relationship_cutoff,
        participant_aliases=relationship_aliases,
        text_key="fact_text",
        relationship_context=False,
    )
    known_player_facts = [
        record["fact_text"]
        for record in fact_records
        if not _single_text_conflicts_with_relationship_graph(
            str(record.get("fact_text") or ""),
            character_id,
            related_character_ids,
            character_relationships,
            aliases_by_character,
        )
    ]

    return {
        "relationship_graph_lines": relationship_graph_lines,
        "character_relationships": character_relationships,
        "known_player_facts": known_player_facts,
        "cross_mode_memories": _format_cross_mode_memories(
            character_id=character_id,
            player_id=player_id,
            shared_records=shared_records,
            group_records=group_records,
            related_character_ids=related_character_ids,
            character_names=character_names,
            aliases_by_character=aliases_by_character,
            relationship_aliases=relationship_aliases,
            relationship_cutoff=relationship_cutoff,
            character_relationships=character_relationships,
        ),
    }


# =========================
# Session 创建
# =========================
def start_session(
    character_id: str,
    player_id: str,
    player_name: str,
    debug: bool = False,
    debug_sink: DebugSink | None = None,
) -> dict:
    """对应 /dialogue/session/start"""
    
    card = character_loader.load_character_card(character_id, player_id)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    clock_snapshot = world_clock.get_clock_snapshot(player_id)
    time_context = clock_snapshot.prompt_context(
        repository.get_last_character_interaction_world_at(player_id, character_id),
        locale=getattr(getattr(card, "speech_style", None), "language", "zh-CN"),
    )
    
    session_id = str(uuid.uuid4())
    repository.create_session(session_id, character_id, player_id, player_name)
    
    # 获取历史会话摘要（最近3次）
    past_summaries_raw = repository.get_recent_summaries(character_id, player_id, limit=3)
    past_summaries = [s["summary_text"] for s in past_summaries_raw] if past_summaries_raw else []
    prompt_context = _load_single_character_prompt_context(
        character_id,
        player_id,
        card,
        fallback_known_player_facts=runtime_state.get("known_player_facts"),
    )
    runtime_state["known_player_facts"] = prompt_context["known_player_facts"]
    past_summaries.extend(prompt_context["cross_mode_memories"])
    
    system_prompt = _build_system_prompt(
        card,
        runtime_state,
        player_name,
        past_summaries=past_summaries,
        relationship_graph_lines=prompt_context["relationship_graph_lines"],
        time_context=time_context,
    )
    opening_instruction = prompt_builder.build_opening_line_prompt(card, runtime_state, player_name)
    
    result = llm_client.call_role_turn(
        system_prompt = system_prompt + opening_instruction,
        history =  [],
        debug = debug,
        debug_sink = debug_sink,
    )
    
    dialogue = _safety_check(result.get("dialogue", ""))
    
    assistant_msg_id = _append_short_term_message(
        session_id,
        "assistant",
        dialogue,
        action=result.get("action", card.action_vocabulary.default_action),
        affinity_delta=0,
        trust_delta=0,
        current_affinity=runtime_state.get("affection_level", 0),
        current_trust=runtime_state.get("trust_level", 0),
        current_mood=runtime_state.get("current_mood", "neutral"),
        world_created_at=clock_snapshot.world_now.isoformat(),
    )
    
    return{
        "session_id": session_id,
        "opening_line": dialogue,
        "action": result.get("action", card.action_vocabulary.default_action),
        "current_affinity": runtime_state.get("affection_level", 0),
        "current_trust": runtime_state.get("trust_level", 0),
        "world_created_at": clock_snapshot.world_now.isoformat(),
        "assistant_message_id": assistant_msg_id,
    }
    

# =========================
# 主对话流程
# =========================
def run_dialogue_turn(
    session_id: str,
    player_message: str,
    request_id: str | None = None,
    debug: bool = False,
    debug_sink: DebugSink | None = None,
) -> dict:
    """对应 /dialogue/turn"""
    
    session = repository.get_session(session_id)
    if not session:
        raise ValueError(f"会话不存在: {session_id}")
    if session.get("status") == "ended":
        raise ValueError("会话已经结束")
    
    character_id = session["character_id"]
    player_id = session["player_id"]
    player_name = session["player_name"]
    card = character_loader.load_character_card(character_id, player_id)
    clock_snapshot = world_clock.get_clock_snapshot(player_id)
    time_context = clock_snapshot.prompt_context(
        repository.get_last_character_interaction_world_at(player_id, character_id),
        locale=getattr(getattr(card, "speech_style", None), "language", "zh-CN"),
    )
    
    # 使用玩家消息作为查询上下文，进行向量检索
    runtime_state = repository.get_runtime_state(
        character_id, 
        player_id, 
        card,
        query_context=player_message
    )
    previous_affinity = _safe_float(runtime_state.get("affection_level", 0))
    previous_trust = _safe_float(runtime_state.get("trust_level", 0))
    
    # =========================
    # 短期记忆
    # =========================
    history = repository.get_short_term_history(
        session_id,
        limit_turns = 8
    )
    knowledge = retrieve_knowledge(
        owner_user_id=player_id,
        character_id=character_id,
        current_message=player_message,
        recent_history=history,
    )
    
    # 获取历史会话摘要（最近3次，用于上下文增强）
    past_summaries_raw = repository.get_recent_summaries(character_id, player_id, limit=3)
    past_summaries = [s["summary_text"] for s in past_summaries_raw] if past_summaries_raw else []
    prompt_context = _load_single_character_prompt_context(
        character_id,
        player_id,
        card,
        query_context=player_message,
        fallback_known_player_facts=runtime_state.get("known_player_facts"),
    )
    runtime_state["known_player_facts"] = prompt_context["known_player_facts"]
    past_summaries.extend(prompt_context["cross_mode_memories"])
    
    system_prompt = _build_system_prompt(
        card,
        runtime_state,
        player_name,
        past_summaries=past_summaries,
        relationship_graph_lines=prompt_context["relationship_graph_lines"],
        time_context=time_context,
        knowledge_context=knowledge.prompt_section,
    )
    
    messages = history + [
        {"role": "user", "content": player_message}
    ]
    
    result = llm_client.call_role_turn(
        system_prompt = system_prompt,
        history = messages,
        debug = debug,
        debug_sink = debug_sink,
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
    # 暂缓持久化——先执行事件，成功后统一写入，避免事件失败时数据不一致
    # =========================
    # =========================
    # 事件系统检测和执行
    # =========================
    triggered_events_info = []
    event_notification = None
    event_notifications = []
    event_results = []
    user_msg_id = None
    assistant_msg_id = None
    
    try:
        event_context = event_runtime.build_event_context(
            character_id=character_id,
            player_id=player_id,
            session_id=session_id,
            current_affinity=new_affinity,
            current_trust=new_trust,
            current_mood=mood_after,
            previous_affinity=previous_affinity,
            previous_trust=previous_trust,
            affinity_delta=affinity_delta,
            trust_delta=trust_delta,
            player_message=player_message,
            npc_response=dialogue,
            character_relationships=prompt_context.get("character_relationships", {}),
            world_time=clock_snapshot.world_now.isoformat(),
            execution_key=(
                f"dialogue:{session_id}:{request_id}"
                if request_id
                else None
            ),
            trigger_source="dialogue",
        )
        
        event_results = event_runtime.detect_and_execute_events(event_context)
        dialogue, new_affinity, new_trust, mood_after, triggered_events_info, event_notification = (
            event_runtime.apply_event_results_to_dialogue_state(
                event_results,
                dialogue,
                new_affinity,
                new_trust,
                mood_after,
            )
        )
        event_notifications = event_runtime.collect_event_notifications(event_results)
        
    except Exception as e:
        logger.error(f"事件系统处理失败: {e}", exc_info=True)

    final_affinity_delta = round(new_affinity - previous_affinity, 6)
    final_trust_delta = round(new_trust - previous_trust, 6)

    try:
        # 更新最终状态
        repository.save_runtime_state(
            character_id,
            player_id,
            new_affinity,
            new_trust,
            mood_after
        )

        user_msg_id = _append_short_term_message(
            session_id,
            "user",
            player_message,
            world_created_at=clock_snapshot.world_now.isoformat(),
        )
        assistant_msg_id = _append_short_term_message(
            session_id,
            "assistant",
            dialogue,
            action=action,
            affinity_delta=final_affinity_delta,
            trust_delta=final_trust_delta,
            current_affinity=new_affinity,
            current_trust=new_trust,
            current_mood=mood_after,
            event_notification=event_notification,
            world_created_at=clock_snapshot.world_now.isoformat(),
            knowledge_sources=knowledge.sources,
        )

        if repository.is_long_term_memory_checkpoint(
            session_id, configs.long_term_memory_interval_turns
        ):
            player_history = repository.get_short_term_history(
                session_id,
                limit_turns=configs.long_term_memory_interval_turns,
            )
            repository.save_long_term_fact(
                character_id,
                player_id,
                extract_player_memory(player_history),
            )
    except Exception as e:
        logger.error(f"对话持久化失败: {e}", exc_info=True)
        raise RuntimeError("对话持久化失败") from e
        
    # =========================
    # 返回结果
    # =========================
    return {
        "dialogue": dialogue,
        "action": action,
        "affinity_delta": final_affinity_delta,
        "trust_delta": final_trust_delta,
        "current_affinity": new_affinity,
        "current_trust": new_trust,
        "current_mood": mood_after,
        "triggered_events": triggered_events_info,
        "event_executions": [
            result.model_dump(mode="json")
            for result in event_results
            if hasattr(result, "model_dump")
        ],
        "event_notifications": event_notifications,
        "event_notification": event_notification,
        "user_message_id": user_msg_id,
        "assistant_message_id": assistant_msg_id,
        "world_created_at": clock_snapshot.world_now.isoformat(),
        "knowledge_sources": knowledge.sources,
    }
