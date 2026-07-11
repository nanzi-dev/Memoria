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
# OpenAI Client（懒加载单例）
# =========================
_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=configs.llm_base_url,
            api_key=configs.llm_api_key.get_secret_value()
        )
    return _client

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


def _strip_markdown_code_fence(raw_text: str) -> str:
    text = (raw_text or "").strip()
    code_block = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if code_block:
        return code_block.group(1).strip()
    return text


def _extract_balanced_json_object(raw_text: str) -> Optional[str]:
    """
    从混杂文本中按括号配平提取第一个 JSON 对象。

    正则的 `{.*}` 在字段内容包含花括号时容易截错，这里只做一个小型扫描器。
    """
    text = _strip_markdown_code_fence(raw_text)
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:] if start >= 0 else None


def _cleanup_jsonish_text(raw_text: str) -> str:
    text = _extract_balanced_json_object(raw_text) or _strip_markdown_code_fence(raw_text)
    text = text.strip()
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _json_loads_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace('\\"', '"').replace("\\n", "\n").strip()


def _extract_jsonish_string_field(text: str, field: str) -> Optional[str]:
    """
    从整体 JSON 已经损坏的文本里提取字符串字段。

    通过下一个已知字段名或对象结尾作为边界，避免把整段 JSON 都吃进 dialogue。
    """
    next_fields = (
        "dialogue", "action", "affinity_delta", "trust_delta",
        "mood_after", "memory_worth_keeping",
    )
    boundary_fields = [name for name in next_fields if name != field]
    boundary = "|".join(re.escape(name) for name in boundary_fields)
    pattern = (
        rf'"{re.escape(field)}"\s*:\s*"([\s\S]*?)"'
        rf'\s*(?=,\s*"(?:{boundary})"\s*:|\s*}})'
    )
    match = re.search(pattern, text)
    if match:
        value = _json_loads_string(match.group(1)).strip()
        return value if value else None

    bare_match = re.search(
        rf'"{re.escape(field)}"\s*:\s*(null|[^,\n\r}}]+)',
        text,
        re.I,
    )
    if not bare_match:
        return None
    value = bare_match.group(1).strip().strip('"')
    if not value or value.lower() == "null":
        return None
    return value


def _extract_jsonish_number_field(text: str, field: str, default: int = 0) -> int:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(-?\d+(?:\.\d+)?)', text)
    if not match:
        return default
    try:
        return int(float(match.group(1)))
    except Exception:
        return default


def _looks_like_provider_rejection(raw_text: str) -> bool:
    text = (raw_text or "").lower()
    return any(
        marker in text
        for marker in (
            "the request was rejected",
            "considered high risk",
            "content policy",
            "safety policy",
            "risk control",
        )
    )


def _local_role_turn_fallback(raw_text: str, default_action: str = "neutral") -> Optional[dict]:
    """
    修复模型也失败时，在本地从 JSON-ish 输出里保底提取角色回合字段。
    """
    cleaned = _cleanup_jsonish_text(raw_text)
    if not cleaned:
        return None

    # 先尝试常见的小破损：代码块、前后混杂文本、尾逗号、智能引号。
    parsed = _extract_json(cleaned)
    if isinstance(parsed, dict):
        parsed.setdefault("dialogue", "……")
        parsed.setdefault("action", default_action)
        parsed.setdefault("affinity_delta", 0)
        parsed.setdefault("trust_delta", 0)
        parsed.setdefault("mood_after", None)
        parsed.setdefault("memory_worth_keeping", None)
        parsed["_fallback_mode"] = True
        parsed["_fallback_parser"] = "local_json"
        return parsed

    dialogue = _extract_jsonish_string_field(cleaned, "dialogue")
    if not dialogue:
        return None

    return {
        "dialogue": dialogue,
        "action": _extract_jsonish_string_field(cleaned, "action") or default_action,
        "affinity_delta": _extract_jsonish_number_field(cleaned, "affinity_delta"),
        "trust_delta": _extract_jsonish_number_field(cleaned, "trust_delta"),
        "mood_after": _extract_jsonish_string_field(cleaned, "mood_after"),
        "memory_worth_keeping": _extract_jsonish_string_field(cleaned, "memory_worth_keeping"),
        "_fallback_mode": True,
        "_fallback_parser": "local_fields",
    }


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
        response = _retry_call(_get_client().chat.completions.create, 
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
    - 优先从 JSON-ish 文本中本地提取 dialogue/action/关系变化
    - 如果只是普通文本，则保留模型输出作为 dialogue
    - 如果是服务商拒绝/风控提示，则避免技术文本进入对白
    - 其余字段降级处理
    """

    local_result = _local_role_turn_fallback(raw_text, default_action)
    if local_result is not None:
        logger.warning("LLM JSON 解析失败，已使用本地字段兜底: %s", raw_text[:200])
        return local_result

    logger.warning("LLM JSON 解析失败，进入纯文本模式: %s", raw_text[:200])
    dialogue = (raw_text or "").strip()
    if _looks_like_provider_rejection(dialogue):
        dialogue = "……"

    return {
        "dialogue": dialogue or "……",
        "action": default_action,
        "affinity_delta": 0,
        "trust_delta": 0,
        "mood_after": None,  # 保持当前情绪
        "memory_worth_keeping": None,
        "_fallback_mode": True,
    }
    


import time as _time

_MAX_RETRIES = 3
_BASE_DELAY = 1.0

def _retry_call(fn, *args, **kwargs):
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning("LLM重试 %d/%d (%.1fs后): %s", attempt + 1, _MAX_RETRIES, delay, e)
                _time.sleep(delay)
    raise last_err


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
        response = _retry_call(_get_client().chat.completions.create, 
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
        
        response = _retry_call(_get_client().chat.completions.create, 
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
        response = _retry_call(_get_client().chat.completions.create, 
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
