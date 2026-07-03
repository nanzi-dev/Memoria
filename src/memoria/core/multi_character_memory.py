"""
多角色记忆系统

功能：
1. 管理多角色场景下的记忆
2. 角色间共享记忆（群体事件）
3. 角色对其他角色的印象记忆
4. 多角色会话摘要生成
"""

import json
import logging
from typing import Optional

from memoria.core import llm_client
from memoria.db import repository

logger = logging.getLogger(__name__)


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
    
    # 构建对话文本
    dialogue_text = _format_messages_for_extraction(recent_messages)
    
    # 为每个角色提取记忆
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
    """
    格式化消息用于记忆提取
    
    Args:
        messages: 消息列表
    
    Returns:
        str: 格式化后的对话文本
    """
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
    """
    为特定角色提取记忆
    
    Args:
        character_id: 角色ID
        dialogue_text: 对话文本
        all_character_ids: 所有参与角色ID
    
    Returns:
        list[str]: 记忆列表
    """
    # 构建提取提示
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
        # 调用LLM提取记忆
        response = llm_client.call_light_task(prompt)
        
        # 解析JSON
        memories = json.loads(response)
        
        if isinstance(memories, list):
            return [m for m in memories if m and isinstance(m, str)]
        else:
            logger.warning(f"记忆提取返回非数组格式: {response}")
            return []
    
    except json.JSONDecodeError as e:
        logger.error(f"记忆提取JSON解析失败: {e}, response={response[:200]}")
        return []
    
    except Exception as e:
        logger.error(f"记忆提取失败: {e}")
        return []


# =========================
# 角色间印象记忆
# =========================

def save_character_impression(
    observer_id: str,
    target_id: str,
    impression: str,
    session_id: str
):
    """
    保存角色对其他角色的印象
    
    Args:
        observer_id: 观察者角色ID
        target_id: 目标角色ID
        impression: 印象描述
        session_id: 会话ID
    """
    # 构建印象记忆文本
    memory_text = f"对{target_id}的印象：{impression}"
    
    # 保存为长期记忆（使用observer_id作为player_id的特殊标记）
    fact_id = repository.save_long_term_fact(
        character_id=observer_id,
        player_id=f"char_{target_id}",  # 特殊标记：角色间记忆
        fact_text=memory_text,
        importance=6  # 中等重要性
    )
    
    logger.info(f"保存角色印象: {observer_id} -> {target_id}")
    
    return fact_id


def get_character_impressions(
    observer_id: str,
    target_id: str,
    limit: int = 5
) -> list[str]:
    """
    获取角色对其他角色的印象记忆
    
    Args:
        observer_id: 观察者角色ID
        target_id: 目标角色ID
        limit: 最大返回数量
    
    Returns:
        list[str]: 印象记忆列表
    """
    impressions = repository.get_long_term_facts(
        character_id=observer_id,
        player_id=f"char_{target_id}",
        limit=limit
    )
    
    return impressions


# =========================
# 群体记忆
# =========================

def save_group_event_memory(
    event_description: str,
    character_ids: list[str],
    session_id: str,
    importance: int = 7
):
    """
    保存群体事件记忆（所有参与角色共享）
    
    Args:
        event_description: 事件描述
        character_ids: 参与角色ID列表
        session_id: 会话ID
        importance: 重要性（1-10）
    """
    # 为每个角色保存相同的群体记忆
    for char_id in character_ids:
        repository.save_long_term_fact(
            character_id=char_id,
            player_id=f"group_{session_id}",  # 特殊标记：群体记忆
            fact_text=f"群体事件：{event_description}",
            importance=importance
        )
    
    logger.info(f"保存群体记忆给 {len(character_ids)} 个角色")


def get_group_memories(
    character_id: str,
    session_id: str,
    limit: int = 10
) -> list[str]:
    """
    获取角色的群体记忆
    
    Args:
        character_id: 角色ID
        session_id: 会话ID
        limit: 最大返回数量
    
    Returns:
        list[str]: 群体记忆列表
    """
    memories = repository.get_long_term_facts(
        character_id=character_id,
        player_id=f"group_{session_id}",
        limit=limit
    )
    
    return memories


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
    
    # 格式化对话
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
    
    # 构建摘要提示
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
        summary = llm_client.call_light_task(prompt)
        summary = summary.strip()
        
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
    保存多角色会话摘要（为每个角色保存一份）
    
    Args:
        session_id: 会话ID
        character_ids: 参与角色ID列表
        player_id: 玩家ID
        summary_text: 摘要文本
        message_count: 消息数量
    """
    # 为每个角色保存摘要
    for char_id in character_ids:
        repository.save_session_summary(
            session_id=session_id,
            character_id=char_id,
            player_id=player_id,
            summary_text=summary_text,
            message_count=message_count
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
    query_context: str = None
) -> dict:
    """
    整合多角色场景的完整上下文
    
    包括：
    - 对玩家的记忆
    - 对其他角色的印象
    - 群体记忆
    
    Args:
        character_id: 当前角色ID
        player_id: 玩家ID
        session_id: 会话ID
        other_character_ids: 其他参与角色ID列表
        query_context: 查询上下文（用于向量检索）
    
    Returns:
        dict: 完整的记忆上下文
    """
    context = {
        "player_memories": [],
        "character_impressions": {},
        "group_memories": []
    }
    
    # 1. 对玩家的记忆
    player_memories = repository.get_long_term_facts(
        character_id=character_id,
        player_id=player_id,
        limit=10,
        query_context=query_context
    )
    context["player_memories"] = player_memories
    
    # 2. 对其他角色的印象
    for other_id in other_character_ids:
        if other_id != character_id:
            impressions = get_character_impressions(
                observer_id=character_id,
                target_id=other_id,
                limit=3
            )
            if impressions:
                context["character_impressions"][other_id] = impressions
    
    # 3. 群体记忆
    group_memories = get_group_memories(
        character_id=character_id,
        session_id=session_id,
        limit=5
    )
    context["group_memories"] = group_memories
    
    return context


# =========================
# 自动记忆处理
# =========================

def auto_process_multi_character_memories(
    session_id: str,
    character_ids: list[str],
    player_id: str,
    trigger_threshold: int = 20
):
    """
    自动处理多角色会话的记忆
    
    当消息数达到阈值时，自动提取记忆和生成摘要
    
    Args:
        session_id: 会话ID
        character_ids: 参与角色ID列表
        player_id: 玩家ID
        trigger_threshold: 触发阈值（消息数）
    """
    # 获取最近的消息
    recent_messages = repository.get_multi_character_history(
        session_id=session_id,
        limit_messages=trigger_threshold
    )
    
    if len(recent_messages) < trigger_threshold:
        return
    
    logger.info(f"自动处理多角色记忆: session={session_id}, messages={len(recent_messages)}")
    
    # 1. 提取记忆
    character_memories = extract_multi_character_memories(
        session_id=session_id,
        recent_messages=recent_messages,
        character_ids=character_ids
    )
    
    # 保存提取的记忆
    for char_id, memories in character_memories.items():
        for memory in memories:
            repository.save_long_term_fact(
                character_id=char_id,
                player_id=player_id,
                fact_text=memory,
                importance=7
            )
    
    # 2. 生成摘要（可选，根据需要）
    # 注意：这里可以选择性地生成中期摘要
    
    logger.info(f"自动记忆处理完成: 为 {len(character_memories)} 个角色提取了记忆")


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
    
    # 查询对其他角色的印象（如果需要）
    if include_impressions:
        # 这里简化处理，实际可以遍历所有其他角色
        # 暂时留空，可根据需要扩展
        pass
    
    # 查询群体记忆（如果需要）
    if include_group:
        group_memories = get_group_memories(
            character_id=character_id,
            session_id=session_id,
            limit=5
        )
        results["group_memories"] = group_memories
    
    return results
