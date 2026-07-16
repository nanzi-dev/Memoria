from datetime import datetime, timedelta, timezone
from threading import Event
import uuid

import pytest

from memoria.core import background_jobs
from memoria.core.background_jobs import (
    BackgroundJobWorker,
    checkpoint_memory_lease_seconds,
    register_checkpoint_memory_handlers,
)
from memoria.db import repository


@pytest.mark.parametrize(
    ("job_type", "identity"),
    [
        ("single_checkpoint_memory", {"session_id": "session-1"}),
        ("group_checkpoint_memory", {"group_thread_id": "thread-1"}),
    ],
)
def test_worker_dispatches_supported_checkpoint_payload_and_completes(
    job_type,
    identity,
):
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    payload = {
        **identity,
        "checkpoint_turn": 5,
        "history": [{"role": "user", "content": "immutable snapshot"}],
    }
    queued = repository.enqueue_background_job(
        job_type=job_type,
        dedupe_key=f"{job_type}:{uuid.uuid4().hex}",
        payload=payload,
        available_at=now,
    )
    seen = []
    worker = BackgroundJobWorker(worker_id="worker-1")
    worker.register_handler(job_type, lambda received: seen.append(received))

    assert worker.run_once(now=now)

    assert seen == [payload]
    completed = repository.get_background_job(queued["job_id"])
    assert completed["status"] == "completed"


def test_worker_retries_transient_failure_without_losing_payload():
    now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
    payload = {
        "session_id": "session-retry",
        "checkpoint_turn": 10,
        "history": [{"role": "assistant", "content": "stable snapshot"}],
    }
    queued = repository.enqueue_background_job(
        job_type="single_checkpoint_memory",
        dedupe_key=f"worker-retry:{uuid.uuid4().hex}",
        payload=payload,
        available_at=now,
    )
    received = []

    def fail(received_payload):
        received.append(received_payload)
        raise RuntimeError("transient extraction failure")

    worker = BackgroundJobWorker(
        worker_id="worker-retry",
        max_attempts=2,
        retry_delay_seconds=30,
    )
    worker.register_handler("single_checkpoint_memory", fail)

    assert worker.run_once(now=now)
    retry = repository.get_background_job(queued["job_id"])
    assert retry["status"] == "retry"
    assert retry["payload"] == payload

    assert worker.run_once(now=now + timedelta(seconds=30))
    failed = repository.get_background_job(queued["job_id"])
    assert failed["status"] == "failed"
    assert received == [payload, payload]


def test_worker_loop_stops_via_event_after_processing():
    stop_event = Event()
    queued = repository.enqueue_background_job(
        job_type="group_checkpoint_memory",
        dedupe_key=f"worker-loop:{uuid.uuid4().hex}",
        payload={"group_thread_id": "thread-loop", "history": []},
    )
    worker = BackgroundJobWorker(worker_id="worker-loop", poll_interval_seconds=0.01)

    def stop_after_handling(payload):
        stop_event.set()

    worker.register_handler("group_checkpoint_memory", stop_after_handling)
    worker.run(stop_event)

    assert stop_event.is_set()
    assert repository.get_background_job(queued["job_id"])["status"] == "completed"


def test_checkpoint_memory_lease_covers_full_llm_retry_budget():
    lease_seconds = checkpoint_memory_lease_seconds(45.0)

    assert lease_seconds >= (45 * 3) + 1 + 2 + 15


def test_checkpoint_memory_provider_failure_retries_job(monkeypatch):
    from memoria.core import memory_extractor

    jobs = [
        {
            "job_id": "job-memory-failure",
            "job_type": "single_checkpoint_memory",
            "payload": {
                "history": [{"role": "user", "content": "记住这件事"}],
                "session_id": "session-1",
                "owner_user_id": "player-1",
                "scope_type": "character",
                "scope_id": "character-1",
            },
            "attempts": 1,
        }
    ]
    failures = []
    monkeypatch.setattr(
        background_jobs.repository,
        "claim_background_job",
        lambda **_kwargs: jobs.pop(0) if jobs else None,
    )
    monkeypatch.setattr(
        background_jobs.repository,
        "record_background_job_failure",
        lambda job_id, **kwargs: failures.append((job_id, kwargs)) or {
            "status": "pending"
        },
    )
    monkeypatch.setattr(
        background_jobs.repository,
        "complete_background_job",
        lambda *_args, **_kwargs: pytest.fail("failed job must not complete"),
    )
    monkeypatch.setattr(
        memory_extractor,
        "call_light_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("provider unavailable")
        ),
    )

    worker = BackgroundJobWorker(worker_id="worker-1")
    register_checkpoint_memory_handlers(worker)

    assert worker.run_once() is True
    assert failures[0][0] == "job-memory-failure"
    assert failures[0][1]["error"] == "provider unavailable"


@pytest.mark.asyncio
async def test_lifespan_configures_safe_memory_lease_and_joins_threads_off_loop(
    monkeypatch,
):
    from memoria import main

    created_workers = []
    joined_threads = []
    offloaded_calls = []

    class FakeWorker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_workers.append(self)

        def run(self, _stop_event):
            return None

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            return None

        def join(self, timeout):
            joined_threads.append((self.name, timeout))

        def is_alive(self):
            return False

    async def idle_scheduler():
        await __import__("asyncio").Event().wait()

    async def fake_to_thread(func, *args):
        offloaded_calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(main.repository, "init_db", lambda: None)
    monkeypatch.setattr(main, "ensure_default_event_templates", lambda: None)
    monkeypatch.setattr(main, "reconcile_event_schedule_due_times", lambda: 0)
    monkeypatch.setattr(main, "run_world_clock_scheduler", idle_scheduler)
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main, "BackgroundJobWorker", FakeWorker)
    monkeypatch.setattr(
        main,
        "register_checkpoint_memory_handlers",
        lambda _worker: None,
    )
    monkeypatch.setattr(main.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(main.configs, "llm_timeout_seconds", 45.0)

    async with main.lifespan(main.app):
        pass

    assert created_workers[0].kwargs["lease_seconds"] == (
        checkpoint_memory_lease_seconds(45.0)
    )
    assert [call[0].__self__.name for call in offloaded_calls] == [
        "memoria-knowledge-document-recovery",
        "memoria-checkpoint-memory-worker",
    ]
    assert joined_threads == [
        ("memoria-knowledge-document-recovery", 5.0),
        ("memoria-checkpoint-memory-worker", 5.0),
    ]


@pytest.mark.parametrize(
    ("job_type", "scope_type", "scope_id"),
    [
        ("single_checkpoint_memory", "character", "char-1"),
        ("group_checkpoint_memory", "group_thread", "thread-1"),
    ],
)
def test_checkpoint_memory_handler_extracts_snapshot_and_records_claim(
    monkeypatch,
    job_type,
    scope_type,
    scope_id,
):
    history = [{"role": "user", "content": "我会带茉莉花茶"}]
    queued = repository.enqueue_background_job(
        job_type=job_type,
        dedupe_key=f"memory-handler:{uuid.uuid4().hex}",
        payload={
            "owner_user_id": "player-1",
            "scope_type": scope_type,
            "scope_id": scope_id,
            "session_id": "session-1",
            "history": history,
        },
    )
    extracted = []
    claims = []
    monkeypatch.setattr(
        background_jobs,
        "extract_player_memory",
        lambda snapshot, **_kwargs: (
            extracted.append(snapshot) or "玩家会带茉莉花茶"
        ),
    )
    monkeypatch.setattr(
        background_jobs,
        "record_generated_memory_claim",
        lambda **kwargs: claims.append(kwargs),
    )
    worker = BackgroundJobWorker(worker_id="memory-worker")
    register_checkpoint_memory_handlers(worker)

    assert worker.run_once()

    assert extracted == [history]
    assert claims == [{
        "owner_user_id": "player-1",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "fact_text": "玩家会带茉莉花茶",
        "source_ids": ["session:session-1"],
        "provenance": {
            "memory_kind": "player_fact",
            "session_id": "session-1",
        },
    }]
    assert repository.get_background_job(queued["job_id"])["status"] == "completed"
