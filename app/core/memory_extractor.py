"""
记忆萃取模块。
用便宜模型从单轮对话里判断是否有值得长期记住的事实。

注：主流程里，结构化输出本身已经带了 memory_worth_keeping 字段
（让主模型在生成对话的同时顺带判断），这是更省成本的做法，已在 orchestrator.py 里使用。
本模块提供的是"批量回顾多轮对话做摘要"的能力，用于会话结束时的摘要萃取（中期记忆），在对话轮次较多、单轮判断可能遗漏跨轮关联信息时补充使用。
"""
from app.core.llm_client import call_light_task

SUMMARY_PROMPT_TEMPLATE = """请阅读以下这段游戏NPC与玩家的对话，用1-3句话概括这次对话中发生的关键事情（比如玩家做了什么承诺、送了什么礼物、透露了什么个人信息、关系发生了什么变化等）。

**重要提示**：
- 请忽略寒暄和不重要的细节
- 如果这段对话确实没有任何值得记录的内容，请输出"无"
- 如果有值得记录的内容，请直接输出摘要文本，不要添加任何前缀或说明

对话内容：
{transcript}

摘要："""


def summarize_session(history: list[dict]) -> str | None:
    """对一段对话历史做摘要萃取，用于会话结束时写入 session_summary 表。"""
    if not history:
        return None
    
    transcript = "\n".join(
        f"{'玩家' if m['role'] == 'user' else 'NPC'}：{m['content']}" for m in history
    )
    
    prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)
    result = call_light_task(prompt)
    
    if not result:
        return None
    
    result_stripped = result.strip()
    
    # 检查是否是无效回复
    if result_stripped.lower() in ("无", "none", "null", "无。", "none.", "null."):
        return None
    
    return result_stripped
