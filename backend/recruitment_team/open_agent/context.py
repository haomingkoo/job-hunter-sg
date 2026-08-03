"""Per-invocation context for open-agent tools, mirroring resume_agent.tools's
_current_bullets pattern -- tools read the active request without the model
having to pass IDs it was never given."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator

from ..assessment_contracts import TargetAssessmentRequest

if TYPE_CHECKING:
    from ..coordinator.context import ConversationContext

# Two shapes ride this one var: a TargetAssessmentRequest for an assessment run,
# a ConversationContext for a chat turn. Tools state which they need.
_current_request: ContextVar["TargetAssessmentRequest | ConversationContext | None"] = ContextVar(
    "open_agent_current_request", default=None
)
_current_document: ContextVar[dict[str, Any] | None] = ContextVar(
    "open_agent_current_document", default=None
)
_proposed_edits: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "open_agent_proposed_edits", default=None
)


@contextmanager
def assessment_context(
    request: "TargetAssessmentRequest | ConversationContext",
    *,
    initial_edits: list[dict[str, Any]] | None = None,
) -> Iterator[None]:
    """Carry edits across an ``ask_candidate`` pause.

    Duplicate-call state belongs to the agent middleware, not this tool-data
    context.
    """
    request_token = _current_request.set(request)
    document_token = _current_document.set(request.resume_document)
    edits_token = _proposed_edits.set(initial_edits if initial_edits is not None else [])
    try:
        yield
    finally:
        _current_request.reset(request_token)
        _current_document.reset(document_token)
        _proposed_edits.reset(edits_token)


def current_request() -> "TargetAssessmentRequest | ConversationContext | None":
    return _current_request.get()


def current_document() -> dict[str, Any] | None:
    return _current_document.get()


def proposed_edits() -> list[dict[str, Any]] | None:
    return _proposed_edits.get()
