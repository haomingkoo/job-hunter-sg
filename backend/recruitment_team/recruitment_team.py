"""Deep V3 recruitment-team module: persistence, orchestration, and activity."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
import weakref
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
    AnswerAssessmentQuestion,
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
# A derived query stands in for a typed one, so keep it to a search-sized phrase.
MAX_DERIVED_QUERY_CHARS = 200
# A UI-sent opener is an instruction to the team, not something the candidate
# wants searched, so it must never become the query.
AUTOPILOT_MARKER = "[autopilot]"
RESUME_TITLE_LINES = 6
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
        thread_id = getattr(command, "thread_id", None)
        if thread_id is None:
            return self._execute_locked(owner_id, command, idempotency_key)
        with _thread_lock(thread_id):
            return self._execute_locked(owner_id, command, idempotency_key)

    def _execute_locked(
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
                    reply, completion_detail = self._search_jobs(thread, command, message)
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

    def _query_from_candidate(self, thread: RecruitmentThread, resume: ResumeVersion) -> str:
        """Build a search query from the candidate's own material.

        Preference order matters. The team's own extracted preferences are the
        sharpest signal because they are what the model concluded the candidate
        wants. A typed message is next. The resume itself is last, and is the one
        that has to work: a candidate who clicks straight through to a search has
        said nothing at all, and searching their resume beats searching whatever
        instruction the UI happened to send on their behalf.
        """
        facts = thread.case_facts or {}
        preferences = " ".join(
            str(fact.get("value") or "")
            for fact in (facts.get("preferences") or [])
            if isinstance(fact, dict)
        ).strip()
        if preferences:
            return preferences[:MAX_DERIVED_QUERY_CHARS]

        latest = (
            self._db.query(RecruitmentMessage)
            .filter(RecruitmentMessage.thread_id == thread.id, RecruitmentMessage.role == "user")
            .order_by(RecruitmentMessage.id.desc())
            .first()
        )
        typed = (latest.content or "").strip() if latest else ""
        if typed and not typed.startswith(AUTOPILOT_MARKER):
            return typed[:MAX_DERIVED_QUERY_CHARS]

        return self._query_from_resume(resume)

    @staticmethod
    def _query_from_resume(resume: ResumeVersion) -> str:
        """Role titles plus extracted skills, as a search phrase.

        Whole sentences pull the search toward what the candidate has already
        done; a career changer searching their own prose gets more of their old
        job. Titles and skills keep it on the roles themselves.
        """
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
        return (phrase or resume.label or "roles matching my experience")[:MAX_DERIVED_QUERY_CHARS]

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

        request = self._target_assessment_request(thread, resume, run.trace_key)
        thread.workflow_state = "assessing"
        self._db.commit()

        updates = self._target_assessment_runner.resume(
            str(pause_token),
            answer,
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
        try:
            for update in updates:
                if isinstance(update, TargetAssessmentProgress):
                    last_progress_status = update.status
                    if update.status == "paused":
                        pending_question = str((update.detail or {}).get("question") or "")
                        pause_detail = update.detail or {}
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
        artifact.specialist_runs = list(result.specialist_runs) if effective_status == "completed" else []
        artifact.synthesis = result.synthesis if effective_status == "completed" else ""
        artifact.pending_specialist_runs = None
        artifact.pending_synthesis = None
        artifact.pending_proposed_edits = None
        artifact.judge = result.judge
        artifact.correction = result.correction
        artifact.error = effective_error
        artifact.execution_policy = result.execution_policy
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
        resume_text = self._owned_resume(owner_id, thread.resume_version_id).resume_text or ""
        return [
            {
                "id": edit.id,
                "block_id": edit.block_id,
                "section_key": edit.section_key,
                "entry_id": edit.entry_id,
                "original": edit.original,
                "rewrite": edit.rewrite,
                "status": edit.status,
                "applicable": bool(edit.original) and edit.original in resume_text,
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
        thread = self._owned_thread(owner_id, thread_id)
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
        applied: list[str] = []
        stale: list[str] = []
        for edit in edits:
            if edit.original and edit.original in text:
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
        thread = self._owned_thread(owner_id, thread_id)
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
        )
