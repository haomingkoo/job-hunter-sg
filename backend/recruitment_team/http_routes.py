"""Thin FastAPI transport for the recruitment-team module interface."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from auth import get_current_user
from database import get_db
from models import User

from .conversation_model import ConversationModel
from .coordinator.model import DeepAgentConversationModel
from .candidate_profile import (
    CandidateProfilerFactory,
    LangChainCandidateProfilerFactory,
)
from .discovery import DiscoveryPort, LangChainJobDiscovery
from .activity_publisher import IgnoreActivityPublisher
from .assessed_role_success import EvidenceAssessedRoleSuccessProfiler
from .activity_stream import stream_command, stream_retry, stream_run
from .errors import (
    DiscoveryUnavailable,
    InvalidCommand,
    ResumeVersionNotFound,
    RunConcurrencyExceeded,
    ServiceUnavailable,
    ThreadNotFound,
)
from .interface import (
    AnswerAssessmentQuestion,
    BuildCandidateProfile,
    HideJob,
    AssessTargetJob,
    SearchJobs,
    SelectTargetJob,
    SendMessage,
    ShortlistJob,
    StartThread,
)
from .recruitment_team import RecruitmentTeam, THREAD_TITLE_MAX_CHARS
from .role_success import LangChainRoleDefinitionGenerator, RoleSuccessProfiler
from .role_evidence_assessor import LangChainRoleEvidenceAssessor
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from .assessment_contracts import TargetAssessmentRunner
from .open_agent.runner import OpenAgentTargetAssessmentRunner, delete_checkpoint
from .study import dispatch_resume_study
from resume_agent.models import ResumeAgentConfigurationError


router = APIRouter(prefix="/api/recruitment-team", tags=["recruitment-team"])

IDEMPOTENCY_KEY_MAX_CHARS = 200
SEARCH_QUERY_MAX_CHARS = 500
PROPOSED_EDIT_ACTION_MAX_ITEMS = 100
JOB_FEEDBACK_REASON_MAX_CHARS = 500
RECRUITMENT_MESSAGE_MAX_CHARS = 10_000
SSE_HEADERS = {"Cache-Control": "no-store"}


class StartThreadRequest(BaseModel):
    resume_version_id: int
    message: str = Field(min_length=1, max_length=RECRUITMENT_MESSAGE_MAX_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=RECRUITMENT_MESSAGE_MAX_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class SearchJobsRequest(BaseModel):
    """Omit query to search from what the candidate has already said."""

    query: str = Field(default="", max_length=SEARCH_QUERY_MAX_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class JobActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class JobFeedbackRequest(BaseModel):
    scope: Literal["role", "company"]
    reason: str = Field(default="", max_length=JOB_FEEDBACK_REASON_MAX_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class AnswerAssessmentQuestionRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=RECRUITMENT_MESSAGE_MAX_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class ProposedEditActionRequest(BaseModel):
    """Omit edit_ids on accept to take every pending edit."""

    edit_ids: list[str] | None = Field(default=None, max_length=PROPOSED_EDIT_ACTION_MAX_ITEMS)
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class RenameThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=THREAD_TITLE_MAX_CHARS)


class DeleteThreadRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


def get_recruitment_telemetry() -> RecruitmentTelemetry:
    return OpenTelemetryRecorder()


def get_conversation_model(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> ConversationModel:
    # The discovery port arrives on the ConversationContext RecruitmentTeam
    # builds per turn, so this needs no Depends(get_job_discovery).
    try:
        return DeepAgentConversationModel(telemetry=telemetry)
    except ResumeAgentConfigurationError:
        _raise_model_configuration_error()


def get_job_discovery() -> DiscoveryPort:
    return LangChainJobDiscovery()


def get_role_success_profiler(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> RoleSuccessProfiler:
    try:
        return EvidenceAssessedRoleSuccessProfiler(
            LangChainRoleDefinitionGenerator(telemetry=telemetry),
            LangChainRoleEvidenceAssessor(telemetry=telemetry),
        )
    except ResumeAgentConfigurationError:
        _raise_model_configuration_error()


def get_candidate_profiler_factory(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> CandidateProfilerFactory:
    try:
        return LangChainCandidateProfilerFactory(telemetry=telemetry)
    except ResumeAgentConfigurationError:
        _raise_model_configuration_error()


def _raise_model_configuration_error():
    raise HTTPException(status_code=503, detail="AI service is not configured.") from None


def get_study_profiler_provider(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    """Delay model construction until the background study has started."""
    return lambda: get_candidate_profiler_factory(telemetry)


def _automatic_study_dispatcher(db: Session, telemetry, profiler_provider):
    bind = db.get_bind()
    if bind.dialect.name == "sqlite" and not bind.url.database:
        return None
    study_sessions = sessionmaker(bind=bind, expire_on_commit=False)
    return lambda owner_id, resume_id, thread_id, activity_publisher=None: dispatch_resume_study(
        study_sessions,
        owner_id=owner_id,
        resume_version_id=resume_id,
        thread_id=thread_id,
        profiler_factory_provider=profiler_provider,
        telemetry=telemetry,
        activity_publisher=activity_publisher,
    )


def get_target_assessment_runner(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> TargetAssessmentRunner:
    return OpenAgentTargetAssessmentRunner(telemetry=telemetry)


def _team(
    db: Session,
    conversation_model: ConversationModel,
    discovery: DiscoveryPort,
    role_profiler: RoleSuccessProfiler,
    telemetry: RecruitmentTelemetry,
    candidate_profiler_factory: CandidateProfilerFactory | None = None,
    target_assessment_runner: TargetAssessmentRunner | None = None,
    study_dispatcher=None,
) -> RecruitmentTeam:
    return RecruitmentTeam(
        db,
        conversation_model,
        discovery,
        role_profiler,
        telemetry,
        IgnoreActivityPublisher(),
        candidate_profiler_factory,
        target_assessment_runner,
        study_dispatcher,
    )


def _read_team(db: Session, telemetry: RecruitmentTelemetry) -> RecruitmentTeam:
    """Build a read-only team with no model dependencies."""
    return RecruitmentTeam(db, None, None, None, telemetry, IgnoreActivityPublisher())


def _streaming_read_team_factory(db: Session, telemetry: RecruitmentTelemetry):
    return lambda activity_publisher: RecruitmentTeam(
        db,
        None,
        None,
        None,
        telemetry,
        activity_publisher,
    )


def _streaming_team_factory(
    db: Session,
    conversation_model: ConversationModel,
    discovery: DiscoveryPort,
    role_profiler: RoleSuccessProfiler,
    telemetry: RecruitmentTelemetry,
    candidate_profiler_factory: CandidateProfilerFactory | None = None,
    target_assessment_runner: TargetAssessmentRunner | None = None,
    study_dispatcher=None,
):
    def create(activity_publisher):
        visible_study_dispatcher = (
            (
                lambda owner_id, resume_id, thread_id: study_dispatcher(
                    owner_id,
                    resume_id,
                    thread_id,
                    activity_publisher,
                )
            )
            if study_dispatcher is not None
            else None
        )
        return RecruitmentTeam(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            activity_publisher,
            candidate_profiler_factory,
            target_assessment_runner,
            visible_study_dispatcher,
        )

    return create


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, (ThreadNotFound, ResumeVersionNotFound)):
        raise HTTPException(status_code=404, detail=str(error)) from None
    if isinstance(error, InvalidCommand):
        raise HTTPException(status_code=422, detail=str(error)) from None
    if isinstance(error, RunConcurrencyExceeded):
        raise HTTPException(status_code=429, detail=str(error)) from None
    if isinstance(error, (DiscoveryUnavailable, ServiceUnavailable)):
        raise HTTPException(status_code=503, detail=str(error)) from None
    raise error


def _execute_command(team: RecruitmentTeam, owner_id: int, command: Any, idempotency_key: str):
    """Adapt one domain command to the shared JSON/error transport contract."""
    try:
        return asdict(team.execute(owner_id, command, idempotency_key))
    except Exception as error:
        _raise_http_error(error)


def _stream_command_response(
    team_factory,
    owner_id: int,
    command: Any,
    idempotency_key: str,
) -> StreamingResponse:
    """Adapt one domain command to the shared SSE transport contract."""
    return StreamingResponse(
        stream_command(team_factory, owner_id, command, idempotency_key),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/threads", status_code=status.HTTP_201_CREATED)
def start_thread(
    body: StartThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    study_profiler_provider=Depends(get_study_profiler_provider),
):
    study_dispatcher = _automatic_study_dispatcher(db, telemetry, study_profiler_provider)
    return _execute_command(
        _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            study_dispatcher=study_dispatcher,
        ),
        user.id,
        StartThread(resume_version_id=body.resume_version_id, message=body.message),
        body.idempotency_key,
    )


@router.post("/threads/stream")
def stream_start_thread(
    body: StartThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    study_profiler_provider=Depends(get_study_profiler_provider),
):
    study_dispatcher = _automatic_study_dispatcher(db, telemetry, study_profiler_provider)
    command = StartThread(
        resume_version_id=body.resume_version_id,
        message=body.message,
    )
    return _stream_command_response(
        _streaming_team_factory(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            study_dispatcher=study_dispatcher,
        ),
        user.id,
        command,
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/messages")
def send_message(
    thread_id: str,
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _execute_command(
        _team(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        SendMessage(thread_id=thread_id, message=body.message),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/runs/{run_id}/retry")
def retry_conversation_run(
    thread_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    try:
        return asdict(
            _team(
                db,
                conversation_model,
                discovery,
                role_profiler,
                telemetry,
                target_assessment_runner=target_assessment_runner,
            ).retry_conversation_run(
                user.id,
                thread_id,
                run_id,
            )
        )
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/runs/{run_id}/retry/stream")
def stream_retry_conversation_run(
    thread_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    return StreamingResponse(
        stream_retry(
            _streaming_team_factory(
                db,
                conversation_model,
                discovery,
                role_profiler,
                telemetry,
                target_assessment_runner=target_assessment_runner,
            ),
            user.id,
            thread_id,
            run_id,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/threads/{thread_id}/candidate-profile")
def build_candidate_profile(
    thread_id: str,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    candidate_profiler_factory: CandidateProfilerFactory = Depends(get_candidate_profiler_factory),
):
    return _execute_command(
        _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            candidate_profiler_factory,
        ),
        user.id,
        BuildCandidateProfile(thread_id=thread_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/candidate-profile/stream")
def stream_candidate_profile(
    thread_id: str,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    candidate_profiler_factory: CandidateProfilerFactory = Depends(get_candidate_profiler_factory),
):
    return _stream_command_response(
        _streaming_team_factory(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            candidate_profiler_factory,
        ),
        user.id,
        BuildCandidateProfile(thread_id=thread_id),
        body.idempotency_key,
    )


@router.get("/threads/{thread_id}/candidate-profile")
def get_candidate_profile(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        artifact = _read_team(db, telemetry).candidate_profile(user.id, thread_id)
        return asdict(artifact) if artifact is not None else None
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/assessment")
def assess_target_job(
    thread_id: str,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    return _execute_command(
        _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            target_assessment_runner=target_assessment_runner,
        ),
        user.id,
        AssessTargetJob(thread_id=thread_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/assessment/stream")
def stream_target_assessment(
    thread_id: str,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    return _stream_command_response(
        _streaming_team_factory(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            target_assessment_runner=target_assessment_runner,
        ),
        user.id,
        AssessTargetJob(thread_id=thread_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/assessment/answer")
def answer_assessment_question(
    thread_id: str,
    body: AnswerAssessmentQuestionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    return _execute_command(
        _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            target_assessment_runner=target_assessment_runner,
        ),
        user.id,
        AnswerAssessmentQuestion(thread_id=thread_id, answer=body.answer),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/assessment/answer/stream")
def stream_answer_assessment_question(
    thread_id: str,
    body: AnswerAssessmentQuestionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    target_assessment_runner: TargetAssessmentRunner = Depends(get_target_assessment_runner),
):
    return _stream_command_response(
        _streaming_team_factory(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            target_assessment_runner=target_assessment_runner,
        ),
        user.id,
        AnswerAssessmentQuestion(thread_id=thread_id, answer=body.answer),
        body.idempotency_key,
    )


@router.get("/threads/{thread_id}/assessment")
def get_target_assessment(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        artifact = _read_team(db, telemetry).target_assessment(user.id, thread_id)
        return asdict(artifact) if artifact is not None else None
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/messages/stream")
def stream_send_message(
    thread_id: str,
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    command = SendMessage(thread_id=thread_id, message=body.message)
    return _stream_command_response(
        _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        command,
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/search")
def search_thread_jobs(
    thread_id: str,
    body: SearchJobsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _execute_command(
        _team(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        SearchJobs(thread_id=thread_id, query=body.query),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/search/stream")
def stream_search_thread_jobs(
    thread_id: str,
    body: SearchJobsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _stream_command_response(
        _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        SearchJobs(thread_id=thread_id, query=body.query),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/shortlist")
def shortlist_thread_job(
    thread_id: str,
    job_id: int,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _execute_command(
        _read_team(db, telemetry),
        user.id,
        ShortlistJob(thread_id=thread_id, job_id=job_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/shortlist/stream")
def stream_shortlist_thread_job(
    thread_id: str,
    job_id: int,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _stream_command_response(
        _streaming_read_team_factory(db, telemetry),
        user.id,
        ShortlistJob(thread_id=thread_id, job_id=job_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/feedback/stream")
def stream_job_feedback(
    thread_id: str,
    job_id: int,
    body: JobFeedbackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _stream_command_response(
        _streaming_read_team_factory(db, telemetry),
        user.id,
        HideJob(
            thread_id=thread_id,
            job_id=job_id,
            scope=body.scope,
            reason=body.reason,
        ),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/select")
def select_thread_target(
    thread_id: str,
    job_id: int,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _execute_command(
        _team(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        SelectTargetJob(thread_id=thread_id, job_id=job_id),
        body.idempotency_key,
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/select/stream")
def stream_select_thread_target(
    thread_id: str,
    job_id: int,
    body: JobActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return _stream_command_response(
        _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
        user.id,
        SelectTargetJob(thread_id=thread_id, job_id=job_id),
        body.idempotency_key,
    )


@router.get("/threads")
def list_threads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return [
        asdict(thread) for thread in _read_team(db, telemetry).threads(user.id)
    ]


@router.get("/retention")
def get_retention_contract(
    _user: User = Depends(get_current_user),
):
    return RecruitmentTeam.retention_contract()


@router.patch("/threads/{thread_id}")
def rename_thread(
    thread_id: str,
    body: RenameThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _read_team(db, telemetry).rename_thread(user.id, thread_id, body.title)
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/archive")
def archive_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _read_team(db, telemetry).archive_thread(user.id, thread_id)
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/restore")
def restore_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _read_team(db, telemetry).restore_thread(user.id, thread_id)
    except Exception as error:
        _raise_http_error(error)


@router.delete("/threads/{thread_id}")
def delete_thread(
    thread_id: str,
    body: DeleteThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _read_team(db, telemetry).delete_thread(
            user.id,
            thread_id,
            body.idempotency_key,
            delete_checkpoints=delete_checkpoint,
        )
    except Exception as error:
        _raise_http_error(error)


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return asdict(
            _read_team(db, telemetry).snapshot(
                user.id,
                thread_id,
            )
        )
    except Exception as error:
        _raise_http_error(error)


@router.get("/threads/{thread_id}/events")
def get_thread_events(
    thread_id: str,
    after_sequence: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return [
            asdict(event)
            for event in _read_team(db, telemetry).events(
                user.id,
                thread_id,
                after_sequence,
            )
        ]
    except Exception as error:
        _raise_http_error(error)


@router.get("/runs/{run_id}/stream")
def reattach_run(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    team = _read_team(db, telemetry)
    try:
        # Validate ownership before response headers are sent, so missing and
        # other-user run IDs remain the same non-disclosing 404.
        team.run_replay(user.id, run_id, after_sequence)
    except Exception as error:
        _raise_http_error(error)
    return StreamingResponse(
        stream_run(team, user.id, run_id, after_sequence),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/threads/{thread_id}/proposed-edits")
def list_proposed_edits(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _read_team(db, telemetry).proposed_edits(
            user.id,
            thread_id,
        )
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/proposed-edits/accept")
def accept_proposed_edits(
    thread_id: str,
    body: ProposedEditActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _team(
            db, conversation_model, discovery, role_profiler, telemetry
        ).accept_proposed_edits(user.id, thread_id, body.edit_ids)
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/{thread_id}/proposed-edits/reject")
def reject_proposed_edits(
    thread_id: str,
    body: ProposedEditActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return _team(
            db, conversation_model, discovery, role_profiler, telemetry
        ).reject_proposed_edits(user.id, thread_id, body.edit_ids or [])
    except Exception as error:
        _raise_http_error(error)
