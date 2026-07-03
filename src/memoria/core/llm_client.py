"""
LLM 调用适配层
对应设计文档：

设计目标：
1. 统一 OpenAI-compatible API 调用接口
2. 支持多模型切换
3. 对 JSON 输出进行三层容错解析
4. 永不因模型输出格式问题导致系统崩溃
"""

import json
import logging
import re
from typing import Optional

from openai import BadRequestError, OpenAI

from memoria.core.config import configs

logger = logging.getLogger(__name__)

# =========================
# OpenAI Client（轻量单例）
# =========================
_client = OpenAI(
    base_url = configs.llm_base_url,
    api_key = configs.llm_api_key.get_secret_value()
)

# 轻量任务专用 Client（如果配置了则使用，否则使用主 Client）
if configs.llm_light_base_url and configs.llm_light_api_key.get_secret_value():
    _light_client = OpenAI(
        base_url = configs.llm_light_base_url,
        api_key = configs.llm_light_api_key.get_secret_value()
    )
    logger.info(f"Light task client initialized: {configs.llm_light_base_url}")
else:
    _light_client = _client
    logger.info("Light task using main LLM client")

# =========================
# 自定义异常（保留扩展能力）
# =========================
class LLMOutputParseError(Exception):
    pass

# =========================
# JSON 提取器（宽松模式）
# =========================
def _extract_json(raw_text: str) -> Optional[dict]:
    """
    从模型输出中尽可能提取 JSON

    支持：
    - 纯 JSON
    - ```json code block
    - 夹杂解释文本
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    
    # -------------------------
    # 情况1：完整 JSON
    # -------------------------
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # -------------------------
    # 情况2：```json 或 ``` 包裹
    # -------------------------
    code_block = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass
        
    # -------------------------
    # 情况3：提取第一个 JSON 对象（非贪婪）
    # -------------------------
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None

# =========================
# JSON 修复请求（二次纠错）
# =========================
def _retry_as_json(raw_text: str, model: str) -> Optional[dict]:
    """
    当解析失败时，将模型输出重新转换为标准 JSON
    （将任务从“生成+格式”转为“纯格式转换”，成功率更高）
    """
    fix_prompt = f"""
请将以下内容转换为严格 JSON 格式。

要求：
- 只输出 JSON
- 不要添加任何解释
- 不要 Markdown
- 保持原始 dialogue 内容不变

JSON 结构如下：
{{
  "dialogue": "...",
  "action": "neutral",
  "affinity_delta": 0,
  "mood_after": "平静",
  "memory_worth_keeping": null
}}

原始内容：
{raw_text}
""".strip()

    try:
        response = _client.chat.completions.create(
            model = model,
            messages = [{"role": "user", "content": fix_prompt}],
            max_tokens = 300,
            temperature = 0.2,
        )
        
        fix_text = response.choices[0].message.content or ""
        return _extract_json(fix_text)
    except Exception:
        logger.warning("json修复请求失败",exc_info = True)
        return None
    
    
# =========================
# 最终兜底策略（保证系统不崩）
# =========================
def _plain_text_fallback(raw_text: str, default_action: str = "neutral") -> dict:
    """
    当 JSON 完全解析失败时：
    - 保留模型输出作为 dialogue
    - 其余字段降级处理
    """

    logger.warning("LLM JSON 解析失败，进入纯文本模式: %s", raw_text[:200])

    return {
        "dialogue": raw_text.strip() or "……",
        "action": default_action,
        "affinity_delta": 0,
        "mood_after": None,  # 保持当前情绪
        "memory_worth_keeping": None,
        "_fallback_mode": True,
    }
    

# =========================
# 主 Role 调用函数
# =========================
def call_role_turn(
    system_prompt: str,
    history: list[dict],
    model: str | None = None) -> dict:
    """
    调用 LLM 生成 Role 一轮对话

    三层容错：
    1. 正常 JSON 输出解析
    2. 二次修复请求
    3. 文本兜底返回
    """
    
    model = model or configs.llm_model
    messages = [{"role": "system", "content": system_prompt}] + history
    
    # =========================
    # 1. 主请求
    # =========================
    try:
        response = _client.chat.completions.create(
            model = model,
            messages = messages,
            max_tokens = configs.max_output_tokens,
            temperature = 0.8,
            
            # 部分模型支持JSON强制模式
            response_format = {"type": "json_object"},
        )
    except BadRequestError:
        # 某些厂商不支持 response_format
        logger.warning("模型不支持 response_format，已降级为普通调用")
        
        response = _client.chat.completions.create(
            model = model,
            messages = messages,
            max_tokens = configs.max_output_tokens,
            temperature = 0.8,
        )
    
    raw_text = response.choices[0].message.content or ""
    
    # =========================
    # 2. JSON 解析
    # =========================
    result = _extract_json(raw_text)
    if result is not None:
        return result
    
    logger.warning("首次 JSON 解析失败，尝试修复")
    
    # =========================
    # 3. 修复重试
    # =========================
    result = _retry_as_json(raw_text, model)
    if result is not None:
        return result
    
    # =========================
    # 4. 兜底返回
    # =========================
    return _plain_text_fallback(raw_text)

# =========================
# 轻量任务模型（记忆/摘要等）
# =========================
def call_light_task(prompt: str) -> str:
    """
    使用轻量模型处理辅助任务（低成本）
    """
    
    logger.debug(f"Calling light model: {configs.light_model}")
    
    try:
        response = _light_client.chat.completions.create(
            model = configs.light_model,
            messages = [{"role": "user", "content": prompt}],
            max_tokens = 800,
            temperature = 0.3,
        )
        
        if not response.choices:
            logger.warning("No choices in LLM response")
            return ""
        
        message = response.choices[0].message
        
        # 优先使用 content，如果为空则尝试 reasoning_content（推理模型）
        content = message.content
        
        if not content or content.strip() == "":
            if hasattr(message, 'reasoning_content') and message.reasoning_content:
                logger.debug("Using reasoning_content instead of content")
                content = message.reasoning_content
            else:
                logger.warning("Both content and reasoning_content are empty")
                return ""
        
        result = content.strip()
        logger.debug(f"Light task completed, result length: {len(result)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Exception in call_light_task: {e}")
        return ""

