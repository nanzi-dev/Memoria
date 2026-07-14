"""
多角色记忆系统

功能：
1. 管理多角色场景下的记忆
2. 角色间共享记忆（shared_memory 表）
3. 群体记忆（group_memory 表）
4. 多角色会话摘要生成
"""

import json
import logging
from typing import Optional

from memoria.core import llm_client, relationship_context
from memoria.core.memory_extractor import clean_summary_text
from memoria.db import repository

logger = logging.getLogger(__name__)


def _relationship_updated_at_for_pair(
    character_relationships: dict | None,
    player_id: str,
    character_id_a: str,
    character_id_b: str
) -> str | None:
    relationship = relationship_context.relationship_between(
        character_relationships,
        character_id_a,
        character_id_b
    )
    updated_at = relationship.get("updated_at") if relationship else None
    revision_updated_at = repository.get_character_relationship_updated_at(
        player_id,
        character_id_a,
        character_id_b
    )
    return relationship_context.latest_timestamp(updated_at, revision_updated_at)


def get_relationship_history_cutoff(
    player_id: str,
    character_ids: list[str],
    character_relationships: dict | None = None
) -> str | None:
    """返回参与角色图谱最近一次变更时间，包含已删除关系。"""
    latest = None
    clean_character_ids = [cid for cid in character_ids if cid]
    for idx, character_id_a in enumerate(clean_character_ids):
        for character_id_b in clean_character_ids[idx + 1:]:
            updated_at = _relationship_updated_at_for_pair(
                character_relationships,
                player_id,
                character_id_a,
                character_id_b
            )
            latest = relationship_context.latest_timestamp(latest, updated_at)
    return latest


def load_player_memories_for_relationship_graph(
    character_id: str,
    player_id: str,
    other_character_ids: list[str],
    relationship_history_cutoff: str | None = None,
    query_context: str | None = None,
    relationship_aliases: list[str] | None = None,
    limit: int = 10
) -> list[str]:
    """
    加载多角色场景下的长期记忆。

    关系图谱修订只隔离旧的角色关系事实；普通玩家事实、经历事实和世界事实
    不应因为图谱更新而从长期记忆上下文中消失。
    """
    participant_aliases = relationship_context.normalize_aliases(
        [character_id, *other_character_ids, *(relationship_aliases or [])]
    )
    records = repository.get_long_term_fact_records(
        character_id=character_id,
        player_id=player_id,
        limit=max(limit * 3, 20),
        query_context=query_context,
    )
    records = relationship_context.filter_stale_relationship_memory_records(
        records,
        relationship_history_cutoff,
        participant_aliases=participant_aliases,
        text_key="fact_text",
        relationship_context=False,
    )
    return [record["fact_text"] for record in records[:limit]]


# =========================
# 多角色记忆提取
# =========================

def extract_multi_character_memories(
    session_id: str,
    recent_messages: list[dict],
    character_ids: list[str]
) -> dict[str, list[str]]:
    """
    从多角色对话中提取记忆
    
    为每个角色提取他们应该记住的内容，包括：
    - 对玩家的了解
    - 对其他角色的观察
    - 重要的群体事件
    
    Args:
        session_id: 会话ID
        recent_messages: 最近的消息列表
        character_ids: 参与角色ID列表
    
    Returns:
        dict: {character_id: [memory_facts]}
    """
    if not recent_messages:
        return {}
    
    dialogue_text = _format_messages_for_extraction(recent_messages)
    
    character_memories = {}
    
    for char_id in character_ids:
        try:
            memories = _extract_character_specific_memories(
                char_id,
                dialogue_text,
                character_ids
            )
            
            if memories:
                character_memories[char_id] = memories
                logger.info(f"为角色 {char_id} 提取了 {len(memories)} 条记忆")
        
        except Exception as e:
            logger.error(f"为角色 {char_id} 提取记忆失败: {e}")
    
    return character_memories


def _format_messages_for_extraction(messages: list[dict]) -> str:
    """格式化消息用于记忆提取"""
    lines = []
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        char_name = msg.get("character_name", "")
        
        if role == "user":
            lines.append(f"玩家: {content}")
        elif role == "assistant" and char_name:
            lines.append(f"{char_name}: {content}")
    
    return "\n".join(lines)


def _extract_character_specific_memories(
    character_id: str,
    dialogue_text: str,
    all_character_ids: list[str]
) -> list[str]:
    """为特定角色提取记忆"""
    prompt = f"""
分析以下多角色对话，从角色 {character_id} 的视角，提取值得记住的信息。

对话内容：
{dialogue_text}

请提取以下类型的记忆：
1. 关于玩家的新信息（兴趣、背景、态度等）
2. 对其他角色的观察和印象
3. 重要的群体事件或决定
4. 情感变化或关系变化

要求：
- 以第一人称视角记录（我注意到...、我了解到...）
- 每条记忆独立、具体、有价值
- 不要记录琐碎的闲聊
- 最多提取5条最重要的记忆

请以JSON数组格式输出：
["记忆1", "记忆2", ...]

如果没有值得记住的内容，返回空数组 []
"""
    
    try:
        response = llm_client.call_light_task(prompt)
        memories = json.loads(response)
        
        if isinstance(memories, list):
            return [m for m in memories if m and isinstance(m, str)]
        else:
            logger.warning(f"记忆提取返回非数组格式: {response}")
            return []
    
    except json.JSONDecodeError as e:
        logger.error(f"记忆提取JSON解析失败: {e}")
        return []
    
    except Exception as e:
        logger.error(f"记忆提取失败: {e}")
        return []


def _parse_json_array_response(response: str) -> list:
    """从轻量模型响应中提取 JSON 数组。"""
    if not response:
        return []
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []

    return data if isinstance(data, list) else []


def _parse_json_object_response(response: str) -> dict:
    """从轻量模型响应中提取 JSON 对象。"""
    if not response:
        return {}
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def extract_dialogue_pulse_memories(
    recent_messages: list[dict],
    character_ids: list[str],
) -> dict:
    """一次调用提取脉冲内玩家事实、共同经历和受限秘密。"""
    clean_character_ids = list(dict.fromkeys(cid for cid in character_ids if cid))
    dialogue_text = _format_messages_for_extraction(recent_messages)
    if not dialogue_text.strip() or not clean_character_ids:
        return {"player_facts": [], "shared_facts": [], "secret_facts": []}

    prompt = f"""
分析以下多角色群聊脉冲，只提取值得长期记住的新事实。

实际在场角色ID：
{json.dumps(clean_character_ids, ensure_ascii=False)}

脉冲内容：
{dialogue_text}

规则：
- player_facts：玩家明确透露的个人事实；不要把 NPC 的经历误记成玩家事实
- shared_facts：所有在场角色共同见证的决定、事件、承诺或关系变化
- secret_facts：只有部分在场角色可以知道的事实，每条必须给 allowed_character_ids
- allowed_character_ids 只能来自实际在场角色ID；不确定谁能知道时不要提取为秘密
- 忽略寒暄、修辞、推测和无剧情价值的闲聊
- 每类最多 5 条，没有则返回空数组
- 只返回合法 JSON 对象，不使用 Markdown 或解释文字

格式：
{{
  "player_facts": ["玩家事实"],
  "shared_facts": ["共同经历"],
  "secret_facts": [
    {{"fact": "秘密事实", "allowed_character_ids": ["角色ID"]}}
  ]
}}
"""
    try:
        raw = llm_client.call_light_task(prompt, allow_reasoning_fallback=False)
        payload = _parse_json_object_response(raw)
    except Exception as exc:
        logger.error("群聊脉冲记忆提取失败: %s", exc)
        payload = {}

    player_facts = [
        str(fact).strip()
        for fact in payload.get("player_facts", [])[:5]
        if isinstance(fact, str) and fact.strip()
    ]
    shared_facts = [
        str(fact).strip()
        for fact in payload.get("shared_facts", [])[:5]
        if isinstance(fact, str) and fact.strip()
    ]
    allowed = set(clean_character_ids)
    secret_facts = []
    for row in payload.get("secret_facts", [])[:5]:
        if not isinstance(row, dict):
            continue
        fact = str(row.get("fact") or "").strip()
        allowed_ids = [
            character_id
            for character_id in row.get("allowed_character_ids", [])
            if character_id in allowed
        ]
        if fact and allowed_ids:
            secret_facts.append({
                "fact": fact,
                "allowed_character_ids": list(dict.fromkeys(allowed_ids)),
            })
    return {
        "player_facts": player_facts,
        "shared_facts": shared_facts,
        "secret_facts": secret_facts,
    }


def process_dialogue_pulse_memories(
    session_id: str,
    recent_messages: list[dict],
    character_ids: list[str],
    player_id: str,
) -> dict:
    """提取一次并按在场/知情范围持久化整个对话脉冲的长期记忆。"""
    present_ids = list(dict.fromkeys(cid for cid in character_ids if cid))
    extracted = extract_dialogue_pulse_memories(recent_messages, present_ids)

    for fact in extracted["player_facts"]:
        for character_id in present_ids:
            repository.save_long_term_fact(character_id, player_id, fact, importance=7)

    for fact in extracted["shared_facts"]:
        repository.save_group_memory(
            session_id=session_id,
            memory_text=fact,
            participants=present_ids,
            context="dialogue_pulse",
            importance=0.7,
        )
        for index, character_id_a in enumerate(present_ids):
            for character_id_b in present_ids[index + 1:]:
                repository.save_shared_memory(
                    owner_user_id=player_id,
                    character_a_id=character_id_a,
                    character_b_id=character_id_b,
                    memory_text=fact,
                    context=f"session:{session_id}:dialogue_pulse",
                    importance=0.7,
                )

    for row in extracted["secret_facts"]:
        for character_id in row["allowed_character_ids"]:
            repository.save_long_term_fact(
                character_id,
                player_id,
                row["fact"],
                importance=8,
            )
    return extracted


def extract_character_impressions(
    session_id: str,
    recent_messages: list[dict],
    character_ids: list[str]
) -> list[dict]:
    """
    从多角色对话中提取角色间印象。

    返回结构：
    [{"observer_id": "...", "target_id": "...", "impression": "...", "importance": 0.6}]
    """
    clean_character_ids = [cid for cid in character_ids if cid]
    if len(clean_character_ids) < 2 or not recent_messages:
        return []

    dialogue_text = _format_messages_for_extraction(recent_messages)
    if not dialogue_text.strip():
        return []

    prompt = f"""
分析以下多角色群聊，只提取角色之间值得长期记住的印象、冲突、合作、承诺或共同经历。

参与角色ID：
{json.dumps(clean_character_ids, ensure_ascii=False)}

对话内容：
{dialogue_text}

要求：
- 只记录角色对其他角色的印象或角色之间的共同经历
- 不要记录玩家个人信息，玩家相关记忆不属于本任务
- 忽略寒暄、告别、无意义闲聊
- observer_id 和 target_id 必须来自参与角色ID，且不能相同
- impression 使用简短中文，不要带“分析”“原因”等说明
- importance 为 0.0 到 1.0 的数字，默认 0.6
- 没有值得记录的内容时返回 []
- 只返回 JSON 数组，不要输出任何解释、前缀或 Markdown

JSON 格式：
[
  {{"observer_id":"角色A","target_id":"角色B","impression":"角色A认为角色B在行动中很可靠","importance":0.7}}
]
"""

    try:
        response = llm_client.call_light_task(prompt, allow_reasoning_fallback=False)
        rows = _parse_json_array_response(response)
    except Exception as e:
        logger.error(f"角色间印象提取失败: {e}")
        return []

    allowed = set(clean_character_ids)
    impressions = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        observer_id = str(row.get("observer_id") or "").strip()
        target_id = str(row.get("target_id") or "").strip()
        impression = str(row.get("impression") or "").strip()
        if not observer_id or not target_id or not impression:
            continue
        if observer_id == target_id or observer_id not in allowed or target_id not in allowed:
            continue
        try:
            importance = float(row.get("importance", 0.6))
        except (TypeError, ValueError):
            importance = 0.6
        importance = max(0.0, min(1.0, importance))
        impressions.append({
            "observer_id": observer_id,
            "target_id": target_id,
            "impression": impression,
            "importance": importance,
        })

    return impressions


# =========================
# 角色间印象记忆（shared_memory）
# =========================

def save_character_impression(
    observer_id: str,
    target_id: str,
    impression: str,
    session_id: str,
    player_id: str = None,
    importance: float = 0.6
):
    """
    保存角色对其他角色的印象
    
    Args:
        observer_id: 观察者角色ID
        target_id: 目标角色ID
        impression: 印象描述
        session_id: 会话ID（作为上下文）
        player_id: 当前用户/玩家ID，用于隔离不同用户的角色间记忆
        importance: 重要性权重（默认 0.6）
    
    Returns:
        str: 记忆ID
    """
    if not player_id:
        raise ValueError("player_id is required for character impression isolation")
    memory_text = f"对 {target_id} 的印象：{impression}"
    
    memory_id = repository.save_shared_memory(
        owner_user_id=player_id,
        character_a_id=observer_id,
        character_b_id=target_id,
        memory_text=memory_text,
        context=f"session:{session_id}",
        importance=importance
    )
    
    logger.info(f"保存角色印象: {observer_id} -> {target_id}, id={memory_id}")
    return memory_id


def get_character_impressions(
    observer_id: str,
    target_id: str,
    player_id: str = None,
    limit: int = 5
) -> list[dict]:
    """
    获取角色对其他角色的印象记忆
    
    Args:
        observer_id: 观察者角色ID
        target_id: 目标角色ID
        player_id: 当前用户/玩家ID，用于隔离不同用户的角色间记忆
        limit: 最大返回数量
    
    Returns:
        list[dict]: 印象记忆列表，每项含 memory_text、importance 等字段
    """
    if not player_id:
        raise ValueError("player_id is required for character impression isolation")
    return repository.get_shared_memories(
        owner_user_id=player_id,
        character_id_a=observer_id,
        character_id_b=target_id,
        limit=limit
    )


def process_character_impressions(
    session_id: str,
    recent_messages: list[dict],
    character_ids: list[str],
    player_id: str
) -> int:
    """提取并保存群聊中的角色间印象。"""
    if not player_id:
        raise ValueError("player_id is required for character impression processing")
    if len(character_ids) < 2 or not recent_messages:
        return 0

    impressions = extract_character_impressions(
        session_id=session_id,
        recent_messages=recent_messages,
        character_ids=character_ids,
    )

    saved_count = 0
    for item in impressions:
        try:
            save_character_impression(
                observer_id=item["observer_id"],
                target_id=item["target_id"],
                impression=item["impression"],
                session_id=session_id,
                player_id=player_id,
                importance=item.get("importance", 0.6),
            )
            saved_count += 1
        except Exception as e:
            logger.error(f"保存角色间印象失败: session={session_id}, item={item}, error={e}")

    if saved_count:
        logger.info(f"保存角色间印象: session={session_id}, count={saved_count}")
    return saved_count


# =========================
# 群体记忆（group_memory）
# =========================

def save_group_event_memory(
    event_description: str,
    character_ids: list[str],
    session_id: str,
    importance: float = 0.7
):
    """
    保存群体事件记忆
    
    Args:
        event_description: 事件描述
        character_ids: 参与角色ID列表
        session_id: 会话ID
        importance: 重要性权重（默认 0.7）
    
    Returns:
        str: 记忆ID
    """
    memory_text = f"群体事件：{event_description}"
    
    memory_id = repository.save_group_memory(
        session_id=session_id,
        memory_text=memory_text,
        participants=character_ids,
        importance=importance
    )
    
    logger.info(f"保存群体记忆: session={session_id}, participants={len(character_ids)}, id={memory_id}")
    return memory_id


def get_group_memories(
    character_id: str,
    session_id: str,
    limit: int = 10
) -> list[dict]:
    """
    获取某个角色在某会话中的群体记忆
    
    优先按 session_id 精确查询，若该会话无群体记忆则按角色查询。
    
    Args:
        character_id: 角色ID
        session_id: 会话ID
        limit: 最大返回数量
    
    Returns:
        list[dict]: 群体记忆列表
    """
    # 先按会话精确查询
    memories = repository.get_session_group_memories(
        session_id=session_id,
        limit=limit
    )
    
    if memories:
        return memories
    
    # 回退：按角色查询历史群体记忆
    return repository.get_character_group_memories(
        character_id=character_id,
        limit=limit
    )


# =========================
# 多角色会话摘要
# =========================

def generate_multi_character_summary(
    session_id: str,
    messages: list[dict],
    character_names: dict[str, str],
    player_name: str
) -> str:
    """
    生成多角色会话摘要
    
    Args:
        session_id: 会话ID
        messages: 消息列表
        character_names: 角色ID到名称的映射
        player_name: 玩家名称
    
    Returns:
        str: 会话摘要
    """
    if not messages:
        return "空会话"
    
    dialogue_text = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        char_id = msg.get("character_id")
        
        if role == "user":
            dialogue_text.append(f"{player_name}: {content}")
        elif role == "assistant" and char_id:
            char_name = character_names.get(char_id, "未知角色")
            dialogue_text.append(f"{char_name}: {content}")
    
    dialogue_str = "\n".join(dialogue_text)
    participants_str = "、".join(character_names.values())
    
    prompt = f"""
请为以下多角色群聊生成简洁的会话摘要。

参与者：{player_name}（玩家）、{participants_str}

对话内容：
{dialogue_str}

摘要要求：
1. 客观描述主要讨论的话题和事件
2. 记录重要的决定或结论
3. 概括角色间的互动和氛围
4. 2-3句话，简洁明了
5. 不要使用"本次对话"等元叙述

直接输出摘要文本，不要有任何前缀。
"""
    
    try:
        summary = llm_client.call_light_task(prompt, allow_reasoning_fallback=False)
        summary = clean_summary_text(summary) or ""
        logger.info(f"生成多角色会话摘要: session={session_id}, length={len(summary)}")
        return summary
    
    except Exception as e:
        logger.error(f"生成摘要失败: {e}")
        return f"多角色对话（{len(messages)}条消息）"


def save_multi_character_summary(
    session_id: str,
    character_ids: list[str],
    player_id: str,
    summary_text: str,
    message_count: int
):
    """
    保存多角色会话摘要
    
    同时保存到 session_summary（每个角色一份）和 group_memory（群体记忆）。
    
    Args:
        session_id: 会话ID
        character_ids: 参与角色ID列表
        player_id: 玩家ID
        summary_text: 摘要文本
        message_count: 消息数量
    """
    # 为每个角色保存独立摘要（兼容单角色查询逻辑）
    for char_id in character_ids:
        repository.save_session_summary(
            session_id=session_id,
            character_id=char_id,
            player_id=player_id,
            summary_text=summary_text,
            message_count=message_count
        )
    
    # 同时保存为群体记忆
    repository.save_group_memory(
        session_id=session_id,
        memory_text=f"会话摘要：{summary_text}",
        participants=character_ids,
        context=f"共 {message_count} 条消息",
        importance=0.5
    )
    
    logger.info(f"为 {len(character_ids)} 个角色保存会话摘要")


# =========================
# 记忆整合
# =========================

def integrate_multi_character_context(
    character_id: str,
    player_id: str,
    session_id: str,
    other_character_ids: list[str],
    query_context: str = None,
    character_relationships: dict | None = None,
    relationship_aliases: list[str] | None = None
) -> dict:
    """
    整合多角色场景的完整上下文
    
    包括：
    - 对玩家的记忆（long_term_fact）
    - 对其他角色的印象（shared_memory）
    - 群体记忆（group_memory）
    
    Args:
        character_id: 当前角色ID
        player_id: 玩家ID
        session_id: 会话ID
        other_character_ids: 其他参与角色ID列表
        query_context: 查询上下文（用于向量检索）
        character_relationships: 当前关系图谱，用于过滤图谱更新前的旧角色印象
        relationship_aliases: 参与角色的 ID / 名称别名，用于识别长期记忆里的关系事实
    
    Returns:
        dict: 完整的记忆上下文
    """
    context = {
        "player_memories": [],
        "character_impressions": {},
        "group_memories": []
    }
    participant_ids = [character_id] + [cid for cid in other_character_ids if cid != character_id]
    relationship_context_updated_at = get_relationship_history_cutoff(
        player_id,
        participant_ids,
        character_relationships
    )
    
    # 1. 对玩家的记忆：只过滤图谱修订前的关系事实，保留普通长期记忆
    player_memories = load_player_memories_for_relationship_graph(
        character_id=character_id,
        player_id=player_id,
        other_character_ids=other_character_ids,
        relationship_history_cutoff=relationship_context_updated_at,
        query_context=query_context,
        relationship_aliases=relationship_aliases,
        limit=10,
    )
    context["player_memories"] = player_memories
    
    # 2. 对其他角色的印象（从 shared_memory 表查询）
    for other_id in other_character_ids:
        if other_id != character_id:
            relationship_updated_at = _relationship_updated_at_for_pair(
                character_relationships,
                player_id,
                character_id,
                other_id
            )
            impressions = repository.get_shared_memories(
                owner_user_id=player_id,
                character_id_a=character_id,
                character_id_b=other_id,
                limit=10,
            )
            relationship = relationship_context.relationship_between(
                character_relationships,
                character_id,
                other_id,
            )
            impressions = relationship_context.filter_stale_relationship_memory_records(
                impressions,
                relationship_updated_at,
                participant_aliases=[character_id, other_id, *(relationship_aliases or [])],
                text_key="memory_text",
                relationship_context=True,
                relationship=relationship,
            )
            if impressions:
                # 提取 memory_text 用于 prompt 构建
                context["character_impressions"][other_id] = [
                    imp["memory_text"] for imp in impressions[:3]
                ]
    
    # 3. 群体记忆（从 group_memory 表查询）
    group_memories = repository.get_session_group_memories(
        session_id=session_id,
        limit=10,
    )
    group_memories = relationship_context.filter_stale_relationship_memory_records(
        group_memories,
        relationship_context_updated_at,
        participant_aliases=[*participant_ids, *(relationship_aliases or [])],
        text_key="memory_text",
        relationship_context=True,
    )
    context["group_memories"] = [
        gm["memory_text"] for gm in group_memories[:5]
    ]
    
    return context


# =========================
# 自动记忆处理
# =========================

def auto_process_multi_character_memories(
    session_id: str,
    character_ids: list[str],
    player_id: str,
    trigger_threshold: int = 20,
    created_after: str | None = None
):
    """
    自动处理多角色会话的记忆
    
    当消息数达到阈值时，自动提取记忆和生成摘要
    
    Args:
        session_id: 会话ID
        character_ids: 参与角色ID列表
        player_id: 玩家ID
        trigger_threshold: 触发阈值（消息数）
        created_after: 只处理该时间之后的群聊消息
    """
    recent_messages = repository.get_multi_character_history(
        session_id=session_id,
        limit_messages=trigger_threshold,
        created_after=created_after
    )
    
    if len(recent_messages) < trigger_threshold:
        return
    
    logger.info(f"自动处理多角色记忆: session={session_id}, messages={len(recent_messages)}")
    
    # 1. 提取记忆并保存为个人长期记忆
    character_memories = extract_multi_character_memories(
        session_id=session_id,
        recent_messages=recent_messages,
        character_ids=character_ids
    )
    
    for char_id, memories in character_memories.items():
        for memory in memories:
            repository.save_long_term_fact(
                character_id=char_id,
                player_id=player_id,
                fact_text=memory,
                importance=7
            )

    impression_count = process_character_impressions(
        session_id=session_id,
        recent_messages=recent_messages,
        character_ids=character_ids,
        player_id=player_id,
    )
    
    logger.info(f"自动记忆处理完成: 为 {len(character_memories)} 个角色提取了记忆，保存 {impression_count} 条角色间印象")


# =========================
# 记忆查询工具
# =========================

def query_multi_character_memories(
    character_id: str,
    player_id: str,
    session_id: str,
    query: str,
    include_impressions: bool = True,
    include_group: bool = True
) -> dict:
    """
    查询多角色场景的记忆
    
    Args:
        character_id: 角色ID
        player_id: 玩家ID
        session_id: 会话ID
        query: 查询文本
        include_impressions: 是否包含对其他角色的印象
        include_group: 是否包含群体记忆
    
    Returns:
        dict: 查询结果
    """
    results = {
        "player_memories": [],
        "character_impressions": [],
        "group_memories": []
    }
    
    # 查询对玩家的记忆（使用向量检索）
    player_memories = repository.get_long_term_facts(
        character_id=character_id,
        player_id=player_id,
        limit=10,
        query_context=query
    )
    results["player_memories"] = player_memories
    
    # 查询对其他角色的印象
    if include_impressions:
        shared = repository.get_character_shared_memories(
            owner_user_id=player_id,
            character_id=character_id,
            limit=10
        )
        results["character_impressions"] = [
            {"with": s["character_b_id"] if s["character_a_id"] == character_id else s["character_a_id"],
             "memory": s["memory_text"]}
            for s in shared
        ]
    
    # 查询群体记忆
    if include_group:
        group_memories = repository.get_character_group_memories(
            character_id=character_id,
            limit=5,
            owner_user_id=player_id,
        )
        results["group_memories"] = [gm["memory_text"] for gm in group_memories]
    
    return results
