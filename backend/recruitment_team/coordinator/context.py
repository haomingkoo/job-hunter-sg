"""What a conversational turn knows about its own thread.

`TargetAssessmentRequest` (assessment_contracts.py:36-41) requires `target_job`
and `role_profile`, and a chat turn has neither, so this is a separate type
rather than a loosened version of that one. Field names are deliberately
identical where the shared open-agent tools touch them, so
`read_candidate_evidence`, `read_target_job` and `propose_resume_edit` read one
attribute name whichever context is active.

It rides the same `open_agent.context` ContextVars: `assessment_context` reads
exactly one attribute off its argument (`resume_document`) and accepts a
caller-owned edits list, so there is no second context manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..candidate_profile import CandidateEvidenceProfile
from ..discovery import DiscoveryPort, JobSearchResult, JobSnapshot
from ..interface import PreferenceFact, PreferenceUpdate
from ..role_success import RoleSuccessProfile


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
    plan: tuple[dict[str, str], ...] = ()
    latest_user_message: str = ""
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
    """The shortlist as it stands mid-turn: query and jobs.

    One function with two callers on purpose. `read_shortlist` shows the agent
    what its own searches found, and `RecruitmentTeam` writes the same list to
    `case_facts["recommendations"]`. Deriving them separately is how a panel
    ends up disagreeing with the tool the agent read.

    A search that returned nothing, or failed, changes neither. The command path
    raises before it touches `case_facts` and so can never destroy a shortlist;
    a tool has no such protection unless it is given one here.
    """
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
