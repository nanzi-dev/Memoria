"""
记忆萃取模块（Memory Extractor）

用途：
- 从对话历史中提取重要事实
- 对长期记忆进行总结和压缩
- 识别关键信息并评估重要性

设计思路：
- 使用轻量模型处理萃取任务（降低成本）
- 支持批量处理多轮对话
- 可扩展为定期后台任务
"""

import logging
from typing import Optional

from app.core import llm_client

logger = logging.getLogger(__name__)

# =========================
# 记忆萃取提示词模板
# =========================
MEMORY_EXTRACTION_PROMPT = """
请从以下对话中提取关于玩家的重要信息。

对话历史：
{dialogue_history}

要求：
1. 只提取关于玩家的事实性信息（姓名、职业、喜好、经历等）
2. 每条信息独立成句，简洁明确
3. 忽略无关紧要的闲聊内容
4. 如果没有值得记录的信息，返回 "无"

请以列表形式输出，每行一条信息：
"""

# =========================
# 记忆总结提示词模板
# =========================
MEMORY_SUMMARY_PROMPT = """
请对以下关于玩家的记忆进行总结压缩，保留最重要的信息。

现有记忆：
{existing_facts}

要求：
1. 去除重复和矛盾的信息
2. 保留最新、最重要的事实
3. 合并相似的内容
4. 保持信息的准确性

请输出压缩后的记忆列表，每行一条：
"""

# =========================
# 重要性评分提示词模板
# =========================
IMPORTANCE_SCORING_PROMPT = """
请评估以下信息的重要性，返回1-10的分数。

信息：{fact}

评分标准：
- 1-3分：日常闲聊，无长期价值
- 4-6分：一般信息，可能有用
- 7-9分：重要信息，应当记住
- 10分：关键信息，必须记住

只返回数字分数：
"""


# =========================
# 从对话历史中提取记忆
# =========================
def extract_memories_from_dialogue(dialogue_history: list[dict]) -> list[str]:
    """
    从对话历史中提取重要记忆
    
    参数：
    - dialogue_history: 对话历史列表，格式为 [{"role": "user", "content": "..."}, ...]
    
    返回：
    - 提取的记忆列表
    """
    if not dialogue_history:
        return []
    
    # 将对话历史格式化为文本
    formatted_history = "\n".join([
        f"{msg['role']}: {msg['content']}" 
        for msg in dialogue_history
    ])
    
    prompt = MEMORY_EXTRACTION_PROMPT.format(dialogue_history=formatted_history)
    
    try:
        result = llm_client.call_light_task(prompt)
        
        # 解析结果
        if not result or result.strip().lower() in ("无", "none", "null", ""):
            return []
        
        # 按行分割，过滤空行
        memories = [
            line.strip().lstrip("-•*").strip() 
            for line in result.split("\n") 
            if line.strip() and not line.strip().lower() in ("无", "none")
        ]
        
        return memories
    
    except Exception as e:
        logger.error("记忆萃取失败: %s", e, exc_info=True)
        return []


# =========================
# 总结和压缩记忆
# =========================
def summarize_memories(existing_facts: list[str], max_facts: int = 20) -> list[str]:
    """
    总结和压缩长期记忆
    
    参数：
    - existing_facts: 现有的事实列表
    - max_facts: 最大保留的事实数量
    
    返回：
    - 压缩后的记忆列表
    """
    if not existing_facts:
        return []
    
    # 如果数量未超标，不需要压缩
    if len(existing_facts) <= max_facts:
        return existing_facts
    
    formatted_facts = "\n".join([f"- {fact}" for fact in existing_facts])
    prompt = MEMORY_SUMMARY_PROMPT.format(existing_facts=formatted_facts)
    
    try:
        result = llm_client.call_light_task(prompt)
        
        # 解析结果
        summarized = [
            line.strip().lstrip("-•*").strip() 
            for line in result.split("\n") 
            if line.strip()
        ]
        
        # 确保不超过最大数量
        return summarized[:max_facts]
    
    except Exception as e:
        logger.error("记忆总结失败: %s", e, exc_info=True)
        # 降级策略：返回最新的 max_facts 条
        return existing_facts[-max_facts:]


# =========================
# 评估记忆重要性
# =========================
def score_memory_importance(fact: str) -> int:
    """
    评估单条记忆的重要性
    
    参数：
    - fact: 要评估的事实
    
    返回：
    - 重要性分数 (1-10)
    """
    if not fact or not fact.strip():
        return 1
    
    prompt = IMPORTANCE_SCORING_PROMPT.format(fact=fact)
    
    try:
        result = llm_client.call_light_task(prompt)
        
        # 尝试解析数字
        score = int(result.strip())
        
        # 确保分数在有效范围内
        return max(1, min(10, score))
    
    except Exception as e:
        logger.warning("重要性评分失败，使用默认值: %s", e)
        # 默认中等重要性
        return 5


# =========================
# 批量处理对话历史
# =========================
def batch_extract_from_sessions(
    session_messages: list[dict], 
    batch_size: int = 10
) -> list[tuple[str, int]]:
    """
    批量从多个会话中提取记忆
    
    参数：
    - session_messages: 会话消息列表
    - batch_size: 每批处理的消息数量
    
    返回：
    - (记忆, 重要性分数) 的列表
    """
    all_memories = []
    
    for i in range(0, len(session_messages), batch_size):
        batch = session_messages[i:i + batch_size]
        memories = extract_memories_from_dialogue(batch)
        
        for memory in memories:
            importance = score_memory_importance(memory)
            all_memories.append((memory, importance))
    
    # 按重要性排序
    all_memories.sort(key=lambda x: x[1], reverse=True)
    
    return all_memories


# =========================
# 去重和合并相似记忆
# =========================
def deduplicate_memories(memories: list[str]) -> list[str]:
    """
    去除重复的记忆（简单实现）
    
    参数：
    - memories: 记忆列表
    
    返回：
    - 去重后的记忆列表
    """
    if not memories:
        return []
    
    # 简单去重：基于文本相似度
    seen = set()
    unique_memories = []
    
    for memory in memories:
        # 标准化：去除空格、标点，转小写
        normalized = memory.lower().strip().replace(" ", "").replace("，", "").replace("。", "")
        
        if normalized not in seen and normalized:
            seen.add(normalized)
            unique_memories.append(memory)
    
    return unique_memories
