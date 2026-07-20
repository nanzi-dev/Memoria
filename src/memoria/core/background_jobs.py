"""Persistent background-job worker primitives."""

from __future__ import annotations

from datetime import datetime
import logging
import math
import uuid
from typing import Any, Callable

from memoria.core.memory_extractor import (
    extract_player_memory,
    record_generated_memory_claim,
)
from memoria.db import repository

logger = logging.getLogger(__name__)

BackgroundJobHandler = Callable[[dict[str, Any]], Any]
SUPPORTED_CHECKPOINT_JOB_TYPES = frozenset(
    {
        "single_checkpoint_memory",
        "group_checkpoint_memory",
    }
)
_LLM_MAX_ATTEMPTS = 1
_LLM_RETRY_BACKOFF_SECONDS = 0
_CHECKPOINT_LEASE_MARGIN_SECONDS = 15


def checkpoint_memory_lease_seconds(llm_timeout_seconds: float) -> int:
    """Cover all LLM attempts, retry backoff, and a completion margin."""
    retry_budget = (
        max(0.0, float(llm_timeout_seconds)) * _LLM_MAX_ATTEMPTS
        + _LLM_RETRY_BACKOFF_SECONDS
        + _CHECKPOINT_LEASE_MARGIN_SECONDS
    )
    return max(1, math.ceil(retry_budget))


class BackgroundJobWorker:
    """Claim and dispatch persistent jobs through explicitly registered handlers."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        retry_delay_seconds: float = 5,
        max_attempts: int = 3,
        poll_interval_seconds: float = 1,
    ) -> None:
        self.worker_id = worker_id or f"background-worker:{uuid.uuid4().hex}"
        self.lease_seconds = max(1, int(lease_seconds))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._handlers: dict[str, BackgroundJobHandler] = {}

    def register_handler(
        self,
        job_type: str,
        handler: BackgroundJobHandler,
    ) -> None:
        if not job_type:
            raise ValueError("job_type is required")
        if not callable(handler):
            raise TypeError("background job handler must be callable")
        self._handlers[job_type] = handler

    def run_once(self, *, now: datetime | str | None = None) -> bool:
        """Process at most one due job; return whether a job was claimed."""
        job = repository.claim_background_job(
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
            now=now,
        )
        if job is None:
            return False

        try:
            handler = self._handlers.get(job["job_type"])
            if handler is None:
                raise LookupError(
                    f"no background job handler registered for {job['job_type']}"
                )
            handler(job["payload"])
        except Exception as exc:
            recorded = repository.record_background_job_failure(
                job["job_id"],
                lease_owner=self.worker_id,
                error=str(exc),
                max_attempts=self.max_attempts,
                retry_delay_seconds=self.retry_delay_seconds,
                now=now,
            )
            if recorded is None:
                logger.warning(
                    "Background job lease was lost while recording failure: %s",
                    job["job_id"],
                )
            else:
                logger.warning(
                    "Background job %s attempt %s ended as %s: %s",
                    job["job_id"],
                    job["attempts"],
                    recorded["status"],
                    exc,
                )
            return True

        if not repository.complete_background_job(
            job["job_id"],
            lease_owner=self.worker_id,
            now=now,
        ):
            logger.warning(
                "Background job lease was lost before completion: %s",
                job["job_id"],
            )
        return True

    def run(self, stop_event) -> None:
        """Poll until a threading-compatible stop event is signalled."""
        while not stop_event.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.error("Background job worker iteration failed", exc_info=True)
                processed = False
            if not processed:
                stop_event.wait(self.poll_interval_seconds)


def _process_checkpoint_memory(payload: dict[str, Any]) -> None:
    history = payload["history"]
    fact_text = extract_player_memory(
        history,
        raise_on_error=True,
        max_attempts=1,
    )
    if not fact_text:
        return
    session_id = payload["session_id"]
    record_generated_memory_claim(
        owner_user_id=payload["owner_user_id"],
        scope_type=payload["scope_type"],
        scope_id=payload["scope_id"],
        fact_text=fact_text,
        source_ids=[f"session:{session_id}"],
        provenance={
            "memory_kind": "player_fact",
            "session_id": session_id,
        },
    )


def register_checkpoint_memory_handlers(worker: BackgroundJobWorker) -> None:
    """Attach durable checkpoint-memory handlers to a worker."""
    for job_type in SUPPORTED_CHECKPOINT_JOB_TYPES:
        worker.register_handler(job_type, _process_checkpoint_memory)
