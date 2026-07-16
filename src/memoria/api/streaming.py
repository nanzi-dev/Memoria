"""SSE bridge for synchronous dialogue workers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from collections.abc import Callable
from typing import Any

from fastapi.responses import StreamingResponse


EventSink = Callable[[str, dict[str, Any]], None]
SyncWorker = Callable[[EventSink], Any]
logger = logging.getLogger(__name__)


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


STREAM_MAX_WORKERS = _positive_int_env("MEMORIA_STREAM_MAX_WORKERS", 16)
STREAM_EVENT_QUEUE_SIZE = _positive_int_env(
    "MEMORIA_STREAM_EVENT_QUEUE_SIZE",
    256,
)
_stream_slots = threading.BoundedSemaphore(STREAM_MAX_WORKERS)


class StreamDisconnected(RuntimeError):
    """Raised inside a worker when its response consumer has disconnected."""


def _encode_sse(event_type: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n"


def create_sse_response(
    worker: SyncWorker,
    *,
    started_data: dict[str, Any],
    completion_mapper: Callable[[Any], Any] | None = None,
) -> StreamingResponse:
    """Run a synchronous worker in a thread and stream its events as SSE."""

    async def event_stream():
        if not _stream_slots.acquire(blocking=False):
            yield _encode_sse(
                "error",
                {
                    "detail": "流式对话请求过多，请稍后重试",
                    "error_type": "StreamCapacityError",
                },
            )
            return

        loop = asyncio.get_running_loop()
        event_queue: queue.Queue[
            tuple[str, dict[str, Any]] | None
        ] = queue.Queue(maxsize=STREAM_EVENT_QUEUE_SIZE)
        disconnected = threading.Event()
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)

        def enqueue(item: tuple[str, dict[str, Any]] | None) -> None:
            while True:
                if disconnected.is_set():
                    raise StreamDisconnected()
                try:
                    event_queue.put(item, timeout=0.1)
                    break
                except queue.Full:
                    continue
            try:
                os.write(write_fd, b"\0")
            except OSError:
                # A full pipe is already readable; a closed pipe means the
                # response ended before the synchronous worker finished.
                return

        async def wait_for_events() -> None:
            ready = loop.create_future()

            def mark_ready() -> None:
                if not ready.done():
                    ready.set_result(None)

            try:
                loop.add_reader(read_fd, mark_ready)
            except (AttributeError, NotImplementedError):
                await asyncio.sleep(0.005)
                return
            try:
                await ready
            finally:
                loop.remove_reader(read_fd)

            try:
                while os.read(read_fd, 4096):
                    pass
            except BlockingIOError:
                pass

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            enqueue((event_type, payload))

        def run_worker() -> None:
            try:
                sink("turn_started", started_data)
                result = worker(sink)
                if completion_mapper is not None:
                    result = completion_mapper(result)
                sink("turn_completed", {"response": result})
            except StreamDisconnected:
                return
            except Exception as exc:
                logger.exception("Dialogue stream worker failed")
                if not disconnected.is_set():
                    sink(
                        "error",
                        {
                            "detail": "流式对话生成失败，请稍后重试",
                            "error_type": type(exc).__name__,
                        },
                    )
            finally:
                try:
                    if not disconnected.is_set():
                        enqueue(None)
                finally:
                    try:
                        os.close(write_fd)
                    finally:
                        _stream_slots.release()

        worker_thread = threading.Thread(
            target=run_worker,
            name="memoria-dialogue-stream",
            daemon=True,
        )
        worker_thread.start()
        try:
            while True:
                if event_queue.empty():
                    await wait_for_events()
                while True:
                    try:
                        item = event_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is None:
                        return
                    event_type, payload = item
                    yield _encode_sse(event_type, payload)
        finally:
            disconnected.set()
            os.close(read_fd)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
