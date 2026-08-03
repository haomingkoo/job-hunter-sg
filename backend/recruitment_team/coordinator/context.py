"""Thread-scoped state shared by the conversational coordinator tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..candidate_profile import CandidateEvidenceProfile
from ..discovery import DiscoveryPort, JobSearchResult, JobSnapshot
from ..interface import ConfirmedEvidenceFact, PreferenceFact, PreferenceUpdate
from ..role_success import RoleSuccessProfile
from ..resume_edit_evidence import ResumeEditEvidenceValidator


@dataclass(frozen=True)
class ConversationContext:
    # RecruitmentThread.id is String(36) holding a uuid4 (models.py:312). A
    # frozen dataclass does no runtime validation and f"coordinator-{thread_id}"
    # formats either way, so an `int` annotation here would never be caught.
    thread_id: str
    trace_key: str
    candidate_profile: CandidateEvidenceProfile | None
    role_profile: RoleSuccessProfile | None
    target_job: JobSnapshot | None
    resume_document: dict[str, Any] | None
    latest_search_query: str
    recommendations: tuple[JobSnapshot, ...]
    shortlisted_jobs: tuple[JobSnapshot, ...]
    preferences: tuple[PreferenceFact, ...]
    published_matches: tuple[dict[str, Any], ...]
    discovery: DiscoveryPort
    edit_evidence_validator: ResumeEditEvidenceValidator
    plan: tuple[dict[str, str], ...] = ()
    latest_user_message: str = ""
    latest_user_message_id: int = 0
    latest_user_run_id: str = ""
    confirmed_evidence: tuple[ConfirmedEvidenceFact, ...] = ()
    drafted_confirmed_evidence: list[ConfirmedEvidenceFact] = field(
        default_factory=list,
        compare=False,
    )
    # The LangGraph thread id of a graph this thread left paused on
    # ask_candidate, or "" when nothing is pending. Read from case_facts; the
    # reply reports a new one back the same way.
    pause_token: str = ""
    # Mutable sinks. Tools append; RecruitmentTeam drains once the turn returns,
    # so the tools stay free of the ORM and the write lands in the same
    # transaction as the assistant message.
    search_results: list[JobSearchResult] = field(default_factory=list, compare=False)
    drafted_preferences: list[PreferenceUpdate] = field(default_factory=list, compare=False)
    drafted_matches: list[dict[str, Any]] = field(default_factory=list, compare=False)
    drafted_plan: list[dict[str, str]] = field(default_factory=list, compare=False)
    proposed_edits: list[dict[str, Any]] = field(default_factory=list, compare=False)
    # One normalized iter_progress_events dict per event: tool_call, tool_result,
    # message.
    on_event: Callable[[dict[str, Any]], None] | None = field(default=None, compare=False)


def current_conversation() -> ConversationContext | None:
    """The active conversational context, or None inside a target assessment."""
    from ..open_agent import context as open_agent_context

    active = open_agent_context.current_request()
    return active if isinstance(active, ConversationContext) else None


def merged_recommendations(
    context: ConversationContext,
) -> tuple[str, tuple[JobSnapshot, ...]]:
    """Merge successful searches without erasing the existing shortlist."""
    useful = [result for result in context.search_results if result.jobs]
    if not useful:
        return context.latest_search_query, context.recommendations
    seen: set[int] = set()
    merged: list[JobSnapshot] = []
    for result in reversed(useful):  # newest search first
        for job in result.jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                merged.append(job)
    return useful[-1].query, tuple(merged)
