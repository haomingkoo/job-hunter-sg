"""Deep V3 recruitment-team module: persistence, orchestration, and activity."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
import weakref
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from models import (
    CandidateProfileArtifact,
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    RecruitmentThreadDeletionRequest,
    ResumeVersion,
    TargetAssessmentArtifact,
    TrackedJob,
    User,
)
import config
from application_workspace import ensure_recruitment_application
from resume_agent.telemetry import trace_key
from run_concurrency import release_owner_run, reserve_owner_run
from schemas import TrackedJobCreate

from .interface import (
    ActivityEvent,
    AnswerAssessmentQuestion,
    AssessTargetJob,
    BuildCandidateProfile,
    CandidateProfileArtifactSnapshot,
    CaseFacts,
    Command,
    ConfirmedEvidenceFact,
    HideJob,
    Message,
    PreferenceFact,
    RunReceipt,
    SearchJobs,
    SelectTargetJob,
    SendMessage,
    ShortlistJob,
    StartThread,
    ThreadSnapshot,
    ThreadSummary,
    TargetAssessmentArtifactSnapshot,
    confirmed_evidence_fact,
)
from .execution_metrics import merge_execution_metrics
from .errors import (
    CandidateProfilingUnavailable,
    DiscoveryUnavailable,
    InvalidCommand,
    ResumeVersionNotFound,
    RoleProfilingUnavailable,
    RunConcurrencyExceeded,
    ThreadNotFound,
    TargetAssessmentUnavailable,
    ServiceUnavailable,
)
from .conversation_model import (
    ConversationModel,
    ModelReply,
    PreferenceUpdate,
    evidenced_preference_updates,
    paragraph_reply,
)
from .coordinator.context import ConversationContext, merged_recommendations
from .open_agent.context import assessment_context
from .open_agent.streaming import describe_progress
from .recovery import (
    AttemptLayer,
    RecoveryDecision,
    attempts_remaining,
    classify_exception,
    classify_failure,
    merge_execution_attempts,
    normalize_failure_code,
    record_attempt,
)
from .candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileProgress,
    CandidateProfileTransportError,
    CandidateProfileValidationError,
    candidate_profile_progress_event,
    CandidateProfilerFactory,
    candidate_profile_from_dict,
)
from .candidate_profile_store import (
    RETRY_FEEDBACK_SCOPE_KEY,
    CandidateProfileCheckpointMismatch,
    SQLAlchemyCandidateProfileStore,
    candidate_profile_artifact_is_current,
)
from .discovery import DiscoveryPort, JobPostingVariant, JobSnapshot, JobSource
from .role_success import (
    CandidateEvidenceMatch,
    PolicyConstraint,
    ResumeEvidenceRecord,
    RoleCitation,
    RoleCriterion,
    RoleProfileValidationError,
    RoleSource,
    RoleSuccessProfile,
    RoleSuccessProfiler,
    SourceCoverage,
)
from .role_evidence_assessor import RoleEvidenceAssessmentError, role_evidence_attempt_limit
from .telemetry import RecruitmentTelemetry
from .activity_publisher import ActivityPublisher
from .prompts import CONVERSATION_PROMPT_VERSION
from .assessment_contracts import (
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentRunner,
    target_assessment_execution_policy,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


FIRST_ATTEMPT = 1
ACTIVE_THREAD_STATUS = "active"
ARCHIVED_THREAD_STATUS = "archived"
THREAD_TITLE_MAX_CHARS = 120
MAX_JOB_FEEDBACK_SIGNALS = 100
# A derived query stands in for a typed one, so keep it to a search-sized phrase.
MAX_DERIVED_QUERY_CHARS = 200
# Fallback for turns where the model composed no phrase. Only what the candidate
# wants belongs in a similarity query: an embedding has no way to represent
# "not", so searching "not computer vision" scores computer vision roles higher.
SEMANTIC_PREFERENCE_FIELDS = frozenset({"role"})
# A UI-sent opener is an instruction to the team, not something the candidate
# wants searched, so it must never become the query.
AUTOPILOT_MARKER = "[autopilot]"
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?65[\s-]?)?[689]\d{3}[\s-]?\d{4}(?!\d)")


def _job_hidden_by_feedback(facts: dict, job: JobSnapshot) -> bool:
    company = job.company.strip().casefold()
    for signal in facts.get("job_feedback", []):
        if not isinstance(signal, dict):
            continue
        if signal.get("scope") == "role" and signal.get("target") == str(job.job_id):
            return True
        if signal.get("scope") == "company" and signal.get("target") == company:
            return True
    return False


def _safe_trace_query(query: str) -> tuple[str, bool]:
    if _EMAIL.search(query) or _PHONE.search(query):
        return "[redacted: possible contact data]", True
    return query, False


def _trace_attributes(item: dict, detail: dict) -> dict:
    """Persist operational facts only; never raw messages, resumes, or reasoning."""
    attributes = {}
    for key in ("tool_name", "stage"):
        if isinstance(detail.get(key), str):
            attributes[key] = detail[key]
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    if isinstance(args.get("query"), str):
        query, redacted = _safe_trace_query(args["query"])
        attributes["query"] = query
        attributes["query_redacted"] = redacted
    if isinstance(detail.get("result_count"), int):
        attributes["result_count"] = detail["result_count"]
    if item.get("id"):
        attributes["span_id"] = str(item["id"])
    return attributes


def _trace_event_fields(
    *,
    kind: str,
    call_id: str,
    run_id: str,
    detail: dict,
    started_calls: dict[str, float],
    args: dict | None = None,
) -> tuple[str, float | None, dict]:
    duration_ms = None
    if kind == "tool_call" and call_id:
        started_calls[call_id] = time.perf_counter()
    elif kind == "tool_result" and call_id:
        started_at = started_calls.pop(call_id, None)
        if started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000
    item = {"kind": kind, "id": call_id, "args": args or {}}
    parent_id = call_id if kind == "tool_result" and call_id else run_id
    return parent_id, duration_ms, _trace_attributes(item, detail)


def _run_duration_ms(run: RecruitmentRun) -> float | None:
    if run.created_at is None:
        return None
    started = run.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (_utcnow() - started).total_seconds() * 1000)


def _trim_to_word(text: str, limit: int) -> str:
    """Cut to a whole word. A slice mid-token leaves the model a fragment."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else head).strip()


def _current_candidate_profile_artifact(
    artifacts: list[CandidateProfileArtifact],
) -> CandidateProfileArtifact | None:
    return next(
        (
            item
            for item in artifacts
            if candidate_profile_artifact_is_current(item)
        ),
        None,
    )


RESUME_TITLE_MAX_CHARS = 60
RESUME_TITLE_LINES = 3
RESUME_FALLBACK_WORDS = 30
# A LinkedIn PDF export is two-column, and text extraction interleaves the
# sidebar with the body, so nothing can be inferred from a line's position.
# These pick title-shaped lines out of that jumble wherever they landed.
_ROLE_WORD = re.compile(
    r"\b(engineer|analyst|manager|accountant|consultant|specialist|developer"
    r"|director|lead|officer|executive|scientist|architect)\b",
    re.IGNORECASE,
)
# Contact details are not signal, and a query is not a place to put someone's
# email address.
_CONTACT_LINE = re.compile(r"@|https?://|linkedin\.com|www\.|\+\d{6,}", re.IGNORECASE)
_FIRST_PERSON = re.compile(r"\b(i|i'm|my|me|we)\b", re.IGNORECASE)
BUILD_CANDIDATE_PROFILE_MESSAGE = "Study my attached resume and build its evidence profile."
ASSESS_TARGET_JOB_MESSAGE = "Run the bounded recruitment-team assessment for my selected target."
COMPLETION_SUMMARIES = {
    "coordinator": "The coordinator completed this turn.",
    "candidate_profiler": "The candidate profiler completed this turn.",
    "quality_judge": "The independent quality judge completed this turn.",
}
TRANSPORT_ATTEMPT_LIMIT = FIRST_ATTEMPT + config.RECRUITMENT_MODEL_TRANSPORT_RETRIES
SEMANTIC_ATTEMPT_LIMITS = {
    "start_thread": config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS,
    "send_message": config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS,
    "build_candidate_profile": config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
    "search_jobs": FIRST_ATTEMPT,
    "shortlist_job": FIRST_ATTEMPT,
    "select_target_job": max(
        config.ROLE_DEFINITION_VALIDATION_ATTEMPTS,
        config.ROLE_EVIDENCE_VALIDATION_ATTEMPTS,
    ),
    "assess_target_job": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
    "answer_assessment_question": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
    "hide_job": FIRST_ATTEMPT,
}

# One lock per thread_id, serializing every command against that thread so two
# concurrent requests (e.g. a double-click answering a paused assessment, or
# two browser tabs) can't both pass a workflow_state check-then-act before
# either commits its transition. Weakly held so the registry doesn't grow
# unbounded over a long-running process -- an entry disappears once nothing
# is actively holding that thread's lock.
_THREAD_LOCKS: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
_THREAD_LOCKS_REGISTRY_LOCK = threading.Lock()


def _thread_lock(thread_id: str) -> threading.Lock:
    with _THREAD_LOCKS_REGISTRY_LOCK:
        lock = _THREAD_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[thread_id] = lock
        return lock


def _reserve_event_sequence(db: Session, thread_id: str) -> int:
    """Atomically reserve one ordered event number across database sessions."""
    next_value = db.execute(
        update(RecruitmentThread)
        .where(RecruitmentThread.id == thread_id)
        .values(next_event_sequence=RecruitmentThread.next_event_sequence + 1)
        .returning(RecruitmentThread.next_event_sequence)
    ).scalar_one()
    return int(next_value) - 1


class RecruitmentTeam:
    """The sole orchestration interface used by transports, canaries, and tests."""

    def __init__(
        self,
        db: Session,
        conversation_model: ConversationModel,
        discovery: DiscoveryPort,
        role_profiler: RoleSuccessProfiler,
        telemetry: RecruitmentTelemetry,
        activity_publisher: ActivityPublisher,
        candidate_profiler_factory: CandidateProfilerFactory | None = None,
        target_assessment_runner: TargetAssessmentRunner | None = None,
        study_dispatcher: Callable[[int, int, str], None] | None = None,
    ):
        self._db = db
        self._conversation_model = conversation_model
        self._discovery = discovery
        self._role_profiler = role_profiler
        self._telemetry = telemetry
        self._activity_publisher = activity_publisher
        self._candidate_profiler_factory = candidate_profiler_factory
        self._target_assessment_runner = target_assessment_runner
        self._study_dispatcher = study_dispatcher

    def _record_run_attempt(
        self,
        run: RecruitmentRun,
        *,
        stage: str,
        layer: AttemptLayer,
        limit: int,
        status: str,
        decision: RecoveryDecision | None = None,
        model: str = "",
        validation_code: str = "",
        error_type: str = "",
    ) -> None:
        stage_ledger = ((run.attempt_ledger or {}).get("stages") or {}).get(stage) or {}
        used = int((stage_ledger.get(layer) or {}).get("used") or 0)
        run.attempt_ledger = record_attempt(
            run.attempt_ledger,
            logical_run_id=run.id,
            stage=stage,
            layer=layer,
            limit=limit,
            status=status,
            attempt_id=f"{stage}:{layer}:{used + 1}",
            decision=decision,
            model=model,
            validation_code=validation_code,
            error_type=error_type,
        )

    def _merge_run_metrics(
        self,
        run: RecruitmentRun,
        metrics: dict | None,
        *,
        semantic_limit: int,
    ) -> None:
        run.attempt_ledger = merge_execution_attempts(
            run.attempt_ledger,
            logical_run_id=run.id,
            metrics=metrics,
            transport_limit=TRANSPORT_ATTEMPT_LIMIT,
            semantic_limit=semantic_limit,
        )

    def _persist_recovery_decision(
        self,
        thread: RecruitmentThread,
        command_type: str,
        detail: dict,
    ) -> None:
        facts = thread.case_facts or {}
        if command_type == "build_candidate_profile":
            artifact_id = facts.get("candidate_profile_artifact_id")
            artifact = self._db.get(CandidateProfileArtifact, artifact_id) if artifact_id else None
        elif command_type in {"assess_target_job", "answer_assessment_question"}:
            artifact_id = facts.get("target_assessment_artifact_id")
            artifact = self._db.get(TargetAssessmentArtifact, artifact_id) if artifact_id else None
        else:
            artifact = None
        if artifact is not None:
            existing = artifact.error or {}
            cause_type = existing.get("error_type")
            merged = {**existing, **detail}
            if cause_type:
                merged["error_type"] = cause_type
            artifact.error = merged

    def _prepare_workflow_resume(self, run: RecruitmentRun) -> None:
        stage = run.command_type
        remaining = attempts_remaining(
            run.attempt_ledger,
            stage,
            "workflow_resume",
            config.RECRUITMENT_WORKFLOW_RESUME_LIMIT,
        )
        last = (run.attempt_ledger or {}).get("last_decision") or {}
        failure_code = str(last.get("failure_code") or "unclassified_failure")
        if last.get("retryable") is not True:
            raise ServiceUnavailable(
                "the failed command cannot be resumed safely",
                decision=classify_failure(failure_code),
            )
        decision = classify_failure(
            failure_code,
            attempts_remaining=remaining,
        )
        if not decision.retryable:
            raise ServiceUnavailable(
                "the failed command cannot be resumed safely",
                decision=decision,
            )
        self._record_run_attempt(
            run,
            stage=stage,
            layer="workflow_resume",
            limit=config.RECRUITMENT_WORKFLOW_RESUME_LIMIT,
            status="resumed",
            decision=decision,
        )
        self._db.commit()

    def execute(
        self,
        owner_id: int,
        command: Command,
        idempotency_key: str,
    ) -> RunReceipt:
        key = idempotency_key.strip()
        if not key:
            raise InvalidCommand("idempotency_key is required")
        previous = (
            self._db.query(RecruitmentRun)
            .filter(
                RecruitmentRun.user_id == owner_id,
                RecruitmentRun.idempotency_key == key,
            )
            .first()
        )
        if previous is not None and previous.status != "failed":
            return self._receipt(previous)
        if previous is not None:
            self._prepare_workflow_resume(previous)

        owner_key = f"user:{owner_id}"
        capacity_limited = isinstance(
            command,
            (
                StartThread,
                SendMessage,
                BuildCandidateProfile,
                SearchJobs,
                AssessTargetJob,
                AnswerAssessmentQuestion,
            ),
        )
        if capacity_limited and not reserve_owner_run(owner_key):
            raise RunConcurrencyExceeded(
                "Another AI run is already active for this user or the service is at capacity. Try again shortly."
            )
        try:
            thread_id = getattr(command, "thread_id", None)
            if thread_id is None:
                return self._execute_locked(owner_id, command, key, previous)
            with _thread_lock(thread_id):
                return self._execute_locked(owner_id, command, key, previous)
        finally:
            if capacity_limited:
                release_owner_run(owner_key)

    def _execute_locked(
        self,
        owner_id: int,
        command: Command,
        idempotency_key: str,
        previous: RecruitmentRun | None,
    ) -> RunReceipt:
        key = idempotency_key

        with self._telemetry.operation(
            "command",
            {
                "owner_type": "user",
                "attempt": FIRST_ATTEMPT,
            },
        ) as command_span:
            if isinstance(command, StartThread):
                if previous is None:
                    thread, resume = self._start_thread(owner_id, command)
                else:
                    thread = self._owned_thread(owner_id, previous.thread_id)
                    resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "start_thread"
                message = command.message
            elif isinstance(command, SendMessage):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "send_message"
                message = command.message
            elif isinstance(command, BuildCandidateProfile):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "build_candidate_profile"
                message = BUILD_CANDIDATE_PROFILE_MESSAGE
            elif isinstance(command, SearchJobs):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "search_jobs"
                message = command.query.strip() or self._query_from_candidate(thread, resume)
            elif isinstance(command, ShortlistJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "shortlist_job"
                job = self._known_job(thread, command.job_id)
                message = f"Shortlist {job.title} at {job.company}."
            elif isinstance(command, SelectTargetJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "select_target_job"
                job = self._known_job(thread, command.job_id)
                message = f"Select {job.title} at {job.company} as my target."
            elif isinstance(command, HideJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "hide_job"
                job = self._known_job(thread, command.job_id)
                message = f"Hide this {command.scope}: {job.title} at {job.company}."
            elif isinstance(command, AssessTargetJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "assess_target_job"
                message = ASSESS_TARGET_JOB_MESSAGE
            elif isinstance(command, AnswerAssessmentQuestion):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "answer_assessment_question"
                message = command.answer
            else:
                raise InvalidCommand("unsupported recruitment-team command")

            if thread.status != ACTIVE_THREAD_STATUS:
                raise InvalidCommand("restore this archived conversation before continuing its workflow")

            if not message.strip():
                raise InvalidCommand("message is required")

            if previous is not None:
                run_id = previous.id
                correlation_key = trace_key(run_id)
                command_span.set_attribute("trace_key", correlation_key)
                command_span.set_attribute("command_type", command_type)
                run = previous
                run.command_type = command_type
                run.status = "running"
                run.trace_key = correlation_key
                run.error_type = None
                run.result = None
                run.completed_at = None
            else:
                run_id = str(uuid.uuid4())
                correlation_key = trace_key(run_id)
                command_span.set_attribute("trace_key", correlation_key)
                command_span.set_attribute("command_type", command_type)
                run = RecruitmentRun(
                    id=run_id,
                    user_id=owner_id,
                    thread_id=thread.id,
                    idempotency_key=key,
                    command_type=command_type,
                    status="running",
                    trace_key=correlation_key,
                )
                self._db.add(run)
            if previous is None and not isinstance(command, SearchJobs):
                self._db.add(
                    RecruitmentMessage(
                        thread_id=thread.id,
                        run_id=run_id,
                        role="user",
                        content=message.strip(),
                    )
                )
            candidate_profile_command = isinstance(command, BuildCandidateProfile)
            running_event = self._event(
                thread,
                run,
                event_type="run",
                status="running",
                summary=(
                    "The candidate profiler is studying this resume."
                    if candidate_profile_command
                    else "The recruitment-team coordinator is reviewing your request."
                ),
                team_member=(
                    "candidate_profiler" if candidate_profile_command else "coordinator"
                ),
            )
            with self._telemetry.operation("persist_running"):
                self._db.commit()
            self._activity_publisher.publish(self._activity(running_event))

            if isinstance(command, StartThread) and self._study_dispatcher is not None:
                self._study_dispatcher(owner_id, resume.id, thread.id)

            try:
                if isinstance(command, SearchJobs):
                    reply, completion_detail = self._search_jobs(thread, command, message)
                    completion_member = "coordinator"
                elif isinstance(command, BuildCandidateProfile):
                    reply, completion_detail = self._build_candidate_profile(
                        owner_id,
                        thread,
                        resume,
                        run,
                    )
                    completion_member = "candidate_profiler"
                elif isinstance(command, ShortlistJob):
                    reply, completion_detail = self._shortlist_job(owner_id, thread, resume, command)
                    completion_member = "coordinator"
                elif isinstance(command, SelectTargetJob):
                    reply, completion_detail = self._select_target(
                        owner_id,
                        thread,
                        resume,
                        run,
                        command,
                    )
                    completion_member = "coordinator"
                elif isinstance(command, HideJob):
                    reply, completion_detail = self._hide_job(thread, command)
                    completion_member = "coordinator"
                elif isinstance(command, AssessTargetJob):
                    reply, completion_detail = self._assess_target(
                        owner_id,
                        thread,
                        resume,
                        run,
                    )
                    # A paused run (the ask_candidate interrupt) never reaches
                    # the judge -- _assess_target sets workflow_state to
                    # "awaiting_candidate_answer" for exactly that case, so
                    # use it to avoid crediting the judge for a turn it never
                    # ran on.
                    completion_member = (
                        "coordinator"
                        if thread.workflow_state == "awaiting_candidate_answer"
                        else "quality_judge"
                    )
                elif isinstance(command, AnswerAssessmentQuestion):
                    reply, completion_detail = self._answer_assessment_question(
                        owner_id,
                        thread,
                        resume,
                        run,
                        command.answer,
                    )
                    # Same reasoning as AssessTargetJob above: answering may
                    # itself pause again on a follow-up question.
                    completion_member = (
                        "coordinator"
                        if thread.workflow_state == "awaiting_candidate_answer"
                        else "quality_judge"
                    )
                else:
                    reply = self._model_reply(
                        thread,
                        resume,
                        run,
                        correlation_key,
                        command_type,
                    )
                    completion_detail = {"model": reply.model_name}
                    completion_member = "coordinator"
            except BaseException as error:
                run.status = "failed"
                run.error_type = type(error).__name__
                run.completed_at = _utcnow()
                initial_decision = (
                    error.decision
                    if isinstance(error, ServiceUnavailable)
                    else classify_exception(error)
                )
                layer: AttemptLayer = (
                    "transport" if initial_decision.failure_type == "transient" else "semantic"
                )
                limit = (
                    TRANSPORT_ATTEMPT_LIMIT
                    if layer == "transport"
                    else SEMANTIC_ATTEMPT_LIMITS[command_type]
                )
                remaining = attempts_remaining(
                    run.attempt_ledger,
                    command_type,
                    layer,
                    limit - FIRST_ATTEMPT,
                )
                decision = (
                    classify_failure(
                        initial_decision.failure_code,
                        attempts_remaining=remaining,
                        retry_after_seconds=initial_decision.retry_after_seconds,
                    )
                    if initial_decision.failure_type == "transient"
                    else initial_decision
                )
                self._record_run_attempt(
                    run,
                    stage=command_type,
                    layer=layer,
                    limit=limit,
                    status="error",
                    decision=decision,
                    error_type=type(error).__name__,
                )
                failure_detail = {
                    "error_type": type(error).__name__,
                    "failure_type": decision.failure_type,
                    "failure_code": decision.failure_code,
                    "retryable": decision.retryable,
                    "recovery_action": decision.recovery_action,
                }
                if decision.retry_after_seconds is not None:
                    failure_detail["retry_after_seconds"] = decision.retry_after_seconds
                self._persist_recovery_decision(thread, command_type, failure_detail)
                for attribute, value in failure_detail.items():
                    command_span.set_attribute(attribute, value)
                failed_event = self._event(
                    thread,
                    run,
                    event_type="run",
                    status="failed",
                    summary="The coordinator could not complete this turn.",
                    detail=failure_detail,
                    parent_id=run.id,
                    duration_ms=_run_duration_ms(run),
                    attributes=failure_detail,
                )
                with self._telemetry.operation("persist_failed"):
                    self._db.commit()
                self._activity_publisher.publish(self._activity(failed_event))
                raise

            if command_type in {"start_thread", "send_message"}:
                self._record_run_attempt(
                    run,
                    stage=command_type,
                    layer="transport",
                    limit=TRANSPORT_ATTEMPT_LIMIT,
                    status="success",
                    model=reply.model_name,
                )
                self._record_run_attempt(
                    run,
                    stage=command_type,
                    layer="semantic",
                    limit=SEMANTIC_ATTEMPT_LIMITS[command_type],
                    status="success",
                    model=reply.model_name,
                )
            elif command_type == "search_jobs":
                self._record_run_attempt(
                    run,
                    stage=command_type,
                    layer="transport",
                    limit=TRANSPORT_ATTEMPT_LIMIT,
                    status="success",
                    model=reply.model_name,
                )

            self._db.add(
                RecruitmentMessage(
                    thread_id=thread.id,
                    run_id=run_id,
                    role="assistant",
                    content=reply.content,
                )
            )
            run.status = "completed"
            run.completed_at = _utcnow()
            run.result = {
                "run_id": run.id,
                "thread_id": run.thread_id,
                "status": run.status,
                "trace_key": run.trace_key,
                # Frozen here, not read from the thread at receipt time: the
                # thread moves on, so replaying a paused run's idempotency key
                # after it resumed would otherwise report the later state.
                "workflow_state": thread.workflow_state or "",
            }
            completed_event = self._event(
                thread,
                run,
                event_type="run",
                status="completed",
                summary=COMPLETION_SUMMARIES[completion_member],
                detail=completion_detail,
                team_member=completion_member,
                parent_id=run.id,
                duration_ms=_run_duration_ms(run),
                attributes={
                    key: value
                    for key, value in completion_detail.items()
                    if key in {"model", "input_tokens", "output_tokens"}
                },
            )
            thread.updated_at = _utcnow()
            with self._telemetry.operation("persist_completed"):
                self._db.commit()
            self._activity_publisher.publish(self._activity(completed_event))
            return self._receipt(run)

    def _model_reply(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
        correlation_key: str,
        command_type: str,
    ) -> ModelReply:
        with self._telemetry.operation(
            "model",
            {
                "trace_key": correlation_key,
                "command_type": command_type,
                "workflow_state": thread.workflow_state,
                "attempt": FIRST_ATTEMPT,
            },
        ) as model_span:
            messages = self._messages(thread.id)
            latest_user = next(
                (message for message in reversed(messages) if message.role == "user"),
                None,
            )
            if latest_user is None:
                raise InvalidCommand("conversation turn has no user message")
            preferences = self._preference_facts(thread.case_facts)
            conversation = self._conversation_context(
                thread,
                resume,
                preferences,
                correlation_key,
                self._conversation_activity(thread, run),
                latest_user,
            )
            # The turn is handed to the model twice over: explicitly as the
            # fourth argument, which is what DeepAgentConversationModel requires
            # and refuses to run without, and through the ContextVars the
            # coordinator's tools read once the loop binds them.
            with assessment_context(conversation, initial_edits=conversation.proposed_edits):
                reply = self._conversation_model.respond(
                    messages,
                    resume.resume_text,
                    preferences,
                    conversation,
                )
            if not reply.content:
                raise InvalidCommand("conversation model returned no user-facing reply")
            reply = replace(reply, content=paragraph_reply(reply.content))
            evidenced, unevidenced = evidenced_preference_updates(
                (*reply.preference_updates, *conversation.drafted_preferences),
                latest_user.content,
            )
            if evidenced:
                self._merge_preference_updates(thread, evidenced, latest_user)
            if conversation.drafted_confirmed_evidence:
                self._merge_confirmed_evidence(thread, conversation.drafted_confirmed_evidence)
            if reply.search_query:
                self._remember_search_query(thread, reply.search_query)
            # After _remember_search_query on purpose: a query that really ran
            # outranks one the model merely asked for.
            self._persist_conversation_searches(thread, conversation)
            self._persist_conversation_matches(thread, conversation)
            self._persist_conversation_plan(thread, conversation)
            self._persist_conversation_edits(thread, resume, run, conversation)
            self._remember_pause_token(thread, reply.pause_token)
            model_span.set_attribute("model", reply.model_name)
            model_span.set_attribute(
                "prompt_version",
                getattr(reply, "prompt_version", "") or CONVERSATION_PROMPT_VERSION,
            )
            model_span.set_attribute("preference_update_count", len(evidenced))
            if unevidenced:
                # Recorded, not raised. The quote could not be found in what the
                # candidate just wrote, so the update is dropped and the rest of
                # the turn stands.
                model_span.set_attribute("preference_updates_dropped", len(unevidenced))
                model_span.set_attribute("preference_update_rejections", "; ".join(unevidenced))
            if reply.input_tokens is not None:
                model_span.set_attribute("input_tokens", reply.input_tokens)
            if reply.output_tokens is not None:
                model_span.set_attribute("output_tokens", reply.output_tokens)
            return reply

    def _conversation_context(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        preferences: tuple[PreferenceFact, ...],
        correlation_key: str,
        on_event,
        latest_user: Message,
    ) -> ConversationContext:
        """Everything this turn already knows, assembled once before the model runs."""
        from resume_document import create_resume_document

        facts = thread.case_facts
        profile = self._find_completed_candidate_profile(thread, resume)
        return ConversationContext(
            thread_id=thread.id,
            trace_key=correlation_key,
            candidate_profile=profile,
            role_profile=(
                self._role_profile_from_dict(facts["role_success_profile"])
                if isinstance(facts.get("role_success_profile"), dict)
                else None
            ),
            target_job=(
                self._job_from_dict(facts["selected_target"])
                if isinstance(facts.get("selected_target"), dict)
                else None
            ),
            resume_document=create_resume_document(resume.resume_text),
            latest_search_query=str(facts.get("latest_search_query") or ""),
            recommendations=tuple(
                self._job_from_dict(item) for item in facts.get("recommendations", [])
            ),
            shortlisted_jobs=tuple(
                self._job_from_dict(item) for item in facts.get("shortlisted_jobs", [])
            ),
            preferences=preferences,
            published_matches=tuple(
                item for item in facts.get("match_rationales", []) if isinstance(item, dict)
            ),
            plan=self._plan_steps(facts),
            discovery=self._discovery,
            latest_user_message=latest_user.content,
            latest_user_message_id=latest_user.message_id,
            latest_user_run_id=latest_user.run_id,
            confirmed_evidence=self._confirmed_evidence_facts(facts),
            pause_token=str(facts.get("coordinator_pause_token") or ""),
            on_event=on_event,
        )

    @staticmethod
    def _remember_pause_token(thread: RecruitmentThread, pause_token: str) -> None:
        """Persist or clear the conversational pause token."""
        facts = dict(thread.case_facts)
        if pause_token:
            facts["coordinator_pause_token"] = pause_token
        elif "coordinator_pause_token" not in facts:
            return
        else:
            facts.pop("coordinator_pause_token")
        thread.case_facts = facts

    def _conversation_activity(self, thread: RecruitmentThread, run: RecruitmentRun):
        """Persist and publish each coordinator tool event."""

        started_calls: dict[str, float] = {}

        def publish(item: dict) -> None:
            described = describe_progress(item)
            if described is None:
                return
            summary, detail = described
            call_id = str(item.get("id") or "")
            parent_id, duration_ms, attributes = _trace_event_fields(
                kind=str(item.get("kind") or ""),
                call_id=call_id,
                run_id=run.id,
                detail=detail,
                started_calls=started_calls,
                args=item.get("args") if isinstance(item.get("args"), dict) else None,
            )
            event = self._event(
                thread,
                run,
                event_type="conversation",
                status="running",
                summary=summary,
                detail=detail,
                team_member=item.get("team_member") or "coordinator",
                parent_id=parent_id,
                duration_ms=duration_ms,
                attributes=attributes,
            )
            self._db.commit()
            self._activity_publisher.publish(self._activity(event))

        return publish

    def _persist_conversation_edits(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
        conversation: ConversationContext,
    ) -> None:
        """Persist coordinator edits for candidate review."""
        for edit in conversation.proposed_edits:
            self._db.add(
                ProposedResumeEdit(
                    id=str(uuid.uuid4()),
                    user_id=thread.user_id,
                    thread_id=thread.id,
                    run_id=run.id,
                    resume_version_id=resume.id,
                    block_id=edit["block_id"],
                    section_key=edit.get("section_key", ""),
                    entry_id=edit.get("entry_id", ""),
                    original=edit["original"],
                    rewrite=edit["rewrite"],
                    evidence_ids=edit.get("evidence_ids") or None,
                    document_revision=edit["document_revision"],
                    status="pending",
                )
            )

    def _persist_conversation_searches(
        self,
        thread: RecruitmentThread,
        conversation: ConversationContext,
    ) -> None:
        """Persist successful coordinator searches without erasing prior results."""
        results = conversation.search_results
        if not results:
            return
        # What ran, whatever it returned. _query_from_candidate reads this key on
        # the next SearchJobs command.
        self._remember_search_query(thread, results[-1].query)
        if not any(result.jobs for result in results):
            return
        latest_query, recommendations = merged_recommendations(conversation)
        facts = dict(thread.case_facts)
        recommendations = tuple(
            job for job in recommendations if not _job_hidden_by_feedback(facts, job)
        )
        facts["latest_search_query"] = latest_query
        facts["recommendations"] = [asdict(job) for job in recommendations]
        facts.pop("match_rationales", None)
        thread.case_facts = facts

    def _persist_conversation_matches(
        self,
        thread: RecruitmentThread,
        conversation: ConversationContext,
    ) -> None:
        """Persist the agent's ordered, evidence-gated shortlist artifact."""
        if not conversation.drafted_matches:
            return
        _, recommendations = merged_recommendations(conversation)
        known_jobs = {
            job.job_id: job
            for job in (*recommendations, *conversation.shortlisted_jobs)
        }
        requested_job_ids = [int(match["job_id"]) for match in conversation.drafted_matches]
        if any(job_id not in known_jobs for job_id in requested_job_ids):
            raise InvalidCommand("published shortlist referenced an unavailable job")
        facts = dict(thread.case_facts)
        job_ids = [
            job_id
            for job_id in requested_job_ids
            if not _job_hidden_by_feedback(facts, known_jobs[job_id])
        ]
        facts["recommendations"] = [asdict(known_jobs[job_id]) for job_id in job_ids]
        facts["match_rationales"] = [
            match for match in conversation.drafted_matches if int(match["job_id"]) in job_ids
        ]
        thread.case_facts = facts

    @staticmethod
    def _persist_conversation_plan(
        thread: RecruitmentThread,
        conversation: ConversationContext,
    ) -> None:
        if not conversation.drafted_plan:
            return
        facts = dict(thread.case_facts)
        facts["plan"] = list(conversation.drafted_plan)
        thread.case_facts = facts

    def _query_from_candidate(self, thread: RecruitmentThread, resume: ResumeVersion) -> str:
        """Build a search query from model output, preferences, message, or resume."""
        facts = thread.case_facts or {}
        composed = str(facts.get("search_query") or "").strip()
        if composed:
            return _trim_to_word(composed, MAX_DERIVED_QUERY_CHARS)

        preferences = " ".join(
            str(fact.get("value") or "")
            for fact in (facts.get("preferences") or [])
            if isinstance(fact, dict) and fact.get("field") in SEMANTIC_PREFERENCE_FIELDS
        ).strip()
        if preferences:
            return _trim_to_word(preferences, MAX_DERIVED_QUERY_CHARS)

        latest = (
            self._db.query(RecruitmentMessage)
            .filter(RecruitmentMessage.thread_id == thread.id, RecruitmentMessage.role == "user")
            .order_by(RecruitmentMessage.id.desc())
            .first()
        )
        typed = (latest.content or "").strip() if latest else ""
        if typed and not typed.startswith(AUTOPILOT_MARKER):
            return _trim_to_word(typed, MAX_DERIVED_QUERY_CHARS)

        return self._query_from_resume(resume)

    @staticmethod
    def _query_from_resume(resume: ResumeVersion) -> str:
        """Build a search phrase from resume role titles and skills."""
        from resume_agent.tools import extract_skills

        text = resume.resume_text or ""
        titles: list[str] = []
        seen: set[str] = set()
        for raw in text.splitlines():
            line = raw.strip().rstrip("\u00b7").strip()
            if not line or len(line) > RESUME_TITLE_MAX_CHARS or line.endswith("."):
                continue
            if _CONTACT_LINE.search(line) or _FIRST_PERSON.search(line):
                continue
            if not _ROLE_WORD.search(line) or line.lower() in seen:
                continue
            seen.add(line.lower())
            titles.append(line)
            if len(titles) >= RESUME_TITLE_LINES:
                break

        phrase = " ".join(titles + extract_skills.invoke({"text": text})).strip()
        if not phrase:
            # A prose resume has no title lines and may name no known skill, so
            # use its own opening words rather than the label the candidate typed.
            body = [
                line.strip() for line in text.splitlines()
                if line.strip() and not _CONTACT_LINE.search(line)
            ]
            phrase = " ".join(" ".join(body).split()[:RESUME_FALLBACK_WORDS]).strip()
        return _trim_to_word(phrase or resume.label or "roles matching my experience",
                             MAX_DERIVED_QUERY_CHARS)

    def _search_jobs(
        self,
        thread: RecruitmentThread,
        command: SearchJobs,
        resolved_query: str,
    ) -> tuple[ModelReply, dict]:
        with self._telemetry.operation(
            "job.search",
            {
                "attempt": FIRST_ATTEMPT,
            },
        ) as search_span:
            search_span.set_attribute("query_derived", not command.query.strip())
            result = self._discovery.search_jobs(resolved_query)
            search_span.set_attribute("valid_empty", result.valid_empty)
            search_span.set_attribute("result_count", len(result.jobs))
            search_span.set_attribute("truncated", result.truncated)
            if result.failure_type:
                search_span.set_attribute("failure_type", result.failure_type)
                decision = classify_failure(
                    result.failure_code or "unclassified_failure",
                    attempts_remaining=False,
                )
                search_span.set_attribute("failure_code", decision.failure_code)
                search_span.set_attribute("retryable", decision.retryable)
                raise DiscoveryUnavailable(
                    f"job search unavailable: {decision.failure_code}",
                    decision=decision,
                )

        facts = dict(thread.case_facts)
        visible_jobs = tuple(
            job for job in result.jobs if not _job_hidden_by_feedback(facts, job)
        )
        facts["latest_search_query"] = result.query
        facts["recommendations"] = [asdict(job) for job in visible_jobs]
        thread.case_facts = facts
        count = len(visible_jobs)
        content = (
            "No current jobs matched this search. The source was reached successfully; "
            "you can refine the role or constraints."
            if result.valid_empty
            else f"I found {count} current, source-backed job matches. Review the "
            "posting evidence below before shortlisting a target."
        )
        return ModelReply(content=content, model_name="job-discovery"), {
            "operation": "job_search",
            "result_count": count,
            "candidate_count": result.candidate_count,
            "visible_candidate_count": result.visible_candidate_count,
            "truncated": result.truncated,
            "valid_empty": result.valid_empty,
        }

    def _build_candidate_profile(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        command_run: RecruitmentRun,
    ) -> tuple[ModelReply, dict]:
        if self._candidate_profiler_factory is None:
            raise InvalidCommand("candidate profile capability is not configured")
        from resume_document import SCHEMA_VERSION, create_resume_document

        document = resume.resume_structured
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            document = create_resume_document(resume.resume_text)
            resume.resume_structured = document
            self._db.commit()
        elif document.get("raw_text") != resume.resume_text:
            raise CandidateProfilingUnavailable(
                "saved resume structure does not match its immutable text",
                decision=classify_failure("checkpoint_mismatch"),
            )

        store = SQLAlchemyCandidateProfileStore(
            self._db,
            owner_id=owner_id,
            resume_version_id=resume.id,
            model_name=self._candidate_profiler_factory.model_name,
        )
        def publish_progress(progress: CandidateProfileProgress) -> None:
            status, summary, detail = candidate_profile_progress_event(progress)
            event = self._event(
                thread,
                command_run,
                event_type="candidate_profile",
                status=status,
                summary=summary,
                detail=detail,
                team_member="candidate_profiler",
            )
            self._db.commit()
            self._activity_publisher.publish(self._activity(event))

        profiler = self._candidate_profiler_factory.create(store, publish_progress)
        try:
            run = profiler.profile(document)
        except CandidateProfileTransportError as error:
            artifact = store.fail(
                error.checkpoint_id,
                {
                    "failure_type": "transient",
                    "failure_code": error.failure_code,
                    "cause_type": error.cause_type,
                    "failed_scope_id": error.scope_id,
                    "attempt": error.attempt,
                    "completed_scope_ids": list(error.completed_scope_ids),
                    "recovery": "Resume the candidate profile command.",
                },
            )
            facts = dict(thread.case_facts)
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = artifact.status
            thread.case_facts = facts
            self._merge_run_metrics(
                command_run,
                store.execution_metrics(error.checkpoint_id),
                semantic_limit=config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
            )
            raise CandidateProfilingUnavailable(
                "candidate profile model transport failed",
                decision=classify_failure(error.failure_code),
            ) from error
        except CandidateProfileValidationError as error:
            failure_code = (
                "information_absent"
                if error.validation_code == "profile:empty"
                else "semantic_fixable"
            )
            artifact = store.fail(
                error.checkpoint_id,
                {
                    "failure_type": "validation",
                    "failure_code": failure_code,
                    "validation_code": error.validation_code,
                    "completed_scope_ids": list(error.completed_scope_ids),
                    "recovery": "Correct the failed structured scope before resuming.",
                },
            )
            facts = dict(thread.case_facts)
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = artifact.status
            thread.case_facts = facts
            self._merge_run_metrics(
                command_run,
                store.execution_metrics(error.checkpoint_id),
                semantic_limit=config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
            )
            raise CandidateProfilingUnavailable(
                "candidate profile failed semantic validation",
                decision=classify_failure(failure_code),
            ) from error
        except CandidateProfileCheckpointMismatch as error:
            raise CandidateProfilingUnavailable(
                "candidate profile checkpoint no longer matches the configured "
                "prompt, model, decomposition, or execution policy version",
                decision=classify_failure("checkpoint_mismatch"),
            ) from error

        current_metrics = store.execution_metrics(run.checkpoint_id)
        store.merge_execution_metrics(run.checkpoint_id, {
            "logical_run_id": run.checkpoint_id,
            "trace_key": command_run.trace_key,
            "stage": "candidate_profile",
            "model_call_count": 0 if current_metrics else run.model_call_count,
            "checkpoint_hit_count": 0 if current_metrics else run.checkpoint_hit_count,
            "input_tokens": 0 if current_metrics else int(run.input_tokens or 0),
            "output_tokens": 0 if current_metrics else int(run.output_tokens or 0),
            "validation_codes": [] if current_metrics else list(run.validation_codes),
            "models": [] if current_metrics else [run.model_name],
            "attempts": [],
            "terminal_status": "completed",
        })
        self._merge_run_metrics(
            command_run,
            store.execution_metrics(run.checkpoint_id),
            semantic_limit=config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
        )
        artifact = store.complete(run.checkpoint_id, run.profile, run.evaluation)
        facts = dict(thread.case_facts)
        facts["candidate_profile_artifact_id"] = artifact.id
        facts["candidate_profile_status"] = artifact.status
        thread.case_facts = facts
        thread.workflow_state = "profile_ready"
        return ModelReply(
            content=(
                f"Built a role-neutral evidence profile with {len(run.profile.fields)} "
                "source-backed fields. It can now be reused for job exploration and assessment."
            ),
            model_name=run.model_name,
        ), {
            "operation": "build_candidate_profile",
            "artifact_id": artifact.id,
            "field_count": len(run.profile.fields),
            "scope_count": run.scope_count,
            "model_call_count": run.model_call_count,
            "checkpoint_hit_count": run.checkpoint_hit_count,
            "attempt_count": run.attempt_count,
            "validation_codes": list(run.validation_codes),
        }

    def _shortlist_job(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        command: ShortlistJob,
    ) -> tuple[ModelReply, dict]:
        job = self._known_job(thread, command.job_id)
        facts = dict(thread.case_facts)
        shortlist = list(facts.get("shortlisted_jobs", []))
        if not any(int(item.get("job_id", -1)) == job.job_id for item in shortlist):
            shortlist.append(asdict(job))
        facts["shortlisted_jobs"] = shortlist
        facts.pop("shortlisted_job_ids", None)
        tracked = self._ensure_application(owner_id, thread, resume, job, selected=False)
        tracked_job_ids = dict(facts.get("tracked_job_ids") or {})
        tracked_job_ids[str(job.job_id)] = tracked.id
        facts["tracked_job_ids"] = tracked_job_ids
        thread.case_facts = facts
        return ModelReply(
            content=f"Shortlisted {job.title} at {job.company}.",
            model_name="deterministic-workflow",
        ), {
            "operation": "shortlist_job",
            "shortlist_count": len(shortlist),
            "tracked_job_id": tracked.id,
        }

    def _select_target(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run_record: RecruitmentRun,
        command: SelectTargetJob,
    ) -> tuple[ModelReply, dict]:
        job = self._known_job(thread, command.job_id)
        candidate_profile = self._completed_candidate_profile(thread, resume)
        comparable_jobs: tuple[JobSnapshot, ...] = ()
        profile_started = time.perf_counter()
        try:
            with self._telemetry.operation(
                "role_success.profile",
                {
                    "attempt": FIRST_ATTEMPT,
                    "logical_run_id": run_record.id,
                    "trace_key": run_record.trace_key,
                    "stage": "role_success_profile",
                    "target_source_type": "persisted_job_snapshot",
                    "comparable_job_count": len(comparable_jobs),
                    "candidate_profile_version": candidate_profile.profile_version,
                    "candidate_profile_field_count": len(candidate_profile.fields),
                },
            ) as profile_span:
                run = self._role_profiler.profile(
                    candidate_profile,
                    job,
                    comparable_jobs,
                )
                profile_span.set_attribute("model", run.model_name)
                profile_span.set_attribute("attempt_count", run.attempt_count)
                profile_span.set_attribute("generator_attempt_count", run.generator_attempt_count)
                profile_span.set_attribute("assessor_attempt_count", run.assessor_attempt_count)
                if run.generator_model_name:
                    profile_span.set_attribute("generator_model", run.generator_model_name)
                if run.assessor_model_name:
                    profile_span.set_attribute("assessor_model", run.assessor_model_name)
                profile_span.set_attribute("validation_codes", list(run.validation_codes))
                profile_span.set_attribute("criterion_count", len(run.profile.criteria))
                profile_span.set_attribute(
                    "taxonomy_match_quality",
                    run.profile.source_coverage.taxonomy_match_quality,
                )
                if run.input_tokens is not None:
                    profile_span.set_attribute("input_tokens", run.input_tokens)
                if run.output_tokens is not None:
                    profile_span.set_attribute("output_tokens", run.output_tokens)
        except (RoleProfileValidationError, RoleEvidenceAssessmentError) as error:
            raise RoleProfilingUnavailable(
                "role success profile failed semantic validation",
                decision=classify_failure("semantic_fixable"),
            ) from error
        except Exception as error:
            raise RoleProfilingUnavailable(
                f"role success profiling unavailable: {type(error).__name__}",
                decision=classify_exception(error),
            ) from error
        facts = dict(thread.case_facts)
        shortlist = list(facts.get("shortlisted_jobs", []))
        if not any(int(item.get("job_id", -1)) == job.job_id for item in shortlist):
            shortlist.append(asdict(job))
        facts["shortlisted_jobs"] = shortlist
        facts.pop("shortlisted_job_ids", None)
        facts["selected_target"] = asdict(job)
        facts["role_success_profile"] = asdict(run.profile)
        role_attempts = []
        if run.generator_attempt_count:
            role_attempts.append({
                "stage": "role_definition",
                "team_member": "role_profiler",
                "model": run.generator_model_name or run.model_name,
                "attempt_count": run.generator_attempt_count,
                "attempt_limit": config.ROLE_DEFINITION_VALIDATION_ATTEMPTS,
                "status": "success",
            })
        if run.assessor_attempt_count:
            role_attempts.append({
                "stage": "role_evidence",
                "team_member": "role_evidence_assessor",
                "model": run.assessor_model_name or run.model_name,
                "attempt_count": run.assessor_attempt_count,
                "attempt_limit": role_evidence_attempt_limit(len(run.profile.criteria)),
                "status": "success",
            })
        if not role_attempts:
            role_attempts.append({
                "stage": "role_success_profile",
                "team_member": "role_profiler",
                "model": run.model_name,
                "attempt_count": run.attempt_count,
                "attempt_limit": SEMANTIC_ATTEMPT_LIMITS["select_target_job"],
                "status": "success",
            })
        facts["role_success_metrics"] = {
            "logical_run_id": run_record.id,
            "trace_key": run_record.trace_key,
            "stage": "role_success_profile",
            "model_call_count": run.attempt_count,
            "checkpoint_hit_count": 0,
            "input_tokens": int(run.input_tokens or 0),
            "output_tokens": int(run.output_tokens or 0),
            "latency_ms": round((time.perf_counter() - profile_started) * 1000, 3),
            "validation_codes": list(run.validation_codes),
            "models": list(dict.fromkeys(filter(None, (
                run.generator_model_name,
                run.assessor_model_name,
                run.model_name,
            )))),
            "attempts": role_attempts,
            "terminal_status": "completed",
        }
        self._merge_run_metrics(
            run_record,
            facts["role_success_metrics"],
            semantic_limit=SEMANTIC_ATTEMPT_LIMITS["select_target_job"],
        )
        tracked = self._ensure_application(owner_id, thread, resume, job, selected=True)
        tracked_job_ids = dict(facts.get("tracked_job_ids") or {})
        tracked_job_ids[str(job.job_id)] = tracked.id
        facts["tracked_job_ids"] = tracked_job_ids
        thread.case_facts = facts
        thread.workflow_state = "target_selected"
        alignment_counts: dict[str, int] = {}
        for item in run.profile.candidate_evidence:
            alignment_counts[item.alignment] = alignment_counts.get(item.alignment, 0) + 1
        question = run.profile.clarification_question
        content = (
            f"Selected {job.title} at {job.company} as the target and built a "
            f"source-backed success profile with {len(run.profile.criteria)} criteria. "
            "The saved posting snapshot remains available if the live source changes."
        )
        if question:
            content += f"\n\nFocused clarification: {question}"
        return ModelReply(content=content, model_name=run.model_name), {
            "operation": "select_target",
            "target_selected": True,
            "criterion_count": len(run.profile.criteria),
            "alignment_counts": alignment_counts,
            "taxonomy_match_quality": run.profile.source_coverage.taxonomy_match_quality,
            "source_count": len(run.profile.sources),
            "attempt_count": run.attempt_count,
            "generator_attempt_count": run.generator_attempt_count,
            "assessor_attempt_count": run.assessor_attempt_count,
            "validation_codes": list(run.validation_codes),
            "candidate_profile_version": candidate_profile.profile_version,
            "candidate_profile_field_count": len(candidate_profile.fields),
            "tracked_job_id": tracked.id,
        }

    def _ensure_application(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        job: JobSnapshot,
        *,
        selected: bool,
    ) -> TrackedJob:
        user = self._db.get(User, owner_id)
        if user is None:
            raise InvalidCommand("application owner was not found")
        rationale = next(
            (
                item
                for item in thread.case_facts.get("match_rationales", [])
                if isinstance(item, dict) and int(item.get("job_id", -1)) == job.job_id
            ),
            None,
        )
        tracked_job_id = (thread.case_facts.get("tracked_job_ids") or {}).get(str(job.job_id))
        return ensure_recruitment_application(
            self._db,
            user,
            TrackedJobCreate(
                company=job.company,
                role=job.title,
                status="saved",
                source=job.source.source,
                source_url=job.source.url,
                job_description=job.description,
                scraped_job_id=job.job_id,
                resume_version_id=resume.id,
            ),
            thread_id=thread.id,
            source_job_id=job.job_id,
            posting_snapshot=asdict(job),
            fit_evidence=rationale,
            selected=selected,
            existing_tracked_job_id=int(tracked_job_id) if tracked_job_id is not None else None,
        )

    def _hide_job(
        self,
        thread: RecruitmentThread,
        command: HideJob,
    ) -> tuple[ModelReply, dict]:
        job = self._known_job(thread, command.job_id)
        facts = dict(thread.case_facts)
        if any(
            isinstance(item, dict) and int(item.get("job_id", -1)) == job.job_id
            for item in facts.get("shortlisted_jobs", [])
        ) or int((facts.get("selected_target") or {}).get("job_id", -1)) == job.job_id:
            raise InvalidCommand("a shortlisted or selected role must be managed from its application workspace")

        normalized_company = job.company.strip().casefold()
        def hidden(item: dict) -> bool:
            if command.scope == "role":
                return int(item.get("job_id", -1)) == job.job_id
            return str(item.get("company") or "").strip().casefold() == normalized_company

        removed_job_ids = {
            int(item.get("job_id", -1))
            for item in facts.get("recommendations", [])
            if isinstance(item, dict) and hidden(item)
        }
        facts["recommendations"] = [
            item
            for item in facts.get("recommendations", [])
            if not (isinstance(item, dict) and hidden(item))
        ]
        facts["match_rationales"] = [
            item
            for item in facts.get("match_rationales", [])
            if not isinstance(item, dict) or int(item.get("job_id", -1)) not in removed_job_ids
        ]
        target = str(job.job_id) if command.scope == "role" else normalized_company
        feedback = [
            item
            for item in facts.get("job_feedback", [])
            if not (
                isinstance(item, dict)
                and item.get("scope") == command.scope
                and item.get("target") == target
            )
        ]
        feedback.append({
            "scope": command.scope,
            "target": target,
            "reason": command.reason.strip(),
            "job": asdict(job),
            "recorded_at": _utcnow().isoformat(),
        })
        facts["job_feedback"] = feedback[-MAX_JOB_FEEDBACK_SIGNALS:]
        thread.case_facts = facts
        subject = job.company if command.scope == "company" else f"{job.title} at {job.company}"
        return ModelReply(
            content=f"Hidden {subject} from this conversation. I recorded it as your feedback, not as a universal relevance rule.",
            model_name="deterministic-workflow",
        ), {
            "operation": "hide_job",
            "scope": command.scope,
            "hidden_result_count": len(removed_job_ids),
        }

    def _target_assessment_request(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        trace_key_value: str,
    ) -> TargetAssessmentRequest:
        from resume_document import create_resume_document

        facts = thread.case_facts
        return TargetAssessmentRequest(
            candidate_profile=self._completed_candidate_profile(thread, resume),
            role_profile=self._role_profile_from_dict(facts["role_success_profile"]),
            target_job=self._job_from_dict(facts["selected_target"]),
            trace_key=trace_key_value,
            resume_document=create_resume_document(resume.resume_text),
            confirmed_evidence=self._confirmed_evidence_facts(facts),
        )

    def _assess_target(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
    ) -> tuple[ModelReply, dict]:
        if self._target_assessment_runner is None:
            raise InvalidCommand("target assessment capability is not configured")

        facts = dict(thread.case_facts)
        if not isinstance(facts.get("selected_target"), dict):
            raise InvalidCommand("select a target job before running its assessment")
        if not isinstance(facts.get("role_success_profile"), dict):
            raise InvalidCommand("build the role success profile before running its assessment")
        candidate_profile_artifact_id = str(facts["candidate_profile_artifact_id"])
        request = self._target_assessment_request(thread, resume, run.trace_key)
        target_snapshot_sha256 = hashlib.sha256(
            json.dumps(asdict(request.target_job), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        artifact = TargetAssessmentArtifact(
            id=str(uuid.uuid4()),
            user_id=owner_id,
            thread_id=thread.id,
            run_id=run.id,
            resume_version_id=resume.id,
            candidate_profile_artifact_id=candidate_profile_artifact_id,
            target_job_id=request.target_job.job_id,
            target_snapshot_sha256=target_snapshot_sha256,
            status="running",
            specialist_runs=[],
            synthesis="",
            execution_policy=target_assessment_execution_policy(),
            execution_metrics={
                "logical_run_id": run.id,
                "trace_key": run.trace_key,
                "stage": "target_assessment",
            },
        )
        self._db.add(artifact)
        facts["target_assessment_artifact_id"] = artifact.id
        facts["target_assessment_status"] = "running"
        thread.case_facts = facts
        thread.workflow_state = "assessing"
        self._db.commit()

        return self._consume_target_assessment_updates(
            owner_id, thread, resume, run, artifact, self._target_assessment_runner.run(request)
        )

    def _answer_assessment_question(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
        answer: str,
    ) -> tuple[ModelReply, dict]:
        if self._target_assessment_runner is None:
            raise InvalidCommand("target assessment capability is not configured")
        if thread.workflow_state != "awaiting_candidate_answer":
            raise InvalidCommand("there is no pending assessment question to answer")

        facts = dict(thread.case_facts)
        artifact_id = facts.get("target_assessment_artifact_id")
        pause_token = facts.get("target_assessment_pause_token")
        if not artifact_id or not pause_token:
            raise InvalidCommand("no paused assessment found for this thread")
        artifact = (
            self._db.query(TargetAssessmentArtifact)
            .filter(
                TargetAssessmentArtifact.id == artifact_id,
                TargetAssessmentArtifact.user_id == owner_id,
            )
            .first()
        )
        if artifact is None:
            raise ThreadNotFound(f"assessment artifact {artifact_id} not found")

        latest_user = next(
            (message for message in reversed(self._messages(thread.id)) if message.role == "user"),
            None,
        )
        if latest_user is None:
            raise InvalidCommand("assessment answer has no user message")
        confirmed = confirmed_evidence_fact(
            answer,
            source_run_id=latest_user.run_id,
            source_message_id=latest_user.message_id,
        )
        self._merge_confirmed_evidence(thread, [confirmed])
        request = self._target_assessment_request(thread, resume, run.trace_key)
        thread.workflow_state = "assessing"
        self._db.commit()

        updates = self._target_assessment_runner.resume(
            str(pause_token),
            (
                f"{answer}\n\n[System: this candidate-confirmed answer is stored as "
                f"evidence ID {confirmed.evidence_id}. Cite that ID in "
                "propose_resume_edit if the answer supports a rewrite.]"
            ),
            request,
            list(artifact.pending_specialist_runs or []),
            artifact.pending_synthesis or "",
            list(artifact.pending_proposed_edits or []),
            ask_candidate_call_id=facts.get("target_assessment_pause_call_id") or None,
        )
        return self._consume_target_assessment_updates(owner_id, thread, resume, run, artifact, updates)

    def _consume_target_assessment_updates(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
        artifact: TargetAssessmentArtifact,
        updates,
    ) -> tuple[ModelReply, dict]:
        result: TargetAssessmentResult | None = None
        last_progress_status: str | None = None
        pending_question = ""
        pause_detail: dict = {}
        started_calls: dict[str, float] = {}
        try:
            for update in updates:
                if isinstance(update, TargetAssessmentProgress):
                    last_progress_status = update.status
                    if update.status == "paused":
                        pending_question = str((update.detail or {}).get("question") or "")
                        pause_detail = update.detail or {}
                    detail = update.detail or {}
                    call_id = str(detail.get("tool_call_id") or "")
                    kind = "tool_result" if detail.get("stage") == "result" else "tool_call"
                    args = {"query": detail["query"]} if isinstance(detail.get("query"), str) else None
                    parent_id, duration_ms, attributes = _trace_event_fields(
                        kind=kind,
                        call_id=call_id,
                        run_id=run.id,
                        detail=detail,
                        started_calls=started_calls,
                        args=args,
                    )
                    progress_event = self._event(
                        thread,
                        run,
                        event_type="assessment",
                        status=update.status,
                        summary=update.summary,
                        detail=detail,
                        team_member=update.team_member,
                        parent_id=parent_id,
                        duration_ms=duration_ms,
                        attributes=attributes,
                    )
                    self._db.commit()
                    self._activity_publisher.publish(self._activity(progress_event))
                elif isinstance(update, TargetAssessmentResult):
                    if result is not None:
                        raise ValueError("target assessment runner returned more than one result")
                    result = update
                else:
                    raise TypeError("target assessment runner returned an unsupported update")
        except Exception as error:
            decision = classify_exception(error)
            artifact.status = "failed"
            artifact.error = {
                "failure_type": decision.failure_type,
                "failure_code": decision.failure_code,
                "error_type": type(error).__name__,
                "retryable": decision.retryable,
                "recovery_action": decision.recovery_action,
            }
            facts = dict(thread.case_facts)
            facts["target_assessment_status"] = artifact.status
            thread.case_facts = facts
            artifact.updated_at = _utcnow()
            self._db.commit()
            raise TargetAssessmentUnavailable(
                f"target assessment unavailable: {type(error).__name__}",
                decision=decision,
            ) from error

        if result is None:
            if last_progress_status == "paused":
                artifact.status = "paused"
                artifact.execution_metrics = merge_execution_metrics(
                    artifact.execution_metrics,
                    {
                        **(pause_detail.get("execution_metrics") or {}),
                        "logical_run_id": run.id,
                        "trace_key": run.trace_key,
                    },
                )
                self._merge_run_metrics(
                    run,
                    artifact.execution_metrics,
                    semantic_limit=config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                )
                artifact.pending_specialist_runs = pause_detail.get("specialist_runs") or []
                artifact.pending_synthesis = str(pause_detail.get("synthesis") or "")
                artifact.pending_proposed_edits = pause_detail.get("proposed_edits") or []
                artifact.updated_at = _utcnow()
                facts = dict(thread.case_facts)
                facts["target_assessment_status"] = "paused"
                facts["target_assessment_pause_token"] = str(pause_detail.get("pause_token") or "")
                facts["target_assessment_pause_call_id"] = str(pause_detail.get("ask_candidate_call_id") or "")
                thread.case_facts = facts
                thread.workflow_state = "awaiting_candidate_answer"
                self._db.commit()
                return ModelReply(
                    content=pending_question,
                    model_name="open-agent-recruitment-team",
                ), {}
            artifact.status = "failed"
            artifact.error = {
                "failure_type": "business",
                "failure_code": "missing_terminal_result",
                "error_type": "MissingTerminalResult",
                "retryable": False,
                "recovery_action": "operator_review",
            }
            facts = dict(thread.case_facts)
            facts["target_assessment_status"] = artifact.status
            thread.case_facts = facts
            artifact.updated_at = _utcnow()
            self._db.commit()
            raise TargetAssessmentUnavailable(
                "target assessment runner returned no terminal result",
                decision=classify_failure("missing_terminal_result"),
            )
        effective_status = result.status
        effective_error = result.error
        if result.status == "completed" and not result.synthesis.strip():
            effective_status = "failed"
            effective_error = {
                "failure_type": "validation",
                "failure_code": "structured_output_invalid",
                "error_type": "EmptySynthesis",
                "retryable": False,
                "recovery_action": "attempt_budget_exhausted",
            }
        terminal_decision = None
        if effective_status != "completed":
            failure_code = (
                "quality_gate_blocked"
                if effective_status == "quality_blocked"
                else normalize_failure_code(
                    str(
                        (effective_error or {}).get("failure_code")
                        or (effective_error or {}).get("failure_type")
                        or ""
                    )
                )
            )
            terminal_decision = classify_failure(failure_code)
            effective_error = {
                **(effective_error or {}),
                "failure_type": terminal_decision.failure_type,
                "failure_code": terminal_decision.failure_code,
                "retryable": terminal_decision.retryable,
                "recovery_action": terminal_decision.recovery_action,
            }
        artifact.status = effective_status
        artifact.specialist_runs = list(result.specialist_runs) if effective_status == "completed" else []
        artifact.synthesis = result.synthesis if effective_status == "completed" else ""
        artifact.pending_specialist_runs = None
        artifact.pending_synthesis = None
        artifact.pending_proposed_edits = None
        artifact.judge = result.judge
        artifact.correction = result.correction
        artifact.error = effective_error
        artifact.execution_policy = result.execution_policy
        artifact.execution_metrics = merge_execution_metrics(
            artifact.execution_metrics,
            {
                **result.execution_metrics,
                "logical_run_id": run.id,
                "trace_key": run.trace_key,
            },
        )
        self._merge_run_metrics(
            run,
            artifact.execution_metrics,
            semantic_limit=config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
        )
        artifact.updated_at = _utcnow()
        facts = dict(thread.case_facts)
        facts["target_assessment_status"] = effective_status
        facts.pop("target_assessment_pause_token", None)
        facts.pop("target_assessment_pause_call_id", None)
        thread.case_facts = facts
        self._db.commit()

        if effective_status != "completed":
            if effective_status == "quality_blocked":
                thread.workflow_state = "quality_blocked"
                self._db.commit()
            raise TargetAssessmentUnavailable(
                "target assessment did not pass its independent quality gate",
                decision=terminal_decision or classify_failure("unclassified_failure"),
            )
        for edit in result.proposed_edits:
            self._db.add(
                ProposedResumeEdit(
                    id=str(uuid.uuid4()),
                    user_id=owner_id,
                    thread_id=thread.id,
                    run_id=run.id,
                    resume_version_id=resume.id,
                    block_id=edit["block_id"],
                    section_key=edit.get("section_key", ""),
                    entry_id=edit.get("entry_id", ""),
                    original=edit["original"],
                    rewrite=edit["rewrite"],
                    evidence_ids=edit.get("evidence_ids") or None,
                    document_revision=edit["document_revision"],
                    status="pending",
                )
            )
        thread.workflow_state = "assessment_ready"
        return ModelReply(
            content=artifact.synthesis,
            model_name="bounded-recruitment-team",
        ), {
            "operation": "assess_target_job",
            "assessment_artifact_id": artifact.id,
            "specialist_run_count": len(result.specialist_runs),
            "judge_status": (result.judge or {}).get("verdict", "completed"),
            "correction_attempted": bool((result.correction or {}).get("attempted")),
            "execution_policy": result.execution_policy,
        }

    def _completed_candidate_profile(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
    ) -> CandidateEvidenceProfile:
        profile = self._find_completed_candidate_profile(thread, resume)
        if profile is not None:
            return profile
        raise InvalidCommand("build the candidate evidence profile before selecting a target job")

    def _find_completed_candidate_profile(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
    ) -> CandidateEvidenceProfile | None:
        artifact_id = thread.case_facts.get("candidate_profile_artifact_id")
        artifacts = (
            self._db.query(CandidateProfileArtifact)
            .filter(
                CandidateProfileArtifact.user_id == thread.user_id,
                CandidateProfileArtifact.resume_version_id == resume.id,
                CandidateProfileArtifact.status == "completed",
            )
            .order_by(CandidateProfileArtifact.updated_at.desc())
            .all()
        )
        artifact = _current_candidate_profile_artifact(artifacts)
        if artifact is None or artifact.profile is None:
            return None
        if artifact_id != artifact.id or thread.case_facts.get("candidate_profile_status") != "completed":
            facts = dict(thread.case_facts or {})
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = "completed"
            thread.case_facts = facts
        return self._candidate_profile_from_dict(artifact.profile)

    def snapshot(self, owner_id: int, thread_id: str) -> ThreadSnapshot:
        thread = self._owned_thread(owner_id, thread_id)
        facts = thread.case_facts
        return ThreadSnapshot(
            thread_id=thread.id,
            title=self._thread_title(thread),
            status=thread.status,
            workflow_state=thread.workflow_state,
            case_facts=CaseFacts(
                resume_version_id=int(facts["resume_version_id"]),
                resume_label=str(facts["resume_label"]),
                resume_sha256=str(facts["resume_sha256"]),
                latest_search_query=str(facts.get("latest_search_query") or ""),
                recommendations=tuple(self._job_from_dict(item) for item in facts.get("recommendations", [])),
                match_rationales=tuple(
                    item for item in facts.get("match_rationales", []) if isinstance(item, dict)
                ),
                shortlisted_jobs=tuple(self._job_from_dict(item) for item in facts.get("shortlisted_jobs", [])),
                shortlisted_job_ids=tuple(
                    dict.fromkeys(
                        (
                            *(self._job_from_dict(item).job_id for item in facts.get("shortlisted_jobs", [])),
                            *(int(job_id) for job_id in facts.get("shortlisted_job_ids", [])),
                        )
                    )
                ),
                selected_target=(
                    self._job_from_dict(facts["selected_target"])
                    if isinstance(facts.get("selected_target"), dict)
                    else None
                ),
                tracked_job_ids={
                    str(job_id): int(tracked_id)
                    for job_id, tracked_id in (facts.get("tracked_job_ids") or {}).items()
                },
                job_feedback=tuple(
                    item for item in facts.get("job_feedback", []) if isinstance(item, dict)
                ),
                role_success_profile=(
                    self._role_profile_from_dict(facts["role_success_profile"])
                    if isinstance(facts.get("role_success_profile"), dict)
                    else None
                ),
                role_success_metrics=(
                    dict(facts["role_success_metrics"])
                    if isinstance(facts.get("role_success_metrics"), dict)
                    else None
                ),
                preferences=self._preference_facts(facts),
                confirmed_evidence=self._confirmed_evidence_facts(facts),
                plan=self._plan_steps(facts),
                candidate_profile_artifact_id=(
                    str(facts["candidate_profile_artifact_id"]) if facts.get("candidate_profile_artifact_id") else None
                ),
                candidate_profile_status=str(facts.get("candidate_profile_status") or "not_started"),
                target_assessment_artifact_id=(
                    str(facts["target_assessment_artifact_id"]) if facts.get("target_assessment_artifact_id") else None
                ),
                target_assessment_status=str(facts.get("target_assessment_status") or "not_started"),
            ),
            messages=self._messages(thread.id),
            last_event_sequence=thread.next_event_sequence - 1,
        )

    def candidate_profile(
        self,
        owner_id: int,
        thread_id: str,
    ) -> CandidateProfileArtifactSnapshot | None:
        thread = self._owned_thread(owner_id, thread_id)
        artifacts = (
            self._db.query(CandidateProfileArtifact)
            .filter(
                CandidateProfileArtifact.user_id == owner_id,
                CandidateProfileArtifact.resume_version_id == thread.resume_version_id,
                CandidateProfileArtifact.status == "completed",
            )
            .order_by(CandidateProfileArtifact.updated_at.desc())
            .all()
        )
        artifact = _current_candidate_profile_artifact(artifacts)
        if artifact is None:
            return None
        return CandidateProfileArtifactSnapshot(
            artifact_id=artifact.id,
            resume_version_id=artifact.resume_version_id,
            checkpoint_id=artifact.checkpoint_id,
            prompt_version=artifact.prompt_version,
            decomposition_version=artifact.decomposition_version,
            model_name=artifact.model_name,
            execution_policy=artifact.execution_policy,
            status=artifact.status,
            completed_scope_ids=tuple(
                scope_id
                for scope_id in artifact.scopes
                if scope_id != RETRY_FEEDBACK_SCOPE_KEY and not scope_id.startswith("__")
            ),
            execution_metrics=artifact.execution_metrics or {},
            profile=artifact.profile,
            evaluation=artifact.evaluation,
            error=artifact.error,
            updated_at=artifact.updated_at,
        )

    def target_assessment(
        self,
        owner_id: int,
        thread_id: str,
    ) -> TargetAssessmentArtifactSnapshot | None:
        thread = self._owned_thread(owner_id, thread_id)
        artifact_id = thread.case_facts.get("target_assessment_artifact_id")
        if not artifact_id:
            return None
        artifact = (
            self._db.query(TargetAssessmentArtifact)
            .filter(
                TargetAssessmentArtifact.id == str(artifact_id),
                TargetAssessmentArtifact.user_id == owner_id,
                TargetAssessmentArtifact.thread_id == thread.id,
            )
            .first()
        )
        if artifact is None:
            raise InvalidCommand("target assessment artifact reference is invalid")
        # A paused run parks completed specialist work in pending_specialist_runs,
        # so reading specialist_runs alone showed a candidate nothing while their
        # scored verdicts sat in the row. Pausing is the normal HITL state, not an
        # error, so surface what the specialists already reported.
        reported = list(artifact.specialist_runs or []) or list(
            artifact.pending_specialist_runs or []
        )
        return TargetAssessmentArtifactSnapshot(
            artifact_id=artifact.id,
            target_job_id=artifact.target_job_id,
            status=artifact.status,
            specialist_runs=tuple(reported),
            synthesis=artifact.synthesis,
            judge=artifact.judge,
            correction=artifact.correction,
            error=artifact.error,
            execution_policy=artifact.execution_policy,
            execution_metrics=artifact.execution_metrics or {},
            updated_at=artifact.updated_at,
        )

    def events(
        self,
        owner_id: int,
        thread_id: str,
        after_sequence: int,
    ) -> list[ActivityEvent]:
        self._owned_thread(owner_id, thread_id)
        records = (
            self._db.query(RecruitmentActivityEvent)
            .filter(
                RecruitmentActivityEvent.thread_id == thread_id,
                RecruitmentActivityEvent.sequence > after_sequence,
            )
            .order_by(RecruitmentActivityEvent.sequence)
            .all()
        )
        return [self._activity(item) for item in records]

    def threads(self, owner_id: int) -> list[ThreadSummary]:
        records = (
            self._db.query(RecruitmentThread)
            .filter(RecruitmentThread.user_id == owner_id)
            .order_by(RecruitmentThread.updated_at.desc(), RecruitmentThread.id)
            .all()
        )
        summaries: list[ThreadSummary] = []
        for thread in records:
            last_message = (
                self._db.query(RecruitmentMessage)
                .filter(RecruitmentMessage.thread_id == thread.id)
                .order_by(RecruitmentMessage.id.desc())
                .first()
            )
            summaries.append(
                ThreadSummary(
                    thread_id=thread.id,
                    title=self._thread_title(thread),
                    status=thread.status,
                    workflow_state=thread.workflow_state,
                    resume_version_id=thread.resume_version_id,
                    resume_label=str(thread.case_facts["resume_label"]),
                    last_message=last_message.content if last_message else None,
                    updated_at=thread.updated_at,
                )
            )
        return summaries

    @staticmethod
    def retention_contract() -> dict[str, str]:
        return dict(config.RECRUITMENT_RETENTION_NOTICE)

    @staticmethod
    def _thread_title(thread: RecruitmentThread) -> str:
        facts = thread.case_facts or {}
        return str(facts.get("title") or facts.get("resume_label") or "Recruitment conversation")

    def rename_thread(self, owner_id: int, thread_id: str, title: str) -> dict:
        thread = self._owned_thread(owner_id, thread_id)
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise InvalidCommand("conversation title is required")
        if len(normalized) > THREAD_TITLE_MAX_CHARS:
            raise InvalidCommand(f"conversation title cannot exceed {THREAD_TITLE_MAX_CHARS} characters")
        facts = dict(thread.case_facts or {})
        if facts.get("title") != normalized:
            facts["title"] = normalized
            thread.case_facts = facts
            self._db.commit()
        return {"thread_id": thread.id, "title": normalized, "status": thread.status}

    def archive_thread(self, owner_id: int, thread_id: str) -> dict:
        thread = self._owned_thread(owner_id, thread_id)
        if thread.status != ARCHIVED_THREAD_STATUS:
            thread.status = ARCHIVED_THREAD_STATUS
            self._db.commit()
        return {"thread_id": thread.id, "title": self._thread_title(thread), "status": thread.status}

    def restore_thread(self, owner_id: int, thread_id: str) -> dict:
        thread = self._owned_thread(owner_id, thread_id)
        if thread.status != ACTIVE_THREAD_STATUS:
            thread.status = ACTIVE_THREAD_STATUS
            self._db.commit()
        return {"thread_id": thread.id, "title": self._thread_title(thread), "status": thread.status}

    def delete_thread(
        self,
        owner_id: int,
        thread_id: str,
        idempotency_key: str,
        *,
        delete_checkpoints: Callable[[str], None] | None = None,
    ) -> dict:
        key = idempotency_key.strip()
        if not key:
            raise InvalidCommand("idempotency_key is required")
        previous = (
            self._db.query(RecruitmentThreadDeletionRequest)
            .filter(
                RecruitmentThreadDeletionRequest.user_id == owner_id,
                RecruitmentThreadDeletionRequest.idempotency_key == key,
            )
            .first()
        )
        if previous is not None:
            return dict(previous.result)

        thread = self._owned_thread(owner_id, thread_id)
        trace_keys = [
            str(value)
            for (value,) in self._db.query(RecruitmentRun.trace_key)
            .filter(RecruitmentRun.thread_id == thread.id)
            .all()
            if value
        ]
        assessment_ids = [
            str(value)
            for (value,) in self._db.query(TargetAssessmentArtifact.id)
            .filter(TargetAssessmentArtifact.thread_id == thread.id)
            .all()
        ]
        facts = thread.case_facts or {}
        checkpoint_tokens = [
            str(value)
            for value in {
                facts.get("coordinator_pause_token"),
                facts.get("target_assessment_pause_token"),
            }
            if value
        ]
        if delete_checkpoints is not None:
            for token in checkpoint_tokens:
                delete_checkpoints(token)

        result = {
            "thread_id": thread.id,
            "status": "deleted",
            "deletion_request_status": "requested",
            "trace_deletion_requests": len(trace_keys),
            "evaluation_deletion_requests": len(assessment_ids),
            "retention": self.retention_contract(),
        }
        self._db.add(
            RecruitmentThreadDeletionRequest(
                id=str(uuid.uuid4()),
                user_id=owner_id,
                thread_id=thread.id,
                idempotency_key=key,
                status="requested",
                targets={
                    "trace_keys": trace_keys,
                    "assessment_artifact_ids": assessment_ids,
                    "checkpoint_tokens": checkpoint_tokens,
                },
                result=result,
            )
        )
        self._db.delete(thread)
        with self._telemetry.operation(
            "delete_thread",
            {
                "owner_type": "user",
                "trace_request_count": len(trace_keys),
                "evaluation_request_count": len(assessment_ids),
            },
        ):
            self._db.commit()
        return result

    def _start_thread(
        self,
        owner_id: int,
        command: StartThread,
    ) -> tuple[RecruitmentThread, ResumeVersion]:
        resume = self._owned_resume(owner_id, command.resume_version_id)
        thread = RecruitmentThread(
            id=str(uuid.uuid4()),
            user_id=owner_id,
            resume_version_id=resume.id,
            case_facts={
                "resume_version_id": resume.id,
                "resume_label": resume.label,
                "resume_sha256": hashlib.sha256(resume.resume_text.encode()).hexdigest(),
            },
        )
        self._db.add(thread)
        self._db.flush()
        return thread, resume

    def proposed_edits(self, owner_id: int, thread_id: str) -> list[dict]:
        """Pending agent-drafted edits, newest run last, with applicability resolved.

        `stale` means the source resume no longer contains the text the edit was
        drafted against, so accepting it would silently do nothing.
        """
        thread = self._owned_thread(owner_id, thread_id)
        edits = (
            self._db.query(ProposedResumeEdit)
            .filter(
                ProposedResumeEdit.user_id == owner_id,
                ProposedResumeEdit.thread_id == thread.id,
                ProposedResumeEdit.status == "pending",
            )
            .order_by(ProposedResumeEdit.created_at)
            .all()
        )
        if not edits:
            return []
        from resume_document import create_resume_document

        resume_text = self._owned_resume(owner_id, thread.resume_version_id).resume_text or ""
        revision = create_resume_document(resume_text)["revision"]
        evidence_by_id = {
            fact.evidence_id: fact
            for fact in self._confirmed_evidence_facts(thread.case_facts)
        }
        return [
            {
                "id": edit.id,
                "block_id": edit.block_id,
                "section_key": edit.section_key,
                "entry_id": edit.entry_id,
                "original": edit.original,
                "rewrite": edit.rewrite,
                "evidence_refs": [
                    {
                        "evidence_id": evidence_id,
                        "evidence_quote": evidence_by_id[evidence_id].evidence_quote,
                    }
                    for evidence_id in (edit.evidence_ids or [])
                    if evidence_id in evidence_by_id
                ],
                "status": edit.status,
                "applicable": (
                    edit.document_revision == revision
                    and bool(edit.original)
                    and edit.original in resume_text
                ),
                "created_at": edit.created_at.isoformat() if edit.created_at else "",
            }
            for edit in edits
        ]

    def accept_proposed_edits(
        self,
        owner_id: int,
        thread_id: str,
        edit_ids: list[str] | None = None,
    ) -> dict:
        """Apply accepted edits into a NEW resume version.

        Never writes over the source version, so accepting is reversible and the
        candidate keeps the original. Edits whose original text no longer appears
        are marked stale rather than applied, so an accept-all can never silently
        drop a change without saying so.
        """
        thread = self._active_thread(owner_id, thread_id)
        query = self._db.query(ProposedResumeEdit).filter(
            ProposedResumeEdit.user_id == owner_id,
            ProposedResumeEdit.thread_id == thread.id,
            ProposedResumeEdit.status == "pending",
        )
        if edit_ids:
            query = query.filter(ProposedResumeEdit.id.in_(edit_ids))
        edits = query.order_by(ProposedResumeEdit.created_at).all()
        if not edits:
            raise InvalidCommand("no pending resume edits to accept")

        source = self._owned_resume(owner_id, thread.resume_version_id)
        text = source.resume_text or ""
        from resume_document import create_resume_document

        revision = create_resume_document(text)["revision"]
        applied: list[str] = []
        stale: list[str] = []
        for edit in edits:
            if edit.document_revision == revision and edit.original and edit.original in text:
                text = text.replace(edit.original, edit.rewrite, 1)
                edit.status = "accepted"
                applied.append(edit.id)
            else:
                edit.status = "stale"
                stale.append(edit.id)

        if not applied:
            self._db.commit()
            raise InvalidCommand(
                "every selected edit was drafted against resume text that has since changed"
            )

        target = (thread.case_facts or {}).get("selected_target") or {}
        job_title = str(target.get("title") or "")
        version = ResumeVersion(
            user_id=owner_id,
            label=f"Tailored for {job_title}" if job_title else "Recruitment team edits",
            source="recruitment_team",
            resume_text=text,
            job_id=target.get("job_id"),
            job_title=job_title,
            job_company=str(target.get("company") or ""),
            word_count=len(text.split()),
        )
        self._db.add(version)
        self._db.flush()
        thread.resume_version_id = version.id
        facts = dict(thread.case_facts or {})
        facts.update({
            "resume_version_id": version.id,
            "resume_label": version.label,
            "resume_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "candidate_profile_status": "not_started",
            "target_assessment_status": "not_started",
        })
        facts.pop("candidate_profile_artifact_id", None)
        facts.pop("target_assessment_artifact_id", None)
        thread.case_facts = facts
        self._db.commit()
        return {
            "resume_version_id": version.id,
            "label": version.label,
            "accepted_edit_ids": applied,
            "stale_edit_ids": stale,
        }

    def reject_proposed_edits(
        self,
        owner_id: int,
        thread_id: str,
        edit_ids: list[str],
    ) -> dict:
        thread = self._active_thread(owner_id, thread_id)
        edits = (
            self._db.query(ProposedResumeEdit)
            .filter(
                ProposedResumeEdit.user_id == owner_id,
                ProposedResumeEdit.thread_id == thread.id,
                ProposedResumeEdit.status == "pending",
                ProposedResumeEdit.id.in_(edit_ids),
            )
            .all()
        )
        if not edits:
            raise InvalidCommand("no matching pending resume edits")
        for edit in edits:
            edit.status = "rejected"
        self._db.commit()
        return {"rejected_edit_ids": [edit.id for edit in edits]}

    def _owned_thread(self, owner_id: int, thread_id: str) -> RecruitmentThread:
        thread = (
            self._db.query(RecruitmentThread)
            .filter(
                RecruitmentThread.id == thread_id,
                RecruitmentThread.user_id == owner_id,
            )
            .first()
        )
        if thread is None:
            raise ThreadNotFound("recruitment thread not found")
        return thread

    def _active_thread(self, owner_id: int, thread_id: str) -> RecruitmentThread:
        thread = self._owned_thread(owner_id, thread_id)
        if thread.status != ACTIVE_THREAD_STATUS:
            raise InvalidCommand("restore this archived conversation before continuing its workflow")
        return thread

    def _owned_resume(self, owner_id: int, resume_id: int) -> ResumeVersion:
        resume = (
            self._db.query(ResumeVersion)
            .filter(
                ResumeVersion.id == resume_id,
                ResumeVersion.user_id == owner_id,
                ResumeVersion.is_active.is_(True),
            )
            .first()
        )
        if resume is None:
            raise ResumeVersionNotFound("resume version not found")
        return resume

    def _known_job(
        self,
        thread: RecruitmentThread,
        job_id: int,
    ) -> JobSnapshot:
        jobs = (
            *thread.case_facts.get("recommendations", []),
            *thread.case_facts.get("shortlisted_jobs", []),
        )
        for item in jobs:
            if isinstance(item, dict) and int(item.get("job_id", -1)) == job_id:
                return self._job_from_dict(item)
        raise InvalidCommand("job was not returned or shortlisted by this thread")

    @staticmethod
    def _job_from_dict(item: dict) -> JobSnapshot:
        source = item.get("source") or {}
        return JobSnapshot(
            job_id=int(item["job_id"]),
            title=str(item.get("title") or ""),
            company=str(item.get("company") or ""),
            location=str(item.get("location") or ""),
            salary=str(item.get("salary") or ""),
            employment_type=str(item.get("employment_type") or ""),
            seniority=str(item.get("seniority") or ""),
            description=str(item.get("description") or ""),
            skills=tuple(str(skill) for skill in item.get("skills") or []),
            similarity_score=(
                float(item["similarity_score"]) if isinstance(item.get("similarity_score"), (int, float)) else None
            ),
            source=JobSource(
                source=str(source.get("source") or ""),
                url=str(source.get("url") or ""),
                source_posting_id=str(source.get("source_posting_id") or ""),
                posted_date=str(source.get("posted_date") or ""),
                closing_date=str(source.get("closing_date") or ""),
                scraped_at=str(source.get("scraped_at") or ""),
                availability=str(source.get("availability") or "unknown"),
                snapshot_sha256=str(source.get("snapshot_sha256") or ""),
            ),
            posting_variants=tuple(
                JobPostingVariant(
                    job_id=int(variant["job_id"]),
                    salary=str(variant.get("salary") or ""),
                    source=JobSource(**variant["source"]),
                )
                for variant in item.get("posting_variants") or []
            ),
            sector=str(item.get("sector") or ""),
            parsed_jd=(
                item.get("parsed_jd") if isinstance(item.get("parsed_jd"), dict) else None
            ),
            job_terms_preview=tuple(
                str(term) for term in item.get("job_terms_preview") or []
            ),
            salary_context=(
                item.get("salary_context")
                if isinstance(item.get("salary_context"), dict)
                else None
            ),
            fact_context_status=str(item.get("fact_context_status") or "unavailable"),
        )

    @staticmethod
    def _role_profile_from_dict(item: dict) -> RoleSuccessProfile:
        coverage = item["source_coverage"]
        return RoleSuccessProfile(
            profile_version=str(item["profile_version"]),
            target_job_id=int(item["target_job_id"]),
            sources=tuple(
                RoleSource(
                    source_id=str(source["source_id"]),
                    source_type=source["source_type"],
                    title=str(source["title"]),
                    url=str(source.get("url") or ""),
                    publication_date=str(source.get("publication_date") or ""),
                    evidence_strength=source["evidence_strength"],
                    evidence_fields=tuple(str(field) for field in source.get("evidence_fields") or []),
                )
                for source in item["sources"]
            ),
            criteria=tuple(
                RoleCriterion(
                    criterion_id=str(criterion["criterion_id"]),
                    category=criterion["category"],
                    requirement_level=criterion["requirement_level"],
                    statement=str(criterion["statement"]),
                    source_ids=tuple(str(value) for value in criterion["source_ids"]),
                    source_citations=tuple(
                        RoleCitation(
                            source_id=str(citation["source_id"]),
                            source_path=str(citation["source_path"]),
                            relevant_excerpt=str(citation["relevant_excerpt"]),
                        )
                        for citation in criterion.get("source_citations") or []
                    ),
                    alternative_group_id=(
                        str(criterion["alternative_group_id"]) if criterion.get("alternative_group_id") else None
                    ),
                )
                for criterion in item["criteria"]
            ),
            candidate_evidence=tuple(
                CandidateEvidenceMatch(
                    criterion_id=str(match["criterion_id"]),
                    alignment=match["alignment"],
                    resume_evidence_ids=tuple(str(value) for value in match["resume_evidence_ids"]),
                    explanation=str(match["explanation"]),
                    confidence=float(match["confidence"]),
                    confidence_basis=str(match["confidence_basis"]),
                    supported_strength=str(match.get("supported_strength") or ""),
                    remaining_gap=str(match.get("remaining_gap") or ""),
                    evidence_support_score=(
                        int(match["evidence_support_score"])
                        if match.get("evidence_support_score") is not None
                        else None
                    ),
                    score_reason=str(match.get("score_reason") or ""),
                    candidate_profile_field_ids=tuple(
                        str(value) for value in match.get("candidate_profile_field_ids") or []
                    ),
                )
                for match in item["candidate_evidence"]
            ),
            source_coverage=SourceCoverage(
                exact_job=bool(coverage["exact_job"]),
                comparable_job_count=int(coverage["comparable_job_count"]),
                occupation_source_count=int(coverage["occupation_source_count"]),
                taxonomy_match_quality=coverage["taxonomy_match_quality"],
                notes=tuple(str(note) for note in coverage["notes"]),
            ),
            clarification_question=(
                str(item["clarification_question"]) if item.get("clarification_question") else None
            ),
            validation_notes=tuple(str(note) for note in item.get("validation_notes") or []),
            cited_resume_evidence=tuple(
                ResumeEvidenceRecord(
                    evidence_id=str(record["evidence_id"]),
                    kind=str(record.get("kind") or ""),
                    text=str(record["text"]),
                    source_locator=str(record.get("source_locator") or ""),
                    section_key=str(record.get("section_key") or ""),
                )
                for record in item.get("cited_resume_evidence") or []
            ),
            policy_constraints=tuple(
                PolicyConstraint(
                    constraint_id=str(constraint["constraint_id"]),
                    statement=str(constraint["statement"]),
                    source_id=str(constraint["source_id"]),
                )
                for constraint in item.get("policy_constraints") or []
            ),
            assessment_disposition=item.get("assessment_disposition"),
            evidence_assessment_prompt_version=str(item.get("evidence_assessment_prompt_version") or ""),
            evidence_assessment_model=str(item.get("evidence_assessment_model") or ""),
            evidence_assessment_attempt_count=int(item.get("evidence_assessment_attempt_count") or 0),
        )

    @staticmethod
    def _candidate_profile_from_dict(item: dict) -> CandidateEvidenceProfile:
        return candidate_profile_from_dict(item)

    def _messages(self, thread_id: str) -> list[Message]:
        records = (
            self._db.query(RecruitmentMessage)
            .filter(RecruitmentMessage.thread_id == thread_id)
            .order_by(RecruitmentMessage.id)
            .all()
        )
        return [
            Message(
                message_id=item.id,
                role=item.role,
                content=item.content,
                run_id=item.run_id,
                created_at=item.created_at,
            )
            for item in records
        ]

    @staticmethod
    def _preference_facts(facts: dict) -> tuple[PreferenceFact, ...]:
        return tuple(
            PreferenceFact(
                field=item["field"],
                value=str(item["value"]),
                evidence_quote=str(item["evidence_quote"]),
                source_run_id=str(item["source_run_id"]),
                source_message_id=int(item["source_message_id"]),
            )
            for item in facts.get("preferences", [])
        )

    @staticmethod
    def _confirmed_evidence_facts(facts: dict) -> tuple[ConfirmedEvidenceFact, ...]:
        return tuple(
            ConfirmedEvidenceFact(
                evidence_id=str(item["evidence_id"]),
                evidence_quote=str(item["evidence_quote"]),
                source_run_id=str(item["source_run_id"]),
                source_message_id=int(item["source_message_id"]),
            )
            for item in facts.get("confirmed_evidence", [])
            if isinstance(item, dict)
            and item.get("evidence_id")
            and item.get("evidence_quote")
        )

    @staticmethod
    def _plan_steps(facts: dict) -> tuple[dict[str, str], ...]:
        return tuple(
            {"step": str(item["step"]), "status": str(item["status"])}
            for item in facts.get("plan", [])
            if isinstance(item, dict) and item.get("step") and item.get("status")
        )

    @staticmethod
    def _remember_search_query(thread: RecruitmentThread, query: str) -> None:
        """Keep the phrase the model wrote for the latest turn."""
        facts = dict(thread.case_facts)
        facts["search_query"] = _trim_to_word(query.strip(), MAX_DERIVED_QUERY_CHARS)
        thread.case_facts = facts

    @staticmethod
    def _merge_preference_updates(
        thread: RecruitmentThread,
        updates: tuple[PreferenceUpdate, ...],
        source_message: Message,
    ) -> None:
        """Takes the updates rather than the reply: only evidenced ones get here."""
        current = list(thread.case_facts.get("preferences", []))
        for update in updates:
            if update.operation == "remove":
                current = [
                    item
                    for item in current
                    if not (
                        item.get("field") == update.field
                        and item.get("value") == update.value
                    )
                ]
                continue
            fact = {
                "field": update.field,
                "value": update.value,
                "evidence_quote": update.evidence_quote,
                "source_run_id": source_message.run_id,
                "source_message_id": source_message.message_id,
            }
            if not any(
                item.get("field") == update.field and item.get("value") == update.value
                for item in current
            ):
                current.append(fact)
        facts = dict(thread.case_facts)
        facts["preferences"] = current
        thread.case_facts = facts

    @staticmethod
    def _merge_confirmed_evidence(
        thread: RecruitmentThread,
        updates: list[ConfirmedEvidenceFact],
    ) -> None:
        current = list(thread.case_facts.get("confirmed_evidence", []))
        known_ids = {
            str(item.get("evidence_id"))
            for item in current
            if isinstance(item, dict) and item.get("evidence_id")
        }
        current.extend(
            asdict(fact) for fact in updates if fact.evidence_id not in known_ids
        )
        facts = dict(thread.case_facts)
        facts["confirmed_evidence"] = current
        thread.case_facts = facts

    def _event(
        self,
        thread: RecruitmentThread,
        run: RecruitmentRun,
        *,
        event_type: str,
        status: str,
        summary: str,
        detail: dict | None = None,
        team_member: str = "coordinator",
        parent_id: str | None = None,
        duration_ms: float | None = None,
        attributes: dict | None = None,
    ) -> RecruitmentActivityEvent:
        sequence = _reserve_event_sequence(self._db, thread.id)
        event = RecruitmentActivityEvent(
            thread_id=thread.id,
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            team_member=team_member,
            attempt=FIRST_ATTEMPT,
            trace_key=run.trace_key,
            summary=summary,
            detail=detail or {},
            parent_id=parent_id,
            duration_ms=duration_ms,
            attributes=attributes or {},
        )
        self._db.add(event)
        return event

    @staticmethod
    def _activity(item: RecruitmentActivityEvent) -> ActivityEvent:
        return ActivityEvent(
            sequence=item.sequence,
            run_id=item.run_id,
            event_type=item.event_type,
            status=item.status,
            team_member=item.team_member,
            attempt=item.attempt,
            trace_key=item.trace_key,
            summary=item.summary,
            detail=item.detail,
            parent_id=item.parent_id,
            duration_ms=item.duration_ms,
            attributes=item.attributes or {},
            created_at=item.created_at,
        )

    def _receipt(self, run: RecruitmentRun) -> RunReceipt:
        if run.status != "completed":
            raise InvalidCommand(f"command is {run.status}")
        stored = run.result if isinstance(run.result, dict) else {}
        workflow_state = stored.get("workflow_state")
        if workflow_state is None:
            # Runs recorded before workflow_state was stored; the thread's
            # current state is the best available answer for those.
            thread = (
                self._db.query(RecruitmentThread)
                .filter(RecruitmentThread.id == run.thread_id)
                .first()
            )
            workflow_state = thread.workflow_state if thread else ""
        return RunReceipt(
            run_id=run.id,
            thread_id=run.thread_id,
            status="completed",
            trace_key=run.trace_key,
            workflow_state=workflow_state or "",
            attempt_ledger=run.attempt_ledger or {},
        )
