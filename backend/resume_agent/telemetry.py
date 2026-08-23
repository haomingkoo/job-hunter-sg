"""Opt-in, metadata-only OpenTelemetry for the resume-agent workflow."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


_provider = None
TRACE_KEY_HEX_LENGTH = 16


def configure_telemetry():
    """Configure console or OTLP traces from standard OpenTelemetry settings."""
    global _provider
    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "none").strip().lower()
    if exporter_name in {"", "none"} or _provider is not None:
        return _provider

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    provider = TracerProvider(resource=Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "job-hunter-sg"),
    }))
    if exporter_name == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif exporter_name == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        raise ValueError("OTEL_TRACES_EXPORTER must be one of: none, console, otlp")
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def shutdown_telemetry() -> None:
    if _provider is not None:
        _provider.shutdown()


def tracer():
    return trace.get_tracer("jobhunter.resume_agent")


def trace_key(value: str) -> str:
    """Export a stable correlation key without exporting the session identifier."""
    return hashlib.sha256(value.encode()).hexdigest()[:TRACE_KEY_HEX_LENGTH] if value else ""


@contextmanager
def operation(name: str, **attributes):
    with tracer().start_as_current_span(
        f"resume_agent.{name}",
        attributes={f"resume_agent.{key}": value for key, value in attributes.items() if value is not None},
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise


def traced_events(events: Iterator[dict], **attributes) -> Iterator[dict]:
    """Keep the workflow span current only while advancing the underlying iterator."""
    span = tracer().start_span(
        "resume_agent.review",
        attributes={f"resume_agent.{key}": value for key, value in attributes.items() if value is not None},
    )
    try:
        while True:
            with trace.use_span(span, end_on_exit=False):
                try:
                    event = next(events)
                except StopIteration:
                    break
            if event.get("event") == "error":
                span.set_status(Status(StatusCode.ERROR, "stream_error"))
            yield event
    except BaseException as exc:
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        raise
    finally:
        span.end()


def finish_span(otel_span, recorded: dict) -> None:
    if otel_span is None:
        return
    try:
        otel_span.set_attribute("resume_agent.status", str(recorded.get("status") or "unknown"))
        duration = recorded.get("duration_ms")
        if isinstance(duration, int):
            otel_span.set_attribute("resume_agent.duration_ms", duration)
        for key, value in (recorded.get("result") or {}).items():
            if isinstance(value, (bool, int, float, str)):
                otel_span.set_attribute(f"resume_agent.result.{key}", value)
        if recorded.get("status") == "error":
            otel_span.set_status(Status(StatusCode.ERROR))
    finally:
        otel_span.end()
