"""Deep V3 recruitment-team module: persistence, orchestration, and activity."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import (
    CandidateProfileArtifact,
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
    TargetAssessmentArtifact,
)
from resume_agent.telemetry import trace_key

from .interface import (
    ActivityEvent,
    AssessTargetJob,
    BuildCandidateProfile,
    CandidateProfileArtifactSnapshot,
    CaseFacts,
    Command,
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
)
from .errors import (
    CandidateProfilingUnavailable,
    DiscoveryUnavailable,
    InvalidCommand,
    ResumeVersionNotFound,
    RoleProfilingUnavailable,
    ThreadNotFound,
    TargetAssessmentUnavailable,
)
from .conversation_model import ConversationModel, ModelReply, preference_update_error
from .candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileTransportError,
    CandidateProfileValidationError,
    CandidateProfilerFactory,
    candidate_profile_from_dict,
)
from .candidate_profile_store import (
    RETRY_FEEDBACK_SCOPE_KEY,
    CandidateProfileCheckpointMismatch,
    SQLAlchemyCandidateProfileStore,
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
from .role_evidence_assessor import RoleEvidenceAssessmentError
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
BUILD_CANDIDATE_PROFILE_MESSAGE = "Study my attached resume and build its evidence profile."
ASSESS_TARGET_JOB_MESSAGE = "Run the bounded recruitment-team assessment for my selected target."
COMPLETION_SUMMARIES = {
    "coordinator": "The coordinator completed this turn.",
    "candidate_profiler": "The candidate profiler completed this turn.",
    "quality_judge": "The independent quality judge completed this turn.",
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
    ):
        self._db = db
        self._conversation_model = conversation_model
        self._discovery = discovery
        self._role_profiler = role_profiler
        self._telemetry = telemetry
        self._activity_publisher = activity_publisher
        self._candidate_profiler_factory = candidate_profiler_factory
        self._target_assessment_runner = target_assessment_runner

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

        with self._telemetry.operation(
            "command",
            {
                "owner_type": "user",
                "attempt": FIRST_ATTEMPT,
            },
        ) as command_span:
            if isinstance(command, StartThread):
                thread, resume = self._start_thread(owner_id, command)
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
                message = command.query
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
            elif isinstance(command, AssessTargetJob):
                thread = self._owned_thread(owner_id, command.thread_id)
                resume = self._owned_resume(owner_id, thread.resume_version_id)
                command_type = "assess_target_job"
                message = ASSESS_TARGET_JOB_MESSAGE
            else:
                raise InvalidCommand("unsupported recruitment-team command")

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
            self._db.add(
                RecruitmentMessage(
                    thread_id=thread.id,
                    run_id=run_id,
                    role="user",
                    content=message.strip(),
                )
            )
            running_event = self._event(
                thread,
                run,
                event_type="run",
                status="running",
                summary="The recruitment-team coordinator is reviewing your request.",
            )
            with self._telemetry.operation("persist_running"):
                self._db.commit()
            self._activity_publisher.publish(self._activity(running_event))

            try:
                if isinstance(command, SearchJobs):
                    reply, completion_detail = self._search_jobs(thread, command)
                    completion_member = "coordinator"
                elif isinstance(command, BuildCandidateProfile):
                    reply, completion_detail = self._build_candidate_profile(
                        owner_id,
                        thread,
                        resume,
                    )
                    completion_member = "candidate_profiler"
                elif isinstance(command, ShortlistJob):
                    reply, completion_detail = self._shortlist_job(thread, command)
                    completion_member = "coordinator"
                elif isinstance(command, SelectTargetJob):
                    reply, completion_detail = self._select_target(thread, resume, command)
                    completion_member = "coordinator"
                elif isinstance(command, AssessTargetJob):
                    reply, completion_detail = self._assess_target(
                        owner_id,
                        thread,
                        resume,
                        run,
                    )
                    completion_member = "quality_judge"
                else:
                    reply = self._model_reply(
                        thread,
                        resume,
                        correlation_key,
                        command_type,
                    )
                    completion_detail = {"model": reply.model_name}
                    completion_member = "coordinator"
            except BaseException as error:
                run.status = "failed"
                run.error_type = type(error).__name__
                run.completed_at = _utcnow()
                failure_detail = {"error_type": type(error).__name__}
                if hasattr(error, "failure_type"):
                    failure_detail["failure_type"] = str(error.failure_type)
                if hasattr(error, "retryable"):
                    failure_detail["retryable"] = bool(error.retryable)
                failed_event = self._event(
                    thread,
                    run,
                    event_type="run",
                    status="failed",
                    summary="The coordinator could not complete this turn.",
                    detail=failure_detail,
                )
                with self._telemetry.operation("persist_failed"):
                    self._db.commit()
                self._activity_publisher.publish(self._activity(failed_event))
                raise

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
            }
            completed_event = self._event(
                thread,
                run,
                event_type="run",
                status="completed",
                summary=COMPLETION_SUMMARIES[completion_member],
                detail=completion_detail,
                team_member=completion_member,
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
            preferences = self._preference_facts(thread.case_facts)
            reply = self._conversation_model.respond(
                messages,
                resume.resume_text,
                preferences,
            )
            if not reply.content:
                raise InvalidCommand("conversation model returned no user-facing reply")
            latest_user = next(
                (message for message in reversed(messages) if message.role == "user"),
                None,
            )
            if latest_user is None:
                raise InvalidCommand("conversation turn has no user message")
            update_error = preference_update_error(
                reply.preference_updates,
                latest_user.content,
            )
            if update_error:
                raise InvalidCommand(update_error)
            if reply.preference_updates:
                self._merge_preference_updates(thread, reply, latest_user)
            model_span.set_attribute("model", reply.model_name)
            model_span.set_attribute("prompt_version", CONVERSATION_PROMPT_VERSION)
            model_span.set_attribute("preference_update_count", len(reply.preference_updates))
            if reply.input_tokens is not None:
                model_span.set_attribute("input_tokens", reply.input_tokens)
            if reply.output_tokens is not None:
                model_span.set_attribute("output_tokens", reply.output_tokens)
            return reply

    def _search_jobs(
        self,
        thread: RecruitmentThread,
        command: SearchJobs,
    ) -> tuple[ModelReply, dict]:
        with self._telemetry.operation(
            "job.search",
            {
                "attempt": FIRST_ATTEMPT,
            },
        ) as search_span:
            result = self._discovery.search_jobs(command.query.strip())
            search_span.set_attribute("valid_empty", result.valid_empty)
            search_span.set_attribute("result_count", len(result.jobs))
            search_span.set_attribute("truncated", result.truncated)
            if result.failure_type:
                search_span.set_attribute("failure_type", result.failure_type)
                search_span.set_attribute("retryable", result.retryable)
                raise DiscoveryUnavailable(f"job search unavailable: {result.failure_type}")

        facts = dict(thread.case_facts)
        facts["latest_search_query"] = result.query
        facts["recommendations"] = [asdict(job) for job in result.jobs]
        thread.case_facts = facts
        count = len(result.jobs)
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
    ) -> tuple[ModelReply, dict]:
        if self._candidate_profiler_factory is None:
            raise InvalidCommand("candidate profile capability is not configured")
        from resume_document import create_resume_document

        document = resume.resume_structured
        if document is None:
            document = create_resume_document(resume.resume_text)
        elif document.get("schema_version") != 1 or document.get("raw_text") != resume.resume_text:
            raise CandidateProfilingUnavailable(
                "saved resume structure does not match its immutable text",
                failure_type="validation",
                retryable=False,
            )

        store = SQLAlchemyCandidateProfileStore(
            self._db,
            owner_id=owner_id,
            resume_version_id=resume.id,
            model_name=self._candidate_profiler_factory.model_name,
        )
        profiler = self._candidate_profiler_factory.create(store)
        try:
            run = profiler.profile(document)
        except CandidateProfileTransportError as error:
            artifact = store.fail(
                error.checkpoint_id,
                {
                    "failure_type": "transport",
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
            raise CandidateProfilingUnavailable(
                "candidate profile model transport failed",
                failure_type="transport",
                retryable=True,
            ) from error
        except CandidateProfileValidationError as error:
            artifact = store.fail(
                error.checkpoint_id,
                {
                    "failure_type": "validation",
                    "validation_code": error.validation_code,
                    "completed_scope_ids": list(error.completed_scope_ids),
                    "recovery": "Correct the failed structured scope before resuming.",
                },
            )
            facts = dict(thread.case_facts)
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = artifact.status
            thread.case_facts = facts
            raise CandidateProfilingUnavailable(
                "candidate profile failed semantic validation",
                failure_type="validation",
                retryable=False,
            ) from error
        except CandidateProfileCheckpointMismatch as error:
            raise CandidateProfilingUnavailable(
                "candidate profile checkpoint no longer matches the configured "
                "prompt, model, decomposition, or execution policy version",
                failure_type="business",
                retryable=False,
            ) from error

        artifact = store.complete(run.checkpoint_id, run.profile)
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
        thread: RecruitmentThread,
        command: ShortlistJob,
    ) -> tuple[ModelReply, dict]:
        job = self._known_job(thread, command.job_id)
        facts = dict(thread.case_facts)
        shortlist = list(facts.get("shortlisted_jobs", []))
        if not any(int(item.get("job_id", -1)) == job.job_id for item in shortlist):
            shortlist.append(asdict(job))
        facts["shortlisted_jobs"] = shortlist
        facts.pop("shortlisted_job_ids", None)
        thread.case_facts = facts
        return ModelReply(
            content=f"Shortlisted {job.title} at {job.company}.",
            model_name="deterministic-workflow",
        ), {"operation": "shortlist_job", "shortlist_count": len(shortlist)}

    def _select_target(
        self,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        command: SelectTargetJob,
    ) -> tuple[ModelReply, dict]:
        job = self._known_job(thread, command.job_id)
        candidate_profile = self._completed_candidate_profile(thread, resume)
        comparable_jobs: tuple[JobSnapshot, ...] = ()
        try:
            with self._telemetry.operation(
                "role_success.profile",
                {
                    "attempt": FIRST_ATTEMPT,
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
                failure_type="validation",
                retryable=False,
            ) from error
        except Exception as error:
            raise RoleProfilingUnavailable(
                f"role success profiling unavailable: {type(error).__name__}",
                failure_type="transient",
                retryable=True,
            ) from error
        facts = dict(thread.case_facts)
        shortlist = list(facts.get("shortlisted_jobs", []))
        if not any(int(item.get("job_id", -1)) == job.job_id for item in shortlist):
            shortlist.append(asdict(job))
        facts["shortlisted_jobs"] = shortlist
        facts.pop("shortlisted_job_ids", None)
        facts["selected_target"] = asdict(job)
        facts["role_success_profile"] = asdict(run.profile)
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
        }

    def _assess_target(
        self,
        owner_id: int,
        thread: RecruitmentThread,
        resume: ResumeVersion,
        run: RecruitmentRun,
    ) -> tuple[ModelReply, dict]:
        if self._target_assessment_runner is None:
            raise InvalidCommand("target assessment capability is not configured")
        from resume_document import create_resume_document

        resume_document = create_resume_document(resume.resume_text)
        facts = dict(thread.case_facts)
        if not isinstance(facts.get("selected_target"), dict):
            raise InvalidCommand("select a target job before running its assessment")
        if not isinstance(facts.get("role_success_profile"), dict):
            raise InvalidCommand("build the role success profile before running its assessment")
        candidate_profile = self._completed_candidate_profile(thread, resume)
        candidate_profile_artifact_id = str(facts["candidate_profile_artifact_id"])
        target = self._job_from_dict(facts["selected_target"])
        role_profile = self._role_profile_from_dict(facts["role_success_profile"])
        target_snapshot_sha256 = hashlib.sha256(
            json.dumps(asdict(target), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        artifact = TargetAssessmentArtifact(
            id=str(uuid.uuid4()),
            user_id=owner_id,
            thread_id=thread.id,
            run_id=run.id,
            resume_version_id=resume.id,
            candidate_profile_artifact_id=candidate_profile_artifact_id,
            target_job_id=target.job_id,
            target_snapshot_sha256=target_snapshot_sha256,
            status="running",
            specialist_runs=[],
            synthesis="",
            execution_policy=target_assessment_execution_policy(),
        )
        self._db.add(artifact)
        facts["target_assessment_artifact_id"] = artifact.id
        facts["target_assessment_status"] = "running"
        thread.case_facts = facts
        thread.workflow_state = "assessing"
        self._db.commit()

        result: TargetAssessmentResult | None = None
        last_progress_status: str | None = None
        pending_question = ""
        try:
            for update in self._target_assessment_runner.run(
                TargetAssessmentRequest(
                    candidate_profile=candidate_profile,
                    role_profile=role_profile,
                    target_job=target,
                    trace_key=run.trace_key,
                    resume_document=resume_document,
                )
            ):
                if isinstance(update, TargetAssessmentProgress):
                    last_progress_status = update.status
                    if update.status == "paused":
                        pending_question = str((update.detail or {}).get("question") or "")
                    progress_event = self._event(
                        thread,
                        run,
                        event_type="assessment",
                        status=update.status,
                        summary=update.summary,
                        detail=update.detail,
                        team_member=update.team_member,
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
            artifact.status = "failed"
            artifact.error = {
                "failure_type": "workflow",
                "error_type": type(error).__name__,
                "retryable": True,
            }
            facts = dict(thread.case_facts)
            facts["target_assessment_status"] = artifact.status
            thread.case_facts = facts
            artifact.updated_at = _utcnow()
            self._db.commit()
            raise TargetAssessmentUnavailable(
                f"target assessment unavailable: {type(error).__name__}",
                failure_type="transient",
                retryable=True,
            ) from error

        if result is None:
            if last_progress_status == "paused":
                artifact.status = "paused"
                artifact.updated_at = _utcnow()
                facts = dict(thread.case_facts)
                facts["target_assessment_status"] = "paused"
                thread.case_facts = facts
                thread.workflow_state = "awaiting_candidate_answer"
                self._db.commit()
                return ModelReply(
                    content=pending_question,
                    model_name="open-agent-recruitment-team",
                ), {}
            artifact.status = "failed"
            artifact.error = {
                "failure_type": "workflow",
                "error_type": "MissingTerminalResult",
                "retryable": True,
            }
            facts = dict(thread.case_facts)
            facts["target_assessment_status"] = artifact.status
            thread.case_facts = facts
            artifact.updated_at = _utcnow()
            self._db.commit()
            raise TargetAssessmentUnavailable(
                "target assessment runner returned no terminal result",
                failure_type="workflow",
                retryable=True,
            )
        effective_status = result.status
        effective_error = result.error
        if result.status == "completed" and not result.synthesis.strip():
            effective_status = "failed"
            effective_error = {
                "failure_type": "validation",
                "error_type": "EmptySynthesis",
                "retryable": False,
            }
        artifact.status = effective_status
        artifact.specialist_runs = list(result.specialist_runs)
        artifact.synthesis = result.synthesis
        artifact.judge = result.judge
        artifact.correction = result.correction
        artifact.error = effective_error
        artifact.execution_policy = result.execution_policy
        artifact.updated_at = _utcnow()
        facts = dict(thread.case_facts)
        facts["target_assessment_status"] = effective_status
        thread.case_facts = facts
        self._db.commit()

        if effective_status != "completed":
            if effective_status == "quality_blocked":
                thread.workflow_state = "quality_blocked"
                self._db.commit()
            failure_type = "quality" if effective_status == "quality_blocked" else "workflow"
            raise TargetAssessmentUnavailable(
                "target assessment did not pass its independent quality gate",
                failure_type=failure_type,
                retryable=bool((effective_error or {}).get("retryable")),
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
                    document_revision=edit["document_revision"],
                    status="pending",
                )
            )
        thread.workflow_state = "assessment_ready"
        return ModelReply(
            content=result.synthesis,
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
        artifact_id = thread.case_facts.get("candidate_profile_artifact_id")
        if not artifact_id or thread.case_facts.get("candidate_profile_status") != "completed":
            raise InvalidCommand("build the candidate evidence profile before selecting a target job")
        artifact = (
            self._db.query(CandidateProfileArtifact)
            .filter(
                CandidateProfileArtifact.id == str(artifact_id),
                CandidateProfileArtifact.user_id == thread.user_id,
                CandidateProfileArtifact.resume_version_id == resume.id,
                CandidateProfileArtifact.status == "completed",
            )
            .first()
        )
        if artifact is None or artifact.profile is None:
            raise InvalidCommand("completed candidate profile artifact is unavailable")
        return self._candidate_profile_from_dict(artifact.profile)

    def snapshot(self, owner_id: int, thread_id: str) -> ThreadSnapshot:
        thread = self._owned_thread(owner_id, thread_id)
        facts = thread.case_facts
        return ThreadSnapshot(
            thread_id=thread.id,
            status=thread.status,
            workflow_state=thread.workflow_state,
            case_facts=CaseFacts(
                resume_version_id=int(facts["resume_version_id"]),
                resume_label=str(facts["resume_label"]),
                resume_sha256=str(facts["resume_sha256"]),
                latest_search_query=str(facts.get("latest_search_query") or ""),
                recommendations=tuple(self._job_from_dict(item) for item in facts.get("recommendations", [])),
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
                role_success_profile=(
                    self._role_profile_from_dict(facts["role_success_profile"])
                    if isinstance(facts.get("role_success_profile"), dict)
                    else None
                ),
                preferences=self._preference_facts(facts),
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
        artifact_id = thread.case_facts.get("candidate_profile_artifact_id")
        if not artifact_id:
            return None
        artifact = (
            self._db.query(CandidateProfileArtifact)
            .filter(
                CandidateProfileArtifact.id == str(artifact_id),
                CandidateProfileArtifact.user_id == owner_id,
                CandidateProfileArtifact.resume_version_id == thread.resume_version_id,
            )
            .first()
        )
        if artifact is None:
            raise InvalidCommand("candidate profile artifact reference is invalid")
        return CandidateProfileArtifactSnapshot(
            artifact_id=artifact.id,
            resume_version_id=artifact.resume_version_id,
            checkpoint_id=artifact.checkpoint_id,
            prompt_version=artifact.prompt_version,
            decomposition_version=artifact.decomposition_version,
            model_name=artifact.model_name,
            execution_policy=artifact.execution_policy,
            status=artifact.status,
            completed_scope_ids=tuple(scope_id for scope_id in artifact.scopes if scope_id != RETRY_FEEDBACK_SCOPE_KEY),
            profile=artifact.profile,
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
        return TargetAssessmentArtifactSnapshot(
            artifact_id=artifact.id,
            target_job_id=artifact.target_job_id,
            status=artifact.status,
            specialist_runs=tuple(artifact.specialist_runs),
            synthesis=artifact.synthesis,
            judge=artifact.judge,
            correction=artifact.correction,
            error=artifact.error,
            execution_policy=artifact.execution_policy,
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
                    status=thread.status,
                    workflow_state=thread.workflow_state,
                    resume_version_id=thread.resume_version_id,
                    resume_label=str(thread.case_facts["resume_label"]),
                    last_message=last_message.content if last_message else None,
                    updated_at=thread.updated_at,
                )
            )
        return summaries

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
    def _merge_preference_updates(
        thread: RecruitmentThread,
        reply: ModelReply,
        source_message: Message,
    ) -> None:
        current = list(thread.case_facts.get("preferences", []))
        for update in reply.preference_updates:
            fact = {
                "field": update.field,
                "value": update.value,
                "evidence_quote": update.evidence_quote,
                "source_run_id": source_message.run_id,
                "source_message_id": source_message.message_id,
            }
            if update.field == "constraints":
                if not any(
                    item.get("field") == "constraints" and item.get("value") == update.value for item in current
                ):
                    current.append(fact)
            else:
                current = [item for item in current if item.get("field") != update.field]
                current.append(fact)
        facts = dict(thread.case_facts)
        facts["preferences"] = current
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
    ) -> RecruitmentActivityEvent:
        sequence = thread.next_event_sequence
        thread.next_event_sequence += 1
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
            created_at=item.created_at,
        )

    @staticmethod
    def _receipt(run: RecruitmentRun) -> RunReceipt:
        if run.status != "completed":
            raise InvalidCommand(f"command is {run.status}")
        return RunReceipt(
            run_id=run.id,
            thread_id=run.thread_id,
            status="completed",
            trace_key=run.trace_key,
        )
