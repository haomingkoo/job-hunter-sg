"""Deep V3 recruitment-team module: persistence, orchestration, and activity."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import (
    CandidateProfileArtifact,
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    RecruitmentThreadDeletionRequest,
    RoleProfileArtifact,
    ResumeVersion,
    TargetAssessmentArtifact,
    TrackedJob,
    User,
)
import config
from application_workspace import ensure_recruitment_application
from resume_agent.telemetry import trace_key
from run_concurrency import (
    database_owner_run_available,
    release_owner_run,
    reserve_owner_run,
)
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
from .job_recommender import JobRecommender, RankingReceipt, ranking_receipt_from_dict
from .execution_metrics import merge_execution_metrics
from .model_transport_observer import collect_transport_metrics
from .errors import (
    CandidateProfilingUnavailable,
    DiscoveryUnavailable,
    InvalidCommand,
    ResumeVersionNotFound,
    ResumeBindingConflict,
    RoleProfilingUnavailable,
    RunConcurrencyExceeded,
    ThreadNotFound,
    TargetAssessmentUnavailable,
    ServiceUnavailable,
    safe_terminal_error_payload,
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
from .run_lease import claim_failed_run, reconcile_expired_runs, renew_run_lease
from .candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileProgress,
    CandidateProfileValidationError,
    DETERMINISTIC_PROFILE_IMPLEMENTATION,
    candidate_profile_progress_event,
    CandidateProfilerFactory,
    candidate_profile_from_dict,
)
from .candidate_profile_store import (
    CandidateProfileCheckpointMismatch,
    SQLAlchemyCandidateProfileStore,
    candidate_profile_artifact_is_current,
)
from .discovery import DiscoveryPort, JobPostingVariant, JobSnapshot, JobSource
from .role_success import (
    RoleProfileValidationError,
    RoleSuccessProfile,
    RoleSuccessProfiler,
    role_profile_from_dict,
)
from .role_evidence_assessor import RoleEvidenceAssessmentError, role_evidence_attempt_limit
from .role_profile_store import (
    RoleProfileCheckpointMismatch,
    SQLAlchemyRoleProfileStore,
    public_role_validation_code,
    role_profile_identity,
)
from .resume_edit_evidence import (
    LangChainResumeEditEvidenceValidator,
    ResumeEditEvidenceValidator,
)
from .telemetry import RecruitmentTelemetry
from .activity_publisher import ActivityPublisher
from . import activity_events
from .prompts import COORDINATOR_PROMPT_VERSION
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
DEFAULT_THREAD_MESSAGE_PAGE_SIZE = 100
MAX_THREAD_MESSAGE_PAGE_SIZE = 200
ACTIVE_THREAD_STATUS = "active"
ARCHIVED_THREAD_STATUS = "archived"
THREAD_TITLE_MAX_CHARS = 120
MAX_JOB_FEEDBACK_SIGNALS = 100
MAX_DERIVED_QUERY_CHARS = 200
PROFILE_DERIVED_FACT_KEYS = (
    "latest_ranking_receipt",
    "recommendations",
    "match_rationales",
    "shortlisted_jobs",
    "shortlisted_job_ids",
    "selected_target",
    "role_success_profile",
    "role_success_metrics",
    "target_assessment_artifact_id",
)


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


def _trace_event_fields(
    *,
    kind: str,
    call_id: str,
    run_id: str,
    detail: dict,
    started_calls: dict[str, float],
) -> tuple[str, float | None, dict]:
    duration_ms = None
    if kind == "tool_call" and call_id:
        started_calls[call_id] = time.perf_counter()
    elif kind == "tool_result" and call_id:
        started_at = started_calls.pop(call_id, None)
        if started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000
    item = {"kind": kind, "id": call_id}
    parent_id = call_id if kind == "tool_result" and call_id else run_id
    return parent_id, duration_ms, activity_events.trace_attributes(item, detail)


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


BUILD_CANDIDATE_PROFILE_MESSAGE = "Study my attached resume and build its evidence profile."
ASSESS_TARGET_JOB_MESSAGE = "Run the bounded recruitment-team assessment for my selected target."
COMPLETION_SUMMARIES = {
    "coordinator": "The coordinator completed this turn.",
    "job_search": "The job search service completed this request.",
    "candidate_profiler": "The candidate profiler completed this turn.",
    "role_profiler": "The role profiler completed this turn.",
    "quality_judge": "The independent quality judge completed this turn.",
}
TRANSPORT_ATTEMPT_LIMIT = FIRST_ATTEMPT + config.RECRUITMENT_MODEL_TRANSPORT_RETRIES
SEMANTIC_ATTEMPT_LIMITS = {
    "start_thread": config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS,
    "send_message": config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS,
    "build_candidate_profile": FIRST_ATTEMPT,
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
        edit_evidence_validator: ResumeEditEvidenceValidator | None = None,
        recommender: JobRecommender | None = None,
        ai_credit_consumer: Callable[[int, str, str], None] | None = None,
        owns_session: bool = False,
        candidate_profiler_factory_provider: Callable[[], CandidateProfilerFactory] | None = None,
    ):
        self._db = db
        self._conversation_model = conversation_model
        self._discovery = discovery
        self._role_profiler = role_profiler
        self._telemetry = telemetry
        self._activity_publisher = activity_publisher
        self._candidate_profiler_factory = candidate_profiler_factory
        self._target_assessment_runner = target_assessment_runner
        self._candidate_profiler_factory_provider = candidate_profiler_factory_provider
        self._edit_evidence_validator = edit_evidence_validator or LangChainResumeEditEvidenceValidator(
            telemetry=telemetry
        )
        self._recommender = recommender or JobRecommender()
        self._ai_credit_consumer = ai_credit_consumer
        self._owns_session = owns_session

    def close(self) -> None:
        """Release a transport-owned database session, if this team owns one."""
        if self._owns_session:
            self._db.close()

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
        if command_type in {"build_candidate_profile", "candidate_profile"}:
            artifact_id = facts.get("candidate_profile_artifact_id")
            artifact = self._db.get(CandidateProfileArtifact, artifact_id) if artifact_id else None
        elif command_type in {"assess_target_job", "answer_assessment_question"}:
            artifact_id = facts.get("target_assessment_artifact_id")
            artifact = self._db.get(TargetAssessmentArtifact, artifact_id) if artifact_id else None
        elif command_type == "select_target_job":
            artifact = (
                self._db.query(RoleProfileArtifact)
                .filter(
                    RoleProfileArtifact.user_id == thread.user_id,
                    RoleProfileArtifact.thread_id == thread.id,
                )
                .order_by(RoleProfileArtifact.updated_at.desc())
                .first()
            )
        else:
            artifact = None
        if artifact is not None:
            existing = artifact.error or {}
            cause_type = existing.get("error_type")
            merged = {**existing, **detail}
            if cause_type:
                merged["error_type"] = cause_type
            artifact.error = merged

    def _prepare_workflow_resume(self, run: RecruitmentRun, *, record: bool = True) -> None:
        ledger = run.attempt_ledger or {}
        stage = str(ledger.get("last_attempted_stage") or run.command_type)
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
        if stage == "answer_assessment_question":
            self._restore_paused_assessment(run, restore=record)
        if record:
            self._record_run_attempt(
                run,
                stage=stage,
                layer="workflow_resume",
                limit=config.RECRUITMENT_WORKFLOW_RESUME_LIMIT,
                status="resumed",
                decision=decision,
            )

    def _restore_paused_assessment(self, run: RecruitmentRun, *, restore: bool) -> None:
        """Restore the durable pause consumed by a failed answer attempt."""

        thread = self._db.get(RecruitmentThread, run.thread_id)
        if thread is None:
            raise ThreadNotFound("recruitment thread not found")
        facts = dict(thread.case_facts or {})
        artifact_id = facts.get("target_assessment_artifact_id")
        pause_token = facts.get("target_assessment_pause_token")
        artifact = self._db.get(TargetAssessmentArtifact, artifact_id) if artifact_id else None
        if artifact is None or not pause_token or artifact.pending_specialist_runs is None:
            raise ServiceUnavailable(
                "the failed assessment answer no longer has a resumable checkpoint",
                decision=classify_failure("checkpoint_state_unavailable"),
            )
        if not restore:
            return
        artifact.status = "paused"
        facts["target_assessment_status"] = "paused"
        thread.case_facts = facts
        thread.workflow_state = "awaiting_candidate_answer"

    def _renew_run_lease(self, run: RecruitmentRun, *, commit: bool = False) -> None:
        owner = run.lease_owner or ""
        if not owner or not renew_run_lease(self._db, run.id, owner, _utcnow()):
            self._db.rollback()
            raise InvalidCommand("the run lease expired before this worker finished")
        if commit:
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
        owner_key = f"user:{owner_id}"
        capacity_limited = isinstance(
            command,
            (
                StartThread,
                SendMessage,
                BuildCandidateProfile,
                SearchJobs,
                SelectTargetJob,
                AssessTargetJob,
                AnswerAssessmentQuestion,
            ),
        )
        if capacity_limited and not reserve_owner_run(owner_key):
            raise RunConcurrencyExceeded(
                "Another AI run is already active for this user or the service is at capacity. Try again shortly."
            )
        try:
            thread_id = getattr(command, "thread_id", None) or (
                previous.thread_id if previous is not None else None
            )

            def execute_current() -> RunReceipt:
                nonlocal previous
                if previous is not None:
                    self._db.refresh(previous)
                else:
                    # A same-process duplicate can have been committed while
                    # this request waited for capacity/the thread lock.
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
                    if previous.command_type in {
                        "start_thread",
                        "send_message",
                        "answer_assessment_question",
                    }:
                        self._assert_latest_failed_conversation_turn(previous)
                    # Validate before the atomic claim so an unapproved retry
                    # never takes ownership. Record only after claim refreshes
                    # the row; production sessions disable autoflush.
                    self._prepare_workflow_resume(previous, record=False)
                if capacity_limited and not database_owner_run_available(self._db, owner_id):
                    # Release the database row lock now rather than holding it
                    # until request-session cleanup.
                    self._db.rollback()
                    raise RunConcurrencyExceeded(
                        "Another AI run is already active for this user or the service is at capacity. Try again shortly."
                    )
                if previous is None:
                    # Another worker may have completed this idempotency key
                    # while this request waited on the owner row lock.
                    previous = (
                        self._db.query(RecruitmentRun)
                        .filter(
                            RecruitmentRun.user_id == owner_id,
                            RecruitmentRun.idempotency_key == key,
                        )
                        .first()
                    )
                    if previous is not None and previous.status != "failed":
                        receipt = self._receipt(previous)
                        self._db.rollback()
                        return receipt
                    if previous is not None:
                        if previous.command_type in {
                            "start_thread",
                            "send_message",
                            "answer_assessment_question",
                        }:
                            self._assert_latest_failed_conversation_turn(previous)
                        self._prepare_workflow_resume(previous, record=False)
                if previous is None and capacity_limited and self._ai_credit_consumer is not None:
                    self._ai_credit_consumer(owner_id, type(command).__name__, key)
                try:
                    return self._execute_locked(
                        owner_id,
                        command,
                        key,
                        previous,
                    )
                except BaseException:
                    if self._db.in_transaction():
                        self._db.rollback()
                    raise

            if thread_id is None:
                return execute_current()
            with activity_events.thread_lock(thread_id):
                return execute_current()
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
                    resume = self._bound_resume(owner_id, thread)
                command_type = "start_thread"
                message = command.message
            elif isinstance(command, SendMessage):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "send_message"
                message = command.message
            elif isinstance(command, BuildCandidateProfile):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "build_candidate_profile"
                message = BUILD_CANDIDATE_PROFILE_MESSAGE
            elif isinstance(command, SearchJobs):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "search_jobs"
                message = command.query.strip()
                if not message:
                    raise InvalidCommand("job search requires an explicit query")
            elif isinstance(command, ShortlistJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "shortlist_job"
                job = self._known_job(thread, command.job_id)
                message = f"Shortlist {job.title} at {job.company}."
            elif isinstance(command, SelectTargetJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "select_target_job"
                self._completed_candidate_profile(thread, resume)
                job = self._known_job(thread, command.job_id)
                message = f"Select {job.title} at {job.company} as my target."
            elif isinstance(command, HideJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "hide_job"
                job = self._known_job(thread, command.job_id)
                message = f"Hide this {command.scope}: {job.title} at {job.company}."
            elif isinstance(command, AssessTargetJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
                command_type = "assess_target_job"
                message = ASSESS_TARGET_JOB_MESSAGE
            elif isinstance(command, AnswerAssessmentQuestion):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._bound_resume(owner_id, thread)
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
                lease_owner = uuid.uuid4().hex
                if not claim_failed_run(self._db, run.id, lease_owner, _utcnow()):
                    self._db.rollback()
                    self._db.refresh(run)
                    if run.status == "completed":
                        return self._receipt(run)
                    raise InvalidCommand(f"command is {run.status}")
                self._db.refresh(run)
                self._prepare_workflow_resume(run)
                run.command_type = command_type
                run.trace_key = correlation_key
                run.lease_owner = lease_owner
            else:
                run_id = str(uuid.uuid4())
                lease_owner = uuid.uuid4().hex
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
                    lease_owner=lease_owner,
                    lease_expires_at=(
                        _utcnow() + timedelta(seconds=config.RECRUITMENT_RUN_LEASE_SECONDS)
                    ),
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
            candidate_profile_command = isinstance(
                command,
                (StartThread, SendMessage, BuildCandidateProfile, SearchJobs),
            )
            direct_search_command = isinstance(command, SearchJobs)
            running_event = self._event(
                thread,
                run,
                event_type="run",
                status="running",
                summary=(
                    "The candidate profiler is checking the current resume evidence profile."
                    if candidate_profile_command
                    else (
                        "The job search service is searching current postings."
                        if direct_search_command
                        else "The recruitment-team coordinator is reviewing your request."
                    )
                ),
                team_member=(
                    "candidate_profiler"
                    if candidate_profile_command
                    else ("job_search" if direct_search_command else "coordinator")
                ),
            )
            with self._telemetry.operation("persist_running"):
                self._db.commit()
            self._activity_publisher.publish(activity_events.to_activity_event(running_event))
            command_transport_metrics: dict = {}
            attempted_stage = command_type
            try:
                if isinstance(command, SearchJobs):
                    attempted_stage = "candidate_profile"
                    profile_detail = self._ensure_candidate_profile(owner_id, thread, resume, run)
                    self._publish_stage_event(
                        thread,
                        run,
                        event_type="candidate_profile",
                        status="completed",
                        summary=(
                            "The current resume evidence profile was reused."
                            if profile_detail["reused"]
                            else "The candidate profiler completed the resume evidence profile."
                        ),
                        detail=profile_detail,
                        team_member="candidate_profiler",
                    )
                    self._publish_stage_event(
                        thread,
                        run,
                        event_type="job_search",
                        status="running",
                        summary="The job search service is searching current postings.",
                        detail={"operation": "job_search"},
                        team_member="job_search",
                    )
                    attempted_stage = command_type
                    reply, completion_detail = self._search_jobs(thread, resume, command, message)
                    completion_detail = {**completion_detail, "profile": profile_detail}
                    completion_member = "job_search"
                elif isinstance(command, BuildCandidateProfile):
                    completion_detail = self._ensure_candidate_profile(
                        owner_id, thread, resume, run
                    )
                    reply = ModelReply(
                        content=(
                            "The current role-neutral evidence profile is already ready."
                            if completion_detail["reused"]
                            else "The role-neutral evidence profile is ready."
                        ),
                        model_name=(
                            "candidate-profile-cache"
                            if completion_detail["reused"]
                            else str(self._candidate_profiler_factory.model_name)
                        ),
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
                    completion_member = "role_profiler"
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
                elif isinstance(command, (StartThread, SendMessage)):
                    attempted_stage = "candidate_profile"
                    profile_detail = self._ensure_candidate_profile(owner_id, thread, resume, run)
                    self._publish_stage_event(
                        thread,
                        run,
                        event_type="candidate_profile",
                        status="completed",
                        summary=(
                            "The current resume evidence profile was reused."
                            if profile_detail["reused"]
                            else "The candidate profiler completed the resume evidence profile."
                        ),
                        detail=profile_detail,
                        team_member="candidate_profiler",
                    )
                    self._publish_stage_event(
                        thread,
                        run,
                        event_type="conversation",
                        status="running",
                        summary="The recruitment-team coordinator is reviewing your request.",
                        detail={"operation": "coordinator"},
                        team_member="coordinator",
                    )
                    attempted_stage = command_type
                    with collect_transport_metrics() as conversation_transport_metrics:
                        reply = self._model_reply(
                            thread,
                            resume,
                            run,
                            correlation_key,
                            command_type,
                        )
                    command_transport_metrics = conversation_transport_metrics.summary()
                    completion_detail = {"model": reply.model_name, "profile": profile_detail}
                    completion_member = "coordinator"
                else:
                    with collect_transport_metrics() as conversation_transport_metrics:
                        reply = self._model_reply(
                            thread,
                            resume,
                            run,
                            correlation_key,
                            command_type,
                        )
                    command_transport_metrics = conversation_transport_metrics.summary()
                    completion_detail = {"model": reply.model_name}
                    completion_member = "coordinator"
            except BaseException as error:
                command_transport_metrics = (
                    getattr(error, "recruitment_transport_metrics", None)
                    or command_transport_metrics
                )
                if attempted_stage == "candidate_profile":
                    facts = dict(thread.case_facts or {})
                    facts["candidate_profile_status"] = "failed"
                    thread.case_facts = facts
                self._renew_run_lease(run)
                run.status = "failed"
                run.error_type = type(error).__name__
                run.completed_at = _utcnow()
                run.lease_owner = None
                run.lease_expires_at = None
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
                    attempted_stage,
                    layer,
                    limit - FIRST_ATTEMPT,
                )
                if (
                    command_type == "answer_assessment_question"
                    and initial_decision.failure_code == "checkpoint_state_unavailable"
                ):
                    remaining = remaining and attempts_remaining(
                        run.attempt_ledger,
                        command_type,
                        "workflow_resume",
                        config.RECRUITMENT_WORKFLOW_RESUME_LIMIT,
                    )
                elif (
                    command_type == "answer_assessment_question"
                    and initial_decision.failure_type != "transient"
                ):
                    # Semantic corrections must happen inside the still-running
                    # assessment graph. A terminal result has already cleaned its
                    # pause checkpoint, so advertising a workflow retry here would
                    # direct the caller to state that cannot be resumed.
                    remaining = False
                # The error source cannot know the durable budget. Reclassify
                # here, where the persisted ledger says whether a known
                # transport or semantic correction is still allowed. Terminal
                # categories remain terminal in classify_failure.
                decision = classify_failure(
                    initial_decision.failure_code,
                    attempts_remaining=remaining,
                    retry_after_seconds=initial_decision.retry_after_seconds,
                )
                if isinstance(error, ServiceUnavailable):
                    # The durable ledger is authoritative. Streaming observes
                    # this same exception after the command unwinds, so keep
                    # its public decision aligned with the persisted one.
                    error.failure_type = decision.failure_type
                    error.failure_code = decision.failure_code
                    error.retryable = decision.retryable
                    error.recovery_action = decision.recovery_action
                    error.retry_after_seconds = decision.retry_after_seconds
                    error.decision = decision
                self._record_run_attempt(
                    run,
                    stage=attempted_stage,
                    layer=layer,
                    limit=limit,
                    status="error",
                    decision=decision,
                    error_type=type(error).__name__,
                )
                run.attempt_ledger = {
                    **(run.attempt_ledger or {}),
                    "last_attempted_stage": attempted_stage,
                }
                attempt_budget = run.attempt_ledger["stages"][attempted_stage][layer]
                failure_detail = {
                    "command_type": command_type,
                    "attempted_stage": attempted_stage,
                    "attempt_count": attempt_budget["used"],
                    "attempt_limit": attempt_budget["limit"],
                    "error_type": type(error).__name__,
                    "failure_type": decision.failure_type,
                    "failure_code": decision.failure_code,
                    "retryable": decision.retryable,
                    "recovery_action": decision.recovery_action,
                    "message": safe_terminal_error_payload(error)["message"],
                }
                if decision.retry_after_seconds is not None:
                    failure_detail["retry_after_seconds"] = decision.retry_after_seconds
                if isinstance(error, ServiceUnavailable):
                    failure_detail.update({
                        key: value
                        for key, value in error.detail.items()
                        if key in {
                            "attempted_stage",
                            "validation_code",
                            "correction_scope",
                            "partial_artifact_id",
                            "alternatives",
                            "tool_name",
                        }
                    })
                self._persist_recovery_decision(thread, attempted_stage, failure_detail)
                terminal_error = {
                    key: failure_detail[key]
                    for key in (
                        "error_type",
                        "message",
                        "failure_type",
                        "failure_code",
                        "retryable",
                        "recovery_action",
                        "retry_after_seconds",
                        "attempted_stage",
                        "validation_code",
                        "correction_scope",
                        "partial_artifact_id",
                        "alternatives",
                        "tool_name",
                    )
                    if key in failure_detail
                }
                run.result = {
                    "terminal_error": terminal_error,
                    "transport_metrics": command_transport_metrics,
                }
                for attribute, value in failure_detail.items():
                    if attribute != "message":
                        command_span.set_attribute(attribute, value)
                failure_member = (
                    "candidate_profiler"
                    if attempted_stage == "candidate_profile" or command_type == "build_candidate_profile"
                    else ("job_search" if command_type == "search_jobs" else "coordinator")
                )
                failed_event = self._event(
                    thread,
                    run,
                    event_type="run",
                    status="failed",
                    summary={
                        "candidate_profiler": "The candidate profiler could not complete the resume study.",
                        "job_search": "The job search service could not complete this request.",
                        "coordinator": "The coordinator could not complete this turn.",
                    }[failure_member],
                    detail=failure_detail,
                    team_member=failure_member,
                    parent_id=run.id,
                    duration_ms=_run_duration_ms(run),
                    attributes={
                        key: value
                        for key, value in failure_detail.items()
                        if key != "message"
                    },
                )
                with self._telemetry.operation("persist_failed"):
                    self._db.commit()
                self._activity_publisher.publish(activity_events.to_activity_event(failed_event))
                error.recruitment_terminal_payload = terminal_error
                raise

            self._renew_run_lease(run)
            completion_detail = {
                **completion_detail,
                "reply_mode": reply.reply_mode,
            }
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
            run.lease_owner = None
            run.lease_expires_at = None
            run.result = {
                "run_id": run.id,
                "thread_id": run.thread_id,
                "status": run.status,
                "trace_key": run.trace_key,
                # Frozen here, not read from the thread at receipt time: the
                # thread moves on, so replaying a paused run's idempotency key
                # after it resumed would otherwise report the later state.
                "workflow_state": thread.workflow_state or "",
                "transport_metrics": command_transport_metrics,
                "reply_mode": reply.reply_mode,
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
                    if key in {"model", "input_tokens", "output_tokens", "reply_mode"}
                },
            )
            thread.updated_at = _utcnow()
            with self._telemetry.operation("persist_completed"):
                self._db.commit()
            self._activity_publisher.publish(activity_events.to_activity_event(completed_event))
            return self._receipt(run)

    def retry_conversation_run(
        self,
        owner_id: int,
        thread_id: str,
        run_id: str,
    ) -> RunReceipt:
        """Retry one durable conversation turn with its original identity."""

        thread = self._owned_thread(owner_id, thread_id)
        run = (
            self._db.query(RecruitmentRun)
            .filter(
                RecruitmentRun.id == run_id,
                RecruitmentRun.user_id == owner_id,
                RecruitmentRun.thread_id == thread.id,
            )
            .first()
        )
        if run is None:
            raise ThreadNotFound("recruitment run not found")
        if run.status == "completed":
            return self._receipt(run)
        if run.status != "failed":
            raise InvalidCommand(f"command is {run.status}")
        if run.command_type not in {
            "start_thread",
            "send_message",
            "answer_assessment_question",
        }:
            raise InvalidCommand(
                "only failed conversation turns or assessment answers can be retried here"
            )

        message = self._conversation_run_message(run)
        if run.command_type == "start_thread":
            command: Command = StartThread(
                resume_version_id=thread.resume_version_id,
                message=message.content,
            )
        elif run.command_type == "send_message":
            command = SendMessage(thread_id=thread.id, message=message.content)
        else:
            command = AnswerAssessmentQuestion(thread_id=thread.id, answer=message.content)
        return self.execute(owner_id, command, run.idempotency_key)

    def _conversation_run_message(self, run: RecruitmentRun) -> RecruitmentMessage:
        message = (
            self._db.query(RecruitmentMessage)
            .filter(
                RecruitmentMessage.thread_id == run.thread_id,
                RecruitmentMessage.run_id == run.id,
                RecruitmentMessage.role == "user",
            )
            .one_or_none()
        )
        if message is None:
            raise InvalidCommand("failed conversation turn has no durable user message")
        return message

    def _assert_latest_failed_conversation_turn(self, run: RecruitmentRun) -> None:
        message = self._conversation_run_message(run)
        latest = (
            self._db.query(RecruitmentMessage)
            .filter(
                RecruitmentMessage.thread_id == run.thread_id,
                RecruitmentMessage.role == "user",
            )
            .order_by(RecruitmentMessage.id.desc())
            .first()
        )
        if latest is None or latest.id != message.id:
            raise InvalidCommand("only the latest failed conversation turn can be retried")

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
            messages = self._messages(
                thread.id,
                limit=(config.RECRUITMENT_MODEL_HISTORY_TURNS * 2) + 1,
            )[0]
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
            try:
                with assessment_context(conversation, initial_edits=conversation.proposed_edits):
                    reply = self._conversation_model.respond(
                        messages,
                        resume.resume_text,
                        preferences,
                        conversation,
                    )
            except BaseException as error:
                cleanup_token = str(getattr(error, "checkpoint_cleanup_token", "") or "")
                if cleanup_token:
                    self._remember_coordinator_checkpoint_state(
                        thread,
                        pause_token="",
                        cleanup_token=cleanup_token,
                    )
                raise
            if not reply.content:
                raise InvalidCommand("conversation model returned no user-facing reply")
            reply = replace(reply, content=paragraph_reply(reply.content))
            evidenced, unevidenced = evidenced_preference_updates(
                reply.preference_updates,
                latest_user.content,
            )
            if evidenced:
                self._merge_preference_updates(thread, evidenced, latest_user)
            if reply.search_query:
                self._remember_search_query(thread, reply.search_query)
            # After _remember_search_query on purpose: a query that really ran
            # outranks one the model merely asked for.
            self._persist_conversation_searches(thread, conversation)
            self._persist_conversation_matches(thread, conversation)
            self._persist_conversation_plan(thread, conversation)
            self._persist_conversation_edits(thread, resume, run, conversation)
            self._remember_coordinator_checkpoint_state(
                thread,
                pause_token=reply.pause_token,
                cleanup_token=reply.checkpoint_cleanup_token,
            )
            model_span.set_attribute("model", reply.model_name)
            model_span.set_attribute(
                "prompt_version",
                getattr(reply, "prompt_version", "") or COORDINATOR_PROMPT_VERSION,
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
        profile = self._completed_candidate_profile(thread, resume)
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
            edit_evidence_validator=self._edit_evidence_validator,
            recommender=self._recommender,
            latest_user_message=latest_user.content,
            latest_user_message_id=latest_user.message_id,
            latest_user_run_id=latest_user.run_id,
            confirmed_evidence=self._confirmed_evidence_facts(facts),
            pause_token=str(facts.get("coordinator_pause_token") or ""),
            on_event=on_event,
        )

    @staticmethod
    def _remember_coordinator_checkpoint_state(
        thread: RecruitmentThread,
        *,
        pause_token: str,
        cleanup_token: str,
    ) -> None:
        """Persist the only coordinator checkpoint that still needs work."""
        facts = dict(thread.case_facts)
        if pause_token:
            facts["coordinator_pause_token"] = pause_token
        else:
            facts.pop("coordinator_pause_token", None)
        if cleanup_token:
            facts["coordinator_cleanup_token"] = cleanup_token
        else:
            facts.pop("coordinator_cleanup_token", None)
        thread.case_facts = facts

    def _conversation_activity(self, thread: RecruitmentThread, run: RecruitmentRun):
        """Persist and publish each coordinator tool event."""

        started_calls: dict[str, float] = {}

        def publish(item: dict) -> None:
            described = describe_progress(item)
            if described is None:
                if item.get("kind") == "model_attempt":
                    self._renew_run_lease(run, commit=True)
                return
            summary, detail = described
            call_id = str(item.get("id") or "")
            parent_id, duration_ms, attributes = _trace_event_fields(
                kind=str(item.get("kind") or ""),
                call_id=call_id,
                run_id=run.id,
                detail=detail,
                started_calls=started_calls,
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
            self._renew_run_lease(run, commit=True)
            self._activity_publisher.publish(activity_events.to_activity_event(event))

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
        latest_receipt = results[-1].ranking_receipt
        if latest_receipt is not None:
            facts["latest_ranking_receipt"] = self._ranking_receipt(thread, latest_receipt)
        facts.pop("match_rationales", None)
        thread.case_facts = facts

    @staticmethod
    def _ranking_receipt(thread: RecruitmentThread, receipt: RankingReceipt) -> dict:
        facts = thread.case_facts or {}
        value = asdict(receipt)
        value.update({
            "resume_version_id": thread.resume_version_id,
            "resume_sha256": str(facts.get("resume_sha256") or ""),
            "candidate_profile_artifact_id": (
                str(facts.get("candidate_profile_artifact_id") or "")
                if receipt.candidate_profile_used
                else ""
            ),
        })
        return value

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

    def _search_jobs(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
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
            profile = self._completed_candidate_profile(thread, resume)
            result = self._discovery.search_jobs(
                resolved_query,
                company=command.company,
                direct_employers_only=command.direct_employers_only,
                exclude_junior=command.exclude_junior,
                singapore_only=command.singapore_only,
                title_phrase=command.title_phrase,
            )
            batch = self._recommender.recommend(profile, result)
            result = batch.search_result
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
        facts["latest_ranking_receipt"] = self._ranking_receipt(thread, batch.receipt)
        thread.case_facts = facts
        count = len(visible_jobs)
        content = (
            "No current jobs matched this search. The source was reached successfully; "
            "you can refine the role or constraints."
            if result.valid_empty
            else f"Found {count} current, source-backed job matches. Review the "
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
            write_fence=lambda: self._renew_run_lease(command_run),
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
            self._renew_run_lease(command_run)
            self._db.commit()
            self._activity_publisher.publish(activity_events.to_activity_event(event))

        profiler = self._candidate_profiler_factory.create(store, publish_progress)
        try:
            run = profiler.profile(document)
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
            self._activate_candidate_profile_artifact(thread, artifact)
            self._merge_run_metrics(
                command_run,
                store.execution_metrics(error.checkpoint_id),
                semantic_limit=FIRST_ATTEMPT,
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
            "models": (
                []
                if run.model_call_count == 0 or current_metrics
                else [run.model_name]
            ),
            **(
                {"implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION}
                if run.model_call_count == 0
                else {}
            ),
            "attempts": [],
            "terminal_status": "completed",
        })
        self._merge_run_metrics(
            command_run,
            store.execution_metrics(run.checkpoint_id),
            semantic_limit=FIRST_ATTEMPT,
        )
        artifact = store.complete(run.checkpoint_id, run.profile, run.evaluation)
        self._activate_candidate_profile_artifact(thread, artifact)
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

    def _ensure_candidate_profile(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        command_run: RecruitmentRun,
    ) -> dict:
        """Resolve the exact resume profile required before a coordinator turn."""
        profile = self._find_completed_candidate_profile(thread, resume)
        if profile is not None:
            return {
                "operation": "candidate_profile",
                "artifact_id": thread.case_facts.get("candidate_profile_artifact_id"),
                "field_count": len(profile.fields),
                "reused": True,
            }
        if self._candidate_profiler_factory is None:
            provider_error = None
            if self._candidate_profiler_factory_provider is not None:
                try:
                    self._candidate_profiler_factory = self._candidate_profiler_factory_provider()
                except Exception as error:
                    provider_error = error
            if self._candidate_profiler_factory is None:
                unavailable = CandidateProfilingUnavailable(
                    "candidate profile capability is not configured",
                    decision=classify_failure("invalid_configuration"),
                    detail={"attempted_stage": "candidate_profile"},
                )
                if provider_error is not None:
                    raise unavailable from provider_error
                raise unavailable
        _, detail = self._build_candidate_profile(owner_id, thread, resume, command_run)
        return {**detail, "reused": False}

    def _publish_stage_event(
        self,
        thread: RecruitmentThread,
        run: RecruitmentRun,
        *,
        event_type: str,
        status: str,
        summary: str,
        detail: dict,
        team_member: str,
    ) -> None:
        event = self._event(
            thread,
            run,
            event_type=event_type,
            status=status,
            summary=summary,
            detail=detail,
            team_member=team_member,
            parent_id=run.id,
        )
        self._renew_run_lease(run)
        self._db.commit()
        self._activity_publisher.publish(activity_events.to_activity_event(event))

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
        checkpoint_store = None
        try:
            if hasattr(self._role_profiler, "checkpoint_identity"):
                checkpoint_store = SQLAlchemyRoleProfileStore(
                    self._db,
                    owner_id=owner_id,
                    thread_id=thread.id,
                    run_id=run_record.id,
                    resume_version_id=resume.id,
                    target_job_id=job.job_id,
                    identity=role_profile_identity(
                        candidate_profile=candidate_profile,
                        target=job,
                        comparable_jobs=comparable_jobs,
                        profiler=self._role_profiler,
                    ),
                )
                checkpoint_store.start()
        except RoleProfileCheckpointMismatch as error:
            raise RoleProfilingUnavailable(
                "the saved target-role checkpoint does not match this run",
                decision=classify_failure("checkpoint_mismatch"),
                detail={
                    "attempted_stage": "role_definition",
                    "validation_code": "checkpoint_mismatch",
                    "correction_scope": "none",
                    "partial_artifact_id": error.artifact_id,
                    "alternatives": ["start_new_logical_run"],
                },
            ) from error
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
                with collect_transport_metrics() as role_transport_metrics:
                    run = self._role_profiler.profile(
                        candidate_profile,
                        job,
                        comparable_jobs,
                        checkpoint_store,
                        before_model_call=lambda: self._renew_run_lease(run_record, commit=True),
                    )
                profile_span.set_attribute("model", run.model_name)
                profile_span.set_attribute("attempt_count", run.attempt_count)
                profile_span.set_attribute("generator_attempt_count", run.generator_attempt_count)
                profile_span.set_attribute("assessor_attempt_count", run.assessor_attempt_count)
                if run.generator_model_name:
                    profile_span.set_attribute("generator_model", run.generator_model_name)
                if run.assessor_model_name:
                    profile_span.set_attribute("assessor_model", run.assessor_model_name)
                profile_span.set_attribute(
                    "validation_codes",
                    [public_role_validation_code(code) for code in run.validation_codes],
                )
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
            validation_code = str(getattr(error, "validation_code", "semantic_fixable"))
            if checkpoint_store is not None:
                assessment_checkpoint = checkpoint_store.assessment()
                checkpoint_store.fail(
                    {
                        "attempted_stage": (
                            "role_evidence"
                            if isinstance(error, RoleEvidenceAssessmentError)
                            else "role_definition"
                        ),
                        "validation_code": validation_code,
                        "correction_scope": (
                            assessment_checkpoint.previous_scope
                            if assessment_checkpoint
                            else "full"
                        ),
                        "retryable": True,
                        "alternatives": ["retry_incomplete_stage", "start_new_logical_run"],
                        "transport_metrics": getattr(
                            error,
                            "recruitment_transport_metrics",
                            {},
                        ),
                    }
                )
            raise RoleProfilingUnavailable(
                "role success profile failed semantic validation",
                decision=classify_failure("semantic_fixable"),
                detail=checkpoint_store.error_detail() if checkpoint_store else {},
            ) from error
        except Exception as error:
            if checkpoint_store is not None:
                stage = "role_evidence" if checkpoint_store.definition() else "role_definition"
                assessment_checkpoint = checkpoint_store.assessment()
                checkpoint_store.fail(
                    {
                        "attempted_stage": stage,
                        "validation_code": str(
                            assessment_checkpoint.validation_code if assessment_checkpoint else ""
                        ),
                        "correction_scope": (
                            assessment_checkpoint.previous_scope if assessment_checkpoint else "none"
                        ),
                        "retryable": classify_exception(error, attempts_remaining=True).retryable,
                        "alternatives": ["retry_incomplete_stage", "start_new_logical_run"],
                        "transport_metrics": getattr(
                            error,
                            "recruitment_transport_metrics",
                            {},
                        ),
                    }
                )
            raise RoleProfilingUnavailable(
                f"role success profiling unavailable: {type(error).__name__}",
                decision=classify_exception(error),
                detail=checkpoint_store.error_detail() if checkpoint_store else {},
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
        if not run.checkpoint_hit_count and run.generator_attempt_count:
            role_attempts.append({
                "stage": "role_definition",
                "team_member": "role_profiler",
                "model": run.generator_model_name or run.model_name,
                "attempt_count": run.generator_attempt_count,
                "attempt_limit": config.ROLE_DEFINITION_VALIDATION_ATTEMPTS,
                "status": "success",
            })
        if not run.checkpoint_hit_count and run.assessor_attempt_count:
            role_attempts.append({
                "stage": "role_evidence",
                "team_member": "role_evidence_assessor",
                "model": run.assessor_model_name or run.model_name,
                "attempt_count": run.assessor_attempt_count,
                "attempt_limit": role_evidence_attempt_limit(len(run.profile.criteria)),
                "status": "success",
            })
        if not role_attempts and not run.checkpoint_hit_count:
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
            "model_call_count": 0 if run.checkpoint_hit_count else run.attempt_count,
            "checkpoint_hit_count": run.checkpoint_hit_count,
            "input_tokens": int(run.input_tokens or 0),
            "output_tokens": int(run.output_tokens or 0),
            "latency_ms": round((time.perf_counter() - profile_started) * 1000, 3),
            "validation_codes": [
                public_role_validation_code(code) for code in run.validation_codes
            ],
            "models": list(dict.fromkeys(filter(None, (
                run.generator_model_name,
                run.assessor_model_name,
                run.model_name,
            )))),
            "attempts": role_attempts,
            "terminal_status": "completed",
            **role_transport_metrics.summary(),
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
            "attempt_count": 0 if run.checkpoint_hit_count else run.attempt_count,
            "generator_attempt_count": run.generator_attempt_count,
            "assessor_attempt_count": run.assessor_attempt_count,
            "validation_codes": [
                public_role_validation_code(code) for code in run.validation_codes
            ],
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
            edit_evidence_validator=self._edit_evidence_validator,
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
            synthesis_claims=[],
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
            owner_id,
            thread,
            resume,
            run,
            artifact,
            self._target_assessment_runner.run(
                request,
                renew_lease=lambda: self._renew_run_lease(run, commit=True),
            ),
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

        latest_user_record = (
            self._db.query(RecruitmentMessage)
            .filter(
                RecruitmentMessage.thread_id == thread.id,
                RecruitmentMessage.role == "user",
            )
            .order_by(RecruitmentMessage.id.desc())
            .first()
        )
        latest_user = (
            Message(
                message_id=latest_user_record.id,
                role=latest_user_record.role,
                content=latest_user_record.content,
                run_id=latest_user_record.run_id,
                created_at=latest_user_record.created_at,
            )
            if latest_user_record is not None
            else None
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
            renew_lease=lambda: self._renew_run_lease(run, commit=True),
            synthesis_claims=list(artifact.pending_synthesis_claims or []),
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
                    kind = {
                        "call": "tool_call",
                        "result": "tool_result",
                        "model": "model_attempt",
                    }.get(str(detail.get("stage") or ""), "lifecycle")
                    parent_id, duration_ms, attributes = _trace_event_fields(
                        kind=kind,
                        call_id=call_id,
                        run_id=run.id,
                        detail=detail,
                        started_calls=started_calls,
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
                    self._renew_run_lease(run)
                    self._db.commit()
                    self._activity_publisher.publish(activity_events.to_activity_event(progress_event))
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
            artifact.execution_metrics = merge_execution_metrics(
                artifact.execution_metrics,
                {
                    **(getattr(error, "recruitment_transport_metrics", None) or {}),
                    "command_run_id": run.id,
                    "command_trace_key": run.trace_key,
                    "stage": "target_assessment",
                    "terminal_status": "failed",
                },
            )
            self._merge_run_metrics(
                run,
                artifact.execution_metrics,
                semantic_limit=config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
            )
            facts = dict(thread.case_facts)
            facts["target_assessment_status"] = artifact.status
            cleanup_token = str(getattr(error, "checkpoint_cleanup_token", "") or "")
            if cleanup_token:
                facts["target_assessment_cleanup_token"] = cleanup_token
            thread.case_facts = facts
            thread.workflow_state = "assessment_failed"
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
                        "command_run_id": run.id,
                        "command_trace_key": run.trace_key,
                    },
                )
                self._merge_run_metrics(
                    run,
                    artifact.execution_metrics,
                    semantic_limit=config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                )
                artifact.pending_specialist_runs = pause_detail.get("specialist_runs") or []
                artifact.pending_synthesis = str(pause_detail.get("synthesis") or "")
                artifact.pending_synthesis_claims = pause_detail.get("synthesis_claims") or []
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
                    reply_mode="paused",
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
            thread.workflow_state = "assessment_failed"
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
            retry_same_run = (
                run.command_type == "answer_assessment_question"
                and failure_code == "checkpoint_state_unavailable"
                and (effective_error or {}).get("retryable") is True
                and (effective_error or {}).get("recovery_action") == "retry_same_run"
            )
            retry_remaining = retry_same_run and attempts_remaining(
                run.attempt_ledger,
                run.command_type,
                "transport",
                TRANSPORT_ATTEMPT_LIMIT - FIRST_ATTEMPT,
            ) and attempts_remaining(
                run.attempt_ledger,
                run.command_type,
                "workflow_resume",
                config.RECRUITMENT_WORKFLOW_RESUME_LIMIT,
            )
            terminal_decision = classify_failure(
                failure_code,
                attempts_remaining=retry_remaining,
            )
            effective_error = {
                **(effective_error or {}),
                "failure_type": terminal_decision.failure_type,
                "failure_code": terminal_decision.failure_code,
                "retryable": terminal_decision.retryable,
                "recovery_action": terminal_decision.recovery_action,
            }
        artifact.status = effective_status
        # Unapproved model content stays out of the durable artifact. Attempt
        # metadata and lifecycle events remain available for diagnosis.
        artifact.specialist_runs = list(result.specialist_runs) if effective_status == "completed" else []
        artifact.synthesis = result.synthesis if effective_status == "completed" else ""
        artifact.synthesis_claims = (
            list(result.synthesis_claims) if effective_status == "completed" else []
        )
        retain_pause = (
            terminal_decision is not None
            and terminal_decision.retryable
            and terminal_decision.recovery_action == "retry_same_run"
        )
        if not retain_pause:
            artifact.pending_specialist_runs = None
            artifact.pending_synthesis = None
            artifact.pending_synthesis_claims = None
            artifact.pending_proposed_edits = None
        artifact.judge = result.judge
        artifact.correction = result.correction
        artifact.error = effective_error
        artifact.execution_policy = result.execution_policy
        artifact.execution_metrics = merge_execution_metrics(
            artifact.execution_metrics,
            {
                **result.execution_metrics,
                "command_run_id": run.id,
                "command_trace_key": run.trace_key,
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
        if result.checkpoint_cleanup_token:
            facts["target_assessment_cleanup_token"] = result.checkpoint_cleanup_token
        if not retain_pause:
            facts.pop("target_assessment_pause_token", None)
            facts.pop("target_assessment_pause_call_id", None)
        thread.case_facts = facts
        self._db.commit()

        if effective_status != "completed":
            if effective_status == "quality_blocked":
                thread.workflow_state = "quality_blocked"
            else:
                thread.workflow_state = "assessment_failed"
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
            "judge_status": (result.judge or {}).get("disposition", "completed"),
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

    @staticmethod
    def _profile_artifact_matches(
        artifact: CandidateProfileArtifact | None,
        resume: ResumeVersion,
    ) -> bool:
        if artifact is None or artifact.status != "completed" or not isinstance(artifact.profile, dict):
            return False
        from resume_document import create_resume_document

        document = create_resume_document(resume.resume_text)
        return (
            candidate_profile_artifact_is_current(artifact)
            and artifact.resume_version_id == resume.id
            and artifact.profile.get("resume_document_id") == document["document_id"]
            and artifact.profile.get("resume_revision") == document["revision"]
        )

    def _without_profile_derived_facts(self, facts: dict) -> dict:
        safe = dict(facts)
        for key in PROFILE_DERIVED_FACT_KEYS:
            safe.pop(key, None)
        safe["target_assessment_status"] = "not_started"
        return safe

    def _activate_candidate_profile_artifact(
        self,
        thread: RecruitmentThread,
        artifact: CandidateProfileArtifact,
    ) -> None:
        facts = dict(thread.case_facts or {})
        previous_id = str(facts.get("candidate_profile_artifact_id") or "")
        if artifact.status != "completed" or (previous_id and previous_id != artifact.id):
            facts = self._without_profile_derived_facts(facts)
            self._db.query(ProposedResumeEdit).filter(
                ProposedResumeEdit.user_id == thread.user_id,
                ProposedResumeEdit.thread_id == thread.id,
                ProposedResumeEdit.status == "pending",
            ).update({"status": "stale"})
        facts["candidate_profile_artifact_id"] = artifact.id
        facts["candidate_profile_status"] = artifact.status
        thread.case_facts = facts

    def _validated_case_facts(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
    ) -> dict:
        facts = dict(thread.case_facts or {})
        receipt = facts.get("latest_ranking_receipt")
        if not isinstance(receipt, dict):
            return self._without_profile_derived_facts(facts)
        valid = (
            receipt.get("resume_version_id") == resume.id
            and receipt.get("resume_sha256")
            == hashlib.sha256(resume.resume_text.encode()).hexdigest()
        )
        if valid and receipt.get("candidate_profile_used") is True:
            artifact_id = str(receipt.get("candidate_profile_artifact_id") or "")
            artifact = self._db.get(CandidateProfileArtifact, artifact_id) if artifact_id else None
            valid = (
                artifact_id == str(facts.get("candidate_profile_artifact_id") or "")
                and artifact is not None
                and artifact.user_id == thread.user_id
                and self._profile_artifact_matches(artifact, resume)
            )
        return facts if valid else self._without_profile_derived_facts(facts)

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
        if not self._profile_artifact_matches(artifact, resume):
            return None
        if artifact_id != artifact.id or thread.case_facts.get("candidate_profile_status") != "completed":
            facts = dict(thread.case_facts or {})
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = "completed"
            thread.case_facts = facts
        return self._candidate_profile_from_dict(artifact.profile)

    def snapshot(
        self,
        owner_id: int,
        thread_id: str,
        *,
        message_limit: int = DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
        before_message_id: int | None = None,
    ) -> ThreadSnapshot:
        thread = self._owned_thread(owner_id, thread_id)
        try:
            self._bound_resume(owner_id, thread)
            binding_status = "verified"
            facts = thread.case_facts
        except (ResumeBindingConflict, ResumeVersionNotFound):
            binding_status = "mismatch"
            facts = self._without_profile_derived_facts(thread.case_facts or {})
        messages, message_history_has_more = self._messages(
            thread.id,
            limit=message_limit,
            before_message_id=before_message_id,
        )
        return ThreadSnapshot(
            thread_id=thread.id,
            title=self._thread_title(thread),
            status=thread.status,
            workflow_state=thread.workflow_state,
            case_facts=CaseFacts(
                resume_version_id=int(facts.get("resume_version_id") or thread.resume_version_id),
                resume_label=str(facts.get("resume_label") or "Unavailable resume"),
                resume_sha256=str(facts.get("resume_sha256") or ""),
                resume_word_count=int(facts.get("resume_word_count") or 0),
                resume_created_at=str(facts.get("resume_created_at") or ""),
                resume_binding_status=binding_status,
                latest_search_query=str(facts.get("latest_search_query") or ""),
                latest_ranking_receipt=(
                    ranking_receipt_from_dict(facts["latest_ranking_receipt"])
                    if isinstance(facts.get("latest_ranking_receipt"), dict)
                    else None
                ),
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
            messages=messages,
            message_history_has_more=message_history_has_more,
            oldest_message_id=(messages[0].message_id if messages else None),
            last_event_sequence=thread.next_event_sequence - 1,
        )

    def candidate_profile(
        self,
        owner_id: int,
        thread_id: str,
    ) -> CandidateProfileArtifactSnapshot | None:
        thread = self._owned_thread(owner_id, thread_id)
        resume = self._bound_resume(owner_id, thread)
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
        if not self._profile_artifact_matches(artifact, resume):
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
                if not scope_id.startswith("__")
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
        resume = self._bound_resume(owner_id, thread)
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
        selected_target = thread.case_facts.get("selected_target")
        if artifact is None or not isinstance(selected_target, dict):
            return None
        target_sha256 = hashlib.sha256(
            json.dumps(selected_target, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        profile_artifact = self._db.get(
            CandidateProfileArtifact,
            artifact.candidate_profile_artifact_id,
        )
        if (
            artifact.resume_version_id != resume.id
            or artifact.candidate_profile_artifact_id
            != str(thread.case_facts.get("candidate_profile_artifact_id") or "")
            or artifact.target_job_id != int(selected_target.get("job_id") or 0)
            or artifact.target_snapshot_sha256 != target_sha256
            or profile_artifact is None
            or profile_artifact.user_id != owner_id
            or not self._profile_artifact_matches(profile_artifact, resume)
        ):
            return None
        # pending_specialist_runs is resumable coordinator state, not a reviewed
        # candidate-facing result. Only the post-judge specialist_runs field crosses
        # this API boundary.
        reported = list(artifact.specialist_runs or [])
        return TargetAssessmentArtifactSnapshot(
            artifact_id=artifact.id,
            target_job_id=artifact.target_job_id,
            status=artifact.status,
            specialist_runs=tuple(reported),
            synthesis=artifact.synthesis,
            synthesis_claims=tuple(artifact.synthesis_claims or []),
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
        limit: int = activity_events.DEFAULT_ACTIVITY_EVENT_LIMIT,
        *,
        tail: bool = True,
    ) -> list[ActivityEvent]:
        self._owned_thread(owner_id, thread_id)
        reconcile_expired_runs(self._db, thread_id=thread_id)
        query = (
            self._db.query(RecruitmentActivityEvent)
            .filter(
                RecruitmentActivityEvent.thread_id == thread_id,
                RecruitmentActivityEvent.sequence > after_sequence,
            )
        )
        if tail and after_sequence == 0:
            records = list(reversed(
                query.order_by(RecruitmentActivityEvent.sequence.desc()).limit(limit).all()
            ))
        else:
            records = query.order_by(RecruitmentActivityEvent.sequence).limit(limit).all()
        return [activity_events.to_activity_event(item) for item in records]

    def run_replay(
        self,
        owner_id: int,
        run_id: str,
        after_sequence: int,
    ) -> tuple[list[ActivityEvent], tuple[str, RunReceipt | dict] | None]:
        """Read new durable events and the terminal result for one owned run."""

        self._db.expire_all()
        run = (
            self._db.query(RecruitmentRun)
            .filter(RecruitmentRun.id == run_id, RecruitmentRun.user_id == owner_id)
            .first()
        )
        if run is None:
            raise ThreadNotFound("recruitment run not found")
        reconcile_expired_runs(self._db, thread_id=run.thread_id)
        self._db.refresh(run)
        records = (
            self._db.query(RecruitmentActivityEvent)
            .filter(
                RecruitmentActivityEvent.thread_id == run.thread_id,
                RecruitmentActivityEvent.run_id == run.id,
                RecruitmentActivityEvent.sequence > after_sequence,
            )
            .order_by(RecruitmentActivityEvent.sequence)
            .limit(activity_events.DEFAULT_ACTIVITY_EVENT_LIMIT + 1)
            .all()
        )
        has_more_events = len(records) > activity_events.DEFAULT_ACTIVITY_EVENT_LIMIT
        records = records[:activity_events.DEFAULT_ACTIVITY_EVENT_LIMIT]
        events = [activity_events.to_activity_event(item) for item in records]
        if has_more_events:
            return events, None
        if run.status == "completed":
            return events, ("receipt", self._receipt(run))
        if run.status != "failed":
            return events, None

        persisted_error = (run.result or {}).get("terminal_error")
        if isinstance(persisted_error, dict):
            return events, ("error", dict(persisted_error))

        failed = (
            self._db.query(RecruitmentActivityEvent)
            .filter(
                RecruitmentActivityEvent.run_id == run.id,
                RecruitmentActivityEvent.status == "failed",
            )
            .order_by(RecruitmentActivityEvent.sequence.desc())
            .first()
        )
        detail = failed.detail if failed is not None else {}
        return events, (
            "error",
            {
                "error_type": run.error_type or detail.get("error_type", "RecruitmentTeamError"),
                "message": detail.get(
                    "message",
                    failed.summary if failed is not None else "The recruitment team could not complete this turn.",
                ),
                **{
                    key: detail[key]
                    for key in (
                        "failure_type",
                        "failure_code",
                        "retryable",
                        "recovery_action",
                        "retry_after_seconds",
                    )
                    if key in detail
                },
            },
        )

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
                    resume_sha256=str(thread.case_facts.get("resume_sha256") or ""),
                    resume_word_count=int(thread.case_facts.get("resume_word_count") or 0),
                    resume_created_at=str(thread.case_facts.get("resume_created_at") or ""),
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

    def _finish_thread_checkpoint_cleanup(
        self,
        request: RecruitmentThreadDeletionRequest,
        result: dict,
        delete_checkpoints: Callable[[str], None] | None,
    ) -> dict:
        checkpoint_tokens = [
            str(token)
            for token in (request.targets or {}).get("checkpoint_tokens", [])
            if token
        ]
        if not checkpoint_tokens:
            return result
        if delete_checkpoints is None:
            raise ServiceUnavailable(
                "thread data was deleted, but checkpoint cleanup is still pending",
                decision=classify_failure(
                    "checkpoint_cleanup_failed",
                    attempts_remaining=True,
                ),
            )
        try:
            for token in checkpoint_tokens:
                delete_checkpoints(token)
        except Exception as error:
            raise ServiceUnavailable(
                "thread data was deleted, but checkpoint cleanup is still pending",
                decision=classify_failure(
                    "checkpoint_cleanup_failed",
                    attempts_remaining=True,
                ),
            ) from error
        result["deletion_request_status"] = "completed"
        request.status = "completed"
        request.targets = {}
        request.result = result
        self._db.commit()
        return result

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
            result = dict(previous.result or {})
            # Normalize legacy tombstones that claimed an external deletion
            # request existed even though no provider deletion integration was
            # configured. Exported telemetry is content-free, so the truthful
            # contract is synchronous application deletion plus provider
            # retention for operational metadata.
            result.update({
                "deletion_request_status": "completed",
                "provider_deletion_required": False,
                "retention": self.retention_contract(),
            })
            result.pop("trace_deletion_requests", None)
            result.pop("evaluation_deletion_requests", None)
            if (previous.targets or {}).get("checkpoint_tokens"):
                return self._finish_thread_checkpoint_cleanup(
                    previous,
                    result,
                    delete_checkpoints,
                )
            if previous.status != "completed" or previous.result != result or previous.targets:
                previous.status = "completed"
                previous.targets = {}
                previous.result = result
                self._db.commit()
            return result

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
                facts.get("coordinator_cleanup_token"),
                facts.get("target_assessment_pause_token"),
                facts.get("target_assessment_cleanup_token"),
            }
            if value
        ]
        result = {
            "thread_id": thread.id,
            "status": "deleted",
            "deletion_request_status": "cleanup_pending" if checkpoint_tokens else "completed",
            "provider_deletion_required": False,
            "retention": self.retention_contract(),
        }
        request = RecruitmentThreadDeletionRequest(
            id=str(uuid.uuid4()),
            user_id=owner_id,
            thread_id=thread.id,
            idempotency_key=key,
            status="cleanup_pending" if checkpoint_tokens else "completed",
            # Retain only opaque local checkpoint identifiers until their
            # idempotent cleanup succeeds. Never retain deleted content or
            # model-provider identifiers in this tombstone.
            targets={"checkpoint_tokens": checkpoint_tokens} if checkpoint_tokens else {},
            result=result,
        )
        self._db.add(request)
        self._db.delete(thread)
        with self._telemetry.operation(
            "delete_thread",
            {
                "owner_type": "user",
                "local_run_count": len(trace_keys),
                "local_evaluation_count": len(assessment_ids),
                "provider_deletion_required": False,
            },
        ):
            self._db.commit()
        if checkpoint_tokens:
            return self._finish_thread_checkpoint_cleanup(
                request,
                result,
                delete_checkpoints,
            )
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
                "resume_word_count": resume.word_count or len(resume.resume_text.split()),
                "resume_created_at": resume.created_at.isoformat() if resume.created_at else "",
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
        resume = self._bound_resume(owner_id, thread)
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

        resume_text = resume.resume_text or ""
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

        source = self._bound_resume(owner_id, thread)
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

    def _bound_resume(self, owner_id: int, thread: RecruitmentThread) -> ResumeVersion:
        """Resolve one thread's immutable resume identity or fail closed."""
        resume = (
            self._db.query(ResumeVersion)
            .filter(
                ResumeVersion.id == thread.resume_version_id,
                ResumeVersion.user_id == owner_id,
            )
            .first()
        )
        if resume is None:
            raise ResumeVersionNotFound("resume version not found")
        facts = thread.case_facts or {}
        expected_version_id = facts.get("resume_version_id")
        expected_sha256 = str(facts.get("resume_sha256") or "")
        actual_sha256 = hashlib.sha256(resume.resume_text.encode()).hexdigest()
        if expected_version_id != resume.id or expected_sha256 != actual_sha256:
            raise ResumeBindingConflict(
                "resume_binding_mismatch: this conversation's resume changed; start a new conversation"
            )
        thread.case_facts = self._validated_case_facts(thread, resume)
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
        return role_profile_from_dict(item)

    @staticmethod
    def _candidate_profile_from_dict(item: dict) -> CandidateEvidenceProfile:
        return candidate_profile_from_dict(item)

    def _messages(
        self,
        thread_id: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> tuple[list[Message], bool]:
        query = (
            self._db.query(RecruitmentMessage)
            .filter(RecruitmentMessage.thread_id == thread_id)
        )
        if before_message_id is not None:
            query = query.filter(RecruitmentMessage.id < before_message_id)
        records = query.order_by(RecruitmentMessage.id.desc()).limit(limit + 1).all()
        has_more = len(records) > limit
        records = list(reversed(records[:limit]))
        return [
            Message(
                message_id=item.id,
                role=item.role,
                content=item.content,
                run_id=item.run_id,
                created_at=item.created_at,
            )
            for item in records
        ], has_more

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
        return activity_events.create_record(
            self._db,
            thread=thread,
            run=run,
            event_type=event_type,
            status=status,
            summary=summary,
            detail=detail,
            team_member=team_member,
            parent_id=parent_id,
            duration_ms=duration_ms,
            attributes=attributes,
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
