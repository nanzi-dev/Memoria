"""
轻量性能采样器。

用于开发者端点查看 LLM 调用、记忆检索等关键路径耗时分布。
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from time import perf_counter
from typing import Any


_MAX_SAMPLES = 200
_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))


def record(metric: str, duration_ms: float) -> None:
    _samples[metric].append(float(duration_ms))


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


def snapshot() -> dict[str, Any]:
    result = {}
    for metric, values_deque in _samples.items():
        values = sorted(values_deque)
        if not values:
            continue
        result[metric] = {
            "count": len(values),
            "avg_ms": round(sum(values) / len(values), 2),
            "min_ms": round(values[0], 2),
            "p50_ms": round(_percentile(values, 0.50), 2),
            "p95_ms": round(_percentile(values, 0.95), 2),
            "max_ms": round(values[-1], 2),
        }
    return result


def reset() -> None:
    _samples.clear()
