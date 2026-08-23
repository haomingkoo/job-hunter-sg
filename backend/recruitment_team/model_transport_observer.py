"""Content-free transport-attempt telemetry for recruitment model calls."""

from __future__ import annotations

import atexit
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler

from .telemetry import RecruitmentTelemetry


@dataclass
class _TransportCall:
    attempts: int = 0
    collector: TransportMetricsCollector | None = None
    role: str = "unclassified"
    started_at: float = 0.0
    model_hint: str = ""


_ACTIVE_TRANSPORT_CALL: ContextVar[_TransportCall | None] = ContextVar(
    "recruitment_model_transport_call",
    default=None,
)


class TransportMetricsCollector:
    """Run-local, content-free transport totals suitable for durable metrics."""

    def __init__(self) -> None:
        self._records: list[dict[str, str | int | float]] = []
        self._semantic_attempts: list[dict[str, str | int | float]] = []
        self._lock = threading.Lock()

    def record(
        self,
        *,
        role: str,
        attempts: int,
        outcome: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        model: str = "",
        semantic_attempt: dict[str, str | int | float] | None = None,
    ) -> None:
        with self._lock:
            self._records.append({
                "role": role,
                "attempts": attempts,
                "outcome": outcome,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "model": model,
            })
            if semantic_attempt is not None:
                self._semantic_attempts.append(dict(semantic_attempt))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)
            semantic_attempts = list(self._semantic_attempts)
        by_role: dict[str, dict[str, Any]] = {}
        for record in records:
            role = str(record["role"])
            role_totals = by_role.setdefault(
                role,
                {
                    "call_count": 0,
                    "attempt_count": 0,
                    "retry_count": 0,
                    "error_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_ms": 0.0,
                    "models": [],
                },
            )
            attempts = int(record["attempts"])
            role_totals["call_count"] += 1
            role_totals["attempt_count"] += attempts
            role_totals["retry_count"] += max(0, attempts - 1)
            role_totals["error_count"] += int(record["outcome"] == "error")
            role_totals["input_tokens"] += int(record["input_tokens"])
            role_totals["output_tokens"] += int(record["output_tokens"])
            role_totals["latency_ms"] += float(record["latency_ms"])
            model = str(record["model"])
            if model and model not in role_totals["models"]:
                role_totals["models"].append(model)
        for role_totals in by_role.values():
            role_totals["latency_ms"] = round(float(role_totals["latency_ms"]), 3)
        transport_models = list(dict.fromkeys(
            str(item["model"]) for item in records if str(item["model"])
        ))
        summary: dict[str, Any] = {
            "transport_call_count": len(records),
            "transport_attempt_count": sum(int(item["attempts"]) for item in records),
            "transport_retry_count": sum(max(0, int(item["attempts"]) - 1) for item in records),
            "transport_error_count": sum(item["outcome"] == "error" for item in records),
            "transport_input_tokens": sum(int(item["input_tokens"]) for item in records),
            "transport_output_tokens": sum(int(item["output_tokens"]) for item in records),
            "transport_latency_ms": round(
                sum(float(item["latency_ms"]) for item in records),
                3,
            ),
            "transport_models": transport_models,
            "transport_by_role": by_role,
        }
        if semantic_attempts:
            summary["nested_model_attempts"] = semantic_attempts
        return summary


_ACTIVE_TRANSPORT_METRICS: ContextVar[TransportMetricsCollector | None] = ContextVar(
    "recruitment_model_transport_metrics",
    default=None,
)
_ACTIVE_TRANSPORT_ROLE: ContextVar[str | None] = ContextVar(
    "recruitment_model_transport_role",
    default=None,
)


@contextmanager
def collect_transport_metrics() -> Iterator[TransportMetricsCollector]:
    """Collect safe transport totals for one target-assessment run or resume."""
    collector = TransportMetricsCollector()
    token = _ACTIVE_TRANSPORT_METRICS.set(collector)
    try:
        yield collector
    except BaseException as error:
        # The service boundary persists this content-free summary even when a
        # provider exception escapes before the runner can return a result.
        try:
            setattr(error, "recruitment_transport_metrics", collector.summary())
        except (AttributeError, TypeError):  # pragma: no cover - unusual immutable exception
            pass
        raise
    finally:
        _ACTIVE_TRANSPORT_METRICS.reset(token)


def current_transport_metrics() -> dict[str, Any]:
    collector = _ACTIVE_TRANSPORT_METRICS.get()
    return collector.summary() if collector is not None else {}


@contextmanager
def transport_role(role: str) -> Iterator[None]:
    """Attach a code-owned stage label to model calls made in this context."""
    token = _ACTIVE_TRANSPORT_ROLE.set(role)
    try:
        yield
    finally:
        _ACTIVE_TRANSPORT_ROLE.reset(token)


def observe_transport_request(_request: httpx.Request) -> None:
    """Count one physical request without retaining any request data."""
    active = _ACTIVE_TRANSPORT_CALL.get()
    if active is not None:
        active.attempts += 1


_SHARED_HTTP_CLIENT = httpx.Client(event_hooks={"request": [observe_transport_request]})
atexit.register(_SHARED_HTTP_CLIENT.close)


def observed_http_client() -> httpx.Client:
    """Return the process-owned client used by observed ChatOpenAI models."""
    return _SHARED_HTTP_CLIENT


@contextmanager
def bind_transport_collector(model: Any, collector: TransportMetricsCollector) -> Iterator[None]:
    """Bind a run collector to observers on one run-owned model instance."""
    observers = [
        callback
        for callback in (getattr(model, "callbacks", None) or ())
        if isinstance(callback, ModelTransportObserver)
    ]
    previous: list[TransportMetricsCollector | None] = []
    for observer in observers:
        with observer._lock:
            previous.append(observer._bound_collector)
            observer._bound_collector = collector
    try:
        yield
    finally:
        for observer, prior in zip(observers, previous, strict=True):
            with observer._lock:
                observer._bound_collector = prior


def create_observed_agent_model(
    telemetry: RecruitmentTelemetry,
    *,
    role: str,
    **model_options: Any,
):
    """Build a default agent model with content-free transport observation."""
    from resume_agent.models import create_agent_model

    return create_agent_model(
        **model_options,
        http_client=observed_http_client(),
        callbacks=[ModelTransportObserver(telemetry, role=role)],
    )


class ModelTransportObserver(BaseCallbackHandler):
    """Emit one safe retry summary for each logical chat-model call."""

    def __init__(self, telemetry: RecruitmentTelemetry, *, role: str = "unclassified") -> None:
        self._telemetry = telemetry
        self._role = role
        self._active: dict[str, tuple[_TransportCall, Token]] = {}
        self._lock = threading.Lock()
        self._bound_collector: TransportMetricsCollector | None = None

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **_kwargs: Any,
    ) -> None:
        del messages
        role = _ACTIVE_TRANSPORT_ROLE.get() or self._role
        tags = _kwargs.get("tags") or ()
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("transport_role:specialist:"):
                candidate = tag.removeprefix("transport_role:")
                if candidate and len(candidate) <= 80 and all(
                    character.isalnum() or character in "_-:." for character in candidate
                ):
                    role = candidate
                    break
        collector = _ACTIVE_TRANSPORT_METRICS.get()
        with self._lock:
            collector = collector or self._bound_collector
        call = _TransportCall(
            collector=collector,
            role=role,
            started_at=time.perf_counter(),
            model_hint=_model_identity(serialized, _kwargs),
        )
        token = _ACTIVE_TRANSPORT_CALL.set(call)
        with self._lock:
            self._active[str(run_id)] = (call, token)

    def on_llm_end(self, response: Any, *, run_id: UUID, **_kwargs: Any) -> None:
        self._finish(run_id, outcome="success", response=response)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **_kwargs: Any) -> None:
        self._finish(run_id, outcome="error", error_type=type(error).__name__)

    def _finish(
        self,
        run_id: UUID,
        *,
        outcome: str,
        error_type: str = "",
        response: Any | None = None,
    ) -> None:
        with self._lock:
            active = self._active.pop(str(run_id), None)
        if active is None:
            return
        call, token = active
        try:
            _ACTIVE_TRANSPORT_CALL.reset(token)
        except ValueError:
            # A callback manager may finish on a copied context. Clearing the
            # local context is safe; the mutable counter contains no user data.
            _ACTIVE_TRANSPORT_CALL.set(None)
        attributes: dict[str, str | int | float | bool] = {
            "transport_attempt_count": call.attempts,
            "transport_retry_count": max(0, call.attempts - 1),
            "outcome": outcome,
        }
        if error_type:
            attributes["error_type"] = error_type
        attributes["role"] = call.role
        input_tokens, output_tokens, model = _response_usage(response)
        model = model or call.model_hint
        latency_ms = round(max(0.0, (time.perf_counter() - call.started_at) * 1000), 3)
        attributes["input_tokens"] = input_tokens
        attributes["output_tokens"] = output_tokens
        attributes["latency_ms"] = latency_ms
        if model:
            attributes["model"] = model
        if call.collector is not None:
            semantic_attempt = None
            if call.role == "resume_edit_evidence":
                semantic_attempt = {
                    "attempt_id": f"resume_edit_evidence:{run_id}",
                    "stage": "resume_edit_evidence",
                    "team_member": "resume_edit_evidence",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "attempt_count": 1,
                    "status": outcome,
                }
                if error_type:
                    semantic_attempt["error_type"] = error_type
            call.collector.record(
                role=call.role,
                attempts=call.attempts,
                outcome=outcome,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                model=model,
                semantic_attempt=semantic_attempt,
            )
        with self._telemetry.operation("model_transport", attributes) as operation:
            if error_type:
                operation.mark_error(error_type)


def _response_usage(response: Any | None) -> tuple[int, int, str]:
    """Extract safe usage metadata from a LangChain LLM result."""
    message = None
    generations = getattr(response, "generations", None) or []
    if generations and generations[0]:
        message = getattr(generations[0][0], "message", None)
    usage = getattr(message, "usage_metadata", None) or {}
    metadata = getattr(message, "response_metadata", None) or {}
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or {}
    return (
        int(usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0),
        int(usage.get("output_tokens") or token_usage.get("completion_tokens") or 0),
        str(metadata.get("model_name") or metadata.get("model") or llm_output.get("model_name") or ""),
    )


def _model_identity(serialized: dict[str, Any], callback_kwargs: dict[str, Any]) -> str:
    """Extract only a bounded model identifier from callback metadata."""
    invocation = callback_kwargs.get("invocation_params") or {}
    serialized_kwargs = serialized.get("kwargs") or {}
    if not isinstance(invocation, dict):
        invocation = {}
    if not isinstance(serialized_kwargs, dict):
        serialized_kwargs = {}
    for value in (
        invocation.get("model_name"),
        invocation.get("model"),
        serialized_kwargs.get("model_name"),
        serialized_kwargs.get("model"),
    ):
        candidate = str(value or "").strip()
        if candidate and len(candidate) <= 200 and all(
            character.isalnum() or character in "._:/-" for character in candidate
        ):
            return candidate
    return ""
