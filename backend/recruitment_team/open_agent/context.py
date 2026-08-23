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
_submitted_synthesis: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "open_agent_submitted_synthesis", default=None
)
_synthesis_validation_failures: ContextVar[list[str] | None] = ContextVar(
    "open_agent_synthesis_validation_failures", default=None
)
_required_specialist_ids: ContextVar[tuple[str, ...]] = ContextVar(
    "open_agent_required_specialist_ids", default=()
)
_completed_specialist_ids: ContextVar[list[str] | None] = ContextVar(
    "open_agent_completed_specialist_ids", default=None
)
_terminal_specialist_failures: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "open_agent_terminal_specialist_failures", default=None
)
_completed_specialist_revisit_allowed: ContextVar[bool] = ContextVar(
    "open_agent_completed_specialist_revisit_allowed", default=False
)


@contextmanager
def assessment_context(
    request: "TargetAssessmentRequest | ConversationContext",
    *,
    initial_edits: list[dict[str, Any]] | None = None,
    required_specialist_ids: tuple[str, ...] = (),
    initial_specialist_ids: tuple[str, ...] = (),
    allow_completed_specialist_revisit: bool = False,
) -> Iterator[None]:
    """Carry edits across an ``ask_candidate`` pause.

    Duplicate-call state belongs to the agent middleware, not this tool-data
    context.
    """
    request_token = _current_request.set(request)
    document_token = _current_document.set(request.resume_document)
    edits_token = _proposed_edits.set(initial_edits if initial_edits is not None else [])
    synthesis_token = _submitted_synthesis.set([])
    synthesis_failures_token = _synthesis_validation_failures.set([])
    required_specialists_token = _required_specialist_ids.set(required_specialist_ids)
    completed_specialists_token = _completed_specialist_ids.set(list(initial_specialist_ids))
    specialist_failures_token = _terminal_specialist_failures.set([])
    specialist_revisit_token = _completed_specialist_revisit_allowed.set(
        allow_completed_specialist_revisit
    )
    try:
        yield
    finally:
        _current_request.reset(request_token)
        _current_document.reset(document_token)
        _proposed_edits.reset(edits_token)
        _submitted_synthesis.reset(synthesis_token)
        _synthesis_validation_failures.reset(synthesis_failures_token)
        _required_specialist_ids.reset(required_specialists_token)
        _completed_specialist_ids.reset(completed_specialists_token)
        _terminal_specialist_failures.reset(specialist_failures_token)
        _completed_specialist_revisit_allowed.reset(specialist_revisit_token)


def current_request() -> "TargetAssessmentRequest | ConversationContext | None":
    return _current_request.get()


def current_document() -> dict[str, Any] | None:
    return _current_document.get()


def proposed_edits() -> list[dict[str, Any]] | None:
    return _proposed_edits.get()


def store_submitted_synthesis(rendered: str, claims: list[dict[str, Any]]) -> None:
    submissions = _submitted_synthesis.get()
    if submissions is not None:
        submissions.append({"rendered": rendered, "claims": claims})


def submitted_synthesis() -> str:
    submissions = _submitted_synthesis.get() or []
    return str(submissions[-1]["rendered"]) if submissions else ""


def submitted_synthesis_claims() -> list[dict[str, Any]]:
    submissions = _submitted_synthesis.get() or []
    return list(submissions[-1]["claims"]) if submissions else []


def record_synthesis_validation_failure(code: str) -> int:
    failures = _synthesis_validation_failures.get()
    if failures is None:
        return 1
    failures.append(code)
    return len(failures)


def record_completed_specialist(persona_id: str) -> None:
    completed = _completed_specialist_ids.get()
    if completed is not None and persona_id not in completed:
        completed.append(persona_id)


def record_terminal_specialist_failure(persona_id: str, validation_codes: list[str]) -> None:
    failures = _terminal_specialist_failures.get()
    if failures is not None:
        failures.append({"persona_id": persona_id, "validation_codes": list(validation_codes)})


def terminal_specialist_failure() -> dict[str, Any] | None:
    failures = _terminal_specialist_failures.get() or []
    return dict(failures[-1]) if failures else None


def completed_specialist_revisit_allowed() -> bool:
    return _completed_specialist_revisit_allowed.get()


def missing_required_specialists() -> tuple[str, ...]:
    completed = set(_completed_specialist_ids.get() or ())
    return tuple(
        persona_id
        for persona_id in _required_specialist_ids.get()
        if persona_id not in completed
    )
