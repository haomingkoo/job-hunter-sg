"""Per-invocation context for open-agent tools, mirroring resume_agent.tools's
_current_bullets pattern -- tools read the active request without the model
having to pass IDs it was never given."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from ..assessment_contracts import TargetAssessmentRequest

_current_request: ContextVar[TargetAssessmentRequest | None] = ContextVar(
    "open_agent_current_request", default=None
)
_proposed_edits: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "open_agent_proposed_edits", default=None
)


@contextmanager
def assessment_context(request: TargetAssessmentRequest) -> Iterator[None]:
    request_token = _current_request.set(request)
    edits_token = _proposed_edits.set([])
    try:
        yield
    finally:
        _current_request.reset(request_token)
        _proposed_edits.reset(edits_token)


def current_request() -> TargetAssessmentRequest | None:
    return _current_request.get()


def proposed_edits() -> list[dict[str, Any]] | None:
    return _proposed_edits.get()
