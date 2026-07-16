"""
轻量性能采样器。

用于开发者端点查看 LLM 调用、记忆检索等关键路径耗时分布。
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
from typing import Any


_MAX_SAMPLES = 200
_duration_samples: dict[str, deque[float]] = defaultdict(
    lambda: deque(maxlen=_MAX_SAMPLES)
)
_observation_samples: dict[str, deque[float]] = defaultdict(
    lambda: deque(maxlen=_MAX_SAMPLES)
)
_counters: Counter[str] = Counter()
_lock = Lock()


def record(metric: str, duration_ms: float) -> None:
    with _lock:
        _duration_samples[metric].append(float(duration_ms))


def increment(metric: str, amount: int = 1) -> None:
    with _lock:
        _counters[metric] += int(amount)


def observe(metric: str, value: float) -> None:
    with _lock:
        _observation_samples[metric].append(float(value))


def sample_window() -> int:
    return _MAX_SAMPLES


@contextmanager
def measure(metric: str):
    started_at = perf_counter()
    try:
        yield
    finally:
        record(metric, (perf_counter() - started_at) * 1000)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = int(round((len(values) - 1) * percentile))
    return values[index]


def _duration_distribution(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "avg_ms": round(sum(values) / len(values), 2),
        "min_ms": round(values[0], 2),
        "p50_ms": round(_percentile(values, 0.50), 2),
        "p95_ms": round(_percentile(values, 0.95), 2),
        "max_ms": round(values[-1], 2),
    }


def _observation_distribution(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 2),
        "min": round(values[0], 2),
        "p50": round(_percentile(values, 0.50), 2),
        "p95": round(_percentile(values, 0.95), 2),
        "max": round(values[-1], 2),
    }


def snapshot() -> dict[str, Any]:
    with _lock:
        durations = {
            metric: _duration_distribution(sorted(values))
            for metric, values in _duration_samples.items()
            if values
        }
        observations = {
            metric: _observation_distribution(sorted(values))
            for metric, values in _observation_samples.items()
            if values
        }
        counters = dict(_counters)

    return {
        "durations": durations,
        "counters": counters,
        "observations": observations,
    }


def reset() -> None:
    with _lock:
        _duration_samples.clear()
        _observation_samples.clear()
        _counters.clear()
