"""Operational telemetry port with OpenTelemetry and recorded test adapters."""

from __future__ import annotations

import uuid
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import ContextManager, Iterator, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


class TelemetryOperation(Protocol):
    def set_attribute(self, name: str, value: str | int | float | bool) -> None: ...


class RecruitmentTelemetry(Protocol):
    def operation(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> ContextManager[TelemetryOperation]: ...


class OpenTelemetryOperation:
    def __init__(self, span):
        self._span = span

    def set_attribute(self, name: str, value: str | int | float | bool) -> None:
        self._span.set_attribute(f"recruitment_team.{name}", value)


class OpenTelemetryRecorder:
    """Production metadata-only adapter using the configured global provider."""

    @contextmanager
    def operation(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[OpenTelemetryOperation]:
        tracer = trace.get_tracer("jobhunter.recruitment_team")
        with tracer.start_as_current_span(
            f"recruitment_team.{name}",
            attributes={f"recruitment_team.{key}": value for key, value in (attributes or {}).items()},
        ) as span:
            try:
                yield OpenTelemetryOperation(span)
            except BaseException as error:
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise


@dataclass
class RecordedSpan:
    span_id: str
    parent_id: str | None
    name: str
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)
    status: str = "running"
    error_type: str | None = None
    duration_ms: float | None = None

    def set_attribute(self, name: str, value: str | int | float | bool) -> None:
        self.attributes[name] = value


class RecordedTelemetry:
    """In-memory adapter for asserting the production operation tree."""

    def __init__(self):
        self.spans: list[RecordedSpan] = []
        self._active: list[RecordedSpan] = []

    @contextmanager
    def operation(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[RecordedSpan]:
        span = RecordedSpan(
            span_id=str(uuid.uuid4()),
            parent_id=self._active[-1].span_id if self._active else None,
            name=name,
            attributes=dict(attributes or {}),
        )
        self.spans.append(span)
        self._active.append(span)
        started_at = time.perf_counter()
        try:
            yield span
        except BaseException as error:
            span.status = "error"
            span.error_type = type(error).__name__
            raise
        else:
            span.status = "success"
        finally:
            span.duration_ms = (time.perf_counter() - started_at) * 1000
            self._active.pop()
