"""
OpenTelemetry 可选追踪封装。

未安装 opentelemetry 时保持无副作用；安装并配置 SDK/exporter 后会产生 span。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Any


try:
    from opentelemetry import trace

    _tracer = trace.get_tracer("memoria")
except Exception:
    _tracer = None


@contextmanager
def start_span(name: str, **attributes: Any):
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def set_span_attributes(span, **attributes: Any) -> None:
    if span is None:
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def disabled_span():
    return nullcontext(None)
