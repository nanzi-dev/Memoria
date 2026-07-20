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
import inspect
import logging
import re
from time import perf_counter
from typing import Callable, Optional
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    BadRequestError,
    DefaultHttpxClient,
    OpenAI,
)

from memoria.core import performance, tracing
from memoria.core.config import configs

logger = logging.getLogger(__name__)

DebugSink = Callable[[str], None]


def _replace_unpaired_surrogates(value):
    if isinstance(value, str):
        return "".join(
            "\ufffd" if 0xD800 <= ord(char) <= 0xDFFF else char
            for char in value
        )
    if isinstance(value, list):
        return [_replace_unpaired_surrogates(item) for item in value]
    if isinstance(value, dict):
        return {
            _replace_unpaired_surrogates(key): _replace_unpaired_surrogates(item)
            for key, item in value.items()
        }
    return value


class _DialogueJsonStream:
    """Decode the first complete top-level string-valued dialogue field."""

    def __init__(self) -> None:
        self._stack: list[str] = []
        self._previous_significant = ""
        self._in_token_string = False
        self._token_is_top_level_key = False
        self._token_raw = ""
        self._token_escaped = False
        self._awaiting_dialogue_colon = False
        self._awaiting_dialogue_value = False
        self._raw_value = ""
        self._decoded_value = ""
        self._in_value = False
        self._value_escaped = False
        self._done = False

    @staticmethod
    def _complete_prefix_length(raw_value: str) -> int:
        index = 0
        complete_end = 0
        while index < len(raw_value):
            if raw_value[index] != "\\":
                index += 1
                complete_end = index
                continue

            if index + 1 >= len(raw_value):
                break
            escape_type = raw_value[index + 1]
            if escape_type != "u":
                index += 2
                complete_end = index
                continue

            if index + 6 > len(raw_value):
                break
            try:
                codepoint = int(raw_value[index + 2:index + 6], 16)
            except ValueError:
                break
            index += 6

            if 0xD800 <= codepoint <= 0xDBFF:
                if index >= len(raw_value):
                    break
                if raw_value[index] == "\\" and index + 2 > len(raw_value):
                    break
                if raw_value[index:index + 2] == "\\u":
                    if index + 6 > len(raw_value):
                        break
                    try:
                        low_surrogate = int(raw_value[index + 2:index + 6], 16)
                    except ValueError:
                        low_surrogate = -1
                    if 0xDC00 <= low_surrogate <= 0xDFFF:
                        index += 6

            complete_end = index
        return complete_end

    def _decode_available(self) -> list[str]:
        prefix_length = self._complete_prefix_length(self._raw_value)
        if prefix_length <= 0:
            return []
        try:
            decoded = json.loads(f'"{self._raw_value[:prefix_length]}"')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        decoded = _replace_unpaired_surrogates(decoded)
        if len(decoded) <= len(self._decoded_value):
            return []
        delta = decoded[len(self._decoded_value):]
        self._decoded_value = decoded
        return [delta] if delta else []

    def _feed_value(self, text: str) -> list[str]:
        for char in text:
            if self._value_escaped:
                self._raw_value += char
                self._value_escaped = False
                continue
            if char == "\\":
                self._raw_value += char
                self._value_escaped = True
                continue
            if char == '"':
                self._done = True
                self._in_value = False
                break
            self._raw_value += char
        return self._decode_available()

    @property
    def authoritative_dialogue(self) -> str | None:
        return self._decoded_value if self._done else None

    def feed(self, text: str) -> list[str]:
        if self._done or not text:
            return []
        if self._in_value:
            return self._feed_value(text)

        for index, char in enumerate(text):
            if self._in_token_string:
                if self._token_escaped:
                    self._token_raw += char
                    self._token_escaped = False
                    continue
                if char == "\\":
                    self._token_raw += char
                    self._token_escaped = True
                    continue
                if char != '"':
                    self._token_raw += char
                    continue

                self._in_token_string = False
                if self._token_is_top_level_key:
                    try:
                        key = json.loads(f'"{self._token_raw}"')
                    except json.JSONDecodeError:
                        key = None
                    self._awaiting_dialogue_colon = key == "dialogue"
                self._previous_significant = '"'
                continue

            if self._awaiting_dialogue_colon:
                if char.isspace():
                    continue
                self._awaiting_dialogue_colon = False
                if char == ":":
                    self._awaiting_dialogue_value = True
                    self._previous_significant = char
                    continue

            if self._awaiting_dialogue_value:
                if char.isspace():
                    continue
                self._awaiting_dialogue_value = False
                if char == '"':
                    self._in_value = True
                    return self._feed_value(text[index + 1:])

            if char == '"':
                self._in_token_string = True
                self._token_is_top_level_key = (
                    self._stack == ["{"]
                    and self._previous_significant in {"{", ","}
                )
                self._token_raw = ""
                self._token_escaped = False
                continue

            if char in "{[":
                self._stack.append(char)
            elif char == "}" and self._stack and self._stack[-1] == "{":
                self._stack.pop()
            elif char == "]" and self._stack and self._stack[-1] == "[":
                self._stack.pop()

            if not char.isspace():
                self._previous_significant = char
        return []


def _consume_role_stream(
    response,
    on_dialogue_delta: Callable[[str], None],
    request_started_at: float,
) -> tuple[str, str | None]:
    raw_parts = []
    dialogue_stream = _DialogueJsonStream()
    ttft_recorded = False
    usage = None
    for chunk in response:
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = chunk_usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) or ""
        if not content:
            continue
        raw_parts.append(content)
        for dialogue_delta in dialogue_stream.feed(content):
            if not dialogue_delta:
                continue
            if not ttft_recorded:
                performance.record(
                    "llm.role_turn.ttft",
                    (perf_counter() - request_started_at) * 1000,
                )
                ttft_recorded = True
            on_dialogue_delta(dialogue_delta)
    _record_provider_usage(usage, task_name="role_turn")
    return "".join(raw_parts), dialogue_stream.authoritative_dialogue


def _finalize_role_turn_result(result, streamed_dialogue: str | None):
    result = _replace_unpaired_surrogates(result)
    if streamed_dialogue is not None and isinstance(result, dict):
        result = dict(result)
        result["dialogue"] = streamed_dialogue
    return result


# =========================
# OpenAI Client（懒加载单例）
# =========================
_client = None
_light_client = None
_light_client_signature = None
_response_format_unsupported: set[tuple[str, str]] = set()


def _metric_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "unknown"))[:80]


def _record_llm_call(*, kind: str, task_name: str, model: str) -> None:
    task = _metric_segment(task_name)
    model_name = _metric_segment(model)
    performance.increment("llm.calls.total")
    performance.increment(f"llm.calls.{kind}")
    performance.increment(f"llm.calls.task.{task}")
    performance.increment(f"llm.calls.model.{model_name}")
    performance.increment(f"llm.calls.task_model.{task}.{model_name}")


def _usage_value(usage, name: str) -> int | None:
    if usage is None:
        return None
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_provider_usage(usage, *, task_name: str) -> None:
    task = _metric_segment(task_name)
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _usage_value(usage, field)
        if value is not None:
            performance.observe(f"llm.tokens.{field}", value)
            performance.observe(f"llm.tokens.{task}.{field}", value)


def _has_dedicated_light_client() -> bool:
    return bool(
        configs.llm_light_base_url
        and configs.llm_light_api_key.get_secret_value()
    )


def _resolve_http_proxy(base_url: str) -> str | None:
    """Resolve one HTTP proxy without letting an unsupported ALL_PROXY win."""
    parsed = urlsplit(base_url)
    if not parsed.hostname or proxy_bypass(parsed.hostname):
        return None

    proxies = getproxies()
    proxy_url = proxies.get(parsed.scheme.lower()) or proxies.get("all")
    if not proxy_url:
        return None

    proxy_scheme = urlsplit(proxy_url).scheme.lower()
    if proxy_scheme not in {"http", "https"}:
        logger.warning("Ignoring unsupported LLM proxy scheme: %s", proxy_scheme or "unknown")
        return None
    return proxy_url


def _build_http_client(base_url: str):
    proxy_url = _resolve_http_proxy(base_url)
    kwargs = {"trust_env": False}
    if proxy_url:
        proxy_parameter = (
            "proxy"
            if "proxy" in inspect.signature(httpx.Client).parameters
            else "proxies"
        )
        kwargs[proxy_parameter] = proxy_url
    return DefaultHttpxClient(**kwargs)


def _create_openai_client(
    base_url: str,
    api_key: str,
    *,
    timeout: float,
):
    kwargs = {
        "base_url": base_url,
        "api_key": api_key,
        "http_client": _build_http_client(base_url),
    }
    parameters = inspect.signature(OpenAI).parameters
    if "timeout" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        kwargs["timeout"] = timeout
    if "max_retries" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        kwargs["max_retries"] = 0
    return OpenAI(**kwargs)

def _get_client():
    global _client
    if _client is None:
        _client = _create_openai_client(
            configs.llm_base_url,
            configs.llm_api_key.get_secret_value(),
            timeout=configs.llm_timeout_seconds,
        )
    return _client


def _get_light_client():
    """返回轻量任务专用 client；未完整配置时回退主 client。"""
    global _light_client, _light_client_signature
    light_api_key = configs.llm_light_api_key.get_secret_value()
    if configs.llm_light_base_url and light_api_key:
        signature = (
            configs.llm_light_base_url,
            light_api_key,
            _resolve_http_proxy(configs.llm_light_base_url),
            configs.llm_light_timeout_seconds,
        )
        if _light_client is None or _light_client_signature != signature:
            _light_client = _create_openai_client(
                configs.llm_light_base_url,
                light_api_key,
                timeout=configs.llm_light_timeout_seconds,
            )
            _light_client_signature = signature
            logger.info("Light task client initialized: %s", configs.llm_light_base_url)
        return _light_client

    logger.warning("Light task client is not fully configured; using main LLM client")
    return _get_client()

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


def _emit_debug(debug_sink: DebugSink | None, title: str, payload) -> None:
    if debug_sink is None:
        return
    debug_sink(
        "[LLM DEBUG] "
        + title
        + "\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )
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


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, httpx.TransportError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _retry_call(fn, *args, max_attempts: int = _MAX_RETRIES, **kwargs):
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if not _is_retryable_error(e) or attempt >= max_attempts - 1:
                raise
            if attempt < max_attempts - 1:
                performance.increment("llm.retry")
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM重试 %d/%d (%.1fs后): %s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    e,
                )
                _time.sleep(delay)
    raise last_err


# =========================
# 主 Role 调用函数
# =========================
def call_role_turn(
    system_prompt: str,
    history: list[dict],
    model: str | None = None,
    debug: bool = False,
    debug_sink: DebugSink | None = None,
    on_dialogue_delta: Callable[[str], None] | None = None,
) -> dict:
    """
    调用 LLM 生成 Role 一轮对话

    两层容错：
    1. 正常 JSON 输出解析
    2. 本地 JSON-ish / 文本兜底返回
    """
    
    model = model or configs.llm_model
    task_name = "role_turn"
    messages = [{"role": "system", "content": system_prompt}] + history
    response_format_key = (configs.llm_base_url, model)
    supports_response_format = response_format_key not in _response_format_unsupported
    request_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": configs.max_output_tokens,
        "temperature": 0.8,
    }
    if supports_response_format:
        request_payload["response_format"] = {"type": "json_object"}
    else:
        performance.increment("llm.calls_avoided.response_format_probe")
    if on_dialogue_delta is not None:
        request_payload["stream"] = True
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages)
    performance.observe("llm.prompt_chars", prompt_chars)
    performance.observe("llm.prompt_chars.role_turn", prompt_chars)
    if debug:
        _emit_debug(debug_sink, "role_turn.request", request_payload)
    
    # =========================
    # 1. 主请求
    # =========================
    streamed_dialogue = None
    response_format_unsupported = False
    response_format_name = "json_object" if supports_response_format else "none"
    with tracing.start_span("llm.role_turn", **{"llm.model": model, "llm.response_format": response_format_name}):
        with performance.measure("llm.role_turn"):
            request_started_at = perf_counter()
            _record_llm_call(kind="role", task_name=task_name, model=model)
            try:
                response = _retry_call(
                    _get_client().chat.completions.create,
                    **request_payload,
                )
            except BadRequestError:
                performance.increment("llm.calls.failed")
                if supports_response_format:
                    response_format_unsupported = True
                    _response_format_unsupported.add(response_format_key)
                else:
                    raise
            except Exception:
                performance.increment("llm.calls.failed")
                raise
            else:
                performance.increment("llm.calls.succeeded")
                if on_dialogue_delta is not None:
                    raw_text, streamed_dialogue = _consume_role_stream(
                        response,
                        on_dialogue_delta,
                        request_started_at,
                    )

    if response_format_unsupported:
        # 某些厂商不支持 response_format
        logger.warning("模型不支持 response_format，已降级为普通调用")
        performance.increment("llm.response_format_fallback")
        fallback_request = dict(request_payload)
        fallback_request.pop("response_format", None)
        if debug:
            _emit_debug(debug_sink, "role_turn.request_without_response_format", fallback_request)

        with tracing.start_span("llm.role_turn", **{"llm.model": model, "llm.response_format": "none"}):
            with performance.measure("llm.role_turn"):
                request_started_at = perf_counter()
                _record_llm_call(kind="role", task_name=task_name, model=model)
                try:
                    response = _retry_call(
                        _get_client().chat.completions.create,
                        **fallback_request,
                    )
                except Exception:
                    performance.increment("llm.calls.failed")
                    raise
                performance.increment("llm.calls.succeeded")
                if on_dialogue_delta is not None:
                    raw_text, streamed_dialogue = _consume_role_stream(
                        response,
                        on_dialogue_delta,
                        request_started_at,
                    )
    
    if on_dialogue_delta is None:
        raw_text = response.choices[0].message.content or ""
        _record_provider_usage(getattr(response, "usage", None), task_name=task_name)
    performance.observe("llm.output_chars", len(raw_text))
    performance.observe("llm.output_chars.role_turn", len(raw_text))
    if debug:
        _emit_debug(debug_sink, "role_turn.raw_response", {"content": raw_text})
    
    # =========================
    # 2. JSON 解析
    # =========================
    result = _extract_json(raw_text)
    if result is not None:
        result = _finalize_role_turn_result(result, streamed_dialogue)
        if debug:
            _emit_debug(debug_sink, "role_turn.parsed_response", result)
        return result
    
    # =========================
    # 3. 本地兜底返回
    # =========================
    logger.warning("LLM JSON 解析失败，使用本地兜底")
    performance.increment("llm.calls_avoided.json_repair")
    performance.increment("llm.local_fallback")
    result = _finalize_role_turn_result(
        _plain_text_fallback(raw_text),
        streamed_dialogue,
    )
    if debug:
        _emit_debug(debug_sink, "role_turn.fallback_response", result)
    return result

# =========================
# 轻量任务模型（记忆/摘要等）
# =========================
def call_light_task(
    prompt: str,
    allow_reasoning_fallback: bool = True,
    raise_on_error: bool = False,
    task_name: str = "light_task",
    max_tokens: int | None = None,
    max_attempts: int = 2,
) -> str:
    """
    使用轻量模型处理辅助任务（低成本）
    """
    
    model = configs.light_model
    task = _metric_segment(task_name)
    output_limit = max_tokens or configs.light_task_max_output_tokens
    prompt_chars = len(prompt)
    logger.debug("Calling light model: %s, task=%s", model, task_name)
    performance.observe("llm.prompt_chars", prompt_chars)
    performance.observe(f"llm.prompt_chars.{task}", prompt_chars)
    if not _has_dedicated_light_client():
        performance.increment("llm.light.fallback_to_main")
    
    try:
        with tracing.start_span(
            "llm.light_task",
            **{"llm.model": model, "llm.task": task_name},
        ):
            with performance.measure("llm.light_task"):
                _record_llm_call(kind="light", task_name=task_name, model=model)
                try:
                    response = _retry_call(
                        _get_light_client().chat.completions.create,
                        max_attempts=max_attempts,
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=output_limit,
                        temperature=0.3,
                    )
                except Exception:
                    performance.increment("llm.calls.failed")
                    raise
        performance.increment("llm.calls.succeeded")
        _record_provider_usage(getattr(response, "usage", None), task_name=task_name)
        
        if not response.choices:
            logger.warning("No choices in LLM response")
            return ""
        
        message = response.choices[0].message
        
        # 优先使用 content。推理内容通常不是最终答案，只在调用方允许时兜底使用。
        content = message.content
        
        if not content or content.strip() == "":
            if allow_reasoning_fallback and hasattr(message, 'reasoning_content') and message.reasoning_content:
                logger.debug("Using reasoning_content instead of content")
                content = message.reasoning_content
            else:
                logger.warning("Light task final content is empty")
                return ""
        
        result = content.strip()
        performance.observe("llm.output_chars", len(result))
        performance.observe(f"llm.output_chars.{task}", len(result))
        logger.debug(f"Light task completed, result length: {len(result)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Exception in call_light_task: {e}")
        if raise_on_error:
            raise
        return ""
