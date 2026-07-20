"""Thin FastAPI transport for the recruitment-team module interface."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import User

from .conversation_model import ConversationModel, LangChainConversationModel
from .candidate_profile import (
    CandidateProfilerFactory,
    LangChainCandidateProfilerFactory,
)
from .discovery import DiscoveryPort, LangChainJobDiscovery
from .activity_publisher import IgnoreActivityPublisher
from .assessed_role_success import EvidenceAssessedRoleSuccessProfiler
from .activity_stream import stream_command
from .errors import (
    CandidateProfilingUnavailable,
    DiscoveryUnavailable,
    InvalidCommand,
    ResumeVersionNotFound,
    RoleProfilingUnavailable,
    ThreadNotFound,
    TargetAssessmentUnavailable,
)
from .interface import (
    BuildCandidateProfile,
    AssessTargetJob,
    SearchJobs,
    SelectTargetJob,
    SendMessage,
    ShortlistJob,
    StartThread,
)
from .recruitment_team import RecruitmentTeam
from .role_success import LangChainRoleDefinitionGenerator, RoleSuccessProfiler
from .role_evidence_assessor import LangChainRoleEvidenceAssessor
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from .assessment_contracts import TargetAssessmentRunner
from .open_agent.runner import OpenAgentTargetAssessmentRunner


router = APIRouter(prefix="/api/recruitment-team", tags=["recruitment-team"])


class StartThreadRequest(BaseModel):
    resume_version_id: int
    message: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SearchJobsRequest(BaseModel):
    query: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class JobActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


def get_recruitment_telemetry() -> RecruitmentTelemetry:
    return OpenTelemetryRecorder()


def get_conversation_model(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> ConversationModel:
    return LangChainConversationModel(telemetry=telemetry)


def get_job_discovery() -> DiscoveryPort:
    return LangChainJobDiscovery()


def get_role_success_profiler(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> RoleSuccessProfiler:
    return EvidenceAssessedRoleSuccessProfiler(
        LangChainRoleDefinitionGenerator(telemetry=telemetry),
        LangChainRoleEvidenceAssessor(telemetry=telemetry),
    )


def get_candidate_profiler_factory(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> CandidateProfilerFactory:
    return LangChainCandidateProfilerFactory(telemetry=telemetry)


def get_target_assessment_runner() -> TargetAssessmentRunner:
    return OpenAgentTargetAssessmentRunner()


def _team(
    db: Session,
    conversation_model: ConversationModel,
    discovery: DiscoveryPort,
    role_profiler: RoleSuccessProfiler,
    telemetry: RecruitmentTelemetry,
    candidate_profiler_factory: CandidateProfilerFactory | None = None,
    target_assessment_runner: TargetAssessmentRunner | None = None,
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
    )


def _streaming_team_factory(
    db: Session,
    conversation_model: ConversationModel,
    discovery: DiscoveryPort,
    role_profiler: RoleSuccessProfiler,
    telemetry: RecruitmentTelemetry,
    candidate_profiler_factory: CandidateProfilerFactory | None = None,
    target_assessment_runner: TargetAssessmentRunner | None = None,
):
    def create(activity_publisher):
        return RecruitmentTeam(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
            activity_publisher,
            candidate_profiler_factory,
            target_assessment_runner,
        )

    return create


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, (ThreadNotFound, ResumeVersionNotFound)):
        raise HTTPException(status_code=404, detail=str(error)) from None
    if isinstance(error, InvalidCommand):
        raise HTTPException(status_code=422, detail=str(error)) from None
    if isinstance(
        error,
        (
            CandidateProfilingUnavailable,
            DiscoveryUnavailable,
            RoleProfilingUnavailable,
            TargetAssessmentUnavailable,
        ),
    ):
        raise HTTPException(status_code=503, detail=str(error)) from None
    raise error


@router.post("/threads", status_code=status.HTTP_201_CREATED)
def start_thread(
    body: StartThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).execute(
                user.id,
                StartThread(
                    resume_version_id=body.resume_version_id,
                    message=body.message,
                ),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


@router.post("/threads/stream")
def stream_start_thread(
    body: StartThreadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    command = StartThread(
        resume_version_id=body.resume_version_id,
        message=body.message,
    )
    return StreamingResponse(
        stream_command(
            _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
            user.id,
            command,
            body.idempotency_key,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
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
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).execute(
                user.id,
                SendMessage(thread_id=thread_id, message=body.message),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


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
    try:
        return asdict(
            _team(
                db,
                conversation_model,
                discovery,
                role_profiler,
                telemetry,
                candidate_profiler_factory,
            ).execute(
                user.id,
                BuildCandidateProfile(thread_id=thread_id),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


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
    return StreamingResponse(
        stream_command(
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
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/threads/{thread_id}/candidate-profile")
def get_candidate_profile(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        artifact = _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
        ).candidate_profile(user.id, thread_id)
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
    try:
        return asdict(
            _team(
                db,
                conversation_model,
                discovery,
                role_profiler,
                telemetry,
                target_assessment_runner=target_assessment_runner,
            ).execute(
                user.id,
                AssessTargetJob(thread_id=thread_id),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


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
    return StreamingResponse(
        stream_command(
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
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/threads/{thread_id}/assessment")
def get_target_assessment(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        artifact = _team(
            db,
            conversation_model,
            discovery,
            role_profiler,
            telemetry,
        ).target_assessment(user.id, thread_id)
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
    return StreamingResponse(
        stream_command(
            _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
            user.id,
            command,
            body.idempotency_key,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
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
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).execute(
                user.id,
                SearchJobs(thread_id=thread_id, query=body.query),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


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
    return StreamingResponse(
        stream_command(
            _streaming_team_factory(db, conversation_model, discovery, role_profiler, telemetry),
            user.id,
            SearchJobs(thread_id=thread_id, query=body.query),
            body.idempotency_key,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/threads/{thread_id}/jobs/{job_id}/shortlist")
def shortlist_thread_job(
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
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).execute(
                user.id,
                ShortlistJob(thread_id=thread_id, job_id=job_id),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


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
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).execute(
                user.id,
                SelectTargetJob(thread_id=thread_id, job_id=job_id),
                body.idempotency_key,
            )
        )
    except Exception as error:
        _raise_http_error(error)


@router.get("/threads")
def list_threads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    return [
        asdict(thread) for thread in _team(db, conversation_model, discovery, role_profiler, telemetry).threads(user.id)
    ]


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return asdict(
            _team(db, conversation_model, discovery, role_profiler, telemetry).snapshot(
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
    conversation_model: ConversationModel = Depends(get_conversation_model),
    discovery: DiscoveryPort = Depends(get_job_discovery),
    role_profiler: RoleSuccessProfiler = Depends(get_role_success_profiler),
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
):
    try:
        return [
            asdict(event)
            for event in _team(db, conversation_model, discovery, role_profiler, telemetry).events(
                user.id,
                thread_id,
                after_sequence,
            )
        ]
    except Exception as error:
        _raise_http_error(error)
