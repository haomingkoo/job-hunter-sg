"""Resume-version-scoped candidate study, independent of conversation locks."""

from __future__ import annotations

import hashlib
import logging
from threading import Thread
import uuid

from sqlalchemy.orm import Session

from models import (
    CandidateProfileArtifact,
    RecruitmentActivityEvent,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
)
from resume_document import SCHEMA_VERSION, create_resume_document

from .candidate_profile import CandidateProfilerFactory, candidate_profile_execution_policy
from .candidate_profile_store import SQLAlchemyCandidateProfileStore
from .prompts import CANDIDATE_PROFILE_PROMPT_VERSION
from .candidate_profile import CANDIDATE_PROFILE_DECOMPOSITION_VERSION
from .telemetry import RecruitmentTelemetry
from .activity_publisher import ActivityPublisher


log = logging.getLogger("jobhunter.recruitment_team.study")


def _completed_artifact(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    profiler_factory: CandidateProfilerFactory,
) -> CandidateProfileArtifact | None:
    artifacts = (
        db.query(CandidateProfileArtifact)
        .filter(
            CandidateProfileArtifact.user_id == owner_id,
            CandidateProfileArtifact.resume_version_id == resume_version_id,
            CandidateProfileArtifact.status == "completed",
            CandidateProfileArtifact.prompt_version == CANDIDATE_PROFILE_PROMPT_VERSION,
            CandidateProfileArtifact.decomposition_version == CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
            CandidateProfileArtifact.model_name == profiler_factory.model_name,
        )
        .order_by(CandidateProfileArtifact.updated_at.desc())
        .all()
    )
    return artifacts[0] if artifacts else None


def study_resume_version(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    profiler_factory: CandidateProfilerFactory,
    telemetry: RecruitmentTelemetry,
) -> CandidateProfileArtifact:
    """Build or reuse the current evidence profile for one immutable resume."""
    resume = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == resume_version_id,
            ResumeVersion.user_id == owner_id,
            ResumeVersion.is_active.is_(True),
        )
        .one()
    )
    document = resume.resume_structured
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SCHEMA_VERSION
        or document.get("raw_text") != resume.resume_text
    ):
        document = create_resume_document(resume.resume_text)
        resume.resume_structured = document
        db.commit()
    cached = _completed_artifact(
        db,
        owner_id=owner_id,
        resume_version_id=resume_version_id,
        profiler_factory=profiler_factory,
    )
    if cached is not None and cached.execution_policy == candidate_profile_execution_policy():
        return cached
    store = SQLAlchemyCandidateProfileStore(
        db,
        owner_id=owner_id,
        resume_version_id=resume.id,
        model_name=profiler_factory.model_name,
    )
    run = profiler_factory.create(store).profile(document)
    return store.complete(run.checkpoint_id, run.profile)


def _record_event(
    db: Session,
    *,
    thread: RecruitmentThread,
    run: RecruitmentRun,
    status: str,
    summary: str,
    detail: dict | None = None,
    activity_publisher: ActivityPublisher | None = None,
) -> None:
    from .recruitment_team import RecruitmentTeam, _reserve_event_sequence, _thread_lock

    with _thread_lock(thread.id):
        sequence = _reserve_event_sequence(db, thread.id)
        event = RecruitmentActivityEvent(
            thread_id=thread.id,
            run_id=run.id,
            sequence=sequence,
            event_type="candidate_profile",
            status=status,
            team_member="candidate_profiler",
            attempt=1,
            trace_key=run.trace_key,
            summary=summary,
            detail=detail or {},
        )
        db.add(event)
        db.commit()
        if activity_publisher is not None:
            activity_publisher.publish(RecruitmentTeam._activity(event))


def dispatch_resume_study(
    session_factory,
    *,
    owner_id: int,
    resume_version_id: int,
    thread_id: str,
    profiler_factory_provider,
    telemetry: RecruitmentTelemetry,
    activity_publisher: ActivityPublisher | None = None,
) -> Thread:
    """Start a daemon study whose model work never holds the thread lock."""

    def work() -> None:
        try:
            profiler_factory = profiler_factory_provider()
            db_context = session_factory()
            with db_context as db:
                _run_dispatched_study(
                    db,
                    owner_id=owner_id,
                    resume_version_id=resume_version_id,
                    thread_id=thread_id,
                    profiler_factory=profiler_factory,
                    telemetry=telemetry,
                    activity_publisher=activity_publisher,
                )
        except Exception:
            log.exception("automatic candidate study could not start for resume %s", resume_version_id)

    worker = Thread(target=work, name=f"resume-study-{resume_version_id}", daemon=True)
    worker.start()
    return worker


def _run_dispatched_study(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    thread_id: str,
    profiler_factory: CandidateProfilerFactory,
    telemetry: RecruitmentTelemetry,
    activity_publisher: ActivityPublisher | None = None,
) -> None:
    thread = db.query(RecruitmentThread).filter_by(id=thread_id, user_id=owner_id).one()
    key = f"study:{resume_version_id}:{profiler_factory.model_name}"
    run = db.query(RecruitmentRun).filter_by(user_id=owner_id, idempotency_key=key).first()
    if run is None:
        run_id = str(uuid.uuid4())
        run = RecruitmentRun(
            id=run_id,
            user_id=owner_id,
            thread_id=thread.id,
            idempotency_key=key,
            command_type="study_resume_version",
            status="running",
            trace_key=hashlib.sha256(run_id.encode()).hexdigest()[:32],
        )
        db.add(run)
        db.commit()
    elif run.status in {"running", "completed"}:
        return

    facts = dict(thread.case_facts or {})
    facts["candidate_profile_status"] = "running"
    thread.case_facts = facts
    db.commit()
    _record_event(
        db,
        thread=thread,
        run=run,
        status="running",
        summary="The candidate profiler is studying this resume.",
        activity_publisher=activity_publisher,
    )
    try:
        artifact = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_version_id,
            profiler_factory=profiler_factory,
            telemetry=telemetry,
        )
        db.refresh(thread)
        if thread.resume_version_id == resume_version_id:
            facts = dict(thread.case_facts or {})
            facts["candidate_profile_artifact_id"] = artifact.id
            facts["candidate_profile_status"] = "completed"
            thread.case_facts = facts
        run.status = "completed"
        run.result = {"candidate_profile_artifact_id": artifact.id}
        db.commit()
        _record_event(
            db,
            thread=thread,
            run=run,
            status="completed",
            summary="The candidate profiler completed the resume study.",
            detail={"candidate_profile_artifact_id": artifact.id},
            activity_publisher=activity_publisher,
        )
    except Exception as error:
        log.exception("automatic candidate study failed for resume %s", resume_version_id)
        db.refresh(thread)
        if thread.resume_version_id == resume_version_id:
            facts = dict(thread.case_facts or {})
            facts["candidate_profile_status"] = "failed"
            thread.case_facts = facts
        run.status = "failed"
        run.error_type = type(error).__name__
        db.commit()
        _record_event(
            db,
            thread=thread,
            run=run,
            status="failed",
            summary="The candidate profiler could not complete the resume study.",
            activity_publisher=activity_publisher,
        )
