import asyncio
import json
import os
import queue
import sys
import threading
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


async def _response_text(response) -> str:
    async def consume() -> str:
        chunks = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8")
            chunks.append(chunk)
        return "".join(chunks)

    return await asyncio.wait_for(consume(), timeout=1)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = frame.splitlines()
        event_type = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((event_type, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_sse_bridge_wakes_consumer_for_later_worker_event():
    from memoria.api.streaming import create_sse_response

    release_worker = threading.Event()

    def worker(event_sink):
        release_worker.wait()
        event_sink("stage", {"name": "generation"})
        return {"dialogue": "done"}

    response = create_sse_response(
        worker,
        started_data={"request_id": "req-race"},
    )
    iterator = response.body_iterator.__aiter__()

    try:
        first = await asyncio.wait_for(iterator.__anext__(), timeout=1)
        asyncio.get_running_loop().call_soon(release_worker.set)
        started_at = asyncio.get_running_loop().time()
        second = await asyncio.wait_for(iterator.__anext__(), timeout=1)
        elapsed = asyncio.get_running_loop().time() - started_at
    finally:
        release_worker.set()
        await iterator.aclose()

    assert first.startswith("event: turn_started\n")
    assert second.startswith("event: stage\n")
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_sse_bridge_keeps_write_fd_owned_by_worker_after_client_disconnect(
    monkeypatch,
):
    from memoria.api import streaming

    release_worker = threading.Event()
    worker_done = threading.Event()
    pipe_fds = {}
    closed_fds = []
    real_pipe = os.pipe
    real_close = os.close

    def tracked_pipe():
        read_fd, write_fd = real_pipe()
        pipe_fds.update(read=read_fd, write=write_fd)
        return read_fd, write_fd

    def tracked_close(fd):
        closed_fds.append(fd)
        real_close(fd)

    monkeypatch.setattr(streaming.os, "pipe", tracked_pipe)
    monkeypatch.setattr(streaming.os, "close", tracked_close)

    def worker(_event_sink):
        try:
            release_worker.wait()
            return {"dialogue": "done"}
        finally:
            worker_done.set()

    response = streaming.create_sse_response(
        worker,
        started_data={"request_id": "req-disconnect"},
    )
    iterator = response.body_iterator.__aiter__()

    try:
        await asyncio.wait_for(iterator.__anext__(), timeout=1)
        await iterator.aclose()
        closed_before_worker_exit = list(closed_fds)
    finally:
        release_worker.set()
        assert await asyncio.to_thread(worker_done.wait, 1)
        await asyncio.sleep(0.01)

    assert closed_before_worker_exit == [pipe_fds["read"]]
    assert closed_fds == [pipe_fds["read"], pipe_fds["write"]]


@pytest.mark.asyncio
async def test_sse_bridge_closes_write_fd_when_consumer_disconnects_before_first_event(
    monkeypatch,
):
    from memoria.api import streaming

    pipe_fds = {}
    closed_fds = []
    deferred_target = {}
    thread_started = asyncio.Event()
    real_pipe = os.pipe
    real_close = os.close

    def tracked_pipe():
        read_fd, write_fd = real_pipe()
        pipe_fds.update(read=read_fd, write=write_fd)
        return read_fd, write_fd

    def tracked_close(fd):
        closed_fds.append(fd)
        real_close(fd)

    class DeferredThread:
        def __init__(self, *, target, name, daemon):
            deferred_target["run"] = target

        def start(self):
            thread_started.set()

    monkeypatch.setattr(streaming.os, "pipe", tracked_pipe)
    monkeypatch.setattr(streaming.os, "close", tracked_close)
    monkeypatch.setattr(streaming.threading, "Thread", DeferredThread)

    response = streaming.create_sse_response(
        lambda _event_sink: {"dialogue": "done"},
        started_data={"request_id": "req-before-first-event"},
    )
    iterator = response.body_iterator.__aiter__()
    next_event = asyncio.create_task(iterator.__anext__())

    await asyncio.wait_for(thread_started.wait(), timeout=1)
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event
    await iterator.aclose()

    try:
        deferred_target["run"]()
    except streaming.StreamDisconnected:
        pass

    assert closed_fds == [pipe_fds["read"], pipe_fds["write"]]


@pytest.mark.asyncio
async def test_sse_bridge_stops_worker_on_next_event_after_disconnect():
    from memoria.api import streaming

    release_worker = threading.Event()
    worker_cancelled = threading.Event()
    worker_done = threading.Event()

    def worker(event_sink):
        try:
            release_worker.wait()
            event_sink("dialogue_delta", {"delta": "late"})
            pytest.fail("disconnected stream must reject later events")
        except streaming.StreamDisconnected:
            worker_cancelled.set()
            raise
        finally:
            worker_done.set()

    response = streaming.create_sse_response(
        worker,
        started_data={"request_id": "req-cancel"},
    )
    iterator = response.body_iterator.__aiter__()

    await asyncio.wait_for(iterator.__anext__(), timeout=1)
    await iterator.aclose()
    release_worker.set()

    assert await asyncio.to_thread(worker_done.wait, 1)
    assert worker_cancelled.is_set()


@pytest.mark.asyncio
async def test_sse_bridge_rejects_requests_beyond_global_worker_capacity(monkeypatch):
    from memoria.api import streaming

    release_worker = threading.Event()
    worker_done = threading.Event()
    monkeypatch.setattr(streaming, "_stream_slots", threading.BoundedSemaphore(1))

    def blocking_worker(_event_sink):
        try:
            release_worker.wait()
            return {"dialogue": "done"}
        finally:
            worker_done.set()

    first = streaming.create_sse_response(
        blocking_worker,
        started_data={"request_id": "req-capacity-1"},
    )
    first_iterator = first.body_iterator.__aiter__()
    await asyncio.wait_for(first_iterator.__anext__(), timeout=1)

    second = streaming.create_sse_response(
        lambda _event_sink: {"dialogue": "must-not-run"},
        started_data={"request_id": "req-capacity-2"},
    )
    second_events = _parse_sse(await _response_text(second))

    try:
        assert [event_type for event_type, _ in second_events] == ["error"]
        assert second_events[0][1]["error_type"] == "StreamCapacityError"
    finally:
        await first_iterator.aclose()
        release_worker.set()
        assert await asyncio.to_thread(worker_done.wait, 1)


@pytest.mark.asyncio
async def test_sse_bridge_uses_a_bounded_event_queue(monkeypatch):
    from memoria.api import streaming

    queue_sizes = []
    real_queue = queue.Queue

    def tracked_queue(maxsize=0):
        queue_sizes.append(maxsize)
        return real_queue(maxsize=maxsize)

    monkeypatch.setattr(streaming.queue, "Queue", tracked_queue)

    response = streaming.create_sse_response(
        lambda event_sink: (
            event_sink("dialogue_delta", {"delta": "ok"})
            or {"dialogue": "ok"}
        ),
        started_data={"request_id": "req-bounded-queue"},
    )
    await _response_text(response)

    assert queue_sizes == [streaming.STREAM_EVENT_QUEUE_SIZE]
    assert queue_sizes[0] > 0


@pytest.mark.asyncio
async def test_dialogue_stream_emits_incremental_events_and_final_response(monkeypatch):
    from memoria.api import dialogue

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "character_id": "char-1",
            "player_id": "player-1",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        dialogue.repository,
        "is_character_card_active",
        lambda owner_user_id, character_id: True,
    )

    def fake_turn(session_id, player_message, request_id=None, event_sink=None):
        event_sink("stage", {"name": "llm"})
        event_sink(
            "character_started",
            {"stream_id": f"{request_id}:0", "character_id": "char-1"},
        )
        event_sink(
            "dialogue_delta",
            {"stream_id": f"{request_id}:0", "delta": "你"},
        )
        event_sink(
            "dialogue_delta",
            {"stream_id": f"{request_id}:0", "delta": "好"},
        )
        return {
            "dialogue": "你好",
            "action": "wave",
            "affinity_delta": 1,
            "trust_delta": 0,
            "current_affinity": 1,
            "current_trust": 0,
            "current_mood": "warm",
            "assistant_message_id": 12,
            "user_message_id": 11,
        }

    monkeypatch.setattr(dialogue.orchestrator, "run_dialogue_turn", fake_turn)

    response = await dialogue.dialogue_turn_stream(
        dialogue.DialogueTurnRequest(
            session_id="session-1",
            player_message="你好",
            request_id="req-1",
        ),
        current_user_id="player-1",
    )
    events = _parse_sse(await _response_text(response))

    assert response.media_type == "text/event-stream"
    assert [event_type for event_type, _ in events] == [
        "turn_started",
        "stage",
        "character_started",
        "dialogue_delta",
        "dialogue_delta",
        "turn_completed",
    ]
    assert events[3][1]["delta"] == "你"
    assert events[-1][1]["response"]["dialogue"] == "你好"
    assert events[-1][1]["response"]["assistant_message_id"] == 12


@pytest.mark.asyncio
async def test_dialogue_stream_converts_worker_exception_to_error_event(monkeypatch):
    from memoria.api import dialogue

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "character_id": "char-1",
            "player_id": "player-1",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        dialogue.repository,
        "is_character_card_active",
        lambda owner_user_id, character_id: True,
    )

    def fake_turn(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(dialogue.orchestrator, "run_dialogue_turn", fake_turn)

    response = await dialogue.dialogue_turn_stream(
        dialogue.DialogueTurnRequest(
            session_id="session-1",
            player_message="你好",
            request_id="req-2",
        ),
        current_user_id="player-1",
    )
    events = _parse_sse(await _response_text(response))

    assert [event_type for event_type, _ in events] == [
        "turn_started",
        "error",
    ]
    assert events[-1][1]["error_type"] == "RuntimeError"
    assert "provider unavailable" not in events[-1][1]["detail"]


@pytest.mark.asyncio
async def test_multi_dialogue_stream_returns_authoritative_group_shape(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "player_id": "player-1",
            "status": "active",
            "is_multi_character": True,
        },
    )
    monkeypatch.setattr(
        multi_dialogue,
        "_require_active_session_participants",
        lambda session_id: [],
    )

    def fake_turn(
        session_id,
        player_message,
        discussion_mode=True,
        max_responses=None,
        request_id=None,
        event_sink=None,
    ):
        event_sink(
            "character_started",
            {
                "stream_id": f"{request_id}:0",
                "character_id": "char-1",
                "character_name": "角色一",
            },
        )
        event_sink(
            "dialogue_delta",
            {"stream_id": f"{request_id}:0", "delta": "收到"},
        )
        return [
            {
                "message_id": 22,
                "character_id": "char-1",
                "character_name": "角色一",
                "dialogue": "收到",
                "action": "nod",
            }
        ]

    monkeypatch.setattr(
        multi_dialogue,
        "process_multi_character_turn",
        fake_turn,
    )

    response = await multi_dialogue.multi_dialogue_turn_stream(
        multi_dialogue.MultiDialogueTurnRequest(
            session_id="session-1",
            player_message="行动",
            discussion_mode=True,
            request_id="req-group",
        ),
        current_user_id="player-1",
    )
    events = _parse_sse(await _response_text(response))

    assert [event_type for event_type, _ in events] == [
        "turn_started",
        "character_started",
        "dialogue_delta",
        "turn_completed",
    ]
    final_response = events[-1][1]["response"]
    assert final_response["discussion_mode"] is True
    assert final_response["total_speakers"] == 1
    assert final_response["responses"][0]["message_id"] == 22
