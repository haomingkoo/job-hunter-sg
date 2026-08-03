"""Commands and results exposed by the V3 recruitment-team interface."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .discovery import JobSnapshot
from .role_success import RoleSuccessProfile


@dataclass(frozen=True)
class StartThread:
    resume_version_id: int
    message: str


@dataclass(frozen=True)
class SendMessage:
    thread_id: str
    message: str


@dataclass(frozen=True)
class BuildCandidateProfile:
    thread_id: str


@dataclass(frozen=True)
class SearchJobs:
    thread_id: str
    query: str


@dataclass(frozen=True)
class ShortlistJob:
    thread_id: str
    job_id: int


@dataclass(frozen=True)
class SelectTargetJob:
    thread_id: str
    job_id: int


@dataclass(frozen=True)
class HideJob:
    thread_id: str
    job_id: int
    scope: Literal["role", "company"]
    reason: str = ""


@dataclass(frozen=True)
class AssessTargetJob:
    thread_id: str


@dataclass(frozen=True)
class AnswerAssessmentQuestion:
    thread_id: str
    answer: str


Command = (
    StartThread
    | SendMessage
    | BuildCandidateProfile
    | SearchJobs
    | ShortlistJob
    | SelectTargetJob
    | HideJob
    | AssessTargetJob
    | AnswerAssessmentQuestion
)


PreferenceField = Literal["role", "location", "seniority", "salary", "constraints"]


@dataclass(frozen=True)
class PreferenceUpdate:
    field: PreferenceField
    value: str
    evidence_quote: str
    operation: Literal["set", "remove"] = "set"


@dataclass(frozen=True)
class PreferenceFact:
    field: PreferenceField
    value: str
    evidence_quote: str
    source_run_id: str
    source_message_id: int


@dataclass(frozen=True)
class ConfirmedEvidenceFact:
    evidence_id: str
    evidence_quote: str
    source_run_id: str
    source_message_id: int


def confirmed_evidence_fact(
    evidence_quote: str,
    *,
    source_run_id: str,
    source_message_id: int,
) -> ConfirmedEvidenceFact:
    quote = evidence_quote.strip()
    return ConfirmedEvidenceFact(
        evidence_id=f"candidate_{uuid.uuid5(uuid.NAMESPACE_URL, f'{source_run_id}:{source_message_id}:{quote}')}",
        evidence_quote=quote,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
    )


@dataclass(frozen=True)
class RunReceipt:
    run_id: str
    thread_id: str
    # The command completed. That is not the same as the work finishing: a
    # target assessment that stops to ask the candidate a question also
    # completes its command. workflow_state is what says which happened.
    status: Literal["completed"]
    trace_key: str
    workflow_state: str = ""
    attempt_ledger: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CaseFacts:
    resume_version_id: int
    resume_label: str
    resume_sha256: str
    latest_search_query: str = ""
    recommendations: tuple[JobSnapshot, ...] = ()
    match_rationales: tuple[dict, ...] = ()
    shortlisted_jobs: tuple[JobSnapshot, ...] = ()
    shortlisted_job_ids: tuple[int, ...] = ()
    selected_target: JobSnapshot | None = None
    tracked_job_ids: dict[str, int] | None = None
    job_feedback: tuple[dict, ...] = ()
    role_success_profile: RoleSuccessProfile | None = None
    role_success_metrics: dict | None = None
    preferences: tuple[PreferenceFact, ...] = ()
    confirmed_evidence: tuple[ConfirmedEvidenceFact, ...] = ()
    plan: tuple[dict[str, str], ...] = ()
    candidate_profile_artifact_id: str | None = None
    candidate_profile_status: str = "not_started"
    target_assessment_artifact_id: str | None = None
    target_assessment_status: str = "not_started"


@dataclass(frozen=True)
class CandidateProfileArtifactSnapshot:
    artifact_id: str
    resume_version_id: int
    checkpoint_id: str
    prompt_version: str
    decomposition_version: str
    model_name: str
    execution_policy: dict
    status: str
    completed_scope_ids: tuple[str, ...]
    execution_metrics: dict
    profile: dict | None
    evaluation: dict | None
    error: dict | None
    updated_at: datetime


@dataclass(frozen=True)
class TargetAssessmentArtifactSnapshot:
    artifact_id: str
    target_job_id: int
    status: str
    specialist_runs: tuple[dict, ...]
    synthesis: str
    judge: dict | None
    correction: dict | None
    error: dict | None
    execution_policy: dict
    execution_metrics: dict
    updated_at: datetime


@dataclass(frozen=True)
class Message:
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    run_id: str
    created_at: datetime


@dataclass(frozen=True)
class ActivityEvent:
    sequence: int
    run_id: str
    event_type: str
    status: str
    team_member: str
    attempt: int
    trace_key: str
    summary: str
    detail: dict
    parent_id: str | None
    duration_ms: float | None
    attributes: dict
    created_at: datetime


@dataclass(frozen=True)
class ThreadSnapshot:
    thread_id: str
    title: str
    status: str
    workflow_state: str
    case_facts: CaseFacts
    messages: list[Message]
    last_event_sequence: int


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: str
    title: str
    status: str
    workflow_state: str
    resume_version_id: int
    resume_label: str
    last_message: str | None
    updated_at: datetime
