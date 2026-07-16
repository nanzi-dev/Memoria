from types import SimpleNamespace

import pytest


def _stream_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def _stream_client(chunks, calls):
    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return iter(_stream_chunk(chunk) for chunk in chunks)

    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))


def _non_stream_client(content, calls):
    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content),
                    )
                ]
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))


def test_dialogue_json_stream_decodes_split_dialogue_value():
    from memoria.core.llm_client import _DialogueJsonStream

    parser = _DialogueJsonStream()
    emitted = []
    for chunk in [
        '{"action":"wave","dialogue":"你',
        "好，\\n旅",
        '行者","mood":"warm"}',
    ]:
        emitted.extend(parser.feed(chunk))

    assert "".join(emitted) == "你好，\n旅行者"


def test_dialogue_json_stream_decodes_escapes_once_and_ignores_other_fields():
    from memoria.core.llm_client import _DialogueJsonStream

    parser = _DialogueJsonStream()
    emitted = []
    for chunk in [
        '{"before":"ignore","dialog',
        'ue":"她说：\\"向 C:\\\\temp 前进\\"，字',
        '\\u7b26\\u4e32结束","after":"ignore"}',
    ]:
        emitted.extend(parser.feed(chunk))

    assert "".join(emitted) == '她说："向 C:\\temp 前进"，字符串结束'


def test_dialogue_json_stream_waits_for_complete_escape_sequences():
    from memoria.core.llm_client import _DialogueJsonStream

    parser = _DialogueJsonStream()

    assert parser.feed('{"dialogue":"A\\') == ["A"]
    assert parser.feed("nB\\u4") == ["\nB"]
    assert parser.feed('f60C","action":"idle"}') == ["你C"]


def test_dialogue_json_stream_ignores_nested_dialogue_fields():
    from memoria.core.llm_client import _DialogueJsonStream

    parser = _DialogueJsonStream()
    emitted = []
    for chunk in [
        '{"metadata":{"dialogue":"不应流出"},"dial',
        'ogue":"顶层对白","action":"idle"}',
    ]:
        emitted.extend(parser.feed(chunk))

    assert "".join(emitted) == "顶层对白"
    assert parser.authoritative_dialogue == "顶层对白"


def test_call_role_turn_keeps_first_top_level_dialogue_authoritative(monkeypatch):
    from memoria.core import llm_client

    calls = []
    fake_client = _stream_client(
        [
            '{"dialogue":"先发送的对白",',
            '"metadata":{"dialogue":"嵌套值"},',
            '"dialogue":"后续重复值","action":"idle"}',
        ],
        calls,
    )
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    deltas = []

    result = llm_client.call_role_turn(
        "system",
        [{"role": "user", "content": "hello"}],
        on_dialogue_delta=deltas.append,
    )

    assert "".join(deltas) == "先发送的对白"
    assert result["dialogue"] == "先发送的对白"


def test_call_role_turn_replaces_unpaired_surrogates_before_streaming(monkeypatch):
    from memoria.api.streaming import _encode_sse
    from memoria.core import llm_client

    calls = []
    fake_client = _stream_client(
        ['{"dialogue":"安全前缀\\udc00后缀","action":"idle"}'],
        calls,
    )
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    deltas = []

    result = llm_client.call_role_turn(
        "system",
        [{"role": "user", "content": "hello"}],
        on_dialogue_delta=deltas.append,
    )

    assert "".join(deltas) == "安全前缀\ufffd后缀"
    assert result["dialogue"] == "安全前缀\ufffd后缀"
    assert _encode_sse("dialogue_delta", {"delta": result["dialogue"]}).encode(
        "utf-8"
    )


def test_call_role_turn_streams_structured_json_and_returns_final_object(monkeypatch):
    from memoria.core import llm_client, performance

    calls = []
    fake_client = _stream_client(
        [
            '{"action":"wave","dialogue":"你',
            '好","affinity_delta":1}',
        ],
        calls,
    )
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    performance.reset()
    deltas = []

    result = llm_client.call_role_turn(
        "system",
        [{"role": "user", "content": "hello"}],
        on_dialogue_delta=deltas.append,
    )

    assert calls[0]["stream"] is True
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "".join(deltas) == "你好"
    assert result == {
        "action": "wave",
        "dialogue": "你好",
        "affinity_delta": 1,
    }
    metrics = performance.snapshot()
    assert metrics["durations"]["llm.role_turn.ttft"]["count"] == 1
    assert metrics["observations"]["llm.prompt_chars"]["max"] == 11
    assert metrics["observations"]["llm.output_chars"]["max"] == 52


def test_call_role_turn_without_callback_preserves_non_stream_request(monkeypatch):
    from memoria.core import llm_client

    calls = []
    fake_client = _non_stream_client(
        '{"dialogue":"你好","action":"idle","affinity_delta":0}',
        calls,
    )
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    result = llm_client.call_role_turn(
        "system",
        [{"role": "user", "content": "hello"}],
    )

    assert "stream" not in calls[0]
    assert result["dialogue"] == "你好"


def test_call_role_turn_records_repair_and_response_format_fallback(monkeypatch):
    from memoria.core import llm_client, performance

    class UnsupportedResponseFormat(Exception):
        pass

    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise UnsupportedResponseFormat()
            return iter([_stream_chunk("not json")])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(llm_client, "BadRequestError", UnsupportedResponseFormat)
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(
        llm_client,
        "_retry_as_json",
        lambda *args, **kwargs: {
            "dialogue": "repaired",
            "action": "idle",
            "affinity_delta": 0,
        },
    )
    performance.reset()

    result = llm_client.call_role_turn(
        "system",
        [{"role": "user", "content": "hello"}],
        on_dialogue_delta=lambda _delta: None,
    )

    assert result["dialogue"] == "repaired"
    assert calls[0]["stream"] is True
    assert calls[1]["stream"] is True
    assert "response_format" not in calls[1]
    counters = performance.snapshot()["counters"]
    assert counters["llm.response_format_fallback"] == 1
    assert counters["llm.json_repair"] == 1


def test_call_role_turn_does_not_restart_after_stream_has_emitted(monkeypatch):
    from memoria.core import llm_client

    class StreamBadRequest(Exception):
        pass

    calls = []

    class FailingStream:
        def __iter__(self):
            yield _stream_chunk('{"dialogue":"前缀')
            raise StreamBadRequest("stream failed after output")

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return FailingStream()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(llm_client, "BadRequestError", StreamBadRequest)
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    deltas = []

    with pytest.raises(StreamBadRequest, match="stream failed after output"):
        llm_client.call_role_turn(
            "system",
            [{"role": "user", "content": "hello"}],
            on_dialogue_delta=deltas.append,
        )

    assert len(calls) == 1
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert deltas == ["前缀"]


def test_retry_call_records_each_retry(monkeypatch):
    from memoria.core import llm_client, performance

    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return "ok"

    monkeypatch.setattr(llm_client, "_is_retryable_error", lambda _exc: True)
    monkeypatch.setattr(llm_client._time, "sleep", lambda _delay: None)
    performance.reset()

    assert llm_client._retry_call(flaky) == "ok"
    assert performance.snapshot()["counters"]["llm.retry"] == 2


def test_create_openai_client_uses_configured_timeout_and_single_retry_layer(
    monkeypatch,
):
    from memoria.core import llm_client

    created = {}
    http_client = object()

    class FakeOpenAI:
        def __init__(
            self,
            base_url,
            api_key,
            http_client,
            timeout,
            max_retries,
        ):
            created.update(
                {
                    "base_url": base_url,
                    "api_key": api_key,
                    "http_client": http_client,
                    "timeout": timeout,
                    "max_retries": max_retries,
                }
            )

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client, "_build_http_client", lambda _base_url: http_client)
    monkeypatch.setattr(llm_client.configs, "llm_timeout_seconds", 12.5)

    client = llm_client._create_openai_client("https://llm.test/v1", "secret")

    assert isinstance(client, FakeOpenAI)
    assert created["timeout"] == 12.5
    assert created["max_retries"] == 0


def test_call_light_task_uses_configured_output_limit(monkeypatch):
    from memoria.core import llm_client

    called = {}

    class FakeCompletions:
        def create(self, **kwargs):
            called.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="summary"),
                    )
                ]
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(llm_client, "_get_light_client", lambda: fake_client)
    monkeypatch.setattr(
        llm_client,
        "_retry_call",
        lambda fn, *args, **kwargs: fn(*args, **kwargs),
    )
    monkeypatch.setattr(llm_client.configs, "light_task_max_output_tokens", 123)

    assert llm_client.call_light_task("summarize") == "summary"
    assert called["max_tokens"] == 123
