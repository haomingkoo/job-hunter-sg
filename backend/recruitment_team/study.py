"""Resume-version-scoped candidate study, independent of conversation locks."""

from __future__ import annotations

import hashlib
import json
import logging
from threading import Thread
import uuid

from sqlalchemy.orm import Session

from models import CandidateProfileArtifact, RecruitmentRun, RecruitmentThread, ResumeVersion
from resume_document import SCHEMA_VERSION, create_resume_document

from .candidate_profile import (
    candidate_profile_execution_policy,
    CandidateProfileProgress,
    CandidateProfileProgressPublisher,
    CandidateProfilerFactory,
    candidate_profile_progress_event,
)
from .candidate_profile_store import (
    SQLAlchemyCandidateProfileStore,
    candidate_profile_artifact_is_current,
)
from .prompts import CANDIDATE_PROFILE_PROMPT_VERSION
from .candidate_profile import CANDIDATE_PROFILE_DECOMPOSITION_VERSION
from .telemetry import RecruitmentTelemetry
from .activity_publisher import ActivityPublisher
from . import activity_events


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


def _study_idempotency_key(resume_version_id: int, model_name: str) -> str:
    identity = json.dumps(
        {
            "model": model_name,
            "execution_policy": candidate_profile_execution_policy(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"study:{resume_version_id}:{hashlib.sha256(identity.encode()).hexdigest()}"


def _link_completed_profile(
    thread: RecruitmentThread,
    resume_version_id: int,
    artifact: CandidateProfileArtifact,
) -> None:
    if thread.resume_version_id != resume_version_id:
        return
    facts = dict(thread.case_facts or {})
    facts["candidate_profile_artifact_id"] = artifact.id
    facts["candidate_profile_status"] = "completed"
    thread.case_facts = facts


def study_resume_version(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    profiler_factory: CandidateProfilerFactory,
    telemetry: RecruitmentTelemetry,
    progress_publisher: CandidateProfileProgressPublisher | None = None,
    trace_key: str = "",
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
    if cached is not None and candidate_profile_artifact_is_current(cached):
        return cached
    store = SQLAlchemyCandidateProfileStore(
        db,
        owner_id=owner_id,
        resume_version_id=resume.id,
        model_name=profiler_factory.model_name,
    )
    run = profiler_factory.create(store, progress_publisher).profile(document)
    store.merge_execution_metrics(run.checkpoint_id, {
        "logical_run_id": run.checkpoint_id,
        "trace_key": trace_key,
        "stage": "candidate_profile",
        "terminal_status": "completed",
    })
    return store.complete(run.checkpoint_id, run.profile, run.evaluation)


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
    with activity_events.thread_lock(thread.id):
        event = activity_events.create_record(
            db,
            thread=thread,
            run=run,
            event_type="candidate_profile",
            status=status,
            team_member="candidate_profiler",
            summary=summary,
            detail=detail,
        )
        db.commit()
        if activity_publisher is not None:
            activity_publisher.publish(activity_events.to_activity_event(event))


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
            db_context = session_factory()
            with db_context as db:
                try:
                    profiler_factory = profiler_factory_provider()
                except Exception as error:
                    log.exception(
                        "automatic candidate study provider could not start for resume %s",
                        resume_version_id,
                    )
                    _record_study_startup_failure(
                        db,
                        owner_id=owner_id,
                        resume_version_id=resume_version_id,
                        thread_id=thread_id,
                        error=error,
                        activity_publisher=activity_publisher,
                    )
                    return
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


def _record_study_startup_failure(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    thread_id: str,
    error: Exception,
    activity_publisher: ActivityPublisher | None,
) -> None:
    """Make provider/configuration startup failures durable and user-visible."""
    thread = db.query(RecruitmentThread).filter_by(id=thread_id, user_id=owner_id).one()
    key = f"study-startup:{resume_version_id}:{CANDIDATE_PROFILE_PROMPT_VERSION}"
    run = db.query(RecruitmentRun).filter_by(user_id=owner_id, idempotency_key=key).first()
    if run is None:
        run_id = str(uuid.uuid4())
        run = RecruitmentRun(
            id=run_id,
            user_id=owner_id,
            thread_id=thread.id,
            idempotency_key=key,
            command_type="study_resume_version",
            status="failed",
            trace_key=hashlib.sha256(run_id.encode()).hexdigest()[:32],
        )
        db.add(run)
    run.status = "failed"
    run.error_type = type(error).__name__
    facts = dict(thread.case_facts or {})
    facts["candidate_profile_status"] = "failed"
    thread.case_facts = facts
    db.commit()
    _record_event(
        db,
        thread=thread,
        run=run,
        status="failed",
        summary="The candidate profiler could not start the resume study.",
        detail={
            "failure_type": "configuration",
            "failure_code": "provider_startup_failed",
            "error_type": type(error).__name__,
            "retryable": True,
            "recovery_action": "retry_incomplete_stage",
        },
        activity_publisher=activity_publisher,
    )


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
    from .run_lease import reconcile_expired_runs

    thread = db.query(RecruitmentThread).filter_by(id=thread_id, user_id=owner_id).one()
    reconcile_expired_runs(db, thread_id=thread_id)
    db.commit()
    cached = _completed_artifact(
        db,
        owner_id=owner_id,
        resume_version_id=resume_version_id,
        profiler_factory=profiler_factory,
    )
    if cached is not None and candidate_profile_artifact_is_current(cached):
        _link_completed_profile(thread, resume_version_id, cached)
        db.commit()
        return

    key = _study_idempotency_key(resume_version_id, profiler_factory.model_name)
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
    else:
        run.status = "running"
        run.error_type = None
        run.result = None
        db.commit()

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
        def publish_progress(progress: CandidateProfileProgress) -> None:
            status, summary, detail = candidate_profile_progress_event(progress)
            _record_event(
                db,
                thread=thread,
                run=run,
                status=status,
                summary=summary,
                detail=detail,
                activity_publisher=activity_publisher,
            )

        artifact = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_version_id,
            profiler_factory=profiler_factory,
            telemetry=telemetry,
            progress_publisher=publish_progress,
            trace_key=run.trace_key,
        )
        db.refresh(thread)
        _link_completed_profile(thread, resume_version_id, artifact)
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
